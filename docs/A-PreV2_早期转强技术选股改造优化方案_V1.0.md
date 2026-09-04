# A-PreV2 早期转强技术选股改造优化方案 V1.0

> **用途：交给 AI Coder 直接改造现有 A-PreV2**
>
> 本文针对当前 A-PreV2 的实际运行结果进行修正。
>
> 本次只解决当前已经暴露出来的核心问题：
>
> 1. `Freshness` 在未站上 3 根均线时仍拿满分；
> 2. `EARLY_TURN` 仅靠总分即可进入，缺乏必要状态门槛；
> 3. 股票跌回均线后再次站上，会反复“重置为早期转强”；
> 4. `TOO_LATE` 把“短期涨得急”和“整个早期窗口已经结束”混为一谈；
> 5. `SECONDARY_TURN` 当前过于泛化，不能区分“普通失败反抽”和“真正完成过一波行情”；
> 6. A-PreV2 需要记住“本轮转向生命周期”，而不是每天只看当前截面。
>
> **本次不加入 30 分钟双底/结构突破策略。**
> 海星股份、301013 这类“价格结构先于均线确认”的机会后续单独研究，不为了捕捉它们而放松 A-PreV2。

---

# 1. A-PreV2 的职责重新定义

A-PreV2 只负责寻找：

> **长期弱势/低位之后，第一次有效转强的早期窗口。**

它不是负责：

- 第一波上涨完成后的二次启动；
- 上涨趋势调整后的再启动；
- 30分钟双底突破；
- 高位平台突破；
- 所有“重新站上均线”的股票。

因此以后必须区分：

```text
“第一次转强窗口”
```

和：

```text
“第一波已经走完，后来再次转强”
```

后者即使技术上仍然很好，也不应该重新被 A-PreV2 当成 EARLY_TURN。

---

# 2. 当前实现中必须先修的明确 Bug

当前实现中：

```text
Retake < 3
```

时，`Freshness` 仍然可能得到：

```text
10 分
```

并显示：

```text
站上3MA第0天
突破新鲜度极佳
```

这是明确错误。

例如现有结果中多次出现：

```text
Retake = 0
Fresh = 10
```

甚至仍然因为其他分数较高而进入 `EARLY_TURN`。

---

## 2.1 正确规则

只有当前满足：

```text
close > 至少3根目标均线
```

时，才存在：

```text
freshness
```

否则：

```text
freshness_valid = false
freshness_days = NULL
freshness_score = 0
```

不得：

```text
freshness_days = 0
```

再被解释成“最新鲜”。

---

## 2.2 Freshness 的日期定义

当股票第一次满足：

```text
retake_count >= 3
```

时：

```text
freshness_days = 1
```

第二个连续交易日：

```text
freshness_days = 2
```

依此类推。

如果中间失去 3MA：

```text
当前 retake freshness 失效
```

但注意：

> **这不代表整个 Turn Episode 可以重新从头开始。**

当前局部 `retake freshness` 和整个“第一次转强生命周期”必须分开。

---

# 3. EARLY_TURN 不能再只靠总分决定

当前：

```text
score >= 75
→ EARLY_TURN
```

这个逻辑需要改。

原因：

股票可能：

```text
Retake = 0
Freshness 本来就不成立
```

但因为其他项目得分高，仍然被总分补成 `EARLY_TURN`。

---

## 3.1 新规则

`EARLY_TURN` 必须同时满足：

### 状态条件

```text
turn_episode_state == FIRST_TURN_WINDOW
```

### 当前价格条件

```text
retake_count >= 3
```

### 总分条件

```text
score >= early_turn_score_threshold
```

推荐保留当前：

```text
75
```

作为实验默认值，但不再单独决定状态。

---

## 3.2 PRE_READY

`PRE_READY` 可以允许：

```text
retake_count == 2
```

或者：

```text
当前尚未完全站上3MA，但均线压缩/方向改善明显
```

