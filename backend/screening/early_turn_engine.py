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

        close = _f(features, "close")
        ma5 = _f(features, "ma5")
        ma10 = _f(features, "ma10")
        ma20 = _f(features, "ma20")
        ma30 = _f(features, "ma30")
        ma60 = _f(features, "ma60")
        atr20 = _f(features, "atr20") or (close * 0.03)

        # ── A. Background & Base (背景与底分, Max 15) ───────────────────────
        tt = features.get("turn_type", "FIRST_TURN")
        bg_type = tt
        bg_score = 5.0
        if tt == "FIRST_TURN":
            bg_score = 15.0
        elif tt == "SECONDARY_TURN":
            bg_score = 12.0
        elif tt == "CONSOLIDATION_RESTART":
            bg_score = 10.0

        # ── B. MA Regime Transition (均线状态转换, Max 25) ───────────────────
        # 3-MA spread
        ma_vals = [ma5, ma10, ma20, ma30]
        valid_mas = [m for m in ma_vals if m > 0]
        if len(valid_mas) >= 3:
            sorted_mas = sorted(valid_mas)
            min_3_spread = min(
                sorted_mas[2] - sorted_mas[0],
                sorted_mas[3] - sorted_mas[1] if len(sorted_mas) >= 4 else 999.0
            )
        else:
            min_3_spread = 999.0
        min_3ma_spread_atr = min_3_spread / atr20 if atr20 > 0 else 9.9

        spread_5d = _f(features, "ma_spread_5d_ago", default=min_3_spread * 1.2)
        comp_ratio = min_3_spread / spread_5d if spread_5d > 0 else 1.0
        cross_pairs = int(_f(features, "cross_pair_count_10d"))

        score_transition = 0.0
        if min_3ma_spread_atr <= 0.51:
            score_transition += 15.0
        elif min_3ma_spread_atr <= 0.8:
            score_transition += 10.0
        elif min_3ma_spread_atr <= 1.2:
            score_transition += 5.0

        if comp_ratio < 0.8:
            score_transition += 5.0
        elif comp_ratio < 0.95:
            score_transition += 3.0

        if cross_pairs >= 3:
            score_transition += 5.0
        elif cross_pairs >= 2:
            score_transition += 3.0

        # chop penalty: if price crossed back and forth many times (using cross_event_count_10d)
        cross_events = int(_f(features, "cross_event_count_10d"))
        chop_penalty = 0.0
        if cross_events >= 8:
            chop_penalty = 6.0
        elif cross_events >= 4:
            chop_penalty = 3.0
        score_transition = max(0.0, score_transition - chop_penalty)
        score_transition = min(25.0, score_transition)

        # ── C. Price Retake (价格夺回成本区, Max 15) ───────────────────────────
        retake_cnt = int(_f(features, "retake_count"))
        score_retake = 0.0
        if retake_cnt == 4:
            score_retake = 15.0
        elif retake_cnt == 3:
            score_retake = 10.0
        elif retake_cnt == 2:
            score_retake = 5.0

        days_retake_3ma = int(_f(features, "days_retake_3ma"))
        if days_retake_3ma > 3:
            score_retake = max(0.0, score_retake - 5.0)

        # ── D. Directional Turn (方向性转向, Max 15) ──────────────────────────
        order_score = _f(features, "order_score")
        order_improvement = _f(features, "order_improvement")
        score_direction = 0.0
        if order_score >= 3.0:
            score_direction += 10.0
        elif order_score >= 2.0:
            score_direction += 5.0
        if order_improvement > 0:
            score_direction += 5.0
        score_direction = min(15.0, score_direction)

        # ── E. Freshness (新鲜度, Max 10) ──────────────────────────────────
        score_freshness = 1.0
        if days_retake_3ma <= 2:
            score_freshness = 10.0
        elif days_retake_3ma <= 5:
            score_freshness = 7.0
        elif days_retake_3ma <= 10:
            score_freshness = 4.0

        # ── F. Volume Confirmation (成交确认, Max 10) ─────────────────────────
        vol_ratio = _f(features, "volume_ratio", default=1.0)
        score_vol = 2.0
        if vol_ratio >= 1.5:
            score_vol = 10.0
        elif vol_ratio >= 1.1:
            score_vol = 6.0
        elif vol_ratio >= 0.8:
            score_vol = 4.0

        # ── G. Space & Extension (空间与过度延伸, Max 10) ──────────────────────
        extension_atr = (close - ma20) / atr20 if ma20 > 0 and atr20 > 0 else 0.0
        is_overextended = extension_atr > 2.0 or (close - ma20) / ma20 > 0.18 if ma20 > 0 else False
        dist_high_60 = _f(features, "dist_high_60")
        overhead_res = bool(features.get("overhead_resistance_flag"))

        score_space = 0.0
        if extension_atr <= 1.0:
            score_space += 5.0
        elif extension_atr <= 1.5:
            score_space += 3.0
        elif extension_atr <= 2.0:
            score_space += 1.0

        if dist_high_60 >= 0.08:
            score_space += 5.0
        elif dist_high_60 >= 0.04:
            score_space += 3.0
        elif not overhead_res:
            score_space += 2.0

        score_space = min(10.0, score_space)

        # ── 总分计算 (Total Score) ──────────────────────────────────────────
        total_score = (
            bg_score +
            score_transition +
            score_retake +
            score_direction +
            score_freshness +
            score_vol +
            score_space
        )
        total_score = round(min(100.0, total_score), 1)

        # 状态确定
        if is_overextended:
            state = "TOO_LATE"
        elif total_score >= 75.0 and min_3ma_spread_atr <= 0.8 and cross_pairs >= 2:
            state = "EARLY_TURN_STRICT"
        elif total_score >= 75.0:
            state = "EARLY_TURN"
        elif total_score >= 65.0 and min_3ma_spread_atr <= 1.0 and cross_pairs >= 1:
            state = "PRE_READY_STRICT"
        elif total_score >= 65.0:
            state = "PRE_READY"
        elif total_score >= 50.0:
            state = "WATCH"
        else:
            state = "NO_SIGNAL"

        # 原因分析列表 (Reasons)
        reasons = []
        if tt == "FIRST_TURN":
            reasons.append({"type": "INFO", "msg": "识别为首次底部转向 (FIRST_TURN)"})
        elif tt == "SECONDARY_TURN":
            reasons.append({"type": "INFO", "msg": "识别为二次转强突破 (SECONDARY_TURN)"})
        elif tt == "CONSOLIDATION_RESTART":
            reasons.append({"type": "INFO", "msg": "识别为整理后再启动 (CONSOLIDATION_RESTART)"})

        if min_3ma_spread_atr <= 0.51:
            reasons.append({"type": "BONUS", "msg": f"均线系统高度压缩 (离散度/ATR: {min_3ma_spread_atr:.2f})"})
        if cross_pairs >= 3:
            reasons.append({"type": "BONUS", "msg": f"发生 {cross_pairs} 组均线交叉结扎 (MA Knot)"})
        if chop_penalty > 0:
            reasons.append({"type": "WARN", "msg": f"检测到近期均线反复交叉缠绕，存在震荡杂噪 (扣分 {chop_penalty:.1f})"})
        if days_retake_3ma <= 2:
            reasons.append({"type": "BONUS", "msg": f"突破新鲜度极佳 (站上 3MA 第 {days_retake_3ma} 天)"})
        if overhead_res:
            reasons.append({"type": "WARN", "msg": f"当前价格上方 6% 内存在较强历史局部阻力位 (距离: {dist_high_60:.2%})"})
        if is_overextended:
            reasons.append({"type": "WARN", "msg": f"股价偏离均线团 {extension_atr:.1f} ATR，属于追高过度延伸"})

        # UI 兼容性映射 (将 V2 七大模块得分映射回原 V1 八大指标中，不破坏 UI 显示)
        score_detail = {
            "background": bg_score,
            "compression": round(score_transition * 0.6, 1),
            "knot": round(score_transition * 0.4, 1),
            "direction": round(score_direction * 0.6, 1),
            "slope": round(score_direction * 0.4, 1),
            "retake": score_retake,
            "extension": score_space,
            "bonus": round(score_freshness + score_vol, 1),
            # 原始技术指标字段
            "min_3ma_spread_atr": round(min_3ma_spread_atr, 2),
            "cross_pair_count_10d": cross_pairs,
            "order_score": order_score,
            "order_improvement": order_improvement,
            "up_slope_count": int(_f(features, "days_ma5_slope_pos")),  # 借用字段展示斜率转强天数
            "retake_count": retake_cnt,
            "fresh_retake": days_retake_3ma <= 2,
            "extension_atr": round(extension_atr, 2),
            # 新增 V2 调试细节
            "v2_details": {
                "turn_type": tt,
                "transition": score_transition,
                "retake": score_retake,
                "direction": score_direction,
                "freshness": score_freshness,
                "vol": score_vol,
                "space": score_space,
                "chop_penalty": chop_penalty,
                "overhead_resistance": overhead_res,
                "dist_high_60": dist_high_60
            }
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
