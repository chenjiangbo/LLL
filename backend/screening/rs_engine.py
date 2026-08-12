"""
RS 相对强度引擎 — P2 L3

计算 RS20 / RS60 / RS120 因子，并进行横截面排名：
  - 全市场百分位排名
  - 池内（A / B / C）百分位排名
  - 申万二级行业内百分位排名

重要约束（文档红线）：
  - 必须固定 universe 后一次性计算，禁止逐个算完再合并
  - 使用 Point-in-Time 复权价格（adj_close = close * adj_factor / latest_adj_factor）
  - winsorize 1% / 99%
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.screening.storage import PostgresScreeningStore

logger = logging.getLogger(__name__)

FACTOR_VERSION = "rs_v1.0"

# RS 窗口列表，主窗口 RS60
RS_WINDOWS = [20, 60, 120]
RS_PRIMARY = 60

# winsorize 上下界
WINSORIZE_LOWER = 0.01
WINSORIZE_UPPER = 0.99


@dataclass
class RSEngine:
    store: PostgresScreeningStore
    # 最小行业样本数，小于此回退到全市场排名
    min_industry_members: int = 10
    # 是否将因子写入 factor_snapshot（P1 审计要求）
    persist_factors: bool = True

    def compute_and_save(
        self,
        trade_date: str,
        industry_source_version: str = "SW2021",
        pool_map: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        计算指定交易日的 RS 因子并写入 factor_snapshot。

        pool_map: ts_code -> pool_code (A/B/C)，用于池内排名。
                  为 None 时跳过池内排名。
        返回计算摘要。
        """
        logger.info(f"计算 {trade_date} RS 因子...")

        # ── 1. 加载 Point-in-Time 复权收益率序列 ────────────────────────
        adj_returns = self._load_adj_returns(trade_date, max_window=max(RS_WINDOWS) + 5)
        if adj_returns.empty:
            logger.warning(f"{trade_date} 无复权日线数据，跳过 RS 计算")
            return {"trade_date": trade_date, "computed": 0}

        # 只保留 stock 类型（RS 排名 universe 只含股票）
        stock_codes = list(adj_returns.index)
        logger.info(f"RS universe: {len(stock_codes)} 只股票")

        # ── 2. 计算各窗口窗口收益率（截面） ─────────────────────────────
        rs_data: dict[str, pd.Series] = {}
        for w in RS_WINDOWS:
            ret = self._window_return(adj_returns, w)
            if ret.empty:
                continue
            # winsorize
            lo = ret.quantile(WINSORIZE_LOWER)
            hi = ret.quantile(WINSORIZE_UPPER)
            ret_clipped = ret.clip(lo, hi)
            rs_data[f"rs{w}"] = ret_clipped

        if not rs_data:
            logger.warning("所有 RS 窗口计算失败")
            return {"trade_date": trade_date, "computed": 0}

        df_rs = pd.DataFrame(rs_data)  # index=ts_code

        # ── 3. 全市场横截面排名（百分位） ────────────────────────────────
        rank_cols: dict[str, pd.Series] = {}
        for col in df_rs.columns:
            rank_cols[f"{col}_rank_all"] = df_rs[col].rank(pct=True, na_option="keep")

        # ── 4. 池内排名 ──────────────────────────────────────────────────
        if pool_map:
            pool_series = pd.Series(pool_map)
            for pool in ["A", "B", "C"]:
                pool_codes = pool_series[pool_series == pool].index.tolist()
                pool_subset = df_rs.loc[df_rs.index.isin(pool_codes)]
                if pool_subset.empty:
                    continue
                for col in df_rs.columns:
                    rank_col = f"{col}_rank_pool_{pool}"
                    ranked = pool_subset[col].rank(pct=True, na_option="keep")
                    rank_cols[rank_col] = ranked

        # ── 5. 申万二级行业内排名 ─────────────────────────────────────────
        memberships = self.store.load_industry_membership_for_date(
            trade_date, industry_source_version
        )
        # 构建 ts_code -> l2_code
        l2_map: dict[str, str] = {}
        for ts_code, mem in memberships.items():
            l2 = mem.get("l2_code")
            if l2:
                l2_map[ts_code] = l2

        l2_series = pd.Series(l2_map)
        unique_l2 = l2_series.unique()
        for l2_code in unique_l2:
            members = l2_series[l2_series == l2_code].index.tolist()
            # 小样本回退到全市场排名（文档要求）
            if len(members) < self.min_industry_members:
                continue
            subset = df_rs.loc[df_rs.index.isin(members)]
            if subset.empty:
                continue
            for col in df_rs.columns:
                ranked = subset[col].rank(pct=True, na_option="keep")
                # 用 l2_code 标记行业内排名（存为独立因子）
                rank_col = f"{col}_rank_ind_{l2_code}"
                rank_cols[rank_col] = ranked

        # ── 6. 汇总并持久化 ──────────────────────────────────────────────
        all_cols = pd.concat([df_rs, pd.DataFrame(rank_cols)], axis=1)

        factor_rows: list[dict[str, Any]] = []
        for ts_code in all_cols.index:
            for factor_name, val in all_cols.loc[ts_code].items():
                if pd.isna(val):
                    continue
                factor_rows.append({
                    "trade_date":   trade_date,
                    "ts_code":      ts_code,
                    "factor_name":  factor_name,
                    "factor_value": float(val),
                    "data_quality": "OK",
                })

        if self.persist_factors and factor_rows:
            self.store.save_factor_snapshots(factor_rows, FACTOR_VERSION)
            logger.info(f"写入 {len(factor_rows)} 条因子快照")

        return {
            "trade_date": trade_date,
            "universe_size": len(stock_codes),
            "factor_count": len(df_rs.columns),
            "factor_rows": len(factor_rows),
        }

    def load_rs_for_date(
        self, trade_date: str, ts_codes: list[str] | None = None
    ) -> pd.DataFrame:
        """加载指定日期的 RS 因子，返回 DataFrame（index=ts_code）"""
        factor_names = [f"rs{w}" for w in RS_WINDOWS] + [
            f"rs{w}_rank_all" for w in RS_WINDOWS
        ]
        rows = self.store.load_factor_snapshots(
            trade_date, factor_names, FACTOR_VERSION, ts_codes=ts_codes
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).pivot(
            index="ts_code", columns="factor_name", values="factor_value"
        )
        return df

    # ── 内部方法 ───────────────────────────────────────────────────────────

    def _load_adj_returns(self, end_date: str, max_window: int) -> pd.DataFrame:
        """
        加载个股复权价格，返回以 end_date 为最新日的 adj_close 序列。
        index=ts_code，columns=trade_date（升序）
        只含 stock 类型。
        """
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                select b.asset_code as ts_code,
                       b.trade_date,
                       b.close,
                       coalesce(f.adj_factor, 1.0) as adj_factor
                from screening_daily_bar b
                left join screening_adj_factor f
                    on f.asset_code = b.asset_code and f.trade_date = b.trade_date
                where b.trade_date <= %s
                  and b.asset_type = 'stock'
                order by b.asset_code, b.trade_date
                """,
                (end_date,),
            ).fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame([dict(r) for r in rows])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["adj_factor"] = pd.to_numeric(df["adj_factor"], errors="coerce").fillna(1.0)

        # 计算前复权价：adj_close = close * adj_factor / latest_adj_factor
        latest_adj = df.groupby("ts_code")["adj_factor"].last()
        df = df.merge(latest_adj.rename("latest_adj"), on="ts_code")
        df["adj_close"] = df["close"] * df["adj_factor"] / df["latest_adj"]

        # pivot：行=ts_code，列=trade_date
        pivot = df.pivot_table(
            index="ts_code", columns="trade_date", values="adj_close", aggfunc="last"
        )
        # 只保留有 end_date 数据且至少有 max_window 天的股票
        pivot = pivot[pivot.columns[pivot.columns <= end_date]]
        pivot = pivot.dropna(subset=[end_date])  # 当日无数据的剔除
        pivot = pivot[pivot.notna().sum(axis=1) >= max_window]

        return pivot

    def _window_return(self, adj_pivot: pd.DataFrame, window: int) -> pd.Series:
        """
        计算指定窗口的区间收益率（end_date vs end_date - window 个交易日）。
        返回 Series，index=ts_code。
        """
        cols = adj_pivot.columns.tolist()  # 已按日期升序
        if len(cols) < window + 1:
            return pd.Series(dtype=float)

        end_col   = cols[-1]
        start_col = cols[-(window + 1)]

        end_price   = adj_pivot[end_col]
        start_price = adj_pivot[start_col]

        valid = (start_price > 0) & start_price.notna() & end_price.notna()
        ret = (end_price / start_price - 1).where(valid)
        return ret.dropna()
