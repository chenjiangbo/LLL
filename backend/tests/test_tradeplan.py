from backend.trading.account import normalize_symbol
from backend.trading.tradeplan import AccountRiskSettings, InstrumentInfo, TradePlanCalculator, TradePlanInput


def base_plan(**overrides):
    values = dict(symbol="600000", security_name="浦发银行", reference_entry_price=10, risk_reference_price=9.5, plan_risk_pct=0.008, expected_price=11.5)
    values.update(overrides)
    return TradePlanInput(**values)


def base_account(**overrides):
    values = dict(account_equity=100000, available_cash=100000, current_invested_amount=0, default_risk_pct=0.008, max_single_position_pct=0.2, max_total_position_pct=1.0)
    values.update(overrides)
    return AccountRiskSettings(**values)


def test_risk_budget_limits_quantity():
    result = TradePlanCalculator.calculate(base_plan(risk_reference_price=9), base_account())
    assert result["recommended_qty"] == 800
    assert result["unrounded_recommended_qty"] == 800
    assert result["limiting_factor"] == "RISK_BUDGET"
    assert result["planned_risk_amount"] == 800
    assert result["post_trade_total_position_pct"] == 0.08


def test_single_position_limits_quantity():
    result = TradePlanCalculator.calculate(base_plan(risk_reference_price=9.9), base_account(max_single_position_pct=0.1))
    assert result["recommended_qty"] == 1000
    assert result["limiting_factor"] == "SINGLE_POSITION_LIMIT"


def test_manual_quantity_recalculates_and_blocks_hard_limit():
    result = TradePlanCalculator.calculate(base_plan(manual_planned_qty=1500), base_account(max_single_position_pct=0.1))
    assert result["planned_qty"] == 1500
    assert any("single-position" in error for error in result["blocking_errors"])


def test_lower_manual_quantity_recalculates_plan_and_zero_is_rejected():
    result = TradePlanCalculator.calculate(base_plan(manual_planned_qty=500), base_account())
    assert result["recommended_qty"] == 1600
    assert result["planned_qty"] == 500
    assert result["planned_notional"] == 5000
    assert result["planned_risk_amount"] == 250
    assert result["blocking_errors"] == []
    invalid = TradePlanCalculator.calculate(base_plan(manual_planned_qty=0), base_account())
    assert "manual_planned_qty must be a positive integer" in invalid["blocking_errors"]


def test_changing_open_budget_recalculates_limits_and_respects_manual_quantity():
    account = base_account(max_single_position_pct=1.0)
    high = TradePlanCalculator.calculate(base_plan(plan_risk_pct=0.008), account)
    low = TradePlanCalculator.calculate(base_plan(plan_risk_pct=0.004), account)
    assert (high["risk_budget_amount"], high["recommended_qty"], high["planned_notional"]) == (800, 1600, 16000)
    assert (low["risk_budget_amount"], low["recommended_qty"], low["planned_notional"]) == (400, 800, 8000)
    manual = TradePlanCalculator.calculate(base_plan(plan_risk_pct=0.004, manual_planned_qty=500), account)
    assert (manual["planned_qty"], manual["planned_risk_amount"], manual["risk_budget_amount"]) == (500, 250, 400)


def test_trend_following_without_target_is_valid():
    result = TradePlanCalculator.calculate(base_plan(), base_account())
    assert result["reward_risk_ratio"] is None
    assert result["blocking_errors"] == []


def test_trend_following_expected_price_calculates_expected_reward():
    result = TradePlanCalculator.calculate(base_plan(expected_price=11.5), base_account())
    assert result["expected_reward_r"] == 3
    assert result["expected_price"] == 11.5


def test_trend_following_can_calculate_without_optional_space_reference():
    result = TradePlanCalculator.calculate(base_plan(expected_price=None), base_account())
    assert result["blocking_errors"] == []
    assert result["expected_price"] is None
    assert result["expected_reward_r"] is None
    assert result["r1_price"] == 10.5
    assert result["r2_price"] == 11.0
    assert result["r3_price"] == 11.5


def test_trend_following_requires_space_reference_when_saving():
    result = TradePlanCalculator.calculate(base_plan(expected_price=None), base_account(), require_complete=True)
    assert any("expected_price is required" in error for error in result["blocking_errors"])


def test_invalid_price_relationship_blocks():
    result = TradePlanCalculator.calculate(base_plan(risk_reference_price=10.5), base_account())
    assert result["blocking_errors"]


