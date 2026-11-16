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
from backend.screening.double_bottom_rules import (
    SHORT_MIN_GAP, DAILY_MIN_GAP, MAX_GAP, MAX_SECOND_LOW_DROP, MAX_SECOND_LOW_RISE,
    BREAK_CLOSE_TOLERANCE, ACTIVE_BARS_AFTER_CONFIRMATION,
)

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
FIRST_WAVE_GAIN_THRESHOLD = 0.20
FIRST_WAVE_ATR_THRESHOLD = 4.0
FIRST_WAVE_FAST_MAX_BARS = 4
FIRST_WAVE_PULLBACK_THRESHOLD = 0.06
TURN_FAILURE_TRIGGER_DRAWDOWN = 0.12
POST_COOLDOWN_BARS = 60
PRE_EXIT_GRACE_BARS = 5
PRE_MIN_DECLINE_FROM_60D_HIGH = 0.20
DECLINE_CONTEXT_LOOKBACK_BARS = 60
DECLINE_CONTEXT_MAX_AGE_BARS = 60
PRE_FAILURE_REACCEL_SLOPE = -0.02
PRE_FAILURE_CONFIRM_BARS = 2
EPISODE_WARMUP_BARS = 60
MIN_VALID_HISTORY_BARS = 80
SINGLE_TEST_LIFECYCLE_LOOKBACK_BARS = 60
# 单股窗口回放读取 120 根热身行情以计算最长的滚动背景字段；
# 生命周期仍从窗口前第 60 个交易日开始初始化。
SINGLE_TEST_INDICATOR_WARMUP_BARS = 120
EARLY_TURN_CONFIG_VERSION = "A_PRE_V2_REPAIR_SCORE_V6"
# 圆弧入口按最近十个交易日的均线观察下跌、平缓和回升。
ROUNDED_SLOPE_LOOKBACK_BARS = 9
ROUNDED_TRANSITION_BARS = 5
ROUNDED_RECOVERY_MAX_AGE_BARS = 3
ROUNDED_FLAT_SLOPE_LIMIT = 0.006
ROUNDED_MIN_FLAT_BARS = 2
ROUNDED_MIN_DECLINE_SLOPE = -0.006
FIRST_MA20_5D_MIN_SLOPE = -0.02
MA10_RECOVERY_DAYS = 3
MA10_RECOVERY_MIN_UP_DAYS = 2
MA10_RECOVERY_RANGE_5D = 0.03
MA10_DECELERATION_DAILY_MIN = -0.005
# 二次机会只作观察候选，使用日线与评估日之前可见的行情。
SECOND_MIN_WAVE_GAIN = 0.15
SECOND_MIN_POST_BARS = 3
SECOND_MIN_PULLBACK = 0.05
SECOND_MAX_PULLBACK = 0.35
SECOND_BASE_BREAK_TOLERANCE = 0.015
SECOND_CONSOLIDATION_BARS = 5
SECOND_CONSOLIDATION_MAX_RANGE = 0.12


def first_wave_meets_criteria(gain: float, gain_atr: float) -> bool:
    return gain >= FIRST_WAVE_GAIN_THRESHOLD and gain_atr >= FIRST_WAVE_ATR_THRESHOLD


def rounded_ma5_shape(ma5: list[float]) -> dict[str, Any]:
    """按时间顺序识别下跌→平缓→回升，只使用输入窗口内的数据。"""
    result: dict[str, Any] = {'ma5_rounded': False, 'ma5_decelerating': False,
                              'ma5_flattened': False, 'ma5_turning_up': False,
                              'ma5_decline_seen': False}
    if len(ma5) != ROUNDED_SLOPE_LOOKBACK_BARS + 1 or any(not math.isfinite(v) or v <= 0 for v in ma5):
        return result
    slopes = [ma5[i] / ma5[i - 1] - 1 for i in range(1, len(ma5))]
    result['ma5_daily_slopes'] = slopes
    # 在最近几日寻找回升起点；平缓证据必须出现在该起点之前。
    for pivot in range(len(slopes) - 1, len(slopes) - ROUNDED_RECOVERY_MAX_AGE_BARS - 2, -1):
        begin = pivot - ROUNDED_TRANSITION_BARS
        if begin < 0 or slopes[pivot] <= 0:
            continue
        before = slopes[begin:pivot]
        flattened = sum(abs(x) <= ROUNDED_FLAT_SLOPE_LIMIT for x in before) >= ROUNDED_MIN_FLAT_BARS
        had_decline = min(before) <= ROUNDED_MIN_DECLINE_SLOPE
        decelerating = had_decline and float(np.median(before[-2:])) > float(np.median(before[:2]))
        # 允许回升途中小幅回落，但当前均线须仍高于回升前。
        turning_up = ma5[-1] > ma5[pivot] and ma5[-1] >= ma5[-3]
        result['ma5_decline_seen'] |= had_decline
        result['ma5_flattened'] |= flattened
        result['ma5_decelerating'] |= decelerating
        result['ma5_turning_up'] |= turning_up
        # 先前必须确实下跌，并且至少有一段低位平缓；平缓后只要求
        # “下跌继续减速”或“均线已开始抬头”其中一项成立。
        # 不再要求减速与抬头必须在同一个观察日同时满足。
        if had_decline and flattened and (decelerating or turning_up):
            result['ma5_rounded'] = True
            result['recovery_age_bars'] = len(slopes) - 1 - pivot
            break
    # 杯底可以尚未向上：允许近三日轻微波动；下跌背景和平缓过渡仍是必需条件。
    if not result['ma5_rounded']:
        before = slopes[-ROUNDED_TRANSITION_BARS:]
        flattened = sum(abs(x) <= ROUNDED_FLAT_SLOPE_LIMIT for x in before) >= ROUNDED_MIN_FLAT_BARS
        had_decline = min(before) <= ROUNDED_MIN_DECLINE_SLOPE
        decelerating = had_decline and float(np.median(before[-2:])) > float(np.median(before[:2]))
        near_flat = ma5[-1] / ma5[-3] - 1 >= -0.002 and abs(slopes[-1]) <= ROUNDED_FLAT_SLOPE_LIMIT
        result['ma5_decline_seen'] |= had_decline
        result['ma5_flattened'] |= flattened
        result['ma5_decelerating'] |= decelerating
        if had_decline and flattened and (decelerating or near_flat):
            result.update({'ma5_rounded': True, 'ma5_flattened': True, 'ma5_turning_up': False})
    return result


