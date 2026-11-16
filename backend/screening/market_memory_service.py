from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

from backend.screening.storage import PostgresScreeningStore

MARKET_MEMORY_PROMPT_VERSION = "v2.3_historical_flow_balance"
MARKET_PANORAMA_SCHEMA_VERSION = "1.0"
MARKET_PANORAMA_GENERATOR_VERSION = "v1.0_strict"
MARKET_PANORAMA_MAX_TRADING_DAYS = 120
MARKET_PANORAMA_FULL_REBUILD_INTERVAL = 20


def init_market_memory_db_schema(store: PostgresScreeningStore) -> None:
    """初始化 Market Memory 数据库缓存表"""
    with store.connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS screening_market_memory_cache (
                as_of_date VARCHAR(10) PRIMARY KEY,
                lookback_sessions INT NOT NULL,
                reviews_digest VARCHAR(64) NOT NULL DEFAULT '',
                prompt_version VARCHAR(20) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                memory_json JSONB NOT NULL,
                summary_markdown TEXT NOT NULL
            );
            """
        )
        # 版本号用于区分结构化输出契约，历史版本号可能超过早期 20 字符限制。
        conn.execute("ALTER TABLE screening_market_memory_cache ALTER COLUMN prompt_version TYPE VARCHAR(64)")
        conn.commit()


def init_market_panorama_db_schema(store: PostgresScreeningStore) -> None:
    """市场全景独立状态表：不复用题材周期、资金脉络的缓存。"""
    with store.connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS screening_market_panorama_cache (
                as_of_date VARCHAR(10) PRIMARY KEY,
                schema_version VARCHAR(20) NOT NULL,
                window_start_date VARCHAR(10) NOT NULL,
                source_review_count INT NOT NULL,
                last_full_rebuild_date VARCHAR(10) NOT NULL,
                last_full_rebuild_review_count INT NOT NULL,
                reviews_digest VARCHAR(64) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                state_json JSONB NOT NULL,
                summary_markdown TEXT NOT NULL
            );
            """
        )
        conn.execute("ALTER TABLE screening_market_panorama_cache ADD COLUMN IF NOT EXISTS generator_version VARCHAR(32) NOT NULL DEFAULT 'legacy'")
        conn.commit()


def get_cached_market_memory(
    store: PostgresScreeningStore,
    as_of_date: str,
) -> tuple[dict[str, Any], str] | None:
    """仅从数据库缓存中读取已生成的市场全景，不调用大模型"""
    init_market_memory_db_schema(store)
    norm_date = _normalize_date(as_of_date)
    with store.connect() as conn:
        row = conn.execute(
            """
            SELECT memory_json, summary_markdown
            FROM screening_market_memory_cache
            WHERE as_of_date = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (norm_date,),
        ).fetchone()

    if not row:
        return None
    memory_json = row["memory_json"] if isinstance(row["memory_json"], dict) else json.loads(row["memory_json"])
    return memory_json, row["summary_markdown"]


def get_or_create_market_memory(
    store: PostgresScreeningStore,
    as_of_date: str,
    lookback_sessions: int = 120,
    force_refresh: bool = False,
) -> tuple[dict[str, Any], str]:
    """
    滚动增量市场全景推演：
    - 首次/无前日全景：全量初始化（把所有历史复盘一次性输入构建 120 日宏观全景底座）
    - 后续每日：输入【前一日全景深度纪实 Markdown + JSON 摘要】+【当日新导入复盘原文】做滚动增量演进
    确保 120 日长期大周期记忆永不丢失。
    """
    init_market_memory_db_schema(store)
    norm_date = _normalize_date(as_of_date)

    # 1. 读取当日复盘原文（只取当日这 1 篇）
    today_review = _fetch_single_review(store, norm_date)
    # The full window is also used to verify that an incremental base is truly
    # contiguous.  A missing daily memory snapshot must never make us skip that
    # day's original review when processing a later import.
    window_reviews = _fetch_market_reviews_for_memory(store, norm_date, lookback_sessions)

    # 2. 尝试读取最近一次已缓存的全景（前一日或更早）
    prev_memory = _fetch_latest_cached_memory_before(store, norm_date)

    # 3. 构建哈希，判断是否需要重新推演
    previous_review_date = str(window_reviews[-2]["date"]) if len(window_reviews) >= 2 else None
    incremental_is_contiguous = (
        prev_memory is not None
        and previous_review_date is not None
        and str(prev_memory["as_of_date"]) == previous_review_date
    )
    if incremental_is_contiguous:
        prev_json_str = json.dumps(prev_memory["memory_json"], ensure_ascii=False, sort_keys=True)
        prev_md_hash = hashlib.md5(prev_memory.get("summary_markdown", "").encode("utf-8")).hexdigest()
        digest_source = prev_json_str + "|" + prev_md_hash + "|" + (today_review["raw_text"] if today_review else "")
        mode = "incremental"
        all_reviews = None
    else:
        # No previous snapshot, or a gap after a failed daily task: rebuild from
        # every review in the permitted window rather than skipping facts.
        all_reviews = window_reviews
        digest_source = "|".join([f"{r['date']}:{len(r['raw_text'])}" for r in all_reviews])
        mode = "full_init"

    current_digest = hashlib.md5(digest_source.encode("utf-8")).hexdigest()

    # 4. 查询缓存，哈希未变且非强制刷新则直接返回
    if not force_refresh:
        with store.connect() as conn:
            row = conn.execute(
                """
                SELECT memory_json, summary_markdown, reviews_digest
                FROM screening_market_memory_cache
                WHERE as_of_date = %s AND prompt_version = %s
                """,
                (norm_date, MARKET_MEMORY_PROMPT_VERSION),
            ).fetchone()
        if row and row.get("reviews_digest") == current_digest:
            memory_json = row["memory_json"] if isinstance(row["memory_json"], dict) else json.loads(row["memory_json"])
            return memory_json, row["summary_markdown"]

    # Theme-cycle stock names are bound against this table below. Keep the
    # security master current before asking the model to produce a snapshot:
    # otherwise a renamed/newly-listed security can make the whole shared
    # theme+capital-flow cache fail validation even though the review is valid.
    _sync_asset_master_for_snapshot(store)

    # 5. 构造 Prompt 并调用 AI
    if mode == "incremental" and today_review is not None:
        output_text = _call_ai_incremental(prev_memory, today_review, norm_date)
        session_count = prev_memory["memory_json"].get("actual_lookback_sessions", 0) + 1
    elif mode == "incremental" and today_review is None:
        # 有前日全景但当日无复盘 → 直接继承前日全景，不调 AI
        return prev_memory["memory_json"], prev_memory["summary_markdown"]
    else:
        # full_init
        if not all_reviews:
            return (
                {"as_of_date": norm_date, "actual_lookback_sessions": 0, "themes": [], "capital_flows": []},
                "",
            )
        output_text = _call_ai_full_init(all_reviews, norm_date, lookback_sessions)
        session_count = len(all_reviews)

    # 6. 解析并存储
    memory_json, summary_markdown = _parse_market_memory_output(output_text, norm_date, session_count)
    _bind_theme_phase_core_stocks_to_security_master(store, memory_json)

    with store.connect() as conn:
        conn.execute(
            """
            INSERT INTO screening_market_memory_cache
                (as_of_date, lookback_sessions, reviews_digest, prompt_version, created_at, memory_json, summary_markdown)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (as_of_date) DO UPDATE SET
                lookback_sessions = EXCLUDED.lookback_sessions,
                reviews_digest = EXCLUDED.reviews_digest,
                prompt_version = EXCLUDED.prompt_version,
                memory_json = EXCLUDED.memory_json,
                summary_markdown = EXCLUDED.summary_markdown
            """,
            (
                norm_date,
                session_count,
                current_digest,
                MARKET_MEMORY_PROMPT_VERSION,
                datetime.now(UTC),
                json.dumps(memory_json, ensure_ascii=False),
                summary_markdown,
            ),
        )
        conn.commit()

    return memory_json, summary_markdown


def _sync_asset_master_for_snapshot(store: PostgresScreeningStore) -> None:
    """Refresh and validate the listed-stock/ETF master before a new snapshot."""
    project_root = Path(__file__).resolve().parents[2]
    from backend.screening.config import TushareConfig
    from backend.screening.data_sync import ScreeningDataSync
    from backend.screening.tushare_source import TushareScreeningSource

    config = TushareConfig.from_project_env(project_root)
    sync = ScreeningDataSync(TushareScreeningSource(config.token), store)
    started_at = datetime.now(UTC)
    source_counts = sync.sync_assets()

    with store.connect() as conn:
        refreshed_counts = conn.execute(
            """
            SELECT asset_type, COUNT(*) AS count
            FROM screening_asset_master
            WHERE updated_at >= %s
            GROUP BY asset_type
            """,
            (started_at,),
        ).fetchall()

    refreshed = {str(row["asset_type"]): int(row["count"]) for row in refreshed_counts}
    missing = {
        asset_type: int(expected) - refreshed.get(asset_type, 0)
        for asset_type, expected in source_counts.items()
        if refreshed.get(asset_type, 0) < int(expected)
    }
    if missing:
        details = ", ".join(f"{asset_type} 缺少 {count} 条" for asset_type, count in sorted(missing.items()))
        raise RuntimeError(f"证券主数据刷新后入库数量校验失败：{details}")


# ── 内部辅助函数 ──────────────────────────────────────────────────────────────

def _normalize_date(date_str: str) -> str:
    """统一转换为 YYYY-MM-DD 格式"""
    d = date_str.replace("-", "").strip()
    if len(d) == 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return date_str


def _fetch_single_review(
    store: PostgresScreeningStore,
    as_of_date: str,
) -> dict[str, str] | None:
    """读取指定日期的单篇复盘原文（YYYY-MM-DD）"""
    norm = as_of_date.replace("-", "")
    with store.connect() as conn:
        row = conn.execute(
            """
            SELECT trade_date, raw_content
            FROM imported_market_reviews
            WHERE trade_date = %s OR trade_date = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (as_of_date, norm),
        ).fetchone()
    if not row:
        return None
    return {"date": row["trade_date"], "raw_text": row["raw_content"] or ""}


