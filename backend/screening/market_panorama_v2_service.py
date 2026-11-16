from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.screening.market_memory_service import _normalize_date, _run_ai
from backend.screening.storage import PostgresScreeningStore


SCHEMA_VERSION = "2.0"
GENERATOR_VERSION = "v2.0"
WINDOW_CALENDAR_DAYS = 120
FULL_REBUILD_INTERVAL = 20

_STATE_PROMPT = """你是一名专业的A股市场历史复盘分析器。
你现在要维护的功能叫“市场全景”。默认观察最近120个自然日；若提供复盘不足120天，只能基于现有复盘，不得补造缺失历史。

任务不是总结今天，也不是拼接日报，而是站在窗口末端理解整个窗口内：市场经历的阶段、主线和重要故事如何演进、故事之间怎样接力竞争共振、资金风格怎样变化、哪些日期是真正转折，以及怎样一步一步走到窗口末端。

Market Phase 只在风险偏好、成交、广度、风格、主线或市场级风险显著变化时切换。120天通常4至8个，特殊时3至10个；绝不按每天划阶段。
Story 是否进入全景取决于整个窗口的重要性而非今天是否活跃。退潮但曾主导、形成赚钱效应、持续较长、影响风险偏好或有多轮行情的故事必须保留。Story 可有多轮 Episode；旧 Episode 已退潮、因新变量重启时必须新建 Episode。AI、医药等大型母题必须记录内部 Subtheme 的承载迁移。
Style Evolution 必须是整个窗口的变化过程，不是当前偏好。Turning Point 必须说明此前、发生、改变、后续。Story Interaction 只能表述市场重心、相对强化、共振或竞争，不能臆测真实账户资金流。Window Pattern 必须输出3至8条由窗口内案例真实支持的规律；即使窗口较短，也要从不同维度提炼至少3条，不能只输出1至2条。窗口末端仅是历史终点。

只输出符合系统提供的 MarketPanoramaHistory JSON，禁止 Markdown、解释、补造历史；不能让最近3至5天吞掉窗口早中期重要历史。"""

_INCREMENTAL_PROMPT = """你是一名A股“市场全景”历史状态更新器。
输入固定包括三部分：上一版 market_panorama_history.json、上一版《市场全景》成稿、今日独立复盘。任务是把今日事实放入已有120天市场历史，不是生成今日复盘或当前强弱榜。

上一版成稿是面向用户的历史叙事，用于保持新旧成稿的论述连续性、避免无必要地改写已形成的历史判断；它不是事实源，不能据此补造、覆盖或推断历史事实。事实更新只能依据上一版结构化历史和今日原始复盘。

按顺序：滚动120自然日窗口；判断是否改变当前 Market Phase；更新 Story/Episode；更新大型母题 Subtheme；必要时结束旧 Episode或开启新 Episode；判断 Turning Point；更新 Style Evolution、Story Interaction、Window Pattern、Window End State；输出完整新 JSON。
普通交易日通常不新建 Phase 或 Turning Point。窗口内仍重要的历史不能因今天变弱而删除。已明确结束的 Phase、Episode、Turning Point 默认只读，若修改必须在 maintenance.historical_corrections 中记录原判断、新判断、原因、新证据。
只输出严格 JSON，不输出 Markdown。"""

_RENDER_PROMPT = """你是一名专业投资机构的A股策略研究员。输入是一份结构化 market_panorama_history.json。
把它写成真正可读的“市场全景”。标题只能是“# 市场全景”。标题下说明默认观察最近120天；历史不足时说明实际覆盖区间和复盘数量。

必须严格采用八章：
## 1. 市场演进概述
## 2. 市场阶段演进
## 3. 主要故事演进
## 4. 资金风格演进
## 5. 关键市场转折
## 6. 主线互动与轮动
## 7. 窗口内规律
## 8. 窗口末端定位

采用专业投资机构策略报告文风：客观、克制、严谨、简洁，依据复盘事实说明阶段变化、因果和结构含义。禁止小说化、情绪化、夸张化表达；禁止使用“惊心动魄、旅程、风暴、闪电、迷雾、无头苍蝇、绝望、救赎、宣泄”等文学修辞或拟人化比喻。避免绝对化词汇，事实与判断应清楚区分。

这是完整讲述市场怎样一步步走到今天的历史分析。第三章按窗口重要性而非当前强弱排序；大型母题需写内部子主题迁移，退潮但重要的故事也必须写。第八章只占全文5%到10%。不得写成数据库字段、状态卡、观察股清单、明日验证、赚钱亏钱榜。直接输出 Markdown。"""

