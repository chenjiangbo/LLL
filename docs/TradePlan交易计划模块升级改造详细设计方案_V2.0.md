# TradePlan 交易计划模块升级改造详细设计方案 V2.0

> 用途：指导 AI Coder 对现有「交易计划 / TradePlan」模块进行升级改造。
>
> 核心目标：将当前主要面向“首次开仓”的 TradePlan，升级为能够覆盖一笔股票交易完整生命周期的交易计划体系，包括：
>
> **OPEN 开仓 → ADD 加仓 → REDUCE 减仓 → CLOSE 清仓**
>
> 本方案只设计“交易计划与持仓计划”能力，不规定用户必须采用某一种具体交易策略。

---

# 1. 设计背景

当前 TradePlan 已经能够完成一笔首次买入计划的核心工作，例如：

- 参考入场价；
- 最高可接受买入价；
- 风险参考价；
- 单笔风险预算；
- 根据风险预算计算建议买入数量；
- 单股仓位、现金、总仓位等约束；
- 趋势跟踪 / 固定目标；
- 1R / 2R / 3R 等参考结果。

当前模型仍然隐含了一个前提：

> **TradePlan ≈ 第一次买入计划。**

实际股票交易并不是一次买入以后只等待卖出。

完整交易可能包含：

```text
第一次开仓
↓
第一次加仓
↓
第二次加仓
↓
部分减仓
↓
再次减仓
↓
最后清仓
```

而且：

- 用户可能第一次参与就在“二买”或突破位置，而不是底部；
- 加仓次数不应该由系统写死；
- 某次 ADD 的逻辑失败，不一定意味着整笔交易逻辑失败；
- 卖出可能采用趋势跟踪、固定目标、反弹退出、分批兑现、时间退出等不同方式；
- 已经盈利后仍存在利润回吐风险和仓位集中风险；
- 不同交易类型需要不同的退出管理方式。

因此必须升级领域模型。

---

# 2. 最重要的设计原则

## 2.1 系统能力与交易策略分离

TradePlan 模块不能规定：

```text
必须2R减仓
必须第一根阴线卖
必须用动态止损
必须趋势破坏才卖
必须加仓两次
```

这些属于：

> **Playbook / 具体交易策略规则**

而不是 TradePlan 平台能力。

TradePlan 应提供足够通用的能力，让不同 Playbook 使用。

---

## 2.2 TradePlan 是“一次交易动作的计划”

升级后：

```text
TradePlan != 整笔交易
```

TradePlan 定义：

> **我准备对当前 Trade 做一次什么动作。**

动作包括：

```text
OPEN
ADD
REDUCE
CLOSE
```

---

## 2.3 Trade 是“一笔完整交易生命周期”

新增顶层领域对象：

```text
Trade
```

它代表：

> 从第一次建仓开始，到最后一股清仓为止的一整笔交易。

例如：

```text
Trade #T001  某股票趋势交易

├─ Plan #1 OPEN
├─ Plan #2 ADD
├─ Plan #3 ADD
├─ Plan #4 REDUCE
├─ Plan #5 REDUCE
└─ Plan #6 CLOSE
```

所有计划、订单、成交、持仓变化最终都属于同一个 Trade。

---

# 3. 当前业务范围

本系统当前考虑：

```text
趋势交易
反弹 / 波段交易
固定目标型交易
自定义交易
```

暂不考虑：

```text
长期价值投资 / 长期基本面投资
```

注意：

> “交易类型”只是帮助选择默认计划和管理方式，不应限制系统底层能力。

---

# 4. Trade 类型

V2.0 初始枚举：

```text
TREND
REBOUND
FIXED_TARGET
CUSTOM
```

中文：

```text
趋势交易
反弹 / 波段
固定目标
自定义
```

---

## 4.1 TREND

核心特征：

- 不预先假设最终顶部；
- 可以多次加仓；
- 可以采用动态风险参考；
- 可以采用分批兑现；
- 剩余仓位可继续跟踪趋势。

---

## 4.2 REBOUND

核心特征：

- 明确认为只是一段阶段性反弹；
- 通常存在明显压力区或空间预期；
- 更强调时间效率；
- 可能采用目标区、时间退出和结构失败退出；
- 不应该在持有过程中自动“漂移”为长期趋势交易。

---

## 4.3 FIXED_TARGET

核心特征：

- 有明确目标价；
- 可以计算计划收益风险比；
- 到目标后按计划减仓或清仓。

---

## 4.4 CUSTOM

用于暂时无法归入标准类型的交易。

---

# 5. 新领域模型总览

```text
TradingAccount
     │
RiskProfile
     │
     ▼
Trade
│
├─ TradePlan (OPEN)
│    └─ ExecutionPlan → Order → Fill
│
├─ Position / TradePosition
│
├─ TradePlan (ADD)
│    └─ ExecutionPlan → Order → Fill
│
├─ TradePlan (REDUCE)
│    └─ ExecutionPlan → Order → Fill
│
├─ TradePlan (CLOSE)
│    └─ ExecutionPlan → Order → Fill
│
└─ TradeResult
```

---

# 6. Trade 对象设计

建议字段：

