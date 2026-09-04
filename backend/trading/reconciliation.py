from __future__ import annotations

from typing import Any

from .execution import ExecutionStore


class ReconciliationService:
    """Compares broker facts with local records and records every discrepancy."""

    def __init__(self, store: ExecutionStore, account_id: int):
        self.store = store
        if account_id <= 0:
            raise ValueError("account_id must be positive")
        self.account_id = account_id

    def compare_positions(self, local_positions: list[dict[str, Any]], broker_positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        local = {item["symbol"]: item for item in local_positions}
        broker = {item["symbol"]: item for item in broker_positions}
        issues: list[dict[str, Any]] = []
        for symbol in sorted(set(local) | set(broker)):
            local_item = local.get(symbol)
            broker_item = broker.get(symbol)
            local_qty = int(local_item.get("quantity", 0)) if local_item else 0
            broker_qty = int(broker_item.get("quantity", 0)) if broker_item else 0
            if local_qty != broker_qty:
                issues.append(self.store.add_reconciliation_issue(self.account_id, {"issue_type": "POSITION_QUANTITY_MISMATCH", "symbol": symbol, "local_value": {"quantity": local_qty}, "broker_value": {"quantity": broker_qty}}))
        return issues

    def compare_orders(self, local_orders: list[dict[str, Any]], broker_orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        local = {item.get("broker_order_id"): item for item in local_orders if item.get("broker_order_id")}
        broker_client_ids = {str(item.get("client_order_id")) for item in broker_orders if item.get("client_order_id")}
        existing_issues = self.store.list_reconciliation_issues(self.account_id) if hasattr(self.store, "list_reconciliation_issues") else []
        existing_unconfirmed = {
            str((issue.get("local_value") or {}).get("client_order_id"))
            for issue in existing_issues
            if issue.get("issue_type") == "LOCAL_ORDER_UNCONFIRMED"
        }
        issues: list[dict[str, Any]] = []
        for item in local_orders:
            client_id = item.get("client_order_id")
            if item.get("status") in {"PENDING_SUBMIT", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"} and not item.get("broker_order_id") and str(client_id) not in broker_client_ids and str(client_id) not in existing_unconfirmed:
                issues.append(self.store.add_reconciliation_issue(self.account_id, {"issue_type": "LOCAL_ORDER_UNCONFIRMED", "symbol": item.get("symbol"), "local_value": item, "broker_value": None}))
        for item in broker_orders:
            broker_id = item.get("broker_order_id") or item.get("order_id")
            if broker_id and broker_id not in local:
                issues.append(self.store.add_reconciliation_issue(self.account_id, {"issue_type": "UNMATCHED_BROKER_ORDER", "symbol": item.get("symbol"), "local_value": None, "broker_value": item}))
        return issues
