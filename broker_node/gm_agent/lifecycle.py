from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from broker_node.gm_agent.gm_adapter import GmContextAdapter
from broker_node.gm_agent.event_writer import EventWriter
from broker_node.gm_agent.snapshot_writer import SnapshotWriter
from broker_node.gm_agent.synchronizer import ReadonlySynchronizer
from broker_node.gm_agent.reconciler import Reconciler
from broker_node.gm_agent.quote_cache import QuoteCache
from broker_node.gm_agent.quote_service import ExecutionQuoteService
from broker_node.gm_agent.quote_subscriptions import QuoteSubscriptionManager
from broker_node.gm_agent.executor import BrokerCommandExecutor
from broker_node.shared.db import connect
from broker_node.shared.config import NodeConfig


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_MANUAL_PAUSE_REASONS = frozenset({"API_PAUSED", "API_PAUSED_AND_CANCELING", "USER_PAUSED"})


class AgentLifecycle:
    def __init__(self, config: NodeConfig, durable_db):
        self.config = config
        self.durable_db = durable_db
        self.snapshots = SnapshotWriter(durable_db)
        self.events = EventWriter(durable_db)
        self._lifecycle_ready = False
        self._last_periodic_sync = 0.0
        self._last_reconcile_attempt = 0.0
        self._last_callback_heartbeat = 0.0
        self._next_quote_retry = 0.0
        self._pending_quote_priming: set[str] = set()
        self.quote_service = ExecutionQuoteService(QuoteCache(Path(config.raw["runtime"]["quote_cache_db"])))
        self.quote_subscriptions = QuoteSubscriptionManager(durable_db)
        self.executor = BrokerCommandExecutor(durable_db)
        self._adapter = None

    def initialize_from_context(self, context: Any) -> dict[str, int]:
        adapter = GmContextAdapter(context)
        self._adapter = adapter
        account_id = adapter.account_id()
        expected = self.config.raw.get("expected_broker_account_id")
        if not expected:
            raise RuntimeError("expected_broker_account_id is required before Agent can become ready")
        if account_id != expected:
            self._write_state(
                agent_process_status="ONLINE",
                broker_account_status="MISMATCH",
                execution_enabled=False,
                paused=True,
                pause_reason="ACCOUNT_MISMATCH",
                reconciliation_required=True,
            )
            raise RuntimeError("actual gm account does not match expected_broker_account_id")

        self._write_state(
            agent_process_status="ONLINE",
            market_connection_status="CONNECTED",
            trade_connection_status="CONNECTED",
            broker_account_status="CONNECTED",
            execution_enabled=False,
            paused=True,
            reconciliation_required=True,
        )
        counts = ReadonlySynchronizer(adapter, self.snapshots, self.events).synchronize()
        reconciliation = Reconciler(self.durable_db, self.events, self.snapshots).startup()
        if reconciliation["reconciliation_required"]:
            self._lifecycle_ready = True
            self.events.append("AGENT_RECONCILIATION_REQUIRED", reconciliation, "AGENT")
            self._last_periodic_sync = time.monotonic()
            return counts
        self._write_state(
            agent_process_status="ONLINE",
            market_connection_status="CONNECTED",
            trade_connection_status="CONNECTED",
            broker_account_status="CONNECTED",
            execution_enabled=True,
            paused=False,
            pause_reason=None,
            reconciliation_required=False,
            last_account_sync_at=_now(),
            last_position_sync_at=_now(),
            last_order_sync_at=_now(),
            last_fill_sync_at=_now(),
        )
        self._lifecycle_ready = True
        self.events.append("AGENT_READY", {"sync_counts": counts}, "AGENT")
        self._last_periodic_sync = time.monotonic()
        return counts

    def record_callback_heartbeat(self) -> None:
        # Heartbeat comes from the SDK callback thread so a stalled callback
        # loop cannot be reported as a healthy Agent by another thread.
        now = time.monotonic()
        if now - self._last_callback_heartbeat >= 1:
            self._write_state(agent_process_status="ONLINE", last_agent_heartbeat_at=_now())
            self._last_callback_heartbeat = now

    def on_tick(self, tick: Any) -> None:
        # Guotou's gm.api delivers TickLikeDict2, a mapping-compatible SDK
        # object that is not registered as collections.abc.Mapping.  Convert
        # only at this adapter boundary so the durable quote path always gets
        # a complete ordinary mapping and malformed SDK payloads fail loudly.
        if isinstance(tick, Mapping):
            tick = dict(tick)
        else:
            try:
                public_fields = (name for name in dir(tick) if not name.startswith("_"))
                tick = {
                    name: value
                    for name in public_fields
                    if not callable(value := getattr(tick, name))
                }
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"gm.api tick payload must be mapping-compatible, got {type(tick).__name__}"
                ) from exc
        # gm.api trading/query calls must run on the strategy callback thread;
        # do not dispatch order_volume/order_cancel from a Python worker.
        self.quote_service.on_tick(tick)

    def record_connection(self, channel: str, status: str, raw: Any = None) -> bool:
        """Persist connection transitions and fail closed on any disconnect."""
        if channel not in {"MARKET", "TRADE", "ACCOUNT"}:
            raise ValueError(f"unsupported connection channel: {channel}")
        if status not in {"CONNECTED", "DISCONNECTED", "UNKNOWN"}:
            raise ValueError(f"unsupported connection status: {status}")
        field = {
            "MARKET": "market_connection_status",
            "TRADE": "trade_connection_status",
            "ACCOUNT": "broker_account_status",
        }[channel]
        with connect(self.durable_db) as connection:
            current = connection.execute(
                f"SELECT {field} FROM node_state LIMIT 1"
            ).fetchone()
        transitioned = current is None or current[field] != status
        updates: dict[str, Any] = {field: status}
        if status != "CONNECTED":
            with connect(self.durable_db) as connection:
                state = connection.execute("SELECT pause_reason FROM node_state LIMIT 1").fetchone()
            existing_reason = state["pause_reason"] if state else None
            updates.update(
                execution_enabled=False,
                paused=True,
                # A connection flap must not erase a user pause.  The
                # reconciliation_required bit records the transport failure
                # separately; a successful reconnect will clear that bit but
                # will leave the user pause in place.
                pause_reason=(
                    existing_reason
                    if existing_reason in _MANUAL_PAUSE_REASONS
                    else f"{channel}_{status}"
                ),
                reconciliation_required=True,
            )
        self._write_state(**updates)
        event_type = "ACCOUNT_STATUS_CHANGED" if channel == "ACCOUNT" else "BROKER_CONNECTION_CHANGED"
        self.events.append(event_type, {"channel": channel, "status": status, "raw": raw}, "CALLBACK")
        return transitioned

    def reconcile_after_reconnect(self) -> dict[str, Any]:
        """Refresh broker facts after recovery before execution can resume."""
        if not self._adapter:
            raise RuntimeError("GM_ACCOUNT_CONTEXT_NOT_READY")
        with connect(self.durable_db) as connection:
            state = connection.execute(
                "SELECT market_connection_status, trade_connection_status, broker_account_status "
                "FROM node_state LIMIT 1"
            ).fetchone()
        if not state:
            raise RuntimeError("NODE_STATE_NOT_INITIALIZED")
        connection_status = dict(state)
        if any(value != "CONNECTED" for value in connection_status.values()):
            manual_pause_reason = self._manual_pause_reason()
            unavailable = next(
                name for name, value in connection_status.items() if value != "CONNECTED"
            )
            unavailable_channel = {
                "market_connection_status": "MARKET",
                "trade_connection_status": "TRADE",
                "broker_account_status": "ACCOUNT",
            }[unavailable]
            pause_reason = manual_pause_reason or f"{unavailable_channel}_DISCONNECTED"
            self._write_state(
                execution_enabled=False,
                paused=True,
                pause_reason=pause_reason,
                reconciliation_required=True,
            )
            self.events.append(
                "RECONCILIATION_DEFERRED",
                {"reason": "CONNECTION_NOT_READY", "connections": connection_status},
                "RECONCILE",
            )
            return {
                "reconciliation_required": True,
                "connection_status": connection_status,
            }
        try:
            counts = ReadonlySynchronizer(self._adapter, self.snapshots, self.events).synchronize()
            result = Reconciler(self.durable_db, self.events, self.snapshots).startup()
        except Exception as exc:
            # A reconnect is not verified merely because the transport says
            # CONNECTED.  If any read-side reconciliation step fails, keep
            # the node fail-closed and make the reason observable.
            manual_pause_reason = self._manual_pause_reason()
            self._write_state(
                execution_enabled=False,
                paused=True,
                pause_reason=manual_pause_reason or "RECONCILIATION_REQUIRED",
                reconciliation_required=True,
            )
            self.events.append(
                "RECONCILIATION_FAILED",
                {"error_type": type(exc).__name__, "message": str(exc)},
                "RECONCILE",
            )
            raise
        if result["reconciliation_required"]:
            manual_pause_reason = self._manual_pause_reason()
            self._write_state(
                execution_enabled=False,
                paused=True,
                pause_reason=manual_pause_reason or "RECONCILIATION_REQUIRED",
                reconciliation_required=True,
            )
            return {"sync_counts": counts, **result}
        # A verified reconnect restores execution only when the pause was the
        # automatic consequence of the connection failure.  A user pause is a
        # separate intent and must survive the reconnect.
        manual_pause_reason = self._manual_pause_reason()
        auto_resume = manual_pause_reason is None
        self._write_state(
            execution_enabled=auto_resume,
            paused=not auto_resume,
            pause_reason=None if auto_resume else manual_pause_reason,
            reconciliation_required=False,
            last_account_sync_at=_now(),
            last_position_sync_at=_now(),
            last_order_sync_at=_now(),
            last_fill_sync_at=_now(),
        )
        return {"sync_counts": counts, **result}

    def _manual_pause_reason(self) -> str | None:
        with connect(self.durable_db) as connection:
            state = connection.execute("SELECT pause_reason FROM node_state LIMIT 1").fetchone()
        reason = state["pause_reason"] if state else None
        return str(reason) if reason in _MANUAL_PAUSE_REASONS else None

    def _prime_current_quotes(self, symbols: set[str]) -> None:
        if not symbols:
            return
        from gm.api import current
        values = current(sorted(symbols), fields="symbol,price,quotes")
        for value in values:
            self.quote_service.on_tick(value)

    def process_one_command(self) -> None:
        if not self._adapter:
            return
        # A transient query failure during reconnect must not require another
        # connection transition before the Agent tries reconciliation again.
        now = time.monotonic()
        with connect(self.durable_db) as connection:
            state = connection.execute(
                "SELECT reconciliation_required,market_connection_status,trade_connection_status,broker_account_status FROM node_state LIMIT 1"
            ).fetchone()
            unknown = connection.execute("SELECT 1 FROM commands WHERE status='UNKNOWN' LIMIT 1").fetchone()
        if (state and state["reconciliation_required"] and not unknown
                and all(state[key] == "CONNECTED" for key in (
                    "market_connection_status", "trade_connection_status", "broker_account_status"))
                and now - self._last_reconcile_attempt >= 5):
            self._last_reconcile_attempt = now
            self.reconcile_after_reconnect()
        sync_period = float(self.config.raw["sync"]["account_position_sync_seconds"])
        if now - self._last_periodic_sync >= sync_period:
            self._sync_periodic(now)
        with connect(self.durable_db) as connection:
            state = connection.execute("SELECT execution_enabled,paused,account_mode FROM node_state LIMIT 1").fetchone()
        command = self.executor.claim_next() if state and state["execution_enabled"] and not state["paused"] else None
        if command:
            self.executor.dispatch(command, self._adapter.account_id())
            self._sync_periodic(now)

        # Quote leases are independent of command consumption. A failed
        # subscription is recorded and retried instead of starving the queue.
        if now >= self._next_quote_retry:
            try:
                added = self.quote_subscriptions.refresh()
                self._pending_quote_priming.update(added)
                self._pending_quote_priming.intersection_update(self.quote_subscriptions.active)
                self._prime_current_quotes(self._pending_quote_priming)
                self._pending_quote_priming.clear()
            except Exception as exc:
                self._next_quote_retry = now + 5
                logging.getLogger(__name__).exception("Execution quote subscription failed")
                self.events.append("QUOTE_SUBSCRIPTION_FAILED", {"error": str(exc)}, "AGENT")

    def _sync_periodic(self, now: float) -> None:
        self._last_periodic_sync = now
        try:
            ReadonlySynchronizer(self._adapter, self.snapshots, self.events).synchronize()
        except Exception as exc:
            logging.getLogger(__name__).exception("Periodic broker synchronization failed")
            self.events.append("BROKER_SYNC_FAILED", {"error": str(exc)}, "AGENT")
            self._write_state(
                execution_enabled=False, paused=True,
                pause_reason=self._manual_pause_reason() or "RECONCILIATION_REQUIRED",
                reconciliation_required=True,
            )

    def _write_state(self, **updates: Any) -> None:
        current = {
            "node_id": self.config.raw["node_id"],
            "broker_account_key": self.config.raw["broker_account_key"],
            "account_mode": self.config.raw["account_mode"],
            "updated_at": _now(),
        }
        current.update(updates)
        self.snapshots.write_node_state(current)
