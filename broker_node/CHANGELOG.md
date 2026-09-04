# Broker Node change log

## 2026-09-03

- Completed Phase 0 verified contract and real gm.api fixtures.
- Completed Phase 1 read-only Agent and API validation on the Guotou Windows terminal.
- Added strict configuration loading, durable SQLite state/snapshot/event storage, raw-preserving gm.api mapping, startup reconciliation, heartbeat, Bearer-authenticated read-only API, and idempotent external-order events.
- Verified against the live SIM strategy/account: gm.api state `3`, total asset `200409.99938964844`, one position, two orders, zero unfinished orders, two fills; API authentication and all Phase 1 read-only endpoints passed.
- Execution remains paused and disabled by configuration.
- Started Phase 2: added real-L1 quote normalization/cache, owner subscription lease API, quote freshness, Agent subscription refresh/current quote priming. The closed-market run verified a real `current()` quote and cache; tick callback capture remains explicitly pending a market-hours run.
- Phase 2 market-hours verification completed: real `on_tick` callbacks were received from the Guotou terminal and a redacted tick fixture was added.
- Completed Phase 3 SIM execution path: durable command queue, SIM-only gate, callback-thread gm.api dispatch, generated broker-order to client-order linking, order/fill synchronization, T+1 sellable-quantity protection, idempotent callbacks, and cancel dependency retry.
- Windows SIM validation completed during market hours: 100-share BUY orders filled with query/callback fill evidence; the real Guotou order record exposed T+1 sellability through `available_now` and the implementation now enforces it; terminal-order cancel returns `409 ALREADY_TERMINAL` without claiming a false cancel. A broker-level pending-order-to-canceled final state was NOT_REPRODUCED because this Guotou simulation immediately fills the chosen test orders.
- Completed Phase 4 main-system integration boundary: strict `GMBrokerHttpGateway` HTTP contract, explicit timeout/error propagation, quote subscription/read methods, at-least-once `BrokerEventConsumer` cursor advancement after successful application, malformed-event rejection, and active-plan quote subscription/lease renewal/unsubscription in `ExecutionQuotePoller`.
- Completed Phase 5 execution orchestration: `ExecutionEngine` consumes only the latest quote, blocks stale/disconnected conditional execution, evaluates LIMIT/PRICE_TRIGGER/PRICE_RANGE plans, runs existing `PreTradeRisk`, creates the local pending order before calling the Gateway, propagates safety constraints and trigger snapshots, and leaves fills/positions to Broker events and reconciliation. Added end-to-end orchestration tests.
- Added the Phase 10 pause-and-cancel-open-orders API. It pauses the node first, then creates one idempotent cancel command per open linked system order. Corrected Windows startup scripts to require an explicit Broker Node config path, read the configured token environment variable, and use the configured API host/port; they no longer depend on `broker_sdk_probe`.
- Added connection transition callbacks for market and trade channels. Disconnect or UNKNOWN events persist the state, set the node paused, disable execution, and require reconciliation; reconnect events are recorded without automatically resuming execution.
