"""SDK-callback driven V2 Agent; no DB, config files or file logs.

Construction and credentials are injected by the hosting terminal strategy.
SIM and LIVE use this same snapshot, command execution, and callback path.
"""
from __future__ import annotations

import math
import time
import uuid
import threading
import json
from decimal import Decimal
from collections import deque
from itertools import islice
from typing import Any, Callable

from broker_node.gm_agent.gm_adapter import GmContextAdapter
from broker_node.gm_agent.snapshot_collector import collect_snapshot, _json_value, _separate_broker_id
from broker_node.gm_agent.gm_mapper import map_order, map_fill
from broker_node.shared.order_types import GM_ORDER_TYPE_NAMES, validate_broker_order_type
from broker_node.gm_agent.ipc_client import IPCError


class RuntimeErrorState(RuntimeError):
    pass


class ReadonlyRuntime:
    def __init__(self, client: Any, identity: dict[str, Any], expected_account_id: str,
                 snapshot_interval_seconds: float, *, event_queue_limit: int, event_batch_limit: int,
                 clock: Callable[[], float] = time.monotonic,
                 adapter_factory: Callable[[Any], Any] = GmContextAdapter):
        if not isinstance(expected_account_id, str) or not expected_account_id:
            raise ValueError('expected account id is required')
        if isinstance(snapshot_interval_seconds, bool) or not isinstance(snapshot_interval_seconds, (int, float)) or not math.isfinite(snapshot_interval_seconds) or snapshot_interval_seconds <= 0:
            raise ValueError('snapshot interval must be positive and finite')
        if any(isinstance(n, bool) or not isinstance(n, int) or n <= 0 for n in (event_queue_limit, event_batch_limit)) or event_batch_limit > event_queue_limit:
            raise ValueError('explicit positive event queue and batch limits are required')
        self.client, self.identity = client, dict(identity)
        self.expected_account_id, self.interval = expected_account_id, snapshot_interval_seconds
        self.clock, self.adapter_factory = clock, adapter_factory
        self.sequence = 0
        self.started = False
        self.last_snapshot_at = None
        self.pending_snapshot = None
        self.event_queue_limit, self.event_batch_limit = event_queue_limit, event_batch_limit
        self.events = deque()
        self.events_lock = threading.Lock()
        self.timer_lock = threading.Lock()
        self.pending_events = None
        self.event_overflowed = False
        self.trade_connected = False
        self.market_connected = False
        self.connection_generation = 0
        self.pending_command_result = None
        self.active_quote_symbols = set()
        self.quote_ticks = deque()
        self.pending_quote_ticks = None

    def init(self, context: Any, timer: Callable[..., Any], period_ms: int) -> None:
        if self.started:
            raise RuntimeErrorState('runtime already started')
        if isinstance(period_ms, bool) or not isinstance(period_ms, int) or not 1 <= period_ms <= 43200000:
            raise ValueError('timer period out of range')
        adapter = self.adapter_factory(context)
        if adapter.account_id() != self.expected_account_id:
            raise RuntimeErrorState('broker account mismatch')
        self.client.hello(self.identity)
        # Actual Guotou 3.0.193 returned the key "status" in the verified
        # experiments. Do not silently substitute the docs' timer_status.
        self.started = True
        try:
            result = timer(self.on_timer, period=period_ms, start_delay=0)
            if not isinstance(result, dict) or result.get('status') != 0 or isinstance(result.get('timer_id'), bool) or not isinstance(result.get('timer_id'), int):
                raise RuntimeErrorState('GM timer registration failed')
        except BaseException:
            self.started = False
            raise

    def on_timer(self, context: Any) -> None:
        if not self.timer_lock.acquire(blocking=False):
            raise RuntimeErrorState('overlapping SDK timer callback')
        try:
            try:
                if self.client.session is None:
                    self.client.hello(self.identity)
                    self.sequence = 0
                    self.last_snapshot_at = None
                    self.pending_snapshot = None
                    self.pending_command_result = None
                self._on_timer(context)
            except IPCError as exc:
                print('Agent communication error:', str(exc), flush=True)
                if exc.status == 409:
                    self.client.session = None
            except Exception as exc:
                print('Agent callback error:', type(exc).__name__, str(exc), flush=True)
                try:
                    self.on_error('AGENT_CALLBACK_ERROR', str(exc))
                except Exception as report_error:
                    print('Agent error reporting failed:', str(report_error), flush=True)
        finally:
            self.timer_lock.release()

    def _on_timer(self, context: Any) -> None:
        if not self.started:
            raise RuntimeErrorState('runtime not initialized')
        with self.events_lock:
            if self.event_overflowed:
                # Stop reporting progress; the Node must expire this session
                # until full broker reconciliation has been performed.
                raise RuntimeErrorState('event queue overflow: reconciliation required')
        adapter = self.adapter_factory(context)
        if adapter.account_id() != self.expected_account_id:
            raise RuntimeErrorState('broker account mismatch')
        self.sequence += 1
        # This counter advances only from the real SDK timer callback.
        self.client.heartbeat(self.sequence, self.sequence)
        with self.events_lock:
            trade_connected, market_connected = self.trade_connected, self.market_connected
            generation = self.connection_generation
        node_generation = self.client.connectivity(self.sequence, trade_connected, market_connected, adapter.account_id())
        self._flush_events()
        if not trade_connected or not market_connected:
            return
        self._refresh_quotes()
        self._flush_quotes()
        if self.pending_snapshot is not None and (self.pending_snapshot[2] != generation or self.pending_snapshot[3] != node_generation):
            print('Agent connection changed; querying account data again', flush=True)
            self.pending_snapshot = None
        now = self.clock()
        if self.pending_snapshot is None and (self.last_snapshot_at is None or now - self.last_snapshot_at >= self.interval):
            batch = collect_snapshot(adapter, self.expected_account_id)
            self.pending_snapshot = (str(uuid.uuid4()), batch, generation, node_generation)
        if self.pending_snapshot is not None:
            message_id, batch, _, snapshot_generation = self.pending_snapshot
            with self.events_lock:
                if self.connection_generation != generation:
                    raise RuntimeErrorState('connection changed during snapshot query')
            self.client.snapshot(message_id, batch, snapshot_generation)
            self.pending_snapshot = None
            with self.events_lock:
                changed_during_send = self.connection_generation != generation
                self.last_snapshot_at = None if changed_during_send else self.clock()
            if changed_during_send:
                print('Agent connection changed during account sync; querying again', flush=True)
                return
        self._process_command(adapter, node_generation)

    def _process_command(self, adapter=None, node_generation=None):
        # Retry result delivery only; never repeat the SDK invocation.
        if self.pending_command_result is not None:
            self.client.command_result(**self.pending_command_result)
            self.pending_command_result = None
        try:
            command = self.client.claim_command()
        except IPCError:
            # The claim response may have been lost. End the session so Node
            # records an interrupted dispatch as UNKNOWN instead of retrying it.
            try:
                self.client.goodbye()
            except IPCError:
                pass
            self.client.session = None
            raise
        if command is None:
            return
        status, result, error = 'FAILED_SAFE', None, None
        called = False
        try:
            payload = json.loads(command['payload_json'])
            import gm.api as gm
            if command['command_type'] == 'ORDER_SUBMIT':
                side = {'BUY': gm.OrderSide_Buy, 'SELL': gm.OrderSide_Sell}[payload['side']]
                effect = gm.PositionEffect_Open if payload['side'] == 'BUY' else gm.PositionEffect_Close
                order_type = getattr(gm, GM_ORDER_TYPE_NAMES[validate_broker_order_type(payload['exchange'], payload['order_type'])])
                kwargs = {} if payload.get('price') is None else {'price': float(Decimal(payload['price']))}
                symbol = ('SHSE' if payload['exchange'] == 'SH' else 'SZSE') + '.' + payload['code']
                called = True
                result = gm.order_volume(symbol, payload['quantity'], side, order_type, effect, **kwargs)
            elif command['command_type'] == 'ORDER_CANCEL':
                called = True
                result = gm.order_cancel({'cl_ord_id': command['broker_client_order_id'], 'account_id': self.expected_account_id})
            elif command['command_type'] == 'SYNC_ALL':
                if adapter is None or node_generation is None:
                    raise RuntimeErrorState('account context is required for sync')
                batch = collect_snapshot(adapter, self.expected_account_id)
                self.client.snapshot(str(uuid.uuid4()), batch, node_generation)
                self.last_snapshot_at = self.clock()
            else:
                raise RuntimeErrorState('unsupported command type: ' + command['command_type'])
            result = _json_value(result)
            status = 'ACKED'
        except Exception as exc:
            status = 'UNKNOWN' if called else 'FAILED_SAFE'
            error = str(exc)
        self.pending_command_result = dict(command_id=command['command_id'], status=status, result=result, error=error)
        self.client.command_result(**self.pending_command_result)
        self.pending_command_result = None

    def _enqueue_event(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {'event_id': str(uuid.uuid4()), 'event_type': event_type, 'payload': _json_value(payload)}
        with self.events_lock:
            if len(self.events) >= self.event_queue_limit:
                self.event_overflowed = True
                raise RuntimeErrorState('event queue overflow: reconciliation required')
            self.events.append(event)

    def on_order_status(self, order: Any) -> None:
        self._enqueue_event('ORDER_STATUS', _separate_broker_id(map_order(order)))

    def on_execution_report(self, report: Any) -> None:
        self._enqueue_event('FILL', _separate_broker_id(map_fill(report)))

    def on_tick(self, tick: Any) -> None:
        data = _json_value(tick)
        with self.events_lock:
            self.quote_ticks.append(data)

    def _refresh_quotes(self) -> None:
        desired = set(self.client.quote_subscriptions())
        added = desired - self.active_quote_symbols
        removed = self.active_quote_symbols - desired
        if not added and not removed:
            return
        from gm.api import subscribe, unsubscribe
        try:
            if added:
                subscribe(symbols=sorted(added), frequency='tick', count=1, unsubscribe_previous=False, format='col')
                self.active_quote_symbols.update(added)
            for symbol in sorted(removed):
                unsubscribe(symbols=symbol, frequency='tick')
                self.active_quote_symbols.remove(symbol)
        except Exception as exc:
            self.on_error('QUOTE_SUBSCRIPTION_FAILED', str(exc))

    def _flush_quotes(self) -> None:
        with self.events_lock:
            if self.pending_quote_ticks is None and self.quote_ticks:
                self.pending_quote_ticks = list(self.quote_ticks)
            pending = self.pending_quote_ticks
        if not pending:
            return
        self.client.quote_ticks(pending)
        with self.events_lock:
            for _ in pending:
                self.quote_ticks.popleft()
            self.pending_quote_ticks = None

    def on_error(self, code: Any, info: Any) -> None:
        self._enqueue_event('GM_ERROR', {'code': code, 'info': str(info)})
        self._flush_events()

    def connection_changed(self, channel: str, connected: bool) -> None:
        if channel not in ('TRADE', 'MARKET') or type(connected) is not bool:
            raise ValueError('invalid SDK connection event')
        with self.events_lock:
            if channel == 'TRADE':
                changed = self.trade_connected != connected
                self.trade_connected = connected
            else:
                changed = self.market_connected != connected
                self.market_connected = connected
            if changed:
                self.connection_generation += 1
                # Force a fresh full query after either connection changes.
                self.last_snapshot_at = None
                if channel == 'MARKET' and not connected:
                    self.active_quote_symbols.clear()

    def _flush_events(self) -> None:
        with self.events_lock:
            if self.event_overflowed:
                raise RuntimeErrorState('event queue overflow: reconciliation required')
            if self.pending_events is None and self.events:
                self.pending_events = (str(uuid.uuid4()), list(islice(self.events, self.event_batch_limit)))
            pending = self.pending_events
        if pending is None:
            return
        message_id, batch = pending
        self.client.events(message_id, batch)
        with self.events_lock:
            for expected in batch:
                if not self.events or self.events[0]['event_id'] != expected['event_id']:
                    raise RuntimeErrorState('event queue order changed')
                self.events.popleft()
            self.pending_events = None

    def shutdown(self) -> None:
        if not self.started:
            raise RuntimeErrorState('runtime not initialized')
        self.started = False
        with self.events_lock:
            pending = self.pending_snapshot is not None or bool(self.events) or self.event_overflowed
        self.client.goodbye()
        if pending:
            raise RuntimeErrorState('unacknowledged data requires resynchronization')
