from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return str(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def json_dump(payload: Any) -> str:
    return json.dumps(jsonable(payload), ensure_ascii=False, separators=(",", ":"))


def json_load(payload: str) -> Any:
    return json.loads(payload)
