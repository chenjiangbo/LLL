"""Create current stock profiles without altering historical selection snapshots.

This is a one-time, resumable migration.  It rebuilds the current fundamental
and market profiles for every security that already has a historical secondary
analysis.  Historical candidate snapshots remain untouched.  Existing theme
and AI research outputs are copied as the latest available profile only; later
manual analysis replaces them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.screening.config import screening_database_url_from_env
from backend.screening.current_stock_profile_service import (
    get_or_refresh_current_fundamental_profile,
    get_or_refresh_current_market_profile,
    get_or_refresh_current_theme_profile,
)
from backend.screening.storage import PostgresScreeningStore

STATE_PATH = PROJECT_ROOT / "data" / "migration_state" / "current_stock_profiles.json"


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_state(resume: bool) -> dict[str, Any]:
    if resume and STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "version": 1,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "completed_codes": [],
        "failures": {},
    }


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _historical_codes(store: PostgresScreeningStore) -> list[str]:
    with store.connect() as conn:
        rows = conn.execute(
            """
            select distinct ts_code
            from (
                select ts_code from company_evidence_snapshot
                union
                select ts_code from candidate_secondary_snapshot
                union
                select ts_code from ai_stock_theme_match
                union
                select ts_code from ai_stock_research
            ) all_profiled
            order by ts_code
            """
        ).fetchall()
    return [str(row["ts_code"]).strip().upper() for row in rows]


def _refresh_theme_and_copy_ai(store: PostgresScreeningStore) -> dict[str, int]:
    counts = {"theme": 0, "ai_research": 0}
    with store.connect() as conn:
        theme_rows = conn.execute(
            """
            select distinct on (ts_code) ts_code, as_of_date, result_json, status
            from ai_stock_theme_match
            order by ts_code, created_at desc
            """
        ).fetchall()
        ai_rows = conn.execute(
            """
            select distinct on (ts_code) ts_code, result_markdown, priority,
                   source_manifest_json, status
            from ai_stock_research
            order by ts_code, created_at desc
            """
        ).fetchall()
    for row in theme_rows:
        # A current profile must be matched against the latest market-theme
        # memory, not copied from a historical review date.
        get_or_refresh_current_theme_profile(store, row["ts_code"])
        counts["theme"] += 1
    for row in ai_rows:
        manifest = row["source_manifest_json"] if isinstance(row["source_manifest_json"], dict) else json.loads(row["source_manifest_json"])
        store.save_current_ai_research_profile(
            row["ts_code"], _fingerprint(manifest), row["result_markdown"],
            row["priority"], manifest, str(row["status"] or "READY"),
        )
        counts["ai_research"] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true", help="continue from the persisted migration state")
    args = parser.parse_args()

    store = PostgresScreeningStore(screening_database_url_from_env(PROJECT_ROOT))
    codes = _historical_codes(store)
    if not codes:
        raise RuntimeError("未找到任何历史股票分析记录，迁移无法开始")
    state = _load_state(args.resume)
    completed = set(state.get("completed_codes") or [])
    failures: dict[str, str] = dict(state.get("failures") or {})
    print(f"[CurrentProfileMigration] total={len(codes)} completed={len(completed)} pending={len(set(codes) - completed)}")

    for index, code in enumerate(codes, start=1):
        if code in completed:
            continue
        try:
            get_or_refresh_current_fundamental_profile(store, code)
            get_or_refresh_current_market_profile(store, code)
        except Exception as exc:  # all failures are persisted and make the migration fail explicitly
            failures[code] = f"{type(exc).__name__}: {exc}"
            state["failures"] = failures
            _save_state(state)
            print(f"[CurrentProfileMigration] FAILED {code}: {failures[code]}")
            continue
        completed.add(code)
        failures.pop(code, None)
        state["completed_codes"] = sorted(completed)
        state["failures"] = failures
        _save_state(state)
        if index % 25 == 0 or index == len(codes):
            print(f"[CurrentProfileMigration] progress={len(completed)}/{len(codes)} failures={len(failures)}")

    copied = _refresh_theme_and_copy_ai(store)
    state["finished_at"] = datetime.now().isoformat(timespec="seconds")
    state["copied"] = copied
    _save_state(state)
    if failures:
        raise RuntimeError(f"迁移未完成：{len(failures)} 只股票失败；详情见 {STATE_PATH}")
    print(f"[CurrentProfileMigration] SUCCESS fundamental_market={len(completed)} theme={copied['theme']} ai_research={copied['ai_research']}")


if __name__ == "__main__":
    main()
