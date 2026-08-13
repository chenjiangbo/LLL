#!/usr/bin/env python3
import os
import sys
import argparse
import pandas as pd
import numpy as np
from backend.screening.storage import PostgresScreeningStore
from backend.screening.early_turn_service import EarlyTurnService
from backend.screening.early_turn_engine import EarlyTurnEngine

def evaluate_stock_v2(df_slice, idx, feat):
    # A. Background & Base: max 15 points
    tt = feat["turn_type"]
    bg_score = 5.0
    if tt == "FIRST_TURN":
        bg_score = 15.0
    elif tt == "SECONDARY_TURN":
        bg_score = 12.0
    elif tt == "CONSOLIDATION_RESTART":
        bg_score = 10.0
    
    # B. MA Regime Transition: max 25 points
    min_3ma_spread_atr = feat["min_3ma_spread_atr"]
    spread_5d = feat.get("ma_spread_5d_ago", min_3ma_spread_atr * 1.2)
    comp_ratio = min_3ma_spread_atr / spread_5d if spread_5d > 0 else 1.0
    cross_pairs = feat.get("cross_pair_count_10d", 0)
    
    score_transition = 0.0
    if min_3ma_spread_atr <= 0.51:
        score_transition += 15.0
    elif min_3ma_spread_atr <= 0.8:
        score_transition += 10.0
    elif min_3ma_spread_atr <= 1.2:
        score_transition += 5.0
        
    if comp_ratio < 0.8:
        score_transition += 5.0
    elif comp_ratio < 0.95:
        score_transition += 3.0
        
    if cross_pairs >= 3:
        score_transition += 5.0
    elif cross_pairs >= 2:
        score_transition += 3.0
        
    # chop penalty
    cross_reversal_count = 0
    slice_15 = df_slice.iloc[max(0, idx-15):idx+1]
    if len(slice_15) >= 2:
        cross_states = (slice_15["close"] > slice_15["ma20"]).astype(int)
        cross_reversal_count = (cross_states.diff().abs() == 1).sum()
    
    chop_penalty = 0.0
    if cross_reversal_count >= 4:
        chop_penalty = 6.0
    elif cross_reversal_count >= 2:
        chop_penalty = 3.0
    score_transition = max(0.0, score_transition - chop_penalty)
    score_transition = min(25.0, score_transition)

    # C. Price Retake: max 15 points
    retake_cnt = feat["retake_count"]
    score_retake = 0.0
    if retake_cnt == 4:
        score_retake = 15.0
    elif retake_cnt == 3:
        score_retake = 10.0
    elif retake_cnt == 2:
        score_retake = 5.0
        
    days_retake_3ma = feat["days_retake_3ma"]
    if days_retake_3ma > 3:
        score_retake = max(0.0, score_retake - 5.0)

    # D. Directional Turn (MA Direction): max 15 points
    order_score = feat["order_score"]
    order_improvement = feat["order_improvement"]
    score_direction = 0.0
    if order_score >= 3.0:
        score_direction += 10.0
    elif order_score >= 2.0:
        score_direction += 5.0
    if order_improvement > 0:
        score_direction += 5.0
    score_direction = min(15.0, score_direction)

    # E. Freshness: max 10 points
    score_freshness = 1.0
    if days_retake_3ma <= 2:
        score_freshness = 10.0
    elif days_retake_3ma <= 5:
        score_freshness = 7.0
    elif days_retake_3ma <= 10:
        score_freshness = 4.0

    # F. Volume Confirmation: max 10 points
    vol_ratio = feat["volume_ratio"]
    score_vol = 2.0
    if vol_ratio >= 1.5:
        score_vol = 10.0
    elif vol_ratio >= 1.1:
        score_vol = 6.0
    elif vol_ratio >= 0.8:
        score_vol = 4.0

    # G. Space & Extension: max 10 points
    extension_atr = feat["extension_atr"]
    dist_high_60 = feat["dist_high_60"]
    overhead_res = feat["overhead_resistance_flag"]
    
    score_space = 0.0
    if extension_atr <= 1.0:
        score_space += 5.0
    elif extension_atr <= 1.5:
        score_space += 3.0
    elif extension_atr <= 2.0:
        score_space += 1.0
        
    if dist_high_60 >= 0.08:
        score_space += 5.0
    elif dist_high_60 >= 0.04:
        score_space += 3.0
    elif not overhead_res:
        score_space += 2.0
        
    score_space = min(10.0, score_space)
    
    total_score = bg_score + score_transition + score_retake + score_direction + score_freshness + score_vol + score_space
    
    # State assignment
    is_ext = extension_atr > 2.0
    if is_ext:
        state = "TOO_LATE"
    elif total_score >= 75.0 and min_3ma_spread_atr <= 0.51 and cross_pairs >= 3:
        state = "EARLY_TURN_STRICT"
    elif total_score >= 75.0:
        state = "EARLY_TURN"
    elif total_score >= 65.0 and min_3ma_spread_atr <= 0.60 and cross_pairs >= 2:
        state = "PRE_READY_STRICT"
    elif total_score >= 65.0:
        state = "PRE_READY"
    elif total_score >= 50.0:
        state = "WATCH"
    else:
        state = "NO_SIGNAL"
        
    return {
        "total_score": round(total_score, 1),
        "state": state,
        "detail": {
            "background": bg_score,
            "transition": score_transition,
            "retake": score_retake,
            "direction": score_direction,
            "freshness": score_freshness,
            "vol": score_vol,
            "space": score_space,
            "chop_penalty": chop_penalty,
        }
    }

