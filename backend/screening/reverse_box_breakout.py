from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.screening.errors import ScreeningError
from backend.screening.storage import PostgresScreeningStore


BOX_REJECT_REASONS = {
    "BOX_TREND_TOO_STRONG",
    "BOX_OCCUPANCY_LOW",
    "UPPER_TOUCH_LOW",
    "TOUCH_SPAN_SHORT",
    "BOX_WIDTH_INVALID",
}


@dataclass(frozen=True)
class ReverseBoxBreakoutConfig:
    mode: str = "box-breakout-v2"
    start_date: str = "20260101"
    end_date: str = "20260810"
    top_n: int = 300
    box_windows: list[int] = field(default_factory=lambda: [25, 30, 40, 50, 60, 80])
    touch_tolerance: float = 0.02
    min_box_width: float = 0.05
    max_box_width: float = 0.35
    min_inside_ratio: float = 0.70
    max_drift_ratio: float = 0.45
    max_efficiency_ratio: float = 0.50
    min_upper_touches: int = 2
    min_upper_touch_span: float = 0.35
    min_breakout_pct: float = 0.002
    max_breakout_pct: float = 0.08
    min_breakout_volume: float = 1.30
    exclude_st: bool = True
    export_dir: str = "data/screening/output"


@dataclass
class ReverseBoxBreakoutFinder:
    store: PostgresScreeningStore
    config: ReverseBoxBreakoutConfig

    def run(self) -> dict[str, Any]:
        start_date = _normalize_date(self.config.start_date)
        end_date = _normalize_date(self.config.end_date)
        if start_date > end_date:
            raise ScreeningError("start_date cannot be later than end_date")
        windows = sorted({int(w) for w in self.config.box_windows if int(w) >= 25})
        if not windows:
            raise ScreeningError("box_windows must include at least one window >= 25")

        history_start = _calendar_offset(start_date, days=520)
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
        near_misses: list[dict[str, Any]] = []
        reject_counts: dict[str, int] = {}
        seen_boxes: set[tuple[str, int, float, float]] = set()
        scanned_assets = 0
        scanned_events = 0

        for asset_code, group in history.groupby("asset_code", sort=False):
            df = _prepare_asset_frame(group)
            if df.empty or str(df["asset_type"].iloc[-1]) != "stock":
                continue
            name = str(df["name"].dropna().iloc[-1]) if df["name"].notna().any() else ""
            if self.config.exclude_st and "ST" in name.upper():
                continue

            scanned_assets += 1
            df["_amount_base20"] = df["amount"].rolling(20).median().shift(1)
            df["_breakout_volume0"] = df["amount"] / df["_amount_base20"]
            scan_mask = (
                df["trade_date"].isin(scan_dates)
                & (df.index >= max(windows) + 20)
                & (df["_breakout_volume0"] >= self.config.min_breakout_volume)
            )
            scan_idx = df.index[scan_mask].tolist()
            skipped_for_volume = int(df["trade_date"].isin(scan_dates).sum()) - len(scan_idx)
            if skipped_for_volume > 0:
                reject_counts["BREAKOUT_VOLUME_LOW"] = reject_counts.get("BREAKOUT_VOLUME_LOW", 0) + skipped_for_volume
            for idx in scan_idx:
                scanned_events += 1
                event = self._evaluate_event(df, idx, windows)
                if event.get("accepted"):
                    row = event["row"]
                    key = (
                        row["ts_code"],
                        int(row["box_window"]),
                        round(float(row["support"]), 2),
                        round(float(row["resistance"]), 2),
                    )
                    if key in seen_boxes:
                        reject_counts["DUPLICATE_BOX"] = reject_counts.get("DUPLICATE_BOX", 0) + 1
                        continue
                    seen_boxes.add(key)
                    results.append(row)
                elif event.get("near_miss"):
                    near_misses.append(event["row"])
                else:
                    reason = str(event.get("reject_reason") or "UNKNOWN")
                    reject_counts[reason] = reject_counts.get(reason, 0) + 1

        results.sort(key=lambda item: (-item["total_score"], item["trade_date"], item["ts_code"]))
        near_misses.sort(key=lambda item: (-item["total_score"], item["trade_date"], item["ts_code"]))
        top = results[: self.config.top_n]
        near_top = near_misses[: self.config.top_n]
        csv_paths = _export_rows(self.config.export_dir, start_date, end_date, results, near_misses)
        payload = {
            "metadata": {
                **asdict(self.config),
                "box_windows": windows,
                "start_date": start_date,
                "end_date": end_date,
                "effective_start_date": scan_dates[0],
                "effective_end_date": scan_dates[-1],
                "scanned_assets": scanned_assets,
                "scanned_events": scanned_events,
                "candidate_count": len(results),
                "near_miss_count": len(near_misses),
                "returned_count": len(top),
                "near_miss_returned_count": len(near_top),
                "strict_csv_path": csv_paths["strict"],
                "near_miss_csv_path": csv_paths["near_miss"],
            },
            "reject_counts": dict(sorted(reject_counts.items(), key=lambda item: item[0])),
            "items": top,
            "near_miss_items": near_top,
        }
        _export_payload(self.config.export_dir, start_date, end_date, payload)
        return payload

    def _evaluate_event(self, df: pd.DataFrame, idx: int, windows: list[int]) -> dict[str, Any]:
        if idx < max(windows) + 20:
            return {"accepted": False, "reject_reason": "DATA_INSUFFICIENT"}
        row = df.iloc[idx]
        if not _valid_price_row(row):
            return {"accepted": False, "reject_reason": "NOT_TRADING"}
        amount_base20 = float(row["_amount_base20"])
        if amount_base20 <= 0 or not np.isfinite(amount_base20):
            return {"accepted": False, "reject_reason": "DATA_INSUFFICIENT"}
        if float(row["amount"]) / amount_base20 < self.config.min_breakout_volume:
            return {"accepted": False, "reject_reason": "BREAKOUT_VOLUME_LOW"}

        close = float(row["adj_close"])
        viable_windows = []
        for window in windows:
            if idx - window < 0:
                continue
            high = df["adj_high"].iloc[idx - window : idx].to_numpy(dtype=float)
            resistance0 = float(np.quantile(high, 0.90))
            if resistance0 > 0 and 0.975 <= close / resistance0 <= 1.105:
                viable_windows.append(window)
        if not viable_windows:
            return {"accepted": False, "reject_reason": "NOT_BREAKOUT"}

        box_candidates = [
            _evaluate_box_window(df, idx, window, self.config)
            for window in viable_windows
        ]
        box_candidates = [item for item in box_candidates if item is not None]
        if not box_candidates:
            return {"accepted": False, "reject_reason": "DATA_INSUFFICIENT"}
        best_box = max(box_candidates, key=lambda item: item["box_score"])
        box_failures = _box_failures(best_box, self.config)

        event_features = _evaluate_breakout_event(df, idx, float(best_box["resistance"]), amount_base20, self.config)
        if event_features is None:
            return {"accepted": False, "reject_reason": "DATA_INSUFFICIENT"}
        event_failures = _event_failures(event_features, self.config)
        all_failures = box_failures + event_failures

        scores = {
            "box_score": round(float(best_box["box_score"]), 2),
            "breakout_score": round(_score_breakout(event_features, self.config), 2),
            "volume_score": round(_score_volume(event_features, self.config), 2),
        }
        total_score = round(scores["box_score"] * 0.60 + scores["breakout_score"] * 0.20 + scores["volume_score"] * 0.20, 2)
        row_out = _jsonable_row(
            {
                "ts_code": str(row["asset_code"]),
                "name": str(row.get("name") or ""),
                "trade_date": str(row["trade_date"]),
                "box_window": int(best_box["box_window"]),
                "box_start": str(best_box["box_start"]),
                "box_end": str(best_box["box_end"]),
                "support": best_box["support"],
                "resistance": best_box["resistance"],
                "box_width": best_box["box_width"],
                "inside_ratio": best_box["inside_ratio"],
                "drift_ratio": best_box["drift_ratio"],
                "efficiency_ratio": best_box["efficiency_ratio"],
                "upper_touch_count": best_box["upper_touch_count"],
                "lower_touch_count": best_box["lower_touch_count"],
                "upper_touch_span": best_box["upper_touch_span"],
                "preheat3": event_features["preheat3"],
                "preheat5": event_features["preheat5"],
                "hot_days5": event_features["hot_days5"],
                "breakout_pct": event_features["breakout_pct"],
                "breakout_volume": event_features["breakout_volume"],
                "close_location": event_features["close_location"],
                "body_pct": event_features["body_pct"],
                "gap_pct": event_features["gap_pct"],
                "box_score": scores["box_score"],
                "breakout_score": scores["breakout_score"],
                "volume_score": scores["volume_score"],
                "total_score": total_score,
                "bonus_score": _score_bonus(df, idx),
                "reject_reason": ",".join(all_failures),
                "industry_l1": str(row.get("industry") or ""),
            }
        )

        if not all_failures:
            return {"accepted": True, "row": row_out}
        if not event_failures and len(box_failures) == 1:
            return {"near_miss": True, "row": row_out}
        return {"accepted": False, "reject_reason": all_failures[0]}


