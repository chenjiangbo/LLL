from __future__ import annotations

import pandas as pd
import akshare as ak


def stock_daily(symbol: str, start_date: str, end_date: str, adjust: str = "") -> pd.DataFrame:
    df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust=adjust)
    if df is None or df.empty:
        return pd.DataFrame()
    return df.rename(
        columns={
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "vol",
            "成交额": "amount",
        }
    )


def etf_spot() -> pd.DataFrame:
    return ak.fund_etf_spot_em()


def etf_daily(symbol: str, start_date: str, end_date: str, adjust: str = "") -> pd.DataFrame:
    df = ak.fund_etf_hist_em(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust=adjust)
    if df is None or df.empty:
        return pd.DataFrame()
    return df.rename(
        columns={
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "vol",
            "成交额": "amount",
        }
    )


def etf_30m(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    return ak.fund_etf_hist_min_em(
        symbol=symbol,
        period="30",
        start_date=start_date,
        end_date=end_date,
        adjust="",
    )
