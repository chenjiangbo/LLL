# gm.api 已验证契约（方案 B）

> 状态：Phase 0 进行中  
> 最后更新：2026-09-02  
> 证据来源：broker_sdk_probe/reports/phase_b_trade_report.md、方案 B Probe 源码及 Windows 实机运行记录  
> 说明：没有原始实机输出的字段不标记为已验证。

## 1. 已确认运行环境

| 项目 | 已确认值 |
|---|---|
| 运行系统 | Windows 11 |
| Python | 3.9.13 |
| Python 路径 | C:\Program Files\Python39\python.exe |
| gm Python SDK | 3.0.186 |
| C SDK | 3.8.19 |
| 运行模式 | MODE_LIVE |
| 接入方式 | 国投掘金策略实例 + 已绑定仿真账户 |
| 账户模式 | SIM |

生产 Agent 必须沿用该环境，不安装 gmtrade，不升级或降级 gm。

## 2. 已确认启动方式

已验证的入口形态：

~~~python
from gm.api import *

run(
    strategy_id=<配置中的真实策略 ID>,
    filename=<策略文件名>,
    mode=MODE_LIVE,
    token=<配置中的 token>,
)
~~~

Windows 环境下策略文件名需要使用实际运行文件名，不能假设 Unix 路径可直接作为模块名。

## 3. 已确认账户链路

方案 B 已实机验证：

~~~text
context.account()              → 非空账户对象
context.account().status.state → 3
context.account().cash.nav     → 约 200000
context.account().cash.available → 约 200000
context.account().positions()  → 可返回持仓列表
~~~

完整对象 repr 已保存为脱敏 raw fixture，可用于生产 mapper 的字段核对。账户 ID、账户名和 token 已脱敏。

## 4. 已确认交易链路

已实机验证：

~~~python
order_volume(
    symbol="SZSE.000661",
    volume=100,
    side=OrderSide_Buy,
    order_type=OrderType_Limit,
    position_effect=PositionEffect_Open,
    price=<Decimal-compatible limit price>,
)
~~~

已确认：

- 仿真限价买入可以提交；
- 订单可以成交；
- 成交后可查询订单；
- 成交回报可以查询；
- 成交后持仓会变化；
- 成交后资金会变化；
- 有效限价单在当前仿真柜台可能立即成交。

真实账户、持仓、订单、未完成订单和成交 raw repr 已保存为脱敏 fixture，可用于 mapper 和去重测试。

## 5. 已确认的事实来源

生产系统只能把以下内容作为 Fill 来源：

- 真实 execution report callback；
- 完整券商成交查询；
- reconcile 查询得到的真实成交。

不能从订单意图、HTTP 202、账户金额变化或本地计算推导 Fill。

## 6. 已确认和未确认的回调

Probe 源码已经使用或声明以下回调：

- on_order_status；
- on_execution_report；
- on_error。

以下内容尚未取得可归档的完整 raw callback fixture：

- 每个回调的精确参数结构；
- 账户状态回调在 gm.api 3.0.186 下的稳定行为；
- 行情连接断开/恢复回调；
- 交易连接断开/恢复回调；
- callback 与 query 的完整重复去重样本。

在这些 fixture 完成前，mapper 和正式 callback 处理只能保持 UNVERIFIED。

## 7. 订单和成交标识

Probe 代码使用过：

- cl_ord_id；
- account_id；
- order 返回对象；
- execution report 返回对象。

以下字段尚未用完整 raw fixture 确认：

- 稳定 broker_order_id 的生产命名仍需确定；
- exchange_order_id（实机字段名为 ex_ord_id）；
- broker_execution_id（实机字段名为 exec_id）；
- 多次 callback/query 返回时的唯一键关系。

禁止用随机 UUID、时间戳或无法证明稳定的字段作为成交去重键。

## 8. 撤单状态

当前已知：

- 通过有效价格提交的仿真订单可能立即成交；
- 当前已完成测试没有形成可稳定撤销的未成交订单；
- 因此撤单最终状态仍未完成实机验证。

生产设计仍必须实现：

~~~text
CANCEL request sent
→ callback/query
→ CANCELLED / FILLED / other terminal state
~~~

“撤单函数调用返回”不能直接映射为 CANCELLED。

## 9. Execution Quote

以下字段和调用方式目前未完成可归档的完整 gm.api raw fixture：

- subscribe / unsubscribe 的确切签名；
- last；
- bid1、bid1_volume；
- ask1、ask1_volume；
- market time；
- quote revision；
- 行情断线与恢复；
- freshness 所需的时间字段。

这些项目必须在 Phase 0 后续 Probe 中完成；在完成前，不能声称 Execution Quote Service 已支持。

## 10. 当前未完成项

~~~text
已完成-01 账户对象完整 raw payload（账户 ID 脱敏）
已完成-02 cash 完整字段和类型
已完成-03 position 完整字段和类型
已完成-04 order 完整字段和状态枚举样本
已完成-05 execution report 完整字段和唯一成交 ID（exec_id）样本
UNVERIFIED-06 callback 精确参数结构
已完成-07 subscribe/unsubscribe 真实签名和 quote payload
UNVERIFIED-08 撤单回报和最终状态
UNVERIFIED-09 部分成交回报
UNVERIFIED-10 断线、重连和重启恢复
~~~

补充实测：`gm.api.current("SZSE.000661", fields="symbol,price,quotes")` 返回了真实 L1 行情，`subscribe(symbols="SZSE.000661", frequency="tick", count=1, format="col")` 在交易时段连续触发真实 `on_tick` 回调，已保存至 `broker_sdk_probe/tests/fixtures/gm_quotes/current_real.json` 和 `tick_real.json`。Tick 中 `quotes` 是五档对象列表，第一档提供 `bid_p/bid_v/ask_p/ask_v`；Tick 还提供 `created_at`、`receive_local_time`、`cum_volume` 和 `last_volume`。

## 11. Phase 0 门槛状态

当前：

~~~text
已通过：运行环境、账户状态、资金、完整账户 raw、完整持仓 raw、完整订单 raw、完整成交 raw、基础下单、基础成交查询
未通过：完整 raw fixtures、完整 gm mapper 契约、行情、撤单、部分成交、恢复
~~~

账户、资金、持仓、订单和成交的核心 mapper 可以进入 Phase 1 开发；行情、回调、撤单、部分成交和恢复仍保持 UNVERIFIED，并在对应阶段前补齐真实 fixture。它们不能被标记为已支持或 PASS。
