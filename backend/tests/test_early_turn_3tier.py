import pytest
from backend.screening.early_turn_engine import EarlyTurnEngine

def test_freshness_zero_score_when_retake_less_than_3():
    """验证当站上均线数小于3 (retake_count < 3) 时，Freshness 算子强制为 0 分且无效"""
    engine = EarlyTurnEngine()
    features = {
        "close": 10.0,
        "ma5": 10.2,
        "ma10": 10.4,
        "ma20": 10.6,
        "ma30": 10.8,
        "ma60": 11.0,
        "atr20": 0.4,
        "retake_count": 1,          # 站上均线不足 3 根
        "days_retake_3ma": 0,       # 0 天
        "turn_episode_state": "PRE_FIRST_TURN",
    }
    res = engine.evaluate_stock("000001.SZ", "20260814", features, prep_score_mode="existing")
    score_detail = res["score_detail_json"]
    assert score_detail["freshness_valid"] is False
    assert score_detail["v2_details"]["freshness"] == 0.0

def test_turn_episode_post_first_wave_transition():
    """验证第一波已走完 (POST_FIRST_WAVE) 时，即使总分较高也提示第一波已完成，退出 A-Pre"""
    engine = EarlyTurnEngine()
    features = {
        "close": 15.0,
        "ma5": 14.8,
        "ma10": 14.6,
        "ma20": 14.4,
        "ma30": 14.0,
        "ma60": 13.0,
        "atr20": 0.5,
        "order_score": 3.5,
        "retake_count": 4,
        "days_retake_3ma": 1,
        "turn_episode_state": "POST_FIRST_WAVE", # 已处于第一波完成阶段
        "first_trigger_date": "20260625",
        "first_trigger_close": 10.0,
        "return_since_first_trigger": 0.50,
    }
    res = engine.evaluate_stock("002550.SZ", "20260814", features, prep_score_mode="existing")
    assert res["turn_episode_state"] == "POST_FIRST_WAVE"
    assert res["signal_status"] == "POST_FIRST_WAVE"
    assert res["state"] == "POST_FIRST_WAVE"
    assert res["entry_extension_state"] == "NOT_APPLICABLE"

def test_structural_damage_flag_caps_at_pre_ready():
    """验证急跌结构受损 (structural_damage_flag = True) 时，最高只能进入 PRE_READY"""
    engine = EarlyTurnEngine()
    features = {
        "close": 10.0,
        "ma5": 9.9,
        "ma10": 9.8,
        "ma20": 9.7,
        "ma30": 9.6,
        "ma60": 12.0,
        "atr20": 0.5,
        "order_score": 3.0,
        "retake_count": 4,
        "days_retake_3ma": 1,
        "turn_episode_state": "FIRST_TURN_WINDOW",
        "structural_damage_flag": True,  # 结构受损
    }
    res = engine.evaluate_stock("002921.SZ", "20260814", features, prep_score_mode="existing")
    assert res["structural_damage_flag"] is True
    assert res["signal_status"] != "EARLY_TURN"
    assert res["signal_status"] in ("PRE_READY", "WATCH", "NO_SIGNAL")

def test_entry_extension_state_decoupled_from_signal_status():
    """验证买点偏离状态 (VERY_EXTENDED / 追高) 独立解耦于信号状态"""
    engine = EarlyTurnEngine()
    features = {
        "close": 55.0,
        "ma5": 50.8,
        "ma10": 50.5,
        "ma20": 50.2,
        "ma30": 50.0,
        "ma60": 45.0,
        "atr20": 1.5,
        "order_score": 3.5,
        "retake_count": 4,
        "days_retake_3ma": 2,
        "turn_type": "FIRST_TURN",
        "cross_pair_count_10d": 4,
        "ma_spread_5d_ago": 2.0,
        "volume_ratio": 1.6,
        "turn_episode_state": "FIRST_TURN_WINDOW",
        "first_trigger_date": "20260810",
        "first_trigger_close": 48.0,
        "return_since_first_trigger": 0.145, # 距触发价涨幅 14.5% (> 8%)
    }
    res = engine.evaluate_stock("301479.SZ", "20260814", features, prep_score_mode="existing")
    assert res["turn_episode_state"] == "FIRST_TURN_WINDOW"
    assert res["signal_status"] == "EARLY_TURN"
    assert res["entry_extension_state"] == "VERY_EXTENDED"


