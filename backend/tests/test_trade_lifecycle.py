import pytest

from backend.trading.trade import TradeInput, validate_exit_rule, validate_trade_input, validate_trade_plan_action


def test_trade_input_accepts_supported_trade_types():
    validate_trade_input(TradeInput(account_id=1, symbol="600000", symbol_name="浦发银行", trade_type="TREND"))


def test_trade_input_rejects_unknown_trade_type():
    with pytest.raises(ValueError, match="trade_type is invalid"):
        validate_trade_input(TradeInput(account_id=1, symbol="600000", symbol_name="浦发银行", trade_type="UNKNOWN"))  # type: ignore[arg-type]


def test_trade_plan_action_requires_positive_sequence():
    with pytest.raises(ValueError, match="sequence_no"):
        validate_trade_plan_action("ADD", 0)


def test_exit_rule_accepts_documented_values():
    validate_exit_rule("R_MULTIPLE", "REDUCE_POSITION_PCT", "REQUIRE_CONFIRMATION")


def test_exit_rule_rejects_internal_unknown_values():
    with pytest.raises(ValueError, match="trigger_type"):
        validate_exit_rule("UNKNOWN", "ALERT_ONLY", "ALERT_ONLY")
