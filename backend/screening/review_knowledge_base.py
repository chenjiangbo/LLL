"""复盘原文知识库。

每日复盘原文是长期事实证据，不能随着 Market Memory 的滚动摘要被覆盖。
本模块只负责原文索引和按股票/主题检索，不对原文做截断或摘要替代。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Iterable

from backend.screening.storage import PostgresScreeningStore


def _ilike_contains_pattern(term: str) -> str:
    """生成不把用户词条中的 SQL 通配符当成模式的包含匹配。"""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def init_review_knowledge_schema(store: PostgresScreeningStore) -> None:
    """创建复盘知识库索引表；原文仍以 imported_market_reviews 为权威来源。"""
    with store.connect() as conn:
        conn.execute(
            """
            create table if not exists review_knowledge_documents (
                trade_date text primary key,
                raw_content text not null,
                payload_json jsonb not null,
                search_text text not null,
                content_sha256 text not null,
                indexed_at timestamptz not null
            )
            """
        )
        conn.execute(
            "create index if not exists idx_review_knowledge_date on review_knowledge_documents(trade_date)"
        )
        conn.commit()


def sync_review_knowledge_base(store: PostgresScreeningStore) -> dict[str, int]:
    """把全部已导入复盘建立可检索索引。

    不使用 limit、样本或只取最近文章。空库也会明确返回 0，调用方可据此展示数据缺口。
    """
    init_review_knowledge_schema(store)
    with store.connect() as conn:
        rows = conn.execute(
            """
            select trade_date, raw_content, payload_json
            from imported_market_reviews
            order by trade_date asc
            """
        ).fetchall()
        indexed = 0
        unchanged = 0
        now = datetime.now(UTC)
        for row in rows:
            raw_content = row["raw_content"] or ""
            payload = row["payload_json"]
            payload_text = payload if isinstance(payload, str) else json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
            search_text = f"{raw_content}\n{payload_text}"
            digest = hashlib.sha256(search_text.encode("utf-8")).hexdigest()
            existing = conn.execute(
                "select content_sha256 from review_knowledge_documents where trade_date = %s",
                (row["trade_date"],),
            ).fetchone()
            if existing and existing["content_sha256"] == digest:
                unchanged += 1
                continue
            conn.execute(
                """
                insert into review_knowledge_documents
                    (trade_date, raw_content, payload_json, search_text, content_sha256, indexed_at)
                values (%s, %s, %s::jsonb, %s, %s, %s)
                on conflict (trade_date) do update set
                    raw_content = excluded.raw_content,
                    payload_json = excluded.payload_json,
                    search_text = excluded.search_text,
                    content_sha256 = excluded.content_sha256,
                    indexed_at = excluded.indexed_at
                """,
                (row["trade_date"], raw_content, payload_text, search_text, digest, now),
            )
            indexed += 1
        conn.commit()
    return {"source_documents": len(rows), "indexed": indexed, "unchanged": unchanged}


def build_review_search_terms(values: Iterable[Any]) -> list[str]:
    """整理可用于原文检索的精确词条，保持输入顺序并去重。"""
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, (list, tuple, set)):
            nested = build_review_search_terms(value)
            for term in nested:
                if term not in seen:
                    seen.add(term)
                    terms.append(term)
            continue
        if value is None:
            continue
        term = str(value).strip()
        if len(term) < 2 or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def retrieve_review_evidence(
    store: PostgresScreeningStore,
    as_of_date: str,
    terms: Iterable[Any],
) -> dict[str, Any]:
    """检索截至查看日的全部相关复盘原文，不静默截断。"""
    normalized_terms = build_review_search_terms(terms)
    if not normalized_terms:
        return {"status": "NO_SEARCH_TERMS", "terms": [], "documents": []}
    sync_review_knowledge_base(store)
    # 历史导入允许 YYYYMMDD / YYYY-MM-DD 两种日期格式，比较时统一成数字日期。
    normalized_date = as_of_date.replace("-", "").strip()
    clauses = ["replace(trade_date, '-', '') <= %s and search_text ilike %s" for _ in normalized_terms]
    params: list[Any] = []
    for term in normalized_terms:
        params.extend([normalized_date, _ilike_contains_pattern(term)])
    with store.connect() as conn:
        rows = conn.execute(
            f"""
            select trade_date, raw_content, payload_json, search_text
            from review_knowledge_documents
            where {' or '.join(clauses)}
            order by trade_date asc
            """,
            params,
        ).fetchall()
    documents = [
        {
            "trade_date": row["trade_date"],
            "raw_content": row["raw_content"],
            "payload": row["payload_json"],
            "matched_terms": [term for term in normalized_terms if term in (row["search_text"] or "")],
        }
        for row in rows
    ]
    return {
        "status": "MATCHED" if documents else "NO_MATCH",
        "terms": normalized_terms,
        "document_count": len(documents),
        "documents": documents,
    }


def format_review_evidence_for_prompt(evidence: dict[str, Any]) -> str:
    """保留日期和原文边界，供 AI 直接核对证据。"""
    documents = evidence.get("documents", [])
    if not documents:
        return f"状态：{evidence.get('status', 'NO_MATCH')}\n检索词：{json.dumps(evidence.get('terms', []), ensure_ascii=False)}\n未检索到相关复盘原文。"
    blocks = []
    for document in documents:
        blocks.append(
            f"【复盘原文｜{document['trade_date']}｜命中：{', '.join(document.get('matched_terms', [])) or '结构化内容'}】\n"
            f"{document['raw_content']}"
        )
    return f"共检索到 {len(documents)} 篇相关复盘原文。\n\n" + "\n\n".join(blocks)
