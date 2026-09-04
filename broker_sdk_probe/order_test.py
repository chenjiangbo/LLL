import datetime as dt
import json
import time
from pathlib import Path

from gmtrade.api import account, get_orders, login, order_cancel, order_volume, set_endpoint, set_token, start, stop
from common.serializer import to_jsonable

ROOT = Path(__file__).resolve().parent
EVENTS = []


def on_order_status(data):
    EVENTS.append({"event": "on_order_status", "received_at": dt.datetime.now(dt.timezone.utc).isoformat(), "payload": to_jsonable(data)})


def on_execution_report(data):
    EVENTS.append({"event": "on_execution_report", "received_at": dt.datetime.now(dt.timezone.utc).isoformat(), "payload": to_jsonable(data)})


def on_error(code, info):
    EVENTS.append({"event": "on_error", "received_at": dt.datetime.now(dt.timezone.utc).isoformat(), "code": code, "info": str(info)})


def main():
    config = json.loads((ROOT / "config.local.json").read_text(encoding="utf-8-sig"))
    if config["test_account_type"] != "SIM" or config["allow_order_test"] is not True:
        raise RuntimeError("ORDER_TEST_REQUIRES_SIM_AND_EXPLICIT_FLAG")
    set_token(config["gm_token"])
    set_endpoint(config["endpoint"])
    login(account(account_id=config["gmtrade_account_id"]))
    result = {"request": {"symbol": "SZSE.000661", "price": 74.20, "volume": 100, "side": 1, "order_type": 1, "position_effect": 1}, "events": EVENTS}
    try:
        start("order_test.py")
        time.sleep(2)
        started = time.perf_counter()
        orders = order_volume("SZSE.000661", 100, 1, 1, 1, price=74.20, account=config["gmtrade_account_id"])
        result["submit"] = {"elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "count": len(orders), "orders": [to_jsonable(item) for item in orders]}
        time.sleep(3)
        result["events"] = EVENTS
        result["orders_after_submit"] = [to_jsonable(item) for item in get_orders(config["gmtrade_account_id"])]
        cancel_requests = []
        for item in orders:
            if hasattr(item, "cl_ord_id") and item.cl_ord_id:
                cancel_requests.append({"cl_ord_id": item.cl_ord_id, "account_id": config["gmtrade_account_id"]})
        result["cancel_request_count"] = len(cancel_requests)
        if cancel_requests:
            order_cancel(cancel_requests)
            time.sleep(2)
        result["events_after_cancel"] = EVENTS
        result["orders_after_cancel"] = [to_jsonable(item) for item in get_orders(config["gmtrade_account_id"])]
    finally:
        try:
            stop()
        except SystemExit as exc:
            if exc.code not in (None, 0, 2):
                raise
        (ROOT / "reports").mkdir(exist_ok=True)
        (ROOT / "reports" / "gmtrade_order_test.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
