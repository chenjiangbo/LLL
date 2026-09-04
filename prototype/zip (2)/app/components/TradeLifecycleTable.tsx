"use client";

import { Fragment, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Plus, RefreshCw, Search } from "lucide-react";

const tradeTypeLabel: Record<string, string> = { TREND: "趋势交易", REBOUND: "反弹/波段", FIXED_TARGET: "固定目标", CUSTOM: "自定义" };
const tradeStatusLabel: Record<string, string> = { PLANNED: "计划中", ACTIVE: "进行中", CLOSING: "清仓中", CLOSED: "已结束", CANCELLED: "已取消" };
const actionLabel: Record<string, string> = { OPEN: "OPEN 建仓", ADD: "ADD 加仓", REDUCE: "REDUCE 计划减仓", CLOSE: "CLOSE 清仓" };

function money(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`
    : "—";
}

function statusClass(status: string) {
  if (status === "ACTIVE") return "bg-[#c9f3d8] text-[#145c39]";
  if (status === "CLOSING") return "bg-[#ffd9df] text-[#9a2447]";
  if (status === "CLOSED") return "bg-[#e9e9e5] text-[#5c625e]";
  return "bg-[#efeee9] text-[#555c58]";
}

type Props = {
  items: any[];
  loading: boolean;
  query: string;
  setQuery: (value: string) => void;
  statusFilter: string;
  setStatusFilter: (value: string) => void;
  typeFilter: string;
  setTypeFilter: (value: string) => void;
  onRefresh: () => void;
  onCreate: () => void;
  onOpen: (tradeId: number) => void;
};

export default function TradeLifecycleTable({ items, loading, query, setQuery, statusFilter, setStatusFilter, typeFilter, setTypeFilter, onRefresh, onCreate, onOpen }: Props) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const rows = useMemo(() => items.filter((item) => {
    const text = `${item.symbol} ${item.symbol_name} ${item.playbook_id || ""}`.toLowerCase();
    return text.includes(query.trim().toLowerCase()) && (statusFilter === "ALL" || item.status === statusFilter) && (typeFilter === "ALL" || item.trade_type === typeFilter);
  }), [items, query, statusFilter, typeFilter]);
  const counts = useMemo(() => ({
    all: items.length,
    active: items.filter((item) => item.status === "ACTIVE").length,
    planned: items.filter((item) => item.status === "PLANNED").length,
    closing: items.filter((item) => item.status === "CLOSING").length,
    closed: items.filter((item) => item.status === "CLOSED").length,
  }), [items]);
  const toggle = (id: number) => setExpanded((current) => {
    const next = new Set(current);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  return (
    <div className="min-h-[calc(100vh-64px)] bg-[#f8f7f2] px-6 py-5 text-[#191c1d] xl:px-7">
      <div className="mx-auto max-w-[1800px]">
        <section className="mb-4 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[#eee9df] bg-white px-5 py-4 shadow-[0_2px_10px_rgba(25,28,29,0.04)]">
          <div className="min-w-[320px]">
            <div className="flex items-center gap-2">
              <span className="grid h-7 w-7 place-items-center rounded-md border border-[#1e6c43] text-[#0f5238]">⌘</span>
              <div><h1 className="font-serif text-xl font-bold">Trade 生命周期中心</h1><p className="text-xs text-[#52616b]">管理从建仓、加仓到清仓的完整 Trade 生命周期</p></div>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
              <span className="rounded-full bg-[#f4f3ee] px-2.5 py-1">全部 {counts.all}</span>
              <span className="rounded-full bg-[#f4f3ee] px-2.5 py-1 text-[#145c39]">● 进行中 {counts.active}</span>
              <span className="rounded-full bg-[#f4f3ee] px-2.5 py-1 text-[#59615d]">● 计划中 {counts.planned}</span>
              <span className="rounded-full bg-[#f4f3ee] px-2.5 py-1 text-[#9a2447]">● 清仓中 {counts.closing}</span>
              <span className="rounded-full bg-[#f4f3ee] px-2.5 py-1 text-[#59615d]">● 已结束 {counts.closed}</span>
              <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} className="rounded-full border-0 bg-[#f4f3ee] px-2.5 py-1 text-xs outline-none">
                <option value="ALL">类型：全部类型</option><option value="TREND">趋势交易</option><option value="REBOUND">反弹/波段</option><option value="FIXED_TARGET">固定目标</option><option value="CUSTOM">自定义</option>
              </select>
            </div>
          </div>
          <div className="flex min-w-[360px] flex-1 items-center justify-end gap-2">
            <label className="relative max-w-[360px] flex-1"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#6d746f]" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="按股票代码 / 名称 / Playbook 搜索" className="input pl-9" /></label>
            <button onClick={onRefresh} title="刷新交易" className="grid h-10 w-10 place-items-center rounded-lg border border-[#d9d3c8] bg-white"><RefreshCw className={loading ? "h-4 w-4 animate-spin" : "h-4 w-4"} /></button>
            <button onClick={onCreate} className="inline-flex h-10 shrink-0 items-center gap-2 rounded-lg bg-[#0f5238] px-4 text-sm font-bold text-white"><Plus className="h-4 w-4" />创建新交易</button>
          </div>
        </section>

        <section className="overflow-hidden rounded-2xl border border-[#eee9df] bg-white shadow-[0_2px_10px_rgba(25,28,29,0.04)]">
          <div className="overflow-x-auto">
            <table className="min-w-[1450px] w-full text-left text-sm">
              <thead className="border-b border-[#eee9df] bg-[#faf9f5] text-xs font-medium text-[#52616b]"><tr>{["展开", "股票标的", "交易类型", "战法体系 (PLAYBOOK)", "状态", "持仓 / 可卖", "现价 / 成本", "浮动盈亏", "本金计划风险", "利润回吐风险", "最近动作"].map((label) => <th key={label} className="px-4 py-3 font-medium">{label}</th>)}</tr></thead>
              <tbody>{rows.map((item) => {
                const position = item.position || {};
                const latest = item.plans?.[item.plans.length - 1];
                const isExpanded = expanded.has(item.id);
                return <Fragment key={item.id}>
                  <tr key={item.id} className="border-b border-[#eee9df] hover:bg-[#fdfcf9]">
                    <td className="px-4 py-4"><button onClick={() => toggle(item.id)} aria-label={isExpanded ? "收起执行动作明细" : "展开执行动作明细"} className="grid h-8 w-8 place-items-center rounded-md bg-[#f1f0eb]">{isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</button></td>
                    <td className="px-4 py-4"><button onClick={() => onOpen(item.id)} className="text-left"><b className="block text-lg">{item.symbol_name}</b><span className="text-xs text-[#52616b]">{item.symbol}</span></button></td>
                    <td className="px-4 py-4"><span className="rounded-md bg-[#f0eee8] px-2 py-1.5 text-xs">{tradeTypeLabel[item.trade_type] || "自定义"}</span></td>
                    <td className="px-4 py-4"><span className="text-[#404943]">{item.playbook_id || "—"}</span></td>
                    <td className="px-4 py-4"><span className={`rounded-full px-3 py-1.5 text-xs font-bold ${statusClass(item.status)}`}>● {tradeStatusLabel[item.status] || item.status}</span></td>
                    <td className="px-4 py-4">{position.quantity?.toLocaleString?.() || "0"} 股<div className="mt-0.5 text-xs text-[#52616b]">可卖: {position.available_quantity?.toLocaleString?.() || "0"} 股</div></td>
                    <td className="px-4 py-4">{money(position.market_price)}<div className="mt-0.5 text-xs text-[#52616b]">成本: {money(position.average_cost)}</div></td>
                    <td className={`px-4 py-4 font-bold ${Number(position.unrealized_pnl) > 0 ? "text-[#b52b5d]" : Number(position.unrealized_pnl) < 0 ? "text-[#176342]" : "text-[#52616b]"}`}>{money(position.unrealized_pnl)}<div className="mt-0.5 text-xs font-normal">{position.unrealized_pnl_pct == null ? "—" : `${(position.unrealized_pnl_pct * 100).toFixed(2)}%`}</div></td>
                    <td className="px-4 py-4 text-[#145c39]">{money(position.current_capital_risk)}<div className="mt-0.5 text-xs">{position.current_capital_risk == null ? "未形成持仓" : "安全垫已锁"}</div></td>
                    <td className="px-4 py-4">{money(position.current_giveback_risk)}</td>
                    <td className="px-4 py-4"><button onClick={() => onOpen(item.id)} className="rounded-md bg-[#fce2e7] px-2 py-1 text-xs font-bold text-[#8f2243]">{latest ? actionLabel[latest.action_type] || latest.action_type : "—"}</button></td>
                  </tr>
                  {isExpanded && <tr key={`${item.id}-details`} className="border-b border-[#eee9df] bg-[#fdfcf9]"><td colSpan={11} className="px-14 py-4"><section className="rounded-xl border border-[#e9e4d9] bg-white p-4"><h2 className="mb-3 font-serif text-lg">执行动作明细 <span className="text-sm text-[#52616b]">(TradePlan → ExecutionPlan → Order → Fill)</span></h2><div className="space-y-2">{(item.plans || []).map((plan: any) => <div key={plan.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md bg-[#f5f4ef] px-3 py-2 text-xs"><span className={`rounded px-2 py-1 font-bold text-white ${["REDUCE", "CLOSE"].includes(plan.action_type) ? "bg-[#b52b5d]" : "bg-[#397252]"}`}>{actionLabel[plan.action_type] || plan.action_type}</span><span>{plan.created_at ? new Date(plan.created_at).toLocaleString("zh-CN") : "时间未记录"}</span><span>计划 {plan.calculation_snapshot_json?.planned_qty ?? "—"} 股</span><b>{plan.execution_plans?.length ? `已有 ${plan.execution_plans.length} 个执行计划` : "尚未创建执行计划"}</b></div>)}{!(item.plans || []).length && <p className="text-sm text-[#52616b]">暂无动作记录</p>}</div></section></td></tr>}
                </Fragment>;
              })}</tbody>
            </table>
          </div>
          {!loading && rows.length === 0 && <div className="px-5 py-16 text-center text-sm text-[#52616b]">没有符合条件的交易。</div>}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#eee9df] bg-[#faf9f5] px-5 py-3 text-sm"><span>系统总括汇总 · 共 {rows.length} 笔交易</span><span>当前活动持仓总额：<b>{rows.reduce((sum, item) => sum + Number(item.position?.market_value || 0), 0).toLocaleString("zh-CN", { style: "currency", currency: "CNY" })}</b></span><span>正在承担本金计划风险：<b>{rows.reduce((sum, item) => sum + Number(item.position?.current_capital_risk || 0), 0).toLocaleString("zh-CN", { style: "currency", currency: "CNY" })}</b></span></div>
        </section>
      </div>
    </div>
  );
}
