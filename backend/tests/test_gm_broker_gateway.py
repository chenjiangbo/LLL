import json
from urllib.request import Request

import pytest

from backend.trading.gm_broker_gateway import GMBrokerHttpGateway, BrokerNodeRequestError


def test_gateway_requires_explicit_endpoint(monkeypatch):
    monkeypatch.delenv("BROKER_NODE_URL", raising=False)
    monkeypatch.delenv("BROKER_NODE_API_TOKEN", raising=False)
    gateway = GMBrokerHttpGateway("http://node")
    assert gateway.base_url == "http://node"


def test_gateway_maps_read_and_order_routes(monkeypatch):
    gateway = GMBrokerHttpGateway("http://node")
    seen = []

    def fake_open(request, timeout):
        seen.append((request.method, request.full_url, json.loads(request.data) if request.data else None, request.headers.get("Authorization")))
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"payload": []}'
        return Response()

    monkeypatch.setattr("backend.trading.gm_broker_gateway.urlopen", fake_open)
    assert gateway.get_positions() == []
    gateway.submit_order({"request_id": "r", "client_order_id": "c"})
    assert seen[0][1].endswith("/api/v1/positions")
    assert seen[1][0] == "POST"
    assert all(item[3] is None for item in seen)


def test_gateway_surfaces_http_error(monkeypatch):
    gateway = GMBrokerHttpGateway("http://node")
    def fail(*args, **kwargs):
        raise BrokerNodeRequestError(409, {"code": "IDEMPOTENCY_CONFLICT"})
    monkeypatch.setattr(gateway, "_request", fail)
    with pytest.raises(BrokerNodeRequestError):
        gateway.connect()
