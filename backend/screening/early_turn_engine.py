"""
A-Pre V2 / Early Turn 早期转强实验选股引擎

实现《A-PreV2_早期转强实验选股策略_开发说明_V1.0.docx》定义的均线状态迁移打分模型：
1. 特征组 A：均线压缩 (Compression)
2. 特征组 B：交叉网络 (MA Knot)
3. 特征组 C：方向性重排 (Direction & Reordering)
4. 特征组 D：斜率转向 (Slope Turn)
5. 特征组 E：夺回成本区 (Price Retake)
6. 特征组 F：位置不过度延伸 (Extension ATR)
7. 特征组 G：背景与辅助 Bonus (Higher Low / Volume Preheat)

全量计算基于 Point-in-Time 时间点无未来函数。
"""

from typing import Any
import math


def _f(d: dict[str, Any], key: str, default: float = 0.0) -> float:
    val = d.get(key)
    if val is None:
        return default
    try:
        f = float(val)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _b(d: dict[str, Any], key: str) -> bool:
    return bool(d.get(key))


class EarlyTurnEngine:
    """A-Pre V2 早期转强评分引擎"""

    def evaluate_stock(
        self,
        ts_code: str,
        trade_date: str,
        features: dict[str, Any],
    ) -> dict[str, Any]:
        """对单只股票的日线及技术特征计算 Early Turn 8 大模块分值与状态"""
        if not features:
            return {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "total_score": 0.0,
                "state": "NO_SIGNAL",
                "background_type": "UNKNOWN",
                "is_overextended": False,
                "features_json": {},
                "score_detail_json": {},
                "reasons_json": [{"code": "DATA_MISSING", "msg": "基础特征数据缺失"}],
            }

        close = _f(features, "close") or _f(features, "adj_close")
        ma5 = _f(features, "ma5")
        ma10 = _f(features, "ma10")
        ma20 = _f(features, "ma20")
        ma30 = _f(features, "ma30")
        ma60 = _f(features, "ma60")
        atr20 = _f(features, "atr20") or (close * 0.03)

        # ── 1. 背景分类 (Background Classifier) ────────────────────────────────
        bg_type = "UNKNOWN"
        bg_score = 5.0
        ma20_slope_10 = _f(features, "ma20_slope_10")
        close_vs_ma60 = (close - ma60) / ma60 if ma60 > 0 else 0.0

        if ma20_slope_10 < 0 and close_vs_ma60 < -0.05:
            bg_type = "REVERSAL_BASE"
            bg_score = 10.0
        elif close_vs_ma60 > 0.05 or _f(features, "ma60_slope_20") > 0:
            bg_type = "CONSOLIDATION_RESTART"
            bg_score = 10.0

        # ── 2. 特征组 A：均线压缩 (Compression, 满分 20) ────────────────────────
        ma_vals = [ma5, ma10, ma20, ma30]
        valid_mas = [m for m in ma_vals if m > 0]
        
        if len(valid_mas) >= 3:
            # 最小三根均线的离散度
            sorted_mas = sorted(valid_mas)
            min_3_spread = min(
                sorted_mas[2] - sorted_mas[0],
                sorted_mas[3] - sorted_mas[1] if len(sorted_mas) >= 4 else 999.0
            )
        else:
            min_3_spread = 999.0

        min_3ma_spread_atr = min_3_spread / atr20 if atr20 > 0 else 9.9
        spread_5d = _f(features, "ma_spread_5d_ago", default=min_3_spread * 1.2)
        spread_change_5d = min_3_spread / spread_5d if spread_5d > 0 else 1.0

        score_compression = 0.0
        if min_3ma_spread_atr <= 0.5:
            score_compression += 14.0
        elif min_3ma_spread_atr <= 0.8:
            score_compression += 8.0
        elif min_3ma_spread_atr <= 1.2:
            score_compression += 4.0

        if spread_change_5d < 0.8:
            score_compression += 6.0
        elif spread_change_5d < 0.95:
            score_compression += 3.0

        score_compression = min(20.0, score_compression)

        # ── 3. 特征组 B：交叉网络 (MA Knot, 满分 15) ─────────────────────────────
        cross_pair_count_10d = int(_f(features, "cross_pair_count_10d"))
        cross_event_count_10d = int(_f(features, "cross_event_count_10d"))

        score_knot = 0.0
        if cross_pair_count_10d >= 4:
            score_knot = 15.0
        elif cross_pair_count_10d == 3:
            score_knot = 10.0
        elif cross_pair_count_10d == 2:
            score_knot = 5.0

        # ── 4. 特征组 C：方向性重排 (Direction & Reordering, 满分 20) ────────────
        order_score = (
            (1.0 if ma5 > ma10 else 0.0) +
            (1.0 if ma5 > ma20 else 0.0) +
            (1.0 if ma10 > ma20 else 0.0) +
            (0.5 if ma20 > ma30 else 0.0)
        )
        order_score_5d = _f(features, "order_score_5d_ago", default=1.0)
        order_improvement = order_score - order_score_5d

        score_direction = 0.0
        if order_score >= 3.0:
            score_direction += 12.0
        elif order_score >= 2.0:
            score_direction += 6.0

        if order_improvement > 0:
            score_direction += 8.0
        elif order_improvement == 0 and order_score >= 2.5:
            score_direction += 4.0

        score_direction = min(20.0, score_direction)

        # ── 5. 特征组 D：均线斜率转向 (Slope Turn, 满分 15) ──────────────────────
        slope5 = _f(features, "slope5_3d") or (ma5 / _f(features, "ma5_3d_ago", ma5) - 1.0 if _f(features, "ma5_3d_ago") > 0 else 0.0)
        slope10 = _f(features, "slope10_5d") or (ma10 / _f(features, "ma10_5d_ago", ma10) - 1.0 if _f(features, "ma10_5d_ago") > 0 else 0.0)
        slope20 = _f(features, "slope20_5d") or (ma20 / _f(features, "ma20_5d_ago", ma20) - 1.0 if _f(features, "ma20_5d_ago") > 0 else 0.0)
        slope30 = _f(features, "slope30_5d") or (ma30 / _f(features, "ma30_5d_ago", ma30) - 1.0 if _f(features, "ma30_5d_ago") > 0 else 0.0)

        up_slope_count = sum([1 for s in (slope5, slope10, slope20, slope30) if s > 0])

        score_slope = 0.0
        if up_slope_count >= 3:
            score_slope = 15.0
        elif up_slope_count == 2:
            score_slope = 10.0
        elif up_slope_count == 1:
            score_slope = 5.0

        # ── 6. 特征组 E：夺回成本区 (Price Retake, 满分 10) ───────────────────────
        retake_count = sum([
            1 for m in (ma5, ma10, ma20, ma30) if m > 0 and close > m
        ])
        retake_3d_ago = int(_f(features, "retake_count_3d_ago", default=2))
        fresh_retake = retake_count >= 3 and retake_3d_ago <= 2

        score_retake = 0.0
        if retake_count >= 3:
            score_retake += 6.0
            if fresh_retake:
                score_retake += 4.0
        elif retake_count == 2:
            score_retake += 3.0

        score_retake = min(10.0, score_retake)

        # ── 7. 特征组 F：位置不过度延伸 (Extension ATR, 满分 5) ────────────────────
        center_ma = ma20 if ma20 > 0 else (ma10 if ma10 > 0 else close)
        extension_atr = (close - center_ma) / atr20 if atr20 > 0 else 0.0
        is_overextended = extension_atr > 2.0 or (close - ma20) / ma20 > 0.18 if ma20 > 0 else False

        score_extension = 0.0
        if 0 <= extension_atr <= 1.0:
            score_extension = 5.0
        elif 1.0 < extension_atr <= 1.5:
            score_extension = 3.0
        elif 1.5 < extension_atr <= 2.0:
            score_extension = 1.0

        # ── 8. 特征组 G：辅助/量能 Bonus (Bonus, 满分 5) ────────────────────────
        score_bonus = 0.0
        higher_low = _b(features, "higher_low")
        if higher_low:
            score_bonus += 3.0

        amount_preheat = _f(features, "amount_preheat", default=1.0)
        if 1.1 <= amount_preheat <= 1.6:
            score_bonus += 2.0

        score_bonus = min(5.0, score_bonus)

        # ── 9. 总分加总与状态决定 ──────────────────────────────────────────────
        total_score = (
            bg_score +
            score_compression +
            score_knot +
            score_direction +
            score_slope +
            score_retake +
            score_extension +
            score_bonus
        )
        total_score = round(min(100.0, total_score), 1)

        # 状态确定 (新增独立精准分类 EARLY_TURN_STRICT 和 PRE_READY_STRICT)
        if is_overextended:
            state = "TOO_LATE"
        elif total_score >= 75.0 and min_3ma_spread_atr <= 0.8 and cross_pair_count_10d >= 2:
            state = "EARLY_TURN_STRICT"
        elif total_score >= 75.0:
            state = "EARLY_TURN"
        elif total_score >= 65.0 and min_3ma_spread_atr <= 1.0 and cross_pair_count_10d >= 1:
            state = "PRE_READY_STRICT"
        elif total_score >= 65.0:
            state = "PRE_READY"
        elif total_score >= 50.0:
            state = "WATCH"
        else:
            state = "NO_SIGNAL"

        # 原因分析列表 (Reasons)
        reasons = []
        if score_compression >= 14:
            reasons.append({"type": "BONUS", "msg": f"均线高度压缩 (离散/ATR: {min_3ma_spread_atr:.2f})"})
        if cross_pair_count_10d >= 3:
            reasons.append({"type": "BONUS", "msg": f"发生 {cross_pair_count_10d} 组均线结扎交叉 (MA Knot)"})
        if order_improvement > 0:
            reasons.append({"type": "BONUS", "msg": f"交叉后形成了明显的向上次序重排 (order +{order_improvement:.1f})"})
        if fresh_retake:
            reasons.append({"type": "BONUS", "msg": "股价刚刚重新夺回 3 根以上短中均线 (Fresh Retake)"})
        if is_overextended:
            reasons.append({"type": "WARN", "msg": f"股价偏离均线团 {extension_atr:.1f} ATR，属于追高过度延伸"})
        if up_slope_count >= 3:
            reasons.append({"type": "BONUS", "msg": f"已有 {up_slope_count} 根均线斜率向上拐头"})

        score_detail = {
            "background": bg_score,
            "compression": score_compression,
            "knot": score_knot,
            "direction": score_direction,
            "slope": score_slope,
            "retake": score_retake,
            "extension": score_extension,
            "bonus": score_bonus,
            "min_3ma_spread_atr": round(min_3ma_spread_atr, 2),
            "cross_pair_count_10d": cross_pair_count_10d,
            "order_score": order_score,
            "order_improvement": order_improvement,
            "up_slope_count": up_slope_count,
            "retake_count": retake_count,
            "fresh_retake": fresh_retake,
            "extension_atr": round(extension_atr, 2),
        }

        return {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "total_score": total_score,
            "state": state,
            "background_type": bg_type,
            "selected": state in ("EARLY_TURN", "PRE_READY", "EARLY_TURN_STRICT", "PRE_READY_STRICT"),
            "is_overextended": is_overextended,
            "features_json": features,
            "score_detail_json": score_detail,
            "reasons_json": reasons,
        }
