from pathlib import Path

from broker_node.gm_agent.quote_subscriptions import QuoteSubscriptionManager
from broker_node.shared.db import connect, initialize


def test_desired_quote_subscriptions_ignore_expired(tmp_path: Path):
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    with connect(db) as connection:
        connection.execute("INSERT INTO quote_subscriptions VALUES ('EXECUTION_PLAN','p','SZ:000661','SZSE.000661','2000-01-01T00:00:00+00:00','2000-01-01T00:00:00+00:00','2000-01-01T00:00:00+00:00')")
    assert QuoteSubscriptionManager(db).desired() == set()
