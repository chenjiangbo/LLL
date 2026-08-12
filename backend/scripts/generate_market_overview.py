#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.market_review.config import PipelineConfig
from backend.market_review.pipeline import MarketReviewPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the A-share market review overview snapshot.")
    parser.add_argument("--trade-date", help="Trade date in YYYYMMDD. Defaults to latest common index date.")
    parser.add_argument("--start-date", default="20250101", help="History start date in YYYYMMDD.")
    parser.add_argument("--database-url", default=os.getenv("MARKET_REVIEW_DATABASE_URL", ""))
    parser.add_argument("--report-dir", default="data/market_review/reports")
    parser.add_argument("--max-industries", type=int, help="Development only: limit industry history fetch count.")
    parser.add_argument("--report-type", choices=["daily", "weekly"], default="daily")
    parser.add_argument("--no-ai", action="store_true", help="Generate only deterministic analytics without AI draft.")
    parser.add_argument("--force-data-refresh", action="store_true")
    parser.add_argument("--force-ai-refresh", action="store_true")
    args = parser.parse_args()

    config = PipelineConfig(
        database_url=args.database_url,
        report_dir=Path(args.report_dir),
        default_history_start=args.start_date,
    )
    pipeline = MarketReviewPipeline.create(config)
    report = pipeline.generate_overview(
        trade_date=args.trade_date,
        start_date=args.start_date,
        max_industries=args.max_industries,
        report_type=args.report_type,
        include_ai=not args.no_ai,
        force_data_refresh=args.force_data_refresh,
        force_ai_refresh=args.force_ai_refresh,
    )
    print(
        json.dumps(
            {
                "trade_date": report["trade_date"],
                "summary": report["core_conclusion"]["summary"],
                "report_path": str(Path(args.report_dir) / f"overview_{report['trade_date']}.json"),
                "industry_scope": report["industry_scope"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
