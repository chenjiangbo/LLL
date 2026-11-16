'use client';

import { useEffect, useMemo, useState } from 'react';
import dynamic from 'next/dynamic';
import { Activity, AlertTriangle, ArrowLeft, Brain, Filter, Layers, LineChart, Loader2, PlayCircle, Search, Sparkles, TestTube2 } from 'lucide-react';

const KLineModal = dynamic(() => import('./KLineModal'), { ssr: false });
const SecondaryStockDetailDrawer = dynamic(() => import('./SecondaryStockDetailDrawer'), { ssr: false });
const TechnicalSingleStockTestView = dynamic(() => import('./TechnicalSingleStockTestView'), { ssr: false });
const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL || 'http://127.0.0.1:18080';
const PAGE_SIZE = 200;

type Item = {
  ts_code: string; name?: string; industry?: string; weekly_stage: string; daily_subtype: string;
  setup_score: number | null; score_type?: string; is_overextended: boolean; reason_codes: string[]; ths_concepts?: string[];
  episode_json?: Record<string, unknown>; episode_fields?: Record<string, unknown>;
  financial_facts?: Record<string, any>;
};
type Payload = {
  trade_date: string; total: number; items: Item[];
  weekly_stage_counts?: Record<string, number>;
  weekly_subtype_counts?: Record<string, Array<{ name: string; count: number }>>;
  concept_counts?: Record<string, number>; hot_theme_options?: Array<{ canonical_name: string; match_count: number }>; hot_theme_issue?: string | null;
};
type RunStatus = { status: string; progress?: number; step_message?: string; error?: string };

