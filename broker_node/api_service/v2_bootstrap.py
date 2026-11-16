"""Explicit V2 application assembly; no implicit secret or port fallback.

The process launcher and terminal credential delivery are intentionally not
included until their Windows/QMT behaviour is verified.
"""
from __future__ import annotations

import ipaddress
import math
from pathlib import Path
from typing import Any, Callable

from broker_node.api_service.app import create_app, default_config_path
from broker_node.api_service.ipc_app import create_ipc_app
from broker_node.api_service.ipc_store import IPCStore
from broker_node.shared.config import ConfigError, NodeConfig
from broker_node.shared.db import initialize
from broker_node.gm_agent.quote_cache import QuoteCache
from broker_node.gm_agent.quote_service import ExecutionQuoteService


def assemble_v2(config: NodeConfig, ipc_credential: str, process_verifier: Callable[[int, str], bool]):
    if default_config_path().resolve() != config.path.resolve():
        raise ConfigError('V2 and public API must use the same explicit configuration')
    raw: dict[str, Any] = config.raw
    ipc = raw.get('ipc_v2')
    if not isinstance(ipc, dict):
        raise ConfigError('ipc_v2 configuration is required')
    host = ipc.get('host')
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ConfigError('ipc_v2.host must be a loopback IP literal') from exc
    if not address.is_loopback:
        raise ConfigError('ipc_v2.host must be loopback')
    port, maximum, timeout = ipc.get('port'), ipc.get('max_body_bytes'), ipc.get('heartbeat_timeout_seconds')
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigError('ipc_v2.port must be an explicit port')
    if port == raw['api'].get('port'):
        raise ConfigError('IPC and public API ports must differ')
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
        raise ConfigError('ipc_v2.max_body_bytes must be positive')
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ConfigError('ipc_v2.heartbeat_timeout_seconds must be positive')
    if not isinstance(ipc_credential, str) or len(ipc_credential.encode('utf-8')) < 32:
        raise ConfigError('dedicated IPC credential is required')
    if not callable(process_verifier):
        raise ConfigError('process identity verifier is required')
    expected = {'node_id': raw['node_id'], 'account_mode': raw['account_mode'],
                'strategy_id': raw['gm']['strategy_id'], 'broker_account_key': raw['broker_account_key'],
                'broker_account_id': raw.get('expected_broker_account_id')}
    if any(not isinstance(value, str) or not value for value in expected.values()):
        raise ConfigError('complete account and strategy identity is required')
    path = Path(raw['runtime']['durable_db'])
    initialize(path)
    store = IPCStore(path, timeout, config=config, process_verifier=process_verifier)
    token_path = path.with_name('gm_token.txt')
    def read_token():
        return token_path.read_text(encoding='utf-8').strip()
    quote_service = ExecutionQuoteService(QuoteCache(Path(raw['runtime']['quote_cache_db'])))
    private = create_ipc_app(store, expected, ipc_credential, maximum, read_token, quote_service)
    # create_app reads its explicitly configured NodeConfig and rejects a
    # different DB. The caller must set BROKER_NODE_CONFIG to this config.
    public = create_app(ipc_store=store, node_config=config)
    return public, private, store
