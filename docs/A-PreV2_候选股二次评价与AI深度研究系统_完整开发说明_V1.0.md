# A-PreV2 候选股二次评价与 AI 深度研究系统
## 完整开发说明 V1.0

> **文档性质：完整功能交付规格，不是 MVP、不是分阶段路线图。**  
> 本文中标记为 **MUST / 必须** 的功能均属于本版本验收范围。  
> AI Coder 不得自行删除、简化、延后、替换本文明确要求的功能。  
> 若外部权限、密钥或数据源未满足，系统必须将该能力标记为 `BLOCKED_BY_DEPENDENCY` 并明确展示缺失项；**不得静默跳过后仍显示“已完成”“正常”“分析成功”。**

---

# 0. 项目定位

现有 `A-PreV2` 已负责发现：

> **技术形态已经从弱势/整理状态向早期转强迁移的股票。**

A-PreV2 的技术分只回答：

> **“这只股票技术上准备好了吗？”**

它不负责回答：

- 当前资金为什么会选择这个行业/题材；
- 同一个行业里为什么会优先选择某几只股票；
- 公司本身是否存在明显基本面拖累或边际改善；
- 股票属于哪些市场概念，这些概念与公司实际业务是什么关系；
- 之前的一波行情里它是否已经表现出相对领先；
- 当前股票更像先锋、小票弹性、容量核心还是普通跟随；
- 结合历史资金复盘与当前市场故事，这只股票是否值得人工进一步研究。

本功能是 **A-PreV2 之后的二次评价层**。

设计原则：

```text
A-PreV2：
技术发现

↓

程序化二次评价：
整理客观事实、做可审计的量化比较和排名

↓

人工勾选：
用户决定哪些股票值得进入深度研究

↓

AI 深度分析：
结合历史资金复盘、概念标签、公司资料、量化事实和网络检索，
理解“当前市场故事里，这只股票处在什么位置”

↓

用户最终决定：
是否继续研究 / 是否制定交易计划
```

**禁止把本功能做成自动买卖系统。**

---

# 1. 最重要的设计原则

## 1.1 不再制造一个神秘“综合总分”

本功能 **MUST NOT** 默认生成类似：

```text
综合机会分：87.36
主题分：92
催化分：73
概念关联度：88
```

原因：

市场主题、消息解释、公司与主题的关系很多属于语义判断，强行转成 0~100 往往只是拍脑袋。

本系统必须区分：

### 可以客观计算的东西

例如：

- 行业内 20 日相对收益百分位；
- 行业上涨日超额收益；
- 行业下跌日抗跌程度；
- 成交额变化；
- 自由流通市值；
- 营收同比；
- 扣非利润同比；
- 业绩预告类型；
- A-PreV2 技术分。

这些可以量化、排序。

### 不应该伪装成精确数字的东西

例如：

- “CRO 是不是当前资金主线”；
- “公司 AI 医疗业务是不是市场真正交易的逻辑”；
- “这个概念是不是蹭热点”；
- “这家公司是不是该主题真正的核心受益者”。

这些交给 AI 输出 **结论 + 证据 + 不确定性**，不强制打 90/70 分。

---

## 1.2 A-PreV2 技术逻辑不得在本层重复实现

本系统读取：

```text
aprev2_score
aprev2_status
aprev2_signal_date
aprev2_turn_type
aprev2关键指标
```

但 **MUST NOT** 再复制一套均线、MA Knot、Retake 等技术评分。

原因：

- 避免技术因子重复计分；
- 避免两个模块对同一技术状态给出冲突结论；
- A-PreV2 负责技术；
- 本模块负责“技术之外的二次评价”。

---

## 1.3 “没有证据”不等于“负面证据”

例如早期行情刚开始时，可能还无法判断谁是行业龙头。

此时必须显示：

```text
RELATIVE_LEADERSHIP = INSUFFICIENT_EVIDENCE
```

不能因为缺少历史领先证据而给 0 分或过滤股票。

同理：

```text
未发现公开催化
```

不能自动解释为：

```text
公司没有催化 / 股票不会涨
```

---

## 1.4 排名和过滤必须区分

二次评价默认以 **排序、标签、人工研究优先级** 为主。

### 允许硬过滤的内容

仅限非常明确的基础风险，例如现有系统已经定义的：

- 非正常交易；
- ST / *ST / 退市风险；
- 核心数据不可用；
- 其他已有 L1 硬规则。

### 本模块以下内容默认不得作为硬过滤

- 基本面一般；
- 亏损；
- 没有业绩预增；
- 主题不强；
- 暂无龙头证据；
- 自由流通市值较大；
- 没有明显“主力净流入”；
- 上方存在压力；
- 同花顺概念标签少。

这些只能影响人工研究优先级或作为标签。

---

# 2. 完整功能组成

本功能必须同时实现以下 6 个部分：

```text
Q1  Company Evidence
    公司层面客观证据 / 基本面边际

Q2  Relative Leadership
    行业内部相对领先性

Q3  Supply Profile
    筹码与推动画像

M1  Concept Metadata
    同花顺概念 / 行业 / 主题标签底库

A1  AI Deep Research
    人工触发 AI 深度研究

H1  Historical Replay
    任意历史日期回放 + 严格防未来函数
```

这 6 部分均属于 V1.0 完整交付内容。

---

# 3. 页面入口与完整交互

建议页面名称：

```text
候选研究 > A-PreV2 二次评价
```

也可以嵌入现有 A-PreV2 页面，但必须完整呈现本文要求的能力。

## 3.1 顶部控制区

必须包含：

### 日期

```text
as_of_date
```

默认最新交易日。

必须可以选择任意历史交易日。

### 数据状态

展示：

```text
行情数据：READY / MISSING
财务数据：READY / MISSING
申万行业：READY / MISSING
同花顺概念：READY / PERMISSION_BLOCKED / STALE
历史资金复盘：READY / NONE
AI网络检索：READY / CONFIG_REQUIRED
```

不得隐藏数据依赖状态。

### 数据刷新

提供：

```text
刷新当日二次评价
同步同花顺概念
刷新财务数据
重新计算 Relative Leadership
```

### AI 批量入口

用户勾选股票后：

```text
AI 深度分析
```

允许：

```text
单只
多只（建议最多 20 只/次）
```

---

# 4. 主结果表

A-PreV2 在指定 `as_of_date` 被选出的股票进入二次评价表。

至少包含以下列。

## 4.1 基础信息

```text
ts_code
name
as_of_date
申万一级行业
申万二级行业
申万三级行业
```

## 4.2 A-PreV2 信息

```text
A-PreV2 分数
A-PreV2 状态
turn_type
signal_age
```

