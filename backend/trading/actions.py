from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


class TradeActionValidationError(ValueError):
    """Raised when an ADD/position action cannot be calculated safely."""


@dataclass(frozen=True)
class AddPlanInput:
    reference_price: float
    risk_reference_price: float
    manual_quantity: int | None = None
    action_risk_budget_pct: float | None = None
    action_risk_budget_amount: float | None = None
    failure_handling: str | None = None


@dataclass(frozen=True)
class AddAccountContext:
    equity: float
    available_cash: float
    current_invested_amount: float
    max_single_position_pct: float
    max_total_exposure_pct: float
    trade_risk_budget_amount: float
    current_market_price: float
    current_position_qty: int
    current_average_cost: float
    current_risk_reference_price: float | None = None
    current_risk_reference_note: str | None = None
    existing_legs: tuple[dict[str, Any], ...] = ()
    max_single_order_notional: float | None = None
    max_single_order_quantity: float | None = None


def _positive(value: float, field: str) -> float:
    if not math.isfinite(value) or value <= 0:
        raise TradeActionValidationError(f"{field} must be finite and greater than 0")
    return float(value)


def _nonnegative(value: float, field: str) -> float:
    if not math.isfinite(value) or value < 0:
        raise TradeActionValidationError(f"{field} must be finite and non-negative")
    return float(value)


