"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus, RefreshCw, Trash2, X } from "lucide-react";
import type { TradingPageKey } from "../types";
import { canEditTradePlan, readLocalOverviewCache, writeLocalOverviewCache } from "../common/tradingData";
import { exchangeFromSymbol, orderTypesForExchange, orderTypeDescription } from "../orderTypes";

type TradesProps = {
  accountId: number;
  onNavigate: (page: TradingPageKey, tradeId?: number, planId?: number) => void;
  onRefresh?: () => void;
};

type TradingData = {
  account: Record<string, any>;
  risk_profile?: Record<string, any> | null;
  positions: Array<Record<string, any>>;
  trades: Array<Record<string, any>>;
  execution_plans: Array<Record<string, any>>;
  orders: Array<Record<string, any>>;
  fills: Array<Record<string, any>>;
};

type StatusFilter = "ALL" | "PLANNED" | "ACTIVE" | "CLOSING" | "CLOSED" | "CANCELLED";

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;
const LIVE_ORDER_STATUSES = new Set(["PENDING_SUBMIT", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED", "CANCEL_PENDING", "UNKNOWN"]);

function money(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : "—";
}

function percent(value: unknown, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(digits)}%` : "—";
}

function dateLabel(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function statusLabel(value: unknown) {
  return ({
    DRAFT: "草稿",
    PLANNED: "计划中",
    READY: "已确认，待安排执行",
    ARMED: "执行中",
    PARTIALLY_EXECUTED: "部分成交",
    EXECUTED: "已成交",
    INVALIDATED: "已失效",
    ACTIVE: "持仓中",
    CLOSING: "清仓中",
    CLOSED: "已结束",
    COMPLETED: "已结束",
    CANCELLED: "已取消",
    CANCELED: "已取消",
    EXPIRED: "已过期",
    PAUSED: "已暂停，待检查",
    SUBMITTED: "委托已发送",
    ACCEPTED: "委托已接受",
    PARTIALLY_FILLED: "部分成交",
    FILLED: "已成交",
    REJECTED: "委托被拒绝",
  } as Record<string, string>)[String(value || "").toUpperCase()] || "状态未记录";
}

function executionSummaryLabel(execution: Record<string, any>, orders: Array<Record<string, any>> | null, reason: string) {
  const status = String(execution.status || "").toUpperCase();
  const target = Number(execution.target_qty || 0);
  const filled = Number(execution.filled_qty || 0);
  const remaining = Number(execution.remaining_qty || 0);
  const progress = `成交 ${filled.toLocaleString("zh-CN")} / ${target.toLocaleString("zh-CN")} 股`;
  if (filled + remaining !== target) return `成交数据待核对：已记成交 ${filled.toLocaleString("zh-CN")} 股，剩余 ${remaining.toLocaleString("zh-CN")} 股，计划 ${target.toLocaleString("zh-CN")} 股`;
  if (status === "COMPLETED") return filled === target ? `已全部成交 · ${progress}` : `执行已结束，成交记录待核对 · ${progress}`;
  if (status === "CANCELLED" && orders?.some((order) => String(order.status || "").toUpperCase() === "CANCEL_PENDING")) {
    return `撤单请求已发送，等待券商确认 · ${progress}`;
  }
  if (status === "CANCELLED") return `已取消 · ${progress}`;
  if (status === "PAUSED") return `已暂停 · ${progress}${reason && !reason.startsWith("用户手动") ? ` · ${reason}` : ""}`;
  if (status !== "ACTIVE") return `${statusLabel(status)} · ${progress}`;
  if (orders === null) return `委托状态待核实 · ${progress}`;

  const orderStatuses = orders.map((order) => String(order.status || "").toUpperCase());
  if (orderStatuses.includes("CANCEL_PENDING")) return `撤单中，等待券商确认 · ${progress}`;
  if (orderStatuses.includes("PARTIALLY_FILLED")) return `部分成交，委托仍在处理 · ${progress}`;
  if (orderStatuses.includes("FILLED")) return `委托已成交 · ${progress}`;
  if (orderStatuses.includes("ACCEPTED")) return `委托已接受，等待成交 · ${progress}`;
  if (orderStatuses.includes("SUBMITTED")) return `委托已发送，等待券商回报 · ${progress}`;
  if (orderStatuses.includes("PENDING_SUBMIT") || orderStatuses.includes("QUEUED")) return `委托等待发送 · ${progress}`;
  if (reason && !["用户手动恢复执行", "用户手动暂停执行"].includes(reason)) return `${reason} · ${progress}`;
  if (execution.valid_from && Date.parse(String(execution.valid_from)) > Date.now()) return `等待开始时间 · ${progress}`;
  if (execution.execution_type === "PRICE_TRIGGER") return `等待触发价格 · ${progress}`;
  if (execution.execution_type === "PRICE_RANGE") return `等待进入价格区间 · ${progress}`;
  return `执行已启动，等待提交委托 · ${progress}`;
}

function actionRemainingQuantity(plan: Record<string, any>) {
  const planned = Number(plan.calculation_snapshot_json?.planned_qty ?? plan.input_json?.manual_planned_qty ?? plan.target_qty ?? 0);
  const executions = Array.isArray(plan.execution_plans) ? plan.execution_plans : [];
  const filled = executions.reduce((total: number, item: Record<string, any>) => total + Number(item.filled_qty || 0), 0);
  return Number.isFinite(planned) ? Math.max(0, Math.floor(planned - filled)) : 0;
}

function typeLabel(value: unknown) {
  return ({ TREND: "趋势", REBOUND: "反弹", FIXED_TARGET: "固定目标", CUSTOM: "自定义" } as Record<string, string>)[String(value)] || "未记录";
}

function actionLabel(value: unknown) {
  return ({ OPEN: "建仓", ADD: "加仓", REDUCE: "减仓", CLOSE: "清仓" } as Record<string, string>)[String(value)] || "动作";
}

function calculateRisk(trade: Record<string, any>, position: Record<string, any> | undefined) {
  const legs = Array.isArray(trade.legs) ? trade.legs : [];
  let capital = 0;
  let giveback = 0;
  let validLegs = 0;
  let incomplete = legs.length === 0;
  for (const leg of legs) {
    const quantity = Number(leg.remaining_qty);
    const entry = Number(leg.actual_avg_entry_price ?? leg.planned_entry_price);
    const reference = Number(leg.current_risk_reference_price ?? leg.initial_risk_reference_price);
    const market = Number(position?.market_price);
    if (!Number.isFinite(quantity) || quantity < 0 || !Number.isFinite(entry) || !Number.isFinite(reference) || reference <= 0) {
      incomplete = true;
      continue;
    }
    if (quantity === 0) continue;
    validLegs += 1;
    capital += Math.max(0, entry - reference) * quantity;
    if (!Number.isFinite(market)) incomplete = true;
    else giveback += Math.max(0, market - reference) * quantity;
  }
  return { capital: validLegs > 0 && !incomplete ? capital : null, giveback: validLegs > 0 && !incomplete ? giveback : null };
}

async function readTradingData(accountId: number): Promise<TradingData> {
  if (!API_BASE) throw new Error("交易服务配置不可用，请联系管理员");
  const response = await fetch(`${API_BASE}/api/trading/overview/local?account_id=${encodeURIComponent(String(accountId))}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`交易列表读取失败（HTTP ${response.status}）`);
  const payload = await response.json();
  const required = ["positions", "trades", "execution_plans", "orders", "fills"];
  if (!payload.account || required.some((key) => !Array.isArray(payload[key]))) throw new Error("交易列表数据不完整，请刷新后重试");
  if (Number(payload.account.id) !== accountId) throw new Error("交易列表账号数据校验失败，请刷新后重试");
  return payload as TradingData;
}

