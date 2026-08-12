'use client';

import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import dynamic from 'next/dynamic';
import RunScreeningModal from './components/RunScreeningModal';
import RunHistoryModal from './components/RunHistoryModal';
import { History } from 'lucide-react';

const EarlyTurnFunnel = dynamic(() => import('./components/EarlyTurnFunnel'), { ssr: false });
const SampleValidationView = dynamic(() => import('./components/SampleValidationView'), { ssr: false });
const KLineModal = dynamic(() => import('./components/KLineModal'), { ssr: false });
const PoolStageFunnel = dynamic(() => import('./components/PoolStageFunnel'), { ssr: false });
const ImportModal = dynamic(() => import('./components/ImportModal'), { ssr: false });
const ImportedDashboard = dynamic(() => import('./components/ImportedDashboard'), { ssr: false });
const ReverseBreakoutPage = dynamic(() => import('./components/ReverseBreakoutPage'), { ssr: false });
const MarketQuotesPage = dynamic(() => import('./components/MarketQuotesPage'), { ssr: false });
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Calendar,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  ExternalLink,
  LineChart,
  Loader2,
  PlayCircle,
  RefreshCw,
  Search,
  Sparkles,
  Moon,
  Sun,
  Target,
  TrendingDown,
  TrendingUp,
  Filter,
  ChevronDown,
  X,
} from 'lucide-react';

type ReturnMap = Record<string, number | null>;

type TimeframeSummary = {
  daily: string;
  short_term: string;
  medium_term: string;
  long_term: string;
};

type IndexRow = {
  id: string;
  name: string;
  symbol: string;
  quote_url: string;
  close: number;
  amount: number;
  returns: ReturnMap;
  rankings: Record<string, number>;
  drawdowns: Record<string, number | null>;
  moving_averages: Record<string, {
    available: boolean;
    position?: string;
    slope?: string;
    distance_pct?: number;
  }>;
  amount_vs_20w_avg_pct: number | null;
  internal_breadth: {
    up_ratio: number | null;
    median_return: number | null;
    equal_weight_return: number | null;
  };
  attribution: {
    available: boolean;
    reason?: string;
    covered_weight_pct?: number;
    weight_effective_date?: string;
    estimated_return_pct?: number;
    actual_return_pct?: number | null;
    top_positive_contributors?: Array<{
      code: string;
      name: string | null;
      contribution_pct_points: number;
    }>;
    top_negative_contributors?: Array<{
      code: string;
      name: string | null;
      contribution_pct_points: number;
    }>;
    direction?: 'up' | 'down';
    key_constituents?: Array<{
      code: string;
      name: string | null;
      return_pct: number;
      industry: string;
    }>;
  };
};

type IndustryRow = {
  name: string;
  close: number;
  returns: ReturnMap;
  rankings: Record<string, number>;
  internal_breadth: number;
  up_count: number;
  down_count: number;
  summary_change_pct: number;
};

type OverviewReport = {
  is_imported?: boolean;
  raw_content?: string;
  imported_payload?: any;
  trade_date: string;
  mode?: 'daily' | 'weekly';
  updated_at?: string;
  core_conclusion: {
    summary: string;
    headline: string;
    timeframes: TimeframeSummary;
    evidence: string[];
    conflicts: string[];
    risks: string[];
    changes_from_previous_review: string[];
    industry_groups: {
      top_gainers: string[];
      top_decliners: string[];
    };
  };
  indices: IndexRow[];
  breadth: {
    trade_date: string;
    snapshot_time: string;
    stock_count: number;
    rising_count: number;
    falling_count: number;
    flat_count: number;
    rising_ratio: number;
    total_amount: number;
    limit_up_count: number;
    limit_down_count: number | null;
    quadrant: string;
    five_index_equal_weight_daily_return: number;
    limit_down_empty_with_no_columns: boolean;
    technical: {
      above_ma20_count: number;
      above_ma20_ratio: number;
      above_ma20_eligible_count: number;
      above_ma60_count: number;
      above_ma60_ratio: number;
      above_ma60_eligible_count: number;
      new_high_20_count: number;
      new_high_20_ratio: number;
      new_low_20_count: number;
      new_low_20_ratio: number;
      new_high_low_eligible_count: number;
    };
    history: {
      avg_rising_ratio_5d: number | null;
      avg_rising_ratio_20d: number | null;
      turnover_change_vs_previous_pct: number | null;
      turnover_avg_5d: number | null;
      turnover_avg_20d: number | null;
      turnover_vs_20d_pct: number | null;
      turnover_one_year_percentile: number | null;
      available_days: number;
    };
  };
  industries: IndustryRow[];
  industry_scope: {
    actual_industries: number;
    is_full_universe: boolean;
  };
  data_sources: Record<string, string>;
  data_quality: {
    status: 'intraday' | 'closing_pending' | 'final' | 'partial' | 'error';
    label: string;
    message: string;
    is_final: boolean;
    missing_fields: string[];
    snapshot_time?: string;
    captured_at?: string;
    industry_taxonomy: string;
  };
  market_classification: {
    daily_state: string;
    size_style: string;
    growth_style: string;
    risk_appetite: string;
    evidence: string[];
    conflicting_evidence: string[];
    period: string;
  };
  ai_analysis?: {
    data_quality: {status: string; message: string};
    headline: string;
    timeframes: TimeframeSummary;
    market_structure: {
      common_direction: string;
      relative_strength: string;
      style_interpretation: string;
      confidence: string;
    };
    index_attribution: Array<{
      index_name: string;
      summary: string;
      data_limitations: string[];
    }>;
    breadth_and_turnover: {
      summary: string;
      breadth_interpretation: string;
      turnover_interpretation: string;
      short_term_vs_medium_term: string;
    };
    industries: {
      top_gainers: string[];
      top_decliners: string[];
      breadth_interpretation: string;
      summary: string;
    };
    changes_from_previous_review: string[];
    conflicting_evidence: string[];
    unknowns: string[];
    next_observations: string[];
    full_review: string;
    meta: {
      model: string;
      generated_at: string;
      cached: boolean;
      report_type: 'daily' | 'weekly';
    };
  };
};

type HistoryItem = {
  trade_date: string;
  summary: string;
  data_status: string | null;
  report_type: string | null;
  updated_at: string;
};

type ScreeningPool = 'A-Pre' | 'A' | 'B' | 'C';

type ScreeningCandidate = {
  trade_date: string;
  asset_code: string;
  name: string | null;
  asset_type: 'stock' | 'etf';
  primary_pool: 'A-Pre' | 'A' | 'B' | 'C';
  stage: string;
  score: number;
  pools: Array<{
    pool: string;
    stage: string;
    score: number;
    score_detail?: Record<string, number>;
    passed_rules?: string[];
    failed_rules?: string[];
  }>;
  reasons: string[];
  risks: string[];
  status_change: string;
  features: Record<string, number | string | boolean | null>;
  is_selected?: boolean;
  user_note?: string;
  industry?: string | null;
  market?: string | null;
  ent_type?: string | null;
  province?: string | null;
  city?: string | null;
  main_business?: string | null;
  fund_type?: string | null;
  management?: string | null;
};

