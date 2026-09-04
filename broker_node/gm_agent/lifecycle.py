from __future__ import annotations

import threading
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


class AgentLifecycle:
    def __init__(self, config: NodeConfig, durable_db):
        self.config = config
        self.durable_db = durable_db
        self.snapshots = SnapshotWriter(durable_db)
        self.events = EventWriter(durable_db)
        self._stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._lifecycle_ready = False
        self.quote_service = ExecutionQuoteService(QuoteCache(Path(config.raw["runtime"]["quote_cache_db"])))
        self.quote_subscriptions = QuoteSubscriptionManager(durable_db)
        self.executor = BrokerCommandExecutor(durable_db)
        self._adapter = None

    def start_heartbeat(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="broker-node-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            self._write_state(
                agent_process_status="ONLINE",
                last_agent_heartbeat_at=_now(),
            )
            self._stop.wait(1.0)

    def initialize_from_context(self, context: Any) -> dict[str, int]:
        self.start_heartbeat()
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
            paused=bool(self.config.raw["safety"]["start_paused"]),
            reconciliation_required=True,
        )
        counts = ReadonlySynchronizer(adapter, self.snapshots, self.events).synchronize()
        added = self.quote_subscriptions.refresh()
        self._prime_current_quotes(added)
        reconciliation = Reconciler(self.durable_db, self.events, self.snapshots).startup()
        if reconciliation["reconciliation_required"]:
            raise RuntimeError(f"startup reconciliation requires protection: {reconciliation}")
        self._write_state(
            agent_process_status="ONLINE",
            market_connection_status="CONNECTED",
            trade_connection_status="CONNECTED",
            broker_account_status="CONNECTED",
            execution_enabled=False,
            paused=bool(self.config.raw["safety"]["start_paused"]),
            pause_reason=("START_PAUSED" if self.config.raw["safety"]["start_paused"] else None),
            reconciliation_required=False,
            last_account_sync_at=_now(),
            last_position_sync_at=_now(),
            last_order_sync_at=_now(),
            last_fill_sync_at=_now(),
        )
        self._lifecycle_ready = True
        self.events.append("AGENT_READY", {"sync_counts": counts}, "AGENT")
        return counts

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
        added = self.quote_subscriptions.refresh()
        self._prime_current_quotes(added)
        self.process_one_command()
        self.quote_service.on_tick(tick)

    def record_connection(self, channel: str, status: str, raw: Any = None) -> None:
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
        updates: dict[str, Any] = {field: status}
        if status != "CONNECTED":
            updates.update(
                execution_enabled=False,
                paused=True,
                pause_reason=f"{channel}_{status}",
                reconciliation_required=True,
            )
        self._write_state(**updates)
        event_type = "ACCOUNT_STATUS_CHANGED" if channel == "ACCOUNT" else "BROKER_CONNECTION_CHANGED"
        self.events.append(event_type, {"channel": channel, "status": status, "raw": raw}, "CALLBACK")

    def reconcile_after_reconnect(self) -> dict[str, Any]:
        """Refresh broker facts after recovery before execution can resume."""
        if not self._adapter:
            raise RuntimeError("GM_ACCOUNT_CONTEXT_NOT_READY")
        counts = ReadonlySynchronizer(self._adapter, self.snapshots, self.events).synchronize()
        result = Reconciler(self.durable_db, self.events, self.snapshots).startup()
        if result["reconciliation_required"]:
            self._write_state(
                execution_enabled=False,
                paused=True,
                pause_reason="RECONCILIATION_REQUIRED",
                reconciliation_required=True,
            )
            return {"sync_counts": counts, **result}
        # A verified reconnect restores the user's still-active execution
        # intent for both SIM and LIVE. Unknown commands and reconciliation
        # failures return above and keep the fail-closed lock in place.
        auto_resume = True
        self._write_state(
            execution_enabled=auto_resume,
            paused=not auto_resume,
            pause_reason=None if auto_resume else "RECONCILED_WAITING_RESUME",
            reconciliation_required=False,
            last_account_sync_at=_now(),
            last_position_sync_at=_now(),
            last_order_sync_at=_now(),
            last_fill_sync_at=_now(),
        )
        return {"sync_counts": counts, **result}

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
        with connect(self.durable_db) as connection:
            state = connection.execute("SELECT execution_enabled,paused,account_mode FROM node_state LIMIT 1").fetchone()
        if not state or not state["execution_enabled"] or state["paused"]:
            return
        command = self.executor.claim_next()
        if command:
            self.executor.dispatch(command, self._adapter.account_id())
            # A write ACK is not a broker terminal fact. Immediately query the
            # full read side so order/fill/position snapshots can reflect the
            # command without waiting for the next periodic reconcile.
            ReadonlySynchronizer(self._adapter, self.snapshots, self.events).synchronize()


    def _write_state(self, **updates: Any) -> None:
        current = {
            "node_id": self.config.raw["node_id"],
            "broker_account_key": self.config.raw["broker_account_key"],
            "account_mode": self.config.raw["account_mode"],
            "updated_at": _now(),
        }
        current.update(updates)
        self.snapshots.write_node_state(current)

    def stop(self) -> None:
        self._stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=3)
