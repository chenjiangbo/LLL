from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Literal

from google import genai
from google.auth.exceptions import GoogleAuthError
from google.genai import types
from google.oauth2 import service_account
from pydantic import BaseModel, Field, ValidationError

from backend.market_review.config import VertexConfig
from backend.market_review.errors import MarketReviewError
from backend.market_review.json_utils import jsonable
from backend.market_review.postgres_storage import PostgresMarketReviewStore


_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
_PROMPT_VERSION = "market-review-v0.3"


class AIDataQuality(BaseModel):
    status: Literal["intraday", "closing_pending", "final", "partial", "error"]
    message: str


class AITimeframes(BaseModel):
    daily: str
    short_term: str
    medium_term: str
    long_term: str


class AIMarketStructure(BaseModel):
    common_direction: str
    relative_strength: str
    style_interpretation: str
    confidence: Literal["high", "medium", "low"]
    evidence_refs: list[dict[str, Any]]


class AIIndexAttribution(BaseModel):
    index_name: str
    summary: str
    main_positive_sources: list[str]
    main_negative_sources: list[str]
    breadth_interpretation: str
    data_limitations: list[str]


class AIBreadthTurnover(BaseModel):
    summary: str
    breadth_interpretation: str
    turnover_interpretation: str
    short_term_vs_medium_term: str


class AIIndustries(BaseModel):
    top_gainers: list[str]
    top_decliners: list[str]
    breadth_interpretation: str
    summary: str


class AIThemesAndSentiment(BaseModel):
    themes: list[str]
    sentiment_summary: str
    limitations: list[str]


class AIEventDriver(BaseModel):
    fact: str
    possibly_related_market_move: str
    certainty: Literal["confirmed", "possible", "unclear"]


class AIReviewPayload(BaseModel):
    data_quality: AIDataQuality
    headline: str = Field(min_length=1)
    timeframes: AITimeframes
    market_structure: AIMarketStructure
    index_attribution: list[AIIndexAttribution]
    breadth_and_turnover: AIBreadthTurnover
    industries: AIIndustries
    themes_and_sentiment: AIThemesAndSentiment
    events_and_drivers: list[AIEventDriver]
    changes_from_previous_review: list[str]
    conflicting_evidence: list[str]
    unknowns: list[str]
    next_observations: list[str]
    full_review: str = Field(min_length=1)


class MetricItem(BaseModel):
    name: str = Field(description="指标或分类名称，如 上证指数、创业板指、沪深京成交额、上涨股票数、涨停股票数")
    value: str = Field(description="收盘数值或具体表现，如 3822.28点、22287亿元、3642只")
    change: str = Field(description="涨跌幅或变化量，如 +0.33%、增加2174亿元、+5.64%")


class ContextStage(BaseModel):
    stage_name: str = Field(description="阶段名称或日期，如 8月3日：恐慌释放 或 盘中走势特征")
    description: str = Field(description="该阶段的逻辑链条、风格特点与资金运行路线")


class SectorAnalysis(BaseModel):
    sector_name: str = Field(description="板块或主线名称，如 CPO与光通信、半导体设备/材料、煤炭与资源")
    trend_type: str = Field(description="板块状态，如 核心主线、高低切换、内部筛选、回落调整")
    detail: str = Field(description="板块逻辑简述及提及的相关代表个股或细分方向")


class DeepLogicItem(BaseModel):
    topic: str = Field(description="盘面焦点或分化现象，如：为什么上证指数仅平盘而创业板/科创50大涨超4%？、为什么资金从CPO高位切换到半导体/存储芯片？、核电/资源股暴涨背后的产业与资金驱动力？")
    reasoning: str = Field(description="文章中阐述的深层因果逻辑、产业/政策/资金博弈背后的真实原因")


