from __future__ import annotations

import json
from pathlib import Path

from broker_node.gm_agent.event_writer import EventWriter
from broker_node.gm_agent.snapshot_writer import SnapshotWriter
from broker_node.gm_agent.synchronizer import ReadonlySynchronizer
from broker_node.shared.db import connect, initialize


class _Adapter:
    def cash(self):
        return {
            "account_id": "account",
            "nav": 100000.0,
            "available": 99000.0,
            "updated_at": "2026-09-05T01:20:11+08:00",
        }

    def positions(self):
        return []

    def orders(self):
        return [
            {
                "cl_ord_id": "gm-client",
                "order_id": "",
                "ex_ord_id": "",
                "symbol": "SHSE.600300",
                "side": 1,
                "status": 10,
                "price": 3.27,
                "volume": 300,
                "filled_volume": 0,
                "filled_vwap": 0,
                "filled_amount": 0,
                "created_at": "2026-09-05 03:46:35.357108+08:00",
                "updated_at": "2026-09-05 03:46:35.357108+08:00",
            }
        ]

    def unfinished_orders(self):
        return self.orders()

    def execution_reports(self):
        return []


def _insert_durable_facts(db: Path) -> None:
    now = "2026-09-05T03:46:35+08:00"
    with connect(db) as connection:
        connection.execute(
            """
            INSERT INTO commands(
                command_id,request_id,command_type,client_order_id,payload_hash,
                payload_json,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                "command",
                "request",
                "ORDER_SUBMIT",
                "local-order",
                "hash",
                json.dumps({"code": "600300", "exchange": "SH", "side": "BUY", "price": "3.27", "quantity": 300}),
                "ACKED",
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO order_links(
                client_order_id,submit_command_id,broker_client_order_id,broker_order_id,
                last_broker_status,last_raw_status,origin,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            ("local-order", "command", "gm-client", "broker-order", "FILLED", "3", "SYSTEM", now, now),
        )
    EventWriter(db).append(
        "ORDER_STATUS",
        {
            "normalized": {
                "client_order_id": "local-order",
                "broker_client_order_id": "gm-client",
                "broker_order_id": "broker-order",
                "exchange_order_id": "broker-order",
                "instrument": {"code": "600300", "exchange": "SH"},
                "side": "BUY",
                "status": "FILLED",
                "raw_status": 3,
                "price": 3.27,
                "quantity": 300,
                "filled_quantity": 300,
                "filled_vwap": 3.27,
                "filled_amount": 981.0,
                "created_at": now,
                "updated_at": now,
            },
            "raw": {},
        },
        "CALLBACK",
        client_order_id="local-order",
        broker_order_id="broker-order",
        occurred_at=now,
        event_id="filled-order",
    )
    EventWriter(db).append(
        "FILL",
        {
            "normalized": {
                "client_order_id": "local-order",
                "broker_client_order_id": "gm-client",
                "broker_order_id": "broker-order",
                "broker_execution_id": "execution",
                "instrument": {"code": "600300", "exchange": "SH"},
                "side": "BUY",
                "price": 3.27,
                "quantity": 300,
                "amount": 981.0,
                "occurred_at": now,
            },
            "raw": {},
        },
        "CALLBACK",
        client_order_id="local-order",
        broker_order_id="broker-order",
        broker_execution_id="execution",
        occurred_at=now,
        event_id="execution",
    )


def test_durable_terminal_callback_wins_over_lagging_query_and_fill_is_preserved(tmp_path: Path) -> None:
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    _insert_durable_facts(db)
    snapshots = SnapshotWriter(db)
    snapshots.write("ORDERS", [], "2026-09-05T01:20:11+08:00")
    snapshots.write("FILLS", [], "2026-09-05T01:20:11+08:00")

    result = ReadonlySynchronizer(_Adapter(), snapshots, EventWriter(db)).synchronize()

    assert result == {"positions": 0, "orders": 1, "unfinished_orders": 0, "fills": 1}
    with connect(db) as connection:
        order_snapshot = json.loads(connection.execute("SELECT payload_json FROM snapshots WHERE snapshot_type='ORDERS'").fetchone()[0])
        fill_snapshot = json.loads(connection.execute("SELECT payload_json FROM snapshots WHERE snapshot_type='FILLS'").fetchone()[0])
        position_snapshot = json.loads(connection.execute("SELECT payload_json FROM snapshots WHERE snapshot_type='POSITIONS'").fetchone()[0])
    assert order_snapshot[0]["normalized"]["status"] == "FILLED"
    assert order_snapshot[0]["normalized"]["broker_order_id"] == "broker-order"
    assert order_snapshot[0]["normalized"]["filled_quantity"] == 300
    assert fill_snapshot[0]["normalized"]["broker_execution_id"] == "execution"
    assert position_snapshot == []
