from __future__ import annotations

from pathlib import Path

from broker_node.api_service.repositories import NodeRepository
from broker_node.gm_agent.event_writer import EventWriter
from broker_node.gm_agent.snapshot_writer import SnapshotWriter
from broker_node.shared.db import connect, initialize


def test_event_writer_is_idempotent_by_event_id(tmp_path: Path) -> None:
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    writer = EventWriter(db)
    first = writer.append("FILL", {"value": 1}, "CALLBACK", event_id="event-1")
    second = writer.append("FILL", {"value": 1}, "QUERY", event_id="event-1")
    assert first == second
    assert NodeRepository(db).list_events(0, 500)["events"][0]["seq"] == first


def test_partial_node_state_update_preserves_connection_state(tmp_path: Path) -> None:
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    writer = SnapshotWriter(db)
    writer.write_node_state({
        "node_id": "node", "broker_account_key": "sim", "account_mode": "SIM",
        "market_connection_status": "CONNECTED", "trade_connection_status": "CONNECTED",
        "broker_account_status": "CONNECTED", "execution_enabled": False,
        "paused": False, "reconciliation_required": False,
        "last_agent_heartbeat_at": "old", "updated_at": "old",
    })
    writer.write_node_state({
        "node_id": "node", "broker_account_key": "sim", "account_mode": "SIM",
        "last_agent_heartbeat_at": "new", "updated_at": "new",
    })
    with connect(db) as connection:
        row = connection.execute("SELECT market_connection_status, trade_connection_status, broker_account_status, last_agent_heartbeat_at FROM node_state").fetchone()
    assert tuple(row) == ("CONNECTED", "CONNECTED", "CONNECTED", "new")
