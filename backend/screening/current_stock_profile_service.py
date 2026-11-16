"""Current stock profiles shared by review, screening and watchlist surfaces.

Historical selection evidence remains in the date-keyed secondary tables.  This
module deliberately keeps only the latest cross-page stock attributes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.screening.secondary_eval_engine import evaluate_company_evidence, evaluate_supply_profile
from backend.screening.storage import PostgresScreeningStore
from backend.screening.theme_match_service import match_stock_theme
from backend.screening.ths_concept_service import get_stock_ths_concepts


def _json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return {}


def _current_pit_date() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")


def _latest_market_memory(store: PostgresScreeningStore) -> tuple[str, dict[str, Any]]:
    with store.connect() as conn:
        row = conn.execute(
            "select as_of_date, memory_json from screening_market_memory_cache order by as_of_date desc limit 1"
        ).fetchone()
    if not row:
        raise RuntimeError("当前尚无可用市场主题记忆")
    return str(row["as_of_date"]).replace("-", ""), _as_dict(row["memory_json"])


def _stock_identity(store: PostgresScreeningStore, ts_code: str) -> dict[str, Any]:
    with store.connect() as conn:
        row = conn.execute(
            "select name, raw_json->>'main_business' as main_business, raw_json->>'industry' as industry from screening_asset_master where asset_code = %s",
            (ts_code,),
        ).fetchone()
    if not row:
        raise RuntimeError(f"证券主数据不存在：{ts_code}")
    return dict(row)


def get_or_refresh_current_fundamental_profile(store: PostgresScreeningStore, ts_code: str) -> dict[str, Any]:
    code = ts_code.strip().upper()
    evidence = evaluate_company_evidence(store, code, _current_pit_date())
    fingerprint_input = {
        key: evidence.get(key)
        for key in (
            "latest_report_period", "latest_report_ann_date", "revenue", "revenue_yoy",
            "parent_net_profit", "parent_net_profit_yoy", "deducted_net_profit",
            "deducted_net_profit_yoy", "operating_cashflow", "operating_cashflow_yoy",
            "forecast_ann_date", "forecast_type", "forecast_p_change_min", "forecast_p_change_max",
            "express_ann_date", "express_end_date", "express_revenue", "express_n_income",
            "express_yoy_net_profit", "fundamental_filter_state", "risk_flags_json",
        )
    }
    fingerprint = _json_hash(fingerprint_input)
    existing = store.get_current_stock_profile("fundamental", code)
    if existing and existing.get("source_fingerprint") == fingerprint:
        return existing
    announcement_dates = [
        str(evidence.get(field) or "")
        for field in ("latest_report_ann_date", "forecast_ann_date", "express_ann_date")
        if evidence.get(field)
    ]
    store.save_current_fundamental_profile(
        code, fingerprint, max(announcement_dates) if announcement_dates else None,
        evidence, str(evidence.get("fundamental_filter_state") or "UNKNOWN"),
    )
    profile = store.get_current_stock_profile("fundamental", code)
    if not profile:
        raise RuntimeError("当前基本面档案保存后无法读取")
    return profile


def get_or_refresh_current_market_profile(store: PostgresScreeningStore, ts_code: str) -> dict[str, Any]:
    code = ts_code.strip().upper()
    with store.connect() as conn:
        row = conn.execute(
            "select max(trade_date) as trade_date from screening_daily_bar where asset_code = %s and asset_type = 'stock'",
            (code,),
        ).fetchone()
    trade_date = str(row["trade_date"] or "") if row else ""
    if not trade_date:
        raise RuntimeError(f"{code} 缺少可用日线行情，无法生成当前市场状态")
    market = evaluate_supply_profile(store, code, trade_date)
    fingerprint = _json_hash(market)
    existing = store.get_current_stock_profile("market", code)
    if existing and existing.get("source_fingerprint") == fingerprint:
        return existing
    store.save_current_market_profile(code, trade_date, fingerprint, market, str(market.get("supply_profile_label") or "UNKNOWN"))
    profile = store.get_current_stock_profile("market", code)
    if not profile:
        raise RuntimeError("当前市场状态保存后无法读取")
    return profile


def get_or_refresh_current_theme_profile(store: PostgresScreeningStore, ts_code: str) -> dict[str, Any]:
    code = ts_code.strip().upper()
    memory_date, memory_json = _latest_market_memory(store)
    identity = _stock_identity(store, code)
    concepts_info = get_stock_ths_concepts(store, code, memory_date)
    concept_names = [str(item.get("ths_name") or "") for item in concepts_info.get("concepts", []) if item.get("ths_name")]
    theme_fingerprint = _json_hash(memory_json.get("themes") or [])
    concept_fingerprint = _json_hash({
        "concepts": sorted(concept_names),
        "snapshot_date": concepts_info.get("snapshot_date"),
    })
    existing = store.get_current_stock_profile("theme", code)
    if existing and existing.get("market_theme_fingerprint") == theme_fingerprint and existing.get("concept_fingerprint") == concept_fingerprint:
        return existing
    result = match_stock_theme(
        store=store,
        ts_code=code,
        as_of_date=memory_date,
        market_memory=memory_json,
        stock_knowledge={
            "ts_code": code,
            "stock_name": identity.get("name"),
            "industry": identity.get("industry"),
            "main_business": identity.get("main_business"),
            "ths_concepts": concept_names,
            "concept_temporal_status": concepts_info.get("temporal_status", "PIT_SAFE"),
        },
        use_web_search=False,
    )
    result.pop("_ai_usage", None)
    store.save_current_theme_profile(
        code, theme_fingerprint, memory_date, concept_fingerprint, result,
        "READY" if not result.get("no_active_theme_match") else "NO_ACTIVE_THEME_MATCH",
    )
    profile = store.get_current_stock_profile("theme", code)
    if not profile:
        raise RuntimeError("当前主题档案保存后无法读取")
    return profile


def current_stock_profile_bundle(store: PostgresScreeningStore, ts_code: str, refresh_fundamental: bool = True, refresh_market: bool = True) -> dict[str, Any]:
    code = ts_code.strip().upper()
    if refresh_fundamental:
        get_or_refresh_current_fundamental_profile(store, code)
    if refresh_market:
        get_or_refresh_current_market_profile(store, code)
    return store.get_current_stock_profiles(code)
