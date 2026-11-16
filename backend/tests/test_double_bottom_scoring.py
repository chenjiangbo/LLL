import pandas as pd
import pytest

from backend.screening.early_turn_engine import EarlyTurnEngine
from backend.screening.early_turn_service import detect_bottom_structure


def _bars(gap: int) -> pd.DataFrame:
    rows = []
    for i in range(65):
        low = 11.5 + 0.001 * i
        rows.append({'trade_date': f'{i:08d}', 'low': low, 'high': low + 0.3,
                     'close': low + 0.2, 'ma5': 11.0, 'atr20': 1.0})
    rows[10].update(low=10.0, close=10.2, high=10.4)
    rows[10 + gap].update(low=10.1, close=10.3, high=10.5)
    return pd.DataFrame(rows)


@pytest.mark.parametrize('gap,expected', [(3, 'MICRO_DOUBLE_BOTTOM'), (7, 'MICRO_DOUBLE_BOTTOM'), (8, 'STANDARD_DOUBLE_BOTTOM'), (30, 'STANDARD_DOUBLE_BOTTOM')])
def test_classification_confirmation_and_twenty_day_lifetime(gap, expected):
    bars = _bars(gap)
    second = 10 + gap
    assert detect_bottom_structure(bars, second + 1)['bottom_structure_type'] == 'NONE'
    confirmed = detect_bottom_structure(bars, second + 2)
    assert confirmed['bottom_structure_type'] == expected
    assert confirmed['bottom_structure_confirmed_date'] == f'{second + 2:08d}'
    assert detect_bottom_structure(bars, second + 22)['bottom_structure_type'] == expected
    assert detect_bottom_structure(bars, second + 23)['bottom_structure_type'] == 'NONE'
    # 失败周期之后不能沿用失败前确认的形态。
    assert detect_bottom_structure(bars, second + 3, confirmed_after=f'{second + 2:08d}')['bottom_structure_type'] == 'NONE'


def test_intraday_wick_does_not_invalidate_but_confirmed_close_does():
    bars = _bars(10)
    bars.loc[24, 'low'] = 9.9
    bars.loc[24, 'close'] = 10.0
    assert detect_bottom_structure(bars, 24)['bottom_structure_type'] == 'STANDARD_DOUBLE_BOTTOM'
    bars.loc[24, 'low'] = 9.80
    bars.loc[24, 'close'] = 9.84
    assert detect_bottom_structure(bars, 24)['bottom_structure_type'] == 'NONE'
    # 之后的破位不能反向改写之前的历史结果。
    assert detect_bottom_structure(bars, 22)['bottom_structure_type'] == 'STANDARD_DOUBLE_BOTTOM'


def test_double_bottom_bonus_applies_once_to_preparation_and_not_turn_score():
    engine = EarlyTurnEngine()
    f = {'close': 10.0, 'ma5': 9.8, 'ma10': 9.7, 'ma20': 10.1, 'ma30': 10.4,
         'ma60': 11.0, 'atr20': 0.5, 'turn_episode_state': 'PRE_FIRST_TURN',
         'retake_count': 2, 'cross_pair_count_10d': 1, 'ma_spread_atr': 1.1,
         'ma10_slope_5d': -0.015, 'ma20_slope_5d': -0.04,
         'ma10_curve_improve': -0.001, 'ma20_curve_improve': 0.02,
         'rounded_repair': {'indicators_available': True, 'ma5_decelerating': True,
                            'ma5_flattened': True, 'ma5_rounded': True, 'ma5_daily_slopes': [-0.01, -0.005, 0.001]},
         'bottom_structure_type': 'NONE', 'bottom_structure_quality': 'NONE'}
    def run(**updates):
        return engine.evaluate_stock('TEST.SZ', '20261109', {**f, **updates})
    base = run()
    short = run(bottom_structure_type='MICRO_DOUBLE_BOTTOM', bottom_structure_quality='CLEAR')
    possible = run(bottom_structure_type='STANDARD_DOUBLE_BOTTOM', bottom_structure_quality='POSSIBLE', bottom_structure_age_bars=0, bottom_structure_confirmed_date='20261109')
    clear = run(bottom_structure_type='STANDARD_DOUBLE_BOTTOM', bottom_structure_quality='CLEAR', bottom_structure_age_bars=0, bottom_structure_confirmed_date='20261109')
    assert short['prep_score'] == base['prep_score']
    assert possible['prep_score'] == min(100, base['prep_score'] + 2)
    assert clear['prep_score'] == min(100, base['prep_score'] + 5)
    assert clear['score_detail_json']['v2_details']['prep']['bottom_bonus'] == 5
    outside = run(turn_episode_state='OUTSIDE_A_PRE', bottom_structure_type='STANDARD_DOUBLE_BOTTOM', bottom_structure_quality='CLEAR', bottom_structure_age_bars=0, bottom_structure_confirmed_date='20261109')
    assert outside['prep_score'] == clear['prep_score']
    assert outside['turn_episode_state'] == 'OUTSIDE_A_PRE' and outside['total_score'] == 0
    assert outside['selected'] is False
    first_base = run(turn_episode_state='FIRST_TURN_WINDOW')
    first_clear = run(turn_episode_state='FIRST_TURN_WINDOW', bottom_structure_type='STANDARD_DOUBLE_BOTTOM', bottom_structure_quality='CLEAR', bottom_structure_age_bars=0, bottom_structure_confirmed_date='20261109')
    assert first_clear['turn_score'] == first_base['turn_score']
    assert first_clear['selected'] == first_base['selected']


