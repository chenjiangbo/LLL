# A-PreV2 第一波识别与生命周期修正方案 V1.0

> 用途：交给 AI Coder 对当前 A-PreV2 做小范围修正。
>
> 本次只修改 **FIRST_TURN_WINDOW → POST_FIRST_WAVE / PRE_FIRST_TURN** 的生命周期判断。
>
> **不修改 PRE 定义，不修改七项评分，不修改 75 分入选阈值。**

---

## 1. 当前问题

样本：`300849.SZ 锦盛新材`

当前程序轨迹大致为：

```text
2026-07-31  PRE_FIRST_TURN
2026-08-03  PRE_FIRST_TURN
2026-08-06  FIRST_TURN_WINDOW
2026-08-12  FIRST_TURN_WINDOW
2026-08-19  PRE_FIRST_TURN
2026-08-21  PRE_FIRST_TURN
```

更合理的轨迹应为：

```text
2026-07-31  PRE_FIRST_TURN
2026-08-03  PRE_FIRST_TURN
2026-08-06  FIRST_TURN_WINDOW
2026-08-12  FIRST_TURN_WINDOW / 第一波已展开
2026-08-14 左右  POST_FIRST_WAVE
2026-08-21  POST_FIRST_WAVE
```

原因：

这只股票从 7 月下旬约 16~17 元底部开始，至 8 月 12 日最高收盘约 23.15 元，已经形成一段很明显的第一波上涨。

后续 8 月中旬回落到 19~21 元区域，属于：

> **第一波上涨后的明显调整**

而不是：

> **一次首次转强失败后重新回到底部准备。**

---

## 2. 根因

当前失败逻辑主要基于：

```text
current_close < first_trigger_close * 0.88
```

300849：

```text
first_trigger_close ≈ 22.58
2026-08-19 close ≈ 19.57
```

相对触发价跌幅约 -13.3%，因此被程序判为：

```text
FIRST_TURN_WINDOW
→ Turn Failed
→ PRE_FIRST_TURN
```

但这个判断忽略了：

> first_trigger 只是确认点，不一定是本轮上涨的真实起点。

300849 在正式触发前已经从约 16~17 元涨到 22 元以上。

因此：

```text
trigger → high
```

涨幅很小，

但：

```text
episode_base_low → first_wave_high
```

已经是非常明显的第一波。

---

## 3. 新增并固定 episode_base_low

每一轮 PRE / FIRST Episode 必须保存：

```text
episode_base_low
episode_base_low_date
```

建议定义：

> 在本轮 PRE_FIRST_TURN 形成过程中，取触发日前最近 40 个交易日的最低前复权价。

一旦进入 FIRST_TURN_WINDOW：

```text
episode_base_low
episode_base_low_date
```

在本轮 Episode 内固定，不再漂移。

同时继续保存：

```text
first_trigger_date
first_trigger_close
first_wave_high_close
first_wave_high_date
```

---

## 4. 第一波是否成立：改为从 episode_base_low 判断

不要再主要使用：

```text
first_trigger_close → high
```

判断第一波。

改为：

```text
first_wave_gain
=
first_wave_high_close / episode_base_low - 1
```

V1 建议：

满足任一：

```text
first_wave_gain >= 8%
```

或：

```text
(first_wave_high - episode_base_low) / ATR20_at_base >= 2.5
```

则：

```text
first_wave_formed = true
```

参数配置化。

---

## 5. FIRST_TURN_WINDOW 回落时的判断顺序

最重要的改动：

> **先判断第一波是否已经形成，再判断 trigger 是否失败。**

正确顺序：

```text
FIRST_TURN_WINDOW
↓
1. first_wave_formed ?
```

如果：

```text
first_wave_formed = true
```

继续判断：

```text
从 first_wave_high_close 回撤 >= 6%
或
收盘跌破 MA30
```

则：

```text
→ POST_FIRST_WAVE
```

此时：

> 不允许再因为价格跌破 first_trigger_close 12% 而重置回 PRE。

如果：

```text
first_wave_formed = false
```

才允许继续检查：

```text
current_close < first_trigger_close * 0.88
```

或：

```text
跌破 episode_base_low / 触发前结构低点
```

若成立：

```text
→ Turn Failed
→ PRE_FIRST_TURN
```

---

## 6. 状态迁移规则

最终：

```text
PRE_FIRST_TURN
    ↓ 有效首次触发
FIRST_TURN_WINDOW
```

在 FIRST 内：

```text
如果第一波已经形成
    ↓
出现明显回撤
    ↓
POST_FIRST_WAVE
```

只有：

```text
第一波尚未形成
+
首次转强明显失败
```

才允许：

```text
FIRST_TURN_WINDOW
→ PRE_FIRST_TURN
```

---

## 7. POST_FIRST_WAVE 不允许重新回 PRE

同一个 Episode 内：

```text
POST_FIRST_WAVE
```

之后即使：

```text
均线再次压缩
重新站上 1~3 根均线
Freshness 再次提高
技术得分重新升高
```

也不能回：

```text
PRE_FIRST_TURN
FIRST_TURN_WINDOW
```

除非以后满足已经单独存在的：

```text
Structural Reset
```

即真正形成一轮新的大级别下跌、新低和新 Episode。

---

## 8. 300849 回归验收

固定测试：

| 日期 | 期望生命周期 |
|---|---|
| 2026-07-31 | `PRE_FIRST_TURN` |
| 2026-08-03 | `PRE_FIRST_TURN` |
| 2026-08-04~05 | 仍可为 `PRE_FIRST_TURN`，属于较成熟准备 |
| 2026-08-06 | `FIRST_TURN_WINDOW` |
| 2026-08-12 | `FIRST_TURN_WINDOW`，且 `first_wave_formed=true` |
| 2026-08-14 左右 | 应进入 `POST_FIRST_WAVE` |
| 2026-08-19 | 不得回 `PRE_FIRST_TURN` |
| 2026-08-21 | 应保持 `POST_FIRST_WAVE` |

特别检查：

```text
episode_base_low
first_trigger_close
first_wave_high_close
first_wave_gain
first_wave_formed
drawdown_from_first_wave_high
```

---

## 9. 本次不要修改

本次不要顺手调整：

```text
PRE_FIRST_TURN 的定义
七项评分结构
Freshness
Retake
Dir
Volume
Space
75 分正式入选阈值
is_overextended
```

本次只解决：

> **已经形成第一波的股票，被错误当成首次转强失败并重新回到 PRE**

这个生命周期问题。

---

## 10. 最终原则

一句话：

> **触发价是确认点，不是本轮行情起点。**

判断第一波是否已经发生，应优先看：

```text
episode_base_low → first_wave_high
```

而不是只看：

```text
first_trigger_close → first_wave_high
```

因此：

> **只要本轮从底部已经形成过一段明确上涨，之后的大幅回落应优先解释为第一波后的调整，而不是“首次转强失败、重新底部准备”。**