def _evaluate_box_window(
    df: pd.DataFrame,
    idx: int,
    window: int,
    config: ReverseBoxBreakoutConfig,
) -> dict[str, Any] | None:
    box = df.iloc[idx - window : idx]
    if len(box) != window:
        return None
    close = box["adj_close"].to_numpy(dtype=float)
    high = box["adj_high"].to_numpy(dtype=float)
    low = box["adj_low"].to_numpy(dtype=float)
    if not np.all(np.isfinite(close)) or not np.all(np.isfinite(high)) or not np.all(np.isfinite(low)):
        return None

    resistance0 = float(np.quantile(high, 0.90))
    support0 = float(np.quantile(low, 0.10))
    local_high_idx = _local_extrema_indexes(high, is_high=True)
    local_low_idx = _local_extrema_indexes(low, is_high=False)
    local_highs = high[local_high_idx] if len(local_high_idx) else np.array([], dtype=float)
    local_lows = low[local_low_idx] if len(local_low_idx) else np.array([], dtype=float)
    resistance_candidates = local_highs[np.abs(local_highs / resistance0 - 1) <= config.touch_tolerance] if resistance0 > 0 else []
    support_candidates = local_lows[np.abs(local_lows / support0 - 1) <= config.touch_tolerance] if support0 > 0 else []
    resistance = float(np.median(resistance_candidates)) if len(resistance_candidates) else resistance0
    support = float(np.median(support_candidates)) if len(support_candidates) else support0
    if support <= 0 or resistance <= support:
        return None

    box_height = resistance - support
    box_width = resistance / support - 1
    x = np.arange(window, dtype=float)
    slope, intercept = np.polyfit(x, close, 1)
    drift_ratio = abs((intercept + slope * (window - 1)) - intercept) / box_height
    path = float(np.abs(np.diff(close)).sum())
    efficiency_ratio = abs(float(close[-1] - close[0])) / path if path > 0 else 0.0
    inside_ratio = float(((close >= support) & (close <= resistance)).mean())

    upper_touch_idx = np.array([i for i in local_high_idx if abs(high[i] / resistance - 1) <= config.touch_tolerance], dtype=int)
    lower_touch_idx = np.array([i for i in local_low_idx if abs(low[i] / support - 1) <= config.touch_tolerance], dtype=int)
    upper_touch_count = int(len(upper_touch_idx))
    lower_touch_count = int(len(lower_touch_idx))
    upper_touch_span = float((upper_touch_idx[-1] - upper_touch_idx[0]) / window) if upper_touch_count >= 2 else 0.0
    first_upper_touch_ratio = float(upper_touch_idx[0] / window) if upper_touch_count else 1.0
    last_upper_touch_ratio = float(upper_touch_idx[-1] / window) if upper_touch_count else 0.0
    prior_breakout_inside = _has_consecutive_above(close, resistance * 1.01, consecutive=2)
    ma20_drift = _ma20_drift(close, box_height)

    box_score = _score_box(
        window=window,
        box_width=box_width,
        inside_ratio=inside_ratio,
        drift_ratio=drift_ratio,
        efficiency_ratio=efficiency_ratio,
        upper_touch_count=upper_touch_count,
        lower_touch_count=lower_touch_count,
        upper_touch_span=upper_touch_span,
        first_upper_touch_ratio=first_upper_touch_ratio,
        last_upper_touch_ratio=last_upper_touch_ratio,
        prior_breakout_inside=prior_breakout_inside,
        ma20_drift=ma20_drift,
        config=config,
    )
    return {
        "box_window": window,
        "box_start": str(box["trade_date"].iloc[0]),
        "box_end": str(box["trade_date"].iloc[-1]),
        "support": support,
        "resistance": resistance,
        "box_width": box_width,
        "inside_ratio": inside_ratio,
        "drift_ratio": drift_ratio,
        "efficiency_ratio": efficiency_ratio,
        "upper_touch_count": upper_touch_count,
        "lower_touch_count": lower_touch_count,
        "upper_touch_span": upper_touch_span,
        "first_upper_touch_ratio": first_upper_touch_ratio,
        "last_upper_touch_ratio": last_upper_touch_ratio,
        "prior_breakout_inside": prior_breakout_inside,
        "ma20_drift": ma20_drift,
        "box_score": box_score,
    }


