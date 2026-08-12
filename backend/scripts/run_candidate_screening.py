from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.screening.config import ScreeningConfig, TushareConfig, screening_database_url_from_env
from backend.screening.data_sync import ScreeningDataSync
from backend.screening.service import CandidateScreeningService
from backend.screening.storage import PostgresScreeningStore
from backend.screening.tushare_source import TushareScreeningSource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run candidate screening")
    parser.add_argument("--trade-date", required=True, help="Target trade date, for example 20260806")
    parser.add_argument("--database-url", default="", help="PostgreSQL URL. Defaults to MARKET_REVIEW_DATABASE_URL from .env")
    parser.add_argument("--output-dir", default="data/screening/output")
    parser.add_argument("--pool", choices=["A-Pre", "A", "B", "C", "ABC"], default="A", help="Screening pool. Current default is A only.")
    parser.add_argument("--sync-assets", action="store_true", help="Sync stock and ETF master data from TuShare")
    parser.add_argument("--sync-day", action="store_true", help="Sync one trade date from TuShare")
    parser.add_argument("--sync-history-start", help="Sync all open trade dates from this date to --trade-date")
    parser.add_argument("--sync-stock-weekly-start", help="Sync stock weekly bars from this date to --trade-date")
    parser.add_argument("--scan", action="store_true", help="Run local screening and export candidates")
    parser.add_argument("--select-a", help="Manually select one asset_code into A candidate tracking")
    parser.add_argument("--dismiss-a", help="Mark one A candidate as dismissed after manual review")
    parser.add_argument("--viewed-a", help="Mark one A candidate as viewed after manual review")
    parser.add_argument("--note", default="", help="Manual review note for select/dismiss/viewed actions")
    parser.add_argument("--list-selected-a", action="store_true", help="List manual A selections")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = ScreeningConfig(output_dir=Path(args.output_dir))
    database_url = args.database_url.strip() or screening_database_url_from_env(PROJECT_ROOT)
    store = PostgresScreeningStore(database_url)
    source = None
    sync = None

    if args.sync_assets or args.sync_day or args.sync_history_start or args.sync_stock_weekly_start:
        tushare_config = TushareConfig.from_project_env(PROJECT_ROOT)
        source = TushareScreeningSource(tushare_config.token)
        sync = ScreeningDataSync(source, store)

    result: dict[str, object] = {"trade_date": args.trade_date}
    if args.sync_assets:
        assert sync is not None
        result["assets"] = sync.sync_assets()
    if args.sync_history_start:
        assert sync is not None
        result["history"] = sync.sync_history(args.sync_history_start, args.trade_date)
    elif args.sync_day:
        assert sync is not None
        result["daily"] = sync.sync_trade_date(args.trade_date)
    if args.sync_stock_weekly_start:
        assert sync is not None
        result["stock_weekly"] = sync.sync_stock_weekly_history(args.sync_stock_weekly_start, args.trade_date)
    if args.scan:
        pools = {"A-Pre", "A", "B", "C"} if args.pool in ("ABC", "ALL") else {args.pool}
        result["screening"] = CandidateScreeningService(config, store).run(args.trade_date, pools=pools)
    if args.select_a:
        result["select_a"] = store.select_manual_candidate(args.trade_date, args.select_a, "A", "SELECT", args.note or None)
    if args.dismiss_a:
        result["dismiss_a"] = store.select_manual_candidate(args.trade_date, args.dismiss_a, "A", "DISMISS", args.note or None)
    if args.viewed_a:
        result["viewed_a"] = store.select_manual_candidate(args.trade_date, args.viewed_a, "A", "VIEWED", args.note or None)
    if args.list_selected_a:
        result["selected_a"] = store.load_manual_selections(pool="A", trade_date=args.trade_date)

    if not any([
        args.sync_assets,
        args.sync_day,
        args.sync_history_start,
        args.sync_stock_weekly_start,
        args.scan,
        args.select_a,
        args.dismiss_a,
        args.viewed_a,
        args.list_selected_a,
    ]):
        raise SystemExit("No action requested. Use --sync-assets, --sync-day, --sync-history-start, or --scan.")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