_REVIEW_PROMPT = """你是“市场全景”质量审查器。输入包括 market_panorama_history.json 和生成文章。
评分0至10：时间覆盖完整性、重要Story覆盖、Episode准确性、市场阶段清晰度、风格演进完整度、Story接力竞争叙事、近期偏差、过度当前化、叙事可读性、是否像数据库字段拼装。
硬失败：窗口末端内容超过20%；遗漏窗口内明显major Story；将退潮再启动写成连续行情；最近5交易日超过全文50%且历史更长；大量出现状态/证据/下一验证/Priority字段；缺少阶段和主线叙事；标题不是规定的八个短标题；出现小说化、情绪化、夸张化修辞或拟人化比喻，不符合专业投资机构研报文风。
只输出 JSON：{\"pass\":true,\"scores\":{},\"problems\":[],\"required_fixes\":[]}。"""

_RENDER_REPAIR_PROMPT = """你是成熟的A股市场复盘作者。根据同一份 market_panorama_history.json 和 Reviewer 的 required_fixes，重写市场全景文章。严格保持八章、标题“# 市场全景”，只修复审查指出的问题；不得补造事实或改写 JSON。直接输出 Markdown。"""


def init_v2_schema(store: PostgresScreeningStore) -> None:
    with store.connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS screening_market_panorama_v2_snapshot (
                as_of_date VARCHAR(10) PRIMARY KEY,
                generator_version VARCHAR(20) NOT NULL,
                requested_start_date VARCHAR(10) NOT NULL,
                actual_first_review_date VARCHAR(10) NOT NULL,
                review_count INT NOT NULL,
                last_full_rebuild_review_count INT NOT NULL,
                last_full_rebuild_date VARCHAR(10),
                reviews_digest VARCHAR(64) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                history_json JSONB NOT NULL,
                article_markdown TEXT NOT NULL,
                reviewer_json JSONB NOT NULL
            )
        """)
        conn.execute("ALTER TABLE screening_market_panorama_v2_snapshot ADD COLUMN IF NOT EXISTS last_full_rebuild_date VARCHAR(10)")
        conn.commit()


def _calendar_window_start(as_of_date: str) -> str:
    return (datetime.fromisoformat(as_of_date).date() - timedelta(days=WINDOW_CALENDAR_DAYS - 1)).isoformat()


def _reviews_for_window(store: PostgresScreeningStore, as_of_date: str) -> list[dict[str, str]]:
    start = _calendar_window_start(as_of_date)
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT trade_date, raw_content
            FROM imported_market_reviews
            WHERE trade_date >= %s AND trade_date <= %s
            ORDER BY trade_date ASC
            """,
            (start, as_of_date),
        ).fetchall()
    reviews = [
        {
            "date": str(row["trade_date"]),
            "raw_text": row["raw_content"] if isinstance(row["raw_content"], str) else json.dumps(row["raw_content"], ensure_ascii=False),
        }
        for row in rows
    ]
    if not reviews or reviews[-1]["date"] != as_of_date:
        raise RuntimeError(f"{as_of_date} 没有已导入复盘，无法生成市场全景")
    return reviews