class AddPlanCalculator:
    """Calculates an ADD action without imposing a strategy-specific rule."""

    @staticmethod
    def calculate(plan: AddPlanInput, context: AddAccountContext, quantity_step: int = 100) -> dict[str, Any]:
        errors: list[str] = []
        for value, field in ((plan.reference_price, "reference_price"), (plan.risk_reference_price, "risk_reference_price")):
            try:
                _positive(value, field)
            except TradeActionValidationError as exc:
                errors.append(str(exc))
        for value, field in ((context.equity, "equity"), (context.current_market_price, "current_market_price"), (context.current_average_cost, "current_average_cost")):
            try:
                _positive(value, field)
            except TradeActionValidationError as exc:
                errors.append(str(exc))
        for value, field in ((context.available_cash, "available_cash"), (context.current_invested_amount, "current_invested_amount"), (context.trade_risk_budget_amount, "trade_risk_budget_amount")):
            try:
                _nonnegative(value, field)
            except TradeActionValidationError as exc:
                errors.append(str(exc))
        if context.current_position_qty < 0:
            errors.append("current_position_qty cannot be negative")
        for value, field in ((context.max_single_position_pct, "max_single_position_pct"), (context.max_total_exposure_pct, "max_total_exposure_pct")):
            try:
                _positive(value, field)
            except TradeActionValidationError as exc:
                errors.append(str(exc))
        if quantity_step <= 0:
            errors.append("quantity_step must be greater than 0")
        if errors:
            return {"blocking_errors": errors, "warnings": []}

        unit_add_risk = max(0.0, plan.reference_price - plan.risk_reference_price)
        current_capital_risk = 0.0
        giveback_risk = 0.0
        for leg in context.existing_legs:
            remaining_qty = int(leg.get("remaining_qty", 0))
            entry = float(leg.get("actual_avg_entry_price") or leg.get("planned_entry_price") or 0)
            risk_ref = float(leg.get("current_risk_reference_price") or leg.get("initial_risk_reference_price") or 0)
            if remaining_qty < 0 or entry <= 0 or risk_ref <= 0:
                raise TradeActionValidationError("existing leg risk data is incomplete")
            current_capital_risk += max(0.0, (entry - risk_ref) * remaining_qty)
            giveback_risk += max(0.0, (context.current_market_price - risk_ref) * remaining_qty)

        remaining_trade_risk = max(0.0, context.trade_risk_budget_amount - current_capital_risk)
        action_budget = plan.action_risk_budget_amount
        if action_budget is None and plan.action_risk_budget_pct is not None:
            action_budget = context.equity * _nonnegative(plan.action_risk_budget_pct, "action_risk_budget_pct")
        if action_budget is not None:
            action_budget = _nonnegative(action_budget, "action_risk_budget_amount")
            if action_budget > remaining_trade_risk:
                errors.append("action_risk_budget_amount exceeds remaining Trade risk budget")
        risk_budget = min(action_budget, remaining_trade_risk) if action_budget is not None else remaining_trade_risk

        limits: dict[str, float] = {}
        if unit_add_risk > 0:
            limits["RISK_BUDGET"] = risk_budget / unit_add_risk
        current_value = context.current_position_qty * context.current_market_price
        single_capacity = max(0.0, context.equity * context.max_single_position_pct - current_value)
        total_capacity = max(0.0, context.equity * context.max_total_exposure_pct - context.current_invested_amount)
        limits["SINGLE_POSITION_LIMIT"] = single_capacity / plan.reference_price
        limits["TOTAL_POSITION_LIMIT"] = total_capacity / plan.reference_price
        limits["CASH_LIMIT"] = context.available_cash / plan.reference_price
        if context.max_single_order_notional is not None:
            limits["SINGLE_ORDER_AMOUNT_LIMIT"] = _positive(float(context.max_single_order_notional), "max_single_order_notional") / plan.reference_price
        if context.max_single_order_quantity is not None:
            limits["SINGLE_ORDER_QUANTITY_LIMIT"] = _positive(float(context.max_single_order_quantity), "max_single_order_quantity")

        limiting_factor = min(limits, key=limits.get)
        unrounded_qty = int(math.floor(limits[limiting_factor]))
        recommended_qty = int(math.floor(unrounded_qty / quantity_step) * quantity_step)
        planned_qty = plan.manual_quantity if plan.manual_quantity is not None else recommended_qty
        if not isinstance(planned_qty, int) or planned_qty < 0:
            errors.append("manual_quantity must be a non-negative integer")
            planned_qty = 0
        if planned_qty and planned_qty % quantity_step:
            errors.append(f"planned quantity must be a multiple of quantity_step ({quantity_step})")
        if recommended_qty <= 0:
            errors.append("recommended_add_qty must be greater than 0")
        if plan.manual_quantity is not None:
            for name, raw_limit in limits.items():
                if math.isfinite(raw_limit) and planned_qty > raw_limit + 1e-9:
                    errors.append({"SINGLE_ORDER_AMOUNT_LIMIT": "计划金额超过单笔最大金额，请减少计划数量或调整账户设置", "SINGLE_ORDER_QUANTITY_LIMIT": "计划数量超过单笔最大数量，请减少计划数量或调整账户设置"}.get(name, f"manual quantity exceeds {name.lower()}"))

        total_qty = context.current_position_qty + planned_qty
        post_trade_invested_amount = context.current_invested_amount + planned_qty * plan.reference_price
        current_position_cost = context.current_position_qty * context.current_average_cost
        post_trade_position_cost = current_position_cost + planned_qty * plan.reference_price
        incremental_risk = unit_add_risk * planned_qty
        post_trade_capital_risk = current_capital_risk + incremental_risk
        return {
            "unit_add_risk": unit_add_risk,
            "incremental_risk_amount": incremental_risk,
            "current_capital_risk": current_capital_risk,
            "current_giveback_risk": giveback_risk,
            "remaining_trade_risk_budget": remaining_trade_risk,
            "action_risk_budget_amount": action_budget,
            "qty_by_risk": None if unit_add_risk == 0 else int(math.floor(risk_budget / unit_add_risk)),
            "qty_by_single_position": int(math.floor(limits["SINGLE_POSITION_LIMIT"])),
            "qty_by_single_order_amount": int(math.floor(limits["SINGLE_ORDER_AMOUNT_LIMIT"])) if "SINGLE_ORDER_AMOUNT_LIMIT" in limits else None,
            "qty_by_single_order_quantity": int(math.floor(limits["SINGLE_ORDER_QUANTITY_LIMIT"])) if "SINGLE_ORDER_QUANTITY_LIMIT" in limits else None,
            "qty_by_total_position": int(math.floor(limits["TOTAL_POSITION_LIMIT"])),
            "qty_by_cash": int(math.floor(limits["CASH_LIMIT"])),
            "unrounded_recommended_qty": unrounded_qty,
            "recommended_qty": recommended_qty,
            "planned_qty": planned_qty,
            "planned_notional": planned_qty * plan.reference_price,
            "planned_position_pct": (planned_qty * plan.reference_price) / context.equity,
            "post_trade_total_position_pct": post_trade_invested_amount / context.equity,
            "post_trade_position_qty": total_qty,
            "post_trade_average_cost": post_trade_position_cost / total_qty if total_qty else context.current_average_cost,
            "post_trade_capital_risk": post_trade_capital_risk,
            "risk_budget_used_pct": post_trade_capital_risk / context.trade_risk_budget_amount if context.trade_risk_budget_amount else None,
            "limiting_factor": limiting_factor,
            "blocking_errors": errors,
            "warnings": [],
        }


@dataclass(frozen=True)
class ReducePlanInput:
    reduce_method: str
    quantity: int | None = None
    position_pct: float | None = None
    target_remaining_qty: int | None = None
    target_remaining_pct: float | None = None
    reference_price: float | None = None
    minimum_acceptable_price: float | None = None
    trigger_condition: str | None = None


@dataclass(frozen=True)
class PositionActionContext:
    equity: float
    current_position_qty: int
    available_position_qty: int
    average_cost: float
    market_price: float
    current_invested_amount: float
    existing_legs: tuple[dict[str, Any], ...] = ()


