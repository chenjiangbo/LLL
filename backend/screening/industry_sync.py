"""
申万行业数据同步模块 — P2

功能：
  1. 从 Tushare index_classify 获取申万三级行业树结构
  2. 从 Tushare index_member_all 获取个股历史申万成分（含 in/out date）
  3. 写入 industry_membership_history
  4. 如果有 sw_daily 权限（5000积分），同步行业日线并计算 ind_trend_score
     否则：从个股 daily_bar 聚合计算行业强度（降级方案）

所有与 Tushare 的交互都显式传入 api 对象，不做任何隐式切换。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.screening.storage import PostgresScreeningStore

logger = logging.getLogger(__name__)

# 申万行业体系版本
SW_SOURCE_VERSION = "SW2021"


@dataclass
class IndustrySyncService:
    store: PostgresScreeningStore
    ts_api: Any  # tushare.pro_api 实例

    def sync_industry_classify(self) -> dict[str, Any]:
        """
        同步申万三级行业树。
        返回各级别行业数量。
        """
        logger.info("同步申万行业分类树（index_classify）...")
        # 申万一级
        df_l1 = self.ts_api.index_classify(level="L1", src="SW2021")
        # 申万二级
        df_l2 = self.ts_api.index_classify(level="L2", src="SW2021")
        # 申万三级
        df_l3 = self.ts_api.index_classify(level="L3", src="SW2021")

        return {
            "l1_count": len(df_l1) if df_l1 is not None else 0,
            "l2_count": len(df_l2) if df_l2 is not None else 0,
            "l3_count": len(df_l3) if df_l3 is not None else 0,
        }

    def sync_industry_members(self) -> dict[str, Any]:
        """
        同步个股申万行业归属历史（index_member_all）。
        写入 industry_membership_history 表。

        Tushare index_member_all 字段：
          index_code, con_code, con_name, in_date, out_date, is_new
        需要配合 index_classify 获取三级归属关系。
        """
        logger.info("同步申万行业成分历史（index_member_all）...")

        # 获取各级行业代码映射
        df_l1 = self.ts_api.index_classify(level="L1", src="SW2021")
        df_l2 = self.ts_api.index_classify(level="L2", src="SW2021")
        df_l3 = self.ts_api.index_classify(level="L3", src="SW2021")

        # 构建 index_code -> (level, name, parent) 映射
        industry_meta: dict[str, dict[str, Any]] = {}
        if df_l1 is not None:
            for _, row in df_l1.iterrows():
                industry_meta[str(row["index_code"])] = {
                    "level": 1, "name": row.get("industry_name", ""),
                }
        if df_l2 is not None:
            for _, row in df_l2.iterrows():
                industry_meta[str(row["index_code"])] = {
                    "level": 2, "name": row.get("industry_name", ""),
                    "parent": str(row.get("parent_code", "")),
                }
        if df_l3 is not None:
            for _, row in df_l3.iterrows():
                industry_meta[str(row["index_code"])] = {
                    "level": 3, "name": row.get("industry_name", ""),
                    "parent": str(row.get("parent_code", "")),
                }

        # 获取申万三级成分历史（包含 in/out date）
        # 按三级行业逐个拉取（Tushare 接口限制）
        l3_codes = [k for k, v in industry_meta.items() if v.get("level") == 3]
        if not l3_codes:
            # 兜底：直接拉全量
            df_members = self.ts_api.index_member_all(src="SW2021")
            if df_members is None or df_members.empty:
                logger.warning("index_member_all 返回空，跳过")
                return {"synced": 0}
            all_members = df_members
        else:
            frames = []
            for l3_code in l3_codes:
                try:
                    df = self.ts_api.index_member_all(index_code=l3_code)
                    if df is not None and not df.empty:
                        df["l3_index_code"] = l3_code
                        frames.append(df)
                except Exception as e:
                    logger.warning(f"index_member_all({l3_code}) 失败: {e}")
            if not frames:
                logger.warning("所有三级行业成分拉取失败，跳过")
                return {"synced": 0}
            all_members = pd.concat(frames, ignore_index=True)

        # 构建归属记录（每只股票取最新/最相关的三级归属）
        memberships: list[dict[str, Any]] = []
        for _, row in all_members.iterrows():
            ts_code = str(row.get("con_code", "")).strip()
            if not ts_code:
                continue

            l3_code = str(row.get("l3_index_code", row.get("index_code", ""))).strip()
            l3_info = industry_meta.get(l3_code, {})
            l2_code = str(l3_info.get("parent", "")).strip()
            l2_info = industry_meta.get(l2_code, {})
            l1_code = str(l2_info.get("parent", "")).strip()
            l1_info = industry_meta.get(l1_code, {})

            memberships.append({
                "ts_code":  ts_code,
                "l1_code":  l1_code or None,
                "l1_name":  l1_info.get("name") or None,
                "l2_code":  l2_code or None,
                "l2_name":  l2_info.get("name") or None,
                "l3_code":  l3_code or None,
                "l3_name":  l3_info.get("name") or None,
                "in_date":  str(row.get("in_date", "") or "").strip() or None,
                "out_date": str(row.get("out_date", "") or "").strip() or None,
            })

        if memberships:
            self.store.save_industry_memberships(memberships, SW_SOURCE_VERSION)
            logger.info(f"写入 {len(memberships)} 条行业归属记录")

        return {"synced": len(memberships)}

    def sync_industry_daily(
        self, trade_date: str, has_sw_daily_permission: bool = False
    ) -> dict[str, Any]:
        """
        同步申万行业日线，计算行业强度分。

        has_sw_daily_permission=True：使用 Tushare sw_daily（需要 5000 积分）
        has_sw_daily_permission=False：从个股 daily_bar 聚合（降级方案）
        """
        if has_sw_daily_permission:
            return self._sync_from_sw_daily(trade_date)
        else:
            return self._sync_from_stock_aggregation(trade_date)

    def _sync_from_sw_daily(self, trade_date: str) -> dict[str, Any]:
        """使用 sw_daily 接口（需 5000 积分）"""
        logger.info(f"从 sw_daily 同步 {trade_date} 行业日线...")
        df = self.ts_api.sw_daily(trade_date=trade_date)
        if df is None or df.empty:
            logger.warning(f"sw_daily({trade_date}) 返回空")
            return {"synced": 0, "method": "sw_daily"}

        snapshots: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            industry_code = str(row.get("index_code", "")).strip()
            if not industry_code:
                continue
            pct_chg  = _safe_float(row.get("pct_change"))
            # ind_trend_score 简单版：以 pct_change 为基础，后续可扩展
            trend_score = _simple_trend_score(pct_chg)
            snapshots.append({
                "trade_date":     trade_date,
                "industry_code":  industry_code,
                "industry_level": 2,  # sw_daily 默认是二级
                "industry_name":  str(row.get("name", "") or ""),
                "ret_1d":         pct_chg,
                "ind_trend_score": trend_score,
                "raw_json": dict(row),
            })

        if snapshots:
            self.store.save_industry_factor_snapshots(snapshots)

        return {"synced": len(snapshots), "method": "sw_daily"}

    def _sync_from_stock_aggregation(self, trade_date: str) -> dict[str, Any]:
        """
        降级方案：从个股 daily_bar + industry_membership_history 聚合计算行业涨跌。
        不依赖 sw_daily，只需 2000 积分数据。
        """
        logger.info(f"从个股日线聚合 {trade_date} 行业强度（降级方案）...")

        # 加载当日个股涨跌幅
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                select b.asset_code as ts_code, b.pct_chg
                from screening_daily_bar b
                where b.trade_date = %s and b.asset_type = 'stock'
                """,
                (trade_date,),
            ).fetchall()

        if not rows:
            logger.warning(f"当日 {trade_date} 无股票日线数据，跳过行业聚合")
            return {"synced": 0, "method": "stock_aggregation"}

        pct_map = {row["ts_code"]: _safe_float(row["pct_chg"]) for row in rows}

        # 加载行业归属（point-in-time）
        memberships = self.store.load_industry_membership_for_date(
            trade_date, SW_SOURCE_VERSION
        )

        # 按申万二级行业聚合
        industry_data: dict[str, dict[str, Any]] = {}
        for ts_code, mem in memberships.items():
            pct = pct_map.get(ts_code)
            if pct is None:
                continue
            l2_code = mem.get("l2_code")
            if not l2_code:
                continue
            if l2_code not in industry_data:
                industry_data[l2_code] = {
                    "l2_name": mem.get("l2_name"),
                    "l1_code": mem.get("l1_code"),
                    "pct_list": [],
                    "up": 0, "down": 0, "flat": 0,
                }
            d = industry_data[l2_code]
            d["pct_list"].append(pct)
            if pct > 0:
                d["up"] += 1
            elif pct < 0:
                d["down"] += 1
            else:
                d["flat"] += 1

        snapshots: list[dict[str, Any]] = []
        for l2_code, data in industry_data.items():
            pct_list = data["pct_list"]
            total = len(pct_list)
            if total == 0:
                continue
            avg_ret = sum(pct_list) / total
            up_ratio = data["up"] / total
            trend_score = _simple_trend_score(avg_ret, up_ratio=up_ratio)
            snapshots.append({
                "trade_date":     trade_date,
                "industry_code":  l2_code,
                "industry_level": 2,
                "industry_name":  data["l2_name"],
                "ret_1d":         avg_ret,
                "up_count":       data["up"],
                "down_count":     data["down"],
                "total_count":    total,
                "ind_trend_score": trend_score,
                "raw_json":       {},
            })

        if snapshots:
            self.store.save_industry_factor_snapshots(snapshots)

        return {"synced": len(snapshots), "method": "stock_aggregation"}


# ── 辅助函数 ───────────────────────────────────────────────────────────────────

def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _simple_trend_score(ret_1d: float | None, up_ratio: float | None = None) -> float:
    """
    简单版行业趋势分（0-100）。
    V1 仅用当日涨跌幅 + 上涨家数比例估算。
    后续可扩展为 ret_5d / ret_20d / ret_60d 加权。
    """
    score = 50.0  # 基准
    if ret_1d is not None:
        score += min(ret_1d * 5, 20)   # 涨跌幅贡献（最多 ±20）
    if up_ratio is not None:
        score += (up_ratio - 0.5) * 30  # 广度贡献（最多 ±15）
    return max(0.0, min(100.0, round(score, 2)))