这里仅展示，不重新评分。

## 4.3 Company Evidence

```text
company_evidence_state
revenue_yoy
parent_net_profit_yoy
deducted_net_profit_yoy
operating_cashflow_yoy
latest_forecast_type
latest_forecast_change_range
latest_financial_ann_date
company_risk_flags
```

## 4.4 Relative Leadership

```text
leadership_state
leadership_rank_value
industry_rs_5_pct
industry_rs_10_pct
industry_rs_20_pct
up_capture_excess
down_defense_excess
participation_pct
participation_change
up_event_count
down_event_count
```

## 4.5 Supply Profile

```text
total_mv
circ_mv
free_float_mv
free_share
turnover_rate
turnover_rate_f
amount
amount_median_20
supply_profile_label
```

## 4.6 Concept Metadata

结果表只显示前若干标签：

```text
CRO
基因测序
智能医疗
AI智能体
...
```

点击展开全部。

必须能够区分：

```text
概念/主题
行业
证券属性/特色类
```

不要将所有标签混成一个字符串。

## 4.7 AI 分析状态

```text
未分析
已分析
分析过期
分析失败
依赖阻塞
```

展示：

```text
最后分析时间
分析所使用的 as_of_date
分析版本
```

---

# 5. Q1 — Company Evidence
# 公司层面客观证据 / 基本面边际

## 5.1 本模块目的

不是寻找传统意义上的“优质白马股”。

重点回答：

> **公司经营是明显改善、混合、恶化还是存在重大风险？**

尤其关注：

> **边际变化，而不是静态优秀程度。**

例如：

```text
长期亏损，但亏损显著收窄
```

可能比：

```text
一直盈利但利润同比持续下滑
```

对早期交易机会更有价值。

## 5.2 本模块不做重型价值评分

以下指标可以保存和展示，但不得因为一般水平就大幅扣分：

- 负债率；
- ROE；
- 非经常损益比例；
- PE/PB；
- 现金比率；
- 传统估值。

只有极端风险才作为风险标记。

## 5.3 重点数据

必须至少读取：

### 收入

```text
营业收入 / 营业总收入
同比变化
```

### 归母净利润

```text
当期值
去年同期
同比变化
```

### 扣非净利润

```text
当期值
去年同期
同比变化
```

### 经营现金流

```text
当期值
去年同期
同比变化
```

### 毛利率

```text
当前值
去年同期
变化百分点
```

毛利率仅作辅助。

### 业绩预告

```text
type
p_change_min
p_change_max
net_profit_min
net_profit_max
ann_date
summary
change_reason
```

### 业绩快报（如已有接口数据）

展示最新可见快报。

---

# 6. 财务数据必须 Point-in-Time 安全

这是强制要求。

例如：

```text
as_of_date = 2026-08-03
```

系统只能使用：

```text
ann_date <= 2026-08-03
```

的财务报表、财务指标、业绩预告和快报。

即使某份 2026 半年报报告期为：

```text
2026-06-30
```

但如果实际公告日期：

```text
2026-08-20
```

那么在 2026-08-03 回放时 **禁止使用**。

## 6.1 数据选择规则

对每类财务数据：

```text
1. 过滤 ann_date <= as_of_date
2. 同一报告期存在更新版本时
3. 选择截至 as_of_date 当时已公开的最新版本
```

严禁：

```text
按 period 直接取数据库最新值
```

因为这会造成未来数据污染。

---

# 7. Company Evidence 派生事实

不做神秘总分。

输出若干明确事实标签。

## 7.1 收入状态

```text
REVENUE_GROWING
REVENUE_FLAT
REVENUE_DECLINING
REVENUE_UNKNOWN
```

阈值全部配置化。

推荐默认：

```text
growing: yoy >= +5%
flat: -5% < yoy < +5%
declining: yoy <= -5%
```

这是实验默认值，不是交易真理。

## 7.2 利润状态必须正确处理亏损公司

不能简单计算：

```text
(current - previous) / abs(previous)
```

然后把所有结果当作“盈利增长”。

必须区分：

### 盈利 → 盈利

正常同比。

### 亏损 → 盈利

```text
TURNAROUND
```

### 亏损 → 亏损但亏损缩小

```text
LOSS_NARROWING
```

### 亏损 → 亏损扩大

```text
LOSS_WIDENING
```

### 盈利 → 亏损

```text
TURN_TO_LOSS
```

这一点归母和扣非利润都必须支持。

## 7.3 业绩预告状态

保留 Tushare 原始类型：

```text
预增
略增
扭亏
续盈
预减
略减
首亏
续亏
```

不允许只转换成一个数字分。

UI 必须展示：

```text
预告类型
变动区间
公告日期
摘要
原因
```

---

# 8. Company Evidence 总体标签

总体标签不是连续分数。

定义：

```text
POSITIVE
MIXED
NEGATIVE
RISK
UNKNOWN
```

要求每一个标签都可解释。

示例：

```text
POSITIVE
原因：
- 最新报告营收同比 +18.4%
- 扣非净利润由亏损转盈利
- 最新业绩预告为“预增”
```

```text
MIXED
原因：
- 营收同比 +12%
- 归母利润增长
- 但扣非利润仍亏损
```

```text
NEGATIVE
原因：
- 营收同比 -17%
- 归母由盈转亏
- 扣非亏损扩大
```

总体标签逻辑必须集中配置，不得散落 hardcode。

---

# 9. Serious Risk Flags

只标记明显风险，不做一般基本面挑剔。

至少支持：

```text
TURN_TO_LOSS
LOSS_WIDENING
REVENUE_SHARP_DROP
NEGATIVE_OCF_PERSISTENT
NONSTANDARD_AUDIT
NET_ASSET_RISK
```

若数据不足：

```text
UNKNOWN
```

禁止把 UNKNOWN 当 PASS。

---

# 10. Q2 — Relative Leadership
# 行业内部相对领先性

## 10.1 重新定义

本模块不试图猜：

> “神秘主力今天买了多少钱”。

它回答：

> **如果该行业此前已经发生过一段价格运动，这只股票相对于同行是否表现得更像市场优先选择的核心？**

因此名称使用：

```text
Relative Leadership
```

而不是：

```text
Main Money Score
```

---

# 11. 比较基准

历史日期下，股票所属行业必须使用 **当时有效的申万行业成分**。

优先：

```text
申万二级行业
```

如果二级行业有效可比股票：

```text
< 15只
```

则回退：

```text
申万一级行业
```

必须记录：

```text
comparison_level
comparison_industry_code
comparison_industry_name
comparison_universe_size
```

---

