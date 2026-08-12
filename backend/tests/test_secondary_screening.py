from __future__ import annotations

import unittest
from typing import Any

from backend.screening.secondary_service import (
    SecondaryScreeningConfig,
    SecondaryScreeningService,
    STATUS_PASS,
    STATUS_FAIL,
)


class DummyStore:
    def __init__(self) -> None:
        self.created_runs: list[dict[str, Any]] = []
        self.finished_runs: list[dict[str, Any]] = []
        self.pool_candidates: list[dict[str, Any]] = []
        self.stage_snapshots: list[dict[str, Any]] = []
        self.stage_reasons: list[dict[str, Any]] = []
    def get_data_freshness_info(self) -> dict[str, Any]:
        return {"daily_trade_date": "20260806", "trade_dates_count": 500}

    def create_screening_run(self, run_id: str, trade_date: str, config_version: str, data_version: str, **kwargs: Any) -> None:
        self.created_runs.append({
            "run_id": run_id, "trade_date": trade_date, "config_version": config_version, "data_version": data_version
        })

    def finish_screening_run(self, run_id: str, status: str, summary: dict[str, Any] | None = None, error_message: str | None = None) -> None:
        self.finished_runs.append({"run_id": run_id, "status": status, "summary": summary, "error_message": error_message})

    def save_pool_candidates_v2(self, run_id: str, candidates: list[dict[str, Any]]) -> None:
        self.pool_candidates.extend(candidates)

    def save_stage_snapshots(self, snapshots: list[dict[str, Any]]) -> None:
        self.stage_snapshots.extend(snapshots)

    def save_stage_reasons(self, reasons: list[dict[str, Any]]) -> None:
        self.stage_reasons.extend(reasons)

    def save_factor_snapshots(self, snapshots: list[dict[str, Any]], factor_version: str) -> None:
        self.factor_snapshots.extend(snapshots)

    def load_industry_membership_for_date(self, trade_date: str, source_version: str, ts_codes: list[str] | None = None) -> dict[str, dict[str, Any]]:
        return {
            "000001.SZ": {"ts_code": "000001.SZ", "l2_code": "SW_BANK"},
            "000002.SZ": {"ts_code": "000002.SZ", "l2_code": "SW_REALESTATE"},
        }


class SecondaryScreeningServiceTests(unittest.TestCase):
    def test_l1_hard_filter_st_and_liquidity(self) -> None:
        store = DummyStore()
        config = SecondaryScreeningConfig(min_median_amount_20_cny=5e7, exclude_st=True)
        svc = SecondaryScreeningService(config=config, store=store)

        # 股票 1：ST 股票，应该触发 L1_ST_RISK
        # 股票 2：成交额低，应该触发 L1_LOW_LIQUIDITY
        l0_candidates = [
            {"asset_code": "000001.SZ", "asset_type": "stock", "primary_pool": "A", "stage": "PASS", "score": 80.0},
            {"asset_code": "000002.SZ", "asset_type": "stock", "primary_pool": "B", "stage": "PASS", "score": 75.0},
        ]
        feature_map = {
            "000001.SZ": {"name": "*ST平安", "history_days": 200, "amount_ma20": 1e8},
            "000002.SZ": {"name": "万科A", "history_days": 200, "amount_ma20": 1e7},  # 1000万 < 5000万
        }

        # Mock loader methods
        svc._load_l0_candidates = lambda td: l0_candidates
        svc._load_features = lambda td: feature_map

        summary = svc.run("20260806")

        self.assertEqual(summary["status"], "DONE")
        self.assertEqual(summary["l0_count"], 2)
        self.assertEqual(summary["l1_pass"], 0)
        self.assertEqual(summary["l1_fail"], 2)

        reasons = store.stage_reasons
        self.assertEqual(len(reasons), 2)
        reason_codes = {r["reason_code"] for r in reasons}
        self.assertIn("L1_ST_RISK", reason_codes)
        self.assertIn("L1_LOW_LIQUIDITY", reason_codes)


if __name__ == "__main__":
    unittest.main()
