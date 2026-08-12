from __future__ import annotations

import os
import re
import pandas as pd

# 强制清空代理影响
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["http_proxy"] = ""
os.environ["https_proxy"] = ""

import requests
_orig_request = requests.Session.request
def _no_proxy_request(self, method, url, **kwargs):
    kwargs["proxies"] = {"http": None, "https": None}
    if "timeout" not in kwargs:
        kwargs["timeout"] = 6
    return _orig_request(self, method, url, **kwargs)
requests.Session.request = _no_proxy_request

import akshare as ak
from backend.screening.errors import ScreeningError


def ts_code_to_ak_symbol(ts_code: str) -> tuple[str, str]:
    parts = ts_code.split(".")
    if len(parts) == 2:
        code, exchange = parts[0], parts[1].lower()
        return code, f"{exchange}{code}"
    return ts_code, ts_code.lower()


class AkshareScreeningSource:
    def min_bar(
        self,
        asset_code: str,
        asset_type: str = "stock",
        start_date: str = "",
        end_date: str = "",
        freq: str = "30min",
    ) -> pd.DataFrame:
        code, symbol = ts_code_to_ak_symbol(asset_code)
        df = None

        # 1. 优先尝试 stock_zh_a_minute
        try:
            df = ak.stock_zh_a_minute(symbol=symbol, period="30")
            if df is not None and not df.empty:
                df = df.rename(columns={"day": "trade_time", "volume": "vol"})
        except Exception:
            df = None

        # 2. 备用尝试 stock_zh_a_hist_min_em / fund_etf_hist_min_em
        if df is None or df.empty:
            try:
                if asset_type == "etf":
                    df = ak.fund_etf_hist_min_em(symbol=code, period="30")
                else:
                    df = ak.stock_zh_a_hist_min_em(symbol=code, period="30")
                if df is not None and not df.empty:
                    df = df.rename(
                        columns={
                            "时间": "trade_time",
                            "开盘": "open",
                            "最高": "high",
                            "最低": "low",
                            "收盘": "close",
                            "成交量": "vol",
                            "成交额": "amount",
                        }
                    )
            except Exception:
                df = None

        if df is None or df.empty:
            return pd.DataFrame()

        df["open"] = pd.to_numeric(df["open"], errors="coerce")
        df["high"] = pd.to_numeric(df["high"], errors="coerce")
        df["low"] = pd.to_numeric(df["low"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["vol"] = pd.to_numeric(df["vol"], errors="coerce")

        if "amount" not in df.columns or df["amount"].isna().all():
            df["amount"] = df["close"] * df["vol"]
        else:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

        df["asset_code"] = asset_code
        df["asset_type"] = asset_type

        if start_date:
            s_formatted = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            df = df[df["trade_time"] >= s_formatted]
        if end_date:
            e_formatted = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]} 23:59:59"
            df = df[df["trade_time"] <= e_formatted]

        return df[["asset_code", "asset_type", "trade_time", "open", "high", "low", "close", "vol", "amount"]]
