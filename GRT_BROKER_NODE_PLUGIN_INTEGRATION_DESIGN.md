# GRT / Chrome 插件与 Broker Node 对接设计草案

状态：方案设计，尚未实现

## 1. 本次代码调查结论

### 1.1 现有 Broker Node 的职责

当前 `broker_node` 已经具备：

- 持久化命令表 `commands`；
- `request_id` 幂等；
- `QUEUED → CLAIMED → DISPATCHING → ACKED/FAILED_SAFE/UNKNOWN` 生命周期；
- 订单、成交、持仓和账户快照；
- `order_links` 以及券商事实事件；
- 交易暂停、对账阻断和实盘开关；
- 通过 gm.api 执行 `ORDER_SUBMIT` / `ORDER_CANCEL`。

当前 Broker Node 不具备：

- `broker.note` 接口或同名命令；
- GRT 条件单命令类型；
- Chrome 扩展连接管理；
- GRT 页面任务 ID、页面状态和页面错误的持久化；
- GRT 条件单与 LLL `ExecutionPlan` 的映射。

### 1.2 当前交易系统的执行模型

现有 `ExecutionPlan` 支持：

- `LIMIT`；
- `PERSISTENT_LIMIT`；
- `PRICE_TRIGGER`；
- `PRICE_RANGE`。

但现有执行引擎仍然承担触发职责：

```text
ExecutionQuotePoller
  → ExecutionEngine.evaluate()
  → 主系统判断价格是否触发
  → ExecutionEngine.submit()
  → Broker Node /api/v1/orders
  → gm.api order_volume()
```

`PRICE_TRIGGER` 和 `PRICE_RANGE` 目前由主系统读取行情后判断，触发后仍转换为普通限价委托。这个模型与“把条件单交给 GRT 服务器执行”不同。

## 2. 目标执行模型

新的 GRT 执行通道应改成：

```text
交易计划
  → ExecutionPlan
  → 生成 GRT 条件单描述
  → Broker Node 持久化 GRT 命令
  → Windows Chrome 插件领取命令
  → GRT 页面填写并提交
  → 插件读取页面结果
  → Broker Node 保存 GRT 条件单事实
  → 主系统读取任务状态
```

GRT 条件单提交之后，主系统不再为了该条件单持续轮询行情，也不再自行实现“到点后再调用普通下单接口”的后台定时提交逻辑。

主系统仍然负责：

- 交易计划和风险规则；
- 参考价、最高可接受价、数量和有效期；
- 条件单类型选择；
- 提交前风险校验；
- 插件和 GRT 任务状态监控；
- 最终委托、成交、持仓的事实同步和对账。

## 3. 建议的命令边界

不建议让 Chrome 插件直接理解 LLL 的完整交易计划。Broker Node 应把交易计划转换成明确的页面命令。

建议新增独立的 GRT 命令族：

```text
GRT_CONDITION_CREATE
GRT_CONDITION_MODIFY
GRT_CONDITION_PAUSE
GRT_CONDITION_RESUME
GRT_CONDITION_CANCEL
GRT_CONDITION_QUERY
GRT_CONDITION_SYNC
```

可以保留 `broker.note` 作为远程系统调用层的业务入口，但它不能替代 Broker Node 内部的持久化命令类型。建议语义为：

```text
远程系统 / broker.note
  → Broker Node GRT 命令 API
  → commands 表
  → Windows Chrome 插件
```

## 4. GRT 条件命令数据结构

建议把 GRT 页面字段放入独立的 `grt_condition` 对象，不把条件字段继续塞进普通订单的 `price` 字段：

```json
{
  "request_id": "...",
  "client_execution_id": "LLL-EP-...",
  "broker_account_key": "...",
  "account_mode": "SIM",
  "command_type": "GRT_CONDITION_CREATE",
  "symbol": "SZ:000651",
  "side": "BUY",
  "quantity": 100,
  "valid_until": "2026-09-24T15:00:00+08:00",
  "condition": {
    "type": "PRICE",
    "operator": "LESS_EQUAL",
    "trigger_price": "..."
  },
  "order": {
    "type": "LIMIT",
    "price": "..."
  },
  "source": {
    "system": "LLL",
    "execution_plan_id": "..."
  },
  "safety_constraints": {
    "max_acceptable_price": "..."
  }
}
```

插件只执行页面动作，并返回页面事实，例如：

```json
{
  "command_id": "...",
  "page_task_id": "...",
  "page_status": "RUNNING",
  "condition_type": "价格条件",
  "symbol": "SZ:000651",
  "side": "BUY",
  "quantity": 100,
  "order_type": "市价委托",
  "valid_until": "2026-09-24",
  "page_message": "添加成功",
  "observed_at": "..."
}
```

## 5. 参考价和最高价的关键语义

当前交易计划表单的核心输入是：

- 参考入场价；
- 最高可接受价。

这两个字段不能直接机械地分别映射成 GRT 的任意两个价格字段，必须先固定业务语义：

### 方案 A：参考价作为触发价，最高价作为限价

```text
价格达到参考价
  → GRT 触发
  → 以最高可接受价以内的限价委托提交
```

