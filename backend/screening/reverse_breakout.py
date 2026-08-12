from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from backend.screening.errors import ScreeningError
from backend.screening.storage import PostgresScreeningStore


@dataclass(frozen=True)
class ReverseBreakoutConfig:
    mode: str = "historical-window"
    start_date: str = "20260401"
    end_date: str = "20260806"
    top_n: int = 100
    resistance_lookback: int = 30
    touch_tolerance: float = 0.02
    min_touch_count: int = 2
    breakout_min_pct: float = 0.005
    preheat_min_ratio: float = 1.15
    breakout_amount_min_ratio: float = 1.30
    min_liquidity: float = 10_000_000.0
    exclude_st: bool = True
    max_extension_atr_exclude: float = 4.5


@dataclass
class ReverseBreakoutFinder:
    store: PostgresScreeningStore
    config: ReverseBreakoutConfig

    def run(self) -> dict[str, Any]:
        start_date = _normalize_date(self.config.start_date)
        end_date = _normalize_date(self.config.end_date)
        if start_date > end_date:
            raise ScreeningError("start_date cannot be later than end_date")

        history_start = _calendar_offset(start_date, days=420)
        history = self.store.load_history(end_date=end_date, min_start_date=history_start)
        if history.empty:
            raise ScreeningError(f"no local daily history found on or before end_date={end_date}")

        available_dates = sorted(str(v) for v in history["trade_date"].dropna().unique())
        scan_dates = [d for d in available_dates if start_date <= d <= end_date]
        if not scan_dates:
            latest = available_dates[-1] if available_dates else "none"
            raise ScreeningError(
                f"no local trading dates in scan window {start_date}~{end_date}; latest_loaded_date={latest}"
            )

        results: list[dict[str, Any]] = []
        reject_counts: dict[str, int] = {}
        scanned_events = 0
        scanned_assets = 0

        for asset_code, group in history.groupby("asset_code", sort=False):
            group = _prepare_asset_frame(group)
            if group.empty:
                continue
            asset_type = str(group["asset_type"].iloc[-1])
            if asset_type != "stock":
                continue
            name = str(group["name"].dropna().iloc[-1]) if group["name"].notna().any() else ""
            if self.config.exclude_st and "ST" in name.upper():
                continue

            scanned_assets += 1
            scan_idx = group.index[group["trade_date"].isin(scan_dates)].tolist()
            for idx in scan_idx:
                scanned_events += 1
                event = self._evaluate_event(group, idx)
                if event.get("accepted"):
                    results.append(event["row"])
                else:
                    reason = str(event["reject_reason"])
                    reject_counts[reason] = reject_counts.get(reason, 0) + 1

        results.sort(key=lambda item: (-item["total_score"], -item["breakout_amount_ratio"], item["trade_date"], item["ts_code"]))
        top = results[: self.config.top_n]
        return {
            "metadata": {
                **asdict(self.config),
                "start_date": start_date,
                "end_date": end_date,
                "effective_start_date": scan_dates[0],
                "effective_end_date": scan_dates[-1],
                "scanned_assets": scanned_assets,
                "scanned_events": scanned_events,
                "candidate_count": len(results),
                "returned_count": len(top),
            },
            "reject_counts": dict(sorted(reject_counts.items(), key=lambda item: item[0])),
            "items": top,
        }

    def _evaluate_event(self, df: pd.DataFrame, idx: int) -> dict[str, Any]:
        min_required = max(120, self.config.resistance_lookback + 25, 65)
        if idx < min_required:
            return {"accepted": False, "reject_reason": "DATA_INSUFFICIENT"}

        row = df.iloc[idx]
        prev = df.iloc[idx - 1]
        if not _valid_price_row(row):
            return {"accepted": False, "reject_reason": "NOT_TRADING"}

        amount_median20 = float(df["amount"].iloc[idx - 20 : idx].median())
        if amount_median20 <= 0 or np.isnan(amount_median20):
            return {"accepted": False, "reject_reason": "DATA_INSUFFICIENT"}
        if self.config.min_liquidity > 0 and amount_median20 < self.config.min_liquidity:
            return {"accepted": False, "reject_reason": "LIQUIDITY_LOW"}

        resistance_info = _detect_resistance(
            df.iloc[idx - self.config.resistance_lookback : idx],
            tolerance=self.config.touch_tolerance,
        )
        if resistance_info is None:
            return {"accepted": False, "reject_reason": "NO_RESISTANCE"}
        resistance, touch_count, cluster_spread = resistance_info
        if touch_count < self.config.min_touch_count:
            return {"accepted": False, "reject_reason": "TOUCH_COUNT_LOW"}
        if _resistance_invalidated(df.iloc[idx - self.config.resistance_lookback : idx], resistance, self.config.touch_tolerance):
            return {"accepted": False, "reject_reason": "RESISTANCE_INVALIDATED"}

        close = float(row["adj_close"])
        breakout_pct = close / resistance - 1
        if breakout_pct < self.config.breakout_min_pct:
            return {"accepted": False, "reject_reason": "NOT_BREAKOUT"}

        breakout_amount_ratio = float(row["amount"] / amount_median20)
        if breakout_amount_ratio < self.config.breakout_amount_min_ratio:
            return {"accepted": False, "reject_reason": "BREAKOUT_VOLUME_LOW"}

        features = _calc_features(df, idx, resistance, amount_median20, touch_count, cluster_spread)
        if features["amount_preheat_5_20"] < self.config.preheat_min_ratio:
            return {"accepted": False, "reject_reason": "PREHEAT_LOW"}
        if features["extension_atr"] > self.config.max_extension_atr_exclude:
            return {"accepted": False, "reject_reason": "EXTENSION_TOO_HIGH"}

        scores = _score_features(features)
        total_score = round(sum(scores.values()), 2)
        row_out = {
            "ts_code": str(row["asset_code"]),
            "name": str(row.get("name") or ""),
            "trade_date": str(row["trade_date"]),
            "total_score": total_score,
            "bonus_score": 0.0,
            "industry_l1": str(row.get("industry") or ""),
            "industry_l2": "",
            "concept_hits": "",
            "scores": scores,
            **features,
        }
        return {"accepted": True, "row": _jsonable_row(row_out)}


