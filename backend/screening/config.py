from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

from backend.screening.errors import ScreeningError


RULESET_VERSION = "ABC_V1.0"


@dataclass(frozen=True)
class ScreeningConfig:
    output_dir: Path = Path("data/screening/output")
    ruleset_version: str = RULESET_VERSION
    exclude_st: bool = True
    min_listing_days_stock: int = 120
    min_listing_days_etf: int = 120
    min_listing_days_a_stock: int = 250
    min_listing_days_a_etf: int = 250
    min_coverage_120d: float = 0.85
    min_amount_ma20_stock: float = 20_000_000.0
    min_amount_ma20_etf: float = 10_000_000.0
    threshold_a: float = 60.0
    threshold_a_pre: float = 55.0
    threshold_b: float = 60.0
    threshold_c: float = 60.0
    swing_window: int = 5
    a_min_downtrend_score: float = 18.0
    min_listing_days_a_pre_stock: int = 250
    min_listing_days_a_pre_etf: int = 250
    min_listing_days_b_stock: int = 180
    min_listing_days_b_etf: int = 180
    min_listing_days_c_stock: int = 120
    min_listing_days_c_etf: int = 120
    b_min_uptrend_score: float = 18.0
    b_min_pullback_score: float = 12.0
    b_pullback_pct_stock_min: float = -0.03
    b_pullback_pct_stock_max: float = -0.20
    b_pullback_pct_etf_min: float = -0.02
    b_pullback_pct_etf_max: float = -0.12
    b_pullback_atr_min: float = 1.5
    b_pullback_peak_min_age: int = 3
    b_pullback_days_max: int = 60
    b_break_swing_low_atr_tolerance: float = 1.0
    b_stage_b2_min_stabilize_hits: int = 2
    b_stage_b3_min_breakout_hits: int = 1
    c_min_downtrend_score: float = 16.0
    c_min_oversold_score: float = 12.0
    c_drawdown20_stock: float = -0.06
    c_drawdown60_stock: float = -0.12
    c_drawdown20_etf: float = -0.04
    c_drawdown60_etf: float = -0.08
    c_drawdown20_atr_min: float = 2.0
    c_rsi_oversold: float = 35.0
    c_rsi_deep_oversold: float = 30.0
    c_rsi_recover_level: float = 35.0
    c_ret10_weak: float = -0.05
    c_stage_c2_min_rebound_hits: int = 2
    c_exclude_if_break_prev_high60: bool = True
    c_exclude_if_ma20_above_ma60: bool = True
    c_exclude_if_higher_low_and_break_swing_high: bool = True


@dataclass(frozen=True)
class TushareConfig:
    token: str

    @classmethod
    def from_project_env(cls, project_root: Path) -> "TushareConfig":
        load_dotenv(project_root / ".env", override=False)
        token = os.getenv("TUSHARE_TOKEN", "").strip()
        if not token:
            raise ScreeningError("TUSHARE_TOKEN is required for candidate screening")
        return cls(token=token)


def screening_database_url_from_env(project_root: Path) -> str:
    load_dotenv(project_root / ".env", override=False)
    database_url = os.getenv("MARKET_REVIEW_DATABASE_URL", "").strip()
    if not database_url:
        raise ScreeningError("MARKET_REVIEW_DATABASE_URL is required for candidate screening PostgreSQL storage")
    return database_url
