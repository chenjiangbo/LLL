# 国投掘金 Broker Node V1.2 完整开发实施计划

> 本文是《国投掘金_Broker_Node_接入技术设计与实施方案_V1.2.md》的正式实施计划。
> 本计划覆盖 V1.2 全部生产功能、测试清单、验收门槛和交付物，不允许以简版、Demo 或临时实现替代。

## 当前执行状态（2026-09-03）

- Phase 0：已完成账户、资金、持仓、订单、成交和真实 L1/tick fixtures；撤单最终态和断线恢复按后续阶段记录。
- Phase 1：已完成并通过 Windows 实机端到端验收。Agent、SQLite 快照/事件、启动对账、heartbeat、只读 API 和鉴权均已验证。
- Phase 2：已实现 L1 行情规范化、quote cache、ExecutionPlan 订阅租约、订阅刷新、当前行情预热、freshness 和 API；已通过交易时段 Windows tick 实测。
- Phase 3：已完成 SIM 命令日志、下单/撤单门禁、订单回报与成交幂等、T+1 可卖校验、订单关联和恢复性重试；Windows 实机时段仿真买入/成交/查询/终态撤单保护已验证。T+1 映射已由真实 `available_now` 字段和单元测试校验；上一轮实机卖出请求已被柜台按可卖持仓拒绝。由于该仿真柜台对测试限价单立即成交，未能制造“未成交后最终撤单”的 broker 事实，标记为 NOT_REPRODUCED，不伪造 PASS。
- Phase 4（主系统 Gateway）：已完成 HTTP Gateway、事件游标消费者和 Execution Quote Poller；已通过本地契约测试。事件消费采用“应用成功后推进游标”，重复事件由主系统事务处理器幂等落库。
- Phase 5（端到端仿真编排）：已完成主系统 ExecutionEngine 的 Quote → 条件判断 → PreTradeRisk → 本地 Order 创建 → BrokerGateway 提交编排，并覆盖 FRESH/STALE/DISCONNECTED、LIMIT/PRICE_TRIGGER/PRICE_RANGE、最高可接受价传递和 trigger snapshot。真实柜台买入/成交事实沿用 Phase 3 Windows 验证，未重复制造额外真实订单。Phase 6-7：尚未完成，不提前标记通过。
- 追加实现：暂停并撤销未完成系统订单接口；Windows 启动脚本改为显式选择 Broker Node 配置；行情/交易连接断开或状态未知时自动进入暂停、禁用执行并要求对账；上述内容已有本地集成/单元测试。Phase 9-12 的完整 Windows 故障注入、交易时段部分成交、实盘只读和最终 P0 验收仍未标记通过。

## 1. 执行原则

1. 严格按 V1.2 第 1 至 65 节实施，不缩减功能范围。
2. 每个阶段必须通过阶段门槛，才能进入下一阶段。
3. 未验证的 gm 字段、枚举、回调参数和线程行为标记为 UNVERIFIED，不猜测。
4. 失败、超时、断线和无法确认的券商写操作必须显式报错或进入保护状态。
5. 禁止 mock、伪造券商事实、隐藏 fallback、截断数据和静默跳过。
6. SIM/LIVE 严格隔离，实盘写入默认关闭。
7. TradePlan、ExecutionPlan、ExecutionEngine、Order、Fill、Position 的业务职责不迁移到 Broker Node。
8. 任何架构、业务边界或测试范围变化，先记录原因、影响和方案并取得用户确认。
9. 每阶段完成时更新 CHANGELOG、阶段状态、测试结果、未完成项和下一阶段入口条件。

## 2. 当前基线和已知差异

已有：

- 主系统 TradePlan、ExecutionPlan、Order、Fill、Position 的现有实现；
- 基础 BrokerGateway 抽象；
- 独立 broker_sdk_probe 验证项目；
- 方案 B 的账户、资金、持仓、下单、成交验证结果。

尚未完成：

- gm_verified_contract.md；
- 完整脱敏 gm fixtures；
- Windows Broker Node；
- Broker API Service；
- GM Strategy Agent；
- Durable Journal 和 Ephemeral Quote Cache；
- Execution Quote Service；
- GMBrokerHttpGateway、BrokerEventConsumer、ExecutionQuotePoller；
- 完整撤单、部分成交、断线恢复、UNKNOWN、对账和安全验收。

已知差异：