def _schema_hint(as_of_date: str, requested_start: str, reviews: list[dict[str, str]]) -> str:
    return f"""严格 JSON 顶层字段：
{{"schema_version":"2.0","as_of":"{as_of_date}","window":{{"window_days":120,"window_type":"calendar_days","requested_start_date":"{requested_start}","actual_first_review_date":"{reviews[0]['date']}","end_date":"{as_of_date}","review_count":{len(reviews)},"history_complete":false}},"market_phases":[],"stories":[],"turning_points":[],"style_evolution":{{}},"story_interactions":[],"window_patterns":[],"window_end_state":{{}},"source_reviews":[],"maintenance":{{"historical_corrections":[]}}}}

market_phases 每项必须有 phase_id,start_date,end_date,title,summary,index_environment,liquidity,breadth,risk_appetite,dominant_styles,dominant_story_ids,ending_reason,important_dates。
stories 每项必须有 story_id,display_name,importance,first_seen_in_window,last_seen_in_window,window_role_summary,episodes,subthemes,representative_stocks,related_phase_ids；importance 只能是 major/important/secondary/minor。episodes 每项必须有 episode_id,start_date,end_date,trigger,current_or_final_state,state_nodes；subthemes 每项必须有 subtheme_id,display_name,first_major_date,role_summary。
turning_points 每项必须有 date,title,before,event,after,affected_story_ids,importance。style_evolution 必须含 large_vs_small,trend_vs_limitup,high_vs_low,capacity_vs_elasticity,limitup_structure,growth_vs_defensive,concentration_vs_rotation，且每项有 summary,nodes。window_patterns 必须输出3至8项，每项必须有 pattern_id,summary,supporting_cases。story_interactions 每项必须有 date_range,story_ids,relationship,summary,confidence。window_end_state 必须有 summary,position_in_history。source_reviews 必须与输入复盘日期逐一对应。"""


def _strip_json(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1]
        if value.rstrip().endswith("```"):
            value = value.rstrip()[:-3]
    return value.strip()


def _require_dict(item: Any, fields: tuple[str, ...], label: str) -> dict[str, Any]:
    if not isinstance(item, dict) or any(field not in item for field in fields):
        raise RuntimeError(f"{label} 不符合市场全景 V2.0 Schema，未写入")
    return item


def validate_history(history: Any, as_of_date: str, requested_start: str, reviews: list[dict[str, str]]) -> dict[str, Any]:
    root = _require_dict(history, ("schema_version","as_of","window","market_phases","stories","turning_points","style_evolution","story_interactions","window_patterns","window_end_state","source_reviews","maintenance"), "历史状态")
    if root["schema_version"] != SCHEMA_VERSION or root["as_of"] != as_of_date:
        raise RuntimeError("市场全景版本或截止日期不正确，未写入")
    window = _require_dict(root["window"], ("window_days","window_type","requested_start_date","actual_first_review_date","end_date","review_count","history_complete"), "window")
    if window != {**window, "window_days": 120, "window_type": "calendar_days", "requested_start_date": requested_start, "actual_first_review_date": str(reviews[0]['date']), "end_date": as_of_date, "review_count": len(reviews), "history_complete": len(reviews) > 0 and str(reviews[0]['date']) == requested_start}:
        # Only validate specified factual fields; model may not know completeness ahead of importing history.
        if any(window.get(k) != v for k, v in {"window_days":120,"window_type":"calendar_days","requested_start_date":requested_start,"actual_first_review_date":str(reviews[0]['date']),"end_date":as_of_date,"review_count":len(reviews)}.items()):
            raise RuntimeError("市场全景窗口元数据与实际复盘不一致，未写入")
    if not 3 <= len(root["market_phases"]) <= 10:
        raise RuntimeError("市场阶段必须为3至10个，未写入")
    for item in root["market_phases"]:
        _require_dict(item, ("phase_id","start_date","end_date","title","summary","index_environment","liquidity","breadth","risk_appetite","dominant_styles","dominant_story_ids","ending_reason","important_dates"), "Market Phase")
    for story in root["stories"]:
        story = _require_dict(story, ("story_id","display_name","importance","first_seen_in_window","last_seen_in_window","window_role_summary","episodes","subthemes","representative_stocks","related_phase_ids"), "Story")
        if story["importance"] not in {"major","important","secondary","minor"}:
            raise RuntimeError("Story importance 无效，未写入")
        for episode in story["episodes"]:
            _require_dict(episode, ("episode_id","start_date","end_date","trigger","current_or_final_state","state_nodes"), "Episode")
        for subtheme in story["subthemes"]:
            _require_dict(subtheme, ("subtheme_id","display_name","first_major_date","role_summary"), "Subtheme")
    if not 8 <= len(root["turning_points"]) <= 15 and len(reviews) >= 40:
        raise RuntimeError("完整窗口的转折点必须为8至15个，未写入")
    for point in root["turning_points"]:
        _require_dict(point, ("date","title","before","event","after","affected_story_ids","importance"), "Turning Point")
    for key in ("large_vs_small","trend_vs_limitup","high_vs_low","capacity_vs_elasticity","limitup_structure","growth_vs_defensive","concentration_vs_rotation"):
        _require_dict(root["style_evolution"].get(key), ("summary","nodes"), f"Style Evolution {key}")
    for item in root["story_interactions"]:
        _require_dict(item, ("date_range","story_ids","relationship","summary","confidence"), "Story Interaction")
    if not 3 <= len(root["window_patterns"]) <= 8:
        raise RuntimeError("窗口规律必须为3至8条，未写入")
    for item in root["window_patterns"]:
        _require_dict(item, ("pattern_id","summary","supporting_cases"), "Window Pattern")
    _require_dict(root["window_end_state"], ("summary","position_in_history"), "Window End State")
    dates = [str(item["date"]) if isinstance(item, dict) else str(item) for item in root["source_reviews"]]
    expected = [str(item["date"]) for item in reviews]
    if dates != expected:
        raise RuntimeError("source_reviews 未完整对应输入复盘，未写入")
    _require_dict(root["maintenance"], ("historical_corrections",), "maintenance")
    return root


