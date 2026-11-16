from __future__ import annotations

from typing import Final


SDK_ORDER_TYPES: Final[dict[str, int]] = {
    "LIMIT": 1,
    "MARKET": 2,
    "MARKET_BOC": 20,
    "MARKET_BOP": 21,
    "MARKET_FAK": 22,
    "MARKET_FOK": 23,
    "MARKET_B5TC": 24,
    "MARKET_B5TL": 25,
}

MARKET_ORDER_TYPES: Final[frozenset[str]] = frozenset(SDK_ORDER_TYPES) - {"LIMIT"}
ORDER_TYPES_BY_EXCHANGE: Final[dict[str, frozenset[str]]] = {
    "SH": frozenset({"LIMIT", "MARKET", "MARKET_BOC", "MARKET_BOP", "MARKET_B5TC", "MARKET_B5TL"}),
    "SZ": frozenset({"LIMIT", "MARKET", "MARKET_BOC", "MARKET_BOP", "MARKET_FAK", "MARKET_FOK", "MARKET_B5TC"}),
}


def canonical_order_type(value: object) -> str:
    order_type = str(value or "").strip().upper()
    if not order_type:
        raise ValueError("必须选择委托类型")
    if order_type not in SDK_ORDER_TYPES:
        raise ValueError(f"不支持的 A 股委托类型：{value}")
    return order_type


def validate_order_type_for_exchange(exchange: object, order_type: object) -> str:
    market = str(exchange or "").strip().upper()
    if market not in ORDER_TYPES_BY_EXCHANGE:
        raise ValueError(f"不支持的证券交易所：{exchange}")
    normalized = canonical_order_type(order_type)
    if normalized not in ORDER_TYPES_BY_EXCHANGE[market]:
        raise ValueError(f"{market} 不支持委托类型 {normalized}")
    return normalized


def validate_order_price(exchange: object, order_type: object, price: object) -> float | None:
    """Validate the A-share price field semantics without inventing a fallback."""
    market = str(exchange or "").strip().upper()
    normalized = validate_order_type_for_exchange(market, order_type)
    if normalized == "LIMIT" or (market == "SH" and normalized in MARKET_ORDER_TYPES):
        if price is None or str(price).strip() == "":
            field = "委托限价" if normalized == "LIMIT" else "上交所市价单保护限价"
            raise ValueError(f"{field}必须填写")
        try:
            parsed = float(price)
        except (TypeError, ValueError) as exc:
            raise ValueError("委托价格必须是有效数字") from exc
        if not (parsed > 0 and parsed < float("inf")):
            raise ValueError("委托价格必须是有限正数")
        return parsed

    if price is not None and str(price).strip() != "":
        try:
            parsed = float(price)
        except (TypeError, ValueError) as exc:
            raise ValueError("深交所市价单不接收价格字段；请清空价格") from exc
        if parsed != 0:
            raise ValueError("深交所市价单不接收限价或保护价；请清空价格")
    return None