def _evaluate_breakout_event(
    df: pd.DataFrame,
    idx: int,
    resistance: float,
    amount_base20: float,
    config: ReverseBoxBreakoutConfig,
) -> dict[str, Any] | None:
    if idx < 20:
        return None
    row = df.iloc[idx]
    prev_close = float(df["adj_close"].iloc[idx - 1])
    close = float(row["adj_close"])
    open_ = float(row["adj_open"])
    high = float(row["adj_high"])
    low = float(row["adj_low"])
    day_range = high - low
    prev10 = df["adj_close"].iloc[max(0, idx - 10) : idx].to_numpy(dtype=float)
    return {
        "preheat3": float(df["amount"].iloc[idx - 3 : idx].mean() / amount_base20),
        "preheat5": float(df["amount"].iloc[idx - 5 : idx].mean() / amount_base20),
        "hot_days5": int((df["amount"].iloc[idx - 5 : idx] >= amount_base20 * 1.20).sum()),
        "breakout_pct": close / resistance - 1,
        "breakout_volume": float(row["amount"] / amount_base20),
        "close_location": _safe_ratio(close - low, day_range, default=0.5),
        "body_pct": (close - open_) / open_ if open_ > 0 else 0.0,
        "gap_pct": open_ / prev_close - 1 if prev_close > 0 else 0.0,
        "no_prior_breakout_10d": not _has_consecutive_above(prev10, resistance * (1 + config.min_breakout_pct), consecutive=2),
    }


