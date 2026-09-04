'use client';

import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
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
  RefreshCw,
  Database,
  BarChart2,
  Sparkles,
  Star,
  History,
  Trash2,
  TestTube2,
  Download,
} from 'lucide-react';
import SecondaryStockDetailDrawer from './SecondaryStockDetailDrawer';
import SingleStockTestView from './SingleStockTestView';
import { downloadSingleStockMarkdown } from './singleStockMarkdown';

type EarlyTurnState = 'ALL' | 'PRE_FIRST_TURN' | 'FIRST_TURN_WINDOW' | 'POST_FIRST_WAVE';
type BackgroundType = 'ALL' | 'REVERSAL_BASE' | 'CONSOLIDATION_RESTART' | 'UNKNOWN';
type FundamentalFilterState = 'ALL' | 'FUNDAMENTAL_ACCEPTABLE' | 'FUNDAMENTAL_POSITIVE' | 'FUNDAMENTAL_RISK' | 'FUNDAMENTAL_DATA_INSUFFICIENT' | 'UNRESEARCHED';

interface EarlyTurnStockItem {
  run_id: string;
  ts_code: string;
  trade_date: string;
  name?: string;
  industry?: string;
  main_business?: string;
  total_score: number;
  state: EarlyTurnState;
  turn_episode_state?: string;
  signal_status?: string;
  entry_extension_state?: string;
  first_trigger_date?: string;
  first_trigger_close?: number;
  return_since_first_trigger?: number;
  structural_damage_flag?: boolean;
  background_type: BackgroundType;
  selected: boolean;
  is_overextended: boolean;
  first_selected_date?: string;
  features_json?: Record<string, any>;
  score_detail_json?: Record<string, any>;
  reasons_json?: Array<{ type: string; msg: string }>;
  ths_concepts?: string[];
  concepts?: string[];
  hot_theme_matches?: Array<{ canonical_name: string; matched_concept?: string; status?: string }>;
  financial_facts?: Record<string, any>;
}

interface HotThemeOption {
  canonical_name: string;
  status: string;
  match_count: number;
  first_seen_date?: string;
  last_active_date?: string;
}

interface SecondaryMetricItem {
  ts_code: string;
  evidence_state?: string | null;
  fundamental_filter_state?: FundamentalFilterState | null;
  fundamental_filter_reasons_json?: string[];
  revenue_yoy?: number | string | null;
  parent_net_profit_yoy?: number | string | null;
  forecast_type?: string | null;
  quarter_facts_json?: QuarterFact[];
  fact_tags_json?: FactTag[];
  data_quality_json?: DataQuality;
  leadership_state?: string | null;
  free_float_mv?: number | string | null;
  amount_median_20?: number | string | null;
  turnover_rate_f?: number | string | null;
  unlock_30d?: number | string | null;
  unlock_60d?: number | string | null;
  unlock_90d?: number | string | null;
  recent_reduction_flag?: boolean | null;
  supply_profile_label?: string | null;
  ai_status?: string | null;
  ai_priority?: string | null;
  ai_input_tokens?: number | null;
  ai_output_tokens?: number | null;
  ai_total_tokens?: number | null;
  ai_elapsed_ms?: number | null;
  web_search_used?: boolean | null;
}

interface QuarterFact {
  period?: string | null;
  quarter?: string | null;
  available_date?: string | null;
  revenue?: number | string | null;
  revenue_qoq?: number | string | null;
  revenue_yoy?: number | string | null;
  parent_net_profit?: number | string | null;
  parent_net_profit_qoq?: number | string | null;
  parent_net_profit_yoy?: number | string | null;
  operating_cashflow?: number | string | null;
  operating_cashflow_qoq?: number | string | null;
  operating_cashflow_yoy?: number | string | null;
}

interface FactTag {
  label?: string;
  tone?: string;
  support?: any;
}

interface DataQuality {
  quarter_count?: number;
  missing_fields?: string[];
  notes?: string[];
}

interface EarlyTurnResponse {
  total: number;
  counts: Record<string, number>;
  industry_counts?: Record<string, number>;
  concept_counts?: Record<string, number>;
  concept_snapshot_date?: string;
  hot_theme_options?: HotThemeOption[];
  hot_theme_snapshot_date?: string;
  fundamental_counts?: Record<string, number>;
  items: EarlyTurnStockItem[];
  page: number;
  page_size: number;
}

interface EarlyTurnTaskStatus {
  status: 'idle' | 'queued' | 'running' | 'success' | 'failed' | string;
  progress?: number;
  step_message?: string;
  trade_date?: string;
  run_id?: string | null;
  candidate_count?: number;
  error?: string | null;
}

interface SecondaryMetricsIssue {
  code?: string;
  message: string;
  early_turn_count?: number;
  secondary_snapshot_count?: number;
  candidate_scope?: string[];
}

const getApiBase = (): string => {
  if (process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL) {
    return process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;
  }
  if (typeof window !== 'undefined' && window.location?.hostname) {
    return `${window.location.protocol}//${window.location.hostname}:18080`;
  }
  return 'http://127.0.0.1:18080';
};

const API_BASE = getApiBase();

const safeFetch = async (url: string, options?: RequestInit): Promise<Response | null> => {
  try {
    const res = await fetch(url, options);
    return res;
  } catch (e) {
    if (url.includes('127.0.0.1:18080')) {
      const altUrl = url.replace('127.0.0.1:18080', 'localhost:18080');
      try { return await fetch(altUrl, options); } catch (_) {}
    } else if (url.includes('localhost:18080')) {
      const altUrl = url.replace('localhost:18080', '127.0.0.1:18080');
      try { return await fetch(altUrl, options); } catch (_) {}
    }
    return null;
  }
};

const toNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const num = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(num) ? num : null;
};

const formatRatioPercent = (value: unknown, digits = 1): string => {
  const num = toNumber(value);
  if (num === null) return '缺失';
  return `${(num * 100).toFixed(digits)}%`;
};

const formatRawPercent = (value: unknown, digits = 1): string => {
  const num = toNumber(value);
  if (num === null) return '缺失';
  return `${num.toFixed(digits)}%`;
};

const formatMoneyYi = (value: unknown): string => {
  const num = toNumber(value);
  if (num === null) return '缺失';
  return `${num.toFixed(1)}亿`;
};

const formatAmountWan = (value: unknown): string => {
  const num = toNumber(value);
  if (num === null) return '缺失';
  if (Math.abs(num) >= 100000000) return `${(num / 100000000).toFixed(1)}亿`;
  if (Math.abs(num) >= 10000) return `${(num / 10000).toFixed(0)}万`;
  return num.toFixed(0);
};

const formatAmountCompact = (value: unknown): string => {
  const num = toNumber(value);
  if (num === null) return '缺失';
  if (Math.abs(num) >= 100000000) return `${(num / 100000000).toFixed(1)}亿`;
  if (Math.abs(num) >= 10000) return `${(num / 10000).toFixed(0)}万`;
  return `${num.toFixed(0)}`;
};

const formatSignedRatio = (value: unknown): string => {
  const num = toNumber(value);
  if (num === null) return '环比缺失';
  return `环比 ${num >= 0 ? '+' : ''}${(num * 100).toFixed(1)}%`;
};

const supplyLabelText = (value?: string | null): string => {
  const map: Record<string, string> = {
    MICRO_ELASTIC: '微盘弹性',
    SMALL_ELASTIC: '小盘弹性',
    MID_CAP: '中等容量',
    LARGE_CAPACITY: '大容量',
    MEGA_CAPACITY: '超大容量',
    DATA_MISSING: '数据缺失',
  };
  return value ? (map[value] || value) : '缺失';
};

const factTagTone = (tag: FactTag): string => {
  if (tag.tone === 'POSITIVE') return 'bg-emerald-50 text-emerald-800 border-emerald-200';
  if (tag.tone === 'RISK') return 'bg-rose-50 text-rose-800 border-rose-200';
  return 'bg-amber-50 text-amber-900 border-amber-200';
};

const metricTone = (value: unknown, mode: 'ratio' | 'percent' | 'boolean' = 'ratio') => {
  if (value === null || value === undefined || value === '') return 'bg-slate-100 text-slate-500 border-slate-200';
  if (mode === 'boolean') return value ? 'bg-rose-50 text-rose-800 border-rose-200' : 'bg-emerald-50 text-emerald-800 border-emerald-200';
  const num = toNumber(value);
  if (num === null) return 'bg-slate-100 text-slate-500 border-slate-200';
  if (num > 0) return 'bg-emerald-50 text-emerald-800 border-emerald-200';
  if (num < 0) return 'bg-rose-50 text-rose-800 border-rose-200';
  return mode === 'percent' ? 'bg-blue-50 text-blue-800 border-blue-200' : 'bg-slate-100 text-slate-700 border-slate-200';
};

const fundamentalFilterLabel = (state?: string | null): string => ({
  FUNDAMENTAL_ACCEPTABLE: '可接受',
  FUNDAMENTAL_POSITIVE: '经营向好',
  FUNDAMENTAL_RISK: '存在风险',
  FUNDAMENTAL_DATA_INSUFFICIENT: '数据不足',
  UNRESEARCHED: '未研究',
}[state || ''] || '未研究');

const fundamentalFilterTone = (state?: string | null): string => {
  if (state === 'FUNDAMENTAL_POSITIVE') return 'bg-emerald-50 text-emerald-800 border-emerald-200';
  if (state === 'FUNDAMENTAL_ACCEPTABLE') return 'bg-sky-50 text-sky-800 border-sky-200';
  if (state === 'FUNDAMENTAL_RISK') return 'bg-rose-50 text-rose-800 border-rose-200';
  return 'bg-slate-100 text-slate-600 border-slate-200';
};

const MetricChip = ({ label, value, tone }: { label: string; value: string; tone: string }) => (
  <span className={`metric-chip inline-flex w-fit max-w-full items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-black leading-tight ${tone}`}>
    <span className="text-current/65">{label}</span>
    <span className="truncate">{value}</span>
  </span>
);

const lowSignalConcepts = new Set([
  '融资融券',
  '沪股通',
  '深股通',
  '富时罗素',
  '标普道琼斯A股',
  'MSCI概念',
  '转融券标的',
  '证金持股',
  '地方国企改革',
]);

const isLowSignalConcept = (name: string) => {
  return lowSignalConcepts.has(name) || /融资融券|沪股通|深股通|陆股通|MSCI|富时罗素|标普|同花顺|样本股|成份股|成分股|全A|沪深|A股|指数|大盘|中盘|小盘|高估值|低估值|高动量|低动量|高盈利|低盈利|均衡|保守投资|激进投资|昨日|近期|百日新高|高贝塔|股性|减持|增发|可转债|基金重仓|保险重仓|社保重仓|城市群|都市圈|华东|华南|华北|华中|西南|西北|东北|广东|江苏|浙江|上海|深圳|北京|河北|湖北/.test(name);
};

const sortConceptTags = (tags: string[]) => {
  return [...new Set(tags.filter(Boolean))]
    .sort((a, b) => {
      const aLow = isLowSignalConcept(a);
      const bLow = isLowSignalConcept(b);
      if (aLow !== bLow) return aLow ? 1 : -1;
      return a.localeCompare(b, 'zh-CN');
    });
};

