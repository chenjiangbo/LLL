from backend.trading.reconciliation import ReconciliationService


class FakeStore:
    def __init__(self):
        self.calls = []

    def add_reconciliation_issue(self, account_id, issue):
        self.calls.append((account_id, issue))
        return {"account_id": account_id, **issue}

    def list_reconciliation_issues(self, account_id):
        return []


def test_reconciliation_writes_issues_with_selected_account_scope():
    store = FakeStore()
    service = ReconciliationService(store, 2)
    issues = service.compare_positions(
        [{"symbol": "000001", "quantity": 100}],
        [{"symbol": "000001", "quantity": 0}],
    )
    assert issues[0]["account_id"] == 2
    assert store.calls[0][0] == 2


def test_reconciliation_matches_normalized_symbol_without_false_mismatch():
    store = FakeStore()
    service = ReconciliationService(store, 2)
    assert service.compare_positions(
        [{"symbol": "000661", "quantity": 1400}],
        [{"symbol": "000661", "quantity": 1400}],
    ) == []


def test_reconciliation_exposes_local_order_without_broker_identity():
    store = FakeStore()
    service = ReconciliationService(store, 7)
    issues = service.compare_orders(
        [{"id": 3, "client_order_id": "client-3", "broker_order_id": None, "symbol": "600000", "status": "PENDING_SUBMIT"}],
        [],
    )
    assert issues[0]["issue_type"] == "LOCAL_ORDER_UNCONFIRMED"
    assert issues[0]["local_value"]["client_order_id"] == "client-3"
