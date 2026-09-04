# 市场全景（Market Panorama）功能设计与 AI 提示词方案 V1.0

> 适用项目：个人交易决策支持系统 / A股每日复盘模块  
> 目标读者：AI Coder / 后端开发 / 前端开发 / 提示词工程  
> 文档性质：可直接据此开发的功能设计、数据结构、AI 工作流与提示词规范  
> 核心定义：**市场全景不是“历史摘要”，而是最近一段时间的滚动市场状态机 / 当前作战地图。**

---

# 1. 设计结论

本功能不应被设计成：

> 把最近几个月所有复盘文件总结成一篇越来越长的文章。

而应被设计成：

> **基于最近 60～80 个交易日的原始复盘，维护一份结构化、可滚动更新、可定期重建的“当前市场状态”。**

推荐采用双层架构：

1. **结构化状态层**：`market_panorama_state.json`
   - 机器事实源
   - 供 AI、后端、前端和后续功能读取

2. **展示层**：`market_panorama.md`
   - 从 JSON 渲染生成
   - 供用户阅读

推荐采用两套 AI 工作流：

1. **全量重建 Prompt**
   - 输入最近约 80 个交易日原始复盘
   - 不依赖旧市场全景
   - 重新构建干净状态
   - 建议每 20 个交易日 / 每月执行一次

2. **每日增量更新 Prompt**
   - 输入昨日 `market_panorama_state.json` + 今日独立复盘
   - 给昨日所有状态“判卷”
   - 更新故事、Episode、变量、核心观察股、未决问题

核心原则：

> **每日增量保证连续性；定期全量重建防止递归摘要造成信息漂移。**

---

# 2. 功能目标

市场全景每天必须回答：

1. 当前市场总体处于什么状态？
2. 当前风险偏好高还是低？
3. 哪些“故事 / 母题 / 方向”仍然活跃？
4. 每个方向处于启动、强化、分歧、修复还是退潮？
5. 当前主要赚钱效应在哪里？
6. 当前主要亏钱效应在哪里？
7. 哪些重要变量改变了原有判断？
8. 当前资金偏好什么风格？
9. 哪些股票最有“市场传感器”价值？
10. 当前有哪些关键问题尚未得到验证？
11. 相比上一交易日，市场全景具体发生了哪些变化？

市场全景不是：

- 每日复盘拼接
- 新闻汇总
- 最近几个月全部事件时间线
- 长篇市场研究报告
- 买入推荐
- 对所有行业机械评分
- 永久递归的“摘要的摘要”

---

# 3. 时间窗口

推荐参数：

```text
detail_window_trading_days = 60
max_window_trading_days = 80
full_rebuild_interval_trading_days = 20
```

约等于：

- 20 个交易日 ≈ 1 个月
- 60 个交易日 ≈ 3 个月
- 80 个交易日 ≈ 4 个月

80 个交易日以外的信息原则上不保留，除非它是当前活跃故事必须使用的历史锚点。

原则：

> **历史只在能解释今天时存在。**

---

# 4. 核心概念：Story 与 Episode

## 4.1 Story

`story_id` 是长期稳定的“市场故事”唯一标识。

例如：

```text
AI
AI_INFRASTRUCTURE
AI_APPLICATION
AGRICULTURE
PRECIOUS_METALS
CHEMICALS
PHARMA
BROKERAGE
DIGITAL_RMB
REAL_ESTATE
```

注意：

> `story_id` 不是软件行业标签。

例如：

- AI算力可能横跨通信、电子、计算机
- 粮食安全可能横跨种业、粮食、养殖、农资
- 贵金属可能横跨采掘、资源、珠宝

Story 的本质是：

> **市场正在共同交易的一个可解释故事。**

---

## 4.2 Episode

同一个 Story 可以反复出现多轮独立行情。

例如：

```text
story_id = AGRICULTURE
```

可以存在：

```text
AGRICULTURE_20260817_01
AGRICULTURE_20260824_02
```

第一轮可能是：

> 启动 → 扩散 → 分歧 → 核心集中 → 退潮

之后因为新变量再次启动，应创建新的 Episode。

不能错误写成：

> 农业从8月17日一直持续到8月31日。

正确做法：

### Episode 1
8/17 启动 → 8/18 扩散 → 8/19 集中 → 8/21 退潮

### Episode 2
8/24 新天气变量重新启动 → 8/25 确认 → 8/27 再扩散 → 8/31 高位缩圈

**Story 负责“这是什么故事”，Episode 负责“这一轮行情”。**

---

# 5. 生命周期状态

每个当前 Episode 必须有 `lifecycle_state`。

推荐枚举：

