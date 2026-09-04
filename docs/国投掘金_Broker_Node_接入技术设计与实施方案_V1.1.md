# 国投证券掘金 Broker Node 接入技术设计与实施方案 V1.1

> 面向 AI Coder 的正式落地设计文档  
> 最后更新：2026-09-02  
> 适用范围：国投证券掘金 3 + `gm.api` + `MODE_LIVE` + Windows 交易节点  
> 本版本已吸收《国投证券「掘金量化交易系统」接入测试与验收方案 V1.2》的测试边界、安全要求、行情能力、订单回调、恢复与回归测试设计。

---

## 0. 文档状态与结论

### 0.1 已完成的技术选型

前期验证已经得到明确结论：

```text
方案 A：gmtrade 独立交易 SDK
结果：不可用于当前国投证券掘金正式接入

方案 B：gm.api + MODE_LIVE
结果：可用
```

因此正式系统只实现方案 B：

```text
主交易系统
    ↓
Windows Broker Node
    ↓
国投掘金实时策略进程
    ↓
gm.api + MODE_LIVE
    ↓
国投仿真账户 / 实盘账户
```

正式代码中不得继续保留 `gmtrade` 的生产 fallback，不得同时维护两套底层驱动。

### 0.2 本文与“券商接口测试控制台”的关系

现有《接入测试与验收方案 V1.2》定义的是一个独立的：

```text
Broker Validation Console
券商接口测试控制台
```

该工具的职责是验证：

- 环境和连接；
- 资金与持仓；
- L1/L2 行情能力；
- 仿真下单、撤单、成交；
- callback 与主动查询一致性；
- T+1；
- 断线、重连和重启恢复；
- 实盘只读与受控实盘写；
- SDK/终端升级后的回归能力。

**Broker Validation Console 不是正式 Broker Node。**

正式系统不得把测试控制台直接改造成生产交易服务，也不得把测试用例执行器、实盘测试页面等混入生产 Broker Node。

正确关系是：

```text
                    ┌─────────────────────────┐
                    │ Broker Validation Console│
                    │ 验证 / 回归 / 诊断       │
                    └───────────┬─────────────┘
                                │ 验证同一套 gm 能力
                                ▼
主交易系统 ───────→ Broker Node ───────→ gm.api + MODE_LIVE
                    生产执行服务
```

如果测试工具中已经存在经过实机验证的：

- gm 调用封装；
- callback 字段样本；
- 订单状态样本；
- 成交字段样本；
- 账户/持仓原始返回；
- 证券代码转换；
- 错误码样本；

则正式项目应优先**提取、复用或转化为 fixture**，不得重新凭文档猜测字段和枚举。

### 0.3 本文是 V1.0 的替代版本

V1.1 对 V1.0 的关键补充是：

1. 正式纳入行情桥接能力；
2. 明确行情 freshness / STALE 状态；
3. 明确 `Trigger Price != Order Limit Price`；
4. 把 `max_acceptable_price` 作为执行层硬保护之一；
5. 明确 T+1 和 `available_volume` 是正式持仓字段；
6. 明确 callback + query + reconcile 三方一致性；
7. 明确 Broker Validation Console 长期保留为回归工具；
8. 将测试方案 Case ID 映射为正式开发验收条件；
9. 明确哪些“测试限制”不能误带进生产交易逻辑。

---

# 1. 系统目标

现有交易系统的业务主链保持不变：

```text
研究 / 自选股
      ↓
TradePlan 交易计划
      ↓ 用户确认
ExecutionPlan 执行计划
      ↓ 执行条件与下单前风控
Order 本地订单
      ↓ BrokerGateway
Windows Broker Node
      ↓
国投掘金 / 券商柜台
      ↓
Order 回报 / Fill 成交 / Position 账户事实
```

Broker Node 的目标不是“再开发一套交易系统”，而是提供一个稳定、受控、可恢复、可审计的券商执行边界。

核心原则：

> 主系统负责“为什么交易、何时交易、交易多少、允许承担什么风险”；Broker Node 负责“把一条已经批准的原子券商命令安全地送到国投掘金，并把券商事实可靠地带回来”。

---

# 2. 设计依据和强约束

## 2.1 现有交易域模型不得重写

正式接入必须保留现有：

```text
TradingAccount
RiskProfile
TradePlan
ExecutionPlan
Order
Fill
Position
```

Broker Node 不拥有 TradePlan，也不拥有 ExecutionPlan 的业务真相。

### 2.1.1 业务事实的归属

| 事实 | 最终归属 |
|---|---|
| 为什么买 | TradePlan |
| 风险预算 | TradePlan / RiskProfile |
| 何时触发执行 | ExecutionPlan |
| 本地订单意图 | 主系统 Order |
| 柜台真实委托 | Broker / 券商 |
| 真实成交 | Broker / 券商 |
| 账户持仓 | Broker / 券商 |
| Broker Node 临时执行记录 | Windows 本地 journal |

## 2.2 不伪造成交

无论任何异常：

- API 返回超时；
- gm callback 丢失；
- Windows 进程崩溃；
- 掘金终端断线；
- 主系统断线；

都不得基于本地价格或执行计划生成假 Fill。

只有：

```text
真实 execution report
或
券商主动查询得到的真实成交
```

才能形成 Fill。

## 2.3 gm.api 的实际函数签名以验证项目为准

测试方案已经对以下能力提出验证要求：

- 账户；
- 持仓；
- 当日委托；
- 未完成委托；
- 当日成交；
- 实时 Tick / L1；
- `on_order_status`；
- `on_execution_report`；
- 连接状态和错误回调；
- 重启后主动查询恢复。

正式实现时：

> AI Coder 必须以已经跑通的 B 方案代码、原始 samples 和历史测试结果为事实来源。

不得从其他版本 SDK 示例中“猜”当前 `gm 3.0.186` 的参数、枚举或返回字段。

---

# 3. 生产架构

## 3.1 总体拓扑

```text
┌─────────────────────────────────────────────────────────┐
│                    主交易系统                           │
│                                                         │
│ TradePlan                                               │
│ ExecutionPlan / ExecutionEngine                         │
│ PreTradeRiskCheck                                       │
│ Order / Fill / Position                                 │
│ BrokerEventConsumer                                     │
│ GMBrokerHttpGateway                                     │
└──────────────────────┬──────────────────────────────────┘
                       │ 私网 HTTP/JSON
                       ▼
┌─────────────────────────────────────────────────────────┐
│                Windows Broker Node                      │
│                                                         │
│  ┌──────────────────────┐                               │
│  │ Broker API Service   │                               │
│  │ HTTP / Auth / DTO    │                               │
│  └─────────┬────────────┘                               │
│            │                                            │
│  ┌─────────▼──────────────────────────────────────────┐  │
│  │ Local Durable Journal / Snapshot Store            │  │
│  │ SQLite WAL                                        │  │
│  │ commands / events / order_links / snapshots       │  │
│  └─────────┬──────────────────────────────────────────┘  │
│            │                                            │
│  ┌─────────▼──────────────────────────────────────────┐  │
│  │ GM Strategy Agent                                │  │
│  │                                                   │  │
│  │ GmCallExecutor                                    │  │
│  │ Account/Order/Fill Synchronizer                   │  │
│  │ Market Data Bridge                                │  │
│  │ Reconciler                                        │  │
│  │ Callback Handlers                                 │  │
│  └─────────┬──────────────────────────────────────────┘  │
└────────────┼────────────────────────────────────────────┘
             │
             ▼
      gm.api + MODE_LIVE
             │
             ▼
        国投证券掘金 3
             │
       仿真 / 实盘柜台
```

