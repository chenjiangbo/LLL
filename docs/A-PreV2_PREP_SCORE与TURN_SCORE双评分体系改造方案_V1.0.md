# A-PreV2 双评分体系改造方案 V1.0

> **用途**：交给 AI Coder 对当前 A-PreV2 的评分体系做一次小范围重构。
>
> **本次只改评分，不改生命周期。**
>
> 当前已经修正的：
>
> ```text
> PRE_FIRST_TURN
> FIRST_TURN_WINDOW
> POST_FIRST_WAVE
> ```
>
> 以及 Episode / 第一波识别逻辑，本次全部保持不动。

---

# 1. 改造目标

当前 A-PreV2 用同一套七项评分：

```text
Base / Trans / Retake / Dir / Fresh / Vol / Space
```

同时评价：

```text
PRE_FIRST_TURN
FIRST_TURN_WINDOW
```

这会产生两个问题：

1. **真正的早期 PRE 被低估**  
   PRE 阶段本来就可能只站回 1~2 根均线，Freshness 尚未出现，均线也未完成多头重排，因此旧评分天然偏低。

2. **PRE 的高分原因和人工判断不一致**  
   用户真正看重的是：
   - 前面有一段较充分下跌；
   - MA10 / MA20 从陡峭下降开始减速；
   - 均线逐渐走平、形成较大弧度；
   - 均线开始靠拢/交叉；
   - K 线开始站回 1~2 根短均线。

   但旧评分中，PRE 经常靠 Freshness、Volume、Space 拿到高分，而不是因为“均线正在走平”。

因此改为：

```text
PRE_FIRST_TURN
→ PREP_SCORE

FIRST_TURN_WINDOW
→ TURN_SCORE
```

---

# 2. 核心原则

以后评分只回答当前生命周期自己的问题：

### PREP_SCORE

回答：

> **这只股票的“底部早期准备”成熟到什么程度？**

### TURN_SCORE

回答：

> **这只股票已经进入首次转强以后，当前转强确认质量怎么样？**

不要再让 PRE 和 FIRST 共用同一把 100 分尺子。

---

# 3. PREP_SCORE：底部准备成熟度

满分：

```text
100
```

建议拆为 4 个部分：

| 维度 | 分值 |
|---|---:|
| 均线下降减速 / 走平 / 拐头 | 40 |
| 均线靠拢 / 压缩 / 交叉 | 25 |
| K线开始夺回短均线 | 20 |
| 下跌充分 + 当前位置仍早 | 15 |

PRE 阶段：

```text
Freshness = 0 权重
Volume = 0 权重
```

这两个指标保留底层数据，但不进入 PREP_SCORE。

---

# 4. PREP_SCORE：均线走平度 40 分

这是 PRE 最重要的部分。

主要看：

```text
MA10
MA20
```

不要把 MA5 当成核心，因为 MA5 太灵敏。

---

## 4.1 需要新增/确认的指标

```text
ma10_slope_5d
= MA10(t) / MA10(t-5) - 1

ma20_slope_5d
= MA20(t) / MA20(t-5) - 1

ma10_slope_prev5
= MA10(t-5) / MA10(t-10) - 1

ma20_slope_prev5
= MA20(t-5) / MA20(t-10) - 1

ma10_curve_improve
= ma10_slope_5d - ma10_slope_prev5

ma20_curve_improve
= ma20_slope_5d - ma20_slope_prev5
```

---

## 4.2 MA10 当前斜率：10 分

```text
ma10_slope_5d <= -3.0%   → 0
-3.0% ~ -2.0%            → 2
-2.0% ~ -1.0%            → 5
-1.0% ~ -0.3%            → 8
>= -0.3%                  → 10
```

含义：

> MA10 越接近横向，准备度越高。

---

## 4.3 MA20 当前斜率：10 分

```text
ma20_slope_5d <= -3.0%   → 0
-3.0% ~ -2.0%            → 2
-2.0% ~ -1.0%            → 5
-1.0% ~ -0.3%            → 8
>= -0.3%                  → 10
```

MA20 比 MA10 更慢，能更好区分：

> 只是短线反弹

和

> 中期均线真的开始变平。

---

## 4.4 MA10 减速改善：10 分

```text
ma10_curve_improve <= 0      → 0
0 ~ +0.5%                    → 3
+0.5% ~ +1.0%                → 6
>= +1.0%                     → 10
```

例如：

```text
前5日 MA10斜率 = -3.0%
最近5日 MA10斜率 = -1.0%
```

则：

```text
curve_improve = +2.0%
```

应该给高分。

这就是对人工看到的：

> “均线开始形成弧度”

的量化近似。

---

