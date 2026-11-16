# 交易系统前端 UI/UX 字段与状态验收矩阵

本文件记录非配置页面的真实数据来源、运行态证据和仍受交易时段限制的项目。原型 HTML 中的示例值只允许出现在前端清理逻辑中，不能作为接口失败或字段缺失时的显示兜底。

## 页面字段来源

| 页面 | 主要服务端来源 | 已核对的核心字段 | 运行入口 |
|---|---|---|---|
| 交易总览 | `/api/trading/overview`、`/api/trading/broker` | 账户净资产、现金、仓位、盈亏、风险、待办、Trade、订单/成交流水 | 一级导航 → 总览 |
| Trade 列表 | `/api/trading/overview` | 一行一个 Trade、状态筛选、类型、持仓/可卖、价格/成本、盈亏、风险、创建时间 | 一级导航 → 交易 |
| Trade Detail | `/api/trades/{id}`、`position-state`、`exit-rules`、`risk-reference-history` | Trade、TradePlan、TradeLeg、持仓、风险、时间线、退出规则、成交日志 | Trade 列表 → 详情 |
| OPEN | `/api/trading/overview` + 当前用户输入 + 建仓计算接口 | 交易类型、Playbook、Thesis、入场价、最高买入价、风险参考价、数量、风险计算摘要 | 总览 → 创建交易 |
| ADD | Trade 详情接口 + `/api/trades/{id}/add/calculate` | 当前持仓、可卖/T+1、参考价、最高价、数量、加仓理由、失败处理、风险变化 | Trade Detail → 加仓 |
| REDUCE | Trade 详情接口 + `/api/trades/{id}/reduce/calculate` | 当前持仓、可卖/T+1、固定数量/比例/目标剩余、卖出价、原因、剩余风险参考 | Trade Detail → 减仓 |
| CLOSE | Trade 详情接口 + `/api/trades/{id}/close/calculate` | 总持仓、可执行数量、T+1 延期数量、最低接受价、触发条件、清仓原因 | Trade Detail → 清仓 |
| 风险参考 | Trade 详情、风险历史接口、当前用户输入 | Trade/TradeLeg 范围、原风险参考、新风险参考、计算结果、历史记录、失败态 | Trade Detail → 调整风险参考 |
| Action Detail | Trade 详情关联的 TradePlan → ExecutionPlan → Order → Fill | 动作、状态、原因、风险预算、数量、价格参数、委托号、成交数量/价格/金额/时间、影响分析 | Trade Detail → 查看动作详情 |
| ExecutionPlan | `/api/trading/overview` | 所属 Trade、动作、数量、执行方式、价格参数、有效期、状态、暂停/恢复/取消 | 一级导航 → 执行 |
| Order | `/api/trading/overview`、订单详情接口 | 筛选、方向、价格、数量、状态、券商订单号、所属动作、成交回报、撤单/失败态 | 一级导航 → 订单 |
| Position | `/api/trading/overview` | Trade 类型/状态、数量、可卖、成本、现价、市值、盈亏、仓位、风险和动作入口 | 一级导航 → 持仓 |

## K 线功能替换

OPEN、Trade Detail 和风险参考页面原型中的静态图形已移除，统一复用项目既有 `KLineModal` 与 `/api/screening/kline/{code}` 数据链路。Trade Detail / 风险参考从当前 Trade 的真实证券代码加载，并叠加真实成交标记；OPEN 在尚未选择证券时明确显示待选择状态，不生成示例行情。

## 已完成的状态证据

- account_id=1 / 2 切换后，账户、Trade、订单、成交、持仓和详情上下文保持隔离。
- 空订单、空持仓、无执行计划、券商不可用、HTTP 403、HTTP 503 和加载中状态均已在浏览器运行态验证。
- `PENDING_SUBMIT / SUBMITTED / ACCEPTED / PARTIALLY_FILLED / CANCEL_PENDING / UNKNOWN` 到合法终态的后端状态转移已测试；`FILLED / CANCELLED / REJECTED / EXPIRED` 不允许重新打开。
- 当前仿真账号的命中价格委托会立即成交，没有真实未成交订单，因此挂单、部分成交和撤单不伪造测试结果。
- 生产构建、TypeScript 检查、Python 编译、前后端联合测试均已通过；最新联合测试为 `184 passed`。

## 尚需交易时段证据

- 使用新仿真账号完成可卖数量大于零的 REDUCE 和 CLOSE，并验证实现盈亏、剩余持仓、Trade 状态。
- 在真实未成交条件下验证挂单、部分成交、撤单和对应状态回报。
- 开盘后验证实时行情、PRICE_TRIGGER、PRICE_RANGE 及单次委托保护。
- 第 4 项 DOM、布局、字体、颜色、响应式和视觉验收由用户完成，本项目不代替。

详细执行记录以[交易系统前端 UI/UX 全量重构开发计划](/Users/xipilabs/dev/Experiment/LLL/docs/交易系统前端UI_UX全量重构开发计划_V1.0.md)为准。
