from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from backend.screening.secondary_eval_engine import (
    _build_company_fact_tags,
    _determine_profit_state,
    evaluate_company_evidence,
    evaluate_supply_profile,
)
from backend.screening.ths_concept_service import check_data_capabilities, get_stock_ths_concepts


def test_financial_loss_state_transitions():
    """验证 7.2 节：亏损与盈利状态精准判定"""
    # 1. 亏损 -> 盈利 (TURNAROUND)
    assert _determine_profit_state(curr=2000.0, last=-5000.0, yoy=1.4) == "TURNAROUND"

    # 2. 亏损 -> 亏损收窄 (LOSS_NARROWING)
    assert _determine_profit_state(curr=-1000.0, last=-3000.0, yoy=0.66) == "LOSS_NARROWING"

    # 3. 亏损 -> 亏损扩大 (LOSS_WIDENING)
    assert _determine_profit_state(curr=-5000.0, last=-2000.0, yoy=-1.5) == "LOSS_WIDENING"

    # 4. 盈利 -> 亏损 (TURN_TO_LOSS)
    assert _determine_profit_state(curr=-500.0, last=2000.0, yoy=-1.25) == "TURN_TO_LOSS"

    # 5. 盈利 -> 盈利增长
    assert _determine_profit_state(curr=3000.0, last=2000.0, yoy=0.5) == "PROFIT_GROWING"


def test_qoq_turnaround_is_not_mislabeled_as_yoy_turnaround():
    """上一季度亏损、去年同期盈利时，只能标注环比由亏转盈。"""
    facts = [
        {"period": "20260331", "quarter": "2026Q1", "parent_net_profit": 2236.0, "operating_cashflow": 5259.0},
        {"period": "20251231", "quarter": "2025Q4", "parent_net_profit": -1889.0, "operating_cashflow": -3391.0},
        {"period": "20250331", "quarter": "2025Q1", "parent_net_profit": 3023.0, "operating_cashflow": 5809.0},
    ]
    tags = _build_company_fact_tags(facts, {}, {})
    labels = {tag["label"] for tag in tags}
    assert "环比由亏转盈" in labels
    assert "同比扭亏" not in labels
    assert _determine_profit_state(2236.0, 3023.0, -0.26) == "PROFIT_DECLINING"


def test_company_evidence_identifies_deducted_loss_widening_separately():
    """归母亏损收窄、扣非亏损扩大时，风险来源必须明确为扣非口径。"""
    mock_store = MagicMock()
    mock_store.get_company_financial_periods_pit.return_value = {
        "income_rows": [
            {"end_date": "20260630", "available_date": "20260811", "ann_date": "20260811", "total_revenue": 493101109.19, "n_income_attr_p": -1759780.90},
            {"end_date": "20260331", "available_date": "20260422", "ann_date": "20260422", "total_revenue": 261607639.95, "n_income_attr_p": -1033903.38},
            {"end_date": "20250630", "available_date": "20250811", "ann_date": "20250811", "total_revenue": 400000000.0, "n_income_attr_p": -4000000.0},
            {"end_date": "20250331", "available_date": "20250422", "ann_date": "20250422", "total_revenue": 200000000.0, "n_income_attr_p": -2500000.0},
        ],
        "cashflow_rows": [],
        "indicator_rows": [
            {"end_date": "20260630", "available_date": "20260811", "ann_date": "20260811", "profit_dedt": -2971690.39},
            {"end_date": "20260331", "available_date": "20260422", "ann_date": "20260422", "profit_dedt": -1388513.81},
            {"end_date": "20250630", "available_date": "20250811", "ann_date": "20250811", "profit_dedt": -2000000.0},
            {"end_date": "20250331", "available_date": "20250422", "ann_date": "20250422", "profit_dedt": -1000000.0},
        ],
        "forecast": None,
        "express": None,
    }
    mock_store.get_company_financial_pit.return_value = {}

    evidence = evaluate_company_evidence(mock_store, "300437.SZ", "20260827")

    assert evidence["parent_profit_state"] == "LOSS_NARROWING"
    assert evidence["deducted_profit_state"] == "LOSS_WIDENING"
    assert evidence["risk_flags_json"] == ["DEDUCTED_LOSS_WIDENING"]


def test_free_float_mv_unit_calculation():
    """验证 22 节：自由流通市值单位计算 (free_share 万股 * close 元 / 10000 -> 亿元)"""
    mock_store = MagicMock()
    # 模拟自由股本 50,000 万股 (5亿股), 收盘价 10.0 元
    # 自由流通市值 = 50,000 * 10.0 / 10,000 = 50.0 亿元
    mock_b_row = {"free_share": 50000.0, "turnover_rate": 2.5, "turnover_rate_f": 3.2}
    mock_bar_row = {"close": 10.0, "amount": 150000.0}
    mock_store.get_supply_events_pit.return_value = {
        "unlock_30d": 0.0,
        "unlock_60d": 0.0,
        "unlock_90d": 0.0,
        "recent_reduction_flag": False,
    }

    mock_conn = MagicMock()
    mock_store.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.side_effect = [
        MagicMock(fetchone=lambda: mock_b_row),
        MagicMock(fetchone=lambda: mock_bar_row),
        MagicMock(fetchone=lambda: {"amount_median_20": 150000.0}),
    ]

    profile = evaluate_supply_profile(mock_store, "600518.SH", "20260803")
    assert profile["free_float_mv"] == 50.0
    assert profile["supply_profile_label"] == "SMALL_ELASTIC"


