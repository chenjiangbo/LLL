from __future__ import annotations

from datetime import datetime
import logging
import re
from typing import Any

import pandas as pd

from backend.screening.storage import PostgresScreeningStore
from backend.screening.utils import json_dumps


SUPPLY_PROFILE_THRESHOLDS = {
    "micro_free_float_mv_yi": 20.0,
    "small_free_float_mv_yi": 50.0,
    "mid_free_float_mv_yi": 150.0,
    "large_free_float_mv_yi": 500.0,
}
SECONDARY_EVAL_VERSION = "v3.2"
logger = logging.getLogger(__name__)


# Market Memory uses trading-theme labels while the THS snapshot stores
# canonical concept/index names. Keep this mapping explicit and auditable;
# do not silently fall back to an arbitrary concept or sample universe.
THEME_CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "农业/种业": ("农业", "种业", "种植", "养殖", "猪肉", "生猪", "农林牧渔", "农产品", "农副食品", "畜牧"),
    "农业种业": ("农业", "种业", "种植", "养殖", "猪肉", "生猪", "农林牧渔", "农产品", "农副食品", "畜牧"),
}


def _theme_concept_terms(theme_name: str) -> list[str]:
    normalized = re.sub(r"\s+", "", str(theme_name or "")).strip()
    if not normalized:
        return []
    terms = [normalized]
    terms.extend(
        token
        for token in re.split(r"[/／、,，&+及和()（）]", normalized)
        if len(token) >= 2
    )
    terms.extend(THEME_CONCEPT_ALIASES.get(normalized, ()))
    return list(dict.fromkeys(term for term in terms if term))


