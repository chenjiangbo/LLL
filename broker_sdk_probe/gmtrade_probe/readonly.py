import time

from common.serializer import to_jsonable


READ_METHODS = ("get_cash", "get_positions", "get_orders", "get_unfinished_orders", "get_execution_reports")


def query_readonly(api, account_id):
    trade = api
    output = {}
    for method_name in READ_METHODS:
        method = getattr(trade, method_name, None)
        if method is None:
            output[method_name] = {"status": "UNAVAILABLE"}
            continue
        started = time.perf_counter()
        try:
            value = method(account_id)
            value_json = to_jsonable(value)
            item_status = "FAIL" if value is None else "PASS"
            output[method_name] = {"status": item_status, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "value": value_json}
        except Exception as exc:
            output[method_name] = {"status": "FAIL", "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "error": {"type": type(exc).__name__, "text": str(exc)}}
    return output


def query_default_cash(api):
    started = time.perf_counter()
    try:
        value = api.get_cash()
        return {"status": "FAIL" if value is None else "PASS", "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "value": to_jsonable(value)}
    except Exception as exc:
        return {"status": "FAIL", "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "error": {"type": type(exc).__name__, "text": str(exc)}}
