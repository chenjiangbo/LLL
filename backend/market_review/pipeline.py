from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import time
from typing import Any

from backend.market_review.analytics import OverviewAnalytics
from backend.market_review.ai_analysis import MarketReviewAI
from backend.market_review.config import CORE_INDICES, PipelineConfig
from backend.market_review.data_quality import build_data_quality
from backend.market_review.errors import MarketReviewError
from backend.market_review.postgres_storage import PostgresMarketReviewStore
from backend.market_review.sources.akshare_source import AkShareSource
from backend.market_review.sources.tushare_source import TushareSource


def _normalize_trade_date(value: str) -> str:
    return value.replace("-", "")


def _display_date(value: str) -> str:
    value = _normalize_trade_date(value)
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


@dataclass
class MarketReviewPipeline:
    config: PipelineConfig
    source: AkShareSource
    store: Any
    analytics: OverviewAnalytics
    tushare_source: TushareSource

    @classmethod
    def create(cls, config: PipelineConfig | None = None) -> "MarketReviewPipeline":
        config = config or PipelineConfig()
        if not config.database_url:
            raise MarketReviewError("MARKET_REVIEW_DATABASE_URL is required")
        store = PostgresMarketReviewStore(config.database_url)
        return cls(
            config=config,
            source=AkShareSource(),
            store=store,
            analytics=OverviewAnalytics(),
            tushare_source=TushareSource.from_env(),
        )

    def generate_overview(
        self,
        trade_date: str | None = None,
        start_date: str | None = None,
        max_industries: int | None = None,
        report_type: str = "daily",
        include_ai: bool = True,
        force_data_refresh: bool = False,
        force_ai_refresh: bool = False,
    ) -> dict[str, Any]:
        if report_type not in {"daily", "weekly"}:
            raise MarketReviewError(f"unsupported report_type: {report_type}")
        end_date = _normalize_trade_date(trade_date or date.today().strftime("%Y%m%d"))
        start = _normalize_trade_date(start_date or self.config.default_history_start)
        core_indices, index_stats = self._load_incremental_indices(start, end_date, force_data_refresh)
        selected_trade_date = _normalize_trade_date(trade_date or self._latest_index_trade_date(core_indices))
        selected_display_date = _display_date(selected_trade_date)

        self._assert_indices_have_trade_date(core_indices, selected_display_date)

        breadth, breadth_fetched = self._load_or_fetch_daily_snapshot(
            selected_trade_date,
            "market_breadth",
            self.source.fetch_market_breadth_snapshot,
            force_data_refresh,
        )
        industry_summary, summary_fetched = self._load_or_fetch_daily_snapshot(
            selected_trade_date,
            "industry_summary",
            lambda _: self.source.fetch_industry_summary(),
            force_data_refresh,
        )
        industry_histories, industry_stats = self._load_incremental_industries(
            industry_summary=industry_summary,
            start_date=start,
            end_date=selected_trade_date,
            max_industries=max_industries,
            force_refresh=force_data_refresh,
        )

        self.store.save_raw_snapshot(selected_trade_date, "core_indices", "akshare", core_indices)
        self.store.save_raw_snapshot(selected_trade_date, "market_breadth", "akshare", breadth)
        self.store.save_raw_snapshot(selected_trade_date, "industry_summary", "akshare", industry_summary)
        self.store.save_raw_snapshot(selected_trade_date, "industry_histories", "akshare", industry_histories)

        attribution_data, attribution_stats = self._load_attribution_data(
            selected_trade_date, force_data_refresh
        )
        mover_codes = self._select_mover_codes(core_indices, attribution_data)
        industry_map_source = "ths.stock_profile_sw_industry"
        industry_map = self.store.load_raw_snapshot(
            selected_trade_date, "constituent_industry_map", industry_map_source
        )
        industry_map_fetched = False
        cached_codes = {
            str(row["code"]).zfill(6)
            for row in (industry_map or {}).get("rows", [])
            if row.get("code") and row.get("name") and row.get("industry")
        }
        if force_data_refresh or not mover_codes.issubset(cached_codes):
            industry_map = self.source.fetch_ths_industry_map(mover_codes)
            self.store.save_raw_snapshot(
                selected_trade_date,
                "constituent_industry_map",
                industry_map_source,
                industry_map,
            )
            industry_map_fetched = True
        attribution_data["industry_map"] = industry_map
        attribution_stats["industry_map_fetched"] = industry_map_fetched
        stock_history, stock_history_stats = self._load_stock_technical_history(
            selected_trade_date, core_indices, attribution_data["stock_daily"]
        )
        attribution_data["stock_history"] = stock_history
        attribution_stats["stock_technical_history"] = stock_history_stats

        breadth_history = self.store.load_raw_snapshot_history(
            "market_breadth", "akshare", selected_trade_date
        )
        previous_report = self.store.load_previous_overview_report(selected_trade_date)
        report = self.analytics.build(
            trade_date=selected_trade_date,
            core_indices=core_indices,
            breadth=breadth,
            industry_summary=industry_summary,
            industry_histories=industry_histories,
            breadth_history=breadth_history,
            previous_report=previous_report,
            attribution_data=attribution_data,
        )
        report["industry_scope"] = {
            "requested_max_industries": max_industries,
            "actual_industries": len(industry_histories),
            "is_full_universe": max_industries is None,
        }
        report["mode"] = report_type
        report["data_quality"] = build_data_quality(
            trade_date=selected_trade_date,
            breadth=breadth,
            industry_summary=industry_summary,
            index_rows=report["indices"],
            industry_rows=report["industries"],
        )
        if report_type == "weekly" and not report["data_quality"]["is_final"]:
            raise MarketReviewError(
                f"weekly report requires final data; current status={report['data_quality']['status']}"
            )
        report["data_update"] = {
            "strategy": "incremental",
            "generated_at": datetime.utcnow().isoformat(),
            "index_series": index_stats,
            "industry_series": industry_stats,
            "market_breadth_fetched": breadth_fetched,
            "industry_summary_fetched": summary_fetched,
            "attribution": attribution_stats,
        }
        if include_ai:
            report["ai_analysis"] = MarketReviewAI(self.store).generate(
                report,
                report_type=report_type,
                force=force_ai_refresh,
            )
        self.store.save_overview_report(selected_trade_date, report)
        self._write_report_json(selected_trade_date, report)
        return report

    def generate_ai_for_existing_report(
        self,
        trade_date: str,
        report_type: str = "daily",
        force: bool = False,
    ) -> dict[str, Any]:
        report = self.store.load_overview_report(_normalize_trade_date(trade_date))
        if report is None:
            raise MarketReviewError(f"no overview report found for trade_date={trade_date}")
        report["mode"] = report_type
        report["ai_analysis"] = MarketReviewAI(self.store).generate(
            report,
            report_type=report_type,
            force=force,
        )
        self.store.save_overview_report(report["trade_date"], report)
        self._write_report_json(report["trade_date"], report)
        return report

    def _load_incremental_indices(
        self,
        start_date: str,
        end_date: str,
        force_refresh: bool,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        result: dict[str, Any] = {}
        fetched = 0
        reused = 0
        bootstrapped = 0
        source_name = "ak.stock_zh_index_daily_tx"
        legacy = self.store.load_latest_raw_snapshot("core_indices", "akshare", end_date)
        for index_id, meta in CORE_INDICES.items():
            latest = self.store.latest_series_date("index", index_id, source_name)
            if latest is None and isinstance(legacy, dict) and index_id in legacy:
                self.store.save_series_records(
                    "index", index_id, source_name, legacy[index_id]["records"], "date"
                )
                latest = self.store.latest_series_date("index", index_id, source_name)
                bootstrapped += 1
            fetch_start = self._incremental_fetch_start(start_date, end_date, latest, force_refresh)
            if fetch_start:
                payload = self.source.fetch_index_history(index_id, fetch_start, end_date)
                self.store.save_series_records(
                    "index", index_id, source_name, payload["records"], "date"
                )
                fetched += 1
            else:
                reused += 1
            records = self.store.load_series_records(
                "index", index_id, source_name, start_date, end_date
            )
            if not records:
                raise MarketReviewError(f"no cached index records for {index_id} in {start_date}-{end_date}")
            result[index_id] = {
                "id": index_id,
                "name": meta["name"],
                "symbol": meta["ak_symbol"],
                "quote_url": meta["quote_url"],
                "source": source_name,
                "records": records,
            }
        return result, {
            "fetched_series": fetched,
            "reused_series": reused,
            "bootstrapped_series": bootstrapped,
        }

    def _load_attribution_data(
        self,
        trade_date: str,
        force_refresh: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        daily_source = "tushare.daily"
        stock_daily = self.store.load_raw_snapshot(trade_date, "stock_daily", daily_source)
        daily_fetched = False
        if stock_daily is None or force_refresh:
            stock_daily = self.tushare_source.fetch_daily_snapshot(trade_date)
            self.store.save_raw_snapshot(trade_date, "stock_daily", daily_source, stock_daily)
            daily_fetched = True

        weights: dict[str, Any] = {}
        fetched_weights: list[str] = []
        reused_weights: list[str] = []
        for index_id, meta in CORE_INDICES.items():
            source_name = (
                "ak.index_stock_cons_weight_csindex"
                if meta["weight_source"] == "akshare"
                else "tushare.index_weight"
            )
            snapshot_type = f"index_weights_{index_id}"
            payload = self.store.load_raw_snapshot(trade_date, snapshot_type, source_name)
            if payload is None or force_refresh:
                if meta["weight_source"] == "akshare":
                    payload = self.source.fetch_index_weights(index_id, trade_date)
                else:
                    payload = self.tushare_source.fetch_index_weights(index_id, trade_date)
                self.store.save_raw_snapshot(trade_date, snapshot_type, source_name, payload)
                fetched_weights.append(index_id)
            else:
                reused_weights.append(index_id)
            weights[index_id] = payload
        return {
            "stock_daily": stock_daily,
            "weights": weights,
        }, {
            "stock_daily_fetched": daily_fetched,
            "fetched_weights": fetched_weights,
            "reused_weights": reused_weights,
        }

    def _load_stock_technical_history(
        self,
        trade_date: str,
        core_indices: dict[str, Any],
        current_daily: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        records = sorted(core_indices["hs300"]["records"], key=lambda row: str(row["date"]))
        trade_dates = [
            str(row["date"]).replace("-", "")
            for row in records
            if str(row["date"]).replace("-", "") <= trade_date
        ][-60:]
        if len(trade_dates) != 60 or trade_dates[-1] != trade_date:
            raise MarketReviewError(
                f"market technical breadth requires 60 trading dates ending at {trade_date}"
            )

        history: list[dict[str, Any]] = []
        fetched_daily = 0
        fetched_adjustments = 0
        for current_date in trade_dates:
            daily = current_daily if current_date == trade_date else self.store.load_raw_snapshot(
                current_date, "stock_daily", "tushare.daily"
            )
            if daily is None:
                daily = self.tushare_source.fetch_daily_snapshot(current_date)
                self.store.save_raw_snapshot(
                    current_date, "stock_daily", "tushare.daily", daily
                )
                fetched_daily += 1
                time.sleep(0.35)

            adjustment = self.store.load_raw_snapshot(
                current_date, "stock_adjustment_factors", "tushare.adj_factor"
            )
            if adjustment is None:
                adjustment = self.tushare_source.fetch_adjustment_factor_snapshot(current_date)
                self.store.save_raw_snapshot(
                    current_date,
                    "stock_adjustment_factors",
                    "tushare.adj_factor",
                    adjustment,
                )
                fetched_adjustments += 1
                time.sleep(0.35)
            history.append(
                {"trade_date": current_date, "daily": daily, "adjustment": adjustment}
            )
        return history, {
            "trading_days": len(history),
            "daily_snapshots_fetched": fetched_daily,
            "adjustment_snapshots_fetched": fetched_adjustments,
        }

    @staticmethod
    def _select_mover_codes(
        core_indices: dict[str, Any], attribution_data: dict[str, Any]
    ) -> set[str]:
        daily_by_code = {
            str(row["ts_code"]).split(".")[0].zfill(6): row
            for row in attribution_data["stock_daily"]["rows"]
            if row.get("ts_code") and row.get("pct_chg") is not None
        }
        selected: set[str] = set()
        for index_id, payload in core_indices.items():
            records = sorted(payload["records"], key=lambda row: str(row["date"]))
            if len(records) < 2:
                raise MarketReviewError(f"index {index_id} needs two records to select movers")
            index_return = (float(records[-1]["close"]) / float(records[-2]["close"]) - 1) * 100
            candidates = []
            for row in attribution_data["weights"][index_id]["rows"]:
                code = str(row["code"]).zfill(6)
                daily = daily_by_code.get(code)
                if daily is not None:
                    candidates.append((code, float(daily["pct_chg"])))
            if len(candidates) < 5:
                raise MarketReviewError(f"index {index_id} has fewer than five constituent returns")
            candidates.sort(key=lambda item: item[1], reverse=index_return >= 0)
            selected.update(code for code, _ in candidates[:5])
        return selected

    def _load_incremental_industries(
        self,
        industry_summary: dict[str, Any],
        start_date: str,
        end_date: str,
        max_industries: int | None,
        force_refresh: bool,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        names = [str(row["板块"]) for row in industry_summary["rows"] if row.get("板块")]
        if max_industries is not None:
            names = names[:max_industries]
        if not names:
            raise MarketReviewError("industry summary contains no industry names")
        source_name = "ak.stock_board_industry_index_ths"
        histories: dict[str, Any] = {}
        fetched = 0
        reused = 0
        bootstrapped = 0
        legacy = self.store.load_latest_raw_snapshot("industry_histories", "akshare", end_date)
        for name in names:
            latest = self.store.latest_series_date("industry", name, source_name)
            if latest is None and isinstance(legacy, dict) and name in legacy:
                self.store.save_series_records(
                    "industry", name, source_name, legacy[name]["records"], "日期"
                )
                latest = self.store.latest_series_date("industry", name, source_name)
                bootstrapped += 1
            fetch_start = self._incremental_fetch_start(start_date, end_date, latest, force_refresh)
            if fetch_start:
                payload = self.source.fetch_industry_history(name, fetch_start, end_date)
                self.store.save_series_records(
                    "industry", name, source_name, payload["records"], "日期"
                )
                fetched += 1
            else:
                reused += 1
            records = self.store.load_series_records(
                "industry", name, source_name, start_date, end_date
            )
            if not records:
                raise MarketReviewError(f"no cached industry records for {name} in {start_date}-{end_date}")
            histories[name] = {"name": name, "source": source_name, "records": records}
        return histories, {
            "fetched_series": fetched,
            "reused_series": reused,
            "bootstrapped_series": bootstrapped,
        }

    def _incremental_fetch_start(
        self,
        requested_start: str,
        end_date: str,
        latest_cached: str | None,
        force_refresh: bool,
    ) -> str | None:
        if latest_cached is None:
            return requested_start
        if latest_cached < end_date:
            next_date = (datetime.strptime(latest_cached, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
            return max(requested_start, next_date)
        if force_refresh:
            return end_date
        return None

    def _load_or_fetch_daily_snapshot(
        self,
        trade_date: str,
        snapshot_type: str,
        fetcher: Any,
        force_refresh: bool,
    ) -> tuple[dict[str, Any], bool]:
        cached = self.store.load_raw_snapshot(trade_date, snapshot_type, "akshare")
        if cached is not None and not force_refresh:
            return cached, False
        today = date.today().strftime("%Y%m%d")
        if trade_date != today:
            action = "refresh" if cached is not None else "backfill"
            raise MarketReviewError(
                f"cannot {action} historical {snapshot_type} for {trade_date}; "
                "AkShare provides only a live snapshot and no verified historical snapshot"
            )
        payload = fetcher(trade_date)
        self.store.save_raw_snapshot(trade_date, snapshot_type, "akshare", payload)
        return payload, True

    def _latest_index_trade_date(self, core_indices: dict[str, Any]) -> str:
        dates = []
        for payload in core_indices.values():
            if not payload["records"]:
                raise MarketReviewError(f"index {payload['name']} has no records")
            dates.append(str(payload["records"][-1]["date"]).replace("-", ""))
        latest = min(dates)
        if not latest:
            raise MarketReviewError("cannot determine latest common index trade date")
        return latest

    def _assert_indices_have_trade_date(self, core_indices: dict[str, Any], display_date: str) -> None:
        missing = []
        for payload in core_indices.values():
            dates = {str(row["date"]) for row in payload["records"]}
            if display_date not in dates:
                missing.append(payload["name"])
        if missing:
            raise MarketReviewError(f"indices missing trade date {display_date}: {missing}")

    def _fetch_industry_histories(
        self,
        industry_summary: dict[str, Any],
        start_date: str,
        end_date: str,
        max_industries: int | None,
    ) -> dict[str, Any]:
        rows = industry_summary["rows"]
        industry_names = [str(row["板块"]) for row in rows if row.get("板块")]
        if max_industries is not None:
            industry_names = industry_names[:max_industries]
        if not industry_names:
            raise MarketReviewError("industry summary contains no industry names")
        histories = {}
        for name in industry_names:
            histories[name] = self.source.fetch_industry_history(name, start_date, end_date)
        return histories

    def _write_report_json(self, trade_date: str, report: dict[str, Any]) -> None:
        import json

        self.config.report_dir.mkdir(parents=True, exist_ok=True)
        output = Path(self.config.report_dir) / f"overview_{trade_date}.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
