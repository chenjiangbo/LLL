from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from openai import OpenAI
from backend.screening.market_memory_service import get_cached_market_memory, get_or_create_market_memory
from backend.screening.secondary_eval_engine import (
    compute_theme_relative_facts,
    evaluate_single_secondary_candidate,
)
from backend.screening.storage import PostgresScreeningStore
from backend.screening.theme_match_service import match_stock_theme
from backend.screening.ths_concept_service import get_stock_ths_concepts
from backend.screening.review_knowledge_base import (
    format_review_evidence_for_prompt,
    retrieve_review_evidence,
)


def _json_safe(value: Any) -> Any:
    """将数据库返回的 Decimal/日期递归转换为 JSON 原生类型，保持数值语义。"""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _usage_from_response(response: Any, elapsed_ms: int, web_search: bool) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "reasoning_tokens": int(getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0) or 0),
        "elapsed_ms": elapsed_ms,
        "web_search": web_search,
        "reasoning": "none",
    }


def run_ai_stock_research(
    store: PostgresScreeningStore,
    ts_code: str,
    as_of_date: str,
    review_lookback: int = 120,
    use_web_search: bool = True,
) -> dict[str, Any]:
    """
    三阶段 AI 解耦二次研究总编排 (符合 V1.0 架构优化方案):
    1. AI-1: 提取或调取共享 Market Memory 市场长期记忆;
    2. AI-2: 运行 Theme Match 判断股票与哪被真实交易的主题匹配 (或 NO_ACTIVE_THEME_MATCH);
    3. 程序: 若命中主题，计算 Theme-relative Facts 全市场客观对比事实;
    4. AI-3: Final Research 运行最终二次研究，输出 10 维 Markdown 报告与研究优先级。
    """
    research_started = time.perf_counter()
    # -------------------------------------------------------------
    # 阶段 1: Market Memory 共享市场长期记忆 (AI-1)
    # -------------------------------------------------------------
    market_memory_json, market_memory_summary = get_or_create_market_memory(
        store, as_of_date, lookback_sessions=review_lookback
    )

    # -------------------------------------------------------------
    # 提取基础数据与快照事实
    # -------------------------------------------------------------
    sec_snap, evidence, leadership, supply = evaluate_single_secondary_candidate(store, ts_code, as_of_date)
    concepts_info = get_stock_ths_concepts(store, ts_code, as_of_date)

    # K 线真实基础数据
    kline_facts = _fetch_stock_kline_facts(store, ts_code, as_of_date, limit=25)

    # M1 股票知识库结构
    stock_knowledge = {
        "ts_code": ts_code,
        "stock_name": _load_stock_name(store, ts_code),
        "industry": evidence.get("industry"),
        "main_business": evidence.get("main_business"),
        "ths_concepts": [c["ths_name"] for c in concepts_info.get("concepts", [])],
        "concept_temporal_status": concepts_info.get("temporal_status", "PIT_SAFE"),
    }

    quarterly_facts_brief = _json_safe({
        "quarter_facts": evidence.get("quarter_facts_json", []),
        "forecast": {
            "type": evidence.get("forecast_type"),
            "ann_date": evidence.get("forecast_ann_date"),
            "net_profit_min": evidence.get("forecast_net_profit_min"),
            "net_profit_max": evidence.get("forecast_net_profit_max"),
        },
        "express": {
            "end_date": evidence.get("express_end_date"),
            "ann_date": evidence.get("express_ann_date"),
            "revenue": evidence.get("express_revenue"),
            "n_income": evidence.get("express_n_income"),
        },
    })
    financial_comparison_facts = _build_financial_comparison_facts(
        list(quarterly_facts_brief.get("quarter_facts") or [])
    )
    supply = _json_safe(supply)

    # -------------------------------------------------------------
    # 阶段 2: Theme Match (AI-2)
    # -------------------------------------------------------------
    stock_basic_info = {
        "ts_code": ts_code,
        "as_of_date": as_of_date,
        "close": kline_facts.get("latest_close"),
    }

    saved_theme_match = store.get_ai_stock_theme_match(ts_code, as_of_date)
    if not saved_theme_match:
        raise RuntimeError("请先完成主题匹配，再开始 AI 分析")
    theme_match_result = saved_theme_match.get("result_json") or {}
    if isinstance(theme_match_result, str):
        theme_match_result = json.loads(theme_match_result)
    theme_match_result = dict(theme_match_result)
    theme_match_result["_ai_usage"] = {
        "input_tokens": int(saved_theme_match.get("input_tokens") or 0),
        "output_tokens": int(saved_theme_match.get("output_tokens") or 0),
        "total_tokens": int(saved_theme_match.get("total_tokens") or 0),
        "elapsed_ms": int(saved_theme_match.get("elapsed_ms") or 0),
        "web_search": False,
        "reasoning": "none",
    }
    # AI 只能从真实同花顺概念标签中选择匹配项；不接受自行创造的主题名称。
    allowed_ths_concepts = set(stock_knowledge.get("ths_concepts") or [])
    theme_match_result["matched_ths_concepts"] = [
        name for name in (theme_match_result.get("matched_ths_concepts") or [])
        if isinstance(name, str) and name in allowed_ths_concepts
    ]

    # -------------------------------------------------------------
    # 阶段 3: 程序全市场 Theme-relative Facts 计算
    # -------------------------------------------------------------
    primary_theme = theme_match_result.get("primary_active_theme")
    no_theme_match = theme_match_result.get("no_active_theme_match", True)

    theme_relative_facts = None
    if not no_theme_match and primary_theme:
        theme_relative_facts = compute_theme_relative_facts(
            store=store,
            ts_code=ts_code,
            as_of_date=as_of_date,
            theme_name=primary_theme,
            lookback_days=15,
        )

    # -------------------------------------------------------------
    # 4: 原始复盘证据检索。Market Memory 是摘要，不能替代每日复盘原文。
    # -------------------------------------------------------------
    evidence_terms = [
        ts_code,
        stock_knowledge.get("stock_name"),
        stock_knowledge.get("ths_concepts", []),
        primary_theme,
        theme_match_result.get("secondary_active_themes", []),
    ]
    review_evidence = retrieve_review_evidence(store, as_of_date, evidence_terms)

    # -------------------------------------------------------------
    # 阶段 5: Final Research 最终二次研究 (AI-3)
    # -------------------------------------------------------------
    theme_usage = theme_match_result.pop("_ai_usage", {})
    final_result = _call_ai3_final_research(
        store=store,
        ts_code=ts_code,
        as_of_date=as_of_date,
        market_memory_summary=market_memory_summary,
        market_memory_json=market_memory_json,
        review_evidence=review_evidence,
        theme_match_result=theme_match_result,
        kline_facts=kline_facts,
        quarterly_facts=quarterly_facts_brief,
        financial_comparison_facts=financial_comparison_facts,
        stock_knowledge=stock_knowledge,
        supply_snap=supply,
        theme_relative_facts=theme_relative_facts,
        use_web_search=use_web_search,
    )
    if len(final_result) == 4:
        markdown_report, priority, uncertainties, model_used = final_result
        final_usage = {}
    else:
        markdown_report, priority, uncertainties, model_used, final_usage = final_result
    ai_usage = {
        "stages": {"theme_match": theme_usage, "final_research": final_usage},
        "input_tokens": int(theme_usage.get("input_tokens", 0)) + int(final_usage.get("input_tokens", 0)),
        "output_tokens": int(theme_usage.get("output_tokens", 0)) + int(final_usage.get("output_tokens", 0)),
        "total_tokens": int(theme_usage.get("total_tokens", 0)) + int(final_usage.get("total_tokens", 0)),
        "reasoning_tokens": int(theme_usage.get("reasoning_tokens", 0)) + int(final_usage.get("reasoning_tokens", 0)),
        "model_elapsed_ms": int(theme_usage.get("elapsed_ms", 0)) + int(final_usage.get("elapsed_ms", 0)),
        "elapsed_ms": round((time.perf_counter() - research_started) * 1000),
        "web_search": use_web_search,
        "reasoning": "none",
    }

    # -------------------------------------------------------------
    # 5. 持久化存储结果至 Postgres
    # -------------------------------------------------------------
    analysis_id = f"AIR_{ts_code}_{as_of_date}_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)

    source_manifest = _json_safe({
        "as_of_date": as_of_date,
        "theme_match": theme_match_result,
        "theme_relative_facts": theme_relative_facts,
        "review_evidence": {
            "status": review_evidence.get("status"),
            "terms": review_evidence.get("terms", []),
            "document_count": review_evidence.get("document_count", 0),
            "trade_dates": [d.get("trade_date") for d in review_evidence.get("documents", [])],
        },
        "actual_lookback_sessions": market_memory_json.get("actual_lookback_sessions", review_lookback),
    })

    record = {
        "analysis_id": analysis_id,
        "ts_code": ts_code,
        "as_of_date": as_of_date,
        "created_at": now,
        "priority": priority,
        "result_markdown": markdown_report,
        "model": model_used,
        "prompt_version": "v1.1_fact_constrained",
        "review_lookback_days": review_lookback,
        "aprev2_snapshot_id": f"{as_of_date}_{ts_code}",
        "company_snapshot_id": f"{as_of_date}_{ts_code}",
        "leadership_snapshot_id": f"{as_of_date}_{ts_code}",
        "supply_snapshot_id": f"{as_of_date}_{ts_code}",
        "concept_snapshot_date": concepts_info.get("snapshot_date"),
        "concept_temporal_status": concepts_info.get("temporal_status", "PIT_SAFE"),
        "web_search_used": use_web_search,
        "source_manifest_json": json.dumps(source_manifest, ensure_ascii=False),
        "uncertainty_json": json.dumps(_json_safe(uncertainties), ensure_ascii=False),
        "ai_usage_json": json.dumps(_json_safe(ai_usage), ensure_ascii=False),
        "ai_input_tokens": ai_usage["input_tokens"],
        "ai_output_tokens": ai_usage["output_tokens"],
        "ai_total_tokens": ai_usage["total_tokens"],
        "ai_elapsed_ms": ai_usage["elapsed_ms"],
        "status": "READY",
    }

    with store.connect() as conn:
        conn.execute(
            """
            INSERT INTO ai_stock_research (
                analysis_id, ts_code, as_of_date, created_at, priority, result_markdown,
                model, prompt_version, review_lookback_days, aprev2_snapshot_id,
                company_snapshot_id, leadership_snapshot_id, supply_snapshot_id,
                concept_snapshot_date, concept_temporal_status, web_search_used,
                source_manifest_json, uncertainty_json, ai_usage_json,
                ai_input_tokens, ai_output_tokens, ai_total_tokens, ai_elapsed_ms, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s)
            ON CONFLICT (analysis_id) DO UPDATE SET
                result_markdown = EXCLUDED.result_markdown,
                priority = EXCLUDED.priority,
                status = EXCLUDED.status,
                source_manifest_json = EXCLUDED.source_manifest_json,
                uncertainty_json = EXCLUDED.uncertainty_json,
                ai_usage_json = EXCLUDED.ai_usage_json,
                ai_input_tokens = EXCLUDED.ai_input_tokens,
                ai_output_tokens = EXCLUDED.ai_output_tokens,
                ai_total_tokens = EXCLUDED.ai_total_tokens,
                ai_elapsed_ms = EXCLUDED.ai_elapsed_ms
            """,
            (
                record["analysis_id"],
                record["ts_code"],
                record["as_of_date"],
                record["created_at"],
                record["priority"],
                record["result_markdown"],
                record["model"],
                record["prompt_version"],
                record["review_lookback_days"],
                record["aprev2_snapshot_id"],
                record["company_snapshot_id"],
                record["leadership_snapshot_id"],
                record["supply_snapshot_id"],
                record["concept_snapshot_date"],
                record["concept_temporal_status"],
                record["web_search_used"],
                record["source_manifest_json"],
                record["uncertainty_json"],
                record["ai_usage_json"],
                record["ai_input_tokens"],
                record["ai_output_tokens"],
                record["ai_total_tokens"],
                record["ai_elapsed_ms"],
                record["status"],
            ),
        )
        conn.commit()

    return record


