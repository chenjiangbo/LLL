from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from broker_node.shared.db import connect
from broker_node.shared.order_types import GM_ORDER_TYPE_NAMES, validate_broker_order_type


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BrokerCommandExecutor:
    """Dispatches validated commands through the bound gm.api context."""

    def __init__(self, durable_db: Path):
        self.durable_db = durable_db

    def claim_next(self) -> dict[str, Any] | None:
        with connect(self.durable_db) as connection:
            # Keep the broker boundary single-flight.  A timer callback may
            # wake frequently, but it must never claim a second command while
            # the previous SDK call is still unresolved.
            in_flight = connection.execute(
                "SELECT 1 FROM commands WHERE status IN ('CLAIMED','DISPATCHING') LIMIT 1"
            ).fetchone()
            if in_flight:
                return None
            row = connection.execute(
                """
                SELECT c.*
                FROM commands c
                WHERE c.status='QUEUED'
                  AND (
                      c.error_code IS NULL
                      OR c.error_code <> 'WAITING_ORDER_LINK'
                      OR EXISTS (
                          SELECT 1 FROM order_links l
                          WHERE l.client_order_id=c.client_order_id
                            AND l.broker_order_id IS NOT NULL
                      )
                  )
                ORDER BY c.created_at
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            now = _now()
            updated = connection.execute(
                "UPDATE commands SET status='CLAIMED',claimed_at=?,updated_at=? WHERE command_id=? AND status='QUEUED'",
                (now, now, row["command_id"]),
            )
            if updated.rowcount != 1:
                return None
            return dict(row)

    def dispatch(self, command: dict[str, Any], account_id: str) -> Any:
        payload = json.loads(command["payload_json"])
        now = _now()
        self._set_status(command["command_id"], "DISPATCHING", now)
        sdk_call_started = False
        try:
            import gm.api as gm
            if command["command_type"] == "ORDER_SUBMIT":
                side = {"BUY": gm.OrderSide_Buy, "SELL": gm.OrderSide_Sell}[payload["side"]]
                effect = gm.PositionEffect_Open if payload["side"] == "BUY" else gm.PositionEffect_Close
                order_type = validate_broker_order_type(payload["exchange"], payload["order_type"])
                gm_order_type = getattr(gm, GM_ORDER_TYPE_NAMES[order_type])
                order_arguments = {}
                if payload.get("price") is not None:
                    order_arguments["price"] = float(Decimal(payload["price"]))
                sdk_call_started = True
                result = gm.order_volume(
                    f"{'SHSE' if payload['exchange'] == 'SH' else 'SZSE'}.{payload['code']}",
                    payload["quantity"],
                    side,
                    gm_order_type,
                    effect,
                    **order_arguments,
                )
            elif command["command_type"] == "ORDER_CANCEL":
                links = self._link_for(payload["client_order_id"])
                if not links or not links["broker_order_id"] or not links["broker_client_order_id"]:
                    # The broker can acknowledge a submit before its queried
                    # order record is visible. Keep the cancel queued until
                    # the authoritative sync creates the link; do not turn a
                    # timing dependency into a false permanent failure.
                    self._set_status(
                        command["command_id"],
                        "QUEUED",
                        _now(),
                        error_code="WAITING_ORDER_LINK",
                        error_message="broker order/client link is not visible yet",
                    )
                    return None
                sdk_call_started = True
                result = gm.order_cancel({"cl_ord_id": links["broker_client_order_id"], "account_id": account_id})
            else:
                raise RuntimeError(f"unsupported command type: {command['command_type']}")
            if command["command_type"] == "ORDER_SUBMIT":
                self._link_submitted_order(command, result)
            self._set_status(command["command_id"], "ACKED", _now())
        except Exception as exc:
            if sdk_call_started:
                # The SDK may have sent the command before raising. Preserve
                # the uncertain outcome and stop subsequent dispatches.
                with connect(self.durable_db) as connection:
                    connection.execute(
                        "UPDATE commands SET status='UNKNOWN',error_code='DISPATCH_UNKNOWN',error_message=?,updated_at=? WHERE command_id=?",
                        (str(exc), _now(), command["command_id"]),
                    )
                    connection.execute(
                        "UPDATE node_state SET execution_enabled=0,paused=1,reconciliation_required=1,pause_reason='RECONCILIATION_REQUIRED',updated_at=?",
                        (_now(),),
                    )
            else:
                self._set_status(command["command_id"], "FAILED_SAFE", _now(), error_code="DISPATCH_ERROR", error_message=str(exc))
            raise
        return result

    def _link_submitted_order(self, command: dict[str, Any], result: Any) -> None:
        order = result[0] if isinstance(result, (list, tuple)) and result else result
        if order is not None:
            get = (lambda key: order.get(key)) if isinstance(order, dict) else (lambda key: getattr(order, key, None))
            broker_order_id = get("order_id")
            broker_client_id = get("cl_ord_id")
            if broker_order_id and broker_client_id:
                self._insert_link(command, broker_client_id, broker_order_id, get("ex_ord_id"), get("status"))
                return

    def _insert_link(self, command: dict[str, Any], client_order_id: str, broker_order_id: str, exchange_order_id: str | None, raw_status: Any) -> None:
        with connect(self.durable_db) as connection:
            connection.execute(
                "INSERT INTO order_links(client_order_id,submit_command_id,broker_client_order_id,broker_order_id,exchange_order_id,last_broker_status,last_raw_status,origin,created_at,updated_at) VALUES(?,?,?,?,?,?,?, 'SYSTEM',?,?) ON CONFLICT(client_order_id) DO UPDATE SET submit_command_id=excluded.submit_command_id,broker_client_order_id=excluded.broker_client_order_id,broker_order_id=excluded.broker_order_id,exchange_order_id=excluded.exchange_order_id,last_raw_status=excluded.last_raw_status,updated_at=excluded.updated_at",
                (command["client_order_id"], command["command_id"], client_order_id, broker_order_id, exchange_order_id, None, raw_status, _now(), _now()),
            )

    def _link_for(self, client_order_id: str) -> dict[str, Any] | None:
        with connect(self.durable_db) as connection:
            row = connection.execute("SELECT * FROM order_links WHERE client_order_id=?", (client_order_id,)).fetchone()
        return dict(row) if row else None

    def _set_status(self, command_id: str, status: str, now: str, error_code: str | None = None, error_message: str | None = None) -> None:
        with connect(self.durable_db) as connection:
            connection.execute("UPDATE commands SET status=?,error_code=?,error_message=?,updated_at=? WHERE command_id=?", (status, error_code, error_message, now, command_id))
