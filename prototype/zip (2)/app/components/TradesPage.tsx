"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, ChevronRight, Plus, RefreshCw, SlidersHorizontal } from "lucide-react";
import { ActionPlanDialog, TradeDetailDialog } from "./TradePlansPage";
import KLineModal from "./KLineModal";
import TradeLifecycleTable from "./TradeLifecycleTable";

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;

async function request(path: string, accountId?: number) {
  if (!API_BASE) throw new Error("NEXT_PUBLIC_MARKET_REVIEW_API_URL 未配置");
  const scopedPath = accountId === undefined ? path : `${path}${path.includes("?") ? "&" : "?"}account_id=${encodeURIComponent(String(accountId))}`;
  const response = await fetch(`${API_BASE}${scopedPath}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

const tradeStatus: Record<string, string> = {
  PLANNED: "计划中", ACTIVE: "进行中", CLOSING: "清仓中", CLOSED: "已结束", CANCELLED: "已取消",
};
const tradeType: Record<string, string> = {
  TREND: "趋势交易", REBOUND: "反弹 / 波段", FIXED_TARGET: "固定目标", CUSTOM: "自定义",
};
const actionType: Record<string, string> = { OPEN: "建仓", ADD: "加仓", REDUCE: "减仓", CLOSE: "清仓" };

function money(value: unknown) {
  return typeof value === "number" ? `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}` : "—";
}
function percent(value: unknown) {
  return typeof value === "number" ? `${(value * 100).toFixed(2)}%` : "—";
}
function status(value: string) {
  return tradeStatus[value] || value;
}

export default function TradesPage({ onCreate, accountId, initialTradeId, onInitialTradeIdConsumed }: { onCreate: () => void; accountId?: number; initialTradeId?: number | null; onInitialTradeIdConsumed?: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [selected, setSelected] = useState<any>(null);
  const [action, setAction] = useState<any>(null);
  const [positionState, setPositionState] = useState<any>(null);
  const [riskHistory, setRiskHistory] = useState<any[]>([]);
  const [exitRules, setExitRules] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [typeFilter, setTypeFilter] = useState("ALL");

  async function load() {
    setLoading(true); setError(null);
    try { const [result, overview] = await Promise.all([request("/api/trades", accountId), request("/api/trading/overview", accountId)]); const positions = new Map((overview.positions || []).map((position: any) => [position.symbol, position])); setItems((result.items || []).map((item: any) => ({ ...item, position: positions.get(item.symbol) || null }))); }
    catch (e) { setError(e instanceof Error ? e.message : "交易读取失败"); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, [accountId]);
  useEffect(() => {
    if (!initialTradeId) return;
    void openTrade(initialTradeId);
    onInitialTradeIdConsumed?.();
  }, [initialTradeId]);

  async function openTrade(tradeId: number) {
    setError(null);
    try {
      const [trade, position, history, rules] = await Promise.all([
        request(`/api/trades/${tradeId}`, accountId),
        request(`/api/trades/${tradeId}/position-state`, accountId),
        request(`/api/trades/${tradeId}/risk-reference-history`, accountId),
        request(`/api/trades/${tradeId}/exit-rules`, accountId),
      ]);
      setSelected(trade.item);
      setPositionState(position.item);
      setRiskHistory(history.items || []);
      setExitRules(rules.items || []);
    } catch (e) { setError(e instanceof Error ? e.message : "交易详情读取失败"); }
  }

  if (selected) {
    const plans = selected.plans || [];
    const legs = selected.legs || [];
    const tradeMarkers = plans.map((plan: any) => ({ date: plan.created_at || selected.created_at, price: Number(plan.input_json?.reference_entry_price || 0), label: `${actionType[plan.action_type] || "动作"} #${plan.sequence_no}`, color: plan.action_type === "CLOSE" ? "#ae2012" : plan.action_type === "REDUCE" ? "#a64b00" : "#0f5238" })).filter((item: any) => item.price > 0);
    return (
      <div className="min-h-[calc(100vh-64px)] bg-[#f8f9fa] px-5 py-5 text-[#191c1d] xl:px-6">
        <div className="mx-auto max-w-[1600px] space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><button onClick={() => setSelected(null)} className="mb-2 inline-flex items-center gap-1 text-sm font-bold text-[#0f5238]"><ArrowLeft className="h-4 w-4" />返回交易</button><h1 className="text-2xl font-bold">{selected.symbol} {selected.symbol_name}</h1><p className="mt-1 text-sm text-[#52616b]">{tradeType[selected.trade_type] || "自定义"} · <span className="font-bold">{status(selected.status)}</span>{selected.playbook_id ? ` · Playbook ${selected.playbook_id}` : ""}</p></div>
            <div className="flex gap-2">{selected.status === "ACTIVE" && <><button onClick={() => setAction({ tradeId: selected.id, symbol: selected.symbol, securityName: selected.symbol_name, type: "ADD" })} className="rounded-md bg-[#0f5238] px-3 py-2 text-sm font-bold text-white">加仓</button><button onClick={() => setAction({ tradeId: selected.id, symbol: selected.symbol, securityName: selected.symbol_name, type: "REDUCE" })} className="rounded-md border border-[#0f5238] px-3 py-2 text-sm font-bold text-[#0f5238]">减仓</button><button onClick={() => setAction({ tradeId: selected.id, symbol: selected.symbol, securityName: selected.symbol_name, type: "CLOSE" })} className="rounded-md bg-[#ae2012] px-3 py-2 text-sm font-bold text-white">清仓</button><button onClick={() => setAction({ risk: true })} className="inline-flex items-center gap-1 rounded-md border border-[#bfc9c1] px-3 py-2 text-sm font-bold text-[#404943]"><SlidersHorizontal className="h-4 w-4" />调整风险</button></>}</div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{[["当前状态", status(selected.status)], ["交易类型", tradeType[selected.trade_type] || "自定义"], ["动作数量", `${plans.length} 项`], ["TradeLeg", `${legs.length} 个`], ["风险预算", money(selected.trade_risk_budget_amount)]].map(([label, value]) => <div key={label} className="rounded-xl border border-[#dee2e6] bg-white p-4"><p className="text-xs text-[#52616b]">{label}</p><p className="mt-1 font-mono text-base font-bold">{value}</p></div>)}</div>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.7fr)]">
            <section className="rounded-xl bg-white p-4 shadow-[0_2px_7px_rgba(25,28,29,0.06)] xl:col-span-2"><div className="mb-3 flex items-center justify-between"><div><h2 className="text-lg font-bold">价格与交易标记</h2><p className="mt-1 text-xs text-[#52616b]">展示建仓、加仓、减仓、清仓对应的计划价格。</p></div><div className="flex flex-wrap gap-1.5 text-xs">{tradeMarkers.map((marker: any) => <span key={marker.label} className="rounded-full px-2 py-1 text-white" style={{ backgroundColor: marker.color }}>{marker.label}</span>)}</div></div><div className="h-[460px] overflow-hidden rounded-lg"><KLineModal embedded isOpen assetCode={selected.symbol} assetName={selected.symbol_name || selected.symbol} onClose={() => undefined} showAiPoolButton={false} showWatchlistButton={false} showNavigation={false} showAssetInfo={false} tradeMarkers={tradeMarkers} /></div></section>
            <section className="rounded-xl bg-white p-5 shadow-[0_2px_7px_rgba(25,28,29,0.06)]"><h2 className="mb-4 text-lg font-bold">交易时间线</h2><div className="space-y-3 border-l-2 border-[#bfc9c1] pl-4">{plans.map((plan: any) => <div key={plan.id} className="rounded-lg border border-[#dee2e6] p-3"><div className="flex justify-between gap-2"><b>{actionType[plan.action_type] || plan.action_type} #{plan.sequence_no}</b><span className="text-xs text-[#52616b]">{plan.status}</span></div><p className="mt-1 text-sm text-[#52616b]">计划数量：{plan.calculation_snapshot_json?.planned_qty ?? "—"} 股 · {plan.reason_text || "未填写理由"}</p><button onClick={() => setAction({ detail: true, tradeId: selected.id })} className="mt-2 inline-flex items-center gap-1 text-xs font-bold text-[#0f5238]">查看动作详情<ChevronRight className="h-3 w-3" /></button></div>)}</div></section>
            <div className="space-y-4"><section className="rounded-xl bg-white p-5 shadow-[0_2px_7px_rgba(25,28,29,0.06)]"><h2 className="mb-3 text-lg font-bold">持仓与风险</h2><div className="grid grid-cols-2 gap-2"><div className="rounded-lg bg-[#f3f4f5] p-3"><span className="text-xs text-[#52616b]">当前持仓</span><b className="mt-1 block">{positionState?.position_qty ?? "—"} 股</b></div><div className="rounded-lg bg-[#f3f4f5] p-3"><span className="text-xs text-[#52616b]">可卖数量</span><b className="mt-1 block">{positionState?.available_qty ?? "—"} 股</b></div><div className="rounded-lg bg-[#f3f4f5] p-3"><span className="text-xs text-[#52616b]">平均成本 / 现价</span><b className="mt-1 block">{money(positionState?.avg_cost)} / {money(positionState?.market_price)}</b></div><div className="rounded-lg bg-[#f3f4f5] p-3"><span className="text-xs text-[#52616b]">风险参考</span><b className="mt-1 block">{money(positionState?.position_risk_reference_price)}</b></div><div className="rounded-lg bg-[#fff8ed] p-3"><span className="text-xs text-[#52616b]">本金计划风险</span><b className="mt-1 block">{money(positionState?.current_capital_risk)}</b></div><div className="rounded-lg bg-[#fff8ed] p-3"><span className="text-xs text-[#52616b]">利润回吐风险</span><b className="mt-1 block">{money(positionState?.current_giveback_risk)}</b></div></div></section><section className="rounded-xl bg-white p-5 shadow-[0_2px_7px_rgba(25,28,29,0.06)]"><h2 className="mb-3 text-lg font-bold">TradeLeg</h2>{legs.length ? legs.map((leg: any) => <div key={leg.id} className="flex justify-between border-b border-[#edf0f2] py-2 text-sm"><span>{leg.leg_type || `Leg #${leg.sequence_no}`}</span><b>{leg.remaining_qty ?? "—"} 股 · 风险参考 {money(leg.current_risk_reference_price)}</b></div>) : <p className="text-sm text-[#52616b]">暂无已形成的 TradeLeg</p>}</section><section className="rounded-xl bg-white p-5 shadow-[0_2px_7px_rgba(25,28,29,0.06)]"><h2 className="mb-3 text-lg font-bold">风险参考历史</h2>{riskHistory.length ? riskHistory.map((item) => <div key={item.id} className="flex justify-between border-b border-[#edf0f2] py-2 text-xs"><span>{money(item.old_price)} → {money(item.new_price)}</span><span className="text-[#52616b]">{item.reason}</span></div>) : <p className="text-sm text-[#52616b]">暂无调整记录</p>}</section><section className="rounded-xl bg-white p-5 shadow-[0_2px_7px_rgba(25,28,29,0.06)]"><div className="mb-3 flex items-center justify-between"><h2 className="text-lg font-bold">退出规则</h2><button onClick={() => setAction({ exitRule: true })} className="rounded-md border border-[#0f5238] px-2 py-1 text-xs font-bold text-[#0f5238]">新增规则</button></div>{exitRules.length ? exitRules.map((rule) => <div key={rule.id} className="flex justify-between border-b border-[#edf0f2] py-2 text-sm"><span>{rule.trigger_type} → {rule.action_type}</span><span className={rule.enabled ? "text-[#2d6a4f]" : "text-[#52616b]"}>{rule.enabled ? "启用" : "停用"}</span></div>) : <p className="text-sm text-[#52616b]">暂无退出规则</p>}</section></div>
          </div>
          {action?.detail && <TradeDetailDialog accountId={accountId} tradeId={selected.id} onClose={() => setAction(null)} onError={setError} />}
          {action?.type && <ActionPlanDialog accountId={accountId} fullPage action={action} onClose={() => setAction(null)} onSaved={async () => { setAction(null); await load(); await openTrade(selected.id); }} onError={setError} />}
          {action?.risk && <RiskReferenceDialog accountId={accountId} tradeId={selected.id} legs={legs} current={positionState?.position_risk_reference_price} onClose={() => setAction(null)} onSaved={async () => { setAction(null); await openTrade(selected.id); }} onError={setError} />}
          {action?.exitRule && <ExitRuleDialog accountId={accountId} tradeId={selected.id} onClose={() => setAction(null)} onSaved={async () => { setAction(null); await openTrade(selected.id); }} onError={setError} />}
          {error && <div className="fixed bottom-5 right-5 rounded-lg border border-[#ffdad6] bg-[#fff8f7] px-4 py-3 text-sm text-[#93000a]">{error}</div>}
        </div>
      </div>
    );
  }

  const filteredItems = items.filter((item) => {
    const matchesQuery = !query.trim() || `${item.symbol} ${item.symbol_name}`.toLowerCase().includes(query.trim().toLowerCase());
    return matchesQuery && (statusFilter === "ALL" || item.status === statusFilter) && (typeFilter === "ALL" || item.trade_type === typeFilter);
  });
  return <TradeLifecycleTable items={items} loading={loading} query={query} setQuery={setQuery} statusFilter={statusFilter} setStatusFilter={setStatusFilter} typeFilter={typeFilter} setTypeFilter={setTypeFilter} onRefresh={() => void load()} onCreate={onCreate} onOpen={(tradeId: number) => void openTrade(tradeId)} />;
  return <div className="min-h-[calc(100vh-64px)] bg-[#f8f9fa] px-5 py-5 text-[#191c1d] xl:px-6"><div className="mx-auto max-w-[1600px]"><div className="mb-5 flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-2xl font-bold">交易</h1><p className="mt-1 text-sm text-[#52616b]">管理从建仓到清仓的完整交易生命周期</p></div><div className="flex gap-2"><button onClick={() => void load()} className="rounded-md border border-[#bfc9c1] bg-white p-2" title="刷新交易"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /></button><button onClick={onCreate} className="inline-flex items-center gap-1.5 rounded-md bg-[#0f5238] px-3 py-2 text-sm font-bold text-white"><Plus className="h-4 w-4" />创建新交易</button></div></div>{error && <div className="mb-3 rounded-lg border border-[#ffdad6] bg-[#fff8f7] px-4 py-3 text-sm text-[#93000a]">{error}</div>}<div className="mb-4 grid gap-2 rounded-xl border border-[#dee2e6] bg-white p-3 sm:grid-cols-[minmax(0,1fr)_180px_180px]"><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索股票代码或名称" className="input" /><select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="input"><option value="ALL">全部状态</option><option value="PLANNED">计划中</option><option value="ACTIVE">进行中</option><option value="CLOSING">清仓中</option><option value="CLOSED">已结束</option><option value="CANCELLED">已取消</option></select><select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="input"><option value="ALL">全部类型</option><option value="TREND">趋势交易</option><option value="REBOUND">反弹 / 波段</option><option value="FIXED_TARGET">固定目标</option><option value="CUSTOM">自定义</option></select></div><section className="overflow-hidden rounded-xl bg-white shadow-[0_2px_7px_rgba(25,28,29,0.06)]"><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="border-b border-[#dee2e6] bg-[#f3f4f5] text-xs text-[#52616b]"><tr>{["股票", "类型", "状态", "当前持仓", "最近动作", "创建时间", "操作"].map((label) => <th key={label} className="px-4 py-3">{label}</th>)}</tr></thead><tbody>{filteredItems.map((item) => { const latest = item.plans?.[item.plans.length - 1]; return <tr key={item.id} className="border-b border-[#edf0f2] hover:bg-[#f8fbf9]"><td className="px-4 py-3"><b>{item.symbol}</b><span className="ml-2 text-[#52616b]">{item.symbol_name}</span></td><td className="px-4 py-3">{tradeType[item.trade_type] || "自定义"}</td><td className="px-4 py-3"><span className="rounded-full bg-[#edf0f2] px-2 py-1 text-xs font-bold">{status(item.status)}</span></td><td className="px-4 py-3">—</td><td className="px-4 py-3">{latest ? `${actionType[latest.action_type] || latest.action_type} #${latest.sequence_no}` : "—"}</td><td className="px-4 py-3 text-[#52616b]">{item.created_at ? new Date(item.created_at).toLocaleString("zh-CN") : "—"}</td><td className="px-4 py-3"><button onClick={() => void openTrade(item.id)} className="font-bold text-[#0f5238]">查看</button></td></tr>; })}</tbody></table></div>{!loading && filteredItems.length === 0 && <div className="px-5 py-16 text-center text-sm text-[#52616b]">没有符合条件的交易。</div>}</section></div></div>;
}

export function RiskReferenceDialog({ tradeId, legs, current, initialReason, accountId, onClose, onSaved, onError }: { tradeId: number; legs: any[]; current?: number; initialReason?: string; accountId?: number; onClose: () => void; onSaved: () => Promise<void>; onError: (message: string) => void }) {
  const [target, setTarget] = useState("TRADE");
  const [price, setPrice] = useState(current == null ? "" : String(current));
  const [reason, setReason] = useState(initialReason || "");
  const [busy, setBusy] = useState(false);
  async function save() {
    if (accountId === undefined) { onError("未选择交易账号，无法调整风险参考"); return; }
    setBusy(true);
    try { const legId = target === "TRADE" ? undefined : Number(target); await requestPost(`/api/trades/${tradeId}/risk-reference`, { new_price: Number(price), reason, leg_id: legId }, accountId); await onSaved(); }
    catch (e) { onError(e instanceof Error ? e.message : "风险参考调整失败"); }
    finally { setBusy(false); }
  }
  return <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/30 p-4"><div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl"><div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-bold">调整风险参考</h2><button onClick={onClose} className="text-xl text-[#52616b]">×</button></div><label className="mb-3 block text-sm font-bold">调整对象<select value={target} onChange={(e) => setTarget(e.target.value)} className="input mt-1"><option value="TRADE">整个 Trade</option>{legs.map((leg) => <option key={leg.id} value={leg.id}>{leg.leg_type || "TradeLeg"} #{leg.sequence_no}</option>)}</select></label><label className="mb-3 block text-sm font-bold">新风险参考价<input value={price} onChange={(e) => setPrice(e.target.value)} type="number" min="0.01" step="0.01" className="input mt-1" /></label><label className="block text-sm font-bold">调整理由<textarea value={reason} onChange={(e) => setReason(e.target.value)} className="input mt-1 min-h-20" placeholder="说明本次调整依据" /></label><div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-md border border-[#bfc9c1] px-3 py-2 text-sm font-bold">取消</button><button onClick={() => void save()} disabled={busy || !price || !reason.trim()} className="rounded-md bg-[#0f5238] px-3 py-2 text-sm font-bold text-white disabled:opacity-50">保存调整</button></div></div></div>;
}

export function ExitRuleDialog({ tradeId, accountId, rule, onClose, onSaved, onError }: { tradeId: number; accountId?: number; rule?: any; onClose: () => void; onSaved: () => Promise<void>; onError: (message: string) => void }) {
  const [triggerType, setTriggerType] = useState(rule?.trigger_type || "PRICE_BELOW");
  const [actionType, setActionType] = useState(rule?.action_type || "ALERT_ONLY");
  const [price, setPrice] = useState(rule?.trigger_config_json?.price == null ? "" : String(rule.trigger_config_json.price));
  const [notes, setNotes] = useState(rule?.notes || "");
  const [busy, setBusy] = useState(false);
  const needsPrice = triggerType === "PRICE_BELOW" || triggerType === "PRICE_ABOVE";
  async function save() {
    if (accountId === undefined) { onError("未选择交易账号，无法保存退出规则"); return; }
    if (needsPrice && (!price || Number(price) <= 0)) {
      onError("价格触发规则必须填写大于 0 的触发价格");
      return;
    }
    setBusy(true);
    try { await requestPost(rule ? `/api/trades/${tradeId}/exit-rules/${rule.id}` : `/api/trades/${tradeId}/exit-rules`, { rule_type: "EXIT", trigger_type: triggerType, trigger_config_json: price ? { price: Number(price) } : {}, action_type: actionType, action_config_json: {}, execution_behavior: "REQUIRE_CONFIRMATION", notes, enabled: rule?.enabled ?? true }, accountId, rule ? "PATCH" : "POST"); await onSaved(); }
    catch (e) { onError(e instanceof Error ? e.message : "退出规则保存失败"); }
    finally { setBusy(false); }
  }
  return <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/30 p-4"><div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl"><div className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-bold">{rule ? "编辑退出规则" : "新增退出规则"}</h2><p className="mt-1 text-xs text-[#52616b]">规则触发后仍需人工确认，不会直接发送委托。</p></div><button onClick={onClose} className="text-xl text-[#52616b]">×</button></div><div className="grid gap-3"><label className="text-sm font-bold">触发类型<select value={triggerType} onChange={(e) => setTriggerType(e.target.value)} className="input mt-1"><option value="PRICE_BELOW">价格跌破</option><option value="PRICE_ABOVE">价格突破</option><option value="R_MULTIPLE">达到 R 倍数</option><option value="DATE_TIME">指定日期时间</option><option value="HOLDING_DAYS">持有天数</option><option value="MANUAL_CONFIRMATION">人工确认</option></select></label><label className="text-sm font-bold">触发价格{needsPrice && <span className="ml-1 text-[#b5284d]">*</span>}<input value={price} onChange={(e) => setPrice(e.target.value)} type="number" min="0.01" step="0.01" className="input mt-1" placeholder={needsPrice ? "请输入触发价格" : "非价格规则可留空"} /></label><label className="text-sm font-bold">触发后的动作<select value={actionType} onChange={(e) => setActionType(e.target.value)} className="input mt-1"><option value="ALERT_ONLY">仅提醒</option><option value="REDUCE_FIXED_QTY">创建减仓建议</option><option value="CLOSE_ALL">创建清仓建议</option><option value="UPDATE_RISK_REFERENCE">调整风险参考</option></select></label><label className="text-sm font-bold">说明<textarea value={notes} onChange={(e) => setNotes(e.target.value)} className="input mt-1 min-h-20" placeholder="说明规则依据" /></label></div><div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-md border border-[#bfc9c1] px-3 py-2 text-sm font-bold">取消</button><button onClick={() => void save()} disabled={busy || (needsPrice && (!price || Number(price) <= 0))} className="rounded-md bg-[#0f5238] px-3 py-2 text-sm font-bold text-white disabled:opacity-50">{rule ? "保存修改" : "保存规则"}</button></div></div></div>;
}

async function requestPost(path: string, body: unknown, accountId?: number, method = "POST") {
  if (!API_BASE) throw new Error("NEXT_PUBLIC_MARKET_REVIEW_API_URL 未配置");
  const scopedPath = accountId === undefined ? path : `${path}${path.includes("?") ? "&" : "?"}account_id=${encodeURIComponent(String(accountId))}`;
  const response = await fetch(`${API_BASE}${scopedPath}`, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}
