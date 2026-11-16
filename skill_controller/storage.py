from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Profile, default_profile, profile_from_dict, profile_to_dict


def config_path() -> Path:
    if os.name == "nt":
        app_data = os.environ.get("APPDATA")
        if not app_data:
            raise RuntimeError("Windows 缺少 APPDATA 环境变量，无法确定配置目录")
        root = Path(app_data)
    else:
        root = Path.home() / ".config"
    return root / "SkillController" / "profiles.json"


def load_profile() -> Profile:
    path = config_path()
    if not path.exists():
        return default_profile()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"配置文件格式错误：{path}")
    return profile_from_dict(data)


def save_profile(profile: Profile) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(profile_to_dict(profile), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
