from pathlib import Path

from broker_node.gm_agent.quote_cache import QuoteCache
from broker_node.gm_agent.quote_service import ExecutionQuoteService, broker_symbol, normalize_tick


def test_broker_symbol_uses_gm_api_exchange_codes():
    assert broker_symbol("600300", "SH") == "SHSE.600300"
    assert broker_symbol("000661", "SZ") == "SZSE.000661"


def test_tick_is_normalized_and_cached(tmp_path: Path):
    tick = {"symbol": "SZSE.000661", "price": 74.2, "bid_p": [74.1], "bid_v": [100], "ask_p": [74.2], "ask_v": [200], "created_at": "2026-09-03T10:00:00+08:00"}
    assert normalize_tick(tick)["symbol_key"] == "SZ:000661"
    cache = QuoteCache(tmp_path / "quote.sqlite3")
    ExecutionQuoteService(cache).on_tick(tick)
    quote = cache.get(["SZ:000661"], 3000)
    assert len(quote) == 1
    assert quote[0]["last"] == 74.2
    assert quote[0]["bid1_volume"] == 100


def test_current_quote_shape_is_normalized(tmp_path: Path):
    quote = normalize_tick({"symbol": "SZSE.000661", "price": 74.2, "quotes": [{"bid_p": 74.19, "bid_v": 116, "ask_p": 74.2, "ask_v": 5400}]})
    assert quote["bid1"] == 74.19
    assert quote["ask1_volume"] == 5400