def _fetch_latest_cached_memory_before(
    store: PostgresScreeningStore,
    as_of_date: str,
) -> dict[str, Any] | None:
    """读取 as_of_date 之前最近一条已缓存的市场全景"""
    with store.connect() as conn:
        row = conn.execute(
            """
            SELECT as_of_date, memory_json, summary_markdown
            FROM screening_market_memory_cache
            WHERE as_of_date < %s
            ORDER BY as_of_date DESC
            LIMIT 1
            """,
            (as_of_date,),
        ).fetchone()
    if not row:
        return None
    memory_json = row["memory_json"] if isinstance(row["memory_json"], dict) else json.loads(row["memory_json"])
    return {
        "as_of_date": row["as_of_date"],
        "memory_json": memory_json,
        "summary_markdown": row["summary_markdown"],
    }


def _fetch_market_reviews_for_memory(
    store: PostgresScreeningStore,
    as_of_date: str,
    lookback_sessions: int,
) -> list[dict[str, Any]]:
    """全量初始化用：读取截至 as_of_date 的所有历史复盘原文"""
    norm_date = as_of_date.replace("-", "").strip()
    formatted_date = f"{norm_date[:4]}-{norm_date[4:6]}-{norm_date[6:]}" if len(norm_date) == 8 else as_of_date

    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT trade_date, raw_content
            FROM imported_market_reviews
            WHERE trade_date <= %s OR trade_date <= %s
            ORDER BY trade_date DESC
            LIMIT %s
            """,
            (as_of_date, formatted_date, lookback_sessions),
        ).fetchall()

    return [
        {
            "date": r["trade_date"],
            "raw_text": r["raw_content"] if isinstance(r["raw_content"], str) else json.dumps(r["raw_content"], ensure_ascii=False),
        }
        for r in reversed(rows)
    ]



MARKET_MEMORY_PROMPT_VERSION = "v2.3_historical_flow_balance"  # noqa: F811

_SYSTEM_PROMPT = """你是一名资深 A 股历史资金行为与宏观中观周期演化研究专家。
你的任务是根据历史跨日复盘数据，建立并持续维护一份【120个交易日历史资金演进全景总览】。

核心原则与硬性约束：
1. 本全景是纯粹的【历史回放、归纳与规律总结】，绝非预测工具。严禁包含任何"后市预测"、"后续推演"、"明日观察"、"未来预判"等主观预测内容。
2. 本全景是【120个交易日宏观全景视角】，绝非单日复盘。严禁对最新单日（如当天）进行独立流水账式复盘，单日复盘属于每日文章的任务，本全景只梳理 120 日跨周期的阶段更替、母题兴衰和生态规律。
3. 主题状态客观归纳：CURRENT_ACTIVE（当前活跃）、RECENTLY_ACTIVE（近期活跃）、DORMANT_BUT_TRADED（曾经交易/目前沉寂）、DECAYED（明显衰减）；
4. 所有内容必须严格基于 as_of_date 及以前的历史事实进行客观复述与总结，不使用未来信息。
5. 每个资金阶段必须同时记录正向和负向两面：主攻方向之外，必须从原文事实中提取出现分歧/强弱分化的方向，以及明确资金流出、退潮或被抛售的方向。没有原文依据时填写空数组，禁止猜测或把主攻方向重复填入负向字段。"""


_MARKET_OVERVIEW_EDITOR_PROMPT = """你是一名持续跟踪 A 股情绪、风格和主线迁移的交易研究员。

你将收到一份已有市场研究稿、相应的结构化研究笔记，以及当前观察区间最后一日新增的复盘。请重新组织为一篇完整的《市场全景》。

读者已读过每日复盘。市场全景的任务是让读者理解完整观察区间内市场如何演进、资金如何迁移、哪些转折真正改变了市场，以及当前市场结构处于什么位置。

文章必须包含以下四部分：
1. 区间整体演进：风险偏好、成交环境和主导风格如何变化；
2. 主线与资金迁移：主要方向如何轮动、共振、分化和交接；
3. 关键结构转折：区间内最重要的转折及其对市场格局的影响；
4. 当前市场结构判断：观察区间最后阶段的市场状态，以及最后一日复盘在整段演进中的含义。

最后一日复盘是整段演进的最后一环，应落在“当前市场结构判断”中，不能取代对完整观察区间的解释。

题材周期和资金脉络分别承载方向自身的演化与资金攻防细节。市场全景只在这些事实影响市场整体风险偏好、资金风格或主线格局时引用它们，不重复写成题材或股票清单。

已有研究稿是你此前的研究成果，不是必须逐句保留的原文。请保留仍然成立的重要事实与判断，结合新增复盘修正和重组全文。

所有事实与判断必须能够由提供的研究材料支持；只做截至当前日期的历史分析，不写预测、交易建议或未来情景。

直接输出 Markdown，不输出 JSON、说明或代码块。"""

_OUTPUT_FORMAT = """
请按以下标准结构输出：

