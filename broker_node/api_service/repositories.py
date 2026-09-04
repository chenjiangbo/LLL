from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from broker_node.shared.db import connect


class NodeRepository:
    def __init__(self, durable_db: Path):
        self.durable_db = durable_db

    def get_node_state(self) -> dict[str, Any] | None:
        with connect(self.durable_db) as connection:
            row = connection.execute("SELECT * FROM node_state LIMIT 1").fetchone()
        return dict(row) if row else None

    def get_snapshot(self, snapshot_type: str) -> dict[str, Any] | None:
        with connect(self.durable_db) as connection:
            row = connection.execute(
                "SELECT * FROM snapshots WHERE snapshot_type = ?", (snapshot_type,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        result["stale"] = bool(result["stale"])
        return result

    def list_events(self, after_seq: int, limit: int) -> dict[str, Any]:
        if after_seq < 0:
            raise ValueError("after_seq must be non-negative")
        if limit <= 0:
            raise ValueError("limit must be positive")
        with connect(self.durable_db) as connection:
            rows = connection.execute(
                """
                SELECT seq, event_id, event_type, client_order_id,
                       broker_order_id, broker_execution_id, source,
                       payload_json, occurred_at, received_at
                FROM broker_events
                WHERE seq > ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (after_seq, limit),
            ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            events.append(item)
        return {
            "events": events,
            "next_seq": events[-1]["seq"] if events else after_seq,
        }

    def unresolved_unknown_commands(self) -> int:
        with connect(self.durable_db) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM commands WHERE status = 'UNKNOWN'"
            ).fetchone()
        return int(row["count"])

    def enqueue_sync(self, request_id: str, now: str) -> dict[str, Any]:
        import hashlib
        import uuid

        payload = {"request_id": request_id, "scope": "ALL"}
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        command_id = str(uuid.uuid4())
        with connect(self.durable_db) as connection:
            existing = connection.execute(
                "SELECT * FROM commands WHERE request_id = ?", (request_id,)
            ).fetchone()
            if existing:
                return {"command_id": existing["command_id"], "request_id": request_id, "status": existing["status"], "deduplicated": True}
            connection.execute(
                """
                INSERT INTO commands (
                    command_id, request_id, command_type, payload_hash,
                    payload_json, status, created_at, updated_at
                ) VALUES (?, ?, 'SYNC_ALL', ?, ?, 'QUEUED', ?, ?)
                """,
                (command_id, request_id, payload_hash, payload_json, now, now),
            )
        return {"command_id": command_id, "request_id": request_id, "status": "QUEUED", "deduplicated": False}

    def set_quote_subscription(self, owner_id: str, symbols: list[dict[str, str]], lease_seconds: int, now: str) -> None:
        expires = (datetime.fromisoformat(now) + timedelta(seconds=lease_seconds)).isoformat()
        with connect(self.durable_db) as connection:
            connection.execute("DELETE FROM quote_subscriptions WHERE owner_type='EXECUTION_PLAN' AND owner_id=?", (owner_id,))
            for item in symbols:
                code, exchange = item["code"], item["exchange"]
                if exchange not in ("SH", "SZ") or not code:
                    raise ValueError("unsupported execution quote instrument")
                connection.execute("INSERT INTO quote_subscriptions(owner_type,owner_id,symbol_key,broker_symbol,lease_expires_at,created_at,updated_at) VALUES('EXECUTION_PLAN',?,?,?,?,?,?)", (owner_id, f"{exchange}:{code}", f"{'SHSE' if exchange == 'SH' else 'SZSE'}.{code}", expires, now, now))

    def remove_quote_subscription(self, owner_id: str) -> None:
        with connect(self.durable_db) as connection:
            connection.execute("DELETE FROM quote_subscriptions WHERE owner_type='EXECUTION_PLAN' AND owner_id=?", (owner_id,))

    def list_quote_subscriptions(self) -> list[dict[str, Any]]:
        with connect(self.durable_db) as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM quote_subscriptions ORDER BY owner_id,symbol_key")]

    def set_paused(self, paused: bool, reason: str | None = None) -> dict[str, Any]:
        with connect(self.durable_db) as connection:
            row = connection.execute("SELECT * FROM node_state LIMIT 1").fetchone()
            if not row:
                raise ValueError("AGENT_NOT_INITIALIZED")
            if not paused and (row["agent_process_status"] != "ONLINE" or row["market_connection_status"] != "CONNECTED" or row["trade_connection_status"] != "CONNECTED" or row["broker_account_status"] != "CONNECTED" or row["reconciliation_required"] or self.unresolved_unknown_commands()):
                raise ValueError("NOT_READY")
            connection.execute("UPDATE node_state SET paused=?,execution_enabled=?,pause_reason=?,updated_at=?", (int(paused), int(not paused), reason if paused else None, datetime.now(timezone.utc).isoformat()))
            return dict(connection.execute("SELECT * FROM node_state LIMIT 1").fetchone())

    def enqueue_command(self, request_id: str, command_type: str, payload: dict[str, Any], client_order_id: str | None, now: str) -> dict[str, Any]:
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        import hashlib, uuid
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with connect(self.durable_db) as connection:
            existing = connection.execute("SELECT * FROM commands WHERE request_id = ?", (request_id,)).fetchone()
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise ValueError("IDEMPOTENCY_CONFLICT")
                return {"command_id": existing["command_id"], "request_id": request_id, "status": existing["status"], "deduplicated": True}
            command_id = str(uuid.uuid4())
            connection.execute("INSERT INTO commands(command_id,request_id,command_type,client_order_id,payload_hash,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?, 'QUEUED',?,?)", (command_id, request_id, command_type, client_order_id, payload_hash, payload_json, now, now))
        return {"command_id": command_id, "request_id": request_id, "status": "QUEUED", "deduplicated": False}

    def order_status(self, client_order_id: str) -> str | None:
        snapshot = self.get_snapshot("ORDERS")
        if not snapshot:
            return None
        linked_broker_order_id = None
        with connect(self.durable_db) as connection:
            link = connection.execute(
                "SELECT broker_order_id FROM order_links WHERE client_order_id=?",
                (client_order_id,),
            ).fetchone()
            if link:
                linked_broker_order_id = link["broker_order_id"]
        for item in snapshot["payload"]:
            normalized = item.get("normalized", {})
            if (
                normalized.get("client_order_id") == client_order_id
                or (
                    linked_broker_order_id
                    and normalized.get("broker_order_id") == linked_broker_order_id
                )
            ):
                return normalized.get("status")
        return None

    def open_system_orders(self) -> list[str]:
        """Return linked system orders that are not known to be terminal."""
        terminal = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}
        with connect(self.durable_db) as connection:
            rows = connection.execute(
                "SELECT client_order_id FROM order_links WHERE origin='SYSTEM' ORDER BY client_order_id"
            ).fetchall()
        return [
            row["client_order_id"]
            for row in rows
            if self.order_status(row["client_order_id"]) not in terminal
        ]