但必须仍处于：

```text
PRE_FIRST_TURN
或
FIRST_TURN_WINDOW
```

不能是：

```text
POST_FIRST_WAVE
```

---

# 4. 新增 Turn Episode：本轮转向生命周期

这是本次改造最核心的部分。

当前算法每天重新计算当前形态，却没有记住：

> **这一轮底部转向到底从什么时候开始、第一波是否已经完成。**

因此千红制药、紫光股份这类股票会：

```text
第一次转强
→ 上涨
→ 回调
→ 再次站上均线
→ Freshness重新变高
→ 再次被当成EARLY_TURN
```

这是错误的。

---

# 5. Turn Episode 只需要三个状态

本次不要设计复杂状态机。

只增加三个核心状态：

```text
PRE_FIRST_TURN
FIRST_TURN_WINDOW
POST_FIRST_WAVE
```

---

## 5.1 PRE_FIRST_TURN

含义：

> 仍处于底部准备/修复阶段，尚未形成第一次有效转强。

典型情况：

- 均线仍在下降；
- 价格只站上 1~2 根均线；
- 均线开始压缩；
- 方向逐渐改善；
- 尚未满足第一次有效触发。

---

## 5.2 FIRST_TURN_WINDOW

含义：

> 第一次有效转强已经出现，仍然处于 A-PreV2 希望寻找的早期窗口。

进入该状态后，需要保存：

```text
first_trigger_date
first_trigger_close
first_trigger_atr20
```

这三个字段以后用于：

- 判断已经离第一次触发走了多远；
- 判断最佳新开仓窗口是否已经明显过去；
- 防止后面重新站均线时“重置人生”。

---

## 5.3 POST_FIRST_WAVE

含义：

> 第一次有效转强之后，股票已经完成一段明显上涨，并随后进入明显调整/回落。

一旦进入：

```text
POST_FIRST_WAVE
```

该 Turn Episode 内不得再重新变回：

```text
FIRST_TURN_WINDOW
```

即使之后：

- 均线再次粘合；
- 再次站上 3MA；
- 再次放量；
- 再次形成 Knot；
- 再次总分 90。

这些都属于：

> 后续二次机会

而不是 A-PreV2 的“第一次早期转强”。

---

# 6. FIRST_TURN_WINDOW 的首次触发条件

不要完全依赖总分。

建议首次有效触发满足：

```text
retake_count >= 3
AND
direction_score >= 最低要求
AND
transition_score >= 最低要求
AND
score >= first_trigger_score
```

默认实验参数可先使用：

```text
first_trigger_score = 65
```

原因：

第一次有效触发不一定当日就达到 75 分。

例如：

```text
65~74
```

可能已经是非常重要的早期信号。

真正：

```text
>=75
```

再用于 `EARLY_TURN` 精选。

---

# 7. 如何判断“第一波已经完成”

本次不要设计过于复杂。

从：

```text
first_trigger_date
first_trigger_close
```

开始记录：

```text
max_close_since_trigger
max_high_since_trigger
max_return_since_trigger
```

同时记录：

```text
drawdown_from_episode_high
```

---

## 7.1 推荐判断思路

只有同时满足：

### A. 第一波已经明显走出来

满足任一：

```text
max_return_since_trigger >= first_wave_min_return
```

或：

```text
(max_high_since_trigger - first_trigger_close) / first_trigger_atr20
>= first_wave_min_atr
```

### B. 随后出现明显回撤/调整

满足任一：

```text
drawdown_from_episode_high >= first_wave_pullback_pct
```

或：

```text
价格重新跌回短中期均线团，并持续若干日
```

才进入：

```text
POST_FIRST_WAVE
```

---

## 7.2 参数不要写死

建议先作为配置：

```yaml
turn_episode:
  first_trigger_score: 65

  first_wave_min_return: 0.10
  first_wave_min_atr: 4.0

  first_wave_pullback_pct: 0.06
  pullback_below_ma_cluster_days: 3
```