```text
id
account_id
symbol
symbol_name

trade_type
playbook_id
playbook_snapshot_json

status

thesis
initial_reason
notes

opened_at
closed_at

created_at
updated_at
```

---

## 6.1 Trade Status

```text
PLANNED
ACTIVE
CLOSING
CLOSED
CANCELLED
```

### PLANNED

已经创建 OPEN 计划，但尚未实际形成持仓。

### ACTIVE

至少有一笔 OPEN 成交，当前仍有持仓。

### CLOSING

已经创建全仓退出计划，但尚未完全成交。

### CLOSED

该 Trade 对应持仓已经归零。

### CANCELLED

OPEN 计划取消，Trade 从未真正形成持仓。

---

# 7. TradePlan Action Type

新增：

```text
action_type
```

枚举：

```text
OPEN
ADD
REDUCE
CLOSE
```

---

# 8. OPEN

含义：

> 这笔 Trade 第一次建立持仓。

一个 Trade 只允许一个真正执行成功的 OPEN。

如果 OPEN 尚未成交，可以修改/取消并重新建立计划。

---

# 9. ADD

含义：

> 在已有持仓基础上增加持仓。

规则：

- ADD 次数不写死；
- 一个 Trade 可以有 0～N 个 ADD；
- 每次 ADD 都是独立 TradePlan；
- 每次重新计算风险、仓位和现金约束；
- 必须记录本次加仓理由；
- 可以有独立的风险参考和失败处理方式。

---

# 10. REDUCE

含义：

> 部分降低当前持仓。

例如：

```text
卖30%
卖500股
降低到目标仓位20%
```

REDUCE 后 Trade 仍为 ACTIVE。

---

# 11. CLOSE

含义：

> 计划结束整个 Trade。

目标是：

```text
position quantity → 0
```

但要考虑 A 股 T+1：

如果：

```text
总持仓1000
当前可卖800
```

则 CLOSE 计划仍可以表示：

```text
目标：全部清仓
```

但当前只能执行：

```text
800
```

剩余200股待下一个交易日继续执行。

因此：

> CLOSE 是业务目标，不等于一次订单一定卖完所有股票。

---

# 12. TradePlan 通用字段

建议升级为：

```text
id
trade_id
account_id
symbol

action_type
sequence_no

status

reason_code
reason_text

reference_price
max_acceptable_price
min_acceptable_price

planned_quantity
recommended_quantity

risk_reference_price
risk_reference_note

risk_budget_pct
risk_budget_amount

target_type
target_price

trigger_config_json
exit_config_json

valid_from
expires_at

notes

created_at
updated_at
```

不同 action 使用不同字段组合。

---

# 13. TradePlan Status

建议：

```text
DRAFT
READY
ARMED
PARTIALLY_EXECUTED
EXECUTED
CANCELLED
EXPIRED
INVALIDATED
```

---

## DRAFT

计划正在编辑。

## READY

计划已经完整，可以提交给执行模块。

## ARMED

对应 ExecutionPlan 已启用，等待执行条件。

## PARTIALLY_EXECUTED

计划数量部分成交。

## EXECUTED

该 TradePlan 计划数量已经完成。

## CANCELLED

用户主动取消。

## EXPIRED

超过计划有效期。

## INVALIDATED

交易理由已失效，计划不应再执行。

---

# 14. TradePlan 与 ExecutionPlan 必须继续分离

TradePlan 回答：

```text
为什么交易？
买/卖多少？
最多接受什么价格？
承担多少风险？
什么情况下这个计划失效？
```

ExecutionPlan 回答：

```text
具体怎么成交？
限价？
到价触发？
持续挂单？
撤单重挂？
TWAP？
```

不要把：

```text
TWAP
订单状态
broker order id
```

塞进 TradePlan。

---

# 15. OPEN 计划设计

现有 TradePlan 基本可以保留。

用户填写：

```text
交易类型
交易理由
参考入场价
最高可接受买入价
风险参考价
计划风险预算
目标/退出类型
计划有效期
```

系统计算：

```text
每股风险
价格风险%
风险预算金额

风险预算允许数量
单股仓位允许数量
现金允许数量
总仓位允许数量

最终建议数量
预计投入金额
资金仓位%
计划风险金额
账户计划风险%
```

---

# 16. OPEN 计划结果区域必须显示

建议明确：

```text
系统建议数量
最终计划数量

预计投入
本次资金仓位

参考入场价
风险参考价
价格风险

风险预算

若按风险参考价退出：
计划亏损金额
账户计划风险
```

不要使用“最大亏损”。

显示说明：

> 实际亏损可能因跳空、跌停、滑点等高于计划风险。

---

# 17. ADD 计划的业务核心

ADD 不是简单复制 OPEN。

创建 ADD 时必须读取：

```text
当前 Trade
当前实际持仓
当前可用资金
当前平均成本
当前市场价格
现有所有 OPEN / ADD leg
当前持仓管理风险参考
账户风险配置
```

---

# 18. ADD 必填信息

```text
加仓理由
参考加仓价
最高可接受加仓价
本次加仓风险参考价
本次风险预算
本次加仓失败处理
计划有效期
```

可选：

