from __future__ import annotations

import json
import os
import time
from typing import Any

from openai import OpenAI

from backend.screening.storage import PostgresScreeningStore


def match_stock_theme(
    store: PostgresScreeningStore,
    ts_code: str,
    as_of_date: str,
    market_memory: dict[str, Any],
    stock_knowledge: dict[str, Any],
    quarterly_facts_brief: dict[str, Any] | None = None,
    use_web_search: bool = False,
) -> dict[str, Any]:
    """
    AI-2: Theme Match (判断“这只股票真正应该和谁比较”)
    输入: Market Memory 活跃主题列表 + 个股主营/行业/同花顺概念列表。
    输出: 匹配的主主题 (PRIMARY)、次主题 (SECONDARY) 或 NO_ACTIVE_THEME_MATCH 结果。
    """
    system_prompt = """你是一名有多年 A 股经验的专业交易者。
你的任务非常单一：判断这只股票在截至 as_of_date 的市场环境中，真正应该和哪些“近期真实交易过的主题”放在一起研究。

规则：
1. 绝对不要因为同花顺有某个概念标签就自动匹配。融资融券、深股通、次新股等证券交易属性不是业务主题。
2. 如果公司确实与某个活跃或近期交易主题高度相关，返回 PRIMARY_ACTIVE_THEME 与 SECONDARY_ACTIVE_THEMES。
   同时检查股票的同花顺概念标签：如果主主题与某个标签明确对应，必须在 matched_ths_concepts 中返回该标签的原始名称（只能从输入的 ths_concepts 列表中选择，不能自行改写）。这一步是主题匹配的必需输出，不是可选解释。
   如果主主题与任何同花顺概念都不能明确对应，matched_ths_concepts 必须返回空数组，不能创造新概念。
3. 如果近期 Market Memory 中没有合适主题，明确返回 NO_ACTIVE_THEME_MATCH: true。
   注意：NO_ACTIVE_THEME_MATCH 不是负面结论。对于早期反转股票，它可能意味着市场尚未形成共识的新修复方向或个股独立变化。
4. 不要在这里判断是否买入，不要给股票打分或给出最终研究优先级。
"""

    active_themes_text = json.dumps(market_memory.get("themes", []), ensure_ascii=False)
    knowledge_text = json.dumps(stock_knowledge, ensure_ascii=False)

    user_prompt = f"""查看日期：{as_of_date}
目标股票：{ts_code}

【Market Memory 活跃主题】
{active_themes_text}

【股票业务/概念知识 (M1 知识库)】
{knowledge_text}

请精准判断这只股票与 Market Memory 中主题的真正关联，并从它已有的同花顺概念中识别与该主题相关的概念。不要把“主主题名称”当作同花顺概念名称；两者可以不同。

请按以下 JSON 结构输出（包裹在 ```json 代码块中）：
```json
{{
  "ts_code": "{ts_code}",
  "as_of_date": "{as_of_date}",
  "no_active_theme_match": false,
  "primary_active_theme": "匹配的核心主主题名称 (若无则为 null)",
  "secondary_active_themes": ["次要主题1"],
  "matched_ths_concepts": ["与主主题明确对应的同花顺概念原始名称，只能从输入列表中选择"],
  "match_rationale": "详细匹配依据说明",
  "ignored_concept_tags": ["忽略的非业务/交易属性标签"],
  "no_match_reason": "若无匹配主题，解释说明为什么（如未形成共识、独立修复等）"
}}
```
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
        os.getenv("AI_BASE_MODEL", "").strip()
        or os.getenv("AI_BASE_OPENAI_MODEL", "").strip()
        or "qwen3.8-max"
    )

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=120.0,
    )

    started = time.perf_counter()
    response = client.responses.create(
        model=model,
        instructions=system_prompt,
        input=user_prompt,
        tools=[{"type": "web_search"}] if use_web_search else None,
        reasoning={"effort": "none"},
    )

    output_text = getattr(response, "output_text", None)
    if not (isinstance(output_text, str) and output_text.strip()):
        output_items = getattr(response, "output", []) or []
        chunks: list[str] = []
        for item in output_items:
            item_dict = item if isinstance(item, dict) else (item.model_dump() if hasattr(item, "model_dump") else {})
            if item_dict.get("type") == "message":
                for content in item_dict.get("content", []) or []:
                    c_dict = content if isinstance(content, dict) else (content.model_dump() if hasattr(content, "model_dump") else {})
                    if c_dict.get("type") in {"output_text", "text"} and c_dict.get("text"):
                        chunks.append(str(c_dict["text"]))
        output_text = "\n".join(chunks).strip() if chunks else ""

    if not output_text:
        raise RuntimeError("百炼 Responses API 未返回有效内容")

    result = _parse_theme_match_output(output_text, ts_code, as_of_date)
    usage = getattr(response, "usage", None)
    result["_ai_usage"] = {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "reasoning_tokens": int(getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0) or 0),
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "web_search": use_web_search,
        "reasoning": "none",
    }
    return result


def _parse_theme_match_output(
    output_text: str,
    ts_code: str,
    as_of_date: str,
) -> dict[str, Any]:
    """解析 Theme Match AI 的 JSON 输出"""
    result = {
        "ts_code": ts_code,
        "as_of_date": as_of_date,
        "no_active_theme_match": True,
        "primary_active_theme": None,
        "secondary_active_themes": [],
        "matched_ths_concepts": [],
        "match_rationale": output_text,
        "ignored_concept_tags": [],
        "no_match_reason": "解析未找到明确主题 JSON 匹配",
    }

    json_start = output_text.find("```json")
    if json_start != -1:
        json_end = output_text.find("```", json_start + 7)
        if json_end != -1:
            raw_json_str = output_text[json_start + 7 : json_end].strip()
            try:
                parsed = json.loads(raw_json_str)
                if isinstance(parsed, dict):
                    result.update(parsed)
                    if not result.get("matched_ths_concepts") and isinstance(parsed.get("related_ths_concepts"), list):
                        result["matched_ths_concepts"] = parsed["related_ths_concepts"]
            except Exception:
                pass

    return result