这些均标记：

```text
EXPERIMENTAL_DEFAULT
```

后续用样本回归调整。

重点是：

> **先实现生命周期思想，不要把这些默认阈值当成最终交易真理。**

---

# 8. TOO_LATE 必须拆成两个完全不同的问题

当前逻辑：

```text
close - MA20 > 2 ATR
→ TOO_LATE
```

把两件事混在一起：

### 问题 A

> 今天涨得是不是太急？

### 问题 B

> 整个第一次早期转强窗口是不是已经过去？

这是不同的问题。

---

# 9. 保留短期 Extension，但不要叫 TOO_LATE

ATR 偏离仍然有价值。

它回答：

> **当前这个交易日追进去，短期位置是否拉得太急。**

建议改名：

```text
entry_extension_state
```

枚举：

```text
NORMAL
STRETCHED
VERY_STRETCHED
```

默认：

```text
<= 1.5 ATR : NORMAL
1.5~2.0 ATR : STRETCHED
> 2.0 ATR : VERY_STRETCHED
```

参数配置化。

---

## 9.1 Extension 不能改变 Turn Episode

例如：

```text
Turn Episode = FIRST_TURN_WINDOW
Extension = VERY_STRETCHED
```

意思是：

> 这仍然是第一次转强阶段，但今天追进去短期风险较高。

不能再简单显示：

```text
TOO_LATE
```

---

# 10. 新增 Entry Timing：相对首次触发的位置

真正“最佳买点已经过去”应更多参考：

```text
first_trigger_close
```

而不是只参考 MA20。

必须计算：

```text
days_since_first_trigger
return_since_first_trigger
```

---

## 10.1 Entry Timing 状态

建议：

```text
ENTRY_WINDOW
EXTENDED_FROM_TRIGGER
TOO_LATE_FOR_NEW_ENTRY
```

---

## 10.2 初版逻辑

### ENTRY_WINDOW

例如：

```text
return_since_first_trigger <= +4%
```

或：

```text
距离 first_trigger 不超过若干 ATR
```

### EXTENDED_FROM_TRIGGER

例如：

```text
+4% ~ +8%
```

### TOO_LATE_FOR_NEW_ENTRY

例如：

```text
> +8%
```

以上阈值只作为实验默认。

真正实现时建议同时参考：

```text
return_since_trigger
ATR extension
days_since_trigger
```

但不要设计复杂打分。

---

# 11. 良信股份与弘景光电为什么要这样改

---

## 11.1 良信股份

现有：

```text
8/13:
score = 90
extension ≈ 2.1 ATR
→ TOO_LATE
```

8/14：

```text
价格 9.99 → 10.01
几乎没有继续上涨
仍然因为 MA20 偏离约2ATR
→ TOO_LATE
```

这是不合理的。

改造后应该可能表现为：

```text
Turn Episode:
FIRST_TURN_WINDOW

8/13:
entry_extension = STRETCHED / VERY_STRETCHED
entry_timing = ENTRY_WINDOW 或 EXTENDED_FROM_TRIGGER

8/14:
仍然 FIRST_TURN_WINDOW
return_since_first_trigger 很小
不应仅因2ATR判“最佳买点已过”
```

---

## 11.2 弘景光电

现有：

```text
8/13:
50.93
82分
EARLY_TURN

8/14:
55.36
82分
2.9 ATR
TOO_LATE
```

这个案例的 `TOO_LATE` 方向基本合理，但原因需要改。

正确表达更应该是：

```text
Turn Episode:
仍然 FIRST_TURN_WINDOW

Entry Timing:
TOO_LATE_FOR_NEW_ENTRY

原因：
距离首次有效触发价格已经上涨约8%+
```

也就是说：

> 阶段仍早，但新开仓时点已经明显变差。

---

# 12. 紫光股份、千红制药：生命周期必须阻止“重新变新鲜”

