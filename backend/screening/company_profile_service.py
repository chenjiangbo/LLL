"""Current, source-backed company business introductions.

The short introduction is a current stock attribute, not a dated selection
snapshot.  The model may summarize retrieved sources, but it may not invent
business facts that are not supported by those sources.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from openai import OpenAI
from pydantic import BaseModel, Field

from backend.market_review.ai_analysis import _extract_json_object
from backend.screening.storage import PostgresScreeningStore


class CompanySource(BaseModel):
    title: str = Field(min_length=1)
    url: str = Field(min_length=8)
    source_type: str = Field(min_length=1)
    published_at: str | None = None


class CurrentThemeContext(BaseModel):
    as_of_date: str
    theme_name: str | None = None
    relationship_type: Literal[
        "DIRECT_BUSINESS",
        "COMPANY_PRODUCT_OR_PROJECT",
        "PARENT_OR_SHAREHOLDER_RESOURCE",
        "MARKET_ASSOCIATION",
        "NO_VERIFIED_RELATION",
    ]
    evidence_type: Literal["COMPANY_DISCLOSURE", "PUBLIC_SOURCE", "MARKET_INFERENCE", "UNCONFIRMED"]
    summary: str = Field(min_length=15, max_length=500)
    boundary: str = Field(min_length=1, max_length=300)
    sources: list[CompanySource] = Field(min_length=1)


class CompanyProfilePayload(BaseModel):
    summary: str = Field(min_length=20)
    key_points: list[str] = Field(min_length=5, max_length=8)
    upstream: str = Field(min_length=1)
    downstream: str = Field(min_length=1)
    positioning: str = Field(min_length=1)
    business_evidence: list[str] = Field(default_factory=list, max_length=2)
    uncertainties: list[str] = Field(default_factory=list)
    sources: list[CompanySource] = Field(min_length=1)
    market_context: CurrentThemeContext


COMPANY_PROFILE_PROMPT_VERSION = "business_profile_v3"


def _json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _theme_context_fingerprint(theme_profile: dict[str, Any], theme_result: dict[str, Any]) -> str:
    return _json_hash({
        "market_memory_date": theme_profile.get("market_memory_date"),
        "market_theme_fingerprint": theme_profile.get("market_theme_fingerprint"),
        "concept_fingerprint": theme_profile.get("concept_fingerprint"),
        "theme_result": theme_result,
    })


def _company_identity(store: PostgresScreeningStore, ts_code: str) -> dict[str, Any]:
    with store.connect() as conn:
        row = conn.execute(
            "select asset_code, name, raw_json->>'main_business' as main_business, raw_json->>'industry' as industry "
            "from screening_asset_master where asset_code = %s",
            (ts_code,),
        ).fetchone()
    if not row:
        raise RuntimeError(f"证券主数据不存在：{ts_code}")
    return dict(row)


def _extract_output(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        item_dict = item if isinstance(item, dict) else (item.model_dump() if hasattr(item, "model_dump") else {})
        if item_dict.get("type") != "message":
            continue
        for content in item_dict.get("content", []) or []:
            content_dict = content if isinstance(content, dict) else (content.model_dump() if hasattr(content, "model_dump") else {})
            if content_dict.get("type") in {"output_text", "text"} and content_dict.get("text"):
                chunks.append(str(content_dict["text"]))
    return "\n".join(chunks).strip()


def _response_debug_summary(response: Any, output: str) -> str:
    def plain(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if hasattr(value, "model_dump"):
            return value.model_dump()
        return str(value)

    output_items = getattr(response, "output", []) or []
    item_types: list[str] = []
    content_types: list[str] = []
    for item in output_items:
        item_data = item if isinstance(item, dict) else (item.model_dump() if hasattr(item, "model_dump") else {})
        item_types.append(str(item_data.get("type") or "unknown"))
        for content in item_data.get("content", []) or []:
            content_data = content if isinstance(content, dict) else (content.model_dump() if hasattr(content, "model_dump") else {})
            content_types.append(str(content_data.get("type") or "unknown"))
    prefix = " ".join((output or "").split())[:160]
    summary = {
        "response_id": getattr(response, "id", None),
        "status": getattr(response, "status", None),
        "incomplete_details": plain(getattr(response, "incomplete_details", None)),
        "response_error": plain(getattr(response, "error", None)),
        "output_types": item_types,
        "content_types": content_types,
        "output_length": len(output or ""),
        "output_prefix": prefix,
    }
    return json.dumps(summary, ensure_ascii=False, default=str)


def generate_company_profile(
    store: PostgresScreeningStore,
    ts_code: str,
    theme_profile: dict[str, Any],
) -> dict[str, Any]:
    code = ts_code.strip().upper()
    identity = _company_identity(store, code)
    knowledge = {
        "ts_code": code,
        "name": identity.get("name"),
        "industry": identity.get("industry"),
        "raw_main_business": identity.get("main_business"),
    }
    theme_result = theme_profile.get("result_json") or {}
    if isinstance(theme_result, str):
        try:
            theme_result = json.loads(theme_result)
        except json.JSONDecodeError as exc:
            raise RuntimeError("当前主题匹配结果不是有效 JSON，无法生成题材关联说明") from exc
    if not isinstance(theme_result, dict):
        raise RuntimeError("当前主题匹配结果格式无效，无法生成题材关联说明")
    theme_knowledge = {
        "as_of_date": theme_profile.get("market_memory_date") or theme_result.get("as_of_date"),
        "primary_active_theme": theme_result.get("primary_active_theme"),
        "secondary_active_themes": theme_result.get("secondary_active_themes") or [],
        "matched_ths_concepts": theme_result.get("matched_ths_concepts") or [],
        "match_rationale": theme_result.get("match_rationale"),
        "no_active_theme_match": bool(theme_result.get("no_active_theme_match")),
    }
    theme_context_fingerprint = _theme_context_fingerprint(theme_profile, theme_result)
    model = os.getenv("AI_BASE_MODEL", "").strip()
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip() or os.getenv("AI_BASE_API_KEY", "").strip()
    base_url = os.getenv("AI_BASE_BASE_URL", "").strip() or os.getenv("DASHSCOPE_BASE_URL", "").strip() or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if not model or not api_key:
        raise RuntimeError("企业业务简介研究缺少 AI_BASE_MODEL 或 DASHSCOPE_API_KEY")

    system_prompt = """你是一个严谨的 A 股公司资料研究员。你只能根据联网搜索得到的可靠公开资料和输入的证券基础资料总结企业业务，不能凭常识补写。

