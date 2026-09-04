# 交易与持仓管理模块 — TradePlan 设计与实现方案 V0.1

## 1. 文档目的

本文档用于指导当前项目首先实现「交易与持仓管理」一级功能中的第一个子模块：

**TradePlan（交易计划）**

当前阶段的目标不是实现实盘交易，也不是实现量化策略自动交易，而是先做出一个可以真实使用的交易计划页面，让用户能够：

1. 人工选择一只股票；
2. 输入自己对入场位置和风险位置的判断；
3. 系统自动计算建议仓位、资金占用、计划风险、收益风险比等；
4. 用户可以调整计划数量；
5. 系统指出明显风险和不合理之处；
6. 保存和管理交易计划；
7. 为后续虚拟盘、ExecutionRule、订单、持仓和实盘连接提供统一数据入口。

V0.1 应优先追求：

- 简单；
- 容易理解；
- 容易实际使用；
- 计算结果透明；
- 不过度工程化；
- 不依赖尚未实现的选股或研究模块。

---

# 2. 一级功能规划

整个一级模块正式名称建议为：

## 交易与持仓管理

UI 一级菜单名称可简化为：

> 交易

未来完整结构规划如下。

| 二级功能 | 作用 | 当前阶段 |
|---|---|---|
| TradePlan 交易计划 | 制定交易方案、计算风险和仓位 | **本次开发** |
| 虚拟账户 | 模拟资金、持仓和交易结果 | 下一阶段 |
| 执行任务 ExecutionRule | 持续挂单、分批买入等机械执行 | 后续 |
| 订单与成交 | 管理订单状态和实际成交 | 后续 |
| 持仓管理 | 买入后的仓位、风险位置和退出管理 | 后续 |
| 风险规则 | 单笔风险、单股仓位、总仓位等统一配置 | 逐步完善 |
| 券商连接 | QMT/iQuant等实盘接口 | 后期 |
| 对账与异常 | 本地账户与券商账户核对 | 实盘阶段 |

整体关系：

```text
TradePlan
    ↓
ExecutionRule
    ↓
Order
    ↓
PaperBroker / RealBroker
    ↓
Fill
    ↓
Position
    ↓
持仓管理
```

当前 V0.1 只实现最上面的：

```text
TradePlan
```

但避免将 TradePlan 与未来 Order、Broker 等概念混在一起。

---

# 3. TradePlan 的产品定义

TradePlan 是：

> 用户对一笔交易的事前决策记录和风险规划。

它回答：

- 我准备在哪个价格附近买？
- 最多涨到什么价格，我仍愿意买？
- 如果判断错误，我目前认为风险参考位置在哪里？
- 这笔交易最多愿意承担多少账户风险？
- 系统建议我买多少？
- 买入后占账户多少仓位？
- 如果达到风险参考位置，大约损失多少？
- 如果达到目标位置，大约赚多少？
- 当前交易计划有没有明显问题？

TradePlan **不负责**：

- 自动选股；
- 自动判断股票结构；
- 自动寻找止损位；
- 自动判断趋势已经破坏；
- 自动提交订单；
- 每天重新挂单；
- 自动止盈止损；
- 券商连接。

上述能力由以后其他模块承担。

---

# 4. V0.1 功能范围

V0.1 首先完整支持：

> **做多股票的新建仓位计划**

即：

```text
OPEN_LONG
```

数据模型可以预留：

```text
ADD_POSITION
REDUCE_POSITION
CLOSE_POSITION
```

但第一版无需把加仓、减仓、清仓逻辑全部实现。

原因是新建仓位已经可以验证 TradePlan 最核心的产品体验：

> 风险位置 → 风险预算 → 仓位计算 →人工计划。

待实际使用 V0.1 后，再根据体验实现加仓和持仓管理。

---

# 5. 独立运行原则

V0.1 暂时与选股系统解耦。

TradePlan 不依赖：

