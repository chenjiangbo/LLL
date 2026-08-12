from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.screening.config import ScreeningConfig


POOL_ORDER = {
    "A3": 0,
    "A2": 1,
    "A1": 2,
    "A-PRE-3": 0,
    "A-PRE-2": 1,
    "A-PRE-1": 2,
    "B3": 0,
    "B2": 1,
    "B1": 2,
    "C3": 0,
    "C2": 1,
    "C1": 2,
}


@dataclass(frozen=True)
class PoolResult:
    pool: str
    stage: str
    score: float
    reasons: list[str]
    score_detail: dict[str, Any]
    passed_rules: list[str]
    failed_rules: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "pool": self.pool,
            "stage": self.stage,
            "score": round(self.score, 2),
            "reasons": self.reasons,
            "score_detail": self.score_detail,
            "passed_rules": self.passed_rules,
            "failed_rules": self.failed_rules,
        }


@dataclass
class ScreeningRules:
    config: ScreeningConfig

    def passes_common_filter(self, f: dict[str, Any]) -> tuple[bool, list[str]]:
        risks: list[str] = []
        name = str(f.get("name") or "")
        asset_type = f["asset_type"]
        if self.config.exclude_st and asset_type == "stock" and "ST" in name.upper():
            return False, ["ST股票已按配置排除"]
        min_days = self.config.min_listing_days_stock if asset_type == "stock" else self.config.min_listing_days_etf
        if _num(f, "history_days") < min_days:
            return False, [f"交易历史不足{min_days}日"]
        if _num(f, "coverage_120d") < self.config.min_coverage_120d:
            return False, ["近120日行情覆盖不足"]
        min_amount = self.config.min_amount_ma20_stock if asset_type == "stock" else self.config.min_amount_ma20_etf
        if _num(f, "amount_ma20") < min_amount:
            return False, ["20日平均成交额低于最低门槛"]
        if asset_type == "stock" and str(f.get("limit_status") or "").upper() == "U":
            risks.append("今日涨停")
        return True, risks

    def evaluate(self, f: dict[str, Any], pools: set[str] | None = None) -> tuple[list[PoolResult], list[str]]:
        passed, risks = self.passes_common_filter(f)
        if not passed:
            return [], risks
        risks.extend(_risk_labels(f))
        selected = pools or {"A-Pre", "A", "B", "C"}
        results = []
        if "A-Pre" in selected or "APRE" in selected:
            results.append(self.evaluate_a_pre(f))
        if "A" in selected:
            results.append(self.evaluate_a(f))
        if "B" in selected:
            results.append(self.evaluate_b(f))
        if "C" in selected:
            results.append(self.evaluate_c(f))
        thresholds = {
            "A-Pre": self.config.threshold_a_pre,
            "APRE": self.config.threshold_a_pre,
            "A": self.config.threshold_a,
            "B": self.config.threshold_b,
            "C": self.config.threshold_c,
        }
        return [item for item in results if item.score >= thresholds.get(item.pool, 60.0)], risks

    def evaluate_a_pre(self, f: dict[str, Any]) -> PoolResult:
        reasons: list[str] = []
        passed: list[str] = []
        failed: list[str] = []

        min_days = self.config.min_listing_days_a_pre_stock if f.get("asset_type") == "stock" else self.config.min_listing_days_a_pre_etf
        if _num(f, "history_days") < min_days:
            failed.append("APRE_HARD_HISTORY_TOO_SHORT")
            return _empty_result("A-Pre", "A-PRE-1", failed)

        drawdown_250 = _num(f, "drawdown_from_250d_high")
        position_250 = _num(f, "position_250")
        ret_120 = _num(f, "ret_120")

        # 核心硬前提：至少经历过长期弱势（近250日高点回撤>=25% 或 价格在过去1年下半区），且不能是已经爆发大涨的极度牛股(ret_120 < +10%)
        if not (drawdown_250 <= -0.25 or position_250 <= 0.40):
            failed.append("APRE_HARD_NOT_WEAK_ENOUGH")
            return _empty_result("A-Pre", "A-PRE-1", failed)
        if ret_120 >= 0.10:
            failed.append("APRE_HARD_UPTREND_TOO_STRONG")
            return _empty_result("A-Pre", "A-PRE-1", failed)

        score_detail: dict[str, float] = {}

        # 1. 长期弱势背景 (15分)
        bg_score = 0.0
        if drawdown_250 <= -0.35:
            bg_score += 10.0
            passed.append("APRE_DRAWDOWN_DEEP")
        elif drawdown_250 <= -0.25:
            bg_score += 7.0
            passed.append("APRE_DRAWDOWN_MODERATE")

        if position_250 <= 0.30:
            bg_score += 5.0
            passed.append("APRE_POSITION_LOW")
        elif position_250 <= 0.40:
            bg_score += 3.0
            passed.append("APRE_POSITION_MID_LOW")
        score_detail["background_score"] = bg_score

        # 2. 下跌减速 (25分)
        slope_60 = _num(f, "slope_60")
        slope_20 = _num(f, "slope_20")
        slope_10 = _num(f, "slope_10")
        decel = _num(f, "deceleration")

        decel_score = 0.0
        if slope_60 < 0:
            if decel >= 0.75:
                decel_score += 12.0
                passed.append("APRE_DECEL_STRONG")
            elif decel >= 0.50:
                decel_score += 8.0
                passed.append("APRE_DECEL_MODERATE")
        if slope_20 >= 0:
            decel_score += 8.0
            passed.append("APRE_SLOPE20_POSITIVE")
        if slope_10 > slope_20:
            decel_score += 5.0
            passed.append("APRE_SLOPE10_ACCELERATING")
        score_detail["deceleration_score"] = decel_score

        # 3. 底部结构 (20分)
        low_ratio = _num(f, "low_ratio")
        bottom_score = 0.0
        if low_ratio > 0.02:
            bottom_score += 20.0
            passed.append("APRE_HIGHER_LOW")
            reasons.append("近期低点高于此前低点，形成抬高底部")
        elif -0.02 <= low_ratio <= 0.02:
            bottom_score += 12.0
            passed.append("APRE_DOUBLE_BOTTOM")
            reasons.append("近期低点与前低基本持平，形成近似双底")
        elif -0.05 <= low_ratio < -0.02:
            bottom_score += 5.0
            passed.append("APRE_SLOW_NEW_LOW")
        score_detail["bottom_structure_score"] = bottom_score

        # 4. 波动/卖压收缩 (15分)
        atr_ratio = _num(f, "atr_ratio")
        compression = _num(f, "compression")
        vol_score = 0.0
        if atr_ratio > 0 and atr_ratio < 0.70:
            vol_score += 8.0
            passed.append("APRE_ATR_COMPACT_DEEP")
        elif atr_ratio > 0 and atr_ratio < 0.85:
            vol_score += 5.0
            passed.append("APRE_ATR_COMPACT_MODERATE")

        if compression > 0 and compression < 0.55:
            vol_score += 7.0
            passed.append("APRE_RANGE_COMPRESSION_STRONG")
        elif compression > 0 and compression < 0.70:
            vol_score += 4.0
            passed.append("APRE_RANGE_COMPRESSION_MODERATE")
        score_detail["volatility_contraction_score"] = vol_score

        # 5. 相对强度与成交结构 (15分)
        vol_asym = _num(f, "volume_asymmetry")
        amt_ratio_5_20 = _num(f, "amount_ratio_5_20")
        ma60_slope_imp = _num(f, "ma60_slope_improvement")
        rs_score = 0.0

        if vol_asym >= 1.5:
            rs_score += 5.0
            passed.append("APRE_VOL_ASYM_STRONG")
        elif vol_asym >= 1.2:
            rs_score += 3.0
            passed.append("APRE_VOL_ASYM_MODERATE")

        if 1.0 <= amt_ratio_5_20 <= 1.5:
            rs_score += 5.0
            passed.append("APRE_VOLUME_MEMBER_INCREASE")
        elif amt_ratio_5_20 > 1.5:
            rs_score += 3.0

        if ma60_slope_imp > 0:
            rs_score += 5.0
            passed.append("APRE_RS_IMPROVING")
        score_detail["rs_and_volume_score"] = rs_score

        # 6. 临近启动 (10分)
        dist_break = _num(f, "distance_to_breakout")
        break_score = 0.0
        if -0.08 <= dist_break <= 0.0:
            break_score += 10.0
            passed.append("APRE_NEAR_BREAKOUT")
            reasons.append("价格紧临近期阻力位(距突破在8%以内)")
        elif -0.15 <= dist_break < -0.08:
            break_score += 5.0
            passed.append("APRE_APPROACHING_BREAKOUT")
        elif dist_break > 0.0:
            # 已经突破前高，扣10分防止抢占正式 A 池
            break_score -= 10.0
            failed.append("APRE_ALREADY_BROKEN_OUT")
        score_detail["breakout_proximity_score"] = break_score

        total_score = bg_score + decel_score + bottom_score + vol_score + rs_score + break_score

        # 三级阶段判定
        if total_score >= 75.0:
            stage = "A-PRE-3"
            reasons.append("A-Pre预备池阶段：PRE-3(临界启动)")
        elif total_score >= 65.0:
            stage = "A-PRE-2"
            reasons.append("A-Pre预备池阶段：PRE-2(底部形成)")
        else:
            stage = "A-PRE-1"
            reasons.append("A-Pre预备池阶段：PRE-1(下跌衰竭)")

        return PoolResult(
            pool="A-Pre",
            stage=stage,
            score=total_score,
            reasons=reasons,
            score_detail=score_detail,
            passed_rules=passed,
            failed_rules=failed,
        )

    def evaluate_a(self, f: dict[str, Any]) -> PoolResult:
        reasons: list[str] = []
        passed: list[str] = []
        failed: list[str] = []

        min_days = self.config.min_listing_days_a_stock if f.get("asset_type") == "stock" else self.config.min_listing_days_a_etf
        if _num(f, "history_days") < min_days:
            failed.append("A_HARD_HISTORY_TOO_SHORT")
            return _empty_result("A", "A1", failed)

        decline_score = 0.0
        decline_hits = 0
        if _num(f, "ret_250") <= -0.30:
            decline_score += 10
            decline_hits += 1
            passed.append("A-D1_STRONG")
            reasons.append(_pct_reason("250日收益显著为负", f, "ret_250"))
        elif _num(f, "ret_250") <= -0.15:
            decline_score += 7
            decline_hits += 1
            passed.append("A-D1")
            reasons.append(_pct_reason("250日收益为负", f, "ret_250"))
        else:
            failed.append("A-D1_RET250_NOT_WEAK")

        if _num(f, "max_drawdown_250") <= -0.40:
            decline_score += 8
            decline_hits += 1
            passed.append("A-D2_STRONG")
            reasons.append(_pct_reason("250日内最大回撤明显", f, "max_drawdown_250"))
        elif _num(f, "max_drawdown_250") <= -0.30:
            decline_score += 6
            decline_hits += 1
            passed.append("A-D2")
            reasons.append(_pct_reason("250日内最大回撤", f, "max_drawdown_250"))
        else:
            failed.append("A-D2_DRAWDOWN_NOT_ENOUGH")

        if _num(f, "ma120_slope_60") < -0.03:
            decline_score += 6
            decline_hits += 1
            passed.append("A-D3")
            reasons.append(_pct_reason("MA120过去60日明显向下", f, "ma120_slope_60"))
        else:
            failed.append("A-D3_MA120_NOT_DECLINING")

        if _num(f, "ma60") < _num(f, "ma120") or _num(f, "ma120") < _num(f, "ma250"):
            decline_score += 4
            decline_hits += 1
            passed.append("A-D4")
            reasons.append("长期均线仍呈空头倾向")
        else:
            failed.append("A-D4_MA_STRUCTURE_NOT_BEARISH")

        if bool(f.get("lower_high")) and bool(f.get("lower_low")):
            decline_score += 4
            decline_hits += 1
            passed.append("A-D5")
            reasons.append("已确认Swing高点和低点仍呈下降结构")

        if decline_score < self.config.a_min_downtrend_score or decline_hits < 2:
            failed.append("A_HARD_DOWNTREND_SCORE_TOO_LOW")
            return _empty_result(
                "A",
                "A1",
                failed,
                {
                    "long_term_decline": round(decline_score, 2),
                    "weakening": 0,
                    "turning": 0,
                    "position": 0,
                    "total": round(decline_score, 2),
                },
                passed,
                reasons[:6],
            )

        weakening_score = 0.0
        weakening_hits = 0
        if _num(f, "distance_from_low_60") > 0.08:
            weakening_score += 6
            weakening_hits += 1
            passed.append("A-S1")
            reasons.append(_pct_reason("当前高于60日低点", f, "distance_from_low_60"))
        if _num(f, "ma20_slope_10") >= 0:
            weakening_score += 5
            weakening_hits += 1
            passed.append("A-S2")
            reasons.append(_pct_reason("MA20走平或上行", f, "ma20_slope_10"))
        if _num(f, "ma60_slope_improvement") > 0:
            weakening_score += 5
            weakening_hits += 1
            passed.append("A-S3")
            reasons.append(_pct_reason("MA60下降速度改善", f, "ma60_slope_improvement"))
        if 0 < _num(f, "volatility_contract") < 0.9:
            weakening_score += 4
            weakening_hits += 1
            passed.append("A-S4")
            reasons.append(_pct_reason("近期波动收缩至前段", f, "volatility_contract", ratio=True))
        if bool(f.get("higher_low")):
            weakening_score += 5
            weakening_hits += 1
            passed.append("A-S5")
            reasons.append("已确认Swing Low抬高")

        if weakening_hits < 2:
            failed.append("A_HARD_WEAKENING_EVIDENCE_TOO_FEW")
            return _empty_result(
                "A",
                "A1",
                failed,
                {
                    "long_term_decline": round(decline_score, 2),
                    "weakening": round(weakening_score, 2),
                    "turning": 0,
                    "position": 0,
                    "total": round(decline_score + weakening_score, 2),
                },
                passed,
                reasons[:6],
            )

        turning_score = 0.0
        turning_hits = 0
        if _num(f, "adj_close") > _num(f, "ma20"):
            turning_score += 5
            turning_hits += 1
            passed.append("A-T1")
            reasons.append("收盘价站上MA20")
        if _num(f, "adj_close") > _num(f, "ma60"):
            turning_score += 5
            turning_hits += 1
            passed.append("A-T2")
            reasons.append("收盘价站上MA60")
        if _num(f, "ma20_slope_10") > 0:
            turning_score += 5
            turning_hits += 1
            passed.append("A-T3")
            reasons.append("MA20斜率转正")
        if _num(f, "adj_close") > _num(f, "prev_high_20"):
            turning_score += 5
            turning_hits += 1
            passed.append("A-T4")
            reasons.append("收盘突破前20日高点")
        if _num(f, "adj_close") > _num(f, "prev_high_60"):
            turning_score += 7
            turning_hits += 1
            passed.append("A-T5")
            reasons.append("收盘突破前60日高点")
        if bool(f.get("higher_low")) and bool(f.get("break_last_swing_high")):
            turning_score += 3
            turning_hits += 1
            passed.append("A-T6")
            reasons.append("Higher Low后突破已确认Swing High")

        position_score = max(0.0, 15.0 - _overheat_penalty(f))
        score_detail = {
            "long_term_decline": round(min(decline_score, 30), 2),
            "weakening": round(min(weakening_score, 25), 2),
            "turning": round(min(turning_score, 30), 2),
            "position": round(position_score, 2),
        }
        total = min(sum(score_detail.values()), 100.0)
        score_detail["total"] = round(total, 2)

        stage = "A1"
        if turning_hits >= 2 and _num(f, "adj_close") > _num(f, "ma20") and (
            _num(f, "adj_close") > _num(f, "ma60")
            or _num(f, "adj_close") > _num(f, "prev_high_20")
            or _num(f, "ma20_slope_10") > 0.02
        ):
            stage = "A2"
        if bool(f.get("higher_low")) and _num(f, "ma20_slope_10") > 0 and (
            bool(f.get("break_last_swing_high")) or _num(f, "adj_close") > _num(f, "prev_high_60")
        ):
            stage = "A3"

        return PoolResult("A", stage, total, reasons[:8], score_detail, passed, failed)

    def evaluate_b(self, f: dict[str, Any]) -> PoolResult:
        reasons: list[str] = []
        passed: list[str] = []
        failed: list[str] = []

        min_days = self.config.min_listing_days_b_stock if f.get("asset_type") == "stock" else self.config.min_listing_days_b_etf
        if _num(f, "history_days") < min_days:
            failed.append("B_HARD_HISTORY_TOO_SHORT")
            return _empty_result("B", "B1", failed)

        uptrend_score = 0.0
        uptrend_hits = 0
        if _num(f, "ma60_slope_20") > 0:
            uptrend_score += 10
            uptrend_hits += 1
            passed.append("B-U1")
            reasons.append(_pct_reason("MA60过去20日上行", f, "ma60_slope_20"))
        else:
            failed.append("B-U1_MA60_NOT_UP")
        if _num(f, "ma120_slope_20") >= 0:
            uptrend_score += 9
            uptrend_hits += 1
            passed.append("B-U2_STRONG")
            reasons.append(_pct_reason("MA120过去20日不向下", f, "ma120_slope_20"))
        elif _num(f, "ma120_slope_20") >= -0.01:
            uptrend_score += 7
            uptrend_hits += 1
            passed.append("B-U2")
            reasons.append(_pct_reason("MA120过去20日基本不向下", f, "ma120_slope_20"))
        else:
            failed.append("B-U2_MA120_WEAK")
        if _num(f, "ret_120") > 0.20:
            uptrend_score += 9
            uptrend_hits += 1
            passed.append("B-U3_STRONG")
            reasons.append(_pct_reason("120日收益明显为正", f, "ret_120"))
        elif _num(f, "ret_120") > 0.10:
            uptrend_score += 7
            uptrend_hits += 1
            passed.append("B-U3")
            reasons.append(_pct_reason("120日收益为正", f, "ret_120"))
        else:
            failed.append("B-U3_RET120_NOT_STRONG")
        if _num(f, "ma20") > _num(f, "ma60") > _num(f, "ma120"):
            uptrend_score += 5
            uptrend_hits += 1
            passed.append("B-U4")
            reasons.append("MA20、MA60、MA120呈多头倾向")
        if bool(f.get("higher_high")) and bool(f.get("higher_low")):
            uptrend_score += 6
            uptrend_hits += 1
            passed.append("B-U5")
            reasons.append("已确认Swing高点和低点抬高")

        if uptrend_score < self.config.b_min_uptrend_score or uptrend_hits < 2:
            failed.append("B_HARD_UPTREND_SCORE_TOO_LOW")
            return _empty_result(
                "B",
                "B1",
                failed,
                {"uptrend": round(uptrend_score, 2), "pullback_health": 0, "stabilize": 0, "turning": 0, "total": round(uptrend_score, 2)},
                passed,
                reasons[:6],
            )

        pullback_score = 0.0
        pullback_hits = 0
        pullback_pct = _num(f, "pullback_pct_120")
        min_pullback = self.config.b_pullback_pct_stock_min if f.get("asset_type") == "stock" else self.config.b_pullback_pct_etf_min
        max_pullback = self.config.b_pullback_pct_stock_max if f.get("asset_type") == "stock" else self.config.b_pullback_pct_etf_max
        if max_pullback <= pullback_pct <= min_pullback:
            pullback_score += 10
            pullback_hits += 1
            passed.append("B-PB1")
            reasons.append(_pct_reason("从120日阶段高点发生合理回撤", f, "pullback_pct_120"))
        else:
            failed.append("B-PB1_PULLBACK_RANGE_INVALID")
        atr_pct = _num(f, "atr_pct")
        pullback_atr = abs(pullback_pct) / atr_pct if atr_pct > 0 else 0.0
        if pullback_atr >= self.config.b_pullback_atr_min:
            pullback_score += 6
            pullback_hits += 1
            passed.append("B-PB2")
            reasons.append(f"回撤达到{pullback_atr:.1f}倍ATR")
        else:
            failed.append("B-PB2_PULLBACK_ATR_TOO_SMALL")
        if _num(f, "pullback_peak_age_120") >= self.config.b_pullback_peak_min_age:
            pullback_score += 4
            pullback_hits += 1
            passed.append("B-PB3")
            reasons.append(f"阶段高点已过去{_num(f, 'pullback_peak_age_120'):.0f}个交易日")
        else:
            failed.append("B-PB3_PEAK_TOO_RECENT")
        if 0 < _num(f, "pullback_peak_age_120") <= self.config.b_pullback_days_max:
            pullback_score += 3
            passed.append("B-PB4")
        else:
            failed.append("B-PB4_PULLBACK_TOO_LONG")
        if _num(f, "adj_close") > _num(f, "ma120"):
            pullback_score += 4
            pullback_hits += 1
            passed.append("B-P1")
            reasons.append("当前仍高于MA120")
        break_swing_low_pct = _num(f, "break_swing_low_pct")
        swing_tolerance = -self.config.b_break_swing_low_atr_tolerance * atr_pct
        if break_swing_low_pct >= swing_tolerance:
            pullback_score += 5
            pullback_hits += 1
            passed.append("B-P3")
            reasons.append("调整未有效跌破前一重要Swing Low")
        else:
            failed.append("B-P3_BROKE_PREVIOUS_SWING_LOW")
        if _num(f, "volume_ratio_5_20") < 0.9:
            pullback_score += 5
            pullback_hits += 1
            passed.append("B-P5")
            reasons.append("调整期短期成交量低于20日均量")

        if pullback_score < self.config.b_min_pullback_score or pullback_hits < 2:
            failed.append("B_HARD_PULLBACK_HEALTH_TOO_LOW")
            total = uptrend_score + pullback_score
            return _empty_result(
                "B",
                "B1",
                failed,
                {"uptrend": round(uptrend_score, 2), "pullback_health": round(pullback_score, 2), "stabilize": 0, "turning": 0, "total": round(total, 2)},
                passed,
                reasons[:6],
            )

        stabilize_score = 0.0
        stabilize_hits = 0
        if bool(f.get("low_5_not_falling")):
            stabilize_score += 5
            stabilize_hits += 1
            passed.append("B-S1")
            reasons.append("最近5日低点未继续明显下移")
        if bool(f.get("higher_low")):
            stabilize_score += 5
            stabilize_hits += 1
            passed.append("B-S2")
            reasons.append("调整中出现Higher Low")
        if _num(f, "adj_close") > _num(f, "ma10"):
            stabilize_score += 4
            stabilize_hits += 1
            passed.append("B-S3")
            reasons.append("收盘价重新站上MA10")
        if _num(f, "adj_close") > _num(f, "ma20"):
            stabilize_score += 4
            stabilize_hits += 1
            passed.append("B-S4")
            reasons.append("收盘价重新站上MA20")
        if _num(f, "ma20_slope_10") > 0:
            stabilize_score += 4
            stabilize_hits += 1
            passed.append("B-S5")
            reasons.append("MA20走平或向上")

        turning_score = 0.0
        turning_hits = 0
        if bool(f.get("break_5")):
            turning_score += 4
            turning_hits += 1
            passed.append("B-T1")
            reasons.append("收盘突破最近5日高点")
        if bool(f.get("break_10")):
            turning_score += 5
            turning_hits += 1
            passed.append("B-T2")
            reasons.append("收盘突破最近10日高点")
        if bool(f.get("break_last_swing_high")):
            turning_score += 4
            turning_hits += 1
            passed.append("B-T3")
            reasons.append("突破已确认调整Swing High")
        if _num(f, "today_volume_ratio_20") > 1.2:
            turning_score += 2
            turning_hits += 1
            passed.append("B-T4_STRONG")
            reasons.append(_pct_reason("突破日成交量恢复", f, "today_volume_ratio_20", ratio=True))
        elif _num(f, "today_volume_ratio_20") > 1:
            turning_score += 1
            passed.append("B-T4")

        score_detail = {
            "uptrend": round(min(uptrend_score, 35), 2),
            "pullback_health": round(min(pullback_score, 30), 2),
            "stabilize": round(min(stabilize_score, 20), 2),
            "turning": round(min(turning_score, 15), 2),
        }
        total = max(0.0, min(sum(score_detail.values()) - _overheat_penalty(f), 100.0))
        score_detail["total"] = round(total, 2)
        stage = "B1"
        if stabilize_hits >= self.config.b_stage_b2_min_stabilize_hits:
            stage = "B2"
        if stage == "B2" and turning_hits >= self.config.b_stage_b3_min_breakout_hits:
            stage = "B3"
        return PoolResult("B", stage, total, reasons[:8], score_detail, passed, failed)

    def evaluate_c(self, f: dict[str, Any]) -> PoolResult:
        reasons: list[str] = []
        passed: list[str] = []
        failed: list[str] = []

        min_days = self.config.min_listing_days_c_stock if f.get("asset_type") == "stock" else self.config.min_listing_days_c_etf
        if _num(f, "history_days") < min_days:
            failed.append("C_HARD_HISTORY_TOO_SHORT")
            return _empty_result("C", "C1", failed)

        if self.config.c_exclude_if_break_prev_high60 and _num(f, "adj_close") > _num(f, "prev_high_60"):
            failed.append("C_HARD_BROKE_60D_HIGH_MORE_LIKE_A")
            return _empty_result("C", "C1", failed)
        if self.config.c_exclude_if_ma20_above_ma60 and _num(f, "ma20") > _num(f, "ma60"):
            failed.append("C_HARD_MA20_ABOVE_MA60_MORE_LIKE_A")
            return _empty_result("C", "C1", failed)
        if self.config.c_exclude_if_higher_low_and_break_swing_high and bool(f.get("higher_low")) and bool(f.get("break_last_swing_high")):
            failed.append("C_HARD_STRUCTURE_REVERSAL_MORE_LIKE_A")
            return _empty_result("C", "C1", failed)

        downtrend_score = 0.0
        downtrend_hits = 0
        if _num(f, "adj_close") < _num(f, "ma120"):
            downtrend_score += 7
            downtrend_hits += 1
            passed.append("C-D1")
            reasons.append("收盘仍低于MA120")
        else:
            failed.append("C-D1_CLOSE_NOT_BELOW_MA120")
        if _num(f, "ma120_slope_20") < 0:
            downtrend_score += 7
            downtrend_hits += 1
            passed.append("C-D2")
            reasons.append(_pct_reason("MA120仍向下", f, "ma120_slope_20"))
        else:
            failed.append("C-D2_MA120_NOT_DOWN")
        if _num(f, "ma60") < _num(f, "ma120"):
            downtrend_score += 6
            downtrend_hits += 1
            passed.append("C-D3")
            reasons.append("MA60仍低于MA120")
        if _num(f, "ret_120") < 0:
            downtrend_score += 5
            downtrend_hits += 1
            passed.append("C-D4")
            reasons.append(_pct_reason("120日收益仍为负", f, "ret_120"))
        if bool(f.get("lower_high")) or bool(f.get("lower_low")):
            downtrend_score += 5
            downtrend_hits += 1
            passed.append("C-D5")
            reasons.append("Swing结构仍有下降特征")

        if downtrend_score < self.config.c_min_downtrend_score or downtrend_hits < 2:
            failed.append("C_HARD_DOWNTREND_SCORE_TOO_LOW")
            return _empty_result(
                "C",
                "C1",
                failed,
                {"downtrend": round(downtrend_score, 2), "oversold": 0, "selling_pressure": 0, "rebound": 0, "total": round(downtrend_score, 2)},
                passed,
                reasons[:6],
            )

        oversold_score = 0.0
        oversold_hits = 0
        drawdown20 = self.config.c_drawdown20_stock if f.get("asset_type") == "stock" else self.config.c_drawdown20_etf
        drawdown60 = self.config.c_drawdown60_stock if f.get("asset_type") == "stock" else self.config.c_drawdown60_etf
        if _num(f, "drawdown_from_20d_high") <= drawdown20:
            oversold_score += 8
            oversold_hits += 1
            passed.append("C-O1")
            reasons.append(_pct_reason("20日回撤较充分", f, "drawdown_from_20d_high"))
        if _num(f, "drawdown_from_60d_high") <= drawdown60:
            oversold_score += 7
            oversold_hits += 1
            passed.append("C-O2")
            reasons.append(_pct_reason("60日回撤较充分", f, "drawdown_from_60d_high"))
        oversold_atr = abs(_num(f, "drawdown_from_20d_high")) / _num(f, "atr_pct") if _num(f, "atr_pct") > 0 else 0.0
        if oversold_atr >= self.config.c_drawdown20_atr_min:
            oversold_score += 5
            oversold_hits += 1
            passed.append("C-O3")
            reasons.append(f"20日回撤达到{oversold_atr:.1f}倍ATR")
        if _num(f, "rsi14_min_5") <= self.config.c_rsi_deep_oversold:
            oversold_score += 6
            oversold_hits += 1
            passed.append("C-O4_STRONG")
            reasons.append("近5日RSI出现深度超跌")
        elif _num(f, "rsi14_min_5") <= self.config.c_rsi_oversold:
            oversold_score += 4
            oversold_hits += 1
            passed.append("C-O4")
            reasons.append("近5日RSI出现超跌")
        if _num(f, "ret_10") < self.config.c_ret10_weak:
            oversold_score += 4
            oversold_hits += 1
            passed.append("C-O5")
            reasons.append(_pct_reason("10日收益明显为负", f, "ret_10"))

        if oversold_score < self.config.c_min_oversold_score or oversold_hits < 2:
            failed.append("C_HARD_OVERSOLD_SCORE_TOO_LOW")
            total = downtrend_score + oversold_score
            return _empty_result(
                "C",
                "C1",
                failed,
                {"downtrend": round(downtrend_score, 2), "oversold": round(oversold_score, 2), "selling_pressure": 0, "rebound": 0, "total": round(total, 2)},
                passed,
                reasons[:6],
            )

        pressure_score = 0.0
        pressure_hits = 0
        if bool(f.get("low_3_not_falling")):
            pressure_score += 5
            pressure_hits += 1
            passed.append("C-S1")
            reasons.append("最近3日低点不再明显下移")
        if 0 < _num(f, "range_contract_3") < 1:
            pressure_score += 4
            pressure_hits += 1
            passed.append("C-S2")
            reasons.append("短期K线波动收窄")
        if _num(f, "volume_ratio_5_20") < 1:
            pressure_score += 4
            pressure_hits += 1
            passed.append("C-S3")
            reasons.append("短期成交量低于20日均量")
        if _num(f, "rsi14_prev_min_5") <= self.config.c_rsi_oversold and _num(f, "rsi14") > self.config.c_rsi_recover_level:
            pressure_score += 7
            pressure_hits += 1
            passed.append("C-S4")
            reasons.append("RSI从低位回升")

        rebound_score = 0.0
        rebound_hits = 0
        if _num(f, "adj_close") > _num(f, "ma5"):
            rebound_score += 4
            rebound_hits += 1
            passed.append("C-T1")
            reasons.append("收盘站上MA5")
        if _num(f, "adj_close") > _num(f, "ma10"):
            rebound_score += 4
            rebound_hits += 1
            passed.append("C-T2")
            reasons.append("收盘站上MA10")
        if bool(f.get("break_5")):
            rebound_score += 4
            rebound_hits += 1
            passed.append("C-T3")
            reasons.append("突破前5日高点")
        if bool(f.get("break_10")):
            rebound_score += 5
            rebound_hits += 1
            passed.append("C-T4")
            reasons.append("突破前10日高点")
        if bool(f.get("strong_bullish_atr")) and _num(f, "close_position") > 0.7:
            rebound_score += 4
            rebound_hits += 1
            passed.append("C-T5")
            reasons.append("出现强反弹阳线")
        if _num(f, "close_position") > 0.6:
            rebound_score += 2
            passed.append("C-T5_POSITION")
        if _num(f, "today_volume_ratio_20") > 1.2:
            rebound_score += 3
            rebound_hits += 1
            passed.append("C-T6")
            reasons.append(_pct_reason("今日成交量高于20日均量", f, "today_volume_ratio_20", ratio=True))

        score_detail = {
            "downtrend": round(min(downtrend_score, 30), 2),
            "oversold": round(min(oversold_score, 30), 2),
            "selling_pressure": round(min(pressure_score, 20), 2),
            "rebound": round(min(rebound_score, 20), 2),
        }
        total = max(0.0, min(sum(score_detail.values()), 100.0))
        score_detail["total"] = round(total, 2)

        stage = "C1"
        if pressure_hits + rebound_hits >= self.config.c_stage_c2_min_rebound_hits:
            stage = "C2"
        if stage == "C2" and (bool(f.get("break_5")) or bool(f.get("break_10"))):
            stage = "C3"
        return PoolResult("C", stage, total, reasons[:8], score_detail, passed, failed)


