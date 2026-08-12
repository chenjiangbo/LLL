from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import warnings

import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning

from backend.screening.config import ScreeningConfig
from backend.screening.errors import ScreeningError


warnings.filterwarnings("ignore", category=PerformanceWarning)

MA_WINDOWS = [5, 10, 20, 60, 120, 250]
RET_WINDOWS = [5, 10, 20, 60, 120, 250]
HIGH_LOW_WINDOWS = [5, 10, 20, 60, 120, 250]


@dataclass
class FeatureEngine:
    config: ScreeningConfig
    skipped_assets: list[dict[str, str]] = None

    def __post_init__(self) -> None:
        if self.skipped_assets is None:
            self.skipped_assets = []

    def build_latest_features(self, history: pd.DataFrame, trade_date: str) -> list[dict[str, Any]]:
        if history.empty:
            raise ScreeningError("no local daily history available for screening")
        if "adj_factor" not in history.columns:
            raise ScreeningError("local history is missing adj_factor column")

        result: list[dict[str, Any]] = []
        for asset_code, group in history.groupby("asset_code", sort=False):
            group = group.sort_values("trade_date").reset_index(drop=True)
            if trade_date not in set(group["trade_date"].astype(str)):
                continue
            if group["adj_factor"].isna().any():
                self.skipped_assets.append({"asset_code": str(asset_code), "reason": "missing_adj_factor"})
                continue
            features_df = self._build_asset_features(group)
            latest = features_df[features_df["trade_date"].astype(str) == trade_date]
            if latest.empty:
                continue
            row = latest.iloc[-1]
            result.append(
                {
                    "asset_code": asset_code,
                    "asset_type": row["asset_type"],
                    "trade_date": trade_date,
                    "features": _row_features(row),
                }
            )
        if not result:
            raise ScreeningError(f"no assets have local bars for trade_date={trade_date}")
        return result

    def _build_asset_features(self, group: pd.DataFrame) -> pd.DataFrame:
        df = group.copy()
        numeric_columns = [
            "open",
            "high",
            "low",
            "close",
            "pct_chg",
            "vol",
            "amount",
            "adj_factor",
            "turnover_rate",
            "turnover_rate_f",
            "total_mv",
            "circ_mv",
        ]
        for column in numeric_columns:
            if column in df.columns:
                df[column] = pd.to_numeric(df[column], errors="coerce")
        latest_factor = df["adj_factor"].iloc[-1]
        if pd.isna(latest_factor) or latest_factor == 0:
            raise ScreeningError(f"invalid latest adj_factor for {df['asset_code'].iloc[-1]}")
        scale = df["adj_factor"] / latest_factor
        for column in ["open", "high", "low", "close"]:
            df[f"adj_{column}"] = df[column] * scale

        for window in MA_WINDOWS:
            df[f"ma{window}"] = df["adj_close"].rolling(window, min_periods=window).mean()
        df["ma20_slope_10"] = df["ma20"] / df["ma20"].shift(10) - 1
        df["ma60_slope_20"] = df["ma60"] / df["ma60"].shift(20) - 1
        df["ma120_slope_20"] = df["ma120"] / df["ma120"].shift(20) - 1
        df["ma120_slope_60"] = df["ma120"] / df["ma120"].shift(60) - 1
        df["ma60_slope_improvement"] = df["ma60_slope_20"] - df["ma60_slope_20"].shift(20)
        for window in [20, 60, 120]:
            df[f"close_vs_ma{window}"] = df["adj_close"] / df[f"ma{window}"] - 1

        for window in RET_WINDOWS:
            df[f"ret_{window}"] = df["adj_close"] / df["adj_close"].shift(window) - 1

        for window in HIGH_LOW_WINDOWS:
            df[f"prev_high_{window}"] = df["adj_high"].shift(1).rolling(window, min_periods=window).max()
            df[f"prev_low_{window}"] = df["adj_low"].shift(1).rolling(window, min_periods=window).min()
            df[f"distance_from_high_{window}"] = df["adj_close"] / df[f"prev_high_{window}"] - 1
            df[f"distance_from_low_{window}"] = df["adj_close"] / df[f"prev_low_{window}"] - 1
            df[f"drawdown_from_{window}d_high"] = df["adj_close"] / df[f"prev_high_{window}"] - 1

        df["max_drawdown_120"] = _rolling_max_drawdown(df["adj_close"], 120)
        df["max_drawdown_250"] = _rolling_max_drawdown(df["adj_close"], 250)

        for window in [5, 20, 60]:
            df[f"vol_ma{window}"] = df["vol"].rolling(window, min_periods=window).mean()
            df[f"amount_ma{window}"] = df["amount"].rolling(window, min_periods=window).mean()
        df["volume_ratio_5_20"] = df["vol_ma5"] / df["vol_ma20"]
        df["amount_ratio_5_20"] = df["amount_ma5"] / df["amount_ma20"]
        df["today_volume_ratio_20"] = df["vol"] / df["vol_ma20"]

        prev_close = df["adj_close"].shift(1)
        true_ranges = pd.concat(
            [
                df["adj_high"] - df["adj_low"],
                (df["adj_high"] - prev_close).abs(),
                (df["adj_low"] - prev_close).abs(),
            ],
            axis=1,
        )
        df["atr14"] = true_ranges.max(axis=1).rolling(14, min_periods=14).mean()
        df["atr_pct"] = df["atr14"] / df["adj_close"]
        df["volatility_20"] = df["adj_close"].pct_change().rolling(20, min_periods=20).std()
        df["prev_volatility_20"] = df["volatility_20"].shift(20)
        df["volatility_contract"] = df["volatility_20"] / df["prev_volatility_20"]
        df["rsi14"] = _rsi(df["adj_close"], 14)
        df["rsi14_min_5"] = df["rsi14"].rolling(5, min_periods=5).min()
        df["rsi14_prev_min_5"] = df["rsi14_min_5"].shift(1)

        day_range = df["adj_high"] - df["adj_low"]
        df["close_position"] = np.where(day_range > 0, (df["adj_close"] - df["adj_low"]) / day_range, 0.5)
        df["body_pct"] = (df["adj_close"] - df["adj_open"]).abs() / df["adj_close"]
        df["gap_pct"] = df["adj_open"] / prev_close - 1
        df["coverage_120d"] = df["close"].rolling(120, min_periods=1).count() / 120
        df["history_days"] = np.arange(1, len(df) + 1)
        df["low_3_not_falling"] = df["adj_low"].rolling(3, min_periods=3).min() >= df["adj_low"].shift(3).rolling(3, min_periods=3).min() * 0.99
        df["low_5_not_falling"] = df["adj_low"].rolling(5, min_periods=5).min() >= df["adj_low"].shift(5).rolling(5, min_periods=5).min() * 0.98
        df["range_ma3"] = (df["adj_high"] - df["adj_low"]).rolling(3, min_periods=3).mean()
        df["prev_range_ma3"] = df["range_ma3"].shift(3)
        df["range_contract_3"] = df["range_ma3"] / df["prev_range_ma3"]
        df["near_high_60_pct"] = df["adj_close"] / df["prev_high_60"] - 1
        df["break_5"] = df["adj_close"] > df["adj_high"].shift(1).rolling(5, min_periods=5).max()
        df["break_10"] = df["adj_close"] > df["adj_high"].shift(1).rolling(10, min_periods=10).max()
        df["strong_bullish_atr"] = (df["pct_chg"] / 100) > df["atr_pct"]
        df["pullback_peak_120"] = df["prev_high_120"]
        df["pullback_peak_age_120"] = _rolling_peak_age(df["adj_high"].shift(1), 120)
        df["pullback_pct_120"] = df["adj_close"] / df["pullback_peak_120"] - 1
        df["pullback_low_since_peak_120"] = _latest_low_since_previous_peak(df["adj_low"], df["adj_high"], 120)
        df = _add_swing_features(df, self.config.swing_window)
        df["break_swing_low_pct"] = df["pullback_low_since_peak_120"] / df["last_swing_low"] - 1

        # A-Pre 专属特征计算
        high_low_diff_250 = df["prev_high_250"] - df["prev_low_250"]
        df["position_250"] = np.where(high_low_diff_250 > 0, (df["adj_close"] - df["prev_low_250"]) / high_low_diff_250, 0.5)
        df["slope_60"] = _rolling_slope(df["adj_close"], 60)
        df["slope_20"] = _rolling_slope(df["adj_close"], 20)
        df["slope_10"] = _rolling_slope(df["adj_close"], 10)
        df["deceleration"] = _calc_deceleration(df["slope_60"], df["slope_20"])

        recent_low_10 = df["adj_low"].rolling(10, min_periods=10).min()
        prev_low_11_30 = df["adj_low"].shift(10).rolling(20, min_periods=20).min()
        df["low_ratio"] = recent_low_10 / prev_low_11_30 - 1.0

        df["atr20"] = true_ranges.max(axis=1).rolling(20, min_periods=20).mean()
        df["atr60"] = true_ranges.max(axis=1).rolling(60, min_periods=60).mean()
        df["atr_ratio"] = df["atr20"] / df["atr60"]

        high20 = df["adj_high"].rolling(20, min_periods=20).max()
        low20 = df["adj_low"].rolling(20, min_periods=20).min()
        high60 = df["adj_high"].rolling(60, min_periods=60).max()
        low60 = df["adj_low"].rolling(60, min_periods=60).min()
        range20 = (high20 - low20) / df["adj_close"]
        range60 = (high60 - low60) / df["adj_close"]
        df["compression"] = range20 / range60

        df["volume_asymmetry"] = _calc_volume_asymmetry(df["pct_chg"], df["amount"], 20)
        resistance_20_30 = df["adj_high"].shift(1).rolling(20, min_periods=20).max()
        df["distance_to_breakout"] = df["adj_close"] / resistance_20_30 - 1.0
        return df


