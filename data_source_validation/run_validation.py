#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_source_validation.providers import akshare_test, baostock_test, gm_test
from data_source_validation.providers.tushare_test import (
    TushareValidation,
    five_year_start,
    three_year_start,
)
from data_source_validation.validation.compare import compare_ohlc
from data_source_validation.validation.quality_check import check_ohlc_frame


TUSHARE_STOCK_CODES = ["000001.SZ", "600519.SH", "300750.SZ", "688981.SH"]
ETF_CODES = ["510300.SH", "159915.SZ", "588000.SH", "513100.SH"]
INDEX_CODES = ["000300.SH", "399006.SZ", "000905.SH"]


def jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.DataFrame):
        return {
            "rows": int(len(value)),
            "columns": [str(column) for column in value.columns],
            "sample": jsonable(value.head(20).to_dict(orient="records")),
        }
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def status_from_exception(exc: Exception) -> str:
    message = str(exc).lower()
    if "permission" in message or "权限" in message or "积分" in message or "access" in message:
        return "PERMISSION_DENIED"
    if "timeout" in message or "timed out" in message:
        return "TIMEOUT"
    return "API_ERROR"


@dataclass
class Recorder:
    output_dir: Path
    results: list[dict[str, Any]]
    errors: list[dict[str, Any]]

    def run(
        self,
        api_id: str,
        provider: str,
        api_name: str,
        params: dict[str, Any],
        fn: Callable[[], Any],
        required: bool = False,
    ) -> Any:
        started = time.time()
        try:
            payload = fn()
            elapsed = round(time.time() - started, 3)
            rows = int(len(payload)) if isinstance(payload, pd.DataFrame) else None
            status = "EMPTY" if isinstance(payload, pd.DataFrame) and payload.empty else "PASS"
            self.results.append(
                {
                    "id": api_id,
                    "provider": provider,
                    "api": api_name,
                    "status": status,
                    "rows": rows,
                    "seconds": elapsed,
                    "params": params,
                    "required": required,
                }
            )
            if isinstance(payload, pd.DataFrame):
                self.save_sample(api_id, payload)
            return payload
        except Exception as exc:
            elapsed = round(time.time() - started, 3)
            status = status_from_exception(exc)
            item = {
                "id": api_id,
                "provider": provider,
                "api": api_name,
                "status": status,
                "rows": None,
                "seconds": elapsed,
                "params": params,
                "required": required,
                "error": str(exc),
            }
            self.results.append(item)
            self.errors.append({**item, "traceback": traceback.format_exc(limit=8)})
            if required:
                raise
            return None

    def save_sample(self, api_id: str, df: pd.DataFrame) -> None:
        raw_dir = self.output_dir / "raw_samples"
        raw_dir.mkdir(parents=True, exist_ok=True)
        df.head(50).to_csv(raw_dir / f"{api_id}.csv", index=False)


