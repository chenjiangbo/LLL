import argparse
import json
import time
from pathlib import Path

from gmtrade.api import *

ROOT = Path(__file__).resolve().parent
ACCOUNT_STATES = []
ERRORS = []


def on_trade_data_connected():
    print("SDK -> terminal connected", flush=True)


def on_account_status(status):
    item = {"account_id": getattr(status, "account_id", None), "account_name": getattr(status, "account_name", None), "status": str(getattr(status, "status", None))}
    ACCOUNT_STATES.append(item)
    print("ACCOUNT STATUS:", item, flush=True)


def on_error(code, info):
    ERRORS.append({"code": str(code), "info": str(info)})
    print("ERROR:", code, info, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", choices=("default", "empty", "localhost"), default="localhost")
    args = parser.parse_args()
    config = json.loads((ROOT / "config.local.json").read_text(encoding="utf-8-sig"))

    set_token(config["gm_token"])

    # 官方要求本地终端 endpoint 留空；国投环境另保留 localhost:7001 对比诊断。
    endpoint = {"default": "<SDK default>", "empty": "", "localhost": "localhost:7001"}[args.endpoint]
    if args.endpoint != "default":
        set_endpoint(endpoint)

    acc = account(account_id=config["gmtrade_account_id"])
    login(acc)

    # gmtrade 3.0.6 在 Windows 下不能解析绝对 __file__；使用同一文件名保持官方 start(filename=__file__) 的语义。
    start_result = start(filename=Path(__file__).name)
    print("start =", start_result, flush=True)

    time.sleep(3)

    cash_default = get_cash()
    cash_by_id = get_cash(acc.account_id)
    positions = get_positions(acc.account_id)
    result = {
        "endpoint": endpoint,
        "start": start_result,
        "account_states": ACCOUNT_STATES,
        "errors": ERRORS,
        "cash_default_is_none": cash_default is None,
        "cash_by_id_is_none": cash_by_id is None,
        "cash_default": repr(cash_default),
        "cash_by_id": repr(cash_by_id),
        "positions": [repr(item) for item in positions],
    }
    print("cash(default) =", cash_default, flush=True)
    print("cash(id)      =", cash_by_id, flush=True)
    print("positions     =", positions, flush=True)

    try:
        stop()
    except SystemExit as exc:
        if exc.code not in (None, 0, 2):
            raise
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / ("official_flow_" + args.endpoint + ".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
