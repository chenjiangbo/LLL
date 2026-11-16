'use client';

import { doubleBottomLabel } from './doubleBottomLabel';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  X,
  Sparkles,
  Building2,
  TrendingUp,
  Layers,
  Tag,
  Bot,
  History,
  Info,
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
  FlaskConical,
  ChartNoAxesCombined,
  Activity,
  Loader2,
  RefreshCw,
  ArrowUp,
  ArrowDown,
  Network,
} from 'lucide-react';
import KLineModal from './KLineModal';

interface SecondaryStockDetailDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  tsCode: string;
  asOfDate: string;
  stockName?: string;
  onTriggerAI: (tsCode: string) => Promise<void> | void;
  onTriggerThemeMatch?: (tsCode: string) => Promise<void> | void;
  onRunBasicAnalysis?: (tsCode: string) => Promise<void> | void;
  basicAnalysisRunning?: boolean;
  computeOnOpen?: boolean;
  /** Current profiles are shared across review and screening; date stays for K-line/technical context. */
  useCurrentProfiles?: boolean;
  aiRunning?: boolean;
  initialTab?: 'detail' | 'kline';
  scoreStartDate?: string;
  onNavigatePrev?: () => void;
  onNavigateNext?: () => void;
  hasPrev?: boolean;
  hasNext?: boolean;
  onSpaceToggleWatchlist?: () => void;
  watchlistSource?: { type: 'MANUAL' | 'STRATEGY'; strategy?: string; stage?: string; snapshot_date?: string };
}

type MetricItem = {
  label: string;
  value: React.ReactNode;
  tone?: 'default' | 'good' | 'warn' | 'bad' | 'muted';
};

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;
if (!API_BASE) {
  throw new Error('NEXT_PUBLIC_MARKET_REVIEW_API_URL is required');
}

const toNumberOrNull = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

const isMissing = (value: unknown): boolean => {
  return value === null || value === undefined || value === '';
};

const textValue = (value: unknown): string => {
  if (isMissing(value)) return '暂无';
  return String(value);
};

const formatNumber = (value: unknown, digits = 1, suffix = ''): string => {
  const n = toNumberOrNull(value);
  return n === null ? '暂无' : `${n.toFixed(digits)}${suffix}`;
};

const formatPercentRatio = (value: unknown, digits = 1): string => {
  const n = toNumberOrNull(value);
  if (n === null) return '暂无';
  return `${n >= 0 ? '+' : ''}${(n * 100).toFixed(digits)}%`;
};

const formatPercentValue = (value: unknown, digits = 2): string => {
  const n = toNumberOrNull(value);
  return n === null ? '暂无' : `${n.toFixed(digits)}%`;
};

const formatMoneyYi = (value: unknown, digits = 1): string => {
  const n = toNumberOrNull(value);
  return n === null ? '暂无' : `${n.toFixed(digits)} 亿元`;
};

const formatAmountYuan = (value: unknown): string => {
  const n = toNumberOrNull(value);
  if (n === null) return '暂无';
  if (Math.abs(n) >= 100000000) return `${(n / 100000000).toFixed(2)} 亿元`;
  if (Math.abs(n) >= 10000) return `${(n / 10000).toFixed(1)} 万元`;
  return `${n.toFixed(0)} 元`;
};

const formatSignedRatio = (value: unknown): string => {
  const n = toNumberOrNull(value);
  if (n === null) return '暂无';
  return `${n >= 0 ? '+' : ''}${(n * 100).toFixed(1)}%`;
};

const formatBool = (value: unknown): string => {
  if (value === true) return '是';
  if (value === false) return '否';
  return '暂无';
};

const STATUS_TEXT: Record<string, string> = {
  EARLY_TURN: '早期转强',
  EARLY_TURN_STRICT: '严格早期转强',
  PRE_READY: '预备转强',
  PRE_READY_STRICT: '严格预备转强',
  WATCH: '观察',
  TOO_LATE: '过度延伸',
  NO_SIGNAL: '无信号',
  FIRST_TURN: '首次转向',
  PRE_FIRST_TURN: '底部准备',
  FIRST_TURN_WINDOW: '首次转强',
  POST_FIRST_WAVE: '第一波已完成',
  OUTSIDE_A_PRE: '未进入 A-Pre',
  SECONDARY_TURN: '二次转强',
  CONSOLIDATION_RESTART: '整理再启动',
  REVERSAL_BASE: '下降筑底反转',
  BOTTOM_REBOUND: '底部反弹',
  POSITIVE: '正向边际',
  MIXED: '证据混合',
  RISK: '风险',
  UNKNOWN: '暂无判断',
  INSUFFICIENT_EVIDENCE: '证据不足',
  LEADING: '领先',
  ABOVE_AVERAGE: '偏强',
  NEUTRAL: '中性',
  LAGGING: '落后',
  MICRO_ELASTIC: '微盘弹性',
  SMALL_ELASTIC: '小盘弹性',
  MID_CAP: '中等容量',
  LARGE_CAPACITY: '大容量',
  MEGA_CAPACITY: '超大容量',
  DATA_MISSING: '暂无数据',
  CURRENT_REFERENCE_ONLY: '当前标签参考',
  NO_ACTIVE_THEME_MATCH: '未匹配近期主题',
  PENDING_THEME_MATCH: '待 AI 主题匹配',
  PIT_SAFE: '按当日可见数据',
  READY: '就绪',
  STALE: '需重新分析',
  CONFIG_REQUIRED: '需要配置',
  PERMISSION_BLOCKED: '权限受限',
  PROFIT_GROWING: '利润增长',
  PROFIT_DECLINING: '利润下滑',
  TURNAROUND: '扭亏为盈',
  LOSS_NARROWING: '亏损收窄',
  LOSS_WIDENING: '亏损扩大',
  PARENT_LOSS_WIDENING: '归母亏损扩大',
  DEDUCTED_LOSS_WIDENING: '扣非亏损扩大',
  TURN_TO_LOSS: '由盈转亏',
  DONE: '已完成',
  SUCCESS: '成功',
  FAILED: '失败',
  ERROR: '错误',
  REVENUE_SHARP_DROP: '营收大幅下降',
  PROFIT_SHARP_DROP: '利润大幅下降',
  CASHFLOW_DETERIORATION: '经营现金流恶化',
  MARGIN_COMPRESSION: '毛利率下滑',
  THEME_MISMATCH: '题材匹配不足',
  FUNDAMENTAL_ACCEPTABLE: '可接受',
  FUNDAMENTAL_POSITIVE: '经营向好',
  FUNDAMENTAL_RISK: '存在风险',
  FUNDAMENTAL_DATA_INSUFFICIENT: '数据不足',
};

const statusText = (status?: unknown): string => {
  if (isMissing(status)) return '暂无';
  const raw = String(status);
  return STATUS_TEXT[raw] || raw;
};

const riskFlagText = (flag: unknown, detail: Record<string, any>): string => {
  const raw = String(flag || '');
  if (raw !== 'LOSS_WIDENING') return statusText(raw);

  const parentWidening = detail.parent_profit_state === 'LOSS_WIDENING';
  const deductedWidening = detail.deducted_profit_state === 'LOSS_WIDENING';
  if (parentWidening && deductedWidening) return '归母及扣非亏损扩大';
  if (parentWidening) return '归母亏损扩大';
  if (deductedWidening) return '扣非亏损扩大';
  return statusText(raw);
};

