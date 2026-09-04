from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from backend.trading.trade import validate_exit_rule


class TradePlanValidationError(ValueError):
    """Raised when a TradePlan cannot be calculated or persisted safely."""


@dataclass(frozen=True)
class TradePlanInput:
    symbol: str
    security_name: str
    reference_entry_price: float
    max_acceptable_entry_price: float
    risk_reference_price: float
    plan_risk_pct: float
    target_type: Literal["FIXED_TARGET", "TREND_FOLLOWING"] = "TREND_FOLLOWING"
    target_price: float | None = None
    expected_price: float | None = None
    manual_planned_qty: int | None = None
    current_price: float | None = None
    risk_reference_note: str | None = None
    thesis: str | None = None
    selection_source_type: Literal["MANUAL", "STRATEGY", "UNKNOWN"] = "MANUAL"
    selection_strategy: str | None = None
    selection_stage: str | None = None
    selection_snapshot_date: str | None = None
    trade_type: Literal["TREND", "REBOUND", "FIXED_TARGET", "CUSTOM"] = "CUSTOM"
    target_zone_lower: float | None = None
    target_zone_upper: float | None = None
    holding_period_days: int | None = None
    time_invalidation_condition: str | None = None
    playbook_id: str | None = None
    playbook_snapshot_json: dict[str, Any] | None = None
    action_type: Literal["OPEN", "ADD", "REDUCE", "CLOSE"] = "OPEN"
    sequence_no: int = 1
    trade_id: int | None = None
    reason_code: str | None = None
    reason_text: str | None = None
    action_risk_budget_pct: float | None = None
    action_risk_budget_amount: float | None = None
    failure_handling: str | None = None
    target_remaining_qty: int | None = None
    target_remaining_pct: float | None = None
    trigger_config_json: dict[str, Any] | None = None
    exit_config_json: dict[str, Any] | None = None
    account_id: int = 0


@dataclass(frozen=True)
class AccountRiskSettings:
    account_equity: float
    available_cash: float
    current_invested_amount: float
    default_risk_pct: float
    max_single_position_pct: float
    max_total_position_pct: float
    max_trade_risk_pct: float = 0.02


@dataclass(frozen=True)
class InstrumentInfo:
    quantity_step: int = 100


def _finite_positive(value: float | None, field: str) -> float:
    if value is None or not math.isfinite(value) or value <= 0:
        raise TradePlanValidationError(f"{field} must be a finite number greater than 0")
    return float(value)


def _finite_nonnegative(value: float | None, field: str) -> float:
    if value is None or not math.isfinite(value) or value < 0:
        raise TradePlanValidationError(f"{field} must be a finite number greater than or equal to 0")
    return float(value)