def get_ai_stock_research_result(
    store: PostgresScreeningStore,
    ts_code: str,
    as_of_date: str,
) -> dict[str, Any] | None:
    """获取股票在指定交易日的 AI 深度研究结果记录。"""
    with store.connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM ai_stock_research
            WHERE ts_code = %s AND as_of_date = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (ts_code, as_of_date),
        ).fetchone()
    return dict(row) if row else None


def _build_financial_comparison_facts(quarter_facts: list[dict[str, Any]]) -> dict[str, Any]:
    """从原始季度数据生成可审计的环比、同比对照，不引用基本面模块的结论标签。"""
    latest = quarter_facts[0] if quarter_facts else {}
    latest_period = str(latest.get("period") or "")
    previous_quarter = quarter_facts[1] if len(quarter_facts) > 1 else None
    same_period_last_year = None
    if re.fullmatch(r"\d{8}", latest_period):
        target_period = f"{int(latest_period[:4]) - 1}{latest_period[4:]}"
        same_period_last_year = next(
            (fact for fact in quarter_facts[1:] if str(fact.get("period") or "") == target_period),
            None,
        )

    def comparison(field: str) -> dict[str, Any]:
        current = latest.get(field)
        qoq = previous_quarter.get(field) if previous_quarter else None
        yoy = same_period_last_year.get(field) if same_period_last_year else None
        return {
            "current": current,
            "previous_quarter": qoq,
            "same_period_last_year": yoy,
            "qoq_sign_change": _sign_change_label(qoq, current),
            "yoy_sign_change": _sign_change_label(yoy, current),
            "qoq_change_ratio": latest.get(f"{field}_qoq"),
            "yoy_change_ratio": latest.get(f"{field}_yoy"),
        }

    return {
        "latest_period": latest_period or None,
        "previous_quarter_period": previous_quarter.get("period") if previous_quarter else None,
        "same_period_last_year_period": same_period_last_year.get("period") if same_period_last_year else None,
        "revenue": comparison("revenue"),
        "parent_net_profit": comparison("parent_net_profit"),
        "deducted_net_profit": comparison("deducted_net_profit"),
        "operating_cashflow": comparison("operating_cashflow"),
    }


