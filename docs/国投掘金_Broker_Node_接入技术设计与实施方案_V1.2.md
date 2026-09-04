# 国投证券掘金 Broker Node 接入技术设计与实施方案 V1.2

> 面向 AI Coder 的正式落地设计文档  
> 最后更新：2026-09-02  
> 适用范围：国投证券掘金 3 + `gm.api` + `MODE_LIVE` + Windows 交易节点  
> 本文同时包含修订后的接入测试与验收方案，不再单独维护另一份测试设计文档。

---

# 0. 文档状态、技术结论与 V1.2 变更

## 0.1 已确定的底层接入方案

前期实机验证结论已经明确：

```text
方案 A：gmtrade 独立交易 SDK
结果：当前国投证券掘金环境不可用

方案 B：gm.api + MODE_LIVE
结果：已验证可用
```

因此正式生产接入只实现：

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

生产代码中不得保留 `gmtrade` fallback，不得同时维护两套底层交易驱动。

## 0.2 V1.2 最重要的范围收缩

V1.1 曾把掘金行情能力扩展为较广的 Market Data Bridge。V1.2 明确收缩：

> **掘金不是本项目的研究数据源，也不是行情数据中心。掘金只为交易执行提供实时执行行情和券商账户事实。**

正式数据职责划分如下：

| 数据用途 | 主数据来源 | 是否由 Broker Node 负责 |
|---|---|---|
| 选股 | 现有数据中心 / Tushare | 否 |
| 历史日线、周线、K 线 | 现有数据中心 / Tushare | 否 |
| 财务报表、财务指标 | 现有数据中心 / Tushare | 否 |
| 行业、主题、因子、复盘 | 现有数据中心及其他研究数据源 | 否 |
| 执行中的最新 Tick / 最新价 | 国投掘金 | 是 |
| 执行中的买一、卖一及对应量 | 国投掘金 | 是 |
| 执行行情时间和 freshness | 国投掘金 | 是 |
| 账户资金 | 国投掘金 | 是 |
| 真实持仓、可卖数量 | 国投掘金 | 是 |
| 委托、订单状态 | 国投掘金 | 是 |
| 成交回报 | 国投掘金 | 是 |

因此 V1.2 删除以下生产目标：

```text
× 历史行情下载
× 全市场行情扫描
× 1分钟 / 5分钟 / 15分钟 Bar 数据服务
× 多周期 Bar 数据仓库
× L2 逐笔成交
× L2 逐笔委托
× 委托队列
× 五档盘口作为 P0 依赖
× 财务数据
× 基本面数据
× 选股数据
× 因子计算
× 行业数据
× 用掘金替代 Tushare 的研究数据体系
```

如果未来研究数据源需要调整，应在“数据中心”模块单独设计，不与 Broker Node 绑定。

## 0.3 V1.2 中行情模块的正式名称

V1.1 的：

```text
Market Data Bridge
```

在 V1.2 正式改名为：

```text
Execution Quote Service
执行行情服务
```

这个名字表达了明确边界：

> 它只服务活动中的 ExecutionPlan 和下单前安全检查，不向选股、图表、财务、复盘等模块提供通用行情服务。

## 0.4 测试方案的修订原则

原《国投证券「掘金量化交易系统」接入测试与验收方案 V1.2》中的测试框架继续保留，但测试范围同步收缩。

保留：

```text
环境与连接
账户资金
持仓与可卖数量
执行所需 L1/Tick
最新价、买一、卖一
行情时间与 freshness
仿真下单 / 撤单 / 成交
订单生命周期
callback
T+1
恢复 / 对账
实盘只读
受控实盘写
安全与防重复
```

删除或降为未来范围：

```text
五档盘口专项验收
多周期 Bar
L2
历史行情
大规模行情连续性研究
Linux 直接连接国投实盘
GM 官方远程 endpoint 探索
gmtrade 验证
条件单 / 算法单 / 网格 / TWAP / VWAP 能力普查
与研究、财务、选股有关的数据能力测试
```

---

# 1. 系统目标

现有交易系统业务链保持不变：

```text
研究 / 自选股
      ↓
TradePlan 交易计划
      ↓ 用户确认
ExecutionPlan 执行计划
      ↓
ExecutionEngine
      ↓ 行情条件满足 + 下单前风控
Order 本地订单
      ↓ BrokerGateway
Windows Broker Node
      ↓
gm.api + MODE_LIVE
      ↓
国投掘金 / 券商柜台
      ↓
Order 回报 / Fill 成交 / Position 账户事实
```

Broker Node 的目标是：

> **提供一个稳定、受控、幂等、可恢复、可审计的国投券商执行边界。**

Broker Node 不再开发一套交易系统，也不负责研究数据。

它只回答两类问题：

### A. “现在能不能安全把这条原子交易命令送给券商？”

包括：

- 账户是否正确；
- 通道是否在线；
- 节点是否暂停；
- 是否发生 UNKNOWN / 对账异常；
- 请求是否重复；
- 卖出数量是否超过当前可卖；
- 买入限价是否突破主系统给出的最高可接受价；
- 若命令依赖实时触发，执行行情是否新鲜。

### B. “券商现在真实发生了什么？”

包括：

- 资金；
- 持仓；
- 可卖数量；
- 委托；
- 订单状态；
- 成交；
- 通道状态；
- 当前执行标的的最新行情。

---

# 2. 强制业务边界

## 2.1 现有交易域模型不得重写

必须保留主系统已有：

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

| 事实 | 归属 |
|---|---|
| 为什么买 / 卖 | TradePlan |
| 风险预算 | TradePlan / RiskProfile |
| 建议数量和确认数量 | TradePlan |
| 什么时候进入执行 | ExecutionPlan |
| 价格触发 / 区间触发 | ExecutionEngine |
| 本地订单意图 | 主系统 Order |
| 柜台委托 | 国投掘金 / 券商 |
| 真实成交 | 国投掘金 / 券商 |
| 账户真实持仓 | 国投掘金 / 券商 |
| Windows 执行日志 | Broker Node journal |

## 2.2 Broker Node 不产生交易决策

Broker Node 禁止自己：

```text
× 选股
× 判断股票值不值得买
× 计算仓位
× 计算风险预算
× 生成止损 / 止盈策略
× 自动加仓 / 减仓
× 根据历史 K 线生成信号
× 根据财务数据生成信号
× 自行追价
```

## 2.3 Broker Node 不伪造券商事实

无论发生：

- gm API 超时；
- callback 丢失；
- Agent 崩溃；
- 掘金断线；
- Windows 重启；
- 主系统断开；

都不得基于本地行情或订单意图生成假 Fill。

只有：

```text
真实 execution report
或
主动查询得到的真实成交
```

才能形成 Fill。

## 2.4 研究数据与执行行情彻底分离

主系统中的：

```text
K 线展示
历史走势
财务信息
行业信息
选股数据
复盘数据
```

不得调用 Broker Node 获取。

Broker Node 也不得依赖 Tushare。

两边只通过：

```text
TradePlan / ExecutionPlan / Order
```

发生业务关联。

---

# 3. 总体生产架构

## 3.1 拓扑

```text
┌─────────────────────────────────────────────────────────────┐
│                        主交易系统                           │
│                                                             │
│ Research/Data Center                                        │
│  └─ Tushare / 现有研究数据                                  │
│                                                             │
│ TradePlan                                                   │
│ ExecutionPlan                                               │
│ ExecutionEngine                                             │
│ PreTradeRiskCheck                                           │
│ Order / Fill / Position                                     │
│ BrokerEventConsumer                                         │
│ GMBrokerHttpGateway                                         │
└───────────────────────────┬─────────────────────────────────┘
                            │ 私网 HTTP/JSON
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Windows Broker Node                      │
│                                                             │
│ ┌────────────────────────┐                                  │
│ │ Broker API Service     │                                  │
│ │ HTTP / Auth / DTO      │                                  │
│ └───────────┬────────────┘                                  │
│             │                                               │
│ ┌───────────▼─────────────────────────────────────────────┐  │
│ │ Durable Journal DB                                    │  │
│ │ SQLite WAL + FULL                                     │  │
│ │ commands / events / snapshots / order_links           │  │
│ └───────────┬────────────────────────────────────────────┘  │
│             │                                               │
│ ┌───────────▼─────────────────────────────────────────────┐  │
│ │ GM Strategy Agent                                     │  │
│ │                                                       │  │
│ │ GmCallExecutor                                        │  │
│ │ Account / Position / Order / Fill Synchronizer        │  │
│ │ Execution Quote Service                               │  │
│ │ Callback Handlers                                     │  │
│ │ Reconciler                                            │  │
│ └───────────┬─────────────────────────────────────────────┘  │
│             │                                               │
│ ┌───────────▼─────────────────────────────────────────────┐  │
│ │ Ephemeral Quote Cache                                 │  │
│ │ 最新执行行情；可丢失；可重新订阅重建                    │  │
│ └─────────────────────────────────────────────────────────┘  │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
                   gm.api + MODE_LIVE
                            │
                            ▼
                    国投证券掘金 3
                            │
                   仿真账户 / 实盘账户
```