# 12. 申万行业历史成员必须防未来函数

使用 `index_member_all`：

```text
in_date <= as_of_date
AND
(out_date is null OR out_date > as_of_date)
```

禁止直接拿：

```text
is_new = Y
```

去回放过去日期。

---

# 13. Relative Leadership 的客观指标

## 13.1 行业内 RS

计算：

```text
stock_ret_5
stock_ret_10
stock_ret_20
```

然后在相同行业成分中做横截面百分位：

```text
industry_rs_5_pct
industry_rs_10_pct
industry_rs_20_pct
```

含义：

```text
industry_rs_20_pct = 85
```

表示：

> 过去 20 个交易日表现超过同一行业约 85% 的股票。

这是“百分位事实”，不是主观 85 分。

---

# 14. 行业上涨事件捕获能力

需要回答：

> 行业真正走强时，它是否比行业更强？

回看：

```text
EVENT_LOOKBACK = 40 trading days
```

推荐默认定义行业上涨事件日：

```text
industry_daily_ret >= +0.8%
```

阈值必须配置化。

获取所有事件：

```text
UP_EVENT_DAYS
```

计算：

```text
up_event_count
```

如果：

```text
up_event_count >= 3
```

计算：

```text
up_capture_excess =
mean(stock_ret - industry_ret on UP_EVENT_DAYS)
```

如果事件不足：

```text
up_capture_state = INSUFFICIENT_EVIDENCE
```

不得填 0。

---

# 15. 行业下跌事件抗跌能力

定义：

```text
industry_daily_ret <= -0.8%
```

获取：

```text
DOWN_EVENT_DAYS
```

若：

```text
down_event_count >= 3
```

计算：

```text
down_defense_excess =
mean(stock_ret - industry_ret on DOWN_EVENT_DAYS)
```

正值表示：

> 行业跌时该股相对更抗跌。

事件不足：

```text
INSUFFICIENT_EVIDENCE
```

---

# 16. 资金参与度变化

主干不依赖“主力净流入”。

必须优先使用真实成交行为：

```text
amount
turnover_rate
turnover_rate_f
```

计算：

```text
amount_ratio_5_20 =
mean(amount,last5) / median(amount,last20)

amount_ratio_10_40 =
mean(amount,last10) / median(amount,last40)
```

行业内部计算：

```text
amount_pct_today
turnover_f_pct_today
```

以及：

```text
participation_pct
```

可由：

```text
amount_ratio_5_20
turnover_rate_f
```

在行业内分别取百分位后平均得到。

这里可以取平均，因为两个输入均是客观百分位。

必须展示底层值。

---

# 17. 参与度排名变化

计算：

```text
participation_pct_recent5
participation_pct_previous15
```

得到：

```text
participation_change =
recent5 - previous15
```

用于观察：

> 近期成交参与度是否正在行业内部上升。

---

# 18. moneyflow_ths 的使用原则

若账户达到 6000 积分，可同步：

```text
moneyflow_ths
```

字段例如：

```text
net_amount
net_d5_amount
buy_lg_amount
buy_lg_amount_rate
...
```

但该数据仅作为：

```text
AUXILIARY_EVIDENCE
```

必须明确标注：

> “同花顺资金流口径辅助数据”

不得作为 Relative Leadership 主干，也不得把：

```text
净流入 > 0
```

等价为：

```text
资金选择了这只股票
```

---

# 19. Relative Leadership 合成方式

这里允许一个 **透明的客观排名值**，但必须明确它不是交易评分。

有效组件：

```text
industry_rs_10_pct
industry_rs_20_pct
up_capture_percentile
down_defense_percentile
participation_change_percentile
```

其中：

```text
industry_rs_5_pct
```

用于展示超短期变化，不默认进入合成，避免太敏感。

## 19.1 合成公式

只对“有效证据”求等权平均：

```text
leadership_rank_value =
mean(valid percentile components)
```

要求：

```text
valid_component_count >= 3
```

否则：

```text
leadership_state = INSUFFICIENT_EVIDENCE
leadership_rank_value = NULL
```

不允许用 0 补缺失值。

## 19.2 Leadership 标签

```text
LEADING
ABOVE_AVERAGE
NEUTRAL
LAGGING
INSUFFICIENT_EVIDENCE
```

建议默认：

```text
>= 75 : LEADING
60~75 : ABOVE_AVERAGE
40~60 : NEUTRAL
< 40  : LAGGING
```

这些只是排名标签，阈值必须配置化并显示。

用户必须能够看到：

> 为什么它被标记成 LEADING。

---

# 20. 这块为什么适合早期机会

如果刚刚出现第一波，历史证据可能不足：

```text
INSUFFICIENT_EVIDENCE
```

这不影响 A-PreV2 候选资格。

如果已经经历：

```text
第一波上涨
→ 行业回调
→ 第二次准备启动
```

那么 Relative Leadership 可以识别：

- 第一波谁跑得更强；
- 调整时谁更抗跌；
- 谁的成交参与度持续提升。

这正是“资金之前已经投过票”的客观痕迹。

---

# 21. Q3 — Supply Profile
# 筹码与推动画像

## 21.1 本模块只做画像，不做硬过滤

必须明确：

```text
大市值 != 差股票
小市值 != 好股票
```

本模块用于帮助理解：

> 这只股票更可能是小票弹性、普通中盘还是容量核心。

---

# 22. 必须展示的数据

使用 `daily_basic` 等：

```text
total_share
float_share
free_share
total_mv
circ_mv
turnover_rate
turnover_rate_f
volume_ratio
```

计算：

```text
free_float_mv =
free_share * close
```

注意单位统一。

必须写单元测试验证：

```text
free_share 的 Tushare 单位
close 单位
最终 free_float_mv 单位
```

不得凭经验直接乘错单位。

---

# 23. Supply Profile 标签

可以配置成：

```text
MICRO_ELASTIC
SMALL_ELASTIC
MID_CAP
LARGE_CAPACITY
MEGA_CAPACITY
```

但标签只能由：

```text
自由流通市值区间
+ 日均成交额
```

客观生成。

阈值必须配置化。

UI 文案建议：

```text
自由流通市值：48亿元
20日成交额中位数：3.2亿元
画像：小中盘 / 弹性较高
```

而不是：

```text
筹码得分 88
```

---

# 24. 额外筹码风险

若已有结构化数据，显示：

```text
未来30/60/90日解禁
近期股东减持
大宗交易
股东人数变化
融资余额
```

全部作为事实标签。

默认不硬过滤。

---

# 25. M1 — Concept Metadata
# 同花顺概念 / 主题标签底库

这是本功能的重要组成部分。

---

