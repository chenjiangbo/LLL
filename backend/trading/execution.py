from __future__ import annotations

import json
import hashlib
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time as dtime
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from .account import normalize_symbol
from .order_types import canonical_order_type, validate_order_price


_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def execution_submission_window_open(account: dict[str, Any], calendar: Any, now: datetime | None = None) -> bool:
    """Return whether the configured account schedule permits an order attempt."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    local_now = current.astimezone(_SHANGHAI_TZ)
    current_time = local_now.time().replace(tzinfo=None)

    def configured_time(field: str) -> dtime:
        raw_value = account.get(field)
        try:
            value = raw_value if isinstance(raw_value, dtime) else dtime.fromisoformat(str(raw_value))
        except (TypeError, ValueError) as exc:
            raise ExecutionValidationError(f"交易账号缺少有效执行时段配置：{field}") from exc
        if value.second or value.microsecond:
            raise ExecutionValidationError(f"执行时段配置必须精确到分钟：{field}")
        return value

    morning_start = configured_time("morning_session_start")
    morning_end = configured_time("morning_session_end")
    afternoon_start = configured_time("afternoon_session_start")
    afternoon_end = configured_time("afternoon_session_end")
    next_day_start = configured_time("next_day_submission_start")
    if not morning_start < morning_end:
        raise ExecutionValidationError("上午交易时段结束时间必须晚于开始时间")
    if not morning_end <= afternoon_start:
        raise ExecutionValidationError("下午交易时段不能早于上午交易时段结束")
    if not afternoon_start < afternoon_end:
        raise ExecutionValidationError("下午交易时段结束时间必须晚于开始时间")
    if not afternoon_end < next_day_start:
        raise ExecutionValidationError("次日委托开始时间必须晚于下午交易时段结束")
    in_session = calendar.is_open(local_now.date()) and (
        morning_start <= current_time < morning_end
        or afternoon_start <= current_time < afternoon_end
    )
    if in_session:
        return True

    # The pre-session order window begins on the prior open day at the
    # configured time and remains open through weekends/holidays until the
    # next actual exchange session starts.
    previous_open = calendar.previous_open_date(local_now.date())
    next_open = calendar.next_open_date(local_now.date(), inclusive=True)
    window_start = datetime.combine(previous_open, next_day_start, tzinfo=_SHANGHAI_TZ)
    next_session_start = datetime.combine(next_open, morning_start, tzinfo=_SHANGHAI_TZ)
    if window_start <= local_now < next_session_start:
        return True

    if current_time >= next_day_start:
        # Today's 23:00 window starts even when the following session is
        # several calendar days away, as happens before weekends/holidays.
        calendar.next_open_date(local_now.date(), inclusive=False)
        return True
    return False


def automatic_next_day_submission_open(now: datetime | None = None) -> bool:
    """Legacy helper retained for callers that used the former 23:00 cutoff."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(_SHANGHAI_TZ).time() >= dtime(23, 0)


class ExecutionValidationError(ValueError):
    """Raised when an execution instruction is invalid."""


def execution_plan_start_reached(execution_plan: dict[str, Any], now: datetime | None = None) -> bool:
    """Return whether an optional scheduled start time has arrived."""
    raw_start = execution_plan.get("valid_from")
    if not raw_start:
        return True
    start = raw_start if isinstance(raw_start, datetime) else datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ExecutionValidationError("执行开始时间必须包含时区")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC) >= start.astimezone(UTC)


@dataclass(frozen=True)
class ExecutionPlanInput:
    trade_plan_id: int
    symbol: str
    side: Literal["BUY", "SELL"]
    target_qty: int
    execution_type: Literal["LIMIT", "PERSISTENT_LIMIT", "PRICE_TRIGGER", "PRICE_RANGE"]
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    execution_params: dict[str, Any] | None = None
    client_request_id: str | None = None
    account_id: int = 0


@dataclass(frozen=True)
class OrderInput:
    execution_plan_id: int
    symbol: str
    side: Literal["BUY", "SELL"]
    order_type: str
    quantity: int
    price: float | None = None
    account_id: int = 0


@dataclass(frozen=True)
class PreTradeRiskResult:
    status: Literal["PASS", "WARNING", "BLOCK"]
    checks: list[dict[str, Any]]


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ExecutionValidationError(f"{field} must be a positive integer")
    return value


def _positive_number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionValidationError(f"{field} must be a number") from exc
    if not math.isfinite(result) or result <= 0:
        raise ExecutionValidationError(f"{field} must be finite and greater than 0")
    return result


class PreTradeRisk:
    """Deterministic checks executed immediately before an order is submitted."""

    @staticmethod
    def check(
        account: dict[str, Any],
        risk_profile: dict[str, Any],
        execution_plan: dict[str, Any],
        order: OrderInput,
        positions: list[dict[str, Any]],
        active_orders: list[dict[str, Any]],
        now: datetime | None = None,
    ) -> PreTradeRiskResult:
        checks: list[dict[str, Any]] = []
        blocking = False
        current_time = now or datetime.now(UTC)

        def check(name: str, passed: bool, level: str, message: str) -> None:
            nonlocal blocking
            checks.append({"name": name, "status": level if not passed else "PASS", "message": message})
            if not passed and level == "BLOCK":
                blocking = True

        check("account_configuration", bool(account.get("configuration_confirmed")) and bool(risk_profile.get("configuration_confirmed")), "BLOCK", "交易账户或风险规则尚未完成配置")
        check("account_status", account.get("status") == "ACTIVE", "BLOCK", "账户当前不可交易")
        check("execution_status", execution_plan.get("status") == "ACTIVE", "BLOCK", "执行计划不是活动状态")
        valid_until = execution_plan.get("valid_until")
        if valid_until:
            expiry = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
            check("validity", current_time <= expiry, "BLOCK", "执行计划已超过有效期")
        check("remaining_quantity", int(execution_plan.get("remaining_qty", 0)) >= order.quantity, "BLOCK", "委托数量超过执行计划剩余数量")
        check("quantity", order.quantity > 0, "BLOCK", "委托数量必须大于零")
        check("quantity_step", order.quantity % 100 == 0, "BLOCK", "A股委托数量必须为 100 股的整数倍")
        max_quantity = risk_profile.get("max_single_order_quantity")
        if max_quantity is not None:
            check("max_single_order_quantity", order.quantity <= int(max_quantity), "BLOCK", "委托数量超过单笔最大数量")
        if order.side == "BUY":
            if order.price is not None:
                required_cash = order.price * order.quantity
                check("available_cash", float(account.get("available_cash", 0)) >= required_cash, "BLOCK", "可用现金不足")
            else:
                checks.append({"name": "available_cash", "status": "WARNING", "message": "市价类委托需要券商返回最终资金校验"})
        order_symbol = normalize_symbol(order.symbol)
        symbol_orders = [
            item for item in active_orders
            if normalize_symbol(item.get("symbol")) == order_symbol
            and item.get("status") not in {"CANCELLED", "FILLED", "REJECTED", "EXPIRED"}
        ]
        check("duplicate_order", not symbol_orders, "BLOCK", "该证券已有未完成委托")
        equity = float(account.get("equity", 0))
        if order.side == "BUY" and order.price is not None and equity > 0:
            current_value = sum(
                float(item.get("market_value", 0))
                for item in positions
                if normalize_symbol(item.get("symbol")) == order_symbol
            )
            new_position_pct = (current_value + order.price * order.quantity) / equity
            check("single_position_limit", new_position_pct <= float(risk_profile["max_single_position_pct"]), "BLOCK", "预计单股仓位超过上限")
            market_value = sum(float(item.get("market_value", 0)) for item in positions)
            total_pct = (market_value + order.price * order.quantity) / equity
            if total_pct > float(risk_profile["max_total_exposure_pct"]):
                check("total_exposure_limit", False, "BLOCK", "预计总仓位超过上限")
            else:
                check("total_exposure_limit", True, "BLOCK", "预计总仓位在上限内")
        return PreTradeRiskResult("BLOCK" if blocking else ("WARNING" if any(item["status"] == "WARNING" for item in checks) else "PASS"), checks)


