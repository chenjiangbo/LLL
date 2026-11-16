"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { TradingPageKey } from "../types";

type OverviewProps = {
  accountId: number;
  onNavigate: (page: TradingPageKey, tradeId?: number, planId?: number) => void;
  onCreateTrade?: () => void;
  onOpenSettings?: () => void;
  onRefresh?: () => void;
};

type OverviewData = {
  account: {
    id: number;
    name: string;
    account_type: string;
    status: string;
    equity: number | null;
    available_cash: number | null;
    updated_at?: string | null;
    market_value?: number | null;
    total_exposure_pct?: number | null;
  };
  risk_profile?: { max_account_risk_pct?: number | null; max_total_exposure_pct?: number | null };
  positions: Array<Record<string, any>>;
  trades: Array<Record<string, any>>;
  execution_plans: Array<Record<string, any>>;
  orders: Array<Record<string, any>>;
  fills: Array<Record<string, any>>;
  reconciliation_issues: Array<Record<string, any>>;
  broker_status: Record<string, any>;
  live_snapshot_at?: string | null;
};

type PendingItem = {
  title: string;
  symbol?: string;
  detail: string;
  kind: string;
  tradeId?: number;
  planId?: number;
  page?: TradingPageKey;
};

function pendingTone(kind: string) {
  if (kind === "待执行") return "primary";
  if (kind === "待处理" || kind === "计划中") return "warning";
  if (["风险复核", "对账", "连接异常"].includes(kind)) return "danger";
  return "neutral";
}

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;
const OVERVIEW_CACHE_VERSION = 1;

function overviewCacheKey(accountId: number) {
  return `lll:trading-overview:${OVERVIEW_CACHE_VERSION}:${accountId}`;
}

function readOverviewCache(accountId: number): { data: OverviewData; cachedAt: string } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(overviewCacheKey(accountId));
    if (!raw) return null;
    const cached = JSON.parse(raw);
    if (!cached || cached.accountId !== accountId || typeof cached.cachedAt !== "string" || !cached.data?.account || !Array.isArray(cached.data.positions) || !Array.isArray(cached.data.trades) || !Array.isArray(cached.data.execution_plans) || !Array.isArray(cached.data.orders) || !Array.isArray(cached.data.fills) || !Array.isArray(cached.data.reconciliation_issues)) return null;
    return { data: cached.data as OverviewData, cachedAt: cached.cachedAt };
  } catch {
    return null;
  }
}

function writeOverviewCache(accountId: number, data: OverviewData) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(overviewCacheKey(accountId), JSON.stringify({ version: OVERVIEW_CACHE_VERSION, accountId, cachedAt: new Date().toISOString(), data }));
}

function formatMoney(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : "—";
}

function formatPercent(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "—";
}

function statusLabel(value: unknown) {
  return ({ ACTIVE: "运行中", CLOSING: "清仓中", PLANNED: "计划中", CLOSED: "已结束", PENDING_SUBMIT: "等待发送", QUEUED: "排队中", SUBMITTED: "已发送", ACCEPTED: "已接受", PARTIALLY_FILLED: "部分成交", FILLED: "已成交", CANCEL_PENDING: "撤单中", PENDING_CANCEL: "撤单中", CANCEL_REQUESTED: "撤单中", CANCELLED: "已撤单", CANCELLED_ORDER: "已撤单", CANCELED: "已撤单", REJECTED: "已拒单", FAILED: "失败", EXPIRED: "已过期" } as Record<string, string>)[String(value)] || "状态未记录";
}

function tradeStatusLabel(value: unknown) {
  return value === "ACTIVE" ? "已成交" : statusLabel(value);
}

function typeLabel(value: unknown) {
  return ({ TREND: "趋势", REBOUND: "反弹", FIXED_TARGET: "固定目标", CUSTOM: "自定义" } as Record<string, string>)[String(value)] || "未记录";
}

function actionLabel(value: unknown) {
  return ({ OPEN: "建仓", ADD: "加仓", REDUCE: "减仓", CLOSE: "清仓", OPEN_LONG: "建仓", RISK_REFERENCE: "风险参考调整", RISK_ADJUSTMENT: "风险参考调整", UPDATE_RISK_REFERENCE: "风险参考调整" } as Record<string, string>)[String(value)] || "动作";
}

