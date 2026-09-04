from backend.trading.tradeplan import AccountRiskSettings, InstrumentInfo, TradePlanCalculator, TradePlanInput


def base_plan(**overrides):
    values = dict(symbol="600000", security_name="浦发银行", reference_entry_price=10, max_acceptable_entry_price=10.3, risk_reference_price=9.5, plan_risk_pct=0.008, expected_price=11.5)
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


def test_trend_following_without_target_is_valid():
    result = TradePlanCalculator.calculate(base_plan(), base_account())
    assert result["reward_risk_ratio"] is None
    assert result["blocking_errors"] == []


def test_trend_following_expected_price_calculates_expected_reward():
    result = TradePlanCalculator.calculate(base_plan(expected_price=11.5), base_account())
    assert result["expected_reward_r"] == 3
    assert result["expected_price"] == 11.5


def test_invalid_price_relationship_blocks():
    result = TradePlanCalculator.calculate(base_plan(risk_reference_price=10.5), base_account())
    assert result["blocking_errors"]


def test_max_price_scenario_reduces_quantity():
    result = TradePlanCalculator.calculate(base_plan(), base_account())
    scenario = result["max_price_scenario"]
    assert scenario["recommended_qty"] < result["recommended_qty"]
    assert scenario["planned_risk_amount"] > 0
    assert scenario["post_trade_total_position_pct"] > 0


def test_quantity_adjustment_preserves_pre_lot_quantity():
    result = TradePlanCalculator.calculate(
        base_plan(reference_entry_price=29.47, max_acceptable_entry_price=30, risk_reference_price=27.23, plan_risk_pct=0.01),
        base_account(account_equity=100000, available_cash=100000, max_single_position_pct=1, max_total_position_pct=1),
    )
    assert result["qty_by_risk"] == 446
    assert result["unrounded_recommended_qty"] == 446
    assert result["recommended_qty"] == 400


def test_plan_risk_above_account_max_is_blocked():
    result = TradePlanCalculator.calculate(base_plan(plan_risk_pct=0.03), base_account(max_trade_risk_pct=0.02))
    assert "plan_risk_pct exceeds max_trade_risk_pct" in result["blocking_errors"]


def test_rebound_requires_target_zone_holding_period_and_invalidation():
    result = TradePlanCalculator.calculate(base_plan(trade_type="REBOUND"), base_account())
    assert "target_zone_lower must be greater than reference_entry_price for REBOUND" in result["blocking_errors"]
    assert "holding_period_days must be a positive integer for REBOUND" in result["blocking_errors"]
    assert "time_invalidation_condition is required for REBOUND" in result["blocking_errors"]


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