def normalize_tushare_daily(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["trade_date"] = out["trade_date"].astype(str)
    for column in ["open", "high", "low", "close", "vol", "amount"]:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def normalize_ak_daily(df: pd.DataFrame, ts_code: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["trade_date"] = out["trade_date"].astype(str).str.replace("-", "", regex=False)
    out["ts_code"] = ts_code
    for column in ["open", "high", "low", "close", "vol", "amount"]:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def matrix_status(results: list[dict[str, Any]], provider: str, ids: list[str]) -> str:
    matched = [item for item in results if item["provider"] == provider and item["id"] in ids]
    if not matched:
        return "NOT_TESTED"
    statuses = {item["status"] for item in matched}
    if statuses == {"NOT_TESTED"}:
        return "NOT_TESTED"
    if "PASS" in statuses and not (statuses - {"PASS"}):
        return "PASS"
    if "PASS" in statuses:
        return "LIMITED"
    if "PERMISSION_DENIED" in statuses:
        return "PAID_PERMISSION"
    return "FAIL"


def build_summary(
    output_dir: Path,
    results: list[dict[str, Any]],
    etf_decision: dict[str, Any],
    stock_quality: list[dict[str, Any]],
    etf_quality: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
) -> str:
    rows = [
        ["A股列表", matrix_status(results, "tushare", ["T01"]), "NOT_TESTED", "NOT_TESTED", "NOT_TESTED", "TuShare"],
        ["A股日K", matrix_status(results, "tushare", ["T02A", "T02B"]), matrix_status(results, "akshare", ["A01"]), matrix_status(results, "baostock", ["B01"]), matrix_status(results, "gm", ["G01"]), "TuShare"],
        ["A股复权", matrix_status(results, "tushare", ["T03"]), "LIMITED", matrix_status(results, "baostock", ["B01"]), matrix_status(results, "gm", ["G01"]), "TuShare"],
        ["换手/市值", matrix_status(results, "tushare", ["T04"]), "NOT_TESTED", "NOT_TESTED", "NOT_TESTED", "TuShare"],
        ["ETF列表", matrix_status(results, "tushare", ["E01", "E02"]), matrix_status(results, "akshare", ["A02"]), "NOT_TESTED", matrix_status(results, "gm", ["G02"]), "TuShare优先"],
        ["ETF日K", matrix_status(results, "tushare", ["E03", "E04"]), matrix_status(results, "akshare", ["A03"]), matrix_status(results, "baostock", ["B02"]), matrix_status(results, "gm", ["G02"]), etf_decision["recommended_etf_daily_source"]],
        ["ETF复权", matrix_status(results, "tushare", ["E05"]), matrix_status(results, "akshare", ["A03_QFQ"]), "NOT_TESTED", matrix_status(results, "gm", ["G02"]), etf_decision["recommended_etf_adjust_source"]],
        ["指数日K", matrix_status(results, "tushare", ["I01"]), "NOT_TESTED", "NOT_TESTED", "NOT_TESTED", "TuShare"],
        ["申万分类", matrix_status(results, "tushare", ["I02", "I03"]), "NOT_TESTED", "NOT_TESTED", "NOT_TESTED", "TuShare"],
        ["申万行业日K", matrix_status(results, "tushare", ["I04"]), "NOT_TESTED", "NOT_TESTED", "NOT_TESTED", "TuShare或暂缓"],
        ["ETF 30分钟", matrix_status(results, "tushare", ["E06"]), matrix_status(results, "akshare", ["A04"]), "NOT_TESTED", matrix_status(results, "gm", ["G02"]), "暂不作为第一版主源"],
    ]
    table = [
        "| 数据需求 | TuShare2200 | AKShare | BaoStock | 掘金 | 推荐主源 |",
        "|---|---|---|---|---|---|",
    ]
    table.extend("| " + " | ".join(row) + " |" for row in rows)
    recommendation = etf_decision["final_recommendation"]
    return "\n".join(
        [
            "# 数据源验证 summary",
            "",
            f"- 生成日期：{date.today().isoformat()}",
            "- 默认策略：TuShare 优先；AkShare 只用于 TuShare 缺失项补充和交叉核对。",
            f"- 接口测试数：{len(results)}",
            f"- 股票质量记录：{len(stock_quality)}",
            f"- ETF质量记录：{len(etf_quality)}",
            f"- 跨源比较记录：{len(comparisons)}",
            "",
            *table,
            "",
            "## 说明",
            "",
            "- PASS：本次真实调用成功。",
            "- FAIL：调用失败或核心质量检查未通过。",
            "- LIMITED：部分接口可用，但字段、权限、稳定性或覆盖范围不足。",
            "- PAID_PERMISSION：真实调用返回权限不足或积分限制。",
            "- NOT_TESTED：未测试或当前环境未配置。",
            "",
            f"最终建议：{recommendation}",
            "",
            f"详细 ETF 结论见 `{output_dir / 'ETF_DATA_DECISION.md'}`。",
        ]
    )


def build_etf_decision(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {item["id"]: item for item in results}
    fund_daily_ok = by_id.get("E03", {}).get("status") == "PASS"
    ak_etf_ok = by_id.get("A03", {}).get("status") == "PASS"
    fund_adj_ok = by_id.get("E05", {}).get("status") == "PASS"
    if fund_daily_ok:
        daily_source = "TuShare"
        recommendation = "维持TuShare 2200"
    elif ak_etf_ok:
        daily_source = "AKShare"
        recommendation = "暂不升级，采用TuShare + AKShare组合"
    else:
        daily_source = "待重新评估"
        recommendation = "建议升级TuShare 5000"
    return {
        "tushare_etf_list": by_id.get("E01", {}).get("status", "NOT_TESTED"),
        "fund_basic_filter": "YES_WITH_FILTER" if by_id.get("E01", {}).get("status") == "PASS" else "NO",
        "etf_basic": by_id.get("E02", {}).get("status", "NOT_TESTED"),
        "fund_daily": "AVAILABLE" if fund_daily_ok else "NOT_AVAILABLE",
        "fund_adj": by_id.get("E05", {}).get("status", "NOT_TESTED"),
        "akshare_etf_daily": by_id.get("A03", {}).get("status", "NOT_TESTED"),
        "baostock_etf": by_id.get("B02", {}).get("status", "NOT_TESTED"),
        "gm_etf": by_id.get("G02", {}).get("status", "NOT_TESTED"),
        "recommended_etf_daily_source": daily_source,
        "recommended_etf_adjust_source": "TuShare" if fund_adj_ok else ("AKShare" if ak_etf_ok else "待重新评估"),
        "final_recommendation": recommendation,
    }


def write_etf_decision(path: Path, decision: dict[str, Any]) -> None:
    lines = [
        "# ETF_DATA_DECISION",
        "",
        f"1. TuShare 2200能否获取ETF名单？{decision['tushare_etf_list']}",
        f"2. fund_basic能否可靠过滤出ETF？{decision['fund_basic_filter']}",
        f"3. etf_basic当前Token是否有权限？{decision['etf_basic']}",
        f"4. fund_daily当前Token是否有权限？{decision['fund_daily']}",
        f"5. fund_adj当前Token是否有权限？{decision['fund_adj']}",
        "6. ETF日K最早可以获取到什么时候？见 etf_quality.csv 的 first_date。",
        f"7. TuShare ETF日K如果没有权限，AKShare能否替代？{decision['akshare_etf_daily']}",
        "8. AKShare ETF日K和公开行情是否一致？本脚本记录跨源/质量结果；人工抽查结论需补充。",
        "9. AKShare ETF接口是否存在明显稳定性问题？见 api_matrix.csv 调用耗时与错误。",
        f"10. BaoStock是否支持ETF？{decision['baostock_etf']}",
        f"11. 掘金是否支持ETF且当前账号可用？{decision['gm_etf']}",
        f"12. 是否值得为了ETF升级TuShare到5000积分？{decision['final_recommendation']}",
        "13. 是否值得升级到8000积分？仅在 etf_basic 为 PAID_PERMISSION 且业务确实需要增强ETF元数据时再评估。",
        "14. 目前是否需要购买分钟行情权限？不需要，第一轮候选扫描不依赖30分钟数据。",
        "",
        f"明确建议：{decision['final_recommendation']}",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description="TuShare-first data source validation for A-share and ETF selection.")
    parser.add_argument("--output-dir", default="data_source_validation/output")
    parser.add_argument("--skip-akshare", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for TuShare-first validation")

    recorder = Recorder(output_dir=output_dir, results=[], errors=[])
    tushare = TushareValidation(token)
    stock_quality: list[dict[str, Any]] = []
    etf_quality: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []

    latest_trade_date = recorder.run("T05", "tushare", "trade_cal", {}, tushare.trade_cal, required=True)
    latest_completed = tushare.latest_completed_trade_date()
    end_date = latest_completed
    start_3y = three_year_start()
    start_5y = five_year_start()
    start_60d = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=100)).strftime("%Y%m%d")
    start_20d = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=35)).strftime("%Y%m%d")

    stock_basic = recorder.run("T01", "tushare", "stock_basic", {"list_status": "L"}, tushare.stock_basic, required=True)
    if isinstance(stock_basic, pd.DataFrame) and not stock_basic.empty:
        listed_dates = stock_basic["list_date"].dropna().astype(str)
        new_candidates = stock_basic[listed_dates >= (datetime.today() - timedelta(days=370)).strftime("%Y%m%d")]
        if not new_candidates.empty:
            TUSHARE_STOCK_CODES.append(str(new_candidates.iloc[0]["ts_code"]))
        st_candidates = stock_basic[stock_basic["name"].astype(str).str.contains("ST", na=False)]
        if not st_candidates.empty:
            TUSHARE_STOCK_CODES.append(str(st_candidates.iloc[0]["ts_code"]))

    daily_codes = list(dict.fromkeys(TUSHARE_STOCK_CODES))
    daily_history = recorder.run(
        "T02A",
        "tushare",
        "daily",
        {"codes": daily_codes, "start_date": start_3y, "end_date": end_date},
        lambda: tushare.daily_for_codes(daily_codes, start_3y, end_date),
        required=True,
    )
    if isinstance(daily_history, pd.DataFrame):
        stock_quality.append(
            {
                "provider": "tushare",
                "api": "daily",
                "scope": "sample_codes_3y",
                **check_ohlc_frame(
                    normalize_tushare_daily(daily_history),
                    ["ts_code", "trade_date"],
                    ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"],
                    "vol",
                    "amount",
                ).as_dict(),
            }
        )
    market_daily = recorder.run(
        "T02B",
        "tushare",
        "daily",
        {"trade_date": latest_completed},
        lambda: tushare.daily_by_trade_date(latest_completed),
        required=True,
    )
    if isinstance(market_daily, pd.DataFrame):
        stock_quality.append(
            {
                "provider": "tushare",
                "api": "daily",
                "scope": f"market_{latest_completed}",
                **check_ohlc_frame(
                    normalize_tushare_daily(market_daily),
                    ["ts_code", "trade_date"],
                    ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"],
                    "vol",
                    "amount",
                ).as_dict(),
            }
        )
    adj = recorder.run(
        "T03",
        "tushare",
        "adj_factor",
        {"codes": daily_codes[:4], "start_date": start_5y, "end_date": end_date},
        lambda: tushare.adj_factor_for_codes(daily_codes[:4], start_5y, end_date),
        required=True,
    )
    daily_basic = recorder.run(
        "T04",
        "tushare",
        "daily_basic",
        {"trade_date": latest_completed},
        lambda: tushare.daily_basic(latest_completed),
        required=True,
    )
    if isinstance(daily_basic, pd.DataFrame) and isinstance(market_daily, pd.DataFrame):
        merged = daily_basic.merge(market_daily[["ts_code", "close"]], on="ts_code", suffixes=("_basic", "_daily"))
        recorder.results.append(
            {
                "id": "T04_MATCH",
                "provider": "tushare",
                "api": "daily_basic_vs_daily",
                "status": "PASS" if len(merged) / max(len(market_daily), 1) >= 0.99 else "EMPTY",
                "rows": int(len(merged)),
                "seconds": 0,
                "params": {"trade_date": latest_completed},
                "required": True,
            }
        )

    for api_id, api_name, fn in [
        ("E01", "fund_basic", tushare.fund_basic),
        ("E02", "etf_basic", tushare.etf_basic),
        ("E03", "fund_daily", lambda: tushare.fund_daily_for_codes(ETF_CODES, start_20d, end_date)),
        ("E03_MARKET", "fund_daily", lambda: tushare.fund_daily_by_trade_date(latest_completed)),
        ("E04", "pro_bar", lambda: tushare.pro_bar_etf("510300.SH", start_20d, end_date)),
        ("E05", "fund_adj", lambda: tushare.fund_adj(ETF_CODES, start_5y, end_date)),
        ("E06", "etf_mins", lambda: tushare.etf_mins("510300.SH", latest_completed)),
        ("I01", "index_daily", lambda: tushare.index_daily(INDEX_CODES, start_20d, end_date)),
        ("I02", "index_classify", tushare.index_classify_sw),
    ]:
        payload = recorder.run(api_id, "tushare", api_name, {}, fn)
        if api_id in {"E03", "E04"} and isinstance(payload, pd.DataFrame):
            etf_quality.append(
                {
                    "provider": "tushare",
                    "api": api_name,
                    "scope": api_id,
                    "first_date": str(payload["trade_date"].min()) if "trade_date" in payload.columns and not payload.empty else "",
                    "last_date": str(payload["trade_date"].max()) if "trade_date" in payload.columns and not payload.empty else "",
                    **check_ohlc_frame(
                        normalize_tushare_daily(payload),
                        ["ts_code", "trade_date"],
                        ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"],
                        "vol",
                        "amount",
                    ).as_dict(),
                }
            )

    classify = next((item for item in recorder.results if item["id"] == "I02" and item["status"] == "PASS"), None)
    sample_sw_code = ""
    if classify:
        raw_file = output_dir / "raw_samples" / "I02.csv"
        if raw_file.exists():
            sw_df = pd.read_csv(raw_file)
            if not sw_df.empty and "index_code" in sw_df.columns:
                sample_sw_code = str(sw_df.iloc[0]["index_code"])
    if sample_sw_code:
        recorder.run("I03", "tushare", "index_member_all", {"l1_code": sample_sw_code}, lambda: tushare.index_member_all(l1_code=sample_sw_code))
        recorder.run("I04", "tushare", "sw_daily", {"ts_code": sample_sw_code}, lambda: tushare.sw_daily(sample_sw_code, start_20d, end_date))
    else:
        recorder.results.append({"id": "I03", "provider": "tushare", "api": "index_member_all", "status": "NOT_TESTED", "rows": None, "seconds": 0, "params": {}, "required": False})
        recorder.results.append({"id": "I04", "provider": "tushare", "api": "sw_daily", "status": "NOT_TESTED", "rows": None, "seconds": 0, "params": {}, "required": False})

    if not args.skip_akshare:
        ak_frames = []
        for code in daily_codes[:4]:
            symbol = code.split(".")[0]
            ak_payload = recorder.run(
                "A01",
                "akshare",
                "stock_zh_a_hist",
                {"symbol": symbol, "start_date": start_60d, "end_date": end_date},
                lambda symbol=symbol: akshare_test.stock_daily(symbol, start_60d, end_date),
            )
            if isinstance(ak_payload, pd.DataFrame):
                ak_norm = normalize_ak_daily(ak_payload, code)
                ak_frames.append(ak_norm)
                if isinstance(daily_history, pd.DataFrame):
                    ts_norm = normalize_tushare_daily(daily_history[daily_history["ts_code"] == code])
                    comparisons.append(compare_ohlc(ts_norm, ak_norm, "tushare.daily", "akshare.stock_zh_a_hist", ["ts_code", "trade_date"], 0.01))
        etf_spot = recorder.run("A02", "akshare", "fund_etf_spot_em", {}, akshare_test.etf_spot)
        for adjust, api_id in [("", "A03"), ("qfq", "A03_QFQ")]:
            etf_frames = []
            for code in ETF_CODES:
                symbol = code.split(".")[0]
                payload = recorder.run(
                    api_id,
                    "akshare",
                    "fund_etf_hist_em",
                    {"symbol": symbol, "adjust": adjust, "start_date": start_3y, "end_date": end_date},
                    lambda symbol=symbol, adjust=adjust: akshare_test.etf_daily(symbol, start_3y, end_date, adjust),
                )
                if isinstance(payload, pd.DataFrame):
                    norm = normalize_ak_daily(payload, code)
                    etf_frames.append(norm)
            if etf_frames:
                all_etf = pd.concat(etf_frames, ignore_index=True)
                etf_quality.append(
                    {
                        "provider": "akshare",
                        "api": f"fund_etf_hist_em:{adjust or 'none'}",
                        "scope": api_id,
                        "first_date": str(all_etf["trade_date"].min()),
                        "last_date": str(all_etf["trade_date"].max()),
                        **check_ohlc_frame(
                            all_etf,
                            ["ts_code", "trade_date"],
                            ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"],
                            "vol",
                            "amount",
                        ).as_dict(),
                    }
                )
        recorder.run("A04", "akshare", "fund_etf_hist_min_em", {"symbol": "510300"}, lambda: akshare_test.etf_30m("510300", start_20d, end_date))

    if baostock_test.is_configured():
        recorder.results.append({"id": "B01", "provider": "baostock", "api": "query_history_k_data_plus", "status": "NOT_TESTED", "rows": None, "seconds": 0, "params": {}, "required": False})
        recorder.results.append({"id": "B02", "provider": "baostock", "api": "query_history_k_data_plus_etf", "status": "NOT_TESTED", "rows": None, "seconds": 0, "params": {}, "required": False})
    else:
        recorder.results.append({"id": "B01", "provider": "baostock", "api": "module", "status": "NOT_TESTED", "rows": None, "seconds": 0, "params": {"reason": "SDK_NOT_INSTALLED"}, "required": False})
        recorder.results.append({"id": "B02", "provider": "baostock", "api": "module", "status": "NOT_TESTED", "rows": None, "seconds": 0, "params": {"reason": "SDK_NOT_INSTALLED"}, "required": False})

    gm_status = gm_test.configuration_status()
    recorder.results.append({"id": "G01", "provider": "gm", "api": "history", "status": "NOT_TESTED", "rows": None, "seconds": 0, "params": {"status": gm_status}, "required": False})
    recorder.results.append({"id": "G02", "provider": "gm", "api": "history_etf", "status": "NOT_TESTED", "rows": None, "seconds": 0, "params": {"status": gm_status}, "required": False})

    api_fields = ["id", "provider", "api", "status", "rows", "seconds", "required", "params", "error"]
    write_csv(output_dir / "api_matrix.csv", recorder.results, api_fields)
    write_csv(output_dir / "stock_quality.csv", stock_quality, ["provider", "api", "scope", "rows", "duplicate_count", "invalid_ohlc_count", "invalid_volume_count", "invalid_amount_count", "null_required_count"])
    write_csv(output_dir / "etf_quality.csv", etf_quality, ["provider", "api", "scope", "first_date", "last_date", "rows", "duplicate_count", "invalid_ohlc_count", "invalid_volume_count", "invalid_amount_count", "null_required_count"])
    write_csv(output_dir / "cross_source_compare.csv", comparisons, ["left", "right", "status", "matched_rows", "within_tolerance_ratio", "max_diff", "max_diff_key"])
    (output_dir / "errors.log").write_text(json.dumps(jsonable(recorder.errors), ensure_ascii=False, indent=2), encoding="utf-8")

    decision = build_etf_decision(recorder.results)
    write_etf_decision(output_dir / "ETF_DATA_DECISION.md", decision)
    (output_dir / "summary.md").write_text(
        build_summary(output_dir, recorder.results, decision, stock_quality, etf_quality, comparisons),
        encoding="utf-8",
    )
    (output_dir / "run_metadata.json").write_text(
        json.dumps(
            jsonable(
                {
                    "generated_at": datetime.now().isoformat(),
                    "python": sys.version,
                    "latest_completed_trade_date": latest_completed,
                    "providers": {"gm": gm_status, "baostock_installed": baostock_test.is_configured()},
                }
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"wrote validation outputs to {output_dir}")
    if any(item["required"] and item["status"] != "PASS" for item in recorder.results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