def _box_failures(box: dict[str, Any], config: ReverseBoxBreakoutConfig) -> list[str]:
    failures: list[str] = []
    if not (config.min_box_width <= float(box["box_width"]) <= config.max_box_width):
        failures.append("BOX_WIDTH_INVALID")
    if float(box["inside_ratio"]) < config.min_inside_ratio:
        failures.append("BOX_OCCUPANCY_LOW")
    if float(box["drift_ratio"]) > config.max_drift_ratio or float(box["efficiency_ratio"]) > config.max_efficiency_ratio:
        failures.append("BOX_TREND_TOO_STRONG")
    if int(box["upper_touch_count"]) < config.min_upper_touches:
        failures.append("UPPER_TOUCH_LOW")
    if float(box["upper_touch_span"]) < config.min_upper_touch_span:
        failures.append("TOUCH_SPAN_SHORT")
    if bool(box["prior_breakout_inside"]):
        failures.append("NOT_FIRST_BREAKOUT")
    return failures


def _event_failures(event: dict[str, Any], config: ReverseBoxBreakoutConfig) -> list[str]:
    failures: list[str] = []
    breakout_pct = float(event["breakout_pct"])
    if breakout_pct < config.min_breakout_pct:
        failures.append("NOT_BREAKOUT")
    if breakout_pct > config.max_breakout_pct:
        failures.append("BREAKOUT_TOO_FAR")
    if not bool(event["no_prior_breakout_10d"]):
        failures.append("NOT_FIRST_BREAKOUT")
    if float(event["breakout_volume"]) < config.min_breakout_volume:
        failures.append("BREAKOUT_VOLUME_LOW")
    return failures