```text
加仓后整体持仓风险参考价
```

---

# 19. ADD 加仓失败处理

不能假设：

> ADD失败 = 只卖新增仓

也不能假设：

> ADD失败 = 全部清仓

必须让用户/Playbook定义。

枚举：

```text
EXIT_ADDED_QTY_ONLY
REDUCE_TO_TARGET_QTY
REDUCE_TO_TARGET_PCT
CLOSE_ALL
MANUAL_DECISION
```

中文：

```text
仅撤本次新增仓
减仓到指定数量
减仓到指定比例
全部退出
人工重新判断
```

---

# 20. “本次新增仓”在系统中的含义

券商账户里的股票是同一证券的聚合持仓。

真实卖出时，并不存在交易所层面的：

> “我要卖掉第二次加仓的那100股。”

因此系统中的：

```text
OPEN leg
ADD leg
```

属于：

> **内部策略归因和风险管理层。**

实际卖出时只是：

```text
SELL 100
```

系统再按照内部归因规则把这100股归入某个 leg。

---

# 21. PositionLeg / TradeLeg

为支持加仓管理，建议增加内部对象：

```text
TradeLeg
```

字段：

```text
id
trade_id
source_plan_id

leg_type
sequence_no

entry_qty
remaining_qty

planned_entry_price
actual_avg_entry_price

initial_risk_reference_price
current_risk_reference_price

failure_handling

opened_at
closed_at
```

leg_type：

```text
OPEN
ADD
```

---

# 22. TradeLeg 的目的

它不是模拟券商真实“独立仓位”。

它主要用于：

- 分析每次 OPEN / ADD 的效果；
- 计算每个加仓动作自身风险；
- 判断 ADD 失败时理论上需要撤多少；
- Playbook 后续统计：
  - 第1次加仓；
  - 第2次加仓；
  - 第3次加仓；
- 复盘不同加仓行为的期望值。

---

# 23. 减仓时 Leg 的内部归因

V2.0 建议支持：

```text
NEWEST_FIRST
OLDEST_FIRST
PROPORTIONAL
MANUAL
```

默认建议：

```text
NEWEST_FIRST
```

只是内部统计归因。

不影响券商实际成本计算方式。

---

# 24. ADD 的风险预算逻辑

一个 Trade 应有：

```text
trade_risk_budget_pct
trade_risk_budget_amount
```

表示：

> 整笔 Trade 正常情况下允许承担的计划本金风险预算。

例如：

```text
账户净资产 = 100000
Trade最大风险预算 = 1%

trade_risk_budget_amount = 1000
```

---

# 25. 每次动作风险预算

OPEN / ADD 可以分别配置：

```text
action_risk_budget_pct
action_risk_budget_amount
```

例如：

```text
OPEN：0.3%
ADD #1：0.4%
ADD #2：0.3%
```

这只是示例。

系统不能写死比例。

---

# 26. 新增仓自身风险

对于做多：

```text
unit_add_risk =
add_entry_price - add_risk_reference_price
```

如果：

```text
unit_add_risk <= 0
```

说明风险参考位不低于计划买入价。

系统不能简单返回负风险。

应显示：

```text
新增仓计划本金风险：0
```

同时仍计算：

```text
当前价格到风险参考的利润回吐
```

---

# 27. 本次加仓风险金额

```text
incremental_risk_amount =
max(0, add_entry_price - add_risk_reference_price)
× add_qty
```

---

# 28. 剩余风险预算

最基础模型：

```text
remaining_trade_risk_budget =
trade_risk_budget_amount
-
current_trade_capital_risk
```

注意：

> current_trade_capital_risk 必须按“当前有效风险参考”重新计算，而不是永远按最初风险参考。

---

# 29. 当前 Trade 本金风险

对于每个仍持有的 leg：

```text
leg_exit_pnl =
(current_risk_reference_price - actual_avg_entry_price)
× remaining_qty
```

整个 Trade：

```text
planned_exit_pnl =
Σ leg_exit_pnl
```

然后：

```text
current_trade_capital_risk =
max(0, -planned_exit_pnl)
```

如果：

```text
planned_exit_pnl > 0
```

表示：

> 按当前风险参考退出，整笔 Trade 仍然计划盈利。

此时：

```text
current_trade_capital_risk = 0
```

但不代表“没有风险”。

还需要看利润回吐风险。

---

# 30. 当前利润回吐风险 Giveback Risk

对于做多：

```text
leg_giveback =
max(0, current_market_price - current_risk_reference_price)
× remaining_qty
```

整个 Trade：

```text
giveback_risk =
Σ leg_giveback
```

例如：

```text
当前浮盈 +5000
若达到风险参考后只剩 +2500
```

则：

```text
giveback_risk ≈ 2500
```

---

# 31. 为什么要同时展示两种风险

已经盈利以后：

```text
本金风险可能 = 0
```

但：

```text
利润回吐风险可能很大
```

因此 ADD 页面必须至少显示：

```text
当前本金计划风险
当前利润回吐风险
```

避免：

> 因为风险参考已经高于成本，就误认为可以无限加仓。

---

# 32. ADD 最大建议数量

本次 ADD 的数量首先由新增风险预算决定：