- 现有主系统 BrokerGateway 是同步基础抽象，需扩展适配层，不重写交易域模型。
- 现有主系统部分金额和价格使用 float；Broker API、Broker Node、SQLite 和 gm 边界必须使用 Decimal。默认只在边界显式转换，不未经确认整体改造主系统。
- 方案 B 已验证账户、资金、持仓、下单、成交；撤单、部分成交、完整行情订阅/恢复仍不得标记为已验证。
- broker_sdk_probe 只复用验证证据和测试基础设施，不直接作为生产 Broker Node。

## 3. Phase 0：固化 gm.api 验证契约

### 工作

整理真实 Probe 代码、结果和 Windows 实机信息，确认：

- Python、gm、掘金版本；
- strategy_id、token、账户绑定和 MODE_LIVE；
- 账户、资金、持仓、可卖、成本字段；
- 当日订单、未完成订单、成交字段；
- broker_order_id、exchange_order_id、broker_execution_id；
- raw order status；
- on_order_status、on_execution_report 参数；
- 账户、行情、交易连接回调；
- 错误回调；
- 下单、撤单、查询、subscribe/unsubscribe；
- 断线、重连、终端关闭、重启后的行为。

### 交付物

- broker_node/docs/gm_verified_contract.md；
- tests/fixtures/gm_account；
- tests/fixtures/gm_positions；
- tests/fixtures/gm_orders；
- tests/fixtures/gm_fills；
- tests/fixtures/gm_quotes。

所有样本脱敏。未验证内容保留 UNVERIFIED 标记，不人工编造。

### 门槛

已有账户、资金、持仓、订单、成交字段具备原始证据；未完成项具备明确的后续测试编号和阻塞说明。

## 4. Phase 1：工程骨架和环境隔离

建立 D:\QMT\workspace\broker_node\，包含：

- docs、config、shared、api_service、gm_agent、runtime、scripts、tests；
- README、CHANGELOG、requirements-api.txt；
- config.example.json 和不入 Git 的 config.local.json；
- API Service 和 GM Strategy Agent 两个进程。

GM Agent 固定使用 C:\Program Files\Python39\python.exe、Python 3.9.13、gm 3.0.186。API Service 创建独立 .venv-api，不导入 gm.api。

提供 API 启动、停止、健康检查、GM Agent 部署、runtime 备份脚本。不得修改掘金程序组件或内置运行环境。

### 门槛

目录、依赖、配置、日志、凭据脱敏和启动方式可复核；两个进程边界明确。

## 5. Phase 2：共享模块、数据库和状态机

实现 shared 下的：

- enums.py；
- dto.py；
- config.py；
- db.py；
- decimal_utils.py；
- time_utils.py；
- masking.py；
- security_id.py。

建立 broker_node.sqlite3，包含：

- node_state；
- commands；
- order_links；
- broker_events；
- snapshots；
- quote_subscriptions。

建立 quote_cache.sqlite3 和 quote_state。

实现：

- WAL、FULL、busy_timeout、foreign_keys；
- 可重复初始化/migration；
- request_id、client_order_id、cancel_request_id 幂等；
- payload_hash 和冲突识别；
- raw + normalized；
- Decimal 和 ISO 8601；
- 命令、订单、事件状态机；
- 事件 seq；
- 账户和日志脱敏。

### 门槛

约束、事务、重复请求、冲突请求、事件游标、重启恢复和数据一致性测试通过。

## 6. Phase 3：GM Agent 只读链路

实现：

- lifecycle.py；
- gm_adapter.py；
- gm_mapper.py；
- gm_executor.py；
- callbacks.py；
- account_sync.py；
- position_sync.py；
- order_sync.py；
- fill_sync.py；
- reconciler.py。

启动顺序固定为：

加载配置 → 打开 DB → heartbeat → 初始化 gm → 等待行情/交易通道 → 获取账户 → 校验账户 → startup reconcile → 同步账户、持仓、订单、成交 → 恢复行情订阅 → 检查 UNKNOWN → 计算 readiness → 消费命令。

只读能力覆盖：

- 账户、总资产、可用资金、冻结资金；
- 持仓、可卖、成本；
- 当日订单、未完成订单、当日成交；
- 账户状态、行情连接、交易连接；
- Agent heartbeat。

查询失败必须显式报告 stale 或错误，不得静默返回旧数据。

### 门槛

资金、持仓、可卖、订单、成交与国投终端人工核对；query 和 callback 均保存 raw 数据并幂等更新。

## 7. Phase 4：Broker API Service 只读接口

实现：

- GET /api/v1/health；
- GET /api/v1/status；
- GET /api/v1/account；
- GET /api/v1/positions；
- GET /api/v1/orders?scope=today；
- GET /api/v1/orders?scope=unfinished；
- GET /api/v1/fills?scope=today；
- GET /api/v1/events；
- POST /api/v1/sync。