def _score_box(
    *,
    window: int,
    box_width: float,
    inside_ratio: float,
    drift_ratio: float,
    efficiency_ratio: float,
    upper_touch_count: int,
    lower_touch_count: int,
    upper_touch_span: float,
    first_upper_touch_ratio: float,
    last_upper_touch_ratio: float,
    prior_breakout_inside: bool,
    ma20_drift: float,
    config: ReverseBoxBreakoutConfig,
) -> float:
    horizontality = (
        _reverse_linear(drift_ratio, config.max_drift_ratio, 0.12) * 11
        + _reverse_linear(efficiency_ratio, config.max_efficiency_ratio, 0.18) * 9
    )
    touch_layout = (
        min(1.0, upper_touch_count / 3) * 6
        + min(1.0, lower_touch_count / 2) * 3
        + _linear(upper_touch_span, config.min_upper_touch_span, 0.65) * 4
        + (1.0 if first_upper_touch_ratio <= 0.60 else 0.0) * 1
        + (1.0 if last_upper_touch_ratio >= 0.50 else 0.0) * 1
    )
    inside = _linear(inside_ratio, config.min_inside_ratio, 0.88) * 8 + (0.0 if prior_breakout_inside else 2.0)
    duration = _linear(window, 25, 60) * 8 + (2.0 if window >= 40 else 0.0)
    width_midpoint = 0.18
    width = max(0.0, 1.0 - abs(box_width - width_midpoint) / width_midpoint) * 5
    ma_penalty = min(3.0, max(0.0, ma20_drift - 0.35) * 6)
    return round(max(0.0, min(60.0, horizontality + touch_layout + inside + duration + width - ma_penalty)), 2)


def _score_breakout(event: dict[str, Any], config: ReverseBoxBreakoutConfig) -> float:
    breakout_pct = float(event["breakout_pct"])
    effective = _linear(breakout_pct, config.min_breakout_pct, 0.025) * 6 + _reverse_linear(breakout_pct, config.max_breakout_pct, 0.035) * 4
    first = 5.0 if bool(event["no_prior_breakout_10d"]) else 0.0
    candle = _linear(float(event["close_location"]), 0.55, 0.9) * 3 + _linear(float(event["body_pct"]), 0.0, 0.05) * 2
    return max(0.0, min(20.0, effective + first + candle))


def _score_volume(event: dict[str, Any], config: ReverseBoxBreakoutConfig) -> float:
    preheat = max(_linear(float(event["preheat3"]), 1.0, 1.45), _linear(float(event["preheat5"]), 1.0, 1.35)) * 7
    hot_days = min(1.0, int(event["hot_days5"]) / 3) * 3
    breakout = _linear(float(event["breakout_volume"]), config.min_breakout_volume, 2.20) * 10
    return max(0.0, min(20.0, preheat + hot_days + breakout))


def _score_bonus(df: pd.DataFrame, idx: int) -> float:
    close = float(df["adj_close"].iloc[idx])
    start = max(0, idx - 249)
    high250 = float(df["adj_high"].iloc[start : idx + 1].max())
    low250 = float(df["adj_low"].iloc[start : idx + 1].min())
    position = _safe_ratio(close - low250, high250 - low250, default=0.5)
    drawdown = close / high250 - 1 if high250 > 0 else 0.0
    return round(_reverse_linear(position, 0.55, 0.20) * 4 + _linear(-drawdown, 0.10, 0.35) * 4, 2)


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
    df["industry"] = df["raw_json"].apply(lambda value: (value or {}).get("industry") if isinstance(value, dict) else "") if "raw_json" in df.columns else ""
    return df


