from __future__ import annotations


RATE_LIMIT_PATTERNS = (
    "频率超限",
    "访问频次",
    "每分钟",
    "每小时",
    "每秒",
    "1次/小时",
    "2次/天",
    "1次/",
    "rate limit",
    "tushare_rate_limit",
    "too many requests",
)

EMPTY_DATA_PATTERNS = (
    "returned empty data",
    "empty data",
    "empty dataframe",
)


def is_tushare_rate_limit_error(exc: BaseException | str) -> bool:
    message = str(exc).lower()
    return any(pattern.lower() in message for pattern in RATE_LIMIT_PATTERNS)


def is_empty_data_error(exc: BaseException | str) -> bool:
    message = str(exc).lower()
    return any(pattern.lower() in message for pattern in EMPTY_DATA_PATTERNS)
