'use client';

import React, { useState, useMemo, useEffect } from 'react';
import { 
  BookOpen, 
  TrendingUp, 
  TrendingDown, 
  Layers, 
  List, 
  BarChart2, 
  Flame, 
  ArrowUpRight, 
  ArrowDownRight, 
  Maximize2, 
  Tag,
  Calendar,
  Sparkles,
  RefreshCw,
  X,
  Activity,
  ChevronRight,
  ChevronLeft,
  Brain
} from 'lucide-react';
import MarketMemoryModal from './MarketMemoryModal';
import SecondaryStockDetailDrawer from './SecondaryStockDetailDrawer';

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;
if (!API_BASE) {
  throw new Error('NEXT_PUBLIC_MARKET_REVIEW_API_URL is required');
}

export type MarketIndexItem = {
  name: string;
  symbol: string;
  close: string;
  pct_change: string;
  amount: string;
  amount_diff: string;
  is_up: boolean;
};

export type THSConceptItem = {
  name: string;
  pct_change: string;
  amount: string;
  leading_stock: string;
  ths_code?: string;
};

export type KeyStockItem = {
  ts_code: string;
  name: string;
  trade_date?: string | null;
  mention_date?: string | null;
  performance_date?: string | null;
  close: string;
  pct_change: string;
  amount: string;
  tag: string;
  sector?: string;
  story?: string;
  concepts?: string[];
  mention_name?: string;
  is_up: boolean;
  prev_pct_change?: string | null;
  prev_is_up?: boolean;
  market_data_available?: boolean;
};

export type MarketObjectiveData = {
  trade_date: string;
  indices: MarketIndexItem[];
  breadth: {
    total_amount: string;
    total_amount_diff: string;
    rising_count: number;
    falling_count: number;
    flat_count: number;
    limit_up_count: number;
    limit_down_count: number;
    limit_up_broken_count: number;
    limit_up_seal_rate: string;
  };
  ths_concepts: {
    top_gainers: THSConceptItem[];
    top_losers: THSConceptItem[];
  };
  key_stocks: KeyStockItem[];
  today_stocks?: KeyStockItem[];
  weekly_focus?: {
    window_dates: string[];
    price_window_dates: string[];
    stock_count: number;
    groups: Array<{
      sector: string;
      stocks: Array<KeyStockItem & {
        mention_dates?: string[];
        daily?: Array<{ date: string; close: string; pct_change: string; amount: string }>;
        latest?: { date: string; close: string; pct_change: string; amount: string } | null;
      }>;
    }>;
    date_groups?: Array<{
      date: string;
      stocks: Array<KeyStockItem & {
        mention_date?: string;
        mention_dates?: string[];
        daily?: Array<{ date: string; close: string; pct_change: string; amount: string }>;
        latest?: { date: string; close: string; pct_change: string; amount: string } | null;
      }>;
    }>;
};
};

export type ImportedPayload = {
  trade_date: string;
  title: string;
  full_markdown?: string;
  raw_content?: string;
  [key: string]: any;
};

type ArticleStockLink = { label: string; code: string; name: string };
type LimitUpReason = {
  symbol: string;
  name: string;
  reason: string;
  drivers?: string[];
  basis?: string;
  sources?: string[];
};
const EMPTY_ARTICLE_STOCK_LINKS: ArticleStockLink[] = [];

interface ImportedDashboardProps {
  tradeDate: string;
  payload: ImportedPayload;
  rawContent?: string;
  articleStockLinks?: ArticleStockLink[];
  marketData?: MarketObjectiveData;
  marketDataError?: string | null;
  onOpenImportModal?: () => void;
  history?: Array<{ trade_date: string }>;
  onSelectDate?: (date: string) => void;
}

