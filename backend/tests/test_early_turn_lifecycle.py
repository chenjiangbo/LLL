from __future__ import annotations

import math
import random
from typing import Any

from backend.screening.early_turn_service import EarlyTurnService


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, *_args: Any) -> "_FakeConnection":
        return self

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeStore:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self._rows)


def _descending_daily_rows(prices: list[float]) -> list[dict[str, Any]]:
    # calculate_features_from_bars() 按查询结果倒序读取，再反转为时间正序。
    return [
        {
            "trade_date": f"{idx:08d}",
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "vol": 1000.0,
            "amount": 1000.0,
            "adj_factor": 1.0,
        }
        for idx, price in reversed(list(enumerate(prices)))
    ]


def test_yalian_failed_first_turn_is_reset_and_does_not_keep_old_trigger(monkeypatch) -> None:
    """隔离圆弧识别，验证旧触发失效后后续窗口使用新 trigger。"""
    monkeypatch.setattr('backend.screening.early_turn_service.rounded_ma5_shape', lambda _values: {'ma5_rounded': True, 'ma5_flattened': True, 'ma5_decelerating': True, 'ma5_turning_up': True})
    prices = (
        [10.0] * 60
        + [10.0 + i * 0.25 for i in range(1, 21)]
        + [15.0 - i * 0.4 for i in range(1, 21)]
        + [7.0] * 20
        + [7.0 + i * 0.2 for i in range(1, 30)]
    )
    service = EarlyTurnService(_FakeStore(_descending_daily_rows(prices)))

    features = service.calculate_features_from_bars("002284.SZ", f"{len(prices) - 1:08d}")

    assert features["turn_episode_state"] == "FIRST_TURN_WINDOW"
    assert features["first_trigger_date"] is not None
    assert int(features["first_trigger_date"]) > 100
    # 新一轮必须先经过 PRE 确认，首次触发不再机械地落在反弹第一天。
    assert features["first_trigger_close"] >= 7.2


def test_airo_post_wave_can_reset_after_deep_structural_break(monkeypatch) -> None:
    """隔离圆弧识别，验证深跌后可以建立新的 Episode。"""
    monkeypatch.setattr('backend.screening.early_turn_service.rounded_ma5_shape', lambda _values: {'ma5_rounded': True, 'ma5_flattened': True, 'ma5_decelerating': True, 'ma5_turning_up': True})
    prices = (
        [10.0] * 60
        + [10.0 + i * 0.2 for i in range(1, 21)]
        + [14.0 - i * 0.15 for i in range(1, 8)]
        + [12.8 - i * 0.3 for i in range(1, 21)]
        + [6.0] * 15
        + [6.0 + i * 0.02 for i in range(1, 11)]  # 均线重新靠拢、走平并小幅夺回
        + [6.0 + i * 0.2 for i in range(1, 30)]
    )
    service = EarlyTurnService(_FakeStore(_descending_daily_rows(prices)))

    features = service.calculate_features_from_bars("688717.SH", f"{len(prices) - 1:08d}")

    assert features["turn_episode_state"] == "FIRST_TURN_WINDOW"
    assert features["first_trigger_date"] is not None
    assert int(features["first_trigger_date"]) > 100
    # 逐日均线交叉可让新 PRE 更早成立；重点是触发属于第二轮，
    # 不是依赖某个具体价格阈值。
    assert features["first_trigger_close"] >= 6.0


def test_post_wave_expires_to_outside_after_cooldown() -> None:
    """POST 冷却期结束后，未重建 PRE 的股票必须回到策略外。"""
    prices = (
        [40.0] * 60
        + [40.0 + i * 0.3 for i in range(1, 21)]
        + [47.0 + i * 0.7 for i in range(1, 21)]
        + [60.0 - i * 0.8 for i in range(1, 21)]
        + [44.4] * 20
    )
    service = EarlyTurnService(_FakeStore(_descending_daily_rows(prices)))

    features = service.calculate_features_from_bars("688130.BJ", f"{len(prices) - 1:08d}")

    assert features["turn_episode_state"] == "OUTSIDE_A_PRE"
    assert features["first_trigger_close"] is None
    assert features["close"] == 44.4


def test_post_wave_damage_does_not_become_pre_until_new_pre_structure_forms() -> None:
    """旧轮深度受损后，不能因清空锚点自动变成 PRE。"""
    prices = (
        [10.0] * 60
        + [10.0 + i * 0.25 for i in range(1, 21)]
        + [15.0 - i * 0.20 for i in range(1, 6)]  # 第一波回撤，进入 POST
        + [14.0 - i * 0.35 for i in range(1, 16)]  # 跌破旧基准低点，确认旧轮失效
        + [8.75, 8.60, 8.50, 8.45, 8.40]  # 仍未夺回任一均线，不得成为 PRE
    )
    service = EarlyTurnService(_FakeStore(_descending_daily_rows(prices)))

    features = service.calculate_features_from_bars("605068.SH", f"{len(prices) - 1:08d}")

    assert features["turn_episode_state"] == "OUTSIDE_A_PRE"
    assert features["turn_episode_state"] != "PRE_FIRST_TURN"