def test_company_evidence_rebuilds_v3_amount_fields_from_source_data():
    mock_store = MagicMock()
    mock_store.get_company_financial_periods_pit.return_value = {
        "income_rows": [
            {
                "end_date": "20260630",
                "available_date": "20260808",
                "ann_date": "20260808",
                "total_revenue": 750.0,
                "oper_cost": 350.0,
                "n_income_attr_p": 150.0,
            },
            {
                "end_date": "20260331",
                "available_date": "20260424",
                "ann_date": "20260424",
                "total_revenue": 350.0,
                "oper_cost": 160.0,
                "n_income_attr_p": 80.0,
            },
        ],
        "cashflow_rows": [
            {"end_date": "20260630", "available_date": "20260808", "ann_date": "20260808", "n_cashflow_act": 110.0},
            {"end_date": "20260331", "available_date": "20260424", "ann_date": "20260424", "n_cashflow_act": 45.0},
        ],
        "indicator_rows": [
            {
                "end_date": "20260630",
                "available_date": "20260808",
                "ann_date": "20260808",
                "profit_dedt": 140.0,
                "dt_netprofit_yoy": 10.0,
                "grossprofit_margin": 53.3,
            },
            {
                "end_date": "20260331",
                "available_date": "20260424",
                "ann_date": "20260424",
                "profit_dedt": 75.0,
                "dt_netprofit_yoy": 8.0,
                "grossprofit_margin": 54.2,
            },
        ],
        "forecast": None,
        "express": None,
    }
    mock_store.get_company_financial_pit.return_value = {
        "income": {"end_date": "20260630"},
        "indicator": {"dt_netprofit_yoy": 10.0, "grossprofit_margin": 53.3},
    }

    evidence = evaluate_company_evidence(mock_store, "002550.SZ", "20260814")
    latest = evidence["quarter_facts_json"][0]

    assert latest["quarter"] == "2026Q2"
    assert latest["revenue"] == 400.0
    assert latest["gross_profit"] == 210.0
    assert latest["deducted_net_profit"] == 65.0
    assert latest["operating_cashflow"] == 65.0
    assert evidence["deducted_net_profit"] == 65.0
    assert "deducted_net_profit_amount" not in evidence["data_quality_json"]["missing_fields"]
    assert "gross_profit_amount" not in evidence["data_quality_json"]["missing_fields"]


def test_ths_permission_and_capabilities_status():
    """验证 26 节：系统数据能力检测 (Data Capability Check)"""
    caps = check_data_capabilities()
    assert "tushare_points_detected" in caps
    assert "ths_index" in caps
    assert "ths_member" in caps
    assert caps["sw_industry"] == "READY"


def test_kangmei_pharmacutical_case_regression():
    """验证 66 节：康美药业 (600518.SH @ 2026-08-03) 案例回归测试"""
    from backend.screening.ai_deep_research_service import run_ai_stock_research

    mock_store = MagicMock()
    mock_conn = MagicMock()
    mock_store.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchone.return_value = None
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_store.get_company_financial_periods_pit.return_value = {
        "income": [],
        "indicator": [],
        "cashflow": [],
        "forecast": None,
        "express": None,
    }
    mock_store.get_company_financial_pit.return_value = {}
    mock_store.get_supply_events_pit.return_value = {
        "unlock_30d": None,
        "unlock_60d": None,
        "unlock_90d": None,
        "recent_reduction_flag": None,
    }

    import pandas as pd
    from backend.screening import ai_deep_research_service

    mock_report = "# 研究结论\n\n研究优先级：中\n\n一句话结论：保留观察\n\n## 9. 不确定性\n- 不确定性1"

    with pytest.MonkeyPatch.context() as m:
        m.setattr(pd, "read_sql", lambda sql, conn, params: pd.DataFrame())
        m.setattr(
            ai_deep_research_service,
            "_call_ai3_final_research",
            lambda **kwargs: (mock_report, "中", ["不确定性1"], "gpt-test-model"),
        )
        m.setattr(
            ai_deep_research_service,
            "get_or_create_market_memory",
            lambda store, date, lookback_sessions: ({"themes": []}, "市场记忆摘要"),
        )
        m.setattr(
            ai_deep_research_service,
            "match_stock_theme",
            lambda **kwargs: {"no_active_theme_match": True, "primary_active_theme": None},
        )
        res = run_ai_stock_research(mock_store, "600518.SH", "20260803", review_lookback=20, use_web_search=True)

    assert res["ts_code"] == "600518.SH"
    assert res["as_of_date"] == "20260803"
    assert res["priority"] in ["中", "高", "低", "证据不足"]
    assert "研究结论" in res["result_markdown"]