def evaluate_company_evidence(
    store: PostgresScreeningStore,
    ts_code: str,
    as_of_date: str,
) -> dict[str, Any]:
    """
    公司层面客观证据。
    仅读取查看日期前已经公告的财务与预告数据。
    """
    reasons: list[dict[str, Any]] = []
    risk_flags: list[str] = []

    periods = store.get_company_financial_periods_pit(ts_code, as_of_date, limit=16)
    quarter_facts = _build_quarter_facts(periods)
    latest_quarter = quarter_facts[0] if quarter_facts else {}

    pit = store.get_company_financial_pit(ts_code, as_of_date)
    income = pit.get("income") or {}
    indicator = pit.get("indicator") or {}
    forecast = periods.get("forecast") or pit.get("forecast") or {}
    express = periods.get("express") or pit.get("express") or {}
    if express and income.get("end_date") and str(express.get("end_date") or "") < str(income.get("end_date")):
        express = {}

    revenue = _safe_float(latest_quarter.get("revenue"))
    parent_profit_curr = _safe_float(latest_quarter.get("parent_net_profit"))
    deducted_profit_curr = _safe_float(latest_quarter.get("deducted_net_profit"))
    operating_cashflow = _safe_float(latest_quarter.get("operating_cashflow"))

    rev_yoy = _safe_float(latest_quarter.get("revenue_yoy"))
    parent_yoy = _safe_float(latest_quarter.get("parent_net_profit_yoy"))
    deducted_yoy = _safe_float(latest_quarter.get("deducted_net_profit_yoy"))
    if deducted_yoy is None:
        deducted_yoy = _pct_to_ratio(indicator.get("dt_netprofit_yoy"))
    ocf_yoy = _safe_float(latest_quarter.get("operating_cashflow_yoy"))
    gross_margin = _pct_to_ratio(indicator.get("grossprofit_margin"))

    # 利润状态以去年同期为唯一的经营判断口径。上一季度仅用于展示环比变化，
    # 不能把季节性造成的“环比由亏转盈”误写成经营层面的“扭亏”。
    same_period_last_year = _find_same_period_last_year(quarter_facts)
    parent_profit_state = _determine_profit_state(
        parent_profit_curr,
        _safe_float((same_period_last_year or {}).get("parent_net_profit")),
        parent_yoy,
    )
    deducted_profit_state = _determine_profit_state(
        deducted_profit_curr,
        _safe_float((same_period_last_year or {}).get("deducted_net_profit")),
        deducted_yoy,
    )

    # 3. 风险标记检查
    if parent_profit_state == "TURN_TO_LOSS" or deducted_profit_state == "TURN_TO_LOSS":
        risk_flags.append("TURN_TO_LOSS")
        reasons.append({"type": "RISK", "msg": "业绩由盈利转为亏损"})
    if parent_profit_state == "LOSS_WIDENING":
        risk_flags.append("PARENT_LOSS_WIDENING")
        reasons.append({"type": "RISK", "msg": "归母净利润同比亏损额进一步扩大"})
    if deducted_profit_state == "LOSS_WIDENING":
        risk_flags.append("DEDUCTED_LOSS_WIDENING")
        reasons.append({"type": "RISK", "msg": "扣非净利润同比亏损额进一步扩大"})
    if rev_yoy is not None and rev_yoy <= -0.20:
        risk_flags.append("REVENUE_SHARP_DROP")
        reasons.append({"type": "RISK", "msg": f"营业收入大幅下滑 {rev_yoy*100:.1f}%"})

    # 4. 正面边际标记
    if parent_profit_state == "TURNAROUND" or deducted_profit_state == "TURNAROUND":
        reasons.append({"type": "POSITIVE", "msg": "归母或扣非利润同比扭亏为盈"})
    elif parent_profit_state == "LOSS_NARROWING":
        reasons.append({"type": "POSITIVE", "msg": "亏损大幅收窄，边际改善"})

    if rev_yoy is not None and rev_yoy >= 0.10:
        reasons.append({"type": "POSITIVE", "msg": f"营业收入保持良好增长 (同比+{rev_yoy*100:.1f}%)"})
    fact_tags = _build_company_fact_tags(quarter_facts, forecast, express)
    # 现金流由正转负是明确的经营恶化，和由盈转亏一样应进入硬风险集合。
    # 以前它只有标签，容易被其它正面标签掩盖。
    if any(tag.get("label") == "现金流同比转负" for tag in fact_tags):
        risk_flags.append("CASHFLOW_TURN_TO_NEGATIVE")
        reasons.append({"type": "RISK", "msg": "经营现金流由正转负"})
    for tag in fact_tags:
        reasons.append({"type": tag.get("tone", "INFO"), "msg": tag["label"]})

    if express:
        reasons.append({"type": "INFO", "msg": f"已纳入 {express.get('end_date')} 业绩快报"})

    # 5. 总体 Evidence 状态判定
    if len(risk_flags) > 0:
        evidence_state = "RISK"
    elif any(r["type"] == "POSITIVE" for r in reasons):
        if any(r["type"] == "RISK" for r in reasons):
            evidence_state = "MIXED"
        else:
            evidence_state = "POSITIVE"
    elif rev_yoy is not None or parent_yoy is not None:
        evidence_state = "MIXED" if (rev_yoy or 0) < 0 else "POSITIVE"
    elif fact_tags:
        evidence_state = "MIXED"
    else:
        evidence_state = "UNKNOWN"
        reasons.append({"type": "INFO", "msg": "当前日期前，系统中暂无已公告的财报或业绩预告记录"})

    data_quality = _build_company_data_quality(periods, quarter_facts)
    fundamental_filter_state, fundamental_filter_reasons = classify_fundamental_filter(
        latest_report_period=latest_quarter.get("period") or income.get("end_date"),
        revenue=revenue,
        parent_net_profit=parent_profit_curr,
        deducted_net_profit=deducted_profit_curr,
        risk_flags=risk_flags,
        fact_tags=fact_tags,
        revenue_yoy=rev_yoy,
        parent_profit_state=parent_profit_state,
        deducted_profit_state=deducted_profit_state,
    )

    return {
        "as_of_date": as_of_date,
        "ts_code": ts_code,
        "latest_report_period": latest_quarter.get("period") or income.get("end_date"),
        "latest_report_ann_date": latest_quarter.get("available_date") or income.get("available_date"),
        "revenue": revenue,
        "revenue_yoy": rev_yoy,
        "parent_net_profit": parent_profit_curr,
        "parent_net_profit_yoy": parent_yoy,
        "parent_profit_state": parent_profit_state,
        "deducted_net_profit": deducted_profit_curr,
        "deducted_net_profit_yoy": deducted_yoy,
        "deducted_profit_state": deducted_profit_state,
        "operating_cashflow": operating_cashflow,
        "operating_cashflow_yoy": ocf_yoy,
        "gross_margin": gross_margin,
        "gross_margin_yoy_delta": None,
        "forecast_ann_date": forecast.get("available_date"),
        "forecast_type": forecast.get("type"),
        "forecast_p_change_min": _safe_float(forecast.get("p_change_min")),
        "forecast_p_change_max": _safe_float(forecast.get("p_change_max")),
        "forecast_net_profit_min": _safe_float(forecast.get("net_profit_min")),
        "forecast_net_profit_max": _safe_float(forecast.get("net_profit_max")),
        "express_ann_date": express.get("available_date"),
        "express_end_date": express.get("end_date"),
        "express_revenue": _safe_float(express.get("revenue")),
        "express_n_income": _safe_float(express.get("n_income")),
        "express_yoy_net_profit": _pct_to_ratio(express.get("yoy_net_profit")),
        "express_summary": express.get("perf_summary"),
        "evidence_state": evidence_state,
        "reason_json": reasons,
        "risk_flags_json": risk_flags,
        "quarter_facts_json": quarter_facts[:8],
        "fact_tags_json": fact_tags,
        "data_quality_json": data_quality,
        "fundamental_filter_state": fundamental_filter_state,
        "fundamental_filter_reasons_json": fundamental_filter_reasons,
        "data_version": SECONDARY_EVAL_VERSION,
    }


