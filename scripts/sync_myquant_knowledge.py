#!/usr/bin/env python3
"""Synchronize the pinned MyQuant development references and official examples."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DEST = ROOT / ".agents" / "skills" / "myquant-dev"
STRATEGY_DEST = ROOT / "vendor" / "myquant-strategy"
LOCK_PATH = ROOT / "docs" / "vendor" / "myquant" / "SOURCE_LOCK.json"
SKILL_SOURCE = Path("plugins/myquant-dev/skills/myquant-dev")

SOURCES = {
    "myquant_dev": "https://github.com/aliwangzai/myquant-dev.git",
    "myquant_strategy": "https://github.com/myquant/strategy.git",
}


def run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        args, cwd=cwd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return result.stdout.strip()


def require_file(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"缺少必要文件：{path}")


def validate_skill(source: Path) -> int:
    skill = source / "SKILL.md"
    references = source / "references"
    require_file(skill)
    if not references.is_dir():
        raise RuntimeError(f"缺少 references 目录：{references}")
    text = skill.read_text(encoding="utf-8")
    if not text.startswith("---") or "name:" not in text or "description:" not in text:
        raise RuntimeError(f"SKILL.md 缺少有效 frontmatter：{skill}")
    count = len(list(references.glob("*.md")))
    if count < 29:
        raise RuntimeError(f"references 文档数量异常：{count}，预期至少 29 篇")
    return count


def replace_tree(source: Path, destination: Path) -> None:
    staging = destination.parent / f".{destination.name}.sync-staging"
    if staging.exists():
        raise RuntimeError(f"发现未完成的同步暂存目录，请人工检查后移除：{staging}")
    shutil.copytree(source, staging, ignore=shutil.ignore_patterns(".git"))
    try:
        if destination.exists():
            shutil.rmtree(destination)
        staging.replace(destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def normalize_skill_name(path: Path) -> None:
    skill = path / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    text = text.replace("name: myquant_dev", "name: myquant-dev", 1)
    text = text.replace("version: 1.0.4\n", "", 1)
    trigger_start = text.find("triggers:\n")
    if trigger_start >= 0:
        trigger_end = text.find("---\n", trigger_start)
        if trigger_end < 0:
            raise RuntimeError("无法规范化 Skill frontmatter：缺少结束标记")
        text = text[:trigger_start] + text[trigger_end:]
    skill.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    ROOT.joinpath(".agents/skills", "myquant-dev").parent.mkdir(parents=True, exist_ok=True)
    STRATEGY_DEST.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="myquant-knowledge-") as temp:
        temp_root = Path(temp)
        dev_checkout = temp_root / "myquant-dev"
        strategy_checkout = temp_root / "myquant-strategy"
        print("正在获取 aliwangzai/myquant-dev …")
        run("git", "clone", "--depth", "1", SOURCES["myquant_dev"], str(dev_checkout))
        print("正在获取 myquant/strategy …")
        run("git", "clone", "--depth", "1", SOURCES["myquant_strategy"], str(strategy_checkout))

        skill_source = dev_checkout / SKILL_SOURCE
        references_count = validate_skill(skill_source)
        require_file(strategy_checkout / "README.md")
        require_file(strategy_checkout / "LICENSE")

        dev_commit = run("git", "rev-parse", "HEAD", cwd=dev_checkout)
        strategy_commit = run("git", "rev-parse", "HEAD", cwd=strategy_checkout)
        replace_tree(skill_source, SKILL_DEST)
        normalize_skill_name(SKILL_DEST)
        replace_tree(strategy_checkout, STRATEGY_DEST)

    lock = {
        "myquant_dev": {
            "repository": SOURCES["myquant_dev"],
            "commit": dev_commit,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "references_count": references_count,
        },
        "myquant_strategy": {
            "repository": SOURCES["myquant_strategy"],
            "commit": strategy_commit,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    LOCK_PATH.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已同步 Skill：{SKILL_DEST}")
    print(f"已同步策略库：{STRATEGY_DEST}")
    print(f"已更新锁定文件：{LOCK_PATH}")
    print(f"myquant-dev: {dev_commit} ({references_count} 篇 references)")
    print(f"myquant/strategy: {strategy_commit}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (subprocess.CalledProcessError, OSError, RuntimeError) as exc:
        print(f"同步失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
