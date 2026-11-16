# Guotou Broker Node

仿真和实盘统一使用 Broker Node HTTP API、Node 独占 SQLite、掘金终端 Agent 和同一套 `gm.api` 下单/撤单/回报处理代码。实盘与仿真的交易执行差异只来自账户权限、现有“允许实盘下单”设置以及券商实际响应。

每个 Node 配置都必须先运行 `scripts/setup_terminal_agent.py`，生成 `ipc_v2` 配置和掘金终端策略入口。Node 启动脚本不再启动旧的共享 SQLite Agent。

- Broker API Service：HTTP、鉴权、命令持久化和快照读取，不导入 gm.api。
- GM Strategy Agent：从 Node 通过 HTTP 获取命令，并通过 HTTP 回传账户快照及交易回报。
- Durable SQLite：仅由 Node 读写。
- Quote Cache：由 Node 维护行情缓存。

命令清理边界：Broker Node 禁止物理删除 `commands` 记录。只能通过受鉴权保护的
`POST /api/v1/commands/{command_id}/archive` 记录归档原因；未完成、未知、仍在执行、
没有券商订单链接或券商订单未处于终态的命令会被拒绝归档，并可通过
`GET /api/v1/commands/{command_id}` 查询原始状态和归档审计。归档不会覆盖原始命令状态，
也不会删除订单、回报或事件数据。

实盘下单只受现有 `safety.allow_live_orders` 用户设置控制；该设置关闭时，查询链路仍可使用，但下单和撤单命令不会进入 Agent。