export default function ImportedDashboard({ 
  tradeDate, 
  payload, 
  rawContent,
  articleStockLinks,
  marketData,
  marketDataError,
  onOpenImportModal,
  history = [],
  onSelectDate
}: ImportedDashboardProps) {
  const stableArticleStockLinks = articleStockLinks ?? EMPTY_ARTICLE_STOCK_LINKS;
  const [isTocOpen, setIsTocOpen] = useState(false);
  const [showMarketMemoryInline, setShowMarketMemoryInline] = useState(false);
  const [marketMemoryView, setMarketMemoryView] = useState<'markdown' | 'themes' | 'capital_flows'>('markdown');
  const [memoryUpdating, setMemoryUpdating] = useState(false);
  const [panoramaUpdating, setPanoramaUpdating] = useState(false);
  const [weeklyFocusQuery, setWeeklyFocusQuery] = useState('');
  const [weeklyFocusView, setWeeklyFocusView] = useState<'date' | 'theme'>('date');
  const [enrichedArticleStockLinks, setEnrichedArticleStockLinks] = useState<ArticleStockLink[]>(stableArticleStockLinks);

  useEffect(() => {
    setEnrichedArticleStockLinks(stableArticleStockLinks);
  }, [articleStockLinks, tradeDate]);

  useEffect(() => {
    let mounted = true;
    const checkStatus = async () => {
      try {
        const [memoryRes, panoramaRes] = await Promise.all([
          fetch('http://127.0.0.1:18080/api/market-review/market-memory/status'),
          fetch('http://127.0.0.1:18080/api/market-review/market-panorama/status'),
        ]);
        if (mounted && memoryRes.ok) {
          const json = await memoryRes.json();
          setMemoryUpdating(Boolean(json.running));
        }
        if (mounted && panoramaRes.ok) {
          const json = await panoramaRes.json();
          setPanoramaUpdating(Boolean(json.running));
        }
      } catch {
        // ignore
      }
    };
    checkStatus();
    const timer = setInterval(checkStatus, 3000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, []);
  
  const [detailStock, setDetailStock] = useState<{ code: string; name: string } | null>(null);
  const [basicAnalysisRunning, setBasicAnalysisRunning] = useState(false);

  // 关键焦点股票双 Tab 与全屏验证大表 Modal 状态
  const [focusStockTab, setFocusStockTab] = useState<'prev_verify' | 'today_mentioned'>('prev_verify');
  const [isFocusTableModalOpen, setIsFocusTableModalOpen] = useState(false);
  const [showWeeklyFocusInline, setShowWeeklyFocusInline] = useState(false);
  const [isDatePickerOpen, setIsDatePickerOpen] = useState(false);

  // Calendar navigation state
  const activeDate = payload.trade_date || tradeDate;

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const checkEnrichment = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/market-review/import-enrichment?date=${encodeURIComponent(activeDate)}`, { cache: 'no-store' });
        if (!response.ok) return;
        const result = await response.json() as {
          stock_extraction_status?: string;
          article_stock_links?: ArticleStockLink[];
        };
        if (cancelled) return;
        if (Array.isArray(result.article_stock_links) && result.article_stock_links.length > 0) {
          setEnrichedArticleStockLinks(result.article_stock_links);
        }
        if (result.stock_extraction_status === 'SUCCESS') {
          return;
        }
        if (result.stock_extraction_status === 'PENDING' || result.stock_extraction_status === 'RUNNING') {
          timer = window.setTimeout(checkEnrichment, 2000);
        }
      } catch {
        // The article remains readable with its immediate local bindings. A later
        // poll can update it when the backend is reachable again.
        if (!cancelled) timer = window.setTimeout(checkEnrichment, 4000);
      }
    };
    checkEnrichment();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [activeDate]);

  // 焦点股区域统一使用绝对日期，避免“今天/前日”随查看历史复盘日期产生歧义。
  const formatDateLabel = (value?: string | null) => {
    if (!value) return '日期未明';
    const normalized = String(value).replace(/-/g, '').slice(0, 8);
    if (normalized.length !== 8) return String(value);
    return `${parseInt(normalized.slice(4, 6))}月${parseInt(normalized.slice(6, 8))}日`;
  };
  const formatDayLabel = (value?: string | null) => {
    if (!value) return '日期未明';
    const normalized = String(value).replace(/-/g, '').slice(0, 8);
    if (normalized.length !== 8) return String(value);
    return `${parseInt(normalized.slice(6, 8))}日`;
  };
  const reviewDateLabel = formatDateLabel(activeDate);
  const prevMentionDate = marketData?.key_stocks?.[0]?.mention_date || marketData?.key_stocks?.[0]?.trade_date;
  const verificationDate = marketData?.key_stocks?.[0]?.performance_date || activeDate;
  const mentionDateLabel = formatDateLabel(prevMentionDate);
  const verificationDateLabel = formatDateLabel(verificationDate);
  const weeklyFocusGroups = useMemo(() => {
    const groups = marketData?.weekly_focus?.groups || [];
    const query = weeklyFocusQuery.trim().toLowerCase();
    if (!query) return groups;
    return groups
      .map((group) => ({
        ...group,
        stocks: group.stocks.filter((stock) =>
          `${stock.name} ${stock.ts_code}`.toLowerCase().includes(query),
        ),
      }))
      .filter((group) => group.stocks.length > 0);
  }, [marketData?.weekly_focus?.groups, weeklyFocusQuery]);
  const weeklyFocusDateGroups = useMemo(() => {
    const groups = marketData?.weekly_focus?.date_groups || [];
    const query = weeklyFocusQuery.trim().toLowerCase();
    if (!query) return groups;
    return groups
      .map((group) => ({
        ...group,
        stocks: group.stocks.filter((stock) => `${stock.name} ${stock.ts_code}`.toLowerCase().includes(query)),
      }))
      .filter((group) => group.stocks.length > 0);
  }, [marketData?.weekly_focus?.date_groups, weeklyFocusQuery]);
  const parsedDate = useMemo(() => {
    if (!activeDate) return new Date();
    const parts = activeDate.split('-');
    if (parts.length === 3) {
      return new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
    }
    return new Date();
  }, [activeDate]);

  const [calYear, setCalYear] = useState<number>(parsedDate.getFullYear());
  const [calMonth, setCalMonth] = useState<number>(parsedDate.getMonth()); // 0-11

  // Keep calendar in sync when activeDate changes externally
  useEffect(() => {
    setCalYear(parsedDate.getFullYear());
    setCalMonth(parsedDate.getMonth());
  }, [parsedDate]);

  const calendarDays = useMemo(() => {
    const days: Array<{ dateStr: string; dayNum: number; isCurrentMonth: boolean; hasReview: boolean; isSelected: boolean }> = [];
    
    // First day of current month
    const firstDay = new Date(calYear, calMonth, 1);
    const startDayOfWeek = firstDay.getDay(); // 0 is Sunday, ..., 6 is Saturday
    
    // Total days in current month
    const totalDays = new Date(calYear, calMonth + 1, 0).getDate();
    
    // Total days in previous month
    const prevMonthTotalDays = new Date(calYear, calMonth, 0).getDate();
    
    const historySet = new Set((history || []).map(h => h.trade_date));

    // Pad previous month's days
    for (let i = startDayOfWeek - 1; i >= 0; i--) {
      const dNum = prevMonthTotalDays - i;
      const prevMonth = calMonth === 0 ? 11 : calMonth - 1;
      const prevYear = calMonth === 0 ? calYear - 1 : calYear;
      const dateStr = `${prevYear}-${String(prevMonth + 1).padStart(2, '0')}-${String(dNum).padStart(2, '0')}`;
      days.push({
        dateStr,
        dayNum: dNum,
        isCurrentMonth: false,
        hasReview: historySet.has(dateStr),
        isSelected: dateStr === activeDate
      });
    }
    
    // Current month's days
    for (let i = 1; i <= totalDays; i++) {
      const dateStr = `${calYear}-${String(calMonth + 1).padStart(2, '0')}-${String(i).padStart(2, '0')}`;
      days.push({
        dateStr,
        dayNum: i,
        isCurrentMonth: true,
        hasReview: historySet.has(dateStr),
        isSelected: dateStr === activeDate
      });
    }
    
    // Pad next month's days to fill a full grid (usually 42 cells for 6 rows)
    const totalCells = 42;
    const nextDaysNeeded = totalCells - days.length;
    for (let i = 1; i <= nextDaysNeeded; i++) {
      const nextMonth = calMonth === 11 ? 0 : calMonth + 1;
      const nextYear = calMonth === 11 ? calYear + 1 : calYear;
      const dateStr = `${nextYear}-${String(nextMonth + 1).padStart(2, '0')}-${String(i).padStart(2, '0')}`;
      days.push({
        dateStr,
        dayNum: i,
        isCurrentMonth: false,
        hasReview: historySet.has(dateStr),
        isSelected: dateStr === activeDate
      });
    }
    
    return days;
  }, [calYear, calMonth, history, activeDate]);

  const articleDocument = useMemo(() => {
    const source = rawContent || payload.full_markdown || payload.raw_content || '';
    const reasons = new Map<string, LimitUpReason>();
    const commentPattern = /<!--[\s\S]*?-->|<!--\s*A_SHARE_LIMIT_UP_REASONS_V1[\s\S]*$/g;
    const visible = source.replace(commentPattern, (comment) => {
      const body = comment
        .slice(4, comment.endsWith('-->') ? -3 : undefined)
        .trim()
        .replace(/^A_SHARE_LIMIT_UP_REASONS_V1\s*/i, '')
        .replace(/^json\s*/i, '')
        .trim();
      try {
        const jsonStart = body.indexOf('{');
        const endMarker = body.lastIndexOf('A_SHARE_LIMIT_UP_REASONS_END');
        const jsonBody = endMarker >= 0 ? body.slice(0, endMarker).trim() : body;
        const jsonEnd = jsonBody.lastIndexOf('}');
        const parsed = JSON.parse(jsonStart >= 0 ? jsonBody.slice(jsonStart, jsonEnd >= jsonStart ? jsonEnd + 1 : undefined) : jsonBody);
        if (parsed?.schema !== 'a_share_limit_up_reasons' || !Array.isArray(parsed.items)) return comment;
        for (const item of parsed.items) {
          if (!item || typeof item !== 'object' || typeof item.reason !== 'string') continue;
          const symbol = String(item.symbol || '').trim().toUpperCase();
          const name = String(item.name || '').trim();
          if (!symbol && !name) continue;
          const normalized = symbol.replace(/^(SH|SZ|BJ)/, '') || name;
          const value = {
            symbol,
            name,
            reason: item.reason.trim(),
            drivers: Array.isArray(item.drivers) ? item.drivers.map(String) : [],
            basis: item.basis ? String(item.basis) : undefined,
            sources: Array.isArray(item.sources) ? item.sources.map(String) : [],
          };
          reasons.set(normalized, value);
          if (name) reasons.set(name, value);
        }
      } catch {
        // A legacy/non-JSON comment must remain untouched for backward compatibility.
        return comment;
      }
      return '';
    });
    return { markdown: visible, reasons };
  }, [rawContent, payload]);

  const articleMarkdown = articleDocument.markdown;
  const limitUpReasons = articleDocument.reasons;

  // 仅使用导入时已完成证券主数据绑定的全文提取结果生成正文链接。
  // 文章中的普通词汇绝不会被按名称猜测为股票，避免误跳转。
  const articleStockMentions = useMemo(() => {
    const mentions = new Map<string, { code: string; name: string }>();
    for (const stock of stableArticleStockLinks) {
      if (stock.label?.trim() && stock.code?.trim() && stock.name?.trim()) {
        mentions.set(stock.label.trim(), { code: stock.code, name: stock.name });
      }
    }
    for (const stock of enrichedArticleStockLinks) {
      if (stock.label?.trim() && stock.code?.trim() && stock.name?.trim()) {
        mentions.set(stock.label.trim(), { code: stock.code, name: stock.name });
      }
    }
    for (const stock of marketData?.today_stocks || []) {
      const labels = [stock.mention_name, stock.name, stock.ts_code, stock.ts_code?.split('.')[0]];
      for (const label of labels) {
        const normalized = label?.trim();
        if (normalized && !mentions.has(normalized)) {
          mentions.set(normalized, { code: stock.ts_code, name: stock.name });
        }
      }
    }
    for (const reason of limitUpReasons.values()) {
      const symbol = String(reason.symbol || '').toUpperCase();
      const match = symbol.match(/^(SH|SZ|BJ)(\d{6})$/);
      const code = match ? `${match[2]}.${match[1]}` : '';
      if (code && reason.name && !mentions.has(reason.name)) {
        mentions.set(reason.name, { code, name: reason.name });
      }
    }
    return Array.from(mentions.entries())
      .map(([label, stock]) => ({ label, ...stock }))
      .sort((left, right) => right.label.length - left.label.length);
  }, [stableArticleStockLinks, enrichedArticleStockLinks, marketData?.today_stocks, limitUpReasons]);

  // Extract headings for TOC (只提取带显式数字/序号编号的章节标题，如 一、 1. 【1】 第1章 等)
  const tocItems = useMemo(() => {
    if (!articleMarkdown) return [];
    const lines = articleMarkdown.split('\n');
    const items: Array<{ id: string; text: string; level: number }> = [];
    
    // 正则检查是否包含数字编号或中文序号
    const numberPattern = /^(?:#+\s*)?(?:[一二三四五六七八九十]+[、\.\s]|[0-9]+[\.\、\s]|【[0-9一二三四五六七八九十]+】|第[0-9一二三四五六七八九十]+[章节条]?)/;

    lines.forEach((line, idx) => {
      const trimmed = line.trim();
      const rawText = trimmed.replace(/^#+\s*/, '').trim();
      if ((trimmed.startsWith('# ') || trimmed.startsWith('## ') || trimmed.startsWith('### ')) && numberPattern.test(trimmed)) {
        const level = trimmed.startsWith('# ') ? 1 : trimmed.startsWith('## ') ? 2 : 3;
        items.push({ id: `heading-${idx}`, text: rawText, level });
      } else if (!trimmed.startsWith('#') && numberPattern.test(trimmed) && trimmed.length <= 40) {
        items.push({ id: `heading-${idx}`, text: trimmed, level: 2 });
      }
    });
    return items;
  }, [articleMarkdown]);

  const handleStockClick = (code: string, name: string) => {
    setDetailStock({ code, name });
  };

  const runBasicAnalysis = async (code: string) => {
    setBasicAnalysisRunning(true);
    try {
      const res = await fetch(`${API_BASE}/api/stock-profiles/${encodeURIComponent(code)}/fundamental/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = typeof body?.detail === 'string' ? body.detail : body?.detail?.message;
        throw new Error(detail || `基本面分析失败（HTTP ${res.status}）`);
      }
    } finally {
      setBasicAnalysisRunning(false);
    }
  };

  const runStockAIResearch = async (code: string) => {
    const res = await fetch(`${API_BASE}/api/ai/stock-research-async`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ts_codes: [code], date: activeDate, use_web_search: true }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok || !body?.job_id) {
      const detail = typeof body?.detail === 'string' ? body.detail : body?.detail?.message;
      throw new Error(detail || `AI 分析任务创建失败（HTTP ${res.status}）`);
    }
    for (;;) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      const statusRes = await fetch(`${API_BASE}/api/ai/stock-research-status/${encodeURIComponent(body.job_id)}`);
      const statusBody = await statusRes.json().catch(() => ({}));
      if (!statusRes.ok) throw new Error(statusBody?.detail || `AI 分析状态读取失败（HTTP ${statusRes.status}）`);
      if (statusBody.status === 'success') return;
      if (statusBody.status === 'failed') throw new Error(statusBody.error || statusBody.step_message || 'AI 分析失败');
    }
  };

  const runStockThemeMatch = async (code: string) => {
    const res = await fetch(`${API_BASE}/api/ai/stock-theme-match`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ts_code: code }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof body?.detail === 'string' ? body.detail : body?.detail?.message;
      throw new Error(detail || `主题匹配失败（HTTP ${res.status}）`);
    }
    if (!body?.job_id) {
      throw new Error('主题匹配任务未成功提交');
    }
    for (;;) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      const statusRes = await fetch(`${API_BASE}/api/ai/stock-theme-match-status/${encodeURIComponent(body.job_id)}`, { cache: 'no-store' });
      const statusBody = await statusRes.json().catch(() => ({}));
      if (!statusRes.ok) throw new Error(statusBody?.detail || `主题匹配状态读取失败（HTTP ${statusRes.status}）`);
      if (statusBody.status === 'success') return;
      if (statusBody.status === 'failed') throw new Error(statusBody.error || statusBody.step_message || '主题匹配失败');
    }
  };

  const handleTocClick = (id: string) => {
    setIsTocOpen(false);
    const element = document.getElementById(id);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  // Helper parser for Markdown with Compact Styling
  const renderFormattedMarkdown = (markdownText: string) => {
    if (!markdownText) return null;
    const lines = markdownText.split('\n');
    const elements: React.ReactNode[] = [];
    
    let inTable = false;
    let tableHeaders: string[] = [];
    let tableRows: string[][] = [];
    let inCodeBlock = false;
    let codeLines: string[] = [];

    const flushTable = (keyPrefix: number) => {
      if (tableHeaders.length > 0) {
        elements.push(
          <div key={`table-${keyPrefix}`} className="my-2.5 overflow-x-auto rounded-md border border-[#c4c8bc]/50 bg-white shadow-2xs">
            <table className="w-full text-left text-xs border-collapse">
              <thead className="bg-[#f0ece4] text-[#2e3230] font-extrabold border-b border-[#c4c8bc]/50">
                <tr>
                  {tableHeaders.map((th, idx) => (
                    <th key={idx} className="px-2.5 py-1.5 font-bold border-r border-[#c4c8bc]/30 last:border-0 whitespace-nowrap">
                      {th.trim()}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#eae6de]">
                {tableRows.map((row, rIdx) => (
                  <tr key={rIdx} className={rIdx % 2 === 0 ? 'bg-white' : 'bg-[#faf8f5]'}>
                    {row.map((cell, cIdx) => {
                      const cellText = cell.trim();
                      const isUp = cellText.includes('强') || cellText.includes('高潮') || cellText.includes('大涨') || cellText.includes('涨停');
                      const isDown = cellText.includes('弱') || cellText.includes('跌') || cellText.includes('衰减') || cellText.includes('风险');
                      return (
                        <td key={cIdx} className={`px-2.5 py-1.5 border-r border-[#c4c8bc]/20 last:border-0 font-medium ${
                          isUp ? 'text-[#b83230] font-bold' : isDown ? 'text-[#237a4b] font-bold' : 'text-[#2e3230]'
                        }`}>
                          {parseInlineMarkdown(cellText)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      inTable = false;
      tableHeaders = [];
      tableRows = [];
    };

    const flushCodeBlock = (keyPrefix: number) => {
      elements.push(
        <div key={`code-${keyPrefix}`} className="my-3 rounded-lg border border-[#c4c8bc]/50 bg-[#f8f6f1] px-4 py-3 text-sm leading-7 text-[#2e3230] whitespace-pre-wrap break-words">
          {codeLines.join('\n')}
        </div>,
      );
      codeLines = [];
      inCodeBlock = false;
    };

    lines.forEach((line, index) => {
      const trimmed = line.trim();

      // 处理 AI 常见的 ```text ... ``` 围栏，避免围栏标记直接显示在文章中。
      if (trimmed.startsWith('```')) {
        if (inCodeBlock) {
          flushCodeBlock(index);
        } else {
          if (inTable) flushTable(index);
          inCodeBlock = true;
          codeLines = [];
        }
        return;
      }
      if (inCodeBlock) {
        codeLines.push(line);
        return;
      }

      // Table line detect
      if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
        const cells = trimmed.split('|').slice(1, -1);
        if (cells.every(c => c.trim().match(/^:?-+:?$/))) {
          // Separator line, ignore
          return;
        }
        if (!inTable) {
          inTable = true;
          tableHeaders = cells;
        } else {
          tableRows.push(cells);
        }
        return;
      } else if (inTable) {
        flushTable(index);
      }

      if (!trimmed) {
        elements.push(<div key={index} className="h-1.5" />);
        return;
      }

      if (trimmed.startsWith('# ')) {
        elements.push(
          <h1 key={index} id={`heading-${index}`} className="mt-5 mb-3 font-[family-name:var(--font-literata)] text-2xl font-extrabold text-[#2e3230] border-b border-[#c4c8bc]/40 pb-2">
            {trimmed.replace(/^#\s+/, '')}
          </h1>
        );
      } else if (trimmed.startsWith('## ')) {
        const text = trimmed.replace(/^##\s+/, '');
        elements.push(
          <h2 key={index} id={`heading-${index}`} className="mt-6 mb-2.5 font-[family-name:var(--font-literata)] text-lg font-bold text-[#705c30] flex items-center gap-2 border-l-3 border-[#705c30] pl-2.5">
            {text}
          </h2>
        );
      } else if (trimmed.startsWith('### ')) {
        const text = trimmed.replace(/^###\s+/, '');
        elements.push(
          <h3 key={index} id={`heading-${index}`} className="mt-4 mb-2 text-sm sm:text-base font-bold text-[#2e3230]">
            {text}
          </h3>
        );
      } else if (trimmed.startsWith('> ')) {
        const text = trimmed.replace(/^>\s+/, '');
        elements.push(
          <blockquote key={index} className="my-2 rounded-md border-l-3 border-[#4a7c59] bg-[#f2efe9] px-3.5 py-2 text-sm font-semibold text-[#2e3230] leading-relaxed">
            💡 {parseInlineMarkdown(text)}
          </blockquote>
        );
      } else if (trimmed.startsWith('---')) {
        elements.push(<hr key={index} className="my-4 border-[#c4c8bc]/40" />);
      } else if (trimmed.startsWith('- ')) {
        const text = trimmed.replace(/^-\s+/, '');
        elements.push(
          <li key={index} className="ml-4 my-1 text-sm leading-relaxed text-[#2e3230] list-disc">
            {parseInlineMarkdown(text)}
          </li>
        );
      } else {
        elements.push(
          <p key={index} className="my-2 text-sm sm:text-base leading-relaxed text-[#2e3230] font-normal">
            {parseInlineMarkdown(trimmed)}
          </p>
        );
      }
    });

    if (inTable) {
      flushTable(lines.length);
    }
    if (inCodeBlock) {
      flushCodeBlock(lines.length);
    }

    return elements;
  };

  const renderArticleStockMentions = (text: string, keyPrefix: string): React.ReactNode[] => {
    if (!articleStockMentions.length) return [text];
    const pattern = articleStockMentions
      .map(({ label }) => label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      .join('|');
    if (!pattern) return [text];
    const matcher = new RegExp(`(${pattern})`, 'g');
    return text.split(matcher).filter(Boolean).map((part, index) => {
      const stock = articleStockMentions.find((candidate) => candidate.label === part);
      if (!stock) return <React.Fragment key={`${keyPrefix}-text-${index}`}>{part}</React.Fragment>;
      const stockCode = String(stock.code || '').toUpperCase().replace(/^(SH|SZ|BJ)/, '').split('.')[0];
      const reason = limitUpReasons.get(stockCode) || limitUpReasons.get(stock.name);
      return (
        <button
          key={`${keyPrefix}-stock-${index}`}
          type="button"
          onClick={() => handleStockClick(stock.code, stock.name)}
          title={reason?.reason || `查看${stock.name} K线`}
          className="group relative inline rounded-sm font-semibold text-[#705c30] underline decoration-[#705c30]/45 decoration-1 underline-offset-2 transition hover:bg-[#705c30]/10 hover:text-[#4f3f1e] focus:outline-none focus:ring-2 focus:ring-[#705c30]/35"
        >
          {part}
          {reason?.reason && (
            <span className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 hidden w-72 -translate-x-1/2 rounded-md border border-[#c9b27a] bg-[#fffdf7] px-3 py-2 text-left text-[11px] font-bold leading-relaxed text-[#4b3a1c] normal-case no-underline shadow-xl group-hover:block">
              {reason.reason}
            </span>
          )}
        </button>
      );
    });
  };

  const renderInlineEmphasis = (text: string, keyPrefix: string) => {
    const parts = text.split(/(\*\*.*?\*\*)/g);
    return parts.map((part, index) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={`${keyPrefix}-bold-${index}`} className="font-bold text-[#705c30] bg-[#705c30]/10 px-1 py-0.2 rounded">{renderArticleStockMentions(part.slice(2, -2), `${keyPrefix}-bold-${index}`)}</strong>;
      }
      return <React.Fragment key={`${keyPrefix}-text-${index}`}>{renderArticleStockMentions(part, `${keyPrefix}-text-${index}`)}</React.Fragment>;
    });
  };

  const parseInlineMarkdown = (text: string) => {
    // 复盘来源常见两种链接写法：Markdown 的 [标题](URL)，以及编辑器生成的【标题】(URL)。
    // 展示时只保留标题，URL 作为可点击链接隐藏在标题后面，避免长 URL 破坏文章排版。
    const linkPattern = /(\[[^\]]+\]\(https?:\/\/[^\s)]+\)|【[^】]+】\(https?:\/\/[^\s)]+\))/g;
    const elements: React.ReactNode[] = [];
    let cursor = 0;
    let match: RegExpExecArray | null;
    let index = 0;
    while ((match = linkPattern.exec(text)) !== null) {
      if (match.index > cursor) {
        elements.push(...renderInlineEmphasis(text.slice(cursor, match.index), `inline-${index}`));
      }
      const raw = match[0];
      const markdownMatch = raw.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
      const editorialMatch = raw.match(/^【([^】]+)】\((https?:\/\/[^\s)]+)\)$/);
      const label = markdownMatch?.[1] || editorialMatch?.[1] || raw;
      const href = markdownMatch?.[2] || editorialMatch?.[2];
      if (href) {
        elements.push(
          <a
            key={`inline-link-${index}`}
            href={href.replace(/[，。；、]+$/, '')}
            target="_blank"
            rel="noreferrer"
            className="font-semibold text-[#705c30] underline decoration-[#705c30]/45 underline-offset-2 hover:text-[#4f3f1e]"
            title={href}
          >
            {label}
          </a>,
        );
      } else {
        elements.push(...renderInlineEmphasis(raw, `inline-${index}`));
      }
      cursor = match.index + raw.length;
      index += 1;
    }
    if (cursor < text.length) {
      elements.push(...renderInlineEmphasis(text.slice(cursor), `inline-${index}`));
    }
    return elements;
  };

  // Keep the article readable while objective market data is still syncing.
  // Never substitute another date or synthetic values into the dashboard.
  const data = marketData || {
    trade_date: tradeDate,
    indices: [],
    breadth: {
      total_amount: '—', total_amount_diff: '—', rising_count: 0,
      falling_count: 0, flat_count: 0, limit_up_count: 0,
      limit_down_count: 0, limit_up_broken_count: 0, limit_up_seal_rate: '—',
    },
    ths_concepts: { top_gainers: [], top_losers: [] },
    key_stocks: [],
  };

  const totalStocks = (data.breadth?.rising_count || 0) + (data.breadth?.falling_count || 0) + (data.breadth?.flat_count || 0);
  const risingRatio = totalStocks > 0 ? ((data.breadth?.rising_count || 0) / totalStocks) * 100 : 50;

  return (
    <div className="px-3 py-3 sm:px-6 lg:px-8 space-y-3 max-w-[1600px] mx-auto h-[calc(100vh-4.5rem)] flex flex-col overflow-hidden relative">
      {/* 1. 左侧悬浮抽屉触发按钮 (固定于左边缘，默认隐藏不遮挡) */}
      {!showMarketMemoryInline && !showWeeklyFocusInline && tocItems.length > 0 && (
        <button
          onClick={() => setIsTocOpen(true)}
          className="fixed left-0 top-28 z-40 flex items-center gap-1.5 rounded-r-xl border border-l-0 border-[#c4c8bc]/60 bg-[#705c30] px-2.5 py-2 text-xs font-bold text-white shadow-lg hover:bg-[#5a4926] active:scale-95 transition-all group"
          title="打开文章大纲目录"
        >
          <List className="h-4 w-4" />
          <span className="hidden sm:inline">文章大纲</span>
          <ChevronRight className="h-3.5 w-3.5 opacity-70 group-hover:translate-x-0.5 transition-transform" />
        </button>
      )}

      {/* 2. 左侧大纲抽屉 (Drawer Side Panel) */}
      {!showMarketMemoryInline && !showWeeklyFocusInline && isTocOpen && (
        <>
          {/* 背景遮罩 */}
          <div 
            onClick={() => setIsTocOpen(false)} 
            className="fixed inset-0 z-50 bg-black/30 backdrop-blur-xs transition-opacity" 
          />
          {/* 滑出抽屉 */}
          <div className="fixed left-0 top-0 bottom-0 z-50 w-80 sm:w-96 bg-[#faf8f3] border-r border-[#c4c8bc]/60 shadow-2xl p-5 flex flex-col space-y-4 animate-in slide-in-from-left duration-200">
            <div className="flex items-center justify-between border-b border-[#c4c8bc]/40 pb-3">
              <h3 className="flex items-center gap-2 text-base font-extrabold text-[#705c30]">
                <List className="h-5 w-5 text-[#705c30]" />
                文章大纲目录 ({tocItems.length} 个章节)
              </h3>
              <button
                onClick={() => setIsTocOpen(false)}
                className="rounded-md p-1.5 text-[#686d68] hover:bg-[#e2d5bd]/40 hover:text-[#2e3230] transition"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto overflow-x-hidden space-y-2 pr-1.5 text-sm">
              {tocItems.map((item, idx) => (
                <button
                  key={item.id}
                  onClick={() => handleTocClick(item.id)}
                  className={`w-full text-left rounded-xl p-2.5 transition-all flex items-start gap-2 break-words whitespace-normal ${
                    item.level === 2 
                      ? 'bg-white border border-[#c4c8bc]/50 font-bold text-sm text-[#2e3230] hover:border-[#705c30] hover:text-[#705c30] shadow-2xs' 
                      : 'ml-4 bg-transparent text-[#686d68] hover:text-[#2e3230] font-medium text-sm'
                  }`}
                >
                  <span className="leading-snug break-words">{item.text}</span>
                </button>
              ))}
            </div>

            <div className="border-t border-[#c4c8bc]/40 pt-2.5 text-xs text-[#686d68] text-center font-medium">
              点击章节可直接平滑跳转
            </div>
          </div>
        </>
      )}

      {/* 复盘专属控制工具栏 Header */}
      <header className="rounded-xl border border-[#c4c8bc]/40 bg-[#f0ece4] p-3 sm:p-3.5 shadow-xs flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="font-[family-name:var(--font-literata)] text-base font-extrabold text-[#2e3230] sm:text-lg">
            复盘中心
          </h1>
        </div>

        {/* 复盘操作按钮栏：导入按钮 + 日期选择器 + 视图切换 */}
        <div className="flex items-center gap-2">
          {onOpenImportModal && (
            <button
              onClick={onOpenImportModal}
              className="inline-flex items-center gap-1.5 rounded-md bg-[#4a7c59] px-3 py-1.5 text-xs font-bold text-white shadow-xs hover:bg-[#3b6447] active:scale-95 transition-all"
            >
              <Sparkles className="h-3.5 w-3.5" />
              导入复盘文章
            </button>
          )}

          <button
            onClick={() => { setShowMarketMemoryInline(false); setShowWeeklyFocusInline(false); setIsTocOpen(false); }}
            className={!showMarketMemoryInline && !showWeeklyFocusInline ? 'inline-flex items-center gap-1.5 rounded-md border border-[#4a7c59] bg-[#4a7c59] px-3 py-1.5 text-xs font-bold text-white shadow-xs' : 'inline-flex items-center gap-1.5 rounded-md border border-[#4a7c59]/40 bg-white px-3 py-1.5 text-xs font-bold text-[#4a7c59] shadow-xs hover:bg-[#4a7c59]/10'}
            title="返回每日复盘文章"
          >
            每日复盘
          </button>

          {onSelectDate && (
            <div className="relative">
              <button
                onClick={() => setIsDatePickerOpen(!isDatePickerOpen)}
                className="review-date-trigger flex items-center gap-2 rounded-md border border-[#c4c8bc]/60 bg-white px-3 py-1.5 text-xs font-extrabold text-[#2e3230] shadow-xs hover:border-[#705c30] transition-all"
              >
                <Calendar className="h-4 w-4 text-[#705c30]" />
                <span>{payload.trade_date || tradeDate}</span>
                <ChevronRight className={`h-3.5 w-3.5 text-[#686d68] transition-transform ${isDatePickerOpen ? 'rotate-90' : ''}`} />
              </button>

              {/* 日历 Dropdown Popover */}
              {isDatePickerOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setIsDatePickerOpen(false)} />
                  <div className="review-date-popover absolute right-0 top-full mt-1.5 z-50 w-80 rounded-xl bg-white border border-[#c4c8bc]/80 shadow-2xl p-4 animate-in fade-in zoom-in-95 duration-150 space-y-3">
                    {/* Header with year, month and navigation */}
                    <div className="flex items-center justify-between border-b border-[#eae6de] pb-2 text-xs font-extrabold text-[#2e3230]">
                      <div className="flex items-center gap-1.5">
                        <Calendar className="h-4 w-4 text-[#705c30]" />
                        <span>{calYear}年 {calMonth + 1}月</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => {
                            if (calMonth === 0) {
                              setCalMonth(11);
                              setCalYear(prev => prev - 1);
                            } else {
                              setCalMonth(prev => prev - 1);
                            }
                          }}
                          className="p-1 hover:bg-[#705c30]/10 rounded text-[#705c30] transition"
                        >
                          <ChevronLeft className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => {
                            if (calMonth === 11) {
                              setCalMonth(0);
                              setCalYear(prev => prev + 1);
                            } else {
                              setCalMonth(prev => prev + 1);
                            }
                          }}
                          className="p-1 hover:bg-[#705c30]/10 rounded text-[#705c30] transition"
                        >
                          <ChevronRight className="h-4 w-4" />
                        </button>
                      </div>
                    </div>

                    {/* Weekday headers */}
                    <div className="grid grid-cols-7 gap-1 text-center text-[10px] font-bold text-[#686d68]">
                      <span>日</span>
                      <span>一</span>
                      <span>二</span>
                      <span>三</span>
                      <span>四</span>
                      <span>五</span>
                      <span>六</span>
                    </div>

                    {/* Calendar grid cells */}
                    <div className="grid grid-cols-7 gap-1">
                      {calendarDays.map((day, idx) => {
                        const isSelectable = day.hasReview;
                        return (
                          <button
                            key={idx}
                            disabled={!isSelectable}
                            onClick={() => {
                              setIsDatePickerOpen(false);
                              onSelectDate(day.dateStr);
                            }}
                            className={`review-date-cell relative aspect-square flex flex-col items-center justify-center rounded-lg text-xs font-bold transition ${
                              day.isSelected
                                ? 'bg-[#705c30] text-white shadow-2xs'
                                : day.isCurrentMonth
                                ? isSelectable
                                  ? 'bg-[#fcfaf7] text-[#2e3230] hover:bg-[#705c30]/10 hover:text-[#705c30] border border-[#705c30]/20'
                                  : 'bg-transparent text-[#c4c8bc]/60 cursor-not-allowed'
                                : isSelectable
                                ? 'bg-[#fcfaf7]/50 text-[#2e3230]/50 hover:bg-[#705c30]/10 border border-[#705c30]/10'
                                : 'bg-transparent text-[#c4c8bc]/30 cursor-not-allowed'
                            }`}
                            title={isSelectable ? `${day.dateStr} (有复盘文章)` : `${day.dateStr} (无复盘)`}
                          >
                            <span>{day.dayNum}</span>
                            {/* Dot indicator for review availability */}
                            {day.hasReview && (
                              <span className={`absolute bottom-1 h-1 w-1 rounded-full ${
                                day.isSelected ? 'bg-white' : 'bg-[#4a7c59]'
                              }`} />
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </>
              )}
            </div>
          )}

          {([
            ['markdown', '市场全景', Brain],
            ['themes', '题材周期', Layers],
            ['capital_flows', '资金脉络', Activity],
          ] as const).map(([view, label, Icon]) => (
            <button
              key={view}
              onClick={() => { setIsTocOpen(false); setShowWeeklyFocusInline(false); setMarketMemoryView(view); setShowMarketMemoryInline(true); }}
              className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-bold shadow-xs transition-all ${
                showMarketMemoryInline && marketMemoryView === view
                  ? 'border-[#705c30] bg-[#705c30] text-white'
                  : 'border-[#705c30]/40 bg-white text-[#705c30] hover:bg-[#705c30]/10'
              }`}
              title={`查看${label}`}
            >
              <Icon className={`h-3.5 w-3.5 ${(view === 'markdown' ? panoramaUpdating : memoryUpdating) ? 'animate-spin' : ''}`} />
              <span>{(view === 'markdown' ? panoramaUpdating : memoryUpdating) ? `${label}更新中...` : label}</span>
            </button>
          ))}

          <button
            onClick={() => { setIsTocOpen(false); setShowMarketMemoryInline(false); setShowWeeklyFocusInline((current) => !current); }}
            className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-bold shadow-xs transition-all ${
              showWeeklyFocusInline
                ? 'border-[#4a7c59] bg-[#4a7c59] text-white'
                : 'border-[#4a7c59]/40 bg-white text-[#4a7c59] hover:bg-[#4a7c59]/10'
            }`}
            title="在当前页面查看关键股票"
          >
            <Tag className="h-3.5 w-3.5" />
            关键股票
          </button>

        </div>
      </header>

      {showMarketMemoryInline && !showWeeklyFocusInline && (
        <MarketMemoryModal
          isOpen={showMarketMemoryInline}
        inline
        onClose={() => setShowMarketMemoryInline(false)}
        tradeDate={payload?.trade_date || tradeDate}
        view={marketMemoryView}
        onOpenKline={(stock) => handleStockClick(stock.code, stock.name)}
      />
      )}

      {showWeeklyFocusInline && (
        <section id="weekly-focus-inline" className="flex-1 min-h-0 overflow-y-auto px-1 pb-2 lg:flex lg:items-start lg:gap-4">
          <aside className="mb-3 shrink-0 rounded-lg border border-[#c4c8bc]/50 bg-white p-2 lg:sticky lg:top-0 lg:mb-0 lg:max-h-[calc(100vh-12rem)] lg:w-48 lg:overflow-y-auto">
            <nav className="flex flex-wrap gap-1.5 lg:flex-col" aria-label={weeklyFocusView === 'date' ? '关键股票日期导航' : '关键股票题材导航'}>
              {(weeklyFocusView === 'date' ? weeklyFocusDateGroups : weeklyFocusGroups).map((group, groupIndex) => {
                const label = weeklyFocusView === 'date' ? formatDateLabel((group as { date: string }).date) : (group as { sector: string }).sector;
                return <button key={label} onClick={() => document.getElementById(`weekly-focus-inline-group-${groupIndex}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })} className="rounded-lg border border-[#705c30]/30 bg-[#faf8f3] px-2 py-1 text-left text-[11px] font-bold text-[#705c30] hover:bg-[#705c30] hover:text-white lg:w-full">
                  {label}（{group.stocks.length}只）
                </button>;
              })}
            </nav>
          </aside>
          <div className="min-w-0 flex-1">
          <div className="mb-3 flex items-center gap-2 rounded-lg border border-[#c4c8bc]/60 bg-white px-3 py-2">
            <input value={weeklyFocusQuery} onChange={(event) => setWeeklyFocusQuery(event.target.value)} placeholder="搜索股票名称或代码" className="min-w-0 flex-1 bg-transparent text-sm text-[#2e3230] outline-none placeholder:text-[#9a9d96]" aria-label="搜索关键股票" />
            {weeklyFocusQuery && <button onClick={() => setWeeklyFocusQuery('')} className="text-xs font-bold text-[#705c30]">清空</button>}
          </div>
          <div className="mb-3 inline-flex rounded-lg border border-[#c4c8bc]/60 bg-white p-1 text-xs font-bold">
            <button onClick={() => setWeeklyFocusView('date')} className={`rounded-md px-3 py-1.5 ${weeklyFocusView === 'date' ? 'bg-[#705c30] text-white' : 'text-[#686d68] hover:text-[#2e3230]'}`}>按日期</button>
            <button onClick={() => setWeeklyFocusView('theme')} className={`rounded-md px-3 py-1.5 ${weeklyFocusView === 'theme' ? 'bg-[#705c30] text-white' : 'text-[#686d68] hover:text-[#2e3230]'}`}>按题材</button>
          </div>
          {(weeklyFocusView === 'date' ? weeklyFocusDateGroups : weeklyFocusGroups).length ? (
            <div className="space-y-3">
              {(weeklyFocusView === 'date' ? weeklyFocusDateGroups : weeklyFocusGroups).map((group, groupIndex) => (
                <section id={`weekly-focus-inline-group-${groupIndex}`} key={weeklyFocusView === 'date' ? (group as { date: string }).date : (group as { sector: string }).sector} className="scroll-mt-3 overflow-x-auto rounded-lg border border-[#c4c8bc]/60 bg-white">
                  <div className="border-b border-[#eae6de] bg-[#f0ece4] px-3 py-2 text-sm font-extrabold text-[#2e3230]">{weeklyFocusView === 'date' ? formatDateLabel((group as { date: string }).date) : (group as { sector: string }).sector}（{group.stocks.length}只）</div>
                  <table className="w-full min-w-[620px] text-left text-xs"><thead className="border-b border-[#eae6de] text-[#686d68]"><tr><th className="px-3 py-2">股票</th>{weeklyFocusView === 'date' ? <><th className="px-3 py-2">题材</th><th className="px-3 py-2">提及逻辑</th></> : <th className="px-3 py-2">提及日期</th>}{data.weekly_focus?.price_window_dates.map((date) => <th key={date} className="px-2 py-2 text-right">{formatDateLabel(date)}</th>)}</tr></thead><tbody className="divide-y divide-[#eae6de]">{group.stocks.map((stock) => <tr key={`${stock.ts_code}-${stock.mention_date || ''}`}><td className="px-3 py-2 font-bold text-[#2e3230]"><button onClick={() => handleStockClick(stock.ts_code, stock.name)} className="text-left hover:text-[#705c30]">{stock.name}<span className="block text-[10px] font-mono text-[#686d68]">{stock.ts_code}</span></button></td>{weeklyFocusView === 'date' ? <><td className="px-3 py-2 text-[#705c30]">{stock.sector}</td><td className="max-w-[16rem] px-3 py-2 text-[#686d68]">{stock.story || stock.tag}</td></> : <td className="px-3 py-2 text-[#686d68]">{(stock.mention_dates || []).map(formatDateLabel).join('、')}</td>}{data.weekly_focus?.price_window_dates.map((date) => { const day = stock.daily?.find((item) => item.date === date); const isDown = day?.pct_change?.startsWith('-'); return <td key={date} className={`px-2 py-2 text-right font-mono font-bold ${isDown ? 'quote-down text-[#237a4b]' : day ? 'quote-up text-[#b83230]' : ''}`}>{day?.pct_change || '—'}</td>; })}</tr>)}</tbody></table>
                </section>
              ))}
            </div>
          ) : <div className="rounded-lg border border-dashed border-[#c4c8bc] bg-white p-5 text-center text-sm text-[#686d68]">没有找到匹配的股票。</div>}
          </div>
        </section>
      )}

      {/* 3. 独立滚动双栏布局容器 (高度固定，阻止 overscroll 链传导) */}
      {!showWeeklyFocusInline && !showMarketMemoryInline && <div className="flex-1 overflow-hidden min-h-0">
        {/* 每日复盘文章：主内容占满页面，不再显示右侧客观行情看板 */}
        <main className="h-full overflow-y-auto overscroll-contain pr-1.5 space-y-3">
          <article className="rounded-xl border border-[#c4c8bc]/40 bg-[#faf8f3] p-4 sm:p-5 shadow-xs">
            {renderFormattedMarkdown(articleMarkdown)}
          </article>
        </main>

        {/* 右侧客观行情看板已从每日复盘界面移除，保留独立功能入口。 */}
        {false && <aside className="col-span-12 h-full overflow-y-auto overscroll-contain pr-1.5 space-y-3 lg:col-span-4">
          {!marketData && (
            <div className="rounded-xl border border-[#d8c9a8] bg-[#fbf7ee] px-3.5 py-3 text-xs text-[#705c30]">
              <div className="font-bold">本日客观行情数据尚未就绪</div>
              <div className="mt-1 text-[#686d68]">复盘文章已可阅读，行情数据完成同步后会显示。{marketDataError ? `（${marketDataError}）` : ''}</div>
            </div>
          )}
            {/* 卡片 1: 核心大盘指数与市场广度 */}
            <section className="rounded-xl border border-[#c4c8bc]/40 bg-white p-3.5 shadow-xs space-y-2.5">
              <div className="flex items-center justify-between border-b border-[#eae6de] pb-1.5">
                <h2 className="flex items-center gap-1.5 text-xs sm:text-sm font-extrabold text-[#2e3230]">
                  <BarChart2 className="h-4 w-4 text-[#4a7c59]" />
                  核心大盘指数与成交
                </h2>
              </div>

              {/* 指数列表 */}
              <div className="space-y-1.5">
                {data.indices.map((idxItem, idx) => (
                  <div 
                    key={idx} 
                    className="flex items-center justify-between rounded-md border border-[#c4c8bc]/30 bg-[#faf8f5] px-3 py-1.5 text-xs shadow-2xs hover:border-[#4a7c59]/40 transition-colors"
                  >
                    <div>
                      <span className="font-bold text-[#2e3230] block">{idxItem.name}</span>
                      <span className="text-[10px] text-[#686d68]">{idxItem.symbol}</span>
                    </div>
                    <div className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <span className="font-extrabold text-[#2e3230]">{idxItem.close}</span>
                        <span className={`font-bold px-1 py-0.2 rounded text-[10px] ${
                          idxItem.is_up ? 'bg-[#b83230]/10 text-[#b83230]' : 'bg-[#237a4b]/10 text-[#237a4b]'
                        }`}>
                          {idxItem.pct_change}
                        </span>
                      </div>
                      <div className="text-[10px] text-[#686d68]">
                        成交: {idxItem.amount} ({idxItem.amount_diff})
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {/* 市场广度与涨跌比 */}
              <div className="rounded-lg border border-[#e2d5bd] bg-[#fbf7ee] p-2.5 space-y-2 text-xs">
                <div className="flex items-center justify-between font-bold text-[#2e3230]">
                  <span>沪深成交：<strong className="text-[#705c30]">{data.breadth.total_amount}</strong></span>
                  <span className="text-[10px] text-[#4a7c59] bg-[#4a7c59]/10 px-1.5 py-0.2 rounded">{data.breadth.total_amount_diff}</span>
                </div>

                {/* 涨跌分布比例条 */}
                <div className="space-y-1">
                  <div className="flex justify-between text-[10px] font-bold">
                    <span className="text-[#b83230]">上涨 {data.breadth.rising_count}只</span>
                    <span className="text-[#237a4b]">下跌 {data.breadth.falling_count}只</span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-[#237a4b] overflow-hidden flex">
                    <div 
                      className="h-full bg-[#b83230] transition-all duration-500" 
                      style={{ width: `${risingRatio}%` }} 
                    />
                  </div>
                </div>

                {/* 涨停跌停细节 */}
                <div className="grid grid-cols-3 gap-1.5 pt-1 text-center border-t border-[#e2d5bd]/60 text-[10px]">
                  <div className="bg-white p-1 rounded border border-[#c4c8bc]/30">
                    <span className="text-[#686d68] block">涨停家数</span>
                    <span className="font-bold text-[#b83230]">{data.breadth.limit_up_count}只</span>
                  </div>
                  <div className="bg-white p-1 rounded border border-[#c4c8bc]/30">
                    <span className="text-[#686d68] block">跌停/炸板</span>
                    <span className="font-bold text-[#237a4b]">{data.breadth.limit_down_count} / {data.breadth.limit_up_broken_count}</span>
                  </div>
                  <div className="bg-white p-1 rounded border border-[#c4c8bc]/30">
                    <span className="text-[#686d68] block">封板率</span>
                    <span className="font-bold text-[#705c30]">{data.breadth.limit_up_seal_rate}</span>
                  </div>
                </div>
              </div>
            </section>

            {/* 卡片 2: 同花顺概念板块榜单 (THS Concept Boards) */}
            <section className="rounded-xl border border-[#c4c8bc]/40 bg-white p-3.5 shadow-xs space-y-2.5">
              <div className="flex items-center justify-between border-b border-[#eae6de] pb-1.5">
                <h2 className="flex items-center gap-1.5 text-xs sm:text-sm font-extrabold text-[#2e3230]">
                  <Flame className="h-4 w-4 text-[#b83230]" />
                  同花顺概念板块榜单 (THS)
                </h2>
              </div>

              {/* 领涨板块列表 */}
              <div className="space-y-1.5">
                <span className="text-[11px] font-bold text-[#b83230] flex items-center gap-0.5">
                  <ArrowUpRight className="h-3 w-3" /> 领涨同花顺概念 TOP 6
                </span>
                {data.ths_concepts.top_gainers.map((concept, idx) => (
                  <div 
                    key={idx} 
                    className="flex items-center justify-between rounded-md border border-[#c4c8bc]/30 bg-[#faf8f5] px-2 py-1.5 text-xs hover:border-[#b83230]/40 transition-colors"
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-[#b83230]/10 text-[9px] font-bold text-[#b83230]">
                        {idx + 1}
                      </span>
                      <div>
                        <span className="font-bold text-[#2e3230] block">{concept.name}</span>
                        <span className="text-[10px] text-[#686d68]">领涨: {concept.leading_stock}</span>
                      </div>
                    </div>
                    <div className="text-right">
                      <span className="font-extrabold text-[#b83230] block text-xs">{concept.pct_change}</span>
                      <span className="text-[9px] text-[#686d68]">{concept.amount}</span>
                    </div>
                  </div>
                ))}
              </div>

              {/* 领跌板块 */}
              {data.ths_concepts.top_losers && data.ths_concepts.top_losers.length > 0 && (
                <div className="space-y-1.5 pt-1.5 border-t border-[#eae6de]">
                  <span className="text-[11px] font-bold text-[#237a4b] flex items-center gap-0.5">
                    <ArrowDownRight className="h-3 w-3" /> 领跌/分歧概念
                  </span>
                  {data.ths_concepts.top_losers.map((concept, idx) => (
                    <div 
                      key={idx} 
                      className="flex items-center justify-between rounded-md border border-[#c4c8bc]/30 bg-[#faf8f5] px-2 py-1 text-xs"
                    >
                      <span className="font-bold text-[#2e3230]">{concept.name}</span>
                      <div className="text-right">
                        <span className="font-bold text-[#237a4b] text-xs block">{concept.pct_change}</span>
                        <span className="text-[9px] text-[#686d68]">{concept.leading_stock}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* 卡片 3: 关键焦点股票 (前日提及次日验证 vs 今日提及) */}
            <section className="rounded-xl border border-[#c4c8bc]/40 bg-white p-3.5 shadow-xs space-y-2.5">
              <div className="flex items-center justify-between border-b border-[#eae6de] pb-2">
                <div className="flex items-center gap-1.5">
                  <Tag className="h-4 w-4 text-[#705c30]" />
                  <h2 className="text-sm font-extrabold text-[#2e3230]">关键焦点股票</h2>
                </div>
                <button
                  onClick={() => { setIsTocOpen(false); setShowMarketMemoryInline(false); setShowWeeklyFocusInline(true); }}
                  className="text-[11px] font-bold text-[#705c30] hover:text-[#4a7c59] bg-[#705c30]/10 hover:bg-[#705c30]/20 px-2 py-0.5 rounded transition flex items-center gap-0.5"
                  title="查看最近一周按题材分组的关注股票"
                >
                  <Maximize2 className="h-3 w-3" />
                  打开关键股票
                </button>
              </div>

              {/* 双 Tab 切换开关 */}
              <div className="grid grid-cols-2 gap-1 p-1 bg-[#f4efe6] rounded-lg text-xs font-bold">
                <button
                  onClick={() => setFocusStockTab('prev_verify')}
                  className={`py-1.5 rounded-md transition text-center ${
                    focusStockTab === 'prev_verify'
                      ? 'bg-[#705c30] text-white shadow-2xs'
                      : 'text-[#686d68] hover:text-[#2e3230]'
                  }`}
                >
                  {formatDayLabel(prevMentionDate)}复盘提及·{formatDayLabel(verificationDate)}行情验证 ({data.key_stocks.length})
                </button>
                <button
                  onClick={() => setFocusStockTab('today_mentioned')}
                  className={`py-1.5 rounded-md transition text-center ${
                    focusStockTab === 'today_mentioned'
                      ? 'bg-[#705c30] text-white shadow-2xs'
                      : 'text-[#686d68] hover:text-[#2e3230]'
                  }`}
                >
                  {formatDayLabel(activeDate)}复盘提及 ({(data.today_stocks || []).length})
                </button>
              </div>

              {/* 列表渲染 (已移除多余内部嵌套滚动条，跟随右栏整体平滑滚动) */}
              <div className="space-y-2">
                {focusStockTab === 'prev_verify' ? (
                  /* Tab 1: 前日提及 vs 今日表现对比 */
                  data.key_stocks.map((stock, idx) => {
                    const prevPct = stock.prev_pct_change || '0.00%';
                    const prevIsUp = !prevPct.includes('-');
                    return (
                      <button
                        key={idx}
                        onClick={() => handleStockClick(stock.ts_code, stock.name)}
                        className="focus-stock-card w-full rounded-lg border border-[#c4c8bc]/50 bg-[#faf8f5] p-2.5 text-xs text-left hover:border-[#705c30] hover:bg-white transition-all shadow-2xs group space-y-1.5"
                      >
                        <div className="flex items-center justify-between border-b border-[#eae6de]/60 pb-1">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="font-extrabold text-sm text-[#2e3230] group-hover:text-[#705c30]">{stock.name}</span>
                            <span className="text-[10px] font-mono text-[#686d68]">{stock.ts_code}</span>
                            {stock.sector && (
                              <span className="px-1.5 py-0.2 rounded bg-[#705c30]/15 text-[#705c30] text-[10px] font-bold border border-[#705c30]/20">
                                {stock.sector}
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] font-bold text-[#705c30] bg-[#705c30]/10 px-1.5 py-0.5 rounded">
                            点击看K线
                          </span>
                        </div>

                        {/* 对比渲染区域 */}
                        <div className="grid grid-cols-2 gap-2 text-[11px]">
                          {/* 左侧：前日提及与前日表现 */}
                          <div className="focus-stock-mention rounded border border-[#c4c8bc]/30 bg-[#f0ece4]/70 p-1.5">
                            <span className="text-[#686d68] block text-[10px]">{formatDayLabel(prevMentionDate)}定位标签</span>
                            <span className="font-bold text-[#2e3230] block truncate" title={stock.tag}>{stock.tag}</span>
                            <span className={`font-mono font-bold text-[10px] ${prevIsUp ? 'text-[#b83230]' : 'text-[#237a4b]'}`}>
                              {formatDayLabel(prevMentionDate)}涨跌: {prevPct}
                            </span>
                            {stock.story && <span className="mt-1 block text-[10px] leading-4 text-[#686d68]">{stock.story}</span>}
                          </div>

                          {/* 右侧：今日验证表现 */}
                          <div className="focus-stock-verification rounded border border-[#c4c8bc]/40 bg-white p-1.5">
                            <span className="text-[#686d68] block text-[10px]">{formatDayLabel(verificationDate)}验证表现</span>
                            <span className={`font-mono font-extrabold text-xs block ${stock.is_up ? 'text-[#b83230]' : 'text-[#237a4b]'}`}>
                              {formatDayLabel(verificationDate)}: {stock.pct_change}
                            </span>
                            <span className="text-[10px] text-[#686d68] block">{formatDayLabel(verificationDate)}成交 {stock.amount}</span>
                          </div>
                        </div>
                      </button>
                    );
                  })
                ) : (
                  /* Tab 2: 今日复盘提及 */
                  (data.today_stocks || []).map((stock, idx) => (
                    <button
                      key={idx}
                      onClick={() => handleStockClick(stock.ts_code, stock.name)}
                      className="w-full flex items-center justify-between rounded-lg border border-[#c4c8bc]/40 bg-[#faf6f0] px-3 py-2 text-xs text-left hover:border-[#705c30] hover:bg-white transition-all shadow-2xs group"
                    >
                      <div>
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-bold text-sm text-[#2e3230] group-hover:text-[#705c30]">{stock.name}</span>
                          <span className="text-[10px] text-[#686d68]">{stock.ts_code}</span>
                          {stock.sector && (
                            <span className="px-1.5 py-0.2 rounded bg-[#705c30]/15 text-[#705c30] text-[10px] font-bold border border-[#705c30]/20">
                              {stock.sector}
                            </span>
                          )}
                        </div>
                        <span className={`inline-block mt-1 text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          !stock.market_data_available
                            ? 'text-[#686d68] bg-[#686d68]/10 border border-[#686d68]/20'
                            : stock.is_up 
                            ? 'text-[#b83230] bg-[#b83230]/10 border border-[#b83230]/20' 
                            : 'text-[#237a4b] bg-[#237a4b]/10 border border-[#237a4b]/20'
                        }`}>
                          {stock.tag}
                        </span>
                        {stock.story && <span className="mt-1 block max-w-[18rem] text-[10px] leading-4 text-[#686d68]">{stock.story}</span>}
                      </div>

                      <div className="text-right">
                        <span className={`font-extrabold text-sm block ${!stock.market_data_available ? 'text-[#686d68]' : stock.is_up ? 'text-[#b83230]' : 'text-[#237a4b]'}`}>
                          {stock.pct_change}
                        </span>
                        <span className="text-[10px] text-[#686d68]">成交 {stock.amount}</span>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </section>
        </aside>}
      </div>}

      {detailStock && (
        <SecondaryStockDetailDrawer
          isOpen={true}
          onClose={() => setDetailStock(null)}
          tsCode={detailStock.code}
          stockName={detailStock.name}
          asOfDate={activeDate}
          computeOnOpen={false}
          useCurrentProfiles={true}
          basicAnalysisRunning={basicAnalysisRunning}
          onRunBasicAnalysis={runBasicAnalysis}
          onTriggerThemeMatch={runStockThemeMatch}
          onTriggerAI={runStockAIResearch}
        />
      )}

      {/* 全屏跨日跟踪对比大表 Modal */}
      {isFocusTableModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4 animate-in fade-in duration-200">
          <div className="flex flex-col w-full max-w-5xl h-[85vh] rounded-2xl bg-[#faf8f3] border border-[#c4c8bc]/80 shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[#c4c8bc]/60 bg-white">
              <div className="flex items-center gap-2">
                <Tag className="h-5 w-5 text-[#705c30]" />
                <h3 className="text-base font-extrabold text-[#2e3230]">
                  关键股票 —— 按题材跟踪 ({data.weekly_focus?.stock_count || 0}只)
                </h3>
              </div>
              <button
                onClick={() => setIsFocusTableModalOpen(false)}
                className="p-1.5 rounded-lg text-[#686d68] hover:bg-[#c4c8bc]/30 hover:text-[#2e3230] transition"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-6">
              <div className="mb-4 flex items-center gap-2 rounded-lg border border-[#c4c8bc]/60 bg-white px-3 py-2">
                <input
                  value={weeklyFocusQuery}
                  onChange={(event) => setWeeklyFocusQuery(event.target.value)}
                  placeholder="搜索股票名称或代码"
                  className="min-w-0 flex-1 bg-transparent text-sm text-[#2e3230] outline-none placeholder:text-[#9a9d96]"
                  aria-label="搜索关键股票"
                />
                {weeklyFocusQuery && (
                  <button onClick={() => setWeeklyFocusQuery('')} className="text-xs font-bold text-[#705c30] hover:text-[#2e3230]">清空</button>
                )}
              </div>
              {weeklyFocusGroups.length ? (
                <div className="space-y-4 mb-5">
                  <p className="text-xs text-[#686d68]">窗口：{data.weekly_focus?.window_dates.map(formatDateLabel).join('、')}。{weeklyFocusQuery ? `已筛选出 ${weeklyFocusGroups.reduce((count, group) => count + group.stocks.length, 0)} 只股票。` : '同一股票若连续多日被提及，会合并在同一题材下。'}</p>
                  <nav className="sticky top-0 z-10 -mx-1 flex flex-wrap gap-1.5 rounded-lg border border-[#c4c8bc]/50 bg-[#faf8f3]/95 p-2 backdrop-blur-xs" aria-label="关键股票题材目录">
                    {weeklyFocusGroups.map((group, groupIndex) => (
                      <button
                        key={group.sector}
                        onClick={() => document.getElementById(`weekly-focus-group-${groupIndex}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                        className="rounded-full border border-[#705c30]/30 bg-white px-2.5 py-1 text-[11px] font-bold text-[#705c30] transition hover:bg-[#705c30] hover:text-white"
                      >
                        {group.sector} <span className="opacity-70">（{group.stocks.length}只）</span>
                      </button>
                    ))}
                  </nav>
                  {weeklyFocusGroups.map((group, groupIndex) => (
                    <section id={`weekly-focus-group-${groupIndex}`} key={group.sector} className="scroll-mt-14 rounded-xl border border-[#c4c8bc]/60 bg-white overflow-hidden shadow-2xs">
                      <div className="px-4 py-3 bg-[#f0ece4] border-b border-[#c4c8bc]/60 flex items-center justify-between">
                        <span className="font-extrabold text-sm text-[#2e3230]">{group.sector}</span>
                        <span className="text-xs text-[#686d68]">{group.stocks.length}只</span>
                      </div>
                      <div className="overflow-x-auto">
                        <table className="w-full text-left text-xs border-collapse">
                          <thead className="text-[#686d68] border-b border-[#eae6de]"><tr>
                            <th className="px-4 py-2">股票</th><th className="px-4 py-2">提及日期</th>
                            {data.weekly_focus?.price_window_dates.map((date) => <th key={date} className="px-3 py-2 text-right">{formatDateLabel(date)}</th>)}
                          </tr></thead>
                          <tbody className="divide-y divide-[#eae6de]">
                            {group.stocks.map((stock) => (
                              <tr key={`${group.sector}-${stock.ts_code}`} className="hover:bg-[#faf8f5]">
                                <td className="px-4 py-3 font-bold text-[#2e3230] whitespace-nowrap">
                                  <button onClick={() => handleStockClick(stock.ts_code, stock.name)} className="text-left hover:text-[#705c30]">
                                    {stock.name}<span className="block text-[10px] text-[#686d68] font-mono">{stock.ts_code}</span>
                                  </button>
                                </td>
                                <td className="px-4 py-3 text-[#686d68] whitespace-nowrap">{(stock.mention_dates || []).map(formatDateLabel).join('、')}</td>
                                {data.weekly_focus?.price_window_dates.map((date) => {
                                  const day = stock.daily?.find((item) => item.date === date);
                                  const isDown = day?.pct_change?.startsWith('-');
                                  return <td key={date} className={`px-3 py-3 text-right font-mono font-bold whitespace-nowrap ${isDown ? 'quote-down text-[#237a4b]' : day ? 'quote-up text-[#b83230]' : ''}`}>{day ? day.pct_change : '—'}</td>;
                                })}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </section>
                  ))}
                </div>
              ) : <div className="mb-5 rounded-lg border border-dashed border-[#c4c8bc] bg-white p-6 text-center text-sm text-[#686d68]">没有找到匹配的股票。</div>}
              <h4 className="text-xs font-extrabold text-[#686d68] mb-2">当前复盘日的前一交易日验证明细</h4>
              <div className="rounded-xl border border-[#c4c8bc]/60 bg-white overflow-hidden shadow-2xs">
                <table className="w-full text-left text-xs border-collapse">
                  <thead className="bg-[#f0ece4] text-[#2e3230] font-extrabold border-b border-[#c4c8bc]/60">
                    <tr>
                      <th className="px-4 py-3">股票名称 / 代码</th>
                      <th className="px-4 py-3">题材方向</th>
                      <th className="px-4 py-3">{mentionDateLabel}提及标签与定位</th>
                      <th className="px-4 py-3 text-right">{mentionDateLabel}涨跌幅</th>
                      <th className="px-4 py-3 text-right">{verificationDateLabel}验证表现</th>
                      <th className="px-4 py-3 text-right">{verificationDateLabel}成交额</th>
                      <th className="px-4 py-3 text-center">快捷工具</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#eae6de]">
                    {data.key_stocks.map((stock, idx) => {
                      const prevPct = stock.prev_pct_change || '0.00%';
                      const prevIsUp = !prevPct.includes('-');
                      return (
                        <tr key={idx} className="hover:bg-[#faf8f5] transition-colors">
                          <td className="px-4 py-3 font-bold text-sm text-[#2e3230]">
                            {stock.name}
                            <span className="text-xs text-[#686d68] font-mono block">{stock.ts_code}</span>
                          </td>
                          <td className="px-4 py-3">
                            <span className="px-2 py-1 rounded bg-[#705c30]/15 text-[#705c30] font-bold text-xs border border-[#705c30]/20">
                              {stock.sector || '主线/观察'}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <span className="px-2 py-1 rounded bg-[#f0ece4] text-[#2e3230] font-bold text-xs">
                              {stock.tag}
                            </span>
                          </td>
                          <td className={`px-4 py-3 text-right font-mono font-bold text-xs ${prevIsUp ? 'quote-up text-[#b83230]' : 'quote-down text-[#237a4b]'}`}>
                            {prevPct}
                          </td>
                          <td className={`px-4 py-3 text-right font-mono font-extrabold text-sm ${stock.is_up ? 'quote-up text-[#b83230]' : 'quote-down text-[#237a4b]'}`}>
                            {stock.pct_change}
                          </td>
                          <td className="px-4 py-3 text-right text-xs text-[#686d68] font-mono">
                            {stock.amount}
                          </td>
                          <td className="px-4 py-3 text-center">
                            <button
                              onClick={() => handleStockClick(stock.ts_code, stock.name)}
                              className="px-2.5 py-1 bg-[#4a7c59] text-white rounded text-xs font-bold hover:bg-[#3b6447] transition shadow-2xs"
                            >
                              看 K 线
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="px-6 py-3 bg-[#f0ece4] border-t border-[#c4c8bc]/60 text-right">
              <button
                onClick={() => setIsFocusTableModalOpen(false)}
                className="px-4 py-1.5 bg-[#2e3230] text-white rounded-lg text-xs font-bold hover:bg-[#4a4e4a] transition shadow-xs"
              >
                关闭大表
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
