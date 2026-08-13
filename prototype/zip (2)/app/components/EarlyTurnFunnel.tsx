'use client';

import React, { useEffect, useState, useCallback, useMemo } from 'react';
import {
  PlayCircle,
  Search,
  Filter,
  Layers,
  TrendingUp,
  Activity,
  CheckCircle2,
  AlertTriangle,
  Clock,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Calendar,
  Database,
  BarChart2,
  Target,
  Sparkles,
} from 'lucide-react';
import KLineModal from './KLineModal';

type EarlyTurnState = 'ALL' | 'EARLY_TURN_STRICT' | 'EARLY_TURN' | 'PRE_READY_STRICT' | 'PRE_READY' | 'WATCH' | 'TOO_LATE' | 'NO_SIGNAL';
type BackgroundType = 'ALL' | 'REVERSAL_BASE' | 'CONSOLIDATION_RESTART' | 'UNKNOWN';

interface EarlyTurnStockItem {
  run_id: string;
  ts_code: string;
  trade_date: string;
  name?: string;
  industry?: string;
  main_business?: string;
  total_score: number;
  state: EarlyTurnState;
  background_type: BackgroundType;
  selected: boolean;
  is_overextended: boolean;
  first_selected_date?: string;
  features_json?: Record<string, any>;
  score_detail_json?: Record<string, any>;
  reasons_json?: Array<{ type: string; msg: string }>;
}

interface EarlyTurnResponse {
  total: number;
  counts: Record<string, number>;
  industry_counts?: Record<string, number>;
  items: EarlyTurnStockItem[];
  page: number;
  page_size: number;
}

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL || 'http://127.0.0.1:18080';