```json
[
  "watch",
  "new_launch",
  "strengthening",
  "expanding",
  "confirmed",
  "divergence",
  "core_concentration",
  "repair",
  "re_strengthening",
  "high_level_concentration",
  "weakening",
  "retreat",
  "persistent_negative_feedback",
  "retired"
]
```

含义：

- `watch`：只有线索，尚未形成明确群体资金行为
- `new_launch`：第一日明显群体攻击
- `strengthening`：已有方向继续加强
- `expanding`：从前排扩散到更多相关分支
- `confirmed`：至少通过一次重要跨日验证
- `divergence`：明显强弱分化
- `core_concentration`：后排掉队，资金集中核心
- `repair`：前期走弱后重新修复
- `re_strengthening`：分歧/修复后重新明显强化
- `high_level_concentration`：持续较长后，高位核心仍强，后排明显掉队
- `weakening`：广度、溢价、核心承接下降
- `retreat`：主要核心补跌，本轮赚钱效应明显结束
- `persistent_negative_feedback`：连续成为主要亏钱方向
- `retired`：从 Active Story 移出

---

# 6. 只记录状态转折，不记录每日流水账

Episode 的历史不应每天新增一条。

例如农业第二轮：

```text
8/24  new_launch
新天气变量重新激活农业。

8/25  confirmed
前排继续晋级，形成跨日赚钱效应。

8/26  core_concentration
后排分化，资金集中核心。

8/27  re_strengthening
核心强，板块重新扩散。

8/31  high_level_concentration
最高核心继续，后排亏钱效应扩大。
```

即使一个方向交易 20 天，最终可能只有 5～8 个真正重要的状态节点。

---

# 7. market_panorama_state.json 顶层结构

```json
{
  "schema_version": "1.0",
  "as_of": "2026-08-31",
  "window": {},
  "market_regime": {},
  "capital_preferences": {},
  "active_stories": [],
  "watchlist_stories": [],
  "retired_stories": [],
  "key_variables": [],
  "market_turning_points": [],
  "earning_effects": {},
  "core_sensors": [],
  "open_questions": [],
  "last_update_changes": [],
  "source_files": []
}
```

---

# 8. 字段设计

## 8.1 window

```json
{
  "detail_trading_days": 60,
  "max_trading_days": 80,
  "start_date": "2026-05-08",
  "end_date": "2026-08-31"
}
```

---

## 8.2 market_regime

```json
{
  "summary": "风险偏好仍高，但板块轮动快，AI持续产生新分支，旧高位淘汰加快。",
  "risk_appetite": "high_but_selective",
  "liquidity_state": "active",
  "breadth_state": "mixed_positive",
  "market_structure": "structural_rotation",
  "trend_quality": "medium_high",
  "short_term_sentiment": "strong_but_rotating",
  "confidence": 0.82,
  "evidence": [
    "两市成交维持2万亿附近",
    "高位连板仍活跃",
    "AI应用/液冷/超节点产生新赚钱分支",
    "医药/黄金出现明显负反馈"
  ]
}
```

推荐枚举：

### risk_appetite

```text
very_low
low
neutral
medium
high
high_but_selective
extreme
```

### liquidity_state

```text
contracting
low
normal
active
expanding
```

### breadth_state

```text
broad_weakness
weak
mixed
mixed_positive
broad_strength
```

### market_structure

```text
single_mainline
mainline_plus_rotations
structural_rotation
broad_risk_on
broad_risk_off
transition
```

---

## 8.3 capital_preferences

固定跟踪：

```json
{
  "large_vs_small": {},
  "trend_vs_limitup": {},
  "high_vs_low": {},
  "growth_vs_defensive": {},
  "concentration_vs_expansion": {},
  "mainline_vs_rotation": {},
  "capacity_vs_elasticity": {}
}
```

每项结构统一：

```json
{
  "state": "balanced_but_small_caps_active",
  "recent_change": "由大小票共振转为题材和高辨识度更强",
  "evidence": [
    "科创50回落但涨停数量维持高位",
    "大量20cm和高辨识度题材继续活跃"
  ],
  "confidence": 0.76
}
```

---

## 8.4 active_stories

示例：

