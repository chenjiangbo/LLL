"""V2 IPC session storage. Node is the sole owner of this database."""
from __future__ import annotations

import secrets
import sqlite3
import hashlib
import json
import time
from datetime import datetime, timezone, timedelta
from contextlib import closing
from pathlib import Path
from typing import Any

from broker_node.shared.db import connect
from broker_node.shared.config import NodeConfig


class SessionError(ValueError):
    pass


class IPCStore:
    def __init__(self, path: Path, heartbeat_timeout_seconds: float, *, config: NodeConfig, clock=time.monotonic, process_verifier=None):
        if isinstance(heartbeat_timeout_seconds, bool) or not isinstance(heartbeat_timeout_seconds, (int, float)) or not 0 < heartbeat_timeout_seconds < float('inf'):
            raise ValueError('a finite positive heartbeat timeout is required')
        self.path = path
        self.config = config
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.clock = clock
        self.process_verifier = process_verifier
        self.epoch = secrets.token_urlsafe(32)
        with closing(connect(path)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ipc_agent_sessions (
                    session_id TEXT PRIMARY KEY, node_epoch TEXT NOT NULL,
                    agent_instance_id TEXT NOT NULL, node_id TEXT NOT NULL,
                    account_mode TEXT NOT NULL, strategy_id TEXT NOT NULL,
                    broker_account_key TEXT NOT NULL, pid INTEGER NOT NULL,
                    started_at TEXT NOT NULL, last_sequence INTEGER NOT NULL DEFAULT 0,
                    callback_counter INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL,
                    last_seen_monotonic REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ipc_unique_active_session
                    ON ipc_agent_sessions(node_id) WHERE state = 'ACTIVE';
                CREATE TABLE IF NOT EXISTS ipc_node_epoch (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), epoch TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ipc_connection_state (
                    session_id TEXT PRIMARY KEY, trade_connected INTEGER NOT NULL,
                    market_connected INTEGER NOT NULL, account_verified INTEGER NOT NULL,
                    sequence INTEGER NOT NULL DEFAULT 0, generation INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS ipc_inbox (
                    message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    message_type TEXT NOT NULL, payload_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ipc_snapshot_batches (
                    batch_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ipc_staged_events (
                    event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ipc_fill_facts (
                    broker_account_key TEXT NOT NULL, trade_date TEXT NOT NULL,
                    broker_execution_id TEXT NOT NULL, economic_hash TEXT NOT NULL,
                    broker_event_seq INTEGER NOT NULL,
                    PRIMARY KEY (broker_account_key, trade_date, broker_execution_id)
                );
                CREATE TABLE IF NOT EXISTS ipc_event_issues (
                    event_id TEXT PRIMARY KEY, reason TEXT NOT NULL,
                    created_at TEXT NOT NULL, resolved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS ipc_event_issue_attempts (
                    attempt_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL, attempted_at TEXT NOT NULL,
                    outcome TEXT NOT NULL, reason TEXT
                );
            """)
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute('PRAGMA table_info(ipc_agent_sessions)')}
            if 'last_seen_monotonic' not in columns:
                db.execute('ALTER TABLE ipc_agent_sessions ADD COLUMN last_seen_monotonic REAL NOT NULL DEFAULT 0')
            snapshot_columns = {row[1] for row in db.execute('PRAGMA table_info(ipc_snapshot_batches)')}
            if 'published' not in snapshot_columns:
                db.execute('ALTER TABLE ipc_snapshot_batches ADD COLUMN published INTEGER NOT NULL DEFAULT 0')
            conn_columns = {row[1] for row in db.execute('PRAGMA table_info(ipc_connection_state)')}
            if 'sequence' not in conn_columns:
                db.execute('ALTER TABLE ipc_connection_state ADD COLUMN sequence INTEGER NOT NULL DEFAULT 0')
            if 'generation' not in conn_columns:
                db.execute('ALTER TABLE ipc_connection_state ADD COLUMN generation INTEGER NOT NULL DEFAULT 0')
            command_columns = {row[1] for row in db.execute('PRAGMA table_info(commands)')}
            if 'ipc_session_id' not in command_columns:
                db.execute('ALTER TABLE commands ADD COLUMN ipc_session_id TEXT')
            if 'ipc_result_hash' not in command_columns:
                db.execute('ALTER TABLE commands ADD COLUMN ipc_result_hash TEXT')
            if 'ipc_result_json' not in command_columns:
                db.execute('ALTER TABLE commands ADD COLUMN ipc_result_json TEXT')
            db.execute("UPDATE commands SET status='UNKNOWN', error_code='AGENT_INTERRUPTED', error_message='Agent or Node stopped during dispatch' WHERE status IN ('CLAIMED','DISPATCHING')")
            # A new Node epoch fences every previous process, regardless of timestamps.
            db.execute("UPDATE ipc_agent_sessions SET state='EXPIRED' WHERE state='ACTIVE'")
            # Persisted v1 values describe the previous session. Keep their
            # content for audit, but never present them as current after restart.
            db.execute("UPDATE snapshots SET stale=1 WHERE stale=0")
            db.execute("""UPDATE node_state SET agent_process_status='OFFLINE',
                market_connection_status='UNKNOWN',trade_connection_status='UNKNOWN',
                broker_account_status='UNKNOWN',execution_enabled=0,reconciliation_required=1""")
            db.execute("INSERT INTO ipc_node_epoch(singleton,epoch) VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET epoch=excluded.epoch", (self.epoch,))

    def _assert_current_epoch(self, db: sqlite3.Connection) -> None:
        row = db.execute("SELECT epoch FROM ipc_node_epoch WHERE singleton=1").fetchone()
        if not row or row[0] != self.epoch:
            raise SessionError("node epoch is no longer current")

    def reconcile_if_needed(self, session, epoch):
        from broker_node.gm_agent.reconciler import Reconciler
        from broker_node.gm_agent.event_writer import EventWriter
        from broker_node.gm_agent.snapshot_writer import SnapshotWriter
        with closing(connect(self.path)) as db:
            self._require_active(db, session, epoch)
            state = db.execute('SELECT reconciliation_required FROM node_state').fetchone()
            inflight = db.execute("SELECT 1 FROM commands WHERE status IN ('CLAIMED','DISPATCHING') LIMIT 1").fetchone()
            if not state or not state['reconciliation_required'] or inflight:
                return
        outcome = Reconciler(self.path, EventWriter(self.path), SnapshotWriter(self.path)).startup()
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._require_active(db, session, epoch)
            connections = db.execute('SELECT * FROM ipc_connection_state WHERE session_id=?', (session,)).fetchone()
            issues = db.execute('SELECT 1 FROM ipc_event_issues WHERE resolved_at IS NULL LIMIT 1').fetchone()
            unknown = db.execute("SELECT 1 FROM commands WHERE status IN ('UNKNOWN','CLAIMED','DISPATCHING') LIMIT 1").fetchone()
            if outcome['reconciliation_required'] or issues or unknown or not connections or not all(connections[k] for k in ('trade_connected','market_connected','account_verified')):
                return
            now = datetime.now(timezone.utc).isoformat()
            paused = db.execute("SELECT pause_reason FROM node_state").fetchone()[0] in ('API_PAUSED','API_PAUSED_AND_CANCELING','USER_PAUSED')
            state = db.execute("SELECT account_mode FROM node_state").fetchone()
            execution_authorized = state['account_mode'] == 'SIM' or self.config.live_orders_enabled()
            db.execute("""UPDATE node_state SET reconciliation_required=0,
                execution_enabled=?,
                paused=?,
                pause_reason=CASE WHEN pause_reason IN ('API_PAUSED','API_PAUSED_AND_CANCELING','USER_PAUSED') THEN pause_reason ELSE NULL END,
                last_account_sync_at=?,last_position_sync_at=?,last_order_sync_at=?,last_fill_sync_at=?,updated_at=?""",
                (int(execution_authorized and not paused), int(paused), now,now,now,now,now))

    def refresh_execution_authorization(self) -> bool:
        """Apply the existing user authorization to a connected, reconciled LIVE node."""
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            state = db.execute('SELECT * FROM node_state').fetchone()
            if not state:
                return False
            unknown = db.execute("SELECT 1 FROM commands WHERE status IN ('UNKNOWN','CLAIMED','DISPATCHING') LIMIT 1").fetchone()
            issues = db.execute('SELECT 1 FROM ipc_event_issues WHERE resolved_at IS NULL LIMIT 1').fetchone()
            ready = (
                self.config.live_orders_enabled()
                and state['account_mode'] == 'LIVE'
                and state['agent_process_status'] == 'ONLINE'
                and state['trade_connection_status'] == 'CONNECTED'
                and state['market_connection_status'] == 'CONNECTED'
                and state['broker_account_status'] == 'CONNECTED'
                and not state['paused']
                and not state['reconciliation_required']
                and not unknown
                and not issues
            )
            db.execute('UPDATE node_state SET execution_enabled=?,updated_at=?',
                       (int(ready), datetime.now(timezone.utc).isoformat()))
            return ready

    def _require_active(self, db, session, epoch):
        self._assert_current_epoch(db)
        self._assert_process_identity(db, session, epoch)
        now = self.clock()
        row = db.execute("SELECT * FROM ipc_agent_sessions WHERE session_id=? AND node_epoch=? AND state='ACTIVE' AND callback_counter>0 AND last_seen_monotonic BETWEEN ? AND ?", (session, epoch, now-self.heartbeat_timeout_seconds, now)).fetchone()
        if not row:
            raise SessionError('agent session is not active')
        return row

    def verify_session(self, session, epoch):
        with closing(connect(self.path)) as db:
            self._require_active(db, session, epoch)

    def quote_subscriptions(self, session, epoch):
        with closing(connect(self.path)) as db:
            self._require_active(db, session, epoch)
            now = datetime.now(timezone.utc).isoformat()
            return [row[0] for row in db.execute('SELECT DISTINCT broker_symbol FROM quote_subscriptions WHERE lease_expires_at>? ORDER BY broker_symbol', (now,))]

    def claim_command(self, session, epoch):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            agent = self._require_active(db, session, epoch)
            state = db.execute('SELECT execution_enabled,paused,reconciliation_required FROM node_state').fetchone()
            if db.execute("SELECT 1 FROM commands WHERE status IN ('CLAIMED','DISPATCHING') LIMIT 1").fetchone():
                return None
            unknown = db.execute("SELECT 1 FROM commands WHERE status='UNKNOWN' LIMIT 1").fetchone()
            account_authorized = agent['account_mode'] == 'SIM' or self.config.live_orders_enabled()
            trading_ready = bool(account_authorized and state and state['execution_enabled'] and not state['paused'] and not state['reconciliation_required'] and not unknown)
            row = db.execute("""SELECT c.* FROM commands c WHERE c.status='QUEUED'
                AND (c.command_type='SYNC_ALL' OR ?)
                AND (c.command_type != 'ORDER_CANCEL' OR EXISTS
                (SELECT 1 FROM order_links l WHERE l.client_order_id=c.client_order_id AND l.broker_client_order_id IS NOT NULL))
                ORDER BY c.created_at LIMIT 1""", (int(trading_ready),)).fetchone()
            if not row:
                return None
            now = datetime.now(timezone.utc).isoformat()
            db.execute("UPDATE commands SET status='DISPATCHING',claimed_at=?,dispatched_at=?,updated_at=?,ipc_session_id=? WHERE command_id=? AND status='QUEUED'", (now, now, now, session, row['command_id']))
            command = dict(row)
            if command['command_type'] == 'ORDER_CANCEL':
                link = db.execute('SELECT broker_client_order_id FROM order_links WHERE client_order_id=?', (command['client_order_id'],)).fetchone()
                command['broker_client_order_id'] = link['broker_client_order_id']
            return command

    def command_result(self, session, epoch, command_id, status, result, error):
        if status not in ('ACKED', 'FAILED_SAFE', 'UNKNOWN'):
            raise SessionError('invalid command status')
        fingerprint = hashlib.sha256(json.dumps([status, result, error], sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._require_active(db, session, epoch)
            row = db.execute('SELECT * FROM commands WHERE command_id=?', (command_id,)).fetchone()
            if not row or row['ipc_session_id'] != session:
                raise SessionError('command does not belong to session')
            if row['ipc_result_hash']:
                if row['ipc_result_hash'] != fingerprint:
                    raise SessionError('command result conflict')
                return
            if row['status'] != 'DISPATCHING':
                raise SessionError('command is not dispatching')
            now = datetime.now(timezone.utc).isoformat()
            if status == 'ACKED' and row['command_type'] == 'ORDER_SUBMIT':
                order = result[0] if isinstance(result, list) and result else result
                if not isinstance(order, dict) or not order.get('cl_ord_id'):
                    status, error = 'UNKNOWN', 'GM result lacks order identity'
                else:
                    db.execute("""INSERT INTO order_links(client_order_id,submit_command_id,broker_client_order_id,broker_order_id,exchange_order_id,last_raw_status,origin,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,'SYSTEM',?,?) ON CONFLICT(client_order_id) DO UPDATE SET broker_client_order_id=excluded.broker_client_order_id,broker_order_id=COALESCE(excluded.broker_order_id,order_links.broker_order_id),exchange_order_id=COALESCE(excluded.exchange_order_id,order_links.exchange_order_id),last_raw_status=excluded.last_raw_status,updated_at=excluded.updated_at""", (row['client_order_id'], command_id, order['cl_ord_id'], order.get('order_id') or None, order.get('ex_ord_id'), order.get('status'), now, now))
                    db.execute("UPDATE broker_events SET client_order_id=? WHERE client_order_id IS NULL AND (broker_order_id=? OR json_extract(payload_json,'$.normalized.broker_client_order_id')=?)", (row['client_order_id'], order.get('order_id') or None, order['cl_ord_id']))
                    observed = db.execute("SELECT broker_order_id,payload_json FROM broker_events WHERE client_order_id=? AND event_type='ORDER_STATUS' AND broker_order_id IS NOT NULL AND broker_order_id<>'' ORDER BY seq DESC LIMIT 1", (row['client_order_id'],)).fetchone()
                    if observed:
                        normalized = json.loads(observed['payload_json']).get('normalized', {})
                        db.execute('UPDATE order_links SET broker_order_id=?,last_broker_status=?,last_raw_status=?,updated_at=? WHERE client_order_id=?', (observed['broker_order_id'], normalized.get('status'), normalized.get('raw_status'), now, row['client_order_id']))
            db.execute('UPDATE commands SET status=?,error_code=?,error_message=?,completed_at=?,updated_at=?,ipc_result_hash=?,ipc_result_json=? WHERE command_id=?', (status, 'DISPATCH_UNKNOWN' if status == 'UNKNOWN' else 'DISPATCH_ERROR' if status == 'FAILED_SAFE' else None, error, now, now, fingerprint, json.dumps(result,ensure_ascii=False), command_id))
            if status == 'UNKNOWN':
                db.execute("UPDATE node_state SET execution_enabled=0,reconciliation_required=1,pause_reason='RECONCILIATION_REQUIRED',updated_at=?", (now,))

    def _assert_process_identity(self, db: sqlite3.Connection, session: str, epoch: str) -> None:
        row = db.execute("SELECT pid,started_at FROM ipc_agent_sessions WHERE session_id=? AND node_epoch=? AND state='ACTIVE'", (session, epoch)).fetchone()
        if not row or self.process_verifier is None:
            raise SessionError('process identity unavailable')
        try:
            verified = self.process_verifier(row['pid'], row['started_at']) is True
        except (OSError, ValueError):
            verified = False
        if not verified:
            raise SessionError('process identity cannot be verified')

    def unresolved_event_issues(self) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as db, db:
            self._assert_current_epoch(db)
            return [dict(row) for row in db.execute('SELECT event_id,reason,created_at FROM ipc_event_issues WHERE resolved_at IS NULL ORDER BY created_at,event_id')]

    def retry_event_issue(self, event_id: str) -> dict[str, Any]:
        """Retry a persisted fact once; never change execution readiness."""
        if not isinstance(event_id, str) or not event_id:
            raise SessionError('event ID required')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._assert_current_epoch(db)
            row = db.execute('''SELECT i.resolved_at,e.event_type FROM ipc_event_issues i
                JOIN ipc_staged_events e ON e.event_id=i.event_id WHERE i.event_id=?''', (event_id,)).fetchone()
            if not row:
                raise SessionError('event issue not found')
            if row['resolved_at'] is not None:
                return {'resolved': True, 'duplicate': True}
            now = datetime.now(timezone.utc).isoformat()
            db.execute('SAVEPOINT retry_event')
            try:
                if row['event_type'] == 'FILL':
                    seq = self._promote_fill_in_transaction(db, event_id)
                elif row['event_type'] == 'ORDER_STATUS':
                    seq = self._promote_order_in_transaction(db, event_id)
                else:
                    raise SessionError('event type requires processing')
            except SessionError as exc:
                db.execute('ROLLBACK TO retry_event')
                reason = str(exc)
                db.execute('UPDATE ipc_event_issues SET reason=? WHERE event_id=?', (reason, event_id))
                db.execute("INSERT INTO ipc_event_issue_attempts(event_id,attempted_at,outcome,reason) VALUES(?,?,'UNRESOLVED',?)", (event_id, now, reason))
                result = {'resolved': False, 'reason': reason}
            else:
                db.execute('UPDATE ipc_event_issues SET resolved_at=? WHERE event_id=?', (now, event_id))
                db.execute("INSERT INTO ipc_event_issue_attempts(event_id,attempted_at,outcome) VALUES(?,?,'RESOLVED')", (event_id, now))
                result = {'resolved': True, 'event_seq': seq, 'duplicate': False}
            finally:
                db.execute('RELEASE retry_event')
        return result

    def health(self) -> dict[str, Any]:
        """Check current SDK progress and independently verified process identity."""
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._assert_current_epoch(db)
            row = db.execute("SELECT * FROM ipc_agent_sessions WHERE node_epoch=? AND state='ACTIVE'", (self.epoch,)).fetchone()
            now = self.clock()
            timely = bool(row and 0 <= now-row['last_seen_monotonic'] <= self.heartbeat_timeout_seconds)
            starting = bool(timely and row['callback_counter'] == 0)
            fresh = bool(timely and row['callback_counter'] > 0)
            verified = False
            if row and fresh and self.process_verifier is not None:
                # The verifier must check both PID and process start identity.
                # Failure is not a reason to accept an unverified session.
                try:
                    verified = self.process_verifier(row['pid'], row['started_at']) is True
                except (OSError, ValueError):
                    verified = False
            online = fresh and verified
            if not online:
                if row and not starting:
                    db.execute("UPDATE ipc_agent_sessions SET state='EXPIRED' WHERE session_id=?", (row['session_id'],))
                    db.execute("UPDATE commands SET status='UNKNOWN',error_code='AGENT_INTERRUPTED',error_message='Agent stopped during dispatch' WHERE status='DISPATCHING' AND ipc_session_id=?", (row['session_id'],))
                db.execute('UPDATE snapshots SET stale=1 WHERE stale=0')
                db.execute("""UPDATE node_state SET agent_process_status='OFFLINE',
                    market_connection_status='UNKNOWN', trade_connection_status='UNKNOWN',
                    broker_account_status='UNKNOWN', execution_enabled=0, reconciliation_required=1""")
            reason = 'ONLINE' if online else ('NO_SESSION' if not row else 'STARTING' if starting else 'SDK_STALE' if not fresh else 'PROCESS_UNVERIFIED')
            connections = db.execute('SELECT trade_connected,market_connected,account_verified FROM ipc_connection_state WHERE session_id=?', (row['session_id'],)).fetchone() if online else None
            if online:
                if not connections:
                    reason = 'CONNECTIVITY_PENDING'
                elif not connections['account_verified']:
                    reason = 'ACCOUNT_UNVERIFIED'
                elif not connections['trade_connected']:
                    reason = 'TRADE_DISCONNECTED'
                elif not connections['market_connected']:
                    reason = 'MARKET_DISCONNECTED'
            return {'agent_online': online, 'sdk_progress_fresh': fresh,
                    'agent_process_online': verified, 'connection_state_reason': reason,
                    'trade_connected': bool(connections and connections['trade_connected']),
                    'market_connected': bool(connections and connections['market_connected']),
                    'account_verified': bool(connections and connections['account_verified'])}

    def hello(self, identity: dict[str, Any], expected: dict[str, str]) -> dict[str, str]:
        required = ("node_id", "account_mode", "strategy_id", "broker_account_key")
        if any(identity.get(k) != expected.get(k) or not expected.get(k) for k in required):
            raise SessionError("identity mismatch")
        pid, instance, started = identity.get("pid"), identity.get("agent_instance_id"), identity.get("started_at")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 or not isinstance(instance, str) or not instance or not isinstance(started, str) or not started:
            raise SessionError("invalid process identity")
        if self.process_verifier is None:
            raise SessionError('process verification unavailable')
        try:
            verified = self.process_verifier(pid, started) is True
        except (OSError, ValueError):
            verified = False
        if not verified:
            raise SessionError('process identity cannot be verified')
        session = secrets.token_urlsafe(32)
        try:
            with closing(connect(self.path)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._assert_current_epoch(db)
                db.execute("INSERT INTO ipc_agent_sessions(session_id,node_epoch,agent_instance_id,node_id,account_mode,strategy_id,broker_account_key,pid,started_at,state,last_seen_monotonic) VALUES(?,?,?,?,?,?,?,?,?,'ACTIVE',?)",
                    (session, self.epoch, instance, *(identity[k] for k in required), pid, started, self.clock()))
                db.execute("INSERT OR IGNORE INTO node_state(node_id,broker_account_key,account_mode,updated_at) VALUES(?,?,?,?)", (identity['node_id'],identity['broker_account_key'],identity['account_mode'],datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError as exc:
            raise SessionError("active session exists") from exc
        return {"session_id": session, "node_epoch": self.epoch}

    def heartbeat(self, session: str, epoch: str, sequence: int, callback_counter: int) -> None:
        if epoch != self.epoch or isinstance(sequence, bool) or not isinstance(sequence, int) or isinstance(callback_counter, bool) or not isinstance(callback_counter, int):
            raise SessionError("invalid heartbeat")
        with closing(connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._assert_current_epoch(db)
            self._assert_process_identity(db, session, epoch)
            now = self.clock()
            updated = db.execute("""UPDATE ipc_agent_sessions SET last_sequence=?,callback_counter=?,last_seen_monotonic=?
                WHERE session_id=? AND node_epoch=? AND state='ACTIVE'
                  AND last_sequence < ? AND callback_counter < ?
                  AND last_seen_monotonic <= ? AND last_seen_monotonic >= ?""",
                (sequence, callback_counter, now, session, epoch, sequence, callback_counter, now, now - self.heartbeat_timeout_seconds))
            if updated.rowcount != 1:
                raise SessionError("stale session or SDK progress")

    def goodbye(self, session: str, epoch: str) -> bool:
        if epoch != self.epoch:
            raise SessionError('stale node epoch')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._assert_current_epoch(db)
            row = db.execute('SELECT state FROM ipc_agent_sessions WHERE session_id=? AND node_epoch=?', (session, epoch)).fetchone()
            if not row:
                raise SessionError('unknown session')
            if row['state'] == 'ENDED':
                return False
            if row['state'] != 'ACTIVE':
                raise SessionError('stale session')
            self._assert_process_identity(db, session, epoch)
            db.execute("UPDATE ipc_agent_sessions SET state='ENDED' WHERE session_id=?", (session,))
            db.execute("UPDATE commands SET status='UNKNOWN',error_code='AGENT_INTERRUPTED',error_message='Agent stopped during dispatch' WHERE status='DISPATCHING' AND ipc_session_id=?", (session,))
            db.execute('UPDATE snapshots SET stale=1 WHERE stale=0')
            db.execute("""UPDATE node_state SET agent_process_status='OFFLINE',
                market_connection_status='UNKNOWN', trade_connection_status='UNKNOWN',
                broker_account_status='UNKNOWN', execution_enabled=0, reconciliation_required=1""")
        return True

    def connectivity(self, session: str, epoch: str, sequence: int, trade_connected: bool, market_connected: bool, account_verified: bool) -> int:
        if epoch != self.epoch or type(sequence) is not int or sequence <= 0 or any(type(x) is not bool for x in (trade_connected, market_connected, account_verified)):
            raise SessionError('invalid connection state')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._assert_current_epoch(db)
            self._assert_process_identity(db, session, epoch)
            now = self.clock()
            row = db.execute("SELECT last_sequence FROM ipc_agent_sessions WHERE session_id=? AND node_epoch=? AND state='ACTIVE' AND callback_counter>0 AND last_seen_monotonic BETWEEN ? AND ?", (session, epoch, now-self.heartbeat_timeout_seconds, now)).fetchone()
            if not row:
                raise SessionError('stale session')
            if row['last_sequence'] != sequence:
                raise SessionError('connection sequence mismatch')
            prior = db.execute('SELECT * FROM ipc_connection_state WHERE session_id=?', (session,)).fetchone()
            if prior and prior['sequence'] == sequence:
                if (prior['trade_connected'], prior['market_connected'], prior['account_verified']) != (int(trade_connected), int(market_connected), int(account_verified)):
                    raise SessionError('connection sequence conflict')
                return int(prior['generation'])
            if prior and prior['sequence'] > sequence:
                raise SessionError('stale connection sequence')
            generation = 1 if prior is None else int(prior['generation']) + int((prior['trade_connected'], prior['market_connected'], prior['account_verified']) != (int(trade_connected), int(market_connected), int(account_verified)))
            db.execute('''INSERT INTO ipc_connection_state(session_id,trade_connected,market_connected,account_verified,sequence,generation) VALUES(?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET
                trade_connected=excluded.trade_connected, market_connected=excluded.market_connected,
                account_verified=excluded.account_verified,sequence=excluded.sequence,generation=excluded.generation''', (session, int(trade_connected), int(market_connected), int(account_verified), sequence, generation))
            stamp = datetime.now(timezone.utc).isoformat()
            db.execute("UPDATE node_state SET agent_process_status='ONLINE',trade_connection_status=?,market_connection_status=?,broker_account_status=?,last_agent_heartbeat_at=?,updated_at=?", ('CONNECTED' if trade_connected else 'DISCONNECTED', 'CONNECTED' if market_connected else 'DISCONNECTED', 'CONNECTED' if account_verified else 'MISMATCH', stamp, stamp))
            if not trade_connected or not market_connected or not account_verified:
                db.execute('UPDATE snapshots SET stale=1 WHERE stale=0')
                db.execute('UPDATE node_state SET execution_enabled=0,reconciliation_required=1')
            return generation

    def snapshot(self, session: str, epoch: str, message_id: str, batch: dict[str, Any]) -> bool:
        return self._snapshot(session, epoch, message_id, batch, None, None)

    def ingest_snapshot(self, session: str, epoch: str, message_id: str, batch: dict[str, Any], expected_account_id: str, generation: int) -> bool:
        if not expected_account_id:
            raise SessionError('expected account required')
        if type(generation) is not int or generation <= 0:
            raise SessionError('connection generation required')
        return self._snapshot(session, epoch, message_id, batch, expected_account_id, generation)

    def _snapshot(self, session: str, epoch: str, message_id: str, batch: dict[str, Any], publish_account_id: str | None, generation: int | None) -> bool:
        if epoch != self.epoch or not isinstance(message_id, str) or not message_id:
            raise SessionError("invalid snapshot identity")
        if set(batch) != {"batch_id", "as_of", "account", "positions", "orders", "unfinished_orders", "fills", "component_counts"}:
            raise SessionError("snapshot must include all components")
        components = ('positions', 'orders', 'unfinished_orders', 'fills')
        if not isinstance(batch['batch_id'], str) or not batch['batch_id'] or not isinstance(batch['as_of'], str) or not batch['as_of'] or not isinstance(batch['account'], dict) or any(not isinstance(batch[k], list) for k in components):
            raise SessionError("invalid snapshot components")
        counts = batch['component_counts']
        if not isinstance(counts, dict) or set(counts) != set(components) or any(type(counts[k]) is not int or counts[k] != len(batch[k]) for k in components):
            raise SessionError('snapshot component counts do not match')
        try:
            stamp = datetime.fromisoformat(batch['as_of'].replace('Z', '+00:00'))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError('timezone required')
        except ValueError as exc:
            raise SessionError('snapshot time is invalid or lacks timezone') from exc
        payload = json.dumps(batch, sort_keys=True, separators=(',', ':'), allow_nan=False, ensure_ascii=False)
        digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._assert_current_epoch(db)
            self._assert_process_identity(db, session, epoch)
            now = self.clock()
            active = db.execute("SELECT 1 FROM ipc_agent_sessions WHERE session_id=? AND node_epoch=? AND state='ACTIVE' AND callback_counter > 0 AND last_seen_monotonic BETWEEN ? AND ?", (session, epoch, now - self.heartbeat_timeout_seconds, now)).fetchone()
            if not active:
                raise SessionError('stale session')
            if publish_account_id is not None:
                conn = db.execute('''SELECT c.*,s.last_sequence FROM ipc_connection_state c JOIN ipc_agent_sessions s ON s.session_id=c.session_id WHERE c.session_id=?''', (session,)).fetchone()
                if not conn or not conn['trade_connected'] or not conn['market_connected'] or not conn['account_verified'] or conn['sequence'] != conn['last_sequence'] or conn['generation'] != generation:
                    raise SessionError('connection generation is stale or unavailable')
            existing = db.execute('SELECT session_id,message_type,payload_hash FROM ipc_inbox WHERE message_id=?', (message_id,)).fetchone()
            if existing:
                if tuple(existing) != (session, 'SNAPSHOT', digest):
                    raise SessionError('message id conflict')
                if publish_account_id is not None:
                    self._publish_snapshot_in_transaction(db, session, batch['batch_id'], publish_account_id)
                return False
            try:
                db.execute('INSERT INTO ipc_snapshot_batches(batch_id,session_id,payload_json,payload_hash) VALUES(?,?,?,?)', (batch['batch_id'], session, payload, digest))
                db.execute('INSERT INTO ipc_inbox(message_id,session_id,message_type,payload_hash) VALUES(?,?,?,?)', (message_id, session, 'SNAPSHOT', digest))
            except sqlite3.IntegrityError as exc:
                raise SessionError('snapshot batch conflict') from exc
            if publish_account_id is not None:
                self._publish_snapshot_in_transaction(db, session, batch['batch_id'], publish_account_id)
        return True

    def publish_snapshot(self, session: str, epoch: str, batch_id: str, expected_account_id: str, generation: int) -> bool:
        """Publish all v1 snapshot components in one transaction, or none.

        This does not set readiness: session identity, reconciliation and SDK
        connectivity must be established separately before execution is allowed.
        """
        if epoch != self.epoch or not expected_account_id or type(generation) is not int or generation <= 0:
            raise SessionError('invalid snapshot publication identity')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._assert_current_epoch(db)
            self._assert_process_identity(db, session, epoch)
            now_mono = self.clock()
            active = db.execute("SELECT 1 FROM ipc_agent_sessions WHERE session_id=? AND node_epoch=? AND state='ACTIVE' AND callback_counter > 0 AND last_seen_monotonic BETWEEN ? AND ?", (session, epoch, now_mono - self.heartbeat_timeout_seconds, now_mono)).fetchone()
            if not active:
                raise SessionError('stale session')
            conn = db.execute('''SELECT c.*,s.last_sequence FROM ipc_connection_state c JOIN ipc_agent_sessions s ON s.session_id=c.session_id WHERE c.session_id=?''', (session,)).fetchone()
            if not conn or not conn['trade_connected'] or not conn['market_connected'] or not conn['account_verified'] or conn['sequence'] != conn['last_sequence'] or conn['generation'] != generation:
                raise SessionError('connection generation is stale or unavailable')
            return self._publish_snapshot_in_transaction(db, session, batch_id, expected_account_id)

    def _publish_snapshot_in_transaction(self, db: sqlite3.Connection, session: str, batch_id: str, expected_account_id: str) -> bool:
        row = db.execute('SELECT payload_json,published FROM ipc_snapshot_batches WHERE batch_id=? AND session_id=?', (batch_id, session)).fetchone()
        if not row:
            raise SessionError('snapshot batch missing')
        batch = json.loads(row['payload_json'])
        account = batch['account']
        normalized = account.get('normalized') if isinstance(account, dict) else None
        if not isinstance(normalized, dict) or normalized.get('account_id') != expected_account_id or normalized.get('total_asset') is None or normalized.get('available_cash') is None:
            raise SessionError('broker account snapshot is invalid')
        if row['published']:
            return False
        for component in ('positions', 'orders', 'unfinished_orders', 'fills'):
            if any(not isinstance(item, dict) or not isinstance(item.get('normalized'), dict) or not isinstance(item.get('raw'), dict) for item in batch[component]):
                raise SessionError('snapshot item is missing normalized or raw facts')
        for component in ('orders', 'unfinished_orders', 'fills'):
            for item in batch[component]:
                normalized = item['normalized']
                broker_id = normalized.get('broker_order_id') or None
                broker_client_id = normalized.get('broker_client_order_id') or None
                if not broker_id and not broker_client_id:
                    raise SessionError('broker order identity missing from snapshot')
                links = db.execute('''SELECT client_order_id FROM order_links WHERE
                    (? IS NOT NULL AND broker_order_id=?) OR (? IS NOT NULL AND broker_client_order_id=?)''',
                    (broker_id, broker_id, broker_client_id, broker_client_id)).fetchall()
                candidates = {link['client_order_id'] for link in links}
                if len(candidates) > 1:
                    raise SessionError('ambiguous broker order identity in snapshot')
                if candidates:
                    local_id = next(iter(candidates))
                    normalized['client_order_id'] = local_id
                    if broker_id and component in ('orders', 'unfinished_orders'):
                        db.execute('UPDATE order_links SET broker_order_id=?,last_broker_status=?,last_raw_status=?,updated_at=? WHERE client_order_id=?',
                            (broker_id, normalized.get('status'), normalized.get('raw_status'), datetime.now(timezone.utc).isoformat(), local_id))
        try:
            as_of = datetime.fromisoformat(batch['as_of'].replace('Z', '+00:00'))
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                raise ValueError('timezone required')
            for old in db.execute('SELECT as_of FROM snapshots'):
                old_time = datetime.fromisoformat(old['as_of'].replace('Z', '+00:00'))
                if old_time.tzinfo is None or old_time.utcoffset() is None or old_time > as_of:
                    raise ValueError('existing snapshot is newer or has ambiguous time')
        except ValueError as exc:
            raise SessionError('snapshot time cannot safely supersede existing data') from exc
        updated_at = datetime.now(timezone.utc).isoformat()
        for snapshot_type, key in (('ACCOUNT', 'account'), ('POSITIONS', 'positions'), ('ORDERS', 'orders'), ('UNFINISHED_ORDERS', 'unfinished_orders'), ('FILLS', 'fills')):
            payload = json.dumps(batch[key], ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            db.execute('''INSERT INTO snapshots(snapshot_type,snapshot_version,as_of,source,stale,payload_json,updated_at)
                VALUES(?,1,?,'GM_QUERY',0,?,?)
                ON CONFLICT(snapshot_type) DO UPDATE SET snapshot_version=snapshots.snapshot_version+1,
                as_of=excluded.as_of, source=excluded.source, stale=0,
                payload_json=excluded.payload_json, updated_at=excluded.updated_at''',
                (snapshot_type, batch['as_of'], payload, updated_at))
        db.execute('UPDATE ipc_snapshot_batches SET published=1 WHERE batch_id=? AND session_id=?', (batch_id, session))
        return True

    def promote_fill(self, event_id: str) -> int:
        """Promote one staged fill using broker IDs only; never guess a local order."""
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._assert_current_epoch(db)
            return self._promote_fill_in_transaction(db, event_id)

    def _promote_fill_in_transaction(self, db: sqlite3.Connection, event_id: str) -> int:
        row = db.execute('''SELECT e.payload_json,s.broker_account_key FROM ipc_staged_events e
            JOIN ipc_agent_sessions s ON s.session_id=e.session_id
            WHERE e.event_id=? AND e.event_type='FILL' ''', (event_id,)).fetchone()
        if not row:
            raise SessionError('staged fill missing')
        event = json.loads(row['payload_json'])
        mapped = event['payload']
        normalized = mapped.get('normalized')
        if not isinstance(normalized, dict):
            raise SessionError('fill normalized data missing')
        execution_id = normalized.get('broker_execution_id')
        occurred_at = normalized.get('occurred_at')
        broker_order_id = normalized.get('broker_order_id')
        broker_client_id = normalized.get('broker_client_order_id')
        if not all(isinstance(x, str) and x for x in (execution_id, occurred_at, broker_order_id)):
            raise SessionError('fill lacks authoritative identity')
        try:
            stamp = datetime.fromisoformat(occurred_at.replace('Z', '+00:00'))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError('timezone required')
            trade_date = stamp.astimezone(timezone(timedelta(hours=8))).date().isoformat()
        except ValueError as exc:
            raise SessionError('fill time is invalid or lacks timezone') from exc
        economic_fields = ('broker_order_id', 'instrument', 'side', 'price', 'quantity')
        if any(normalized.get(k) is None for k in economic_fields):
            raise SessionError('fill economic facts missing')
        economic = {k: normalized[k] for k in economic_fields}
        economic_hash = hashlib.sha256(json.dumps(economic, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        previous = db.execute('SELECT economic_hash,broker_event_seq FROM ipc_fill_facts WHERE broker_account_key=? AND trade_date=? AND broker_execution_id=?', (row['broker_account_key'], trade_date, execution_id)).fetchone()
        if previous:
            if previous['economic_hash'] != economic_hash:
                raise SessionError('conflicting broker fill identity')
            return int(previous['broker_event_seq'])
        # Legacy events require explicit reconciliation before migration;
        # we cannot assume their account/date scope or silently duplicate them.
        if db.execute("SELECT 1 FROM broker_events WHERE broker_execution_id=? LIMIT 1", (execution_id,)).fetchone():
            raise SessionError('legacy broker fill requires reconciliation')
        links = db.execute('''SELECT client_order_id FROM order_links
            WHERE (broker_order_id IS NOT NULL AND broker_order_id=?)
               OR (broker_client_order_id IS NOT NULL AND broker_client_order_id=?)''',
            (broker_order_id, broker_client_id)).fetchall()
        clients = {link['client_order_id'] for link in links}
        if len(clients) > 1:
            raise SessionError('ambiguous broker order identity')
        local_id = next(iter(clients)) if clients else None
        normalized['client_order_id'] = local_id
        payload = json.dumps(mapped, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        stable_id = 'v2-fill:' + hashlib.sha256(json.dumps([row['broker_account_key'], trade_date, execution_id], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        cursor = db.execute('''INSERT INTO broker_events(event_id,event_type,client_order_id,broker_order_id,broker_execution_id,source,raw_fingerprint,payload_json,occurred_at,received_at)
            VALUES(?,'FILL',?,?,?,'CALLBACK',?,?,?,?)''', (stable_id, local_id, broker_order_id, execution_id, hashlib.sha256(payload.encode()).hexdigest(), payload, occurred_at, now))
        seq = int(cursor.lastrowid)
        db.execute('INSERT INTO ipc_fill_facts VALUES(?,?,?,?,?)', (row['broker_account_key'], trade_date, execution_id, economic_hash, seq))
        return seq

    def _promote_order_in_transaction(self, db: sqlite3.Connection, event_id: str) -> int:
        row = db.execute('''SELECT e.payload_json,s.broker_account_key FROM ipc_staged_events e
            JOIN ipc_agent_sessions s ON s.session_id=e.session_id
            WHERE e.event_id=? AND e.event_type='ORDER_STATUS' ''', (event_id,)).fetchone()
        if not row:
            raise SessionError('staged order status missing')
        event = json.loads(row['payload_json'])
        mapped = event['payload']
        source_fingerprint = hashlib.sha256(json.dumps(mapped, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        normalized = mapped.get('normalized')
        if not isinstance(normalized, dict):
            raise SessionError('order normalized data missing')
        broker_id = normalized.get('broker_order_id')
        broker_client_id = normalized.get('broker_client_order_id')
        updated_at = normalized.get('updated_at')
        raw_status = normalized.get('raw_status')
        if not (broker_id or broker_client_id) or not isinstance(updated_at, str) or not updated_at or raw_status is None:
            raise SessionError('order status lacks authoritative identity')
        try:
            stamp = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError('timezone required')
        except ValueError as exc:
            raise SessionError('order time is invalid or lacks timezone') from exc
        stable_id = 'v2-order:' + hashlib.sha256(json.dumps([row['broker_account_key'], broker_id or broker_client_id, raw_status, updated_at], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        links = db.execute('''SELECT client_order_id FROM order_links
            WHERE (broker_order_id IS NOT NULL AND broker_order_id=?)
               OR (broker_client_order_id IS NOT NULL AND broker_client_order_id=?)''',
            (broker_id, normalized.get('broker_client_order_id'))).fetchall()
        clients = {link['client_order_id'] for link in links}
        if len(clients) > 1:
            raise SessionError('ambiguous broker order identity')
        local_id = next(iter(clients)) if clients else None
        if local_id and broker_id:
            db.execute('UPDATE order_links SET broker_order_id=?,last_broker_status=?,last_raw_status=?,updated_at=? WHERE client_order_id=?', (broker_id, normalized.get('status'), raw_status, datetime.now(timezone.utc).isoformat(), local_id))
        normalized['client_order_id'] = local_id
        payload = json.dumps(mapped, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        fingerprint = source_fingerprint
        old = db.execute('SELECT seq,raw_fingerprint FROM broker_events WHERE event_id=?', (stable_id,)).fetchone()
        if old:
            if old['raw_fingerprint'] != fingerprint:
                raise SessionError('conflicting broker order status identity')
            return int(old['seq'])
        for legacy in db.execute("SELECT seq,payload_json FROM broker_events WHERE event_type='ORDER_STATUS' AND broker_order_id=? AND event_id NOT LIKE 'v2-order:%'", (broker_id,)):
            try:
                old_payload = json.loads(legacy['payload_json'])
                old_norm = old_payload['normalized']
                if not isinstance(old_norm, dict):
                    raise ValueError('invalid normalized order')
            except (ValueError, TypeError, KeyError) as exc:
                raise SessionError('legacy order status requires reconciliation') from exc
            if old_norm.get('raw_status') == raw_status and old_norm.get('updated_at') == updated_at:
                if old_payload != mapped:
                    raise SessionError('legacy order status requires reconciliation')
                return int(legacy['seq'])
        now = datetime.now(timezone.utc).isoformat()
        cursor = db.execute('''INSERT INTO broker_events(event_id,event_type,client_order_id,broker_order_id,source,raw_fingerprint,payload_json,occurred_at,received_at)
            VALUES(?,'ORDER_STATUS',?,?,'CALLBACK',?,?,?,?)''',
            (stable_id, local_id, broker_id, fingerprint, payload, updated_at, now))
        return int(cursor.lastrowid)


    def events(self, session: str, epoch: str, message_id: str, events: list[dict[str, Any]]) -> bool:
        """Stage and process each IPC batch transactionally; retain unresolved facts."""
        if epoch != self.epoch or not isinstance(message_id, str) or not message_id or not isinstance(events, list) or not events:
            raise SessionError('invalid event batch')
        encoded = []
        for event in events:
            if not isinstance(event, dict) or set(event) != {'event_id', 'event_type', 'payload'}:
                raise SessionError('invalid event envelope')
            if not isinstance(event['event_id'], str) or not event['event_id'] or not isinstance(event['event_type'], str) or not event['event_type'] or not isinstance(event['payload'], dict):
                raise SessionError('invalid event fields')
            raw = json.dumps(event, sort_keys=True, separators=(',', ':'), allow_nan=False, ensure_ascii=False)
            encoded.append((event, raw, hashlib.sha256(raw.encode('utf-8')).hexdigest()))
        batch_json = json.dumps(events, sort_keys=True, separators=(',', ':'), allow_nan=False, ensure_ascii=False)
        digest = hashlib.sha256(batch_json.encode('utf-8')).hexdigest()
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._assert_current_epoch(db)
            now = self.clock()
            self._assert_process_identity(db, session, epoch)
            active = db.execute("SELECT 1 FROM ipc_agent_sessions WHERE session_id=? AND node_epoch=? AND state='ACTIVE' AND callback_counter > 0 AND last_seen_monotonic BETWEEN ? AND ?", (session, epoch, now-self.heartbeat_timeout_seconds, now)).fetchone()
            if not active:
                raise SessionError('stale session')
            existing = db.execute('SELECT session_id,message_type,payload_hash FROM ipc_inbox WHERE message_id=?', (message_id,)).fetchone()
            if existing:
                if (existing['message_type'], existing['payload_hash']) != ('EVENTS', digest):
                    raise SessionError('message id conflict')
                return False
            for event, raw, fingerprint in encoded:
                prior = db.execute('SELECT event_type,payload_hash FROM ipc_staged_events WHERE event_id=?', (event['event_id'],)).fetchone()
                if prior:
                    if tuple(prior) != (event['event_type'], fingerprint):
                        raise SessionError('event id conflict')
                    continue
                db.execute('INSERT INTO ipc_staged_events(event_id,session_id,event_type,payload_json,payload_hash) VALUES(?,?,?,?,?)', (event['event_id'], session, event['event_type'], raw, fingerprint))
                db.execute('SAVEPOINT process_event')
                try:
                    if event['event_type'] == 'FILL':
                        self._promote_fill_in_transaction(db, event['event_id'])
                    elif event['event_type'] == 'ORDER_STATUS':
                        self._promote_order_in_transaction(db, event['event_id'])
                    elif event['event_type'] == 'GM_ERROR':
                        db.execute("INSERT OR IGNORE INTO broker_events(event_id,event_type,source,payload_json,occurred_at,received_at) VALUES(?,'GM_ERROR','CALLBACK',?,?,?)", (event['event_id'], json.dumps(event['payload'],ensure_ascii=False), datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))
                    else:
                        raise SessionError('event type requires processing')
                except SessionError as exc:
                    db.execute('ROLLBACK TO process_event')
                    db.execute('INSERT INTO ipc_event_issues(event_id,reason,created_at) VALUES(?,?,?)',
                        (event['event_id'], str(exc), datetime.now(timezone.utc).isoformat()))
                    db.execute('UPDATE node_state SET execution_enabled=0,reconciliation_required=1')
                finally:
                    db.execute('RELEASE process_event')
            db.execute('INSERT INTO ipc_inbox(message_id,session_id,message_type,payload_hash) VALUES(?,?,?,?)', (message_id, session, 'EVENTS', digest))
        return True
