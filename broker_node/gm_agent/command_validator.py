from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from broker_node.shared.db import connect


class CommandValidationError(ValueError):
    pass


def validate_order_payload(payload: dict[str, Any], config: dict[str, Any], durable_db: Path) -> dict[str, Any]:
    if payload.get("exchange") not in config["safety"]["allowed_exchanges"]:
        raise CommandValidationError("exchange is not allowed")
    if payload.get("side") not in ("BUY", "SELL"):
        raise CommandValidationError("side must be BUY or SELL")
    quantity = payload.get("quantity")
    if not isinstance(quantity, int) or quantity <= 0 or quantity % 100:
        raise CommandValidationError("quantity must be a positive multiple of 100")
    try:
        price = Decimal(str(payload.get("price")))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CommandValidationError("price must be a finite positive decimal") from exc
    if not price.is_finite() or price <= 0:
        raise CommandValidationError("price must be a finite positive decimal")
    maximum = config["safety"].get("max_single_order_notional")
    if maximum is not None and price * quantity > Decimal(str(maximum)):
        raise CommandValidationError("order notional exceeds configured limit")
    if payload["side"] == "SELL":
        symbol = f"{payload['exchange']}:{payload['code']}"
        with connect(durable_db) as connection:
            row = connection.execute("SELECT payload_json FROM snapshots WHERE snapshot_type='POSITIONS'").fetchone()
        if not row:
            raise CommandValidationError("position snapshot is unavailable")
        positions = json.loads(row[0])
        available = 0
        for item in positions:
            normalized = item.get("normalized", {})
            instrument = normalized.get("instrument", {})
            if f"{instrument.get('exchange')}:{instrument.get('code')}" == symbol:
                available += int(normalized.get("available_quantity", 0))
        if quantity > available:
            raise CommandValidationError("sell quantity exceeds available quantity (T+1 guard)")
    payload["price"] = format(price, "f")
    return payload
