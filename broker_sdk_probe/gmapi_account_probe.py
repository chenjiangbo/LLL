"""Minimal official gm.api account-only diagnostic for the Guotou terminal."""

import json
from pathlib import Path

from gm.api import *


CONFIG = Path(__file__).with_name("config.local.json")


def _dump(label, value):
    print(label)
    print(repr(value))
    for name in ("state", "account_id", "account_name", "available", "nav", "cash", "positions"):
        try:
            print("  {} = {!r}".format(name, getattr(value, name)))
        except Exception:
            pass


def init(context):
    print("=== GM.API DIAGNOSTIC ===")
    try:
        _dump("account status:", context.account().status)
    except Exception as exc:
        print("status error:", repr(exc))
    try:
        _dump("account cash:", context.account().cash)
    except Exception as exc:
        print("cash error:", repr(exc))
    try:
        positions = context.account().positions()
        print("positions:")
        print(repr(positions))
        print("positions count =", len(positions))
    except Exception as exc:
        print("positions error:", repr(exc))


if __name__ == "__main__":
    with CONFIG.open("r", encoding="utf-8-sig") as handle:
        cfg = json.load(handle)
    run(
        strategy_id=cfg["gm_strategy_id"],
        # Guotou's bundled gm.api 3.0.186 imports an absolute Windows path
        # as a dotted module name; use the basename while keeping the script
        # in the working directory.
        filename=Path(__file__).name,
        mode=MODE_LIVE,
        token=cfg["gm_token"],
    )