def run_ai_stock_theme_match(
    store: PostgresScreeningStore,
    ts_code: str,
    as_of_date: str,
) -> dict[str, Any]:
    """独立执行主题匹配，不联网，也不读取复盘原文或行情技术序列。"""
    normalized_code = ts_code.strip().upper()
    normalized_date = str(as_of_date).strip().replace("-", "")
    memory = get_cached_market_memory(store, normalized_date)
    if memory is None:
        raise RuntimeError("当前查看日尚未生成市场主题记忆，请先导入该日复盘并生成市场全景")
    market_memory_json, _ = memory
    concepts_info = get_stock_ths_concepts(store, normalized_code, normalized_date)
    with store.connect() as conn:
        profile = conn.execute(
            "select name, raw_json->>'main_business' as main_business, raw_json->>'industry' as industry "
            "from screening_asset_master where asset_code = %s",
            (normalized_code,),
        ).fetchone()
    stock_knowledge = {
        "ts_code": normalized_code,
        "stock_name": _load_stock_name(store, normalized_code),
        "industry": (profile or {}).get("industry"),
        "main_business": (profile or {}).get("main_business"),
        "ths_concepts": [c["ths_name"] for c in concepts_info.get("concepts", [])],
        "concept_temporal_status": concepts_info.get("temporal_status", "PIT_SAFE"),
    }
    result = match_stock_theme(
        store=store,
        ts_code=normalized_code,
        as_of_date=normalized_date,
        market_memory=market_memory_json,
        stock_knowledge=stock_knowledge,
        use_web_search=False,
    )
    usage = result.pop("_ai_usage", {})
    now = datetime.now(UTC)
    store.save_ai_stock_theme_match({
        "ts_code": normalized_code,
        "as_of_date": normalized_date,
        "created_at": now,
        "model": os.getenv("AI_BASE_MODEL", "").strip() or os.getenv("AI_BASE_OPENAI_MODEL", "").strip() or "qwen3.8-max",
        "result_json": json.dumps(_json_safe(result), ensure_ascii=False),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "elapsed_ms": usage.get("elapsed_ms", 0),
        "web_search_used": False,
        "status": "READY",
    })
    return {"result": result, "usage": usage, "as_of_date": normalized_date, "ts_code": normalized_code}