def classify_fundamental_filter(
    *,
    latest_report_period: Any,
    revenue: float | None,
    parent_net_profit: float | None,
    deducted_net_profit: float | None,
    risk_flags: list[str],
    fact_tags: list[dict[str, Any]],
    revenue_yoy: float | None,
    parent_profit_state: str,
    deducted_profit_state: str,
) -> tuple[str, list[str]]:
    """Generate the user-facing post-research fundamental filter state.

    The classification deliberately uses explicit evidence rather than a hidden
    total score.  "Data insufficient" and "unresearched" are kept separate:
    this function only handles stocks that have actually run through research.
    """
    if not latest_report_period or (revenue is None and parent_net_profit is None and deducted_net_profit is None):
        return "FUNDAMENTAL_DATA_INSUFFICIENT", ["缺少最新已公告的营收或利润数据，暂不判断经营质量"]

    risk_labels = {
        "TURN_TO_LOSS": "由盈转亏",
        "PARENT_LOSS_WIDENING": "归母亏损扩大",
        "DEDUCTED_LOSS_WIDENING": "扣非亏损扩大",
        "REVENUE_SHARP_DROP": "营收同比大幅下滑",
        "CASHFLOW_TURN_TO_NEGATIVE": "经营现金流转负",
    }
    hard_risks = [risk_labels[flag] for flag in risk_flags if flag in risk_labels]
    if hard_risks:
        return "FUNDAMENTAL_RISK", hard_risks

    positive_labels = [
        str(tag.get("label"))
        for tag in fact_tags
        if tag.get("tone") == "POSITIVE" and tag.get("label")
    ]
    if (
        revenue_yoy is not None and revenue_yoy >= 0.10
        or parent_profit_state in {"TURNAROUND", "LOSS_NARROWING"}
        or deducted_profit_state in {"TURNAROUND", "LOSS_NARROWING"}
        or positive_labels
    ):
        return "FUNDAMENTAL_POSITIVE", list(dict.fromkeys(positive_labels)) or ["经营出现正向边际证据"]

    return "FUNDAMENTAL_ACCEPTABLE", ["最新报告已披露，未命中硬性经营风险"]


def rebuild_company_evidence_snapshots(store: PostgresScreeningStore) -> dict[str, Any]:
    """基于原始 PIT 财务数据完整重建全部已保存的公司证据快照。"""
    with store.connect() as conn:
        rows = conn.execute(
            """
            select distinct as_of_date, ts_code
            from company_evidence_snapshot
            order by as_of_date, ts_code
            """
        ).fetchall()
    by_date: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows, start=1):
        as_of_date = str(row["as_of_date"])
        evidence = evaluate_company_evidence(store, str(row["ts_code"]), as_of_date)
        by_date.setdefault(as_of_date, []).append(evidence)
        if index % 100 == 0 or index == len(rows):
            logger.info("已重建公司基本面快照 %s/%s", index, len(rows))

    counts: dict[str, int] = {}
    for as_of_date, evidence_rows in by_date.items():
        store.save_secondary_evaluation_snapshots(as_of_date, [], evidence_rows, [], [])
        for evidence in evidence_rows:
            state = str(evidence["fundamental_filter_state"])
            counts[state] = counts.get(state, 0) + 1

    with store.connect() as conn:
        conn.execute(
            """
            update candidate_secondary_snapshot candidate
            set company_evidence_state = evidence.evidence_state,
                calc_version = %s
            from company_evidence_snapshot evidence
            where candidate.as_of_date = evidence.as_of_date
              and candidate.ts_code = evidence.ts_code
            """,
            (SECONDARY_EVAL_VERSION,),
        )
        conn.commit()
    return {"processed_count": len(rows), "counts": counts, "data_version": SECONDARY_EVAL_VERSION}


def refresh_fundamental_filter_states(store: PostgresScreeningStore) -> dict[str, Any]:
    """兼容旧调用：规则升级时必须完整重建，不能仅重算筛选标签。"""
    return rebuild_company_evidence_snapshots(store)


