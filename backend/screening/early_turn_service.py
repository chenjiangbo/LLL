"""
A-Pre V2 EarlyTurnService

基于 screening_daily_bar 的 90 日 K 线数据实时计算 8 大量化特征组与打分模型。
1. run(trade_date, ts_code=None): 支持全市场选股评估或单股定向测试。
2. validate_positive_samples(): 运行正样本（京投发展、浙江医药、百花医药等）基于 K 线的全量回归测试。
"""

from typing import Any, Dict, List, Optional
import uuid
import math
import pandas as pd
import numpy as np
from dataclasses import dataclass
from backend.screening.storage import PostgresScreeningStore
from backend.screening.early_turn_engine import EarlyTurnEngine

# 预设验证集正样本（来自文档）
BUILTIN_POSITIVE_SAMPLES = [
    {"ts_code": "600683.SH", "target_date": "20260807", "sample_name": "京投发展", "note": "最佳入选日: 08-07 (68分 PRE_READY)，信号从 08-04 的 57分(WATCH) 递增至 08-07 的 68分"},
    {"ts_code": "600216.SH", "target_date": "20260715", "sample_name": "浙江医药", "note": "最佳入选区间: 07-09~07-15 (连续71分 PRE_READY)，07-16 暴涨拐点达 88分 EARLY_TURN"},
    {"ts_code": "600721.SH", "target_date": "20260720", "sample_name": "百花医药", "note": "最佳入选日: 07-17 与 07-20 (86分 EARLY_TURN)，首次观察日为 07-15"},
    {"ts_code": "600266.SH", "target_date": "20260723", "sample_name": "城建发展", "note": "最佳入选日: 07-15 (83分 EARLY_TURN) 及 07-23/07-27 (67分 PRE_READY)，回避了07-25试盘探底"},
    {"ts_code": "002659.SZ", "target_date": "20260729", "sample_name": "凯文教育", "note": "最佳入选日: 07-15 (83分) 与 07-29 (88分 EARLY_TURN)，08-01 连涨后精准触发防追高风控"},
    {"ts_code": "300308.SZ", "target_date": "20260617", "sample_name": "中际旭创", "note": "高位横盘整理再启动样本，最佳入选日: 06-17 (67分 PRE_READY)，首次观察日 05-08"},
]