实现 Bearer Token、统一错误码、HTTP 状态、timeout、Agent 离线、stale snapshot、account mismatch、pause 和 reconciliation lock。

本阶段交易写接口必须关闭。

### 门槛

通过 SAFE 只读、鉴权、离线、stale snapshot、after_seq 和主动同步测试。

## 8. Phase 5：Execution Quote Service

实现：

- PUT /api/v1/execution-quotes/subscriptions/{execution_plan_id}；
- DELETE /api/v1/execution-quotes/subscriptions/{execution_plan_id}；
- GET /api/v1/execution-quotes/subscriptions；
- GET /api/v1/execution-quotes。

支持 last、bid1、bid1_volume、ask1、ask1_volume、market time、received time、revision、freshness 和连接状态。

实现 owner subscription、lease、重启恢复、无人使用时 unsubscribe、quote cache、断线/恢复和 FRESH/STALE/DISCONNECTED/UNKNOWN。

禁止实现历史行情、Bar、L2、全市场订阅和研究数据服务。

### 门槛

通过 MKT-01、02、03、05、06、07、13、14、15；TP-02、03、05、07、08。STALE/DISCONNECTED 时不得触发行情条件订单。

## 9. Phase 6：执行边界和安全保护

四类 ExecutionPlan 的职责必须保持：

- LIMIT：主系统生成原子限价单；
- PERSISTENT_LIMIT：主系统撤旧单、确认终态、生成新订单；
- PRICE_TRIGGER：主系统使用 FRESH quote 判断触发；
- PRICE_RANGE：主系统使用 FRESH quote 判断区间。

Broker Node 实现：

- max_acceptable_price 双层保护；
- require_fresh_quote；
- available_quantity 卖出保护；
- 数量、金额、市场和证券类型硬保护；
- Trigger 与 Limit 分离；
- trigger quote snapshot 审计。

不得实现选股、仓位计算、追价、自动补单、条件判断或交易决策。

### 门槛

TP-02 至 TP-08、ERR-01、ERR-02、ERR-04、SAFE-03、SAFE-04、SAFE-11 有可复核结果。

## 10. Phase 7：仿真原子交易写链路

仅允许 SIM。

实现：

POST /orders → durable persist → 202 QUEUED → CLAIMED → DISPATCHING → 串行 gm LIMIT submit → 保存 broker_order_id → ORDER_SUBMIT_RESULT → order callback/query → execution report/query → Fill → snapshot/reconcile。

覆盖：

- client_order_id 幂等；
- payload 冲突 409；
- 订单状态映射；
- Fill 幂等；
- 拒单原因；
- 手续费；
- 部分成交模型；
- 全部成交；
- T+1 guard；
- 撤单命令。

撤单调用成功不等于最终撤单成功，必须由 callback/query 确认最终状态。终态订单重复撤单返回 ALREADY_TERMINAL。

### 门槛

通过 SIM-01 至 SIM-10、ORD-01 至 ORD-13、ERR-03 至 ERR-07、EVT-01、02、08、09、10、T1-01 至 T1-04。无法稳定制造部分成交/未成交时标 WARNING 或 NOT_REPRODUCED，但代码和 fixture 仍须覆盖。

当前 Phase 3 实机证据：BUY 100 股以 80.00 成交并产生成交回报；随后 SELL 受 `available_now=0` 的 T+1 保护；低价测试单也被仿真柜台立即成交，因此实际 broker 级“挂单后撤单”标记 NOT_REPRODUCED。已验证终态订单重复撤单返回 `409 ALREADY_TERMINAL`，且未误报撤单成功。

## 11. Phase 8：主系统 Gateway 和事件消费

实现：

- GMBrokerHttpGateway；
- BrokerEventConsumer；
- ExecutionQuotePoller。

扩展现有 BrokerGateway，不让 TradePlan/ExecutionPlan 直接拼 HTTP。

Event Consumer 在 Order、Fill、Position 事务提交后推进 event seq，支持断线补事件、重复事件、Fill 幂等、Position 券商事实校正和外部订单。

### 门槛

通过：

TradePlan → ExecutionPlan → Execution Quote → PreTradeRiskCheck → Order → Broker Node → gm.api → callback/query → Fill → Position。

## 12. Phase 9：恢复、对账、外部订单和保护锁

实现并测试：