const stages: Record<string, { title: string; short: string; tip: string; badge: string; card: string; selectionClass: string; leaf: string; Icon: typeof Activity }> = {
  W1_BASE: { title: 'W1_BASE（底部构筑）', short: '底部构筑', tip: '低位筑底，关注转强与突破信号', badge: '等待突破', card: 'bg-slate-700 border-slate-700 text-white', selectionClass: 'state-card-pre', leaf: 'border-slate-200 bg-slate-50 text-slate-700', Icon: Activity },
  W2_ADVANCE: { title: 'W2_ADVANCE（上升推进）', short: '上升推进', tip: '趋势向上，观察回踩与再加速结构', badge: '趋势进行', card: 'bg-[#4a7c59] border-[#4a7c59] text-white', selectionClass: 'state-card-window', leaf: 'border-emerald-200 bg-emerald-50 text-emerald-800', Icon: Sparkles },
  W3_TOP: { title: 'W3_TOP（高位转换）', short: '高位转换', tip: '高位分歧，重点观察转弱和修复', badge: '注意风险', card: 'bg-[#a57626] border-[#a57626] text-white', selectionClass: 'state-card-top', leaf: 'border-amber-200 bg-amber-50 text-amber-800', Icon: AlertTriangle },
  W4_DECLINE: { title: 'W4_DECLINE（回撤修复）', short: '回撤修复', tip: '下跌或修复期，等待结构重新形成', badge: '等待修复', card: 'bg-rose-800 border-rose-800 text-white', selectionClass: 'state-card-post', leaf: 'border-rose-200 bg-rose-50 text-rose-800', Icon: AlertTriangle },
};
const subtypeNames: Record<string, string> = {
  UNAVAILABLE: '历史数据不足',
  W1_BASE_RANGE: '底部箱体', W1_BASE_COMPRESSION: '底部压缩', W1_EARLY_PREP: '底部早期准备', W1_FIRST_TURN: '首次转强', W1_BREAKOUT: '底部突破', W1_BREAKOUT_PULLBACK: '突破后回踩', W1_BREAKOUT_REACCEL: '突破再启动', W1_FAILED_BREAKOUT: '突破失败',
  W2_STEADY_ADVANCE: '稳步上升', W2_ACCEL_EXTENDED: '加速乖离', W2_PULLBACK: '上升回踩', W2_PULLBACK_STABILIZING: '回踩企稳', W2_REACCEL: '趋势再加速', W2_TREND_DAMAGE: '趋势受损',
  W3_HIGH_RANGE: '高位箱体', W3_HIGH_COMPRESSION: '高位压缩', W3_HIGH_REPAIR: '高位修复', W3_HIGH_REACCEL: '高位再加速', W3_HIGH_WEAKENING: '高位走弱', W3_BREAKDOWN: '高位破位', W3_POST_BREAKDOWN_REBOUND: '破位后反弹',
  W4_DECLINE: '下跌延续', W4_ACCEL_DECLINE: '加速下跌', W4_DECLINE_DECELERATING: '下跌减速', W4_EARLY_PREP: '下跌早期准备', W4_FIRST_TURN: '首次转强', W4_FIRST_ADVANCE: '第一波推进', W4_FIRST_PULLBACK: '首次回踩', W4_SECOND_TURN: '二次转强', W4_MATURE_REBOUND: '成熟反弹',
};
const episodeNames: Record<string, string> = { NONE: '无进行中形态', TURN: '首次转强', ADVANCE: '第一波推进', PULLBACK: '回踩确认', SECOND_TURN: '二次转强', BREAKOUT: '突破确认', FAILED: '突破失败', BREAKDOWN: '破位下行', REACCEL: '趋势再加速', STABILIZING: '企稳中' };
const formatFinancialAmount = (value: unknown): string => {
  const number = Number(value);
  if (!Number.isFinite(number)) return '缺失';
  if (Math.abs(number) >= 100000000) return `${(number / 100000000).toFixed(1)}亿`;
  if (Math.abs(number) >= 10000) return `${(number / 10000).toFixed(0)}万`;
  return number.toFixed(0);
};
const forecastLabel = (value: unknown): string => {
  const text = String(value || '');
  if (!text) return '';
  if (text.includes('预增')) return '业绩预增';
  if (text.includes('预亏')) return '业绩预亏';
  if (text.includes('扭亏')) return '业绩扭亏';
  return `业绩${text}`;
};
const forecastTone = (value: unknown): string => {
  const text = String(value || '');
  return text.includes('预增') || text.includes('扭亏') ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : text.includes('预亏') || text.includes('下降') || text.includes('首亏') ? 'border-rose-200 bg-rose-50 text-rose-800' : 'border-amber-200 bg-amber-50 text-amber-900';
};
const subtypeTagStyles = [
  'border-sky-200 bg-sky-50 text-sky-800', 'border-emerald-200 bg-emerald-50 text-emerald-800', 'border-violet-200 bg-violet-50 text-violet-800',
  'border-amber-200 bg-amber-50 text-amber-800', 'border-rose-200 bg-rose-50 text-rose-800', 'border-cyan-200 bg-cyan-50 text-cyan-800',
  'border-indigo-200 bg-indigo-50 text-indigo-800', 'border-lime-200 bg-lime-50 text-lime-800', 'border-orange-200 bg-orange-50 text-orange-800',
];

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { ...init, cache: 'no-store' });
  const raw = await res.text();
  if (!res.ok) {
    try { const body = JSON.parse(raw); throw new Error(body.detail || body.message || raw); } catch (error) { if (error instanceof Error) throw error; }
    throw new Error(raw || `请求失败（HTTP ${res.status}）`);
  }
  return raw ? JSON.parse(raw) as T : {} as T;
}

