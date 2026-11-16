"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { TradingPageKey } from "./types";
import KLineModal from "../KLineModal";
import { ActionPlanDialog } from "../TradePlansPage";
import { canEditTradePlan } from "./common/tradingData";
import { orderTypeLabel } from "./orderTypes";

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;

type AnyRecord = Record<string, any>;
type PageProps = { accountId: number; tradeId: number | null; planId?: number | null; onNavigate: (page: TradingPageKey, tradeId?: number, planId?: number) => void; onRefresh?: () => void };

function money(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—";
}
function numberLabel(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN") : "—";
}
function dateLabel(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN");
}
function statusLabel(value: unknown) {
  return ({ DRAFT: "草稿", READY: "已确认，待安排执行", ARMED: "执行中", PARTIALLY_EXECUTED: "部分成交", EXECUTED: "已成交", INVALIDATED: "已失效", ACTIVE: "持仓中", PLANNED: "计划中", CLOSING: "清仓中", CLOSED: "已结束", COMPLETED: "已完成", FAILED: "失败", PENDING_SUBMIT: "等待发送", QUEUED: "排队中", SUBMITTED: "委托已发送", ACCEPTED: "委托已接受", PARTIALLY_FILLED: "部分成交", FILLED: "已成交", CANCEL_PENDING: "撤单中", CANCELLED: "已取消", CANCELED: "已取消", REJECTED: "委托被拒绝", EXPIRED: "已过期", PAUSED: "已暂停，待检查" } as Record<string, string>)[String(value)] || String(value || "状态未记录");
}
function actionLabel(value: unknown) {
  return ({ OPEN: "建仓", ADD: "加仓", REDUCE: "减仓", CLOSE: "清仓" } as Record<string, string>)[String(value)] || "动作";
}
function sideLabel(value: unknown) {
  return ({ BUY: "买入", SELL: "卖出" } as Record<string, string>)[String(value)] || String(value || "—");
}
function executionTypeLabel(value: unknown) {
  return ({ LIMIT: "立即提交限价单", PERSISTENT_LIMIT: "持续限价（旧方案）", PRICE_TRIGGER: "达到价格后提交限价单", PRICE_RANGE: "进入价格区间后提交限价单" } as Record<string, string>)[String(value)] || String(value || "执行方式未记录");
}

async function readJson(path: string, accountId: number, init?: RequestInit) {
  if (!API_BASE) throw new Error("交易服务配置不可用，请联系管理员");
  const response = await fetch(`${API_BASE}${path}${path.includes("?") ? "&" : "?"}account_id=${encodeURIComponent(String(accountId))}`, { ...init, cache: "no-store" });
  if (!response.ok) throw new Error(`交易数据读取失败（HTTP ${response.status}）`);
  return response.json();
}

function PageState({ loading, error, onRetry }: { loading: boolean; error: string | null; onRetry: () => void }) {
  if (loading) return <div className="trading-page-state">正在读取交易数据…</div>;
  if (error) return <div className="trading-page-state trading-page-state-error"><strong>{error}</strong><button type="button" onClick={onRetry}>重新读取</button></div>;
  return null;
}

