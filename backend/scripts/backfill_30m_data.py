from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.screening.config import TushareConfig, screening_database_url_from_env
from backend.screening.data_sync import ScreeningDataSync
from backend.screening.storage import PostgresScreeningStore
from backend.screening.tushare_source import TushareScreeningSource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="前台运行最近一段交易日的 30 分钟 K 线缺口补齐")
    parser.add_argument("--days", type=int, default=30, help="向前检查的自然日范围，默认 30")
    parser.add_argument("--delay", type=float, default=None, help="每个资产请求后的等待秒数，默认使用数据管理配置")
    parser.add_argument("--database-url", default="", help="PostgreSQL URL，默认读取项目 .env")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.days < 1:
        raise SystemExit("--days 必须大于 0")
    database_url = args.database_url.strip() or screening_database_url_from_env(PROJECT_ROOT)
    store = PostgresScreeningStore(database_url)
    config = store.get_data_management_config()["config"]
    asset_types = set()
    if config.get("stock_30m_enabled", True):
        asset_types.add("stock")
    if config.get("etf_30m_enabled", True):
        asset_types.add("etf")
    if not asset_types:
        raise SystemExit("数据管理配置已关闭股票和 ETF 的 30 分钟数据更新，无法执行补齐")

    source_config = TushareConfig.from_project_env(PROJECT_ROOT)
    sync = ScreeningDataSync(TushareScreeningSource(source_config.token), store)
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y%m%d")
    trade_dates = sync.source.trade_dates(start_date, end_date)
    if not trade_dates:
        raise SystemExit(f"{start_date} 至 {end_date} 没有交易日")

    delay = float(config.get("request_delay_seconds", 0.12) if args.delay is None else args.delay)
    retry_attempts = int(config.get("retry_attempts", 3))
    if delay < 0 or retry_attempts < 1:
        raise SystemExit("数据管理配置中的请求间隔或重试次数无效")
    task_id = str(uuid.uuid4())
    store.create_data_task(task_id, "backfill_30m", None)
    store.update_data_task(task_id, status="RUNNING", progress=0, stage_message="正在准备历史 30 分钟数据补齐", started_at=datetime.now().astimezone())
    store.prune_sync_logs(int(config.get("sync_log_retention_days", 30)), int(config.get("sync_log_max_rows", 10000)))

    print(f"补齐范围: {start_date} 至 {end_date}，交易日 {len(trade_dates)} 天", flush=True)
    print(f"补齐类型: {', '.join(sorted(asset_types))}；请求间隔 {delay}s；失败重试 {retry_attempts} 次", flush=True)
    results: list[dict[str, object]] = []
    failed_dates = 0
    try:
        for date_index, trade_date in enumerate(trade_dates, 1):
            store.update_data_task(task_id, trade_date=trade_date, progress=int((date_index - 1) * 100 / len(trade_dates)), stage_message=f"正在补齐 {trade_date}（{date_index}/{len(trade_dates)}）")
            print(f"[{date_index}/{len(trade_dates)}] 开始 {trade_date}", flush=True)

            def progress(index: int, total: int, code: str, status: str) -> None:
                if index == 1 or index % 25 == 0 or index == total:
                    print(f"  [{index}/{total}] {code} {status}", flush=True)

            result = sync.sync_30m_bars_for_date(
                trade_date,
                asset_types,
                delay_seconds=delay,
                retry_attempts=retry_attempts,
                progress_callback=progress,
            )
            results.append(result)
            if result["status"] != "PASS":
                failed_dates += 1
            print(json.dumps({key: value for key, value in result.items() if key != "failures"}, ensure_ascii=False), flush=True)

        summary = {
            "days": len(trade_dates),
            "failed_dates": failed_dates,
            "results": results,
            "asset_types": sorted(asset_types),
        }
        status = "SUCCESS" if failed_dates == 0 else "FAILED"
        store.update_data_task(task_id, status=status, progress=100, stage_message="最近 30 天 30 分钟数据补齐完成" if status == "SUCCESS" else "补齐完成，但仍存在未完成交易日", summary_json=summary, completed_at=datetime.now().astimezone())
        store.prune_sync_logs(int(config.get("sync_log_retention_days", 30)), int(config.get("sync_log_max_rows", 10000)))
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        return 0 if status == "SUCCESS" else 1
    except Exception as exc:
        store.update_data_task(task_id, status="FAILED", stage_message="历史 30 分钟数据补齐失败", error_message=str(exc), completed_at=datetime.now().astimezone())
        raise


if __name__ == "__main__":
    raise SystemExit(main())
