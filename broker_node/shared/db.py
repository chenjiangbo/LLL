from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS node_state (
    node_id TEXT PRIMARY KEY,
    broker_account_key TEXT NOT NULL,
    account_mode TEXT NOT NULL CHECK (account_mode IN ('SIM', 'LIVE')),
    api_process_status TEXT NOT NULL DEFAULT 'OFFLINE',
    agent_process_status TEXT NOT NULL DEFAULT 'OFFLINE',
    market_connection_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    trade_connection_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    broker_account_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    execution_enabled INTEGER NOT NULL DEFAULT 0 CHECK (execution_enabled IN (0, 1)),
    paused INTEGER NOT NULL DEFAULT 1 CHECK (paused IN (0, 1)),
    pause_reason TEXT,
    reconciliation_required INTEGER NOT NULL DEFAULT 1 CHECK (reconciliation_required IN (0, 1)),
    last_agent_heartbeat_at TEXT,
    last_broker_event_at TEXT,
    last_account_sync_at TEXT,
    last_position_sync_at TEXT,
    last_order_sync_at TEXT,
    last_fill_sync_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commands (
    command_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    command_type TEXT NOT NULL,
    client_order_id TEXT,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    broker_order_id TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    validated_at TEXT,
    claimed_at TEXT,
    dispatched_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_links (
    client_order_id TEXT PRIMARY KEY,
    submit_command_id TEXT NOT NULL,
    broker_order_id TEXT,
    exchange_order_id TEXT,
    last_broker_status TEXT,
    last_raw_status TEXT,
    origin TEXT NOT NULL CHECK (origin IN ('SYSTEM', 'EXTERNAL')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broker_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    client_order_id TEXT,
    broker_order_id TEXT,
    broker_execution_id TEXT,
    source TEXT NOT NULL,
    raw_fingerprint TEXT,
    payload_json TEXT NOT NULL,
    occurred_at TEXT,
    received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_type TEXT PRIMARY KEY,
    snapshot_version INTEGER NOT NULL,
    as_of TEXT NOT NULL,
    source TEXT NOT NULL,
    stale INTEGER NOT NULL CHECK (stale IN (0, 1)),
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quote_subscriptions (
    owner_type TEXT NOT NULL CHECK (owner_type = 'EXECUTION_PLAN'),
    owner_id TEXT NOT NULL,
    symbol_key TEXT NOT NULL,
    broker_symbol TEXT NOT NULL,
    lease_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (owner_type, owner_id, symbol_key)
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize(path: Path) -> None:
    with connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA)
