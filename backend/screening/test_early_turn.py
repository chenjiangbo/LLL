import pytest
from backend.screening.early_turn_engine import EarlyTurnEngine
from backend.screening.early_turn_service import EarlyTurnService, BUILTIN_POSITIVE_SAMPLES


def test_early_turn_engine_calculation():
    engine = EarlyTurnEngine()
    features = {
        "close": 10.5,
        "adj_close": 10.5,
        "ma5": 10.4,
        "ma10": 10.3,
        "ma20": 10.2,
        "ma30": 10.1,
        "ma60": 9.8,
        "atr20": 0.3,
        "ma20_slope_10": -0.01,
        "cross_pair_count_10d": 4,
        "cross_event_count_10d": 6,
        "order_score_5d_ago": 1.0,
        "slope5_3d": 0.02,
        "slope10_5d": 0.01,
        "slope20_5d": 0.005,
        "slope30_5d": 0.0,
        "retake_count_3d_ago": 1,
        "higher_low": True,
        "amount_preheat": 1.3,
    }

    res = engine.evaluate_stock("600683.SH", "20260807", features)

    assert res["ts_code"] == "600683.SH"
    assert res["total_score"] >= 65.0
    assert res["state"] in ("EARLY_TURN", "PRE_READY")
    assert res["is_overextended"] is False
    assert "compression" in res["score_detail_json"]
    assert "knot" in res["score_detail_json"]
    assert res["score_detail_json"]["cross_pair_count_10d"] == 4


def test_builtin_positive_samples_defined():
    assert len(BUILTIN_POSITIVE_SAMPLES) >= 5
    codes = [s["ts_code"] for s in BUILTIN_POSITIVE_SAMPLES]
    assert "600683.SH" in codes