```text
qty_by_action_risk =
action_risk_budget_amount
/
unit_add_risk
```

如果没有单独 action risk：

```text
qty_by_trade_risk =
remaining_trade_risk_budget
/
unit_add_risk
```

同时继续受：

```text
qty_by_single_position_limit
qty_by_total_exposure
qty_by_cash
qty_by_manual_cap
```

最终：

```text
recommended_add_qty =
floor_to_lot(
  min(
    qty_by_risk,
    qty_by_single_position_limit,
    qty_by_total_exposure,
    qty_by_cash,
    qty_by_manual_cap
  )
)
```

---

# 33. ADD 不限制次数，但有限制条件

系统不设置：

```text
MAX_ADD_COUNT = 2
```

每次 ADD 都必须重新通过：

```text
风险预算
仓位上限
现金
总暴露
计划价格
Playbook限制（如配置）
```

如果未来 Playbook 根据统计得出：

```text
最多只允许2次ADD
```

则属于 Playbook 规则。

TradePlan 底层仍支持 N 次。

---

# 34. ADD 页面计算结果

建议显示：

```text
当前持仓         500股
当前平均成本      ¥10.00
当前市价          ¥12.00

本次参考加仓价     ¥12.00
本次风险参考价     ¥11.40
每股新增风险       ¥0.60

本次风险预算       ¥400
风险允许           666股
仓位上限允许       900股
现金允许          3000股

系统建议           600股

──────── 加仓后 ────────

预计总持仓        1100股
预计平均成本       ¥11.09
预计资金仓位       XX%

新增仓计划风险      ¥360
整笔Trade本金风险   ¥0 / ¥XXX
利润回吐风险        ¥XXX

风险预算使用        XX%
```

---

# 35. 加仓后整体风险参考

ADD 后存在两种管理方式：

## A. 每个 Leg 保留自己的风险参考

例如：

```text
OPEN：
risk_ref = 9.40

ADD：
risk_ref = 11.40
```

发生不同条件时分别退出。

---

## B. 将整个 Trade 提高到新的整体风险参考

例如：

```text
所有剩余仓位 current risk ref = 11.40
```

---

## C. 混合

例如：

```text
ADD失败 → 先撤ADD
OPEN继续按更大级别结构持有
```

系统必须支持。

不能强迫只使用一个总止损价。

---

# 36. Position Management / 持仓管理状态

Trade ACTIVE 后，应存在一份动态的持仓管理状态。

不是新的独立一级功能页面也可以。

建议对象：

```text
TradePositionState
```

字段：

```text
trade_id

position_qty
available_qty
avg_cost
market_price
market_value

current_capital_risk
current_giveback_risk

position_risk_reference_price
position_risk_reference_note

management_state
updated_at
```

---

# 37. 风险参考历史

无论用户如何调整动态风险参考，都必须保存历史：

```text
PositionRiskHistory
```

字段：

```text
trade_id
leg_id nullable

old_price
new_price

reason
changed_at
```

不能覆盖后丢失。

---

# 38. 动态风险参考

TradePlan 模块必须支持动态风险参考，但不能强迫用户使用。

更新方式：

```text
MANUAL
RULE_BASED
```

V2.0 第一阶段建议先完整实现：

```text
MANUAL
```

即：

> 用户根据结构判断主动提高/降低风险参考。

`RULE_BASED` 预留接口。

---

# 39. 未来 Rule-Based 动态风险参考

可扩展：

```text
PREVIOUS_SWING_LOW
MOVING_AVERAGE
ATR_TRAILING
PERCENT_TRAILING
CUSTOM
```

但是：

> 不在 V2.0 第一阶段强制开发自动结构识别。

---

# 40. REDUCE 计划

创建 REDUCE 时必须读取当前持仓。

用户可定义减仓数量方式：

```text
FIXED_QTY
POSITION_PCT
TARGET_REMAINING_QTY
TARGET_REMAINING_PCT
```

例如：

```text
卖500股
卖30%
剩1000股
降到20%仓位
```

---

# 41. REDUCE 的计划理由

系统提供通用原因码，但允许自定义：

```text
PROFIT_TAKING
FAILED_ADD
TREND_WEAKENING
TARGET_REACHED
TIME_EXIT
RISK_REDUCTION
POSITION_CONCENTRATION
CUSTOM
```

中文：

```text
主动兑现利润
加仓失败
趋势转弱
达到目标
时间退出
主动降低风险
仓位过度集中
其他
```

注意：

> 原因码只用于记录和统计，不代表系统自动判断市场状态。

---

# 42. REDUCE 后系统需要计算

```text
预计卖出数量
预计卖出金额

减仓前持仓
减仓后持仓

减仓前资金仓位
减仓后资金仓位

预计实现盈亏
剩余浮动盈亏

减仓前本金风险
减仓后本金风险

减仓前利润回吐风险
减仓后利润回吐风险
```

---

# 43. REDUCE 后必须处理剩余仓位

用户必须明确或确认：

```text
剩余仓位风险参考是否变化？
```

选择：

```text
KEEP_EXISTING
SET_NEW_REFERENCE
MANUAL_LATER
```

避免：

