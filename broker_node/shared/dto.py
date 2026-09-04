from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Instrument:
    code: str
    exchange: str


@dataclass(frozen=True)
class LimitOrderRequest:
    request_id: str
    client_order_id: str
    broker_account_key: str
    instrument: Instrument
    side: str
    price: Decimal
    quantity: int
    source: dict[str, Any]
    safety_constraints: dict[str, Any]
    trigger_snapshot: dict[str, Any] | None = None


def decimal_to_json(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("Decimal must be finite")
    return format(value, "f")

