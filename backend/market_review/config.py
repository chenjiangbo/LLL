from __future__ import annotations

from dataclasses import dataclass
import os
from datetime import time
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


CORE_INDICES = {
    "hs300": {"name": "沪深300", "ak_symbol": "sh000300", "weight_code": "000300", "weight_source": "akshare", "category": "large_cap", "quote_url": "https://quote.eastmoney.com/unify/r/1.000300"},
    "csi500": {"name": "中证500", "ak_symbol": "sh000905", "weight_code": "000905", "weight_source": "akshare", "category": "mid_cap", "quote_url": "https://quote.eastmoney.com/unify/r/1.000905"},
    "csi1000": {"name": "中证1000", "ak_symbol": "sh000852", "weight_code": "000852", "weight_source": "akshare", "category": "small_cap", "quote_url": "https://quote.eastmoney.com/unify/r/1.000852"},
    "chinext": {"name": "创业板指", "ak_symbol": "sz399006", "weight_code": "399006.SZ", "weight_source": "tushare", "category": "growth", "quote_url": "https://quote.eastmoney.com/unify/r/0.399006"},
    "star50": {"name": "科创50", "ak_symbol": "sh000688", "weight_code": "000688", "weight_source": "akshare", "category": "hard_tech", "quote_url": "https://quote.eastmoney.com/unify/r/1.000688"},
}

PERIODS = {
    "1d": 1,
    "1w": 5,
    "5w": 25,
    "20w": 100,
    "60w": 300,
}

MA_WINDOWS = {
    "20w": 100,
    "30w": 150,
    "60w": 300,
}

INDUSTRY_PERIODS = {
    "5d": 5,
    "20d": 20,
    "60d": 60,
}

MARKET_CLOSE_TIME = time(15, 0)
FINAL_DATA_TIME = time(16, 10)
STYLE_SPREAD_THRESHOLD_PCT = 1.0
RISK_APPETITE_SCORE_THRESHOLD = 2


@dataclass(frozen=True)
class PipelineConfig:
    database_url: str = ""
    report_dir: Path = Path("data/market_review/reports")
    default_history_start: str = "20250101"


@dataclass(frozen=True)
class QwenConfig:
    api_key: str
    base_url: str
    model: str

    @classmethod
    def from_env(cls) -> "QwenConfig":
        required = {
            "DASHSCOPE_API_KEY": os.getenv("DASHSCOPE_API_KEY", "").strip(),
            "AI_BASE_BASE_URL": os.getenv("AI_BASE_BASE_URL", "").strip(),
            "AI_BASE_MODEL": os.getenv("AI_BASE_MODEL", "").strip(),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"missing required DashScope environment variables: {missing}")
        return cls(
            api_key=required["DASHSCOPE_API_KEY"],
            base_url=required["AI_BASE_BASE_URL"],
            model=required["AI_BASE_MODEL"],
        )
