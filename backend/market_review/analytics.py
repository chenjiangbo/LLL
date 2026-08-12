from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.market_review.config import (
    INDUSTRY_PERIODS,
    MA_WINDOWS,
    PERIODS,
    RISK_APPETITE_SCORE_THRESHOLD,
    STYLE_SPREAD_THRESHOLD_PCT,
)
from backend.market_review.errors import MarketReviewError


def _to_number(value: Any, default: float = 0) -> float:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return float(number)


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        raise MarketReviewError("cannot compute percentage change with zero denominator")
    return (current / previous - 1) * 100


def _safe_period_return(df: pd.DataFrame, close_col: str, days: int) -> float | None:
    if len(df) <= days:
        return None
    return _pct_change(float(df[close_col].iloc[-1]), float(df[close_col].iloc[-days - 1]))


def _moving_average_state(df: pd.DataFrame, close_col: str, window: int) -> dict[str, Any]:
    if len(df) < window + 5:
        return {"available": False, "reason": f"need at least {window + 5} rows"}
    ma = df[close_col].rolling(window).mean()
    latest_close = float(df[close_col].iloc[-1])
    latest_ma = float(ma.iloc[-1])
    prev_ma = float(ma.iloc[-5])
    distance_pct = _pct_change(latest_close, latest_ma)
    if abs(distance_pct) <= 1.5:
        position = "接近"
    elif distance_pct > 0:
        position = "高于"
    else:
        position = "低于"
    slope_pct = _pct_change(latest_ma, prev_ma)
    if abs(slope_pct) <= 0.3:
        slope = "走平"
    elif slope_pct > 0:
        slope = "向上"
    else:
        slope = "向下"
    return {
        "available": True,
        "value": latest_ma,
        "position": position,
        "distance_pct": distance_pct,
        "slope": slope,
        "slope_pct_5d": slope_pct,
    }


def _max_drawdown_from_high(df: pd.DataFrame, close_col: str, days: int) -> float | None:
    if len(df) < days:
        return None
    window = df.tail(days)
    high = float(window[close_col].max())
    latest = float(window[close_col].iloc[-1])
    return _pct_change(latest, high)


