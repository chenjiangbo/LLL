"""Dedicated IPC ASGI app. Run only on loopback; never mount in the public app.

Credential provisioning and the production launcher are deliberately not
provided here: the terminal-to-Agent credential path still needs validation.
"""
from __future__ import annotations

import hmac
import ipaddress
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr

from broker_node.api_service.ipc_store import IPCStore, SessionError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Hello(StrictModel):
    node_id: StrictStr
    account_mode: StrictStr
    strategy_id: StrictStr
    broker_account_key: StrictStr
    agent_instance_id: StrictStr
    pid: StrictInt
    started_at: StrictStr


class Heartbeat(StrictModel):
    session_id: StrictStr
    node_epoch: StrictStr
    sequence: StrictInt
    callback_counter: StrictInt


class Goodbye(StrictModel):
    session_id: StrictStr
    node_epoch: StrictStr


class Connectivity(StrictModel):
    session_id: StrictStr
    node_epoch: StrictStr
    sequence: StrictInt
    trade_connected: StrictBool
    market_connected: StrictBool
    broker_account_id: StrictStr


class Snapshot(StrictModel):
    session_id: StrictStr
    node_epoch: StrictStr
    message_id: StrictStr
    generation: StrictInt
    batch: dict[str, Any]


class Events(StrictModel):
    session_id: StrictStr
    node_epoch: StrictStr
    message_id: StrictStr
    events: list[dict[str, Any]]


class CommandResult(Goodbye):
    command_id: StrictStr
    status: StrictStr
    result: Any = None
    error: Optional[str] = None


class QuoteTicks(Goodbye):
    ticks: list[dict[str, Any]]


def create_ipc_app(store: IPCStore, expected: dict[str, str], credential: str, max_body_bytes: int, token_provider=None, quote_service=None) -> FastAPI:
    if not isinstance(credential, str) or len(credential.encode('utf-8')) < 32:
        raise ValueError('a dedicated IPC credential of at least 32 bytes is required')
    if isinstance(max_body_bytes, bool) or not isinstance(max_body_bytes, int) or max_body_bytes <= 0:
        raise ValueError('an explicit positive IPC message limit is required')
    if not isinstance(expected.get('broker_account_id'), str) or not expected['broker_account_id']:
        raise ValueError('expected broker account id is required')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def authenticate(request: Request, call_next):
        from fastapi.responses import JSONResponse
        try:
            peer = ipaddress.ip_address(request.client.host if request.client else '')
        except ValueError:
            return JSONResponse(status_code=403, content={'error': 'loopback required'})
        if not peer.is_loopback:
            return JSONResponse(status_code=403, content={'error': 'loopback required'})
        supplied = request.headers.get('authorization', '')
        if not hmac.compare_digest(supplied.encode('utf-8'), ('Bearer ' + credential).encode('utf-8')):
            return JSONResponse(status_code=401, content={'error': 'unauthorized'})
        length = request.headers.get('content-length')
        if length is None or not length.isascii() or not length.isdigit():
            return JSONResponse(status_code=411, content={'error': 'content length required'})
        if int(length) > max_body_bytes:
            return JSONResponse(status_code=413, content={'error': 'message too large'})
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > max_body_bytes or size > int(length):
                return JSONResponse(status_code=413, content={'error': 'message too large'})
            chunks.append(chunk)
        if size != int(length):
            return JSONResponse(status_code=400, content={'error': 'content length mismatch'})
        # Starlette's cached request supplies the already validated body to the
        # downstream ASGI application without reading an unbounded stream.
        request._body = b''.join(chunks)
        return await call_next(request)

    @app.post('/ipc/v2/sessions/hello')
    def hello(request: Hello):
        try:
            return store.hello(request.model_dump(), expected)
        except SessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post('/ipc/v2/bootstrap')
    def bootstrap():
        if token_provider is None:
            raise HTTPException(status_code=503, detail='GM token is unavailable')
        token = token_provider()
        if not isinstance(token, str) or not token:
            raise HTTPException(status_code=503, detail='GM token is unavailable')
        return {'token': token}

    @app.post('/ipc/v2/sessions/heartbeat')
    def heartbeat(request: Heartbeat):
        try:
            store.heartbeat(request.session_id, request.node_epoch, request.sequence, request.callback_counter)
        except SessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {'ack': True}

    @app.post('/ipc/v2/sessions/goodbye')
    def goodbye(request: Goodbye):
        try:
            ended = store.goodbye(request.session_id, request.node_epoch)
        except SessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {'ack': True, 'duplicate': not ended}

    @app.post('/ipc/v2/sessions/connectivity')
    def connectivity(request: Connectivity):
        verified = hmac.compare_digest(request.broker_account_id.encode('utf-8'), expected['broker_account_id'].encode('utf-8'))
        try:
            generation = store.connectivity(request.session_id, request.node_epoch, request.sequence, request.trade_connected, request.market_connected, verified)
        except SessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not verified:
            raise HTTPException(status_code=409, detail='broker account mismatch')
        return {'ack': True, 'generation': generation}

    @app.post('/ipc/v2/facts/snapshot')
    def snapshot(request: Snapshot):
        try:
            account = request.batch.get('account')
            normalized = account.get('normalized') if isinstance(account, dict) else None
            if not isinstance(normalized, dict) or normalized.get('account_id') != expected['broker_account_id']:
                raise SessionError('broker account mismatch')
            inserted = store.ingest_snapshot(request.session_id, request.node_epoch, request.message_id, request.batch, expected['broker_account_id'], request.generation)
            store.reconcile_if_needed(request.session_id, request.node_epoch)
        except (SessionError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {'ack': True, 'committed': True, 'duplicate': not inserted}

    @app.post('/ipc/v2/events/batch')
    def events(request: Events):
        try:
            inserted = store.events(request.session_id, request.node_epoch, request.message_id, request.events)
        except (SessionError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {'ack': True, 'committed': True, 'duplicate': not inserted}

    @app.post('/ipc/v2/commands/claim')
    def claim_command(request: Goodbye):
        try:
            return {'command': store.claim_command(request.session_id, request.node_epoch)}
        except SessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post('/ipc/v2/commands/result')
    def command_result(request: CommandResult):
        try:
            store.command_result(request.session_id, request.node_epoch, request.command_id, request.status, request.result, request.error)
        except SessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {'ack': True}

    @app.post('/ipc/v2/quotes/subscriptions')
    def quote_subscriptions(request: Goodbye):
        try:
            return {'symbols': store.quote_subscriptions(request.session_id, request.node_epoch)}
        except SessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post('/ipc/v2/quotes/ticks')
    def quote_ticks(request: QuoteTicks):
        try:
            store.verify_session(request.session_id, request.node_epoch)
            if quote_service is None:
                raise SessionError('quote service unavailable')
            for tick in request.ticks:
                quote_service.on_tick(tick)
        except (SessionError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {'ack': True}

    return app
