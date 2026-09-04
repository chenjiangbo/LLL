from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from broker_node.shared.db import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_quote_cache(path: Path) -> None:
    with connect(path) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS latest_quotes (
                symbol_key TEXT PRIMARY KEY, broker_symbol TEXT NOT NULL,
                payload_json TEXT NOT NULL, quote_revision INTEGER NOT NULL,
                market_time TEXT, received_at TEXT NOT NULL
            )
        """)


class QuoteCache:
    def __init__(self, path: Path):
        self.path = path
        initialize_quote_cache(path)

    def put(self, quote: dict[str, Any]) -> None:
        with connect(self.path) as connection:
            current = connection.execute("SELECT quote_revision FROM latest_quotes WHERE symbol_key = ?", (quote["symbol_key"],)).fetchone()
            revision = int(current["quote_revision"]) + 1 if current else 1
            received = _now()
            connection.execute("""
                INSERT INTO latest_quotes(symbol_key,broker_symbol,payload_json,quote_revision,market_time,received_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(symbol_key) DO UPDATE SET
                broker_symbol=excluded.broker_symbol,payload_json=excluded.payload_json,
                quote_revision=excluded.quote_revision,market_time=excluded.market_time,
                received_at=excluded.received_at
            """, (quote["symbol_key"], quote["broker_symbol"], json.dumps(quote, default=str, sort_keys=True), revision, quote.get("market_time"), received))

    def get(self, symbols: list[str] | None, freshness_ms: int) -> list[dict[str, Any]]:
        with connect(self.path) as connection:
            rows = connection.execute("SELECT payload_json,quote_revision,received_at FROM latest_quotes" + (" WHERE symbol_key IN (" + ",".join("?" for _ in symbols) + ")" if symbols else ""), symbols or ()).fetchall()
        result = []
        now = time.time()
        for row in rows:
            item = json.loads(row["payload_json"])
            item["received_at"] = row["received_at"]
            item["quote_revision"] = row["quote_revision"]
            age = max(0, int((now - datetime.fromisoformat(row["received_at"]).timestamp()) * 1000))
            item["age_ms"] = age
            item["freshness"] = "FRESH" if age <= freshness_ms else "STALE"
            result.append(item)
        return result
