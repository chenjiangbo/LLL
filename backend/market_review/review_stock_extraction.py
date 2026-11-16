from __future__ import annotations

"""Full-text, evidence-backed stock mention extraction for imported reviews."""

import json
import re
import time
from typing import Any

import httpx
from openai import OpenAI
from pydantic import AliasChoices, BaseModel, Field, ValidationError

from backend.market_review.ai_analysis import _extract_json_object, _is_retryable
from backend.market_review.config import QwenConfig
from backend.market_review.errors import MarketReviewError
from backend.market_review.postgres_storage import PostgresMarketReviewStore


EXTRACTION_VERSION = "review-stock-entities-v5"

# Verified editorial aliases found in imported review prose.  These are explicit
# mappings to official asset-master names, not fuzzy matching.
SECURITY_NAME_ALIASES = {
    "电联技术": "电连技术",
}
NON_TRACKABLE_REFERENCES = {"英伟达", "宇树科技"}


class ReviewStockEntity(BaseModel):
    stock_name: str = Field(
        min_length=2,
        validation_alias=AliasChoices("stock_name", "name"),
        description="原文明确出现的股票、ETF或可交易证券名称",
    )
    ts_code: str | None = Field(default=None, description="原文明确给出的标准代码；不确定时为 null，禁止猜测")
    canonical_theme: str = Field(min_length=1, description="一个标准、可跨日复用的主题名称，例如 mRNA疫苗")
    # “无额外细分概念”是有效事实，不应让模型漏字段导致整篇复盘无法导入。
    concepts: list[str] = Field(default_factory=list, description="原文对应的概念、细分方向或故事关键词；没有则输出空数组")
    # 名单型段落往往只陈述股票和所属方向，未给出单独逻辑或角色。
    # 以“原文提及”显式保留这种未知状态，不将其伪造成核心、跟随等判断。
    story: str = Field(default="原文提及", min_length=1, description="该股票在文中被提及的催化、逻辑或市场叙事；原文未单列时为“原文提及”")
    mention_role: str = Field(default="原文提及", min_length=1, description="如 核心、跟随、容量核心、弹性标的、风险标的、观察标的；原文未说明时为“原文提及”")
    source_excerpt: str = Field(min_length=2, description="能证明该股票被提及的原文短句，必须逐字来自原文")


class ReviewStockExtractionPayload(BaseModel):
    mentions: list[ReviewStockEntity] = Field(description="全文所有明确出现的可交易证券；同一证券只保留一项并合并其最重要逻辑")


def _theme_key(value: str) -> str:
    return re.sub(r"[\s/、·・()（）\-—_]+", "", value).lower()


def canonicalize_theme(value: str) -> tuple[str, str]:
    """Apply deliberately small, auditable synonym rules before grouping."""
    label = re.sub(r"\s+", "", str(value or "")).strip("、/·-—")
    key = _theme_key(label)
    aliases = {
        "mrna": "mRNA疫苗",
        "mrna疫苗": "mRNA疫苗",
        "mrna癌症疫苗": "mRNA疫苗",
        "mrna肿瘤疫苗": "mRNA疫苗",
    }
    label = aliases.get(key, label or "未分类题材")
    return label, _theme_key(label)


def scan_review_stock_links(store: PostgresMarketReviewStore, content: str) -> list[dict[str, str]]:
    """Bind explicit security names/codes in Markdown without using an AI model.

    This scanner is deliberately exact: a token is linkable only when it maps to
    one unique local stock or ETF.  It is used for immediate article reading;
    the later full-text extraction remains responsible for themes and narratives.
    """
    with store.connect() as conn:
        rows = conn.execute(
            """
            select asset_code, name
            from screening_asset_master
            where asset_type in ('stock', 'etf')
            order by asset_code
            """
        ).fetchall()

    candidates: dict[str, tuple[str, str]] = {}
    ambiguous: set[str] = set()

    def add_candidate(label: str, code: str, name: str) -> None:
        token = label.strip()
        if len(token) < 2:
            return
        existing = candidates.get(token)
        if existing is None:
            candidates[token] = (code, name)
        elif existing != (code, name):
            ambiguous.add(token)

    master_by_name: dict[str, tuple[str, str]] = {}
    for row in rows:
        code, name = str(row["asset_code"]), str(row["name"])
        master_by_name[name] = (code, name)
        add_candidate(name, code, name)
        add_candidate(code, code, name)
        add_candidate(code.split(".")[0], code, name)
    for editorial_name, canonical_name in SECURITY_NAME_ALIASES.items():
        resolved = master_by_name.get(canonical_name)
        if resolved:
            add_candidate(editorial_name, *resolved)
    for token in ambiguous:
        candidates.pop(token, None)

    if not candidates or not content:
        return []
    matcher = re.compile("|".join(re.escape(token) for token in sorted(candidates, key=len, reverse=True)))
    links: list[dict[str, str]] = []
    emitted: set[tuple[str, str]] = set()
    for match in matcher.finditer(content):
        label = match.group(0)
        code, name = candidates[label]
        identity = (label, code)
        if identity in emitted:
            continue
        emitted.add(identity)
        links.append({"label": label, "code": code, "name": name})
    return links


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _load_known_themes(store: PostgresMarketReviewStore) -> list[str]:
    with store.connect() as conn:
        rows = conn.execute(
            """
            select canonical_theme, count(*) as n
            from imported_review_stock_mentions
            group by canonical_theme
            order by n desc, canonical_theme asc
            """
        ).fetchall()
    return [str(row["canonical_theme"]) for row in rows]


