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

from backend.screening.double_bottom_rules import POSSIBLE_BONUS, CLEAR_BONUS, ACTIVE_BARS_AFTER_CONFIRMATION


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


def calc_min_3ma_spread(row: dict[str, Any] | Any) -> float | None:
    """Return the tightest span among any three of MA5/10/20/30.

    This is deliberately distinct from PREP_SCORE's four-line overall spread.
    A missing moving average means that the historical compression observation is
    not usable; callers must not invent a substitute value.
    """
    values: list[float] = []
    for period in (5, 10, 20, 30):
        try:
            value = float(row[f"ma{period}"])
        except (KeyError, TypeError, ValueError):
            return None
        if math.isnan(value) or value <= 0:
            return None
        values.append(value)
    values.sort()
    return min(values[2] - values[0], values[3] - values[1])


class EarlyTurnEngine:
    """A-Pre V2 早期转强评分引擎"""

    def evaluate_stock(
        self,
        ts_code: str,
        trade_date: str,
        features: dict[str, Any],
        *,
        prep_score_mode: str = "rounded",
    ) -> dict[str, Any]:
        """对单只股票的日线及技术特征计算 Early Turn 8 大模块分值与状态"""
        data_status = features.get("data_status") if features else None
        if data_status:
            return {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "total_score": 0.0,
                "raw_total_score": 0.0,
                "score_type": "NONE",
                "prep_score": None,
                "turn_score": None,
                "state": "NO_SIGNAL",
                "turn_episode_state": None,
                "signal_status": "NO_SIGNAL",
                "background_type": "UNKNOWN",
                "selected": False,
                "is_overextended": False,
                "features_json": features,
                "score_detail_json": {},
                "reasons_json": [{"code": data_status, "msg": features.get("data_reason", "数据不可用于正式评估")}],
            }
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
        min_3_spread = calc_min_3ma_spread({"ma5": ma5, "ma10": ma10, "ma20": ma20, "ma30": ma30})
        if min_3_spread is None:
            min_3_spread = 999.0
        min_3ma_spread_atr = min_3_spread / atr20 if atr20 > 0 else 9.9

        # 收敛必须比较真实的 5 日前最紧三均线跨度；缺失时此项不给分，
        # 不能以当前值乘常数伪造历史压缩。
        raw_spread_5d = features.get("min_3ma_spread_5d_ago")
        try:
            spread_5d = float(raw_spread_5d) if raw_spread_5d is not None else None
        except (ValueError, TypeError):
            spread_5d = None
        if spread_5d is not None and (math.isnan(spread_5d) or spread_5d <= 0):
            spread_5d = None
        comp_ratio = min_3_spread / spread_5d if spread_5d is not None else None
        cross_pairs = int(_f(features, "cross_pair_count_10d"))

        score_transition = 0.0
        if min_3ma_spread_atr <= 0.51:
            score_transition += 15.0
        elif min_3ma_spread_atr <= 0.8:
            score_transition += 10.0
        elif min_3ma_spread_atr <= 1.2:
            score_transition += 5.0

        if comp_ratio is not None and comp_ratio < 0.8:
            score_transition += 5.0
        elif comp_ratio is not None and comp_ratio < 0.95:
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

        # 生命周期决定使用哪一套评分。生命周期本身由服务层先回放完成；这里
        # 只按既定状态打分，不能反向影响触发、第一波或 Episode reset。
        turn_episode_state = str(features.get("turn_episode_state", "PRE_FIRST_TURN"))

        # ── E. Freshness (突破新鲜度, Max 10) ──────────────────────────────────
        # Freshness 只用于已进入 FIRST_TURN_WINDOW 的确认质量；PRE 的准备度
        # 不因“刚站上 3MA”而被抬高。
        days_retake_3ma = int(_f(features, "days_retake_3ma"))
        if turn_episode_state == "FIRST_TURN_WINDOW" and retake_cnt >= 3 and days_retake_3ma >= 1:
            freshness_valid = True
            if days_retake_3ma <= 2:
                score_freshness = 10.0
            elif days_retake_3ma <= 5:
                score_freshness = 7.0
            elif days_retake_3ma <= 10:
                score_freshness = 4.0
            else:
                score_freshness = 1.0
        else:
            freshness_valid = False
            score_freshness = 0.0

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

        # ── TURN_SCORE：首次转强确认质量（旧七项评分，Max 100）──────────────
        turn_score = (
            bg_score +
            score_transition +
            score_retake +
            score_direction +
            score_freshness +
            score_vol +
            score_space
        )
        turn_score = round(min(100.0, turn_score), 1)

        # ── PREP_SCORE：底部准备成熟度（Max 100）─────────────────────────────
        # 只在 PRE 使用；刻意不纳入 Freshness / Volume / 旧 Space / 旧 Dir。
        # 它衡量“变化正在形成”，不等同于正式首次转强确认。
        def slope_flat_score(slope: float) -> float:
            if slope <= -0.03:
                return 0.0
            if slope <= -0.02:
                return 2.0
            if slope <= -0.01:
                return 5.0
            if slope <= -0.003:
                return 8.0
            return 10.0

        def curve_improve_score(improve: float) -> float:
            if improve <= 0:
                return 0.0
            if improve < 0.005:
                return 3.0
            if improve < 0.01:
                return 6.0
            return 10.0

        ma10_slope_5d = _f(features, "ma10_slope_5d")
        ma20_slope_5d = _f(features, "ma20_slope_5d")
        ma10_slope_prev5 = _f(features, "ma10_slope_prev5")
        ma20_slope_prev5 = _f(features, "ma20_slope_prev5")
        ma10_curve_improve = _f(features, "ma10_curve_improve")
        ma20_curve_improve = _f(features, "ma20_curve_improve")
        ma_spread_atr = _f(features, "ma_spread_atr", default=9.9)

        # A-PreV2 的新方案；独立技术分类仍显式使用其原有评分口径。
        prep_slope_breakdown = None
        if prep_score_mode == "rounded":
            rounded = features.get("rounded_repair")
            required = ("ma5_decelerating", "ma5_flattened", "ma5_rounded")
            if (not isinstance(rounded, dict) or not rounded.get("indicators_available")
                    or any(not isinstance(rounded.get(key), bool) for key in required)):
                raise ValueError("底部准备度评分缺少 MA5 圆弧诊断数据")
            ma5_points = (5.0 if rounded["ma5_decelerating"] else 0.0) + (5.0 if rounded["ma5_flattened"] else 0.0) + (5.0 if rounded["ma5_rounded"] else 0.0)
            ma5_daily = rounded.get('ma5_daily_slopes')
            if not isinstance(ma5_daily, list) or len(ma5_daily) < 3 or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in ma5_daily[-3:]):
                raise ValueError('底部准备度评分缺少 MA5 近期斜率')
            if ma5_daily[-1] > 0 and ma5_daily[-1] > ma5_daily[-2] > ma5_daily[-3]:
                ma5_points = max(ma5_points, 10.0)
            ma10_points = slope_flat_score(ma10_slope_5d) * 0.8 + curve_improve_score(ma10_curve_improve) * 0.7
            ma20_points = slope_flat_score(ma20_slope_5d) * 0.5 + curve_improve_score(ma20_curve_improve) * 0.5
            if ma10_slope_5d > 0:
                ma10_points = 15.0
            if ma20_slope_5d > 0:
                ma20_points = 10.0
            prep_slope_turn = round(ma5_points + ma10_points + ma20_points, 1)
            prep_slope_breakdown = {"ma5": ma5_points, "ma10": round(ma10_points, 1), "ma20": round(ma20_points, 1)}
        elif prep_score_mode == "existing":
            prep_slope_turn = (
                slope_flat_score(ma10_slope_5d) + slope_flat_score(ma20_slope_5d)
                + curve_improve_score(ma10_curve_improve) + curve_improve_score(ma20_curve_improve)
            )
        else:
            raise ValueError(f"未知的准备度评分方案：{prep_score_mode}")

        if ma_spread_atr <= 0.60:
            prep_compression = 15.0
        elif ma_spread_atr <= 0.90:
            prep_compression = 12.0
        elif ma_spread_atr <= 1.20:
            prep_compression = 8.0
        elif ma_spread_atr <= 1.60:
            prep_compression = 4.0
        else:
            prep_compression = 0.0
        # 已站回三根均线、短线拐升时，适度展开仍是修复，不按压缩不足降分。
        if (prep_score_mode == 'rounded' and close > ma5 and close > ma10 and close > ma20
                and ma10_slope_5d > 0 and isinstance(ma5_daily, list) and ma5_daily
                and ma5_daily[-1] > 0 and ma_spread_atr <= 1.20):
            prep_compression = 15.0
        if cross_pairs >= 3:
            prep_cross = 10.0
        elif cross_pairs == 2:
            prep_cross = 7.0
        elif cross_pairs == 1:
            prep_cross = 4.0
        else:
            prep_cross = 0.0
        prep_compression_cross = prep_compression + prep_cross

        prep_retake = {0: 0.0, 1: 5.0, 2: 12.0, 3: 18.0, 4: 20.0}.get(retake_cnt, 0.0)
        return_20d = _f(features, "return_20d")
        return_40d = _f(features, "return_40d")
        max_drawdown_60d = _f(features, "max_drawdown_60d")
        days_since_40d_high = int(_f(features, "days_since_40d_high"))
        strong_decline = (
            return_20d <= -0.08
            or return_40d <= -0.15
            or max_drawdown_60d >= 0.18
        ) and days_since_40d_high >= 8
        weak_decline = (
            return_20d <= -0.04
            or return_40d <= -0.08
            or max_drawdown_60d >= 0.10
        ) and days_since_40d_high >= 5
        prep_decline = 10.0 if strong_decline else (5.0 if weak_decline else 0.0)
        position_full_limit = 1.5 if prep_score_mode == 'rounded' else 1.0
        position_partial_limit = 2.0 if prep_score_mode == 'rounded' else 1.5
        if extension_atr <= position_full_limit:
            prep_position = 5.0
        elif extension_atr <= position_partial_limit:
            prep_position = 3.0
        else:
            prep_position = 0.0
        prep_background_position = prep_decline + prep_position
        prep_base_score = round(min(100.0, prep_slope_turn + prep_compression_cross + prep_retake + prep_background_position), 1)
        bottom_bonus = 0.0
        if prep_score_mode == "rounded":
            if "bottom_structure_type" not in features or "bottom_structure_quality" not in features:
                raise ValueError("底部准备度评分缺少双底结构数据")
            bottom_type = features["bottom_structure_type"]
            bottom_quality = features["bottom_structure_quality"]
            if bottom_type not in {"NONE", "MICRO_DOUBLE_BOTTOM", "STANDARD_DOUBLE_BOTTOM"} or bottom_quality not in {"NONE", "POSSIBLE", "CLEAR"}:
                raise ValueError("双底结构类型或质量无效")
            if (bottom_type == "NONE") != (bottom_quality == "NONE"):
                raise ValueError("双底结构类型与质量不一致")
            if bottom_type == "STANDARD_DOUBLE_BOTTOM":
                age = features.get("bottom_structure_age_bars")
                confirmed_date = features.get("bottom_structure_confirmed_date")
                if (not isinstance(age, int) or isinstance(age, bool) or not 0 <= age <= ACTIVE_BARS_AFTER_CONFIRMATION
                        or not isinstance(confirmed_date, str) or len(confirmed_date) != 8
                        or confirmed_date > str(trade_date).replace("-", "")):
                    raise ValueError("日线双底确认日期或有效期无效")
                bottom_bonus = {"POSSIBLE": POSSIBLE_BONUS, "CLEAR": CLEAR_BONUS}[bottom_quality]
        prep_score = round(min(100.0, prep_base_score + bottom_bonus), 1)
        bottom_bonus_applied = round(prep_score - prep_base_score, 1)

        # 评分输出统一为 total_score，但语义必须由 score_type 明确区分。
        # FIRST 的 75 分正式入选门槛只比较 TURN_SCORE，保持原策略不变。
        retake_zero_cap = False
        if turn_episode_state == "PRE_FIRST_TURN":
            score_type = "PREP_SCORE"
            raw_total_score = prep_score
            total_score = prep_score
        elif turn_episode_state == "FIRST_TURN_WINDOW":
            score_type = "TURN_SCORE"
            raw_total_score = turn_score
            retake_zero_cap = retake_cnt == 0
            total_score = round(min(turn_score, 49.0) if retake_zero_cap else turn_score, 1)
        elif turn_episode_state == "POST_FIRST_WAVE":
            score_type = "NONE"
            raw_total_score = turn_score
            total_score = turn_score
        else:  # OUTSIDE_A_PRE：不属于本策略，不展示为低分候选。
            score_type = "NONE"
            raw_total_score = turn_score
            total_score = 0.0

        # ── 三层状态架构计算 (3-Tier Architecture) ─────────────────────────
        structural_damage_flag = bool(features.get("structural_damage_flag", False))
        first_trigger_date = features.get("first_trigger_date")
        first_trigger_close = _f(features, "first_trigger_close")
        return_since_first_trigger = _f(features, "return_since_first_trigger")
        pct_change_today = _f(features, "pct_change_today")

        # 1. 旧 signal_status 保留用于数据库/历史兼容；新的正式资格由
        #    lifecycle + total_score 单独决定，不能再由 PRE_READY/WATCH 放宽。
        if turn_episode_state in {"POST_FIRST_WAVE", "OUTSIDE_A_PRE"}:
            signal_status = "POST_FIRST_WAVE"
            if turn_episode_state == "OUTSIDE_A_PRE":
                signal_status = "NO_SIGNAL"
        elif structural_damage_flag:
            if total_score >= 65.0:
                signal_status = "PRE_READY"
            elif total_score >= 50.0:
                signal_status = "WATCH"
            else:
                signal_status = "NO_SIGNAL"
        elif turn_episode_state == "FIRST_TURN_WINDOW":
            if retake_cnt >= 3 and total_score >= 75.0:
                signal_status = "EARLY_TURN"
            elif total_score >= 65.0:
                signal_status = "PRE_READY"
            elif total_score >= 50.0:
                signal_status = "WATCH"
            else:
                signal_status = "NO_SIGNAL"
        else:  # PRE_FIRST_TURN
            if total_score >= 65.0:
                signal_status = "PRE_READY"
            elif total_score >= 50.0:
                signal_status = "WATCH"
            else:
                signal_status = "NO_SIGNAL"

        # 2. 旧 entry_extension_state 保留审计兼容；用户侧只看 is_overextended。
        if turn_episode_state in {"POST_FIRST_WAVE", "OUTSIDE_A_PRE"}:
            entry_extension_state = "NOT_APPLICABLE"
        elif return_since_first_trigger > 0.08 or extension_atr > 2.0 or (ma20 > 0 and (close - ma20) / ma20 > 0.18):
            entry_extension_state = "VERY_EXTENDED"  # 追高
        elif return_since_first_trigger > 0.04 or extension_atr > 1.5:
            entry_extension_state = "EXTENDED"       # 略延伸
        else:
            entry_extension_state = "NORMAL"         # 正常

        is_overextended = bool(
            extension_atr > 2.0
            or (ma20 > 0 and (close - ma20) / ma20 > 0.18)
            or pct_change_today >= 0.15
        )

        # state 是新的主状态：只表达生命周期；signal_status 作为旧字段保留。
        state = turn_episode_state

        # 原因分析列表 (Reasons)
        reasons = []
        if turn_episode_state == "FIRST_TURN_WINDOW":
            reasons.append({"type": "INFO", "msg": f"处于首次转强窗口 (触发日: {first_trigger_date or '近期'})"})
        elif turn_episode_state == "POST_FIRST_WAVE":
            reasons.append({"type": "WARN", "msg": "第一波上涨已完成并经历回撤，标志本轮 A-Pre 早期使命结束"})
        elif turn_episode_state == "OUTSIDE_A_PRE":
            reasons.append({"type": "INFO", "msg": "当前未形成 A-Pre 底部准备结构，暂不纳入本策略"})

        if turn_episode_state == "PRE_FIRST_TURN":
            reasons.append({
                "type": "INFO",
                "msg": f"底部准备度 {prep_score:.1f}/100：均线走平 {prep_slope_turn:.0f}/40、均线结构 {prep_compression_cross:.0f}/25、夺回均线 {prep_retake:.0f}/20、背景位置 {prep_background_position:.0f}/15",
            })
        if min_3ma_spread_atr <= 0.51:
            reasons.append({"type": "BONUS", "msg": f"均线系统高度压缩 (离散度/ATR: {min_3ma_spread_atr:.2f})"})
        if cross_pairs >= 3:
            reasons.append({"type": "BONUS", "msg": f"发生 {cross_pairs} 组均线交叉结扎 (MA Knot)"})
        if chop_penalty > 0:
            reasons.append({"type": "WARN", "msg": f"检测到近期均线反复交叉缠绕，存在震荡杂噪 (扣分 {chop_penalty:.1f})"})
        if freshness_valid and days_retake_3ma <= 2:
            reasons.append({"type": "BONUS", "msg": f"突破新鲜度极佳 (站上 3MA 第 {days_retake_3ma} 天)"})
        if structural_damage_flag:
            reasons.append({"type": "WARN", "msg": "检测到 60 日内大幅急跌后反射性反弹，结构受损"})
        if is_overextended:
            # 触发价收益与 MA20/ATR 拉伸是两个独立维度；负的触发价收益
            # 只能说明当前价格已低于触发价，不能被描述为追高原因。
            if extension_atr > 2.0 or (ma20 > 0 and (close - ma20) / ma20 > 0.18):
                reasons.append({
                    "type": "WARN",
                    "msg": f"股价偏离 20MA {extension_atr:.1f} ATR，当前相对 MA20 短期拉伸",
                })
            if return_since_first_trigger > 0.08:
                reasons.append({
                    "type": "WARN",
                    "msg": f"当前较首次触发价上涨 {return_since_first_trigger:.1%}，位置偏离触发区",
                })
            if pct_change_today >= 0.15:
                reasons.append({
                    "type": "WARN",
                    "msg": f"首次触发日/当前交易日涨幅 {pct_change_today:.1%}，属于大阳线加速",
                })

        # UI 兼容性映射
        score_detail = {
            "score_type": score_type,
            "prep_score": prep_score,
            "turn_score": turn_score,
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
            "min_3ma_spread": round(min_3_spread, 6) if min_3_spread < 999.0 else None,
            "min_3ma_spread_5d_ago": round(spread_5d, 6) if spread_5d is not None else None,
            "comp_ratio": round(comp_ratio, 4) if comp_ratio is not None else None,
            "cross_pair_count_10d": cross_pairs,
            "order_score": order_score,
            "freshness_valid": freshness_valid,
            "days_retake_3ma": days_retake_3ma,
            "order_improvement": order_improvement,
            "up_slope_count": int(_f(features, "days_ma5_slope_pos")),
            "retake_count": retake_cnt,
            "fresh_retake": freshness_valid and days_retake_3ma <= 2,
            "extension_atr": round(extension_atr, 2),
            "pct_change_today": round(pct_change_today, 4),
            "v2_details": {
                "turn_type": tt,
                "score_type": score_type,
                "prep_score": prep_score,
                "turn_score": turn_score,
                "prep": {
                    "slope_turn": prep_slope_turn,
                    "slope_breakdown": prep_slope_breakdown,
                    "compression_cross": prep_compression_cross,
                    "retake": prep_retake,
                    "background_position": prep_background_position,
                    "base_score": prep_base_score,
                    "bottom_bonus": bottom_bonus_applied,
                    "bottom_bonus_before_cap": bottom_bonus,
                    "decline": prep_decline,
                    "position": prep_position,
                },
                "ma10_slope_5d": ma10_slope_5d,
                "ma20_slope_5d": ma20_slope_5d,
                "ma10_slope_prev5": ma10_slope_prev5,
                "ma20_slope_prev5": ma20_slope_prev5,
                "ma10_curve_improve": ma10_curve_improve,
                "ma20_curve_improve": ma20_curve_improve,
                "ma_spread_atr": ma_spread_atr,
                "return_20d": return_20d,
                "return_40d": return_40d,
                "max_drawdown_60d": max_drawdown_60d,
                "days_since_40d_high": days_since_40d_high,
                "transition": score_transition,
                "retake": score_retake,
                "direction": score_direction,
                "freshness": score_freshness,
                "vol": score_vol,
                "space": score_space,
                "chop_penalty": chop_penalty,
                "overhead_resistance": overhead_res,
                "dist_high_60": dist_high_60,
                "turn_episode_state": turn_episode_state,
                "signal_status": signal_status,
                "entry_extension_state": entry_extension_state,
                "structural_damage_flag": structural_damage_flag,
                "episode_base_low": features.get("episode_base_low"),
                "episode_base_low_date": features.get("episode_base_low_date"),
                "first_wave_high_close": features.get("first_wave_high_close"),
                "first_wave_high_date": features.get("first_wave_high_date"),
                "first_wave_gain": _f(features, "first_wave_gain"),
                "first_wave_gain_atr": _f(features, "first_wave_gain_atr"),
                "first_wave_formed": bool(features.get("first_wave_formed", False)),
                "drawdown_from_first_wave_high": _f(features, "drawdown_from_first_wave_high"),
                "raw_total_score": raw_total_score,
                "retake_zero_cap": retake_zero_cap,
            }
        }

        return {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "total_score": total_score,
            "raw_total_score": raw_total_score,
            "score_type": score_type,
            "prep_score": prep_score,
            "turn_score": turn_score,
            "retake_zero_cap": retake_zero_cap,
            "state": state,
            "turn_episode_state": turn_episode_state,
            "signal_status": signal_status,
            "entry_extension_state": entry_extension_state,
            "background_type": bg_type,
            "selected": (
                turn_episode_state == "FIRST_TURN_WINDOW"
                and retake_cnt >= 3
                and turn_score >= 75.0
            ),
            "is_overextended": is_overextended,
            "first_trigger_date": first_trigger_date,
            "first_trigger_close": first_trigger_close,
            "return_since_first_trigger": return_since_first_trigger,
            "structural_damage_flag": structural_damage_flag,
            "bottom_structure_type": features.get("bottom_structure_type", "NONE"),
            "bottom_structure_quality": features.get("bottom_structure_quality", "NONE"),
            "bottom_structure_strength": features.get("bottom_structure_strength", 0),
            "bottom_first_low_date": features.get("bottom_first_low_date"),
            "bottom_second_low_date": features.get("bottom_second_low_date"),
            "bottom_structure_confirmed_date": features.get("bottom_structure_confirmed_date"),
            "features_json": features,
            "score_detail_json": score_detail,
            "reasons_json": reasons,
        }