- A/B/C 池；
- 市场状态；
- 行业强度；
- 个股评分；
- AI 研究结论；
- 自动技术分析。

如果当前项目已有股票基础数据，则可以复用：

- 股票代码；
- 股票名称；
- 最新价格。

如果没有，则允许用户手工输入。

后续可以增加：

```text
research_context_snapshot
```

用于保存创建交易计划时已有的研究信息，但它不是 TradePlan 运行的必要条件。

---

# 6. 页面结构

建议增加一级菜单：

```text
交易
```

当前只出现一个可用二级入口：

```text
交易计划
```

页面路径建议：

```text
/trading/trade-plans
/trading/trade-plans/new
/trading/trade-plans/{id}
```

---

# 7. TradePlan 列表页

列表页主要用于查看已经创建的交易计划。

字段：

| 字段 | 说明 |
|---|---|
| 股票 | 股票代码 + 名称 |
| 状态 | Draft / Ready / Cancelled / Expired |
| 参考入场价 | 用户填写 |
| 风险参考价 | 用户填写 |
| 建议数量 | 系统计算 |
| 人工计划数量 | 如果用户进行了覆盖 |
| 计划资金仓位 | 自动计算 |
| 计划账户风险 | 自动计算 |
| 创建时间 | 自动 |
| 有效期 | 自动/用户设置 |

支持：

- 新建 TradePlan；
- 编辑 Draft；
- 查看详情；
- 复制一个 TradePlan；
- 取消计划；
- 删除 Draft。

已经确认的计划原则上不要直接删除，应保留历史。

---

# 8. 新建 TradePlan 页面整体布局

推荐采用：

```text
┌──────────────────────────────┬─────────────────────┐
│                              │                     │
│       左侧：计划输入           │   右侧：计算结果      │
│                              │   Sticky 固定显示     │
│                              │                     │
└──────────────────────────────┴─────────────────────┘
```

右侧结果随着左侧输入实时更新。

在窄屏情况下改为上下排列。

---

# 9. 第一部分：标的信息

## 用户输入

### 股票

支持：

- 股票代码搜索；
- 股票名称搜索。

如果项目已经有证券基础数据，则自动带入。

字段：

```text
symbol
security_name
```

### 当前价格

如果已有行情数据：

```text
current_price
```

自动读取。

如果暂时没有实时行情，可以允许手工修改。

当前价格主要用于：

- 当前计划是否已经超出最高接受价格提示；
- 页面参考。

它不作为核心仓位计算依据。

仓位核心计算使用：

```text
reference_entry_price
```

---

# 10. 第二部分：账户与风险参数

因为 V0.1 暂时没有完整账户系统，因此提供一个简单的「交易参数」配置。

全局保存，而不是每次重复输入。

## 必要参数

```text
account_equity
available_cash
current_invested_amount
default_risk_pct
max_single_position_pct
max_total_position_pct
```

示例：

```text
账户净资产             100,000
可用现金                60,000
当前已投入资金          30,000

默认单笔计划风险           0.8%
单股最大资金仓位            12%
账户最大总资金仓位           80%
```

用户创建 TradePlan 时自动读取这些默认值。

其中：

### account_equity

账户总净资产。

### available_cash

目前可用于交易的资金。

### current_invested_amount

目前已经投入股票的资金。

V0.1 可以人工维护。

以后接入虚拟账户或真实券商后自动取得。

### default_risk_pct

默认单笔交易允许的计划风险。

例如：

```text
0.8%
```

这里表示：

> 如果交易按计划失败，希望本次计划损失尽量控制在账户净资产 0.8% 左右或以下。

它不是必须用满的风险预算，而是上限。

### max_single_position_pct

单只股票最大资金仓位。

### max_total_position_pct

整个账户允许投入股票的最大资金仓位。

---

# 11. 第三部分：交易核心输入

用户真正需要填写的核心内容尽量控制在少数几个字段。

## 11.1 参考入场价

字段：

