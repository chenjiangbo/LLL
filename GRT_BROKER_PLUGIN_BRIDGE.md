# Broker Node → Chrome 扩展控制桥接

## 目标

远程系统提交交易意图后，由 Windows Broker Node 将命令交给 Chrome 扩展；扩展只负责控制 GRT 页面并返回页面确认到的结果。

## 当前项目状态

现有 Broker Node 已有持久化命令队列、幂等 request_id、订单状态和 gm.api 事实读取接口，但当前代码中尚未发现 `broker.note` 名称或 Chrome 扩展桥接实现。

现有 `/api/v1/orders` 和 `/api/v1/orders/{client_order_id}/cancel` 是 gm.api 交易通道，不等同于 GRT 页面控制通道。

## 页面控制验证结果

2026-09-18 在模拟盘完成了 GRT 条件单的页面控制闭环：浏览器控制层能够打开条件单表单、选择“价格条件”、输入并确认 `白云机场(600004)`、填写触发价格 `1` 元、数量 `100` 股、截止日期 `2026/09/24`，点击“确定”，并在列表中读回运行中记录。

因此当前结论是：GRT 页面本身具备被 Chrome 自动化控制的可行性；尚未完成的是“远程 `broker.note` → Windows 扩展 → 页面控制”的正式命令桥接，不应把两者混为一谈。

## 建议的命令边界

未来需要单独定义 GRT 命令类型，例如：

- `GRT_CONDITION_CREATE`
- `GRT_CONDITION_MODIFY`
- `GRT_CONDITION_PAUSE`
- `GRT_CONDITION_RESUME`
- `GRT_CONDITION_CANCEL`
- `GRT_CONDITION_QUERY`

每条命令至少需要：`request_id`、`client_execution_id`、目标账户上下文、业务参数、超时、幂等键和审计状态。

## 不可省略的状态

```text
QUEUED
→ CLAIMED
→ PREPARING
→ PREPARED
→ VALIDATED
→ SUBMITTING
→ SUBMITTED
```

如果页面提交后无法确认条件单是否创建：

```text
SUBMITTING → UNKNOWN
```

禁止自动重试，必须先查询 GRT 条件单列表以及 gm.api 可见事实。

## Fact Plane

GRT 是控制通道；gm.api 可能是事实通道。实盘中必须单独验证 GRT/手机 App/其他客户端产生的委托、成交、持仓和资金是否能被 gm.api 读取；本项不在模拟盘页面控制验证中假设成立。
