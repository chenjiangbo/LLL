"""Callbacks used by a strategy launched from the GM terminal."""
from gm.api import timer
from broker_node.gm_agent.ipc_client import IPCClient
from broker_node.gm_agent.terminal_entry import TerminalEntry

_entry = None


def configure(settings):
    global _entry
    _entry = TerminalEntry(**settings)
    client = IPCClient(settings['ipc_host'], settings['ipc_port'], settings['ipc_credential'], settings['ipc_timeout_seconds'], settings['max_response_bytes'])
    return client.bootstrap_token()


def init(context):
    print('HTTP_AGENT init', flush=True)
    _entry.init(context, timer)


def on_trade_data_connected(context): _entry.on_trade_data_connected(context)
def on_trade_data_disconnected(context): _entry.on_trade_data_disconnected(context)
def on_market_data_connected(context): _entry.on_market_data_connected(context)
def on_market_data_disconnected(context): _entry.on_market_data_disconnected(context)
def on_order_status(context, order): _entry.on_order_status(context, order)
def on_execution_report(context, report): _entry.on_execution_report(context, report)
def on_tick(context, tick): _entry.on_tick(context, tick)
def on_error(context, code, info):
    print('HTTP_AGENT error', code, info, flush=True)
    try:
        _entry.on_error(context, code, info)
    except Exception as exc:
        print('HTTP_AGENT error reporting failed:', str(exc), flush=True)
def on_shutdown(context): _entry.on_shutdown(context)
