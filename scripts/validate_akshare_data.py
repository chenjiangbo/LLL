#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import akshare as ak
import numpy as np
import pandas as pd


CORE_INDICES = {
    "沪深300": "sh000300",
    "中证500": "sh000905",
    "中证1000": "sh000852",
    "创业板指": "sz399006",
    "科创50": "sh000688",
}

CSI_WEIGHT_INDICES = {
    "沪深300": "000300",
    "中证500": "000905",
    "中证1000": "000852",
}

REQUIRED_INDEX_COLUMNS = {"date", "close", "amount"}
REQUIRED_SPOT_COLUMNS = {"代码", "名称", "涨跌幅", "成交额"}
REQUIRED_LIMIT_POOL_COLUMNS = {"代码", "名称", "涨跌幅", "所属行业"}
REQUIRED_INDUSTRY_COLUMNS = {"板块", "涨跌幅", "总成交额", "上涨家数", "下跌家数"}
REQUIRED_INDUSTRY_HIST_COLUMNS = {"日期", "收盘价", "成交额"}
REQUIRED_WEIGHT_COLUMNS = {"成分券代码", "成分券名称", "权重"}


def to_jsonable(value: Any) -> Any:
    if isinstance(value, (date, pd.Timestamp)):
        return str(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.DataFrame):
        return {
            "rows": int(len(value)),
            "columns": [str(column) for column in value.columns],
            "sample": value.head(3).astype(str).to_dict(orient="records"),
        }
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