> 卖了一部分，却不知道剩下的仓位怎么管理。

---

# 44. CLOSE 计划

CLOSE 表示：

> 结束整笔 Trade。

可以由：

- 风险逻辑失效；
- 趋势结束；
- 固定目标；
- 时间退出；
- 用户主动决定；
- 其他 Playbook 规则；

触发。

---

# 45. CLOSE 页面必须显示

```text
当前总持仓
当前可卖数量

预计清仓金额
预计实现盈亏

如果受T+1限制：
当前可执行数量
待下一交易日数量
```

---

# 46. CLOSE 与 T+1

如果：

```text
position_qty = 1000
available_qty = 800
```

用户点击：

```text
全部清仓
```

TradePlan：

```text
planned_quantity = 1000
target_remaining_qty = 0
```

ExecutionPlan 当前只能：

```text
SELL 800
```

之后 Trade 状态：

```text
CLOSING
```

第二天剩余200可卖后继续。

直到：

```text
position_qty = 0
```

才：

```text
Trade.status = CLOSED
```

---

# 47. 卖出框架不能写死

TradePlan 必须支持多种退出模型。

建议新增：

```text
exit_style
```

枚举：

```text
MANUAL
FIXED_TARGET
TRAILING
TIME_BASED
SCALE_OUT
STRUCTURE_INVALIDATION
HYBRID
CUSTOM
```

---

# 48. MANUAL

用户人工决定减仓/清仓。

系统记录理由和数量。

---

# 49. FIXED_TARGET

例如：

```text
target_price = 15.00
```

可以：

```text
达到目标 → REDUCE
达到目标 → CLOSE
```

---

# 50. TRAILING

风险参考随行情变化。

可以是：

```text
人工调整
未来规则自动调整
```

系统不能规定 trailing 的具体算法。

---

# 51. TIME_BASED

例如反弹交易：

```text
计划持有最多10个交易日
```

达到时间条件：

```text
提示 REDUCE / CLOSE
```

具体动作由 Playbook 配置。

---

# 52. SCALE_OUT

分批兑现。

例如：

```text
阶段1 → REDUCE 30%
阶段2 → REDUCE 30%
剩余 → TRAILING
```

比例不能写死。

---

# 53. STRUCTURE_INVALIDATION

表示：

> 用户认为某个价格/结构出现后原逻辑失效。

V2.0 可以由用户人工维护：

```text
risk_reference_price
reason
```

不要开发 AI 自动判定“结构破坏”。

---

# 54. HYBRID

允许组合：

```text
固定目标 + 趋势跟踪
时间退出 + 风险参考
分批兑现 + 剩余Trailing
```

---

# 55. ExitRule 通用模型

为了不把卖出策略写死，建议内部增加：

```text
ExitRule
```

字段：

```text
id
trade_id
source_plan_id nullable

rule_type
priority
enabled

trigger_type
trigger_config_json

action_type
action_config_json

execution_behavior

notes
created_at
updated_at
```

---

# 56. TriggerType

V2.0 支持：

```text
MANUAL_CONFIRMATION
PRICE_ABOVE
PRICE_BELOW
PRICE_RANGE
R_MULTIPLE
DATE_TIME
HOLDING_DAYS
CUSTOM
```

---

# 57. ExitRule Action

```text
REDUCE_FIXED_QTY
REDUCE_POSITION_PCT
REDUCE_TO_TARGET_PCT
CLOSE_ALL
UPDATE_RISK_REFERENCE
ALERT_ONLY
```

---

# 58. Execution Behavior

TradePlan 只描述业务动作是否成立。

真正自动下单仍属于 ExecutionPlan。

这里记录：

```text
ALERT_ONLY
REQUIRE_CONFIRMATION
```

V2.0 不要求：

```text
AUTO_EXECUTE
```

实盘初期仍以人工确认后发送为主。

---

# 59. 为什么 ExitRule 很重要

这样系统可以支持完全不同的 Playbook。

例如：

## 趋势型

```text
价格跌破动态风险参考
→ CLOSE
```

## 反弹型

```text
到达压力区
→ REDUCE 50%

持有超过10天仍未达到预期
→ CLOSE
```

## 固定目标型

```text
达到2.5R
→ CLOSE
```

TradePlan 平台无需修改。

---

# 60. 反弹交易专项

REBOUND 类型创建 OPEN 时应额外突出：

```text
预期交易周期
第一空间参考
目标区
时间失效条件
风险参考
```

但这些不是所有 Trade 必填。

---

# 61. 趋势交易专项

TREND 类型重点突出：

```text
初始风险参考
是否允许加仓
当前整体风险参考
动态风险管理方式
第一空间参考
```

固定目标不必强制填写。

---

# 62. 固定目标专项

FIXED_TARGET：

必须能计算：

```text
reward =
target_price - entry_price

risk =
entry_price - risk_reference_price

reward_risk_ratio =
reward / risk
```

如果没有合理目标价：

不允许伪造固定盈亏比。

---

# 63. “第一空间参考”继续保留

对于 TREND / REBOUND 可以填写：

```text
space_reference_price
```

它表示：

> 当前可见的重要压力 / 第一空间边界。

