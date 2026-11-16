#!/usr/bin/env python3
"""启动 Skill Controller 图形界面。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skill_controller.app import main


if __name__ == "__main__":
    raise SystemExit(main())
