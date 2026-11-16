import pytest
from backend.screening.early_turn_service import EARLY_TURN_CONFIG_VERSION, EarlyTurnService


class _Connection:
    def __init__(self, store): self.store = store
    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def execute(self, sql, params):
        if 'select run_name, notes from early_turn_run' in sql:
            self.one = {'run_name': '历史批次', 'notes': None}; self.rows = []
        elif 'select ts_code from early_turn_result' in sql:
            self.rows = [{'ts_code': '300136.SZ'}]; self.one = None
        else:
            self.rows = []; self.one = None
        return self
    def fetchone(self): return self.one
    def fetchall(self): return self.rows


class _Store:
    def __init__(self): self.created = []; self.finished = []
    def connect(self): return _Connection(self)
    def create_early_turn_run(self, **kwargs): self.created.append(kwargs)
    def save_early_turn_results(self, _results): pass
    def finish_early_turn_run(self, run_id, **kwargs): self.finished.append((run_id, kwargs))
    def reset_early_turn_run(self, **_kwargs): raise AssertionError('历史批次不得重置')


def test_reevaluate_creates_new_versioned_batch_without_overwriting_history():
    store = _Store()
    result = EarlyTurnService(store).run('20261110', run_id='historical_run')
    assert result['run_id'] != 'historical_run'
    assert store.created[0]['run_id'] == result['run_id']
    assert store.created[0]['config_version'] == EARLY_TURN_CONFIG_VERSION
    assert store.finished[0][1]['status'] == 'DONE'


def test_current_strategy_cannot_be_recorded_as_old_version():
    with pytest.raises(ValueError, match='不能使用'):
        EarlyTurnService(_Store()).run('20261110', config_version='A_PRE_V2_STABLE_REPLAY_V1')
