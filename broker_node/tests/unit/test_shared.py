from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from broker_node.shared.config import NodeConfig
from broker_node.shared.db import connect, initialize
from broker_node.shared.dto import decimal_to_json


def test_config_example_is_valid_and_live_gate_is_closed(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "config" / "config.example.json"
    config_path = tmp_path / "config.json"
    raw = json.loads(example.read_text(encoding="utf-8"))
    raw["gm"]["strategy_id"] = "strategy-for-test"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config = NodeConfig.load(config_path)
    assert config.raw["account_mode"] == "SIM"
    assert config.live_orders_enabled() is False


def test_live_read_only_configuration_keeps_writes_closed(tmp_path: Path, monkeypatch) -> None:
    raw = json.loads((Path(__file__).parents[2] / "config" / "config.example.json").read_text(encoding="utf-8"))
    raw["account_mode"] = "LIVE"
    raw["gm"]["strategy_id"] = "live-read-only-strategy"
    raw["expected_broker_account_id"] = "live-account"
    config_path = tmp_path / "live.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    assert NodeConfig.load(config_path).live_orders_enabled() is False


def test_live_write_gate_requires_explicit_two_factor_enablement(tmp_path: Path, monkeypatch) -> None:
    raw = json.loads((Path(__file__).parents[2] / "config" / "config.example.json").read_text(encoding="utf-8"))
    raw["account_mode"] = "LIVE"
    raw["gm"]["strategy_id"] = "live-strategy"
    raw["expected_broker_account_id"] = "live-account"
    raw["safety"]["allow_live_orders"] = True
    config_path = tmp_path / "live-enabled.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    assert NodeConfig.load(config_path).live_orders_enabled() is True


def test_durable_schema_is_complete(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "broker_node.sqlite3"
    initialize(path)
    with connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type='table'"
            )
        }
    assert {
        "node_state",
        "commands",
        "order_links",
        "broker_events",
        "snapshots",
        "quote_subscriptions",
    } <= tables


def test_decimal_is_serialized_as_string() -> None:
    assert decimal_to_json(Decimal("10.2300")) == "10.2300"