def _resolve_entity(store: PostgresMarketReviewStore, entity: ReviewStockEntity, content: str) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    # Extraction evidence helps users trace a mention back to the review, but an
    # extra model-recognised stock must not make the entire daily import fail.
    # Binding safety is enforced independently below against the local master.
    source_excerpt = entity.source_excerpt.strip()
    if entity.stock_name in NON_TRACKABLE_REFERENCES:
        # A factual company reference, rather than an A-share/ETF that can open
        # a local K-line. It belongs to the extracted story, not the stock list.
        return None, None

    lookup_name = SECURITY_NAME_ALIASES.get(entity.stock_name, entity.stock_name)

    with store.connect() as conn:
        if entity.ts_code:
            row = conn.execute(
                "select asset_code, name from screening_asset_master where asset_code = %s",
                (entity.ts_code.upper(),),
            ).fetchone()
            if row is None:
                return None, {"stock_name": entity.stock_name, "reason": f"代码 {entity.ts_code} 不在证券主数据中"}
        else:
            rows = conn.execute(
                "select asset_code, name from screening_asset_master where name = %s order by asset_code",
                (lookup_name,),
            ).fetchall()
            # A-share names are sometimes written with a listing suffix in articles
            # (for example “中巨芯-U”), while the Tushare master omits it.  This is
            # a deterministic normalization, never a fuzzy name guess.
            if not rows:
                stripped_name = re.sub(r"-[A-Z]+$", "", lookup_name.upper()).strip()
                if stripped_name and stripped_name != lookup_name:
                    rows = conn.execute(
                        "select asset_code, name from screening_asset_master where name = %s order by asset_code",
                        (stripped_name,),
                    ).fetchall()
            if not rows:
                # Articles often omit a unique listing marker/prefix, such as
                # “宝鹰” for “宝鹰股份” or “嘉立创” for “C嘉立创”.
                rows = conn.execute(
                    """
                    select asset_code, name from screening_asset_master
                    where name like %s or name like %s
                    order by asset_code
                    """,
                    (f"{lookup_name}%", f"%{lookup_name}"),
                ).fetchall()
            if len(rows) != 1:
                reason = "证券主数据中未找到同名证券" if not rows else "同名证券不唯一，无法安全绑定代码"
                return None, {"stock_name": entity.stock_name, "reason": reason}
            row = rows[0]

    theme, key = canonicalize_theme(entity.canonical_theme)
    return {
        "asset_code": str(row["asset_code"]),
        "asset_name": str(row["name"]),
        "mention_name": entity.stock_name.strip(),
        "canonical_theme": theme,
        "theme_key": key,
        "concepts": sorted({str(item).strip() for item in entity.concepts if str(item).strip()}),
        "story": entity.story.strip(),
        "mention_role": entity.mention_role.strip(),
        "source_excerpt": source_excerpt,
    }, None


def _repair_extraction_payload(
    client: OpenAI,
    config: QwenConfig,
    raw: dict[str, Any],
    content: str,
    validation_error: ValidationError,
) -> ReviewStockExtractionPayload:
    """Repair one malformed model response before rejecting the import.

    This is a format correction, not an additional extraction pass: the complete candidate
    list and the same original review are supplied, and every surviving row is validated.
    """
    errors = validation_error.errors(include_url=False)
    prompt = f"""下面的“候选股票提取 JSON”未通过字段完整性校验。请只修复 JSON 结构，返回完整的同一份 JSON 对象，禁止删掉任何候选 mention，禁止补造原文没有的股票或事实。

每个 mention 必须包含：stock_name（或 name）、ts_code（不确定则 null）、canonical_theme、concepts（没有则 []）、story（原文未单独说明则“原文提及”）、mention_role（原文未单独说明则“原文提及”）、source_excerpt（必须是原文连续短句）。
股票名称、canonical_theme、source_excerpt 如无法依据原文补齐，应保留该 mention 并写入最贴近的原文事实；不得用空字符串。

【校验错误】
{json.dumps(errors, ensure_ascii=False)}

【候选股票提取 JSON】
{json.dumps(raw, ensure_ascii=False)}

【原始复盘全文】
{content}
"""
    response = client.responses.create(
        model=config.model,
        instructions="你只输出修复后的完整 JSON 对象，不要输出 Markdown、解释或省略任何 mention。",
        input=prompt,
        reasoning={"effort": "none"},
    )
    repaired = _extract_json_object(str(getattr(response, "output_text", "") or "").strip())
    try:
        return ReviewStockExtractionPayload.model_validate(repaired)
    except ValidationError as exc:
        missing = [".".join(str(part) for part in item["loc"]) for item in exc.errors(include_url=False)]
        raise MarketReviewError(f"复盘股票提取格式修复后仍缺少必填信息：{', '.join(missing)}；未导入该复盘") from exc


