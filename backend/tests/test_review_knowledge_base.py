from __future__ import annotations

from backend.screening.review_knowledge_base import (
    build_review_search_terms,
    format_review_evidence_for_prompt,
)


def test_build_review_search_terms_deduplicates_and_preserves_nested_terms():
    assert build_review_search_terms(["600518.SH", ["康美药业", "算力", "康美药业"], None, "A"]) == [
        "600518.SH",
        "康美药业",
        "算力",
    ]


def test_format_review_evidence_keeps_date_and_full_article_boundary():
    rendered = format_review_evidence_for_prompt(
        {
            "status": "MATCHED",
            "terms": ["康美药业"],
            "documents": [
                {
                    "trade_date": "20260803",
                    "raw_content": "资金从医药方向分流，康美药业出现观察信号。",
                    "matched_terms": ["康美药业"],
                }
            ],
        }
    )
    assert "20260803" in rendered
    assert "康美药业" in rendered
    assert "资金从医药方向分流" in rendered
    assert "共检索到 1 篇" in rendered


def test_format_review_evidence_exposes_no_match():
    rendered = format_review_evidence_for_prompt(
        {"status": "NO_MATCH", "terms": ["机器人"], "documents": []}
    )
    assert "NO_MATCH" in rendered
    assert "未检索到相关复盘原文" in rendered
