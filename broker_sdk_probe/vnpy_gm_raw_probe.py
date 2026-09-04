"""A1: reproduce vnpy_gm 1.0.0 GmTdApi initialization without gmtrade.start()."""

import json
import sys
import time
from pathlib import Path

from gmtrade.api import account, get_cash, get_execution_reports, get_orders, get_positions, login, set_endpoint, set_token
from gmtrade.api.callback import callback_controller
from gmtrade.api.storage import ctx
from gmtrade.csdk.c_sdk import gmi_get_c_version, py_gmi_set_data_callback, py_gmi_start, py_gmi_stop
from gmtrade.__version__ import __version__


ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "reports" / "vnpy_gm_raw_probe.json"
EVENTS = []


def on_execution_report(data):
    item = {"type": "execution_report", "repr": repr(data)}
    EVENTS.append(item)
    print("EXECUTION REPORT:", item, flush=True)


def on_order_status(data):
    item = {"type": "order_status", "repr": repr(data)}
    EVENTS.append(item)
    print("ORDER STATUS:", item, flush=True)


def on_connected():
    EVENTS.append({"type": "connected"})
    print("CONNECTED", flush=True)


def on_disconnected():
    EVENTS.append({"type": "disconnected"})
    print("DISCONNECTED", flush=True)


def on_account_status(data):
    item = {
        "type": "account_status",
        "account_id": getattr(data, "account_id", None),
        "account_name": getattr(data, "account_name", None),
        "status": repr(getattr(data, "status", None)),
    }
    EVENTS.append(item)
    print("ACCOUNT STATUS:", item, flush=True)


def on_error(code, info):
    item = {"type": "error", "code": str(code), "info": str(info)}
    EVENTS.append(item)
    print("ERROR:", code, info, flush=True)


def main():
    config = json.loads((ROOT / "config.local.json").read_text(encoding="utf-8-sig"))
    token = config["gm_token"]
    account_id = config["gmtrade_account_id"]

    print("gmtrade version:", __version__, flush=True)
    print("c_sdk version:", gmi_get_c_version(), flush=True)
    set_token(token)
    set_endpoint()
    login(account(account_id))

    # This is the vnpy_gm 1.0.0 sequence, deliberately not gmtrade.start().
    ctx.inside_file_module = sys.modules[__name__]
    ctx.on_execution_report_fun = on_execution_report
    ctx.on_order_status_fun = on_order_status
    ctx.on_account_status_fun = on_account_status
    ctx.on_trade_data_connected_fun = on_connected
    ctx.on_trade_data_disconnected_fun = on_disconnected
    ctx.on_error_fun = on_error
    py_gmi_set_data_callback(callback_controller)

    status = py_gmi_start()
    print("py_gmi_start =", status, flush=True)
    time.sleep(3)

    values = {}
    for name, fn in (
        ("cash_default", get_cash),
        ("cash_by_id", lambda: get_cash(account_id)),
        ("positions", lambda: get_positions(account_id)),
        ("orders", lambda: get_orders(account_id)),
        ("execution_reports", lambda: get_execution_reports(account_id)),
    ):
        try:
            value = fn()
            values[name] = repr(value)
            print(name, "=", value, flush=True)
        except Exception as exc:
            values[name] = {"error": repr(exc)}
            print(name, "ERROR:", repr(exc), flush=True)

    result = {"sdk_version": __version__, "c_sdk_version": repr(gmi_get_c_version()), "start": status, "events": EVENTS, "values": values}
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    py_gmi_stop()


if __name__ == "__main__":
    main()