## 3.2 为什么仍然采用两个进程

正式节点采用：

```text
Broker API Service
 
GM Strategy Agent
```

而不是在 FastAPI 请求线程中直接调用 `gm.api`。

原因：

1. 掘金策略运行生命周期和 HTTP Server 生命周期不同；
2. gm 的线程 / event-loop 使用必须沿用已验证成功的 B 方案；
3. HTTP 并发不能直接变成 gm 交易 API 并发；
4. API Service 可独立提供健康状态和历史事件；
5. API 依赖升级不会污染已验证的 gm Python 环境；
6. durable command journal 可以处理 HTTP 重试和进程崩溃窗口；
7. Agent 即使暂时与主系统断开，也必须继续接收券商成交回报。

---

# 4. Windows 节点定位与环境

Windows 笔记本正式定位：

```text
Broker Execution Node
券商执行节点
```

不是：

```text
研究服务器
行情历史数据库
财务数据服务器
选股服务器
```

当前已验证运行基础：

```text
Windows 11
Python 3.9.13
C:\Program Files\Python39\python.exe
gm 3.0.186
国投证券掘金 3
SSH 可运维
```

正式项目目录：

```text
D:\QMT\workspace\broker_node\
```

日志：

```text
D:\QMT\logs\broker_node\
```

当前 Windows IP 为 DHCP 动态地址。正式联调前建议在路由器侧设置 DHCP Reservation，或使用稳定主机名，**不要把当前 IP 硬编码进源代码**。

---

# 5. 项目目录设计

```text
broker_node\
├── README.md
├── CHANGELOG.md
├── requirements-api.txt
│
├── docs\
│   ├── gm_verified_contract.md
│   ├── api_contract.md
│   └── operations.md
│
├── config\
│   ├── config.example.json
│   └── config.local.json              # gitignored
│
├── shared\
│   ├── enums.py
│   ├── dto.py
│   ├── config.py
│   ├── db.py
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
│       ├── execution_quotes.py
│       ├── events.py
│       ├── sync.py
│       ├── control.py
│       └── diagnostics.py
│
├── gm_agent\
│   ├── main.py                        # 掘金策略入口
│   ├── lifecycle.py
│   ├── gm_adapter.py
│   ├── gm_mapper.py
│   ├── gm_executor.py
│   ├── command_consumer.py
│   ├── callbacks.py
│   ├── account_sync.py
│   ├── position_sync.py
│   ├── order_sync.py
│   ├── fill_sync.py
│   ├── execution_quote_service.py
│   ├── quote_freshness.py
│   └── reconciler.py
│
├── runtime\
│   ├── broker_node.sqlite3            # durable
│   └── quote_cache.sqlite3            # ephemeral
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
        ├── gm_account\
        ├── gm_positions\
        ├── gm_orders\
        ├── gm_fills\
        └── gm_quotes\
```

如果之前已经开发 `Broker Validation Console`，继续保持独立工程，不将测试 UI 嵌入生产 Broker Node。

---

# 6. Python 环境与依赖隔离

## 6.1 GM Strategy Agent

必须使用已经验证成功的 Python：

```text
C:\Program Files\Python39\python.exe
Python 3.9.13
gm 3.0.186
```

禁止因 Broker Node 开发而：

```text
× 升级 gm
× 降级 gm
× 安装 gmtrade 作为 fallback
× 引入 xtquant / xttrader
× 替换掘金内置运行组件
```

## 6.2 Broker API Service

API Service 建独立虚拟环境：

```text
D:\QMT\workspace\broker_node\.venv-api
```

API 进程不依赖 `gm.api`。

建议：

```text
FastAPI
Uvicorn
与 Python 3.9 兼容的 Pydantic
标准库 sqlite3
```

依赖越少越好。

---

# 7. Phase 0：把“B 方案实机验证”固化为代码契约

在正式写 Adapter 前，AI Coder 必须先整理已经验证成功的 B 方案。

输出：

```text
docs/gm_verified_contract.md
```

至少逐项记录：

```text
1. gm.api 当前实际 import 方式
2. 实盘 / 仿真运行所需 strategy_id、token、账户绑定方式
3. 账户查询实际函数和返回字段
4. Position 中总持仓、可卖、冻结、成本等真实字段名
5. 当日订单查询函数和真实字段
6. 未完成订单查询函数和真实字段
7. 成交查询函数和真实字段
8. order_id / cl_ord_id / ex_ord_id 实际可用情况
9. order raw status 的实际枚举样本
10. execution report 的唯一成交字段
11. on_order_status 实际参数结构
12. on_execution_report 实际参数结构
13. 交易连接断开 / 恢复 callback 的实际行为
14. Tick / quote 中 last、bid1、ask1、time 的真实字段
15. subscribe / unsubscribe 的实际调用方式
16. 关闭国投终端后的实际行为
17. 重启 / 重连后是否自动恢复，还是必须重新初始化
18. 下单和撤单函数的真实参数要求
```

同时将实机原始返回保存为 `tests/fixtures`。

原则：

> **生产 mapper 只根据已验证样本开发，不根据其他 gm 版本、其他券商或网上示例猜字段。**

如果某个字段尚未验证，文档标 `UNVERIFIED`，代码保留显式 capability / adapter 分支，不静默猜测。

---

# 8. GM Strategy Agent 运行模型

## 8.1 Agent 本质

它虽然以“掘金策略”形式运行，但不是业务交易策略。

它只包含：

```text
命令消费者
券商查询器
执行行情订阅器
callback 接收器
对账器
```

## 8.2 启动流程

```text
1. 加载 config
2. 打开 durable SQLite
3. 打开 quote cache
4. 写 Agent heartbeat
5. 初始化 gm runtime
6. 等待行情 / 交易通道状态
7. 获取实际账户
8. 校验实际账户 == expected account
9. startup reconciliation
10. 刷新资金、持仓、当日订单、未完成订单、当日成交
11. 恢复仍有效的 Execution Quote 订阅
12. 检查遗留 DISPATCHING / UNKNOWN 命令
13. 计算 Node Readiness
14. 开始消费新命令
```

## 8.3 所有 gm 调用串行化

全部 gm 调用统一经过：

```text
GmCallExecutor
```

其具体线程 / callback / event-loop 模型必须沿用 B 方案验证成功的方式。

禁止：

```text
× HTTP worker 直接调用 gm
× 多 worker 并发调用 order API
× callback 内做长耗时交易逻辑
× 未经验证自行改 gm 线程模型
```

## 8.4 Callback 原则

以实机存在的 callback 为准，例如：

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
→ normalize
→ 幂等写 event / snapshot
→ 必要时更新 order link
→ 返回
```

callback 不做：

```text
TradePlan 判断
ExecutionPlan 价格触发
仓位计算
追价
自动补单
```

---

# 9. 本地持久化设计

## 9.1 两类本地存储

### Durable Journal

```text
runtime\broker_node.sqlite3
```

保存：

```text
commands
order_links
broker_events
snapshots
node_state
quote_subscriptions
```

配置：

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;
```

### Ephemeral Quote Cache

```text
runtime\quote_cache.sqlite3
```

只保存活动执行标的最新 quote。

配置可使用：

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=1000;
```

它不是交易事实账本，允许在重启时重建。

## 9.2 为什么行情不和交易命令使用同一 FULL DB 高频写

Tick 可能频繁到达。

如果每个 Tick 都：

```text
SQLite FULL fsync
```

会没有必要地增加磁盘写和锁竞争。

因此 Agent：

```text
每个 Tick → 先更新进程内 latest quote
每隔 quote_flush_interval_ms → 把最新状态 flush 到 quote_cache
```

V1 默认可先：

```text
quote_flush_interval_ms = 100 ~ 250
```

最终值以 Windows 实测为准。

主系统不需要拿到每一个原始 Tick；它只需要足够新鲜的“最新可执行行情状态”。

---

# 10. Durable SQLite Schema

## 10.1 `node_state`

```text
node_id
broker_account_key
account_mode                     SIM / LIVE
api_process_status
agent_process_status
market_connection_status
trade_connection_status
broker_account_status
execution_enabled
paused
pause_reason
reconciliation_required
last_agent_heartbeat_at
last_broker_event_at
last_account_sync_at
last_position_sync_at
last_order_sync_at
last_fill_sync_at
updated_at
```

## 10.2 `commands`

```text
command_id                       UUID PK
request_id                       UUID UNIQUE
command_type                     ORDER_SUBMIT / ORDER_CANCEL / SYNC_ALL / ...
client_order_id                  nullable
payload_hash
payload_json
status
broker_order_id                  nullable
error_code                       nullable
error_message                    nullable
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

`UNKNOWN`：

> 不能确定该券商写命令是否已经到达柜台，因此禁止自动重发。

