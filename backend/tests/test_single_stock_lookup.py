from __future__ import annotations

import pytest
from backend.screening.early_turn_service import EarlyTurnService


class StockLookupStore:
    def __init__(self, matches):
        self.matches = matches
        self.queries = []

    def connect(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, params):
        self.queries.append((sql, params))
        self.result = self.matches if 'screening_asset_master' in sql else []
        return self

    def fetchall(self):
        return self.result


@pytest.mark.parametrize('value', ['信维通信', '300136', '300136.sz'])
def test_single_stock_lookup_uses_resolved_asset_code(value):
    store = StockLookupStore([{'asset_code': '300136.SZ', 'name': '信维通信', 'industry': '通信设备'}])
    result = EarlyTurnService(store).evaluate_single_stock_range(value, '20261010', '20261110')
    assert result['ts_code'] == '300136.SZ'
    assert result['name'] == '信维通信'
    assert all(params[0] == '300136.SZ' for sql, params in store.queries if 'screening_daily_bar' in sql)


def test_single_stock_lookup_reports_unknown_and_ambiguous_names():
    with pytest.raises(ValueError, match='未找到股票'):
        EarlyTurnService(StockLookupStore([])).evaluate_single_stock_range('不存在', '20261010', '20261110')
    matches = [
        {'asset_code': '000001.SZ', 'name': '同名', 'industry': None},
        {'asset_code': '600001.SH', 'name': '同名', 'industry': None},
    ]
    with pytest.raises(ValueError, match='匹配到多只股票'):
        EarlyTurnService(StockLookupStore(matches)).evaluate_single_stock_range('同名', '20261010', '20261110')