def run_check(name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        details = fn()
        return {"name": name, "status": "ok", "details": to_jsonable(details)}
    except Exception as exc:
        return {
            "name": name,
            "status": "failed",
            "error": str(exc),
            "traceback": traceback.format_exc(limit=5),
        }


def require_columns(df: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required.difference(set(map(str, df.columns))))
    if missing:
        raise ValueError(f"{label} missing required columns: {missing}; columns={list(df.columns)}")
    if df.empty:
        raise ValueError(f"{label} returned empty dataframe")


def check_core_indices(start_date: str, end_date: str) -> dict[str, Any]:
    results = {}
    for name, symbol in CORE_INDICES.items():
        df = ak.stock_zh_index_daily_tx(symbol=symbol)
        require_columns(df, REQUIRED_INDEX_COLUMNS, f"stock_zh_index_daily_tx({symbol})")
        date_key = df["date"].astype(str).str.replace("-", "", regex=False)
        df = df[(date_key >= start_date) & (date_key <= end_date)]
        if df.empty:
            raise ValueError(f"stock_zh_index_daily_tx({symbol}) returned no rows in range {start_date}-{end_date}")
        results[name] = {
            "symbol": symbol,
            "source": "ak.stock_zh_index_daily_tx",
            "rows": len(df),
            "columns": list(df.columns),
            "first_date": df["date"].iloc[0],
            "last_date": df["date"].iloc[-1],
            "last_close": df["close"].iloc[-1],
            "last_amount": df["amount"].iloc[-1],
        }
    return results


def check_market_breadth_and_limits(limit_date: str) -> dict[str, Any]:
    df = ak.stock_zh_a_spot()
    require_columns(df, REQUIRED_SPOT_COLUMNS, "stock_zh_a_spot")
    pct = pd.to_numeric(df["涨跌幅"], errors="coerce")
    amount = pd.to_numeric(df["成交额"], errors="coerce")
    rising = int((pct > 0).sum())
    falling = int((pct < 0).sum())
    flat = int((pct == 0).sum())
    invalid_pct = int(pct.isna().sum())

    limit_up_df = ak.stock_zt_pool_em(date=limit_date)
    require_columns(limit_up_df, REQUIRED_LIMIT_POOL_COLUMNS, f"stock_zt_pool_em({limit_date})")

    limit_down_df = ak.stock_zt_pool_dtgc_em(date=limit_date)
    if not limit_down_df.empty:
        require_columns(limit_down_df, REQUIRED_LIMIT_POOL_COLUMNS, f"stock_zt_pool_dtgc_em({limit_date})")

    return {
        "spot_source": "ak.stock_zh_a_spot",
        "limit_up_source": "ak.stock_zt_pool_em",
        "limit_down_source": "ak.stock_zt_pool_dtgc_em",
        "limit_date": limit_date,
        "stock_count": len(df),
        "rising_count": rising,
        "falling_count": falling,
        "flat_count": flat,
        "invalid_pct_count": invalid_pct,
        "rising_ratio": round(rising / max(rising + falling + flat, 1), 6),
        "total_amount": float(amount.sum(skipna=True)),
        "limit_up_count": len(limit_up_df),
        "limit_down_count": len(limit_down_df),
        "limit_down_empty_columns": list(limit_down_df.columns),
        "spot_columns": list(df.columns),
        "limit_up_columns": list(limit_up_df.columns),
    }


def check_industry_boards(start_date: str, end_date: str) -> dict[str, Any]:
    board_df = ak.stock_board_industry_summary_ths()
    require_columns(board_df, REQUIRED_INDUSTRY_COLUMNS, "stock_board_industry_summary_ths")
    first_board = str(board_df.iloc[0]["板块"])

    hist_df = ak.stock_board_industry_index_ths(
        symbol=first_board,
        start_date=start_date,
        end_date=end_date,
    )
    require_columns(hist_df, REQUIRED_INDUSTRY_HIST_COLUMNS, f"stock_board_industry_index_ths({first_board})")

    return {
        "summary_source": "ak.stock_board_industry_summary_ths",
        "history_source": "ak.stock_board_industry_index_ths",
        "board_count": len(board_df),
        "board_columns": list(board_df.columns),
        "sample_board": first_board,
        "sample_board_up_count": board_df.iloc[0]["上涨家数"],
        "sample_board_down_count": board_df.iloc[0]["下跌家数"],
        "hist_rows": len(hist_df),
        "hist_columns": list(hist_df.columns),
        "hist_first_date": hist_df["日期"].iloc[0],
        "hist_last_date": hist_df["日期"].iloc[-1],
    }


def check_csi_components_and_weights() -> dict[str, Any]:
    results = {}
    for name, symbol in CSI_WEIGHT_INDICES.items():
        cons_df = ak.index_stock_cons_csindex(symbol=symbol)
        weight_df = ak.index_stock_cons_weight_csindex(symbol=symbol)
        require_columns(cons_df, {"成分券代码", "成分券名称"}, f"index_stock_cons_csindex({symbol})")
        require_columns(weight_df, REQUIRED_WEIGHT_COLUMNS, f"index_stock_cons_weight_csindex({symbol})")
        results[name] = {
            "symbol": symbol,
            "constituent_rows": len(cons_df),
            "weight_rows": len(weight_df),
            "weight_sum": round(float(weight_df["权重"].sum()), 6),
            "weight_columns": list(weight_df.columns),
            "top_weights": weight_df.sort_values("权重", ascending=False).head(5),
        }
    return results


def build_report(results: list[dict[str, Any]]) -> str:
    ok_count = sum(1 for item in results if item["status"] == "ok")
    failed_count = len(results) - ok_count
    lines = [
        "# AkShare 数据源验证报告",
        "",
        f"- 生成日期：{date.today().isoformat()}",
        f"- AkShare 版本：{ak.__version__}",
        f"- 检查项：{len(results)}",
        f"- 成功：{ok_count}",
        f"- 失败：{failed_count}",
        "",
        "## 检查结果",
        "",
    ]
    for item in results:
        status = "通过" if item["status"] == "ok" else "失败"
        lines.append(f"### {item['name']}：{status}")
        lines.append("")
        if item["status"] == "ok":
            lines.append("```json")
            lines.append(json.dumps(item["details"], ensure_ascii=False, indent=2))
            lines.append("```")
        else:
            lines.append(f"- 错误：{item['error']}")
            lines.append("")
            lines.append("```text")
            lines.append(item["traceback"])
            lines.append("```")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate AkShare interfaces for the market review MVP.")
    parser.add_argument("--start-date", default=(date.today() - timedelta(days=520)).strftime("%Y%m%d"))
    parser.add_argument("--end-date", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--limit-date", default="")
    parser.add_argument("--json-output", default="data/validation/akshare_validation.json")
    parser.add_argument("--report-output", default="docs/data/akshare_validation_report.md")
    args = parser.parse_args()

    limit_date = args.limit_date or args.end_date

    checks = [
        ("五大核心指数历史行情", lambda: check_core_indices(args.start_date, args.end_date)),
        ("市场广度与涨跌停统计", lambda: check_market_breadth_and_limits(limit_date)),
        ("同花顺行业板块行情", lambda: check_industry_boards(args.start_date, args.end_date)),
        ("中证指数成分与权重", check_csi_components_and_weights),
    ]
    results = [run_check(name, fn) for name, fn in checks]

    json_output = Path(args.json_output)
    report_output = Path(args.report_output)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.parent.mkdir(parents=True, exist_ok=True)

    json_output.write_text(json.dumps(to_jsonable(results), ensure_ascii=False, indent=2), encoding="utf-8")
    report_output.write_text(build_report(results), encoding="utf-8")

    failed = [item for item in results if item["status"] != "ok"]
    print(f"wrote {json_output}")
    print(f"wrote {report_output}")
    print(f"ok={len(results) - len(failed)} failed={len(failed)}")
    if failed:
        for item in failed:
            print(f"failed: {item['name']}: {item['error']}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