## 10.3 `order_links`

```text
client_order_id                  UNIQUE
submit_command_id
broker_order_id                  nullable
exchange_order_id                nullable
last_broker_status
last_raw_status
origin                            SYSTEM / EXTERNAL
created_at
updated_at
```

## 10.4 `broker_events`

```text
seq                               INTEGER AUTOINCREMENT PK
event_id                          UUID UNIQUE
event_type
client_order_id                   nullable
broker_order_id                   nullable
broker_execution_id               nullable
source                             CALLBACK / QUERY / RECONCILE / NODE
raw_fingerprint                   nullable
payload_json
occurred_at                       nullable
received_at
```

## 10.5 `snapshots`

```text
snapshot_type                     ACCOUNT / POSITIONS / ORDERS / FILLS
snapshot_version
as_of
source                             QUERY / RECONCILE
payload_json
updated_at
```

## 10.6 `quote_subscriptions`

用于记录“哪些 ExecutionPlan 当前需要哪个证券的实时执行行情”。

```text
owner_type                         EXECUTION_PLAN
owner_id                           ExecutionPlan ID
symbol_key
broker_symbol
lease_expires_at                  nullable
created_at
updated_at
PRIMARY KEY(owner_type, owner_id, symbol_key)
```

可使用 lease 防止主系统异常退出后留下永久订阅。

---

# 11. Quote Cache Schema

`quote_state`：每个证券一行。

```text
symbol_key                        PK
broker_symbol
last_price
bid1
bid1_volume
ask1
ask1_volume
market_time_raw
market_time_normalized
received_at
quote_revision
freshness_status
raw_json                          可配置关闭
updated_at
```

V1 不保存历史 Tick。

---

# 12. Broker API 基本约定

```text
Base URL: /api/v1
HTTP/1.1
JSON UTF-8
```

## 12.1 Decimal

价格、资金、金额：

- Python 内部使用 `Decimal`；
- JSON 传字符串。

```json
{
  "price": "10.23",
  "available_cash": "152330.18"
}
```

禁止把最终资金、价格接口定义成 float。

## 12.2 时间

统一：

```text
ISO 8601 +08:00
```

同时保留：

```text
broker_time_raw
received_at
```

## 12.3 Broker Account Key

主系统只识别逻辑账户：

```text
guotou_sim_01
guotou_live_01
```

真实券商 account id 仅存在 Windows 私有配置中，普通日志和 API 默认脱敏。

## 12.4 所有写接口必须有 Request ID

写请求至少包含：

```text
request_id
```

下单还必须包含：

```text
client_order_id
```

撤单必须包含：

```text
cancel_request_id
```

---

# 13. 健康、连接与 Readiness

## 13.1 `GET /api/v1/health`

只证明 API Service 活着，不触发 gm 查询。

```json
{
  "ok": true,
  "node_id": "guotou-win-01",
  "server_time": "2026-09-02T20:00:00+08:00"
}
```

## 13.2 `GET /api/v1/status`

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
  "unresolved_unknown_commands": 0,
  "last_agent_heartbeat_at": "...",
  "last_account_sync_at": "..."
}
```

## 13.3 `TRADING_READY`

允许新的券商写命令必须同时满足：

```text
Agent 心跳新鲜
AND
交易通道已连接
AND
账户连接正常
AND
实际账户 = expected account
AND
execution_enabled = true
AND
paused = false
AND
reconciliation_required = false
AND
无 unresolved UNKNOWN submit
AND
若 LIVE：生产实盘双重 gate 已开启
```

对于依赖实时触发的订单，还需要：

```text
对应 Execution Quote = FRESH
```

---

# 14. 账户、持仓、订单、成交 API

## 14.1 账户

```text
GET /api/v1/account
```

返回标准字段至少：

```text
total_asset
available_cash
frozen_cash                      若 gm 实际可用
market_value                     若 gm 实际可用
as_of
stale
raw                              可配置是否返回
```

## 14.2 持仓

```text
GET /api/v1/positions
```

至少：

```text
instrument
quantity
available_quantity
frozen_quantity                  若实际存在
cost_price
market_value                     若实际存在
as_of
raw
```

其中 `available_quantity` 是生产核心字段。

## 14.3 订单

```text
GET /api/v1/orders?scope=today
GET /api/v1/orders?scope=unfinished
```

## 14.4 成交

```text
GET /api/v1/fills?scope=today
```

## 14.5 主动刷新

HTTP GET 不直接同步阻塞调用 gm。

如主系统需要主动刷新：

```text
POST /api/v1/sync
```

请求：

```json
{
  "request_id": "...",
  "scope": "ALL"
}
```

返回 command id，Agent 异步执行。

---

# 15. Execution Quote Service：执行行情服务

## 15.1 唯一职责

只服务：

```text
活动中的 ExecutionPlan
+
下单前最后安全检查
```

只承诺：

```text
最新 Tick / last
bid1 / bid1_volume
ask1 / ask1_volume
market timestamp
received timestamp
freshness
行情连接状态
```

明确不承诺：

```text
历史行情
Bar
L2
全市场行情
研究行情数据库
```

## 15.2 订阅生命周期必须与 ExecutionPlan 绑定

当 ExecutionPlan 进入需要实时价格观察的活动状态：

```text
ExecutionPlan ACTIVE
        ↓
主系统注册 execution quote subscription
        ↓
Broker Node subscribe(symbol)
```

当：

```text
COMPLETED
CANCELLED
EXPIRED
或不再需要行情
```

则：

```text
移除 owner subscription
→ 该 symbol 已无任何 owner
→ gm unsubscribe(symbol)
```

Windows 节点启动后**禁止自动订阅整个 A 股市场**。

## 15.3 Subscription API

### 设置一个 ExecutionPlan 的目标订阅

```text
PUT /api/v1/execution-quotes/subscriptions/{execution_plan_id}
```

```json
{
  "symbols": [
    {"code": "600000", "exchange": "SH"}
  ],
  "lease_seconds": 120
}
```

此接口是 desired-state/idempotent 语义。

主系统可每 30~60 秒续租。

### 删除订阅

```text
DELETE /api/v1/execution-quotes/subscriptions/{execution_plan_id}
```

### 查询当前订阅

```text
GET /api/v1/execution-quotes/subscriptions
```

## 15.4 最新执行行情 API

```text
GET /api/v1/execution-quotes?symbols=SH:600000,SZ:000001
```

示例：

```json
{
  "quotes": [
    {
      "instrument": {"code": "600000", "exchange": "SH"},
      "last": "10.21",
      "bid1": "10.20",
      "bid1_volume": 3200,
      "ask1": "10.21",
      "ask1_volume": 2500,
      "market_time": "2026-09-02T10:21:31.210+08:00",
      "received_at": "2026-09-02T10:21:31.238+08:00",
      "age_ms": 82,
      "quote_revision": 182341,
      "freshness": "FRESH"
    }
  ]
}
```

## 15.5 主系统消费方式

V1 不要求 WebSocket。

主系统的 ExecutionEngine 可按活动标的批量轮询：

```text
execution_quote_poll_ms = 250 ~ 500
```

只轮询活动 ExecutionPlan 的证券。

因为本项目是 A 股中低频执行系统，不是 HFT，不要求传输每个原始 Tick。

如未来实测证明 250~500ms 不满足需求，再升级 SSE/WebSocket，不改变 BrokerGateway 业务模型。

## 15.6 Freshness 状态

统一：

```text
FRESH
STALE
DISCONNECTED
UNKNOWN
```

同时可返回：

```text
market_phase
```

避免午休、闭市时仅凭“几秒没 Tick”误判。

freshness 判定不得只有：

```text
now - last_tick > 3s
```

需要综合：

```text
行情通道状态
当前交易阶段
last market timestamp
received_at
配置阈值
```

阈值必须配置化，并以实盘/仿真测试结果调整。

---

# 16. TradePlan / ExecutionPlan 与实时行情的边界

## 16.1 价格条件判断仍在主系统

例如：

```text
价格进入 10.20 ~ 10.50
```

判断发生在：

```text
ExecutionEngine
```

Broker Node 不自己观察区间然后产生交易命令。

## 16.2 Trigger Price 与 Order Limit Price 必须分离

```text
Trigger condition
!=
Order Limit Price
```

触发只回答：

```text
“现在是否可以进入一次执行动作？”
```

委托价由 ExecutionPlan 的执行规则单独产生。

禁止：

```text
到价了
→ 直接用当前价无保护下单
```

## 16.3 `max_acceptable_price` 双层保护

主系统首先检查：

```text
BUY limit price <= TradePlan.max_acceptable_price
```

Broker Node 再做 defense-in-depth：

订单请求携带：

```json
{
  "safety_constraints": {
    "max_acceptable_price": "10.50",
    "require_fresh_quote": true
  }
}
```

Broker Node 再检查：

```text
BUY LIMIT price <= max_acceptable_price
```

不满足：

```text
FAILED_SAFE
PRICE_GUARD_VIOLATION
```

Broker Node 不知道为什么上限是 10.50，也不重新计算这个值。

## 16.4 由行情触发的订单必须记录触发快照

主系统 Order / Execution log 至少保留：

```text
trigger_quote_revision
trigger_quote_time
trigger_last
trigger_bid1
trigger_ask1
trigger_freshness
```

这样以后复盘可以回答：

> “这张订单为什么在这个时刻被生成？”

而不是需要永久保存所有 Tick。

## 16.5 Quote 失效时的规则

当 ExecutionPlan 依赖实时价格条件：

```text
freshness != FRESH
```

则禁止产生新的行情触发订单。

如果主系统已经创建订单，但 Broker Node 收到时请求要求：

```text
require_fresh_quote=true
```

Node 在实际发 gm 前再次检查。

失败：

```text
MARKET_STALE
或
MARKET_CONNECTION_DOWN
```

---

# 17. 四类 ExecutionPlan 如何落到 Broker Node

现有执行方式包括：

```text
限价委托
持续限价
价格触发
价格区间触发
```

Broker Node 始终只接受“原子券商命令”。

## 17.1 限价委托

```text
ExecutionPlan
→ 主系统创建一次 LIMIT Order
→ Broker Node Submit
```

## 17.2 持续限价

持续逻辑留在主系统：

```text
主系统判断旧单是否需要撤
→ Cancel
→ 等待旧单终态 / 确认剩余数量
→ 新 client_order_id
→ 新 LIMIT Order
```

Broker Node 不内部维护“持续追价策略”。

## 17.3 价格触发

```text
主系统订阅 Execution Quote
→ ExecutionEngine 判断条件
→ FRESH
→ 触发
→ 生成 LIMIT Order
→ Broker Node
```

## 17.4 价格区间触发

同样：

```text
Execution Quote
→ 主系统判断是否进入区间
→ 生成 LIMIT Order
```

Broker Node 只做 freshness 和 hard guard。

---

# 18. 下单 API

## 18.1 正确顺序

```text
ExecutionPlan 条件满足
→ PreTradeRiskCheck
→ 主系统创建 Order(PENDING_SEND)
→ BrokerGateway.place_order()
→ Broker Node
```

`client_order_id` 是跨系统幂等键。

## 18.2 `POST /api/v1/orders`

V1 只实现普通原子 LIMIT 单。

```json
{
  "request_id": "f82c...",
  "client_order_id": "ord_...",
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
    "require_fresh_quote": true
  },
  "trigger_snapshot": {
    "quote_revision": 182341,
    "quote_time": "...",
    "last": "10.22",
    "bid1": "10.21",
    "ask1": "10.22"
  }
}
```

## 18.3 Broker Node 执行前检查

只做执行层安全检查：

```text
请求结构合法
账户匹配
SIM / LIVE 模式匹配
TRADING_READY
client_order_id 幂等
quantity > 0
证券代码可映射
订单类型受支持
灾难性数量 / 金额硬上限
SELL quantity <= 最新已知 available_quantity
BUY limit <= max_acceptable_price（若传入）
require_fresh_quote 时 quote == FRESH
```

Broker Node 不重新计算：

```text
风险预算
总仓位
单股仓位
TradePlan 风险参考价
收益风险比
是否值得买
```

## 18.4 返回

命令 durable persist 后：

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
Broker Node 安全接收了命令
```

