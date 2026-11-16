'use client';

import React, { useState, useEffect } from 'react';
import { 
  Brain, 
  RefreshCw, 
  Download, 
  Copy, 
  Check, 
  Layers, 
  Sparkles, 
  Calendar, 
  Activity, 
  AlertCircle,
  Workflow
} from 'lucide-react';

interface ThemeItem {
  canonical_name: string;
  aliases?: string[];
  status: 'CURRENT_ACTIVE' | 'RECENTLY_ACTIVE' | 'DORMANT_BUT_TRADED' | 'DECAYED' | string;
  parent_theme?: string;
  first_seen_date?: string;
  last_active_date?: string;
  evolution_summary?: string;
  key_review_dates?: string[];
  phases?: ThemePhase[];
}

interface ThemePhase {
  time_range: string;
  stage_name: string;
  description: string;
  core_stocks: Array<{
    name: string;
    ts_code?: string | null;
    /** 该阶段结束日（若非交易日则最近前一交易日）的真实日线涨跌幅。 */
    pct_chg?: number | null;
    quote_date?: string | null;
  }>;
  non_security_entities?: Array<{
    name: string;
    reason: string;
  }>;
}

/**
 * 主题周期的内容由模型提供事实，展示层负责稳定排版。
 * 旧快照中的 evolution_summary 可能是一整段按日期串联的长文，
 * 这里仅按原文中的日期和标点切分，不改写、不补充事实。
 */
// 只有段落/分句开头的日期才是新的时间节点；正文中的“相较 9 月 4 日”等引用日期不拆行。
const EVOLUTION_DATE_RE = /(?:^|[；。！？\n])\s*((?:\d{1,2}月\d{1,2}日|\d{1,2}[./年]\d{1,2}(?:日)?))/g;

function splitReadableParagraphs(value: string): string[] {
  const text = value.replace(/\s+/g, ' ').trim();
  if (!text) return [];
  const pieces = text
    .split(/(?<=[。！？；])\s*/)
    .map((item) => item.trim())
    .filter(Boolean);
  return pieces.length > 1 ? pieces : [text];
}