## 3.2 为什么保留两个进程

生产节点采用：

```text
Broker API Service
+
GM Strategy Agent
```

而不是在 FastAPI 请求线程中直接导入、调用 `gm.api`。

原因：

1. 掘金运行生命周期与 HTTP 生命周期完全不同；
2. gm 调用线程模型必须复用验证通过的方式；
3. HTTP 并发不能直接变成 gm 并发；
4. API 服务可以独立保持在线并报告 Agent 状态；
5. API 依赖升级不能污染已验证的 Python/gm 环境；
6. 崩溃窗口和命令重放可以通过 durable journal 明确控制。

---

# 4. 生产系统与 Validation Console 的代码关系

## 4.1 推荐仓库关系

如果 Validation Console 已经是独立工程，则保持独立：

```text
broker-validation-console/

broker-node/
```

不要把两个产品合成一个 Web 应用。

## 4.2 允许复用的内容

可抽取一个内部共享包，例如：

```text
guotou_gm_common/
├── raw_models/
├── enum_mapping/
├── security_mapper/
├── callback_normalizer/
└── fixtures/
```

只有经过实机验证且生产需要的部分才进入共享层。

允许复用：

- symbol 转换；
- 账户字段 normalization；
- position 字段 normalization；
- order 状态映射；
- execution report normalization；
- callback 原始样本 fixture；
- SDK/终端版本检测代码；
- 已验证的 gm 调用模式。

## 4.3 禁止复用进生产的内容

Validation Console 中以下内容不得直接进入生产节点：

- 测试 Case Runner；
- “运行全部安全测试”；
- 自动仿真测试序列；
- 实盘测试页面；
- 用户填写测试股票并下单的 UI；
- 测试特有的 100 股限制；
- 测试状态 `PASS/FAIL/WARNING/...` 作为交易状态；
- 测试历史表直接当作生产订单审计表。

特别注意：

> “实盘测试最多 100 股”是验证工具的安全限制，不是正式交易系统的生产交易上限。

生产上限由主系统 RiskProfile / ExecutionPlan 决定；Broker Node 只可额外配置灾难性硬上限防止数量级 bug。

---

# 5. Windows 项目目录

正式项目：

```text
D:\QMT\workspace\broker_node\
```

建议结构：

```text
broker_node\
├── README.md
├── CHANGELOG.md
├── requirements-api.txt
│
├── config\
│   ├── config.example.json
│   └── config.local.json            # gitignored
│
├── shared\
│   ├── enums.py
│   ├── dto.py
│   ├── db.py
│   ├── config.py
│   ├── decimal_utils.py
│   ├── time_utils.py
│   ├── masking.py
│   └── security_id.py
│
├── api_service\
│   ├── app.py
│   ├── auth.py
│   ├── errors.py
│   ├── repositories.py
│   ├── services.py
│   └── routes\
│       ├── health.py
│       ├── status.py
│       ├── account.py
│       ├── positions.py
│       ├── orders.py
│       ├── fills.py
│       ├── market.py
│       ├── events.py
│       ├── commands.py
│       ├── control.py
│       └── diagnostics.py
│
├── gm_agent\
│   ├── main.py                      # 掘金策略入口
│   ├── lifecycle.py
│   ├── gm_adapter.py
│   ├── gm_mapper.py
│   ├── gm_executor.py
│   ├── command_consumer.py
│   ├── callbacks.py
│   ├── account_sync.py
│   ├── order_sync.py
│   ├── fill_sync.py
│   ├── market_bridge.py
│   ├── market_freshness.py
│   └── reconciler.py
│
├── runtime\
│   └── broker_node.sqlite3
│
├── scripts\
│   ├── init_db.py
│   ├── start_api.ps1
│   ├── stop_api.ps1
│   ├── health_check.ps1
│   ├── deploy_gm_agent.ps1
│   └── backup_runtime.ps1
│
└── tests\
    ├── unit\
    ├── integration\
    └── fixtures\
        ├── gm_orders\
        ├── gm_fills\
        ├── gm_positions\
        └── gm_market\
```

日志：

```text
D:\QMT\logs\broker_node\
├── api.log
├── gm_agent.log
├── audit.jsonl
└── reconciliation.log
```

---

# 6. Python 环境

## 6.1 GM Strategy Agent

必须使用当前已经验证的：

```text
C:\Program Files\Python39\python.exe
Python 3.9.13
gm 3.0.186
```

禁止因 Broker Node 开发而：

- 升级 gm；
- 降级 gm；
- 替换 QMT/掘金内置组件；
- 安装 xtquant / xttrader 作为生产依赖；
- 引入 gmtrade fallback。

## 6.2 Broker API Service

建立独立：

```text
.venv-api
```

API Service 不依赖 `gm.api`。

建议依赖：

- FastAPI；
- Uvicorn；
- 与 Python 3.9 兼容的 Pydantic；
- 标准库 sqlite3；
- 其他依赖尽量少。

---

# 7. GM Strategy Agent 的运行模型

## 7.1 本质

虽然它由掘金以“策略”形式运行，但它不是交易策略。

它不产生：

- 买卖信号；
- 选股结果；
- 仓位建议；
- 止损止盈决策；
- 自动加减仓逻辑。

它只是：

```text
命令消费者
+
券商状态采集器
+
行情桥接器
+
回调接收器
+
对账执行器
```

## 7.2 启动流程

Agent 启动：

```text
1. 加载配置
2. 打开本地 SQLite
3. 写入 heartbeat
4. 初始化 gm runtime
5. 等待行情/交易通道状态
6. 获取实际账户
7. 校验账户是否与配置一致
8. 执行 startup reconciliation
9. 刷新账户、持仓、当日订单、未完成订单、当日成交
10. 恢复行情订阅
11. 检查未决 UNKNOWN 命令
12. 决定 READY / PAUSED / RECONCILIATION_REQUIRED
13. 开始消费新命令
```

## 7.3 gm 调用串行化

所有实际 gm 调用统一通过：

```text
GmCallExecutor
```

具体执行线程/上下文**必须照搬 B 方案验证通过的模型**。

禁止：

- HTTP 请求线程直接调用 gm；
- 多个 worker 并发调用 order API；
- callback 内再发复杂同步交易命令；
- 未经验证自行改变 gm event-loop 使用方式。

## 7.4 Callback 原则

以下回调（以验证实际存在的为准）：

```text
on_order_status
on_execution_report
on_account_status
trade connected / disconnected
market connected / disconnected
on_error
```

callback 只做：

```text
接收 raw payload
→ 标准化
→ 幂等写 journal/event
→ 更新必要快照
→ 返回
```

callback 不做：

- TradePlan 判断；
- 新机会生成；
- 策略追价；
- 复杂 DB 查询；
- 长时间阻塞操作。

---

# 8. 本地 SQLite：只做执行型持久化

