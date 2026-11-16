from __future__ import annotations

import json
from pathlib import Path

import pytest

from broker_node.gm_agent.event_writer import EventWriter
from broker_node.gm_agent.reconciler import Reconciler
from broker_node.gm_agent.lifecycle import AgentLifecycle
from broker_node.shared.config import NodeConfig
from broker_node.gm_agent.snapshot_writer import SnapshotWriter
from broker_node.shared.db import connect, initialize
import broker_node.gm_agent.lifecycle as lifecycle_module


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
    again = Reconciler(db, EventWriter(db), SnapshotWriter(db)).startup()
    assert again["unknown_commands"] == 1
    assert again["reconciliation_required"] is True


def test_callback_heartbeat_is_not_written_when_cycle_raises(monkeypatch) -> None:
    import broker_node.gm_agent.main as main
    class BrokenCycle:
        def __init__(self):
            self.heartbeat = False
        def process_one_command(self):
            raise RuntimeError("cycle stopped")
        def record_callback_heartbeat(self):
            self.heartbeat = True
    agent = BrokenCycle()
    monkeypatch.setattr(main, "_lifecycle", agent)
    main._process_commands(None)
    assert agent.heartbeat is False


def test_account_status_only_updates_the_configured_account(monkeypatch) -> None:
    import broker_node.gm_agent.main as main
    class Agent:
        config = NodeConfig({"expected_broker_account_id": "ours"}, Path("config.json"))
    events = []
    monkeypatch.setattr(main, "_lifecycle", Agent())
    monkeypatch.setattr(main, "_record_connection", lambda channel, status: events.append((channel, status)))
    main.on_account_status(None, {"account_id": "other", "status": {"state": 3}})
    main.on_account_status(None, {"account_id": "ours", "status": {"state": 3}})
    main.on_account_status(None, {"account_id": "ours", "status": {"state": 5}})
    assert events == [("ACCOUNT", "CONNECTED"), ("ACCOUNT", "DISCONNECTED")]


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


def test_missing_snapshot_does_not_lock_terminal_link(tmp_path: Path) -> None:
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    now = "2026-09-05T00:00:00+08:00"
    with connect(db) as connection:
        connection.execute(
            "INSERT INTO node_state (node_id, broker_account_key, account_mode, updated_at) VALUES (?, ?, ?, ?)",
            ("node", "sim", "SIM", now),
        )
        connection.execute(
            "INSERT INTO order_links(client_order_id,submit_command_id,broker_client_order_id,broker_order_id,last_broker_status,origin,created_at,updated_at) VALUES(?,?,?,?,?,'SYSTEM',?,?)",
            ("local", "submit", "gm-client", "broker-filled", "FILLED", now, now),
        )
    SnapshotWriter(db).write("ORDERS", [], now)
    result = Reconciler(db, EventWriter(db), SnapshotWriter(db)).startup()
    assert result["missing_links"] == 0


def test_external_links_do_not_lock_and_status_is_recovered_from_event(tmp_path: Path) -> None:
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    now = "2026-09-05T00:00:00+08:00"
    with connect(db) as connection:
        connection.execute(
            "INSERT INTO node_state (node_id, broker_account_key, account_mode, updated_at) VALUES (?, ?, ?, ?)",
            ("node", "sim", "SIM", now),
        )
        connection.execute(
            "INSERT INTO order_links(client_order_id,submit_command_id,broker_order_id,last_broker_status,origin,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("external:broker", "external", "broker", None, "EXTERNAL", now, now),
        )
        connection.execute(
            "INSERT INTO order_links(client_order_id,submit_command_id,broker_order_id,last_broker_status,origin,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("local:broker", "submit", "broker-rejected", None, "SYSTEM", now, now),
        )
    EventWriter(db).append(
        "ORDER_STATUS",
        {"normalized": {"status": "UNKNOWN", "raw_status": 8}},
        "CALLBACK",
        broker_order_id="broker-rejected",
    )
    SnapshotWriter(db).write("ORDERS", [], now)
    result = Reconciler(db, EventWriter(db), SnapshotWriter(db)).startup()
    assert result["missing_links"] == 0
    with connect(db) as connection:
        status = connection.execute("SELECT last_broker_status FROM order_links WHERE client_order_id='local:broker'").fetchone()[0]
    assert status == "REJECTED"


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


