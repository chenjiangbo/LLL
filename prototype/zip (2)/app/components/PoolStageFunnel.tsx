'use client';
import KLineModal from './KLineModal';

import { useEffect, useState, useCallback, useMemo } from 'react';
import {
  Activity, AlertTriangle, CheckCircle2, ChevronRight,
  Filter, Loader2, PlayCircle, RefreshCw, XCircle, Search, TrendingUp
} from 'lucide-react';

type PoolCode = 'A-Pre' | 'A' | 'B' | 'C';

type FunnelRow = {
  pool_code: string;
  stage: string;
  status: string;
  cnt: number;
};

type ReasonSummary = {
  reason_code: string;
  message: string;
  cnt: number;
};

type ReasonDetail = {
  ts_code: string;
  reason_code: string;
  severity: string;
  actual_value?: number | string;
  threshold_value?: number | string;
  message: string;
};

type StockItem = {
  run_id: string;
  ts_code: string;
  pool_code: string;
  stage: string;
  status: string;
  score?: number | null;
  score_detail_json?: Record<string, unknown>;
  name?: string;
  asset_type?: string;
  industry?: string | null;
  main_business?: string | null;
  market?: string | null;
  l0_reasons?: string[];
  features?: Record<string, any>;
  is_selected?: boolean;
  reasons: ReasonDetail[];
};

type StocksResponse = {
  total: number;
  industry_counts?: Record<string, number>;
  items: StockItem[];
  page: number;
  page_size: number;
};

const STAGE_NAMES: Record<string, string> = {
  L0: 'L0 初始候选',
  L1: 'L1 硬过滤',
  L2: 'L2 质量分',
  L3: 'L3 相对强度',
  L4: 'L4 触发时机',
  L5: 'L5 机会排名',
};

const STAGE_DESCS: Record<string, string> = {
  L0: '常规选股策略初步入池股票',
  L1: '剔除 ST、退市、低成交额及一字涨停',
  L2: '各池结构形态与修复动能二次评分',
  L3: 'RS60 全市场与行业内相对强度过滤',
  L4: '入场动能突破与追高风险隔离',
  L5: '综合质量/强度/时机/行业 Top 排名',
};

const REASON_NAMES: Record<string, string> = {
  L1_NOT_TRADING: '当日无有效交易',
  L1_ST_RISK: 'ST/*ST 风险提示',
  L1_TOO_NEW: '上市天数不足 (120天)',
  L1_LOW_LIQUIDITY: '20日均成交额不足 (3000万)',
  L1_TEMP_LIMITED: '一字涨停不可执行',
  DATA_CORE_MISSING: '核心数据缺失',
  L2_PREMISE_BROKEN: '核心前提结构失效',
  L2_QUALITY_LOW: '质量分低于最低门槛 (45分)',
  L3_STRENGTH_LOW: 'RS60 相对强度低于门槛 (40%)',
  L4_NOT_READY: '触发得分不足 (时机未到)',
  L4_OVEREXTENDED: '偏离均线过多 (追高风险)',
  L4_STRUCTURE_INVALID: '关键支撑破坏 (结构失效)',
  L5_SCORE_LOW: '综合机会得分不足 70分',
};