def extract_and_store_review_stock_mentions(
    store: PostgresMarketReviewStore,
    trade_date: str,
    content: str,
) -> dict[str, Any]:
    """Extract every explicit stock mention from the full review and persist verified records.

    This is intentionally synchronous: an import is not reported as fully processed until
    the corresponding stock-mention index has been generated and quality-checked.
    """
    try:
        config = QwenConfig.from_env()
        client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=httpx.Timeout(connect=15.0, read=180.0, write=60.0, pool=60.0),
        )
    except ValueError as exc:
        raise MarketReviewError(f"无法初始化百炼复盘股票提取服务: {exc}") from exc

    known_themes = _load_known_themes(store)
    known_hint = "、".join(known_themes) if known_themes else "（目前没有历史题材词表）"
    prompt = f"""你是金融文本信息抽取器，只做事实提取和归类，不写复盘、不推演、不补充原文没有的信息。

请扫描下面整篇A股复盘文章的全部章节，提取每一只可以唯一识别的股票、ETF或可交易证券，不能只看“核心观察”章节。

规则：
1. 只提取原文明确出现且可唯一识别名称或代码的A股、北交所或境内ETF；同一证券全文只保留一条，合并最重要的提及理由。泛称或境外公司不是本系统可跟踪的证券实体：例如原文仅写“通信ETF”而没有完整基金名称或代码、或只写“英伟达”而没有境内证券代码时，应放在 concepts，不得放入 mentions。
2. source_excerpt 必须是原文中的连续短句，不能改写；无法给出原文依据就不要输出该证券。
3. ts_code 仅在原文明确写出时填写，否则填 null；禁止猜测代码。
4. canonical_theme 是用于跨日分组的标准中文名称。优先复用已有词表中的精确含义；同义词必须统一，例如 mRNA、mRNA癌症疫苗、mRNA肿瘤疫苗都归为“mRNA疫苗”。一个证券只选择一个最贴近原文的主分组，避免重复分组。
5. concepts 用于保留细分概念或故事关键词；每条 mention 都必须输出 concepts 字段，没有额外概念时写 []。story 和 mention_role 必须忠实反映文章表达，不能基于行情自行判断；原文没有单独给出时，分别写“原文提及”。
6. 若文章没有任何证券名称，返回空 mentions 数组。

已有题材词表（仅在语义相同的情况下复用）：{known_hint}

交易日期：{trade_date}

复盘文章全文：
{content}
"""
    last_error: Exception | None = None
    for attempt, delay in enumerate((1.0, 2.0, 4.0), start=1):
        try:
            response = client.responses.create(
                model=config.model,
                instructions="你只输出符合要求的 JSON 对象，不要输出 Markdown 或解释。",
                input=prompt,
                reasoning={"effort": "none"},
            )
            raw = _extract_json_object(str(getattr(response, "output_text", "") or "").strip())
            try:
                payload = ReviewStockExtractionPayload.model_validate(raw)
            except ValidationError as validation_error:
                payload = _repair_extraction_payload(client, config, raw, content, validation_error)
            break
        except MarketReviewError:
            raise
        except Exception as exc:
            last_error = exc
            if not _is_retryable(exc) or attempt == 3:
                raise MarketReviewError(f"复盘股票提取请求失败: {exc}") from exc
            time.sleep(delay)
    else:
        raise MarketReviewError(f"复盘股票提取请求失败: {last_error}")

    deduped: dict[str, ReviewStockEntity] = {}
    for entity in payload.mentions:
        key = entity.ts_code.upper() if entity.ts_code else entity.stock_name
        deduped.setdefault(key, entity)

    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []
    for entity in deduped.values():
        item, issue = _resolve_entity(store, entity, content)
        if issue:
            unresolved.append(issue)
        elif item:
            resolved.append(item)

    return store.replace_imported_review_stock_mentions(
        trade_date=trade_date,
        mentions=resolved,
        # 无法绑定的名称保留在提取运行记录中作为显式警告；不阻断其他已
        # 精确绑定股票的写入，也不为它们猜测代码。
        unresolved=unresolved,
        source_stock_count=len(deduped),
        extraction_version=EXTRACTION_VERSION,
    )