async function mutateTradeApi(path: string, accountId: number, init: RequestInit = {}) {
  if (!API_BASE) throw new Error("交易服务配置不可用，请联系管理员");
  const response = await fetch(`${API_BASE}${path}${path.includes("?") ? "&" : "?"}account_id=${encodeURIComponent(String(accountId))}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
    cache: "no-store",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === "string" ? payload.detail : payload.detail?.message;
    throw new Error(detail || `操作失败（HTTP ${response.status}）`);
  }
  return payload;
}

function executionDefaultPrice(plan: Record<string, any>) {
  const input = plan.input_json || {};
  const value = input.reference_entry_price ?? input.reference_price;
  return value == null ? "" : String(value);
}

function localDateTimeInputValue(value: Date) {
  return new Date(value.getTime() - value.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export default function TradingTradesPage({ accountId, onNavigate, onRefresh }: TradesProps) {
  const [data, setData] = useState<TradingData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [dataUpdatedAt, setDataUpdatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const hasData = useRef(false);
  const [status, setStatus] = useState<StatusFilter>("ALL");
  const [query, setQuery] = useState("");
  const [type, setType] = useState("ALL");
  const [days, setDays] = useState("30");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [compact, setCompact] = useState(false);
  const [now] = useState(() => Date.now());
  const [executionPlan, setExecutionPlan] = useState<Record<string, any> | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [commandBusy, setCommandBusy] = useState(false);
  const [cancelBusyActionId, setCancelBusyActionId] = useState<number | null>(null);
  const [brokerState, setBrokerState] = useState<{ accountId: number; message: string | null; checked: boolean }>({ accountId, message: null, checked: false });

  const checkBrokerState = useCallback(async () => {
    try {
      if (!API_BASE) throw new Error("交易服务配置不可用");
      const response = await fetch(`${API_BASE}/api/trading/broker?account_id=${encodeURIComponent(String(accountId))}`, { cache: "no-store", signal: AbortSignal.timeout(12000) });
      if (!response.ok) throw new Error(`交易通道状态读取失败（HTTP ${response.status}）`);
      const payload = await response.json();
      const connection = payload.connection;
      if (!connection || typeof connection.status !== "string") throw new Error("交易通道状态数据不完整");
      const node = connection.node_status;
      let message: string | null = null;
      if (connection.status !== "CONNECTED") message = "交易通道未连接，请检查连接状态";
      else if (!node || typeof node.reconciliation_required !== "boolean" || typeof node.paused !== "boolean" || typeof node.execution_enabled !== "boolean" || typeof node.agent_online !== "boolean") message = "交易通道状态不完整，请检查连接状态";
      else if (node.reconciliation_required) message = "交易通道需要核对，暂不能提交委托";
      else if (node.paused || !node.execution_enabled) message = "交易通道已暂停，暂不能提交委托";
      else if (!node.agent_online) message = "交易服务未运行，暂不能提交委托";
      else if (node.trade_connected !== true || node.account_connected !== true) message = "券商账户未连接，暂不能提交委托";
      else if (node.market_connected !== true) message = "行情连接中断，请检查交易通道";
      setBrokerState({ accountId, message, checked: true });
    } catch {
      setBrokerState({ accountId, message: "交易通道状态读取失败，请检查连接并刷新", checked: true });
    }
  }, [accountId]);

  useEffect(() => {
    if (data?.account.account_type === "PLANNING") return;
    setBrokerState({ accountId, message: null, checked: false });
    void checkBrokerState();
    const interval = window.setInterval(() => void checkBrokerState(), 15000);
    return () => window.clearInterval(interval);
  }, [accountId, checkBrokerState, data?.account.account_type]);

  const load = useCallback(async () => {
    setSyncing(true);
    if (!hasData.current) setLoading(true);
    setSyncError(null);
    try {
      const fresh = await readTradingData(accountId);
      setData(fresh);
      hasData.current = true;
      writeLocalOverviewCache(accountId, fresh);
      setDataUpdatedAt(new Date().toISOString());
      setError(null);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "交易列表读取失败";
      if (hasData.current) setSyncError(message);
      else setError(message);
    } finally {
      setLoading(false);
      setSyncing(false);
    }
  }, [accountId]);

  useEffect(() => {
    const cached = readLocalOverviewCache(accountId);
    hasData.current = Boolean(cached);
    if (cached) { setData(cached.data as TradingData); setDataUpdatedAt(cached.cachedAt); setLoading(false); }
    else { setData(null); setDataUpdatedAt(null); setLoading(true); }
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [accountId, load]);

  const hasCancelPendingOrders = Boolean(data?.orders.some((order) => String(order.status || "").toUpperCase() === "CANCEL_PENDING"));
  useEffect(() => {
    if (!hasCancelPendingOrders) return;
    const interval = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(interval);
  }, [hasCancelPendingOrders, load]);

  const derived = useMemo(() => {
    if (!data) return null;
    const positions = new Map(data.positions.map((position) => [String(position.symbol), position]));
    const cutoff = days === "ALL" ? null : now - Number(days) * 24 * 60 * 60 * 1000;
    const matchingTrades = data.trades.filter((trade) => {
      if (type !== "ALL" && String(trade.trade_type) !== type) return false;
      const text = `${trade.symbol || ""} ${trade.symbol_name || ""} ${trade.playbook || ""}`.toLowerCase();
      if (query.trim() && !text.includes(query.trim().toLowerCase())) return false;
      if (cutoff !== null && trade.created_at && new Date(String(trade.created_at)).getTime() < cutoff) return false;
      return true;
    });
    const counts: Record<StatusFilter, number> = { ALL: matchingTrades.length, PLANNED: 0, ACTIVE: 0, CLOSING: 0, CLOSED: 0, CANCELLED: 0 };
    matchingTrades.forEach((trade) => {
      const key = String(trade.status) as StatusFilter;
      if (key in counts && key !== "ALL") counts[key] += 1;
    });
    const latestPlan = (trade: Record<string, any>) => {
      const plans = Array.isArray(trade.plans) ? trade.plans : data.execution_plans.filter((plan) => Number(plan.trade_id) === Number(trade.id) || Number(plan.trade_plan_id) === Number(trade.id));
      return plans.length ? plans[plans.length - 1] : undefined;
    };
    const recentAction = (trade: Record<string, any>) => {
      const plan = latestPlan(trade);
      if (!plan) return null;
      return `${actionLabel(plan.action_type || plan.action)} #${plan.sequence_no ?? "—"} · ${String(plan.status || "").toUpperCase() === "COMPLETED" ? "已完成" : statusLabel(plan.status)}`;
    };
    const items = matchingTrades.filter((trade) => status === "ALL" || String(trade.status) === status);
    const risk = new Map(data.trades.map((trade) => [Number(trade.id), calculateRisk(trade, positions.get(String(trade.symbol)))]));
    return { positions, counts, items, risk, latestPlan, recentAction };
  }, [data, days, now, query, status, type]);

  async function deleteDraft(planId: number) {
    if (!window.confirm("删除这条草稿计划？已确认的计划不能删除。")) return;
    setCommandBusy(true); setCommandError(null);
    try { await mutateTradeApi(`/api/trade-plans/${planId}`, accountId, { method: "DELETE" }); await load(); onRefresh?.(); }
    catch (cause) { setCommandError(cause instanceof Error ? cause.message : "草稿删除失败"); }
    finally { setCommandBusy(false); }
  }

  async function cancelActionPlan(plan: Record<string, any>) {
    const executions = Array.isArray(plan.execution_plans) ? plan.execution_plans : [];
    const activeExecution = executions.find((item: Record<string, any>) => !["COMPLETED", "CANCELLED", "EXPIRED"].includes(String(item.status)));
    const activeOrders = Array.isArray(activeExecution?.orders) ? activeExecution.orders : [];
    const hasOpenOrder = activeOrders.some((order: Record<string, any>) => LIVE_ORDER_STATUSES.has(String(order.status || "").toUpperCase()));
    const confirmed = window.confirm(activeExecution
      ? hasOpenOrder
        ? "确定取消执行并撤单吗？系统会停止后续执行，并向券商撤销未成交部分；已成交部分会保留。撤单是否成功以券商回报为准。"
        : "确定取消执行计划吗？系统会停止等待开始时间或价格触发条件，不会向券商发送委托。"
      : "确定取消这项计划吗？");
    if (!confirmed) return;
    setCommandBusy(true); setCancelBusyActionId(Number(plan.id)); setCommandError(null);
    try {
      if (activeExecution) await mutateTradeApi(`/api/trading/execution-plans/${activeExecution.id}/cancel`, accountId, { method: "POST" });
      else await mutateTradeApi(`/api/trade-plans/${plan.id}/cancel`, accountId, { method: "POST" });
      await load(); onRefresh?.();
    } catch (cause) { setCommandError(cause instanceof Error ? cause.message : "计划取消失败"); }
    finally { setCommandBusy(false); setCancelBusyActionId(null); }
  }

  async function createExecutionPlan(values: Record<string, any>) {
    const plan = executionPlan;
    if (!plan) return;
    const plannedQty = Number(plan.remaining_action_qty ?? actionRemainingQuantity(plan));
    if (!Number.isInteger(plannedQty) || plannedQty <= 0) { setCommandError("动作计划没有有效的计划数量，无法安排执行"); return; }
    const params: Record<string, any> = { order_type: values.order_type };
    const exchange = exchangeFromSymbol(plan.symbol);
    if (values.order_type === "LIMIT") params.limit_price = Number(values.price);
    else if (exchange === "SH") params.protection_price = Number(values.price);
    if (values.execution_type === "PRICE_TRIGGER") params.trigger_price = Number(values.trigger_price);
    if (values.execution_type === "PRICE_RANGE") { params.low_price = Number(values.low_price); params.high_price = Number(values.high_price); }
    setCommandBusy(true); setCommandError(null);
    try {
      const result = await mutateTradeApi("/api/trading/execution-plans", accountId, { method: "POST", body: JSON.stringify({
        trade_plan_id: plan.id,
        symbol: plan.symbol,
        side: ["REDUCE", "CLOSE"].includes(String(plan.action_type || plan.action)) ? "SELL" : "BUY",
        target_qty: plannedQty,
        execution_type: values.execution_type,
        valid_from: values.immediate ? null : (values.starts_at ? new Date(values.starts_at).toISOString() : null),
        client_request_id: values.client_request_id,
        execution_params: params,
      }) });
      if (!result.item?.id) throw new Error("执行方案保存接口未返回编号");
      await mutateTradeApi(`/api/trading/execution-plans/${result.item.id}/status`, accountId, { method: "PATCH", body: JSON.stringify({ status: "ACTIVE" }) });
      setExecutionPlan(null); await load(); onRefresh?.();
    } catch (cause) { setCommandError(cause instanceof Error ? cause.message : "执行方案创建失败"); }
    finally { setCommandBusy(false); }
  }

  function exportCsv() {
    if (!derived || !data) return;
    const rows = derived.items.map((trade) => {
      const position = derived.positions.get(String(trade.symbol));
      const tradeRisk = derived.risk.get(Number(trade.id));
      return [trade.symbol, trade.symbol_name, trade.trade_type, trade.status, position?.quantity ?? "", position?.market_value ?? "", tradeRisk?.capital ?? "", tradeRisk?.giveback ?? ""];
    });
    const csv = [["证券代码", "证券名称", "交易类型", "状态", "持仓数量", "持仓市值", "本金计划风险", "利润回吐风险"], ...rows]
      .map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(","))
      .join("\n");
    const url = URL.createObjectURL(new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `交易列表-${accountId}-${new Date().toISOString().slice(0, 10)}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (loading) return <div className="trading-trades-state">正在读取交易数据…</div>;
  if (error || !data || !derived) return <div className="trading-trades-state trading-trades-state-error"><p>{error || "交易列表读取失败"}</p><button type="button" onClick={() => void load()}>重新读取</button></div>;

  const equity = typeof data.account.equity === "number" ? data.account.equity : null;
  const openPnl = typeof data.account.unrealized_pnl === "number" ? data.account.unrealized_pnl : data.positions.reduce((sum, position) => sum + (typeof position.unrealized_pnl === "number" ? position.unrealized_pnl : 0), 0);
  const brokerMessage = data.account.account_type === "PLANNING" ? null : brokerState.accountId !== accountId || !brokerState.checked ? "正在检查交易通道状态" : brokerState.message;
  const statusTabs: Array<[StatusFilter, string]> = [["ALL", "全部"], ["PLANNED", "计划中"], ["ACTIVE", "持仓中"], ["CLOSING", "清仓中"], ["CLOSED", "已结束"], ["CANCELLED", "已取消"]];

  return <div className={`trading-trades-page ${compact ? "is-compact" : ""}`}>
    {(syncing || syncError) && <div className="trades-sync-status" role="status">{syncError ? "更新失败，当前显示已保存的数据：" + syncError : "正在更新交易数据" + (dataUpdatedAt ? " · 上次读取 " + dateLabel(dataUpdatedAt) : "")}</div>}
    <section className="trades-page-header">
      <div className="trades-title-group"><span className="trades-live-dot" /><h1>交易</h1><span>管理从建仓到清仓的完整交易过程</span><span className="trades-risk-badge"><span className="material-symbols-outlined">shield_with_heart</span>综合在途风险敞口：{money(data.account.total_risk ?? null)}{equity ? ` (${percent(Number(data.account.total_risk || 0) / equity * 100)} NAV)` : ""}</span></div>
      <div className="trades-page-actions">{brokerMessage && <span className="trades-broker-warning" role="status" title={brokerMessage}>{brokerMessage}</span>}<button type="button" className="trades-primary-action" onClick={() => onNavigate("open")}><Plus size={18} strokeWidth={2.5} aria-hidden="true" />创建计划</button></div>
    </section>
    {commandError && <div className="trading-inline-error" role="alert"><span>{commandError}</span><button type="button" onClick={() => setCommandError(null)} title="关闭提示" aria-label="关闭提示"><X size={16} /></button></div>}

    <section className="trades-filter-panel">
      <div className="trades-filter-tabs"><div>{statusTabs.map(([key, label]) => <button key={key} type="button" className={status === key ? "active" : ""} onClick={() => setStatus(key)}>{label} <small>({derived.counts[key]})</small></button>)}</div><span>持仓浮盈：<strong className={openPnl >= 0 ? "trades-profit" : "trades-loss"}>{money(openPnl)}</strong><i />持仓标的：<strong>{data.positions.length} 只</strong></span></div>
      <div className="trades-filter-controls"><div className="trades-filter-left"><label className="trades-search"><span className="material-symbols-outlined">search</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索股票代码 / 名称 / Playbook…" /></label><label className="trades-select"><select value={type} onChange={(event) => setType(event.target.value)}><option value="ALL">全部类型</option><option value="TREND">趋势交易</option><option value="REBOUND">反弹波段</option><option value="FIXED_TARGET">固定目标</option><option value="CUSTOM">自定义</option></select><span className="material-symbols-outlined">expand_more</span></label><label className="trades-select"><select value={days} onChange={(event) => setDays(event.target.value)}><option value="30">最近30天</option><option value="90">最近90天</option><option value="ALL">全部时间</option></select><span className="material-symbols-outlined">calendar_today</span></label></div><div className="trades-filter-actions">{dataUpdatedAt && <span className="trades-last-refresh" title={`上次成功读取：${dateLabel(dataUpdatedAt)}`}>更新于 {dateLabel(dataUpdatedAt)}</span>}<button type="button" title={syncing ? "正在刷新交易数据" : "刷新交易数据"} aria-label="刷新交易数据" disabled={syncing} onClick={() => { void load(); void checkBrokerState(); onRefresh?.(); }}><RefreshCw size={17} aria-hidden="true" className={syncing ? "animate-spin" : ""} /></button><button type="button" title="切换表格密度" aria-label="切换表格密度" onClick={() => setCompact((value) => !value)}><span className="material-symbols-outlined">view_column</span></button><button type="button" title="导出CSV" aria-label="导出CSV" onClick={exportCsv}><span className="material-symbols-outlined">download</span></button></div></div>
    </section>

    <section className="trades-table-panel"><div className="trades-table-scroll"><table><thead><tr><th>股票 / Playbook</th><th>类型</th><th>状态</th><th>持仓 / 可卖</th><th>现价 / 成本</th><th>浮动盈亏</th><th>计划风险（R）</th><th>回吐风险</th><th>最近动作</th><th>创建时间</th><th>操作</th></tr></thead><tbody>{derived.items.length ? derived.items.map((trade) => {
      const position = derived.positions.get(String(trade.symbol));
      const tradeRisk = derived.risk.get(Number(trade.id));
      const marketValue = typeof position?.market_value === "number" ? position.market_value : null;
      const pnl = typeof position?.unrealized_pnl === "number" ? position.unrealized_pnl : null;
      const isExpanded = expanded === Number(trade.id);
      const toggleExpanded = () => setExpanded(isExpanded ? null : Number(trade.id));
      const handleTradeRowClick = (event: React.MouseEvent<HTMLTableRowElement>) => {
        const target = event.target as HTMLElement;
        if (target.closest("button, a, input, select, textarea, details, summary")) return;
        toggleExpanded();
      };
      return <Fragment key={String(trade.id)}>
        <tr key={String(trade.id)} className={`trades-data-row ${isExpanded ? "is-expanded" : ""}`} onClick={handleTradeRowClick} aria-expanded={isExpanded}>
          <td><div className="trades-name-cell"><button type="button" className={`trades-expand ${isExpanded ? "expanded" : ""}`} aria-label={isExpanded ? "收起交易动作" : "展开交易动作"} onClick={toggleExpanded}><span className="material-symbols-outlined">chevron_right</span></button><button type="button" className="trades-symbol-button" onClick={() => onNavigate("trade", Number(trade.id))}><strong>{trade.symbol_name || "—"}</strong><small>{trade.symbol || "—"}</small>{trade.playbook && <em>{trade.playbook}</em>}</button></div></td><td><span className="trades-type-tag">{typeLabel(trade.trade_type)}</span></td><td><span className={`trades-status-tag trades-status-${String(trade.status).toLowerCase()}`}><i />{statusLabel(trade.status)}</span></td><td className="trades-number-cell"><strong>{position?.quantity ?? 0} 股</strong><small>{position?.available_quantity ?? 0} 股可卖</small></td><td className="trades-number-cell"><strong>{money(position?.market_price)}</strong><small>{money(position?.average_cost)}</small></td><td className={`trades-number-cell ${pnl !== null && pnl >= 0 ? "trades-profit" : "trades-loss"}`}><strong>{money(pnl)}</strong><small>{pnl !== null && marketValue ? percent(pnl / marketValue * 100) : "—"}</small></td><td className="trades-number-cell"><strong>{money(tradeRisk?.capital)}</strong><small className={tradeRisk?.capital == null ? "trades-risk-incomplete" : undefined}>{equity && tradeRisk?.capital !== null && tradeRisk?.capital !== undefined ? percent(tradeRisk.capital / equity * 100) + " NAV" : "风险数据不完整"}</small></td><td className="trades-number-cell"><strong>{money(tradeRisk?.giveback)}</strong><small>{position?.current_risk_reference_price ? `保护位 ${money(position.current_risk_reference_price)}` : "—"}</small></td><td><span className="trades-action-label">{derived.recentAction(trade) || "—"}</span></td><td className="trades-date-cell">{dateLabel(trade.created_at)}</td><td><div className="flex flex-wrap items-center gap-1"><button type="button" className="trades-detail-button" onClick={() => onNavigate("trade", Number(trade.id))}>详情</button><details className="trades-add-plan-menu"><summary title="为当前股票添加计划">添加计划</summary><div>{trade.status === "ACTIVE" ? <><button type="button" onClick={() => onNavigate("add", Number(trade.id))}>加仓</button><button type="button" onClick={() => onNavigate("reduce", Number(trade.id))}>减仓</button><button type="button" onClick={() => onNavigate("close", Number(trade.id))}>清仓</button></> : <span className="trades-add-plan-hint">{trade.status === "PLANNED" ? "建仓成交后可添加加仓、减仓或清仓计划" : "当前交易状态不能添加计划"}</span>}</div></details></div></td>
        </tr>
        {isExpanded && <tr key={`${trade.id}-details`} className="trades-leg-row"><td colSpan={11}><div className="trades-leg-content"><div className="trades-leg-heading"><span><span className="material-symbols-outlined">account_tree</span>交易动作（{Array.isArray(trade.plans) ? trade.plans.length : 0} 项）</span></div><div className="trades-leg-grid">{Array.isArray(trade.plans) && trade.plans.length ? trade.plans.map((item: any, index: number) => { const input = item.input_json || {}; const calc = item.calculation_snapshot_json || {}; const itemStatus = String(item.status || "").toUpperCase(); const isDraft = itemStatus === "DRAFT"; const executions = Array.isArray(item.execution_plans) ? item.execution_plans : []; const execution = executions[executions.length - 1]; const executionStatus = String(execution?.status || "").toUpperCase(); const executionOrders = execution && Array.isArray(execution.orders) ? execution.orders : null; const hasLiveBrokerOrder = Boolean(execution) && (executionOrders === null || executionOrders.some((order: any) => LIVE_ORDER_STATUSES.has(String(order.status || "").toUpperCase()))); const executionParams = execution?.execution_params_json || {}; const executionReason = String(execution?.status_reason || "").trim(); const maxOrderAmount = data.risk_profile?.max_single_order_notional; const limitPrice = executionParams.order_type === "LIMIT" ? Number(executionParams.limit_price) : NaN; const orderAmount = limitPrice * Number(execution?.remaining_qty); const exceedsOrderAmount = executionStatus === "ACTIVE" && executionOrders?.length === 0 && maxOrderAmount != null && Number.isFinite(orderAmount) && orderAmount > Number(maxOrderAmount); const activeExecution = execution && !["COMPLETED", "CANCELLED", "EXPIRED"].includes(executionStatus); const canEdit = canEditTradePlan(item); const remainingActionQty = actionRemainingQuantity(item); const canExecute = ["READY", "PARTIALLY_EXECUTED"].includes(itemStatus) && canEdit && !activeExecution && !hasLiveBrokerOrder && remainingActionQty > 0; const editAction = () => item.action_type === "OPEN" ? onNavigate("open", undefined, Number(item.id)) : onNavigate(item.action_type === "ADD" ? "add" : item.action_type === "REDUCE" ? "reduce" : "close", Number(trade.id), Number(item.id)); const openAction = () => canEdit ? editAction() : onNavigate("action", Number(trade.id), Number(item.id)); const inputPrice = input.reference_entry_price ?? input.reference_price; return <div key={String(item.id ?? index)} className="trades-leg-item"><button type="button" className="trades-leg-summary" onClick={openAction}><span className={`trades-leg-tag ${item.action_type === "CLOSE" || item.action_type === "REDUCE" ? "exit" : ""}`}>{actionLabel(item.action_type || item.action)} #{item.sequence_no ?? index + 1}</span><strong className="trades-leg-quantity">计划 {calc.planned_qty ?? input.manual_planned_qty ?? item.target_qty ?? "—"} 股</strong><span className="trades-leg-price">参考价 {money(inputPrice)}</span><span className="trades-leg-status">{statusLabel(item.status)}</span>{exceedsOrderAmount && <span className="trades-order-limit-warning" title="请调整计划数量或账户单笔最大金额">委托金额 {money(orderAmount)} 超过单笔上限 {money(Number(maxOrderAmount))}</span>}{execution && <span className="trades-execution-rule">{({ LIMIT: "立即提交", PERSISTENT_LIMIT: "持续限价", PRICE_TRIGGER: "触价提交", PRICE_RANGE: "区间提交" } as Record<string, string>)[execution.execution_type] || execution.execution_type} · {executionSummaryLabel(execution, executionOrders, executionReason)}</span>}</button><div className="trades-leg-controls">{canEdit && <><button type="button" className="trades-detail-button trades-draft-edit" onClick={editAction}>编辑</button>{isDraft && <button type="button" className="trades-detail-button trades-action-delete" disabled={commandBusy} onClick={() => void deleteDraft(Number(item.id))} title="删除草稿" aria-label="删除草稿"><Trash2 size={14} />删除</button>}</>}{canExecute && <button type="button" className="trades-detail-button trades-execute-action" onClick={() => { setCommandError(null); setExecutionPlan({ ...item, remaining_action_qty: remainingActionQty }); }}>执行</button>}{activeExecution && <><button type="button" className="trades-detail-button trades-action-delete" disabled={commandBusy} onClick={() => void cancelActionPlan(item)} title="停止执行并撤销未成交委托">{cancelBusyActionId === Number(item.id) ? <><RefreshCw size={14} className="animate-spin" />撤单中</> : "取消"}</button></>}{itemStatus === "READY" && !execution && <button type="button" className="trades-detail-button trades-action-delete" disabled={commandBusy} onClick={() => void cancelActionPlan(item)}>取消计划</button>}</div></div>; }) : <p>当前交易暂无动作计划。</p>}</div></div></td></tr>}
      </Fragment>;
    }) : <tr><td colSpan={11} className="trades-empty">当前筛选条件下没有交易记录。</td></tr>}</tbody></table></div><footer className="trades-table-footer"><span>共 {derived.items.length} 笔交易</span><span>当前显示全部符合条件的记录</span></footer></section>
        {executionPlan && <ExecutionPlanDialog plan={executionPlan} busy={commandBusy} error={commandError} onClose={() => setExecutionPlan(null)} onSubmit={createExecutionPlan} />}
  </div>;
}

function ExecutionPlanDialog({ plan, busy, error, onClose, onSubmit }: { plan: Record<string, any>; busy: boolean; error: string | null; onClose: () => void; onSubmit: (values: Record<string, any>) => Promise<void> }) {
  const [clientRequestId] = useState(() => crypto.randomUUID());
  const [executionType, setExecutionType] = useState("LIMIT");
  const exchange = exchangeFromSymbol(plan.symbol);
  const [orderType, setOrderType] = useState("LIMIT");
  const defaultPrice = executionDefaultPrice(plan);
  const [orderPrice, setOrderPrice] = useState(defaultPrice);
  const [triggerPrice, setTriggerPrice] = useState(defaultPrice);
  const [lowPrice, setLowPrice] = useState(defaultPrice);
  const [highPrice, setHighPrice] = useState(defaultPrice);
  const [initialStart] = useState(() => localDateTimeInputValue(new Date()));
  const [startsAt, setStartsAt] = useState(initialStart);
  const requiresPrice = orderType === "LIMIT" || exchange === "SH";
  const priceLabel = orderType === "LIMIT" ? "委托限价" : exchange === "SH" ? "保护限价" : "";
  const priceRequiredAndMissing = requiresPrice && !orderPrice;
  const formDisabled = busy || priceRequiredAndMissing || (executionType === "PRICE_TRIGGER" && !triggerPrice) || (executionType === "PRICE_RANGE" && (!lowPrice || !highPrice));
  return <div className="execution-composer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className="execution-composer" role="dialog" aria-modal="true" aria-label="安排动作执行"><header className="trading-panel-title"><div><h2>安排{actionLabel(plan.action_type || plan.action)}执行</h2><span>{plan.security_name || plan.symbol} · 计划 {(plan.remaining_action_qty ?? plan.calculation_snapshot_json?.planned_qty ?? plan.target_qty).toLocaleString("zh-CN")} 股</span></div><button type="button" title="关闭" aria-label="关闭" onClick={onClose}><X size={18} /></button></header><div className="trading-form-grid"><label>委托类型<select value={orderType} onChange={(event) => setOrderType(event.target.value)}>{orderTypesForExchange(exchange).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><p className="execution-composer-note">{orderTypeDescription(orderType, exchange)}</p><label>提交时机<select value={executionType} onChange={(event) => setExecutionType(event.target.value)}><option value="LIMIT">立即提交</option><option value="PRICE_TRIGGER">到达触发价格时提交</option><option value="PRICE_RANGE">进入价格区间时提交</option></select></label>{requiresPrice && <label>{priceLabel}<input type="number" min="0.01" step="0.01" value={orderPrice} onChange={(event) => setOrderPrice(event.target.value)} /></label>}{executionType === "PRICE_TRIGGER" && <label>触发价格<input type="number" min="0.01" step="0.01" value={triggerPrice} onChange={(event) => setTriggerPrice(event.target.value)} /></label>}{executionType === "PRICE_RANGE" && <><label>区间最低价<input type="number" min="0.01" step="0.01" value={lowPrice} onChange={(event) => setLowPrice(event.target.value)} /></label><label>区间最高价<input type="number" min="0.01" step="0.01" value={highPrice} onChange={(event) => setHighPrice(event.target.value)} /></label></>}<label>开始执行时间（可选）<input type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} /></label></div><p className="execution-composer-note">“按设定时间执行”会在选定时间到达后启动；“立即执行”会忽略该时间并马上启动。{executionType === "LIMIT" ? "启动后提交一次委托。" : "达到触发条件后提交所选委托。"}{orderType !== "LIMIT" && exchange === "SH" ? " 上交所市价单必须填写保护限价。" : ""}{orderType !== "LIMIT" && exchange === "SZ" ? " 深交所市价单不带保护限价，成交价格按市场盘口决定。" : ""}</p>{error && <p className="trading-inline-error" role="alert">{error}</p>}<footer className="trading-form-actions"><button type="button" onClick={onClose}>返回</button><button type="button" disabled={formDisabled || !startsAt} onClick={() => void onSubmit({ execution_type: executionType, order_type: orderType, price: orderPrice, trigger_price: triggerPrice, low_price: lowPrice, high_price: highPrice, starts_at: startsAt, immediate: false, client_request_id: clientRequestId })}>{busy ? "正在保存…" : "按设定时间执行"}</button><button type="button" className="trades-primary-action" disabled={formDisabled} onClick={() => void onSubmit({ execution_type: executionType, order_type: orderType, price: orderPrice, trigger_price: triggerPrice, low_price: lowPrice, high_price: highPrice, starts_at: "", immediate: true, client_request_id: clientRequestId })}>{busy ? "正在启动…" : "立即执行"}</button></footer></section></div>;
}