function PageFrame({ title, eyebrow, actions, children }: { title: string; eyebrow: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return <div className="trading-react-page"><header className="trading-react-page-header"><div><small>{eyebrow}</small><h1>{title}</h1></div><div className="trading-react-page-actions">{actions}</div></header>{children}</div>;
}

function Metric({ label, value, detail }: { label: string; value: React.ReactNode; detail?: React.ReactNode }) {
  return <div className="trading-metric"><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>;
}

function Table({ headers, children }: { headers: string[]; children: React.ReactNode }) {
  return <div className="trading-data-table"><table><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{children}</tbody></table></div>;
}

export function TradeDetailPage({ accountId, tradeId, onNavigate, onRefresh }: PageProps) {
  const [detail, setDetail] = useState<AnyRecord | null>(null);
  const [position, setPosition] = useState<AnyRecord | null>(null);
  const [rules, setRules] = useState<AnyRecord[]>([]);
  const [riskHistory, setRiskHistory] = useState<AnyRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showKline, setShowKline] = useState(false);
  const load = useCallback(async () => {
    if (tradeId === null) { setError("当前页面缺少 Trade 上下文，请从交易列表进入"); setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const [trade, state, exitRules, history] = await Promise.all([
        readJson(`/api/trades/${tradeId}`, accountId), readJson(`/api/trades/${tradeId}/position-state`, accountId),
        readJson(`/api/trades/${tradeId}/exit-rules`, accountId), readJson(`/api/trades/${tradeId}/risk-reference-history`, accountId),
      ]);
      if (!trade.item || Number(trade.item.id) !== tradeId) throw new Error("Trade 数据校验失败，请刷新后重试");
      const normalizedTrade = {
        ...trade.item,
        legs: Array.isArray(trade.item.legs)
          ? trade.item.legs.map((leg: AnyRecord) => ({
            ...leg,
            action_type: actionLabel(leg.action_type ?? leg.leg_type),
            planned_qty: leg.planned_qty ?? leg.entry_qty,
          }))
          : trade.item.legs,
      };
      setDetail(normalizedTrade); setPosition(state.item || state.position || null); setRules(Array.isArray(exitRules.items) ? exitRules.items : []); setRiskHistory(Array.isArray(history.items) ? history.items : []);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Trade 详情读取失败"); } finally { setLoading(false); }
  }, [accountId, tradeId]);
  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);
  const trade = detail;
  const legs = Array.isArray(trade?.legs) ? trade.legs : [];
  const risk = legs.reduce((summary, leg: AnyRecord) => {
    const quantity = Number(leg.remaining_qty); const entry = Number(leg.actual_avg_entry_price ?? leg.planned_entry_price); const reference = Number(leg.current_risk_reference_price ?? leg.initial_risk_reference_price); const market = Number(position?.market_price);
    if (![quantity, entry, reference].every(Number.isFinite) || quantity <= 0) return summary;
    return { capital: summary.capital + Math.max(0, entry - reference) * quantity, giveback: summary.giveback + (Number.isFinite(market) ? Math.max(0, market - reference) * quantity : 0), valid: summary.valid + 1 };
  }, { capital: 0, giveback: 0, valid: 0 });
  const positionQty = Number(position?.position_qty);
  const availableQty = Number(position?.available_qty);
  const averageCost = Number(position?.avg_cost);
  const marketPrice = Number(position?.market_price);
  const unrealizedPnl = [positionQty, averageCost, marketPrice].every(Number.isFinite)
    ? (marketPrice - averageCost) * positionQty
    : null;
  const active = trade && ["ACTIVE", "CLOSING"].includes(String(trade.status));
  const timeline = trade ? [{ label: "Trade 创建", time: trade.created_at, detail: "交易记录已建立" }, ...(Array.isArray(trade.plans) ? trade.plans.map((plan: AnyRecord) => ({ label: `${actionLabel(plan.action_type || plan.action)} #${plan.sequence_no ?? "—"}`, time: plan.updated_at || plan.created_at, detail: `动作计划${statusLabel(plan.status)}` })) : []), { label: "当前状态", time: trade.updated_at || trade.created_at, detail: statusLabel(trade.status) }] : [];
  return <PageFrame title="Trade 详情" eyebrow="交易生命周期 / TRADE DETAIL" actions={<><button type="button" onClick={() => onNavigate("trades")}>返回交易列表</button><button type="button" onClick={() => setShowKline(true)} disabled={!trade?.symbol}>查看 K 线</button>{active && <><button type="button" onClick={() => onNavigate("add", tradeId || undefined)}>加仓</button><button type="button" onClick={() => onNavigate("risk", tradeId || undefined)}>调风控</button><button type="button" onClick={() => onNavigate("close", tradeId || undefined)}>清仓</button></>}<button type="button" onClick={() => { void load(); onRefresh?.(); }}>刷新</button></>}>
    <PageState loading={loading} error={error} onRetry={() => void load()} />
    {trade && <><section className="trading-detail-hero"><div><small className="trading-phase-label">{trade.status === "CLOSED" ? "PHASE · SETTLEMENT" : "PHASE · ACTIVE TRADE"}</small><span className="trading-symbol-name">{trade.symbol_name || "未命名标的"}</span><code>{trade.symbol || "—"}</code><p>{trade.playbook || "未设置 Playbook"}</p></div><div className="trading-status-pill">{statusLabel(trade.status)}</div></section><section className="trading-metric-grid"><Metric label="交易类型" value={String(trade.trade_type || "—")} detail={trade.playbook || "未设置策略"} /><Metric label="当前持仓" value={`${numberLabel(positionQty)} 股`} detail={`可卖 ${numberLabel(availableQty)} · T+1 ${numberLabel(Number.isFinite(positionQty) && Number.isFinite(availableQty) ? positionQty - availableQty : null)}`} /><Metric label="现价 / 成本" value={money(marketPrice)} detail={`平均成本 ${money(averageCost)}`} /><Metric label="浮动盈亏" value={money(unrealizedPnl)} detail={dateLabel(position?.updated_at || trade.updated_at || trade.created_at)} /></section><section className="trading-risk-summary"><div><span>风险控制与腿部归因</span><strong>{risk.valid ? money(risk.capital) : "—"}</strong><small>实际承担本金计划风险</small></div><div><span>利润回吐风险</span><strong>{risk.valid ? money(risk.giveback) : "—"}</strong><small>按当前风险参考与行情计算</small></div><div><span>关联分腿</span><strong>{legs.length} 条</strong><small>{risk.valid ? "数据完整" : "风险数据不完整"}</small></div></section><div className="trading-detail-grid"><section className="trading-panel"><div className="trading-panel-title"><h2>TradeLeg 交易分腿明细</h2><span>{legs.length} 条</span></div><Table headers={["分腿", "计划数量", "剩余数量", "入场价", "当前风控基准", "状态"]}>{legs.map((leg: AnyRecord, index: number) => <tr key={String(leg.id ?? index)}><td><strong>{leg.action_type || `Leg ${index + 1}`}</strong><small>{leg.source || "交易动作记录"}</small></td><td>{numberLabel(leg.planned_qty ?? leg.planned_quantity)}</td><td>{numberLabel(leg.remaining_qty)}</td><td>{money(leg.actual_avg_entry_price ?? leg.planned_entry_price)}</td><td>{money(leg.current_risk_reference_price ?? leg.initial_risk_reference_price)}</td><td>{statusLabel(leg.status || trade.status)}</td></tr>)}</Table></section><section className="trading-panel"><div className="trading-panel-title"><h2>退出规则</h2><span>{rules.length} 条</span></div>{rules.length ? <ul className="trading-audit-list">{rules.map((rule) => <li key={String(rule.id)}><strong>{rule.trigger_type || "触发条件"}</strong><span>{rule.enabled === false ? "已停用" : "已启用"}</span><small>{rule.notes || "未填写说明"}</small></li>)}</ul> : <div className="trading-empty">当前 Trade 暂无退出规则。</div>}<div className="trading-panel-title trading-panel-title-spaced"><h2>风险参考变更</h2><span>{riskHistory.length} 条记录</span></div>{riskHistory.length ? <ul className="trading-audit-list">{riskHistory.slice(0, 5).map((item) => <li key={String(item.id)}><strong>{money(item.new_price ?? item.risk_reference_price)}</strong><span>{dateLabel(item.created_at)}</span><small>{item.reason || "未填写原因"}</small></li>)}</ul> : <div className="trading-empty">暂无风险参考变更记录。</div>}</section></div><section className="trading-panel trading-timeline-panel"><div className="trading-panel-title"><h2>Trade 生命周期时间线</h2><span>{timeline.length} 个节点</span></div><ol className="trading-timeline">{timeline.map((item) => <li key={`${item.label}-${item.time || ""}`}><span className="trading-timeline-node" /><div><strong>{item.label}</strong><small>{item.detail}</small></div><time>{dateLabel(item.time)}</time></li>)}</ol></section></>}
    {showKline && trade?.symbol && <KLineModal assetCode={String(trade.symbol)} assetName={String(trade.symbol_name || trade.symbol)} isOpen={true} onClose={() => setShowKline(false)} />}
  </PageFrame>;
}

