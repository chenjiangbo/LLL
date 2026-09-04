from datetime import UTC, datetime, timedelta

import pytest

from backend.trading.execution_engine import ExecutionEngine


class FakeGateway:
    def __init__(self):
        self.orders = []

    def submit_order(self, order):
        self.orders.append(order)
        return {"status": "QUEUED", "request_id": order["request_id"]}


def plan(**overrides):
    value = {
        "id": 7,
        "status": "ACTIVE",
        "symbol": "SZ:000661",
        "side": "BUY",
        "remaining_qty": 100,
        "execution_type": "PRICE_TRIGGER",
        "valid_until": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        "execution_params": {"trigger_price": "75", "limit_price": "74.50", "require_fresh_quote": True},
    }
    value.update(overrides)
    return value


def quote(**overrides):
    value = {"symbol_key": "SZ:000661", "last": "75.10", "freshness": "FRESH", "quote_revision": 3}
    value.update(overrides)
    return value


def account():
    return {"status": "ACTIVE", "equity": 100000, "available_cash": 100000, "configuration_confirmed": True}


def risk():
    return {"max_single_position_pct": 0.2, "max_total_exposure_pct": 1.0, "configuration_confirmed": True}


def test_price_trigger_waits_then_ready():
    engine = ExecutionEngine(FakeGateway())
    assert engine.evaluate(plan(), quote()) .status == "WAIT"
    assert engine.evaluate(plan(), quote(last="75.00")).status == "READY"


def test_stale_quote_blocks_condition():
    decision = ExecutionEngine(FakeGateway()).evaluate(plan(), quote(freshness="STALE", last="75.00"))
    assert decision.status == "BLOCK"
    assert decision.reason == "MARKET_STALE"


def test_end_to_end_ready_plan_creates_local_order_then_submits_gateway():
    gateway = FakeGateway()
    created = []
    result = ExecutionEngine(gateway).submit(
        plan(), quote(last="75.00"), account(), risk(), [], [], "guotou_sim_01", "req-1", "client-1",
        lambda payload: created.append(payload) or {"id": 123, "client_order_id": payload["client_order_id"]},
    )
    assert result is not None
    assert created[0]["client_order_id"] == "client-1"
    assert gateway.orders[0]["trigger_snapshot"]["quote_revision"] == 3


def test_stale_quote_never_creates_order():
    gateway = FakeGateway()
    result = ExecutionEngine(gateway).submit(
        plan(), quote(last="75.00", freshness="DISCONNECTED"), account(), risk(), [], [], "guotou_sim_01", "req-1", "client-1", lambda payload: payload,
    )
    assert result is None
    assert gateway.orders == []


def test_trigger_requires_separate_limit_price():
    params = {"trigger_price": "75"}
    with pytest.raises(ValueError, match="limit_price is required"):
        ExecutionEngine(FakeGateway()).submit(
            plan(execution_params=params), quote(last="75.00"), account(), risk(), [], [], "guotou_sim_01", "req-1", "client-1", lambda payload: payload,
        )


def test_buy_limit_cannot_exceed_max_acceptable_price():
    with pytest.raises(ValueError, match="max_acceptable_price"):
        ExecutionEngine(FakeGateway()).submit(
            plan(execution_params={"trigger_price": "75", "limit_price": "76", "max_acceptable_price": "75.50"}),
            quote(last="75.00"), account(), risk(), [], [], "guotou_sim_01", "req-1", "client-1", lambda payload: payload,
        )


def test_limit_plan_does_not_require_a_live_quote():
    gateway = FakeGateway()
    created = []
    result = ExecutionEngine(gateway).submit(
        plan(
            execution_type="LIMIT",
            execution_params={"limit_price": "74.50"},
        ),
        {"symbol_key": "SZ:000661", "freshness": "NOT_REQUIRED"},
        account(),
        risk(),
        [],
        [],
        "guotou_sim_01",
        "req-limit",
        "client-limit",
        lambda payload: created.append(payload) or {"id": 1},
    )
    assert result is not None
    assert created[0]["instrument"] == {"exchange": "SZ", "code": "000661"}
    assert created[0]["order_type"] == "LIMIT"


def test_limit_plan_after_close_accepts_missing_live_price():
    decision = ExecutionEngine(FakeGateway()).evaluate(
        plan(execution_type="PERSISTENT_LIMIT", execution_params={"limit_price": "74.50"}),
        {"symbol_key": "SZ:000661", "freshness": "NOT_REQUIRED"},
    )
    assert decision.status == "READY"
    assert decision.reason == "LIMIT_READY"
