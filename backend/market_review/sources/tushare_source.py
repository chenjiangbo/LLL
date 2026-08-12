from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from typing import Any

import pandas as pd
import tushare as ts

from backend.market_review.config import CORE_INDICES
from backend.market_review.errors import MarketReviewError


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return df.astype(object).where(pd.notna(df), None).to_dict(orient="records")


@dataclass
class TushareSource:
    token: str

    @classmethod
    def from_env(cls) -> "TushareSource":
        token = os.getenv("TUSHARE_TOKEN", "").strip()
        if not token:
            raise MarketReviewError("TUSHARE_TOKEN is required for constituent attribution")
        return cls(token=token)

    @property
    def pro(self):
        return ts.pro_api(self.token)

    def fetch_daily_snapshot(self, trade_date: str) -> dict[str, Any]:
        fields = "ts_code,trade_date,close,pre_close,pct_chg,vol,amount"
        try:
            df = self.pro.daily(trade_date=trade_date, fields=fields)
        except Exception as exc:
            raise MarketReviewError(f"tushare daily({trade_date}) failed: {exc}") from exc
        required = {"ts_code", "trade_date", "close", "pre_close", "pct_chg", "vol", "amount"}
        if df is None or df.empty or not required.issubset(df.columns):
            raise MarketReviewError(f"tushare daily({trade_date}) returned incomplete data")
        for column in ["close", "pre_close", "pct_chg", "vol", "amount"]:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        if df[["ts_code", "pct_chg"]].isna().any().any():
            raise MarketReviewError(f"tushare daily({trade_date}) contains invalid values")
        dates = set(df["trade_date"].astype(str))
        if dates != {trade_date}:
            raise MarketReviewError(f"tushare daily returned unexpected dates: {sorted(dates)}")
        return {
            "trade_date": trade_date,
            "source": "tushare.daily",
            "rows": _records(df),
        }

    def fetch_adjustment_factor_snapshot(self, trade_date: str) -> dict[str, Any]:
        fields = "ts_code,trade_date,adj_factor"
        try:
            df = self.pro.adj_factor(trade_date=trade_date, fields=fields)
        except Exception as exc:
            raise MarketReviewError(f"tushare adj_factor({trade_date}) failed: {exc}") from exc
        required = {"ts_code", "trade_date", "adj_factor"}
        if df is None or df.empty or not required.issubset(df.columns):
            raise MarketReviewError(f"tushare adj_factor({trade_date}) returned incomplete data")
        df["adj_factor"] = pd.to_numeric(df["adj_factor"], errors="coerce")
        if df[["ts_code", "adj_factor"]].isna().any().any():
            raise MarketReviewError(f"tushare adj_factor({trade_date}) contains invalid values")
        dates = set(df["trade_date"].astype(str))
        if dates != {trade_date}:
            raise MarketReviewError(f"tushare adj_factor returned unexpected dates: {sorted(dates)}")
        return {
            "trade_date": trade_date,
            "source": "tushare.adj_factor",
            "rows": _records(df),
        }

    def fetch_index_weights(self, index_id: str, trade_date: str) -> dict[str, Any]:
        if index_id not in CORE_INDICES:
            raise MarketReviewError(f"unsupported core index: {index_id}")
        meta = CORE_INDICES[index_id]
        if meta["weight_source"] != "tushare":
            raise MarketReviewError(f"Tushare is not the configured weight source for {index_id}")
        start_date = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=120)).strftime("%Y%m%d")
        try:
            df = self.pro.index_weight(
                index_code=meta["weight_code"], start_date=start_date, end_date=trade_date
            )
        except Exception as exc:
            raise MarketReviewError(f"tushare index_weight({meta['weight_code']}) failed: {exc}") from exc
        required = {"con_code", "trade_date", "weight"}
        if df is None or df.empty or not required.issubset(df.columns):
            raise MarketReviewError(f"tushare index_weight({meta['weight_code']}) returned incomplete data")
        df = df.copy()
        df["trade_date"] = df["trade_date"].astype(str)
        df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
        if df["weight"].isna().any():
            raise MarketReviewError(f"tushare index_weight({meta['weight_code']}) contains invalid weights")
        effective_date = str(df["trade_date"].max())
        df = df[df["trade_date"] == effective_date]
        return {
            "index_id": index_id,
            "effective_date": effective_date,
            "source": "tushare.index_weight",
            "rows": [
                {
                    "code": str(row["con_code"]).split(".")[0].zfill(6),
                    "name": None,
                    "weight_pct": float(row["weight"]),
                }
                for _, row in df.iterrows()
            ],
        }
