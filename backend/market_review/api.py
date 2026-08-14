from __future__ import annotations

import os
import math
import time
import requests
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import psycopg
from psycopg.rows import dict_row

_MARKET_QUOTES_CACHE: dict[str, Any] = {"timestamp": 0.0, "data": []}

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
                cur.execute("""
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
                """)
                rows = cur.fetchall()
                for row in rows:
                    raw_code = str(row["asset_code"])
                    code = raw_code.split(".")[0]
                    name = str(row["name"] or code)
                    ind_name = str(row.get("industry") or "")
                    pct = float(row["pct_chg"] or 0.0)
                    price = float(row["price"] or 0.0)
                    change = float(row["change"] or 0.0)
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
    config_version: str = "early_turn_v1.0" 

class AddPositiveSampleRequest(BaseModel):
    ts_code: str
    target_date: str
    sample_name: str
    note: str | None = None

class DataSyncRequest(BaseModel):
    trade_date: str | None = None
    sync_financials: bool = True


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

_screening_task_lock = threading.Lock()
_screening_task_status = {
    "status": "idle",
    "progress": 0,
    "step_message": "",
    "trade_date": "",
    "pool": "ABC",
    "error": None,
    "started_at": None,
    "completed_at": None,
}


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


def _latest_open_trade_date(sync: ScreeningDataSync) -> str:
    today = date.today()
    start = (today - timedelta(days=14)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    dates = sync.source.trade_dates(start, end)
    if not dates:
        raise ScreeningError(f"no open trade dates between {start} and {end}")
    return dates[-1]


def _sync_screening_trade_date(store: PostgresScreeningStore, trade_date: str | None) -> dict[str, Any]:
    sync = _screening_sync(store)
    target_date = (trade_date or "").strip().replace("-", "")
    if not target_date:
        target_date = _latest_open_trade_date(sync)
    if len(target_date) != 8 or not target_date.isdigit():
        raise ScreeningError(f"invalid trade_date: {trade_date}")
    
    # 幂等判断：如果数据库已经拥有该主日线数据，0ms 静默跳过，无网络开销
    if store.has_daily_data(target_date):
        freshness = store.get_data_freshness_info()
        return {"trade_date": target_date, "skipped": True, "counts": {}, "freshness": freshness}
    
    counts: dict[str, Any] = {}
    try:
        counts = sync.sync_trade_date(target_date)
    except ScreeningError as exc:
        if "EMPTY_DATA" in str(exc):
            # 盘后日线尚未生成（如当天盘中），自动向前回溯前一交易日
            start = (date.today() - timedelta(days=14)).strftime("%Y%m%d")
            dates = sync.source.trade_dates(start, target_date)
            prev_date = dates[-2] if len(dates) >= 2 else target_date
            
            if store.has_daily_data(prev_date):
                print(f"[SYNC_SKIP] {target_date} 日线未出盘后总结，而前一交易日 {prev_date} 已在库，静默跳过日线补齐。", flush=True)
                counts = {"skipped": True, "fallback_date": prev_date}
            else:
                counts = sync.sync_trade_date(prev_date)
        else:
            raise exc

    freshness = store.get_data_freshness_info()

    # ── 月度概念快照自动断点补抓 (Monthly Auto Catch-up) ──────────────────
    try:
        from backend.screening.ths_concept_service import sync_ths_concepts
        sync_ths_concepts(store, as_of_date=target_date, force=False)
    except Exception as e_ths:
        print(f"[SYNC_WARN] Monthly THS concept catch-up warning: {e_ths}", flush=True)

    # ── 候选股二次评价快照自动补齐 (Secondary Evaluation Catch-up) ─────────
    try:
        from backend.screening.secondary_eval_engine import evaluate_single_secondary_candidate
        run_info = store.get_latest_early_turn_run(target_date)
        if run_info:
            res = store.query_early_turn_results(run_info["run_id"], limit=200)
            sec_rows, ev_rows, lead_rows, sup_rows = [], [], [], []
            for item in res.get("items", []):
                sec, ev, lead, sup = evaluate_single_secondary_candidate(store, item["ts_code"], target_date, item)
                sec_rows.append(sec)
                ev_rows.append(ev)
                lead_rows.append(lead)
                sup_rows.append(sup)
            if sec_rows:
                store.save_secondary_evaluation_snapshots(target_date, sec_rows, ev_rows, lead_rows, sup_rows)
    except Exception as e_sec:
        print(f"[SYNC_WARN] Secondary evaluation catch-up warning: {e_sec}", flush=True)

    return {"trade_date": target_date, "counts": counts, "freshness": freshness}


def create_app() -> FastAPI:
    from backend.market_review.scheduler import AutoDataScheduler
    from contextlib import asynccontextmanager

    scheduler = AutoDataScheduler(_database_url())

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        try:
            scheduler.start()
        except Exception as e:
            print(f"[API_STARTUP] 启动自动数据调度器失败: {e}")
        yield
        try:
            scheduler.stop()
        except Exception as e:
            print(f"[API_SHUTDOWN] 关闭自动数据调度器提示: {e}")

    app = FastAPI(title="LLL Market Review API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3002",
            "http://127.0.0.1:3002",
            "http://localhost:3004",
            "http://127.0.0.1:3004",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        _database_url()
        return {"status": "ok"}

    @app.post("/api/market-review/import")
    def import_market_review(request: ImportReviewRequest) -> dict[str, Any]:
        try:
            store = PostgresMarketReviewStore(_database_url())
            ai = MarketReviewAI(store)
            parsed = ai.parse_imported_review(content=request.content, trade_date=request.trade_date)
            
            trade_date = parsed.get("trade_date") or request.trade_date or "2026-08-04"
            saved = store.save_imported_review(
                trade_date=trade_date,
                raw_content=request.content,
                payload=parsed,
            )
            return saved
        except MarketReviewError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/market-review/overview/latest")
    def latest_overview() -> dict[str, Any]:
        store = PostgresMarketReviewStore(_database_url())
        imported = store.load_latest_imported_review()
        if imported is not None:
            return {
                "is_imported": True,
                "trade_date": imported["trade_date"],
                "raw_content": imported["raw_content"],
                "imported_payload": imported["payload"],
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
            return {
                "is_imported": True,
                "trade_date": imported["trade_date"],
                "raw_content": imported["raw_content"],
                "imported_payload": imported["payload"],
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

        bars = store.get_kline_bars(asset_code=code_str, period=period, adjust=adjust)
        if not bars and code_str != asset_code:
            bars = store.get_kline_bars(asset_code=asset_code, period=period, adjust=adjust)

        return {"asset_code": asset_code, "period": period, "adjust": adjust, "bars": bars}

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

    @app.get("/api/market/boards")
    def get_market_boards(
        sort_by: str = Query(default="pct_chg"),
        sort_order: str = Query(default="desc"),
        keyword: str = Query(default=""),
    ) -> dict[str, Any]:
        store_db_url = _database_url()
        with psycopg.connect(store_db_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    WITH latest_date AS (
                        SELECT MAX(trade_date) as max_date FROM screening_daily_bar
                    ),
                    stock_data AS (
                        SELECT 
                            m.asset_code,
                            m.name,
                            COALESCE(m.raw_json->>'industry', '其他') as industry,
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
                        industry as name,
                        COUNT(asset_code) as stock_count,
                        ROUND(AVG(pct_chg), 2) as pct_chg,
                        SUM(amount) as amount
                    FROM stock_data
                    WHERE industry IS NOT NULL AND industry != ''
                    GROUP BY industry;
                """)
                board_rows = cur.fetchall()

                cur.execute("""
                    WITH latest_date AS (
                        SELECT MAX(trade_date) as max_date FROM screening_daily_bar
                    ),
                    ranked_stocks AS (
                        SELECT 
                            COALESCE(m.raw_json->>'industry', '其他') as industry,
                            m.asset_code,
                            m.name,
                            COALESCE(b.pct_chg, 0) as pct_chg,
                            ROW_NUMBER() OVER (PARTITION BY COALESCE(m.raw_json->>'industry', '其他') ORDER BY COALESCE(b.pct_chg, 0) DESC) as rn
                        FROM screening_asset_master m
                        LEFT JOIN screening_daily_bar b 
                            ON m.asset_code = b.asset_code 
                           AND b.trade_date = (SELECT max_date FROM latest_date)
                        WHERE m.asset_type = 'stock'
                    )
                    SELECT industry, asset_code, name, pct_chg
                    FROM ranked_stocks
                    WHERE rn = 1;
                """)
                top_stocks = {r["industry"]: r for r in cur.fetchall()}

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
    @app.get("/api/early-turn/latest")
    def get_latest_early_turn_run(trade_date: str | None = Query(default=None)) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        run = store.get_latest_early_turn_run(trade_date=trade_date)
        if not run:
            # 兼容：如果尚未运行过，返回最新行情日期
            freshness = store.get_data_freshness_info()
            latest_date = freshness.get("daily_market_date") or "20260806"
            return {
                "run_id": None,
                "trade_date": latest_date,
                "status": "NOT_STARTED",
                "summary_json": {},
            }
        return _serialize_run(run)

    @app.get("/api/early-turn/runs/{run_id}/stocks")
    def get_early_turn_stocks(
        run_id: str,
        state: str | None = Query(default=None),
        bg_type: str | None = Query(default=None),
        min_score: float | None = Query(default=None),
        q: str | None = Query(default=None),
        industry: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        store = PostgresScreeningStore(_database_url())
        res = store.query_early_turn_results(
            run_id=run_id,
            state=state,
            background_type=bg_type,
            min_score=min_score,
            query_text=q,
            industry=industry,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        res["page"] = page
        res["page_size"] = page_size
        return res

    @app.post("/api/early-turn/run")
    def trigger_early_turn_run(req: RunEarlyTurnRequest) -> dict[str, Any]:
        from backend.screening.early_turn_service import EarlyTurnService
        store = PostgresScreeningStore(_database_url())
        trade_date = req.trade_date or store.get_data_freshness_info().get("daily_market_date") or "20260806"
        
        # 同步增量交易日数据
        _sync_screening_trade_date(store, trade_date)
        
        svc = EarlyTurnService(store=store)
        summary = svc.run(trade_date=trade_date, ts_code=req.ts_code, config_version=req.config_version)
        return {"status": "SUCCESS", "summary": summary}

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
        with _screening_task_lock:
            if _screening_task_status.get("status") in ("running", "RUNNING"):
                return {"status": "already_running", "task": dict(_screening_task_status)}
            
            _screening_task_status["status"] = "running"
            _screening_task_status["progress"] = 10
            _screening_task_status["step_message"] = "正在启动后台数据同步与补全线程..."
            _screening_task_status["error"] = None
            _screening_task_status["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

        def _sync_worker():
            try:
                store = PostgresScreeningStore(_database_url())
                with _screening_task_lock:
                    _screening_task_status["progress"] = 15
                    _screening_task_status["step_message"] = "正在检查并补齐全市场 5500+ A股日线数据..."
                
                result = _sync_screening_trade_date(store, None)
                target_date = result.get("trade_date") or ""

                # 双重完备跳过：若该交易日全量日线与 30m K线均已完备，0.01秒瞬间结束
                if target_date and store.has_daily_data(target_date) and store.has_30m_data(target_date):
                    _MARKET_QUOTES_CACHE["timestamp"] = 0.0
                    with _screening_task_lock:
                        _screening_task_status["status"] = "success"
                        _screening_task_status["progress"] = 100
                        _screening_task_status["step_message"] = f"行情数据已是最新 ({target_date})，无需重复同步！"
                        _screening_task_status["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    return

                # 增加 30 分钟 K 线增量同步
                sync = _screening_sync(store)
                with _screening_task_lock:
                    _screening_task_status["progress"] = 35
                    _screening_task_status["step_message"] = "正在增量补全 5500+ A股的 30 分钟 K 线数据..."
                
                def _30m_progress(idx: int, total: int, code: str):
                    pct = 35 + int((idx / max(total, 1)) * 50)
                    with _screening_task_lock:
                        _screening_task_status["progress"] = pct
                        _screening_task_status["step_message"] = f"正在同步 30 分钟 K 线 ({code} {idx}/{total})..."

                start_lookup = target_date or "20260101"
                try:
                    sync.sync_30m_bars_all(
                        start_date=start_lookup,
                        end_date=target_date,
                        progress_callback=_30m_progress
                    )
                except Exception as e:
                    print(f"30m bar sync warning: {e}")

                with _screening_task_lock:
                    _screening_task_status["progress"] = 90
                    _screening_task_status["step_message"] = "正在更新申万板块与聚合指标..."

                _MARKET_QUOTES_CACHE["timestamp"] = 0.0

                with _screening_task_lock:
                    _screening_task_status["status"] = "success"
                    _screening_task_status["progress"] = 100
                    _screening_task_status["step_message"] = f"目标交易日 {target_date} 全量日线与 30 分钟 K 线数据已成功更新补齐！"
                    _screening_task_status["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as exc:
                with _screening_task_lock:
                    _screening_task_status["status"] = "failed"
                    _screening_task_status["progress"] = 0
                    _screening_task_status["step_message"] = f"数据补全失败: {str(exc)}"
                    _screening_task_status["error"] = str(exc)

        background_tasks.add_task(_sync_worker)
        return {"status": "started", "message": "后台补全数据任务已启动"}

    @app.post("/api/screening/data-sync/cancel")
    def cancel_data_sync() -> dict[str, Any]:
        with _screening_task_lock:
            _screening_task_status["status"] = "idle"
            _screening_task_status["progress"] = 0
            _screening_task_status["step_message"] = "数据补全任务已重置归零"
            _screening_task_status["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
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

    # ── Secondary Evaluation & AI Deep Research System V1.0 Endpoints ────
    @app.get("/api/data/capabilities")
    def data_capabilities() -> dict[str, Any]:
        from backend.screening.ths_concept_service import check_data_capabilities
        store = PostgresScreeningStore(_database_url())
        return check_data_capabilities(store)

    @app.post("/api/data/ths-concepts/sync")
    def sync_ths_concepts_endpoint(trade_date: str | None = Query(default=None)) -> dict[str, Any]:
        from backend.screening.ths_concept_service import sync_ths_concepts
        store = PostgresScreeningStore(_database_url())
        return sync_ths_concepts(store, as_of_date=trade_date)

    @app.get("/api/candidate-secondary")
    def get_candidate_secondary_list_endpoint(date: str | None = Query(default=None)) -> dict[str, Any]:
        from backend.screening.secondary_eval_engine import evaluate_single_secondary_candidate
        store = PostgresScreeningStore(_database_url())
        as_of_date = date or store.latest_candidate_date(RULESET_VERSION) or datetime.now(UTC).strftime("%Y%m%d")
        items = store.get_candidate_secondary_list(as_of_date)
        if not items:
            run_info = store.get_latest_early_turn_run(as_of_date)
            if run_info:
                res = store.query_early_turn_results(run_info["run_id"], limit=100)
                sec_rows, ev_rows, lead_rows, sup_rows = [], [], [], []
                for item in res.get("items", []):
                    sec, ev, lead, sup = evaluate_single_secondary_candidate(store, item["ts_code"], as_of_date, item)
                    sec_rows.append(sec)
                    ev_rows.append(ev)
                    lead_rows.append(lead)
                    sup_rows.append(sup)
                if sec_rows:
                    store.save_secondary_evaluation_snapshots(as_of_date, sec_rows, ev_rows, lead_rows, sup_rows)
                    items = store.get_candidate_secondary_list(as_of_date)
        return {"as_of_date": as_of_date, "items": items, "count": len(items)}

    @app.get("/api/candidate-secondary/{ts_code}")
    def get_candidate_secondary_detail_endpoint(ts_code: str, date: str = Query(...)) -> dict[str, Any]:
        from backend.screening.ai_deep_research_service import get_ai_stock_research_result
        from backend.screening.secondary_eval_engine import evaluate_single_secondary_candidate
        from backend.screening.ths_concept_service import get_stock_ths_concepts

        store = PostgresScreeningStore(_database_url())
        detail = store.get_candidate_secondary_detail(date, ts_code)
        if not detail:
            sec, ev, lead, sup = evaluate_single_secondary_candidate(store, ts_code, date)
            store.save_secondary_evaluation_snapshots(date, [sec], [ev], [lead], [sup])
            detail = store.get_candidate_secondary_detail(date, ts_code)

        concepts = get_stock_ths_concepts(store, ts_code, date)
        ai_research = get_ai_stock_research_result(store, ts_code, date)

        return {
            "as_of_date": date,
            "ts_code": ts_code,
            "detail": detail,
            "concepts_info": concepts,
            "ai_research": ai_research,
        }

    @app.post("/api/candidate-secondary/run")
    def run_candidate_secondary_endpoint(body: dict[str, Any]) -> dict[str, Any]:
        from backend.screening.secondary_eval_engine import evaluate_single_secondary_candidate
        as_of_date = body.get("date") or datetime.now(UTC).strftime("%Y%m%d")
        store = PostgresScreeningStore(_database_url())
        run_info = store.get_latest_early_turn_run(as_of_date)
        ts_codes = []
        if run_info:
            res = store.query_early_turn_results(run_info["run_id"], limit=500)
            ts_codes = [r["ts_code"] for r in res.get("items", [])]
        if not ts_codes:
            ts_codes = ["600518.SH", "300759.SZ", "300308.SZ", "603881.SH"]

        sec_rows, ev_rows, lead_rows, sup_rows = [], [], [], []
        for code in ts_codes:
            sec, ev, lead, sup = evaluate_single_secondary_candidate(store, code, as_of_date)
            sec_rows.append(sec)
            ev_rows.append(ev)
            lead_rows.append(lead)
            sup_rows.append(sup)

        store.save_secondary_evaluation_snapshots(as_of_date, sec_rows, ev_rows, lead_rows, sup_rows)
        return {"status": "SUCCESS", "as_of_date": as_of_date, "evaluated_count": len(sec_rows)}

    @app.post("/api/ai/stock-research")
    def run_ai_stock_research_endpoint(body: dict[str, Any]) -> dict[str, Any]:
        from backend.screening.ai_deep_research_service import run_ai_stock_research
        as_of_date = body.get("date") or datetime.now(UTC).strftime("%Y%m%d")
        ts_codes = body.get("ts_codes") or []
        lookback = body.get("review_lookback", 20)
        use_search = body.get("use_web_search", True)

        if not ts_codes:
            raise HTTPException(status_code=400, detail="ts_codes is required")

        store = PostgresScreeningStore(_database_url())
        results = []
        for code in ts_codes[:20]:
            res = run_ai_stock_research(store, code, as_of_date, review_lookback=lookback, use_web_search=use_search)
            results.append(res)

        return {"status": "SUCCESS", "as_of_date": as_of_date, "items": results}

    @app.get("/api/ai/stock-research/{ts_code}")
    def get_ai_stock_research_endpoint(ts_code: str, date: str = Query(...)) -> dict[str, Any]:
        from backend.screening.ai_deep_research_service import get_ai_stock_research_result
        store = PostgresScreeningStore(_database_url())
        res = get_ai_stock_research_result(store, ts_code, date)
        return {"ts_code": ts_code, "as_of_date": date, "result": res}

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