const bilingualStatus = (status?: unknown): string => {
  if (isMissing(status)) return '暂无';
  const raw = String(status);
  const zh = STATUS_TEXT[raw];
  return zh ? `${raw}（${zh}）` : raw;
};

const statusTone = (status?: string): 'good' | 'warn' | 'bad' | 'muted' => {
  if (!status) return 'muted';
  if (['READY', 'POSITIVE', 'LEADING', 'ABOVE_AVERAGE', 'DONE', 'SUCCESS', 'FUNDAMENTAL_POSITIVE'].includes(status)) return 'good';
  if (['RISK', 'FAILED', 'ERROR', 'FUNDAMENTAL_RISK'].includes(status)) return 'bad';
  if (['MIXED', 'INSUFFICIENT_EVIDENCE', 'CURRENT_REFERENCE_ONLY', 'NO_ACTIVE_THEME_MATCH', 'PENDING_THEME_MATCH', 'CONFIG_REQUIRED', 'PERMISSION_BLOCKED', 'DATA_MISSING', 'FUNDAMENTAL_DATA_INSUFFICIENT', 'STALE'].includes(status)) return 'warn';
  return 'muted';
};

const toneClass = (tone: MetricItem['tone'] = 'default'): string => {
  if (tone === 'good') return 'text-emerald-800';
  if (tone === 'warn') return 'text-amber-800';
  if (tone === 'bad') return 'text-rose-800';
  if (tone === 'muted') return 'text-slate-500';
  return 'text-slate-900';
};

const statusPillClass = (tone: ReturnType<typeof statusTone>): string => {
  if (tone === 'good') return 'bg-emerald-50 text-emerald-800 border-emerald-200';
  if (tone === 'bad') return 'bg-rose-50 text-rose-800 border-rose-200';
  if (tone === 'warn') return 'bg-amber-50 text-amber-800 border-amber-200';
  return 'bg-slate-100 text-slate-700 border-slate-200';
};

const readableMissingField = (field: string): string => {
  const map: Record<string, string> = {
    income_vip: '利润表',
    cashflow_vip: '现金流量表',
    fina_indicator_vip: '财务指标',
    forecast_vip: '业绩预告',
    express_vip: '业绩快报',
    deducted_net_profit_amount: '扣非净利润金额',
    gross_profit_amount: '毛利金额',
  };
  return map[field] || field;
};

