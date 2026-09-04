from __future__ import annotations

from typing import Any

from broker_node.gm_agent.event_writer import EventWriter


class ConnectionStateRecorder:
    def __init__(self, events: EventWriter):
        self.events = events

    def record(self, channel: str, status: str, raw: Any = None) -> int:
        if channel not in {"MARKET", "TRADE", "ACCOUNT"}:
            raise ValueError(f"unsupported connection channel: {channel}")
        if status not in {"CONNECTED", "DISCONNECTED", "UNKNOWN"}:
            raise ValueError(f"unsupported connection status: {status}")
        event_type = "ACCOUNT_STATUS_CHANGED" if channel == "ACCOUNT" else "BROKER_CONNECTION_CHANGED"
        return self.events.append(
            event_type,
            {"channel": channel, "status": status, "raw": raw},
            "CALLBACK",
        )