绝不表示：

```text
券商已经 ACCEPTED
```

---

# 19. 下单幂等

## 19.1 `client_order_id`

全局唯一。

同 ID + 相同 payload：

```text
返回原 command
不重复下单
```

同 ID + 不同 payload：

```text
409 IDEMPOTENCY_CONFLICT
```

## 19.2 必须覆盖的重复来源

```text
UI 双击
主系统 HTTP 重试
请求超时后自动 retry
反向代理重试
人工误点两次
Broker Node ACK 丢失
```

前端按钮 disable 不是幂等机制。

---

# 20. `DISPATCHING` 崩溃窗口

最危险场景：

```text
command = DISPATCHING
→ gm order API 已调用
→ 券商可能收到
→ Agent 崩溃
→ 本地还没保存 broker_order_id
```

重启后：

```text
DISPATCHING 且无可靠 ACK
→ UNKNOWN
→ reconciliation_required = true
→ execution_enabled = false
```

禁止自动重放。

Agent 查询：

```text
当日订单
未完成订单
当日成交
```

只有能够唯一匹配时才恢复链接。

不能唯一匹配：

> 人工处理，绝不为了“恢复”重新发一次。

---

# 21. 订单状态映射

主系统标准状态：

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

gm raw status → standard status 的 mapping 必须来自 `gm_verified_contract.md` 和实机 fixture。

未知 raw status：

```text
standard = UNKNOWN
保留 raw
记录 warning
```

禁止未知状态默认映射成 ACCEPTED。

---

# 22. Fill 与成交幂等

## 22.1 Order / Fill 分离

```text
1 Order → 0 / 1 / N Fill
```

部分成交必须正确累计：

```text
filled_quantity
remaining_quantity
filled_vwap
```

## 22.2 成交唯一键

优先：

```text
(broker_account_key, broker_execution_id)
```

如果实机证明没有稳定 execution id，则根据真实字段定义 deterministic surrogate key。

禁止随机 UUID 用于判断“是否同一成交”。

## 22.3 callback + query 去重

同一 Fill 可能：

```text
callback 先到
query 后查到
reconcile 再扫到
```

最终只能形成一条本地 Fill 事实。

---

# 23. 撤单

## 23.1 API

```text
POST /api/v1/orders/{client_order_id}/cancel
```

```json
{
  "cancel_request_id": "...",
  "reason": "USER_CANCEL"
}
```

## 23.2 撤单不是立即终态

调用 gm cancel 成功只代表：

```text
撤单请求已发出
```

最终：

```text
CANCELLED
或
FILLED
或其他终态
```

必须来自 callback 或主动查询。

## 23.3 已终态订单

```text
FILLED / CANCELLED / REJECTED / EXPIRED
```

再次撤单：

```text
ALREADY_TERMINAL
```

不作为系统故障。

## 23.4 V1 不做柜台改单

需要改价：

```text
撤旧单
→ 确认旧单终态及剩余量
→ 新 client_order_id
→ 新 LIMIT
```

流程由主系统 ExecutionEngine 负责。

---

# 24. T+1 与可卖数量

## 24.1 Position 核心事实

必须保留：

```text
quantity
available_quantity
frozen_quantity（若 gm 实际存在）
```

## 24.2 SELL 最小防错

Broker Node 发单前：

```text
requested_sell_quantity <= latest_known_available_quantity
```

不满足：

```text
FAILED_SAFE
INSUFFICIENT_AVAILABLE_POSITION
```

券商柜台仍然是最终裁决者。

## 24.3 新交易日

禁止仅根据本地昨日 Fill 推算可卖。

新交易日：

```text
startup reconcile
→ 重新查询 broker position
→ 更新 available_quantity
```

---

# 25. Callback + Query + Reconcile 三层同步

生产必须同时使用：

```text
实时 callback
+
周期 query
+
完整 reconciliation
```

## 25.1 callback

解决快速变化：

```text
券商接受
部分成交
全部成交
撤单
拒单
连接变化
```

## 25.2 周期 query

解决：

```text
callback 漏失
进程短暂离线
外部人工委托
状态校验
```

## 25.3 full reconcile

至少读取：

```text
资金
持仓
当日订单
未完成订单
当日成交
```

## 25.4 初始工程默认值

```text
command_poll_interval_ms          200
unfinished_order_sync_seconds       5
account_position_sync_seconds      15
full_reconcile_seconds             60
```

这些只是工程默认值，必须可配置。

---

# 26. Reconciliation 规则

## 26.1 强制 full reconcile 的时机

```text
Agent 启动
交易通道重新连接
账户重新登录
检测到 UNKNOWN
关键查询出现不一致
```

完成前不进入 `TRADING_READY`。

## 26.2 外部订单

券商存在、本地无 client_order_id：

```text
origin = EXTERNAL
```

产生：

```text
EXTERNAL_ORDER_FOUND
```

不得自动绑定 TradePlan / ExecutionPlan。

## 26.3 漏成交补齐

query / reconcile 找到、本地没有的成交：

```text
补写 FILL event
source = RECONCILE
```

## 26.4 持仓差异

主系统根据 Fill 推算和券商 Position 不一致：

```text
券商 Position = 最终账户事实
+
RECONCILIATION_ALERT
```

## 26.5 保护锁定

至少以下情况进入：

```text
reconciliation_required = true
execution_enabled = false
```

场景：

```text
UNKNOWN submit 无法唯一确认
实际账户变化
成交无法唯一识别
订单数量 / 状态严重不一致
关键对账接口失败
```

---

# 27. Crash / Disconnect Recovery

## 27.1 API Service 重启

