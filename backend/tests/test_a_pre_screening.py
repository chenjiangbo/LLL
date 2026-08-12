from __future__ import annotations

import unittest
import numpy as np
import pandas as pd

from backend.screening.config import ScreeningConfig
from backend.screening.feature_engine import FeatureEngine
from backend.screening.rules import ScreeningRules


class APreScreeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ScreeningConfig(threshold_a_pre=55.0)
        self.rules = ScreeningRules(self.config)

    def test_feature_engine_a_pre_metrics(self) -> None:
        # 构造一条 300 天的行情，模拟长期下跌后跌速明显减慢并筑底的走势
        dates = [f"2025{i:04d}" for i in range(1, 301)]
        closes = []
        c = 100.0
        for i in range(300):
            if i < 200:
                c *= 0.995  # 前期快速下跌
            elif i < 280:
                c *= 0.999  # 跌速极大地减缓 (deceleration 高)
            else:
                c *= 1.001  # 短期微幅转强
            closes.append(c)

        df = pd.DataFrame(
            {
                "asset_code": "000001.SZ",
                "asset_type": "stock",
                "trade_date": dates,
                "open": closes,
                "high": [c * 1.01 for c in closes],
                "low": [c * 0.99 for c in closes],
                "close": closes,
                "pct_chg": [0.1] * 300,
                "vol": [10000] * 300,
                "amount": [50000000] * 300,
                "adj_factor": [1.0] * 300,
                "turnover_rate": [1.0] * 300,
                "history_days": list(range(1, 301)),
            }
        )

        engine = FeatureEngine(self.config)
        features_df = engine._build_asset_features(df)
        latest = features_df.iloc[-1]

        # 校验关键指标是否存在且算得合理
        self.assertIn("deceleration", latest)
        self.assertIn("low_ratio", latest)
        self.assertIn("atr_ratio", latest)
        self.assertIn("compression", latest)
        self.assertIn("position_250", latest)
        self.assertIn("distance_to_breakout", latest)

        # 前期跌了300天，250日高点回撤必定为负，且减速率高
        self.assertLess(latest["drawdown_from_250d_high"], -0.20)
        self.assertGreaterEqual(latest["deceleration"], 0.5)

    def test_rules_evaluate_a_pre_scoring_and_stage(self) -> None:
        # 手工构造符合 A-PRE-3 (临界启动) 的特征字典
        f = {
            "asset_code": "000001.SZ",
            "asset_type": "stock",
            "history_days": 300,
            "drawdown_from_250d_high": -0.40,  # 长期回撤40%
            "position_250": 0.20,             # 处于250日低区
            "ret_120": -0.15,                 # 120日处于负收益
            "slope_60": -0.003,
            "slope_20": 0.001,                # slope20转正
            "slope_10": 0.002,
            "deceleration": 1.0,              # 下跌减速率100%
            "low_ratio": 0.03,                # 出现抬高低点 (>0.02)
            "atr_ratio": 0.65,                # ATR收缩 (<0.70)
            "compression": 0.50,              # 区间压缩 (<0.55)
            "volume_asymmetry": 1.6,          # 上涨日成交额高
            "amount_ratio_5_20": 1.2,         # 温和放量
            "ma60_slope_improvement": 0.01,
            "distance_to_breakout": -0.04,     # 距离阻力位仅4% (接近突破)
        }

        res = self.rules.evaluate_a_pre(f)

        self.assertEqual(res.pool, "A-Pre")
        self.assertEqual(res.stage, "A-PRE-3")
        self.assertGreaterEqual(res.score, 75.0)
        self.assertIn("APRE_HIGHER_LOW", res.passed_rules)
        self.assertIn("APRE_NEAR_BREAKOUT", res.passed_rules)

    def test_rules_evaluate_a_pre_rejects_strong_uptrend(self) -> None:
        # 已暴涨股票 (ret_120 >= 0.10) 应该被 A-Pre 硬前提拒绝
        f = {
            "asset_code": "000002.SZ",
            "asset_type": "stock",
            "history_days": 300,
            "drawdown_from_250d_high": -0.30,
            "position_250": 0.30,
            "ret_120": 0.35,  # 暴涨的标的
        }

        res = self.rules.evaluate_a_pre(f)
        self.assertEqual(res.score, 0.0)
        self.assertIn("APRE_HARD_UPTREND_TOO_STRONG", res.failed_rules)


if __name__ == "__main__":
    unittest.main()
