"""Main-system consumers for the Broker Node HTTP contract."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable

from .gm_broker_gateway import GMBrokerHttpGateway


class BrokerEventConsumer:
    def __init__(self, gateway: GMBrokerHttpGateway, read_cursor: Callable[[], int], write_cursor: Callable[[int], None], apply_event: Callable[[dict[str, Any]], None]):
        self.gateway = gateway
        self.read_cursor = read_cursor
        self.write_cursor = write_cursor
        self.apply_event = apply_event

    def consume(self, limit: int = 500) -> dict[str, int]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        cursor = self.read_cursor()
        response = self.gateway._request("GET", f"/api/v1/events?after_seq={cursor}&limit={limit}")
        if not isinstance(response, dict) or not isinstance(response.get("events"), list):
            raise RuntimeError("Broker Node events response is malformed")
        events = response["events"]
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get("seq"), int):
                raise RuntimeError("Broker Node event is malformed")
            self.apply_event(event)
            cursor = int(event["seq"])
        if events:
            self.write_cursor(cursor)
        return {"consumed": len(events), "last_seq": cursor}

    def consume_all(self, limit: int = 500) -> dict[str, int]:
        """Drain the event log until the node reports no more events.

        The cursor is persisted only after each event has been applied.  A
        malformed page or an apply failure therefore stops the sync and keeps
        the cursor at the last committed event; it is never silently skipped.
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        consumed = 0
        cursor = self.read_cursor()
        while True:
            response = self.gateway._request("GET", f"/api/v1/events?after_seq={cursor}&limit={limit}")
            if not isinstance(response, dict) or not isinstance(response.get("events"), list):
                raise RuntimeError("Broker Node events response is malformed")
            events = response["events"]
            if not events:
                return {"consumed": consumed, "last_seq": cursor}
            page_last = cursor
            for event in events:
                if not isinstance(event, dict) or not isinstance(event.get("seq"), int):
                    raise RuntimeError("Broker Node event is malformed")
                seq = int(event["seq"])
                if seq <= page_last:
                    raise RuntimeError("Broker Node event sequence did not advance")
                self.apply_event(event)
                page_last = seq
                consumed += 1
            cursor = page_last
            self.write_cursor(cursor)
            if len(events) < limit:
                return {"consumed": consumed, "last_seq": cursor}


@dataclass
class ExecutionQuotePoller:
    gateway: GMBrokerHttpGateway
    poll_ms: int = 250
    lease_seconds: int = 120

    def __post_init__(self) -> None:
        if self.poll_ms < 1:
            raise ValueError("poll_ms must be positive")
        if self.lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        self._known_plan_ids: set[str] = set()
        self._subscription_fingerprint: dict[str, tuple[str, ...]] = {}
        self._next_renewal: dict[str, float] = {}

    def poll(self, active_plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not active_plans:
            for plan_id in sorted(self._known_plan_ids):
                self.gateway.remove_execution_quote_subscription(plan_id)
            self._known_plan_ids.clear()
            self._subscription_fingerprint.clear()
            self._next_renewal.clear()
            return []
        active = {
            str(plan["id"]): plan
            for plan in active_plans
            if plan.get("status") == "ACTIVE" and plan.get("id") is not None
        }
        for plan_id, plan in sorted(active.items()):
            symbol = plan.get("symbol")
            if not isinstance(symbol, str) or not symbol:
                raise ValueError(f"active execution plan {plan_id} has no symbol")
            fingerprint = (symbol,)
            now = time.monotonic()
            if (
                plan_id not in self._known_plan_ids
                or self._subscription_fingerprint.get(plan_id) != fingerprint
                or now >= self._next_renewal.get(plan_id, 0)
            ):
                self.gateway.set_execution_quote_subscription(
                    plan_id,
                    [self._parse_symbol(symbol)],
                    self.lease_seconds,
                )
                self._subscription_fingerprint[plan_id] = fingerprint
                self._next_renewal[plan_id] = now + max(1.0, self.lease_seconds / 2)
        for plan_id in sorted(self._known_plan_ids - set(active)):
            self.gateway.remove_execution_quote_subscription(plan_id)
            self._subscription_fingerprint.pop(plan_id, None)
            self._next_renewal.pop(plan_id, None)
        self._known_plan_ids = set(active)
        symbols = sorted({plan["symbol"] for plan in active.values()})
        return self.gateway.get_execution_quotes(symbols) if symbols else []

    @staticmethod
    def _parse_symbol(symbol: str) -> dict[str, str]:
        try:
            exchange, code = symbol.split(":", 1)
        except ValueError as exc:
            raise ValueError(f"invalid execution quote symbol: {symbol}") from exc
        if exchange not in {"SH", "SZ"} or not code:
            raise ValueError(f"unsupported execution quote symbol: {symbol}")
        return {"exchange": exchange, "code": code}
