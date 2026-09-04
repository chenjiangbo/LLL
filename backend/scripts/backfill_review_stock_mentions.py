from __future__ import annotations

"""Rebuild full-text stock mention indexes for every imported market review."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.market_review.api import _database_url
from backend.market_review.postgres_storage import PostgresMarketReviewStore
from backend.market_review.review_stock_extraction import EXTRACTION_VERSION, extract_and_store_review_stock_mentions


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild full-text review stock mention indexes")
    parser.add_argument("--trade-date", help="Only rebuild one YYYY-MM-DD review date")
    parser.add_argument("--resume", action="store_true", help="Skip dates already completed by the current extraction version")
    args = parser.parse_args()

    store = PostgresMarketReviewStore(_database_url())
    if args.trade_date:
        review = store.load_imported_review(args.trade_date)
        reviews = [review] if review else []
    else:
        with store.connect() as conn:
            if args.resume:
                rows = conn.execute(
                    """
                    select r.trade_date, r.raw_content
                    from imported_market_reviews r
                    left join imported_review_stock_extraction_runs x on x.trade_date = r.trade_date
                    where x.status is distinct from 'COMPLETE'
                       or x.extraction_version is distinct from %s
                    order by r.trade_date asc
                    """,
                    (EXTRACTION_VERSION,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "select trade_date, raw_content from imported_market_reviews order by trade_date asc"
                ).fetchall()
        reviews = [{"trade_date": str(row["trade_date"]), "raw_content": str(row["raw_content"])} for row in rows]
    if not reviews:
        raise RuntimeError("没有找到需要回填的复盘文章")

    results: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    total = len(reviews)
    for index, review in enumerate(reviews, start=1):
        trade_date = str(review["trade_date"])
        try:
            result = extract_and_store_review_stock_mentions(store, trade_date, str(review["raw_content"]))
            results.append({"trade_date": trade_date, **result})
            print(f"[{index}/{total}] {trade_date}: {result['resolved_stock_count']} 只证券，完成", flush=True)
        except Exception as exc:
            failures.append({"trade_date": trade_date, "error": str(exc)})
            print(f"[{index}/{total}] {trade_date}: 失败 — {exc}", flush=True)

    output = {"total": total, "completed": len(results), "failed": failures, "results": results}
    print(json.dumps(output, ensure_ascii=False), flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