def evaluate_supply_profile(
    store: PostgresScreeningStore,
    ts_code: str,
    as_of_date: str,
) -> dict[str, Any]:
    """
    交易容量与活跃度画像。
    使用 daily_basic 与最近 20 个交易日成交额计算真实筹码/容量画像。
    """
    with store.connect() as conn:
        b_row = conn.execute(
            "select * from screening_daily_basic where asset_code = %s and trade_date = %s", (ts_code, as_of_date)
        ).fetchone()
        bar_row = conn.execute(
            "select close, amount from screening_daily_bar where asset_code = %s and trade_date = %s",
            (ts_code, as_of_date),
        ).fetchone()
        amount_median_row = conn.execute(
            """
            select percentile_cont(0.5) within group (order by amount) as amount_median_20
            from (
                select amount
                from screening_daily_bar
                where asset_code = %s and asset_type = 'stock' and trade_date <= %s
                order by trade_date desc
                limit 20
            ) t
            """,
            (ts_code, as_of_date),
        ).fetchone()
        supply_events = store.get_supply_events_pit(ts_code, as_of_date)

    close = _safe_float(bar_row.get("close")) if bar_row else None
    amount = _safe_float(bar_row.get("amount")) if bar_row else None

    total_share = _safe_float(b_row.get("total_share")) if b_row else None
    float_share = _safe_float(b_row.get("float_share")) if b_row else None
    free_share = _safe_float(b_row.get("free_share")) if b_row else None
    turnover_rate = _safe_float(b_row.get("turnover_rate")) if b_row else None
    turnover_rate_f = _safe_float(b_row.get("turnover_rate_f")) if b_row else None
    volume_ratio = _safe_float(b_row.get("volume_ratio")) if b_row else None
    total_mv = _safe_float(b_row.get("total_mv")) if b_row else None
    circ_mv = _safe_float(b_row.get("circ_mv")) if b_row else None
    amount_median_20 = _safe_float(amount_median_row.get("amount_median_20")) if amount_median_row else None

    if free_share is not None and close is not None:
        free_float_mv_yi = (free_share * close) / 10000.0  # 亿元
    else:
        free_float_mv_yi = None

    if free_float_mv_yi is None or amount_median_20 is None:
        label = "DATA_MISSING"
    elif free_float_mv_yi < SUPPLY_PROFILE_THRESHOLDS["micro_free_float_mv_yi"]:
        label = "MICRO_ELASTIC"
    elif free_float_mv_yi <= SUPPLY_PROFILE_THRESHOLDS["small_free_float_mv_yi"]:
        label = "SMALL_ELASTIC"
    elif free_float_mv_yi < SUPPLY_PROFILE_THRESHOLDS["mid_free_float_mv_yi"]:
        label = "MID_CAP"
    elif free_float_mv_yi < SUPPLY_PROFILE_THRESHOLDS["large_free_float_mv_yi"]:
        label = "LARGE_CAPACITY"
    else:
        label = "MEGA_CAPACITY"

    return {
        "as_of_date": as_of_date,
        "ts_code": ts_code,
        "close": close,
        "total_mv": total_mv / 10000.0 if total_mv else None,
        "circ_mv": circ_mv / 10000.0 if circ_mv else None,
        "total_share": total_share,
        "float_share": float_share,
        "free_share": free_share,
        "free_float_mv": free_float_mv_yi,
        "amount": amount,
        "amount_median_20": amount_median_20,
        "turnover_rate": turnover_rate,
        "turnover_rate_f": turnover_rate_f,
        "volume_ratio": volume_ratio,
        "unlock_30d": supply_events.get("unlock_30d"),
        "unlock_60d": supply_events.get("unlock_60d"),
        "unlock_90d": supply_events.get("unlock_90d"),
        "recent_reduction_flag": supply_events.get("recent_reduction_flag"),
        "supply_profile_label": label,
        "data_version": SECONDARY_EVAL_VERSION,
    }


