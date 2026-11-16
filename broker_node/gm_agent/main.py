from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from broker_node.gm_agent.lifecycle import AgentLifecycle
from broker_node.gm_agent.callbacks import CallbackHandlers
from broker_node.shared.config import ConfigError, NodeConfig
from broker_node.shared.db import initialize


_lifecycle: AgentLifecycle | None = None
_callbacks: CallbackHandlers | None = None
_pending_connection_events: list[tuple[str, str]] = []
_command_timer_id: int | None = None


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
    global _lifecycle, _callbacks, _command_timer_id
    if _lifecycle is None:
        config = NodeConfig.load(_config_path())
        durable_db = Path(config.raw["runtime"]["durable_db"])
        initialize(durable_db)
        _lifecycle = AgentLifecycle(config, durable_db)
        _callbacks = CallbackHandlers(_lifecycle.events, durable_db)
    _lifecycle.initialize_from_context(context)
    for channel, status in _pending_connection_events:
        # Connection callbacks can arrive before gm.api invokes init().  Do
        # not bypass the normal reconnect path after the verified account
        # context is ready: a CONNECTED event must still trigger the full
        # read-side reconciliation before execution can resume.
        _record_connection(channel, status)
    _pending_connection_events.clear()
    # Command consumption must not depend on market ticks.  gm.api timer
    # callbacks run in the strategy callback context, so order_volume and
    # order_cancel remain on the SDK-supported thread even outside market
    # hours.
    from gm.api import timer
    poll_ms = int(_lifecycle.config.raw["sync"]["command_poll_interval_ms"])
    _command_timer_id = timer(_process_commands, period=poll_ms, start_delay=0)
    # Guotou's installed gm 3.0.193 returns `status` (the generic SDK
    # reference calls this field `timer_status`).
    if not isinstance(_command_timer_id, dict) or _command_timer_id.get("status") != 0:
        raise RuntimeError(f"GM command timer could not start: {_command_timer_id!r}")


def _process_commands(context):
    if _lifecycle is None:
        raise RuntimeError("GM Agent lifecycle is not initialized")
    try:
        _lifecycle.process_one_command()
        _lifecycle.record_callback_heartbeat()
    except Exception:
        logging.getLogger(__name__).exception("Agent command cycle failed")


def _record_connection(channel: str, status: str) -> None:
    if _lifecycle is None:
        # gm.api can emit transport-connected callbacks before init(). Keep
        # the event until the verified account context has been constructed;
        # raising here aborts the strategy before account validation runs.
        _pending_connection_events.append((channel, status))
        return
    transitioned = _lifecycle.record_connection(channel, status)
    if status == "CONNECTED" and transitioned and _lifecycle._lifecycle_ready:
        try:
            _lifecycle.reconcile_after_reconnect()
        except Exception:
            logging.getLogger(__name__).exception("Reconciliation after reconnect failed; will retry")


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


def on_account_status(context, account):
    # The verified SDK callback supplies an account_id and status.state.
    config = _lifecycle.config if _lifecycle else NodeConfig.load(_config_path())
    account_id = account.get("account_id")
    if account_id != config.raw.get("expected_broker_account_id"):
        return
    state = account["status"]["state"]
    _record_connection("ACCOUNT", "CONNECTED" if state == 3 else "DISCONNECTED")


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
