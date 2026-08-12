import pytest
from fastapi.testclient import TestClient
from backend.market_review.api import create_app, _MARKET_QUOTES_CACHE

client = TestClient(create_app())

@pytest.fixture(autouse=True)
def mock_cache():
    _MARKET_QUOTES_CACHE["timestamp"] = 9999999999.0
    _MARKET_QUOTES_CACHE["data"] = [
        {
            "code": "300626",
            "name": "华瑞股份",
            "price": 35.69,
            "pct_chg": 12.76,
            "change": 4.04,
            "volume": 10000.0,
            "amount": 350000.0,
            "amplitude": 5.0,
            "turnover": 3.0,
            "speed": 0.08,
            "net_quantity": 0.64,
            "net_inflow": 39684600.0,
            "open": 31.65,
            "high": 36.00,
            "low": 31.00,
            "pre_close": 31.65,
        },
        {
            "code": "600000",
            "name": "浦发银行",
            "price": 10.00,
            "pct_chg": 1.50,
            "change": 0.15,
            "volume": 20000.0,
            "amount": 200000.0,
            "amplitude": 2.0,
            "turnover": 0.5,
            "speed": 0.01,
            "net_quantity": 0.10,
            "net_inflow": 5000000.0,
            "open": 9.85,
            "high": 10.10,
            "low": 9.80,
            "pre_close": 9.85,
        },
        {
            "code": "688001",
            "name": "华兴源创",
            "price": 25.00,
            "pct_chg": -2.00,
            "change": -0.50,
            "volume": 5000.0,
            "amount": 125000.0,
            "amplitude": 3.0,
            "turnover": 1.2,
            "speed": -0.05,
            "net_quantity": -0.20,
            "net_inflow": -1000000.0,
            "open": 25.50,
            "high": 25.80,
            "low": 24.80,
            "pre_close": 25.50,
        }
    ]

def test_market_quotes_default():
    response = client.get("/api/market/quotes")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3
    assert data["items"][0]["code"] == "300626"

def test_market_quotes_filter_keyword():
    response = client.get("/api/market/quotes?keyword=300626")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "华瑞股份"

def test_market_quotes_board_filter():
    response = client.get("/api/market/quotes?board=cyb")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["code"] == "300626"

def test_market_quotes_pagination():
    response = client.get("/api/market/quotes?offset=0&limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["has_more"] is True

    response2 = client.get("/api/market/quotes?offset=2&limit=2")
    assert response2.status_code == 200
    data2 = response2.json()
    assert len(data2["items"]) == 1
    assert data2["has_more"] is False

def test_suggest_market_stocks():
    response = client.get("/api/market/suggest?query=300")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["code"] == "300626"
