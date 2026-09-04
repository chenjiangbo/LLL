from __future__ import annotations

import argparse
from pathlib import Path

from broker_node.shared.db import initialize


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args()
    initialize(args.db)
    print(f"initialized durable database: {args.db}")


if __name__ == "__main__":
    main()

