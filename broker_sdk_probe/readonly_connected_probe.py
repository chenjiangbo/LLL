import datetime as dt
import json
import time
from pathlib import Path

from gmtrade.api import account, get_cash, get_execution_reports, get_orders, get_positions, get_unfinished_orders, login, set_endpoint, set_token, start, stop
from common.serializer import to_jsonable

ROOT = Path(__file__).resolve().parent
EVENTS = []


def on_trade_data_connected():
    EVENTS.append({"event": "on_trade_data_connected", "received_at": dt.datetime.now(dt.timezone.utc).isoformat()})


def on_trade_data_disconnected():
    EVENTS.append({"event": "on_trade_data_disconnected", "received_at": dt.datetime.now(dt.timezone.utc).isoformat()})


def on_account_status(data):
    EVENTS.append({"event": "on_account_status", "received_at": dt.datetime.now(dt.timezone.utc).isoformat(), "payload": to_jsonable(data)})


def on_error(code, info):
    EVENTS.append({"event": "on_error", "received_at": dt.datetime.now(dt.timezone.utc).isoformat(), "code": code, "info": str(info)})


def main():
    config = json.loads((ROOT / "config.local.json").read_text(encoding="utf-8-sig"))
    if config["test_account_type"] != "SIM" or config["allow_order_test"] is not False:
        raise RuntimeError("UNSAFE_CONFIG")
    set_token(config["gm_token"])
    set_endpoint(config["endpoint"])
    login(account(account_id=config["gmtrade_account_id"]))
    result = {}
    try:
        start("readonly_connected_probe.py")
        time.sleep(3)
        sdk_account = config["gmtrade_account_id"]
        for name, function in (("get_cash", get_cash), ("get_positions", get_positions), ("get_orders", get_orders), ("get_unfinished_orders", get_unfinished_orders), ("get_execution_reports", get_execution_reports)):
            started = time.perf_counter()
            value = function(sdk_account)
            result[name] = {"is_none": value is None, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "value": to_jsonable(value)}
    finally:
        try:
            stop()
        except SystemExit as exc:
            if exc.code not in (None, 0, 2):
                raise
        output = {"events": EVENTS, "queries_after_start": result}
        (ROOT / "reports").mkdir(exist_ok=True)
        (ROOT / "reports" / "gmtrade_cash_diagnosis.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
