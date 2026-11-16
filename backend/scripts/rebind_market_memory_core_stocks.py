"""Repair and verify theme-cycle core-stock code bindings.

The market-memory model describes phase core stocks by company name.  Securities
codes are canonical local-master data and are therefore rebound here by exact name.
The command is deliberately transactional: an unknown or non-unique name aborts
the entire repair, leaving every snapshot unchanged.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row


MIGRATION_ID = "20260907_market_memory_core_stock_master_rebind_v1"


def _database_url() -> str:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    value = os.environ.get("MARKET_REVIEW_DATABASE_URL")
    if not value:
        raise RuntimeError("MARKET_REVIEW_DATABASE_URL is required")
    return value


def _core_stocks(memory_json: dict[str, Any]):
    for theme_index, theme in enumerate(memory_json.get("themes", [])):
        if not isinstance(theme, dict):
            raise RuntimeError(f"题材周期第 {theme_index + 1} 项不是对象")
        for phase_index, phase in enumerate(theme.get("phases", [])):
            if not isinstance(phase, dict):
                raise RuntimeError(f"题材周期第 {theme_index + 1} 项阶段 {phase_index + 1} 不是对象")
            for stock_index, stock in enumerate(phase.get("core_stocks", [])):
                if not isinstance(stock, dict):
                    raise RuntimeError(f"题材周期第 {theme_index + 1} 项阶段 {phase_index + 1} 核心股票 {stock_index + 1} 不是对象")
                name = str(stock.get("name") or "").strip()
                if not name:
                    raise RuntimeError(f"题材周期第 {theme_index + 1} 项阶段 {phase_index + 1} 核心股票 {stock_index + 1} 缺少名称")
                yield theme_index, phase_index, stock_index, name, stock


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写入修复；省略时仅做完整核查")
    args = parser.parse_args()

    with psycopg.connect(_database_url(), row_factory=dict_row) as conn:
        with conn.transaction():
            snapshots = conn.execute(
                "SELECT as_of_date, memory_json, summary_markdown FROM screening_market_memory_cache ORDER BY as_of_date FOR UPDATE"
            ).fetchall()
            master_rows = conn.execute(
                "SELECT name, asset_code FROM screening_asset_master WHERE asset_type = 'stock' ORDER BY name, asset_code"
            ).fetchall()

            master: dict[str, list[str]] = {}
            for row in master_rows:
                master.setdefault(str(row["name"]), []).append(str(row["asset_code"]).upper())

            updates: list[tuple[str, dict[str, Any]]] = []
            total = correct = mismatches = 0
            failures: list[str] = []
            for row in snapshots:
                rendered = copy.deepcopy(row["memory_json"])
                changed = False
                for theme_index, phase_index, stock_index, name, stock in _core_stocks(rendered):
                    total += 1
                    matches = master.get(name, [])
                    if len(matches) != 1:
                        reason = "未找到" if not matches else f"不唯一：{', '.join(matches)}"
                        failures.append(
                            f"{row['as_of_date']} / 题材{theme_index + 1} / 阶段{phase_index + 1} / “{name}”：{reason}"
                        )
                        continue
                    canonical_code = matches[0]
                    if str(stock.get("ts_code") or "").upper() == canonical_code:
                        correct += 1
                        continue
                    mismatches += 1
                    stock["ts_code"] = canonical_code
                    changed = True
                if changed:
                    updates.append((str(row["as_of_date"]), rendered))

            if failures:
                raise RuntimeError("核心股票主数据绑定失败，未写入任何修复：\n" + "\n".join(failures))

            if args.apply:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS screening_market_memory_cache_backup (
                        migration_id TEXT NOT NULL,
                        as_of_date VARCHAR(10) NOT NULL,
                        memory_json JSONB NOT NULL,
                        summary_markdown TEXT NOT NULL,
                        backed_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (migration_id, as_of_date)
                    )
                    """
                )
                for row in snapshots:
                    conn.execute(
                        """
                        INSERT INTO screening_market_memory_cache_backup
                            (migration_id, as_of_date, memory_json, summary_markdown, backed_at)
                        VALUES (%s, %s, %s::jsonb, %s, %s)
                        ON CONFLICT (migration_id, as_of_date) DO NOTHING
                        """,
                        (
                            MIGRATION_ID,
                            str(row["as_of_date"]),
                            json.dumps(row["memory_json"], ensure_ascii=False),
                            str(row["summary_markdown"]),
                            datetime.now(UTC),
                        ),
                    )
                for as_of_date, memory_json in updates:
                    conn.execute(
                        "UPDATE screening_market_memory_cache SET memory_json = %s::jsonb WHERE as_of_date = %s",
                        (json.dumps(memory_json, ensure_ascii=False), as_of_date),
                    )

    print(json.dumps({
        "migration_id": MIGRATION_ID,
        "mode": "apply" if args.apply else "audit",
        "snapshots": len(snapshots),
        "core_stock_rows": total,
        "already_correct": correct,
        "rebound_rows": mismatches,
        "updated_snapshots": len(updates),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
