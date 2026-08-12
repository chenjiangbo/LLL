from __future__ import annotations

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
    print(f"[Backup] Starting full database backup to {backup_path} ...")
    cmd = f'pg_dump "{database_url}" | gzip > "{backup_path}"'
    try:
        subprocess.run(cmd, shell=True, check=True)
        size_mb = backup_path.stat().st_size / (1024 * 1024)
        print(f"[Backup SUCCESS] {backup_path} ({size_mb:.2f} MB)")
    except Exception as exc:
        print(f"[Backup FAILED] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