不影响 GM Agent。

API 从 durable DB 恢复：

```text
commands
events
snapshots
heartbeat
```

## 27.2 GM Agent 重启

```text
QUEUED 且从未 DISPATCHING
→ 可以继续执行
```

```text
DISPATCHING 且无确定 ACK
→ UNKNOWN
→ 不重放
```

然后 full reconcile。

## 27.3 掘金 / 交易通道断开

立即：

```text
execution_enabled = false
TRADE_CONNECTION_CHANGED
```

不假设已有挂单被撤。

恢复：

```text
重查账户事实
→ reconcile
→ 无异常
→ 才允许 resume
```

## 27.4 行情通道断开

Execution Quote：

```text
DISCONNECTED
```

任何依赖实时行情条件的新订单阻断。

已有柜台挂单不自动撤。

## 27.5 主系统断开

Broker Node：

```text
不产生新订单
继续接 callback
继续写 Fill / Order 事件
继续 reconcile
```

主系统恢复后从 event seq 补齐。

---

# 28. Durable Event Stream

## 28.1 事件类型

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
QUOTE_CONNECTION_CHANGED
QUOTE_STALE
QUOTE_RECOVERED
```

## 28.2 API

```text
GET /api/v1/events?after_seq=12345&limit=500
```

语义：

```text
at-least-once
```

主系统必须幂等消费。

## 28.3 不把每个 Tick 写 durable event

Tick 只进入：

```text
Agent in-memory latest quote
→ quote cache
```

durable 只记录：

```text
连接变化
freshness 变化
与订单触发有关的 trigger snapshot（在主系统 Order 中）
```

---

# 29. 主系统 `GMBrokerHttpGateway`

新增实现：

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
    def set_execution_quote_subscription(self, execution_plan_id, instruments): ...
    def remove_execution_quote_subscription(self, execution_plan_id): ...
    def get_execution_quotes(self, instruments): ...
    def place_order(self, order): ...
    def cancel_order(self, order): ...
```

TradePlan / ExecutionPlan 不直接拼 HTTP。

## 29.1 `BrokerEventConsumer`

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

只有事务提交后才能推进 seq。

## 29.2 Execution Quote Poller

主系统增加一个轻量：

```text
ExecutionQuotePoller
```

职责：

```text
读取当前 ACTIVE ExecutionPlan 所需 symbols
→ 注册 / 续租订阅
→ 批量读取最新 quote
→ 更新 ExecutionEngine 的临时 quote state
```

它不是数据中心，不保存历史行情。

---

# 30. 主系统 Order / Fill / Position 更新

## 30.1 Order

```text
创建 Order
→ PENDING_SEND
```

Broker Node 202：

```text
QUEUED / SENT 语义
```

真实柜台回报后才：

```text
ACCEPTED
PARTIALLY_FILLED
FILLED
...
```

## 30.2 Fill

只来自 Broker Event / Reconcile 的真实成交事实。

## 30.3 Position

主系统可以根据 Fill 快速增量更新，但必须定期以券商 Position 校正。

尤其：

```text
available_quantity
```

不得仅靠本地推算。

---

# 31. 全局暂停

## 31.1 Pause

```text
POST /api/v1/control/pause
```

效果：

```text
execution_enabled = false
```

不自动撤已有订单。

## 31.2 Resume

只有：

```text
Agent online
trade connected
account matched
reconciliation_required=false
无 UNKNOWN
LIVE gate 满足
```

才能恢复。

## 31.3 Pause + Cancel Open Orders

如主系统需要：

```text
POST /api/v1/control/pause-and-cancel-open-orders
```

也必须：

```text
逐笔撤
逐笔确认
逐笔记录
```

V1 不使用危险的“批量全部撤单”接口作为默认实现。

---

# 32. SIM / LIVE 强隔离

## 32.1 一个 Broker Node 实例只绑定一个账户

```json
{
  "broker_account_key": "guotou_sim_01",
  "account_mode": "SIM",
  "expected_broker_account_id": "..."
}
```

不允许 HTTP 请求动态指定任意券商账户然后切换。

## 32.2 推荐仿真和实盘使用不同掘金策略实例

建议：

```text
BrokerNode-SIM
BrokerNode-LIVE
```

使用不同：

```text
strategy_id
绑定账户
config
runtime DB
API port（如同时运行）
```

降低账户误绑风险。

## 32.3 实盘双重 Gate

生产实盘：

```text
config: allow_live_orders=true
+
env: BROKER_NODE_ENABLE_LIVE_ORDERS=YES
```

任何一个未开启：

```text
LIVE_TRADING_DISABLED
```

## 32.4 账户 mismatch

实际账户 != expected：

```text
ACCOUNT_MISMATCH
READ_ONLY_LOCKED
```

查询可以继续，下单 / 撤单禁止。

---

# 33. Broker Node 灾难性硬保护

Broker Node 不复制 RiskProfile，但允许少量运维安全上限：

```text
max_single_order_quantity
max_single_order_notional
allowed_exchanges
allowed_security_types
```

目的：

> 防止程序数量级 bug，而不是替代交易策略风控。

不能把测试控制台的“100 股”硬编码成正式生产上限。

---

# 34. 证券标识映射

实现：

```text
SecurityIdMapper
```

职责：

```text
主系统 code + exchange
↔
GM broker symbol
```

V1 至少覆盖当前交易范围：

```text
A 股主板
创业板
股票 ETF
科创板相关 ETF
```

所有映射必须有单元测试。

---

# 35. 标准错误码

至少：

```text
AUTH_FAILED
INVALID_REQUEST
ACCOUNT_MISMATCH
BROKER_ACCOUNT_OFFLINE
GM_AGENT_OFFLINE
TRADE_CONNECTION_DOWN
QUOTE_CONNECTION_DOWN
QUOTE_STALE
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

不要把所有券商错误变成 HTTP 500。

---

# 36. 网络与鉴权

## 36.1 V1 网络

```text
主系统
↔ 私有局域网
↔ Windows Broker Node
```

采用：

```text
HTTP + Bearer Token + Windows Firewall 来源 IP 限制
```

不暴露公网交易端口。

## 36.2 后续跨网

如果未来主系统迁移到异地 / 云端：

优先：

```text
Tailscale / WireGuard / 企业 VPN
```

再考虑：

```text
HTTPS / mTLS
```

不尝试破解掘金未公开协议。

## 36.3 凭据

不得：

```text
写入 Git
写入 Markdown
输出完整 token
输出完整账户号
前端持久化真实券商凭据
```

---

# 37. 日志与审计

## 37.1 `api.log`

记录：

```text
request_id
endpoint
client_order_id
command_id
HTTP status
latency
```

## 37.2 `gm_agent.log`

记录：

```text
Agent lifecycle
gm connection
command claim / dispatch
query / reconcile
callback processing
execution quote subscribe / unsubscribe
```

## 37.3 `audit.jsonl`

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
QUOTE_SUBSCRIBE
QUOTE_UNSUBSCRIBE
```

## 37.4 脱敏

```text
账户：****1234
token：永不输出
```

---

# 38. 部署设计

## 38.1 API Service

初期：

```text
start_api.ps1
```

稳定后可注册：

```text
Windows Task Scheduler
或 Windows Service / NSSM
```

## 38.2 GM Strategy Agent

通过国投掘金：

```text
我的策略
→ 交易
→ 绑定仿真 / 实盘账号
→ 启动
```

策略代码版本源：

```text
D:\QMT\workspace\broker_node\gm_agent
```

如果掘金要求策略目录内存在 `main.py`，使用部署脚本复制，不手工维护两份不同代码。

## 38.3 GUI 终端依赖

正式运维必须以 B 方案验证事实为准。

如果关闭掘金终端后交易接口失效：

```text
掘金终端在线 = Broker Node 的生产前置条件
```

API `/status` 必须能反映 Agent / 通道离线。

不要通过 SSH 会话盲目启动 GUI 程序。

---

