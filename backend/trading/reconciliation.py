from __future__ import annotations

from typing import Any

from .account import normalize_symbol
from .execution import ExecutionStore


class ReconciliationService:
    """Compares broker facts with local records and records every discrepancy."""

    def __init__(self, store: ExecutionStore, account_id: int):
        self.store = store
        if account_id <= 0:
            raise ValueError("account_id must be positive")
        self.account_id = account_id

    def compare_positions(self, local_positions: list[dict[str, Any]], broker_positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        qualified_symbols = any(
            any(marker in str(item.get("symbol") or "") for marker in (":", "."))
            for item in [*local_positions, *broker_positions]
        )

        def key(item: dict[str, Any]) -> str:
            value = str(item.get("symbol") or "").strip().upper()
            # Preserve plain-code test/data keys for backward compatibility;
            # whenever either side carries an exchange-qualified symbol,
            # compare both sides in the canonical EXCHANGE:CODE form.
            return normalize_symbol(value) if qualified_symbols else value

        local = {key(item): item for item in local_positions}
        broker = {key(item): item for item in broker_positions}
        issues: list[dict[str, Any]] = []
        for symbol in sorted(set(local) | set(broker)):
            local_item = local.get(symbol)
            broker_item = broker.get(symbol)
            if local_item is not None and (local_item.get("quantity") is None or local_item.get("available_quantity") is None):
                raise ValueError(f"Local position snapshot missing quantity fields for {symbol}")
            if broker_item is not None and (broker_item.get("quantity") is None or broker_item.get("available_quantity") is None):
                raise ValueError(f"Broker position snapshot missing quantity fields for {symbol}")
            local_qty = int(local_item.get("quantity", 0)) if local_item else 0
            broker_qty = int(broker_item.get("quantity", 0)) if broker_item else 0
            local_available = int(local_item.get("available_quantity", 0)) if local_item else 0
            broker_available = int(broker_item.get("available_quantity", 0)) if broker_item else 0
            if local_qty != broker_qty:
                issues.append(self.store.add_reconciliation_issue(self.account_id, {"issue_type": "POSITION_QUANTITY_MISMATCH", "symbol": symbol, "local_value": {"quantity": local_qty}, "broker_value": {"quantity": broker_qty}}))
            elif local_available != broker_available:
                issues.append(self.store.add_reconciliation_issue(self.account_id, {"issue_type": "POSITION_AVAILABLE_QUANTITY_MISMATCH", "symbol": symbol, "local_value": {"quantity": local_qty, "available_quantity": local_available}, "broker_value": {"quantity": broker_qty, "available_quantity": broker_available}}))
            elif hasattr(self.store, "resolve_position_mismatch"):
                self.store.resolve_position_mismatch(self.account_id, symbol, local_qty, broker_qty, local_available, broker_available)
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
