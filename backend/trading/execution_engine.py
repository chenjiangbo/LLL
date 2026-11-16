"""Phase 5 orchestration for the main-system execution boundary.

This module owns only ExecutionPlan condition evaluation and orchestration. It
does not decide positions, create plans, retry orders, or implement broker
algorithms; those remain in the existing trading domain and Broker Node.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from .broker import BrokerGateway
from .execution import OrderInput, PreTradeRisk, PreTradeRiskResult, execution_plan_start_reached
from .order_types import canonical_order_type, validate_order_price, validate_order_type_for_exchange


@dataclass(frozen=True)
class ExecutionDecision:
    status: str
    reason: str
    trigger_snapshot: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionSubmission:
    decision: ExecutionDecision
    risk: PreTradeRiskResult
    order: dict[str, Any]
    broker_response: dict[str, Any]


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{field} must be greater than zero")
    return result


def _quote_symbol(plan_symbol: str) -> str:
    if ":" in plan_symbol:
        exchange, code = plan_symbol.split(":", 1)
        if exchange in {"SH", "SZ"} and code:
            return f"{exchange}:{code}"
    if "." in plan_symbol:
        exchange, code = plan_symbol.split(".", 1)
        exchange = {"SSE": "SH", "SHSE": "SH", "SZSE": "SZ"}.get(exchange)
        if exchange and code:
            return f"{exchange}:{code}"
    raise ValueError(f"execution plan symbol must include exchange: {plan_symbol}")


class ExecutionEngine:
    """Evaluate one active plan against one current quote and submit one order."""

    def __init__(self, gateway: BrokerGateway):
        self.gateway = gateway

    def evaluate(self, plan: dict[str, Any], quote: dict[str, Any]) -> ExecutionDecision:
        if plan.get("status") != "ACTIVE":
            return ExecutionDecision("WAIT", "EXECUTION_PLAN_NOT_ACTIVE")
        if not execution_plan_start_reached(plan):
            return ExecutionDecision("WAIT", "SCHEDULED_START_NOT_REACHED")
        expected_symbol = _quote_symbol(str(plan["symbol"]))
        if quote.get("symbol_key") != expected_symbol:
            raise ValueError("quote does not belong to execution plan instrument")
        snapshot = dict(quote)
        execution_type = plan.get("execution_type")
        params = plan.get("execution_params") or plan.get("execution_params_json") or {}
        requires_fresh = execution_type in {"PRICE_TRIGGER", "PRICE_RANGE"} or bool(params.get("require_fresh_quote"))
        if requires_fresh and quote.get("freshness") != "FRESH":
            return ExecutionDecision("BLOCK", "MARKET_STALE", snapshot)
        # LIMIT orders are valid without a live quote.  The execution cycle
        # supplies an explicit NOT_REQUIRED snapshot after the risk and node
        # safety gates have passed; only conditional execution needs `last`.
        last = None
        if execution_type in {"PRICE_TRIGGER", "PRICE_RANGE"}:
            last = _decimal(quote.get("last"), "quote.last")
        if execution_type == "PRICE_TRIGGER":
            trigger = _decimal(params.get("trigger_price"), "trigger_price")
            triggered = last <= trigger if plan["side"] == "BUY" else last >= trigger
            return ExecutionDecision("READY" if triggered else "WAIT", "TRIGGERED" if triggered else "TRIGGER_NOT_MET", snapshot)
        if execution_type == "PRICE_RANGE":
            low = _decimal(params.get("low_price"), "low_price")
            high = _decimal(params.get("high_price"), "high_price")
            if low > high:
                raise ValueError("low_price cannot exceed high_price")
            inside = low <= last <= high
            return ExecutionDecision("READY" if inside else "WAIT", "IN_RANGE" if inside else "OUT_OF_RANGE", snapshot)
        if execution_type not in {"LIMIT", "PERSISTENT_LIMIT"}:
            raise ValueError(f"unsupported execution type: {execution_type}")
        exchange = expected_symbol.split(":", 1)[0]
        order_type = validate_order_type_for_exchange(exchange, params.get("order_type"))
        if execution_type == "PERSISTENT_LIMIT" and order_type != "LIMIT":
            raise ValueError("持续限价执行方式只能使用普通限价委托")
        return ExecutionDecision("READY", "LIMIT_READY", snapshot)

    def submit(
        self,
        plan: dict[str, Any],
        quote: dict[str, Any],
        account: dict[str, Any],
        risk_profile: dict[str, Any],
        positions: list[dict[str, Any]],
        active_orders: list[dict[str, Any]],
        broker_account_key: str,
        request_id: str,
        client_order_id: str,
        create_order: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> ExecutionSubmission | None:
        decision = self.evaluate(plan, quote)
        if decision.status != "READY":
            return None
        params = plan.get("execution_params") or plan.get("execution_params_json") or {}
        order_type = canonical_order_type(params.get("order_type"))
        exchange, _ = _quote_symbol(str(plan["symbol"])).split(":", 1)
        order_type = validate_order_type_for_exchange(exchange, order_type)
        price_key = "limit_price" if order_type == "LIMIT" else "protection_price"
        price = validate_order_price(exchange, order_type, params.get(price_key))
        order_input = OrderInput(
            execution_plan_id=int(plan["id"]),
            symbol=str(plan["symbol"]),
            side=str(plan["side"]),
            order_type=order_type,
            quantity=int(plan["remaining_qty"]),
            price=price,
        )
        risk = PreTradeRisk.check(account, risk_profile, plan, order_input, positions, active_orders, datetime.now(UTC))
        if risk.status == "BLOCK":
            raise ValueError({"code": "PRETRADE_RISK_BLOCK", "checks": risk.checks})
        payload = {
            "request_id": request_id,
            "client_order_id": client_order_id,
            "broker_account_key": broker_account_key,
            # Broker Node V1.2 validates code/exchange at the top level.
            "code": _quote_symbol(str(plan["symbol"])).split(":", 1)[1],
            "exchange": _quote_symbol(str(plan["symbol"])).split(":", 1)[0],
            "instrument": {
                "code": _quote_symbol(str(plan["symbol"])).split(":", 1)[1],
                "exchange": _quote_symbol(str(plan["symbol"])).split(":", 1)[0],
            },
            "side": plan["side"],
            "order_type": order_type,
            "quantity": order_input.quantity,
            "source": {"execution_plan_id": plan["id"], "execution_type": plan["execution_type"], "order_type": order_type},
            "safety_constraints": {
                **params.get("safety_constraints", {}),
            },
            "trigger_snapshot": decision.trigger_snapshot,
        }
        if price is not None:
            payload["price"] = str(price)
        local_order = create_order(payload)
        broker_response = self.gateway.submit_order(payload)
        return ExecutionSubmission(decision, risk, local_order, broker_response)
