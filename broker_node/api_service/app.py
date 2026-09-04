from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from broker_node.api_service.repositories import NodeRepository
from broker_node.shared.config import ConfigError, NodeConfig
from broker_node.shared.db import initialize
from broker_node.gm_agent.quote_cache import QuoteCache
from broker_node.gm_agent.command_validator import CommandValidationError, validate_order_payload
from broker_node.api_service.auth import require_bearer_token


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SyncRequest(BaseModel):
    request_id: str = Field(min_length=1)


class QuoteSubscriptionRequest(BaseModel):
    symbols: list[dict[str, str]] = Field(min_length=1)
    lease_seconds: int = Field(default=120, ge=1)


class OrderRequest(BaseModel):
    request_id: str = Field(min_length=1)
    client_order_id: str = Field(min_length=1)
    broker_account_key: str = Field(min_length=1)
    code: str = Field(min_length=1)
    exchange: str = Field(pattern="^(SH|SZ)$")
    side: str = Field(pattern="^(BUY|SELL)$")
    price: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    source: dict[str, Any] = Field(default_factory=dict)
    safety_constraints: dict[str, Any] = Field(default_factory=dict)
    trigger_snapshot: Optional[dict[str, Any]] = None


class CancelRequest(BaseModel):
    cancel_request_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class GmTokenRequest(BaseModel):
    token: str = Field(min_length=1)


class NodeSettingsRequest(BaseModel):
    allow_live_orders: bool
    start_paused: bool


