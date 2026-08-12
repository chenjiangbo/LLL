'use client';

import dynamic from 'next/dynamic';
import React, { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  Box,
  Database,
  Filter,
  LineChart,
  Loader2,
  PlayCircle,
  RotateCcw,
  Search,
} from 'lucide-react';

const KLineModal = dynamic(() => import('./KLineModal'), { ssr: false });

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL || 'http://127.0.0.1:18080';

type Mode = 'box-v2' | 'pressure-v1';

type FreshnessInfo = {
  daily_market_date?: string;
  candidate_date?: string;
};

type BoxRequest = {
  start_date: string;
  end_date: string;
  top_n: number;
  min_breakout_volume: number;
  max_breakout_pct: number;
  min_inside_ratio: number;
  max_drift_ratio: number;
  exclude_st: boolean;
};

type PressureRequest = {
  start_date: string;
  end_date: string;
  top_n: number;
  min_liquidity: number;
  breakout_amount_min_ratio: number;
  preheat_min_ratio: number;
  exclude_st: boolean;
};

type BoxItem = {
  ts_code: string;
  name: string;
  trade_date: string;
  box_window: number;
  box_start: string;
  box_end: string;
  support: number;
  resistance: number;
  box_width: number;
  inside_ratio: number;
  drift_ratio: number;
  efficiency_ratio: number;
  upper_touch_count: number;
  lower_touch_count: number;
  upper_touch_span: number;
  preheat3: number;
  preheat5: number;
  hot_days5: number;
  breakout_pct: number;
  breakout_volume: number;
  close_location: number;
  body_pct: number;
  gap_pct: number;
  box_score: number;
  breakout_score: number;
  volume_score: number;
  total_score: number;
  bonus_score: number;
  reject_reason?: string;
  industry_l1?: string;
};

type PressureItem = {
  ts_code: string;
  name: string;
  trade_date: string;
  total_score: number;
  position_120: number;
  drawdown_120: number;
  resistance: number;
  touch_count: number;
  pre_break_distance: number;
  amount_preheat_5_20: number;
  hot_days_5: number;
  breakout_pct: number;
  breakout_amount_ratio: number;
  extension_atr: number;
  industry_l1?: string;
};

type BoxPayload = {
  metadata: {
    start_date: string;
    end_date: string;
    effective_start_date: string;
    effective_end_date: string;
    scanned_assets: number;
    scanned_events: number;
    candidate_count: number;
    near_miss_count: number;
    returned_count: number;
    near_miss_returned_count: number;
    strict_csv_path?: string;
    near_miss_csv_path?: string;
  };
  reject_counts: Record<string, number>;
  items: BoxItem[];
  near_miss_items: BoxItem[];
};

type PressurePayload = {
  metadata: {
    start_date: string;
    end_date: string;
    effective_start_date: string;
    effective_end_date: string;
    scanned_assets: number;
    scanned_events: number;
    candidate_count: number;
    returned_count: number;
  };
  reject_counts: Record<string, number>;
  items: PressureItem[];
};

const DEFAULT_BOX_REQUEST: BoxRequest = {
  start_date: '20260101',
  end_date: '',
  top_n: 300,
  min_breakout_volume: 1.3,
  max_breakout_pct: 0.08,
  min_inside_ratio: 0.7,
  max_drift_ratio: 0.45,
  exclude_st: true,
};

const DEFAULT_PRESSURE_REQUEST: PressureRequest = {
  start_date: '20260401',
  end_date: '',
  top_n: 100,
  min_liquidity: 10000000,
  breakout_amount_min_ratio: 1.3,
  preheat_min_ratio: 1.15,
  exclude_st: true,
};