export default function EarlyTurnFunnel() {
  // 自动选股页面会在切换到单股测试/自选股时卸载。筛选条件和当前批次
  // 需要在页面卸载期间保留，回来后恢复后再按同一条件重新请求列表。
  const funnelSessionKey = 'early_turn_funnel_session_v1';
  const sessionHydratedRef = useRef(false);
  const restoredRunRef = useRef(false);
  const lastFilterRunIdRef = useRef<string | null>(null);
  const [sessionReady, setSessionReady] = useState(false);
  // AI 分析池与 7-Tab 细节抽屉状态
  const [aiPoolCodes, setAiPoolCodes] = useState<string[]>([]);
  const [showAiPoolDrawer, setShowAiPoolDrawer] = useState(false);
  const [detailStock, setDetailStock] = useState<{ tsCode: string; stockName: string; initialTab: 'detail' | 'kline' } | null>(null);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [exportingSingleStockCode, setExportingSingleStockCode] = useState<string | null>(null);
  const [aiResearchRunningCodes, setAiResearchRunningCodes] = useState<string[]>([]);

  // 异步 AI 队列状态 (非阻断式)
  const [aiQueueRunning, setAiQueueRunning] = useState(false);
  const [aiProcessingCode, setAiProcessingCode] = useState<string | null>(null);
  const [aiCompletedCodes, setAiCompletedCodes] = useState<string[]>([]);
  const [aiStatuses, setAiStatuses] = useState<Record<string, { status: 'queued' | 'running' | 'success' | 'failed'; error?: string }>>({});
  const cancelAiQueueRef = useRef(false);

  // 自选股状态 (PostgreSQL 存储)
  const [watchlistCodes, setWatchlistCodes] = useState<string[]>([]);

  const copyStockText = useCallback(async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setToastMsg(`已复制${label}：${value}`);
      setTimeout(() => setToastMsg(null), 2000);
    } catch {
      setToastMsg(`复制${label}失败，请手动选择复制`);
      setTimeout(() => setToastMsg(null), 2500);
    }
  }, []);

  const fetchWatchlistCodes = useCallback(async () => {
    try {
      const baseUrl = getApiBase();
      const res = await safeFetch(`${baseUrl}/api/watchlist/stocks`);
      if (res && res.ok) {
        const data = await res.json();
        setWatchlistCodes(data.watchlist_codes || []);
      }
    } catch (e) {}
  }, []);

  useEffect(() => {
    fetchWatchlistCodes();
  }, [fetchWatchlistCodes]);

  const toggleWatchlist = async (code: string) => {
    const candidate = currentItems.find((item) => item.ts_code === code);
    const source = candidate
      ? {
          type: 'STRATEGY',
          strategy: 'A_PREV2',
          stage: candidate.state,
          snapshot_date: candidate.trade_date,
        }
      : { type: 'MANUAL' };
    // 乐观式即时更新界面状态
    setWatchlistCodes((prev) => {
      const isCurrentlyIn = prev.includes(code);
      const nextList = isCurrentlyIn ? prev.filter((c) => c !== code) : [...prev, code];
      setToastMsg(!isCurrentlyIn ? `已将 ${code} 加入自选股` : `已将 ${code} 移出自选股`);
      setTimeout(() => setToastMsg(null), 2000);
      return nextList;
    });
    try {
      const baseUrl = getApiBase();
      const res = await safeFetch(`${baseUrl}/api/watchlist/stocks/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asset_code: code, source }),
      });
      if (res && res.ok) {
        const data = await res.json();
        if (Array.isArray(data.watchlist_codes)) {
          setWatchlistCodes(data.watchlist_codes);
        }
      }
    } catch (e) {
      console.warn('Failed to toggle watchlist:', e);
    }
  };

  // AI 分析池与自选股统一由 PostgreSQL 持久化
  useEffect(() => {
    safeFetch(`${getApiBase()}/api/watchlist/ai-pool`)
      .then((res) => res?.ok ? res.json() : null)
      .then((data) => { if (data && Array.isArray(data.codes)) setAiPoolCodes(data.codes); })
      .catch((e) => setToastMsg(e instanceof Error ? e.message : 'AI 分析池读取失败'));
  }, []);

  const toggleAiPool = async (tsCode: string) => {
    const res = await safeFetch(`${getApiBase()}/api/watchlist/ai-pool/toggle`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ asset_code: tsCode }) });
    if (!res || !res.ok) throw new Error('AI 分析池操作失败');
    const data = await res.json();
    setAiPoolCodes(data.codes || []);
    setToastMsg(data.in_pool ? `已加入 AI 分析池 (共 ${data.codes.length} 只)` : `已移出 AI 分析池 (还剩 ${data.codes.length} 只)`);
    setTimeout(() => setToastMsg(null), 2000);
  };

  const addAllCurrentToAiPool = async () => {
    if (!data?.items) return;
    const currentCodes = data.items.map((i) => i.ts_code);
    const newPool = Array.from(new Set([...aiPoolCodes, ...currentCodes]));
    const res = await safeFetch(`${getApiBase()}/api/watchlist/ai-pool`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ codes: newPool }) });
    if (!res || !res.ok) throw new Error('AI 分析池批量加入失败');
    const saved = await res.json();
    setAiPoolCodes(saved.codes || []);
    setToastMsg(`已将当前 ${currentCodes.length} 只股票加入 AI 分析池 (共 ${newPool.length} 只)`);
    setTimeout(() => setToastMsg(null), 2000);
  };

  const clearAiPool = async () => {
    const res = await safeFetch(`${getApiBase()}/api/watchlist/ai-pool`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ codes: [] }) });
    if (!res || !res.ok) throw new Error('AI 分析池清空失败');
    setAiPoolCodes([]);
    setToastMsg('AI 分析池已清空');
    setTimeout(() => setToastMsg(null), 2000);
  };
const getTodayTradeDateStr = (): string => {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}${mm}${dd}`;
};

  const [tradeDate, setTradeDate] = useState<string>(getTodayTradeDateStr());

  // 列表直接导出与“单股测试”相同格式的报告，评估截止日使用当前批次快照日。
  const exportSingleStockData = useCallback(async (code: string, name?: string) => {
    if (exportingSingleStockCode) return;
    const endDate = String(tradeDate || '').replace(/-/g, '');
    if (!/^\d{8}$/.test(endDate)) {
      setToastMsg('当前批次没有有效的快照日，无法导出单股数据');
      setTimeout(() => setToastMsg(null), 2500);
      return;
    }
    const end = new Date(Date.UTC(Number(endDate.slice(0, 4)), Number(endDate.slice(4, 6)) - 1, Number(endDate.slice(6, 8))));
    end.setUTCMonth(end.getUTCMonth() - 1);
    const startDate = `${end.getUTCFullYear()}${String(end.getUTCMonth() + 1).padStart(2, '0')}${String(end.getUTCDate()).padStart(2, '0')}`;
    setExportingSingleStockCode(code);
    try {
      const params = new URLSearchParams({ strategy_id: 'A_PRE_V2', ts_code: code, start_date: startDate, end_date: endDate });
      const res = await safeFetch(`${getApiBase()}/api/strategy/single-stock/eval?${params.toString()}`);
      const body = res ? await res.json().catch(() => ({})) : {};
      if (!res || !res.ok) {
        throw new Error(typeof body?.detail === 'string' ? body.detail : `单股数据导出失败（HTTP ${res?.status || 'Network Error'}）`);
      }
      if (!Array.isArray(body.history) || body.history.length === 0) {
        throw new Error(`${code} 在 ${startDate} 至 ${endDate} 没有可导出的日线数据`);
      }
      downloadSingleStockMarkdown(body);
      setToastMsg(`${code}${name ? ` ${name}` : ''} 的单股数据已导出`);
      setTimeout(() => setToastMsg(null), 2500);
    } catch (e) {
      setToastMsg(e instanceof Error ? e.message : '单股数据导出失败');
      setTimeout(() => setToastMsg(null), 3000);
    } finally {
      setExportingSingleStockCode(null);
    }
  }, [exportingSingleStockCode, tradeDate]);

  // 分析池状态按交易日恢复；只查询已有结果，不会触发新的 AI 调用。
  useEffect(() => {
    if (!showAiPoolDrawer || !tradeDate || aiPoolCodes.length === 0) return;
    const statusKey = `ai_analysis_pool_status_${tradeDate}`;
    try {
      const stored = JSON.parse(localStorage.getItem(statusKey) || '{}');
      if (stored && typeof stored === 'object') setAiStatuses((prev) => ({ ...stored, ...prev }));
    } catch {}
    let cancelled = false;
    (async () => {
      const baseUrl = getApiBase();
      const results = await Promise.all(aiPoolCodes.map(async (code) => {
        const res = await safeFetch(`${baseUrl}/api/ai/stock-research/${encodeURIComponent(code)}?date=${encodeURIComponent(tradeDate)}`);
        if (!res || !res.ok) return [code, null] as const;
        const body = await res.json().catch(() => ({}));
        return [code, body?.result?.status === 'READY' ? { status: 'success' as const } : null] as const;
      }));
      if (cancelled) return;
      setAiStatuses((prev) => {
        const next = { ...prev };
        for (const [code, status] of results) if (status) next[code] = status;
        return next;
      });
    })();
    return () => { cancelled = true; };
  }, [showAiPoolDrawer, tradeDate, aiPoolCodes]);

  useEffect(() => {
    if (!tradeDate || Object.keys(aiStatuses).length === 0) return;
    localStorage.setItem(`ai_analysis_pool_status_${tradeDate}`, JSON.stringify(aiStatuses));
  }, [tradeDate, aiStatuses]);
  const [runId, setRunId] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loadingRun, setLoadingRun] = useState(false);
  const [runningTask, setRunningTask] = useState(false);
  const [earlyTurnTask, setEarlyTurnTask] = useState<EarlyTurnTaskStatus | null>(null);

  const openNewRunConfig = useCallback(async () => {
    try {
      const baseUrl = getApiBase();
      const res = await safeFetch(`${baseUrl}/api/screening/freshness`);
      if (!res || !res.ok) {
        throw new Error(`无法读取可用行情日期（HTTP ${res?.status || 'Network Error'}）`);
      }
      const freshness = await res.json();
      const targetDate = String(freshness?.official_daily_date || '').replace(/-/g, '');
      if (!/^\d{8}$/.test(targetDate)) {
        throw new Error('当前没有可用于技术选股的完整日线交易日');
      }
      setUniverseType('ALL');
      setModalTradeDate(targetDate);
      setNewRunName(`${targetDate} 早期转强选股`);
      setNewRunNotes('');
      setShowRunConfigModal(true);
    } catch (e) {
      setToastMsg(e instanceof Error ? e.message : '无法读取可用行情日期');
    }
  }, []);

  // 多选股结果标签页 & 历史选股管理状态
  const [historyRuns, setHistoryRuns] = useState<Array<{
    run_id: string;
    trade_date: string;
    run_name: string;
    notes: string;
    started_at?: string;
    candidate_count?: number;
  }>>([]);
  const [openedTabs, setOpenedTabs] = useState<Array<{
    run_id: string;
    run_name: string;
    trade_date: string;
  }>>([]);
  const [activeTabRunId, setActiveTabRunId] = useState<string>('LATEST');
  const [showHistoryModal, setShowHistoryModal] = useState(false);
  const [showHistoryDropdown, setShowHistoryDropdown] = useState(false);
  const historyDropdownRef = useRef<HTMLDivElement | null>(null);
  const [showRunConfigModal, setShowRunConfigModal] = useState(false);
  const [modalTradeDate, setModalTradeDate] = useState<string>(getTodayTradeDateStr());
  const [newRunName, setNewRunName] = useState('');
  const [newRunNotes, setNewRunNotes] = useState('');
  const [universeType, setUniverseType] = useState<'ALL' | 'CONCEPTS' | 'CUSTOM_CODES'>('ALL');
  const [conceptInput, setConceptInput] = useState('');
  const [selectedConcepts, setSelectedConcepts] = useState<string[]>([]);
  const [conceptSearch, setConceptSearch] = useState('');
  const [systemConcepts, setSystemConcepts] = useState<string[]>([]);
  const [customCodes, setCustomCodes] = useState('');

  // 首次挂载时恢复上一次离开页面时的批次与筛选条件。
  useEffect(() => {
    try {
      const raw = localStorage.getItem(funnelSessionKey);
      const saved = raw ? JSON.parse(raw) : null;
      if (!saved || typeof saved !== 'object') {
        sessionHydratedRef.current = true;
        return;
      }
      if (Array.isArray(saved.openedTabs)) setOpenedTabs(saved.openedTabs);
      if (typeof saved.activeTabRunId === 'string') setActiveTabRunId(saved.activeTabRunId);
      if (typeof saved.runId === 'string' && saved.runId) {
        setRunId(saved.runId);
        restoredRunRef.current = true;
      }
      if (typeof saved.tradeDate === 'string' && saved.tradeDate) setTradeDate(saved.tradeDate);
      if (saved.activeState) setActiveState(saved.activeState);
      if (saved.activeBg) setActiveBg(saved.activeBg);
      if (typeof saved.selectedIndustry === 'string') setSelectedIndustry(saved.selectedIndustry);
      if (typeof saved.selectedConcept === 'string') setSelectedConcept(saved.selectedConcept);
      if (typeof saved.selectedHotTheme === 'string') setSelectedHotTheme(saved.selectedHotTheme);
      if (typeof saved.minScore === 'string') {
        setMinScore(saved.minScore);
        setAppliedMinScore(typeof saved.appliedMinScore === 'string' ? saved.appliedMinScore : saved.minScore.trim());
      }
      if (typeof saved.searchQuery === 'string') {
        setSearchQuery(saved.searchQuery);
        setAppliedSearchQuery(typeof saved.appliedSearchQuery === 'string' ? saved.appliedSearchQuery : saved.searchQuery.trim());
      }
      if (typeof saved.excludeSt === 'boolean') setExcludeSt(saved.excludeSt);
      if (saved.fundamentalFilter) setFundamentalFilter(saved.fundamentalFilter);
    } catch (e) {
      console.warn('Failed to restore early turn funnel session:', e);
    } finally {
      sessionHydratedRef.current = true;
      setSessionReady(true);
    }
  }, []);

  // 自动获取数据库中全量同花顺概念板块列表
  useEffect(() => {
    const fetchSystemConcepts = async () => {
      try {
        const baseUrl = getApiBase();
        const res = await safeFetch(`${baseUrl}/api/data/ths-concepts`);
        if (res && res.ok) {
          const json = await res.json();
          if (Array.isArray(json.concepts) && json.concepts.length > 0) {
            const list = json.concepts.map((c: any) => c.name).filter(Boolean);
            setSystemConcepts(list);
          }
        }
      } catch (e) {
        console.warn('Failed to load system THS concepts:', e);
      }
    };
    fetchSystemConcepts();
  }, []);

  // 匹配和搜索过滤的概念列表
  const filteredConceptsList = useMemo(() => {
    if (!conceptSearch.trim()) return systemConcepts;
    const query = conceptSearch.trim().toLowerCase();
    return systemConcepts.filter((c) => c.toLowerCase().includes(query));
  }, [systemConcepts, conceptSearch]);

  useEffect(() => {
    if (!showHistoryDropdown) return;
    const handlePointerDown = (e: MouseEvent) => {
      if (historyDropdownRef.current && !historyDropdownRef.current.contains(e.target as Node)) {
        setShowHistoryDropdown(false);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [showHistoryDropdown]);

  const deleteHistoryRun = async (targetRunId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const baseUrl = getApiBase();
      const res = await safeFetch(`${baseUrl}/api/early-turn/runs/${targetRunId}`, { method: 'DELETE' });
      if (res && res.ok) {
        const body = await res.json().catch(() => ({}));
        const deletedCount = Number(body?.deleted_result_count || 0);
        setHistoryRuns((prev) => prev.filter((r) => r.run_id !== targetRunId));
        closeHistoryTab(targetRunId);
        setToastMsg(`已删除该批次及 ${deletedCount} 条股票快照`);
        setTimeout(() => setToastMsg(null), 2000);
      } else {
        setToastMsg('删除选股快照失败');
        setTimeout(() => setToastMsg(null), 2000);
      }
    } catch (err) {
      console.warn('Delete run error:', err);
      setToastMsg('删除选股快照失败');
      setTimeout(() => setToastMsg(null), 2000);
    }
  };

  // 查全量历史选股批次
  const fetchHistoryRuns = useCallback(async () => {
    try {
      const baseUrl = getApiBase();
      const res = await safeFetch(`${baseUrl}/api/early-turn/runs`);
      if (res && res.ok) {
        const data = await res.json();
        setHistoryRuns(data.runs || []);
      }
    } catch (e) {
      console.warn('Fetch history runs error:', e);
    }
  }, []);

  useEffect(() => {
    fetchHistoryRuns();
  }, [fetchHistoryRuns]);

  // 打开历史选股 Tab
  const openHistoryTab = (run: { run_id: string; run_name: string; trade_date: string }) => {
    const formattedName = run.run_name || `${run.trade_date} 选股`;
    setOpenedTabs((prev) => {
      if (prev.some((t) => t.run_id === run.run_id)) return prev;
      return [...prev, { ...run, run_name: formattedName }];
    });
    setActiveTabRunId(run.run_id);
    setRunId(run.run_id);
    if (run.trade_date) setTradeDate(run.trade_date);
    setShowHistoryModal(false);
  };

  // 关闭历史选股 Tab
  const closeHistoryTab = (targetRunId: string) => {
    setOpenedTabs((prev) => {
      const closingIndex = prev.findIndex((t) => t.run_id === targetRunId);
      const next = prev.filter((t) => t.run_id !== targetRunId);
      if (activeTabRunId === targetRunId) {
        if (next.length > 0) {
          const nextActiveIndex = Math.min(Math.max(0, closingIndex - 1), next.length - 1);
          const nextTab = next[nextActiveIndex];
          setActiveTabRunId(nextTab.run_id);
          setRunId(nextTab.run_id);
          if (nextTab.trade_date) setTradeDate(nextTab.trade_date);
        } else {
          setActiveTabRunId('EMPTY');
          setRunId(null);
        }
      }
      return next;
    });
  };

  // Filters
  const [activeState, setActiveState] = useState<EarlyTurnState>('ALL');
  const [activeBg, setActiveBg] = useState<BackgroundType>('ALL');
  const [selectedIndustry, setSelectedIndustry] = useState<string>('ALL');
  const [selectedConcept, setSelectedConcept] = useState<string>('ALL');
  const [selectedHotTheme, setSelectedHotTheme] = useState('ALL');
  const [hotThemeOptions, setHotThemeOptions] = useState<HotThemeOption[]>([]);
  const [hotThemeIssue, setHotThemeIssue] = useState<string | null>(null);
  const [industryShowCount, setIndustryShowCount] = useState<number>(8);
  const [industrySearchQuery, setIndustrySearchQuery] = useState<string>('');
  const [showIndustryDropdown, setShowIndustryDropdown] = useState<boolean>(false);
  const [conceptShowCount, setConceptShowCount] = useState<number>(12);
  const [conceptSearchQuery, setConceptSearchQuery] = useState<string>('');
  const [showConceptDropdown, setShowConceptDropdown] = useState<boolean>(false);
  const [minScore, setMinScore] = useState<string>('');
  const [appliedMinScore, setAppliedMinScore] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [appliedSearchQuery, setAppliedSearchQuery] = useState<string>('');
  const [excludeSt, setExcludeSt] = useState<boolean>(false);
  const [fundamentalFilter, setFundamentalFilter] = useState<FundamentalFilterState>('ALL');
  const [secondaryRunLoading, setSecondaryRunLoading] = useState(false);

  // 只保存界面状态，不保存列表数据；列表回来后由当前批次和筛选条件重新读取，
  // 避免浏览器缓存了过期快照。
  useEffect(() => {
    if (!sessionHydratedRef.current || !sessionReady) return;
    try {
      localStorage.setItem(funnelSessionKey, JSON.stringify({
        runId,
        activeTabRunId,
        openedTabs,
        tradeDate,
        activeState,
        activeBg,
        selectedIndustry,
        selectedConcept,
        selectedHotTheme,
        minScore,
        appliedMinScore,
        searchQuery,
        appliedSearchQuery,
        excludeSt,
        fundamentalFilter,
      }));
    } catch (e) {
      console.warn('Failed to persist early turn funnel session:', e);
    }
  }, [sessionReady, runId, activeTabRunId, openedTabs, tradeDate, activeState, activeBg, selectedIndustry, selectedConcept, selectedHotTheme, minScore, appliedMinScore, searchQuery, appliedSearchQuery, excludeSt, fundamentalFilter]);

  // Pagination & List data
  const [data, setData] = useState<EarlyTurnResponse | null>(null);
  const [loadingStocks, setLoadingStocks] = useState(false);
  const [secondaryMetrics, setSecondaryMetrics] = useState<Record<string, SecondaryMetricItem>>({});
  const [loadingSecondaryMetrics, setLoadingSecondaryMetrics] = useState(false);
  const [secondaryMetricsError, setSecondaryMetricsError] = useState<string | null>(null);
  const [secondaryMetricsIssue, setSecondaryMetricsIssue] = useState<SecondaryMetricsIssue | null>(null);
  const [secondaryMetricsDate, setSecondaryMetricsDate] = useState<string>('');
  const [page, setPage] = useState(1);
  // 列表请求可能在网络较慢时乱序返回。只允许当前筛选条件发出的最新请求更新界面，
  // 避免输入框已经是新代码、列表却被旧请求覆盖的错配。
  const stockRequestVersionRef = useRef(0);
  const currentStockCodes = useMemo(
    () => (data?.items || []).map((item) => item.ts_code).filter(Boolean),
    [data?.items]
  );
  const industryDropdownRef = useRef<HTMLDivElement | null>(null);
  const conceptDropdownRef = useRef<HTMLDivElement | null>(null);
  const industryDropdownButtonRef = useRef<HTMLButtonElement | null>(null);
  const conceptDropdownButtonRef = useRef<HTMLButtonElement | null>(null);
  const [industryDropdownPosition, setIndustryDropdownPosition] = useState<{ left: number; top: number; width: number } | null>(null);
  const [conceptDropdownPosition, setConceptDropdownPosition] = useState<{ left: number; top: number; width: number } | null>(null);

  // 输入框保持编辑态，用户停顿后才提交筛选，避免输入 75 或完整股票代码时逐字请求。
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setAppliedMinScore(minScore.trim());
      setPage(1);
    }, 700);
    return () => window.clearTimeout(timer);
  }, [minScore]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setAppliedSearchQuery(searchQuery.trim());
      setPage(1);
    }, 700);
    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  // 当前列表中打开抽屉的股票；左右键严格沿用列表顺序。
  const [selectedStockIndex, setSelectedStockIndex] = useState<number | null>(null);

  // 1. Fetch latest run info
  const loadLatestRun = useCallback(async (targetDate?: string) => {
    setLoadingRun(true);
    try {
      // 若上次离开页面时已有明确的批次，优先恢复它；否则才读取最新批次。
      // 这样切到其他模块再回来不会被“最新批次”覆盖当前正在复盘的批次。
      if (!targetDate && restoredRunRef.current) {
        return;
      }
      const baseUrl = getApiBase();
      const url = targetDate
        ? `${baseUrl}/api/early-turn/latest?trade_date=${targetDate}`
        : `${baseUrl}/api/early-turn/latest`;
      const res = await safeFetch(url);
      if (res && res.ok) {
        const runInfo = await res.json();
        if (runInfo.trade_date) setTradeDate(runInfo.trade_date);
        if (runInfo.run_id) {
          setRunId(runInfo.run_id);
          const tabName = runInfo.run_name || `${runInfo.trade_date} 选股`;
          setOpenedTabs((prev) => {
            if (prev.some((t) => t.run_id === runInfo.run_id)) return prev;
            return [{ run_id: runInfo.run_id, run_name: tabName, trade_date: runInfo.trade_date }, ...prev];
          });
          setActiveTabRunId(runInfo.run_id);
        }
        if (runInfo.summary_json?.counts) setCounts(runInfo.summary_json.counts);
      }
    } catch (e) {
      console.warn('Failed to load latest early turn run:', e);
    } finally {
      setLoadingRun(false);
    }
  }, [runId]);

  useEffect(() => {
    loadLatestRun();
  }, [loadLatestRun]);

  // 2. Fetch stock list drilldown
  const loadStocks = useCallback(async () => {
    if (!runId) return;
    const requestVersion = ++stockRequestVersionRef.current;
    setLoadingStocks(true);
    try {
      const params = new URLSearchParams();
      if (activeState !== 'ALL') params.set('state', activeState);
      if (activeBg !== 'ALL') params.set('bg_type', activeBg);
      if (appliedMinScore) params.set('min_score', appliedMinScore);
      if (appliedSearchQuery) params.set('q', appliedSearchQuery);
      if (selectedIndustry !== 'ALL') params.set('industry', selectedIndustry);
      if (selectedConcept !== 'ALL') params.set('concept', selectedConcept);
      // ALL_RECENT：命中任一近期热点；具体名称：命中该热点；ALL：不按热点过滤。
      if (selectedHotTheme !== 'ALL') {
        params.set('hot_theme_scope', 'RECENT_60D');
        if (selectedHotTheme !== 'ALL_RECENT') params.set('hot_theme', selectedHotTheme);
      }
      if (excludeSt) params.set('exclude_st', 'true');
      if (fundamentalFilter !== 'ALL') params.set('fundamental_state', fundamentalFilter);
      params.set('page', String(page));
      params.set('page_size', '50');

      const baseUrl = getApiBase();
      const res = await safeFetch(`${baseUrl}/api/early-turn/runs/${runId}/stocks?${params.toString()}`);
      if (requestVersion !== stockRequestVersionRef.current) return;
      if (res && res.ok) {
        const json: EarlyTurnResponse = await res.json();
        setData(json);
        if (json.counts) setCounts(json.counts);
      } else if (selectedHotTheme !== 'ALL') {
        setData((previous) => previous ? { ...previous, total: 0, items: [], page: 1 } : null);
        setSecondaryMetrics({});
        setSecondaryMetricsDate('');
        try {
          const body = await res?.json();
          setHotThemeIssue(body?.detail?.message || '热点方向筛选数据不可用');
        } catch {
          setHotThemeIssue('热点方向筛选数据不可用');
        }
      }
    } catch (e) {
      if (requestVersion !== stockRequestVersionRef.current) return;
      console.warn('Failed to fetch early turn stocks:', e);
    } finally {
      if (requestVersion === stockRequestVersionRef.current) {
        setLoadingStocks(false);
      }
    }
  }, [runId, activeState, activeBg, appliedMinScore, appliedSearchQuery, selectedIndustry, selectedConcept, selectedHotTheme, excludeSt, fundamentalFilter, page]);

  const filtersPending =
    minScore.trim() !== appliedMinScore || searchQuery.trim() !== appliedSearchQuery;

  useEffect(() => {
    if (!sessionReady || !runId) return;
    if (lastFilterRunIdRef.current && lastFilterRunIdRef.current !== runId) {
      setSelectedHotTheme('ALL');
      setFundamentalFilter('ALL');
    }
    lastFilterRunIdRef.current = runId;
  }, [runId, sessionReady]);

  useEffect(() => {
    if (!runId) {
      setHotThemeOptions([]);
      setHotThemeIssue(null);
      return;
    }
    let cancelled = false;
    (async () => {
      const hotParams = new URLSearchParams({
        scope: 'RECENT_60D',
      });
      if (activeState !== 'ALL') hotParams.set('state', activeState);
      if (activeBg !== 'ALL') hotParams.set('bg_type', activeBg);
      if (appliedMinScore) hotParams.set('min_score', appliedMinScore);
      if (appliedSearchQuery) hotParams.set('q', appliedSearchQuery);
      if (selectedIndustry !== 'ALL') hotParams.set('industry', selectedIndustry);
      if (selectedConcept !== 'ALL') hotParams.set('concept', selectedConcept);
      if (excludeSt) hotParams.set('exclude_st', 'true');
      if (fundamentalFilter !== 'ALL') hotParams.set('fundamental_state', fundamentalFilter);
      const res = await safeFetch(`${getApiBase()}/api/early-turn/runs/${runId}/hot-themes?${hotParams.toString()}`);
      if (cancelled) return;
      if (!res || !res.ok) {
        setHotThemeOptions([]);
        try {
          const body = await res?.json();
          setHotThemeIssue(body?.detail?.message || '该批次尚未生成可用的市场热点全景');
        } catch { setHotThemeIssue('该批次尚未生成可用的市场热点全景'); }
        return;
      }
      const body = await res.json();
      setHotThemeOptions(body.options || []);
      setHotThemeIssue(null);
    })();
    return () => { cancelled = true; };
  }, [runId, activeState, activeBg, appliedMinScore, appliedSearchQuery, selectedIndustry, selectedConcept, excludeSt, fundamentalFilter]);

  useEffect(() => {
    loadStocks();
  }, [loadStocks]);

  const loadSecondaryMetrics = useCallback(async () => {
    if (!runId || !tradeDate) return;
    setLoadingSecondaryMetrics(true);
    setSecondaryMetricsError(null);
    setSecondaryMetricsIssue(null);
    try {
      const baseUrl = getApiBase();
      const params = new URLSearchParams({ date: tradeDate });
      if (currentStockCodes.length > 0) {
        params.set('codes', currentStockCodes.join(','));
      }
      const res = await safeFetch(`${baseUrl}/api/candidate-secondary?${params.toString()}`);
      if (!res || !res.ok) {
        setSecondaryMetrics({});
        setSecondaryMetricsDate(tradeDate);
        let errorText = `候选详情接口异常: HTTP ${res?.status || 'Network Error'}`;
        if (res) {
          try {
            const errorJson = await res.json();
            const detail = errorJson?.detail;
            if (typeof detail === 'string') {
              errorText = detail;
            } else if (detail?.message) {
              errorText = detail.message;
              setSecondaryMetricsIssue({
                code: detail.error,
                message: detail.message,
                early_turn_count: detail.early_turn_count,
                secondary_snapshot_count: detail.secondary_snapshot_count,
                candidate_scope: detail.candidate_scope,
              });
            }
          } catch (e) {
            console.warn('Failed to parse secondary metrics error response:', e);
          }
        }
        setSecondaryMetricsError(errorText);
        return;
      }
      const json = await res.json();
      const items: SecondaryMetricItem[] = Array.isArray(json.items) ? json.items : [];
      setSecondaryMetricsError(null);
      setSecondaryMetricsIssue(null);
      setSecondaryMetrics(
        items.reduce<Record<string, SecondaryMetricItem>>((acc, item) => {
          if (item.ts_code) acc[item.ts_code] = item;
          return acc;
        }, {})
      );
      setSecondaryMetricsDate(tradeDate);
    } catch (e) {
      console.warn('Failed to fetch secondary metrics:', e);
      setSecondaryMetrics({});
      setSecondaryMetricsDate(tradeDate);
      setSecondaryMetricsError('详情指标接口异常');
      setSecondaryMetricsIssue(null);
    } finally {
      setLoadingSecondaryMetrics(false);
    }
  }, [runId, tradeDate, currentStockCodes]);

  const handleGenerateSecondary = useCallback(async () => {
    if (!runId) {
      setToastMsg('当前没有可研究的选股批次。');
      setTimeout(() => setToastMsg(null), 2500);
      return;
    }
    setSecondaryRunLoading(true);
    try {
      const baseUrl = getApiBase();
      const res = await safeFetch(`${baseUrl}/api/candidate-secondary/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          run_id: runId,
          date: tradeDate,
          // 生命周期卡片是可选过滤条件；不选时按其余全部筛选条件研究。
          state: activeState !== 'ALL' ? activeState : null,
          min_score: appliedMinScore || null,
          exclude_st: excludeSt,
          q: appliedSearchQuery || null,
          industry: selectedIndustry !== 'ALL' ? selectedIndustry : null,
          concept: selectedConcept !== 'ALL' ? selectedConcept : null,
          hot_theme_scope: selectedHotTheme !== 'ALL' ? 'RECENT_60D' : 'ALL',
          hot_theme: selectedHotTheme !== 'ALL' && selectedHotTheme !== 'ALL_RECENT' ? selectedHotTheme : null,
        }),
      });
      const body = res ? await res.json().catch(() => ({})) : {};
      if (!res || !res.ok) {
        throw new Error(body?.detail?.message || body?.detail || `基本面研究失败（HTTP ${res?.status || 'Network Error'}）`);
      }
      setToastMsg(`已完成 ${body.evaluated_count || 0} 只股票的基本面研究。`);
      setTimeout(() => setToastMsg(null), 2500);
      await loadStocks();
      await loadSecondaryMetrics();
    } catch (e) {
      setToastMsg(e instanceof Error ? e.message : '基本面研究失败');
      setTimeout(() => setToastMsg(null), 3000);
    } finally {
      setSecondaryRunLoading(false);
    }
  }, [runId, tradeDate, activeState, appliedMinScore, excludeSt, appliedSearchQuery, selectedIndustry, selectedConcept, selectedHotTheme, loadStocks, loadSecondaryMetrics]);

  useEffect(() => {
    loadSecondaryMetrics();
  }, [loadSecondaryMetrics]);

  const updateFloatingDropdownPosition = useCallback((
    button: HTMLButtonElement | null,
    maxWidth: number,
    setter: React.Dispatch<React.SetStateAction<{ left: number; top: number; width: number } | null>>
  ) => {
    if (!button || typeof window === 'undefined') return;
    const rect = button.getBoundingClientRect();
    const viewportPadding = 16;
    const width = Math.min(maxWidth, Math.max(240, window.innerWidth - viewportPadding * 2));
    const left = Math.min(
      Math.max(viewportPadding, rect.right - width),
      window.innerWidth - width - viewportPadding
    );
    setter({
      left,
      top: rect.bottom + 8,
      width,
    });
  }, []);

  useEffect(() => {
    if (!showIndustryDropdown) {
      setIndustryDropdownPosition(null);
      return;
    }

    const update = () => updateFloatingDropdownPosition(industryDropdownButtonRef.current, 288, setIndustryDropdownPosition);
    update();
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [showIndustryDropdown, updateFloatingDropdownPosition]);

  useEffect(() => {
    if (!showConceptDropdown) {
      setConceptDropdownPosition(null);
      return;
    }

    const update = () => updateFloatingDropdownPosition(conceptDropdownButtonRef.current, 352, setConceptDropdownPosition);
    update();
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [showConceptDropdown, updateFloatingDropdownPosition]);

  useEffect(() => {
    if (!showIndustryDropdown && !showConceptDropdown) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setShowIndustryDropdown(false);
        setShowConceptDropdown(false);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [showIndustryDropdown, showConceptDropdown]);

  // 3. Trigger new calculation
  const handleTriggerRun = async (rerunRunId?: string) => {
    setShowRunConfigModal(false);
    setRunningTask(true);
    setEarlyTurnTask({
      status: 'queued',
      progress: 0,
      step_message: 'A-PreV2 任务已提交，等待后台执行...',
      trade_date: tradeDate,
    });
    try {
      const defaultName = universeType === 'CONCEPTS'
        ? `概念板块评估 [${conceptInput.trim() || '未指定'}]`
        : universeType === 'CUSTOM_CODES'
        ? `指定范围评估 [${customCodes.trim() || '未指定'}]`
        : `${modalTradeDate || getTodayTradeDateStr()} 早期转强选股`;

      const targetTradeDate = modalTradeDate || getTodayTradeDateStr();
      const payload: Record<string, any> = {
        trade_date: targetTradeDate,
        run_name: newRunName.trim() || defaultName,
        notes: newRunNotes.trim(),
      };
      if (rerunRunId) {
        payload.run_id = rerunRunId;
        payload.trade_date = tradeDate || targetTradeDate;
        delete payload.run_name;
        delete payload.notes;
      }
      if (universeType === 'CONCEPTS' && conceptInput.trim()) {
        payload.ts_code = conceptInput.trim();
      } else if (universeType === 'CUSTOM_CODES' && customCodes.trim()) {
        payload.ts_code = customCodes.trim();
      }

      const baseUrl = getApiBase();
      const res = await safeFetch(`${baseUrl}/api/early-turn/run-async`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res || !res.ok) {
        throw new Error(`HTTP ${res?.status || 'Network Error'}`);
      }
      const submitted = await res.json();
      if (submitted?.task) setEarlyTurnTask(submitted.task);

      let finished = false;
      let consecutiveStatusFailures = 0;
      while (!finished) {
        await new Promise((resolve) => setTimeout(resolve, 1200));
        const statusRes = await safeFetch(`${baseUrl}/api/early-turn/status`);
        if (!statusRes || !statusRes.ok) {
          consecutiveStatusFailures += 1;
          if (consecutiveStatusFailures >= 3) {
            throw new Error('连续三次无法读取 A-PreV2 任务状态，请确认后端服务正常后重新发起选股');
          }
          continue;
        }
        consecutiveStatusFailures = 0;
        const statusJson: EarlyTurnTaskStatus = await statusRes.json();
        setEarlyTurnTask(statusJson);
        if (statusJson.status === 'success') {
          finished = true;
          await fetchHistoryRuns();
          await loadLatestRun(statusJson.trade_date || tradeDate);
          await loadSecondaryMetrics();
        } else if (statusJson.status === 'failed') {
          finished = true;
          throw new Error(statusJson.error || statusJson.step_message || 'A-PreV2 运行失败');
        } else if (statusJson.status === 'idle') {
          throw new Error('A-PreV2 任务状态已丢失（后端可能刚重启），请重新发起选股');
        }
      }
    } catch (e) {
      console.error('Trigger run failed:', e);
      setEarlyTurnTask((prev) => ({
        ...(prev || {}),
        status: 'failed',
        progress: 0,
        step_message: e instanceof Error ? e.message : 'A-PreV2 运行失败',
        error: e instanceof Error ? e.message : 'A-PreV2 运行失败',
      }));
    } finally {
      setRunningTask(false);
    }
  };

  const industryCounts = useMemo(() => {
    return data?.industry_counts || {};
  }, [data]);

  const conceptCounts = useMemo(() => {
    return data?.concept_counts || {};
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

  const sortedConcepts = useMemo(() => {
    return Object.entries(conceptCounts)
      .sort((a, b) => {
        const aLow = isLowSignalConcept(a[0]);
        const bLow = isLowSignalConcept(b[0]);
        if (aLow !== bLow) return aLow ? 1 : -1;
        return b[1] - a[1];
      })
      .map(([name, count]) => ({ name, count }));
  }, [conceptCounts]);

  const topConcepts = useMemo(() => {
    return sortedConcepts.slice(0, conceptShowCount);
  }, [sortedConcepts, conceptShowCount]);

  const allConcepts = useMemo(() => {
    return Object.keys(conceptCounts).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  }, [conceptCounts]);

  const filteredConceptsForSearch = useMemo(() => {
    if (!conceptSearchQuery.trim()) return allConcepts;
    return allConcepts.filter((concept) => concept.toLowerCase().includes(conceptSearchQuery.toLowerCase().trim()));
  }, [allConcepts, conceptSearchQuery]);

  const currentItems = data?.items || [];
  const selectedStock = selectedStockIndex !== null ? currentItems[selectedStockIndex] : null;
  const fundamentalCounts = data?.fundamental_counts || {};
  const fundamentalOptions: Array<{ state: FundamentalFilterState; label: string; tone: string }> = [
    { state: 'ALL', label: '全部', tone: 'slate' },
    { state: 'FUNDAMENTAL_ACCEPTABLE', label: '可接受', tone: 'sky' },
    { state: 'FUNDAMENTAL_POSITIVE', label: '经营向好', tone: 'emerald' },
    { state: 'FUNDAMENTAL_RISK', label: '存在风险', tone: 'rose' },
    { state: 'FUNDAMENTAL_DATA_INSUFFICIENT', label: '数据不足', tone: 'slate' },
    { state: 'UNRESEARCHED', label: '未研究', tone: 'slate' },
  ];
  const hasFundamentalResearch = Object.entries(fundamentalCounts).some(
    ([state, count]) => state !== 'UNRESEARCHED' && Number(count) > 0,
  );

  // K 线切换严格使用当前 A-PreV2 选股列表（data.items）的顺序。
  // 这里不重新按代码、名称或全市场数据排序，避免弹窗内的顺序与列表不一致。
  const navigateSelectedStock = (delta: -1 | 1) => {
    setSelectedStockIndex((currentIndex) => {
      if (currentIndex === null) return currentIndex;
      const nextIndex = currentIndex + delta;
      if (nextIndex < 0 || nextIndex >= currentItems.length) return currentIndex;
      const nextItem = currentItems[nextIndex];
      setDetailStock({
        tsCode: nextItem.ts_code,
        stockName: nextItem.name || nextItem.ts_code,
        initialTab: 'kline',
      });
      return nextIndex;
    });
  };

  // 按键 Space (空格键) 快捷放入当前选中股票到 AI 分析池
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (detailStock) return;
      if (e.code === 'Space' || e.key === ' ') {
        const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
        if (selectedStockIndex !== null && currentItems[selectedStockIndex]) {
          e.preventDefault();
          toggleAiPool(currentItems[selectedStockIndex].ts_code);
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedStockIndex, currentItems, detailStock]);

  return (
    <div className="screening-view space-y-4">
      {(loadingRun || (activeTabRunId !== 'SINGLE_STOCK_TEST' && Boolean(runId) && loadingStocks)) && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#f7f4ee]/75 backdrop-blur-[2px]">
          <div className="flex min-w-56 flex-col items-center gap-3 rounded-2xl border border-[#c4c8bc]/70 bg-white/95 px-8 py-7 text-center shadow-2xl">
            <div className="relative flex h-12 w-12 items-center justify-center">
              <div className="absolute inset-0 rounded-full border-4 border-[#4a7c59]/20 border-t-[#4a7c59] animate-spin" />
              <Loader2 className="h-5 w-5 animate-spin text-[#4a7c59]" />
            </div>
            <div>
              <p className="text-sm font-black text-[#2e3230]">
                {loadingRun ? '正在加载选股批次' : '正在加载股票列表'}
              </p>
              <p className="mt-1 text-[11px] text-[#686d68]">请稍候，正在读取最新筛选结果…</p>
            </div>
          </div>
        </div>
      )}
      {/* 选股批次多标签页栏 (Session Tabs - 无切边 overflow，绝对定位 Popover 安全展示) */}
      <div className="sticky top-14 z-40 -mx-4 px-4 flex items-center justify-between border-b border-[#c4c8bc]/40 bg-[#f7f4ee]/95 backdrop-blur-sm pt-1.5 pb-3 select-none font-sans gap-2 relative">
        {/* 最左侧：历史选股管理图标按钮 & 下拉 Popover */}
        <div className="relative shrink-0" ref={historyDropdownRef}>
          <button
            onClick={() => {
              fetchHistoryRuns();
              setShowHistoryDropdown((prev) => !prev);
            }}
            className={`p-1.5 px-2.5 rounded-lg text-xs font-bold transition border flex items-center justify-center gap-1.5 cursor-pointer ${
              showHistoryDropdown
                ? 'bg-[#705c30] text-white border-[#705c30] shadow-xs'
                : 'bg-white text-[#686d68] hover:text-[#2e3230] border-[#c4c8bc]/60 hover:bg-[#faf6f0] shadow-2xs'
            }`}
            title={`历史选股快照管理 (${historyRuns.length} 次记录)`}
          >
            <History className="w-3.5 h-3.5 text-[#705c30]" />
            <span className="font-mono text-[11px] font-bold text-[#705c30]">{historyRuns.length}</span>
          </button>

          {/* 历史快照下拉列表 Popover (置顶层级 z-50，不再会被外部裁剪) */}
          {showHistoryDropdown && (
            <div className="absolute left-0 top-full mt-2 z-50 w-80 bg-white rounded-xl border border-[#c4c8bc]/70 shadow-2xl p-2.5 space-y-1.5 text-xs max-h-96 overflow-y-auto">
              <div className="px-2 py-1 flex items-center justify-between border-b border-[#c4c8bc]/40 text-[#705c30] font-bold">
                <span className="flex items-center gap-1.5">
                  <History className="w-3.5 h-3.5" />
                  <span>历史选股快照 ({historyRuns.length})</span>
                </span>
                <button
                  onClick={() => {
                    setShowHistoryDropdown(false);
                    void openNewRunConfig();
                  }}
                  className="text-[11px] font-bold text-[#4a7c59] hover:underline flex items-center gap-0.5 cursor-pointer"
                >
                  <span>+ 新建选股</span>
                </button>
              </div>

              {historyRuns.length === 0 ? (
                <div className="text-center py-6 text-slate-400 font-bold text-xs">
                  暂无历史选股快照
                </div>
              ) : (
                historyRuns.map((run) => (
                  <div
                    key={run.run_id}
                    onClick={() => {
                      openHistoryTab(run);
                      setShowHistoryDropdown(false);
                    }}
                    className="p-2 bg-[#faf6f0] hover:bg-[#f2ece0] rounded-lg border border-[#c4c8bc]/40 transition cursor-pointer flex items-center justify-between gap-2 group"
                  >
                    <div className="min-w-0 space-y-0.5">
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold text-[#2e3230] truncate max-w-[140px]">
                          {run.run_name || run.run_id}
                        </span>
                        <span className="px-1.5 py-0.2 rounded bg-emerald-100 text-emerald-800 font-mono font-bold text-[10px]">
                          {run.trade_date}
                        </span>
                      </div>
                      {run.notes && (
                        <p className="text-[10px] text-slate-500 truncate">{run.notes}</p>
                      )}
                      <div className="text-[9px] font-mono text-slate-400">
                          {run.candidate_count || 0} 条股票快照
                      </div>
                    </div>

                    <button
                      onClick={(e) => deleteHistoryRun(run.run_id, e)}
                      className="text-slate-300 hover:text-rose-600 p-1 transition opacity-0 group-hover:opacity-100 cursor-pointer"
                      title="删除此批次及其全部股票快照"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* 中间：动态打开的选股批次标签页 */}
        <div className="flex items-center gap-1.5 overflow-x-auto flex-1 min-w-0 px-1">
          {openedTabs.map((tab) => {
            const isActive = activeTabRunId === tab.run_id;
            return (
              <div
                key={tab.run_id}
                onClick={() => {
                  setActiveTabRunId(tab.run_id);
                  setRunId(tab.run_id);
                  if (tab.trade_date) setTradeDate(tab.trade_date);
                }}
                className={`group relative flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold transition border shrink-0 cursor-pointer ${
                  isActive
                    ? 'bg-white text-[#2e3230] border-[#4a7c59]/60 shadow-xs ring-1 ring-[#4a7c59]/20'
                    : 'bg-[#faf6f0]/70 text-[#686d68] hover:bg-white hover:text-[#2e3230] border-transparent hover:border-[#c4c8bc]/50'
                }`}
              >
                <div className="flex items-center gap-1.5">
                  <span className={isActive ? 'text-[#2e3230]' : 'text-[#4a4e4a]'}>{tab.run_name}</span>
                  <span className={`font-mono text-[10px] ${isActive ? 'text-[#4a7c59] font-bold' : 'text-slate-400'}`}>
                    ({tab.trade_date})
                  </span>
                </div>

                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    closeHistoryTab(tab.run_id);
                  }}
                  className="rounded-full p-0.5 text-slate-400 hover:bg-slate-200/60 hover:text-rose-600 transition text-[11px]"
                  title="关闭此标签"
                >
                  ✕
                </button>
              </div>
            );
          })}

          {/* 最后一个选股快照右侧的 + 号：新建选股评估批次窗口 */}
          <button
            onClick={() => {
              void openNewRunConfig();
            }}
            className="flex items-center justify-center w-7 h-7 rounded-lg text-xs font-black transition border shrink-0 cursor-pointer bg-white/70 hover:bg-emerald-50 text-[#4a7c59] border-[#c4c8bc]/50 hover:border-[#4a7c59]/60 shadow-2xs"
            title="新建选股评估任务"
          >
            +
          </button>
        </div>

        {/* 最右侧：单股测试标签页 + 当前批次快照日 */}
        <div className="ml-auto flex items-center gap-2 shrink-0">
          <button
            onClick={() => setActiveTabRunId('SINGLE_STOCK_TEST')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition border cursor-pointer ${
              activeTabRunId === 'SINGLE_STOCK_TEST'
                ? 'bg-emerald-100 text-[#326044] border-[#4a7c59]/70 shadow-xs ring-1 ring-[#4a7c59]/25'
                : 'bg-emerald-50 text-[#326044] border-[#4a7c59]/40 hover:bg-emerald-100 hover:border-[#4a7c59]/70 shadow-2xs'
            }`}
            title="切换至单股多日策略测试与诊断算子"
          >
            <TestTube2 className="w-3.5 h-3.5" />
            <span>单股测试</span>
          </button>
          <div className="flex items-center gap-1.5 rounded-lg border border-[#c4c8bc]/60 bg-white/80 px-3 py-1.5 text-xs font-bold text-[#2e3230] whitespace-nowrap">
            <Calendar className="h-3.5 w-3.5 text-[#4a7c59]" />
            <span>快照日:</span>
            <span className="font-mono text-[#4a7c59]">{tradeDate || '未加载'}</span>
          </div>
          {activeTabRunId !== 'SINGLE_STOCK_TEST' && (
            <>
              <button
                onClick={() => {
                  setNewRunName(`${tradeDate || '最新'} 重新评估`);
                  setNewRunNotes('');
                  handleTriggerRun(runId || undefined);
                }}
                disabled={runningTask}
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-[#4a7c59] text-white shadow-xs transition hover:bg-[#3b6447] disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
                title="重新评估本批次"
                aria-label="重新评估本批次"
              >
                {runningTask ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              </button>
              <button
                onClick={() => setShowAiPoolDrawer(true)}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold text-white shadow-xs transition cursor-pointer ${
                  aiQueueRunning
                    ? 'bg-gradient-to-r from-purple-800 to-indigo-900 animate-pulse ring-2 ring-purple-400'
                    : 'bg-gradient-to-r from-purple-700 to-indigo-700 hover:from-purple-800 hover:to-indigo-800'
                }`}
                title="打开 AI 分析池"
              >
                <Sparkles className={`h-3.5 w-3.5 ${aiQueueRunning ? 'animate-spin text-amber-300' : 'text-amber-300'}`} />
                <span>{aiQueueRunning ? `分析中 ${aiCompletedCodes.length}/${aiPoolCodes.length}` : `AI 分析池 (${aiPoolCodes.length})`}</span>
              </button>
            </>
          )}
        </div>
      </div>

      <div className={activeTabRunId === 'SINGLE_STOCK_TEST' ? '' : 'hidden'}>
        <SingleStockTestView />
      </div>
      {activeTabRunId !== 'SINGLE_STOCK_TEST' && activeTabRunId === 'EMPTY' ? (
        <div className="bg-white/80 rounded-2xl border border-[#c4c8bc]/60 shadow-xs p-12 text-center space-y-5 my-4">
          <div className="w-16 h-16 rounded-full bg-[#faf6f0] border border-[#c4c8bc]/60 flex items-center justify-center mx-auto text-[#705c30]">
            <History className="w-8 h-8" />
          </div>
          <div className="space-y-1">
            <h3 className="text-base font-bold text-[#2e3230]">当前暂无打开的选股快照</h3>
            <p className="text-xs text-[#686d68]">
              您可以新建一次全市场选股快照，或者从历史快照记录中重新选择打开
            </p>
          </div>
          <div className="flex items-center justify-center gap-3 pt-2">
            <button
              onClick={() => {
                void openNewRunConfig();
              }}
              className="px-4 py-2 bg-[#4a7c59] hover:bg-[#3b6447] text-white rounded-xl text-xs font-bold shadow-xs transition flex items-center gap-1.5 cursor-pointer"
            >
              <PlayCircle className="w-4 h-4" />
              <span>▶ 新建全市场选股评估</span>
            </button>
            <button
              onClick={() => {
                fetchHistoryRuns();
                setShowHistoryDropdown(true);
              }}
              className="px-4 py-2 bg-white text-[#705c30] border border-[#705c30]/50 hover:bg-[#faf6f0] rounded-xl text-xs font-bold shadow-xs transition flex items-center gap-1.5 cursor-pointer"
            >
              <History className="w-4 h-4" />
              <span>📜 打开历史快照清单 ({historyRuns.length})</span>
            </button>
          </div>
        </div>
      ) : activeTabRunId !== 'SINGLE_STOCK_TEST' ? (
        <>
      {/* 页面级 Mask 蒙层 + 算法计算进度 Modal */}
      {runningTask && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 select-none">
          <div className="w-full max-w-md bg-white rounded-2xl p-6 shadow-2xl border border-[#c4c8bc]/60 space-y-4 text-center">
            <div className="flex justify-center">
              <div className="relative">
                <div className="w-16 h-16 rounded-full border-4 border-[#4a7c59]/20 border-t-[#4a7c59] animate-spin" />
                <Sparkles className="w-6 h-6 text-[#4a7c59] absolute inset-0 m-auto" />
              </div>
            </div>

            <div className="space-y-1">
              <h3 className="font-bold text-base text-[#2e3230]">正在执行 A-PreV2 技术选股与候选详情整理</h3>
              <p className="text-xs text-[#686d68]">
                评估交易日: <span className="font-mono font-bold text-[#4a7c59]">{earlyTurnTask?.trade_date || tradeDate}</span>
                {typeof earlyTurnTask?.candidate_count === 'number' && earlyTurnTask.candidate_count > 0 && (
                  <span className="ml-2">候选详情: <span className="font-mono font-bold text-[#705c30]">{earlyTurnTask.candidate_count}</span> 只</span>
                )}
              </p>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-[#686d68] font-bold">
                <span className="text-left">{earlyTurnTask?.step_message || '正在准备任务...'}</span>
                <span className="font-mono text-[#4a7c59]">{Math.round(earlyTurnTask?.progress || 0)}%</span>
              </div>
              <div className="w-full h-2.5 bg-gray-100 rounded-full overflow-hidden border border-gray-200">
                <div
                  className="h-full bg-gradient-to-r from-[#4a7c59] to-[#705c30] rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(100, Math.max(0, earlyTurnTask?.progress || 0))}%` }}
                />
              </div>
            </div>

            <p className="text-[11px] text-[#686d68] italic">
              批量任务只执行技术选股；选择筛选条件后，可手动进行基本面研究。
            </p>
          </div>
        </div>
      )}

      {/* 状态分类顶栏卡片：A-PreV2 生命周期 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {/* Card 1: PRE_FIRST_TURN */}
        <div
          onClick={() => {
            setActiveState('PRE_FIRST_TURN');
            setPage(1);
          }}
          className={`state-card state-card-pre relative cursor-pointer overflow-hidden rounded-xl p-3.5 border-2 bg-slate-700 text-white border-slate-700 transition shadow-xs space-y-1.5 hover:shadow-md ${
            activeState === 'PRE_FIRST_TURN'
              ? 'is-selected'
              : 'opacity-90 hover:opacity-100'
          }`}
        >
          <div className="flex items-center justify-between text-xs">
            <span className="font-bold flex items-center gap-1">
              <Activity className="h-3.5 w-3.5" /> 底部准备
            </span>
            <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-black/10">等待首次触发</span>
          </div>
          <p className="text-xl font-bold font-mono">{counts.PRE_FIRST_TURN || 0} 只</p>
          <p className="text-[10px] text-zinc-300">
            尚未形成有效的首次转强触发
          </p>
        </div>

        {/* Card 2: FIRST_TURN_WINDOW */}
        <div
          onClick={() => {
            setActiveState('FIRST_TURN_WINDOW');
            setPage(1);
          }}
          className={`state-card state-card-window relative cursor-pointer overflow-hidden rounded-xl p-3.5 border-2 bg-[#4a7c59] text-white border-[#4a7c59] transition shadow-xs space-y-1.5 hover:shadow-md ${
            activeState === 'FIRST_TURN_WINDOW'
              ? 'is-selected'
              : 'opacity-90 hover:opacity-100'
          }`}
        >
          <div className="flex items-center justify-between text-xs">
            <span className="font-bold flex items-center gap-1">
              <Sparkles className="h-3.5 w-3.5" /> 首次转强窗口
            </span>
            <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-black/10">正式候选 ≥75分</span>
          </div>
          <p className="text-xl font-bold font-mono">{counts.FIRST_TURN_WINDOW || 0} 只</p>
          <p className="text-[10px] text-emerald-100">
            已触发首次转强，仍处于 A-PreV2 早期窗口
          </p>
        </div>

        {/* Card 3: POST_FIRST_WAVE */}
        <div
          onClick={() => {
            setActiveState('POST_FIRST_WAVE');
            setPage(1);
          }}
          className={`state-card state-card-post relative cursor-pointer overflow-hidden rounded-xl p-3.5 border-2 bg-rose-800 text-white border-rose-800 transition shadow-xs space-y-1.5 hover:shadow-md ${
            activeState === 'POST_FIRST_WAVE'
              ? 'is-selected'
              : 'opacity-90 hover:opacity-100'
          }`}
        >
          <div className="flex items-center justify-between text-xs">
            <span className="font-bold flex items-center gap-1">
              <AlertTriangle className="h-3.5 w-3.5" /> 第一波已完成
            </span>
            <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-black/10">本轮退出</span>
          </div>
          <p className="text-xl font-bold font-mono">{counts.POST_FIRST_WAVE || 0} 只</p>
          <p className="text-[10px] text-rose-100">
            第一波结束后的近期冷却期
          </p>
        </div>

      </div>

      {/* 行业/概念筛选与搜索工具条 */}
      <div className="bg-[#f0ece4]/70 p-2.5 rounded-xl border border-[#c4c8bc]/40 space-y-2 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-3">

          <div className="flex items-center gap-2">
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
            <span className="ml-1 whitespace-nowrap rounded bg-[#faf6f0] px-1.5 py-0.5 text-[10px] font-bold text-[#705c30]">
              {filtersPending ? '输入完成后筛选…' : `当前结果 ${data?.total ?? 0} 条`}
            </span>
          </div>

          <label className="inline-flex items-center gap-1.5 rounded-lg border border-[#c4c8bc]/50 bg-white px-2 py-1 font-bold text-[#686d68] cursor-pointer">
            <input
              type="checkbox"
              checked={excludeSt}
              onChange={(e) => setExcludeSt(e.target.checked)}
              className="accent-[#4a7c59]"
            />
            剔除 ST
          </label>

          {hasFundamentalResearch && (
            <div className="flex flex-wrap items-center gap-1 rounded-lg border border-[#c4c8bc]/50 bg-white px-2 py-1">
              <span className="mr-0.5 whitespace-nowrap text-[#686d68] font-bold">基本面:</span>
              {fundamentalOptions.map((option) => {
                const selected = fundamentalFilter === option.state;
                const count = option.state === 'ALL'
                  ? Object.values(fundamentalCounts).reduce((sum, value) => sum + Number(value || 0), 0)
                  : Number(fundamentalCounts[option.state] || 0);
                const activeClass = option.tone === 'emerald'
                  ? 'border-emerald-700 bg-emerald-700 text-white'
                  : option.tone === 'sky'
                    ? 'border-sky-700 bg-sky-700 text-white'
                    : option.tone === 'rose'
                      ? 'border-rose-700 bg-rose-700 text-white'
                      : 'border-slate-700 bg-slate-700 text-white';
                const idleClass = option.tone === 'emerald'
                  ? 'border-emerald-200 text-emerald-800 hover:bg-emerald-50'
                  : option.tone === 'sky'
                    ? 'border-sky-200 text-sky-800 hover:bg-sky-50'
                    : option.tone === 'rose'
                      ? 'border-rose-200 text-rose-800 hover:bg-rose-50'
                      : 'border-slate-200 text-slate-600 hover:bg-slate-50';
                return (
                  <button
                    key={option.state}
                    type="button"
                    onClick={() => { setFundamentalFilter(option.state); setPage(1); }}
                    className={`rounded-md border px-1.5 py-0.5 text-[11px] font-bold transition ${selected ? activeClass : idleClass}`}
                  >
                    {option.label} ({count})
                  </button>
                );
              })}
            </div>
          )}

          <button
            type="button"
            onClick={() => void handleGenerateSecondary()}
            disabled={secondaryRunLoading || !runId}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[#705c30] bg-[#705c30] px-3 py-1 font-bold text-white shadow-xs transition hover:bg-[#5e4d27] disabled:cursor-not-allowed disabled:opacity-45"
            title="对当前所有筛选条件过滤出的股票进行基本面研究"
          >
            {secondaryRunLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BarChart2 className="h-3.5 w-3.5" />}
            {secondaryRunLoading ? '研究中...' : '基本面研究'}
          </button>

          <button
            type="button"
            onClick={() => setShowConceptDropdown((open) => !open)}
            aria-expanded={showConceptDropdown}
            className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 font-bold transition ${showConceptDropdown || selectedConcept !== 'ALL' ? 'border-violet-500 bg-violet-50 text-violet-800' : 'border-violet-200 bg-white text-violet-700 hover:bg-violet-50'}`}
          >
            <Layers className="h-3.5 w-3.5" />
            概念筛选{selectedConcept !== 'ALL' ? ' · 已选' : ''}
          </button>

          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#c4c8bc]/30 pt-2">
          {showConceptDropdown && (
            <div className="flex w-full flex-wrap items-center gap-1.5 border-t border-[#c4c8bc]/20 pt-2">
              <span className="mr-1 font-bold text-[#686d68]">概念筛选:</span>
              <div className="flex items-center gap-1 rounded-md border border-violet-200 bg-white px-2 py-1">
                <Search className="h-3.5 w-3.5 text-violet-700" />
                <input value={conceptSearchQuery} onChange={(e) => setConceptSearchQuery(e.target.value)} placeholder="搜索概念..." className="w-32 bg-transparent text-xs text-[#2e3230] outline-none" />
              </div>
              <button onClick={() => { setSelectedConcept('ALL'); setPage(1); }} className={`rounded-md px-2.5 py-1 font-bold ${selectedConcept === 'ALL' ? 'bg-violet-700 text-white' : 'border border-violet-200 bg-white text-violet-800'}`}>全部概念</button>
              {filteredConceptsForSearch.slice(0, conceptShowCount).map((concept) => {
                const weak = isLowSignalConcept(concept);
                return <button key={concept} onClick={() => { setSelectedConcept(concept); setPage(1); }} className={`rounded-md border px-2.5 py-1 font-bold ${selectedConcept === concept ? 'border-violet-700 bg-violet-700 text-white' : weak ? 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50' : 'border-violet-200 bg-white text-violet-800 hover:bg-violet-50'}`}>{concept} ({conceptCounts[concept] || 0})</button>;
              })}
              {filteredConceptsForSearch.length === 0 && <span className="py-1 text-xs text-[#686d68]">无匹配概念</span>}
              {conceptShowCount < filteredConceptsForSearch.length && <button onClick={() => setConceptShowCount((count) => Math.min(count + 24, filteredConceptsForSearch.length))} className="rounded-md border border-dashed border-violet-500/60 px-2 py-1 font-bold text-violet-700">更多</button>}
              {conceptShowCount > 12 && <button onClick={() => setConceptShowCount(12)} className="rounded-md border border-dashed border-[#686d68]/50 px-2 py-1 font-bold text-[#686d68]">收起</button>}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-1.5 border-t border-[#c4c8bc]/20 pt-2 w-full">
            <span className="font-bold text-[#686d68] mr-1">近期热点方向:</span>
            <button
              type="button"
              onClick={() => { setSelectedHotTheme('ALL'); setPage(1); }}
              className={`rounded-md px-2.5 py-1 font-bold transition ${
                selectedHotTheme === 'ALL'
                  ? 'bg-amber-700 text-white shadow-xs'
                  : 'border border-amber-200 bg-white text-amber-800 hover:bg-amber-50'
              }`}
            >不限</button>
            <button
              type="button"
              onClick={() => { setSelectedHotTheme('ALL_RECENT'); setPage(1); }}
              className={`rounded-md px-2.5 py-1 font-bold transition ${
                selectedHotTheme === 'ALL_RECENT'
                  ? 'bg-amber-600 text-white shadow-xs'
                  : 'border border-amber-200 bg-white text-amber-800 hover:bg-amber-50'
              }`}
            >全部近期热点</button>
            {hotThemeOptions.map((item) => (
              <button
                key={item.canonical_name}
                type="button"
                onClick={() => { setSelectedHotTheme((current) => current === item.canonical_name ? 'ALL' : item.canonical_name); setPage(1); }}
                className={`rounded-md px-2.5 py-1 font-bold transition ${
                  selectedHotTheme === item.canonical_name
                    ? 'bg-amber-600 text-white shadow-xs'
                    : 'border border-amber-200 bg-white text-amber-800 hover:bg-amber-50'
                }`}
              >
                {item.canonical_name} ({item.match_count})
              </button>
            ))}
            {hotThemeIssue && <span className="text-[11px] font-bold text-rose-700">{hotThemeIssue}</span>}
          </div>
        </div>
      </div>

      {/* 结果数据主表格 */}
      <div className="bg-white rounded-xl border border-[#c4c8bc]/60 shadow-sm overflow-hidden">
        {secondaryMetricsIssue && (
          <div className="flex flex-wrap items-center gap-2 border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900">
            <AlertTriangle className="h-4 w-4 text-amber-700" />
            <span>{secondaryMetricsIssue.message}</span>
            {typeof secondaryMetricsIssue.secondary_snapshot_count === 'number' && typeof secondaryMetricsIssue.early_turn_count === 'number' && (
              <span className="rounded bg-white/80 px-2 py-0.5 font-mono text-amber-800">
                覆盖 {secondaryMetricsIssue.secondary_snapshot_count}/{secondaryMetricsIssue.early_turn_count}
              </span>
            )}
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-[#f0ece4] border-b border-[#c4c8bc]/40 text-[#4a4e4a]">
                <th className="py-3 px-3 font-bold w-48 min-w-[170px]">代码 & 名称</th>
                <th className="py-3 px-3 font-bold w-24">技术得分</th>
                <th className="py-3 px-3 font-bold w-52">最近经营变化</th>
                <th className="py-3 px-3 font-bold w-40">主题内表现</th>
                <th className="py-3 px-3 font-bold w-44">交易容量</th>
                <th className="py-3 px-3 font-bold w-48 max-w-[195px]">题材标签</th>
                <th className="py-3 px-3 font-bold w-36">8大算子摘要</th>
                <th className="py-3 px-3 font-bold w-24">首次入选</th>
                <th className="py-3 px-3 font-bold text-center w-40">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#c4c8bc]/20">
              {loadingStocks ? (
                <tr>
                  <td colSpan={9} className="py-12 text-center text-[#686d68]">
                    <div className="inline-flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin text-[#4a7c59]" />
                      正在加载 Early Turn 评估结果...
                    </div>
                  </td>
                </tr>
              ) : currentItems.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-12 text-center text-[#686d68]">
                    当前筛选条件下暂无 Early Turn 候选。
                  </td>
                </tr>
              ) : (
                currentItems.map((item, idx) => {
                  const s = item.score_detail_json || {};
                  const isSelected = selectedStockIndex === idx;
                  const inPool = aiPoolCodes.includes(item.ts_code);
                  const secondary = secondaryMetricsDate === tradeDate ? secondaryMetrics[item.ts_code] : undefined;
                  const financial = item.financial_facts || {};
                  const latestQuarter = Array.isArray(secondary?.quarter_facts_json) ? secondary?.quarter_facts_json?.[0] : undefined;
                  const factTags = Array.isArray(secondary?.fact_tags_json) ? secondary?.fact_tags_json || [] : [];
                  const secondaryFallbackValue =
                    loadingSecondaryMetrics || secondaryMetricsDate !== tradeDate
                      ? '指标加载中'
                      : secondaryMetricsIssue?.code === 'SECONDARY_SNAPSHOT_INCOMPLETE'
                        ? '待生成'
                        : secondaryMetricsError
                          ? '接口异常'
                        : '暂无详情快照';
                  const secondaryFallbackTone =
                    secondaryMetricsIssue?.code === 'SECONDARY_SNAPSHOT_INCOMPLETE'
                      ? 'bg-amber-50 text-amber-800 border-amber-200'
                      : secondaryMetricsError
                      ? 'bg-rose-50 text-rose-800 border-rose-200'
                      : 'bg-slate-100 text-slate-500 border-slate-200';

                  // 对应状态字体颜色
                  const stateTextColor =
                    item.state === 'FIRST_TURN_WINDOW'
                      ? 'text-emerald-800 font-black'
                    : item.state === 'POST_FIRST_WAVE'
                      ? 'text-rose-800 font-black'
                      : 'text-slate-800 font-bold';

                  return (
                    <tr
                      key={item.ts_code}
                      onClick={() => {
                        setSelectedStockIndex(idx);
                        setDetailStock({
                          tsCode: item.ts_code,
                          stockName: item.name || item.ts_code,
                          initialTab: 'kline',
                        });
                      }}
                      title="点击查看 K 线与股票详情"
                      className={`hover:bg-[#f7f5f0]/80 transition cursor-pointer ${
                        isSelected ? 'bg-[#4a7c59]/10' : ''
                      }`}
                    >
                      {/* 代码 & 名称 (紧凑清晰同行排列) */}
                      <td className="py-3 px-3 space-y-1 select-text cursor-text" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center gap-1.5 min-w-0">
                          <button type="button" onClick={() => void copyStockText(item.ts_code, '股票代码')} className={`font-mono font-black text-xs select-text cursor-copy shrink-0 hover:underline ${stateTextColor}`} title="点击复制股票代码">
                            {item.ts_code}
                          </button>
                          <button type="button" onClick={() => void copyStockText(item.name || '未命名', '股票名称')} className={`max-w-[100px] truncate text-left font-black text-xs select-text cursor-copy hover:underline ${stateTextColor}`} title="点击复制股票名称">
                            {item.name || '未命名'}
                          </button>
                        </div>
                        {item.industry && (
                          <div className="pl-5">
                            <span className="rounded bg-slate-200/70 text-slate-700 px-1.5 py-0.5 text-[10px] font-bold select-text">
                              {item.industry}
                            </span>
                          </div>
                        )}
                      </td>

                      {/* 技术得分与 3 层状态属性 */}
                      <td className="py-3 px-3 space-y-1">
                        <div className="font-mono font-black text-sm text-slate-900">
                          {item.total_score.toFixed(1)}分
                        </div>
                        <div className="flex flex-col gap-1 items-start">
                          {/* 1. Turn Phase (生命周期) */}
                          <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold border ${
                            item.turn_episode_state === 'FIRST_TURN_WINDOW'
                              ? 'bg-emerald-50 text-emerald-800 border-emerald-300'
                              : item.turn_episode_state === 'POST_FIRST_WAVE'
                              ? 'bg-rose-50 text-rose-800 border-rose-300'
                              : 'bg-slate-100 text-slate-700 border-slate-300'
                          }`}>
                            {item.turn_episode_state === 'FIRST_TURN_WINDOW'
                              ? '首次转强'
                              : item.turn_episode_state === 'POST_FIRST_WAVE'
                              ? '第一波已完成'
                              : '底部准备中'}
                          </span>

                          {/* 2. Buy Point Status (买点延伸度 - 仅在延伸/追高时才展示警示徽章) */}
                          {item.is_overextended && (
                            <span className="inline-block rounded px-1.5 py-0.5 text-[10px] font-black border bg-rose-50 text-rose-800 border-rose-300">
                              偏离过大
                            </span>
                          )}
                        </div>
                      </td>

                      {/* 最近经营变化 */}
                      <td className="py-3 px-3 space-y-1">
                        {secondary ? (
                          <div className="flex flex-col items-start gap-1">
                            <MetricChip
                              label="基本面"
                              value={fundamentalFilterLabel(secondary.fundamental_filter_state)}
                              tone={fundamentalFilterTone(secondary.fundamental_filter_state)}
                            />
                            {factTags.slice(0, 2).map((tag) => (
                              <MetricChip key={tag.label || 'tag'} label="标签" value={tag.label || '事实'} tone={factTagTone(tag)} />
                            ))}
                            {latestQuarter ? (
                              <>
                                <MetricChip label={latestQuarter.quarter || latestQuarter.period || '最近Q'} value={`营收 ${formatAmountCompact(latestQuarter.revenue)} · ${formatSignedRatio(latestQuarter.revenue_yoy)}`} tone={metricTone(latestQuarter.revenue_yoy)} />
                                <MetricChip label="归母净利" value={`${formatAmountCompact(latestQuarter.parent_net_profit)} · ${formatSignedRatio(latestQuarter.parent_net_profit_yoy)}`} tone={metricTone(latestQuarter.parent_net_profit_yoy)} />
                                <MetricChip label="经营现金流" value={`${formatAmountCompact(latestQuarter.operating_cashflow)} · ${formatSignedRatio(latestQuarter.operating_cashflow_yoy)}`} tone={metricTone(latestQuarter.operating_cashflow_yoy)} />
                              </>
                            ) : (
                              <MetricChip label="财务" value="暂无季度表" tone="bg-slate-100 text-slate-500 border-slate-200" />
                            )}
                          </div>
                        ) : Object.keys(financial).length > 0 ? (
                          <div className="flex flex-col items-start gap-1">
                            {financial.type && (
                              <MetricChip
                                label="基本面"
                                value={`业绩${String(financial.type)}`}
                                tone={String(financial.type).includes('预增') || String(financial.type).includes('扭亏') ? 'bg-emerald-50 text-emerald-800 border-emerald-200' : String(financial.type).includes('预亏') || String(financial.type).includes('下降') || String(financial.type).includes('首亏') ? 'bg-rose-50 text-rose-800 border-rose-200' : 'bg-slate-50 text-slate-700 border-slate-200'}
                              />
                            )}
                            {financial.total_revenue != null && <MetricChip label="营收" value={formatAmountCompact(financial.total_revenue)} tone="bg-slate-50 text-slate-700 border-slate-200" />}
                            {financial.n_income_attr_p != null && <MetricChip label="归母净利" value={formatAmountCompact(financial.n_income_attr_p)} tone="bg-slate-50 text-slate-700 border-slate-200" />}
                            {financial.n_cashflow_act != null && <MetricChip label="经营现金流" value={formatAmountCompact(financial.n_cashflow_act)} tone="bg-slate-50 text-slate-700 border-slate-200" />}
                          </div>
                        ) : (
                          <MetricChip label="详情" value={secondaryFallbackValue} tone={secondaryFallbackTone} />
                        )}
                      </td>

                      {/* 主题内表现 */}
                      <td className="py-3 px-3 space-y-1">
                        {secondary ? (
                          <div className="flex flex-col items-start gap-1">
                            {secondary.ai_status === 'READY' ? (
                              <MetricChip label="AI研究" value={`已完成${secondary.ai_priority ? ` · ${secondary.ai_priority}` : ''}`} tone="bg-emerald-50 text-emerald-800 border-emerald-200" />
                            ) : (
                              <MetricChip label="AI研究" value="待分析" tone="bg-amber-50 text-amber-800 border-amber-200" />
                            )}
                            <MetricChip label="主题" value={secondary.ai_status === 'READY' ? '已匹配' : '待研究后生成'} tone="bg-indigo-50 text-indigo-800 border-indigo-200" />
                          </div>
                        ) : (
                          <MetricChip label="详情" value={secondaryFallbackValue} tone={secondaryFallbackTone} />
                        )}
                      </td>

                      {/* 交易容量 */}
                      <td className="transaction-capacity-cell py-3 px-3 space-y-1">
                        {secondary ? (
                          <div className="flex flex-col items-start gap-1">
                            <MetricChip label="画像" value={supplyLabelText(secondary.supply_profile_label)} tone="bg-blue-50 text-blue-900 border-blue-200" />
                            <MetricChip label="流通值" value={formatMoneyYi(secondary.free_float_mv)} tone="bg-indigo-50 text-indigo-900 border-indigo-200" />
                            <MetricChip label="20日额" value={formatAmountWan(secondary.amount_median_20)} tone="bg-cyan-50 text-cyan-900 border-cyan-200" />
                            <MetricChip
                              label="解禁/减持"
                              value={`${formatRawPercent(secondary.unlock_30d)} / ${
                                secondary.recent_reduction_flag === null || secondary.recent_reduction_flag === undefined
                                  ? '缺失'
                                  : secondary.recent_reduction_flag
                                    ? '有'
                                    : '无'
                              }`}
                              tone={secondary.recent_reduction_flag ? 'bg-rose-50 text-rose-800 border-rose-200' : metricTone(secondary.unlock_30d, 'percent')}
                            />
                          </div>
                        ) : (
                          <MetricChip label="详情" value={secondaryFallbackValue} tone={secondaryFallbackTone} />
                        )}
                      </td>

                      {/* 题材标签 (收窄宽度，自然换行折叠) */}
                      <td className="py-3 px-3">
                        <div className="flex flex-wrap gap-1 max-w-[195px]">
                          {(() => {
                            const tags = sortConceptTags(
                              Array.isArray(item.ths_concepts) && item.ths_concepts.length > 0
                                ? item.ths_concepts
                                : Array.isArray(item.concepts) && item.concepts.length > 0
                                  ? item.concepts
                                  : []
                            );
                            if (tags.length === 0) {
                              return <span className="text-[11px] font-bold text-slate-400 italic">暂无关联概念</span>;
                            }
                            return (
                              <>
                                {tags.slice(0, 8).map((tag: string) => {
                                  const weak = isLowSignalConcept(tag);
                                  return (
                                    <span
                                      key={tag}
                                      className={`px-1.5 py-0.5 rounded-md border text-[10px] font-black ${
                                        weak
                                          ? 'bg-slate-50 text-slate-500 border-slate-200'
                                          : 'bg-violet-50 text-violet-900 border-violet-200'
                                      }`}
                                    >
                                      {tag}
                                    </span>
                                  );
                                })}
                                {tags.length > 8 && (
                                  <span className="px-1.5 py-0.5 rounded-md bg-slate-100 text-slate-500 border border-slate-200 text-[10px] font-black">
                                    +{tags.length - 8}
                                  </span>
                                )}
                              </>
                            );
                          })()}
                        </div>
                      </td>

                      {/* 8大算子摘要 */}
                      <td className="py-3 px-3">
                        <div className="grid grid-cols-1 gap-1 text-[10px]">
                          <span className="rounded bg-slate-100 text-slate-800 px-1.5 py-0.5 font-bold leading-tight">
                            压缩 {s.compression || 0} / 均线结 {s.knot || 0}
                          </span>
                          <span className="rounded bg-slate-100 text-slate-800 px-1.5 py-0.5 font-bold leading-tight">
                            斜率 {s.slope || 0} / 量能 {s.volume || 0}
                          </span>
                          {item.is_overextended && (
                            <span className="rounded bg-rose-600 text-white px-1.5 py-0.5 font-extrabold leading-tight">
                              偏离过大
                            </span>
                          )}
                        </div>
                      </td>

                      {/* 首次入选 */}
                      <td className="py-3 px-3 font-mono text-[11px] font-bold text-slate-700">
                        {item.first_selected_date || '未首次入选'}
                      </td>

                      {/* 操作 */}
                      <td className="py-3 px-3 text-center">
                        <div className="flex flex-wrap justify-center gap-1">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              void exportSingleStockData(item.ts_code, item.name);
                            }}
                            disabled={exportingSingleStockCode !== null}
                            className="inline-flex items-center gap-1 px-2 py-1 text-[11px] font-black rounded-md bg-white text-[#4a7c59] border border-[#4a7c59]/50 hover:bg-emerald-50 transition disabled:cursor-wait disabled:opacity-60"
                            title="导出与单股测试相同格式的 Markdown 数据"
                          >
                            {exportingSingleStockCode === item.ts_code ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                            单股数据
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleAiPool(item.ts_code);
                            }}
                            className={`inline-flex items-center gap-1 px-2 py-1 text-[11px] font-black rounded-md transition border ${
                              inPool
                                ? 'bg-purple-700 text-white border-purple-700 hover:bg-purple-800'
                                : 'bg-white text-purple-700 border-purple-300 hover:bg-purple-50'
                            }`}
                            title="按空格键 Space 可快捷加入/移出"
                          >
                            <Star className={`w-3.5 h-3.5 ${inPool ? 'fill-white text-white' : 'text-purple-600'}`} />
                            AI池
                          </button>
                        </div>
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

      {/* Floating Toast Notification */}
      {toastMsg && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#2e3230] text-white px-4 py-2.5 rounded-xl text-xs font-bold shadow-2xl flex items-center gap-2 border border-purple-400/40 animate-bounce">
          <Sparkles className="w-4 h-4 text-amber-300 fill-amber-300" />
          <span>{toastMsg}</span>
        </div>
      )}

      {/* 股票抽屉：K 线和详情共用一个入口 */}
      {detailStock && (
        <SecondaryStockDetailDrawer
          isOpen={true}
          onClose={() => {
            setDetailStock(null);
            setSelectedStockIndex(null);
          }}
          tsCode={detailStock.tsCode}
          asOfDate={tradeDate}
          stockName={detailStock.stockName}
          aiRunning={aiResearchRunningCodes.includes(detailStock.tsCode)}
          initialTab={detailStock.initialTab}
          scoreStartDate={selectedStock?.first_selected_date || selectedStock?.trade_date}
          hasPrev={selectedStockIndex !== null && selectedStockIndex > 0}
          hasNext={selectedStockIndex !== null && selectedStockIndex < currentItems.length - 1}
          onNavigatePrev={selectedStockIndex !== null ? () => navigateSelectedStock(-1) : undefined}
          onNavigateNext={selectedStockIndex !== null ? () => navigateSelectedStock(1) : undefined}
          onSpaceToggleWatchlist={() => { void toggleWatchlist(detailStock.tsCode); }}
          watchlistSource={selectedStock ? { type: 'STRATEGY', strategy: 'A_PREV2', stage: selectedStock.state, snapshot_date: selectedStock.trade_date } : undefined}
          onTriggerAI={async (code) => {
            if (aiResearchRunningCodes.includes(code)) return;
            setAiResearchRunningCodes((codes) => Array.from(new Set([...codes, code])));
            const baseUrl = getApiBase();
            try {
              const res = await safeFetch(`${baseUrl}/api/ai/stock-research-async`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                // 后端研究接口字段名为 date；传错为 as_of_date 会回退到服务器当前日期，
                // 导致无法读取该批次对应的事实快照。
                body: JSON.stringify({ ts_codes: [code], date: tradeDate, use_web_search: true }),
              });
              const body = res ? await res.json().catch(() => ({})) : {};
              if (!res || !res.ok) {
                const detail = typeof body?.detail === 'string' ? body.detail : body?.detail?.message;
                throw new Error(detail || `AI 分析失败（HTTP ${res?.status || 'Network Error'}）`);
              }
              const jobId = body?.job_id;
              if (!jobId) throw new Error('AI 分析任务未成功创建');
              for (;;) {
                await new Promise((resolve) => window.setTimeout(resolve, 2000));
                const statusRes = await safeFetch(`${baseUrl}/api/ai/stock-research-status/${encodeURIComponent(jobId)}`);
                const statusBody = statusRes ? await statusRes.json().catch(() => ({})) : {};
                if (!statusRes || !statusRes.ok) {
                  throw new Error(statusBody?.detail || `AI 分析状态读取失败（HTTP ${statusRes?.status || 'Network Error'}）`);
                }
                if (statusBody.status === 'success') break;
                if (statusBody.status === 'failed') {
                  throw new Error(statusBody.error || statusBody.step_message || 'AI 分析失败');
                }
              }
              await loadSecondaryMetrics();
              setToastMsg(`${code} AI 分析已完成`);
              setTimeout(() => setToastMsg(null), 2500);
            } finally {
              setAiResearchRunningCodes((codes) => codes.filter((item) => item !== code));
            }
          }}
        />
      )}

      {/* AI 分析池 Drawer / Modal */}
      {showAiPoolDrawer && (
        <div className="ai-pool-drawer fixed inset-0 z-50 flex items-center justify-end bg-black/50 backdrop-blur-xs select-none">
          <div className="w-full max-w-lg h-full bg-white shadow-2xl border-l border-[#c4c8bc]/60 flex flex-col p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-[#c4c8bc]/40 pb-4">
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-purple-600" />
                <h3 className="font-bold text-slate-800 text-base">AI 分析池</h3>
                <span className="px-2 py-0.5 rounded-full bg-purple-100 text-purple-700 font-bold text-xs font-mono">
                  {aiPoolCodes.length} 只股票
                </span>
              </div>
              <button
                onClick={() => setShowAiPoolDrawer(false)}
                className="text-slate-400 hover:text-slate-700 font-bold text-lg px-2"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-slate-500">
              已收集放入 AI 分析池的标的。支持在列表、K 线图中随手按<span className="font-bold text-purple-700 bg-purple-50 px-1 py-0.5 rounded">空格键 (Space)</span>无缝加入/移出。
            </p>

            <div className="flex-1 overflow-y-auto space-y-2 pr-1">
              {aiPoolCodes.length === 0 ? (
                <div className="text-center py-16 text-slate-400 space-y-2 text-xs">
                  <p>AI 分析池暂无标的</p>
                  <p className="text-[11px] text-slate-400">在任意列表或 K 线图浏览时按空格键 (Space) 即可放入</p>
                </div>
              ) : (
                aiPoolCodes.map((code) => {
                  const queueStatus = aiStatuses[code]?.status;
                  const isCompleted = queueStatus === 'success' || aiCompletedCodes.includes(code);
                  const isProcessing = queueStatus === 'running' || aiProcessingCode === code;
                  const isFailed = queueStatus === 'failed';
                  const isQueued = queueStatus === 'queued' || (!isCompleted && !isProcessing && aiQueueRunning);
                  return (
                    <div key={code} className="flex items-center justify-between p-3 bg-[#faf6f0] rounded-xl border border-[#c4c8bc]/40">
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <button type="button" onClick={() => void copyStockText(code, '股票代码')} title="点击复制股票代码" className="font-mono text-sm font-bold text-slate-800 hover:underline">
                            {code}
                          </button>
                          {isCompleted && (
                            <span className="px-2 py-0.5 rounded-md bg-emerald-100 text-emerald-700 font-bold text-[11px] flex items-center gap-1">
                              ✓ 已完成
                            </span>
                          )}
                          {isProcessing && (
                            <span className="px-2 py-0.5 rounded-md bg-purple-100 text-purple-700 font-bold text-[11px] flex items-center gap-1 animate-pulse">
                              <div className="w-2.5 h-2.5 rounded-full border-2 border-purple-700 border-t-transparent animate-spin" />
                              分析中...
                            </span>
                          )}
                          {isFailed && (
                            <span title={aiStatuses[code]?.error || 'AI 研究失败'} className="px-2 py-0.5 rounded-md bg-rose-100 text-rose-700 font-bold text-[11px]">
                              分析失败
                            </span>
                          )}
                          {isQueued && !isProcessing && !isFailed && (
                            <span className="px-2 py-0.5 rounded-md bg-slate-100 text-slate-500 font-bold text-[11px]">
                              等待中
                            </span>
                          )}
                        </div>
                        <div className="text-[11px] text-slate-500">技术生命周期请在上方结果表查看</div>
                      </div>
                      <div className="flex items-center gap-2">
                        {isCompleted && (
                          <button
                            onClick={() => {
                              setSelectedStockIndex(null);
                              setDetailStock({ tsCode: code, stockName: code, initialTab: 'detail' });
                              setShowAiPoolDrawer(false);
                            }}
                            className="px-2.5 py-1 text-xs text-purple-700 hover:bg-purple-50 rounded border border-purple-300 font-bold"
                          >
                            查看 AI 分析结论
                          </button>
                        )}
                        <button
                          onClick={() => toggleAiPool(code)}
                          disabled={aiQueueRunning && isProcessing}
                          className="px-2.5 py-1 text-xs text-rose-600 hover:bg-rose-50 rounded border border-rose-200 font-bold disabled:opacity-40"
                        >
                          移除
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            <div className="border-t border-[#c4c8bc]/40 pt-4 flex items-center justify-between gap-3">
              {aiQueueRunning ? (
                <button
                  onClick={() => { cancelAiQueueRef.current = true; }}
                  className="w-full px-4 py-2.5 bg-rose-600 text-white rounded-xl text-xs font-bold hover:bg-rose-700 shadow-md flex items-center justify-center gap-1.5"
                >
                  <span>⏹ 取消剩余股票 AI 分析</span>
                </button>
              ) : (
                <>
                  <button
                    onClick={clearAiPool}
                    disabled={aiPoolCodes.length === 0}
                    className="px-4 py-2 bg-slate-100 text-slate-600 rounded-xl text-xs font-bold hover:bg-slate-200 disabled:opacity-40"
                  >
                    清空分析池
                  </button>
                  <button
                    onClick={async () => {
                      if (aiPoolCodes.length === 0 || aiQueueRunning) return;
                      setAiQueueRunning(true);
                      cancelAiQueueRef.current = false;
                      setAiStatuses(Object.fromEntries(aiPoolCodes.map((item) => [item, { status: 'queued' as const }])));

                      for (let i = 0; i < aiPoolCodes.length; i++) {
                        if (cancelAiQueueRef.current) break;
                        const code = aiPoolCodes[i];
                        setAiProcessingCode(code);
                        setAiStatuses((prev) => ({ ...prev, [code]: { status: 'running' } }));
                        try {
                        const baseUrl = getApiBase();
                          const submitRes = await safeFetch(`${baseUrl}/api/ai/stock-research-async`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ ts_codes: [code], date: tradeDate, use_web_search: true }),
                          });
                          const submitBody = submitRes ? await submitRes.json().catch(() => ({})) : {};
                          if (!submitRes || !submitRes.ok || !submitBody.job_id) throw new Error(submitBody?.detail || 'AI 任务提交失败');
                          for (;;) {
                            await new Promise((resolve) => window.setTimeout(resolve, 2000));
                            const statusRes = await safeFetch(`${baseUrl}/api/ai/stock-research-status/${encodeURIComponent(submitBody.job_id)}`);
                            const statusBody = statusRes ? await statusRes.json().catch(() => ({})) : {};
                            if (!statusRes || !statusRes.ok) throw new Error(statusBody?.detail || 'AI 任务状态读取失败');
                            if (statusBody.status === 'success') break;
                            if (statusBody.status === 'failed') throw new Error(statusBody.error || 'AI 研究失败');
                          }
                          setAiCompletedCodes((prev) => [...prev, code]);
                          setAiStatuses((prev) => ({ ...prev, [code]: { status: 'success' } }));
                        } catch (e) {
                          console.warn(`AI research for ${code} failed:`, e);
                          setAiStatuses((prev) => ({ ...prev, [code]: { status: 'failed', error: e instanceof Error ? e.message : 'AI 研究失败' } }));
                        }
                      }

                      setAiProcessingCode(null);
                      setAiQueueRunning(false);
                      void loadStocks();
                    }}
                    disabled={aiPoolCodes.length === 0}
                    className="flex-1 px-4 py-2.5 bg-gradient-to-r from-purple-700 to-indigo-700 text-white rounded-xl text-xs font-bold hover:opacity-95 shadow-md flex items-center justify-center gap-1.5 disabled:opacity-40"
                  >
                    <Sparkles className="w-4 h-4 text-amber-300" />
                    <span>一键执行 AI 深度分析 ({aiPoolCodes.length}只)</span>
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
        </>
      ) : null}

      {/* 运行评估配置 Modal */}
      {showRunConfigModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4">
          <div className="bg-white rounded-xl p-6 w-full max-w-md border border-[#c4c8bc]/60 shadow-2xl space-y-4 select-none">
            <div className="flex items-center justify-between border-b pb-3 border-[#c4c8bc]/40">
              <h3 className="font-bold text-sm text-[#2e3230] flex items-center gap-2">
                <PlayCircle className="w-5 h-5 text-[#4a7c59]" />
                <span>配置本次选股评估任务</span>
              </h3>
              <button onClick={() => setShowRunConfigModal(false)} className="text-slate-400 hover:text-slate-700 font-bold">
                ✕
              </button>
            </div>

            <div className="space-y-3.5 text-xs">
              <div>
                <label className="block font-bold text-[#2e3230] mb-1">选股批次名称:</label>
                <input
                  type="text"
                  value={newRunName}
                  onChange={(e) => setNewRunName(e.target.value)}
                  placeholder="例如: 2026-08-17 强转强复盘"
                  className="w-full bg-[#faf6f0] border border-[#c4c8bc]/60 rounded-lg px-3 py-2 font-bold outline-none text-[#2e3230] focus:border-[#4a7c59]"
                  autoFocus
                />
              </div>

              <div>
                <label className="block font-bold text-[#2e3230] mb-1.5">评估目标范围 (Universe):</label>
                <div className="grid grid-cols-3 gap-1.5">
                  <button
                    type="button"
                    onClick={() => setUniverseType('ALL')}
                    className={`px-2.5 py-2 rounded-lg font-bold text-xs border transition text-center cursor-pointer ${
                      universeType === 'ALL'
                        ? 'bg-[#4a7c59] text-white border-[#4a7c59] shadow-xs'
                        : 'bg-[#faf6f0] text-slate-700 border-[#c4c8bc]/60 hover:bg-slate-100'
                    }`}
                  >
                    🌐 全市场
                  </button>
                  <button
                    type="button"
                    onClick={() => setUniverseType('CONCEPTS')}
                    className={`px-2.5 py-2 rounded-lg font-bold text-xs border transition text-center cursor-pointer ${
                      universeType === 'CONCEPTS'
                        ? 'bg-[#705c30] text-white border-[#705c30] shadow-xs'
                        : 'bg-[#faf6f0] text-slate-700 border-[#c4c8bc]/60 hover:bg-slate-100'
                    }`}
                  >
                    🔥 概念板块
                  </button>
                  <button
                    type="button"
                    onClick={() => setUniverseType('CUSTOM_CODES')}
                    className={`px-2.5 py-2 rounded-lg font-bold text-xs border transition text-center cursor-pointer ${
                      universeType === 'CUSTOM_CODES'
                        ? 'bg-[#2e3230] text-white border-[#2e3230] shadow-xs'
                        : 'bg-[#faf6f0] text-slate-700 border-[#c4c8bc]/60 hover:bg-slate-100'
                    }`}
                  >
                    🎯 指定股票
                  </button>
                </div>

                {/* 2. 同花顺概念板块选择器 (支持搜索、勾选多选与手动带出) */}
                {universeType === 'CONCEPTS' && (
                  <div className="mt-2.5 space-y-2 bg-[#faf6f0] p-3 rounded-lg border border-[#c4c8bc]/60">
                    <div className="flex items-center justify-between">
                      <label className="block font-bold text-[#705c30] text-xs">
                        同花顺概念板块 (可搜索/勾选或手动输入):
                      </label>
                      {selectedConcepts.length > 0 && (
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedConcepts([]);
                            setConceptInput('');
                          }}
                          className="text-[10px] text-rose-700 hover:underline font-bold"
                        >
                          清空已选({selectedConcepts.length})
                        </button>
                      )}
                    </div>

                    {/* 已勾选的 Gem/Chip 概念标签展示 */}
                    {selectedConcepts.length > 0 && (
                      <div className="flex flex-wrap gap-1 bg-white p-2 rounded-lg border border-[#c4c8bc]/50 max-h-20 overflow-y-auto">
                        {selectedConcepts.map((concept) => (
                          <span
                            key={concept}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold bg-[#705c30] text-white shadow-xs"
                          >
                            <span>{concept}</span>
                            <button
                              type="button"
                              onClick={() => {
                                const next = selectedConcepts.filter((c) => c !== concept);
                                setSelectedConcepts(next);
                                setConceptInput(next.join(', '));
                              }}
                              className="hover:text-amber-200 font-black cursor-pointer ml-0.5"
                            >
                              ✕
                            </button>
                          </span>
                        ))}
                      </div>
                    )}

                    {/* 概念搜索与手动输入框 */}
                    <div className="flex items-center gap-1.5 bg-white border border-[#c4c8bc]/60 rounded-lg px-2.5 py-1.5 focus-within:border-[#705c30]">
                      <Search className="w-3.5 h-3.5 text-[#686d68] shrink-0" />
                      <input
                        type="text"
                        value={conceptSearch}
                        onChange={(e) => {
                          const val = e.target.value;
                          setConceptSearch(val);
                          setConceptInput(val);
                        }}
                        placeholder="输入或搜索概念，如: 半导体, 人形机器人..."
                        className="w-full bg-transparent outline-none font-bold text-xs text-[#2e3230]"
                      />
                      {conceptSearch && (
                        <button
                          type="button"
                          onClick={() => {
                            setConceptSearch('');
                            setConceptInput(selectedConcepts.join(', '));
                          }}
                          className="text-slate-400 hover:text-slate-600 font-bold text-xs"
                        >
                          ✕
                        </button>
                      )}
                    </div>

                    {/* 可选/匹配到的概念标签池 (点击自动多选) */}
                    <div className="space-y-1">
                      <div className="flex items-center justify-between text-[10px] text-slate-500 font-bold">
                        <span>{conceptSearch.trim() ? '🔍 匹配到的概念:' : '💡 常用/可选概念板块 (点击多选):'}</span>
                        <span>共 {filteredConceptsList.length} 个板块</span>
                      </div>
                      <div className="flex flex-wrap gap-1 max-h-32 overflow-y-auto p-1.5 bg-white/70 rounded-lg border border-[#c4c8bc]/40">
                        {filteredConceptsList.slice(0, 40).map((concept) => {
                          const isSelected = selectedConcepts.includes(concept);
                          return (
                            <button
                              key={concept}
                              type="button"
                              onClick={() => {
                                let next: string[];
                                if (isSelected) {
                                  next = selectedConcepts.filter((c) => c !== concept);
                                } else {
                                  next = [...selectedConcepts, concept];
                                }
                                setSelectedConcepts(next);
                                setConceptInput(next.join(', '));
                              }}
                              className={`px-2 py-0.5 rounded text-[11px] font-bold border transition cursor-pointer flex items-center gap-1 ${
                                isSelected
                                  ? 'bg-[#705c30] text-white border-[#705c30] shadow-xs'
                                  : 'bg-white text-slate-700 border-slate-300 hover:bg-amber-50 hover:border-amber-300'
                              }`}
                            >
                              <span>{isSelected ? '✓' : '+'}</span>
                              <span>{concept}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                )}

                {/* 3. 自定义股票代码/名称范围 */}
                {universeType === 'CUSTOM_CODES' && (
                  <div className="mt-2.5 space-y-2 bg-[#faf6f0] p-3 rounded-lg border border-[#c4c8bc]/60">
                    <div className="flex items-center justify-between">
                      <label className="block font-bold text-[#2e3230]">股票代码或名称 (多只股票分隔输入):</label>
                      <button
                        type="button"
                        onClick={() => {
                          if (watchlistCodes.length > 0) {
                            setCustomCodes(watchlistCodes.join(', '));
                          }
                        }}
                        className="text-[11px] text-[#4a7c59] hover:underline font-bold"
                      >
                        一键载入自选股({watchlistCodes.length}只)
                      </button>
                    </div>
                    <textarea
                      value={customCodes}
                      onChange={(e) => setCustomCodes(e.target.value)}
                      rows={2}
                      placeholder="支持代码或名称混输，如: 600683, 紫光股份, 002550, 600216"
                      className="w-full bg-white border border-[#c4c8bc]/60 rounded-lg px-2.5 py-1.5 font-mono font-bold outline-none text-[#2e3230] text-xs focus:border-[#2e3230]"
                    />
                    <div className="flex flex-wrap gap-1">
                      <span className="text-[10px] text-slate-500 font-bold self-center">快速点选范例:</span>
                      {[
                        { code: '600683.SH', name: '京投发展' },
                        { code: '000938.SZ', name: '紫光股份' },
                        { code: '000750.SZ', name: '国海证券' },
                        { code: '600216.SH', name: '浙江医药' },
                      ].map((item) => (
                        <button
                          key={item.code}
                          type="button"
                          onClick={() => {
                            if (!customCodes.includes(item.code)) {
                              setCustomCodes(customCodes ? `${customCodes}, ${item.code}` : item.code);
                            }
                          }}
                          className="px-1.5 py-0.5 bg-white hover:bg-slate-100 border border-slate-300 rounded text-[10px] font-mono text-slate-700 font-bold transition cursor-pointer"
                        >
                          + {item.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div>
                <label className="block font-bold text-[#2e3230] mb-1">评估截止交易日:</label>
                <input
                  type="date"
                  value={modalTradeDate.length === 8 ? `${modalTradeDate.slice(0, 4)}-${modalTradeDate.slice(4, 6)}-${modalTradeDate.slice(6, 8)}` : modalTradeDate}
                  onChange={(e) => {
                    const val = e.target.value.replace(/-/g, '');
                    setModalTradeDate(val);
                  }}
                  className="w-full bg-[#faf6f0] border border-[#c4c8bc]/60 rounded-lg px-3 py-2 font-mono font-bold outline-none text-[#2e3230] focus:border-[#4a7c59]"
                />
              </div>

              <div>
                <label className="block font-bold text-[#2e3230] mb-1">选股备注说明 (选填):</label>
                <textarea
                  value={newRunNotes}
                  onChange={(e) => setNewRunNotes(e.target.value)}
                  rows={2}
                  placeholder="如: 重点关注突破前高、均线金叉放量标的..."
                  className="w-full bg-[#faf6f0] border border-[#c4c8bc]/60 rounded-lg px-3 py-2 font-bold outline-none text-[#2e3230] focus:border-[#4a7c59]"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#c4c8bc]/40">
              <button
                onClick={() => setShowRunConfigModal(false)}
                className="px-3.5 py-1.5 bg-slate-100 text-slate-600 text-xs font-bold rounded-lg hover:bg-slate-200"
              >
                取消
              </button>
              <button
                onClick={() => handleTriggerRun()}
                className="px-4 py-1.5 bg-[#4a7c59] text-white text-xs font-bold rounded-lg hover:bg-[#3b6447] shadow-xs flex items-center gap-1.5"
              >
                <PlayCircle className="w-4 h-4" />
                <span>立即启动选股</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 历史选股管理 Modal */}
      {showHistoryModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4">
          <div className="bg-white rounded-xl p-6 w-full max-w-2xl border border-[#c4c8bc]/60 shadow-2xl space-y-4 select-none max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between border-b pb-3 border-[#c4c8bc]/40">
              <h3 className="font-bold text-sm text-[#2e3230] flex items-center gap-2">
                <History className="w-5 h-5 text-[#705c30]" />
                <span>📜 历史选股记录管理 ({historyRuns.length} 次)</span>
              </h3>
              <button onClick={() => setShowHistoryModal(false)} className="text-slate-400 hover:text-slate-700 font-bold">
                ✕
              </button>
            </div>

            <div className="flex-1 overflow-y-auto space-y-2 pr-1">
              {historyRuns.length === 0 ? (
                <div className="text-center py-16 text-slate-400 font-bold text-xs space-y-1">
                  <p>暂无历史选股批次记录</p>
                  <p className="text-[11px] font-normal text-slate-400">每次运行评估均会自动保存为独立批次</p>
                </div>
              ) : (
                historyRuns.map((run) => (
                  <div
                    key={run.run_id}
                    className="p-3.5 bg-[#faf6f0] hover:bg-[#f2ece0] rounded-xl border border-[#c4c8bc]/50 transition flex items-center justify-between gap-4"
                  >
                    <div className="space-y-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-black text-sm text-slate-900 truncate">{run.run_name || run.run_id}</span>
                        <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 font-mono font-bold text-[11px]">
                          {run.trade_date}
                        </span>
                        <span className="px-2 py-0.5 rounded bg-purple-100 text-purple-700 font-mono font-bold text-[11px]">
                          {run.candidate_count} 只命中
                        </span>
                      </div>
                      {run.notes && (
                        <p className="text-xs text-slate-600 font-medium truncate">{run.notes}</p>
                      )}
                      <div className="text-[10px] font-mono text-slate-400">
                        运行时间: {run.started_at ? run.started_at.slice(0, 19).replace('T', ' ') : '近期'}
                      </div>
                    </div>

                    <button
                      onClick={() => openHistoryTab({ run_id: run.run_id, run_name: run.run_name, trade_date: run.trade_date })}
                      className="px-3.5 py-1.5 bg-[#2e3230] text-white hover:bg-[#1f2321] text-xs font-black rounded-lg transition shrink-0 shadow-xs flex items-center gap-1"
                    >
                      <span>打开标签卡</span>
                      <ChevronRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
