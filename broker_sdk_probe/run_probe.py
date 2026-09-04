import argparse
import datetime as dt
import importlib.metadata
import importlib.util
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from common.result import result
from common.security import mask_account, redact
from common.serializer import dump_json, to_jsonable
from gmtrade_probe.environment import inspect_surface
from gmtrade_probe.connection import login_readonly
from gmtrade_probe.readonly import query_readonly, query_default_cash


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SAMPLES = ROOT / "samples"


def command_text(command):
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        return {"returncode": completed.returncode, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}
    except Exception as exc:
        return {"returncode": None, "error": {"type": type(exc).__name__, "text": str(exc)}}


def environment_report():
    gm_version = None
    try:
        gm_version = importlib.metadata.version("gm")
    except importlib.metadata.PackageNotFoundError:
        pass
    gmtrade_version = None
    try:
        gmtrade_version = importlib.metadata.version("gmtrade")
    except importlib.metadata.PackageNotFoundError:
        pass
    return result(
        "PASS",
        platform={"system": platform.system(), "release": platform.release(), "version": platform.version(), "machine": platform.machine()},
        python={"executable": sys.executable, "version": platform.python_version()},
        packages={
            "gm": {"import": importlib.util.find_spec("gm") is not None, "version": gm_version},
            "gmtrade": {"import": importlib.util.find_spec("gmtrade") is not None, "version": gmtrade_version},
        },
        qmt_process_probe=command_text(["tasklist", "/FI", "IMAGENAME eq essence.exe", "/FO", "CSV", "/NH"]),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("environment", "api-surface", "readonly"), required=True)
    args = parser.parse_args()
    if args.mode == "environment":
        payload = environment_report()
        dump_json(REPORTS / "environment_report.json", payload)
    elif args.mode == "api-surface":
        payload = result("PASS", gmtrade=inspect_surface())
        dump_json(REPORTS / "api_surface_report.json", payload)
    else:
        config_path = ROOT / "config.local.json"
        if not config_path.exists():
            raise RuntimeError("CONFIG_NOT_FOUND")
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        for key in ("gm_token", "gmtrade_account_id", "endpoint", "test_account_type", "allow_order_test"):
            if key not in config:
                raise RuntimeError("CONFIG_KEY_MISSING:" + key)
        if config["test_account_type"] != "SIM":
            raise RuntimeError("ACCOUNT_TYPE_MUST_BE_SIM")
        if config["allow_order_test"] is not False:
            raise RuntimeError("ORDER_TEST_MUST_REMAIN_DISABLED")
        if not config["gm_token"] or not config["gmtrade_account_id"]:
            raise RuntimeError("CREDENTIAL_VALUE_MISSING")
        api, sdk_account = login_readonly(config)
        try:
            readonly = query_readonly(api, config["gmtrade_account_id"])
            readonly["get_cash_default_account"] = query_default_cash(api)
            readonly["sdk_version"] = {"status": "PASS", "value": api.get_version()}
            overall = "PASS" if all(item["status"] == "PASS" for item in readonly.values()) else "FAIL"
            payload = result(overall, account_id=mask_account(config["gmtrade_account_id"]), endpoint=config["endpoint"], readonly=readonly)
            dump_json(SAMPLES / "gmtrade_readonly.json", payload)
            dump_json(REPORTS / "gmtrade_readonly_report.json", payload)
        finally:
            try:
                api.stop()
            except SystemExit as exc:
                if exc.code not in (None, 0, 2):
                    raise
    print(json.dumps(redact(to_jsonable(payload)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