function MetricGrid({ items }: { items: MetricItem[] }) {
  return (
    <dl className="grid grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-3">
      {items.map((item) => (
        <div key={item.label} className={`min-w-0 border-b border-[#d8d1c4]/60 pb-2 ${item.label === '当前结果' ? 'col-span-2 lg:col-span-4' : ''}`}>
          <dt className="text-[11px] font-bold text-[#686d68] truncate">{item.label}</dt>
          <dd className={`mt-1 text-sm font-black break-words ${item.label === '当前结果' ? 'lg:whitespace-nowrap' : ''} ${toneClass(item.tone)}`}>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ReasonMessage({ message }: { message: unknown }) {
  const text = String(message ?? '').trim();
  const segments = text.split(/(?=\d+[.)、]\s+)/).map((segment) => segment.trim()).filter(Boolean);
  const numbered = segments.length > 1 && segments.every((segment) => /^\d+[.)、]\s+/.test(segment));
  if (!numbered) return <span>{text}</span>;
  return (
    <span className="block space-y-2">
      {segments.map((segment, index) => {
        const match = segment.match(/^(\d+)[.)、]\s+([\s\S]*)$/);
        return (
          <span key={`${match?.[1] || index}-${index}`} className="block">
            {match ? <><span className="mr-1 font-black text-[#4a7c59]">{match[1]}.</span>{match[2]}</> : segment}
          </span>
        );
      })}
    </span>
  );
}

function ReasonList({ title, reasons }: { title: string; reasons: any[] }) {
  if (!Array.isArray(reasons) || reasons.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="text-sm font-black text-[#4f554f]">{title}</div>
      <div className="space-y-1">
        {reasons.map((reason, idx) => {
          const type = String(reason?.type || 'INFO');
          const Icon = type === 'RISK' || type === 'WARNING' ? AlertTriangle : type === 'POSITIVE' ? CheckCircle2 : HelpCircle;
          return (
            <div key={`${type}-${idx}`} className="flex items-start gap-2 text-sm leading-6 text-slate-700">
              <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${type === 'RISK' || type === 'WARNING' ? 'text-amber-700' : type === 'POSITIVE' ? 'text-emerald-700' : 'text-slate-500'}`} />
              <ReasonMessage message={reason?.msg || String(reason)} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StatusPill({ label, status }: { label: string; status?: string }) {
  const tone = statusTone(status);
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-black ${statusPillClass(tone)}`}>
      <span className="text-slate-500">{label}</span>
      <span>{statusText(status)}</span>
    </span>
  );
}

function InfoHint({ text }: { text: string }) {
  return (
    <details className="relative inline-block">
      <summary className="flex h-5 w-5 cursor-pointer list-none items-center justify-center rounded-full text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 [&::-webkit-details-marker]:hidden">
        <Info className="h-3.5 w-3.5" />
      </summary>
      <div className="absolute right-0 top-6 z-10 w-72 rounded-md border border-slate-200 bg-white p-3 text-xs font-bold leading-relaxed text-slate-700 shadow-xl">
        {text}
      </div>
    </details>
  );
}

function FactTagPill({ tag }: { tag: any }) {
  const tone = tag?.tone === 'RISK'
    ? 'border-rose-200 bg-rose-50 text-rose-800'
    : tag?.tone === 'POSITIVE'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
      : 'border-amber-200 bg-amber-50 text-amber-900';
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-1 text-[11px] font-black ${tone}`}>
      {tag?.label || '事实标签'}
    </span>
  );
}

function QuarterFactsTable({ facts }: { facts: any[] }) {
  if (!Array.isArray(facts) || facts.length === 0) {
    return <div className="text-xs font-bold text-slate-500">当前日期前暂无可展示的季度财务数据。</div>;
  }
  return (
    <div className="overflow-x-auto rounded-md border border-[#d8d1c4]/70">
      <table className="min-w-full text-left text-xs">
        <thead className="bg-[#f0ece4] text-[#4a4e4a]">
          <tr>
            <th className="px-3 py-2 font-black">季度</th>
            <th className="px-3 py-2 font-black">公告日</th>
            <th className="px-3 py-2 font-black">营收</th>
            <th className="px-3 py-2 font-black">营收同比</th>
            <th className="px-3 py-2 font-black">归母净利</th>
            <th className="px-3 py-2 font-black">归母净利同比</th>
            <th className="px-3 py-2 font-black">扣非净利</th>
            <th className="px-3 py-2 font-black">扣非净利同比</th>
            <th className="px-3 py-2 font-black">经营现金流</th>
            <th className="px-3 py-2 font-black">毛利率</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#d8d1c4]/60 bg-white">
          {facts.slice(0, 8).map((fact, idx) => (
            <tr key={`${fact.period || idx}`}>
              <td className="px-3 py-2 font-mono font-black text-slate-900">{fact.quarter || fact.period || '暂无'}</td>
              <td className="px-3 py-2 font-mono text-slate-600">{textValue(fact.available_date)}</td>
              <td className="px-3 py-2 font-black text-slate-900">{formatAmountYuan(fact.revenue)}</td>
              <td className="px-3 py-2 font-bold text-slate-700">{formatSignedRatio(fact.revenue_yoy)}</td>
              <td className="px-3 py-2 font-black text-slate-900">{formatAmountYuan(fact.parent_net_profit)}</td>
              <td className="px-3 py-2 font-bold text-slate-700">{formatSignedRatio(fact.parent_net_profit_yoy)}</td>
              <td className="px-3 py-2 font-black text-slate-900">{formatAmountYuan(fact.deducted_net_profit)}</td>
              <td className="px-3 py-2 font-bold text-slate-700">{formatSignedRatio(fact.deducted_net_profit_yoy)}</td>
              <td className="px-3 py-2 font-black text-slate-900">{formatAmountYuan(fact.operating_cashflow)}</td>
              <td className="px-3 py-2 font-bold text-slate-700">{formatPercentRatio(fact.gross_margin)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AiMarkdown({ text }: { text: string }) {
  const inline = (value: string): React.ReactNode => value.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith('**') && part.endsWith('**')
      ? <strong key={index} className="font-extrabold text-[#1f2923]">{part.slice(2, -2)}</strong>
      : part
  );
  const parseTableRow = (line: string) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
  const isTableSeparator = (line: string) => {
    const cells = parseTableRow(line);
    return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
  };
  const lines = text.split(/\r?\n/);
  const blocks: React.ReactNode[] = [];

  for (let index = 0; index < lines.length;) {
    const value = lines[index].trim();
    if (value.includes('|') && index + 1 < lines.length && isTableSeparator(lines[index + 1])) {
      const headers = parseTableRow(value);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].trim().includes('|')) {
        rows.push(parseTableRow(lines[index]));
        index += 1;
      }
      blocks.push(
        <div key={`table-${index}`} className="overflow-x-auto rounded-md border border-[#d8d1c4] bg-white">
          <table className="min-w-full text-left text-xs leading-5">
            <thead className="bg-[#f3efe8] text-[#4b504c]">
              <tr>{headers.map((header, headerIndex) => <th key={headerIndex} className="whitespace-nowrap px-3 py-2 font-black">{inline(header)}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-[#e5dfd5] text-[#2e3230]">
              {rows.map((row, rowIndex) => <tr key={rowIndex}>{headers.map((_, columnIndex) => <td key={columnIndex} className="align-top px-3 py-2">{inline(row[columnIndex] || '')}</td>)}</tr>)}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (!value) blocks.push(<div key={`blank-${index}`} className="h-1" />);
    else if (value.startsWith('### ')) blocks.push(<h4 key={index} className="pt-2 text-sm font-black text-violet-700">{inline(value.slice(4))}</h4>);
    else if (value.startsWith('## ')) blocks.push(<h3 key={index} className="pt-3 text-base font-black text-[#2e3230]">{inline(value.slice(3))}</h3>);
    else if (value.startsWith('# ')) blocks.push(<h2 key={index} className="pt-2 text-lg font-black text-[#2e3230]">{inline(value.slice(2))}</h2>);
    else if (/^[-*]\s+/.test(value)) blocks.push(<div key={index} className="flex gap-2 pl-2"><span className="text-violet-600">•</span><span>{inline(value.replace(/^[-*]\s+/, ''))}</span></div>);
    else blocks.push(<p key={index}>{inline(value)}</p>);
    index += 1;
  }
  return <div className="space-y-2 text-sm leading-7 text-[#2e3230]">{blocks}</div>;
}

function Section({
  icon,
  title,
  help,
  status,
  headerExtra,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  help?: string;
  status?: string;
  headerExtra?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-[#d8d1c4] py-5 first:border-t-0 first:pt-0">
      <div className="mb-4 flex flex-nowrap items-center justify-between gap-3">
        <h3 className="flex shrink-0 items-center gap-2 text-base font-black text-[#2e3230]">
          {icon}
          <span>{title}</span>
          {help && <InfoHint text={help} />}
        </h3>
        <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
          {headerExtra}
          {status && <StatusPill label="状态" status={status} />}
        </div>
      </div>
      {children}
    </section>
  );
}

export const SecondaryStockDetailDrawer: React.FC<SecondaryStockDetailDrawerProps> = ({
  isOpen,
  onClose,
  tsCode,
  asOfDate,
  stockName,
  onTriggerAI,
  onTriggerThemeMatch,
  onRunBasicAnalysis,
  basicAnalysisRunning = false,
  computeOnOpen = true,
  useCurrentProfiles = true,
  aiRunning = false,
  initialTab = 'kline',
  scoreStartDate,
  onNavigatePrev,
  onNavigateNext,
  hasPrev = false,
  hasNext = false,
  onSpaceToggleWatchlist,
  watchlistSource,
}) => {
  const [detailData, setDetailData] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [entered, setEntered] = useState(false);
  const [copyNotice, setCopyNotice] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'detail' | 'kline'>(initialTab);
  const [localAiRunning, setLocalAiRunning] = useState(false);
  const [localThemeMatchRunning, setLocalThemeMatchRunning] = useState(false);
  const [themeMatchError, setThemeMatchError] = useState<string | null>(null);
  const [localBasicAnalysisRunning, setLocalBasicAnalysisRunning] = useState(false);
  const [basicAnalysisError, setBasicAnalysisError] = useState<string | null>(null);
  const [strategyTestRequest, setStrategyTestRequest] = useState(0);
  const [conceptRefreshRunning, setConceptRefreshRunning] = useState(false);
  const [conceptRefreshError, setConceptRefreshError] = useState<string | null>(null);
  const themeStatusJobRef = useRef<string | null>(null);

  const fetchDetail = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/candidate-secondary/${encodeURIComponent(tsCode)}?date=${encodeURIComponent(asOfDate)}&compute=${computeOnOpen ? 'true' : 'false'}&profile_mode=${useCurrentProfiles ? 'current' : 'selection'}`);
      if (!res.ok) {
        throw new Error(`Fetch secondary detail failed: ${res.status}`);
      }
      const json = await res.json();
      setDetailData(json);
    } catch (e) {
      console.error('Fetch secondary detail failed:', e);
      setDetailData(null);
    } finally {
      setLoading(false);
    }
  }, [tsCode, asOfDate, computeOnOpen, useCurrentProfiles]);

  useEffect(() => {
    if (isOpen && tsCode && asOfDate) {
      void Promise.resolve().then(fetchDetail);
    }
  }, [isOpen, tsCode, asOfDate, fetchDetail]);

  useEffect(() => {
    if (isOpen) return;
    setThemeMatchError(null);
    setLocalThemeMatchRunning(false);
    themeStatusJobRef.current = null;
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || !tsCode) return;
    let disposed = false;
    const checkThemeJob = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/ai/stock-theme-match-status/by-stock/${encodeURIComponent(tsCode)}`, { cache: 'no-store' });
        if (!res.ok || disposed) return;
        const job = await res.json();
        if (job.status === 'queued' || job.status === 'running') {
          themeStatusJobRef.current = job.job_id || null;
          setLocalThemeMatchRunning(true);
          return;
        }
        if (themeStatusJobRef.current) {
          themeStatusJobRef.current = null;
          setLocalThemeMatchRunning(false);
          void fetchDetail();
        }
      } catch {
        // The detail view remains usable if the optional task-status check is unavailable.
      }
    };
    void checkThemeJob();
    const timer = window.setInterval(checkThemeJob, 3000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [isOpen, tsCode, fetchDetail]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => setEntered(isOpen));
    return () => window.cancelAnimationFrame(frame);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = originalOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const detail = detailData?.detail || {};
  const conceptsInfo = detailData?.concepts_info || {};
  const aiResearch = detailData?.ai_research || {};
  const companyProfile = detail.company_profile && typeof detail.company_profile === 'object' ? detail.company_profile : {};
  const companyKeyPoints = Array.isArray(companyProfile.key_points) ? companyProfile.key_points : [];
  const companyBusinessEvidence = Array.isArray(companyProfile.business_evidence) ? companyProfile.business_evidence : [];
  const companySources = Array.isArray(companyProfile.sources) ? companyProfile.sources : [];
  const currentThemeContext = companyProfile.market_context && typeof companyProfile.market_context === 'object' ? companyProfile.market_context : null;
  const conceptsList = Array.isArray(conceptsInfo.concepts) ? conceptsInfo.concepts : [];
  const riskFlags = Array.isArray(detail.risk_flags_json) ? detail.risk_flags_json : [];
  const quarterFacts = Array.isArray(detail.quarter_facts_json) ? detail.quarter_facts_json : [];
  const factTags = Array.isArray(detail.fact_tags_json) ? detail.fact_tags_json : [];
  const dataQuality = detail.data_quality_json || {};
  const missingFields = Array.isArray(dataQuality.missing_fields) ? dataQuality.missing_fields : [];
  const aiStatus = aiRunning ? '分析中' : (aiResearch?.status || '未分析');
  const basicAnalysisPending = detailData?.research_snapshot_status === 'NOT_COMPUTED';
  const selectionChanges = Array.isArray(detailData?.selection_changes) ? detailData.selection_changes : [];
  const isAiRunning = aiRunning || localAiRunning;
  const themeMatchReady = detail.theme_match_status === 'READY' || Boolean(aiResearch?.status);
  const isThemeMatchRunning = localThemeMatchRunning;
  const handleTriggerThemeMatch = async () => {
    if (!onTriggerThemeMatch || isThemeMatchRunning) return;
    setThemeMatchError(null);
    setLocalThemeMatchRunning(true);
    try {
      await onTriggerThemeMatch(tsCode);
    } catch (error) {
      setThemeMatchError(error instanceof Error ? error.message : '主题匹配暂时无法完成');
    } finally {
      // Theme tags may have been saved even when company-introduction research
      // failed, so refresh the drawer for either terminal outcome.
      await fetchDetail();
      setLocalThemeMatchRunning(false);
    }
  };
  const handleTriggerAI = async () => {
    if (isAiRunning) return;
    setLocalAiRunning(true);
    try {
      await onTriggerAI(tsCode);
      await fetchDetail();
    } finally {
      setLocalAiRunning(false);
    }
  };
  const isBasicAnalysisRunning = basicAnalysisRunning || localBasicAnalysisRunning;
  const handleRunBasicAnalysis = async () => {
    if (isBasicAnalysisRunning) return;
    setBasicAnalysisError(null);
    setLocalBasicAnalysisRunning(true);
    try {
      if (onRunBasicAnalysis) {
        await onRunBasicAnalysis(tsCode);
      } else {
        const response = await fetch(`${API_BASE}/api/stock-profiles/${encodeURIComponent(tsCode)}/fundamental/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
          const detail = typeof body?.detail === 'string' ? body.detail : body?.detail?.message;
          throw new Error(detail || `基本面分析失败（HTTP ${response.status}）`);
        }
      }
      await fetchDetail();
    } catch (error) {
      setBasicAnalysisError(error instanceof Error ? error.message : '基本面分析失败');
    } finally {
      setLocalBasicAnalysisRunning(false);
    }
  };
  const handleRefreshConcepts = async () => {
    if (conceptRefreshRunning) return;
    setConceptRefreshError(null);
    setConceptRefreshRunning(true);
    try {
      const res = await fetch(`${API_BASE}/api/data/ths-concepts/stock/${encodeURIComponent(tsCode)}/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: asOfDate }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = typeof body?.detail === 'string' ? body.detail : body?.detail?.message;
        throw new Error(detail || `同花顺概念更新失败（HTTP ${res.status}）`);
      }
      await fetchDetail();
    } catch (error) {
      setConceptRefreshError(error instanceof Error ? error.message : '同花顺概念更新失败');
    } finally {
      setConceptRefreshRunning(false);
    }
  };
  const copyStockText = async (value: string, label: string) => {
    await navigator.clipboard.writeText(value);
    setCopyNotice(`已复制${label}：${value}`);
    window.setTimeout(() => setCopyNotice(null), 1800);
  };

  const companyMetrics: MetricItem[] = [
    { label: '营业收入', value: formatAmountYuan(detail.revenue) },
    { label: '营收同比', value: formatPercentRatio(detail.revenue_yoy), tone: isMissing(detail.revenue_yoy) ? 'muted' : 'default' },
    { label: '归母净利润', value: formatAmountYuan(detail.parent_net_profit) },
    { label: '归母净利润同比', value: formatPercentRatio(detail.parent_net_profit_yoy), tone: isMissing(detail.parent_net_profit_yoy) ? 'muted' : 'default' },
    { label: '归母利润变化', value: statusText(detail.parent_profit_state), tone: statusTone(detail.parent_profit_state) },
    { label: '扣非净利润', value: formatAmountYuan(detail.deducted_net_profit) },
    { label: '扣非净利润同比', value: formatPercentRatio(detail.deducted_net_profit_yoy), tone: isMissing(detail.deducted_net_profit_yoy) ? 'muted' : 'default' },
    { label: '扣非利润变化', value: statusText(detail.deducted_profit_state), tone: statusTone(detail.deducted_profit_state) },
    { label: '经营现金流', value: formatAmountYuan(detail.operating_cashflow) },
    { label: '经营现金流同比', value: formatPercentRatio(detail.operating_cashflow_yoy), tone: isMissing(detail.operating_cashflow_yoy) ? 'muted' : 'default' },
    { label: '毛利率', value: formatPercentRatio(detail.gross_margin) },
    { label: '毛利率同比变化', value: formatPercentRatio(detail.gross_margin_yoy_delta) },
    { label: '最新报告期', value: textValue(detail.latest_report_period) },
    { label: '报告公告日', value: textValue(detail.latest_report_ann_date) },
    { label: '业绩预告类型', value: textValue(detail.forecast_type) },
    { label: '业绩预告公告日', value: textValue(detail.forecast_ann_date) },
    { label: '预告变动下限', value: formatPercentValue(detail.forecast_p_change_min) },
    { label: '预告变动上限', value: formatPercentValue(detail.forecast_p_change_max) },
    { label: '预告净利润下限', value: formatNumber(detail.forecast_net_profit_min, 1, ' 万元') },
    { label: '预告净利润上限', value: formatNumber(detail.forecast_net_profit_max, 1, ' 万元') },
    { label: '快报报告期', value: textValue(detail.express_end_date) },
    { label: '快报公告日', value: textValue(detail.express_ann_date) },
    { label: '快报营业收入', value: formatAmountYuan(detail.express_revenue) },
    { label: '快报净利润', value: formatAmountYuan(detail.express_n_income) },
    { label: '快报净利润同比', value: formatPercentRatio(detail.express_yoy_net_profit) },
    { label: '快报摘要', value: textValue(detail.express_summary) },
  ];

  const aiThemeName = isMissing(detail.ai_theme_name)
    ? (isMissing(detail.theme_match_name) ? '' : String(detail.theme_match_name))
    : String(detail.ai_theme_name);
  const matchedThemeConcepts = Array.isArray(detail.ai_theme_concept_names)
    ? detail.ai_theme_concept_names.map((name: unknown) => String(name)).filter(Boolean)
    : (Array.isArray(detail.theme_match_concept_names)
      ? detail.theme_match_concept_names.map((name: unknown) => String(name)).filter(Boolean)
      : []);
  const isMatchedThemeConcept = (conceptName: string): boolean => {
    return matchedThemeConcepts.includes(conceptName);
  };

  const supplyMetrics: MetricItem[] = [
    { label: '收盘价', value: formatNumber(detail.close, 2) },
    { label: '总股本', value: formatNumber(detail.total_share, 2, ' 万股') },
    { label: '流通股本', value: formatNumber(detail.float_share, 2, ' 万股') },
    { label: '总市值', value: formatMoneyYi(detail.total_mv) },
    { label: '流通市值', value: formatMoneyYi(detail.circ_mv) },
    { label: '自由流通股本', value: formatNumber(detail.free_share, 2, ' 万股') },
    { label: '自由流通市值', value: formatMoneyYi(detail.free_float_mv), tone: isMissing(detail.free_float_mv) ? 'muted' : 'default' },
    { label: '成交额', value: formatAmountYuan(detail.amount) },
    { label: '20日成交额中位数', value: formatAmountYuan(detail.amount_median_20) },
    { label: '成交放量倍数', value: formatNumber(detail.volume_ratio, 2) },
    { label: '换手率', value: formatPercentValue(detail.turnover_rate) },
    { label: '自由流通换手率', value: formatPercentValue(detail.turnover_rate_f) },
    { label: '30日解禁', value: formatPercentValue(detail.unlock_30d) },
    { label: '60日解禁', value: formatPercentValue(detail.unlock_60d) },
    { label: '90日解禁', value: formatPercentValue(detail.unlock_90d) },
    { label: '近期减持标记', value: formatBool(detail.recent_reduction_flag) },
  ];

  return (
    <div
      className="secondary-stock-drawer fixed inset-0 z-50 flex justify-end overflow-hidden bg-black/45 backdrop-blur-xs"
      onMouseDown={onClose}
      onWheel={(event) => event.stopPropagation()}
    >
      <div
        className={`flex h-full w-full max-w-5xl flex-col border-l border-[#c4c8bc] bg-[#faf6f0] shadow-2xl transition-transform duration-300 ease-out ${
          entered ? 'translate-x-0' : 'translate-x-full'
        }`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        {/* 吸顶工具栏：股票信息、视图切换与操作放在同一行，避免占用内容高度 */}
        <div className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-[#c4c8bc]/70 bg-white px-6 py-2.5 shadow-xs">
          <div className="flex min-w-0 items-center gap-2 overflow-hidden">
            <button type="button" onClick={() => void copyStockText(tsCode, '股票代码')} title="点击复制股票代码" className="rounded-md bg-[#2e3230] px-3 py-1 font-mono text-sm font-black text-white hover:bg-[#454a47]">
              {tsCode}
            </button>
            <button type="button" onClick={() => void copyStockText(stockName || detail.name || tsCode, '股票名称')} title="点击复制股票名称" className="truncate text-left text-lg font-black text-[#2e3230] hover:underline">
              {stockName || detail.name || tsCode}
            </button>
            <StatusPill label="行业" status={detail.industry} />
          </div>

          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            <div className="inline-flex items-center rounded-md border border-[#c4c8bc] bg-[#faf6f0] p-0.5">
              <button
                type="button"
                onClick={() => setActiveTab('kline')}
                aria-pressed={activeTab === 'kline'}
                className={`rounded px-3 py-1.5 text-xs font-black transition ${activeTab === 'kline' ? 'bg-[#2e3230] text-white shadow-xs' : 'text-slate-500 hover:bg-white hover:text-slate-800'}`}
              >
                K 线
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('detail')}
                aria-pressed={activeTab === 'detail'}
                className={`rounded px-3 py-1.5 text-xs font-black transition ${activeTab === 'detail' ? 'bg-[#2e3230] text-white shadow-xs' : 'text-slate-500 hover:bg-white hover:text-slate-800'}`}
              >
                详情
              </button>
            </div>
            {onTriggerThemeMatch && (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => void handleTriggerThemeMatch()}
                  disabled={isThemeMatchRunning || isAiRunning}
                  className="inline-flex items-center gap-1.5 rounded-md border border-[#d7a64a] bg-[#fff8e8] px-3.5 py-1.5 text-xs font-black text-[#8a5a00] shadow-xs transition hover:border-[#b88325] hover:bg-[#fff1c9] disabled:cursor-wait disabled:opacity-60"
                  title="匹配近期市场主题，并联网核验企业业务、上下游与产业链位置"
                >
                  {isThemeMatchRunning ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Layers className="h-4 w-4" aria-hidden="true" />}
                  <span>{isThemeMatchRunning ? '匹配中…' : '主题匹配'}</span>
                </button>
                {themeMatchError && (
                  <div role="alert" className="absolute right-0 top-full z-40 mt-1 flex w-72 items-start gap-2 rounded-md border border-[#d8c6a2] bg-[#fff8e8] px-2.5 py-2 text-[11px] font-bold leading-relaxed text-[#705c30] shadow-lg">
                    <p className="min-w-0 flex-1">{themeMatchError}</p>
                    <button type="button" onClick={() => setThemeMatchError(null)} aria-label="关闭主题匹配错误提示" className="shrink-0 rounded px-1 text-sm leading-none text-[#705c30]/70 hover:bg-[#f3e7cf] hover:text-[#705c30]">×</button>
                  </div>
                )}
              </div>
            )}
            <button
              onClick={() => void handleTriggerAI()}
              disabled={isAiRunning || !themeMatchReady}
              title={themeMatchReady ? '基于已完成的主题匹配开展完整 AI 研究' : '请先完成左侧的主题匹配'}
              className="inline-flex items-center gap-1.5 rounded-md bg-gradient-to-r from-[#8b00ff] via-[#6d28d9] to-[#4338ca] px-3.5 py-1.5 text-xs font-black text-white shadow-[0_6px_16px_rgba(91,33,182,0.28)] transition hover:from-[#7c00e8] hover:via-[#5b21b6] hover:to-[#3730a3] disabled:cursor-wait disabled:opacity-60"
            >
              {isAiRunning ? (
                <Loader2 className="h-4 w-4 animate-spin text-white" aria-hidden="true" />
              ) : (
                <Sparkles className="h-4 w-4 text-amber-300" aria-hidden="true" />
              )}
              <span>{isAiRunning ? '分析中…' : 'AI 分析'}</span>
            </button>
            <button
              type="button"
              onClick={() => void handleRunBasicAnalysis()}
              disabled={isBasicAnalysisRunning}
              className="inline-flex items-center gap-1.5 rounded-md border border-[#aa9a78] bg-[#e8dfcf] px-3.5 py-1.5 text-xs font-black text-[#5d4b24] shadow-xs transition hover:border-[#8e805f] hover:bg-[#ded2bd] disabled:cursor-wait disabled:opacity-60"
            >
              {isBasicAnalysisRunning ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ChartNoAxesCombined className="h-4 w-4" aria-hidden="true" />}
              <span>{isBasicAnalysisRunning ? '计算中…' : '基本面分析'}</span>
            </button>
            <button
              type="button"
              onClick={() => setStrategyTestRequest((request) => request + 1)}
              className="inline-flex items-center gap-1.5 rounded-md border border-[#9bb8a4] bg-[#f0f6f1] px-3.5 py-1.5 text-xs font-black text-[#39704d] shadow-xs transition hover:border-[#4a7c59] hover:bg-[#e4f0e6]"
              title="选择策略和时间范围，临时显示单股测试得分"
            >
              <FlaskConical className="h-4 w-4" aria-hidden="true" />
              <span>单股测试</span>
            </button>
            <button
              onClick={onClose}
              className="rounded-md p-1.5 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
              aria-label="关闭抽屉"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {copyNotice && <div className="absolute left-1/2 top-16 z-40 -translate-x-1/2 rounded-md bg-[#2e3230] px-3 py-1.5 text-xs font-bold text-white shadow-lg">{copyNotice}</div>}

        {activeTab === 'kline' ? (
          <div className="min-h-0 flex-1 overflow-hidden px-3 pb-3 pt-0" onWheel={(event) => event.stopPropagation()}>
            <KLineModal
              embedded
              isOpen={isOpen}
              onClose={onClose}
              assetCode={tsCode}
              assetName={stockName || detail.name || tsCode}
              industry={detail.industry}
              hasPrev={hasPrev}
              hasNext={hasNext}
              onNavigatePrev={onNavigatePrev}
              onNavigateNext={onNavigateNext}
              showSubIndicators={true}
              showAiPoolButton={true}
              showWatchlistButton={true}
              strategyTestRequest={strategyTestRequest}
              onSpaceToggleWatchlist={onSpaceToggleWatchlist}
              watchlistSource={watchlistSource}
            />
          </div>
          ) : (
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {loading ? (
            <div className="py-24 text-center text-sm font-bold text-[#686d68]">正在加载详情...</div>
          ) : !detailData ? (
            <div className="py-24 text-center text-sm font-bold text-rose-700">详情加载失败，请查看后端日志。</div>
          ) : (
            <div className="space-y-5 rounded-md bg-white px-5 py-5 shadow-xs ring-1 ring-[#d8d1c4]/70">
              {basicAnalysisPending && (
                <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-xs font-bold leading-relaxed text-amber-900">
                  股票基础财务数据已加载。点击右上角“基本面分析”后，系统会按 {asOfDate} 当日可见的数据计算自动选股所需的经营标签、风险标签和交易画像。
                </div>
              )}
              {basicAnalysisError && (
                <div className="rounded-md border border-rose-200 bg-rose-50 p-4 text-xs font-bold leading-relaxed text-rose-900">
                  基本面分析失败：{basicAnalysisError}
                </div>
              )}
              {/* 业务描述与概念标签 (在页面主体内连贯滚动) */}
              <div className="space-y-3 border-b border-[#d8d1c4] pb-4">
                {(companyProfile.summary || companyKeyPoints.length > 0) ? (
                  <div className="space-y-2 rounded-md border border-emerald-200 bg-emerald-50/60 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-sm font-black text-emerald-950">企业业务简介</h3>
                      {detail.company_profile_refreshed_at && (
                        <span className="text-[10px] font-bold text-emerald-800">已联网核验</span>
                      )}
                    </div>
                    {companyProfile.summary && (
                      <p className="text-xs font-bold leading-relaxed text-emerald-950">{companyProfile.summary}</p>
                    )}
                    {companyKeyPoints.length > 0 && (
                      <ul className="list-disc space-y-1 pl-4 text-xs font-bold leading-relaxed text-emerald-950">
                        {companyKeyPoints.map((point: unknown, index: number) => <li key={`company-point-${index}`}>{String(point)}</li>)}
                      </ul>
                    )}
                    {companyBusinessEvidence.length > 0 && (
                      <p className="text-[11px] font-bold leading-relaxed text-emerald-900">
                        <span className="text-emerald-700">业务证据：</span>{companyBusinessEvidence.map(String).join('；')}
                      </p>
                    )}
                    {currentThemeContext?.summary && (
                      <div className="border-t border-emerald-200 pt-2 text-xs leading-relaxed text-slate-800">
                        <div className="mb-1 flex flex-wrap items-center gap-2">
                          <span className="font-black text-amber-800">当前题材关联</span>
                          {currentThemeContext.theme_name && <span className="rounded-full bg-amber-100 px-2 py-0.5 font-bold text-amber-900">{String(currentThemeContext.theme_name)}</span>}
                          {currentThemeContext.relationship_type && <span className="text-[10px] font-bold text-slate-500">{{
                            DIRECT_BUSINESS: '公司主营业务',
                            COMPANY_PRODUCT_OR_PROJECT: '公司产品/项目',
                            PARENT_OR_SHAREHOLDER_RESOURCE: '控股股东资源',
                            MARKET_ASSOCIATION: '市场关联',
                            NO_VERIFIED_RELATION: '暂无可核实的直接关联',
                          }[String(currentThemeContext.relationship_type)] || '关联类型待核实'}</span>}
                          {currentThemeContext.as_of_date && <span className="text-[10px] font-bold text-slate-500">截至 {String(currentThemeContext.as_of_date)}</span>}
                          {currentThemeContext.evidence_type && <span className="text-[10px] font-bold text-slate-500">{{
                            COMPANY_DISCLOSURE: '公司披露',
                            PUBLIC_SOURCE: '公开资料',
                            MARKET_INFERENCE: '市场推演',
                            UNCONFIRMED: '尚未核实',
                          }[String(currentThemeContext.evidence_type)] || '依据待核实'}</span>}
                        </div>
                        <p className="font-medium">{String(currentThemeContext.summary)}</p>
                        {currentThemeContext.boundary && <p className="mt-1 font-bold text-rose-800">{String(currentThemeContext.boundary)}</p>}
                        {Array.isArray(currentThemeContext.sources) && currentThemeContext.sources.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                            {currentThemeContext.sources.map((source: any, index: number) => (
                              <a key={`theme-context-source-${index}`} className="text-[10px] font-bold text-emerald-800 underline" href={String(source.url || '#')} target="_blank" rel="noreferrer">
                                {String(source.title || '题材依据')}
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                    <div className="grid gap-2 md:grid-cols-3">
                      <div className="rounded-lg border border-amber-500 bg-[#d88900] p-3 text-[11px] font-bold leading-relaxed text-white shadow-sm">
                        <div className="mb-1.5 flex items-center gap-1.5 text-xs font-black text-white">
                          <ArrowUp className="h-3.5 w-3.5" aria-hidden="true" />
                          <span>上游环节</span>
                        </div>
                        <p>{textValue(companyProfile.upstream)}</p>
                      </div>
                      <div className="rounded-lg border border-blue-500 bg-[#2563a8] p-3 text-[11px] font-bold leading-relaxed text-white shadow-sm">
                        <div className="mb-1.5 flex items-center gap-1.5 text-xs font-black text-white">
                          <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
                          <span>下游应用</span>
                        </div>
                        <p>{textValue(companyProfile.downstream)}</p>
                      </div>
                      <div className="rounded-lg border border-fuchsia-500 bg-[#8b3fb8] p-3 text-[11px] font-bold leading-relaxed text-white shadow-sm">
                        <div className="mb-1.5 flex items-center gap-1.5 text-xs font-black text-white">
                          <Network className="h-3.5 w-3.5" aria-hidden="true" />
                          <span>产业链位置</span>
                        </div>
                        <p>{textValue(companyProfile.positioning)}</p>
                      </div>
                    </div>
                    {companySources.length > 0 && (
                      <details className="text-[11px] font-bold text-emerald-900">
                        <summary className="cursor-pointer">查看资料来源（{companySources.length}）</summary>
                        <ul className="mt-1 space-y-1 pl-4">
                          {companySources.map((source: any, index: number) => (
                            <li key={`company-source-${index}`}>
                              <a className="underline hover:text-emerald-700" href={String(source.url || '#')} target="_blank" rel="noreferrer">
                                {String(source.title || source.url || '公开资料')}
                              </a>
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                ) : null}
                {detail.main_business && (
                  <p className="text-xs font-bold leading-relaxed text-[#686d68]">{detail.main_business}</p>
                )}
                <div className="flex flex-wrap gap-1.5">
                  {conceptsList.length > 0 ? conceptsList.map((concept: any) => (
                    <span
                      key={`${concept.ths_code || concept.ths_name}`}
                      className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-black ${isMatchedThemeConcept(String(concept.ths_name || concept.name || concept)) ? 'border-amber-400 bg-amber-100 text-amber-950 ring-1 ring-amber-300' : 'border-purple-200 bg-purple-50 text-purple-900'}`}
                      title={concept.type_label || concept.raw_type || ''}
                    >
                      <Tag className="h-3 w-3" />
                      {concept.ths_name || concept.name || String(concept)}
                    </span>
                  )) : (
                    <span className="text-xs font-bold text-slate-500">暂无同花顺标签</span>
                  )}
                </div>
                {conceptsInfo.temporal_notice && (
                  <div className="flex items-center gap-1.5 text-[11px] font-bold text-amber-800">
                    <span>{conceptsInfo.temporal_notice}</span>
                    <button
                      type="button"
                      onClick={() => void handleRefreshConcepts()}
                      disabled={conceptRefreshRunning}
                      className="inline-flex shrink-0 items-center justify-center rounded p-1 text-[#705c30] transition hover:bg-[#705c30]/10 disabled:cursor-wait disabled:opacity-60"
                      title="更新当前股票的同花顺概念标签"
                      aria-label="更新当前股票的同花顺概念标签"
                    >
                      <RefreshCw className={`h-3.5 w-3.5 ${conceptRefreshRunning ? 'animate-spin' : ''}`} />
                    </button>
                  </div>
                )}
                {conceptRefreshError && <p className="text-[11px] font-bold text-rose-700">同花顺概念更新失败：{conceptRefreshError}</p>}
                <div className="flex flex-wrap gap-2 pt-1">
                  <span className="inline-flex items-center rounded-md border border-slate-300 bg-slate-50 px-2 py-1 text-[11px] font-black text-slate-800">技术分 {formatNumber(detail.aprev2_score, 1)}</span>
                  <StatusPill label="生命周期" status={detail.aprev2_status} />
                  <span className="inline-flex items-center rounded-md border border-slate-300 bg-slate-50 px-2 py-1 text-[11px] font-black text-slate-800">类型 {statusText(detail.turn_type)}</span>
                  {(() => {
                    const quality = detail.bottom_structure_quality || detail.features_json?.bottom_structure_quality;
                    if (!quality || quality === 'NONE') return null;
                    const features = detail.features_json || {};
                    const title = `第一底 ${detail.bottom_first_low_date || features.bottom_first_low_date || '-'} · 第二底 ${detail.bottom_second_low_date || features.bottom_second_low_date || '-'} · 确认 ${detail.bottom_structure_confirmed_date || features.bottom_structure_confirmed_date || '-'}`;
                    return (
                      <span
                        title={title}
                        className={`inline-flex items-center rounded-md border px-2 py-1 text-[11px] font-black ${quality === 'CLEAR' ? 'border-emerald-300 bg-emerald-50 text-emerald-900' : 'border-amber-300 bg-amber-50 text-amber-900'}`}
                      >
                        {doubleBottomLabel(detail.bottom_structure_type || detail.features_json?.bottom_structure_type, quality)}
                      </span>
                    );
                  })()}
                  <StatusPill label="基本面" status={detail.fundamental_filter_state} />
                  <StatusPill label="经营" status={detail.company_evidence_state || detail.evidence_state} />
                  <StatusPill label="主题" status={detail.leadership_state || (detail.theme_match_status === 'READY' ? (aiThemeName ? 'READY' : 'NO_ACTIVE_THEME_MATCH') : 'PENDING_THEME_MATCH')} />
                  <StatusPill label="交易" status={detail.supply_profile_label} />
                </div>
              </div>

              <Section
                icon={<Building2 className="h-5 w-5 text-emerald-700" />}
                title="最近经营变化"
                help="这里看公司最近几个季度的收入、利润、现金流有没有变化。表里的季度数据按公告日期控制，只使用查看日期前已经公开的数据。"
                headerExtra={
                  <div className="flex min-w-0 flex-nowrap items-center justify-end gap-2 overflow-x-auto">
                    {factTags.map((tag: any, idx: number) => <FactTagPill key={`header-fact-${idx}`} tag={tag} />)}
                    {riskFlags.map((flag: any, idx: number) => (
                      <span key={`header-risk-${idx}`} className="inline-flex items-center rounded-md border border-rose-300 bg-rose-100 px-2 py-1 text-[11px] font-black text-rose-900">
                        风险：{riskFlagText(flag, detail)}
                      </span>
                    ))}
                  </div>
                }
              >
                <div className="mb-4 flex flex-wrap gap-2">
                  {factTags.length === 0 && riskFlags.length === 0 && <span className="text-xs font-bold text-slate-500">暂无明显经营变化标签</span>}
                </div>
                <MetricGrid
                  items={[
                    { label: '最新报告期', value: textValue(detail.latest_report_period) },
                    { label: '报告公告日', value: textValue(detail.latest_report_ann_date) },
                    { label: '业绩预告类型', value: textValue(detail.forecast_type) },
                    { label: '快报报告期', value: textValue(detail.express_end_date) },
                  ]}
                />
                <div className="mt-4">
                  <QuarterFactsTable facts={quarterFacts} />
                </div>
                <details className="mt-4 rounded-md border border-[#d8d1c4]/70 bg-[#faf6f0] p-3">
                  <summary className="cursor-pointer text-xs font-black text-[#686d68]">展开更多财务明细</summary>
                  <div className="mt-3 space-y-4">
                    <MetricGrid items={companyMetrics} />
                    {missingFields.length > 0 && (
                      <div className="flex items-center gap-1 text-xs font-bold text-amber-800">
                        <span>这些明细当前暂时看不到：{missingFields.map(readableMissingField).join('、')}</span>
                        <InfoHint text="这不是说没有这只股票的数据，而是当前详情页还没有拿到这些更细的财务字段；能展示的收入、归母净利、现金流、预告和快报仍按已公开数据展示。" />
                      </div>
                    )}
                  </div>
                </details>
              </Section>

              <Section
                icon={<Layers className="h-5 w-5 text-amber-700" />}
                title="主题内表现"
                help="先运行主题匹配，判断这只股票与近期市场主题的关系；完成完整 AI 分析后，再补充同主题内的涨幅和成交额排名。"
                headerExtra={aiThemeName ? <span className="inline-flex items-center rounded-full border border-amber-300 bg-amber-100 px-3 py-1 text-xs font-black text-amber-950">近期相关主题：{aiThemeName}</span> : null}
              >
                {detail.ai_theme_relative?.total_members ? (
                  <div className="mb-4 border-b border-[#d8d1c4]/60 pb-3">
                    <div className="text-sm font-black text-[#686d68]">当前结果</div>
                    <div className="mt-1 text-base font-black leading-7 text-emerald-800">
                      {detail.ai_theme_relative.total_members} 只成员 · 15日涨幅 {Number(detail.ai_theme_relative.stock_pct_change ?? 0) >= 0 ? '+' : ''}{detail.ai_theme_relative.stock_pct_change}%（第 {detail.ai_theme_relative.pct_rank} 名）· 5日均额 {detail.ai_theme_relative.avg_amount_5d_yi} 亿元（第 {detail.ai_theme_relative.amount_rank} 名）
                    </div>
                  </div>
                ) : (
                  <div className="mb-4 border-b border-[#d8d1c4]/60 pb-3">
                    <div className="text-sm font-black text-[#686d68]">当前结果</div>
                    <div className="mt-1 text-sm font-bold text-amber-800">{detail.theme_match_status === 'NOT_RUN' ? '尚未进行主题匹配' : aiThemeName ? '主题已匹配，完整 AI 分析后生成主题内排名' : '当前未识别到近期相关主题'}</div>
                  </div>
                )}
                <div className="mt-4">
                  <ReasonList title={detail.theme_match_status === 'READY' && !aiResearch ? '主题匹配说明' : '主题排名说明'} reasons={detail.leadership_reasons} />
                </div>
              </Section>

              <Section
                icon={<Activity className="h-5 w-5 text-blue-700" />}
                title="交易容量与活跃度"
                help="这里看这只股票大概是小盘弹性票，还是能容纳大资金的容量票；成交额、换手率和自由流通市值是主要参考。"
                status={detail.supply_profile_label}
              >
                <MetricGrid items={supplyMetrics} />
              </Section>

              <Section
                icon={<Bot className="h-5 w-5 text-violet-700" />}
                title="AI 研究"
                help="AI 研究会把技术形态、经营变化、题材标签、市场复盘和主题内表现放在一起，给出正面证据、反证和研究优先级。"
                status={aiStatus}
                headerExtra={aiResearch?.web_search_used ? <span className="rounded-md border border-violet-200 bg-violet-50 px-2 py-1 text-[11px] font-black text-violet-800">联网搜索已开启</span> : undefined}
              >
                <MetricGrid
                  items={[
                    { label: '分析状态', value: textValue(aiStatus), tone: statusTone(aiStatus) },
                    { label: '分析日期', value: textValue(aiResearch?.as_of_date) },
                    { label: '模型用量', value: aiResearch?.ai_total_tokens ? `${aiResearch.ai_total_tokens} tokens` : '暂无' },
                    { label: '分析耗时', value: aiResearch?.ai_elapsed_ms ? `${(Number(aiResearch.ai_elapsed_ms) / 1000).toFixed(1)} 秒` : '暂无' },
                  ]}
                />
                {aiResearch?.result_markdown && aiStatus !== 'STALE' ? (
                  <div className="mt-4 rounded-md border border-violet-200 bg-violet-50/40 p-4">
                    <AiMarkdown text={aiResearch.result_markdown} />
                  </div>
                ) : aiStatus === 'STALE' ? (
                  <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4 text-xs font-bold leading-relaxed text-amber-900">
                    财务与主题判断已更新，请重新分析后查看当前结论。
                  </div>
                ) : aiRunning ? (
                  <div className="mt-4 rounded-md border border-violet-200 bg-violet-50 p-4 text-xs font-bold leading-relaxed text-violet-900">
                    分析正在进行，关闭此窗口不影响结果生成；完成后重新打开即可查看结论。
                  </div>
                ) : (
                  <div className="mt-4 text-xs font-bold text-[#686d68]">当前日期还没有生成 AI 研究结果。</div>
                )}
              </Section>

              <Section
                icon={<History className="h-5 w-5 text-slate-700" />}
                title="入选以来变化"
                help="这里不是重新整理日线行情，而是把这只股票从首次入选到当前日期的关键变化做成摘要：每天技术状态有没有变化、分数有没有明显跳升、是否从观察区进入转强区。完整走势仍以 K 线窗口为准。"
                status="可在 K 线查看"
              >
                {selectionChanges.length === 0 ? (
                  <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs font-bold text-slate-600">暂无历史选股记录。</div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {selectionChanges.filter((row: any) => row.selected || row.total_score >= 75).slice(-12).map((row: any, index: number) => (
                      <span key={`${row.trade_date}-${index}`} className={`inline-flex items-center rounded-md border px-2 py-1 text-[11px] font-black ${row.selected ? 'border-emerald-300 bg-emerald-50 text-emerald-900' : 'border-slate-200 bg-slate-50 text-slate-700'}`}>
                        {row.trade_date} · {Number(row.total_score ?? 0).toFixed(1)}分 · {statusText(row.turn_episode_state || row.state)}
                      </span>
                    ))}
                  </div>
                )}
              </Section>
            </div>
          )}
        </div>
        )}
      </div>
    </div>
  );
};

export default SecondaryStockDetailDrawer;
