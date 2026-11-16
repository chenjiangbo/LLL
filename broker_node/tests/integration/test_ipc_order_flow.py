import json
import sys
import types
from pathlib import Path
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from broker_node.api_service.app import create_app
from broker_node.api_service.ipc_app import create_ipc_app
from broker_node.api_service.ipc_store import IPCStore
from broker_node.gm_agent.ipc_client import IPCClient
from broker_node.gm_agent.readonly_runtime import ReadonlyRuntime
from broker_node.gm_agent.quote_cache import QuoteCache
from broker_node.gm_agent.quote_service import ExecutionQuoteService
from broker_node.shared.config import NodeConfig
from broker_node.shared.db import connect, initialize


def test_public_order_through_ipc_to_mock_sdk_and_cancel(tmp_path, monkeypatch):
    config = json.loads((Path(__file__).parents[2] / 'config' / 'config.example.json').read_text())
    config['gm']['strategy_id'] = 'strategy'
    config['runtime']['durable_db'] = str(tmp_path / 'broker.db')
    config['runtime']['quote_cache_db'] = str(tmp_path / 'quotes.db')
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    monkeypatch.setenv('BROKER_NODE_CONFIG', str(path))
    initialize(Path(config['runtime']['durable_db']))
    store = IPCStore(Path(config['runtime']['durable_db']), 30, config=NodeConfig(config, path), process_verifier=lambda p, s: True)
    identity = dict(node_id=config['node_id'], account_mode='SIM', strategy_id='strategy', broker_account_key=config['broker_account_key'], agent_instance_id='one', pid=1, started_at='now')
    expected = dict(identity, broker_account_id='account')
    secret = 'a' * 32
    quote_service = ExecutionQuoteService(QuoteCache(Path(config['runtime']['quote_cache_db'])))
    ipc = TestClient(create_ipc_app(store, expected, secret, 100000, quote_service=quote_service), client=('127.0.0.1', 1234))
    public = TestClient(create_app(ipc_store=store))
    class Transport(IPCClient):
        def _post(self, url, payload):
            response = ipc.post(url, json=payload, headers={'Authorization': 'Bearer ' + secret})
            assert response.status_code == 200, response.text
            return response.json()
    transport = Transport('127.0.0.1', 1234, secret, 5, 100000)
    transport.hello(identity)
    transport.heartbeat(1, 1)
    generation = transport.connectivity(1, True, True, 'account')
    batch = dict(batch_id='snapshot-1', as_of=datetime.now(timezone.utc).isoformat(),
                 account={'normalized': {'account_id':'account','total_asset':200000,'available_cash':200000}, 'raw':{}},
                 positions=[], orders=[], unfinished_orders=[], fills=[],
                 component_counts={'positions':0,'orders':0,'unfinished_orders':0,'fills':0})
    transport.snapshot('message-1', batch, generation)
    assert public.get('/api/v1/account').json()['payload']['normalized']['available_cash'] == 200000
    assert public.get('/api/v1/status').json()['execution_enabled'] is True
    calls = []
    gm = types.ModuleType('gm.api')
    gm.OrderSide_Buy, gm.OrderSide_Sell = 1, 2
    gm.PositionEffect_Open, gm.PositionEffect_Close, gm.OrderType_Limit = 1, 2, 1
    gm.order_volume = lambda *args, **kwargs: calls.append(('submit', args, kwargs)) or [{'order_id':'', 'cl_ord_id':'gm-1', 'status':10}]
    gm.order_cancel = lambda arg: calls.append(('cancel', arg)) or []
    monkeypatch.setitem(sys.modules, 'gm', types.ModuleType('gm'))
    monkeypatch.setitem(sys.modules, 'gm.api', gm)
    runtime = ReadonlyRuntime(transport, identity, 'account', 60, event_queue_limit=10, event_batch_limit=10)
    gm.subscribe = lambda **kwargs: calls.append(('subscribe', kwargs))
    gm.unsubscribe = lambda **kwargs: calls.append(('unsubscribe', kwargs))
    assert public.put('/api/v1/execution-quotes/subscriptions/plan-1', json={'symbols':[{'code':'000661','exchange':'SZ'}]}).status_code == 200
    runtime._refresh_quotes()
    assert calls.pop()[0] == 'subscribe'
    runtime.on_tick({'symbol':'SZSE.000661','price':70.0,'created_at':datetime.now(timezone.utc).isoformat()})
    runtime._flush_quotes()
    assert public.get('/api/v1/execution-quotes?symbols=SZ:000661').json()['quotes'][0]['last'] == 70.0
    order = dict(request_id='r1',client_order_id='c1',broker_account_key=config['broker_account_key'],code='000661',exchange='SZ',side='BUY',order_type='LIMIT',price='70.00',quantity=100)
    first = public.post('/api/v1/orders', json=order)
    assert first.status_code == 202, first.text
    assert public.post('/api/v1/orders', json=order).json()['deduplicated']
    deliver = transport.command_result
    def response_lost(**kwargs):
        deliver(**kwargs)
        raise TimeoutError('response lost after commit')
    transport.command_result = response_lost
    with pytest.raises(TimeoutError):
        runtime._process_command()
    transport.command_result = deliver
    runtime._process_command()
    assert len(calls) == 1
    with connect(store.path) as db:
        assert db.execute('SELECT status FROM commands WHERE request_id=?', ('r1',)).fetchone()[0] == 'ACKED'
        assert db.execute('SELECT broker_client_order_id FROM order_links WHERE client_order_id=?', ('c1',)).fetchone()[0] == 'gm-1'
    now = datetime.now(timezone.utc)
    runtime.on_order_status(dict(cl_ord_id='gm-1', order_id='', symbol='SZSE.000661', side=1, status=10, updated_at=now, volume=100, price=70))
    runtime.on_order_status(dict(cl_ord_id='gm-1', order_id='broker-1', symbol='SZSE.000661', side=1, status=1, updated_at=now, volume=100, price=70))
    runtime.on_execution_report(dict(cl_ord_id='gm-1', order_id='broker-1', exec_id='fill-1', symbol='SZSE.000661', side=1, price=70, volume=100, created_at=now))
    runtime._flush_events()
    runtime.on_error(63001, 'test error')
    with connect(store.path) as db:
        events = db.execute("SELECT event_type,client_order_id FROM broker_events ORDER BY seq").fetchall()
        assert [tuple(row) for row in events] == [('ORDER_STATUS', 'c1'), ('ORDER_STATUS', 'c1'), ('FILL', 'c1'), ('GM_ERROR', None)]
        assert db.execute('SELECT broker_order_id FROM order_links WHERE client_order_id=?', ('c1',)).fetchone()[0] == 'broker-1'
    batch['batch_id'] = 'snapshot-2'
    batch['as_of'] = datetime.now(timezone.utc).isoformat()
    batch['orders'] = [{'normalized':{'broker_order_id':'broker-1','broker_client_order_id':'gm-1','client_order_id':None,'status':'NEW','raw_status':1},'raw':{}}]
    batch['component_counts']['orders'] = 1
    transport.snapshot('message-2', batch, generation)
    assert public.get('/api/v1/orders').json()['payload'][0]['normalized']['client_order_id'] == 'c1'
    cancel = public.post('/api/v1/orders/c1/cancel', json={'cancel_request_id':'r2', 'reason':'test'})
    assert cancel.status_code == 202, cancel.text
    runtime._process_command()
    assert calls[1] == ('cancel', {'cl_ord_id':'gm-1', 'account_id':'account'})
    second = dict(order, request_id='r3', client_order_id='c3')
    assert public.post('/api/v1/orders', json=second).status_code == 202
    def timeout(*args, **kwargs):
        calls.append(('submit-timeout',))
        raise TimeoutError('SDK response lost')
    gm.order_volume = timeout
    runtime._process_command()
    runtime._process_command()
    assert calls.count(('submit-timeout',)) == 1
    repeat = public.post('/api/v1/orders', json=second)
    assert repeat.status_code == 202 and repeat.json()['deduplicated'] is True
    assert repeat.json()['status'] == 'UNKNOWN'
    with connect(store.path) as db:
        assert db.execute('SELECT status FROM commands WHERE request_id=?', ('r3',)).fetchone()[0] == 'UNKNOWN'