这个方案最接近“参考价 + 最高价”的原有语义，但前提是 GRT 价格条件单支持独立的限价委托价格，并且页面字段可以稳定填写。

### 方案 B：参考价作为触发价，GRT 使用市价委托

```text
价格达到参考价
  → GRT 提交市价委托
```

这个方案不能严格保证最高可接受价。最高价只能作为提交前提示或风险约束，不能作为成交价格上限，因此不应默认采用。

### 方案 C：参考价和最高价映射成 GRT 区间/高卖低买/其他条件

这需要确认 GRT 对该功能的真实语义，不能仅凭名称推断。只有当页面明确表达“触发价”和“委托限价”两个独立概念时，才能作为原交易计划的等价映射。

当前建议：先把 `trigger_price`、`order_price`、`max_acceptable_price` 在数据模型中分开，禁止用一个 `limit_price` 字段同时表达三个含义。

## 6. 状态模型

GRT 命令不应直接复用普通 gm.api 订单状态。建议分两层保存：

### 命令状态

```text
RECEIVED
→ VALIDATED
→ QUEUED
→ CLAIMED
→ DISPATCHING
→ PAGE_OPENED
→ FORM_FILLED
→ SUBMITTING
→ SUBMITTED
```

异常状态：

```text
FAILED_SAFE
UNKNOWN
```

### GRT 页面任务状态

```text
RUNNING
PAUSED
TRIGGERED
ORDER_SUBMITTED
FILLED
ENDED
CANCELLED
REJECTED
UNKNOWN
```

页面点击后无法确认是否提交成功时，必须进入 `UNKNOWN`，先查询 GRT 条件单列表，禁止自动重复点击提交。

## 7. Broker Node 与 Chrome 插件的连接方式

第一版建议使用 Windows 本机回环连接：

```text
Chrome Extension Service Worker
  ⇄ http://127.0.0.1:<port>/api/v1/grt/commands
  ⇄ Windows Broker Node
```

推荐插件侧采用短轮询或长轮询领取命令，而不是让远程服务器直接连接浏览器。原因是：

- Chrome 插件只需要访问本机 Broker Node；
- 远程端不需要暴露浏览器控制端口；
- Broker Node 可以统一做账户隔离、幂等、审计和暂停控制；
- Windows 机器断网时，命令仍有明确的本地持久化状态。

插件需要的最小接口：

```text
POST /api/v1/grt/worker/register
POST /api/v1/grt/worker/heartbeat
POST /api/v1/grt/commands/claim
POST /api/v1/grt/commands/{command_id}/events
POST /api/v1/grt/commands/{command_id}/complete
```

插件必须声明当前页面账户、页面 URL、页面是否显示“模拟/实盘”、扩展版本和能力版本。Broker Node 在 `SIM` / `LIVE` 账户不匹配时必须拒绝命令。

## 8. 需要改造的代码边界

### Broker Node

- 扩展 `CommandType`；
- 新增 GRT 命令 payload 校验；
- 增加 GRT worker 注册、心跳、领取和回报接口；
- 增加 GRT 页面任务表或等价持久化结构；
- 保存 `page_task_id`、页面回显、页面错误和最后观察时间；
- 保留现有幂等、UNKNOWN、暂停和审计规则；
- GRT 命令不能进入现有 gm.api `BrokerCommandExecutor`。

### 主交易系统

- 扩展 `ExecutionPlan` 的执行通道，例如 `execution_channel = GM_NATIVE | GRT_CONDITION`；
- 增加 `grt_condition_type` 和专属参数；
- 将“本地行情触发后普通下单”的路径与“GRT 条件单托管”的路径分开；
- 保留参考价和最高可接受价的风险约束，但先明确二者与 GRT 触发价/委托价的映射；
- 创建 GRT 条件命令，而不是调用 `/api/v1/orders`；
- 将 GRT 条件单状态纳入执行计划详情和对账状态；
- 成交后继续通过 Broker Node 的事实平面更新订单、成交和持仓。

### Chrome 插件

- 只负责 GRT 页面控制，不负责风险计算；
- 使用页面结构定位通用控件和类型专属控件；
- 提交前检查账户标识和模拟/实盘标识；
- 每一步发送结构化事件；
- 提交后读取列表回显确认；
- 超时或页面状态不明时回报 `UNKNOWN`，不自动重复提交。

## 9. 当前不能直接实现的地方

在正式修改代码前，必须先确认以下产品语义：

1. `参考入场价` 是否就是 GRT 的触发价；
2. `最高可接受价` 是否必须成为最终委托限价；
3. 若 GRT 某类条件单只能提交市价委托，是否允许该类交易计划使用它；
4. GRT 的页面任务是否需要由系统保存任务标识，还是仅通过股票、方向、数量和有效期匹配；
5. `broker.note` 是远程业务 API 名称，还是现有项目中另一个尚未检出的内部接口。

这些问题会改变 `ExecutionPlan` 的正式 schema 和执行状态机，因此本文件先作为设计基线，不在未确认前直接改造生产交易路径。