def detect_second_opportunity(df: pd.DataFrame, *, base_low: float | None,
                              first_idx: int | None, post_idx: int | None) -> dict[str, Any]:
    """从已确认的一波和回调中识别观察候选；只接受截至当日的日线。"""
    result: dict[str, Any] = {'active': False, 'types': []}
    if base_low is None or base_low <= 0 or first_idx is None or post_idx is None:
        return result
    if first_idx < 0 or post_idx < first_idx or post_idx >= len(df):
        return result
    post = df.iloc[post_idx:]
    if len(post) < SECOND_MIN_POST_BARS:
        return result
    first_wave = df.iloc[first_idx:post_idx + 1]
    peak = float(first_wave['high'].max())
    gain = peak / base_low - 1
    low_after_peak = float(post['low'].min())
    pullback = 1 - low_after_peak / peak
    if (gain < SECOND_MIN_WAVE_GAIN or pullback < SECOND_MIN_PULLBACK
            or pullback > SECOND_MAX_PULLBACK
            or (post['close'] < base_low * (1 - SECOND_BASE_BREAK_TOLERANCE)).any()):
        return result
    row, prev = df.iloc[-1], df.iloc[-2]
    if any(pd.isna(row[x]) or float(row[x]) <= 0 for x in ('ma5', 'ma10')):
        return result
    if len(df) < 4 or pd.isna(df.iloc[-4]['ma5']):
        return result
    above_short = float(row['close']) > float(row['ma5']) and float(row['close']) > float(row['ma10'])
    ma5_values = [float(df.iloc[i]['ma5']) for i in range(len(df) - 4, len(df))]
    if any(not math.isfinite(value) or value <= 0 for value in ma5_values):
        return result
    ma5_changes = [ma5_values[i] / ma5_values[i - 1] - 1 for i in range(1, 4)]
    # 短期已经向上，或仍小幅下降但连续减速；不要求当前高于三日前。
    ma5_recovering = ma5_changes[-1] >= 0 or (
        ma5_changes[-1] >= -0.01 and ma5_changes[-1] > ma5_changes[-2] > ma5_changes[-3]
    )
    stabilized = above_short and ma5_recovering and float(row['close']) >= float(prev['close'])
    types: list[str] = []
    if stabilized:
        types.append('PULLBACK_RECOVERY')
    if len(post) >= SECOND_CONSOLIDATION_BARS + 1:
        consolidation = post.iloc[-SECOND_CONSOLIDATION_BARS - 1:-1]
        low, high = float(consolidation['low'].min()), float(consolidation['high'].max())
        if low > 0 and high / low - 1 <= SECOND_CONSOLIDATION_MAX_RANGE and float(row['close']) > high and above_short:
            types.append('CONSOLIDATION_BREAKOUT')
    result.update({'active': bool(types), 'types': types, 'wave_gain': gain, 'pullback': pullback,
                   'post_enter_date': str(df.iloc[post_idx]['trade_date'])})
    return result


def detect_bottom_structure(df: pd.DataFrame, as_of_idx: int, *, confirmed_after: str | None = None) -> dict[str, Any]:
    none = {
        'bottom_structure_type': 'NONE',
        'bottom_structure_quality': 'NONE',
        'bottom_structure_strength': 0,
        'bottom_first_low_date': None,
        'bottom_second_low_date': None,
        'bottom_structure_confirmed_date': None,
        'bottom_first_low': None,
        'bottom_middle_high': None,
        'bottom_second_low': None,
        'bottom_low_gap_bars': None,
        'bottom_structure_age_bars': None,
    }
    # 不截断更早的可确认结构；有效性由确认日期与失效条件决定。
    scan_start = 2
    scan_end = as_of_idx - 2  # 右侧两根K用于确认局部低点
    if scan_end <= scan_start:
        return none

    lows = df['low'].astype(float).tolist()
    highs = df['high'].astype(float).tolist()
    closes = df['close'].astype(float).tolist()
    local_lows: list[int] = []
    for low_idx in range(scan_start, scan_end + 1):
        window = lows[low_idx - 2:low_idx + 3]
        if lows[low_idx] <= min(window):
            local_lows.append(low_idx)
    if len(local_lows) < 2:
        return none

    candidates: list[dict[str, Any]] = []
    # 从最近的第二底向前寻找第一底；最终优先最近且已确认的结构。
    for second_pos in range(len(local_lows) - 1, 0, -1):
        l2_idx = local_lows[second_pos]
        for first_pos in range(second_pos - 1, -1, -1):
            l1_idx = local_lows[first_pos]
            gap = l2_idx - l1_idx
            if gap < SHORT_MIN_GAP:
                continue
            if gap > MAX_GAP:
                break
            l1 = lows[l1_idx]
            l2 = lows[l2_idx]
            if (l1 <= 0 or l2 <= 0
                    or l2 < l1 * (1 - MAX_SECOND_LOW_DROP)
                    or l2 > l1 * (1 + MAX_SECOND_LOW_RISE)):
                continue
            # 以收盘价而非盘中下影线确认破位，留出价格噪声空间。
            later_closes = closes[l2_idx + 1:as_of_idx + 1]
            if later_closes and min(later_closes) < min(l1, l2) * (1 - BREAK_CLOSE_TOLERANCE):
                continue

            middle_slice = highs[l1_idx + 1:l2_idx]
            if not middle_slice:
                continue
            h_rel = int(np.argmax(middle_slice))
            h_idx = l1_idx + 1 + h_rel
            middle_high = float(highs[h_idx])
            atr_l1 = float(df.iloc[l1_idx]['atr20']) if pd.notna(df.iloc[l1_idx]['atr20']) else 0.0
            atr_h = float(df.iloc[h_idx]['atr20']) if pd.notna(df.iloc[h_idx]['atr20']) else 0.0
            rise_pct = middle_high / l1 - 1.0
            pullback_pct = 1.0 - l2 / middle_high if middle_high > 0 else 0.0
            rise_atr = (middle_high - l1) / atr_l1 if atr_l1 > 0 else 0.0
            pullback_atr = (middle_high - l2) / atr_h if atr_h > 0 else 0.0
            rise_clear = rise_pct >= 0.03 or rise_atr >= 0.8
            pullback_clear = pullback_pct >= 0.025 or pullback_atr >= 0.6
            if not rise_clear or not pullback_clear:
                continue

            # L2 后的确认也只能使用 as_of_idx 及之前的数据；不要求站回3MA。
            confirm_idx: int | None = None
            for j in range(l2_idx + 1, as_of_idx + 1):
                close_j = closes[j]
                ma5_j = df.iloc[j]['ma5']
                close_above_ma5 = pd.notna(ma5_j) and close_j > float(ma5_j)
                recent_close_high = close_j >= max(closes[max(l2_idx + 1, j - 2):j]) if j > l2_idx + 1 else False
                rebound_half_atr = atr_l2 = float(df.iloc[l2_idx]['atr20']) if pd.notna(df.iloc[l2_idx]['atr20']) else 0.0
                rebound_half_atr = atr_l2 > 0 and (close_j - l2) / atr_l2 >= 0.5
                if close_above_ma5 or recent_close_high or rebound_half_atr:
                    confirm_idx = j
                    break
            if confirm_idx is None:
                continue
            confirm_idx = max(confirm_idx, l2_idx + 2)
            age = as_of_idx - confirm_idx
            if confirmed_after and str(df.iloc[confirm_idx]['trade_date']) <= confirmed_after:
                continue
            if age > ACTIVE_BARS_AFTER_CONFIRMATION:
                continue

            clear = l2 >= l1 and rise_clear and pullback_clear
            candidate = {
                'bottom_structure_type': 'MICRO_DOUBLE_BOTTOM' if gap < DAILY_MIN_GAP else 'STANDARD_DOUBLE_BOTTOM',
                'bottom_structure_quality': 'CLEAR' if clear else 'POSSIBLE',
                'bottom_structure_strength': 2 if clear else 1,
                'bottom_first_low_date': str(df.iloc[l1_idx]['trade_date']),
                'bottom_second_low_date': str(df.iloc[l2_idx]['trade_date']),
                'bottom_structure_confirmed_date': str(df.iloc[confirm_idx]['trade_date']),
                'bottom_first_low': round(l1, 6),
                'bottom_middle_high': round(middle_high, 6),
                'bottom_second_low': round(l2, 6),
                'bottom_low_gap_bars': gap,
                'bottom_structure_age_bars': age,
            }
            # 较短候选不能阻止继续检查同一个第二底之前的日线双底。
            if candidate['bottom_structure_type'] == 'STANDARD_DOUBLE_BOTTOM':
                return candidate
            if not candidates:
                candidates.append(candidate)
    return candidates[0] if candidates else none


