from __future__ import annotations

import gzip
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.screening.config import screening_database_url_from_env


def main() -> None:
    database_url = screening_database_url_from_env(PROJECT_ROOT)
    backup_dir = PROJECT_ROOT / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"lll_market_review_backup_{timestamp}.sql.gz"
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        print("[Backup FAILED] pg_dump is not installed or not on PATH; no backup was created.")
        sys.exit(1)
    print(f"[Backup] Starting full database backup to {backup_path} ...")
    try:
        with gzip.open(backup_path, "wb") as output:
            completed = subprocess.run([pg_dump, database_url], stdout=output, stderr=subprocess.PIPE, check=False)
        if completed.returncode != 0:
            backup_path.unlink(missing_ok=True)
            raise RuntimeError(completed.stderr.decode("utf-8", errors="replace").strip() or "pg_dump failed")
        if backup_path.stat().st_size <= 20:
            backup_path.unlink(missing_ok=True)
            raise RuntimeError("backup output is empty")
        size_mb = backup_path.stat().st_size / (1024 * 1024)
        print(f"[Backup SUCCESS] {backup_path} ({size_mb:.2f} MB)")
    except Exception as exc:
        print(f"[Backup FAILED] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