它不是自动止盈价。

系统计算：

```text
space_R =
(space_reference_price - reference_entry_price)
/
(reference_entry_price - risk_reference_price)
```

用于辅助判断：

> 当前入场是否距离明显压力太近。

---

# 64. 当前 Trade 风险面板

Trade 详情页必须持续显示：

```text
当前持仓
平均成本
当前价格
资金仓位

已实现盈亏
浮动盈亏

当前本金计划风险
当前利润回吐风险

Trade风险预算
已使用/剩余风险预算

当前整体风险参考
```

---

# 65. 风险术语统一

## 计划本金风险

如果按当前风险参考退出：

> 相对历史实际买入成本可能损失多少本金。

## 利润回吐风险

如果从当前价格跌到计划退出位置：

> 当前浮盈会回吐多少。

## 资金仓位

```text
market_value / account_equity
```

## 风险预算

用户允许该 Trade 承担的账户净值损失预算。

---

# 66. 不使用“最大亏损”

所有 UI 使用：

```text
计划风险
计划亏损
风险参考
```

并提示：

> 跳空、跌停、流动性和滑点可能导致实际损失超过计划值。

---

# 67. Trade 列表页

现有“交易计划”页面建议升级为：

```text
交易计划
```

支持两个视图：

```text
按 Trade 查看
按 Action Plan 查看
```

默认：

```text
按 Trade
```

---

# 68. Trade 列表展示

例如：

| 标的 | 类型 | 状态 | 持仓 | 当前风险 | 最近动作 |
|---|---|---|---:|---:|---|
| XXX | 趋势 | ACTIVE | 1100股 | 0.42% | ADD #2 |
| YYY | 反弹 | ACTIVE | 500股 | 0.31% | OPEN |
| ZZZ | 固定目标 | CLOSED | 0 | - | CLOSE |

点击进入 Trade Detail。

---

# 69. Trade Detail 页面

顶部：

```text
股票
Trade类型
Playbook
Trade状态

当前持仓
当前市值
平均成本
当前盈亏
```

中间：

```text
风险面板
```

下方：

```text
交易时间线
```

---

# 70. 交易时间线

例如：

```text
09-01 OPEN
500股 @10.00

09-05 ADD #1
600股 @10.80

09-12 ADD #2
400股 @11.50

09-20 REDUCE
卖400股

10-02 CLOSE
卖剩余1100股
```

每一个节点可以查看：

```text
计划
订单
成交
当时风险
理由
```

---

# 71. Trade Detail 操作按钮

ACTIVE 时：

```text
[创建加仓计划]
[创建减仓计划]
[创建清仓计划]
[调整风险参考]
```

PLANNED 时：

```text
[编辑OPEN计划]
[取消Trade]
```

CLOSED 时：

```text
[查看交易结果]
```

---

# 72. 创建 ADD 页面

布局建议：

## 当前持仓

```text
当前数量
平均成本
当前价
资金仓位
浮盈亏
当前风险
```

## 本次加仓

```text
加仓理由
参考加仓价
最高可接受价
本次风险参考
本次风险预算
失败处理
```

## 系统计算

显示第34节全部结果。

---

# 73. 创建 REDUCE 页面

显示：

```text
当前持仓
可卖数量
当前盈亏
当前利润回吐风险
```

填写：

```text
减仓原因
减仓方式
数量/比例
参考卖出价
最低可接受卖出价（如需要）
触发条件
```

计算：

```text
减仓后持仓
减仓后资金仓位
预计实现盈亏
减仓后风险
```

---

# 74. 创建 CLOSE 页面

显示：

```text
当前持仓
当前可卖
预计实现盈亏
```

填写：

```text
清仓原因
参考卖出价
最低接受卖价（可选）
触发条件
```

如果 T+1：

明确显示：

```text
当前只能卖800股
剩余200股将在可卖后继续完成CLOSE
```

---

# 75. 修改风险参考

独立操作：

```text
[调整风险参考]
```

用户选择：

```text
整个Trade
某个TradeLeg
```

填写：

```text
新风险参考价
调整理由
```

展示：

```text
调整前计划本金风险
调整后计划本金风险

调整前利润回吐风险
调整后利润回吐风险
```

确认后保存历史。

---

# 76. 价格方向验证

对于做多：

```text
OPEN/ADD风险参考
通常应低于参考买入价
```

如果异常：

```text
risk_reference >= entry
```

允许保存，但提示：

> 当前风险参考已经高于计划成本，新增仓本金风险按0计算，请确认该设置是否符合实际管理意图。

不要直接阻止。

---

# 77. 手工覆盖系统建议数量

继续支持：

```text
manual_planned_quantity
```

如果：

```text
manual <= recommended
```

正常。

如果：

```text
manual > recommended
```

重新计算全部风险。

如果突破硬限制：

```text
BLOCK
```

如果只是超过标准风险预算但未超过硬上限：

```text
WARNING + 二次确认
```

---

# 78. 风险配置来源

TradePlan 不重复维护账户风险规则。

继续从：

```text
TradingAccount
RiskProfile
```

读取：

```text
标准单笔风险预算
单笔风险硬上限
单股仓位上限
总仓位上限
```