def test_ordinary_rally_cannot_open_first_without_a_prior_pre() -> None:
    """普通上涨趋势的站上三根均线，不能从策略外直接进入 FIRST。"""
    prices = [10.0] * 60 + [10.0 + i * 0.25 for i in range(1, 50)]
    service = EarlyTurnService(_FakeStore(_descending_daily_rows(prices)))

    features = service.calculate_features_from_bars("000001.SZ", f"{len(prices) - 1:08d}")

    assert features["turn_episode_state"] == "OUTSIDE_A_PRE"
    assert features["first_trigger_date"] is None


def test_target_day_without_daily_bar_is_not_evaluated_as_current() -> None:
    """正式扫描不能拿停牌前的旧 K 线冒充目标日行情。"""
    prices = [10.0] * 90
    service = EarlyTurnService(_FakeStore(_descending_daily_rows(prices)))

    features = service.calculate_features_from_bars("000001.SZ", "99999999")

    assert features["data_status"] == "DATA_STALE"
    assert features["latest_trade_date"] == f"{len(prices) - 1:08d}"


def test_insufficient_history_is_not_scored_as_flat_preparation() -> None:
    """不足 80 根日K不得因缺失斜率被误认为均线走平。"""
    prices = [10.0] * 79
    service = EarlyTurnService(_FakeStore(_descending_daily_rows(prices)))

    features = service.calculate_features_from_bars("000001.SZ", f"{len(prices) - 1:08d}")

    assert features["data_status"] == "DATA_INSUFFICIENT"
    assert features["valid_bar_count"] == 79


def test_replay_does_not_read_bars_after_target_date() -> None:
    class TimeBoundConnection(_FakeConnection):
        def execute(self, _sql: str, params: tuple[Any, ...]) -> "TimeBoundConnection":
            self._rows = [row for row in self._rows if row['trade_date'] <= params[1]]
            return self

    class TimeBoundStore(_FakeStore):
        def connect(self) -> TimeBoundConnection:
            return TimeBoundConnection(self._rows[:])

    prices = [10.0] * 60 + [10.0 - i * 0.05 for i in range(20)] + [9.0 + i * 0.04 for i in range(30)]
    target = '00000109'
    original = EarlyTurnService(TimeBoundStore(_descending_daily_rows(prices))).calculate_features_from_bars('TEST', target)
    extended = EarlyTurnService(TimeBoundStore(_descending_daily_rows(prices + [25.0, 3.0, 30.0]))).calculate_features_from_bars('TEST', target)
    assert original['cross_pair_count_10d'] == extended['cross_pair_count_10d']
    assert original['turn_episode_state'] == extended['turn_episode_state']
    assert original['first_trigger_date'] == extended['first_trigger_date']


def test_episode_history_keeps_same_first_when_evaluation_date_advances() -> None:
    """跨越 320 根边界，已发生的同一轮 FIRST 不应被滑动起点改写。"""
    class TimeBoundConnection(_FakeConnection):
        def execute(self, _sql: str, params: tuple[Any, ...]) -> "TimeBoundConnection":
            self._rows = [row for row in self._rows if row['trade_date'] <= params[1]]
            if len(params) > 2:
                self._rows = self._rows[:params[2]]
            return self

    class TimeBoundStore(_FakeStore):
        def connect(self) -> TimeBoundConnection:
            return TimeBoundConnection(self._rows[:])

    rng = random.Random(16)
    prices = [10.0]
    for i in range(1, 480):
        prices.append(max(prices[-1] * (1 + 0.011 * math.sin(i / 13) + rng.gauss(0, 0.016)), 1.0))
    service = EarlyTurnService(TimeBoundStore(_descending_daily_rows(prices)))
    earlier = service.calculate_features_from_bars('TEST', '00000429')
    later = service.calculate_features_from_bars('TEST', '00000469')
    assert earlier['turn_episode_state'] == 'POST_FIRST_WAVE'
    assert earlier['first_trigger_date'] == '00000338'
    assert later['last_closed_episode']['first_trigger_date'] == earlier['first_trigger_date']
    assert later['last_closed_episode']['post_enter_date'] == earlier['post_enter_date']
    assert earlier['episode_replay_start_date'] == later['episode_replay_start_date'] == '00000000'


