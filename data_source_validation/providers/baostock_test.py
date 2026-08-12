from __future__ import annotations

import importlib.util


def is_configured() -> bool:
    return importlib.util.find_spec("baostock") is not None
