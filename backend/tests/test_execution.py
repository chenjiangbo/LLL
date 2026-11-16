from datetime import UTC, datetime, timedelta

import pytest

from backend.trading.broker import BrokerNotConnectedError, DisconnectedBrokerGateway
from backend.trading.execution import ExecutionStore, OrderInput, PreTradeRisk, automatic_next_day_submission_open


def execution_plan(**overrides):
    value = dict(status="ACTIVE", remaining_qty=1000, symbol="600000", valid_until=(datetime.now(UTC) + timedelta(days=1)).isoformat())
    value.update(overrides)
    return value


def account(**overrides):
    value = dict(status="ACTIVE", equity=100000, available_cash=100000, configuration_confirmed=True)
    value.update(overrides)
    return value


def risk_profile(**overrides):
    value = dict(max_single_position_pct=0.2, max_total_exposure_pct=1.0, configuration_confirmed=True)
    value.update(overrides)
    return value


def test_automatic_next_day_submission_waits_until_23_00_china_time():
    before = datetime(2026, 9, 14, 14, 59, tzinfo=UTC)  # 22:59 Asia/Shanghai
    at_window = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)  # 23:00 Asia/Shanghai
    assert automatic_next_day_submission_open(before) is False
    assert automatic_next_day_submission_open(at_window) is True


def order(**overrides):
    value = dict(execution_plan_id=1, symbol="600000", side="BUY", order_type="LIMIT", quantity=100, price=10.0)
    value.update(overrides)
    return OrderInput(**value)


def test_pretrade_risk_passes_valid_buy():
    result = PreTradeRisk.check(account(), risk_profile(), execution_plan(), order(), [], [], datetime.now(UTC))
    assert result.status == "PASS"


def test_pretrade_risk_blocks_duplicate_order():
    result = PreTradeRisk.check(account(), risk_profile(), execution_plan(), order(), [], [{"symbol": "600000", "status": "SUBMITTED"}], datetime.now(UTC))
    assert result.status == "BLOCK"
    assert any(item["name"] == "duplicate_order" and item["status"] == "BLOCK" for item in result.checks)


def test_pretrade_risk_blocks_position_limit():
    result = PreTradeRisk.check(account(), risk_profile(max_single_position_pct=0.1), execution_plan(), order(quantity=200), [{"symbol": "600000", "market_value": 9000}], [], datetime.now(UTC))
    assert result.status == "BLOCK"


def test_pretrade_risk_blocks_single_order_quantity_limit():
    result = PreTradeRisk.check(account(), risk_profile(max_single_order_quantity=100), execution_plan(), order(quantity=200), [], [], datetime.now(UTC))
    assert result.status == "BLOCK"
    assert any(item["name"] == "max_single_order_quantity" and item["status"] == "BLOCK" for item in result.checks)


def test_pretrade_risk_does_not_recheck_plan_notional_against_market_order_price():
    result = PreTradeRisk.check(
        account(),
        risk_profile(max_single_order_notional=1000),
        execution_plan(),
        order(order_type="MARKET_FAK", quantity=200, price=None),
        [],
        [],
        datetime.now(UTC),
    )
    assert result.status == "PASS"
    assert not any(item["name"] == "max_single_order_notional" for item in result.checks)


def test_disconnected_gateway_never_creates_order():
    with pytest.raises(BrokerNotConnectedError):
        DisconnectedBrokerGateway().submit_order({"symbol": "600000"})


def test_execution_store_serializes_boolean_control_fields_as_booleans():
    serialized = ExecutionStore._serialize({"execution_paused": False, "id": 3})
    assert serialized == {"execution_paused": False, "id": 3}


@pytest.mark.parametrize(
    ("current", "next_status", "should_pause"),
    [
        ("SUBMITTED", "CANCELLED", True),
        ("CANCEL_PENDING", "CANCELLED", True),
        ("SUBMITTED", "REJECTED", True),
        ("SUBMITTED", "EXPIRED", True),
        ("CANCELLED", "CANCELLED", False),
        ("REJECTED", "REJECTED", False),
        ("EXPIRED", "EXPIRED", False),
    ],
)
def test_terminal_order_event_pauses_only_on_first_terminal_transition(current, next_status, should_pause):
    assert ExecutionStore.should_pause_plan_for_order_transition(current, next_status) is should_pause


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        ("PENDING_SUBMIT", "SUBMITTED"),
        ("SUBMITTED", "ACCEPTED"),
        ("ACCEPTED", "PARTIALLY_FILLED"),
        ("PARTIALLY_FILLED", "FILLED"),
        ("SUBMITTED", "CANCEL_PENDING"),
        ("CANCEL_PENDING", "CANCELLED"),
        ("UNKNOWN", "SUBMITTED"),
    ],
)
def test_order_status_matrix_accepts_valid_progression(current, next_status):
    assert ExecutionStore.is_order_status_transition_allowed(current, next_status)


@pytest.mark.parametrize(
    ("current", "terminal"),
    [
        ("PENDING_SUBMIT", "REJECTED"),
        ("SUBMITTED", "REJECTED"),
        ("SUBMITTED", "EXPIRED"),
        ("ACCEPTED", "REJECTED"),
        ("ACCEPTED", "EXPIRED"),
        ("PARTIALLY_FILLED", "CANCELLED"),
        ("CANCEL_PENDING", "CANCELLED"),
        ("UNKNOWN", "REJECTED"),
        ("UNKNOWN", "EXPIRED"),
    ],
)
def test_order_status_matrix_accepts_terminal_outcomes(current, terminal):
    assert ExecutionStore.is_order_status_transition_allowed(current, terminal)


@pytest.mark.parametrize("terminal", ["FILLED", "CANCELLED", "REJECTED", "EXPIRED"])
@pytest.mark.parametrize("next_status", ["SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED", "CANCEL_PENDING"])
def test_order_status_matrix_rejects_reopening_terminal_order(terminal, next_status):
    assert not ExecutionStore.is_order_status_transition_allowed(terminal, next_status)