def test_quantity_adjustment_preserves_pre_lot_quantity():
    result = TradePlanCalculator.calculate(
        base_plan(reference_entry_price=29.47, risk_reference_price=27.23, plan_risk_pct=0.01),
        base_account(account_equity=100000, available_cash=100000, max_single_position_pct=1, max_total_position_pct=1),
    )
    assert result["qty_by_risk"] == 446
    assert result["unrounded_recommended_qty"] == 446
    assert result["recommended_qty"] == 400


def test_plan_risk_above_account_max_is_blocked():
    result = TradePlanCalculator.calculate(base_plan(plan_risk_pct=0.03), base_account(max_trade_risk_pct=0.02))
    assert "plan_risk_pct exceeds max_trade_risk_pct" in result["blocking_errors"]


def test_rebound_requires_target_zone_holding_period_and_invalidation():
    result = TradePlanCalculator.calculate(base_plan(trade_type="REBOUND"), base_account(), require_complete=True)
    assert "target_zone_lower must be greater than reference_entry_price for REBOUND" in result["blocking_errors"]
    assert "holding_period_days must be a positive integer for REBOUND" in result["blocking_errors"]
    assert "time_invalidation_condition is required for REBOUND" in result["blocking_errors"]


def test_rebound_can_calculate_core_metrics_before_optional_fields_are_filled():
    result = TradePlanCalculator.calculate(base_plan(trade_type="REBOUND"), base_account())
    assert result["blocking_errors"] == []
    assert result["planned_qty"] > 0
    assert result["planned_risk_amount"] > 0
    assert result["target_zone_lower"] is None


def test_rebound_calculates_with_explicit_target_zone():
    result = TradePlanCalculator.calculate(
        base_plan(
            trade_type="REBOUND",
            target_zone_lower=11,
            target_zone_upper=12,
            holding_period_days=10,
            time_invalidation_condition="10个交易日内未触及目标区",
        ),
        base_account(),
    )
    assert result["blocking_errors"] == []
    assert result["target_zone_lower"] == 11
    assert result["holding_period_days"] == 10


def test_rebound_uses_target_zone_for_reward_r_and_does_not_require_trend_space():
    result = TradePlanCalculator.calculate(
        base_plan(
            trade_type="REBOUND",
            target_zone_lower=11,
            target_zone_upper=12,
            holding_period_days=10,
            time_invalidation_condition="10个交易日内未触及目标区",
            expected_price=None,
        ),
        base_account(),
        require_complete=True,
    )
    assert result["blocking_errors"] == []
    assert result["rebound_conservative_reward_r"] == 2
    assert result["rebound_ideal_reward_r"] == 4
    assert result["expected_reward_r"] is None


def test_bare_stock_codes_use_exchange_qualified_identity():
    assert normalize_symbol("000977") == "SZ:000977"
    assert normalize_symbol("600000") == "SH:600000"
    assert normalize_symbol("SZSE.000977") == "SZ:000977"
    assert normalize_symbol("SH:600000") == "SH:600000"


def test_enabled_minimum_cash_ratio_reduces_total_position_capacity():
    result = TradePlanCalculator.calculate(
        base_plan(reference_entry_price=10, risk_reference_price=9, plan_risk_pct=0.2),
        base_account(
            account_equity=100000,
            available_cash=100000,
            max_single_position_pct=1.0,
            max_total_position_pct=1.0,
            max_trade_risk_pct=1.0,
            min_cash_ratio_enabled=True,
            min_cash_ratio_pct=0.2,
        ),
    )
    assert result["qty_by_total_position"] == 10000
    assert result["qty_by_min_cash"] == 8000
    assert result["recommended_qty"] == 8000
    assert result["limiting_factor"] == "MIN_CASH_LIMIT"


def test_single_order_limits_reduce_recommendation_and_block_manual_excess():
    account = base_account(account_equity=200000, available_cash=200000, max_single_position_pct=1.0, max_single_order_notional=20000, max_single_order_quantity=5000)
    plan = base_plan(reference_entry_price=6.21, risk_reference_price=6.0, expected_price=7)
    result = TradePlanCalculator.calculate(plan, account)
    assert result['qty_by_single_order_amount'] == 3220
    assert result['recommended_qty'] == 3200
    assert result['limiting_factor'] == 'SINGLE_ORDER_AMOUNT_LIMIT'
    excessive = TradePlanCalculator.calculate(base_plan(reference_entry_price=6.21, risk_reference_price=6.0, expected_price=7, manual_planned_qty=3700), account)
    assert any('单笔最大金额' in error for error in excessive['blocking_errors'])
