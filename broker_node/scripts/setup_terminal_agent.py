"""Configure an existing Windows Node and its GM terminal strategy."""
from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path


def setup(config_path: Path) -> None:
    import winreg

    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    port = int(config['api']['port'])
    strategy = config['gm']['strategy_id']
    account = config['expected_broker_account_id']
    strategy_path = Path.home() / '.essence' / 'projects' / strategy / 'main.py'
    if not strategy_path.is_file() or not account:
        raise ValueError('GM strategy or account configuration is missing')
    env_name = 'LLL_NODE_IPC_' + str(port)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
        try:
            secret = winreg.QueryValueEx(key, env_name)[0]
        except FileNotFoundError:
            secret = secrets.token_urlsafe(36)
            winreg.SetValueEx(key, env_name, 0, winreg.REG_SZ, secret)
    ipc_port = port + 1000
    config['ipc_v2'] = {'host': '127.0.0.1', 'port': ipc_port, 'max_body_bytes': 16777216,
                        'heartbeat_timeout_seconds': 30, 'health_interval_seconds': 3,
                        'credential_env': env_name}
    settings = {'node_id': config['node_id'], 'account_mode': config['account_mode'],
                'strategy_id': strategy, 'broker_account_key': config['broker_account_key'],
                'broker_account_id': account, 'ipc_host': '127.0.0.1', 'ipc_port': ipc_port,
                'ipc_credential': secret, 'ipc_timeout_seconds': 5, 'max_response_bytes': 16777216,
                'snapshot_interval_seconds': 15, 'event_queue_limit': 10000,
                'event_batch_limit': 500, 'timer_period_ms': 1000}
    source = ("import sys\nsys.path.insert(0, r'D:\\QMT\\workspace')\n"
              "from gm.api import run, MODE_LIVE\n"
              "from broker_node.gm_agent.terminal_strategy import *\n"
              "token = configure(" + repr(settings) + ")\n"
              "if __name__ == '__main__':\n"
              "    run(strategy_id=" + repr(strategy) + ", filename='main.py', mode=MODE_LIVE, token=token)\n")
    compile(source, str(strategy_path), 'exec')
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    strategy_path.write_text(source, encoding='utf-8')
    print('Configured Node port', port, 'for', config['account_mode'])


if __name__ == '__main__':
    setup(Path(sys.argv[1]))
