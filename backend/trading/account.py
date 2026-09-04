from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from urllib.parse import urlparse
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row


class TradingDataValidationError(ValueError):
    """Raised when account, risk, or planning-position data is invalid."""


@dataclass(frozen=True)
class TradingAccount:
    name: str
    account_type: Literal["PLANNING", "SIMULATION", "LIVE"] = "PLANNING"
    broker: str | None = None
    broker_account_id: str | None = None
    broker_account_key: str | None = None
    broker_strategy_id: str | None = None
    broker_node_url: str | None = None
    broker_token_env: str | None = None
    currency: str = "CNY"
    status: Literal["ACTIVE", "DISCONNECTED", "LOCKED"] = "ACTIVE"
    equity: float = 0.0
    cash: float = 0.0
    available_cash: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass(frozen=True)
class RiskProfile:
    default_trade_risk_pct: float
    max_trade_risk_pct: float
    max_single_position_pct: float
    max_total_exposure_pct: float


@dataclass(frozen=True)
class PlanningPosition:
    symbol: str
    security_name: str
    quantity: int
    available_quantity: int
    average_cost: float
    market_price: float
    current_risk_reference_price: float | None = None
    risk_note: str | None = None


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TradingDataValidationError(f"{field} must be a number") from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise TradingDataValidationError(f"{field} must be finite")
    if positive and result <= 0:
        raise TradingDataValidationError(f"{field} must be greater than 0")
    if not positive and result < 0:
        raise TradingDataValidationError(f"{field} cannot be negative")
    return result


