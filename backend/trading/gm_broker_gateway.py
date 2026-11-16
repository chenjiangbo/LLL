"""HTTP gateway for the V1.2 Broker Node contract.

The gateway deliberately requires explicit endpoint and token configuration;
it never falls back to a different broker or fabricates disconnected data.
"""
from __future__ import annotations

import json
import os
from http.client import RemoteDisconnected
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

from .broker import BrokerGateway


class BrokerNodeRequestError(RuntimeError):
    def __init__(self, status: int, payload: Any):
        super().__init__(f"Broker Node request failed: HTTP {status}")
        self.status = status
        self.payload = payload


class GMBrokerHttpGateway(BrokerGateway):
    def __init__(self, base_url: str | None = None, api_token: str | None = None, timeout: float = 30.0):
        self.base_url = base_url or os.environ.get("BROKER_NODE_URL")
        self.api_token = api_token
        if not self.base_url:
            raise ValueError("BROKER_NODE_URL is required")
        self.base_url = self.base_url.rstrip("/")
        self.timeout = timeout
        # Broker Node endpoints are private LAN/Tailscale services.  A desktop
        # HTTP proxy can return its own 502 for these addresses, so this
        # dedicated broker channel must connect directly to the configured node.
        self._http = build_opener(ProxyHandler({}))

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        request = Request(self.base_url + path, data=body, method=method, headers=headers)
        try:
            with self._http.open(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise RuntimeError("Broker Node response must be a JSON object")
                return payload
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8"))
            except Exception:
                detail = {"error": str(exc)}
            raise BrokerNodeRequestError(exc.code, detail) from exc
        except (URLError, RemoteDisconnected, TimeoutError, ConnectionError) as exc:
            raise ConnectionError("Broker Node is unreachable") from exc

    def connect(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/health")

    def get_capabilities(self) -> dict[str, Any]:
        orders_by_exchange = {
            "SH": ["LIMIT", "MARKET", "MARKET_BOC", "MARKET_BOP", "MARKET_B5TC", "MARKET_B5TL"],
            "SZ": ["LIMIT", "MARKET", "MARKET_BOC", "MARKET_BOP", "MARKET_FAK", "MARKET_FOK", "MARKET_B5TC"],
        }
        return {
            "status": "CONNECTED",
            "native_orders": sorted({order_type for types in orders_by_exchange.values() for order_type in types}),
            "order_types_by_exchange": orders_by_exchange,
            "verified_order_types": ["LIMIT"],
            "unverified_order_types": sorted({order_type for types in orders_by_exchange.values() for order_type in types} - {"LIMIT"}),
            "conditional_execution": [],
            "algorithms": [],
        }

    def get_status(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/status")

    def configure_gm_token(self, token: str) -> dict[str, Any]:
        if not token:
            raise ValueError("GM token is required")
        return self._request("PUT", "/api/v1/connection/token", {"token": token})

    def get_node_settings(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/config/settings")

    def update_node_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", "/api/v1/config/settings", settings)

    def get_account(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/account")

    def get_positions(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/positions")["payload"]

    def get_orders(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/orders?scope=today")["payload"]

    def get_fills(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/fills?scope=today")["payload"]

    def get_events(self, after_seq: int, limit: int = 500) -> dict[str, Any]:
        if after_seq < 0 or limit <= 0:
            raise ValueError("after_seq must be non-negative and limit must be positive")
        return self._request("GET", f"/api/v1/events?after_seq={after_seq}&limit={limit}")

    def get_command(self, command_id: str) -> dict[str, Any]:
        if not str(command_id).strip():
            raise ValueError("command_id is required")
        return self._request("GET", f"/api/v1/commands/{quote(str(command_id), safe='')}")

    def set_execution_quote_subscription(self, execution_plan_id: str, instruments: list[dict[str, str]], lease_seconds: int = 120) -> dict[str, Any]:
        return self._request("PUT", f"/api/v1/execution-quotes/subscriptions/{execution_plan_id}", {"symbols": instruments, "lease_seconds": lease_seconds})

    def remove_execution_quote_subscription(self, execution_plan_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/api/v1/execution-quotes/subscriptions/{execution_plan_id}")

    def get_execution_quotes(self, instruments: list[str]) -> list[dict[str, Any]]:
        if any(not isinstance(item, str) or not item for item in instruments):
            raise ValueError("execution quote symbols must be non-empty strings")
        query = quote(",".join(instruments), safe=":,")
        return self._request("GET", f"/api/v1/execution-quotes?symbols={query}")["quotes"]

    def submit_order(self, order: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/orders", order)

    def cancel_order(self, order: dict[str, Any]) -> dict[str, Any]:
        client_order_id = order["client_order_id"]
        return self._request("POST", f"/api/v1/orders/{client_order_id}/cancel", {"cancel_request_id": order["cancel_request_id"], "reason": order.get("reason", "SYSTEM_CANCEL")})
