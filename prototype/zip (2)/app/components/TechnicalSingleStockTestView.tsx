'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { init, dispose, Chart } from 'klinecharts';
import { ArrowLeft, Calendar, Download, LineChart, Loader2, PlayCircle, Search } from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL || 'http://127.0.0.1:18080';

type DayResult = { trade_date: string; weekly_stage: string; daily_subtype: string; score: number | null; score_type?: string | null; episode: Record<string, unknown>; reason_codes: string[]; features: Record<string, number | string | null> };
type Kline = { trade_date: string; open: number; high: number; low: number; close: number; vol: number; amount: number };
type Result = { ts_code: string; name?: string; industry?: string; start_date: string; end_date: string; history: DayResult[]; klines: Kline[]; latest: DayResult };

const subtypeNames: Record<string, string> = { W1_BASE_RANGE: '底部箱体', W1_BASE_COMPRESSION: '底部压缩', W1_EARLY_PREP: '底部早期准备', W1_FIRST_TURN: '首次转强', W1_BREAKOUT: '底部突破', W1_BREAKOUT_PULLBACK: '突破后回踩', W1_BREAKOUT_REACCEL: '突破再启动', W1_FAILED_BREAKOUT: '突破失败', W2_STEADY_ADVANCE: '稳步上升', W2_ACCEL_EXTENDED: '加速乖离', W2_PULLBACK: '上升回踩', W2_PULLBACK_STABILIZING: '回踩企稳', W2_REACCEL: '趋势再加速', W2_TREND_DAMAGE: '趋势受损', W3_HIGH_RANGE: '高位箱体', W3_HIGH_COMPRESSION: '高位压缩', W3_HIGH_REPAIR: '高位修复', W3_HIGH_REACCEL: '高位再加速', W3_HIGH_WEAKENING: '高位走弱', W3_BREAKDOWN: '高位破位', W3_POST_BREAKDOWN_REBOUND: '破位后反弹', W4_DECLINE: '下跌延续', W4_ACCEL_DECLINE: '加速下跌', W4_DECLINE_DECELERATING: '下跌减速', W4_EARLY_PREP: '下跌早期准备', W4_FIRST_TURN: '首次转强', W4_FIRST_ADVANCE: '第一波推进', W4_FIRST_PULLBACK: '首次回踩', W4_SECOND_TURN: '二次转强', W4_MATURE_REBOUND: '成熟反弹' };
const stageNames: Record<string, string> = { W1_BASE: '底部构筑', W2_ADVANCE: '上升推进', W3_TOP: '高位转换', W4_DECLINE: '回撤修复' };
const episodeNames: Record<string, string> = { NONE: '无', BREAKOUT: '突破', PULLBACK: '回踩', REACCEL: '再加速', STABILIZING: '企稳', BREAKDOWN: '破位' };
const scoreTypeNames: Record<string, string> = { PREP_SCORE: '准备度评分', TURN_SCORE: '转强评分' };
const episodeName = (item: DayResult) => episodeNames[String(item.episode?.state || 'NONE')] || '无';

