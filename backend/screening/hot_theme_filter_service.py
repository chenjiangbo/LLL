"""Deterministic, point-in-time hot-theme filtering for A-PreV2."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import Any

from backend.screening.market_memory_service import get_cached_market_memory
from backend.screening.storage import PostgresScreeningStore

SCOPES = {
    "RECENT_60D": {"CURRENT_ACTIVE", "RECENTLY_ACTIVE", "DORMANT_BUT_TRADED"},
    "CURRENT_ACTIVE": {"CURRENT_ACTIVE"},
    "RECENTLY_ACTIVE": {"RECENTLY_ACTIVE"},
    "CURRENT_AND_RECENT": {"CURRENT_ACTIVE", "RECENTLY_ACTIVE"},
    "HISTORICAL": {"CURRENT_ACTIVE", "RECENTLY_ACTIVE", "DORMANT_BUT_TRADED"},
}


def normalize_theme_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\s\u00b7·•/\\|,，。:：()（）\[\]【】\-_—–]+", "", text)


def _themes(memory: dict[str, Any], scope: str, trade_date: str) -> list[dict[str, Any]]:
    allowed = SCOPES.get(scope)
    if not allowed:
        raise ValueError(f"不支持的热点方向范围: {scope}")
    result = []
    cutoff = date.fromisoformat(f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}") - timedelta(days=60)
    for raw in memory.get("themes") or []:
        if not isinstance(raw, dict) or raw.get("status") not in allowed:
            continue
        last_active = str(raw.get("last_active_date") or "")
        first_seen = str(raw.get("first_seen_date") or "")
        if scope == "RECENT_60D" and not (
            (last_active and last_active >= cutoff.isoformat())
            or (first_seen and first_seen >= cutoff.isoformat())
        ):
            continue
        canonical = str(raw.get("canonical_name") or "").strip()
        if not canonical:
            continue
        aliases = [str(x).strip() for x in (raw.get("aliases") or []) if str(x).strip()]
        result.append({
            "canonical_name": canonical,
            "aliases": aliases,
            "status": raw.get("status"),
            "first_seen_date": raw.get("first_seen_date"),
            "last_active_date": raw.get("last_active_date"),
            "key_review_dates": raw.get("key_review_dates") or [],
        })
    return result


def load_hot_theme_matches(
    store: PostgresScreeningStore,
    trade_date: str,
    scope: str,
    selected_theme: str | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], str]:
    """Return code -> explainable matches using the latest concept snapshot <= trade_date.

    Missing Market Memory or concept snapshots are explicit errors: callers must not
    silently use a newer date or an unfiltered result.
    """
    cached = get_cached_market_memory(store, trade_date)
    memory_date = trade_date
    if cached is None:
        # 使用评估日之前最近一次已生成的全景；禁止读取未来日期，保证点时一致。
        with store.connect() as conn:
            row = conn.execute(
                """select as_of_date, memory_json, summary_markdown
                   from screening_market_memory_cache
                   where as_of_date <= %s order by as_of_date desc, created_at desc limit 1""",
                (trade_date,),
            ).fetchone()
        if row:
            raw = row["memory_json"]
            import json
            cached = (raw if isinstance(raw, dict) else json.loads(raw), row.get("summary_markdown") or "")
            memory_date = str(row["as_of_date"])
    if cached is None:
        raise LookupError(f"交易日 {trade_date} 之前尚未生成任何市场热点全景")
    memory, _ = cached
    if scope == "RECENT_60D":
        # 合并截止日前 60 天内已生成的每日全景，避免某一天的摘要遗漏前几天仍属近期的 CPO、医药等主题。
        cutoff_text = (date.fromisoformat(f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}") - timedelta(days=60)).isoformat().replace('-', '')
        with store.connect() as conn:
            rows = conn.execute(
                "select memory_json from screening_market_memory_cache where as_of_date > %s and as_of_date <= %s order by as_of_date",
                (cutoff_text, trade_date),
            ).fetchall()
        merged: dict[str, dict[str, Any]] = {}
        import json
        for row in rows:
            raw_memory = row["memory_json"]
            current = raw_memory if isinstance(raw_memory, dict) else json.loads(raw_memory)
            for theme in current.get("themes") or []:
                key = normalize_theme_text(theme.get("canonical_name")) if isinstance(theme, dict) else ""
                if not key:
                    continue
                previous = merged.get(key, {})
                status_rank = {"DECAYED": 0, "DORMANT_BUT_TRADED": 1, "RECENTLY_ACTIVE": 2, "CURRENT_ACTIVE": 3}
                previous_status = previous.get("status")
                current_status = theme.get("status")
                merged[key] = {
                    **previous,
                    **theme,
                    "status": current_status if status_rank.get(current_status, 0) >= status_rank.get(previous_status, 0) else previous_status,
                    "last_active_date": max(str(previous.get("last_active_date") or ""), str(theme.get("last_active_date") or "")) or None,
                    "first_seen_date": min(str(previous.get("first_seen_date") or "99999999"), str(theme.get("first_seen_date") or "99999999")),
                    "aliases": sorted(set((previous.get("aliases") or []) + (theme.get("aliases") or []))),
                }
        if merged:
            memory = {"themes": list(merged.values())}
    themes = _themes(memory, scope, trade_date)
    if selected_theme:
        selected_norm = normalize_theme_text(selected_theme)
        themes = [t for t in themes if normalize_theme_text(t["canonical_name"]) == selected_norm]
        if not themes:
            raise ValueError(f"热点方向不在当前筛选范围内: {selected_theme}")

    with store.connect() as conn:
        snap = conn.execute(
            """select snapshot_date from ths_concept_member_snapshot
               where snapshot_date <= %s order by snapshot_date desc limit 1""",
            (trade_date,),
        ).fetchone()
        if not snap:
            raise LookupError(f"交易日 {trade_date} 没有可用的概念成员快照")
        snapshot_date = snap["snapshot_date"]
        rows = conn.execute(
            """select cm.ts_code, coalesce(im.name, cm.ths_name) as concept_name
               from ths_concept_member_snapshot cm
               left join ths_index_master im on im.ths_code = cm.ths_code
               where cm.snapshot_date = %s""",
            (snapshot_date,),
        ).fetchall()

    alias_map: dict[str, list[dict[str, Any]]] = {}
    for theme in themes:
        for name in [theme["canonical_name"], *theme["aliases"]]:
            key = normalize_theme_text(name)
            if key:
                alias_map.setdefault(key, []).append(theme)

    matches: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        concept_name = row.get("concept_name")
        for theme in alias_map.get(normalize_theme_text(concept_name), []):
            item = {
                "canonical_name": theme["canonical_name"],
                "matched_concept": concept_name,
                "status": theme["status"],
                "last_active_date": theme.get("last_active_date"),
            }
            if item not in matches.setdefault(row["ts_code"], []):
                matches[row["ts_code"]].append(item)

    options = []
    for theme in themes:
        options.append({
            "canonical_name": theme["canonical_name"],
            "status": theme["status"],
            "first_seen_date": theme.get("first_seen_date"),
            "last_active_date": theme.get("last_active_date"),
            "match_count": sum(1 for values in matches.values() if any(v["canonical_name"] == theme["canonical_name"] for v in values)),
        })
    options.sort(key=lambda x: (-x["match_count"], x["canonical_name"]))
    return matches, options, f"{memory_date}|概念快照:{snapshot_date}"
