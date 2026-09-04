import json
import time
from pathlib import Path

from gmtrade.api import *

ROOT = Path(__file__).resolve().parent
config = json.loads((ROOT / "config.local.json").read_text(encoding="utf-8-sig"))

set_token(config["gm_token"])

# 接入本地掘金终端
set_endpoint("")

acc = account(account_id=config["gmtrade_account_id"])


def on_trade_data_connected():
    print("SDK -> terminal connected")


def on_account_status(status):
    print("ACCOUNT STATUS:", status)


def on_error(code, info):
    print("ERROR:", code, info)


login(acc)

r = start(filename=__file__)
print("start =", r)

time.sleep(3)

print("cash(default) =", get_cash())
print("cash(id)      =", get_cash(acc.account_id))
print("positions     =", get_positions(acc.account_id))

input("press enter...")