class AIImportedReviewPayload(BaseModel):
    trade_date: str = Field(description="从文章识别出的交易日期，格式 YYYY-MM-DD，如 2026-08-04")
    title: str = Field(min_length=1, description="复盘文章完整标题")
    headline: str = Field(min_length=1, description="核心一句话定性与市场态度总结")
    executive_summary: str = Field(
        description="通俗看盘总述段落（200-300字）。【必须强调硬核数据】使用通俗自然的中文（说人话），用一个连贯段落交待清楚：1.今天大盘指数与成交量（精准包含成交额如2.66万亿、对比前一日放量/缩量具体金额与比例，创业板/科创50/上证指数涨跌幅%）；2.盘面热点与分歧（带头上涨板块、拖累大盘板块、资金热点转向）；3.行情本质与后市操作要点。只要原文有数字，必须精确写出！"
    )
    core_conclusions: list[str] = Field(description="核心结论要点列表（3-5条），【必须包含原文中的关键定量数据，如成交额变化、涨跌家数、指数增幅等】")
    deep_logic_analysis: list[DeepLogicItem] = Field(description="复盘文章中的深度因果归因与逻辑剖析（2-4条），解释为什么某板块涨/为何指数分化背后的真实驱动力")
    market_metrics: list[MetricItem] = Field(description="文章中包含的关键市场行情数据与指标对比表")
    intraday_trend: str = Field(description="盘中走势及阶段表现的梳理总结")
    multi_day_context: list[ContextStage] = Field(description="文章提及的多日演变结构或历史连贯阶段")
    leading_sectors: list[SectorAnalysis] = Field(description="领涨主线、热点板块或板块轮动分析")
    key_takeaways: list[str] = Field(description="交易启示、后市观察点与风险提示")
    full_markdown: str = Field(min_length=1, description="文章的 Markdown 全文")



def _extract_json_object(text: str) -> dict[str, Any]:
    content = (text or "").strip()
    if not content:
        raise MarketReviewError("Vertex returned empty content")
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise MarketReviewError(f"Vertex did not return valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise MarketReviewError("Vertex JSON response must be an object")
    return value


def _is_retryable(exc: Exception) -> bool:
    message = str(exc)
    return any(
        token in message
        for token in (
            "RESOURCE_EXHAUSTED",
            "429",
            "500",
            "503",
            "INTERNAL",
            "UNAVAILABLE",
            "timed out",
            "ECONNRESET",
            "Connection reset by peer",
        )
    )


def _analysis_input(report: dict[str, Any], report_type: str) -> dict[str, Any]:
    industries = {
        "top_gainers": sorted(
            report["industries"], key=lambda item: item["summary_change_pct"], reverse=True
        )[:10],
        "top_decliners": sorted(
            report["industries"], key=lambda item: item["summary_change_pct"]
        )[:10],
    }
    return jsonable(
        {
            "meta": {
                "review_date": report["trade_date"],
                "review_mode": report_type,
                "prompt_version": _PROMPT_VERSION,
                "data_status": report["data_quality"]["status"],
                "data_status_message": report["data_quality"]["message"],
                "snapshot_time": report["data_quality"].get("snapshot_time"),
                "captured_at": report["data_quality"].get("captured_at"),
                "industry_taxonomy": report["data_quality"]["industry_taxonomy"],
                "missing_fields": report["data_quality"]["missing_fields"],
                "sources": report["data_sources"],
            },
            "market": {
                "turnover": {
                    "current": report["breadth"].get("total_amount"),
                    **report["breadth"].get("history", {}),
                },
                "breadth": {
                    "up_count": report["breadth"].get("rising_count"),
                    "down_count": report["breadth"].get("falling_count"),
                    "flat_count": report["breadth"].get("flat_count"),
                    "up_ratio": report["breadth"].get("rising_ratio"),
                    "avg_up_ratio_5d": report["breadth"].get("history", {}).get("avg_rising_ratio_5d"),
                    "avg_up_ratio_20d": report["breadth"].get("history", {}).get("avg_rising_ratio_20d"),
                    "five_index_equal_weight_daily_return": report["breadth"].get("five_index_equal_weight_daily_return"),
                    "quadrant": report["breadth"].get("quadrant"),
                    "technical": report["breadth"]["technical"],
                },
                "sentiment": {
                    "limit_up_count": report["breadth"].get("limit_up_count"),
                    "limit_down_count": report["breadth"].get("limit_down_count"),
                    "failed_limit_count": None,
                    "seal_rate": None,
                    "max_board_height": None,
                    "promotion_rate": None,
                },
            },
            "rule_conclusion": report["core_conclusion"],
            "market_classification": report["market_classification"],
            "indices": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "close": row["close"],
                    "returns": row["returns"],
                    "rankings": row["rankings"],
                    "moving_averages": row["moving_averages"],
                    "internal_breadth": row["internal_breadth"],
                    "direction": row["attribution"].get("direction"),
                    "key_constituents": row["attribution"].get("key_constituents", []),
                }
                for row in report["indices"]
            ],
            "industries": industries,
            "themes": [],
            "events": [],
            "previous_review": {
                "changes": report["core_conclusion"].get("changes_from_previous_review", []),
            },
            "manual_notes": [],
        }
    )


