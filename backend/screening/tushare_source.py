from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import tushare as ts

from backend.screening.errors import ScreeningError


def _require_frame(df: pd.DataFrame | None, api_name: str, required: set[str]) -> pd.DataFrame:
    if df is None or df.empty:
        raise ScreeningError(f"tushare {api_name} returned empty data")
    missing = required.difference(df.columns)
    if missing:
        raise ScreeningError(f"tushare {api_name} missing columns: {sorted(missing)}")
    return df.copy()


def _to_number(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


@dataclass
class TushareScreeningSource:
    token: str

    @property
    def pro(self):
        return ts.pro_api(self.token)

    def trade_dates(self, start_date: str, end_date: str) -> list[str]:
        df = self.pro.trade_cal(exchange="", start_date=start_date, end_date=end_date, is_open="1")
        df = _require_frame(df, "trade_cal", {"cal_date", "is_open"})
        return sorted(df["cal_date"].astype(str).tolist())

    def stock_company(self) -> pd.DataFrame:
        fields = "ts_code,province,city,main_business,act_ent_type"
        df = self.pro.stock_company(fields=fields)
        return _require_frame(df, "stock_company", {"ts_code"})

    def stock_basic(self) -> pd.DataFrame:
        fields = "ts_code,symbol,name,area,industry,market,list_date"
        df = self.pro.stock_basic(exchange="", list_status="L", fields=fields)
        df = _require_frame(df, "stock_basic", {"ts_code", "name", "list_date"})
        comp_df = self.stock_company()
        if not comp_df.empty and "ts_code" in comp_df.columns:
            df = df.merge(comp_df, on="ts_code", how="left")

        ent_types = []
        for val in (df["act_ent_type"] if "act_ent_type" in df.columns else []):
            if not val or pd.isna(val):
                ent_types.append(None)
            elif "民营" in str(val):
                ent_types.append("民企")
            elif "国" in str(val):
                ent_types.append("国企")
            elif "外资" in str(val):
                ent_types.append("外资")
            elif "公众" in str(val):
                ent_types.append("公众公司")
            else:
                ent_types.append(str(val))

        return pd.DataFrame(
            {
                "asset_code": df["ts_code"].astype(str),
                "asset_type": "stock",
                "name": df["name"].astype(str),
                "list_date": df["list_date"].astype(str),
                "market": df.get("market"),
                "industry": df.get("industry"),
                "province": df.get("province") if "province" in df.columns else None,
                "city": df.get("city") if "city" in df.columns else None,
                "ent_type": ent_types if ent_types else None,
                "main_business": df.get("main_business") if "main_business" in df.columns else None,
            }
        )

    def fund_basic(self) -> pd.DataFrame:
        fields = "ts_code,name,management,custodian,fund_type,found_date,due_date,list_date,issue_date,delist_date,market"
        df = self.pro.fund_basic(market="E", status="L", fields=fields)
        df = _require_frame(df, "fund_basic", {"ts_code", "name"})
        list_date = df["list_date"] if "list_date" in df.columns else df.get("found_date")
        return pd.DataFrame(
            {
                "asset_code": df["ts_code"].astype(str),
                "asset_type": "etf",
                "name": df["name"].astype(str),
                "list_date": list_date.astype(str).where(pd.notna(list_date), None),
                "market": df.get("market"),
                "industry": "ETF",
                "fund_type": df.get("fund_type") if "fund_type" in df.columns else None,
                "management": df.get("management") if "management" in df.columns else None,
            }
        )

    def stock_daily(self, trade_date: str) -> pd.DataFrame:
        fields = "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount"
        df = self.pro.daily(trade_date=trade_date, fields=fields)
        df = _require_frame(df, "daily", {"ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"})
        df = _to_number(df, ["open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"])
        _assert_no_nan(df, ["open", "high", "low", "close", "vol", "amount"], "daily")
        return _daily_frame(df, "stock")

    def stock_weekly(self, trade_date: str) -> pd.DataFrame:
        fields = "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount"
        df = self.pro.weekly(trade_date=trade_date, fields=fields)
        df = _require_frame(df, "weekly", {"ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"})
        df = _to_number(df, ["open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"])
        _assert_no_nan(df, ["open", "high", "low", "close", "vol", "amount"], "weekly")
        if df.empty:
            raise ScreeningError(f"tushare weekly({trade_date}) returned empty data")
        return _daily_frame(df, "stock")

    def daily_basic(self, trade_date: str) -> pd.DataFrame:
        fields = (
            "ts_code,trade_date,total_share,float_share,free_share,total_mv,circ_mv,"
            "turnover_rate,turnover_rate_f,volume_ratio,pe_ttm,dv_ttm,limit_status"
        )
        df = self.pro.daily_basic(trade_date=trade_date, fields=fields)
        df = _require_frame(df, "daily_basic", {"ts_code", "trade_date"})
        df = _to_number(
            df,
            [
                "total_share",
                "float_share",
                "free_share",
                "turnover_rate",
                "turnover_rate_f",
                "volume_ratio",
                "pe_ttm",
                "dv_ttm",
                "total_mv",
                "circ_mv",
            ],
        )
        return pd.DataFrame(
            {
                "asset_code": df["ts_code"].astype(str),
                "trade_date": df["trade_date"].astype(str),
                "total_share": df.get("total_share"),
                "float_share": df.get("float_share"),
                "free_share": df.get("free_share"),
                "turnover_rate": df.get("turnover_rate"),
                "turnover_rate_f": df.get("turnover_rate_f"),
                "volume_ratio": df.get("volume_ratio"),
                "pe_ttm": df.get("pe_ttm"),
                "dv_ttm": df.get("dv_ttm"),
                "total_mv": df.get("total_mv"),
                "circ_mv": df.get("circ_mv"),
                "limit_status": df.get("limit_status"),
            }
        )

    def income_vip(self, ts_code: str) -> pd.DataFrame:
        fields = "ts_code,ann_date,f_ann_date,end_date,total_revenue,oper_cost,n_income_attr_p,update_flag"
        df = self.pro.income_vip(ts_code=ts_code, fields=fields)
        df = _require_frame(df, "income_vip", {"ts_code", "end_date"})
        df = _to_number(df, ["total_revenue", "oper_cost", "n_income_attr_p"])
        return df

    def cashflow_vip(self, ts_code: str) -> pd.DataFrame:
        fields = "ts_code,ann_date,f_ann_date,end_date,n_cashflow_act,update_flag"
        df = self.pro.cashflow_vip(ts_code=ts_code, fields=fields)
        df = _require_frame(df, "cashflow_vip", {"ts_code", "end_date"})
        df = _to_number(df, ["n_cashflow_act"])
        return df

    def fina_indicator_vip(self, ts_code: str) -> pd.DataFrame:
        fields = "ts_code,ann_date,end_date,profit_dedt,or_yoy,op_yoy,netprofit_yoy,dt_netprofit_yoy,grossprofit_margin"
        df = self.pro.fina_indicator_vip(ts_code=ts_code, fields=fields)
        df = _require_frame(df, "fina_indicator_vip", {"ts_code", "end_date"})
        df = _to_number(df, ["profit_dedt", "or_yoy", "op_yoy", "netprofit_yoy", "dt_netprofit_yoy", "grossprofit_margin"])
        return df

    def forecast_vip(self, ts_code: str) -> pd.DataFrame:
        fields = "ts_code,ann_date,end_date,type,p_change_min,p_change_max,net_profit_min,net_profit_max,summary,change_reason"
        df = self.pro.forecast_vip(ts_code=ts_code, fields=fields)
        if df is None or df.empty:
            return pd.DataFrame(columns=fields.split(","))
        df = _require_frame(df, "forecast_vip", {"ts_code", "ann_date"})
        df = _to_number(df, ["p_change_min", "p_change_max", "net_profit_min", "net_profit_max"])
        return df

    def express_vip(self, ts_code: str) -> pd.DataFrame:
        fields = (
            "ts_code,ann_date,end_date,revenue,operate_profit,total_profit,n_income,"
            "total_assets,total_hldr_eqy_exc_min_int,diluted_eps,diluted_roe,"
            "yoy_net_profit,bps,open_net_assets,open_bps,perf_summary,update_flag"
        )
        df = self.pro.express_vip(ts_code=ts_code, fields=fields)
        if df is None or df.empty:
            return pd.DataFrame(columns=fields.split(","))
        df = _require_frame(df, "express_vip", {"ts_code", "ann_date", "end_date"})
        df = df[df["ts_code"].astype(str) == ts_code].copy()
        if df.empty:
            return pd.DataFrame(columns=fields.split(","))
        df = _to_number(
            df,
            [
                "revenue",
                "operate_profit",
                "total_profit",
                "n_income",
                "total_assets",
                "total_hldr_eqy_exc_min_int",
                "diluted_eps",
                "diluted_roe",
                "yoy_net_profit",
                "bps",
                "open_net_assets",
                "open_bps",
            ],
        )
        return df

    def share_float(self, ts_code: str) -> pd.DataFrame:
        fields = "ts_code,ann_date,float_date,float_share,float_ratio,holder_name,share_type"
        df = self.pro.share_float(ts_code=ts_code, fields=fields)
        if df is None or df.empty:
            return pd.DataFrame(columns=fields.split(","))
        df = _require_frame(df, "share_float", {"ts_code", "float_date"})
        df = df[df["ts_code"].astype(str) == ts_code].copy()
        if df.empty:
            return pd.DataFrame(columns=fields.split(","))
        df = _to_number(df, ["float_share", "float_ratio"])
        return df

    def stk_holdertrade(self, ts_code: str) -> pd.DataFrame:
        fields = "ts_code,ann_date,holder_name,holder_type,in_de,change_vol,change_ratio,after_share,after_ratio,avg_price,total_share"
        df = self.pro.stk_holdertrade(ts_code=ts_code, fields=fields)
        if df is None or df.empty:
            return pd.DataFrame(columns=fields.split(","))
        df = _require_frame(df, "stk_holdertrade", {"ts_code", "ann_date"})
        df = df[df["ts_code"].astype(str) == ts_code].copy()
        if df.empty:
            return pd.DataFrame(columns=fields.split(","))
        df = _to_number(df, ["change_vol", "change_ratio", "after_share", "after_ratio", "avg_price", "total_share"])
        return df

    def stock_adj_factor(self, trade_date: str) -> pd.DataFrame:
        df = self.pro.adj_factor(trade_date=trade_date, fields="ts_code,trade_date,adj_factor")
        df = _require_frame(df, "adj_factor", {"ts_code", "trade_date", "adj_factor"})
        df = _to_number(df, ["adj_factor"])
        _assert_no_nan(df, ["adj_factor"], "adj_factor")
        return _adj_frame(df, "stock")

    def fund_daily(self, trade_date: str) -> pd.DataFrame:
        fields = "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount"
        df = self.pro.fund_daily(trade_date=trade_date, market="E", fields=fields)
        df = _require_frame(df, "fund_daily", {"ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"})
        df = _to_number(df, ["open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"])
        _assert_no_nan(df, ["open", "high", "low", "close", "vol", "amount"], "fund_daily")
        return _daily_frame(df, "etf")

    def fund_adj_factor(self, trade_date: str) -> pd.DataFrame:
        df = self.pro.fund_adj(ts_code="", trade_date=trade_date)
        df = _require_frame(df, "fund_adj", {"ts_code", "trade_date", "adj_factor"})
        df = _to_number(df, ["adj_factor"])
        _assert_no_nan(df, ["adj_factor"], "fund_adj")
        return _adj_frame(df, "etf")

    def min_bar(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        freq: str = "30min",
        asset_type: str = "stock",
    ) -> pd.DataFrame:
        if asset_type == "stock":
            df = self.pro.stk_mins(ts_code=ts_code, start_date=start_date, end_date=end_date, freq=freq)
        else:
            asset_param = "FD" if asset_type == "etf" else "E"
            df = ts.pro_bar(
                ts_code=ts_code,
                api=self.pro,
                start_date=start_date,
                end_date=end_date,
                freq=freq,
                asset=asset_param,
            )

        if df is None or df.empty:
            return pd.DataFrame()

        required = {"ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount"}
        missing = required.difference(df.columns)
        if missing:
            return pd.DataFrame()

        df = _to_number(df, ["open", "high", "low", "close", "vol", "amount"])
        return pd.DataFrame(
            {
                "asset_code": df["ts_code"].astype(str),
                "asset_type": asset_type,
                "trade_time": df["trade_time"].astype(str),
                "open": df["open"],
                "high": df["high"],
                "low": df["low"],
                "close": df["close"],
                "vol": df["vol"],
                "amount": df["amount"],
            }
        )


def _daily_frame(df: pd.DataFrame, asset_type: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "asset_code": df["ts_code"].astype(str),
            "asset_type": asset_type,
            "trade_date": df["trade_date"].astype(str),
            "open": df["open"],
            "high": df["high"],
            "low": df["low"],
            "close": df["close"],
            "pre_close": df.get("pre_close"),
            "pct_chg": df.get("pct_chg"),
            "vol": df["vol"],
            "amount": df["amount"] * 1000.0,
        }
    )


def _adj_frame(df: pd.DataFrame, asset_type: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "asset_code": df["ts_code"].astype(str),
            "asset_type": asset_type,
            "trade_date": df["trade_date"].astype(str),
            "adj_factor": df["adj_factor"],
        }
    )


def _assert_no_nan(df: pd.DataFrame, columns: list[str], api_name: str) -> None:
    invalid = df[columns].isna().any()
    if bool(invalid.any()):
        raise ScreeningError(f"tushare {api_name} contains invalid numeric fields: {invalid[invalid].index.tolist()}")
