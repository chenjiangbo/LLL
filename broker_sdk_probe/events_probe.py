import datetime as dt
import json
import time
from pathlib import Path

from gmtrade.api import account, login, set_endpoint, set_token, start, stop

ROOT = Path(__file__).resolve().parent
EVENTS = []


def record(name, payload=None):
    EVENTS.append({"event": name, "received_at": dt.datetime.now(dt.timezone.utc).isoformat(), "payload": str(payload) if payload is not None else None})


def on_trade_data_connected():
    record("on_trade_data_connected")


def on_trade_data_disconnected():
    record("on_trade_data_disconnected")


def on_account_status(data):
    record("on_account_status", data)


def on_error(code, info):
    record("on_error", {"code": code, "info": info})


def on_shutdown(data):
    record("on_shutdown", data)


def main():
    config = json.loads((ROOT / "config.local.json").read_text(encoding="utf-8-sig"))
    if config["test_account_type"] != "SIM" or config["allow_order_test"] is not False:
        raise RuntimeError("UNSAFE_CONFIG")
    set_token(config["gm_token"])
    set_endpoint(config["endpoint"])
    login(account(account_id=config["gmtrade_account_id"]))
    try:
        start("events_probe.py")
        time.sleep(15)
    finally:
        try:
            stop()
        except SystemExit as exc:
            if exc.code not in (None, 0, 2):
                raise
        (ROOT / "reports").mkdir(exist_ok=True)
        (ROOT / "reports" / "events_gmtrade.json").write_text(json.dumps(EVENTS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"event_count": len(EVENTS), "events": EVENTS}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
