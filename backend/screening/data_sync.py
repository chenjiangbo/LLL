from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import time
from typing import Any, Callable, TypeVar
from zoneinfo import ZoneInfo

import pandas as pd

from backend.screening.errors import ScreeningError
from backend.screening.storage import PostgresScreeningStore, _completed_30m_slots
from backend.screening.tushare_errors import is_empty_data_error, is_tushare_rate_limit_error
from backend.screening.tushare_source import TushareScreeningSource


T = TypeVar("T")


@dataclass
class ScreeningDataSync:
    source: TushareScreeningSource
    store: PostgresScreeningStore

    def sync_assets(self) -> dict[str, int]:
        stocks = _with_retry(lambda: self.source.stock_basic(), "stock_basic", "asset_master", attempts=3)
        etfs = _with_retry(lambda: self.source.fund_basic(), "fund_basic", "asset_master", attempts=3)
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

    def sync_daily_basic_for_date(self, trade_date: str) -> dict[str, int | str]:
        try:
            daily_basic = _with_retry(lambda: self.source.daily_basic(trade_date), "daily_basic", trade_date)
            self.store.save_daily_basic(daily_basic)
            result = {"trade_date": trade_date, "daily_basic": len(daily_basic)}
            self.store.log_sync(trade_date, "daily_basic", "PASS", str(result))
            return result
        except Exception as exc:
            self.store.log_sync(trade_date, "daily_basic", "FAIL", str(exc))
            raise

    def sync_financials_for_stock(self, ts_code: str) -> dict[str, int | str]:
        clean_code = ts_code.strip().upper()
        if "." not in clean_code:
            clean_code = clean_code + (".SH" if clean_code.startswith("6") else ".SZ")
        try:
            def fetch_financial_source(label: str, fetcher: Callable[[], pd.DataFrame]) -> pd.DataFrame:
                try:
                    return _with_retry(fetcher, label, clean_code, attempts=3, retry_empty=True)
                except ScreeningError as exc:
                    if str(exc).startswith("EMPTY_DATA:"):
                        self.store.mark_event_sync_status(clean_code, label, "EMPTY", 0, str(exc))
                        return pd.DataFrame()
                    raise

            income = fetch_financial_source("income_vip", lambda: self.source.income_vip(clean_code))
            cashflow = fetch_financial_source("cashflow_vip", lambda: self.source.cashflow_vip(clean_code))
            indicator = fetch_financial_source("fina_indicator_vip", lambda: self.source.fina_indicator_vip(clean_code))
            forecast = fetch_financial_source("forecast_vip", lambda: self.source.forecast_vip(clean_code))
            express = fetch_financial_source("express_vip", lambda: self.source.express_vip(clean_code))
            result = {
                "ts_code": clean_code,
                "income": self.store.save_income_statements(income),
                "cashflow": self.store.save_cashflow_statements(cashflow),
                "fina_indicator": self.store.save_fina_indicators(indicator),
                "forecast": self.store.save_forecasts(forecast),
                "express": self.store.save_express_reports(express, clean_code),
            }
            source_to_key = {
                "income_vip": "income",
                "cashflow_vip": "cashflow",
                "fina_indicator_vip": "fina_indicator",
                "forecast_vip": "forecast",
                "express_vip": "express",
            }
            for source_name, result_key in source_to_key.items():
                row_count = int(result[result_key])
                if row_count > 0:
                    self.store.mark_event_sync_status(clean_code, source_name, "PASS", row_count, None)
                else:
                    self.store.mark_event_sync_status(clean_code, source_name, "EMPTY", 0, "Tushare returned no PIT rows for this stock")
            return result
        except Exception as exc:
            self.store.log_sync(clean_code, "financials", "FAIL", str(exc))
            raise

    def sync_supply_events_for_stock(self, ts_code: str) -> dict[str, int | str]:
        clean_code = ts_code.strip().upper()
        if "." not in clean_code:
            clean_code = clean_code + (".SH" if clean_code.startswith("6") else ".SZ")
        try:
            share_float = _with_retry(lambda: self.source.share_float(clean_code), "share_float", clean_code, attempts=2)
            holder_trade = _with_retry(lambda: self.source.stk_holdertrade(clean_code), "stk_holdertrade", clean_code, attempts=2)
            return {
                "ts_code": clean_code,
                "share_float": self.store.save_share_float_events(share_float, clean_code),
                "stk_holdertrade": self.store.save_holder_trades(holder_trade, clean_code),
            }
        except Exception as exc:
            self.store.log_sync(clean_code, "supply_events", "FAIL", str(exc))
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
        asset_types: set[str] | None = None,
        stop_callback: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        assets = self.store.get_priority_assets()
        if not assets:
            self.sync_assets()
            assets = self.store.get_priority_assets()
        if asset_types is not None:
            if not asset_types or not asset_types <= {"stock", "etf"}:
                raise ScreeningError("asset_types must contain stock and/or etf")
            assets = [item for item in assets if item["asset_type"] in asset_types]
            if not assets:
                raise ScreeningError("no assets available for requested 30m sync types")

        total = len(assets)
        synced_count = 0
        inactive_count = 0
        total_rows = 0
        failed_assets: list[dict[str, str]] = []
        today_shanghai = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
        expected_slot_labels = _completed_30m_slots(datetime.now(ZoneInfo("Asia/Shanghai")).time()) if end_date == today_shanghai else [
            "10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00"
        ]
        expected_slots = len(expected_slot_labels)
        from backend.screening.akshare_source import AkshareScreeningSource
        ak_source = AkshareScreeningSource()

        def record_existing_status(code: str, atype: str) -> None:
            actual = self.store.count_min_slots(code, end_date, "30min")
            status = "COMPLETE" if actual >= expected_slots else "PARTIAL" if actual > 0 else "PENDING"
            self.store.save_min_sync_status(code, end_date, expected_slots, actual, status)
            if status != "COMPLETE":
                failed_assets.append({"asset_code": code, "asset_type": atype, "error": f"existing data only {actual}/{expected_slots} slots"})

        if expected_slots == 0:
            summary = {
                "total_assets": total,
                "synced_assets": 0,
                "failed_assets": 0,
                "inactive_assets": 0,
                "total_rows": 0,
                "failures": [],
                "validation": {"total_assets": total, "complete_assets": 0, "pending_assets": total, "complete": False},
                "status": "NOT_READY",
            }
            self.store.log_sync(end_date, "min_30m_all", "NOT_READY", str(summary))
            return summary

        for idx, item in enumerate(assets, 1):
            if stop_callback and stop_callback():
                raise ScreeningError("DATA_SYNC_CANCELLED: task cancellation requested")
            asset_code = item["asset_code"]
            asset_type = item["asset_type"]
            name = item.get("name", asset_code)
            cur_start = start_date

            previous_status = self.store.get_min_sync_status(asset_code, end_date, "30min")
            if previous_status and previous_status.get("status") == "INACTIVE":
                inactive_count += 1
                if progress_callback:
                    progress_callback(idx, total, asset_code)
                continue

            if not force_full:
                latest_time = self.store.get_latest_min_trade_time(asset_code, freq="30min")
                if latest_time:
                    latest_date = latest_time.split()[0].replace("-", "")
                    if latest_date > end_date:
                        record_existing_status(asset_code, asset_type)
                        if progress_callback:
                            progress_callback(idx, total, asset_code)
                        continue
                    elif latest_date == end_date:
                        latest_slot = latest_time.split()[1][:5] if " " in latest_time else ""
                        if end_date == today_shanghai:
                            if latest_slot and latest_slot >= expected_slot_labels[-1]:
                                record_existing_status(asset_code, asset_type)
                                if progress_callback:
                                    progress_callback(idx, total, asset_code)
                                continue
                        else:
                            if latest_slot >= "15:00":
                                record_existing_status(asset_code, asset_type)
                                if progress_callback:
                                    progress_callback(idx, total, asset_code)
                                continue
                        cur_start = latest_date
                    else:
                        cur_start = latest_date if latest_date >= start_date else start_date

            # 同一日期、同一完成时段已经尝试过且仍不完整时，本轮不重复请求。
            # 下一时段出现后 expected_slots 增大，才会重新补齐。
            if (
                previous_status
                and int(previous_status.get("expected_slots") or 0) == expected_slots
                and previous_status.get("status") in {"PARTIAL", "FAILED", "RATE_LIMITED", "EMPTY"}
            ):
                actual = self.store.count_min_slots(asset_code, end_date, "30min")
                self.store.save_min_sync_status(
                    asset_code, end_date, expected_slots, actual,
                    previous_status["status"], previous_status.get("last_error"),
                )
                failed_assets.append({"asset_code": asset_code, "asset_type": asset_type, "error": previous_status.get("last_error") or f"already attempted {actual}/{expected_slots} slots"})
                if progress_callback:
                    progress_callback(idx, total, asset_code)
                continue

            try:
                # 30 分钟线正式链路只使用 AkShare。Tushare stk_mins 存在单标的
                # 分钟级限频，不能作为全市场同步来源，也不能隐式切换数据源。
                df = ak_source.min_bar(
                    asset_code,
                    asset_type,
                    cur_start,
                    end_date,
                    freq="30min",
                )
                if df is not None and not df.empty:
                    self.store.save_min_bars(df, freq="30min")
                    total_rows += len(df)
                    synced_count += 1
                    actual_slots = self.store.count_min_slots(asset_code, end_date, "30min")
                    status = "COMPLETE" if actual_slots >= expected_slots else "PARTIAL"
                    self.store.save_min_sync_status(asset_code, end_date, expected_slots, actual_slots, status)
                    if status != "COMPLETE":
                        failed_assets.append({"asset_code": asset_code, "asset_type": asset_type, "error": f"only {actual_slots}/{expected_slots} slots"})
                    print(f"[{idx}/{total}] [AkShare {status}] {asset_code} ({name}) saved {len(df)} rows", flush=True)
                else:
                    error = "AkShare returned no bars for requested date"
                    self.store.save_min_sync_status(asset_code, end_date, expected_slots, 0, "EMPTY", error)
                    failed_assets.append({"asset_code": asset_code, "asset_type": asset_type, "error": error})
                    print(f"[{idx}/{total}] [EMPTY] {asset_code} ({name}) no 30m bars returned", flush=True)
            except Exception as exc:
                failure = {"asset_code": asset_code, "asset_type": asset_type, "error": str(exc)}
                failed_assets.append(failure)
                error_text = str(exc)
                status = "RATE_LIMITED" if any(token in error_text.lower() for token in ("rate limit", "频率", "限频", "too many")) else "FAILED"
                self.store.save_min_sync_status(asset_code, end_date, expected_slots, 0, status, error_text)
                print(f"[{idx}/{total}] [AkShare {status}] {asset_code} ({name}): {exc}", flush=True)

            if progress_callback:
                progress_callback(idx, total, asset_code)

            if delay_seconds > 0:
                time.sleep(delay_seconds)

        validation = self.store.validate_min_sync_date(end_date)
        summary = {
            "total_assets": total,
            "synced_assets": synced_count,
            "failed_assets": len(failed_assets),
            "inactive_assets": inactive_count,
            "total_rows": total_rows,
            "failures": failed_assets,
            "validation": validation,
            "status": "PASS" if validation["complete"] else "FAIL",
        }
        self.store.log_sync(end_date, "min_30m_all", summary["status"], str(summary))
        return summary

    def sync_30m_bars_for_date(
        self,
        trade_date: str,
        asset_types: set[str],
        delay_seconds: float = 0.12,
        retry_attempts: int = 3,
        progress_callback: Callable[[int, int, str, str], None] | None = None,
        stop_callback: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Fill one historical date without treating later data as coverage for that date."""
        from backend.screening.akshare_source import AkshareScreeningSource

        if not asset_types or not asset_types <= {"stock", "etf"}:
            raise ScreeningError("asset_types must contain stock and/or etf")
        assets = [item for item in self.store.get_all_assets() if item["asset_type"] in asset_types]
        if not assets:
            raise ScreeningError("no assets available for requested 30m backfill types")
        total = len(assets)
        synced = skipped = inactive = failed = rows_saved = 0
        failures: list[dict[str, str]] = []
        source = AkshareScreeningSource()
        expected_slots = 8
        for index, item in enumerate(assets, 1):
            if stop_callback and stop_callback():
                raise ScreeningError("DATA_SYNC_CANCELLED: task cancellation requested")
            code = item["asset_code"]
            asset_type = item["asset_type"]
            previous_status = self.store.get_min_sync_status(code, trade_date, "30min")
            if previous_status and previous_status.get("status") == "INACTIVE":
                inactive += 1
                skipped += 1
                if progress_callback:
                    progress_callback(index, total, code, "INACTIVE")
                continue
            actual = self.store.count_min_slots(code, trade_date, "30min")
            if actual >= expected_slots:
                self.store.save_min_sync_status(code, trade_date, expected_slots, actual, "COMPLETE")
                skipped += 1
                if progress_callback:
                    progress_callback(index, total, code, "SKIPPED")
                continue
            last_error: Exception | None = None
            saved = False
            marked_inactive = False
            for attempt in range(1, retry_attempts + 1):
                try:
                    frame = source.min_bar(code, asset_type, trade_date, trade_date, freq="30min")
                    if frame is None or frame.empty:
                        self.store.save_min_sync_status(code, trade_date, expected_slots, actual, "INACTIVE", "当天无有效行情，可能停牌或已退市")
                        marked_inactive = True
                        inactive += 1
                        skipped += 1
                        break
                    self.store.save_min_bars(frame, freq="30min")
                    actual = self.store.count_min_slots(code, trade_date, "30min")
                    status = "COMPLETE" if actual >= expected_slots else "PARTIAL"
                    self.store.save_min_sync_status(code, trade_date, expected_slots, actual, status, None if status == "COMPLETE" else f"only {actual}/{expected_slots} slots")
                    rows_saved += len(frame)
                    synced += 1
                    saved = True
                    if status != "COMPLETE":
                        failures.append({"asset_code": code, "asset_type": asset_type, "error": f"only {actual}/{expected_slots} slots"})
                        failed += 1
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < retry_attempts:
                        time.sleep(5 * attempt)
            if not saved and not marked_inactive:
                message = str(last_error or "unknown sync error")
                self.store.save_min_sync_status(code, trade_date, expected_slots, actual, "FAILED", message)
                failures.append({"asset_code": code, "asset_type": asset_type, "error": message})
                failed += 1
            if progress_callback:
                progress_callback(index, total, code, "INACTIVE" if marked_inactive else "OK" if saved else "FAILED")
            if delay_seconds > 0:
                time.sleep(delay_seconds)
        validations = [self.store.validate_min_sync_date(trade_date, asset_type=kind) for kind in sorted(asset_types)]
        validation = {
            key: sum(int(item.get(key) or 0) for item in validations)
            for key in ("total_assets", "complete_assets", "inactive_assets", "partial_assets", "failed_assets", "pending_assets")
        }
        validation["complete"] = bool(validations) and all(bool(item.get("complete")) for item in validations)
        return {
            "trade_date": trade_date,
            "total_assets": total,
            "synced_assets": synced,
            "skipped_assets": skipped,
            "inactive_assets": inactive,
            "failed_assets": failed,
            "total_rows": rows_saved,
            "failures": failures,
            "validation": validation,
            "status": "PASS" if validation["complete"] else "FAIL",
        }

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
                if latest_date > end_date:
                    if progress_callback:
                        progress_callback(idx, total, asset_code)
                    continue
                elif latest_date == end_date:
                    today_str = date.today().strftime("%Y%m%d")
                    latest_slot = latest_time.split()[1][:5] if " " in latest_time else ""
                    if end_date == today_str:
                        expected_slots = _completed_30m_slots(datetime.now(ZoneInfo("Asia/Shanghai")).time())
                        if not expected_slots or (latest_slot and latest_slot >= expected_slots[-1]):
                            if progress_callback:
                                progress_callback(idx, total, asset_code)
                            continue
                    else:
                        if latest_slot >= "15:00":
                            if progress_callback:
                                progress_callback(idx, total, asset_code)
                            continue
                    cur_start = latest_date
                else:
                    cur_start = latest_date if latest_date >= start_date else start_date

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



def _with_retry(
    func: Callable[[], T],
    label: str,
    trade_date: str,
    attempts: int = 10,
    retry_empty: bool = False,
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_error = exc
            if is_tushare_rate_limit_error(exc):
                print(f"[TUSHARE_RATE_LIMIT] {label}({trade_date}) hit Tushare rate limit: {exc}", flush=True)
                raise ScreeningError(f"TUSHARE_RATE_LIMIT:{label}({trade_date}):{exc}") from exc
            if is_empty_data_error(exc):
                if retry_empty and attempt < attempts:
                    wait_seconds = 3 * attempt
                    print(
                        f"[EMPTY_RETRY] {label}({trade_date}) returned empty data. "
                        f"Waiting {wait_seconds}s (attempt {attempt}/{attempts})...",
                        flush=True,
                    )
                    time.sleep(wait_seconds)
                    continue
                print(f"[EMPTY_DATA] {label}({trade_date}) returned empty data after {attempt} attempt(s).", flush=True)
                raise ScreeningError(f"EMPTY_DATA:{label}({trade_date})") from exc
            
            print(f"[RETRY_ERR] {label} error: {exc}. Waiting {5 * attempt}s (attempt {attempt}/{attempts})...", flush=True)
            if attempt == attempts:
                break
            time.sleep(5 * attempt)
    assert last_error is not None
    raise ScreeningError(f"{label}({trade_date}) failed after {attempts} attempts: {last_error}") from last_error
