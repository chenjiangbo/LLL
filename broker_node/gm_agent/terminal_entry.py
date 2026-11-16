"""Explicitly configured terminal-strategy callbacks for V2 readonly mode.

The terminal's strategy is responsible for securely supplying every setting.
No file, environment, credential fallback, or SDK run() call is performed.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Callable
from collections.abc import Mapping

from broker_node.gm_agent.ipc_client import IPCClient
from broker_node.gm_agent.readonly_runtime import ReadonlyRuntime, RuntimeErrorState
from broker_node.shared.windows_process import process_started_at


_ENV_FIELDS = {
    'node_id': 'LLL_V2_NODE_ID', 'account_mode': 'LLL_V2_ACCOUNT_MODE',
    'strategy_id': 'LLL_V2_STRATEGY_ID', 'broker_account_key': 'LLL_V2_BROKER_ACCOUNT_KEY',
    'broker_account_id': 'LLL_V2_BROKER_ACCOUNT_ID', 'ipc_host': 'LLL_V2_IPC_HOST',
    'ipc_port': 'LLL_V2_IPC_PORT', 'ipc_credential': 'LLL_V2_IPC_CREDENTIAL',
    'ipc_timeout_seconds': 'LLL_V2_IPC_TIMEOUT_SECONDS', 'max_response_bytes': 'LLL_V2_MAX_RESPONSE_BYTES',
    'snapshot_interval_seconds': 'LLL_V2_SNAPSHOT_INTERVAL_SECONDS',
    'event_queue_limit': 'LLL_V2_EVENT_QUEUE_LIMIT', 'event_batch_limit': 'LLL_V2_EVENT_BATCH_LIMIT',
    'timer_period_ms': 'LLL_V2_TIMER_PERIOD_MS',
}


def terminal_entry_from_environment(environment: Mapping[str, str]) -> 'TerminalEntry':
    """Candidate delivery mechanism; caller explicitly supplies environment.

    Reading this mapping does not establish that the broker terminal inherits
    it, nor that it is suitable for a particular Windows permissions model.
    Those conditions must be validated before deployment.
    """
    values = {}
    for field, name in _ENV_FIELDS.items():
        value = environment.get(name)
        if not isinstance(value, str) or not value:
            raise ValueError('required terminal setting is missing: ' + name)
        values[field] = value
    for field in ('ipc_port', 'max_response_bytes', 'event_queue_limit', 'event_batch_limit', 'timer_period_ms'):
        value = values[field]
        if not value.isascii() or not value.isdigit():
            raise ValueError('terminal integer setting is invalid: ' + _ENV_FIELDS[field])
        values[field] = int(value)
    for field in ('ipc_timeout_seconds', 'snapshot_interval_seconds'):
        try:
            values[field] = float(values[field])
        except ValueError as exc:
            raise ValueError('terminal numeric setting is invalid: ' + _ENV_FIELDS[field]) from exc
    return TerminalEntry(**values)


class TerminalEntry:
    def __init__(self, *, node_id: str, account_mode: str, strategy_id: str,
                 broker_account_key: str, broker_account_id: str, ipc_host: str,
                 ipc_port: int, ipc_credential: str, ipc_timeout_seconds: float,
                 max_response_bytes: int, snapshot_interval_seconds: float,
                 event_queue_limit: int, event_batch_limit: int, timer_period_ms: int,
                 process_identity: Callable[[int], str] = process_started_at,
                 client_factory: Callable[..., Any] = IPCClient,
                 runtime_factory: Callable[..., Any] = ReadonlyRuntime):
        if account_mode not in ('SIM', 'LIVE'):
            raise ValueError('account mode must be SIM or LIVE')
        if any(not isinstance(value, str) or not value for value in (node_id, strategy_id, broker_account_key, broker_account_id)):
            raise ValueError('complete account and strategy identity required')
        if isinstance(timer_period_ms, bool) or not isinstance(timer_period_ms, int) or not 1 <= timer_period_ms <= 43200000:
            raise ValueError('timer period out of range')
        pid = os.getpid()
        identity = {'node_id': node_id, 'account_mode': account_mode, 'strategy_id': strategy_id,
                    'broker_account_key': broker_account_key, 'pid': pid,
                    'started_at': process_identity(pid), 'agent_instance_id': str(uuid.uuid4())}
        client = client_factory(ipc_host, ipc_port, ipc_credential, ipc_timeout_seconds, max_response_bytes)
        self.runtime = runtime_factory(client, identity, broker_account_id, snapshot_interval_seconds,
                                       event_queue_limit=event_queue_limit, event_batch_limit=event_batch_limit)
        self.timer_period_ms = timer_period_ms

    def init(self, context: Any, timer: Callable[..., Any]) -> None:
        self.runtime.init(context, timer, self.timer_period_ms)

    def on_order_status(self, context: Any, order: Any) -> None:
        if not self.runtime.started:
            raise RuntimeErrorState('order callback arrived before runtime initialization')
        self.runtime.on_order_status(order)

    def on_execution_report(self, context: Any, report: Any) -> None:
        if not self.runtime.started:
            raise RuntimeErrorState('fill callback arrived before runtime initialization')
        self.runtime.on_execution_report(report)

    def on_tick(self, context: Any, tick: Any) -> None:
        if self.runtime.started:
            self.runtime.on_tick(tick)

    def on_error(self, context: Any, code: Any, info: Any) -> None:
        if self.runtime.started:
            self.runtime.on_error(code, info)

    def on_trade_data_connected(self, context: Any) -> None:
        self.runtime.connection_changed('TRADE', True)

    def on_trade_data_disconnected(self, context: Any) -> None:
        self.runtime.connection_changed('TRADE', False)

    def on_market_data_connected(self, context: Any) -> None:
        self.runtime.connection_changed('MARKET', True)

    def on_market_data_disconnected(self, context: Any) -> None:
        self.runtime.connection_changed('MARKET', False)

    def on_shutdown(self, context: Any) -> None:
        self.runtime.shutdown()
