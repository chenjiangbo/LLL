from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from broker_node.shared.db import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SnapshotWriter:
    def __init__(self, durable_db: Path):
        self.durable_db = durable_db

    def write(self, snapshot_type: str, payload: Any, as_of: str, source: str = "QUERY", stale: bool = False) -> None:
        payload_json = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
        now = _now()
        with connect(self.durable_db) as connection:
            current = connection.execute(
                "SELECT snapshot_version FROM snapshots WHERE snapshot_type = ?",
                (snapshot_type,),
            ).fetchone()
            version = int(current["snapshot_version"]) + 1 if current else 1
            connection.execute(
                """
                INSERT INTO snapshots (
                    snapshot_type, snapshot_version, as_of, source,
                    stale, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_type) DO UPDATE SET
                    snapshot_version = excluded.snapshot_version,
                    as_of = excluded.as_of,
                    source = excluded.source,
                    stale = excluded.stale,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (snapshot_type, version, as_of, source, int(stale), payload_json, now),
            )

    def write_node_state(self, state: dict[str, Any]) -> None:
        required = ("node_id", "broker_account_key", "account_mode", "updated_at")
        missing = [field for field in required if field not in state]
        if missing:
            raise ValueError(f"missing node state fields: {', '.join(missing)}")
        with connect(self.durable_db) as connection:
            existing = connection.execute(
                "SELECT * FROM node_state WHERE node_id = ?", (state["node_id"],)
            ).fetchone()
            effective = dict(existing) if existing else {}
            effective.update(state)
            connection.execute(
                """
                INSERT INTO node_state (
                    node_id, broker_account_key, account_mode,
                    api_process_status, agent_process_status,
                    market_connection_status, trade_connection_status,
                    broker_account_status, execution_enabled, paused,
                    pause_reason, reconciliation_required,
                    last_agent_heartbeat_at, last_broker_event_at,
                    last_account_sync_at, last_position_sync_at,
                    last_order_sync_at, last_fill_sync_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    broker_account_key=excluded.broker_account_key,
                    account_mode=excluded.account_mode,
                    api_process_status=excluded.api_process_status,
                    agent_process_status=excluded.agent_process_status,
                    market_connection_status=excluded.market_connection_status,
                    trade_connection_status=excluded.trade_connection_status,
                    broker_account_status=excluded.broker_account_status,
                    execution_enabled=excluded.execution_enabled,
                    paused=excluded.paused,
                    pause_reason=excluded.pause_reason,
                    reconciliation_required=excluded.reconciliation_required,
                    last_agent_heartbeat_at=excluded.last_agent_heartbeat_at,
                    last_broker_event_at=excluded.last_broker_event_at,
                    last_account_sync_at=excluded.last_account_sync_at,
                    last_position_sync_at=excluded.last_position_sync_at,
                    last_order_sync_at=excluded.last_order_sync_at,
                    last_fill_sync_at=excluded.last_fill_sync_at,
                    updated_at=excluded.updated_at
                """,
                (
                    effective["node_id"], effective["broker_account_key"], effective["account_mode"],
                    effective.get("api_process_status", "OFFLINE"),
                    effective.get("agent_process_status", "ONLINE"),
                    effective.get("market_connection_status", "UNKNOWN"),
                    effective.get("trade_connection_status", "UNKNOWN"),
                    effective.get("broker_account_status", "UNKNOWN"),
                    int(effective.get("execution_enabled", False)),
                    int(effective.get("paused", True)),
                    effective.get("pause_reason"),
                    int(effective.get("reconciliation_required", True)),
                    effective.get("last_agent_heartbeat_at"),
                    effective.get("last_broker_event_at"),
                    effective.get("last_account_sync_at"),
                    effective.get("last_position_sync_at"),
                    effective.get("last_order_sync_at"),
                    effective.get("last_fill_sync_at"),
                    effective["updated_at"],
                ),
            )
