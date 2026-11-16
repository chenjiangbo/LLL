from backend.trading.reconciliation import ReconciliationService
from backend.trading.execution import ExecutionStore


class FakeStore:
    def __init__(self):
        self.calls = []

    def add_reconciliation_issue(self, account_id, issue):
        self.calls.append((account_id, issue))
        return {"account_id": account_id, **issue}

    def list_reconciliation_issues(self, account_id):
        return []

    def resolve_position_mismatch(self, account_id, symbol, local_quantity, broker_quantity, local_available_quantity=None, broker_available_quantity=None):
        self.calls.append(("resolve", account_id, symbol, local_quantity, broker_quantity, local_available_quantity, broker_available_quantity))
        return 0


def test_reconciliation_writes_issues_with_selected_account_scope():
    store = FakeStore()
    service = ReconciliationService(store, 2)
    issues = service.compare_positions(
        [{"symbol": "000001", "quantity": 100, "available_quantity": 100}],
        [{"symbol": "000001", "quantity": 0, "available_quantity": 0}],
    )
    assert issues[0]["account_id"] == 2
    assert store.calls[0][0] == 2


def test_reconciliation_matches_normalized_symbol_without_false_mismatch():
    store = FakeStore()
    service = ReconciliationService(store, 2)
    assert service.compare_positions(
        [{"symbol": "000661", "quantity": 1400, "available_quantity": 1400}],
        [{"symbol": "000661", "quantity": 1400, "available_quantity": 1400}],
    ) == []
    assert store.calls[-1] == ("resolve", 2, "000661", 1400, 1400, 1400, 1400)


def test_reconciliation_matches_exchange_qualified_and_plain_broker_symbol():
    store = FakeStore()
    service = ReconciliationService(store, 2)
    assert service.compare_positions(
        [{"symbol": "SH:600000", "quantity": 1200, "available_quantity": 0}],
        [{"symbol": "600000", "quantity": 1200, "available_quantity": 0}],
    ) == []


def test_reconciliation_blocks_available_quantity_mismatch_even_when_total_quantity_matches():
    store = FakeStore()
    service = ReconciliationService(store, 2)
    issues = service.compare_positions(
        [{"symbol": "600300", "quantity": 300, "available_quantity": 300}],
        [{"symbol": "600300", "quantity": 300, "available_quantity": 0}],
    )
    assert issues[0]["issue_type"] == "POSITION_AVAILABLE_QUANTITY_MISMATCH"
    assert issues[0]["local_value"]["available_quantity"] == 300
    assert issues[0]["broker_value"]["available_quantity"] == 0


def test_reconciliation_rejects_position_snapshot_without_available_quantity():
    store = FakeStore()
    service = ReconciliationService(store, 2)
    try:
        service.compare_positions(
            [{"symbol": "600300", "quantity": 300, "available_quantity": 300}],
            [{"symbol": "600300", "quantity": 300}],
        )
    except ValueError as exc:
        assert "quantity fields" in str(exc)
    else:
        raise AssertionError("missing available quantity must fail reconciliation")


def test_reconciliation_exposes_local_order_without_broker_identity():
    store = FakeStore()
    service = ReconciliationService(store, 7)
    issues = service.compare_orders(
        [{"id": 3, "client_order_id": "client-3", "broker_order_id": None, "symbol": "600000", "status": "PENDING_SUBMIT"}],
        [],
    )
    assert issues[0]["issue_type"] == "LOCAL_ORDER_UNCONFIRMED"
    assert issues[0]["local_value"]["client_order_id"] == "client-3"


def test_reconciliation_fingerprint_uses_durable_broker_identity_over_event_metadata():
    first = ExecutionStore._reconciliation_fingerprint({
        "issue_type": "UNMATCHED_BROKER_ORDER_EVENT",
        "symbol": "SZSE.000661",
        "broker_value": {"order_id": "broker-42", "event_seq": 10, "detected_at": "2026-09-04T11:00:00Z"},
    })
    replay = ExecutionStore._reconciliation_fingerprint({
        "issue_type": "UNMATCHED_BROKER_ORDER_EVENT",
        "symbol": "SZSE.000661",
        "broker_value": {"order_id": "broker-42", "event_seq": 99, "detected_at": "2026-09-04T12:00:00Z"},
    })
    assert first == replay
