import pytest

from backend.trading.account import TradingDataValidationError, TradingStore


def test_broker_snapshot_rejects_legacy_alias_before_creating_duplicate_position() -> None:
    store = TradingStore.__new__(TradingStore)
    store.list_positions = lambda account_id: [
        {
            "symbol": "600300",
            "security_name": "维维股份",
            "quantity": 300,
            "available_quantity": 300,
            "average_cost": 3.27,
            "market_price": 3.27,
            "broker_snapshot_at": None,
        }
    ]

    with pytest.raises(TradingDataValidationError, match="SH:600300"):
        store.apply_broker_positions_snapshot(
            2,
            [
                {
                    "symbol": "SH:600300",
                    "security_name": "维维股份",
                    "quantity": 300,
                    "available_quantity": 300,
                    "average_cost": 3.27,
                    "market_price": 3.33,
                    "as_of": "2026-09-07T00:30:00+00:00",
                }
            ],
        )