```text
reference_entry_price
```

含义：

> 用户认为比较理想、并用于计算交易计划的参考买入价格。

例如：

```text
10.00
```

---

## 11.2 最高可接受买入价

字段：

```text
max_acceptable_entry_price
```

例如：

```text
10.30
```

含义：

> 如果市场价格高于该价格，原 TradePlan 不应被直接执行，需要用户重新判断。

要求：

```text
max_acceptable_entry_price >= reference_entry_price
```

---

# 12. 风险参考位置

字段：

```text
risk_reference_price
```

例如：

```text
9.50
```

这是整个仓位计算最核心的输入之一。

它的定义是：

> 用户认为如果价格运行至该区域，本次交易的原始判断已经明显受到挑战，并以此价格作为计划风险估算基准。

注意：

它**不是程序自动判断的止损价**。

它也不意味着：

> 价格达到这里一定自动卖出。

风险参考位置完全由用户人工判断。

程序当前只使用它进行：

- 单股风险计算；
- 建议仓位计算；
- R 倍数计算；
- 风险提示。

---

# 13. 风险参考备注

可选字段：

```text
risk_reference_note
```

例如：

```text
前一轮日线调整低点附近。
如果有效跌破，需要重新判断原来的上涨假设。
```

这里只记录人的判断。

V0.1 不做：

- 自动结构识别；
- 自动技术止损；
- AI 判断结构是否已经失效。

---

# 14. 本次计划风险比例

默认值来自：

```text
default_risk_pct
```

例如：

```text
0.8%
```

字段：

```text
plan_risk_pct
```

允许用户针对某一次 TradePlan 修改。

例如：

```text
0.5%
1.0%
```

修改后立即重新计算。

页面应该明显显示：

```text
系统默认：0.8%
本次计划：1.0%
```

如果本次高于默认值，显示 Warning。

例如：

```text
⚠ 本次计划风险比默认水平高 25%
```

正式版可以增加：

```text
absolute_max_risk_pct
```

用于硬限制。

V0.1 可以先预留字段。

---

# 15. 盈利目标

字段：

```text
target_type
target_price
```

支持两种：

```text
FIXED_TARGET
TREND_FOLLOWING
```

## 固定目标

例如：

```text
第一目标价：12.00
```

系统计算收益风险比。

## 趋势跟踪

用户可以选择：

```text
暂不设置固定目标
```

此时：

```text
target_price = null
```

系统不强迫用户填写目标价。

显示：

```text
固定收益风险比：未计算
退出方式：趋势跟踪 / 后续人工管理
```

---

# 16. TradePlan 有效期

字段：

```text
expires_at
```

V0.1 支持：

```text
3个交易日
5个交易日
自定义日期
直到手动取消
```

目的：

避免几周或几个月以前制定的计划，在市场环境已经变化后仍被当成有效计划。

V0.1 暂时可以按自然日期实现。

以后正式版本再统一升级为交易日计算。

---

# 17. 交易逻辑备注

字段：

```text
thesis
```

可选。

示例：

```text
日线调整结束后重新转强，
当前位置风险收益比较合理，
计划尝试建立第一笔仓位。
```

当前不要求 AI 理解这些文字。

主要用于：

- 人工回顾；
- 后续复盘；
- 记录当时为什么做这笔交易。

---

# 18. 核心计算逻辑

所有核心计算应集中在后端或 Domain Service：

```text
TradePlanCalculator
```

不要在不同页面分别写一套公式。

前端可以实时请求计算接口。

后端是最终权威结果。

---

# 19. 单股计划风险

对于做多：

```text
unit_risk =
reference_entry_price - risk_reference_price
```

必须满足：

```text
unit_risk > 0
```

否则无法形成有效交易计划。

例如：

```text
参考入场     10.00
风险参考      9.50

每股计划风险   0.50
```

---

# 20. 价格风险比例

```text
price_risk_pct =
unit_risk / reference_entry_price
```