Trade 增加：

```text
trade_risk_budget
```

但不得超过账户硬限制。

---

# 79. Trade 风险预算与 Action 风险预算

关系：

```text
RiskProfile
    ↓
Trade Risk Budget
    ↓
OPEN / ADD Action Budget
```

例如：

```text
账户硬上限：1.2%
Trade计划预算：1.0%

OPEN：0.3%
ADD1：0.4%
ADD2：0.3%
```

只是可配置示例。

---

# 80. 不强制风险预算必须一次用满

系统允许：

```text
Trade预算1%
实际只使用0.6%
```

剩余：

```text
0.4%
```

可以：

- 后续 ADD 使用；
- 永远不用；
- 随计划结束作废。

---

# 81. 组合层风险

V2.0 TradePlan 继续检查：

```text
单股最大仓位
账户总仓位
可用现金
```

未来可以增加：

```text
账户总计划风险
行业集中
相关性
```

但不在本次升级强制实现复杂组合模型。

---

# 82. 账户总计划风险

如现有持仓均有风险参考，可以计算：

```text
account_planned_risk =
Σ 各Trade current_capital_risk
```

显示：

```text
账户当前总计划风险
```

V2.0 建议实现为只读指标。

是否作为硬限制：

> 暂不写死，由 RiskProfile 后续配置。

---

# 83. Playbook 集成

Trade 创建时支持：

```text
playbook_id
playbook_snapshot_json
```

TradePlan Action 额外记录：

```text
reason_code
sequence_no
```

方便后续统计：

```text
OPEN表现
ADD #1表现
ADD #2表现
REDUCE效果
退出规则效果
```

---

# 84. 策略规则不要硬编码进 TradePlan

例如：

```text
第1次阴线不卖
2R减30%
第三次ADD禁止
横盘20天退出
```

这些应来自：

```text
Playbook
```

或用户当前 Trade 的自定义设置。

TradePlan 只负责执行和记录这些规则。

---

# 85. 正期望闭环

未来 Playbook 可以统计：

```text
不同OPEN类型
不同ADD次数
不同REDUCE规则
不同CLOSE规则

对应：
胜率
平均R
期望R
持仓时间
最大回撤
利润回吐
```

然后用户根据真实样本优化规则。

TradePlan 不负责宣布：

> 某策略一定有效。

---

# 86. 数据库建议

新增：

```text
trades
trade_plans
trade_legs
trade_position_state
position_risk_history
exit_rules
```

保留已有：

```text
execution_plans
orders
fills
positions
```

如现有表名称不同，由 AI Coder 按项目实际情况映射。

---

# 87. TradePlan 表升级重点

至少增加：

```text
trade_id
action_type
sequence_no

reason_code
reason_text

action_risk_budget_pct
action_risk_budget_amount

risk_reference_price
failure_handling

target_remaining_qty
target_remaining_pct

trigger_config_json
exit_config_json
```

---

# 88. 迁移现有 TradePlan

历史已有 TradePlan 默认迁移为：

```text
action_type = OPEN
sequence_no = 1
```

为每个旧 TradePlan 创建对应：

```text
Trade
```

如果旧计划从未成交：

```text
Trade.status = PLANNED
```

如果已有持仓关联：

```text
Trade.status = ACTIVE
```

不能破坏现有测试数据。

---

# 89. 旧页面兼容

现有创建 TradePlan 页面不要推翻重写。

第一阶段改造成：

```text
创建新Trade
→ 创建OPEN TradePlan
```

大部分已有字段继续复用。

---

# 90. 开发分阶段

## Phase 1：领域模型升级

实现：

```text
Trade
TradePlan action_type
TradeLeg
Trade Detail
OPEN迁移
```

暂不开发复杂 ExitRule。

## Phase 2：ADD

实现：

```text
ADD计划
ADD风险计算
TradeLeg
新增仓失败处理
加仓后风险面板
```

## Phase 3：REDUCE / CLOSE

实现：

```text
REDUCE计划
CLOSE计划
T+1可卖约束
减仓后风险计算
```

## Phase 4：Position Management

实现：

```text
动态风险参考
风险历史
本金风险
利润回吐风险
账户总计划风险
```

## Phase 5：ExitRule 通用规则

实现：

```text
Manual
Price
R Multiple
Holding Days
Fixed Target
Scale Out
Hybrid
```

以“计划与提醒”为主。

不要直接自动实盘下单。

---

# 91. 第一阶段明确不做

不要在本次 TradePlan 升级中过度开发：

```text
AI自动识别二买
AI自动识别趋势结束
AI自动移动结构止损
机器学习卖点
参数寻优
复杂组合VaR
自动实盘卖出
机构级OMS
微服务拆分
```

---

# 92. 关键验收场景 1：二买直接 OPEN

用户没有底仓。

```text
Trade Type = TREND
OPEN reason = 二买

entry = 10
risk_ref = 9.4
risk budget = 0.8%
```

系统正常计算建议数量。

证明：

> OPEN 不依赖“底部准备”。

---

# 93. 关键验收场景 2：底仓后 ADD

```text
OPEN：
500股 @10

ADD：
600股 @10.8
risk_ref = 10.2
```