function renderEvolutionSummary(value: string | undefined, keyPrefix: string): React.ReactNode {
  const text = String(value || '').trim();
  if (!text) return <p className="text-sm leading-7 text-[#686d68]">暂无演化记录</p>;

  const matches = Array.from(text.matchAll(EVOLUTION_DATE_RE));
  if (matches.length >= 2) {
    const entries = matches.map((match, index) => {
      const fullStart = match.index ?? 0;
      const date = match[1] || '';
      const start = fullStart + Math.max(0, match[0].indexOf(date));
      const next = index + 1 < matches.length ? matches[index + 1] : null;
      const end = next ? (next.index ?? text.length) : text.length;
      return { date, body: text.slice(start + date.length, end).trim() };
    }).filter((entry) => entry.body);
    const firstDate = matches[0][1] || '';
    const firstDateStart = (matches[0].index ?? 0) + Math.max(0, matches[0][0].indexOf(firstDate));
    const intro = text.slice(0, firstDateStart).trim();
    return (
      <div className="space-y-1">
        {intro && <p className="text-sm leading-8 text-[#4a4e4a]">{intro}</p>}
        {entries.map((entry, index) => (
          <p key={`${keyPrefix}-${index}`} className="text-sm leading-8 text-[#4a4e4a]">
            <span className="mr-2 font-mono font-extrabold text-[#705c30]">{entry.date}</span>
            {entry.body}
          </p>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {splitReadableParagraphs(text).map((paragraph, index) => (
        <p key={`${keyPrefix}-${index}`} className="text-sm leading-8 text-[#4a4e4a]">{paragraph}</p>
      ))}
    </div>
  );
}

interface CapitalFlowItem {
  time_range: string;
  stage_name: string;
  main_sectors: string[];
  core_stocks: string[];
  divergence_sectors?: string[];
  divergence_stocks?: string[];
  outflow_sectors?: string[];
  outflow_stocks?: string[];
  flow_description: string;
  transition_trigger?: string;
}

interface CapitalFlowStockResolution {
  code: string;
  name: string;
}

interface MemoryData {
  status?: 'SUCCESS' | 'PENDING' | 'GENERATING' | 'FAILED';
  as_of_date: string;
  latest_available_date?: string | null;
  message?: string;
  memory_json: {
    as_of_date?: string;
    actual_lookback_sessions?: number;
    themes?: ThemeItem[];
    capital_flows?: CapitalFlowItem[];
    binding_warnings?: string[];
  };
  summary_markdown: string;
}

interface MarketPanoramaData {
  status?: 'SUCCESS' | 'PENDING' | 'GENERATING' | 'FAILED';
  as_of_date: string;
  latest_available_date?: string | null;
  message?: string;
  state: {
    window?: { actual_first_review_date?: string; end_date?: string; review_count?: number };
    stories?: Array<Record<string, unknown>>;
  } | null;
  summary_markdown: string;
}

interface MarketMemoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  tradeDate: string;
  inline?: boolean;
  view?: 'markdown' | 'themes' | 'capital_flows';
  onOpenKline?: (stock: { code: string; name: string }) => void;
}

export default function MarketMemoryModal({ isOpen, onClose, tradeDate, inline = false, view, onOpenKline }: MarketMemoryModalProps) {
  const [data, setData] = useState<MemoryData | null>(null);
  const [panorama, setPanorama] = useState<MarketPanoramaData | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [triggering, setTriggering] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'markdown' | 'themes' | 'capital_flows'>('markdown');
  const [copied, setCopied] = useState<boolean>(false);
  const [capitalFlowStockResolutions, setCapitalFlowStockResolutions] = useState<Record<string, CapitalFlowStockResolution>>({});

  const fetchMemory = async (silent: boolean = false) => {
    if (!tradeDate) return;
    if (!silent) setLoading(true);
    setError(null);
    try {
      const apiBase = 'http://127.0.0.1:18080';
      const [memoryRes, panoramaRes] = await Promise.all([
        fetch(`${apiBase}/api/market-review/market-memory?date=${tradeDate}&force_refresh=false`),
        fetch(`${apiBase}/api/market-review/market-panorama?date=${tradeDate}`),
      ]);
      if (!memoryRes.ok) {
        throw new Error(`HTTP ${memoryRes.status}: 读取题材周期与资金脉络失败`);
      }
      if (!panoramaRes.ok) {
        throw new Error(`HTTP ${panoramaRes.status}: 读取市场全景状态失败`);
      }
      setData(await memoryRes.json());
      setPanorama(await panoramaRes.json());
    } catch (err) {
      if (!silent) {
        setError(err instanceof Error ? err.message : '读取市场全景失败');
      }
    } finally {
      if (!silent) setLoading(false);
    }
  };

  // 触发后台异步推演并轮询状态
  const handleTriggerRecompute = async (scope: 'legacy' | 'panorama' = 'legacy') => {
    if (!tradeDate) return;
    setTriggering(true);
    setError(null);
    try {
      const apiBase = 'http://127.0.0.1:18080';
      const triggerPath = scope === 'panorama'
        ? '/api/market-review/market-panorama/trigger'
        : '/api/market-review/market-memory/trigger';
      const triggerRes = await fetch(`${apiBase}${triggerPath}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(scope === 'panorama' ? { date: tradeDate, force_rebuild: true } : { date: tradeDate, force_refresh: true }),
      });
      if (!triggerRes.ok) {
        throw new Error(`启动更新失败: HTTP ${triggerRes.status}`);
      }

      // 启动轮询检查状态
      let attempts = 0;
      const interval = setInterval(async () => {
        attempts += 1;
        try {
          const statusPath = scope === 'panorama'
            ? '/api/market-review/market-panorama/status'
            : `/api/market-review/market-memory/status?date=${tradeDate}`;
          const statusRes = await fetch(`${apiBase}${statusPath}`);
          if (statusRes.ok) {
            const statusJson = await statusRes.json();
            if (!statusJson.running) {
              clearInterval(interval);
              setTriggering(false);
              if (statusJson.error) {
                setError(`推演遇到异常: ${statusJson.error}`);
              } else {
                fetchMemory(false);
              }
            }
          }
        } catch {
          // ignore network hiccups during polling
        }
        if (attempts > 240) {
          clearInterval(interval);
          setTriggering(false);
          setError('推演耗时较长，后台仍在继续处理，请稍后刷新查看');
        }
      }, 2000);
    } catch (err) {
      setTriggering(false);
      setError(err instanceof Error ? err.message : '触发全景更新失败');
    }
  };

  const handleTriggerCapitalFlowRefresh = async () => {
    if (!tradeDate) return;
    setTriggering(true);
    setError(null);
    try {
      const apiBase = 'http://127.0.0.1:18080';
      const res = await fetch(`${apiBase}/api/market-review/market-memory/capital-flows/trigger`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: tradeDate }),
      });
      if (!res.ok) throw new Error(`启动资金脉络回填失败: HTTP ${res.status}`);
      let attempts = 0;
      const interval = setInterval(async () => {
        attempts += 1;
        try {
          const statusRes = await fetch(`${apiBase}/api/market-review/market-memory/capital-flows/status`);
          const statusJson = await statusRes.json();
          if (!statusJson.running) {
            clearInterval(interval); setTriggering(false);
            if (statusJson.error) setError(`资金脉络回填遇到异常: ${statusJson.error}`);
            else fetchMemory(false);
          }
        } catch { /* 网络短暂抖动由下一轮轮询处理 */ }
        if (attempts > 240) { clearInterval(interval); setTriggering(false); setError('资金脉络回填仍在后台处理，请稍后刷新'); }
      }, 2000);
    } catch (err) {
      setTriggering(false);
      setError(err instanceof Error ? err.message : '启动资金脉络回填失败');
    }
  };

  useEffect(() => {
    if (isOpen && tradeDate) {
      fetchMemory(false);
    }
  }, [isOpen, tradeDate]);

  useEffect(() => {
    const needsRefresh = panorama?.status === 'PENDING' || panorama?.status === 'GENERATING'
      || data?.status === 'PENDING' || data?.status === 'GENERATING';
    if (!isOpen || !tradeDate || !needsRefresh) return;
    const timer = window.setInterval(() => { void fetchMemory(true); }, 3000);
    return () => window.clearInterval(timer);
  }, [isOpen, tradeDate, panorama?.status, data?.status]);

  useEffect(() => {
    if (view) setActiveTab(view);
  }, [view]);

  useEffect(() => {
    const flows = data?.memory_json?.capital_flows || [];
    const names = [...new Set(flows.flatMap((flow) => [
      ...(flow.core_stocks || []),
      ...(flow.divergence_stocks || []),
      ...(flow.outflow_stocks || []),
    ].map((name) => String(name).trim()).filter(Boolean)))];
    if (!names.length) {
      setCapitalFlowStockResolutions({});
      return;
    }

    let cancelled = false;
    void fetch('http://127.0.0.1:18080/api/market-review/capital-flow-stocks/resolve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ names }),
    }).then(async (response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json() as Promise<{ resolved?: Record<string, CapitalFlowStockResolution> }>;
    }).then((result) => {
      if (!cancelled) setCapitalFlowStockResolutions(result.resolved || {});
    }).catch(() => {
      if (!cancelled) setCapitalFlowStockResolutions({});
    });

    return () => { cancelled = true; };
  }, [data?.as_of_date, data?.memory_json?.capital_flows]);

  if (!isOpen) return null;

  const handleCopyMarkdown = () => {
    if (!panorama?.summary_markdown) return;
    navigator.clipboard.writeText(panorama.summary_markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadMarkdown = () => {
    if (!panorama?.summary_markdown) return;
    const blob = new Blob([panorama.summary_markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${tradeDate}_市场演进全景纪实.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const renderCapitalFlowStocks = (stocks: string[], className: string, withSeparators = false) => stocks.map((stock, index) => {
    const stockName = String(stock).trim();
    const resolved = capitalFlowStockResolutions[stockName];
    const separator = withSeparators && index < stocks.length - 1 ? <span className="text-[#8c9288]">、</span> : null;
    if (!resolved || !onOpenKline) {
      return <React.Fragment key={`${stockName}-${index}`}><span className={className}>{stockName}</span>{separator}</React.Fragment>;
    }
    return (
      <React.Fragment key={`${stockName}-${index}`}>
        <button
          type="button"
          onClick={() => onOpenKline({ code: resolved.code, name: resolved.name })}
          className={`${className} cursor-pointer transition hover:brightness-90 focus:outline-none focus:ring-2 focus:ring-[#705c30]/40`}
          title={`查看${resolved.name} K线`}
        >
          {stockName}
        </button>
        {separator}
      </React.Fragment>
    );
  });

  // Helper Markdown Formatter (含加粗、列表、表格与段落渲染)
  const parseInlineFormatting = (text: string): React.ReactNode => {
    if (!text) return text;
    // 解析 **bold** 格式
    const parts = text.split(/(\*\*.*?\*\*)/g);
    return parts.map((part, idx) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return (
          <strong key={idx} className="font-extrabold text-[#1a1d1b] bg-[#705c30]/10 px-1 py-0.5 rounded">
            {part.slice(2, -2)}
          </strong>
        );
      }
      return part;
    });
  };

  const renderFormattedMarkdown = (markdownText: string) => {
    if (!markdownText) return null;
    const lines = markdownText.split('\n');
    const elements: React.ReactNode[] = [];
    
    let inTable = false;
    let tableHeaders: string[] = [];
    let tableRows: string[][] = [];

    const flushTable = (keyPrefix: number) => {
      if (tableHeaders.length > 0) {
        elements.push(
          <div key={`table-${keyPrefix}`} className="my-3 overflow-x-auto rounded-lg border border-[#c4c8bc]/60 bg-white shadow-2xs">
            <table className="w-full text-left text-xs border-collapse">
              <thead className="bg-[#f0ece4] text-[#2e3230] font-extrabold border-b border-[#c4c8bc]/50">
                <tr>
                  {tableHeaders.map((th, idx) => (
                    <th key={idx} className="px-3 py-2 font-bold border-r border-[#c4c8bc]/30 last:border-0 whitespace-nowrap">
                      {parseInlineFormatting(th.trim())}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#eae6de]">
                {tableRows.map((row, rIdx) => (
                  <tr key={rIdx} className={rIdx % 2 === 0 ? 'bg-white' : 'bg-[#faf8f5]'}>
                    {row.map((cell, cIdx) => (
                      <td key={cIdx} className="px-3 py-2 border-r border-[#c4c8bc]/20 last:border-0 text-[#2e3230]">
                        {parseInlineFormatting(cell.trim())}
                      </td>
                    ))}
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

    lines.forEach((line, index) => {
      const trimmed = line.trim();

      if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
        const cells = trimmed.split('|').slice(1, -1);
        if (cells.every(c => c.trim().match(/^:?-+:?$/))) {
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

      if (trimmed.startsWith('# ')) {
        elements.push(
          <h1 key={index} className="text-xl font-extrabold text-[#2e3230] mt-6 mb-3 pb-2 border-b border-[#c4c8bc]/70 flex items-center gap-2">
            <Brain className="h-5 w-5 text-[#705c30]" />
            {parseInlineFormatting(trimmed.replace(/^#\s+/, ''))}
          </h1>
        );
      } else if (trimmed.startsWith('## ')) {
        elements.push(
          <h2 key={index} className="text-lg font-bold text-[#2e3230] mt-5 mb-2.5 pb-1.5 border-b border-[#c4c8bc]/40 flex items-center gap-2">
            <Layers className="h-4.5 w-4.5 text-[#4a7c59]" />
            {parseInlineFormatting(trimmed.replace(/^##\s+/, ''))}
          </h2>
        );
      } else if (trimmed.startsWith('### ')) {
        elements.push(
          <h3 key={index} className="text-base font-bold text-[#705c30] mt-4 mb-2 flex items-center gap-1.5">
            <Sparkles className="h-4 w-4 text-[#705c30]" />
            {parseInlineFormatting(trimmed.replace(/^###\s+/, ''))}
          </h3>
        );
      } else if (trimmed.startsWith('#### ')) {
        elements.push(
          <h4 key={index} className="text-sm font-extrabold text-[#2e3230] mt-3.5 mb-1.5 bg-[#f4efe6]/60 px-2.5 py-1 rounded-md border-l-3 border-[#705c30] flex items-center gap-1.5">
            {parseInlineFormatting(trimmed.replace(/^####\s+/, ''))}
          </h4>
        );
      } else if (trimmed.startsWith('##### ') || trimmed.startsWith('###### ')) {
        elements.push(
          <h5 key={index} className="text-xs font-bold text-[#4a4e4a] mt-3 mb-1">
            {parseInlineFormatting(trimmed.replace(/^#{5,6}\s+/, ''))}
          </h5>
        );
      } else if (trimmed === '---' || trimmed === '***' || trimmed === '___') {
        elements.push(
          <hr key={index} className="my-4 border-t border-[#c4c8bc]/50" />
        );
      } else if (trimmed.startsWith('> ')) {
        elements.push(
          <div key={index} className="my-2.5 border-l-3 border-[#705c30] bg-[#f4efe6]/80 px-3.5 py-2.5 rounded-r-md text-xs leading-relaxed text-[#4a4e4a] font-medium shadow-2xs">
            {parseInlineFormatting(trimmed.replace(/^>\s+/, ''))}
          </div>
        );
      } else if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
        elements.push(
          <li key={index} className="ml-4 list-disc text-sm text-[#2e3230] leading-relaxed my-1">
            {parseInlineFormatting(trimmed.replace(/^[-*]\s+/, ''))}
          </li>
        );
      } else if (trimmed.length > 0) {
        elements.push(
          <p key={index} className="text-sm text-[#2e3230] leading-relaxed my-2.5">
            {parseInlineFormatting(trimmed)}
          </p>
        );
      }
    });

    if (inTable) flushTable(lines.length);
    return elements;
  };

  const themes = data?.memory_json?.themes || [];
  const capitalFlows = data?.memory_json?.capital_flows || [];
  const memoryUnavailable = data?.status && data.status !== 'SUCCESS';
  const panoramaUnavailable = panorama?.status && panorama.status !== 'SUCCESS';
  const legacyCapitalFlows = capitalFlows.length > 0 && !('divergence_sectors' in capitalFlows[0]);
  // 最新阶段在最上面（倒序排列）
  const reversedCapitalFlows = [...capitalFlows].reverse();

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'CURRENT_ACTIVE':
        return <span className="bg-[#b83230]/10 text-[#b83230] border border-[#b83230]/30 px-2.5 py-0.5 rounded text-xs font-extrabold">当前活跃主线</span>;
      case 'RECENTLY_ACTIVE':
        return <span className="bg-[#705c30]/10 text-[#705c30] border border-[#705c30]/30 px-2.5 py-0.5 rounded text-xs font-bold">近期轮动活跃</span>;
      case 'DORMANT_BUT_TRADED':
        return <span className="bg-[#8c9288]/15 text-[#5e635e] border border-[#8c9288]/30 px-2.5 py-0.5 rounded text-xs font-medium">曾经主攻/目前沉寂</span>;
      case 'DECAYED':
        return <span className="bg-[#237a4b]/10 text-[#237a4b] border border-[#237a4b]/30 px-2.5 py-0.5 rounded text-xs font-medium">明显退潮衰减</span>;
      default:
        return <span className="bg-gray-100 text-gray-700 px-2.5 py-0.5 rounded text-xs">{status}</span>;
    }
  };

  const renderSnapshotStatus = (label: string, snapshot: MemoryData | MarketPanoramaData | null) => {
    const status = snapshot?.status || 'PENDING';
    const failed = status === 'FAILED';
    const pending = status === 'PENDING';
    const latest = snapshot?.latest_available_date;
    return (
      <div className={`rounded-xl border p-6 text-center space-y-2 ${failed ? 'border-[#b83230]/40 bg-[#b83230]/5' : 'border-[#d8c6a2] bg-[#f6efe1]'}`}>
        {failed ? <AlertCircle className="mx-auto h-8 w-8 text-[#b83230]" /> : <RefreshCw className={`mx-auto h-8 w-8 text-[#705c30] ${pending ? '' : 'animate-spin'}`} />}
        <h4 className="text-sm font-bold text-[#2e3230]">{tradeDate} 的{label}{failed ? '生成失败' : pending ? '等待自动更新' : '正在生成'}</h4>
        <p className="text-xs leading-relaxed text-[#686d68]">{snapshot?.message || (failed ? '本次结果未写入，历史快照未受影响。' : pending ? '系统将自动继续更新，完成后会显示当前日期的内容。' : '生成完成后会自动显示当前日期的内容。')}</p>
        {latest && <p className="text-xs text-[#686d68]">上一份可用数据：{latest}</p>}
      </div>
    );
  };

  return (
    <div className={inline ? "flex-1 min-h-0 h-full overflow-hidden bg-[#faf8f3]" : "fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4 animate-in fade-in duration-200"}>
      <div className={inline ? "flex h-full min-h-0 flex-col w-full bg-[#faf8f3] overflow-hidden" : "flex flex-col w-full max-w-6xl h-[92vh] rounded-2xl bg-[#faf8f3] border border-[#c4c8bc]/80 shadow-2xl overflow-hidden"}>
        
        <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-4 overscroll-contain">
          {triggering ? (
            <div className="flex flex-col items-center justify-center h-full space-y-3">
              <div className="relative flex items-center justify-center">
                <div className="h-12 w-12 rounded-full border-3 border-[#705c30]/20 border-t-[#705c30] animate-spin" />
                <Brain className="h-6 w-6 text-[#705c30] absolute" />
              </div>
              <p className="text-sm font-bold text-[#2e3230]">正在更新市场全景...</p>
              <p className="text-xs text-[#686d68]">系统正在梳理市场状态、资金偏好、活跃故事与核心观察股</p>
            </div>
          ) : loading ? (
            <div className="flex flex-col items-center justify-center h-full space-y-2">
              <div className="h-8 w-8 rounded-full border-2 border-[#705c30]/20 border-t-[#705c30] animate-spin" />
              <p className="text-xs text-[#686d68]">正在读取市场全景数据...</p>
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center h-full p-6 text-center space-y-3">
              <AlertCircle className="h-10 w-10 text-[#b83230]" />
              <h3 className="text-sm font-bold text-[#2e3230]">市场全景推演提示</h3>
              <p className="text-xs text-[#686d68] max-w-md bg-white p-3 rounded-lg border border-[#c4c8bc]/60 font-mono text-left">
                {error}
              </p>
              <button
                onClick={() => handleTriggerRecompute('panorama')}
                className="px-4 py-2 bg-[#705c30] text-white text-xs font-bold rounded-lg hover:bg-[#5c4a24] transition shadow-xs"
              >
                重新更新全景
              </button>
            </div>
          ) : activeTab === 'markdown' ? (
            <article className="w-full rounded-xl border border-[#c4c8bc]/50 bg-white p-4 sm:p-5 shadow-xs">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-[#eae6de] pb-3">
                <div className="flex flex-wrap items-center gap-3 text-sm font-bold text-[#4a4e4a]">
                  <span className="inline-flex items-center gap-1"><Calendar className="h-4 w-4 text-[#705c30]" />复盘 {panorama?.state?.window?.review_count || 0} 个交易日</span>
                  <span className="inline-flex items-center gap-1"><Activity className="h-4 w-4 text-[#4a7c59]" />重要故事 {panorama?.state?.stories?.length || 0} 个</span>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => handleTriggerRecompute('panorama')} disabled={loading || triggering} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[#705c30]/40 bg-white text-[#705c30] hover:bg-[#705c30]/10 transition disabled:opacity-50" title="更新市场全景"><RefreshCw className={`h-4 w-4 ${triggering ? 'animate-spin' : ''}`} /></button>
                  <button onClick={handleCopyMarkdown} disabled={loading || triggering || !panorama?.summary_markdown} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[#c4c8bc]/60 bg-white text-[#4a4e4a] hover:bg-[#faf8f5] transition disabled:opacity-50" title="复制文章"><>{copied ? <Check className="h-4 w-4 text-[#237a4b]" /> : <Copy className="h-4 w-4" />}</></button>
                  <button onClick={handleDownloadMarkdown} disabled={loading || triggering || !panorama?.summary_markdown} className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-[#4a7c59] text-white hover:bg-[#3d6649] transition disabled:opacity-50" title="导出 Markdown"><Download className="h-4 w-4" /></button>
                </div>
              </div>
              {!panoramaUnavailable && panorama?.summary_markdown ? (
                renderFormattedMarkdown(panorama.summary_markdown)
              ) : panoramaUnavailable ? (
                renderSnapshotStatus('市场全景', panorama)
              ) : (
                <div className="rounded-xl border border-[#c4c8bc]/60 bg-white p-8 text-center space-y-3 max-w-md mx-auto my-6">
                  <Brain className="h-10 w-10 text-[#705c30]/50 mx-auto" />
                  <h4 className="text-sm font-bold text-[#2e3230]">该日期尚未生成市场全景</h4>
                  <p className="text-xs text-[#686d68] leading-relaxed">
                    系统尚未推演该日期的市场全景深度纪实与资金脉络。点击下方按钮即可由 AI 自动推演生成。
                  </p>
                  <button
                    onClick={() => handleTriggerRecompute('panorama')}
                    className="px-4 py-2 bg-[#705c30] text-white text-xs font-bold rounded-lg hover:bg-[#5c4a24] transition shadow-xs inline-flex items-center gap-1.5"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    立即生成市场全景
                  </button>
                </div>
              )}
            </article>
          ) : activeTab === 'themes' ? (
            memoryUnavailable ? renderSnapshotStatus('题材周期', data) : <div className="w-full space-y-4">
              {data?.memory_json?.binding_warnings && data.memory_json.binding_warnings.length > 0 && (
                <div className="rounded-xl border border-[#d8c6a2] bg-[#f6efe1] px-4 py-3 text-xs leading-6 text-[#705c30]">
                  部分产业主体未能绑定 A 股证券代码，已保留为不可交易主体；相关名称不提供 K 线入口。
                </div>
              )}
              {themes.length > 0 && themes.some((theme) => !theme.phases) && (
                <div className="rounded-xl border border-[#d8c6a2] bg-[#f6efe1] px-4 py-3 text-xs text-[#705c30]">
                  当前日期的题材周期还是旧版摘要，尚未包含阶段时间线与核心股票。点击右上角「更新全景」后，会按历史复盘重建这部分内容。
                </div>
              )}
              <div className="flex items-start gap-4">
                <aside className="sticky top-0 hidden max-h-[calc(100vh-12rem)] w-44 shrink-0 overflow-y-auto overscroll-contain border-r border-[#c4c8bc]/60 pr-3 lg:block">
                  <nav className="space-y-1" aria-label="题材周期导航">
                    {themes.map((theme, idx) => (
                      <button
                        key={`${theme.canonical_name}-${idx}`}
                        type="button"
                        onClick={() => document.getElementById(`theme-cycle-${idx}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                        className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-2 text-left text-sm font-bold text-[#4a4e4a] transition hover:bg-[#705c30]/10 hover:text-[#705c30]"
                        title={`定位到${theme.canonical_name}`}
                      >
                        <span className="truncate">{theme.canonical_name}</span>
                        <span className="shrink-0 font-mono text-xs text-[#8c9288]">{theme.phases?.length || 0}</span>
                      </button>
                    ))}
                  </nav>
                </aside>
                <div className="min-w-0 flex-1 space-y-4">
                {themes.map((theme, idx) => (
                  <section id={`theme-cycle-${idx}`} key={idx} className="scroll-mt-4 rounded-xl border border-[#c4c8bc]/60 bg-white p-5 shadow-2xs space-y-3">
                    <div className="flex items-start justify-between">
                      <div>
                        <h4 className="text-base font-extrabold text-[#2e3230]">{theme.canonical_name}</h4>
                        {theme.parent_theme && (
                          <span className="text-xs text-[#686d68] block mt-0.5">
                            母题归属: {theme.parent_theme}
                          </span>
                        )}
                      </div>
                      {getStatusBadge(theme.status)}
                    </div>

                    {theme.aliases && theme.aliases.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {theme.aliases.map((a, aIdx) => (
                          <span key={aIdx} className="px-2 py-0.5 rounded bg-[#f0ece4] text-xs text-[#4a4e4a]">
                            {a}
                          </span>
                        ))}
                      </div>
                    )}

                    <div className="rounded-lg border border-[#eae6de] bg-[#faf8f5] p-3">
                      <div className="mb-2 text-xs font-extrabold text-[#705c30]">主题演化概括</div>
                      {renderEvolutionSummary(theme.evolution_summary, `theme-${idx}-summary`)}
                    </div>

                    {theme.phases && theme.phases.length > 0 && (
                      <div className="border-t border-[#eae6de] pt-3 space-y-2">
                        <div className="text-sm font-extrabold text-[#705c30]">阶段演化与核心股票</div>
                        <div className="space-y-2">
                          {theme.phases.map((phase, phaseIdx) => (
                            <div key={`${phase.time_range}-${phaseIdx}`} className="rounded-lg border border-[#eae6de] bg-[#faf8f5] p-2.5">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className="rounded bg-[#705c30]/10 px-2 py-0.5 font-mono text-xs font-bold text-[#705c30]">{phase.time_range}</span>
                                <span className="text-sm font-extrabold text-[#2e3230]">{phase.stage_name}</span>
                              </div>
                              <div className="mt-1.5 space-y-1">
                                {splitReadableParagraphs(phase.description).map((paragraph, paragraphIdx) => (
                                  <p key={`${phase.time_range}-${phaseIdx}-description-${paragraphIdx}`} className="text-sm leading-7 text-[#4a4e4a]">{paragraph}</p>
                                ))}
                              </div>
                              {phase.core_stocks.length > 0 && (
                                <div className="mt-2 flex flex-wrap gap-1.5">
                                  {phase.core_stocks.map((stock, stockIdx) => {
                                    const pctChg = typeof stock.pct_chg === 'number' ? stock.pct_chg : null;
                                    const quoteTone = pctChg === null
                                      ? 'border-[#c4c8bc]/60 bg-[#f0ece4] text-[#4a4e4a] hover:bg-[#eae6de]'
                                      : pctChg > 0
                                        ? 'border-[#b83230]/25 bg-[#b83230]/10 text-[#b83230] hover:bg-[#b83230]/20'
                                        : pctChg < 0
                                          ? 'border-[#237a4b]/25 bg-[#237a4b]/10 text-[#237a4b] hover:bg-[#237a4b]/20'
                                          : 'border-[#705c30]/25 bg-[#705c30]/10 text-[#705c30] hover:bg-[#705c30]/20';
                                    const pctLabel = pctChg === null ? '行情缺失' : `${pctChg > 0 ? '+' : ''}${pctChg.toFixed(2)}%`;
                                    return (
                                      <button
                                        key={`${stock.ts_code}-${stockIdx}`}
                                        type="button"
                                        onClick={() => stock.ts_code && onOpenKline?.({ code: stock.ts_code, name: stock.name })}
                                        disabled={!onOpenKline || !stock.ts_code}
                                        className={`rounded border px-2 py-1 text-sm font-bold transition disabled:cursor-default disabled:opacity-100 ${quoteTone}`}
                                        title={stock.ts_code && onOpenKline ? `查看${stock.name} K线；${stock.quote_date || phase.time_range} 涨跌 ${pctLabel}` : `${stock.name}（非可交易证券）`}
                                      >
                                        {stock.name} {stock.ts_code && <span className="font-mono text-xs font-medium">{stock.ts_code}</span>}{' '}
                                        <span className="font-mono text-xs font-bold">{pctLabel}</span>
                                      </button>
                                    );
                                  })}
                                </div>
                              )}
                              {phase.non_security_entities && phase.non_security_entities.length > 0 && (
                                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-sm text-[#686d68]">
                                  <span className="font-bold">产业主体：</span>
                                  {phase.non_security_entities.map((entity, entityIdx) => (
                                    <span
                                      key={`${entity.name}-${entityIdx}`}
                                      className="rounded border border-[#c4c8bc]/60 bg-[#f0ece4] px-2 py-1"
                                      title={entity.reason}
                                    >
                                      {entity.name}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="flex items-center justify-between text-xs text-[#686d68] pt-1 border-t border-[#eae6de]">
                      <span>首见: {theme.first_seen_date || '-'}</span>
                      <span>活跃: {theme.last_active_date || '-'}</span>
                    </div>
                  </section>
                ))}
                </div>
              </div>
            </div>
          ) : (
            /* 资金脉络卡片流 */
            memoryUnavailable ? renderSnapshotStatus('资金脉络', data) : <div className="w-full space-y-4">
              {legacyCapitalFlows && (
                <div className="rounded-xl border border-[#d8c6a2] bg-[#f6efe1] px-4 py-3 flex items-center justify-between gap-3">
                  <p className="text-xs text-[#705c30]">当前资金脉络是旧版缓存，只记录主攻方向；更新全景后会补充分歧与流出方向。</p>
                  <button
                    onClick={() => handleTriggerRecompute('legacy')}
                    disabled={triggering}
                    className="shrink-0 px-3 py-1.5 bg-[#705c30] text-white text-xs font-bold rounded-lg disabled:opacity-50"
                  >
                    {triggering ? '更新中…' : '更新全景'}
                  </button>
                </div>
              )}
              {reversedCapitalFlows.length > 0 ? (
                <div className="relative border-l-2 border-[#705c30]/30 ml-4 pl-6 space-y-6">
                  {reversedCapitalFlows.map((flow, idx) => (
                    <div key={idx} className="relative group">
                      {/* Timeline dot */}
                      <div className="absolute -left-[31px] top-1 h-3.5 w-3.5 rounded-full border-2 border-[#705c30] bg-[#faf8f3]" />

                      <div className="rounded-xl border border-[#c4c8bc]/70 bg-white p-4 shadow-2xs space-y-2.5 hover:shadow-xs transition">
                        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#eae6de] pb-2">
                          <div className="flex items-center gap-2">
                            <span className="px-2.5 py-1 rounded bg-[#705c30]/10 text-[#705c30] font-mono text-sm font-bold">
                              {flow.time_range}
                            </span>
                            <h4 className="text-base font-extrabold text-[#2e3230]">
                              {flow.stage_name}
                            </h4>
                          </div>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                          <div className="space-y-1">
                            <span className="text-xs font-bold text-[#686d68]">主攻方向</span>
                            <div className="flex flex-wrap gap-1">
                              {flow.main_sectors.map((s, sIdx) => (
                                <span key={sIdx} className="px-2.5 py-1 rounded bg-[#f0ece4] text-[#2e3230] font-medium text-sm">
                                  {s}
                                </span>
                              ))}
                            </div>
                          </div>

                          <div className="space-y-1">
                            <span className="text-xs font-bold text-[#686d68]">核心领涨标的</span>
                            <div className="flex flex-wrap gap-1">
                              {renderCapitalFlowStocks(flow.core_stocks, 'px-2.5 py-1 rounded bg-[#b83230]/10 text-[#b83230] font-bold text-sm border border-[#b83230]/20')}
                            </div>
                          </div>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm border-t border-[#eae6de] pt-3">
                          <div className="space-y-1">
                            <span className="text-xs font-bold text-[#705c30]">分歧 / 强弱分化</span>
                            <div className="flex flex-wrap gap-1">
                              {(flow.divergence_sectors || []).length > 0 ? flow.divergence_sectors!.map((sector, sectorIdx) => (
                                <span key={sectorIdx} className="px-2.5 py-1 rounded bg-[#f6efe1] text-[#705c30] font-medium text-sm border border-[#d8c6a2]">
                                  {sector}
                                </span>
                              )) : <span className="text-sm text-[#8c9288]">本阶段未记录</span>}
                            </div>
                            {(flow.divergence_stocks || []).length > 0 && (
                              <div className="flex flex-wrap items-center gap-1 text-sm text-[#686d68]">
                                <span>代表股：</span>
                                {renderCapitalFlowStocks(flow.divergence_stocks!, 'font-medium text-[#705c30] hover:underline', true)}
                              </div>
                            )}
                          </div>

                          <div className="space-y-1">
                            <span className="text-xs font-bold text-[#237a4b]">流出 / 退潮方向</span>
                            <div className="flex flex-wrap gap-1">
                              {(flow.outflow_sectors || []).length > 0 ? flow.outflow_sectors!.map((sector, sectorIdx) => (
                                <span key={sectorIdx} className="px-2.5 py-1 rounded bg-[#edf4ef] text-[#237a4b] font-medium text-sm border border-[#b9d4c0]">
                                  {sector}
                                </span>
                              )) : <span className="text-sm text-[#8c9288]">本阶段未记录</span>}
                            </div>
                            {(flow.outflow_stocks || []).length > 0 && (
                              <div className="flex flex-wrap items-center gap-1 text-sm text-[#686d68]">
                                <span>代表股：</span>
                                {renderCapitalFlowStocks(flow.outflow_stocks!, 'font-medium text-[#237a4b] hover:underline', true)}
                              </div>
                            )}
                          </div>
                        </div>

                        <div className="rounded-lg border border-[#eae6de] bg-[#faf8f5] p-3">
                          <div className="mb-2 text-xs font-extrabold text-[#705c30]">资金演化说明</div>
                          {renderEvolutionSummary(flow.flow_description, `capital-flow-${idx}-description`)}
                        </div>

                        {flow.transition_trigger && (
                          <div className="flex items-start gap-1.5 text-sm leading-7 text-[#705c30] pt-1">
                            <AlertCircle className="h-3 w-3" />
                            <span><strong>转折动因:</strong> {splitReadableParagraphs(flow.transition_trigger).join(' ')}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-xl border border-[#c4c8bc]/60 bg-white p-8 text-center space-y-3">
                  <Workflow className="h-10 w-10 text-[#705c30]/50 mx-auto" />
                  <h4 className="text-sm font-bold text-[#2e3230]">暂无结构化资金脉络数据</h4>
                  <p className="text-xs text-[#686d68]">点击右上角【更新全景】，系统将自动梳理近 30~120 日资金主线迁移路径</p>
                  <button
                    onClick={() => handleTriggerRecompute('legacy')}
                    className="px-4 py-2 bg-[#705c30] text-white text-xs font-bold rounded-lg hover:bg-[#5c4a24] transition shadow-xs"
                  >
                    更新全景并生成资金脉络
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