```json
{
  "story_id": "AGRICULTURE",
  "display_name": "农业 / 种业 / 粮食安全",
  "mother_theme": "农业与粮食安全",
  "current_episode": {
    "episode_id": "AGRICULTURE_20260824_02",
    "start_date": "2026-08-24",
    "trigger": "极端天气/厄尔尼诺预期强化农业供给扰动逻辑",
    "current_state": "high_level_concentration",
    "priority": "high",
    "confidence": 0.88,
    "status_summary": "第二轮已多次通过跨日验证，目前最高核心继续强，但后排开始掉队。",
    "state_nodes": [
      {"date":"2026-08-24","state":"new_launch","summary":"新天气变量重新激活农业。"},
      {"date":"2026-08-25","state":"confirmed","summary":"前排继续晋级，完成第一次次日确认。"},
      {"date":"2026-08-26","state":"core_concentration","summary":"广度收窄，核心继续。"},
      {"date":"2026-08-27","state":"re_strengthening","summary":"重新从核心向板块扩散。"},
      {"date":"2026-08-31","state":"high_level_concentration","summary":"最高核心继续，后排亏钱效应扩大。"}
    ],
    "core_sensors": ["万向德农","金健米业","新赛股份"],
    "positive_evidence": [],
    "negative_evidence": [],
    "next_validation": [
      "最高核心是否开始补跌",
      "后排亏钱效应是否向前排传导"
    ]
  },
  "previous_episode_anchor": "8/17第一轮启动，8/21完成退潮。"
}
```

---

## 8.5 watchlist_stories

尚未完全形成 Active Story 的方向。

```json
{
  "story_id": "REAL_ESTATE",
  "display_name": "房地产政策线",
  "reason": "政策力度大，但开发权重高开低走，仅部分服务/轻资产强。",
  "status": "watch",
  "promotion_condition": [
    "服务核心继续获得溢价",
    "开发容量股开始止跌并参与"
  ],
  "drop_condition": [
    "高弹性前排次日也大幅负反馈"
  ]
}
```

---

## 8.6 retired_stories

只保留近期有参考价值的退潮方向。

```json
{
  "story_id": "PHARMA",
  "display_name": "医药 / 创新药",
  "retired_date": "2026-08-31",
  "last_episode_id": "PHARMA_20260820_01",
  "retire_reason": "高辨识度核心与高价格反应股票连续制造亏钱效应。",
  "reactivation_condition": [
    "核心止跌",
    "板块广度恢复",
    "出现新产业/政策变量并得到群体响应"
  ],
  "historical_anchor": "8/20 mRNA高潮，之后反复分歧与短暂修复，8/31退潮进一步确认。"
}
```

建议只保留最近 5～15 个重要 retired story。

---

## 8.7 key_variables

变量必须真正改变市场理解。

```json
{
  "variable_id": "VAR_20260831_AI_APPLICATION",
  "date": "2026-08-31",
  "scope": "story",
  "story_id": "AI_APPLICATION",
  "importance": "high",
  "prior_expectation": "8/28 AI应用刚启动，尚未证明持续性。",
  "actual_result": "AI长剧事件驱动AI应用大面积涨停并扩散至IP、语料、文生视频。",
  "interpretation": "AI应用获得跨交易日确认。",
  "priority_change": {
    "up": ["AI_APPLICATION"],
    "down": [],
    "unchanged": ["AI"]
  },
  "next_validation": [
    "应用端前排能否继续有溢价",
    "容量软件核心能否保持承接"
  ]
}
```

建议最多保留最近 10～20 个关键变量。

禁止每天机械凑固定数量。

---

## 8.8 market_turning_points

只记录真正的市场级转折。

```json
{
  "date": "2026-08-19",
  "name": "市场级风险释放",
  "from": "结构轮动",
  "to": "风险偏好急剧下降",
  "summary": "大量股票下跌，成长与高位同时释放风险。"
}
```

建议保留最近 5～10 个。

---

## 8.9 earning_effects

```json
{
  "positive": [
    {"name":"AI应用","strength":"strong","reason":"跨交易日确认并大面积扩散"},
    {"name":"液冷","strength":"strong","reason":"经历分歧后重新扩散"}
  ],
  "negative": [
    {"name":"医药","strength":"very_strong_negative","reason":"核心批量跌停/大跌"},
    {"name":"贵金属","strength":"strong_negative","reason":"前趋势核心出现大面积负反馈"}
  ]
}
```

---

## 8.10 core_sensors

建议总量始终保持 10～20 只。

每只必须有角色：

```json
{
  "symbol": "600371",
  "name": "万向德农",
  "story_id": "AGRICULTURE",
  "episode_id": "AGRICULTURE_20260824_02",
  "role": "第二轮高度核心",
  "why_watch": "判断农业高位缩圈是否继续穿越",
  "if_strong_means": "农业第二轮仍有核心承接",
  "if_weak_means": "农业退潮概率明显提高",
  "status": "active"
}
```

删除条件：

- 已失去当前信息价值
- 所属故事已 retired
- 角色已被新核心替代
- 连续多个交易日不再代表重要判断

核心观察股不是买入建议。

---

## 8.11 open_questions

这是每日增量更新最重要的入口。

