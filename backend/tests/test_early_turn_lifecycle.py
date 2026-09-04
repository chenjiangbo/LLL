from __future__ import annotations

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


def test_yalian_failed_first_turn_is_reset_and_does_not_keep_old_trigger() -> None:
    """模拟亚联机械：旧触发跌破 12% 后，后续窗口必须使用新 trigger。"""
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


def test_airo_post_wave_can_reset_after_deep_structural_break() -> None:
    """模拟艾罗能源：深跌后先重建 PRE，再建立新的 Episode。"""
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
    assert features["first_trigger_close"] >= 6.2


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