# 26. Tushare 权限要求

本模块完整功能要求：

```text
Tushare >= 6000 积分
```

必须使用：

```text
ths_index
ths_member
```

建议同时同步：

```text
ths_daily
moneyflow_ths
moneyflow_ind_ths
```

其中：

```text
ths_index / ths_member
```

是 Concept Metadata 的必需依赖。

用户当前若只有 5200 积分，UI 必须显示：

```text
同花顺概念：PERMISSION_BLOCKED
需要 Tushare 6000 积分
```

不得静默显示空概念列表并让用户以为：

> “这只股票没有概念”。

---

# 27. ths_index 同步

同步 A 股：

```text
exchange = A
```

保存至少：

```text
ts_code
name
type
count
list_date
sync_time
```

类型保留原始值：

```text
N  概念
I  行业
R  地域
S  特色
ST 风格
TH 主题
BB 宽基
```

不要自行丢弃原始类型。

---

# 28. ths_member 同步

必须建立：

```text
stock <-> THS index
```

多对多关系。

保存：

```text
ths_index_code
ths_index_name
ths_index_type
stock_ts_code
stock_name
is_new
snapshot_date
sync_time
```

---

# 29. 非常重要：同花顺概念的历史数据限制

Tushare 当前 `ths_member` 文档中：

```text
weight：暂无
in_date：暂无
out_date：暂无
```

因此：

> **不能假装可以从 Tushare 直接还原任意历史日期的同花顺概念成分。**

这必须在实现中明确处理。

---

# 30. Concept Snapshot 机制

从系统启用概念同步之日起：

每次完整同步后保存：

```text
snapshot_date
```

并保存当日所有：

```text
stock -> concept
```

关系。

建议每个交易日收盘后完整同步一次。

这样从启用日期以后，可以使用：

```text
latest snapshot_date <= as_of_date
```

还原当时系统已知标签。

---

# 31. 历史日期早于概念快照怎么办

例如：

```text
系统2026-08-20才开始保存概念快照
用户回放2026-08-03
```

当前 ths_member 返回的概念 **不能** 被当成 8 月 3 日事实。

必须标记：

```text
concept_temporal_status = CURRENT_REFERENCE_ONLY
```

UI 展示：

> 当前同花顺概念，仅供参考；缺少该历史日期的 Point-in-Time 成分快照。

AI 分析时：

- 可以把当前标签作为“线索”；
- 不能直接声称该标签在 as_of_date 当天已经存在；
- 如该概念对结论关键，必须通过截至 `as_of_date` 的公开资料进行历史验证；
- 无法验证则写“历史时点关联未确认”。

这项要求不得省略。

---

# 32. Concept 标签不是“业务真实性”

同花顺标签只解决：

> **召回 / 发现这家公司可能涉及什么。**

不能自动等价：

```text
属于CRO概念
=
CRO是公司核心业务
```

---

# 33. AI 对概念的最终表达

AI 不输出：

```text
CRO exposure = 90
AI医疗 exposure = 70
```

必须输出语义分类。

推荐枚举：

```text
CORE_BUSINESS
MATERIAL_BUSINESS
BUSINESS_LAYOUT
THEMATIC_RELATION
TRADING_ATTRIBUTE
WEAK_OR_UNVERIFIED
```

用户可见中文：

```text
CRO：核心业务，高相关
AI医疗：存在业务布局，但收入贡献不明确
人民币贬值受益：交易属性标签，不是主营
融资融券：证券属性，不属于业务主题
```

---

# 34. 主营业务构成用于验证概念

使用：

```text
fina_mainbz_vip
```

保存最新 Point-in-Time 可见的：

```text
产品
行业
主营收入
主营利润
主营成本
报告期
```

AI 可以使用这些事实辅助判断概念是否属于核心业务。

---

# 35. 主营收入占比

同一报告期、同一分类类型中可计算：

```text
bz_sales_share
```

但必须小心：

- Tushare 数据可能同时包含汇总项与子项；
- “其他主营业务”可能和其他条目有包含关系；
- 不允许机械相加造成收入超过100%。

因此：

### 规则

仅当同一分类口径能够确认条目互斥时显示占比。

否则：

```text
revenue_share = UNKNOWN
```

AI 文案：

> 公司披露该业务，但现有结构化数据无法可靠计算收入占比。

禁止硬凑 90%/70%。

---

# 36. 概念标签详情页

点击股票“概念”后展示：

```text
同花顺原始标签
类型
数据来源
快照日期
历史有效性状态
AI验证结果（若已分析）
AI验证证据
```

必须区分：

```text
原始数据
AI判断
```

不得覆盖原始标签。

---

# 37. A1 — AI Deep Research
# 人工触发 AI 深度研究

这是整个二次评价系统的最终研究层。

**必须由用户人工触发。**

不得默认对全市场几千只股票自动跑 AI。

---

# 38. AI 分析入口

用户在结果表：

```text
勾选 1~20 只股票
```

点击：

```text
AI 深度分析
```

可以选择：

```text
分析单只
逐只分析选中股票
```

每只股票必须生成独立研究结果。

---

# 39. AI 输入必须完整

每次分析必须给 AI 以下上下文。

## 39.1 股票技术信息

来自 A-PreV2：

```text
as_of_date
A-PreV2 score
status
turn_type
signal_date
signal_age
MA transition summary
关键原始技术指标
```

AI 不需要重新算技术分，但需要知道为什么该股进入候选。

## 39.2 Company Evidence

输入：

```text
最新可见报告
收入变化
归母利润变化
扣非利润变化
现金流
业绩预告
公司风险标记
主营业务构成
```

全部严格 Point-in-Time。

## 39.3 Relative Leadership

输入全部原始结果：

```text
比较行业
可比股票数
RS5/10/20 行业百分位
up_capture
down_defense
participation
leadership_state
leadership_rank_value
证据是否充分
```

## 39.4 Supply Profile

输入：

```text
总市值
流通市值
自由流通市值
成交额
换手率
自由流通换手率
解禁/减持等
```

## 39.5 Concept Metadata

输入：

```text
所有同花顺原始标签
标签类型
snapshot_date
historical validity
```

不能只给AI前三个标签。

## 39.6 历史资金复盘

读取用户现有每日复盘中的：

```text
资金地图
市场偏好
次日观察
其他相关市场复盘内容
```

默认读取：

```text
as_of_date 向前 20 个交易日
```

必须可配置：

```text
5 / 10 / 20 / 40 trading days
```

最重要：

```text
review_date <= as_of_date
```

严禁使用未来复盘。

---

# 40. 历史资金复盘输入不得被量化成拍脑袋分数