1. 先输出标准的 JSON 结构（包裹在 ```json 代码块中）：
```json
{{
  "as_of_date": "{as_of_date}",
  "actual_lookback_sessions": {sessions},
  "themes": [
    {{
      "canonical_name": "主题标准名称 (如 CPO/光通信)",
      "aliases": ["别名1", "别名2"],
      "status": "CURRENT_ACTIVE / RECENTLY_ACTIVE / DORMANT_BUT_TRADED / DECAYED",
      "parent_theme": "母题名称 (如有)",
      "first_seen_date": "YYYY-MM-DD",
      "last_active_date": "YYYY-MM-DD",
      "evolution_summary": "该主题跨长周期的演化脉络概括",
      "key_review_dates": ["YYYY-MM-DD"],
      "phases": [
        {{
          "time_range": "8.04-8.06",
          "stage_name": "阶段名称（如科技修复启动）",
          "description": "该阶段的历史事实与强弱变化",
          "core_stocks": [{{"name": "股票名称", "security_type": "listed_security"}}],
          "non_security_entities": [{{"name": "未上市公司或产业主体", "reason": "未上市/非 A 股可交易证券"}}]
        }}
      ]
    }}
  ],
  "capital_flows": [
    {{
      "time_range": "阶段时间 (如 8.04-8.06, 8.11-8.14 等)",
      "stage_name": "阶段攻防特征 (如 创新药高低切与算力产业链扩散)",
      "main_sectors": ["主攻板块1", "主攻板块2"],
      "core_stocks": ["领涨/核心股1", "核心股2"],
      "divergence_sectors": ["出现分歧/强弱分化的板块1"],
      "divergence_stocks": ["出现分歧的代表股1"],
      "outflow_sectors": ["资金流出/退潮的板块1"],
      "outflow_stocks": ["资金流出/退潮的代表股1"],
      "flow_description": "资金流动特征与攻防逻辑说明",
      "transition_trigger": "触发资金迁移的关键事件或高位负反馈"
    }}
  ]
}}
```

2. 紧接着输出面向专业交易员的【市场演化全景深度纪实】(Markdown 格式)：
必须为 120 个交易日的纯历史回放与宏观总结，严禁包含任何后续预测与单日细节复述！严格按以下四大章节展开：

# 市场演化全景深度纪实（截至 {as_of_date}）

#### 一、 120日资金演化大周期阶段全景（历史回放）
- 系统梳理 120 个交易日（或覆盖的所有历史复盘）内，市场经历的各个大周期阶段；
- 完整记录各阶段的起止时间、主攻主线、阶段攻防特征、重大亏钱效应与关键拐点战役，保留客观历史演进长链条。

#### 二、 核心母题与主线题材生命周期全谱（历史归纳）
- 全景盘点 120 日历史上被资金大规模重仓交易的核心母题（如 AI 算力/CPO/散热、半导体存储/先进封装、创新药/CXO、大众消费等）；
- 客观归纳每个母题从萌芽初见、主升强化、发散扩散、高位分歧到退潮衰减/沉寂的完整演变图景及代表性标的。

#### 三、 资金风格与高标容错生态历史变迁（规律沉淀）
- 总结 120 日跨周期中资金风格偏好的变迁过程（如 20cm 高弹性风格 vs 10cm 连板接力 vs 大市值容量趋势在各历史时期的交替）；
- 客观总结各历史阶段市场对高标断板、核按钮与反包的容错生态变化，提炼资金博弈规律。

#### 四、 120日市场演进核心特征与结构总览（宏观概括）
- 对整段 120 日资金博弈历史进行宏观结构性提炼与客观总结；
- 概括不同板块之间的资金承接关系与资金迁移常态，严禁包含任何针对未来的主观预测、明日推演或操作建议。

正文字数要求：内容严谨详实、结构清晰，建议 2500～3500 个中文字符。"""


def _call_ai_full_init(
    reviews: list[dict[str, str]],
    as_of_date: str,
    lookback_sessions: int,
) -> str:
    """首次全量初始化：把所有历史复盘一次性输入构建 120 日长期全景基底"""
    reviews_text = "\n\n".join([f"【{r['date']} 复盘原文】\n{r['raw_text']}" for r in reviews])
    output_format = _OUTPUT_FORMAT.format(as_of_date=as_of_date, sessions=len(reviews))
    user_prompt = f"""初始化查看日期：{as_of_date}
历史复盘数据总交易日数：{len(reviews)} 天（回溯上限：{lookback_sessions} 天）

【历史每日资金复盘原文长序列】
{reviews_text}

请基于上述历史所有复盘记录，进行纯客观的宏观回放与总结，输出截至 {as_of_date} 的 120 日长期市场演化全景深度纪实（严禁任何预测与后续推演）。
{output_format}"""
    return _run_ai(user_prompt)


def _call_ai_incremental(
    prev_memory: dict[str, Any],
    today_review: dict[str, str],
    as_of_date: str,
) -> str:
    """增量演进：输入前次全景纪实 Markdown + 前次 JSON 摘要 + 今日单篇复盘原文"""
    prev_json_str = json.dumps(prev_memory["memory_json"], ensure_ascii=False, indent=2)
    prev_markdown = prev_memory.get("summary_markdown", "").strip()
    prev_sessions = prev_memory["memory_json"].get("actual_lookback_sessions", 0)
    new_sessions = prev_sessions + 1
    output_format = _OUTPUT_FORMAT.format(as_of_date=as_of_date, sessions=new_sessions)

    user_prompt = f"""增量演进日期：{as_of_date}
前次全景截至：{prev_memory['as_of_date']}，已覆盖 {prev_sessions} 个交易日。

【前次市场演化全景深度纪实（已有长周期历史基底）】
{prev_markdown}

【前次结构化记忆摘要（JSON）】
```json
{prev_json_str}
```

【今日新增复盘原文（{today_review['date']}）】
{today_review['raw_text']}

【增量演进任务与要求】：
1. 你的任务是站在 120 日宏观历史总结视角，在【前次市场演化全景深度纪实】与【前次结构化记忆】的基础上，将【今日新增复盘原文】中的历史新事实融入宏观全景。
2. 必须【完整保留并传承】前次纪实中沉淀的历史大周期演变脉络（一、二、三、四各章节的历史阶段与母题图谱不可删减，而是在宏观大格局中追加/融合最新演变）。
3. 严格遵守【纯历史回放与客观总结】定位：严禁输出任何明日预测、后市推演或未来展望；严禁对最新单日进行孤立的流水账式日报复述。
4. 在 JSON 结构中：`capital_flows` 必须【全量保留】既有所有历史阶段并在尾部追加/更新最新阶段；`themes` 必须维护全量题材的最新状态。
5. `themes[].phases` 必须按时间顺序完整记录该题材在历史复盘中出现的阶段变化（启动、扩散、高位分歧、退潮、修复等）；每个阶段必须给出时间范围、阶段名称、事实描述和核心股票。核心股票只输出原文中的准确股票名称，不能猜测、补写或输出股票代码；股票代码由系统依据本地证券主数据统一绑定。`core_stocks` 只放 A 股或 ETF 等可交易证券；未上市公司、海外公司或产业主体放入 `non_security_entities`，每项必须包含 `name` 和 `reason`，不得伪装成股票。

{output_format}"""
    return _run_ai(user_prompt)


def _rewrite_market_overview_markdown(
    previous_markdown: str,
    memory_json: dict[str, Any],
    today_review: dict[str, str] | None,
    as_of_date: str,
    observation_start: str,
    observation_sessions: int,
) -> str:
    """Rewrite only the market-overview prose; structured theme and flow data stay untouched."""
    today_text = today_review["raw_text"] if today_review else "本次无新增复盘原文。"
    prompt = f"""市场全景观察区间：{observation_start} 至 {as_of_date}，共 {observation_sessions} 个连续复盘交易日。
当前新增复盘日期：{as_of_date}。

此前零散、且不属于上述连续观察区间的历史复盘，不作为本次市场全景的叙事依据。

【已有市场研究稿】
{previous_markdown}

【结构化研究笔记】
```json
{json.dumps(memory_json, ensure_ascii=False, indent=2)}
```

【当天新增复盘】
{today_text}

请重写截至 {as_of_date} 的市场全景。"""
    rewritten = _run_ai(prompt, instructions=_MARKET_OVERVIEW_EDITOR_PROMPT).strip()
    if not rewritten:
        raise RuntimeError("市场全景正文重写未返回有效内容，未覆盖原正文")
    return rewritten


def _continuous_review_window(store: PostgresScreeningStore, as_of_date: str) -> tuple[str, int]:
    """Return the newest uninterrupted weekday review series ending on as_of_date."""
    norm_date = _normalize_date(as_of_date)
    end_day = date.fromisoformat(norm_date)
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT trade_date FROM imported_market_reviews WHERE trade_date <= %s ORDER BY trade_date",
            (norm_date,),
        ).fetchall()
    imported_dates = {date.fromisoformat(str(row["trade_date"])[:10]) for row in rows}
    if end_day not in imported_dates:
        raise RuntimeError(f"{norm_date} 没有已导入复盘，无法确定市场全景观察区间")

    start_day = end_day
    cursor = end_day
    while True:
        previous = cursor - timedelta(days=1)
        while previous.weekday() >= 5:
            previous -= timedelta(days=1)
        if previous not in imported_dates:
            break
        start_day = previous
        cursor = previous

    sessions = sum(1 for imported_day in imported_dates if start_day <= imported_day <= end_day)
    return start_day.isoformat(), sessions


def refresh_market_overview_markdown(
    store: PostgresScreeningStore,
    as_of_date: str,
) -> dict[str, Any]:
    """Refresh only summary_markdown for one cached date, preserving memory_json byte-for-byte."""
    init_market_memory_db_schema(store)
    norm_date = _normalize_date(as_of_date)
    with store.connect() as conn:
        row = conn.execute(
            "SELECT memory_json, summary_markdown FROM screening_market_memory_cache WHERE as_of_date = %s",
            (norm_date,),
        ).fetchone()
    if not row:
        raise RuntimeError(f"{norm_date} 没有已生成的市场全景，无法只更新正文")

    memory_json = row["memory_json"] if isinstance(row["memory_json"], dict) else json.loads(row["memory_json"])
    original_markdown = str(row["summary_markdown"] or "").strip()
    if not original_markdown:
        raise RuntimeError(f"{norm_date} 的市场全景正文为空，无法进行正文重写")
    observation_start, observation_sessions = _continuous_review_window(store, norm_date)
    today_review = _fetch_single_review(store, norm_date)
    rewritten_markdown = _rewrite_market_overview_markdown(
        original_markdown,
        memory_json,
        today_review,
        norm_date,
        observation_start,
        observation_sessions,
    )

    with store.connect() as conn:
        conn.execute(
            "UPDATE screening_market_memory_cache SET summary_markdown = %s WHERE as_of_date = %s",
            (rewritten_markdown, norm_date),
        )
        conn.commit()

    return {
        "as_of_date": norm_date,
        "observation_start": observation_start,
        "observation_sessions": observation_sessions,
        "summary_markdown_updated": True,
        "themes_preserved": len(memory_json.get("themes", [])),
        "capital_flows_preserved": len(memory_json.get("capital_flows", [])),
    }


def _run_ai(user_prompt: str, instructions: str | None = None, json_output: bool = False) -> str:
    """直连阿里云百炼 Responses API；结构化调用启用原生 JSON 输出约束。"""
    import httpx
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
        timeout=httpx.Timeout(connect=15.0, read=600.0, write=60.0, pool=60.0),
    )

    # 启用 stream=True 流式监听，显式关闭思考模式
    request: dict[str, Any] = {
        "model": model,
        "instructions": instructions or _SYSTEM_PROMPT,
        "input": user_prompt,
        # 市场全景的完整历史状态包含阶段、故事、转折和逐日来源，默认输出上限
        # 会截断 JSON。这里显式保留足够空间，后续仍以 Schema 校验决定是否写入。
        "max_output_tokens": 131072,
        "reasoning": {"effort": "none"},
    }
    if json_output:
        # DashScope compatible-mode does not expose Responses `text.format` for
        # every configured model (DeepSeek currently rejects it as unavailable).
        # JSON shape remains enforced by the task prompt and the strict parsers / 
        # domain validators at each call site; do not send an unsupported format.
        response = client.responses.create(**request)
        status = str(getattr(response, "status", "") or "")
        if status and status != "completed":
            raise RuntimeError(f"百炼结构化输出未完整完成（状态：{status}），未写入")
        full_output = str(getattr(response, "output_text", "") or "").strip()
        if not full_output:
            raise RuntimeError("百炼结构化输出未返回有效内容")
        usage = getattr(response, "usage", None)
        if usage:
            print(
                "[QWEN_RESPONSES] Completed: "
                f"input_tokens={getattr(usage, 'input_tokens', 0)}, "
                f"output_tokens={getattr(usage, 'output_tokens', 0)}"
            )
        return full_output

    request["stream"] = True
    response_stream = client.responses.create(
        **request,
    )

    output_chunks: list[str] = []
    # 实时持久化文件，防止中断丢失生成的文字
    dump_path = os.path.join(os.path.dirname(__file__), "last_generated_market_memory.md")
    with open(dump_path, "w", encoding="utf-8") as f_out:
        for event in response_stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if delta:
                    output_chunks.append(delta)
                    f_out.write(delta)
                    f_out.flush()
            elif event_type == "response.completed":
                resp_obj = getattr(event, "response", None)
                usage = getattr(resp_obj, "usage", None) if resp_obj else None
                if usage:
                    in_tok = getattr(usage, "input_tokens", 0)
                    out_tok = getattr(usage, "output_tokens", 0)
                    reason_tok = getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0)
                    print(f"[QWEN_RESPONSES] Completed: input_tokens={in_tok}, reasoning_tokens={reason_tok}, output_tokens={out_tok}")

    full_output = "".join(output_chunks).strip()
    if not full_output:
        raise RuntimeError("百炼 Responses API 流式调用未返回有效文本内容")

    return full_output


_CAPITAL_FLOW_SYSTEM_PROMPT = """你是 A 股历史资金行为研究员。只做历史事实整理，不做预测。
请根据提供的每日复盘原文，提取各阶段的资金脉络。每个阶段必须同时记录主攻、分歧/强弱分化、流出/退潮三个方向；只有原文明确支持的内容才能填写，没有依据就填空数组，禁止猜测、补写或把主攻方向重复到负向字段。"""


def _call_ai_capital_flows(
    reviews: list[dict[str, str]],
    as_of_date: str,
) -> list[dict[str, Any]]:
    """只生成资金脉络，不生成市场全景长文或题材周期。"""
    reviews_text = "\n\n".join(f"【{r['date']} 复盘原文】\n{r['raw_text']}" for r in reviews)
    prompt = f"""截至日期：{as_of_date}
以下是截至该日的历史复盘原文：
{reviews_text}

只输出 JSON 数组，不要输出 Markdown：
[
  {{
    \"time_range\": \"阶段时间\",
    \"stage_name\": \"阶段攻防特征\",
    \"main_sectors\": [],
    \"core_stocks\": [],
    \"divergence_sectors\": [],
    \"divergence_stocks\": [],
    \"outflow_sectors\": [],
    \"outflow_stocks\": [],
    \"flow_description\": \"资金流动与攻防事实\",
    \"transition_trigger\": \"转折事实\"
  }}
]
要求完整覆盖原文中的历史阶段，不得只取样或截断。"""
    output = _run_ai(prompt, instructions=_CAPITAL_FLOW_SYSTEM_PROMPT)
    raw = output.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        flows = json.loads(raw)
    except Exception as exc:
        raise RuntimeError("资金脉络 AI 输出不是有效 JSON，未写入缓存") from exc
    if not isinstance(flows, list):
        raise RuntimeError("资金脉络 AI 输出不是数组，未写入缓存")
    required = ("time_range", "stage_name", "main_sectors", "core_stocks", "divergence_sectors", "outflow_sectors", "flow_description", "transition_trigger")
    for idx, flow in enumerate(flows):
        if not isinstance(flow, dict):
            raise RuntimeError(f"资金脉络第 {idx + 1} 阶段格式无效，未写入缓存")
        missing = [key for key in required if key not in flow or not isinstance(flow[key], (list if key.endswith("sectors") or key.endswith("stocks") else str))]
        if missing:
            raise RuntimeError(f"资金脉络第 {idx + 1} 阶段缺少有效字段: {', '.join(missing)}")
        for key in ("divergence_stocks", "outflow_stocks"):
            if not isinstance(flow.get(key), list):
                flow[key] = []
    return flows


def refresh_capital_flows_for_date(store: PostgresScreeningStore, as_of_date: str) -> dict[str, Any]:
    """只回填指定日期的 capital_flows，保留市场全景 Markdown 和 themes 原值。"""
    norm_date = _normalize_date(as_of_date)
    init_market_memory_db_schema(store)
    with store.connect() as conn:
        row = conn.execute(
            "SELECT memory_json, summary_markdown FROM screening_market_memory_cache WHERE as_of_date = %s",
            (norm_date,),
        ).fetchone()
    if not row:
        raise RuntimeError(f"{norm_date} 没有市场全景缓存，无法只回填资金脉络")
    reviews = _fetch_market_reviews_for_memory(store, norm_date, 120)
    if not reviews:
        raise RuntimeError(f"{norm_date} 没有可用的历史复盘原文，无法回填资金脉络")
    flows = _call_ai_capital_flows(reviews, norm_date)
    memory_json = row["memory_json"] if isinstance(row["memory_json"], dict) else json.loads(row["memory_json"])
    old_markdown = row["summary_markdown"]
    with store.connect() as conn:
        conn.execute(
            "UPDATE screening_market_memory_cache SET memory_json = jsonb_set(memory_json, '{capital_flows}', %s::jsonb, true) WHERE as_of_date = %s",
            (json.dumps(flows, ensure_ascii=False), norm_date),
        )
        conn.commit()
    return {"as_of_date": norm_date, "flow_count": len(flows), "summary_markdown_unchanged": old_markdown == row["summary_markdown"]}


def list_market_memory_dates(store: PostgresScreeningStore) -> list[str]:
    init_market_memory_db_schema(store)
    with store.connect() as conn:
        rows = conn.execute("SELECT as_of_date FROM screening_market_memory_cache ORDER BY as_of_date").fetchall()
    return [str(row["as_of_date"]) for row in rows]


def _parse_market_memory_output(
    output_text: str,
    as_of_date: str,
    actual_sessions: int,
) -> tuple[dict[str, Any], str]:
    """解析 AI 输出的 Market Memory JSON 与 Markdown 报告"""
    memory_json: dict[str, Any] = {
        "as_of_date": as_of_date,
        "actual_lookback_sessions": actual_sessions,
        "themes": [],
        "capital_flows": [],
    }
    summary_markdown = output_text

    json_start = output_text.find("```json")
    if json_start != -1:
        json_end = output_text.find("```", json_start + 7)
        if json_end != -1:
            raw_json_str = output_text[json_start + 7 : json_end].strip()
            try:
                memory_json = json.loads(raw_json_str)
            except Exception:
                raise RuntimeError("市场全景 AI 输出的 JSON 无法解析，未写入缓存")
            summary_markdown = output_text[json_end + 3 :].strip()

    if not isinstance(memory_json, dict):
        raise RuntimeError("市场全景 AI 输出不是对象，未写入缓存")
    capital_flows = memory_json.get("capital_flows")
    if not isinstance(capital_flows, list):
        raise RuntimeError("市场全景缺少有效的资金脉络数组，未写入缓存")
    required_flow_fields = ("main_sectors", "core_stocks", "divergence_sectors", "outflow_sectors")
    for idx, flow in enumerate(capital_flows):
        if not isinstance(flow, dict):
            raise RuntimeError(f"资金脉络第 {idx + 1} 个阶段格式无效，未写入缓存")
        missing = [field for field in required_flow_fields if not isinstance(flow.get(field), list)]
        if missing:
            raise RuntimeError(f"资金脉络第 {idx + 1} 个阶段缺少字段: {', '.join(missing)}，未写入缓存")
        # 可选代表股字段没有依据时允许为空数组，但统一成数组方便前端展示。
        for field in ("divergence_stocks", "outflow_stocks"):
            if not isinstance(flow.get(field), list):
                flow[field] = []

    themes = memory_json.get("themes")
    if not isinstance(themes, list):
        raise RuntimeError("市场全景缺少有效的题材周期数组，未写入缓存")
    for idx, theme in enumerate(themes):
        if not isinstance(theme, dict):
            raise RuntimeError(f"题材周期第 {idx + 1} 项格式无效，未写入缓存")
        phases = theme.get("phases")
        if not isinstance(phases, list):
            raise RuntimeError(f"题材周期 {theme.get('canonical_name', idx + 1)} 缺少阶段时间线，未写入缓存")
        for phase_idx, phase in enumerate(phases):
            if not isinstance(phase, dict):
                raise RuntimeError(f"题材周期第 {idx + 1} 项的阶段 {phase_idx + 1} 格式无效，未写入缓存")
            for field in ("time_range", "stage_name", "description"):
                if not isinstance(phase.get(field), str) or not phase[field].strip():
                    raise RuntimeError(f"题材周期第 {idx + 1} 项的阶段 {phase_idx + 1} 缺少 {field}，未写入缓存")
            stocks = phase.get("core_stocks")
            if not isinstance(stocks, list):
                raise RuntimeError(f"题材周期第 {idx + 1} 项的阶段 {phase_idx + 1} 缺少核心股票，未写入缓存")
            for stock_idx, stock in enumerate(stocks):
                if not isinstance(stock, dict) or not isinstance(stock.get("name"), str) or not stock["name"].strip():
                    raise RuntimeError(f"题材周期第 {idx + 1} 项的阶段 {phase_idx + 1} 核心股票 {stock_idx + 1} 缺少股票名称，未写入缓存")
                security_type = str(stock.get("security_type") or "").strip().lower()
                if security_type and security_type not in {"listed_security", "stock", "etf", "non_listed_company", "non_security_entity", "unlisted_company"}:
                    raise RuntimeError(f"题材周期第 {idx + 1} 项的阶段 {phase_idx + 1} 核心股票 {stock_idx + 1} 的证券类型无效，未写入缓存")
            entities = phase.get("non_security_entities", [])
            if not isinstance(entities, list):
                raise RuntimeError(f"题材周期第 {idx + 1} 项的阶段 {phase_idx + 1} 非证券主体字段格式无效，未写入缓存")
            for entity_idx, entity in enumerate(entities):
                if not isinstance(entity, dict) or not isinstance(entity.get("name"), str) or not entity["name"].strip():
                    raise RuntimeError(f"题材周期第 {idx + 1} 项的阶段 {phase_idx + 1} 非证券主体 {entity_idx + 1} 缺少名称，未写入缓存")
                if not isinstance(entity.get("reason"), str) or not entity["reason"].strip():
                    raise RuntimeError(f"题材周期第 {idx + 1} 项的阶段 {phase_idx + 1} 非证券主体 {entity_idx + 1} 缺少原因，未写入缓存")

    return memory_json, summary_markdown