系统正确显示：

```text
本次新增风险
加仓后总持仓
加仓后平均成本
整笔Trade本金风险
利润回吐风险
```

---

# 94. 关键验收场景 3：ADD失败只撤新增仓

ADD 配置：

```text
failure_handling = EXIT_ADDED_QTY_ONLY
```

系统能生成：

```text
REDUCE
qty = 当前该ADD leg remaining qty
reason = FAILED_ADD
```

并继续保留 OPEN leg。

---

# 95. 关键验收场景 4：ADD失败关闭全部

另一 Trade：

```text
failure_handling = CLOSE_ALL
```

证明 TradePlan 不假设固定的加仓失败处理方式。

---

# 96. 关键验收场景 5：多次 ADD

同一 Trade：

```text
OPEN
ADD #1
ADD #2
ADD #3
```

底层无次数限制。

每次：

```text
sequence_no
risk
qty
reason
```

独立保存。

---

# 97. 关键验收场景 6：动态风险参考

OPEN 后：

```text
risk_ref：9.4 → 10.5 → 12.0
```

每次保存风险历史。

页面实时重算：

```text
本金风险
利润回吐风险
```

---

# 98. 关键验收场景 7：盈利后的 ADD

当前 Trade 已经：

```text
planned_exit_pnl > 0
```

系统显示：

```text
本金计划风险 = 0
利润回吐风险 > 0
```

新增 ADD 仍必须按自己的：

```text
entry - risk_ref
```

计算新增风险。

不能显示：

> “当前无风险，因此可以无限加仓。”

---

# 99. 关键验收场景 8：反弹交易

```text
trade_type = REBOUND
```

用户填写：

```text
目标区
预期持有期
时间失效
```

系统允许：

```text
达到目标 → REDUCE/CLOSE
时间到 → 提醒/退出
```

不强迫使用趋势 trailing。

---

# 100. 关键验收场景 9：固定目标

```text
trade_type = FIXED_TARGET
```

系统计算：

```text
固定目标
收益风险比
预计盈利
```

---

# 101. 关键验收场景 10：趋势交易无固定目标

```text
trade_type = TREND
target_price = null
```

页面：

```text
固定收益风险比：不适用
```

仍可以显示：

```text
1R / 2R / 3R
第一空间参考R
```

不能把3R当成目标价。

---

# 102. 关键验收场景 11：部分减仓

```text
当前1100股
REDUCE 30%
```

考虑 A 股交易单位和可卖数量后：

计算最终可执行数量。

减仓后：

```text
remaining qty
position pct
risk
giveback
```

正确。

---

# 103. 关键验收场景 12：T+1 CLOSE

```text
总持仓1000
可卖800
```

CLOSE：

```text
目标归零
当前卖800
剩余200待T+1
Trade = CLOSING
```

第二天卖完：

```text
Trade = CLOSED
```

---

# 104. UI 文案要求

避免暴露内部枚举：

```text
EXIT_ADDED_QTY_ONLY
POSITION_PCT
TREND
```

页面显示：

```text
仅退出本次新增仓
按持仓比例减仓
趋势交易
```

内部值仍使用英文枚举。

---

# 105. UI 数字要求

百分比：

```text
0.80%
12%
80%
```

不要显示：

```text
0.008
0.12
0.8
```

金额：

```text
¥1,000
```

数量：

```text
600股
```

---

# 106. 所有建议数量必须解释来源

例如 ADD：

```text
风险预算允许：666股
单股仓位允许：900股
现金允许：3200股
总仓位允许：1400股

系统建议：
600股

限制因素：
本次风险预算

666股 → 按交易单位向下调整 → 600股
```

---

# 107. 所有风险必须可解释

用户点击：

```text
为什么是¥360？
```

可以展开：

```text
参考加仓价：12.00
风险参考价：11.40
每股计划风险：0.60

600股 × 0.60
= ¥360
```

---

# 108. 设计成功标准

升级完成后，系统应能自然表达下面这一整笔股票交易：

```text
我在二买第一次建仓
↓
突破确认后加仓
↓
趋势中继再次加仓
↓
某次加仓失败，只撤新增仓
↓
后来重新转强又再次ADD
↓
进入主升后分批减仓
↓
剩余仓位继续动态风险跟踪
↓
最后趋势结束清仓
```

同时也能表达完全不同的交易：

```text
我只是做一段反弹
↓
到目标区减仓
↓
时间到了仍没有继续上涨
↓
全部退出
```

而不需要修改 TradePlan 底层模型。

---

# 109. 最终架构原则

TradePlan V2.0 的核心不是：

> 增加“加仓”和“卖出”两个按钮。

而是建立：

```text
Trade
      ↓
OPEN / ADD / REDUCE / CLOSE
      ↓
每个动作独立计划
      ↓
统一风险与仓位计算
      ↓
Position Management
      ↓
ExecutionPlan
      ↓
Order / Fill
```

交易方法由：

```text
Playbook
```

定义。

交易计划模块负责：

```text
表达
计算
约束
记录
执行前准备
```

而不是替用户决定：

> 哪一种交易方法才是唯一正确的专业方法。