---

## 12.1 千红制药

第一次有效窗口大致发生在：

```text
6月底
```

后面已经：

```text
完成第一波上涨
→ 回调/整理
```

进入：

```text
POST_FIRST_WAVE
```

以后即使：

```text
8月再次站上均线
总分重新80~90
```

也不能再：

```text
EARLY_TURN
```

最多显示：

```text
POST_FIRST_WAVE
A_PRE_NOT_APPLICABLE
```

---

## 12.2 紫光股份

该股在当前 A-PreV2 被再次高分选出，但此前已经明显走出过一轮行情，当前属于：

> 日线第一波上涨后的调整/再启动。

因此应被生命周期识别为：

```text
POST_FIRST_WAVE
```

而不是重新：

```text
EARLY_TURN
```

---

# 13. SECONDARY_TURN 背景分类需要降级

当前多个明显不同样本长期全部显示：

```text
SECONDARY_TURN
```

说明当前背景分类区分能力不足。

---

## 13.1 本次不要继续强化 SECONDARY_TURN

建议：

### A-PreV2 核心状态优先看 Turn Episode

```text
PRE_FIRST_TURN
FIRST_TURN_WINDOW
POST_FIRST_WAVE
```

### 原 `background_type`

可以保留用于审计：

```text
FIRST_TURN
SECONDARY_TURN
CONSOLIDATION_RESTART
```

但暂时不再让它决定核心状态。

---

## 13.2 需要重新定义“前期强转向尝试”

普通下跌过程中的短线反抽：

```text
不能自动算成 SECONDARY_TURN
```

只有前期曾经满足类似：

```text
真实站上3MA
+
持续若干日
+
价格/均线方向明显转好
```

才可以认定为：

```text
prior_valid_turn_attempt = true
```

否则：

```text
普通反抽
```

不能把底部第一次真正启动误分类成二次转强。

---

# 14. 联诚精密：增加一个简单的结构受损警告

联诚精密当前问题不是“已经走完第一波”，而更像：

```text
急跌
→ 快速反抽
→ 再急跌
→ 再快速反抽
```

这种结构可能因为：

- MA5快速上拐；
- MA10快速上拐；
- 短均线交叉；

而获得较高分。

---

## 14.1 本次只增加警告，不新建复杂策略

增加：

```text
structural_damage_flag
```

初版可基于最近：

```text
60个交易日
```

识别：

### 大幅快速下跌

例如：

```text
20日内最大回撤 >= 20%
```

且：

### 最近低点距离当前很近

例如：

```text
days_since_60d_low <= 15
```

且：

### MA60 仍明显向下

则：

```text
structural_damage_flag = true
```

---

## 14.2 作用

不直接 FAIL。

但：

```text
FIRST_TURN_WINDOW
+
structural_damage_flag = true
```

时：

- 最高只能进入 `PRE_READY`
- 暂不允许直接 `EARLY_TURN`

直到结构进一步稳定。

这是为了减少：

> 瀑布式下跌后的反射性反弹

被误判为成熟底部转向。

---

# 15. 状态输出建议

最终不要只输出：

```text
EARLY_TURN / PRE_READY / TOO_LATE
```

建议同时输出三组状态：

---

## 15.1 Turn Episode

```text
PRE_FIRST_TURN
FIRST_TURN_WINDOW
POST_FIRST_WAVE
```

---

## 15.2 Signal Status

```text
EARLY_TURN
PRE_READY
WATCH
NO_SIGNAL
A_PRE_NOT_APPLICABLE
```

---

## 15.3 Entry Timing

```text
ENTRY_WINDOW
EXTENDED_FROM_TRIGGER
TOO_LATE_FOR_NEW_ENTRY
NOT_APPLICABLE
```

---

## 15.4 Extension

```text
NORMAL
STRETCHED
VERY_STRETCHED
```

这样：

### 弘景 8/14

可能显示：