示例：

```text
0.50 / 10.00 = 5%
```

页面显示：

```text
计划价格风险：5.00%
```

不要显示成：

```text
最大亏损5%
```

因为真实交易可能存在跳空和成交偏差。

---

# 21. 计划风险预算金额

```text
risk_budget_amount =
account_equity × plan_risk_pct
```

例如：

```text
账户净资产：100,000
风险比例：0.8%

风险预算：
800元
```

---

# 22. 按风险预算允许的数量

```text
qty_by_risk =
risk_budget_amount / unit_risk
```

向下取整。

例如：

```text
800 / 0.50
=
1600股
```

---

# 23. 单股最大仓位允许数量

```text
max_single_position_amount =
account_equity × max_single_position_pct
```

```text
qty_by_single_position =
max_single_position_amount /
reference_entry_price
```

例如：

```text
账户：100,000
单股最大仓位：12%

最多投入：
12,000

10元股票：

最多约：
1200股
```

---

# 24. 可用现金允许数量

```text
qty_by_cash =
available_cash /
reference_entry_price
```

---

# 25. 总仓位限制允许数量

首先计算剩余资金容量：

```text
max_total_invested_amount =
account_equity × max_total_position_pct
```

```text
remaining_total_capacity =
max_total_invested_amount -
current_invested_amount
```

如果小于0：

```text
remaining_total_capacity = 0
```

然后：

```text
qty_by_total_position =
remaining_total_capacity /
reference_entry_price
```

---

# 26. 建议数量

核心公式：

```text
recommended_qty_raw =
MIN(
    qty_by_risk,
    qty_by_single_position,
    qty_by_cash,
    qty_by_total_position
)
```

然后按照证券数量步进向下修整：

```text
recommended_qty
```

V0.1 不要在代码中到处硬编码交易单位。

建立：

```text
quantity_step
```

证券基础数据能提供时使用真实规则。

暂时无法获取时：

```text
quantity_step = 100
```

但标记为规划层估算。

未来真正提交订单时，由 Broker/Order 层再次进行交易规则校验。

---

# 27. 最终限制因素

系统必须记录：

```text
limiting_factor
```

枚举：

```text
RISK_BUDGET
SINGLE_POSITION_LIMIT
CASH_LIMIT
TOTAL_POSITION_LIMIT
```

页面必须告诉用户：

> 为什么系统建议这个数量。

例如：

```text
风险预算允许        1600股
单股仓位允许        1200股
现金允许            6000股
总仓位允许          5000股

系统建议：
1200股

限制因素：
单只股票最大仓位
```

这是 TradePlan 非常重要的产品体验。

---

# 28. 计划投入金额

```text
planned_notional =
recommended_qty × reference_entry_price
```

---

# 29. 计划资金仓位

```text
planned_position_pct =
planned_notional /
account_equity
```

页面同时显示：

```text
预计投入：12,000元
资金仓位：12.00%
```

---

# 30. 实际使用的计划风险

因为最终建议数量可能受到其他限制，所以实际风险往往低于风险预算。

```text
planned_risk_amount =
recommended_qty × unit_risk
```

```text
planned_account_risk_pct =
planned_risk_amount /
account_equity
```

例如：

```text
风险预算：
800元 / 0.80%

最终建议：
1200股

实际计划风险：
600元 / 0.60%
```

页面必须同时显示：

```text
风险预算上限：0.80%
实际计划风险：0.60%
```

---

# 31. 1R / 2R / 3R 价格

即使没有目标价，也自动计算：

```text
1R_price =
reference_entry_price + unit_risk

2R_price =
reference_entry_price + unit_risk × 2

3R_price =
reference_entry_price + unit_risk × 3
```

页面显示：

```text
1R：10.50
2R：11.00
3R：11.50
```

这个功能开发成本很低，V0.1 直接实现。

---

# 32. 固定目标收益风险比

如果存在：

```text
target_price
```

