from pathlib import Path

from broker_node.gm_agent.quote_cache import QuoteCache


def test_quote_cache_revision_and_freshness(tmp_path: Path):
    cache = QuoteCache(tmp_path / "quote.sqlite3")
    cache.put({"symbol_key": "SZ:000661", "broker_symbol": "SZSE.000661", "last": 74.2, "market_time": ""})
    values = cache.get(["SZ:000661"], 3000)
    assert values[0]["quote_revision"] == 1
    assert values[0]["freshness"] == "FRESH"
