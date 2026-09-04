# 项目协作规则

## MyQuant / 国投证券掘金开发规则

本项目已安装 repo-scoped `myquant-dev` Skill：`.agents/skills/myquant-dev/`。

当任务涉及 MyQuant、掘金量化、国投证券掘金、`gm.api`、Broker Node、`MODE_LIVE`、行情订阅、账户、资金、持仓、订单、成交、交易回调、错误码或 MyQuant 策略时：

1. 必须优先使用 `myquant-dev` Skill，并按需读取 `.agents/skills/myquant-dev/references/` 中的相关文档；不得根据模型记忆猜测函数签名、枚举值、对象字段或回调名称。
2. 如果 Skill 没有自动激活，先读取 `.agents/skills/myquant-dev/SKILL.md` 和相关 references，再实现代码。
3. 需要策略范例时，可搜索 `vendor/myquant-strategy/`；该目录仅作为官方示例库，不能覆盖 SDK 定义。
4. 生产交易事实优先级为：国投证券当前 gm 3.0.186 实机验证结果 > 本项目验证文档和测试 > myquant-dev references > 官方策略范例 > 模型记忆。
5. 如果 Skill 文档与国投实机结果冲突，不得擅自覆盖实机结论；必须报告冲突并以实机结果作为当前实现依据。
6. 修改真实交易关键路径前，说明实际查阅的本地 MyQuant 文档文件。
7. 不得因为 MyQuant 通用 SDK 支持某能力，就假定国投券商版已经开放；关键能力必须有国投实机验证。