def _apply_system_provenance(history: Any, as_of_date: str, reviews: list[dict[str, str]]) -> Any:
    """Set system-owned review provenance after the model supplies its analysis.

    A model analyses market structure; it is not the source of truth for which
    reviews were actually supplied.  These fields are derived directly from the
    database window so every stored history can be traced exactly to its inputs.
    """
    if not isinstance(history, dict):
        return history
    requested_start = _calendar_window_start(as_of_date)
    result = dict(history)
    result["schema_version"] = SCHEMA_VERSION
    result["as_of"] = as_of_date
    result["window"] = {
        "window_days": WINDOW_CALENDAR_DAYS,
        "window_type": "calendar_days",
        "requested_start_date": requested_start,
        "actual_first_review_date": str(reviews[0]["date"]),
        "end_date": as_of_date,
        "review_count": len(reviews),
        "history_complete": str(reviews[0]["date"]) == requested_start,
    }
    result["source_reviews"] = [str(item["date"]) for item in reviews]
    return result


def _call_state_full(reviews: list[dict[str, str]], as_of_date: str) -> dict[str, Any]:
    prompt = f"观察截止：{as_of_date}\n默认窗口起点：{_calendar_window_start(as_of_date)}\n\n【按日期排序的原始复盘】\n" + "\n\n".join(f"【{item['date']}】\n{item['raw_text']}" for item in reviews) + "\n\n" + _schema_hint(as_of_date, _calendar_window_start(as_of_date), reviews)
    return json.loads(_strip_json(_run_ai(prompt, instructions=_STATE_PROMPT, json_output=True)))


def _call_state_incremental(
    previous_history: dict[str, Any],
    previous_article: str,
    today_review: dict[str, str],
    as_of_date: str,
    reviews: list[dict[str, str]],
) -> dict[str, Any]:
    """日更只使用已验证历史、上一版成稿与当天原文，禁止隐式补取近期复盘。"""
    requested_start = _calendar_window_start(as_of_date)
    prompt = (
        f"新观察截止：{as_of_date}\n"
        f"滚动窗口起点：{requested_start}\n"
        f"窗口内实际首篇复盘：{reviews[0]['date']}；复盘数量：{len(reviews)}\n\n"
        f"【上一版结构化市场全景历史（事实状态与更新依据）】\n{json.dumps(previous_history, ensure_ascii=False)}\n\n"
        f"【上一版《市场全景》成稿（截至上一交易日的用户展示文章；仅用于叙事连续性，不是事实源）】\n{previous_article}\n\n"
        f"【今日原始复盘（{today_review['date']}，本次唯一新增事实）】\n{today_review['raw_text']}\n\n"
        + _schema_hint(as_of_date, requested_start, reviews)
    )
    return json.loads(_strip_json(_run_ai(prompt, instructions=_INCREMENTAL_PROMPT, json_output=True)))


