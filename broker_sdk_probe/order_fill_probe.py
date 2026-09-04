import datetime as dt
import json
import time
from pathlib import Path

from gmtrade.api import account, get_execution_reports, get_orders, get_positions, get_unfinished_orders, login, order_volume, set_endpoint, set_token, start, stop
from common.serializer import to_jsonable

ROOT = Path(__file__).resolve().parent


def main():
    config = json.loads((ROOT / "config.local.json").read_text(encoding="utf-8-sig"))
    if config["test_account_type"] != "SIM" or config["allow_order_test"] is not True:
        raise RuntimeError("ORDER_TEST_REQUIRES_SIM_AND_EXPLICIT_FLAG")
    set_token(config["gm_token"])
    set_endpoint(config["endpoint"])
    login(account(account_id=config["gmtrade_account_id"]))
    result = {"submitted_at": dt.datetime.now(dt.timezone.utc).isoformat(), "request": {"symbol": "SZSE.000661", "price": 74.20, "volume": 100, "side": 1, "order_type": 1, "position_effect": 1}}
    try:
        start("order_fill_probe.py")
        time.sleep(2)
        orders = order_volume("SZSE.000661", 100, 1, 1, 1, price=74.20, account=config["gmtrade_account_id"])
        result["submit"] = {"count": len(orders), "orders": [to_jsonable(item) for item in orders]}
        time.sleep(5)
        result["before_cancel"] = {
            "orders": [to_jsonable(item) for item in get_orders(config["gmtrade_account_id"])],
            "unfinished_orders": [to_jsonable(item) for item in get_unfinished_orders(config["gmtrade_account_id"])],
            "execution_reports": [to_jsonable(item) for item in get_execution_reports(config["gmtrade_account_id"])],
            "positions": [to_jsonable(item) for item in get_positions(config["gmtrade_account_id"])],
        }
    finally:
        try:
            stop()
        except SystemExit as exc:
            if exc.code not in (None, 0, 2):
                raise
        (ROOT / "reports").mkdir(exist_ok=True)
        (ROOT / "reports" / "gmtrade_order_before_cancel.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
