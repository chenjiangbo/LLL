from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.screening.config import screening_database_url_from_env
from backend.screening.data_sync import ScreeningDataSync
from backend.screening.storage import PostgresScreeningStore
from backend.screening.tushare_source import TushareScreeningSource
from backend.screening.akshare_source import AkshareScreeningSource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync 30m min bars for Candidate Pools A/B/C and Watchlist, then backup DB")
    # 周末休市时，默认结束日期为最近的交易五（如 20260807）
    now = datetime.now()
    if now.weekday() == 5: # Saturday
        last_trade_day = now - timedelta(days=1)
    elif now.weekday() == 6: # Sunday
        last_trade_day = now - timedelta(days=2)
    else:
        last_trade_day = now

    today_str = last_trade_day.strftime("%Y%m%d")
    thirty_days_ago_str = (last_trade_day - timedelta(days=30)).strftime("%Y%m%d")

    parser.add_argument("--start-date", default=thirty_days_ago_str, help="Start date (YYYYMMDD), default 30 days ago")
    parser.add_argument("--end-date", default=today_str, help="End date (YYYYMMDD), default latest trade date")
    parser.add_argument("--database-url", default="", help="PostgreSQL URL. Defaults to MARKET_REVIEW_DATABASE_URL from .env")
    parser.add_argument("--backup-dir", default="data/backups", help="Directory to save full DB backup file after sync")
    return parser.parse_args()


def backup_database(database_url: str, backup_dir: str) -> None:
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = Path(backup_dir) / f"lll_market_review_backup_{timestamp}.sql.gz"
    
    print(f"\n=======================================================", flush=True)
    print(f"[Backup] Starting FULL database backup to {backup_path} ...", flush=True)
    
    cmd = f"docker exec lll-market-review-postgres pg_dump -U lll lll_market_review | gzip > \"{backup_path}\""
    
    try:
        subprocess.run(cmd, shell=True, check=True)
        size_mb = backup_path.stat().st_size / (1024 * 1024)
        print(f"[Backup SUCCESS] Full DB backup completed: {backup_path} ({size_mb:.2f} MB)", flush=True)
        print(f"=======================================================\n", flush=True)
    except Exception as exc:
        print(f"[Backup FAILED] Could not backup database: {exc}", flush=True)


def main() -> None:
    args = parse_args()
    database_url = args.database_url.strip() or screening_database_url_from_env(PROJECT_ROOT)
    store = PostgresScreeningStore(database_url)
    ak_source = AkshareScreeningSource()

    with store.connect() as conn:
        rows = conn.execute(
            """
            select distinct a.asset_code, a.asset_type, a.name
            from screening_asset_master a
            left join screening_candidate_snapshot s on s.asset_code = a.asset_code
            left join screening_user_watchlist w on w.asset_code = a.asset_code
            where s.primary_pool in ('A', 'B', 'C') or w.asset_code is not null
            order by a.asset_code
            """
        ).fetchall()

    pool_assets = [dict(r) for r in rows]
    total = len(pool_assets)

    print(f"Starting 30m bar sync for Pools A/B/C & Watchlist ({total} assets): start_date={args.start_date}, end_date={args.end_date}", flush=True)

    synced_count = 0
    total_rows = 0

    for idx, item in enumerate(pool_assets, 1):
        asset_code = item["asset_code"]
        asset_type = item["asset_type"]
        name = item.get("name", asset_code)
        cur_start = args.start_date

        latest_time = store.get_latest_min_trade_time(asset_code, freq="30min")
        if latest_time:
            latest_date = latest_time.split()[0].replace("-", "")
            if latest_date >= args.end_date:
                if idx % 200 == 0 or idx == total:
                    print(f"[{idx}/{total}] [SKIP] {asset_code} already up to date ({latest_date})", flush=True)
                continue
            cur_start = latest_date

        try:
            df = ak_source.min_bar(asset_code, asset_type, cur_start, args.end_date, freq="30min")
            if df is not None and not df.empty:
                store.save_min_bars(df, freq="30min")
                total_rows += len(df)
                synced_count += 1
                if synced_count % 10 == 0 or idx == total:
                    print(f"[{idx}/{total}] [Pools OK] {asset_code} ({name}) saved {len(df)} rows (Total saved: {synced_count} assets, {total_rows} rows)", flush=True)
        except Exception as exc:
            print(f"[{idx}/{total}] [Pools ERR] {asset_code} ({name}): {exc}", flush=True)

    print(f"\nPools A/B/C 30m sync finished: synced {synced_count}/{total} assets, {total_rows} total 30m rows saved.", flush=True)

    # 同步完成后触发全量数据库备份
    backup_database(database_url, args.backup_dir)


if __name__ == "__main__":
    main()