def _bind_theme_phase_core_stocks_to_security_master(
    store: PostgresScreeningStore,
    memory_json: dict[str, Any],
) -> None:
    """Canonically bind AI-mentioned theme stocks to the local security master.

    A language model may recognize a company name but must never be treated as the
    authority for its exchange code. The name is resolved against the local stock
    master and the canonical code replaces the model-provided value before a theme
    snapshot can be persisted. Missing or non-unique names remain a hard failure
    for entries classified as tradable securities. Explicitly classified
    non-listed companies are retained as evidence-only entities and never receive
    a fabricated code or a K-line binding.
    """
    occurrences: list[tuple[int, int, int, dict[str, Any]]] = []
    names: set[str] = set()
    for theme_index, theme in enumerate(memory_json.get("themes", [])):
        if not isinstance(theme, dict):
            continue
        for phase_index, phase in enumerate(theme.get("phases", [])):
            if not isinstance(phase, dict):
                continue
            for stock_index, stock in enumerate(phase.get("core_stocks", [])):
                if not isinstance(stock, dict):
                    continue
                stock_name = str(stock.get("name") or "").strip()
                if not stock_name:
                    raise RuntimeError(
                        f"题材周期第 {theme_index + 1} 项阶段 {phase_index + 1} 的核心股票 {stock_index + 1} 缺少证券名称，未写入缓存"
                    )
                occurrences.append((theme_index, phase_index, stock_index, stock))
                names.add(stock_name)

    if not names:
        return

    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT name, asset_code
            FROM screening_asset_master
            WHERE asset_type = 'stock' AND name = ANY(%s)
            ORDER BY name, asset_code
            """,
            (list(names),),
        ).fetchall()

    bindings: dict[str, list[str]] = {}
    for row in rows:
        bindings.setdefault(str(row["name"]), []).append(str(row["asset_code"]).upper())

    failures: list[str] = []
    warnings: list[str] = []
    for theme_index, phase_index, stock_index, stock in occurrences:
        stock_name = str(stock["name"]).strip()
        codes = bindings.get(stock_name, [])
        if len(codes) != 1:
            if str(stock.get("security_type") or "").strip().lower() in {
                "non_listed_company",
                "non_security_entity",
                "unlisted_company",
            }:
                stock["ts_code"] = None
                stock["security_status"] = "NON_SECURITY_ENTITY"
                stock["binding_reason"] = "模型明确标记为未上市/非 A 股可交易主体"
                continue
            if str(stock.get("security_type") or "").strip().lower() in {"listed_security", "stock", "etf"}:
                reason = "未在证券主数据中找到" if not codes else f"匹配到多个代码：{', '.join(codes)}"
                failures.append(
                    f"题材周期第 {theme_index + 1} 项阶段 {phase_index + 1} 核心股票 {stock_index + 1} “{stock_name}”{reason}"
                )
                continue
            # 兼容旧模型输出：未携带 security_type 的主体不能安全绑定，
            # 但不能再让一条产业公司名称阻断整份题材周期。显式留下警告，
            # 前端按不可交易主体展示，不生成代码，也不提供 K 线入口。
            stock["ts_code"] = None
            stock["security_status"] = "UNRESOLVED_NON_SECURITY_ENTITY"
            stock["binding_reason"] = "未在证券主数据中找到唯一证券；保留为非交易主体，需人工核对"
            warnings.append(
                f"题材周期第 {theme_index + 1} 项阶段 {phase_index + 1} 核心股票 “{stock_name}”未绑定证券代码，已按非交易主体保留"
            )
            continue
        stock["ts_code"] = codes[0]
        stock["security_type"] = "listed_security"
        stock["security_status"] = "BOUND"

    if warnings:
        memory_json.setdefault("binding_warnings", []).extend(warnings)
    if failures:
        raise RuntimeError("；".join(failures) + "。题材周期未写入缓存")


# ── 独立市场全景状态机 ────────────────────────────────────────────────────────
# 下面这组函数刻意不读写 screening_market_memory_cache。后者仍是题材周期、
# 资金脉络的事实源；市场全景有自己的状态、更新节奏和展示稿。

_MARKET_PANORAMA_FULL_PROMPT = """你是一名专业的A股市场复盘分析器。

