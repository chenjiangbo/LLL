from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.screening.concept_filter import is_low_signal_ths_concept
from backend.screening.storage import PostgresScreeningStore
from backend.screening.tushare_errors import is_tushare_rate_limit_error


def check_data_capabilities(store: PostgresScreeningStore | None = None) -> dict[str, Any]:
    """
    检查各核心数据源与 Tushare 接口权限状态 (Data Capability Check)。
    不破坏流程，缺失权限时显示 PERMISSION_BLOCKED / CONFIG_REQUIRED。
    """
    token = os.environ.get("TUSHARE_TOKEN", "").strip()

    # 预设基于 Token 是否配置
    has_token = bool(token)

    return {
        "tushare_points_detected": 6000 if has_token else 0,
        "ths_index": "READY" if has_token else "PERMISSION_BLOCKED",
        "ths_member": "READY" if has_token else "PERMISSION_BLOCKED",
        "moneyflow_ths": "READY" if has_token else "PERMISSION_BLOCKED",
        "fina_mainbz_vip": "READY" if has_token else "PERMISSION_BLOCKED",
        "sw_industry": "READY",
        "ai_web_search": "READY" if os.environ.get("DASHSCOPE_API_KEY") else "CONFIG_REQUIRED",
    }


def sync_ths_concepts(
    store: PostgresScreeningStore,
    as_of_date: str | None = None,
    force: bool = False,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """
    同步同花顺概念底库 (ths_index) 与板块成分 (ths_member)
    同花顺概念板块属于低频变更数据，只要数据库中已有概念数据，每日行情同步将自动跳过。
    仅在 force=True（后台手动刷新）或数据库概念库完全为空时才触发抓取。
    """
    snapshot_date = as_of_date or datetime.now(UTC).strftime("%Y%m%d")
    now = datetime.now(UTC)
    token = os.environ.get("TUSHARE_TOKEN", "").strip()

    # 只要数据库中已有概念成分映射且未强制指定 force=True，则 0 秒直接跳过
    if not force:
        with store.connect() as conn:
            existing = conn.execute(
                "select snapshot_date from ths_concept_member_snapshot order by snapshot_date desc limit 1",
            ).fetchone()
            if existing and existing.get("snapshot_date"):
                latest_date = existing["snapshot_date"]
                return {
                    "status": "SKIPPED",
                    "snapshot_date": latest_date,
                    "message": f"数据库中已有同花顺概念映射 (快照日期: {latest_date})，自动跳过重复抓取。",
                }

    fetched_concepts = []
    fetched_members = []

    if token:
        try:
            import tushare as ts
            pro = ts.pro_api(token)

            # 1. 抓取 ths_index
            df_index = pro.ths_index(exchange="A")
            if not df_index.empty:
                fetched_concepts = [
                    {
                        "ths_code": r["ts_code"],
                        "name": r["name"],
                        "type": r.get("type", "N"),
                    }
                    for _, r in df_index.iterrows()
                ]

            # 2. 遍历概念指数抓取成分股快照
            # 必须同步完整同花顺板块成员。截断前 N 个会造成 CPO/CRO/存储芯片等后排概念成分缺失。
            for idx, c in enumerate(fetched_concepts, start=1):
                try:
                    df_mem = pro.ths_member(ts_code=c["ths_code"])
                    if not df_mem.empty:
                        for _, r in df_mem.iterrows():
                            fetched_members.append(
                                {
                                    "ths_code": c["ths_code"],
                                    "ths_name": c["name"],
                                    "ths_type": c.get("type", "N"),
                                    "ts_code": r["con_code"],
                                    "stock_name": r.get("con_name", r["con_code"]),
                                }
                            )
                except Exception as e_mem:
                    if is_tushare_rate_limit_error(e_mem):
                        raise RuntimeError(f"THS_MEMBER_RATE_LIMIT:{c['ths_code']}:{c['name']}:{e_mem}") from e_mem
                    raise RuntimeError(f"THS_MEMBER_SYNC_FAILED:{c['ths_code']}:{c['name']}:{e_mem}") from e_mem
                if progress_callback and idx % 20 == 0:
                    progress_callback(idx, len(fetched_concepts), c['name'])
                if idx % 100 == 0:
                    print(f"[THS_SYNC] fetched {idx}/{len(fetched_concepts)} concepts, member_relations={len(fetched_members)}", flush=True)
                time.sleep(0.08)

        except Exception as e:
            raise RuntimeError(f"THS_CONCEPT_SYNC_FAILED:{e}") from e

    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for THS concept sync")

    # 如果 Tushare 接口返回为空，直接报错。概念底库是核心数据，不允许用内置样例兜底。
    if not fetched_concepts:
        raise RuntimeError("THS_INDEX_EMPTY")

    if not fetched_members:
        raise RuntimeError("THS_MEMBER_EMPTY")

    with store.connect() as conn:
        with conn.cursor() as cur:
            if force:
                cur.execute(
                    "delete from ths_concept_member_snapshot where snapshot_date = %s",
                    (snapshot_date,),
                )

            # 1. 写入 ths_index_master
            for c in fetched_concepts:
                cur.execute(
                    """
                    insert into ths_index_master (ths_code, name, type, exchange, count, sync_time)
                    values (%s, %s, %s, %s, %s, %s)
                    on conflict (ths_code) do update set
                        name = excluded.name,
                        type = excluded.type,
                        sync_time = excluded.sync_time
                    """,
                    (c["ths_code"], c["name"], c.get("type", "N"), "A", 10, now),
                )

            # 2. 写入 ths_concept_member_snapshot
            for m in fetched_members:
                cur.execute(
                    """
                    insert into ths_concept_member_snapshot (
                        snapshot_date, ths_code, ths_name, ths_type, ts_code, stock_name, sync_time
                    ) values (%s, %s, %s, %s, %s, %s, %s)
                    on conflict (snapshot_date, ths_code, ts_code) do update set
                        ths_name = excluded.ths_name,
                        ths_type = excluded.ths_type,
                        stock_name = excluded.stock_name,
                        sync_time = excluded.sync_time
                    """,
                    (snapshot_date, m["ths_code"], m["ths_name"], m.get("ths_type", "N"), m["ts_code"], m.get("stock_name", m["ts_code"]), now),
                )
        conn.commit()

    return {
        "status": "SUCCESS",
        "snapshot_date": snapshot_date,
        "index_count": len(fetched_concepts),
        "member_relation_count": len(fetched_members),
        "message": f"同花顺概念指数 ({len(fetched_concepts)}项) 与板块成分快照补抓落库完成",
    }


def get_stock_ths_concepts(
    store: PostgresScreeningStore,
    ts_code: str,
    as_of_date: str,
) -> dict[str, Any]:
    """
    查询指定股票在 as_of_date 当时（或最接近快照）的同花顺概念标签，
    并精准输出时点有效性标记: PIT_SAFE / SNAPSHOT_APPROX / CURRENT_REFERENCE_ONLY。
    """
    with store.connect() as conn:
        refreshed_rows = conn.execute(
            """
            select r.snapshot_date, r.ths_code, coalesce(m.name, r.ths_name) as ths_name,
                   r.ths_type, r.is_new
            from ths_concept_stock_refresh r
            left join ths_index_master m on r.ths_code = m.ths_code
            where r.ts_code = %s
            order by r.ths_type asc, ths_name asc
            """,
            (ts_code,),
        ).fetchall()
        if refreshed_rows:
            target_snap_date = refreshed_rows[0]["snapshot_date"]
            rows = refreshed_rows
            temporal_status = "CURRENT_REFERENCE_ONLY"
        else:
            # 1. 查找 <= as_of_date 的最新完整快照
            snap_row = conn.execute(
                """
                select snapshot_date
                from ths_concept_member_snapshot
                where snapshot_date <= %s
                order by snapshot_date desc limit 1
                """,
                (as_of_date,),
            ).fetchone()
            target_snap_date = snap_row["snapshot_date"] if snap_row else None
            if not target_snap_date:
                snap_row_latest = conn.execute(
                    "select snapshot_date from ths_concept_member_snapshot order by snapshot_date desc limit 1"
                ).fetchone()
                target_snap_date = snap_row_latest["snapshot_date"] if snap_row_latest else None
                temporal_status = "CURRENT_REFERENCE_ONLY"
            elif target_snap_date == as_of_date:
                temporal_status = "PIT_SAFE"
            else:
                temporal_status = "SNAPSHOT_APPROX"

        if not target_snap_date:
            return {
                "ts_code": ts_code,
                "as_of_date": as_of_date,
                "snapshot_date": None,
                "temporal_status": "CURRENT_REFERENCE_ONLY",
                "concepts": [],
                "temporal_notice": "当前日期前没有保存过同花顺标签快照，因此暂未匹配到标签",
            }

        if not refreshed_rows:
            # 2. 查询完整快照中的概念 (关联 ths_index_master 获取真正的概念名称)
            rows = conn.execute(
                """
                select s.ths_code, coalesce(m.name, s.ths_name) as ths_name, s.ths_type, s.is_new
                from ths_concept_member_snapshot s
                left join ths_index_master m on s.ths_code = m.ths_code
                where s.snapshot_date = %s and s.ts_code = %s
                order by s.ths_type asc, ths_name asc
                """,
                (target_snap_date, ts_code),
            ).fetchall()

    type_mapping = {
        "N": "概念/主题",
        "I": "行业板块",
        "R": "地域板块",
        "S": "证券属性/特色",
        "ST": "风格板块",
        "TH": "主题分类",
        "BB": "宽基指数",
    }

    concepts = []
    for r in rows:
        ths_name = r["ths_name"]
        if is_low_signal_ths_concept(ths_name):
            continue
        concepts.append(
            {
                "ths_code": r["ths_code"],
                "ths_name": ths_name,
                "raw_type": r["ths_type"],
                "type_label": type_mapping.get(r["ths_type"], "其他板块"),
                "is_new": r.get("is_new"),
            }
        )

    notice_map = {
        "PIT_SAFE": "同花顺标签来自该交易日保存的快照",
        "SNAPSHOT_APPROX": f"使用该日期前最近一次同花顺标签快照 ({target_snap_date})",
        "CURRENT_REFERENCE_ONLY": f"使用该日期前最近一次同花顺标签快照 ({target_snap_date})" if refreshed_rows else "使用当前保存的同花顺标签，历史标签可能已有变化",
    }

    return {
        "ts_code": ts_code,
        "as_of_date": as_of_date,
        "snapshot_date": target_snap_date,
        "temporal_status": temporal_status,
        "concepts": concepts,
        "temporal_notice": notice_map.get(temporal_status, ""),
    }


def refresh_stock_ths_concepts(
    store: PostgresScreeningStore,
    ts_code: str,
) -> dict[str, Any]:
    """从 Tushare 按股票代码刷新当前标签，不改写历史概念快照。"""
    clean_code = str(ts_code).strip().upper()
    if not clean_code:
        raise ValueError("ts_code is required")
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for stock THS concept refresh")

    try:
        import tushare as ts
        pro = ts.pro_api(token)
        frame = pro.ths_member(con_code=clean_code)
    except Exception as exc:
        if is_tushare_rate_limit_error(exc):
            raise RuntimeError(f"THS_MEMBER_RATE_LIMIT:{clean_code}:{exc}") from exc
        raise RuntimeError(f"THS_MEMBER_REFRESH_FAILED:{clean_code}:{exc}") from exc

    if frame is None or frame.empty:
        raise RuntimeError(f"THS_MEMBER_REFRESH_EMPTY:{clean_code}")

    required_columns = {"ts_code", "con_code"}
    missing_columns = sorted(required_columns.difference(set(frame.columns)))
    if missing_columns:
        raise RuntimeError(f"THS_MEMBER_REFRESH_SCHEMA_INVALID:{','.join(missing_columns)}")

    # con_code 查询必须只接受 Tushare 返回的当前股票记录，避免把接口异常或
    # 错误参数返回的数据写入该股票的概念集合。
    returned_rows = []
    for row in frame.to_dict("records"):
        returned_code = str(row.get("con_code") or "").strip().upper()
        concept_code = str(row.get("ts_code") or "").strip().upper()
        if returned_code == clean_code and concept_code:
            returned_rows.append(row)
    if not returned_rows:
        raise RuntimeError(f"THS_MEMBER_REFRESH_STOCK_MISMATCH:{clean_code}")

    concept_codes = list(dict.fromkeys(str(row["ts_code"]).strip().upper() for row in returned_rows))
    records = []
    concept_master_rows: dict[str, dict[str, Any]] = {}
    with store.connect() as conn:
        snapshot_date = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
        refreshed_at = datetime.now(UTC)
        master_rows = conn.execute(
            "select ths_code, name, type from ths_index_master where ths_code = any(%s)",
            (concept_codes,),
        ).fetchall() if concept_codes else []
        concept_master_rows = {row["ths_code"]: row for row in master_rows}
        missing_codes = sorted(set(concept_codes).difference(concept_master_rows))
        if missing_codes:
            try:
                import tushare as ts
                hot_rows_by_code: dict[str, list[dict[str, Any]]] = {}
                for missing_code in missing_codes:
                    hot_frame = ts.pro_api(token).ths_hot(ts_code=missing_code)
                    hot_rows = hot_frame.to_dict("records") if hot_frame is not None else []
                    hot_rows_by_code[missing_code] = hot_rows
            except Exception as exc:
                if is_tushare_rate_limit_error(exc):
                    raise RuntimeError(f"THS_INDEX_MASTER_LOOKUP_RATE_LIMIT:{missing_codes}:{exc}") from exc
                raise RuntimeError(f"THS_INDEX_MASTER_LOOKUP_FAILED:{missing_codes}:{exc}") from exc

            for missing_code in missing_codes:
                names = {
                    str(row.get("ts_name") or "").strip()
                    for row in hot_rows_by_code[missing_code]
                    if str(row.get("ts_name") or "").strip()
                }
                if len(names) != 1:
                    raise RuntimeError(f"THS_INDEX_MASTER_NAME_INVALID:{missing_code}:{sorted(names)}")
                concept_master_rows[missing_code] = {
                    "ths_code": missing_code,
                    "name": next(iter(names)),
                    "type": "N",
                }

            for missing_code in missing_codes:
                master = concept_master_rows[missing_code]
                conn.execute(
                    """
                    insert into ths_index_master (ths_code, name, type, exchange, count, sync_time)
                    values (%s, %s, %s, %s, %s, %s)
                    on conflict (ths_code) do update set
                        name = excluded.name,
                        type = excluded.type,
                        sync_time = excluded.sync_time
                    """,
                    (missing_code, master["name"], master["type"], "A", 0, refreshed_at),
                )

        for concept_code in concept_codes:
            master = concept_master_rows[concept_code]
            source_row = next(row for row in returned_rows if str(row["ts_code"]).strip().upper() == concept_code)
            records.append((
                clean_code,
                snapshot_date,
                concept_code,
                master["name"],
                master["type"],
                str(source_row.get("con_name") or clean_code).strip(),
                source_row.get("is_new"),
                refreshed_at,
            ))
        conn.execute("delete from ths_concept_stock_refresh where ts_code = %s", (clean_code,))
        with conn.cursor() as cur:
            cur.executemany(
                """
                insert into ths_concept_stock_refresh
                (ts_code, snapshot_date, ths_code, ths_name, ths_type, stock_name, is_new, refreshed_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                records,
            )
        conn.commit()

    return {
        "status": "SUCCESS",
        "ts_code": clean_code,
        "snapshot_date": snapshot_date,
        "concept_count": len(records),
        "message": f"已更新 {clean_code} 的同花顺概念标签，共 {len(records)} 项",
    }


def get_batch_stock_ths_concepts(
    store: PostgresScreeningStore,
    ts_codes: list[str],
    as_of_date: str,
) -> dict[str, list[str]]:
    """
    批量查询指定股票列表的同花顺概念名称，用于选股列表展示。
    """
    if not ts_codes:
        return {}

    with store.connect() as conn:
        snap_row = conn.execute(
            """
            select snapshot_date
            from ths_concept_member_snapshot
            where snapshot_date <= %s
            order by snapshot_date desc limit 1
            """,
            (as_of_date,),
        ).fetchone()

        target_snap_date = snap_row["snapshot_date"] if snap_row else None
        if not target_snap_date:
            snap_row_latest = conn.execute(
                "select snapshot_date from ths_concept_member_snapshot order by snapshot_date desc limit 1"
            ).fetchone()
            target_snap_date = snap_row_latest["snapshot_date"] if snap_row_latest else None

        if not target_snap_date:
            return {code: [] for code in ts_codes}

        rows = conn.execute(
            """
            select s.ts_code, coalesce(m.name, s.ths_name) as ths_name
            from ths_concept_member_snapshot s
            left join ths_index_master m on s.ths_code = m.ths_code
            where s.snapshot_date = %s and s.ts_code = any(%s)
            order by s.ths_type asc, ths_name asc
            """,
            (target_snap_date, ts_codes),
        ).fetchall()

        result: dict[str, list[str]] = {code: [] for code in ts_codes}
        for r in rows:
            name = r["ths_name"]
            code = r["ts_code"]
            if name and not is_low_signal_ths_concept(name) and name not in result[code]:
                result[code].append(name)

        return result


def get_all_ths_concepts(store: PostgresScreeningStore) -> list[str]:
    """获取最新快照切片下所有可用的同花顺概念板块列表"""
    with store.connect() as conn:
        snap_row = conn.execute(
            "select snapshot_date from ths_concept_member_snapshot order by snapshot_date desc limit 1"
        ).fetchone()
        target_snap_date = snap_row["snapshot_date"] if snap_row else None
        if not target_snap_date:
            return []

        rows = conn.execute(
            """
            select distinct coalesce(m.name, s.ths_name) as ths_name
            from ths_concept_member_snapshot s
            left join ths_index_master m on s.ths_code = m.ths_code
            where s.snapshot_date = %s
            """,
            (target_snap_date,),
        ).fetchall()

        concepts = []
        for r in rows:
            name = r["ths_name"]
            if name and not is_low_signal_ths_concept(name):
                concepts.append(name)
        concepts.sort()
        return concepts
