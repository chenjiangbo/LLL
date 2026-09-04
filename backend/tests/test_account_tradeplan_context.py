from backend.trading.account import TradingStore


def test_valid_planning_account_and_risk_rules_are_ready_without_broker() -> None:
    account = {
        "name": "A股交易规划",
        "account_type": "PLANNING",
        "broker": None,
        "equity": 100000,
        "cash": 60000,
        "available_cash": 60000,
        "configuration_confirmed": False,
    }
    risk = {
        "default_trade_risk_pct": 0.008,
        "max_trade_risk_pct": 0.02,
        "max_single_position_pct": 0.12,
        "max_total_exposure_pct": 0.8,
        "configuration_confirmed": False,
    }

    assert TradingStore.is_trade_plan_configuration_ready(account, risk) is True


def test_missing_risk_rule_blocks_tradeplan_even_with_a_planning_account() -> None:
    account = {
        "name": "A股交易规划",
        "equity": 100000,
        "cash": 60000,
        "available_cash": 60000,
    }
    risk = {
        "default_trade_risk_pct": 0.008,
        "max_trade_risk_pct": 0.02,
        "max_single_position_pct": 0,
        "max_total_exposure_pct": 0.8,
    }

    assert TradingStore.is_trade_plan_configuration_ready(account, risk) is False