export default function ReverseBreakoutPage() {
  const [mode, setMode] = useState<Mode>('box-v2');
  const [boxRequest, setBoxRequest] = useState<BoxRequest>(DEFAULT_BOX_REQUEST);
  const [pressureRequest, setPressureRequest] = useState<PressureRequest>(DEFAULT_PRESSURE_REQUEST);
  const [freshness, setFreshness] = useState<FreshnessInfo>({});
  const [boxPayload, setBoxPayload] = useState<BoxPayload | null>(null);
  const [pressurePayload, setPressurePayload] = useState<PressurePayload | null>(null);
  const [showNearMiss, setShowNearMiss] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [klineIndex, setKlineIndex] = useState(-1);

  useEffect(() => {
    fetch(`${API_BASE}/api/screening/freshness`, { cache: 'no-store' })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: FreshnessInfo) => {
        setFreshness(data);
        setBoxRequest((prev) => ({ ...prev, end_date: prev.end_date || data.daily_market_date || '' }));
        setPressureRequest((prev) => ({ ...prev, end_date: prev.end_date || data.daily_market_date || '' }));
        if (data.daily_market_date) {
          loadSavedBoxPayload('20260101', data.daily_market_date);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : '读取数据日期失败'));
  }, []);

  const activeItems = useMemo(() => {
    const rows = mode === 'box-v2'
      ? (showNearMiss ? boxPayload?.near_miss_items || [] : boxPayload?.items || [])
      : pressurePayload?.items || [];
    const keyword = query.trim().toLowerCase();
    if (!keyword) return rows;
    return rows.filter((item) => (
      item.ts_code.toLowerCase().includes(keyword)
      || item.name.toLowerCase().includes(keyword)
      || (item.industry_l1 || '').toLowerCase().includes(keyword)
    ));
  }, [boxPayload, mode, pressurePayload, query, showNearMiss]);

  const currentKline = klineIndex >= 0 ? activeItems[klineIndex] : null;

  async function runReverseFinder() {
    setLoading(true);
    setError(null);
    try {
      const endpoint = mode === 'box-v2' ? 'reverse-box-breakout' : 'reverse-breakout';
      const request = mode === 'box-v2'
        ? {
            ...boxRequest,
            start_date: cleanDate(boxRequest.start_date),
            end_date: cleanDate(boxRequest.end_date),
          }
        : {
            ...pressureRequest,
            start_date: cleanDate(pressureRequest.start_date),
            end_date: cleanDate(pressureRequest.end_date),
          };
      const res = await fetch(`${API_BASE}/api/screening/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      if (mode === 'box-v2') setBoxPayload(data);
      else setPressurePayload(data);
      setKlineIndex(-1);
    } catch (err) {
      setError(err instanceof Error ? err.message : '反查扫描失败');
    } finally {
      setLoading(false);
    }
  }

  async function loadSavedBoxPayload(startDate: string, endDate: string) {
    setError(null);
    try {
      const params = new URLSearchParams({
        start_date: cleanDate(startDate),
        end_date: cleanDate(endDate),
        top_n: String(DEFAULT_BOX_REQUEST.top_n),
      });
      const res = await fetch(`${API_BASE}/api/screening/reverse-box-breakout/saved?${params.toString()}`, {
        cache: 'no-store',
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setBoxPayload(data);
      setShowNearMiss(false);
    } catch (err) {
      setError(err instanceof Error ? `读取已保存 V2 反查结果失败：${err.message}` : '读取已保存 V2 反查结果失败');
    }
  }

  function openKline(index: number) {
    if (index < 0 || index >= activeItems.length) return;
    setKlineIndex(index);
  }

  const payload = mode === 'box-v2' ? boxPayload : pressurePayload;

  return (
    <div className="px-4 py-5 sm:px-6 lg:px-8">
      <section className="mb-4 border-b border-[#c4c8bc]/40 pb-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-1 flex items-center gap-2 text-xs font-bold text-[#705c30]">
              <Search className="h-4 w-4" />
              Historical Pattern Reverse Finder
            </div>
            <h1 className="font-[family-name:var(--font-literata)] text-2xl font-extrabold text-[#2e3230]">
              A股技术形态样本反查
            </h1>
            <p className="mt-1 max-w-4xl text-sm leading-6 text-[#4a4e4a]">
              V2 按“长期横盘箱体、边界稳定、右端刚突破、突破日放量”扫描；低位和题材只做加分，不参与硬过滤。
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-lg border border-[#c4c8bc]/40 bg-[#f0ece4] px-3 py-2 text-xs text-[#4a4e4a]">
            <Database className="h-4 w-4 text-[#4a7c59]" />
            日线至 <strong className="text-[#2e3230]">{formatDate(freshness.daily_market_date || boxRequest.end_date)}</strong>
          </div>
        </div>
      </section>

      <section className="mb-4 flex flex-wrap gap-2">
        <ModeButton active={mode === 'box-v2'} onClick={() => { setMode('box-v2'); setKlineIndex(-1); }}>
          <Box className="h-4 w-4" />
          横盘箱体突破 V2
        </ModeButton>
        <ModeButton active={mode === 'pressure-v1'} onClick={() => { setMode('pressure-v1'); setKlineIndex(-1); }}>
          <BarChart3 className="h-4 w-4" />
          压力位突破 V1
        </ModeButton>
      </section>

      <section className="mb-4 rounded-lg border border-[#c4c8bc]/30 bg-[#f0ece4] p-4 shadow-sm">
        {mode === 'box-v2' ? (
          <div className="grid gap-3 lg:grid-cols-[repeat(8,minmax(0,1fr))_auto]">
            <Field label="开始日期"><Input value={boxRequest.start_date} onChange={(value) => setBoxRequest((prev) => ({ ...prev, start_date: value }))} /></Field>
            <Field label="结束日期"><Input value={boxRequest.end_date} onChange={(value) => setBoxRequest((prev) => ({ ...prev, end_date: value }))} /></Field>
            <Field label="Top N"><NumberInput min={20} max={500} value={boxRequest.top_n} onChange={(value) => setBoxRequest((prev) => ({ ...prev, top_n: value }))} /></Field>
            <Field label="突破放量"><NumberInput step={0.05} value={boxRequest.min_breakout_volume} onChange={(value) => setBoxRequest((prev) => ({ ...prev, min_breakout_volume: value }))} /></Field>
            <Field label="最远突破"><NumberInput step={0.01} value={boxRequest.max_breakout_pct} onChange={(value) => setBoxRequest((prev) => ({ ...prev, max_breakout_pct: value }))} /></Field>
            <Field label="箱内占比"><NumberInput step={0.05} value={boxRequest.min_inside_ratio} onChange={(value) => setBoxRequest((prev) => ({ ...prev, min_inside_ratio: value }))} /></Field>
            <Field label="最大漂移"><NumberInput step={0.05} value={boxRequest.max_drift_ratio} onChange={(value) => setBoxRequest((prev) => ({ ...prev, max_drift_ratio: value }))} /></Field>
            <CheckField checked={boxRequest.exclude_st} onChange={(value) => setBoxRequest((prev) => ({ ...prev, exclude_st: value }))} />
            <RunButton loading={loading} onClick={runReverseFinder} />
          </div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-[repeat(7,minmax(0,1fr))_auto]">
            <Field label="开始日期"><Input value={pressureRequest.start_date} onChange={(value) => setPressureRequest((prev) => ({ ...prev, start_date: value }))} /></Field>
            <Field label="结束日期"><Input value={pressureRequest.end_date} onChange={(value) => setPressureRequest((prev) => ({ ...prev, end_date: value }))} /></Field>
            <Field label="Top N"><NumberInput min={20} max={300} value={pressureRequest.top_n} onChange={(value) => setPressureRequest((prev) => ({ ...prev, top_n: value }))} /></Field>
            <Field label="20日成交额底线"><NumberInput step={1000000} value={pressureRequest.min_liquidity} onChange={(value) => setPressureRequest((prev) => ({ ...prev, min_liquidity: value }))} /></Field>
            <Field label="预热倍率"><NumberInput step={0.05} value={pressureRequest.preheat_min_ratio} onChange={(value) => setPressureRequest((prev) => ({ ...prev, preheat_min_ratio: value }))} /></Field>
            <Field label="突破放量倍率"><NumberInput step={0.05} value={pressureRequest.breakout_amount_min_ratio} onChange={(value) => setPressureRequest((prev) => ({ ...prev, breakout_amount_min_ratio: value }))} /></Field>
            <CheckField checked={pressureRequest.exclude_st} onChange={(value) => setPressureRequest((prev) => ({ ...prev, exclude_st: value }))} />
            <RunButton loading={loading} onClick={runReverseFinder} />
          </div>
        )}
      </section>

      {error && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-[#b83230]/30 bg-[#f0ece4] p-4 text-sm text-[#8f2927]">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="break-words">{error}</span>
        </div>
      )}

      {payload && (
        <>
          <section className="mb-4 grid gap-3 md:grid-cols-4">
            <SummaryMetric label="实际扫描区间" value={`${formatDate(payload.metadata.effective_start_date)} ~ ${formatDate(payload.metadata.effective_end_date)}`} />
            <SummaryMetric label="扫描事件" value={payload.metadata.scanned_events.toLocaleString()} />
            <SummaryMetric label="严格候选" value={payload.metadata.candidate_count.toLocaleString()} />
            <SummaryMetric label={mode === 'box-v2' ? 'Near Miss' : '返回结果'} value={mode === 'box-v2' ? (boxPayload?.metadata.near_miss_count || 0).toLocaleString() : payload.metadata.returned_count.toLocaleString()} />
          </section>

          {mode === 'box-v2' && boxPayload && (
            <section className="mb-4 flex flex-wrap items-center gap-2 text-xs">
              <ModeButton active={!showNearMiss} onClick={() => { setShowNearMiss(false); setKlineIndex(-1); }}>严格通过 {boxPayload.metadata.returned_count}</ModeButton>
              <ModeButton active={showNearMiss} onClick={() => { setShowNearMiss(true); setKlineIndex(-1); }}>箱体近似 {boxPayload.metadata.near_miss_returned_count}</ModeButton>
              <span className="text-[#686d68]">CSV: {boxPayload.metadata.strict_csv_path || '未生成'} / {boxPayload.metadata.near_miss_csv_path || '未生成'}</span>
            </section>
          )}

          <section className="mb-4 grid gap-4 lg:grid-cols-[1fr_320px]">
            <div className="rounded-lg border border-[#c4c8bc]/30 bg-[#f0ece4] shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#c4c8bc]/30 px-4 py-3">
                <div className="flex items-center gap-2 text-sm font-bold text-[#2e3230]">
                  <BarChart3 className="h-4 w-4 text-[#4a7c59]" />
                  {mode === 'box-v2' ? (showNearMiss ? 'V2 箱体近似样本' : 'V2 严格通过样本') : 'V1 压力位突破样本'}
                </div>
                <label className="flex items-center gap-2 rounded-md border border-[#c4c8bc]/50 bg-white px-2.5 py-1.5 text-xs text-[#4a4e4a]">
                  <Filter className="h-3.5 w-3.5" />
                  <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="代码 / 名称 / 行业" className="w-40 bg-transparent outline-none" />
                </label>
              </div>
              {mode === 'box-v2'
                ? <BoxTable items={activeItems as BoxItem[]} onOpen={openKline} />
                : <PressureTable items={activeItems as PressureItem[]} onOpen={openKline} />}
            </div>

            <aside className="rounded-lg border border-[#c4c8bc]/30 bg-[#f0ece4] p-4 shadow-sm">
              <div className="mb-3 flex items-center gap-2 text-sm font-bold text-[#2e3230]">
                <RotateCcw className="h-4 w-4 text-[#705c30]" />
                未入选原因统计
              </div>
              <div className="space-y-2 text-xs">
                {Object.entries(payload.reject_counts).slice(0, 14).map(([reason, count]) => (
                  <div key={reason} className="flex items-center justify-between gap-3 rounded-md bg-[#faf6f0] px-3 py-2">
                    <span className="font-mono text-[#4a4e4a]">{reason}</span>
                    <strong className="text-[#2e3230]">{count.toLocaleString()}</strong>
                  </div>
                ))}
              </div>
            </aside>
          </section>
        </>
      )}

      <KLineModal
        assetCode={currentKline?.ts_code || ''}
        assetName={currentKline?.name || currentKline?.ts_code || ''}
        isOpen={!!currentKline}
        onClose={() => setKlineIndex(-1)}
        onNavigatePrev={() => openKline(klineIndex - 1)}
        onNavigateNext={() => openKline(klineIndex + 1)}
        hasPrev={klineIndex > 0}
        hasNext={klineIndex >= 0 && klineIndex < activeItems.length - 1}
        apiHost={API_BASE}
      />
    </div>
  );
}

function BoxTable({ items, onOpen }: { items: BoxItem[]; onOpen: (index: number) => void }) {
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[1520px] grid-cols-[48px_110px_150px_82px_92px_110px_120px_120px_110px_112px_112px_120px_96px] gap-3 border-b border-[#c4c8bc]/30 px-4 py-2 text-xs font-bold text-[#686d68]">
        <span>#</span><span>代码</span><span>名称/日期</span><span>总分</span><span>箱体</span><span>宽度/占比</span><span>漂移/ER</span><span>上沿触碰</span><span>量能预热</span><span>突破放量</span><span>突破幅度</span><span>失败原因</span><span>操作</span>
      </div>
      {items.map((item, index) => (
        <div key={`${item.ts_code}-${item.trade_date}-${item.reject_reason || 'pass'}`} className="grid min-w-[1520px] grid-cols-[48px_110px_150px_82px_92px_110px_120px_120px_110px_112px_112px_120px_96px] gap-3 border-b border-[#c4c8bc]/30 px-4 py-3 text-sm last:border-b-0 hover:bg-black/5">
          <span className="text-xs font-bold text-[#686d68]">{index + 1}</span>
          <button onClick={() => onOpen(index)} className="text-left font-bold text-[#2e3230] underline-offset-2 hover:text-[#4a7c59] hover:underline">{item.ts_code}</button>
          <div className="min-w-0">
            <p className="truncate font-bold text-[#2e3230]">{item.name || '未命名'}</p>
            <p className="text-xs text-[#686d68]">{formatDate(item.trade_date)} {item.industry_l1 ? `· ${item.industry_l1}` : ''}</p>
          </div>
          <div>
            <p className="text-lg font-extrabold text-[#4a7c59]">{item.total_score.toFixed(1)}</p>
            <p className="text-[11px] text-[#686d68]">箱{item.box_score.toFixed(0)} 突{item.breakout_score.toFixed(0)} 量{item.volume_score.toFixed(0)}</p>
          </div>
          <span className="text-[#4a4e4a]">{item.box_window}日<br />{formatDate(item.box_start)}~{formatDate(item.box_end)}</span>
          <span className="font-bold text-[#2e3230]">{formatPct(item.box_width)} / {formatRatio(item.inside_ratio)}</span>
          <span className="text-[#4a4e4a]">{formatRatio(item.drift_ratio)} / {formatRatio(item.efficiency_ratio)}</span>
          <span className="font-bold text-[#2e3230]">{item.upper_touch_count}次 / 跨{formatRatio(item.upper_touch_span)}</span>
          <span className="font-bold text-[#2e3230]">{item.preheat3.toFixed(2)}x / {item.preheat5.toFixed(2)}x</span>
          <span className="font-bold text-[#8f2927]">{item.breakout_volume.toFixed(2)}x</span>
          <span className="font-bold text-[#8f2927]">{formatPct(item.breakout_pct)}</span>
          <span className="truncate font-mono text-xs text-[#705c30]" title={item.reject_reason || ''}>{item.reject_reason || 'PASS'}</span>
          <button onClick={() => onOpen(index)} className="inline-flex items-center justify-center gap-1 rounded-md border border-[#4a7c59] bg-[#4a7c59]/10 px-2 py-1 text-xs font-bold text-[#4a7c59] hover:bg-[#4a7c59]/20">
            <LineChart className="h-3.5 w-3.5" />
            K线
          </button>
        </div>
      ))}
    </div>
  );
}

function PressureTable({ items, onOpen }: { items: PressureItem[]; onOpen: (index: number) => void }) {
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[1280px] grid-cols-[56px_110px_160px_90px_78px_120px_120px_120px_120px_120px_96px] gap-3 border-b border-[#c4c8bc]/30 px-4 py-2 text-xs font-bold text-[#686d68]">
        <span>#</span><span>代码</span><span>名称/日期</span><span>总分</span><span>触碰</span><span>低位</span><span>突破前距离</span><span>预热</span><span>突破放量</span><span>突破幅度</span><span>操作</span>
      </div>
      {items.map((item, index) => (
        <div key={`${item.ts_code}-${item.trade_date}`} className="grid min-w-[1280px] grid-cols-[56px_110px_160px_90px_78px_120px_120px_120px_120px_120px_96px] gap-3 border-b border-[#c4c8bc]/30 px-4 py-3 text-sm last:border-b-0 hover:bg-black/5">
          <span className="text-xs font-bold text-[#686d68]">{index + 1}</span>
          <button onClick={() => onOpen(index)} className="text-left font-bold text-[#2e3230] underline-offset-2 hover:text-[#4a7c59] hover:underline">{item.ts_code}</button>
          <div className="min-w-0">
            <p className="truncate font-bold text-[#2e3230]">{item.name || '未命名'}</p>
            <p className="text-xs text-[#686d68]">{formatDate(item.trade_date)} {item.industry_l1 ? `· ${item.industry_l1}` : ''}</p>
          </div>
          <p className="text-lg font-extrabold text-[#4a7c59]">{item.total_score.toFixed(1)}</p>
          <span className="font-bold text-[#2e3230]">{item.touch_count}</span>
          <span className="text-[#4a4e4a]">{formatPct(item.drawdown_120)} / {formatRatio(item.position_120)}</span>
          <span className={item.pre_break_distance <= 0 ? 'font-bold text-[#4a7c59]' : 'font-bold text-[#705c30]'}>{formatPct(item.pre_break_distance)}</span>
          <span className="font-bold text-[#2e3230]">{item.amount_preheat_5_20.toFixed(2)}x / {item.hot_days_5}日</span>
          <span className="font-bold text-[#8f2927]">{item.breakout_amount_ratio.toFixed(2)}x</span>
          <span className="font-bold text-[#8f2927]">{formatPct(item.breakout_pct)}</span>
          <button onClick={() => onOpen(index)} className="inline-flex items-center justify-center gap-1 rounded-md border border-[#4a7c59] bg-[#4a7c59]/10 px-2 py-1 text-xs font-bold text-[#4a7c59] hover:bg-[#4a7c59]/20">
            <LineChart className="h-3.5 w-3.5" />
            K线
          </button>
        </div>
      ))}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="space-y-1 text-xs font-bold text-[#4a4e4a]"><span>{label}</span>{children}</label>;
}

function Input({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <input value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-md border border-[#c4c8bc] bg-white px-2.5 py-2 text-xs text-[#2e3230] outline-none focus:border-[#4a7c59]" />;
}

function NumberInput({ value, onChange, min, max, step }: { value: number; onChange: (value: number) => void; min?: number; max?: number; step?: number }) {
  return <input type="number" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full rounded-md border border-[#c4c8bc] bg-white px-2.5 py-2 text-xs text-[#2e3230] outline-none focus:border-[#4a7c59]" />;
}

function CheckField({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="flex items-end gap-2 rounded-md bg-[#faf6f0] px-3 py-2 text-xs font-bold text-[#4a4e4a]"><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />剔除 ST</label>;
}

function RunButton({ loading, onClick }: { loading: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} disabled={loading} className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-[#4a7c59] px-4 py-2 text-xs font-bold text-white shadow-xs hover:bg-[#3b6447] disabled:opacity-60">
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
      {loading ? '扫描中' : '开始反查'}
    </button>
  );
}

function ModeButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className={`inline-flex items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-bold ${active ? 'border-[#4a7c59] bg-[#4a7c59] text-white' : 'border-[#c4c8bc]/50 bg-[#f0ece4] text-[#4a4e4a] hover:border-[#4a7c59]/50'}`}>
      {children}
    </button>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[#c4c8bc]/30 bg-[#f0ece4] p-4 shadow-sm">
      <p className="text-xs font-bold text-[#686d68]">{label}</p>
      <p className="mt-1 text-lg font-extrabold text-[#2e3230]">{value}</p>
    </div>
  );
}

function cleanDate(value: string) {
  return value.trim().replaceAll('-', '');
}

function formatDate(value?: string | number) {
  if (!value) return '未知';
  const text = String(value).replaceAll('-', '');
  if (text.length !== 8) return value;
  return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}`;
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '暂无';
  const pct = value * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
}

function formatRatio(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '暂无';
  return `${(value * 100).toFixed(0)}%`;
}
