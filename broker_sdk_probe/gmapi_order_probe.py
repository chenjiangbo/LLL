"""Scheme B: one simulated limit order, then observe before any cancel."""

import json
from pathlib import Path

from gm.api import *


CONFIG = Path(__file__).with_name("config.local.json")


def _show_account(context, title):
    print(title, flush=True)
    acc = context.account()
    print("account =", repr(acc), flush=True)
    if acc is not None:
        print("status =", repr(acc.status), flush=True)
        print("cash =", repr(acc.cash), flush=True)
        print("positions =", repr(acc.positions()), flush=True)


def on_order_status(order):
    print("ORDER STATUS CALLBACK:", repr(order), flush=True)


def on_execution_report(report):
    print("EXECUTION REPORT CALLBACK:", repr(report), flush=True)


def on_error(code, info):
    print("ERROR CALLBACK:", code, info, flush=True)


def init(context):
    print("=== GM.API SIMULATED ORDER DIAGNOSTIC ===", flush=True)
    _show_account(context, "before order")

    # Small simulated order only: 100 shares, approximately CNY 7,420.
    result = order_volume(
        symbol="SZSE.000661",
        volume=100,
        side=OrderSide_Buy,
        order_type=OrderType_Limit,
        position_effect=PositionEffect_Open,
        price=74.20,
    )
    print("ORDER SUBMISSION RESULT:", repr(result), flush=True)

    # Do not cancel here. The launcher keeps the process alive so the user can
    # inspect the terminal and we can query the account after the submission.
    import time
    time.sleep(10)
    _show_account(context, "after 10 seconds")
    try:
        print("orders =", repr(get_orders()), flush=True)
    except Exception as exc:
        print("orders error:", repr(exc), flush=True)
    try:
        print("execution_reports =", repr(get_execution_reports()), flush=True)
    except Exception as exc:
        print("execution reports error:", repr(exc), flush=True)


if __name__ == "__main__":
    with CONFIG.open("r", encoding="utf-8-sig") as handle:
        cfg = json.load(handle)
    run(
        strategy_id=cfg["gm_strategy_id"],
        filename=Path(__file__).name,
        mode=MODE_LIVE,
        token=cfg["gm_token"],
    )
