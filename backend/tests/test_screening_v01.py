from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

import pandas as pd

from backend.screening.config import ScreeningConfig
from backend.screening.data_sync import ScreeningDataSync
from backend.screening.feature_engine import FeatureEngine
from backend.screening.service import CandidateScreeningService


class ScreeningFeatureTests(unittest.TestCase):
    def test_prev_high_does_not_include_today(self) -> None:
        rows = _asset_rows("000001.SZ", "stock", "测试股票", 80, base=10.0)
        rows[-1]["high"] = 100.0
        rows[-1]["close"] = 50.0
        df = pd.DataFrame(rows)

        features = FeatureEngine(ScreeningConfig())._build_asset_features(df)
        latest = features.iloc[-1]

        self.assertLess(latest["prev_high_60"], 100.0)
        self.assertTrue(latest["adj_close"] > latest["prev_high_60"])


class ScreeningServiceTests(unittest.TestCase):
    def test_service_exports_candidates_from_local_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = ScreeningConfig(
                output_dir=root / "output",
                min_amount_ma20_stock=1,
                min_amount_ma20_etf=1,
                threshold_a=40,
                threshold_b=40,
                threshold_c=40,
            )
            stock_rows = _asset_rows("000001.SZ", "stock", "测试股票", 320, base=10.0)
            etf_rows = _asset_rows("510300.SH", "etf", "测试ETF", 320, base=5.0)
            bars = pd.DataFrame(stock_rows + etf_rows)
            store = FakeScreeningStore(bars)

            result = CandidateScreeningService(config, store).run("d319")

            self.assertGreater(result["feature_count"], 0)
            self.assertGreater(result["candidate_count"], 0)
            self.assertEqual(result["pools"], ["A"])
            self.assertTrue(all(item["primary_pool"] == "A" for item in store.candidates))
            self.assertTrue((root / "output" / "d319_A_candidates.csv").is_file())
            self.assertTrue((root / "output" / "d319_A_candidates.json").is_file())

    def test_manual_select_a_records_review_decision(self) -> None:
        store = FakeScreeningStore(pd.DataFrame())
        store.candidates = [
            {
                "trade_date": "20260806",
                "asset_code": "000001.SZ",
                "asset_type": "stock",
                "primary_pool": "A",
                "stage": "A2",
                "score": 68.5,
            }
        ]

        selected = store.select_manual_candidate("20260806", "000001.SZ", "A", "SELECT", "继续看")

        self.assertEqual(selected["action"], "SELECT")
        self.assertEqual(selected["asset_code"], "000001.SZ")
        self.assertEqual(store.manual_selections[0]["note"], "继续看")

    def test_weekly_trade_dates_use_last_open_day_of_week(self) -> None:
        source = FakeSource(["20230103", "20230104", "20230106", "20230109", "20230113"])
        sync = ScreeningDataSync(source, FakeScreeningStore(pd.DataFrame()))

        self.assertEqual(sync.weekly_trade_dates("20230101", "20230113"), ["20230106", "20230113"])


class FakeSource:
    def __init__(self, trade_dates: list[str]) -> None:
        self._trade_dates = trade_dates

    def trade_dates(self, start_date: str, end_date: str) -> list[str]:
        return [item for item in self._trade_dates if start_date <= item <= end_date]


class FakeScreeningStore:
    def __init__(self, history: pd.DataFrame) -> None:
        self.history = history
        self.features: list[dict[str, Any]] = []
        self.candidates: list[dict[str, Any]] = []
        self.manual_selections: list[dict[str, Any]] = []

    def load_history(self, end_date: str, min_start_date: str | None = None) -> pd.DataFrame:
        result = self.history[self.history["trade_date"] <= end_date]
        if min_start_date:
            result = result[result["trade_date"] >= min_start_date]
        return result.copy()

    def save_features(self, features: list[dict[str, Any]], ruleset_version: str) -> None:
        self.features = features

    def previous_candidate_date(self, trade_date: str, ruleset_version: str) -> str | None:
        return None

    def load_candidate_primary(self, trade_date: str, ruleset_version: str) -> dict[str, dict[str, Any]]:
        return {}

    def save_candidates(self, trade_date: str, candidates: list[dict[str, Any]], ruleset_version: str) -> None:
        self.candidates = candidates

    def has_daily_data(self, trade_date: str) -> bool:
        return False

    def has_weekly_data(self, trade_date: str, source: str = "tushare.weekly") -> bool:
        return False

    def save_weekly_bars(self, df: pd.DataFrame, source: str) -> None:
        return None

    def log_sync(self, trade_date: str, sync_type: str, status: str, message: str | None = None) -> None:
        return None

    def select_manual_candidate(
        self,
        trade_date: str,
        asset_code: str,
        pool: str,
        action: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        for candidate in self.candidates:
            if (
                candidate["trade_date"] == trade_date
                and candidate["asset_code"] == asset_code
                and candidate["primary_pool"] == pool
            ):
                record = {
                    "trade_date": trade_date,
                    "asset_code": asset_code,
                    "asset_type": candidate["asset_type"],
                    "pool": pool,
                    "action": action,
                    "note": note,
                    "stage": candidate["stage"],
                    "score": candidate["score"],
                }
                self.manual_selections.append(record)
                return record
        raise ValueError("candidate not found")


def _asset_rows(asset_code: str, asset_type: str, name: str, days: int, base: float) -> list[dict]:
    rows = []
    for day in range(days):
        if day < 220:
            close = base + 12.0 - day * 0.065
        elif day < 285:
            close = base - 1.9 + (day - 220) * 0.005
        else:
            close = base - 1.5 + (day - 285) * 0.09
        if day == days - 1:
            close += 1.2
        rows.append(
            {
                "asset_code": asset_code,
                "asset_type": asset_type,
                "trade_date": f"d{day:03d}",
                "name": name,
                "list_date": "20250101",
                "market": "test",
                "open": close * 0.99,
                "high": close * 1.01,
                "low": close * 0.98,
                "close": close,
                "pre_close": close * 0.99,
                "pct_chg": 1.0,
                "vol": 1000000.0,
                "amount": 50000000.0,
                "adj_factor": 1.0,
                "turnover_rate": 2.0 if asset_type == "stock" else None,
                "turnover_rate_f": 2.0 if asset_type == "stock" else None,
                "total_mv": 1000000.0 if asset_type == "stock" else None,
                "circ_mv": 800000.0 if asset_type == "stock" else None,
                "limit_status": None,
            }
        )
    return rows


if __name__ == "__main__":
    unittest.main()