def _prepare_asset_frame(group: pd.DataFrame) -> pd.DataFrame:
    df = group.sort_values("trade_date").reset_index(drop=True).copy()
    numeric_columns = ["open", "high", "low", "close", "amount", "vol", "adj_factor"]
    for col in numeric_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if df.empty or df["adj_factor"].isna().any():
        return pd.DataFrame()
    latest_factor = float(df["adj_factor"].iloc[-1])
    if latest_factor <= 0:
        return pd.DataFrame()
    ratio = df["adj_factor"] / latest_factor
    for col in ["open", "high", "low", "close"]:
        df[f"adj_{col}"] = df[col] * ratio
    df["true_range"] = _true_range(df)
    raw = df["raw_json"] if "raw_json" in df.columns else None
    if raw is not None:
        df["industry"] = raw.apply(lambda value: (value or {}).get("industry") if isinstance(value, dict) else "")
    else:
        df["industry"] = ""
    return df


def _detect_resistance(window: pd.DataFrame, tolerance: float) -> tuple[float, int, float] | None:
    if len(window) < 10:
        return None
    highs = window["adj_high"].to_numpy(dtype=float)
    local_highs: list[float] = []
    for i in range(2, len(highs) - 2):
        center = highs[i]
        if not np.isfinite(center):
            continue
        if center >= np.nanmax(highs[i - 2 : i + 3]):
            local_highs.append(float(center))
    if len(local_highs) < 2:
        return None

    clusters: list[list[float]] = []
    for value in sorted(local_highs):
        placed = False
        for cluster in clusters:
            median = float(np.median(cluster))
            if abs(value / median - 1) <= tolerance:
                cluster.append(value)
                placed = True
                break
        if not placed:
            clusters.append([value])
    clusters = [c for c in clusters if len(c) >= 2]
    if not clusters:
        return None
    best = max(clusters, key=lambda c: (len(c), np.median(c)))
    resistance = float(np.median(best))
    spread = float((max(best) - min(best)) / resistance) if resistance > 0 else 0.0
    return resistance, len(best), spread