必须遵守：
1. 优先使用公司官网、交易所公告、年报/半年报、巨潮资讯、监管披露和权威行业资料；新闻只能作为补充。
2. 每个事实性判断都必须能由来源支持；来源不一致时写入 uncertainties，不要自行裁决。
3. 不得把同花顺概念标签、搜索摘要或市场传闻直接写成主营事实。
4. summary 只写企业业务画像：公司做什么、主要产品、应用场景和产业链位置。允许保留少量能直接证明业务规模或行业地位的数字，但不得写成财务分析。
5. key_points 输出 5～8 条互不重复的业务事实，优先说明产品、技术、客户和应用；不得连续罗列营收、利润、毛利率、现金流、同比、环比或客户占比。
6. business_evidence 最多输出 2 条，只保留能够直接证明主营业务结构、业务规模或行业地位的经营/财务事实；没有必要时返回空数组。
7. upstream、downstream、positioning 只描述产业链业务关系，不要填财务指标。
8. 同一事实只能出现一次，不得在 summary、key_points 和 business_evidence 中重复改写。
9. 没有公开资料确认的内容必须写“暂无公开资料确认”，不得猜测。
10. sources 必须包含实际使用的 HTTP/HTTPS 来源 URL；如果没有可靠来源，直接报错，不要生成无来源简介。
11. summary/key_points/upstream/downstream/positioning 只写公司长期业务事实，不得把当下热点交易叙事混入公司主营介绍。
12. market_context 专门解释本次主线题材与公司的关联，并且必须区分直接业务、公司产品/项目、控股股东资源、市场映射、无可核实关联。控股股东或集团资源不得写成上市公司自有资产或已落地业务。
13. 公司公告对热点业务作出否认或澄清时，必须在 market_context.boundary 中直接说明，并以公司公告为准；市场概念标签不能推翻公司澄清。
14. market_context.summary 与 boundary 合计简短表达，不得复述主营业务全文；sources 必须实际支持这段关联判断。
"""
    user_prompt = f"""请联网研究下面这家上市公司，并严格只输出 JSON，不要输出 Markdown 或解释。

证券基础资料（仅作身份锚点，不足以支撑全部结论）：
{json.dumps(knowledge, ensure_ascii=False)}

本次主题匹配结果（仅说明当前市场关注，不是公司事实来源）：
{json.dumps(theme_knowledge, ensure_ascii=False)}