def test_future_or_expired_daily_structure_cannot_receive_bonus():
    engine = EarlyTurnEngine()
    features = {'close': 10.0, 'ma5': 9.8, 'ma10': 9.7, 'ma20': 10.1, 'ma30': 10.4,
                'ma60': 11.0, 'atr20': 0.5, 'turn_episode_state': 'PRE_FIRST_TURN',
                'rounded_repair': {'indicators_available': True, 'ma5_decelerating': True,
                                   'ma5_flattened': True, 'ma5_rounded': True, 'ma5_daily_slopes': [-0.01, -0.005, 0.001]},
                'bottom_structure_type': 'STANDARD_DOUBLE_BOTTOM', 'bottom_structure_quality': 'CLEAR'}
    with pytest.raises(ValueError, match='确认日期或有效期无效'):
        engine.evaluate_stock('TEST.SZ', '20261109', {**features, 'bottom_structure_age_bars': 0, 'bottom_structure_confirmed_date': '20261110'})
    with pytest.raises(ValueError, match='确认日期或有效期无效'):
        engine.evaluate_stock('TEST.SZ', '20261109', {**features, 'bottom_structure_age_bars': 21, 'bottom_structure_confirmed_date': '20261001'})


def test_daily_bonus_is_capped_at_100_and_discloses_applied_amount():
    engine = EarlyTurnEngine()
    f = {'close': 10.0, 'ma5': 9.8, 'ma10': 9.7, 'ma20': 10.0, 'ma30': 10.2,
         'ma60': 11.0, 'atr20': 1.0, 'turn_episode_state': 'PRE_FIRST_TURN',
         'retake_count': 4, 'cross_pair_count_10d': 3, 'ma_spread_atr': 0.5,
         'ma10_slope_5d': 0.0, 'ma20_slope_5d': 0.0,
         'ma10_curve_improve': 0.02, 'ma20_curve_improve': 0.02,
         'return_20d': -0.10, 'days_since_40d_high': 10,
         'rounded_repair': {'indicators_available': True, 'ma5_decelerating': True,
                            'ma5_flattened': True, 'ma5_rounded': True, 'ma5_daily_slopes': [-0.01, -0.005, 0.001]},
         'bottom_structure_type': 'STANDARD_DOUBLE_BOTTOM', 'bottom_structure_quality': 'CLEAR',
         'bottom_structure_age_bars': 0, 'bottom_structure_confirmed_date': '20261109'}
    result = engine.evaluate_stock('TEST.SZ', '20261109', f)
    p = result['score_detail_json']['v2_details']['prep']
    assert p['base_score'] == 100
    assert p['bottom_bonus_before_cap'] == 5
    assert p['bottom_bonus'] == 0
    assert result['prep_score'] == 100