```json
{
  "question_id": "Q_20260831_01",
  "created_date": "2026-08-31",
  "question": "AI应用今天的大高潮能否获得次日正反馈？",
  "related_story_ids": ["AI_APPLICATION"],
  "validation_signals": {
    "positive": ["前排继续有溢价","应用容量股稳定","板块仍有扩散"],
    "negative": ["涨停股普遍大幅低开","板块广度迅速消失"]
  },
  "status": "open"
}
```

后续可变更为：

```text
confirmed_positive
confirmed_negative
mixed
unresolved
```

每日 AI 首先要拿今日复盘回答昨日 `open_questions`。

---

## 8.12 last_update_changes

每次增量更新必须明确输出：

```json
[
  {
    "type": "story_upgrade",
    "target": "AI_APPLICATION",
    "from": "new_launch",
    "to": "confirmed",
    "reason": "跨交易日继续大面积扩散"
  },
  {
    "type": "story_downgrade",
    "target": "PRECIOUS_METALS",
    "from": "strong_trend",
    "to": "serious_negative_feedback",
    "reason": "核心批量跌停"
  }
]
```

前端可直接渲染“今日全景发生了什么变化”。

---

# 9. market_panorama.md 展示结构

Markdown 必须由 JSON 渲染，不作为唯一数据源。

固定结构：

## 1. 当前市场一句话
最多 2～4 句。

## 2. 当前市场状态
- 风险偏好
- 流动性
- 市场广度
- 短线情绪
- 当前结构

## 3. 当前资金偏好

| 维度 | 当前状态 | 最近变化 | 主要证据 |
|---|---|---|---|
| 大/小 | | | |
| 趋势/连板 | | | |
| 高/低 | | | |
| 成长/防御 | | | |
| 集中/扩散 | | | |
| 主线/轮动 | | | |

## 4. Active Stories 总表

| 故事 | 当前Episode | 当前状态 | 优先级 | 最近变化 | 核心观察 |
|---|---|---|---|---|---|

## 5. Active Story 详情
每个 Story 统一模板：

- 当前 Episode
- 本轮起点
- 当前状态
- 最近关键状态节点
- 当前核心
- 正向证据
- 负向证据
- 下一验证

## 6. 当前主要赚钱效应
只保留 3～6 个。

## 7. 当前主要亏钱效应

## 8. 最近关键变量
最多 10～20 个，按时间倒序。

## 9. 近期市场状态转折时间线
只保留大节点。

## 10. 核心观察股
10～20只。

## 11. 当前未决问题
3～7 个。

## 12. 近期退潮 / 暂时退出观察
简短。

## 13. 本次更新相较上一版
必须列出：

- 新增
- 升级
- 降级
- 状态切换
- Retired
- 核心观察股增删

---

# 10. 每日增量更新流程

每日更新顺序固定：

## Step 1：读取昨日 Open Questions

用今日复盘给每个问题判卷：

```text
confirmed_positive
confirmed_negative
mixed
unresolved
```

## Step 2：更新所有 Active Stories

对每个 Story 回答：

1. 昨天处于什么状态？
2. 如果状态继续，今天按理应该怎样？
3. 今天实际怎样？
4. 是否出现改变理解的新变量？
5. lifecycle_state 应升级、降级还是不变？
6. priority 应如何变化？
7. 下一步验证是什么？

## Step 3：识别新 Story

只有满足明显群体资金行为、有共同故事，而不是单一个股行情时才创建。

## Step 4：识别新 Episode

旧 Story 已 retreat / retired，后续因全新变量再次形成群体攻击时，必须新建 Episode。

## Step 5：关闭 / 退休方向

核心补跌、广度消失、连续负反馈、失去当前信息价值时：

```text
active → retired
```

## Step 6：更新 Key Variables

只保留真正改变方向优先级的变量。

## Step 7：更新 Capital Preferences

只在证据足够时修改。

## Step 8：更新 Core Sensors

总量保持 10～20。

## Step 9：生成新 Open Questions

只来自当前最重要的不确定性。

## Step 10：生成 last_update_changes

## Step 11：Schema 校验

## Step 12：渲染 Markdown

---

# 11. 全量重建流程

输入最近 60～80 个交易日所有原始独立复盘。

**不要读取旧全景作为事实来源。**

流程：

1. 按日期排序
2. 提取市场级状态
3. 提取 Story
4. 合并同 Story
5. 识别不同 Episode
6. 生成关键 State Nodes
7. 识别已结束 Episode
8. 识别当前 Active Episode
9. 生成市场转折
10. 生成 Capital Preferences
11. 生成赚钱/亏钱效应
12. 生成 Core Sensors
13. 生成 Open Questions
14. 输出 JSON
15. 渲染 Markdown

---

# 12. Prompt A：市场全景全量重建

