from backend.screening.secondary_eval_engine import classify_fundamental_filter


def _classify(**overrides):
    payload = {
        "latest_report_period": "20260630",
        "revenue": 100.0,
        "parent_net_profit": 10.0,
        "deducted_net_profit": 8.0,
        "risk_flags": [],
        "fact_tags": [],
        "revenue_yoy": 0.02,
        "parent_profit_state": "PROFIT_GROWING",
        "deducted_profit_state": "PROFIT_GROWING",
    }
    payload.update(overrides)
    return classify_fundamental_filter(**payload)


def test_fundamental_filter_accepts_disclosed_company_without_hard_risk():
    state, reasons = _classify()
    assert state == "FUNDAMENTAL_ACCEPTABLE"
    assert reasons == ["最新报告已披露，未命中硬性经营风险"]


def test_fundamental_filter_marks_positive_operating_evidence():
    state, reasons = _classify(revenue_yoy=0.15)
    assert state == "FUNDAMENTAL_POSITIVE"
    assert reasons


def test_fundamental_filter_prioritizes_hard_risk_over_positive_tags():
    state, reasons = _classify(
        risk_flags=["REVENUE_SHARP_DROP"],
        fact_tags=[{"label": "扭亏", "tone": "POSITIVE"}],
    )
    assert state == "FUNDAMENTAL_RISK"
    assert reasons == ["营收同比大幅下滑"]


def test_fundamental_filter_keeps_missing_data_separate_from_risk():
    state, _ = _classify(
        latest_report_period=None,
        revenue=None,
        parent_net_profit=None,
        deducted_net_profit=None,
    )
    assert state == "FUNDAMENTAL_DATA_INSUFFICIENT"
