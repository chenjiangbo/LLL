from __future__ import annotations

from datetime import date, datetime, timedelta, UTC
from typing import Any

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from backend.screening.tushare_source import TushareScreeningSource


class TradingCalendarUnavailableError(RuntimeError):
    """Raised when an authoritative, current trading calendar is unavailable."""


class TradingCalendarStore:
    EXCHANGE = "SSE"
    SOURCE = "tushare.trade_cal"
    MAX_AGE = timedelta(hours=36)

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
                create table if not exists exchange_trading_calendar (
                    exchange text not null,
                    cal_date date not null,
                    is_open boolean not null,
                    source text not null,
                    fetched_at timestamptz not null,
                    primary key (exchange, cal_date)
                )
            """)
            conn.execute("""
                create table if not exists exchange_trading_calendar_coverage (
                    exchange text not null,
                    calendar_year integer not null,
                    calendar_days integer not null,
                    open_days integer not null,
                    source text not null,
                    fetched_at timestamptz not null,
                    primary key (exchange, calendar_year)
                )
            """)

    @staticmethod
    def _normalize_source_frame(frame: pd.DataFrame, start: date, end: date) -> list[tuple[date, bool]]:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise TradingCalendarUnavailableError("Tushare trade_cal returned no calendar rows")
        required = {"exchange", "cal_date", "is_open"}
        missing = required.difference(frame.columns)
        if missing:
            raise TradingCalendarUnavailableError(f"Tushare trade_cal is missing columns: {sorted(missing)}")

        rows: list[tuple[date, bool]] = []
        seen: set[date] = set()
        for item in frame.to_dict("records"):
            if str(item["exchange"]).upper() != TradingCalendarStore.EXCHANGE:
                raise TradingCalendarUnavailableError(f"Unexpected calendar exchange: {item['exchange']}")
            raw_date = str(item["cal_date"])
            try:
                day = datetime.strptime(raw_date, "%Y%m%d").date()
            except ValueError as exc:
                raise TradingCalendarUnavailableError(f"Invalid calendar date: {raw_date}") from exc
            if not start <= day <= end:
                raise TradingCalendarUnavailableError(f"Tushare returned an out-of-range date: {raw_date}")
            if day in seen:
                raise TradingCalendarUnavailableError(f"Tushare returned duplicate calendar date: {raw_date}")
            seen.add(day)
            raw_open: Any = item["is_open"]
            if raw_open in (1, "1", True):
                is_open = True
            elif raw_open in (0, "0", False):
                is_open = False
            else:
                raise TradingCalendarUnavailableError(f"Invalid is_open value for {raw_date}: {raw_open!r}")
            rows.append((day, is_open))

        expected_days = (end - start).days + 1
        if len(rows) != expected_days:
            missing_dates = expected_days - len(rows)
            raise TradingCalendarUnavailableError(
                f"Tushare calendar coverage incomplete for {start}..{end}: "
                f"expected {expected_days} dates, received {len(rows)} (missing {missing_dates})"
            )
        rows.sort(key=lambda item: item[0])
        open_days = sum(1 for _, is_open in rows if is_open)
        if not 200 <= open_days <= 260:
            raise TradingCalendarUnavailableError(
                f"Tushare calendar has an implausible number of open days for {start.year}: {open_days}"
            )
        months_with_open_days = {day.month for day, is_open in rows if is_open}
        if len(months_with_open_days) != 12:
            raise TradingCalendarUnavailableError(
                f"Tushare calendar is missing open-day coverage in months: "
                f"{sorted(set(range(1, 13)) - months_with_open_days)}"
            )
        return rows

    def refresh_year(self, source: TushareScreeningSource, year: int) -> dict[str, int | str]:
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        try:
            frame = source.trading_calendar(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        except Exception as exc:
            raise TradingCalendarUnavailableError(f"Tushare trade_cal({year}) failed: {exc}") from exc
        rows = self._normalize_source_frame(frame, start, end)
        fetched_at = datetime.now(UTC)
        with self.connect() as conn:
            conn.execute(
                "delete from exchange_trading_calendar where exchange=%s and cal_date between %s and %s",
                (self.EXCHANGE, start, end),
            )
            conn.executemany(
                """
                insert into exchange_trading_calendar(exchange, cal_date, is_open, source, fetched_at)
                values (%s, %s, %s, %s, %s)
                """,
                [(self.EXCHANGE, day, is_open, self.SOURCE, fetched_at) for day, is_open in rows],
            )
            open_days = sum(1 for _, is_open in rows if is_open)
            conn.execute(
                """
                insert into exchange_trading_calendar_coverage(
                    exchange, calendar_year, calendar_days, open_days, source, fetched_at
                ) values (%s, %s, %s, %s, %s, %s)
                on conflict(exchange, calendar_year) do update set
                    calendar_days=excluded.calendar_days,
                    open_days=excluded.open_days,
                    source=excluded.source,
                    fetched_at=excluded.fetched_at
                """,
                (self.EXCHANGE, year, len(rows), open_days, self.SOURCE, fetched_at),
            )
        return {"year": year, "calendar_days": len(rows), "open_days": open_days, "fetched_at": fetched_at.isoformat()}

    def year_is_fresh(self, year: int, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        with self.connect() as conn:
            row = conn.execute(
                """
                select coverage.calendar_days, coverage.open_days, coverage.source, coverage.fetched_at,
                       count(calendar.cal_date)::integer as stored_days,
                       count(*) filter (where calendar.is_open)::integer as stored_open_days
                from exchange_trading_calendar_coverage as coverage
                left join exchange_trading_calendar as calendar
                  on calendar.exchange=coverage.exchange
                 and calendar.cal_date between %s and %s
                where coverage.exchange=%s and coverage.calendar_year=%s
                group by coverage.calendar_days, coverage.open_days, coverage.source, coverage.fetched_at
                """,
                (start, end, self.EXCHANGE, year),
            ).fetchone()
        if not row:
            return False
        expected_days = (date(year + 1, 1, 1) - date(year, 1, 1)).days
        fetched_at = row["fetched_at"]
        return (
            int(row["calendar_days"]) == expected_days
            and int(row["stored_days"]) == expected_days
            and int(row["stored_open_days"]) == int(row["open_days"])
            and row["source"] == self.SOURCE
            and current - fetched_at <= self.MAX_AGE
        )

    def require_year(self, year: int) -> None:
        if not self.year_is_fresh(year):
            raise TradingCalendarUnavailableError(
                f"{year} 年上交所交易日历缺失或超过 {self.MAX_AGE.total_seconds() / 3600:g} 小时未刷新"
            )

    def is_open(self, day: date) -> bool:
        self.require_year(day.year)
        with self.connect() as conn:
            row = conn.execute(
                "select is_open from exchange_trading_calendar where exchange=%s and cal_date=%s",
                (self.EXCHANGE, day),
            ).fetchone()
        if not row:
            raise TradingCalendarUnavailableError(f"{day} 的交易日历记录缺失")
        return bool(row["is_open"])

    def previous_open_date(self, day: date) -> date:
        self.require_year(day.year)
        with self.connect() as conn:
            row = conn.execute(
                "select cal_date from exchange_trading_calendar where exchange=%s and is_open=true and cal_date < %s order by cal_date desc limit 1",
                (self.EXCHANGE, day),
            ).fetchone()
        if not row and day.year > 1:
            self.require_year(day.year - 1)
            with self.connect() as conn:
                row = conn.execute(
                    "select cal_date from exchange_trading_calendar where exchange=%s and is_open=true and cal_date < %s order by cal_date desc limit 1",
                    (self.EXCHANGE, day),
                ).fetchone()
        if not row:
            raise TradingCalendarUnavailableError(f"无法从交易日历找到 {day} 之前的开市日")
        if row["cal_date"].year != day.year:
            self.require_year(row["cal_date"].year)
        return row["cal_date"]

    def next_open_date(self, day: date, *, inclusive: bool) -> date:
        self.require_year(day.year)
        operator = ">=" if inclusive else ">"
        with self.connect() as conn:
            row = conn.execute(
                f"select cal_date from exchange_trading_calendar where exchange=%s and is_open=true and cal_date {operator} %s order by cal_date limit 1",
                (self.EXCHANGE, day),
            ).fetchone()
        if not row:
            self.require_year(day.year + 1)
            with self.connect() as conn:
                row = conn.execute(
                    f"select cal_date from exchange_trading_calendar where exchange=%s and is_open=true and cal_date {operator} %s order by cal_date limit 1",
                    (self.EXCHANGE, day),
                ).fetchone()
        if not row:
            raise TradingCalendarUnavailableError(f"交易日历中找不到 {day} 之后的开市日")
        if row["cal_date"].year != day.year:
            self.require_year(row["cal_date"].year)
        return row["cal_date"]