## 8.1 定位

SQLite 不是第二套业务数据库。

它只保存：

```text
commands       命令队列与幂等
order_links    client_order_id ↔ broker_order_id
broker_events  券商增量事件
gm_snapshots   最新账户事实
market_state   当前订阅行情状态
node_state     节点状态
```

即使 SQLite 损坏，券商事实应能通过重新查询重建；但订单命令的“是否已经发送”存在无法完全由券商自动推断的窗口，因此 journal 必须使用严格落盘策略。

## 8.2 SQLite 配置

初始化：

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;
```

不要在 SQLite 中保存：

- token；
- Windows 密码；
- 主系统 API 密钥。

---

# 9. SQLite 数据表

## 9.1 `node_state`

单节点单行：

```text
node_id
broker_account_key
account_mode                 SIM / LIVE
api_process_status
agent_process_status
market_connection_status
trade_connection_status
broker_account_status
execution_enabled
paused
pause_reason
reconciliation_required
market_default_freshness_ms
last_agent_heartbeat_at
last_broker_event_at
last_account_sync_at
last_order_sync_at
last_market_event_at
updated_at
```

## 9.2 `commands`

```text
command_id                    UUID PK
request_id                    UUID UNIQUE
command_type                  ORDER_SUBMIT / ORDER_CANCEL / SYNC / ...
client_order_id               nullable
payload_hash
payload_json
status
broker_order_id               nullable
error_code                    nullable
error_message                 nullable
created_at
validated_at
claimed_at
dispatched_at
completed_at
updated_at
```

状态：

```text
RECEIVED
VALIDATED
QUEUED
CLAIMED
DISPATCHING
ACKED
REJECTED
FAILED_SAFE
UNKNOWN
```

`UNKNOWN` 的含义：

> 不能确定该券商写命令是否已经到达柜台，因此禁止自动重发。

## 9.3 `order_links`

```text
client_order_id               UNIQUE
submit_command_id
broker_order_id               nullable
exchange_order_id             nullable
last_broker_status
last_raw_status
origin                         SYSTEM / EXTERNAL
created_at
updated_at
```

## 9.4 `broker_events`

```text
seq                            INTEGER AUTOINCREMENT PK
event_id                       UUID UNIQUE
event_type
client_order_id                nullable
broker_order_id                nullable
broker_execution_id            nullable
source                          CALLBACK / QUERY / RECONCILE / NODE
raw_fingerprint                nullable
payload_json
occurred_at                    nullable
received_at
```

## 9.5 `gm_snapshots`

```text
snapshot_type                  ACCOUNT / POSITIONS / ORDERS / FILLS
snapshot_version
as_of
source                          QUERY / RECONCILE
payload_json
updated_at
```

## 9.6 `market_state`

每个订阅证券一行最新状态：

```text
symbol_key
broker_symbol
subscribed
last_price
bid1
bid1_volume
ask1
ask1_volume
market_time_raw
market_time_normalized
received_at
age_ms
freshness_status               FRESH / STALE / DISCONNECTED / UNKNOWN
raw_json
updated_at
```

V1 不把每个 Tick 永久写 SQLite。

如需短期诊断，写 rolling log；历史行情仍进入项目原有行情数据体系，不在 Broker Node 重建行情数据库。

---

# 10. Broker API 基本约定

API：

```text
/api/v1
HTTP/1.1
JSON
UTF-8
```

## 10.1 Decimal

所有价格、资金、金额：

- Python 内部 `Decimal`；
- JSON 传字符串。

例如：

```json
{
  "price": "10.23",
  "available_cash": "152330.18"
}
```

## 10.2 时间

统一：

```text
ISO 8601 +08:00
```

同时保留券商原始时间字段：

```text
broker_time_raw
received_at
```

## 10.3 Broker Account Key

主系统只使用：

```text
guotou_sim_01
guotou_live_01
```

实际券商 account id 只存在 Windows 私有配置中，普通 API 响应默认脱敏。

---

# 11. 健康、连接和运行状态 API

## 11.1 `GET /api/v1/health`

只证明 API Service 活着，不触发 gm 查询。

```json
{
  "ok": true,
  "node_id": "guotou-win-01",
  "server_time": "2026-09-02T20:00:00+08:00"
}
```

## 11.2 `GET /api/v1/status`

```json
{
  "node_id": "guotou-win-01",
  "broker_account_key": "guotou_sim_01",
  "account_mode": "SIM",
  "agent_online": true,
  "market_connected": true,
  "trade_connected": true,
  "account_connected": true,
  "execution_enabled": true,
  "paused": false,
  "reconciliation_required": false,
  "last_agent_heartbeat_at": "...",
  "last_account_sync_at": "...",
  "last_market_event_at": "..."
}
```

## 11.3 `TRADING_READY`

允许新下单必须同时满足：

```text
Agent 心跳新鲜
AND
交易通道已连接
AND
账户连接正常
AND
实际账户 = 预期账户
AND
execution_enabled = true
AND
paused = false
AND
reconciliation_required = false
AND
无 unresolved UNKNOWN submit
AND
若 LIVE：实盘生产开关已开启
```

**行情通道是否必须 FRESH**取决于命令类型：

- 普通人工确认的固定 LIMIT 原子单：可不要求行情新鲜，但主系统必须已完成风控；
- 由实时行情触发的 ExecutionPlan：必须在主系统侧确认触发源行情 FRESH；
- 如果订单请求携带 `require_fresh_market=true`，Broker Node 必须再次检查该证券行情新鲜度。

---

# 12. 账户、持仓、订单、成交 API

## 12.1 账户

```text
GET /api/v1/account
```

返回至少：

```text
total_asset
available_cash
frozen_cash（若实际接口存在）
market_value
as_of
stale
raw
```

具体字段按验证样本映射。

## 12.2 持仓

```text
GET /api/v1/positions
```

标准字段至少：

```text
instrument
quantity
available_quantity
frozen_quantity（若实际接口存在）
cost_price
market_value
raw
```

`available_quantity` 是正式生产字段，不是 UI 可选信息。

它直接关系：

- A 股 T+1；
- 卖出前置校验；
- 主系统 Position 展示；
- 对账。

## 12.3 订单

```text
GET /api/v1/orders?scope=today
GET /api/v1/orders?scope=unfinished
```

## 12.4 成交

```text
GET /api/v1/fills?scope=today
```

任何响应都保持：

```text
normalized fields
+
raw broker payload
```

---

# 13. 正式行情桥接设计

这是 V1.1 新增的生产能力。

测试方案已经明确把实时 L1、Tick、买一卖一、行情 freshness、断线与恢复作为未来交易系统的重要能力，因此 Broker Node 不能只做交易通道而完全不暴露实时行情。

## 13.1 Broker Node 行情职责

Broker Node 只承担**执行所需的实时行情桥接**：

- 指定证券 L1/Tick 订阅；
- 最新价；
- bid1 / ask1 及量；
- 可用时的五档；
- 行情时间戳；
- freshness；
- 连接状态；
- 必要的 1 分钟 Bar（若 ExecutionEngine 确实需要）。

它不是历史行情中心。

## 13.2 订阅 API

建议：

```text
POST /api/v1/market/subscriptions
DELETE /api/v1/market/subscriptions/{symbol}
GET /api/v1/market/subscriptions
```

请求：

```json
{
  "symbols": [
    {"code": "600000", "exchange": "SH"}
  ],
  "level": "L1"
}
```

V1 只承诺 L1。

L2：

```text
CAPABILITY
```

如果无权限，不是 Broker Node 故障。

## 13.3 最新行情 API

```text
GET /api/v1/market/quotes?symbols=...
```

标准响应：

```json
{
  "instrument": {"code": "600000", "exchange": "SH"},
  "last": "10.21",
  "bid1": "10.20",
  "bid1_volume": 3200,
  "ask1": "10.21",
  "ask1_volume": 2500,
  "market_time": "...",
  "received_at": "...",
  "age_ms": 183,
  "freshness": "FRESH",
  "raw": {}
}
```

## 13.4 行情 freshness

统一状态：

```text
FRESH
STALE
DISCONNECTED
UNKNOWN
```

freshness threshold 必须可配置，不能写死在业务代码中。

阈值定义和交易时段内外的判断以验证项目实际表现为基础。

原则：

> “多久没有 Tick 就算 stale”必须考虑停牌、集合竞价、午休、非交易时段，不能用一个无条件固定秒数误判。

V1 可采用：

```text
连接状态
+
交易阶段
+
last market timestamp
+
received_at
```

综合判定。

## 13.5 行情事件

主系统可通过统一事件流获取：

```text
MARKET_QUOTE
MARKET_CONNECTION_CHANGED
MARKET_STALE
MARKET_RECOVERED
```

为避免把所有 Tick 永久存入 durable `broker_events`，建议：

- 订单/成交/连接/对账事件：durable；
- 高频行情：latest-state + 独立轻量 stream/poll；
- 对 ExecutionPlan 有意义的状态变化（FRESH→STALE、触发快照）可 durable。

V1 可先采用 200~500ms quote polling，不强制 WebSocket。

---

# 14. TradePlan / ExecutionPlan 与行情的边界

## 14.1 触发条件属于主系统

例如：

```text
价格进入 10.20 ~ 10.50 区间
```

判断发生在：

```text
ExecutionEngine
```

不发生在 Broker Node。

## 14.2 Trigger Price 与 Order Limit Price 必须分离

正式模型明确：

```text
Trigger Price
!=
Order Limit Price
```

触发条件只决定“现在是否允许创建订单”。

委托价由执行计划单独决定。

禁止：

```text
触发价到了
→ 直接用当前价无约束下单
```

## 14.3 `max_acceptable_price` 的生产硬保护

测试方案特别强调：

```text
任何买入委托价不得超过 max_acceptable_price
```

主系统原本已拥有该约束。

V1.1 增加 defense-in-depth：订单请求可携带：

```json
{
  "safety_constraints": {
    "max_acceptable_price": "10.50",
    "require_fresh_market": true
  }
}
```

Broker Node 在执行前再次检查：

```text
BUY LIMIT price <= max_acceptable_price
```

否则：

```text
FAILED_SAFE
PRICE_GUARD_VIOLATION
```

这不是把 TradePlan 复制进 Broker Node，而是把主系统已经确定的一条**不可突破的执行不变量**随订单一起传递。

Broker Node 不重新计算 max acceptable price，也不知道它为什么是 10.50。

## 14.4 行情失效保护

当订单是由行情触发产生，主系统必须记录：

```text
trigger_quote_time
trigger_quote_price
trigger_quote_freshness
```

并可传：

```text
require_fresh_market=true
```

Broker Node 发单前再次检查：

```text
market connection OK
AND
quote freshness == FRESH
```

如果 stale：

```text
FAILED_SAFE
MARKET_STALE
```

这与测试方案的 `TP-07 / SAFE-11` 对齐。

---

# 15. 下单 API

## 15.1 主系统先创建本地 Order

顺序：

```text
ExecutionPlan 条件满足
→ PreTradeRiskCheck
→ 主系统创建 Order(PENDING_SEND)
→ 调 Broker Node
```

本地：

```text
client_order_id
```

是跨系统幂等键。

## 15.2 `POST /api/v1/orders`

V1 只实现原子 LIMIT 单。

示例：

```json
{
  "request_id": "...",
  "client_order_id": "...",
  "broker_account_key": "guotou_sim_01",
  "instrument": {
    "code": "600000",
    "exchange": "SH"
  },
  "side": "BUY",
  "order_type": "LIMIT",
  "price": "10.23",
  "quantity": 100,
  "source": {
    "trade_plan_id": "...",
    "execution_plan_id": "..."
  },
  "safety_constraints": {
    "max_acceptable_price": "10.50",
    "require_fresh_market": true
  }
}
```

## 15.3 Broker Node 的执行前校验

只做执行层检查：

```text
请求结构合法
账户匹配
SIM/LIVE 模式匹配
TRADING_READY
client_order_id 幂等
quantity > 0
订单类型受支持
证券代码可映射
灾难性数量/金额硬上限
BUY price <= max_acceptable_price（若传入）
require_fresh_market 时行情 FRESH
```

**Broker Node 不重新计算：**

- 单笔风险比例；
- 总仓位；
- 单股仓位；
- 风险参考价；
- 收益风险比；
- 是否应该买。

## 15.4 返回

命令先 durable persist：

```http
202 Accepted
```

```json
{
  "command_id": "...",
  "client_order_id": "...",
  "status": "QUEUED",
  "deduplicated": false
}
```

202 只表示：

```text
Broker Node 已安全接收执行命令
```

不表示：

```text
柜台接受
订单成交
```

---

# 16. 下单幂等与重复提交保护

## 16.1 幂等规则

`client_order_id` 全局唯一。

同 ID + 完全相同 payload：

```text
返回已有命令
不重复下单
deduplicated = true
```

同 ID + 不同 payload：

```text
409 IDEMPOTENCY_CONFLICT
```

## 16.2 防双击与 HTTP 重试

生产系统必须同时处理：

- UI 双击；
- 主系统重试；
- 反向代理重试；
- 超时后人工再次点击；
- Broker Node ACK 丢失。

不能依赖“前端按钮 disable”作为防重复下单的唯一措施。

---

# 17. `DISPATCHING` 崩溃窗口

最危险情况：

```text
本地 command = DISPATCHING
→ 已调用 gm order API
→ 券商可能收到
→ 进程崩溃
→ 本地尚未写 broker_order_id
```

重启后：

```text
DISPATCHING 且无可靠 ACK
→ UNKNOWN
→ reconciliation_required = true
→ execution_enabled = false
```

禁止自动重放。

然后查询：

```text
当日订单
未完成订单
当日成交
```

尝试通过已验证的稳定字段唯一匹配。

如果不能唯一确认：

> 必须人工处理，不能“为了恢复”再发一次。

---

# 18. 订单状态映射

主系统统一状态：

```text
PENDING_SEND
SENT
ACCEPTED
PARTIALLY_FILLED
FILLED
CANCEL_PENDING
CANCELLED
REJECTED
EXPIRED
UNKNOWN
```

实际 gm raw status → normalized status 映射必须来自 Validation Console / B 方案实际样本。

不得：

- 凭其他券商映射；
- 凭别的 gm 版本文档硬编码；
- 把未知状态当 ACCEPTED。

新 raw 状态：

```text
UNKNOWN
+
保留 raw
+
写 warning
```

---

# 19. Fill 成交与幂等

## 19.1 Order 与 Fill 分离

一个 Order 可以：

```text
0 Fill
1 Fill
N Fill
```

部分成交必须正确累计：

```text
filled_quantity
remaining_quantity
filled_vwap
```

## 19.2 成交唯一键

优先：

```text
(broker_account_key, broker_execution_id)
```

如果验证结果证明实际 SDK 没有稳定成交编号，则必须按实际字段设计 deterministic surrogate key。

禁止用随机 UUID 作为“同一成交是否重复”的判断依据。

## 19.3 callback 与 query

同一成交可能：

```text
先从 callback 到
后从 query 再查到
```

必须幂等合并为一条 Fill。

这是 Validation Console `EVT-09 / EVT-10 / REC-10` 在生产系统中的直接落地。

---

# 20. 撤单

## 20.1 API

```text
POST /api/v1/orders/{client_order_id}/cancel
```

请求：

```json
{
  "cancel_request_id": "...",
  "reason": "USER_CANCEL"
}
```

## 20.2 撤单结果

发出 cancel API 不等于撤单成功。

最终状态必须来自：

```text
order status callback
或
主动订单查询
```

## 20.3 已终态订单

如果订单已经：

```text
FILLED
CANCELLED
REJECTED
EXPIRED
```

撤单返回：

```text
ALREADY_TERMINAL
```

不算系统故障。

## 20.4 不实现“券商改单”

V1：

```text
撤旧单
→ 确认旧单终态和剩余数量
→ 新 client_order_id
→ 新 LIMIT 单
```

属于主系统 ExecutionEngine。

---

# 21. T+1 和可卖数量

Validation Console 已将 T+1 作为专门验收组，因此正式系统必须把它作为账户事实，而不是 UI 细节。

## 21.1 Position 必须保存

```text
quantity
available_quantity
frozen_quantity（若有）
```

## 21.2 SELL 前 Broker Node 的最小防错

对于普通股票卖单，在送 gm 前：

```text
requested_quantity <= 最新已知 available_quantity
```

若不满足：

```text
FAILED_SAFE
INSUFFICIENT_AVAILABLE_POSITION
```

但最新可卖数量仍以券商柜台为最终裁决；柜台拒单要保留原始 reason。

## 21.3 跨日恢复

新交易日 startup reconciliation 后：

```text
重新查询 position
→ available_quantity 更新
```

禁止仅根据昨日本地 Fill 自己推算“今天肯定可卖”。

---

# 22. 实时 callback + 周期查询 + 完整 reconcile

生产同步必须是三层：

```text
callback
+
周期 query
+
完整 reconcile
```

## 22.1 Callback

解决快速状态：

- 接受；
- 部分成交；
- 完成；
- 撤单；
- 拒单；
- 连接变化。

## 22.2 周期 query

解决：

- callback 漏失；
- 恢复；
- 主动校验；
- 外部人工委托；
- 进程曾离线。

## 22.3 完整 reconcile

至少读取：

```text
资金
持仓
当日订单
未完成订单
当日成交
```

这与 Validation Console `REC-09` 完全一致。

## 22.4 建议默认间隔

可配置初始值：

```text
command_poll_interval_ms          200
unfinished_order_sync_seconds       5
account_position_sync_seconds      15
full_reconcile_seconds             60
```

这些是工程默认值，不是业务策略参数。

---

# 23. Reconciliation 对账规则

## 23.1 启动对账

每次：

- Agent 启动；
- 交易通道重新连接；
- 账户重新登录；
- 检测到 UNKNOWN；

必须 full reconciliation。

完成前不进入 READY。

## 23.2 外部订单

券商存在、Broker Node 没有 client_order_id 的委托：

```text
origin = EXTERNAL
```

产生：

```text
EXTERNAL_ORDER_FOUND
```

不得自动绑定：

- TradePlan；
- ExecutionPlan；
- 某个本地 Order。

## 23.3 漏成交补齐

query 找到、event journal 不存在的真实成交：

```text
补写 FILL event
source = RECONCILE
```

通过 broker_execution_id 幂等。

## 23.4 持仓差异

主系统 Fill 累计结果与券商 Position 不一致：

```text
券商 Position = 最终账户事实
+
RECONCILIATION_ALERT
```

不能用主系统推算值覆盖券商事实。

## 23.5 进入保护锁定的情况

至少包括：

```text
UNKNOWN submit 无法唯一确认
实际账户变更
成交无法唯一识别
订单数量/状态严重不一致
对账查询关键接口失败
```

进入：

```text
reconciliation_required = true
execution_enabled = false
```

---

# 24. Crash / Disconnect Recovery

## 24.1 API Service 重启

不影响已经运行的 GM Agent。

API 从 SQLite 恢复：

- 命令；
- 事件；
- 快照；
- Agent heartbeat。

## 24.2 GM Agent 重启

```text
QUEUED 且从未 DISPATCHING
→ 可继续
```

```text
DISPATCHING 且无确定 ACK
→ UNKNOWN
→ 不重放
```

然后 full reconciliation。

## 24.3 掘金终端/交易通道断开

立即：

```text
execution_enabled = false
TRADE_CONNECTION_CHANGED
```

不假设已有挂单被撤。

恢复后：

```text
重新查询
→ reconcile
→ 确认无异常
→ 才允许 resume
```

## 24.4 行情断开

行情变：

```text
DISCONNECTED
```

对固定、人工确认的原子订单是否完全禁止，由订单 `require_fresh_market` 决定。

但：

> 任何由行情条件自动触发的新订单必须阻断。

## 24.5 主系统断开

Broker Node：

- 不自行产生新订单；
- 继续收 callback；
- 继续保存成交；
- 继续同步券商状态。

主系统恢复后按 event seq 补齐。

---

# 25. 事件传输

## 25.1 Durable 事件

至少：

```text
BROKER_CONNECTION_CHANGED
ACCOUNT_STATUS_CHANGED
ORDER_SUBMIT_RESULT
ORDER_STATUS
FILL
COMMAND_STATUS
EXTERNAL_ORDER_FOUND
RECONCILIATION_ALERT
NODE_PAUSED
NODE_RESUMED
MARKET_CONNECTION_CHANGED
MARKET_STALE
MARKET_RECOVERED
```

## 25.2 API

```text
GET /api/v1/events?after_seq=12345&limit=500
```

语义：

```text
at-least-once
```

主系统必须幂等消费。

## 25.3 行情 Tick 不走 durable event 全量账本

否则数据库会被大量 Tick 淹没。

V1：

- quote latest state：API 拉取；
- 行情连接/freshness 状态：durable event；
- 未来如需要更实时，可加 WebSocket / SSE，但不是 P0。

---

# 26. 主系统 `GMBrokerHttpGateway`

现有 BrokerGateway 新增实现：

```text
GMBrokerHttpGateway
```

概念接口：

```python
class GMBrokerHttpGateway(BrokerGateway):
    def get_status(self): ...
    def get_account(self): ...
    def get_positions(self): ...
    def get_orders(self): ...
    def get_fills(self): ...
    def subscribe_market(self, instruments): ...
    def get_quotes(self, instruments): ...
    def place_order(self, order): ...
    def cancel_order(self, order): ...
