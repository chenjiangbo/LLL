"""Account-scoped, idempotent consumption of Broker Node durable events."""
from __future__ import annotations

from typing import Any

from .broker_node_consumer import BrokerEventConsumer
from .execution import ExecutionStore, ExecutionValidationError


class BrokerEventSyncService:
    _BROKER_ORDER_STATUS = {
        "NEW": "SUBMITTED",
        "PENDING_NEW": "SUBMITTED",
        "QUEUED": "SUBMITTED",
        "CLAIMED": "SUBMITTED",
        "DISPATCHING": "SUBMITTED",
        "SUBMITTED": "SUBMITTED",
        "ACCEPTED": "ACCEPTED",
        "PARTIALLY_FILLED": "PARTIALLY_FILLED",
        "FILLED": "FILLED",
        "CANCEL_PENDING": "CANCEL_PENDING",
        "CANCELLED": "CANCELLED",
        "CANCELED": "CANCELLED",
        "REJECTED": "REJECTED",
        "EXPIRED": "EXPIRED",
    }
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

    @staticmethod
    def _normalized_item(item: dict[str, Any]) -> dict[str, Any]:
        """Expose the Broker Node normalized fields at one explicit layer.

        Snapshot payloads contain ``normalized`` and ``raw`` siblings.  The
        normalized contract is authoritative for linking and state changes;
        raw data is retained as audit data but must not hide the normalized
        identifiers one level below the event item.
        """
        normalized = item.get("normalized")
        raw = item.get("raw")
        if normalized is not None and not isinstance(normalized, dict):
            raise RuntimeError("Broker snapshot normalized item must be an object")
        if raw is not None and not isinstance(raw, dict):
            raise RuntimeError("Broker snapshot raw item must be an object")
        result = {
            **(raw if isinstance(raw, dict) else {}),
            **(normalized if isinstance(normalized, dict) else item),
            "raw_broker_data": item,
        }
        instrument = result.get("instrument") if isinstance(result.get("instrument"), dict) else {}
        if instrument.get("code"):
            result["symbol"] = str(instrument["code"])
        if instrument.get("exchange"):
            result["exchange"] = str(instrument["exchange"])
        return result

    def _apply_order_items(self, account_id: int, items: list[dict[str, Any]], event: dict[str, Any]) -> int:
        applied = 0
        for item in items:
            broker_item = self._normalized_item(item)
            client_id = broker_item.get("client_order_id") or event.get("client_order_id")
            broker_id = broker_item.get("broker_order_id") or broker_item.get("order_id") or event.get("broker_order_id")
            local = self.execution_store.find_order_by_broker_reference(account_id, client_id, broker_id)
            if not local:
                self.execution_store.add_reconciliation_issue(account_id, {"issue_type": "UNMATCHED_BROKER_ORDER_EVENT", "symbol": broker_item.get("symbol"), "broker_value": item})
                continue
            status = broker_item.get("status") or broker_item.get("normalized_status")
            if not status:
                raise RuntimeError(f"Broker order event {event.get('seq')} has no normalized status")
            status = self._BROKER_ORDER_STATUS.get(str(status).upper())
            if not status:
                raise RuntimeError(f"Broker order event {event.get('seq')} has unsupported normalized status")
            if local.get("status") in {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"} and status != local["status"]:
                # A durable snapshot can arrive after a newer terminal event.
                # Preserve the terminal local state; the stale broker fact is
                # still retained in the event log and must not block replay.
                continue
            if local.get("status") == "CANCEL_PENDING" and status in {"SUBMITTED", "ACCEPTED"}:
                # The submit acknowledgement can be delivered after the user
                # has already requested cancellation.  It is an older broker
                # fact, not a valid transition back from CANCEL_PENDING.  The
                # event is acknowledged by advancing the cursor, while the
                # local cancellation state remains authoritative until the
                # broker emits CANCELLED, FILLED, or another valid outcome.
                continue
            self.execution_store.record_order_update(account_id, int(local["id"]), {"status": status, "broker_order_id": broker_id, "reject_code": broker_item.get("reject_code"), "reject_message": broker_item.get("reject_message"), "raw_broker_data": item})
            applied += 1
        return applied

    def _apply_fill_items(self, account_id: int, items: list[dict[str, Any]], event: dict[str, Any]) -> int:
        applied = 0
        for item in items:
            broker_item = self._normalized_item(item)
            client_id = broker_item.get("client_order_id") or event.get("client_order_id")
            broker_id = broker_item.get("broker_order_id") or event.get("broker_order_id")
            local = self.execution_store.find_order_by_broker_reference(account_id, client_id, broker_id)
            fill_id = broker_item.get("broker_execution_id") or broker_item.get("exec_id") or broker_item.get("fill_id") or event.get("broker_execution_id")
            if not local:
                self.execution_store.add_reconciliation_issue(account_id, {"issue_type": "UNMATCHED_BROKER_FILL", "symbol": broker_item.get("symbol"), "broker_value": item})
                continue
            if not fill_id:
                raise RuntimeError(f"Broker fill event {event.get('seq')} has no execution id")
            self.execution_store.record_fill(account_id, int(local["id"]), {"broker_fill_id": str(fill_id), "broker_order_id": broker_id, "quantity": int(broker_item.get("quantity") or broker_item.get("filled_quantity") or broker_item.get("filled_qty") or 0), "price": broker_item.get("price") or broker_item.get("avg_price") or broker_item.get("fill_price"), "filled_at": broker_item.get("filled_at") or broker_item.get("execution_time") or broker_item.get("trade_time") or broker_item.get("occurred_at"), "commission": broker_item.get("commission", 0), "tax": broker_item.get("tax", 0), "other_fee": broker_item.get("other_fee", 0), "raw_broker_data": item})
            applied += 1
        return applied

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
                self._apply_order_items(account_id, items, event)
            elif event_type in {"FILL_SNAPSHOT_UPDATED", "FILL"}:
                self._apply_fill_items(account_id, items, event)
            elif event_type in {"ACCOUNT_SNAPSHOT_UPDATED", "POSITION_SNAPSHOT_UPDATED"}:
                # These are normal periodic snapshot notifications, not
                # reconciliation failures.  The snapshot facts are reconciled
                # by the explicit reconciliation query, while this durable
                # event is acknowledged without generating a false alarm.
                return

        consumer = BrokerEventConsumer(gateway, lambda: self.execution_store.get_event_cursor(account_id), lambda seq: self.execution_store.save_event_cursor(account_id, seq), apply)
        return consumer.consume_all()

    def sync_current_snapshots(self, account_id: int) -> dict[str, int]:
        """Apply the current authoritative order/fill snapshots.

        This repairs a safe, already-consumed event window after Broker Node
        establishes a previously missing local-order link.  It does not infer
        identity from symbol/price/quantity: only normalized snapshot IDs are
        accepted by ``find_order_by_broker_reference``.
        """
        account = self.trading_store.get_broker_account(account_id)
        if not account:
            raise ExecutionValidationError("broker account not found")
        gateway = self.gateway_factory(account_id)
        account_snapshot = gateway.get_account()
        account_payload = account_snapshot.get("payload") if isinstance(account_snapshot, dict) else None
        if not isinstance(account_payload, dict):
            raise RuntimeError("Broker account snapshot payload must be an object")
        account_normalized = self._normalized_item(account_payload)
        broker_positions = gateway.get_positions()
        position_items = [self._normalized_item(item) for item in broker_positions]
        self.trading_store.apply_broker_account_snapshot(account_id, account_normalized)
        self.trading_store.apply_broker_positions_snapshot(account_id, position_items)
        orders = gateway.get_orders()
        fills = gateway.get_fills()
        applied_orders = 0
        applied_fills = 0
        resolved_issues = 0
        for item in orders:
            broker_item = self._normalized_item(item)
            client_id = broker_item.get("client_order_id")
            broker_id = broker_item.get("broker_order_id") or broker_item.get("order_id")
            if not client_id and not broker_id:
                raise RuntimeError("Broker order snapshot item has no durable identity")
            local = self.execution_store.find_order_by_broker_reference(account_id, client_id, broker_id)
            if not local:
                self.execution_store.add_reconciliation_issue(account_id, {"issue_type": "UNMATCHED_BROKER_ORDER_EVENT", "symbol": broker_item.get("symbol"), "broker_value": item})
                continue
            status = self._BROKER_ORDER_STATUS.get(str(broker_item.get("status") or "").upper())
            if not status:
                raise RuntimeError("Broker order snapshot item has no normalized status")
            if local.get("status") in {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"} and status != local["status"]:
                continue
            self.execution_store.record_order_update(account_id, int(local["id"]), {"status": status, "broker_order_id": broker_id, "reject_code": broker_item.get("reject_code"), "reject_message": broker_item.get("reject_message"), "raw_broker_data": item})
            resolved_issues += self.execution_store.resolve_linked_broker_issues(account_id, int(local["id"]), str(broker_id), str(broker_item.get("broker_client_order_id") or "") or None)
            applied_orders += 1
        for item in fills:
            broker_item = self._normalized_item(item)
            client_id = broker_item.get("client_order_id")
            broker_id = broker_item.get("broker_order_id") or broker_item.get("order_id")
            fill_id = broker_item.get("broker_execution_id") or broker_item.get("exec_id") or broker_item.get("fill_id")
            if not fill_id or (not client_id and not broker_id):
                raise RuntimeError("Broker fill snapshot item has incomplete durable identity")
            local = self.execution_store.find_order_by_broker_reference(account_id, client_id, broker_id)
            if not local:
                self.execution_store.add_reconciliation_issue(account_id, {"issue_type": "UNMATCHED_BROKER_FILL", "symbol": broker_item.get("symbol"), "broker_value": item})
                continue
            self.execution_store.record_fill(account_id, int(local["id"]), {"broker_fill_id": str(fill_id), "broker_order_id": broker_id, "quantity": int(broker_item.get("quantity") or broker_item.get("filled_quantity") or broker_item.get("filled_qty") or 0), "price": broker_item.get("price") or broker_item.get("avg_price") or broker_item.get("fill_price"), "filled_at": broker_item.get("filled_at") or broker_item.get("execution_time") or broker_item.get("trade_time") or broker_item.get("occurred_at"), "commission": broker_item.get("commission", 0), "tax": broker_item.get("tax", 0), "other_fee": broker_item.get("other_fee", 0), "raw_broker_data": item})
            resolved_issues += self.execution_store.resolve_linked_broker_issues(account_id, int(local["id"]), str(broker_id), str(broker_item.get("broker_client_order_id") or "") or None, str(fill_id))
            applied_fills += 1
        self.trading_store.rebuild_positions_from_local_fills(account_id)
        return {"orders": applied_orders, "fills": applied_fills, "resolved_issues": resolved_issues}
