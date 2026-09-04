from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    pass


class AccountMode(StrEnum):
    SIM = "SIM"
    LIVE = "LIVE"


class CommandType(StrEnum):
    ORDER_SUBMIT = "ORDER_SUBMIT"
    ORDER_CANCEL = "ORDER_CANCEL"
    SYNC_ALL = "SYNC_ALL"


class CommandStatus(StrEnum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    DISPATCHING = "DISPATCHING"
    ACKED = "ACKED"
    REJECTED = "REJECTED"
    FAILED_SAFE = "FAILED_SAFE"
    UNKNOWN = "UNKNOWN"


class OrderStatus(StrEnum):
    PENDING_SEND = "PENDING_SEND"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class Freshness(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
    UNKNOWN = "UNKNOWN"


class Origin(StrEnum):
    SYSTEM = "SYSTEM"
    EXTERNAL = "EXTERNAL"