def _row_features(row: pd.Series) -> dict[str, Any]:
    keys = [
        "asset_code",
        "asset_type",
        "trade_date",
        "name",
        "list_date",
        "open",
        "high",
        "low",
        "close",
        "pct_chg",
        "vol",
        "amount",
        "turnover_rate",
        "turnover_rate_f",
        "total_mv",
        "circ_mv",
        "limit_status",
        "history_days",
        "coverage_120d",
        "adj_open",
        "adj_high",
        "adj_low",
        "adj_close",
        "ma5",
        "ma10",
        "ma20",
        "ma60",
        "ma120",
        "ma250",
        "ma20_slope_10",
        "ma60_slope_20",
        "ma120_slope_20",
        "ma120_slope_60",
        "ma60_slope_improvement",
        "close_vs_ma20",
        "close_vs_ma60",
        "close_vs_ma120",
        "ret_5",
        "ret_10",
        "ret_20",
        "ret_60",
        "ret_120",
        "ret_250",
        "prev_high_20",
        "prev_high_5",
        "prev_high_10",
        "prev_high_60",
        "prev_high_120",
        "prev_high_250",
        "prev_low_5",
        "prev_low_10",
        "prev_low_20",
        "prev_low_60",
        "prev_low_120",
        "prev_low_250",
        "distance_from_high_5",
        "distance_from_high_10",
        "distance_from_high_20",
        "distance_from_high_60",
        "distance_from_high_120",
        "distance_from_high_250",
        "distance_from_low_5",
        "distance_from_low_10",
        "distance_from_low_20",
        "distance_from_low_60",
        "distance_from_low_120",
        "distance_from_low_250",
        "drawdown_from_5d_high",
        "drawdown_from_10d_high",
        "drawdown_from_20d_high",
        "drawdown_from_60d_high",
        "drawdown_from_120d_high",
        "drawdown_from_250d_high",
        "max_drawdown_120",
        "max_drawdown_250",
        "vol_ma5",
        "vol_ma20",
        "vol_ma60",
        "amount_ma5",
        "amount_ma20",
        "amount_ma60",
        "volume_ratio_5_20",
        "amount_ratio_5_20",
        "today_volume_ratio_20",
        "atr14",
        "atr_pct",
        "rsi14",
        "rsi14_min_5",
        "rsi14_prev_min_5",
        "volatility_20",
        "prev_volatility_20",
        "volatility_contract",
        "close_position",
        "body_pct",
        "gap_pct",
        "low_3_not_falling",
        "low_5_not_falling",
        "range_contract_3",
        "near_high_60_pct",
        "break_5",
        "break_10",
        "strong_bullish_atr",
        "pullback_peak_120",
        "pullback_peak_age_120",
        "pullback_pct_120",
        "pullback_low_since_peak_120",
        "break_swing_low_pct",
        "last_swing_high",
        "previous_swing_high",
        "last_swing_low",
        "previous_swing_low",
        "higher_high",
        "higher_low",
        "lower_high",
        "lower_low",
        "break_last_swing_high",
        "position_250",
        "slope_60",
        "slope_20",
        "slope_10",
        "deceleration",
        "low_ratio",
        "atr20",
        "atr60",
        "atr_ratio",
        "compression",
        "volume_asymmetry",
        "distance_to_breakout",
    ]
    output: dict[str, Any] = {}
    for key in keys:
        if key not in row.index:
            continue
        value = row[key]
        if pd.isna(value):
            output[key] = None
        elif isinstance(value, (np.integer, np.floating)):
            output[key] = float(value)
        elif isinstance(value, np.bool_):
            output[key] = bool(value)
        else:
            output[key] = value
    return output


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    log_s = np.log(series.clip(lower=1e-6))
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()

    def get_slope(y: np.ndarray) -> float:
        if np.isnan(y).any():
            return np.nan
        return float(((x - x_mean) * (y - y.mean())).sum() / x_var)

    return log_s.rolling(window, min_periods=window).apply(get_slope, raw=True)


