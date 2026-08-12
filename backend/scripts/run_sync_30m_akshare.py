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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync 30m min bars via AkShare and perform full DB backup after completion")
    today_str = datetime.now().strftime("%Y%m%d")
    thirty_days_ago_str = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

    parser.add_argument("--start-date", default=thirty_days_ago_str, help="Start date (YYYYMMDD), default 30 days ago")
    parser.add_argument("--end-date", default=today_str, help="End date (YYYYMMDD), default today")
    parser.add_argument("--workers", type=int, default=8, help="Number of parallel worker threads (default 8)")
    parser.add_argument("--database-url", default="", help="PostgreSQL URL. Defaults to MARKET_REVIEW_DATABASE_URL from .env")
    parser.add_argument("--backup-dir", default="data/backups", help="Directory to save full DB backup file after sync")
    return parser.parse_args()


def backup_database(database_url: str, backup_dir: str) -> None:
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = Path(backup_dir) / f"lll_market_review_backup_{timestamp}.sql.gz"
    
    print(f"\n=======================================================", flush=True)
    print(f"[Backup] Starting FULL database backup (including 30m data) to {backup_path} ...", flush=True)
    
    # 容器内通过 docker exec 或直接 pg_dump
    # 此处使用 docker exec 导出 postgres 容器
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

    # 用空 token 实例化 TushareSource，因主逻辑使用 AkShare
    source = TushareScreeningSource("dummy_token")
    sync = ScreeningDataSync(source, store)

    print(f"Starting AkShare 30m bar sync: start_date={args.start_date}, end_date={args.end_date}, workers={args.workers}", flush=True)

    res = sync.sync_30m_bars_akshare(
        start_date=args.start_date,
        end_date=args.end_date,
        max_workers=args.workers,
    )

    print(f"\nAkShare 30m sync finished: {res}", flush=True)
    
    # 数据全量拉取落库完成后，触发全量数据库备份！
    backup_database(database_url, args.backup_dir)


if __name__ == "__main__":
    main()
