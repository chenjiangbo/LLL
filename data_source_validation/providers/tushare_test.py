from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import tushare as ts


@dataclass
class TushareValidation:
    token: str

    @property
    def pro(self):
        return ts.pro_api(self.token)

    def stock_basic(self) -> pd.DataFrame:
        return self.pro.stock_basic(
            list_status="L",
            fields="ts_code,symbol,name,market,exchange,list_date,list_status",
        )

    def trade_cal(self) -> pd.DataFrame:
        start = (date.today() - timedelta(days=400)).strftime("%Y%m%d")
        end = date.today().strftime("%Y%m%d")
        return self.pro.trade_cal(exchange="SSE", start_date=start, end_date=end)

    def latest_completed_trade_date(self) -> str:
        cal = self.trade_cal()
        if cal is None or cal.empty:
            raise RuntimeError("trade_cal returned empty data")
        cal = cal.copy()
        cal["cal_date"] = cal["cal_date"].astype(str)
        today = date.today().strftime("%Y%m%d")
        completed = cal[(cal["is_open"] == 1) & (cal["cal_date"] < today)]
        if completed.empty:
            raise RuntimeError("cannot resolve latest completed trade date")
        return str(completed["cal_date"].max())

    def daily_for_codes(self, codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        frames = []
        for code in codes:
            frames.append(
                self.pro.daily(
                    ts_code=code,
                    start_date=start_date,
                    end_date=end_date,
                    fields="ts_code,trade_date,open,high,low,close,pre_close,vol,amount",
                )
            )
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def daily_by_trade_date(self, trade_date: str) -> pd.DataFrame:
        return self.pro.daily(
            trade_date=trade_date,
            fields="ts_code,trade_date,open,high,low,close,pre_close,vol,amount",
        )

    def adj_factor_for_codes(self, codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        frames = []
        for code in codes:
            frames.append(self.pro.adj_factor(ts_code=code, start_date=start_date, end_date=end_date))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def daily_basic(self, trade_date: str) -> pd.DataFrame:
        return self.pro.daily_basic(
            trade_date=trade_date,
            fields="ts_code,trade_date,turnover_rate,turnover_rate_f,total_mv,circ_mv,limit_status,close,volume_ratio",
        )

    def fund_basic(self) -> pd.DataFrame:
        return self.pro.fund_basic(market="E", status="L")

    def etf_basic(self) -> pd.DataFrame:
        return self.pro.etf_basic(list_status="L")

    def fund_daily_for_codes(self, codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        frames = []
        for code in codes:
            frames.append(self.pro.fund_daily(ts_code=code, start_date=start_date, end_date=end_date))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def fund_daily_by_trade_date(self, trade_date: str) -> pd.DataFrame:
        return self.pro.fund_daily(trade_date=trade_date)

    def pro_bar_etf(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        ts.set_token(self.token)
        return ts.pro_bar(
            ts_code=code,
            api=self.pro,
            asset="FD",
            adj="qfq",
            start_date=start_date,
            end_date=end_date,
        )

    def fund_adj(self, codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        frames = []
        for code in codes:
            frames.append(self.pro.fund_adj(ts_code=code, start_date=start_date, end_date=end_date))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def etf_mins(self, code: str, trade_date: str) -> pd.DataFrame:
        return self.pro.etf_mins(ts_code=code, freq="30min", trade_date=trade_date)

    def index_daily(self, codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        frames = []
        for code in codes:
            frames.append(self.pro.index_daily(ts_code=code, start_date=start_date, end_date=end_date))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def index_classify_sw(self) -> pd.DataFrame:
        return self.pro.index_classify(level="L1", src="SW2021")

    def index_member_all(self, **kwargs: Any) -> pd.DataFrame:
        return self.pro.index_member_all(**kwargs)

    def sw_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.pro.sw_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)


def three_year_start() -> str:
    return (datetime.today() - timedelta(days=365 * 3 + 20)).strftime("%Y%m%d")


def five_year_start() -> str:
    return (datetime.today() - timedelta(days=365 * 5 + 30)).strftime("%Y%m%d")