```

TradePlan / ExecutionPlan 不直接拼 HTTP。

## 26.1 BrokerEventConsumer

主系统按 account 保存：

```text
last_consumed_event_seq
```

事务：

```text
拉 events
→ 幂等更新 Order / Fill / broker Position facts
→ 更新 last_consumed_event_seq
→ COMMIT
```

只有 commit 后才能推进 seq。

---

# 27. 主系统 Order / Fill / Position 更新

## 27.1 Order

```text
创建本地 Order
→ PENDING_SEND
```

Broker Node 202：

```text
最多进入 SENT/QUEUED 语义
```

不能当 ACCEPTED。

真实柜台 callback/query 才能：

```text
ACCEPTED
PARTIALLY_FILLED
FILLED
...
```

## 27.2 Fill

只来自真实券商事实。

## 27.3 Position

主系统可以基于 Fill 做快速增量更新，但必须周期性以券商 Position 纠正。

特别是：

```text
available_quantity
```

不能单靠本地 Fill 推断。

---

# 28. 全局暂停

## 28.1 `POST /api/v1/control/pause`

效果：

```text
execution_enabled=false
```

不自动撤现有订单。

## 28.2 Resume

只有：

```text
Agent online
trade connected
account match
reconciliation_required=false
no unresolved UNKNOWN
生产 LIVE gate 满足
```

才能恢复。

## 28.3 “暂停并撤单”必须独立

正式系统可提供：

```text
POST /api/v1/control/pause-and-cancel-open-orders
```

但必须逐笔撤单、逐笔确认。

不得使用危险的“一键全部实盘批量 API”作为 V1 默认实现。

---

# 29. SIM / LIVE 强隔离

## 29.1 节点配置

```json
{
  "broker_account_key": "guotou_sim_01",
  "account_mode": "SIM",
  "expected_broker_account_id": "..."
}
```

一个 GM Agent 运行实例只绑定一个预期账户。

不允许“请求里随便传 account id 然后切账户”。

## 29.2 生产实盘开关

实盘生产节点建议至少两个来源的 gate：

```text
config: allow_live_orders=true
+
env: BROKER_NODE_ENABLE_LIVE_ORDERS=YES
```

但注意：

> 这是生产节点开关，不是 Validation Console 的 LIVE_WRITE 测试开关。

两者配置和审计必须独立。

## 29.3 账户不匹配

实际绑定账户 ≠ expected：

```text
ACCOUNT_MISMATCH
READ_ONLY_LOCKED
```

查询允许，新的交易写禁止。

---

# 30. Broker Node 灾难性硬保护

Broker Node 不复制主系统风险模型，但可以有极少量防 bug 上限：

```text
max_single_order_quantity
max_single_order_notional
allowed_exchanges
allowed_security_types
```

用途：

> 防止程序 bug 把“100 股”错误变成“100000 股”之类数量级事故。

这些值是运维安全阈值，不是交易策略。

生产默认值由用户/系统部署阶段配置，不能直接照抄 Validation Console 的“100 股”。

---

# 31. 证券标识映射

主系统证券标识保持原样。

Broker 边界实现：

```text
SecurityIdMapper
```

职责：

```text
主系统 code + exchange
↔
GM symbol
```

V1 至少覆盖当前交易范围：

- A 股主板；
- 创业板；
- 股票 ETF；
- 科创板相关 ETF。

所有映射必须有单元测试。

---

# 32. 错误码

统一节点级错误码至少：

```text
AUTH_FAILED
INVALID_REQUEST
ACCOUNT_MISMATCH
BROKER_ACCOUNT_OFFLINE
GM_AGENT_OFFLINE
TRADE_CONNECTION_DOWN
MARKET_CONNECTION_DOWN
MARKET_STALE
NODE_PAUSED
LIVE_TRADING_DISABLED
RECONCILIATION_REQUIRED
IDEMPOTENCY_CONFLICT
PRICE_GUARD_VIOLATION
INSUFFICIENT_AVAILABLE_POSITION
ORDER_NOT_FOUND
ORDER_ALREADY_TERMINAL
ORDER_REJECTED_BY_BROKER
SUBMIT_UNKNOWN
CANCEL_UNKNOWN
STALE_SNAPSHOT
UNSUPPORTED_ORDER_TYPE
INTERNAL_ERROR
```

异步券商拒单：

```text
ORDER_REJECTED_BY_BROKER
+
raw error code
+
raw reject reason
```

不要把所有券商错误统一成 HTTP 500。

---

# 33. 网络和鉴权

## 33.1 V1 网络

当前 Windows 是局域网交易节点。

V1：

```text
HTTP + Bearer Token + Windows Firewall IP 限制
```

不要暴露公网交易端口。

## 33.2 将来跨机器/跨网

如果主系统迁移到云端或异地：

优先：

```text
Tailscale / WireGuard / 企业 VPN
```

再考虑：

```text
HTTPS / mTLS
```

不要尝试破解或猜测掘金未公开的远程协议。

## 33.3 Token

不得：

- 写 Git；
- 写 Markdown；
- 打普通日志；
- 放前端浏览器持久化。

---

# 34. 日志和审计

## 34.1 `api.log`

记录：

```text
request_id
endpoint
client_order_id（如有）
command_id
HTTP status
latency
```

## 34.2 `gm_agent.log`

记录：

```text
agent lifecycle
connection changes
command claim/dispatch
query/reconcile
callback processing
market subscriptions
```

## 34.3 `audit.jsonl`

关键事实：

```text
ORDER_COMMAND_RECEIVED
ORDER_DISPATCH_STARTED
ORDER_DISPATCH_ACK
ORDER_STATUS
FILL
CANCEL_COMMAND_RECEIVED
PAUSE
RESUME
ACCOUNT_MISMATCH
RECONCILIATION_ALERT
LIVE_GATE_CHANGED
```

## 34.4 脱敏

账号：

```text
****1234
```

token/API secret 绝不输出。

---

# 35. Diagnostics：与 Validation Console 配合

生产 Broker Node 只提供轻量只读 diagnostics：

```text
GET /api/v1/diagnostics/environment
GET /api/v1/diagnostics/capabilities
GET /api/v1/diagnostics/last-reconciliation
```

内容例如：

```text
OS
Python version
gm version
终端版本（若验证代码可可靠获取）
market connected
trade connected
account mode
capabilities
```

但不要把 Validation Console 的完整 Case Runner 内嵌进生产服务。

Regression 应继续由 Validation Console 执行。

---

# 36. 能力声明 Capability Model

正式节点启动时生成能力快照：

```json
{
  "account_query": true,
  "position_query": true,
  "order_query": true,
  "fill_query": true,
  "limit_order": true,
  "cancel_order": true,
  "l1_quote": true,
  "five_level_book": false,
  "l2_trade": false,
  "l2_order": false
}
```

能力应来自：

- 已验证版本；
- 当前权限；
- 实际 runtime 检测。

无 L2 权限是：

```text
NOT_SUPPORTED/CAPABILITY_FALSE
```

不是生产节点失败。

---

# 37. 部署方式

## 37.1 Broker API Service

可通过 PowerShell 脚本启动：

```text
start_api.ps1
```

后续稳定后可注册：

- Windows Task Scheduler；
- NSSM/Windows Service（如确定运维需要）。

V1 不要求一开始就把 GM GUI/策略完全服务化。

## 37.2 GM Strategy Agent

由国投掘金“交易”模式绑定仿真或实盘账号运行。

策略源代码仍以：

```text
D:\QMT\workspace\broker_node\gm_agent
```

为版本源。

如果掘金要求复制进策略项目目录，通过部署脚本复制，不手工长期维护两份源代码。

## 37.3 GUI 终端依赖

Validation Console 已包含 `DEP-05 Windows终端依赖` 测试。

正式运维规则必须以实际验证结果为准：

- 若关闭掘金终端后 gm.api 失效，则终端在线是生产前置条件；
- Broker Node health 必须反映该依赖；
- 不通过 SSH 远程会话盲目启动 GUI。

---

# 38. 配置示例

```json
{
  "node_id": "guotou-win-01",
  "broker_account_key": "guotou_sim_01",
  "account_mode": "SIM",
  "expected_broker_account_id": "",

  "api": {
    "host": "0.0.0.0",
    "port": 18731,
    "token_env": "BROKER_NODE_API_TOKEN"
  },

  "runtime": {
    "sqlite_path": "D:\\QMT\\workspace\\broker_node\\runtime\\broker_node.sqlite3",
    "log_dir": "D:\\QMT\\logs\\broker_node"
  },

  "sync": {
    "command_poll_interval_ms": 200,
    "unfinished_order_sync_seconds": 5,
    "account_position_sync_seconds": 15,
    "full_reconcile_seconds": 60,
    "agent_offline_seconds": 5
  },

  "market": {
    "enabled": true,
    "default_level": "L1",
    "freshness_ms": 3000
  },

  "safety": {
    "start_paused": true,
    "allow_live_orders": false,
    "max_single_order_notional": null,
    "max_single_order_quantity": null
  }
}
```

注意：

`freshness_ms=3000` 只是示例配置值，不代表已验证的最终业务阈值。AI Coder 应把阈值配置化，并结合真实行情测试结果调整。

---

# 39. 生产验收：必须复用 Validation Console 的测试基线

Broker Node 开发完成后，不应重新发明一套验收清单。

正式验收直接引用已有测试 Case ID。

## 39.1 P0 上线前必须通过

### 环境/连接

```text
ENV-01
ENV-02
ENV-03
CONN-01 ~ CONN-07
```

### 账户

```text
ACC-01 ~ ACC-13
```

至少资金、持仓、可卖数量、当日订单、当日成交必须与国投终端做人工核对。

### 行情

```text
MKT-01
MKT-02
MKT-03
MKT-05
MKT-06
MKT-13
MKT-14
MKT-15
```

如生产 ExecutionPlan 依赖 1min Bar，再要求 `MKT-10`。

### TradePlan / Execution 条件

```text
TP-02
TP-03
TP-04
TP-05
TP-06
TP-07
TP-08
```

### 仿真订单

```text
SIM-01 ~ SIM-10
```

### 订单生命周期

```text
ORD-01 ~ ORD-13
```

部分成交无法稳定复现时可 WARNING，但代码必须支持。

### callback

```text
EVT-01
EVT-02
EVT-04
EVT-05
EVT-06
EVT-07
EVT-08
EVT-09
EVT-10
```

### 恢复

```text
REC-01 ~ REC-10
```

### 安全

```text
SAFE-01
SAFE-06
SAFE-07
SAFE-08
SAFE-09
SAFE-10
SAFE-11
SAFE-12
```

## 39.2 实盘生产启用前

至少先通过：

```text
LIVE-R-01 ~ LIVE-R-06
```

实盘写能力的验证仍然通过 Validation Console 的独立受控页面进行。

完成测试后，生产 Broker Node 的 live gate 才允许打开。

---

# 40. 自动化测试策略

## 40.1 单元测试

必须覆盖：

```text
SecurityIdMapper
Decimal 序列化
时间 normalization
Order status mapping
Fill idempotency
client_order_id idempotency
payload conflict
max_acceptable_price guard
available_quantity guard
market freshness state
UNKNOWN recovery state machine
```

## 40.2 Fixture 来源

fixtures 优先来自 Validation Console 实机保存的 raw payload。

目录例如：

```text
tests/fixtures/gm_orders/accepted.json
tests/fixtures/gm_orders/partial.json
tests/fixtures/gm_orders/cancelled.json
tests/fixtures/gm_orders/rejected.json