计算：

```text
reward_per_share =
target_price - reference_entry_price
```

```text
reward_risk_ratio =
reward_per_share / unit_risk
```

例如：

```text
参考入场：10.00
风险参考：9.50
目标：12.00

收益风险比：
4.0R
```

如果未设置固定目标：

```text
reward_risk_ratio = null
```

不要阻止计划确认。

---

# 33. 人工覆盖建议数量

系统计算：

```text
recommended_qty
```

用户还可以输入：

```text
manual_planned_qty
```

例如：

```text
系统建议：1200股

用户计划：
500股
```

系统必须根据人工数量重新计算：

- 实际投入金额；
- 实际资金仓位；
- 实际计划风险金额；
- 实际账户风险比例。

页面显示：

```text
系统建议数量：1200股

人工计划数量：500股

对应：
投入5,000元
资金仓位5%
计划风险250元
账户风险0.25%
```

---

# 34. 人工数量高于建议数量

例如：

```text
系统建议：
1000股

人工计划：
1500股
```

如果只是超过系统建议但没有触发硬限制：

显示 Warning：

```text
⚠ 人工计划数量高于系统建议 50%

系统建议计划风险：0.80%
当前人工计划风险：1.20%
```

如果违反：

- 现金限制；
- 最大单股仓位；
- 最大总仓位；
- 绝对风险上限；

则不能进入 READY 状态。

但仍允许保存 Draft。

---

# 35. 当前价格提示

如果有：

```text
current_price
```

并且：

```text
current_price >
max_acceptable_entry_price
```

显示：

```text
⚠ 当前价格已经高于本交易计划的最高可接受入场价。

当前：10.50
最高接受：10.30

当前计划不适合直接进入执行。
建议重新检查计划。
```

这属于 Warning / 当前不可执行提示。

TradePlan 本身仍可以保留。

---

# 36. 最高可接受价格情景

V0.1 应额外计算一个非常实用的结果：

> 如果最终是在最高接受价格成交，仓位应该是多少？

例如：

```text
参考入场：
10.00

最高接受：
10.30

风险参考：
9.50
```

系统重新使用：

```text
entry = 10.30
```

计算：

```text
unit_risk
qty_by_risk
recommended_qty
planned_risk
```

页面显示：

```text
参考价格10.00：
建议1200股

如果价格达到10.30：
建议800股
```

这样用户可以非常直观地看到：

> 买得越贵，同样风险预算下可以买的数量越少。

---

# 37. 页面右侧「交易计划卡」

右侧应始终显示一张核心摘要卡。

示例：

```text
XX股份
新建仓位

计划状态
🟢 可确认

参考入场             ¥10.00
最高接受             ¥10.30
风险参考              ¥9.50

价格风险               5.00%

风险预算：
¥800 / 0.80%

系统建议：
1200股

人工计划：
1000股

预计投入：
¥10,000

资金仓位：
10.00%

计划风险：
¥500 / 0.50%

1R                    ¥10.50
2R                    ¥11.00
3R                    ¥11.50

目标                  ¥12.00
收益风险比              4.0R

仓位主要限制：
单股最大仓位
```

这张卡应该是用户最常看的部分。

---

# 38. Validation 体系

分为：

```text
blocking_errors
warnings
```

---

# 39. Blocking Errors

存在 Blocking Error 时：

- 可以保存 Draft；
- 不允许确认 READY。

至少包括：

### 非法价格关系

```text
reference_entry_price <= 0
```

```text
risk_reference_price >= reference_entry_price
```

```text
max_acceptable_entry_price <
reference_entry_price
```

固定目标存在时：

```text
target_price <= reference_entry_price
```

### 非法账户参数

```text
account_equity <= 0
```

```text
available_cash < 0
```

### 无法形成交易数量

```text
recommended_qty <= 0
```

### 人工计划违反硬限制

例如：

```text
manual_notional >
available_cash
```

或者超过绝对风险上限。

