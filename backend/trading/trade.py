from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TradeType = Literal["TREND", "REBOUND", "FIXED_TARGET", "CUSTOM"]
TradeStatus = Literal["PLANNED", "ACTIVE", "CLOSING", "CLOSED", "CANCELLED"]
TradePlanAction = Literal["OPEN", "ADD", "REDUCE", "CLOSE"]
TradePlanStatus = Literal["DRAFT", "READY", "ARMED", "PARTIALLY_EXECUTED", "EXECUTED", "CANCELLED", "EXPIRED", "INVALIDATED"]
EXIT_TRIGGER_TYPES = {"MANUAL_CONFIRMATION", "PRICE_ABOVE", "PRICE_BELOW", "PRICE_RANGE", "R_MULTIPLE", "DATE_TIME", "HOLDING_DAYS", "CUSTOM"}
EXIT_ACTION_TYPES = {"REDUCE_FIXED_QTY", "REDUCE_POSITION_PCT", "REDUCE_TO_TARGET_PCT", "CLOSE_ALL", "UPDATE_RISK_REFERENCE", "ALERT_ONLY"}
EXIT_EXECUTION_BEHAVIORS = {"ALERT_ONLY", "REQUIRE_CONFIRMATION"}


@dataclass(frozen=True)
class TradeInput:
    account_id: int
    symbol: str
    symbol_name: str
    trade_type: TradeType = "CUSTOM"
    playbook_id: str | None = None
    playbook_snapshot_json: dict | None = None
    thesis: str | None = None
    initial_reason: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class TradeLegInput:
    trade_id: int
    source_plan_id: int
    leg_type: Literal["OPEN", "ADD"]
    sequence_no: int
    entry_qty: int
    remaining_qty: int
    planned_entry_price: float
    actual_avg_entry_price: float | None = None
    initial_risk_reference_price: float | None = None
    current_risk_reference_price: float | None = None
    failure_handling: str | None = None


def validate_trade_input(item: TradeInput) -> None:
    if item.account_id <= 0:
        raise ValueError("account_id must be a positive integer")
    if not item.symbol.strip():
        raise ValueError("symbol is required")
    if not item.symbol_name.strip():
        raise ValueError("symbol_name is required")
    if item.trade_type not in {"TREND", "REBOUND", "FIXED_TARGET", "CUSTOM"}:
        raise ValueError("trade_type is invalid")


def validate_trade_plan_action(action_type: str, sequence_no: int) -> None:
    if action_type not in {"OPEN", "ADD", "REDUCE", "CLOSE"}:
        raise ValueError("action_type is invalid")
    if not isinstance(sequence_no, int) or sequence_no <= 0:
        raise ValueError("sequence_no must be a positive integer")


def validate_exit_rule(trigger_type: str, action_type: str, execution_behavior: str) -> None:
    if trigger_type not in EXIT_TRIGGER_TYPES:
        raise ValueError("trigger_type is invalid")
    if action_type not in EXIT_ACTION_TYPES:
        raise ValueError("action_type is invalid")
    if execution_behavior not in EXIT_EXECUTION_BEHAVIORS:
        raise ValueError("execution_behavior is invalid")
