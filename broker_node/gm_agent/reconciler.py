from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from broker_node.gm_agent.event_writer import EventWriter
from broker_node.gm_agent.snapshot_writer import SnapshotWriter
from broker_node.shared.db import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Reconciler:
    def __init__(self, durable_db, events: EventWriter, snapshots: SnapshotWriter):
        self.durable_db = durable_db
        self.events = events
        self.snapshots = snapshots

    def startup(self) -> dict[str, Any]:
        result = {
            "unknown_commands": self._protect_dispatching_commands(),
            "missing_links": self._find_missing_order_links(),
            "external_orders": self._find_external_orders(),
        }
        # An external order is an auditable fact, not by itself an execution
        # inconsistency. It remains unbound to the system and is surfaced as an
        # event; only unknown commands or broken local links require the lock.
        result["reconciliation_required"] = bool(
            result["unknown_commands"] or result["missing_links"]
        )
        if result["reconciliation_required"]:
            self._set_protection("RECONCILIATION_REQUIRED")
        return result

    def _protect_dispatching_commands(self) -> int:
        with connect(self.durable_db) as connection:
            rows = connection.execute(
                "SELECT command_id FROM commands WHERE status IN ('CLAIMED', 'DISPATCHING')"
            ).fetchall()
            if rows:
                connection.execute(
                    """
                    UPDATE commands
                    SET status = 'UNKNOWN',
                        error_code = 'SUBMIT_UNKNOWN',
                        error_message = 'Command was dispatching when Agent restarted',
                        updated_at = ?
                    WHERE status IN ('CLAIMED', 'DISPATCHING')
                    """,
                    (_now(),),
                )
        for row in rows:
            self.events.append(
                "COMMAND_STATUS",
                {"command_id": row["command_id"], "status": "UNKNOWN"},
                "RECONCILE",
            )
        return len(rows)

    def _broker_order_ids_from_snapshot(self) -> set[str]:
        snapshot = self.snapshots
        with connect(self.durable_db) as connection:
            row = connection.execute(
                "SELECT payload_json FROM snapshots WHERE snapshot_type = 'ORDERS'"
            ).fetchone()
        if not row:
            return set()
        payload = json.loads(row["payload_json"])
        return {
            str(item["normalized"]["broker_order_id"])
            for item in payload
            if item.get("normalized", {}).get("broker_order_id")
        }

    def _find_missing_order_links(self) -> int:
        broker_ids = self._broker_order_ids_from_snapshot()
        if not broker_ids:
            return 0
        with connect(self.durable_db) as connection:
            rows = connection.execute(
                """
                SELECT client_order_id, broker_order_id
                FROM order_links
                WHERE broker_order_id IS NOT NULL
                """
            ).fetchall()
        missing = [row for row in rows if row["broker_order_id"] not in broker_ids]
        for row in missing:
            self.events.append(
                "RECONCILIATION_ALERT",
                {"reason": "LOCAL_ORDER_NOT_FOUND_AT_BROKER", "client_order_id": row["client_order_id"], "broker_order_id": row["broker_order_id"]},
                "RECONCILE",
                client_order_id=row["client_order_id"],
                broker_order_id=row["broker_order_id"],
            )
        return len(missing)

    def _find_external_orders(self) -> int:
        broker_ids = self._broker_order_ids_from_snapshot()
        if not broker_ids:
            return 0
        with connect(self.durable_db) as connection:
            linked = {
                row["broker_order_id"]
                for row in connection.execute(
                    "SELECT broker_order_id FROM order_links WHERE broker_order_id IS NOT NULL"
                ).fetchall()
            }
        external = broker_ids - linked
        for broker_id in external:
            with connect(self.durable_db) as connection:
                connection.execute("INSERT OR IGNORE INTO order_links(client_order_id,submit_command_id,broker_order_id,last_broker_status,origin,created_at,updated_at) VALUES(?,?,?,?, 'EXTERNAL',?,?)", (f"external:{broker_id}", "external", broker_id, None, _now(), _now()))
            self.events.append(
                "EXTERNAL_ORDER_FOUND",
                {"broker_order_id": broker_id, "origin": "EXTERNAL"},
                "RECONCILE",
                broker_order_id=broker_id,
                event_id=f"external-order:{broker_id}",
            )
        return len(external)

    def _set_protection(self, reason: str) -> None:
        with connect(self.durable_db) as connection:
            connection.execute(
                """
                UPDATE node_state
                SET execution_enabled = 0,
                    reconciliation_required = 1,
                    pause_reason = ?,
                    updated_at = ?
                """,
                (reason, _now()),
            )
