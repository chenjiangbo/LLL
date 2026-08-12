from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backend.screening.config import ScreeningConfig
from backend.screening.errors import ScreeningError
from backend.screening.feature_engine import FeatureEngine
from backend.screening.rules import ScreeningRules, build_candidate
from backend.screening.storage import PostgresScreeningStore
from backend.screening.utils import json_dumps


@dataclass
class CandidateScreeningService:
    config: ScreeningConfig
    store: PostgresScreeningStore

    def run(self, trade_date: str, pools: set[str] | None = None) -> dict[str, Any]:
        selected_pools = pools or {"A"}
        unsupported = selected_pools.difference({"A", "B", "C", "A-Pre", "APRE"})
        if unsupported:
            raise ScreeningError(f"unsupported screening pools: {sorted(unsupported)}")
        history = self.store.load_history(trade_date)
        self._assert_local_data_ready(history, trade_date)
        feature_engine = FeatureEngine(self.config)
        features = feature_engine.build_latest_features(history, trade_date)
        self.store.save_features(features, self.config.ruleset_version)

        previous_date = self.store.previous_candidate_date(trade_date, self.config.ruleset_version)
        previous = self.store.load_candidate_primary(previous_date, self.config.ruleset_version) if previous_date else {}
        rules = ScreeningRules(self.config)
        candidates: list[dict[str, Any]] = []
        for item in features:
            f = item["features"]
            pool_results, risks = rules.evaluate(f, selected_pools)
            if not pool_results:
                continue
            candidates.append(build_candidate(f, pool_results, risks, previous.get(f["asset_code"])))

        candidates = self._sort_candidates(candidates)
        self.store.save_candidates(trade_date, candidates, self.config.ruleset_version)
        outputs = self.export_candidates(trade_date, candidates, selected_pools)
        return {
            "trade_date": trade_date,
            "ruleset_version": self.config.ruleset_version,
            "pools": sorted(selected_pools),
            "feature_count": len(features),
            "skipped_asset_count": len(feature_engine.skipped_assets),
            "skipped_asset_examples": feature_engine.skipped_assets[:10],
            "candidate_count": len(candidates),
            "counts": _counts(candidates),
            "outputs": outputs,
        }

    def export_candidates(self, trade_date: str, candidates: list[dict[str, Any]], pools: set[str]) -> dict[str, str]:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        pool_label = "ABC" if pools == {"A", "B", "C"} else "".join(sorted(pools))
        csv_path = self.config.output_dir / f"{trade_date}_{pool_label}_candidates.csv"
        json_path = self.config.output_dir / f"{trade_date}_{pool_label}_candidates.json"
        rows = [_flat_row(item) for item in candidates]
        pd.DataFrame(rows).to_csv(csv_path, index=False)
        json_path.write_text(json_dumps(candidates), encoding="utf-8")
        return {"csv": str(csv_path), "json": str(json_path)}

    def _assert_local_data_ready(self, history: pd.DataFrame, trade_date: str) -> None:
        if history.empty:
            raise ScreeningError("local screening database is empty; run explicit data sync first")
        latest_dates = set(history["trade_date"].astype(str))
        if trade_date not in latest_dates:
            raise ScreeningError(f"trade_date={trade_date} is not present in local daily_bar")
        latest = history[history["trade_date"].astype(str) == trade_date]
        stock_rows = latest[latest["asset_type"] == "stock"]
        etf_rows = latest[latest["asset_type"] == "etf"]
        if stock_rows.empty:
            raise ScreeningError(f"no stock daily rows for {trade_date}")
        if etf_rows.empty:
            raise ScreeningError(f"no ETF daily rows for {trade_date}")
        missing_basic = stock_rows["turnover_rate"].isna().all() and stock_rows["total_mv"].isna().all()
        if missing_basic:
            raise ScreeningError(f"stock daily_basic is missing for {trade_date}")
        counts = history.groupby("asset_code")["trade_date"].count()
        if int((counts >= self.config.min_listing_days_stock).sum()) == 0:
            raise ScreeningError(
                f"local history is shorter than min_listing_days_stock={self.config.min_listing_days_stock}; "
                "sync a longer explicit history range first"
            )

    def _sort_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        stage_priority = {
            "A3": 0,
            "A2": 1,
            "A1": 2,
            "B3": 0,
            "B2": 1,
            "B1": 2,
            "C3": 0,
            "C2": 1,
            "C1": 2,
        }
        return sorted(
            candidates,
            key=lambda item: (
                item["asset_type"] != "stock",
                item["primary_pool"],
                stage_priority.get(item["stage"], 99),
                -float(item["score"]),
                item["asset_code"],
            ),
        )


