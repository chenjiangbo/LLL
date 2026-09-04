from pathlib import Path

from broker_node.gm_agent.executor import BrokerCommandExecutor
from broker_node.shared.db import connect, initialize


def test_claim_is_atomic_and_ordered(tmp_path: Path):
    db = tmp_path / "broker.sqlite3"
    initialize(db)
    with connect(db) as c:
        c.execute("INSERT INTO commands(command_id,request_id,command_type,payload_hash,payload_json,status,created_at,updated_at) VALUES('c','r','ORDER_SUBMIT','h','{}','QUEUED','2026-01-01','2026-01-01')")
    command = BrokerCommandExecutor(db).claim_next()
    assert command["command_id"] == "c"
    with connect(db) as c:
        assert c.execute("SELECT status FROM commands WHERE command_id='c'").fetchone()[0] == "CLAIMED"
