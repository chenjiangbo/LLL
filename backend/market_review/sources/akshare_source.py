from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd
import requests
from bs4 import BeautifulSoup

from backend.market_review.config import CORE_INDICES
from backend.market_review.errors import MarketReviewError


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return df.astype(object).where(pd.notna(df), None).to_dict(orient="records")


def _require_columns(df: pd.DataFrame, required: set[str], label: str) -> None:
    if df is None or df.empty:
        raise MarketReviewError(f"{label} returned empty data")
    missing = sorted(required.difference(set(map(str, df.columns))))
    if missing:
        raise MarketReviewError(f"{label} missing columns: {missing}; columns={list(df.columns)}")


@dataclass
class AkShareSource:
    """AkShare supplemental source for live snapshots and TuShare gaps."""

    def fetch_core_index_history(self, start_date: str, end_date: str) -> dict[str, Any]:
        return {
            index_id: self.fetch_index_history(index_id, start_date, end_date)
            for index_id in CORE_INDICES
        }

    def fetch_index_history(self, index_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        if index_id not in CORE_INDICES:
            raise MarketReviewError(f"unsupported core index: {index_id}")
        meta = CORE_INDICES[index_id]
        symbol = meta["ak_symbol"]
        df = ak.stock_zh_index_daily_tx(symbol=symbol)
        _require_columns(df, {"date", "open", "close", "high", "low", "amount"}, f"stock_zh_index_daily_tx({symbol})")
        date_key = df["date"].astype(str).str.replace("-", "", regex=False)
        df = df[(date_key >= start_date) & (date_key <= end_date)].copy()
        if df.empty:
            raise MarketReviewError(f"stock_zh_index_daily_tx({symbol}) has no rows in {start_date}-{end_date}")
        for column in ["open", "close", "high", "low", "amount"]:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        if df[["close", "amount"]].isna().any().any():
            raise MarketReviewError(f"stock_zh_index_daily_tx({symbol}) contains invalid close/amount values")
        return {
            "id": index_id,
            "name": meta["name"],
            "symbol": symbol,
            "quote_url": meta["quote_url"],
            "source": "ak.stock_zh_index_daily_tx",
            "records": _records(df),
        }

    def fetch_market_breadth_snapshot(self, trade_date: str) -> dict[str, Any]:
        captured_at = datetime.now(ZoneInfo("Asia/Shanghai"))
        spot_df = ak.stock_zh_a_spot()
        _require_columns(spot_df, {"代码", "名称", "涨跌幅", "成交额", "时间戳"}, "stock_zh_a_spot")
        pct = pd.to_numeric(spot_df["涨跌幅"], errors="coerce")
        amount = pd.to_numeric(spot_df["成交额"], errors="coerce")
        if pct.isna().any():
            raise MarketReviewError("stock_zh_a_spot contains invalid pct change values")

        limit_up_df = ak.stock_zt_pool_em(date=trade_date)
        _require_columns(limit_up_df, {"代码", "名称", "涨跌幅", "所属行业"}, f"stock_zt_pool_em({trade_date})")

        limit_down_df = ak.stock_zt_pool_dtgc_em(date=trade_date)
        if limit_down_df is None:
            raise MarketReviewError(f"stock_zt_pool_dtgc_em({trade_date}) returned None")
        _require_columns(
            limit_down_df,
            {"代码", "名称", "涨跌幅", "所属行业"},
            f"stock_zt_pool_dtgc_em({trade_date})",
        )

        rising = int((pct > 0).sum())
        falling = int((pct < 0).sum())
        flat = int((pct == 0).sum())
        valid_count = rising + falling + flat
        if valid_count == 0:
            raise MarketReviewError("stock_zh_a_spot has no valid stock rows")

        return {
            "trade_date": trade_date,
            "captured_at": captured_at.isoformat(),
            "capture_trade_date": captured_at.strftime("%Y%m%d"),
            "source": {
                "spot": "ak.stock_zh_a_spot",
                "limit_up": "ak.stock_zt_pool_em",
                "limit_down": "ak.stock_zt_pool_dtgc_em",
            },
            "snapshot_time": str(spot_df["时间戳"].dropna().iloc[-1]),
            "stock_count": int(len(spot_df)),
            "rising_count": rising,
            "falling_count": falling,
            "flat_count": flat,
            "rising_ratio": rising / valid_count,
            "falling_ratio": falling / valid_count,
            "total_amount": float(amount.sum(skipna=True)),
            "limit_up_count": int(len(limit_up_df)),
            "limit_down_count": int(len(limit_down_df)),
            "limit_down_empty_with_no_columns": False,
            "limit_up_rows": _records(limit_up_df),
            "limit_down_rows": _records(limit_down_df),
        }

    def fetch_industry_summary(self) -> dict[str, Any]:
        captured_at = datetime.now(ZoneInfo("Asia/Shanghai"))
        df = ak.stock_board_industry_summary_ths()
        _require_columns(df, {"板块", "涨跌幅", "总成交额", "上涨家数", "下跌家数"}, "stock_board_industry_summary_ths")
        return {
            "source": "ak.stock_board_industry_summary_ths",
            "captured_at": captured_at.isoformat(),
            "capture_trade_date": captured_at.strftime("%Y%m%d"),
            "rows": _records(df),
        }

    def fetch_industry_history(self, industry_name: str, start_date: str, end_date: str) -> dict[str, Any]:
        df = ak.stock_board_industry_index_ths(symbol=industry_name, start_date=start_date, end_date=end_date)
        _require_columns(df, {"日期", "开盘价", "最高价", "最低价", "收盘价", "成交额"}, f"stock_board_industry_index_ths({industry_name})")
        for column in ["开盘价", "最高价", "最低价", "收盘价", "成交额"]:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        if df[["收盘价", "成交额"]].isna().any().any():
            raise MarketReviewError(f"stock_board_industry_index_ths({industry_name}) contains invalid values")
        return {
            "name": industry_name,
            "source": "ak.stock_board_industry_index_ths",
            "records": _records(df),
        }

    def fetch_ths_industry_map(self, stock_codes: set[str]) -> dict[str, Any]:
        targets = {str(code).zfill(6) for code in stock_codes}
        if not targets:
            raise MarketReviewError("cannot fetch THS industries without stock codes")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36"
            ),
        }
        resolved: dict[str, str] = {}
        stock_names: dict[str, str] = {}
        for code in sorted(targets):
            url = f"https://basic.10jqka.com.cn/{code}/"
            try:
                response = requests.get(url, headers=headers, timeout=15)
                response.raise_for_status()
            except Exception as exc:
                raise MarketReviewError(f"failed to fetch THS profile for {code}: {exc}") from exc
            response.encoding = "gbk"
            soup = BeautifulSoup(response.text, features="lxml")
            label = soup.find(string=lambda text: text and "所属申万行业" in text)
            value = label.parent.find_next_sibling("span") if label and label.parent else None
            industry = value.get_text(strip=True) if value else ""
            if not industry:
                raise MarketReviewError(f"THS profile has no SW industry for {code}")
            title = soup.title.get_text(strip=True) if soup.title else ""
            marker = f"({code})"
            stock_name = title.split(marker, 1)[0].strip() if marker in title else ""
            if not stock_name:
                raise MarketReviewError(f"THS profile has no stock name for {code}")
            resolved[code] = industry
            stock_names[code] = stock_name

        missing = sorted(targets.difference(resolved))
        if missing:
            raise MarketReviewError(f"THS industry mapping missing for constituent stocks: {missing}")
        return {
            "source": "ths.stock_profile_sw_industry",
            "captured_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "rows": [
                {"code": code, "name": stock_names[code], "industry": resolved[code]}
                for code in sorted(resolved)
            ],
        }

    def fetch_index_weights(self, index_id: str, trade_date: str) -> dict[str, Any]:
        if index_id not in CORE_INDICES:
            raise MarketReviewError(f"unsupported core index: {index_id}")
        meta = CORE_INDICES[index_id]
        if meta["weight_source"] != "akshare":
            raise MarketReviewError(f"AkShare is not the configured weight source for {index_id}")
        symbol = meta["weight_code"]
        df = ak.index_stock_cons_weight_csindex(symbol=symbol)
        _require_columns(df, {"日期", "成分券代码", "成分券名称", "权重"}, f"index_stock_cons_weight_csindex({symbol})")
        df = df.copy()
        df["日期"] = df["日期"].astype(str).str.replace("-", "", regex=False)
        df["权重"] = pd.to_numeric(df["权重"], errors="coerce")
        if df["权重"].isna().any():
            raise MarketReviewError(f"index_stock_cons_weight_csindex({symbol}) contains invalid weights")
        eligible = df[df["日期"] <= trade_date]
        if eligible.empty:
            raise MarketReviewError(
                f"AkShare weight date for {index_id} is later than report date {trade_date}"
            )
        effective_date = str(eligible["日期"].max())
        eligible = eligible[eligible["日期"] == effective_date]
        rows = [
            {
                "code": str(row["成分券代码"]).zfill(6),
                "name": str(row["成分券名称"]),
                "weight_pct": float(row["权重"]),
            }
            for _, row in eligible.iterrows()
        ]
        return {
            "index_id": index_id,
            "effective_date": effective_date,
            "source": "ak.index_stock_cons_weight_csindex",
            "rows": rows,
        }
