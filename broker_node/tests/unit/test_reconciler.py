from __future__ import annotations

import json
from pathlib import Path

from broker_node.gm_agent.event_writer import EventWriter
from broker_node.gm_agent.reconciler import Reconciler
from broker_node.gm_agent.lifecycle import AgentLifecycle
from broker_node.shared.config import NodeConfig
from broker_node.gm_agent.snapshot_writer import SnapshotWriter
from broker_node.shared.db import connect, initialize


def test_dispatching_command_becomes_unknown_and_protected(tmp_path: Path) -> None:
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    now = "2026-09-02T00:00:00+00:00"
    with connect(db) as connection:
        connection.execute(
            "INSERT INTO node_state (node_id, broker_account_key, account_mode, updated_at) VALUES (?, ?, ?, ?)",
            ("node", "sim", "SIM", now),
        )
        connection.execute(
            "INSERT INTO commands (command_id, request_id, command_type, payload_hash, payload_json, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("cmd", "req", "ORDER_SUBMIT", "hash", "{}", "DISPATCHING", now, now),
        )
    result = Reconciler(db, EventWriter(db), SnapshotWriter(db)).startup()
    assert result["unknown_commands"] == 1
    with connect(db) as connection:
        command = connection.execute("SELECT status FROM commands WHERE command_id='cmd'").fetchone()
        state = connection.execute("SELECT execution_enabled, reconciliation_required FROM node_state").fetchone()
    assert command["status"] == "UNKNOWN"
    assert tuple(state) == (0, 1)


def test_external_order_is_recorded(tmp_path: Path) -> None:
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    SnapshotWriter(db).write("ORDERS", [{"normalized": {"broker_order_id": "broker-1"}, "raw": {}}], "2026-09-02T00:00:00+00:00")
    result = Reconciler(db, EventWriter(db), SnapshotWriter(db)).startup()
    assert result["external_orders"] == 1
    with connect(db) as connection:
        event = connection.execute("SELECT event_type, broker_order_id FROM broker_events").fetchone()
    assert tuple(event) == ("EXTERNAL_ORDER_FOUND", "broker-1")
    again = Reconciler(db, EventWriter(db), SnapshotWriter(db)).startup()
    assert again["external_orders"] == 0


def test_connection_disconnect_fails_closed(tmp_path: Path) -> None:
    config = NodeConfig({
        "node_id": "node", "broker_account_key": "sim", "account_mode": "SIM",
        "gm": {"strategy_id": "strategy", "token_env": "GM_API_TOKEN"},
        "api": {"token_env": "BROKER_NODE_API_TOKEN", "host": "127.0.0.1", "port": 1},
        "runtime": {"durable_db": str(tmp_path / "node.sqlite3"), "quote_cache_db": str(tmp_path / "quote.sqlite3"), "log_dir": str(tmp_path)},
        "sync": {}, "execution_quote": {}, "safety": {"start_paused": False, "allow_live_orders": False},
    }, tmp_path / "config.json")
    initialize(config.path.parent / "node.sqlite3")
    lifecycle = AgentLifecycle(config, config.path.parent / "node.sqlite3")
    lifecycle._write_state(
        market_connection_status="CONNECTED", trade_connection_status="CONNECTED",
        broker_account_status="CONNECTED", execution_enabled=True, paused=False,
        reconciliation_required=False,
    )
    lifecycle.record_connection("TRADE", "DISCONNECTED")
    state = SnapshotWriter(config.path.parent / "node.sqlite3").durable_db
    with connect(state) as connection:
        row = connection.execute("SELECT trade_connection_status, execution_enabled, paused, reconciliation_required FROM node_state").fetchone()
    assert tuple(row) == ("DISCONNECTED", 0, 1, 1)