def _resistance_invalidated(window: pd.DataFrame, resistance: float, tolerance: float) -> bool:
    closes = window["adj_close"].to_numpy(dtype=float)
    above = closes > resistance * (1 + tolerance)
    consecutive = 0
    for flag in above:
        consecutive = consecutive + 1 if flag else 0
        if consecutive >= 2:
            return True
    return False


def _calc_features(
    df: pd.DataFrame,
    idx: int,
    resistance: float,
    amount_median20: float,
    touch_count: int,
    cluster_spread: float,
) -> dict[str, Any]:
    row = df.iloc[idx]
    prev = df.iloc[idx - 1]
    close = float(row["adj_close"])
    high120 = float(df["adj_high"].iloc[idx - 119 : idx + 1].max())
    low120 = float(df["adj_low"].iloc[idx - 119 : idx + 1].min())
    high60 = float(df["adj_high"].iloc[idx - 59 : idx + 1].max())
    low60 = float(df["adj_low"].iloc[idx - 59 : idx + 1].min())
    high20 = float(df["adj_high"].iloc[idx - 19 : idx + 1].max())
    low20 = float(df["adj_low"].iloc[idx - 19 : idx + 1].min())

    atr20 = float(df["true_range"].iloc[idx - 19 : idx + 1].mean())
    atr60 = float(df["true_range"].iloc[idx - 59 : idx + 1].mean())
    ma5 = float(df["adj_close"].iloc[idx - 4 : idx + 1].mean())
    ma10 = float(df["adj_close"].iloc[idx - 9 : idx + 1].mean())
    ma20 = float(df["adj_close"].iloc[idx - 19 : idx + 1].mean())
    ma5_prev3 = float(df["adj_close"].iloc[idx - 7 : idx - 2].mean())
    ma10_prev5 = float(df["adj_close"].iloc[idx - 14 : idx - 5].mean())
    day_range = float(row["adj_high"] - row["adj_low"])

    pre_amount = df["amount"].iloc[idx - 5 : idx]
    hot_days = int((pre_amount >= amount_median20 * 1.2).sum())
    amount_preheat = float(pre_amount.mean() / amount_median20)
    return {
        "position_120": _safe_ratio(close - low120, high120 - low120, default=0.5),
        "drawdown_120": close / high120 - 1 if high120 > 0 else 0.0,
        "resistance": resistance,
        "touch_count": touch_count,
        "resistance_cluster_spread": cluster_spread,
        "pre_break_distance": float(prev["adj_close"] / resistance - 1),
        "range20": _safe_ratio(high20 - low20, close),
        "range60": _safe_ratio(high60 - low60, close),
        "compression": _safe_ratio(_safe_ratio(high20 - low20, close), _safe_ratio(high60 - low60, close), default=1.0),
        "atr_compression": _safe_ratio(atr20, atr60, default=1.0),
        "amount_preheat_5_20": amount_preheat,
        "hot_days_5": hot_days,
        "breakout_pct": close / resistance - 1,
        "breakout_amount_ratio": float(row["amount"] / amount_median20),
        "close_location": _safe_ratio(close - float(row["adj_low"]), day_range, default=0.5),
        "body_pct": float((row["adj_close"] - row["adj_open"]) / row["adj_open"]) if float(row["adj_open"]) > 0 else 0.0,
        "ma5_slope": _safe_ratio(ma5, ma5_prev3, default=1.0) - 1,
        "ma10_slope": _safe_ratio(ma10, ma10_prev5, default=1.0) - 1,
        "extension_atr": _safe_ratio(close - ma20, atr20, default=0.0),
        "amount_median20": amount_median20,
    }