系统不需要将：

```text
“光通信/CPO是最明确主攻方向”
```

转换成：

```text
CPO = 92分
```

AI 直接理解原始自然语言。

这是明确设计要求。

---

# 41. 历史复盘过长时的处理

不得静默截断。

若超过模型上下文预算：

```text
1. 按日期分块
2. 对较旧内容先做带日期的结构化压缩
3. 最近若干交易日保留完整原文
4. 最终提示词同时包含：
   - 历史压缩摘要
   - 最近完整复盘
5. 保存压缩结果与来源日期映射
```

UI 必须显示：

```text
本次使用20个交易日复盘
其中最近8日原文
较早12日经日期保留式压缩
```

---

# 42. AI 网络检索

AI 深度分析必须具备外部检索能力，用于：

- 验证公司真实业务；
- 解释某个概念标签为什么存在；
- 查询截至分析日期已公开的重要公司事实；
- 查询产业/政策背景；
- 查找公开公告或可靠媒体报道；
- 验证“算力租赁”“CRO”“AI医疗”等关系是否真实。

---

# 43. 网络检索历史时点规则

若：

```text
as_of_date < today
```

AI 必须严格区分：

### 可用于当时决策的信息

```text
publish_date <= as_of_date
```

### 后见信息

```text
publish_date > as_of_date
```

默认：

> 后见信息不得参与“当时是否应该优先研究”的判断。

如为了复盘需要展示后见信息，必须单独放入：

```text
事后验证（不参与当时判断）
```

禁止混入主体结论。

---

# 44. AI 搜索来源优先级

优先：

1. 上市公司正式公告 / 定期报告；
2. 交易所 / 证监会 / 政府正式文件；
3. 公司官网 / 官方公众号；
4. 可信财经媒体；
5. 其他公开资料。

对于概念关联，不允许仅因为：

> 某个股票网站写“XX概念”

就直接认定为核心业务。

必须尽量追溯实质依据。

---

# 45. AI 对“Concept Relevance”的分析要求

对每个与当前市场故事相关的重要概念输出：

```text
概念名称
关联分类
事实依据
主营收入贡献（如可确认）
当前市场是否正在交易该方向
置信度
```

关联分类：

```text
核心业务
重要业务
存在布局但贡献不明确
主题/交易属性关联
弱相关
无法验证
```

这里的：

```text
置信度
```

用：

```text
高 / 中 / 低
```

即可。

不要输出伪精确百分比。

---

# 46. AI 必须回答的核心问题

每只股票必须回答：

### 1. 技术上现在处于什么阶段？

简要引用 A-PreV2，不重新发明技术结论。

### 2. 截至该日期，市场资金最近在交易什么？

结合用户历史资金复盘。

### 3. 这只股票真正涉及哪些相关主题？

结合：

```text
同花顺标签
主营业务构成
网络验证
```

### 4. 哪些概念属于核心业务？

必须与：

```text
交易属性 / 弱概念
```

区分。

### 5. 公司层面有没有明显边际改善或拖累？

结合 Company Evidence。

### 6. 如果行业此前已有一波行情，它是否表现出相对领先？

结合 Relative Leadership。

### 7. 如果证据不足，要明确说证据不足。

### 8. 这只股票更可能是什么市场角色？

例如：

```text
先锋
高弹性跟随
容量核心候选
普通跟随
暂时无法判断
```

这属于 AI 推理，不做固定量化分。

### 9. 当前最重要的正面证据是什么？

### 10. 当前最重要的反证是什么？

### 11. 为什么它可能比同类候选更值得优先研究？

或：

> 为什么即使技术形态漂亮，它仍然可能只是普通跟随？

---

# 47. AI 输出格式

不要输出单一总分。

推荐固定结构：

```markdown
## 研究结论

研究优先级：高 / 中 / 低 / 证据不足

一句话结论：
...

## 1. 当前市场上下文

...

## 2. 公司与当前主题的真实关联

- CRO：核心业务，高相关
- AI医疗：有布局，但收入贡献不明确
- 人民币贬值受益：交易属性，不是主营

## 3. 公司层面证据

...

## 4. 相对领先性

...

## 5. 筹码与可能市场角色

...

## 6. 主要正面证据

...

## 7. 主要反证 / 风险

...

## 8. 不确定性

...

## 9. 最终研究建议

重点研究 / 保留观察 / 暂不优先
```

---

# 48. “研究优先级”不是交易信号

AI 输出：

```text
重点研究
```

不等于：

```text
BUY
```

禁止输出自动下单建议。

---

# 49. AI 必须区分事实和推理

AI 结果中的关键结论必须标记来源类型。

例如：

```text
[事实] 公司2026H1业绩预告为预增...
[事实] 过去20日行业内RS为82百分位...
[复盘记录] 8月12日资金地图判断CPO强化...
[推理] 因此该股更像当前主题的高弹性跟随...
```

UI 至少能展示事实来源。

---

# 50. AI 分析结果必须存档

保存：

```text
analysis_id
ts_code
as_of_date
created_at
model
prompt_version
data_snapshot_version
review_lookback
web_search_used
result_markdown
priority
uncertainties
```

同一股票不同日期必须是不同记录。

禁止覆盖历史分析。

---

# 51. 分析过期机制

如果：

- 新交易日到来；
- 新财报/预告发布；
- 概念标签变化；
- 用户新增资金复盘；
- A-PreV2 状态变化；

旧分析显示：

```text
STALE
```

但不得删除。

用户可重新分析。

---

# 52. H1 — Historical Replay
# 任意历史日期回放

整个二次评价系统必须支持：

```text
选择 2026-08-03
```

然后看到：

> **如果当时运行系统，能够看到什么。**

---

# 53. 所有模块都必须遵守 as_of_date

包括：

```text
A-PreV2
Company Evidence
Relative Leadership
Supply Profile
申万行业
历史复盘
AI网络搜索
业绩预告
财务报表
```

---

# 54. 未来函数统一断言

后端建立统一：

```python
assert source_available_date <= as_of_date
```

对于价格数据：

```python
assert trade_date <= as_of_date
```

对于财务/公告：

```python
assert ann_date <= as_of_date
```

对于用户复盘：

```python
assert review_date <= as_of_date
```

对于申万成员：

```text
in_date <= as_of_date
out_date为空 OR out_date > as_of_date
```

---

# 55. 同花顺概念例外必须显式标记

因为当前接口历史纳入/剔除日期不可用：

```text
PIT_SAFE
SNAPSHOT_APPROX
CURRENT_REFERENCE_ONLY
```

必须让用户知道。

不能伪造历史准确性。

---

# 56. 数据源设计