export default function TechnicalClassificationPage() {
  const [tradeDate, setTradeDate] = useState('');
  const [payload, setPayload] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState('ALL');
  const [subtype, setSubtype] = useState('ALL');
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [minScore, setMinScore] = useState('');
  const [excludeSt, setExcludeSt] = useState(false);
  const [selectedConcept, setSelectedConcept] = useState('ALL');
  const [showConcepts, setShowConcepts] = useState(false);
  const [selectedHotTheme, setSelectedHotTheme] = useState('ALL');
  const [conceptShowCount, setConceptShowCount] = useState(12);
  const [selected, setSelected] = useState<Item | null>(null);
  const [drawer, setDrawer] = useState<Item | null>(null);
  const [aiMessage, setAiMessage] = useState('');
  const [showSingleTest, setShowSingleTest] = useState(false);
  const [singleInput, setSingleInput] = useState('');
  const [singleResult, setSingleResult] = useState<Item | null>(null);
  const [singleLoading, setSingleLoading] = useState(false);

  async function load(date: string, nextPage = page, nextStage = stage, nextSubtype = subtype, nextConcept = selectedConcept, nextHotTheme = selectedHotTheme, nextExcludeSt = excludeSt) {
    if (!date) return;
    setLoading(true); setError(null);
    try {
      const query = new URLSearchParams({ page: String(nextPage), page_size: String(PAGE_SIZE) });
      if (nextStage !== 'ALL') query.set('weekly_stage', nextStage);
      if (nextSubtype !== 'ALL') query.set('daily_subtype', nextSubtype);
      if (nextConcept !== 'ALL') query.set('concept', nextConcept);
      query.set('hot_theme_scope', 'RECENT_60D');
      if (nextHotTheme === 'ALL_RECENT') query.set('hot_theme_all', 'true');
      else if (nextHotTheme !== 'ALL') query.set('hot_theme', nextHotTheme);
      if (nextExcludeSt) query.set('exclude_st', 'true');
      setPayload(await requestJson<Payload>(`/api/technical-classification/${date}?${query}`));
    } catch (e) {
      setPayload(null);
      setError(e instanceof Error ? e.message : '分类结果读取失败');
    } finally { setLoading(false); }
  }

  useEffect(() => {
    requestJson<{ trade_date?: string | null }>('/api/technical-classification/latest')
      .then(async (snapshot) => {
        const date = String(snapshot.trade_date || '').replaceAll('-', '');
        if (!date) throw new Error('尚未生成技术分类快照，请先运行一次全市场分类');
        setTradeDate(date);
        await load(date, 1, 'ALL', 'ALL');
      })
      .catch((e) => { setLoading(false); setError(e instanceof Error ? e.message : '技术分类快照读取失败'); });
  }, []);

  function applyClassification(nextStage: string, nextSubtype = 'ALL') {
    setStage(nextStage); setSubtype(nextSubtype); setPage(1);
    void load(tradeDate, 1, nextStage, nextSubtype);
  }

  async function run() {
    if (!tradeDate || running) return;
    setRunning(true); setError(null); setRunStatus({ status: 'running', progress: 0, step_message: '正在准备全市场数据…' });
    try {
      await requestJson('/api/technical-classification/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ trade_date: tradeDate }) });
      for (;;) {
        await new Promise((resolve) => setTimeout(resolve, 1200));
        const status = await requestJson<RunStatus>('/api/technical-classification/status');
        setRunStatus(status);
        if (status.status === 'success') break;
        if (status.status === 'failed') throw new Error(status.error || status.step_message || '技术分类运行失败');
      }
      applyClassification('ALL');
    } catch (e) { setError(e instanceof Error ? e.message : '技术分类运行失败'); }
    finally { setRunning(false); }
  }

  async function triggerAI(code: string) {
    setAiMessage('AI 研究任务提交中…');
    try {
      const result = await requestJson<{ job_id?: string }>('/api/ai/stock-research-async', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ts_codes: [code], date: tradeDate, use_web_search: true }) });
      if (!result.job_id) throw new Error('AI 分析任务未成功创建');
      setAiMessage(`${code} 的 AI 研究已提交`);
    } catch (e) { setAiMessage(e instanceof Error ? e.message : 'AI 分析失败'); }
  }
  async function triggerThemeMatch(code: string) {
    setAiMessage('主题匹配任务执行中…');
    try {
      await requestJson('/api/ai/stock-theme-match', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ts_code: code, date: tradeDate }),
      });
      setAiMessage(`${code} 的主题匹配已完成`);
    } catch (e) {
      setAiMessage(e instanceof Error ? e.message : '主题匹配失败');
      throw e;
    }
  }
  async function runSingleTest() {
    if (!singleInput.trim() || !tradeDate) return;
    setSingleLoading(true); setError(null); setSingleResult(null);
    try { setSingleResult(await requestJson<Item>(`/api/technical-classification/single/${encodeURIComponent(singleInput.trim().toUpperCase())}?trade_date=${tradeDate}`)); }
    catch (e) { setError(e instanceof Error ? e.message : '单股技术分类测试失败'); }
    finally { setSingleLoading(false); }
  }

  const items = payload?.items || [];
  const visible = items.filter((item) => (!search || `${item.ts_code} ${item.name || ''} ${item.industry || ''}`.toLowerCase().includes(search.toLowerCase())) && (!minScore || (item.setup_score ?? -1) >= Number(minScore)));
  const totalPages = Math.max(1, Math.ceil((payload?.total || 0) / PAGE_SIZE));
  const topConcepts = useMemo(() => Object.entries(payload?.concept_counts || {}).sort((a, b) => b[1] - a[1]).slice(0, conceptShowCount), [payload, conceptShowCount]);

  if (showSingleTest) return <TechnicalSingleStockTestView initialEndDate={tradeDate} onBack={() => setShowSingleTest(false)} />;

  return <main className="technical-classification-view mx-auto max-w-[1680px] space-y-5 px-4 pb-10 pt-5 lg:px-8">

    {running && <section className="rounded-xl border border-[#c4c8bc]/60 bg-white p-4"><div className="mb-2 flex justify-between text-xs font-bold text-[#686d68]"><span>{runStatus?.step_message || '正在计算技术形态…'}</span><span>{Math.round((runStatus?.progress || 0) * 100)}%</span></div><div className="h-2 overflow-hidden rounded-full border border-gray-200 bg-gray-100"><div className="h-full bg-gradient-to-r from-[#4a7c59] to-[#705c30] transition-all" style={{ width: `${Math.max(4, (runStatus?.progress || 0) * 100)}%` }} /></div></section>}
    {error && <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}
    {aiMessage && <div className="rounded-xl border border-purple-200 bg-purple-50 px-4 py-3 text-sm text-purple-800">{aiMessage}</div>}

    <section className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
      {Object.entries(stages).map(([key, meta]) => {
        const Icon = meta.Icon;
        const subtypes = payload?.weekly_subtype_counts?.[key] || [];
        return <div key={key} role="button" tabIndex={0} aria-pressed={stage === key} onClick={() => applyClassification(stage === key ? 'ALL' : key)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') applyClassification(stage === key ? 'ALL' : key); }} className={`state-card ${meta.selectionClass} relative min-h-[196px] cursor-pointer overflow-hidden rounded-xl border-2 p-3.5 text-left shadow-xs transition hover:brightness-105 ${meta.card} ${stage === key ? 'is-selected' : 'opacity-90 hover:opacity-100'}`}>
            <div className="flex items-center justify-between text-xs"><span className="flex items-center gap-1 font-bold"><Icon className="h-3.5 w-3.5" />{meta.title}</span><span className="rounded bg-black/10 px-1.5 py-0.5 font-mono text-[10px]">{meta.badge}</span></div>
            <p className="mt-2 text-xl font-bold font-mono">{(payload?.weekly_stage_counts?.[key] || 0).toLocaleString()} 只</p>
            <p className="mt-1 text-[10px] text-white/75">{meta.tip}</p>
            <div className="mt-3 grid grid-cols-2 gap-1">
              {subtypes.map((item, index) => <button key={item.name} aria-pressed={subtype === item.name} onClick={(event) => { event.stopPropagation(); applyClassification(key, item.name); }} className={`flex min-w-0 items-center justify-between gap-1 rounded-md border px-1.5 py-1 text-left text-[10px] font-bold transition hover:brightness-95 ${subtypeTagStyles[index % subtypeTagStyles.length]} ${subtype === item.name ? 'relative z-10 -translate-y-px border-[#2e3230] !border-2 text-[11px] ring-2 ring-white shadow-[0_0_0_2px_rgba(46,50,48,.72),0_4px_10px_rgba(0,0,0,.2)]' : ''}`} title={`筛选：${subtypeNames[item.name] || item.name}`}><span className="truncate">{subtypeNames[item.name] || item.name}</span><span className="shrink-0 font-mono opacity-75">{item.count}</span></button>)}
            </div>
        </div>;
      })}
    </section>

    {loading ? <div className="flex min-h-[260px] items-center justify-center text-sm text-[#686d68]"><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在读取全市场分类快照…</div> : !payload ? <div className="rounded-xl border border-[#c4c8bc]/60 bg-white p-12 text-center text-sm text-[#686d68]">尚未生成技术分类快照。<button onClick={() => setShowSingleTest(true)} className="ml-3 rounded-lg border border-[#c4c8bc] bg-white px-3 py-1.5 text-xs font-bold text-[#3e4a41]">单股测试</button></div> : <>
      <section className="space-y-2 rounded-xl border border-[#c4c8bc]/40 bg-[#f0ece4]/70 p-2.5 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 rounded-lg border border-[#c4c8bc]/50 bg-white px-2.5 py-1"><Search className="h-3.5 w-3.5 text-[#686d68]" /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索当前页代码、名称…" className="w-36 bg-transparent outline-none" /></div>
          <div className="flex items-center gap-1 rounded-lg border border-[#c4c8bc]/50 bg-white px-2 py-1"><span className="font-bold text-[#686d68]">最低分:</span><input value={minScore} onChange={(e) => setMinScore(e.target.value.replace(/\D/g, ''))} placeholder="—" className="w-10 border border-[#c4c8bc]/50 px-1 text-center font-mono outline-none" /><span className="rounded bg-[#faf6f0] px-1.5 py-0.5 text-[10px] font-bold text-[#705c30]">当前结果 {payload.total} 条</span></div>
          <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-[#c4c8bc]/50 bg-white px-2 py-1 font-bold text-[#686d68]"><input type="checkbox" checked={excludeSt} onChange={(event) => { const next = event.target.checked; setExcludeSt(next); setPage(1); void load(tradeDate, 1, stage, subtype, selectedConcept, selectedHotTheme, next); }} className="accent-[#4a7c59]" />剔除 ST</label>
          <button onClick={() => setDrawer(visible[0] || null)} disabled={visible.length === 0} className="inline-flex items-center gap-1.5 rounded-lg border border-[#705c30] bg-[#705c30] px-3 py-1 font-bold text-white disabled:opacity-45"><Brain className="h-3.5 w-3.5" />基本面研究</button>
          <button onClick={() => setShowConcepts((value) => !value)} aria-expanded={showConcepts} className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1 font-bold transition ${showConcepts || selectedConcept !== 'ALL' ? 'border-violet-500 bg-violet-50 text-violet-800' : 'border-violet-200 bg-white text-violet-700 hover:bg-violet-50'}`}><Layers className="h-3.5 w-3.5" />概念筛选{selectedConcept !== 'ALL' ? ' · 已选' : ''}</button>
          <div className="ml-auto flex items-center gap-3"><button onClick={() => setShowSingleTest(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#4a7c59]/45 bg-emerald-50 px-3 py-1.5 font-bold text-[#326044] shadow-2xs transition hover:border-[#4a7c59] hover:bg-emerald-100"><TestTube2 className="h-3.5 w-3.5" />单股测试</button><span className="text-[#686d68]">第 {page} / {totalPages} 页</span></div>
        </div>
        {showConcepts && <div className="flex flex-wrap items-center gap-1.5 border-t border-[#d9d4ca]/60 pt-2"><span className="mr-1 font-bold text-[#686d68]">概念筛选:</span><button onClick={() => { setSelectedConcept('ALL'); setPage(1); void load(tradeDate, 1, stage, subtype, 'ALL', selectedHotTheme); }} className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 font-bold ${selectedConcept === 'ALL' ? 'bg-violet-700 text-white' : 'border border-violet-200 bg-white text-violet-800'}`}><Layers className="h-3.5 w-3.5" />全部概念</button>{topConcepts.map(([name, count]) => <button key={name} onClick={() => { setSelectedConcept(name); setPage(1); void load(tradeDate, 1, stage, subtype, name, selectedHotTheme); }} className={`rounded-md border px-2.5 py-1 font-bold ${selectedConcept === name ? 'border-violet-700 bg-violet-700 text-white' : 'border-violet-200 bg-white text-violet-800 hover:bg-violet-50'}`}>{name} ({count})</button>)}{Object.keys(payload.concept_counts || {}).length > conceptShowCount && <button onClick={() => setConceptShowCount((n) => n + 24)} className="rounded-md border border-dashed border-violet-500/60 px-2 py-1 font-bold text-violet-700">更多</button>}</div>}
        <div className="flex flex-wrap items-center gap-1.5 border-t border-[#d9d4ca]/60 pt-2"><span className="mr-1 font-bold text-[#686d68]">近期热点方向:</span><button onClick={() => { setSelectedHotTheme('ALL'); setPage(1); void load(tradeDate, 1, stage, subtype, selectedConcept, 'ALL'); }} className={`rounded-md px-2.5 py-1 font-bold ${selectedHotTheme === 'ALL' ? 'bg-amber-700 text-white' : 'border border-amber-200 bg-white text-amber-800'}`}>不限</button><button onClick={() => { setSelectedHotTheme('ALL_RECENT'); setPage(1); void load(tradeDate, 1, stage, subtype, selectedConcept, 'ALL_RECENT'); }} className={`rounded-md border px-2.5 py-1 font-bold ${selectedHotTheme === 'ALL_RECENT' ? 'border-amber-600 bg-amber-600 text-white' : 'border border-amber-200 bg-white text-amber-800 hover:bg-amber-50'}`}>全部近期热点</button>{(payload.hot_theme_options || []).map((option) => <button key={option.canonical_name} onClick={() => { const next = selectedHotTheme === option.canonical_name ? 'ALL' : option.canonical_name; setSelectedHotTheme(next); setPage(1); void load(tradeDate, 1, stage, subtype, selectedConcept, next); }} className={`rounded-md border px-2.5 py-1 font-bold ${selectedHotTheme === option.canonical_name ? 'border-amber-600 bg-amber-600 text-white' : 'border-amber-200 bg-white text-amber-800 hover:bg-amber-50'}`}>{option.canonical_name} ({option.match_count})</button>)}{payload.hot_theme_issue && <span className="text-[11px] font-bold text-rose-700">热点数据不可用：{payload.hot_theme_issue}</span>}</div>
      </section>

      <section className="overflow-hidden rounded-xl border border-[#c4c8bc]/60 bg-white shadow-xs">
        <div className="overflow-x-auto"><table className="w-full min-w-[1320px] text-left text-sm"><thead className="bg-[#f0ece4]/80 text-xs font-bold text-[#5f655f]"><tr><th className="px-4 py-3">代码 & 名称</th><th className="px-3 py-3">周线阶段</th><th className="px-3 py-3">日线子分类</th><th className="px-3 py-3">技术得分</th><th className="px-3 py-3">形态状态</th><th className="px-3 py-3">基本面</th><th className="px-3 py-3">同花顺概念</th><th className="px-4 py-3 text-right">操作</th></tr></thead><tbody>{visible.map((item) => {
          const meta = stages[item.weekly_stage]; const episode = item.episode_json || item.episode_fields || {};
          const financial = item.financial_facts || {};
          return <tr key={item.ts_code} className="border-t border-[#eeeae2] hover:bg-[#faf8f3]"><td className="px-4 py-3"><div className="font-bold text-[#bf1f4e]">{item.ts_code} <span className="text-[#2e3230]">{item.name || ''}</span></div><span className="mt-1 inline-block rounded bg-[#eef1f5] px-1.5 py-0.5 text-[10px] text-[#667080]">{item.industry || '行业未标注'}</span></td><td className="px-3 py-3"><span className="rounded bg-slate-100 px-2 py-1 text-xs font-bold text-slate-700">{meta?.short || item.weekly_stage}</span></td><td className="px-3 py-3 font-bold text-[#4b3a68]">{subtypeNames[item.daily_subtype] || item.daily_subtype}</td><td className="px-3 py-3"><span className="font-mono text-lg font-bold text-[#202b40]">{item.setup_score ?? '—'}</span><span className="ml-1 text-[10px] text-[#899289]">{item.score_type || ''}</span></td><td className="px-3 py-3"><span className="rounded border border-[#d9ccff] bg-[#faf7ff] px-2 py-1 text-xs text-[#6730cf]">{episodeNames[String(episode.state || 'NONE')] || String(episode.state || 'NONE')}</span></td><td className="max-w-[250px] px-3 py-3 text-xs text-[#616b62]"><div className="flex flex-wrap gap-1">{financial.type && <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold ${forecastTone(financial.type)}`}>{forecastLabel(financial.type)}</span>}{financial.total_revenue != null && <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-700">营收 {formatFinancialAmount(financial.total_revenue)}</span>}{financial.n_income_attr_p != null && <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-700">归母净利 {formatFinancialAmount(financial.n_income_attr_p)}</span>}{financial.n_cashflow_act != null && <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-700">经营现金流 {formatFinancialAmount(financial.n_cashflow_act)}</span>}</div></td><td className="max-w-[260px] px-3 py-3 text-xs text-[#616b62]"><div className="flex flex-wrap gap-1">{(item.ths_concepts || []).slice(0, 6).map((name) => <span key={name} className="rounded border border-violet-200 bg-violet-50 px-1.5 py-0.5 text-[10px] text-violet-800">{name}</span>)}</div></td><td className="px-4 py-3"><div className="flex justify-end gap-1.5"><button onClick={() => setDrawer(item)} className="rounded-md border border-[#c4c8bc] px-2.5 py-1.5 text-xs font-bold text-[#3e4a41]">详情</button><button onClick={() => setSelected(item)} className="inline-flex items-center gap-1 rounded-md bg-[#303736] px-2.5 py-1.5 text-xs font-bold text-white"><LineChart className="h-3.5 w-3.5" />K线</button><button onClick={() => void triggerAI(item.ts_code)} className="inline-flex items-center gap-1 rounded-md border border-purple-300 px-2.5 py-1.5 text-xs font-bold text-purple-700"><Sparkles className="h-3.5 w-3.5" />AI池</button></div></td></tr>;
        })}</tbody></table></div>
        {visible.length === 0 && <div className="p-12 text-center text-sm text-[#686d68]">没有符合当前筛选条件的股票。</div>}
        <div className="flex items-center justify-between border-t border-[#eeeae2] px-4 py-3 text-xs text-[#686d68]"><span>当前页 {visible.length} 条 · 共 {payload.total} 条</span><div className="flex gap-2"><button disabled={page <= 1} onClick={() => { const next = page - 1; setPage(next); void load(tradeDate, next, stage, subtype, selectedConcept, selectedHotTheme); }} className="rounded border border-[#c4c8bc] px-2.5 py-1 disabled:opacity-40">上一页</button><button disabled={page >= totalPages} onClick={() => { const next = page + 1; setPage(next); void load(tradeDate, next, stage, subtype, selectedConcept, selectedHotTheme); }} className="rounded border border-[#c4c8bc] px-2.5 py-1 disabled:opacity-40">下一页</button></div></div>
      </section>
    </>}
    {selected && <KLineModal assetCode={selected.ts_code} assetName={selected.name || selected.ts_code} industry={selected.industry} scoreTradeDate={tradeDate} isOpen={true} onClose={() => setSelected(null)} showSubIndicators={false} showAiPoolButton={true} />}
    {drawer && <SecondaryStockDetailDrawer isOpen={true} onClose={() => setDrawer(null)} tsCode={drawer.ts_code} asOfDate={tradeDate} stockName={drawer.name} onTriggerThemeMatch={triggerThemeMatch} onTriggerAI={triggerAI} />}
  </main>;
}

function SingleResult({ item, onKLine, onResearch, onAI }: { item: Item; onKLine: () => void; onResearch: () => void; onAI: () => void }) {
  const episode = item.episode_json || item.episode_fields || {};
  return <section className="rounded-xl border border-[#c4c8bc]/60 bg-white p-5"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-lg font-bold text-[#2e3230]">{item.ts_code} {item.name || ''}</p><p className="mt-1 text-xs text-[#686d68]">{item.industry || '行业未标注'} · {item.ths_concepts?.slice(0, 5).join(' · ') || '暂无同花顺概念标签'}</p></div><div className="flex gap-2"><button onClick={onResearch} className="rounded-md border border-[#c4c8bc] px-3 py-1.5 text-xs font-bold">详情</button><button onClick={onKLine} className="rounded-md bg-[#303736] px-3 py-1.5 text-xs font-bold text-white">K线</button><button onClick={onAI} className="rounded-md border border-purple-300 px-3 py-1.5 text-xs font-bold text-purple-700">AI池</button></div></div><div className="mt-5 grid gap-3 md:grid-cols-4"><TestMetric label="周线阶段" value={stages[item.weekly_stage]?.short || item.weekly_stage} /><TestMetric label="日线子分类" value={subtypeNames[item.daily_subtype] || item.daily_subtype} /><TestMetric label="技术得分" value={item.setup_score == null ? '—' : String(item.setup_score)} /><TestMetric label="形态状态" value={episodeNames[String(episode.state || 'NONE')] || String(episode.state || 'NONE')} /></div></section>;
}

function TestMetric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-[#f5f2eb] p-3"><p className="text-[11px] font-bold text-[#686d68]">{label}</p><p className="mt-1 text-sm font-bold text-[#2e3230]">{value}</p></div>;
}
