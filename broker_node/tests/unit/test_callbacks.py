from __future__ import annotations

import json
from pathlib import Path

from broker_node.gm_agent.callbacks import CallbackHandlers
from broker_node.gm_agent.event_writer import EventWriter
from broker_node.shared.db import connect, initialize


def test_order_and_fill_callbacks_write_real_identifiers(tmp_path: Path) -> None:
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    handlers = CallbackHandlers(EventWriter(db))
    handlers.on_order_status({"cl_ord_id": "client", "order_id": "broker", "ex_ord_id": "exchange", "symbol": "SZSE.000661", "side": 1, "status": 3, "volume": 100, "filled_volume": 100, "filled_vwap": 70.0, "filled_amount": 7000.0})
    handlers.on_execution_report({"exec_id": "execution", "order_id": "broker", "cl_ord_id": "client", "symbol": "SZSE.000661", "side": 1, "price": 70.0, "volume": 100, "amount": 7000.0})
    with connect(db) as connection:
        rows = connection.execute("select event_type, broker_order_id, broker_execution_id from broker_events order by seq").fetchall()
    assert [(row[0], row[1], row[2]) for row in rows] == [("ORDER_STATUS", "broker", None), ("FILL", "broker", "execution")]


def test_callbacks_map_gm_generated_client_id_to_local_order(tmp_path: Path) -> None:
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    now = "2026-09-05T00:53:17.350935+08:00"
    with connect(db) as connection:
        connection.execute(
            "INSERT INTO commands(command_id,request_id,command_type,client_order_id,payload_hash,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "submit-command", "request", "ORDER_SUBMIT", "LLL-local", "hash",
                '{"code":"600000","exchange":"SH","side":"BUY","price":"9.43","quantity":100}',
                "ACKED", now, now,
            ),
        )
    handlers = CallbackHandlers(EventWriter(db), db)
    handlers.on_execution_report({
        "exec_id": "execution", "order_id": "broker", "cl_ord_id": "gm-generated",
        "symbol": "SHSE.600000", "side": 1, "price": 9.43, "volume": 100,
        "amount": 943.0, "created_at": "2026-09-05 00:53:17.751493+08:00",
    })
    with connect(db) as connection:
        event = connection.execute("SELECT client_order_id, broker_order_id, broker_execution_id, payload_json FROM broker_events").fetchone()
        link = connection.execute("SELECT client_order_id, broker_client_order_id, broker_order_id FROM order_links").fetchone()
        command = connection.execute("SELECT broker_order_id FROM commands WHERE command_id='submit-command'").fetchone()
    assert tuple(event[:3]) == ("LLL-local", "broker", "execution")
    assert json.loads(event[3])["normalized"]["broker_client_order_id"] == "gm-generated"
    assert tuple(link) == ("LLL-local", "gm-generated", "broker")
    assert command[0] == "broker"
