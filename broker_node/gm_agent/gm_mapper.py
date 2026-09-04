from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


class MappingError(ValueError):
    pass


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "items"):
        return dict(value.items())
    raise MappingError(f"gm payload is not a mapping: {type(value).__name__}")


def _required(payload: Mapping[str, Any], field: str) -> Any:
    if field not in payload:
        raise MappingError(f"required gm field is missing: {field}")
    return payload[field]


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _instrument(symbol: str) -> dict[str, str]:
    try:
        exchange, code = symbol.split(".", 1)
    except ValueError as exc:
        raise MappingError(f"invalid gm symbol: {symbol}") from exc
    exchange_map = {"SZSE": "SZ", "SSE": "SH", "SHSE": "SH"}
    if exchange not in exchange_map:
        raise MappingError(f"unsupported gm exchange: {exchange}")
    return {"code": code, "exchange": exchange_map[exchange]}


def map_account(raw: Any) -> dict[str, Any]:
    payload = _mapping(raw)
    normalized = {
        "account_id": _required(payload, "account_id"),
        "total_asset": payload.get("nav"),
        "available_cash": payload.get("available"),
        "frozen_cash": payload.get("frozen"),
        "market_value": payload.get("market_value"),
        "as_of": _iso(payload.get("updated_at")),
    }
    if normalized["total_asset"] is None or normalized["available_cash"] is None:
        raise MappingError("account nav and available are required")
    return {"normalized": normalized, "raw": payload}


def map_position(raw: Any) -> dict[str, Any]:
    payload = _mapping(raw)
    symbol = str(_required(payload, "symbol"))
    normalized = {
        "instrument": _instrument(symbol),
        "quantity": _required(payload, "volume"),
        # Guotou exposes total available inventory as ``available`` and the
        # T+1 sellable inventory as ``available_now``.  Selling must use the
        # latter when the broker provides it.
        "available_quantity": payload.get("available_now", _required(payload, "available")),
        "frozen_quantity": payload.get("order_frozen"),
        "cost_price": payload.get("vwap"),
        "market_value": payload.get("market_value"),
        "as_of": _iso(payload.get("updated_at")),
    }
    return {"normalized": normalized, "raw": payload}


def map_order(raw: Any) -> dict[str, Any]:
    payload = _mapping(raw)
    side = {1: "BUY", 2: "SELL"}.get(payload.get("side"), "UNKNOWN")
    status = {
        0: "UNKNOWN",
        1: "NEW",
        2: "PARTIALLY_FILLED",
        3: "FILLED",
        4: "DONE_FOR_DAY",
        5: "CANCELED",
        6: "PENDING_CANCEL",
        7: "STOPPED",
        8: "REJECTED",
        9: "SUSPENDED",
        10: "PENDING_NEW",
        11: "CALCULATED",
        12: "EXPIRED",
        13: "ACCEPTED_FOR_BIDDING",
        14: "PENDING_REPLACE",
    }.get(payload.get("status"), "UNKNOWN")
    normalized = {
        "client_order_id": _required(payload, "cl_ord_id"),
        "broker_order_id": _required(payload, "order_id"),
        "exchange_order_id": payload.get("ex_ord_id"),
        "instrument": _instrument(str(_required(payload, "symbol"))),
        "side": side,
        "status": status,
        "raw_status": payload.get("status"),
        "price": payload.get("price"),
        "quantity": payload.get("volume"),
        "filled_quantity": payload.get("filled_volume"),
        "filled_vwap": payload.get("filled_vwap"),
        "filled_amount": payload.get("filled_amount"),
        "reject_code": payload.get("ord_rej_reason"),
        "reject_reason": payload.get("ord_rej_reason_detail"),
        "created_at": _iso(payload.get("created_at")),
        "updated_at": _iso(payload.get("updated_at")),
    }
    return {"normalized": normalized, "raw": payload}


def map_fill(raw: Any) -> dict[str, Any]:
    payload = _mapping(raw)
    normalized = {
        "broker_execution_id": _required(payload, "exec_id"),
        "broker_order_id": _required(payload, "order_id"),
        "client_order_id": _required(payload, "cl_ord_id"),
        "instrument": _instrument(str(_required(payload, "symbol"))),
        "side": {1: "BUY", 2: "SELL"}.get(payload.get("side"), "UNKNOWN"),
        "price": _required(payload, "price"),
        "quantity": _required(payload, "volume"),
        "amount": payload.get("amount"),
        "commission": payload.get("commission"),
        "occurred_at": _iso(payload.get("created_at")),
    }
    return {"normalized": normalized, "raw": payload}