def _sign_change_label(previous: Any, current: Any) -> str | None:
    try:
        previous_value = float(previous)
        current_value = float(current)
    except (TypeError, ValueError):
        return None
    if previous_value < 0 <= current_value:
        return "由负转正"
    if previous_value >= 0 > current_value:
        return "由正转负"
    return "同为正值" if current_value >= 0 else "同为负值"


def _load_stock_name(store: PostgresScreeningStore, ts_code: str) -> str | None:
    """从本地资产主表读取股票名称；名称缺失必须显式保留为空。"""
    with store.connect() as conn:
        row = conn.execute(
            "select name from screening_asset_master where asset_code = %s",
            (ts_code,),
        ).fetchone()
    return row["name"] if row else None


def _fetch_stock_kline_facts(
    store: PostgresScreeningStore,
    ts_code: str,
    as_of_date: str,
    limit: int = 25,
) -> dict[str, Any]:
    """提取近 limit 个交易日真实 K 线与均线基础数据"""
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT trade_date, open, high, low, close, pct_chg, amount
            FROM screening_daily_bar
            WHERE asset_code = %s AND trade_date <= %s
            ORDER BY trade_date DESC
            LIMIT %s
            """,
            (ts_code, as_of_date, limit),
        ).fetchall()

    if not rows:
        return {"price_table": [], "latest_close": None, "ma": {}}

    bars = [dict(r) for r in reversed(rows)]
    latest = bars[-1]

    closes = [float(b["close"]) for b in bars if b.get("close") is not None]

    def calc_ma(n: int) -> float | None:
        return round(sum(closes[-n:]) / float(n), 2) if len(closes) >= n else None

    ma = {
        "MA5": calc_ma(5),
        "MA10": calc_ma(10),
        "MA20": calc_ma(20),
        "MA30": calc_ma(30),
    }

    price_table = [
        {
            "date": b["trade_date"],
            "close": b["close"],
            "pct_chg": b["pct_chg"],
            "amount_yi": round(float(b["amount"] or 0) / 10000.0, 2),
        }
        for b in bars
    ]

    return {"price_table": price_table, "latest_close": latest["close"], "ma": ma}


def _call_ai3_final_research(
    store: PostgresScreeningStore,
    ts_code: str,
    as_of_date: str,
    market_memory_summary: str,
    market_memory_json: dict[str, Any],
    review_evidence: dict[str, Any],
    theme_match_result: dict[str, Any],
    kline_facts: dict[str, Any],
    quarterly_facts: dict[str, Any],
    financial_comparison_facts: dict[str, Any],
    stock_knowledge: dict[str, Any],
    supply_snap: dict[str, Any],
    theme_relative_facts: dict[str, Any] | None,
    use_web_search: bool,
) -> tuple[str, str, list[str], str, dict[str, Any]]:
    """
    AI-3: Final Research (最终二次研究)
    完全不传 A-PreV2 综合分数或算法打分标签，给原始基础事实。
    模拟多年经验的主观交易研究员做二次研究。
    """
    system_prompt = """你是一名有多年中国 A 股实战经验的主观交易研究员。