def _calc_deceleration(slope60: pd.Series, slope20: pd.Series) -> pd.Series:
    abs_s60 = slope60.abs()
    min_s20_0 = np.minimum(slope20, 0)
    abs_min_s20 = np.abs(min_s20_0)
    decel = np.where(slope60 < 0, 1.0 - abs_min_s20 / abs_s60.clip(lower=1e-8), np.nan)
    decel = np.where((slope60 < 0) & (slope20 >= 0), 1.0, decel)
    return pd.Series(decel, index=slope60.index)


def _calc_volume_asymmetry(pct_chg: pd.Series, amount: pd.Series, window: int = 20) -> pd.Series:
    up_amt = np.where(pct_chg > 0, amount, np.nan)
    down_amt = np.where(pct_chg < 0, amount, np.nan)
    s_up = pd.Series(up_amt, index=pct_chg.index).rolling(window, min_periods=1).mean()
    s_down = pd.Series(down_amt, index=pct_chg.index).rolling(window, min_periods=1).mean()
    ratio = s_up / s_down
    return ratio.replace([np.inf, -np.inf], np.nan)


def _rolling_max_drawdown(series: pd.Series, window: int) -> pd.Series:
    rolling_high = series.rolling(window, min_periods=window).max()
    drawdown = series / rolling_high - 1
    return drawdown.rolling(window, min_periods=1).min()


