"""Account-scoped, idempotent consumption of Broker Node durable events."""
from __future__ import annotations

from typing import Any

from .broker_node_consumer import BrokerEventConsumer
from .execution import ExecutionStore, ExecutionValidationError


class BrokerEventSyncService:
    def __init__(self, execution_store: ExecutionStore, trading_store: Any, gateway_factory: Any):
        self.execution_store = execution_store
        self.trading_store = trading_store
        self.gateway_factory = gateway_factory

    @staticmethod
    def _payload(event: dict[str, Any]) -> dict[str, Any] | list[Any]:
        payload = event.get("payload")
        if not isinstance(payload, (dict, list)):
            raise RuntimeError(f"Broker event {event.get('seq')} has malformed payload")
        return payload

    @staticmethod
    def _items(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
        raw = payload
        if isinstance(payload, dict):
            for key in ("items", "data", "orders", "fills", "positions", "records"):
                if key in payload:
                    raw = payload[key]
                    break
        if isinstance(raw, dict):
            return [raw]
        if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
            raise RuntimeError("Broker snapshot payload must contain object items")
        return raw

    def sync_account(self, account_id: int) -> dict[str, int]:
        account = self.trading_store.get_broker_account(account_id)
        if not account:
            raise ExecutionValidationError("broker account not found")
        gateway = self.gateway_factory(account_id)

        def apply(event: dict[str, Any]) -> None:
            event_account_key = event.get("broker_account_key")
            payload = self._payload(event)
            items = self._items(payload)
            if isinstance(payload, dict):
                event_account_key = event_account_key or payload.get("broker_account_key")
            if event_account_key and str(event_account_key) != str(account["broker_account_key"]):
                raise RuntimeError(f"Broker event {event.get('seq')} belongs to another account")
            event_type = str(event.get("event_type") or "")
            if event_type in {"ORDER_SNAPSHOT_UPDATED", "ORDER_STATUS", "ORDER_SUBMIT_RESULT"}:
                for item in items:
                    client_id = item.get("client_order_id") or event.get("client_order_id")
                    broker_id = item.get("broker_order_id") or item.get("order_id") or event.get("broker_order_id")
                    local = self.execution_store.find_order_by_broker_reference(account_id, client_id, broker_id)
                    if not local:
                        self.execution_store.add_reconciliation_issue(account_id, {"issue_type": "UNMATCHED_BROKER_ORDER_EVENT", "symbol": item.get("symbol"), "broker_value": item})
                        continue
                    normalized = item.get("normalized") if isinstance(item.get("normalized"), dict) else {}
                    status = item.get("status") or item.get("normalized_status") or normalized.get("status")
                    if not status:
                        raise RuntimeError(f"Broker order event {event.get('seq')} has no normalized status")
                    status = str(status).upper()
                    if status in {"QUEUED", "CLAIMED", "DISPATCHING"}:
                        status = "SUBMITTED"
                    self.execution_store.record_order_update(account_id, int(local["id"]), {"status": status, "broker_order_id": broker_id, "reject_code": item.get("reject_code"), "reject_message": item.get("reject_message"), "raw_broker_data": item})
            elif event_type in {"FILL_SNAPSHOT_UPDATED", "FILL"}:
                for item in items:
                    client_id = item.get("client_order_id") or event.get("client_order_id")
                    broker_id = item.get("broker_order_id") or event.get("broker_order_id")
                    local = self.execution_store.find_order_by_broker_reference(account_id, client_id, broker_id)
                    fill_id = item.get("broker_execution_id") or item.get("exec_id") or item.get("fill_id") or event.get("broker_execution_id")
                    if not local:
                        self.execution_store.add_reconciliation_issue(account_id, {"issue_type": "UNMATCHED_BROKER_FILL", "symbol": item.get("symbol"), "broker_value": item})
                        continue
                    if not fill_id:
                        raise RuntimeError(f"Broker fill event {event.get('seq')} has no execution id")
                    self.execution_store.record_fill(account_id, int(local["id"]), {"broker_fill_id": str(fill_id), "broker_order_id": broker_id, "quantity": int(item.get("quantity") or item.get("filled_quantity") or item.get("filled_qty") or 0), "price": item.get("price") or item.get("avg_price") or item.get("fill_price"), "filled_at": item.get("filled_at") or item.get("execution_time") or item.get("trade_time"), "commission": item.get("commission", 0), "tax": item.get("tax", 0), "other_fee": item.get("other_fee", 0), "raw_broker_data": item})
            elif event_type in {"ACCOUNT_SNAPSHOT_UPDATED", "POSITION_SNAPSHOT_UPDATED"}:
                # These are normal periodic snapshot notifications, not
                # reconciliation failures.  The snapshot facts are reconciled
                # by the explicit reconciliation query, while this durable
                # event is acknowledged without generating a false alarm.
                return

        consumer = BrokerEventConsumer(gateway, lambda: self.execution_store.get_event_cursor(account_id), lambda seq: self.execution_store.save_event_cursor(account_id, seq), apply)
        return consumer.consume_all()