你现在做的不是技术选股，也不是预测明天涨跌。
这只股票已经通过了一套独立的技术初筛。你的任务是做“二次研究”，判断它是否值得在当前市场环境下被优先投入更多研究时间。

你的思考方式要接近真实专业交易者，而不是量化打分模型：
1. 综合理解最近几个月市场真正交易过哪些主题，资金如何迁移；
2. 这只股票是否真正属于其中某个活跃或近期活跃主题；
3. 如果属于主题，市场截至目前已经如何对待它；
4. 如果不属于当前主题，它是否可能处于尚未形成市场共识的新修复方向；
5. 公司最近几个季度是否出现值得市场重新定价的实际变化；
6. 股票的市值、成交额和换手意味着它更可能以什么方式被资金交易；
7. 为什么资金可能选择它，为什么资金也可能不选择它。

重要规则：
- 不要使用加权打分思维。
- Theme-relative 数据只是辅助参考证据，不是决策规则。
- 不要因为没有命中近期主线就自动判低优先级。对早期反转股票，“尚无主题共识”可能意味着新方向。
- 不得使用 as_of_date 之后的信息判断当时机会。
- 最终研究优先级只能是：高 / 中 / 低 / 证据不足。
- 所有财务判断必须同时区分“环比”和“同比”。环比由负转正不等于同比扭亏；去年同期已盈利而本期利润下降时，必须表述为“同比利润下降”。
- 如 Theme Match 已命中主题，不能称“没有产业/主题催化”；可以判断该主题不足以构成公司独立的中线催化，但必须明确这是判断而非事实缺失。
- 禁止使用“没有任何业绩变量”“纯粹情绪交易”等绝对表述，除非输入事实同时不含经营变化与主题催化。对每项结论说明所依据的事实和你的判断。
"""

    price_table_text = json.dumps(_json_safe(kline_facts.get("price_table", [])), ensure_ascii=False)
    ma_text = json.dumps(_json_safe(kline_facts.get("ma", {})), ensure_ascii=False)
    quarterly_text = json.dumps(_json_safe(quarterly_facts), ensure_ascii=False)
    financial_comparison_text = json.dumps(_json_safe(financial_comparison_facts), ensure_ascii=False)
    theme_match_text = json.dumps(_json_safe(theme_match_result), ensure_ascii=False)
    capital_flows_text = json.dumps(_json_safe(market_memory_json.get("capital_flows", [])), ensure_ascii=False)
    review_evidence_text = format_review_evidence_for_prompt(review_evidence)
    theme_relative_text = json.dumps(_json_safe(theme_relative_facts), ensure_ascii=False) if theme_relative_facts else "无 (未命中活跃主题或数据不足)"

    user_prompt = f"""查看日期：{as_of_date}