def _local_extrema_indexes(values: np.ndarray, *, is_high: bool) -> np.ndarray:
    indexes: list[int] = []
    for i in range(2, len(values) - 2):
        center = float(values[i])
        if not np.isfinite(center):
            continue
        window = values[i - 2 : i + 3]
        if is_high and center >= float(np.nanmax(window)):
            indexes.append(i)
        if not is_high and center <= float(np.nanmin(window)):
            indexes.append(i)
    return np.array(indexes, dtype=int)


def _has_consecutive_above(values: np.ndarray, threshold: float, *, consecutive: int) -> bool:
    count = 0
    for value in values:
        count = count + 1 if float(value) > threshold else 0
        if count >= consecutive:
            return True
    return False


def _ma20_drift(close: np.ndarray, box_height: float) -> float:
    if len(close) < 30 or box_height <= 0:
        return 0.0
    ma20 = pd.Series(close).rolling(20).mean()
    end = float(ma20.iloc[-1])
    prev10 = float(ma20.iloc[-11])
    if not np.isfinite(end) or not np.isfinite(prev10):
        return 0.0
    return abs(end - prev10) / box_height


def _export_rows(
    export_dir: str,
    start_date: str,
    end_date: str,
    results: list[dict[str, Any]],
    near_misses: list[dict[str, Any]],
) -> dict[str, str]:
    root = Path(export_dir)
    root.mkdir(parents=True, exist_ok=True)
    strict_path = root / f"reverse_box_breakout_{start_date}_{end_date}.csv"
    near_path = root / f"reverse_box_breakout_near_miss_box_{start_date}_{end_date}.csv"
    pd.DataFrame(results).to_csv(strict_path, index=False)
    pd.DataFrame(near_misses).to_csv(near_path, index=False)
    return {"strict": str(strict_path), "near_miss": str(near_path)}


def _export_payload(export_dir: str, start_date: str, end_date: str, payload: dict[str, Any]) -> str:
    root = Path(export_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"reverse_box_breakout_{start_date}_{end_date}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def load_saved_reverse_box_breakout_result(
    *,
    start_date: str,
    end_date: str,
    export_dir: str = "data/screening/output",
    top_n: int = 300,
) -> dict[str, Any]:
    start = _normalize_date(start_date)
    end = _normalize_date(end_date)
    root = Path(export_dir)
    json_path = root / f"reverse_box_breakout_{start}_{end}.json"
    strict_path = root / f"reverse_box_breakout_{start}_{end}.csv"
    near_path = root / f"reverse_box_breakout_near_miss_box_{start}_{end}.csv"
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        payload["items"] = payload.get("items", [])[:top_n]
        payload["near_miss_items"] = payload.get("near_miss_items", [])[:top_n]
        payload.setdefault("metadata", {})
        payload["metadata"]["returned_count"] = len(payload["items"])
        payload["metadata"]["near_miss_returned_count"] = len(payload["near_miss_items"])
        payload["metadata"]["loaded_from_cache"] = True
        return payload
    if not strict_path.exists() or not near_path.exists():
        raise ScreeningError(f"saved reverse box breakout result not found for {start}~{end}")

    strict_df = pd.read_csv(strict_path)
    near_df = pd.read_csv(near_path)
    strict_items = _df_json_records(strict_df)
    near_items = _df_json_records(near_df)
    return {
        "metadata": {
            "mode": "box-breakout-v2",
            "start_date": start,
            "end_date": end,
            "effective_start_date": start,
            "effective_end_date": end,
            "scanned_assets": 0,
            "scanned_events": 0,
            "candidate_count": len(strict_items),
            "near_miss_count": len(near_items),
            "returned_count": min(top_n, len(strict_items)),
            "near_miss_returned_count": min(top_n, len(near_items)),
            "strict_csv_path": str(strict_path),
            "near_miss_csv_path": str(near_path),
            "loaded_from_cache": True,
        },
        "reject_counts": {},
        "items": strict_items[:top_n],
        "near_miss_items": near_items[:top_n],
    }


def _df_json_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    for col in ["trade_date", "box_start", "box_end"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda value: "" if pd.isna(value) else str(value).split(".")[0])
    records = df.replace({np.nan: None}).to_dict(orient="records")
    return [_jsonable_row(record) for record in records]


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