class TradePlanCalculator:
    """Pure TradePlan calculator. Percentages are decimal fractions, e.g. 0.008 = 0.8%."""

    @staticmethod
    def calculate(
        plan: TradePlanInput,
        account: AccountRiskSettings,
        instrument: InstrumentInfo = InstrumentInfo(),
    ) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        try:
            entry = _finite_positive(plan.reference_entry_price, "reference_entry_price")
            max_entry = _finite_positive(plan.max_acceptable_entry_price, "max_acceptable_entry_price")
            risk_reference = _finite_positive(plan.risk_reference_price, "risk_reference_price")
            equity = _finite_positive(account.account_equity, "account_equity")
            cash = _finite_nonnegative(account.available_cash, "available_cash")
            invested = _finite_nonnegative(account.current_invested_amount, "current_invested_amount")
            risk_pct = _finite_positive(plan.plan_risk_pct, "plan_risk_pct")
            max_trade_risk_pct = _finite_positive(account.max_trade_risk_pct, "max_trade_risk_pct")
            single_pct = _finite_positive(account.max_single_position_pct, "max_single_position_pct")
            total_pct = _finite_positive(account.max_total_position_pct, "max_total_position_pct")
        except TradePlanValidationError as exc:
            errors.append(str(exc))
            return {"blocking_errors": errors, "warnings": warnings}

        # 交易设置来自数据库时，金额字段可能是 Decimal。计算链路统一使用
        # float，避免在仓位、风险和情景测算中混用 Decimal 与 float。
        account = AccountRiskSettings(
            account_equity=equity,
            available_cash=cash,
            current_invested_amount=invested,
            default_risk_pct=float(account.default_risk_pct),
            max_single_position_pct=single_pct,
            max_total_position_pct=total_pct,
            max_trade_risk_pct=max_trade_risk_pct,
        )

        if max_entry < entry:
            errors.append("max_acceptable_entry_price must be greater than or equal to reference_entry_price")
        if risk_reference >= entry:
            errors.append("risk_reference_price must be lower than reference_entry_price for OPEN_LONG")
        if account.available_cash < 0:
            errors.append("available_cash cannot be negative")
        if risk_pct > max_trade_risk_pct:
            errors.append("plan_risk_pct exceeds max_trade_risk_pct")
        if plan.target_type not in ("FIXED_TARGET", "TREND_FOLLOWING"):
            errors.append("target_type must be FIXED_TARGET or TREND_FOLLOWING")
        if plan.target_type == "FIXED_TARGET":
            if plan.target_price is None or not math.isfinite(plan.target_price) or plan.target_price <= entry:
                errors.append("target_price must be greater than reference_entry_price for FIXED_TARGET")
            if plan.expected_price is not None:
                errors.append("expected_price must be empty for FIXED_TARGET")
        elif plan.target_price is not None:
            errors.append("target_price must be empty for TREND_FOLLOWING")
        elif plan.expected_price is None or not math.isfinite(plan.expected_price) or plan.expected_price <= entry:
            errors.append("expected_price must be greater than reference_entry_price for TREND_FOLLOWING")
        if plan.selection_source_type not in {"MANUAL", "STRATEGY", "UNKNOWN"}:
            errors.append("selection_source_type is invalid")
        if plan.trade_type not in {"TREND", "REBOUND", "FIXED_TARGET", "CUSTOM"}:
            errors.append("trade_type is invalid")
        if plan.trade_type == "REBOUND":
            if plan.target_zone_lower is None or not math.isfinite(plan.target_zone_lower) or plan.target_zone_lower <= entry:
                errors.append("target_zone_lower must be greater than reference_entry_price for REBOUND")
            if plan.target_zone_upper is None or not math.isfinite(plan.target_zone_upper) or plan.target_zone_upper <= entry:
                errors.append("target_zone_upper must be greater than reference_entry_price for REBOUND")
            if plan.target_zone_lower is not None and plan.target_zone_upper is not None and plan.target_zone_upper < plan.target_zone_lower:
                errors.append("target_zone_upper must be greater than or equal to target_zone_lower")
            if plan.holding_period_days is None or not isinstance(plan.holding_period_days, int) or plan.holding_period_days <= 0:
                errors.append("holding_period_days must be a positive integer for REBOUND")
            if not (plan.time_invalidation_condition or "").strip():
                errors.append("time_invalidation_condition is required for REBOUND")
        if plan.selection_source_type == "STRATEGY" and (not plan.selection_strategy or not plan.selection_stage or not plan.selection_snapshot_date):
            errors.append("strategy selection source is incomplete")
        if not isinstance(instrument.quantity_step, int) or instrument.quantity_step <= 0:
            errors.append("quantity_step must be a positive integer")

        unit_risk = entry - risk_reference
        price_risk_pct = unit_risk / entry if entry > 0 else None
        risk_budget_amount = equity * risk_pct
        max_single_amount = equity * single_pct
        max_total_amount = equity * total_pct
        remaining_total_capacity = max(0.0, max_total_amount - invested)

        if unit_risk <= 0:
            errors.append("unit risk must be greater than 0")
            return {"blocking_errors": errors, "warnings": warnings}

        qty_by_risk_raw = risk_budget_amount / unit_risk
        qty_by_single_raw = max_single_amount / entry
        qty_by_cash_raw = cash / entry
        qty_by_total_raw = remaining_total_capacity / entry
        raw_limits = {
            "RISK_BUDGET": qty_by_risk_raw,
            "SINGLE_POSITION_LIMIT": qty_by_single_raw,
            "CASH_LIMIT": qty_by_cash_raw,
            "TOTAL_POSITION_LIMIT": qty_by_total_raw,
        }
        limiting_factor = min(raw_limits, key=raw_limits.get)
        unrounded_recommended_qty = int(math.floor(raw_limits[limiting_factor]))
        recommended_qty = int(math.floor(unrounded_recommended_qty / instrument.quantity_step) * instrument.quantity_step)
        planned_qty = plan.manual_planned_qty if plan.manual_planned_qty is not None else recommended_qty
        if planned_qty is not None and (not isinstance(planned_qty, int) or planned_qty < 0):
            errors.append("manual_planned_qty must be a non-negative integer")
            planned_qty = 0
        if planned_qty and planned_qty % instrument.quantity_step != 0:
            errors.append(f"planned quantity must be a multiple of quantity_step ({instrument.quantity_step})")
        if recommended_qty <= 0:
            errors.append("recommended_qty must be greater than 0")
        if plan.manual_planned_qty is not None:
            if planned_qty > qty_by_risk_raw + 1e-9:
                errors.append("manual planned quantity exceeds risk budget")
            if planned_qty > qty_by_single_raw + 1e-9:
                errors.append("manual planned quantity exceeds single-position limit")
            if planned_qty > qty_by_cash_raw + 1e-9:
                errors.append("manual planned quantity exceeds available cash")
            if planned_qty > qty_by_total_raw + 1e-9:
                errors.append("manual planned quantity exceeds total-position limit")
            if planned_qty > recommended_qty:
                warnings.append(f"manual planned quantity is above system recommendation by {planned_qty - recommended_qty} shares")

        if plan.current_price is not None and math.isfinite(plan.current_price) and plan.current_price > max_entry:
            warnings.append("current price is above the maximum acceptable entry price")
        if risk_pct > account.default_risk_pct:
            warnings.append("plan risk is above the default risk level")
        target_reward_risk = None
        if plan.target_type == "FIXED_TARGET" and plan.target_price is not None and not errors:
            target_reward_risk = (plan.target_price - entry) / unit_risk
            if target_reward_risk < 1.5:
                warnings.append("fixed target reward-to-risk ratio is below 1.5R")
        expected_price = plan.expected_price if plan.target_type == "TREND_FOLLOWING" else None
        expected_reward_risk = (expected_price - entry) / unit_risk if expected_price is not None else None
        if price_risk_pct > 0.1:
            warnings.append("risk reference price is far from the reference entry price")

        planned_notional = planned_qty * entry
        planned_risk_amount = planned_qty * unit_risk
        target_profit_amount = None
        target_return_pct = None
        if plan.target_type == "FIXED_TARGET" and plan.target_price is not None:
            target_profit_amount = planned_qty * (plan.target_price - entry)
            target_return_pct = (plan.target_price - entry) / entry
        result = {
            "unit_risk": unit_risk,
            "price_risk_pct": price_risk_pct,
            "risk_budget_amount": risk_budget_amount,
            "qty_by_risk": int(math.floor(qty_by_risk_raw)),
            "qty_by_single_position": int(math.floor(qty_by_single_raw)),
            "qty_by_cash": int(math.floor(qty_by_cash_raw)),
            "qty_by_total_position": int(math.floor(qty_by_total_raw)),
            "unrounded_recommended_qty": unrounded_recommended_qty,
            "recommended_qty": recommended_qty,
            "planned_qty": planned_qty,
            "planned_notional": planned_notional,
            "planned_position_pct": planned_notional / equity,
            "post_trade_total_position_pct": (invested + planned_notional) / equity,
            "planned_risk_amount": planned_risk_amount,
            "planned_account_risk_pct": planned_risk_amount / equity,
            "r1_price": entry + unit_risk,
            "r2_price": entry + unit_risk * 2,
            "r3_price": entry + unit_risk * 3,
            "reward_risk_ratio": target_reward_risk,
            "target_profit_amount": target_profit_amount,
            "target_return_pct": target_return_pct,
            "expected_reward_r": expected_reward_risk,
            "expected_price": expected_price,
            "target_zone_lower": plan.target_zone_lower,
            "target_zone_upper": plan.target_zone_upper,
            "holding_period_days": plan.holding_period_days,
            "time_invalidation_condition": plan.time_invalidation_condition,
            "limiting_factor": limiting_factor,
            "max_price_scenario": TradePlanCalculator._scenario(plan, account, instrument, max_entry),
            "warnings": warnings,
            "blocking_errors": errors,
        }
        return result

    @staticmethod
    def _scenario(plan: TradePlanInput, account: AccountRiskSettings, instrument: InstrumentInfo, entry: float) -> dict[str, Any]:
        risk = entry - plan.risk_reference_price
        if risk <= 0:
            return {"entry_price": entry, "blocking_errors": ["maximum entry price does not leave positive unit risk"]}
        limits = {
            "RISK_BUDGET": account.account_equity * plan.plan_risk_pct / risk,
            "SINGLE_POSITION_LIMIT": account.account_equity * account.max_single_position_pct / entry,
            "CASH_LIMIT": account.available_cash / entry,
            "TOTAL_POSITION_LIMIT": max(0.0, account.account_equity * account.max_total_position_pct - account.current_invested_amount) / entry,
        }
        limiting = min(limits, key=limits.get)
        unrounded_qty = int(math.floor(limits[limiting]))
        qty = int(math.floor(unrounded_qty / instrument.quantity_step) * instrument.quantity_step)
        planned_notional = qty * entry
        planned_risk_amount = qty * risk
        return {
            "entry_price": entry,
            "unit_risk": risk,
            "unrounded_recommended_qty": unrounded_qty,
            "recommended_qty": qty,
            "planned_notional": planned_notional,
            "planned_risk_amount": planned_risk_amount,
            "planned_account_risk_pct": planned_risk_amount / account.account_equity,
            "planned_position_pct": planned_notional / account.account_equity,
            "post_trade_total_position_pct": (account.current_invested_amount + planned_notional) / account.account_equity,
            "limiting_factor": limiting,
        }