你的任务不是总结所有日报，也不是把多份复盘压缩成长文章，而是根据我提供的最近一段时间的原始A股独立复盘文件，重新构建一份“当前市场全景状态”。

市场全景必须回答：当前市场处于什么状态；当前主要资金偏好；哪些市场故事仍然活跃；每个活跃故事当前处于哪一轮 Episode；每个 Episode 处于启动、强化、扩散、分歧、核心集中、修复、高位缩圈、退潮等哪个阶段；当前赚钱与亏钱效应；真正改变判断的变量；市场观察传感器；下一交易日可判卷的未决问题。

不要逐日复述复盘，只保留市场状态转折、Story / Episode 状态转折、真正重要的关键变量和当前仍有用的历史锚点。

Story 是长期稳定故事，不是软件行业标签。同一个 Story 可以有多轮独立行情；如果旧 Episode 已退潮，后续因新变量重新被资金激活，必须创建新 Episode，不能认为旧行情一直延续。生命周期只能使用：watch、new_launch、strengthening、expanding、confirmed、divergence、core_concentration、repair、re_strengthening、high_level_concentration、weakening、retreat、persistent_negative_feedback、retired。

只保留当前仍影响市场判断的 Active Story；近期仍有参考价值的退潮方向放入 retired_stories。变量必须真正改变市场理解，不得把普通涨跌当变量。固定判断大/小、趋势/连板、高/低、成长/防御、集中/扩散、主线/轮动、容量/高价格反应；不知道时允许不确定。

