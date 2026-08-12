from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, TypeVar

import pandas as pd

from backend.screening.errors import ScreeningError
from backend.screening.storage import PostgresScreeningStore
from backend.screening.tushare_source import TushareScreeningSource


T = TypeVar("T")


@dataclass
class ScreeningDataSync:
    source: TushareScreeningSource
    store: PostgresScreeningStore

    def sync_assets(self) -> dict[str, int]:
        stocks = self.source.stock_basic()
        etfs = self.source.fund_basic()
        assets = pd.concat([stocks, etfs], ignore_index=True)
        if assets.empty:
            raise ScreeningError("asset sync produced no assets")
        self.store.save_assets(assets)
        return {
            "stock": int((assets["asset_type"] == "stock").sum()),
            "etf": int((assets["asset_type"] == "etf").sum()),
        }

    def sync_trade_date(self, trade_date: str) -> dict[str, int]:
        if self.store.has_daily_data(trade_date):
            return {"trade_date": trade_date, "skipped": 1}
        counts: dict[str, int] = {}
        try:
            stock_daily = _with_retry(lambda: self.source.stock_daily(trade_date), "stock_daily", trade_date)
            stock_adj = _with_retry(lambda: self.source.stock_adj_factor(trade_date), "stock_adj_factor", trade_date)
            daily_basic = _with_retry(lambda: self.source.daily_basic(trade_date), "daily_basic", trade_date)
            etf_daily = _with_retry(lambda: self.source.fund_daily(trade_date), "fund_daily", trade_date)
            etf_adj = _with_retry(lambda: self.source.fund_adj_factor(trade_date), "fund_adj_factor", trade_date)

            self.store.save_daily_bars(stock_daily)
            self.store.save_adj_factors(stock_adj)
            self.store.save_daily_basic(daily_basic)
            self.store.save_daily_bars(etf_daily)
            self.store.save_adj_factors(etf_adj)

            counts = {
                "stock_daily": len(stock_daily),
                "stock_adj_factor": len(stock_adj),
                "daily_basic": len(daily_basic),
                "etf_daily": len(etf_daily),
                "etf_adj_factor": len(etf_adj),
            }
            self.store.log_sync(trade_date, "daily", "PASS", str(counts))
            return counts
        except Exception as exc:
            self.store.log_sync(trade_date, "daily", "FAIL", str(exc))
            raise

    def sync_history(self, start_date: str, end_date: str) -> list[dict[str, int | str]]:
        trade_dates = self.source.trade_dates(start_date, end_date)
        if not trade_dates:
            raise ScreeningError(f"no open trade dates between {start_date} and {end_date}")
        results: list[dict[str, int | str]] = []
        for trade_date in trade_dates:
            counts = self.sync_trade_date(trade_date)
            results.append({"trade_date": trade_date, **counts})
        return results

    def sync_stock_weekly_history(self, start_date: str, end_date: str) -> list[dict[str, int | str]]:
        weekly_dates = self.weekly_trade_dates(start_date, end_date)
        if not weekly_dates:
            raise ScreeningError(f"no weekly trade dates between {start_date} and {end_date}")
        results: list[dict[str, int | str]] = []
        for trade_date in weekly_dates:
            if self.store.has_weekly_data(trade_date, "tushare.weekly"):
                results.append({"trade_date": trade_date, "skipped": 1})
                continue
            try:
                weekly = _with_retry(lambda: self.source.stock_weekly(trade_date), "stock_weekly", trade_date)
                self.store.save_weekly_bars(weekly, "tushare.weekly")
                self.store.log_sync(trade_date, "stock_weekly", "PASS", f"rows={len(weekly)}")
                results.append({"trade_date": trade_date, "stock_weekly": len(weekly)})
            except Exception as exc:
                self.store.log_sync(trade_date, "stock_weekly", "FAIL", str(exc))
                raise
        return results

    def weekly_trade_dates(self, start_date: str, end_date: str) -> list[str]:
        trade_dates = self.source.trade_dates(start_date, end_date)
        if not trade_dates:
            return []
        frame = pd.DataFrame({"trade_date": trade_dates})
        dates = pd.to_datetime(frame["trade_date"], format="%Y%m%d")
        periods = dates.dt.to_period("W-FRI")
        end = pd.to_datetime(end_date, format="%Y%m%d")
        frame = frame[periods.dt.end_time.dt.normalize() <= end]
        frame["week"] = periods[frame.index].astype(str)
        return frame.groupby("week")["trade_date"].max().sort_values().tolist()

    def sync_30m_bars_all(
        self,
        start_date: str,
        end_date: str,
        force_full: bool = False,
        delay_seconds: float = 0.12,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, int]:
        assets = self.store.get_priority_assets()
        if not assets:
            self.sync_assets()
            assets = self.store.get_priority_assets()

        total = len(assets)
        synced_count = 0
        total_rows = 0

        for idx, item in enumerate(assets, 1):
            asset_code = item["asset_code"]
            asset_type = item["asset_type"]
            name = item.get("name", asset_code)
            cur_start = start_date

            if not force_full:
                latest_time = self.store.get_latest_min_trade_time(asset_code, freq="30min")
                if latest_time:
                    latest_date = latest_time.split()[0].replace("-", "")
                    if latest_date >= end_date:
                        if progress_callback:
                            progress_callback(idx, total, asset_code)
                        continue
                    cur_start = latest_date

            try:
                df = _with_retry(
                    lambda code=asset_code, s=cur_start, e=end_date, atype=asset_type: self.source.min_bar(
                        ts_code=code,
                        start_date=s,
                        end_date=e,
                        freq="30min",
                        asset_type=atype,
                    ),
                    f"min_bar({asset_code})",
                    cur_start,
                    attempts=10,
                )
                if df is not None and not df.empty:
                    self.store.save_min_bars(df, freq="30min")
                    total_rows += len(df)
                    synced_count += 1
                    print(f"[{idx}/{total}] [SUCCESS] {asset_code} ({name}) saved {len(df)} rows of 30m bars", flush=True)
                else:
                    print(f"[{idx}/{total}] [EMPTY] {asset_code} ({name}) no 30m bars returned", flush=True)
            except Exception as exc:
                print(f"[{idx}/{total}] [FAILED] {asset_code} ({name}): {exc}", flush=True)
                self.store.log_sync(end_date, f"min_30m_{asset_code}", "FAIL", str(exc))

            if progress_callback:
                progress_callback(idx, total, asset_code)

            if delay_seconds > 0:
                time.sleep(delay_seconds)

        summary = {"total_assets": total, "synced_assets": synced_count, "total_rows": total_rows}
        self.store.log_sync(end_date, "min_30m_all", "PASS", str(summary))
        return summary

    def sync_30m_bars_akshare(
        self,
        start_date: str,
        end_date: str,
        max_workers: int = 1,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, int]:
        from backend.screening.akshare_source import AkshareScreeningSource

        ak_source = AkshareScreeningSource()
        assets = self.store.get_priority_assets()
        if not assets:
            self.sync_assets()
            assets = self.store.get_priority_assets()

        total = len(assets)
        synced_count = 0
        total_rows = 0

        print(f"Starting AkShare 30m sequential sync for {total} assets...", flush=True)

        for idx, item in enumerate(assets, 1):
            asset_code = item["asset_code"]
            asset_type = item["asset_type"]
            name = item.get("name", asset_code)
            cur_start = start_date

            latest_time = self.store.get_latest_min_trade_time(asset_code, freq="30min")
            if latest_time:
                latest_date = latest_time.split()[0].replace("-", "")
                if latest_date >= end_date:
                    if progress_callback:
                        progress_callback(idx, total, asset_code)
                    continue
                cur_start = latest_date

            try:
                df = ak_source.min_bar(asset_code, asset_type, cur_start, end_date, freq="30min")
                if df is not None and not df.empty:
                    self.store.save_min_bars(df, freq="30min")
                    total_rows += len(df)
                    synced_count += 1
                    print(f"[{idx}/{total}] [AkShare OK] {asset_code} ({name}) saved {len(df)} rows (Total saved: {synced_count} assets, {total_rows} rows)", flush=True)
                else:
                    if idx % 50 == 0 or idx == total:
                        print(f"[{idx}/{total}] [AkShare EMPTY] {asset_code} ({name})", flush=True)
            except Exception as exc:
                print(f"[{idx}/{total}] [AkShare ERR] {asset_code} ({name}): {exc}", flush=True)

            if progress_callback:
                progress_callback(idx, total, asset_code)

        summary = {"total_assets": total, "synced_assets": synced_count, "total_rows": total_rows}
        self.store.log_sync(end_date, "min_30m_akshare_all", "PASS", str(summary))
        return summary



