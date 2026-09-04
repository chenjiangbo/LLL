from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time as dtime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from backend.screening.concept_filter import is_low_signal_ths_concept
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
                    total_share numeric,
                    float_share numeric,
                    free_share numeric,
                    turnover_rate numeric,
                    turnover_rate_f numeric,
                    volume_ratio numeric,
                    total_mv numeric,
                    circ_mv numeric,
                    limit_status text,
                    raw_json jsonb not null,
                    updated_at timestamptz not null,
                    primary key (asset_code, trade_date)
                )
                """
            )
            conn.execute("alter table screening_daily_basic add column if not exists total_share numeric")
            conn.execute("alter table screening_daily_basic add column if not exists float_share numeric")
            conn.execute("alter table screening_daily_basic add column if not exists free_share numeric")
            conn.execute("alter table screening_daily_basic add column if not exists volume_ratio numeric")
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
                create table if not exists screening_watchlist_groups (
                    group_id bigserial primary key,
                    group_name text not null,
                    parent_id bigint references screening_watchlist_groups(group_id) on delete cascade,
                    sort_order int default 0,
                    created_at timestamptz not null default now()
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_user_watchlist (
                    asset_code text not null,
                    asset_type text not null default 'stock',
                    group_id bigint references screening_watchlist_groups(group_id) on delete cascade,
                    note text,
                    source_type text not null default 'UNKNOWN',
                    source_strategy text,
                    source_stage text,
                    source_snapshot_date text,
                    source_recorded_at timestamptz,
                    created_at timestamptz not null default now(),
                    primary key (asset_code, group_id)
                )
                """
            )
            conn.execute("alter table screening_user_watchlist add column if not exists group_id bigint")
            conn.execute("alter table screening_user_watchlist add column if not exists created_at timestamptz default now()")
            conn.execute("alter table screening_user_watchlist add column if not exists source_type text not null default 'UNKNOWN'")
            conn.execute("alter table screening_user_watchlist add column if not exists source_strategy text")
            conn.execute("alter table screening_user_watchlist add column if not exists source_stage text")
            conn.execute("alter table screening_user_watchlist add column if not exists source_snapshot_date text")
            conn.execute("alter table screening_user_watchlist add column if not exists source_recorded_at timestamptz")
            conn.execute(
                """
                update screening_user_watchlist
                set source_type = 'UNKNOWN'
                where source_recorded_at is null
                  and source_type = 'MANUAL'
                  and source_strategy is null
                  and source_stage is null
                  and source_snapshot_date is null
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
                create table if not exists screening_ai_analysis_pool (
                    asset_code text primary key,
                    asset_type text not null default 'stock',
                    created_at timestamptz not null default now()
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
                create table if not exists screening_data_management_config (
                    config_id integer primary key default 1 check (config_id = 1),
                    config_json jsonb not null,
                    version integer not null default 1,
                    updated_at timestamptz not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists screening_data_task (
                    task_id text primary key,
                    task_type text not null,
                    status text not null,
                    progress integer not null default 0,
                    stage_message text not null default '',
                    trade_date text,
                    summary_json jsonb not null default '{}'::jsonb,
                    error_message text,
                    cancel_requested boolean not null default false,
                    started_at timestamptz,
                    completed_at timestamptz,
                    created_at timestamptz not null,
                    updated_at timestamptz not null
                )
                """
            )
            conn.execute("alter table screening_data_task add column if not exists cancel_requested boolean not null default false")
            conn.execute("create index if not exists idx_screening_data_task_created on screening_data_task(created_at desc)")
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
                create table if not exists screening_min_sync_status (
                    asset_code text not null,
                    trade_date text not null,
                    freq text not null default '30min',
                    expected_slots integer not null,
                    actual_slots integer not null default 0,
                    status text not null,
                    attempt_count integer not null default 0,
                    last_error text,
                    updated_at timestamptz not null,
                    primary key (asset_code, trade_date, freq)
                )
                """
            )
            # 历史版本把“当天无行情”记为 EMPTY，导致失败队列持续重试。
            # 该状态在分钟线链路中表示证券当天没有有效交易数据，应归为正常的不可用行情状态。
            conn.execute(
                """
                update screening_min_sync_status
                set status = 'INACTIVE',
                    last_error = coalesce(last_error, '当天无有效行情，可能停牌或已退市')
                where status = 'EMPTY'
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
                    run_name text,
                    notes text,
                    config_version text not null,
                    started_at timestamptz not null,
                    finished_at timestamptz,
                    status text not null default 'RUNNING',
                    error_message text,
                    summary_json jsonb
                )
                """
            )
            conn.execute("alter table early_turn_run add column if not exists run_name text")
            conn.execute("alter table early_turn_run add column if not exists notes text")
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
                    membership_key text,
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
                    primary key (membership_key)
                )
                """
            )
            conn.execute("alter table industry_membership_history add column if not exists membership_key text")
            conn.execute(
                """
                update industry_membership_history
                set membership_key = md5(
                    ts_code || '|' || coalesce(l3_code, '') || '|' ||
                    coalesce(in_date, '') || '|' || coalesce(out_date, '') || '|' || source_version
                )
                where membership_key is null
                """
            )
            conn.execute(
                """
                do $$
                begin
                    if exists (
                        select 1
                        from pg_constraint
                        where conrelid = 'industry_membership_history'::regclass
                          and conname = 'industry_membership_history_pkey'
                          and pg_get_constraintdef(oid) <> 'PRIMARY KEY (membership_key)'
                    ) then
                        alter table industry_membership_history drop constraint industry_membership_history_pkey;
                    end if;
                    if not exists (
                        select 1
                        from pg_constraint
                        where conrelid = 'industry_membership_history'::regclass
                          and contype = 'p'
                    ) then
                        alter table industry_membership_history add primary key (membership_key);
                    end if;
                end $$;
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
            # ── Secondary Evaluation & AI Deep Research System V1.0 ──────────────
            conn.execute(
                """
                create table if not exists candidate_secondary_snapshot (
                    as_of_date text not null,
                    ts_code text not null,
                    aprev2_score numeric,
                    aprev2_status text,
                    turn_type text,
                    company_evidence_state text,
                    leadership_state text,
                    leadership_rank_value numeric,
                    supply_profile_label text,
                    calc_version text not null default 'v1.0',
                    created_at timestamptz not null,
                    primary key (as_of_date, ts_code)
                )
                """
            )
            conn.execute(
                """
                create table if not exists company_evidence_snapshot (
                    as_of_date text not null,
                    ts_code text not null,
                    latest_report_period text,
                    latest_report_ann_date text,
                    revenue numeric,
                    revenue_yoy numeric,
                    parent_net_profit numeric,
                    parent_net_profit_yoy numeric,
                    parent_profit_state text,
                    deducted_net_profit numeric,
                    deducted_net_profit_yoy numeric,
                    deducted_profit_state text,
                    operating_cashflow numeric,
                    operating_cashflow_yoy numeric,
                    gross_margin numeric,
                    gross_margin_yoy_delta numeric,
                    forecast_ann_date text,
                    forecast_type text,
                    forecast_p_change_min numeric,
                    forecast_p_change_max numeric,
                    forecast_net_profit_min numeric,
                    forecast_net_profit_max numeric,
                    express_ann_date text,
                    express_end_date text,
                    express_revenue numeric,
                    express_n_income numeric,
                    express_yoy_net_profit numeric,
                    express_summary text,
                    evidence_state text not null,
                    reason_json jsonb not null,
                    risk_flags_json jsonb not null,
                    data_version text not null default 'v1.0',
                    created_at timestamptz not null,
                    primary key (as_of_date, ts_code)
                )
                """
            )
            conn.execute("alter table company_evidence_snapshot add column if not exists express_ann_date text")
            conn.execute("alter table company_evidence_snapshot add column if not exists express_end_date text")
            conn.execute("alter table company_evidence_snapshot add column if not exists express_revenue numeric")
            conn.execute("alter table company_evidence_snapshot add column if not exists express_n_income numeric")
            conn.execute("alter table company_evidence_snapshot add column if not exists express_yoy_net_profit numeric")
            conn.execute("alter table company_evidence_snapshot add column if not exists express_summary text")
            conn.execute("alter table company_evidence_snapshot add column if not exists quarter_facts_json jsonb not null default '[]'::jsonb")
            conn.execute("alter table company_evidence_snapshot add column if not exists fact_tags_json jsonb not null default '[]'::jsonb")
            conn.execute("alter table company_evidence_snapshot add column if not exists data_quality_json jsonb not null default '{}'::jsonb")
            conn.execute("alter table company_evidence_snapshot add column if not exists fundamental_filter_state text")
            conn.execute("alter table company_evidence_snapshot add column if not exists fundamental_filter_reasons_json jsonb not null default '[]'::jsonb")
            conn.execute(
                """
                create table if not exists market_financial_summary_latest (
                    ts_code text primary key,
                    latest_report_period text,
                    revenue numeric,
                    revenue_yoy numeric,
                    parent_net_profit numeric,
                    parent_net_profit_yoy numeric,
                    operating_cashflow numeric,
                    operating_cashflow_yoy numeric,
                    forecast_type text,
                    fact_tags_json jsonb not null,
                    data_status text not null,
                    source_updated_at timestamptz,
                    generated_at timestamptz not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists relative_leadership_snapshot (
                    as_of_date text not null,
                    ts_code text not null,
                    comparison_level text,
                    comparison_industry_code text,
                    comparison_industry_name text,
                    comparison_universe_size integer,
                    stock_ret_5 numeric,
                    stock_ret_10 numeric,
                    stock_ret_20 numeric,
                    industry_rs_5_pct numeric,
                    industry_rs_10_pct numeric,
                    industry_rs_20_pct numeric,
                    up_event_count integer,
                    up_capture_excess numeric,
                    up_capture_pct numeric,
                    down_event_count integer,
                    down_defense_excess numeric,
                    down_defense_pct numeric,
                    amount_ratio_5_20 numeric,
                    amount_ratio_10_40 numeric,
                    participation_pct numeric,
                    participation_change numeric,
                    participation_change_pct numeric,
                    valid_component_count integer,
                    leadership_rank_value numeric,
                    leadership_state text not null,
                    reason_json jsonb not null,
                    calc_version text not null default 'v1.0',
                    created_at timestamptz not null,
                    primary key (as_of_date, ts_code)
                )
                """
            )
            conn.execute(
                """
                create table if not exists supply_profile_snapshot (
                    as_of_date text not null,
                    ts_code text not null,
                    close numeric,
                    total_share numeric,
                    float_share numeric,
                    total_mv numeric,
                    circ_mv numeric,
                    free_share numeric,
                    free_float_mv numeric,
                    amount numeric,
                    amount_median_20 numeric,
                    turnover_rate numeric,
                    turnover_rate_f numeric,
                    volume_ratio numeric,
                    unlock_30d numeric,
                    unlock_60d numeric,
                    unlock_90d numeric,
                    recent_reduction_flag boolean default false,
                    supply_profile_label text not null,
                    data_version text not null default 'v1.0',
                    created_at timestamptz not null,
                    primary key (as_of_date, ts_code)
                )
                """
            )
            conn.execute("alter table supply_profile_snapshot add column if not exists total_share numeric")
            conn.execute("alter table supply_profile_snapshot add column if not exists float_share numeric")
            conn.execute(
                """
                create table if not exists ths_index_master (
                    ths_code text primary key,
                    name text not null,
                    type text not null,
                    exchange text,
                    count integer,
                    list_date text,
                    sync_time timestamptz not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists ths_concept_member_snapshot (
                    snapshot_date text not null,
                    ths_code text not null,
                    ths_name text not null,
                    ths_type text not null,
                    ts_code text not null,
                    stock_name text,
                    is_new text,
                    sync_time timestamptz not null,
                    primary key (snapshot_date, ths_code, ts_code)
                )
                """
            )
            conn.execute(
                """
                create table if not exists stock_business_segment (
                    ts_code text not null,
                    period text not null,
                    ann_date_or_available_date text not null,
                    bz_code text,
                    bz_item text not null,
                    bz_sales numeric,
                    bz_profit numeric,
                    bz_cost numeric,
                    source text not null default 'tushare.fina_mainbz_vip',
                    sync_time timestamptz not null,
                    primary key (ts_code, period, bz_item)
                )
                """
            )
            conn.execute(
                """
                create table if not exists stock_income_statement (
                    ts_code text not null,
                    end_date text not null,
                    available_date text not null,
                    ann_date text,
                    f_ann_date text,
                    total_revenue numeric,
                    oper_cost numeric,
                    n_income_attr_p numeric,
                    update_flag text,
                    raw_json jsonb not null,
                    sync_time timestamptz not null,
                    primary key (ts_code, end_date, available_date)
                )
                """
            )
            conn.execute("alter table stock_income_statement add column if not exists oper_cost numeric")
            conn.execute(
                """
                create table if not exists stock_cashflow_statement (
                    ts_code text not null,
                    end_date text not null,
                    available_date text not null,
                    ann_date text,
                    f_ann_date text,
                    n_cashflow_act numeric,
                    update_flag text,
                    raw_json jsonb not null,
                    sync_time timestamptz not null,
                    primary key (ts_code, end_date, available_date)
                )
                """
            )
            conn.execute(
                """
                create table if not exists stock_fina_indicator (
                    ts_code text not null,
                    end_date text not null,
                    available_date text not null,
                    ann_date text,
                    or_yoy numeric,
                    op_yoy numeric,
                    netprofit_yoy numeric,
                    profit_dedt numeric,
                    dt_netprofit_yoy numeric,
                    grossprofit_margin numeric,
                    raw_json jsonb not null,
                    sync_time timestamptz not null,
                    primary key (ts_code, end_date, available_date)
                )
                """
            )
            conn.execute("alter table stock_fina_indicator add column if not exists profit_dedt numeric")
            conn.execute(
                """
                create table if not exists stock_forecast (
                    ts_code text not null,
                    end_date text,
                    available_date text not null,
                    ann_date text not null,
                    type text,
                    p_change_min numeric,
                    p_change_max numeric,
                    net_profit_min numeric,
                    net_profit_max numeric,
                    summary text,
                    change_reason text,
                    raw_json jsonb not null,
                    sync_time timestamptz not null,
                    primary key (ts_code, ann_date, available_date)
                )
                """
            )
            conn.execute(
                """
                create table if not exists stock_express (
                    ts_code text not null,
                    end_date text not null,
                    available_date text not null,
                    ann_date text not null,
                    revenue numeric,
                    operate_profit numeric,
                    total_profit numeric,
                    n_income numeric,
                    total_assets numeric,
                    total_hldr_eqy_exc_min_int numeric,
                    diluted_eps numeric,
                    diluted_roe numeric,
                    yoy_net_profit numeric,
                    bps numeric,
                    open_net_assets numeric,
                    open_bps numeric,
                    perf_summary text,
                    update_flag text,
                    raw_json jsonb not null,
                    sync_time timestamptz not null,
                    primary key (ts_code, end_date, available_date)
                )
                """
            )
            conn.execute(
                """
                create table if not exists stock_share_float (
                    ts_code text not null,
                    ann_date text,
                    available_date text,
                    float_date text not null,
                    float_share numeric,
                    float_ratio numeric,
                    holder_name text,
                    share_type text,
                    raw_json jsonb not null,
                    sync_time timestamptz not null,
                    primary key (ts_code, float_date, holder_name, share_type)
                )
                """
            )
            conn.execute(
                """
                create table if not exists stock_holder_trade (
                    trade_key text primary key,
                    ts_code text not null,
                    ann_date text not null,
                    holder_name text,
                    holder_type text,
                    in_de text,
                    change_vol numeric,
                    change_ratio numeric,
                    after_share numeric,
                    after_ratio numeric,
                    avg_price numeric,
                    total_share numeric,
                    raw_json jsonb not null,
                    sync_time timestamptz not null
                )
                """
            )
            conn.execute("alter table stock_holder_trade add column if not exists trade_key text")
            conn.execute(
                """
                create table if not exists stock_event_sync_status (
                    ts_code text not null,
                    source_name text not null,
                    status text not null,
                    row_count integer not null default 0,
                    message text,
                    sync_time timestamptz not null,
                    primary key (ts_code, source_name)
                )
                """
            )
            conn.execute(
                """
                create table if not exists ai_stock_research (
                    analysis_id text primary key,
                    ts_code text not null,
                    as_of_date text not null,
                    created_at timestamptz not null,
                    priority text not null,
                    result_markdown text not null,
                    model text not null,
                    prompt_version text not null default 'v1.0',
                    review_lookback_days integer not null default 20,
                    aprev2_snapshot_id text,
                    company_snapshot_id text,
                    leadership_snapshot_id text,
                    supply_snapshot_id text,
                    concept_snapshot_date text,
                    concept_temporal_status text not null default 'PIT_SAFE',
                    web_search_used boolean not null default false,
                    source_manifest_json jsonb not null,
                    uncertainty_json jsonb not null,
                    status text not null default 'READY',
                    stale_reason text
                )
                """
            )
            conn.execute(
                """
                create table if not exists user_research_watchlist (
                    ts_code text not null,
                    as_of_date text not null,
                    added_date text not null,
                    user_note text,
                    research_status text not null default '待AI分析',
                    updated_at timestamptz not null,
                    primary key (as_of_date, ts_code)
                )
                """
            )
            conn.execute("alter table ai_stock_research add column if not exists ai_usage_json jsonb")
            conn.execute("alter table ai_stock_research add column if not exists ai_input_tokens integer")
            conn.execute("alter table ai_stock_research add column if not exists ai_output_tokens integer")
            conn.execute("alter table ai_stock_research add column if not exists ai_total_tokens integer")
            conn.execute("alter table ai_stock_research add column if not exists ai_elapsed_ms integer")

            conn.execute("create index if not exists idx_cand_sec_date on candidate_secondary_snapshot(as_of_date)")
            conn.execute("create index if not exists idx_ths_member_snap_stock on ths_concept_member_snapshot(snapshot_date, ts_code)")
            conn.execute("create index if not exists idx_ai_research_stock on ai_stock_research(ts_code, as_of_date)")

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
                    _nullable_float(record.get("total_share")),
                    _nullable_float(record.get("float_share")),
                    _nullable_float(record.get("free_share")),
                    _nullable_float(record.get("turnover_rate")),
                    _nullable_float(record.get("turnover_rate_f")),
                    _nullable_float(record.get("volume_ratio")),
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
                        asset_code, trade_date, total_share, float_share, free_share,
                        turnover_rate, turnover_rate_f, volume_ratio, total_mv,
                        circ_mv, limit_status, raw_json, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict(asset_code, trade_date) do update set
                        total_share = excluded.total_share,
                        float_share = excluded.float_share,
                        free_share = excluded.free_share,
                        turnover_rate = excluded.turnover_rate,
                        turnover_rate_f = excluded.turnover_rate_f,
                        volume_ratio = excluded.volume_ratio,
                        total_mv = excluded.total_mv,
                        circ_mv = excluded.circ_mv,
                        limit_status = excluded.limit_status,
                        raw_json = excluded.raw_json,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
            conn.commit()

    def save_income_statements(self, df: pd.DataFrame) -> int:
        now = _now()
        rows = []
        for record in df.to_dict(orient="records"):
            available_date = _available_date(record)
            if not available_date:
                continue
            rows.append((
                str(record["ts_code"]),
                str(record["end_date"]),
                available_date,
                _nullable_text(record.get("ann_date")),
                _nullable_text(record.get("f_ann_date")),
                _nullable_float(record.get("total_revenue")),
                _nullable_float(record.get("oper_cost")),
                _nullable_float(record.get("n_income_attr_p")),
                _nullable_text(record.get("update_flag")),
                json_dumps(record),
                now,
            ))
        if not rows:
            return 0
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into stock_income_statement (
                        ts_code, end_date, available_date, ann_date, f_ann_date,
                        total_revenue, oper_cost, n_income_attr_p, update_flag, raw_json, sync_time
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict (ts_code, end_date, available_date) do update set
                        ann_date = excluded.ann_date,
                        f_ann_date = excluded.f_ann_date,
                        total_revenue = excluded.total_revenue,
                        oper_cost = excluded.oper_cost,
                        n_income_attr_p = excluded.n_income_attr_p,
                        update_flag = excluded.update_flag,
                        raw_json = excluded.raw_json,
                        sync_time = excluded.sync_time
                    """,
                    rows,
                )
            conn.commit()
        return len(rows)

    def save_cashflow_statements(self, df: pd.DataFrame) -> int:
        now = _now()
        rows = []
        for record in df.to_dict(orient="records"):
            available_date = _available_date(record)
            if not available_date:
                continue
            rows.append((
                str(record["ts_code"]),
                str(record["end_date"]),
                available_date,
                _nullable_text(record.get("ann_date")),
                _nullable_text(record.get("f_ann_date")),
                _nullable_float(record.get("n_cashflow_act")),
                _nullable_text(record.get("update_flag")),
                json_dumps(record),
                now,
            ))
        if not rows:
            return 0
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into stock_cashflow_statement (
                        ts_code, end_date, available_date, ann_date, f_ann_date,
                        n_cashflow_act, update_flag, raw_json, sync_time
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict (ts_code, end_date, available_date) do update set
                        ann_date = excluded.ann_date,
                        f_ann_date = excluded.f_ann_date,
                        n_cashflow_act = excluded.n_cashflow_act,
                        update_flag = excluded.update_flag,
                        raw_json = excluded.raw_json,
                        sync_time = excluded.sync_time
                    """,
                    rows,
                )
            conn.commit()
        return len(rows)

    def save_fina_indicators(self, df: pd.DataFrame) -> int:
        now = _now()
        rows = []
        for record in df.to_dict(orient="records"):
            available_date = _available_date(record)
            if not available_date:
                continue
            rows.append((
                str(record["ts_code"]),
                str(record["end_date"]),
                available_date,
                _nullable_text(record.get("ann_date")),
                _nullable_float(record.get("or_yoy")),
                _nullable_float(record.get("op_yoy")),
                _nullable_float(record.get("netprofit_yoy")),
                _nullable_float(record.get("profit_dedt")),
                _nullable_float(record.get("dt_netprofit_yoy")),
                _nullable_float(record.get("grossprofit_margin")),
                json_dumps(record),
                now,
            ))
        if not rows:
            return 0
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into stock_fina_indicator (
                        ts_code, end_date, available_date, ann_date, or_yoy, op_yoy,
                        netprofit_yoy, profit_dedt, dt_netprofit_yoy, grossprofit_margin, raw_json, sync_time
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict (ts_code, end_date, available_date) do update set
                        ann_date = excluded.ann_date,
                        or_yoy = excluded.or_yoy,
                        op_yoy = excluded.op_yoy,
                        netprofit_yoy = excluded.netprofit_yoy,
                        profit_dedt = excluded.profit_dedt,
                        dt_netprofit_yoy = excluded.dt_netprofit_yoy,
                        grossprofit_margin = excluded.grossprofit_margin,
                        raw_json = excluded.raw_json,
                        sync_time = excluded.sync_time
                    """,
                    rows,
                )
            conn.commit()
        return len(rows)

    def save_forecasts(self, df: pd.DataFrame) -> int:
        now = _now()
        rows = []
        for record in df.to_dict(orient="records"):
            available_date = _available_date(record)
            if not available_date:
                continue
            rows.append((
                str(record["ts_code"]),
                _nullable_text(record.get("end_date")),
                available_date,
                str(record["ann_date"]),
                _nullable_text(record.get("type")),
                _nullable_float(record.get("p_change_min")),
                _nullable_float(record.get("p_change_max")),
                _nullable_float(record.get("net_profit_min")),
                _nullable_float(record.get("net_profit_max")),
                _nullable_text(record.get("summary")),
                _nullable_text(record.get("change_reason")),
                json_dumps(record),
                now,
            ))
        if not rows:
            return 0
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into stock_forecast (
                        ts_code, end_date, available_date, ann_date, type,
                        p_change_min, p_change_max, net_profit_min, net_profit_max,
                        summary, change_reason, raw_json, sync_time
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict (ts_code, ann_date, available_date) do update set
                        end_date = excluded.end_date,
                        type = excluded.type,
                        p_change_min = excluded.p_change_min,
                        p_change_max = excluded.p_change_max,
                        net_profit_min = excluded.net_profit_min,
                        net_profit_max = excluded.net_profit_max,
                        summary = excluded.summary,
                        change_reason = excluded.change_reason,
                        raw_json = excluded.raw_json,
                        sync_time = excluded.sync_time
                    """,
                    rows,
                )
            conn.commit()
        return len(rows)

    def save_express_reports(self, df: pd.DataFrame, ts_code: str) -> int:
        now = _now()
        rows = []
        for record in df.to_dict(orient="records"):
            available_date = _nullable_text(record.get("ann_date"))
            end_date = _nullable_text(record.get("end_date"))
            if not available_date or not end_date:
                continue
            rows.append((
                str(record["ts_code"]),
                end_date,
                available_date,
                available_date,
                _nullable_float(record.get("revenue")),
                _nullable_float(record.get("operate_profit")),
                _nullable_float(record.get("total_profit")),
                _nullable_float(record.get("n_income")),
                _nullable_float(record.get("total_assets")),
                _nullable_float(record.get("total_hldr_eqy_exc_min_int")),
                _nullable_float(record.get("diluted_eps")),
                _nullable_float(record.get("diluted_roe")),
                _nullable_float(record.get("yoy_net_profit")),
                _nullable_float(record.get("bps")),
                _nullable_float(record.get("open_net_assets")),
                _nullable_float(record.get("open_bps")),
                _nullable_text(record.get("perf_summary")),
                _nullable_text(record.get("update_flag")),
                json_dumps(record),
                now,
            ))
        with self.connect() as conn:
            conn.execute("delete from stock_express where ts_code = %s", (ts_code,))
            if rows:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """
                        insert into stock_express (
                            ts_code, end_date, available_date, ann_date, revenue, operate_profit,
                            total_profit, n_income, total_assets, total_hldr_eqy_exc_min_int,
                            diluted_eps, diluted_roe, yoy_net_profit, bps, open_net_assets,
                            open_bps, perf_summary, update_flag, raw_json, sync_time
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                        on conflict (ts_code, end_date, available_date) do update set
                            revenue = excluded.revenue,
                            operate_profit = excluded.operate_profit,
                            total_profit = excluded.total_profit,
                            n_income = excluded.n_income,
                            total_assets = excluded.total_assets,
                            total_hldr_eqy_exc_min_int = excluded.total_hldr_eqy_exc_min_int,
                            diluted_eps = excluded.diluted_eps,
                            diluted_roe = excluded.diluted_roe,
                            yoy_net_profit = excluded.yoy_net_profit,
                            bps = excluded.bps,
                            open_net_assets = excluded.open_net_assets,
                            open_bps = excluded.open_bps,
                            perf_summary = excluded.perf_summary,
                            update_flag = excluded.update_flag,
                            raw_json = excluded.raw_json,
                            sync_time = excluded.sync_time
                        """,
                        rows,
                    )
            if rows:
                self.save_event_sync_status(conn, ts_code, "express_vip", "PASS", len(rows), None, now)
            conn.commit()
        return len(rows)

    def save_share_float_events(self, df: pd.DataFrame, ts_code: str) -> int:
        now = _now()
        rows = []
        for record in df.to_dict(orient="records"):
            float_date = _nullable_text(record.get("float_date"))
            if not float_date:
                continue
            rows.append((
                str(record["ts_code"]),
                _nullable_text(record.get("ann_date")),
                _nullable_text(record.get("ann_date")),
                float_date,
                _nullable_float(record.get("float_share")),
                _nullable_float(record.get("float_ratio")),
                _nullable_text(record.get("holder_name")) or "",
                _nullable_text(record.get("share_type")) or "",
                json_dumps(record),
                now,
            ))
        with self.connect() as conn:
            conn.execute("delete from stock_share_float where ts_code = %s", (ts_code,))
            if rows:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """
                        insert into stock_share_float (
                            ts_code, ann_date, available_date, float_date, float_share, float_ratio,
                            holder_name, share_type, raw_json, sync_time
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                        on conflict (ts_code, float_date, holder_name, share_type) do update set
                            ann_date = excluded.ann_date,
                            available_date = excluded.available_date,
                            float_share = excluded.float_share,
                            float_ratio = excluded.float_ratio,
                            raw_json = excluded.raw_json,
                            sync_time = excluded.sync_time
                        """,
                        rows,
                    )
            saved_count = conn.execute(
                "select count(*) as count from stock_share_float where ts_code = %s",
                (ts_code,),
            ).fetchone()["count"]
            self.save_event_sync_status(conn, ts_code, "share_float", "PASS", int(saved_count), None, now)
            conn.commit()
        return int(saved_count)

    def save_holder_trades(self, df: pd.DataFrame, ts_code: str) -> int:
        now = _now()
        rows = []
        for record in df.to_dict(orient="records"):
            ann_date = _nullable_text(record.get("ann_date"))
            if not ann_date:
                continue
            rows.append((
                _holder_trade_key(record),
                str(record["ts_code"]),
                ann_date,
                _nullable_text(record.get("holder_name")),
                _nullable_text(record.get("holder_type")),
                _nullable_text(record.get("in_de")),
                _nullable_float(record.get("change_vol")),
                _nullable_float(record.get("change_ratio")),
                _nullable_float(record.get("after_share")),
                _nullable_float(record.get("after_ratio")),
                _nullable_float(record.get("avg_price")),
                _nullable_float(record.get("total_share")),
                json_dumps(record),
                now,
            ))
        with self.connect() as conn:
            conn.execute("delete from stock_holder_trade where ts_code = %s", (ts_code,))
            if rows:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """
                        insert into stock_holder_trade (
                            trade_key, ts_code, ann_date, holder_name, holder_type, in_de, change_vol,
                            change_ratio, after_share, after_ratio, avg_price, total_share,
                            raw_json, sync_time
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                        on conflict (trade_key) do update set
                            ts_code = excluded.ts_code,
                            ann_date = excluded.ann_date,
                            holder_name = excluded.holder_name,
                            holder_type = excluded.holder_type,
                            in_de = excluded.in_de,
                            change_vol = excluded.change_vol,
                            change_ratio = excluded.change_ratio,
                            after_share = excluded.after_share,
                            after_ratio = excluded.after_ratio,
                            avg_price = excluded.avg_price,
                            total_share = excluded.total_share,
                            raw_json = excluded.raw_json,
                            sync_time = excluded.sync_time
                        """,
                        rows,
                    )
            saved_count = conn.execute(
                "select count(*) as count from stock_holder_trade where ts_code = %s",
                (ts_code,),
            ).fetchone()["count"]
            self.save_event_sync_status(conn, ts_code, "stk_holdertrade", "PASS", int(saved_count), None, now)
            conn.commit()
        return int(saved_count)

    def save_event_sync_status(
        self,
        conn: psycopg.Connection,
        ts_code: str,
        source_name: str,
        status: str,
        row_count: int,
        message: str | None,
        sync_time: datetime,
    ) -> None:
        conn.execute(
            """
            insert into stock_event_sync_status (ts_code, source_name, status, row_count, message, sync_time)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (ts_code, source_name) do update set
                status = excluded.status,
                row_count = excluded.row_count,
                message = excluded.message,
                sync_time = excluded.sync_time
            """,
            (ts_code, source_name, status, row_count, message, sync_time),
        )

    def mark_event_sync_status(
        self,
        ts_code: str,
        source_name: str,
        status: str,
        row_count: int = 0,
        message: str | None = None,
    ) -> None:
        with self.connect() as conn:
            self.save_event_sync_status(conn, ts_code, source_name, status, row_count, message, _now())
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
        limit: int | None = 50,
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

    def get_data_management_config(self) -> dict[str, Any]:
        defaults = {
            "enabled": True,
            "timezone": "Asia/Shanghai",
            "trading_days_only": True,
            "intraday_enabled": True,
            "intraday_interval_minutes": 30,
            "intraday_start_time": "09:30",
            "intraday_end_time": "15:30",
            "daily_enabled": True,
            "daily_run_times": ["18:00"],
            "concept_enabled": True,
            "concept_interval_hours": 24,
            "industry_enabled": True,
            "industry_interval_hours": 24,
            "quality_check_enabled": True,
            "retry_attempts": 3,
            "request_delay_seconds": 0.12,
            "stock_30m_enabled": True,
            "etf_30m_enabled": True,
            "sync_log_retention_days": 30,
            "sync_log_max_rows": 10000,
        }
        with self.connect() as conn:
            row = conn.execute(
                "select config_json, version, updated_at from screening_data_management_config where config_id = 1"
            ).fetchone()
        if not row:
            return {"config": defaults, "version": 0, "updated_at": None}
        config = {**defaults, **dict(row["config_json"] or {})}
        return {"config": config, "version": row["version"], "updated_at": row["updated_at"]}

    def save_data_management_config(self, config: dict[str, Any]) -> dict[str, Any]:
        current = self.get_data_management_config()
        version = int(current.get("version") or 0) + 1
        now = _now()
        with self.connect() as conn:
            conn.execute(
                """
                insert into screening_data_management_config (config_id, config_json, version, updated_at)
                values (1, %s::jsonb, %s, %s)
                on conflict (config_id) do update set
                    config_json = excluded.config_json,
                    version = excluded.version,
                    updated_at = excluded.updated_at
                """,
                (json_dumps(config), version, now),
            )
            conn.commit()
        return {"config": config, "version": version, "updated_at": now}

    def create_data_task(self, task_id: str, task_type: str, trade_date: str | None = None) -> None:
        now = _now()
        with self.connect() as conn:
            conn.execute(
                """
                insert into screening_data_task
                    (task_id, task_type, status, trade_date, created_at, updated_at)
                values (%s, %s, 'QUEUED', %s, %s, %s)
                """,
                (task_id, task_type, trade_date, now, now),
            )
            conn.commit()

    def update_data_task(self, task_id: str, **fields: Any) -> None:
        allowed = {
            "status", "progress", "stage_message", "trade_date", "summary_json",
            "error_message", "started_at", "completed_at",
        }
        updates = [(key, value) for key, value in fields.items() if key in allowed]
        if not updates:
            return
        assignments = ", ".join(f"{key} = %s::jsonb" if key == "summary_json" else f"{key} = %s" for key, _ in updates)
        values = [json_dumps(value) if key == "summary_json" else value for key, value in updates]
        values.extend([_now(), task_id])
        with self.connect() as conn:
            conn.execute(
                f"update screening_data_task set {assignments}, updated_at = %s where task_id = %s",
                values,
            )
            conn.commit()

    def request_data_task_cancel(self, task_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "update screening_data_task set cancel_requested = true, updated_at = %s where task_id = %s and status in ('QUEUED', 'RUNNING') returning task_id",
                (_now(), task_id),
            ).fetchone()
            conn.commit()
        return bool(row)

    def is_data_task_cancel_requested(self, task_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("select cancel_requested from screening_data_task where task_id = %s", (task_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def list_data_tasks(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select task_id, task_type, status, progress, stage_message, trade_date,
                       summary_json, error_message, cancel_requested, started_at, completed_at, created_at, updated_at
                from screening_data_task
                order by created_at desc
                limit %s
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_failed_minute_items(self, trade_date: str | None = None, asset_type: str | None = None, limit: int | None = None, offset: int = 0, search: str | None = None) -> list[dict[str, Any]]:
        clauses = ["s.status in ('FAILED', 'EMPTY', 'PARTIAL', 'PENDING')"]
        params: list[Any] = []
        if trade_date:
            clauses.append("s.trade_date = %s"); params.append(trade_date)
        if asset_type:
            clauses.append("a.asset_type = %s"); params.append(asset_type)
        if search:
            clauses.append("(a.asset_code ilike %s or a.name ilike %s)"); params.extend([f"%{search}%", f"%{search}%"])
        pagination = "" if limit is None else " limit %s offset %s"
        query_params = params if limit is None else [*params, limit, offset]
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                select s.asset_code, a.name, a.asset_type, s.trade_date, s.expected_slots,
                       s.actual_slots, s.status, s.attempt_count, s.last_error, s.updated_at
                from screening_min_sync_status s
                join screening_asset_master a on a.asset_code = s.asset_code
                where {' and '.join(clauses)}
                order by s.trade_date desc, s.asset_code
                {pagination}
                """,
                query_params,
            ).fetchall()
        return [dict(row) for row in rows]

    def count_failed_minute_items(self, trade_date: str | None = None, asset_type: str | None = None, search: str | None = None) -> int:
        clauses = ["s.status in ('FAILED', 'EMPTY', 'PARTIAL', 'PENDING')"]
        params: list[Any] = []
        if trade_date:
            clauses.append("s.trade_date = %s"); params.append(trade_date)
        if asset_type:
            clauses.append("a.asset_type = %s"); params.append(asset_type)
        if search:
            clauses.append("(a.asset_code ilike %s or a.name ilike %s)"); params.extend([f"%{search}%", f"%{search}%"])
        with self.connect() as conn:
            row = conn.execute(
                f"""
                select count(*) as total
                from screening_min_sync_status s
                join screening_asset_master a on a.asset_code = s.asset_code
                where {' and '.join(clauses)}
                """,
                params,
            ).fetchone()
        return int((row or {}).get("total") or 0)

    def get_min_sync_status(self, asset_code: str, trade_date: str, freq: str = "30min") -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                select asset_code, trade_date, freq, expected_slots, actual_slots,
                       status, attempt_count, last_error, updated_at
                from screening_min_sync_status
                where asset_code = %s and trade_date = %s and freq = %s
                """,
                (asset_code, trade_date, freq),
            ).fetchone()
        return dict(row) if row else None

    def list_sync_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select id, trade_date, sync_type, status, message, created_at
                from screening_sync_log
                order by created_at desc
                limit %s
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def prune_sync_logs(self, retention_days: int, max_rows: int) -> dict[str, int]:
        if retention_days < 1 or max_rows < 1:
            raise ValueError("日志保留天数和最大条数必须大于 0")
        with self.connect() as conn:
            old_rows = conn.execute(
                "delete from screening_sync_log where created_at < now() - (%s * interval '1 day')",
                (retention_days,),
            ).rowcount
            overflow_rows = conn.execute(
                """
                delete from screening_sync_log
                where id in (
                    select id from screening_sync_log
                    order by created_at desc
                    offset %s
                )
                """,
                (max_rows,),
            ).rowcount
            conn.commit()
        return {"deleted_by_age": int(old_rows or 0), "deleted_by_count": int(overflow_rows or 0)}

    def get_data_quality_report(self) -> dict[str, Any]:
        """Return full-dataset coverage facts used by the data-management UI."""
        with self.connect() as conn:
            asset_rows = conn.execute(
                "select asset_type, count(*) as count from screening_asset_master group by asset_type order by asset_type"
            ).fetchall()
            latest_daily = conn.execute(
                """
                select max(trade_date) as trade_date,
                       count(*) filter (where asset_type = 'stock') as stock_rows,
                       count(*) filter (where asset_type = 'etf') as etf_rows,
                       count(distinct asset_code) filter (where asset_type = 'stock') as stock_assets,
                       count(distinct asset_code) filter (where asset_type = 'etf') as etf_assets
                from screening_daily_bar
                where trade_date = (select max(trade_date) from screening_daily_bar)
                """
            ).fetchone()
            latest_minute = conn.execute(
                """
                select max(substr(trade_time, 1, 10)) as trade_date,
                       max(trade_time) as trade_time,
                       count(*) as rows,
                       count(distinct asset_code) as assets,
                       count(distinct trade_time) as slots
                from screening_min_bar
                where freq = '30min'
                """
            ).fetchone()
            failures = conn.execute(
                """
                select count(*) filter (where status in ('FAIL', 'FAILED')) as failed,
                       count(*) as total
                from screening_sync_log
                """
            ).fetchone()
            min_status = conn.execute(
                """
                select status, count(*) as count
                from screening_min_sync_status
                where trade_date = (select max(trade_date) from screening_min_sync_status)
                group by status
                order by status
                """
            ).fetchall()

        assets = {str(row["asset_type"]): int(row["count"] or 0) for row in asset_rows}
        daily = dict(latest_daily or {})
        minute = dict(latest_minute or {})
        failures_data = dict(failures or {})
        minute_status = {str(row["status"]): int(row["count"] or 0) for row in min_status}
        issues: list[dict[str, Any]] = []
        if not assets:
            issues.append({"code": "ASSET_MASTER_EMPTY", "severity": "BLOCKING", "message": "证券主数据为空"})
        if not daily.get("trade_date"):
            issues.append({"code": "DAILY_DATA_EMPTY", "severity": "BLOCKING", "message": "日线行情为空"})
        if not minute.get("trade_date"):
            issues.append({"code": "MINUTE_DATA_EMPTY", "severity": "WARNING", "message": "30 分钟行情为空"})
        if int(failures_data.get("failed") or 0) > 0:
            issues.append({"code": "SYNC_FAILURES_EXIST", "severity": "WARNING", "message": f"同步日志中存在 {failures_data['failed']} 条失败记录"})
        if minute_status.get("PARTIAL", 0) or minute_status.get("FAILED", 0) or minute_status.get("EMPTY", 0):
            issues.append({"code": "MINUTE_COVERAGE_INCOMPLETE", "severity": "WARNING", "message": "最新分钟线批次存在未完成资产"})
        return {
            "status": "BLOCKING" if any(item["severity"] == "BLOCKING" for item in issues) else "WARNING" if issues else "READY",
            "assets": assets,
            "daily": daily,
            "minute": minute,
            "sync_logs": failures_data,
            "minute_status": minute_status,
            "issues": issues,
        }

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

    def get_intraday_synthetic_daily_bar(
        self,
        asset_code: str,
        adjust: str = "qfq",
        now: datetime | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
        trade_date = current.strftime("%Y%m%d")
        expected_slots = _completed_30m_slots(current.time())
        is_weekday = current.weekday() < 5
        is_after_close = current.time() >= dtime(15, 0)
        meta: dict[str, Any] = {
            "enabled": True,
            "trade_date": trade_date,
            "source": "intraday_30m_synthetic",
            "status": "NOT_READY",
            "is_weekday": is_weekday,
            "is_after_close": is_after_close,
            "expected_slots": expected_slots,
            "present_slots": [],
            "missing_slots": expected_slots,
            "bar": None,
        }
        if not is_weekday:
            meta["status"] = "NON_TRADING_DAY"
            meta["missing_slots"] = []
            return None, meta
        if not expected_slots:
            meta["status"] = "NO_COMPLETED_30M_SLOT"
            return None, meta

        with self.connect() as conn:
            official = conn.execute(
                """
                select 1
                from screening_daily_bar
                where asset_code = %s and trade_date = %s
                limit 1
                """,
                (asset_code, trade_date),
            ).fetchone()
            if official:
                meta["status"] = "OFFICIAL_DAILY_EXISTS"
                meta["missing_slots"] = []
                return None, meta

            rows = conn.execute(
                """
                select trade_time, open, high, low, close, vol, amount
                from screening_min_bar
                where asset_code = %s
                  and freq = '30min'
                  and trade_time >= %s
                  and trade_time <= %s
                order by trade_time asc
                """,
                (
                    asset_code,
                    f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]} 00:00:00",
                    f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]} 23:59:59",
                ),
            ).fetchall()
            adj_rows = conn.execute(
                "select trade_date, adj_factor from screening_adj_factor where asset_code = %s order by trade_date asc",
                (asset_code,),
            ).fetchall()

        by_slot: dict[str, Any] = {}
        for row in rows:
            slot = str(row["trade_time"])[11:16]
            by_slot[slot] = row
        present_slots = [slot for slot in expected_slots if slot in by_slot]
        missing_slots = [slot for slot in expected_slots if slot not in by_slot]
        meta["present_slots"] = present_slots
        meta["missing_slots"] = missing_slots
        if not present_slots:
            meta["status"] = "INCOMPLETE_30M" if is_after_close else "INTRADAY_PARTIAL"
            return None, meta
        if missing_slots:
            meta["status"] = "INCOMPLETE_30M" if is_after_close else "INTRADAY_PARTIAL"

        completed_rows = [by_slot[slot] for slot in present_slots]
        first = completed_rows[0]
        last = completed_rows[-1]
        op = float(first["open"])
        hi = max(float(row["high"]) for row in completed_rows)
        lo = min(float(row["low"]) for row in completed_rows)
        cl = float(last["close"])
        vol = sum(float(row["vol"]) for row in completed_rows)
        amt = sum(float(row["amount"]) for row in completed_rows)

        adjust_status = "none"
        if adjust == "qfq":
            # 当天官方复权因子通常尚未生成；用上一条已落库因子保持与历史 qfq 坐标一致。
            latest_adj = float(adj_rows[-1]["adj_factor"]) if adj_rows else 1.0
            if latest_adj > 0:
                ratio = latest_adj / latest_adj
                op = round(op * ratio, 2)
                hi = round(hi * ratio, 2)
                lo = round(lo * ratio, 2)
                cl = round(cl * ratio, 2)
                adjust_status = "estimated_with_latest_adj_factor"

        dt = datetime.strptime(trade_date, "%Y%m%d").replace(tzinfo=UTC)
        bar = {
            "timestamp": int(dt.timestamp() * 1000),
            "trade_date": trade_date,
            "open": op,
            "high": hi,
            "low": lo,
            "close": cl,
            "volume": vol,
            "turnover": amt,
            "source": "intraday_30m_synthetic",
            "is_synthetic": True,
            "completed_30m_slots": expected_slots,
            "last_30m_slot": expected_slots[-1],
            "adjust_status": adjust_status,
        }
        meta["status"] = "READY"
        meta["bar"] = bar
        meta["adjust_status"] = adjust_status
        return bar, meta




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

    def count_min_slots(self, asset_code: str, trade_date: str, freq: str = "30min") -> int:
        normalized_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        with self.connect() as conn:
            row = conn.execute(
                """
                select count(distinct trade_time) as slots
                from screening_min_bar
                where asset_code = %s and freq = %s
                  and trade_time >= %s and trade_time < (%s::date + interval '1 day')::text
                """,
                (asset_code, freq, normalized_date, normalized_date),
            ).fetchone()
        return int((row or {}).get("slots") or 0)

    def save_min_sync_status(
        self,
        asset_code: str,
        trade_date: str,
        expected_slots: int,
        actual_slots: int,
        status: str,
        error: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into screening_min_sync_status
                    (asset_code, trade_date, freq, expected_slots, actual_slots,
                     status, attempt_count, last_error, updated_at)
                values (%s, %s, '30min', %s, %s, %s, 1, %s, %s)
                on conflict (asset_code, trade_date, freq) do update set
                    expected_slots = excluded.expected_slots,
                    actual_slots = excluded.actual_slots,
                    status = excluded.status,
                    attempt_count = screening_min_sync_status.attempt_count + 1,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (asset_code, trade_date, expected_slots, actual_slots, status, error, _now()),
            )
            conn.commit()

    def validate_min_sync_date(self, trade_date: str, asset_type: str | None = None) -> dict[str, Any]:
        clauses = ["a.asset_type = %s"] if asset_type else []
        params: list[Any] = [trade_date] + ([asset_type] if asset_type else [])
        where = "and " + " and ".join(clauses) if clauses else ""
        with self.connect() as conn:
            row = conn.execute(
                f"""
                select count(*) as total_assets,
                       count(*) filter (where s.status = 'COMPLETE') as complete_assets,
                       count(*) filter (where s.status = 'INACTIVE') as inactive_assets,
                       count(*) filter (where s.status = 'PARTIAL') as partial_assets,
                       count(*) filter (where s.status in ('FAILED', 'RATE_LIMITED', 'EMPTY')) as failed_assets,
                       count(*) filter (where s.status = 'PENDING') as pending_assets
                from screening_asset_master a
                left join screening_min_sync_status s
                  on s.asset_code = a.asset_code and s.trade_date = %s and s.freq = '30min'
                where 1=1 {where}
                """,
                params,
            ).fetchone()
        result = dict(row or {})
        result["complete"] = (
            int(result.get("total_assets") or 0) > 0
            and int(result.get("complete_assets") or 0) + int(result.get("inactive_assets") or 0) == int(result.get("total_assets") or 0)
        )
        return result


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

        latest_min_date = str(max_min)[:10].replace("-", "") if max_min else None
        latest_open_date = max(filter(None, (max_daily, latest_min_date)), default=None)

        return {
            # 日线日期必须来自完整 screening_daily_bar，不能被分钟线日期冒充。
            "daily_market_date": max_daily or "未知",
            "official_daily_date": max_daily or "未知",
            # 对外“最新行情”可以使用当天已落库的 30 分钟数据；正式日线日期仍单独保留。
            "latest_open_trade_date": latest_open_date or "未知",
            "intraday_market_date": latest_min_date or "未知",
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
                _membership_key(item, source_version),
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
            conn.execute(
                "delete from industry_membership_history where source_version = %s",
                (source_version,),
            )
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into industry_membership_history (
                        membership_key, ts_code, l1_code, l1_name, l2_code, l2_name, l3_code, l3_name,
                        in_date, out_date, source_version, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (membership_key) do update set
                        ts_code = excluded.ts_code,
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
        config_version: str = "A_PRE_V2_20260828_V1",
        run_name: str | None = None,
        notes: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into early_turn_run (run_id, trade_date, config_version, started_at, status, run_name, notes)
                values (%s, %s, %s, %s, 'RUNNING', %s, %s)
                on conflict (run_id) do nothing
                """,
                (run_id, trade_date, config_version, _now(), run_name, notes),
            )
            conn.commit()

    def reset_early_turn_run(self, run_id: str, trade_date: str, config_version: str, run_name: str | None = None, notes: str | None = None) -> list[str]:
        """清空既有批次结果并将同一批次重置为运行中，返回原批次股票范围。"""
        with self.connect() as conn:
            codes = [r["ts_code"] for r in conn.execute(
                "select distinct ts_code from early_turn_result where run_id = %s order by ts_code", (run_id,)
            ).fetchall()]
            existing = conn.execute("select run_id from early_turn_run where run_id = %s", (run_id,)).fetchone()
            if not existing:
                raise ValueError(f"early-turn run not found: {run_id}")
            conn.execute("delete from early_turn_result where run_id = %s", (run_id,))
            conn.execute(
                """
                update early_turn_run
                set trade_date = %s, config_version = %s, started_at = %s,
                    finished_at = null, status = 'RUNNING', summary_json = '{}'::jsonb,
                    error_message = null,
                    run_name = coalesce(%s, run_name), notes = coalesce(%s, notes)
                where run_id = %s
                """,
                (trade_date, config_version, _now(), run_name, notes, run_id),
            )
            conn.commit()
            return codes

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
            conn.execute("alter table early_turn_result add column if not exists turn_episode_state text")
            conn.execute("alter table early_turn_result add column if not exists signal_status text")
            conn.execute("alter table early_turn_result add column if not exists entry_extension_state text")
            conn.execute("alter table early_turn_result add column if not exists first_trigger_date text")
            conn.execute("alter table early_turn_result add column if not exists first_trigger_close numeric")
            conn.execute("alter table early_turn_result add column if not exists return_since_first_trigger numeric")
            conn.execute("alter table early_turn_result add column if not exists structural_damage_flag boolean default false")

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
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def get_all_early_turn_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select r.run_id, r.trade_date, r.run_name, r.notes, r.started_at, r.finished_at, r.status,
                       count(res.ts_code) as candidate_count
                from early_turn_run r
                left join early_turn_result res on r.run_id = res.run_id
                group by r.run_id, r.trade_date, r.run_name, r.notes, r.started_at, r.finished_at, r.status
                order by r.started_at desc
                limit %s
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "run_id": r["run_id"],
                    "trade_date": r["trade_date"],
                    "run_name": r.get("run_name") or f"选股记录 ({r['trade_date']})",
                    "notes": r.get("notes") or "",
                    "started_at": r["started_at"].isoformat() if r.get("started_at") else None,
                    "status": r["status"],
                    "candidate_count": r.get("candidate_count") or 0,
                }
                for r in rows
            ]

    def delete_early_turn_run(self, run_id: str) -> int:
        """删除一个批次及其全部逐股技术快照，返回被删除的股票快照数量。"""
        with self.connect() as conn:
            existing = conn.execute(
                "select run_id from early_turn_run where run_id = %s", (run_id,)
            ).fetchone()
            if not existing:
                raise ValueError(f"early-turn run not found: {run_id}")
            deleted_result_count = conn.execute(
                "delete from early_turn_result where run_id = %s", (run_id,)
            ).rowcount
            conn.execute("delete from early_turn_run where run_id = %s", (run_id,))
            conn.commit()
            return int(deleted_result_count or 0)

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
                r.get("turn_episode_state", "PRE_FIRST_TURN"),
                r.get("signal_status", r["state"]),
                r.get("entry_extension_state", "NORMAL"),
                r.get("first_trigger_date"),
                r.get("first_trigger_close"),
                r.get("return_since_first_trigger"),
                r.get("structural_damage_flag", False),
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
                        reasons_json, first_selected_date, turn_episode_state, signal_status,
                        entry_extension_state, first_trigger_date, first_trigger_close,
                        return_since_first_trigger, structural_damage_flag, created_at
                    )
                    values (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s::jsonb, %s::jsonb,
                        %s::jsonb, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s
                    )
                    on conflict (run_id, ts_code) do update set
                        total_score = excluded.total_score,
                        state = excluded.state,
                        background_type = excluded.background_type,
                        selected = excluded.selected,
                        is_overextended = excluded.is_overextended,
                        features_json = excluded.features_json,
                        score_detail_json = excluded.score_detail_json,
                        reasons_json = excluded.reasons_json,
                        first_selected_date = excluded.first_selected_date,
                        turn_episode_state = excluded.turn_episode_state,
                        signal_status = excluded.signal_status,
                        entry_extension_state = excluded.entry_extension_state,
                        first_trigger_date = excluded.first_trigger_date,
                        first_trigger_close = excluded.first_trigger_close,
                        return_since_first_trigger = excluded.return_since_first_trigger,
                        structural_damage_flag = excluded.structural_damage_flag
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
        concept: str | None = None,
        ts_codes: list[str] | None = None,
        exclude_st: bool = False,
        fundamental_state: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_concept_counts: bool = False,
    ) -> dict[str, Any]:
        where_clauses = ["r.run_id = %s"]
        params: list[Any] = [run_id]
        concept_snapshot_date: str | None = None

        with self.connect() as conn:
            run_row = conn.execute(
                "select trade_date from early_turn_run where run_id = %s",
                (run_id,),
            ).fetchone()
            run_trade_date = run_row["trade_date"] if run_row else None
            if run_trade_date:
                snap_row = conn.execute(
                    """
                    select snapshot_date
                    from ths_concept_member_snapshot
                    where snapshot_date <= %s
                    order by snapshot_date desc
                    limit 1
                    """,
                    (run_trade_date,),
                ).fetchone()
                concept_snapshot_date = snap_row["snapshot_date"] if snap_row else None
            if not concept_snapshot_date:
                snap_row = conn.execute(
                    "select snapshot_date from ths_concept_member_snapshot order by snapshot_date desc limit 1"
                ).fetchone()
                concept_snapshot_date = snap_row["snapshot_date"] if snap_row else None

            def add_base_filters(
                clauses: list[str], values: list[Any], include_industry: bool = True,
                include_concept: bool = True, include_fundamental: bool = True,
            ) -> None:
                # OUTSIDE_A_PRE 仅用于生命周期回放，不能进入用户侧的 A-Pre
                # 股票列表、筛选计数或基本面研究范围。
                clauses.append("r.state <> 'OUTSIDE_A_PRE'")
                if state and state != "ALL":
                    clauses.append("r.state = %s")
                    values.append(state)
                if background_type and background_type != "ALL":
                    clauses.append("r.background_type = %s")
                    values.append(background_type)
                if min_score is not None:
                    clauses.append("r.total_score >= %s")
                    values.append(min_score)
                if ts_codes is not None:
                    clauses.append("r.ts_code = any(%s)")
                    values.append(ts_codes)
                if exclude_st:
                    clauses.append("coalesce(a.name, '') not ilike 'ST%%' and coalesce(a.name, '') not ilike '*ST%%'")
                if include_industry and industry and industry != "ALL":
                    clauses.append("a.raw_json->>'industry' = %s")
                    values.append(industry)
                if query_text:
                    clauses.append("(r.ts_code ilike %s or a.name ilike %s)")
                    q_param = f"%{query_text.strip()}%"
                    values.extend([q_param, q_param])
                if include_concept and concept and concept != "ALL":
                    if not concept_snapshot_date:
                        clauses.append("false")
                    else:
                        clauses.append(
                            """
                            exists (
                                select 1
                                from ths_concept_member_snapshot cm
                                left join ths_index_master im on im.ths_code = cm.ths_code
                                where cm.snapshot_date = %s
                                  and cm.ts_code = r.ts_code
                                  and coalesce(im.name, cm.ths_name) = %s
                            )
                            """
                        )
                        values.extend([concept_snapshot_date, concept])
                if include_fundamental and fundamental_state and fundamental_state != "ALL":
                    if fundamental_state == "UNRESEARCHED":
                        clauses.append("e.ts_code is null")
                    else:
                        clauses.append("e.fundamental_filter_state = %s")
                        values.append(fundamental_state)

            add_base_filters(where_clauses, params)

            where_sql = " where " + " and ".join(where_clauses)

            count_sql = f"""
                select count(*) as cnt
                from early_turn_result r
                left join screening_asset_master a on a.asset_code = r.ts_code
                left join early_turn_run er on er.run_id = r.run_id
                left join company_evidence_snapshot e on e.as_of_date = er.trade_date and e.ts_code = r.ts_code
                {where_sql}
            """

            pagination_sql = "limit %s offset %s" if limit is not None else ""
            data_sql = f"""
                select r.run_id, r.ts_code, r.trade_date, r.total_score, r.state,
                       r.background_type, r.selected, r.is_overextended,
                       r.features_json, r.score_detail_json, r.reasons_json,
                       coalesce(
                           r.first_selected_date,
                           (select min(prev.trade_date) from early_turn_result prev
                            where prev.ts_code = r.ts_code and prev.selected = true
                              and prev.trade_date <= r.trade_date)
                       ) as first_selected_date,
                       r.turn_episode_state, r.signal_status,
                       r.entry_extension_state, r.first_trigger_date, r.first_trigger_close,
                       r.return_since_first_trigger, r.structural_damage_flag,
                       e.fundamental_filter_state, e.fundamental_filter_reasons_json,
                       a.name, a.asset_type,
                       a.raw_json->>'industry' as industry,
                       a.raw_json->>'main_business' as main_business
                from early_turn_result r
                left join screening_asset_master a on a.asset_code = r.ts_code
                left join early_turn_run er on er.run_id = r.run_id
                left join company_evidence_snapshot e on e.as_of_date = er.trade_date and e.ts_code = r.ts_code
                {where_sql}
                order by r.total_score desc, r.ts_code asc
                {pagination_sql}
            """

            total = conn.execute(count_sql, params).fetchone()["cnt"]
            data_params = params + ([limit, offset] if limit is not None else [])
            rows = conn.execute(data_sql, data_params).fetchall()
            
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

            # 行业分布 counts 统计 (忽略当前 industry 筛选，但保留 state/bg_type/min_score/query_text/concept 筛选)
            ind_where_clauses = ["r.run_id = %s"]
            ind_params = [run_id]
            add_base_filters(ind_where_clauses, ind_params, include_industry=False, include_concept=True)
                
            ind_where_sql = " where " + " and ".join(ind_where_clauses)
            
            industry_sql = f"""
                select a.raw_json->>'industry' as ind, count(*) as cnt
                from early_turn_result r
                left join screening_asset_master a on a.asset_code = r.ts_code
                left join early_turn_run er on er.run_id = r.run_id
                left join company_evidence_snapshot e on e.as_of_date = er.trade_date and e.ts_code = r.ts_code
                {ind_where_sql}
                group by ind
            """
            ind_rows = conn.execute(industry_sql, ind_params).fetchall()
            industry_counts = {r["ind"]: r["cnt"] for r in ind_rows if r["ind"]}

            concept_counts: dict[str, int] = {}
            if concept_snapshot_date:
                concept_where_clauses = ["r.run_id = %s"]
                concept_params: list[Any] = [run_id]
                add_base_filters(concept_where_clauses, concept_params, include_industry=True, include_concept=False)
                concept_where_sql = " where " + " and ".join(concept_where_clauses)
                concept_rows = conn.execute(
                    f"""
                    select coalesce(im.name, cm.ths_name) as concept_name, count(r.ts_code) as cnt
                    from early_turn_result r
                    left join screening_asset_master a on a.asset_code = r.ts_code
                    left join early_turn_run er on er.run_id = r.run_id
                    left join company_evidence_snapshot e on e.as_of_date = er.trade_date and e.ts_code = r.ts_code
                    join ths_concept_member_snapshot cm
                      on cm.snapshot_date = %s and cm.ts_code = r.ts_code
                    left join ths_index_master im on im.ths_code = cm.ths_code
                    {concept_where_sql}
                    group by concept_name
                    order by cnt desc, concept_name asc
                    """,
                    [concept_snapshot_date] + concept_params,
                ).fetchall()
                concept_counts = {
                    r["concept_name"]: r["cnt"]
                    for r in concept_rows
                    if r["concept_name"] and not is_low_signal_ths_concept(r["concept_name"])
                }

            fundamental_where_clauses = ["r.run_id = %s"]
            fundamental_params: list[Any] = [run_id]
            add_base_filters(
                fundamental_where_clauses, fundamental_params,
                include_industry=True, include_concept=True, include_fundamental=False,
            )
            fundamental_rows = conn.execute(
                f"""
                select coalesce(e.fundamental_filter_state, 'UNRESEARCHED') as filter_state, count(*) as cnt
                from early_turn_result r
                left join screening_asset_master a on a.asset_code = r.ts_code
                left join early_turn_run er on er.run_id = r.run_id
                left join company_evidence_snapshot e on e.as_of_date = er.trade_date and e.ts_code = r.ts_code
                where {' and '.join(fundamental_where_clauses)}
                group by coalesce(e.fundamental_filter_state, 'UNRESEARCHED')
                """,
                fundamental_params,
            ).fetchall()
            fundamental_counts = {row["filter_state"]: row["cnt"] for row in fundamental_rows}

        items = []
        for row in rows:
            item = dict(row)
            item["total_score"] = _nullable_float(item.get("total_score"))
            items.append(item)

        return {
            "total": total,
            "counts": counts,
            "industry_counts": industry_counts,
            "concept_counts": concept_counts,
            "fundamental_counts": fundamental_counts,
            "concept_snapshot_date": concept_snapshot_date,
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

    # ── Secondary Evaluation & AI Deep Research Methods ─────────────────
    def save_secondary_evaluation_snapshots(
        self,
        as_of_date: str,
        sec_rows: list[dict[str, Any]],
        evidence_rows: list[dict[str, Any]],
        leadership_rows: list[dict[str, Any]],
        supply_rows: list[dict[str, Any]],
    ) -> None:
        now = _now()
        with self.connect() as conn:
            with conn.cursor() as cur:
                # 1. candidate_secondary_snapshot
                for r in sec_rows:
                    cur.execute(
                        """
                        insert into candidate_secondary_snapshot (
                            as_of_date, ts_code, aprev2_score, aprev2_status, turn_type,
                            company_evidence_state, leadership_state, leadership_rank_value,
                            supply_profile_label, calc_version, created_at
                        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        on conflict (as_of_date, ts_code) do update set
                            aprev2_score = excluded.aprev2_score,
                            aprev2_status = excluded.aprev2_status,
                            turn_type = excluded.turn_type,
                            company_evidence_state = excluded.company_evidence_state,
                            leadership_state = excluded.leadership_state,
                            leadership_rank_value = excluded.leadership_rank_value,
                            supply_profile_label = excluded.supply_profile_label,
                            calc_version = excluded.calc_version,
                            created_at = excluded.created_at
                        """,
                        (
                            as_of_date,
                            r["ts_code"],
                            r.get("aprev2_score"),
                            r.get("aprev2_status"),
                            r.get("turn_type"),
                            r.get("company_evidence_state"),
                            r.get("leadership_state"),
                            r.get("leadership_rank_value"),
                            r.get("supply_profile_label"),
                            r.get("calc_version", "v1.0"),
                            now,
                        ),
                    )

                # 2. company_evidence_snapshot
                for r in evidence_rows:
                    cur.execute(
                        """
                        insert into company_evidence_snapshot (
                            as_of_date, ts_code, latest_report_period, latest_report_ann_date,
                            revenue, revenue_yoy, parent_net_profit, parent_net_profit_yoy, parent_profit_state,
                            deducted_net_profit, deducted_net_profit_yoy, deducted_profit_state,
                            operating_cashflow, operating_cashflow_yoy, gross_margin, gross_margin_yoy_delta,
                            forecast_ann_date, forecast_type, forecast_p_change_min, forecast_p_change_max,
                            forecast_net_profit_min, forecast_net_profit_max, express_ann_date, express_end_date,
                            express_revenue, express_n_income, express_yoy_net_profit, express_summary,
                            evidence_state, reason_json,
                            risk_flags_json, quarter_facts_json, fact_tags_json, data_quality_json,
                            fundamental_filter_state, fundamental_filter_reasons_json,
                            data_version, created_at
                        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s, %s)
                        on conflict (as_of_date, ts_code) do update set
                            latest_report_period = excluded.latest_report_period,
                            latest_report_ann_date = excluded.latest_report_ann_date,
                            revenue = excluded.revenue,
                            revenue_yoy = excluded.revenue_yoy,
                            parent_net_profit = excluded.parent_net_profit,
                            parent_net_profit_yoy = excluded.parent_net_profit_yoy,
                            parent_profit_state = excluded.parent_profit_state,
                            deducted_net_profit = excluded.deducted_net_profit,
                            deducted_net_profit_yoy = excluded.deducted_net_profit_yoy,
                            deducted_profit_state = excluded.deducted_profit_state,
                            operating_cashflow = excluded.operating_cashflow,
                            operating_cashflow_yoy = excluded.operating_cashflow_yoy,
                            gross_margin = excluded.gross_margin,
                            gross_margin_yoy_delta = excluded.gross_margin_yoy_delta,
                            forecast_ann_date = excluded.forecast_ann_date,
                            forecast_type = excluded.forecast_type,
                            forecast_p_change_min = excluded.forecast_p_change_min,
                            forecast_p_change_max = excluded.forecast_p_change_max,
                            forecast_net_profit_min = excluded.forecast_net_profit_min,
                            forecast_net_profit_max = excluded.forecast_net_profit_max,
                            express_ann_date = excluded.express_ann_date,
                            express_end_date = excluded.express_end_date,
                            express_revenue = excluded.express_revenue,
                            express_n_income = excluded.express_n_income,
                            express_yoy_net_profit = excluded.express_yoy_net_profit,
                            express_summary = excluded.express_summary,
                            evidence_state = excluded.evidence_state,
                            reason_json = excluded.reason_json,
                            risk_flags_json = excluded.risk_flags_json,
                            quarter_facts_json = excluded.quarter_facts_json,
                            fact_tags_json = excluded.fact_tags_json,
                            data_quality_json = excluded.data_quality_json,
                            fundamental_filter_state = excluded.fundamental_filter_state,
                            fundamental_filter_reasons_json = excluded.fundamental_filter_reasons_json,
                            data_version = excluded.data_version,
                            created_at = excluded.created_at
                        """,
                        (
                            as_of_date,
                            r["ts_code"],
                            r.get("latest_report_period"),
                            r.get("latest_report_ann_date"),
                            r.get("revenue"),
                            r.get("revenue_yoy"),
                            r.get("parent_net_profit"),
                            r.get("parent_net_profit_yoy"),
                            r.get("parent_profit_state"),
                            r.get("deducted_net_profit"),
                            r.get("deducted_net_profit_yoy"),
                            r.get("deducted_profit_state"),
                            r.get("operating_cashflow"),
                            r.get("operating_cashflow_yoy"),
                            r.get("gross_margin"),
                            r.get("gross_margin_yoy_delta"),
                            r.get("forecast_ann_date"),
                            r.get("forecast_type"),
                            r.get("forecast_p_change_min"),
                            r.get("forecast_p_change_max"),
                            r.get("forecast_net_profit_min"),
                            r.get("forecast_net_profit_max"),
                            r.get("express_ann_date"),
                            r.get("express_end_date"),
                            r.get("express_revenue"),
                            r.get("express_n_income"),
                            r.get("express_yoy_net_profit"),
                            r.get("express_summary"),
                            r.get("evidence_state", "UNKNOWN"),
                            json_dumps(r.get("reason_json", [])),
                            json_dumps(r.get("risk_flags_json", [])),
                            json_dumps(r.get("quarter_facts_json", [])),
                            json_dumps(r.get("fact_tags_json", [])),
                            json_dumps(r.get("data_quality_json", {})),
                            r.get("fundamental_filter_state"),
                            json_dumps(r.get("fundamental_filter_reasons_json", [])),
                            r.get("data_version", "v1.0"),
                            now,
                        ),
                    )

                # 3. relative_leadership_snapshot
                for r in leadership_rows:
                    cur.execute(
                        """
                        insert into relative_leadership_snapshot (
                            as_of_date, ts_code, comparison_level, comparison_industry_code,
                            comparison_industry_name, comparison_universe_size, stock_ret_5, stock_ret_10,
                            stock_ret_20, industry_rs_5_pct, industry_rs_10_pct, industry_rs_20_pct,
                            up_event_count, up_capture_excess, up_capture_pct, down_event_count,
                            down_defense_excess, down_defense_pct, amount_ratio_5_20, amount_ratio_10_40,
                            participation_pct, participation_change, participation_change_pct,
                            valid_component_count, leadership_rank_value, leadership_state, reason_json,
                            calc_version, created_at
                        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                        on conflict (as_of_date, ts_code) do update set
                            comparison_level = excluded.comparison_level,
                            comparison_industry_code = excluded.comparison_industry_code,
                            comparison_industry_name = excluded.comparison_industry_name,
                            comparison_universe_size = excluded.comparison_universe_size,
                            stock_ret_5 = excluded.stock_ret_5,
                            stock_ret_10 = excluded.stock_ret_10,
                            stock_ret_20 = excluded.stock_ret_20,
                            industry_rs_5_pct = excluded.industry_rs_5_pct,
                            industry_rs_10_pct = excluded.industry_rs_10_pct,
                            industry_rs_20_pct = excluded.industry_rs_20_pct,
                            up_event_count = excluded.up_event_count,
                            up_capture_excess = excluded.up_capture_excess,
                            up_capture_pct = excluded.up_capture_pct,
                            down_event_count = excluded.down_event_count,
                            down_defense_excess = excluded.down_defense_excess,
                            down_defense_pct = excluded.down_defense_pct,
                            amount_ratio_5_20 = excluded.amount_ratio_5_20,
                            amount_ratio_10_40 = excluded.amount_ratio_10_40,
                            participation_pct = excluded.participation_pct,
                            participation_change = excluded.participation_change,
                            participation_change_pct = excluded.participation_change_pct,
                            valid_component_count = excluded.valid_component_count,
                            leadership_rank_value = excluded.leadership_rank_value,
                            leadership_state = excluded.leadership_state,
                            reason_json = excluded.reason_json,
                            calc_version = excluded.calc_version,
                            created_at = excluded.created_at
                        """,
                        (
                            as_of_date,
                            r["ts_code"],
                            r.get("comparison_level"),
                            r.get("comparison_industry_code"),
                            r.get("comparison_industry_name"),
                            r.get("comparison_universe_size"),
                            r.get("stock_ret_5"),
                            r.get("stock_ret_10"),
                            r.get("stock_ret_20"),
                            r.get("industry_rs_5_pct"),
                            r.get("industry_rs_10_pct"),
                            r.get("industry_rs_20_pct"),
                            r.get("up_event_count"),
                            r.get("up_capture_excess"),
                            r.get("up_capture_pct"),
                            r.get("down_event_count"),
                            r.get("down_defense_excess"),
                            r.get("down_defense_pct"),
                            r.get("amount_ratio_5_20"),
                            r.get("amount_ratio_10_40"),
                            r.get("participation_pct"),
                            r.get("participation_change"),
                            r.get("participation_change_pct"),
                            r.get("valid_component_count"),
                            r.get("leadership_rank_value"),
                            r.get("leadership_state", "INSUFFICIENT_EVIDENCE"),
                            json_dumps(r.get("reason_json", [])),
                            r.get("calc_version", "v1.0"),
                            now,
                        ),
                    )

                # 4. supply_profile_snapshot
                for r in supply_rows:
                    cur.execute(
                        """
                        insert into supply_profile_snapshot (
                            as_of_date, ts_code, close, total_share, float_share, total_mv, circ_mv, free_share, free_float_mv,
                            amount, amount_median_20, turnover_rate, turnover_rate_f, volume_ratio,
                            unlock_30d, unlock_60d, unlock_90d, recent_reduction_flag, supply_profile_label,
                            data_version, created_at
                        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        on conflict (as_of_date, ts_code) do update set
                            close = excluded.close,
                            total_share = excluded.total_share,
                            float_share = excluded.float_share,
                            total_mv = excluded.total_mv,
                            circ_mv = excluded.circ_mv,
                            free_share = excluded.free_share,
                            free_float_mv = excluded.free_float_mv,
                            amount = excluded.amount,
                            amount_median_20 = excluded.amount_median_20,
                            turnover_rate = excluded.turnover_rate,
                            turnover_rate_f = excluded.turnover_rate_f,
                            volume_ratio = excluded.volume_ratio,
                            unlock_30d = excluded.unlock_30d,
                            unlock_60d = excluded.unlock_60d,
                            unlock_90d = excluded.unlock_90d,
                            recent_reduction_flag = excluded.recent_reduction_flag,
                            supply_profile_label = excluded.supply_profile_label,
                            data_version = excluded.data_version,
                            created_at = excluded.created_at
                        """,
                        (
                            as_of_date,
                            r["ts_code"],
                            r.get("close"),
                            r.get("total_share"),
                            r.get("float_share"),
                            r.get("total_mv"),
                            r.get("circ_mv"),
                            r.get("free_share"),
                            r.get("free_float_mv"),
                            r.get("amount"),
                            r.get("amount_median_20"),
                            r.get("turnover_rate"),
                            r.get("turnover_rate_f"),
                            r.get("volume_ratio"),
                            r.get("unlock_30d"),
                            r.get("unlock_60d"),
                            r.get("unlock_90d"),
                            r.get("recent_reduction_flag"),
                            r.get("supply_profile_label", "MID_CAP"),
                            r.get("data_version", "v1.0"),
                            now,
                        ),
                    )
            conn.commit()

    def get_candidate_secondary_list(self, as_of_date: str) -> list[dict[str, Any]]:
        query = """
            select s.as_of_date, s.ts_code, s.aprev2_score, s.aprev2_status, s.turn_type,
                   s.company_evidence_state, coalesce(l.leadership_state, s.leadership_state) as leadership_state,
                   s.supply_profile_label, s.calc_version, s.created_at,
                   e.evidence_state, e.revenue_yoy, e.parent_net_profit_yoy, e.deducted_net_profit_yoy,
                   e.forecast_type, e.reason_json as evidence_reasons, e.risk_flags_json,
                   e.quarter_facts_json, e.fact_tags_json, e.data_quality_json,
                   e.fundamental_filter_state, e.fundamental_filter_reasons_json,
                   p.free_float_mv, p.amount_median_20, p.turnover_rate_f,
                   p.unlock_30d, p.unlock_60d, p.unlock_90d, p.recent_reduction_flag,
                   p.supply_profile_label,
                   a.name, a.raw_json->>'industry' as industry,
                   ar.status as ai_status, ar.priority as ai_priority, ar.created_at as ai_created_at,
                   ar.ai_input_tokens, ar.ai_output_tokens, ar.ai_total_tokens, ar.ai_elapsed_ms,
                   ar.web_search_used
            from candidate_secondary_snapshot s
            left join company_evidence_snapshot e on e.as_of_date = s.as_of_date and e.ts_code = s.ts_code
            left join relative_leadership_snapshot l on l.as_of_date = s.as_of_date and l.ts_code = s.ts_code
            left join supply_profile_snapshot p on p.as_of_date = s.as_of_date and p.ts_code = s.ts_code
            left join screening_asset_master a on a.asset_code = s.ts_code
            left join lateral (
                select * from ai_stock_research ar0
                where ar0.as_of_date = s.as_of_date and ar0.ts_code = s.ts_code
                order by ar0.created_at desc limit 1
            ) ar on true
            where s.as_of_date = %s
            order by s.aprev2_score desc, s.ts_code asc
        """
        with self.connect() as conn:
            rows = conn.execute(query, (as_of_date,)).fetchall()
        return [dict(r) for r in rows]

    def save_market_financial_summaries(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        now = _now()
        with self.connect() as conn:
            for row in rows:
                conn.execute(
                    """insert into market_financial_summary_latest (ts_code,latest_report_period,revenue,revenue_yoy,parent_net_profit,parent_net_profit_yoy,operating_cashflow,operating_cashflow_yoy,forecast_type,fact_tags_json,data_status,source_updated_at,generated_at)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                    on conflict (ts_code) do update set latest_report_period=excluded.latest_report_period,revenue=excluded.revenue,revenue_yoy=excluded.revenue_yoy,parent_net_profit=excluded.parent_net_profit,parent_net_profit_yoy=excluded.parent_net_profit_yoy,operating_cashflow=excluded.operating_cashflow,operating_cashflow_yoy=excluded.operating_cashflow_yoy,forecast_type=excluded.forecast_type,fact_tags_json=excluded.fact_tags_json,data_status=excluded.data_status,source_updated_at=excluded.source_updated_at,generated_at=excluded.generated_at""",
                    (row["ts_code"], row.get("latest_report_period"), row.get("revenue"), row.get("revenue_yoy"), row.get("parent_net_profit"), row.get("parent_net_profit_yoy"), row.get("operating_cashflow"), row.get("operating_cashflow_yoy"), row.get("forecast_type"), json_dumps(row.get("fact_tags") or []), row["data_status"], row.get("source_updated_at"), now),
                )
            conn.commit()

    def get_market_financial_summaries(self, ts_codes: list[str]) -> dict[str, dict[str, Any]]:
        if not ts_codes:
            return {}
        with self.connect() as conn:
            rows = conn.execute("select * from market_financial_summary_latest where ts_code=any(%s)", (ts_codes,)).fetchall()
        return {row["ts_code"]: dict(row) for row in rows}

    def get_latest_financial_facts(self, ts_codes: list[str]) -> dict[str, dict[str, Any]]:
        if not ts_codes:
            return {}
        query = """
        with income as (select distinct on (ts_code) ts_code,end_date,total_revenue,n_income_attr_p from stock_income_statement where ts_code=any(%s) order by ts_code,end_date desc,available_date desc),
        cash as (select distinct on (ts_code) ts_code,end_date,n_cashflow_act from stock_cashflow_statement where ts_code=any(%s) order by ts_code,end_date desc,available_date desc),
        forecast as (select distinct on (ts_code) ts_code,type,p_change_min,p_change_max,net_profit_min,net_profit_max from stock_forecast where ts_code=any(%s) order by ts_code,available_date desc,end_date desc),
        express as (select distinct on (ts_code) ts_code,end_date,revenue,n_income,yoy_net_profit from stock_express where ts_code=any(%s) order by ts_code,end_date desc,available_date desc)
        select coalesce(i.ts_code,c.ts_code,f.ts_code,e.ts_code) as ts_code,i.end_date,i.total_revenue,i.n_income_attr_p,c.n_cashflow_act,f.type,f.p_change_min,f.p_change_max,f.net_profit_min,f.net_profit_max,e.revenue as express_revenue,e.n_income as express_net_profit,e.yoy_net_profit as express_net_profit_yoy
        from income i full join cash c on c.ts_code=i.ts_code full join forecast f on f.ts_code=coalesce(i.ts_code,c.ts_code) full join express e on e.ts_code=coalesce(i.ts_code,c.ts_code,f.ts_code)
        """
        with self.connect() as conn:
            rows = conn.execute(query, (ts_codes, ts_codes, ts_codes, ts_codes)).fetchall()
        return {row["ts_code"]: dict(row) for row in rows}

    def has_financial_data_for_stock(self, ts_code: str, as_of_date: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                select exists (
                    select 1 from stock_income_statement
                    where ts_code = %s
                      and available_date <= %s
                      and (raw_json ? 'total_revenue' or raw_json ? 'revenue' or raw_json ? 'n_income_attr_p')
                ) as has_income,
                exists (
                    select 1 from stock_event_sync_status
                    where ts_code = %s and source_name = 'income_vip' and status = 'EMPTY'
                ) as has_income_empty_sync,
                exists (
                    select 1 from stock_event_sync_status
                    where ts_code = %s and source_name = 'cashflow_vip' and status in ('PASS', 'EMPTY')
                ) as has_cashflow_sync,
                exists (
                    select 1 from stock_fina_indicator
                    where ts_code = %s
                      and available_date <= %s
                ) as has_indicator,
                exists (
                    select 1 from stock_event_sync_status
                    where ts_code = %s and source_name = 'fina_indicator_vip' and status = 'EMPTY'
                ) as has_indicator_empty_sync,
                exists (
                    select 1 from stock_event_sync_status
                    where ts_code = %s and source_name = 'forecast_vip' and status in ('PASS', 'EMPTY')
                ) as has_forecast_sync,
                exists (
                    select 1 from stock_event_sync_status
                    where ts_code = %s and source_name = 'express_vip' and status in ('PASS', 'EMPTY')
                ) as has_express_sync
                """,
                (ts_code, as_of_date, ts_code, ts_code, ts_code, as_of_date, ts_code, ts_code, ts_code),
            ).fetchone()
        return bool(
            row
            and (row["has_income"] or row["has_income_empty_sync"])
            and row["has_cashflow_sync"]
            and (row["has_indicator"] or row["has_indicator_empty_sync"])
            and row["has_forecast_sync"]
            and row["has_express_sync"]
        )

    def has_supply_event_data_for_stock(self, ts_code: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                select count(*) as source_count
                from stock_event_sync_status
                where ts_code = %s
                  and source_name = any(%s)
                  and status = 'PASS'
                """,
                (ts_code, ["share_float", "stk_holdertrade"]),
            ).fetchone()
        return int(row["source_count"] if row else 0) == 2

    def has_daily_basic_extended(self, trade_date: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                select exists (
                    select 1
                    from screening_daily_basic
                    where trade_date = %s
                      and free_share is not null
                      and volume_ratio is not null
                ) as has_extended
                """,
                (trade_date,),
            ).fetchone()
        return bool(row and row["has_extended"])

    def has_industry_memberships(self, source_version: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                select exists (
                    select 1
                    from industry_membership_history
                    where source_version = %s
                ) as has_memberships
                """,
                (source_version,),
            ).fetchone()
        return bool(row and row["has_memberships"])

    def get_company_financial_pit(self, ts_code: str, as_of_date: str) -> dict[str, Any]:
        with self.connect() as conn:
            income = conn.execute(
                """
                select *
                from stock_income_statement
                where ts_code = %s and available_date <= %s
                order by end_date desc, available_date desc
                limit 1
                """,
                (ts_code, as_of_date),
            ).fetchone()

            prev_income = None
            cashflow = None
            prev_cashflow = None
            indicator = None
            express = conn.execute(
                """
                select *
                from stock_express
                where ts_code = %s and available_date <= %s
                order by end_date desc, available_date desc
                limit 1
                """,
                (ts_code, as_of_date),
            ).fetchone()
            forecast = conn.execute(
                """
                select *
                from stock_forecast
                where ts_code = %s and available_date <= %s
                order by coalesce(end_date, '') desc, available_date desc
                limit 1
                """,
                (ts_code, as_of_date),
            ).fetchone()

            if income:
                prev_end_date = _previous_year_period(str(income["end_date"]))
                prev_income = conn.execute(
                    """
                    select *
                    from stock_income_statement
                    where ts_code = %s and end_date = %s and available_date <= %s
                    order by available_date desc
                    limit 1
                    """,
                    (ts_code, prev_end_date, as_of_date),
                ).fetchone()
                cashflow = conn.execute(
                    """
                    select *
                    from stock_cashflow_statement
                    where ts_code = %s and end_date = %s and available_date <= %s
                    order by available_date desc
                    limit 1
                    """,
                    (ts_code, income["end_date"], as_of_date),
                ).fetchone()
                prev_cashflow = conn.execute(
                    """
                    select *
                    from stock_cashflow_statement
                    where ts_code = %s and end_date = %s and available_date <= %s
                    order by available_date desc
                    limit 1
                    """,
                    (ts_code, prev_end_date, as_of_date),
                ).fetchone()
                indicator = conn.execute(
                    """
                    select *
                    from stock_fina_indicator
                    where ts_code = %s and end_date = %s and available_date <= %s
                    order by available_date desc
                    limit 1
                    """,
                    (ts_code, income["end_date"], as_of_date),
                ).fetchone()

        return {
            "income": dict(income) if income else None,
            "prev_income": dict(prev_income) if prev_income else None,
            "cashflow": dict(cashflow) if cashflow else None,
            "prev_cashflow": dict(prev_cashflow) if prev_cashflow else None,
            "indicator": dict(indicator) if indicator else None,
            "forecast": dict(forecast) if forecast else None,
            "express": dict(express) if express else None,
        }

    def get_company_financial_periods_pit(self, ts_code: str, as_of_date: str, limit: int = 12) -> dict[str, Any]:
        """Return PIT financial rows by report period for cumulative-to-quarter reconstruction."""
        with self.connect() as conn:
            income_rows = conn.execute(
                """
                select distinct on (end_date) *
                from stock_income_statement
                where ts_code = %s and available_date <= %s
                order by end_date desc, available_date desc
                limit %s
                """,
                (ts_code, as_of_date, limit),
            ).fetchall()
            cashflow_rows = conn.execute(
                """
                select distinct on (end_date) *
                from stock_cashflow_statement
                where ts_code = %s and available_date <= %s
                order by end_date desc, available_date desc
                limit %s
                """,
                (ts_code, as_of_date, limit),
            ).fetchall()
            indicator_rows = conn.execute(
                """
                select distinct on (end_date) *
                from stock_fina_indicator
                where ts_code = %s and available_date <= %s
                order by end_date desc, available_date desc
                limit %s
                """,
                (ts_code, as_of_date, limit),
            ).fetchall()
            forecast = conn.execute(
                """
                select *
                from stock_forecast
                where ts_code = %s and available_date <= %s
                order by coalesce(end_date, '') desc, available_date desc
                limit 1
                """,
                (ts_code, as_of_date),
            ).fetchone()
            express = conn.execute(
                """
                select *
                from stock_express
                where ts_code = %s and available_date <= %s
                order by end_date desc, available_date desc
                limit 1
                """,
                (ts_code, as_of_date),
            ).fetchone()

        return {
            "income_rows": [dict(r) for r in income_rows],
            "cashflow_rows": [dict(r) for r in cashflow_rows],
            "indicator_rows": [dict(r) for r in indicator_rows],
            "forecast": dict(forecast) if forecast else None,
            "express": dict(express) if express else None,
        }

    def get_supply_events_pit(self, ts_code: str, as_of_date: str) -> dict[str, Any]:
        with self.connect() as conn:
            share_sync = conn.execute(
                """
                select *
                from stock_event_sync_status
                where ts_code = %s and source_name = 'share_float' and status = 'PASS'
                """,
                (ts_code,),
            ).fetchone()
            holder_sync = conn.execute(
                """
                select *
                from stock_event_sync_status
                where ts_code = %s and source_name = 'stk_holdertrade' and status = 'PASS'
                """,
                (ts_code,),
            ).fetchone()
            unlock = conn.execute(
                """
                select
                    coalesce(sum(float_ratio) filter (
                        where to_date(float_date, 'YYYYMMDD') > to_date(%s, 'YYYYMMDD')
                          and to_date(float_date, 'YYYYMMDD') <= to_date(%s, 'YYYYMMDD') + interval '30 days'
                    ), 0) as unlock_30d,
                    coalesce(sum(float_ratio) filter (
                        where to_date(float_date, 'YYYYMMDD') > to_date(%s, 'YYYYMMDD')
                          and to_date(float_date, 'YYYYMMDD') <= to_date(%s, 'YYYYMMDD') + interval '60 days'
                    ), 0) as unlock_60d,
                    coalesce(sum(float_ratio) filter (
                        where to_date(float_date, 'YYYYMMDD') > to_date(%s, 'YYYYMMDD')
                          and to_date(float_date, 'YYYYMMDD') <= to_date(%s, 'YYYYMMDD') + interval '90 days'
                    ), 0) as unlock_90d
                from stock_share_float
                where ts_code = %s
                  and (available_date is null or available_date <= %s)
                  and float_date is not null
                """,
                (as_of_date, as_of_date, as_of_date, as_of_date, as_of_date, as_of_date, ts_code, as_of_date),
            ).fetchone()
            reduction = conn.execute(
                """
                select exists (
                    select 1
                    from stock_holder_trade
                    where ts_code = %s
                      and ann_date <= %s
                      and to_date(ann_date, 'YYYYMMDD') >= to_date(%s, 'YYYYMMDD') - interval '180 days'
                      and (
                          in_de like '%%减%%'
                          or change_vol < 0
                          or change_ratio < 0
                      )
                ) as has_reduction
                """,
                (ts_code, as_of_date, as_of_date),
            ).fetchone()
        return {
            "share_float_synced": bool(share_sync),
            "holder_trade_synced": bool(holder_sync),
            "unlock_30d": _nullable_float(unlock.get("unlock_30d")) if share_sync and unlock else None,
            "unlock_60d": _nullable_float(unlock.get("unlock_60d")) if share_sync and unlock else None,
            "unlock_90d": _nullable_float(unlock.get("unlock_90d")) if share_sync and unlock else None,
            "recent_reduction_flag": bool(reduction and reduction["has_reduction"]) if holder_sync else None,
        }

    def get_candidate_secondary_detail(self, as_of_date: str, ts_code: str) -> dict[str, Any] | None:
        query = """
            select s.as_of_date, s.ts_code, s.aprev2_score, s.aprev2_status, s.turn_type,
                   s.company_evidence_state, coalesce(l.leadership_state, s.leadership_state) as leadership_state,
                   s.supply_profile_label, s.calc_version, s.created_at,
                   e.latest_report_period, e.latest_report_ann_date,
                   e.revenue, e.revenue_yoy, e.parent_net_profit, e.parent_net_profit_yoy, e.parent_profit_state,
                   e.deducted_net_profit, e.deducted_net_profit_yoy, e.deducted_profit_state, e.operating_cashflow,
                   e.operating_cashflow_yoy, e.gross_margin, e.gross_margin_yoy_delta, e.forecast_type, e.forecast_ann_date,
                   e.forecast_p_change_min, e.forecast_p_change_max, e.forecast_net_profit_min, e.forecast_net_profit_max,
                   e.express_ann_date, e.express_end_date, e.express_revenue, e.express_n_income,
                   e.express_yoy_net_profit, e.express_summary,
                   e.reason_json as evidence_reasons, e.risk_flags_json,
                   e.quarter_facts_json, e.fact_tags_json, e.data_quality_json,
                   e.fundamental_filter_state, e.fundamental_filter_reasons_json,
                   l.reason_json as leadership_reasons,
                   p.close, p.total_share, p.float_share, p.total_mv, p.circ_mv, p.free_share, p.free_float_mv, p.amount, p.amount_median_20, p.turnover_rate,
                   p.turnover_rate_f, p.volume_ratio, p.unlock_30d, p.unlock_60d, p.unlock_90d, p.recent_reduction_flag,
                   p.supply_profile_label,
                   a.name, a.raw_json->>'industry' as industry, a.raw_json->>'main_business' as main_business
            from candidate_secondary_snapshot s
            left join company_evidence_snapshot e on e.as_of_date = s.as_of_date and e.ts_code = s.ts_code
            left join relative_leadership_snapshot l on l.as_of_date = s.as_of_date and l.ts_code = s.ts_code
            left join supply_profile_snapshot p on p.as_of_date = s.as_of_date and p.ts_code = s.ts_code
            left join screening_asset_master a on a.asset_code = s.ts_code
            where s.as_of_date = %s and s.ts_code = %s
        """
        with self.connect() as conn:
            row = conn.execute(query, (as_of_date, ts_code)).fetchone()
        return dict(row) if row else None


def _now() -> datetime:

    return datetime.now(UTC)


def _nullable_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _nullable_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _available_date(record: dict[str, Any]) -> str | None:
    return _nullable_text(record.get("f_ann_date")) or _nullable_text(record.get("ann_date"))


def _previous_year_period(end_date: str | None) -> str | None:
    if not end_date or len(end_date) != 8 or not end_date[:4].isdigit():
        return None
    return f"{int(end_date[:4]) - 1}{end_date[4:]}"


def _membership_key(item: dict[str, Any], source_version: str) -> str:
    parts = [
        str(item.get("ts_code") or ""),
        str(item.get("l3_code") or item.get("l2_code") or item.get("l1_code") or ""),
        str(item.get("in_date") or ""),
        str(item.get("out_date") or ""),
        source_version,
    ]
    return "|".join(parts)


def _holder_trade_key(record: dict[str, Any]) -> str:
    parts = [
        str(record.get("ts_code") or ""),
        str(record.get("ann_date") or ""),
        str(record.get("holder_name") or ""),
        str(record.get("in_de") or ""),
        str(record.get("change_vol") or ""),
        str(record.get("change_ratio") or ""),
    ]
    return "|".join(parts)


def _completed_30m_slots(current_time: dtime) -> list[str]:
    slots = [
        ("10:00", dtime(10, 0)),
        ("10:30", dtime(10, 30)),
        ("11:00", dtime(11, 0)),
        ("11:30", dtime(11, 30)),
        ("13:30", dtime(13, 30)),
        ("14:00", dtime(14, 0)),
        ("14:30", dtime(14, 30)),
        ("15:00", dtime(15, 0)),
    ]
    return [label for label, end_time in slots if current_time >= end_time]


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


# Watchlist Management Extensions for PostgresScreeningStore
def get_watchlist_groups(self) -> list[dict[str, Any]]:
    with self.connect() as conn:
        rows = conn.execute(
            """
            select group_id, group_name, parent_id, sort_order, created_at
            from screening_watchlist_groups
            order by parent_id nulls first, sort_order asc, group_id asc
            """
        ).fetchall()
        return [
            {
                "group_id": r["group_id"],
                "group_name": r["group_name"],
                "parent_id": r["parent_id"],
                "sort_order": r["sort_order"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in rows
        ]

def get_watchlist_group_nodes(self) -> list[dict[str, Any]]:
    """Return editable manual groups plus read-only industry groups derived from watchlist data."""
    with self.connect() as conn:
        manual_rows = conn.execute(
            """
            select group_id, group_name, parent_id, sort_order, created_at
            from screening_watchlist_groups
            order by parent_id nulls first, sort_order asc, group_id asc
            """
        ).fetchall()
        industry_rows = conn.execute(
            """
            select coalesce(nullif(trim(m.raw_json->>'industry'), ''), '未分类') as industry,
                   count(distinct w.asset_code) as stock_count
            from screening_user_watchlist w
            left join screening_asset_master m on m.asset_code = w.asset_code
            group by coalesce(nullif(trim(m.raw_json->>'industry'), ''), '未分类')
            order by industry
            """
        ).fetchall()
        nodes = [
            {
                "group_id": r["group_id"],
                "group_key": f"manual:{r['group_id']}",
                "group_name": r["group_name"],
                "group_type": "manual",
                "parent_id": r["parent_id"],
                "sort_order": r["sort_order"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in manual_rows
        ]
        nodes.extend(
            {
                "group_id": None,
                "group_key": f"industry:{r['industry']}",
                "group_name": r["industry"],
                "group_type": "industry",
                "parent_id": None,
                "sort_order": 0,
                "stock_count": int(r["stock_count"]),
            }
            for r in industry_rows
        )
        return nodes

def create_watchlist_group(self, group_name: str, parent_id: int | None = None) -> dict[str, Any]:
    with self.connect() as conn:
        row = conn.execute(
            """
            insert into screening_watchlist_groups (group_name, parent_id, created_at)
            values (%s, %s, now())
            returning group_id, group_name, parent_id, sort_order, created_at
            """,
            (group_name, parent_id),
        ).fetchone()
        conn.commit()
        return {
            "group_id": row["group_id"],
            "group_name": row["group_name"],
            "parent_id": row["parent_id"],
            "sort_order": row["sort_order"],
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        }

def update_watchlist_group(self, group_id: int, group_name: str) -> bool:
    with self.connect() as conn:
        cur = conn.execute(
            "update screening_watchlist_groups set group_name = %s where group_id = %s",
            (group_name, group_id),
        )
        conn.commit()
        return cur.rowcount > 0

def delete_watchlist_group(self, group_id: int) -> bool:
    with self.connect() as conn:
        cur = conn.execute("delete from screening_watchlist_groups where group_id = %s", (group_id,))
        conn.commit()
        return cur.rowcount > 0

def get_watchlist_stocks(self, group_id: int | None = None) -> list[dict[str, Any]]:
    with self.connect() as conn:
        if group_id is not None:
            rows = conn.execute(
                """
                select w.asset_code, w.group_id, w.created_at, m.name, m.raw_json->>'industry' as industry
                from screening_user_watchlist w
                left join screening_asset_master m on w.asset_code = m.asset_code
                where w.group_id = %s
                order by w.created_at desc
                """,
                (group_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                select distinct on (w.asset_code) w.asset_code, w.group_id, w.created_at, m.name, m.raw_json->>'industry' as industry
                from screening_user_watchlist w
                left join screening_asset_master m on w.asset_code = m.asset_code
                order by w.asset_code, w.created_at desc
                """
            ).fetchall()
        return [
            {
                "asset_code": r["asset_code"],
                "group_id": r["group_id"],
                "name": r.get("name") or r["asset_code"],
                "industry": r.get("industry") or "A股",
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in rows
        ]

def get_watchlist_stocks_by_group_key(self, group_key: str | None = None) -> list[dict[str, Any]]:
    if not group_key:
        return self.get_watchlist_stocks()
    if group_key.startswith("manual:"):
        try:
            return self.get_watchlist_stocks(int(group_key.split(":", 1)[1]))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid manual watchlist group key") from exc
    if group_key.startswith("industry:"):
        industry = group_key.split(":", 1)[1]
        with self.connect() as conn:
            rows = conn.execute(
                """
                select distinct on (w.asset_code) w.asset_code, w.group_id, w.created_at,
                       m.name, coalesce(nullif(trim(m.raw_json->>'industry'), ''), '未分类') as industry
                from screening_user_watchlist w
                left join screening_asset_master m on m.asset_code = w.asset_code
                where coalesce(nullif(trim(m.raw_json->>'industry'), ''), '未分类') = %s
                order by w.asset_code, w.created_at desc
                """,
                (industry,),
            ).fetchall()
            return [
                {
                    "asset_code": r["asset_code"],
                    "group_id": r["group_id"],
                    "name": r.get("name") or r["asset_code"],
                    "industry": r.get("industry") or "未分类",
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                }
                for r in rows
            ]
    raise ValueError("unsupported watchlist group key")

def get_watchlist_stocks_with_research(self, group_key: str | None = None) -> list[dict[str, Any]]:
    """Return the selected watchlist scope together with its latest available research snapshots.

    A watchlist is independent from an A-PreV2 batch, so every stock can have a
    different latest research date.  The lateral joins deliberately select the
    complete latest snapshot for each stock instead of assuming the latest
    market-wide batch covered every watchlist member.
    """
    base_params: list[Any] = []
    if not group_key:
        base_sql = """
            select distinct on (w.asset_code)
                   w.asset_code, w.group_id, w.created_at, w.source_type, w.source_strategy, w.source_stage, w.source_snapshot_date,
                   m.name, coalesce(nullif(trim(m.raw_json->>'industry'), ''), '未分类') as industry
            from screening_user_watchlist w
            left join screening_asset_master m on m.asset_code = w.asset_code
            order by w.asset_code, w.created_at desc
        """
    elif group_key.startswith("manual:"):
        try:
            group_id = int(group_key.split(":", 1)[1])
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid manual watchlist group key") from exc
        base_sql = """
            select w.asset_code, w.group_id, w.created_at, w.source_type, w.source_strategy, w.source_stage, w.source_snapshot_date,
                   m.name, coalesce(nullif(trim(m.raw_json->>'industry'), ''), '未分类') as industry
            from screening_user_watchlist w
            left join screening_asset_master m on m.asset_code = w.asset_code
            where w.group_id = %s
        """
        base_params.append(group_id)
    elif group_key.startswith("industry:"):
        industry = group_key.split(":", 1)[1]
        base_sql = """
            select distinct on (w.asset_code)
                   w.asset_code, w.group_id, w.created_at, w.source_type, w.source_strategy, w.source_stage, w.source_snapshot_date,
                   m.name, coalesce(nullif(trim(m.raw_json->>'industry'), ''), '未分类') as industry
            from screening_user_watchlist w
            left join screening_asset_master m on m.asset_code = w.asset_code
            where coalesce(nullif(trim(m.raw_json->>'industry'), ''), '未分类') = %s
            order by w.asset_code, w.created_at desc
        """
        base_params.append(industry)
    else:
        raise ValueError("unsupported watchlist group key")

    query = f"""
        with watchlist_scope as ({base_sql})
        select w.asset_code, w.group_id, w.created_at, w.source_type, w.source_strategy, w.source_stage, w.source_snapshot_date, w.name, w.industry,
               s.as_of_date as research_as_of_date,
               s.aprev2_score, s.aprev2_status, s.turn_type,
               e.evidence_state, e.fundamental_filter_state, e.latest_report_period,
               e.revenue_yoy, e.parent_net_profit_yoy, e.operating_cashflow_yoy,
               e.forecast_type, e.fact_tags_json, e.risk_flags_json,
               ar.as_of_date as ai_as_of_date, ar.status as ai_status,
               ar.priority as ai_priority, ar.created_at as ai_created_at,
               ar.ai_total_tokens, ar.ai_elapsed_ms, ar.web_search_used
        from watchlist_scope w
        left join lateral (
            select *
            from candidate_secondary_snapshot s0
            where s0.ts_code = w.asset_code
            order by s0.as_of_date desc, s0.created_at desc
            limit 1
        ) s on true
        left join company_evidence_snapshot e
            on e.as_of_date = s.as_of_date and e.ts_code = s.ts_code
        left join lateral (
            select *
            from ai_stock_research ar0
            where ar0.ts_code = w.asset_code
            order by ar0.created_at desc
            limit 1
        ) ar on true
        order by w.created_at desc, w.asset_code asc
    """
    with self.connect() as conn:
        rows = conn.execute(query, base_params).fetchall()
    return [dict(row) for row in rows]

def toggle_watchlist_stock(self, asset_code: str, group_id: int | None = None, source: dict[str, Any] | None = None) -> bool:
    clean_code = asset_code.strip().upper()
    source = source or {"type": "MANUAL"}
    source_type = str(source.get("type") or "MANUAL").upper()
    if source_type not in {"MANUAL", "STRATEGY"}:
        raise ValueError("invalid watchlist source type")
    strategy = str(source.get("strategy") or "").strip() or None
    stage = str(source.get("stage") or "").strip() or None
    snapshot_date = str(source.get("snapshot_date") or "").strip() or None
    if source_type == "STRATEGY" and (not strategy or not stage or not snapshot_date):
        raise ValueError("strategy source requires strategy, stage and snapshot_date")
    with self.connect() as conn:
        # Check if code is already in watchlist
        if group_id is not None:
            existing = conn.execute(
                "select 1 from screening_user_watchlist where asset_code = %s and group_id = %s",
                (clean_code, group_id),
            ).fetchone()
        else:
            existing = conn.execute(
                "select 1 from screening_user_watchlist where asset_code = %s",
                (clean_code,),
            ).fetchone()
        
        if existing:
            if group_id is not None:
                conn.execute(
                    "delete from screening_user_watchlist where asset_code = %s and group_id = %s",
                    (clean_code, group_id),
                )
            else:
                conn.execute(
                    "delete from screening_user_watchlist where asset_code = %s",
                    (clean_code,),
                )
            conn.commit()
            return False
        else:
            conn.execute(
                """
                insert into screening_user_watchlist
                    (asset_code, asset_type, group_id, source_type, source_strategy, source_stage, source_snapshot_date, source_recorded_at, created_at)
                values (%s, 'stock', %s, %s, %s, %s, %s, now(), now()) on conflict do nothing
                """,
                (clean_code, group_id, source_type, strategy, stage, snapshot_date),
            )
            conn.commit()
            return True

def get_watchlist_code_set(self) -> set[str]:
    with self.connect() as conn:
        rows = conn.execute("select distinct asset_code from screening_user_watchlist").fetchall()
        return {r["asset_code"] for r in rows}

def get_ai_analysis_pool(self) -> list[dict[str, Any]]:
    with self.connect() as conn:
        rows = conn.execute(
            """
            with pool_scope as (
                select p.asset_code, p.created_at, m.name,
                       coalesce(nullif(trim(m.raw_json->>'industry'), ''), '未分类') as industry
                from screening_ai_analysis_pool p
                left join screening_asset_master m on m.asset_code = p.asset_code
            )
            select p.asset_code, p.created_at, p.name, p.industry,
                   s.as_of_date as research_as_of_date,
                   s.aprev2_score, s.aprev2_status, s.turn_type,
                   e.evidence_state, e.fundamental_filter_state, e.latest_report_period,
                   e.revenue_yoy, e.parent_net_profit_yoy, e.operating_cashflow_yoy,
                   e.forecast_type, e.fact_tags_json, e.risk_flags_json,
                   ar.as_of_date as ai_as_of_date, ar.status as ai_status,
                   ar.priority as ai_priority, ar.created_at as ai_created_at,
                   ar.ai_total_tokens, ar.ai_elapsed_ms, ar.web_search_used
            from pool_scope p
            left join lateral (
                select * from candidate_secondary_snapshot s0
                where s0.ts_code = p.asset_code
                order by s0.as_of_date desc, s0.created_at desc
                limit 1
            ) s on true
            left join company_evidence_snapshot e
                on e.as_of_date = s.as_of_date and e.ts_code = s.ts_code
            left join lateral (
                select * from ai_stock_research ar0
                where ar0.ts_code = p.asset_code
                order by ar0.created_at desc
                limit 1
            ) ar on true
            order by p.created_at desc, p.asset_code
            """
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["name"] = item.get("name") or item["asset_code"]
            item["industry"] = item.get("industry") or "未分类"
            item["created_at"] = item["created_at"].isoformat() if item.get("created_at") else None
            result.append(item)
        return result

def toggle_ai_analysis_pool(self, asset_code: str) -> bool:
    clean_code = asset_code.strip().upper()
    with self.connect() as conn:
        existing = conn.execute("select 1 from screening_ai_analysis_pool where asset_code = %s", (clean_code,)).fetchone()
        if existing:
            conn.execute("delete from screening_ai_analysis_pool where asset_code = %s", (clean_code,))
            added = False
        else:
            conn.execute("insert into screening_ai_analysis_pool (asset_code) values (%s)", (clean_code,))
            added = True
        conn.commit()
        return added

def replace_ai_analysis_pool(self, asset_codes: list[str]) -> list[dict[str, Any]]:
    clean_codes = sorted({str(code).strip().upper() for code in asset_codes if str(code).strip()})
    with self.connect() as conn:
        conn.execute("delete from screening_ai_analysis_pool")
        if clean_codes:
            conn.executemany("insert into screening_ai_analysis_pool (asset_code) values (%s)", [(code,) for code in clean_codes])
        conn.commit()
    return self.get_ai_analysis_pool()

PostgresScreeningStore.get_watchlist_groups = get_watchlist_groups
PostgresScreeningStore.get_watchlist_group_nodes = get_watchlist_group_nodes
PostgresScreeningStore.create_watchlist_group = create_watchlist_group
PostgresScreeningStore.update_watchlist_group = update_watchlist_group
PostgresScreeningStore.delete_watchlist_group = delete_watchlist_group
PostgresScreeningStore.get_watchlist_stocks = get_watchlist_stocks
PostgresScreeningStore.get_watchlist_stocks_by_group_key = get_watchlist_stocks_by_group_key
PostgresScreeningStore.get_watchlist_stocks_with_research = get_watchlist_stocks_with_research
PostgresScreeningStore.toggle_watchlist_stock = toggle_watchlist_stock
PostgresScreeningStore.get_watchlist_code_set = get_watchlist_code_set
PostgresScreeningStore.get_ai_analysis_pool = get_ai_analysis_pool
PostgresScreeningStore.toggle_ai_analysis_pool = toggle_ai_analysis_pool
PostgresScreeningStore.replace_ai_analysis_pool = replace_ai_analysis_pool
