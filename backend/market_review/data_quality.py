from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.market_review.config import FINAL_DATA_TIME, MARKET_CLOSE_TIME


STATUS_LABELS = {
    "intraday": "盘中临时复盘",
    "closing_pending": "收盘数据待确认",
    "final": "正式收盘数据",
    "partial": "部分数据缺失",
    "error": "关键数据异常",
}


def build_data_quality(
    trade_date: str,
    breadth: dict[str, Any],
    industry_summary: dict[str, Any],
    index_rows: list[dict[str, Any]],
    industry_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    missing_fields: list[str] = []
    errors: list[str] = []

    if breadth.get("limit_down_count") is None:
        missing_fields.append("market.sentiment.limit_down_count")
    if not breadth.get("captured_at"):
        missing_fields.append("meta.market_breadth_captured_at")
    if not industry_summary.get("captured_at"):
        missing_fields.append("meta.industry_summary_captured_at")

    expected_display = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    wrong_indices = [row["name"] for row in index_rows if row.get("date") != expected_display]
    wrong_industries = [row["name"] for row in industry_rows if str(row.get("date", "")).replace("-", "") != trade_date]
    if wrong_indices:
        errors.append(f"指数日期不一致: {wrong_indices}")
    if wrong_industries:
        errors.append(f"行业日期不一致: {wrong_industries[:10]}")

    breadth_capture_date = breadth.get("capture_trade_date")
    industry_capture_date = industry_summary.get("capture_trade_date")
    if breadth_capture_date and breadth_capture_date != trade_date:
        errors.append(f"市场快照采集日期为{breadth_capture_date}，报告日期为{trade_date}")
    if industry_capture_date and industry_capture_date != trade_date:
        errors.append(f"行业快照采集日期为{industry_capture_date}，报告日期为{trade_date}")

    captured_at = _parse_datetime(breadth.get("captured_at"))
    if errors:
        status = "error"
    elif missing_fields:
        status = "partial"
    elif captured_at is None:
        status = "partial"
    elif captured_at.time() < MARKET_CLOSE_TIME:
        status = "intraday"
    elif captured_at.time() < FINAL_DATA_TIME:
        status = "closing_pending"
    else:
        status = "final"

    return {
        "status": status,
        "label": STATUS_LABELS[status],
        "message": _status_message(status, missing_fields, errors),
        "is_final": status == "final",
        "missing_fields": missing_fields,
        "errors": errors,
        "snapshot_time": breadth.get("snapshot_time"),
        "captured_at": breadth.get("captured_at"),
        "industry_captured_at": industry_summary.get("captured_at"),
        "industry_taxonomy": "同花顺行业板块",
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed.astimezone(ZoneInfo("Asia/Shanghai"))


def _status_message(status: str, missing_fields: list[str], errors: list[str]) -> str:
    if status == "error":
        return "；".join(errors)
    if status == "partial":
        return "存在缺失字段：" + "、".join(missing_fields)
    if status == "intraday":
        return "当前为盘中快照，只能生成临时复盘。"
    if status == "closing_pending":
        return "市场已收盘，等待数据源完成最终更新。"
    return "关键数据日期一致，已通过正式收盘复盘检查。"