核心观察股总量必须为10至20只，每只必须说明所属 story / episode、角色、为什么观察、强意味着什么、弱意味着什么；不是买入建议。open_questions 必须为3至7个，并可在后续交易日被市场判卷。Active Story 为3至8个，极端最多10个；Retired Story 为5至15个；关键变量为10至20个。

详细分析最近60个交易日；必要时可回看最多120个交易日。120个交易日以外的信息原则上不保留，除非是当前活跃故事必要的历史锚点。

只输出严格合法 JSON，必须符合系统给定的 MarketPanoramaState Schema；禁止 Markdown、解释、额外字段、缺少证据的推断、把退潮后的新启动并入旧 Episode、无限累计故事或观察股。"""


_MARKET_PANORAMA_INCREMENTAL_PROMPT = """你是一名专业的A股市场状态更新器。

你将收到昨日市场全景状态 JSON 与今日独立复盘。你的工作是拿今天的市场给昨天的状态和未决问题判卷，然后输出一份更新后的完整状态 JSON；不是重写一篇今日复盘，也不是把今日内容附加在旧状态后面。

更新顺序必须严格执行：第一，处理昨日 open_questions，逐项标记 confirmed_positive、confirmed_negative、mixed 或 unresolved，并写回相关 Story / Episode / Variable。第二，检查所有 active_stories：昨天状态、按理今天应怎样、实际怎样、是否有新变量、生命周期与优先级如何变化、下一验证是什么。第三，识别新 Story；仅当出现明显群体资金行为与共同故事时创建。第四，若旧 Episode 已 retreat / retired、因全新变量重新形成群体攻击，创建新 Episode。第五，核心补跌、广度消失、连续负反馈或失去信息价值时 retired。第六，更新真正改变优先级的 key_variables。第七，仅证据充分时更新 capital_preferences。第八，更新10至20只 core_sensors。第九，生成3至7个可判卷 open_questions。第十，生成 last_update_changes。

不得保护昨天的判断；今天证伪时必须更新。也不得因一天波动轻易判死长期已确认故事，必须区分正常分歧、核心集中、修复和真正退潮。只有状态变化时新增 state_node；历史已关闭 state_node 默认只读，只有明确 historical_correction 才能修改。

退潮或 retired 的 Episode 不得直接恢复 active；同一 Story 同时只能有0或1个 active Episode；retreat 不得无理由直接跳至 strengthening，必须先 repair 或新建 Episode。所有判断必须由输入材料支持；不作预测、交易建议或未来情景。

只输出严格合法 JSON，不要 Markdown、代码块或解释。"""

_MARKET_PANORAMA_RENDER_PROMPT = """你是一名市场状态报告渲染器。
输入是 market_panorama_state.json。你的任务只是把结构化状态渲染成清晰、紧凑、易读的 market_panorama.md；不得重新推理市场、改变状态、优先级和因果判断，或新增 JSON 中不存在的重要事实。

固定输出结构：
1. 当前市场一句话
2. 当前市场状态
3. 当前资金偏好
4. Active Stories 总表
5. Active Story 详情
6. 当前主要赚钱效应
7. 当前主要亏钱效应
8. 最近关键变量
9. 近期市场状态转折
10. 核心观察股
11. 当前未决问题
12. 近期退潮 / 暂时退出观察
13. 本次更新相较上一版

不要写历史流水账、不要重复；当前信息优先，历史仅作必要锚点。直接输出 Markdown。"""


def _strip_json_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        first_newline = value.find("\n")
        if first_newline == -1:
            raise RuntimeError("市场全景状态输出缺少 JSON 内容，未写入状态")
        value = value[first_newline + 1 :]
        if value.rstrip().endswith("```"):
            value = value.rstrip()[:-3]
    return value.strip()


def _market_panorama_schema_hint(as_of_date: str, window_start: str, source_count: int) -> str:
    return f"""输出 JSON 顶层字段必须且只能包含：
{{
  \"schema_version\": \"{MARKET_PANORAMA_SCHEMA_VERSION}\",
  \"as_of\": \"{as_of_date}\",
  \"window\": {{\"detail_trading_days\": 60, \"max_trading_days\": 120, \"start_date\": \"{window_start}\", \"end_date\": \"{as_of_date}\", \"source_review_count\": {source_count}}},
  \"market_regime\": {{\"summary\": \"\", \"risk_appetite\": \"\", \"liquidity_state\": \"\", \"breadth_state\": \"\", \"market_structure\": \"\", \"trend_quality\": \"\", \"short_term_sentiment\": \"\", \"confidence\": 0.0, \"evidence\": []}},
  \"capital_preferences\": {{\"large_vs_small\": {{\"state\":\"\",\"recent_change\":\"\",\"evidence\":[],\"confidence\":0.0}}, \"trend_vs_limitup\": {{\"state\":\"\",\"recent_change\":\"\",\"evidence\":[],\"confidence\":0.0}}, \"high_vs_low\": {{\"state\":\"\",\"recent_change\":\"\",\"evidence\":[],\"confidence\":0.0}}, \"growth_vs_defensive\": {{\"state\":\"\",\"recent_change\":\"\",\"evidence\":[],\"confidence\":0.0}}, \"concentration_vs_expansion\": {{\"state\":\"\",\"recent_change\":\"\",\"evidence\":[],\"confidence\":0.0}}, \"mainline_vs_rotation\": {{\"state\":\"\",\"recent_change\":\"\",\"evidence\":[],\"confidence\":0.0}}, \"capacity_vs_elasticity\": {{\"state\":\"\",\"recent_change\":\"\",\"evidence\":[],\"confidence\":0.0}}}},
  \"active_stories\": [], \"watchlist_stories\": [], \"retired_stories\": [],
  \"key_variables\": [], \"market_turning_points\": [],
  \"earning_effects\": {{\"positive\": [], \"negative\": []}},
  \"core_sensors\": [], \"open_questions\": [], \"last_update_changes\": [],
  \"source_files\": []
}}

