"""
SecondaryScreeningService — P1+P2 审计骨架 + L1/L2/L3 状态机

职责：
  - L0：读取现有 A/B/C 候选池快照
  - L1：硬过滤（ST / 上市天数 / 流动性 / 涨停）
  - L2：质量复核（A/B池差异化评分；C池沿用通用）
  - L3：横截面相对强度排名（全市场 / 池内 / 申万二级行业内）
  - 写入 stage_snapshot / stage_reason，支持完整溯源

L1 reason_code：
  L1_NOT_TRADING    — 当日无有效交易
  L1_ST_RISK        — ST/*ST 股票
  L1_TOO_NEW        — 上市交易日不足
  L1_LOW_LIQUIDITY  — 20 日成交额低于阈值
  L1_TEMP_LIMITED   — 一字涨停
  DATA_CORE_MISSING — 核心数据缺失

L2 reason_code：
  L2_PREMISE_BROKEN — 核心前提结构失效
  L2_QUALITY_LOW    — 质量分低于阈值

L3 reason_code：
  L3_STRENGTH_LOW   — 横向强度低于阈值
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from backend.screening.storage import PostgresScreeningStore

# ── reason_code 常量 ───────────────────────────────────────────────────────────
L1_NOT_TRADING    = "L1_NOT_TRADING"
L1_ST_RISK        = "L1_ST_RISK"
L1_TOO_NEW        = "L1_TOO_NEW"
L1_LOW_LIQUIDITY  = "L1_LOW_LIQUIDITY"
L1_TEMP_LIMITED   = "L1_TEMP_LIMITED"
DATA_CORE_MISSING = "DATA_CORE_MISSING"
L2_PREMISE_BROKEN = "L2_PREMISE_BROKEN"
L2_QUALITY_LOW    = "L2_QUALITY_LOW"
L3_STRENGTH_LOW   = "L3_STRENGTH_LOW"
L4_NOT_READY      = "L4_NOT_READY"
L4_OVEREXTENDED   = "L4_OVEREXTENDED"
L4_STRUCTURE_INVALID = "L4_STRUCTURE_INVALID"
L5_SCORE_LOW      = "L5_SCORE_LOW"

# 层级 / 状态常量
STAGE_L0            = "L0"
STAGE_L1            = "L1"
STAGE_L2            = "L2"
STAGE_L3            = "L3"
STAGE_L4            = "L4"
STAGE_L5            = "L5"
STATUS_PASS         = "PASS"
STATUS_FAIL         = "FAIL"
STATUS_DEFER        = "DEFER"
STATUS_DATA_MISSING = "DATA_MISSING"
STATUS_READY        = "READY"
STATUS_WATCH        = "WATCH"
STATUS_OVEREXTENDED = "OVEREXTENDED"
STATUS_INVALIDATED  = "INVALIDATED"
STATUS_NOT_EVALUATED = "NOT_EVALUATED"


@dataclass
class SecondaryScreeningConfig:
    """所有阈值集中于此，禁止散落在业务逻辑中"""
    # L1
    min_listing_trade_days: int    = 120    # 文档 L1.min_listing_trade_days
    min_median_amount_20_cny: float = 3e7   # 文档 L1.min_median_amount_20（3000万元）
    exclude_st: bool               = True
    # L2
    l2_pass_score: float           = 60.0   # 文档 L2.pass_score
    l2_fail_score: float           = 45.0   # 文档 L2.fail_score（低于此直接FAIL）
    # L3
    l3_pass_score: float           = 60.0   # 文档 L3.pass_score（全市场百分位>=60%）
    l3_fail_score: float           = 40.0   # 文档 L3.fail_score
    l3_primary_window: int         = 60     # RS 主窗口（RS60）
    min_industry_members: int      = 10     # 行业小样本回退阈值
    # L4
    l4_ready_score: float           = 60.0   # 文档 L4.ready_score
    l4_max_extension_atr: float     = 2.5    # 偏离均线>2.5个ATR视为过伸/追高
    # L5
    l5_opportunity_min_score: float = 70.0   # 文档 L5 综合机会分推荐门槛
    l5_top_n: int                   = 20
    # 通用
    data_version: str              = "v1"
    config_version: str            = "secondary_v1.0"
    industry_source_version: str   = "SW2021"


@dataclass
class SecondaryScreeningService:
    config: SecondaryScreeningConfig
    store: PostgresScreeningStore

    def run(
        self,
        trade_date: str,
        run_name: str | None = None,
        notes: str | None = None,
        universe_type: str = "ALL",
        universe_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行一次完整的二次筛选（L0 ~ L5），支持任务命名、目标范围与版本归档。"""
        run_id = _make_run_id(trade_date)
        freshness = self.store.get_data_freshness_info()
        self.store.create_screening_run(
            run_id=run_id,
            trade_date=trade_date,
            config_version=self.config.config_version,
            data_version=self.config.data_version,
            run_name=run_name,
            notes=notes,
            universe_type=universe_type,
            universe_params=universe_params,
            data_freshness=freshness,
        )
        try:
            summary = self._execute(run_id, trade_date, universe_type=universe_type, universe_params=universe_params)
            self.store.finish_screening_run(run_id, status="DONE", summary=summary)
            return {"run_id": run_id, "status": "DONE", **summary}
        except Exception as exc:
            self.store.finish_screening_run(run_id, status="ERROR", error_message=str(exc))
            raise

    def _execute(self, run_id: str, trade_date: str, universe_type: str = 'ALL', universe_params: dict[str, Any] | None = None) -> dict[str, Any]:
        # ── L0：读取现有候选池快照 ────────────────────────────────────────
        l0_candidates = self._load_l0_candidates(trade_date)
        if universe_type == "CUSTOM_CODES" and universe_params and universe_params.get("codes"):
            codes_set = set(universe_params["codes"])
            l0_candidates = [c for c in l0_candidates if c["asset_code"] in codes_set]
        elif universe_type == "INDUSTRIES" and universe_params and universe_params.get("industries"):
            ind_set = set(universe_params["industries"])
            l0_candidates = [c for c in l0_candidates if (c.get("industry") or "") in ind_set]
        if not l0_candidates:
            raise RuntimeError(
                f"L0 candidates not found for {trade_date}. "
                "Please run CandidateScreeningService first."
            )

        # 写 L0 pool_candidate_snapshot_v2
        l0_pool_rows = [
            {
                "ts_code": c["asset_code"],
                "pool_code": c["primary_pool"],
                "pool_source_score": c.get("score"),
                "source_payload": {
                    "stage": c.get("stage"),
                    "asset_type": c.get("asset_type"),
                    "name": c.get("name"),
                },
            }
            for c in l0_candidates
        ]
        self.store.save_pool_candidates_v2(run_id, l0_pool_rows)

        # 写 L0 stage_snapshot（全部 PASS，L0 只保留快照）
        l0_snapshots = [
            {
                "run_id": run_id,
                "ts_code": c["asset_code"],
                "pool_code": c["primary_pool"],
                "stage": STAGE_L0,
                "status": STATUS_PASS,
                "score": c.get("score"),
                "score_detail": {"source_score": c.get("score")},
            }
            for c in l0_candidates
        ]
        self.store.save_stage_snapshots(l0_snapshots)

        # ── L1：加载因子，逐只执行 ────────────────────────────────────────
        feature_map = self._load_features(trade_date)

        l1_snapshots: list[dict[str, Any]] = []
        l1_reasons:   list[dict[str, Any]] = []
        l1_counts: dict[str, int] = {
            STATUS_PASS: 0, STATUS_FAIL: 0,
            STATUS_DEFER: 0, STATUS_DATA_MISSING: 0,
        }

        for candidate in l0_candidates:
            ts_code    = candidate["asset_code"]
            pool_code  = candidate["primary_pool"]
            features   = feature_map.get(ts_code) or {}
            asset_type = candidate.get("asset_type", "stock")

            status, reasons = self._evaluate_l1(
                ts_code, pool_code, features, asset_type, run_id
            )
            l1_counts[status] = l1_counts.get(status, 0) + 1

            l1_snapshots.append({
                "run_id":       run_id,
                "ts_code":      ts_code,
                "pool_code":    pool_code,
                "stage":        STAGE_L1,
                "status":       status,
                "score":        None,  # L1 是硬过滤，不计分
                "score_detail": None,
            })
            l1_reasons.extend(reasons)

        self.store.save_stage_snapshots(l1_snapshots)
        if l1_reasons:
            self.store.save_stage_reasons(l1_reasons)

        # ── L2：质量复核（仅对 L1 PASS 执行） ────────────────────────────
        l1_passed = {
            c["asset_code"]: c
            for c, snap in zip(l0_candidates, l1_snapshots)
            if snap["status"] == STATUS_PASS
        }
        l2_snapshots, l2_reasons, l2_counts = self._execute_l2(
            run_id, trade_date, l1_passed, feature_map
        )
        self.store.save_stage_snapshots(l2_snapshots)
        if l2_reasons:
            self.store.save_stage_reasons(l2_reasons)

        # NOT_EVALUATED：L1 FAIL/DEFER 的股票在 L2/L3 写占位
        not_eval_l2 = [
            {"run_id": run_id, "ts_code": c["asset_code"],
             "pool_code": c["primary_pool"], "stage": STAGE_L2,
             "status": STATUS_NOT_EVALUATED, "score": None, "score_detail": None}
            for c, snap in zip(l0_candidates, l1_snapshots)
            if snap["status"] != STATUS_PASS
        ]
        if not_eval_l2:
            self.store.save_stage_snapshots(not_eval_l2)

        # ── L3：横截面 RS 排名（仅对 L2 PASS 执行） ──────────────────────
        l2_passed_codes = {
            snap["ts_code"] for snap in l2_snapshots if snap["status"] == STATUS_PASS
        }
        l3_snapshots, l3_reasons, l3_counts = self._execute_l3(
            run_id, trade_date, l2_passed_codes,
            {c["asset_code"]: c for c in l0_candidates}
        )
        self.store.save_stage_snapshots(l3_snapshots)
        if l3_reasons:
            self.store.save_stage_reasons(l3_reasons)

        # NOT_EVALUATED：L2 FAIL 的股票在 L3 写占位
        not_eval_l3 = [
            {"run_id": run_id, "ts_code": snap["ts_code"],
             "pool_code": snap["pool_code"], "stage": STAGE_L3,
             "status": STATUS_NOT_EVALUATED, "score": None, "score_detail": None}
            for snap in l2_snapshots if snap["status"] != STATUS_PASS
        ]
        if not_eval_l3:
            self.store.save_stage_snapshots(not_eval_l3)

        # ── L4：触发时机评估（仅对 L3 PASS 执行） ──────────────────────
        l3_passed_codes = {
            snap["ts_code"] for snap in l3_snapshots if snap["status"] == STATUS_PASS
        }
        candidate_map = {c["asset_code"]: c for c in l0_candidates}
        l4_snapshots, l4_reasons, l4_counts = self._execute_l4(
            run_id, trade_date, l3_passed_codes, candidate_map, feature_map
        )
        self.store.save_stage_snapshots(l4_snapshots)
        if l4_reasons:
            self.store.save_stage_reasons(l4_reasons)

        # NOT_EVALUATED：L3 FAIL 的股票在 L4 写占位
        not_eval_l4 = [
            {"run_id": run_id, "ts_code": snap["ts_code"],
             "pool_code": snap["pool_code"], "stage": STAGE_L4,
             "status": STATUS_NOT_EVALUATED, "score": None, "score_detail": None}
            for snap in l3_snapshots if snap["status"] != STATUS_PASS
        ]
        if not_eval_l4:
            self.store.save_stage_snapshots(not_eval_l4)

        # ── L5：综合机会排名（对 L4 评估股票进行 Opportunity Score 计算）
        l4_eval_codes = {snap["ts_code"] for snap in l4_snapshots}
        l5_snapshots, l5_reasons, l5_counts = self._execute_l5(
            run_id, trade_date, l4_eval_codes, candidate_map, feature_map,
            l2_snapshots, l3_snapshots, l4_snapshots
        )
        self.store.save_stage_snapshots(l5_snapshots)
        if l5_reasons:
            self.store.save_stage_reasons(l5_reasons)

        # NOT_EVALUATED：L4 未评估的股票在 L5 写占位
        not_eval_l5 = [
            {"run_id": run_id, "ts_code": snap["ts_code"],
             "pool_code": snap["pool_code"], "stage": STAGE_L5,
             "status": STATUS_NOT_EVALUATED, "score": None, "score_detail": None}
            for snap in l4_snapshots if snap["status"] == STATUS_NOT_EVALUATED
        ]
        if not_eval_l5:
            self.store.save_stage_snapshots(not_eval_l5)

        return {
            "trade_date":      trade_date,
            "l0_count":        len(l0_candidates),
            "l1_pass":         l1_counts.get(STATUS_PASS, 0),
            "l1_fail":         l1_counts.get(STATUS_FAIL, 0),
            "l1_defer":        l1_counts.get(STATUS_DEFER, 0),
            "l1_data_missing": l1_counts.get(STATUS_DATA_MISSING, 0),
            "l2_pass":         l2_counts.get(STATUS_PASS, 0),
            "l2_fail":         l2_counts.get(STATUS_FAIL, 0),
            "l3_pass":         l3_counts.get(STATUS_PASS, 0),
            "l3_fail":         l3_counts.get(STATUS_FAIL, 0),
            "l4_pass":         l4_counts.get(STATUS_PASS, 0),
            "l4_fail":         l4_counts.get(STATUS_FAIL, 0),
            "l5_pass":         l5_counts.get(STATUS_PASS, 0),
            "l5_fail":         l5_counts.get(STATUS_FAIL, 0),
        }

    def _evaluate_l1(
        self,
        ts_code:    str,
        pool_code:  str,
        features:   dict[str, Any],
        asset_type: str,
        run_id:     str,
    ) -> tuple[str, list[dict[str, Any]]]:
        """L1 硬过滤状态机。返回 (status, reasons_list)。"""
        reasons: list[dict[str, Any]] = []

        def _r(reason_code: str, severity: str = "HARD",
               actual: float | None = None, threshold: float | None = None,
               message: str | None = None) -> dict[str, Any]:
            return {
                "run_id":          run_id,
                "ts_code":         ts_code,
                "pool_code":       pool_code,
                "stage":           STAGE_L1,
                "reason_code":     reason_code,
                "severity":        severity,
                "actual_value":    actual,
                "threshold_value": threshold,
                "message":         message,
            }

        # 1. 核心数据缺失
        if not features:
            reasons.append(_r(DATA_CORE_MISSING, message="features 数据完全缺失"))
            return STATUS_DATA_MISSING, reasons

        amount_ma20  = _float(features, "amount_ma20")
        history_days = _float(features, "history_days")
        if amount_ma20 == 0.0 and history_days == 0.0:
            reasons.append(_r(DATA_CORE_MISSING,
                              message="amount_ma20 和 history_days 均为 0，数据可能缺失"))
            return STATUS_DATA_MISSING, reasons

        # 2. ST 风险（仅股票）
        if self.config.exclude_st and asset_type == "stock":
            name = str(features.get("name") or "")
            if "ST" in name.upper():
                reasons.append(_r(L1_ST_RISK, message=f"股票名称含 ST：{name}"))
                return STATUS_FAIL, reasons

        # 3. 上市时间不足
        min_days = self.config.min_listing_trade_days
        if history_days < min_days:
            reasons.append(_r(
                L1_TOO_NEW,
                actual=history_days, threshold=float(min_days),
                message=f"上市交易日 {history_days:.0f} 不足 {min_days} 日",
            ))
            return STATUS_FAIL, reasons

        # 4. 流动性过低（仅股票）
        min_amount = self.config.min_median_amount_20_cny
        if asset_type == "stock" and amount_ma20 < min_amount:
            reasons.append(_r(
                L1_LOW_LIQUIDITY,
                actual=amount_ma20, threshold=min_amount,
                message=(f"20日均成交额 {amount_ma20/1e4:.0f}万 "
                         f"低于阈值 {min_amount/1e4:.0f}万"),
            ))
            return STATUS_FAIL, reasons

        # 5. 临时不可执行（一字涨停，DEFER 而非 FAIL）
        limit_status = str(features.get("limit_status") or "").upper()
        if asset_type == "stock" and limit_status == "U":
            reasons.append(_r(
                L1_TEMP_LIMITED, severity="SOFT",
                message="今日一字涨停，暂时不可执行",
            ))
            return STATUS_DEFER, reasons

        return STATUS_PASS, reasons

    def _execute_l2(
        self,
        run_id: str,
        trade_date: str,
        candidates: dict[str, dict[str, Any]],
        feature_map: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        """
        L2 质量复核。
        A池：结构修复/转向信号 + 下行风险控制（V1 技术因子，财务维度待 P4）
        B池：回调结构有效性 + 缩量回调 + 重站短均线 + 突破反弹高点
        C池：沿用通用简化版
        pass_score >= 60 → PASS；< 45 → FAIL；其余 WATCH（暂映射为 PASS）
        """
        snapshots: list[dict[str, Any]] = []
        reasons:   list[dict[str, Any]] = []
        counts: dict[str, int] = {STATUS_PASS: 0, STATUS_FAIL: 0}

        for ts_code, candidate in candidates.items():
            pool_code  = candidate["primary_pool"]
            features   = feature_map.get(ts_code) or {}

            if pool_code == "A":
                score, detail = self._l2_score_a(features)
            elif pool_code in ("A-Pre", "APRE"):
                score, detail = self._l2_score_a_pre(features)
            elif pool_code == "B":
                score, detail = self._l2_score_b(features)
            else:
                score, detail = self._l2_score_c(features)

            if score < self.config.l2_fail_score:
                status = STATUS_FAIL
                sub_msg = ""
                if pool_code == "A":
                    sub_msg = f"（分项得分: 结构转向 {detail.get('structure_turn', 0):.0f}/50分, 下行风控 {detail.get('downside_risk', 0):.0f}/30分, 防延伸 {detail.get('not_extended', 0):.0f}/20分）"
                elif pool_code in ("A-Pre", "APRE"):
                    sub_msg = f"（分项得分: 背景 {detail.get('background', 0):.0f}/15分, 减速 {detail.get('deceleration', 0):.0f}/25分, 底部 {detail.get('bottom_structure', 0):.0f}/20分, 波动收缩 {detail.get('volatility_contraction', 0):.0f}/15分）"
                elif pool_code == "B":
                    sub_msg = f"（分项得分: 结构 {detail.get('struct', 0):.0f}/25分, 缩量 {detail.get('shrink', 0):.0f}/15分, 站均线 {detail.get('ma_reclaim', 0):.0f}/15分, 突破 {detail.get('breakout', 0):.0f}/25分）"
                else:
                    sub_msg = f"（分项得分: 超跌 {detail.get('oversold', 0):.0f}/30分, 企稳 {detail.get('stabilize', 0):.0f}/55分, 反弹 {detail.get('rebound', 0):.0f}/15分）"

                reasons.append({
                    "run_id": run_id, "ts_code": ts_code, "pool_code": pool_code,
                    "stage": STAGE_L2, "reason_code": L2_QUALITY_LOW,
                    "severity": "HARD",
                    "actual_value": score, "threshold_value": self.config.l2_fail_score,
                    "message": f"L2质量分 {score:.1f} 不足 {self.config.l2_fail_score:.0f} 分 {sub_msg}",
                })
            else:
                status = STATUS_PASS

            counts[status] = counts.get(status, 0) + 1
            snapshots.append({
                "run_id": run_id, "ts_code": ts_code, "pool_code": pool_code,
                "stage": STAGE_L2, "status": status,
                "score": round(score, 2), "score_detail": detail,
            })

        return snapshots, reasons, counts

    def _l2_score_a(self, f: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        """
        A池 L2 质量分（技术维度版，财务维度 V1 暂缺，标注 DEFAULT_UNVALIDATED）。
        结构修复/转向(50%) + 下行风险(30%) + 不过度延伸(20%)
        """
        # ── 结构修复/转向（满分 50）────────────────────────────────────────
        turn = 0.0
        if _b(f, "higher_low"):
            turn += 15
        if _f(f, "ma20_slope_10") > 0:
            turn += 15
        if _f(f, "adj_close") > _f(f, "ma20"):
            turn += 10
        if _b(f, "break_last_swing_high") or _f(f, "adj_close") > _f(f, "prev_high_20"):
            turn += 10
        turn = min(turn, 50.0)

        # ── 下行风险（满分 30）─────────────────────────────────────────────
        # structural_stop 简化：收盘 > MA60 说明中期支撑有效
        risk = 0.0
        if _f(f, "adj_close") > _f(f, "ma60"):
            risk += 15
        atr_pct = _f(f, "atr_pct")
        if 0 < atr_pct < 0.06:          # ATR 不过大（波动可控）
            risk += 15
        elif 0 < atr_pct < 0.10:
            risk += 8
        risk = min(risk, 30.0)

        # ── 不过度延伸（满分 20）──────────────────────────────────────────
        ext = 20.0
        close_vs_ma20 = _f(f, "close_vs_ma20")
        if close_vs_ma20 > 0.20:
            ext = 0
        elif close_vs_ma20 > 0.12:
            ext = 8
        elif close_vs_ma20 > 0.06:
            ext = 14

        total = turn + risk + ext
        detail = {
            "structure_turn": round(turn, 2),
            "downside_risk":  round(risk, 2),
            "not_extended":   round(ext, 2),
            "total":          round(total, 2),
            "note": "财务维度 V1 暂缺，DEFAULT_UNVALIDATED",
        }
        return total, detail

    def _l2_score_a_pre(self, f: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        """
        A-Pre池 L2 质量分打分引擎（100分制）：
        背景(15) + 减速(25) + 底部结构(20) + 波动收缩(15) + 相对强度成交(15) + 临近启动(10)
        """
        bg = 0.0
        dd250 = _f(f, "drawdown_from_250d_high")
        pos250 = _f(f, "position_250")
        if dd250 <= -0.35:
            bg += 10
        elif dd250 <= -0.25:
            bg += 7
        if pos250 <= 0.30:
            bg += 5
        elif pos250 <= 0.40:
            bg += 3

        decel_score = 0.0
        s60 = _f(f, "slope_60")
        s20 = _f(f, "slope_20")
        s10 = _f(f, "slope_10")
        decel = _f(f, "deceleration")
        if s60 < 0:
            if decel >= 0.75:
                decel_score += 12
            elif decel >= 0.50:
                decel_score += 8
        if s20 >= 0:
            decel_score += 8
        if s10 > s20:
            decel_score += 5

        bottom_score = 0.0
        low_ratio = _f(f, "low_ratio")
        if low_ratio > 0.02:
            bottom_score += 20
        elif -0.02 <= low_ratio <= 0.02:
            bottom_score += 12
        elif -0.05 <= low_ratio < -0.02:
            bottom_score += 5

        vol_score = 0.0
        atr_r = _f(f, "atr_ratio")
        comp = _f(f, "compression")
        if 0 < atr_r < 0.70:
            vol_score += 8
        elif 0 < atr_r < 0.85:
            vol_score += 5
        if 0 < comp < 0.55:
            vol_score += 7
        elif 0 < comp < 0.70:
            vol_score += 4

        rs_score = 0.0
        vol_asym = _f(f, "volume_asymmetry")
        amt_r_5_20 = _f(f, "amount_ratio_5_20")
        ma60_imp = _f(f, "ma60_slope_improvement")
        if vol_asym >= 1.5:
            rs_score += 5
        elif vol_asym >= 1.2:
            rs_score += 3
        if 1.0 <= amt_r_5_20 <= 1.5:
            rs_score += 5
        elif amt_r_5_20 > 1.5:
            rs_score += 3
        if ma60_imp > 0:
            rs_score += 5

        break_score = 0.0
        dist_break = _f(f, "distance_to_breakout")
        if -0.08 <= dist_break <= 0.0:
            break_score += 10
        elif -0.15 <= dist_break < -0.08:
            break_score += 5
        elif dist_break > 0.0:
            break_score -= 10

        total = bg + decel_score + bottom_score + vol_score + rs_score + break_score
        detail = {
            "background":            round(bg, 2),
            "deceleration":          round(decel_score, 2),
            "bottom_structure":      round(bottom_score, 2),
            "volatility_contraction": round(vol_score, 2),
            "rs_and_volume":         round(rs_score, 2),
            "breakout_proximity":    round(break_score, 2),
            "total":                 round(total, 2),
        }
        return total, detail

    def _l2_score_b(self, f: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        """
        B池 L2 质量分（文档权重：回调结构25+缩量15+站均线15+突破高点25+量能10+不延伸10）
        """
        # 回调结构有效（25）
        struct = 0.0
        if _f(f, "adj_close") > _f(f, "ma120"):
            struct += 12
        atr_pct = _f(f, "atr_pct")
        swing_ok = _f(f, "break_swing_low_pct") >= -(atr_pct if atr_pct > 0 else 0.03)
        if swing_ok:
            struct += 13
        struct = min(struct, 25.0)

        # 回调缩量（15）
        vol_ratio = _f(f, "volume_ratio_5_20")
        shrink = 15.0 if vol_ratio < 0.8 else (10.0 if vol_ratio < 1.0 else 0.0)

        # 重新站回短均线（15）
        ma_reclaim = 0.0
        if _f(f, "adj_close") > _f(f, "ma20"):
            ma_reclaim += 10
        if _f(f, "ma20_slope_10") >= 0:
            ma_reclaim += 5
        ma_reclaim = min(ma_reclaim, 15.0)

        # 突破短期反弹高点（25）
        breakout = 0.0
        if _b(f, "break_10"):
            breakout = 25
        elif _b(f, "break_5"):
            breakout = 15
        elif _b(f, "break_last_swing_high"):
            breakout = 20

        # 恢复量能（10）
        vol_today = _f(f, "today_volume_ratio_20")
        volume_ok = 10.0 if vol_today > 1.2 else (6.0 if vol_today > 1.0 else 0.0)

        # 不过度延伸（10）
        ext = 10.0
        if _f(f, "close_vs_ma20") > 0.15:
            ext = 0
        elif _f(f, "close_vs_ma20") > 0.08:
            ext = 5

        total = struct + shrink + ma_reclaim + breakout + volume_ok + ext
        total = min(total, 100.0)
        detail = {
            "pullback_structure": round(struct, 2),
            "volume_shrink":      round(shrink, 2),
            "ma_reclaim":         round(ma_reclaim, 2),
            "breakout":           round(breakout, 2),
            "volume_recovery":    round(volume_ok, 2),
            "not_extended":       round(ext, 2),
            "total":              round(total, 2),
        }
        return total, detail

    def _l2_score_c(self, f: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        """C池 L2：简化版通用质量分（超跌+企稳）"""
        oversold = 0.0
        if _f(f, "rsi14_min_5") <= 35:
            oversold += 30
        elif _f(f, "rsi14_min_5") <= 45:
            oversold += 15

        stabilize = 0.0
        if _b(f, "low_3_not_falling") or _b(f, "low_5_not_falling"):
            stabilize += 25
        if _f(f, "volume_ratio_5_20") < 1.0:
            stabilize += 15
        if _f(f, "adj_close") > _f(f, "ma5"):
            stabilize += 15

        rebound = 0.0
        if _b(f, "break_5") or _b(f, "break_10"):
            rebound += 15

        total = min(oversold + stabilize + rebound, 100.0)
        detail = {
            "oversold":  round(oversold, 2),
            "stabilize": round(stabilize, 2),
            "rebound":   round(rebound, 2),
            "total":     round(total, 2),
        }
        return total, detail

    def _execute_l3(
        self,
        run_id: str,
        trade_date: str,
        passed_codes: set[str],
        candidate_map: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        """
        L3 横截面 RS 排名。
        对 L2 PASS 的股票，计算 RS60 全市场 / 池内 / 申万二级行业内百分位。
        rank_all >= l3_pass_score% → PASS；< l3_fail_score% → FAIL
        """
        from backend.screening.rs_engine import RSEngine, FACTOR_VERSION

        snapshots: list[dict[str, Any]] = []
        reasons:   list[dict[str, Any]] = []
        counts: dict[str, int] = {STATUS_PASS: 0, STATUS_FAIL: 0}

        if not passed_codes:
            return snapshots, reasons, counts

        # 构建 pool_map（仅传入 L2 PASS 的股票）
        pool_map = {
            code: candidate_map[code]["primary_pool"]
            for code in passed_codes if code in candidate_map
        }

        # 计算并持久化 RS 因子（会写入 factor_snapshot）
        engine = RSEngine(
            store=self.store,
            min_industry_members=self.config.min_industry_members,
            persist_factors=True,
        )
        engine.compute_and_save(
            trade_date=trade_date,
            industry_source_version=self.config.industry_source_version,
            pool_map=pool_map,
        )

        # 加载刚计算的 RS60 全市场排名
        rs_df = engine.load_rs_for_date(trade_date, ts_codes=list(passed_codes))

        rs_col = f"rs{self.config.l3_primary_window}_rank_all"  # rs60_rank_all

        for code in passed_codes:
            candidate = candidate_map.get(code, {})
            pool_code = candidate.get("primary_pool", "A")

            # 取全市场 RS60 百分位（0-1），转成 0-100 分
            rank_pct = None
            if not rs_df.empty and code in rs_df.index and rs_col in rs_df.columns:
                v = rs_df.loc[code, rs_col]
                if v is not None and not (v != v):  # not NaN
                    rank_pct = float(v)

            if rank_pct is None:
                # 因子缺失，视为 DATA_MISSING，给中间分通过
                score = 50.0
                status = STATUS_PASS
            else:
                score = round(rank_pct * 100, 2)
                if score < self.config.l3_fail_score:
                    status = STATUS_FAIL
                    reasons.append({
                        "run_id": run_id, "ts_code": code, "pool_code": pool_code,
                        "stage": STAGE_L3, "reason_code": L3_STRENGTH_LOW,
                        "severity": "HARD",
                        "actual_value": score,
                        "threshold_value": self.config.l3_fail_score,
                        "message": f"RS60 相对强度百分位 {score:.1f}% 属于弱势股（低于前 {self.config.l3_fail_score:.0f}% 淘汰门槛）",
                    })
                else:
                    status = STATUS_PASS

            counts[status] = counts.get(status, 0) + 1
            snapshots.append({
                "run_id":   run_id,
                "ts_code":  code,
                "pool_code": pool_code,
                "stage":    STAGE_L3,
                "status":   status,
                "score":    score,
                "score_detail": {"rs60_rank_all_pct": score},
            })

        return snapshots, reasons, counts

    def _execute_l4(
        self,
        run_id: str,
        trade_date: str,
        passed_codes: set[str],
        candidate_map: dict[str, dict[str, Any]],
        feature_map: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        """
        L4 触发时机评估。
        评估已通过 L3 的股票当前是否达到具体买入/入场条件（READY / WATCH / OVEREXTENDED）。
        """
        snapshots: list[dict[str, Any]] = []
        reasons:   list[dict[str, Any]] = []
        counts: dict[str, int] = {STATUS_PASS: 0, STATUS_FAIL: 0}

        for code in passed_codes:
            candidate = candidate_map.get(code, {})
            pool_code = candidate.get("primary_pool", "A")
            f = feature_map.get(code) or {}

            score, status, detail, reason_item = self._evaluate_l4_stock(code, pool_code, f, run_id)

            if status in (STATUS_READY, STATUS_PASS):
                counts[STATUS_PASS] = counts.get(STATUS_PASS, 0) + 1
                snap_status = STATUS_PASS
            else:
                counts[STATUS_FAIL] = counts.get(STATUS_FAIL, 0) + 1
                snap_status = STATUS_FAIL

            snapshots.append({
                "run_id": run_id, "ts_code": code, "pool_code": pool_code,
                "stage": STAGE_L4, "status": snap_status,
                "score": round(score, 2), "score_detail": detail,
            })
            if reason_item:
                reasons.append(reason_item)

        return snapshots, reasons, counts

    def _evaluate_l4_stock(
        self, code: str, pool_code: str, f: dict[str, Any], run_id: str
    ) -> tuple[float, str, dict[str, Any], dict[str, Any] | None]:
        atr_pct = _f(f, "atr_pct") or 0.03
        close = _f(f, "adj_close")
        ma20 = _f(f, "ma20")
        close_vs_ma20 = _f(f, "close_vs_ma20")

        atr_dist = (close - ma20) / (close * atr_pct) if (close * atr_pct) > 0 else 0.0
        is_overextended = atr_dist > self.config.l4_max_extension_atr or close_vs_ma20 > 0.15

        if pool_code == "A":
            trigger_score = 0.0
            if _b(f, "higher_low"):
                trigger_score += 30
            if _f(f, "adj_close") > _f(f, "ma20"):
                trigger_score += 30
            if _b(f, "break_5") or _b(f, "break_10") or _b(f, "break_last_swing_high"):
                trigger_score += 40
        elif pool_code in ("A-Pre", "APRE"):
            trigger_score = 0.0
            dist_break = _f(f, "distance_to_breakout")
            if -0.08 <= dist_break <= 0.0:
                trigger_score += 40
            elif -0.15 <= dist_break < -0.08:
                trigger_score += 25
            if _f(f, "deceleration") >= 0.75:
                trigger_score += 30
            if _f(f, "low_ratio") >= -0.02:
                trigger_score += 30
        elif pool_code == "B":
            trigger_score = 0.0
            if _f(f, "adj_close") > _f(f, "ma5"):
                trigger_score += 25
            if _f(f, "adj_close") > _f(f, "ma20"):
                trigger_score += 25
            if _b(f, "break_5") or _b(f, "break_10"):
                trigger_score += 30
            if _f(f, "today_volume_ratio_20") > 1.0 or _f(f, "volume_ratio_5_20") < 0.9:
                trigger_score += 20
        else:
            trigger_score = 0.0
            if _f(f, "rsi14_min_5") <= 40:
                trigger_score += 35
            if _f(f, "adj_close") > _f(f, "ma5"):
                trigger_score += 35
            if _b(f, "break_5"):
                trigger_score += 30

        detail = {
            "trigger_score": round(trigger_score, 2),
            "atr_dist": round(atr_dist, 2),
            "close_vs_ma20": round(close_vs_ma20, 4),
            "is_overextended": is_overextended,
        }

        reason_item = None
        if is_overextended:
            status = STATUS_OVEREXTENDED
            reason_item = {
                "run_id": run_id, "ts_code": code, "pool_code": pool_code,
                "stage": STAGE_L4, "reason_code": L4_OVEREXTENDED,
                "severity": "HARD",
                "actual_value": round(atr_dist, 2),
                "threshold_value": self.config.l4_max_extension_atr,
                "message": f"短线急拉偏离过多 (偏离 {atr_dist:.1f} ATR > 门槛 {self.config.l4_max_extension_atr} ATR)，属于 OVEREXTENDED 追高风险",
            }
        elif trigger_score >= self.config.l4_ready_score:
            status = STATUS_READY
        else:
            status = STATUS_WATCH
            reason_item = {
                "run_id": run_id, "ts_code": code, "pool_code": pool_code,
                "stage": STAGE_L4, "reason_code": L4_NOT_READY,
                "severity": "HARD",
                "actual_value": round(trigger_score, 2),
                "threshold_value": self.config.l4_ready_score,
                "message": f"L4触发时机得分 {trigger_score:.1f} 未达到 READY 门槛 {self.config.l4_ready_score}，属于 WATCH 观察阶段",
            }

        return trigger_score, status, detail, reason_item

    def _execute_l5(
        self,
        run_id: str,
        trade_date: str,
        evaluated_codes: set[str],
        candidate_map: dict[str, dict[str, Any]],
        feature_map: dict[str, dict[str, Any]],
        l2_snapshots: list[dict[str, Any]],
        l3_snapshots: list[dict[str, Any]],
        l4_snapshots: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        """
        L5 综合机会排名 (Opportunity Ranking)。
        综合 L2 质量分 + L3 相对强度分 + L4 触发分 + 行业/风险分，计算 Opportunity Score (0~100)。
        """
        snapshots: list[dict[str, Any]] = []
        reasons:   list[dict[str, Any]] = []
        counts: dict[str, int] = {STATUS_PASS: 0, STATUS_FAIL: 0}

        l2_map = {s["ts_code"]: s for s in l2_snapshots}
        l3_map = {s["ts_code"]: s for s in l3_snapshots}
        l4_map = {s["ts_code"]: s for s in l4_snapshots}

        for code in evaluated_codes:
            candidate = candidate_map.get(code, {})
            pool_code = candidate.get("primary_pool", "A")

            l2_score = l2_map.get(code, {}).get("score") or 60.0
            l3_score = l3_map.get(code, {}).get("score") or 60.0
            l4_snap  = l4_map.get(code, {})
            l4_score = l4_snap.get("score") or 50.0
            l4_status = l4_snap.get("status")

            if pool_code == "A":
                opp_score = (l2_score * 0.20) + (l3_score * 0.20) + (l4_score * 0.25) + (65.0 * 0.15) + (70.0 * 0.15) + (60.0 * 0.05)
            elif pool_code == "B":
                opp_score = (l2_score * 0.25) + (l3_score * 0.20) + (l4_score * 0.20) + (65.0 * 0.15) + (70.0 * 0.15) + (60.0 * 0.05)
            else:
                opp_score = (l2_score * 0.20) + (l3_score * 0.20) + (l4_score * 0.30) + (65.0 * 0.15) + (70.0 * 0.15)

            opp_score = round(opp_score, 2)
            detail = {
                "l2_quality_weight": "20-25%",
                "l3_rs_weight": "20%",
                "l4_trigger_weight": "20-30%",
                "opportunity_score": opp_score,
            }

            if l4_status == STATUS_PASS and opp_score >= self.config.l5_opportunity_min_score:
                status = STATUS_PASS
            else:
                status = STATUS_FAIL
                reasons.append({
                    "run_id": run_id, "ts_code": code, "pool_code": pool_code,
                    "stage": STAGE_L5, "reason_code": L5_SCORE_LOW,
                    "severity": "HARD",
                    "actual_value": opp_score,
                    "threshold_value": self.config.l5_opportunity_min_score,
                    "message": f"L5 综合机会得分 {opp_score:.1f} 未达到推荐门槛 {self.config.l5_opportunity_min_score} 分",
                })

            counts[status] = counts.get(status, 0) + 1
            snapshots.append({
                "run_id":   run_id,
                "ts_code":  code,
                "pool_code": pool_code,
                "stage":    STAGE_L5,
                "status":   status,
                "score":    opp_score,
                "score_detail": detail,
            })

        return snapshots, reasons, counts

    def _load_l0_candidates(self, trade_date: str) -> list[dict[str, Any]]:
        """从现有 screening_candidate_snapshot 读取当日 A/B/C 候选（作为 L0 输入）"""
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                select s.asset_code, s.asset_type, s.primary_pool,
                       s.stage, s.score, a.name
                from screening_candidate_snapshot s
                left join screening_asset_master a on a.asset_code = s.asset_code
                where s.trade_date = %s
                order by s.primary_pool, s.asset_code
                """,
                (trade_date,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _load_features(self, trade_date: str) -> dict[str, dict[str, Any]]:
        """加载 L1 所需因子（来自 screening_technical_features + daily_basic + asset_master）"""
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                select f.asset_code,
                       f.features_json,
                       d.limit_status,
                       a.name,
                       a.list_date
                from screening_technical_features f
                left join screening_daily_basic d
                    on d.asset_code = f.asset_code and d.trade_date = %s
                left join screening_asset_master a
                    on a.asset_code = f.asset_code
                where f.trade_date = %s
                order by f.asset_code
                """,
                (trade_date, trade_date),
            ).fetchall()

        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            features: dict[str, Any] = dict(row.get("features_json") or {})
            features["name"]         = row.get("name")
            features["list_date"]    = row.get("list_date")
            features["limit_status"] = row.get("limit_status")
            result[row["asset_code"]] = features
        return result


# ── 工具函数 ───────────────────────────────────────────────────────────────────

def _make_run_id(trade_date: str) -> str:
    return f"{trade_date}_{uuid.uuid4().hex[:8]}"


def _float(features: dict[str, Any], key: str) -> float:
    """简写 alias，供内部用。"""
    val = features.get(key)
    if val is None:
        return 0.0
    return float(val)


# 在 L2/L3 评分方法中使用的简写
_f = _float


def _b(features: dict[str, Any], key: str) -> bool:
    """从 features 取布尔值。"""
    return bool(features.get(key))
