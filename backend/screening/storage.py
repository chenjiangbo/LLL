from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from backend.screening.utils import json_dumps


@dataclass
class PostgresScreeningStore:
    database_url: str

    def __post_init__(self) -> None:
        if not self.database_url:
            raise ValueError("database_url is required for PostgresScreeningStore")
        self.init_schema()

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                create table if not exists screening_asset_master (
                    asset_code text primary key,
                    asset_type text not null,
                    name text not null,
                    list_date text,
                    market text,
                    raw_json jsonb not null,
                    updated_at timestamptz not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_daily_bar (
                    asset_code text not null,
                    asset_type text not null,
                    trade_date text not null,
                    open numeric not null,
                    high numeric not null,
                    low numeric not null,
                    close numeric not null,
                    pre_close numeric,
                    pct_chg numeric,
                    vol numeric not null,
                    amount numeric not null,
                    raw_json jsonb not null,
                    updated_at timestamptz not null,
                    primary key (asset_code, trade_date)
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_adj_factor (
                    asset_code text not null,
                    asset_type text not null,
                    trade_date text not null,
                    adj_factor numeric not null,
                    raw_json jsonb not null,
                    updated_at timestamptz not null,
                    primary key (asset_code, trade_date)
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_daily_basic (
                    asset_code text not null,
                    trade_date text not null,
                    turnover_rate numeric,
                    turnover_rate_f numeric,
                    total_mv numeric,
                    circ_mv numeric,
                    limit_status text,
                    raw_json jsonb not null,
                    updated_at timestamptz not null,
                    primary key (asset_code, trade_date)
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_weekly_bar (
                    asset_code text not null,
                    asset_type text not null,
                    trade_date text not null,
                    open numeric not null,
                    high numeric not null,
                    low numeric not null,
                    close numeric not null,
                    pre_close numeric,
                    pct_chg numeric,
                    vol numeric not null,
                    amount numeric not null,
                    source text not null,
                    raw_json jsonb not null,
                    updated_at timestamptz not null,
                    primary key (asset_code, trade_date, source)
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_technical_features (
                    asset_code text not null,
                    asset_type text not null,
                    trade_date text not null,
                    features_json jsonb not null,
                    ruleset_version text not null,
                    updated_at timestamptz not null,
                    primary key (asset_code, trade_date, ruleset_version)
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_candidate_snapshot (
                    trade_date text not null,
                    asset_code text not null,
                    asset_type text not null,
                    primary_pool text not null,
                    stage text not null,
                    score numeric not null,
                    pools_json jsonb not null,
                    reasons_json jsonb not null,
                    risks_json jsonb not null,
                    status_change text not null,
                    ruleset_version text not null,
                    updated_at timestamptz not null,
                    primary key (trade_date, asset_code, ruleset_version)
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_candidate_history (
                    id bigserial primary key,
                    trade_date text not null,
                    asset_code text not null,
                    asset_type text not null,
                    pool text not null,
                    stage text not null,
                    score numeric not null,
                    reason_json jsonb not null,
                    risk_json jsonb not null,
                    status_change text not null,
                    ruleset_version text not null,
                    created_at timestamptz not null,
                    unique(trade_date, asset_code, pool, ruleset_version)
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_user_watchlist (
                    asset_code text primary key,
                    asset_type text not null,
                    status text not null,
                    note text,
                    snooze_until text,
                    updated_at timestamptz not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_manual_pool_selection (
                    trade_date text not null,
                    asset_code text not null,
                    asset_type text not null,
                    pool text not null,
                    action text not null,
                    note text,
                    selected_at timestamptz not null,
                    primary key (trade_date, asset_code, pool)
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_config (
                    ruleset_version text primary key,
                    config_json jsonb not null,
                    created_at timestamptz not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_sync_log (
                    id bigserial primary key,
                    trade_date text not null,
                    sync_type text not null,
                    status text not null,
                    message text,
                    created_at timestamptz not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_min_bar (
                    asset_code text not null,
                    asset_type text not null,
                    trade_time text not null,
                    open numeric not null,
                    high numeric not null,
                    low numeric not null,
                    close numeric not null,
                    vol numeric not null,
                    amount numeric not null,
                    freq text not null default '30min',
                    raw_json jsonb not null,
                    updated_at timestamptz not null,
                    primary key (asset_code, trade_time, freq)
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_kline_drawings (
                    asset_code text primary key,
                    drawings_json jsonb not null,
                    updated_at timestamptz not null
                )
                """
            )
            conn.execute("create index if not exists idx_screening_daily_bar_date on screening_daily_bar(trade_date)")
            conn.execute("create index if not exists idx_screening_weekly_bar_date on screening_weekly_bar(trade_date)")
            conn.execute("create index if not exists idx_screening_min_bar_code_time on screening_min_bar(asset_code, trade_time, freq)")
            conn.execute("create index if not exists idx_screening_candidates_date on screening_candidate_snapshot(trade_date)")
            conn.execute("create index if not exists idx_screening_manual_pool on screening_manual_pool_selection(pool, trade_date)")


            # 动态列迁移 for screening_run
            conn.execute("alter table screening_run add column if not exists run_name text;")
            conn.execute("alter table screening_run add column if not exists notes text;")
            conn.execute("alter table screening_run add column if not exists universe_type text default 'ALL';")
            conn.execute("alter table screening_run add column if not exists universe_params_json jsonb;")
            conn.execute("alter table screening_run add column if not exists data_freshness_json jsonb;")


            # ── A-Pre V2 / Early Turn 早期转强实验专属表 ────────────────────────
            conn.execute(
                """
                create table if not exists early_turn_run (
                    run_id text primary key,
                    trade_date text not null,
                    config_version text not null,
                    started_at timestamptz not null,
                    finished_at timestamptz,
                    status text not null default 'RUNNING',
                    error_message text,
                    summary_json jsonb
                )
                """
            )
            conn.execute(
                """
                create table if not exists early_turn_result (
                    run_id text not null,
                    ts_code text not null,
                    trade_date text not null,
                    total_score numeric not null,
                    state text not null,
                    background_type text not null,
                    selected boolean not null default false,
                    is_overextended boolean not null default false,
                    features_json jsonb not null,
                    score_detail_json jsonb not null,
                    reasons_json jsonb not null,
                    first_selected_date text,
                    created_at timestamptz not null,
                    primary key (run_id, ts_code)
                )
                """
            )
            conn.execute(
                """
                create table if not exists early_turn_positive_sample (
                    sample_id bigserial primary key,
                    ts_code text not null,
                    target_date text not null,
                    sample_name text not null,
                    note text,
                    label_version text not null default 'v1.0',
                    created_at timestamptz not null,
                    unique (ts_code, target_date, label_version)
                )
                """
            )
            conn.execute("create index if not exists idx_early_turn_res_date on early_turn_result(trade_date)")
            conn.execute("create index if not exists idx_early_turn_res_state on early_turn_result(run_id, state)")

            # ── P1 审计骨架新表 ──────────────────────────────────────────────
            conn.execute(
                """
                create table if not exists screening_run (
                    run_id text primary key,
                    trade_date text not null,
                    config_version text not null,
                    data_version text not null,
                    started_at timestamptz not null,
                    finished_at timestamptz,
                    status text not null default 'RUNNING',
                    error_message text,
                    summary_json jsonb
                )
                """
            )
            conn.execute(
                """
                create table if not exists pool_candidate_snapshot_v2 (
                    run_id text not null,
                    ts_code text not null,
                    pool_code text not null,
                    pool_source_score numeric,
                    source_payload jsonb,
                    created_at timestamptz not null,
                    primary key (run_id, ts_code, pool_code)
                )
                """
            )
            conn.execute(
                """
                create table if not exists stage_snapshot (
                    run_id text not null,
                    ts_code text not null,
                    pool_code text not null,
                    stage text not null,
                    status text not null,
                    score numeric,
                    rank_all integer,
                    rank_pool integer,
                    rank_industry integer,
                    score_detail_json jsonb,
                    evaluated_at timestamptz not null,
                    primary key (run_id, ts_code, pool_code, stage)
                )
                """
            )
            conn.execute(
                """
                create table if not exists stage_reason (
                    id bigserial primary key,
                    run_id text not null,
                    ts_code text not null,
                    pool_code text not null,
                    stage text not null,
                    reason_code text not null,
                    severity text not null default 'HARD',
                    actual_value numeric,
                    threshold_value numeric,
                    message text,
                    created_at timestamptz not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists factor_snapshot (
                    trade_date text not null,
                    ts_code text not null,
                    factor_name text not null,
                    factor_value numeric,
                    data_quality text not null default 'OK',
                    factor_version text not null,
                    updated_at timestamptz not null,
                    primary key (trade_date, ts_code, factor_name, factor_version)
                )
                """
            )
            conn.execute(
                """
                create table if not exists industry_membership_history (
                    ts_code text not null,
                    l1_code text,
                    l1_name text,
                    l2_code text,
                    l2_name text,
                    l3_code text,
                    l3_name text,
                    in_date text,
                    out_date text,
                    source_version text not null,
                    updated_at timestamptz not null,
                    primary key (ts_code, source_version)
                )
                """
            )
            conn.execute(
                """
                create table if not exists industry_factor_snapshot (
                    trade_date text not null,
                    industry_code text not null,
                    industry_level integer not null,
                    industry_name text,
                    ret_1d numeric,
                    ret_5d numeric,
                    ret_20d numeric,
                    ret_60d numeric,
                    up_count integer,
                    down_count integer,
                    total_count integer,
                    ind_trend_score numeric,
                    raw_json jsonb,
                    updated_at timestamptz not null,
                    primary key (trade_date, industry_code)
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_config_v2 (
                    config_version text primary key,
                    effective_from text not null,
                    config_yaml text not null,
                    created_at timestamptz not null,
                    note text
                )
                """
            )
            conn.execute("create index if not exists idx_screening_run_date on screening_run(trade_date)")
            conn.execute("create index if not exists idx_pool_candidate_v2_run on pool_candidate_snapshot_v2(run_id)")
            conn.execute("create index if not exists idx_stage_snapshot_run_ts on stage_snapshot(run_id, ts_code)")
            conn.execute("create index if not exists idx_stage_reason_run_ts on stage_reason(run_id, ts_code)")
            conn.execute("create index if not exists idx_factor_snapshot_date on factor_snapshot(trade_date, factor_name)")
            conn.execute("create index if not exists idx_industry_membership_ts on industry_membership_history(ts_code)")
            conn.execute("create index if not exists idx_industry_factor_date on industry_factor_snapshot(trade_date)")
            conn.commit()

    def save_assets(self, df: pd.DataFrame) -> None:
        now = _now()
        rows = [
            (
                record["asset_code"],
                record["asset_type"],
                record["name"],
                record.get("list_date"),
                record.get("market"),
                json_dumps(record),
                now,
            )
            for record in df.to_dict(orient="records")
        ]
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into screening_asset_master (
                        asset_code, asset_type, name, list_date, market, raw_json, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict(asset_code) do update set
                        asset_type = excluded.asset_type,
                        name = excluded.name,
                        list_date = excluded.list_date,
                        market = excluded.market,
                        raw_json = excluded.raw_json,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
            conn.commit()

    def save_daily_bars(self, df: pd.DataFrame) -> None:
        now = _now()
        rows = []
        for record in df.to_dict(orient="records"):
            rows.append(
                (
                    record["asset_code"],
                    record["asset_type"],
                    record["trade_date"],
                    float(record["open"]),
                    float(record["high"]),
                    float(record["low"]),
                    float(record["close"]),
                    _nullable_float(record.get("pre_close")),
                    _nullable_float(record.get("pct_chg")),
                    float(record["vol"]),
                    float(record["amount"]),
                    json_dumps(record),
                    now,
                )
            )
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into screening_daily_bar (
                        asset_code, asset_type, trade_date, open, high, low, close, pre_close,
                        pct_chg, vol, amount, raw_json, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict(asset_code, trade_date) do update set
                        asset_type = excluded.asset_type,
                        open = excluded.open,
                        high = excluded.high,
                        low = excluded.low,
                        close = excluded.close,
                        pre_close = excluded.pre_close,
                        pct_chg = excluded.pct_chg,
                        vol = excluded.vol,
                        amount = excluded.amount,
                        raw_json = excluded.raw_json,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
            conn.commit()

    def save_weekly_bars(self, df: pd.DataFrame, source: str) -> None:
        now = _now()
        rows = []
        for record in df.to_dict(orient="records"):
            rows.append(
                (
                    record["asset_code"],
                    record["asset_type"],
                    record["trade_date"],
                    float(record["open"]),
                    float(record["high"]),
                    float(record["low"]),
                    float(record["close"]),
                    _nullable_float(record.get("pre_close")),
                    _nullable_float(record.get("pct_chg")),
                    float(record["vol"]),
                    float(record["amount"]),
                    source,
                    json_dumps(record),
                    now,
                )
            )
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into screening_weekly_bar (
                        asset_code, asset_type, trade_date, open, high, low, close, pre_close,
                        pct_chg, vol, amount, source, raw_json, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict(asset_code, trade_date, source) do update set
                        asset_type = excluded.asset_type,
                        open = excluded.open,
                        high = excluded.high,
                        low = excluded.low,
                        close = excluded.close,
                        pre_close = excluded.pre_close,
                        pct_chg = excluded.pct_chg,
                        vol = excluded.vol,
                        amount = excluded.amount,
                        raw_json = excluded.raw_json,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
            conn.commit()

    def save_adj_factors(self, df: pd.DataFrame) -> None:
        now = _now()
        rows = [
            (
                record["asset_code"],
                record["asset_type"],
                record["trade_date"],
                float(record["adj_factor"]),
                json_dumps(record),
                now,
            )
            for record in df.to_dict(orient="records")
        ]
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into screening_adj_factor (
                        asset_code, asset_type, trade_date, adj_factor, raw_json, updated_at
                    )
                    values (%s, %s, %s, %s, %s::jsonb, %s)
                    on conflict(asset_code, trade_date) do update set
                        asset_type = excluded.asset_type,
                        adj_factor = excluded.adj_factor,
                        raw_json = excluded.raw_json,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
            conn.commit()

    def save_daily_basic(self, df: pd.DataFrame) -> None:
        now = _now()
        rows = []
        for record in df.to_dict(orient="records"):
            rows.append(
                (
                    record["asset_code"],
                    record["trade_date"],
                    _nullable_float(record.get("turnover_rate")),
                    _nullable_float(record.get("turnover_rate_f")),
                    _nullable_float(record.get("total_mv")),
                    _nullable_float(record.get("circ_mv")),
                    record.get("limit_status"),
                    json_dumps(record),
                    now,
                )
            )
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into screening_daily_basic (
                        asset_code, trade_date, turnover_rate, turnover_rate_f, total_mv,
                        circ_mv, limit_status, raw_json, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict(asset_code, trade_date) do update set
                        turnover_rate = excluded.turnover_rate,
                        turnover_rate_f = excluded.turnover_rate_f,
                        total_mv = excluded.total_mv,
                        circ_mv = excluded.circ_mv,
                        limit_status = excluded.limit_status,
                        raw_json = excluded.raw_json,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
            conn.commit()

    def load_assets(self) -> pd.DataFrame:
        with self.connect() as conn:
            rows = conn.execute("select * from screening_asset_master").fetchall()
        return pd.DataFrame([dict(row) for row in rows])

    def load_history(self, end_date: str, min_start_date: str | None = None) -> pd.DataFrame:
        query = """
            select b.asset_code, b.asset_type, b.trade_date, b.open, b.high, b.low, b.close,
                   b.pre_close, b.pct_chg, b.vol, b.amount, a.name, a.list_date, a.market,
                   f.adj_factor, d.turnover_rate, d.turnover_rate_f, d.total_mv, d.circ_mv,
                   d.limit_status
            from screening_daily_bar b
            join screening_asset_master a on a.asset_code = b.asset_code
            left join screening_adj_factor f on f.asset_code = b.asset_code and f.trade_date = b.trade_date
            left join screening_daily_basic d on d.asset_code = b.asset_code and d.trade_date = b.trade_date
            where b.trade_date <= %s
        """
        params: list[Any] = [end_date]
        if min_start_date:
            query += " and b.trade_date >= %s"
            params.append(min_start_date)
        query += " order by b.asset_code, b.trade_date"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return pd.DataFrame([dict(row) for row in rows])

    def has_daily_data(self, trade_date: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                select
                    (select count(*) from screening_daily_bar where trade_date = %s and asset_type = 'stock') as stock_daily,
                    (select count(*) from screening_adj_factor where trade_date = %s and asset_type = 'stock') as stock_adj,
                    (select count(*) from screening_daily_basic where trade_date = %s) as daily_basic
                """,
                (trade_date, trade_date, trade_date),
            ).fetchone()
        # 必须至少有 4000 只全量股票日线完备，才认可该日为完整成功数据
        return int(row["stock_daily"] or 0) >= 4000 and int(row["stock_adj"] or 0) >= 4000 and int(row["daily_basic"] or 0) >= 4000

    def has_30m_data(self, trade_date: str) -> bool:
        with self.connect() as conn:
            formatted_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}" if len(trade_date) == 8 else trade_date
            row = conn.execute(
                "select count(*) as cnt from screening_min_bar where trade_time >= %s and freq in ('30m', '30min')",
                (formatted_date,),
            ).fetchone()
        return int(row["cnt"] or 0) >= 4000

    def has_weekly_data(self, trade_date: str, source: str = "tushare.weekly") -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                select count(*) as rows
                from screening_weekly_bar
                where trade_date = %s and source = %s
                """,
                (trade_date, source),
            ).fetchone()
        return int(row["rows"] or 0) > 0

    def load_candidate_primary(self, trade_date: str, ruleset_version: str) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select asset_code, primary_pool, stage, score
                from screening_candidate_snapshot
                where trade_date = %s and ruleset_version = %s
                """,
                (trade_date, ruleset_version),
            ).fetchall()
        return {row["asset_code"]: dict(row) for row in rows}

    def previous_candidate_date(self, trade_date: str, ruleset_version: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                select max(trade_date) as trade_date
                from screening_candidate_snapshot
                where trade_date < %s and ruleset_version = %s
                """,
                (trade_date, ruleset_version),
            ).fetchone()
        return row["trade_date"] if row and row["trade_date"] else None

    def latest_candidate_date(self, ruleset_version: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                select max(trade_date) as trade_date
                from screening_candidate_snapshot
                where ruleset_version = %s
                """,
                (ruleset_version,),
            ).fetchone()
        return row["trade_date"] if row and row["trade_date"] else None

    def candidate_dates(self, ruleset_version: str, limit: int = 20) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select trade_date
                from screening_candidate_snapshot
                where ruleset_version = %s
                group by trade_date
                order by trade_date desc
                limit %s
                """,
                (ruleset_version, limit),
            ).fetchall()
        return [row["trade_date"] for row in rows]

    def query_candidates(
        self,
        trade_date: str,
        ruleset_version: str,
        pools: set[str] | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        query_text: str | None = None,
        industry: str | None = None,
        only_selected: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [trade_date, ruleset_version]
        query = """
            select
                s.trade_date,
                s.asset_code,
                a.name,
                s.asset_type,
                s.primary_pool,
                s.stage,
                s.score,
                s.pools_json,
                s.reasons_json,
                s.risks_json,
                s.status_change,
                f.features_json,
                s.updated_at,
                m.action as manual_action,
                m.note as manual_note,
                a.raw_json->>'industry' as industry,
                a.raw_json
            from screening_candidate_snapshot s
            left join screening_asset_master a on a.asset_code = s.asset_code
            left join screening_technical_features f
                on f.asset_code = s.asset_code
                and f.trade_date = s.trade_date
                and f.ruleset_version = s.ruleset_version
            left join screening_manual_pool_selection m
                on m.trade_date = s.trade_date
                and m.asset_code = s.asset_code
                and m.pool = s.primary_pool
            where s.trade_date = %s and s.ruleset_version = %s
        """
        if only_selected:
            query += " and m.action = 'SELECT'"
        if pools:
            query += " and s.primary_pool = any(%s)"
            params.append(sorted(pools))
        if min_score is not None:
            query += " and s.score >= %s"
            params.append(min_score)
        if max_score is not None:
            query += " and s.score <= %s"
            params.append(max_score)
        if query_text:
            query += " and (s.asset_code ilike %s or a.name ilike %s or s.stage ilike %s or a.raw_json->>'industry' ilike %s)"
            pattern = f"%{query_text}%"
            params.extend([pattern, pattern, pattern, pattern])
        if industry:
            query += " and coalesce(nullif(a.raw_json->>'industry', ''), case when s.asset_type = 'etf' then coalesce(nullif(a.raw_json->>'fund_type', ''), 'ETF') else '\u672a\u5206\u7c7b' end) = %s"
            params.append(industry)
        query += """
            order by
                case s.primary_pool when 'A' then 1 when 'B' then 2 when 'C' then 3 else 9 end,
                case s.stage
                    when 'A3' then 1 when 'A2' then 2 when 'A1' then 3
                    when 'B3' then 1 when 'B2' then 2 when 'B1' then 3
                    when 'C3' then 1 when 'C2' then 2 when 'C1' then 3
                    else 9
                end,
                s.score desc,
                s.asset_code
            limit %s offset %s
        """
        params.extend([limit, offset])
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_candidate_row(row) for row in rows]

    def candidate_industry_counts(
        self,
        trade_date: str,
        ruleset_version: str,
        pools: set[str] | None = None,
    ) -> dict[str, int]:
        params: list[Any] = [trade_date, ruleset_version]
        query = """
            select
                coalesce(nullif(a.raw_json->>'industry', ''), case when s.asset_type = 'etf' then coalesce(nullif(a.raw_json->>'fund_type', ''), 'ETF') else '未分类' end) as industry_name,
                count(*) as total_count
            from screening_candidate_snapshot s
            left join screening_asset_master a on a.asset_code = s.asset_code
            where s.trade_date = %s and s.ruleset_version = %s
        """
        if pools:
            query += " and s.primary_pool = any(%s)"
            params.append(sorted(pools))
        query += " group by industry_name order by total_count desc"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return {row["industry_name"]: int(row["total_count"]) for row in rows}

    def filtered_candidate_count(
        self,
        trade_date: str,
        ruleset_version: str,
        pools: set[str] | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        query_text: str | None = None,
        industry: str | None = None,
        only_selected: bool = False,
    ) -> int:
        params: list[Any] = [trade_date, ruleset_version]
        query = """
            select count(*) as rows
            from screening_candidate_snapshot s
            left join screening_asset_master a on a.asset_code = s.asset_code
            left join screening_manual_pool_selection m
                on m.trade_date = s.trade_date
                and m.asset_code = s.asset_code
                and m.pool = s.primary_pool
            where s.trade_date = %s and s.ruleset_version = %s
        """
        if only_selected:
            query += " and m.action = 'SELECT'"
        if pools:
            query += " and s.primary_pool = any(%s)"
            params.append(sorted(pools))
        if min_score is not None:
            query += " and s.score >= %s"
            params.append(min_score)
        if max_score is not None:
            query += " and s.score <= %s"
            params.append(max_score)
        if query_text:
            query += " and (s.asset_code ilike %s or a.name ilike %s or s.stage ilike %s or a.raw_json->>'industry' ilike %s)"
            pattern = f"%{query_text}%"
            params.extend([pattern, pattern, pattern, pattern])
        if industry:
            query += " and coalesce(nullif(a.raw_json->>'industry', ''), case when s.asset_type = 'etf' then coalesce(nullif(a.raw_json->>'fund_type', ''), 'ETF') else '\u672a\u5206\u7c7b' end) = %s"
            params.append(industry)
        with self.connect() as conn:
            row = conn.execute(query, params).fetchone()
        return int(row["rows"])

    def candidate_counts(self, trade_date: str, ruleset_version: str) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select primary_pool, asset_type, count(*) as rows
                from screening_candidate_snapshot
                where trade_date = %s and ruleset_version = %s
                group by primary_pool, asset_type
                """,
                (trade_date, ruleset_version),
            ).fetchall()
            selected_row = conn.execute(
                """
                select count(*) as rows
                from screening_manual_pool_selection
                where trade_date = %s and action = 'SELECT'
                """,
                (trade_date,),
            ).fetchone()
        counts = {"total": 0, "stock": 0, "etf": 0, "A": 0, "B": 0, "C": 0, "selected": int(selected_row["rows"]) if selected_row else 0}
        for row in rows:
            value = int(row["rows"])
            counts["total"] += value
            counts[row["asset_type"]] = counts.get(row["asset_type"], 0) + value
            counts[row["primary_pool"]] = counts.get(row["primary_pool"], 0) + value
        return counts

    def screening_coverage(self, trade_date: str, ruleset_version: str) -> dict[str, dict[str, int]]:
        result = {
            "listed": {"stock": 0, "etf": 0},
            "daily": {"stock": 0, "etf": 0},
            "scanned": {"stock": 0, "etf": 0},
        }
        with self.connect() as conn:
            listed = conn.execute(
                "select asset_type, count(*) as rows from screening_asset_master group by asset_type"
            ).fetchall()
            daily = conn.execute(
                """
                select asset_type, count(distinct asset_code) as rows
                from screening_daily_bar
                where trade_date = %s
                group by asset_type
                """,
                (trade_date,),
            ).fetchall()
            scanned = conn.execute(
                """
                select asset_type, count(*) as rows
                from screening_technical_features
                where trade_date = %s and ruleset_version = %s
                group by asset_type
                """,
                (trade_date, ruleset_version),
            ).fetchall()
        for label, rows in (("listed", listed), ("daily", daily), ("scanned", scanned)):
            for row in rows:
                result[label][row["asset_type"]] = int(row["rows"])
        return result

    def save_features(self, features: list[dict[str, Any]], ruleset_version: str) -> None:
        now = _now()
        rows = [
            (
                item["asset_code"],
                item["asset_type"],
                item["trade_date"],
                json_dumps(item["features"]),
                ruleset_version,
                now,
            )
            for item in features
        ]
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into screening_technical_features (
                        asset_code, asset_type, trade_date, features_json, ruleset_version, updated_at
                    )
                    values (%s, %s, %s, %s::jsonb, %s, %s)
                    on conflict(asset_code, trade_date, ruleset_version) do update set
                        features_json = excluded.features_json,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
            conn.commit()

    def save_candidates(self, trade_date: str, candidates: list[dict[str, Any]], ruleset_version: str) -> None:
        now = _now()
        snapshot_rows = []
        history_rows = []
        for item in candidates:
            snapshot_rows.append(
                (
                    trade_date,
                    item["asset_code"],
                    item["asset_type"],
                    item["primary_pool"],
                    item["stage"],
                    float(item["score"]),
                    json_dumps(item["pools"]),
                    json_dumps(item["reasons"]),
                    json_dumps(item["risks"]),
                    item["status_change"],
                    ruleset_version,
                    now,
                )
            )
            for pool in item["pools"]:
                history_rows.append(
                    (
                        trade_date,
                        item["asset_code"],
                        item["asset_type"],
                        pool["pool"],
                        pool["stage"],
                        float(pool["score"]),
                        json_dumps(pool["reasons"]),
                        json_dumps(item["risks"]),
                        item["status_change"],
                        ruleset_version,
                        now,
                    )
                )
        with self.connect() as conn:
            conn.execute(
                "delete from screening_candidate_snapshot where trade_date = %s and ruleset_version = %s",
                (trade_date, ruleset_version),
            )
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into screening_candidate_snapshot (
                        trade_date, asset_code, asset_type, primary_pool, stage, score, pools_json,
                        reasons_json, risks_json, status_change, ruleset_version, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s)
                    """,
                    snapshot_rows,
                )
                cursor.executemany(
                    """
                    insert into screening_candidate_history (
                        trade_date, asset_code, asset_type, pool, stage, score, reason_json,
                        risk_json, status_change, ruleset_version, created_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                    on conflict(trade_date, asset_code, pool, ruleset_version) do update set
                        stage = excluded.stage,
                        score = excluded.score,
                        reason_json = excluded.reason_json,
                        risk_json = excluded.risk_json,
                        status_change = excluded.status_change
                    """,
                    history_rows,
                )
            conn.commit()

    def select_manual_candidate(
        self,
        trade_date: str,
        asset_code: str,
        pool: str,
        action: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            candidate = conn.execute(
                """
                select asset_code, asset_type, primary_pool, stage, score
                from screening_candidate_snapshot
                where trade_date = %s and asset_code = %s and primary_pool = %s
                order by updated_at desc
                limit 1
                """,
                (trade_date, asset_code, pool),
            ).fetchone()
            if candidate is None:
                raise ValueError(f"no {pool} candidate found for {asset_code} on {trade_date}")
            now = _now()
            if action == "REMOVE":
                conn.execute(
                    """
                    delete from screening_manual_pool_selection
                    where trade_date = %s and asset_code = %s and pool = %s
                    """,
                    (trade_date, asset_code, pool),
                )
                conn.execute(
                    """
                    delete from screening_user_watchlist
                    where asset_code = %s
                    """,
                    (asset_code,),
                )
            else:
                conn.execute(
                    """
                    insert into screening_manual_pool_selection (
                        trade_date, asset_code, asset_type, pool, action, note, selected_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s)
                    on conflict(trade_date, asset_code, pool) do update set
                        action = excluded.action,
                        note = excluded.note,
                        selected_at = excluded.selected_at
                    """,
                    (trade_date, asset_code, candidate["asset_type"], pool, action, note, now),
                )
                if action == "SELECT":
                    conn.execute(
                        """
                        insert into screening_user_watchlist (
                            asset_code, asset_type, status, note, snooze_until, updated_at
                        )
                        values (%s, %s, %s, %s, null, %s)
                        on conflict(asset_code) do update set
                            asset_type = excluded.asset_type,
                            status = excluded.status,
                            note = excluded.note,
                            snooze_until = null,
                            updated_at = excluded.updated_at
                        """,
                        (asset_code, candidate["asset_type"], "WATCHING_A", note, now),
                    )
            conn.commit()
        return {
            "trade_date": trade_date,
            "asset_code": asset_code,
            "asset_type": candidate["asset_type"],
            "pool": pool,
            "action": action,
            "note": note,
            "stage": candidate["stage"],
            "score": float(candidate["score"]),
        }

    def load_manual_selections(self, pool: str = "A", trade_date: str | None = None) -> list[dict[str, Any]]:
        query = """
            select s.trade_date, s.asset_code, s.asset_type, a.name, s.pool, s.action, s.note, s.selected_at
            from screening_manual_pool_selection s
            left join screening_asset_master a on a.asset_code = s.asset_code
            where s.pool = %s
        """
        params: list[Any] = [pool]
        if trade_date:
            query += " and s.trade_date = %s"
            params.append(trade_date)
        query += " order by s.trade_date desc, s.selected_at desc"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def log_sync(self, trade_date: str, sync_type: str, status: str, message: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into screening_sync_log (trade_date, sync_type, status, message, created_at)
                values (%s, %s, %s, %s, %s)
                """,
                (trade_date, sync_type, status, message, _now()),
            )
            conn.commit()

    def get_kline_bars(
        self, asset_code: str, period: str = "daily", adjust: str = "qfq"
    ) -> list[dict[str, Any]]:
        # ── 30 分钟 K 线 ────────────────────────────────────────────────
        if period == "30min":
            with self.connect() as conn:
                rows = conn.execute(
                    """
                    select trade_time, open, high, low, close, vol, amount
                    from screening_min_bar
                    where asset_code = %s and freq = '30min'
                    order by trade_time asc
                    """,
                    (asset_code,),
                ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                trade_time = row["trade_time"]  # e.g. '2026-08-06 15:00:00'
                dt = datetime.strptime(str(trade_time)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                result.append({
                    "timestamp": int(dt.timestamp() * 1000),
                    "trade_date": str(trade_time)[:10].replace("-", ""),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["vol"]),
                    "turnover": float(row["amount"]),
                })
            return result

        # ── 月线（从日线合成）────────────────────────────────────────────
        if period == "monthly":
            with self.connect() as conn:
                adj_rows = conn.execute(
                    "select trade_date, adj_factor from screening_adj_factor where asset_code = %s order by trade_date asc",
                    (asset_code,),
                ).fetchall()
                adj_map = {row["trade_date"]: float(row["adj_factor"]) for row in adj_rows}
                latest_adj = float(adj_rows[-1]["adj_factor"]) if adj_rows else 1.0

                # 按自然月聚合：first open / max high / min low / last close / sum vol/amount
                bars = conn.execute(
                    """
                    select
                        to_char(date_trunc('month', to_date(trade_date, 'YYYYMMDD')), 'YYYYMMDD') as month_start,
                        (array_agg(open  order by trade_date asc))[1]  as open,
                        max(high)                                        as high,
                        min(low)                                         as low,
                        (array_agg(close order by trade_date desc))[1]  as close,
                        sum(vol)                                         as vol,
                        sum(amount)                                      as amount,
                        min(trade_date)                                  as first_date,
                        max(trade_date)                                  as last_date
                    from screening_daily_bar
                    where asset_code = %s
                    group by date_trunc('month', to_date(trade_date, 'YYYYMMDD'))
                    order by month_start asc
                    """,
                    (asset_code,),
                ).fetchall()

            result = []
            for bar in bars:
                month_start = bar["month_start"]
                last_date = bar["last_date"]
                dt = datetime.strptime(month_start, "%Y%m%d").replace(tzinfo=UTC)
                timestamp = int(dt.timestamp() * 1000)

                op = float(bar["open"])
                hi = float(bar["high"])
                lo = float(bar["low"])
                cl = float(bar["close"])

                if adjust == "qfq" and latest_adj > 0 and last_date in adj_map:
                    ratio = adj_map[last_date] / latest_adj
                    op = round(op * ratio, 2)
                    hi = round(hi * ratio, 2)
                    lo = round(lo * ratio, 2)
                    cl = round(cl * ratio, 2)

                result.append({
                    "timestamp": timestamp,
                    "trade_date": month_start,
                    "open": op,
                    "high": hi,
                    "low": lo,
                    "close": cl,
                    "volume": float(bar["vol"]),
                    "turnover": float(bar["amount"]),
                })
            return result

        # ── 日线 / 周线 ─────────────────────────────────────────────────
        table_name = "screening_weekly_bar" if period == "weekly" else "screening_daily_bar"
        with self.connect() as conn:
            adj_rows = conn.execute(
                "select trade_date, adj_factor from screening_adj_factor where asset_code = %s order by trade_date asc",
                (asset_code,),
            ).fetchall()
            adj_map = {row["trade_date"]: float(row["adj_factor"]) for row in adj_rows}
            latest_adj = float(adj_rows[-1]["adj_factor"]) if adj_rows else 1.0

            bars = conn.execute(
                f"""
                select trade_date, open, high, low, close, vol, amount
                from {table_name}
                where asset_code = %s
                order by trade_date asc
                """,
                (asset_code,),
            ).fetchall()

        result = []
        for bar in bars:
            t_date = bar["trade_date"]
            dt = datetime.strptime(t_date, "%Y%m%d").replace(tzinfo=UTC)
            timestamp = int(dt.timestamp() * 1000)

            op = float(bar["open"])
            hi = float(bar["high"])
            lo = float(bar["low"])
            cl = float(bar["close"])
            vol = float(bar["vol"])
            amt = float(bar["amount"])

            if adjust == "qfq" and latest_adj > 0 and t_date in adj_map:
                ratio = adj_map[t_date] / latest_adj
                op = round(op * ratio, 2)
                hi = round(hi * ratio, 2)
                lo = round(lo * ratio, 2)
                cl = round(cl * ratio, 2)

            result.append(
                {
                    "timestamp": timestamp,
                    "trade_date": t_date,
                    "open": op,
                    "high": hi,
                    "low": lo,
                    "close": cl,
                    "volume": vol,
                    "turnover": amt,
                }
            )
        return result




    def get_kline_drawings(self, asset_code: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "select drawings_json from screening_kline_drawings where asset_code = %s",
                (asset_code,),
            ).fetchone()
            if row and row.get("drawings_json"):
                return row["drawings_json"]
            return []

    def save_kline_drawings(self, asset_code: str, drawings: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into screening_kline_drawings (asset_code, drawings_json, updated_at)
                values (%s, %s, %s)
                on conflict (asset_code) do update
                set drawings_json = excluded.drawings_json,
                    updated_at = excluded.updated_at
                """,
                (asset_code, json_dumps(drawings), _now()),
            )
            conn.commit()

    def save_min_bars(self, df: pd.DataFrame, freq: str = "30min") -> None:
        if df.empty:
            return
        now = _now()
        rows = []
        for record in df.to_dict(orient="records"):
            rows.append(
                (
                    str(record["asset_code"]),
                    str(record["asset_type"]),
                    str(record["trade_time"]),
                    float(record["open"]),
                    float(record["high"]),
                    float(record["low"]),
                    float(record["close"]),
                    float(record["vol"]),
                    float(record["amount"]),
                    freq,
                    json_dumps(record),
                    now,
                )
            )
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into screening_min_bar (
                        asset_code, asset_type, trade_time, open, high, low, close,
                        vol, amount, freq, raw_json, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict(asset_code, trade_time, freq) do update set
                        asset_type = excluded.asset_type,
                        open = excluded.open,
                        high = excluded.high,
                        low = excluded.low,
                        close = excluded.close,
                        vol = excluded.vol,
                        amount = excluded.amount,
                        raw_json = excluded.raw_json,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
            conn.commit()

    def get_all_assets(self) -> list[dict[str, str]]:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "select asset_code, asset_type, name from screening_asset_master order by asset_code"
                )
                return cursor.fetchall()

    def get_priority_assets(self) -> list[dict[str, str]]:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select a.asset_code, a.asset_type, a.name,
                        case
                            when w.asset_code is not null then 1
                            when c.asset_code is not null then 2
                            when a.asset_type = 'etf' then 3
                            else 9
                        end as prio
                    from screening_asset_master a
                    left join screening_user_watchlist w on w.asset_code = a.asset_code
                    left join (select distinct asset_code from screening_candidate_snapshot) c on c.asset_code = a.asset_code
                    order by prio asc, a.asset_code asc
                    """
                )
                return cursor.fetchall()

    def get_latest_min_trade_time(self, asset_code: str, freq: str = "30min") -> str | None:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "select max(trade_time) as max_time from screening_min_bar where asset_code = %s and freq = %s",
                    (asset_code, freq),
                )
                row = cursor.fetchone()
                return row["max_time"] if row and row.get("max_time") else None


    # ── P1 审计骨架：screening_run ──────────────────────────────────────
    def create_screening_run(
        self,
        run_id: str,
        trade_date: str,
        config_version: str,
        data_version: str,
        run_name: str | None = None,
        notes: str | None = None,
        universe_type: str = "ALL",
        universe_params: dict[str, Any] | None = None,
        data_freshness: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into screening_run (
                    run_id, trade_date, config_version, data_version, started_at, status,
                    run_name, notes, universe_type, universe_params_json, data_freshness_json
                )
                values (%s, %s, %s, %s, %s, 'RUNNING', %s, %s, %s, %s::jsonb, %s::jsonb)
                on conflict (run_id) do nothing
                """,
                (
                    run_id, trade_date, config_version, data_version, _now(),
                    run_name or f"{trade_date} 选股任务", notes, universe_type,
                    json_dumps(universe_params or {}), json_dumps(data_freshness or {})
                ),
            )
            conn.commit()

    def finish_screening_run(
        self,
        run_id: str,
        status: str,
        summary: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                update screening_run
                set status = %s, finished_at = %s, summary_json = %s::jsonb, error_message = %s
                where run_id = %s
                """,
                (status, _now(), json_dumps(summary or {}), error_message, run_id),
            )
            conn.commit()

    def get_latest_screening_run(self, trade_date: str | None = None) -> dict[str, Any] | None:
        query = "select * from screening_run"
        params: list[Any] = []
        if trade_date:
            query += " where trade_date = %s"
            params.append(trade_date)
        query += " order by started_at desc limit 1"
        with self.connect() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None


    def list_screening_runs_history(self, limit: int = 50) -> list[dict[str, Any]]:
        query = """
            select run_id, trade_date, config_version, data_version, started_at, finished_at,
                   status, error_message, summary_json, run_name, notes, universe_type,
                   universe_params_json, data_freshness_json
            from screening_run
            order by started_at desc
            limit %s
        """
        with self.connect() as conn:
            rows = conn.execute(query, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_data_freshness_info(self) -> dict[str, Any]:
        with self.connect() as conn:
            # 只有全量数据 >= 4000 条的完整交易日才认作合格有效的新鲜度日期
            row_daily = conn.execute(
                """
                select trade_date
                from screening_daily_bar
                where asset_type = 'stock'
                group by trade_date
                having count(*) >= 4000
                order by trade_date desc
                limit 1
                """
            ).fetchone()
            max_daily = row_daily["trade_date"] if row_daily else None

            max_min = conn.execute("select max(trade_time) as mt from screening_min_bar").fetchone()["mt"]
            max_candidate = conn.execute("select max(trade_date) as mc from screening_candidate_snapshot").fetchone()["mc"]
        return {
            "daily_market_date": max_daily or "未知",
            "min_bar_time": max_min or "未知",
            "candidate_date": max_candidate or "未知",
            "financial_data_quarter": "2026Q2",
        }

    def get_screening_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "select * from screening_run where run_id = %s",
                (run_id,),
            ).fetchone()
        return dict(row) if row else None

    # ── P1 审计骨架：pool_candidate_snapshot_v2 ─────────────────────────
    def save_pool_candidates_v2(self, run_id: str, candidates: list[dict[str, Any]]) -> None:
        now = _now()
        rows = [
            (
                run_id,
                item["ts_code"],
                item["pool_code"],
                _nullable_float(item.get("pool_source_score")),
                json_dumps(item.get("source_payload") or {}),
                now,
            )
            for item in candidates
        ]
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into pool_candidate_snapshot_v2 (run_id, ts_code, pool_code, pool_source_score, source_payload, created_at)
                    values (%s, %s, %s, %s, %s::jsonb, %s)
                    on conflict (run_id, ts_code, pool_code) do nothing
                    """,
                    rows,
                )
            conn.commit()

    def load_pool_candidates_v2(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "select * from pool_candidate_snapshot_v2 where run_id = %s order by pool_code, ts_code",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── P1 审计骨架：stage_snapshot ─────────────────────────────────────
    def save_stage_snapshots(self, snapshots: list[dict[str, Any]]) -> None:
        now = _now()
        rows = [
            (
                item["run_id"],
                item["ts_code"],
                item["pool_code"],
                item["stage"],
                item["status"],
                _nullable_float(item.get("score")),
                item.get("rank_all"),
                item.get("rank_pool"),
                item.get("rank_industry"),
                json_dumps(item.get("score_detail") or {}),
                now,
            )
            for item in snapshots
        ]
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into stage_snapshot (
                        run_id, ts_code, pool_code, stage, status, score,
                        rank_all, rank_pool, rank_industry, score_detail_json, evaluated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict (run_id, ts_code, pool_code, stage) do update set
                        status = excluded.status,
                        score = excluded.score,
                        rank_all = excluded.rank_all,
                        rank_pool = excluded.rank_pool,
                        rank_industry = excluded.rank_industry,
                        score_detail_json = excluded.score_detail_json,
                        evaluated_at = excluded.evaluated_at
                    """,
                    rows,
                )
            conn.commit()

    def load_stage_snapshots(self, run_id: str, ts_code: str | None = None) -> list[dict[str, Any]]:
        query = "select * from stage_snapshot where run_id = %s"
        params: list[Any] = [run_id]
        if ts_code:
            query += " and ts_code = %s"
            params.append(ts_code)
        query += " order by ts_code, stage"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def load_stage_funnel(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select pool_code, stage, status, count(*) as cnt
                from stage_snapshot
                where run_id = %s
                group by pool_code, stage, status
                order by pool_code, stage, status
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── P1 审计骨架：stage_reason ───────────────────────────────────────
    def save_stage_reasons(self, reasons: list[dict[str, Any]]) -> None:
        now = _now()
        rows = [
            (
                item["run_id"],
                item["ts_code"],
                item["pool_code"],
                item["stage"],
                item["reason_code"],
                item.get("severity", "HARD"),
                _nullable_float(item.get("actual_value")),
                _nullable_float(item.get("threshold_value")),
                item.get("message"),
                now,
            )
            for item in reasons
        ]
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into stage_reason (
                        run_id, ts_code, pool_code, stage, reason_code, severity,
                        actual_value, threshold_value, message, created_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
            conn.commit()

    def load_stage_reasons(self, run_id: str, ts_code: str | None = None) -> list[dict[str, Any]]:
        query = "select * from stage_reason where run_id = %s"
        params: list[Any] = [run_id]
        if ts_code:
            query += " and ts_code = %s"
            params.append(ts_code)
        query += " order by ts_code, stage, id"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def load_stage_reasons_summary(
        self, run_id: str, pool_code: str, stage: str
    ) -> list[dict[str, Any]]:
        """获取某次运行中，指定池和层级的淘汰原因分类统计（按 reason_code 汇总）"""
        with self.connect() as conn:
            rows = conn.execute(
                """
                select reason_code, count(*) as cnt
                from stage_reason
                where run_id = %s and pool_code = %s and stage = %s
                group by reason_code
                order by cnt desc, reason_code asc
                """,
                (run_id, pool_code, stage),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_stage_stocks_drilldown(
        self,
        run_id: str,
        pool_code: str,
        stage: str,
        status: str | None = None,
        reason_code: str | None = None,
        industry: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """下钻查询指定池、层级、状态或淘汰原因的股票列表明细，包含全量行业统计频次"""
        base_where_clauses = ["s.run_id = %s", "s.pool_code = %s", "s.stage = %s"]
        base_params: list[Any] = [run_id, pool_code, stage]

        if status:
            base_where_clauses.append("s.status = %s")
            base_params.append(status)

        if reason_code:
            base_where_clauses.append(
                "exists (select 1 from stage_reason r where r.run_id = s.run_id and r.ts_code = s.ts_code and r.stage = s.stage and r.reason_code = %s)"
            )
            base_params.append(reason_code)

        base_where_sql = " where " + " and ".join(base_where_clauses)

        # 行业分布查询 (基于 base_where_sql，不含 industry 过滤)
        industry_sql = f"""
            select coalesce(a.raw_json->>'industry', '未分类') as ind, count(*) as cnt
            from stage_snapshot s
            left join screening_asset_master a on a.asset_code = s.ts_code
            {base_where_sql}
            group by ind
            order by cnt desc
        """

        where_clauses = list(base_where_clauses)
        params = list(base_params)

        if industry and industry != "ALL":
            where_clauses.append("a.raw_json->>'industry' = %s")
            params.append(industry)

        where_sql = " where " + " and ".join(where_clauses)

        count_sql = f"""
            select count(*) as cnt
            from stage_snapshot s
            left join screening_asset_master a on a.asset_code = s.ts_code
            {where_sql}
        """
        data_sql = f"""
            select s.run_id, s.ts_code, s.pool_code, s.stage, s.status, s.score,
                   s.score_detail_json, a.name, a.asset_type,
                   a.raw_json->>'industry' as industry,
                   a.raw_json->>'main_business' as main_business,
                   a.raw_json->>'market' as market,
                   c.reasons_json as l0_reasons_json,
                   f.features_json,
                   m.action as manual_action
            from stage_snapshot s
            left join screening_asset_master a on a.asset_code = s.ts_code
            left join screening_run r on r.run_id = s.run_id
            left join screening_candidate_snapshot c
                on c.trade_date = r.trade_date and c.asset_code = s.ts_code and c.primary_pool = s.pool_code
            left join screening_technical_features f
                on f.trade_date = r.trade_date and f.asset_code = s.ts_code
            left join screening_manual_pool_selection m
                on m.trade_date = r.trade_date and m.asset_code = s.ts_code and m.pool = s.pool_code
            {where_sql}
            order by s.status asc, s.score desc nulls last, s.ts_code asc
            limit %s offset %s
        """

        with self.connect() as conn:
            ind_rows = conn.execute(industry_sql, base_params).fetchall()
            industry_counts = {r["ind"]: r["cnt"] for r in ind_rows}

            total = conn.execute(count_sql, params).fetchone()["cnt"]
            stock_rows = conn.execute(data_sql, params + [limit, offset]).fetchall()

            # 查询相关原因
            ts_codes = [r["ts_code"] for r in stock_rows]
            reasons_map: dict[str, list[dict[str, Any]]] = {}
            if ts_codes:
                reason_rows = conn.execute(
                    """
                    select ts_code, reason_code, severity, actual_value, threshold_value, message
                    from stage_reason
                    where run_id = %s and stage = %s and ts_code = any(%s)
                    order by id asc
                    """,
                    (run_id, stage, ts_codes),
                ).fetchall()
                for r in reason_rows:
                    reasons_map.setdefault(r["ts_code"], []).append(dict(r))

        items = []
        for r in stock_rows:
            item = dict(r)
            item["score"] = _nullable_float(item.get("score"))
            item["features"] = item.get("features_json") or {}
            item["l0_reasons"] = item.get("l0_reasons_json") or []
            item["is_selected"] = (item.get("manual_action") == "SELECT")
            raw_reasons = reasons_map.get(r["ts_code"], [])
            formatted_reasons = []
            for reason in raw_reasons:
                rf = dict(reason)
                rf["actual_value"] = _nullable_float(rf.get("actual_value"))
                rf["threshold_value"] = _nullable_float(rf.get("threshold_value"))
                formatted_reasons.append(rf)
            item["reasons"] = formatted_reasons
            items.append(item)

        return {
            "total": total,
            "industry_counts": industry_counts,
            "items": items,
            "limit": limit,
            "offset": offset,
        }


    # ── P2 因子快照：factor_snapshot ────────────────────────────────────
    def save_factor_snapshots(self, snapshots: list[dict[str, Any]], factor_version: str) -> None:
        now = _now()
        rows = [
            (
                item["trade_date"],
                item["ts_code"],
                item["factor_name"],
                _nullable_float(item.get("factor_value")),
                item.get("data_quality", "OK"),
                factor_version,
                now,
            )
            for item in snapshots
        ]
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into factor_snapshot (
                        trade_date, ts_code, factor_name, factor_value, data_quality, factor_version, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s)
                    on conflict (trade_date, ts_code, factor_name, factor_version) do update set
                        factor_value = excluded.factor_value,
                        data_quality = excluded.data_quality,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
            conn.commit()

    def load_factor_snapshots(
        self,
        trade_date: str,
        factor_names: list[str],
        factor_version: str,
        ts_codes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            select ts_code, factor_name, factor_value, data_quality
            from factor_snapshot
            where trade_date = %s and factor_name = any(%s) and factor_version = %s
        """
        params: list[Any] = [trade_date, factor_names, factor_version]
        if ts_codes:
            query += " and ts_code = any(%s)"
            params.append(ts_codes)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    # ── P2 行业数据：industry_membership_history ─────────────────────────
    def save_industry_memberships(self, memberships: list[dict[str, Any]], source_version: str) -> None:
        now = _now()
        rows = [
            (
                item["ts_code"],
                item.get("l1_code"),
                item.get("l1_name"),
                item.get("l2_code"),
                item.get("l2_name"),
                item.get("l3_code"),
                item.get("l3_name"),
                item.get("in_date"),
                item.get("out_date"),
                source_version,
                now,
            )
            for item in memberships
        ]
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into industry_membership_history (
                        ts_code, l1_code, l1_name, l2_code, l2_name, l3_code, l3_name,
                        in_date, out_date, source_version, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (ts_code, source_version) do update set
                        l1_code = excluded.l1_code, l1_name = excluded.l1_name,
                        l2_code = excluded.l2_code, l2_name = excluded.l2_name,
                        l3_code = excluded.l3_code, l3_name = excluded.l3_name,
                        in_date = excluded.in_date, out_date = excluded.out_date,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
            conn.commit()

    def load_industry_memberships(
        self,
        source_version: str,
        ts_codes: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        query = "select * from industry_membership_history where source_version = %s"
        params: list[Any] = [source_version]
        if ts_codes:
            query += " and ts_code = any(%s)"
            params.append(ts_codes)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return {row["ts_code"]: dict(row) for row in rows}

    def load_industry_membership_for_date(
        self,
        trade_date: str,
        source_version: str,
        ts_codes: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """返回指定 trade_date 时仍在成分内的行业归属（in_date <= trade_date < out_date 或 out_date 为空）"""
        query = """
            select * from industry_membership_history
            where source_version = %s
              and (in_date is null or in_date <= %s)
              and (out_date is null or out_date > %s)
        """
        params: list[Any] = [source_version, trade_date, trade_date]
        if ts_codes:
            query += " and ts_code = any(%s)"
            params.append(ts_codes)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return {row["ts_code"]: dict(row) for row in rows}

    # ── P2 行业因子：industry_factor_snapshot ────────────────────────────
    def save_industry_factor_snapshots(self, snapshots: list[dict[str, Any]]) -> None:
        now = _now()
        rows = [
            (
                item["trade_date"],
                item["industry_code"],
                int(item.get("industry_level", 2)),
                item.get("industry_name"),
                _nullable_float(item.get("ret_1d")),
                _nullable_float(item.get("ret_5d")),
                _nullable_float(item.get("ret_20d")),
                _nullable_float(item.get("ret_60d")),
                item.get("up_count"),
                item.get("down_count"),
                item.get("total_count"),
                _nullable_float(item.get("ind_trend_score")),
                json_dumps(item.get("raw_json") or {}),
                now,
            )
            for item in snapshots
        ]
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into industry_factor_snapshot (
                        trade_date, industry_code, industry_level, industry_name,
                        ret_1d, ret_5d, ret_20d, ret_60d,
                        up_count, down_count, total_count, ind_trend_score,
                        raw_json, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict (trade_date, industry_code) do update set
                        industry_name = excluded.industry_name,
                        ret_1d = excluded.ret_1d, ret_5d = excluded.ret_5d,
                        ret_20d = excluded.ret_20d, ret_60d = excluded.ret_60d,
                        up_count = excluded.up_count, down_count = excluded.down_count,
                        total_count = excluded.total_count, ind_trend_score = excluded.ind_trend_score,
                        raw_json = excluded.raw_json, updated_at = excluded.updated_at
                    """,
                    rows,
                )
            conn.commit()

    def load_industry_factors(self, trade_date: str) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "select * from industry_factor_snapshot where trade_date = %s",
                (trade_date,),
            ).fetchall()
        return {row["industry_code"]: dict(row) for row in rows}

    # ── 配置版本管理 v2 ──────────────────────────────────────────────────
    def save_config_v2(
        self,
        config_version: str,
        effective_from: str,
        config_yaml: str,
        note: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into screening_config_v2 (config_version, effective_from, config_yaml, created_at, note)
                values (%s, %s, %s, %s, %s)
                on conflict (config_version) do nothing
                """,
                (config_version, effective_from, config_yaml, _now(), note),
            )
            conn.commit()


        # ── A-Pre V2 Early Turn 实验存储 API ──────────────────────────────────────
    def create_early_turn_run(
        self,
        run_id: str,
        trade_date: str,
        config_version: str = "early_turn_v1.0",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into early_turn_run (run_id, trade_date, config_version, started_at, status)
                values (%s, %s, %s, %s, 'RUNNING')
                on conflict (run_id) do nothing
                """,
                (run_id, trade_date, config_version, _now()),
            )
            conn.commit()

    def finish_early_turn_run(
        self,
        run_id: str,
        status: str,
        summary: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                update early_turn_run
                set status = %s, finished_at = %s, summary_json = %s::jsonb, error_message = %s
                where run_id = %s
                """,
                (status, _now(), json_dumps(summary or {}), error_message, run_id),
            )
            conn.commit()

    def get_latest_early_turn_run(self, trade_date: str | None = None) -> dict[str, Any] | None:
        query = "select * from early_turn_run"
        params: list[Any] = []
        if trade_date:
            query += " where trade_date = %s"
            params.append(trade_date)
        query += " order by started_at desc limit 1"
        with self.connect() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def save_early_turn_results(self, results: list[dict[str, Any]]) -> None:
        if not results:
            return
        now = _now()
        rows = [
            (
                r["run_id"],
                r["ts_code"],
                r["trade_date"],
                r["total_score"],
                r["state"],
                r["background_type"],
                r.get("selected", False),
                r.get("is_overextended", False),
                json_dumps(r.get("features_json", {})),
                json_dumps(r.get("score_detail_json", {})),
                json_dumps(r.get("reasons_json", [])),
                r.get("first_selected_date"),
                now,
            )
            for r in results
        ]
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into early_turn_result (
                    run_id, ts_code, trade_date, total_score, state, background_type,
                    selected, is_overextended, features_json, score_detail_json,
                    reasons_json, first_selected_date, created_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
                on conflict (run_id, ts_code) do update set
                    total_score = excluded.total_score,
                    state = excluded.state,
                    background_type = excluded.background_type,
                    selected = excluded.selected,
                    is_overextended = excluded.is_overextended,
                    features_json = excluded.features_json,
                    score_detail_json = excluded.score_detail_json,
                    reasons_json = excluded.reasons_json,
                    first_selected_date = excluded.first_selected_date
                """,
                rows,
            )
            conn.commit()

    def query_early_turn_results(
        self,
        run_id: str,
        state: str | None = None,
        background_type: str | None = None,
        min_score: float | None = None,
        query_text: str | None = None,
        industry: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        where_clauses = ["r.run_id = %s"]
        params: list[Any] = [run_id]

        if state and state != "ALL":
            where_clauses.append("r.state = %s")
            params.append(state)
        if background_type and background_type != "ALL":
            where_clauses.append("r.background_type = %s")
            params.append(background_type)
        if min_score is not None:
            where_clauses.append("r.total_score >= %s")
            params.append(min_score)
        if industry and industry != "ALL":
            where_clauses.append("a.raw_json->>'industry' = %s")
            params.append(industry)
        if query_text:
            where_clauses.append("(r.ts_code ilike %s or a.name ilike %s)")
            q_param = f"%{query_text.strip()}%"
            params.extend([q_param, q_param])

        where_sql = " where " + " and ".join(where_clauses)

        count_sql = f"""
            select count(*) as cnt
            from early_turn_result r
            left join screening_asset_master a on a.asset_code = r.ts_code
            {where_sql}
        """

        data_sql = f"""
            select r.run_id, r.ts_code, r.trade_date, r.total_score, r.state,
                   r.background_type, r.selected, r.is_overextended,
                   r.features_json, r.score_detail_json, r.reasons_json,
                   r.first_selected_date, a.name, a.asset_type,
                   a.raw_json->>'industry' as industry,
                   a.raw_json->>'main_business' as main_business
            from early_turn_result r
            left join screening_asset_master a on a.asset_code = r.ts_code
            {where_sql}
            order by r.total_score desc, r.ts_code asc
            limit %s offset %s
        """

        with self.connect() as conn:
            total = conn.execute(count_sql, params).fetchone()["cnt"]
            rows = conn.execute(data_sql, params + [limit, offset]).fetchall()
            
            # 基础 Counts 统计
            counts_row = conn.execute(
                """
                select state, count(*) as cnt
                from early_turn_result
                where run_id = %s
                group by state
                """,
                (run_id,),
            ).fetchall()
            counts = {r["state"]: r["cnt"] for r in counts_row}

            # 行业分布 counts 统计 (忽略当前 industry 筛选，但保留 state/bg_type/min_score/query_text 筛选)
            ind_where_clauses = ["r.run_id = %s"]
            ind_params = [run_id]
            if state and state != "ALL":
                ind_where_clauses.append("r.state = %s")
                ind_params.append(state)
            if background_type and background_type != "ALL":
                ind_where_clauses.append("r.background_type = %s")
                ind_params.append(background_type)
            if min_score is not None:
                ind_where_clauses.append("r.total_score >= %s")
                ind_params.append(min_score)
            if query_text:
                ind_where_clauses.append("(r.ts_code ilike %s or a.name ilike %s)")
                q_param = f"%{query_text.strip()}%"
                ind_params.extend([q_param, q_param])
                
            ind_where_sql = " where " + " and ".join(ind_where_clauses)
            
            industry_sql = f"""
                select a.raw_json->>'industry' as ind, count(*) as cnt
                from early_turn_result r
                left join screening_asset_master a on a.asset_code = r.ts_code
                {ind_where_sql}
                group by ind
            """
            ind_rows = conn.execute(industry_sql, ind_params).fetchall()
            industry_counts = {r["ind"]: r["cnt"] for r in ind_rows if r["ind"]}

        items = []
        for row in rows:
            item = dict(row)
            item["total_score"] = _nullable_float(item.get("total_score"))
            items.append(item)

        return {
            "total": total,
            "counts": counts,
            "industry_counts": industry_counts,
            "items": items,
            "limit": limit,
            "offset": offset,
        }

    def list_positive_samples(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("select * from early_turn_positive_sample order by sample_id asc").fetchall()
        return [dict(r) for r in rows]

    def save_positive_sample(self, ts_code: str, target_date: str, sample_name: str, note: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into early_turn_positive_sample (ts_code, target_date, sample_name, note, created_at)
                values (%s, %s, %s, %s, %s)
                on conflict (ts_code, target_date, label_version) do update set
                    sample_name = excluded.sample_name,
                    note = excluded.note
                """,
                (ts_code, target_date, sample_name, note, _now()),
            )
            conn.commit()


def _now() -> datetime:

    return datetime.now(UTC)


def _nullable_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _candidate_row(row: dict[str, Any]) -> dict[str, Any]:
    features = row.get("features_json") or {}
    raw_json = row.get("raw_json") or {}
    industry = row.get("industry") or raw_json.get("industry") or ("ETF" if row["asset_type"] == "etf" else None)
    market = raw_json.get("market") or ("ETF" if row["asset_type"] == "etf" else "主板")
    ent_type = raw_json.get("ent_type")
    province = raw_json.get("province")
    city = raw_json.get("city")
    main_business = raw_json.get("main_business")
    fund_type = raw_json.get("fund_type")
    management = raw_json.get("management")

    return {
        "trade_date": row["trade_date"],
        "asset_code": row["asset_code"],
        "name": row.get("name"),
        "industry": industry,
        "market": market,
        "ent_type": ent_type,
        "province": province,
        "city": city,
        "main_business": main_business,
        "fund_type": fund_type,
        "management": management,
        "asset_type": row["asset_type"],
        "primary_pool": row["primary_pool"],
        "stage": row["stage"],
        "score": float(row["score"]),
        "pools": row.get("pools_json") or [],
        "reasons": row.get("reasons_json") or [],
        "risks": row.get("risks_json") or [],
        "status_change": row["status_change"],
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        "features": features,
        "is_selected": bool(row.get("manual_action") == "SELECT"),
        "user_note": row.get("manual_note"),
    }