def _input_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class MarketReviewAI:
    store: PostgresMarketReviewStore

    def generate(
        self,
        report: dict[str, Any],
        report_type: Literal["daily", "weekly"] = "daily",
        force: bool = False,
    ) -> dict[str, Any]:
        try:
            config = VertexConfig.from_env()
        except ValueError as exc:
            raise MarketReviewError(str(exc)) from exc
        payload = _analysis_input(report, report_type)
        payload_hash = _input_hash(payload)
        cached = self.store.load_ai_draft(report["trade_date"], report_type)
        if cached and not force and cached["input_hash"] == payload_hash and cached["model"] == config.model:
            return {
                **cached["payload"],
                "meta": {
                    "model": cached["model"],
                    "input_hash": cached["input_hash"],
                    "generated_at": cached["updated_at"],
                    "cached": True,
                    "report_type": report_type,
                },
            }

        result = self._invoke(config, payload, report_type)
        saved = self.store.save_ai_draft(
            trade_date=report["trade_date"],
            report_type=report_type,
            input_hash=payload_hash,
            model=config.model,
            payload=result,
        )
        return {
            **saved["payload"],
            "meta": {
                "model": config.model,
                "input_hash": payload_hash,
                "generated_at": saved["updated_at"],
                "cached": False,
                "report_type": report_type,
            },
        }

    def _invoke(
        self,
        config: VertexConfig,
        payload: dict[str, Any],
        report_type: str,
    ) -> dict[str, Any]:
        try:
            credentials = service_account.Credentials.from_service_account_file(
                str(config.credentials_path), scopes=list(_SCOPES)
            )
            client = genai.Client(
                vertexai=True,
                project=config.project,
                location=config.location,
                credentials=credentials,
            )
        except (GoogleAuthError, ValueError, OSError) as exc:
            raise MarketReviewError(f"failed to initialize Vertex client: {exc}") from exc

        system_prompt = (
            "你是一名谨慎、注重证据的A股市场复盘分析助手。输入结构化数据是唯一事实来源。"
            "严格区分当日盘面、短期变化、中期结构和长期背景。先陈述事实再解释，结论必须可追溯。"
            "指数个股解释只能使用key_constituents和internal_breadth。key_constituents是按个股当日涨跌幅排序，"
            "不是按权重计算的指数贡献，不得称为贡献度或完整归因。"
            "不得猜测国家队、机构或资金主体，不得把单日普涨解释为中期反转。"
            "行业部分只分析当日涨幅前10和跌幅前10，不得使用持续强势、低位修复、持续弱势、退潮等状态标签。"
            "缺失值不得按0处理；成交活跃度没有历史比较时不得判断放量或缩量。"
            "市场广度必须结合指数方向、上涨下跌家数、涨跌停、20日新高新低、站上20日线和60日线比例解释赚钱效应。"
            "指数上涨但上涨家数或均线广度偏弱时，要指出行情集中；指数涨幅有限但广度强时，要指出内部活跃。"
            "breadth_interpretation必须依次解释指数与上涨家数是否一致、20日新高新低与20日线代表的短期结构、"
            "60日线代表的中期结构；short_term_vs_medium_term必须明确短期与中期证据是否冲突以及不能推出什么结论。"
            "数据非final时必须在开头说明并降低确定性。"
            "不得输出A池、B池、候选股、仓位、买卖建议、目标价或行情预测。"
            "事件只能基于输入，不能联网补充。证据冲突时保留冲突，不强行贴唯一标签。"
            "输出必须符合指定JSON结构，不能增加字段，所有内容使用清晰朴素的中文。"
        )
        report_label = "每日简报" if report_type == "daily" else "每周深度复盘"
        user_prompt = (
            f"请根据以下结构化数据生成{report_label}系统初稿。先检查data_status和missing_fields，"
            "再分别总结当日、短期、中期和长期；分析指数相对强弱、关键成分股表现、市场广度、成交、"
            "当日行业领涨领跌结构和上一期变化。最后列出冲突证据、未知问题和下期观察点。"
            "full_review必须与结构化字段一致。\n\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        generation_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=AIReviewPayload,
        )

        last_error: Exception | None = None
        for attempt, delay in enumerate((1.0, 2.0, 4.0), start=1):
            try:
                response = client.models.generate_content(
                    model=config.model,
                    contents=[{"role": "user", "parts": [{"text": user_prompt}]}],
                    config=generation_config,
                )
                raw = _extract_json_object((response.text or "").strip())
                try:
                    return AIReviewPayload.model_validate(raw).model_dump()
                except ValidationError as exc:
                    raise MarketReviewError(f"Vertex response schema validation failed: {exc}") from exc
            except MarketReviewError:
                raise
            except Exception as exc:
                last_error = exc
                if not _is_retryable(exc) or attempt == 3:
                    raise MarketReviewError(f"Vertex request failed: {exc}") from exc
                time.sleep(delay)
        raise MarketReviewError(f"Vertex request failed: {last_error}")

    def parse_imported_review(
        self,
        content: str,
        trade_date: str | None = None,
    ) -> dict[str, Any]:
        try:
            config = VertexConfig.from_env()
        except ValueError as exc:
            raise MarketReviewError(str(exc)) from exc

        try:
            credentials = service_account.Credentials.from_service_account_file(
                str(config.credentials_path), scopes=list(_SCOPES)
            )
            client = genai.Client(
                vertexai=True,
                project=config.project,
                location=config.location,
                credentials=credentials,
            )
        except (GoogleAuthError, ValueError, OSError) as exc:
            raise MarketReviewError(f"failed to initialize Vertex client: {exc}") from exc

        system_prompt = (
            "你是一名顶级的A股复盘分析专家和结构化数据提炼助手。用户会提供一篇手动导入的每日A股复盘文章。\n"
            "你的任务是仔细阅读全篇文本，对其进行精细梳理和标准化结构提炼：\n"
            "1. 提取复盘日期（标准格式 YYYY-MM-DD，若提示中提供了指定日期则优先使用指定日期，否则从标题或文中识别，如 2026-08-04）。\n"
            "2. 提取文章完整标题 title。\n"
            "3. 提取核心一句话定性 headline（简短凝练）。\n"
            "4. 撰写通俗看盘总述段落 executive_summary（200-300字）。【必须“摆事实”、精确包含关键定量数据】使用通俗自然的中文（“说人话”），用一个连贯流畅的段落交待清楚今日盘面全貌：①大盘指数与成交量（收盘点位、涨跌幅%、全天成交额及较昨日放量/缩量的具体金额与比例）；②主要热点板块与资金动向（谁在带头暴涨领跑、哪些权重在压制大盘、龙头股成交额等）；③行情核心结论与后市看点。只要原文中有具体数字，必须精确引用！严禁使用空洞抽象套话。\n"
            "5. 提取核心结论 points (core_conclusions，包含3-5条重点，【必须包含原文中的关键定量数据与差额比率】）。\n"
            "6. 提取深度因果归因与逻辑剖析 deep_logic_analysis（包含2-4个焦点现象与深层逻辑，如：为何上证跌而科创大涨？为何资金从CPO切换半导体？行业爆发背后的产业政策与资金博弈链条）。\n"
            "7. 提取文章中出现的行情数据与主要指标对比 market_metrics（包括上证指数、深证成指、创业板指、科创指数、成交额、上涨/下跌股票数、涨停/跌停数等，按名称、数值、涨跌/变化提炼）。\n"
            "8. 提取盘中走势特征 intraday_trend（包含高开/低开、早盘与午盘走势、资金承接力等）。\n"
            "9. 提取多日演变逻辑或历史连贯阶段 multi_day_context（如文章中提到的连贯数日逻辑演化、前几日表现对比）。\n"
            "10. 提取领涨主线与板块分析 leading_sectors（板块名称、表现状态如领涨/切换/分歧、板块逻辑与细分方向/代表个股）。\n"
            "11. 提取交易启示与后续观察点 key_takeaways。\n"
            "12. 在 full_markdown 中完整保留原始 Markdown 的排版与丰富内容，确保原汁原味可供全貌阅读。\n"
            "请严格按照指定的 JSON 数据 Schema 输出，语言保持朴素通俗、专业且对数字高度敏感。"
        )

        user_prompt = (
            f"【指定交易日期】: {trade_date if trade_date else '未指定（请从文本标题/正文中识别）'}\n\n"
            f"【复盘文章全文内容】:\n{content}"
        )

        generation_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=AIImportedReviewPayload,
        )

        last_error: Exception | None = None
        for attempt, delay in enumerate((1.0, 2.0, 4.0), start=1):
            try:
                response = client.models.generate_content(
                    model=config.model,
                    contents=[{"role": "user", "parts": [{"text": user_prompt}]}],
                    config=generation_config,
                )
                raw = _extract_json_object((response.text or "").strip())
                try:
                    validated = AIImportedReviewPayload.model_validate(raw).model_dump()
                    if trade_date and validated.get("trade_date") != trade_date:
                        validated["trade_date"] = trade_date
                    return validated
                except ValidationError as exc:
                    raise MarketReviewError(f"Vertex import parsing response validation failed: {exc}") from exc
            except MarketReviewError:
                raise
            except Exception as exc:
                last_error = exc
                if not _is_retryable(exc) or attempt == 3:
                    raise MarketReviewError(f"Vertex import request failed: {exc}") from exc
                time.sleep(delay)
        raise MarketReviewError(f"Vertex request failed: {last_error}")

