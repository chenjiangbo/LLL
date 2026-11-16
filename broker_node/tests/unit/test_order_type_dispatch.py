from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from broker_node.gm_agent.executor import BrokerCommandExecutor
from broker_node.shared.db import connect, initialize
from broker_node.gm_agent.command_validator import CommandValidationError, validate_order_payload
from broker_node.shared.order_types import GM_ORDER_TYPE_NAMES, ORDER_TYPES_BY_EXCHANGE


@pytest.mark.parametrize(
    ("exchange", "order_type", "price", "expected_price"),
    [
        ("SH", "LIMIT", "10.25", "10.25"),
        ("SH", "MARKET_B5TL", "10.25", "10.25"),
        ("SZ", "MARKET_FAK", None, None),
    ],
)
def test_node_accepts_exchange_supported_order_type_and_price_contract(
    tmp_path: Path, exchange: str, order_type: str, price: str | None, expected_price: str | None
) -> None:
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    config = {"safety": {"allowed_exchanges": ["SH", "SZ"]}}
    payload = {
        "exchange": exchange,
        "code": "600000" if exchange == "SH" else "000001",
        "side": "BUY",
        "order_type": order_type,
        "price": price,
        "quantity": 100,
    }
    validated = validate_order_payload(payload, config)
    assert validated["order_type"] == order_type
    if expected_price is None:
        assert "price" not in validated
    else:
        assert validated["price"] == expected_price


def test_node_rejects_exchange_mismatched_order_type(tmp_path: Path) -> None:
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    with pytest.raises(CommandValidationError, match="does not support"):
        validate_order_payload(
            {"exchange": "SH", "code": "600000", "side": "BUY", "order_type": "MARKET_FOK", "price": "10", "quantity": 100},
            {"safety": {"allowed_exchanges": ["SH", "SZ"]}},
        )


def test_node_does_not_enforce_account_risk_or_local_position_snapshot() -> None:
    config = {"safety": {"allowed_exchanges": ["SH", "SZ"], "max_single_order_notional": 1}}
    payload = {"exchange": "SZ", "code": "000001", "side": "SELL", "order_type": "LIMIT", "price": "10", "quantity": 23}
    assert validate_order_payload(payload, config)["quantity"] == 23


@pytest.mark.parametrize(
    ("exchange", "order_type"),
    [(exchange, order_type) for exchange, types in ORDER_TYPES_BY_EXCHANGE.items() for order_type in sorted(types)],
)
def test_gm_dispatch_maps_selected_order_type_and_obeys_market_price_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exchange: str, order_type: str
) -> None:
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    observed: dict[str, object] = {}
    gm = types.ModuleType("gm")
    api = types.ModuleType("gm.api")
    api.OrderSide_Buy = 1
    api.OrderSide_Sell = 2
    api.PositionEffect_Open = 1
    for value, enum_name in enumerate(GM_ORDER_TYPE_NAMES.values(), start=1):
        setattr(api, enum_name, value)

    def order_volume(*args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return None

    api.order_volume = order_volume
    gm.api = api
    monkeypatch.setitem(sys.modules, "gm", gm)
    monkeypatch.setitem(sys.modules, "gm.api", api)
    payload = {
        "exchange": exchange,
        "code": "600000" if exchange == "SH" else "000001",
        "side": "BUY",
        "order_type": order_type,
        "quantity": 100,
    }
    if order_type == "LIMIT" or exchange == "SH":
        payload["price"] = "10.00"
    with connect(db) as connection:
        connection.execute(
            "INSERT INTO commands(command_id,request_id,command_type,client_order_id,payload_hash,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("cmd-1", "req-1", "ORDER_SUBMIT", "client-1", "hash", json.dumps(payload), "CLAIMED", "now", "now"),
        )
    command = {"command_id": "cmd-1", "command_type": "ORDER_SUBMIT", "client_order_id": "client-1", "payload_json": json.dumps(payload)}

    BrokerCommandExecutor(db).dispatch(command, "account-1")

    assert observed["args"][3] == getattr(api, GM_ORDER_TYPE_NAMES[order_type])
    if order_type != "LIMIT" and exchange == "SZ":
        assert "price" not in observed["kwargs"]
    else:
        assert observed["kwargs"]["price"] == 10.0
