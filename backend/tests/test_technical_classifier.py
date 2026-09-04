import numpy as np
import pandas as pd

from backend.screening.technical_classifier import _classify_stock, _daily_features, _weekly_stage


def _bars(periods: int = 420, end: str = "2025-08-21") -> pd.DataFrame:
    dates = pd.bdate_range(end=pd.Timestamp(end), periods=periods)
    rng = np.random.default_rng(20260824)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, periods)))
    return pd.DataFrame({
        "asset_code": "000001.SZ",
        "trade_date": dates.strftime("%Y%m%d"),
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "vol": 1_000_000.0,
        "amount": 100_000_000.0,
        "adj_factor": 1.0,
    })


def test_weekly_state_is_historical_and_excludes_incomplete_week() -> None:
    frame = _bars(end="2025-08-21")  # Thursday: current W-FRI is incomplete.
    features = _daily_features(frame)
    current, since, history, daily_map = _weekly_stage(features)

    assert current != "UNAVAILABLE"
    assert since is not None
    assert history
    assert max(item["trade_date"] for item in history) < "20250821"
    assert daily_map["20250821"] == history[-1]["stage"]


def test_order_score_is_ma_order_only_and_cross_metrics_are_separate() -> None:
    frame = _bars()
    features = _daily_features(frame)
    row = features.iloc[-1]
    expected_order = int(row["ma5"] > row["ma10"]) + int(row["ma5"] > row["ma20"]) + int(row["ma10"] > row["ma20"]) + int(row["ma20"] > row["ma30"])
    assert row["order_score"] == expected_order
    assert row["cross_event_count_10d"] >= row["cross_pair_count_10d"]


def test_classifier_returns_a_single_latest_subtype_and_turn_score_type() -> None:
    result = _classify_stock(_bars(), "000001.SZ")
    assert result["trade_date"] == "20250821"
    assert result["weekly_stage"] in {"W1_BASE", "W2_ADVANCE", "W3_TOP", "W4_DECLINE"}
    assert result["daily_subtype"].startswith(result["weekly_stage"][:2])
    assert result["score_type"] in {None, "PREP_SCORE", "TURN_SCORE"}
