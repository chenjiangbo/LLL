"""Scheme B: submit a deliberately non-marketable simulated order and cancel it."""

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
    print("=== GM.API CANCEL DIAGNOSTIC ===", flush=True)
    result = order_volume(
        symbol="SZSE.000661",
        volume=100,
        side=OrderSide_Buy,
        order_type=OrderType_Limit,
        position_effect=PositionEffect_Open,
        price=70.00,
    )
    print("ORDER SUBMISSION RESULT:", repr(result), flush=True)
    if not result:
        raise RuntimeError("simulated cancel-test order was not accepted by gm.api")

    submitted = result[0]
    cl_ord_id = submitted["cl_ord_id"]
    account_id = submitted["account_id"]
    # The Guotou simulation matcher may fill valid limit orders immediately.
    # Send the cancel request immediately to test the actual cancel API race.
    order_cancel({"cl_ord_id": cl_ord_id, "account_id": account_id})
    print("CANCEL REQUEST SENT IMMEDIATELY", flush=True)
    time.sleep(5)
    after = [item for item in get_orders() if item.get("cl_ord_id") == cl_ord_id]
    print("ORDER AFTER CANCEL:", repr(after), flush=True)


if __name__ == "__main__":
    with CONFIG.open("r", encoding="utf-8-sig") as handle:
        cfg = json.load(handle)
    run(
        strategy_id=cfg["gm_strategy_id"],
        filename=Path(__file__).name,
        mode=MODE_LIVE,
        token=cfg["gm_token"],
    )
