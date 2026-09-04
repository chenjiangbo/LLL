from __future__ import annotations

from broker_node.gm_agent.gm_mapper import map_account, map_fill, map_order, map_position


def test_account_mapping_uses_verified_fields_and_keeps_raw() -> None:
    raw = {"account_id": "redacted", "nav": 200409.99, "available": 185570.0, "frozen": 14420.0, "updated_at": "2026-09-02T18:10:35+08:00"}
    mapped = map_account(raw)
    assert mapped["normalized"]["total_asset"] == 200409.99
    assert mapped["normalized"]["available_cash"] == 185570.0
    assert mapped["raw"] == raw


def test_position_mapping_preserves_available_quantity() -> None:
    raw = {"symbol": "SZSE.000661", "volume": 200, "available": 200, "vwap": 72.1, "market_value": 14840.0}
    assert map_position(raw)["normalized"] == {
        "instrument": {"code": "000661", "exchange": "SZ"},
        "quantity": 200,
        "available_quantity": 200,
        "frozen_quantity": None,
        "cost_price": 72.1,
        "market_value": 14840.0,
        "as_of": None,
    }


def test_order_and_fill_mapping_uses_real_identifiers() -> None:
    order = map_order({"cl_ord_id": "client", "order_id": "broker", "ex_ord_id": "exchange", "symbol": "SZSE.000661", "side": 1, "status": 3, "price": 70.0, "volume": 100, "filled_volume": 100, "filled_vwap": 70.0, "filled_amount": 7000.0})
    fill = map_fill({"exec_id": "execution", "order_id": "broker", "cl_ord_id": "client", "symbol": "SZSE.000661", "side": 1, "price": 70.0, "volume": 100, "amount": 7000.0})
    assert order["normalized"]["status"] == "FILLED"
    assert order["normalized"]["exchange_order_id"] == "exchange"
    assert fill["normalized"]["broker_execution_id"] == "execution"


def test_unknown_order_status_is_not_accepted() -> None:
    raw = {"cl_ord_id": "client", "order_id": "broker", "symbol": "SZSE.000661", "side": 1, "status": 999, "volume": 100}
    assert map_order(raw)["normalized"]["status"] == "UNKNOWN"


def test_position_uses_sellable_available_now_for_t_plus_one() -> None:
    raw = {
        "symbol": "SZSE.000661",
        "volume": 700,
        "available": 700,
        "available_now": 200,
    }
    assert map_position(raw)["normalized"]["available_quantity"] == 200