export function RiskReferencePage({ accountId, tradeId, onNavigate, onRefresh }: PageProps) {
  const [detail, setDetail] = useState<AnyRecord | null>(null); const [position, setPosition] = useState<AnyRecord | null>(null); const [history, setHistory] = useState<AnyRecord[]>([]); const [value, setValue] = useState(""); const [reason, setReason] = useState(""); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(true); const [saving, setSaving] = useState(false); const [showKline, setShowKline] = useState(false);
  const load = useCallback(async () => { if (tradeId === null) { setError("当前页面缺少 Trade 上下文，请先选择交易"); setLoading(false); return; } setLoading(true); setError(null); try { const [trade, state, result] = await Promise.all([readJson(`/api/trades/${tradeId}`, accountId), readJson(`/api/trades/${tradeId}/position-state`, accountId), readJson(`/api/trades/${tradeId}/risk-reference-history`, accountId)]); if (!trade.item) throw new Error("Trade 数据不存在"); const rawPosition = state.item || state.position || null; const normalizedPosition = rawPosition ? { ...rawPosition, quantity: rawPosition.quantity ?? rawPosition.position_qty, available_quantity: rawPosition.available_quantity ?? rawPosition.available_qty, average_cost: rawPosition.average_cost ?? rawPosition.avg_cost } : null; const normalizedTrade = { ...trade.item, legs: Array.isArray(trade.item.legs) ? trade.item.legs.map((leg: AnyRecord) => ({ ...leg, action_type: actionLabel(leg.action_type ?? leg.leg_type) })) : trade.item.legs }; setDetail(normalizedTrade); setPosition(normalizedPosition); setHistory(Array.isArray(result.items) ? result.items : []); setValue(trade.item.position_risk_reference_price ? String(trade.item.position_risk_reference_price) : ""); } catch (cause) { setError(cause instanceof Error ? cause.message : "风险参考读取失败"); } finally { setLoading(false); } }, [accountId, tradeId]);
  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);
  async function save() { if (tradeId === null || !value.trim() || !Number.isFinite(Number(value)) || Number(value) <= 0) { setError("请输入有效的风险参考价"); return; } setSaving(true); setError(null); try { await readJson(`/api/trades/${tradeId}/risk-reference`, accountId, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ new_price: Number(value), reason: reason.trim() || undefined }) }); setReason(""); await load(); onRefresh?.(); } catch (cause) { setError(cause instanceof Error ? cause.message : "风险参考保存失败"); } finally { setSaving(false); } }
  const current = Number(position?.market_price); const cost = Number(position?.average_cost); const target = Number(value); const distance = Number.isFinite(current) && Number.isFinite(target) && current > 0 ? `${((current - target) / current * 100).toFixed(2)}%` : "—";
  const original = Number(detail?.position_risk_reference_price); const proposed = Number(target); const referenceDelta = Number.isFinite(original) && Number.isFinite(proposed) && original > 0 ? `${((proposed - original) / original * 100).toFixed(2)}%` : "—";
  return <PageFrame title="风险参考" eyebrow="交易风控 / RISK REFERENCE" actions={<><button type="button" onClick={() => onNavigate("trade", tradeId || undefined)}>返回 Trade</button><button type="button" onClick={() => setShowKline(true)} disabled={!detail?.symbol}>查看 K 线</button></>}><PageState loading={loading} error={error} onRetry={() => void load()} />{detail && <><section className="trading-detail-hero"><div><span className="trading-symbol-name">{detail.symbol_name || detail.symbol}</span><code>{detail.symbol || "—"}</code><p>{detail.playbook || detail.trade_type || "Trade"} · {statusLabel(detail.status)}</p></div><div className="trading-status-pill">风险调整写入审计记录</div></section><section className="trading-metric-grid"><Metric label="当前市价" value={money(position?.market_price)} detail="来自当前持仓快照" /><Metric label="原风险参考" value={money(detail.position_risk_reference_price)} detail="当前 Trade 基准" /><Metric label="新防守建议线" value={money(target)} detail={`距现价 ${distance}`} /><Metric label="平均成本" value={money(position?.average_cost)} detail={Number.isFinite(cost) ? "保本线参考" : "成本数据不可用"} /></section><section className="risk-comparison-grid"><div><span>参考线变化</span><strong>{referenceDelta}</strong><small>{money(original)} → {money(proposed)}</small></div><div><span>距现价空间</span><strong>{distance}</strong><small>新防守建议线与当前市价比较</small></div><div><span>关联分腿</span><strong>{Array.isArray(detail.legs) ? detail.legs.length : "—"}</strong><small>调整将写入 Trade 风险审计</small></div><div><span>调整状态</span><strong>{saving ? "保存中" : "待确认"}</strong><small>确认后才会提交真实变更</small></div></section><div className="trading-detail-grid"><section className="trading-panel"><div className="trading-panel-title"><h2>调整风险参考</h2><span>{detail.symbol_name || detail.symbol}</span></div><div className="trading-form-grid"><label>新风险参考价 *<input value={value} onChange={(event) => setValue(event.target.value)} inputMode="decimal" placeholder="输入防守基准价" /></label><label>调整依据<textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="说明调整风险参考的业务原因，用于风控日志与复盘归因" /></label></div><div className="risk-quick-values"><button type="button" onClick={() => setValue(Number.isFinite(current) ? current.toFixed(2) : "")}>现价 {money(current)}</button><button type="button" onClick={() => setValue(Number.isFinite(cost) ? cost.toFixed(2) : "")}>保本线 {money(cost)}</button></div><div className="trading-form-actions"><button type="button" onClick={() => void save()} disabled={saving}>{saving ? "保存中…" : "确认调整"}</button></div></section><section className="trading-panel"><div className="trading-panel-title"><h2>分腿影响预览</h2><span>{Array.isArray(detail.legs) ? detail.legs.length : 0} 条</span></div>{Array.isArray(detail.legs) && detail.legs.length ? <ul className="trading-audit-list">{detail.legs.map((leg: AnyRecord, index: number) => <li key={String(leg.id ?? index)}><strong>{leg.action_type || `Leg ${index + 1}`}</strong><span>{numberLabel(leg.remaining_qty)} 股</span><small>原参考 {money(leg.current_risk_reference_price ?? leg.initial_risk_reference_price)} · 新参考 {money(proposed)}</small></li>)}</ul> : <div className="trading-empty">当前没有可展示的分腿风险数据。</div>}<div className="trading-panel-title trading-panel-title-spaced"><h2>调整记录</h2><span>{history.length} 条</span></div><ul className="trading-audit-list">{history.length ? history.map((item) => <li key={String(item.id)}><strong>{money(item.new_price ?? item.risk_reference_price)}</strong><span>{dateLabel(item.created_at)}</span><small>{item.reason || "未填写原因"}</small></li>) : <li className="trading-empty">暂无调整记录。</li>}</ul></section></div></>}{showKline && detail?.symbol && <KLineModal assetCode={String(detail.symbol)} assetName={String(detail.symbol_name || detail.symbol)} isOpen={true} onClose={() => setShowKline(false)} />}</PageFrame>;
}

