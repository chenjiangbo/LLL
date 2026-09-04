# A-PreV2 早期转强技术选股实现说明（当前版）

> 本文以当前代码为准，说明界面唯一开放的技术选股策略 A-PreV2 的数据口径、特征计算、三种生命周期状态、评分规则和入选条件。它是实现文档，不构成投资建议。
>
> 核心实现：`backend/screening/early_turn_service.py`、`backend/screening/early_turn_engine.py`。批次结果保存于 `early_turn_run` 与 `early_turn_result`。

## 1. 策略定位

A-PreV2 用来识别股票从低位准备或整理状态，进入**第一次有效转强窗口**的阶段。策略把两个概念分开：

- **生命周期**回答“本轮行情走到哪一步”；
- **技术评分**回答“当前技术条件有多完整”。

因此，分数高不等于一定处于首次转强窗口；只有 `FIRST_TURN_WINDOW` 且正式分达到 75 分，才会成为 A-PreV2 正式候选。`POST_FIRST_WAVE` 是第一波完成后的整理/后续阶段，不会因为短期重新站上均线而自动重新成为首次转强。

## 2. 数据与时间口径

### 2.1 Point-in-Time 前复权

每只股票在评估日向前读取最多 150 根日 K。原始行情保留在 `screening_daily_bar`，技术指标使用同日 `screening_adj_factor` 的前复权价格：

```python
select b.trade_date, b.open, b.high, b.low, b.close,
       b.vol, b.amount, a.adj_factor
from screening_daily_bar b
join screening_adj_factor a
  on a.asset_code = b.asset_code
 and a.trade_date = b.trade_date
where b.asset_code = %s
  and b.trade_date <= %s
order by b.trade_date desc
limit 150
```

代码随后只对 OHLC 做 `price * adj_factor`；成交量和成交额保持原始口径。这样可以避免除权除息日的价格跳变被误判为暴跌或生命周期破坏，同时没有引用评估日之后的数据。K 线展示和技术评分因此使用同一套前复权逻辑，原始值仍可用于审计。

前 15 根 K 线作为指标预热区，生命周期从第 16 根开始逐日回放。少于 15 根有效日 K 的股票不写入本次结果。

### 2.2 计算的基础指标

- MA5、MA10、MA20、MA30、MA60；
- TR 与 ATR20：`TR = max(H-L, abs(H-C前一日), abs(L-C前一日))`，`ATR20 = 最近20日 TR 的算术平均`；
- 收盘价站上 MA5/10/20/30 的数量 `retake_count`；
- 连续站上至少 3 根均线的天数 `days_retake_3ma`；
- 最近 10 日均线交叉对数及交叉事件数；
- 均线排列 `order_score` 及其相对 5 日前的改善值；
- 当日成交额 / 最近 60 日成交额中位数 `volume_ratio`；
- 距 60 日最高价的空间 `dist_high_60`；
- 当前价上方 0%～6% 内是否存在至少两个局部高点 `overhead_resistance_flag`；
- 20 日急跌、60 日新低和 MA60 下行组成的 `structural_damage_flag`。

## 3. 三种生命周期状态

生命周期不是只看评估日一个截面，而是对读取到的 150 根 K 线逐日回放。一轮 Episode 可以失败、结束，再开始下一轮；最终输出评估日所在的最新一轮状态。

### 3.1 `PRE_FIRST_TURN`：底部准备

初始状态，或上一轮已经失效并完成结构重置后的状态。它表示当前还没有形成一轮有效的首次转强窗口。

### 3.2 `FIRST_TURN_WINDOW`：首次转强窗口

当某一日同时满足以下条件，记录首次触发日期、触发收盘价和触发时 ATR20，并进入该状态：

```text
retake_count >= 3
order_score >= 2.0
MA5 > MA10
```

此状态是 A-PreV2 的核心观察窗口。若后续失败，旧触发会被清除：

- 收盘价低于首次触发收盘价的 88%；或
- 收盘价跌破触发前阶段低点。

