"""Agent-side IPC transport; caller supplies credentials without file access."""
from __future__ import annotations

import http.client
import ipaddress
import json
import math
from typing import Any


class IPCError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class IPCClient:
    def __init__(self, host: str, port: int, credential: str, timeout_seconds: float, max_response_bytes: int):
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError('IPC host must be a loopback IP literal') from exc
        if not address.is_loopback or isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError('invalid IPC endpoint')
        if not isinstance(credential, str) or len(credential.encode('utf-8')) < 32:
            raise ValueError('dedicated IPC credential required')
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError('finite positive IPC timeout required')
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or max_response_bytes <= 0:
            raise ValueError('explicit IPC response limit required')
        self.host, self.port, self._credential = host, port, credential
        self.timeout_seconds, self.max_response_bytes = timeout_seconds, max_response_bytes
        self.session = None

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout_seconds)
        try:
            connection.request('POST', path, body=data, headers={'Authorization': 'Bearer ' + self._credential, 'Content-Type': 'application/json'})
            response = connection.getresponse()
            body = response.read(self.max_response_bytes + 1)
            if len(body) > self.max_response_bytes:
                raise IPCError('IPC response exceeds configured limit')
            if response.status != 200:
                raise IPCError('IPC request failed with HTTP %s' % response.status, response.status)
            parsed = json.loads(body.decode('utf-8'))
            if not isinstance(parsed, dict):
                raise IPCError('invalid IPC response')
            return parsed
        except (OSError, http.client.HTTPException, UnicodeError, ValueError) as exc:
            raise IPCError('IPC transport failed') from exc
        finally:
            connection.close()

    def hello(self, identity: dict[str, Any]) -> None:
        if self.session is not None:
            raise IPCError('session already registered')
        data = self._post('/ipc/v2/sessions/hello', identity)
        if set(data) != {'session_id', 'node_epoch'} or any(not isinstance(data[k], str) or not data[k] for k in data):
            raise IPCError('invalid session response')
        self.session = data

    def bootstrap_token(self) -> str:
        result = self._post('/ipc/v2/bootstrap', {})
        token = result.get('token')
        if not isinstance(token, str) or not token:
            raise IPCError('GM token unavailable')
        return token

    def _envelope(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.session is None:
            raise IPCError('session not registered')
        return dict(self.session, **payload)

    def heartbeat(self, sequence: int, callback_counter: int) -> None:
        result = self._post('/ipc/v2/sessions/heartbeat', self._envelope({'sequence': sequence, 'callback_counter': callback_counter}))
        if result.get('ack') is not True:
            raise IPCError('heartbeat not acknowledged')

    def connectivity(self, sequence: int, trade_connected: bool, market_connected: bool, broker_account_id: str) -> int:
        result = self._post('/ipc/v2/sessions/connectivity', self._envelope({
            'trade_connected': trade_connected, 'market_connected': market_connected,
            'broker_account_id': broker_account_id, 'sequence': sequence,
        }))
        if result.get('ack') is not True:
            raise IPCError('connection state not acknowledged')
        generation = result.get('generation')
        if type(generation) is not int or generation <= 0:
            raise IPCError('invalid connection generation')
        return generation

    def goodbye(self) -> None:
        result = self._post('/ipc/v2/sessions/goodbye', self._envelope({}))
        if result.get('ack') is not True:
            raise IPCError('goodbye not acknowledged')
        self.session = None

    def snapshot(self, message_id: str, batch: dict[str, Any], generation: int) -> dict[str, Any]:
        result = self._post('/ipc/v2/facts/snapshot', self._envelope({'message_id': message_id, 'batch': batch, 'generation': generation}))
        if result.get('ack') is not True or result.get('committed') is not True:
            raise IPCError('snapshot not committed')
        return result

    def events(self, message_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        result = self._post('/ipc/v2/events/batch', self._envelope({'message_id': message_id, 'events': events}))
        if result.get('ack') is not True or result.get('committed') is not True:
            raise IPCError('event batch not committed')
        return result

    def claim_command(self):
        return self._post('/ipc/v2/commands/claim', self._envelope({}))['command']

    def command_result(self, command_id, status, result=None, error=None):
        response = self._post('/ipc/v2/commands/result', self._envelope(dict(command_id=command_id, status=status, result=result, error=error)))
        if response.get('ack') is not True:
            raise IPCError('command result not acknowledged')

    def quote_subscriptions(self):
        result = self._post('/ipc/v2/quotes/subscriptions', self._envelope({}))
        return result['symbols']

    def quote_ticks(self, ticks):
        result = self._post('/ipc/v2/quotes/ticks', self._envelope({'ticks': ticks}))
        if result.get('ack') is not True:
            raise IPCError('quote ticks not acknowledged')