export function ActionPage({ mode, accountId, tradeId, planId, onNavigate, onRefresh }: PageProps & { mode: "ADD" | "REDUCE" | "CLOSE" }) {
  const [trade, setTrade] = useState<AnyRecord | null>(null); const [draftPlan, setDraftPlan] = useState<AnyRecord | null>(null); const [initialValues, setInitialValues] = useState<AnyRecord | undefined>(); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(true);
  const load = useCallback(async () => { if (tradeId === null) { setError("当前动作缺少 Trade 上下文，请从 Trade 列表进入"); setLoading(false); return; } setLoading(true); try { const result = await readJson(`/api/trades/${tradeId}`, accountId); if (!result.item) throw new Error("Trade 数据不存在"); setTrade(result.item); if (planId !== null && planId !== undefined) { const planResult = await readJson(`/api/trade-plans/${planId}`, accountId); const plan = planResult.item; if (!plan || Number(plan.trade_id) !== tradeId || !canEditTradePlan(plan)) throw new Error("这条动作计划已有执行安排或成交记录，当前不能修改"); const input = plan.input_json || {}; setDraftPlan(plan); setInitialValues({ referencePrice: String(input.reference_price ?? ""), riskPrice: String(input.risk_reference_price ?? ""), quantity: String(input.manual_quantity ?? input.quantity ?? ""), minimumPrice: String(input.minimum_acceptable_price ?? ""), triggerCondition: String(input.trigger_condition ?? ""), reasonText: String(input.reason_text ?? ""), reasonCode: String(input.reason_code ?? "CUSTOM"), failureHandling: String(input.failure_handling ?? "EXIT_ADDED_QTY_ONLY"), failureTargetQty: String(input.failure_target_qty ?? ""), failureTargetPct: input.failure_target_pct == null ? "" : String(Number(input.failure_target_pct) * 100), actionRiskBudget: String(input.action_risk_budget_amount ?? ""), riskMode: String(input.risk_management_mode ?? "INDEPENDENT"), unifiedRiskReference: String(input.unified_risk_reference_price ?? ""), reduceMethod: String(input.reduce_method ?? "FIXED_QTY"), positionPct: input.position_pct == null ? "" : String(Number(input.position_pct) * 100), targetRemainingQty: String(input.target_remaining_qty ?? ""), targetRemainingPct: input.target_remaining_pct == null ? "" : String(Number(input.target_remaining_pct) * 100), residualMode: String(input.residual_mode ?? "KEEP"), residualRiskReference: String(input.residual_risk_reference_price ?? "") }); } else { setDraftPlan(null); setInitialValues(undefined); } } catch (cause) { setError(cause instanceof Error ? cause.message : "Trade 读取失败"); } finally { setLoading(false); } }, [accountId, planId, tradeId]);
  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);
  if (loading || error) return <PageFrame title={`${actionLabel(mode)}计划`} eyebrow="交易动作 / ACTION PLAN"><PageState loading={loading} error={error} onRetry={() => void load()} /></PageFrame>;
  if (!trade || tradeId === null) return null;
  return <ActionPlanDialog key={`${planId || "new"}-${mode}`} fullPage accountId={accountId} planId={draftPlan ? Number(draftPlan.id) : undefined} initialValues={initialValues} initialCalculation={draftPlan?.calculation_snapshot_json} action={{ tradeId, symbol: String(trade.symbol || ""), securityName: String(trade.symbol_name || trade.symbol || ""), type: mode }} onClose={() => onNavigate("trades")} onSaved={async () => { onRefresh?.(); onNavigate("trades"); }} onError={setError} />;
}

