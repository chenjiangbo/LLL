from __future__ import annotations

import unittest

from backend.market_review.ai_analysis import _analysis_input
from backend.market_review.analytics import OverviewAnalytics
from backend.market_review.data_quality import build_data_quality


class DataQualityTests(unittest.TestCase):
    def _rows(self) -> tuple[list[dict], list[dict]]:
        indices = [{"name": "沪深300", "date": "2026-08-03"}]
        industries = [{"name": "银行", "date": "2026-08-03"}]
        return indices, industries

    def test_intraday_snapshot_is_not_final(self) -> None:
        indices, industries = self._rows()
        result = build_data_quality(
            "20260803",
            {
                "captured_at": "2026-08-03T14:17:39+08:00",
                "capture_trade_date": "20260803",
                "snapshot_time": "14:17:39",
                "limit_down_count": 2,
            },
            {"captured_at": "2026-08-03T14:18:00+08:00", "capture_trade_date": "20260803"},
            indices,
            industries,
        )
        self.assertEqual(result["status"], "intraday")
        self.assertFalse(result["is_final"])

    def test_missing_limit_down_is_partial_not_zero(self) -> None:
        indices, industries = self._rows()
        result = build_data_quality(
            "20260803",
            {
                "captured_at": "2026-08-03T16:20:00+08:00",
                "capture_trade_date": "20260803",
                "snapshot_time": "15:00:00",
                "limit_down_count": None,
            },
            {"captured_at": "2026-08-03T16:20:00+08:00", "capture_trade_date": "20260803"},
            indices,
            industries,
        )
        self.assertEqual(result["status"], "partial")
        self.assertIn("market.sentiment.limit_down_count", result["missing_fields"])

    def test_capture_date_mismatch_is_error(self) -> None:
        indices, industries = self._rows()
        result = build_data_quality(
            "20260803",
            {
                "captured_at": "2026-08-04T16:20:00+08:00",
                "capture_trade_date": "20260804",
                "snapshot_time": "15:00:00",
                "limit_down_count": 1,
            },
            {"captured_at": "2026-08-03T16:20:00+08:00", "capture_trade_date": "20260803"},
            indices,
            industries,
        )
        self.assertEqual(result["status"], "error")