def test_formal_selection_uses_lifecycle_score_and_overextension_is_independent():
    engine = EarlyTurnEngine()
    features = {
        "close": 55.0,
        "ma5": 50.3,
        "ma10": 50.2,
        "ma20": 50.1,
        "ma30": 50.0,
        "ma60": 40.0,
        "atr20": 1.0,
        "order_score": 4.0,
        "retake_count": 4,
        "days_retake_3ma": 1,
        "turn_episode_state": "FIRST_TURN_WINDOW",
        "pct_change_today": 0.16,
        "return_since_first_trigger": 0.12,
        "first_trigger_close": 49.0,
        "cross_pair_count_10d": 3,
        "cross_event_count_10d": 2,
        "ma_spread_5d_ago": 2.0,
        "order_improvement": 1.0,
        "volume_ratio": 1.6,
    }
    res = engine.evaluate_stock("920083.BJ", "20260814", features, prep_score_mode="existing")
    assert res["total_score"] >= 75.0
    assert res["selected"] is True
    assert res["is_overextended"] is True

    features["turn_episode_state"] = "POST_FIRST_WAVE"
    res_post = engine.evaluate_stock("920083.BJ", "20260814", features, prep_score_mode="existing")
    assert res_post["selected"] is False
    assert res_post["is_overextended"] is True


def test_prep_score_does_not_use_legacy_retake_zero_cap():
    engine = EarlyTurnEngine()
    features = {
        "close": 3.11,
        "ma5": 3.63,
        "ma10": 3.51,
        "ma20": 3.35,
        "ma30": 3.45,
        "ma60": 3.8,
        "atr20": 0.12,
        "turn_type": "SECONDARY_TURN",
        "turn_episode_state": "PRE_FIRST_TURN",
        "retake_count": 0,
        "order_score": 4.0,
        "order_improvement": 1.0,
        "cross_pair_count_10d": 3,
        "volume_ratio": 1.6,
        "dist_high_60": 0.30,
    }
    res = engine.evaluate_stock("002047.SZ", "20260819", features, prep_score_mode="existing")
    # PRE 阶段不再走旧七项评分，也不能由 Volume / Space 等滞后项托分。
    assert res["score_type"] == "PREP_SCORE"
    assert res["total_score"] == res["prep_score"]
    assert res["retake_zero_cap"] is False
    assert res["score_detail_json"]["v2_details"]["freshness"] == 0.0
    assert res["score_detail_json"]["v2_details"]["prep"]["retake"] == 0.0


def test_prep_score_rewards_ma_deceleration_without_freshness_or_volume():
    engine = EarlyTurnEngine()
    base = {
        "close": 10.0, "ma5": 9.9, "ma10": 10.0, "ma20": 10.2, "ma30": 10.4,
        "ma60": 11.0, "atr20": 0.5, "turn_episode_state": "PRE_FIRST_TURN",
        "retake_count": 2, "cross_pair_count_10d": 2, "ma_spread_atr": 0.8,
        "return_20d": -0.09, "return_40d": -0.16, "max_drawdown_60d": 0.20,
        "days_since_40d_high": 10, "volume_ratio": 3.0, "days_retake_3ma": 1,
    }
    steep = engine.evaluate_stock("920078.BJ", "20260805", {
        **base,
        "ma10_slope_5d": -0.025, "ma20_slope_5d": -0.020,
        "ma10_slope_prev5": -0.026, "ma20_slope_prev5": -0.021,
    }, prep_score_mode="existing")
    improving = engine.evaluate_stock("920078.BJ", "20260821", {
        **base,
        "ma10_slope_5d": -0.002, "ma20_slope_5d": -0.001,
        "ma10_slope_prev5": -0.018, "ma20_slope_prev5": -0.014,
    }, prep_score_mode="existing")
    assert steep["score_type"] == "PREP_SCORE"
    assert improving["total_score"] > steep["total_score"]
    assert improving["score_detail_json"]["v2_details"]["freshness"] == 0.0
    assert improving["score_detail_json"]["v2_details"]["prep"]["slope_turn"] > steep["score_detail_json"]["v2_details"]["prep"]["slope_turn"]


