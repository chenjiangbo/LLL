"""Verify the live PostgreSQL schema required by TradePlan V2.0.

This intentionally requires MARKET_REVIEW_DATABASE_URL. It must never silently inspect a
different database or substitute an in-memory schema.
"""

from __future__ import annotations

import os

from backend.trading.tradeplan import TradePlanStore


REQUIRED_TABLES = {
    "trades",
    "trade_plan",
    "trade_leg",
    "trade_position_state",
    "position_risk_history",
    "exit_rule",
}


def main() -> None:
    database_url = os.environ["MARKET_REVIEW_DATABASE_URL"]
    store = TradePlanStore(database_url)
    with store.connect() as conn:
        tables = {
            row["tablename"]
            for row in conn.execute(
                "select tablename from pg_catalog.pg_tables where schemaname = current_schema()"
            ).fetchall()
        }
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            raise RuntimeError(f"TradePlan V2.0 schema is incomplete; missing tables: {missing}")
        columns = {
            row["column_name"]
            for row in conn.execute(
                """
                select column_name from information_schema.columns
                where table_schema=current_schema() and table_name='trade_plan'
                """
            ).fetchall()
        }
        required_plan_columns = {"trade_id", "action_type", "sequence_no", "trigger_config_json", "exit_config_json"}
        missing_columns = sorted(required_plan_columns - columns)
        if missing_columns:
            raise RuntimeError(f"trade_plan schema is incomplete; missing columns: {missing_columns}")
        print("TradePlan V2.0 PostgreSQL schema verification passed.")


if __name__ == "__main__":
    main()