export function ActionDetailPage({ accountId, tradeId, planId, onNavigate, onRefresh }: PageProps) {
  const [plan, setPlan] = useState<AnyRecord | null>(null); const [executions, setExecutions] = useState<AnyRecord[]>([]); const [orders, setOrders] = useState<AnyRecord[]>([]); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(true);
  const load = useCallback(async () => { if (planId === null || planId === undefined) { setError("当前页面缺少动作计划，请从交易列表进入"); setLoading(false); return; } setLoading(true); setError(null); try { const response = await readJson(`/api/trade-plans/${planId}`, accountId); const selected = response.item; if (!selected || (tradeId !== null && Number(selected.trade_id) !== tradeId)) throw new Error("未找到这笔交易的动作计划"); const linked = Array.isArray(selected.execution_plans) ? selected.execution_plans : []; setPlan(selected); setExecutions(linked); setOrders(linked.flatMap((item: AnyRecord) => Array.isArray(item.orders) ? item.orders : [])); } catch (cause) { setError(cause instanceof Error ? cause.message : "动作详情读取失败"); } finally { setLoading(false); } }, [accountId, planId, tradeId]);
  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);
  const filled = orders.reduce((sum, item) => sum + (Number(item.filled_quantity) || 0), 0);
  const fills = orders.reduce((sum, item) => sum + (Array.isArray(item.fills) ? item.fills.length : 0), 0);
  const planInput = plan?.input_json || {};
  return <PageFrame title="动作计划详情" eyebrow="交易动作 / ACTION PLAN" actions={<><button type="button" onClick={() => onNavigate("trades")}>返回交易</button><button type="button" onClick={() => { void load(); onRefresh?.(); }}>刷新</button></>}><PageState loading={loading} error={error} onRetry={() => void load()} />{plan && <><section className="trading-detail-hero"><div><small className="trading-phase-label">{actionLabel(plan.action_type || plan.action)}计划</small><span className="trading-symbol-name">{plan.security_name || plan.symbol || "未命名标的"}</span><code>{plan.symbol || "—"}</code><p>动作 #{plan.sequence_no ?? "—"} · {dateLabel(plan.created_at)}</p></div><div className="trading-status-pill">{statusLabel(plan.status)}</div></section><section className="trading-metric-grid"><Metric label="计划数量" value={`${numberLabel(plan.calculation_snapshot_json?.planned_qty)} 股`} /><Metric label="参考价格" value={money(planInput.reference_entry_price ?? planInput.reference_price)} /><Metric label="风险参考价" value={money(planInput.risk_reference_price)} /><Metric label="已成交" value={`${numberLabel(filled)} 股`} detail={`${fills} 笔成交回报`} /></section><section className="trading-panel"><div className="trading-panel-title"><h2>执行进度</h2><span>{executions.length} 个执行方案</span></div>{executions.length ? executions.map((item) => <article className="action-plan-execution-row" key={String(item.id)}><div><strong>{executionTypeLabel(item.execution_type)}</strong><small>{statusLabel(item.status)} · 成交 {numberLabel(item.filled_qty)} / {numberLabel(item.target_qty)} 股 · 剩余 {numberLabel(item.remaining_qty)} 股</small>{item.status_reason && <small>{item.status_reason}</small>}</div><div>{(item.orders || []).map((order: AnyRecord) => <span key={String(order.id)}>{sideLabel(order.side)} {numberLabel(order.filled_quantity)} / {numberLabel(order.quantity)} 股 · {statusLabel(order.status)}</span>)}</div></article>) : <p className="trading-empty">尚未安排执行。请返回交易列表，在这条动作计划上选择“执行”。</p>}</section></>}</PageFrame>;
}