def test_first_turn_keeps_turn_score_and_75_point_selection_rule():
    engine = EarlyTurnEngine()
    features = {
        "close": 15.0, "ma5": 14.6, "ma10": 14.4, "ma20": 14.2, "ma30": 14.0,
        "ma60": 13.0, "atr20": 0.5, "turn_type": "FIRST_TURN",
        "turn_episode_state": "FIRST_TURN_WINDOW", "retake_count": 4,
        "days_retake_3ma": 1, "order_score": 3.5, "order_improvement": 1.0,
        "cross_pair_count_10d": 3, "ma_spread_5d_ago": 2.0, "volume_ratio": 1.6,
    }
    res = engine.evaluate_stock("000001.SZ", "20260821", features, prep_score_mode="existing")
    assert res["score_type"] == "TURN_SCORE"
    assert res["total_score"] == res["turn_score"]
    assert res["selected"] is (res["turn_score"] >= 75.0)


def test_rounded_prep_scoring_rewards_ma5_without_changing_first_turn_score():
    import pytest
    engine = EarlyTurnEngine()
    features = {
        'close': 10.0, 'ma5': 9.8, 'ma10': 9.7, 'ma20': 10.1, 'ma30': 10.4,
        'ma60': 11.0, 'atr20': 0.5, 'turn_episode_state': 'PRE_FIRST_TURN',
        'retake_count': 2, 'cross_pair_count_10d': 1, 'ma_spread_atr': 1.1,
        'ma10_slope_5d': -0.015, 'ma20_slope_5d': -0.04,
        'ma10_curve_improve': -0.001, 'ma20_curve_improve': 0.02,
        'bottom_structure_type': 'NONE', 'bottom_structure_quality': 'NONE',
        'rounded_repair': {'indicators_available': True, 'ma5_decelerating': True,
                           'ma5_flattened': True, 'ma5_rounded': True, 'ma5_daily_slopes': [-0.01, -0.005, 0.001]},
    }
    result = engine.evaluate_stock('TEST.SZ', '20261109', features, prep_score_mode='rounded')
    breakdown = result['score_detail_json']['v2_details']['prep']['slope_breakdown']
    assert breakdown == {'ma5': 15.0, 'ma10': 4.0, 'ma20': 5.0}
    assert result['score_detail_json']['v2_details']['prep']['slope_turn'] == 24.0
    first = {**features, 'turn_episode_state': 'FIRST_TURN_WINDOW'}
    old = engine.evaluate_stock('TEST.SZ', '20261109', first, prep_score_mode='existing')
    new = engine.evaluate_stock('TEST.SZ', '20261109', first, prep_score_mode='rounded')
    assert new['turn_score'] == old['turn_score']
    assert new['selected'] == old['selected']
    with pytest.raises(ValueError, match='缺少 MA5'):
        engine.evaluate_stock('TEST.SZ', '20261109', {**features, 'rounded_repair': None}, prep_score_mode='rounded')


def test_prep_rewards_uptrend_without_acceleration_and_moderate_expansion():
    features = {
        'close': 10.6, 'ma5': 10.0, 'ma10': 9.95, 'ma20': 10.0, 'ma30': 10.2,
        'ma60': 10.5, 'atr20': 0.5, 'turn_episode_state': 'FIRST_TURN_WINDOW',
        'retake_count': 3, 'cross_pair_count_10d': 3, 'ma_spread_atr': 0.8,
        'ma10_slope_5d': 0.05, 'ma10_curve_improve': -0.005,
        'ma20_slope_5d': -0.004, 'ma20_curve_improve': 0,
        'bottom_structure_type': 'NONE', 'bottom_structure_quality': 'NONE',
        'rounded_repair': {'indicators_available': True, 'ma5_decelerating': False,
                           'ma5_flattened': False, 'ma5_rounded': False,
                           'ma5_daily_slopes': [-0.014, -0.009, 0.01]},
    }
    engine = EarlyTurnEngine()
    result = engine.evaluate_stock('TEST.SZ', '20261109', features)
    prep = result['score_detail_json']['v2_details']['prep']
    assert prep['slope_breakdown']['ma5'] == 10
    assert prep['slope_breakdown']['ma10'] == 15
    assert prep['compression_cross'] == 25
    assert prep['position'] == 5
    far = engine.evaluate_stock('TEST.SZ', '20261109', {**features, 'close': 11.2})
    assert far['score_detail_json']['v2_details']['prep']['position'] == 0
    assert result['turn_score'] == engine.evaluate_stock('TEST.SZ', '20261109', features, prep_score_mode='existing')['turn_score']
