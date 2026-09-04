"""
A-Pre V2 EarlyTurnService

基于 screening_daily_bar 的 90 日 K 线数据实时计算 8 大量化特征组与打分模型。
1. run(trade_date, ts_code=None): 支持全市场选股评估或单股定向测试。
2. validate_positive_samples(): 运行正样本（京投发展、浙江医药、百花医药等）基于 K 线的全量回归测试。
"""

from typing import Any, Callable, Dict, List, Optional
import uuid
import math
import pandas as pd
import numpy as np
from dataclasses import dataclass
from backend.screening.storage import PostgresScreeningStore
from backend.screening.early_turn_engine import EarlyTurnEngine, calc_min_3ma_spread

# 预设验证集正样本（来自文档）
BUILTIN_POSITIVE_SAMPLES = [
    {"ts_code": "600683.SH", "target_date": "20260807", "sample_name": "京投发展", "note": "最佳入选日: 08-07 (68分 PRE_READY)，信号从 08-04 的 57分(WATCH) 递增至 08-07 的 68分"},
    {"ts_code": "600216.SH", "target_date": "20260715", "sample_name": "浙江医药", "note": "最佳入选区间: 07-09~07-15 (连续71分 PRE_READY)，07-16 暴涨拐点达 88分 EARLY_TURN"},
    {"ts_code": "600721.SH", "target_date": "20260720", "sample_name": "百花医药", "note": "最佳入选日: 07-17 与 07-20 (86分 EARLY_TURN)，首次观察日为 07-15"},
    {"ts_code": "600266.SH", "target_date": "20260723", "sample_name": "城建发展", "note": "最佳入选日: 07-15 (83分 EARLY_TURN) 及 07-23/07-27 (67分 PRE_READY)，回避了07-25试盘探底"},
    {"ts_code": "002659.SZ", "target_date": "20260729", "sample_name": "凯文教育", "note": "最佳入选日: 07-15 (83分) 与 07-29 (88分 EARLY_TURN)，08-01 连涨后精准触发防追高风控"},
    {"ts_code": "300308.SZ", "target_date": "20260617", "sample_name": "中际旭创", "note": "高位横盘整理再启动样本，最佳入选日: 06-17 (67分 PRE_READY)，首次观察日 05-08"},
]

# 第一波识别参数：只服务于生命周期 FIRST → POST / PRE 的判断，
# 不参与 A-PreV2 的七项评分、PRE 定义或正式入选阈值。
EPISODE_BASE_LOOKBACK_BARS = 40
FIRST_WAVE_GAIN_THRESHOLD = 0.08
FIRST_WAVE_ATR_THRESHOLD = 2.5
FIRST_WAVE_PULLBACK_THRESHOLD = 0.06
TURN_FAILURE_TRIGGER_DRAWDOWN = 0.12
POST_COOLDOWN_BARS = 60
PRE_EXIT_GRACE_BARS = 5
PRE_MIN_DECLINE_FROM_40D_HIGH = 0.08
HISTORY_LOOKBACK_BARS = 320
EPISODE_WARMUP_BARS = 60
MIN_VALID_HISTORY_BARS = 80
EARLY_TURN_CONFIG_VERSION = "A_PRE_V2_20260830_V3"