export function ExecutionPlansPage({ accountId, onNavigate, onRefresh }: PageProps) {
  return <CollectionPage title="交易执行" eyebrow="交易执行 / EXECUTION PLANS" accountId={accountId} endpoint="/api/trading/execution-plans" headers={["标的", "动作", "数量", "执行方式", "状态", "更新时间"]} row={(item) => <><td>{item.symbol_name || item.symbol || "—"}<small>{item.symbol || "—"}</small></td><td>{actionLabel(item.action_type || item.action)}</td><td>{numberLabel(item.target_qty ?? item.quantity)} 股</td><td>{executionTypeLabel(item.execution_type || item.execution_method)}</td><td><span className="trading-status-pill">{statusLabel(item.status)}</span></td><td>{dateLabel(item.updated_at || item.created_at)}</td></>} action={(item, runCommand) => { const paused = ["PAUSED", "SUSPENDED"].includes(String(item.status)); const terminal = ["COMPLETED", "CANCELLED", "FAILED", "EXPIRED"].includes(String(item.status)); return <button type="button" className="trading-row-action" disabled={terminal} onClick={() => void runCommand(`/api/trading/execution-plans/${item.id}/status`, { method: "PATCH", body: JSON.stringify({ status: paused ? "ACTIVE" : "PAUSED" }) })}>{terminal ? "已结束" : paused ? "恢复" : "暂停"}</button>; }} onNavigate={onNavigate} onRefresh={onRefresh} />;
}
export function OrdersPage({ accountId, onNavigate, onRefresh }: PageProps) {
  return <CollectionPage title="订单" eyebrow="交易执行 / ORDERS" accountId={accountId} endpoint="/api/trading/orders" headers={["标的", "方向", "委托类型", "委托数量", "成交数量", "价格", "状态", "时间"]} row={(item) => <><td>{item.symbol_name || item.symbol || "—"}<small>{item.symbol || "—"}</small></td><td>{item.side === "BUY" ? "买入" : item.side === "SELL" ? "卖出" : item.side || "—"}</td><td>{item.order_type ? orderTypeLabel(item.order_type) : "委托类型未记录"}</td><td>{numberLabel(item.quantity)} 股</td><td>{numberLabel(item.filled_quantity)} 股</td><td>{money(item.price ?? item.limit_price)}</td><td><span className="trading-status-pill">{statusLabel(item.status)}</span></td><td>{dateLabel(item.updated_at || item.created_at)}</td></>} action={(item, runCommand) => { const cancellable = ["PENDING_SUBMIT", "QUEUED", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"].includes(String(item.status)); return <button type="button" className="trading-row-action trading-row-action-danger" disabled={!cancellable} onClick={() => void runCommand(`/api/trading/orders/${item.id}/cancel`, { method: "POST" })}>{cancellable ? "撤单" : "不可撤"}</button>; }} onNavigate={onNavigate} onRefresh={onRefresh} />;
}
export function PositionsPage({ accountId, onNavigate, onRefresh }: PageProps) {
  return <CollectionPage title="持仓" eyebrow="账户事实 / POSITIONS" accountId={accountId} endpoint="/api/trading/overview" collectionKey="positions" headers={["标的", "持仓", "可卖", "现价", "成本", "浮动盈亏", "更新时间"]} row={(item) => <><td>{item.security_name || item.symbol_name || item.symbol || "—"}<small>{item.symbol || "—"}</small></td><td>{numberLabel(item.quantity)} 股</td><td>{numberLabel(item.available_quantity)} 股</td><td>{money(item.market_price)}</td><td>{money(item.average_cost)}</td><td className={Number(item.unrealized_pnl) >= 0 ? "trading-profit" : "trading-loss"}>{money(item.unrealized_pnl)}</td><td>{dateLabel(item.updated_at)}</td></>} onNavigate={onNavigate} onRefresh={onRefresh} />;
}

function CollectionPage({ title, eyebrow, accountId, endpoint, collectionKey, headers, row, action, onNavigate, onRefresh }: { title: string; eyebrow: string; accountId: number; endpoint: string; collectionKey?: string; headers: string[]; row: (item: AnyRecord) => React.ReactNode; action?: (item: AnyRecord, runCommand: (path: string, init?: RequestInit) => Promise<void>) => React.ReactNode; onNavigate: PageProps["onNavigate"]; onRefresh?: () => void }) {
  const [items, setItems] = useState<AnyRecord[]>([]); const [payload, setPayload] = useState<AnyRecord | null>(null); const [error, setError] = useState<string | null>(null); const [commandError, setCommandError] = useState<string | null>(null); const [loading, setLoading] = useState(true); const [query, setQuery] = useState("");
  const load = useCallback(async () => { setLoading(true); setError(null); try { const result = await readJson(endpoint, accountId); const source = collectionKey ? result[collectionKey] : result.items; if (!Array.isArray(source)) throw new Error(`${title}数据不完整，请刷新后重试`); setPayload(result); setItems(source); } catch (cause) { setError(cause instanceof Error ? cause.message : `${title}读取失败`); } finally { setLoading(false); } }, [accountId, endpoint, collectionKey, title]);
  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);
  async function runCommand(path: string, init?: RequestInit) { setCommandError(null); try { await readJson(path, accountId, init); await load(); onRefresh?.(); } catch (cause) { setCommandError(cause instanceof Error ? cause.message : "操作失败，请重试"); } }
  const filtered = useMemo(() => { const value = query.trim().toLowerCase(); return value ? items.filter((item) => `${item.symbol || ""} ${item.symbol_name || item.security_name || ""} ${item.status || ""}`.toLowerCase().includes(value)) : items; }, [items, query]);
  const summary = useMemo(() => {
    const count = (statuses: string[]) => items.filter((item) => statuses.includes(String(item.status))).length;
    if (title === "交易执行") return [{ label: "执行计划总数", value: `${items.length} 条`, detail: "当前账户" }, { label: "等待执行", value: `${count(["PENDING_SUBMIT", "QUEUED"])} 条`, detail: "尚未发送" }, { label: "执行中", value: `${count(["SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"])} 条`, detail: "已进入通道" }, { label: "已完成", value: `${count(["COMPLETED", "FILLED"])} 条`, detail: "执行结果" }];
    if (title === "订单") return [{ label: "委托总数", value: `${items.length} 笔`, detail: "当前账户" }, { label: "待处理", value: `${count(["PENDING_SUBMIT", "QUEUED", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"])} 笔`, detail: "等待或部分成交" }, { label: "已成交", value: `${count(["FILLED"])} 笔`, detail: "成交状态" }, { label: "已撤/拒单", value: `${count(["CANCELLED", "REJECTED", "FAILED", "EXPIRED"])} 笔`, detail: "异常或结束" }];
    const marketValue = items.reduce((sum, item) => sum + (Number(item.market_value) || 0), 0); const pnl = items.reduce((sum, item) => sum + (Number(item.unrealized_pnl) || 0), 0); const exposure = typeof payload?.account?.total_exposure_pct === "number" ? payload.account.total_exposure_pct : null;
    return [{ label: "持仓标的", value: `${items.length} 只`, detail: "当前账户" }, { label: "持仓市值", value: money(marketValue), detail: "实时快照" }, { label: "浮动盈亏", value: money(pnl), detail: "持仓汇总" }, { label: "资金总仓位", value: exposure == null ? "—" : `${(exposure * 100).toFixed(2)}%`, detail: "账户敞口" }];
  }, [items, payload, title]);
  return <PageFrame title={title} eyebrow={eyebrow} actions={<><button type="button" onClick={() => { void load(); onRefresh?.(); }}>刷新</button>{title === "交易执行" && <button type="button" onClick={() => onNavigate("overview")}>返回总览</button>}</>}><PageState loading={loading} error={error} onRetry={() => void load()} />{!loading && !error && <><section className="trading-metric-grid">{summary.map((item) => <Metric key={item.label} label={item.label} value={item.value} detail={item.detail} />)}</section><section className="trading-panel">{commandError && <div className="trading-command-error">{commandError}</div>}<div className="trading-panel-title"><h2>{title}记录</h2><span>{filtered.length} 条</span></div><label className="trading-search-field">搜索<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="证券代码、名称或状态" /></label><Table headers={action ? [...headers, "操作"] : headers}>{filtered.length ? filtered.map((item, index) => <tr key={String(item.id ?? `${item.symbol}-${index}`)}>{row(item)}{action && <td>{action(item, runCommand)}</td>}</tr>) : <tr><td colSpan={action ? headers.length + 1 : headers.length} className="trading-empty">当前没有可展示的{title}记录。</td></tr>}</Table></section></>}</PageFrame>;
}