```text
你是一名专业的A股市场复盘分析器。

你的任务不是总结所有日报，也不是把多份复盘压缩成长文章，而是根据我提供的最近一段时间的原始A股独立复盘文件，重新构建一份“当前市场全景状态”。

【核心目标】

市场全景必须回答：
1. 当前市场处于什么状态？
2. 当前主要资金偏好是什么？
3. 哪些市场故事仍然活跃？
4. 每个活跃故事当前处于哪一轮 Episode？
5. 每个 Episode 当前处于启动、强化、扩散、分歧、核心集中、修复、高位缩圈、退潮等哪个阶段？
6. 当前主要赚钱效应与亏钱效应在哪里？
7. 最近哪些关键变量真正改变了市场判断？
8. 当前哪些股票最适合作为市场“观察传感器”？
9. 当前有哪些关键问题仍待下一交易日验证？

【非常重要】

你不是做时间流水账。
不要逐日复述复盘内容。
只保留：
- 市场状态转折
- Story / Episode 状态转折
- 真正重要的关键变量
- 当前仍有用的历史锚点

【Story 与 Episode】

Story 是长期稳定故事，例如：
AI
AI_INFRASTRUCTURE
AI_APPLICATION
AGRICULTURE
PRECIOUS_METALS
PHARMA
CHEMICALS

同一个 Story 可以有多轮独立行情。

如果某故事已经退潮，后来因为新的变量重新被资金激活，必须创建新的 Episode，而不是认为旧行情一直延续。

例如：
AGRICULTURE_20260817_01
AGRICULTURE_20260824_02

【生命周期枚举】
watch
new_launch
strengthening
expanding
confirmed
divergence
core_concentration
repair
re_strengthening
high_level_concentration
weakening
retreat
persistent_negative_feedback
retired

【状态节点规则】

不要每天生成状态节点。
只在发生真正状态变化时记录。

【Active Story】

只保留当前仍然影响市场判断的方向。

【Retired Story】

已经失去赚钱效应、核心补跌、连续负反馈或当前不再重要的方向放入 retired_stories。
只保留最近仍有参考价值的退潮方向，不要无限累计。

【关键变量】

变量不是“某板块今天涨3%”。
变量必须满足：

按照前一状态，本来今天应该____；
实际却____；
所以对市场/方向的理解从____调整为____。

只保留真正重要的变量，不要每天机械凑数量。

【资金偏好】

固定判断：
- 大票 / 小票
- 趋势 / 连板
- 高位 / 低位
- 成长 / 防御
- 集中 / 扩散
- 主线 / 轮动
- 容量 / 高价格反应

不知道时允许写不确定，不强行分类。

【核心观察股】

总量保持10～20只。
每只必须回答：
- 属于哪个 story / episode
- 当前角色
- 为什么观察
- 强意味着什么
- 弱意味着什么

核心观察股不是买入建议。

【Open Questions】

必须生成当前最重要、尚未得到答案的市场问题。
问题必须可在后续交易日被市场判卷。

【时间窗口】

详细分析最近60个交易日。
必要时可回看最多80个交易日。
80个交易日以外的信息原则上不保留，除非是当前活跃故事必要的历史锚点。

【输出】

只输出严格合法的 JSON，结构必须符合系统给定的 MarketPanoramaState Schema。

禁止：
- Markdown 混入 JSON
- JSON 后附解释
- 自己发明 schema 字段
- 将缺少证据的推断写成事实
- 把退潮后的新启动错误并入旧 Episode
- 将软件行业标签直接等同于市场 Story
- 无限累计故事、核心股、变量

输出必须代表“当前作战地图”，而不是历史百科全书。
```

---

# 13. Prompt B：每日市场全景增量更新