def _render_and_review(history: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    article = _run_ai(json.dumps(history, ensure_ascii=False), instructions=_RENDER_PROMPT).strip()
    reviewer = json.loads(_strip_json(_run_ai(f"【历史状态】\n{json.dumps(history, ensure_ascii=False)}\n\n【文章】\n{article}", instructions=_REVIEW_PROMPT, json_output=True)))
    _require_dict(reviewer, ("pass","scores","problems","required_fixes"), "Reviewer 输出")
    if not reviewer["pass"]:
        article = _run_ai(f"【历史状态】\n{json.dumps(history, ensure_ascii=False)}\n\n【Reviewer 必修项】\n{json.dumps(reviewer['required_fixes'], ensure_ascii=False)}", instructions=_RENDER_REPAIR_PROMPT).strip()
        reviewer = json.loads(_strip_json(_run_ai(f"【历史状态】\n{json.dumps(history, ensure_ascii=False)}\n\n【文章】\n{article}", instructions=_REVIEW_PROMPT, json_output=True)))
        _require_dict(reviewer, ("pass","scores","problems","required_fixes"), "Reviewer 输出")
    if not reviewer["pass"]:
        raise RuntimeError("市场全景文章未通过 V2.0 Reviewer，未写入")
    if any(f"## {i}." not in article for i in range(1, 9)):
        raise RuntimeError("市场全景文章未按八章结构生成，未写入")
    return article, reviewer


def get_cached_v2(store: PostgresScreeningStore, as_of_date: str) -> tuple[dict[str, Any], str, dict[str, Any]] | None:
    init_v2_schema(store)
    with store.connect() as conn:
        row = conn.execute("SELECT history_json, article_markdown, reviewer_json FROM screening_market_panorama_v2_snapshot WHERE as_of_date = %s AND generator_version = %s", (_normalize_date(as_of_date), GENERATOR_VERSION)).fetchone()
    if not row:
        return None
    def decode(value: Any) -> dict[str, Any]: return value if isinstance(value, dict) else json.loads(value)
    return decode(row["history_json"]), row["article_markdown"], decode(row["reviewer_json"])


def _get_previous_snapshot(store: PostgresScreeningStore, as_of_date: str) -> dict[str, Any] | None:
    with store.connect() as conn:
        row = conn.execute(
            """SELECT as_of_date, history_json, article_markdown, last_full_rebuild_review_count, last_full_rebuild_date
               FROM screening_market_panorama_v2_snapshot
               WHERE as_of_date < %s AND generator_version = %s
               ORDER BY as_of_date DESC LIMIT 1""",
            (as_of_date, GENERATOR_VERSION),
        ).fetchone()
    if not row:
        return None
    return {
        "as_of_date": str(row["as_of_date"]),
        "history": row["history_json"] if isinstance(row["history_json"], dict) else json.loads(row["history_json"]),
        "article": str(row["article_markdown"]),
        "last_full_rebuild_review_count": int(row["last_full_rebuild_review_count"]),
        "last_full_rebuild_date": str(row["last_full_rebuild_date"] or row["as_of_date"]),
    }


def _write_snapshot(
    store: PostgresScreeningStore,
    norm: str,
    reviews: list[dict[str, str]],
    history: dict[str, Any],
    article: str,
    reviewer: dict[str, Any],
    last_full_rebuild_review_count: int,
    last_full_rebuild_date: str,
) -> None:
    digest = hashlib.sha256("|".join(f"{item['date']}:{item['raw_text']}" for item in reviews).encode()).hexdigest()
    with store.connect() as conn:
        conn.execute("""INSERT INTO screening_market_panorama_v2_snapshot
            (as_of_date,generator_version,requested_start_date,actual_first_review_date,review_count,last_full_rebuild_review_count,last_full_rebuild_date,reviews_digest,created_at,history_json,article_markdown,reviewer_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)
            ON CONFLICT (as_of_date) DO UPDATE SET generator_version=EXCLUDED.generator_version,requested_start_date=EXCLUDED.requested_start_date,actual_first_review_date=EXCLUDED.actual_first_review_date,review_count=EXCLUDED.review_count,last_full_rebuild_review_count=EXCLUDED.last_full_rebuild_review_count,last_full_rebuild_date=EXCLUDED.last_full_rebuild_date,reviews_digest=EXCLUDED.reviews_digest,created_at=EXCLUDED.created_at,history_json=EXCLUDED.history_json,article_markdown=EXCLUDED.article_markdown,reviewer_json=EXCLUDED.reviewer_json""",
            (norm,GENERATOR_VERSION,_calendar_window_start(norm),str(reviews[0]['date']),len(reviews),last_full_rebuild_review_count,last_full_rebuild_date,digest,datetime.now(UTC),json.dumps(history,ensure_ascii=False),article,json.dumps(reviewer,ensure_ascii=False)))
        conn.commit()


def rebuild_v2(store: PostgresScreeningStore, as_of_date: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
    norm = _normalize_date(as_of_date)
    init_v2_schema(store)
    reviews = _reviews_for_window(store, norm)
    history = validate_history(
        _apply_system_provenance(_call_state_full(reviews, norm), norm, reviews),
        norm,
        _calendar_window_start(norm),
        reviews,
    )
    article, reviewer = _render_and_review(history)
    _write_snapshot(store, norm, reviews, history, article, reviewer, len(reviews), norm)
    return history, article, reviewer


def update_incremental_v2(store: PostgresScreeningStore, as_of_date: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """导入一篇新复盘后的 V2 日更；满 20 个新增复盘时按规格重新全量生成。"""
    norm = _normalize_date(as_of_date)
    init_v2_schema(store)
    reviews = _reviews_for_window(store, norm)
    previous = _get_previous_snapshot(store, norm)
    if previous is None:
        return rebuild_v2(store, norm)
    # Incremental input is only valid when the immediately preceding imported
    # review already has a snapshot.  If a prior daily task failed, feeding just
    # the newest review would silently skip the missing day's market facts.
    if len(reviews) < 2 or previous["as_of_date"] != str(reviews[-2]["date"]):
        return rebuild_v2(store, norm)
    with store.connect() as conn:
        new_review_count = conn.execute(
            "SELECT COUNT(*) AS count FROM imported_market_reviews WHERE trade_date > %s AND trade_date <= %s",
            (previous["last_full_rebuild_date"], norm),
        ).fetchone()["count"]
    if int(new_review_count) >= FULL_REBUILD_INTERVAL:
        return rebuild_v2(store, norm)
    history = validate_history(
        _apply_system_provenance(
            _call_state_incremental(previous["history"], previous["article"], reviews[-1], norm, reviews),
            norm,
            reviews,
        ),
        norm,
        _calendar_window_start(norm),
        reviews,
    )
    article, reviewer = _render_and_review(history)
    _write_snapshot(store, norm, reviews, history, article, reviewer, previous["last_full_rebuild_review_count"], previous["last_full_rebuild_date"])
    return history, article, reviewer


def rerender_v2(store: PostgresScreeningStore, as_of_date: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """只重写前台叙事与审查结果，历史结构保持不变。"""
    norm = _normalize_date(as_of_date)
    cached = get_cached_v2(store, norm)
    if cached is None:
        raise RuntimeError(f"{norm} 尚无 V2 市场全景历史，需先全量重建")
    history, _, _ = cached
    article, reviewer = _render_and_review(history)
    with store.connect() as conn:
        conn.execute(
            "UPDATE screening_market_panorama_v2_snapshot SET article_markdown = %s, reviewer_json = %s::jsonb, created_at = %s WHERE as_of_date = %s AND generator_version = %s",
            (article, json.dumps(reviewer, ensure_ascii=False), datetime.now(UTC), norm, GENERATOR_VERSION),
        )
        conn.commit()
    return history, article, reviewer