def _score_features(f: dict[str, Any]) -> dict[str, float]:
    low = max(_linear(-f["drawdown_120"], 0.10, 0.30), _reverse_linear(f["position_120"], 0.75, 0.35)) * 15
    touch = min(1.0, f["touch_count"] / 4) * 10
    distance = _distance_score(f["pre_break_distance"]) * 10
    stability = max(0.0, 1.0 - f["resistance_cluster_spread"] / 0.04) * 5
    compression = max(_reverse_linear(f["compression"], 0.95, 0.55), _reverse_linear(f["atr_compression"], 1.0, 0.75)) * 10
    preheat = _linear(f["amount_preheat_5_20"], 1.0, 1.6) * 14 + min(1.0, f["hot_days_5"] / 3) * 6
    breakout = (
        _linear(f["breakout_pct"], 0.005, 0.08) * 5
        + _linear(f["breakout_amount_ratio"], 1.3, 2.2) * 7
        + _linear(f["close_location"], 0.55, 0.9) * 4
        + _linear(f["body_pct"], 0.0, 0.06) * 4
    )
    ma = (
        (1.0 if f["ma5_slope"] > 0 else 0.0) * 3
        + (1.0 if f["ma10_slope"] >= 0 else 0.0) * 2
        + _reverse_linear(max(f["extension_atr"], 0.0), 4.5, 1.5) * 5
    )
    return {
        "low_context": round(low, 2),
        "resistance_quality": round(touch + distance + stability, 2),
        "compression": round(compression, 2),
        "preheat": round(preheat, 2),
        "breakout_quality": round(breakout, 2),
        "ma_extension": round(ma, 2),
    }


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["adj_close"].shift(1)
    return pd.concat(
        [
            df["adj_high"] - df["adj_low"],
            (df["adj_high"] - prev_close).abs(),
            (df["adj_low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _valid_price_row(row: pd.Series) -> bool:
    return all(float(row[k]) > 0 for k in ("adj_open", "adj_high", "adj_low", "adj_close", "amount"))


def _linear(value: float, start: float, full: float) -> float:
    if value <= start:
        return 0.0
    if value >= full:
        return 1.0
    return float((value - start) / (full - start))


def _reverse_linear(value: float, start: float, full: float) -> float:
    if value >= start:
        return 0.0
    if value <= full:
        return 1.0
    return float((start - value) / (start - full))


def _distance_score(value: float) -> float:
    if -0.05 <= value <= 0.0:
        return 1.0
    if -0.08 <= value < -0.05:
        return 0.75
    if -0.12 <= value < -0.08:
        return 0.35
    if 0.0 < value <= 0.03:
        return 0.45
    return 0.0


def _safe_ratio(a: float, b: float, default: float = 0.0) -> float:
    if b == 0 or not np.isfinite(a) or not np.isfinite(b):
        return default
    return float(a / b)


def _normalize_date(value: str) -> str:
    text = str(value).strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ScreeningError(f"invalid date: {value}")
    return text


def _calendar_offset(value: str, days: int) -> str:
    dt = datetime.strptime(value, "%Y%m%d").date() - timedelta(days=days)
    return dt.strftime("%Y%m%d")


def _jsonable_row(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, dict):
            result[key] = _jsonable_row(value)
        elif isinstance(value, (np.integer,)):
            result[key] = int(value)
        elif isinstance(value, (np.floating,)):
            result[key] = None if not np.isfinite(value) else float(value)
        elif isinstance(value, float):
            result[key] = None if not np.isfinite(value) else value
        else:
            result[key] = value
    return result