def _risk_snapshot(context: PositionActionContext, remaining_qty: int) -> dict[str, float]:
    capital_risk = 0.0
    giveback_risk = 0.0
    current_price = context.market_price
    total_leg_qty = sum(max(0, int(leg.get("remaining_qty", 0))) for leg in context.existing_legs)
    for leg in context.existing_legs:
        leg_qty = max(0, int(leg.get("remaining_qty", 0)))
        if total_leg_qty:
            leg_qty = leg_qty * remaining_qty / total_leg_qty
        entry = float(leg.get("actual_avg_entry_price") or leg.get("planned_entry_price") or context.average_cost)
        risk_ref = float(leg.get("current_risk_reference_price") or leg.get("initial_risk_reference_price") or 0)
        if risk_ref <= 0:
            raise TradeActionValidationError("existing leg risk data is incomplete")
        capital_risk += max(0.0, (entry - risk_ref) * leg_qty)
        giveback_risk += max(0.0, (current_price - risk_ref) * leg_qty)
    return {"capital_risk": capital_risk, "giveback_risk": giveback_risk}


class ReducePlanCalculator:
    @staticmethod
    def calculate(plan: ReducePlanInput, context: PositionActionContext, quantity_step: int = 100) -> dict[str, Any]:
        if context.current_position_qty <= 0:
            raise TradeActionValidationError("当前没有持仓，无法创建减仓计划")
        if not context.existing_legs:
            raise TradeActionValidationError("当前 Trade 缺少成交交易腿，无法计算持仓风险")
        if context.available_position_qty < 0 or context.available_position_qty > context.current_position_qty:
            raise TradeActionValidationError("可卖数量不在当前持仓范围内")
        method = plan.reduce_method
        if method not in {"FIXED_QTY", "POSITION_PCT", "TARGET_REMAINING_QTY", "TARGET_REMAINING_PCT"}:
            raise TradeActionValidationError("reduce_method is invalid")
        if method == "FIXED_QTY":
            requested = plan.quantity
        elif method == "POSITION_PCT":
            requested = math.floor(context.current_position_qty * float(plan.position_pct or 0))
        elif method == "TARGET_REMAINING_QTY":
            requested = context.current_position_qty - int(plan.target_remaining_qty or 0)
        else:
            requested = context.current_position_qty - math.floor(context.current_position_qty * float(plan.target_remaining_pct or 0))
        if requested is None or requested <= 0:
            raise TradeActionValidationError("预计减仓数量必须大于 0")
        executable_qty = min(int(requested), context.available_position_qty)
        executable_qty = math.floor(executable_qty / quantity_step) * quantity_step
        if executable_qty <= 0:
            raise TradeActionValidationError("当前可卖数量不足一个交易单位")
        remaining_qty = context.current_position_qty - executable_qty
        price = float(plan.reference_price or context.market_price)
        if not math.isfinite(price) or price <= 0:
            raise TradeActionValidationError("reference_price must be finite and greater than 0")
        minimum_price = plan.minimum_acceptable_price
        if minimum_price is not None:
            if not math.isfinite(minimum_price) or minimum_price <= 0:
                raise TradeActionValidationError("minimum_acceptable_price must be finite and greater than 0")
            if minimum_price > price:
                raise TradeActionValidationError("minimum_acceptable_price cannot exceed reference_price")
        before = _risk_snapshot(context, context.current_position_qty)
        after = _risk_snapshot(context, remaining_qty)
        realized_pnl = executable_qty * (price - context.average_cost)
        return {
            "requested_qty": int(requested),
            "planned_qty": int(executable_qty),
            "remaining_qty": int(remaining_qty),
            "planned_notional": executable_qty * price,
            "reference_price": price,
            "minimum_acceptable_price": minimum_price,
            "trigger_condition": plan.trigger_condition,
            "realized_pnl": realized_pnl,
            "remaining_position_pct": remaining_qty * context.market_price / context.equity,
            "capital_risk_before": before["capital_risk"],
            "capital_risk_after": after["capital_risk"],
            "giveback_risk_before": before["giveback_risk"],
            "giveback_risk_after": after["giveback_risk"],
            "t_plus_one_limited": executable_qty < requested,
            "blocking_errors": [],
            "warnings": [],
        }


class ClosePlanCalculator:
    @staticmethod
    def calculate(context: PositionActionContext, reference_price: float | None = None, minimum_acceptable_price: float | None = None, trigger_condition: str | None = None, quantity_step: int = 100) -> dict[str, Any]:
        return ReducePlanCalculator.calculate(
            ReducePlanInput("FIXED_QTY", quantity=context.current_position_qty, reference_price=reference_price, minimum_acceptable_price=minimum_acceptable_price, trigger_condition=trigger_condition),
            context,
            quantity_step,
        )