## 4.5 MA20 减速改善：10 分

同样：

```text
ma20_curve_improve <= 0      → 0
0 ~ +0.5%                    → 3
+0.5% ~ +1.0%                → 6
>= +1.0%                     → 10
```

---

# 5. PREP_SCORE：均线靠拢 / 交叉 25 分

继续使用当前 Trans 中有价值的部分，但不要直接复用整个旧 `Trans score`。

---

## 5.1 均线压缩：15 分

使用：

```text
ma_spread_atr
=
(max(MA5, MA10, MA20, MA30)
-
min(MA5, MA10, MA20, MA30))
/
ATR20
```

评分：

```text
<= 0.60  → 15
<= 0.90  → 12
<= 1.20  → 8
<= 1.60  → 4
> 1.60   → 0
```

---

## 5.2 均线交叉 / 结扎：10 分

使用最近 10 日“发生过交叉的不同均线对数量”。

注意：

> **不要使用交叉事件总次数冒充交叉对数量。**

建议：

```text
cross_pair_count_10d = 0  → 0
1                       → 4
2                       → 7
>= 3                    → 10
```

如果现有系统还有：

```text
cross_event_count_10d
```

可以保留作噪声诊断，但不直接增加准备分。

---

# 6. PREP_SCORE：K线夺回短均线 20 分

PRE 阶段不要求已经完整站上 3~4 根均线。

这里主要奖励：

> 价格已经开始重新夺回短期成本区。

建议：

```text
只站上 0 根 MA5/10/20/30  → 0
站上 1 根                  → 5
站上 2 根                  → 12
站上 3 根                  → 18
站上 4 根                  → 20
```

但注意：

> `retake_count >= 3` 并不自动意味着应该进入 FIRST。

生命周期仍由现有 FIRST_TURN 触发规则决定。

---

# 7. PREP_SCORE：背景和位置 15 分

这一块不要复杂化。

---

## 7.1 前期下跌充分度：10 分

优先使用当前已有下跌背景判断。

建议：

满足任一：

```text
20日跌幅 <= -8%
40日跌幅 <= -15%
60日最大回撤 >= 18%
```

并且：

```text
距离最近40日高点 >= 8个交易日
```

则：

```text
10分
```

较弱但仍有明显调整：

```text
5分
```

没有明显下跌 / 调整：

```text
0分
```

这里目的不是判断“绝对底部”，只是避免：

> 股票只跌了 2~3 天，就因为均线短暂交叉被认成底部准备。

---

## 7.2 当前偏离位置：5 分

使用：

```text
extension_atr = (close - MA20) / ATR20
```

评分：

```text
extension_atr <= 1.0  → 5
<= 1.5                → 3
> 1.5                 → 0
```

PRE 阶段不再额外使用“离60日高点越远越高分”的旧 Space 逻辑。

---

# 8. PREP_SCORE 不再使用的旧评分项

在：

```text
PRE_FIRST_TURN
```

下，不再计算旧总分：

```text
Base + Trans + Retake + Dir + Fresh + Vol + Space
```

而改为：

```text
PREP_SCORE
=
SlopeTurn
+
CompressionCross
+
Retake
+
BackgroundPosition
```

其中：

```text
Freshness 不计分
Volume 不计分
旧 Space 不计分
旧 Dir 不计分
```

原因：

- Freshness 是正式突破确认指标；
- Volume 更适合 FIRST；
- Space 容易出现“越跌分越高”；
- Dir 偏完整重排，PRE 阶段本来还未完成。

---

# 9. TURN_SCORE：FIRST 阶段继续使用现有评分

在：

```text
FIRST_TURN_WINDOW
```

下，继续使用当前七项评分体系作为 `TURN_SCORE`。

本次先不大改：

```text
Base
Trans
Retake
Dir
Fresh
Vol
Space
```

原因：

这套评分本来更适合回答：

> “已经进入首次转强以后，确认质量怎么样？”

---

# 10. TURN_SCORE 本次只做两个兼容调整

## 10.1 Freshness 只属于 FIRST

只有：

```text
turn_episode_state == FIRST_TURN_WINDOW
```

时：

```text
Freshness
```

才参与评分。

---

## 10.2 PRE / FIRST 分数字段统一但标记 score_type

可以继续保留：

```text
total_score
```

避免大改前端和数据库。

但新增：

```text
score_type
```

值：

```text
PREP_SCORE
TURN_SCORE
NONE
```

规则：

```text
PRE_FIRST_TURN
→ total_score = prep_score
→ score_type = PREP_SCORE

FIRST_TURN_WINDOW
→ total_score = turn_score
→ score_type = TURN_SCORE

POST_FIRST_WAVE
→ 可保留 raw score 做诊断
→ score_type = NONE
→ 不参与 A-Pre 正式排序
```

