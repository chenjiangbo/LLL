"use client";

import { useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;
const legLabels: Record<string, string> = { OPEN: "建仓", ADD: "加仓", REDUCE: "减仓", CLOSE: "清仓" };

async function requestPost(path: string, body: unknown, accountId: number, method = "POST") {
  if (!API_BASE) throw new Error("交易服务配置不可用，请联系管理员");
  const response = await fetch(`${API_BASE}${path}?account_id=${encodeURIComponent(String(accountId))}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : typeof detail?.message === "string" ? detail.message : `交易请求未完成（HTTP ${response.status}）`);
  }
  return response.json();
}

export function RiskReferenceDialog({ tradeId, legs, current, initialReason, initialTarget, accountId, onClose, onSaved, onError }: { tradeId: number; legs: any[]; current?: number; initialReason?: string; initialTarget?: string; accountId: number; onClose: () => void; onSaved: () => Promise<void>; onError: (message: string) => void }) {
  const [target, setTarget] = useState(initialTarget || "TRADE");
  const [price, setPrice] = useState(current == null ? "" : String(current));
  const [reason, setReason] = useState(initialReason || "");
  const [busy, setBusy] = useState(false);
  async function save() {
    const newPrice = Number(price);
    if (!Number.isFinite(newPrice) || newPrice <= 0) { onError("请输入大于 0 的风险参考价"); return; }
    if (target !== "TRADE" && !legs.some((leg) => String(leg.id) === target)) { onError("当前交易腿不存在，请刷新后重试"); return; }
    setBusy(true);
    try { await requestPost(`/api/trades/${tradeId}/risk-reference`, { new_price: newPrice, reason, leg_id: target === "TRADE" ? undefined : Number(target) }, accountId); await onSaved(); }
    catch (error) { onError(error instanceof Error ? error.message : "风险参考调整失败"); }
    finally { setBusy(false); }
  }
  return <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/30 p-4"><div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl"><div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-bold">调整风险参考</h2><button onClick={onClose} className="text-xl text-[#52616b]">×</button></div><label className="mb-3 block text-sm font-bold">调整对象<select value={target} onChange={(event) => setTarget(event.target.value)} className="input mt-1"><option value="TRADE">整个 Trade</option>{legs.map((leg) => <option key={leg.id} value={leg.id}>{legLabels[leg.leg_type] || "分腿"} #{leg.sequence_no}</option>)}</select></label><label className="mb-3 block text-sm font-bold">新风险参考价<input value={price} onChange={(event) => setPrice(event.target.value)} type="number" min="0.01" step="0.01" className="input mt-1" /></label><label className="block text-sm font-bold">调整理由<textarea value={reason} onChange={(event) => setReason(event.target.value)} className="input mt-1 min-h-20" placeholder="说明本次调整依据" /></label><div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-md border border-[#bfc9c1] px-3 py-2 text-sm font-bold">取消</button><button onClick={() => void save()} disabled={busy || !price || !reason.trim()} className="rounded-md bg-[#0f5238] px-3 py-2 text-sm font-bold text-white disabled:opacity-50">保存调整</button></div></div></div>;
}

export function ExitRuleDialog({ tradeId, accountId, rule, onClose, onSaved, onError }: { tradeId: number; accountId: number; rule?: any; onClose: () => void; onSaved: () => Promise<void>; onError: (message: string) => void }) {
  const [triggerType, setTriggerType] = useState(rule?.trigger_type || "PRICE_BELOW");
  const [actionType, setActionType] = useState(rule?.action_type || "ALERT_ONLY");
  const [price, setPrice] = useState(rule?.trigger_config_json?.price == null ? "" : String(rule.trigger_config_json.price));
  const [notes, setNotes] = useState(rule?.notes || "");
  const [busy, setBusy] = useState(false);
  const needsPrice = triggerType === "PRICE_BELOW" || triggerType === "PRICE_ABOVE";
  async function save() {
    if (needsPrice && (!Number.isFinite(Number(price)) || Number(price) <= 0)) { onError("价格触发规则必须填写大于 0 的触发价格"); return; }
    setBusy(true);
    try { await requestPost(rule ? `/api/trades/${tradeId}/exit-rules/${rule.id}` : `/api/trades/${tradeId}/exit-rules`, { rule_type: "EXIT", trigger_type: triggerType, trigger_config_json: price ? { price: Number(price) } : {}, action_type: actionType, action_config_json: {}, execution_behavior: "REQUIRE_CONFIRMATION", notes, enabled: rule?.enabled ?? true }, accountId, rule ? "PATCH" : "POST"); await onSaved(); }
    catch (error) { onError(error instanceof Error ? error.message : "退出规则保存失败"); }
    finally { setBusy(false); }
  }
  return <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/30 p-4"><div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl"><div className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-bold">{rule ? "编辑退出规则" : "新增退出规则"}</h2><p className="mt-1 text-xs text-[#52616b]">规则触发后仍需人工确认，不会直接发送委托。</p></div><button onClick={onClose} className="text-xl text-[#52616b]">×</button></div><div className="grid gap-3"><label className="text-sm font-bold">触发类型<select value={triggerType} onChange={(event) => setTriggerType(event.target.value)} className="input mt-1"><option value="PRICE_BELOW">价格跌破</option><option value="PRICE_ABOVE">价格突破</option><option value="R_MULTIPLE">达到 R 倍数</option><option value="DATE_TIME">指定日期时间</option><option value="HOLDING_DAYS">持有天数</option><option value="MANUAL_CONFIRMATION">人工确认</option></select></label><label className="text-sm font-bold">触发价格{needsPrice && <span className="ml-1 text-[#b5284d]">*</span>}<input value={price} onChange={(event) => setPrice(event.target.value)} type="number" min="0.01" step="0.01" className="input mt-1" placeholder={needsPrice ? "请输入触发价格" : "非价格规则可留空"} /></label><label className="text-sm font-bold">触发后的动作<select value={actionType} onChange={(event) => setActionType(event.target.value)} className="input mt-1"><option value="ALERT_ONLY">仅提醒</option><option value="REDUCE_FIXED_QTY">创建减仓建议</option><option value="CLOSE_ALL">创建清仓建议</option><option value="UPDATE_RISK_REFERENCE">调整风险参考</option></select></label><label className="text-sm font-bold">说明<textarea value={notes} onChange={(event) => setNotes(event.target.value)} className="input mt-1 min-h-20" placeholder="说明规则依据" /></label></div><div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-md border border-[#bfc9c1] px-3 py-2 text-sm font-bold">取消</button><button onClick={() => void save()} disabled={busy || (needsPrice && (!price || Number(price) <= 0))} className="rounded-md bg-[#0f5238] px-3 py-2 text-sm font-bold text-white disabled:opacity-50">{rule ? "保存修改" : "保存规则"}</button></div></div></div>;
}