def test_lost_dispatch_becomes_unknown_and_is_not_claimed_again(tmp_path):
    dbpath = tmp_path / 'broker.db'
    initialize(dbpath)
    config = json.loads((Path(__file__).parents[2] / 'config' / 'config.example.json').read_text())
    config['runtime']['durable_db'] = str(dbpath)
    config_path = tmp_path / 'config.json'
    config_path.write_text(json.dumps(config))
    store = IPCStore(dbpath, 30, config=NodeConfig(config, config_path), process_verifier=lambda p, s: True)
    identity = dict(node_id='n', account_mode='SIM', strategy_id='s', broker_account_key='a', agent_instance_id='i', pid=1, started_at='now')
    session = store.hello(identity, identity)
    store.heartbeat(**{'session':session['session_id'], 'epoch':session['node_epoch'], 'sequence':1, 'callback_counter':1})
    with connect(dbpath) as db:
        db.execute("UPDATE node_state SET execution_enabled=1,paused=0,reconciliation_required=0")
        db.execute("INSERT INTO commands(command_id,request_id,command_type,payload_hash,payload_json,status,created_at,updated_at) VALUES('c','r','ORDER_SUBMIT','h','{}','QUEUED','now','now')")
    assert store.claim_command(session['session_id'], session['node_epoch'])['command_id'] == 'c'
    assert store.claim_command(session['session_id'], session['node_epoch']) is None
    store.goodbye(session['session_id'], session['node_epoch'])
    with connect(dbpath) as db:
        assert db.execute("SELECT status FROM commands WHERE command_id='c'").fetchone()[0] == 'UNKNOWN'
