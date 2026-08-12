from __future__ import annotations

from typing import Any

import pandas as pd


def compare_ohlc(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_name: str,
    right_name: str,
    key_columns: list[str],
    tolerance: float,
) -> dict[str, Any]:
    if left is None or right is None or left.empty or right.empty:
        return {
            "left": left_name,
            "right": right_name,
            "status": "EMPTY_INPUT",
            "matched_rows": 0,
            "within_tolerance_ratio": 0.0,
        }
    merged = left.merge(right, on=key_columns, suffixes=("_left", "_right"))
    if merged.empty:
        return {
            "left": left_name,
            "right": right_name,
            "status": "NO_MATCH",
            "matched_rows": 0,
            "within_tolerance_ratio": 0.0,
        }
    diff_columns = []
    for column in ["open", "high", "low", "close"]:
        lcol = f"{column}_left"
        rcol = f"{column}_right"
        if lcol in merged.columns and rcol in merged.columns:
            merged[f"{column}_diff"] = (
                pd.to_numeric(merged[lcol], errors="coerce")
                - pd.to_numeric(merged[rcol], errors="coerce")
            ).abs()
            diff_columns.append(f"{column}_diff")
    if not diff_columns:
        return {
            "left": left_name,
            "right": right_name,
            "status": "NO_OHLC_COLUMNS",
            "matched_rows": int(len(merged)),
            "within_tolerance_ratio": 0.0,
        }
    max_diff = merged[diff_columns].max(axis=1)
    within = max_diff <= tolerance
    worst_idx = max_diff.idxmax()
    return {
        "left": left_name,
        "right": right_name,
        "status": "PASS" if bool(within.all()) else "DIFF",
        "matched_rows": int(len(merged)),
        "within_tolerance_ratio": round(float(within.mean()), 6),
        "max_diff": float(max_diff.max()),
        "max_diff_key": {column: str(merged.loc[worst_idx, column]) for column in key_columns},
    }