function activityTone(action: string) {
  if (["OPEN", "OPEN_LONG", "ADD"].includes(action)) return "primary";
  if (action === "REDUCE") return "muted";
  if (action === "CLOSE") return "error";
  if (["RISK_REFERENCE", "RISK_ADJUSTMENT", "UPDATE_RISK_REFERENCE"].includes(action)) return "tertiary";
  return "secondary";
}

function dateLabel(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function tradingSymbolKey(value: unknown) {
  const symbol = String(value ?? "").trim().toUpperCase();
  if (!symbol) return "";
  const separator = Math.max(symbol.lastIndexOf(":"), symbol.lastIndexOf("."));
  return separator >= 0 ? symbol.slice(separator + 1) : symbol;
}

function calculateTradeRisk(trade: Record<string, any>, position: Record<string, any> | undefined) {
  const legs = Array.isArray(trade.legs) ? trade.legs : [];
  let capital = 0;
  let giveback = 0;
  let validLegs = 0;
  let incomplete = legs.length === 0;
  for (const leg of legs) {
    const remainingQty = Number(leg.remaining_qty);
    if (!Number.isFinite(remainingQty) || remainingQty < 0) { incomplete = true; continue; }
    if (remainingQty === 0) continue;
    const entryPrice = Number(leg.actual_avg_entry_price ?? leg.planned_entry_price);
    const referencePrice = Number(leg.current_risk_reference_price ?? leg.initial_risk_reference_price);
    const marketPrice = Number(position?.market_price);
    if (!Number.isFinite(entryPrice) || !Number.isFinite(referencePrice) || referencePrice <= 0) { incomplete = true; continue; }
    validLegs += 1;
    capital += Math.max(0, entryPrice - referencePrice) * remainingQty;
    if (!Number.isFinite(marketPrice)) incomplete = true;
    else giveback += Math.max(0, marketPrice - referencePrice) * remainingQty;
  }
  return { capital: validLegs > 0 && !incomplete ? capital : null, giveback: validLegs > 0 && !incomplete ? giveback : null, incomplete: validLegs === 0 || incomplete };
}

async function readOverview(accountId: number): Promise<OverviewData> {
  if (!API_BASE) throw new Error("交易服务配置不可用，请联系管理员");
  const response = await fetch(`${API_BASE}/api/trading/overview?account_id=${encodeURIComponent(String(accountId))}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`交易总览读取失败（HTTP ${response.status}）`);
  const payload = await response.json();
  const required = ["positions", "trades", "execution_plans", "orders", "fills", "reconciliation_issues"];
  if (!payload.account || !payload.broker_status || typeof payload.broker_status !== "object" || required.some((key) => !Array.isArray(payload[key]))) throw new Error("交易总览数据不完整，请刷新后重试");
  if (Number(payload.account.id) !== accountId) throw new Error("交易总览账号数据校验失败，请刷新后重试");
  if (!["SIMULATION", "LIVE"].includes(String(payload.account.account_type))) return payload as OverviewData;

  const liveResponse = await fetch(`${API_BASE}/api/trading/live-snapshot?account_id=${encodeURIComponent(String(accountId))}`, { cache: "no-store" });
  if (!liveResponse.ok) throw new Error(`实时账户快照读取失败（HTTP ${liveResponse.status}）`);
  const livePayload = await liveResponse.json();
  if (!livePayload.account || !Array.isArray(livePayload.positions) || !livePayload.broker_status || typeof livePayload.broker_status !== "object") {
    throw new Error("实时账户快照数据不完整，请刷新后重试");
  }
  const planningPositions = new Map<string, Record<string, any>>(payload.positions.map((position: Record<string, any>) => [String(position.symbol), position]));
  const livePositions = livePayload.positions.map((position: Record<string, any>) => ({
    ...(planningPositions.get(String(position.symbol)) || {}),
    ...position,
    security_name: position.security_name || planningPositions.get(String(position.symbol))?.security_name || String(position.symbol),
  }));
  return {
    ...payload,
    account: {
      ...payload.account,
      ...livePayload.account,
      id: accountId,
      name: payload.account.name,
      account_type: payload.account.account_type,
      status: payload.account.status,
      updated_at: livePayload.as_of || payload.account.updated_at,
    },
    positions: livePositions,
    broker_status: livePayload.broker_status,
    live_snapshot_at: livePayload.as_of || null,
  } as OverviewData;
}

function SummaryCard({ title, value, supporting, tone }: { title: string; value: string; supporting: string; tone: "green" | "blue" | "amber" | "rose" | "slate" }) {
  return (
    <section className={`overview-card overview-card-${tone}`}>
      <div className="overview-card-heading"><span>{title}</span><span className="material-symbols-outlined text-[18px]">{tone === "green" ? "account_balance" : tone === "blue" ? "savings" : tone === "amber" ? "pie_chart" : tone === "rose" ? "security" : "speed"}</span></div>
      <div className="overview-card-value">{value}</div>
      <div className="overview-card-supporting">{supporting}</div>
    </section>
  );
}

export default function TradingOverviewPage({ accountId, onNavigate, onCreateTrade, onOpenSettings, onRefresh }: OverviewProps) {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [dataUpdatedAt, setDataUpdatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setSyncing(true);
    setSyncError(null);
    try {
      const fresh = await readOverview(accountId);
      setData(fresh);
      writeOverviewCache(accountId, fresh);
      setDataUpdatedAt(fresh.live_snapshot_at || fresh.account.updated_at || new Date().toISOString());
      setError(null);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "交易总览读取失败";
      if (data || readOverviewCache(accountId)) setSyncError(message);
      else setError(message);
    } finally {
      setLoading(false);
      setSyncing(false);
    }
  }, [accountId]);

  useEffect(() => {
    const cached = readOverviewCache(accountId);
    if (cached) {
      setData(cached.data);
      setDataUpdatedAt(cached.cachedAt);
      setLoading(false);
    } else {
      setData(null);
      setDataUpdatedAt(null);
      setLoading(true);
    }
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [accountId]);

  const derived = useMemo(() => {
    if (!data) return null;
    const activeTrades = data.trades.filter((trade) => ["ACTIVE", "CLOSING"].includes(String(trade.status)));
    const plannedTrades = data.trades.filter((trade) => String(trade.status) === "PLANNED");
    const account = data.account;
    const equity = typeof account.equity === "number" ? account.equity : null;
    const availableCash = typeof account.available_cash === "number" ? account.available_cash : null;
    const exposure = typeof account.total_exposure_pct === "number" ? account.total_exposure_pct : null;
    const riskBudgetPct = typeof data.risk_profile?.max_account_risk_pct === "number" ? data.risk_profile.max_account_risk_pct : null;
    const positionBySymbol = new Map(data.positions.map((position) => [tradingSymbolKey(position.symbol), position]));
    const riskByTrade = new Map(activeTrades.map((trade) => [Number(trade.id), calculateTradeRisk(trade, positionBySymbol.get(tradingSymbolKey(trade.symbol)))]));
    const readyActions = activeTrades.flatMap((trade) => (Array.isArray(trade.plans) ? trade.plans : [])
      .filter((plan) => ["READY", "ARMED", "MONITORING"].includes(String(plan.status)))
      .map((plan) => ({ title: String(trade.symbol_name || trade.symbol || "未命名 Trade"), symbol: String(trade.symbol || ""), detail: `${actionLabel(plan.action_type || plan.action)} #${plan.sequence_no ?? "—"} 已确认，等待创建执行计划。`, kind: "待执行", tradeId: Number(trade.id), planId: Number(plan.id) })));
    const pendingExecutionPlans = data.execution_plans
      .filter((plan) => ["PENDING_SUBMIT", "QUEUED", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"].includes(String(plan.status)))
      .map((plan) => ({ title: String(plan.symbol_name || plan.symbol || "未记录标的"), symbol: String(plan.symbol || ""), detail: `执行计划${statusLabel(plan.status)}，目标 ${plan.target_qty ?? "—"} 股。`, kind: "执行中", tradeId: undefined, planId: Number(plan.id), page: "execution" as const }));
    const partialOrders = data.orders
      .filter((order) => Number(order.filled_quantity) > 0 && Number(order.filled_quantity) < Number(order.quantity))
      .map((order) => ({ title: String(order.symbol_name || order.symbol || "未记录标的"), symbol: String(order.symbol || ""), detail: `订单部分成交 ${order.filled_quantity} / ${order.quantity} 股，仍有剩余数量。`, kind: "部分成交", tradeId: undefined, page: "orders" as const }));
    const t1Positions = data.positions
      .filter((position) => Number(position.available_quantity) < Number(position.quantity))
      .map((position) => ({ title: String(position.security_name || position.symbol || "未记录标的"), symbol: String(position.symbol || ""), detail: "当前持仓存在 T+1 或可卖数量限制。", kind: "待处理", tradeId: activeTrades.find((trade) => tradingSymbolKey(trade.symbol) === tradingSymbolKey(position.symbol))?.id, page: "positions" as const }));
    const incompleteRisk = activeTrades
      .filter((trade) => riskByTrade.get(Number(trade.id))?.incomplete)
      .map((trade) => ({ title: String(trade.symbol_name || trade.symbol || "未命名 Trade"), symbol: String(trade.symbol || ""), detail: "风险参考已长时间未更新，请重新确认防守基准。", kind: "风险复核", tradeId: Number(trade.id) }));
    const connectionPending = data.broker_status && (data.broker_status.status !== "CONNECTED" || data.broker_status.node_status?.reconciliation_required)
      ? [{ title: "券商交易通道", detail: data.broker_status.node_status?.reconciliation_required ? "当前通道需要完成对账后再继续执行。" : `当前通道${data.broker_status.message || "未连接"}。`, kind: "连接异常", tradeId: undefined }]
      : [];
    const pending: PendingItem[] = [
      ...plannedTrades.map((trade) => ({ title: String(trade.symbol_name || trade.symbol || "未命名 Trade"), detail: "交易计划已存在，等待后续执行安排。", kind: "计划中", tradeId: Number(trade.id) })),
      ...readyActions,
      ...pendingExecutionPlans,
      ...partialOrders,
      ...t1Positions,
      ...incompleteRisk,
      ...(data.reconciliation_issues.length ? [{ title: "账户对账", detail: `当前有 ${data.reconciliation_issues.length} 项对账事项需要处理。`, kind: "对账", tradeId: undefined }] : []),
      ...connectionPending,
    ];
    const activities = [
      ...data.trades.flatMap((trade) => (Array.isArray(trade.plans) ? trade.plans : []).map((plan) => {
        const action = String(plan.action_type || plan.action || "");
        return { label: `${actionLabel(action)} #${plan.sequence_no ?? "—"}`, symbol: trade.symbol, symbolName: trade.symbol_name, detail: `计划状态：${statusLabel(plan.status)}`, time: plan.updated_at || plan.created_at, tone: activityTone(action) };
      })),
      ...data.orders.map((order) => ({ label: order.status === "FILLED" ? "订单成交" : "订单状态", symbol: order.symbol, symbolName: order.symbol_name, detail: `${order.side === "BUY" ? "买入" : "卖出"} ${order.quantity ?? "—"} 股 · ${statusLabel(order.status)}`, time: order.updated_at || order.created_at, tone: "secondary" })),
      ...data.fills.map((fill) => ({ label: "订单成交", symbol: fill.symbol, symbolName: fill.symbol_name, detail: `${fill.quantity ?? fill.filled_quantity ?? "—"} 股成交 · ${formatMoney(fill.price ?? fill.average_fill_price)}`, time: fill.filled_at || fill.created_at, tone: "secondary" })),
    ].sort((a, b) => String(b.time || "").localeCompare(String(a.time || "")));
    return { activeTrades, plannedTrades, account, equity, availableCash, exposure, riskBudgetPct, positionBySymbol, riskByTrade, pending, activities, incompleteRiskCount: incompleteRisk.length };
  }, [data]);

  if (loading) return <div className="overview-state">正在读取交易总览…</div>;
  if (error || !data || !derived) return <div className="overview-state overview-state-error"><p>{error || "交易总览读取失败"}</p><button type="button" onClick={() => void load()}>重新读取</button></div>;

  const { account, equity, availableCash, exposure, riskBudgetPct, positionBySymbol, riskByTrade, activeTrades, plannedTrades, pending, activities, incompleteRiskCount } = derived;
  const visibleTrades = [...activeTrades, ...plannedTrades];
  const pendingPreview: PendingItem[] = [];
  const pendingKinds = new Set<string>();
  for (const item of pending) {
    if (pendingPreview.length >= 3 || pendingKinds.has(item.kind)) continue;
    pendingPreview.push(item);
    pendingKinds.add(item.kind);
  }
  const cashRatio = equity && availableCash !== null ? availableCash / equity : null;
  const riskValues = activeTrades.map((trade) => riskByTrade.get(Number(trade.id))?.capital ?? null);
  const riskValue = riskValues.length === 0 ? 0 : riskValues.every((value) => typeof value === "number") ? riskValues.reduce((total, value) => total + Number(value), 0) : null;
  const riskRatio = equity && riskBudgetPct && riskValue !== null ? riskValue / equity / riskBudgetPct : null;
  const currentRiskPct = equity && riskValue !== null ? riskValue / equity : null;
  const maxExposurePct = typeof data.risk_profile?.max_total_exposure_pct === "number" ? data.risk_profile.max_total_exposure_pct : null;
  const exposureUsageRatio = exposure !== null && maxExposurePct ? exposure / maxExposurePct : null;

  return (
    <div className="trading-overview-page">
      <div className="overview-page-header">
        <div><div className="overview-title-row"><h1>交易总览</h1><span>实时监控账户资产、活跃 Trade 敞口与待办风险</span></div></div>
        <div className="overview-actions">{!syncing && (syncError ? <span className="overview-sync-status overview-sync-status-error">同步失败，当前显示本地数据</span> : dataUpdatedAt ? <span className="overview-sync-status">同步于 {dateLabel(dataUpdatedAt)}</span> : null)}<button type="button" onClick={() => { void load(); onRefresh?.(); }}><span className={`material-symbols-outlined ${syncing ? "overview-refresh-spinning" : ""}`}>refresh</span>刷新数据</button><button type="button" className="overview-primary-action" onClick={onCreateTrade}><span className="material-symbols-outlined">add_circle</span>创建交易</button></div>
      </div>

      <div className="overview-summary-grid">
        <SummaryCard title="账户净资产" value={formatMoney(account.equity)} supporting="当前账号资产净值" tone="green" />
        <SummaryCard title="可用现金" value={formatMoney(account.available_cash)} supporting={`现金储备比例 ${formatPercent(cashRatio)}`} tone="blue" />
        <SummaryCard title="当前总仓位" value={formatPercent(exposure)} supporting={`持仓市值 ${formatMoney(account.market_value)} · ${data.positions.length} 只持仓标的`} tone="amber" />
        <SummaryCard title="账户当前总风险" value={formatMoney(riskValue)} supporting={`计划风险占比 ${equity && riskValue !== null ? formatPercent(riskValue / equity) : "—"}`} tone="rose" />
      </div>

      <div className="overview-risk-overview">
        <div className={`overview-risk-warning ${incompleteRiskCount || data.reconciliation_issues.length || data.broker_status?.status !== "CONNECTED" ? "overview-risk-strip-warning" : ""}`}>
          <div><span className="overview-risk-warning-icon material-symbols-outlined">warning</span><span>{incompleteRiskCount ? `部分 Trade 尚未设置有效风险参考，账户总计划风险可能低估。` : data.reconciliation_issues.length ? `当前有 ${data.reconciliation_issues.length} 项对账事项需要处理。` : data.broker_status?.status !== "CONNECTED" ? `券商交易通道${data.broker_status?.message || "未连接"}，请检查连接状态。` : "当前账户数据已完成读取，请关注活动 Trade 和待处理事项。"}</span></div>
          <button type="button" onClick={onOpenSettings}>去设置<span className="material-symbols-outlined">arrow_forward</span></button>
        </div>
        <div className="overview-risk-mini-grid">
          <div className="overview-risk-mini-card"><div><span>计划风险进度</span><span>{currentRiskPct === null || riskBudgetPct === null ? "—" : `${formatPercent(currentRiskPct)} / ${formatPercent(riskBudgetPct)}`}</span></div><div className="overview-progress-track"><div className="overview-progress-risk" style={{ width: `${Math.min(100, Math.max(0, (riskRatio || 0) * 100))}%` }} /></div></div>
          <div className="overview-risk-mini-card"><div><span>仓位占用</span><span>{exposure === null || maxExposurePct === null ? "—" : `${formatPercent(exposure)} / ${formatPercent(maxExposurePct)}`}</span></div><div className="overview-progress-track"><div className="overview-progress-exposure" style={{ width: `${Math.min(100, Math.max(0, (exposureUsageRatio || 0) * 100))}%` }} /></div></div>
        </div>
      </div>

      <div className="overview-content-grid">
        <div className="overview-main-column"><section className="overview-panel overview-trades-panel"><div className="overview-panel-header"><h2><span className="material-symbols-outlined">candlestick_chart</span>活动 Trade 敞口监控 <em>{activeTrades.length} 活跃 · {plannedTrades.length} 计划</em></h2><span>红涨绿跌模式</span></div><div className="overview-table-wrap"><table><thead><tr><th>标的代码/名称</th><th>类型</th><th>状态</th><th>当前持仓</th><th>资金仓位</th><th>现价 / 成本</th><th>浮动盈亏</th><th>本金计划风险</th><th>利润回吐风险</th><th>操作</th></tr></thead><tbody>{visibleTrades.length ? visibleTrades.map((trade) => { const position = positionBySymbol.get(String(trade.symbol)); const tradeRisk = riskByTrade.get(Number(trade.id)); const pnl = typeof position?.unrealized_pnl === "number" ? position.unrealized_pnl : null; const price = Number(position?.market_price); const cost = Number(position?.average_cost); const rowTone = String(trade.status) === "PLANNED" || pnl === null || !Number.isFinite(price) || !Number.isFinite(cost) || price === cost ? "overview-row-neutral" : price > cost ? "overview-row-profit" : "overview-row-loss"; return <tr className={rowTone} key={String(trade.id)} onClick={() => onNavigate("trade", Number(trade.id))}><td><strong>{trade.symbol_name || "—"}</strong><small>{trade.symbol || "—"}</small></td><td><span className="overview-tag overview-tag-violet">{typeLabel(trade.trade_type)}</span></td><td><span className={`overview-tag ${String(trade.status) === "PLANNED" ? "overview-tag-amber" : "overview-tag-green"}`}>{tradeStatusLabel(trade.status)}</span></td><td>{position?.quantity ?? "—"} 股</td><td>{equity && typeof position?.market_value === "number" ? formatPercent(position.market_value / equity) : "—"}</td><td><strong>{formatMoney(position?.market_price)}</strong><small>成本 {formatMoney(position?.average_cost)}</small></td><td className={pnl !== null && pnl >= 0 ? "overview-profit" : "overview-loss"}>{formatMoney(pnl)}</td><td>{formatMoney(tradeRisk?.capital)}</td><td>{formatMoney(tradeRisk?.giveback)}</td><td><button type="button" onClick={(event) => { event.stopPropagation(); onNavigate("trade", Number(trade.id)); }}>查看</button></td></tr>; }) : <tr><td colSpan={10} className="overview-empty-cell">当前账号暂无活动或计划中的 Trade。</td></tr>}</tbody></table></div></section></div>

        <aside className="overview-side-column"><section className="overview-panel overview-pending-panel"><div className="overview-panel-header"><h2><span aria-hidden="true" className="material-symbols-outlined">pending_actions</span>待处理事项 <em>{pendingPreview.length} 项</em></h2></div><div className="overview-pending-list">{pendingPreview.length ? pendingPreview.map((item, index) => <button type="button" className={`overview-pending-item overview-pending-${pendingTone(item.kind)}`} key={`${item.title}-${index}`} onClick={() => item.tradeId ? onNavigate("trade", Number(item.tradeId)) : item.page ? onNavigate(item.page, undefined, item.planId) : onOpenSettings?.()}><div className="overview-pending-copy"><div className="overview-pending-title"><strong>{item.title}</strong>{item.symbol && <code>{item.symbol}</code>}</div><span className="overview-pending-detail">{item.detail}</span></div><span className={`overview-pending-cta overview-pending-cta-${pendingTone(item.kind)}`}>{item.kind === "计划中" || item.kind === "待执行" ? "去执行" : item.kind === "对账" || item.kind === "连接异常" ? "处理" : item.kind === "风险复核" ? "调风控" : "查看"}</span></button>) : <p className="overview-empty">当前账号暂无待处理事项。</p>}</div></section><section className="overview-panel overview-activity-panel"><div className="overview-panel-header"><h2><span aria-hidden="true" className="material-symbols-outlined">history</span>最近系统动作</h2><button type="button" className="overview-activity-all">查看全部</button></div><div className="overview-activity-list">{activities.length ? activities.map((item, index) => <div className={`overview-activity-item overview-activity-${item.tone}`} key={`${item.symbol}-${index}`}><span className="overview-activity-dot" /><div className="overview-activity-copy"><div className="overview-activity-title"><strong className="overview-activity-tag">{item.label}</strong><span>{item.symbolName || item.symbol || "—"} {item.symbol || ""}</span></div><p>{item.detail}</p></div><time>{dateLabel(item.time)}</time></div>) : <p className="overview-empty">当前账号暂无订单或成交流水。</p>}</div></section></aside>
      </div>
    </div>
  );
}