## 56.1 Tushare 结构化数据

至少需要：

### 行情

```text
daily
adj_factor 或项目已有前复权行情
daily_basic
```

### 财务

```text
income_vip
cashflow_vip
fina_indicator_vip
forecast_vip
express_vip（如项目已有）
fina_mainbz_vip
```

### 申万

```text
index_member_all
sw_daily / 项目现有申万行情
```

### 同花顺（6000积分）

```text
ths_index
ths_member
ths_daily
moneyflow_ths
moneyflow_ind_ths
```

---

# 57. Tushare 当前权限事实

截至本文编写时：

```text
ths_index：6000积分
ths_member：6000积分
moneyflow_ths：6000积分
fina_mainbz_vip：5000积分
fina_indicator_vip：5000积分
forecast_vip：5000积分
daily_basic：2000可用，5000无总量限制
index_member_all：2000积分
```

这些属于外部服务条件。

系统必须提供：

```text
Data Capability Check
```

实际运行时检查接口权限。

---

# 58. 不购买新闻/公告 Tushare 额外权限

本版本不要求购买 Tushare 单独新闻/公告权限。

原因：

AI 深度分析是人工触发，只研究少量候选。

优先：

```text
结构化Tushare事实
+
AI网络检索
```

完成公司/主题研究。

---

# 59. 推荐数据库模型

字段可以按现有项目命名调整，但语义不得减少。

## 59.1 candidate_secondary_snapshot

```text
id
as_of_date
ts_code
aprev2_score
aprev2_status
turn_type
company_evidence_state
leadership_state
leadership_rank_value
supply_profile_label
calc_version
created_at
```

## 59.2 company_evidence_snapshot

```text
as_of_date
ts_code
latest_report_period
latest_report_ann_date
revenue
revenue_yoy
parent_net_profit
parent_net_profit_yoy
parent_profit_state
deducted_net_profit
deducted_net_profit_yoy
deducted_profit_state
operating_cashflow
operating_cashflow_yoy
gross_margin
gross_margin_yoy_delta
forecast_ann_date
forecast_type
forecast_p_change_min
forecast_p_change_max
forecast_net_profit_min
forecast_net_profit_max
evidence_state
reason_json
risk_flags_json
data_version
```

## 59.3 relative_leadership_snapshot

```text
as_of_date
ts_code
comparison_level
comparison_industry_code
comparison_industry_name
comparison_universe_size
stock_ret_5
stock_ret_10
stock_ret_20
industry_rs_5_pct
industry_rs_10_pct
industry_rs_20_pct
up_event_count
up_capture_excess
up_capture_pct
down_event_count
down_defense_excess
down_defense_pct
amount_ratio_5_20
amount_ratio_10_40
participation_pct
participation_change
participation_change_pct
valid_component_count
leadership_rank_value
leadership_state
reason_json
calc_version
```

## 59.4 supply_profile_snapshot

```text
as_of_date
ts_code
close
total_mv
circ_mv
free_share
free_float_mv
amount
amount_median_20
turnover_rate
turnover_rate_f
volume_ratio
unlock_30d
unlock_60d
unlock_90d
recent_reduction_flag
supply_profile_label
data_version
```

## 59.5 ths_index_master

```text
ths_code
name
type
exchange
count
list_date
sync_time
```

## 59.6 ths_concept_member_snapshot

```text
snapshot_date
ths_code
ths_name
ths_type
ts_code
stock_name
is_new
sync_time
```

唯一约束建议：

```text
(snapshot_date, ths_code, ts_code)
```

## 59.7 stock_business_segment

```text
ts_code
period
ann_date_or_available_date
bz_code
bz_item
bz_sales
bz_profit
bz_cost
source
sync_time
```

## 59.8 ai_stock_research

```text
analysis_id
ts_code
as_of_date
created_at
priority
result_markdown
model
prompt_version
review_lookback_days
aprev2_snapshot_id
company_snapshot_id
leadership_snapshot_id
supply_snapshot_id
concept_snapshot_date
concept_temporal_status
web_search_used
source_manifest_json
uncertainty_json
status
stale_reason
```

---

# 60. API 设计

可按现有框架调整路径，但能力必须完整。

## 60.1 查询二次评价列表

```http
GET /api/candidate-secondary
    ?date=2026-08-03
    &source=APREV2
```

返回所有模块摘要。

## 60.2 股票详情

```http
GET /api/candidate-secondary/{ts_code}
    ?date=2026-08-03
```

返回：

```text
A-PreV2
Company Evidence
Relative Leadership
Supply Profile
Concept Metadata
AI history
```

## 60.3 重新计算

```http
POST /api/candidate-secondary/run
```

Body：

```json
{
  "date": "2026-08-03"
}
```

## 60.4 同花顺概念同步

```http
POST /api/data/ths-concepts/sync
```

返回：

```text
权限状态
指数数
股票-概念关系数
snapshot_date
错误明细
```

## 60.5 数据能力检查

```http
GET /api/data/capabilities
```

至少：

```json
{
  "tushare_points_detected": 6000,
  "ths_index": "READY",
  "ths_member": "READY",
  "moneyflow_ths": "READY",
  "fina_mainbz_vip": "READY",
  "ai_web_search": "READY"
}
```

如果无法自动知道积分，可以用真实接口 probe。

## 60.6 AI 深度研究

```http
POST /api/ai/stock-research
```

Body：

```json
{
  "date": "2026-08-03",
  "ts_codes": [
    "600518.SH",
    "600721.SH"
  ],
  "review_lookback": 20,
  "use_web_search": true
}
```

## 60.7 AI 历史

```http
GET /api/ai/stock-research/{ts_code}
```

---

# 61. 前端详情抽屉

点击任意候选股票必须出现完整详情。

Tabs：

```text
技术来源
公司证据
相对领先
筹码画像
概念标签
AI研究
历史变化
```

---

# 62. “历史变化”Tab

至少能够查看过去 40 个交易日：

```text
A-PreV2 score
industry_rs_20_pct
leadership_rank_value
amount_ratio_5_20
turnover_rate_f
company_evidence_state（有公告时变化）
```

必须支持查看：

> 某只股票为什么从普通候选逐渐变成相对领先。

---

# 63. 默认排序

系统不得把一个主观综合分当默认排序。

建议默认：

```text
第一排序：A-PreV2 score DESC
第二排序：leadership_state（有证据者优先展示）
第三排序：leadership_rank_value DESC
```

用户必须可以：

- 按 Company Evidence 筛选；
- 按 Leadership 排序；
- 按自由流通市值排序；
- 按行业筛选；
- 按概念筛选；
- 只看已分析 / 未分析；
- 只看用户勾选。