def test_windowed_replay_separates_indicator_warmup_from_lifecycle_start() -> None:
    class WindowConnection(_FakeConnection):
        def execute(self, _sql: str, params: tuple[Any, ...]) -> "WindowConnection":
            self._rows = [
                row for row in self._rows
                if row['trade_date'] <= params[1] and row['trade_date'] >= params[3]
            ]
            return self

    class WindowStore(_FakeStore):
        def connect(self) -> WindowConnection:
            return WindowConnection(self._rows[:])

    prices = [20.0] * 170
    features = EarlyTurnService(WindowStore(_descending_daily_rows(prices))).calculate_features_from_bars(
        'TEST.SZ', '00000150', history_start_date='00000070', replay_start_date='00000090'
    )
    assert features['episode_replay_mode'] == 'WINDOWED_60_TRADING_DAYS'
    assert features['episode_replay_data_start_date'] == '00000070'
    assert features['episode_replay_start_date'] == '00000090'
    assert features['episode_replay_first_evaluation_date'] == '00000090'




def test_early_observation_is_independent_of_formal_episode_and_point_in_time() -> None:
    """A1 仅提供观察提示，不能建立正式 PRE 或改变当日评分。"""
    from backend.screening.early_turn_engine import EarlyTurnEngine

    rng = random.Random(8)
    prices = [20.0] * 80
    for _ in range(80):
        prices.append(max(3, prices[-1] * (1 + rng.gauss(-0.005, 0.025))))
    for _ in range(5):
        prices.append(max(3, prices[-1] * (1 + rng.gauss(0.008, 0.015))))
    rows = _descending_daily_rows(prices)
    day = f"{len(prices) - 1:08d}"
    features = EarlyTurnService(_FakeStore(rows)).calculate_features_from_bars("TEST.SZ", day)
    observation = features["early_observation"]
    assert observation["active"] is True
    assert observation["first_date"] <= day
    assert observation["ma10_slope_5d"] >= -0.025
    assert observation["retake_count"] >= 2
    assert observation["compressed"] or observation["cross_repair"]
    assert features["turn_episode_state"] == "OUTSIDE_A_PRE"
    assert features["first_trigger_date"] is None
    result = EarlyTurnEngine().evaluate_stock("TEST.SZ", day, features)
    assert result["selected"] is False
    assert result["total_score"] == 0

    # 增加目标日之后的行情，不得改变目标日的观察信号。
    class TimeBoundConnection(_FakeConnection):
        def execute(self, _sql: str, params: tuple[Any, ...]) -> "TimeBoundConnection":
            self._rows = [row for row in self._rows if row['trade_date'] <= params[1]]
            return self

    class TimeBoundStore(_FakeStore):
        def connect(self) -> TimeBoundConnection:
            return TimeBoundConnection(self._rows)

    later_rows = _descending_daily_rows(prices + [p * 0.7 for p in prices[-5:]])
    repeated = EarlyTurnService(TimeBoundStore(later_rows)).calculate_features_from_bars("TEST.SZ", day)
    assert repeated["early_observation"] == observation
    assert repeated["turn_episode_state"] == features["turn_episode_state"]


def _rounded_repair_case(seed: int, rebound_bars: int) -> list[float]:
    rng = random.Random(seed)
    prices = [20.0] * 80
    for _ in range(70):
        prices.append(max(3, prices[-1] * (1 + rng.gauss(-0.006, 0.02))))
    for _ in range(rebound_bars):
        prices.append(max(3, prices[-1] * (1 + rng.gauss(0.004 if seed == 3 else 0.003, 0.025))))
    return prices


def test_early_rounded_pre_fails_when_close_loses_both_short_mas() -> None:
    rng = random.Random(15)
    prices = [20.0] * 80
    for _ in range(80):
        prices.append(max(3, prices[-1] * (1 + rng.gauss(-0.005, 0.025))))
    for _ in range(5):
        prices.append(max(3, prices[-1] * (1 + rng.gauss(0.008, 0.015))))
    # 取本序列中确实处于未确认早期 PRE 的历史点，避免随机行情后续自然推进到 FIRST。
    prices = prices[:158]
    entry = EarlyTurnService(_FakeStore(_descending_daily_rows(prices))).calculate_features_from_bars('TEST.SZ', f'{len(prices)-1:08d}')
    assert entry['turn_episode_state'] == 'PRE_FIRST_TURN'
    assert entry['pre_entry_reason'] == 'EARLY_ROUNDED_REPAIR'
    assert entry['pre_confirm_date'] is None
    assert entry['rounded_repair']['ma5_rounded']
    failed_prices = prices + [prices[-1] * 0.97]
    failed = EarlyTurnService(_FakeStore(_descending_daily_rows(failed_prices))).calculate_features_from_bars('TEST.SZ', f'{len(failed_prices)-1:08d}')
    assert failed['turn_episode_state'] == 'OUTSIDE_A_PRE'
    assert failed['last_closed_episode']['end_reason'] == 'EARLY_REPAIR_FAILURE'
    assert failed['last_closed_episode']['pre_enter_date'] == entry['pre_enter_date']