def _rolling_peak_age(series: pd.Series, window: int) -> pd.Series:
    def age(values: np.ndarray) -> float:
        if np.isnan(values).all():
            return np.nan
        return float(len(values) - int(np.nanargmax(values)))

    return series.rolling(window, min_periods=window).apply(age, raw=True)


def _latest_low_since_previous_peak(lows: pd.Series, highs: pd.Series, window: int) -> pd.Series:
    low_values = lows.to_numpy(dtype="float64")
    high_values = highs.to_numpy(dtype="float64")
    output = np.full(len(low_values), np.nan, dtype="float64")
    idx = len(low_values) - 1
    if idx < window:
        return pd.Series(output, index=lows.index)
    previous_highs = high_values[idx - window : idx]
    if np.isnan(previous_highs).any():
        return pd.Series(output, index=lows.index)
    peak_position = int(np.argmax(previous_highs))
    peak_idx = idx - window + peak_position
    window_lows = low_values[peak_idx : idx + 1]
    if not np.isnan(window_lows).any():
        output[idx] = float(np.min(window_lows))
    return pd.Series(output, index=lows.index)


def _rsi(series: pd.Series, window: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window, min_periods=window).mean()
    loss = (-delta.clip(upper=0)).rolling(window, min_periods=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def _add_swing_features(df: pd.DataFrame, pivot_window: int) -> pd.DataFrame:
    result = df.copy()
    highs = result["adj_high"]
    lows = result["adj_low"]
    centered_high = highs.rolling(2 * pivot_window + 1, center=True, min_periods=2 * pivot_window + 1).max()
    centered_low = lows.rolling(2 * pivot_window + 1, center=True, min_periods=2 * pivot_window + 1).min()
    confirmed_high = highs.where(highs == centered_high).shift(pivot_window)
    confirmed_low = lows.where(lows == centered_low).shift(pivot_window)

    last_high = confirmed_high.ffill()
    previous_high = confirmed_high.where(confirmed_high.notna()).ffill().shift(1)
    last_low = confirmed_low.ffill()
    previous_low = confirmed_low.where(confirmed_low.notna()).ffill().shift(1)

    result["last_swing_high"] = last_high
    result["previous_swing_high"] = previous_high
    result["last_swing_low"] = last_low
    result["previous_swing_low"] = previous_low
    result["higher_high"] = last_high > previous_high
    result["higher_low"] = last_low > previous_low
    result["lower_high"] = last_high < previous_high
    result["lower_low"] = last_low < previous_low
    result["break_last_swing_high"] = result["adj_close"] > last_high
    return result