---

# 40. Warnings

Warning 不阻止用户确认。

例如：

### 当前价格已经超出最高接受价格

### 本次风险高于默认风险

### 收益风险比较低

例如未来设置默认：

```text
reward_risk_ratio < 1.5
```

只 Warning，不 Block。

### 风险参考位置距离较远

例如：

```text
price_risk_pct > 某提醒值
```

只提示：

```text
⚠ 风险参考位置距离计划入场价格较远，
因此系统建议资金仓位较低。
```

不要替用户判断：

> 这笔交易不能做。

---

# 41. TradePlan 状态

V0.1 使用：

```text
DRAFT
READY
CANCELLED
EXPIRED
```

### DRAFT

正在编辑。

### READY

用户确认计划。

表示：

> 这个 TradePlan 已经制定完成，可以以后交给虚拟盘或 ExecutionRule。

当前 V0.1 到 READY 即结束。

### CANCELLED

用户主动取消。

### EXPIRED

超过有效期。

后续增加 ExecutionRule 后再扩展：

```text
IN_EXECUTION
COMPLETED
```

---

# 42. 确认计划

点击：

```text
确认交易计划
```

前执行完整 Validation。

如果无 Blocking Error：

```text
status = READY
confirmed_at = now
```

同时保存：

```text
calculation_snapshot
```

---

# 43. Calculation Snapshot

必须保存计划确认时的计算结果。

例如：

```text
account_equity
available_cash
current_invested_amount

reference_entry_price
risk_reference_price

risk_budget_amount

qty_by_risk
qty_by_single_position
qty_by_cash
qty_by_total_position

recommended_qty
manual_planned_qty

planned_notional
planned_position_pct

planned_risk_amount
planned_account_risk_pct

reward_risk_ratio

limiting_factor
```

目的：

以后账户数据或行情变化时，不允许历史计划悄悄变化。

---

# 44. TradePlan 修改

V0.1：

DRAFT 可以自由修改。

READY 后如果修改核心字段：

建议：

```text
重新进入 DRAFT
```

并保留：

```text
previous_confirmed_snapshot
```

正式版本再实现完整 Revision History。

不要第一版就建设复杂版本系统。

---

# 45. 建议数据模型

可根据现有项目 ORM 调整。

核心实体：

```text
TradePlan
```

建议字段：

```text
id

symbol
security_name

action
status

reference_entry_price
max_acceptable_entry_price

risk_reference_price
risk_reference_note

plan_risk_pct

target_type
target_price

manual_planned_qty

thesis

expires_at

created_at
updated_at
confirmed_at
cancelled_at

calculation_snapshot_json

validation_snapshot_json
```

V0.1 可以将计算结果作为 JSON Snapshot 保存。

不必立刻拆成几十个数据库字段。

实时计算结果由：

```text
TradePlanCalculator
```

生成。

---

# 46. TradePlanCalculator

建议建立独立领域服务：

```text
TradePlanCalculator
```

输入：

```text
TradePlanInput
AccountRiskSettings
InstrumentInfo
```

输出：

```text
TradePlanCalculationResult
```

示意：

```text
TradePlanCalculationResult
 ├─ unit_risk
 ├─ price_risk_pct
 ├─ risk_budget_amount
 ├─ qty_by_risk
 ├─ qty_by_single_position
 ├─ qty_by_cash
 ├─ qty_by_total_position
 ├─ recommended_qty
 ├─ planned_qty
 ├─ planned_notional
 ├─ planned_position_pct
 ├─ planned_risk_amount
 ├─ planned_account_risk_pct
 ├─ r1_price
 ├─ r2_price
 ├─ r3_price
 ├─ reward_risk_ratio
 ├─ limiting_factor
 ├─ max_price_scenario
 ├─ warnings[]
 └─ blocking_errors[]
```

Calculator 必须尽量保持：

> Pure Function / 无副作用

方便写单元测试。

---

