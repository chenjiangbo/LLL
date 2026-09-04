'use client';

import { useEffect, useState } from 'react';
import { Plus, RefreshCw, Save, Trash2 } from 'lucide-react';
import type { ReactNode } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;

type Overview = {
  account: Record<string, any>;
  risk_profile: Record<string, any>;
  positions: Array<Record<string, any>>;
};

async function request(path: string, options?: RequestInit) {
  if (!API_BASE) throw new Error('NEXT_PUBLIC_MARKET_REVIEW_API_URL 未配置');
  const response = await fetch(`${API_BASE}${path}`, { cache: 'no-store', ...options, headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) } });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function money(value: any) { return typeof value === 'number' ? `¥${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}` : '—'; }
function pct(value: any) { return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '—'; }

export default function TradingOverviewPage({ accountId }: { accountId: number }) {
  const [data, setData] = useState<Overview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accountForm, setAccountForm] = useState<Record<string, any>>({});
  const [riskForm, setRiskForm] = useState<Record<string, any>>({});
  const [position, setPosition] = useState<Record<string, any>>({ symbol: '', security_name: '', quantity: 0, available_quantity: 0, average_cost: '', market_price: '' });

  async function load() {
    setBusy(true); setError(null);
    try {
      const result = await request(`/api/trading/overview?account_id=${encodeURIComponent(String(accountId))}`);
      setData(result); setAccountForm(result.account); setRiskForm(result.risk_profile);
    } catch (e) { setError(e instanceof Error ? e.message : '交易账户读取失败'); }
    finally { setBusy(false); }
  }
  useEffect(() => { load(); }, [accountId]);

  async function saveSettings() {
    setBusy(true); setError(null);
    try {
      await request(`/api/trading/account?account_id=${encodeURIComponent(String(accountId))}`, { method: 'PATCH', body: JSON.stringify(accountForm) });
      await request(`/api/trading/risk-profile?account_id=${encodeURIComponent(String(accountId))}`, { method: 'PATCH', body: JSON.stringify(riskForm) });
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : '交易设置保存失败'); }
    finally { setBusy(false); }
  }

  async function savePosition() {
    setBusy(true); setError(null);
    try {
      await request(`/api/trading/positions/${encodeURIComponent(position.symbol)}?account_id=${encodeURIComponent(String(accountId))}`, { method: 'PUT', body: JSON.stringify({ ...position, quantity: Number(position.quantity), available_quantity: Number(position.available_quantity), average_cost: Number(position.average_cost), market_price: Number(position.market_price), current_risk_reference_price: position.current_risk_reference_price ? Number(position.current_risk_reference_price) : null }) });
      setPosition({ symbol: '', security_name: '', quantity: 0, available_quantity: 0, average_cost: '', market_price: '' });
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : '持仓保存失败'); }
    finally { setBusy(false); }
  }

  async function removePosition(symbol: string) {
    if (!window.confirm(`确认移除 ${symbol} 的规划持仓？`)) return;
    setBusy(true); setError(null);
    try { await request(`/api/trading/positions/${encodeURIComponent(symbol)}?account_id=${encodeURIComponent(String(accountId))}`, { method: 'DELETE' }); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : '持仓移除失败'); }
    finally { setBusy(false); }
  }

  const account = data?.account;
  return <div className="min-h-[calc(100vh-56px)] bg-[#faf6f0] px-4 py-5 text-[#2e3230] sm:px-6 lg:px-8">
    <div className="mx-auto max-w-[1600px]">
      <div className="mb-5 flex justify-end"><button onClick={load} title="刷新" className="rounded-lg border border-[#cfc4b3] p-2"><RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} /></button></div>
      {error && <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}
      {!data ? <div className="rounded-2xl bg-white p-10 text-center text-sm text-[#686d68]">正在读取账户数据…</div> : <>
        <div className="mb-5 flex items-center gap-3"><div><p className="text-xs font-bold text-[#8a7252]">{account?.account_type === 'PLANNING' ? '规划账户' : account?.account_type}</p><h1 className="mt-1 text-2xl font-bold">{account?.name}</h1></div><span className="rounded-full bg-[#e7f0e6] px-3 py-1 text-xs font-bold text-[#356044]">{account?.status === 'ACTIVE' ? '可用' : account?.status}</span></div>
        <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{[['总资产', money(account?.equity)], ['可用现金', money(account?.available_cash)], ['持仓市值', money(account?.market_value)], ['总仓位', pct(account?.total_exposure_pct)], ['持仓数量', `${data.positions.length} 只`]].map(([label, value]) => <div key={label} className="rounded-2xl border border-[#e4e0d8] bg-white p-4 shadow-sm"><div className="text-xs text-[#686d68]">{label}</div><div className="mt-2 text-xl font-bold">{value}</div></div>)}</div>
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.65fr)]">
          <section className="rounded-2xl border border-[#e4e0d8] bg-white shadow-sm"><div className="flex items-center justify-between border-b border-[#e4e0d8] px-5 py-4"><h2 className="font-bold">规划持仓</h2><span className="text-xs text-[#686d68]">用于账户仓位和风险计算</span></div>{data.positions.length === 0 ? <div className="px-5 py-12 text-center text-sm text-[#686d68]">还没有规划持仓，可在右侧添加。</div> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-[#faf8f3] text-xs text-[#686d68]"><tr><th className="px-5 py-3">证券</th><th className="px-5 py-3">数量 / 可卖</th><th className="px-5 py-3">成本 / 现价</th><th className="px-5 py-3">市值</th><th className="px-5 py-3">浮盈亏</th><th /></tr></thead><tbody>{data.positions.map((item) => <tr key={item.symbol} className="border-t border-[#eeeae2]"><td className="px-5 py-4"><b>{item.symbol}</b><span className="ml-2 text-[#686d68]">{item.security_name}</span></td><td className="px-5 py-4">{item.quantity} / {item.available_quantity}</td><td className="px-5 py-4">{item.average_cost.toFixed(2)} / {item.market_price.toFixed(2)}</td><td className="px-5 py-4">{money(item.market_value)}</td><td className={item.unrealized_pnl >= 0 ? 'px-5 py-4 text-emerald-700' : 'px-5 py-4 text-rose-700'}>{money(item.unrealized_pnl)}</td><td className="px-5 py-4 text-right"><button onClick={() => removePosition(item.symbol)} title="移除持仓" className="text-[#686d68] hover:text-rose-700"><Trash2 className="h-4 w-4" /></button></td></tr>)}</tbody></table></div>}</section>
          <aside className="space-y-5">
            <Panel title="账户设置"><div className="grid gap-3 sm:grid-cols-2"><AccountField label="账户名称" fieldKey="name" state={accountForm} setState={setAccountForm} type="text" /><AccountSelect label="账户类型" fieldKey="account_type" state={accountForm} setState={setAccountForm} options={[["PLANNING", "规划账户"], ["SIMULATION", "模拟账户"], ["LIVE", "实盘账户"]]} /><AmountInput label="总资产" fieldKey="equity" state={accountForm} setState={setAccountForm} /><AmountInput label="现金" fieldKey="cash" state={accountForm} setState={setAccountForm} /><AmountInput label="可用现金" fieldKey="available_cash" state={accountForm} setState={setAccountForm} /></div></Panel>
            <Panel title="风险规则"><div className="grid gap-3 sm:grid-cols-2">{field('默认单笔风险', 'default_trade_risk_pct', riskForm, setRiskForm)}{field('最大单笔风险', 'max_trade_risk_pct', riskForm, setRiskForm)}{field('最大单股仓位', 'max_single_position_pct', riskForm, setRiskForm)}{field('最大总仓位', 'max_total_exposure_pct', riskForm, setRiskForm)}</div></Panel>
            <Panel title="添加规划持仓"><div className="grid gap-3 sm:grid-cols-2">{field('股票代码', 'symbol', position, setPosition, 'text')}{field('股票名称', 'security_name', position, setPosition, 'text')}{field('持仓数量', 'quantity', position, setPosition)}{field('可卖数量', 'available_quantity', position, setPosition)}{field('平均成本', 'average_cost', position, setPosition)}{field('当前价格', 'market_price', position, setPosition)}</div><button disabled={busy || !position.symbol} onClick={savePosition} className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg border border-[#cfc4b3] px-4 py-2 text-sm font-bold"><Plus className="h-4 w-4" />保存持仓</button></Panel>
            <button disabled={busy} onClick={saveSettings} className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[#2e3230] px-4 py-3 text-sm font-bold text-white disabled:opacity-50"><Save className="h-4 w-4" />保存账户与风险规则</button>
          </aside>
        </div>
      </>}
    </div>
  </div>;
}

function field(label: string, key: string, state: Record<string, any>, setState: (value: Record<string, any>) => void, type = 'number') { return <label><span className="mb-1 block text-xs font-bold text-[#686d68]">{label}</span><input type={type} step={type === 'number' ? '0.0001' : undefined} value={state[key] ?? ''} onChange={(e) => setState({ ...state, [key]: type === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value })} className="input" /></label>; }
function AccountField({ label, fieldKey, state, setState, type = 'text' }: { label: string; fieldKey: string; state: Record<string, any>; setState: (value: Record<string, any>) => void; type?: string }) { return <label><span className="mb-1 block text-xs font-bold text-[#686d68]">{label}</span><input type={type} value={state[fieldKey] ?? ''} onChange={(e) => setState({ ...state, [fieldKey]: e.target.value })} className="input" /></label>; }
function AccountSelect({ label, fieldKey, state, setState, options }: { label: string; fieldKey: string; state: Record<string, any>; setState: (value: Record<string, any>) => void; options: Array<[string, string]> }) { return <label><span className="mb-1 block text-xs font-bold text-[#686d68]">{label}</span><select value={state[fieldKey] ?? ''} onChange={(e) => setState({ ...state, [fieldKey]: e.target.value })} className="input">{options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>; }
function amountText(value: unknown) {
  if (value === null || value === undefined || value === '') return '';
  const [integer, decimal] = String(value).split('.');
  return decimal === undefined ? Number(integer || '0').toLocaleString('zh-CN') : `${Number(integer || '0').toLocaleString('zh-CN')}.${decimal}`;
}
function amountChinese(value: unknown) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return '';
  const text = (number: number) => Number(number.toFixed(2)).toLocaleString('zh-CN');
  if (Math.abs(amount) >= 100_000_000) return `${text(amount / 100_000_000)} 亿元`;
  if (Math.abs(amount) >= 10_000) return `${text(amount / 10_000)} 万元`;
  return `${text(amount)} 元`;
}
function AmountInput({ label, fieldKey, state, setState }: { label: string; fieldKey: string; state: Record<string, any>; setState: (value: Record<string, any>) => void }) {
  const externalValue = state[fieldKey];
  const [draft, setDraft] = useState(() => amountText(externalValue));
  const [focused, setFocused] = useState(false);
  useEffect(() => { if (!focused) setDraft(amountText(externalValue)); }, [externalValue, focused]);
  const amount = Number(draft.replace(/,/g, ''));
  return <label><span className="mb-1 block text-xs font-bold text-[#686d68]">{label}</span><input type="text" inputMode="decimal" value={draft} onFocus={() => setFocused(true)} onChange={(e) => { const raw = e.target.value.replace(/,/g, ''); if (!/^\d*(?:\.\d{0,2})?$/.test(raw)) return; setDraft(amountText(raw)); setState({ ...state, [fieldKey]: raw === '' || raw === '.' ? null : Number(raw) }); }} onBlur={() => setFocused(false)} className="input" />{draft && Number.isFinite(amount) && <span className="mt-1 block text-xs text-[#686d68]">{amountChinese(amount)}</span>}</label>;
}
function Panel({ title, children }: { title: string; children: ReactNode }) { return <section className="rounded-2xl border border-[#e4e0d8] bg-white p-4 shadow-sm"><h2 className="mb-3 font-bold">{title}</h2>{children}</section>; }