```text
你是一名专业的A股市场状态更新器。

我将提供：
1. 昨日 market_panorama_state.json
2. 今日 A股独立复盘文件

你的任务不是重新写一篇今日复盘，也不是简单把今日内容追加到旧全景。

你的任务是：
“拿今天的市场，给昨天的所有状态和未决问题判卷，然后更新市场全景状态。”

【更新顺序必须严格执行】

第一步：先处理昨日 open_questions。
对每个问题判断：
- confirmed_positive
- confirmed_negative
- mixed
- unresolved
并把结果写回相关 Story / Episode / Variable。

第二步：检查所有 active_stories。
对每个故事回答：
1. 昨天处于什么状态？
2. 如果这个状态继续，今天按理应该怎样？
3. 今天实际怎样？
4. 今天是否出现改变理解的新变量？
5. lifecycle_state 应升级、降级还是不变？
6. priority 应如何变化？
7. 下一步验证条件是什么？

第三步：识别新 Story。
仅在出现明显群体资金行为、有明确共同故事、且不是单一个股行情时创建。

第四步：识别是否需要新 Episode。
如果某 Story 的上一 Episode 已 retreat / retired，而今天因新的变量重新形成群体攻击，必须创建新的 Episode。
绝对不要把新行情错误接到旧 Episode 后面。

第五步：检查是否应该 retired。
如果：
- 核心补跌
- 广度消失
- 连续负反馈
- 已经失去当前信息价值
则将 story / episode 从 active 移入 retired。

第六步：更新 key_variables。
变量必须遵循：
前期状态
→ 按理今天应该怎样
→ 实际怎样
→ 资金态度发生什么变化
→ 哪些方向优先级提高/降低
→ 下一步怎么验证

禁止把普通涨跌当变量。

第七步：更新 capital_preferences。
只在有足够证据时修改。
不要因为单日偶然波动就大幅改变长期判断。

第八步：更新 core_sensors。
总量保持10～20只。
删除已经失去信息价值的旧观察股。
新增股票必须有明确角色。

第九步：生成新的 open_questions。
只生成当前最重要、下一交易日能够被市场验证的问题。

第十步：生成 last_update_changes。
必须明确列出：
- 新增 story / episode
- 升级
- 降级
- 状态变化
- retired
- 观察股增删
- 关键偏好变化

【非常重要】

不得“保护昨天的判断”。
如果今天市场证伪昨日观点，必须立即更新。

也不得因为今天单日波动，就把一个长期已确认故事轻易判死。
必须区分：
- 正常分歧
- 核心集中
- 修复
- 真正退潮

【历史压缩】

不要把今日内容机械追加成时间流水账。
只有状态变化时才新增 state_node。
如果 lifecycle_state 没有真正变化，可以只更新 evidence、confidence、next_validation。

【输出】

只输出符合 MarketPanoramaState Schema 的严格 JSON。
不要输出 Markdown。
不要输出解释。
不要自创字段。
```

---

# 14. Markdown 渲染 Prompt

建议状态更新与 Markdown 渲染拆开。

```text
你是一名市场状态报告渲染器。

输入是 market_panorama_state.json。

你的任务只是把结构化状态渲染成清晰、紧凑、易读的 market_panorama.md。

不得重新推理市场。
不得改变 JSON 中的状态、优先级和因果判断。
不得新增 JSON 中不存在的重要事实。

固定输出结构：
1. 当前市场一句话
2. 当前市场状态
3. 当前资金偏好
4. Active Stories 总表
5. Active Story 详情
6. 当前主要赚钱效应
7. 当前主要亏钱效应
8. 最近关键变量
9. 近期市场状态转折
10. 核心观察股
11. 当前未决问题
12. 近期退潮 / 暂时退出观察
13. 本次更新相较上一版

要求：
- 不写历史流水账
- 不重复
- 当前信息优先
- 历史只作为必要锚点
- 控制篇幅
```

---

# 15. 为什么 JSON → Markdown，而不是 Markdown → Markdown

如果每天直接：

```text
昨日 market_panorama.md
+
今日复盘.md
→
新 market_panorama.md
```

长期容易出现：

1. 语义漂移
2. 日期丢失
3. Episode 合并错误
4. 旧观察股删不掉
5. 变量被摘要化后失去原始逻辑
6. 推断逐渐被写成事实

所以：

> **JSON 是状态事实层，Markdown 是展示层。**

---

# 16. 全量重建调度

系统维护：

```text
last_full_rebuild_date
last_full_rebuild_trading_day_index
```

触发条件：

```text
距离上次全量重建 >= 20个交易日
OR 用户手动点击“重建市场全景”
OR 检测到 panorama_state 连续异常
```

异常包括：

- Active Story > 15
- Core Sensor > 25
- Open Questions > 12
- 某 Episode 状态节点 > 15
- Story 名称重复但 ID 不同
- 同一 Story 同时存在两个 active episode
- 状态与最近复盘严重不一致

---

# 17. 数据清理规则

推荐数量：

```text
Active Story：3～8个，极端最多10个
Watch Story：0～5个
Retired Story：5～15个
Key Variables：10～20个
Core Sensors：10～20只
Open Questions：3～7个
```

如果超出，AI 应重新压缩。

---

# 18. Story 去重与别名

建议维护：

```text
story_aliases.json
```

例如：

```json
{
  "AI_INFRASTRUCTURE": ["AI算力","AI硬件","算力硬件","人工智能基础设施"],
  "AGRICULTURE": ["农业","种业","粮食安全","大农业"]
}
```

AI 提出新 Story 后：

1. 先做 alias 匹配
2. 再做语义相似度
3. 再决定是否真正创建新 Story

避免把“AI算力 / AI硬件 / 算力基础设施 / CPO+AI”建成多个长期重复 Story。

---

# 19. 母题与分支关系

支持：

