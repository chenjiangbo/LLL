from backend.trading.broker_node_consumer import BrokerEventConsumer, ExecutionQuotePoller


class FakeGateway:
    def __init__(self):
        self.calls = []

    def set_execution_quote_subscription(self, plan_id, instruments, lease_seconds):
        self.calls.append(("subscribe", plan_id, instruments, lease_seconds))
        return {"ok": True}

    def remove_execution_quote_subscription(self, plan_id):
        self.calls.append(("unsubscribe", plan_id))
        return {"ok": True}

    def _request(self, method, path):
        self.calls.append((method, path))
        return {"events": [{"seq": 1, "event_type": "FILL"}, {"seq": 2, "event_type": "ORDER_STATUS"}]}

    def get_execution_quotes(self, symbols):
        self.calls.append(("quotes", symbols))
        return [{"symbol_key": symbol} for symbol in symbols]


class PagedEventGateway:
    def __init__(self):
        self.pages = {
            0: {"events": [{"seq": 1, "event_type": "ORDER_STATUS"}, {"seq": 2, "event_type": "FILL"}]},
            2: {"events": [{"seq": 3, "event_type": "ORDER_STATUS"}]},
            3: {"events": []},
        }

    def _request(self, method, path):
        after_seq = int(path.split("after_seq=", 1)[1].split("&", 1)[0])
        return self.pages[after_seq]


def test_event_consumer_advances_cursor_only_after_apply():
    gateway = FakeGateway()
    cursor = []
    consumed = []
    result = BrokerEventConsumer(gateway, lambda: 0, lambda value: cursor.append(value), consumed.append).consume()
    assert result == {"consumed": 2, "last_seq": 2}
    assert [event["seq"] for event in consumed] == [1, 2]
    assert cursor == [2]


def test_event_consumer_drains_all_pages_and_commits_each_page():
    gateway = PagedEventGateway()
    cursor = []
    consumed = []
    result = BrokerEventConsumer(gateway, lambda: 0, lambda value: cursor.append(value), consumed.append).consume_all(limit=2)
    assert result == {"consumed": 3, "last_seq": 3}
    assert [event["seq"] for event in consumed] == [1, 2, 3]
    assert cursor == [2, 3]


def test_event_consumer_maps_broker_queue_status_to_submitted():
    class Store:
        def __init__(self):
            self.updates = []
            self.cursor = 0

        def get_event_cursor(self, account_id):
            return self.cursor

        def save_event_cursor(self, account_id, seq):
            self.cursor = seq

        def find_order_by_broker_reference(self, account_id, client_id, broker_id):
            return {"id": 9}

        def record_order_update(self, account_id, order_id, update):
            self.updates.append(update)

        def add_reconciliation_issue(self, account_id, issue):
            raise AssertionError("queue event should match the local order")

    class Gateway:
        def _request(self, method, path):
            return {"events": [{"seq": 1, "event_type": "ORDER_STATUS", "payload": {"items": [{"client_order_id": "c-1", "broker_order_id": "b-1", "status": "QUEUED"}]}}]}

    store = Store()
    from backend.trading.broker_event_sync import BrokerEventSyncService

    service = BrokerEventSyncService(
        store,
        type("TradingStore", (), {"get_broker_account": lambda self, account_id: {"broker_account_key": "sim-1"}})(),
        lambda account_id: Gateway(),
    )
    service.sync_account(1)
    assert store.updates[0]["status"] == "SUBMITTED"


def test_event_consumer_passes_broker_order_id_with_fill():
    from backend.trading.broker_event_sync import BrokerEventSyncService

    class Store:
        def __init__(self):
            self.fill = None
            self.cursor = 0

        def get_event_cursor(self, account_id):
            return self.cursor

        def save_event_cursor(self, account_id, seq):
            self.cursor = seq

        def find_order_by_broker_reference(self, account_id, client_id, broker_id):
            return {"id": 10}

        def record_fill(self, account_id, order_id, fill):
            self.fill = fill

        def add_reconciliation_issue(self, account_id, issue):
            raise AssertionError("fill event should match the local order")

    class Gateway:
        def _request(self, method, path):
            return {"events": [{"seq": 1, "event_type": "FILL_SNAPSHOT_UPDATED", "payload": {"items": [{"client_order_id": "c-2", "broker_order_id": "b-2", "broker_execution_id": "f-2", "quantity": 100, "price": 9.43}]}}]}

    store = Store()
    service = BrokerEventSyncService(
        store,
        type("TradingStore", (), {"get_broker_account": lambda self, account_id: {"broker_account_key": "sim-1"}})(),
        lambda account_id: Gateway(),
    )
    service.sync_account(1)
    assert store.fill["broker_order_id"] == "b-2"


def test_quote_poller_only_reads_active_plan_symbols():
    gateway = FakeGateway()
    quotes = ExecutionQuotePoller(gateway).poll([{"id": 1, "status": "ACTIVE", "symbol": "SZ:000661"}, {"id": 2, "status": "DRAFT", "symbol": "SH:600000"}])
    assert quotes == [{"symbol_key": "SZ:000661"}]
    assert gateway.calls[0] == ("subscribe", "1", [{"exchange": "SZ", "code": "000661"}], 120)


def test_quote_poller_unsubscribes_plan_that_is_no_longer_active():
    gateway = FakeGateway()
    poller = ExecutionQuotePoller(gateway)
    poller.poll([{"id": 1, "status": "ACTIVE", "symbol": "SZ:000661"}])
    poller.poll([])
    assert ("unsubscribe", "1") in gateway.calls
