from __future__ import annotations

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