股票代码：{ts_code}

说明：
该股票已经通过独立技术初筛。请不要参考任何技术总分，直接根据下面的基础事实做二次研究。

====================
一、市场长期记忆 (Market Memory)
====================
{market_memory_summary}

结构化资金脉络：
{capital_flows_text}

====================
二、相关每日复盘原文证据
====================
以下内容来自查看日及之前已经保存的复盘原文。它们是详细事实证据，不是自动结论。
{review_evidence_text}

====================
三、股票与市场主题匹配 (Theme Match)
====================
{theme_match_text}

注意：如果结果为 NO_ACTIVE_THEME_MATCH，不要自动视为负面。请考虑它是否可能属于尚未形成市场共识的新修复方向。

====================
四、股票最近技术事实
====================
当前价格：{kline_facts.get('latest_close')}
均线体系：{ma_text}
最近20~30个交易日价格/成交：
{price_table_text}

====================
五、公司最近季度基础事实
====================
{quarterly_text}

公司季度环比 / 同比对照（由上述原始季度数值直接计算，不是结论标签）
{financial_comparison_text}

====================
六、公司业务与主题知识 (M1 知识库)
====================
{json.dumps(_json_safe(stock_knowledge), ensure_ascii=False)}

====================
七、市场画像
====================
自由流通市值：{supply_snap.get('free_float_mv')} 亿元
当前成交额：{supply_snap.get('amount')}
20日成交额中位数：{supply_snap.get('amount_median_20')}
换手率：{supply_snap.get('turnover_rate')} %
自由流通换手率：{supply_snap.get('turnover_rate_f')} %

