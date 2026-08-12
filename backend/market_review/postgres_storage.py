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
            try:
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
            except Exception:
                pass
            conn.execute(
                "create index if not exists idx_raw_snapshots_trade_date on raw_snapshots(trade_date)"
            )
            conn.execute(
                "create index if not exists idx_market_series_lookup on market_series(series_type, series_key, record_date)"
            )
            conn.commit()

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

    def load_imported_review(self, trade_date: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                select trade_date, raw_content, payload_json, created_at, updated_at
                from imported_market_reviews
                where trade_date = %s
                """,
                (trade_date,),
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

