"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Ban, Check, ChevronDown, ChevronLeft, ChevronRight, CircleDollarSign, Clock3, Download, FileText, RefreshCw, Search, X } from "lucide-react";
import type { TradingPageKey } from "../types";
import { actionLabel, dateLabel, executionTypeLabel, money, numberLabel, readTradingJson, sideLabel, statusLabel, statusTone, type TradingRecord } from "../common/tradingData";
import { orderTypeLabel } from "../orderTypes";

type Props = { accountId: number; tradeId?: number | null; onNavigate: (page: TradingPageKey, tradeId?: number, planId?: number) => void; onRefresh?: () => void };
type OrderFilter = "ALL" | "PENDING" | "FILLED" | "CLOSED";

const PENDING = ["PENDING_SUBMIT", "QUEUED", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"];
const CLOSED = ["CANCELLED", "CANCELED", "CANCELLED_ORDER", "REJECTED", "FAILED", "EXPIRED"];

function State({ loading, error, retry }: { loading: boolean; error: string | null; retry: () => void }) {
  if (loading) return <div className="trading-page-state">正在读取订单流水…</div>;
  if (error) return <div className="trading-page-state trading-page-state-error"><strong>{error}</strong><button type="button" onClick={retry}>重新读取</button></div>;
  return null;
}

function orderStatusFilter(item: TradingRecord, filter: OrderFilter) {
  const value = String(item.status || "");
  if (filter === "ALL") return true;
  if (filter === "PENDING") return PENDING.includes(value);
  if (filter === "FILLED") return value === "FILLED";
  return CLOSED.includes(value);
}

function localDateKey(value: unknown) {
  if (!value) return "";
  const date = new Date(typeof value === "number" ? value : String(value));
  if (Number.isNaN(date.getTime())) return "";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatOrderTime(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return <><span>{date.toLocaleDateString("zh-CN")}</span><strong>{date.toLocaleTimeString("zh-CN", { hour12: false })}</strong></>;
}

function Detail({ item, onClose }: { item: TradingRecord; onClose: () => void }) {
  const weightedFill = Array.isArray(item.fills) ? item.fills.reduce((sum: number, fill: TradingRecord) => sum + Number(fill.quantity || 0) * Number(fill.price || 0), 0) : 0;
  const fillQty = Array.isArray(item.fills) ? item.fills.reduce((sum: number, fill: TradingRecord) => sum + Number(fill.quantity || 0), 0) : Number(item.filled_quantity || 0);
  const averageFill = fillQty > 0 ? weightedFill / fillQty : null;
  return <div className="trading-drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><aside className="trading-drawer orders-detail-drawer" role="dialog" aria-modal="true" aria-label="订单详情">
    <div className="trading-drawer-header"><div><small>订单详情</small><h2>{item.symbol_name || item.trade?.symbol_name || item.symbol || "订单"}</h2><span>{item.symbol || "—"} · {sideLabel(item.side)} · {statusLabel(item.status)}</span></div><button type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button></div>
    <section className="trading-drawer-section"><h3>委托信息</h3><dl><div><dt>委托时间</dt><dd>{dateLabel(item.created_at)}</dd></div><div><dt>委托类型</dt><dd>{item.order_type ? orderTypeLabel(item.order_type) : executionTypeLabel(item.execution_type || item.execution?.execution_type)}</dd></div><div><dt>委托价格</dt><dd>{item.price == null ? "未填写价格" : money(Number(item.price))}</dd></div><div><dt>委托数量 / 已成交</dt><dd>{numberLabel(Number(item.quantity))} / {numberLabel(fillQty)} 股</dd></div><div><dt>成交均价</dt><dd>{averageFill == null ? "—" : money(averageFill)}</dd></div><div><dt>当前状态</dt><dd>{statusLabel(item.status)}</dd></div></dl></section>
    <section className="trading-drawer-section"><h3>订单编号</h3><dl><div><dt>券商合同号</dt><dd>{item.broker_order_id || "尚未返回"}</dd></div><div><dt>系统订单号</dt><dd>{item.client_order_id || "—"}</dd></div></dl></section>
    <section className="trading-drawer-section"><h3>成交回报</h3>{Array.isArray(item.fills) && item.fills.length ? <ul className="trading-audit-list">{item.fills.map((fill: TradingRecord) => <li key={String(fill.id)}><strong>{dateLabel(fill.filled_at || fill.created_at)}</strong><span>{money(Number(fill.price))} · {numberLabel(Number(fill.quantity))} 股</span></li>)}</ul> : <p className="trading-empty">该订单暂无成交回报。</p>}</section>
    <section className="trading-drawer-section"><h3>关联交易</h3><div className="orders-linkage"><p><span>交易</span>{item.trade ? `${item.trade.symbol_name || item.trade.symbol || "交易"} · #${item.trade.id}` : "未关联"}</p><p><span>动作计划</span>{item.execution?.trade_plan_id ? `${actionLabel(item.tradePlan?.action_type || item.execution.action_type)} · #${item.execution.trade_plan_id}` : "未关联"}</p><p><span>执行安排</span>{item.execution?.id ? `#${item.execution.id} · ${statusLabel(item.execution.status)}` : "未关联"}</p></div></section>
  </aside></div>;
}

export default function OrdersPage({ accountId, tradeId, onNavigate, onRefresh }: Props) {
  const [items, setItems] = useState<TradingRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<OrderFilter>("ALL");
  const [direction, setDirection] = useState("ALL");
  const [dateRange, setDateRange] = useState("ALL");
  const [pageSize, setPageSize] = useState(20);
  const [page, setPage] = useState(1);
  const [now, setNow] = useState(0);
  const [selected, setSelected] = useState<TradingRecord | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [orders, executions, trades, fills] = await Promise.all([
        readTradingJson("/api/trading/orders", accountId),
        readTradingJson("/api/trading/execution-plans", accountId),
        readTradingJson("/api/trades", accountId),
        readTradingJson("/api/trading/fills", accountId),
      ]);
      if (!Array.isArray(orders.items) || !Array.isArray(executions.items) || !Array.isArray(trades.items) || !Array.isArray(fills.items)) throw new Error("订单数据不完整，请刷新后重试");
      const executionMap = new Map(executions.items.map((item: TradingRecord) => [Number(item.id), item]));
      const tradeMap = new Map<number, TradingRecord>();
      const tradePlanMap = new Map<number, TradingRecord>();
      trades.items.forEach((trade: TradingRecord) => (Array.isArray(trade.plans) ? trade.plans : []).forEach((plan: TradingRecord) => { tradeMap.set(Number(plan.id), trade); tradePlanMap.set(Number(plan.id), plan); }));
      const fillsMap = new Map<number, TradingRecord[]>();
      fills.items.forEach((fill: TradingRecord) => fillsMap.set(Number(fill.order_id), [...(fillsMap.get(Number(fill.order_id)) || []), fill]));
      setItems(orders.items.map((order: TradingRecord) => {
        const execution = executionMap.get(Number(order.execution_plan_id));
        const tradePlan = execution ? tradePlanMap.get(Number(execution.trade_plan_id)) : undefined;
        return { ...order, execution, tradePlan, trade: execution ? tradeMap.get(Number(execution.trade_plan_id)) : undefined, fills: fillsMap.get(Number(order.id)) || [] };
      }));
      setNow(Date.now());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "订单读取失败");
    } finally {
      setLoading(false);
    }
  }, [accountId]);

  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);

  const todayOrders = useMemo(() => {
    const today = localDateKey(now || Date.now());
    return items.filter((item) => localDateKey(item.created_at) === today);
  }, [items, now]);
  const baseVisible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const rangeMs = dateRange === "TODAY" ? 24 * 60 * 60 * 1000 : dateRange === "7D" ? 7 * 24 * 60 * 60 * 1000 : dateRange === "30D" ? 30 * 24 * 60 * 60 * 1000 : null;
    return items.filter((item) => {
      const trade = item.trade || {};
      const text = `${item.symbol || ""} ${item.symbol_name || ""} ${trade.symbol || ""} ${trade.symbol_name || ""} ${item.client_order_id || ""} ${item.broker_order_id || ""}`.toLowerCase();
      const created = item.created_at ? new Date(String(item.created_at)).getTime() : NaN;
      const sameTrade = tradeId == null || Number(trade.id) === Number(tradeId);
      const dateMatch = rangeMs === null || (now > 0 && Number.isFinite(created) && now - created <= rangeMs && created <= now);
      return sameTrade && (!needle || text.includes(needle)) && (direction === "ALL" || String(item.side) === direction) && dateMatch;
    });
  }, [items, query, direction, dateRange, now, tradeId]);
  const visible = useMemo(() => baseVisible.filter((item) => orderStatusFilter(item, status)), [baseVisible, status]);
  const pageCount = Math.max(1, Math.ceil(visible.length / pageSize));
  const pageItems = visible.slice((page - 1) * pageSize, page * pageSize);
  const counts = useMemo(() => ({
    total: todayOrders.length,
    filled: todayOrders.filter((item) => item.status === "FILLED").length,
    working: todayOrders.filter((item) => PENDING.includes(String(item.status))).length,
    closed: todayOrders.filter((item) => CLOSED.includes(String(item.status))).length,
    rejected: todayOrders.filter((item) => ["REJECTED", "FAILED", "EXPIRED"].includes(String(item.status))).length,
    cancelled: todayOrders.filter((item) => ["CANCELLED", "CANCELED", "CANCELLED_ORDER"].includes(String(item.status))).length,
  }), [todayOrders]);
  const tabCounts = useMemo(() => ({
    ALL: baseVisible.length,
    PENDING: baseVisible.filter((item) => orderStatusFilter(item, "PENDING")).length,
    FILLED: baseVisible.filter((item) => orderStatusFilter(item, "FILLED")).length,
    CLOSED: baseVisible.filter((item) => orderStatusFilter(item, "CLOSED")).length,
  }), [baseVisible]);
  const fillSummary = useMemo(() => todayOrders.reduce((summary, item) => {
    for (const fill of Array.isArray(item.fills) ? item.fills : []) {
      const value = Number(fill.quantity || 0) * Number(fill.price || 0);
      if (!Number.isFinite(value)) continue;
      summary.total += value;
      if (item.side === "BUY") summary.buy += value;
      if (item.side === "SELL") summary.sell += value;
    }
    return summary;
  }, { total: 0, buy: 0, sell: 0 }), [todayOrders]);
  const syncTime = items.reduce<string | null>((latest, item) => {
    const candidate = String(item.updated_at || item.created_at || "");
    return !latest || (candidate && new Date(candidate).getTime() > new Date(latest).getTime()) ? candidate || latest : latest;
  }, null);

  function exportCsv() {
    const headers = ["委托时间", "证券代码", "证券名称", "所属交易", "动作", "买卖方向", "委托类型", "委托价格", "委托数量", "成交数量", "订单状态", "券商合同号", "系统订单号"];
    const rows = visible.map((item) => [item.created_at, item.symbol, item.symbol_name || item.trade?.symbol_name, item.trade?.id, item.tradePlan?.action_type, sideLabel(item.side), item.order_type ? orderTypeLabel(item.order_type) : executionTypeLabel(item.execution_type || item.execution?.execution_type), item.price, item.quantity, item.filled_quantity, statusLabel(item.status), item.broker_order_id, item.client_order_id]);
    const csv = [headers, ...rows].map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(",")).join("\r\n");
    const blob = new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `订单流水_${new Date().toISOString().slice(0, 10)}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function cancel(item: TradingRecord) {
    setError(null);
    try {
      await readTradingJson(`/api/trading/orders/${item.id}/cancel`, accountId, { method: "POST" });
      await load();
      onRefresh?.();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "撤单失败");
    }
  }
  const cancellable = (item: TradingRecord) => PENDING.includes(String(item.status));
  const tabs: Array<{ value: OrderFilter; label: string }> = [{ value: "ALL", label: "全部" }, { value: "PENDING", label: "待处理" }, { value: "FILLED", label: "已成交" }, { value: "CLOSED", label: "已结束" }];

  useEffect(() => { setPage(1); }, [query, status, direction, dateRange, tradeId, pageSize]);

  return <div className="trading-react-page orders-page orders-prototype-page">
    <header className="orders-page-header">
      <div className="orders-page-heading"><div className="orders-breadcrumb"><span><i />交易执行</span><b>/</b><strong>ORDER LEDGER</strong><b>/</b><span>订单流水</span></div><div className="orders-title-line"><h1>订单流水</h1><span className="orders-live-badge">订单记录</span></div><p>查看委托、成交回报与订单状态。</p></div>
      <div className="orders-page-actions"><button type="button" className="orders-button orders-button-secondary" onClick={() => onNavigate("overview")}><ArrowLeft size={15} />返回总览</button><button type="button" className="orders-button orders-button-primary" onClick={() => { void load(); onRefresh?.(); }} disabled={loading}><RefreshCw size={15} className={loading ? "orders-spin" : ""} />刷新订单</button></div>
    </header>

    <State loading={loading} error={error} retry={() => void load()} />
    {!loading && !error && <>
      <section className="orders-summary-grid" aria-label="今日订单汇总">
        <article className="orders-summary-card orders-summary-blue"><div className="orders-summary-label"><span>今日委托</span><i><FileText size={16} /></i></div><strong>{numberLabel(counts.total)}<small>笔</small></strong><p><i />当前账户今日委托</p></article>
        <article className="orders-summary-card orders-summary-green"><div className="orders-summary-label"><span>已完全成交</span><i><Check size={16} /></i></div><strong>{numberLabel(counts.filled)}<small>笔</small></strong><p><i />{counts.total ? `${(counts.filled / counts.total * 100).toFixed(1)}% 委托已全部成交` : "今日暂无成交委托"}</p></article>
        <article className="orders-summary-card orders-summary-amber"><div className="orders-summary-label"><span>部分成交 / 待处理</span><i><Clock3 size={16} /></i></div><strong>{numberLabel(counts.working)}<small>笔</small></strong><p><i />仍有数量等待处理</p></article>
        <article className="orders-summary-card orders-summary-red"><div className="orders-summary-label"><span>已撤单 / 废单</span><i><Ban size={16} /></i></div><strong>{numberLabel(counts.closed)}<small>笔</small></strong><p><i />主动撤单 {numberLabel(counts.cancelled)} · 拒单或失效 {numberLabel(counts.rejected)}</p></article>
        <article className="orders-summary-card orders-summary-total"><div><div className="orders-summary-label"><span>今日实际成交总额</span></div><strong>{money(fillSummary.total)}</strong><p>买入 {money(fillSummary.buy)} <span>/</span> 卖出 {money(fillSummary.sell)}</p></div><i><CircleDollarSign size={17} /></i></article>
      </section>

      <section className="orders-ledger-card">
        <div className="orders-filter-row">
          <div className="orders-filter-tabs" role="tablist" aria-label="订单状态筛选">{tabs.map((tab) => <button key={tab.value} type="button" role="tab" aria-selected={status === tab.value} className={status === tab.value ? "active" : ""} onClick={() => setStatus(tab.value)}>{tab.label}<small>{numberLabel(tabCounts[tab.value])}</small></button>)}</div>
          <div className="orders-ledger-info"><span><i />订单记录已同步</span><b />显示 <strong>{numberLabel(visible.length)}</strong> / {numberLabel(baseVisible.length)} 条</div>
        </div>
        <div className="orders-tools-row">
          <label className="orders-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索证券代码、名称、订单号…" /></label>
          <label className="orders-select"><select value={direction} onChange={(event) => setDirection(event.target.value)}><option value="ALL">全部方向</option><option value="BUY">买入</option><option value="SELL">卖出</option></select><ChevronDown size={14} /></label>
          <label className="orders-select"><select value={dateRange} onChange={(event) => setDateRange(event.target.value)}><option value="ALL">全部日期</option><option value="TODAY">最近 24 小时</option><option value="7D">最近 7 天</option><option value="30D">最近 30 天</option></select><ChevronDown size={14} /></label>
          <div className="orders-tool-spacer" />
          <button type="button" className="orders-button orders-button-export" onClick={exportCsv} disabled={!visible.length}><Download size={14} />导出报表</button>
          <button type="button" className="orders-icon-button" title="刷新订单" aria-label="刷新订单" onClick={() => { void load(); onRefresh?.(); }} disabled={loading}><RefreshCw size={15} className={loading ? "orders-spin" : ""} /></button>
        </div>

        <div className="orders-table-meta"><strong>订单明细</strong><span>共 {numberLabel(visible.length)} 条记录</span><div><span><i className="orders-legend-buy" />买入</span><span><i className="orders-legend-sell" />卖出</span>{syncTime && <span>最近更新：{dateLabel(syncTime)}</span>}</div></div>
        <div className="orders-table-scroll"><table className="orders-table"><thead><tr><th>委托时间</th><th>标的证券</th><th>所属交易 / 动作</th><th>委托类型</th><th className="numeric">报单价 / 成交均价</th><th>委托 / 成交数量</th><th>订单状态</th><th>券商合同号 / 系统订单号</th><th className="center">操作</th></tr></thead><tbody>
          {pageItems.length ? pageItems.map((item) => {
            const quantity = Number(item.quantity || 0);
            const filled = Number(item.filled_quantity || 0);
            const percent = quantity > 0 ? Math.min(100, Math.round(filled / quantity * 100)) : 0;
            const weighted = (item.fills || []).reduce((sum: number, fill: TradingRecord) => sum + Number(fill.quantity || 0) * Number(fill.price || 0), 0);
            const fillQty = (item.fills || []).reduce((sum: number, fill: TradingRecord) => sum + Number(fill.quantity || 0), 0);
            const avgFill = fillQty > 0 ? weighted / fillQty : null;
            const sideClass = item.side === "BUY" ? "buy" : "sell";
            const action = item.tradePlan?.action_type || item.execution?.action_type;
            return <tr key={String(item.id)} onClick={() => setSelected(item)} className={item.status === "PARTIALLY_FILLED" ? "is-partial" : ""}>
              <td className="orders-time-cell">{formatOrderTime(item.created_at)}</td>
              <td><div className="orders-security"><strong>{item.symbol_name || item.trade?.symbol_name || item.symbol || "—"}</strong><div className="orders-security-meta"><small>{item.symbol || "—"}</small><span className={`orders-side-tag ${sideClass}`}>{sideLabel(item.side)}</span></div></div></td>
              <td><div className="orders-trade-cell">{item.trade ? <button type="button" onClick={(event) => { event.stopPropagation(); onNavigate("trade", Number(item.trade.id)); }}><span>{item.trade.symbol_name || item.trade.symbol || `交易 #${item.trade.id}`}</span><small>交易 · #{item.trade.id}</small></button> : <><span>未关联交易</span><small>—</small></>}{action && <em>{actionLabel(action)}{item.tradePlan?.sequence_no ? ` #${item.tradePlan.sequence_no}` : ""}</em>}</div></td>
              <td><span className="orders-type-tag">{item.order_type || item.order_type_name || item.execution?.order_type ? orderTypeLabel(item.order_type || item.order_type_name || item.execution?.order_type) : executionTypeLabel(item.execution_type || item.execution?.execution_type)}</span></td>
              <td className="numeric orders-price-cell"><strong>{item.price == null ? "市价" : money(Number(item.price))}</strong><small>{avgFill == null ? "—" : money(avgFill)}</small></td>
              <td><div className="orders-fill-cell"><div><strong>{numberLabel(filled)} / {numberLabel(quantity)} 股</strong><span>{percent}%</span></div><i><b style={{ width: `${percent}%` }} /></i></div></td>
              <td><span className={`orders-status-pill orders-status-${statusTone(item.status)}`}><i />{statusLabel(item.status)}</span></td>
              <td className="orders-id-cell"><strong>{item.broker_order_id || "券商编号待返回"}</strong><small>{item.client_order_id || "—"}</small></td>
              <td className="center"><div className="orders-row-actions"><button type="button" onClick={(event) => { event.stopPropagation(); setSelected(item); }}>详情</button>{cancellable(item) && <button type="button" className="danger" onClick={(event) => { event.stopPropagation(); void cancel(item); }}>撤单</button>}</div></td>
            </tr>;
          }) : <tr><td colSpan={9} className="orders-empty">{items.length ? "当前筛选条件下没有订单记录。" : "当前账户暂无订单记录。"}</td></tr>}
        </tbody></table></div>
        <footer className="orders-table-footer"><span><i />最近记录更新：{syncTime ? dateLabel(syncTime) : "暂无订单数据"}</span><div><label>每页<select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}><option value={20}>20 条</option><option value={50}>50 条</option><option value={100}>100 条</option></select></label><span>{visible.length ? `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, visible.length)} / ${visible.length}` : "0 条"}</span><button type="button" aria-label="上一页" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft size={16} /></button><strong>{page}</strong><button type="button" aria-label="下一页" disabled={page >= pageCount} onClick={() => setPage((value) => Math.min(pageCount, value + 1))}><ChevronRight size={16} /></button></div></footer>
      </section>
    </>}
    {selected && <Detail item={selected} onClose={() => setSelected(null)} />}
  </div>;
}