---

# 11. 正式入选规则暂不修改

保持当前：

```text
FIRST_TURN_WINDOW
AND
TURN_SCORE >= 75
→ selected = true
```

PRE 不因为 PREP_SCORE 高就自动成为正式候选。

PREP_SCORE 的用途是：

> **在 PRE_FIRST_TURN 里排序，找到最接近真正转强的少量股票。**

例如：

```text
PREP_SCORE >= 70
```

可以作为重点观察区，但 V1 不增加新的生命周期状态。

---

# 12. 族兴新材 920078 回归要求

该股票用于验证：

> **PREP_SCORE 是否真正反映“均线从陡峭下降逐渐走平”的过程。**

重点日期：

```text
2026-08-05
2026-08-06
2026-08-21
```

---

## 12.1 2026-08-05 / 08-06

可以保持：

```text
PRE_FIRST_TURN
```

但 PREP_SCORE 不应该很高。

原因：

8/5：

```text
MA10 ≈ 18.97
MA20 ≈ 21.15
MA30 ≈ 23.86
```

8/6：

```text
MA10 ≈ 18.96
MA20 ≈ 20.88
MA30 ≈ 23.47
```

价格已经开始修复，但 MA20 / MA30 依然明显向下。

期望：

```text
PREP_SCORE = 中低
```

不要因为：

```text
站上部分均线
```

就直接获得很高准备度。

---

## 12.2 2026-08-21

应仍可以是：

```text
PRE_FIRST_TURN
```

并且：

```text
PREP_SCORE 明显高于 8/5、8/6
```

因为当时：

```text
MA10 ≈ 19.38
MA20 ≈ 19.17
MA30 ≈ 20.38
```

MA10 / MA20 已明显接近横向并互相靠拢。

这是用户人工判断中非常重要的：

> **均线真正开始走平。**

---

## 12.3 不要求固定具体分数

本次验收先看：

```text
score(8/21) > score(8/6) > score(8/5)
```

并且差距应该能从：

```text
ma10_slope
ma20_slope
ma10_curve_improve
ma20_curve_improve
```

中解释出来。

不要为了命中 72 / 60 / 50 之类的具体数字过拟合。

---

# 13. 智信精密回归要求

之前人工认为：

> 2026-07-29 已经属于较早的底部准备。

因为：

- K线已经开始站上两根短均线；
- MA5 / MA10 有交叉；
- 但完整 FIRST 尚未出现。

新 PREP_SCORE 应比旧 42 分更符合“已有明显准备迹象”的直觉。

重点不是必须多少分，而是：

> 不应因为 Freshness=0 就被长期压在低分。

---

# 14. 科森科技回归要求

2026-08-04 / 08-05：

人工认为已经出现早期 PRE。

新 PREP_SCORE 应能体现：

> 短均线正在走平和重新靠拢。

但如果 MA20 / MA30 仍明显向下：

> 分数仍不应过高。

---

# 15. 不要修改的内容

本次不要同时修改：

```text
PRE_FIRST_TURN 生命周期定义
FIRST_TURN_WINDOW 触发规则
POST_FIRST_WAVE 判断
Episode Reset
第一波识别
75分 FIRST 正式入选阈值
is_overextended
```

先只验证：

> **双评分是否比一套评分更符合人工排序。**

---

# 16. 建议增加的诊断输出

PRE 详情中增加：

```text
PREP_SCORE
ma10_slope_5d
ma20_slope_5d
ma10_slope_prev5
ma20_slope_prev5
ma10_curve_improve
ma20_curve_improve
ma_spread_atr
cross_pair_count_10d
retake_count
extension_atr
```

同时输出四项分解：

```text
SlopeTurn: xx / 40
CompressionCross: xx / 25
Retake: xx / 20
BackgroundPosition: xx / 15
```

这样后续看到一个 PRE 分数异常时，可以直接判断：

> 是均线走平算错，
> 还是压缩算错，
> 还是 Retake 权重不合理。

---

# 17. 本次实现目标

本次改造完成后，系统应满足：

```text
PRE_FIRST_TURN
→ 分数主要随着“均线由陡峭下降转向走平”而提高

FIRST_TURN_WINDOW
→ 分数主要随着“正式转强确认质量”提高
```

尤其避免：

```text
早期 PRE 因为没有 Freshness 而被严重低估
```

以及：

```text
PRE 因为刚站上3MA、当天放量而突然获得过高分
```

最终一句话：

> **PREP_SCORE 评价“变化正在形成”；TURN_SCORE 评价“变化已经确认”。**
