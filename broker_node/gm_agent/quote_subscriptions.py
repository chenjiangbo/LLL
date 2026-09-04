from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from broker_node.shared.db import connect


class QuoteSubscriptionManager:
    def __init__(self, durable_db: Path):
        self.durable_db = durable_db
        self.active: set[str] = set()

    def desired(self) -> set[str]:
        now = datetime.now(timezone.utc).isoformat()
        with connect(self.durable_db) as connection:
            rows = connection.execute("SELECT broker_symbol FROM quote_subscriptions WHERE lease_expires_at > ?", (now,)).fetchall()
        return {row["broker_symbol"] for row in rows}

    def refresh(self) -> set[str]:
        from gm.api import subscribe, unsubscribe

        desired = self.desired()
        added = desired - self.active
        removed = self.active - desired
        if added:
            subscribe(symbols=sorted(added), frequency="tick", count=1,
                      unsubscribe_previous=False, format="col")
        for symbol in sorted(removed):
            unsubscribe(symbols=symbol, frequency="tick")
        self.active = desired
        return added