def evaluate_single_secondary_candidate(
    store: PostgresScreeningStore,
    ts_code: str,
    as_of_date: str,
    aprev2_info: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    evidence = evaluate_company_evidence(store, ts_code, as_of_date)
    leadership = _pending_theme_leadership(ts_code, as_of_date)
    supply = evaluate_supply_profile(store, ts_code, as_of_date)

    sec_snapshot = {
        "as_of_date": as_of_date,
        "ts_code": ts_code,
        # 复盘文章中的股票不一定来自 A-PreV2。没有对应选股结果时，
        # 技术分和生命周期必须保持为空，不能伪装成默认的选股结论。
        "aprev2_score": aprev2_info.get("total_score") if aprev2_info else None,
        "aprev2_status": aprev2_info.get("state") if aprev2_info else None,
        "turn_type": aprev2_info.get("background_type") if aprev2_info else None,
        "company_evidence_state": evidence["evidence_state"],
        "leadership_state": leadership["leadership_state"],
        "leadership_rank_value": leadership["leadership_rank_value"],
        "supply_profile_label": supply["supply_profile_label"],
        "calc_version": SECONDARY_EVAL_VERSION,
    }

    return sec_snapshot, evidence, leadership, supply


def _pending_theme_leadership(ts_code: str, as_of_date: str) -> dict[str, Any]:
    return {
        "as_of_date": as_of_date,
        "ts_code": ts_code,
        "comparison_level": "THEME",
        "comparison_industry_code": None,
        "comparison_industry_name": None,
        "comparison_universe_size": None,
        "stock_ret_5": None,
        "stock_ret_10": None,
        "stock_ret_20": None,
        "industry_rs_5_pct": None,
        "industry_rs_10_pct": None,
        "industry_rs_20_pct": None,
        "up_event_count": 0,
        "up_capture_excess": None,
        "up_capture_pct": None,
        "down_event_count": 0,
        "down_defense_excess": None,
        "down_defense_pct": None,
        "amount_ratio_5_20": None,
        "amount_ratio_10_40": None,
        "participation_pct": None,
        "participation_change": None,
        "participation_change_pct": None,
        "valid_component_count": 0,
        "leadership_rank_value": None,
        "leadership_state": "PENDING_THEME_MATCH",
        "reason_json": [{"type": "INFO", "msg": "等待主题匹配后显示同主题股票对比。"}],
        "calc_version": SECONDARY_EVAL_VERSION,
    }


def _safe_float(val: Any) -> float | None:
    if val is None or pd.isna(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _pct_to_ratio(val: Any) -> float | None:
    num = _safe_float(val)
    if num is None:
        return None
    return num / 100.0


def _calc_yoy(curr: float | None, last: float | None) -> float | None:
    if curr is None or last is None or last == 0:
        return None
    return (curr - last) / abs(last)


def _period_quarter(end_date: str | None) -> tuple[int, int] | None:
    if not end_date or len(str(end_date)) < 8:
        return None
    text = str(end_date)
    try:
        year = int(text[:4])
        month = int(text[4:6])
    except ValueError:
        return None
    quarter_by_month = {3: 1, 6: 2, 9: 3, 12: 4}
    quarter = quarter_by_month.get(month)
    if quarter is None:
        return None
    return year, quarter


def _quarter_label(end_date: str | None) -> str | None:
    period = _period_quarter(end_date)
    if period is None:
        return None
    year, quarter = period
    return f"{year}Q{quarter}"


def _prev_quarter_end_date(end_date: str | None) -> str | None:
    period = _period_quarter(end_date)
    if period is None:
        return None
    year, quarter = period
    if quarter == 1:
        return None
    end_by_quarter = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}
    return f"{year}{end_by_quarter[quarter - 1]}"


def _previous_year_period(end_date: str | None) -> str | None:
    if not end_date or len(str(end_date)) < 8:
        return None
    return f"{int(str(end_date)[:4]) - 1}{str(end_date)[4:]}"


def _single_quarter_value(
    cumulative_map: dict[str, dict[str, Any]],
    end_date: str,
    field: str,
) -> float | None:
    row = cumulative_map.get(end_date) or {}
    current = _safe_float(row.get(field))
    if current is None and field == "total_revenue":
        current = _safe_float(row.get("revenue"))
    if current is None:
        return None
    period = _period_quarter(end_date)
    if period is None:
        return current
    _, quarter = period
    if quarter == 1:
        return current
    prev_end_date = _prev_quarter_end_date(end_date)
    prev_row = cumulative_map.get(prev_end_date or "") or {}
    prev = _safe_float(prev_row.get(field))
    if prev is None and field == "total_revenue":
        prev = _safe_float(prev_row.get("revenue"))
    if prev is None:
        return None
    return current - prev


def _ratio(curr: float | None, prev: float | None) -> float | None:
    if curr is None or prev is None or prev == 0:
        return None
    return (curr - prev) / abs(prev)


def _build_quarter_facts(periods: dict[str, Any]) -> list[dict[str, Any]]:
    income_rows = periods.get("income_rows") or []
    cashflow_rows = periods.get("cashflow_rows") or []
    indicator_rows = periods.get("indicator_rows") or []
    income_by_period = {str(r["end_date"]): r for r in income_rows if r.get("end_date")}
    cashflow_by_period = {str(r["end_date"]): r for r in cashflow_rows if r.get("end_date")}
    indicator_by_period = {str(r["end_date"]): r for r in indicator_rows if r.get("end_date")}
    all_periods = sorted(
        set(income_by_period) | set(cashflow_by_period) | set(indicator_by_period),
        reverse=True,
    )
    facts: list[dict[str, Any]] = []
    single_by_period: dict[str, dict[str, Any]] = {}
    for end_date in all_periods:
        income = income_by_period.get(end_date) or {}
        cashflow = cashflow_by_period.get(end_date) or {}
        indicator = indicator_by_period.get(end_date) or {}
        fact = {
            "period": end_date,
            "quarter": _quarter_label(end_date),
            "available_date": income.get("available_date") or cashflow.get("available_date") or indicator.get("available_date"),
            "ann_date": income.get("ann_date") or cashflow.get("ann_date") or indicator.get("ann_date"),
            "revenue": _single_quarter_value(income_by_period, end_date, "total_revenue"),
            "gross_profit": _calc_gross_profit(income_by_period, end_date),
            "gross_margin": _pct_to_ratio(indicator.get("grossprofit_margin")),
            "parent_net_profit": _single_quarter_value(income_by_period, end_date, "n_income_attr_p"),
            "deducted_net_profit": (
                _safe_float(indicator.get("q_dtprofit"))
                if _safe_float(indicator.get("q_dtprofit")) is not None
                else _single_quarter_value(indicator_by_period, end_date, "profit_dedt")
            ),
            "operating_cashflow": _single_quarter_value(cashflow_by_period, end_date, "n_cashflow_act"),
            "source": {
                "income": bool(income),
                "cashflow": bool(cashflow),
                "indicator": bool(indicator),
            },
        }
        single_by_period[end_date] = fact

    for end_date in all_periods:
        fact = single_by_period[end_date]
        indicator = indicator_by_period.get(end_date) or {}
        previous_year_end = _previous_year_period(end_date)
        yoy_fact = single_by_period.get(previous_year_end or "")
        for field in ("revenue", "gross_profit", "parent_net_profit", "deducted_net_profit", "operating_cashflow"):
            fact[f"{field}_yoy"] = _ratio(_safe_float(fact.get(field)), _safe_float((yoy_fact or {}).get(field)))
        
        facts.append(fact)

    return facts


def _calc_gross_profit(income_by_period: dict[str, dict[str, Any]], end_date: str) -> float | None:
    revenue = _single_quarter_value(income_by_period, end_date, "total_revenue")
    cost = _single_quarter_value(income_by_period, end_date, "oper_cost")
    if revenue is None or cost is None:
        return None
    return revenue - cost


def _build_company_fact_tags(
    quarter_facts: list[dict[str, Any]],
    forecast: dict[str, Any],
    express: dict[str, Any],
) -> list[dict[str, Any]]:
    tags: list[dict[str, Any]] = []
    # 业绩预告不是永久有效的标签：如果预告公告早于当前最新财报公告，
    # 它可能对应上一财年，不能与最新季度经营事实并列展示。
    latest_report_ann = str((quarter_facts[0] if quarter_facts else {}).get("ann_date") or "")
    forecast_ann = str(forecast.get("available_date") or "")
    forecast_is_current = not latest_report_ann or not forecast_ann or forecast_ann >= latest_report_ann
    if forecast.get("type") and forecast_is_current:
        tags.append({
            "label": f"预告 {forecast.get('type')}",
            "tone": "INFO",
            "support": {
                "ann_date": forecast.get("available_date"),
                "p_change_min": _safe_float(forecast.get("p_change_min")),
                "p_change_max": _safe_float(forecast.get("p_change_max")),
                "net_profit_min": _safe_float(forecast.get("net_profit_min")),
                "net_profit_max": _safe_float(forecast.get("net_profit_max")),
            },
        })
    if express:
        tags.append({
            "label": "业绩快报已公告",
            "tone": "INFO",
            "support": {
                "period": express.get("end_date"),
                "ann_date": express.get("available_date"),
                "revenue": _safe_float(express.get("revenue")),
                "n_income": _safe_float(express.get("n_income")),
            },
        })
    if quarter_facts:
        latest = quarter_facts[0]
        prev = quarter_facts[1] if len(quarter_facts) > 1 else None
        same_period_last_year = _find_same_period_last_year(quarter_facts)
        latest_profit = _safe_float(latest.get("parent_net_profit"))
        year_ago_profit = _safe_float((same_period_last_year or {}).get("parent_net_profit"))
        if latest_profit is not None and year_ago_profit is not None:
            support = _comparison_support(latest, same_period_last_year, "parent_net_profit")
            if year_ago_profit < 0 <= latest_profit:
                tags.append({"label": "同比扭亏", "tone": "POSITIVE", "support": support})
            elif year_ago_profit >= 0 > latest_profit:
                tags.append({"label": "同比由盈转亏", "tone": "RISK", "support": support})
            elif latest_profit < 0 and year_ago_profit < 0 and latest_profit > year_ago_profit:
                tags.append({"label": "同比亏损收窄", "tone": "POSITIVE", "support": support})
            elif latest_profit < 0 and year_ago_profit < 0 and latest_profit < year_ago_profit:
                tags.append({"label": "同比亏损扩大", "tone": "RISK", "support": support})

        if prev:
            prev_profit = _safe_float(prev.get("parent_net_profit"))
            if latest_profit is not None and prev_profit is not None:
                support = _comparison_support(latest, prev, "parent_net_profit")
                if prev_profit < 0 <= latest_profit:
                    tags.append({"label": "环比由亏转盈", "tone": "INFO", "support": support})
                elif prev_profit >= 0 > latest_profit:
                    tags.append({"label": "环比由盈转亏", "tone": "INFO", "support": support})
                elif latest_profit < 0 and prev_profit < 0 and latest_profit > prev_profit:
                    tags.append({"label": "环比亏损收窄", "tone": "INFO", "support": support})
                elif latest_profit < 0 and prev_profit < 0 and latest_profit < prev_profit:
                    tags.append({"label": "环比亏损扩大", "tone": "INFO", "support": support})

        revenue_qoq = _safe_float(latest.get("revenue_qoq"))
        if revenue_qoq is not None and revenue_qoq >= 0.20:
            tags.append({"label": "收入环比增长", "tone": "INFO", "support": _tag_support(quarter_facts, "revenue", 3)})
        elif revenue_qoq is not None and revenue_qoq <= -0.20:
            tags.append({"label": "收入环比下降", "tone": "INFO", "support": _tag_support(quarter_facts, "revenue", 3)})

        cash_qoq = _safe_float(latest.get("operating_cashflow_qoq"))
        cash_latest = _safe_float(latest.get("operating_cashflow"))
        cash_year_ago = _safe_float((same_period_last_year or {}).get("operating_cashflow"))
        if cash_latest is not None and cash_year_ago is not None:
            support = _comparison_support(latest, same_period_last_year, "operating_cashflow")
            if cash_year_ago < 0 <= cash_latest:
                tags.append({"label": "现金流同比转正", "tone": "POSITIVE", "support": support})
            elif cash_year_ago >= 0 > cash_latest:
                tags.append({"label": "现金流同比转负", "tone": "RISK", "support": support})
        if prev:
            cash_prev = _safe_float(prev.get("operating_cashflow"))
            if cash_latest is not None and cash_prev is not None:
                support = _comparison_support(latest, prev, "operating_cashflow")
                if cash_prev < 0 <= cash_latest:
                    tags.append({"label": "现金流环比转正", "tone": "INFO", "support": support})
                elif cash_prev >= 0 > cash_latest:
                    tags.append({"label": "现金流环比转负", "tone": "INFO", "support": support})
        if cash_qoq is not None and cash_qoq >= 0.50:
            tags.append({"label": "现金流环比改善", "tone": "INFO", "support": _tag_support(quarter_facts, "operating_cashflow", 3)})

    return tags[:6]


def _tag_support(quarter_facts: list[dict[str, Any]], field: str, count: int) -> list[dict[str, Any]]:
    return [
        {
            "quarter": fact.get("quarter"),
            "period": fact.get("period"),
            "value": fact.get(field),
            "qoq": fact.get(f"{field}_qoq"),
            "yoy": fact.get(f"{field}_yoy"),
        }
        for fact in quarter_facts[:count]
    ]


def _find_same_period_last_year(quarter_facts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not quarter_facts:
        return None
    latest_period = str(quarter_facts[0].get("period") or "")
    if not re.fullmatch(r"\d{8}", latest_period):
        return None
    target_period = f"{int(latest_period[:4]) - 1}{latest_period[4:]}"
    return next((fact for fact in quarter_facts[1:] if str(fact.get("period") or "") == target_period), None)


def _comparison_support(latest: dict[str, Any], comparison: dict[str, Any] | None, field: str) -> list[dict[str, Any]]:
    return [
        {
            "quarter": fact.get("quarter"),
            "period": fact.get("period"),
            "value": fact.get(field),
            "yoy": fact.get(f"{field}_yoy"),
        }
        for fact in (latest, comparison or {})
        if fact
    ]


def _build_company_data_quality(periods: dict[str, Any], quarter_facts: list[dict[str, Any]]) -> dict[str, Any]:
    missing_fields: list[str] = []
    if not periods.get("income_rows"):
        missing_fields.append("income_vip")
    if not periods.get("cashflow_rows"):
        missing_fields.append("cashflow_vip")
    if not periods.get("indicator_rows"):
        missing_fields.append("fina_indicator_vip")
    if not periods.get("forecast"):
        missing_fields.append("forecast_vip")
    if not periods.get("express"):
        missing_fields.append("express_vip")
    if quarter_facts and all(f.get("deducted_net_profit") is None for f in quarter_facts):
        missing_fields.append("deducted_net_profit_amount")
    if quarter_facts and all(f.get("gross_profit") is None for f in quarter_facts):
        missing_fields.append("gross_profit_amount")
    return {
        "quarter_count": len(quarter_facts),
        "latest_period": quarter_facts[0].get("period") if quarter_facts else None,
        "missing_fields": missing_fields,
        "notes": [
            "单季度营收、毛利、归母净利润、扣非净利润、经营现金流由 Tushare 累计报告按季度差分重建",
        ],
    }


def _determine_profit_state(curr: float | None, last: float | None, yoy: float | None) -> str:
    if curr is None or last is None:
        if yoy is not None:
            return "PROFIT_GROWING" if yoy > 0 else "PROFIT_DECLINING"
        return "UNKNOWN"

    if last < 0:
        if curr >= 0:
            return "TURNAROUND"
        elif curr > last:
            return "LOSS_NARROWING"
        else:
            return "LOSS_WIDENING"
    else:
        if curr < 0:
            return "TURN_TO_LOSS"
        elif curr >= last:
            return "PROFIT_GROWING"
        else:
            return "PROFIT_DECLINING"


def compute_theme_relative_facts(
    store: PostgresScreeningStore,
    ts_code: str,
    as_of_date: str,
    theme_name: str,
    lookback_days: int = 15,
) -> dict[str, Any] | None:
    """
    计算程序客观主题对比事实 (Theme-relative Facts)
    在 AI-2 命中具体主题后调用。
    全量获取同花顺概念底库全市场成员，计算本轮观察起点以来的涨幅排名与成交额排名。
    """
    if not theme_name:
        return None

    with store.connect() as conn:
        # 1. 查找主题成员股票。Market Memory 的主题名与 THS 规范名称
        # 不是同一套词表，例如“农业/种业”对应“生猪养殖、猪肉、养殖业”等。
        # 先完整读取当日快照中的主题标签，再按显式词表归一化匹配。
        theme_terms = _theme_concept_terms(theme_name)
        if not theme_terms:
            return None
        concept_rows = conn.execute(
            """
            SELECT DISTINCT m.ts_code, coalesce(c.name, m.ths_name) AS concept_name
            FROM ths_concept_member_snapshot m
            LEFT JOIN ths_index_master c ON m.ths_code = c.ths_code
            WHERE m.snapshot_date = (
                SELECT max(snapshot_date) FROM ths_concept_member_snapshot WHERE snapshot_date <= %s
            )
            """,
            (as_of_date,),
        ).fetchall()
        matched_codes = {
            row["ts_code"]
            for row in concept_rows
            if any(
                term in str(row["concept_name"] or "")
                or str(row["concept_name"] or "") in term
                for term in theme_terms
            )
        }
        member_codes = sorted(matched_codes)
        if not member_codes:
            member_codes = [ts_code]
        elif ts_code not in member_codes:
            member_codes.append(ts_code)

        if len(member_codes) <= 1:
            return None

        # 2. 查询 as_of_date 的近 lookback_days 交易日至今各股票的涨幅与成交额
        start_row = conn.execute(
            """
            SELECT DISTINCT trade_date
            FROM screening_daily_bar
            WHERE trade_date <= %s
            ORDER BY trade_date DESC
            LIMIT %s
            """,
            (as_of_date, lookback_days),
        ).fetchall()

        if not start_row:
            return None

        start_date = start_row[-1]["trade_date"]

        stats = conn.execute(
            """
            WITH start_prices AS (
                SELECT asset_code AS ts_code, close as start_close
                FROM screening_daily_bar
                WHERE trade_date = %s AND asset_code = ANY(%s)
            ),
            end_prices AS (
                SELECT asset_code AS ts_code, close as end_close, amount as end_amount
                FROM screening_daily_bar
                WHERE trade_date = %s AND asset_code = ANY(%s)
            ),
            avg_amounts AS (
                SELECT ts_code, AVG(amount) as avg_amount_5d
                FROM (
                    SELECT asset_code AS ts_code, amount,
                           ROW_NUMBER() OVER (PARTITION BY asset_code ORDER BY trade_date DESC) as rn
                    FROM screening_daily_bar
                    WHERE trade_date <= %s AND asset_code = ANY(%s)
                ) sub
                WHERE rn <= 5
                GROUP BY ts_code
            )
            SELECT e.ts_code,
                   s.start_close,
                   e.end_close,
                   CASE WHEN s.start_close > 0 THEN (e.end_close - s.start_close) / s.start_close ELSE 0 END as pct_change,
                   a.avg_amount_5d
            FROM end_prices e
            LEFT JOIN start_prices s ON e.ts_code = s.ts_code
            LEFT JOIN avg_amounts a ON e.ts_code = a.ts_code
            """,
            (start_date, member_codes, as_of_date, member_codes, as_of_date, member_codes),
        ).fetchall()

        if not stats:
            return None

        df = pd.DataFrame([dict(r) for r in stats])
        if df.empty or ts_code not in df["ts_code"].values:
            return None

        df["pct_rank"] = df["pct_change"].rank(ascending=False, method="min").astype(int)
        df["amount_rank"] = df["avg_amount_5d"].rank(ascending=False, method="min").astype(int)

        target_row = df[df["ts_code"] == ts_code].iloc[0]

        return {
            "theme_name": theme_name,
            "start_date": start_date,
            "as_of_date": as_of_date,
            "total_members": len(df),
            "stock_pct_change": round(float(target_row["pct_change"]) * 100, 2),
            "pct_rank": int(target_row["pct_rank"]),
            "avg_amount_5d_yi": round(float(target_row["avg_amount_5d"] or 0) / 100000000.0, 2),
            "amount_rank": int(target_row["amount_rank"]),
            "notice": "仅为截至当前市场已留下的客观比较数据，非自动选股预测结论。"
        }