export default function EarlyTurnFunnel({
  onOpenSampleValidation,
}: {
  onOpenSampleValidation?: () => void;
}) {
  const [tradeDate, setTradeDate] = useState<string>('20260806');
  const [runId, setRunId] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loadingRun, setLoadingRun] = useState(false);
  const [runningTask, setRunningTask] = useState(false);

  // Filters
  const [activeState, setActiveState] = useState<EarlyTurnState>('ALL');
  const [activeBg, setActiveBg] = useState<BackgroundType>('ALL');
  const [selectedIndustry, setSelectedIndustry] = useState<string>('ALL');
  const [industryShowCount, setIndustryShowCount] = useState<number>(8);
  const [industrySearchQuery, setIndustrySearchQuery] = useState<string>('');
  const [showIndustryDropdown, setShowIndustryDropdown] = useState<boolean>(false);
  const [minScore, setMinScore] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Pagination & List data
  const [data, setData] = useState<EarlyTurnResponse | null>(null);
  const [loadingStocks, setLoadingStocks] = useState(false);
  const [page, setPage] = useState(1);

  // Selected Stock for Sidebar/KLine
  const [selectedStockIndex, setSelectedStockIndex] = useState<number | null>(null);
  const [targetStockCode, setTargetStockCode] = useState<string>('');
  const [singleStockResult, setSingleStockResult] = useState<any | null>(null);
  const [evaluatingSingle, setEvaluatingSingle] = useState(false);
  const [showDetailSidebar, setShowDetailSidebar] = useState(false);

  // 1. Fetch latest run info
  const loadLatestRun = useCallback(async (targetDate?: string) => {
    setLoadingRun(true);
    try {
      const url = targetDate
        ? `${API_BASE}/api/early-turn/latest?trade_date=${targetDate}`
        : `${API_BASE}/api/early-turn/latest`;
      const res = await fetch(url);
      if (res.ok) {
        const runInfo = await res.json();
        if (runInfo.trade_date) setTradeDate(runInfo.trade_date);
        if (runInfo.run_id) setRunId(runInfo.run_id);
        if (runInfo.summary_json?.counts) setCounts(runInfo.summary_json.counts);
      }
    } catch (e) {
      console.error('Failed to load latest early turn run:', e);
    } finally {
      setLoadingRun(false);
    }
  }, []);

  useEffect(() => {
    loadLatestRun();
  }, [loadLatestRun]);

  // 2. Fetch stock list drilldown
  const loadStocks = useCallback(async () => {
    if (!runId) return;
    setLoadingStocks(true);
    try {
      const params = new URLSearchParams();
      if (activeState !== 'ALL') params.set('state', activeState);
      if (activeBg !== 'ALL') params.set('bg_type', activeBg);
      if (minScore.trim()) params.set('min_score', minScore.trim());
      if (searchQuery.trim()) params.set('q', searchQuery.trim());
      if (selectedIndustry !== 'ALL') params.set('industry', selectedIndustry);
      params.set('page', String(page));
      params.set('page_size', '50');

      const res = await fetch(`${API_BASE}/api/early-turn/runs/${runId}/stocks?${params.toString()}`);
      if (res.ok) {
        const json: EarlyTurnResponse = await res.json();
        setData(json);
        if (json.counts) setCounts(json.counts);
      }
    } catch (e) {
      console.error('Failed to fetch early turn stocks:', e);
    } finally {
      setLoadingStocks(false);
    }
  }, [runId, activeState, activeBg, minScore, searchQuery, selectedIndustry, page]);

  useEffect(() => {
    loadStocks();
  }, [loadStocks]);

  // 3. Trigger new calculation
    const handleSingleStockEval = async () => {
    if (!targetStockCode.trim()) return;
    setEvaluatingSingle(true);
    try {
      const res = await fetch(`${API_BASE}/api/early-turn/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trade_date: tradeDate, ts_code: targetStockCode.trim() }),
      });
      if (res.ok) {
        const json = await res.json();
        if (json.summary?.items && json.summary.items.length > 0) {
          setSingleStockResult(json.summary.items[0]);
        }
      }
    } catch (e) {
      console.error('Single stock eval failed:', e);
    } finally {
      setEvaluatingSingle(false);
    }
  };

  const handleTriggerRun = async () => {
    setRunningTask(true);
    try {
      const res = await fetch(`${API_BASE}/api/early-turn/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trade_date: tradeDate }),
      });
      if (res.ok) {
        await loadLatestRun(tradeDate);
      }
    } catch (e) {
      console.error('Trigger run failed:', e);
    } finally {
      setRunningTask(false);
    }
  };

  const industryCounts = useMemo(() => {
    return data?.industry_counts || {};
  }, [data]);

  const totalIndustryCount = useMemo(() => {
    if (data?.industry_counts && Object.keys(data.industry_counts).length > 0) {
      return Object.values(data.industry_counts).reduce((s, n) => s + n, 0);
    }
    return data?.total || 0;
  }, [data]);

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

  const currentItems = data?.items || [];
  const selectedStock = selectedStockIndex !== null ? currentItems[selectedStockIndex] : null;

  return (
    <div className="space-y-4">
      {/* 顶栏 1: 评估控制 + 交易日切换 + 样本回归入口 */}
      <div className="bg-white/80 p-4 rounded-xl border border-[#c4c8bc]/60 shadow-xs flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 bg-[#faf6f0] px-3 py-1.5 rounded-lg border border-[#c4c8bc]/50 text-xs">
            <Calendar className="h-4 w-4 text-[#4a7c59]" />
            <span className="font-bold text-[#2e3230]">评估交易日:</span>
            <input
              type="date"
              value={tradeDate.length === 8 ? `${tradeDate.slice(0, 4)}-${tradeDate.slice(4, 6)}-${tradeDate.slice(6, 8)}` : tradeDate}
              onChange={(e) => {
                const val = e.target.value.replace(/-/g, '');
                setTradeDate(val);
              }}
              className="bg-white border border-[#c4c8bc]/60 px-2 py-0.5 rounded font-mono font-bold outline-none text-[#2e3230]"
            />
          </div>

          <div className="flex items-center gap-1.5 bg-[#faf6f0] px-3 py-1.5 rounded-lg border border-[#c4c8bc]/50 text-xs">
            <Target className="h-4 w-4 text-[#705c30]" />
            <span className="font-bold text-[#2e3230]">单股测试:</span>
            <input
              type="text"
              value={targetStockCode}
              onChange={(e) => setTargetStockCode(e.target.value)}
              placeholder="如 600683"
              className="w-24 bg-white border border-[#c4c8bc]/60 px-2 py-0.5 rounded font-mono font-bold outline-none text-[#2e3230]"
            />
            <button
              onClick={handleSingleStockEval}
              disabled={evaluatingSingle || !targetStockCode.trim()}
              className="px-2.5 py-0.5 bg-[#705c30] hover:bg-[#5a4a27] text-white font-bold rounded shadow-xs transition disabled:opacity-40"
            >
              {evaluatingSingle ? '计算中...' : '测试单股'}
            </button>
          </div>

          <button
            onClick={handleTriggerRun}
            disabled={runningTask}
            className="inline-flex items-center gap-1.5 bg-[#4a7c59] hover:bg-[#3b6447] text-white px-4 py-1.5 rounded-lg font-bold text-xs shadow-xs transition disabled:opacity-50"
          >
            {runningTask ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
            <span>{runningTask ? '算法计算中...' : '运行 Early Turn 评估'}</span>
          </button>

          {runId && (
            <span className="text-[11px] font-mono text-[#686d68] bg-[#f0ece4] px-2 py-1 rounded">
              RunID: {runId}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {onOpenSampleValidation && (
            <button
              onClick={onOpenSampleValidation}
              className="inline-flex items-center gap-1.5 bg-[#705c30] hover:bg-[#5a4a27] text-white px-3.5 py-1.5 rounded-lg font-bold text-xs shadow-xs transition"
            >
              <Target className="h-4 w-4" />
              <span>🎯 正负样本回归校验看板</span>
            </button>
          )}
        </div>
      </div>

      
      {/* 单股评估结果卡片 (如果用户触发了单股定向测试) */}
      {singleStockResult && (
        <div className="bg-[#faf6f0] border-2 border-[#705c30] p-4 rounded-xl shadow-md space-y-3">
          <div className="flex items-center justify-between border-b border-[#c4c8bc]/40 pb-2">
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-[#705c30]" />
              <span className="font-bold text-base text-[#2e3230]">
                【单股评估结果】{singleStockResult.name || singleStockResult.ts_code} ({singleStockResult.ts_code}) @ {singleStockResult.trade_date}
              </span>
            </div>
            <button
              onClick={() => setSingleStockResult(null)}
              className="px-2.5 py-1 text-xs font-bold text-gray-500 hover:text-gray-800 bg-white border border-gray-300 rounded"
            >
              关闭卡片
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-4 text-xs">
            <div className="bg-white p-3 rounded-lg border border-[#c4c8bc]/50 space-y-1">
              <span className="text-[#686d68] font-bold block">评级总分 & 状态</span>
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-xl text-[#2e3230]">
                  {singleStockResult.total_score.toFixed(1)} 分
                </span>
                <span className={`px-2 py-0.5 rounded text-xs font-bold text-white ${
                  singleStockResult.state === 'EARLY_TURN' ? 'bg-[#4a7c59]' :
                  singleStockResult.state === 'PRE_READY' ? 'bg-[#705c30]' :
                  singleStockResult.state === 'WATCH' ? 'bg-[#2e3230]' : 'bg-rose-700'
                }`}>
                  {singleStockResult.state}
                </span>
              </div>
            </div>

            <div className="flex-1 bg-white p-3 rounded-lg border border-[#c4c8bc]/50 space-y-1.5">
              <span className="text-[#686d68] font-bold block">8 大算子拆解明细</span>
              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-700 font-bold">
                  均线压缩: {singleStockResult.score_detail_json?.compression || 0}分 (ATR:{singleStockResult.score_detail_json?.min_3ma_spread_atr})
                </span>
                <span className="px-2 py-0.5 rounded bg-indigo-50 text-indigo-700 font-bold">
                  均线结: {singleStockResult.score_detail_json?.knot || 0}分 ({singleStockResult.score_detail_json?.cross_pair_count_10d}组)
                </span>
                <span className="px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 font-bold">
                  方向重排: {singleStockResult.score_detail_json?.direction || 0}分 (改善:{singleStockResult.score_detail_json?.order_improvement})
                </span>
                <span className="px-2 py-0.5 rounded bg-amber-50 text-amber-700 font-bold">
                  斜率转向: {singleStockResult.score_detail_json?.slope || 0}分 ({singleStockResult.score_detail_json?.up_slope_count}根)
                </span>
                <span className="px-2 py-0.5 rounded bg-purple-50 text-purple-700 font-bold">
                  夺回成本区: {singleStockResult.score_detail_json?.retake || 0}分
                </span>
                <span className="px-2 py-0.5 rounded bg-rose-50 text-rose-700 font-bold">
                  偏离延伸: {singleStockResult.score_detail_json?.extension || 0}分 ({singleStockResult.score_detail_json?.extension_atr}ATR)
                </span>
              </div>
            </div>
          </div>

        {singleStockResult.reasons_json && singleStockResult.reasons_json.length > 0 && (
            <div className="bg-white p-3 rounded-lg border border-[#c4c8bc]/40 space-y-1 text-xs">
              <span className="font-bold text-[#2e3230]">得分与诊断特征说明:</span>
              {singleStockResult.reasons_json.map((r: any, idx: number) => (
                <div key={idx} className="flex items-center gap-2 text-[11px]">
                  <span className="px-1.5 py-0.2 rounded bg-[#4a7c59]/10 text-[#4a7c59] font-bold">{r.type}</span>
                  <span className="text-[#2e3230]">{r.msg}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 状态分类顶栏卡片 (4大核心状态) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {/* Card 1: EARLY_TURN */}
        <div
          onClick={() => {
            setActiveState(activeState === 'EARLY_TURN' ? 'ALL' : 'EARLY_TURN');
            setPage(1);
          }}
          className={`cursor-pointer rounded-xl p-3.5 border transition shadow-xs space-y-1.5 ${
            activeState === 'EARLY_TURN'
              ? 'bg-[#4a7c59] text-white border-[#4a7c59] ring-2 ring-[#4a7c59]/30'
              : 'bg-white border-[#c4c8bc]/50 hover:border-[#4a7c59]'
          }`}
        >
          <div className="flex items-center justify-between text-xs">
            <span className="font-bold flex items-center gap-1">
              <Sparkles className="h-3.5 w-3.5" /> EARLY_TURN (转强信号)
            </span>
            <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-black/10">{">= 75分"}</span>
          </div>
          <p className="text-xl font-bold font-mono">{counts.EARLY_TURN || 0} 只</p>
          <p className={`text-[10px] ${activeState === 'EARLY_TURN' ? 'text-emerald-100' : 'text-[#686d68]'}`}>
            均线状态重排完成，具备高优先转强动能
          </p>
        </div>

        {/* Card 2: PRE_READY */}
        <div
          onClick={() => {
            setActiveState(activeState === 'PRE_READY' ? 'ALL' : 'PRE_READY');
            setPage(1);
          }}
          className={`cursor-pointer rounded-xl p-3.5 border transition shadow-xs space-y-1.5 ${
            activeState === 'PRE_READY'
              ? 'bg-[#705c30] text-white border-[#705c30] ring-2 ring-[#705c30]/30'
              : 'bg-white border-[#c4c8bc]/50 hover:border-[#705c30]'
          }`}
        >
          <div className="flex items-center justify-between text-xs">
            <span className="font-bold flex items-center gap-1">
              <Target className="h-3.5 w-3.5" /> PRE_READY (重点观察区)
            </span>
            <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-black/10">65~74分</span>
          </div>
          <p className="text-xl font-bold font-mono">{counts.PRE_READY || 0} 只</p>
          <p className={`text-[10px] ${activeState === 'PRE_READY' ? 'text-amber-100' : 'text-[#686d68]'}`}>
            如京投发展 8/5~8/7 爆发前夕形态
          </p>
        </div>

        {/* Card 3: WATCH */}
        <div
          onClick={() => {
            setActiveState(activeState === 'WATCH' ? 'ALL' : 'WATCH');
            setPage(1);
          }}
          className={`cursor-pointer rounded-xl p-3.5 border transition shadow-xs space-y-1.5 ${
            activeState === 'WATCH'
              ? 'bg-[#2e3230] text-white border-[#2e3230] ring-2 ring-[#2e3230]/30'
              : 'bg-white border-[#c4c8bc]/50 hover:border-[#2e3230]'
          }`}
        >
          <div className="flex items-center justify-between text-xs">
            <span className="font-bold flex items-center gap-1">
              <Activity className="h-3.5 w-3.5" /> WATCH (初步观察)
            </span>
            <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-black/10">50~64分</span>
          </div>
          <p className="text-xl font-bold font-mono">{counts.WATCH || 0} 只</p>
          <p className={`text-[10px] ${activeState === 'WATCH' ? 'text-zinc-300' : 'text-[#686d68]'}`}>
            具备均线压缩或初步转向，蓄势中
          </p>
        </div>

        {/* Card 4: TOO_LATE */}
        <div
          onClick={() => {
            setActiveState(activeState === 'TOO_LATE' ? 'ALL' : 'TOO_LATE');
            setPage(1);
          }}
          className={`cursor-pointer rounded-xl p-3.5 border transition shadow-xs space-y-1.5 ${
            activeState === 'TOO_LATE'
              ? 'bg-rose-700 text-white border-rose-700 ring-2 ring-rose-700/30'
              : 'bg-white border-[#c4c8bc]/50 hover:border-rose-700'
          }`}
        >
          <div className="flex items-center justify-between text-xs">
            <span className="font-bold flex items-center gap-1">
              <AlertTriangle className="h-3.5 w-3.5" /> TOO_LATE (过度延伸)
            </span>
            <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-black/10">{"> 2.0 ATR"}</span>
          </div>
          <p className="text-xl font-bold font-mono">{counts.TOO_LATE || 0} 只</p>
          <p className={`text-[10px] ${activeState === 'TOO_LATE' ? 'text-rose-100' : 'text-[#686d68]'}`}>
            信号强但股价已大幅拉升偏离均线
          </p>
        </div>
      </div>

      {/* 行业筛选与搜索工具条（合并行以节省空间） */}
      <div className="bg-[#f0ece4]/70 p-2.5 rounded-xl border border-[#c4c8bc]/40 flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-bold text-[#686d68] mr-1">行业筛选:</span>
          <button
            onClick={() => {
              setSelectedIndustry('ALL');
              setPage(1);
            }}
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
              onClick={() => {
                setSelectedIndustry(ind.name);
                setPage(1);
              }}
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
          {industryShowCount > 8 && (
            <button
              onClick={() => setIndustryShowCount(8)}
              className="px-2 py-1 font-bold rounded-md border border-dashed border-[#686d68]/50 text-[#686d68] hover:bg-[#686d68]/10 transition"
            >
              收起
            </button>
          )}
        </div>

        <div className="flex items-center gap-2 ml-auto">
          {/* 即时搜索框 */}
          <div className="flex items-center gap-1 bg-white px-2.5 py-1 rounded-lg border border-[#c4c8bc]/50">
            <Search className="h-3.5 w-3.5 text-[#686d68]" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索代码、名称..."
              className="w-32 bg-transparent outline-none text-[#2e3230]"
            />
          </div>

          <div className="flex items-center gap-1 bg-white px-2 py-1 rounded-lg border border-[#c4c8bc]/50">
            <span className="text-[#686d68] font-bold">最低分:</span>
            <input
              type="number"
              value={minScore}
              onChange={(e) => setMinScore(e.target.value)}
              placeholder="50"
              className="w-12 bg-white border border-[#c4c8bc]/50 px-1 py-0.5 text-center outline-none rounded font-mono"
            />
          </div>

          {/* 搜索行业 Combobox */}
          <div className="relative">
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
                      setPage(1);
                      setShowIndustryDropdown(false);
                    }}
                    className="w-full text-left px-2 py-1 text-xs text-[#2e3230] hover:bg-[#faf6f0] rounded font-medium"
                  >
                    全部 ({totalIndustryCount})
                  </button>
                  {filteredIndustriesForSearch.map((ind) => (
                    <button
                      key={ind}
                      onClick={() => {
                        setSelectedIndustry(ind);
                        setPage(1);
                        setShowIndustryDropdown(false);
                      }}
                      className={`w-full text-left px-2 py-1 text-xs rounded transition flex items-center justify-between ${
                        selectedIndustry === ind
                          ? 'bg-[#4a7c59]/15 text-[#4a7c59] font-bold'
                          : 'text-[#2e3230] hover:bg-[#faf6f0]'
                      }`}
                    >
                      <span>{ind}</span>
                      <span className="text-[10px] text-[#686d68] font-mono">({industryCounts[ind] || 0})</span>
                    </button>
                  ))}
                  {filteredIndustriesForSearch.length === 0 && (
                    <div className="text-center py-4 text-xs text-gray-400">无匹配行业</div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 结果数据主表格 */}
      <div className="bg-white rounded-xl border border-[#c4c8bc]/60 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-[#f0ece4] border-b border-[#c4c8bc]/40 text-[#686d68]">
                <th className="py-3 px-3 font-bold w-24">代码</th>
                <th className="py-3 px-3 font-bold w-48">名称 / 行业</th>
                <th className="py-3 px-3 font-bold w-28">总分 & 状态</th>
                <th className="py-3 px-3 font-bold w-36">背景类型</th>
                <th className="py-3 px-3 font-bold">8大算子特征得分拆解 (Pillars)</th>
                <th className="py-3 px-3 font-bold w-32">首次入选</th>
                <th className="py-3 px-3 font-bold text-center w-24">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#c4c8bc]/20">
              {loadingStocks ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-[#686d68]">
                    <div className="inline-flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin text-[#4a7c59]" />
                      正在加载 Early Turn 评估结果...
                    </div>
                  </td>
                </tr>
              ) : currentItems.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-[#686d68]">
                    当前筛选条件下暂无 Early Turn 候选。
                  </td>
                </tr>
              ) : (
                currentItems.map((item, idx) => {
                  const s = item.score_detail_json || {};
                  const isSelected = selectedStockIndex === idx;

                  return (
                    <tr
                      key={item.ts_code}
                      onClick={() => {
                        setSelectedStockIndex(idx);
                        setShowDetailSidebar(true);
                      }}
                      className={`hover:bg-[#f7f5f0]/80 transition cursor-pointer ${
                        isSelected ? 'bg-[#4a7c59]/10' : ''
                      }`}
                    >
                      {/* 代码 */}
                      <td className="py-3 px-3 font-mono font-bold text-[#2e3230]">{item.ts_code}</td>

                      {/* 名称 / 行业 */}
                      <td className="py-3 px-3 space-y-1">
                        <div className="flex items-center gap-1.5">
                          <span className="font-bold text-[#2e3230]">{item.name || '未命名'}</span>
                          {item.industry && (
                            <span className="rounded bg-[#4a7c59]/10 px-1.5 py-0.5 text-[10px] font-bold text-[#4a7c59]">
                              {item.industry}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* 总分 & 状态 */}
                      <td className="py-3 px-3 space-y-1">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono font-bold text-sm text-[#2e3230]">
                            {item.total_score.toFixed(1)}分
                          </span>
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                              item.state === 'EARLY_TURN_STRICT'
                                ? 'bg-amber-600 text-white font-black animate-pulse'
                                : item.state === 'EARLY_TURN'
                                ? 'bg-[#4a7c59] text-white'
                                : item.state === 'PRE_READY_STRICT'
                                ? 'bg-amber-700 text-white font-bold'
                                : item.state === 'PRE_READY'
                                ? 'bg-[#705c30] text-white'
                                : item.state === 'WATCH'
                                ? 'bg-[#2e3230] text-white'
                                : item.state === 'TOO_LATE'
                                ? 'bg-rose-700 text-white'
                                : 'bg-gray-200 text-gray-700'
                            }`}
                          >
                            {item.state}
                          </span>
                        </div>
                      </td>

                      {/* 背景类型 */}
                      <td className="py-3 px-3">
                        <span className="inline-block rounded bg-[#faf6f0] border border-[#c4c8bc]/50 px-2 py-0.5 text-[11px] font-bold text-[#705c30]">
                          {item.background_type === 'REVERSAL_BASE'
                            ? '📉 下降筑底反转'
                            : item.background_type === 'CONSOLIDATION_RESTART'
                            ? '📈 整理再启动'
                            : '基础型'}
                        </span>
                      </td>

                      {/* 8大算子拆解 */}
                      <td className="py-3 px-3">
                        <div className="flex flex-wrap items-center gap-1 text-[10px]">
                          <span className="rounded bg-blue-50 text-blue-700 px-1.5 py-0.5 font-semibold">
                            压缩: {s.compression || 0}分 (ATR:{s.min_3ma_spread_atr || '-'})
                          </span>
                          <span className="rounded bg-indigo-50 text-indigo-700 px-1.5 py-0.5 font-semibold">
                            均线结: {s.knot || 0}分 ({s.cross_pair_count_10d || 0}组)
                          </span>
                          <span className="rounded bg-emerald-50 text-emerald-700 px-1.5 py-0.5 font-semibold">
                            方向: {s.direction || 0}分
                          </span>
                          <span className="rounded bg-amber-50 text-amber-700 px-1.5 py-0.5 font-semibold">
                            斜率: {s.slope || 0}分 ({s.up_slope_count || 0}根)
                          </span>
                          <span className="rounded bg-purple-50 text-purple-700 px-1.5 py-0.5 font-semibold">
                            站回: {s.retake || 0}分
                          </span>
                          {item.is_overextended && (
                            <span className="rounded bg-rose-100 text-rose-700 px-1.5 py-0.5 font-bold">
                              ⚠️偏离过大 ({s.extension_atr}ATR)
                            </span>
                          )}
                        </div>
                      </td>

                      {/* 首次入选 */}
                      <td className="py-3 px-3 font-mono text-[11px] text-[#686d68]">
                        {item.first_selected_date || '未首次入选'}
                      </td>

                      {/* 操作 */}
                      <td className="py-3 px-3 text-center">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedStockIndex(idx);
                            setShowDetailSidebar(true);
                          }}
                          className="px-2.5 py-1 bg-white border border-[#4a7c59] text-[#4a7c59] rounded hover:bg-[#4a7c59] hover:text-white font-bold transition text-[11px]"
                        >
                          查看诊断
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        {data && data.total > 50 && (
          <div className="p-3 bg-[#faf6f0] border-t border-[#c4c8bc]/40 flex items-center justify-between text-xs">
            <span className="text-[#686d68]">
              显示 {(page - 1) * 50 + 1} - {Math.min(page * 50, data.total)} 条，共 {data.total} 条
            </span>
            <div className="flex items-center gap-1">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="px-2.5 py-1 bg-white border border-[#c4c8bc]/60 rounded font-bold disabled:opacity-40"
              >
                上一页
              </button>

              <button
                disabled={page >= Math.ceil(data.total / 50)}
                onClick={() => setPage((p) => p + 1)}
                className="px-2.5 py-1 bg-white border border-[#c4c8bc]/60 rounded font-bold disabled:opacity-40"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>

      {/* K 线及单股得分诊断侧栏/弹窗 */}
      {selectedStockIndex !== null && selectedStock && (
        <KLineModal
          assetCode={selectedStock.ts_code}
          assetName={selectedStock.name || selectedStock.ts_code}
          isOpen={showDetailSidebar}
          onClose={() => setShowDetailSidebar(false)}
          hasPrev={selectedStockIndex > 0}
          hasNext={selectedStockIndex < currentItems.length - 1}
          onNavigatePrev={() => setSelectedStockIndex((i) => (i !== null ? Math.max(0, i - 1) : null))}
          onNavigateNext={() => setSelectedStockIndex((i) => (i !== null ? Math.min(currentItems.length - 1, i + 1) : null))}
        />
      )}
    </div>
  );
}