```json
{
  "story_id": "AI_APPLICATION",
  "parent_story_id": "AI"
}
```

例如：

```text
AI
├── AI_INFRASTRUCTURE
│   ├── CPO
│   ├── LIQUID_COOLING
│   ├── PTFE
│   ├── SUPERNODE
│   └── STORAGE_HBM
└── AI_APPLICATION
    ├── AI_VIDEO
    ├── AI_SOFTWARE
    └── AI_SECURITY
```

但不要无限做知识图谱。
只有市场确实把某分支作为独立可交易方向时才建立子 Story。

---

# 20. Confidence 与 Evidence

所有重要判断建议有：

```text
confidence: 0 ~ 1
```

参考：

```text
0.90+ 高度确定
0.75  较明确
0.60  有一定证据
0.50  混合
<0.50 不应形成强结论
```

Evidence 建议区分：

```json
{
  "confirmed_facts": [],
  "market_interpretation": [],
  "inference": []
}
```

这样避免 AI 把推断逐渐变成事实。

---

# 21. 状态升级 / 降级基本规则

## new_launch → confirmed
通常至少满足：
- 第二交易日仍有前排正反馈
- 板块广度仍存在
- 不是只剩一只股票

## confirmed → strengthening / expanding
- 前排继续强
- 后排扩散
- 新分支加入
- 容量股参与

## strengthening → divergence
- 前排强
- 后排明显掉队
- 广度收缩

## divergence → core_concentration
- 只剩少数高辨识度核心
- 后排开始亏钱

## divergence → re_strengthening
- 前排重新强化
- 板块广度恢复

## core_concentration → retreat
- 最前排也开始补跌
- 参与者普遍负反馈
- 板块不再产生新核心

---

# 22. 增量更新防漂移机制

建议程序增加硬校验：

### 校验1
Retired Episode 不能直接恢复 Active；必须创建新 Episode。

### 校验2
同一 Story 同时只能有 0 或 1 个 Active Episode。

### 校验3
`retreat → strengthening` 不能无理由直接跳跃。
必须：
- 要么先 repair
- 要么新建 Episode

### 校验4
`core_sensors > 20` 时要求二次压缩。

### 校验5
`active_stories > 10` 时要求 AI 重新判断哪些只是日内轮动。

### 校验6
正常增量更新时，历史已关闭 state_node 默认只读。
只有明确 `historical_correction` 才能修改旧历史。

---

# 23. 失败与降级保护

如果 AI 返回 JSON 不合法：

1. 不覆盖旧 state

---

2. 自动重试一次
3. 第二次仍失败：
   - 保存今日日报
   - 标记 `panorama_update_failed`
   - 等待人工或下次全量重建

绝不能用坏 JSON 覆盖昨日正常状态。

---

# 24. 每日快照

每日成功后保存：

```text
market_panorama_state_2026-08-31.json
market_panorama_2026-08-31.md
```

同时维护：

```text
market_panorama_state.json
market_panorama.md
```

用于：

- 历史回看
- diff
- 调试 AI
- 回滚

---

# 25. 推荐 AI 调用拆分

## Step A：状态更新
输入：
- old state JSON
- today review

输出：
- new JSON

建议 temperature：

```text
0.1 ~ 0.3
```

## Step B：Markdown 渲染
建议 temperature：

```text
0.2 ~ 0.4
```

不要让一个模型调用同时：

> 读大量历史 + 推理状态 + 写JSON + 写长文 + 做前端摘要

任务越混越容易出错。

---

# 26. 前端展示建议

## 第一屏

### 当前市场一句话

### 市场状态卡
- 风险偏好
- 流动性
- 广度
- 短线情绪

### 今日变化

直接展示：

```text
AI应用  ↑ 新启动 → 确认
农业    ↓ 再强化 → 高位缩圈
黄金    ↓ 趋势强 → 严重负反馈
医药    ↓ 分歧 → 退潮
化工    ↑ 新启动 → 次日确认
```

## 第二屏
Active Stories 总表。

## 第三屏
Story 详情：

> AI → 当前 Episode → 状态节点 → 核心观察 → 下一验证

## 第四屏
Core Sensors + Open Questions。

## 底部
- Retired Stories
- 市场转折时间线
- 最近80交易日历史

---

# 27. 建议数据库表

```text
market_panorama_snapshot
market_story
market_story_episode
market_story_state_node
market_variable
market_core_sensor
market_open_question
market_turning_point
```

### market_story

```text
story_id
display_name
parent_story_id
created_at
status
```

### market_story_episode

```text
episode_id
story_id
start_date
end_date
trigger
current_state
priority
confidence
```

### market_story_state_node

```text
id
episode_id
trade_date
state
summary
evidence_json
```

### market_variable

