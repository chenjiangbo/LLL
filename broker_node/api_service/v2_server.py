"""V2 dual-listener lifecycle. No legacy Agent process is spawned here."""
from __future__ import annotations

import asyncio
import ipaddress
import math
import os
import re
import sqlite3
import socket
from contextlib import nullcontext
from pathlib import Path

import uvicorn

from broker_node.api_service.v2_bootstrap import assemble_v2
from broker_node.shared.config import ConfigError, NodeConfig
from broker_node.shared.windows_process import verify_process
from broker_node.api_service.agent_manager import create_agent_manager


class NodeOwnerLock:
    """Exclusive V2 ownership of one durable DB; does not detect V1 processes."""
    def __init__(self, durable_db: Path):
        self.path = durable_db.with_name(durable_db.name + '.v2.lock')
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, 'a+b')
        try:
            f.seek(0, os.SEEK_END)
            if f.tell() == 0:
                f.write(b'\0'); f.flush()
            f.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            f.close()
            raise
        self.file = f
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.file is not None:
            self.file.close()
            self.file = None


def open_listener(host: str, port: int, *, internal: bool) -> socket.socket:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ConfigError('listener host must be an IP literal') from exc
    if internal and not address.is_loopback:
        raise ConfigError('IPC listener must be loopback')
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigError('listener port is invalid')
    sock = socket.socket(socket.AF_INET6 if address.version == 6 else socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((host, port))
        sock.listen(128)
        sock.setblocking(False)
        return sock
    except BaseException:
        sock.close()
        raise


async def serve_apps(public, private, store, public_socket, private_socket, health_interval_seconds: float, agent_manager=None) -> None:
    if isinstance(health_interval_seconds, bool) or not isinstance(health_interval_seconds, (int, float)) or not math.isfinite(health_interval_seconds) or health_interval_seconds <= 0:
        raise ConfigError('explicit positive health interval required')
    # Uvicorn is embedded twice in the same loop; signal handling belongs to
    # the top-level process, not either embedded server.
    public_server = uvicorn.Server(uvicorn.Config(public, access_log=False, log_level='warning'))
    private_server = uvicorn.Server(uvicorn.Config(private, access_log=False, log_level='warning'))
    public_server.capture_signals = nullcontext
    private_server.capture_signals = nullcontext

    async def monitor():
        # Avoid interrupting ASGI lifespan startup. A listener that fails to
        # start completes its own task and is caught by FIRST_COMPLETED.
        while not (public_server.started and private_server.started):
            await asyncio.sleep(0.01)
        if agent_manager is not None:
            agent_manager.start()
        while True:
            # Exceptions must terminate both listeners; do not claim online on
            # an unhandled database or process-verification failure.
            try:
                await asyncio.to_thread(store.health)
            except sqlite3.OperationalError as exc:
                print('Node health check failed:', str(exc), flush=True)
            await asyncio.sleep(health_interval_seconds)

    tasks = [asyncio.create_task(public_server.serve(sockets=[public_socket])),
             asyncio.create_task(private_server.serve(sockets=[private_socket])),
             asyncio.create_task(monitor())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        raise RuntimeError('a V2 listener or health monitor stopped unexpectedly')
    finally:
        if agent_manager is not None:
            agent_manager.stop()
        public_server.should_exit = True
        private_server.should_exit = True
        if not tasks[2].done():
            tasks[2].cancel()
        # Give both ASGI lifespan handlers a bounded graceful shutdown.
        _, pending = await asyncio.wait(tasks[:2], timeout=5)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    if os.name != 'nt':
        raise ConfigError('V2 Windows launcher requires Windows')
    config_path = os.environ.get('BROKER_NODE_CONFIG')
    if not config_path:
        raise ConfigError('BROKER_NODE_CONFIG is required')
    config = NodeConfig.load(Path(config_path))
    ipc = config.raw.get('ipc_v2')
    if not isinstance(ipc, dict):
        raise ConfigError('ipc_v2 configuration is required')
    secret_name = ipc.get('credential_env')
    if not isinstance(secret_name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', secret_name):
        raise ConfigError('ipc_v2.credential_env must name an environment variable')
    if secret_name == config.raw['api'].get('token_env'):
        raise ConfigError('IPC and public API credentials must be independent')
    credential = os.environ.get(secret_name)
    if not credential:
        raise ConfigError('configured IPC credential environment variable is empty')
    interval = ipc.get('health_interval_seconds')
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
        raise ConfigError('ipc_v2.health_interval_seconds must be positive')
    # Bind both listeners before changing the DB epoch. If either port is in
    # use, startup fails without invalidating a currently running session.
    private_socket = open_listener(ipc.get('host'), ipc.get('port'), internal=True)
    try:
        public_socket = open_listener(config.raw['api'].get('host'), config.raw['api'].get('port'), internal=False)
        try:
            with NodeOwnerLock(Path(config.raw['runtime']['durable_db'])):
                public, private, store = assemble_v2(config, credential, verify_process)
                manager = create_agent_manager(config)
                asyncio.run(serve_apps(public, private, store, public_socket, private_socket, interval, manager))
        finally:
            public_socket.close()
    finally:
        private_socket.close()


if __name__ == '__main__':
    main()