class _SuccessfulSync:
    def __init__(self, *_args):
        pass

    def synchronize(self):
        return {"account": 1, "positions": 1, "orders": 1, "fills": 1}


class _FailingSync:
    def __init__(self, *_args):
        pass

    def synchronize(self):
        raise RuntimeError("sync failed")


class _ReconcileResult:
    def __init__(self, result):
        self.result = result

    def startup(self):
        return self.result


def _lifecycle_for_reconnect(tmp_path: Path) -> tuple[AgentLifecycle, Path]:
    config = NodeConfig({
        "node_id": "node", "broker_account_key": "sim", "account_mode": "SIM",
        "gm": {"strategy_id": "strategy", "token_env": "GM_API_TOKEN"},
        "api": {"token_env": "BROKER_NODE_API_TOKEN", "host": "127.0.0.1", "port": 1},
        "runtime": {"durable_db": str(tmp_path / "node.sqlite3"), "quote_cache_db": str(tmp_path / "quote.sqlite3"), "log_dir": str(tmp_path)},
        "sync": {"account_position_sync_seconds": 15}, "execution_quote": {},
        "safety": {"allow_live_orders": False},
    }, tmp_path / "config.json")
    db = config.path.parent / "node.sqlite3"
    initialize(db)
    lifecycle = AgentLifecycle(config, db)
    lifecycle._write_state(
        market_connection_status="CONNECTED", trade_connection_status="CONNECTED",
        broker_account_status="CONNECTED", execution_enabled=True, paused=False,
        reconciliation_required=False,
    )
    lifecycle._adapter = object()
    return lifecycle, db


def test_timer_retries_transient_reconciliation(tmp_path: Path, monkeypatch) -> None:
    lifecycle, db = _lifecycle_for_reconnect(tmp_path)
    lifecycle._write_state(execution_enabled=False, paused=True, reconciliation_required=True, pause_reason="RECONCILIATION_REQUIRED")
    monkeypatch.setattr(lifecycle_module, "ReadonlySynchronizer", _SuccessfulSync)
    monkeypatch.setattr(lifecycle.quote_subscriptions, "refresh", lambda: set())
    lifecycle.process_one_command()
    with connect(db) as connection:
        state = connection.execute("SELECT execution_enabled,paused,reconciliation_required FROM node_state").fetchone()
    assert tuple(state) == (1, 0, 0)


def test_quote_failure_does_not_prevent_command_consumption(tmp_path: Path, monkeypatch) -> None:
    import time
    lifecycle, db = _lifecycle_for_reconnect(tmp_path)
    lifecycle._last_periodic_sync = time.monotonic()
    class Adapter:
        def account_id(self):
            return "account"
    class Executor:
        def __init__(self):
            self.dispatched = False
        def claim_next(self):
            return {"command_id": "c"}
        def dispatch(self, command, account):
            self.dispatched = True
    lifecycle._adapter = Adapter()
    lifecycle.executor = Executor()
    monkeypatch.setattr(lifecycle_module, "ReadonlySynchronizer", _SuccessfulSync)
    def quote_error():
        raise RuntimeError("subscription rejected")
    monkeypatch.setattr(lifecycle.quote_subscriptions, "refresh", quote_error)
    lifecycle.process_one_command()
    assert lifecycle.executor.dispatched
    with connect(db) as connection:
        assert connection.execute("SELECT 1 FROM broker_events WHERE event_type='QUOTE_SUBSCRIPTION_FAILED'").fetchone()


