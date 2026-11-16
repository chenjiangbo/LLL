"""Create a checksummed pre-migration backup of every profile source table.

The current-profile migration only inserts/updates the new current-profile
tables.  This backup nevertheless preserves all source records required to
rebuild it, independently of a locally installed pg_dump binary.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.screening.config import screening_database_url_from_env
from backend.screening.storage import PostgresScreeningStore

TABLES = (
    "candidate_secondary_snapshot",
    "company_evidence_snapshot",
    "relative_leadership_snapshot",
    "supply_profile_snapshot",
    "ai_stock_theme_match",
    "ai_stock_research",
)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date, Decimal)):
        return str(value)
    raise TypeError(f"unsupported value in backup: {type(value)!r}")


def main() -> None:
    store = PostgresScreeningStore(screening_database_url_from_env(PROJECT_ROOT))
    backup_dir = PROJECT_ROOT / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = backup_dir / f"profile_migration_sources_{stamp}.jsonl.gz"
    digest = hashlib.sha256()
    counts: dict[str, int] = {}
    with store.connect() as conn, gzip.open(path, "wt", encoding="utf-8") as output:
        for table in TABLES:
            rows = conn.execute(f"select * from {table} order by 1").fetchall()
            counts[table] = len(rows)
            for row in rows:
                line = json.dumps({"table": table, "row": dict(row)}, ensure_ascii=False, default=_json_default, sort_keys=True)
                output.write(line + "\n")
                digest.update((line + "\n").encode("utf-8"))
    if path.stat().st_size <= 20:
        path.unlink(missing_ok=True)
        raise RuntimeError("profile source backup is empty")
    manifest = {
        "backup": path.name,
        "sha256_uncompressed_jsonl": digest.hexdigest(),
        "counts": counts,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    manifest_path = path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