def test_failed_first_attempt_closes_episode_without_becoming_pre_same_day() -> None:
    prices = _rounded_repair_case(3, 7)
    first = EarlyTurnService(_FakeStore(_descending_daily_rows(prices))).calculate_features_from_bars(
        'TEST.SZ', f'{len(prices)-1:08d}'
    )
    assert first['turn_episode_state'] == 'FIRST_TURN_WINDOW'
    assert first['first_wave_formed'] is False

    # 小幅回落后收盘跌回 MA5/MA10 下方，未形成第一波，结束这次 FIRST 尝试。
    failed_prices = prices + [prices[-1] * 0.97]
    failed = EarlyTurnService(_FakeStore(_descending_daily_rows(failed_prices))).calculate_features_from_bars(
        'TEST.SZ', f'{len(failed_prices)-1:08d}'
    )
    assert failed['turn_episode_state'] == 'OUTSIDE_A_PRE'
    assert failed['last_closed_episode']['end_reason'] == 'FIRST_TURN_FAILURE'
    assert 'LOST_MA5_MA10_BEFORE_FIRST_WAVE' in failed['last_closed_episode']['end_signals']
    assert failed['last_closed_episode']['first_trigger_date'] == first['first_trigger_date']


def test_first_waits_when_ma20_five_day_slope_is_too_negative() -> None:
    prices = _rounded_repair_case(3, 6)
    features = EarlyTurnService(_FakeStore(_descending_daily_rows(prices))).calculate_features_from_bars('TEST.SZ', f'{len(prices)-1:08d}')
    assert features['pre_enter_date'] < f'{len(prices)-1:08d}'
    assert features['retake_count'] >= 3 and features['order_score'] >= 2
    assert features['ma5'] > features['ma10']
    assert features['ma20_slope_5d'] < -0.02
    assert features['turn_episode_state'] == 'PRE_FIRST_TURN'
    assert features['first_trigger_date'] is None


def test_sharp_v_rebound_is_not_rounded_repair():
    # 连续下跌后直接急拉，MA5 在急拉前没有低位平缓过渡。
    prices = [20.0] * 80
    for _ in range(25):
        prices.append(prices[-1] * 0.98)
    prices[-1] = prices[-2] * 1.4
    features = EarlyTurnService(_FakeStore(_descending_daily_rows(prices))).calculate_features_from_bars('TEST.SZ', f'{len(prices)-1:08d}')
    assert features['rounded_repair']['above_ma5_ma10']
    assert features['rounded_repair']['ma5_rounded'] is False
    assert features['rounded_repair']['eligible'] is False


def test_ma5_rounded_shape_allows_noise_and_late_reclaim_but_rejects_v():
    from backend.screening.early_turn_service import rounded_ma5_shape

    def values(slopes):
        result = [100.0]
        for slope in slopes:
            result.append(result[-1] * (1 + slope))
        return result

    # 逐步减速，中间轻微反复，已经回升几天后才观察到。
    smooth = [-0.018, -0.015, -0.011, -0.006, -0.003, 0.001, -0.002, 0.004, 0.005]
    assert rounded_ma5_shape(values(smooth))['ma5_rounded']
    # 即使回升当日较强，只要之前有平缓过渡，也不按反弹幅度否决。
    strong_rebound = smooth[:-1] + [0.05]
    assert rounded_ma5_shape(values(strong_rebound))['ma5_rounded']
    # 下跌之后直接急升，中间没有平缓过渡。
    sharp_v = [-0.025, -0.024, -0.022, -0.020, -0.018, -0.016, 0.020, 0.030, 0.040]
    assert not rounded_ma5_shape(values(sharp_v))['ma5_rounded']


def test_decline_context_requires_twenty_percent_and_can_survive_rebound():
    prices = [100.0] * 80 + [90.0] * 10
    outside = EarlyTurnService(_FakeStore(_descending_daily_rows(prices))).calculate_features_from_bars('TEST.SZ', f'{len(prices)-1:08d}')
    assert outside['pre_qualification']['decline_context'] is False
    prices += [78.0, 85.0]
    rebound = EarlyTurnService(_FakeStore(_descending_daily_rows(prices))).calculate_features_from_bars('TEST.SZ', f'{len(prices)-1:08d}')
    assert rebound['pre_qualification']['decline_context'] is True


def test_ma5_rounded_shape_accepts_flat_bottom():
    from backend.screening.early_turn_service import rounded_ma5_shape
    values = [100.0]
    for slope in [-.02, -.018, -.015, -.012, -.010, -.006, -.003, -.001, 0.0]:
        values.append(values[-1] * (1 + slope))
    assert rounded_ma5_shape(values)['ma5_rounded'] is True
