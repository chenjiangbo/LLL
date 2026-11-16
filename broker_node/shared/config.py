from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class NodeConfig:
    raw: dict[str, Any]
    path: Path

    @classmethod
    def load(cls, path: Path) -> "NodeConfig":
        if not path.is_file():
            raise ConfigError(f"config file does not exist: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"invalid config file: {path}") from exc
        required = ("node_id", "broker_account_key", "account_mode", "gm", "api", "runtime", "sync", "safety")
        missing = [key for key in required if key not in raw]
        if missing:
            raise ConfigError(f"missing required config fields: {', '.join(missing)}")
        if raw["account_mode"] not in {"SIM", "LIVE"}:
            raise ConfigError("account_mode must be SIM or LIVE")
        strategy_id = raw["gm"].get("strategy_id")
        if not isinstance(strategy_id, str) or not strategy_id:
            raise ConfigError("gm.strategy_id is required")
        return cls(raw=raw, path=path)

    def live_orders_enabled(self) -> bool:
        safety = self.raw.get("safety")
        if not isinstance(safety, dict):
            raise ConfigError("safety must be an object")
        allowed = safety.get("allow_live_orders", False)
        if type(allowed) is not bool:
            raise ConfigError("safety.allow_live_orders must be a boolean")
        return self.raw["account_mode"] == "LIVE" and allowed
