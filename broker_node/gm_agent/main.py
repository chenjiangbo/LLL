from __future__ import annotations

import json
import os
from pathlib import Path

from broker_node.gm_agent.lifecycle import AgentLifecycle
from broker_node.gm_agent.callbacks import CallbackHandlers
from broker_node.shared.config import ConfigError, NodeConfig
from broker_node.shared.db import initialize


_lifecycle: AgentLifecycle | None = None
_callbacks: CallbackHandlers | None = None
_pending_connection_events: list[tuple[str, str]] = []


def _config_path() -> Path:
    value = os.environ.get("BROKER_NODE_CONFIG")
    if not value:
        raise ConfigError("BROKER_NODE_CONFIG is required")
    return Path(value)


def run_agent() -> None:
    config = NodeConfig.load(_config_path())
    durable_db = Path(config.raw["runtime"]["durable_db"])
    initialize(durable_db)

    from gm.api import MODE_LIVE, run

    strategy_id = config.raw["gm"]["strategy_id"]
    token_file = Path(config.raw["runtime"]["durable_db"]).with_name("gm_token.txt")
    token = token_file.read_text(encoding="utf-8").strip() if token_file.is_file() else ""
    if not token:
        raise ConfigError(f"掘金 Token 尚未由后台下发：{token_file}")

    run(
        strategy_id=strategy_id,
        # gm.api resolves the strategy module from filename relative to sys.path.
        # Pass the package-relative path so it imports this module as
        # ``broker_node.gm_agent.main`` from the workspace root.
        filename=os.path.relpath(__file__),
        mode=MODE_LIVE,
        token=token,
    )


def init(context):
    global _lifecycle, _callbacks
    if _lifecycle is None:
        config = NodeConfig.load(_config_path())
        durable_db = Path(config.raw["runtime"]["durable_db"])
        initialize(durable_db)
        _lifecycle = AgentLifecycle(config, durable_db)
        _callbacks = CallbackHandlers(_lifecycle.events, durable_db)
    _lifecycle.initialize_from_context(context)
    for channel, status in _pending_connection_events:
        _lifecycle.record_connection(channel, status)
    _pending_connection_events.clear()


def _record_connection(channel: str, status: str) -> None:
    if _lifecycle is None:
        # gm.api can emit transport-connected callbacks before init(). Keep
        # the event until the verified account context has been constructed;
        # raising here aborts the strategy before account validation runs.
        _pending_connection_events.append((channel, status))
        return
    _lifecycle.record_connection(channel, status)
    if status == "CONNECTED" and channel in {"TRADE", "ACCOUNT"} and _lifecycle._lifecycle_ready:
        _lifecycle.reconcile_after_reconnect()


def on_order_status(context, order):
    if _callbacks is None:
        raise RuntimeError("GM Agent callbacks are not initialized")
    _callbacks.on_order_status(order)


def on_execution_report(context, report):
    if _callbacks is None:
        raise RuntimeError("GM Agent callbacks are not initialized")
    _callbacks.on_execution_report(report)


def on_error(context, code, info):
    if _callbacks is None:
        raise RuntimeError("GM Agent callbacks are not initialized")
    _callbacks.on_error(code, info)


def on_trade_data_connected(context):
    _record_connection("TRADE", "CONNECTED")


def on_trade_data_disconnected(context):
    _record_connection("TRADE", "DISCONNECTED")


def on_market_data_connected(context):
    _record_connection("MARKET", "CONNECTED")


def on_market_data_disconnected(context):
    _record_connection("MARKET", "DISCONNECTED")


def on_tick(context, tick):
    if _lifecycle is None:
        raise RuntimeError("GM Agent lifecycle is not initialized")
    _lifecycle.on_tick(tick)


if __name__ == "__main__":
    run_agent()