- API Service 重启；
- GM Agent 重启；
- 掘金终端关闭；
- 行情/交易通道断开和恢复；
- 主系统断开后事件补齐；
- callback 丢失后 query/reconcile 补齐；
- origin=EXTERNAL 人工订单；
- 重复 reconcile；
- DISPATCHING 崩溃转 UNKNOWN；
- UNKNOWN 禁止自动重放；
- reconciliation_required 保护锁；
- 账户、持仓、订单、成交差异告警。

### 门槛

REC-01 至 REC-10、EVT-04 至 EVT-07、SAFE-09、SAFE-10、SAFE-13、SAFE-14 全部有恢复证据和报告。

## 13. Phase 10：暂停、SIM/LIVE 隔离、部署和网络

实现：

- POST /api/v1/control/pause；
- POST /api/v1/control/resume；
- POST /api/v1/control/pause-and-cancel-open-orders。

pause 不自动撤旧单；pause-and-cancel 逐笔撤销、逐笔确认、逐笔记录。

每个 Broker Node 实例只绑定一个账户。仿真、实盘使用不同策略实例、strategy_id、配置、runtime DB 和端口。

实盘写入必须同时满足：

- allow_live_orders=true；
- BROKER_NODE_ENABLE_LIVE_ORDERS=YES。

提供 Windows Task Scheduler/NSSM、DHCP Reservation/稳定主机名、防火墙来源 IP、禁止公网暴露、掘金 GUI 桌面会话依赖说明。

### 门槛

SAFE-01 至 SAFE-14、DEP-01 至 DEP-05 通过。

## 14. Phase 11：Validation Console 和验收报告

继续保持 broker_sdk_probe 独立，不嵌入生产 Broker Node。

补齐 V1.2 测试组：

- ENV、CONN；
- ACC；
- MKT；
- TP；
- SIM；
- ORD；
- ERR；
- EVT；
- T1；
- REC；
- LIVE-R；
- LIVE-W；
- SAFE；
- DEP。

统一状态：

NOT_TESTED、RUNNING、PASS、FAIL、WARNING、NOT_SUPPORTED、SKIPPED。

每次测试保存：

- test_run_id；
- test_case_id；
- 时间；
- Broker Node、gm、掘金版本；
- 账户模式；
- 参数；
- 结果；
- 结论；
- 错误；
- 原始证据引用。

提供一键验收报告，不报告已删除的 L2、历史 Bar、财务和选股能力。

## 15. Phase 12：完整验收和实盘 Gate

### 仿真

逐项执行 V1.2 第 60 节 P0 清单。无法执行的项目必须保留并说明原因，不能删除。

### 实盘只读

仿真 P0 通过后，执行 LIVE-R-01 至 LIVE-R-06，并与国投终端核对。

### 受控实盘

用户明确授权后，执行 LIVE-W-05 至 LIVE-W-09：

真实 LIMIT → 终端可见 → API 可见 → 人工撤单 → 状态一致。

每次人工填写参数并二次确认，不支持批量。真实成交不是开启生产 Gate 的强制条件，但不得自动执行实盘写入。

## 16. 测试和验收完整覆盖

必须覆盖 V1.2 的 ENV、CONN、ACC、MKT、TP、SIM、ORD、ERR、EVT、T1、REC、LIVE-R、LIVE-W、SAFE、DEP 全部 Case。

特别不得省略：

- 未完成订单；
- 撤单；
- 部分成交模型；
- 重复回报；
- UNKNOWN；
- callback 丢失；
- Agent 崩溃；
- API 重试；
- 人工外部订单；
- T+1；
- STALE 行情；
- 账户错配；
- 实盘默认关闭；
- 防火墙和公网暴露检查。

## 17. 最终交付物

- broker_node 完整源码；
- gm_verified_contract.md；
- 脱敏真实 fixtures；
- SQLite 初始化/migration；
- config.example.json；
- requirements-api.txt；
- Windows 启停、健康检查、部署、备份脚本；
- Execution Quote Service；
- GMBrokerHttpGateway；
- BrokerEventConsumer；
- ExecutionQuotePoller；
- 单元、API 集成、SIM 集成和故障恢复测试；
- API 文档；
- 运维 README；
- CHANGELOG；
- 仿真验收报告；
- 故障恢复测试报告。

## 18. 完成判定

只有同时满足以下条件才算 V1.2 完成：

- V1.2 第 60 节 P0 验收通过；
- V1.2 第 63 节 Definition of Done 通过；
- 全部阶段门槛通过；
- 所有未完成、WARNING、NOT_SUPPORTED 项有明确记录；
- 没有未披露的简化、临时代码、伪数据或隐藏 fallback。