```text
Turn Episode:
FIRST_TURN_WINDOW

Signal:
EARLY_TURN

Entry Timing:
TOO_LATE_FOR_NEW_ENTRY

Extension:
VERY_STRETCHED
```

### 紫光 8/14

可能：

```text
Turn Episode:
POST_FIRST_WAVE

Signal:
A_PRE_NOT_APPLICABLE

Entry Timing:
NOT_APPLICABLE
```

这比一个 `TOO_LATE` 清楚得多。

---

# 16. 评分模型如何处理

本次不要求推翻现有 100 分评分。

现有：

```text
Base
Trans
Retake
Dir
Fresh
Vol
Space
```

可以暂时保留。

但必须修改：

### Fresh

按照本文件修 Bug。

### Score

只负责：

> 同一个 Turn Episode 内部的技术质量排序。

不得再单独决定：

```text
是否属于EARLY_TURN
```

---

# 17. 推荐最终判定顺序

后端流程改为：

```text
1. 计算基础技术指标

2. 计算/更新 Turn Episode

3. 修正 Freshness

4. 计算原有各模块分数

5. 判断 structural_damage_flag

6. 判断 Signal Status

7. 计算 Entry Timing

8. 计算 Extension State

9. 输出完整审计结果
```

---

# 18. Signal Status 建议逻辑

伪代码：

```python
if turn_episode_state == "POST_FIRST_WAVE":
    signal_status = "A_PRE_NOT_APPLICABLE"

elif structural_damage_flag:
    if score >= 65:
        signal_status = "PRE_READY"
    elif score >= 50:
        signal_status = "WATCH"
    else:
        signal_status = "NO_SIGNAL"

elif turn_episode_state == "FIRST_TURN_WINDOW":
    if retake_count >= 3 and score >= 75:
        signal_status = "EARLY_TURN"
    elif score >= 65:
        signal_status = "PRE_READY"
    elif score >= 50:
        signal_status = "WATCH"
    else:
        signal_status = "NO_SIGNAL"

else:  # PRE_FIRST_TURN
    if score >= 65:
        signal_status = "PRE_READY"
    elif score >= 50:
        signal_status = "WATCH"
    else:
        signal_status = "NO_SIGNAL"
```

这是初版逻辑，可配置，但原则不得变：

> **状态优先，分数其次。**

---

# 19. Entry Timing 建议逻辑

只有：

```text
first_trigger_date != NULL
AND
turn_episode_state == FIRST_TURN_WINDOW
```

时计算。

保存：

```text
days_since_first_trigger
return_since_first_trigger
extension_atr
```

伪代码：

```python
if return_since_first_trigger <= entry_window_return:
    entry_timing = "ENTRY_WINDOW"

elif return_since_first_trigger <= too_late_return:
    entry_timing = "EXTENDED_FROM_TRIGGER"

else:
    entry_timing = "TOO_LATE_FOR_NEW_ENTRY"
```

ATR extension 作为辅助说明：

```text
STRETCHED / VERY_STRETCHED
```

不要让 ATR 单独覆盖整个 Entry Timing。

---

# 20. 必须保留审计字段

每只股票每天至少输出：

```text
turn_episode_state

first_trigger_date
first_trigger_close

days_since_first_trigger
return_since_first_trigger

max_return_since_trigger
drawdown_from_episode_high

retake_count
freshness_valid
freshness_days

score
signal_status

entry_timing
extension_atr
extension_state

structural_damage_flag
background_type
```

---

# 21. 前端展示建议

主表不要塞太多字段。

建议：

```text
A-Pre分数：82

阶段：
首次转强窗口

信号：
EARLY_TURN

买点：
正常 / 已延伸 / 新开仓偏晚

短期偏离：
正常 / 拉伸 / 明显拉伸
```

点击详情再显示：

```text
首次触发日期
首次触发价格
距触发涨幅
第一波最大涨幅
当前回撤
Freshness
Turn Episode
```

