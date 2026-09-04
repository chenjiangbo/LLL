import re


def mask_account(value):
    if value is None:
        return None
    text = str(value)
    return ("*" * max(0, len(text) - 4)) + text[-4:]


def redact(value):
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if key.lower() in {"token", "gm_token", "password", "trade_password"} else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and re.search(r"token|password", value, re.I):
        return "[REDACTED]"
    return value
