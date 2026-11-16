from __future__ import annotations


GM_ORDER_TYPE_NAMES = {
    "LIMIT": "OrderType_Limit",
    "MARKET": "OrderType_Market",
    "MARKET_BOC": "OrderType_Market_BOC",
    "MARKET_BOP": "OrderType_Market_BOP",
    "MARKET_FAK": "OrderType_Market_FAK",
    "MARKET_FOK": "OrderType_Market_FOK",
    "MARKET_B5TC": "OrderType_Market_B5TC",
    "MARKET_B5TL": "OrderType_Market_B5TL",
}

MARKET_ORDER_TYPES = frozenset(GM_ORDER_TYPE_NAMES) - {"LIMIT"}
ORDER_TYPES_BY_EXCHANGE = {
    "SH": frozenset({"LIMIT", "MARKET", "MARKET_BOC", "MARKET_BOP", "MARKET_B5TC", "MARKET_B5TL"}),
    "SZ": frozenset({"LIMIT", "MARKET", "MARKET_BOC", "MARKET_BOP", "MARKET_FAK", "MARKET_FOK", "MARKET_B5TC"}),
}


def validate_broker_order_type(exchange: str, order_type: str) -> str:
    market = str(exchange or "").strip().upper()
    normalized = str(order_type or "").strip().upper()
    if market not in ORDER_TYPES_BY_EXCHANGE:
        raise ValueError(f"unsupported exchange: {exchange}")
    if normalized not in ORDER_TYPES_BY_EXCHANGE[market]:
        raise ValueError(f"{market} does not support A-share order type {normalized}")
    return normalized