# 39. 配置示例

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
    "durable_db": "D:\\QMT\\workspace\\broker_node\\runtime\\broker_node.sqlite3",
    "quote_cache_db": "D:\\QMT\\workspace\\broker_node\\runtime\\quote_cache.sqlite3",
    "log_dir": "D:\\QMT\\logs\\broker_node"
  },

  "sync": {
    "command_poll_interval_ms": 200,
    "unfinished_order_sync_seconds": 5,
    "account_position_sync_seconds": 15,
    "full_reconcile_seconds": 60,
    "agent_offline_seconds": 5
  },

  "execution_quote": {
    "enabled": true,
    "quote_flush_interval_ms": 200,
    "subscription_lease_seconds": 120,
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

`freshness_ms=3000` 仅为示例，不代表最终阈值。

---

# 40. 主系统需要修改 / 新增的部分

AI Coder 在主系统侧只增加 Broker 接入能力，不重写业务模型。

## 40.1 新增

```text
GMBrokerHttpGateway
BrokerEventConsumer
ExecutionQuotePoller
Broker Connection State
Broker Reconciliation State
```

## 40.2 TradePlan 不改职责

仍负责：

```text
参考入场价
最高可接受入场价
风险参考价
风险预算
确认数量
交易逻辑
```

## 40.3 ExecutionPlan

仍负责：

```text
执行方式
限价
触发条件
区间条件
活动 / 暂停 / 完成 / 取消 / 过期
```

如果当前实现尚未保存触发时的 quote snapshot，可以增加“执行审计字段”，但不得把券商字段塞回 TradePlan。

## 40.4 Order

需要确保至少能保存：

```text
client_order_id
broker_order_id
exchange_order_id（若实际有）
raw_broker_status
normalized status
broker reject code / reason
```

## 40.5 Fill

需要稳定 broker execution key，支持 callback/query/reconcile 幂等。

## 40.6 Position

必须支持：

```text
quantity
available_quantity
```

券商事实用于纠正本地推算。

---

# 41. 开发阶段与实施顺序

## Phase 0：固化验证事实

```text
1. 读取 B 方案验证代码和结果
2. 输出 gm_verified_contract.md
3. 提取 raw fixtures
4. 确认 callback / query / quote 字段
```

禁止直接根据网上示例开始写 mapper。

## Phase 1：生产只读 Broker Node

实现：

```text
工程骨架
Durable SQLite
API health / status
Agent heartbeat
账户查询
持仓查询
订单查询
成交查询
startup reconcile
raw + normalized mapper
```

此阶段禁止交易写。

## Phase 2：Execution Quote Service

实现：

```text
ExecutionPlan owner subscription
Tick/L1 subscribe
latest quote cache
last / bid1 / ask1
market time
freshness
disconnect / recover
execution quote API
```

不实现 Bar、L2、历史数据。

## Phase 3：仿真交易写

实现：

```text
command journal
client_order_id idempotency
LIMIT submit
order callback
execution report
cancel
Fill 去重
UNKNOWN
T+1 available guard
reconcile
```

只允许 SIM。

## Phase 4：主系统 Gateway

实现：

```text
GMBrokerHttpGateway
BrokerEventConsumer
ExecutionQuotePoller
```

联调现有：

```text
TradePlan
ExecutionPlan
Order
Fill
Position
```

## Phase 5：端到端仿真

完整流程：

```text
TradePlan
→ Confirm
→ ExecutionPlan
→ 注册 Execution Quote
→ 实时价格条件满足
→ quote FRESH
→ PreTradeRiskCheck
→ max acceptable price
→ Order
→ Broker Node
→ gm.api
→ 仿真柜台
→ Order callback
→ Fill
→ Position
→ reconcile
```

连续运行多个交易日。

## Phase 6：实盘只读

```text
allow_live_orders=false
```

只同步实盘：

```text
资金
持仓
可卖数量
订单
成交
```

与国投终端人工核对。

## Phase 7：受控实盘

通过本文后面的实盘验收后再开启：

```text
allow_live_orders=true
BROKER_NODE_ENABLE_LIVE_ORDERS=YES
```

初期建议：

```text
人工确认 ExecutionPlan
小额
单标的
保留国投终端人工兜底
每日收盘 full reconcile
```

---

# 42. AI Coder 推荐编码顺序

```text
01. 阅读现有交易域代码，不改模型
02. 阅读 B 方案实机验证代码
03. 输出 gm_verified_contract.md
04. 提取 fixtures
05. 建 broker_node 工程骨架
06. Durable SQLite schema
07. API health / status
08. Agent heartbeat
09. gm read-only adapter
10. Mapper 单元测试
11. account / positions / orders / fills API
12. startup reconciliation
13. quote subscription owner 模型
14. Tick/L1 subscribe
15. quote cache + freshness
16. execution quote API
17. command journal + idempotency
18. SIM LIMIT submit
19. order callback
20. execution report + Fill 幂等
21. cancel
22. UNKNOWN crash recovery
23. available_quantity guard
24. pause / resume
25. 主系统 GMBrokerHttpGateway
26. BrokerEventConsumer
27. ExecutionQuotePoller
28. 价格触发端到端联调
29. max_acceptable_price 双层保护
30. 完整 SIM 回归
31. LIVE 只读
32. 受控 LIVE 验收
33. 开启生产 live gate
```

---

# 43. 修订后的测试与验收方案

> 本章取代之前单独的《国投证券「掘金量化交易系统」接入测试与验收方案 V1.2》。  
> 测试目标从“探索掘金所有行情/数据能力”收缩为“验证它能否可靠支撑本交易系统的真实执行”。

## 43.1 测试工具定位

保留一个独立轻量：

```text
Broker Validation Console
券商接口测试控制台
```

它不是生产 Broker Node，也不进入实际自动执行链路。

用途：

```text
开发验收
仿真回归
掘金升级后回归
Windows 重装后验收
实盘只读核对
受控实盘测试
故障诊断
```

如果该 Console 已经存在，直接按本文删减 Case；不要重新开发第二套。

## 43.2 页面范围

只保留：

```text
1. 总览
2. 测试项目
3. 实盘验证
4. 历史记录
5. 设置
```

不加入：

```text
历史行情浏览器
财务数据页
选股数据页
L2 数据页
Bar 数据页
```

## 43.3 测试状态

统一：

```text
NOT_TESTED
RUNNING
PASS
FAIL
WARNING
NOT_SUPPORTED
SKIPPED
```

## 43.4 测试风险级别

### SAFE

不会产生真实委托：

```text
环境
连接
资金
持仓
订单查询
成交查询
执行行情
断线检测
恢复 / 对账
```

### SIMULATION

只允许仿真账户：

```text
仿真下单
仿真撤单
仿真成交
拒单
部分成交
T+1
```

### LIVE_WRITE

会产生真实委托：

```text
实盘限价单
实盘撤单
实盘实际成交（只有用户明确选择时）
```

必须逐项人工确认，不支持批量。

---

# 44. 测试清单 A：环境与连接

## ENV-01 SDK / Python 版本

验证：

```text
Python 3.9.13
gm 可 import
gm 版本
```

## ENV-02 掘金终端版本

记录实际版本，绑定测试历史。

## ENV-03 Windows 运行环境

记录：

```text
OS
hostname
Python path
Broker Node version
```

## CONN-01 GM Agent 初始化

验证 Agent 正常进入运行状态。

## CONN-02 认证

验证 strategy/token 认证成功。

## CONN-03 账户绑定

验证实际绑定账户与预期一致。

## CONN-05 行情通道

验证执行行情通道连接状态可识别。

## CONN-06 交易通道

验证交易通道连接状态可识别。

## CONN-07 主动连接状态

Broker Node `/status` 必须能够明确报告连接状态，不能仅凭启动成功推断。

---

# 45. 测试清单 B：账户与券商事实

## ACC-01 账户基础信息

账户 ID、账户模式、状态，页面脱敏。

## ACC-02 总资产

可正常读取。

## ACC-03 可用资金

可正常读取。

## ACC-04 冻结资金

若 gm 当前版本提供稳定字段则验证；否则 `NOT_SUPPORTED`，不是 FAIL。

## ACC-05 持仓市值

若接口提供，验证。

## ACC-06 全部持仓

读取完整持仓列表。

## ACC-07 单只持仓

能从标准化列表正确定位。

## ACC-08 可卖数量

重点验证：

```text
quantity
available_quantity
frozen_quantity（若有）
```

## ACC-09 成本

验证实际 SDK 可提供的成本 / 成本价字段。

## ACC-10 当日委托

可查询。

## ACC-11 未完成委托

可查询。

## ACC-12 当日成交

可查询。

## ACC-13 与国投终端人工核对

至少：

```text
总资产
可用资金
持仓数量
可卖数量
当日委托
当日成交
```

结果：

```text
一致
可解释差异
不一致
```

---

# 46. 测试清单 C：执行行情

本组只验证交易执行真正使用的实时行情。

## MKT-01 最新行情可用

指定股票订阅成功，并能获取最新状态。

## MKT-02 最新价

`last` 可用。

## MKT-03 买一 / 卖一

```text
bid1
bid1_volume
ask1
ask1_volume
```

可用。

## MKT-05 Tick / L1 实时更新

观察一段时间，`quote_revision` 持续变化。

不要求保存每个 Tick。

## MKT-06 行情时间戳

验证：

```text
market_time 存在
格式可标准化
不明显倒序
```

## MKT-07 基本连续性

只做工程级检查：

```text
订阅期间有更新
没有无原因长时间停止
```

不做高频行情质量基准。

## MKT-13 行情断线识别

断线后：

```text
freshness = DISCONNECTED
```

## MKT-14 行情恢复

恢复后：

```text
重新订阅
quote_revision 恢复更新
```

## MKT-15 STALE 识别

最后有效 quote 超过阈值且处于应有行情的交易阶段时：

```text
STALE
```

并验证不能触发行情驱动的新订单。

### 本版本明确删除的行情测试

```text
MKT-04 五档盘口专项要求
MKT-08 Tick 重复率专项统计
MKT-09 HFT 式 P50/P95/P99 延迟基准
MKT-10 1分钟 Bar
MKT-11 多周期 Bar
MKT-12 Bar / 深度人工比对
MKT-16 L2 逐笔成交
MKT-17 L2 逐笔委托
MKT-18 L2 委托队列
```

如将来某个执行算法明确依赖，再单独增加。

---

# 47. 测试清单 D：ExecutionPlan 价格条件

## TP-02 最高可接受价

能从主系统正确传递到订单 safety constraint。

## TP-03 价格区间判断

ExecutionEngine 使用 Broker Node 的最新 FRESH quote 判断是否进入区间。

## TP-04 超过最高买入价

不得生成突破 `max_acceptable_price` 的 BUY LIMIT。

## TP-05 Trigger 与 Limit 分离

验证：

```text
Trigger condition != Order Limit Price
```

## TP-06 Broker Node 硬保护

即使主系统出现 bug，传入：

```text
BUY limit > max_acceptable_price
```

Broker Node 必须 `FAILED_SAFE`。

## TP-07 行情失效阻断

```text
STALE / DISCONNECTED
```

时禁止新的行情触发执行。

## TP-08 观察模式

只订阅 quote、判断区间，不下单时，能够完整运行并解除订阅。

---

# 48. 测试清单 E：仿真交易

## SIM-01 LIMIT BUY

可提交。

## SIM-02 LIMIT SELL

使用仿真可卖持仓，可提交。

## SIM-03 订单查询

提交后可通过 query 查到。

## SIM-04 撤单

未成交单可撤。

## SIM-05 撤单终态

callback / query 最终一致。

## SIM-06 可成交限价单

验证真实仿真成交。

## SIM-07 成交后持仓变化

买入后正确变化。

## SIM-08 成交后资金变化

正确变化。

## SIM-09 卖出后持仓变化

正确变化。

## SIM-10 卖出后资金变化

正确变化。

---

# 49. 测试清单 F：订单生命周期

## ORD-01 client_order_id

全链路可追踪。

## ORD-02 broker_order_id

可保存并映射。

## ORD-03 exchange_order_id

如 gm 实际返回则保存；否则 `NOT_SUPPORTED`。

## ORD-04 状态变化全过程

记录从发送到终态。

## ORD-05 未成交

状态正确。

## ORD-06 部分成交

尽量在仿真复现。

若环境无法稳定制造：

```text
WARNING / NOT_REPRODUCED
```

但代码必须有部分成交模型和 fixture 测试。

## ORD-07 全部成交

`FILLED` 正确。

## ORD-08 撤单状态

正确。

## ORD-09 拒单状态

仅仿真安全构造。

## ORD-10 过期状态

仅当当前接口存在对应概念时验证，否则 `NOT_SUPPORTED`。

## ORD-11 Order / Fill 分离

一个 Order 可以多 Fill。

## ORD-12 成交均价

累计正确。

## ORD-13 成交数量累计

多个 Fill 不重复、不漏计。

---

# 50. 测试清单 G：错误与安全失败

## ERR-01 非法数量

返回可读错误。

## ERR-02 非法价格

返回可读错误。

## ERR-03 资金不足

仿真验证券商拒单。

## ERR-04 可卖不足

先由 Broker Node guard 阻断；如直接走柜台测试则验证柜台 reason。

## ERR-05 不支持证券 / 市场

安全条件下验证。

## ERR-06 错误信息可读

保留：

```text
error code
message
reject reason
raw detail
```

## ERR-07 API 异常不得重复下单

核心验收项。

---

# 51. 测试清单 H：实时事件

## EVT-01 委托状态 callback

验证 `on_order_status` 实际到达和映射。

## EVT-02 成交 callback

验证 `on_execution_report`。

## EVT-03 账户状态 callback

若当前版本实际可用则验证，否则不作为 P0。

## EVT-04 交易断线

能够产生节点状态变化。

## EVT-05 交易恢复

恢复后必须 reconcile。

## EVT-06 行情断线

Execution Quote 进入断开状态。

## EVT-07 行情恢复

恢复订阅。

## EVT-08 错误 callback

可记录且不会导致 Agent 崩溃。

## EVT-09 callback vs query

同一 Order / Fill 最终事实一致。

## EVT-10 重复 callback 幂等

不重复 Fill、不重复更新累计数量。

---

# 52. 测试清单 I：T+1

## T1-01 仿真当日买入

成功。

## T1-02 当日 available_quantity

验证新买入普通 A 股的可卖状态符合账户返回事实。

## T1-03 当日卖出限制

验证 guard / 券商行为。

## T1-04 次交易日

重启 / 新日 reconcile 后，重新读取实际 available_quantity。

## T1-05 实盘已有持仓卖出

只在用户明确选择已有可卖持仓时做实盘验证。

## T1-06 Day1 买入 / Day2 卖出

不是生产启用 P0，属于完整 round-trip 验收可选项。

---

# 53. 测试清单 J：恢复与对账

## REC-01 Agent 重新初始化

可从测试界面 / 运维步骤触发。

## REC-02 重启后资金

通过券商 query 恢复。

## REC-03 重启后持仓

通过券商 query 恢复。

## REC-04 重启后未完成订单

不依赖内存。

## REC-05 重启后当日成交

不依赖之前 callback。

## REC-06 漏 callback

程序离线期间产生的仿真成交，恢复后 query/reconcile 能找回。

## REC-07 掘金 / 通道关闭检测

按实际验证可控方式操作。

## REC-08 重新登录恢复

重新连接后先 reconcile。

## REC-09 完整对账

必须重新同步：

```text
资金
持仓
未完成订单
当日订单
当日成交
```

## REC-10 reconcile 幂等

连续执行两次，不重复订单、不重复 Fill。

---

# 54. 测试清单 K：实盘只读

只有实盘只读通过后才允许进入写测试。

## LIVE-R-01 实盘账户连接

## LIVE-R-02 实盘资金

与终端核对。

## LIVE-R-03 实盘持仓

与终端核对。

## LIVE-R-04 实盘可卖数量

与终端核对。

## LIVE-R-05 实盘委托

与终端核对。

## LIVE-R-06 实盘成交

与终端核对。

---

# 55. 测试清单 L：受控实盘写

> 不批量运行。每次必须由用户在页面填写参数并二次确认。

## LIVE-W-01 测试权限开关

测试 Console 默认：

```text
LIVE_WRITE_ENABLED=false
```

这与生产 Broker Node 的 live gate 是两个不同开关。

## LIVE-W-02 测试数量上限

测试工具第一阶段普通股票：

```text
<= 100 股
```

仅是测试工具限制，不是生产交易上限。

## LIVE-W-03 最大测试金额

由用户配置。

## LIVE-W-04 参数确认

显示：

```text
证券
方向
限价
数量
预计金额
最新执行行情
```

## LIVE-W-05 实盘 LIMIT 提交

人工二次确认后执行。

## LIVE-W-06 国投终端可见

真实订单必须在终端可查。

## LIVE-W-07 API 查询一致

可查询刚发送订单。

## LIVE-W-08 实盘撤单

人工触发。

## LIVE-W-09 撤单结果核对

callback / query / 终端一致。

## LIVE-W-10 实盘真实成交

只有用户明确愿意承担真实持仓风险时测试，不是自动验收项。

后续实盘买入后卖出 round trip 可继续按原测试思路执行，但不作为 Broker Node V1.2 开发完成的前置条件。

---

# 56. 测试清单 M：安全

## SAFE-01 实盘默认关闭

## SAFE-02 无人工确认不得运行 Console 实盘写测试

## SAFE-03 测试数量超限阻断

## SAFE-04 测试金额超限阻断

## SAFE-05 测试工具禁止实盘批量下单 / close-all

## SAFE-06 凭据不写源码

## SAFE-07 凭据不入 Git

## SAFE-08 日志脱敏

## SAFE-09 防双击

## SAFE-10 client_order_id 幂等

## SAFE-11 行情 STALE / DOWN 阻断价格条件执行

## SAFE-12 SIM / LIVE 页面和节点状态明显区分

## SAFE-13 UNKNOWN submit 不自动重放

## SAFE-14 account mismatch 禁止写

---

# 57. 测试清单 N：部署与网络

V1.2 不再验证 Linux 直接 gm 实盘，也不探索掘金远程 endpoint。

只验证实际采用的部署：

## DEP-01 Windows 本机

```text
国投掘金
+
GM Agent
+
Broker API Service
```

可稳定共存。

## DEP-02 主系统 → Windows Broker API

私网可达。

## DEP-03 防火墙

只允许预期主系统来源访问 Broker API 端口。

## DEP-04 不暴露公网

验证交易 API 不直接开放公网。

## DEP-05 掘金终端依赖

确认关闭 / 退出掘金后实际行为，并写入运维手册。

---

# 58. 测试 Console 历史记录

每次测试保存：

```text
test_run_id
test_case_id
开始时间
结束时间
Broker Node version
gm version
掘金终端版本
账户模式
参数
结果
一句话结论
关键指标
错误
原始证据引用
```

用于：

```text
SDK / 终端升级回归
Windows 重装
策略环境变化
券商权限变化
线上故障复现
```

---

# 59. 一键验收报告

Console 提供：

```text
[生成验收报告]
```

报告只覆盖 V1.2 实际生产所需能力：

```text
环境
连接
账户
持仓 / T+1
Execution Quote
仿真交易
订单 / Fill
callback
恢复 / 对账
安全
实盘只读
受控实盘写（如已测试）
```

不再报告：

```text
L2
历史 Bar
财务数据
选股数据
算法单能力大全
```

---

# 60. V1.2 上线前 P0 验收集合

## 必须通过

### 环境 / 连接

```text
ENV-01 ~ ENV-03
CONN-01 / 02 / 03 / 05 / 06 / 07
```

### 账户

```text
ACC-01 ~ ACC-13
```

### 执行行情

```text
MKT-01
MKT-02
MKT-03
MKT-05
MKT-06
MKT-07
MKT-13
MKT-14
MKT-15
```

### 执行条件

```text
TP-02 ~ TP-08
```

### 仿真订单

```text
SIM-01 ~ SIM-10
```

### 订单 / Fill

```text
ORD-01 ~ ORD-13
```

部分成交无法稳定制造可 WARNING，但代码 fixture 必须覆盖。

### 错误与 callback

```text
ERR-01 ~ ERR-07
EVT-01 / 02 / 04 / 05 / 06 / 07 / 08 / 09 / 10
```

### T+1

```text
T1-01 ~ T1-04
```

### 恢复

```text
REC-01 ~ REC-10
```

### 安全

```text
SAFE-01 ~ SAFE-14
```

### 部署

```text
DEP-01 ~ DEP-05
```

## 实盘生产 Gate 开启前另外必须通过

```text
LIVE-R-01 ~ LIVE-R-06
```

并至少完成一次：

```text
LIVE-W-05 ~ LIVE-W-09
```

即：

```text
真实 LIMIT 提交
→ 终端可见
→ API 可见
→ 人工撤单
→ 状态一致
```

是否做“真实成交”由用户明确决定，不作为开启生产实盘的强制条件。

---

# 61. 自动化测试策略

## 61.1 单元测试

必须覆盖：

```text
SecurityIdMapper
Decimal 序列化
时间 normalization
order status mapping
Fill 幂等
client_order_id 幂等
payload conflict
max_acceptable_price guard
available_quantity guard
Execution Quote freshness
quote subscription reference / lease
UNKNOWN recovery state machine
```

## 61.2 Fixture 来源

优先来自实机：

```text
tests/fixtures/gm_orders/...
tests/fixtures/gm_fills/...
tests/fixtures/gm_positions/...
tests/fixtures/gm_quotes/...
```

禁止人工编造“看起来像 gm”的字段证明 mapper 正确。

## 61.3 SIM 集成测试

```text
Quote subscribe
→ LIMIT submit
→ query
→ callback
→ cancel / fill
→ Position / Cash
→ reconcile
```

## 61.4 Crash Test

至少模拟：

```text
QUEUED 时退出
DISPATCHING 时退出
ACK 后退出
Fill callback 前退出
Fill callback 后主系统未消费退出
```

验证恢复行为。

---

# 62. AI Coder 禁止事项

```text
× 重新尝试 gmtrade 生产接入
× 引入 xtquant / xttrader
× 用掘金替代 Tushare 做研究数据源
× 从掘金拉财务数据
× 从掘金构建历史行情数据库
× 开发全市场行情扫描
× 开发 L2 / 多周期 Bar 作为 V1.2 目标
× 重写 TradePlan / ExecutionPlan / Order / Fill / Position
× Broker Node 自己选股
× Broker Node 自己算仓位
× Broker Node 自己触发区间交易
× 本地模拟撮合
× callback 丢失时伪造成交
× UNKNOWN submit 自动重放
× 把 202 Accepted 当券商 ACCEPTED
× 只靠 callback 不 query/reconcile
× 只靠 query 不接 callback
× 把 Trigger Price 当 Order Limit Price
× BUY limit 超过 max_acceptable_price
× STALE quote 触发行情条件订单
× 把每个 Tick 写 durable SQLite FULL
× 用 float 作为最终价格 / 资金格式
× 把 token / 完整账号写日志
× 把交易 API 直接暴露公网
× 把测试用 100 股限制硬编码成生产上限
```

---

# 63. Definition of Done

Broker Node V1.2 满足以下条件才算完成。

## 63.1 工程

```text
[ ] API 与 GM Agent 分进程
[ ] gm 调用符合已验证线程模型
[ ] Durable DB WAL + FULL
[ ] Quote Cache 与 durable journal 分离
[ ] 所有价格金额 Decimal / string
[ ] 凭据不入 Git / 日志
```

## 63.2 券商事实

```text
[ ] 资金
[ ] 持仓
[ ] available_quantity
[ ] 当日订单
[ ] 未完成订单
[ ] 当日成交
[ ] 与国投终端核对
```

## 63.3 Execution Quote

```text
[ ] 只订阅活动 ExecutionPlan 标的
[ ] last
[ ] bid1 / ask1
[ ] market time
[ ] freshness
[ ] disconnect / recover
[ ] 订阅在计划结束后解除
[ ] 不保存历史 Tick
[ ] 不提供研究数据服务
```

## 63.4 订单

```text
[ ] client_order_id 幂等
[ ] LIMIT submit
[ ] cancel
[ ] order callback
[ ] Fill callback
[ ] callback/query/reconcile 去重
[ ] 部分成交模型
[ ] UNKNOWN 不重放
```

## 63.5 执行安全

```text
[ ] SIM / LIVE 强隔离
[ ] account mismatch 锁定
[ ] max_acceptable_price hard guard
[ ] available quantity sell guard
[ ] disaster quantity/notional guard
[ ] global pause
[ ] STALE quote 不触发价格条件订单
```

## 63.6 恢复

```text
[ ] Agent 重启恢复
[ ] 掘金断线识别
[ ] 重连后 full reconcile
[ ] callback 漏失可 query 找回
[ ] 重复 reconcile 幂等
[ ] 外部人工订单可识别
```

## 63.7 端到端

```text
[ ] TradePlan → ExecutionPlan → Execution Quote → Order → Broker → Fill → Position
[ ] Trigger 与 Limit 分离
[ ] BUY limit 不突破 max_acceptable_price
[ ] Broker Position 最终纠正本地推算
[ ] Broker Node 未承担选股 / 财务 / 历史行情职责
```

---

# 64. 后续扩展原则

未来如果出现明确需求：

```text
更低延迟的 quote stream
SSE / WebSocket
五档盘口
L2
算法单
新的券商
新的研究数据源
```

均单独立项。

特别是“研究数据源”：

> 如果未来 Tushare 不够用，增加新的 Data Provider Adapter；不要因为掘金能返回某些数据，就把 Broker Node 扩成数据中心。

---

# 65. 一句话架构总结

```text
Tushare / 数据中心负责研究和选股
              ↓
         TradePlan
              ↓
        ExecutionPlan
              ↓
主系统只为活动执行计划读取掘金最新 Execution Quote
              ↓
         生成原子 Order
              ↓
      Windows Broker Node
              ↓
       gm.api + MODE_LIVE
              ↓
         国投证券柜台
```

最终原则：

> **研究数据留在数据中心；执行行情只服务交易；交易逻辑留在主系统；券商事实服从国投柜台；Broker Node 保持薄、稳、幂等、可恢复。**

---

# 66. V1.2 完整开发实施计划

正式开发计划已写入：

[国投掘金_Broker_Node_V1.2_完整开发实施计划.md](/Users/xipilabs/dev/Experiment/LLL/docs/国投掘金_Broker_Node_V1.2_完整开发实施计划.md)

该计划是 V1.2 的组成部分，覆盖完整生产功能、测试清单、阶段门槛、交付物、已知差异和完成判定。开发过程中必须持续更新计划和 CHANGELOG，不得用未声明的简版、Demo 或临时代码替代 V1.2 正式范围。
+

---

# 66. V1.2 完整开发实施计划

V1.2 的正式开发计划已单独写入：

[国投掘金_Broker_Node_V1.2_完整开发实施计划.md](/Users/xipilabs/dev/Experiment/LLL/docs/国投掘金_Broker_Node_V1.2_完整开发实施计划.md)

该计划是本设计文档的组成部分，覆盖完整生产功能、测试清单、阶段门槛、交付物、已知差异和完成判定。开发过程中必须持续更新该计划及 CHANGELOG；不得以未声明的简版、Demo 或临时实现替代 V1.2 正式范围。
