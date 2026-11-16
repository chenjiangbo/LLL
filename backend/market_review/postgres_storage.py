from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from backend.market_review.json_utils import json_dump, json_load, jsonable


@dataclass
class PostgresMarketReviewStore:
    database_url: str

    def __post_init__(self) -> None:
        if not self.database_url:
            raise ValueError("database_url is required for PostgresMarketReviewStore")
        self.init_schema()

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                create table if not exists raw_snapshots (
                    id bigserial primary key,
                    trade_date text not null,
                    snapshot_type text not null,
                    source text not null,
                    payload_json jsonb not null,
                    created_at timestamptz not null,
                    unique(trade_date, snapshot_type, source)
                )
                """
            )
            conn.execute(
                """
                create table if not exists overview_reports (
                    trade_date text primary key,
                    payload_json jsonb not null,
                    created_at timestamptz not null,
                    updated_at timestamptz not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists market_series (
                    series_type text not null,
                    series_key text not null,
                    record_date text not null,
                    source text not null,
                    payload_json jsonb not null,
                    fetched_at timestamptz not null,
                    primary key(series_type, series_key, record_date, source)
                )
                """
            )
            conn.execute(
                """
                create table if not exists ai_review_drafts (
                    trade_date text not null,
                    report_type text not null,
                    input_hash text not null,
                    model text not null,
                    payload_json jsonb not null,
                    created_at timestamptz not null,
                    updated_at timestamptz not null,
                    primary key(trade_date, report_type)
                )
                """
            )
            conn.execute(
                """
                create table if not exists imported_market_reviews (
                    trade_date text primary key,
                    raw_content text not null,
                    payload_json jsonb not null,
                    created_at timestamptz not null,
                    updated_at timestamptz not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists imported_review_stock_mentions (
                    trade_date text not null,
                    asset_code text not null,
                    asset_name text not null,
                    mention_name text not null,
                    canonical_theme text not null,
                    theme_key text not null,
                    concepts_json jsonb not null,
                    story text not null,
                    mention_role text not null,
                    source_excerpt text not null,
                    extraction_version text not null,
                    created_at timestamptz not null,
                    updated_at timestamptz not null,
                    primary key(trade_date, asset_code)
                )
                """
            )
            # Keep the wording used in the review itself.  The asset-master name is
            # still the canonical security identity; this field is solely for
            # locating the exact wording in the rendered article.
            conn.execute(
                "alter table imported_review_stock_mentions add column if not exists mention_name text"
            )
            conn.execute(
                "update imported_review_stock_mentions set mention_name = asset_name where mention_name is null"
            )
            # Historical records predate mention_name.  A leading C/N is a listing
            # marker in the master name, not necessarily part of the wording in
            # the review.  Only remove it when the remaining exact name is present
            # in the already stored source excerpt.
            conn.execute(
                """
                update imported_review_stock_mentions
                set mention_name = substring(asset_name from 2)
                where mention_name = asset_name
                  and left(asset_name, 1) in ('C', 'N')
                  and source_excerpt like '%%' || substring(asset_name from 2) || '%%'
                """
            )
            conn.execute(
                "alter table imported_review_stock_mentions alter column mention_name set not null"
            )
            conn.execute(
                """
                create table if not exists imported_review_stock_extraction_runs (
                    trade_date text primary key,
                    source_stock_count integer not null,
                    resolved_stock_count integer not null,
                    unresolved_stock_json jsonb not null,
                    status text not null,
                    extraction_version text not null,
                    created_at timestamptz not null,
                    updated_at timestamptz not null
                )
                """
            )
            # 导入复盘时固化同花顺概念板块的当日官方结果。历史复盘页面只读取
            # 该不可变快照，不能在查看时用后来变化的概念成分重新计算。
            conn.execute(
                """
                create table if not exists imported_review_ths_concept_board_snapshots (
                    trade_date text primary key,
                    source text not null,
                    source_row_count integer not null,
                    payload_json jsonb not null,
                    captured_at timestamptz not null
                )
                """
            )
            # 导入复盘后衍生生成的三项内容必须具有可恢复的状态。服务重启不能
            # 让已经写入的复盘原文失去后续的市场全景、题材周期和资金脉络快照。
            conn.execute(
                """
                create table if not exists market_review_snapshot_update_jobs (
                    trade_date text primary key,
                    panorama_status text not null,
                    memory_status text not null,
                    panorama_error text,
                    memory_error text,
                    requested_at timestamptz not null,
                    started_at timestamptz,
                    completed_at timestamptz,
                    updated_at timestamptz not null
                )
                """
            )
            # The review itself is available as soon as its Markdown has been
            # saved.  These two enrichments are intentionally independent of
            # that save so an AI or external-data delay never prevents reading
            # the newly imported article.
            conn.execute(
                """
                create table if not exists market_review_import_enrichment_jobs (
                    trade_date text primary key,
                    stock_extraction_status text not null,
                    concept_board_status text not null,
                    stock_extraction_error text,
                    concept_board_error text,
                    requested_at timestamptz not null,
                    started_at timestamptz,
                    completed_at timestamptz,
                    updated_at timestamptz not null
                )
                """
            )
            conn.execute(
                "create index if not exists idx_raw_snapshots_trade_date on raw_snapshots(trade_date)"
            )
            conn.execute(
                "create index if not exists idx_market_series_lookup on market_series(series_type, series_key, record_date)"
            )
            conn.execute(
                "create index if not exists idx_review_stock_mentions_theme on imported_review_stock_mentions(trade_date, theme_key)"
            )
            conn.execute(
                "create index if not exists idx_review_snapshot_update_jobs_pending on market_review_snapshot_update_jobs(panorama_status, memory_status)"
            )
            conn.execute(
                "create index if not exists idx_review_import_enrichment_jobs_pending on market_review_import_enrichment_jobs(stock_extraction_status, concept_board_status)"
            )
            conn.commit()

    def enqueue_import_enrichment_job(self, trade_date: str) -> None:
        """Queue non-blocking review enrichments after Markdown is saved."""
        now = datetime.utcnow()
        with self.connect() as conn:
            conn.execute(
                """
                insert into market_review_import_enrichment_jobs (
                    trade_date, stock_extraction_status, concept_board_status,
                    stock_extraction_error, concept_board_error,
                    requested_at, started_at, completed_at, updated_at
                ) values (%s, 'PENDING', 'PENDING', null, null, %s, null, null, %s)
                on conflict(trade_date) do update set
                    stock_extraction_status = 'PENDING',
                    concept_board_status = 'PENDING',
                    stock_extraction_error = null,
                    concept_board_error = null,
                    requested_at = excluded.requested_at,
                    started_at = null,
                    completed_at = null,
                    updated_at = excluded.updated_at
                """,
                (trade_date, now, now),
            )
            conn.commit()

    def recover_import_enrichment_jobs(self) -> list[str]:
        """Requeue incomplete enrichments after a backend restart."""
        now = datetime.utcnow()
        with self.connect() as conn:
            conn.execute(
                """
                update market_review_import_enrichment_jobs
                set stock_extraction_status = case when stock_extraction_status = 'RUNNING' then 'PENDING' else stock_extraction_status end,
                    concept_board_status = case when concept_board_status = 'RUNNING' then 'PENDING' else concept_board_status end,
                    started_at = null,
                    updated_at = %s
                where stock_extraction_status = 'RUNNING' or concept_board_status = 'RUNNING'
                """,
                (now,),
            )
            rows = conn.execute(
                """
                select trade_date
                from market_review_import_enrichment_jobs
                where stock_extraction_status = 'PENDING' or concept_board_status = 'PENDING'
                order by trade_date asc
                """
            ).fetchall()
            conn.commit()
        return [str(row["trade_date"]) for row in rows]

    def claim_import_enrichment_part(self, trade_date: str, part: str) -> bool:
        if part not in {"stock_extraction", "concept_board"}:
            raise ValueError("import enrichment part must be stock_extraction or concept_board")
        status_column = f"{part}_status"
        now = datetime.utcnow()
        with self.connect() as conn:
            row = conn.execute(
                f"""
                update market_review_import_enrichment_jobs
                set {status_column} = 'RUNNING',
                    {part}_error = null,
                    started_at = coalesce(started_at, %s),
                    updated_at = %s
                where trade_date = %s and {status_column} = 'PENDING'
                returning trade_date
                """,
                (now, now, trade_date),
            ).fetchone()
            conn.commit()
        return row is not None

    def finish_import_enrichment_part(self, trade_date: str, part: str, error: str | None = None) -> None:
        if part not in {"stock_extraction", "concept_board"}:
            raise ValueError("import enrichment part must be stock_extraction or concept_board")
        status_column = f"{part}_status"
        error_column = f"{part}_error"
        other_status_column = "concept_board_status" if part == "stock_extraction" else "stock_extraction_status"
        now = datetime.utcnow()
        with self.connect() as conn:
            conn.execute(
                f"""
                update market_review_import_enrichment_jobs
                    set {status_column} = %s,
                    {error_column} = %s,
                    completed_at = case
                        when {other_status_column} in ('SUCCESS', 'FAILED') then %s
                        else completed_at
                    end,
                    updated_at = %s
                where trade_date = %s
                """,
                ("FAILED" if error else "SUCCESS", error, now, now, trade_date),
            )
            conn.commit()

    def load_import_enrichment_job(self, trade_date: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                select trade_date, stock_extraction_status, concept_board_status,
                       stock_extraction_error, concept_board_error,
                       requested_at, started_at, completed_at, updated_at
                from market_review_import_enrichment_jobs
                where trade_date = %s
                """,
                (trade_date,),
            ).fetchone()
        return dict(row) if row else None

    def list_imported_review_stock_links(self, trade_date: str) -> list[dict[str, str]]:
        """Return the completed AI extraction bindings used by the article renderer."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                select mention_name, asset_name, asset_code
                from imported_review_stock_mentions
                where trade_date = %s
                order by length(mention_name) desc, mention_name, asset_code
                """,
                (trade_date,),
            ).fetchall()
        return [
            {
                "label": str(row["mention_name"]),
                "name": str(row["asset_name"]),
                "code": str(row["asset_code"]),
            }
            for row in rows
        ]

    def enqueue_snapshot_update_job(self, trade_date: str) -> None:
        """Request a fresh set of derived review snapshots for one imported review."""
        now = datetime.utcnow()
        with self.connect() as conn:
            conn.execute(
                """
                insert into market_review_snapshot_update_jobs (
                    trade_date, panorama_status, memory_status, panorama_error, memory_error,
                    requested_at, started_at, completed_at, updated_at
                ) values (%s, 'PENDING', 'PENDING', null, null, %s, null, null, %s)
                on conflict(trade_date) do update set
                    panorama_status = 'PENDING',
                    memory_status = 'PENDING',
                    panorama_error = null,
                    memory_error = null,
                    requested_at = excluded.requested_at,
                    started_at = null,
                    completed_at = null,
                    updated_at = excluded.updated_at
                """,
                (trade_date, now, now),
            )
            conn.commit()

    def recover_snapshot_update_jobs(self) -> list[str]:
        """Requeue interrupted and missing derived snapshots after a service restart."""
        now = datetime.utcnow()
        with self.connect() as conn:
            # A RUNNING state belongs to a previous process after startup. It has
            # no surviving worker and must be made runnable again.
            conn.execute(
                """
                update market_review_snapshot_update_jobs
                set panorama_status = case when panorama_status = 'RUNNING' then 'PENDING' else panorama_status end,
                    memory_status = case when memory_status = 'RUNNING' then 'PENDING' else memory_status end,
                    started_at = null,
                    updated_at = %s
                where panorama_status = 'RUNNING' or memory_status = 'RUNNING'
                """,
                (now,),
            )
            # Reviews imported before durable jobs existed are also recovered.
            conn.execute(
                """
                insert into market_review_snapshot_update_jobs (
                    trade_date, panorama_status, memory_status, requested_at, updated_at
                )
                select r.trade_date,
                    case when p.as_of_date is null then 'PENDING' else 'SUCCESS' end,
                    case when m.as_of_date is null then 'PENDING' else 'SUCCESS' end,
                    %s, %s
                from imported_market_reviews r
                left join screening_market_panorama_v2_snapshot p on p.as_of_date = r.trade_date
                left join screening_market_memory_cache m on m.as_of_date = r.trade_date
                where r.trade_date = (select max(trade_date) from imported_market_reviews)
                on conflict(trade_date) do nothing
                """,
                (now, now),
            )
            rows = conn.execute(
                """
                select trade_date from market_review_snapshot_update_jobs
                where panorama_status = 'PENDING' or memory_status = 'PENDING'
                order by trade_date asc
                """
            ).fetchall()
            conn.commit()
        return [str(row["trade_date"]) for row in rows]

    def claim_snapshot_update_part(self, trade_date: str, part: str) -> bool:
        if part not in {"panorama", "memory"}:
            raise ValueError("snapshot update part must be panorama or memory")
        status_column = f"{part}_status"
        with self.connect() as conn:
            row = conn.execute(
                f"""
                update market_review_snapshot_update_jobs
                set {status_column} = 'RUNNING',
                    {part}_error = null,
                    started_at = coalesce(started_at, %s),
                    updated_at = %s
                where trade_date = %s and {status_column} = 'PENDING'
                returning trade_date
                """,
                (datetime.utcnow(), datetime.utcnow(), trade_date),
            ).fetchone()
            conn.commit()
        return row is not None

    def retry_snapshot_update_part(self, trade_date: str, part: str) -> None:
        """Explicitly requeue one failed derived-snapshot part without touching the other part."""
        if part not in {"panorama", "memory"}:
            raise ValueError("snapshot update part must be panorama or memory")
        now = datetime.utcnow()
        with self.connect() as conn:
            conn.execute(
                f"""
                update market_review_snapshot_update_jobs
                set {part}_status = 'PENDING',
                    {part}_error = null,
                    completed_at = null,
                    updated_at = %s
                where trade_date = %s
                """,
                (now, trade_date),
            )
            conn.commit()

    def finish_snapshot_update_part(self, trade_date: str, part: str, error: str | None = None) -> None:
        if part not in {"panorama", "memory"}:
            raise ValueError("snapshot update part must be panorama or memory")
        status_column = f"{part}_status"
        error_column = f"{part}_error"
        now = datetime.utcnow()
        final_status = "FAILED" if error else "SUCCESS"
        other_status_column = "memory_status" if part == "panorama" else "panorama_status"
        with self.connect() as conn:
            conn.execute(
                f"""
                update market_review_snapshot_update_jobs
                set {status_column} = %s,
                    {error_column} = %s,
                    completed_at = case
                        when {other_status_column} in ('SUCCESS', 'FAILED') then %s
                        else completed_at
                    end,
                    updated_at = %s
                where trade_date = %s
                """,
                (final_status, error, now, now, trade_date),
            )
            conn.commit()

    def get_snapshot_update_job(self, trade_date: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                select trade_date, panorama_status, memory_status, panorama_error, memory_error,
                       requested_at, started_at, completed_at, updated_at
                from market_review_snapshot_update_jobs
                where trade_date = %s
                """,
                (trade_date,),
            ).fetchone()
        return dict(row) if row else None

    def save_raw_snapshot(self, trade_date: str, snapshot_type: str, source: str, payload: Any) -> None:
        now = datetime.utcnow()
        with self.connect() as conn:
            conn.execute(
                """
                insert into raw_snapshots (trade_date, snapshot_type, source, payload_json, created_at)
                values (%s, %s, %s, %s::jsonb, %s)
                on conflict(trade_date, snapshot_type, source)
                do update set payload_json = excluded.payload_json, created_at = excluded.created_at
                """,
                (trade_date, snapshot_type, source, json_dump(payload), now),
            )
            conn.commit()

    def load_raw_snapshot(self, trade_date: str, snapshot_type: str, source: str) -> Any:
        with self.connect() as conn:
            row = conn.execute(
                """
                select payload_json from raw_snapshots
                where trade_date = %s and snapshot_type = %s and source = %s
                """,
                (trade_date, snapshot_type, source),
            ).fetchone()
        if row is None:
            return None
        return row["payload_json"]

    def load_latest_raw_snapshot(
        self,
        snapshot_type: str,
        source: str,
        on_or_before: str,
    ) -> Any:
        with self.connect() as conn:
            row = conn.execute(
                """
                select payload_json from raw_snapshots
                where snapshot_type = %s and source = %s and trade_date <= %s
                order by trade_date desc, created_at desc
                limit 1
                """,
                (snapshot_type, source, on_or_before),
            ).fetchone()
        return row["payload_json"] if row else None

    def load_raw_snapshot_history(
        self,
        snapshot_type: str,
        source: str,
        on_or_before: str,
        limit: int = 252,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select trade_date, payload_json, created_at from raw_snapshots
                where snapshot_type = %s and source = %s and trade_date <= %s
                order by trade_date desc, created_at desc
                limit %s
                """,
                (snapshot_type, source, on_or_before, limit),
            ).fetchall()
        return [
            {
                "trade_date": row["trade_date"],
                "payload": row["payload_json"],
                "created_at": row["created_at"].isoformat(),
            }
            for row in reversed(rows)
        ]

    def save_series_records(
        self,
        series_type: str,
        series_key: str,
        source: str,
        records: list[dict[str, Any]],
        date_field: str,
    ) -> None:
        if not records:
            return
        now = datetime.utcnow()
        values = []
        for record in records:
            if date_field not in record:
                raise ValueError(f"series record is missing date field {date_field}")
            record_date = str(record[date_field]).replace("-", "")
            values.append((series_type, series_key, record_date, source, json_dump(record), now))
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into market_series (
                        series_type, series_key, record_date, source, payload_json, fetched_at
                    )
                    values (%s, %s, %s, %s, %s::jsonb, %s)
                    on conflict(series_type, series_key, record_date, source)
                    do update set payload_json = excluded.payload_json, fetched_at = excluded.fetched_at
                    """,
                    values,
                )
            conn.commit()

    def load_series_records(
        self,
        series_type: str,
        series_key: str,
        source: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select payload_json from market_series
                where series_type = %s and series_key = %s and source = %s
                  and record_date between %s and %s
                order by record_date
                """,
                (series_type, series_key, source, start_date, end_date),
            ).fetchall()
        return [row["payload_json"] for row in rows]

    def latest_series_date(self, series_type: str, series_key: str, source: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                select max(record_date) as latest_date from market_series
                where series_type = %s and series_key = %s and source = %s
                """,
                (series_type, series_key, source),
            ).fetchone()
        return row["latest_date"] if row and row["latest_date"] else None

    def save_overview_report(self, trade_date: str, payload: Any) -> None:
        now = datetime.utcnow()
        existing = self.load_overview_report(trade_date)
        created_at = existing.get("created_at", now.isoformat()) if isinstance(existing, dict) else now.isoformat()
        record = jsonable(
            {
                **payload,
                "created_at": created_at,
                "updated_at": now.isoformat(),
            }
        )
        with self.connect() as conn:
            conn.execute(
                """
                insert into overview_reports (trade_date, payload_json, created_at, updated_at)
                values (%s, %s::jsonb, %s, %s)
                on conflict(trade_date)
                do update set payload_json = excluded.payload_json, updated_at = excluded.updated_at
                """,
                (trade_date, json_dump(record), created_at, now),
            )
            conn.commit()

    def load_overview_report(self, trade_date: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "select payload_json from overview_reports where trade_date = %s",
                (trade_date,),
            ).fetchone()
        if row is None:
            return None
        payload = row["payload_json"]
        if isinstance(payload, str):
            return json_load(payload)
        return payload

    def load_latest_overview_report(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                select payload_json from overview_reports
                order by trade_date desc, updated_at desc
                limit 1
                """
            ).fetchone()
        if row is None:
            return None
        payload = row["payload_json"]
        if isinstance(payload, str):
            return json_load(payload)
        return payload

    def load_previous_overview_report(self, trade_date: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                select payload_json from overview_reports
                where trade_date < %s
                order by trade_date desc, updated_at desc
                limit 1
                """,
                (trade_date,),
            ).fetchone()
        if row is None:
            return None
        payload = row["payload_json"]
        return json_load(payload) if isinstance(payload, str) else payload

    def load_ai_draft(self, trade_date: str, report_type: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                select input_hash, model, payload_json, created_at, updated_at
                from ai_review_drafts
                where trade_date = %s and report_type = %s
                """,
                (trade_date, report_type),
            ).fetchone()
        if row is None:
            return None
        return {
            "input_hash": row["input_hash"],
            "model": row["model"],
            "payload": row["payload_json"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }

    def save_ai_draft(
        self,
        trade_date: str,
        report_type: str,
        input_hash: str,
        model: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.utcnow()
        existing = self.load_ai_draft(trade_date, report_type)
        created_at = existing["created_at"] if existing else now.isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                insert into ai_review_drafts (
                    trade_date, report_type, input_hash, model, payload_json, created_at, updated_at
                )
                values (%s, %s, %s, %s, %s::jsonb, %s, %s)
                on conflict(trade_date, report_type)
                do update set
                    input_hash = excluded.input_hash,
                    model = excluded.model,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (trade_date, report_type, input_hash, model, json_dump(payload), created_at, now),
            )
            conn.commit()
        return {
            "input_hash": input_hash,
            "model": model,
            "payload": jsonable(payload),
            "created_at": created_at,
            "updated_at": now.isoformat(),
        }

    def save_imported_review(self, trade_date: str, raw_content: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.utcnow()
        existing = self.load_imported_review(trade_date)
        created_at = existing["created_at"] if existing and "created_at" in existing else now.isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                insert into imported_market_reviews (
                    trade_date, raw_content, payload_json, created_at, updated_at
                )
                values (%s, %s, %s::jsonb, %s, %s)
                on conflict(trade_date)
                do update set
                    raw_content = excluded.raw_content,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (trade_date, raw_content, json_dump(payload), created_at, now),
            )
            conn.commit()
        return {
            "trade_date": trade_date,
            "raw_content": raw_content,
            "payload": jsonable(payload),
            "created_at": created_at,
            "updated_at": now.isoformat(),
        }

    def load_imported_review_ths_concept_board_snapshot(self, trade_date: str) -> dict[str, Any] | None:
        """Return the immutable official THS concept-board snapshot for one review date."""
        norm_date = trade_date.replace("-", "").strip()
        with self.connect() as conn:
            row = conn.execute(
                """
                select trade_date, source, source_row_count, payload_json, captured_at
                from imported_review_ths_concept_board_snapshots
                where trade_date = %s
                """,
                (norm_date,),
            ).fetchone()
        if row is None:
            return None
        payload = row["payload_json"]
        return {
            "trade_date": row["trade_date"],
            "source": row["source"],
            "source_row_count": int(row["source_row_count"]),
            "payload": json_load(payload) if isinstance(payload, str) else payload,
            "captured_at": row["captured_at"].isoformat(),
        }

    def save_imported_review_ths_concept_board_snapshot(
        self,
        trade_date: str,
        source: str,
        source_row_count: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist the first official board captured for a review date; never overwrite it."""
        norm_date = trade_date.replace("-", "").strip()
        captured_at = datetime.utcnow()
        with self.connect() as conn:
            conn.execute(
                """
                insert into imported_review_ths_concept_board_snapshots (
                    trade_date, source, source_row_count, payload_json, captured_at
                ) values (%s, %s, %s, %s::jsonb, %s)
                on conflict(trade_date) do nothing
                """,
                (norm_date, source, source_row_count, json_dump(payload), captured_at),
            )
            conn.commit()
        saved = self.load_imported_review_ths_concept_board_snapshot(norm_date)
        if saved is None:
            raise RuntimeError(f"failed to persist THS concept-board snapshot for {norm_date}")
        return saved

    def replace_imported_review_stock_mentions(
        self,
        trade_date: str,
        mentions: list[dict[str, Any]],
        unresolved: list[dict[str, str]],
        source_stock_count: int,
        extraction_version: str,
    ) -> dict[str, Any]:
        """Replace one review's verified stock-mention index.

        Resolved mentions are written atomically.  Unresolved model references are
        retained in the extraction-run warning JSON, so one unbindable name does
        not discard the other deterministically bound securities.
        """
        now = datetime.utcnow()
        status = "COMPLETE"
        with self.connect() as conn:
            conn.execute(
                "delete from imported_review_stock_mentions where trade_date = %s",
                (trade_date,),
            )
            for item in mentions:
                conn.execute(
                    """
                    insert into imported_review_stock_mentions (
                        trade_date, asset_code, asset_name, mention_name, canonical_theme, theme_key,
                        concepts_json, story, mention_role, source_excerpt,
                        extraction_version, created_at, updated_at
                    ) values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        trade_date,
                        item["asset_code"],
                        item["asset_name"],
                        item["mention_name"],
                        item["canonical_theme"],
                        item["theme_key"],
                        json_dump(item["concepts"]),
                        item["story"],
                        item["mention_role"],
                        item["source_excerpt"],
                        extraction_version,
                        now,
                        now,
                    ),
                )
            conn.execute(
                """
                insert into imported_review_stock_extraction_runs (
                    trade_date, source_stock_count, resolved_stock_count, unresolved_stock_json,
                    status, extraction_version, created_at, updated_at
                ) values (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                on conflict(trade_date) do update set
                    source_stock_count = excluded.source_stock_count,
                    resolved_stock_count = excluded.resolved_stock_count,
                    unresolved_stock_json = excluded.unresolved_stock_json,
                    status = excluded.status,
                    extraction_version = excluded.extraction_version,
                    updated_at = excluded.updated_at
                """,
                (
                    trade_date,
                    source_stock_count,
                    len(mentions),
                    json_dump(unresolved),
                    status,
                    extraction_version,
                    now,
                    now,
                ),
            )
            conn.commit()
        return {
            "status": status,
            "source_stock_count": source_stock_count,
            "resolved_stock_count": len(mentions),
            "unresolved_stocks": unresolved,
            "extraction_version": extraction_version,
        }

    def load_imported_review(self, trade_date: str) -> dict[str, Any] | None:
        norm_date = trade_date.replace("-", "").strip()
        formatted_date = f"{norm_date[:4]}-{norm_date[4:6]}-{norm_date[6:]}" if len(norm_date) == 8 else trade_date
        with self.connect() as conn:
            row = conn.execute(
                """
                select trade_date, raw_content, payload_json, created_at, updated_at
                from imported_market_reviews
                where trade_date = %s or trade_date = %s or trade_date = %s
                order by updated_at desc
                limit 1
                """,
                (trade_date, norm_date, formatted_date),
            ).fetchone()
        if row is None:
            return None
        payload = row["payload_json"]
        payload_data = json_load(payload) if isinstance(payload, str) else payload
        return {
            "trade_date": row["trade_date"],
            "raw_content": row["raw_content"],
            "payload": payload_data,
            "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
        }

    def load_latest_imported_review(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                select trade_date, raw_content, payload_json, created_at, updated_at
                from imported_market_reviews
                order by trade_date desc, updated_at desc
                limit 1
                """
            ).fetchone()
        if row is None:
            return None
        payload = row["payload_json"]
        payload_data = json_load(payload) if isinstance(payload, str) else payload
        return {
            "trade_date": row["trade_date"],
            "raw_content": row["raw_content"],
            "payload": payload_data,
            "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
        }

    def list_imported_review_dates(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select trade_date, payload_json->>'title' as title, payload_json->>'headline' as summary, updated_at
                from imported_market_reviews
                order by trade_date desc
                limit %s
                """,
                (limit,),
            ).fetchall()
        return rows