@dataclass
class EarlyTurnService:
    store: PostgresScreeningStore
    engine: EarlyTurnEngine = EarlyTurnEngine()

    def calculate_features_from_bars(
        self,
        ts_code: str,
        target_date: str,
        *,
        history_start_date: str | None = None,
        replay_start_date: str | None = None,
    ) -> dict[str, Any]:
        """以目标日为截止回放生命周期；可选限定行情热身起点与生命周期起点。

        原始行情仍保存在 screening_daily_bar；技术指标不能直接使用原始价，
        否则除权除息日会被误判为暴跌、破位或生命周期结束。这里使用
        ``close * adj_factor``，相对于评估日只是一个统一缩放，既保持
        Point-in-Time 口径，也不会引入未来价格信息。

        ``history_start_date`` 仅用于读取滚动指标所需的热身数据；
        ``replay_start_date`` 用于从指定日重新初始化并回放生命周期。
        """
        if (history_start_date is None) != (replay_start_date is None):
            raise ValueError("窗口回放必须同时提供行情起点和生命周期起点")
        normalized_target_date = str(target_date).replace("-", "")
        normalized_history_start = str(history_start_date).replace("-", "") if history_start_date else None
        normalized_replay_start = str(replay_start_date).replace("-", "") if replay_start_date else None
        history_start_clause = "and b.trade_date >= %s" if normalized_history_start else ""
        query_params = (
            (ts_code, normalized_target_date, normalized_history_start)
            if normalized_history_start
            else (ts_code, normalized_target_date)
        )
        with self.store.connect() as conn:
            rows = conn.execute(
                f"""
                select b.trade_date, b.open, b.high, b.low, b.close, b.vol, b.amount,
                       a.adj_factor
                from screening_daily_bar b
                join screening_adj_factor a
                  on a.asset_code = b.asset_code and a.trade_date = b.trade_date
                where b.asset_code = %s and b.trade_date <= %s
                  and a.adj_factor > 0
                  {history_start_clause}
                order by trade_date desc
                """,
                query_params,
            ).fetchall()

        if not rows:
            return {"data_status": "DATA_MISSING", "data_reason": "未读取到有效前复权日K"}

        df = pd.DataFrame([dict(r) for r in reversed(rows)])
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
        # 与下方最终日统计一致：10 根 K 线内包含 9 个相邻交易日交叉。
        # 每一行只依赖该行及以前的数据，供生命周期逐日回放使用。
        pair_crosses = []
        for p1, p2 in pairs:
            a, b = df[f'ma{p1}'], df[f'ma{p2}']
            valid = a.notna() & b.notna() & a.shift(1).notna() & b.shift(1).notna()
            crossed = valid & ((a > b) != (a.shift(1) > b.shift(1)))
            pair_crosses.append(crossed.rolling(9, min_periods=1).max())
        df['cross_pair_count_10d'] = sum(pair_crosses).astype(int)
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

        # ── 双底结构诊断（仅 Point-in-Time 诊断，不参与评分/状态） ─────────────
        # 局部低点必须等右侧两根日K出现后才能确认，避免在历史回放中把未来
        # 数据带回低点当天。低点日期和结构确认日期因此始终分开保存。
        bottom_structure = detect_bottom_structure(df, idx)

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
        pre_entry_reason: str | None = None
        pre_confirm_date: str | None = None
        pre_invalid_days = 0
        pre_failure_days = 0
        episode_base_low_for_pre: float | None = None
        episode_base_low_for_pre_date: str | None = None
        episode_base_atr_for_pre: float | None = None
        decline_context_active = False
        decline_context_idx: int | None = None
        decline_context_date: str | None = None
        decline_context_peak: float | None = None
        decline_context_low: float | None = None
        post_enter_idx: int | None = None
        post_enter_date: str | None = None
        max_close_since_trigger = 0.0
        max_high_since_trigger = 0.0
        pre_trigger_stage_low: float | None = None
        # 基准低点是本轮 Episode 的起点，不是首次触发确认点。一旦触发后
        # 固定，避免后续回放时低点随窗口移动而漂移。
        episode_base_low: float | None = None
        episode_base_low_date: str | None = None
        episode_base_low_idx: int | None = None
        episode_base_atr20: float | None = None
        first_wave_high_close: float | None = None
        first_wave_high_date: str | None = None
        first_wave_high: float | None = None
        first_wave_high_intraday_date: str | None = None
        first_wave_formed = False
        first_wave_formation_bars: int | None = None
        first_wave_gain = 0.0
        first_wave_gain_atr = 0.0
        drawdown_from_first_wave_high = 0.0
        below_ma30_days = 0
        below_ma60_days = 0
        # 最近结束周期的审计信息与活动周期独立，供单股报告追溯。
        last_closed_episode: dict[str, Any] | None = None
        post_reset_waiting_for_pre = False

        def clear_episode(*, preserve_decline_context: bool = False) -> None:
            """在确认新 PRE 起点时清空上一轮 Episode 的内部锚点。"""
            nonlocal first_trigger_idx, first_trigger_date, first_trigger_close, first_trigger_atr20
            nonlocal max_close_since_trigger, max_high_since_trigger, pre_trigger_stage_low
            nonlocal episode_base_low, episode_base_low_date, episode_base_low_idx, episode_base_atr20
            nonlocal first_wave_high_close, first_wave_high_date, first_wave_high
            nonlocal first_wave_high_intraday_date, first_wave_formed, first_wave_formation_bars
            nonlocal below_ma30_days, below_ma60_days
            nonlocal pre_entry_reason, pre_confirm_date
            nonlocal pre_failure_days, episode_base_low_for_pre
            nonlocal episode_base_low_for_pre_date, episode_base_atr_for_pre
            nonlocal decline_context_active, decline_context_idx
            nonlocal decline_context_date, decline_context_peak, decline_context_low

            pre_entry_reason = None
            pre_confirm_date = None
            first_trigger_idx = None
            first_trigger_date = None
            first_trigger_close = None
            first_trigger_atr20 = None
            max_close_since_trigger = 0.0
            max_high_since_trigger = 0.0
            pre_trigger_stage_low = None
            episode_base_low = None
            episode_base_low_date = None
            episode_base_low_idx = None
            episode_base_atr20 = None
            first_wave_high_close = None
            first_wave_high_date = None
            first_wave_high = None
            first_wave_high_intraday_date = None
            first_wave_formed = False
            first_wave_formation_bars = None
            below_ma30_days = 0
            below_ma60_days = 0
            pre_failure_days = 0
            episode_base_low_for_pre = None
            episode_base_low_for_pre_date = None
            episode_base_atr_for_pre = None
            if not preserve_decline_context:
                decline_context_active = False
                decline_context_idx = None
                decline_context_date = None
                decline_context_peak = None
                decline_context_low = None

        def enter_pre(k: int, row: pd.Series, atr: float, reason: str = 'CONFIRMED_MA_REPAIR') -> None:
            nonlocal turn_episode_state, pre_enter_idx, pre_enter_date, pre_invalid_days, pre_failure_days
            nonlocal pre_entry_reason, pre_confirm_date
            nonlocal episode_base_low_for_pre, episode_base_low_for_pre_date, episode_base_atr_for_pre
            turn_episode_state = 'PRE_FIRST_TURN'
            pre_enter_idx, pre_enter_date = k, str(row['trade_date'])
            pre_entry_reason = reason
            pre_confirm_date = pre_enter_date if reason == 'CONFIRMED_MA_REPAIR' else None
            pre_invalid_days = pre_failure_days = 0
            base_window = df.iloc[max(0, k - EPISODE_BASE_LOOKBACK_BARS):k]
            if len(base_window):
                base_row = df.loc[base_window['low'].idxmin()]
                episode_base_low_for_pre = float(base_row['low'])
                episode_base_low_for_pre_date = str(base_row['trade_date'])
                episode_base_atr_for_pre = float(base_row['atr20']) if pd.notna(base_row['atr20']) and float(base_row['atr20']) > 0 else atr

        def closed_episode(k: int, reason: str, signals: list[str]) -> dict[str, Any]:
            return {
                'pre_enter_date': pre_enter_date,
                'pre_entry_reason': pre_entry_reason,
                'pre_confirm_date': pre_confirm_date,
                'first_trigger_date': first_trigger_date,
                'episode_base_low': episode_base_low,
                'post_enter_date': post_enter_date,
                'end_date': str(df.iloc[k]['trade_date']),
                'end_reason': reason,
                'end_signals': signals,
            }

        def pre_qualification_diagnostics(k: int, row: pd.Series) -> dict[str, Any]:
            """逐项计算现行 PRE 入口条件；数据缺失明确标为不可判断。"""
            context = bool(decline_context_active and decline_context_idx is not None
                           and k - decline_context_idx <= DECLINE_CONTEXT_MAX_AGE_BARS)
            result: dict[str, Any] = {
                'decline_context': context, 'ma5_confirmed': None, 'ma10_confirmed': None,
                'ma10_slope_5d': None, 'ma10_slope_prev5': None,
                'retake_count': int(row['retake_count']), 'price_retake': bool(pd.notna(row['ma5']) and pd.notna(row['ma10']) and float(row['close']) > float(row['ma5']) and float(row['close']) > float(row['ma10'])),
                'compressed': None, 'cross_repair': None, 'repair_context': None,
                'indicators_available': False, 'eligible': False,
            }
            if k < 13:
                return result
            prev5, prev10 = df.iloc[k - 5], df.iloc[k - 10]
            atr = float(row['atr20']) if pd.notna(row['atr20']) and float(row['atr20']) > 0 else 0.0
            if atr <= 0:
                return result

            def pct_between(newer: Any, older: Any) -> float | None:
                if pd.isna(newer) or pd.isna(older) or float(older) == 0:
                    return None
                return float(newer / older - 1.0)

            ma10_now = pct_between(row['ma10'], prev5['ma10'])
            ma20_now = pct_between(row['ma20'], prev5['ma20'])
            ma10_prev = pct_between(prev5['ma10'], prev10['ma10'])
            ma20_prev = pct_between(prev5['ma20'], prev10['ma20'])
            if None in (ma10_now, ma20_now, ma10_prev, ma20_prev):
                return result
            spread = calc_min_3ma_spread(row)
            compressed = spread is not None and float(spread) / atr <= 1.6
            cross_repair = int(row.get('cross_pair_count_10d', 0) or 0) >= 1
            slopes = [pct_between(df.iloc[i]['ma5'], df.iloc[i - 3]['ma5']) for i in range(k - 2, k + 1)]
            ma5_flat = (all(slope is not None for slope in slopes)
                        and sum(slope >= -0.005 for slope in slopes if slope is not None) >= 2
                        and slopes[-1] >= -0.01)
            ma10_recent = [df.iloc[i]['ma10'] for i in range(k - MA10_RECOVERY_DAYS, k + 1)]
            ma10_recent_valid = all(pd.notna(v) and float(v) > 0 for v in ma10_recent)
            ma10_six = [df.iloc[i]['ma10'] for i in range(k - 5, k + 1)]
            ma10_recent_repair = bool(ma10_recent_valid and ma10_recent[-1] >= ma10_recent[0]
                and all(pd.notna(v) and float(v) > 0 for v in ma10_six)
                and max(ma10_six) / min(ma10_six) - 1 <= MA10_RECOVERY_RANGE_5D
                and sum(ma10_recent[i] >= ma10_recent[i - 1] for i in range(1, len(ma10_recent))) >= MA10_RECOVERY_MIN_UP_DAYS)
            ma10_2d = pct_between(row['ma10'], df.iloc[k - 2]['ma10'])
            ma10_prev_2d = pct_between(df.iloc[k - 2]['ma10'], df.iloc[k - 4]['ma10'])
            ma10_daily = pct_between(row['ma10'], df.iloc[k - 1]['ma10'])
            ma10_deceleration = bool(ma10_2d is not None and ma10_prev_2d is not None
                and ma10_daily is not None and ma10_daily >= MA10_DECELERATION_DAILY_MIN
                and ma10_2d > ma10_prev_2d and ma10_now > ma10_prev)
            ma10_flat = (ma10_now >= -0.01 and ma10_now >= ma10_prev) or ma10_recent_repair or ma10_deceleration
            repair_context = compressed or cross_repair
            ma5_values = [df.iloc[i]['ma5'] for i in range(k - ROUNDED_SLOPE_LOOKBACK_BARS, k + 1)]
            shape = rounded_ma5_shape([float(v) for v in ma5_values])
            result.update({
                'ma5_confirmed': bool(ma5_flat), 'ma5_slopes_3d': slopes,
                'ma5_rounded': bool(shape['ma5_rounded']),
                'ma10_confirmed': bool(ma10_flat), 'ma10_slope_5d': ma10_now,
                'ma10_recent_repair': ma10_recent_repair,
                'ma10_deceleration': ma10_deceleration,
                'ma10_slope_prev5': ma10_prev, 'compressed': bool(compressed),
                'cross_repair': bool(cross_repair), 'repair_context': bool(repair_context),
                'indicators_available': True,
                'eligible': bool(context and shape['ma5_rounded'] and ma10_flat and result['price_retake'] and repair_context),
            })
            return result

        def has_pre_qualification(k: int, row: pd.Series, *, early_observation: bool = False) -> bool:
            if (k < 13 or not decline_context_active or decline_context_idx is None
                    or k - decline_context_idx > DECLINE_CONTEXT_MAX_AGE_BARS):
                return False
            details = pre_qualification_diagnostics(k, row)
            if not early_observation:
                return details['eligible']
            return bool(details['indicators_available'] and details['decline_context']
                        and details['ma5_confirmed'] and details['price_retake']
                        and details['repair_context']
                        and (details['ma10_confirmed'] or details['ma10_slope_5d'] >= -0.025))

        def rounded_repair_diagnostics(k: int, row: pd.Series) -> dict[str, Any]:
            info: dict[str, Any] = {'eligible': False, 'indicators_available': False}
            if k < ROUNDED_SLOPE_LOOKBACK_BARS:
                return info
            ma5 = [df.iloc[i]['ma5'] for i in range(k - ROUNDED_SLOPE_LOOKBACK_BARS, k + 1)]
            ma10 = [df.iloc[i]['ma10'] for i in (k - 2, k - 1, k)]
            if any(pd.isna(v) or float(v) <= 0 for v in ma5 + ma10):
                return info
            shape = rounded_ma5_shape([float(v) for v in ma5])
            ma10_slope_now = float(ma10[-1] / ma10[-2] - 1)
            ma10_slope_prev = float(ma10[-2] / ma10[-3] - 1)
            ma10_repair = ma10_slope_now >= 0 or ma10_slope_now > ma10_slope_prev
            background = bool(decline_context_active and decline_context_idx is not None
                              and k - decline_context_idx <= DECLINE_CONTEXT_MAX_AGE_BARS)
            above_short_ma = float(row['close']) > float(row['ma5']) and float(row['close']) > float(row['ma10'])
            info.update(shape)
            qualification = pre_qualification_diagnostics(k, row)
            info.update({'indicators_available': True, 'decline_context': background,
                         'ma10_repair': bool(ma10_repair), 'ma10_daily_slope': ma10_slope_now,
                         'above_ma5_ma10': bool(above_short_ma),
                         'eligible': bool(qualification['eligible'])})
            return info

        # 默认从完整历史的正式评估起点回放。窗口实验会在保留指标热身数据后，
        # 从指定的 60 交易日前重新初始化生命周期；每个目标日仍须有至少 80 根行情。
        start_eval_bar = max(EPISODE_WARMUP_BARS, MIN_VALID_HISTORY_BARS - 1)
        lifecycle_history_floor = 0
        if normalized_replay_start is not None:
            replay_positions = df.index[df['trade_date'].astype(str) == normalized_replay_start].tolist()
            if len(replay_positions) != 1:
                return {
                    "data_status": "REPLAY_START_MISSING",
                    "data_reason": f"生命周期回放起点 {normalized_replay_start} 未找到有效前复权日K",
                    "valid_bar_count": len(df),
                }
            start_eval_bar = int(replay_positions[0])
            lifecycle_history_floor = start_eval_bar
        observation_first_date: str | None = None
        early_observation: dict[str, Any] = {"active": False, "first_date": None, "version": "A1_OBSERVATION_V1"}

        def update_early_observation(k: int, row: pd.Series) -> None:
            nonlocal observation_first_date, early_observation
            active = (turn_episode_state == "OUTSIDE_A_PRE"
                      and not has_pre_qualification(k, row)
                      and has_pre_qualification(k, row, early_observation=True))
            if not active:
                observation_first_date = None
                early_observation = {"active": False, "first_date": None, "version": "A1_OBSERVATION_V1"}
                return
            if observation_first_date is None:
                observation_first_date = str(row['trade_date'])
            atr = float(row['atr20'])
            spread = calc_min_3ma_spread(row)
            early_observation = {
                "active": True,
                "version": "A1_OBSERVATION_V1",
                "first_date": observation_first_date,
                "ma5": float(row['ma5'] / row['adj_factor']),
                "ma10": float(row['ma10'] / row['adj_factor']),
                "ma5_slope_3d": float(row['ma5'] / df.iloc[k - 3]['ma5'] - 1),
                "ma10_slope_5d": float(row['ma10'] / df.iloc[k - 5]['ma10'] - 1),
                "retake_count": int(row['retake_count']),
                "compressed": bool(spread is not None and float(spread) / atr <= 1.6),
                "cross_repair": bool(int(row.get('cross_pair_count_10d', 0) or 0) >= 1),
            }

        for k in range(start_eval_bar, len(df)):
            try:
                row_k = df.iloc[k]
                close_k = float(row_k['close'])
                low_k = float(row_k['low'])
                retake_k = int(row_k['retake_count'])
                atr_k = float(row_k['atr20']) if pd.notna(row_k['atr20']) else close_k * 0.03

                m5_k, m10_k = row_k['ma5'], row_k['ma10']
                order_score_k = calc_order_score(row_k)

                # 下跌背景是历史事件，不是每天重新计算的当前距离高点。事件在
                # 策略外最多保留 60 根；一旦进入 PRE，就随本轮 Episode 固定。
                decline_window = df.iloc[max(lifecycle_history_floor, k - DECLINE_CONTEXT_LOOKBACK_BARS):k]
                decline_peak_k = float(decline_window['high'].max()) if len(decline_window) else 0.0
                decline_event = bool(
                    decline_peak_k > 0
                    and (decline_peak_k - close_k) / decline_peak_k >= PRE_MIN_DECLINE_FROM_60D_HIGH
                )
                if decline_event:
                    decline_context_active = True
                    decline_context_idx = k
                    decline_context_date = str(row_k['trade_date'])
                    decline_context_peak = decline_peak_k
                    decline_context_low = low_k
                elif (
                    decline_context_active
                    and decline_context_idx is not None
                    and k - decline_context_idx > DECLINE_CONTEXT_MAX_AGE_BARS
                    and turn_episode_state == "OUTSIDE_A_PRE"
                ):
                    decline_context_active = False
                    decline_context_idx = None
                    decline_context_date = None
                    decline_context_peak = None
                    decline_context_low = None

                if turn_episode_state == "OUTSIDE_A_PRE":
                    if has_pre_qualification(k, row_k):
                        enter_pre(k, row_k, atr_k, 'EARLY_ROUNDED_REPAIR')
                    continue

                if turn_episode_state == "PRE_FIRST_TURN" and first_trigger_idx is None:
                    if (pre_entry_reason == 'EARLY_ROUNDED_REPAIR' and pre_confirm_date is None
                            and close_k < float(m5_k) and close_k < float(m10_k)):
                        last_closed_episode = closed_episode(k, 'EARLY_REPAIR_FAILURE', ['BELOW_MA5_MA10'])
                        clear_episode(preserve_decline_context=True)
                        turn_episode_state = 'OUTSIDE_A_PRE'
                        pre_enter_idx = None
                        pre_enter_date = None
                        continue
                    confirmation = pre_qualification_diagnostics(k, row_k)
                    if (pre_confirm_date is None and confirmation['decline_context']
                            and confirmation['ma5_confirmed'] and confirmation['ma10_confirmed']
                            and confirmation['price_retake'] and confirmation['repair_context']):
                        pre_confirm_date = str(row_k['trade_date'])
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
                        and close_k > float(m5_k) and close_k > float(m10_k)
                        and pd.notna(df.iloc[k - 3]['ma5']) and pd.notna(df.iloc[k - 3]['ma10'])
                        and float(m5_k) > float(df.iloc[k - 3]['ma5'])
                        and float(m10_k) > float(df.iloc[k - 3]['ma10'])
                        and pd.notna(row_k['ma20']) and pd.notna(df.iloc[k - 5]['ma20'])
                        and float(df.iloc[k - 5]['ma20']) > 0
                        and float(row_k['ma20'] / df.iloc[k - 5]['ma20'] - 1) >= FIRST_MA20_5D_MIN_SLOPE
                    ):
                        # 触发日前最近 40 个交易日的阶段低点；不把触发当天低点
                        # 纳入，以保持“本轮 PRE 形成过程”的起点语义。
                        # 预热区不参与状态迁移，但可以作为本轮启动前的背景，
                        # 否则恰好在第一个可评估日触发时会没有可用的阶段低点。
                        base_start = max(lifecycle_history_floor, k - EPISODE_BASE_LOOKBACK_BARS)
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
                        episode_base_low_idx = int(base_low_idx)
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
                        first_wave_formed = first_wave_meets_criteria(first_wave_gain, first_wave_gain_atr)
                        first_wave_formation_bars = k - episode_base_low_idx if first_wave_formed else None
                        below_ma30_days = 0
                        below_ma60_days = 0
                        pre_trigger_stage_low = (
                            float(df.iloc[lifecycle_history_floor:k]['low'].min()) if k > lifecycle_history_floor else None
                        )
                        turn_episode_state = "FIRST_TURN_WINDOW"
                        continue

                    # PRE 的退出不能复用入口资格。只有底部结构真正失效时才退出：
                    # 重新明显跌破本轮底部，或出现新低并伴随 MA10/MA20 再次加速下行。
                    prev5 = df.iloc[k - 5]
                    prev10 = df.iloc[k - 10]
                    ma10_now = float(row_k['ma10'] / prev5['ma10'] - 1.0) if pd.notna(row_k['ma10']) and pd.notna(prev5['ma10']) and float(prev5['ma10']) else 0.0
                    ma20_now = float(row_k['ma20'] / prev5['ma20'] - 1.0) if pd.notna(row_k['ma20']) and pd.notna(prev5['ma20']) and float(prev5['ma20']) else 0.0
                    ma10_prev = float(prev5['ma10'] / prev10['ma10'] - 1.0) if pd.notna(prev5['ma10']) and pd.notna(prev10['ma10']) and float(prev10['ma10']) else 0.0
                    ma20_prev = float(prev5['ma20'] / prev10['ma20'] - 1.0) if pd.notna(prev5['ma20']) and pd.notna(prev10['ma20']) and float(prev10['ma20']) else 0.0
                    reaccelerating = (
                        ma10_now <= PRE_FAILURE_REACCEL_SLOPE
                        and ma20_now <= PRE_FAILURE_REACCEL_SLOPE
                        and ma10_now < ma10_prev
                        and ma20_now < ma20_prev
                    )
                    broke_episode_base = (
                        episode_base_low_for_pre is not None
                        and low_k < episode_base_low_for_pre
                    )
                    pre_structural_failure = broke_episode_base and reaccelerating
                    if pre_structural_failure:
                        pre_failure_days += 1
                    else:
                        pre_failure_days = 0
                    if pre_failure_days >= PRE_FAILURE_CONFIRM_BARS:
                        turn_episode_state = "OUTSIDE_A_PRE"
                        pre_enter_idx = None
                        pre_enter_date = None
                        pre_invalid_days = 0
                        pre_failure_days = 0
                        episode_base_low_for_pre = None
                        episode_base_low_for_pre_date = None
                        episode_base_atr_for_pre = None
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
                    if not first_wave_formed and first_wave_meets_criteria(first_wave_gain, first_wave_gain_atr):
                        first_wave_formed = True
                        first_wave_formation_bars = k - episode_base_low_idx if episode_base_low_idx is not None else None

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
                            failed_signals = []
                            if (first_trigger_close > 0
                                    and close_k <= first_trigger_close * (1.0 - TURN_FAILURE_TRIGGER_DRAWDOWN)):
                                failed_signals.append('TRIGGER_DRAWDOWN_12_PERCENT')
                            if episode_base_low is not None and close_k < episode_base_low:
                                failed_signals.append('BROKE_EPISODE_BASE')
                            if pre_trigger_stage_low is not None and close_k < pre_trigger_stage_low:
                                failed_signals.append('BROKE_PRE_TRIGGER_LOW')
                            # 第一波尚未形成时，收盘跌回 MA5、MA10 下方且低于触发价，
                            # 视为这次转强尝试失败。不会把历史 FIRST 改写成 PRE；
                            # 结束后需重新通过 PRE 资格，才能开启下一轮准备。
                            if (first_trigger_close > 0 and close_k < first_trigger_close
                                    and pd.notna(row_k['ma5']) and pd.notna(row_k['ma10'])
                                    and close_k < float(row_k['ma5']) and close_k < float(row_k['ma10'])):
                                failed_signals.append('LOST_MA5_MA10_BEFORE_FIRST_WAVE')
                            turn_failed = bool(failed_signals)
                            if turn_failed:
                                last_closed_episode = closed_episode(k, 'FIRST_TURN_FAILURE', failed_signals)
                                clear_episode(preserve_decline_context=True)
                                turn_episode_state = "OUTSIDE_A_PRE"
                                pre_enter_idx = None
                                pre_enter_date = None
                                pre_invalid_days = 0
                                continue

                    elif turn_episode_state == "POST_FIRST_WAVE":
                        # 接近旧底只是回调观察，不等同破位。旧周期只在收盘
                        # 有效跌破旧底，或极端且持续的结构破坏时提前结束。
                        below_ma30_days = below_ma30_days + 1 if m30_k > 0 and close_k < m30_k else 0
                        below_ma60_days = below_ma60_days + 1 if m60_k > 0 and close_k < m60_k else 0
                        prior_60_lows = df.iloc[max(lifecycle_history_floor, k - 60):k]['low']
                        is_new_60d_low = bool(
                            len(prior_60_lows) > 0 and low_k <= float(prior_60_lows.min())
                        )
                        trigger_zone_broken = first_trigger_close > 0 and close_k < first_trigger_close * 0.92
                        structural_drawdown_pct = (
                            (max_high_since_trigger - close_k) / max_high_since_trigger
                            if max_high_since_trigger > 0 else 0.0
                        )
                        prolonged_medium_break = below_ma30_days >= 10 or below_ma60_days >= 5
                        extreme_protracted_break = structural_drawdown_pct >= 0.35 and prolonged_medium_break
                        effective_base_break = episode_base_low is not None and close_k < episode_base_low * (1 - SECOND_BASE_BREAK_TOLERANCE)
                        if trigger_zone_broken and (effective_base_break or extreme_protracted_break):
                            signals = [name for name, hit in (
                                ('NEW_60D_LOW', is_new_60d_low),
                                ('EFFECTIVE_BASE_BREAK', effective_base_break),
                                ('EXTREME_PROTRACTED_BREAK', extreme_protracted_break),
                            ) if hit]
                            last_closed_episode = closed_episode(k, 'STRUCTURAL_FAILURE', signals)
                            clear_episode(preserve_decline_context=True)
                            turn_episode_state = 'OUTSIDE_A_PRE'
                            pre_enter_idx = None
                            pre_enter_date = None
                            post_enter_idx = None
                            post_enter_date = None
                            continue

                        # 先记录结构性失效，再判断自然冷却到期；同日发生时
                        # 保留更具体的失效原因。
                        if post_enter_idx is not None and k - post_enter_idx >= POST_COOLDOWN_BARS:
                            qualifies_for_pre = has_pre_qualification(k, row_k)
                            last_closed_episode = closed_episode(k, 'POST_COOLDOWN_EXPIRED', [])
                            clear_episode(preserve_decline_context=True)
                            if qualifies_for_pre:
                                enter_pre(k, row_k, atr_k, 'EARLY_ROUNDED_REPAIR')
                            else:
                                turn_episode_state = 'OUTSIDE_A_PRE'
                                pre_enter_idx = None
                                pre_enter_date = None
                            post_enter_idx = None
                            post_enter_date = None
                            continue

            finally:
                update_early_observation(k, row_k)

        # 早期 PRE 失败后，重新查找失败之后确认的有效结构，不沿用旧证据。
        if last_closed_episode and last_closed_episode.get('end_reason') == 'EARLY_REPAIR_FAILURE':
            bottom_structure = detect_bottom_structure(df, idx, confirmed_after=last_closed_episode['end_date'])

        # Episode 最终快照字段：供单股回放、批量快照与诊断导出共同使用。
        second_base, second_first_idx, second_post_idx = episode_base_low, first_trigger_idx, post_enter_idx
        if turn_episode_state != 'POST_FIRST_WAVE':
            second_base = second_first_idx = second_post_idx = None
            if (turn_episode_state == 'OUTSIDE_A_PRE' and last_closed_episode
                    and last_closed_episode.get('end_reason') == 'POST_COOLDOWN_EXPIRED'):
                second_base = last_closed_episode.get('episode_base_low')
                index_by_date = {str(d): i for i, d in enumerate(df['trade_date'])}
                second_first_idx = index_by_date.get(str(last_closed_episode.get('first_trigger_date')))
                second_post_idx = index_by_date.get(str(last_closed_episode.get('post_enter_date')))
        second_opportunity = detect_second_opportunity(df, base_low=second_base, first_idx=second_first_idx, post_idx=second_post_idx)
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
            'early_observation': early_observation,
            'second_opportunity': second_opportunity,
            'pre_qualification': pre_qualification_diagnostics(len(df) - 1, curr),
            'episode_replay_start_date': (
                str(df.iloc[start_eval_bar]['trade_date'])
                if normalized_replay_start else str(df.iloc[0]['trade_date'])
            ),
            'episode_replay_data_start_date': str(df.iloc[0]['trade_date']),
            'episode_replay_mode': 'WINDOWED_60_TRADING_DAYS' if normalized_replay_start else 'FULL_HISTORY',
            'episode_replay_first_evaluation_date': str(df.iloc[start_eval_bar]['trade_date']),
            'episode_replay_version': EARLY_TURN_CONFIG_VERSION,
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
            'first_wave_formation_bars': first_wave_formation_bars,
            'first_wave_speed': ('FAST' if first_wave_formation_bars <= FIRST_WAVE_FAST_MAX_BARS else 'NORMAL') if first_wave_formation_bars is not None else None,
            'post_reset_waiting_for_pre': post_reset_waiting_for_pre,
            'last_closed_episode': last_closed_episode,
            'pre_enter_date': pre_enter_date,
            'pre_entry_reason': pre_entry_reason if turn_episode_state != 'OUTSIDE_A_PRE' else None,
            'pre_confirm_date': pre_confirm_date if turn_episode_state != 'OUTSIDE_A_PRE' else None,
            'rounded_repair': rounded_repair_diagnostics(len(df) - 1, curr),
            'pre_episode_base_low': episode_base_low_for_pre,
            'pre_episode_base_low_date': episode_base_low_for_pre_date,
            'decline_context_active': decline_context_active,
            'decline_context_date': decline_context_date,
            'decline_context_peak': decline_context_peak,
            'decline_context_low': decline_context_low,
            'post_enter_date': post_enter_date,
            'drawdown_from_first_wave_high': drawdown_from_first_wave_high,
            'cross_down_ma30': cross_down_ma30,
            **bottom_structure,
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
        if config_version != EARLY_TURN_CONFIG_VERSION:
            raise ValueError(f"当前策略版本为 {EARLY_TURN_CONFIG_VERSION}，不能使用 {config_version} 标记新结果")
        rerun_codes: list[str] = []
        if run_id:
            # 历史批次只读：重新评估复用原股票范围，写入全新批次。
            with self.store.connect() as conn:
                previous = conn.execute("select run_name, notes from early_turn_run where run_id = %s", (run_id,)).fetchone()
                if not previous:
                    raise ValueError(f"找不到选股批次：{run_id}")
                rerun_codes = [r['ts_code'] for r in conn.execute(
                    "select ts_code from early_turn_result where run_id = %s order by ts_code", (run_id,)
                ).fetchall()]
                if not rerun_codes:
                    raise ValueError("原批次没有可重新评估的股票")
                run_name = run_name or f"{previous['run_name'] or trade_date} 重新评估"
                notes = notes or previous['notes']
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

                res = self.engine.evaluate_stock(code, trade_date, feat, prep_score_mode="rounded")
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

            eval_res = self.engine.evaluate_stock(ts_code, t_date, feat, prep_score_mode="rounded")
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
        stock_input = ts_code.strip()
        if not stock_input:
            raise ValueError("请输入股票名称或代码")
        normalized = stock_input.upper()
        with self.store.connect() as conn:
            if normalized.isdigit():
                matches = conn.execute(
                    "select asset_code, name, raw_json->>'industry' as industry from screening_asset_master "
                    "where asset_type = 'stock' and split_part(asset_code, '.', 1) = %s order by asset_code",
                    (normalized,),
                ).fetchall()
            elif normalized.endswith((".SH", ".SZ", ".BJ")):
                matches = conn.execute(
                    "select asset_code, name, raw_json->>'industry' as industry from screening_asset_master "
                    "where asset_type = 'stock' and asset_code = %s order by asset_code",
                    (normalized,),
                ).fetchall()
            else:
                matches = conn.execute(
                    "select asset_code, name, raw_json->>'industry' as industry from screening_asset_master "
                    "where asset_type = 'stock' and name = %s order by asset_code",
                    (stock_input,),
                ).fetchall()
        if not matches:
            raise ValueError(f"未找到股票“{stock_input}”，请输入完整名称或代码")
        if len(matches) != 1:
            choices = '、'.join(f"{row['name']}（{row['asset_code']}）" for row in matches)
            raise ValueError(f"“{stock_input}”匹配到多只股票：{choices}。请输入完整股票代码")
        stock = matches[0]
        clean_code = stock['asset_code']
        name = stock['name'] or clean_code
        industry = stock['industry'] or "未知行业"

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

            # 生命周期从所选窗口前 60 个交易日开始；再向前读取 120 根指标热身行情，
            # 覆盖 MA60 与 120 日背景字段。热身行情不参与窗口前的生命周期继承。
            prior_rows = conn.execute(
                """
                select b.trade_date
                from screening_daily_bar b
                join screening_adj_factor a
                  on a.asset_code = b.asset_code and a.trade_date = b.trade_date
                where b.asset_code = %s and b.trade_date < %s and a.adj_factor > 0
                order by b.trade_date desc
                limit %s
                """,
                (clean_code, s_date, SINGLE_TEST_INDICATOR_WARMUP_BARS),
            ).fetchall()

        if len(prior_rows) != SINGLE_TEST_INDICATOR_WARMUP_BARS:
            raise ValueError(
                f"窗口回放需要区间开始日前 {SINGLE_TEST_INDICATOR_WARMUP_BARS} 根有效前复权日线，"
                f"当前仅有 {len(prior_rows)} 根；未改用更短窗口"
            )
        replay_start_date = str(prior_rows[SINGLE_TEST_LIFECYCLE_LOOKBACK_BARS - 1]['trade_date'])
        history_start_date = str(prior_rows[SINGLE_TEST_INDICATOR_WARMUP_BARS - 1]['trade_date'])

        history = []
        for r in rows:
            d = r["trade_date"]
            close_p = float(r["close"])
            feat = self.calculate_features_from_bars(
                clean_code,
                d,
                history_start_date=history_start_date,
                replay_start_date=replay_start_date,
            )
            if feat.get('data_status'):
                raise ValueError(f"{clean_code} {d} 窗口回放失败：{feat.get('data_reason', feat['data_status'])}")
            feat["name"] = name
            feat["industry"] = industry
            eval_res = self.engine.evaluate_stock(clean_code, d, feat, prep_score_mode="rounded")
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
                "early_observation": feat.get("early_observation"),
                "second_opportunity": feat.get("second_opportunity"),
                "pre_qualification": feat.get("pre_qualification"),
                "rounded_repair": feat.get("rounded_repair"),
                "pre_enter_date": feat.get("pre_enter_date"),
                "pre_entry_reason": feat.get("pre_entry_reason"),
                "pre_confirm_date": feat.get("pre_confirm_date"),
                "retake_count": (eval_res.get("score_detail_json") or {}).get("retake_count"),
                "episode_replay_version": feat.get("episode_replay_version"),
                "episode_replay_start_date": feat.get("episode_replay_start_date"),
                "episode_replay_first_evaluation_date": feat.get("episode_replay_first_evaluation_date"),
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
                "first_wave_formation_bars": feat.get("first_wave_formation_bars"),
                "first_wave_speed": feat.get("first_wave_speed"),
                "drawdown_from_first_wave_high": feat.get("drawdown_from_first_wave_high"),
                "last_closed_episode": feat.get("last_closed_episode"),
                "bottom_structure_type": feat.get("bottom_structure_type", "NONE"),
                "bottom_structure_quality": feat.get("bottom_structure_quality", "NONE"),
                "bottom_structure_strength": feat.get("bottom_structure_strength", 0),
                "bottom_first_low_date": feat.get("bottom_first_low_date"),
                "bottom_second_low_date": feat.get("bottom_second_low_date"),
                "bottom_structure_confirmed_date": feat.get("bottom_structure_confirmed_date"),
                "bottom_first_low": feat.get("bottom_first_low"),
                "bottom_middle_high": feat.get("bottom_middle_high"),
                "bottom_second_low": feat.get("bottom_second_low"),
                "bottom_low_gap_bars": feat.get("bottom_low_gap_bars"),
                "bottom_structure_age_bars": feat.get("bottom_structure_age_bars"),
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
            "replay_mode": "WINDOWED_60_TRADING_DAYS",
            "replay_start_date": replay_start_date,
            "indicator_data_start_date": history_start_date,
            "history": history,
            "klines": klines,
            "recent_90d_klines": klines,
        }