class TradePlanStore:
    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("database_url is required")
        self.database_url = database_url
        self.init_schema()

    def connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute("""
                create table if not exists trades (
                    id bigserial primary key,
                    account_id integer not null,
                    symbol text not null,
                    symbol_name text not null,
                    trade_type text not null check (trade_type in ('TREND','REBOUND','FIXED_TARGET','CUSTOM')),
                    playbook_id text,
                    playbook_snapshot_json jsonb,
                    status text not null default 'PLANNED' check (status in ('PLANNED','ACTIVE','CLOSING','CLOSED','CANCELLED')),
                    thesis text,
                    initial_reason text,
                    notes text,
                    opened_at timestamptz,
                    closed_at timestamptz,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now()
                )
            """)
            conn.execute("""
                create table if not exists trade_plan (
                    id bigserial primary key,
                    symbol text not null,
                    security_name text not null,
                    action text not null default 'OPEN_LONG',
                    status text not null default 'DRAFT',
                    input_json jsonb not null,
                    account_settings_json jsonb not null,
                    instrument_json jsonb not null,
                    calculation_snapshot_json jsonb,
                    validation_snapshot_json jsonb,
                    expires_at timestamptz,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now(),
                    confirmed_at timestamptz,
                    cancelled_at timestamptz
                )
            """)
            conn.execute("alter table trade_plan add column if not exists trade_id bigint references trades(id)")
            conn.execute("alter table trade_plan add column if not exists account_id integer")
            conn.execute("alter table trade_plan add column if not exists action_type text not null default 'OPEN'")
            conn.execute("alter table trade_plan add column if not exists sequence_no integer not null default 1")
            conn.execute("alter table trade_plan add column if not exists reason_code text")
            conn.execute("alter table trade_plan add column if not exists reason_text text")
            conn.execute("alter table trade_plan add column if not exists action_risk_budget_pct numeric")
            conn.execute("alter table trade_plan add column if not exists action_risk_budget_amount numeric")
            conn.execute("alter table trade_plan add column if not exists failure_handling text")
            conn.execute("alter table trade_plan add column if not exists target_remaining_qty integer")
            conn.execute("alter table trade_plan add column if not exists target_remaining_pct numeric")
            conn.execute("alter table trade_plan add column if not exists trigger_config_json jsonb")
            conn.execute("alter table trade_plan add column if not exists exit_config_json jsonb")
            conn.execute("alter table trades add column if not exists trade_risk_budget_pct numeric")
            conn.execute("alter table trades add column if not exists trade_risk_budget_amount numeric")
            conn.execute("update trade_plan set account_id = t.account_id from trades t where trade_plan.trade_id = t.id and trade_plan.account_id is null")
            conn.execute("""do $$ begin
                if not exists (select 1 from pg_constraint where conname='trade_plan_account_fk') then
                    alter table trade_plan add constraint trade_plan_account_fk foreign key (account_id) references trading_account(id) on delete restrict;
                end if;
                if not exists (select 1 from pg_constraint where conname='trades_account_fk') then
                    alter table trades add constraint trades_account_fk foreign key (account_id) references trading_account(id) on delete restrict;
                end if;
            end $$;""")
            conn.execute("""
                create table if not exists trade_leg (
                    id bigserial primary key,
                    trade_id bigint not null references trades(id),
                    source_plan_id bigint not null references trade_plan(id),
                    leg_type text not null check (leg_type in ('OPEN','ADD')),
                    sequence_no integer not null check (sequence_no > 0),
                    entry_qty integer not null check (entry_qty >= 0),
                    remaining_qty integer not null check (remaining_qty >= 0),
                    planned_entry_price numeric not null check (planned_entry_price > 0),
                    actual_avg_entry_price numeric check (actual_avg_entry_price is null or actual_avg_entry_price > 0),
                    initial_risk_reference_price numeric check (initial_risk_reference_price is null or initial_risk_reference_price > 0),
                    current_risk_reference_price numeric check (current_risk_reference_price is null or current_risk_reference_price > 0),
                    failure_handling text,
                    opened_at timestamptz,
                    closed_at timestamptz,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now(),
                    unique(source_plan_id)
                )
            """)
            conn.execute("create index if not exists idx_trades_account_status on trades(account_id, status, created_at desc)")
            conn.execute("create index if not exists idx_trade_plan_trade_sequence on trade_plan(trade_id, sequence_no)")
            conn.execute("create index if not exists idx_trade_leg_trade_sequence on trade_leg(trade_id, sequence_no)")
            conn.execute("""
                create table if not exists trade_position_state (
                    trade_id bigint primary key references trades(id), position_qty integer not null default 0,
                    available_qty integer not null default 0, avg_cost numeric, market_price numeric,
                    market_value numeric, current_capital_risk numeric not null default 0,
                    current_giveback_risk numeric not null default 0, position_risk_reference_price numeric,
                    position_risk_reference_note text, management_state text not null default 'MANUAL',
                    updated_at timestamptz not null default now()
                )
            """)
            conn.execute("""
                create table if not exists position_risk_history (
                    id bigserial primary key, trade_id bigint not null references trades(id),
                    leg_id bigint references trade_leg(id), old_price numeric, new_price numeric not null,
                    reason text not null, changed_at timestamptz not null default now()
                )
            """)
            conn.execute("create index if not exists idx_position_risk_history_trade on position_risk_history(trade_id, changed_at desc)")
            conn.execute("""
                create table if not exists exit_rule (
                    id bigserial primary key, trade_id bigint not null references trades(id),
                    source_plan_id bigint references trade_plan(id), rule_type text not null,
                    priority integer not null default 1, enabled boolean not null default true,
                    trigger_type text not null, trigger_config_json jsonb not null default '{}'::jsonb,
                    action_type text not null, action_config_json jsonb not null default '{}'::jsonb,
                    execution_behavior text not null default 'REQUIRE_CONFIRMATION', notes text,
                    created_at timestamptz not null default now(), updated_at timestamptz not null default now()
                )
            """)
            conn.execute("""
                do $$
                declare item record; new_trade_id bigint; input_data jsonb;
                begin
                    for item in select id, symbol, security_name, input_json from trade_plan where trade_id is null loop
                        input_data := coalesce(item.input_json, '{}'::jsonb);
                        insert into trades (account_id, symbol, symbol_name, trade_type, thesis, initial_reason)
                        values (coalesce((item.input_json->>'account_id')::integer, 1), item.symbol, item.security_name,
                                case when input_data->>'target_type' = 'FIXED_TARGET' then 'FIXED_TARGET' else 'CUSTOM' end,
                                input_data->>'thesis', input_data->>'thesis')
                        returning id into new_trade_id;
                        update trade_plan set trade_id = new_trade_id, action_type = 'OPEN', sequence_no = 1 where id = item.id;
                    end loop;
                end $$;
            """)
            conn.execute("update trade_plan set account_id=trades.account_id from trades where trade_plan.trade_id=trades.id and trade_plan.account_id is null")
            conn.execute("create index if not exists idx_trade_plan_status_created on trade_plan(status, created_at desc)")
            # 将已保存的趋势计划从旧的“预期收益 R”数据结构一次性迁移为
            # “预期价格”。历史记录不在读取时猜测字段，迁移后与新计划使用同一模型。
            conn.execute("""
                update trade_plan
                set input_json = (input_json - 'expected_reward_r') || jsonb_build_object(
                    'expected_price',
                    ((input_json->>'reference_entry_price')::numeric
                    + ((input_json->>'reference_entry_price')::numeric - (input_json->>'risk_reference_price')::numeric)
                    * (input_json->>'expected_reward_r')::numeric)
                )
                where input_json ? 'expected_reward_r'
                  and not (input_json ? 'expected_price')
                  and input_json->>'target_type' = 'TREND_FOLLOWING'
            """)
    def get_settings(self, account_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("""select a.equity as account_equity, a.available_cash,
                coalesce((select sum(quantity * market_price) from planning_position where account_id=a.id),0) as current_invested_amount,
                r.default_trade_risk_pct as default_risk_pct, r.max_single_position_pct,
                r.max_total_exposure_pct as max_total_position_pct, r.max_trade_risk_pct
                from trading_account a join risk_profile r on r.account_id=a.id where a.id=%s""", (account_id,)).fetchone()
        if not row:
            raise RuntimeError("trade_settings row is missing")
        return {key: float(value) for key, value in row.items()}

    def save_settings(self, account_id: int, settings: AccountRiskSettings) -> dict[str, Any]:
        _finite_positive(settings.account_equity, "account_equity")
        _finite_nonnegative(settings.available_cash, "available_cash")
        _finite_nonnegative(settings.current_invested_amount, "current_invested_amount")
        _finite_positive(settings.default_risk_pct, "default_risk_pct")
        _finite_positive(settings.max_single_position_pct, "max_single_position_pct")
        _finite_positive(settings.max_total_position_pct, "max_total_position_pct")
        with self.connect() as conn:
            conn.execute("update trading_account set equity=%s, available_cash=%s, cash=%s, updated_at=now() where id=%s", (settings.account_equity, settings.available_cash, settings.available_cash, account_id))
            conn.execute("""update risk_profile set default_trade_risk_pct=%s, max_trade_risk_pct=%s,
                max_single_position_pct=%s, max_total_exposure_pct=%s, configuration_confirmed=true, updated_at=now()
                where account_id=%s""", (settings.default_risk_pct, settings.max_trade_risk_pct, settings.max_single_position_pct, settings.max_total_position_pct, account_id))
            row = conn.execute("""select a.equity as account_equity, a.available_cash,
                coalesce((select sum(quantity * market_price) from planning_position where account_id=a.id),0) as current_invested_amount,
                r.default_trade_risk_pct as default_risk_pct, r.max_single_position_pct,
                r.max_total_exposure_pct as max_total_position_pct, r.max_trade_risk_pct
                from trading_account a join risk_profile r on r.account_id=a.id where a.id=%s""", (account_id,)).fetchone()
        if not row:
            raise RuntimeError("trade_settings row is missing")
        return {key: float(value) for key, value in row.items()}

    def create(self, plan: TradePlanInput, account: AccountRiskSettings, instrument: InstrumentInfo, calculation: dict[str, Any], expires_at: datetime | None = None) -> dict[str, Any]:
        if plan.action_type not in {"OPEN", "ADD", "REDUCE", "CLOSE"}:
            raise TradePlanValidationError("action_type is invalid")
        if not isinstance(plan.sequence_no, int) or plan.sequence_no <= 0:
            raise TradePlanValidationError("sequence_no must be a positive integer")
        if not isinstance(plan.account_id, int) or plan.account_id <= 0:
            raise TradePlanValidationError("account_id is required")
        with self.connect() as conn:
            trade_id = plan.trade_id
            if trade_id is None:
                trade_row = conn.execute("""
                    insert into trades (account_id, symbol, symbol_name, trade_type, playbook_id, playbook_snapshot_json, thesis, initial_reason, trade_risk_budget_pct, trade_risk_budget_amount)
                    values (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s) returning id
                """, (plan.account_id, plan.symbol, plan.security_name, plan.trade_type, plan.playbook_id, json.dumps(plan.playbook_snapshot_json), plan.thesis, plan.thesis,
                       plan.plan_risk_pct, plan.action_risk_budget_amount or account.account_equity * plan.plan_risk_pct)).fetchone()
                trade_id = int(trade_row["id"])
            elif not conn.execute("select 1 from trades where id=%s and account_id=%s", (trade_id, plan.account_id)).fetchone():
                raise TradePlanValidationError("Trade does not belong to account")
            row = conn.execute("""
                insert into trade_plan (account_id, trade_id, symbol, security_name, action_type, sequence_no, reason_code, reason_text,
                    action_risk_budget_pct, action_risk_budget_amount, failure_handling, target_remaining_qty, target_remaining_pct,
                    trigger_config_json, exit_config_json, input_json, account_settings_json, instrument_json,
                    calculation_snapshot_json, validation_snapshot_json, expires_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                returning *
            """, (plan.account_id, trade_id, plan.symbol, plan.security_name, plan.action_type, plan.sequence_no, plan.reason_code, plan.reason_text,
                   plan.action_risk_budget_pct, plan.action_risk_budget_amount, plan.failure_handling, plan.target_remaining_qty, plan.target_remaining_pct,
                   json.dumps(plan.trigger_config_json), json.dumps(plan.exit_config_json), json.dumps(asdict(plan)), json.dumps(asdict(account)),
                   json.dumps(asdict(instrument)), json.dumps(calculation), json.dumps({"warnings": calculation.get("warnings", []), "blocking_errors": calculation.get("blocking_errors", [])}), expires_at)).fetchone()
            conn.execute("update trades set updated_at = now() where id = %s", (trade_id,))
        return self._serialize(row)

    def create_action_plan(self, account_id: int, trade_id: int, action_type: str, symbol: str, security_name: str,
                           input_data: dict[str, Any], calculation: dict[str, Any],
                           reason_code: str | None = None, reason_text: str | None = None,
                           expires_at: datetime | None = None) -> dict[str, Any]:
        if action_type not in {"ADD", "REDUCE", "CLOSE"}:
            raise TradePlanValidationError("only ADD, REDUCE, or CLOSE can be created as a child action")
        if calculation.get("blocking_errors"):
            raise TradePlanValidationError("action plan has blocking errors")
        with self.connect() as conn:
            trade = conn.execute("select id, account_id, symbol, symbol_name, status from trades where id=%s and account_id=%s for update", (trade_id, account_id)).fetchone()
            if not trade:
                raise TradePlanValidationError("Trade not found")
            if trade["symbol"] != symbol:
                raise TradePlanValidationError("action plan symbol does not match Trade")
            if trade["status"] not in {"ACTIVE", "CLOSING"}:
                raise TradePlanValidationError("Trade is not active")
            sequence = conn.execute("select coalesce(max(sequence_no), 0) + 1 as next_sequence from trade_plan where trade_id=%s", (trade_id,)).fetchone()["next_sequence"]
            row = conn.execute("""
                insert into trade_plan (account_id, trade_id, symbol, security_name, action_type, sequence_no, reason_code, reason_text,
                    input_json, calculation_snapshot_json, validation_snapshot_json, expires_at)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s) returning *
            """, (account_id, trade_id, symbol, security_name, action_type, sequence, reason_code, reason_text,
                   json.dumps(input_data), json.dumps(calculation), json.dumps({"warnings": calculation.get("warnings", []), "blocking_errors": []}), expires_at)).fetchone()
            if action_type == "CLOSE":
                conn.execute("update trades set status='CLOSING', updated_at=now() where id=%s and status='ACTIVE'", (trade_id,))
        return self._serialize(row)

    def update_risk_reference(self, account_id: int, trade_id: int, new_price: float, reason: str, leg_id: int | None = None) -> dict[str, Any]:
        if not reason.strip():
            raise TradePlanValidationError("risk reference change reason is required")
        with self.connect() as conn:
            trade = conn.execute("select id from trades where id=%s and account_id=%s for update", (trade_id, account_id)).fetchone()
            if not trade:
                raise TradePlanValidationError("Trade not found")
            if leg_id is None:
                current = conn.execute("select position_risk_reference_price from trade_position_state where trade_id=%s", (trade_id,)).fetchone()
                old_price = current["position_risk_reference_price"] if current else None
                conn.execute("""
                    insert into trade_position_state (trade_id, position_risk_reference_price, position_risk_reference_note)
                    values (%s,%s,%s)
                    on conflict (trade_id) do update set position_risk_reference_price=excluded.position_risk_reference_price,
                        position_risk_reference_note=excluded.position_risk_reference_note, updated_at=now()
                """, (trade_id, new_price, reason))
            else:
                current = conn.execute("select current_risk_reference_price from trade_leg where id=%s and trade_id=%s for update", (leg_id, trade_id)).fetchone()
                if not current:
                    raise TradePlanValidationError("TradeLeg not found")
                old_price = current["current_risk_reference_price"]
                conn.execute("update trade_leg set current_risk_reference_price=%s, updated_at=now() where id=%s", (new_price, leg_id))
            row = conn.execute("""
                insert into position_risk_history (trade_id, leg_id, old_price, new_price, reason)
                values (%s,%s,%s,%s,%s) returning *
            """, (trade_id, leg_id, old_price, new_price, reason)).fetchone()
        return self._serialize(row)

    def create_exit_rule(self, account_id: int, trade_id: int, data: dict[str, Any]) -> dict[str, Any]:
        if any(not str(data.get(key) or "").strip() for key in ("rule_type", "trigger_type", "action_type")):
            raise TradePlanValidationError("退出规则类型、触发条件和动作不能为空")
        try:
            validate_exit_rule(str(data["trigger_type"]), str(data["action_type"]), str(data.get("execution_behavior", "REQUIRE_CONFIRMATION")))
        except ValueError as exc:
            raise TradePlanValidationError(str(exc)) from exc
        priority = int(data.get("priority", 1))
        if priority <= 0:
            raise TradePlanValidationError("priority must be a positive integer")
        with self.connect() as conn:
            if not conn.execute("select 1 from trades where id=%s and account_id=%s", (trade_id, account_id)).fetchone():
                raise TradePlanValidationError("Trade not found")
            row = conn.execute("""
                insert into exit_rule (trade_id, source_plan_id, rule_type, priority, enabled, trigger_type,
                    trigger_config_json, action_type, action_config_json, execution_behavior, notes)
                values (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s) returning *
            """, (trade_id, data.get("source_plan_id"), data["rule_type"], priority, bool(data.get("enabled", True)),
                   data["trigger_type"], json.dumps(data.get("trigger_config_json") or {}), data["action_type"],
                   json.dumps(data.get("action_config_json") or {}), data.get("execution_behavior", "REQUIRE_CONFIRMATION"), data.get("notes"))).fetchone()
        return self._serialize(row)

    def list_exit_rules(self, account_id: int, trade_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("""select e.* from exit_rule e join trades t on t.id=e.trade_id
                where e.trade_id=%s and t.account_id=%s order by e.priority, e.id""", (trade_id, account_id)).fetchall()
        return [self._serialize(row) for row in rows]

    def update_exit_rule(self, account_id: int, trade_id: int, rule_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        if "trigger_type" in data or "action_type" in data or "execution_behavior" in data:
            try:
                validate_exit_rule(str(data.get("trigger_type", "MANUAL_CONFIRMATION")), str(data.get("action_type", "ALERT_ONLY")), str(data.get("execution_behavior", "REQUIRE_CONFIRMATION")))
            except ValueError as exc:
                raise TradePlanValidationError(str(exc)) from exc
        with self.connect() as conn:
            row = conn.execute("""
                update exit_rule set priority=coalesce(%s, priority), enabled=coalesce(%s, enabled),
                    trigger_type=coalesce(%s, trigger_type), trigger_config_json=coalesce(%s::jsonb, trigger_config_json),
                    action_type=coalesce(%s, action_type), action_config_json=coalesce(%s::jsonb, action_config_json),
                    execution_behavior=coalesce(%s, execution_behavior), notes=coalesce(%s, notes), updated_at=now()
                where id=%s and trade_id=%s and exists (select 1 from trades t where t.id=exit_rule.trade_id and t.account_id=%s) returning *
            """, (data.get("priority"), data.get("enabled"), data.get("trigger_type"), json.dumps(data["trigger_config_json"]) if "trigger_config_json" in data else None,
                   data.get("action_type"), json.dumps(data["action_config_json"]) if "action_config_json" in data else None, data.get("execution_behavior"), data.get("notes"), rule_id, trade_id, account_id)).fetchone()
        return self._serialize(row) if row else None

    def delete_exit_rule(self, account_id: int, trade_id: int, rule_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute("""delete from exit_rule where id=%s and trade_id=%s
                and exists (select 1 from trades t where t.id=exit_rule.trade_id and t.account_id=%s) returning id""", (rule_id, trade_id, account_id)).fetchone()
        return bool(row)

    def get_trade_position_state(self, account_id: int, trade_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("""select s.* from trade_position_state s join trades t on t.id=s.trade_id
                where s.trade_id=%s and t.account_id=%s""", (trade_id, account_id)).fetchone()
        return self._serialize(row)

    def list_risk_reference_history(self, account_id: int, trade_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("""select h.* from position_risk_history h join trades t on t.id=h.trade_id
                where h.trade_id=%s and t.account_id=%s order by h.changed_at desc""", (trade_id, account_id)).fetchall()
        return [self._serialize(row) for row in rows]

    def list_trades(self, account_id: int, status: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if status:
                rows = conn.execute("select * from trades where account_id=%s and status = %s order by created_at desc", (account_id, status)).fetchall()
            else:
                rows = conn.execute("select * from trades where account_id=%s order by created_at desc", (account_id,)).fetchall()
            for row in rows:
                plans = conn.execute("select * from trade_plan where trade_id = %s order by sequence_no, created_at", (row["id"],)).fetchall()
                row["plans"] = [self._with_execution_data(conn, plan) for plan in plans]
                legs = conn.execute("select * from trade_leg where trade_id = %s order by sequence_no, created_at", (row["id"],)).fetchall()
                row["legs"] = [self._serialize(leg) for leg in legs]
        return [self._serialize(row) for row in rows]

    def get_trade(self, account_id: int, trade_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("select * from trades where id = %s and account_id=%s", (trade_id, account_id)).fetchone()
            if not row:
                return None
            plans = conn.execute("select * from trade_plan where trade_id = %s order by sequence_no, created_at", (trade_id,)).fetchall()
            row["plans"] = [self._with_execution_data(conn, plan) for plan in plans]
            legs = conn.execute("select * from trade_leg where trade_id = %s order by sequence_no, created_at", (trade_id,)).fetchall()
            row["legs"] = [self._serialize(leg) for leg in legs]
        return self._serialize(row)

    def list_trade_legs(self, account_id: int, trade_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("""select l.* from trade_leg l join trades t on t.id=l.trade_id
                where l.trade_id = %s and t.account_id=%s order by l.sequence_no, l.created_at""", (trade_id, account_id)).fetchall()
        return [self._serialize(row) for row in rows]

    @classmethod
    def _with_execution_data(cls, conn: Any, plan: dict[str, Any]) -> dict[str, Any]:
        result = cls._serialize(plan)
        executions = conn.execute("select * from execution_plan where trade_plan_id = %s order by created_at", (plan["id"],)).fetchall()
        result["execution_plans"] = []
        for execution in executions:
            execution_item = cls._serialize(execution)
            orders = conn.execute("select * from trading_order where execution_plan_id = %s order by created_at", (execution["id"],)).fetchall()
            execution_item["orders"] = []
            for order in orders:
                order_item = cls._serialize(order)
                fills = conn.execute("select * from trading_fill where order_id = %s order by filled_at", (order["id"],)).fetchall()
                order_item["fills"] = [cls._serialize(fill) for fill in fills]
                execution_item["orders"].append(order_item)
            result["execution_plans"].append(execution_item)
        return result

    def list(self, account_id: int, status: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if status:
                rows = conn.execute("select * from trade_plan where account_id=%s and status = %s order by created_at desc", (account_id, status)).fetchall()
            else:
                rows = conn.execute("select * from trade_plan where account_id=%s order by created_at desc", (account_id,)).fetchall()
        return [self._serialize(row) for row in rows]

    def get(self, account_id: int, plan_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("select * from trade_plan where id = %s and account_id=%s", (plan_id, account_id)).fetchone()
        return self._serialize(row) if row else None

    def update_draft(self, plan_id: int, plan: TradePlanInput, account: AccountRiskSettings, instrument: InstrumentInfo, calculation: dict[str, Any]) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("""
                update trade_plan set symbol=%s, security_name=%s, action_type=%s, sequence_no=%s,
                    reason_code=%s, reason_text=%s, action_risk_budget_pct=%s, action_risk_budget_amount=%s,
                    failure_handling=%s, target_remaining_qty=%s, target_remaining_pct=%s,
                    trigger_config_json=%s::jsonb, exit_config_json=%s::jsonb, input_json=%s::jsonb,
                    account_settings_json=%s::jsonb, instrument_json=%s::jsonb,
                    calculation_snapshot_json=%s::jsonb, validation_snapshot_json=%s::jsonb, updated_at=now()
                where id=%s and status='DRAFT' returning *
            """, (plan.symbol, plan.security_name, plan.action_type, plan.sequence_no, plan.reason_code, plan.reason_text,
                   plan.action_risk_budget_pct, plan.action_risk_budget_amount, plan.failure_handling, plan.target_remaining_qty, plan.target_remaining_pct,
                   json.dumps(plan.trigger_config_json), json.dumps(plan.exit_config_json), json.dumps(asdict(plan)), json.dumps(asdict(account)),
                   json.dumps(asdict(instrument)), json.dumps(calculation), json.dumps({"warnings": calculation.get("warnings", []), "blocking_errors": calculation.get("blocking_errors", [])}), plan_id)).fetchone()
        return self._serialize(row) if row else None

    def delete_draft(self, plan_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute("delete from trade_plan where id=%s and status='DRAFT' returning id", (plan_id,)).fetchone()
        return bool(row)

    def update_status(self, account_id: int, plan_id: int, status: str, calculation: dict[str, Any] | None = None) -> dict[str, Any] | None:
        allowed_transitions = {
            "DRAFT": {"READY", "CANCELLED", "EXPIRED", "INVALIDATED"},
            "READY": {"ARMED", "PARTIALLY_EXECUTED", "EXECUTED", "CANCELLED", "EXPIRED", "INVALIDATED"},
            "ARMED": {"PARTIALLY_EXECUTED", "EXECUTED", "CANCELLED", "EXPIRED", "INVALIDATED"},
            "PARTIALLY_EXECUTED": {"ARMED", "EXECUTED", "CANCELLED", "EXPIRED", "INVALIDATED"},
            "EXECUTED": set(), "CANCELLED": set(), "EXPIRED": set(), "INVALIDATED": set(),
        }
        if status not in allowed_transitions:
            raise TradePlanValidationError("unsupported TradePlan status")
        if status == "READY" and (not calculation or calculation.get("blocking_errors")):
            raise TradePlanValidationError("TradePlan cannot enter READY with blocking errors")
        now = datetime.now(UTC)
        with self.connect() as conn:
            current = conn.execute("select status from trade_plan where id=%s and account_id=%s for update", (plan_id, account_id)).fetchone()
            if not current:
                return None
            if status not in allowed_transitions.get(current["status"], set()):
                raise TradePlanValidationError(f"TradePlan cannot transition from {current['status']} to {status}")
            row = conn.execute("""
                update trade_plan set status = %s, updated_at = %s,
                    confirmed_at = case when %s = 'READY' then %s else confirmed_at end,
                    cancelled_at = case when %s = 'CANCELLED' then %s else cancelled_at end,
                    calculation_snapshot_json = case when %s::jsonb is not null then %s::jsonb else calculation_snapshot_json end,
                    validation_snapshot_json = case when %s::jsonb is not null then %s::jsonb else validation_snapshot_json end
                where id = %s and account_id = %s and status not in ('CANCELLED', 'EXPIRED')
                returning *
            """, (status, now, status, now, status, now, json.dumps(calculation) if calculation else None, json.dumps(calculation) if calculation else None, json.dumps(calculation) if calculation else None, json.dumps(calculation) if calculation else None, plan_id, account_id)).fetchone()
        return self._serialize(row) if row else None

    @staticmethod
    def _serialize(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in ("created_at", "updated_at", "expires_at", "confirmed_at", "cancelled_at"):
            if hasattr(result.get(key), "isoformat"):
                result[key] = result[key].isoformat()
            elif isinstance(result.get(key), Decimal):
                result[key] = float(result[key])
        for key, value in list(result.items()):
            if isinstance(value, Decimal):
                result[key] = float(value)
        return result