const API = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL ?? '';

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${url}`, options);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}


function formatScoreDetail(stage: string, detail?: Record<string, any>): string {
  if (!detail) return '';
  if (stage === 'L2') {
    const parts = [];
    if (detail.structure_turn != null) parts.push(`结构转向:${Math.round(detail.structure_turn)}`);
    if (detail.downside_risk != null) parts.push(`风控:${Math.round(detail.downside_risk)}`);
    if (detail.not_extended != null) parts.push(`防延伸:${Math.round(detail.not_extended)}`);
    if (detail.struct != null) parts.push(`结构:${Math.round(detail.struct)}`);
    if (detail.shrink != null) parts.push(`缩量:${Math.round(detail.shrink)}`);
    if (detail.ma_reclaim != null) parts.push(`站均线:${Math.round(detail.ma_reclaim)}`);
    if (detail.breakout != null) parts.push(`突破:${Math.round(detail.breakout)}`);
    if (detail.oversold != null) parts.push(`超跌:${Math.round(detail.oversold)}`);
    if (detail.stabilize != null) parts.push(`企稳:${Math.round(detail.stabilize)}`);
    if (detail.rebound != null) parts.push(`反弹:${Math.round(detail.rebound)}`);
    return parts.join(' + ');
  }
  if (stage === 'L3') {
    const parts = [];
    if (detail.rs60_rank_all_pct != null) parts.push(`RS60全市场前 ${Math.round(detail.rs60_rank_all_pct)}%`);
    if (detail.pct_all != null) parts.push(`全市场:${Math.round(detail.pct_all * 100)}%`);
    if (detail.pct_pool != null) parts.push(`池内:${Math.round(detail.pct_pool * 100)}%`);
    if (detail.pct_industry != null) parts.push(`行业内:${Math.round(detail.pct_industry * 100)}%`);
    return parts.join(' / ');
  }
  if (stage === 'L4') {
    const parts = [];
    if (detail.trigger_score != null) parts.push(`触发分:${Math.round(detail.trigger_score)}`);
    if (detail.atr_dist != null) parts.push(`偏离:${detail.atr_dist}ATR`);
    if (detail.is_overextended) parts.push(`⚠️已追高过伸`);
    return parts.join(' | ');
  }
  if (stage === 'L5') {
    const parts = [];
    if (detail.l2_quality_part != null) parts.push(`L2:${Math.round(detail.l2_quality_part)}`);
    if (detail.l3_rs_part != null) parts.push(`L3:${Math.round(detail.l3_rs_part)}`);
    if (detail.l4_trigger_part != null) parts.push(`L4:${Math.round(detail.l4_trigger_part)}`);
    return parts.join(' + ');
  }
  return '';
}

function formatMv(mv: any): string {
  if (typeof mv !== 'number' || !Number.isFinite(mv) || mv <= 0) return '';
  if (mv >= 10000) return `${(mv / 10000).toFixed(1)}万亿`;
  return `${mv.toFixed(0)}亿`;
}

export default function PoolStageFunnel({
  activePool,
  onOpenKline,
  onToggleSelect,
}: {
  activePool: PoolCode;
  onOpenKline?: (tsCode: string, name: string) => void;
  onToggleSelect?: (tsCode: string) => void;
}) {

  const [runId, setRunId] = useState<string | null>(null);
  const [tradeDate, setTradeDate] = useState<string | null>(null);
  const [funnel, setFunnel] = useState<FunnelRow[]>([]);
  const [loadingRun, setLoadingRun] = useState(true);
  const [runError, setRunError] = useState<string | null>(null);

  // Active filter state
  const [activeStage, setActiveStage] = useState<string>('L1');
  const [viewStatus, setViewStatus] = useState<'ALL' | 'PASS' | 'FAIL'>('FAIL');
  const [selectedReasonCode, setSelectedReasonCode] = useState<string | null>(null);

  // Reasons summary & Stock list
  const [reasonsSummary, setReasonsSummary] = useState<ReasonSummary[]>([]);
  const [stocksData, setStocksData] = useState<StocksResponse | null>(null);
  const [loadingStocks, setLoadingStocks] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedIndustry, setSelectedIndustry] = useState('ALL');
  const [industrySearchQuery, setIndustrySearchQuery] = useState('');
  const [showIndustryDropdown, setShowIndustryDropdown] = useState(false);
  const [industryShowCount, setIndustryShowCount] = useState(20);
  const [focusedIndex, setFocusedIndex] = useState(0);
  const [page, setPage] = useState(1);
  const [klineIndex, setKlineIndex] = useState<number | null>(null);

  // Load latest run info & funnel
  const loadLatestRun = useCallback(async () => {
    setLoadingRun(true);
    setRunError(null);
    try {
      const runInfo = await fetchJson<{ run_id: string; trade_date: string; status: string }>(
        '/api/screening/runs/latest'
      );
      setRunId(runInfo.run_id);
      setTradeDate(runInfo.trade_date);

      const funnelRes = await fetchJson<{ funnel: FunnelRow[] }>(
        `/api/screening/runs/${runInfo.run_id}/funnel`
      );
      setFunnel(funnelRes.funnel);
    } catch (e: unknown) {
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingRun(false);
    }
  }, []);

  useEffect(() => {
    loadLatestRun();
  }, [loadLatestRun]);

  // Load reasons summary when stage or pool changes
  const loadReasonsSummary = useCallback(async () => {
    if (!runId || activeStage === 'L0') {
      setReasonsSummary([]);
      return;
    }
    try {
      const res = await fetchJson<{ reasons: ReasonSummary[] }>(
        `/api/screening/runs/${runId}/pools/${activePool}/stages/${activeStage}/reasons`
      );
      setReasonsSummary(res.reasons || []);
    } catch {
      setReasonsSummary([]);
    }
  }, [runId, activePool, activeStage]);

  useEffect(() => {
    loadReasonsSummary();
  }, [loadReasonsSummary]);

  // Load drilldown stocks when filters change
  const loadStocks = useCallback(async () => {
    if (!runId) return;
    setLoadingStocks(true);
    try {
      const params = new URLSearchParams();
      if (viewStatus !== 'ALL') {
        params.set('status', viewStatus);
      }
      if (selectedReasonCode && viewStatus === 'FAIL') {
        params.set('reason_code', selectedReasonCode);
      }
      if (selectedIndustry !== 'ALL') {
        params.set('industry', selectedIndustry);
      }
      params.set('page', String(page));
      params.set('page_size', '50');

      const data = await fetchJson<StocksResponse>(
        `/api/screening/runs/${runId}/pools/${activePool}/stages/${activeStage}/stocks?${params.toString()}`
      );
      setStocksData(data);
    } catch {
      setStocksData(null);
    } finally {
      setLoadingStocks(false);
    }
  }, [runId, activePool, activeStage, viewStatus, selectedReasonCode, selectedIndustry, page]);

  useEffect(() => {
    loadStocks();
  }, [loadStocks]);

  // Handle stage change
  const handleSelectStage = (stage: string, defaultStatus: 'ALL' | 'PASS' | 'FAIL' = 'FAIL') => {
    setActiveStage(stage);
    setViewStatus(defaultStatus);
    setSelectedReasonCode(null);
    setSelectedIndustry('ALL');
    setPage(1);
  };

  // Helper counts for active pool
  const getStageCounts = (stage: string) => {
    const rows = funnel.filter((r) => r.pool_code === activePool && r.stage === stage);
    const pass = rows.filter((r) => r.status === 'PASS').reduce((s, r) => s + r.cnt, 0);
    const fail = rows.filter((r) => r.status !== 'PASS' && r.status !== 'NOT_EVALUATED').reduce((s, r) => s + r.cnt, 0);
    return { pass, fail, total: pass + fail };
  };

  const l0Pass = getStageCounts('L0').pass;

    const rawItems = stocksData?.items || [];
  const industryCounts = useMemo(() => {
    return stocksData?.industry_counts || {};
  }, [stocksData]);

  const totalIndustryCount = useMemo(() => {
    if (stocksData?.industry_counts && Object.keys(stocksData.industry_counts).length > 0) {
      return Object.values(stocksData.industry_counts).reduce((s, n) => s + n, 0);
    }
    return stocksData?.total || 0;
  }, [stocksData]);

  const sortedIndustries = useMemo(() => {
    return Object.entries(industryCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ name, count }));
  }, [industryCounts]);

  const topIndustries = useMemo(() => {
    return sortedIndustries.slice(0, industryShowCount);
  }, [sortedIndustries, industryShowCount]);

  const allIndustries = useMemo(() => {
    return Object.keys(industryCounts).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  }, [industryCounts]);

  const filteredIndustriesForSearch = useMemo(() => {
    if (!industrySearchQuery.trim()) return allIndustries;
    return allIndustries.filter((ind) => ind.toLowerCase().includes(industrySearchQuery.toLowerCase().trim()));
  }, [allIndustries, industrySearchQuery]);

  const filteredItems = rawItems.filter((item) => {
    if (selectedIndustry !== 'ALL' && (item.industry || '未分类') !== selectedIndustry) {
      return false;
    }
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase().trim();
    return (
      item.ts_code.toLowerCase().includes(q) ||
      (item.name && item.name.toLowerCase().includes(q)) ||
      (item.industry && item.industry.toLowerCase().includes(q)) ||
      (item.main_business && item.main_business.toLowerCase().includes(q))
    );
  });

  if (loadingRun) {
    return (
      <div className="my-4 flex items-center justify-center gap-2 rounded-xl border border-[#c4c8bc]/40 bg-white/40 p-6 text-sm text-[#686d68]">
        <Loader2 className="h-4 w-4 animate-spin text-[#4a7c59]" />
        加载二次筛选数据...
      </div>
    );
  }

  if (runError || !runId) {
    return (
      <div className="my-4 rounded-xl border border-[#c4c8bc]/40 bg-white/50 p-4 text-xs text-[#686d68]">
        <span>暂无针对交易日的二次筛选记录。请运行一次选股后查看。</span>
        <button
          onClick={loadLatestRun}
          className="ml-3 font-bold text-[#4a7c59] hover:underline"
        >
          刷新
        </button>
      </div>
    );
  }

  return (
    <div className="my-5 rounded-2xl border border-[#c4c8bc]/60 bg-[#fbf9f5] p-5 shadow-xs transition">
      {/* Header bar */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-[#c4c8bc]/30 pb-3">
        <div className="flex items-center gap-2">
          <span className="rounded-md bg-[#2e3230] px-2.5 py-1 text-xs font-bold text-white">
            {activePool} 池过滤链
          </span>
          <span className="text-xs text-[#686d68]">
            运行 ID: <code className="font-mono text-[#2e3230]">{runId}</code> ({tradeDate})
          </span>
        </div>
        <button
          onClick={loadLatestRun}
          className="inline-flex items-center gap-1 text-xs font-bold text-[#4a7c59] hover:text-[#2e3230]"
        >
          <RefreshCw className="h-3.5 w-3.5" /> 刷新状态
        </button>
      </div>

      {/* Stage pipeline tabs */}
      <div className="mb-5 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {['L0', 'L1', 'L2', 'L3', 'L4', 'L5'].map((stage) => {
          const { pass, fail } = getStageCounts(stage);
          const isSelected = activeStage === stage;
          const passRate = l0Pass > 0 ? Math.round((pass / l0Pass) * 100) : 0;

          return (
            <div
              key={stage}
              onClick={() => handleSelectStage(stage, stage === 'L0' ? 'PASS' : 'FAIL')}
              className={`group relative cursor-pointer rounded-xl border p-3.5 transition ${
                isSelected
                  ? 'border-[#4a7c59] bg-white shadow-md ring-2 ring-[#4a7c59]/20'
                  : 'border-[#c4c8bc]/50 bg-white/60 hover:border-[#4a7c59]/50 hover:bg-white'
              }`}
            >
              <div className="mb-1.5 flex items-center justify-between">
                <span className={`text-xs font-bold ${isSelected ? 'text-[#4a7c59]' : 'text-[#2e3230]'}`}>
                  {STAGE_NAMES[stage]}
                </span>
                <span className="text-[11px] font-medium text-[#686d68]">{passRate}% 留存</span>
              </div>
              <p className="mb-3 text-[11px] text-[#686d68] line-clamp-1">{STAGE_DESCS[stage]}</p>

              <div className="flex items-center justify-between border-t border-[#c4c8bc]/20 pt-2 text-xs">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleSelectStage(stage, 'PASS');
                  }}
                  className={`font-bold transition hover:underline ${
                    isSelected && viewStatus === 'PASS' ? 'text-[#4a7c59]' : 'text-[#4a4e4a]'
                  }`}
                >
                  通过: <span className="text-[#4a7c59]">{pass}</span> 只
                </button>
                {stage !== 'L0' && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleSelectStage(stage, 'FAIL');
                    }}
                    className={`font-bold transition hover:underline ${
                      isSelected && viewStatus === 'FAIL' ? 'text-[#8f2927]' : 'text-[#686d68]'
                    }`}
                  >
                    淘汰: <span className="text-[#8f2927]">{fail}</span> 只
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Stage detail filter & Reasons cards - Merged into 1 single line */}
      <div className="rounded-xl border border-[#c4c8bc]/40 bg-white p-4">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-[#c4c8bc]/30 pb-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-bold text-[#2e3230]">
              {STAGE_NAMES[activeStage]}
            </span>

            {/* Instant Search Input */}
            <div className="flex items-center gap-1 bg-[#faf6f0] px-2.5 py-1 rounded-md border border-[#c4c8bc]/50 text-xs">
              <Search className="w-3.5 h-3.5 text-[#686d68]" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="即时搜索代码、名称、行业、主营..."
                className="w-48 text-xs bg-transparent outline-none text-[#2e3230]"
              />
              {searchQuery && (
                <button onClick={() => setSearchQuery('')} className="p-0.5 text-slate-400 hover:text-slate-700">
                  <XCircle className="w-3 h-3" />
                </button>
              )}
            </div>

            {/* View Status Toggle */}
            <div className="flex rounded-lg bg-[#e4e0d8] p-0.5 font-bold">
              <button
                onClick={() => {
                  setViewStatus('FAIL');
                  setSelectedReasonCode(null);
                  setSelectedIndustry('ALL');
                  setPage(1);
                }}
                className={`rounded-md px-2.5 py-1 transition ${
                  viewStatus === 'FAIL' ? 'bg-[#8f2927] text-white' : 'text-[#4a4e4a] hover:text-[#2e3230]'
                }`}
              >
                🚫 淘汰 ({getStageCounts(activeStage).fail})
              </button>
              <button
                onClick={() => {
                  setViewStatus('PASS');
                  setSelectedReasonCode(null);
                  setSelectedIndustry('ALL');
                  setPage(1);
                }}
                className={`rounded-md px-2.5 py-1 transition ${
                  viewStatus === 'PASS' ? 'bg-[#4a7c59] text-white' : 'text-[#4a4e4a] hover:text-[#2e3230]'
                }`}
              >
                ✅ 通过 ({getStageCounts(activeStage).pass})
              </button>
              <button
                onClick={() => {
                  setViewStatus('ALL');
                  setSelectedReasonCode(null);
                  setSelectedIndustry('ALL');
                  setPage(1);
                }}
                className={`rounded-md px-2.5 py-1 transition ${
                  viewStatus === 'ALL' ? 'bg-[#2e3230] text-white' : 'text-[#4a4e4a] hover:text-[#2e3230]'
                }`}
              >
                全量
              </button>
            </div>

            {/* Inlined Reason Category Cards (Same Row!) */}
            {viewStatus === 'FAIL' && activeStage !== 'L0' && reasonsSummary.length > 0 && (
              <>
                <span className="text-[#c4c8bc]">|</span>
                {reasonsSummary.map((reason) => {
                  const isSelected = selectedReasonCode === reason.reason_code;
                  const displayName = REASON_NAMES[reason.reason_code] || reason.reason_code;
                  return (
                    <button
                      key={reason.reason_code}
                      onClick={() => {
                        setSelectedReasonCode(isSelected ? null : reason.reason_code);
                        setPage(1);
                      }}
                      className={`rounded-md px-2.5 py-1 font-bold transition ${
                        isSelected
                          ? 'bg-[#8f2927] text-white shadow-xs'
                          : 'bg-[#faf6f0] text-[#4a4e4a] hover:border-[#8f2927]/40 hover:bg-[#e4e0d8] border border-[#c4c8bc]/50'
                      }`}
                    >
                      <span>{displayName}</span>
                      <span className="ml-1.5 rounded-full bg-black/10 px-1 py-0.5 text-[10px]">
                        {reason.cnt}只
                      </span>
                    </button>
                  );
                })}
              </>
            )}
          </div>

          <span className="text-[#686d68] text-[11px]">
            共 {stocksData?.total || 0} 只匹配股票
          </span>
        </div>


                {/* 行业筛选与统计 Pills 栏 */}
        <div className="mb-4 bg-[#f0ece4]/70 p-2.5 rounded-lg border border-[#c4c8bc]/40">
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="font-bold text-[#686d68] mr-1">行业筛选:</span>
            <button
              onClick={() => setSelectedIndustry('ALL')}
              className={`px-2.5 py-1 font-bold rounded-md transition ${
                selectedIndustry === 'ALL'
                  ? 'bg-[#4a7c59] text-white shadow-xs'
                  : 'bg-white text-[#4a4e4a] hover:bg-[#e4e0d8] border border-[#c4c8bc]/40'
              }`}
            >
              全部 ({totalIndustryCount})
            </button>
            {topIndustries.map((ind) => (
              <button
                key={ind.name}
                onClick={() => setSelectedIndustry(ind.name)}
                className={`px-2.5 py-1 font-bold rounded-md transition ${
                  selectedIndustry === ind.name
                    ? 'bg-[#4a7c59] text-white shadow-xs'
                    : 'bg-white text-[#4a4e4a] hover:bg-[#e4e0d8] border border-[#c4c8bc]/40'
                }`}
              >
                {ind.name} ({ind.count})
              </button>
            ))}
            {industryShowCount < sortedIndustries.length && (
              <button
                onClick={() => setIndustryShowCount((c) => Math.min(c + 20, sortedIndustries.length))}
                className="px-2 py-1 font-bold rounded-md border border-dashed border-[#4a7c59]/60 text-[#4a7c59] hover:bg-[#4a7c59]/10 transition"
              >
                更多 (+{Math.min(20, sortedIndustries.length - industryShowCount)})
              </button>
            )}
            {industryShowCount > 20 && (
              <button
                onClick={() => setIndustryShowCount(20)}
                className="px-2 py-1 font-bold rounded-md border border-dashed border-[#686d68]/50 text-[#686d68] hover:bg-[#686d68]/10 transition"
              >
                收起
              </button>
            )}

            {/* 搜索行业 Combobox */}
            <div className="relative ml-auto">
              <button
                onClick={() => setShowIndustryDropdown(!showIndustryDropdown)}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 font-bold bg-white border border-[#c4c8bc]/60 rounded-md text-[#2e3230] hover:bg-slate-50 transition shadow-xs"
              >
                <Filter className="w-3.5 h-3.5 text-[#4a7c59]" />
                <span>{selectedIndustry === 'ALL' ? '搜索子行业' : `已选: ${selectedIndustry}`}</span>
              </button>

              {showIndustryDropdown && (
                <div className="absolute right-0 top-8 z-30 w-64 p-2 bg-white rounded-lg shadow-xl border border-[#c4c8bc]/60 space-y-2">
                  <div className="flex items-center gap-1 bg-[#faf6f0] px-2 py-1.5 rounded border border-[#c4c8bc]/40">
                    <Search className="w-3.5 h-3.5 text-[#686d68]" />
                    <input
                      type="text"
                      value={industrySearchQuery}
                      onChange={(e) => setIndustrySearchQuery(e.target.value)}
                      placeholder="输入行业打字搜索..."
                      className="w-full text-xs bg-transparent outline-none text-[#2e3230]"
                    />
                  </div>
                  <div className="max-h-56 overflow-y-auto space-y-0.5 pr-1">
                    <button
                      onClick={() => {
                        setSelectedIndustry('ALL');
                        setShowIndustryDropdown(false);
                      }}
                      className={`w-full text-left px-2.5 py-1.5 text-xs rounded transition flex items-center justify-between ${
                        selectedIndustry === 'ALL' ? 'bg-[#4a7c59]/10 font-bold text-[#4a7c59]' : 'hover:bg-slate-100 text-[#4a4e4a]'
                      }`}
                    >
                      <span>全部分类</span>
                      <span className="text-[11px] text-[#686d68]">({totalIndustryCount})</span>
                    </button>
                    {filteredIndustriesForSearch.map((indName) => (
                      <button
                        key={indName}
                        onClick={() => {
                          setSelectedIndustry(indName);
                          setShowIndustryDropdown(false);
                        }}
                        className={`w-full text-left px-2.5 py-1.5 text-xs rounded transition flex items-center justify-between ${
                          selectedIndustry === indName ? 'bg-[#4a7c59]/10 font-bold text-[#4a7c59]' : 'hover:bg-slate-100 text-[#4a4e4a]'
                        }`}
                      >
                        <span className="truncate">{indName}</span>
                        <span className="text-[11px] text-[#686d68] font-semibold">({industryCounts[indName]})</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Drilldown stocks table */}
        {loadingStocks ? (
          <div className="py-8 flex justify-center items-center gap-2 text-xs text-[#686d68]">
            <Loader2 className="h-4 w-4 animate-spin text-[#4a7c59]" />
            读取股票列表中...
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="py-8 text-center text-xs text-[#686d68]">
            当前筛选条件下无股票记录。
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-[#c4c8bc]/40 bg-[#f7f5f0] text-[#686d68]">
                  <th className="py-2.5 px-3 font-bold w-24">代码</th>
                  <th className="py-2.5 px-3 font-bold w-72">名称 / 行业 / 主营业务</th>
                  
                  <th className="py-2.5 px-3 font-bold w-48">得分 & 算子拆解</th>
                  <th className="py-2.5 px-3 font-bold w-44">行情 & 核心因子</th>
                  <th className="py-2.5 px-3 font-bold">选股逻辑 / 淘汰原因</th>
                  <th className="py-2.5 px-3 font-bold text-center w-24">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#c4c8bc]/20">
                {filteredItems.map((stock, idx) => {
                  const numScore = stock.score != null && !isNaN(Number(stock.score)) ? Number(stock.score) : null;
                  const f = stock.features || {};
                  const closePrice = typeof f.close === 'number' ? f.close : null;
                  const pctChg = typeof f.pct_chg === 'number' ? f.pct_chg : null;
                  const amountMa20 = typeof f.amount_ma20 === 'number' ? f.amount_ma20 : null;
                  const pe = typeof f.pe === 'number' ? f.pe : null;
                  const pb = typeof f.pb === 'number' ? f.pb : null;
                  const turnover = typeof f.turnover_rate === 'number' ? f.turnover_rate : null;
                  const volRatio = typeof f.volume_ratio === 'number' ? f.volume_ratio : null;
                  const mvStr = formatMv(f.total_mv);
                  const detailText = formatScoreDetail(activeStage, stock.score_detail_json);

                  return (
                    <tr
                      key={stock.ts_code}
                      onDoubleClick={() => setKlineIndex(idx)}
                      className="hover:bg-[#f7f5f0]/70 transition group cursor-pointer"
                    >
                      {/* 代码 */}
                      <td
                        onClick={() => setKlineIndex(idx)}
                        className="py-2.5 px-3 font-mono font-bold text-[#2e3230] group-hover:text-[#4a7c59] underline-offset-2 group-hover:underline"
                        title="双击或点击查看 K 线"
                      >
                        {stock.ts_code}
                      </td>

                      {/* 名称 / 行业 / 主营业务 */}
                      <td
                        onClick={() => setKlineIndex(idx)}
                        className="py-2.5 px-3 space-y-1"
                        title={stock.main_business ? `主营业务: ${stock.main_business}` : '点击查看 K 线'}
                      >
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="font-bold text-[#2e3230] group-hover:text-[#4a7c59]">{stock.name || '未命名'}</span>
                          {stock.industry && (
                            <span className="rounded bg-[#4a7c59]/10 px-1.5 py-0.5 text-[10px] font-bold text-[#4a7c59]">
                              {stock.industry}
                            </span>
                          )}
                          {stock.market && stock.market !== '主板' && (
                            <span className="rounded bg-[#2e3230]/10 px-1 py-0.5 text-[10px] font-bold text-[#2e3230]">
                              {stock.market}
                            </span>
                          )}
                        </div>
                        {stock.main_business ? (
                          <p className="line-clamp-2 text-[11px] text-[#4a4e4a] leading-relaxed bg-[#f7f5f0] p-1 rounded border border-[#c4c8bc]/30">
                            <span className="font-bold text-[#686d68] mr-1">主营:</span>
                            {stock.main_business}
                          </p>
                        ) : (
                          <p className="text-[10px] text-[#686d68] italic">暂无主营业务简介</p>
                        )}
                      </td>



                      {/* 得分 & 算子拆解 */}
                      <td className="py-2.5 px-3">
                        {numScore != null ? (
                          <div>
                            <span className="font-bold text-[#2e3230] text-sm">{numScore.toFixed(1)}分</span>
                            {detailText && (
                              <p className="text-[10px] text-[#705c30] mt-0.5 font-medium">{detailText}</p>
                            )}
                          </div>
                        ) : (
                          <span className="text-[#686d68]">—</span>
                        )}
                      </td>

                      {/* 行情 & 核心因子 */}
                      <td className="py-2.5 px-3 space-y-0.5">
                        {closePrice !== null && (
                          <p className="font-bold text-[#2e3230]">
                            {closePrice.toFixed(2)}元
                            {pctChg !== null && (
                              <span className={`ml-1 text-[11px] ${pctChg >= 0 ? 'text-[#8f2927]' : 'text-[#4a7c59]'}`}>
                                {pctChg >= 0 ? '+' : ''}{pctChg.toFixed(2)}%
                              </span>
                            )}
                          </p>
                        )}
                        <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-[#686d68]">
                          {amountMa20 !== null && amountMa20 > 0 && <span>均额: {formatMv(amountMa20)}</span>}
                          {mvStr && <span className="text-[#705c30]">市值: {mvStr}</span>}
                          {pe !== null && pe > 0 && <span>PE: {pe.toFixed(1)}</span>}
                          {pb !== null && pb > 0 && <span>PB: {pb.toFixed(1)}</span>}
                          {turnover !== null && <span>换手: {turnover.toFixed(1)}%</span>}
                        </div>
                      </td>

                      {/* 选股逻辑 / 淘汰原因 */}
                      <td className="py-2.5 px-3">
                        {stock.reasons && stock.reasons.length > 0 ? (
                          <div className="space-y-1">
                            {stock.reasons.map((r, i) => (
                              <div key={i} className="flex flex-wrap items-center gap-1.5 text-[11px]">
                                <span className="rounded bg-[#8f2927]/10 px-1.5 py-0.5 font-mono font-bold text-[#8f2927]">
                                  {REASON_NAMES[r.reason_code] || r.reason_code}
                                </span>
                                <span className="text-[#4a4e4a]">{r.message}</span>
                              </div>
                            ))}
                          </div>
                        ) : stock.l0_reasons && stock.l0_reasons.length > 0 ? (
                          <div className="text-[11px] text-[#4a4e4a] leading-relaxed">
                            <span className="font-bold text-[#4a7c59]">入池逻辑: </span>
                            {stock.l0_reasons.join('；')}
                          </div>
                        ) : (
                          <span className="text-[#4a7c59] text-[11px]">符合该层过滤条件</span>
                        )}
                      </td>

                      {/* 操作列 */}
                      <td className="py-2.5 px-3 text-center">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            if (onToggleSelect) onToggleSelect(stock.ts_code);
                          }}
                          className={`rounded-md px-2 py-1 text-xs font-bold transition ${
                            stock.is_selected
                              ? 'bg-[#705c30] text-white hover:bg-[#5a4a27]'
                              : 'border border-[#4a7c59] text-[#4a7c59] hover:bg-[#4a7c59]/10'
                          }`}
                        >
                          {stock.is_selected ? '已选' : '+入池'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {stocksData && stocksData.total > 20 && (
          <div className="mt-4 flex items-center justify-between border-t border-[#c4c8bc]/20 pt-3 text-xs">
            <span className="text-[#686d68]">
              第 {page} 页，共 {Math.ceil(stocksData.total / 20)} 页
            </span>
            <div className="flex gap-1">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="rounded-md border border-[#c4c8bc]/50 bg-white px-2.5 py-1 font-bold disabled:opacity-40"
              >
                上一页
              </button>
              <button
                disabled={page >= Math.ceil(stocksData.total / 20)}
                onClick={() => setPage((p) => p + 1)}
                className="rounded-md border border-[#c4c8bc]/50 bg-white px-2.5 py-1 font-bold disabled:opacity-40"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>
      {/* K线弹窗：绑死当前过滤后的 filteredItems 顺序！ */}
      {klineIndex !== null && filteredItems[klineIndex] && (
        <KLineModal
          assetCode={filteredItems[klineIndex].ts_code}
          assetName={filteredItems[klineIndex].name || filteredItems[klineIndex].ts_code}
          apiHost={process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL || 'http://127.0.0.1:18080'}
          isOpen={klineIndex !== null}
          onClose={() => setKlineIndex(null)}
          hasPrev={klineIndex > 0}
          hasNext={klineIndex < filteredItems.length - 1}
          onNavigatePrev={() => setKlineIndex((i) => (i !== null ? Math.max(0, i - 1) : null))}
          onNavigateNext={() => setKlineIndex((i) => (i !== null ? Math.min(filteredItems.length - 1, i + 1) : null))}
          isSelected={filteredItems[klineIndex].is_selected}
          onToggleSelect={() => {
            if (onToggleSelect) onToggleSelect(filteredItems[klineIndex].ts_code);
          }}
        />
      )}
    </div>
  );
}
