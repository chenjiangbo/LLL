from __future__ import annotations

from typing import Any

from broker_node.gm_agent.event_writer import EventWriter
from broker_node.gm_agent.gm_mapper import map_fill, map_order
from broker_node.shared.db import connect


class CallbackHandlers:
    def __init__(self, events: EventWriter, durable_db=None):
        self.events = events
        self.durable_db = durable_db

    def on_order_status(self, order: Any) -> None:
        mapped = map_order(order)
        normalized = mapped["normalized"]
        self.events.append(
            "ORDER_STATUS",
            mapped,
            "CALLBACK",
            client_order_id=normalized.get("client_order_id"),
            broker_order_id=normalized.get("broker_order_id"),
            occurred_at=normalized.get("updated_at"),
            event_id="order-status:{}:{}:{}".format(normalized.get("broker_order_id"), normalized.get("raw_status"), normalized.get("updated_at")),
        )
        if self.durable_db and normalized.get("client_order_id"):
            with connect(self.durable_db) as connection:
                connection.execute("UPDATE order_links SET last_broker_status=?,last_raw_status=?,updated_at=? WHERE client_order_id=?", (normalized.get("status"), normalized.get("raw_status"), normalized.get("updated_at"), normalized.get("client_order_id")))

    def on_execution_report(self, report: Any) -> None:
        mapped = map_fill(report)
        normalized = mapped["normalized"]
        self.events.append(
            "FILL",
            mapped,
            "CALLBACK",
            client_order_id=normalized.get("client_order_id"),
            broker_order_id=normalized.get("broker_order_id"),
            broker_execution_id=normalized.get("broker_execution_id"),
            occurred_at=normalized.get("occurred_at"),
            event_id="fill:{}".format(normalized.get("broker_execution_id")),
        )

    def on_error(self, code: Any, info: Any) -> None:
        self.events.append(
            "GM_ERROR",
            {"code": code, "info": info},
            "CALLBACK",
        )