```text
variable_id
trade_date
scope
story_id
importance
prior_expectation
actual_result
interpretation
priority_change_json
next_validation_json
```

---

# 28. 验收测试

## Case 1：正常延续
昨日农业 `new_launch`；今日前排继续涨、板块仍扩散。

预期：

```text
confirmed
```

## Case 2：启动失败
昨日固态电池 `new_launch`；今日核心低开、广度消失。

预期：

```text
weakening / watch
```

不能继续 strengthening。

## Case 3：旧故事重新启动
旧 Episode 已 retired，新天气变量重新形成群体攻击。

预期：

```text
创建新的 episode_id
```

禁止恢复旧 Episode。

## Case 4：强分歧但核心还活
后排大跌、最高核心继续强。

预期：

```text
core_concentration
```

不能直接 retreat。

## Case 5：核心补跌
前一日 core_concentration；今日最高核心也跌停、广度消失。

预期：

```text
retreat
```

## Case 6：市场级变量
前一天缩量修复；今日大面积下跌、成长与高位同时崩。

预期：

- market_regime 降级
- 创建 market_turning_point
- 相关 open question 判 negative

---

# 29. 功能验收标准

V1 达到以下标准即可认为可用：

### 数据正确性
- Story 不明显重复
- Episode 能正确拆分
- 历史节点不每天被重写
- Active Story 数量受控
- 退潮方向能被清理

### 连续性
- 今日能回答昨日 Open Questions
- 每个故事能看到完整生命周期
- 每日更新能明确说明 changed what

### 防漂移
- 每20交易日可全量重建
- 全量重建不依赖旧全景
- 新旧 state 可做 diff

### 可读性
用户打开页面后：

> 30秒知道当前市场是什么状态。

3分钟知道：

> 当前主要方向、赚钱效应、亏钱效应、关键核心和下一步验证。

---

# 30. 推荐开发顺序

## Phase 1：最小可用版本
实现：
- market_panorama_state.json
- Story / Episode
- lifecycle state
- active / retired stories
- key variables
- core sensors
- open questions
- 每日增量 Prompt
- Markdown 渲染

## Phase 2：全量重建
实现：
- 最近80交易日读取
- 全量重建 Prompt
- 每20交易日自动执行
- diff
- 快照 / 回滚

## Phase 3：数据库与前端
实现：
- Story 页面
- Episode 状态节点
- 资金偏好
- Core Sensor 页面
- Open Questions
- 今日变化卡片

## Phase 4：优化
可增加：
- story alias 自动合并
- 向量相似度去重
- 自动检测摘要漂移
- 状态历史图
- AI 判断置信度
- 人工纠正后锁定字段
- 全量重建与增量状态差异报告

---

# 31. 最终设计原则

整个市场全景功能始终遵守：

1. **市场全景是当前作战地图，不是历史百科全书。**
2. **Story 是故事，Episode 是这一轮行情。**
3. **只记录状态转折，不记录每日流水账。**
4. **今日市场必须给昨日判断判卷。**
5. **变量是改变理解的新证据，不是普通涨跌。**
6. **核心观察股是传感器，不是推荐股票。**
7. **允许“不确定”，不要强行分类。**
8. **增量更新保证连续性，全量重建防止长期漂移。**
9. **JSON 是事实状态层，Markdown 是展示层。**
10. **历史只在能解释今天时存在。**

---

# 32. AI Coder 最终开发任务清单

请据此完成：

1. 定义 `MarketPanoramaState` JSON Schema。
2. 建立 Story / Episode / State Node 数据模型。
3. 实现每日独立复盘导入。
4. 实现 Incremental Panorama Update AI 调用。
5. 实现 JSON Schema 校验。
6. 实现增量更新失败保护。
7. 实现 Markdown 渲染。
8. 实现每日 Snapshot。
9. 实现每20交易日全量重建。
10. 实现最近60日详细、最多80日原始复盘窗口。
11. 实现 Active / Watch / Retired Story 管理。
12. 实现 Story Alias 去重。
13. 实现 Core Sensor 数量约束。
14. 实现 Open Question 判卷。
15. 实现 `last_update_changes`。
16. 实现前端“当前市场 / Active Stories / 核心观察 / 未决问题 / 今日变化”页面。
17. 提供全量重建和每日增量两份 Prompt 配置。
18. 所有 AI 输出先经过 Schema 校验后才能覆盖当前状态。

最终效果应是：

> 每天导入一份独立复盘，系统自动把“昨天的市场全景”更新成“今天的市场全景”，而不是重新生成一篇失去历史连续性的摘要。

并且在几个月、一两年持续使用后：

> 市场全景仍然保持简洁、准确、有状态连续性，不会因为复盘文件越来越多而失控。
