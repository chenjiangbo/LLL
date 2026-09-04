"""Read-only verification after the scheme-B simulated fill."""

import json
import time
from pathlib import Path

from gm.api import *


CONFIG = Path(__file__).with_name("config.local.json")


def on_order_status(context, order):
    print("ORDER STATUS CALLBACK:", repr(order), flush=True)


def on_execution_report(context, report):
    print("EXECUTION REPORT CALLBACK:", repr(report), flush=True)


def on_error(context, code, info):
    print("ERROR CALLBACK:", code, info, flush=True)


def init(context):
    print("=== GM.API POST-TRADE READONLY CHECK ===", flush=True)
    time.sleep(5)
    acc = context.account()
    print("status =", repr(acc.status), flush=True)
    print("cash(context) =", repr(acc.cash), flush=True)
    print("cash(query) =", repr(get_cash()), flush=True)
    print("positions(context) =", repr(acc.positions()), flush=True)
    print("orders =", repr(get_orders()), flush=True)
    print("execution_reports =", repr(get_execution_reports()), flush=True)


if __name__ == "__main__":
    with CONFIG.open("r", encoding="utf-8-sig") as handle:
        cfg = json.load(handle)
    run(
        strategy_id=cfg["gm_strategy_id"],
        filename=Path(__file__).name,
        mode=MODE_LIVE,
        token=cfg["gm_token"],
    )