class AnalyticsContractTests(unittest.TestCase):
    @staticmethod
    def _stock_history() -> dict:
        history = []
        for day in range(60):
            history.append(
                {
                    "trade_date": f"d{day:02d}",
                    "daily": {
                        "rows": [
                            {"ts_code": "000001.SZ", "close": 10 + day, "pct_chg": 1, "amount": 10},
                            {"ts_code": "600000.SH", "close": 100 - day, "pct_chg": -1, "amount": 20},
                        ]
                    },
                    "adjustment": {
                        "rows": [
                            {"ts_code": "000001.SZ", "adj_factor": 1},
                            {"ts_code": "600000.SH", "adj_factor": 1},
                        ]
                    },
                }
            )
        return {"stock_history": history}

    def test_market_classification_uses_rules_and_evidence(self) -> None:
        rows = [
            {"id": "hs300", "returns": {"5w": 2.0}},
            {"id": "csi500", "returns": {"5w": -1.0}},
            {"id": "csi1000", "returns": {"5w": -3.0}},
            {"id": "chinext", "returns": {"5w": -4.0}},
            {"id": "star50", "returns": {"5w": -5.0}},
        ]
        result = OverviewAnalytics()._build_market_classification(
            rows, {"quadrant": "广泛风险释放", "rising_ratio": 0.3}
        )
        self.assertEqual(result["daily_state"], "广泛风险释放")
        self.assertEqual(result["size_style"], "大盘占优")
        self.assertEqual(result["growth_style"], "成长科技承压")
        self.assertEqual(result["risk_appetite"], "风险偏好收缩")
        self.assertGreaterEqual(len(result["evidence"]), 2)

    def test_constituent_attribution_uses_weight_times_return(self) -> None:
        analytics = OverviewAnalytics()
        data = {
            "stock_daily": {
                "rows": [
                    {"ts_code": "000001.SZ", "pct_chg": 2.0},
                    {"ts_code": "600000.SH", "pct_chg": -1.0},
                ]
            },
            "weights": {
                "hs300": {
                    "effective_date": "20260803",
                    "source": "test.weights",
                    "rows": [
                        {"code": "000001", "name": "甲", "weight_pct": 60.0},
                        {"code": "600000", "name": "乙", "weight_pct": 40.0},
                    ],
                }
            },
            "industry_map": {
                "rows": [
                    {"code": "000001", "industry": "银行"},
                    {"code": "600000", "industry": "银行"},
                ]
            },
        }
        result = analytics._build_attribution("hs300", 0.8, data)
        self.assertTrue(result["available"])
        self.assertAlmostEqual(result["estimated_return_pct"], 0.8)
        self.assertAlmostEqual(result["covered_weight_pct"], 100.0)
        self.assertEqual(result["top_positive_contributors"][0]["name"], "甲")
        self.assertEqual(result["top_negative_contributors"][0]["name"], "乙")
        self.assertEqual(result["direction"], "up")
        self.assertEqual(result["key_constituents"][0]["name"], "甲")
        self.assertEqual(result["key_constituents"][0]["industry"], "银行")

    def test_breadth_quadrant_uses_daily_index_return(self) -> None:
        rows = [
            {"returns": {"1d": -1.0, "1w": 5.0}},
            {"returns": {"1d": -2.0, "1w": 4.0}},
        ]
        breadth = {
            "trade_date": "20260803",
            "snapshot_time": "15:00:00",
            "stock_count": 2,
            "rising_count": 2,
            "falling_count": 0,
            "flat_count": 0,
            "rising_ratio": 1.0,
            "falling_ratio": 0.0,
            "total_amount": 100.0,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "limit_down_empty_with_no_columns": False,
        }
        result = OverviewAnalytics()._build_breadth_block(
            rows, breadth, [], self._stock_history()
        )
        self.assertEqual(result["quadrant"], "中小盘活跃或权重拖累")
        self.assertEqual(result["five_index_equal_weight_daily_return"], -1.5)
        self.assertEqual(result["technical"]["new_high_20_count"], 1)
        self.assertEqual(result["technical"]["new_low_20_count"], 1)
        self.assertEqual(result["technical"]["above_ma60_ratio"], 0.5)

    def test_ai_input_has_quality_and_no_pool_section(self) -> None:
        report = {
            "trade_date": "20260803",
            "data_quality": {
                "status": "partial",
                "message": "缺失",
                "snapshot_time": "14:17:39",
                "captured_at": None,
                "industry_taxonomy": "同花顺行业板块",
                "missing_fields": ["market.sentiment.limit_down_count"],
            },
            "data_sources": {},
            "breadth": {
                "total_amount": 1,
                "history": {},
                "rising_count": 1,
                "falling_count": 1,
                "flat_count": 0,
                "rising_ratio": 0.5,
                "five_index_equal_weight_daily_return": 0,
                "quadrant": "表现分化",
                "technical": {
                    "above_ma20_count": 1,
                    "above_ma20_ratio": 0.5,
                    "above_ma60_count": 1,
                    "above_ma60_ratio": 0.5,
                    "new_high_20_count": 1,
                    "new_high_20_ratio": 0.5,
                    "new_low_20_count": 1,
                    "new_low_20_ratio": 0.5,
                },
                "limit_up_count": 1,
                "limit_down_count": None,
            },
            "core_conclusion": {"changes_from_previous_review": []},
            "market_classification": {
                "daily_state": "表现分化",
                "size_style": "大中小盘相对均衡",
                "growth_style": "成长与宽基相对均衡",
                "risk_appetite": "风险偏好信号混合",
                "evidence": [],
                "conflicting_evidence": [],
                "period": "5w_with_1d_breadth",
            },
            "indices": [],
            "industries": [],
        }
        payload = _analysis_input(report, "daily")
        self.assertEqual(payload["meta"]["data_status"], "partial")
        self.assertIsNone(payload["market"]["sentiment"]["limit_down_count"])
        self.assertNotIn("pool_environment", str(payload))


if __name__ == "__main__":
    unittest.main()