@dataclass
class EarlyTurnService:
    store: PostgresScreeningStore
    engine: EarlyTurnEngine = EarlyTurnEngine()

    def calculate_features_from_bars(self, ts_code: str, target_date: str) -> dict[str, Any]:
        """基于 Point-in-Time 前复权日线向上追溯 320 日现场计算特征。

        原始行情仍保存在 screening_daily_bar；技术指标不能直接使用原始价，
        否则除权除息日会被误判为暴跌、破位或生命周期结束。这里使用
        ``close * adj_factor``，相对于评估日只是一个统一缩放，既保持
        Point-in-Time 口径，也不会引入未来价格信息。
        """
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                select b.trade_date, b.open, b.high, b.low, b.close, b.vol, b.amount,
                       a.adj_factor
                from screening_daily_bar b
                join screening_adj_factor a
                  on a.asset_code = b.asset_code and a.trade_date = b.trade_date
                where b.asset_code = %s and b.trade_date <= %s
                  and a.adj_factor > 0
                order by trade_date desc limit %s
                """,
                (ts_code, target_date, HISTORY_LOOKBACK_BARS),
            ).fetchall()

        if not rows:
            return {"data_status": "DATA_MISSING", "data_reason": "未读取到有效前复权日K"}

        df = pd.DataFrame([dict(r) for r in reversed(rows)])
        normalized_target_date = str(target_date).replace("-", "")
        latest_trade_date = str(df.iloc[-1]["trade_date"])
        if latest_trade_date != normalized_target_date:
            return {
                "data_status": "DATA_STALE",
                "data_reason": f"目标日 {normalized_target_date} 无行情，最新有效日K为 {latest_trade_date}",
                "latest_trade_date": latest_trade_date,
            }
        if len(df) < MIN_VALID_HISTORY_BARS:
            return {
                "data_status": "DATA_INSUFFICIENT",
                "data_reason": f"有效日K仅 {len(df)} 根，正式A-Pre至少需要 {MIN_VALID_HISTORY_BARS} 根",
                "valid_bar_count": len(df),
            }
        for col in ['open', 'high', 'low', 'close', 'vol', 'amount']:
            df[col] = df[col].astype(float)
        df['adj_factor'] = df['adj_factor'].astype(float)
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col] * df['adj_factor']

        # 均线计算
        df['ma5'] = df['close'].rolling(5).mean()
        df['ma10'] = df['close'].rolling(10).mean()
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma30'] = df['close'].rolling(30).mean()
        df['ma60'] = df['close'].rolling(60).mean()

        # ATR20
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                (df['high'] - df['close'].shift(1)).abs(),
                (df['low'] - df['close'].shift(1)).abs()
            )
        )
        df['atr20'] = df['tr'].rolling(20).mean()

        # 10 日均线结 (MA Knot) 交叉对数统计
        pairs = [(5, 10), (5, 20), (5, 30), (10, 20), (10, 30), (20, 30)]
        cross_pairs = set()
        cross_events = 0

        recent_10 = df.tail(10)
        for i in range(1, len(recent_10)):
            t_curr = recent_10.iloc[i]
            t_prev = recent_10.iloc[i - 1]
            for p1, p2 in pairs:
                m1_curr, m2_curr = t_curr[f'ma{p1}'], t_curr[f'ma{p2}']
                m1_prev, m2_prev = t_prev[f'ma{p1}'], t_prev[f'ma{p2}']
                if pd.notna(m1_curr) and pd.notna(m2_curr) and pd.notna(m1_prev) and pd.notna(m2_prev):
                    if (m1_curr > m2_curr) != (m1_prev > m2_prev):
                        cross_pairs.add((p1, p2))
                        cross_events += 1

        def calc_order_score(row):
            m5, m10, m20, m30 = row['ma5'], row['ma10'], row['ma20'], row['ma30']
            if pd.isna(m5) or pd.isna(m10) or pd.isna(m20) or pd.isna(m30):
                return 1.0
            return (1.0 if m5 > m10 else 0.0) + (1.0 if m5 > m20 else 0.0) + (1.0 if m10 > m20 else 0.0) + (0.5 if m20 > m30 else 0.0)

        def calc_retake_count(row):
            close_val = row['close']
            return sum([
                1 for p in (5, 10, 20, 30)
                if pd.notna(row[f'ma{p}']) and close_val > row[f'ma{p}']
            ])

        # Add retake_count column to df for consecutive days calculation
        df['retake_count'] = df.apply(calc_retake_count, axis=1)

        # MA Slopes
        df['ma5_slope'] = df['ma5'].pct_change(3)
        df['ma10_slope'] = df['ma10'].pct_change(5)
        df['ma20_slope'] = df['ma20'].pct_change(5)
        df['ma30_slope'] = df['ma30'].pct_change(5)

        curr = df.iloc[-1]
        prev_5 = df.iloc[-6] if len(df) >= 6 else curr
        prev_10 = df.iloc[-11] if len(df) >= 11 else curr
        idx = len(df) - 1

        def count_consecutive(series_bool, end_idx):
            count = 0
            for k in range(end_idx, -1, -1):
                if series_bool.iloc[k]:
                    count += 1
                else:
                    break
            return count

        days_retake_3ma = count_consecutive(df['retake_count'] >= 3, idx)
        days_retake_4ma = count_consecutive(df['retake_count'] >= 4, idx)
        days_ma5_slope_pos = count_consecutive(df['ma5_slope'] > 0, idx)
        days_ma10_slope_pos = count_consecutive(df['ma10_slope'] > 0, idx)

        # Resistance high
        lookback_60 = df.tail(60)
        recent_high_60 = float(lookback_60['high'].max())
        close_curr = float(curr['close'])
        dist_high_60 = (recent_high_60 - close_curr) / close_curr

        lookback_120 = df.tail(120)
        recent_high_120 = float(lookback_120['high'].max())
        dist_high_120 = (recent_high_120 - close_curr) / close_curr

        # ── PREP_SCORE 专用背景/均线特征 ──────────────────────────────────
        # 这些特征只使用评估日及之前的 K 线，不参与生命周期状态迁移。
        # MA10/20 的“前 5 日斜率”用于量化下跌是否正在减速、走平或拐头。
        def pct_between(newer, older) -> float:
            if pd.isna(newer) or pd.isna(older) or float(older) == 0:
                return 0.0
            return float(newer / older - 1.0)

        ma10_slope_5d = pct_between(curr['ma10'], prev_5['ma10'])
        ma20_slope_5d = pct_between(curr['ma20'], prev_5['ma20'])
        ma10_slope_prev5 = pct_between(prev_5['ma10'], prev_10['ma10'])
        ma20_slope_prev5 = pct_between(prev_5['ma20'], prev_10['ma20'])
        ma10_curve_improve = ma10_slope_5d - ma10_slope_prev5
        ma20_curve_improve = ma20_slope_5d - ma20_slope_prev5

        required_prep_fields = {
            "ma10_slope_5d": ma10_slope_5d,
            "ma20_slope_5d": ma20_slope_5d,
            "ma10_slope_prev5": ma10_slope_prev5,
            "ma20_slope_prev5": ma20_slope_prev5,
            "ma10_curve_improve": ma10_curve_improve,
            "ma20_curve_improve": ma20_curve_improve,
            "atr20": curr["atr20"],
        }
        missing_prep_fields = [name for name, value in required_prep_fields.items() if pd.isna(value)]
        if missing_prep_fields:
            return {
                "data_status": "DATA_INSUFFICIENT",
                "data_reason": f"PREP_SCORE关键字段缺失：{', '.join(missing_prep_fields)}",
                "valid_bar_count": len(df),
            }

        ma_values = [float(curr[f'ma{period}']) for period in (5, 10, 20, 30) if pd.notna(curr[f'ma{period}'])]
        ma_spread_atr = (
            (max(ma_values) - min(ma_values)) / float(curr['atr20'])
            if len(ma_values) == 4 and pd.notna(curr['atr20']) and float(curr['atr20']) > 0
            else 9.9
        )

        ret_20d = pct_between(curr['close'], df.iloc[-21]['close']) if len(df) >= 21 else 0.0
        ret_40d = pct_between(curr['close'], df.iloc[-41]['close']) if len(df) >= 41 else 0.0
        prep_window_60 = df.tail(60)
        running_high_60 = prep_window_60['high'].cummax()
        max_drawdown_60d = float((1.0 - prep_window_60['low'] / running_high_60).max()) if len(prep_window_60) else 0.0
        prep_window_40 = df.tail(40)
        high_40 = float(prep_window_40['high'].max()) if len(prep_window_40) else close_curr
        last_high_40_pos = max(i for i, value in enumerate(prep_window_40['high'].tolist()) if value == high_40) if len(prep_window_40) else 0
        days_since_40d_high = len(prep_window_40) - 1 - last_high_40_pos if len(prep_window_40) else 0

        # Overhead peaks detection
        peaks = []
        for i in range(max(0, idx - 60), idx):
            if i < 2 or i > len(df) - 3:
                continue
            val = df.iloc[i]['high']
            if val == df.iloc[i-2:i+3]['high'].max():
                peaks.append(float(val))
        resistance_peaks = [p for p in peaks if close_curr <= p <= close_curr * 1.06]
        overhead_resistance_flag = len(resistance_peaks) >= 2

        # ── 急跌结构受损标记 (Structural Damage Flag) ──────────────────────
        lookback_20 = df.tail(20)
        running_high_20 = lookback_20['high'].cummax()
        max_20d_drawdown = float((1.0 - lookback_20['low'] / running_high_20).max()) if len(lookback_20) else 0.0

        min_60d_low = float(lookback_60['low'].min()) if len(lookback_60) > 0 else close_curr
        low_idx_rel = lookback_60['low'].values.argmin() if len(lookback_60) > 0 else 0
        days_since_60d_low = len(lookback_60) - 1 - low_idx_rel

        ma60_curr = float(curr['ma60']) if pd.notna(curr['ma60']) else 0.0
        ma60_prev10 = float(df.iloc[-11]['ma60']) if len(df) >= 11 and pd.notna(df.iloc[-11]['ma60']) else ma60_curr
        ma60_slope_down = (ma60_curr < ma60_prev10)

        structural_damage_flag = bool(max_20d_drawdown >= 0.20 and days_since_60d_low <= 15 and ma60_slope_down)

        # ── Point-in-Time Turn Episode Tracking ─────────────────────────────
        first_trigger_idx = None
        first_trigger_date = None
        first_trigger_close = None
        first_trigger_atr20 = None

        # 生命周期不再覆盖所有股票。只有形成有效底部准备结构的标的才
        # 进入 A-Pre；其余均为策略外，不能因一次普通站均线而开启 Episode。
        turn_episode_state = "OUTSIDE_A_PRE"
        pre_enter_idx: int | None = None
        pre_enter_date: str | None = None
        pre_invalid_days = 0
        post_enter_idx: int | None = None
        post_enter_date: str | None = None
        max_close_since_trigger = 0.0
        max_high_since_trigger = 0.0
        pre_trigger_stage_low: float | None = None
        # 基准低点是本轮 Episode 的起点，不是首次触发确认点。一旦触发后
        # 固定，避免后续回放时低点随窗口移动而漂移。
        episode_base_low: float | None = None
        episode_base_low_date: str | None = None
        episode_base_atr20: float | None = None
        first_wave_high_close: float | None = None
        first_wave_high_date: str | None = None
        first_wave_high: float | None = None
        first_wave_high_intraday_date: str | None = None
        first_wave_formed = False
        first_wave_gain = 0.0
        first_wave_gain_atr = 0.0
        drawdown_from_first_wave_high = 0.0
        below_ma30_days = 0
        below_ma60_days = 0
        # POST 的旧轮即使确认失效，也不能立刻被标作新的 PRE。先保留旧轮
        # 的诊断与 POST 状态，等待真正出现一段新的底部准备结构后再开新轮。
        post_reset_waiting_for_pre = False

        def clear_episode() -> None:
            """在确认新 PRE 起点时清空上一轮 Episode 的内部锚点。"""
            nonlocal first_trigger_idx, first_trigger_date, first_trigger_close, first_trigger_atr20
            nonlocal max_close_since_trigger, max_high_since_trigger, pre_trigger_stage_low
            nonlocal episode_base_low, episode_base_low_date, episode_base_atr20
            nonlocal first_wave_high_close, first_wave_high_date, first_wave_high
            nonlocal first_wave_high_intraday_date, first_wave_formed
            nonlocal below_ma30_days, below_ma60_days

            first_trigger_idx = None
            first_trigger_date = None
            first_trigger_close = None
            first_trigger_atr20 = None
            max_close_since_trigger = 0.0
            max_high_since_trigger = 0.0
            pre_trigger_stage_low = None
            episode_base_low = None
            episode_base_low_date = None
            episode_base_atr20 = None
            first_wave_high_close = None
            first_wave_high_date = None
            first_wave_high = None
            first_wave_high_intraday_date = None
            first_wave_formed = False
            below_ma30_days = 0
            below_ma60_days = 0

        def has_pre_qualification(k: int, row: pd.Series) -> bool:
            """确认进入 PRE 前，确实形成了底部准备结构。

            这不是 PREP_SCORE 的评分门槛，而是 A-Pre 生命周期入口：必须有
            足够回撤背景、均线下跌减速/走平、均线靠拢且价格开始夺回均线。
            四项缺一不可，避免普通上涨趋势、高位回踩或下跌途中被标为 PRE。
            """
            if k < 10:
                return False
            prev5 = df.iloc[k - 5]
            prev10 = df.iloc[k - 10]
            atr = float(row['atr20']) if pd.notna(row['atr20']) and float(row['atr20']) > 0 else 0.0
            if atr <= 0:
                return False

            def pct_between(newer: Any, older: Any) -> float | None:
                if pd.isna(newer) or pd.isna(older) or float(older) == 0:
                    return None
                return float(newer / older - 1.0)

            ma10_now = pct_between(row['ma10'], prev5['ma10'])
            ma20_now = pct_between(row['ma20'], prev5['ma20'])
            ma10_prev = pct_between(prev5['ma10'], prev10['ma10'])
            ma20_prev = pct_between(prev5['ma20'], prev10['ma20'])
            if None in (ma10_now, ma20_now, ma10_prev, ma20_prev):
                return False

            min_3_spread = calc_min_3ma_spread(row)
            compressed = min_3_spread is not None and float(min_3_spread) / atr <= 1.2
            prior_40 = df.iloc[max(0, k - 40):k]
            prior_high = float(prior_40['high'].max()) if len(prior_40) else 0.0
            has_decline_background = (
                prior_high > 0
                and (prior_high - float(row['close'])) / prior_high >= PRE_MIN_DECLINE_FROM_40D_HIGH
            )
            def has_stabilized(now: float, previous: float) -> bool:
                # 仍在下行时必须较前一段减速；已经走平或转升后，不因
                # 上涨斜率的自然回落而否定新的 PRE 结构。
                return now >= -0.01 and (now >= 0.0 or now >= previous)

            slope_decelerating = has_stabilized(ma10_now, ma10_prev) and has_stabilized(ma20_now, ma20_prev)
            return (
                has_decline_background
                and int(row['retake_count']) >= 1
                and compressed
                and slope_decelerating
            )

        # 前 60 根只用于指标预热；其后的约一年行情全部参与 Episode 回放。
        start_eval_bar = EPISODE_WARMUP_BARS
        for k in range(start_eval_bar, len(df)):
            row_k = df.iloc[k]
            close_k = float(row_k['close'])
            low_k = float(row_k['low'])
            retake_k = int(row_k['retake_count'])
            atr_k = float(row_k['atr20']) if pd.notna(row_k['atr20']) else close_k * 0.03

            m5_k, m10_k = row_k['ma5'], row_k['ma10']
            order_score_k = calc_order_score(row_k)

            if turn_episode_state == "OUTSIDE_A_PRE":
                if has_pre_qualification(k, row_k):
                    turn_episode_state = "PRE_FIRST_TURN"
                    pre_enter_idx = k
                    pre_enter_date = str(row_k['trade_date'])
                    pre_invalid_days = 0
                continue

            if turn_episode_state == "PRE_FIRST_TURN" and first_trigger_idx is None:
                # FIRST 必须由已存在至少一个交易日的有效 PRE 发起；不能从
                # 策略外状态直接站上三根均线就进入首次转强窗口。
                if (
                    pre_enter_idx is not None
                    and k > pre_enter_idx
                    and retake_k >= 3
                    and order_score_k >= 2.0
                    and pd.notna(m5_k)
                    and pd.notna(m10_k)
                    and m5_k > m10_k
                ):
                    # 触发日前最近 40 个交易日的阶段低点；不把触发当天低点
                    # 纳入，以保持“本轮 PRE 形成过程”的起点语义。
                    # 预热区不参与状态迁移，但可以作为本轮启动前的背景，
                    # 否则恰好在第一个可评估日触发时会没有可用的阶段低点。
                    base_start = max(0, k - EPISODE_BASE_LOOKBACK_BARS)
                    base_window = df.iloc[base_start:k]
                    base_low_idx = base_window['low'].idxmin()
                    base_row = df.loc[base_low_idx]
                    first_trigger_idx = k
                    first_trigger_date = str(row_k['trade_date'])
                    first_trigger_close = close_k
                    first_trigger_atr20 = atr_k
                    max_close_since_trigger = close_k
                    max_high_since_trigger = float(row_k['high'])
                    episode_base_low = float(base_row['low'])
                    episode_base_low_date = str(base_row['trade_date'])
                    episode_base_atr20 = (
                        float(base_row['atr20'])
                        if pd.notna(base_row['atr20']) and float(base_row['atr20']) > 0
                        else atr_k
                    )
                    first_wave_high_close = close_k
                    first_wave_high_date = str(row_k['trade_date'])
                    first_wave_high = float(row_k['high'])
                    first_wave_high_intraday_date = str(row_k['trade_date'])
                    first_wave_gain = (
                        (first_wave_high_close - episode_base_low) / episode_base_low
                        if episode_base_low > 0 else 0.0
                    )
                    first_wave_gain_atr = (
                        (first_wave_high - episode_base_low) / episode_base_atr20
                        if episode_base_atr20 and episode_base_atr20 > 0 else 0.0
                    )
                    first_wave_formed = bool(
                        first_wave_gain >= FIRST_WAVE_GAIN_THRESHOLD
                        or first_wave_gain_atr >= FIRST_WAVE_ATR_THRESHOLD
                    )
                    below_ma30_days = 0
                    below_ma60_days = 0
                    pre_trigger_stage_low = (
                        float(df.iloc[:k]['low'].min()) if k > 0 else None
                    )
                    turn_episode_state = "FIRST_TURN_WINDOW"
                    continue

                # PRE 不应永久滞留。连续失去 PRE 资格后回到策略外，等待
                # 下一段真正的底部准备，而不是用旧资格承接未来任意突破。
                if has_pre_qualification(k, row_k):
                    pre_invalid_days = 0
                else:
                    pre_invalid_days += 1
                    if pre_invalid_days >= PRE_EXIT_GRACE_BARS:
                        turn_episode_state = "OUTSIDE_A_PRE"
                        pre_enter_idx = None
                        pre_enter_date = None
                        pre_invalid_days = 0
                continue

            if first_trigger_idx is not None:
                if float(row_k['high']) > max_high_since_trigger:
                    max_high_since_trigger = float(row_k['high'])
                if close_k > max_close_since_trigger:
                    max_close_since_trigger = close_k

                if first_wave_high_close is None or close_k > first_wave_high_close:
                    first_wave_high_close = close_k
                    first_wave_high_date = str(row_k['trade_date'])
                if first_wave_high is None or float(row_k['high']) > first_wave_high:
                    first_wave_high = float(row_k['high'])
                    first_wave_high_intraday_date = str(row_k['trade_date'])

                # 第一波必须从本轮基准低点识别，而不是从触发确认点识别。
                # 否则触发前已上涨的一段会被忽略，形成第一波后回撤的股票
                # 会被错判为“首次转强失败”。
                first_wave_gain = (
                    (first_wave_high_close - episode_base_low) / episode_base_low
                    if episode_base_low and episode_base_low > 0 and first_wave_high_close is not None
                    else 0.0
                )
                first_wave_gain_atr = (
                    (first_wave_high - episode_base_low) / episode_base_atr20
                    if episode_base_low is not None and first_wave_high is not None and episode_base_atr20 and episode_base_atr20 > 0
                    else 0.0
                )
                if not first_wave_formed and (
                    first_wave_gain >= FIRST_WAVE_GAIN_THRESHOLD
                    or first_wave_gain_atr >= FIRST_WAVE_ATR_THRESHOLD
                ):
                    first_wave_formed = True

                drawdown_from_first_wave_high = (
                    (first_wave_high_close - close_k) / first_wave_high_close
                    if first_wave_high_close and first_wave_high_close > 0 else 0.0
                )

                m30_k = float(row_k['ma30']) if pd.notna(row_k['ma30']) else 0.0
                m60_k = float(row_k['ma60']) if pd.notna(row_k['ma60']) else 0.0
                prev_row_k = df.iloc[k - 1]
                prev_close_k = float(prev_row_k['close'])
                prev_ma30_k = float(prev_row_k['ma30']) if pd.notna(prev_row_k['ma30']) else 0.0
                cross_down_ma30 = (
                    prev_ma30_k > 0
                    and prev_close_k >= prev_ma30_k
                    and m30_k > 0
                    and close_k < m30_k
                )

                if turn_episode_state == "FIRST_TURN_WINDOW":
                    # 顺序必须是：先确认是否已形成第一波，再判断首次转强失败。
                    # 已形成第一波时，回撤应转为 POST，不能再退回 PRE。
                    if first_wave_formed:
                        if (
                            drawdown_from_first_wave_high >= FIRST_WAVE_PULLBACK_THRESHOLD
                            or cross_down_ma30
                        ):
                            turn_episode_state = "POST_FIRST_WAVE"
                            post_enter_idx = k
                            post_enter_date = str(row_k['trade_date'])
                    else:
                        turn_failed = (
                            (first_trigger_close > 0 and close_k <= first_trigger_close * (1.0 - TURN_FAILURE_TRIGGER_DRAWDOWN))
                            or (episode_base_low is not None and close_k < episode_base_low)
                            or (pre_trigger_stage_low is not None and close_k < pre_trigger_stage_low)
                        )
                        if turn_failed:
                            clear_episode()
                            turn_episode_state = "OUTSIDE_A_PRE"
                            pre_enter_idx = None
                            pre_enter_date = None
                            pre_invalid_days = 0
                            continue

                elif turn_episode_state == "POST_FIRST_WAVE":
                    # POST 只表达第一波刚完成后的冷却期。到期后不再占用
                    # 主状态；若当日已有新的 PRE 结构，则从新 Episode 的 PRE
                    # 重新开始，否则回到策略外。
                    if post_enter_idx is not None and k - post_enter_idx >= POST_COOLDOWN_BARS:
                        clear_episode()
                        post_reset_waiting_for_pre = False
                        if has_pre_qualification(k, row_k):
                            turn_episode_state = "PRE_FIRST_TURN"
                            pre_enter_idx = k
                            pre_enter_date = str(row_k['trade_date'])
                            pre_invalid_days = 0
                        else:
                            turn_episode_state = "OUTSIDE_A_PRE"
                            pre_enter_idx = None
                            pre_enter_date = None
                        post_enter_idx = None
                        post_enter_date = None
                        continue

                    # 旧轮已被确认失效时，仍保持 POST，直至另一个真正的 PRE
                    # 结构出现。不能把“没有 active Episode”偷换成“底部准备中”。
                    if post_reset_waiting_for_pre:
                        if has_pre_qualification(k, row_k):
                            clear_episode()
                            post_reset_waiting_for_pre = False
                            turn_episode_state = "PRE_FIRST_TURN"
                            pre_enter_idx = k
                            pre_enter_date = str(row_k['trade_date'])
                            pre_invalid_days = 0
                            post_enter_idx = None
                            post_enter_date = None
                        continue

                    # POST 的重置必须是旧轮的实质失效：创新 60 日低点、价格
                    # 回到本轮基准低点附近，或极端且持续的结构破坏。单纯 25%
                    # 高位回撤和短期跌破均线，不足以说明已形成一轮新的底部。
                    below_ma30_days = below_ma30_days + 1 if m30_k > 0 and close_k < m30_k else 0
                    below_ma60_days = below_ma60_days + 1 if m60_k > 0 and close_k < m60_k else 0
                    prior_60_lows = df.iloc[max(0, k - 60):k]['low']
                    is_new_60d_low = bool(
                        len(prior_60_lows) > 0 and low_k <= float(prior_60_lows.min())
                    )
                    trigger_zone_broken = first_trigger_close > 0 and close_k < first_trigger_close * 0.92
                    structural_drawdown_pct = (
                        (max_high_since_trigger - close_k) / max_high_since_trigger
                        if max_high_since_trigger > 0 else 0.0
                    )
                    near_episode_base = (
                        episode_base_low is not None
                        and low_k <= episode_base_low * 1.05
                    )
                    prolonged_medium_break = below_ma30_days >= 10 or below_ma60_days >= 5
                    extreme_protracted_break = structural_drawdown_pct >= 0.35 and prolonged_medium_break
                    if trigger_zone_broken and (is_new_60d_low or near_episode_base or extreme_protracted_break):
                        post_reset_waiting_for_pre = True
                        continue

        # Episode 最终快照字段：供单股回放、批量快照与诊断导出共同使用。
        first_wave_gain = (
            (first_wave_high_close - episode_base_low) / episode_base_low
            if episode_base_low and episode_base_low > 0 and first_wave_high_close is not None
            else 0.0
        )
        first_wave_gain_atr = (
            (first_wave_high - episode_base_low) / episode_base_atr20
            if episode_base_low is not None and first_wave_high is not None and episode_base_atr20 and episode_base_atr20 > 0
            else 0.0
        )
        drawdown_from_first_wave_high = (
            (first_wave_high_close - close_curr) / first_wave_high_close
            if first_wave_high_close and first_wave_high_close > 0 else 0.0
        )
        days_since_first_trigger = (idx - first_trigger_idx) if first_trigger_idx is not None else 0
        return_since_first_trigger = (close_curr - first_trigger_close) / first_trigger_close if (first_trigger_close and first_trigger_close > 0) else 0.0

        # Turn type (后台降级保留)
        prior_window = df.iloc[max(0, idx-60):max(0, idx-5)]
        has_prior_strong_turn = False
        consec = 0
        for val in prior_window['retake_count']:
            if val >= 3:
                consec += 1
                if consec >= 3:
                    has_prior_strong_turn = True
            else:
                consec = 0

        days_above_ma20_prior = sum([1 for i, r in prior_window.iterrows() if r['close'] > r['ma20']])
        ratio_above_ma20 = days_above_ma20_prior / len(prior_window) if len(prior_window) > 0 else 0.0

        if ratio_above_ma20 > 0.6:
            turn_type = "CONSOLIDATION_RESTART"
        elif has_prior_strong_turn:
            turn_type = "SECONDARY_TURN"
        else:
            turn_type = "FIRST_TURN"

        vol_ratio = float(curr['amount'] / lookback_60['amount'].median()) if len(lookback_60) > 0 and lookback_60['amount'].median() > 0 else 1.0

        order_score_curr = calc_order_score(curr)
        order_score_5d = calc_order_score(prev_5)
        min_3ma_spread = calc_min_3ma_spread(curr)
        min_3ma_spread_5d_ago = calc_min_3ma_spread(prev_5)
        cross_down_ma30 = bool(
            len(df) >= 2
            and pd.notna(df.iloc[-2]['ma30'])
            and float(df.iloc[-2]['close']) >= float(df.iloc[-2]['ma30'])
            and pd.notna(curr['ma30'])
            and close_curr < float(curr['ma30'])
        )

        features = {
            'close': close_curr,
            'ma5': float(curr['ma5']) if pd.notna(curr['ma5']) else 0.0,
            'ma10': float(curr['ma10']) if pd.notna(curr['ma10']) else 0.0,
            'ma20': float(curr['ma20']) if pd.notna(curr['ma20']) else 0.0,
            'ma30': float(curr['ma30']) if pd.notna(curr['ma30']) else 0.0,
            'ma60': float(curr['ma60']) if pd.notna(curr['ma60']) else 0.0,
            'atr20': float(curr['atr20']),
            'cross_pair_count_10d': len(cross_pairs),
            'cross_event_count_10d': cross_events,
            'order_score': order_score_curr,
            'order_score_5d_ago': order_score_5d,
            'order_improvement': order_score_curr - order_score_5d,
            'retake_count': int(curr['retake_count']),
            'days_retake_3ma': days_retake_3ma,
            'days_retake_4ma': days_retake_4ma,
            'days_ma5_slope_pos': days_ma5_slope_pos,
            'days_ma10_slope_pos': days_ma10_slope_pos,
            'recent_high_60': recent_high_60,
            'recent_high_120': recent_high_120,
            'dist_high_60': dist_high_60,
            'dist_high_120': dist_high_120,
            'overhead_resistance_flag': overhead_resistance_flag,
            'turn_type': turn_type,
            'volume_ratio': vol_ratio,
            'slope5_3d': float(curr['ma5'] / df.iloc[-4]['ma5'] - 1.0) if len(df) >= 4 and pd.notna(df.iloc[-4]['ma5']) else 0.0,
            'slope10_5d': ma10_slope_5d,
            'slope20_5d': ma20_slope_5d,
            'slope30_5d': float(curr['ma30'] / prev_5['ma30'] - 1.0) if pd.notna(prev_5['ma30']) else 0.0,
            'ma10_slope_5d': ma10_slope_5d,
            'ma20_slope_5d': ma20_slope_5d,
            'ma10_slope_prev5': ma10_slope_prev5,
            'ma20_slope_prev5': ma20_slope_prev5,
            'ma10_curve_improve': ma10_curve_improve,
            'ma20_curve_improve': ma20_curve_improve,
            'ma_spread_atr': ma_spread_atr,
            'min_3ma_spread': min_3ma_spread,
            'min_3ma_spread_5d_ago': min_3ma_spread_5d_ago,
            'return_20d': ret_20d,
            'return_40d': ret_40d,
            'max_drawdown_60d': max_drawdown_60d,
            'days_since_40d_high': days_since_40d_high,
            'higher_low': float(curr['low']) > float(df.iloc[-10:-1]['low'].min()) if len(df) >= 10 else False,
            'amount_preheat': float(curr['amount'] / df.tail(20)['amount'].median()) if len(df) >= 20 and df.tail(20)['amount'].median() > 0 else 1.0,
            'pct_change_today': (
                float(close_curr / float(df.iloc[-2]['close']) - 1.0)
                if len(df) >= 2 and pd.notna(df.iloc[-2]['close']) and float(df.iloc[-2]['close']) > 0 else None
            ),
            # 新增三层状态属性
            'structural_damage_flag': structural_damage_flag,
            'turn_episode_state': turn_episode_state,
            'first_trigger_date': first_trigger_date,
            'first_trigger_close': first_trigger_close,
            'return_since_first_trigger': return_since_first_trigger,
            'days_since_first_trigger': days_since_first_trigger,
            'episode_base_low': episode_base_low,
            'episode_base_low_date': episode_base_low_date,
            'episode_base_atr20': episode_base_atr20,
            'first_wave_high_close': first_wave_high_close,
            'first_wave_high_date': first_wave_high_date,
            'first_wave_high': first_wave_high,
            'first_wave_high_intraday_date': first_wave_high_intraday_date,
            'first_wave_gain': first_wave_gain,
            'first_wave_gain_atr': first_wave_gain_atr,
            'first_wave_formed': first_wave_formed,
            'post_reset_waiting_for_pre': post_reset_waiting_for_pre,
            'pre_enter_date': pre_enter_date,
            'post_enter_date': post_enter_date,
            'drawdown_from_first_wave_high': drawdown_from_first_wave_high,
            'cross_down_ma30': cross_down_ma30,
        }
        return features

    def run(
        self,
        trade_date: str,
        ts_code: Optional[str] = None,
        config_version: str = EARLY_TURN_CONFIG_VERSION,
        run_name: Optional[str] = None,
        notes: Optional[str] = None,
        run_id: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict[str, Any]:
        """运行一次 A-Pre V2 策略评估（支持全市场或单股定向）"""
        rerun_codes: list[str] = []
        if run_id:
            rerun_codes = self.store.reset_early_turn_run(
                run_id=run_id,
                trade_date=trade_date,
                config_version=config_version,
                run_name=run_name,
                notes=notes,
            )
        else:
            run_id = f"et_{trade_date}_{uuid.uuid4().hex[:8]}"
            self.store.create_early_turn_run(
                run_id=run_id,
                trade_date=trade_date,
                config_version=config_version,
                run_name=run_name,
                notes=notes,
            )

        try:
            # 1. 确定要计算的资产列表
            with self.store.connect() as conn:
                if not ts_code and rerun_codes:
                    ts_code = ",".join(rerun_codes)
                if ts_code and ts_code.strip():
                    raw_input = ts_code.strip()
                    import re
                    terms = [t.strip() for t in re.split(r'[,;\s\n]+', raw_input) if t.strip()]
                    matched_codes = set()

                    for term in terms:
                        term_upper = term.upper()
                        # 1. 匹配股票代码
                        if term_upper.replace('.', '').isdigit() or term_upper.endswith(('.SH', '.SZ', '.BJ')):
                            clean = term_upper
                            if '.' not in clean and clean.isdigit():
                                clean = clean + ('.SH' if clean.startswith('6') else '.SZ')
                            rows_code = conn.execute(
                                "select asset_code as ts_code from screening_asset_master where asset_code ilike %s and asset_type = 'stock'",
                                (f"%{clean}%",),
                            ).fetchall()
                            for r in rows_code:
                                matched_codes.add(r['ts_code'])

                        # 2. 匹配股票名称
                        rows_name = conn.execute(
                            "select asset_code as ts_code from screening_asset_master where name ilike %s and asset_type = 'stock'",
                            (f"%{term}%",),
                        ).fetchall()
                        for r in rows_name:
                            matched_codes.add(r['ts_code'])

                        # 3. 匹配申万/同花顺行业
                        rows_ind = conn.execute(
                            "select asset_code as ts_code from screening_asset_master where raw_json->>'industry' ilike %s and asset_type = 'stock'",
                            (f"%{term}%",),
                        ).fetchall()
                        for r in rows_ind:
                            matched_codes.add(r['ts_code'])

                        # 4. 匹配同花顺概念板块
                        rows_concept = conn.execute(
                            """
                            select distinct asset_code as ts_code
                            from ths_concept_member_snapshot
                            where concept_name ilike %s
                            """,
                            (f"%{term}%",),
                        ).fetchall()
                        for r in rows_concept:
                            matched_codes.add(r['ts_code'])

                    if matched_codes:
                        rows = conn.execute(
                            "select asset_code as ts_code, name, raw_json->>'industry' as industry from screening_asset_master where asset_code = any(%s) and asset_type = 'stock'",
                            (list(matched_codes),),
                        ).fetchall()
                    else:
                        rows = []
                else:
                    rows = conn.execute(
                        "select asset_code as ts_code, name, raw_json->>'industry' as industry from screening_asset_master where asset_type = 'stock'"
                    ).fetchall()

            eval_results = []
            counts: Dict[str, int] = {}
            invalid_data_counts: Dict[str, int] = {}

            total_rows = len(rows)
            for idx, row in enumerate(rows, start=1):
                code = row["ts_code"]
                feat = self.calculate_features_from_bars(code, trade_date)
                data_status = feat.get("data_status") if feat else "DATA_MISSING"
                if data_status:
                    invalid_data_counts[data_status] = invalid_data_counts.get(data_status, 0) + 1
                    if progress_callback:
                        progress_callback(idx, total_rows, code)
                    continue

                feat["name"] = row.get("name")
                feat["industry"] = row.get("industry")

                res = self.engine.evaluate_stock(code, trade_date, feat)
                res["run_id"] = run_id
                res["first_selected_date"] = self._find_first_selected_date(
                    code, trade_date, res["selected"], config_version
                )

                eval_results.append(res)
                st = res["state"]
                counts[st] = counts.get(st, 0) + 1
                if progress_callback:
                    progress_callback(idx, total_rows, code)

            # 2. 保存结果
            self.store.save_early_turn_results(eval_results)

            summary = {
                "run_id": run_id,
                "trade_date": trade_date,
                "total_evaluated": len(eval_results),
                "counts": counts,
                "selected_count": sum(1 for item in eval_results if item.get("selected")),
                "invalid_data_counts": invalid_data_counts,
                "items": eval_results if ts_code else None,
            }
            self.store.finish_early_turn_run(run_id, status="DONE", summary=summary)
            return summary

        except Exception as exc:
            self.store.finish_early_turn_run(run_id, status="ERROR", error_message=str(exc))
            raise exc

    def _find_first_selected_date(
        self, ts_code: str, current_date: str, is_currently_selected: bool, config_version: str
    ) -> str | None:
        with self.store.connect() as conn:
            row = conn.execute(
                """select min(r.trade_date) as min_date
                   from early_turn_result r
                   join early_turn_run run on run.run_id = r.run_id
                   where r.ts_code = %s and r.selected = true
                     and r.trade_date <= %s and run.config_version = %s""",
                (ts_code, current_date, config_version),
            ).fetchone()
        if row and row["min_date"]:
            return row["min_date"]
        return current_date if is_currently_selected else None

    def validate_positive_samples(self, target_trade_date: str | None = None) -> list[dict[str, Any]]:
        """跑预设正样本基于 K 线的全量回归校验集"""
        for s in BUILTIN_POSITIVE_SAMPLES:
            self.store.save_positive_sample(
                ts_code=s["ts_code"],
                target_date=s["target_date"],
                sample_name=s["sample_name"],
                note=s["note"],
            )

        samples = self.store.list_positive_samples()
        validation_results = []

        for sample in samples:
            t_date = target_trade_date or sample["target_date"]
            ts_code = sample["ts_code"]

            feat = self.calculate_features_from_bars(ts_code, t_date)
            if not feat:
                validation_results.append({
                    "sample_id": sample["sample_id"],
                    "ts_code": ts_code,
                    "sample_name": sample["sample_name"],
                    "target_date": t_date,
                    "status": "DATA_MISSING",
                    "note": "行数据不足 15 日",
                    "total_score": 0.0,
                    "state": "NO_SIGNAL",
                })
                continue

            eval_res = self.engine.evaluate_stock(ts_code, t_date, feat)
            eval_res["sample_id"] = sample["sample_id"]
            eval_res["sample_name"] = sample["sample_name"]
            eval_res["target_date"] = t_date
            eval_res["hit"] = bool(eval_res.get("selected"))
            validation_results.append(eval_res)

        return validation_results

    def evaluate_single_stock_range(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        strategy_id: str = "A_PRE_V2",
    ) -> dict[str, Any]:
        """单股多日区间策略打分与 K 线整合评估"""
        clean_code = ts_code.strip().upper()
        if "." not in clean_code:
            if clean_code.startswith("6"):
                exchange_suffix = ".SH"
            elif clean_code.startswith(("4", "8", "9")):
                exchange_suffix = ".BJ"
            else:
                exchange_suffix = ".SZ"
            clean_code = clean_code + exchange_suffix

        # 查资产信息
        name = clean_code
        industry = "未知行业"
        with self.store.connect() as conn:
            row = conn.execute(
                "select name, raw_json->>'industry' as industry from screening_asset_master where asset_code = %s",
                (clean_code,),
            ).fetchone()
            if row:
                name = row["name"] or clean_code
                industry = row["industry"] or "未知行业"

        s_date = start_date.replace("-", "")
        e_date = end_date.replace("-", "")

        # 查指定区间内的所有交易日 K 线
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                select trade_date, open, high, low, close, vol, amount
                from screening_daily_bar
                where asset_code = %s and trade_date >= %s and trade_date <= %s
                order by trade_date asc
                """,
                (clean_code, s_date, e_date),
            ).fetchall()

        history = []
        for r in rows:
            d = r["trade_date"]
            close_p = float(r["close"])
            feat = self.calculate_features_from_bars(clean_code, d)
            if not feat:
                continue
            feat["name"] = name
            feat["industry"] = industry
            eval_res = self.engine.evaluate_stock(clean_code, d, feat)
            history.append({
                "trade_date": d,
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": close_p,
                "vol": float(r["vol"]),
                "amount": float(r["amount"]),
                "total_score": eval_res["total_score"],
                "score_type": eval_res.get("score_type", "NONE"),
                "prep_score": eval_res.get("prep_score"),
                "turn_score": eval_res.get("turn_score"),
                "state": eval_res["state"],
                "selected": eval_res.get("selected", False),
                "is_overextended": eval_res.get("is_overextended", False),
                "turn_episode_state": eval_res.get("turn_episode_state"),
                "signal_status": eval_res.get("signal_status"),
                "entry_extension_state": eval_res.get("entry_extension_state"),
                "first_trigger_date": eval_res.get("first_trigger_date"),
                "first_trigger_close": eval_res.get("first_trigger_close"),
                "return_since_first_trigger": eval_res.get("return_since_first_trigger"),
                "structural_damage_flag": eval_res.get("structural_damage_flag", False),
                # 单股调试导出需要可直接复核本轮生命周期，不只依赖最终状态。
                "episode_base_low": feat.get("episode_base_low"),
                "episode_base_low_date": feat.get("episode_base_low_date"),
                "first_wave_high_close": feat.get("first_wave_high_close"),
                "first_wave_high_date": feat.get("first_wave_high_date"),
                "first_wave_gain": feat.get("first_wave_gain"),
                "first_wave_gain_atr": feat.get("first_wave_gain_atr"),
                "first_wave_formed": feat.get("first_wave_formed", False),
                "drawdown_from_first_wave_high": feat.get("drawdown_from_first_wave_high"),
                "background_type": eval_res["background_type"],
                "score_detail_json": eval_res["score_detail_json"],
                "reasons_json": eval_res["reasons_json"],
            })

        # 获取截至 end_date 的全量历史 K 线数据。
        # 单股测试的策略评分仍使用上面的原始行情；但展示/导出的 K 线
        # 必须与 KLineModal 和常用行情软件保持同一口径，统一使用前复权。
        with self.store.connect() as conn:
            k_rows = conn.execute(
                """
                select trade_date, open, high, low, close, vol, amount
                from screening_daily_bar
                where asset_code = %s and trade_date <= %s
                order by trade_date asc
                """,
                (clean_code, e_date),
            ).fetchall()
            adj_rows = conn.execute(
                """
                select trade_date, adj_factor
                from screening_adj_factor
                where asset_code = %s and trade_date <= %s
                order by trade_date asc
                """,
                (clean_code, e_date),
            ).fetchall()

        klines = []
        if k_rows:
            adj_map = {str(r["trade_date"]): float(r["adj_factor"]) for r in adj_rows if r["adj_factor"] is not None}
            latest_adj = float(adj_rows[-1]["adj_factor"]) if adj_rows else 1.0
            df_k = pd.DataFrame([dict(r) for r in k_rows])
            for c in ["open", "high", "low", "close", "vol", "amount"]:
                df_k[c] = df_k[c].astype(float)
            if latest_adj > 0 and adj_map:
                # 与 storage.get_kline_bars(adjust="qfq") 使用完全相同的
                # Point-in-Time 比例，避免 7/27→7/28 除权日出现假跌幅。
                df_k["_adj_ratio"] = df_k["trade_date"].map(
                    lambda d: adj_map.get(str(d), latest_adj) / latest_adj
                )
                for c in ["open", "high", "low", "close"]:
                    df_k[c] = df_k[c] * df_k["_adj_ratio"]
            df_k["ma5"] = df_k["close"].rolling(5).mean()
            df_k["ma10"] = df_k["close"].rolling(10).mean()
            df_k["ma20"] = df_k["close"].rolling(20).mean()
            df_k["ma30"] = df_k["close"].rolling(30).mean()
            df_k["ma60"] = df_k["close"].rolling(60).mean()

            for _, r in df_k.iterrows():
                klines.append({
                    "trade_date": r["trade_date"],
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "vol": float(r["vol"]),
                    "amount": float(r["amount"]),
                    "ma5": float(r["ma5"]) if pd.notna(r["ma5"]) else None,
                    "ma10": float(r["ma10"]) if pd.notna(r["ma10"]) else None,
                    "ma20": float(r["ma20"]) if pd.notna(r["ma20"]) else None,
                    "ma30": float(r["ma30"]) if pd.notna(r["ma30"]) else None,
                    "ma60": float(r["ma60"]) if pd.notna(r["ma60"]) else None,
                })

        # 选取最近 90 个交易日的 K 线数据（供单股测试详情与导出使用）
        klines = klines[-90:] if len(klines) > 90 else klines

        return {
            "ts_code": clean_code,
            "name": name,
            "industry": industry,
            "strategy_id": strategy_id,
            "start_date": s_date,
            "end_date": e_date,
            "history": history,
            "klines": klines,
            "recent_90d_klines": klines,
        }
