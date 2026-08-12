from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any

import pandas as pd


def normalize_code(value: str) -> str:
    return str(value).strip().upper()


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return df.astype(object).where(pd.notna(df), None).to_dict(orient="records")


def json_dumps(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def json_loads(value: str) -> Any:
    return json.loads(value)


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if pd.isna(value):
        return None
    return value