def _with_retry(func: Callable[[], T], label: str, trade_date: str, attempts: int = 10) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_error = exc
            err_msg = str(exc)
            if "2次/天" in err_msg:
                print(f"[DAILY_QUOTA_EXCEEDED] {label}: Tushare 2000积分账号 30分钟分钟线接口(stk_mins) 每日额度上限已达(2次/天)。", flush=True)
                raise ScreeningError(f"Tushare 30分钟线 API 触发每日额度限制(2次/天)。需要5000+积分或使用AkShare/开源数据源补给: {exc}")
            elif "1次/小时" in err_msg:
                print(f"[COOL_DOWN] {label} hit 1-hour cooldown block ({exc}). Sleeping 1800s (30m) for reset...", flush=True)
                time.sleep(1800)
                continue
            elif "频率超限" in err_msg or "1次/" in err_msg or "rate limit" in err_msg.lower():
                print(f"[RATE_LIMIT] {label} hit limit: {exc}. Sleeping 65s (attempt {attempt}/{attempts})...", flush=True)
                time.sleep(65)
                continue
            
            print(f"[RETRY_ERR] {label} error: {exc}. Waiting {5 * attempt}s (attempt {attempt}/{attempts})...", flush=True)
            if attempt == attempts:
                break
            time.sleep(5 * attempt)
    assert last_error is not None
    raise ScreeningError(f"{label}({trade_date}) failed after {attempts} attempts: {last_error}") from last_error


