from __future__ import annotations

from datetime import datetime, timezone
import json
from decimal import Decimal
from typing import Any, Callable

from broker_node.gm_agent.gm_adapter import GmContextAdapter
from broker_node.gm_agent.event_writer import EventWriter
from broker_node.gm_agent.gm_mapper import map_account, map_fill, map_order, map_position
from broker_node.gm_agent.snapshot_writer import SnapshotWriter
from broker_node.shared.db import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        orders = [map_order(item) for item in orders_raw]
        unfinished_orders = [map_order(item) for item in unfinished_raw]
        fills = [map_fill(item) for item in fills_raw]

        # The broker may emit the order callback before order_volume returns.
        # Reconcile the authoritative order query into order_links as well, so
        # a subsequent cancel never depends on callback timing.
        with connect(self.snapshots.durable_db) as connection:
            for item in orders:
                normalized = item["normalized"]
                client_order_id = normalized.get("client_order_id")
                broker_order_id = normalized.get("broker_order_id")
                if not client_order_id or not broker_order_id:
                    continue
                existing_link = connection.execute(
                    "SELECT client_order_id FROM order_links WHERE client_order_id=?",
                    (client_order_id,),
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
                        client_order_id, submit_command_id, broker_order_id,
                        exchange_order_id, last_broker_status, last_raw_status,
                        origin, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?, 'SYSTEM', ?, ?)
                    ON CONFLICT(client_order_id) DO UPDATE SET
                        submit_command_id=COALESCE(order_links.submit_command_id, excluded.submit_command_id),
                        broker_order_id=excluded.broker_order_id,
                        exchange_order_id=COALESCE(excluded.exchange_order_id, order_links.exchange_order_id),
                        last_broker_status=excluded.last_broker_status,
                        last_raw_status=excluded.last_raw_status,
                        updated_at=excluded.updated_at
                    """,
                    (
                        command["client_order_id"],
                        submit_command_id,
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