---

# 64. 人工研究清单

用户可以把股票加入：

```text
研究清单
```

字段：

```text
added_date
as_of_date
ts_code
user_note
research_status
```

状态：

```text
待AI分析
AI已分析
重点研究
保留观察
暂不优先
```

必须允许用户手工修改状态。

AI 不能自动覆盖用户状态。

---

# 65. AI 提示词基本约束

Prompt 必须包含以下系统性要求：

```text
你是在做“研究优先级判断”，不是预测明日涨跌。

不要因为股票技术形态好就自动给出正面结论。

不要把同花顺概念标签当成公司核心业务事实。

区分：
1. 公司核心业务
2. 重要业务
3. 布局但收入不明
4. 市场交易属性
5. 弱相关或无法验证

重点利用用户截至 as_of_date 的历史资金复盘理解：
赚钱效应正在向哪里迁移、强化、扩散、分歧和衰减。

所有历史分析必须保持 Point-in-Time：
不得利用 as_of_date 之后发生的新闻、行情、财报和复盘来判断当时。

相对领先指标证据不足时明确说“证据不足”，不要当作负面。

最终不要给伪精确的0~100主题分。
输出高/中/低/证据不足的研究优先级，并说明证据。
```

---

# 66. 康美药业案例作为验收样本

必须加入：

```text
600518.SH 康美药业
as_of_date = 2026-08-03
```

目标不是强制 AI 得出：

> “康美一定不该选”。

而是检查系统能否提供：

### 技术事实

A-PreV2 已选中，技术结构不错。

### Company Evidence

展示当时已经公开的经营与利润情况。

### Relative Leadership

只使用 8 月 3 日及以前数据。

### Concept Metadata

展示：

```text
中药
医药流通
以及其他当时可用/当前参考标签
```

并正确标历史有效性。

### AI

应能够研究：

> 当时市场资金主要在交易医药里的什么方向；
> 康美和这些方向是否真正相关；
> 公司层面是否存在强边际催化；
> 技术形态漂亮是否足以让它成为当前医药方向优先研究对象。

不得因为 8 月 13 日已经知道康美后来涨得弱，就反向污染 8 月 3 日判断。

---

# 67. 正向对照样本

在同一历史时期选择若干：

```text
创新药 / CRO / 医药强势候选
```

如果它们也由 A-PreV2 选出，比较：

- Theme 实际关联；
- Company Evidence；
- Relative Leadership；
- AI结合历史复盘给出的研究优先级。

验收重点不是预测100%正确。

而是：

> 系统是否把当时已有的关键差异完整展示出来。

---

# 68. Relative Leadership 负样本测试

至少验证：

### 情况 A

刚出现第一波，没有足够历史事件。

预期：

```text
INSUFFICIENT_EVIDENCE
```

而不是 0。

### 情况 B

行业上涨时明显落后、行业跌时跌更多。

预期：

```text
LAGGING
```

### 情况 C

第一波强于行业，调整抗跌，参与度提升。

预期：

```text
LEADING / ABOVE_AVERAGE
```

---

# 69. Concept Metadata 验收

必须测试一只概念很多的股票。

确认：

1. 能获得全部同花顺标签；
2. 原始 type 未丢失；
3. 可区分概念、主题、特色等；
4. AI 不会把“融资融券”认成主营；
5. AI 能把“CRO核心业务”与“AI医疗布局但收入不明”区分；
6. 历史日期无快照时明确显示 `CURRENT_REFERENCE_ONLY`；
7. 不允许当前概念标签伪装成历史事实。

---

# 70. AI 历史复盘验收

构造：

```text
8月10日
8月11日
8月12日
```

三篇资金复盘。

分析：

```text
as_of_date = 8月11日
```

系统必须：

```text
读取 <=8月11日
禁止读取8月12日
```

写自动测试验证。

---

# 71. 财务历史回放验收

例如某半年报：

```text
period = 2026-06-30
ann_date = 2026-08-20
```

运行：

```text
as_of_date = 2026-08-03
```

必须完全不可见。

运行：

```text
as_of_date = 2026-08-21
```

才能可见。

---

# 72. 完整性验收清单

AI Coder 交付前必须逐项自检。

- [ ] A-PreV2 结果可进入二次评价
- [ ] 可选择任意历史日期
- [ ] Company Evidence 已实现
- [ ] 收入/归母/扣非/现金流同比已实现
- [ ] 亏损收窄/扩大/扭亏/转亏逻辑已实现
- [ ] 业绩预告已实现
- [ ] 财务 Point-in-Time 已实现
- [ ] Relative Leadership 已实现
- [ ] 申万历史成员 Point-in-Time 已实现
- [ ] RS5/10/20 行业内百分位已实现
- [ ] 行业上涨事件捕获已实现
- [ ] 行业下跌抗跌已实现
- [ ] 成交参与度变化已实现
- [ ] Evidence Insufficient 状态已实现
- [ ] Supply Profile 已实现
- [ ] 自由流通市值单位校验已实现
- [ ] 解禁/减持等辅助标签已实现（数据可用处）
- [ ] ths_index 同步已实现
- [ ] ths_member 多对多映射已实现
- [ ] 概念快照历史存储已实现
- [ ] 历史概念时点状态已实现
- [ ] fina_mainbz_vip 主营业务已实现
- [ ] AI 深度分析入口已实现
- [ ] AI 可读 A-PreV2 原始信息
- [ ] AI 可读 Company Evidence
- [ ] AI 可读 Relative Leadership
- [ ] AI 可读 Supply Profile
- [ ] AI 可读全部 Concept Metadata
- [ ] AI 可读取历史资金复盘
- [ ] 历史复盘严格 <= as_of_date
- [ ] AI 网络检索已实现并可标来源
- [ ] 历史网络检索防未来信息已实现
- [ ] AI 概念真实性验证已实现
- [ ] AI 不输出伪精确主题相关度分
- [ ] AI 输出高/中/低/证据不足研究优先级
- [ ] AI 明确正面证据、反证、不确定性
- [ ] AI 结果历史存档已实现
- [ ] AI 分析过期状态已实现
- [ ] 人工研究清单已实现
- [ ] 用户状态不会被 AI 覆盖
- [ ] 所有底层指标可查看
- [ ] 所有阈值配置化
- [ ] 所有数据缺失显式展示
- [ ] 权限不足显式展示
- [ ] 不存在静默降级
- [ ] 康美药业历史案例完成回归测试

---

# 73. “不得退化实现”约束

这是本项目特别重要的要求。

AI Coder 不得出现以下情况：

### 禁止 1

文档要求：

