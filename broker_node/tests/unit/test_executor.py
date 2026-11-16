from pathlib import Path
import json
import sys
import types

import pytest

from broker_node.gm_agent.executor import BrokerCommandExecutor
from broker_node.shared.db import connect, initialize


def test_sdk_exception_keeps_outcome_unknown_and_pauses(tmp_path: Path, monkeypatch):
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    payload = {"exchange": "SZ", "code": "000001", "side": "BUY", "order_type": "LIMIT", "quantity": 100, "price": "10"}
    with connect(db) as c:
        c.execute("INSERT INTO node_state(node_id,broker_account_key,account_mode,execution_enabled,paused,reconciliation_required,updated_at) VALUES('n','a','SIM',1,0,0,'2026-01-01')")
        c.execute("INSERT INTO commands(command_id,request_id,command_type,payload_hash,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", ("c", "r", "ORDER_SUBMIT", "h", json.dumps(payload), "CLAIMED", "2026-01-01", "2026-01-01"))
    gm = types.ModuleType("gm")
    api = types.ModuleType("gm.api")
    api.OrderSide_Buy = 1
    api.OrderSide_Sell = 2
    api.PositionEffect_Open = 1
    api.OrderType_Limit = 1
    def uncertain(*args, **kwargs):
        raise TimeoutError("response lost")
    api.order_volume = uncertain
    gm.api = api
    monkeypatch.setitem(sys.modules, "gm", gm)
    monkeypatch.setitem(sys.modules, "gm.api", api)
    with pytest.raises(TimeoutError):
        BrokerCommandExecutor(db).dispatch({"command_id": "c", "command_type": "ORDER_SUBMIT", "payload_json": json.dumps(payload)}, "account")
    with connect(db) as c:
        assert c.execute("SELECT status FROM commands WHERE command_id='c'").fetchone()[0] == "UNKNOWN"
        assert tuple(c.execute("SELECT execution_enabled,paused,reconciliation_required FROM node_state").fetchone()) == (0, 1, 1)


def test_claim_is_atomic_and_ordered(tmp_path: Path):
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    with connect(db) as c:
        c.execute("INSERT INTO commands(command_id,request_id,command_type,payload_hash,payload_json,status,created_at,updated_at) VALUES('c','r','ORDER_SUBMIT','h','{}','QUEUED','2026-01-01','2026-01-01')")
    command = BrokerCommandExecutor(db).claim_next()
    assert command["command_id"] == "c"
    with connect(db) as c:
        assert c.execute("SELECT status FROM commands WHERE command_id='c'").fetchone()[0] == "CLAIMED"


def test_claim_does_not_take_next_command_while_one_is_in_flight(tmp_path: Path):
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    with connect(db) as c:
        c.execute("INSERT INTO commands(command_id,request_id,command_type,payload_hash,payload_json,status,created_at,updated_at) VALUES('in-flight','r1','ORDER_SUBMIT','h1','{}','DISPATCHING','2026-01-01','2026-01-01')")
        c.execute("INSERT INTO commands(command_id,request_id,command_type,payload_hash,payload_json,status,created_at,updated_at) VALUES('next','r2','ORDER_SUBMIT','h2','{}','QUEUED','2026-01-02','2026-01-02')")
    assert BrokerCommandExecutor(db).claim_next() is None


def test_claim_returns_nothing_when_queue_is_empty(tmp_path: Path):
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    assert BrokerCommandExecutor(db).claim_next() is None


def test_waiting_cancel_does_not_starve_new_commands(tmp_path: Path):
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    with connect(db) as c:
        c.execute("INSERT INTO commands(command_id,request_id,command_type,client_order_id,payload_hash,payload_json,status,error_code,created_at,updated_at) VALUES('old-cancel','r1','ORDER_CANCEL','old-order','h1','{}','QUEUED','WAITING_ORDER_LINK','2026-01-01','2026-01-01')")
        c.execute("INSERT INTO commands(command_id,request_id,command_type,client_order_id,payload_hash,payload_json,status,created_at,updated_at) VALUES('new-submit','r2','ORDER_SUBMIT','new-order','h2','{}','QUEUED','2026-01-02','2026-01-02')")
    command = BrokerCommandExecutor(db).claim_next()
    assert command["command_id"] == "new-submit"
