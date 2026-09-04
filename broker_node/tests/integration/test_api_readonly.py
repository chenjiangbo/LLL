from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from broker_node.api_service.app import create_app
from broker_node.gm_agent.event_writer import EventWriter
from broker_node.gm_agent.snapshot_writer import SnapshotWriter
from broker_node.shared.db import initialize
from broker_node.shared.db import connect


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    config = json.loads((Path(__file__).parents[2] / "config" / "config.example.json").read_text())
    durable = tmp_path / "runtime" / "broker.sqlite3"
    config["gm"]["strategy_id"] = "strategy-for-test"
    config["runtime"]["durable_db"] = str(durable)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    initialize(durable)
    monkeypatch.setenv("BROKER_NODE_CONFIG", str(path))
    monkeypatch.setenv("BROKER_NODE_API_TOKEN", "test-token")
    return TestClient(create_app())


def test_health_and_status_are_available_over_the_private_network(client: TestClient) -> None:
    assert client.get("/api/v1/health").status_code == 200
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    assert response.json()["agent_online"] is False
    assert response.json()["reconciliation_required"] is True


def test_snapshot_and_event_endpoints_expose_real_state(client: TestClient, tmp_path: Path) -> None:
    durable = Path(json.loads((Path(__file__).parents[2] / "config" / "config.example.json").read_text())["runtime"]["durable_db"])
    # The fixture setup uses a temporary path; obtain it from the app's config environment.
    config = json.loads(Path(__import__("os").environ["BROKER_NODE_CONFIG"]).read_text())
    durable = Path(config["runtime"]["durable_db"])
    SnapshotWriter(durable).write("ACCOUNT", {"normalized": {"available_cash": "185570.0"}, "raw": {}}, "2026-09-02T23:00:00+08:00")
    EventWriter(durable).append("ACCOUNT_STATUS_CHANGED", {"state": 3}, "QUERY", event_id="event-1")
    account = client.get("/api/v1/account")
    assert account.status_code == 200
    assert account.json()["payload"]["normalized"]["available_cash"] == "185570.0"
    events = client.get("/api/v1/events?after_seq=0&limit=500")
    assert events.status_code == 200
    assert events.json()["events"][0]["event_id"] == "event-1"


def test_sync_request_is_idempotent(client: TestClient) -> None:
    first = client.post("/api/v1/sync", json={"request_id": "sync-request-1"}).json()
    second = client.post("/api/v1/sync", json={"request_id": "sync-request-1"}).json()
    assert first["deduplicated"] is False
    assert second["deduplicated"] is True
    assert first["command_id"] == second["command_id"]


def test_order_request_is_idempotent_and_conflict_is_rejected(client: TestClient) -> None:
    payload = {"request_id": "order-request-1", "client_order_id": "client-1", "broker_account_key": "guotou_sim_01", "code": "000661", "exchange": "SZ", "side": "BUY", "price": "70.00", "quantity": 100}
    first = client.post("/api/v1/orders", json=payload)
    second = client.post("/api/v1/orders", json=payload)
    assert first.status_code == 202
    assert second.json()["deduplicated"] is True
    changed = dict(payload, price="71.00")
    assert client.post("/api/v1/orders", json=changed).status_code == 409


def test_pause_and_cancel_open_orders_pauses_and_queues_each_system_order(client: TestClient) -> None:
    config = json.loads(Path(__import__("os").environ["BROKER_NODE_CONFIG"]).read_text())
    durable = Path(config["runtime"]["durable_db"])
    now = "2026-09-03T10:00:00+00:00"
    with connect(durable) as connection:
        connection.execute(
            "INSERT INTO node_state(node_id, broker_account_key, account_mode, agent_process_status, market_connection_status, trade_connection_status, broker_account_status, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("node", "guotou_sim_01", "SIM", "ONLINE", "CONNECTED", "CONNECTED", "CONNECTED", now),
        )
        connection.execute(
            "INSERT INTO order_links(client_order_id, submit_command_id, broker_order_id, origin, created_at, updated_at) VALUES(?,?,?,?,?,?)",
            ("client-open", "submit", "broker-open", "SYSTEM", now, now),
        )
    SnapshotWriter(durable).write(
        "ORDERS",
        [{"normalized": {"client_order_id": "client-open", "broker_order_id": "broker-open", "status": "NEW"}, "raw": {}}],
        now,
    )
    response = client.post("/api/v1/control/pause-and-cancel-open-orders")
    assert response.status_code == 200
    body = response.json()
    assert body["paused"]["paused"] == 1
    assert body["cancel_requests"][0]["status"] == "QUEUED"