class ExecutionStore:
    TERMINAL_ORDER_STATUSES = frozenset({"CANCELLED", "REJECTED", "EXPIRED"})
    ORDER_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
        "PENDING_SUBMIT": frozenset({"PENDING_SUBMIT", "SUBMITTED", "ACCEPTED", "REJECTED", "UNKNOWN"}),
        "SUBMITTED": frozenset({"SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "REJECTED", "EXPIRED", "UNKNOWN"}),
        "ACCEPTED": frozenset({"ACCEPTED", "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "REJECTED", "EXPIRED", "UNKNOWN"}),
        "PARTIALLY_FILLED": frozenset({"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "EXPIRED", "UNKNOWN"}),
        "CANCEL_PENDING": frozenset({"CANCEL_PENDING", "CANCELLED", "PARTIALLY_FILLED", "FILLED", "UNKNOWN"}),
        "UNKNOWN": frozenset({"UNKNOWN", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "REJECTED", "EXPIRED"}),
        "FILLED": frozenset({"FILLED"}),
        "CANCELLED": frozenset({"CANCELLED"}),
        "REJECTED": frozenset({"REJECTED"}),
        "EXPIRED": frozenset({"EXPIRED"}),
    }

    @classmethod
    def is_order_status_transition_allowed(cls, current_status: str, next_status: str) -> bool:
        """Return whether a broker update may advance the local order state.

        Terminal states are deliberately absorbing.  Replayed or stale broker
        snapshots therefore cannot reopen a filled, cancelled, rejected, or
        expired order.
        """
        return next_status in cls.ORDER_STATUS_TRANSITIONS.get(current_status, frozenset())

    @classmethod
    def should_pause_plan_for_order_transition(cls, current_status: str, next_status: str) -> bool:
        """Pause only when an order first enters a non-fill terminal state."""
        return next_status in cls.TERMINAL_ORDER_STATUSES and current_status != next_status

    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("database_url is required")
        self.database_url = database_url
        self.init_schema()

    def connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _serialize(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if not row:
            return None
        result = dict(row)
        for key, value in result.items():
            if hasattr(value, "isoformat"):
                result[key] = value.isoformat()
            elif isinstance(value, bool):
                result[key] = value
            elif isinstance(value, Decimal):
                result[key] = float(value)
            elif isinstance(value, (int, float)) and key not in {"id", "trade_plan_id", "account_id", "execution_plan_id", "quantity", "target_qty", "filled_qty", "remaining_qty"}:
                result[key] = float(value)
        return result

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute("""
                create table if not exists execution_plan (
                    id bigserial primary key, account_id integer not null,
                    trade_plan_id bigint not null references trade_plan(id), symbol text not null,
                    side text not null check (side in ('BUY','SELL')), target_qty integer not null check (target_qty > 0),
                    filled_qty integer not null default 0 check (filled_qty >= 0), remaining_qty integer not null check (remaining_qty >= 0),
                    execution_type text not null check (execution_type in ('LIMIT','PERSISTENT_LIMIT','PRICE_TRIGGER','PRICE_RANGE')),
                    status text not null default 'DRAFT' check (status in ('DRAFT','ACTIVE','PAUSED','COMPLETED','CANCELLED','EXPIRED')),
                    valid_from timestamptz, valid_until timestamptz, execution_params_json jsonb not null default '{}'::jsonb,
                    status_reason text, status_source text,
                    client_request_id text,
                    created_at timestamptz not null default now(), updated_at timestamptz not null default now()
                )
            """)
            conn.execute("create index if not exists idx_execution_plan_status on execution_plan(status, created_at desc)")
            conn.execute("alter table execution_plan add column if not exists account_id integer")
            conn.execute("alter table execution_plan add column if not exists status_reason text")
            conn.execute("alter table execution_plan add column if not exists status_source text")
            conn.execute("alter table execution_plan add column if not exists client_request_id text")
            conn.execute("create unique index if not exists execution_plan_client_request_idx on execution_plan(account_id, client_request_id) where client_request_id is not null")
            conn.execute("alter table execution_plan alter column account_id drop default")
            conn.execute("update execution_plan set account_id=t.account_id from trade_plan p join trades t on t.id=p.trade_id where execution_plan.trade_plan_id=p.id and execution_plan.account_id is null")
            conn.execute("alter table execution_plan alter column account_id set not null")
            conn.execute("""do $$ begin
                if not exists (select 1 from pg_constraint where conname='execution_plan_account_fk') then
                    alter table execution_plan add constraint execution_plan_account_fk foreign key (account_id) references trading_account(id) on delete restrict;
                end if;
            end $$;""")
            conn.execute("""
                create table if not exists trading_order (
                    id bigserial primary key, account_id integer not null, execution_plan_id bigint not null references execution_plan(id),
                    client_order_id text not null unique, broker_order_id text, symbol text not null, side text not null check (side in ('BUY','SELL')),
                    order_type text not null, price numeric, quantity integer not null check (quantity > 0), filled_quantity integer not null default 0,
                    status text not null default 'PENDING_SUBMIT', reject_code text, reject_message text, raw_broker_data jsonb,
                    submitted_at timestamptz, accepted_at timestamptz, completed_at timestamptz, created_at timestamptz not null default now()
                )
            """)
            conn.execute("alter table trading_order add column if not exists account_id integer")
            conn.execute("alter table trading_order alter column account_id drop default")
            conn.execute("update trading_order set account_id=ep.account_id from execution_plan ep where trading_order.execution_plan_id=ep.id and trading_order.account_id is null")
            conn.execute("alter table trading_order alter column account_id set not null")
            conn.execute("""do $$ begin
                if not exists (select 1 from pg_constraint where conname='trading_order_account_fk') then
                    alter table trading_order add constraint trading_order_account_fk foreign key (account_id) references trading_account(id) on delete restrict;
                end if;
            end $$;""")
            conn.execute("create index if not exists idx_trading_order_status on trading_order(status, created_at desc)")
            conn.execute("""
                create table if not exists trading_fill (
                    id bigserial primary key, order_id bigint not null references trading_order(id), broker_fill_id text,
                    symbol text not null, price numeric not null, quantity integer not null check (quantity > 0),
                    commission numeric not null default 0, tax numeric not null default 0, other_fee numeric not null default 0,
                    filled_at timestamptz not null, raw_broker_data jsonb, unique(order_id, broker_fill_id)
                )
            """)
            conn.execute("alter table trading_fill add column if not exists account_id integer")
            conn.execute("update trading_fill set account_id=o.account_id from trading_order o where trading_fill.order_id=o.id and trading_fill.account_id is null")
            conn.execute("alter table trading_fill alter column account_id set not null")
            conn.execute("""do $$ begin
                if not exists (select 1 from pg_constraint where conname='trading_fill_account_fk') then
                    alter table trading_fill add constraint trading_fill_account_fk foreign key (account_id) references trading_account(id) on delete restrict;
                end if;
            end $$;""")
            conn.execute("""
                create table if not exists trading_control (
                    id integer, execution_paused boolean not null default false,
                    reason text, updated_at timestamptz not null default now(), account_id integer
                )
            """)
            conn.execute("alter table trading_control drop constraint if exists trading_control_id_check")
            conn.execute("alter table trading_control add column if not exists account_id integer")
            conn.execute("update trading_control set account_id=id where account_id is null")
            conn.execute("alter table trading_control alter column account_id set not null")
            conn.execute("alter table trading_control drop constraint if exists trading_control_pkey")
            conn.execute("alter table trading_control add constraint trading_control_pkey primary key (account_id)")
            conn.execute("""do $$ begin
                if not exists (select 1 from pg_constraint where conname='trading_control_account_fk') then
                    alter table trading_control add constraint trading_control_account_fk foreign key (account_id) references trading_account(id) on delete cascade;
                end if;
            end $$;""")
            conn.execute("insert into trading_control(id, account_id) select id, id from trading_account on conflict(account_id) do nothing")
            conn.execute("""
                create table if not exists reconciliation_issue (
                    id bigserial primary key, account_id integer not null, issue_type text not null,
                    symbol text, local_value jsonb, broker_value jsonb, status text not null default 'OPEN',
                    detected_at timestamptz not null default now(), resolved_at timestamptz
                )
            """)
            conn.execute("alter table reconciliation_issue alter column account_id drop default")
            conn.execute("alter table reconciliation_issue add column if not exists fingerprint text")
            conn.execute("create unique index if not exists reconciliation_issue_open_fingerprint_idx on reconciliation_issue(account_id, issue_type, fingerprint) where status='OPEN' and fingerprint is not null")
            conn.execute("""
                create table if not exists broker_event_cursor (
                    account_id integer primary key references trading_account(id) on delete cascade,
                    last_consumed_event_seq bigint not null default 0,
                    updated_at timestamptz not null default now()
                )
            """)
            conn.execute("insert into broker_event_cursor(account_id) select id from trading_account on conflict(account_id) do nothing")

    def create_execution_plan(self, item: ExecutionPlanInput) -> dict[str, Any]:
        _positive_int(item.trade_plan_id, "trade_plan_id")
        _positive_int(item.target_qty, "target_qty")
        _positive_int(item.account_id, "account_id")
        if item.side not in {"BUY", "SELL"} or item.execution_type not in {"LIMIT", "PERSISTENT_LIMIT", "PRICE_TRIGGER", "PRICE_RANGE"}:
            raise ExecutionValidationError("execution plan type or side is invalid")
        params = item.execution_params or {}
        order_type = canonical_order_type(params.get("order_type"))
        params["order_type"] = order_type
        exchange = normalize_symbol(item.symbol).split(":", 1)[0]
        price_key = "limit_price" if order_type == "LIMIT" else "protection_price"
        order_price = validate_order_price(exchange, order_type, params.get(price_key))
        if order_price is not None:
            params[price_key] = order_price
        if item.execution_type == "PERSISTENT_LIMIT" and order_type != "LIMIT":
            raise ExecutionValidationError("持续限价执行方式只能使用普通限价委托")
        if item.execution_type == "PRICE_TRIGGER":
            _positive_number(params.get("trigger_price"), "trigger_price")
        if item.execution_type == "PRICE_RANGE":
            low = _positive_number(params.get("low_price"), "low_price")
            high = _positive_number(params.get("high_price"), "high_price")
            if low > high:
                raise ExecutionValidationError("low_price cannot exceed high_price")
        with self.connect() as conn:
            if item.client_request_id:
                conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"execution-plan:{item.account_id}:{item.client_request_id}",))
                existing = conn.execute("select * from execution_plan where account_id=%s and client_request_id=%s", (item.account_id, str(item.client_request_id))).fetchone()
                if existing:
                    return self._serialize(existing)
            trade_plan = conn.execute("""
                select id, status, calculation_snapshot_json
                from trade_plan where id=%s and account_id=%s for update
            """, (item.trade_plan_id, item.account_id)).fetchone()
            if not trade_plan:
                raise ExecutionValidationError("TradePlan does not belong to account or does not exist")
            if trade_plan["status"] not in {"READY", "ARMED", "PARTIALLY_EXECUTED"}:
                raise ExecutionValidationError("只能为已确认的动作计划安排执行")
            prior_executions = conn.execute("""
                select ep.status,
                       coalesce(bool_or(coalesce(o.filled_quantity, 0) > 0), false) as has_fills,
                       coalesce(bool_or(o.status not in ('CANCELLED','CANCELED','CANCELLED_ORDER','REJECTED','FAILED','EXPIRED')), false) as has_live_order
                from execution_plan ep
                left join trading_order o on o.execution_plan_id=ep.id
                where ep.trade_plan_id=%s
                group by ep.id, ep.status
            """, (item.trade_plan_id,)).fetchall()
            if any(
                str(row["status"]) not in {"CANCELLED", "EXPIRED"}
                or bool(row["has_live_order"])
                for row in prior_executions
            ):
                raise ExecutionValidationError("这条动作仍有未结束的执行安排或委托")
            total_planned_qty = int((trade_plan["calculation_snapshot_json"] or {}).get("planned_qty") or 0)
            filled_before = conn.execute(
                "select coalesce(sum(filled_qty), 0) as quantity from execution_plan where trade_plan_id=%s",
                (item.trade_plan_id,),
            ).fetchone()
            remaining_action_qty = total_planned_qty - int(filled_before["quantity"] or 0)
            if remaining_action_qty <= 0:
                raise ExecutionValidationError("这项动作计划的数量已全部成交，不能再次安排执行")
            if item.target_qty != remaining_action_qty:
                raise ExecutionValidationError(f"再次执行只能安排剩余数量 {remaining_action_qty} 股")
            row = conn.execute("""
                insert into execution_plan (account_id, trade_plan_id, symbol, side, target_qty, remaining_qty, execution_type, valid_from, valid_until, execution_params_json, client_request_id)
                select %s,%s,tp.symbol,%s,%s,%s,%s,%s,%s,%s::jsonb,%s from trade_plan tp
                where tp.id=%s and tp.account_id=%s returning *
            """, (item.account_id, item.trade_plan_id, item.side, item.target_qty, item.target_qty, item.execution_type, item.valid_from, item.valid_until, json.dumps(params), item.client_request_id, item.trade_plan_id, item.account_id)).fetchone()
            if not row:
                raise ExecutionValidationError("TradePlan does not belong to account or does not exist")
        return self._serialize(row)

    def list_execution_plans(self, account_id: int, status: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("select * from execution_plan where account_id=%s and (%s::text is null or status=%s) order by created_at desc", (account_id, status, status)).fetchall()
        return [self._serialize(row) for row in rows]

    def get_execution_plan(self, account_id: int, plan_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("select * from execution_plan where id=%s and account_id=%s", (plan_id, account_id)).fetchone()
        return self._serialize(row)

    def update_execution_status(self, account_id: int, plan_id: int, status: str) -> dict[str, Any] | None:
        if status not in {"ACTIVE", "PAUSED", "CANCELLED"}:
            raise ExecutionValidationError("unsupported execution status")
        with self.connect() as conn:
            row = conn.execute("""
                update execution_plan set status=%s, status_reason=%s, status_source='USER', updated_at=now()
                where id=%s and account_id=%s and status not in ('COMPLETED','CANCELLED','EXPIRED') returning *
            """, (status, "用户手动暂停执行" if status == "PAUSED" else None, plan_id, account_id)).fetchone()
            if row:
                action = conn.execute("select id,status from trade_plan where id=%s and account_id=%s for update", (row["trade_plan_id"], account_id)).fetchone()
                if action:
                    if status == "ACTIVE" and action["status"] in {"READY", "PARTIALLY_EXECUTED"}:
                        conn.execute("update trade_plan set status='ARMED', updated_at=now() where id=%s", (action["id"],))
                    elif status == "CANCELLED" and action["status"] in {"READY", "ARMED", "PARTIALLY_EXECUTED"}:
                        filled = conn.execute("select coalesce(sum(filled_qty), 0) as quantity from execution_plan where trade_plan_id=%s", (action["id"],)).fetchone()
                        next_action_status = "PARTIALLY_EXECUTED" if int(filled["quantity"] or 0) > 0 else "READY"
                        conn.execute("update trade_plan set status=%s, cancelled_at=null, updated_at=now() where id=%s", (next_action_status, action["id"]))
                        trade = conn.execute("select trade_id from trade_plan where id=%s", (action["id"],)).fetchone()
                        if trade and trade["trade_id"]:
                            conn.execute("""
                                update trades t set status=case
                                    when exists (select 1 from trade_leg l where l.trade_id=t.id and l.remaining_qty>0) then 'ACTIVE'
                                    else 'PLANNED' end,
                                    updated_at=now()
                                where t.id=%s and t.account_id=%s and t.status in ('PLANNED','CLOSING','CANCELLED')
                            """, (trade["trade_id"], account_id))
        return self._serialize(row)

    def update_execution_status_reason(self, account_id: int, plan_id: int, reason: str | None) -> None:
        """Persist the latest user-facing reason an active plan is waiting or blocked."""
        value = str(reason).strip() if reason else None
        with self.connect() as conn:
            conn.execute(
                """
                update execution_plan set status_reason=%s, updated_at=now()
                where id=%s and account_id=%s and status='ACTIVE'
                  and status_reason is distinct from %s
                """,
                (value, plan_id, account_id, value),
            )

    def list_orders(self, account_id: int, execution_plan_id: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if execution_plan_id is None:
                rows = conn.execute("select * from trading_order where account_id=%s order by created_at desc", (account_id,)).fetchall()
            else:
                rows = conn.execute("select * from trading_order where account_id=%s and execution_plan_id=%s order by created_at desc", (account_id, execution_plan_id)).fetchall()
        return [self._serialize(row) for row in rows]

    def list_fills(self, account_id: int, order_id: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if order_id is None:
                rows = conn.execute("select * from trading_fill where account_id=%s order by filled_at desc", (account_id,)).fetchall()
            else:
                rows = conn.execute("select * from trading_fill where account_id=%s and order_id=%s order by filled_at desc", (account_id, order_id)).fetchall()
        return [self._serialize(row) for row in rows]

    def create_pending_order(self, item: OrderInput, client_order_id: str | None = None) -> dict[str, Any]:
        _positive_int(item.quantity, "quantity")
        _positive_int(item.account_id, "account_id")
        if item.price is not None:
            _positive_number(item.price, "price")
        client_id = client_order_id or f"LLL-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:10]}"
        canonical_symbol = normalize_symbol(item.symbol)
        with self.connect() as conn:
            row = conn.execute("""
                insert into trading_order (account_id, execution_plan_id, client_order_id, symbol, side, order_type, price, quantity)
                select %s,%s,%s,%s,%s,%s,%s,%s from execution_plan ep
                where ep.id=%s and ep.account_id=%s and ep.status='ACTIVE' returning *
            """, (item.account_id, item.execution_plan_id, client_id, canonical_symbol, item.side, item.order_type, item.price, item.quantity, item.execution_plan_id, item.account_id)).fetchone()
            if not row:
                raise ExecutionValidationError("ExecutionPlan does not belong to account, does not exist, or is not ACTIVE")
        return self._serialize(row)

    def record_fill(self, account_id: int, order_id: int, fill: dict[str, Any]) -> dict[str, Any]:
        _positive_int(order_id, "order_id")
        if not str(fill.get("broker_fill_id") or "").strip():
            raise ExecutionValidationError("broker_fill_id is required for an idempotent fill record")
        quantity = _positive_int(fill.get("quantity"), "quantity")
        price = _positive_number(fill.get("price"), "price")
        filled_at = fill.get("filled_at") or datetime.now(UTC)
        if isinstance(filled_at, str):
            filled_at = datetime.fromisoformat(filled_at.replace("Z", "+00:00"))
        with self.connect() as conn:
            order = conn.execute("select * from trading_order where id=%s and account_id=%s for update", (order_id, account_id)).fetchone()
            if not order:
                raise ExecutionValidationError("Order not found")
            position_symbol = normalize_symbol(order["symbol"])
            if fill.get("broker_fill_id"):
                existing = conn.execute("select * from trading_fill where order_id=%s and broker_fill_id=%s", (order_id, fill["broker_fill_id"])).fetchone()
                if existing:
                    return self._serialize(existing)
            new_filled = int(order["filled_quantity"]) + quantity
            if new_filled > int(order["quantity"]):
                raise ExecutionValidationError("fill quantity exceeds order quantity")
            fill_row = conn.execute("""
                insert into trading_fill (account_id, order_id, broker_fill_id, symbol, price, quantity, commission, tax, other_fee, filled_at, raw_broker_data)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) returning *
            """, (account_id, order_id, fill.get("broker_fill_id"), position_symbol, price, quantity, fill.get("commission", 0), fill.get("tax", 0), fill.get("other_fee", 0), filled_at, json.dumps(fill.get("raw_broker_data")) if fill.get("raw_broker_data") is not None else None)).fetchone()
            order_status = "FILLED" if new_filled == int(order["quantity"]) else "PARTIALLY_FILLED"
            conn.execute("""
                update trading_order set broker_order_id=coalesce(%s, broker_order_id),
                    filled_quantity=%s, status=%s,
                    completed_at=case when %s='FILLED' then now() else completed_at end
                where id=%s
            """, (fill.get("broker_order_id"), new_filled, order_status, order_status, order_id))
            execution = conn.execute("select execution_plan_id from trading_order where id=%s", (order_id,)).fetchone()
            if not execution:
                raise RuntimeError("Order execution plan reference is missing")
            conn.execute("""
                    update execution_plan set filled_qty=filled_qty+%s, remaining_qty=remaining_qty-%s,
                        status=case when remaining_qty-%s=0 then 'COMPLETED' else status end, updated_at=now()
                    where id=%s
                """, (quantity, quantity, quantity, execution["execution_plan_id"]))
            trade = conn.execute("""
                select tp.id as source_plan_id, tp.security_name, tp.trade_id, tp.action_type, tp.sequence_no, tp.input_json from execution_plan ep
                join trade_plan tp on tp.id = ep.trade_plan_id
                join trades t on t.id = tp.trade_id and t.account_id = ep.account_id
                where ep.id = %s and ep.account_id = %s and tp.account_id = ep.account_id
            """, (execution["execution_plan_id"], account_id)).fetchone()
            if not trade or not trade["trade_id"]:
                raise RuntimeError("Execution plan is not attached to a Trade")
            execution_state = conn.execute("""
                select ep.trade_plan_id, ep.filled_qty, ep.remaining_qty, ep.target_qty
                from execution_plan ep join trade_plan tp on tp.id=ep.trade_plan_id
                where ep.id=%s and ep.account_id=%s and tp.account_id=%s
            """, (execution["execution_plan_id"], account_id, account_id)).fetchone()
            if not execution_state:
                raise RuntimeError("Execution plan action reference is missing")
            action_status = "EXECUTED" if int(execution_state["remaining_qty"]) == 0 else "PARTIALLY_EXECUTED"
            conn.execute("""
                update trade_plan set status=%s, updated_at=now()
                where id=%s and account_id=%s and status in ('READY','ARMED','PARTIALLY_EXECUTED')
            """, (action_status, execution_state["trade_plan_id"], account_id))
            if order["side"] == "BUY":
                if trade["action_type"] not in {"OPEN", "ADD"}:
                    raise ExecutionValidationError("买入成交只能归属于 OPEN 或 ADD 计划")
                input_data = trade["input_json"] or {}
                planned_entry = float(input_data.get("reference_entry_price") or price)
                risk_reference = float(input_data.get("risk_reference_price") or 0)
                if risk_reference <= 0:
                    raise ExecutionValidationError("TradePlan 缺少有效风险参考价，无法建立 TradeLeg")
                conn.execute("""
                    insert into planning_position (account_id, symbol, security_name, quantity, available_quantity, average_cost, market_price, updated_at)
                    values (%s,%s,%s,%s,%s,%s,%s,now())
                    on conflict (account_id, symbol) do update set
                        average_cost=((planning_position.quantity * planning_position.average_cost) + (%s * %s)) /
                            (planning_position.quantity + %s),
                        quantity=planning_position.quantity+%s,
                        available_quantity=planning_position.available_quantity+%s,
                        market_price=%s, updated_at=now()
                """, (account_id, position_symbol, trade["security_name"], quantity, quantity, price, price, quantity, price, quantity, quantity, quantity, price))
                conn.execute("""
                    insert into trade_leg (
                        trade_id, source_plan_id, leg_type, sequence_no, entry_qty, remaining_qty,
                        planned_entry_price, actual_avg_entry_price, initial_risk_reference_price,
                        current_risk_reference_price, failure_handling, opened_at, updated_at
                    )
                    select tp.trade_id, tp.id, tp.action_type, tp.sequence_no, %s, %s,
                           %s, %s, %s, %s, tp.failure_handling, now(), now()
                    from trade_plan tp where tp.id = %s
                    on conflict (source_plan_id) do update set
                        actual_avg_entry_price = (
                            (trade_leg.entry_qty * coalesce(trade_leg.actual_avg_entry_price, excluded.actual_avg_entry_price)) +
                            (excluded.entry_qty * excluded.actual_avg_entry_price)
                        ) / nullif(trade_leg.entry_qty + excluded.entry_qty, 0),
                        entry_qty = trade_leg.entry_qty + excluded.entry_qty,
                        remaining_qty = trade_leg.remaining_qty + excluded.remaining_qty,
                        updated_at = now()
                """, (quantity, quantity, planned_entry, price, risk_reference, risk_reference, trade["source_plan_id"]))
                conn.execute("update trades set status='ACTIVE', opened_at=coalesce(opened_at, now()), updated_at=now() where id=%s", (trade["trade_id"],))
            else:
                if trade["action_type"] not in {"REDUCE", "CLOSE"}:
                    raise ExecutionValidationError("卖出成交只能归属于 REDUCE 或 CLOSE 计划")
                position = conn.execute("select quantity, available_quantity, average_cost from planning_position where account_id=%s and symbol=%s for update", (account_id, position_symbol)).fetchone()
                if not position or int(position["available_quantity"]) < quantity:
                    raise ExecutionValidationError("sell fill exceeds available position quantity")
                realized_delta = (price - float(position["average_cost"])) * quantity - sum(
                    float(fill.get(name) or 0) for name in ("commission", "tax", "other_fee")
                )
                account_update = conn.execute(
                    "update trading_account set realized_pnl=realized_pnl+%s, updated_at=now() where id=%s returning id",
                    (realized_delta, account_id),
                ).fetchone()
                if not account_update:
                    raise ExecutionValidationError("Trading account not found")
                remaining = int(position["quantity"]) - quantity
                if remaining == 0:
                    conn.execute("delete from planning_position where account_id=%s and symbol=%s", (account_id, position_symbol))
                else:
                    conn.execute("update planning_position set quantity=%s, available_quantity=available_quantity-%s, market_price=%s, updated_at=now() where account_id=%s and symbol=%s", (remaining, quantity, price, account_id, position_symbol))
                legs = conn.execute("""
                    select id, remaining_qty from trade_leg
                    where trade_id=%s and remaining_qty > 0
                    order by sequence_no desc, id desc
                    for update
                """, (trade["trade_id"],)).fetchall()
                remaining_to_attribute = quantity
                for leg in legs:
                    if remaining_to_attribute <= 0:
                        break
                    attributed = min(remaining_to_attribute, int(leg["remaining_qty"]))
                    new_remaining = int(leg["remaining_qty"]) - attributed
                    conn.execute("""
                        update trade_leg set remaining_qty=%s,
                            closed_at=case when %s=0 then now() else closed_at end,
                            updated_at=now()
                        where id=%s
                    """, (new_remaining, new_remaining, leg["id"]))
                    remaining_to_attribute -= attributed
                if remaining_to_attribute:
                    raise ExecutionValidationError("卖出成交数量超过 TradeLeg 剩余数量")
                current_position = conn.execute("select quantity from planning_position where account_id=%s and symbol=%s", (account_id, position_symbol)).fetchone()
                if current_position and int(current_position["quantity"]) > 0:
                    new_status = "CLOSING" if trade["action_type"] == "CLOSE" else "ACTIVE"
                else:
                    new_status = "CLOSED"
                conn.execute("update trades set status=%s, closed_at=case when %s='CLOSED' then coalesce(closed_at, now()) else closed_at end, updated_at=now() where id=%s", (new_status, new_status, trade["trade_id"]))
            self._refresh_trade_position_state(conn, int(trade["trade_id"]), account_id, position_symbol)
        return self._serialize(fill_row)

    @staticmethod
    def _refresh_trade_position_state(conn: Any, trade_id: int, account_id: int, symbol: str) -> None:
        position = conn.execute("""
            select quantity, available_quantity, average_cost, market_price,
                   quantity * market_price as market_value
            from planning_position where account_id=%s and symbol=%s
        """, (account_id, symbol)).fetchone()
        legs = conn.execute("""
            select remaining_qty, actual_avg_entry_price, planned_entry_price,
                   current_risk_reference_price, initial_risk_reference_price
            from trade_leg where trade_id=%s and remaining_qty > 0
        """, (trade_id,)).fetchall()
        capital_risk = 0.0
        giveback_risk = 0.0
        market_price = float(position["market_price"]) if position else 0.0
        for leg in legs:
            qty = int(leg["remaining_qty"])
            entry = float(leg["actual_avg_entry_price"] or leg["planned_entry_price"])
            risk_ref = float(leg["current_risk_reference_price"] or leg["initial_risk_reference_price"])
            capital_risk += max(0.0, entry - risk_ref) * qty
            giveback_risk += max(0.0, market_price - risk_ref) * qty
        conn.execute("""
            insert into trade_position_state (
                trade_id, position_qty, available_qty, avg_cost, market_price, market_value,
                current_capital_risk, current_giveback_risk, updated_at
            ) values (%s,%s,%s,%s,%s,%s,%s,%s,now())
            on conflict (trade_id) do update set position_qty=excluded.position_qty,
                available_qty=excluded.available_qty, avg_cost=excluded.avg_cost,
                market_price=excluded.market_price, market_value=excluded.market_value,
                current_capital_risk=excluded.current_capital_risk,
                current_giveback_risk=excluded.current_giveback_risk, updated_at=now()
        """, (trade_id, int(position["quantity"]) if position else 0, int(position["available_quantity"]) if position else 0,
               position["average_cost"] if position else None, position["market_price"] if position else None,
               position["market_value"] if position else 0, capital_risk, giveback_risk))

    def record_order_update(self, account_id: int, order_id: int, update: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"PENDING_SUBMIT", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "REJECTED", "EXPIRED", "UNKNOWN"}
        next_status = str(update.get("status") or "").upper()
        if next_status not in allowed:
            raise ExecutionValidationError("unsupported broker order status")
        with self.connect() as conn:
            current = conn.execute("select status from trading_order where id=%s and account_id=%s for update", (order_id, account_id)).fetchone()
            if not current:
                return None
            current_status = str(current["status"])
            if not self.is_order_status_transition_allowed(current_status, next_status):
                raise ExecutionValidationError(f"invalid order status transition: {current_status} -> {next_status}")
            row = conn.execute("""
                update trading_order set broker_order_id=coalesce(%s, broker_order_id), status=%s,
                    reject_code=%s, reject_message=%s, raw_broker_data=%s::jsonb,
                    accepted_at=case when %s in ('ACCEPTED','PARTIALLY_FILLED','FILLED') then coalesce(accepted_at, now()) else accepted_at end
                where id=%s and account_id=%s returning *
            """, (update.get("broker_order_id"), next_status, update.get("reject_code"), update.get("reject_message"), json.dumps(update.get("raw_broker_data")) if update.get("raw_broker_data") is not None else None, next_status, order_id, account_id)).fetchone()
            # A replay of the same terminal broker event must be idempotent.
            # Otherwise a user who explicitly resumes the plan would have it
            # immediately paused again by the old CANCELLED/REJECTED/EXPIRED
            # event for the previous order.
            if self.should_pause_plan_for_order_transition(current_status, next_status):
                reason = str(update.get("status_reason") or update.get("reject_message") or {
                    "CANCELLED": "委托已撤销，等待用户重新审阅",
                    "REJECTED": "委托被拒绝，等待用户重新审阅",
                    "EXPIRED": "委托已过期，等待用户重新审阅",
                }[next_status])
                source = str(update.get("status_source") or "BROKER")
                conn.execute("""
                    update execution_plan
                    set status='PAUSED', status_reason=%s, status_source=%s, updated_at=now()
                    where id=%s and account_id=%s and status='ACTIVE'
                """, (reason, source, row["execution_plan_id"], account_id))
        return self._serialize(row)

    def mark_order_cancelled(self, account_id: int, order_id: int, broker_order_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("update trading_order set status='CANCELLED', broker_order_id=%s where id=%s and account_id=%s and status not in ('FILLED','CANCELLED','REJECTED','EXPIRED') returning *", (broker_order_id, order_id, account_id)).fetchone()
            if row:
                conn.execute("""
                    update execution_plan
                    set status='PAUSED', status_reason='委托已撤销，等待用户重新审阅', status_source='BROKER', updated_at=now()
                    where id=%s and account_id=%s and status='ACTIVE'
                """, (row["execution_plan_id"], account_id))
        return self._serialize(row)

    def mark_order_cancel_pending(
        self,
        account_id: int,
        order_id: int,
        broker_order_id: str | None,
        raw_broker_data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Record an asynchronously accepted cancel request without inventing a terminal state."""
        with self.connect() as conn:
            current = conn.execute(
                "select status, raw_broker_data from trading_order where id=%s and account_id=%s for update",
                (order_id, account_id),
            ).fetchone()
            if not current or str(current["status"]) in {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}:
                return None
            cancel_data = dict(raw_broker_data)
            cancel_data["_cancel_previous_status"] = str(current["status"])
            cancel_data["_cancel_previous_raw_broker_data"] = current["raw_broker_data"]
            cancel_data["_cancel_attempt_count"] = int(raw_broker_data.get("_cancel_attempt_count") or 0)
            row = conn.execute(
                """
                update trading_order
                set status='CANCEL_PENDING',
                    broker_order_id=coalesce(%s, broker_order_id),
                    raw_broker_data=%s::jsonb
                where id=%s and account_id=%s
                  and status not in ('FILLED','CANCELLED','REJECTED','EXPIRED')
                returning *
                """,
                (broker_order_id, json.dumps(cancel_data), order_id, account_id),
            ).fetchone()
            if row:
                conn.execute("""
                    update execution_plan
                    set status='PAUSED', status_reason='撤单请求已受理，等待券商最终状态', status_source='USER', updated_at=now()
                    where id=(select execution_plan_id from trading_order where id=%s and account_id=%s)
                      and account_id=%s and status='ACTIVE'
                """, (order_id, account_id, account_id))
        return self._serialize(row)

    def restore_order_after_cancel_rejection(self, account_id: int, order_id: int, command_id: str) -> dict[str, Any] | None:
        """Restore the prior live order state when Broker Node safely rejects dispatch."""
        with self.connect() as conn:
            current = conn.execute(
                "select raw_broker_data from trading_order where id=%s and account_id=%s for update",
                (order_id, account_id),
            ).fetchone()
            if not current or not isinstance(current["raw_broker_data"], dict):
                return None
            cancel_data = current["raw_broker_data"]
            if str(cancel_data.get("command_id") or "") != command_id:
                return None
            previous_data = cancel_data.get("_cancel_previous_raw_broker_data")
            restored_data = dict(previous_data) if isinstance(previous_data, dict) else {}
            restored_data["_cancel_attempt_count"] = int(cancel_data.get("_cancel_attempt_count") or 0) + 1
            row = conn.execute(
                """
                update trading_order
                set status=coalesce(raw_broker_data->>'_cancel_previous_status', 'SUBMITTED'),
                    raw_broker_data=%s::jsonb
                where id=%s and account_id=%s and status='CANCEL_PENDING'
                  and raw_broker_data->>'command_id'=%s
                returning *
                """,
                (json.dumps(restored_data), order_id, account_id, command_id),
            ).fetchone()
        return self._serialize(row)

    def get_control(self, account_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("select * from trading_control where account_id=%s", (account_id,)).fetchone()
        return self._serialize(row) or {"execution_paused": False}

    def set_control(self, account_id: int, paused: bool, reason: str | None) -> dict[str, Any]:
        with self.connect() as conn:
            if paused:
                conn.execute("update execution_plan set status='PAUSED', updated_at=now() where account_id=%s and status='ACTIVE'", (account_id,))
            row = conn.execute("update trading_control set execution_paused=%s, reason=%s, updated_at=now() where account_id=%s returning *", (paused, reason, account_id)).fetchone()
            if not row:
                raise ExecutionValidationError("Trading account control not found")
        return self._serialize(row)

    def add_reconciliation_issue(self, account_id: int, issue: dict[str, Any]) -> dict[str, Any]:
        fingerprint = self._reconciliation_fingerprint(issue)
        with self.connect() as conn:
            existing = conn.execute("select * from reconciliation_issue where account_id=%s and issue_type=%s and fingerprint=%s and status='OPEN'", (account_id, issue["issue_type"], fingerprint)).fetchone()
            if existing:
                return self._serialize(existing)
            if issue['issue_type'] in ('UNMATCHED_BROKER_ORDER_EVENT', 'UNMATCHED_BROKER_FILL'):
                verified = conn.execute("""select * from reconciliation_issue
                    where account_id=%s and issue_type=%s and fingerprint=%s and status='RESOLVED'
                    and local_value->'resolution'->>'type'='EXTERNAL_VERIFIED'
                    order by resolved_at desc limit 1""", (account_id, issue['issue_type'], fingerprint)).fetchone()
                if verified:
                    return self._serialize(verified)
            # Rows created before fingerprinting was introduced have a NULL
            # fingerprint. Compare their durable broker/local identity too,
            # so replaying the event log cannot create another copy of a
            # legacy issue. Keep the historical rows intact; cleanup is a
            # separate, explicitly approved operation.
            legacy_rows = conn.execute(
                "select * from reconciliation_issue where account_id=%s and issue_type=%s and status='OPEN' and fingerprint is null",
                (account_id, issue["issue_type"]),
            ).fetchall()
            for candidate in legacy_rows:
                candidate_issue = {
                    "issue_type": candidate["issue_type"],
                    "symbol": candidate["symbol"],
                    "local_value": candidate["local_value"],
                    "broker_value": candidate["broker_value"],
                }
                if self._reconciliation_fingerprint(candidate_issue) == fingerprint:
                    return self._serialize(candidate)
            row = conn.execute("insert into reconciliation_issue (account_id, issue_type, symbol, local_value, broker_value, fingerprint) values (%s,%s,%s,%s::jsonb,%s::jsonb,%s) on conflict do nothing returning *", (account_id, issue["issue_type"], issue.get("symbol"), json.dumps(issue.get("local_value")), json.dumps(issue.get("broker_value")), fingerprint)).fetchone()
            if not row:
                row = conn.execute("select * from reconciliation_issue where account_id=%s and issue_type=%s and fingerprint=%s and status='OPEN'", (account_id, issue["issue_type"], fingerprint)).fetchone()
            if not row:
                raise ExecutionValidationError("reconciliation issue insert failed")
        return self._serialize(row)

    @staticmethod
    def _reconciliation_fingerprint(issue: dict[str, Any]) -> str:
        """Return a stable identity for one open reconciliation fact.

        Broker snapshot events may repeat the same order/fill with different
        event sequence numbers.  The identity must therefore use the broker's
        durable order/fill IDs (or the local client ID), never the event seq or
        detection timestamp.
        """
        issue_type = str(issue.get("issue_type") or "UNKNOWN")
        local = issue.get("local_value") if isinstance(issue.get("local_value"), dict) else {}
        broker = issue.get("broker_value") if isinstance(issue.get("broker_value"), dict) else {}

        def candidates(item: dict[str, Any]) -> list[tuple[str, Any]]:
            values: list[tuple[str, Any]] = []
            for key in ("broker_execution_id", "exec_id", "fill_id", "broker_fill_id", "broker_order_id", "order_id", "client_order_id", "cl_ord_id"):
                value = item.get(key)
                if value not in (None, ""):
                    values.append((key, value))
            for nested_key in ("normalized", "raw"):
                nested = item.get(nested_key)
                if isinstance(nested, dict):
                    values.extend(candidates(nested))
            return values

        identity = candidates(broker) + candidates(local)
        if identity:
            key, value = identity[0]
            return f"{issue_type}:{key}:{value}"
        fallback = {
            "issue_type": issue_type,
            "symbol": issue.get("symbol"),
            "local_value": local,
            "broker_value": broker,
        }
        digest = hashlib.sha256(json.dumps(fallback, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        return f"{issue_type}:payload:{digest}"

    def list_reconciliation_issues(self, account_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("select * from reconciliation_issue where account_id=%s and status='OPEN' order by detected_at desc", (account_id,)).fetchall()
        return [self._serialize(row) for row in rows]

    def resolve_position_mismatch(
        self,
        account_id: int,
        symbol: str,
        local_quantity: int,
        broker_quantity: int,
        local_available_quantity: int | None = None,
        broker_available_quantity: int | None = None,
    ) -> int:
        """Resolve an old position mismatch only after a fresh equal snapshot.

        The original local/broker values remain in the issue row for audit; the
        resolution metadata records the fresh values that proved the mismatch
        no longer exists.
        """
        if local_quantity != broker_quantity:
            return 0
        compare_available = local_available_quantity is not None and broker_available_quantity is not None
        if compare_available and local_available_quantity != broker_available_quantity:
            return 0
        with self.connect() as conn:
            issue_types = ("POSITION_QUANTITY_MISMATCH", "POSITION_AVAILABLE_QUANTITY_MISMATCH")
            rows = conn.execute(
                "select id, issue_type, symbol, local_value, broker_value from reconciliation_issue where account_id=%s and issue_type in (%s,%s) and status='OPEN' for update",
                (account_id, *issue_types),
            ).fetchall()
            resolved = 0
            for row in rows:
                if normalize_symbol(row["symbol"]) != normalize_symbol(symbol):
                    continue
                local_value = row["local_value"] if isinstance(row["local_value"], dict) else {}
                resolution = {
                    "type": "POSITION_SNAPSHOT_MATCHED",
                    "symbol": symbol,
                    "local_quantity": local_quantity,
                    "broker_quantity": broker_quantity,
                    "local_available_quantity": local_available_quantity,
                    "broker_available_quantity": broker_available_quantity,
                    "resolved_at": datetime.now(UTC).isoformat(),
                }
                updated = conn.execute(
                    "update reconciliation_issue set status='RESOLVED', resolved_at=now(), local_value=%s::jsonb, broker_value=%s::jsonb where id=%s and account_id=%s and status='OPEN' returning id",
                    (json.dumps({**local_value, "resolution": resolution}), json.dumps({"quantity": broker_quantity, "available_quantity": broker_available_quantity}), row["id"], account_id),
                ).fetchone()
                if updated:
                    resolved += 1
        return resolved

    def resolve_unsubmitted_order_issue(self, account_id: int, issue_id: int, resolution_note: str, resolution_type: str = "BROKER_COMMAND_NOT_FOUND") -> dict[str, Any]:
        """Resolve only a verified local order that never crossed the broker boundary.

        This is deliberately narrower than a generic reconciliation override:
        the caller must first prove at the Broker Node boundary that the
        durable command is absent and that no order/fill exists. The database
        transaction then preserves the issue row as RESOLVED and moves the
        local order to a terminal rejected state; it never deletes audit data.
        """
        if not str(resolution_note or "").strip():
            raise ExecutionValidationError("resolution_note is required")
        if resolution_type not in {"BROKER_COMMAND_NOT_FOUND", "BROKER_VALIDATION_REJECTED"}:
            raise ExecutionValidationError("unsupported reconciliation resolution type")
        with self.connect() as conn:
            issue = conn.execute("select * from reconciliation_issue where id=%s and account_id=%s for update", (issue_id, account_id)).fetchone()
            if not issue:
                raise ExecutionValidationError("reconciliation issue not found for account")
            if issue["status"] != "OPEN" or issue["issue_type"] != "LOCAL_ORDER_UNCONFIRMED":
                raise ExecutionValidationError("only an open LOCAL_ORDER_UNCONFIRMED issue can use this resolution")
            local = issue["local_value"] if isinstance(issue["local_value"], dict) else {}
            order_id = local.get("id")
            if not isinstance(order_id, int):
                raise ExecutionValidationError("reconciliation issue has no local order reference")
            order = conn.execute("select * from trading_order where id=%s and account_id=%s for update", (order_id, account_id)).fetchone()
            if not order:
                raise ExecutionValidationError("local order not found for account")
            if order["broker_order_id"]:
                raise ExecutionValidationError("local order already has a broker order id")
            fill = conn.execute("select 1 from trading_fill where order_id=%s limit 1", (order_id,)).fetchone()
            if fill:
                raise ExecutionValidationError("local order already has a fill")
            raw = order["raw_broker_data"] if isinstance(order["raw_broker_data"], dict) else {}
            raw = {**raw, "resolution": {"type": resolution_type, "note": resolution_note.strip(), "resolved_at": datetime.now(UTC).isoformat()}}
            updated_order = conn.execute("""
                update trading_order set status='REJECTED', reject_code=%s,
                    reject_message=%s, raw_broker_data=%s::jsonb
                where id=%s and account_id=%s and status in ('PENDING_SUBMIT','SUBMITTED','ACCEPTED','UNKNOWN')
                returning *
            """, (resolution_type, resolution_note.strip(), json.dumps(raw), order_id, account_id)).fetchone()
            if not updated_order:
                raise ExecutionValidationError("local order is no longer in a resolvable state")
            # Resolving a never-submitted order must also stop its active
            # execution plan.  Otherwise the scheduler can see the plan as
            # ACTIVE again on the next cycle and create a duplicate order
            # after the reconciliation gate has been cleared.
            conn.execute("""
                update execution_plan
                set status='PAUSED', status_reason=%s, status_source='RECONCILIATION', updated_at=now()
                where id=%s and account_id=%s
                  and status not in ('COMPLETED', 'CANCELLED', 'EXPIRED')
            """, ("本地委托未确认，等待用户重新审阅", order["execution_plan_id"], account_id))
            updated_issue = conn.execute("""
                update reconciliation_issue set status='RESOLVED', resolved_at=now(),
                    local_value=%s::jsonb
                where id=%s and account_id=%s and status='OPEN'
                returning *
            """, (json.dumps({**local, "resolution": {"type": resolution_type, "note": resolution_note.strip()}}), issue_id, account_id)).fetchone()
            if not updated_issue:
                raise ExecutionValidationError("reconciliation issue is no longer open")
        return {"order": self._serialize(updated_order), "issue": self._serialize(updated_issue)}

    def get_event_cursor(self, account_id: int) -> int:
        with self.connect() as conn:
            # The migration seeds cursors for accounts that already existed
            # when the table was created. Accounts added later must be
            # initialized before their first broker-event sync as well.
            conn.execute("""
                insert into broker_event_cursor(account_id, last_consumed_event_seq)
                select id, 0 from trading_account where id=%s
                on conflict(account_id) do nothing
            """, (account_id,))
            row = conn.execute("select last_consumed_event_seq from broker_event_cursor where account_id=%s", (account_id,)).fetchone()
        if not row:
            raise ExecutionValidationError("Trading account not found")
        return int(row["last_consumed_event_seq"])

    def save_event_cursor(self, account_id: int, sequence: int) -> None:
        if sequence < 0:
            raise ValueError("event sequence must be non-negative")
        with self.connect() as conn:
            conn.execute("""
                insert into broker_event_cursor(account_id, last_consumed_event_seq)
                values (%s,%s)
                on conflict(account_id) do update set
                    last_consumed_event_seq=excluded.last_consumed_event_seq, updated_at=now()
                where broker_event_cursor.last_consumed_event_seq <= excluded.last_consumed_event_seq
            """, (account_id, sequence))

    def find_order_by_broker_reference(self, account_id: int, client_order_id: str | None, broker_order_id: str | None) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("""
                select * from trading_order where account_id=%s and (
                    (%s::text is not null and client_order_id=%s) or
                    (%s::text is not null and broker_order_id=%s)
                ) order by id desc limit 1
            """, (account_id, client_order_id, client_order_id, broker_order_id, broker_order_id)).fetchone()
        return self._serialize(row)

    def resolve_linked_broker_issues(
        self,
        account_id: int,
        order_id: int,
        broker_order_id: str,
        broker_client_order_id: str | None = None,
        broker_execution_id: str | None = None,
    ) -> int:
        """Resolve only unmatched facts proven to belong to a local order.

        The caller must have already matched the authoritative Broker Node
        snapshot to ``order_id``.  Each issue is then checked against its
        durable broker identity; unrelated issues remain open.
        """
        if not str(broker_order_id).strip():
            raise ExecutionValidationError("broker_order_id is required")

        def identity_values(value: Any) -> set[str]:
            if not isinstance(value, dict):
                return set()
            values: set[str] = set()
            normalized = value.get("normalized")
            raw = value.get("raw")
            for source in (value, normalized, raw):
                if isinstance(source, dict):
                    for key in ("broker_order_id", "order_id", "exchange_order_id", "broker_execution_id", "exec_id", "client_order_id", "cl_ord_id"):
                        item = source.get(key)
                        if item not in (None, ""):
                            values.add(str(item))
            return values

        expected = {str(broker_order_id)}
        if broker_client_order_id:
            expected.add(str(broker_client_order_id))
        if broker_execution_id:
            expected.add(str(broker_execution_id))
        resolved = 0
        with self.connect() as conn:
            local_order = conn.execute(
                "select client_order_id from trading_order where id=%s and account_id=%s",
                (order_id, account_id),
            ).fetchone()
            if local_order and local_order["client_order_id"]:
                expected.add(str(local_order["client_order_id"]))
            rows = conn.execute(
                "select * from reconciliation_issue where account_id=%s and status='OPEN' and issue_type in ('LOCAL_ORDER_UNCONFIRMED','UNMATCHED_BROKER_ORDER_EVENT','UNMATCHED_BROKER_FILL')",
                (account_id,),
            ).fetchall()
            for row in rows:
                local_value = row["local_value"] if isinstance(row["local_value"], dict) else {}
                local_identity = {str(local_value.get("client_order_id")), str(local_value.get("id"))}
                if not (identity_values(row["broker_value"]) | local_identity) & expected:
                    continue
                resolution = {
                    "type": "BROKER_FACT_LINKED",
                    "order_id": order_id,
                    "broker_order_id": broker_order_id,
                    "broker_execution_id": broker_execution_id,
                    "resolved_at": datetime.now(UTC).isoformat(),
                }
                updated = conn.execute(
                    "update reconciliation_issue set status='RESOLVED', resolved_at=now(), local_value=%s::jsonb where id=%s and account_id=%s and status='OPEN' returning id",
                    (json.dumps({**local_value, "resolution": resolution}), row["id"], account_id),
                ).fetchone()
                if updated:
                    resolved += 1
        return resolved
