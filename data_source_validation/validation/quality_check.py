from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class QualityResult:
    rows: int
    duplicate_count: int
    invalid_ohlc_count: int
    invalid_volume_count: int
    invalid_amount_count: int
    null_required_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "duplicate_count": self.duplicate_count,
            "invalid_ohlc_count": self.invalid_ohlc_count,
            "invalid_volume_count": self.invalid_volume_count,
            "invalid_amount_count": self.invalid_amount_count,
            "null_required_count": self.null_required_count,
        }


def check_ohlc_frame(
    df: pd.DataFrame,
    key_columns: list[str],
    required_columns: list[str],
    volume_column: str | None = None,
    amount_column: str | None = None,
) -> QualityResult:
    if df is None:
        df = pd.DataFrame()
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        return QualityResult(
            rows=int(len(df)),
            duplicate_count=0,
            invalid_ohlc_count=0,
            invalid_volume_count=0,
            invalid_amount_count=0,
            null_required_count=len(missing),
        )

    work = df.copy()
    for column in ["open", "high", "low", "close", volume_column, amount_column]:
        if column and column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce")

    duplicate_count = int(work.duplicated(key_columns).sum()) if key_columns else 0
    null_required_count = int(work[required_columns].isna().any(axis=1).sum()) if required_columns else 0

    invalid_ohlc_count = 0
    if {"open", "high", "low", "close"}.issubset(work.columns):
        invalid_ohlc_count = int(
            (
                (work["high"] < work["low"])
                | (work["high"] < work["open"])
                | (work["high"] < work["close"])
                | (work["low"] > work["open"])
                | (work["low"] > work["close"])
                | (work[["open", "high", "low", "close"]] <= 0).any(axis=1)
            ).sum()
        )

    invalid_volume_count = 0
    if volume_column and volume_column in work.columns:
        invalid_volume_count = int((work[volume_column] < 0).sum())

    invalid_amount_count = 0
    if amount_column and amount_column in work.columns:
        invalid_amount_count = int((work[amount_column] < 0).sum())

    return QualityResult(
        rows=int(len(work)),
        duplicate_count=duplicate_count,
        invalid_ohlc_count=invalid_ohlc_count,
        invalid_volume_count=invalid_volume_count,
        invalid_amount_count=invalid_amount_count,
        null_required_count=null_required_count,
    )