@dataclass
class EarlyTurnService:
    store: PostgresScreeningStore
    engine: EarlyTurnEngine = EarlyTurnEngine()

    def calculate_features_from_bars(self, ts_code: str, target_date: str) -> dict[str, Any]:
        """基于 screening_daily_bar 表向上追溯 150 日 K 线现场实时计算特征"""
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                select trade_date, open, high, low, close, vol, amount
                from screening_daily_bar
                where asset_code = %s and trade_date <= %s
                order by trade_date desc limit 150
                """,
                (ts_code, target_date),
            ).fetchall()

        if not rows or len(rows) < 15:
            return {}

        df = pd.DataFrame([dict(r) for r in reversed(rows)])
        for col in ['open', 'high', 'low', 'close', 'vol', 'amount']:
            df[col] = df[col].astype(float)

        # 均线计算
        df['ma5'] = df['close'].rolling(5).mean()
        df['ma10'] = df['close'].rolling(10).mean()
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma30'] = df['close'].rolling(30).mean()
        df['ma60'] = df['close'].rolling(60).mean()

        # ATR20
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                (df['high'] - df['close'].shift(1)).abs(),
                (df['low'] - df['close'].shift(1)).abs()
            )
        )
        df['atr20'] = df['tr'].rolling(20).mean()

        # 10 日均线结 (MA Knot) 交叉对数统计
        pairs = [(5, 10), (5, 20), (5, 30), (10, 20), (10, 30), (20, 30)]
        cross_pairs = set()
        cross_events = 0

        recent_10 = df.tail(10)
        for i in range(1, len(recent_10)):
            t_curr = recent_10.iloc[i]
            t_prev = recent_10.iloc[i - 1]
            for p1, p2 in pairs:
                m1_curr, m2_curr = t_curr[f'ma{p1}'], t_curr[f'ma{p2}']
                m1_prev, m2_prev = t_prev[f'ma{p1}'], t_prev[f'ma{p2}']
                if pd.notna(m1_curr) and pd.notna(m2_curr) and pd.notna(m1_prev) and pd.notna(m2_prev):
                    if (m1_curr > m2_curr) != (m1_prev > m2_prev):
                        cross_pairs.add((p1, p2))
                        cross_events += 1

        def calc_order_score(row):
            m5, m10, m20, m30 = row['ma5'], row['ma10'], row['ma20'], row['ma30']
            if pd.isna(m5) or pd.isna(m10) or pd.isna(m20) or pd.isna(m30):
                return 1.0
            return (1.0 if m5 > m10 else 0.0) + (1.0 if m5 > m20 else 0.0) + (1.0 if m10 > m20 else 0.0) + (0.5 if m20 > m30 else 0.0)

        def calc_retake_count(row):
            close_val = row['close']
            return sum([
                1 for p in (5, 10, 20, 30)
                if pd.notna(row[f'ma{p}']) and close_val > row[f'ma{p}']
            ])

        # Add retake_count column to df for consecutive days calculation
        df['retake_count'] = df.apply(calc_retake_count, axis=1)

        # MA Slopes
        df['ma5_slope'] = df['ma5'].pct_change(3)
        df['ma10_slope'] = df['ma10'].pct_change(5)
        df['ma20_slope'] = df['ma20'].pct_change(5)
        df['ma30_slope'] = df['ma30'].pct_change(5)

        curr = df.iloc[-1]
        prev_5 = df.iloc[-6] if len(df) >= 6 else curr
        idx = len(df) - 1

        def count_consecutive(series_bool, end_idx):
            count = 0
            for k in range(end_idx, -1, -1):
                if series_bool.iloc[k]:
                    count += 1
                else:
                    break
            return count

        days_retake_3ma = count_consecutive(df['retake_count'] >= 3, idx)
        days_retake_4ma = count_consecutive(df['retake_count'] >= 4, idx)
        days_ma5_slope_pos = count_consecutive(df['ma5_slope'] > 0, idx)
        days_ma10_slope_pos = count_consecutive(df['ma10_slope'] > 0, idx)

        # Resistance high
        lookback_60 = df.tail(60)
        recent_high_60 = float(lookback_60['high'].max())
        close_curr = float(curr['close'])
        dist_high_60 = (recent_high_60 - close_curr) / close_curr

        lookback_120 = df.tail(120)
        recent_high_120 = float(lookback_120['high'].max())
        dist_high_120 = (recent_high_120 - close_curr) / close_curr

        # Overhead peaks detection
        peaks = []
        for i in range(max(0, idx - 60), idx):
            if i < 2 or i > len(df) - 3:
                continue
            val = df.iloc[i]['high']
            if val == df.iloc[i-2:i+3]['high'].max():
                peaks.append(float(val))
        resistance_peaks = [p for p in peaks if close_curr <= p <= close_curr * 1.06]
        overhead_resistance_flag = len(resistance_peaks) >= 2

        # Turn type
        prior_window = df.iloc[max(0, idx-60):max(0, idx-5)]
        has_prior_strong_turn = False
        consec = 0
        for val in prior_window['retake_count']:
            if val >= 3:
                consec += 1
                if consec >= 3:
                    has_prior_strong_turn = True
            else:
                consec = 0

        days_above_ma20_prior = sum([1 for i, r in prior_window.iterrows() if r['close'] > r['ma20']])
        ratio_above_ma20 = days_above_ma20_prior / len(prior_window) if len(prior_window) > 0 else 0.0

        if ratio_above_ma20 > 0.6:
            turn_type = "CONSOLIDATION_RESTART"
        elif has_prior_strong_turn:
            turn_type = "SECONDARY_TURN"
        else:
            turn_type = "FIRST_TURN"

        vol_ratio = float(curr['amount'] / lookback_60['amount'].median()) if len(lookback_60) > 0 and lookback_60['amount'].median() > 0 else 1.0

        order_score_curr = calc_order_score(curr)
        order_score_5d = calc_order_score(prev_5)

        features = {
            'close': close_curr,
            'ma5': float(curr['ma5']) if pd.notna(curr['ma5']) else 0.0,
            'ma10': float(curr['ma10']) if pd.notna(curr['ma10']) else 0.0,
            'ma20': float(curr['ma20']) if pd.notna(curr['ma20']) else 0.0,
            'ma30': float(curr['ma30']) if pd.notna(curr['ma30']) else 0.0,
            'ma60': float(curr['ma60']) if pd.notna(curr['ma60']) else 0.0,
            'atr20': float(curr['atr20']) if pd.notna(curr['atr20']) else close_curr * 0.03,
            'cross_pair_count_10d': len(cross_pairs),
            'cross_event_count_10d': cross_events,
            'order_score': order_score_curr,
            'order_score_5d_ago': order_score_5d,
            'order_improvement': order_score_curr - order_score_5d,
            'retake_count': int(curr['retake_count']),
            'days_retake_3ma': days_retake_3ma,
            'days_retake_4ma': days_retake_4ma,
            'days_ma5_slope_pos': days_ma5_slope_pos,
            'days_ma10_slope_pos': days_ma10_slope_pos,
            'recent_high_60': recent_high_60,
            'recent_high_120': recent_high_120,
            'dist_high_60': dist_high_60,
            'dist_high_120': dist_high_120,
            'overhead_resistance_flag': overhead_resistance_flag,
            'turn_type': turn_type,
            'volume_ratio': vol_ratio,
            'slope5_3d': float(curr['ma5'] / df.iloc[-4]['ma5'] - 1.0) if len(df) >= 4 and pd.notna(df.iloc[-4]['ma5']) else 0.0,
            'slope10_5d': float(curr['ma10'] / prev_5['ma10'] - 1.0) if pd.notna(prev_5['ma10']) else 0.0,
            'slope20_5d': float(curr['ma20'] / prev_5['ma20'] - 1.0) if pd.notna(prev_5['ma20']) else 0.0,
            'slope30_5d': float(curr['ma30'] / prev_5['ma30'] - 1.0) if pd.notna(prev_5['ma30']) else 0.0,
            'higher_low': float(curr['low']) >= float(df.iloc[-10]['low'].min()) if len(df) >= 10 else True,
            'amount_preheat': float(curr['amount'] / df.tail(20)['amount'].median()) if len(df) >= 20 and df.tail(20)['amount'].median() > 0 else 1.0,
        }
        return features

    def run(self, trade_date: str, ts_code: Optional[str] = None, config_version: str = "early_turn_v1.0") -> dict[str, Any]:
        """运行一次 A-Pre V2 策略评估（支持全市场或单股定向）"""
        run_id = f"et_{trade_date}_{uuid.uuid4().hex[:8]}"
        self.store.create_early_turn_run(run_id=run_id, trade_date=trade_date, config_version=config_version)

        try:
            # 1. 确定要计算的资产列表
            with self.store.connect() as conn:
                if ts_code:
                    clean_code = ts_code.strip().upper()
                    if "." not in clean_code:
                        clean_code = clean_code + (".SH" if clean_code.startswith("6") else ".SZ")
                    rows = conn.execute(
                        "select asset_code as ts_code, name, raw_json->>'industry' as industry from screening_asset_master where asset_code ilike %s",
                        (f"%{clean_code}%",),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "select asset_code as ts_code, name, raw_json->>'industry' as industry from screening_asset_master"
                    ).fetchall()

            eval_results = []
            counts: Dict[str, int] = {}

            for row in rows:
                code = row["ts_code"]
                feat = self.calculate_features_from_bars(code, trade_date)
                if not feat:
                    continue

                feat["name"] = row.get("name")
                feat["industry"] = row.get("industry")

                res = self.engine.evaluate_stock(code, trade_date, feat)
                res["run_id"] = run_id
                res["first_selected_date"] = self._find_first_selected_date(code, trade_date, res["selected"])

                eval_results.append(res)
                st = res["state"]
                counts[st] = counts.get(st, 0) + 1

            # 2. 保存结果
            self.store.save_early_turn_results(eval_results)

            summary = {
                "run_id": run_id,
                "trade_date": trade_date,
                "total_evaluated": len(eval_results),
                "counts": counts,
                "selected_count": counts.get("EARLY_TURN_STRICT", 0) + counts.get("EARLY_TURN", 0) + counts.get("PRE_READY_STRICT", 0) + counts.get("PRE_READY", 0),
                "items": eval_results if ts_code else None,
            }
            self.store.finish_early_turn_run(run_id, status="DONE", summary=summary)
            return summary

        except Exception as exc:
            self.store.finish_early_turn_run(run_id, status="ERROR", error_message=str(exc))
            raise exc

    def _find_first_selected_date(self, ts_code: str, current_date: str, is_currently_selected: bool) -> str | None:
        if not is_currently_selected:
            return None
        with self.store.connect() as conn:
            row = conn.execute(
                "select min(trade_date) as min_date from early_turn_result where ts_code = %s and selected = true and trade_date <= %s",
                (ts_code, current_date),
            ).fetchone()
        return row["min_date"] if row and row["min_date"] else current_date

    def validate_positive_samples(self, target_trade_date: str | None = None) -> list[dict[str, Any]]:
        """跑预设正样本基于 K 线的全量回归校验集"""
        for s in BUILTIN_POSITIVE_SAMPLES:
            self.store.save_positive_sample(
                ts_code=s["ts_code"],
                target_date=s["target_date"],
                sample_name=s["sample_name"],
                note=s["note"],
            )

        samples = self.store.list_positive_samples()
        validation_results = []

        for sample in samples:
            t_date = target_trade_date or sample["target_date"]
            ts_code = sample["ts_code"]

            feat = self.calculate_features_from_bars(ts_code, t_date)
            if not feat:
                validation_results.append({
                    "sample_id": sample["sample_id"],
                    "ts_code": ts_code,
                    "sample_name": sample["sample_name"],
                    "target_date": t_date,
                    "status": "DATA_MISSING",
                    "note": "行数据不足 15 日",
                    "total_score": 0.0,
                    "state": "NO_SIGNAL",
                })
                continue

            eval_res = self.engine.evaluate_stock(ts_code, t_date, feat)
            eval_res["sample_id"] = sample["sample_id"]
            eval_res["sample_name"] = sample["sample_name"]
            eval_res["target_date"] = t_date
            eval_res["hit"] = eval_res["state"] in ("EARLY_TURN", "PRE_READY", "WATCH")

            validation_results.append(eval_res)

        return validation_results