@dataclass
class OverviewAnalytics:
    def build(
        self,
        trade_date: str,
        core_indices: dict[str, Any],
        breadth: dict[str, Any],
        industry_summary: dict[str, Any],
        industry_histories: dict[str, Any],
        breadth_history: list[dict[str, Any]] | None = None,
        previous_report: dict[str, Any] | None = None,
        attribution_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        index_rows = self._build_index_rows(core_indices, attribution_data)
        industry_rows = self._build_industry_rows(industry_summary, industry_histories)
        breadth_block = self._build_breadth_block(
            index_rows, breadth, breadth_history or [], attribution_data
        )
        conclusion = self._build_conclusion(index_rows, breadth_block, industry_rows, previous_report)
        return {
            "trade_date": trade_date,
            "mode": "daily",
            "data_sources": {
                "indices": "ak.stock_zh_index_daily_tx",
                "breadth": "ak.stock_zh_a_spot",
                "limit_up": "ak.stock_zt_pool_em",
                "limit_down": "ak.stock_zt_pool_dtgc_em",
                "industry_summary": "ak.stock_board_industry_summary_ths",
                "industry_history": "ak.stock_board_industry_index_ths",
                "stock_daily": "tushare.daily",
                "stock_adjustment": "tushare.adj_factor",
                "technical_breadth": "tushare.daily + tushare.adj_factor",
                "index_weights": {
                    index_id: meta["source"]
                    for index_id, meta in (attribution_data or {}).get("weights", {}).items()
                },
            },
            "core_conclusion": conclusion,
            "indices": index_rows,
            "breadth": breadth_block,
            "industries": industry_rows,
            "market_classification": self._build_market_classification(index_rows, breadth_block),
        }

    def _build_market_classification(
        self, index_rows: list[dict[str, Any]], breadth: dict[str, Any]
    ) -> dict[str, Any]:
        by_id = {row["id"]: row for row in index_rows}
        returns_5w = {index_id: float(row["returns"]["5w"]) for index_id, row in by_id.items()}

        size_returns = {
            "大盘占优": returns_5w["hs300"],
            "中盘占优": returns_5w["csi500"],
            "小盘占优": returns_5w["csi1000"],
        }
        strongest_size = max(size_returns, key=size_returns.get)
        size_spread = max(size_returns.values()) - min(size_returns.values())
        size_style = strongest_size if size_spread >= STYLE_SPREAD_THRESHOLD_PCT else "大中小盘相对均衡"

        growth_return = (returns_5w["chinext"] + returns_5w["star50"]) / 2
        broad_return = (
            returns_5w["hs300"] + returns_5w["csi500"] + returns_5w["csi1000"]
        ) / 3
        growth_spread = growth_return - broad_return
        if growth_spread >= STYLE_SPREAD_THRESHOLD_PCT:
            growth_style = "成长科技占优"
        elif growth_spread <= -STYLE_SPREAD_THRESHOLD_PCT:
            growth_style = "成长科技承压"
        else:
            growth_style = "成长与宽基相对均衡"

        expansion_evidence = []
        contraction_evidence = []
        if returns_5w["csi1000"] > returns_5w["hs300"]:
            expansion_evidence.append("中证1000近5周跑赢沪深300")
        else:
            contraction_evidence.append("中证1000近5周跑输沪深300")
        if returns_5w["csi500"] > returns_5w["hs300"]:
            expansion_evidence.append("中证500近5周跑赢沪深300")
        else:
            contraction_evidence.append("中证500近5周跑输沪深300")
        if breadth["rising_ratio"] >= 0.55:
            expansion_evidence.append("当日上涨家数形成扩散")
        elif breadth["rising_ratio"] <= 0.45:
            contraction_evidence.append("当日下跌家数占优")
        if growth_spread > 0:
            expansion_evidence.append("成长科技近5周相对宽基更强")
        elif growth_spread < 0:
            contraction_evidence.append("成长科技近5周相对宽基更弱")

        if len(expansion_evidence) >= RISK_APPETITE_SCORE_THRESHOLD and len(expansion_evidence) > len(contraction_evidence):
            risk_appetite = "风险偏好扩张"
            risk_evidence = expansion_evidence
            conflicting_evidence = contraction_evidence
        elif len(contraction_evidence) >= RISK_APPETITE_SCORE_THRESHOLD and len(contraction_evidence) > len(expansion_evidence):
            risk_appetite = "风险偏好收缩"
            risk_evidence = contraction_evidence
            conflicting_evidence = expansion_evidence
        else:
            risk_appetite = "风险偏好信号混合"
            risk_evidence = expansion_evidence + contraction_evidence
            conflicting_evidence = []

        return {
            "daily_state": breadth["quadrant"],
            "size_style": size_style,
            "growth_style": growth_style,
            "risk_appetite": risk_appetite,
            "evidence": risk_evidence,
            "conflicting_evidence": conflicting_evidence,
            "period": "5w_with_1d_breadth",
        }

    def _build_index_rows(
        self,
        core_indices: dict[str, Any],
        attribution_data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index_id, payload in core_indices.items():
            df = pd.DataFrame(payload["records"])
            if df.empty:
                raise MarketReviewError(f"index {index_id} has no records")
            df = df.sort_values("date")
            for column in ["open", "close", "high", "low", "amount"]:
                df[column] = pd.to_numeric(df[column], errors="coerce")
            latest = df.iloc[-1]
            returns = {
                key: _safe_period_return(df, "close", days)
                for key, days in PERIODS.items()
            }
            ma_states = {
                key: _moving_average_state(df, "close", window)
                for key, window in MA_WINDOWS.items()
            }
            amount_ma_20w = df["amount"].rolling(PERIODS["20w"]).mean().iloc[-1] if len(df) >= PERIODS["20w"] else None
            amount_vs_20w = None
            if amount_ma_20w and not pd.isna(amount_ma_20w):
                amount_vs_20w = _pct_change(float(latest["amount"]), float(amount_ma_20w))
            rows.append(
                {
                    "id": index_id,
                    "name": payload["name"],
                    "symbol": payload["symbol"],
                    "quote_url": payload["quote_url"],
                    "date": str(latest["date"]),
                    "close": float(latest["close"]),
                    "returns": returns,
                    "drawdowns": {
                        "20w": _max_drawdown_from_high(df, "close", PERIODS["20w"]),
                        "60w": _max_drawdown_from_high(df, "close", PERIODS["60w"]),
                    },
                    "moving_averages": ma_states,
                    "amount": float(latest["amount"]),
                    "amount_vs_20w_avg_pct": amount_vs_20w,
                    "internal_breadth": self._build_internal_breadth(index_id, attribution_data),
                    "attribution": self._build_attribution(
                        index_id, returns["1d"], attribution_data
                    ),
                }
            )

        for period in ["1d", "1w", "5w", "20w", "60w"]:
            available = [row for row in rows if row["returns"][period] is not None]
            ranked = sorted(available, key=lambda row: row["returns"][period], reverse=True)
            for rank, row in enumerate(ranked, start=1):
                row.setdefault("rankings", {})[period] = rank
        return rows

    def _constituent_rows(
        self,
        index_id: str,
        attribution_data: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not attribution_data:
            return [], {}
        weights = attribution_data.get("weights", {}).get(index_id)
        daily_rows = attribution_data.get("stock_daily", {}).get("rows", [])
        if not weights or not daily_rows:
            return [], weights or {}
        daily_by_code = {
            str(row["ts_code"]).split(".")[0].zfill(6): row
            for row in daily_rows
            if row.get("ts_code")
        }
        rows = []
        for weight_row in weights.get("rows", []):
            code = str(weight_row["code"]).zfill(6)
            daily = daily_by_code.get(code)
            if daily is None:
                continue
            pct_chg = float(daily["pct_chg"])
            weight_pct = float(weight_row["weight_pct"])
            rows.append(
                {
                    "code": code,
                    "name": weight_row.get("name"),
                    "weight_pct": weight_pct,
                    "return_pct": pct_chg,
                    "contribution_pct_points": weight_pct * pct_chg / 100,
                }
            )
        return rows, weights

    def _build_internal_breadth(
        self,
        index_id: str,
        attribution_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        rows, _ = self._constituent_rows(index_id, attribution_data)
        if not rows:
            return {
                "up_ratio": None,
                "median_return": None,
                "equal_weight_return": None,
                "above_ma20d_ratio": None,
                "above_ma60d_ratio": None,
            }
        returns = pd.Series([row["return_pct"] for row in rows], dtype=float)
        return {
            "up_ratio": float((returns > 0).mean()),
            "median_return": float(returns.median()),
            "equal_weight_return": float(returns.mean()),
            "above_ma20d_ratio": None,
            "above_ma60d_ratio": None,
        }

    def _build_attribution(
        self,
        index_id: str,
        actual_return: float | None,
        attribution_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        rows, weights = self._constituent_rows(index_id, attribution_data)
        if not rows:
            return {
                "available": False,
                "reason": "缺少成分权重或成分股当日行情",
                "method": "weight_pct × stock_return_pct / 100",
                "top_positive_contributors": [],
                "top_negative_contributors": [],
                "industry_contributions": [],
                "industry_attribution_reason": "尚无可靠的同花顺行业成分映射",
                "concentration": None,
                "direction": None,
                "key_constituents": [],
            }
        industry_by_code = {
            str(row["code"]).zfill(6): str(row["industry"])
            for row in (attribution_data or {}).get("industry_map", {}).get("rows", [])
        }
        name_by_code = {
            str(row["code"]).zfill(6): str(row["name"])
            for row in (attribution_data or {}).get("industry_map", {}).get("rows", [])
            if row.get("name")
        }
        direction = "up" if actual_return is not None and actual_return >= 0 else "down"
        movers = sorted(rows, key=lambda row: row["return_pct"], reverse=direction == "up")[:5]
        missing_industries = [row["code"] for row in movers if row["code"] not in industry_by_code]
        if missing_industries:
            raise MarketReviewError(
                f"missing THS industries for selected {index_id} constituents: {missing_industries}"
            )
        key_constituents = [
            {
                "code": row["code"],
                "name": row["name"] or name_by_code.get(row["code"]),
                "return_pct": row["return_pct"],
                "industry": industry_by_code[row["code"]],
            }
            for row in movers
        ]
        positive = sorted(rows, key=lambda row: row["contribution_pct_points"], reverse=True)
        negative = sorted(rows, key=lambda row: row["contribution_pct_points"])
        covered_weight = sum(row["weight_pct"] for row in rows)
        estimated_return = sum(row["contribution_pct_points"] for row in rows)
        top_weights = sorted((row["weight_pct"] for row in rows), reverse=True)
        return {
            "available": True,
            "reason": None,
            "method": "成分股贡献近似值 = 权重(%) × 当日涨跌幅(%) / 100",
            "weight_effective_date": weights.get("effective_date"),
            "weight_source": weights.get("source"),
            "stock_return_source": "tushare.daily",
            "constituent_count": len(weights.get("rows", [])),
            "covered_constituent_count": len(rows),
            "covered_weight_pct": covered_weight,
            "estimated_return_pct": estimated_return,
            "actual_return_pct": actual_return,
            "tracking_difference_pct_points": (
                estimated_return - actual_return if actual_return is not None else None
            ),
            "top_positive_contributors": positive[:5],
            "top_negative_contributors": negative[:5],
            "industry_contributions": [],
            "industry_attribution_reason": "尚无可靠的同花顺行业成分映射",
            "concentration": {
                "top5_weight_pct": sum(top_weights[:5]),
                "top10_weight_pct": sum(top_weights[:10]),
                "positive_count": sum(row["return_pct"] > 0 for row in rows),
                "negative_count": sum(row["return_pct"] < 0 for row in rows),
                "flat_count": sum(row["return_pct"] == 0 for row in rows),
            },
            "direction": direction,
            "key_constituents": key_constituents,
        }

    def _build_breadth_block(
        self,
        index_rows: list[dict[str, Any]],
        breadth: dict[str, Any],
        breadth_history: list[dict[str, Any]],
        attribution_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        index_returns = [row["returns"]["1d"] for row in index_rows if row["returns"]["1d"] is not None]
        if not index_returns:
            raise MarketReviewError("cannot build breadth block without index daily returns")
        composite_return = sum(index_returns) / len(index_returns)
        rising_ratio = float(breadth["rising_ratio"])
        if composite_return >= 0 and rising_ratio >= 0.5:
            quadrant = "广泛上涨"
        elif composite_return >= 0 and rising_ratio < 0.5:
            quadrant = "权重主导"
        elif composite_return < 0 and rising_ratio >= 0.5:
            quadrant = "中小盘活跃或权重拖累"
        else:
            quadrant = "广泛风险释放"
        historical_payloads = self._build_market_daily_breadth_history(attribution_data)
        amount_values = [float(item["total_amount"]) for item in historical_payloads if item.get("total_amount") is not None]
        ratio_values = [float(item["rising_ratio"]) for item in historical_payloads if item.get("rising_ratio") is not None]
        previous_amount = amount_values[-2] if len(amount_values) >= 2 else None
        current_amount = amount_values[-1]
        amount_change = _pct_change(current_amount, previous_amount) if previous_amount else None
        avg_5d_amount = sum(amount_values[-5:]) / 5 if len(amount_values) >= 5 else None
        avg_20d_amount = sum(amount_values[-20:]) / 20 if len(amount_values) >= 20 else None
        amount_vs_20d = _pct_change(current_amount, avg_20d_amount) if avg_20d_amount else None
        one_year_percentile = None
        if len(amount_values) >= 252:
            one_year_percentile = sum(value <= current_amount for value in amount_values[-252:]) / len(amount_values[-252:])
        return {
            **{key: breadth[key] for key in [
                "trade_date",
                "snapshot_time",
                "stock_count",
                "rising_count",
                "falling_count",
                "flat_count",
                "rising_ratio",
                "falling_ratio",
                "total_amount",
                "limit_up_count",
                "limit_down_count",
                "limit_down_empty_with_no_columns",
            ]},
            "five_index_equal_weight_daily_return": composite_return,
            "quadrant": quadrant,
            "technical": self._build_market_technical_breadth(attribution_data),
            "history": {
                "avg_rising_ratio_5d": sum(ratio_values[-5:]) / 5 if len(ratio_values) >= 5 else None,
                "avg_rising_ratio_20d": sum(ratio_values[-20:]) / 20 if len(ratio_values) >= 20 else None,
                "turnover_change_vs_previous_pct": amount_change,
                "turnover_avg_5d": avg_5d_amount,
                "turnover_avg_20d": avg_20d_amount,
                "turnover_vs_20d_pct": amount_vs_20d,
                "turnover_one_year_percentile": one_year_percentile,
                "available_days": len(historical_payloads),
            },
        }

    def _build_market_daily_breadth_history(
        self, attribution_data: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        history = (attribution_data or {}).get("stock_history", [])
        if len(history) != 60:
            raise MarketReviewError("daily breadth history requires exactly 60 trading days")
        result = []
        for payload in history:
            rows = payload["daily"]["rows"]
            returns = [float(row["pct_chg"]) for row in rows if row.get("pct_chg") is not None]
            if not returns:
                raise MarketReviewError(
                    f"stock daily breadth has no returns for {payload['trade_date']}"
                )
            rising = sum(value > 0 for value in returns)
            falling = sum(value < 0 for value in returns)
            flat = len(returns) - rising - falling
            total_amount = sum(
                float(row["amount"]) * 1000
                for row in rows
                if row.get("amount") is not None
            )
            result.append(
                {
                    "trade_date": payload["trade_date"],
                    "rising_count": rising,
                    "falling_count": falling,
                    "flat_count": flat,
                    "rising_ratio": rising / len(returns),
                    "total_amount": total_amount,
                }
            )
        return result

    def _build_market_technical_breadth(
        self, attribution_data: dict[str, Any] | None
    ) -> dict[str, Any]:
        history = (attribution_data or {}).get("stock_history", [])
        if len(history) != 60:
            raise MarketReviewError("market technical breadth requires exactly 60 trading days")

        series_by_code: dict[str, list[float]] = {}
        current_codes: set[str] = set()
        for day_index, payload in enumerate(history):
            factors = {
                str(row["ts_code"]): float(row["adj_factor"])
                for row in payload["adjustment"]["rows"]
            }
            day_values = {
                str(row["ts_code"]): float(row["close"]) * factors[str(row["ts_code"])]
                for row in payload["daily"]["rows"]
                if row.get("ts_code") in factors and row.get("close") is not None
            }
            if day_index == len(history) - 1:
                current_codes = set(day_values)
            all_codes = set(series_by_code).union(day_values)
            for code in all_codes:
                values = series_by_code.setdefault(code, [])
                if code in day_values:
                    values.append(day_values[code])
                elif values:
                    values.append(values[-1])

        eligible_20 = [series_by_code[code] for code in current_codes if len(series_by_code.get(code, [])) >= 20]
        eligible_60 = [series_by_code[code] for code in current_codes if len(series_by_code.get(code, [])) >= 60]
        if not eligible_20 or not eligible_60:
            raise MarketReviewError("market technical breadth has no eligible 20d/60d stocks")
        above_ma20_count = sum(values[-1] > sum(values[-20:]) / 20 for values in eligible_20)
        above_ma60_count = sum(values[-1] > sum(values[-60:]) / 60 for values in eligible_60)
        new_high_20_count = sum(values[-1] >= max(values[-20:]) for values in eligible_20)
        new_low_20_count = sum(values[-1] <= min(values[-20:]) for values in eligible_20)
        return {
            "above_ma20_count": above_ma20_count,
            "above_ma20_ratio": above_ma20_count / len(eligible_20),
            "above_ma20_eligible_count": len(eligible_20),
            "above_ma60_count": above_ma60_count,
            "above_ma60_ratio": above_ma60_count / len(eligible_60),
            "above_ma60_eligible_count": len(eligible_60),
            "new_high_20_count": new_high_20_count,
            "new_high_20_ratio": new_high_20_count / len(eligible_20),
            "new_low_20_count": new_low_20_count,
            "new_low_20_ratio": new_low_20_count / len(eligible_20),
            "new_high_low_eligible_count": len(eligible_20),
            "price_adjustment": "tushare.adj_factor",
        }

    def _build_industry_rows(
        self,
        industry_summary: dict[str, Any],
        industry_histories: dict[str, Any],
    ) -> list[dict[str, Any]]:
        summary_by_name = {str(row["板块"]): row for row in industry_summary["rows"]}
        rows: list[dict[str, Any]] = []
        for name, payload in industry_histories.items():
            df = pd.DataFrame(payload["records"]).sort_values("日期")
            if df.empty:
                raise MarketReviewError(f"industry {name} has no history")
            df["收盘价"] = pd.to_numeric(df["收盘价"], errors="coerce")
            df["成交额"] = pd.to_numeric(df["成交额"], errors="coerce")
            summary = summary_by_name.get(name, {})
            up_count = int(_to_number(summary.get("上涨家数")))
            down_count = int(_to_number(summary.get("下跌家数")))
            breadth = up_count / max(up_count + down_count, 1)
            returns = {
                key: _safe_period_return(df, "收盘价", days)
                for key, days in INDUSTRY_PERIODS.items()
            }
            rows.append(
                {
                    "name": name,
                    "date": str(df["日期"].iloc[-1]),
                    "close": float(df["收盘价"].iloc[-1]),
                    "returns": returns,
                    "drawdown_60d": _max_drawdown_from_high(df, "收盘价", INDUSTRY_PERIODS["60d"]),
                    "up_count": up_count,
                    "down_count": down_count,
                    "internal_breadth": breadth,
                    "amount": float(df["成交额"].iloc[-1]),
                    "summary_change_pct": _to_number(summary.get("涨跌幅")),
                }
            )
        for period in ["5d", "20d", "60d"]:
            available = [row for row in rows if row["returns"][period] is not None]
            ranked = sorted(available, key=lambda row: row["returns"][period], reverse=True)
            for rank, row in enumerate(ranked, start=1):
                row.setdefault("rankings", {})[period] = rank
        return rows

    def _build_conclusion(
        self,
        index_rows: list[dict[str, Any]],
        breadth: dict[str, Any],
        industry_rows: list[dict[str, Any]],
        previous_report: dict[str, Any] | None,
    ) -> dict[str, Any]:
        daily = [row for row in index_rows if row["returns"]["1d"] is not None]
        one_week = [row for row in index_rows if row["returns"]["1w"] is not None]
        strongest_daily = max(daily, key=lambda row: row["returns"]["1d"])
        weakest_daily = min(daily, key=lambda row: row["returns"]["1d"])
        strongest_week = max(one_week, key=lambda row: row["returns"]["1w"])
        weakest_week = min(one_week, key=lambda row: row["returns"]["1w"])
        daily_direction = self._direction_label(daily, "1d")

        small = next(row for row in index_rows if row["id"] == "csi1000")
        large = next(row for row in index_rows if row["id"] == "hs300")
        small_ret = small["returns"]["5w"]
        large_ret = large["returns"]["5w"]
        if small_ret is not None and large_ret is not None and small_ret < large_ret:
            medium_style = "近5周大盘相对占优，中小盘仍承压"
        elif small_ret is not None and large_ret is not None and small_ret > large_ret:
            medium_style = "近5周小盘相对占优，风险偏好有所扩张"
        else:
            medium_style = "近5周大盘与小盘差异不清晰"

        top_gainers = sorted(
            industry_rows, key=lambda row: row["summary_change_pct"], reverse=True
        )[:10]
        top_decliners = sorted(
            industry_rows, key=lambda row: row["summary_change_pct"]
        )[:10]

        above_long_ma = sum(
            1 for row in index_rows if row["moving_averages"]["60w"].get("position") == "高于"
        )
        headline = (
            f"当日{daily_direction}，{strongest_daily['name']}最强、{weakest_daily['name']}最弱；"
            f"近1周{strongest_week['name']}领先，短期表现与中期结构需分开观察。"
        )
        timeframes = {
            "daily": (
                f"当日五指数等权平均收益为{breadth['five_index_equal_weight_daily_return']:.2f}%，"
                f"上涨家数占比{breadth['rising_ratio']:.1%}，盘面属于“{breadth['quadrant']}”。"
            ),
            "short_term": (
                f"近1周{strongest_week['name']}收益最高，{weakest_week['name']}收益最低；"
                "该结果描述短期变化，不代表中期趋势已经反转。"
            ),
            "medium_term": (
                f"{medium_style}。近20周收益、回撤和20/30周均线共同作为中期判断依据。"
            ),
            "long_term": (
                f"五个指数中有{above_long_ma}个位于60周均线上方；60周收益和均线只作为长期背景。"
            ),
        }

        conflicts = []
        if strongest_week["id"] == "csi1000" and medium_style.startswith("近5周大盘"):
            conflicts.append("中证1000近1周领先，但近5周仍弱于沪深300，短期修复与中期弱势并存。")
        if breadth["rising_ratio"] >= 0.6 and breadth["five_index_equal_weight_daily_return"] < 0:
            conflicts.append("当日多数股票上涨，但五指数等权平均下跌，市场广度与核心指数方向存在背离。")

        limit_down_text = (
            "跌停数据缺失"
            if breadth.get("limit_down_count") is None
            else f"跌停{breadth['limit_down_count']}家"
        )
        evidence = [
            f"当日{strongest_daily['name']}收益排名第一，{weakest_daily['name']}排名最后。",
            f"上涨家数占比为{breadth['rising_ratio']:.1%}，涨停{breadth['limit_up_count']}家，{limit_down_text}。",
            f"行业口径为同花顺行业板块，领涨行业为{top_gainers[0]['name']}，领跌行业为{top_decliners[0]['name']}。",
        ]
        evidence_refs = [
            {"path": "breadth.rising_ratio", "label": "当日上涨比例", "value": breadth["rising_ratio"], "period": "1d"},
            {"path": "breadth.five_index_equal_weight_daily_return", "label": "五指数等权平均", "value": breadth["five_index_equal_weight_daily_return"], "period": "1d"},
            {"path": f"indices.{strongest_week['id']}.returns.1w", "label": f"{strongest_week['name']}近1周收益", "value": strongest_week["returns"]["1w"], "period": "1w"},
            {"path": "indices.csi1000.returns.5w", "label": "中证1000近5周收益", "value": small_ret, "period": "5w"},
            {"path": "indices.hs300.returns.5w", "label": "沪深300近5周收益", "value": large_ret, "period": "5w"},
        ]

        risks = []
        if breadth.get("limit_down_count") is None:
            risks.append("跌停池接口返回空表且无字段，跌停家数为缺失值，不能按0解释。")
        if not risks:
            risks.append("规则结论仍需结合后续数据验证。")
        return {
            "summary": headline,
            "headline": headline,
            "timeframes": timeframes,
            "evidence": evidence,
            "evidence_refs": evidence_refs,
            "conflicts": conflicts,
            "risks": risks,
            "changes_from_previous_review": self._changes_from_previous(index_rows, industry_rows, previous_report),
            "industry_groups": {
                "top_gainers": [row["name"] for row in top_gainers],
                "top_decliners": [row["name"] for row in top_decliners],
            },
        }

    def _direction_label(self, rows: list[dict[str, Any]], period: str) -> str:
        positives = sum(1 for row in rows if row["returns"][period] >= 0)
        negatives = len(rows) - positives
        if positives >= 4:
            return "多数上涨"
        if negatives >= 4:
            return "多数下跌"
        return "表现分化"

    def _changes_from_previous(
        self,
        index_rows: list[dict[str, Any]],
        industry_rows: list[dict[str, Any]],
        previous_report: dict[str, Any] | None,
    ) -> list[str]:
        if not previous_report:
            return ["缺少上一期复盘，暂无法比较变化。"]
        previous_indices = {row["id"]: row for row in previous_report.get("indices", [])}
        changes: list[str] = []
        for row in index_rows:
            previous = previous_indices.get(row["id"])
            if not previous:
                continue
            old_rank = previous.get("rankings", {}).get("1w")
            new_rank = row.get("rankings", {}).get("1w")
            if old_rank and new_rank and old_rank != new_rank:
                direction = "上升" if new_rank < old_rank else "下降"
                changes.append(f"{row['name']}近1周排名由第{old_rank}变为第{new_rank}，排名{direction}。")
        return changes or ["与上一期相比，核心指数排名没有显著变化。"]