function dateOffset(days: number) {
  const d = new Date(); d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function TechnicalSingleStockTestView({ initialEndDate, onBack }: { initialEndDate: string; onBack: () => void }) {
  const [code, setCode] = useState('');
  const [startDate, setStartDate] = useState(dateOffset(-30));
  const [endDate, setEndDate] = useState(initialEndDate ? `${initialEndDate.slice(0, 4)}-${initialEndDate.slice(4, 6)}-${initialEndDate.slice(6, 8)}` : dateOffset(0));
  const [result, setResult] = useState<Result | null>(null);
  const [selectedDate, setSelectedDate] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<Chart | null>(null);

  const active = useMemo(() => result?.history.find((item) => item.trade_date === selectedDate) || result?.latest || null, [result, selectedDate]);

  useEffect(() => {
    if (!result || !chartRef.current) return;
    if (chartInstance.current) dispose(chartRef.current);
    const chart = init(chartRef.current, { timezone: 'Asia/Shanghai' });
    if (!chart) return;
    chartInstance.current = chart;
    chart.createIndicator({ name: 'MA', paneId: 'candle_pane', calcParams: [5, 10, 20, 30, 60] }, true);
    chart.setSymbol({ ticker: result.ts_code, pricePrecision: 2, volumePrecision: 2 });
    chart.setPeriod({ span: 1, type: 'day' });
    chart.setDataLoader({
      getBars: ({ callback }) => callback(result.klines.map((item) => ({
        timestamp: Date.UTC(Number(item.trade_date.slice(0, 4)), Number(item.trade_date.slice(4, 6)) - 1, Number(item.trade_date.slice(6, 8))),
        open: item.open, high: item.high, low: item.low, close: item.close, volume: item.vol, turnover: item.amount, trade_date: item.trade_date,
      }))),
    });
    return () => { if (chartRef.current) dispose(chartRef.current); chartInstance.current = null; };
  }, [result]);

  async function run() {
    if (!code.trim()) return;
    setLoading(true); setError('');
    try {
      const query = new URLSearchParams({ start_date: startDate, end_date: endDate });
      const response = await fetch(`${API_BASE}/api/technical-classification/single/${encodeURIComponent(code.trim().toUpperCase())}/history?${query}`);
      const raw = await response.text();
      if (!response.ok) throw new Error(JSON.parse(raw).detail || raw);
      const next = JSON.parse(raw) as Result;
      setResult(next); setSelectedDate(next.latest.trade_date);
    } catch (err) { setError(err instanceof Error ? err.message : '单股测试失败'); }
    finally { setLoading(false); }
  }

  function exportDetail() {
    if (!result) return;
    const lines = [
      '# 技术形态单股测试',
      '',
      `股票：${result.ts_code} ${result.name || ''}`,
      `区间：${result.start_date} 至 ${result.end_date}`,
      '',
      '## 逐日分类结果',
      '',
      '| 日期 | 周线阶段 | 日线子分类 | 技术得分 | 形态状态 |',
      '| --- | --- | --- | --- | --- |',
      ...result.history.map((item) => `| ${item.trade_date} | ${stageNames[item.weekly_stage] || item.weekly_stage} | ${subtypeNames[item.daily_subtype] || item.daily_subtype} | ${item.score ?? '不适用'} | ${episodeName(item)} |`),
      '',
      '## 区间 K 线数据',
      '',
      '| 日期 | 开盘 | 最高 | 最低 | 收盘 | 成交量 | 成交额 |',
      '| --- | ---: | ---: | ---: | ---: | ---: | ---: |',
      ...result.klines.map((item) => `| ${item.trade_date} | ${item.open} | ${item.high} | ${item.low} | ${item.close} | ${item.vol} | ${item.amount} |`),
    ];
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
    const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `${result.ts_code}_技术形态_${result.start_date}-${result.end_date}.md`; link.click(); URL.revokeObjectURL(link.href);
  }

  return <main className="mx-auto max-w-[1680px] space-y-3 px-4 pb-10 pt-5 lg:px-8">
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#c4c8bc]/60 bg-white/90 px-3.5 py-2.5 text-xs shadow-xs">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5 rounded-lg border border-[#c4c8bc]/50 bg-[#faf6f0] px-2.5 py-1"><LineChart className="h-3.5 w-3.5 text-[#4a7c59]" /><span className="font-bold">分类规则:</span><span className="rounded bg-white px-2 py-0.5 font-bold">全市场技术分类 W1–W4</span></div>
        <div className="flex items-center gap-1.5 rounded-lg border border-[#c4c8bc]/50 bg-[#faf6f0] px-2.5 py-1"><Search className="h-3.5 w-3.5 text-[#705c30]" /><span className="font-bold">股票:</span><input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} onKeyDown={(e) => { if (e.key === 'Enter') void run(); }} placeholder="688505 或 康美药业" className="w-36 rounded border border-[#c4c8bc]/60 bg-white px-2 py-0.5 font-mono font-bold outline-none" /></div>
        <div className="flex items-center gap-1.5 rounded-lg border border-[#c4c8bc]/50 bg-[#faf6f0] px-2.5 py-1"><Calendar className="h-3.5 w-3.5 text-[#4a7c59]" /><span className="font-bold">日期区间:</span><input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="rounded border border-[#c4c8bc]/60 bg-white px-1.5 py-0.5 font-mono font-bold outline-none" /><span>至</span><input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="rounded border border-[#c4c8bc]/60 bg-white px-1.5 py-0.5 font-mono font-bold outline-none" /></div>
      </div>
      <div className="flex items-center gap-2"><button onClick={onBack} className="inline-flex items-center gap-1 rounded-lg border border-[#c4c8bc] bg-white px-3 py-1.5 font-bold text-[#3e4a41]"><ArrowLeft className="h-3.5 w-3.5" />返回</button><button onClick={() => void run()} disabled={loading || !code.trim()} className="inline-flex items-center gap-1.5 rounded-lg bg-[#4a7c59] px-3.5 py-1.5 font-bold text-white disabled:opacity-50">{loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlayCircle className="h-3.5 w-3.5" />}{loading ? '计算中…' : '开始测试'}</button></div>
    </div>
    {error && <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-bold text-rose-800">{error}</div>}
    <section className="relative rounded-xl border border-[#c4c8bc]/60 bg-white p-4 shadow-xs"><div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-[#c4c8bc]/40 pb-2 text-xs">{result ? <div className="flex items-center gap-2"><span className="rounded bg-[#4a7c59] px-2 py-0.5 font-mono font-bold text-white">{result.ts_code}</span><span className="text-base font-bold">{result.name}</span><span className="rounded bg-emerald-50 px-2 py-0.5 font-bold text-[#4a7c59]">{result.industry}</span></div> : <span className="font-bold">单股历史 K 线图</span>}<span className="font-bold text-[#686d68]">MA5 · MA10 · MA20 · MA30 · MA60</span></div><div ref={chartRef} className="h-[520px] w-full bg-white" /></section>
    {active && <section className="overflow-hidden rounded-xl border border-[#c4c8bc]/60 bg-white shadow-xs"><div className="flex items-center justify-between bg-[#f0ece4] px-3 py-2 text-xs"><span className="font-bold">技术形态详情 · {active.trade_date}</span><button onClick={exportDetail} className="inline-flex items-center gap-1 rounded bg-[#4a7c59] px-2.5 py-1 font-bold text-white"><Download className="h-3.5 w-3.5" />导出详情</button></div><div className="grid gap-3 p-3 md:grid-cols-5"><Metric label="周线阶段" value={stageNames[active.weekly_stage] || active.weekly_stage} /><Metric label="日线子分类" value={subtypeNames[active.daily_subtype] || active.daily_subtype} /><Metric label="技术得分" value={active.score == null ? '不适用' : String(active.score)} /><Metric label="形态状态" value={episodeName(active)} /><Metric label="得分类型" value={scoreTypeNames[active.score_type || ''] || '不适用'} /></div><div className="border-t border-[#eeeae2]"><table className="w-full text-left text-xs"><thead className="bg-[#faf6f0] text-[#686d68]"><tr><th className="px-3 py-2">日期</th><th className="px-3 py-2">周线阶段</th><th className="px-3 py-2">日线子分类</th><th className="px-3 py-2">得分</th><th className="px-3 py-2">形态状态</th></tr></thead><tbody>{result?.history.map((item) => <tr key={item.trade_date} onClick={() => setSelectedDate(item.trade_date)} className={`cursor-pointer border-t border-[#eeeae2] hover:bg-[#faf8f3] ${selectedDate === item.trade_date ? 'bg-emerald-50' : ''}`}><td className="px-3 py-2 font-mono">{item.trade_date}</td><td className="px-3 py-2">{stageNames[item.weekly_stage] || item.weekly_stage}</td><td className="px-3 py-2 font-bold">{subtypeNames[item.daily_subtype] || item.daily_subtype}</td><td className="px-3 py-2 font-mono">{item.score ?? '不适用'}</td><td className="px-3 py-2">{episodeName(item)}</td></tr>)}</tbody></table></div></section>}
  </main>;
}
function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-lg bg-[#f5f2eb] p-3"><p className="text-[11px] font-bold text-[#686d68]">{label}</p><p className="mt-1 text-sm font-bold text-[#2e3230]">{value}</p></div>; }