type ScreeningPayload = {
  trade_date: string;
  ruleset_version: string;
  pool: ScreeningPool;
  counts: Record<string, number>;
  industry_counts?: Record<string, number>;
  coverage: {
    listed: Record<'stock' | 'etf', number>;
    daily: Record<'stock' | 'etf', number>;
    scanned: Record<'stock' | 'etf', number>;
  };
  items: ScreeningCandidate[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
  filters: {
    min_score: number | null;
    max_score: number | null;
    query: string;
  };
  run?: {
    candidate_count: number;
    counts: Record<string, number>;
    outputs: Record<string, string>;
  };
};

type ScreeningRequest = {
  page: number;
  pageSize: number;
  minScore: number | null;
  maxScore: number | null;
  query: string;
  industry: string;
};

const DEFAULT_SCREENING_REQUEST: ScreeningRequest = {
  page: 1,
  pageSize: 50,
  minScore: null,
  maxScore: null,
  query: '',
  industry: '',
};

type ScreeningHistoryItem = {
  trade_date: string;
};

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL || 'http://127.0.0.1:18080';

function formatDate(value: string) {
  if (!value || value.length !== 8) return value;
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}`;
}

function formatPct(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '暂无';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

function formatRatio(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '暂无';
  return `${(value * 100).toFixed(1)}%`;
}

function formatAmount(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '暂无';
  return `${(value / 100000000).toFixed(0)}亿`;
}

function toneClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'text-[#4a4e4a]';
  return value >= 0 ? 'text-[#b83230]' : 'text-[#237a4b]';
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {cache: 'no-store'});
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

export default function MarketReviewApp() {
  const [activeView, setActiveView] = useState<'market' | 'review' | 'screening' | 'reverse'>('market');
  const [report, setReport] = useState<OverviewReport | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [showImportModal, setShowImportModal] = useState(false);
  const [screening, setScreening] = useState<ScreeningPayload | null>(null);
  const [screeningHistory, setScreeningHistory] = useState<ScreeningHistoryItem[]>([]);
  const [screeningLoading, setScreeningLoading] = useState(true);
  const [screeningError, setScreeningError] = useState<string | null>(null);
  const [screeningPool, setScreeningPool] = useState<ScreeningPool>('A');
  const [screeningOnlySelected, setScreeningOnlySelected] = useState(false);
  const [screeningSubTab, setScreeningSubTab] = useState<'SECONDARY' | 'EARLY_TURN' | 'SAMPLES'>('SECONDARY');
  const [screeningRunning, setScreeningRunning] = useState(false);
  const [screeningRequest, setScreeningRequest] = useState<ScreeningRequest>(DEFAULT_SCREENING_REQUEST);
  const [taskStatus, setTaskStatus] = useState<{ status: string; progress: number; step_message: string } | null>(null);
  const [theme, setTheme] = useState<'default' | 'dark'>('default');

  useEffect(() => {
    const saved = localStorage.getItem('app-theme') as 'default' | 'dark' | null;
    if (saved === 'dark') {
      setTheme('dark');
      document.documentElement.setAttribute('data-theme', 'dark');
    }
  }, []);

  const toggleTheme = (e: React.MouseEvent<HTMLButtonElement>) => {
    const nextTheme = theme === 'default' ? 'dark' : 'default';

    const updateDOM = () => {
      setTheme(nextTheme);
      if (nextTheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
      } else {
        document.documentElement.removeAttribute('data-theme');
      }
      localStorage.setItem('app-theme', nextTheme);
    };

    if (!(document as any).startViewTransition) {
      updateDOM();
      return;
    }

    const rect = e.currentTarget.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const endRadius = Math.hypot(
      Math.max(x, window.innerWidth - x),
      Math.max(y, window.innerHeight - y)
    );

    const transition = (document as any).startViewTransition(() => {
      updateDOM();
    });

    transition.ready.then(() => {
      const clipPath = [
        `circle(0px at ${x}px ${y}px)`,
        `circle(${endRadius}px at ${x}px ${y}px)`
      ];
      document.documentElement.animate(
        {
          clipPath: clipPath
        },
        {
          duration: 550,
          easing: 'cubic-bezier(0.4, 0, 0.2, 1)',
          pseudoElement: '::view-transition-new(root)',
        }
      );
    });
  };

  useEffect(() => {
    let timer: NodeJS.Timeout;
    const checkStatus = async () => {
      try {
        const res = await fetchJson<{ status: string; progress: number; step_message: string }>('/api/screening/status');
        setTaskStatus(res);
        if (res.status === 'running' || res.status === 'RUNNING') {
          setScreeningRunning(true);
        } else if ((res.status === 'success' || res.status === 'DONE') && screeningRunning) {
          setScreeningRunning(false);
          const historyPayload = await fetchJson<{ items: ScreeningHistoryItem[] }>('/api/screening/history');
          setScreeningHistory(historyPayload.items);
          loadScreening(screeningPool, undefined, DEFAULT_SCREENING_REQUEST);
        } else if ((res.status === 'failed' || res.status === 'ERROR') && screeningRunning) {
          setScreeningRunning(false);
          setScreeningError(res.step_message || '选股运行失败');
        }
      } catch (e) {
        console.error('轮询后台选股任务状态异常', e);
      }
    };

    checkStatus();
    timer = setInterval(checkStatus, 1500);
    return () => clearInterval(timer);
  }, [screeningRunning, screeningPool]);

  async function loadData(tradeDate?: string) {
    setLoading(true);
    setError(null);
    try {
      const [overview, historyPayload] = await Promise.all([
        fetchJson<OverviewReport>(tradeDate ? `/api/market-review/overview/${tradeDate}` : '/api/market-review/overview/latest'),
        fetchJson<{items: HistoryItem[]}>('/api/market-review/history'),
      ]);
      setReport(overview);
      setHistory(historyPayload.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '数据读取失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
    loadScreening();
  }, []);

  async function loadScreening(
    pool: ScreeningPool = screeningPool,
    tradeDate?: string,
    request: ScreeningRequest = screeningRequest,
    onlySelected: boolean = screeningOnlySelected,
    silent: boolean = false,
  ) {
    if (!silent) {
      setScreeningLoading(true);
    }
    setScreeningError(null);
    try {
      const params = new URLSearchParams({
        pool,
        page: String(request.page),
        page_size: String(request.pageSize),
      });
      if (request.minScore !== null) params.set('min_score', String(request.minScore));
      if (request.maxScore !== null) params.set('max_score', String(request.maxScore));
      if (request.query.trim()) params.set('q', request.query.trim());
      if (request.industry?.trim()) params.set('industry', request.industry.trim());
      if (onlySelected) params.set('only_selected', 'true');
      const [payload, historyPayload] = await Promise.all([
        fetchJson<ScreeningPayload>(tradeDate ? `/api/screening/${tradeDate}?${params}` : `/api/screening/latest?${params}`),
        fetchJson<{items: ScreeningHistoryItem[]}>('/api/screening/history'),
      ]);
      setScreening(payload);
      setScreeningHistory(historyPayload.items);
      setScreeningRequest(request);
      setScreeningOnlySelected(onlySelected);
    } catch (err) {
      if (!silent) {
        setScreeningError(err instanceof Error ? err.message : '选股结果读取失败');
      }
    } finally {
      if (!silent) {
        setScreeningLoading(false);
      }
    }
  }

  async function toggleCandidateSelect(item: ScreeningCandidate) {
    if (!screening) return;
    const nextSelected = !item.is_selected;
    const action = nextSelected ? 'SELECT' : 'REMOVE';

    // 乐观 UI 更新：立即翻转该标的的入池状态与计数，避免界面闪烁
    setScreening((prev) => {
      if (!prev) return prev;
      const updatedItems = prev.items.map((candidate) => {
        if (candidate.asset_code === item.asset_code && candidate.primary_pool === item.primary_pool) {
          return { ...candidate, is_selected: nextSelected };
        }
        return candidate;
      });
      const selectedDelta = nextSelected ? 1 : -1;
      const currentSelectedCount = prev.counts.selected || 0;
      return {
        ...prev,
        counts: {
          ...prev.counts,
          selected: Math.max(0, currentSelectedCount + selectedDelta),
        },
        items: updatedItems,
      };
    });

    try {
      await postJson('/api/screening/select', {
        trade_date: item.trade_date,
        asset_code: item.asset_code,
        pool: item.primary_pool,
        action,
      });
      await loadScreening(screeningPool, screening.trade_date, screeningRequest, screeningOnlySelected, true);
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败');
      await loadScreening(screeningPool, screening.trade_date, screeningRequest, screeningOnlySelected, true);
    }
  }

  async function selectDate(tradeDate: string) {
    if (!tradeDate || tradeDate === report?.trade_date) return;
    await loadData(tradeDate);
  }

  async function selectScreeningDate(tradeDate: string) {
    if (!tradeDate || tradeDate === screening?.trade_date) return;
    await loadScreening(screeningPool, tradeDate, {...screeningRequest, page: 1});
  }

  async function selectScreeningPool(pool: ScreeningPool) {
    setScreeningPool(pool);
    await loadScreening(pool, screening?.trade_date, {...screeningRequest, page: 1});
  }

  async function runScreening() {
    const tradeDate = screening?.trade_date || report?.trade_date;
    if (!tradeDate) return;
    setScreeningRunning(true);
    setScreeningError(null);
    try {
      await postJson<{ status: string; trade_date?: string; pool?: string }>('/api/screening/run', {
        trade_date: tradeDate,
        pool: 'ABC',
      });
      setScreeningPool('A');
      setScreeningRequest(DEFAULT_SCREENING_REQUEST);
    } catch (err) {
      setScreeningError(err instanceof Error ? err.message : '自动选股运行失败');
      setScreeningRunning(false);
    }
  }

  async function generateAI() {
    if (!report) return;
    setAiLoading(true);
    setAiError(null);
    try {
      const updated = await postJson<OverviewReport>('/api/market-review/ai/generate', {
        trade_date: report.trade_date,
        report_type: report.mode || 'daily',
        force: Boolean(report.ai_analysis),
      });
      setReport(updated);
    } catch (err) {
      setAiError(err instanceof Error ? err.message : 'AI 初稿生成失败');
    } finally {
      setAiLoading(false);
    }
  }

  return (
    <div className={`min-h-screen flex flex-col ${theme === 'dark' ? 'bg-[#0b0f19] text-[#f8fafc]' : 'bg-[#faf6f0] text-[#2e3230]'}`} data-theme={theme}>
      <header className="fixed top-0 z-50 w-full border-b border-[#c4c8bc]/30 bg-[#f0ece4]/90 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1600px] items-center justify-between px-4 lg:px-8">
          <div className="flex items-center gap-8">
            <div className="flex items-center gap-2">
              <Activity className="h-6 w-6 text-[#4a7c59]" />
              <span className="font-[family-name:var(--font-literata)] text-lg font-bold text-[#2e3230]">
                LLL 交易研究
              </span>
            </div>
            <nav className="hidden items-center gap-1 md:flex">
              <button
                onClick={() => setActiveView('market')}
                className={`rounded-md px-3 py-1.5 text-sm font-bold ${activeView === 'market' ? 'bg-[#4a7c59] text-white' : 'text-[#4a4e4a] hover:bg-[#e4e0d8]'}`}
              >
                A股行情
              </button>
              <button
                onClick={() => setActiveView('review')}
                className={`rounded-md px-3 py-1.5 text-sm font-bold ${activeView === 'review' ? 'bg-[#4a7c59] text-white' : 'text-[#4a4e4a] hover:bg-[#e4e0d8]'}`}
              >
                复盘
              </button>
              <button
                onClick={() => setActiveView('screening')}
                className={`rounded-md px-3 py-1.5 text-sm font-bold ${activeView === 'screening' ? 'bg-[#4a7c59] text-white' : 'text-[#4a4e4a] hover:bg-[#e4e0d8]'}`}
              >
                自动选股
              </button>
              <button
                onClick={() => setActiveView('reverse')}
                className={`rounded-md px-3 py-1.5 text-sm font-bold ${activeView === 'reverse' ? 'bg-[#4a7c59] text-white' : 'text-[#4a4e4a] hover:bg-[#e4e0d8]'}`}
              >
                形态反查
              </button>

            </nav>
          </div>
          <div className="flex items-center gap-3">
            {activeView === 'review' ? (
              <>
                <button
                  onClick={() => setShowImportModal(true)}
                  className="inline-flex items-center gap-1.5 rounded-md bg-[#4a7c59] px-3 py-1.5 text-xs font-bold text-white shadow-xs hover:bg-[#3b6447]"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  导入复盘文章
                </button>
                <label className="flex items-center gap-2 rounded-md bg-[#eae6de] px-3 py-1.5 text-xs font-bold text-[#4a4e4a]">
                  <Calendar className="h-3.5 w-3.5" />
                  <select
                    aria-label="选择复盘日期"
                    value={report?.trade_date || ''}
                    onChange={(event) => selectDate(event.target.value)}
                    className="bg-transparent outline-none"
                  >
                    {!report && <option value="">未加载</option>}
                    {history.map((item) => (
                      <option key={item.trade_date} value={item.trade_date}>{formatDate(item.trade_date)}</option>
                    ))}
                  </select>
                </label>
              </>
            ) : activeView === 'screening' ? (
              <label className="flex items-center gap-2 rounded-md bg-[#eae6de] px-3 py-1.5 text-xs font-bold text-[#4a4e4a]">
                <Calendar className="h-3.5 w-3.5" />
                <select
                  aria-label="选择选股日期"
                  value={screening?.trade_date || ''}
                  onChange={(event) => selectScreeningDate(event.target.value)}
                  className="bg-transparent outline-none"
                >
                  {!screening && <option value="">未加载</option>}
                  {screeningHistory.map((item) => (
                    <option key={item.trade_date} value={item.trade_date}>{formatDate(item.trade_date)}</option>
                  ))}
                </select>
              </label>
            ) : (
              <span className="hidden text-xs font-bold text-[#686d68] sm:inline">
                独立研究工具
              </span>
            )}
            {activeView !== 'reverse' && (
              <button
                onClick={() => activeView === 'review' ? loadData(report?.trade_date) : loadScreening(screeningPool, screening?.trade_date)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[#c4c8bc]/60 bg-white text-[#4a4e4a] hover:text-[#2e3230]"
                title="刷新"
              >
                <RefreshCw className="h-4 w-4" />
              </button>
            )}
            <button
              onClick={toggleTheme}
              className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-[#c4c8bc]/60 bg-white text-[#4a4e4a] shadow-xs transition-all hover:scale-110 active:scale-95 hover:shadow-md theme-toggle-btn"
              title={theme === 'default' ? '切换至 暗色科技 主题' : '切换至 原木默认 主题'}
              aria-label="切换主题"
            >
              {theme === 'dark' ? (
                <Sun className="h-4.5 w-4.5 text-amber-400" />
              ) : (
                <Moon className="h-4.5 w-4.5 text-slate-700" />
              )}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1600px] flex-1 pt-14">
        {activeView === 'review' && loading && <LoadingState label="正在读取复盘数据" />}
        {activeView === 'review' && !loading && error && <ErrorState message={error} onRetry={loadData} />}
        {activeView === 'review' && !loading && !error && report && (
          <Dashboard report={report} onGenerateAI={generateAI} aiLoading={aiLoading} aiError={aiError} />
        )}
        {activeView === 'screening' && (
          <div className="px-4 pt-3 sm:px-6 lg:px-8">
            <div className="flex items-center gap-2 border-b border-[#c4c8bc]/40 pb-2 mb-2">
              <button
                onClick={() => setScreeningSubTab('SECONDARY')}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition flex items-center gap-1.5 ${
                  screeningSubTab === 'SECONDARY'
                    ? 'bg-[#2e3230] text-white shadow-xs'
                    : 'bg-white text-[#4a4e4a] hover:bg-[#e4e0d8] border border-[#c4c8bc]/50'
                }`}
              >
                <span>📊 ABC池二次筛选 (五层过滤)</span>
              </button>

              <button
                onClick={() => setScreeningSubTab('EARLY_TURN')}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition flex items-center gap-1.5 ${
                  screeningSubTab === 'EARLY_TURN'
                    ? 'bg-[#4a7c59] text-white shadow-xs'
                    : 'bg-white text-[#4a4e4a] hover:bg-[#e4e0d8] border border-[#c4c8bc]/50'
                }`}
              >
                <span>🧪 A-Pre V2 早期转强实验 (均线状态迁移)</span>
              </button>

              <button
                onClick={() => setScreeningSubTab('SAMPLES')}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition flex items-center gap-1.5 ${
                  screeningSubTab === 'SAMPLES'
                    ? 'bg-[#705c30] text-white shadow-xs'
                    : 'bg-white text-[#4a4e4a] hover:bg-[#e4e0d8] border border-[#c4c8bc]/50'
                }`}
              >
                <span>🎯 正负样本回归校验看板</span>
              </button>
            </div>
          </div>
        )}

        {activeView === 'screening' && screeningSubTab === 'EARLY_TURN' && (
          <div className="px-4 pb-6 sm:px-6 lg:px-8">
            <EarlyTurnFunnel onOpenSampleValidation={() => setScreeningSubTab('SAMPLES')} />
          </div>
        )}

        {activeView === 'screening' && screeningSubTab === 'SAMPLES' && (
          <div className="px-4 pb-6 sm:px-6 lg:px-8">
            <SampleValidationView onClose={() => setScreeningSubTab('EARLY_TURN')} />
          </div>
        )}

        {activeView === 'screening' && screeningSubTab === 'SECONDARY' && screeningLoading && <LoadingState label="正在读取选股结果" />}
        {activeView === 'screening' && screeningSubTab === 'SECONDARY' && !screeningLoading && screeningError && <ErrorState message={screeningError} onRetry={() => loadScreening(screeningPool, screening?.trade_date)} />}
        {activeView === 'screening' && screeningSubTab === 'SECONDARY' && !screeningLoading && !screeningError && screening && (
          <ScreeningTab
            payload={screening}
            activePool={screeningPool}
            onPoolChange={(pool) => {
              setScreeningPool(pool);
              loadScreening(pool, screening.trade_date, {...screeningRequest, page: 1}, screeningOnlySelected);
            }}
            onlySelected={screeningOnlySelected}
            onOnlySelectedChange={(onlySelected) => {
              loadScreening(screeningPool, screening.trade_date, {...screeningRequest, page: 1}, onlySelected);
            }}
            request={screeningRequest}
            onRequestChange={(req) => loadScreening(screeningPool, screening.trade_date, req, screeningOnlySelected)}
            onRun={runScreening}
            running={screeningRunning}
            taskStatus={taskStatus}
            onToggleSelect={toggleCandidateSelect}
          />
        )}
        {activeView === 'market' && <MarketQuotesPage />}
        {activeView === 'reverse' && <ReverseBreakoutPage />}

        <ImportModal
          isOpen={showImportModal}
          onClose={() => setShowImportModal(false)}
          onSuccess={(date) => loadData(date)}
        />
      </main>
    </div>
  );
}

