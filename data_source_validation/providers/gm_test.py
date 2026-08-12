from __future__ import annotations

import importlib.util
import os


def configuration_status() -> str:
    if not os.getenv("GM_TOKEN", "").strip():
        return "NOT_CONFIGURED"
    if importlib.util.find_spec("gm") is None:
        return "SDK_NOT_INSTALLED"
    return "CONFIGURED"
