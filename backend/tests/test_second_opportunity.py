import pandas as pd

from backend.screening.early_turn_service import detect_second_opportunity, first_wave_meets_criteria


def _bars():
    # 完成一波上涨后先回落，再横盘及向上突破。
    return pd.DataFrame([
        {'trade_date': f'{i:08d}', 'high': high, 'low': low, 'close': close, 'ma5': ma5, 'ma10': ma10}
        for i, (high, low, close, ma5, ma10) in enumerate([
            (110, 100, 108, 105, 104), (120, 108, 118, 109, 106),
            (118, 110, 112, 111, 109), (114, 106, 108, 110, 109),
            (111, 107, 109, 109, 109), (112, 107, 110, 109, 109),
            (113, 108, 111, 109.5, 109.5), (113, 108, 111, 110, 109.5),
            (116, 109, 115, 111, 110),
        ])
    ])


def test_second_opportunity_distinguishes_recovery_and_breakout():
    df = _bars()
    candidate = detect_second_opportunity(df, base_low=100, first_idx=0, post_idx=2)
    assert candidate['active']
    assert set(candidate['types']) == {'PULLBACK_RECOVERY', 'CONSOLIDATION_BREAKOUT'}
    earlier = detect_second_opportunity(df.iloc[:4], base_low=100, first_idx=0, post_idx=2)
    assert not earlier['active']  # 未到观察条件不能借用未来行情


def test_broken_base_and_weak_wave_do_not_make_second_opportunity():
    df = _bars()
    broken = df.copy()
    broken.loc[3, 'close'] = 97
    assert not detect_second_opportunity(broken, base_low=100, first_idx=0, post_idx=2)['active']
    assert not detect_second_opportunity(df, base_low=110, first_idx=0, post_idx=2)['active']


def test_candidate_is_not_disabled_after_sixty_post_days():
    df = _bars()
    extra = pd.concat([df.iloc[[-1]]] * 65, ignore_index=True)
    extended = pd.concat([df, extra], ignore_index=True)
    extended.loc[len(extended) - 1, 'close'] = 116
    assert detect_second_opportunity(extended, base_low=100, first_idx=0, post_idx=2)['active']


def test_first_wave_requires_both_percentage_and_atr():
    assert not first_wave_meets_criteria(0.199, 8.0)
    assert not first_wave_meets_criteria(0.50, 3.99)
    assert first_wave_meets_criteria(0.20, 4.0)