tests/fixtures/gm_fills/fill_1.json

tests/fixtures/gm_positions/t1_same_day.json
tests/fixtures/gm_positions/t1_next_day.json
```

不要人工编造“像 gm 的 JSON”来证明 mapper 正确。

## 40.3 集成测试

### SIM 集成测试

使用仿真账户：

```text
提交 LIMIT
→ 查询
→ callback
→ 撤单
→ 成交
→ 持仓变化
→ 资金变化
→ reconcile
```

### Crash test

模拟：

```text
QUEUED 时退出
DISPATCHING 时退出
ACK 后退出
callback 前退出
callback 后主系统未消费退出
```

分别验证恢复行为。

---

# 41. 开发阶段

## Phase 0：吸收验证成果，不写生产交易

AI Coder 首先完成：

```text
1. 找到 B 方案验证项目代码
2. 找到 Validation Console 的实际 raw samples
3. 列出当前 gm.api 版本实际使用的函数
4. 列出所有实际 callback 字段
5. 列出 order raw status 映射
6. 列出 execution report 唯一字段
7. 列出 position 中 quantity / available 字段
8. 列出行情 tick/bid/ask/time 字段
9. 将样本复制为生产 tests fixture
```

输出：

```text
docs/gm_verified_contract.md
```

这是正式编码前置条件。

如果仓库中没有上述验证材料：

> 不允许自行猜测；明确列出缺失材料并以可注入 mapper/stub 保留接口。

## Phase 1：生产只读 Broker Node

实现：

- SQLite；
- API Service；
- Agent heartbeat；
- status；
- account；
- positions；
- orders；
- fills；
- startup reconcile；
- raw + normalized；
- diagnostics。

此阶段：

```text
ORDER_SUBMIT 禁止
ORDER_CANCEL 禁止
```

验收：

- ACC；
- CONN；
- REC 只读部分；
- LIVE-R 可在只读条件下跑。

## Phase 2：行情桥接

实现：

- L1 subscribe；
- quote latest state；
- bid1/ask1；
- market timestamp；
- freshness；
- disconnect/recover；
- market APIs。

验收：

```text
MKT-01/02/03/05/06/13/14/15
TP-03/04/07/08
```

## Phase 3：仿真交易写

实现：

- command queue；
- idempotency；
- LIMIT submit；
- order status callback；
- execution report；
- cancel；
- UNKNOWN；
- reconcile；
- T+1 available position guard。

仅 SIM。

验收：

```text
SIM
ORD
ERR
EVT
REC
T1
SAFE
```

## Phase 4：主交易系统 Gateway

实现：

```text
GMBrokerHttpGateway
BrokerEventConsumer
Market Quote Client
```

接入：

```text
TradePlan
ExecutionPlan
Order
Fill
Position
```

不得重写现有交易域模型。

## Phase 5：端到端仿真

真实流程：

```text
TradePlan
→ 确认
→ ExecutionPlan
→ 行情触发
→ freshness check
→ max_acceptable_price check
→ 本地 Order
→ Broker Node
→ gm.api
→ 仿真柜台
→ callback
→ Fill
→ Position
→ reconcile
```

至少连续运行多个交易日再进入实盘。

## Phase 6：实盘只读

生产 LIVE 节点：

```text
allow_live_orders=false
```

完成：

```text
LIVE-R-01 ~ LIVE-R-06
```

## Phase 7：受控实盘

先用 Validation Console 完成已设计的实盘测试。

生产系统开启：

```text
allow_live_orders=true
BROKER_NODE_ENABLE_LIVE_ORDERS=YES
```

初期仍建议：

- 单标的小额；
- 人工确认 ExecutionPlan；
- 保留人工券商终端兜底；
- 每日收盘强制 reconcile。

---

# 42. AI Coder 的推荐开发顺序

严格按以下顺序：

```text
01. 读取现有交易域代码，不改模型
02. 读取 Validation Console / B 方案验证代码和样本
03. 输出 gm_verified_contract.md
04. 建 broker_node 项目骨架
05. SQLite schema
06. API health/status
07. Agent heartbeat
08. GmAdapter 只读查询
09. Mapper + raw fixtures 单测
10. account/positions/orders/fills API
11. startup reconciliation
12. market subscribe + latest quote
13. market freshness
14. market API
15. commands + idempotency
16. SIM LIMIT submit
17. order callback
18. execution report + Fill 幂等
19. cancel
20. UNKNOWN crash recovery
21. T+1 available quantity guard
22. pause/resume
23. 主系统 GMBrokerHttpGateway
24. BrokerEventConsumer
25. ExecutionPlan 行情触发联调
26. max_acceptable_price defense-in-depth
27. 完整 SIM 回归
28. LIVE 只读
29. Validation Console 实盘验收
30. 生产 live gate
```

不要跳过 02/03 直接凭 SDK 文档开始写 mapper。

---

# 43. AI Coder 禁止事项

正式开发阶段禁止：

```text
× 重新尝试 gmtrade 生产接入
× 引入 xtquant/xttrader
× 重写 TradePlan / ExecutionPlan / Order / Fill / Position
× Broker Node 自己选股
× Broker Node 自己算仓位
× Broker Node 自己生成交易信号
× 本地模拟撮合
× callback 丢失时伪造成交
× UNKNOWN submit 自动重放
× 把 202 Accepted 当券商 ACCEPTED
× 只靠 callback 不做 query/reconcile
× 只靠 query 不接 callback
× 把行情触发价当委托价
× 允许 BUY limit 超过 max_acceptable_price
× STALE 行情触发自动交易
× 用 float 作为最终价格/资金格式
× 把完整 token/账号写日志
× 把交易端口直接暴露公网
× 把 Validation Console 的实盘测试逻辑当生产执行入口
× 把测试用 100 股上限硬编码成生产交易上限
```

---

# 44. Definition of Done

Broker Node V1.1 只有满足下面条件才算开发完成。

## 44.1 工程

```text
[ ] API 与 GM Agent 已分进程
[ ] gm 调用符合验证过的线程模型
[ ] SQLite WAL + FULL
[ ] 所有价格金额 Decimal/string
[ ] 关键凭据不入 Git/日志
```

## 44.2 只读事实

```text
[ ] 资金可查询
[ ] 持仓可查询
[ ] available_quantity 可查询
[ ] 当日订单可查询
[ ] 未完成订单可查询
[ ] 当日成交可查询
[ ] 与终端人工核对通过
```

## 44.3 行情

```text
[ ] L1 最新价
[ ] bid1/ask1
[ ] 行情时间
[ ] freshness
[ ] disconnect/recover
[ ] STALE 不允许行情条件触发
```

## 44.4 订单

```text
[ ] client_order_id 幂等
[ ] LIMIT submit
[ ] cancel
[ ] order callback
[ ] Fill callback
[ ] callback/query 去重
[ ] 部分成交模型正确
[ ] UNKNOWN 不重放
```

## 44.5 安全

```text
[ ] SIM/LIVE 隔离
[ ] 账户 mismatch 锁定
[ ] max_acceptable_price 硬保护
[ ] available position 卖出保护
[ ] disaster quantity/notional guard
[ ] 全局 pause
```

## 44.6 恢复

```text
[ ] Agent 重启恢复
[ ] 掘金断线识别
[ ] 重新连接后 full reconcile
[ ] callback 漏失可通过 query 找回
[ ] 重复 reconcile 幂等
[ ] 外部人工订单可识别
```

## 44.7 端到端

```text
[ ] TradePlan → ExecutionPlan → Order → Broker → Fill → Position
[ ] Trigger 与 Limit 分离
[ ] 行情 stale 时阻断自动触发
[ ] BUY limit 不超过 max_acceptable_price
[ ] 券商 Position 最终覆盖本地推算差异
```

---

# 45. 需要保留的 Validation Console

Broker Node 上线后，Validation Console 不应删除。

它长期用于：

```text
掘金终端升级后回归
SDK升级后回归
Windows重装后验收
券商权限变化诊断
行情权限变化诊断
断线问题复现
新券商接入能力对比
```

生产变更原则：

> 任何 gm SDK、国投掘金终端、Python 运行环境的大版本/关键版本变化，先在 Validation Console 做 SAFE + SIM 回归，再升级生产 Broker Node。

实盘 regression 不自动批量执行。

---

# 46. 当前仍需由实际验证材料决定、不能在本文猜测的内容

本设计已经足够让 AI Coder 开始工程实现，但以下**具体值**必须来自验证工程，而不是本文：

```text
1. gm.api 当前实际账户查询函数名与返回字段
2. position quantity / available / frozen 的真实字段名
3. order_id / cl_ord_id / ex_ord_id 的真实可用性
4. order raw status 枚举及映射
5. execution report 唯一成交编号字段
6. callback 实际参数结构
7. market tick 中 latest / bid / ask / depth / time 字段
8. 行情断线与恢复 callback 的实际行为
9. 关闭国投终端后 Agent/SDK 的实际表现
10. SDK 重连是否自动完成，还是需重新初始化/重启策略
```

AI Coder 在 `gm_verified_contract.md` 中必须逐项写出“验证事实”。

如果某一项 Validation Console 结果是：

```text
NOT_SUPPORTED
```

生产实现也必须按 capability 不支持处理，而不是把它当 bug 补造。

---

# 47. 一句话架构总结

正式系统最终结构是：

```text
主系统负责决策和执行计划
        ↓
Windows Broker Node 负责受控原子执行、实时 L1 桥接和券商事实同步
        ↓
gm.api + MODE_LIVE
        ↓
国投证券柜台
```

并始终坚持：

> **执行逻辑留在主系统，券商事实服从柜台，Broker Node 只做薄执行层；实时回调用来快，主动查询用来补，对账用来兜底，幂等和 UNKNOWN 保护用来防止真实资金事故。**