def build_candidate(
    features: dict[str, Any],
    pool_results: list[PoolResult],
    risks: list[str],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    ordered = sorted(pool_results, key=lambda item: (-item.score, POOL_ORDER.get(item.stage, 99)))
    primary = ordered[0]
    status_change = _status_change(primary, previous)
    return {
        "asset_code": features["asset_code"],
        "asset_type": features["asset_type"],
        "name": features.get("name"),
        "trade_date": features["trade_date"],
        "primary_pool": primary.pool,
        "stage": primary.stage,
        "score": round(primary.score, 2),
        "pools": [item.as_dict() for item in ordered],
        "reasons": primary.reasons,
        "risks": risks,
        "score_detail": primary.score_detail,
        "passed_rules": primary.passed_rules,
        "failed_rules": primary.failed_rules,
        "status_change": status_change,
        "pct_chg": features.get("pct_chg"),
        "ret_20": features.get("ret_20"),
        "ret_60": features.get("ret_60"),
        "ret_120": features.get("ret_120"),
        "ret_250": features.get("ret_250"),
        "distance_from_high_60": features.get("distance_from_high_60"),
        "distance_from_high_250": features.get("distance_from_high_250"),
        "drawdown_from_20d_high": features.get("drawdown_from_20d_high"),
        "drawdown_from_60d_high": features.get("drawdown_from_60d_high"),
        "max_drawdown_120": features.get("max_drawdown_120"),
        "max_drawdown_250": features.get("max_drawdown_250"),
        "close_vs_ma20": features.get("close_vs_ma20"),
        "close_vs_ma60": features.get("close_vs_ma60"),
        "ma20_slope_10": features.get("ma20_slope_10"),
        "ma60_slope_20": features.get("ma60_slope_20"),
        "ma120_slope_20": features.get("ma120_slope_20"),
        "ma120_slope_60": features.get("ma120_slope_60"),
        "ma60_slope_improvement": features.get("ma60_slope_improvement"),
        "atr_pct": features.get("atr_pct"),
        "rsi14": features.get("rsi14"),
        "rsi14_min_5": features.get("rsi14_min_5"),
        "pullback_pct_120": features.get("pullback_pct_120"),
        "pullback_peak_age_120": features.get("pullback_peak_age_120"),
        "break_swing_low_pct": features.get("break_swing_low_pct"),
        "break_5": features.get("break_5"),
        "break_10": features.get("break_10"),
        "last_swing_high": features.get("last_swing_high"),
        "last_swing_low": features.get("last_swing_low"),
        "higher_low": features.get("higher_low"),
        "lower_high": features.get("lower_high"),
        "lower_low": features.get("lower_low"),
        "amount_ma20": features.get("amount_ma20"),
        "today_volume_ratio_20": features.get("today_volume_ratio_20"),
    }


def _status_change(primary: PoolResult, previous: dict[str, Any] | None) -> str:
    if previous is None:
        return "NEW"
    prev_stage = str(previous["stage"])
    if prev_stage == primary.stage:
        return "STAY"
    prev_rank = POOL_ORDER.get(prev_stage, 99)
    current_rank = POOL_ORDER.get(primary.stage, 99)
    if previous["primary_pool"] == primary.pool and current_rank < prev_rank:
        return "UPGRADE"
    if previous["primary_pool"] == primary.pool and current_rank > prev_rank:
        return "DOWNGRADE"
    return "REENTER"


def _empty_result(
    pool: str,
    stage: str,
    failed_rules: list[str],
    score_detail: dict[str, Any] | None = None,
    passed_rules: list[str] | None = None,
    reasons: list[str] | None = None,
) -> PoolResult:
    detail = score_detail or {"total": 0.0}
    return PoolResult(
        pool=pool,
        stage=stage,
        score=float(detail.get("total", 0.0)),
        reasons=reasons or [],
        score_detail=detail,
        passed_rules=passed_rules or [],
        failed_rules=failed_rules,
    )


def _num(f: dict[str, Any], key: str) -> float:
    value = f.get(key)
    if value is None:
        return 0.0
    return float(value)


def _pct_reason(label: str, f: dict[str, Any], key: str, ratio: bool = False) -> str:
    value = _num(f, key)
    if ratio:
        return f"{label}{value:.2f}倍"
    return f"{label}{value * 100:.1f}%"


def _volatility_contracts(f: dict[str, Any]) -> bool:
    current = _num(f, "volatility_20")
    previous = _num(f, "prev_volatility_20")
    return current > 0 and previous > 0 and current < previous


def _overheat_penalty(f: dict[str, Any]) -> float:
    penalty = 0.0
    if _num(f, "close_vs_ma20") > 0.15:
        penalty += 8
    if _num(f, "ret_5") > 0.15:
        penalty += 6
    if _num(f, "ret_10") > 0.25:
        penalty += 8
    if _num(f, "today_volume_ratio_20") > 3:
        penalty += 6
    current_atr = _num(f, "atr_pct")
    if current_atr > 0.08:
        penalty += 4
    return penalty


def _risk_labels(f: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    if _num(f, "close_vs_ma20") > 0.15:
        risks.append("距离MA20过远")
    if _num(f, "ret_5") > 0.15:
        risks.append("5日涨幅过大")
    if _num(f, "ret_10") > 0.25:
        risks.append("10日涨幅过大")
    if _num(f, "today_volume_ratio_20") > 3:
        risks.append("成交量异常放大")
    if _num(f, "amount_ma20") < 30_000_000 and f.get("asset_type") == "stock":
        risks.append("流动性偏低")
    return risks