function Dashboard({
  report,
  onGenerateAI,
  aiLoading,
  aiError,
}: {
  report: OverviewReport;
  onGenerateAI: () => void;
  aiLoading: boolean;
  aiError: string | null;
}) {
  if (report.is_imported && report.imported_payload) {
    return (
      <ImportedDashboard
        tradeDate={report.trade_date}
        payload={report.imported_payload}
        rawContent={report.raw_content}
      />
    );
  }
  const strongest = useMemo(() => [...report.indices].sort((a, b) => (a.rankings?.['1w'] || 99) - (b.rankings?.['1w'] || 99))[0], [report.indices]);
  const weakest = useMemo(() => [...report.indices].sort((a, b) => (b.rankings?.['1w'] || 0) - (a.rankings?.['1w'] || 0))[0], [report.indices]);
  const industryGainers = useMemo(
    () => [...report.industries].sort((a, b) => b.summary_change_pct - a.summary_change_pct).slice(0, 10),
    [report.industries],
  );
  const industryDecliners = useMemo(
    () => [...report.industries].sort((a, b) => a.summary_change_pct - b.summary_change_pct).slice(0, 10),
    [report.industries],
  );
  const headline = report.ai_analysis?.headline || report.core_conclusion.headline;

  return (
    <div className="px-4 py-8 sm:px-6 lg:px-8">
      <section className="mb-8 rounded-lg border border-[#c4c8bc]/30 bg-[#f0ece4] p-6 shadow-[0_4px_20px_rgba(46,50,48,0.05)] md:p-8">
        <div className="grid gap-8 lg:grid-cols-[1fr_380px]">
          <div>
            <div className="mb-5 flex items-center gap-3">
              <div className="rounded-md bg-[#705c30]/10 p-2">
                <LineChart className="h-5 w-5 text-[#705c30]" />
              </div>
              <div>
                <h1 className="font-[family-name:var(--font-literata)] text-xl font-bold">复盘总览</h1>
                <p className="text-xs font-semibold text-[#4a4e4a]">交易日 {formatDate(report.trade_date)} · 行业口径：同花顺行业板块</p>
              </div>
            </div>
            <p className="max-w-5xl font-[family-name:var(--font-literata)] text-2xl font-bold leading-snug text-[#2e3230] md:text-3xl">
              {headline}
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              <Tag tone="neutral">{report.mode === 'weekly' ? '每周复盘' : '每日复盘'}</Tag>
              <Tag tone="neutral">全行业 {report.industry_scope.actual_industries} 个</Tag>
            </div>
          </div>
          <div className="rounded-lg border border-[#c4c8bc]/40 bg-[#faf6f0] p-5">
            <h2 className="mb-4 flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-[#4a4e4a]">
              <CheckCircle2 className="h-4 w-4" />
              核心依据
            </h2>
            <ul className="space-y-3 text-sm leading-relaxed text-[#4a4e4a]">
              {report.core_conclusion.evidence.map((item) => (
                <li key={item} className="flex gap-3">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[#4a7c59]" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="mb-8 border-y border-[#c4c8bc]/40 bg-white/45 px-5 py-5 md:px-7">
        <h2 className="mb-4 text-sm font-bold text-[#2e3230]">市场分类</h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <ClassificationItem label="当日状态" value={report.market_classification.daily_state} />
          <ClassificationItem label="规模风格 · 近5周" value={report.market_classification.size_style} />
          <ClassificationItem label="成长风格 · 近5周" value={report.market_classification.growth_style} />
          <ClassificationItem label="风险偏好" value={report.market_classification.risk_appetite} />
        </div>
        <p className="mt-4 text-sm leading-6 text-[#4a4e4a]">
          {report.market_classification.evidence.join('；')}。
          {report.market_classification.conflicting_evidence.length > 0 && ` 同时存在：${report.market_classification.conflicting_evidence.join('；')}。`}
        </p>
      </section>

      <section className="mb-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <TimeframeBlock title="当日盘面" text={report.ai_analysis?.timeframes.daily || report.core_conclusion.timeframes.daily} />
        <TimeframeBlock title="短期变化" text={report.ai_analysis?.timeframes.short_term || report.core_conclusion.timeframes.short_term} />
        <TimeframeBlock title="中期结构" text={report.ai_analysis?.timeframes.medium_term || report.core_conclusion.timeframes.medium_term} />
        <TimeframeBlock title="长期背景" text={report.ai_analysis?.timeframes.long_term || report.core_conclusion.timeframes.long_term} />
      </section>

      <section className="mb-8 border-y border-[#c4c8bc]/40 bg-white/45 px-5 py-6 md:px-7">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="rounded-md bg-[#4a7c59]/10 p-2 text-[#4a7c59]">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-bold">AI 复盘解读</h2>
              <p className="text-xs text-[#4a4e4a]">基于规则指标生成的系统初稿，不包含预测和交易建议</p>
            </div>
          </div>
          <button
            onClick={onGenerateAI}
            disabled={aiLoading}
            className="inline-flex items-center gap-2 rounded-md bg-[#4a7c59] px-4 py-2 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            {aiLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {aiLoading ? '正在生成' : report.ai_analysis ? '重新生成' : '生成 AI 初稿'}
          </button>
        </div>
        {aiError && (
          <div className="mb-4 rounded-md border border-[#b83230]/30 bg-[#b83230]/5 p-3 text-sm text-[#8f2927]">
            {aiError}
          </div>
        )}
        {report.ai_analysis ? (
          <div className="space-y-5">
            <div className="grid gap-x-8 gap-y-5 md:grid-cols-2">
              <AIParagraph title="共同方向" text={report.ai_analysis.market_structure.common_direction} />
              <AIParagraph title="相对强弱" text={report.ai_analysis.market_structure.relative_strength} />
              <AIParagraph title="风格解释" text={report.ai_analysis.market_structure.style_interpretation} />
              <AIParagraph title="市场广度分析" text={report.ai_analysis.breadth_and_turnover.breadth_interpretation} />
              <AIParagraph title="短期与中期广度" text={report.ai_analysis.breadth_and_turnover.short_term_vs_medium_term} />
              <AIParagraph title="成交分析" text={report.ai_analysis.breadth_and_turnover.turnover_interpretation} />
              <AIParagraph title="行业结构" text={report.ai_analysis.industries.summary} />
              <AIList title="本期变化" items={report.ai_analysis.changes_from_previous_review} />
              <AIList title="冲突证据" items={report.ai_analysis.conflicting_evidence} />
              <AIList title="下期观察" items={report.ai_analysis.next_observations} />
            </div>
            <p className="text-xs text-[#686d68]">
              {report.ai_analysis.meta.model} · {report.ai_analysis.meta.cached ? '复用已有初稿' : '本次新生成'}
            </p>
          </div>
        ) : (
          <p className="text-sm text-[#4a4e4a]">当前报告尚未生成 AI 初稿，规则结论和全部指标仍可正常使用。</p>
        )}
      </section>

      <section className="mb-8 grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
        {report.indices.map((item) => <IndexCard key={item.id} item={item} />)}
      </section>

      <section className="mb-8 grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <Panel title="多周期收益对比" icon={<BarChart3 className="h-5 w-5" />}>
          <div className="space-y-5">
            {report.indices.map((item) => <ReturnBars key={item.id} item={item} />)}
          </div>
          <div className="mt-5 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
            <Metric label="近1周最强" value={strongest?.name || '暂无'} />
            <Metric label="近1周最弱" value={weakest?.name || '暂无'} />
            <Metric label="五指数当日等权" value={formatPct(report.breadth.five_index_equal_weight_daily_return)} valueClass={toneClass(report.breadth.five_index_equal_weight_daily_return)} />
            <Metric label="成交额" value={formatAmount(report.breadth.total_amount)} />
          </div>
        </Panel>

        <Panel title="市场广度" icon={<Activity className="h-5 w-5" />}>
          <div className="grid grid-cols-2 gap-3">
            <Metric label="上涨家数" value={String(report.breadth.rising_count)} valueClass="text-[#b83230]" />
            <Metric label="下跌家数" value={String(report.breadth.falling_count)} valueClass="text-[#237a4b]" />
            <Metric label="上涨比例" value={formatRatio(report.breadth.rising_ratio)} />
            <Metric label="涨停/跌停" value={`${report.breadth.limit_up_count} / ${report.breadth.limit_down_count}`} />
            <Metric label="创20日新高/新低" value={`${report.breadth.technical.new_high_20_count} / ${report.breadth.technical.new_low_20_count}`} />
            <Metric label="站上20日线" value={formatRatio(report.breadth.technical.above_ma20_ratio)} />
            <Metric label="站上60日线" value={formatRatio(report.breadth.technical.above_ma60_ratio)} />
            <Metric label="平盘家数" value={String(report.breadth.flat_count)} />
          </div>
          {(report.breadth.history.avg_rising_ratio_5d !== null || report.breadth.history.turnover_vs_20d_pct !== null) && (
            <div className="mt-4 grid grid-cols-2 gap-3">
              {report.breadth.history.avg_rising_ratio_5d !== null && (
                <Metric label="5日平均上涨比例" value={formatRatio(report.breadth.history.avg_rising_ratio_5d)} compact />
              )}
              {report.breadth.history.turnover_vs_20d_pct !== null && (
                <Metric label="成交额较20日均值" value={formatPct(report.breadth.history.turnover_vs_20d_pct)} compact />
              )}
            </div>
          )}
          <div className="mt-5 rounded-lg bg-[#faf6f0] p-4">
            <p className="mb-2 text-xs font-bold text-[#4a4e4a]">四象限判断</p>
            <p className="text-xl font-bold text-[#2e3230]">{report.breadth.quadrant}</p>
          </div>
        </Panel>
      </section>

      <section className="mb-8 grid gap-6 lg:grid-cols-2">
        <IndustryRanking title="当日涨幅前10行业" rows={industryGainers} tone="red" />
        <IndustryRanking title="当日跌幅前10行业" rows={industryDecliners} tone="green" />
      </section>
    </div>
  );
}

function ScreeningTab({
  payload,
  activePool,
  onPoolChange,
  onlySelected,
  onOnlySelectedChange,
  request,
  onRequestChange,
  onRun,
  running,
  taskStatus,
  onToggleSelect,
}: {
  payload: ScreeningPayload;
  activePool: ScreeningPool;
  onPoolChange: (pool: ScreeningPool) => void;
  onlySelected: boolean;
  onOnlySelectedChange: (selected: boolean) => void;
  request: ScreeningRequest;
  onRequestChange: (request: ScreeningRequest) => void;
  onRun: () => void;
  running: boolean;
  taskStatus?: { status: string; progress: number; step_message: string } | null;
  onToggleSelect: (item: ScreeningCandidate) => void;
}) {
  const [query, setQuery] = useState(request.query);
  const [minScore, setMinScore] = useState(request.minScore === null ? '' : String(request.minScore));
  const [maxScore, setMaxScore] = useState(request.maxScore === null ? '' : String(request.maxScore));
  const [klineModalAsset, setKlineModalAsset] = useState<{ code: string; name: string } | null>(null);
  const [showRunModal, setShowRunModal] = useState(false);
  const [showHistoryModal, setShowHistoryModal] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [freshnessInfo, setFreshnessInfo] = useState<{ daily_market_date?: string; financial_data_quarter?: string }>({});

  useEffect(() => {
    fetch(`${API_BASE}/api/screening/freshness`)
      .then((res) => res.json())
      .then((data) => setFreshnessInfo(data))
      .catch((err) => console.error('Failed to fetch freshness:', err));
  }, []);
  const [klineModalAssetIndex, setKlineModalAssetIndex] = useState<number>(-1);
  const [focusedCandidateIndex, setFocusedCandidateIndex] = useState<number>(0);

  // 行业过滤状态与智能 Combobox
  const [selectedIndustry, setSelectedIndustry] = useState<string>('ALL');
  const [industrySearchQuery, setIndustrySearchQuery] = useState<string>('');
  const [showIndustryDropdown, setShowIndustryDropdown] = useState<boolean>(false);
  const [industryShowCount, setIndustryShowCount] = useState<number>(20);

  // 统计各行业频次（优先使用全量聚合的 industry_counts）
  const industryCounts = useMemo(() => {
    if (payload.industry_counts && Object.keys(payload.industry_counts).length > 0) {
      return payload.industry_counts;
    }
    const counts: Record<string, number> = {};
    payload.items.forEach((item) => {
      const ind = item.industry || (item.asset_type === 'etf' ? (item.fund_type || 'ETF') : '未分类');
      counts[ind] = (counts[ind] || 0) + 1;
    });
    return counts;
  }, [payload.industry_counts, payload.items]);

  // 按数量降序排列所有行业
  const sortedIndustries = useMemo(() => {
    return Object.entries(industryCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ name, count }));
  }, [industryCounts]);

  // 当前展示的行业（受 industryShowCount 控制）
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

  // 行业过滤已由后端处理，displayedItems 直接使用后端返回的分页数据
  const displayedItems = payload.items;


  const handleOpenKlineForIndex = (index: number) => {
    if (index >= 0 && index < displayedItems.length) {
      setFocusedCandidateIndex(index);
      setKlineModalAssetIndex(index);
      const item = displayedItems[index];
      setKlineModalAsset({ code: item.asset_code, name: item.name || item.asset_code });
    }
  };

  const handlePrevStock = () => {
    if (klineModalAssetIndex > 0) {
      handleOpenKlineForIndex(klineModalAssetIndex - 1);
    }
  };

  const handleNextStock = () => {
    if (klineModalAssetIndex < displayedItems.length - 1) {
      handleOpenKlineForIndex(klineModalAssetIndex + 1);
    }
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (klineModalAsset) return;
      const target = e.target as HTMLElement;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT')) {
        return;
      }

      if (e.key === ' ' || e.key === 'Spacebar') {
        e.preventDefault();
        if (payload.items.length > 0) {
          const targetIndex = focusedCandidateIndex >= 0 && focusedCandidateIndex < payload.items.length ? focusedCandidateIndex : 0;
          handleOpenKlineForIndex(targetIndex);
        }
        return;
      }

      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setFocusedCandidateIndex((prev) => Math.max(0, prev - 1));
        return;
      }

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setFocusedCandidateIndex((prev) => Math.min(payload.items.length - 1, prev + 1));
        return;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [klineModalAsset, payload.items, focusedCandidateIndex]);

  useEffect(() => {
    setQuery(request.query);
    setMinScore(request.minScore === null ? '' : String(request.minScore));
    setMaxScore(request.maxScore === null ? '' : String(request.maxScore));
  }, [request]);

  const parsedMinScore = minScore === '' ? null : Number(minScore);
  const parsedMaxScore = maxScore === '' ? null : Number(maxScore);
  const invalidScoreRange = parsedMinScore !== null && parsedMaxScore !== null && parsedMinScore > parsedMaxScore;

  function applyFilters() {
    if (invalidScoreRange) return;
    onRequestChange({
      ...request,
      page: 1,
      minScore: parsedMinScore,
      maxScore: parsedMaxScore,
      query: query.trim(),
    });
  }

  const pageStart = payload.pagination.total === 0
    ? 0
    : (payload.pagination.page - 1) * payload.pagination.page_size + 1;
  const pageEnd = Math.min(
    payload.pagination.page * payload.pagination.page_size,
    payload.pagination.total,
  );

  return (
    <div className="px-4 py-4 sm:px-6 lg:px-8">
      {/* 顶栏：紧凑选股池切换 + 右侧快捷工具栏 */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 border-b border-[#c4c8bc]/40 pb-3">
        <div className="flex items-center gap-2">
          {(['A-Pre', 'A', 'B', 'C'] as ScreeningPool[]).map((pool) => {
            const isSelected = activePool === pool;
            const labels: Record<string, { title: string; desc: string }> = {
              'A-Pre': { title: 'A-Pre 池', desc: '跌速减慢 & 筑底预备' },
              A: { title: 'A 池', desc: '超跌 & 底部分化' },
              B: { title: 'B 池', desc: '回调突破 & 主升' },
              C: { title: 'C 池', desc: '极度超跌企稳' },
            };
            return (
              <button
                key={pool}
                onClick={() => onPoolChange(pool)}
                className={`flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-bold transition ${
                  isSelected
                    ? 'bg-[#2e3230] text-white shadow-sm ring-2 ring-[#2e3230]/20'
                    : 'border border-[#c4c8bc]/50 bg-white text-[#4a4e4a] hover:bg-[#e4e0d8]'
                }`}
              >
                <span>{labels[pool].title}</span>
                <span className={`text-[10px] font-normal ${isSelected ? 'text-zinc-300' : 'text-[#686d68]'}`}>
                  ({labels[pool].desc})
                </span>
                <span className={`ml-1 rounded px-1.5 py-0.5 text-[10px] ${isSelected ? 'bg-white/20 text-white' : 'bg-[#e4e0d8] text-[#2e3230]'}`}>
                  {payload.counts[pool] || 0}只
                </span>
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => onOnlySelectedChange(!onlySelected)}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-bold transition ${
              onlySelected
                ? 'border-[#705c30] bg-[#705c30] text-white shadow-xs'
                : 'border-[#c4c8bc]/60 bg-white text-[#4a4e4a] hover:bg-[#e4e0d8]'
            }`}
          >
            <span>⭐️ 我的关注</span>
            <span className="rounded bg-black/10 px-1.5 py-0.5 text-[10px]">
              {payload.counts.selected || 0}
            </span>
          </button>

          <button
            onClick={() => setShowHistoryModal(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[#c4c8bc]/60 bg-white px-3 py-1.5 text-xs font-bold text-[#4a4e4a] hover:bg-[#e4e0d8] shadow-xs transition"
          >
            <History className="h-3.5 w-3.5 text-[#705c30]" />
            <span>📜 选股历史</span>
          </button>

          <button
            onClick={() => setShowRunModal(true)}
            disabled={running}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[#4a7c59] px-3.5 py-1.5 text-xs font-bold text-white shadow-xs hover:bg-[#3b6447] disabled:opacity-50"
          >
            {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlayCircle className="h-3.5 w-3.5" />}
            <span>{running ? `计算中 (${taskStatus?.progress || 0}%)` : '运行选股'}</span>
          </button>
        </div>
      </div>

      {/* 选股池过滤与链条统一组件 */}
      <PoolStageFunnel
        activePool={activePool}
        onOpenKline={(code, name) => setKlineModalAsset({ code, name })}
        onToggleSelect={(tsCode) => {
          const found = payload.items.find(i => i.asset_code === tsCode);
          if (found) {
            onToggleSelect(found);
          } else {
            onToggleSelect({
              trade_date: payload.trade_date,
              asset_code: tsCode,
              name: '',
              asset_type: 'stock',
              primary_pool: activePool,
              stage: 'L0',
              score: 0,
              pools: [],
              reasons: [],
              risks: [],
              status_change: '',
              features: {},
            });
          }
        }}
      />

      <RunScreeningModal
        isOpen={showRunModal}
        onClose={() => setShowRunModal(false)}
        tradeDate={payload.trade_date}
        freshnessInfo={freshnessInfo}
        onStartRun={() => onRun()}
      />

      <RunHistoryModal
        isOpen={showHistoryModal}
        onClose={() => setShowHistoryModal(false)}
        onSelectRun={(runId) => {
          setSelectedRunId(runId);
        }}
      />

      <KLineModal
        assetCode={klineModalAsset?.code || ''}
        assetName={klineModalAsset?.name || ''}
        isOpen={!!klineModalAsset}
        onClose={() => setKlineModalAsset(null)}
        onNavigatePrev={handlePrevStock}
        onNavigateNext={handleNextStock}
        hasPrev={klineModalAssetIndex > 0}
        hasNext={klineModalAssetIndex < displayedItems.length - 1}
        apiHost={API_BASE}
        isSelected={displayedItems[klineModalAssetIndex]?.is_selected || false}
        onToggleSelect={() => {
          const currentItem = displayedItems[klineModalAssetIndex];
          if (currentItem) {
            onToggleSelect(currentItem);
          }
        }}
      />
    </div>
  );
}

function CandidateRow({
  item,
  isFocused = false,
  onFocusSelect,
  onToggleSelect,
  onOpenKline,
}: {
  item: ScreeningCandidate;
  isFocused?: boolean;
  onFocusSelect?: () => void;
  onToggleSelect: (item: ScreeningCandidate) => void;
  onOpenKline: (code: string, name: string) => void;
}) {
  const detail = item.pools.find((pool) => pool.pool === item.primary_pool)?.score_detail || {};
  return (
    <div
      onClick={onFocusSelect}
      className={`grid min-w-[1020px] grid-cols-[100px_minmax(280px,1.5fr)_80px_80px_160px_minmax(220px,1fr)_100px] gap-3 border-b border-[#c4c8bc]/30 px-4 py-3 text-sm last:border-b-0 transition-colors ${
        isFocused ? 'bg-emerald-50/70 border-l-4 border-l-emerald-600 font-medium' : 'hover:bg-black/5'
      }`}
    >
      <div
        onClick={() => onOpenKline(item.asset_code, item.name || item.asset_code)}
        className="cursor-pointer group"
        title="点击查看 K 线"
      >
        <p className="font-bold text-[#2e3230] group-hover:text-[#4a7c59] underline-offset-2 group-hover:underline flex items-center gap-1">
          {item.asset_code}
          <LineChart className="w-3.5 h-3.5 text-[#4a7c59] opacity-0 group-hover:opacity-100 transition-opacity" />
        </p>
        <p className="text-xs text-[#686d68]">{item.asset_type === 'stock' ? '股票' : 'ETF'}</p>
      </div>

      {/* 名称 / 行业 / 主营业务 */}
      <div
        onClick={() => onOpenKline(item.asset_code, item.name || item.asset_code)}
        className="min-w-0 cursor-pointer group space-y-1"
        title={item.main_business ? `主营业务: ${item.main_business}` : '点击查看 K 线'}
      >
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-bold text-[#2e3230] group-hover:text-[#4a7c59]">{item.name || '未命名'}</span>
          {item.industry && (
            <span className="rounded bg-[#4a7c59]/10 px-1.5 py-0.5 text-[11px] font-bold text-[#4a7c59]">
              {item.industry}
            </span>
          )}
          {item.market && item.market !== '主板' && (
            <span className="rounded bg-[#2e3230]/10 px-1 py-0.5 text-[10px] font-bold text-[#2e3230]">
              {item.market}
            </span>
          )}
        </div>

        {item.main_business ? (
          <p className="line-clamp-2 text-xs text-[#4a4e4a] leading-relaxed bg-[#f7f5f0] p-1.5 rounded border border-[#c4c8bc]/30">
            <span className="font-bold text-[#686d68] mr-1">主营:</span>
            {item.main_business}
          </p>
        ) : (
          <p className="text-[11px] text-[#686d68] italic">暂无主营业务简介</p>
        )}
      </div>
      <div>
        <Tag tone={item.primary_pool === 'A-Pre' ? 'warning' : item.primary_pool === 'A' ? 'info' : item.primary_pool === 'B' ? 'neutral' : 'warning'}>{item.stage}</Tag>
      </div>
      <div>
        <p className="font-bold text-[#2e3230]">{item.score.toFixed(0)}</p>
        <p className="text-xs text-[#686d68]">{scoreParts(item.primary_pool, detail)}</p>
      </div>
      <KeyMetrics item={item} />
      <div className="min-w-0">
        <p className="line-clamp-2 text-sm leading-6 text-[#4a4e4a]">{item.reasons.join('；') || '暂无原因'}</p>
        {item.risks.length > 0 && <p className="mt-1 text-xs text-[#8f2927]">{item.risks.join('；')}</p>}
      </div>
      <div className="flex items-center justify-center gap-1.5">
        <button
          onClick={() => onOpenKline(item.asset_code, item.name || item.asset_code)}
          className="rounded-md border border-[#4a7c59] bg-[#4a7c59]/10 px-2 py-1 text-xs font-bold text-[#4a7c59] hover:bg-[#4a7c59]/20 transition"
          title="看 K 线"
        >
          K线
        </button>
        <button
          onClick={() => onToggleSelect(item)}
          className={`rounded-md px-2 py-1 text-xs font-bold transition ${
            item.is_selected
              ? 'bg-[#705c30] text-white hover:bg-[#5a4a27]'
              : 'border border-[#4a7c59] text-[#4a7c59] hover:bg-[#4a7c59]/10'
          }`}
        >
          {item.is_selected ? '已选' : '+入池'}
        </button>
      </div>
    </div>
  );
}

function KeyMetrics({item}: {item: ScreeningCandidate}) {
  const closePrice = typeof item.features.close === 'number' ? item.features.close : null;
  const pctChg = typeof item.features.pct_chg === 'number' ? item.features.pct_chg : null;
  const amountMa20 = typeof item.features.amount_ma20 === 'number' ? item.features.amount_ma20 : null;
  const mvStr = formatMv(item.features.total_mv);

  return (
    <div className="space-y-1 text-xs text-[#4a4e4a]">
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
      {amountMa20 !== null && amountMa20 > 0 && (
        <p className="text-[11px] text-[#686d68]">
          20日均额: <span className="font-semibold text-[#2e3230]">{formatMv(amountMa20)}</span>
        </p>
      )}
      {mvStr && <p className="text-[11px] font-semibold text-[#705c30]">市值: {mvStr}</p>}
      {item.primary_pool === 'B' ? (
        <p className="text-[11px] text-[#686d68]">120日: {formatPct(toPct(item.features.ret_120))}</p>
      ) : item.primary_pool === 'C' ? (
        <p className="text-[11px] text-[#686d68]">RSI: {formatNumber(item.features.rsi14)}</p>
      ) : (
        <p className="text-[11px] text-[#686d68]">250日: {formatPct(toPct(item.features.ret_250))}</p>
      )}
    </div>
  );
}


function formatMv(mv: any): string {
  if (typeof mv !== 'number' || !Number.isFinite(mv) || mv <= 0) return '';
  if (mv >= 10000) {
    return `${(mv / 10000).toFixed(1)}万亿`;
  }
  return `${mv.toFixed(0)}亿`;
}

function scoreParts(pool: string, detail: Record<string, number>) {
  const order: Record<string, string[]> = {
    'A-Pre': ['background', 'deceleration', 'bottom_structure', 'volatility_contraction', 'rs_and_volume'],
    A: ['long_term_decline', 'weakening', 'turning', 'position'],
    B: ['uptrend', 'pullback_health', 'stabilize', 'turning'],
    C: ['downtrend', 'oversold', 'selling_pressure', 'rebound'],
  };
  const entries = (order[pool] || Object.keys(detail))
    .filter((key) => key in detail && key !== 'total')
    .slice(0, 2)
    .map((key) => [key, detail[key]] as [string, number]);
  if (!entries.length) return '明细暂无';
  return entries.map(([key, value]) => `${scoreLabel(key)}${Math.round(value)}`).join(' / ');
}

function scoreLabel(key: string) {
  const labels: Record<string, string> = {
    background: '背景',
    deceleration: '减速',
    bottom_structure: '底部',
    volatility_contraction: '收缩',
    rs_and_volume: '量能',
    breakout_proximity: '突破',
    long_term_decline: '下降',
    weakening: '减弱',
    turning: '转强',
    position: '位置',
    uptrend: '趋势',
    pullback_health: '回撤',
    stabilize: '企稳',
    downtrend: '弱势',
    oversold: '超跌',
    selling_pressure: '卖压',
    rebound: '反弹',
  };
  return labels[key] || key;
}

function toPct(value: unknown) {
  return typeof value === 'number' ? value * 100 : null;
}

function formatNumber(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : '暂无';
}

function AIParagraph({title, text}: {title: string; text: string}) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-bold text-[#2e3230]">{title}</h3>
      <p className="text-sm leading-7 text-[#4a4e4a]">{text}</p>
    </div>
  );
}

function ClassificationItem({label, value}: {label: string; value: string}) {
  return (
    <div className="border-l-2 border-[#705c30] pl-3">
      <p className="text-xs font-bold text-[#686d68]">{label}</p>
      <p className="mt-1 text-base font-bold text-[#2e3230]">{value}</p>
    </div>
  );
}

function AIList({title, items}: {title: string; items: string[]}) {
  if (!items.length) return null;
  return (
    <div>
      <h3 className="mb-2 text-sm font-bold text-[#2e3230]">{title}</h3>
      <ul className="space-y-2 text-sm leading-6 text-[#4a4e4a]">
        {items.map((item) => <li key={item}>· {item}</li>)}
      </ul>
    </div>
  );
}

function TimeframeBlock({title, text}: {title: string; text: string}) {
  return (
    <section className="border-l-2 border-[#4a7c59] bg-white/40 px-4 py-3">
      <h2 className="text-sm font-bold text-[#2e3230]">{title}</h2>
      <p className="mt-2 text-sm leading-6 text-[#4a4e4a]">{text}</p>
    </section>
  );
}

function IndexCard({item}: {item: IndexRow}) {
  const ret = item.returns['1d'];
  const movers = item.attribution.key_constituents || [];
  return (
    <a
      href={item.quote_url}
      target="_blank"
      rel="noreferrer"
      title={`在东方财富查看${item.name} K线`}
      className="block rounded-lg border border-[#c4c8bc]/30 bg-[#f0ece4] p-4 shadow-sm transition hover:border-[#4a7c59]/50 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-[#4a7c59]/40"
    >
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <h3 className="font-bold text-[#2e3230]">{item.name}</h3>
          <p className="text-xs text-[#4a4e4a]">{item.symbol}</p>
        </div>
        <div className="flex items-center gap-2">
          {ret !== null && ret >= 0 ? <TrendingUp className="h-4 w-4 text-[#b83230]" /> : <TrendingDown className="h-4 w-4 text-[#237a4b]" />}
          <ExternalLink className="h-3.5 w-3.5 text-[#686d68]" />
        </div>
      </div>
      <p className="text-2xl font-bold">{item.close.toFixed(2)}</p>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <Metric label="当日涨跌幅" value={formatPct(item.returns['1d'])} valueClass={toneClass(item.returns['1d'])} compact />
        <Metric label="1周涨跌幅" value={formatPct(item.returns['1w'])} valueClass={toneClass(item.returns['1w'])} compact />
        <Metric label="5周涨跌幅" value={formatPct(item.returns['5w'])} valueClass={toneClass(item.returns['5w'])} compact />
        <Metric label="20周涨跌幅" value={formatPct(item.returns['20w'])} valueClass={toneClass(item.returns['20w'])} compact />
      </div>
      {item.attribution.available ? (
        <div className="mt-4 border-t border-[#c4c8bc]/50 pt-3 text-xs text-[#4a4e4a]">
          <p className="mb-2 font-bold text-[#2e3230]">
            {item.attribution.direction === 'up' ? '涨幅领先成分股' : '跌幅靠前成分股'}
          </p>
          <div className="space-y-2">
            {movers.map((stock) => (
              <div key={stock.code} className="grid grid-cols-[1fr_auto] gap-2">
                <div className="min-w-0">
                  <p className="truncate font-bold">{stock.name || stock.code}</p>
                  <p className="truncate text-[#686d68]">{stock.industry}</p>
                </div>
                <span className={`font-bold ${toneClass(stock.return_pct)}`}>{formatPct(stock.return_pct)}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </a>
  );
}

function ReturnBars({item}: {item: IndexRow}) {
  const periods = [
    ['5w', '5周'],
    ['20w', '20周'],
  ] as const;
  return (
    <div className="grid gap-3 md:grid-cols-[96px_1fr] md:items-center">
      <div>
        <p className="font-bold">{item.name}</p>
        <p className="text-xs text-[#4a4e4a]">排名 #{item.rankings['5w'] || '-'}</p>
      </div>
      <div className="space-y-2">
        {periods.map(([key, label]) => {
          const value = item.returns[key] || 0;
          const width = Math.min(Math.abs(value) * 6, 100);
          return (
            <div key={key} className="grid grid-cols-[42px_1fr_64px] items-center gap-2 text-xs">
              <span className="font-bold text-[#4a4e4a]">{label}</span>
              <div className="h-3 rounded-sm bg-[#e4e0d8]">
                <div className={`h-3 rounded-sm ${value >= 0 ? 'bg-[#b83230]' : 'bg-[#237a4b]'}`} style={{width: `${Math.max(width, 2)}%`}} />
              </div>
              <span className={`text-right font-bold ${toneClass(value)}`}>{formatPct(value)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function IndustryRanking({title, rows, tone}: {title: string; rows: IndustryRow[]; tone: 'red' | 'green'}) {
  const toneMap = {
    red: 'border-[#b83230]/30',
    green: 'border-[#237a4b]/30',
  };
  return (
    <Panel title={title} icon={<LineChart className="h-5 w-5" />} className={toneMap[tone]}>
      <div className="space-y-3">
        {rows.map((row, index) => (
          <div key={row.name} className="rounded-md bg-[#faf6f0] p-3">
            <div className="grid grid-cols-[28px_1fr_auto] items-center gap-2">
              <span className="text-xs font-bold text-[#686d68]">{index + 1}</span>
              <p className="font-bold">{row.name}</p>
              <span className={`text-sm font-bold ${toneClass(row.summary_change_pct)}`}>{formatPct(row.summary_change_pct)}</span>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function Panel({title, icon, children, className = ''}: {title: string; icon: ReactNode; children: ReactNode; className?: string}) {
  return (
    <section className={`rounded-lg border border-[#c4c8bc]/30 bg-[#f0ece4] p-5 shadow-sm ${className}`}>
      <h2 className="mb-5 flex items-center gap-2 font-[family-name:var(--font-literata)] text-lg font-bold">
        <span className="text-[#4a7c59]">{icon}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function Metric({label, value, valueClass = '', compact = false}: {label: string; value: string; valueClass?: string; compact?: boolean}) {
  return (
    <div className={compact ? '' : 'rounded-md bg-[#faf6f0] p-3'}>
      <p className="text-[11px] font-bold uppercase tracking-wider text-[#4a4e4a]">{label}</p>
      <p className={`mt-1 font-bold ${compact ? 'text-sm' : 'text-xl'} ${valueClass}`}>{value}</p>
    </div>
  );
}

function Tag({children, tone}: {children: ReactNode; tone: 'warning' | 'info' | 'neutral'}) {
  const classes = {
    warning: 'bg-[#705c30]/15 text-[#705c30]',
    info: 'bg-[#4a7c59]/15 text-[#4a7c59]',
    neutral: 'bg-[#e4e0d8] text-[#4a4e4a]',
  };
  return <span className={`rounded-full px-3 py-1 text-xs font-bold ${classes[tone]}`}>{children}</span>;
}

function LoadingState({label = '正在读取数据'}: {label?: string}) {
  return (
    <div className="flex min-h-[420px] items-center justify-center">
      <div className="flex items-center gap-3 rounded-lg border border-[#c4c8bc]/30 bg-[#f0ece4] px-5 py-4 font-bold text-[#4a4e4a]">
        <Loader2 className="h-5 w-5 animate-spin" />
        {label}
      </div>
    </div>
  );
}

function ErrorState({message, onRetry}: {message: string; onRetry: () => void}) {
  return (
    <div className="flex min-h-[420px] items-center justify-center px-6">
      <div className="max-w-2xl rounded-lg border border-[#b83230]/30 bg-[#f0ece4] p-6">
        <div className="mb-3 flex items-center gap-2 text-[#b83230]">
          <AlertTriangle className="h-5 w-5" />
          <h1 className="font-bold">数据读取失败</h1>
        </div>
        <p className="break-words text-sm text-[#4a4e4a]">{message}</p>
        <button onClick={onRetry} className="mt-5 inline-flex items-center gap-2 rounded-md bg-[#4a7c59] px-4 py-2 text-sm font-bold text-white">
          <RefreshCw className="h-4 w-4" />
          重试
        </button>
      </div>
    </div>
  );
}