def create_app() -> FastAPI:
    config_path = default_config_path()
    config = NodeConfig.load(config_path)
    durable_db = Path(config.raw["runtime"]["durable_db"])
    initialize(durable_db)
    repository = NodeRepository(durable_db)
    quote_cache = QuoteCache(Path(config.raw["runtime"]["quote_cache_db"]))
    app = FastAPI(title="Guotou Broker Node API", version="1.2")

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "node_id": config.raw["node_id"], "server_time": _now()}

    @app.get("/api/v1/status")
    def status() -> dict[str, Any]:
        state = repository.get_node_state()
        if not state:
            return {
                "node_id": config.raw["node_id"],
                "broker_account_key": config.raw["broker_account_key"],
                "account_mode": config.raw["account_mode"],
                "strategy_id": config.raw["gm"]["strategy_id"],
                "agent_online": False,
                "market_connected": False,
                "trade_connected": False,
                "account_connected": False,
                "execution_enabled": False,
                "paused": True,
                "reconciliation_required": True,
                "unresolved_unknown_commands": repository.unresolved_unknown_commands(),
                "status": "AGENT_NOT_INITIALIZED",
            }
        heartbeat = state.get("last_agent_heartbeat_at")
        offline_seconds = int(config.raw["sync"]["agent_offline_seconds"])
        agent_online = False
        if heartbeat:
            heartbeat_time = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - heartbeat_time).total_seconds()
            agent_online = age <= offline_seconds
        return {
            "node_id": state["node_id"],
            "broker_account_key": state["broker_account_key"],
            "account_mode": state["account_mode"],
            "strategy_id": config.raw["gm"]["strategy_id"],
            "agent_online": agent_online,
            "market_connected": state["market_connection_status"] == "CONNECTED",
            "trade_connected": state["trade_connection_status"] == "CONNECTED",
            "account_connected": state["broker_account_status"] == "CONNECTED",
            "execution_enabled": bool(state["execution_enabled"]),
            "paused": bool(state["paused"]),
            "reconciliation_required": bool(state["reconciliation_required"]),
            "unresolved_unknown_commands": repository.unresolved_unknown_commands(),
            "last_agent_heartbeat_at": heartbeat,
            "last_account_sync_at": state["last_account_sync_at"],
        }

    def snapshot_response(snapshot_type: str) -> dict[str, Any]:
        snapshot = repository.get_snapshot(snapshot_type)
        if not snapshot:
            raise HTTPException(status_code=503, detail={"code": "STALE_SNAPSHOT", "message": f"{snapshot_type} snapshot is not available"})
        return snapshot

    @app.put("/api/v1/connection/token")
    def configure_gm_token(request: GmTokenRequest) -> dict[str, Any]:
        """Receive the real GM token from the backend and persist it locally.

        The token is never returned in the response. The agent reads this
        private runtime file when it starts; no Windows environment variable
        is required.
        """
        token_file = Path(config.raw["runtime"]["durable_db"]).with_name("gm_token.txt")
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(request.token, encoding="utf-8")
        return {"status": "SUCCESS", "configured": True}

    @app.get("/api/v1/config/settings", dependencies=[Depends(require_bearer_token)])
    def get_config_settings() -> dict[str, Any]:
        safety = config.raw["safety"]
        return {
            "allow_live_orders": bool(safety.get("allow_live_orders", False)),
            "start_paused": bool(safety.get("start_paused", True)),
            "account_mode": config.raw["account_mode"],
            "restart_required": False,
        }

    @app.put("/api/v1/config/settings", dependencies=[Depends(require_bearer_token)])
    def update_config_settings(request: NodeSettingsRequest) -> dict[str, Any]:
        """Persist user-facing safety settings on this Windows node.

        The backend authenticates the user before calling this endpoint. The
        Node still writes only an explicit allow-list and never accepts a
        replacement configuration document from the network.
        """
        if config.raw["account_mode"] != "LIVE" and request.allow_live_orders:
            raise HTTPException(status_code=422, detail={"code": "LIVE_SETTING_ON_SIM_NODE", "message": "仿真节点不能开启实盘交易授权"})
        updated = json.loads(json.dumps(config.raw))
        updated.setdefault("safety", {})["allow_live_orders"] = request.allow_live_orders
        updated["safety"]["start_paused"] = request.start_paused
        temp_path = config_path.with_suffix(config_path.suffix + ".tmp")
        try:
            temp_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp_path.replace(config_path)
        except OSError as exc:
            raise HTTPException(status_code=500, detail={"code": "CONFIG_WRITE_FAILED", "message": "Node 配置写入失败"}) from exc
        config.raw.clear()
        config.raw.update(updated)
        return {
            "status": "SUCCESS",
            "settings": {
                "allow_live_orders": request.allow_live_orders,
                "start_paused": request.start_paused,
                "account_mode": config.raw["account_mode"],
                "restart_required": False,
            },
        }

    @app.get("/api/v1/account")
    def account() -> dict[str, Any]:
        return snapshot_response("ACCOUNT")

    @app.get("/api/v1/positions")
    def positions() -> dict[str, Any]:
        return snapshot_response("POSITIONS")

    @app.get("/api/v1/orders")
    def orders(scope: str = Query(default="today", pattern="^(today|unfinished)$")) -> dict[str, Any]:
        return snapshot_response("ORDERS" if scope == "today" else "UNFINISHED_ORDERS")

    @app.get("/api/v1/fills")
    def fills(scope: str = Query(default="today", pattern="^today$")) -> dict[str, Any]:
        return snapshot_response("FILLS")

    @app.get("/api/v1/events")
    def events(after_seq: int = Query(default=0, ge=0), limit: int = Query(default=500, ge=1)) -> dict[str, Any]:
        if limit > 500:
            raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEST", "message": "limit cannot exceed 500"})
        return repository.list_events(after_seq, limit)

    @app.post("/api/v1/sync")
    def sync(request: SyncRequest) -> dict[str, Any]:
        return repository.enqueue_sync(request.request_id, _now())

    @app.post("/api/v1/orders", status_code=202)
    def place_order(request: OrderRequest) -> dict[str, Any]:
        if config.raw["account_mode"] == "LIVE" and not config.live_orders_enabled():
            raise HTTPException(status_code=423, detail={"code": "LIVE_ORDERS_DISABLED", "message": "live order execution is disabled"})
        if request.broker_account_key != config.raw["broker_account_key"]:
            raise HTTPException(status_code=409, detail={"code": "ACCOUNT_MISMATCH", "message": "broker account key does not match node"})
        payload = request.model_dump()
        try:
            payload = validate_order_payload(payload, config.raw, durable_db)
        except CommandValidationError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_ORDER", "message": str(exc)}) from exc
        try:
            return repository.enqueue_command(request.request_id, "ORDER_SUBMIT", payload, request.client_order_id, _now())
        except ValueError as exc:
            if str(exc) == "IDEMPOTENCY_CONFLICT":
                raise HTTPException(status_code=409, detail={"code": str(exc), "message": "request_id was reused with a different payload"}) from exc
            raise

    @app.post("/api/v1/orders/{client_order_id}/cancel", status_code=202)
    def cancel_order(client_order_id: str, request: CancelRequest) -> dict[str, Any]:
        if repository.order_status(client_order_id) in {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}:
            raise HTTPException(status_code=409, detail={"code": "ALREADY_TERMINAL", "message": "order is already terminal"})
        payload = {"client_order_id": client_order_id, **request.model_dump()}
        try:
            return repository.enqueue_command(request.cancel_request_id, "ORDER_CANCEL", payload, client_order_id, _now())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": str(exc), "message": "cancel request idempotency conflict"}) from exc

    @app.post("/api/v1/control/pause")
    def pause() -> dict[str, Any]:
        return repository.set_paused(True, "API_PAUSED")

    @app.post("/api/v1/control/resume")
    def resume() -> dict[str, Any]:
        if config.raw["account_mode"] == "LIVE" and not config.live_orders_enabled():
            raise HTTPException(status_code=423, detail={"code": "LIVE_ORDERS_DISABLED", "message": "live order execution is disabled"})
        try:
            return repository.set_paused(False)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": str(exc), "message": "node is not ready to resume"}) from exc

    @app.post("/api/v1/control/pause-and-cancel-open-orders")
    def pause_and_cancel_open_orders() -> dict[str, Any]:
        paused = repository.set_paused(True, "API_PAUSED_AND_CANCELING")
        order_ids = repository.open_system_orders()
        queued = []
        for client_order_id in order_ids:
            queued.append(
                repository.enqueue_command(
                    f"pause-cancel:{client_order_id}",
                    "ORDER_CANCEL",
                    {
                        "client_order_id": client_order_id,
                        "cancel_request_id": f"pause-cancel:{client_order_id}",
                        "reason": "PAUSE_AND_CANCEL",
                    },
                    client_order_id,
                    _now(),
                )
            )
        return {"paused": paused, "cancel_requests": queued}

    @app.put("/api/v1/execution-quotes/subscriptions/{execution_plan_id}")
    def set_quote_subscription(execution_plan_id: str, request: QuoteSubscriptionRequest) -> dict[str, Any]:
        try:
            repository.set_quote_subscription(execution_plan_id, request.symbols, request.lease_seconds, _now())
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEST", "message": str(exc)}) from exc
        return {"execution_plan_id": execution_plan_id, "subscriptions": repository.list_quote_subscriptions()}

    @app.delete("/api/v1/execution-quotes/subscriptions/{execution_plan_id}")
    def remove_quote_subscription(execution_plan_id: str) -> dict[str, Any]:
        repository.remove_quote_subscription(execution_plan_id)
        return {"execution_plan_id": execution_plan_id, "removed": True}

    @app.get("/api/v1/execution-quotes/subscriptions")
    def quote_subscriptions() -> dict[str, Any]:
        return {"subscriptions": repository.list_quote_subscriptions()}

    @app.get("/api/v1/execution-quotes")
    def execution_quotes(symbols: Optional[str] = Query(default=None)) -> dict[str, Any]:
        requested = symbols.split(",") if symbols else None
        return {"quotes": quote_cache.get(requested, int(config.raw["execution_quote"]["freshness_ms"]))}

    return app


def default_config_path() -> Path:
    configured = os.environ.get("BROKER_NODE_CONFIG")
    if not configured:
        raise ConfigError("BROKER_NODE_CONFIG is required")
    return Path(configured)