# 47. 推荐接口

如果当前项目为前后端分离，可使用类似：

```text
GET /api/trade-plans
POST /api/trade-plans

GET /api/trade-plans/{id}
PATCH /api/trade-plans/{id}

POST /api/trade-plans/calculate

POST /api/trade-plans/{id}/confirm
POST /api/trade-plans/{id}/cancel
```

如果不是前后端分离架构，不要求照搬 REST。

核心原则是：

> 计算逻辑只维护一份。

---

# 48. 风险参数配置

建议添加非常简单的：

```text
交易设置
```

第一版只包含：

```text
账户净资产
可用现金
当前已投入金额

默认单笔风险%
单股最大仓位%
最大总仓位%
```

暂时不做复杂设置中心。

以后虚拟账户实现后，前三个字段全部自动获得。

---

# 49. V0.1 明确不做

为了控制工程量，本阶段不要开发：

- 自动结构识别；
- 自动止损；
- 自动趋势判断；
- AI 买卖建议；
- 复杂 ATR 仓位；
- Kelly Formula；
- VaR；
- 股票相关系数；
- 行业组合风险；
- 多档自动止盈；
- 自动加仓；
- 实盘交易；
- QMT；
- 自动订单；
- 每日持续挂单；
- 复杂交易费用模型；
- 复杂版本历史。

这些都不是验证 TradePlan 产品价值的必要条件。

---

# 50. V0.1 验收场景

至少覆盖以下测试。

## Case 1：风险模型成为限制因素

```text
账户：100,000
现金：100,000
已投入：0

风险预算：0.8%
单股最大仓位：20%
总仓位上限：100%

入场：10
风险：9
```

风险预算：

```text
800
```

每股风险：

```text
1
```

结果：

```text
qty_by_risk = 800
```

最终建议数量应主要受风险预算限制。

---

## Case 2：单股仓位成为限制因素

```text
账户：100,000
风险预算：0.8%

入场：10
风险：9.9

单股最大仓位：10%
```

风险模型允许大量买入。

但最终建议投入不得超过约：

```text
10,000
```

限制因素：

```text
SINGLE_POSITION_LIMIT
```

---

## Case 3：现金不足

```text
可用现金：
5,000

入场：
10
```

最终建议不得超过现金能力。

---

## Case 4：总仓位限制

```text
账户：
100,000

最大总仓位：
80%

已经投入：
75,000
```

剩余新增投资能力仅约：

```text
5,000
```

---

## Case 5：人工降低仓位

```text
系统建议：
1000股

人工计划：
500股
```

重新计算：

```text
投入金额
资金仓位
计划风险金额
账户风险比例
```

---

## Case 6：人工提高仓位

系统显示明显 Warning。

如果违反硬限制，则不允许 READY。

---

## Case 7：目标为空

允许：

```text
TREND_FOLLOWING
```

收益风险比为空。

仍允许确认。

---

## Case 8：价格关系错误

```text
入场：10
风险参考：10.5
```

必须 Blocking Error。

---

## Case 9：当前价格超出最高接受价

计划仍保存。

但明显提示：

```text
当前不适合按原计划直接执行。
```

---

# 51. 第一阶段页面完成标准

开发完成后，用户应该能够：

1. 打开「交易 → 交易计划」；
2. 新建一只股票 TradePlan；
3. 输入参考入场价；
4. 输入最高接受价格；
5. 输入风险参考价；
6. 使用默认账户风险参数；
7. 可选择输入固定目标价；
8. 实时看到仓位计算；
9. 实时看到风险金额；
10. 实时看到资金仓位；
11. 实时看到 1R / 2R / 3R；
12. 看到哪个因素限制了仓位；
13. 修改人工计划股数；
14. 看到修改后的风险；
15. 保存 Draft；
16. 确认 READY；
17. 在 TradePlan 列表重新打开查看。

达到以上能力，即视为 TradePlan V0.1 完成。

---

