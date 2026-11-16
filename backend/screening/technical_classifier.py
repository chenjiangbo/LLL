"""全市场技术形态分类 V1.0。

该模块与旧 A-Pre、A/B/C 规则完全隔离。它只消费前复权日线，按已完成周线
和逐日 Episode 状态生成唯一的 weekly_stage/daily_subtype。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
import uuid

import numpy as np
import pandas as pd

from backend.screening.data_sync import ScreeningDataSync
from backend.screening.errors import ScreeningError
from backend.screening.storage import PostgresScreeningStore
from backend.screening.tushare_source import TushareScreeningSource
from backend.screening.early_turn_engine import EarlyTurnEngine


CLASSIFIER_VERSION = "TECH_CLASSIFIER_V1_0"
REQUIRED_DAILY_BARS = 250
REQUIRED_COMPLETED_WEEKS = 35

W4_PRIORITY = ["W4_MATURE_REBOUND", "W4_SECOND_TURN", "W4_FIRST_PULLBACK", "W4_FIRST_ADVANCE", "W4_FIRST_TURN", "W4_EARLY_PREP", "W4_DECLINE_DECELERATING", "W4_ACCEL_DECLINE", "W4_DECLINE"]
W1_PRIORITY = ["W1_FAILED_BREAKOUT", "W1_BREAKOUT_REACCEL", "W1_BREAKOUT_PULLBACK", "W1_BREAKOUT", "W1_FIRST_TURN", "W1_EARLY_PREP", "W1_BASE_COMPRESSION", "W1_BASE_RANGE"]
W2_PRIORITY = ["W2_TREND_DAMAGE", "W2_REACCEL", "W2_PULLBACK_STABILIZING", "W2_PULLBACK", "W2_ACCEL_EXTENDED", "W2_STEADY_ADVANCE"]
W3_PRIORITY = ["W3_POST_BREAKDOWN_REBOUND", "W3_BREAKDOWN", "W3_HIGH_REACCEL", "W3_HIGH_WEAKENING", "W3_HIGH_REPAIR", "W3_HIGH_COMPRESSION", "W3_HIGH_RANGE"]


def _ratio(a: float, b: float) -> float:
    return float(a / b - 1.0) if b and np.isfinite(b) else 0.0


def _consecutive(values: pd.Series) -> int:
    count = 0
    for value in reversed(values.tolist()):
        if bool(value):
            count += 1
        else:
            break
    return count


def _daily_features(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.sort_values("trade_date").reset_index(drop=True).copy()
    price = df["close"].astype(float) * df["adj_factor"].astype(float)
    df["adj_close"] = price
    df["adj_high"] = df["high"].astype(float) * df["adj_factor"].astype(float)
    df["adj_low"] = df["low"].astype(float) * df["adj_factor"].astype(float)
    for n in (5, 10, 20, 30, 60):
        df[f"ma{n}"] = price.rolling(n).mean()
    prev_close = price.shift(1)
    tr = pd.concat([(df["adj_high"] - df["adj_low"]), (df["adj_high"] - prev_close).abs(), (df["adj_low"] - prev_close).abs()], axis=1).max(axis=1)
    df["atr20"] = tr.rolling(20).mean()
    for n in (5, 10, 20, 40, 60):
        df[f"return_{n}d"] = price / price.shift(n) - 1.0
        df[f"drawdown_{n}d"] = 1.0 - price / price.rolling(n).max()
    df["days_from_40d_high"] = (price.rolling(40).apply(lambda x: len(x) - 1 - int(np.argmax(x)), raw=True))
    for n, lag in ((5, 5), (10, 5), (20, 5), (30, 5), (60, 20)):
        df[f"ma{n}_slope"] = df[f"ma{n}"] / df[f"ma{n}"].shift(lag) - 1.0
    df["ma10_slope_prev5"] = df["ma10_slope"].shift(5)
    df["ma20_slope_prev5"] = df["ma20_slope"].shift(5)
    df["ma10_curve_improve"] = df["ma10_slope"] - df["ma10_slope_prev5"]
    df["ma20_curve_improve"] = df["ma20_slope"] - df["ma20_slope_prev5"]
    ma_cols = ["ma5", "ma10", "ma20", "ma30"]
    df["ma_spread_atr"] = (df[ma_cols].max(axis=1) - df[ma_cols].min(axis=1)) / df["atr20"]
    df["ma_spread"] = df[ma_cols].max(axis=1) - df[ma_cols].min(axis=1)
    df["ma_spread_5d_ago"] = df["ma_spread"].shift(5)
    df["spread_contract_ratio"] = df["ma_spread"] / df["ma_spread_5d_ago"]
    pairs = ((5, 10), (5, 20), (5, 30), (10, 20), (10, 30), (20, 30))
    cross_events = []
    for a, b in pairs:
        relation = df[f"ma{a}"] > df[f"ma{b}"]
        cross_events.append(relation.ne(relation.shift(1)) & relation.notna() & relation.shift(1).notna())
    df["cross_pair_events"] = pd.concat(cross_events, axis=1).sum(axis=1)
    pair_presence = pd.concat([series.astype(int) for series in cross_events], axis=1)
    df["cross_pair_count_10d"] = pair_presence.rolling(10).max().sum(axis=1)
    df["cross_event_count_10d"] = df["cross_pair_events"].rolling(10).sum()
    df["retake_count"] = sum((price > df[f"ma{n}"]).astype(int) for n in (5, 10, 20, 30))
    df["order_score"] = (df["ma5"] > df["ma10"]).astype(int) + (df["ma5"] > df["ma20"]).astype(int) + (df["ma10"] > df["ma20"]).astype(int) + (df["ma20"] > df["ma30"]).astype(int)
    df["volume_ratio"] = df["amount"].astype(float) / df["amount"].rolling(60).median()
    df["extension_atr"] = (price - df["ma20"]) / df["atr20"]
    df["pct_chg"] = price / price.shift(1) - 1.0
    df["range_pos_60d"] = (price - price.rolling(60).min()) / (price.rolling(60).max() - price.rolling(60).min())
    df["price_amplitude_20d"] = (price.rolling(20).max() - price.rolling(20).min()) / ((price.rolling(20).max() + price.rolling(20).min()) / 2.0)
    return df.replace([np.inf, -np.inf], np.nan)


def _weekly_stage(daily: pd.DataFrame) -> tuple[str, str | None, list[dict[str, Any]], dict[str, str]]:
    """逐周运行 W 状态机，并把状态映射到当时可用的日线。

    当前未完成周不参与计算；该周日线继续使用上一完整周的状态。
    """
    df = daily.sort_values("trade_date").copy()
    dates = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df["week"] = dates.dt.to_period("W-FRI")
    weeks = df.groupby("week", sort=True).agg(
        trade_date=("trade_date", "max"),
        calendar_date=("trade_date", "max"),
        close=("adj_close", "last"),
        high=("adj_high", "max"),
        low=("adj_low", "min"),
    ).reset_index(drop=True)
    weeks["calendar_date"] = pd.to_datetime(weeks["calendar_date"], format="%Y%m%d")
    # 周中评估时，最近一周可能只有周一至周四数据，必须剔除。
    if not weeks.empty and weeks.iloc[-1]["calendar_date"].weekday() < 4:
        weeks = weeks.iloc[:-1].copy()
    weeks["wma30"] = weeks["close"].rolling(30).mean()
    weeks["slope"] = weeks["wma30"] / weeks["wma30"].shift(5) - 1.0
    weeks["dist"] = weeks["close"] / weeks["wma30"] - 1.0
    weeks["ret26"] = weeks["close"] / weeks["close"].shift(26) - 1.0
    weeks["range_pos52"] = (weeks["close"] - weeks["low"].rolling(52).min()) / (weeks["high"].rolling(52).max() - weeks["low"].rolling(52).min())
    stages: list[str] = []
    history: list[dict[str, Any]] = []
    previous_clear: str | None = None
    pending_stage: str | None = None
    pending_weeks = 0
    for idx, row in weeks.iterrows():
        slope, dist = row["slope"], row["dist"]
        if pd.isna(slope) or pd.isna(dist):
            stages.append("UNAVAILABLE")
            history.append({"trade_date": str(row["trade_date"]), "stage": "UNAVAILABLE"})
            continue
        trend_candidate = "W2_ADVANCE" if slope >= .015 and dist >= .02 else "W4_DECLINE" if slope <= -.015 and dist <= -.02 else None
        strong = trend_candidate == "W2_ADVANCE" and slope >= .025 and dist >= .05 or trend_candidate == "W4_DECLINE" and slope <= -.025 and dist <= -.05
        if trend_candidate:
            if strong:
                previous_clear, pending_stage, pending_weeks = trend_candidate, None, 0
            elif pending_stage == trend_candidate:
                pending_weeks += 1
                if pending_weeks >= 2:
                    previous_clear, pending_stage, pending_weeks = trend_candidate, None, 0
            else:
                pending_stage, pending_weeks = trend_candidate, 1
        elif abs(float(slope)) < .015 or abs(float(dist)) <= .02:
            pending_stage, pending_weeks = None, 0
            if previous_clear == "W4_DECLINE":
                previous_clear = "W1_BASE"
            elif previous_clear == "W2_ADVANCE":
                previous_clear = "W3_TOP"
            elif previous_clear is None:
                previous_clear = "W1_BASE" if (row["ret26"] < 0 or row["range_pos52"] <= .45) else "W3_TOP"
        stage = previous_clear or ("W1_BASE" if row["ret26"] < 0 else "W3_TOP")
        stages.append(stage)
        history.append({"trade_date": str(row["trade_date"]), "stage": stage, "slope": float(slope), "dist": float(dist)})
    if len(weeks) < REQUIRED_COMPLETED_WEEKS:
        return "UNAVAILABLE", None, history, {}
    stage_dates = {str(row["trade_date"]): stages[idx] for idx, row in weeks.iterrows()}
    weekly_dates = sorted(stage_dates)
    daily_map: dict[str, str] = {}
    for trade_date in df["trade_date"].astype(str):
        prior = [value for value in weekly_dates if value <= trade_date]
        if prior:
            daily_map[trade_date] = stage_dates[prior[-1]]
    latest_stage = daily_map.get(str(df.iloc[-1]["trade_date"]), "UNAVAILABLE")
    latest_stage_date = next((d for d in reversed(weekly_dates) if d <= str(df.iloc[-1]["trade_date"])), None)
    if latest_stage_date:
        latest_idx = weekly_dates.index(latest_stage_date)
        for prior_idx in range(latest_idx, -1, -1):
            if stages[prior_idx] != latest_stage:
                break
            latest_stage_date = str(weeks.iloc[prior_idx]["trade_date"])
    return latest_stage, latest_stage_date, history, daily_map


def _prep_score(row: pd.Series, background: str) -> int:
    score = 15 if (background == "W4" and row["days_from_40d_high"] >= 8 and (row["return_20d"] <= -.08 or row["return_40d"] <= -.15 or row["drawdown_60d"] >= .18)) or (background != "W4" and row["drawdown_20d"] >= .06) else 0
    score += sum(v for cond, v in ((row["ma10_slope"] >= -.01, 8), (row["ma20_slope"] >= -.015, 8), (row["ma10_curve_improve"] >= .008, 7), (row["ma20_curve_improve"] >= .008, 7)) if cond)
    score += 15 if row["ma_spread_atr"] <= .8 else 10 if row["ma_spread_atr"] <= 1.2 else 5 if row["ma_spread_atr"] <= 1.5 else 0
    score += 10 if row["cross_pair_count_10d"] >= 2 else 5 if row["cross_pair_count_10d"] >= 1 else 0
    score += 20 if row["retake_count"] >= 3 else 14 if row["retake_count"] == 2 else 6 if row["retake_count"] == 1 else 0
    score += 10 if row["extension_atr"] <= 1 else 5 if row["extension_atr"] <= 1.5 else 0
    return int(max(0, min(100, score)))


def _turn_score(features: dict[str, Any], ts_code: str, trade_date: str) -> int:
    """复用现有 A-Pre 转强评分器；分类语义仍由本模块决定。"""
    result = EarlyTurnEngine().evaluate_stock(ts_code, trade_date, features, prep_score_mode="existing")
    return int(round(float(result.get("total_score") or 0)))


def _classify_stock(daily: pd.DataFrame, stock_code: str, include_history: bool = False) -> dict[str, Any]:
    df = _daily_features(daily)
    weekly, weekly_since, weekly_history, daily_weekly_stage = _weekly_stage(df)
    if weekly == "UNAVAILABLE":
        return {"ts_code": stock_code, "weekly_stage": "UNAVAILABLE", "daily_subtype": "UNAVAILABLE", "subtype_family": "UNAVAILABLE", "setup_score": None, "score_type": None, "is_overextended": False, "reason_codes": ["WEEKLY_HISTORY_INSUFFICIENT"], "features": {"daily_bar_count": len(df), "completed_week_count": len(weekly_history)}}
    episode: dict[str, Any] = {"state": "NONE", "turn_idx": None, "base_low": None, "base_low_date": None, "first_turn_date": None, "first_turn_close": None, "first_wave_high_close": None, "first_wave_high_date": None, "pullback_low": None, "pullback_low_date": None, "breakout_level": None, "breakout_date": None, "breakout_high": None, "breakout_below_count": 0, "breakdown_level": None, "breakdown_date": None}
    result_rows: list[dict[str, Any]] = []
    prev_stage = None
    for idx, row in df.iterrows():
        if pd.isna(row["ma60"]) or pd.isna(row["ma20"]):
            continue
        r = row.fillna(0)
        price = float(r["adj_close"])
        enough_decline = r["days_from_40d_high"] >= 8 and (r["return_20d"] <= -.08 or r["return_40d"] <= -.15 or r["drawdown_60d"] >= .18)
        arc = sum((r["ma10_slope"] >= -.01, r["ma20_slope"] >= -.015, r["ma10_curve_improve"] >= .008, r["ma20_curve_improve"] >= .008)) >= 2
        converge = r["ma_spread_atr"] <= 1.2 or r["spread_contract_ratio"] <= .85 or r["cross_pair_count_10d"] >= 1
        first_turn = r["retake_count"] >= 3 and r["order_score"] >= 2 and r["ma5"] > r["ma10"] and (r["ma_spread_atr"] <= 1.2 or r["cross_pair_count_10d"] >= 2)
        stage = daily_weekly_stage.get(str(r["trade_date"]), "UNAVAILABLE")
        if stage == "UNAVAILABLE":
            continue
        if stage == "W4_DECLINE":
            if episode["state"] == "TURN":
                prior_lows = df.iloc[max(0, idx - 60):idx]["adj_low"]
                failed = price < episode["base_low"] * .98 or (len(prior_lows) > 0 and r["adj_low"] <= prior_lows.min() and r["ma20_slope"] < 0 and r["ma30_slope"] < 0)
                if failed:
                    episode = {"state": "NONE", "turn_idx": None, "base_low": None, "base_low_date": None, "first_turn_date": None, "first_turn_close": None, "first_wave_high_close": None, "first_wave_high_date": None, "pullback_low": None, "pullback_low_date": None, "breakout_level": None, "breakout_date": None, "breakout_high": None, "breakout_below_count": 0, "breakdown_level": None, "breakdown_date": None}
                elif episode["turn_idx"] is not None and idx - episode["turn_idx"] >= 2:
                    wave = df.iloc[episode["turn_idx"]:idx + 1]
                    high_close_idx = wave["adj_close"].idxmax()
                    high_idx = wave["adj_high"].idxmax()
                    high_close = float(wave.loc[high_close_idx, "adj_close"])
                    high = float(wave.loc[high_idx, "adj_high"])
                    if high_close / max(episode["base_low"], .01) - 1 >= .08 or (high - episode["base_low"]) / max(float(r["atr20"]), .01) >= 2.5:
                        episode.update(state="ADVANCE", first_wave_high_close=high_close, first_wave_high_date=str(wave.loc[high_close_idx, "trade_date"]))
            if episode["state"] in ("ADVANCE", "PULLBACK") and episode["first_wave_high_close"]:
                if episode["state"] == "ADVANCE" and (episode["first_wave_high_close"] - price) / max(episode["first_wave_high_close"], .01) >= .05 and price > episode["base_low"] * 1.03:
                    episode.update(state="PULLBACK", pullback_low=price, pullback_low_date=str(r["trade_date"]))
                elif episode["state"] == "PULLBACK" and episode["pullback_low"] is not None and price < episode["pullback_low"]:
                    episode.update(pullback_low=price, pullback_low_date=str(r["trade_date"]))
            if episode["state"] == "NONE" and first_turn:
                base_slice = df.iloc[max(0, idx - 40):idx + 1]
                base_idx = base_slice["adj_low"].idxmin()
                episode.update(state="TURN", turn_idx=idx, base_low=float(base_slice.loc[base_idx, "adj_low"]), base_low_date=str(base_slice.loc[base_idx, "trade_date"]), first_turn_date=str(r["trade_date"]), first_turn_close=price)
        if stage == "W4_DECLINE":
            if episode["state"] == "SECOND_TURN" and (price > episode["first_wave_high_close"] or (r["ma20_slope"] > 0 and r["return_10d"] >= .1)):
                subtype = "W4_MATURE_REBOUND"
            elif episode["state"] == "PULLBACK" and episode["pullback_low"] is not None and r["retake_count"] >= 2 and r["ma5_slope"] > 0 and price >= r["ma5"] and price / max(episode["pullback_low"], .01) - 1 >= .04 and (r["cross_pair_count_10d"] >= 1 or price > r["ma20"] or price > df.iloc[max(0, idx - 5):idx]["adj_close"].max()):
                subtype, episode["state"] = "W4_SECOND_TURN", "SECOND_TURN"
            elif episode["state"] in ("ADVANCE", "PULLBACK") and episode["first_wave_high_close"] is not None and episode["base_low"] is not None and (episode["first_wave_high_close"] - price) / max(episode["first_wave_high_close"], .01) >= .05 and price > episode["base_low"] * 1.03:
                subtype, episode["state"] = "W4_FIRST_PULLBACK", "PULLBACK"
                episode["pullback_low"], episode["pullback_low_date"] = price, str(r["trade_date"])
            elif episode["state"] == "ADVANCE":
                subtype = "W4_FIRST_ADVANCE"
            elif episode["state"] == "TURN":
                subtype = "W4_FIRST_TURN"
            elif enough_decline and arc and converge and r["retake_count"] >= 1 and not first_turn and r["extension_atr"] <= 1.5:
                subtype = "W4_EARLY_PREP"
            elif enough_decline and (r["ma10_curve_improve"] >= .008 or r["ma20_curve_improve"] >= .008):
                subtype = "W4_DECLINE_DECELERATING"
            elif (r["return_5d"] <= -.08 or r["return_10d"] <= -.12) and price < r["ma20"] and r["ma20_slope"] <= -.02:
                subtype = "W4_ACCEL_DECLINE"
            else:
                subtype = "W4_DECLINE"
        elif stage == "W1_BASE":
            base_upper = float(df.iloc[max(0, idx - 60):idx]["adj_close"].max()) if idx else price
            if episode["state"] == "BREAKOUT" and price < episode["breakout_level"] * .97:
                episode["breakout_below_count"] += 1
                failed_breakout = episode["breakout_below_count"] >= 2 or (price < r["ma30"] and price < episode["breakout_level"] * .97)
                subtype = "W1_FAILED_BREAKOUT" if failed_breakout else "W1_BREAKOUT"
                if failed_breakout:
                    episode["state"] = "FAILED"
            elif episode["state"] == "BREAKOUT":
                episode["breakout_below_count"] = 0
                subtype = "W1_BREAKOUT"
            elif episode["state"] == "FAILED":
                subtype = "W1_FAILED_BREAKOUT"
            elif episode["state"] == "BREAKOUT" and episode["breakout_high"] and (episode["breakout_high"] - price) / episode["breakout_high"] >= .04 and episode["breakout_level"] * .97 <= price <= episode["breakout_level"] * 1.05:
                subtype, episode["state"] = "W1_BREAKOUT_PULLBACK", "PULLBACK"
                episode["pullback_low"] = price
            elif episode["state"] == "PULLBACK" and episode["breakout_level"] is not None and r["retake_count"] >= 3 and r["ma5_slope"] > 0 and price >= episode["breakout_level"] and price > df.iloc[max(0, idx - 5):idx]["adj_close"].max():
                subtype = "W1_BREAKOUT_REACCEL"
            elif episode["state"] == "PULLBACK" and episode["breakout_level"] is not None:
                subtype = "W1_BREAKOUT_PULLBACK"
            elif episode["state"] == "BREAKOUT" and (base_upper and price < base_upper * .96):
                subtype = "W1_FAILED_BREAKOUT"
            elif price >= base_upper * 1.01 and r["volume_ratio"] >= 1.2 or idx > 1 and price > float(df.iloc[max(0, idx - 61):idx - 1]["adj_close"].max()) and df.iloc[idx - 1]["adj_close"] > float(df.iloc[max(0, idx - 61):idx - 1]["adj_close"].max()):
                subtype, episode["state"] = "W1_BREAKOUT", "BREAKOUT"
                episode.update(breakout_level=base_upper, breakout_high=price, breakout_date=str(r["trade_date"]))
            elif first_turn:
                subtype = "W1_FIRST_TURN"
            elif (r["drawdown_20d"] >= .05 or r["range_pos_60d"] <= .6) and arc and converge and r["retake_count"] >= 1 and r["extension_atr"] <= 1.5:
                subtype = "W1_EARLY_PREP"
            elif r["ma_spread_atr"] <= .8 and (df.iloc[max(0, idx - 20):idx + 1]["adj_close"].max() - df.iloc[max(0, idx - 20):idx + 1]["adj_close"].min()) / max(df.iloc[max(0, idx - 20):idx + 1]["adj_close"].mean(), .01) <= .12 and r["cross_pair_count_10d"] >= 2:
                subtype = "W1_BASE_COMPRESSION"
            else:
                subtype = "W1_BASE_RANGE"
        elif stage == "W2_ADVANCE":
            if price < r["ma60"] * .97 and (r["drawdown_60d"] >= .2 or r["ma20_slope"] <= -.02): subtype = "W2_TREND_DAMAGE"
            elif episode["state"] in ("PULLBACK", "STABILIZING") and r["retake_count"] >= 3 and r["ma5_slope"] > 0 and price > r["ma20"] and price > df.iloc[max(0, idx - 5):idx]["adj_close"].max(): subtype, episode["state"] = "W2_REACCEL", "REACCEL"
            elif r["drawdown_20d"] >= .06 and r["days_from_40d_high"] >= 5 and arc and r["retake_count"] >= 1 and converge: subtype, episode["state"] = "W2_PULLBACK_STABILIZING", "STABILIZING"
            elif r["drawdown_20d"] >= .04 and (price < r["ma10"] or r["return_10d"] < 0) and price >= r["ma60"] * .97: subtype, episode["state"] = "W2_PULLBACK", "PULLBACK"
            elif r["return_10d"] >= .15 or r["extension_atr"] > 2.5 or price / max(r["ma20"], .01) - 1 >= .15: subtype = "W2_ACCEL_EXTENDED"
            else: subtype = "W2_STEADY_ADVANCE"
        else:
            if episode["state"] == "BREAKDOWN" and price > r["ma5"] and r["return_5d"] > 0 and (price < r["ma30"] or price < r["ma60"]): subtype = "W3_POST_BREAKDOWN_REBOUND"
            elif price < r["ma60"] * .98 and r["drawdown_60d"] >= .15 or price < df.iloc[max(0, idx - 40):idx]["adj_close"].min() * .98: subtype, episode["state"] = "W3_BREAKDOWN", "BREAKDOWN"
            elif r["retake_count"] >= 3 and r["ma5_slope"] > 0 and price > r["ma20"] and price > df.iloc[max(0, idx - 5):idx]["adj_close"].max(): subtype = "W3_HIGH_REACCEL"
            elif r["drawdown_20d"] >= .08 and price < r["ma20"] and r["ma5"] < r["ma10"] and r["ma20_slope"] <= 0: subtype = "W3_HIGH_WEAKENING"
            elif r["drawdown_20d"] >= .06 and arc and r["retake_count"] >= 1 and converge: subtype = "W3_HIGH_REPAIR"
            elif r["price_amplitude_20d"] <= .10 and r["ma_spread_atr"] <= .8 and r["range_pos_60d"] >= .55: subtype = "W3_HIGH_COMPRESSION"
            else: subtype = "W3_HIGH_RANGE"
        score_type = "PREP_SCORE" if "EARLY_PREP" in subtype or subtype in ("W2_PULLBACK_STABILIZING", "W3_HIGH_REPAIR") else "TURN_SCORE" if "TURN" in subtype or "REACCEL" in subtype else None
        features = {k: (float(v) if isinstance(v, (np.floating, float)) else int(v) if isinstance(v, (np.integer, int)) else v) for k, v in r.to_dict().items() if k not in {"adj_high", "adj_low"}}
        score = _prep_score(r, stage[:2]) if score_type == "PREP_SCORE" else _turn_score(features, stock_code, str(r["trade_date"])) if score_type == "TURN_SCORE" else None
        result_rows.append({"trade_date": str(r["trade_date"]), "weekly_stage": stage, "daily_subtype": subtype, "score": score, "score_type": score_type, "features": features, "episode": dict(episode)})
    if not result_rows:
        raise ScreeningError(f"{stock_code} has no valid rows after indicator warmup")
    latest = result_rows[-1]
    subtype = latest["daily_subtype"]
    result = {"ts_code": stock_code, "trade_date": latest["trade_date"], "weekly_stage": latest["weekly_stage"], "weekly_stage_since": weekly_since, "daily_subtype": subtype, "subtype_family": subtype.split("_", 1)[1] if "_" in subtype else subtype, "setup_score": latest["score"], "score_type": latest["score_type"], "is_overextended": bool(latest["features"].get("extension_atr", 0) > 2 or latest["features"].get("adj_close", 0) / max(latest["features"].get("ma20", 0), .01) - 1 > .18 or latest["features"].get("pct_chg", 0) >= .15), "episode_fields": latest["episode"], "reason_codes": [subtype, latest["weekly_stage"]], "features": latest["features"], "weekly_history": weekly_history}
    if include_history:
        result["history"] = result_rows
    return result


@dataclass
class TechnicalClassificationService:
    store: PostgresScreeningStore

    def ensure_schema(self) -> None:
        with self.store.connect() as conn:
            conn.execute("""create table if not exists technical_classification_snapshot (trade_date text not null, ts_code text not null, weekly_stage text not null, weekly_stage_since text, daily_subtype text not null, subtype_family text not null, setup_score numeric, score_type text, is_overextended boolean not null, episode_json jsonb not null, reason_codes jsonb not null, features_json jsonb not null, classifier_version text not null, created_at timestamptz not null default now(), primary key (trade_date, ts_code, classifier_version))""")
            conn.execute("""create table if not exists technical_classification_run (run_id text primary key, trade_date text not null, classifier_version text not null, status text not null, summary_json jsonb not null default '{}'::jsonb, error_message text, started_at timestamptz not null default now(), finished_at timestamptz)""")
            conn.commit()

    def _load(self, trade_date: str, ts_code: str | None = None) -> pd.DataFrame:
        with self.store.connect() as conn:
            sql = """select b.asset_code, b.asset_type, b.trade_date, b.open, b.high, b.low, b.close, b.vol, b.amount, f.adj_factor from screening_daily_bar b left join screening_adj_factor f on f.asset_code=b.asset_code and f.trade_date=b.trade_date where b.asset_type='stock' and b.trade_date <= %s"""
            params: list[Any] = [trade_date]
            if ts_code:
                sql += " and b.asset_code=%s"
                params.append(ts_code)
            rows = conn.execute(sql + " order by b.asset_code, b.trade_date", params).fetchall()
        df = pd.DataFrame([dict(row) for row in rows])
        if df.empty: raise ScreeningError(f"no adjusted stock daily data for {trade_date}")
        return df

    def classify_single(self, trade_date: str, ts_code: str) -> dict[str, Any]:
        """对一只股票按与全市场快照完全相同的规则即时分类，不写入全市场快照。"""
        code = ts_code.strip().upper()
        if not code:
            raise ScreeningError("ts_code is required")
        raw = self._load(trade_date, code)
        if raw["adj_factor"].isna().any():
            raise ScreeningError(f"{code} has daily bars without adj_factor; complete adjusted-factor data before testing")
        if len(raw) < REQUIRED_DAILY_BARS:
            return {"ts_code": code, "trade_date": trade_date, "weekly_stage": "UNAVAILABLE", "weekly_stage_since": None, "daily_subtype": "UNAVAILABLE", "setup_score": None, "score_type": None, "is_overextended": False, "episode_fields": {}, "reason_codes": ["DAILY_HISTORY_INSUFFICIENT"], "features": {"daily_bar_count": len(raw)}}
        return _classify_stock(raw, code)

    def classify_history(self, start_date: str, end_date: str, ts_code: str) -> dict[str, Any]:
        code = ts_code.strip().upper()
        start, end = start_date.replace("-", ""), end_date.replace("-", "")
        if len(start) != 8 or len(end) != 8 or start > end:
            raise ScreeningError("start_date/end_date must be valid YYYYMMDD dates")
        raw = self._load(end, code)
        if raw["adj_factor"].isna().any():
            raise ScreeningError(f"{code} has daily bars without adj_factor; complete adjusted-factor data before testing")
        if len(raw) < REQUIRED_DAILY_BARS:
            raise ScreeningError(f"{code} has insufficient daily history: {len(raw)} < {REQUIRED_DAILY_BARS}")
        result = _classify_stock(raw, code, include_history=True)
        history = [item for item in result.pop("history", []) if start <= item["trade_date"] <= end]
        if not history:
            raise ScreeningError(f"{code} has no classifiable trading days in {start}~{end}")
        feature_by_date = {item["trade_date"]: item["features"] for item in history}
        klines = []
        for row in raw[(raw["trade_date"] >= start) & (raw["trade_date"] <= end)].to_dict("records"):
            features = feature_by_date.get(str(row["trade_date"]), {})
            klines.append({"trade_date": str(row["trade_date"]), "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"]), "vol": float(row["vol"]), "amount": float(row["amount"]), "ma5": features.get("ma5"), "ma10": features.get("ma10"), "ma20": features.get("ma20"), "ma30": features.get("ma30"), "ma60": features.get("ma60")})
        return {"ts_code": code, "start_date": start, "end_date": end, "history": history, "klines": klines, "latest": history[-1]}

    def ensure_history(self, trade_date: str, sync: ScreeningDataSync) -> dict[str, Any]:
        """补齐分类所需的历史日线；范围由指标预热要求决定。"""
        with self.store.connect() as conn:
            row = conn.execute("select min(b.trade_date) as first_date, count(distinct b.trade_date) as trading_days, count(*) filter (where f.adj_factor is null) as missing_adjusted from screening_daily_bar b left join screening_adj_factor f on f.asset_code=b.asset_code and f.trade_date=b.trade_date where b.asset_type='stock' and b.trade_date <= %s", (trade_date,)).fetchone()
        trading_days = int(row["trading_days"] or 0) if row else 0
        missing_adjusted = int(row["missing_adjusted"] or 0) if row else 0
        if trading_days >= REQUIRED_DAILY_BARS and missing_adjusted == 0:
            return {"status": "READY", "existing_trading_days": trading_days, "synced_dates": 0}
        end = date.fromisoformat(f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}")
        start = (end - timedelta(days=600)).strftime("%Y%m%d")
        if not self.store.load_assets().shape[0]:
            sync.sync_assets()
        results = sync.sync_history(start, trade_date)
        with self.store.connect() as conn:
            row_after = conn.execute("select count(distinct b.trade_date) as trading_days, count(*) filter (where f.adj_factor is null) as missing_adjusted from screening_daily_bar b left join screening_adj_factor f on f.asset_code=b.asset_code and f.trade_date=b.trade_date where b.asset_type='stock' and b.trade_date <= %s", (trade_date,)).fetchone()
        after = int(row_after["trading_days"] or 0)
        missing_after = int(row_after["missing_adjusted"] or 0)
        if after < REQUIRED_DAILY_BARS or missing_after:
            raise ScreeningError(f"history completion finished but input remains incomplete: trading_days={after}, missing_adjusted={missing_after}, required_days={REQUIRED_DAILY_BARS}")
        return {"status": "COMPLETED", "existing_trading_days": trading_days, "synced_dates": len(results), "available_trading_days": after, "missing_adjusted": missing_after}

    def run(self, trade_date: str, progress_callback: Any | None = None) -> dict[str, Any]:
        self.ensure_schema()
        run_id = f"tech_{trade_date}_{uuid.uuid4().hex[:10]}"
        with self.store.connect() as conn:
            conn.execute("insert into technical_classification_run (run_id, trade_date, classifier_version, status) values (%s,%s,%s,'RUNNING')", (run_id, trade_date, CLASSIFIER_VERSION))
            conn.commit()
        try:
            summary = self._run_inner(trade_date, progress_callback)
            summary["run_id"] = run_id
            with self.store.connect() as conn:
                conn.execute("update technical_classification_run set status='SUCCESS', summary_json=%s::jsonb, finished_at=now() where run_id=%s", (json_dumps(summary), run_id))
                conn.commit()
            return summary
        except Exception as exc:
            with self.store.connect() as conn:
                conn.execute("update technical_classification_run set status='FAILED', error_message=%s, finished_at=now() where run_id=%s", (str(exc), run_id))
                conn.commit()
            raise

    def _run_inner(self, trade_date: str, progress_callback: Any | None = None) -> dict[str, Any]:
        self.ensure_schema()
        raw = self._load(trade_date)
        missing_adjusted = int(raw["adj_factor"].isna().sum())
        if missing_adjusted:
            raise ScreeningError(f"technical classification input has {missing_adjusted} daily rows without adjusted factors; data completion is required")
        counts = raw.groupby("asset_code").size()
        results = []
        grouped = list(raw.groupby("asset_code", sort=True))
        total_assets = len(grouped)
        for asset_index, (code, group) in enumerate(grouped, start=1):
            if len(group) < REQUIRED_DAILY_BARS:
                results.append({"ts_code": code, "trade_date": trade_date, "weekly_stage": "UNAVAILABLE", "weekly_stage_since": None, "daily_subtype": "UNAVAILABLE", "subtype_family": "UNAVAILABLE", "setup_score": None, "score_type": None, "is_overextended": False, "episode_fields": {}, "reason_codes": ["DAILY_HISTORY_INSUFFICIENT"], "features": {"daily_bar_count": len(group)}})
            else:
                results.append(_classify_stock(group, code))
            if progress_callback:
                progress_callback(asset_index, total_assets, str(code))
        unavailable = [r for r in results if r["weekly_stage"] == "UNAVAILABLE"]
        usable = [r for r in results if r["weekly_stage"] != "UNAVAILABLE"]
        with self.store.connect() as conn:
            for item in results:
                conn.execute("""insert into technical_classification_snapshot (trade_date,ts_code,weekly_stage,weekly_stage_since,daily_subtype,subtype_family,setup_score,score_type,is_overextended,episode_json,reason_codes,features_json,classifier_version) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s) on conflict (trade_date,ts_code,classifier_version) do update set weekly_stage=excluded.weekly_stage,weekly_stage_since=excluded.weekly_stage_since,daily_subtype=excluded.daily_subtype,subtype_family=excluded.subtype_family,setup_score=excluded.setup_score,score_type=excluded.score_type,is_overextended=excluded.is_overextended,episode_json=excluded.episode_json,reason_codes=excluded.reason_codes,features_json=excluded.features_json,created_at=now()""", (trade_date,item["ts_code"],item["weekly_stage"],item["weekly_stage_since"],item["daily_subtype"],item["subtype_family"],item["setup_score"],item["score_type"],item["is_overextended"],json_dumps(item["episode_fields"]),json_dumps(item["reason_codes"]),json_dumps(item["features"]),CLASSIFIER_VERSION))
            conn.commit()
        weekly_counts = pd.Series([r["weekly_stage"] for r in results]).value_counts().to_dict()
        subtype_counts = pd.Series([r["daily_subtype"] for r in results]).value_counts().to_dict()
        summary = {"trade_date": trade_date, "classifier_version": CLASSIFIER_VERSION, "asset_count": len(results), "classified_count": len(usable), "weekly_unavailable_count": len(unavailable), "weekly_distribution": weekly_counts, "subtype_distribution": subtype_counts, "quality": {"raw_rows": len(raw), "asset_count": len(counts), "min_daily_bars": int(counts.min()), "max_daily_bars": int(counts.max()), "missing_adjusted_factor_rows": int(raw["adj_factor"].isna().sum())}}
        return summary

    def latest(self, trade_date: str, page: int = 1, page_size: int = 100, weekly_stage: str | None = None, daily_subtype: str | None = None, ts_codes: list[str] | None = None) -> dict[str, Any]:
        self.ensure_schema()
        where, params = ["trade_date=%s and classifier_version=%s"], [trade_date, CLASSIFIER_VERSION]
        if weekly_stage: where.append("weekly_stage=%s"); params.append(weekly_stage)
        if daily_subtype: where.append("daily_subtype=%s"); params.append(daily_subtype)
        if ts_codes is not None: where.append("ts_code = any(%s)"); params.append(ts_codes)
        with self.store.connect() as conn:
            total = conn.execute(f"select count(*) as n from technical_classification_snapshot where {' and '.join(where)}", params).fetchone()["n"]
            rows = conn.execute(f"select s.*, a.name, a.raw_json->>'industry' as industry from technical_classification_snapshot s left join screening_asset_master a on a.asset_code=s.ts_code where {' and '.join('s.' + clause.split('=', 1)[0] + '=' + clause.split('=', 1)[1] for clause in where)} order by s.setup_score desc nulls last,s.ts_code limit %s offset %s", [*params, page_size, (page-1)*page_size]).fetchall()
            distributions = conn.execute("select weekly_stage, count(*) as n from technical_classification_snapshot where trade_date=%s and classifier_version=%s group by weekly_stage", [trade_date, CLASSIFIER_VERSION]).fetchall()
            subtype_distributions = conn.execute("select weekly_stage, daily_subtype, count(*) as n from technical_classification_snapshot where trade_date=%s and classifier_version=%s group by weekly_stage, daily_subtype order by weekly_stage, n desc", [trade_date, CLASSIFIER_VERSION]).fetchall()
        subtype_counts: dict[str, list[dict[str, Any]]] = {}
        for row in subtype_distributions:
            subtype_counts.setdefault(row["weekly_stage"], []).append({"name": row["daily_subtype"], "count": int(row["n"])})
        return {"trade_date": trade_date, "classifier_version": CLASSIFIER_VERSION, "total": int(total), "page": page, "page_size": page_size, "weekly_stage_counts": {r["weekly_stage"]: int(r["n"]) for r in distributions}, "weekly_subtype_counts": subtype_counts, "items": [dict(r) for r in rows]}

    def latest_snapshot_date(self) -> str | None:
        self.ensure_schema()
        with self.store.connect() as conn:
            row = conn.execute("select max(trade_date) as trade_date from technical_classification_snapshot where classifier_version=%s", (CLASSIFIER_VERSION,)).fetchone()
        return str(row["trade_date"]) if row and row.get("trade_date") else None


def json_dumps(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, default=str)