失败当天回到 `PRE_FIRST_TURN`，从下一根 K 线继续寻找新的触发，不沿用旧触发价。

### 3.3 `POST_FIRST_WAVE`：第一波已完成

首次触发后至少经过 5 个交易日，并且满足以下两部分：

1. 第一波上涨达到任一条件：最高收盘价相对首次触发价上涨至少 6%，或最高价相对首次触发价上涨至少 2.5 ATR；
2. 随后出现任一回撤迹象：从最高收盘价回撤至少 6%，或收盘价跌破 MA30。

进入 `POST_FIRST_WAVE` 后，不会因为一次反弹或重新站上均线就回到 PRE。只有旧一轮真正失效才允许结构重置，必须同时满足：

```text
从本轮最高价回撤 >= 25%
收盘价 < 首次触发价 * 0.92
并且满足以下任一中期破坏条件：
  连续 5 日收盘低于 MA30
  连续 3 日收盘低于 MA60
  形成新的 60 日低点
```

结构重置后清空首次触发日期、触发价、触发时 ATR、阶段高点等 Episode 变量，回到 `PRE_FIRST_TURN`，允许后续建立新一轮 Episode。单纯从高点回撤 25% 但仍高于触发价，不会触发重置。

```text
PRE_FIRST_TURN --有效触发--> FIRST_TURN_WINDOW
FIRST_TURN_WINDOW --触发失败--> PRE_FIRST_TURN
FIRST_TURN_WINDOW --第一波完成--> POST_FIRST_WAVE
POST_FIRST_WAVE --旧转向彻底失效--> PRE_FIRST_TURN
```

## 4. 七项评分规则（满分 100）

总分为七项之和，先得到 `raw_total_score`，再得到用于排序和入选的 `total_score`：

```python
raw_total_score = min(100, Base + Trans + Retake + Dir + Fresh + Vol + Space)
total_score = min(raw_total_score, 49) if retake_count == 0 else raw_total_score
```

当价格连一根核心均线都没有站住时，原始分仍保留在明细中，但正式分封顶 49，避免滞后的均线排列、巨量或历史空间把失败状态托成高分。

### 4.1 Base：背景底分（最高 15）

背景由评估日前 60 日的历史形态计算，不替代生命周期状态：

| `turn_type` | 含义 | 分数 |
| --- | --- | ---: |
| `FIRST_TURN` | 偏首次底部转向 | 15 |
| `SECONDARY_TURN` | 过去出现过至少连续 3 日站上 3 根均线，之后再次观察 | 12 |
| `CONSOLIDATION_RESTART` | 过去窗口超过 60% 的交易日收盘在 MA20 上方 | 10 |
| 其它/无法识别 | — | 5 |

### 4.2 Trans：均线状态转换（最高 25）

以 MA5/10/20/30 的均线离散度相对 ATR20 衡量压缩，并叠加收敛、结扎和杂噪：

| 条件 | 分数变化 |
| --- | ---: |
| 三均线最小跨度 / ATR20 `<= 0.51 / 0.80 / 1.20` | +15 / +10 / +5 |
| 当前跨度 / 5 日前跨度 `< 0.80 / 0.95` | +5 / +3 |
| 最近 10 日发生交叉的均线对 `>= 3 / >= 2` | +5 / +3 |
| 最近 10 日交叉事件 `>= 8 / >= 4` | -6 / -3 |

本项最后裁剪到 0～25 分。当前特征层未显式保存 5 日前跨度，评分引擎使用 `当前跨度 * 1.2` 的默认值，因此通常对应 +3 的收敛分；这是当前实现事实。

### 4.3 Retake：价格夺回成本区（最高 15）

| 收盘价站上的均线数 | 分数 |
| ---: | ---: |
| 4 根 | 15 |
| 3 根 | 10 |
| 2 根 | 5 |
| 0～1 根 | 0 |

若连续站上至少 3 根均线超过 3 天，再扣 5 分，最低为 0。

