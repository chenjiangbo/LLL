# OpenAI_Base 集成开发手册 V1

本文面向后续维护 LLL 项目的 AI Coder。当前目标是把 OpenAI_Base 作为 LLL 后端内置能力使用，服务于两个场景：

- `stock`：A 股复盘、选股、个股研究
- `office`：报告、合同、复杂 Excel 分析与生成

当前不实现通用 Agent 平台蓝图，不做租户、应用鉴权、Agent Version、MCP、审批、企业知识库、管理后台和前端页面。

## 1. 集成方式

OpenAI_Base 已作为 LLL 后端模块集成在：

```text
backend/openai_base/
```

LLL 原 FastAPI 服务启动后会直接暴露 OpenAI_Base API，不需要单独启动第二个服务。

接入点在：

```python
from backend.openai_base.integration import include_openai_base

include_openai_base(app, market_database_url=database_url)
```

也就是说，仍然只启动 LLL 后端：

```bash
python3 -m uvicorn backend.market_review.api:app --host 127.0.0.1 --port 18080
```

OpenAI_Base 的 Swagger 接口会出现在同一个文档页面：

```text
http://127.0.0.1:18080/docs
```

## 2. 环境变量

在 LLL 项目根目录 `.env` 中增加：

```env
OPENAI_API_KEY=sk-...
AI_BASE_DATA_DIR=data/openai_base
AI_BASE_OPENAI_MODEL=gpt-5.6
```

规则：

- `OPENAI_API_KEY` 必须存在；读取不到就直接报错。
- OpenAI_Base 自己的 run、file、conversation、artifact 元数据直接写入 LLL 的 `MARKET_REVIEW_DATABASE_URL` 对应 PostgreSQL。
- A 股行情数据也读取同一个 PostgreSQL 中的 LLL 行情表。
- 不允许为了让功能跑通而写 mock、样例数据、静默 fallback 数据。

## 3. 对外 API

### 3.1 健康检查

LLL 原接口不变：

```http
GET /health
```

### 3.2 上传文件

```http
POST /v1/files
Content-Type: multipart/form-data
```

字段：

```text
file=<本地文件>
```

返回：

```json
{
  "file_id": "f_xxx",
  "name": "business.xlsx",
  "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "size": 12345,
  "sha256": "...",
  "preflight": {
    "kind": "xlsx",
    "workbook": {
      "sheets": []
    }
  }
}
```

文件会先保存到 `AI_BASE_DATA_DIR/uploads`，并写入 PostgreSQL 的 `openai_base_files` 表。

### 3.3 统一运行

```http
POST /v1/ai/run
Content-Type: application/json
```

A 股复盘：

```json
{
  "profile": "stock",
  "task": "daily_review",
  "input": "复盘 2026-08-10 A股市场，重点分析半导体方向",
  "conversation_id": null,
  "file_ids": [],
  "stream": false
}
```

合同分析：

```json
{
  "profile": "office",
  "task": "contract_review",
  "input": "按我方立场检查主要风险，并给出修改建议",
  "file_ids": ["f_xxx"],
  "stream": false
}
```

复杂 Excel：

```json
{
  "profile": "office",
  "task": "excel_analyze",
  "input": "分析这个工作簿的业务结构和关键问题，数值结论必须用代码核对",
  "file_ids": ["f_xxx"],
  "stream": false
}
```

返回结构：

```json
{
  "run_id": "run_xxx",
  "conversation_id": "conv_xxx",
  "status": "completed",
  "answer": "...",
  "citations": [],
  "artifacts": [],
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0
  },
  "debug": {
    "web_search_used": true,
    "code_interpreter_used": false,
    "market_data_used": true
  }
}
```

### 3.4 下载产物

```http
GET /v1/artifacts/{artifact_id}
```

## 4. Profile 边界

Profile 配置在：

```text
backend/openai_base/profiles/stock.yaml
backend/openai_base/profiles/office.yaml
backend/openai_base/profiles/prompts/stock.md
backend/openai_base/profiles/prompts/office.md
```

当前只允许：

```text
stock
office
```

不要新增通用平台能力。新增 Profile、版本管理或路由策略前必须先确认。

## 5. A 股 market_data 工具

`stock` Profile 会暴露 `market_data` function tool。

LLL 集成版 Provider 在：

```text
backend/openai_base/lll_market_data.py
```

当前支持：

- `market_overview`
- `stock_snapshot`
- `stock_kline`
- `sector_rank`

当前明确不支持：

- `index_quote`
- `money_flow`

如果模型调用不支持的 action，会得到结构化错误，不允许伪造数据。

数据来源：

```text
screening_daily_bar
screening_asset_master
screening_daily_basic
```

质量规则：

- `market_overview` 和 `sector_rank` 要求目标交易日 `screening_daily_bar` 股票行数至少 4000。
- `stock_snapshot` 查不到指定股票和日期时直接报错。
- `stock_kline` 如果返回行数少于请求的 `limit`，直接报错，不静默缩短。
- 日期统一使用 `YYYYMMDD` 写入 PostgreSQL 查询。

如果底层数据不完整，先运行 LLL 数据同步，不要改 Provider 绕过。

## 6. Office 文件链路

文件上传后会执行 deterministic preflight：

- `.xlsx`：提取 Sheet、维度、公式数量、合并单元格、冻结窗格、表格、图表数量。
- `.docx`：检查 document.xml、嵌入媒体数、宏文件。
- `.pdf`：统计页数。

复杂 Excel 任务必须让模型使用 Code Interpreter/Python 检查文件，不允许只根据摘要回答。

## 7. 后续开发约束

必须遵守：

- 核心数据链路不允许抽样、截断、伪数据、静默跳过或隐藏 fallback。
- 核心环境变量读取不到必须报错。
- A 股数字事实必须来自 `market_data` 或 LLL 已入库数据，不允许模型凭记忆编造。
- 新闻、政策、公告等时效事实必须使用 Web Search 并保留引用。
- 修改 Excel/DOCX 时必须生成副本，不能覆盖原始上传文件。
- Artifact 生成后必须回收到本地，并做可打开性或结构校验。

需要调整范围或方案时，先和用户确认。

## 8. 测试

默认测试不调用 OpenAI：

```bash
pytest backend/tests/test_openai_base_integration.py
```

真实 OpenAI 冒烟测试需要单独写入 `AI_BASE_LIVE_OPENAI_TEST=1`，不能默认在 CI 或普通测试中消耗 Key。

## 9. 常见调用方式

LLL 内部 Python 代码如果要直接调用 Runtime：

```python
from backend.openai_base.runtime.runner import AIRunner
from backend.openai_base.schemas.run import AIRunRequest

runner = AIRunner(
    app.state.openai_base_settings,
    app.state.openai_base_repository,
    market_data_provider=app.state.openai_base_market_data_provider,
)

result = runner.run(
    AIRunRequest(
        profile="stock",
        task="daily_review",
        input="复盘 2026-08-10 A股",
    )
)
```

优先通过 HTTP API 调用，只有后端内部编排确实需要时再直接调用 Runtime。
