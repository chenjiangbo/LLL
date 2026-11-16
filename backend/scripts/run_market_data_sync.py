from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import psycopg


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.screening.config import TushareConfig, screening_database_url_from_env
from backend.screening.data_sync import ScreeningDataSync
from backend.screening.errors import ScreeningError
from backend.screening.storage import PostgresScreeningStore
from backend.screening.tushare_source import TushareScreeningSource


LOCK_KEY = "lll.market_data.standalone_sync"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="独立运行股票与 ETF 日线增量同步")
    parser.add_argument("--trade-date", default=datetime.now().strftime("%Y%m%d"), help="目标交易日 YYYYMMDD")
    parser.add_argument("--database-url", default="", help="PostgreSQL URL，默认读取项目 .env")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database_url = args.database_url.strip() or screening_database_url_from_env(PROJECT_ROOT)
    target = args.trade_date.replace("-", "")
    if len(target) != 8 or not target.isdigit():
        raise SystemExit("--trade-date 必须是 YYYYMMDD")

    lock_conn = psycopg.connect(database_url, autocommit=True)
    acquired = lock_conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (LOCK_KEY,)).fetchone()[0]
    if not acquired:
        lock_conn.close()
        print(json.dumps({"status": "already_running", "message": "已有独立行情同步进程正在运行"}, ensure_ascii=False))
        return 2

    try:
        store = PostgresScreeningStore(database_url)
        config = TushareConfig.from_project_env(PROJECT_ROOT)
        sync = ScreeningDataSync(TushareScreeningSource(config.token), store)
        result: dict[str, object] = {"trade_date": target, "daily": None, "intraday_30m": {"status": "ON_DEMAND"}}

        if store.has_daily_data(target):
            result["daily"] = {"status": "already_complete", "trade_date": target}
            print(f"[daily] {target} 已存在，跳过下载", flush=True)
        else:
            try:
                result["daily"] = {"status": "synced", **sync.sync_trade_date(target)}
                print(f"[daily] {target} 日线同步完成", flush=True)
            except Exception as exc:
                # 正式日线尚未发布时明确记录不可用；分钟线由单只股票 K 线按需获取。
                result["daily"] = {"status": "unavailable", "error": str(exc)}
                print(f"[daily] {target} 尚无可用日线: {exc}", flush=True)

        result["status"] = "success" if result["daily"].get("status") in {"synced", "already_complete"} else "daily_unavailable"
        print("[30m] 股票 K 线数据将在打开时按需获取；ETF 不同步 30 分钟数据", flush=True)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0 if result["status"] == "success" else 1
    except (ScreeningError, Exception) as exc:
        print(json.dumps({"status": "failed", "trade_date": target, "error": str(exc)}, ensure_ascii=False), flush=True)
        return 1
    finally:
        try:
            lock_conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))
        finally:
            lock_conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