# 52. TradePlan 后续正式版本规划

V0.1 实际使用后，再逐步增加。

## TradePlan V1

优先增加：

### 加仓计划

能够读取已有持仓并计算：

- 当前持仓数量；
- 当前持仓市值；
- 当前资金仓位；
- 新增仓位；
- 加仓后总仓位；
- 新增部分计划风险。

### 减仓 / 清仓计划

TradePlan 支持：

```text
REDUCE
CLOSE
```

主要记录退出意图。

---

## TradePlan V1.5

增加：

### 完整计划修改历史

例如：

```text
初始风险参考：9.50

修改：
9.80

修改：
10.50
```

但“持仓后的风险位置动态调整”最终主要进入 Position Management，不应无限扩张 TradePlan。

### 多目标价

支持：

```text
目标1
目标2
趋势持有
```

仍然以人工设置为主。

---

## TradePlan V2

和未来账户与持仓系统连接。

账户数据自动获得：

```text
equity
cash
positions
current_exposure
```

无需人工维护。

增加简单组合风险提示：

```text
当前总仓位
单股仓位
行业暴露
自定义分组暴露
账户整体计划风险
```

不做机构级：

- VaR；
- 协方差矩阵；
- 复杂资产模型。

---

## TradePlan V2.5

接入 ExecutionRule。

用户确认 TradePlan 后：

```text
READY
    ↓
创建执行任务
```

ExecutionRule 决定：

- 一次性下单；
- 分批执行；
- 限价等待；
- 每个交易日重新挂单；
- 部分成交后继续；
- 有效期；
- 手动暂停；
- 计划变化后暂停。

TradePlan 自身仍然不承担订单执行逻辑。

---

# 53. 正式版本长期原则

即使未来系统成熟，仍坚持：

## 人工判断股票

程序不自动决定：

> 买哪只股票。

## 人工判断核心风险位置

程序可以提供技术参考，但不自动宣布：

> 结构已经破坏。

## 系统负责计算

程序擅长：

- 风险；
- 仓位；
- 数量；
- 资金占用；
- 情景计算；
- 纪律检查。

## 系统负责机械执行

以后可以自动：

- 每日重新挂单；
- 处理部分成交；
- 计算剩余数量；
- 根据已经批准的规则继续执行。

## 不建设机构级交易平台

正式版仍服务于：

> 单个个人交易者。

优先考虑：

- 使用方便；
- 风险透明；
- 维护简单；
- 出错容易发现；
- 不增加没有实际价值的复杂度。

---

# 54. 后续开发顺序

TradePlan V0.1 完成并经过实际使用调整后，整个交易模块建议按照以下顺序推进：

```text
阶段1
TradePlan

↓

阶段2
Paper Account
虚拟账户

↓

阶段3
Paper Broker
虚拟订单 / 成交

↓

阶段4
ExecutionRule
持续挂单 / 分批执行

↓

阶段5
Position Management
持仓风险 / 人工动态调整

↓

阶段6
Live Confirm
人工确认实盘

↓

阶段7
Broker Adapter
QMT / iQuant

↓

阶段8
托管式机械执行
+
对账
+
异常保护
```

每完成一个阶段，都应先实际使用，再决定下一阶段具体细节。

不要一次性把整个交易系统全部开发完成。

---

# 55. 本阶段最重要的设计原则

TradePlan V0.1 的成功标准不是功能数量。

而是用户在实际选择一只股票后，可以很快回答：

> 我准备在哪里买？

> 我认为哪里代表这笔交易风险明显增加？

然后系统马上把剩下的问题算清楚：

> 应该买多少？

> 需要多少钱？

> 占多少仓位？

> 计划承担多少账户风险？

> 1R、2R、3R在哪里？

> 如果买贵一点还能买多少？

> 当前计划有没有明显问题？

如果这个页面真正变成用户愿意在每笔交易前使用的工具，TradePlan 的第一阶段就是成功的。