---

# 22. 回归测试样本

本次必须使用以下样本验证。

---

## 22.1 千红制药 002550

期望：

### 6月底

应允许进入：

```text
FIRST_TURN_WINDOW
```

并在适当日期进入：

```text
PRE_READY / EARLY_TURN
```

### 第一波完成后

应进入：

```text
POST_FIRST_WAVE
```

### 7月后/8月重新站均线

不得再次：

```text
EARLY_TURN
```

---

## 22.2 良信股份 002706

重点：

```text
2026-08-13
2026-08-14
```

期望：

- 不应仅因 `2 ATR` 判整个机会已经 TOO_LATE；
- 应仍可以处于 `FIRST_TURN_WINDOW`；
- Entry Timing 根据首次触发价格判断；
- 8/14 若距首次触发并未明显上涨，不应直接叫“最佳买点已过”。

---

## 22.3 弘景光电 301479

重点：

```text
2026-08-13
2026-08-14
```

期望：

### 8/13

```text
FIRST_TURN_WINDOW
EARLY_TURN
ENTRY_WINDOW
```

或接近这一含义。

### 8/14

仍可：

```text
FIRST_TURN_WINDOW
```

但：

```text
TOO_LATE_FOR_NEW_ENTRY
```

因为已经明显离开首次触发价格。

---

## 22.4 紫光股份 000938

重点：

```text
2026-08-13
2026-08-14
```

期望：

应识别：

```text
POST_FIRST_WAVE
```

不得因为重新：

- Knot；
- Retake；
- 放量；

再次成为：

```text
EARLY_TURN
```

---

## 22.5 联诚精密 002921

期望：

若仍处于：

```text
快速大跌后的反射性反弹
```

则：

```text
structural_damage_flag = true
```

即使总分较高，也最高：

```text
PRE_READY
```

直到中期结构进一步稳定。

---

# 23. 本次明确不做的事情

不要顺手增加：

```text
30分钟双底突破
日线W底颈线突破
复杂波浪识别
缠论买点
行业/概念判断
AI二次研究逻辑
```

这些属于其他模块。

本次只修：

> **A-PreV2 自己对“第一次早期转强”生命周期的识别。**

---

# 24. 验收清单

- [ ] `Retake < 3` 时 Freshness 不再拿分
- [ ] `freshness_days=0` 不再等价“最新鲜”
- [ ] EARLY_TURN 不再只由总分决定
- [ ] 新增 `PRE_FIRST_TURN`
- [ ] 新增 `FIRST_TURN_WINDOW`
- [ ] 新增 `POST_FIRST_WAVE`
- [ ] 保存 `first_trigger_date`
- [ ] 保存 `first_trigger_close`
- [ ] 保存 `return_since_first_trigger`
- [ ] 第一波完成后不会重新回到 FIRST_TURN_WINDOW
- [ ] ATR Extension 不再直接等价 TOO_LATE
- [ ] 新增 Entry Timing
- [ ] 新增 Extension State
- [ ] `SECONDARY_TURN` 不再作为核心状态依据
- [ ] 普通反抽不再轻易识别成“前期有效转向”
- [ ] 新增 `structural_damage_flag`
- [ ] 千红制药回归通过
- [ ] 良信股份回归通过
- [ ] 弘景光电回归通过
- [ ] 紫光股份回归通过
- [ ] 联诚精密回归通过

---

# 25. 最终设计原则

本次改造最重要的不是把某只股票从：

```text
82分
```

调成：

```text
72分
```

而是让系统真正理解：

> **这只股票现在还处于第一次转强窗口，还是第一波已经结束。**

以后 A-PreV2 需要同时回答两件事：

```text
1. 整个转向生命周期走到哪一步？
2. 今天这个位置对于新开仓来说是否已经延伸？
```

这两个问题必须分开。

最终：

> **A-PreV2 负责发现第一次有效转强；后续再启动机会交给其他策略。**
