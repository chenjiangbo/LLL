from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.screening.config import TushareConfig, screening_database_url_from_env
from backend.screening.data_sync import ScreeningDataSync
from backend.screening.storage import PostgresScreeningStore
from backend.screening.tushare_source import TushareScreeningSource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sync 30m min bars from TuShare (incremental by default).\n"
            "On each run, assets that already have data will be skipped or updated from their latest trade_time.\n"
            "Use --full to force re-fetch all data from start_date (avoid unless necessary)."
        )
    )
    today_str = datetime.now().strftime("%Y%m%d")
    thirty_days_ago_str = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

    parser.add_argument("--start-date", default=thirty_days_ago_str, help="Start date (YYYYMMDD) for assets with no existing data")
    parser.add_argument("--end-date", default=today_str, help="End date (YYYYMMDD), default today")
    parser.add_argument("--full", action="store_true", help="Force full re-fetch, ignoring existing data (SLOW - avoid for 7000+ assets)")
    parser.add_argument("--delay", type=float, default=62.0, help="Delay seconds between TuShare requests. Default 62s to respect 1/min limit.")
    parser.add_argument("--database-url", default="", help="PostgreSQL URL. Defaults to MARKET_REVIEW_DATABASE_URL from .env")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_url = args.database_url.strip() or screening_database_url_from_env(PROJECT_ROOT)
    store = PostgresScreeningStore(database_url)

    tushare_config = TushareConfig.from_project_env(PROJECT_ROOT)
    source = TushareScreeningSource(tushare_config.token)
    sync = ScreeningDataSync(source, store)

    # 先汇报数据库当前状态
    all_assets = store.get_all_assets()
    total = len(all_assets)

    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT COUNT(*) as rows, COUNT(DISTINCT asset_code) as assets FROM screening_min_bar WHERE freq='30min'"
        ).fetchone()
    existing_rows = row["rows"] if row else 0
    existing_assets = row["assets"] if row else 0
    print(f"[Status] Total assets in DB: {total}")
    print(f"[Status] Existing 30m data: {existing_rows} rows across {existing_assets} assets")
    print(f"[Status] Assets with NO 30m data: {total - existing_assets}")
    print(f"[Status] Sync mode: {'FULL (force re-fetch)' if args.full else 'INCREMENTAL (skip assets with existing data)'}")
    print(f"[Status] Start: {args.start_date} -> End: {args.end_date}, delay={args.delay}s per asset")
    print(f"[Estimated] ~{((total - existing_assets) * args.delay / 3600):.1f} hours remaining at {args.delay}s/asset\n")

    def on_progress(idx: int, total: int, code: str) -> None:
        if idx % 10 == 0 or idx == total:
            print(f"[{idx}/{total}] Processed: {code}")

    res = sync.sync_30m_bars_all(
        start_date=args.start_date,
        end_date=args.end_date,
        force_full=args.full,
        delay_seconds=args.delay,
        progress_callback=on_progress,
    )

    print(f"\n30m sync finished: {res}")


if __name__ == "__main__":
    main()
