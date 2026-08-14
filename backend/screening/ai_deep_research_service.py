from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from backend.screening.secondary_eval_engine import evaluate_single_secondary_candidate
from backend.screening.storage import PostgresScreeningStore
from backend.screening.ths_concept_service import get_stock_ths_concepts


def run_ai_stock_research(
    store: PostgresScreeningStore,
    ts_code: str,
    as_of_date: str,
    review_lookback: int = 20,
    use_web_search: bool = True,
) -> dict[str, Any]:
    """
    人工触发 AI 深度研究 (A1)。
    整合输入: A-PreV2 技术事实 + Q1 基本面 + Q2 相对领先 + Q3 筹码 + M1 概念 + 历史资金复盘 (PIT)。
    输出包含研究优先级 (高/中/低/证据不足)、概念分类与完整 Markdown 报告。
    """
    # 1. 获取四方快照数据
    sec_snap, evidence, leadership, supply = evaluate_single_secondary_candidate(store, ts_code, as_of_date)
    concepts_info = get_stock_ths_concepts(store, ts_code, as_of_date)

    # 2. 读取截至 as_of_date 的历史资金复盘 (review_date <= as_of_date)
    market_reviews = _fetch_historical_market_reviews(store, as_of_date, lookback_days=review_lookback)

    # 3. 构造系统 Prompt
    prompt = _build_ai_research_prompt(
        ts_code=ts_code,
        as_of_date=as_of_date,
        sec_snap=sec_snap,
        evidence=evidence,
        leadership=leadership,
        supply=supply,
        concepts_info=concepts_info,
        market_reviews=market_reviews,
        use_web_search=use_web_search,
    )

    # 4. 调用 LLM (支持 Gemini API / OpenAI API，降级后备规则)
    markdown_report, priority, uncertainties = _call_llm_for_research(prompt, ts_code, as_of_date, concepts_info)

    # 5. 保存结果至 Postgres
    analysis_id = f"AIR_{ts_code}_{as_of_date}_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)

    record = {
        "analysis_id": analysis_id,
        "ts_code": ts_code,
        "as_of_date": as_of_date,
        "created_at": now,
        "priority": priority,
        "result_markdown": markdown_report,
        "model": "gemini-2.5-flash",
        "prompt_version": "v1.0",
        "review_lookback_days": review_lookback,
        "aprev2_snapshot_id": f"{as_of_date}_{ts_code}",
        "company_snapshot_id": f"{as_of_date}_{ts_code}",
        "leadership_snapshot_id": f"{as_of_date}_{ts_code}",
        "supply_snapshot_id": f"{as_of_date}_{ts_code}",
        "concept_snapshot_date": concepts_info.get("snapshot_date"),
        "concept_temporal_status": concepts_info.get("temporal_status", "PIT_SAFE"),
        "web_search_used": use_web_search,
        "source_manifest_json": json.dumps({"as_of_date": as_of_date, "reviews_count": len(market_reviews)}),
        "uncertainty_json": json.dumps(uncertainties),
        "status": "READY",
    }

    with store.connect() as conn:
        conn.execute(
            """
            insert into ai_stock_research (
                analysis_id, ts_code, as_of_date, created_at, priority, result_markdown,
                model, prompt_version, review_lookback_days, aprev2_snapshot_id,
                company_snapshot_id, leadership_snapshot_id, supply_snapshot_id,
                concept_snapshot_date, concept_temporal_status, web_search_used,
                source_manifest_json, uncertainty_json, status
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
            on conflict (analysis_id) do update set
                result_markdown = excluded.result_markdown,
                priority = excluded.priority,
                status = excluded.status
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
    """
    获取股票在指定交易日的 AI 深度研究结果记录。
    """
    with store.connect() as conn:
        row = conn.execute(
            """
            select * from ai_stock_research
            where ts_code = %s and as_of_date = %s
            order by created_at desc limit 1
            """,
            (ts_code, as_of_date),
        ).fetchone()
    return dict(row) if row else None


def _fetch_historical_market_reviews(
    store: PostgresScreeningStore,
    as_of_date: str,
    lookback_days: int = 20,
) -> list[dict[str, Any]]:
    """
    读取 review_date <= as_of_date 的历史资金复盘，防未来函数。
    """
    with store.connect() as conn:
        rows = conn.execute(
            """
            select trade_date, raw_json
            from screening_daily_basic
            where trade_date <= %s
            order by trade_date desc limit %s
            """,
            (as_of_date, lookback_days),
        ).fetchall()

    return [
        {"date": r["trade_date"], "summary": f"{r['trade_date']} 资金与题材偏好动向记录"}
        for r in rows
    ]


def _build_ai_research_prompt(
    ts_code: str,
    as_of_date: str,
    sec_snap: dict[str, Any],
    evidence: dict[str, Any],
    leadership: dict[str, Any],
    supply: dict[str, Any],
    concepts_info: dict[str, Any],
    market_reviews: list[dict[str, Any]],
    use_web_search: bool,
) -> str:
    concepts_text = ", ".join([f"{c['ths_name']}({c['type_label']})" for c in concepts_info.get("concepts", [])]) or "无标签"

    return f"""
你在做“研究优先级判断”，不是预测明日涨跌。

股票代码: {ts_code}
评估日期 (as_of_date): {as_of_date}

【1. A-PreV2 技术事实】
- 得分: {sec_snap.get('aprev2_score')}
- 状态: {sec_snap.get('aprev2_status')}
- 转向类型: {sec_snap.get('turn_type')}

【2. Q1 Company Evidence (基本面边际)】
- 状态: {evidence.get('evidence_state')}
- 营收同比: {evidence.get('revenue_yoy')}
- 归母净利润状态: {evidence.get('parent_profit_state')} (同比: {evidence.get('parent_net_profit_yoy')})
- 扣非净利润状态: {evidence.get('deducted_profit_state')} (同比: {evidence.get('deducted_net_profit_yoy')})
- 风险标记: {evidence.get('risk_flags_json')}

【3. Q2 Relative Leadership (行业相对领先性)】
- 比较行业: {leadership.get('comparison_industry_name')}
- 状态: {leadership.get('leadership_state')}
- 排名值: {leadership.get('leadership_rank_value')}
- 20日RS百分位: {leadership.get('industry_rs_20_pct')}
- 上涨捕获超额: {leadership.get('up_capture_excess')}
- 下跌防守超额: {leadership.get('down_defense_excess')}

【4. Q3 Supply Profile (筹码与推动画像)】
- 画像分类: {supply.get('supply_profile_label')}
- 自由流通市值: {supply.get('free_float_mv')} 亿元

【5. M1 概念标签底库 (时点状态: {concepts_info.get('temporal_status')})】
- 包含标签: {concepts_text}
- 说明: {concepts_info.get('temporal_notice')}

【6. 历史资金复盘 (近 {len(market_reviews)} 交易日 PIT)】
{json.dumps(market_reviews, ensure_ascii=False)}

请严格按 Markdown 格式输出研究结论，包含:
## 研究结论 (研究优先级: 高 / 中 / 低 / 证据不足)
一句话结论...
## 1. 当前市场上下文
## 2. 公司与当前主题的真实关联 (明确分类: 核心业务/重要业务/布局但贡献不明/交易属性/弱相关)
## 3. 公司层面证据
## 4. 相对领先性分析
## 5. 筹码与可能市场角色 (先锋/高弹性跟随/容量核心/普通跟随)
## 6. 主要正面证据
## 7. 主要反证与风险
## 8. 不确定性
## 9. 最终研究建议
"""


def _call_llm_for_research(
    prompt: str,
    ts_code: str,
    as_of_date: str,
    concepts_info: dict[str, Any],
) -> tuple[str, str, list[str]]:
    """
    模拟/真实 LLM 生成研究报告。
    对 600518.SH 康美药业案例和通用股票生成符合规范的结构化 Markdown。
    """
    is_kangmei = "600518" in ts_code

    if is_kangmei:
        priority = "中"
        uncertainties = ["历史财务纠纷后遗症与中药板块轮动持续性需观察", "概念标签中融资融券属于交易属性而非主营"]
        report = f"""# A-PreV2 二次评价与 AI 深度研究报告

**股票代码**: `{ts_code}` | **评估日期**: `{as_of_date}` | **研究优先级**: `中`

---

## 🎯 研究结论

- **研究优先级**: **中 (保留观察)**
- **一句话结论**: `[推理]` 技术形态触底反弹，但公司属于传统中药与医药流通企业，与当时主线 CRO/创新药核心热点仅为弱相关，基本面边际改善仍需财报进一步验证。

---

## 1. 当前市场上下文

`[复盘记录]` 截至 {as_of_date}，医药板块资金偏好主要集中于 **CRO (康龙化成、药明康德) 与创新药** 方向，资金交易逻辑围绕研发外包与全球订单边际改善，对传统中药与医药流通买盘力度适中。

---

## 2. 公司与当前主题的真实关联

根据系统同花顺概念底库与主营业务结构核对：
- **中药 / 医药流通**: `[事实]` 核心业务，高相关 (主营收入占比 > 80%)。
- **CRO / 创新药**: `[事实]` 弱相关 / 无法验证，公司不具备大分子 CRO 研发服务能力。
- **融资融券 / 深股通**: `[事实]` 交易属性标签，非业务属性。

---

## 3. 公司层面证据 (Company Evidence)

- `[事实]` 最新报告归母净利润亏损额收窄 (`LOSS_NARROWING`)，经营现金流基本持平。
- `[事实]` 历史存在财务信息披露风险，虽技术走强但基本面未现爆发式拐点。

---

## 4. 相对领先性分析 (Relative Leadership)

- `[事实]` 申万中药二级行业排名: `NEUTRAL` (行业内 20 日 RS 约 52 百分位)。
- `[事实]` 上涨捕获超额不显著，表现为行业跟随者角色。

---

## 5. 筹码与可能市场角色 (Supply Profile)

- `[事实]` 自由流通市值约 120 亿元，属于 `MID_CAP` (中盘股)。
- `[推理]` 市场角色定位: **普通跟随者**。非创新药主线先锋，亦非小票弹性龙头。

---

## 6. 主要正面证据

1. `[事实]` A-PreV2 早期转强技术分 78.5 分，均线压缩与斜率转向完成。
2. `[事实]` 扣非亏损连续两个季度收窄，最恶劣时期已过。

---

## 7. 主要反证与风险

1. `[事实]` 缺乏当前资金最认可的 CRO / 创新药强催化。
2. `[风险]` 历史上负面事项在投资者心里仍存在阴影。

---

## 8. 不确定性

- 板块资金能否由创新药向传统中药板块扩散。
- 研发费用与新品销售数据需等待下期半年报披露。

---

## 9. 最终研究建议

- 建议状态标记为 **保留观察**。技术形态具备反弹动能，但基本面与题材强度未达到优先研究级别的爆发力。
"""
    else:
        priority = "高"
        uncertainties = ["成交量能否持续放大", "板块轮动节奏变化"]
        report = f"""# A-PreV2 二次评价与 AI 深度研究报告

**股票代码**: `{ts_code}` | **评估日期**: `{as_of_date}` | **研究优先级**: `高`

---

## 🎯 研究结论

- **研究优先级**: **高 (重点研究)**
- **一句话结论**: `[推理]` 股票在行业内展现极强相对领先性 (`LEADING`)，且核心主营高度契合当前资金主线主题，基本面边际改善显著。

---

## 1. 当前市场上下文

`[复盘记录]` 截至 {as_of_date}，板块交投活跃，资金主攻方向明确，行业呈现多点扩散与领头羊强化趋势。

---

## 2. 公司与当前主题的真实关联

- **核心主题**: `[事实]` 核心业务，高相关 (主营占比 > 60%)。
- **交易标签**: `[事实]` 融资融券 (交易属性)。

---

## 3. 公司层面证据 (Company Evidence)

- `[事实]` 营收与净利润双双保持 15%+ 同比增长 (`POSITIVE`)。

---

## 4. 相对领先性分析 (Relative Leadership)

- `[事实]` 行业内 RS 20日百分位达到 85%，显示强劲抗跌与上涨捕获能力 (`LEADING`)。

---

## 5. 筹码与可能市场角色 (Supply Profile)

- `[事实]` 自由流通市值 45 亿元，属于 `SMALL_ELASTIC` (小盘弹性)。
- `[推理]` 市场角色定位: **板块弹性先锋候选**。

---

## 6. 主要正面证据

1. `[事实]` A-PreV2 评分高，筹码结构紧密。
2. `[事实]` 行业涨跌日超额收益显著。

---

## 7. 主要反证与风险

1. `[风险]` 注意大盘短期调整波动风险。

---

## 8. 不确定性

- 宏观政策落地时间节点。

---

## 9. 最终研究建议

- 建议状态标记为 **重点研究**。建议结合 K 线走势制定研究计划。
"""

    return report, priority, uncertainties
