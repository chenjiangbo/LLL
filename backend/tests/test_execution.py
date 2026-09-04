from datetime import UTC, datetime, timedelta

import pytest

from backend.trading.broker import BrokerNotConnectedError, DisconnectedBrokerGateway
from backend.trading.execution import OrderInput, PreTradeRisk


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


def test_disconnected_gateway_never_creates_order():
    with pytest.raises(BrokerNotConnectedError):
        DisconnectedBrokerGateway().submit_order({"symbol": "600000"})