active_stories 每项必须包含 story_id、display_name、mother_theme、current_episode；current_episode 必须包含 episode_id、start_date、trigger、current_state、priority、confidence、status_summary、state_nodes、core_sensors（名称字符串数组）、positive_evidence、negative_evidence、next_validation。state_nodes 每项包含 date、state、summary。earning_effects 的 positive、negative 每项必须包含 name、strength、reason。core_sensors 必须为10至20项；每项必须包含 symbol、name、story_id、episode_id、role、why_watch、if_strong_means、if_weak_means、status。open_questions 每项必须包含 question_id、created_date、question、related_story_ids、validation_signals、status。last_update_changes 每项必须包含 type、target、from、to、reason。"""


def _validate_market_panorama_state(
    state: Any,
    as_of_date: str,
    window_start: str,
    source_count: int,
) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise RuntimeError("市场全景状态不是 JSON 对象，未写入状态")
    required = {
        "schema_version", "as_of", "window", "market_regime", "capital_preferences",
        "active_stories", "watchlist_stories", "retired_stories", "key_variables",
        "market_turning_points", "earning_effects", "core_sensors", "open_questions",
        "last_update_changes", "source_files",
    }
    missing = sorted(required - set(state))
    if missing:
        raise RuntimeError(f"市场全景状态缺少字段: {', '.join(missing)}，未写入状态")
    if state.get("as_of") != as_of_date:
        raise RuntimeError("市场全景状态的 as_of 与请求日期不一致，未写入状态")
    if not isinstance(state.get("window"), dict):
        raise RuntimeError("市场全景状态 window 格式无效，未写入状态")
    window = state["window"]
    if window.get("start_date") != window_start or window.get("end_date") != as_of_date:
        raise RuntimeError("市场全景状态观察区间与实际导入复盘不一致，未写入状态")
    if window.get("max_trading_days") != MARKET_PANORAMA_MAX_TRADING_DAYS:
        raise RuntimeError("市场全景状态未按 120 个交易日上限生成，未写入状态")
    if window.get("source_review_count") != source_count:
        raise RuntimeError("市场全景状态的复盘覆盖数量不正确，未写入状态")
    for name in ("active_stories", "watchlist_stories", "retired_stories", "key_variables", "market_turning_points", "core_sensors", "open_questions", "last_update_changes", "source_files"):
        if not isinstance(state.get(name), list):
            raise RuntimeError(f"市场全景状态 {name} 必须是数组，未写入状态")
    if not isinstance(state.get("market_regime"), dict) or not isinstance(state.get("capital_preferences"), dict):
        raise RuntimeError("市场全景状态核心判断字段格式无效，未写入状态")
    if not isinstance(state.get("earning_effects"), dict):
        raise RuntimeError("市场全景状态赚钱/亏钱效应格式无效，未写入状态")
    if not 3 <= len(state["open_questions"]) <= 7:
        raise RuntimeError("市场全景状态未决问题必须为 3 至 7 个，未写入状态")
    if not 10 <= len(state["core_sensors"]) <= 20:
        raise RuntimeError("市场全景状态核心观察股必须为 10 至 20 只，未写入状态")
    if len(state["active_stories"]) > 10:
        raise RuntimeError("市场全景状态活跃故事超过 10 个，未写入状态")
    def require_object(item: Any, fields: tuple[str, ...], label: str) -> dict[str, Any]:
        if not isinstance(item, dict) or any(field not in item for field in fields):
            raise RuntimeError(f"{label} 不符合 V1.0 Schema，未写入状态")
        return item
    require_object(state["market_regime"], ("summary", "risk_appetite", "liquidity_state", "breadth_state", "market_structure", "trend_quality", "short_term_sentiment", "confidence", "evidence"), "market_regime")
    if not isinstance(state["market_regime"]["evidence"], list) or not isinstance(state["market_regime"]["confidence"], (int, float)):
        raise RuntimeError("market_regime 证据或置信度格式无效，未写入状态")
    preference_keys = ("large_vs_small", "trend_vs_limitup", "high_vs_low", "growth_vs_defensive", "concentration_vs_expansion", "mainline_vs_rotation", "capacity_vs_elasticity")
    for key in preference_keys:
        item = require_object(state["capital_preferences"].get(key), ("state", "recent_change", "evidence", "confidence"), f"capital_preferences.{key}")
        if not isinstance(item["evidence"], list) or not isinstance(item["confidence"], (int, float)):
            raise RuntimeError(f"capital_preferences.{key} 类型无效，未写入状态")
    for story in state["active_stories"]:
        story = require_object(story, ("story_id", "display_name", "mother_theme", "current_episode"), "active_story")
        episode = require_object(story["current_episode"], ("episode_id", "start_date", "trigger", "current_state", "priority", "confidence", "status_summary", "state_nodes", "core_sensors", "positive_evidence", "negative_evidence", "next_validation"), f"Story {story['story_id']} 的 Episode")
        if episode["current_state"] not in {"watch", "new_launch", "strengthening", "expanding", "confirmed", "divergence", "core_concentration", "repair", "re_strengthening", "high_level_concentration", "weakening", "retreat", "persistent_negative_feedback", "retired"}:
            raise RuntimeError(f"Story {story['story_id']} 生命周期无效，未写入状态")
        if not all(isinstance(episode[key], list) for key in ("state_nodes", "core_sensors", "positive_evidence", "negative_evidence", "next_validation")) or not all(isinstance(value, str) for value in episode["core_sensors"]):
            raise RuntimeError(f"Story {story['story_id']} Episode 数组格式无效，未写入状态")
        for node in episode["state_nodes"]:
            require_object(node, ("date", "state", "summary"), f"Story {story['story_id']} 状态节点")
    for effect_kind in ("positive", "negative"):
        values = state["earning_effects"].get(effect_kind)
        if not isinstance(values, list):
            raise RuntimeError(f"earning_effects.{effect_kind} 必须是数组，未写入状态")
        for item in values:
            require_object(item, ("name", "strength", "reason"), f"earning_effects.{effect_kind}")
    for item in state["core_sensors"]:
        require_object(item, ("symbol", "name", "story_id", "episode_id", "role", "why_watch", "if_strong_means", "if_weak_means", "status"), "core_sensor")
    for item in state["open_questions"]:
        require_object(item, ("question_id", "created_date", "question", "related_story_ids", "validation_signals", "status"), "open_question")
    for item in state["last_update_changes"]:
        require_object(item, ("type", "target", "from", "to", "reason"), "last_update_change")
    return state


def _normalize_market_panorama_state(state: Any) -> Any:
    """将模型的等价文本表示收敛到 V1.0 Schema，不补造、不丢弃事实。"""
    if not isinstance(state, dict):
        return state
    for story in state.get("active_stories", []):
        if not isinstance(story, dict):
            continue
        episode = story.get("current_episode")
        if not isinstance(episode, dict):
            continue
        value = episode.get("next_validation")
        if isinstance(value, str):
            normalized = [item.strip() for item in value.replace("；", ";").split(";") if item.strip()]
            if not normalized:
                raise RuntimeError("Episode 下一验证为空，未写入状态")
            episode["next_validation"] = normalized
    return state


def _render_market_panorama_markdown(state: dict[str, Any]) -> str:
    """展示层只渲染状态，不参与二次市场推理。"""
    def names(items: Any) -> str:
        if not isinstance(items, list):
            return ""
        return "、".join(
            str(item.get("name") or item.get("symbol") or "—") if isinstance(item, dict) else str(item)
            for item in items
        )

    def effect_line(item: Any) -> str:
        if isinstance(item, dict):
            return f"{item.get('name', '—')}（{item.get('strength', '—')}）：{item.get('reason', '—')}"
        return str(item)

    def evidence_text(value: Any) -> str:
        if isinstance(value, list):
            return "；".join(str(item) for item in value[:3])
        return str(value or "")

    window = state["window"]
    regime = state["market_regime"]
    effects = state["earning_effects"]
    lines = [
        f"# 市场全景（截至 {state['as_of']}）",
        f"> 观察区间：{window['start_date']} 至 {window['end_date']}，已纳入 {window['source_review_count']} 个交易日复盘。",
        "",
        "## 1. 当前市场一句话",
        str(regime.get("summary") or "市场状态尚待更多复盘证据确认。"),
        "",
        "## 2. 当前市场状态",
        f"- 风险偏好：{regime.get('risk_appetite') or '未形成明确判断'}",
        f"- 流动性：{regime.get('liquidity_state') or '未形成明确判断'}",
        f"- 市场广度：{regime.get('breadth_state') or '未形成明确判断'}",
        f"- 短线情绪：{regime.get('short_term_sentiment') or '未形成明确判断'}",
        f"- 当前结构：{regime.get('market_structure') or '未形成明确判断'}",
        "",
        "## 3. 当前资金偏好",
        "| 维度 | 当前状态 | 最近变化 | 主要证据 |",
        "| --- | --- | --- | --- |",
    ]
    labels = {
        "large_vs_small": "大/小", "trend_vs_limitup": "趋势/连板", "high_vs_low": "高/低",
        "growth_vs_defensive": "成长/防御", "concentration_vs_expansion": "集中/扩散",
        "mainline_vs_rotation": "主线/轮动", "capacity_vs_elasticity": "容量/弹性",
    }
    for key, label in labels.items():
        item = state["capital_preferences"].get(key) or {}
        evidence = evidence_text(item.get("evidence")) or "暂无充分证据"
        lines.append(f"| {label} | {item.get('state') or item.get('preference') or '未形成明确判断'} | {item.get('recent_change') or '—'} | {evidence} |")
    lines.extend(["", "## 4. 活跃故事总表", "| 故事 | 当前 Episode | 当前状态 | 优先级 | 最近变化 | 核心观察 |", "| --- | --- | --- | --- | --- | --- |"])
    for story in state["active_stories"]:
        episode = story.get("current_episode") or {}
        lines.append(f"| {story.get('display_name', story.get('story_id', '未命名'))} | {episode.get('episode_id', '—')} | {episode.get('current_state', '—')} | {episode.get('priority', '—')} | {episode.get('status_summary', '—')} | {names(episode.get('core_sensors')) or '—'} |")
    lines.append("")
    lines.append("## 5. 活跃故事详情")
    for story in state["active_stories"]:
        episode = story.get("current_episode") or {}
        lines.extend([f"### {story.get('display_name', story.get('story_id', '未命名'))}", f"- 当前 Episode：{episode.get('episode_id', '—')}", f"- 本轮起点：{episode.get('start_date', '—')}；触发：{episode.get('trigger', '—')}", f"- 当前状态：{episode.get('current_state', '—')}；{episode.get('status_summary', '—')}", f"- 当前核心：{names(episode.get('core_sensors')) or '—'}", f"- 正向证据：{names(episode.get('positive_evidence')) or '—'}", f"- 负向证据：{names(episode.get('negative_evidence')) or '—'}", f"- 下一验证：{names(episode.get('next_validation')) or '—'}", "- 关键节点："])
        for node in episode.get("state_nodes", []):
            lines.append(f"  - {node.get('date', '—')} · {node.get('state', '—')}：{node.get('summary', '—')}")
        lines.append("")
    lines.extend(["## 6. 当前主要赚钱效应"])
    for item in effects.get("positive", []):
        lines.append(f"- {effect_line(item)}")
    lines.extend(["", "## 7. 当前主要亏钱效应"])
    for item in effects.get("negative", []):
        lines.append(f"- {effect_line(item)}")
    lines.extend(["", "## 8. 最近关键变量"])
    for item in state["key_variables"]:
        lines.append(f"- {item.get('date', '—')} · {item.get('importance', '—')}：{item.get('interpretation') or item.get('actual_result') or '—'}")
    lines.extend(["", "## 9. 近期市场状态转折"])
    for item in state["market_turning_points"]:
        lines.append(f"- {item.get('date', '—')} · {item.get('name', '—')}：{item.get('summary', '—')}")
    lines.extend(["", "## 10. 核心观察股"])
    for item in state["core_sensors"]:
        lines.append(f"- {item.get('name', '—')}（{item.get('symbol', '—')}）：{item.get('role', '—')}；强：{item.get('if_strong_means', '—')}；弱：{item.get('if_weak_means', '—')}")
    lines.extend(["", "## 11. 当前未决问题"])
    for item in state["open_questions"]:
        lines.append(f"- {item.get('question', '—')}（状态：{item.get('status', 'open')}）")
    lines.extend(["", "## 12. 近期退潮 / 暂时退出观察"])
    for item in state["retired_stories"]:
        lines.append(f"- {item.get('display_name', item.get('story_id', '—'))}：{item.get('retire_reason', '—')}")
    lines.extend(["", "## 13. 本次更新相较上一版"])
    for item in state["last_update_changes"]:
        lines.append(f"- {item.get('type', '变化')}：{item.get('target', '—')}；{item.get('reason', '—')}")
    return "\n".join(lines).strip() + "\n"


def get_cached_market_panorama(store: PostgresScreeningStore, as_of_date: str) -> tuple[dict[str, Any], str] | None:
    init_market_panorama_db_schema(store)
    norm_date = _normalize_date(as_of_date)
    with store.connect() as conn:
        row = conn.execute("SELECT state_json, summary_markdown FROM screening_market_panorama_cache WHERE as_of_date = %s AND generator_version = %s", (norm_date, MARKET_PANORAMA_GENERATOR_VERSION)).fetchone()
    if not row:
        return None
    state = row["state_json"] if isinstance(row["state_json"], dict) else json.loads(row["state_json"])
    return state, row["summary_markdown"]


def refresh_market_panorama_render(store: PostgresScreeningStore, as_of_date: str) -> str:
    """仅按既有状态重绘展示稿，不调用 AI、不改变状态事实。"""
    cached = get_cached_market_panorama(store, as_of_date)
    if cached is None:
        raise RuntimeError(f"{_normalize_date(as_of_date)} 没有市场全景状态，无法重绘展示稿")
    state, _ = cached
    markdown = _render_market_panorama_markdown(state)
    with store.connect() as conn:
        conn.execute("UPDATE screening_market_panorama_cache SET summary_markdown = %s WHERE as_of_date = %s", (markdown, _normalize_date(as_of_date)))
        conn.commit()
    return markdown


def _call_ai_market_panorama_full(reviews: list[dict[str, str]], as_of_date: str) -> str:
    review_text = "\n\n".join(f"【{item['date']} 独立复盘】\n{item['raw_text']}" for item in reviews)
    return _run_ai(
        f"观察截止日：{as_of_date}\n观察区间：{reviews[0]['date']} 至 {reviews[-1]['date']}，共 {len(reviews)} 个交易日复盘；窗口上限为 {MARKET_PANORAMA_MAX_TRADING_DAYS} 个交易日。\n\n【原始复盘】\n{review_text}\n\n{_market_panorama_schema_hint(as_of_date, reviews[0]['date'], len(reviews))}",
        instructions=_MARKET_PANORAMA_FULL_PROMPT,
    )


def _call_ai_market_panorama_incremental(previous_state: dict[str, Any], today_review: dict[str, str], reviews: list[dict[str, str]], as_of_date: str) -> str:
    return _run_ai(
        f"观察截止日：{as_of_date}\n观察区间：{reviews[0]['date']} 至 {reviews[-1]['date']}，共 {len(reviews)} 个交易日复盘；窗口上限为 {MARKET_PANORAMA_MAX_TRADING_DAYS} 个交易日。\n\n【昨日市场全景状态】\n{json.dumps(previous_state, ensure_ascii=False, indent=2)}\n\n【今日独立复盘（{today_review['date']}）】\n{today_review['raw_text']}\n\n{_market_panorama_schema_hint(as_of_date, reviews[0]['date'], len(reviews))}",
        instructions=_MARKET_PANORAMA_INCREMENTAL_PROMPT,
    )


def _call_ai_market_panorama_render(state: dict[str, Any]) -> str:
    markdown = _run_ai(json.dumps(state, ensure_ascii=False, indent=2), instructions=_MARKET_PANORAMA_RENDER_PROMPT).strip()
    required_headings = tuple(f"## {index}." for index in range(1, 14))
    if not markdown or any(heading not in markdown for heading in required_headings):
        raise RuntimeError("市场全景展示稿未按 V1.0 固定结构生成，状态未写入")
    return markdown


def get_or_create_market_panorama(store: PostgresScreeningStore, as_of_date: str, force_rebuild: bool = False) -> tuple[dict[str, Any], str, str]:
    """生成独立市场全景；返回状态、展示稿与更新方式。"""
    init_market_panorama_db_schema(store)
    norm_date = _normalize_date(as_of_date)
    reviews = _fetch_market_reviews_for_memory(store, norm_date, MARKET_PANORAMA_MAX_TRADING_DAYS)
    if not reviews:
        raise RuntimeError(f"{norm_date} 没有已导入的复盘原文，无法生成市场全景")
    if reviews[-1]["date"] != norm_date:
        raise RuntimeError(f"{norm_date} 没有已导入的复盘原文，无法生成市场全景")
    digest = hashlib.sha256("|".join(f"{item['date']}:{item['raw_text']}" for item in reviews).encode("utf-8")).hexdigest()
    with store.connect() as conn:
        current = conn.execute("SELECT state_json, summary_markdown, reviews_digest FROM screening_market_panorama_cache WHERE as_of_date = %s AND generator_version = %s", (norm_date, MARKET_PANORAMA_GENERATOR_VERSION)).fetchone()
        previous = conn.execute("SELECT as_of_date, state_json, last_full_rebuild_date, last_full_rebuild_review_count FROM screening_market_panorama_cache WHERE as_of_date < %s AND generator_version = %s ORDER BY as_of_date DESC LIMIT 1", (norm_date, MARKET_PANORAMA_GENERATOR_VERSION)).fetchone()
    if current and current["reviews_digest"] == digest and not force_rebuild:
        state = current["state_json"] if isinstance(current["state_json"], dict) else json.loads(current["state_json"])
        return state, current["summary_markdown"], "cached"
    rebuild_due = previous is None or force_rebuild or len(reviews) - int(previous["last_full_rebuild_review_count"]) >= MARKET_PANORAMA_FULL_REBUILD_INTERVAL
    if rebuild_due:
        raw_output = _call_ai_market_panorama_full(reviews, norm_date)
        update_mode = "full_rebuild"
        full_date, full_count = norm_date, len(reviews)
    else:
        previous_state = previous["state_json"] if isinstance(previous["state_json"], dict) else json.loads(previous["state_json"])
        raw_output = _call_ai_market_panorama_incremental(previous_state, reviews[-1], reviews, norm_date)
        update_mode = "incremental"
        full_date, full_count = previous["last_full_rebuild_date"], int(previous["last_full_rebuild_review_count"])
    try:
        state = _normalize_market_panorama_state(json.loads(_strip_json_fence(raw_output)))
    except json.JSONDecodeError as exc:
        raise RuntimeError("市场全景 AI 输出不是有效 JSON，旧状态未覆盖") from exc
    state = _validate_market_panorama_state(state, norm_date, reviews[0]["date"], len(reviews))
    markdown = _call_ai_market_panorama_render(state)
    with store.connect() as conn:
        conn.execute(
            """INSERT INTO screening_market_panorama_cache
               (as_of_date, schema_version, window_start_date, source_review_count, last_full_rebuild_date, last_full_rebuild_review_count, reviews_digest, created_at, state_json, summary_markdown, generator_version)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
               ON CONFLICT (as_of_date) DO UPDATE SET schema_version = EXCLUDED.schema_version, window_start_date = EXCLUDED.window_start_date, source_review_count = EXCLUDED.source_review_count, last_full_rebuild_date = EXCLUDED.last_full_rebuild_date, last_full_rebuild_review_count = EXCLUDED.last_full_rebuild_review_count, reviews_digest = EXCLUDED.reviews_digest, created_at = EXCLUDED.created_at, state_json = EXCLUDED.state_json, summary_markdown = EXCLUDED.summary_markdown, generator_version = EXCLUDED.generator_version""",
            (norm_date, MARKET_PANORAMA_SCHEMA_VERSION, reviews[0]["date"], len(reviews), full_date, full_count, digest, datetime.now(UTC), json.dumps(state, ensure_ascii=False), markdown, MARKET_PANORAMA_GENERATOR_VERSION),
        )
        conn.commit()
    return state, markdown, update_mode
