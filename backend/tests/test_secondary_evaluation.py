from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from backend.screening.secondary_eval_engine import (
    _determine_profit_state,
    evaluate_company_evidence,
    evaluate_relative_leadership,
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


def test_free_float_mv_unit_calculation():
    """验证 22 节：自由流通市值单位计算 (free_share 万股 * close 元 / 10000 -> 亿元)"""
    mock_store = MagicMock()
    # 模拟自由股本 50,000 万股 (5亿股), 收盘价 10.0 元
    # 自由流通市值 = 50,000 * 10.0 / 10,000 = 50.0 亿元
    mock_b_row = {"free_share": 50000.0, "turnover_rate": 2.5, "turnover_rate_f": 3.2}
    mock_bar_row = {"close": 10.0, "amount": 150000.0}

    mock_conn = MagicMock()
    mock_store.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.side_effect = [
        MagicMock(fetchone=lambda: mock_b_row),
        MagicMock(fetchone=lambda: mock_bar_row),
    ]

    profile = evaluate_supply_profile(mock_store, "600518.SH", "20260803")
    assert profile["free_float_mv"] == 50.0
    assert profile["supply_profile_label"] == "SMALL_ELASTIC"


def test_leadership_insufficient_evidence_when_bars_missing():
    """验证 19.1 节：数据证据不足时输出 INSUFFICIENT_EVIDENCE 而非 0 分"""
    mock_store = MagicMock()
    mock_conn = MagicMock()
    mock_store.connect.return_value.__enter__.return_value = mock_conn

    # 模拟空 K 线
    mock_conn.execute.return_value.fetchone.return_value = {"raw_json": {"industry": "医药"}}

    import pandas as pd
    with pytest.MonkeyPatch.context() as m:
        m.setattr(pd, "read_sql", lambda sql, conn, params: pd.DataFrame())
        result = evaluate_relative_leadership(mock_store, "600518.SH", "20260803")

    assert result["leadership_state"] == "INSUFFICIENT_EVIDENCE"
    assert result["leadership_rank_value"] is None
    assert result["valid_component_count"] == 0


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

    import pandas as pd
    with pytest.MonkeyPatch.context() as m:
        m.setattr(pd, "read_sql", lambda sql, conn, params: pd.DataFrame())
        res = run_ai_stock_research(mock_store, "600518.SH", "20260803", review_lookback=20, use_web_search=True)

    assert res["ts_code"] == "600518.SH"
    assert res["as_of_date"] == "20260803"
    assert res["priority"] in ["中", "高", "低"]
    assert "康美药业" in res["result_markdown"] or "600518" in res["result_markdown"]
    assert "研究优先级" in res["result_markdown"]
