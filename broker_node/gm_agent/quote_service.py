from __future__ import annotations

from typing import Any

from broker_node.gm_agent.quote_cache import QuoteCache


def symbol_key(code: str, exchange: str) -> str:
    if exchange not in ("SH", "SZ") or not code:
        raise ValueError("unsupported execution quote instrument")
    return f"{exchange}:{code}"


def broker_symbol(code: str, exchange: str) -> str:
    # gm.api uses SHSE for Shanghai and SZSE for Shenzhen symbols.
    return f"{'SHSE' if exchange == 'SH' else 'SZSE'}.{code}"


def normalize_tick(tick: dict[str, Any]) -> dict[str, Any]:
    raw_symbol = str(tick["symbol"])
    prefix, code = raw_symbol.split(".", 1)
    exchange = {"SSE": "SH", "SHSE": "SH", "SZSE": "SZ"}.get(prefix)
    if exchange is None:
        raise ValueError(f"unsupported quote exchange: {prefix}")
    quotes = tick.get("quotes")
    if isinstance(quotes, list) and quotes and isinstance(quotes[0], dict):
        level = quotes[0]
        bid_p, bid_v = [level.get("bid_p")], [level.get("bid_v")]
        ask_p, ask_v = [level.get("ask_p")], [level.get("ask_v")]
    else:
        bid_p = tick.get("bid_p") or []
        bid_v = tick.get("bid_v") or []
        ask_p = tick.get("ask_p") or []
        ask_v = tick.get("ask_v") or []
    return {
        "instrument": {"code": code, "exchange": exchange},
        "symbol_key": symbol_key(code, exchange),
        "broker_symbol": raw_symbol,
        "last": tick["price"],
        "bid1": bid_p[0] if bid_p else None,
        "bid1_volume": bid_v[0] if bid_v else None,
        "ask1": ask_p[0] if ask_p else None,
        "ask1_volume": ask_v[0] if ask_v else None,
        "market_time": str(tick.get("created_at") or tick.get("receive_local_time") or ""),
    }


class ExecutionQuoteService:
    def __init__(self, cache: QuoteCache):
        self.cache = cache

    def on_tick(self, tick: dict[str, Any]) -> None:
        self.cache.put(normalize_tick(tick))