### 4.4 Dir：方向性重排（最高 15）

`order_score` 由 `MA5 > MA10`、`MA5 > MA20`、`MA10 > MA20` 各 1 分，`MA20 > MA30` 0.5 分组成。

| 条件 | 分数变化 |
| --- | ---: |
| `order_score >= 3` | +10 |
| `order_score >= 2` | +5 |
| 相对 5 日前排列改善 `order_improvement > 0` | +5 |

### 4.5 Fresh：突破新鲜度（最高 10）

只有 `retake_count >= 3` 且连续站上 3 根均线至少 1 天时才计分：

| 连续站上 3MA 天数 | 分数 |
| ---: | ---: |
| 1～2 天 | 10 |
| 3～5 天 | 7 |
| 6～10 天 | 4 |
| 超过 10 天 | 1 |
| 未达到 3 根均线 | 0 |

### 4.6 Vol：成交量确认（最高 10）

`volume_ratio = 当日成交额 / 最近 60 日成交额中位数`：

| `volume_ratio` | 分数 |
| ---: | ---: |
| `>= 1.5` | 10 |
| `>= 1.1` | 6 |
| `>= 0.8` | 4 |
| `< 0.8` | 2 |

当前实现只判断成交额是否放大，尚未区分上涨放量和下跌放量，因此 Vol 分不能单独解释为上涨确认。

### 4.7 Space：空间与位置延伸（最高 10）

`extensionATR = (close - MA20) / ATR20`：

| 条件 | 分数变化 |
| --- | ---: |
| `extensionATR <= 1.0 / 1.5 / 2.0` | +5 / +3 / +1 |
| `dist_high_60 >= 8% / >= 4%` | +5 / +3 |
| 未达到上述空间条件且没有近端阻力 | +2 |

本项最高裁剪为 10 分。它表达的是“上方空间”，不是当前趋势强度；股价下跌得越远，空间分可能越高，所以必须结合 Retake、Fresh 和生命周期一起看。

## 5. 正式入选与兼容字段

正式入选条件只有：

```python
selected = turn_episode_state == "FIRST_TURN_WINDOW" and total_score >= 75
```

`state` 是当前主状态，只取三种生命周期值。数据库中仍保留 `signal_status`、`entry_extension_state` 等旧字段供历史数据和界面兼容，但它们不覆盖生命周期，也不放宽正式入选条件。

`is_overextended` 只表达当前位置风险，不会取消已经满足的正式入选。以下任一条件会标记位置偏离：`extensionATR > 2.0`、相对 MA20 偏离超过 18%、当日涨幅达到 15%。

## 6. 运行与落库

全市场批次从 `screening_asset_master` 中读取全部 `asset_type='stock'` 标的，不内置样本数量限制。每次运行创建独立 `early_turn_run`，逐只写入 `early_turn_result`，保存：

- `total_score`、`raw_total_score`、`selected`；
- `state`、`turn_episode_state`、首次触发日期/价格；
- `features_json`、`score_detail_json`、`reasons_json`；
- `structural_damage_flag`、`entry_extension_state`、`is_overextended`。

单股测试使用同一套 `EarlyTurnService` 和 `EarlyTurnEngine` 逐日重算，因此单股测试与批量选股不是两套评分逻辑。单股 K 线图、批次列表和历史诊断只是不同展示入口。

## 7. 维护与校验要求

策略改动后至少复核：

1. 全市场评估总量与有效日线缺失数量；
2. 三种生命周期状态分布及正式入选数量；
3. 触发失败、第一波完成、POST 结构重置等状态迁移样例；
4. `raw_total_score`、封顶后的 `total_score` 与七项明细能否相互解释；
5. 关键股票的底层 K 线、复权因子、特征和落库结果是否一致。

评分阈值、生命周期阈值、复权口径、历史窗口或默认值都属于策略规则变更，修改前应先确认并补充回归验证。仓库中暂未展示的其它策略代码不因界面只开放 A-PreV2 而删除。
