from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row


class ExecutionValidationError(ValueError):
    """Raised when an execution instruction is invalid."""


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
        if order.side == "BUY":
            if order.price is not None:
                required_cash = order.price * order.quantity
                check("available_cash", float(account.get("available_cash", 0)) >= required_cash, "BLOCK", "可用现金不足")
            else:
                checks.append({"name": "available_cash", "status": "WARNING", "message": "市价类委托需要券商返回最终资金校验"})
        symbol_orders = [item for item in active_orders if item.get("symbol") == order.symbol and item.get("status") not in {"CANCELLED", "FILLED", "REJECTED", "EXPIRED"}]
        check("duplicate_order", not symbol_orders, "BLOCK", "该证券已有未完成委托")
        equity = float(account.get("equity", 0))
        if order.side == "BUY" and order.price is not None and equity > 0:
            current_value = sum(float(item.get("market_value", 0)) for item in positions if item.get("symbol") == order.symbol)
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
                    created_at timestamptz not null default now(), updated_at timestamptz not null default now()
                )
            """)
            conn.execute("create index if not exists idx_execution_plan_status on execution_plan(status, created_at desc)")
            conn.execute("alter table execution_plan add column if not exists account_id integer")
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
        if item.execution_type in {"LIMIT", "PERSISTENT_LIMIT", "PRICE_TRIGGER", "PRICE_RANGE"}:
            _positive_number(params.get("limit_price"), "limit_price")
        if item.execution_type == "PRICE_TRIGGER":
            _positive_number(params.get("trigger_price"), "trigger_price")
        if item.execution_type == "PRICE_RANGE":
            low = _positive_number(params.get("low_price"), "low_price")
            high = _positive_number(params.get("high_price"), "high_price")
            if low > high:
                raise ExecutionValidationError("low_price cannot exceed high_price")
        with self.connect() as conn:
            row = conn.execute("""
                insert into execution_plan (account_id, trade_plan_id, symbol, side, target_qty, remaining_qty, execution_type, valid_from, valid_until, execution_params_json)
                select %s,%s,tp.symbol,%s,%s,%s,%s,%s,%s,%s::jsonb from trade_plan tp
                where tp.id=%s and tp.account_id=%s returning *
            """, (item.account_id, item.trade_plan_id, item.side, item.target_qty, item.target_qty, item.execution_type, item.valid_from, item.valid_until, json.dumps(params), item.trade_plan_id, item.account_id)).fetchone()
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
            row = conn.execute("update execution_plan set status=%s, updated_at=now() where id=%s and account_id=%s and status not in ('COMPLETED','CANCELLED','EXPIRED') returning *", (status, plan_id, account_id)).fetchone()
        return self._serialize(row)

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
        with self.connect() as conn:
            row = conn.execute("""
                insert into trading_order (account_id, execution_plan_id, client_order_id, symbol, side, order_type, price, quantity)
                select %s,%s,%s,ep.symbol,%s,%s,%s,%s from execution_plan ep
                where ep.id=%s and ep.account_id=%s returning *
            """, (item.account_id, item.execution_plan_id, client_id, item.side, item.order_type, item.price, item.quantity, item.execution_plan_id, item.account_id)).fetchone()
            if not row:
                raise ExecutionValidationError("ExecutionPlan does not belong to account or does not exist")
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
            """, (account_id, order_id, fill.get("broker_fill_id"), order["symbol"], price, quantity, fill.get("commission", 0), fill.get("tax", 0), fill.get("other_fee", 0), filled_at, json.dumps(fill.get("raw_broker_data")) if fill.get("raw_broker_data") is not None else None)).fetchone()
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
                """, (account_id, order["symbol"], trade["security_name"], quantity, quantity, price, price, quantity, price, quantity, quantity, quantity, price))
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
                position = conn.execute("select quantity, available_quantity from planning_position where account_id=%s and symbol=%s for update", (account_id, order["symbol"])).fetchone()
                if not position or int(position["available_quantity"]) < quantity:
                    raise ExecutionValidationError("sell fill exceeds available position quantity")
                remaining = int(position["quantity"]) - quantity
                if remaining == 0:
                    conn.execute("delete from planning_position where account_id=%s and symbol=%s", (account_id, order["symbol"]))
                else:
                    conn.execute("update planning_position set quantity=%s, available_quantity=available_quantity-%s, market_price=%s, updated_at=now() where account_id=%s and symbol=%s", (remaining, quantity, price, account_id, order["symbol"]))
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
                current_position = conn.execute("select quantity from planning_position where account_id=%s and symbol=%s", (account_id, order["symbol"])).fetchone()
                if current_position and int(current_position["quantity"]) > 0:
                    new_status = "CLOSING" if trade["action_type"] == "CLOSE" else "ACTIVE"
                else:
                    new_status = "CLOSED"
                conn.execute("update trades set status=%s, closed_at=case when %s='CLOSED' then coalesce(closed_at, now()) else closed_at end, updated_at=now() where id=%s", (new_status, new_status, trade["trade_id"]))
            self._refresh_trade_position_state(conn, int(trade["trade_id"]), account_id, order["symbol"])
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
            transitions = {
                "PENDING_SUBMIT": {"PENDING_SUBMIT", "SUBMITTED", "ACCEPTED", "REJECTED", "UNKNOWN"},
                "SUBMITTED": {"SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "REJECTED", "EXPIRED", "UNKNOWN"},
                "ACCEPTED": {"ACCEPTED", "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "REJECTED", "EXPIRED", "UNKNOWN"},
                "PARTIALLY_FILLED": {"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "EXPIRED", "UNKNOWN"},
                "CANCEL_PENDING": {"CANCEL_PENDING", "CANCELLED", "PARTIALLY_FILLED", "FILLED", "UNKNOWN"},
                "UNKNOWN": {"UNKNOWN", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "REJECTED", "EXPIRED"},
                "FILLED": {"FILLED"},
                "CANCELLED": {"CANCELLED"},
                "REJECTED": {"REJECTED"},
                "EXPIRED": {"EXPIRED"},
            }
            if next_status not in transitions.get(current_status, set()):
                raise ExecutionValidationError(f"invalid order status transition: {current_status} -> {next_status}")
            row = conn.execute("""
                update trading_order set broker_order_id=coalesce(%s, broker_order_id), status=%s,
                    reject_code=%s, reject_message=%s, raw_broker_data=%s::jsonb,
                    accepted_at=case when %s in ('ACCEPTED','PARTIALLY_FILLED','FILLED') then coalesce(accepted_at, now()) else accepted_at end
                where id=%s and account_id=%s returning *
            """, (update.get("broker_order_id"), next_status, update.get("reject_code"), update.get("reject_message"), json.dumps(update.get("raw_broker_data")) if update.get("raw_broker_data") is not None else None, next_status, order_id, account_id)).fetchone()
        return self._serialize(row)

    def mark_order_cancelled(self, account_id: int, order_id: int, broker_order_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("update trading_order set status='CANCELLED', broker_order_id=%s where id=%s and account_id=%s and status not in ('FILLED','CANCELLED','REJECTED','EXPIRED') returning *", (broker_order_id, order_id, account_id)).fetchone()
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
        with self.connect() as conn:
            row = conn.execute("insert into reconciliation_issue (account_id, issue_type, symbol, local_value, broker_value) values (%s,%s,%s,%s::jsonb,%s::jsonb) returning *", (account_id, issue["issue_type"], issue.get("symbol"), json.dumps(issue.get("local_value")), json.dumps(issue.get("broker_value")))).fetchone()
        return self._serialize(row)

    def list_reconciliation_issues(self, account_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("select * from reconciliation_issue where account_id=%s and status='OPEN' order by detected_at desc", (account_id,)).fetchall()
        return [self._serialize(row) for row in rows]

    def get_event_cursor(self, account_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute("select last_consumed_event_seq from broker_event_cursor where account_id=%s", (account_id,)).fetchone()
        if not row:
            raise ExecutionValidationError("Broker event cursor is missing for account")
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