JSON 结构：
{{
  "summary": "一段 5～8 句的简短企业业务介绍",
  "key_points": ["5～8 条短句，每条都必须有来源依据"],
  "upstream": "上游环节；无法确认时写暂无公开资料确认",
  "downstream": "下游客户/应用；无法确认时写暂无公开资料确认",
  "positioning": "公司在产业链中的位置及有来源支持的竞争特点",
  "business_evidence": ["最多两条、仅在确实能证明业务结构/规模/地位时保留的事实"],
  "uncertainties": ["尚未由公开资料确认的事项"],
  "market_context": {{
    "as_of_date": "题材记忆日期 YYYYMMDD",
    "theme_name": "本次主线题材；无匹配时为 null",
    "relationship_type": "DIRECT_BUSINESS、COMPANY_PRODUCT_OR_PROJECT、PARENT_OR_SHAREHOLDER_RESOURCE、MARKET_ASSOCIATION、NO_VERIFIED_RELATION 之一",
    "evidence_type": "COMPANY_DISCLOSURE、PUBLIC_SOURCE、MARKET_INFERENCE、UNCONFIRMED 之一",
    "summary": "1～3句说明该题材与公司的具体联系",
    "boundary": "说明业务是否已落地、是否仅为集团资源或市场映射；公司有澄清时写明澄清",
    "sources": [{{"title":"支持题材关联判断的来源标题","url":"https://...","source_type":"公告/官网/年报/新闻","published_at":"YYYY-MM-DD 或 null"}}]
  }},
  "sources": [
    {{"title":"来源标题","url":"https://...","source_type":"官网/年报/公告/行业资料/新闻","published_at":"YYYY-MM-DD 或 null"}}
  ]
}}
"""
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=httpx.Timeout(connect=15.0, read=180.0, write=60.0, pool=60.0))
    started = time.perf_counter()
    payload: CompanyProfilePayload | None = None
    response: Any = None
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    last_error: Exception | None = None
    for attempt in range(1, 3):
        response = client.responses.create(
            model=model,
            instructions=system_prompt,
            input=user_prompt,
            tools=[{"type": "web_search"}],
            reasoning={"effort": "none"},
            text={"format": {"type": "json_object"}},
        )
        usage = getattr(response, "usage", None)
        input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        total_tokens += int(getattr(usage, "total_tokens", 0) or 0)
        try:
            output = _extract_output(response)
            if getattr(response, "status", None) not in (None, "completed"):
                raise RuntimeError(f"百炼响应未正常完成：{_response_debug_summary(response, output)}")
            if not output:
                raise RuntimeError(f"百炼响应没有可解析的助手文本：{_response_debug_summary(response, output)}")
            parsed = CompanyProfilePayload.model_validate(_extract_json_object(output))
            if not any(re.match(r"^https?://", source.url) for source in parsed.sources):
                raise RuntimeError("企业业务简介研究未返回可核验来源")
            if not any(re.match(r"^https?://", source.url) for source in parsed.market_context.sources):
                raise RuntimeError("当前题材关联未返回可核验来源")
            payload = parsed
            break
        except Exception as exc:
            response_debug = _response_debug_summary(response, _extract_output(response))
            last_error = RuntimeError(f"{type(exc).__name__}: {exc}; response={response_debug}")
            print(
                f"[company-profile] output validation failed for {code}: "
                f"attempt={attempt}/2, response={response_debug}, "
                f"error={type(exc).__name__}: {exc}"
            )
            if attempt < 2:
                time.sleep(1)
    if payload is None:
        raise RuntimeError(f"企业业务简介连续两次未通过 JSON 和字段校验：{last_error}")
    sources = [source.model_dump() for source in payload.sources if re.match(r"^https?://", source.url)]
    market_context_sources = [
        source.model_dump()
        for source in payload.market_context.sources
        if re.match(r"^https?://", source.url)
    ]
    if not sources:
        raise RuntimeError("企业业务简介研究未返回可核验来源")
    result = payload.model_dump()
    result["market_context"]["sources"] = market_context_sources
    result["market_context_fingerprint"] = theme_context_fingerprint
    result["model"] = model
    result["prompt_version"] = COMPANY_PROFILE_PROMPT_VERSION
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    result["input_tokens"] = input_tokens
    result["output_tokens"] = output_tokens
    result["total_tokens"] = total_tokens
    result["web_search_used"] = True
    return {
        "result": result,
        "source_manifest": {
            "sources": sources,
            "market_context_sources": market_context_sources,
            "web_search_used": True,
            "model": model,
        },
    }


def get_or_refresh_current_company_profile(
    store: PostgresScreeningStore,
    ts_code: str,
    theme_profile: dict[str, Any],
) -> dict[str, Any]:
    code = ts_code.strip().upper()
    existing = store.get_current_stock_profile("company", code)
    if existing and str(existing.get("status")) == "READY":
        existing_result = existing.get("result_json") or {}
        if isinstance(existing_result, str):
            try:
                existing_result = json.loads(existing_result)
            except json.JSONDecodeError:
                existing_result = {}
        existing_context = existing_result.get("market_context") or {}
        existing_theme_result = theme_profile.get("result_json") or {}
        if isinstance(existing_theme_result, str):
            try:
                existing_theme_result = json.loads(existing_theme_result)
            except json.JSONDecodeError:
                existing_theme_result = {}
        expected_context_fingerprint = _theme_context_fingerprint(theme_profile, existing_theme_result)
        if (
            existing_result.get("prompt_version") == COMPANY_PROFILE_PROMPT_VERSION
            and str(existing_context.get("as_of_date") or "") == str(theme_profile.get("market_memory_date") or "")
            and existing_result.get("market_context_fingerprint") == expected_context_fingerprint
        ):
            return existing
    generated = generate_company_profile(store, code, theme_profile)
    identity = _company_identity(store, code)
    fingerprint = _json_hash({"identity": identity, "source_urls": generated["source_manifest"].get("sources", [])})
    store.save_current_company_profile(code, fingerprint, generated["result"], generated["source_manifest"], "READY")
    profile = store.get_current_stock_profile("company", code)
    if not profile:
        raise RuntimeError("企业业务简介保存后无法读取")
    return profile