def _flat_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_date": item["trade_date"],
        "asset_code": item["asset_code"],
        "name": item.get("name"),
        "asset_type": item["asset_type"],
        "primary_pool": item["primary_pool"],
        "stage": item["stage"],
        "score": item["score"],
        "score_detail": json_dumps(item.get("score_detail", {})),
        "passed_rules": "；".join(item.get("passed_rules", [])),
        "all_pools": ";".join(f"{pool['pool']}{pool['stage'][-1]}:{pool['score']}" for pool in item["pools"]),
        "pct_chg": item.get("pct_chg"),
        "ret_20": item.get("ret_20"),
        "ret_60": item.get("ret_60"),
        "ret_120": item.get("ret_120"),
        "ret_250": item.get("ret_250"),
        "distance_from_high_60": item.get("distance_from_high_60"),
        "distance_from_high_250": item.get("distance_from_high_250"),
        "drawdown_from_20d_high": item.get("drawdown_from_20d_high"),
        "drawdown_from_60d_high": item.get("drawdown_from_60d_high"),
        "max_drawdown_120": item.get("max_drawdown_120"),
        "max_drawdown_250": item.get("max_drawdown_250"),
        "close_vs_ma20": item.get("close_vs_ma20"),
        "close_vs_ma60": item.get("close_vs_ma60"),
        "ma20_slope_10": item.get("ma20_slope_10"),
        "ma60_slope_20": item.get("ma60_slope_20"),
        "ma120_slope_20": item.get("ma120_slope_20"),
        "ma120_slope_60": item.get("ma120_slope_60"),
        "ma60_slope_improvement": item.get("ma60_slope_improvement"),
        "atr_pct": item.get("atr_pct"),
        "rsi14": item.get("rsi14"),
        "rsi14_min_5": item.get("rsi14_min_5"),
        "pullback_pct_120": item.get("pullback_pct_120"),
        "pullback_peak_age_120": item.get("pullback_peak_age_120"),
        "break_swing_low_pct": item.get("break_swing_low_pct"),
        "break_5": item.get("break_5"),
        "break_10": item.get("break_10"),
        "last_swing_high": item.get("last_swing_high"),
        "last_swing_low": item.get("last_swing_low"),
        "higher_low": item.get("higher_low"),
        "lower_high": item.get("lower_high"),
        "lower_low": item.get("lower_low"),
        "amount_ma20": item.get("amount_ma20"),
        "today_volume_ratio_20": item.get("today_volume_ratio_20"),
        "status_change": item["status_change"],
        "reasons": "；".join(item["reasons"]),
        "risks": "；".join(item["risks"]),
    }


def _counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "total": len(candidates),
        "stock": 0,
        "etf": 0,
        "A": 0,
        "B": 0,
        "C": 0,
        "NEW": 0,
        "UPGRADE": 0,
        "DOWNGRADE": 0,
        "STAY": 0,
        "REENTER": 0,
    }
    for item in candidates:
        counts[item["asset_type"]] = counts.get(item["asset_type"], 0) + 1
        counts[item["primary_pool"]] = counts.get(item["primary_pool"], 0) + 1
        counts[item["status_change"]] = counts.get(item["status_change"], 0) + 1
    return counts