def test_disconnect_reconnect_reconciliation_failure_stays_fail_closed(tmp_path: Path, monkeypatch) -> None:
    lifecycle, db = _lifecycle_for_reconnect(tmp_path)
    lifecycle.record_connection("TRADE", "DISCONNECTED")
    lifecycle.record_connection("TRADE", "CONNECTED")
    monkeypatch.setattr(lifecycle_module, "ReadonlySynchronizer", _SuccessfulSync)
    monkeypatch.setattr(
        lifecycle_module,
        "Reconciler",
        lambda *_args: _ReconcileResult({"reconciliation_required": True, "unknown_commands": 1, "missing_links": 0, "external_orders": 0}),
    )

    lifecycle.reconcile_after_reconnect()

    with connect(db) as connection:
        row = connection.execute("SELECT execution_enabled,paused,reconciliation_required,pause_reason FROM node_state").fetchone()
    assert tuple(row) == (0, 1, 1, "RECONCILIATION_REQUIRED")


def test_disconnect_reconnect_success_auto_resumes_automatic_protection(tmp_path: Path, monkeypatch) -> None:
    lifecycle, db = _lifecycle_for_reconnect(tmp_path)
    lifecycle.record_connection("TRADE", "DISCONNECTED")
    lifecycle.record_connection("TRADE", "CONNECTED")
    monkeypatch.setattr(lifecycle_module, "ReadonlySynchronizer", _SuccessfulSync)
    monkeypatch.setattr(
        lifecycle_module,
        "Reconciler",
        lambda *_args: _ReconcileResult({"reconciliation_required": False, "unknown_commands": 0, "missing_links": 0, "external_orders": 0}),
    )

    lifecycle.reconcile_after_reconnect()

    with connect(db) as connection:
        row = connection.execute("SELECT execution_enabled,paused,reconciliation_required,pause_reason FROM node_state").fetchone()
    assert tuple(row) == (1, 0, 0, None)


def test_disconnect_reconnect_success_preserves_user_pause(tmp_path: Path, monkeypatch) -> None:
    lifecycle, db = _lifecycle_for_reconnect(tmp_path)
    lifecycle._write_state(execution_enabled=False, paused=True, pause_reason="API_PAUSED", reconciliation_required=False)
    lifecycle.record_connection("TRADE", "DISCONNECTED")
    with connect(db) as connection:
        disconnected = connection.execute("SELECT execution_enabled,paused,reconciliation_required,pause_reason FROM node_state").fetchone()
    assert tuple(disconnected) == (0, 1, 1, "API_PAUSED")
    lifecycle.record_connection("TRADE", "CONNECTED")
    monkeypatch.setattr(lifecycle_module, "ReadonlySynchronizer", _SuccessfulSync)
    monkeypatch.setattr(
        lifecycle_module,
        "Reconciler",
        lambda *_args: _ReconcileResult({"reconciliation_required": False, "unknown_commands": 0, "missing_links": 0, "external_orders": 0}),
    )

    lifecycle.reconcile_after_reconnect()

    with connect(db) as connection:
        row = connection.execute("SELECT execution_enabled,paused,reconciliation_required,pause_reason FROM node_state").fetchone()
    assert tuple(row) == (0, 1, 0, "API_PAUSED")


def test_reconnect_exception_remains_fail_closed_and_is_audited(tmp_path: Path, monkeypatch) -> None:
    lifecycle, db = _lifecycle_for_reconnect(tmp_path)
    lifecycle.record_connection("TRADE", "DISCONNECTED")
    lifecycle.record_connection("TRADE", "CONNECTED")
    monkeypatch.setattr(lifecycle_module, "ReadonlySynchronizer", _FailingSync)

    with pytest.raises(RuntimeError, match="sync failed"):
        lifecycle.reconcile_after_reconnect()

    with connect(db) as connection:
        row = connection.execute("SELECT execution_enabled,paused,reconciliation_required,pause_reason FROM node_state").fetchone()
        event = connection.execute(
            "SELECT event_type,payload_json FROM broker_events WHERE event_type='RECONCILIATION_FAILED' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    assert tuple(row) == (0, 1, 1, "RECONCILIATION_REQUIRED")
    assert event[0] == "RECONCILIATION_FAILED"
