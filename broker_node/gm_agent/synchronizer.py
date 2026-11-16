from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import json
from decimal import Decimal
from typing import Any, Callable

from broker_node.gm_agent.gm_adapter import GmContextAdapter
from broker_node.gm_agent.event_writer import EventWriter
from broker_node.gm_agent.gm_mapper import map_account, map_fill, map_order, map_position
from broker_node.gm_agent.order_linking import resolve_local_order_id
from broker_node.gm_agent.snapshot_writer import SnapshotWriter
from broker_node.shared.db import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_TERMINAL_ORDER_STATUSES = {"FILLED", "CANCELLED", "CANCELED", "REJECTED", "EXPIRED"}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class ReadonlySynchronizer:
    def __init__(self, adapter: GmContextAdapter, snapshots: SnapshotWriter, events: EventWriter):
        self.adapter = adapter
        self.snapshots = snapshots
        self.events = events

    def synchronize(self) -> dict[str, int]:
        account = map_account(self.adapter.cash())
        positions_raw = self.adapter.positions()
        orders_raw = self.adapter.orders()
        unfinished_raw = self.adapter.unfinished_orders()
        fills_raw = self.adapter.execution_reports()

        positions = [map_position(item) for item in positions_raw]
        orders = [self._map_and_resolve(map_order(item)) for item in orders_raw]
        unfinished_orders = [self._map_and_resolve(map_order(item)) for item in unfinished_raw]
        fills = [self._map_and_resolve(map_fill(item)) for item in fills_raw]

        # A query immediately following order_volume can legitimately lag the
        # callback stream.  Never let that weaker read-side response replace a
        # terminal callback fact already committed to the durable event log.
        # This is a merge of observed broker facts, not synthesized order or
        # position data: positions remain exactly what gm.api reports.
        durable_orders, durable_fills = self._durable_terminal_facts()
        orders = self._merge_terminal_orders(orders, durable_orders, "ORDERS")
        unfinished_orders = self._merge_terminal_orders(
            unfinished_orders, durable_orders, "UNFINISHED_ORDERS", allow_append=False
        )
        fills = self._merge_durable_fills(fills, durable_fills)

        # The broker may emit the order callback before order_volume returns.
        # Reconcile the authoritative order query into order_links as well, so
        # a subsequent cancel never depends on callback timing.
        with connect(self.snapshots.durable_db) as connection:
            for item in orders:
                normalized = item["normalized"]
                broker_client_order_id = normalized.get("client_order_id")
                client_order_id = broker_client_order_id
                broker_order_id = normalized.get("broker_order_id")
                if not client_order_id or not broker_order_id:
                    continue
                existing_link = connection.execute(
                    "SELECT client_order_id FROM order_links WHERE client_order_id=? OR broker_client_order_id=? OR broker_order_id=?",
                    (client_order_id, broker_client_order_id, broker_order_id),
                ).fetchone()
                if existing_link:
                    continue
                command = connection.execute(
                    "SELECT command_id FROM commands WHERE client_order_id=? AND command_type='ORDER_SUBMIT' ORDER BY created_at DESC LIMIT 1",
                    (client_order_id,),
                ).fetchone()
                # Guotou generates a broker cl_ord_id internally, so it does
                # not equal our client_order_id. Associate the queried broker
                # order with the one and only recent matching submit command.
                if not command:
                    order_created = datetime.fromisoformat(normalized["created_at"]) if normalized.get("created_at") else None
                    candidates = []
                    for candidate in connection.execute(
                        "SELECT * FROM commands WHERE command_type='ORDER_SUBMIT' AND status='ACKED' ORDER BY created_at DESC"
                    ):
                        payload = json.loads(candidate["payload_json"])
                        command_created = datetime.fromisoformat(candidate["created_at"])
                        if (
                            order_created is not None
                            and (order_created - command_created).total_seconds() >= 0
                            and (order_created - command_created).total_seconds() <= 30
                            and payload.get("code") == normalized["instrument"]["code"]
                            and payload.get("exchange") == normalized["instrument"]["exchange"]
                            and payload.get("side") == normalized["side"]
                            and Decimal(str(payload.get("price"))) == Decimal(str(normalized.get("price")))
                            and payload.get("quantity") == normalized.get("quantity")
                            and not connection.execute(
                                "SELECT 1 FROM order_links WHERE client_order_id=?", (candidate["client_order_id"],)
                            ).fetchone()
                        ):
                            candidates.append(candidate)
                    if len(candidates) > 1:
                        raise RuntimeError(
                            f"broker order could not be uniquely associated: candidates={len(candidates)}"
                        )
                    if not candidates:
                        continue
                    command = candidates[0]
                submit_command_id = command["command_id"]
                connection.execute(
                    """
                    INSERT INTO order_links(
                        client_order_id, submit_command_id, broker_client_order_id, broker_order_id,
                        exchange_order_id, last_broker_status, last_raw_status,
                        origin, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?, 'SYSTEM', ?, ?)
                    ON CONFLICT(client_order_id) DO UPDATE SET
                        submit_command_id=COALESCE(order_links.submit_command_id, excluded.submit_command_id),
                        broker_client_order_id=COALESCE(excluded.broker_client_order_id, order_links.broker_client_order_id),
                        broker_order_id=excluded.broker_order_id,
                        exchange_order_id=COALESCE(excluded.exchange_order_id, order_links.exchange_order_id),
                        last_broker_status=excluded.last_broker_status,
                        last_raw_status=excluded.last_raw_status,
                        updated_at=excluded.updated_at
                    """,
                    (
                        command["client_order_id"],
                        submit_command_id,
                        broker_client_order_id,
                        broker_order_id,
                        normalized.get("exchange_order_id"),
                        normalized.get("status"),
                        normalized.get("raw_status"),
                        _now(),
                        _now(),
                    ),
                )

        as_of = account["normalized"].get("as_of") or _now()
        self.snapshots.write("ACCOUNT", account, as_of)
        self.snapshots.write("POSITIONS", positions, as_of)
        self.snapshots.write("ORDERS", orders, as_of)
        self.snapshots.write("UNFINISHED_ORDERS", unfinished_orders, as_of)
        self.snapshots.write("FILLS", fills, as_of)
        self.events.append("ACCOUNT_SNAPSHOT_UPDATED", account, "QUERY", occurred_at=as_of)
        self.events.append("POSITION_SNAPSHOT_UPDATED", positions, "QUERY", occurred_at=as_of)
        self.events.append("ORDER_SNAPSHOT_UPDATED", orders, "QUERY", occurred_at=as_of)
        self.events.append("FILL_SNAPSHOT_UPDATED", fills, "QUERY", occurred_at=as_of)
        return {
            "positions": len(positions),
            "orders": len(orders),
            "unfinished_orders": len(unfinished_orders),
            "fills": len(fills),
        }

    def _durable_terminal_facts(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        """Read callback facts that a lagging GM query must not erase."""
        terminal_orders: dict[str, dict[str, Any]] = {}
        fills: list[dict[str, Any]] = []
        with connect(self.snapshots.durable_db) as connection:
            rows = connection.execute(
                """
                SELECT seq, event_type, client_order_id, broker_execution_id,
                       payload_json
                FROM broker_events
                WHERE event_type IN ('ORDER_STATUS', 'FILL')
                ORDER BY seq
                """
            ).fetchall()
        for row in rows:
            payload = json.loads(row["payload_json"])
            normalized = payload.get("normalized") if isinstance(payload, dict) else None
            if not isinstance(normalized, dict):
                continue
            if row["event_type"] == "ORDER_STATUS":
                status = str(normalized.get("status") or "").upper()
                local_id = str(row["client_order_id"] or normalized.get("client_order_id") or "").strip()
                if local_id and status in _TERMINAL_ORDER_STATUSES:
                    terminal_orders[local_id] = payload
            elif row["event_type"] == "FILL":
                fills.append(payload)
        return terminal_orders, fills

    @staticmethod
    def _same_order(left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_normalized = left.get("normalized", {})
        right_normalized = right.get("normalized", {})
        left_ids = {
            str(left_normalized.get(name)).strip()
            for name in ("client_order_id", "broker_client_order_id", "broker_order_id")
            if left_normalized.get(name)
        }
        right_ids = {
            str(right_normalized.get(name)).strip()
            for name in ("client_order_id", "broker_client_order_id", "broker_order_id")
            if right_normalized.get(name)
        }
        return bool(left_ids & right_ids)

    def _previous_snapshot_as_of(self, snapshot_type: str) -> datetime | None:
        with connect(self.snapshots.durable_db) as connection:
            row = connection.execute(
                "SELECT as_of FROM snapshots WHERE snapshot_type=?", (snapshot_type,)
            ).fetchone()
        return _parse_time(row["as_of"]) if row else None

    def _merge_terminal_orders(
        self,
        queried: list[dict[str, Any]],
        durable_orders: dict[str, dict[str, Any]],
        snapshot_type: str,
        *,
        allow_append: bool = True,
    ) -> list[dict[str, Any]]:
        result = [deepcopy(item) for item in queried]
        previous_as_of = self._previous_snapshot_as_of(snapshot_type)
        for local_id, durable in durable_orders.items():
            durable_normalized = durable.get("normalized", {})
            durable_time = _parse_time(
                durable_normalized.get("updated_at") or durable_normalized.get("created_at")
            )
            match_index = next(
                (index for index, item in enumerate(result) if self._same_order(item, durable)),
                None,
            )
            if match_index is None:
                if not allow_append:
                    continue
                # Keep the scope of a query snapshot: only add a callback fact
                # that arrived after the snapshot it is replacing.
                if previous_as_of is not None and durable_time is not None and durable_time <= previous_as_of:
                    continue
                result.append(deepcopy(durable))
                continue
            queried_item = result[match_index]
            if not allow_append:
                # The query still exposed a stale in-flight row, but the
                # durable callback has already made it terminal.  It must not
                # remain in the unfinished-order projection.
                result.pop(match_index)
                continue
            queried_normalized = queried_item.get("normalized", {})
            queried_status = str(queried_normalized.get("status") or "").upper()
            if queried_status not in _TERMINAL_ORDER_STATUSES or not queried_normalized.get("broker_order_id"):
                result[match_index] = {
                    **queried_item,
                    "normalized": {**queried_normalized, **durable_normalized},
                    "raw": durable.get("raw", queried_item.get("raw", {})),
                }
        return result

    def _merge_durable_fills(
        self, queried: list[dict[str, Any]], durable_fills: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        result = [deepcopy(item) for item in queried]
        previous_as_of = self._previous_snapshot_as_of("FILLS")
        existing_ids = {
            str(item.get("normalized", {}).get("broker_execution_id"))
            for item in result
            if item.get("normalized", {}).get("broker_execution_id")
        }
        for durable in durable_fills:
            normalized = durable.get("normalized", {})
            execution_id = str(normalized.get("broker_execution_id") or "").strip()
            occurred_at = _parse_time(normalized.get("occurred_at"))
            if not execution_id or execution_id in existing_ids:
                continue
            if previous_as_of is not None and occurred_at is not None and occurred_at <= previous_as_of:
                continue
            result.append(deepcopy(durable))
            existing_ids.add(execution_id)
        return result

    def _map_and_resolve(self, mapped: dict[str, Any]) -> dict[str, Any]:
        normalized = mapped["normalized"]
        broker_client_order_id = normalized.get("client_order_id")
        resolved = resolve_local_order_id(self.snapshots.durable_db, normalized)
        normalized["broker_client_order_id"] = broker_client_order_id
        if resolved:
            normalized["client_order_id"] = resolved["client_order_id"]
        else:
            # Keep the GM-owned id only in the explicit alias field.  An
            # unresolved broker id must not masquerade as our local id.
            normalized["client_order_id"] = None
        return mapped
