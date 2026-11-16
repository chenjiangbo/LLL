import pytest

from backend.trading.actions import AddAccountContext, AddPlanCalculator, AddPlanInput, ClosePlanCalculator, PositionActionContext, ReducePlanCalculator, ReducePlanInput
from backend.trading.account import normalize_symbol
from backend.trading.execution import ExecutionPlanInput, OrderInput, PreTradeRisk


def context(**overrides):
    value = dict(
        equity=100000,
        available_cash=100000,
        current_invested_amount=10000,
        max_single_position_pct=0.2,
        max_total_exposure_pct=1.0,
        trade_risk_budget_amount=1000,
        current_market_price=12,
        current_position_qty=500,
        current_average_cost=10,
        existing_legs=({
            "remaining_qty": 500,
            "actual_avg_entry_price": 10,
            "current_risk_reference_price": 9.4,
        },),
    )
    value.update(overrides)
    return AddAccountContext(**value)


def test_add_calculates_incremental_and_giveback_risk():
    result = AddPlanCalculator.calculate(AddPlanInput(12, 11.4), context())
    assert result["unit_add_risk"] == pytest.approx(0.6)
    assert result["current_capital_risk"] == pytest.approx(300)
    assert result["current_giveback_risk"] == pytest.approx(1300)
    assert result["incremental_risk_amount"] == result["planned_qty"] * result["unit_add_risk"]


def test_add_average_cost_uses_only_the_current_position_not_all_account_positions():
    result = AddPlanCalculator.calculate(AddPlanInput(12, 11.4, manual_quantity=100), context())
    assert result["post_trade_average_cost"] == pytest.approx((500 * 10 + 100 * 12) / 600)


def test_add_uses_action_budget_when_present():
    result = AddPlanCalculator.calculate(
        AddPlanInput(12, 11.4, action_risk_budget_amount=400),
        context(),
    )
    assert result["action_risk_budget_amount"] == 400
    assert result["qty_by_risk"] == 666


def test_add_blocks_manual_quantity_above_hard_limit():
    result = AddPlanCalculator.calculate(AddPlanInput(12, 11.4, manual_quantity=2000), context())
    assert any("single_position_limit" in item for item in result["blocking_errors"])


def position_context(**overrides):
    value = dict(equity=100000, current_position_qty=1000, available_position_qty=800, average_cost=10, market_price=12, current_invested_amount=20000, existing_legs=context().existing_legs)
    value.update(overrides)
    return PositionActionContext(**value)


def test_reduce_respects_t_plus_one_and_calculates_remaining_risk():
    result = ReducePlanCalculator.calculate(ReducePlanInput("POSITION_PCT", position_pct=0.5, reference_price=12), position_context())
    assert result["planned_qty"] == 500
    assert result["remaining_qty"] == 500
    assert result["t_plus_one_limited"] is False
    assert result["realized_pnl"] == 1000


def test_close_is_limited_to_available_quantity():
    result = ClosePlanCalculator.calculate(position_context(), 12)
    assert result["planned_qty"] == 800
    assert result["remaining_qty"] == 200
    assert result["t_plus_one_limited"] is True


def test_reduce_rejects_minimum_price_above_reference_price():
    with pytest.raises(Exception, match="minimum_acceptable_price cannot exceed reference_price"):
        ReducePlanCalculator.calculate(
            ReducePlanInput("FIXED_QTY", quantity=100, reference_price=12, minimum_acceptable_price=12.1),
            position_context(),
        )


def test_close_preserves_sell_constraints_in_calculation():
    result = ClosePlanCalculator.calculate(position_context(), 12, 11.8, "跌破风险位")
    assert result["minimum_acceptable_price"] == pytest.approx(11.8)
    assert result["trigger_condition"] == "跌破风险位"


def test_symbol_aliases_are_compared_in_canonical_form():
    assert normalize_symbol("000977") == "SZ:000977"
    assert normalize_symbol("SZSE.000977") == "SZ:000977"
    result = PreTradeRisk.check(
        account={"configuration_confirmed": True, "status": "ACTIVE", "available_cash": 100000, "equity": 100000},
        risk_profile={"configuration_confirmed": True, "max_single_position_pct": 0.5, "max_total_exposure_pct": 1.0},
        execution_plan={"status": "ACTIVE", "remaining_qty": 100},
        order=OrderInput(1, "000977", "BUY", "LIMIT", 100, 10, 2),
        positions=[{"symbol": "SZ:000977", "market_value": 1000}],
        active_orders=[{"symbol": "SZSE.000977", "status": "SUBMITTED"}],
    )
    duplicate = next(item for item in result.checks if item["name"] == "duplicate_order")
    assert duplicate["status"] == "BLOCK"
