"""Broker Node process manager for the single Agent belonging to this node.

The API process is the node's supervisor.  It owns exactly one Agent child,
checks that child's durable heartbeat, and restarts only that child when the
heartbeat becomes stale.  The Agent itself remains focused on gm.api work and
does not try to supervise a second copy of itself.
"""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from broker_node.shared.config import NodeConfig


STARTUP_GRACE_SECONDS = 120.0
RESTART_DELAY_SECONDS = 5.0
MAX_RESTART_DELAY_SECONDS = 60.0
CALLBACK_TIMEOUT_SECONDS = 60.0


def _heartbeat_age_seconds(database: Path) -> float | None:
    if not database.is_file():
        return None
    try:
        with sqlite3.connect(database, timeout=30.0) as connection:
            row = connection.execute(
                "SELECT last_agent_heartbeat_at FROM node_state LIMIT 1"
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    try:
        timestamp = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds())
    except ValueError:
        return None


class AgentManager:
    """Supervise the Agent associated with one Broker Node config."""

    def __init__(self, config: NodeConfig):
        self.config = config
        self.database = Path(config.raw["runtime"]["durable_db"])
        self.log_path = Path(config.raw["runtime"]["log_dir"]) / "agent.manager.log"
        self.agent_log_path = Path(config.raw["runtime"]["log_dir"]) / "agent.autostart.log"
        self.offline_seconds = max(CALLBACK_TIMEOUT_SECONDS, float(config.raw["sync"]["agent_offline_seconds"]))
        self.startup_grace_seconds = float(
            config.raw["sync"].get("agent_startup_grace_seconds", STARTUP_GRACE_SECONDS)
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._child: subprocess.Popen[bytes] | None = None
        self._child_lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        # The production Agent is a Windows/QMT process.  Tests and local API
        # tooling must not spawn a gm.api child on the development Mac.
        # Both SIM and LIVE use the same terminal strategy and HTTP IPC path.
        return os.name == "nt" and bool(self.config.raw.get("ipc_v2"))

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, name="broker-node-agent-manager", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._child_lock:
            child = self._child
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
        if self._thread:
            self._thread.join(timeout=20)

    def _log(self, message: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8", buffering=1) as stream:
            stream.write(f"{datetime.now(timezone.utc).isoformat()} MANAGER {message}\n")

    def _spawn(self, log: TextIO) -> subprocess.Popen[bytes]:
        if not self.config.raw.get("ipc_v2"):
            raise RuntimeError("SIM and LIVE Agents require the HTTP IPC runtime")
        environment = os.environ.copy()
        environment["BROKER_NODE_CONFIG"] = str(self.config.path)
        environment["PYTHONPATH"] = r"D:\QMT\workspace"
        strategy = Path.home() / '.essence' / 'projects' / self.config.raw['gm']['strategy_id'] / 'main.py'
        if not strategy.is_file():
            raise RuntimeError('GM strategy file is missing')
        command = [sys.executable, '-u', str(strategy)]
        return subprocess.Popen(
            command,
            cwd=r"D:\QMT\workspace",
            env=environment,
            stdout=log,
            stderr=log,
        )

    def _run(self) -> None:
        restart_delay = RESTART_DELAY_SECONDS
        while not self._stop.is_set():
            from broker_node.shared.windows_process import verify_process
            try:
                with sqlite3.connect(self.database, timeout=30.0) as connection:
                    session = connection.execute("SELECT pid,started_at,state,last_seen_monotonic FROM ipc_agent_sessions ORDER BY rowid DESC LIMIT 1").fetchone()
            except sqlite3.Error as exc:
                self._log(f'agent_health_failed error={exc}')
                self._stop.wait(RESTART_DELAY_SECONDS)
                continue
            age = _heartbeat_age_seconds(self.database)
            alive = bool(session and verify_process(session[0], session[1]))
            progress = bool(session and session[2] == 'ACTIVE' and 0 <= time.monotonic() - session[3] <= self.offline_seconds)
            if alive and (progress or (age is not None and age <= self.offline_seconds)):
                self._stop.wait(2)
                continue
            # A terminal-started process can outlive its callback heartbeat.
            # Stop that exact process before starting another strategy.
            if alive:
                self._log(f'agent_restart reason=heartbeat_stale pid={session[0]}')
                try:
                    os.kill(session[0], signal.SIGTERM)
                except OSError as exc:
                    self._log(f'agent_stop_failed pid={session[0]} error={exc}')
                    self._stop.wait(RESTART_DELAY_SECONDS)
                    continue
            started_at = time.monotonic()
            heartbeat_seen = False
            with self.agent_log_path.open("a", encoding="utf-8", buffering=1) as log:
                try:
                    child = self._spawn(log)
                except (OSError, RuntimeError) as exc:
                    self._log(f'agent_start_failed error={exc}')
                    self._stop.wait(restart_delay)
                    restart_delay = min(MAX_RESTART_DELAY_SECONDS, restart_delay * 2)
                    continue
                with self._child_lock:
                    self._child = child
                self._log(f"agent_started pid={child.pid}")
                while child.poll() is None and not self._stop.is_set():
                    age = _heartbeat_age_seconds(self.database)
                    heartbeat_seen = heartbeat_seen or age is not None
                    if time.monotonic() - started_at >= self.startup_grace_seconds:
                        if age is None or age > self.offline_seconds:
                            reason = "heartbeat_missing" if age is None else f"heartbeat_stale age={age:.1f}s"
                            self._log(f"agent_restart reason={reason}")
                            child.terminate()
                            try:
                                child.wait(timeout=15)
                            except subprocess.TimeoutExpired:
                                child.kill()
                            break
                    time.sleep(1.0)
                exit_code = child.poll()
                with self._child_lock:
                    self._child = None
            if self._stop.is_set():
                break
            self._log(f"agent_exited code={exit_code} heartbeat_seen={heartbeat_seen}")
            time.sleep(restart_delay)
            restart_delay = min(MAX_RESTART_DELAY_SECONDS, restart_delay * 2)


def create_agent_manager(config: NodeConfig) -> AgentManager:
    return AgentManager(config)