```text
历史复盘 + AI
```

实际只把当天复盘给 AI。

### 禁止 2

文档要求：

```text
所有同花顺概念
```

实际只显示前三个。

### 禁止 3

文档要求：

```text
历史日期
```

实际查询当前最新财务数据。

### 禁止 4

文档要求：

```text
网络验证概念
```

实际只让 LLM 根据标签自己猜。

### 禁止 5

文档要求：

```text
Evidence Insufficient
```

实际把缺失值设成0分。

### 禁止 6

某接口权限不足时直接：

```text
except Exception:
    return []
```

然后页面显示“无数据”。

必须显示真实错误状态。

### 禁止 7

为了“先跑起来”删除任一完整功能。

---

# 74. 完整性报告

功能完成后，AI Coder 必须额外输出：

```text
IMPLEMENTATION_COVERAGE.md
```

逐条对应本文第 72 节 checklist。

每项必须写：

```text
IMPLEMENTED
文件路径
核心函数
测试文件
验证方式
```

若未实现：

```text
NOT_IMPLEMENTED
原因
```

不允许写：

```text
基本实现
部分支持
后续可扩展
```

来模糊状态。

---

# 75. 自动化测试要求

至少覆盖：

```text
test_financial_point_in_time
test_financial_loss_state
test_sw_member_point_in_time
test_leadership_insufficient_evidence
test_up_capture
test_down_defense
test_participation_change
test_free_float_mv_unit
test_ths_permission_status
test_ths_snapshot_temporal_status
test_review_no_future_leak
test_ai_analysis_snapshot
test_ai_result_not_overwrite
```

---

# 76. 运行日志与审计

每次二次评价运行保存：

```text
run_id
as_of_date
calc_version
data_versions
start_time
end_time
stock_count
error_count
missing_count
```

每只股票必须能够解释：

> 每个结果来自什么数据、什么日期、什么公式。

---

# 77. 参数配置

所有阈值统一配置。

建议：

```yaml
secondary_evaluation:

  fundamental:
    revenue_growth_positive: 0.05
    revenue_decline_negative: -0.05

  leadership:
    event_lookback: 40
    up_event_threshold: 0.008
    down_event_threshold: -0.008
    min_up_events: 3
    min_down_events: 3
    min_valid_components: 3

    leading_min: 75
    above_average_min: 60
    neutral_min: 40

  supply:
    # 实际阈值由项目配置，不散落在代码
    free_float_mv_buckets: []

  ai:
    default_review_lookback: 20
    max_batch_stocks: 20

  concept:
    sync_frequency: DAILY
```

所有默认值标记：

```text
EXPERIMENTAL_DEFAULT
```

---

# 78. 为什么这套设计不再做 Theme Context 数值分

用户每天已经在进行专业资金复盘。

复盘记录类似：

```text
光通信/CPO是今天最明确的主攻方向；
房地产由装修装饰向开发、租购、服务扩散；
医药赚钱效应持续；
油气昨日强今日弱；
MLCC由强化进入分歧。
```

这些信息最有价值的地方是：

> **资金赚钱效应如何迁移、强化、衰减和轮动。**

这属于上下文推理。

系统必须：

```text
保存原始复盘
→ AI读取历史序列
→ AI结合当前候选理解
```

而不是：

```text
强行转成CPO 92分 / 医药78分
```

---

# 79. 最终用户工作流

完整用户体验应为：

```text
1. 用户选择日期

2. A-PreV2 产生技术候选

3. 二次评价页自动显示：
   - 公司边际事实
   - Relative Leadership
   - Supply Profile
   - Concept Tags

4. 用户通过客观数据排序、浏览K线
   从几十/几百只中人工勾选一批

5. 点击“AI深度分析”

6. AI读取：
   - 该历史日期技术状态
   - 公司客观事实
   - 相对领先事实
   - 筹码画像
   - 同花顺概念
   - 主营构成
   - 过去若干日资金复盘
   - 截至当时的网络公开信息

7. AI输出：
   - 市场故事
   - 公司与故事真实关系
   - 公司证据
   - 相对领先
   - 可能角色
   - 正面证据
   - 反证
   - 不确定性
   - 高/中/低研究优先级

8. 用户决定：
   - 重点研究
   - 保留观察
   - 暂不优先
```

---

# 80. 最终设计哲学

这套功能不是为了证明：

> “程序可以完全理解股市。”

而是把不同能力放在合适的位置。

```text
A-PreV2：
发现技术机会

程序：
计算客观事实和横截面比较

同花顺概念：
负责广覆盖召回潜在主题

主营业务：
提供公司真实业务底层事实

历史资金复盘：
保存人对市场资金迁移的长期观察

AI：
理解当前故事、验证概念、综合上下文

人：
决定真正值得下注的机会
```

最重要的原则：

> **量化负责把客观事实整理出来；AI负责理解这些事实在当前市场故事中意味着什么；用户负责最终交易决策。**

---

# 81. Tushare 数据接口依据（开发核对）

本文编写时依据 Tushare 官方接口文档：

```text
ths_index
文档 doc_id=259
6000积分
获取同花顺概念、行业、特色、主题等板块指数

ths_member
文档 doc_id=261
6000积分
获取概念板块成分
支持 con_code 查询股票
当前 weight / in_date / out_date 标记“暂无”

fina_mainbz / fina_mainbz_vip
文档 doc_id=81
vip 5000积分
主营业务按产品/地区/行业

daily_basic
文档 doc_id=32
至少2000积分，5000积分无总量限制
含换手率、自由流通换手率、自由流通股本、总市值、流通市值等

fina_indicator / fina_indicator_vip
文档 doc_id=79
vip 5000积分
含 ann_date，必须用于Point-in-Time控制

forecast / forecast_vip
文档 doc_id=45
vip 5000积分
含公告日期、预告类型、利润变动区间

index_member_all
文档 doc_id=335
2000积分
申万一级/二级/三级历史成员，含in_date/out_date

moneyflow_ths
文档 doc_id=348
6000积分
同花顺个股资金流，作为辅助证据
```

AI Coder 实现前应以项目当前 Tushare SDK 实际返回字段再次做一次 schema probe，
但不得因此删除本文要求的语义能力。

---

# 82. 最终交付要求

开发完成后必须交付：

```text
1. 完整功能代码
2. 数据库迁移
3. 所有API
4. 完整前端页面
5. AI Prompt / Prompt Version
6. 自动化测试
7. 康美药业历史回归结果
8. IMPLEMENTATION_COVERAGE.md
```

在 `IMPLEMENTATION_COVERAGE.md` 全部检查通过之前，

**不得宣称本功能开发完成。**
