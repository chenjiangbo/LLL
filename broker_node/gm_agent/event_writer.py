from __future__ import annotations

import hashlib
import json
import uuid
import sqlite3
from datetime import datetime, timezone
from typing import Any

from broker_node.shared.db import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventWriter:
    def __init__(self, durable_db):
        self.durable_db = durable_db

    def append(
        self,
        event_type: str,
        payload: Any,
        source: str,
        *,
        client_order_id: str | None = None,
        broker_order_id: str | None = None,
        broker_execution_id: str | None = None,
        occurred_at: str | None = None,
        event_id: str | None = None,
    ) -> int:
        payload_json = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
        fingerprint = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        event_id = event_id or str(uuid.uuid4())
        received_at = _now()
        with connect(self.durable_db) as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO broker_events (
                        event_id, event_type, client_order_id, broker_order_id,
                        broker_execution_id, source, raw_fingerprint,
                        payload_json, occurred_at, received_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        event_type,
                        client_order_id,
                        broker_order_id,
                        broker_execution_id,
                        source,
                        fingerprint,
                        payload_json,
                        occurred_at,
                        received_at,
                    ),
                )
                return int(cursor.lastrowid)
            except sqlite3.IntegrityError as exc:
                if "broker_events.event_id" not in str(exc):
                    raise
                row = connection.execute(
                    "SELECT seq FROM broker_events WHERE event_id = ?", (event_id,)
                ).fetchone()
                if row is None:
                    raise
                return int(row["seq"])