====================
八、主题内客观比较 (Theme-relative Facts)
====================
{theme_relative_text}

请按以下格式输出分析报告：

# 研究结论

研究优先级：高 / 中 / 低 / 证据不足

一句话结论：

## 1. 市场环境与主题关系
## 2. 公司与主题的真实关系
## 3. 公司最近发生了什么
## 4. 市场已经如何对待这只股票
## 5. 为什么资金可能选择它
## 6. 为什么资金可能不选择它
## 7. 与同类机会相比
## 8. 最大反证
## 9. 不确定性
## 10. 最终研究意见
(重点研究 / 保留观察 / 暂不优先)
"""

    api_key = (
        os.getenv("DASHSCOPE_API_KEY", "").strip()
        or os.getenv("AI_BASE_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
    )
    if not api_key:
        raise RuntimeError("未在 .env 中配置 DASHSCOPE_API_KEY")

    base_url = (
        os.getenv("AI_BASE_BASE_URL", "").strip()
        or os.getenv("DASHSCOPE_BASE_URL", "").strip()
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    model = (
        os.getenv("AI_RESEARCH_MODEL", "").strip()
        or os.getenv("AI_BASE_MODEL", "").strip()
        or os.getenv("AI_BASE_OPENAI_MODEL", "").strip()
        or "qwen3.8-max"
    )

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=180.0,
    )

    tools = [{"type": "web_search"}] if use_web_search else None
    started = time.perf_counter()
    response = client.responses.create(
        model=model,
        instructions=system_prompt,
        input=user_prompt,
        tools=tools,
        reasoning={"effort": "none"},
    )

    report = getattr(response, "output_text", None)
    if not (isinstance(report, str) and report.strip()):
        output_items = getattr(response, "output", []) or []
        chunks: list[str] = []
        for item in output_items:
            item_dict = item if isinstance(item, dict) else (item.model_dump() if hasattr(item, "model_dump") else {})
            if item_dict.get("type") == "message":
                for content in item_dict.get("content", []) or []:
                    c_dict = content if isinstance(content, dict) else (content.model_dump() if hasattr(content, "model_dump") else {})
                    if c_dict.get("type") in {"output_text", "text"} and c_dict.get("text"):
                        chunks.append(str(c_dict["text"]))
        report = "\n".join(chunks).strip() if chunks else ""

    if not report:
        raise RuntimeError("百炼 Responses API 未返回有效内容")

    # 解析优先级 (高 / 中 / 低 / 证据不足)
    priority = "证据不足"
    match = re.search(r"研究优先级[：:\s\*`]*([高中低]|证据不足)", report)
    if match:
        priority = match.group(1)

    # 解析不确定性列表
    uncertainties: list[str] = []
    in_uncertainty_section = False
    for line in report.splitlines():
        stripped = line.strip()
        if "9. 不确定性" in stripped or ("不确定性" in stripped and stripped.startswith("#")):
            in_uncertainty_section = True
            continue
        if in_uncertainty_section:
            if stripped.startswith("#"):
                break
            if stripped.startswith(("-", "*", "1.", "2.", "3.", "4.", "5.")):
                item_text = stripped.lstrip("-*123456789. ").strip()
                if item_text:
                    uncertainties.append(item_text)

    return report, priority, uncertainties, model, _usage_from_response(
        response, round((time.perf_counter() - started) * 1000), use_web_search
    )
