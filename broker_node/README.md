# Guotou Broker Node

国投掘金 Broker Node V1.2 的正式实现。

架构：

- Broker API Service：HTTP、鉴权、命令持久化和快照读取，不导入 gm.api。
- GM Strategy Agent：由国投掘金策略环境启动，串行调用 gm.api 并写入 durable journal。
- Durable Journal：runtime/broker_node.sqlite3。
- Ephemeral Quote Cache：runtime/quote_cache.sqlite3。

当前开发阶段：Phase 5 已完成代码和本地契约测试；Phase 1、Phase 2、Phase 3 的关键仿真链路已通过 Windows 实机验收。Phase 6-12 中依赖交易时段、专用仿真账户或实盘权限的项目仍按验收清单保留为待测。

生产代码不得使用 gmtrade、xtquant、伪造券商事实或隐藏 fallback。

Phase 6 实盘只读验证使用 `config/config.live.example.json`，复制为独立
实盘配置后填写 `expected_broker_account_id` 和 `gm.strategy_id`。保留
`account_mode=LIVE`、`safety.allow_live_orders=false`，并使用独立 runtime
目录和 API 端口，不得复用仿真 runtime 数据库。
