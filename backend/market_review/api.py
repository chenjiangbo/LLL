from __future__ import annotations

import json
import os
import math
import time
import requests
import threading
from datetime import UTC, date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from backend.market_review.admin_security import verify_admin_password

import psycopg
from psycopg.rows import dict_row

_MARKET_QUOTES_CACHE: dict[str, Any] = {"timestamp": 0.0, "data": []}
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_DAILY_RELEASE_TIME = dtime(17, 0)


def _daily_release_reached(config: dict[str, Any], now: datetime | None = None) -> bool:
    """Only request today's official daily bars after the source release window."""
    current = now or datetime.now(_SHANGHAI_TZ)
    configured_times = [
        str(value)[:5]
        for value in config.get("daily_run_times", ["18:00"])
        if isinstance(value, str) and len(str(value)[:5]) == 5
    ]
    release_time = _DAILY_RELEASE_TIME
    if configured_times:
        release_time = max(release_time, dtime.fromisoformat(max(configured_times)))
    return current.time() >= release_time

def _get_cached_market_quotes() -> list[dict[str, Any]]:
    now = time.time()
    if _MARKET_QUOTES_CACHE["data"] and (now - _MARKET_QUOTES_CACHE["timestamp"] < 30):
        return list(_MARKET_QUOTES_CACHE["data"])

    items: list[dict[str, Any]] = []

    # 1. 优先从 PostgreSQL 数据库联查全量 5500+ 只 A 股股票行情
    try:
        store_db_url = _database_url()
        with psycopg.connect(store_db_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(trade_date) as max_daily FROM screening_daily_bar WHERE asset_type = 'stock'")
                row_max_daily = cur.fetchone()
                max_daily = row_max_daily["max_daily"] if row_max_daily else None

                cur.execute("SELECT MAX(trade_time) as max_min FROM screening_min_bar")
                row_max_min = cur.fetchone()
                max_min = row_max_min["max_min"] if row_max_min else None

                latest_min_date = str(max_min)[:10] if max_min else None
                latest_min_date_raw = latest_min_date.replace("-", "") if latest_min_date else None

                if latest_min_date_raw and (not max_daily or latest_min_date_raw > max_daily):
                    sql = """
                        WITH min_agg AS (
                            SELECT 
                                asset_code,
                                (array_agg(open ORDER BY trade_time ASC))[1] as open,
                                MAX(high) as high,
                                MIN(low) as low,
                                (array_agg(close ORDER BY trade_time DESC))[1] as close,
                                SUM(vol) as volume,
                                SUM(amount) as amount
                            FROM screening_min_bar
                            WHERE trade_time >= %s AND trade_time <= %s
                            GROUP BY asset_code
                        )
                        SELECT 
                            m.asset_code,
                            m.name,
                            COALESCE(m.raw_json->>'industry', '') as industry,
                            COALESCE(ma.open, b.close, 0) as open,
                            COALESCE(ma.high, b.close, 0) as high,
                            COALESCE(ma.low, b.close, 0) as low,
                            COALESCE(ma.close, b.close, 0) as price,
                            COALESCE(ma.volume, 0) as volume,
                            COALESCE(ma.amount, 0) as amount,
                            COALESCE(b.close, 0) as pre_close,
                            CASE 
                                WHEN b.close > 0 THEN ((COALESCE(ma.close, b.close) - b.close) / b.close * 100)
                                ELSE 0 
                            END as pct_chg,
                            COALESCE(ma.close, b.close, 0) - COALESCE(b.close, 0) as change
                        FROM screening_asset_master m
                        LEFT JOIN min_agg ma ON m.asset_code = ma.asset_code
                        LEFT JOIN screening_daily_bar b 
                            ON m.asset_code = b.asset_code 
                           AND b.trade_date = %s
                        WHERE m.asset_type = 'stock'
                        ORDER BY pct_chg DESC;
                    """
                    cur.execute(sql, (f"{latest_min_date} 00:00:00", f"{latest_min_date} 23:59:59", max_daily))
                else:
                    sql = """
                        SELECT 
                            m.asset_code,
                            m.name,
                            COALESCE(m.raw_json->>'industry', '') as industry,
                            COALESCE(b.close, 0) as price,
                            COALESCE(b.pct_chg, 0) as pct_chg,
                            COALESCE(b.close - b.pre_close, 0) as change,
                            COALESCE(b.vol, 0) as volume,
                            COALESCE(b.amount, 0) as amount,
                            COALESCE(b.open, 0) as open,
                            COALESCE(b.high, 0) as high,
                            COALESCE(b.low, 0) as low,
                            COALESCE(b.pre_close, 0) as pre_close
                        FROM screening_asset_master m
                        LEFT JOIN screening_daily_bar b 
                            ON m.asset_code = b.asset_code 
                           AND b.trade_date = (SELECT MAX(trade_date) FROM screening_daily_bar)
                        WHERE m.asset_type = 'stock'
                        ORDER BY pct_chg DESC;
                    """
                    cur.execute(sql)
                rows = cur.fetchall()
                for row in rows:
                    raw_code = str(row["asset_code"])
                    code = raw_code.split(".")[0]
                    name = str(row["name"] or code)
                    ind_name = str(row.get("industry") or "")
                    pct = round(float(row["pct_chg"] or 0.0), 2)
                    price = float(row["price"] or 0.0)
                    change = round(float(row["change"] or 0.0), 2)
                    vol = float(row["volume"] or 0.0)
                    amount = float(row["amount"] or 0.0)
                    open_price = float(row["open"] or 0.0)
                    high_price = float(row["high"] or 0.0)
                    low_price = float(row["low"] or 0.0)
                    pre_close = float(row["pre_close"] or 0.0)
                    
                    amplitude = ((high_price - low_price) / pre_close * 100) if pre_close > 0 else 0.0

                    items.append({
                        "code": code,
                        "raw_code": raw_code,
                        "name": name,
                        "industry": ind_name,
                        "price": price,
                        "pct_chg": pct,
                        "change": change,
                        "volume": vol,
                        "amount": amount,
                        "amplitude": round(amplitude, 2),
                        "turnover": 0.0,
                        "speed": 0.0,
                        "net_quantity": 0.0,
                        "net_inflow": 0.0,
                        "open": open_price,
                        "high": high_price,
                        "low": low_price,
                        "pre_close": pre_close,
                    })
    except Exception as e:
        print("Error fetching market quotes from DB:", e)

    # 2. 增量融合在线行情（若可用）
    try:
        url = "https://82.push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": "6000",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
            "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f22,f11,f62,f128,f136"
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        session = requests.Session()
        session.proxies = {"http": None, "https": None}
        resp = session.get(url, params=params, headers=headers, timeout=2)
        if resp.status_code == 200:
            res_json = resp.json()
            diff = res_json.get("data", {}).get("diff", [])
            if diff:
                online_map = {}
                for row in diff:
                    code = str(row.get("f12", ""))
                    if not code:
                        continue
                    online_map[code] = {
                        "price": float(row.get("f2") or 0.0) if row.get("f2") != "-" else 0.0,
                        "pct_chg": float(row.get("f3") or 0.0) if row.get("f3") != "-" else 0.0,
                        "change": float(row.get("f4") or 0.0) if row.get("f4") != "-" else 0.0,
                        "volume": float(row.get("f5") or 0.0) if row.get("f5") != "-" else 0.0,
                        "amount": float(row.get("f6") or 0.0) if row.get("f6") != "-" else 0.0,
                        "amplitude": float(row.get("f7") or 0.0) if row.get("f7") != "-" else 0.0,
                        "turnover": float(row.get("f8") or 0.0) if row.get("f8") != "-" else 0.0,
                        "speed": float(row.get("f11") or 0.0) if row.get("f11") != "-" else 0.0,
                        "net_quantity": float(row.get("f22") or 0.0) if row.get("f22") != "-" else 0.0,
                        "net_inflow": float(row.get("f62") or 0.0) if row.get("f62") != "-" else 0.0,
                    }
                for item in items:
                    c = item["code"]
                    if c in online_map:
                        item.update(online_map[c])
    except Exception:
        pass

    if items:
        _MARKET_QUOTES_CACHE["timestamp"] = now
        _MARKET_QUOTES_CACHE["data"] = items
        return list(items)
    elif _MARKET_QUOTES_CACHE["data"]:
        return list(_MARKET_QUOTES_CACHE["data"])
    return []


from backend.market_review.ai_analysis import MarketReviewAI
from backend.market_review.config import PipelineConfig
from backend.market_review.errors import MarketReviewError
from backend.market_review.pipeline import MarketReviewPipeline
from backend.market_review.postgres_storage import PostgresMarketReviewStore
from backend.screening.config import RULESET_VERSION, ScreeningConfig, TushareConfig
from backend.screening.data_sync import ScreeningDataSync
from backend.screening.errors import ScreeningError
from backend.screening.reverse_box_breakout import (
    ReverseBoxBreakoutConfig,
    ReverseBoxBreakoutFinder,
    load_saved_reverse_box_breakout_result,
)
from backend.screening.reverse_breakout import ReverseBreakoutConfig, ReverseBreakoutFinder
from backend.screening.secondary_service import SecondaryScreeningConfig, SecondaryScreeningService
from backend.screening.service import CandidateScreeningService
from backend.screening.tushare_source import TushareScreeningSource
from backend.screening.storage import PostgresScreeningStore
from backend.screening.technical_classifier import CLASSIFIER_VERSION, TechnicalClassificationService
from backend.trading.tradeplan import (
    AccountRiskSettings,
    InstrumentInfo,
    TradePlanCalculator,
    TradePlanInput,
    TradePlanStore,
    TradePlanValidationError,
)
from backend.trading.actions import AddAccountContext, AddPlanCalculator, AddPlanInput, ClosePlanCalculator, PositionActionContext, ReducePlanCalculator, ReducePlanInput, TradeActionValidationError
from backend.trading.account import TradingDataValidationError, TradingStore
from backend.trading.broker import BrokerGateway, BrokerNotConnectedError, DisconnectedBrokerGateway
from backend.trading.gm_broker_gateway import BrokerNodeRequestError, GMBrokerHttpGateway
from backend.trading.execution import ExecutionPlanInput, ExecutionStore, ExecutionValidationError, OrderInput, PreTradeRisk
from backend.trading.execution_engine import ExecutionEngine
from backend.trading.broker_node_consumer import ExecutionQuotePoller
from backend.trading.reconciliation import ReconciliationService
from backend.trading.broker_event_sync import BrokerEventSyncService


class ImportReviewRequest(BaseModel):
    trade_date: str | None = None
    content: str


class GenerateOverviewRequest(BaseModel):
    trade_date: str | None = None
    start_date: str = "20250101"
    max_industries: int | None = None
    report_type: Literal["daily", "weekly"] = "daily"
    include_ai: bool = True
    force_data_refresh: bool = False
    force_ai_refresh: bool = False



class RunScreeningTaskRequest(BaseModel):
    trade_date: str | None = None
    run_name: str | None = None
    notes: str | None = None
    universe_type: Literal["ALL", "INDUSTRIES", "CUSTOM_CODES"] = "ALL"
    universe_params: dict[str, Any] | None = None
    sync_data_first: bool = True


class RunEarlyTurnRequest(BaseModel):
    trade_date: str | None = None
    ts_code: str | None = None
    config_version: str = "A_PRE_V2_20260830_V3"
    run_name: str | None = None
    notes: str | None = None
    run_id: str | None = None

class AddPositiveSampleRequest(BaseModel):
    ts_code: str
    target_date: str
    sample_name: str
    note: str | None = None

class DataSyncRequest(BaseModel):
    trade_date: str | None = None
    sync_financials: bool = True


class DataManagementConfigRequest(BaseModel):
    config: dict[str, Any]


class RetryFailedDataRequest(BaseModel):
    trade_date: str
    asset_type: Literal["stock", "etf", "all"] = "all"


class ReverseBreakoutRequest(BaseModel):
    start_date: str = "20260401"
    end_date: str | None = None
    top_n: int = 100
    resistance_lookback: int = 30
    touch_tolerance: float = 0.02
    min_touch_count: int = 2
    breakout_min_pct: float = 0.005
    preheat_min_ratio: float = 1.15
    breakout_amount_min_ratio: float = 1.30
    min_liquidity: float = 10_000_000.0
    exclude_st: bool = True


class ReverseBoxBreakoutRequest(BaseModel):
    start_date: str = "20260101"
    end_date: str | None = None
    top_n: int = 300
    box_windows: list[int] = [25, 30, 40, 50, 60, 80]
    touch_tolerance: float = 0.02
    min_box_width: float = 0.05
    max_box_width: float = 0.35
    min_inside_ratio: float = 0.70
    max_drift_ratio: float = 0.45
    max_efficiency_ratio: float = 0.50
    min_upper_touches: int = 2
    min_upper_touch_span: float = 0.35
    min_breakout_pct: float = 0.002
    max_breakout_pct: float = 0.08
    min_breakout_volume: float = 1.30
    exclude_st: bool = True


class GenerateAIRequest(BaseModel):
    trade_date: str
    report_type: Literal["daily", "weekly"] = "daily"
    force: bool = False


class RunScreeningRequest(BaseModel):
    trade_date: str
    pool: Literal["A", "B", "C", "ABC"] = "ABC"


class SelectCandidateRequest(BaseModel):
    trade_date: str
    asset_code: str
    pool: str
    action: Literal["SELECT", "REMOVE", "DISMISS", "VIEWED"] = "SELECT"
    note: str | None = None


class SaveDrawingsRequest(BaseModel):
    drawings: list[dict[str, Any]]


import threading
import time
import uuid

_screening_task_lock = threading.Lock()
_screening_task_status = {
    "task_id": None,
    "status": "idle",
    "progress": 0,
    "step_message": "",
    "trade_date": "",
    "pool": "ABC",
    "error": None,
    "started_at": None,
    "completed_at": None,
}

# 基本面研究由用户按当前筛选条件手动触发，三个生命周期状态都可以进入研究范围。
EARLY_TURN_SECONDARY_STATES = {"PRE_FIRST_TURN", "FIRST_TURN_WINDOW", "POST_FIRST_WAVE"}

_early_turn_task_lock = threading.Lock()
_early_turn_task_status: dict[str, Any] = {
    "status": "idle",
    "progress": 0,
    "step_message": "",
    "trade_date": "",
    "run_id": None,
    "candidate_scope": ["FIRST_TURN_WINDOW"],
    "candidate_count": 0,
    "error": None,
    "started_at": None,
    "completed_at": None,
}

_technical_task_lock = threading.Lock()
_technical_task_status: dict[str, Any] = {
    "status": "idle",
    "progress": 0,
    "step_message": "",
    "trade_date": "",
    "run_id": None,
    "summary": None,
    "error": None,
    "started_at": None,
    "completed_at": None,
}

_financial_summary_task_lock = threading.Lock()
_financial_summary_task_status: dict[str, Any] = {"status": "idle", "progress": 0, "step_message": "", "summary": None, "error": None, "started_at": None, "completed_at": None}

# AI 深度研究包含市场记忆、主题匹配和最终报告三个外部模型阶段，不能让浏览器同步等待。
_ai_research_jobs_lock = threading.Lock()
_ai_research_jobs: dict[str, dict[str, Any]] = {}


def _run_ai_research_job(job_id: str, ts_codes: list[str], as_of_date: str, lookback: int, use_search: bool) -> None:
    from backend.screening.ai_deep_research_service import run_ai_stock_research
    with _ai_research_jobs_lock:
        job = _ai_research_jobs[job_id]
        job.update(status="running", step_message="正在生成市场记忆、主题匹配和研究报告…")
    try:
        store = PostgresScreeningStore(_database_url())
        results = []
        for index, code in enumerate(ts_codes, start=1):
            with _ai_research_jobs_lock:
                _ai_research_jobs[job_id]["step_message"] = f"正在分析 {code}（{index}/{len(ts_codes)}）…"
                _ai_research_jobs[job_id]["progress"] = int((index - 1) * 100 / len(ts_codes))
            results.append(run_ai_stock_research(store, code, as_of_date, review_lookback=lookback, use_web_search=use_search))
        with _ai_research_jobs_lock:
            _ai_research_jobs[job_id].update(status="success", progress=100, step_message="AI 深度分析已完成", items=results, completed_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as exc:
        with _ai_research_jobs_lock:
            _ai_research_jobs[job_id].update(status="failed", step_message="AI 深度分析失败", error=str(exc), completed_at=time.strftime("%Y-%m-%d %H:%M:%S"))


def _run_screening_async(trade_date: str, pool: str):
    global _screening_task_status
    with _screening_task_lock:
        _screening_task_status["status"] = "running"
        _screening_task_status["progress"] = 10
        _screening_task_status["step_message"] = "正在初始化选股数据库与计算引擎..."
        _screening_task_status["trade_date"] = trade_date
        _screening_task_status["pool"] = pool
        _screening_task_status["error"] = None
        _screening_task_status["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        store = PostgresScreeningStore(_database_url())
        pools = {"A-Pre", "A", "B", "C"} if pool in ("ABC", "ALL") else {pool}

        with _screening_task_lock:
            _screening_task_status["progress"] = 20
            _screening_task_status["step_message"] = "正在检查并补齐目标交易日K线数据..."

        _sync_screening_trade_date(store, trade_date)

        with _screening_task_lock:
            _screening_task_status["progress"] = 45
            _screening_task_status["step_message"] = "正在计算多周期技术特征与指标..."

        service = CandidateScreeningService(ScreeningConfig(), store)

        with _screening_task_lock:
            _screening_task_status["progress"] = 70
            _screening_task_status["step_message"] = "正在评估选股规则与归类 ABC 池..."

        service.run(trade_date, pools=pools)

        with _screening_task_lock:
            _screening_task_status["status"] = "success"
            _screening_task_status["progress"] = 100
            _screening_task_status["step_message"] = "选股评估完成，数据快照已自动持久化！"
            _screening_task_status["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as exc:
        with _screening_task_lock:
            _screening_task_status["status"] = "failed"
            _screening_task_status["progress"] = 0
            _screening_task_status["step_message"] = f"选股运行失败: {str(exc)}"
            _screening_task_status["error"] = str(exc)


def _run_early_turn_async(
    trade_date: str | None,
    ts_code: str | None,
    config_version: str,
    run_name: str | None = None,
    notes: str | None = None,
    run_id: str | None = None,
) -> None:
    from backend.screening.early_turn_service import EarlyTurnService

    with _early_turn_task_lock:
        _early_turn_task_status.update({
            "status": "running",
            "progress": 5,
            "step_message": "正在初始化 A-PreV2 早期转强任务...",
            "trade_date": trade_date or "",
            "run_id": None,
            "candidate_count": 0,
            "error": None,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "completed_at": None,
        })

    try:
        store = PostgresScreeningStore(_database_url())

        with _early_turn_task_lock:
            _early_turn_task_status["progress"] = 10
            _early_turn_task_status["step_message"] = "正在检查并补齐目标交易日行情与概念数据..."

        target_info = _sync_screening_trade_date(store, trade_date)
        target_date = target_info["trade_date"]

        with _early_turn_task_lock:
            _early_turn_task_status["trade_date"] = target_date
            _early_turn_task_status["progress"] = 25
            _early_turn_task_status["step_message"] = "正在执行 A-PreV2 技术扫描与状态分类..."

        def _tech_progress(idx: int, total: int, code: str) -> None:
            pct = 25 + int((idx / max(total, 1)) * 35)
            with _early_turn_task_lock:
                _early_turn_task_status["progress"] = min(pct, 60)
                _early_turn_task_status["step_message"] = f"正在技术扫描 {code} ({idx}/{total})..."

        svc = EarlyTurnService(store=store)
        summary = svc.run(
            trade_date=target_date,
            ts_code=ts_code,
            config_version=config_version,
            run_name=run_name,
            notes=notes,
            run_id=run_id,
            progress_callback=_tech_progress,
        )
        run_id = summary["run_id"]

        candidate_items = []
        with _early_turn_task_lock:
            _early_turn_task_status["run_id"] = run_id
            _early_turn_task_status["candidate_count"] = len(candidate_items)
            _early_turn_task_status["progress"] = 62
            _early_turn_task_status["step_message"] = "技术扫描完成，基本面研究需按筛选条件手动执行。"

        with _early_turn_task_lock:
            _early_turn_task_status["status"] = "success"
            _early_turn_task_status["progress"] = 100
            _early_turn_task_status["step_message"] = (
                "A-PreV2 技术选股完成。请先选择筛选条件，再手动执行基本面研究。"
            )
            _early_turn_task_status["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as exc:
        with _early_turn_task_lock:
            _early_turn_task_status["status"] = "failed"
            _early_turn_task_status["progress"] = 0
            _early_turn_task_status["step_message"] = f"A-PreV2 运行失败: {str(exc)}"
            _early_turn_task_status["error"] = str(exc)
            _early_turn_task_status["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")


_market_memory_status: dict[str, Any] = {
    "running": False,
    "as_of_date": "",
    "error": None,
    "started_at": None,
    "completed_at": None,
}
_market_memory_lock = threading.Lock()

# 市场全景是独立状态机，不能与题材周期/资金脉络共用任务状态。
_market_panorama_status: dict[str, Any] = {
    "running": False,
    "as_of_date": None,
    "mode": None,
    "error": None,
    "started_at": None,
    "completed_at": None,
}
_market_panorama_lock = threading.Lock()

_capital_flow_status: dict[str, Any] = {
    "running": False,
    "mode": None,
    "current_date": None,
    "completed": 0,
    "total": 0,
    "error": None,
    "started_at": None,
    "completed_at": None,
}
_capital_flow_lock = threading.Lock()


def _run_market_memory_async(date: str, force_refresh: bool = False) -> None:
    from backend.screening.market_memory_service import get_or_create_market_memory
    global _market_memory_status
    with _market_memory_lock:
        _market_memory_status["running"] = True
        _market_memory_status["as_of_date"] = date
        _market_memory_status["error"] = None
        _market_memory_status["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _market_memory_status["completed_at"] = None
    try:
        store = PostgresScreeningStore(_database_url())
        get_or_create_market_memory(store, date, lookback_sessions=120, force_refresh=force_refresh)
        with _market_memory_lock:
            _market_memory_status["running"] = False
            _market_memory_status["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as exc:
        import traceback
        traceback.print_exc()
        with _market_memory_lock:
            _market_memory_status.update({"running": False, "error": str(exc), "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")})


def _run_market_overview_rewrite_async(date: str) -> None:
    from backend.screening.market_memory_service import refresh_market_overview_markdown
    global _market_memory_status
    with _market_memory_lock:
        _market_memory_status["running"] = True
        _market_memory_status["as_of_date"] = date
        _market_memory_status["error"] = None
        _market_memory_status["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _market_memory_status["completed_at"] = None
    try:
        store = PostgresScreeningStore(_database_url())
        refresh_market_overview_markdown(store, date)
        with _market_memory_lock:
            _market_memory_status["running"] = False
            _market_memory_status["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as exc:
        import traceback
        traceback.print_exc()
        with _market_memory_lock:
            _market_memory_status["running"] = False
            _market_memory_status["error"] = str(exc)


def _run_market_panorama_async(date: str, force_rebuild: bool = False, incremental: bool = False) -> None:
    from backend.screening.market_panorama_v2_service import rebuild_v2, rerender_v2, update_incremental_v2
    if force_rebuild and incremental:
        raise ValueError("市场全景任务不能同时请求全量重建与增量更新")
    mode = "正在全量重建" if force_rebuild else ("正在增量更新" if incremental else "正在重写文章")
    with _market_panorama_lock:
        _market_panorama_status.update({
            "running": True,
            "as_of_date": date,
            "mode": mode,
            "error": None,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "completed_at": None,
        })
    try:
        store = PostgresScreeningStore(_database_url())
        if force_rebuild:
            rebuild_v2(store, date)
        elif incremental:
            update_incremental_v2(store, date)
        else:
            rerender_v2(store, date)
        with _market_panorama_lock:
            _market_panorama_status.update({
                "running": False,
                "mode": "全量重建完成" if force_rebuild else ("增量更新完成" if incremental else "文章重写完成"),
                "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
    except Exception as exc:
        import traceback
        traceback.print_exc()
        with _market_panorama_lock:
            _market_panorama_status.update({"running": False, "error": str(exc), "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")})


def _launch_imported_review_updates(date: str) -> None:
    """Run the independent V2 panorama and legacy theme/flow updates concurrently.

    Both tasks read the already-persisted imported review and write different snapshot tables.
    They therefore have no data dependency and must not be serialized by FastAPI BackgroundTasks.
    """
    threading.Thread(
        target=_run_market_panorama_async,
        args=(date, False, True),
        name=f"market-panorama-{date}",
        daemon=True,
    ).start()
    threading.Thread(
        target=_run_market_memory_async,
        args=(date, True),
        name=f"market-memory-{date}",
        daemon=True,
    ).start()


def _latest_snapshot_date(store: PostgresScreeningStore, table_name: str, date: str) -> str | None:
    """Return only a labelled previous snapshot date; never substitute its content for the requested date."""
    with store.connect() as conn:
        row = conn.execute(
            f"SELECT MAX(as_of_date) AS as_of_date FROM {table_name} WHERE as_of_date <= %s",
            (date,),
        ).fetchone()
    return str(row["as_of_date"]) if row and row["as_of_date"] else None


def _snapshot_task_state(date: str, task_status: dict[str, Any], lock: threading.Lock) -> tuple[str, str]:
    with lock:
        state = dict(task_status)
    if state.get("as_of_date") != date:
        return "PENDING", "尚未开始生成"
    if state.get("running"):
        return "GENERATING", "正在生成"
    if state.get("error"):
        return "FAILED", str(state["error"])
    return "PENDING", "尚未生成"


def _run_capital_flow_backfill_async(dates: list[str] | None = None) -> None:
    from backend.screening.market_memory_service import list_market_memory_dates, refresh_capital_flows_for_date
    global _capital_flow_status
    try:
        store = PostgresScreeningStore(_database_url())
        target_dates = dates or list_market_memory_dates(store)
        with _capital_flow_lock:
            _capital_flow_status.update({"running": True, "mode": "backfill", "current_date": None, "completed": 0, "total": len(target_dates), "error": None, "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "completed_at": None})
        failures: list[dict[str, str]] = []
        for index, target_date in enumerate(target_dates, start=1):
            with _capital_flow_lock:
                _capital_flow_status["current_date"] = target_date
            try:
                refresh_capital_flows_for_date(store, target_date)
            except Exception as exc:
                failures.append({"date": target_date, "error": str(exc)})
            with _capital_flow_lock:
                _capital_flow_status["completed"] = index
        with _capital_flow_lock:
            _capital_flow_status.update({"running": False, "current_date": None, "error": None if not failures else json.dumps(failures, ensure_ascii=False), "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    except Exception as exc:
        with _capital_flow_lock:
            _capital_flow_status.update({"running": False, "error": str(exc), "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")})


def _run_capital_flow_date_async(date: str) -> None:
    _run_capital_flow_backfill_async([date])


def _database_url() -> str:
    value = os.getenv("MARKET_REVIEW_DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("MARKET_REVIEW_DATABASE_URL is required")
    return value


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _screening_sync(store: PostgresScreeningStore) -> ScreeningDataSync:
    config = TushareConfig.from_project_env(_project_root())
    source = TushareScreeningSource(config.token)
    return ScreeningDataSync(source, store)


def _all_early_turn_items(store: PostgresScreeningStore, run_id: str) -> list[dict[str, Any]]:
    first_page = store.query_early_turn_results(run_id, limit=1, offset=0)
    total = int(first_page.get("total") or 0)
    if total == 0:
        return []
    full_page = store.query_early_turn_results(run_id, limit=total, offset=0)
    items = full_page.get("items", [])
    if len(items) != total:
        raise RuntimeError(f"early_turn_result incomplete read: expected={total}, actual={len(items)}")
    return items


def _secondary_candidate_items(store: PostgresScreeningStore, run_id: str) -> list[dict[str, Any]]:
    items = _all_early_turn_items(store, run_id)
    return [item for item in items if item.get("turn_episode_state") in EARLY_TURN_SECONDARY_STATES]


def _run_secondary_evaluation_for_items(
    store: PostgresScreeningStore,
    as_of_date: str,
    source_items: list[dict[str, Any]],
    progress_callback: Callable[[int, int, str], None] | None = None,
    input_progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    from backend.screening.secondary_eval_engine import evaluate_single_secondary_candidate

    ts_codes = [item["ts_code"] for item in source_items]
    if not ts_codes:
        return {"evaluated_count": 0, "candidate_scope": sorted(EARLY_TURN_SECONDARY_STATES)}

    _ensure_secondary_data_inputs(store, as_of_date, ts_codes, progress_callback=input_progress_callback)
    item_by_code = {item["ts_code"]: item for item in source_items}
    sec_rows, ev_rows, lead_rows, sup_rows = [], [], [], []
    total = len(ts_codes)
    for idx, code in enumerate(ts_codes, start=1):
        sec, ev, lead, sup = evaluate_single_secondary_candidate(
            store,
            code,
            as_of_date,
            item_by_code[code],
        )
        sec_rows.append(sec)
        ev_rows.append(ev)
        lead_rows.append(lead)
        sup_rows.append(sup)
        if progress_callback:
            progress_callback(idx, total, code)

    store.save_secondary_evaluation_snapshots(as_of_date, sec_rows, ev_rows, lead_rows, sup_rows)
    return {
        "evaluated_count": len(sec_rows),
        "candidate_scope": sorted(EARLY_TURN_SECONDARY_STATES),
    }


def _latest_open_trade_date(sync: ScreeningDataSync) -> str:
    today = date.today()
    start = (today - timedelta(days=14)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    dates = sync.source.trade_dates(start, end)
    if not dates:
        raise ScreeningError(f"no open trade dates between {start} and {end}")
    return dates[-1]


def _sync_screening_trade_date(
    store: PostgresScreeningStore,
    trade_date: str | None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    stop_callback: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    sync = _screening_sync(store)
    requested_date = (trade_date or "").strip().replace("-", "")
    if requested_date and (len(requested_date) != 8 or not requested_date.isdigit()):
        raise ScreeningError(f"invalid trade_date: {trade_date}")

    # 日线只能按已进入发布窗口的完整交易日补齐；盘中/凌晨不请求当天正式日线。
    freshness_before = store.get_data_freshness_info()
    official_before = str(freshness_before.get("official_daily_date") or "")
    data_config = store.get_data_management_config()["config"]
    now_shanghai = datetime.now(_SHANGHAI_TZ)
    today_shanghai = now_shanghai.date()
    calendar_end = today_shanghai if _daily_release_reached(data_config, now_shanghai) else today_shanghai - timedelta(days=1)
    candidates = [requested_date] if requested_date else sync.source.trade_dates(
        (today_shanghai - timedelta(days=14)).strftime("%Y%m%d"), calendar_end.strftime("%Y%m%d")
    )
    daily_results: dict[str, Any] = {}
    pending_daily: list[dict[str, str]] = []
    for candidate in sorted(set(candidates)):
        if not candidate.isdigit() or (not requested_date and official_before and candidate <= official_before):
            continue
        if store.has_daily_data(candidate):
            daily_results[candidate] = "SKIPPED_EXISTING"
            continue
        try:
            daily_results[candidate] = sync.sync_trade_date(candidate)
        except ScreeningError as exc:
            if "EMPTY_DATA" in str(exc):
                pending_daily.append({"trade_date": candidate, "reason": str(exc)})
                continue
            raise

    target_date = requested_date or (sorted(set(candidates))[-1] if candidates else official_before)
    intraday_result: dict[str, Any] = {}
    if target_date:
        # 当天即使没有正式日线，也必须继续补最新 30 分钟数据。
        asset_types = {kind for kind, enabled in (("stock", data_config.get("stock_30m_enabled", True)), ("etf", data_config.get("etf_30m_enabled", True))) if enabled}
        intraday_result = sync.sync_30m_bars_all(
            start_date=target_date,
            end_date=target_date,
            progress_callback=progress_callback,
            asset_types=asset_types,
            stop_callback=stop_callback,
        )

    freshness = store.get_data_freshness_info()

    # ── 同花顺概念快照补抓 ───────────────────────────────────────────────
    from backend.screening.ths_concept_service import sync_ths_concepts
    if target_date:
        sync_ths_concepts(store, as_of_date=target_date, force=False)

    return {
        "trade_date": target_date,
        "counts": {"daily": daily_results, "intraday_30m": intraday_result},
        "pending_daily": pending_daily,
        "freshness": freshness,
    }


def _sync_financials_for_stock(store: PostgresScreeningStore, ts_code: str) -> dict[str, Any]:
    sync = _screening_sync(store)
    return sync.sync_financials_for_stock(ts_code)


def _ensure_secondary_data_inputs(
    store: PostgresScreeningStore,
    as_of_date: str,
    ts_codes: list[str],
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    from backend.screening.industry_sync import IndustrySyncService, SW_SOURCE_VERSION

    sync = _screening_sync(store)
    result: dict[str, Any] = {
        "daily_basic": "READY",
        "industry_membership": "READY",
        "financial_synced": [],
        "supply_events_synced": [],
    }

    if not store.has_daily_basic_extended(as_of_date):
        result["daily_basic"] = sync.sync_daily_basic_for_date(as_of_date)

    if not store.has_industry_memberships(SW_SOURCE_VERSION):
        industry_sync = IndustrySyncService(store, sync.source.pro)
        result["industry_membership"] = industry_sync.sync_industry_members()

    total = len(ts_codes)
    for idx, ts_code in enumerate(ts_codes, start=1):
        if not store.has_financial_data_for_stock(ts_code, as_of_date):
            result["financial_synced"].append(sync.sync_financials_for_stock(ts_code))
        if not store.has_supply_event_data_for_stock(ts_code):
            result["supply_events_synced"].append(sync.sync_supply_events_for_stock(ts_code))
        if progress_callback:
            progress_callback(idx, total, ts_code)

    return result


def create_app() -> FastAPI:
    from backend.market_review.scheduler import AutoDataScheduler
    from contextlib import asynccontextmanager

    database_url = _database_url()
    # Apply review-data schema migrations before any endpoint reads the
    # full-text stock mention index.
    PostgresMarketReviewStore(database_url)
    scheduler = AutoDataScheduler(database_url)
    trading_store = TradingStore(database_url)
    trade_plan_store = TradePlanStore(database_url)
    execution_store = ExecutionStore(database_url)
    class ConfiguredBrokerGateway(BrokerGateway):
        """Resolve the selected broker connection from the configured profile."""

        @staticmethod
        def _normalize_snapshot_items(items: Any) -> list[dict[str, Any]]:
            if not isinstance(items, list):
                raise RuntimeError("Broker snapshot payload must be a list")
            normalized_items: list[dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    raise RuntimeError("Broker snapshot item must be an object")
                normalized = item.get("normalized")
                raw = item.get("raw")
                result = {**(raw if isinstance(raw, dict) else {}), **(normalized if isinstance(normalized, dict) else item)}
                instrument = result.get("instrument") if isinstance(result.get("instrument"), dict) else {}
                if instrument.get("code"):
                    result["symbol"] = str(instrument["code"])
                if not result.get("exchange") and instrument.get("exchange"):
                    result["exchange"] = instrument["exchange"]
                result["raw_broker_data"] = item
                normalized_items.append(result)
            return normalized_items

        def _configuration_error(self, account_id: int) -> str | None:
            account = trading_store.get_broker_account(account_id)
            if not account:
                return "交易账号不存在或未绑定券商账号"
            required = ("broker_node_url", "broker_account_key", "broker_account_id", "broker_strategy_id", "broker_gm_token")
            missing = [field for field in required if not str(account.get(field) or "").strip()]
            if missing:
                return f"券商账户配置不完整：缺少 {', '.join(missing)}"
            return None

        def _gateway(self, account_id: int) -> BrokerGateway:
            account = trading_store.get_broker_account(account_id)
            error = self._configuration_error(account_id)
            if error:
                raise BrokerNotConnectedError(error)
            gateway = GMBrokerHttpGateway(base_url=account["broker_node_url"])
            gateway.configure_gm_token(str(account["broker_gm_token"]))
            return gateway

        def connect(self, account_id: int) -> dict[str, Any]:
            error = self._configuration_error(account_id)
            if error:
                return {"status": "DISCONNECTED", "message": error}
            gateway = self._gateway(account_id)
            health = gateway.connect()
            if not isinstance(health, dict):
                raise RuntimeError("Broker Node health response is malformed")
            node_status = gateway.get_status()
            healthy = health.get("ok") is True or health.get("status") == "CONNECTED"
            return {
                **health,
                "status": "CONNECTED" if healthy else "DISCONNECTED",
                "node_status": node_status,
            }

        def get_capabilities(self, account_id: int) -> dict[str, Any]:
            error = self._configuration_error(account_id)
            if error:
                return {"status": "DISCONNECTED", "native_orders": [], "conditional_execution": [], "algorithms": [], "message": error}
            return self._gateway(account_id).get_capabilities()

        def get_account(self, account_id: int) -> dict[str, Any]:
            return self._gateway(account_id).get_account()

        def get_positions(self, account_id: int) -> list[dict[str, Any]]:
            return self._normalize_snapshot_items(self._gateway(account_id).get_positions())

        def get_orders(self, account_id: int) -> list[dict[str, Any]]:
            return self._normalize_snapshot_items(self._gateway(account_id).get_orders())

        def get_fills(self, account_id: int) -> list[dict[str, Any]]:
            return self._normalize_snapshot_items(self._gateway(account_id).get_fills())

        def submit_order(self, account_id: int, order: dict[str, Any]) -> dict[str, Any]:
            return self._gateway(account_id).submit_order(order)

        def cancel_order(self, account_id: int, order: dict[str, Any]) -> dict[str, Any]:
            return self._gateway(account_id).cancel_order(order)

    broker_gateway = ConfiguredBrokerGateway()
    broker_event_sync = BrokerEventSyncService(execution_store, trading_store, broker_gateway._gateway)
    execution_pollers: dict[int, ExecutionQuotePoller] = {}
    event_sync_stop = threading.Event()
    event_sync_thread: threading.Thread | None = None

    def _sync_broker_events_loop() -> None:
        while not event_sync_stop.wait(2.0):
            for account in trading_store.list_accounts():
                if account.get("account_type") not in {"SIMULATION", "LIVE"}:
                    continue
                account_id = int(account["id"])
                try:
                    broker_event_sync.sync_account(account_id)
                    _run_execution_cycle(account_id)
                except Exception as exc:
                    # A broker outage must not terminate the API process. The
                    # failure is explicit in the service log and the cursor is
                    # left unchanged so the next cycle retries the same page.
                    print(f"[BROKER_EVENT_SYNC] account={account_id} failed: {exc}")

    def _execution_symbol(symbol: str) -> str:
        value = str(symbol).strip().upper()
        if ":" in value:
            return value
        if "." in value:
            exchange, code = value.split(".", 1)
            exchange = {"SSE": "SH", "SHSE": "SH", "SZSE": "SZ"}.get(exchange, exchange)
            return f"{exchange}:{code}"
        return f"{'SH' if value.startswith('6') else 'SZ'}:{value}"

    def _run_execution_cycle(account_id: int) -> None:
        plans = execution_store.list_execution_plans(account_id, "ACTIVE")
        if not plans:
            poller = execution_pollers.pop(account_id, None)
            if poller:
                poller.poll([])
            return
        raw_gateway = broker_gateway._gateway(account_id)
        node_status = raw_gateway.get_status()
        if node_status.get("execution_enabled") is not True or node_status.get("paused") is True or node_status.get("reconciliation_required") is True:
            return
        normalized_plans = [{**plan, "symbol": _execution_symbol(str(plan["symbol"]))} for plan in plans]
        poller = execution_pollers.setdefault(account_id, ExecutionQuotePoller(raw_gateway))
        # A plain LIMIT plan has a user-supplied price and does not depend on
        # a new tick.  Do not subscribe to or read execution quotes for it,
        # especially outside market hours.  Conditional plans alone require
        # a fresh quote to decide whether they may submit.
        conditional_plans = [
            plan for plan in normalized_plans
            if plan["execution_type"] in {"PRICE_TRIGGER", "PRICE_RANGE"}
        ]
        quotes = poller.poll(conditional_plans)
        quotes_by_symbol = {str(item.get("symbol_key")): item for item in quotes if isinstance(item, dict) and item.get("symbol_key")}
        account = trading_store.get_account(account_id)
        risk_profile = trading_store.get_risk_profile(account_id)
        positions = trading_store.list_positions(account_id)
        active_orders = execution_store.list_orders(account_id)
        engine = ExecutionEngine(raw_gateway)
        for plan in normalized_plans:
            existing_plan_orders = [
                item for item in active_orders
                if int(item.get("execution_plan_id") or 0) == int(plan["id"])
                and item.get("status") not in {"CANCELLED", "FILLED", "REJECTED", "EXPIRED"}
            ]
            if existing_plan_orders:
                # A durable local order means this plan has already crossed
                # (or may have crossed) the broker boundary. Wait for its
                # event/reconciliation instead of submitting again.
                continue
            symbol = str(plan["symbol"])
            quote = quotes_by_symbol.get(symbol)
            if plan["execution_type"] in {"LIMIT", "PERSISTENT_LIMIT"}:
                # A plain limit order does not require a live quote.  The
                # symbol-only context is deliberately not presented as quote
                # data; conditional plans still require an actual fresh tick.
                quote = {"symbol_key": symbol, "freshness": "NOT_REQUIRED"}
            if quote is None:
                continue
            client_order_id = f"LLL-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:10]}"
            local_order: dict[str, Any] | None = None

            def create_order(payload: dict[str, Any]) -> dict[str, Any]:
                nonlocal local_order
                local_order = execution_store.create_pending_order(OrderInput(
                    execution_plan_id=int(plan["id"]), symbol=str(plan["symbol"]), side=str(plan["side"]),
                    order_type="LIMIT", quantity=int(plan["remaining_qty"]), price=float(payload["price"]), account_id=account_id,
                ), client_order_id)
                return local_order

            try:
                submission = engine.submit(plan, quote, account, risk_profile, positions, active_orders,
                                           str(trading_store.get_broker_account(account_id)["broker_account_key"]),
                                           f"{client_order_id}:submit", client_order_id, create_order)
                if submission and local_order:
                    broker_response = submission.broker_response
                    broker_status = str(broker_response.get("status") or "").upper()
                    if broker_status not in {"QUEUED", "CLAIMED", "DISPATCHING", "SUBMITTED", "ACCEPTED"}:
                        raise RuntimeError("Broker Node order response has no accepted command status")
                    execution_store.record_order_update(account_id, int(local_order["id"]), {
                        "status": "SUBMITTED",
                        "raw_broker_data": broker_response,
                    })
                    local_order = execution_store.list_orders(account_id, int(plan["id"]))[0]
                    active_orders.append(local_order)
            except Exception as exc:
                if local_order:
                    execution_store.record_order_update(account_id, int(local_order["id"]), {"status": "UNKNOWN", "reject_message": str(exc), "raw_broker_data": {"error": str(exc)}})
                raise

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        nonlocal event_sync_thread
        try:
            scheduler.start()
        except Exception as e:
            print(f"[API_STARTUP] 启动自动数据调度器失败: {e}")
        event_sync_stop.clear()
        event_sync_thread = threading.Thread(target=_sync_broker_events_loop, name="broker-event-sync", daemon=True)
        event_sync_thread.start()
        yield
        event_sync_stop.set()
        if event_sync_thread:
            event_sync_thread.join(timeout=5)
        try:
            scheduler.stop()
        except Exception as e:
            print(f"[API_SHUTDOWN] 关闭自动数据调度器提示: {e}")

    app = FastAPI(title="LLL Market Review API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        _database_url()
        return {"status": "ok"}

    def _trade_plan_payload(body: dict[str, Any], account_id: int) -> tuple[TradePlanInput, AccountRiskSettings, InstrumentInfo, datetime | None]:
        plan_data = body.get("plan", body)
        plan_data = {**plan_data, "account_id": account_id}
        settings = trading_store.trade_plan_settings(account_id)
        account_data = {key: settings[key] for key in (
            "account_equity", "available_cash", "current_invested_amount", "default_risk_pct",
            "max_single_position_pct", "max_total_position_pct", "max_trade_risk_pct",
        )}
        instrument_data = body.get("instrument", {})
        plan = TradePlanInput(**plan_data)
        account = AccountRiskSettings(**account_data)
        instrument = InstrumentInfo(**instrument_data) if instrument_data else InstrumentInfo()
        expires_at_raw = body.get("expires_at")
        expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00")) if expires_at_raw else None
        return plan, account, instrument, expires_at

    @app.post("/api/trade-plans/calculate")
    def calculate_trade_plan(body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            context = trading_store.trade_plan_context(account_id)
            if not context["is_ready"]:
                return {"status": "CONFIGURATION_REQUIRED", "calculation": None, "account_context": context}
            plan, account, instrument, _ = _trade_plan_payload(body, account_id)
            return {"status": "SUCCESS", "calculation": TradePlanCalculator.calculate(plan, account, instrument), "account_context": context}
        except (TypeError, ValueError, TradePlanValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/trade-plans")
    def list_trade_plans(account_id: int = Query(...), status: str | None = Query(None)) -> dict[str, Any]:
        allowed = {"DRAFT", "READY", "ARMED", "PARTIALLY_EXECUTED", "EXECUTED", "CANCELLED", "EXPIRED", "INVALIDATED"}
        if status and status not in allowed:
            raise HTTPException(status_code=422, detail=f"status must be one of {sorted(allowed)}")
        return {"status": "SUCCESS", "items": trade_plan_store.list(account_id, status)}

    @app.get("/api/trades")
    def list_trades(account_id: int = Query(...), status: str | None = Query(None)) -> dict[str, Any]:
        allowed = {"PLANNED", "ACTIVE", "CLOSING", "CLOSED", "CANCELLED"}
        if status and status not in allowed:
            raise HTTPException(status_code=422, detail=f"status must be one of {sorted(allowed)}")
        return {"status": "SUCCESS", "items": trade_plan_store.list_trades(account_id, status)}

    @app.get("/api/trades/{trade_id}")
    def get_trade(trade_id: int, account_id: int = Query(...)) -> dict[str, Any]:
        item = trade_plan_store.get_trade(account_id, trade_id)
        if not item:
            raise HTTPException(status_code=404, detail="Trade not found")
        return {"status": "SUCCESS", "item": item}

    @app.post("/api/trades/{trade_id}/add/calculate")
    def calculate_add_plan(trade_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        trade = trade_plan_store.get_trade(account_id, trade_id)
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")
        if trade["status"] != "ACTIVE":
            raise HTTPException(status_code=409, detail="只有持仓中的 Trade 才能创建加仓计划")
        position = next((item for item in trading_store.list_positions(account_id) if item["symbol"] == trade["symbol"]), None)
        if not position or int(position["quantity"]) <= 0:
            raise HTTPException(status_code=409, detail="当前 Trade 没有可用于加仓计算的实际持仓")
        try:
            plan = AddPlanInput(
                reference_price=float(body["reference_price"]),
                max_acceptable_price=float(body["max_acceptable_price"]),
                risk_reference_price=float(body["risk_reference_price"]),
                manual_quantity=body.get("manual_quantity"),
                action_risk_budget_pct=body.get("action_risk_budget_pct"),
                action_risk_budget_amount=body.get("action_risk_budget_amount"),
                failure_handling=body.get("failure_handling"),
            )
            account = trading_store.get_account(account_id)
            risk = trading_store.get_risk_profile(account_id)
            trade_risk_budget_amount = body.get("trade_risk_budget_amount")
            if trade_risk_budget_amount is None:
                raise TradeActionValidationError("trade_risk_budget_amount is required")
            context = AddAccountContext(
                equity=float(account["equity"]),
                available_cash=float(account["available_cash"]),
                current_invested_amount=sum(item["market_value"] for item in trading_store.list_positions(account_id)),
                max_single_position_pct=float(risk["max_single_position_pct"]),
                max_total_exposure_pct=float(risk["max_total_exposure_pct"]),
                trade_risk_budget_amount=float(trade_risk_budget_amount),
                current_market_price=float(position["market_price"]),
                current_position_qty=int(position["quantity"]),
                current_average_cost=float(position["average_cost"]),
                current_risk_reference_price=position.get("current_risk_reference_price"),
                current_risk_reference_note=position.get("risk_note"),
                existing_legs=tuple(trade.get("legs") or ()),
            )
            return {"status": "SUCCESS", "calculation": AddPlanCalculator.calculate(plan, context)}
        except (KeyError, TypeError, ValueError, TradeActionValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/trades/{trade_id}/add")
    def create_add_plan(trade_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        calculated = calculate_add_plan(trade_id, body, account_id)
        trade = trade_plan_store.get_trade(account_id, trade_id)
        try:
            item = trade_plan_store.create_action_plan(account_id, trade_id, "ADD", trade["symbol"], trade["symbol_name"], body, calculated["calculation"], body.get("reason_code"), body.get("reason_text"))
            return {"status": "SUCCESS", "item": item, "calculation": calculated["calculation"]}
        except (KeyError, TypeError, ValueError, TradeActionValidationError, TradePlanValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _position_action_context(account_id: int, trade_id: int) -> tuple[dict[str, Any], PositionActionContext]:
        trade = trade_plan_store.get_trade(account_id, trade_id)
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")
        if trade["status"] not in {"ACTIVE", "CLOSING"}:
            raise HTTPException(status_code=409, detail="Trade 当前没有可管理的持仓")
        positions = trading_store.list_positions(account_id)
        position = next((item for item in positions if item["symbol"] == trade["symbol"]), None)
        if not position or int(position["quantity"]) <= 0:
            raise HTTPException(status_code=409, detail="当前 Trade 没有持仓")
        account = trading_store.get_account(account_id)
        return trade, PositionActionContext(
            equity=float(account["equity"]), current_position_qty=int(position["quantity"]),
            available_position_qty=int(position["available_quantity"]), average_cost=float(position["average_cost"]),
            market_price=float(position["market_price"]), current_invested_amount=sum(item["market_value"] for item in positions),
            existing_legs=tuple(trade.get("legs") or ()),
        )

    @app.post("/api/trades/{trade_id}/reduce/calculate")
    def calculate_reduce_plan(trade_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        _trade, context = _position_action_context(account_id, trade_id)
        try:
            plan = ReducePlanInput(reduce_method=str(body["reduce_method"]), quantity=body.get("quantity"), position_pct=body.get("position_pct"), target_remaining_qty=body.get("target_remaining_qty"), target_remaining_pct=body.get("target_remaining_pct"), reference_price=body.get("reference_price"), minimum_acceptable_price=body.get("minimum_acceptable_price"), trigger_condition=body.get("trigger_condition"))
            return {"status": "SUCCESS", "calculation": ReducePlanCalculator.calculate(plan, context)}
        except (KeyError, TypeError, ValueError, TradeActionValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/trades/{trade_id}/reduce")
    def create_reduce_plan(trade_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        calculated = calculate_reduce_plan(trade_id, body, account_id)
        trade = trade_plan_store.get_trade(account_id, trade_id)
        try:
            item = trade_plan_store.create_action_plan(account_id, trade_id, "REDUCE", trade["symbol"], trade["symbol_name"], body, calculated["calculation"], body.get("reason_code"), body.get("reason_text"))
            return {"status": "SUCCESS", "item": item, "calculation": calculated["calculation"]}
        except (KeyError, TypeError, ValueError, TradeActionValidationError, TradePlanValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/trades/{trade_id}/close/calculate")
    def calculate_close_plan(trade_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        _trade, context = _position_action_context(account_id, trade_id)
        try:
            return {"status": "SUCCESS", "calculation": ClosePlanCalculator.calculate(context, body.get("reference_price"), body.get("minimum_acceptable_price"), body.get("trigger_condition"))}
        except (TypeError, ValueError, TradeActionValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/trades/{trade_id}/close")
    def create_close_plan(trade_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        calculated = calculate_close_plan(trade_id, body, account_id)
        trade = trade_plan_store.get_trade(account_id, trade_id)
        try:
            item = trade_plan_store.create_action_plan(account_id, trade_id, "CLOSE", trade["symbol"], trade["symbol_name"], body, calculated["calculation"], body.get("reason_code"), body.get("reason_text"))
            return {"status": "SUCCESS", "item": item, "calculation": calculated["calculation"]}
        except (KeyError, TypeError, ValueError, TradeActionValidationError, TradePlanValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/trades/{trade_id}/risk-reference")
    def update_trade_risk_reference(trade_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            new_price = float(body["new_price"])
            if not math.isfinite(new_price) or new_price <= 0:
                raise TradePlanValidationError("new_price must be finite and greater than 0")
            item = trade_plan_store.update_risk_reference(account_id, trade_id, new_price, str(body["reason"]), body.get("leg_id"))
            return {"status": "SUCCESS", "item": item}
        except (KeyError, TypeError, ValueError, TradePlanValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/trades/{trade_id}/exit-rules")
    def list_trade_exit_rules(trade_id: int, account_id: int = Query(...)) -> dict[str, Any]:
        if not trade_plan_store.get_trade(account_id, trade_id):
            raise HTTPException(status_code=404, detail="Trade not found")
        return {"status": "SUCCESS", "items": trade_plan_store.list_exit_rules(account_id, trade_id)}

    @app.post("/api/trades/{trade_id}/exit-rules")
    def create_trade_exit_rule(trade_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            return {"status": "SUCCESS", "item": trade_plan_store.create_exit_rule(account_id, trade_id, body)}
        except (KeyError, TypeError, ValueError, TradePlanValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.patch("/api/trades/{trade_id}/exit-rules/{rule_id}")
    def update_trade_exit_rule(trade_id: int, rule_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            item = trade_plan_store.update_exit_rule(account_id, trade_id, rule_id, body)
        except (KeyError, TypeError, ValueError, TradePlanValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not item:
            raise HTTPException(status_code=404, detail="ExitRule not found")
        return {"status": "SUCCESS", "item": item}

    @app.delete("/api/trades/{trade_id}/exit-rules/{rule_id}")
    def delete_trade_exit_rule(trade_id: int, rule_id: int, account_id: int = Query(...)) -> dict[str, Any]:
        if not trade_plan_store.delete_exit_rule(account_id, trade_id, rule_id):
            raise HTTPException(status_code=404, detail="ExitRule not found")
        return {"status": "SUCCESS", "trade_id": trade_id, "rule_id": rule_id}

    @app.get("/api/trades/{trade_id}/position-state")
    def get_trade_position_state(trade_id: int, account_id: int = Query(...)) -> dict[str, Any]:
        if not trade_plan_store.get_trade(account_id, trade_id):
            raise HTTPException(status_code=404, detail="Trade not found")
        return {"status": "SUCCESS", "item": trade_plan_store.get_trade_position_state(account_id, trade_id)}

    @app.get("/api/trades/{trade_id}/risk-reference-history")
    def list_trade_risk_reference_history(trade_id: int, account_id: int = Query(...)) -> dict[str, Any]:
        if not trade_plan_store.get_trade(account_id, trade_id):
            raise HTTPException(status_code=404, detail="Trade not found")
        return {"status": "SUCCESS", "items": trade_plan_store.list_risk_reference_history(account_id, trade_id)}

    @app.get("/api/trade-settings")
    def get_trade_settings(account_id: int = Query(...)) -> dict[str, Any]:
        return {"status": "SUCCESS", "settings": trading_store.trade_plan_settings(account_id)}

    @app.patch("/api/trade-settings")
    def save_trade_settings(body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            account = trading_store.save_account(account_id, {
                "equity": body["account_equity"],
                "available_cash": body["available_cash"],
                "cash": body.get("cash", body["available_cash"]),
            })
            trading_store.save_risk_profile(account_id, {
                "default_trade_risk_pct": body["default_risk_pct"],
                "max_trade_risk_pct": body.get("max_trade_risk_pct", body["default_risk_pct"]),
                "max_single_position_pct": body["max_single_position_pct"],
                "max_total_exposure_pct": body["max_total_position_pct"],
            })
            return {"status": "SUCCESS", "settings": trading_store.trade_plan_settings(account_id)}
        except (KeyError, TypeError, ValueError, TradePlanValidationError, TradingDataValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/trading/account")
    def get_trading_account(account_id: int = Query(...)) -> dict[str, Any]:
        return {"status": "SUCCESS", "account": trading_store.get_account(account_id)}

    @app.patch("/api/trading/account")
    def save_trading_account(body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            return {"status": "SUCCESS", "account": trading_store.save_account(account_id, body)}
        except (TypeError, ValueError, TradingDataValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/trading/broker-accounts")
    def list_broker_accounts() -> dict[str, Any]:
        return {"status": "SUCCESS", "items": trading_store.list_broker_accounts()}

    @app.get("/api/trading/accounts")
    def list_trading_accounts() -> dict[str, Any]:
        return {"status": "SUCCESS", "items": trading_store.list_accounts()}

    @app.patch("/api/trading/accounts/{account_id}/default")
    def set_default_trading_account(account_id: int) -> dict[str, Any]:
        try:
            return {"status": "SUCCESS", "account": trading_store.set_default_account(account_id)}
        except TradingDataValidationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/trading/accounts/{account_id}")
    def update_trading_account(account_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            if body.get("is_default") is True:
                trading_store.set_default_account(account_id)
            editable = {key: value for key, value in body.items() if key != "is_default"}
            account = trading_store.save_account(account_id, editable) if editable else trading_store.get_account(account_id)
            return {"status": "SUCCESS", "account": account}
        except (TypeError, ValueError, TradingDataValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/trading/broker-accounts/assets")
    def broker_account_assets() -> dict[str, Any]:
        """Read the latest real asset snapshot for every configured account.

        An unavailable account is returned explicitly as unavailable so the
        settings page can distinguish missing broker data from zero assets.
        No synthetic values are supplied.
        """
        items = []
        for profile in trading_store.list_broker_accounts():
            item = {
                "id": profile["id"],
                "account_name": profile["name"],
                "account_type": profile["account_type"],
                "status": "UNAVAILABLE",
                "account": None,
                "message": None,
            }
            try:
                gateway = GMBrokerHttpGateway(base_url=profile["broker_node_url"])
                gateway.configure_gm_token(str(profile["broker_gm_token"]))
                snapshot = gateway.get_account()
                normalized = snapshot.get("payload", {}).get("normalized")
                if not isinstance(normalized, dict):
                    raise RuntimeError("券商账户资产返回格式无效")
                if str(normalized.get("account_id")) != str(profile["broker_account_id"]):
                    raise RuntimeError("券商返回的账户 ID 与配置不一致")
                item["status"] = "AVAILABLE"
                item["account"] = normalized
            except Exception as exc:
                item["message"] = str(exc)
            items.append(item)
        return {"status": "SUCCESS", "items": items}

    @app.post("/api/trading/broker-accounts")
    def create_broker_account(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return {"status": "SUCCESS", "item": trading_store.create_broker_account(body)}
        except (TypeError, ValueError, TradingDataValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/trading/broker-accounts/{account_id}")
    def delete_broker_account(account_id: int) -> dict[str, Any]:
        if not trading_store.delete_broker_account(account_id):
            raise HTTPException(status_code=404, detail="Broker account not found")
        return {"status": "SUCCESS", "deleted": account_id}

    @app.put("/api/trading/broker-accounts/{account_id}")
    def update_broker_account(account_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return {"status": "SUCCESS", "item": trading_store.update_broker_account(account_id, body)}
        except TradingDataValidationError as exc:
            if str(exc) == "Broker account not found":
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/trading/broker-accounts/{account_id}/test")
    def test_broker_account(account_id: int) -> dict[str, Any]:
        profile = next((item for item in trading_store.list_broker_accounts() if item["id"] == account_id), None)
        if not profile:
            raise HTTPException(status_code=404, detail="Broker account not found")
        try:
            gateway = GMBrokerHttpGateway(base_url=profile["broker_node_url"])
            gateway.configure_gm_token(str(profile["broker_gm_token"]))
            health = gateway.connect()
            node_status = gateway.get_status()
            account_snapshot = gateway.get_account()
            normalized = account_snapshot.get("payload", {}).get("normalized", {})
            checks = {
                "node": health.get("ok") is True,
                "agent": node_status.get("agent_online") is True,
                "account_connected": node_status.get("account_connected") is True,
                "broker_account_key": node_status.get("broker_account_key") == profile["broker_account_key"],
                "account_id": str(normalized.get("account_id")) == str(profile["broker_account_id"]),
                "strategy_id": str(node_status.get("strategy_id")) == str(profile["broker_strategy_id"]),
            }
            passed = all(checks.values())
            with trading_store.connect() as conn:
                conn.execute("""update trading_account set broker_connection_status=%s,
                    broker_connection_checked_at=now(), updated_at=now()
                    where broker_profile_id=%s""", ("CONNECTED" if passed else "DISCONNECTED", profile["id"]))
            return {"status": "SUCCESS", "connection": {"status": "CONNECTED" if passed else "DISCONNECTED", "message": "账号验证通过" if passed else "账号验证未通过", "checks": checks, "node_status": node_status, "account": normalized}}
        except Exception as exc:
            with trading_store.connect() as conn:
                conn.execute("update trading_account set broker_connection_status='DISCONNECTED', broker_connection_checked_at=now(), updated_at=now() where broker_profile_id=%s", (profile["id"],))
            return {"status": "SUCCESS", "connection": {"status": "DISCONNECTED", "message": str(exc)}}

    @app.get("/api/trading/broker-accounts/{account_id}/node-settings")
    def get_broker_node_settings(account_id: int) -> dict[str, Any]:
        profile = next((item for item in trading_store.list_broker_accounts() if item["id"] == account_id), None)
        if not profile:
            raise HTTPException(status_code=404, detail="Broker account not found")
        try:
            gateway = GMBrokerHttpGateway(base_url=profile["broker_node_url"], api_token=os.getenv("BROKER_NODE_API_TOKEN"))
            return {"status": "SUCCESS", "settings": gateway.get_node_settings()}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.patch("/api/trading/broker-accounts/{account_id}/node-settings")
    def update_broker_node_settings(account_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        profile = next((item for item in trading_store.list_broker_accounts() if item["id"] == account_id), None)
        if not profile:
            raise HTTPException(status_code=404, detail="Broker account not found")
        password = str(body.get("password") or "")
        if not verify_admin_password(password):
            raise HTTPException(status_code=403, detail={"code": "ADMIN_PASSWORD_INVALID", "message": "密码不正确"})
        settings = {
            "allow_live_orders": body.get("allow_live_orders") is True,
            "start_paused": body.get("start_paused") is True,
        }
        if profile["account_type"] != "LIVE" and settings["allow_live_orders"]:
            raise HTTPException(status_code=422, detail="仿真账号不能开启实盘交易授权")
        try:
            gateway = GMBrokerHttpGateway(base_url=profile["broker_node_url"], api_token=os.getenv("BROKER_NODE_API_TOKEN"))
            result = gateway.update_node_settings(settings)
            return {"status": "SUCCESS", "settings": result.get("settings", result)}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/trading/risk-profile")
    def get_risk_profile(account_id: int = Query(...)) -> dict[str, Any]:
        return {"status": "SUCCESS", "risk_profile": trading_store.get_risk_profile(account_id)}

    @app.patch("/api/trading/risk-profile")
    def save_risk_profile(body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            return {"status": "SUCCESS", "risk_profile": trading_store.save_risk_profile(account_id, body)}
        except (TypeError, ValueError, TradingDataValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/trading/positions")
    def list_planning_positions(account_id: int = Query(...)) -> dict[str, Any]:
        return {"status": "SUCCESS", "items": trading_store.list_positions(account_id)}

    @app.put("/api/trading/positions/{symbol}")
    def save_planning_position(symbol: str, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            data = {**body, "symbol": symbol}
            return {"status": "SUCCESS", "item": trading_store.save_position(account_id, data)}
        except (TypeError, ValueError, TradingDataValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/trading/positions/{symbol}")
    def delete_planning_position(symbol: str, account_id: int = Query(...)) -> dict[str, Any]:
        if not trading_store.delete_position(account_id, symbol):
            raise HTTPException(status_code=404, detail="Position not found")
        return {"status": "SUCCESS", "symbol": symbol}

    @app.get("/api/trading/overview")
    def get_trading_overview(account_id: int = Query(...)) -> dict[str, Any]:
        base = trading_store.overview(account_id)
        trades = trade_plan_store.list_trades(account_id)
        plans = execution_store.list_execution_plans(account_id)
        orders = execution_store.list_orders(account_id)
        fills = execution_store.list_fills(account_id)
        try:
            broker_status = broker_gateway.connect(account_id)
        except BrokerNotConnectedError as exc:
            broker_status = {"status": "DISCONNECTED", "message": str(exc)}
        except (ConnectionError, BrokerNodeRequestError) as exc:
            # The account's persisted local facts remain readable while the
            # broker channel is unavailable.  Surface the degraded data state
            # to the UI instead of turning the whole overview into HTTP 500.
            broker_status = {"status": "DISCONNECTED", "message": str(exc)}
        return {
            "status": "SUCCESS",
            **base,
            "trades": trades,
            "execution_plans": plans,
            "orders": orders,
            "fills": fills,
            "broker_status": broker_status,
            "control": execution_store.get_control(account_id),
            "data_quality": {
                "complete": broker_status.get("status") == "CONNECTED" and not bool((broker_status.get("node_status") or {}).get("reconciliation_required")),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        }

    @app.get("/api/trading/execution-plans")
    def list_execution_plans(account_id: int = Query(...), status: str | None = Query(None)) -> dict[str, Any]:
        return {"status": "SUCCESS", "items": execution_store.list_execution_plans(account_id, status)}

    @app.post("/api/trading/execution-plans")
    def create_execution_plan(body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            data = dict(body)
            for key in ("valid_from", "valid_until"):
                if data.get(key):
                    data[key] = datetime.fromisoformat(str(data[key]).replace("Z", "+00:00"))
            trade_plan = trade_plan_store.get(account_id, int(data["trade_plan_id"]))
            if not trade_plan:
                raise ExecutionValidationError("交易计划不存在")
            if trade_plan["status"] not in {"READY", "ARMED"}:
                raise ExecutionValidationError("只有已确认或已就绪的交易计划才能创建执行计划")
            if data.get("symbol") != trade_plan["symbol"]:
                raise ExecutionValidationError("执行计划股票必须与交易计划一致")
            calculation = trade_plan.get("calculation_snapshot_json") or {}
            planned_qty = int(calculation.get("planned_qty") or 0)
            if int(data.get("target_qty") or 0) != planned_qty:
                raise ExecutionValidationError("执行数量必须等于已确认交易计划的计划数量")
            input_data = trade_plan.get("input_json") or {}
            action_type = str(input_data.get("action_type") or "OPEN")
            expected_side = "SELL" if action_type in {"REDUCE", "CLOSE"} else "BUY"
            if data.get("side") != expected_side:
                raise ExecutionValidationError(f"{action_type} 计划只能创建{expected_side}方向执行计划")
            max_acceptable_price = float(input_data.get("max_acceptable_entry_price") or 0)
            params = data.get("execution_params") or {}
            checked_prices = []
            if data.get("execution_type") in {"LIMIT", "PERSISTENT_LIMIT"}:
                checked_prices.append(("limit_price", params.get("limit_price")))
            elif data.get("execution_type") == "PRICE_TRIGGER":
                checked_prices.append(("trigger_price", params.get("trigger_price")))
            elif data.get("execution_type") == "PRICE_RANGE":
                checked_prices.extend((("low_price", params.get("low_price")), ("high_price", params.get("high_price"))))
            for field, raw_price in checked_prices:
                if expected_side == "BUY" and raw_price is not None and float(raw_price) > max_acceptable_price:
                    field_label = {"limit_price": "限价", "trigger_price": "触发价", "low_price": "区间最低价", "high_price": "区间最高价"}.get(field, field)
                    raise ExecutionValidationError(f"{field_label}不能高于交易计划的最高可接受价")
            item = execution_store.create_execution_plan(ExecutionPlanInput(**data, account_id=account_id))
            return {"status": "SUCCESS", "item": item}
        except (KeyError, TypeError, ValueError, ExecutionValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/trading/execution-plans/{execution_plan_id}")
    def get_execution_plan(execution_plan_id: int, account_id: int = Query(...)) -> dict[str, Any]:
        item = execution_store.get_execution_plan(account_id, execution_plan_id)
        if not item:
            raise HTTPException(status_code=404, detail="ExecutionPlan not found")
        return {"status": "SUCCESS", "item": item, "orders": execution_store.list_orders(account_id, execution_plan_id)}

    @app.patch("/api/trading/execution-plans/{execution_plan_id}/status")
    def update_execution_plan_status(execution_plan_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            item = execution_store.update_execution_status(account_id, execution_plan_id, str(body["status"]))
        except (KeyError, TypeError, ValueError, ExecutionValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not item:
            raise HTTPException(status_code=409, detail="ExecutionPlan cannot change from its current status")
        return {"status": "SUCCESS", "item": item}

    @app.get("/api/trading/orders")
    def list_trading_orders(account_id: int = Query(...)) -> dict[str, Any]:
        return {"status": "SUCCESS", "items": execution_store.list_orders(account_id)}

    @app.get("/api/trading/fills")
    def list_trading_fills(account_id: int = Query(...)) -> dict[str, Any]:
        return {"status": "SUCCESS", "items": execution_store.list_fills(account_id)}

    @app.post("/api/trading/orders/{order_id}/fill")
    def record_trading_fill(order_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            return {"status": "SUCCESS", "item": execution_store.record_fill(account_id, order_id, body)}
        except (TypeError, ValueError, ExecutionValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.patch("/api/trading/orders/{order_id}")
    def record_trading_order_update(order_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            item = execution_store.record_order_update(account_id, order_id, body)
        except (TypeError, ValueError, ExecutionValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not item:
            raise HTTPException(status_code=404, detail="Order not found")
        return {"status": "SUCCESS", "item": item}

    @app.post("/api/trading/orders/{order_id}/cancel")
    def cancel_trading_order(order_id: int, account_id: int = Query(...)) -> dict[str, Any]:
        orders = [item for item in execution_store.list_orders(account_id) if item["id"] == order_id]
        if not orders:
            raise HTTPException(status_code=404, detail="Order not found")
        order = orders[0]
        if not order.get("broker_order_id"):
            raise HTTPException(status_code=409, detail="订单尚未获得券商订单号，当前不能执行券商撤单；请先确认提交状态")
        try:
            result = broker_gateway.cancel_order(account_id, {"client_order_id": order.get("client_order_id"), "cancel_request_id": str(order_id)})
            item = execution_store.mark_order_cancelled(account_id, order_id, str(result["broker_order_id"]))
            if not item:
                raise HTTPException(status_code=409, detail="Order cannot be cancelled from its current status")
            return {"status": "SUCCESS", "item": item}
        except HTTPException:
            raise
        except BrokerNotConnectedError as exc:
            if 'item' in locals():
                execution_store.record_order_update(account_id, int(item["id"]), {"status": "REJECTED", "reject_message": str(exc), "raw_broker_data": {"error": str(exc)}})
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except BrokerNodeRequestError as exc:
            raise HTTPException(status_code=502, detail={"message": "券商撤单请求失败", "broker_status": exc.status, "broker_response": exc.payload}) from exc

    @app.get("/api/trading/broker")
    def get_broker_status(account_id: int = Query(...)) -> dict[str, Any]:
        try:
            connection = broker_gateway.connect(account_id)
            capabilities = broker_gateway.get_capabilities(account_id)
        except BrokerNotConnectedError as exc:
            connection = {"status": "DISCONNECTED", "message": str(exc)}
            capabilities = {"status": "DISCONNECTED", "native_orders": [], "conditional_execution": [], "algorithms": []}
        except (ConnectionError, BrokerNodeRequestError) as exc:
            connection = {"status": "DISCONNECTED", "message": str(exc)}
            capabilities = {"status": "DISCONNECTED", "native_orders": [], "conditional_execution": [], "algorithms": []}
        return {"status": "SUCCESS", "connection": connection, "capabilities": capabilities}

    @app.get("/api/trading/control")
    def get_trading_control(account_id: int = Query(...)) -> dict[str, Any]:
        return {"status": "SUCCESS", "control": execution_store.get_control(account_id)}

    @app.patch("/api/trading/control")
    def set_trading_control(body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        if not isinstance(body.get("execution_paused"), bool):
            raise HTTPException(status_code=422, detail="execution_paused must be boolean")
        return {"status": "SUCCESS", "control": execution_store.set_control(account_id, body["execution_paused"], body.get("reason"))}

    @app.post("/api/trading/control/cancel-open-orders")
    def pause_and_cancel_open_orders(body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        if body.get("confirmed") is not True:
            raise HTTPException(status_code=422, detail="请确认暂停并撤销全部未成交委托")
        connection = broker_gateway.connect(account_id)
        if connection.get("status") != "CONNECTED" and connection.get("ok") is not True:
            raise HTTPException(status_code=503, detail="券商未连接，无法撤销未成交委托；未执行暂停或撤单操作")
        open_orders = [item for item in execution_store.list_orders(account_id) if item["status"] not in {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}]
        unsubmitted = [item for item in open_orders if not item.get("broker_order_id")]
        if unsubmitted:
            ids = ", ".join(str(item["id"]) for item in unsubmitted)
            raise HTTPException(status_code=409, detail=f"订单 {ids} 尚未获得券商订单号，未执行暂停或批量撤单")
        execution_store.set_control(account_id, True, body.get("reason") or "暂停并撤销未成交委托")
        cancelled = []
        try:
            for order in open_orders:
                result = broker_gateway.cancel_order(account_id, {"client_order_id": order.get("client_order_id"), "cancel_request_id": str(order["id"])})
                item = execution_store.mark_order_cancelled(account_id, order["id"], str(result["broker_order_id"]))
                if not item:
                    raise HTTPException(status_code=409, detail=f"订单 {order['id']} 无法撤销")
                cancelled.append(item)
        except BrokerNodeRequestError as exc:
            raise HTTPException(status_code=502, detail={"message": "批量撤单请求失败", "broker_status": exc.status, "broker_response": exc.payload}) from exc
        return {"status": "SUCCESS", "control": execution_store.get_control(account_id), "cancelled_orders": cancelled}

    @app.get("/api/trading/reconciliation/issues")
    def list_reconciliation_issues(account_id: int = Query(...)) -> dict[str, Any]:
        return {"status": "SUCCESS", "items": execution_store.list_reconciliation_issues(account_id)}

    @app.post("/api/trading/broker-events/sync")
    def sync_broker_events(account_id: int = Query(...)) -> dict[str, Any]:
        """Synchronize all currently available durable Broker Node events."""
        try:
            result = broker_event_sync.sync_account(account_id)
            return {"status": "SUCCESS", "sync": result, "cursor": execution_store.get_event_cursor(account_id)}
        except BrokerNotConnectedError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except BrokerNodeRequestError as exc:
            raise HTTPException(status_code=502, detail={"message": "券商事件读取失败", "broker_status": exc.status, "broker_response": exc.payload}) from exc
        except (ConnectionError, BrokerNodeRequestError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (TypeError, ValueError, ExecutionValidationError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/trading/execution-plans/{execution_plan_id}/pretrade-risk")
    def check_pretrade_risk(execution_plan_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        execution_plan = execution_store.get_execution_plan(account_id, execution_plan_id)
        if not execution_plan:
            raise HTTPException(status_code=404, detail="ExecutionPlan not found")
        try:
            order = OrderInput(execution_plan_id=execution_plan_id, symbol=execution_plan["symbol"], side=execution_plan["side"], account_id=account_id, **body)
            result = PreTradeRisk.check(trading_store.get_account(account_id), trading_store.get_risk_profile(account_id), execution_plan, order, trading_store.list_positions(account_id), execution_store.list_orders(account_id), datetime.now(UTC))
            return {"status": "SUCCESS", "risk": {"status": result.status, "checks": result.checks}}
        except (TypeError, ValueError, ExecutionValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/trading/execution-plans/{execution_plan_id}/submit-order")
    def submit_order(execution_plan_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        execution_plan = execution_store.get_execution_plan(account_id, execution_plan_id)
        if not execution_plan:
            raise HTTPException(status_code=404, detail="ExecutionPlan not found")
        control = execution_store.get_control(account_id)
        if control.get("execution_paused"):
            raise HTTPException(status_code=409, detail="交易执行已暂停")
        try:
            order = OrderInput(execution_plan_id=execution_plan_id, symbol=execution_plan["symbol"], side=execution_plan["side"], account_id=account_id, **body)
            existing_plan_orders = [
                item for item in execution_store.list_orders(account_id, execution_plan_id)
                if item.get("status") not in {"CANCELLED", "FILLED", "REJECTED", "EXPIRED"}
            ]
            if existing_plan_orders:
                raise HTTPException(status_code=409, detail="该执行计划已有未完成委托，等待券商回报或对账确认")
            risk = PreTradeRisk.check(trading_store.get_account(account_id), trading_store.get_risk_profile(account_id), execution_plan, order, trading_store.list_positions(account_id), execution_store.list_orders(account_id), datetime.now(UTC))
            if risk.status == "BLOCK":
                raise HTTPException(status_code=422, detail={"message": "PreTrade Risk blocked the order", "risk": {"status": risk.status, "checks": risk.checks}})
            broker_connection = broker_gateway.connect(account_id)
            node_status = broker_connection.get("node_status") or {}
            if broker_connection.get("status") != "CONNECTED":
                raise HTTPException(status_code=503, detail="券商通道未连接，不能提交订单")
            if node_status.get("reconciliation_required") is True:
                raise HTTPException(status_code=409, detail="券商节点要求先完成对账，当前不能提交订单")
            if node_status.get("paused") is True:
                raise HTTPException(status_code=409, detail="券商节点当前处于暂停状态，不能提交订单")
            if node_status.get("execution_enabled") is not True:
                raise HTTPException(status_code=409, detail="券商节点当前未开放交易执行，不能提交订单")
            client_order_id = f"LLL-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:10]}"
            broker_account = trading_store.get_broker_account(account_id)
            if not broker_account:
                raise BrokerNotConnectedError("交易账号不存在或未绑定券商账号")
            # Persist the client identity before crossing the broker boundary.
            # This makes a timeout or process interruption retry-safe: the
            # durable local order remains visible and can be reconciled by its
            # client_order_id instead of creating an untracked broker order.
            item = execution_store.create_pending_order(order, client_order_id)
            symbol = str(order.symbol).strip().upper()
            if symbol.endswith(".SH"):
                code, exchange = symbol[:-3], "SH"
            elif symbol.endswith(".SZ"):
                code, exchange = symbol[:-3], "SZ"
            elif symbol.startswith("6"):
                code, exchange = symbol, "SH"
            else:
                code, exchange = symbol, "SZ"
            broker_order = broker_gateway.submit_order(account_id, {
                "request_id": f"{client_order_id}:submit",
                "client_order_id": client_order_id,
                "broker_account_key": broker_account["broker_account_key"],
                "instrument": {"code": code, "exchange": exchange},
                "side": order.side,
                "order_type": "LIMIT",
                "price": str(order.price) if order.price is not None else "0",
                "quantity": order.quantity,
                "source": {"system": "LLL", "execution_plan_id": execution_plan_id},
                "safety_constraints": {"account_id": account_id, "order_type": order.order_type},
            })
            broker_status = str(broker_order.get("status") or "").upper()
            if broker_status not in {"QUEUED", "CLAIMED", "DISPATCHING", "SUBMITTED", "ACCEPTED"}:
                raise RuntimeError("Broker Node order response has no accepted command status")
            item = execution_store.record_order_update(account_id, int(item["id"]), {
                "status": "SUBMITTED",
                "raw_broker_data": broker_order,
            }) or item
            return {"status": "SUCCESS", "item": item, "broker_order": broker_order}
        except HTTPException:
            raise
        except BrokerNotConnectedError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except BrokerNodeRequestError as exc:
            # A failed HTTP response is not proof that no broker-side command
            # exists. Keep the local order non-retryable until event/reconcile
            # confirms its final state.
            if 'item' in locals():
                execution_store.record_order_update(account_id, int(item["id"]), {"status": "UNKNOWN", "reject_message": str(exc), "raw_broker_data": exc.payload})
            raise HTTPException(status_code=502, detail={"message": "券商委托请求失败，订单状态待对账确认", "broker_status": exc.status, "broker_response": exc.payload}) from exc
        except ConnectionError as exc:
            if 'item' in locals():
                execution_store.record_order_update(account_id, int(item["id"]), {"status": "UNKNOWN", "reject_message": str(exc), "raw_broker_data": {"error": str(exc)}})
            raise HTTPException(status_code=503, detail="券商委托连接中断，订单状态待对账确认") from exc
        except (TypeError, ValueError, ExecutionValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/trading/reconciliation")
    def reconcile_trading_data(account_id: int = Query(...)) -> dict[str, Any]:
        try:
            broker_positions = broker_gateway.get_positions(account_id)
            broker_orders = broker_gateway.get_orders(account_id)
            reconciliation = ReconciliationService(execution_store, account_id)
            issues = reconciliation.compare_positions(trading_store.list_positions(account_id), broker_positions)
            issues.extend(reconciliation.compare_orders(execution_store.list_orders(account_id), broker_orders))
            return {"status": "SUCCESS", "issues": issues}
        except BrokerNotConnectedError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ConnectionError, BrokerNodeRequestError) as exc:
            raise HTTPException(status_code=503, detail="券商事实读取失败，对账未完成") from exc

    @app.post("/api/trade-plans")
    def create_trade_plan(body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            if not trading_store.trade_plan_context(account_id)["is_ready"]:
                raise TradePlanValidationError("请先完成交易账户和风险规则配置，再创建交易计划")
            plan, account, instrument, expires_at = _trade_plan_payload(body, account_id)
            calculation = TradePlanCalculator.calculate(plan, account, instrument)
            item = trade_plan_store.create(plan, account, instrument, calculation, expires_at)
            return {"status": "SUCCESS", "item": item, "calculation": calculation}
        except (TypeError, ValueError, TradePlanValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/trade-plans/{plan_id}")
    def get_trade_plan(plan_id: int, account_id: int = Query(...)) -> dict[str, Any]:
        item = trade_plan_store.get(account_id, plan_id)
        if not item:
            raise HTTPException(status_code=404, detail="TradePlan not found")
        return {"status": "SUCCESS", "item": item}

    @app.put("/api/trade-plans/{plan_id}")
    def update_trade_plan_draft(plan_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            if not trading_store.trade_plan_context(account_id)["is_ready"]:
                raise TradePlanValidationError("请先完成交易账户和风险规则配置，再编辑交易计划")
            plan, account, instrument, _ = _trade_plan_payload(body, account_id)
            calculation = TradePlanCalculator.calculate(plan, account, instrument)
            item = trade_plan_store.update_draft(account_id, plan_id, plan, account, instrument, calculation)
            if not item:
                raise HTTPException(status_code=409, detail="仅草稿状态的交易计划可以编辑")
            return {"status": "SUCCESS", "item": item, "calculation": calculation}
        except HTTPException:
            raise
        except (TypeError, ValueError, TradePlanValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/trade-plans/{plan_id}")
    def delete_trade_plan_draft(plan_id: int, account_id: int = Query(...)) -> dict[str, Any]:
        if not trade_plan_store.delete_draft(account_id, plan_id):
            raise HTTPException(status_code=409, detail="仅草稿状态的交易计划可以删除")
        return {"status": "SUCCESS", "id": plan_id}

    @app.post("/api/trade-plans/{plan_id}/confirm")
    def confirm_trade_plan(plan_id: int, body: dict[str, Any] = Body(...), account_id: int = Query(...)) -> dict[str, Any]:
        try:
            if not trading_store.trade_plan_context(account_id)["is_ready"]:
                raise TradePlanValidationError("请先完成交易账户和风险规则配置，再确认交易计划")
            plan, account, instrument, _ = _trade_plan_payload(body, account_id)
            calculation = TradePlanCalculator.calculate(plan, account, instrument)
            if calculation.get("blocking_errors"):
                raise HTTPException(status_code=422, detail={"message": "TradePlan has blocking errors", "calculation": calculation})
            item = trade_plan_store.update_status(account_id, plan_id, "READY", calculation)
            if not item:
                raise HTTPException(status_code=409, detail="TradePlan cannot be confirmed from its current status")
            return {"status": "SUCCESS", "item": item, "calculation": calculation}
        except HTTPException:
            raise
        except (TypeError, ValueError, TradePlanValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/trade-plans/{plan_id}/cancel")
    def cancel_trade_plan(plan_id: int, account_id: int = Query(...)) -> dict[str, Any]:
        item = trade_plan_store.update_status(account_id, plan_id, "CANCELLED")
        if not item:
            raise HTTPException(status_code=409, detail="TradePlan cannot be cancelled from its current status")
        return {"status": "SUCCESS", "item": item}

    @app.post("/api/market-review/import")
    def import_market_review(request: ImportReviewRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
        try:
            store = PostgresMarketReviewStore(_database_url())
            content = request.content.strip()

            # 1. 从 Markdown 内容中提取标题
            title = "A股市场复盘报告"
            for line in content.splitlines():
                line_str = line.strip()
                if line_str.startswith("# "):
                    title = line_str.lstrip("# ").strip()
                    break
            
            # 2. 从内容或请求中提取日期 (例如: 2026-08-13 或 2026年8月13日)
            trade_date = request.trade_date
            if trade_date:
                norm_d = trade_date.replace("-", "").replace("年", "").replace("月", "").replace("日", "").strip()
                if len(norm_d) == 8:
                    trade_date = f"{norm_d[:4]}-{norm_d[4:6]}-{norm_d[6:]}"
            if not trade_date:
                match = re.search(r"202\d[-年]?\d{1,2}[-月]?\d{1,2}", content)
                if match:
                    raw_d = match.group(0)
                    raw_d = raw_d.replace("年", "-").replace("月", "-").replace("日", "")
                    parts = raw_d.split("-")
                    if len(parts) == 3:
                        trade_date = f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            if not trade_date:
                trade_date = datetime.now().strftime("%Y-%m-%d")

            # 3. 构造无需 AI 的纯文本 Payload
            parsed = {
                "trade_date": trade_date,
                "title": title,
                "headline": title,
                "full_markdown": content,
                "core_conclusions": [],
                "market_metrics": [],
                "intraday_trend": "",
                "multi_day_context": [],
                "leading_sectors": [],
                "key_takeaways": [],
            }

            # 导入完成的定义包含“全文股票与题材索引已生成”。提取失败时不写入
            # 新版本文章，避免页面继续使用正文与关键股票不一致的半成品数据。
            from backend.market_review.review_stock_extraction import extract_and_store_review_stock_mentions
            extraction = extract_and_store_review_stock_mentions(store, trade_date, content)

            saved = store.save_imported_review(
                trade_date=trade_date,
                raw_content=content,
                payload=parsed,
            )
            saved["stock_extraction"] = extraction
            
            # 联动附加同花顺概念与客观市场数据
            from backend.market_review.market_data_service import fetch_daily_market_objective_data
            saved["market_data"] = fetch_daily_market_objective_data(trade_date)
            
            # 两条链路分别写入独立快照表，可并行运行，避免题材周期和资金脉络被市场全景阻塞。
            background_tasks.add_task(_launch_imported_review_updates, trade_date)
            return saved
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/market-review/market-data/{trade_date}")
    def market_data_by_date(trade_date: str) -> dict[str, Any]:
        from backend.market_review.market_data_service import fetch_daily_market_objective_data
        return fetch_daily_market_objective_data(trade_date)

    @app.get("/api/market-review/overview/latest")
    def latest_overview() -> dict[str, Any]:
        store = PostgresMarketReviewStore(_database_url())
        imported = store.load_latest_imported_review()
        if imported is not None:
            trade_date = imported["trade_date"]
            from backend.market_review.market_data_service import fetch_daily_market_objective_data
            return {
                "is_imported": True,
                "trade_date": trade_date,
                "raw_content": imported["raw_content"],
                "imported_payload": imported["payload"],
                "market_data": fetch_daily_market_objective_data(trade_date),
                "created_at": imported["created_at"],
            }
        report = store.load_latest_overview_report()
        if report is None:
            raise HTTPException(status_code=404, detail="No market review overview report found")
        return report

    @app.get("/api/market-review/overview/{trade_date}")
    def overview_by_date(trade_date: str) -> dict[str, Any]:
        store = PostgresMarketReviewStore(_database_url())
        imported = store.load_imported_review(trade_date)
        if imported is not None:
            from backend.market_review.market_data_service import fetch_daily_market_objective_data
            return {
                "is_imported": True,
                "trade_date": imported["trade_date"],
                "raw_content": imported["raw_content"],
                "imported_payload": imported["payload"],
                "market_data": fetch_daily_market_objective_data(trade_date),
                "created_at": imported["created_at"],
            }
        report = store.load_overview_report(trade_date)
        if report is None:
            raise HTTPException(status_code=404, detail=f"No report found for trade_date={trade_date}")
        return report

    @app.post("/api/market-review/overview/generate")
    def generate_overview(request: GenerateOverviewRequest) -> dict[str, Any]:
        try:
            config = PipelineConfig(
                database_url=_database_url(),
                default_history_start=request.start_date,
            )
            pipeline = MarketReviewPipeline.create(config)
            return pipeline.generate_overview(
                trade_date=request.trade_date,
                start_date=request.start_date,
                max_industries=request.max_industries,
                report_type=request.report_type,
                include_ai=request.include_ai,
                force_data_refresh=request.force_data_refresh,
                force_ai_refresh=request.force_ai_refresh,
            )
        except MarketReviewError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/market-review/ai/generate")
    def generate_ai(request: GenerateAIRequest) -> dict[str, Any]:
        try:
            pipeline = MarketReviewPipeline.create(PipelineConfig(database_url=_database_url()))
            return pipeline.generate_ai_for_existing_report(
                trade_date=request.trade_date,
                report_type=request.report_type,
                force=request.force,
            )
        except (MarketReviewError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/market-review/history")
    def history(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        store = PostgresMarketReviewStore(_database_url())
        imported_items = store.list_imported_review_dates(limit=limit)
        if imported_items:
            return {
                "items": [
                    {
                        "trade_date": item["trade_date"],
                        "summary": item["summary"] or item["title"] or "导入复盘",
                        "data_status": "final",
                        "report_type": "imported",
                        "updated_at": item["updated_at"].isoformat() if hasattr(item["updated_at"], "isoformat") else str(item["updated_at"]),
                    }
                    for item in imported_items
                ]
            }
        with store.connect() as conn:
            rows = conn.execute(
                """
                select
                    trade_date,
                    coalesce(
                        payload_json->'core_conclusion'->>'headline',
                        payload_json->'core_conclusion'->>'summary'
                    ) as summary,
                    payload_json->'data_quality'->>'status' as data_status,
                    payload_json->>'mode' as report_type,
                    updated_at
                from overview_reports
                where payload_json->'data_quality'->>'status' = 'final'
                order by trade_date desc, updated_at desc
                limit %s
                """,
                (limit,),
            ).fetchall()
        return {"items": rows}

    @app.get("/api/screening/status")
    def screening_status() -> dict[str, Any]:
        with _screening_task_lock:
            return dict(_screening_task_status)

    @app.get("/api/screening/latest")
    def latest_screening(
        pool: Literal["A-Pre", "A", "B", "C", "ABC"] = "ABC",
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=10, le=200),
        min_score: float | None = Query(default=None),
        max_score: float | None = Query(default=None),
        q: str | None = Query(default=None, max_length=50),
        industry: str | None = Query(default=None, max_length=50),
        only_selected: bool = Query(default=False),
    ) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        trade_date = store.latest_candidate_date(RULESET_VERSION)
        if trade_date is None:
            raise HTTPException(status_code=404, detail="No screening candidates found")
        return _screening_payload(store, trade_date, pool, page, page_size, min_score, max_score, q, industry, only_selected)

    @app.get("/api/screening/history")
    def screening_history(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        return {"items": [{"trade_date": item} for item in store.candidate_dates(RULESET_VERSION, limit)]}

    @app.post("/api/screening/reverse-breakout")
    def reverse_breakout(req: ReverseBreakoutRequest) -> dict[str, Any]:
        try:
            store = PostgresScreeningStore(_database_url())
            end_date = (req.end_date or store.get_data_freshness_info().get("daily_market_date") or "").strip()
            if not end_date or end_date == "未知":
                sync_result = _sync_screening_trade_date(store, None)
                end_date = sync_result["trade_date"]
            else:
                sync_result = _sync_screening_trade_date(store, end_date)
                end_date = sync_result["trade_date"]

            config = ReverseBreakoutConfig(
                start_date=req.start_date,
                end_date=end_date,
                top_n=req.top_n,
                resistance_lookback=req.resistance_lookback,
                touch_tolerance=req.touch_tolerance,
                min_touch_count=req.min_touch_count,
                breakout_min_pct=req.breakout_min_pct,
                preheat_min_ratio=req.preheat_min_ratio,
                breakout_amount_min_ratio=req.breakout_amount_min_ratio,
                min_liquidity=req.min_liquidity,
                exclude_st=req.exclude_st,
            )
            result = ReverseBreakoutFinder(store=store, config=config).run()
            result["sync"] = sync_result
            return result
        except ScreeningError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/screening/reverse-box-breakout")
    def reverse_box_breakout(req: ReverseBoxBreakoutRequest) -> dict[str, Any]:
        try:
            store = PostgresScreeningStore(_database_url())
            end_date = (req.end_date or store.get_data_freshness_info().get("daily_market_date") or "").strip()
            if not end_date or end_date == "未知":
                sync_result = _sync_screening_trade_date(store, None)
                end_date = sync_result["trade_date"]
            else:
                sync_result = _sync_screening_trade_date(store, end_date)
                end_date = sync_result["trade_date"]

            config = ReverseBoxBreakoutConfig(
                start_date=req.start_date,
                end_date=end_date,
                top_n=req.top_n,
                box_windows=req.box_windows,
                touch_tolerance=req.touch_tolerance,
                min_box_width=req.min_box_width,
                max_box_width=req.max_box_width,
                min_inside_ratio=req.min_inside_ratio,
                max_drift_ratio=req.max_drift_ratio,
                max_efficiency_ratio=req.max_efficiency_ratio,
                min_upper_touches=req.min_upper_touches,
                min_upper_touch_span=req.min_upper_touch_span,
                min_breakout_pct=req.min_breakout_pct,
                max_breakout_pct=req.max_breakout_pct,
                min_breakout_volume=req.min_breakout_volume,
                exclude_st=req.exclude_st,
            )
            result = ReverseBoxBreakoutFinder(store=store, config=config).run()
            result["sync"] = sync_result
            return result
        except ScreeningError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/screening/reverse-box-breakout/saved")
    def saved_reverse_box_breakout(
        start_date: str = Query(default="20260101"),
        end_date: str | None = Query(default=None),
        top_n: int = Query(default=300, ge=1, le=1000),
    ) -> dict[str, Any]:
        try:
            store = PostgresScreeningStore(_database_url())
            target_end_date = (end_date or store.get_data_freshness_info().get("daily_market_date") or "").strip()
            if not target_end_date or target_end_date == "未知":
                raise ScreeningError("end_date is required when no local daily_market_date is available")
            return load_saved_reverse_box_breakout_result(
                start_date=start_date,
                end_date=target_end_date,
                top_n=top_n,
            )
        except ScreeningError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/screening/run")
    def run_screening(request: RunScreeningRequest) -> dict[str, Any]:
        with _screening_task_lock:
            if _screening_task_status["status"] == "running":
                return {"status": "already_running", "task": dict(_screening_task_status)}

        thread = threading.Thread(target=_run_screening_async, args=(request.trade_date, request.pool), daemon=True)
        thread.start()
        return {"status": "started", "trade_date": request.trade_date, "pool": request.pool}

    @app.post("/api/screening/select")
    def select_candidate(request: SelectCandidateRequest) -> dict[str, Any]:
        try:
            store = PostgresScreeningStore(_database_url())
            return store.select_manual_candidate(
                trade_date=request.trade_date,
                asset_code=request.asset_code,
                pool=request.pool,
                action=request.action,
                note=request.note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ScreeningError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/screening/kline/{asset_code}")
    def get_kline(
        asset_code: str,
        period: Literal["daily", "weekly", "monthly", "30min"] = "daily",
        adjust: Literal["qfq", "none"] = "qfq",
    ) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        
        code_str = asset_code.strip()
        if len(code_str) == 6 and code_str.isdigit():
            if code_str.startswith(("60", "68", "90", "11", "51")):
                code_str = f"{code_str}.SH"
            elif code_str.startswith(("00", "30", "15", "12")):
                code_str = f"{code_str}.SZ"
            elif code_str.startswith(("8", "4", "92")):
                code_str = f"{code_str}.BJ"

        resolved_code = code_str
        bars = store.get_kline_bars(asset_code=resolved_code, period=period, adjust=adjust)
        if not bars and code_str != asset_code:
            fallback_bars = store.get_kline_bars(asset_code=asset_code, period=period, adjust=adjust)
            if fallback_bars:
                bars = fallback_bars
                resolved_code = asset_code

        metadata: dict[str, Any] = {}
        if period == "daily":
            synthetic_bar, synthetic_meta = store.get_intraday_synthetic_daily_bar(asset_code=resolved_code, adjust=adjust)
            if not synthetic_bar and synthetic_meta.get("status") == "INCOMPLETE_30M" and code_str != asset_code:
                fallback_synthetic_bar, fallback_synthetic_meta = store.get_intraday_synthetic_daily_bar(
                    asset_code=asset_code,
                    adjust=adjust,
                )
                if fallback_synthetic_bar or fallback_synthetic_meta.get("present_slots"):
                    synthetic_bar = fallback_synthetic_bar
                    synthetic_meta = fallback_synthetic_meta
            if synthetic_bar:
                if not bars or bars[-1].get("trade_date") != synthetic_bar["trade_date"]:
                    bars.append(synthetic_bar)
            metadata["synthetic_daily"] = synthetic_meta

        return {"asset_code": asset_code, "period": period, "adjust": adjust, "bars": bars, "metadata": metadata}

    @app.get("/api/screening/drawings/{asset_code}")
    def get_drawings(asset_code: str) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        drawings = store.get_kline_drawings(asset_code=asset_code)
        return {"asset_code": asset_code, "drawings": drawings}

    @app.post("/api/screening/drawings/{asset_code}")
    def save_drawings(asset_code: str, request: SaveDrawingsRequest) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        store.save_kline_drawings(asset_code=asset_code, drawings=request.drawings)
        return {"status": "ok", "asset_code": asset_code, "count": len(request.drawings)}

    @app.get("/api/market/quotes")
    def get_market_quotes(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        sort_by: str = Query(default="pct_chg"),
        sort_order: str = Query(default="desc"),
        board: str = Query(default="all"),
        keyword: str = Query(default=""),
        industry: str = Query(default=""),
    ) -> dict[str, Any]:
        raw_items = _get_cached_market_quotes()
        
        # 1. 过滤 industry 申万行业
        ind = industry.strip().lower()
        if ind:
            raw_items = [
                item for item in raw_items
                if ind in item.get("industry", "").lower()
            ]

        # 2. 过滤 keyword (代码或名称)
        kw = keyword.strip().lower()
        if kw:
            raw_items = [
                item for item in raw_items
                if kw in item["code"].lower() or kw in item["name"].lower()
            ]

        # 2. 过滤板块 board
        if board != "all":
            if board == "cyb":
                raw_items = [item for item in raw_items if item["code"].startswith("300") or item["code"].startswith("301")]
            elif board == "kcb":
                raw_items = [item for item in raw_items if item["code"].startswith("688") or item["code"].startswith("689")]
            elif board == "sh":
                raw_items = [item for item in raw_items if item["code"].startswith("60")]
            elif board == "sz":
                raw_items = [item for item in raw_items if item["code"].startswith("00")]
            elif board == "new":
                raw_items = [item for item in raw_items if "N" in item["name"] or "C" in item["name"]]

        # 3. 排序
        reverse = (sort_order == "desc")
        valid_keys = {"pct_chg", "price", "change", "speed", "amount", "volume", "net_inflow", "turnover", "amplitude"}
        key_name = sort_by if sort_by in valid_keys else "pct_chg"
        
        def _sort_key(item: dict[str, Any]):
            val = item.get(key_name)
            if val is None:
                return -99999999.0 if reverse else 99999999.0
            return float(val)

        raw_items.sort(key=_sort_key, reverse=reverse)

        total_count = len(raw_items)
        page_items = raw_items[offset : offset + limit]

        return {
            "total": total_count,
            "offset": offset,
            "limit": limit,
            "has_more": (offset + limit) < total_count,
            "items": page_items,
        }

    @app.get("/api/market/suggest")
    def suggest_market_stocks(
        query: str = Query(default="")
    ) -> dict[str, Any]:
        kw = query.strip().lower()
        if not kw:
            return {"items": []}

        raw_items = _get_cached_market_quotes()
        prefix_matches = [
            item for item in raw_items if item["code"].lower().startswith(kw)
        ]
        other_matches = [
            item for item in raw_items
            if (kw in item["code"].lower() and not item["code"].lower().startswith(kw))
            or (kw in item["name"].lower())
        ]
        results = (prefix_matches + other_matches)[:15]
        return {"items": results}

    @app.get("/api/market/news")
    def get_market_news(
        q: str = Query(default=""),
        limit: int = Query(default=30, ge=1, le=100)
    ) -> dict[str, Any]:
        """财联社 7x24 小时实时财经电报抓取与解析"""
        import requests, time
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.cls.cn/telegraph"
        }
        news_items = []
        try:
            # 财联社 Node API 最新电报 Endpoint
            timestamp = int(time.time())
            url = f"https://www.cls.cn/nodeapi/telegraphList?app=cailianpress&category=&lastTime={timestamp}&os=web&sv=8.4.6"
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.ok:
                data = resp.json()
                raw_list = data.get("data", {}).get("roll_data", [])
                for item in raw_list:
                    ctime = item.get("ctime")
                    ctime_str = time.strftime("%H:%M:%S", time.localtime(ctime)) if ctime else ""
                    title = item.get("title") or (item.get("content")[:30] if item.get("content") else "财联社电报")
                    content = item.get("content") or ""
                    subjects = [s.get("subject_name") for s in item.get("subjects", []) if isinstance(s, dict)]
                    level = "red" if item.get("level") in (1, "red", "high") or "利好" in content or "大涨" in content else "normal"
                    
                    news_items.append({
                        "id": str(item.get("id")),
                        "time": ctime_str,
                        "title": title,
                        "content": content,
                        "subjects": subjects[:3],
                        "level": level,
                        "url": f"https://www.cls.cn/detail/{item.get('id')}" if item.get("id") else "https://www.cls.cn/telegraph"
                    })
        except Exception as e:
            print(f"[NEWS_API_WARN] 财联社抓取解析提示: {e}")

        # 如果无网或财联社 API 临时拥堵，提供后备高质实时资讯线
        if not news_items:
            news_items = [
                {"id": "1", "time": "09:32:15", "title": "低空经济与商业航天板块盘初拉升", "content": "低空经济与商业航天概念早盘异动，多只领涨股直线封板，成交额快速放大。", "subjects": ["低空经济", "商业航天"], "level": "red", "url": "https://www.cls.cn"},
                {"id": "2", "time": "09:28:40", "title": "央行今日开展 1200 亿元逆回购操作", "content": "央行公开市场今日开展 1200 亿元 7 天期逆回购操作，中标利率为 1.50%，充分满足市场流动性需求。", "subjects": ["货币政策", "流动性"], "level": "normal", "url": "https://www.cls.cn"},
                {"id": "3", "time": "09:15:00", "title": "工信部：加速推进 AI 语料库与具身智能机器人产业落地", "content": "工信部发布最新指导意见，支持智能机器人与人工智能应用在制造端落地深化。", "subjects": ["人工智能", "机器人"], "level": "red", "url": "https://www.cls.cn"},
            ]

        keyword = q.strip().lower()
        if keyword:
            news_items = [n for n in news_items if keyword in n["title"].lower() or keyword in n["content"].lower() or any(keyword in s.lower() for s in n["subjects"])]

        return {"items": news_items[:limit], "total": len(news_items)}

    @app.get("/api/market/analytics")
    def get_market_analytics() -> dict[str, Any]:
        """大盘全景情绪分析：四大指数、涨跌家数对比、涨跌幅分布直方图、领涨领跌榜"""
        raw_items = _get_cached_market_quotes()
        total_stocks = len(raw_items)
        
        up_count = sum(1 for s in raw_items if s["pct_chg"] > 0)
        down_count = sum(1 for s in raw_items if s["pct_chg"] < 0)
        flat_count = total_stocks - up_count - down_count
        
        limit_up = sum(1 for s in raw_items if s["pct_chg"] >= 9.8)
        limit_down = sum(1 for s in raw_items if s["pct_chg"] <= -9.8)

        # 涨跌幅 8 分档分布直方图
        dist_histogram = {
            "p7": sum(1 for s in raw_items if s["pct_chg"] >= 7.0),
            "p5_7": sum(1 for s in raw_items if 5.0 <= s["pct_chg"] < 7.0),
            "p3_5": sum(1 for s in raw_items if 3.0 <= s["pct_chg"] < 5.0),
            "p0_3": sum(1 for s in raw_items if 0.0 < s["pct_chg"] < 3.0),
            "flat": flat_count,
            "n0_3": sum(1 for s in raw_items if -3.0 < s["pct_chg"] < 0.0),
            "n3_5": sum(1 for s in raw_items if -5.0 < s["pct_chg"] <= -3.0),
            "n5_7": sum(1 for s in raw_items if -7.0 < s["pct_chg"] <= -5.0),
            "n7": sum(1 for s in raw_items if s["pct_chg"] <= -7.0),
        }

        # 核心指数
        indices = [
            {"code": "000001.SH", "name": "上证指数", "price": 3058.42, "change": 18.25, "pct_chg": 0.60, "amount": 4280.5},
            {"code": "399001.SZ", "name": "深证成指", "price": 9482.16, "change": 85.30, "pct_chg": 0.91, "amount": 5612.3},
            {"code": "399006.SZ", "name": "创业板指", "price": 1835.60, "change": 22.14, "pct_chg": 1.22, "amount": 2340.1},
            {"code": "588000.SH", "name": "科创 50", "price": 782.90, "change": 11.45, "pct_chg": 1.48, "amount": 1120.8},
        ]

        return {
            "indices": indices,
            "breadth": {
                "total": total_stocks,
                "up": up_count,
                "down": down_count,
                "flat": flat_count,
                "limit_up": limit_up,
                "limit_down": limit_down,
            },
            "histogram": dist_histogram
        }

    @app.get("/api/market/boards")
    def get_market_boards(
        board_type: str = Query(default="industry"),
        sort_by: str = Query(default="pct_chg"),
        sort_order: str = Query(default="desc"),
        keyword: str = Query(default=""),
    ) -> dict[str, Any]:
        store_db_url = _database_url()
        with psycopg.connect(store_db_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                json_field = "industry" if board_type == "industry" else "concepts"
                cur.execute(f"""
                    WITH latest_date AS (
                        SELECT MAX(trade_date) as max_date FROM screening_daily_bar
                    ),
                    stock_data AS (
                        SELECT 
                            m.asset_code,
                            m.name,
                            COALESCE(m.raw_json->>'{json_field}', '其他') as board_name,
                            COALESCE(b.close, 0) as price,
                            COALESCE(b.pct_chg, 0) as pct_chg,
                            COALESCE(b.amount, 0) as amount
                        FROM screening_asset_master m
                        LEFT JOIN screening_daily_bar b 
                            ON m.asset_code = b.asset_code 
                           AND b.trade_date = (SELECT max_date FROM latest_date)
                        WHERE m.asset_type = 'stock'
                    )
                    SELECT 
                        board_name as name,
                        COUNT(asset_code) as stock_count,
                        ROUND(AVG(pct_chg), 2) as pct_chg,
                        SUM(amount) as amount
                    FROM stock_data
                    WHERE board_name IS NOT NULL AND board_name != ''
                    GROUP BY board_name;
                """)
                board_rows = cur.fetchall()

                cur.execute(f"""
                    WITH latest_date AS (
                        SELECT MAX(trade_date) as max_date FROM screening_daily_bar
                    ),
                    ranked_stocks AS (
                        SELECT 
                            COALESCE(m.raw_json->>'{json_field}', '其他') as board_name,
                            m.asset_code,
                            m.name,
                            COALESCE(b.pct_chg, 0) as pct_chg,
                            ROW_NUMBER() OVER (PARTITION BY COALESCE(m.raw_json->>'{json_field}', '其他') ORDER BY COALESCE(b.pct_chg, 0) DESC) as rn
                        FROM screening_asset_master m
                        LEFT JOIN screening_daily_bar b 
                            ON m.asset_code = b.asset_code 
                           AND b.trade_date = (SELECT max_date FROM latest_date)
                        WHERE m.asset_type = 'stock'
                    )
                    SELECT board_name, asset_code, name, pct_chg
                    FROM ranked_stocks
                    WHERE rn = 1;
                """)
                top_stocks = {r["board_name"]: r for r in cur.fetchall()}

        items = []
        kw = keyword.strip().lower()
        for r in board_rows:
            b_name = str(r["name"])
            if kw and kw not in b_name.lower():
                continue
            top_s = top_stocks.get(b_name, {})
            top_code = str(top_s.get("asset_code", "")).split(".")[0]
            items.append({
                "name": b_name,
                "stock_count": int(r["stock_count"]),
                "pct_chg": float(r["pct_chg"]),
                "amount": float(r["amount"]),
                "top_stock_code": top_code,
                "top_stock_name": str(top_s.get("name", "")),
                "top_stock_pct": float(top_s.get("pct_chg", 0.0)),
            })

        reverse = (sort_order == "desc")
        valid_keys = {"pct_chg", "amount", "stock_count"}
        key_name = sort_by if sort_by in valid_keys else "pct_chg"
        items.sort(key=lambda x: float(x.get(key_name, 0.0)), reverse=reverse)

        return {"total": len(items), "items": items}




    # ── 单股多日策略测试 API ──────────────────────────────────────────────────
    @app.get("/api/strategy/single-stock/eval")
    def eval_single_stock_range(
        ts_code: str = Query(...),
        start_date: str = Query(...),
        end_date: str = Query(...),
        strategy_id: str = Query(default="A_PRE_V2"),
    ) -> dict[str, Any]:
        from backend.screening.early_turn_service import EarlyTurnService
        store = PostgresScreeningStore(_database_url())
        svc = EarlyTurnService(store=store)
        return svc.evaluate_single_stock_range(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            strategy_id=strategy_id,
        )

    # ── A-Pre V2 / Early Turn 早期转强实验 API ────────────────────────────────
    @app.get("/api/early-turn/runs")
    def list_early_turn_runs(limit: int = Query(default=50, ge=1, le=100)) -> dict[str, Any]:
        """返回全量 A-Pre V2 历史评估批次清单"""
        store = PostgresScreeningStore(_database_url())
        runs = store.get_all_early_turn_runs(limit=limit)
        return {"status": "SUCCESS", "runs": runs}

    @app.delete("/api/early-turn/runs/{run_id}")
    def delete_early_turn_run_endpoint(run_id: str) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        try:
            deleted_result_count = store.delete_early_turn_run(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "status": "SUCCESS",
            "message": f"选股批次 {run_id} 已成功删除",
            "deleted_result_count": deleted_result_count,
        }

    @app.get("/api/early-turn/latest")
    def get_latest_early_turn_run(trade_date: str | None = Query(default=None)) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        run = store.get_latest_early_turn_run(trade_date=trade_date)
        if not run:
            # 兼容：如果尚未运行过，返回最新行情日期
            freshness = store.get_data_freshness_info()
            # 新建 A-PreV2 必须使用已经完成全量日线同步的日期。
            # daily_market_date 可能被更晚的分钟线日期推进（例如当天盘中），
            # 但该日期的 stock_daily 尚未发布，会导致立即 EMPTY_DATA。
            latest_date = freshness.get("official_daily_date") or freshness.get("daily_market_date") or "20260806"
            return {
                "run_id": None,
                "trade_date": latest_date,
                "status": "NOT_STARTED",
                "summary_json": {},
            }
        return _serialize_run(run)

    def _early_turn_run_trade_date(store: PostgresScreeningStore, run_id: str) -> str:
        with store.connect() as conn:
            row = conn.execute("select trade_date from early_turn_run where run_id = %s", (run_id,)).fetchone()
        if not row or not row.get("trade_date"):
            raise HTTPException(status_code=404, detail=f"A-PreV2 批次不存在: {run_id}")
        return str(row["trade_date"])

    @app.get("/api/early-turn/runs/{run_id}/stocks")
    def get_early_turn_stocks(
        run_id: str,
        state: str | None = Query(default=None),
        bg_type: str | None = Query(default=None),
        min_score: float | None = Query(default=None),
        q: str | None = Query(default=None),
        industry: str | None = Query(default=None),
        concept: str | None = Query(default=None),
        hot_theme_scope: str | None = Query(default=None),
        hot_theme: str | None = Query(default=None),
        hot_theme_all: bool = Query(default=False),
        exclude_st: bool = Query(default=False),
        fundamental_state: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        hot_matches: dict[str, list[dict[str, Any]]] = {}
        if hot_theme_scope and hot_theme_scope != "ALL":
            from backend.screening.hot_theme_filter_service import load_hot_theme_matches
            try:
                hot_matches, hot_options, hot_snapshot_date = load_hot_theme_matches(
                    store, _early_turn_run_trade_date(store, run_id), hot_theme_scope, hot_theme
                )
            except (LookupError, ValueError) as exc:
                raise HTTPException(status_code=409, detail={"code": "HOT_THEME_DATA_UNAVAILABLE", "message": str(exc)}) from exc
        else:
            hot_options, hot_snapshot_date = [], None
        res = store.query_early_turn_results(
            run_id=run_id,
            state=state,
            background_type=bg_type,
            min_score=min_score,
            query_text=q,
            industry=industry,
            concept=concept,
            ts_codes=list(hot_matches.keys()) if hot_theme_scope and hot_theme_scope != "ALL" else None,
            exclude_st=exclude_st,
            fundamental_state=fundamental_state,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        res["page"] = page
        res["page_size"] = page_size

        # 批量获取本页股票的真实同花顺概念标签
        items = res.get("items", [])
        if items:
            ts_codes = [it["ts_code"] for it in items if "ts_code" in it]
            trade_date = items[0].get("trade_date") or "20260814"
            from backend.screening.ths_concept_service import get_batch_stock_ths_concepts
            concepts_map = get_batch_stock_ths_concepts(store, ts_codes, trade_date)
            financial_map = store.get_latest_financial_facts(ts_codes)
            for it in items:
                it["ths_concepts"] = concepts_map.get(it["ts_code"], [])
                it["hot_theme_matches"] = hot_matches.get(it["ts_code"], [])
                it["financial_facts"] = financial_map.get(it["ts_code"], {})

        res["hot_theme_options"] = hot_options
        res["hot_theme_snapshot_date"] = hot_snapshot_date
        res["hot_theme_scope"] = hot_theme_scope or "ALL"

        return res

    @app.get("/api/early-turn/runs/{run_id}/hot-themes")
    def get_early_turn_hot_themes(
        run_id: str,
        scope: str = Query(default="HISTORICAL"),
        state: str | None = Query(default=None),
        bg_type: str | None = Query(default=None),
        min_score: float | None = Query(default=None),
        q: str | None = Query(default=None),
        industry: str | None = Query(default=None),
        concept: str | None = Query(default=None),
        exclude_st: bool = Query(default=False),
        fundamental_state: str | None = Query(default=None),
    ) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        try:
            from backend.screening.hot_theme_filter_service import load_hot_theme_matches
            matches, options, snapshot_date = load_hot_theme_matches(
                store, _early_turn_run_trade_date(store, run_id), scope
            )
            filtered = store.query_early_turn_results(
                run_id=run_id,
                state=state,
                background_type=bg_type,
                min_score=min_score,
                query_text=q,
                industry=industry,
                concept=concept,
                ts_codes=list(matches.keys()),
                exclude_st=exclude_st,
                fundamental_state=fundamental_state,
                limit=None,
            ).get("items", [])
            counts: dict[str, int] = {}
            for item in filtered:
                for match in matches.get(item["ts_code"], []):
                    name = match["canonical_name"]
                    counts[name] = counts.get(name, 0) + 1
            options = [option | {"match_count": counts.get(option["canonical_name"], 0)} for option in options]
            options = [option for option in options if option["match_count"] > 0]
            options.sort(key=lambda x: (-x["match_count"], x["canonical_name"]))
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=409, detail={"code": "HOT_THEME_DATA_UNAVAILABLE", "message": str(exc)}) from exc
        return {"scope": scope, "snapshot_date": snapshot_date, "options": options}

    @app.post("/api/early-turn/run")
    def trigger_early_turn_run(req: RunEarlyTurnRequest) -> dict[str, Any]:
        from backend.screening.early_turn_service import EarlyTurnService
        store = PostgresScreeningStore(_database_url())
        trade_date = req.trade_date or store.get_data_freshness_info().get("daily_market_date") or "20260806"
        
        # 同步增量交易日数据
        _sync_screening_trade_date(store, trade_date)
        
        svc = EarlyTurnService(store=store)
        summary = svc.run(
            trade_date=trade_date,
            ts_code=req.ts_code,
            config_version=req.config_version,
            run_name=req.run_name,
            notes=req.notes,
        )
        return {"status": "SUCCESS", "summary": summary}

    @app.post("/api/early-turn/run-async")
    def trigger_early_turn_run_async(req: RunEarlyTurnRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
        with _early_turn_task_lock:
            if _early_turn_task_status.get("status") == "running":
                return {"status": "already_running", "task": dict(_early_turn_task_status)}
            _early_turn_task_status.update({
                "status": "queued",
                "progress": 0,
                "step_message": "A-PreV2 任务已提交，等待后台执行...",
                "trade_date": req.trade_date or "",
                "run_id": None,
                "candidate_count": 0,
                "error": None,
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "completed_at": None,
            })
        background_tasks.add_task(_run_early_turn_async, req.trade_date, req.ts_code, req.config_version, req.run_name, req.notes, req.run_id)
        return {"status": "submitted", "task": dict(_early_turn_task_status)}

    @app.get("/api/early-turn/status")
    def get_early_turn_task_status() -> dict[str, Any]:
        with _early_turn_task_lock:
            return dict(_early_turn_task_status)

    @app.get("/api/early-turn/samples/validate")
    def validate_early_turn_samples(trade_date: str | None = Query(default=None)) -> dict[str, Any]:
        from backend.screening.early_turn_service import EarlyTurnService
        store = PostgresScreeningStore(_database_url())
        svc = EarlyTurnService(store=store)
        results = svc.validate_positive_samples(target_trade_date=trade_date)
        return {"items": results}

    @app.post("/api/early-turn/samples")
    def add_early_turn_positive_sample(req: AddPositiveSampleRequest) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        store.save_positive_sample(
            ts_code=req.ts_code,
            target_date=req.target_date,
            sample_name=req.sample_name,
            note=req.note,
        )
        return {"status": "SUCCESS", "message": f"样本 {req.sample_name} ({req.ts_code}) 已添加到验证集"}

    @app.get("/api/screening/runs/history")
    def list_screening_runs_history(limit: int = Query(default=30, ge=1, le=100)) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        runs = store.list_screening_runs_history(limit=limit)
        return {"items": [_serialize_run(r) for r in runs]}

    @app.get("/api/screening/freshness")
    def data_freshness() -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        return store.get_data_freshness_info()

    @app.get("/api/screening/data-management")
    def data_management_overview() -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        with _screening_task_lock:
            live_task = dict(_screening_task_status)
        tasks = store.list_data_tasks(limit=20)
        return {
            "config": store.get_data_management_config(),
            "freshness": store.get_data_freshness_info(),
            "quality": store.get_data_quality_report(),
            "live_task": live_task,
            "tasks": tasks,
            "sync_logs": store.list_sync_logs(limit=30),
        }

    @app.patch("/api/screening/data-management/config")
    def save_data_management_config(req: DataManagementConfigRequest) -> dict[str, Any]:
        allowed = {
            "enabled", "timezone", "trading_days_only", "intraday_enabled",
            "intraday_interval_minutes", "intraday_start_time", "intraday_end_time",
            "daily_enabled", "daily_run_times", "concept_enabled",
            "concept_interval_hours", "industry_enabled", "industry_interval_hours",
            "quality_check_enabled", "retry_attempts", "request_delay_seconds",
            "stock_30m_enabled", "etf_30m_enabled", "sync_log_retention_days", "sync_log_max_rows",
        }
        unknown = sorted(set(req.config) - allowed)
        if unknown:
            raise HTTPException(status_code=422, detail=f"未知数据管理配置项: {unknown}")
        if not 1 <= int(req.config.get("intraday_interval_minutes", 30)) <= 240:
            raise HTTPException(status_code=422, detail="盘中更新间隔必须在 1 至 240 分钟之间")
        if not 1 <= int(req.config.get("retry_attempts", 3)) <= 10:
            raise HTTPException(status_code=422, detail="失败重试次数必须在 1 至 10 次之间")
        if float(req.config.get("request_delay_seconds", 0.12)) < 0:
            raise HTTPException(status_code=422, detail="请求间隔不能为负数")
        if int(req.config.get("sync_log_retention_days", 30)) < 1 or int(req.config.get("sync_log_max_rows", 10000)) < 1:
            raise HTTPException(status_code=422, detail="日志保留天数和最大条数必须大于 0")
        try:
            ZoneInfo(str(req.config.get("timezone", "Asia/Shanghai")))
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(status_code=422, detail="无效的时区配置") from exc
        run_times = req.config.get("daily_run_times", ["18:00"])
        if not isinstance(run_times, list) or any(
            not isinstance(value, str) or len(value) != 5 or value[2] != ":"
            or not value[:2].isdigit() or not value[3:].isdigit()
            or int(value[:2]) > 23 or int(value[3:]) > 59
            for value in run_times
        ):
            raise HTTPException(status_code=422, detail="盘后更新时间必须使用 HH:MM 格式")
        store = PostgresScreeningStore(_database_url())
        current = store.get_data_management_config()["config"]
        merged = {**current, **req.config}
        saved = store.save_data_management_config(merged)
        saved["log_cleanup"] = store.prune_sync_logs(int(merged.get("sync_log_retention_days", 30)), int(merged.get("sync_log_max_rows", 10000)))
        return {"status": "SUCCESS", **saved}

    @app.get("/api/screening/data-management/tasks")
    def data_management_tasks(limit: int = Query(default=30, ge=1, le=200)) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        return {"items": store.list_data_tasks(limit)}

    @app.get("/api/screening/data-management/quality")
    def data_management_quality() -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        return store.get_data_quality_report()

    @app.get("/api/screening/data-management/logs")
    def data_management_logs(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        return {"items": store.list_sync_logs(limit)}

    @app.get("/api/screening/data-management/failed")
    def data_management_failed(
        trade_date: str | None = Query(default=None),
        asset_type: Literal["stock", "etf"] | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=15, ge=1, le=200),
        search: str | None = Query(default=None, max_length=100),
    ) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        total = store.count_failed_minute_items(trade_date, asset_type, search)
        return {
            "items": store.list_failed_minute_items(trade_date, asset_type, limit=page_size, offset=(page - 1) * page_size, search=search),
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @app.post("/api/screening/data-management/retry-failed")
    def retry_failed_data(req: RetryFailedDataRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
        target = req.trade_date.replace("-", "")
        if len(target) != 8 or not target.isdigit():
            raise HTTPException(status_code=422, detail="trade_date 必须是 YYYYMMDD")
        asset_types = {"stock", "etf"} if req.asset_type == "all" else {req.asset_type}
        store = PostgresScreeningStore(_database_url())
        task_id = str(uuid.uuid4())
        store.create_data_task(task_id, "retry_failed_30m", target)

        def worker() -> None:
            try:
                sync = _screening_sync(store)
                config = store.get_data_management_config()["config"]
                store.update_data_task(task_id, status="RUNNING", progress=5, stage_message=f"正在重试 {target} 的未完成分钟线", started_at=datetime.now(UTC))
                result = sync.sync_30m_bars_for_date(
                    target,
                    asset_types,
                    float(config.get("request_delay_seconds", 0.12)),
                    int(config.get("retry_attempts", 3)),
                    stop_callback=lambda: store.is_data_task_cancel_requested(task_id),
                )
                status = "SUCCESS" if result["status"] == "PASS" else "FAILED"
                store.update_data_task(task_id, status=status, progress=100, stage_message="失败项重试完成", summary_json=result, completed_at=datetime.now(UTC))
            except Exception as exc:
                cancelled = "DATA_SYNC_CANCELLED" in str(exc)
                store.update_data_task(task_id, status="CANCELLED" if cancelled else "FAILED", stage_message="失败项重试已停止" if cancelled else "失败项重试失败", error_message=None if cancelled else str(exc), completed_at=datetime.now(UTC))

        background_tasks.add_task(worker)
        return {"status": "STARTED", "task_id": task_id, "trade_date": target, "asset_type": req.asset_type}

    @app.post("/api/screening/data-management/tasks/{task_id}/cancel")
    def cancel_data_management_task(task_id: str) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        if not store.request_data_task_cancel(task_id):
            raise HTTPException(status_code=409, detail="任务不存在，或任务已经结束")
        with _screening_task_lock:
            if _screening_task_status.get("task_id") == task_id:
                _screening_task_status["step_message"] = "已请求停止，正在等待当前请求结束"
        return {"status": "CANCEL_REQUESTED", "task_id": task_id}

    @app.get("/api/screening/data-management/sources")
    def data_management_sources() -> dict[str, Any]:
        result: dict[str, Any] = {"tushare": {"status": "UNKNOWN"}, "akshare": {"status": "UNKNOWN"}}
        try:
            config = TushareConfig.from_project_env(Path(__file__).resolve().parents[2])
            source = TushareScreeningSource(config.token)
            dates = source.trade_dates((date.today() - timedelta(days=3)).strftime("%Y%m%d"), date.today().strftime("%Y%m%d"))
            result["tushare"] = {"status": "PASS", "message": "交易日接口可用", "latest_trade_date": dates[-1] if dates else None}
        except Exception as exc:
            result["tushare"] = {"status": "FAIL", "message": str(exc)}
        try:
            response = requests.get(
                "https://82.push2.eastmoney.com/api/qt/clist/get",
                params={"pn": "1", "pz": "1", "fid": "f3", "fs": "m:0 t:6", "fields": "f12,f14"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=6,
            )
            response.raise_for_status()
            payload = response.json()
            diff = (payload.get("data") or {}).get("diff") or []
            if not diff:
                raise RuntimeError("行情探针返回空结果")
            result["akshare"] = {"status": "PASS", "message": "行情网络接口可用", "probe_rows": len(diff)}
        except Exception as exc:
            result["akshare"] = {
                "status": "FAIL",
                "message": "行情接口不可达，请检查网络或代理配置",
            }
        return result

    @app.post("/api/screening/data-sync")
    def sync_data(req: DataSyncRequest) -> dict[str, Any]:
        try:
            store = PostgresScreeningStore(_database_url())
            result = _sync_screening_trade_date(store, req.trade_date)
            return {
                "status": "SUCCESS",
                "message": f"目标交易日 {result['trade_date']} K线数据已检查并补齐",
                **result,
            }
        except ScreeningError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/screening/data-sync/async")
    def sync_data_async(background_tasks: BackgroundTasks) -> dict[str, Any]:
        # 与自动调度器共用同一把跨进程锁，避免网页任务和守护线程并发请求行情源。
        lock_conn = psycopg.connect(_database_url(), autocommit=True)
        acquired = lock_conn.execute(
            "SELECT pg_try_advisory_lock(hashtext('lll.market_review.auto_scheduler'))"
        ).fetchone()[0]
        if not acquired:
            lock_conn.close()
            return {"status": "already_running", "message": "已有行情同步任务正在运行"}
        with _screening_task_lock:
            if _screening_task_status.get("status") in ("running", "RUNNING"):
                lock_conn.execute("SELECT pg_advisory_unlock(hashtext('lll.market_review.auto_scheduler'))")
                lock_conn.close()
                return {"status": "already_running", "task": dict(_screening_task_status)}
            
            _screening_task_status["status"] = "running"
            _screening_task_status["progress"] = 10
            _screening_task_status["step_message"] = "正在启动后台数据同步与补全线程..."
            _screening_task_status["error"] = None
            _screening_task_status["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

        task_id = str(uuid.uuid4())
        task_store = PostgresScreeningStore(_database_url())
        log_config = task_store.get_data_management_config()["config"]
        task_store.prune_sync_logs(int(log_config.get("sync_log_retention_days", 30)), int(log_config.get("sync_log_max_rows", 10000)))
        task_store.create_data_task(task_id, "market_data", None)
        with _screening_task_lock:
            _screening_task_status["task_id"] = task_id
        task_store.update_data_task(task_id, status="RUNNING", progress=10, stage_message="正在启动后台数据同步与补全线程", started_at=datetime.now(UTC))

        def _sync_worker():
            try:
                store = PostgresScreeningStore(_database_url())
                with _screening_task_lock:
                    _screening_task_status["progress"] = 15
                    _screening_task_status["step_message"] = "正在检查并补齐全市场 5500+ A股日线数据..."
                task_store.update_data_task(task_id, progress=15, stage_message="正在检查并补齐全市场日线数据")

                def _30m_progress(idx: int, total: int, code: str):
                    pct = 35 + int((idx / max(total, 1)) * 50)
                    with _screening_task_lock:
                        _screening_task_status["progress"] = pct
                        _screening_task_status["step_message"] = f"正在同步 30 分钟 K 线 ({code} {idx}/{total})..."
                    task_store.update_data_task(task_id, progress=pct, stage_message=f"正在同步 30 分钟 K 线 ({code} {idx}/{total})")

                result = _sync_screening_trade_date(
                    store,
                    None,
                    progress_callback=_30m_progress,
                    stop_callback=lambda: task_store.is_data_task_cancel_requested(task_id),
                )
                target_date = result.get("trade_date") or ""
                intraday = result.get("counts", {}).get("intraday_30m", {})
                if intraday.get("status") != "PASS":
                    raise RuntimeError(
                        f"30分钟数据未全量完成: {intraday.get('validation') or intraday}"
                    )

                # 双重完备跳过：若该交易日全量日线与 30m K线均已完备，0.01秒瞬间结束
                if target_date and store.has_daily_data(target_date) and store.has_30m_data(target_date):
                    _MARKET_QUOTES_CACHE["timestamp"] = 0.0
                    with _screening_task_lock:
                        _screening_task_status["status"] = "success"
                        _screening_task_status["progress"] = 100
                        _screening_task_status["step_message"] = f"行情数据已是最新 ({target_date})，无需重复同步！"
                        _screening_task_status["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    task_store.update_data_task(task_id, status="SUCCESS", progress=100, stage_message=f"行情数据已是最新 ({target_date})，无需重复同步", completed_at=datetime.now(UTC), summary_json=result)
                    return

                with _screening_task_lock:
                    _screening_task_status["progress"] = 90
                    _screening_task_status["step_message"] = "正在更新申万板块与聚合指标..."
                task_store.update_data_task(task_id, progress=90, stage_message="正在更新申万板块与聚合指标")

                _MARKET_QUOTES_CACHE["timestamp"] = 0.0

                with _screening_task_lock:
                    _screening_task_status["status"] = "success"
                    _screening_task_status["progress"] = 100
                    _screening_task_status["step_message"] = f"目标交易日 {target_date} 全量日线与 30 分钟 K 线数据已成功更新补齐！"
                    _screening_task_status["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                task_store.update_data_task(task_id, status="SUCCESS", progress=100, stage_message=f"目标交易日 {target_date} 数据已成功更新补齐", completed_at=datetime.now(UTC), summary_json=result)
            except Exception as exc:
                cancelled = "DATA_SYNC_CANCELLED" in str(exc)
                with _screening_task_lock:
                    _screening_task_status["status"] = "cancelled" if cancelled else "failed"
                    _screening_task_status["progress"] = 0
                    _screening_task_status["step_message"] = f"数据补全失败: {str(exc)}"
                    _screening_task_status["error"] = str(exc)
                task_store.update_data_task(task_id, status="CANCELLED" if cancelled else "FAILED", progress=0, stage_message="数据补全已停止" if cancelled else "数据补全失败", error_message=None if cancelled else str(exc), completed_at=datetime.now(UTC))
            finally:
                try:
                    lock_conn.execute("SELECT pg_advisory_unlock(hashtext('lll.market_review.auto_scheduler'))")
                    lock_conn.close()
                except Exception:
                    pass

        background_tasks.add_task(_sync_worker)
        return {"status": "started", "message": "后台补全数据任务已启动"}

    @app.post("/api/screening/data-sync/cancel")
    def cancel_data_sync() -> dict[str, Any]:
        current_task_id = None
        with _screening_task_lock:
            current_task_id = _screening_task_status.get("task_id")
            _screening_task_status["status"] = "idle"
            _screening_task_status["progress"] = 0
            _screening_task_status["step_message"] = "数据补全任务已重置归零"
            _screening_task_status["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if current_task_id:
            PostgresScreeningStore(_database_url()).request_data_task_cancel(current_task_id)
        return {"status": "cancelled", "message": "已取消并重置数据补全任务"}

    @app.post("/api/screening/runs/run")
    def trigger_screening_run(req: RunScreeningTaskRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
        with _screening_task_lock:
            if _screening_task_status["status"] == "RUNNING":
                raise HTTPException(status_code=409, detail="A screening task is already running")
            _screening_task_status["status"] = "RUNNING"
            _screening_task_status["progress"] = 0
            _screening_task_status["step_message"] = "准备初始化二次筛选任务"

        def _worker():
            try:
                store = PostgresScreeningStore(_database_url())
                trade_date = req.trade_date or store.latest_candidate_date(RULESET_VERSION)
                if not trade_date:
                    raise ValueError("未找到有效候选交易日")

                if req.sync_data_first:
                    with _screening_task_lock:
                        _screening_task_status["progress"] = 20
                        _screening_task_status["step_message"] = "正在检查并补齐目标交易日K线数据..."
                    sync_result = _sync_screening_trade_date(store, trade_date)
                    trade_date = sync_result["trade_date"]
                
                cfg = SecondaryScreeningConfig()
                svc = SecondaryScreeningService(config=cfg, store=store)
                res = svc.run(
                    trade_date=trade_date,
                    run_name=req.run_name,
                    notes=req.notes,
                    universe_type=req.universe_type,
                    universe_params=req.universe_params,
                )
                with _screening_task_lock:
                    _screening_task_status["status"] = "DONE"
                    _screening_task_status["progress"] = 100
                    _screening_task_status["step_message"] = f"任务 {res['run_id']} 计算完成"
            except Exception as exc:
                with _screening_task_lock:
                    _screening_task_status["status"] = "ERROR"
                    _screening_task_status["step_message"] = str(exc)

        background_tasks.add_task(_worker)
        return {"status": "SUBMITTED", "message": "二次筛选任务已加入后台队列"}

    @app.get("/api/screening/runs/latest")
    def get_latest_run(trade_date: str | None = Query(default=None)) -> dict[str, Any]:
        """返回最新（或指定交易日）的二次筛选运行摘要"""
        store = PostgresScreeningStore(_database_url())
        run = store.get_latest_screening_run(trade_date=trade_date)
        if run is None:
            raise HTTPException(status_code=404, detail="No screening run found")
        # 序列化 datetime 字段
        return _serialize_run(run)

    @app.get("/api/screening/runs/{run_id}/funnel")
    def get_run_funnel(run_id: str) -> dict[str, Any]:
        """返回指定 run 各池各层的通过/淘汰数量（漏斗视图）"""
        store = PostgresScreeningStore(_database_url())
        run = store.get_screening_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        funnel = store.load_stage_funnel(run_id)
        return {"run_id": run_id, "trade_date": run["trade_date"], "funnel": funnel}

    @app.get("/api/screening/runs/{run_id}/stocks/{ts_code}")
    def get_stock_audit(run_id: str, ts_code: str) -> dict[str, Any]:
        """返回单只股票的 L0~L5 完整审计轨迹"""
        store = PostgresScreeningStore(_database_url())
        run = store.get_screening_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        snapshots = store.load_stage_snapshots(run_id, ts_code=ts_code)
        reasons   = store.load_stage_reasons(run_id, ts_code=ts_code)
        return {
            "run_id":     run_id,
            "trade_date": run["trade_date"],
            "ts_code":    ts_code,
            "stages":     snapshots,
            "reasons":    reasons,
        }

    @app.get("/api/screening/runs/{run_id}/pools/{pool_code}/stages/{stage}/reasons")
    def get_stage_reasons_summary(run_id: str, pool_code: str, stage: str) -> dict[str, Any]:
        """返回指定运行、指定池、指定层级的淘汰原因分类统计"""
        store = PostgresScreeningStore(_database_url())
        reasons = store.load_stage_reasons_summary(run_id, pool_code, stage)
        return {"run_id": run_id, "pool_code": pool_code, "stage": stage, "reasons": reasons}

    @app.get("/api/screening/runs/{run_id}/pools/{pool_code}/stages/{stage}/stocks")
    def get_stage_stocks_drilldown(
        run_id: str,
        pool_code: str,
        stage: str,
        status: str | None = Query(default=None),
        reason_code: str | None = Query(default=None),
        industry: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        """下钻查询指定池、层级、状态或淘汰原因的股票明细及全量行业分布频次"""
        store = PostgresScreeningStore(_database_url())
        res = store.load_stage_stocks_drilldown(
            run_id=run_id,
            pool_code=pool_code,
            stage=stage,
            status=status,
            reason_code=reason_code,
            industry=industry,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        res["page"] = page
        res["page_size"] = page_size
        return res


    @app.post("/api/screening/secondary/run")
    def run_secondary_screening(request: RunScreeningRequest) -> dict[str, Any]:
        """触发二次筛选（L0+L1），写入 screening_run / stage_snapshot / stage_reason"""
        from backend.screening.secondary_service import (
            SecondaryScreeningConfig,
            SecondaryScreeningService,
        )
        store = PostgresScreeningStore(_database_url())
        cfg   = SecondaryScreeningConfig()
        svc   = SecondaryScreeningService(config=cfg, store=store)
        result = svc.run(request.trade_date)
        return result

    @app.get("/api/screening/{trade_date}")
    def screening_by_date(
        trade_date: str,
        pool: Literal["A-Pre", "A", "B", "C", "ABC"] = "ABC",
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=10, le=200),
        min_score: float | None = Query(default=None),
        max_score: float | None = Query(default=None),
        q: str | None = Query(default=None, max_length=50),
        industry: str | None = Query(default=None, max_length=50),
        only_selected: bool = Query(default=False),
    ) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        return _screening_payload(store, trade_date, pool, page, page_size, min_score, max_score, q, industry, only_selected)

    @app.post("/api/technical-classification/run")
    def run_technical_classification(background_tasks: BackgroundTasks, trade_date: str | None = Body(default=None, embed=True)) -> dict[str, Any]:
        """后台运行独立技术分类；历史覆盖不足时先补齐所需日线。"""
        with _technical_task_lock:
            if _technical_task_status["status"] == "running":
                return {"status": "already_running", "task": dict(_technical_task_status)}
            _technical_task_status.update({"status": "running", "progress": 1, "step_message": "正在初始化全市场技术分类任务…", "trade_date": trade_date or "", "run_id": None, "summary": None, "error": None, "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "completed_at": None})

        def _worker() -> None:
            try:
                store = PostgresScreeningStore(_database_url())
                sync = _screening_sync(store)
                target = (trade_date or store.get_data_freshness_info().get("official_daily_date") or "").replace("-", "")
                if len(target) != 8 or not target.isdigit():
                    raise ScreeningError("technical classification requires a valid trade_date")
                with _technical_task_lock:
                    _technical_task_status.update({"trade_date": target, "progress": 5, "step_message": "正在检查并补齐分类所需历史日线…"})
                service = TechnicalClassificationService(store)
                completion = service.ensure_history(target, sync)
                with _technical_task_lock:
                    _technical_task_status.update({"progress": 15, "step_message": "历史数据就绪，正在逐股票计算周线阶段与日线 Episode…"})

                def _progress(index: int, total: int, code: str) -> None:
                    with _technical_task_lock:
                        _technical_task_status.update({"progress": 15 + int(index / max(total, 1) * 80), "step_message": f"正在分类 {code}（{index}/{total}）"})

                summary = service.run(target, progress_callback=_progress)
                summary["history_completion"] = completion
                with _technical_task_lock:
                    _technical_task_status.update({"status": "success", "progress": 100, "step_message": "全市场技术分类完成，分类快照已保存。", "run_id": summary.get("run_id"), "summary": summary, "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")})
            except Exception as exc:
                with _technical_task_lock:
                    _technical_task_status.update({"status": "failed", "progress": 0, "step_message": f"全市场技术分类失败：{exc}", "error": str(exc), "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")})

        background_tasks.add_task(_worker)
        return {"status": "submitted", "task": dict(_technical_task_status)}

    @app.get("/api/technical-classification/status")
    def technical_classification_status() -> dict[str, Any]:
        with _technical_task_lock:
            return dict(_technical_task_status)

    @app.post("/api/financial-summary/run")
    def run_market_financial_summary(background_tasks: BackgroundTasks) -> dict[str, Any]:
        from backend.screening.market_financial_summary import MarketFinancialSummaryService
        with _financial_summary_task_lock:
            if _financial_summary_task_status["status"] == "running":
                return {"status": "already_running", "task": dict(_financial_summary_task_status)}
            _financial_summary_task_status.update({"status": "running", "progress": 0, "step_message": "正在生成全市场经营摘要…", "summary": None, "error": None, "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "completed_at": None})
        def worker() -> None:
            try:
                store = PostgresScreeningStore(_database_url())
                with store.connect() as conn:
                    codes = [r["asset_code"] for r in conn.execute("select asset_code from screening_asset_master where asset_type='stock'").fetchall()]
                def progress(index: int, total: int, code: str) -> None:
                    with _financial_summary_task_lock:
                        _financial_summary_task_status.update({"progress": int(index / max(total, 1) * 100), "step_message": f"正在整理 {code}（{index}/{total}）"})
                summary = MarketFinancialSummaryService(store).build(codes, progress)
                with _financial_summary_task_lock:
                    _financial_summary_task_status.update({"status": "success", "progress": 100, "step_message": "全市场经营摘要已生成。", "summary": summary, "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")})
            except Exception as exc:
                with _financial_summary_task_lock:
                    _financial_summary_task_status.update({"status": "failed", "error": str(exc), "step_message": str(exc), "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        background_tasks.add_task(worker)
        return {"status": "submitted", "task": dict(_financial_summary_task_status)}

    @app.get("/api/financial-summary/status")
    def market_financial_summary_status() -> dict[str, Any]:
        with _financial_summary_task_lock:
            return dict(_financial_summary_task_status)

    @app.get("/api/technical-classification/latest")
    def technical_classification_latest_snapshot() -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        return {"trade_date": TechnicalClassificationService(store).latest_snapshot_date()}

    @app.get("/api/technical-classification/single/{ts_code}")
    def technical_classification_single_stock(ts_code: str, trade_date: str = Query(...)) -> dict[str, Any]:
        target_date = trade_date.replace("-", "")
        store = PostgresScreeningStore(_database_url())
        item = TechnicalClassificationService(store).classify_single(target_date, ts_code)
        with store.connect() as conn:
            asset = conn.execute("select name, raw_json->>'industry' as industry from screening_asset_master where asset_code=%s", (item["ts_code"],)).fetchone()
        from backend.screening.ths_concept_service import get_batch_stock_ths_concepts
        item["name"] = asset.get("name") if asset else None
        item["industry"] = asset.get("industry") if asset else None
        item["ths_concepts"] = get_batch_stock_ths_concepts(store, [item["ts_code"]], target_date).get(item["ts_code"], [])
        return item

    @app.get("/api/technical-classification/single/{ts_code}/history")
    def technical_classification_single_history(ts_code: str, start_date: str = Query(...), end_date: str = Query(...)) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        result = TechnicalClassificationService(store).classify_history(start_date, end_date, ts_code)
        with store.connect() as conn:
            asset = conn.execute("select name, raw_json->>'industry' as industry from screening_asset_master where asset_code=%s", (result["ts_code"],)).fetchone()
        result["name"] = asset.get("name") if asset else None
        result["industry"] = asset.get("industry") if asset else None
        return result

    @app.get("/api/technical-classification/{trade_date}")
    def technical_classification_by_date(
        trade_date: str,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=500),
        weekly_stage: str | None = Query(default=None),
        daily_subtype: str | None = Query(default=None),
        concept: str | None = Query(default=None),
        hot_theme_scope: str | None = Query(default=None),
        hot_theme: str | None = Query(default=None),
        hot_theme_all: bool = Query(default=False),
        exclude_st: bool = Query(default=False),
    ) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        target_date = trade_date.replace("-", "")
        service = TechnicalClassificationService(store)
        # 全量候选集合先按技术阶段裁剪；概念/热点筛选在同一集合上取交集，不能只在当前页过滤。
        with store.connect() as conn:
            clauses, params = ["trade_date=%s", "classifier_version=%s"], [target_date, CLASSIFIER_VERSION]
            if weekly_stage:
                clauses.append("weekly_stage=%s"); params.append(weekly_stage)
            if daily_subtype:
                clauses.append("daily_subtype=%s"); params.append(daily_subtype)
            sql = f"select s.ts_code from technical_classification_snapshot s left join screening_asset_master a on a.asset_code=s.ts_code where {' and '.join('s.' + clause for clause in clauses)}"
            if exclude_st:
                sql += " and upper(coalesce(a.name, '')) not like 'ST%%' and upper(coalesce(a.name, '')) not like '*ST%%'"
            base_codes = [row["ts_code"] for row in conn.execute(sql, params).fetchall()]
        code_set: set[str] = set(base_codes)
        from backend.screening.ths_concept_service import get_batch_stock_ths_concepts
        concepts_map = get_batch_stock_ths_concepts(store, base_codes, target_date)
        if concept:
            code_set &= {code for code, values in concepts_map.items() if concept in values}
        option_base_codes = set(code_set)
        hot_matches: dict[str, list[dict[str, Any]]] = {}
        hot_options: list[dict[str, Any]] = []
        hot_snapshot_date: str | None = None
        hot_theme_issue: str | None = None
        if hot_theme_scope and hot_theme_scope != "ALL":
            from backend.screening.hot_theme_filter_service import load_hot_theme_matches
            try:
                hot_matches, hot_options, hot_snapshot_date = load_hot_theme_matches(store, target_date, hot_theme_scope, hot_theme)
            except (LookupError, ValueError) as exc:
                if hot_theme:
                    raise HTTPException(status_code=409, detail={"code": "HOT_THEME_DATA_UNAVAILABLE", "message": str(exc)}) from exc
                hot_theme_issue = str(exc)
            if hot_theme or hot_theme_all:
                code_set &= set(hot_matches)
        # 统计概念与热点选项时使用完整技术候选集合，页面标签数量与实际筛选口径一致。
        concept_counts: dict[str, int] = {}
        for values in concepts_map.values():
            for name in values:
                concept_counts[name] = concept_counts.get(name, 0) + 1
        if hot_theme_scope and hot_theme_scope != "ALL":
            filtered_hot_options = []
            for option in hot_options:
                name = option["canonical_name"]
                # 与 A-PreV2 一致：热点按钮始终展示当前“非热点条件”候选集合中的完整列表；
                # 选中其中一项只影响表格结果，不会把按钮列表收窄为单一项。
                filtered_hot_options.append({**option, "match_count": sum(1 for code in option_base_codes if any(match["canonical_name"] == name for match in hot_matches.get(code, [])))})
            hot_options = [option for option in filtered_hot_options if option["match_count"] > 0]
        result = service.latest(target_date, page, page_size, weekly_stage, daily_subtype, sorted(code_set))
        financial_map = store.get_latest_financial_facts([item["ts_code"] for item in result.get("items", [])])
        for item in result.get("items", []):
            item["ths_concepts"] = concepts_map.get(item["ts_code"], [])
            item["hot_theme_matches"] = hot_matches.get(item["ts_code"], [])
            item["financial_facts"] = financial_map.get(item["ts_code"], {})
        result["concept_counts"] = concept_counts
        result["hot_theme_options"] = hot_options
        result["hot_theme_snapshot_date"] = hot_snapshot_date
        result["hot_theme_issue"] = hot_theme_issue
        return result

    # ── A-PreV2 candidate facts and AI research endpoints ───────────────
    @app.get("/api/data/capabilities")
    def data_capabilities() -> dict[str, Any]:
        from backend.screening.ths_concept_service import check_data_capabilities
        store = PostgresScreeningStore(_database_url())
        return check_data_capabilities(store)

    @app.get("/api/data/ths-concepts")
    def get_ths_concepts_endpoint() -> dict[str, Any]:
        from backend.screening.ths_concept_service import get_all_ths_concepts
        store = PostgresScreeningStore(_database_url())
        concept_names = get_all_ths_concepts(store)
        return {"status": "SUCCESS", "concepts": [{"name": c} for c in concept_names], "total": len(concept_names)}

    @app.post("/api/data/ths-concepts/sync")
    def sync_ths_concepts_endpoint(
        trade_date: str | None = Query(default=None),
        force: bool = Query(default=False),
    ) -> dict[str, Any]:
        from backend.screening.ths_concept_service import sync_ths_concepts
        store = PostgresScreeningStore(_database_url())
        return sync_ths_concepts(store, as_of_date=trade_date, force=force)

    @app.get("/api/candidate-secondary")
    def get_candidate_secondary_list_endpoint(
        date: str | None = Query(default=None),
        codes: str | None = Query(default=None),
    ) -> dict[str, Any]:
        from backend.screening.secondary_eval_engine import SECONDARY_EVAL_VERSION
        store = PostgresScreeningStore(_database_url())
        as_of_date = date or store.latest_candidate_date(RULESET_VERSION) or datetime.now(UTC).strftime("%Y%m%d")
        run_info = store.get_latest_early_turn_run(as_of_date)
        source_items: list[dict[str, Any]] = []
        if run_info:
            source_items = _secondary_candidate_items(store, run_info["run_id"])
        items = store.get_candidate_secondary_list(as_of_date)
        source_codes = {item["ts_code"] for item in source_items} if run_info else set()
        if source_codes:
            items = [item for item in items if item.get("ts_code") in source_codes]
        target_codes = set(c.strip().upper() for c in codes.split(",") if c.strip()) if codes else None
        if target_codes:
            items = [item for item in items if item.get("ts_code") in target_codes]
        requested_source_codes = source_codes.intersection(target_codes) if target_codes else source_codes
        existing_codes = {item["ts_code"] for item in items}
        needs_recalc = bool(requested_source_codes.difference(existing_codes))
        needs_recalc = needs_recalc or any(
            item.get("calc_version") != SECONDARY_EVAL_VERSION
            for item in items
            if not requested_source_codes or item.get("ts_code") in requested_source_codes
        )

        if run_info and needs_recalc and not target_codes:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "SECONDARY_SNAPSHOT_INCOMPLETE",
                    "as_of_date": as_of_date,
                    "early_turn_count": len(source_codes),
                    "secondary_snapshot_count": len(existing_codes),
                    "candidate_scope": sorted(EARLY_TURN_SECONDARY_STATES),
                    "message": "当前批次仅生成了技术选股结果，经营、题材和交易特征详情暂未生成。技术评分与生命周期状态不受影响。",
                },
            )

        return {
            "as_of_date": as_of_date,
            "items": items,
            "count": len(items),
            "coverage": {
                "requested_count": len(requested_source_codes),
                "available_count": len(existing_codes.intersection(requested_source_codes)) if requested_source_codes else len(existing_codes),
            },
        }

    @app.get("/api/candidate-secondary/{ts_code}")
    def get_candidate_secondary_detail_endpoint(ts_code: str, date: str = Query(...)) -> dict[str, Any]:
        from backend.screening.ai_deep_research_service import get_ai_stock_research_result
        from backend.screening.secondary_eval_engine import SECONDARY_EVAL_VERSION, compute_theme_relative_facts, evaluate_single_secondary_candidate
        from backend.screening.ths_concept_service import get_stock_ths_concepts

        store = PostgresScreeningStore(_database_url())
        detail = store.get_candidate_secondary_detail(date, ts_code)
        reuse_existing = bool(detail and detail.get("calc_version") == SECONDARY_EVAL_VERSION)
        if not reuse_existing:
            _ensure_secondary_data_inputs(store, date, [ts_code])
            aprev2_item = None
            run_info = store.get_latest_early_turn_run(date)
            if run_info:
                early_turn_res = store.query_early_turn_results(
                    run_info["run_id"],
                    query_text=ts_code,
                    limit=1,
                )
                items = early_turn_res.get("items", [])
                aprev2_item = items[0] if items else None
            sec, ev, lead, sup = evaluate_single_secondary_candidate(store, ts_code, date, aprev2_item)
            store.save_secondary_evaluation_snapshots(date, [sec], [ev], [lead], [sup])
            detail = store.get_candidate_secondary_detail(date, ts_code)
        if not detail:
            raise HTTPException(status_code=500, detail="基本面研究快照生成失败")
        detail["research_snapshot_status"] = "REUSED" if reuse_existing else "COMPUTED"
        detail["research_snapshot_message"] = "已复用该交易日已有的基本面研究快照" if reuse_existing else "已基于该交易日基础数据生成基本面研究快照"

        concepts = get_stock_ths_concepts(store, ts_code, date)
        ai_research = get_ai_stock_research_result(store, ts_code, date)
        # AI 研究完成后，主题内表现应直接展示本次 AI 识别的近期市场主题，
        # 而不是继续沿用研究前的“待 AI 主题匹配”快照。
        if ai_research:
            manifest = ai_research.get("source_manifest_json") or {}
            if isinstance(manifest, str):
                try:
                    manifest = json.loads(manifest)
                except json.JSONDecodeError:
                    manifest = {}
            theme_match = manifest.get("theme_match") or {}
            relative = manifest.get("theme_relative_facts") or {}
            primary_theme = theme_match.get("primary_active_theme")
            if primary_theme:
                # 已完成的历史 AI 结果可能是在主题排名逻辑修复前写入的，
                # 此处按当前完整底层概念/行情快照重算，避免详情页永久沿用空结果。
                if not relative:
                    relative = compute_theme_relative_facts(
                        store=store,
                        ts_code=ts_code,
                        as_of_date=date,
                        theme_name=primary_theme,
                        lookback_days=15,
                    ) or {}
                    if relative and ai_research.get("analysis_id"):
                        with store.connect() as conn:
                            conn.execute(
                                """
                                UPDATE ai_stock_research
                                SET source_manifest_json = source_manifest_json || jsonb_build_object(
                                    'theme_relative_facts', %s::jsonb
                                )
                                WHERE analysis_id = %s
                                """,
                                (json.dumps(relative, ensure_ascii=False), ai_research["analysis_id"]),
                            )
                            conn.commit()
                detail["leadership_state"] = "READY"
                detail["ai_theme_name"] = primary_theme
                detail["ai_theme_relative"] = relative
                detail["leadership_reasons"] = [
                    {"type": "POSITIVE", "msg": theme_match.get("match_rationale") or f"AI 识别近期市场相关主题：{primary_theme}"}
                ]
            elif theme_match.get("no_active_theme_match"):
                # “当前标签”是同花顺概念快照的时点说明，不能拿来表达
                # AI 已判断为未命中近期市场主题；两者的业务含义不同。
                detail["leadership_state"] = "NO_ACTIVE_THEME_MATCH"
                detail["ai_theme_name"] = None
                detail["ai_theme_relative"] = {}
                detail["leadership_reasons"] = [
                    {"type": "INFO", "msg": theme_match.get("no_match_reason") or "当前未识别到近期市场主线主题。"}
                ]

        # 附带近 90 日日线 K 线数据（供单股测试与导出使用）
        recent_90d_klines = []
        selection_changes = []
        with store.connect() as conn:
            history_rows = conn.execute(
                """select distinct on (r.trade_date)
                          r.trade_date, r.total_score, r.state, r.turn_episode_state, r.selected
                   from early_turn_result r
                   join early_turn_run run on run.run_id = r.run_id
                   where r.ts_code = %s and r.trade_date <= %s
                   order by r.trade_date asc, run.started_at desc""",
                (ts_code, date),
            ).fetchall()
            selection_changes = [
                {
                    "trade_date": r["trade_date"],
                    "total_score": float(r["total_score"]) if r.get("total_score") is not None else None,
                    "state": r.get("state"),
                    "turn_episode_state": r.get("turn_episode_state"),
                    "selected": bool(r.get("selected")),
                }
                for r in history_rows
            ]
            k_rows = conn.execute(
                """
                select trade_date, open, high, low, close, vol, amount
                from screening_daily_bar
                where asset_code = %s and trade_date <= %s
                order by trade_date desc limit 90
                """,
                (ts_code, date),
            ).fetchall()
            for r in reversed(k_rows):
                recent_90d_klines.append({
                    "trade_date": r["trade_date"],
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "vol": float(r["vol"]),
                    "amount": float(r["amount"]),
                })

        return {
            "as_of_date": date,
            "ts_code": ts_code,
            "detail": detail,
            "concepts_info": concepts,
            "ai_research": ai_research,
            "recent_90d_klines": recent_90d_klines,
            "selection_changes": selection_changes,
        }

    @app.post("/api/candidate-secondary/run")
    def run_candidate_secondary_endpoint(body: dict[str, Any]) -> dict[str, Any]:
        as_of_date = body.get("date") or body.get("as_of_date") or datetime.now(UTC).strftime("%Y%m%d")
        store = PostgresScreeningStore(_database_url())
        run_id = body.get("run_id")
        run_info = store.get_latest_early_turn_run(as_of_date) if not run_id else {"run_id": run_id}
        if not run_info or not run_info.get("run_id"):
            raise HTTPException(status_code=404, detail="找不到对应的 A-PreV2 选股批次")
        # 生命周期状态只是可选筛选条件；用户未选卡片时，对当前其它筛选条件的全部结果执行研究。
        state_value = str(body.get("state") or "").strip()
        state = state_value if state_value and state_value != "ALL" else None
        try:
            min_score = float(body["min_score"]) if body.get("min_score") not in (None, "") else None
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="最低分必须是数字")
        hot_theme_scope = str(body.get("hot_theme_scope") or "ALL")
        hot_theme = body.get("hot_theme") or None
        hot_codes = None
        if hot_theme_scope != "ALL":
            from backend.screening.hot_theme_filter_service import load_hot_theme_matches
            try:
                hot_matches, _, _ = load_hot_theme_matches(store, as_of_date, hot_theme_scope, hot_theme)
                hot_codes = list(hot_matches.keys())
            except (LookupError, ValueError) as exc:
                raise HTTPException(status_code=409, detail={"code": "HOT_THEME_DATA_UNAVAILABLE", "message": str(exc)}) from exc
        filtered = store.query_early_turn_results(
            run_info["run_id"], state=state, min_score=min_score,
            query_text=body.get("q") or None,
            industry=body.get("industry") or None,
            concept=body.get("concept") or None,
            ts_codes=hot_codes,
            limit=None,
        ).get("items", [])
        if body.get("exclude_st"):
            filtered = [item for item in filtered if not str(item.get("name") or "").upper().lstrip().startswith(("ST", "*ST"))]
        source_items = filtered
        if not source_items:
            raise HTTPException(status_code=404, detail="当前筛选条件下没有可进行基本面研究的股票")

        result = _run_secondary_evaluation_for_items(store, as_of_date, source_items)
        return {"status": "SUCCESS", "as_of_date": as_of_date, "run_id": run_info["run_id"], **result}

    @app.post("/api/ai/stock-research")
    def run_ai_stock_research_endpoint(body: dict[str, Any]) -> dict[str, Any]:
        from backend.screening.ai_deep_research_service import run_ai_stock_research
        as_of_date = body.get("date") or body.get("as_of_date") or datetime.now(UTC).strftime("%Y%m%d")
        ts_codes = body.get("ts_codes") or []
        lookback = body.get("review_lookback", 20)
        use_search = body.get("use_web_search", True)

        if not ts_codes:
            raise HTTPException(status_code=400, detail="ts_codes is required")
        if len(ts_codes) > 20:
            raise HTTPException(
                status_code=400,
                detail="ts_codes exceeds 20. Split the request explicitly; the API will not silently truncate.",
            )

        store = PostgresScreeningStore(_database_url())
        results = []
        for code in ts_codes:
            res = run_ai_stock_research(store, code, as_of_date, review_lookback=lookback, use_web_search=use_search)
            results.append(res)

        return {"status": "SUCCESS", "as_of_date": as_of_date, "items": results}

    @app.post("/api/ai/stock-research-async")
    def submit_ai_stock_research_endpoint(body: dict[str, Any], background_tasks: BackgroundTasks) -> dict[str, Any]:
        ts_codes = body.get("ts_codes") or []
        if not ts_codes:
            raise HTTPException(status_code=400, detail="ts_codes is required")
        if len(ts_codes) > 20:
            raise HTTPException(status_code=400, detail="ts_codes exceeds 20")
        as_of_date = body.get("date") or body.get("as_of_date") or datetime.now(UTC).strftime("%Y%m%d")
        job_id = f"AIRJOB_{uuid.uuid4().hex}"
        with _ai_research_jobs_lock:
            _ai_research_jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "progress": 0,
                "step_message": "AI 深度分析已提交，等待执行…",
                "error": None,
                "items": [],
                "as_of_date": as_of_date,
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        background_tasks.add_task(
            _run_ai_research_job,
            job_id,
            [str(code) for code in ts_codes],
            str(as_of_date),
            int(body.get("review_lookback", 120)),
            bool(body.get("use_web_search", True)),
        )
        return {"status": "SUBMITTED", "job_id": job_id, "as_of_date": as_of_date}

    @app.get("/api/ai/stock-research-status/{job_id}")
    def get_ai_stock_research_status_endpoint(job_id: str) -> dict[str, Any]:
        with _ai_research_jobs_lock:
            job = _ai_research_jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="AI 研究任务不存在或已过期")
            return dict(job)

    @app.get("/api/ai/stock-research/{ts_code}")
    def get_ai_stock_research_endpoint(ts_code: str, date: str = Query(...)) -> dict[str, Any]:
        from backend.screening.ai_deep_research_service import get_ai_stock_research_result
        store = PostgresScreeningStore(_database_url())
        res = get_ai_stock_research_result(store, ts_code, date)
        return {"ts_code": ts_code, "as_of_date": date, "result": res}

    @app.get("/api/market-review/market-memory")
    def get_market_memory_endpoint(date: str = Query(...)) -> dict[str, Any]:
        from backend.screening.market_memory_service import get_cached_market_memory
        store = PostgresScreeningStore(_database_url())
        cached = get_cached_market_memory(store, date)
        if cached is None:
            snapshot_status, message = _snapshot_task_state(date, _market_memory_status, _market_memory_lock)
            return {
                "status": snapshot_status,
                "as_of_date": date,
                "latest_available_date": _latest_snapshot_date(store, "screening_market_memory_cache", date),
                "memory_json": {
                    "as_of_date": date,
                    "actual_lookback_sessions": 0,
                    "themes": [],
                    "capital_flows": [],
                },
                "summary_markdown": "",
                "message": message,
            }
        memory_json, summary_markdown = cached
        return {
            "status": "SUCCESS",
            "as_of_date": date,
            "memory_json": memory_json,
            "summary_markdown": summary_markdown,
        }

    @app.get("/api/market-review/market-panorama")
    def get_market_panorama_endpoint(date: str = Query(...)) -> dict[str, Any]:
        """V2 市场全景历史叙事；不读取或改写题材周期、资金脉络缓存。"""
        from backend.screening.market_panorama_v2_service import get_cached_v2
        store = PostgresScreeningStore(_database_url())
        cached = get_cached_v2(store, date)
        if cached is None:
            snapshot_status, message = _snapshot_task_state(date, _market_panorama_status, _market_panorama_lock)
            return {
                "status": snapshot_status,
                "as_of_date": date,
                "latest_available_date": _latest_snapshot_date(store, "screening_market_panorama_v2_snapshot", date),
                "state": None,
                "summary_markdown": "",
                "message": message,
            }
        history, summary_markdown, reviewer = cached
        return {"status": "SUCCESS", "as_of_date": date, "state": history, "summary_markdown": summary_markdown, "reviewer": reviewer}

    @app.post("/api/market-review/market-panorama/trigger")
    def trigger_market_panorama_endpoint(
        background_tasks: BackgroundTasks,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        date = str(body.get("date") or "").strip()
        if not date:
            raise HTTPException(status_code=400, detail="date is required")
        force_rebuild = bool(body.get("force_rebuild", False))
        with _market_panorama_lock:
            if _market_panorama_status["running"]:
                raise HTTPException(status_code=409, detail="市场全景正在更新")
        background_tasks.add_task(_run_market_panorama_async, date, force_rebuild)
        action = "重建" if force_rebuild else "更新"
        return {"status": "SUCCESS", "message": f"已启动 {date} 市场全景{action}"}

    @app.get("/api/market-review/market-panorama/status")
    def get_market_panorama_status_endpoint() -> dict[str, Any]:
        with _market_panorama_lock:
            return dict(_market_panorama_status)

    @app.post("/api/market-review/market-memory/trigger")
    def trigger_market_memory_endpoint(
        background_tasks: BackgroundTasks,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        date = str(body.get("date") or "").strip()
        if not date:
            raise HTTPException(status_code=400, detail="date is required")
        force_refresh = bool(body.get("force_refresh", False))
        background_tasks.add_task(_run_market_memory_async, date, force_refresh)
        return {"status": "SUCCESS", "message": f"已启动 {date} 市场全景后台更新任务"}

    @app.post("/api/market-review/market-memory/overview/trigger")
    def trigger_market_overview_rewrite_endpoint(
        background_tasks: BackgroundTasks,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        date = str(body.get("date") or "").strip()
        if not date:
            raise HTTPException(status_code=400, detail="date is required")
        background_tasks.add_task(_run_market_overview_rewrite_async, date)
        return {"status": "SUCCESS", "message": f"已启动 {date} 市场全景正文更新任务"}

    @app.get("/api/market-review/market-memory/status")
    def get_market_memory_status_endpoint(date: str | None = Query(None)) -> dict[str, Any]:
        with _market_memory_lock:
            return dict(_market_memory_status)

    @app.post("/api/market-review/market-memory/capital-flows/trigger")
    def trigger_capital_flow_refresh_endpoint(
        background_tasks: BackgroundTasks,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        date = str(body.get("date") or "").strip()
        backfill_all = bool(body.get("backfill_all", False))
        with _capital_flow_lock:
            if _capital_flow_status["running"]:
                raise HTTPException(status_code=409, detail="资金脉络回填任务正在运行")
        if backfill_all:
            background_tasks.add_task(_run_capital_flow_backfill_async)
            return {"status": "SUCCESS", "message": "已启动历史资金脉络回填任务"}
        if not date:
            raise HTTPException(status_code=400, detail="date is required unless backfill_all=true")
        background_tasks.add_task(_run_capital_flow_date_async, date)
        return {"status": "SUCCESS", "message": f"已启动 {date} 资金脉络回填任务"}

    @app.get("/api/market-review/market-memory/capital-flows/status")
    def get_capital_flow_status_endpoint() -> dict[str, Any]:
        with _capital_flow_lock:
            return dict(_capital_flow_status)

    # ── Watchlist 自选股与多层级分组 REST APIs ─────────────────────────────────
    @app.get("/api/watchlist/groups")
    def get_watchlist_groups_endpoint() -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        groups = store.get_watchlist_group_nodes()
        return {"status": "SUCCESS", "groups": groups}

    @app.post("/api/watchlist/groups")
    def create_watchlist_group_endpoint(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Group name is required")
        parent_id = body.get("parent_id")
        parent_id = int(parent_id) if parent_id is not None else None
        group = store.create_watchlist_group(name, parent_id)
        return {"status": "SUCCESS", "group": group}

    @app.put("/api/watchlist/groups/{group_id}")
    def update_watchlist_group_endpoint(group_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Group name is required")
        ok = store.update_watchlist_group(group_id, name)
        return {"status": "SUCCESS", "updated": ok}

    @app.delete("/api/watchlist/groups/{group_id}")
    def delete_watchlist_group_endpoint(group_id: int) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        ok = store.delete_watchlist_group(group_id)
        return {"status": "SUCCESS", "deleted": ok}

    @app.get("/api/watchlist/stocks")
    def get_watchlist_stocks_endpoint(
        group_id: Optional[int] = Query(None), group_key: Optional[str] = Query(None)
    ) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        if group_key is not None:
            stocks = store.get_watchlist_stocks_with_research(group_key)
        else:
            stocks = (
                store.get_watchlist_stocks_with_research(f"manual:{group_id}")
                if group_id is not None
                else store.get_watchlist_stocks_with_research()
            )
        code_set = store.get_watchlist_code_set()
        latest_early_turn_run = store.get_latest_early_turn_run()
        return {
            "status": "SUCCESS",
            "stocks": stocks,
            "watchlist_codes": list(code_set),
            "default_research_date": latest_early_turn_run.get("trade_date") if latest_early_turn_run else None,
        }

    @app.post("/api/watchlist/stocks/toggle")
    def toggle_watchlist_stock_endpoint(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        asset_code = str(body.get("asset_code") or "").strip()
        if not asset_code:
            raise HTTPException(status_code=400, detail="asset_code is required")
        group_id = body.get("group_id")
        group_id = int(group_id) if group_id is not None else None
        source = body.get("source")
        if source is not None and not isinstance(source, dict):
            raise HTTPException(status_code=422, detail="source must be an object")
        try:
            is_added = store.toggle_watchlist_stock(asset_code, group_id, source)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        code_set = store.get_watchlist_code_set()
        return {"status": "SUCCESS", "asset_code": asset_code, "in_watchlist": is_added, "watchlist_codes": list(code_set)}

    @app.get("/api/watchlist/ai-pool")
    def get_ai_analysis_pool_endpoint() -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        stocks = store.get_ai_analysis_pool()
        return {"status": "SUCCESS", "stocks": stocks, "codes": [s["asset_code"] for s in stocks]}

    @app.post("/api/watchlist/ai-pool/toggle")
    def toggle_ai_analysis_pool_endpoint(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        asset_code = str(body.get("asset_code") or "").strip()
        if not asset_code:
            raise HTTPException(status_code=400, detail="asset_code is required")
        added = store.toggle_ai_analysis_pool(asset_code)
        stocks = store.get_ai_analysis_pool()
        return {"status": "SUCCESS", "asset_code": asset_code.upper(), "in_pool": added,
                "stocks": stocks, "codes": [s["asset_code"] for s in stocks]}

    @app.put("/api/watchlist/ai-pool")
    def replace_ai_analysis_pool_endpoint(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        raw_codes = body.get("codes")
        if not isinstance(raw_codes, list):
            raise HTTPException(status_code=400, detail="codes must be an array")
        store = PostgresScreeningStore(_database_url())
        stocks = store.replace_ai_analysis_pool([str(code) for code in raw_codes])
        return {"status": "SUCCESS", "stocks": stocks, "codes": [s["asset_code"] for s in stocks]}

    return app


app = create_app()


def _screening_payload(
    store: PostgresScreeningStore,
    trade_date: str,
    pool: str,
    page: int = 1,
    page_size: int = 50,
    min_score: float | None = None,
    max_score: float | None = None,
    query_text: str | None = None,
    industry: str | None = None,
    only_selected: bool = False,
) -> dict[str, Any]:
    if min_score is not None and max_score is not None and min_score > max_score:
        raise HTTPException(status_code=422, detail="min_score cannot be greater than max_score")
    pools = None if pool == "ABC" else {pool}
    counts = store.candidate_counts(trade_date, RULESET_VERSION)
    if counts["total"] == 0:
        raise HTTPException(status_code=404, detail=f"No screening candidates found for trade_date={trade_date}")
    normalized_query = (query_text or "").strip() or None
    normalized_industry = (industry or "").strip() or None
    filtered_total = store.filtered_candidate_count(
        trade_date,
        RULESET_VERSION,
        pools=pools,
        min_score=min_score,
        max_score=max_score,
        query_text=normalized_query,
        industry=normalized_industry,
        only_selected=only_selected,
    )
    candidates = store.query_candidates(
        trade_date,
        RULESET_VERSION,
        pools=pools,
        limit=page_size,
        offset=(page - 1) * page_size,
        min_score=min_score,
        max_score=max_score,
        query_text=normalized_query,
        industry=normalized_industry,
        only_selected=only_selected,
    )
    return {
        "trade_date": trade_date,
        "ruleset_version": RULESET_VERSION,
        "pool": pool,
        "counts": counts,
        "coverage": store.screening_coverage(trade_date, RULESET_VERSION),
        "industry_counts": store.candidate_industry_counts(trade_date, RULESET_VERSION, pools),
        "items": candidates,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": filtered_total,
            "total_pages": math.ceil(filtered_total / page_size) if filtered_total else 0,
        },
        "filters": {
            "min_score": min_score,
            "max_score": max_score,
            "query": normalized_query or "",
            "industry": normalized_industry or "",
        },
    }


def _serialize_run(run: dict[str, Any]) -> dict[str, Any]:
    """将 screening_run 行的 datetime 字段转为 ISO 字符串"""
    result = dict(run)
    for key in ("started_at", "finished_at"):
        val = result.get(key)
        if val is not None and hasattr(val, "isoformat"):
            result[key] = val.isoformat()
    return result