class TradingStore:
    """Persistence for the planning account, risk rules, and manual positions."""

    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("database_url is required")
        self.database_url = database_url
        self.init_schema()

    def connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                create table if not exists trading_account (
                    id integer primary key,
                    name text not null,
                    account_type text not null check (account_type in ('PLANNING', 'SIMULATION', 'LIVE')),
                    broker text,
                    broker_account_id text,
                    broker_account_key text,
                    broker_strategy_id text,
                    broker_node_url text,
                    broker_token_env text,
                    currency text not null default 'CNY',
                    status text not null check (status in ('ACTIVE', 'DISCONNECTED', 'LOCKED')),
                    configuration_confirmed boolean not null default false,
                    equity numeric not null,
                    cash numeric not null,
                    available_cash numeric not null,
                    realized_pnl numeric not null default 0,
                    unrealized_pnl numeric not null default 0,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now()
                )
                """
            )
            conn.execute(
                """
                create table if not exists risk_profile (
                    id integer,
                    default_trade_risk_pct numeric not null,
                    max_trade_risk_pct numeric not null,
                    max_single_position_pct numeric not null,
                    max_total_exposure_pct numeric not null,
                    configuration_confirmed boolean not null default false,
                    updated_at timestamptz not null default now(),
                    account_id integer primary key
                )
                """
            )
            conn.execute("alter table trading_account add column if not exists configuration_confirmed boolean not null default false")
            conn.execute("alter table trading_account add column if not exists broker_account_key text")
            conn.execute("alter table trading_account add column if not exists broker_strategy_id text")
            conn.execute("alter table trading_account add column if not exists broker_node_url text")
            conn.execute("alter table trading_account add column if not exists broker_token_env text")
            conn.execute(
                """
                create table if not exists broker_account_profile (
                    id bigserial primary key,
                    name text not null,
                    account_type text not null check (account_type in ('SIMULATION', 'LIVE')),
                    broker text not null,
                    broker_account_id text not null unique,
                    broker_account_key text not null unique,
                    broker_strategy_id text not null,
                    broker_node_url text not null,
                    broker_token_env text not null,
                    status text not null check (status in ('ACTIVE', 'DISCONNECTED', 'LOCKED')) default 'ACTIVE',
                    is_default boolean not null default false,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now()
                )
                """
            )
            conn.execute("alter table broker_account_profile add column if not exists broker_gm_token text")
            # Multi-account migration. Existing rows retain their IDs and data;
            # no historical records are copied to newly created accounts.
            conn.execute("alter table trading_account drop constraint if exists trading_account_id_check")
            conn.execute("alter table trading_account add column if not exists broker_profile_id bigint unique")
            conn.execute("alter table trading_account add column if not exists is_default boolean not null default false")
            conn.execute("alter table trading_account add column if not exists broker_connection_status text not null default 'UNKNOWN'")
            conn.execute("alter table trading_account add column if not exists broker_connection_checked_at timestamptz")
            conn.execute("alter table trading_account drop constraint if exists trading_account_broker_profile_fk")
            conn.execute("""alter table trading_account add constraint trading_account_broker_profile_fk
                foreign key (broker_profile_id) references broker_account_profile(id) on delete cascade""")
            conn.execute("alter table risk_profile drop constraint if exists risk_profile_id_check")
            conn.execute("alter table risk_profile add column if not exists account_id integer")
            conn.execute("update risk_profile set account_id = id where account_id is null")
            conn.execute("alter table risk_profile alter column account_id set not null")
            conn.execute("alter table risk_profile drop constraint if exists risk_profile_pkey")
            conn.execute("alter table risk_profile add constraint risk_profile_pkey primary key (account_id)")
            conn.execute("""do $$ begin
                if not exists (select 1 from pg_constraint where conname='risk_profile_account_fk') then
                    alter table risk_profile add constraint risk_profile_account_fk
                    foreign key (account_id) references trading_account(id) on delete cascade;
                end if;
            end $$;""")
            conn.execute("alter table risk_profile add column if not exists configuration_confirmed boolean not null default false")
            conn.execute(
                """
                create table if not exists planning_position (
                    id bigserial primary key,
                    account_id integer not null references trading_account(id),
                    symbol text not null,
                    security_name text not null,
                    quantity integer not null check (quantity >= 0),
                    available_quantity integer not null check (available_quantity >= 0),
                    average_cost numeric not null check (average_cost > 0),
                    market_price numeric not null check (market_price > 0),
                    current_risk_reference_price numeric,
                    risk_note text,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now(),
                    unique(account_id, symbol)
                )
                """
            )
            legacy_settings_row = conn.execute("select to_regclass('public.trade_settings') as table_name").fetchone()
            legacy_settings_exists = bool(legacy_settings_row and legacy_settings_row["table_name"])
            if legacy_settings_exists:
                conn.execute(
                    """
                    insert into trading_account (id, name, account_type, currency, status, equity, cash, available_cash)
                    select 1, 'A股交易规划', 'PLANNING', 'CNY', 'ACTIVE',
                           account_equity, available_cash, available_cash
                    from trade_settings where id = 1
                    on conflict (id) do nothing
                    """
                )
            conn.execute(
                """
                insert into trading_account (id, name, account_type, currency, status, equity, cash, available_cash)
                values (1, 'A股交易规划', 'PLANNING', 'CNY', 'ACTIVE', 100000, 60000, 60000)
                on conflict (id) do nothing
                """
            )
            if legacy_settings_exists:
                conn.execute(
                    """
                    insert into risk_profile (id, account_id, default_trade_risk_pct, max_trade_risk_pct,
                        max_single_position_pct, max_total_exposure_pct)
                    select 1, 1, default_risk_pct, default_risk_pct,
                           max_single_position_pct, max_total_position_pct
                    from trade_settings where id = 1
                    on conflict (account_id) do nothing
                    """
                )
            conn.execute(
                """
                insert into risk_profile (id, account_id, default_trade_risk_pct, max_trade_risk_pct,
                    max_single_position_pct, max_total_exposure_pct)
                values (1, 1, 0.008, 0.02, 0.12, 0.8)
                on conflict (account_id) do nothing
                """
            )
            conn.execute("""
                do $$
                declare p record; new_id integer;
                begin
                    for p in select bp.* from broker_account_profile bp
                        left join trading_account a on a.broker_profile_id = bp.id
                        where a.id is null order by bp.id loop
                        select coalesce(max(id), 0) + 1 into new_id from trading_account;
                        insert into trading_account
                            (id, name, account_type, broker, broker_account_id, broker_account_key,
                             broker_strategy_id, broker_node_url, broker_token_env, currency, status,
                             equity, cash, available_cash, broker_profile_id, is_default)
                        values (new_id, p.name, p.account_type, p.broker, p.broker_account_id,
                                p.broker_account_key, p.broker_strategy_id, p.broker_node_url,
                                p.broker_token_env, 'CNY', p.status, 0, 0, 0, p.id,
                                p.is_default and not exists(select 1 from trading_account where is_default));
                        insert into risk_profile (id, account_id, default_trade_risk_pct, max_trade_risk_pct,
                            max_single_position_pct, max_total_exposure_pct)
                        values (new_id, new_id, 0.008, 0.02, 0.12, 0.8)
                        on conflict (account_id) do nothing;
                    end loop;
                end $$;
            """)

    @staticmethod
    def _row(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if not row:
            return None
        result = dict(row)
        for key, value in result.items():
            if hasattr(value, "isoformat"):
                result[key] = value.isoformat()
            elif isinstance(value, bool):
                result[key] = value
            elif key not in {"id", "account_id", "broker_profile_id", "quantity", "available_quantity"} and isinstance(value, (int, float, Decimal)):
                result[key] = float(value)
        return result

    def get_account(self, account_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("select * from trading_account where id = %s", (account_id,)).fetchone()
        result = self._row(row)
        if not result:
            raise RuntimeError("trading_account row is missing")
        return result

    def list_broker_accounts(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("""
                select p.*, a.id as account_id, a.configuration_confirmed,
                       a.status as business_status, a.is_default as account_is_default
                from broker_account_profile p
                left join trading_account a on a.broker_profile_id = p.id
                order by p.is_default desc, p.id
            """).fetchall()
        return [self._row(row) for row in rows]

    def get_broker_account(self, account_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("""
                select p.*, a.id as account_id, a.configuration_confirmed,
                       a.status as business_status, a.is_default as account_is_default
                from trading_account a join broker_account_profile p on p.id = a.broker_profile_id
                where a.id = %s
            """, (account_id,)).fetchone()
        return self._row(row)

    def list_accounts(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("""
                select a.id, a.name, a.account_type, a.status,
                       a.configuration_confirmed, a.is_default,
                       p.broker, p.broker_account_id, p.broker_strategy_id,
                       a.broker_connection_status as connection_status,
                       a.broker_connection_checked_at
                from trading_account a
                left join broker_account_profile p on p.id = a.broker_profile_id
                order by a.is_default desc, a.id
            """).fetchall()
        return [self._row(row) for row in rows]

    def set_default_account(self, account_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            if not conn.execute("select 1 from trading_account where id=%s", (account_id,)).fetchone():
                raise TradingDataValidationError("Trading account not found")
            conn.execute("update trading_account set is_default=false")
            row = conn.execute("update trading_account set is_default=true, updated_at=now() where id=%s returning *", (account_id,)).fetchone()
        return self._row(row)

    def create_broker_account(self, data: dict[str, Any]) -> dict[str, Any]:
        required = ("name", "account_type", "broker", "broker_account_id", "broker_strategy_id", "broker_node_url", "broker_gm_token")
        missing = [field for field in required if not str(data.get(field) or "").strip()]
        if missing:
            raise TradingDataValidationError(f"missing broker account fields: {', '.join(missing)}")
        if data["account_type"] not in {"SIMULATION", "LIVE"}:
            raise TradingDataValidationError("broker account type must be SIMULATION or LIVE")
        parsed = urlparse(str(data["broker_node_url"]))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or not parsed.port:
            raise TradingDataValidationError("broker_node_url must include http(s), host, and port")
        existing = self.list_broker_accounts()
        prefix = "guotou" if "国投" in str(data["broker"]) else (re.sub(r"[^a-z0-9]+", "", str(data["broker"]).lower()) or "broker")
        mode = "sim" if data["account_type"] == "SIMULATION" else "live"
        index = 1
        used = {item["broker_account_key"] for item in existing}
        while f"{prefix}_{mode}_{index:02d}" in used:
            index += 1
        key = f"{prefix}_{mode}_{index:02d}"
        with self.connect() as conn:
            row = conn.execute(
                """
                insert into broker_account_profile(name, account_type, broker, broker_account_id,
                    broker_account_key, broker_strategy_id, broker_node_url, broker_token_env, broker_gm_token, status, is_default)
                values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *
                """,
                (data["name"], data["account_type"], data["broker"], data["broker_account_id"], key,
                 data["broker_strategy_id"], data["broker_node_url"], "BROKER_NODE_API_TOKEN", data["broker_gm_token"], data.get("status", "ACTIVE"), not existing),
            ).fetchone()
            profile_id = int(row["id"])
            next_id = conn.execute("select coalesce(max(id), 0) + 1 as id from trading_account").fetchone()["id"]
            conn.execute("""
                insert into trading_account
                    (id, name, account_type, broker, broker_account_id, broker_account_key,
                     broker_strategy_id, broker_node_url, broker_token_env, currency, status,
                     configuration_confirmed, equity, cash, available_cash, broker_profile_id, is_default)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,'CNY',%s,false,0,0,0,%s,%s)
            """, (next_id, data["name"], data["account_type"], data["broker"], data["broker_account_id"],
                   key, data["broker_strategy_id"], data["broker_node_url"], "BROKER_NODE_API_TOKEN",
                   data.get("status", "ACTIVE"), profile_id, not existing and not conn.execute("select 1 from trading_account where is_default=true").fetchone()))
            conn.execute("insert into risk_profile (id, account_id, default_trade_risk_pct, max_trade_risk_pct, max_single_position_pct, max_total_exposure_pct) values (%s,%s,0.008,0.02,0.12,0.8) on conflict (account_id) do nothing", (next_id, next_id))
            row = dict(row)
            row["account_id"] = next_id
        return self._row(row)

    def delete_broker_account(self, account_id: int) -> bool:
        with self.connect() as conn:
            account = conn.execute("select id, broker_profile_id, is_default from trading_account where broker_profile_id=%s for update", (account_id,)).fetchone()
            if not account or not account["broker_profile_id"]:
                return False
            dependencies = conn.execute("""
                select (select count(*) from trades where account_id=%s) as trades,
                       (select count(*) from planning_position where account_id=%s) as positions,
                       (select count(*) from execution_plan where account_id=%s) as plans,
                       (select count(*) from trading_order where account_id=%s) as orders
            """, (account_id, account_id, account_id, account_id)).fetchone()
            if any(int(dependencies[key]) for key in ("trades", "positions", "plans", "orders")):
                raise TradingDataValidationError("账户已有交易数据，不能删除；请先完成数据归档")
            conn.execute("delete from trading_account where id=%s", (account_id,))
            row = conn.execute("delete from broker_account_profile where id=%s returning id", (account["broker_profile_id"],)).fetchone()
            if account["is_default"]:
                conn.execute("""update trading_account set is_default=true where id=(select id from trading_account order by id limit 1)""")
        return bool(row)

    def update_broker_account(self, account_id: int, data: dict[str, Any]) -> dict[str, Any]:
        required = ("name", "account_type", "broker", "broker_account_id", "broker_strategy_id", "broker_node_url", "broker_gm_token")
        missing = [field for field in required if not str(data.get(field) or "").strip()]
        if missing:
            raise TradingDataValidationError(f"missing broker account fields: {', '.join(missing)}")
        if data["account_type"] not in {"SIMULATION", "LIVE"}:
            raise TradingDataValidationError("broker account type must be SIMULATION or LIVE")
        parsed = urlparse(str(data["broker_node_url"]))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or not parsed.port:
            raise TradingDataValidationError("broker_node_url must include http(s), host, and port")
        with self.connect() as conn:
            row = conn.execute(
                """update broker_account_profile set name=%s, account_type=%s, broker=%s,
                    broker_account_id=%s, broker_strategy_id=%s, broker_node_url=%s,
                    broker_token_env='BROKER_NODE_API_TOKEN', broker_gm_token=%s, updated_at=now() where id=%s returning *""",
                (data["name"], data["account_type"], data["broker"], data["broker_account_id"],
                 data["broker_strategy_id"], data["broker_node_url"], data["broker_gm_token"], account_id),
            ).fetchone()
        if not row:
            raise TradingDataValidationError("Broker account not found")
        with self.connect() as conn:
            conn.execute("""update trading_account a set name=%s, account_type=%s, broker=%s,
                broker_account_id=%s, broker_strategy_id=%s, broker_node_url=%s,
                status=%s, configuration_confirmed=false, updated_at=now()
                from broker_account_profile p where a.broker_profile_id=p.id and p.id=%s""",
                (data["name"], data["account_type"], data["broker"], data["broker_account_id"],
                 data["broker_strategy_id"], data["broker_node_url"], data.get("status", "ACTIVE"), account_id))
        return self._row(row)

    def save_account(self, account_id: int, data: dict[str, Any]) -> dict[str, Any]:
        current = self.get_account(account_id)
        merged = {**current, **data}
        if merged.get("account_type") not in {"PLANNING", "SIMULATION", "LIVE"}:
            raise TradingDataValidationError("account_type is invalid")
        if merged.get("status") not in {"ACTIVE", "DISCONNECTED", "LOCKED"}:
            raise TradingDataValidationError("status is invalid")
        if merged["account_type"] in {"SIMULATION", "LIVE"}:
            for field in ("broker", "broker_account_id", "broker_account_key", "broker_strategy_id", "broker_node_url", "broker_token_env"):
                if not str(merged.get(field) or "").strip():
                    raise TradingDataValidationError(f"{field} is required for broker account")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(merged["broker_token_env"])):
                raise TradingDataValidationError("broker_token_env must be a valid environment variable name")
        for field in ("equity", "cash", "available_cash"):
            _number(merged.get(field), field)
        if not str(merged.get("name") or "").strip():
            raise TradingDataValidationError("name is required")
        with self.connect() as conn:
            row = conn.execute(
                """
                update trading_account set name=%s, account_type=%s, broker=%s, broker_account_id=%s,
                    broker_account_key=%s, broker_strategy_id=%s, broker_node_url=%s,
                    broker_token_env=%s,
                    currency=%s, status=%s, equity=%s, cash=%s, available_cash=%s,
                    realized_pnl=%s, unrealized_pnl=%s, configuration_confirmed=true, updated_at=now()
                where id=%s returning *
                """,
                (merged["name"], merged["account_type"], merged.get("broker"), merged.get("broker_account_id"),
                 merged.get("broker_account_key"), merged.get("broker_strategy_id"), merged.get("broker_node_url"),
                 merged.get("broker_token_env"),
                 merged["currency"], merged["status"], merged["equity"], merged["cash"], merged["available_cash"],
                 merged.get("realized_pnl", 0), merged.get("unrealized_pnl", 0), account_id),
            ).fetchone()
        result = self._row(row)
        if not result:
            raise RuntimeError("trading_account row is missing")
        return result

    def get_risk_profile(self, account_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("select * from risk_profile where account_id=%s", (account_id,)).fetchone()
        result = self._row(row)
        if not result:
            raise RuntimeError("risk_profile row is missing")
        return result

    def save_risk_profile(self, account_id: int, data: dict[str, Any]) -> dict[str, Any]:
        current = self.get_risk_profile(account_id)
        merged = {**current, **data}
        for field in ("default_trade_risk_pct", "max_trade_risk_pct", "max_single_position_pct", "max_total_exposure_pct"):
            _number(merged.get(field), field, positive=True)
        if merged["default_trade_risk_pct"] > merged["max_trade_risk_pct"]:
            raise TradingDataValidationError("default_trade_risk_pct cannot exceed max_trade_risk_pct")
        with self.connect() as conn:
            row = conn.execute(
                """
                update risk_profile set default_trade_risk_pct=%s, max_trade_risk_pct=%s,
                    max_single_position_pct=%s, max_total_exposure_pct=%s, configuration_confirmed=true, updated_at=now()
                where account_id=%s returning *
                """,
                (merged["default_trade_risk_pct"], merged["max_trade_risk_pct"],
                 merged["max_single_position_pct"], merged["max_total_exposure_pct"], account_id),
            ).fetchone()
        result = self._row(row)
        if not result:
            raise RuntimeError("risk_profile row is missing")
        return result

    def list_positions(self, account_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("select * from planning_position where account_id=%s order by symbol", (account_id,)).fetchall()
        result = []
        for row in rows:
            item = self._row(row)
            item["market_value"] = item["quantity"] * item["market_price"]
            item["unrealized_pnl"] = item["quantity"] * (item["market_price"] - item["average_cost"])
            result.append(item)
        return result

    def save_position(self, account_id: int, data: dict[str, Any]) -> dict[str, Any]:
        position = PlanningPosition(**data)
        if not position.symbol.strip() or not position.security_name.strip():
            raise TradingDataValidationError("symbol and security_name are required")
        if position.quantity < 0 or position.available_quantity < 0 or position.available_quantity > position.quantity:
            raise TradingDataValidationError("position quantities are invalid")
        _number(position.average_cost, "average_cost", positive=True)
        _number(position.market_price, "market_price", positive=True)
        if position.current_risk_reference_price is not None:
            _number(position.current_risk_reference_price, "current_risk_reference_price", positive=True)
        with self.connect() as conn:
            row = conn.execute(
                """
                insert into planning_position (account_id, symbol, security_name, quantity, available_quantity,
                    average_cost, market_price, current_risk_reference_price, risk_note, updated_at)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                on conflict (account_id, symbol) do update set security_name=excluded.security_name,
                    quantity=excluded.quantity, available_quantity=excluded.available_quantity,
                    average_cost=excluded.average_cost, market_price=excluded.market_price,
                    current_risk_reference_price=excluded.current_risk_reference_price,
                    risk_note=excluded.risk_note, updated_at=now()
                returning *
                """,
                (account_id, position.symbol.strip(), position.security_name.strip(), position.quantity, position.available_quantity,
                 position.average_cost, position.market_price, position.current_risk_reference_price, position.risk_note),
            ).fetchone()
        result = self._row(row)
        result["market_value"] = result["quantity"] * result["market_price"]
        result["unrealized_pnl"] = result["quantity"] * (result["market_price"] - result["average_cost"])
        return result

    def delete_position(self, account_id: int, symbol: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("delete from planning_position where account_id=%s and symbol=%s returning id", (account_id, symbol)).fetchone()
        return bool(row)

    def overview(self, account_id: int) -> dict[str, Any]:
        account = self.get_account(account_id)
        positions = self.list_positions(account_id)
        market_value = sum(item["market_value"] for item in positions)
        unrealized_pnl = sum(item["unrealized_pnl"] for item in positions)
        equity = account["equity"]
        return {
            "account": {**account, "market_value": market_value, "unrealized_pnl": unrealized_pnl,
                        "total_exposure_pct": market_value / equity if equity else 0},
            "risk_profile": self.get_risk_profile(account_id),
            "positions": positions,
            "counts": {"positions": len(positions)},
        }

    def trade_plan_settings(self, account_id: int) -> dict[str, Any]:
        account = self.get_account(account_id)
        risk = self.get_risk_profile(account_id)
        market_value = sum(item["market_value"] for item in self.list_positions(account_id))
        return {
            "account_equity": account["equity"],
            "available_cash": account["available_cash"],
            "current_invested_amount": market_value,
            "default_risk_pct": risk["default_trade_risk_pct"],
            "max_single_position_pct": risk["max_single_position_pct"],
            "max_total_position_pct": risk["max_total_exposure_pct"],
            "max_trade_risk_pct": risk["max_trade_risk_pct"],
            "is_ready": self.is_trade_plan_configuration_ready(account, risk),
        }

    @staticmethod
    def is_trade_plan_configuration_ready(account: dict[str, Any], risk: dict[str, Any]) -> bool:
        """Only actual planning inputs gate TradePlan; broker connection never does."""
        try:
            equity = _number(account.get("equity"), "equity", positive=True)
            _number(account.get("cash"), "cash")
            _number(account.get("available_cash"), "available_cash")
            default_risk = _number(risk.get("default_trade_risk_pct"), "default_trade_risk_pct", positive=True)
            maximum_risk = _number(risk.get("max_trade_risk_pct"), "max_trade_risk_pct", positive=True)
            _number(risk.get("max_single_position_pct"), "max_single_position_pct", positive=True)
            _number(risk.get("max_total_exposure_pct"), "max_total_exposure_pct", positive=True)
        except TradingDataValidationError:
            return False
        return bool(str(account.get("name") or "").strip()) and equity > 0 and default_risk <= maximum_risk

    def trade_plan_context(self, account_id: int) -> dict[str, Any]:
        overview = self.overview(account_id)
        account = overview["account"]
        risk = overview["risk_profile"]
        return {
            "account": account,
            "risk_profile": risk,
            "current_invested_amount": overview["account"]["market_value"],
            "current_exposure_pct": overview["account"]["total_exposure_pct"],
            "is_ready": self.is_trade_plan_configuration_ready(account, risk),
        }