def main():
    parser = argparse.ArgumentParser(description="A-Pre V2 Debug and Score Explainer")
    parser.add_argument("--ts-code", type=str, default="688505.SH", help="Stock TS code")
    parser.add_argument("--date", type=str, default="20260810", help="Trade date YYYYMMDD")
    args = parser.parse_args()

    ts_code = args.ts_code
    target_date = args.date.replace("-", "")

    db_url = os.getenv("MARKET_REVIEW_DATABASE_URL", "postgresql://lll:lll_dev_password@localhost:15432/lll_market_review")
    store = PostgresScreeningStore(db_url)
    svc = EarlyTurnService(store=store)
    engine = EarlyTurnEngine()

    print(f"=== A-Pre V2 Debug Explainer for {ts_code} on {target_date} ===\n")

    # Fetch 150 trading days for lookback
    with store.connect() as conn:
        rows = conn.execute(
            """
            select trade_date, open, high, low, close, vol, amount
            from screening_daily_bar
            where asset_code = %s and trade_date <= %s
            order by trade_date desc
            limit 150
            """,
            (ts_code, target_date),
        ).fetchall()

    if not rows:
        print(f"Error: No daily bar found for {ts_code} on/before {target_date}.")
        return

    df = pd.DataFrame([dict(r) for r in rows][::-1])
    for col in ["open", "high", "low", "close", "vol", "amount"]:
        df[col] = df[col].astype(float)
        
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma30"] = df["close"].rolling(30).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    
    df["tr"] = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs()
        )
    )
    df["atr20"] = df["tr"].rolling(20).mean()

    target_idx = df[df["trade_date"] == target_date].index
    if len(target_idx) == 0:
        print(f"Error: Date {target_date} not found.")
        return
    idx = target_idx[0]

    # Calculate retake_count for all rows
    def get_retake_count(row):
        c = row["close"]
        return sum([1 for p in (5, 10, 20, 30) if pd.notna(row[f"ma{p}"]) and c > row[f"ma{p}"]])
    df["retake_count"] = df.apply(get_retake_count, axis=1)

    # MA Slopes
    df["ma5_slope"] = df["ma5"].pct_change(3)
    df["ma10_slope"] = df["ma10"].pct_change(5)
    df["ma20_slope"] = df["ma20"].pct_change(5)
    df["ma30_slope"] = df["ma30"].pct_change(5)

    def count_consecutive(series_bool, end_idx):
        count = 0
        for k in range(end_idx, -1, -1):
            if series_bool.iloc[k]:
                count += 1
            else:
                break
        return count

    # Crossings detection
    cross_indices = []
    pairs = [(5, 10), (5, 20), (5, 30), (10, 20), (10, 30), (20, 30)]
    for i in range(1, len(df)):
        has_cross = False
        for p1, p2 in pairs:
            m1_curr, m2_curr = df.iloc[i][f"ma{p1}"], df.iloc[i][f"ma{p2}"]
            m1_prev, m2_prev = df.iloc[i-1][f"ma{p1}"], df.iloc[i-1][f"ma{p2}"]
            if pd.notna(m1_curr) and pd.notna(m2_curr) and pd.notna(m1_prev) and pd.notna(m2_prev):
                if (m1_curr > m2_curr) != (m1_prev > m2_prev):
                    has_cross = True
                    break
        if has_cross:
            cross_indices.append(i)

    # Helper function to generate features dict for evaluation on day i
    def get_eval_features(i):
        curr_row = df.iloc[i]
        prev_3 = df.iloc[i-3] if i >= 3 else curr_row
        prev_5 = df.iloc[i-5] if i >= 5 else curr_row
        
        # cross pairs in last 10 days
        c_pairs = set()
        c_events = 0
        for j in range(max(1, i-9), i+1):
            for p1, p2 in pairs:
                m1_curr, m2_curr = df.iloc[j][f"ma{p1}"], df.iloc[j][f"ma{p2}"]
                m1_prev, m2_prev = df.iloc[j-1][f"ma{p1}"], df.iloc[j-1][f"ma{p2}"]
                if pd.notna(m1_curr) and pd.notna(m2_curr) and pd.notna(m1_prev) and pd.notna(m2_prev):
                    if (m1_curr > m2_curr) != (m1_prev > m2_prev):
                        c_pairs.add((p1, p2))
                        c_events += 1

        def calc_order_score(row):
            m5, m10, m20, m30 = row['ma5'], row['ma10'], row['ma20'], row['ma30']
            if pd.isna(m5) or pd.isna(m10) or pd.isna(m20) or pd.isna(m30):
                return 1.0
            return (1.0 if m5 > m10 else 0.0) + (1.0 if m5 > m20 else 0.0) + (1.0 if m10 > m20 else 0.0) + (0.5 if m20 > m30 else 0.0)

        # 3-MA spread
        mas = [curr_row[f"ma{p}"] for p in (5, 10, 20, 30) if pd.notna(curr_row[f"ma{p}"])]
        min_3_spread = 999.0
        if len(mas) >= 3:
            sorted_mas = sorted(mas)
            min_3_spread = min(sorted_mas[2] - sorted_mas[0], sorted_mas[3] - sorted_mas[1] if len(sorted_mas) >= 4 else 999.0)
            
        atr = curr_row["atr20"] if pd.notna(curr_row["atr20"]) else curr_row["close"] * 0.03
        
        # 5d ago spread
        prev_5_row = df.iloc[i-5] if i >= 5 else curr_row
        prev_5_mas = [prev_5_row[f"ma{p}"] for p in (5, 10, 20, 30) if pd.notna(prev_5_row[f"ma{p}"])]
        prev_5_spread = 999.0
        if len(prev_5_mas) >= 3:
            s_mas = sorted(prev_5_mas)
            prev_5_spread = min(s_mas[2] - s_mas[0], s_mas[3] - s_mas[1] if len(s_mas) >= 4 else 999.0)

        # Resistance high
        lookback_60_d = df.iloc[max(0, i-60):i+1]
        recent_h60 = float(lookback_60_d["high"].max())
        close_val = float(curr_row["close"])
        d_high_60 = (recent_h60 - close_val) / close_val
        
        # peaks in last 60 days
        peaks_d = []
        for k in range(max(0, i-60), i):
            if k < 2 or k > len(df) - 3:
                continue
            v = df.iloc[k]["high"]
            if v == df.iloc[k-2:k+3]["high"].max():
                peaks_d.append(float(v))
        res_peaks = [p for p in peaks_d if close_val <= p <= close_val * 1.06]
        overhead_flag = len(res_peaks) >= 2

        # turn type
        prior_w = df.iloc[max(0, i-60):max(0, i-5)]
        has_prior_t = False
        consec_d = 0
        for val in prior_w["retake_count"]:
            if val >= 3:
                consec_d += 1
                if consec_d >= 3:
                    has_prior_t = True
            else:
                consec_d = 0
        days_above_ma20_p = sum([1 for j, r in prior_w.iterrows() if r["close"] > r["ma20"]])
        ratio_ma20_d = days_above_ma20_p / len(prior_w) if len(prior_w) > 0 else 0.0
        
        if ratio_ma20_d > 0.6:
            tt = "CONSOLIDATION_RESTART"
        elif has_prior_t:
            tt = "SECONDARY_TURN"
        else:
            tt = "FIRST_TURN"

        vol_r = float(curr_row["amount"] / lookback_60_d["amount"].median()) if len(lookback_60_d) > 0 and lookback_60_d["amount"].median() > 0 else 1.0

        return {
            "close": close_val,
            "ma5": float(curr_row["ma5"]) if pd.notna(curr_row["ma5"]) else 0.0,
            "ma10": float(curr_row["ma10"]) if pd.notna(curr_row["ma10"]) else 0.0,
            "ma20": float(curr_row["ma20"]) if pd.notna(curr_row["ma20"]) else 0.0,
            "ma30": float(curr_row["ma30"]) if pd.notna(curr_row["ma30"]) else 0.0,
            "ma60": float(curr_row["ma60"]) if pd.notna(curr_row["ma60"]) else 0.0,
            "atr20": atr,
            "min_3ma_spread_atr": min_3_spread / atr if atr > 0 else 9.9,
            "ma_spread_5d_ago": prev_5_spread,
            "cross_pair_count_10d": len(c_pairs),
            "order_score": calc_order_score(curr_row),
            "order_improvement": calc_order_score(curr_row) - calc_order_score(prev_5_row),
            "retake_count": curr_row["retake_count"],
            "days_retake_3ma": count_consecutive(df["retake_count"] >= 3, i),
            "days_retake_4ma": count_consecutive(df["retake_count"] >= 4, i),
            "days_ma5_slope_pos": count_consecutive(df["ma5_slope"] > 0, i),
            "days_ma10_slope_pos": count_consecutive(df["ma10_slope"] > 0, i),
            "turn_type": tt,
            "volume_ratio": vol_r,
            "dist_high_60": d_high_60,
            "overhead_resistance_flag": overhead_flag,
            "extension_atr": (close_val - curr_row["ma20"]) / atr if pd.notna(curr_row["ma20"]) and atr > 0 else 0.0
        }

    # Evaluate for target day
    feat_target = get_eval_features(idx)
    res_v1 = engine.evaluate_stock(ts_code, target_date, svc.calculate_features_from_bars(ts_code, target_date))
    res_v2 = evaluate_stock_v2(df, idx, feat_target)

    print("=====================================================================")
    print("OUTPUT A: V1 vs V2 DETAILED SCORE COMPARISON (688505.SH 2026-08-10)")
    print("=====================================================================")
    print(f"V1 Total Score: {res_v1['total_score']:.1f}分 | State: {res_v1['state']}")
    print(f"V2 Total Score: {res_v2['total_score']:.1f}分 | State: {res_v2['state']}")
    print("-" * 69)
    print(f"{'Feature Sub-Module':<30} | {'V1 Score':<8} | {'V2 Score':<8} | {'V2 Max':<6} | Description")
    print("-" * 69)
    
    # Details mapping
    print(f"{'Background & Base':<30} | {res_v1['score_detail_json'].get('background', 0):<8.1f} | {res_v2['detail']['background']:<8.1f} | {15:<6} | Reversal/Consolidation/TurnType")
    print(f"{'MA Regime Transition':<30} | {res_v1['score_detail_json'].get('compression', 0) + res_v1['score_detail_json'].get('knot', 0):<8.1f} | {res_v2['detail']['transition']:<8.1f} | {25:<6} | Compression, Knot & Chop penalty")
    print(f"{'Price Retake':<30} | {res_v1['score_detail_json'].get('retake', 0):<8.1f} | {res_v2['detail']['retake']:<8.1f} | {15:<6} | Price above MAs and Freshness cut")
    print(f"{'Directional Turn (MA Direction)':<30} | {res_v1['score_detail_json'].get('direction', 0) + res_v1['score_detail_json'].get('slope', 0):<8.1f} | {res_v2['detail']['direction']:<8.1f} | {15:<6} | Slopes & Order Reordering")
    print(f"{'Freshness (Earliness)':<30} | {'-':<8} | {res_v2['detail']['freshness']:<8.1f} | {10:<6} | Transition Freshness factor")
    print(f"{'Volume Confirmation':<30} | {res_v1['score_detail_json'].get('bonus', 0):<8.1f} | {res_v2['detail']['vol']:<8.1f} | {10:<6} | Volume Ratio and preheat")
    print(f"{'Space & Extension':<30} | {res_v1['score_detail_json'].get('extension', 0):<8.1f} | {res_v2['detail']['space']:<8.1f} | {10:<6} | Space to high and Overextension")
    print("-" * 69)
    print(f"Chop Penalty Applied in V2: -{res_v2['detail']['chop_penalty']} points")

    # --- Print Output B: 20-day Time Series History for V2 ---
    print("\n=========================================================================")
    print("OUTPUT B: 688505.SH 20-DAY TIME SERIES HISTORY (OPTIMIZED V2 MODEL)")
    print("=========================================================================")
    
    ts_data_v2 = []
    start_idx = max(0, idx - 19)
    for i in range(start_idx, idx + 1):
        d = df.iloc[i]["trade_date"]
        feat_day = get_eval_features(i)
        eval_v2 = evaluate_stock_v2(df, i, feat_day)
        
        ts_data_v2.append({
            "trade_date": d,
            "total_score": eval_v2["total_score"],
            "retake_count": feat_day["retake_count"],
            "ma_spread": round(feat_day["min_3ma_spread_atr"], 2),
            "cross_pair_count": feat_day["cross_pair_count_10d"],
            "directional_cross": int(feat_day["order_improvement"] > 0),
            "up_slope_count": sum([1 for s in (df.iloc[i]["ma5_slope"], df.iloc[i]["ma10_slope"], df.iloc[i]["ma20_slope"], df.iloc[i]["ma30_slope"]) if s > 0]),
            "days_since_first_retake_3ma": feat_day["days_retake_3ma"],
            "turn_type": feat_day["turn_type"],
            "volume_ratio": round(feat_day["volume_ratio"], 2),
            "distance_to_resistance": f"{feat_day['dist_high_60']:.2%}",
            "status": eval_v2["state"]
        })

    print(f"{'Date':<10} | {'Score':<5} | {'Retake':<6} | {'Spread':<6} | {'Knot':<4} | {'DirCross':<8} | {'Slope':<5} | {'DaysRet3':<8} | {'TurnType':<22} | {'VolRatio':<8} | {'DistRes':<8} | {'Status'}")
    print("-" * 125)
    for r in ts_data_v2:
        print(f"{r['trade_date']:<10} | {r['total_score']:<5.1f} | {r['retake_count']:<6} | {r['ma_spread']:<6.2f} | {r['cross_pair_count']:<4} | {r['directional_cross']:<8} | {r['up_slope_count']:<5} | {r['days_since_first_retake_3ma']:<8} | {r['turn_type']:<22} | {r['volume_ratio']:<8.2f} | {r['distance_to_resistance']:<8} | {r['status']}")
    print("-" * 125)

if __name__ == "__main__":
    main()
