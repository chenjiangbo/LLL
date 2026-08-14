# A-PreV2 候选股二次评价与 AI 深度研究系统 V1.0 完整性覆盖率报告

> 本文档对应《A-PreV2_候选股二次评价与AI深度研究系统_完整开发说明_V1.0.md》第 72 节 Checklist，逐条核对交付状态。

---

## 逐项自检清单

| 序号 | 检查项 | 交付状态 | 文件路径 | 核心函数/组件 | 测试与验证方式 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | A-PreV2 结果可进入二次评价 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_single_secondary_candidate` | API 接口与单元测试已验证 |
| 2 | 可选择任意历史日期 | `IMPLEMENTED` | `backend/screening/storage.py` | `get_candidate_secondary_list` | 单元测试 & API 端点已验证 |
| 3 | Company Evidence 已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_company_evidence` | 单元测试覆盖 |
| 4 | 收入/归母/扣非/现金流同比已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_company_evidence` | `test_financial_loss_state_transitions` 覆盖 |
| 5 | 亏损收窄/扩大/扭亏/转亏逻辑已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `_determine_profit_state` | `test_financial_loss_state_transitions` 覆盖 |
| 6 | 业绩预告已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_company_evidence` | 单元测试已覆盖 |
| 7 | 财务 Point-in-Time 已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_company_evidence` | 强制 `ann_date <= as_of_date` 校验 |
| 8 | Relative Leadership 已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_relative_leadership` | 单元测试覆盖 |
| 9 | 申万历史成员 Point-in-Time 已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_relative_leadership` | SQL 条件包含 PIT `in_date` / `out_date` 过滤 |
| 10 | RS5/10/20 行业内百分位已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_relative_leadership` | 百分位横截面计算函数覆盖 |
| 11 | 行业上涨事件捕获已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_relative_leadership` | `up_capture_excess` 逻辑覆盖 |
| 12 | 行业下跌抗跌已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_relative_leadership` | `down_defense_excess` 逻辑覆盖 |
| 13 | 成交参与度变化已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_relative_leadership` | `participation_change` 逻辑覆盖 |
| 14 | Evidence Insufficient 状态已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_relative_leadership` | `test_leadership_insufficient_evidence_when_bars_missing` 覆盖 |
| 15 | Supply Profile 已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_supply_profile` | `test_free_float_mv_unit_calculation` 覆盖 |
| 16 | 自由流通市值单位校验已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_supply_profile` | `test_free_float_mv_unit_calculation` 覆盖 |
| 17 | 解禁/减持等辅助标签已实现 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | `evaluate_supply_profile` | 结构化事实输出已覆盖 |
| 18 | ths_index 同步已实现 | `IMPLEMENTED` | `backend/screening/ths_concept_service.py` | `sync_ths_concepts` | 接口调用与数据表映射 |
| 19 | ths_member 多对多映射已实现 | `IMPLEMENTED` | `backend/screening/ths_concept_service.py` | `sync_ths_concepts` | `ths_concept_member_snapshot` 数据表 |
| 20 | 概念快照历史存储已实现 | `IMPLEMENTED` | `backend/screening/ths_concept_service.py` | `sync_ths_concepts` | `snapshot_date` 主键架构覆盖 |
| 21 | 历史概念时点状态已实现 | `IMPLEMENTED` | `backend/screening/ths_concept_service.py` | `get_stock_ths_concepts` | `PIT_SAFE` / `SNAPSHOT_APPROX` / `CURRENT_REFERENCE_ONLY` 标记 |
| 22 | fina_mainbz_vip 主营业务已实现 | `IMPLEMENTED` | `backend/screening/storage.py` | `stock_business_segment` | 表结构与查询支持 |
| 23 | AI 深度分析入口已实现 | `IMPLEMENTED` | `prototype/zip (2)/app/components/SecondaryEvalView.tsx` | `handleTriggerAI` | 前端按钮与批量选股支持 |
| 24 | AI 可读 A-PreV2 原始信息 | `IMPLEMENTED` | `backend/screening/ai_deep_research_service.py` | `_build_ai_research_prompt` | Prompt 结构化上下文注入 |
| 25 | AI 可读 Company Evidence | `IMPLEMENTED` | `backend/screening/ai_deep_research_service.py` | `_build_ai_research_prompt` | Prompt 结构化上下文注入 |
| 26 | AI 可读 Relative Leadership | `IMPLEMENTED` | `backend/screening/ai_deep_research_service.py` | `_build_ai_research_prompt` | Prompt 结构化上下文注入 |
| 27 | AI 可读 Supply Profile | `IMPLEMENTED` | `backend/screening/ai_deep_research_service.py` | `_build_ai_research_prompt` | Prompt 结构化上下文注入 |
| 28 | AI 可读全部 Concept Metadata | `IMPLEMENTED` | `backend/screening/ai_deep_research_service.py` | `_build_ai_research_prompt` | 全量同花顺概念输入 |
| 29 | AI 可读取历史资金复盘 | `IMPLEMENTED` | `backend/screening/ai_deep_research_service.py` | `_fetch_historical_market_reviews` | 限制 `review_date <= as_of_date` |
| 30 | 历史复盘 strictly <= as_of_date | `IMPLEMENTED` | `backend/screening/ai_deep_research_service.py` | `_fetch_historical_market_reviews` | SQL 包含 `trade_date <= as_of_date` 断言 |
| 31 | AI 网络检索已实现并可标来源 | `IMPLEMENTED` | `backend/screening/ai_deep_research_service.py` | `run_ai_stock_research` | 支持 WebSearch 与 `[事实]` / `[推理]` 标签 |
| 32 | 历史网络检索防未来信息已实现 | `IMPLEMENTED` | `backend/screening/ai_deep_research_service.py` | `_build_ai_research_prompt` | 严格限制 publish_date <= as_of_date |
| 33 | AI 概念真实性验证已实现 | `IMPLEMENTED` | `backend/screening/ai_deep_research_service.py` | `_call_llm_for_research` | 核心/重要/布局/交易属性/弱相关五级分类 |
| 34 | AI 不输出伪精确主题相关度分 | `IMPLEMENTED` | `backend/screening/ai_deep_research_service.py` | `_call_llm_for_research` | 输出分类与 Markdown 文本，绝无主观打分 |
| 35 | AI 输出高/中/低/证据不足研究优先级 | `IMPLEMENTED` | `backend/screening/ai_deep_research_service.py` | `_call_llm_for_research` | 4 级研究优先级枚举输出 |
| 36 | AI 明确正面证据、反证、不确定性 | `IMPLEMENTED` | `backend/screening/ai_deep_research_service.py` | `_call_llm_for_research` | 结构化章节规范 |
| 37 | AI 结果历史存档已实现 | `IMPLEMENTED` | `backend/screening/storage.py` | `ai_stock_research` | 表结构与查询支持 |
| 38 | AI 分析过期状态已实现 | `IMPLEMENTED` | `backend/screening/storage.py` | `ai_stock_research` | `status` 包含 `STALE` 机制 |
| 39 | 人工研究清单已实现 | `IMPLEMENTED` | `backend/screening/storage.py` | `user_research_watchlist` | 表结构与界面交互支持 |
| 40 | 用户状态不会被 AI 覆盖 | `IMPLEMENTED` | `backend/screening/storage.py` | `user_research_watchlist` | 独立的数据库持久化更新策略 |
| 41 | 所有底层指标可查看 | `IMPLEMENTED` | `prototype/zip (2)/app/components/SecondaryStockDetailDrawer.tsx` | 7-Tab 细节抽屉 | 前端展示全部底层计算参数 |
| 42 | 所有阈值配置化 | `IMPLEMENTED` | `backend/screening/secondary_eval_engine.py` | 常量参数提炼 | 函数输入配置化 |
| 43 | 所有数据缺失显式展示 | `IMPLEMENTED` | `prototype/zip (2)/app/components/SecondaryEvalView.tsx` | `data_capabilities` | 界面展示全部依赖与 UNKNOWN 状态 |
| 44 | 权限不足显式展示 | `IMPLEMENTED` | `backend/screening/ths_concept_service.py` | `check_data_capabilities` | `PERMISSION_BLOCKED` 状态捕获与透传 |
| 45 | 不存在静默降级 | `IMPLEMENTED` | `backend/screening/ths_concept_service.py` | `check_data_capabilities` | 显式标记阻断项而非掩盖错误 |
| 46 | 康美药业历史案例完成回归测试 | `IMPLEMENTED` | `backend/tests/test_secondary_evaluation.py` | `test_kangmei_pharmacutical_case_regression` | `pytest` 自动化单元测试 100% 验证通过 |
