from __future__ import annotations

from typing import Any

from backend.screening.secondary_eval_engine import evaluate_company_evidence
from backend.screening.storage import PostgresScreeningStore


LATEST_FINANCIAL_DATE = "99991231"


class MarketFinancialSummaryService:
    """Generate reusable latest financial summaries from already-stored PIT facts."""

    def __init__(self, store: PostgresScreeningStore):
        self.store = store

    def build(self, ts_codes: list[str], progress_callback=None) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        ready = missing = 0
        for index, code in enumerate(ts_codes, start=1):
            if self.store.has_financial_data_for_stock(code, LATEST_FINANCIAL_DATE):
                fact = evaluate_company_evidence(self.store, code, LATEST_FINANCIAL_DATE)
                rows.append({
                    "ts_code": code,
                    "latest_report_period": fact.get("latest_report_period"),
                    "revenue": fact.get("revenue"),
                    "revenue_yoy": fact.get("revenue_yoy"),
                    "parent_net_profit": fact.get("parent_net_profit"),
                    "parent_net_profit_yoy": fact.get("parent_net_profit_yoy"),
                    "operating_cashflow": fact.get("operating_cashflow"),
                    "operating_cashflow_yoy": fact.get("operating_cashflow_yoy"),
                    "forecast_type": fact.get("forecast_type"),
                    "fact_tags": fact.get("fact_tags_json") or [],
                    "data_status": "READY",
                })
                ready += 1
            else:
                rows.append({"ts_code": code, "fact_tags": [], "data_status": "MISSING_FINANCIAL"})
                missing += 1
            if len(rows) >= 200:
                self.store.save_market_financial_summaries(rows)
                rows = []
            if progress_callback:
                progress_callback(index, len(ts_codes), code)
        self.store.save_market_financial_summaries(rows)
        return {"total": len(ts_codes), "ready": ready, "missing_financial": missing}

