from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from broker_node.shared.order_types import MARKET_ORDER_TYPES, validate_broker_order_type


class CommandValidationError(ValueError):
    pass


def validate_order_payload(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    if payload.get("exchange") not in config["safety"]["allowed_exchanges"]:
        raise CommandValidationError("exchange is not allowed")
    if payload.get("side") not in ("BUY", "SELL"):
        raise CommandValidationError("side must be BUY or SELL")
    try:
        order_type = validate_broker_order_type(payload["exchange"], payload.get("order_type"))
    except (KeyError, ValueError) as exc:
        raise CommandValidationError(str(exc)) from exc
    quantity = payload.get("quantity")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise CommandValidationError("quantity must be a positive integer")
    raw_price = payload.get("price")
    price_required = order_type == "LIMIT" or (payload["exchange"] == "SH" and order_type in MARKET_ORDER_TYPES)
    if price_required:
        try:
            price = Decimal(str(raw_price))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise CommandValidationError("limit/protection price must be a finite positive decimal") from exc
        if not price.is_finite() or price <= 0:
            raise CommandValidationError("limit/protection price must be a finite positive decimal")
        payload["price"] = format(price, "f")
    else:
        if raw_price not in (None, "", "0", "0.0", "0.00", 0, 0.0):
            raise CommandValidationError("SZSE market orders do not accept a price or protection price; omit price")
        price = None
        payload.pop("price", None)
    payload["order_type"] = order_type
    return payload
