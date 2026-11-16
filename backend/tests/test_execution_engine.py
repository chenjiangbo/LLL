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
        "execution_params": {"order_type": "LIMIT", "trigger_price": "75", "limit_price": "74.50", "require_fresh_quote": True},
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


def test_scheduled_execution_waits_until_start_time():
    future_start = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    decision = ExecutionEngine(FakeGateway()).evaluate(plan(valid_from=future_start), quote(last="75.00"))
    assert decision.status == "WAIT"
    assert decision.reason == "SCHEDULED_START_NOT_REACHED"


def test_price_range_waits_outside_and_is_ready_inside():
    engine = ExecutionEngine(FakeGateway())
    range_plan = plan(
        execution_type="PRICE_RANGE",
        execution_params={"order_type": "LIMIT", "low_price": "74.50", "high_price": "75.00", "limit_price": "74.80"},
    )
    assert engine.evaluate(range_plan, quote(last="75.10")).reason == "OUT_OF_RANGE"
    decision = engine.evaluate(range_plan, quote(last="74.80"))
    assert decision.status == "READY"
    assert decision.reason == "IN_RANGE"
    assert decision.trigger_snapshot["quote_revision"] == 3


def test_price_range_with_stale_quote_is_blocked_before_price_evaluation():
    range_plan = plan(
        execution_type="PRICE_RANGE",
        execution_params={"order_type": "LIMIT", "low_price": "74.50", "high_price": "75.00", "limit_price": "74.80"},
    )
    decision = ExecutionEngine(FakeGateway()).evaluate(range_plan, quote(last="74.80", freshness="STALE"))
    assert decision.status == "BLOCK"
    assert decision.reason == "MARKET_STALE"


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
    params = {"order_type": "LIMIT", "trigger_price": "75"}
    with pytest.raises(ValueError, match="委托限价必须填写"):
        ExecutionEngine(FakeGateway()).submit(
            plan(execution_params=params), quote(last="75.00"), account(), risk(), [], [], "guotou_sim_01", "req-1", "client-1", lambda payload: payload,
        )


def test_execution_uses_the_limit_price_set_in_execution_plan():
    gateway = FakeGateway()
    created = []
    result = ExecutionEngine(gateway).submit(
        plan(execution_params={"order_type": "LIMIT", "trigger_price": "75", "limit_price": "76"}),
        quote(last="75.00"), account(), risk(), [], [], "guotou_sim_01", "req-1", "client-1",
        lambda payload: created.append(payload) or {"id": 123},
    )
    assert result is not None
    assert created[0]["price"] == "76"


def test_limit_plan_does_not_require_a_live_quote():
    gateway = FakeGateway()
    created = []
    result = ExecutionEngine(gateway).submit(
        plan(
            execution_type="LIMIT",
            execution_params={"order_type": "LIMIT", "limit_price": "74.50"},
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
    assert created[0]["code"] == "000661"
    assert created[0]["exchange"] == "SZ"
    assert created[0]["order_type"] == "LIMIT"


def test_limit_plan_after_close_accepts_missing_live_price():
    decision = ExecutionEngine(FakeGateway()).evaluate(
        plan(execution_type="PERSISTENT_LIMIT", execution_params={"order_type": "LIMIT", "limit_price": "74.50"}),
        {"symbol_key": "SZ:000661", "freshness": "NOT_REQUIRED"},
    )
    assert decision.status == "READY"
    assert decision.reason == "LIMIT_READY"


def test_selected_order_type_is_preserved_through_trigger_submission():
    gateway = FakeGateway()
    created = []
    sh_plan = plan(
        symbol="SH:600000",
        execution_type="PRICE_TRIGGER",
        execution_params={
            "order_type": "MARKET_B5TL",
            "trigger_price": "75",
            "protection_price": "74.50",
        },
    )
    result = ExecutionEngine(gateway).submit(
        sh_plan,
        quote(symbol_key="SH:600000", last="75.00"),
        account(),
        risk(),
        [],
        [],
        "guotou_sim_01",
        "req-market",
        "client-market",
        lambda payload: created.append(payload) or {"id": 8, **payload},
    )
    assert result is not None
    assert created[0]["order_type"] == "MARKET_B5TL"
    assert created[0]["price"] == "74.5"
    assert created[0]["source"]["order_type"] == "MARKET_B5TL"
    assert gateway.orders[0]["order_type"] == "MARKET_B5TL"


def test_missing_order_type_is_rejected_instead_of_becoming_limit():
    with pytest.raises(ValueError, match="必须选择委托类型"):
        ExecutionEngine(FakeGateway()).evaluate(
            plan(execution_type="LIMIT", execution_params={"limit_price": "74.50"}),
            {"symbol_key": "SZ:000661", "freshness": "NOT_REQUIRED"},
        )


def test_sz_market_order_submission_has_no_price_value():
    gateway = FakeGateway()
    created = []
    result = ExecutionEngine(gateway).submit(
        plan(
            execution_type="LIMIT",
            execution_params={"order_type": "MARKET_FAK"},
        ),
        {"symbol_key": "SZ:000661", "freshness": "NOT_REQUIRED"},
        account(),
        risk(),
        [],
        [],
        "guotou_sim_01",
        "req-sz-market",
        "client-sz-market",
        lambda payload: created.append(payload) or {"id": 9, **payload},
    )
    assert result is not None
    assert created[0]["order_type"] == "MARKET_FAK"
    assert "price" not in created[0]
    assert "price" not in gateway.orders[0]
