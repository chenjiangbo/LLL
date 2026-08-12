'use client';

import React, { useState } from 'react';
import { Sparkles, CheckCircle2, TrendingUp, Layers, BookOpen, Clock, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';

export type ImportedPayload = {
  trade_date: string;
  title: string;
  headline: string;
  executive_summary?: string;
  core_conclusions: string[];
  deep_logic_analysis?: Array<{
    topic: string;
    reasoning: string;
  }>;
  market_metrics: Array<{
    name: string;
    value: string;
    change: string;
  }>;
  intraday_trend: string;
  multi_day_context: Array<{
    stage_name: string;
    description: string;
  }>;
  leading_sectors: Array<{
    sector_name: string;
    trend_type: string;
    detail: string;
  }>;
  key_takeaways: string[];
  full_markdown: string;
};

interface ImportedDashboardProps {
  tradeDate: string;
  payload: ImportedPayload;
  rawContent?: string;
}

export default function ImportedDashboard({ tradeDate, payload, rawContent }: ImportedDashboardProps) {
  const [showRaw, setShowRaw] = useState(false);

  const getChangeTone = (changeStr: string) => {
    if (changeStr.includes('+') || changeStr.includes('增加') || changeStr.includes('大涨') || changeStr.includes('涨停')) {
      return 'text-[#b83230] bg-[#b83230]/10 border-[#b83230]/30';
    }
    if (changeStr.includes('-') || changeStr.includes('减少') || changeStr.includes('下跌') || changeStr.includes('跌停')) {
      return 'text-[#237a4b] bg-[#237a4b]/10 border-[#237a4b]/30';
    }
    return 'text-[#4a4e4a] bg-[#eae6de] border-[#c4c8bc]/40';
  };

  const getTrendTagTone = (trendType: string) => {
    if (trendType.includes('核心') || trendType.includes('主线') || trendType.includes('领涨')) {
      return 'bg-[#b83230]/10 text-[#b83230] border-[#b83230]/30';
    }
    if (trendType.includes('切换') || trendType.includes('扩散') || trendType.includes('接力')) {
      return 'bg-[#705c30]/10 text-[#705c30] border-[#705c30]/30';
    }
    if (trendType.includes('分歧') || trendType.includes('筛选') || trendType.includes('消化')) {
      return 'bg-[#237a4b]/10 text-[#237a4b] border-[#237a4b]/30';
    }
    return 'bg-[#4a7c59]/10 text-[#4a7c59] border-[#4a7c59]/30';
  };

  return (
    <div className="px-4 py-8 sm:px-6 lg:px-8 space-y-8">
      {/* 1. Header Overview Card (Executive Summary 看板) */}
      <section className="rounded-xl border border-[#c4c8bc]/40 bg-[#f0ece4] p-6 shadow-sm md:p-8 space-y-6">
        {/* Top Title & Tag Bar */}
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#c4c8bc]/30 pb-4">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[#4a7c59] px-3 py-0.5 text-xs font-bold text-white shadow-xs">
                <Sparkles className="h-3.5 w-3.5" />
                AI 智能速览复盘
              </span>
              <span className="text-xs font-bold text-[#686d68] bg-[#eae6de] px-2.5 py-0.5 rounded-md border border-[#c4c8bc]/40">
                交易日期：{payload.trade_date || tradeDate}
              </span>
            </div>
            <h1 className="font-[family-name:var(--font-literata)] text-2xl font-extrabold text-[#2e3230] md:text-3xl">
              {payload.title || '每日复盘文章'}
            </h1>
          </div>

          {/* Quick metrics row in header */}
          {payload.market_metrics && payload.market_metrics.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              {payload.market_metrics.slice(0, 4).map((m, idx) => (
                <div key={idx} className="flex items-center gap-1.5 rounded-lg border border-[#c4c8bc]/40 bg-white/80 px-3 py-1.5 text-xs shadow-2xs">
                  <span className="font-semibold text-[#686d68]">{m.name}:</span>
                  <span className="font-bold text-[#2e3230]">{m.value}</span>
                  {m.change && (
                    <span className={`font-bold px-1 rounded ${getChangeTone(m.change)}`}>
                      {m.change}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 核心盘面全貌通俗看盘 (Executive Narrative Summary) */}
        <div className="rounded-xl border border-[#e2d5bd] bg-[#fbf7ee] p-5 sm:p-6 shadow-xs">
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#4a7c59]/10 text-lg">
              💡
            </span>
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-wider text-[#705c30]">
                  今日盘面全貌速览（通俗带数据版）
                </span>
                <span className="text-[11px] font-medium text-[#4a7c59] bg-[#4a7c59]/10 px-2 py-0.5 rounded-md">
                  一秒抓全貌
                </span>
              </div>
              <p className="font-[family-name:var(--font-literata)] text-base sm:text-lg font-semibold leading-relaxed text-[#2e3230]">
                {payload.executive_summary || payload.headline}
              </p>
            </div>
          </div>
        </div>

        {/* 核心结论要点 (High-density Grid for Quick Reading) */}
        <div className="rounded-xl border border-[#c4c8bc]/50 bg-white/90 p-5 sm:p-6 shadow-xs">
          <div className="mb-4 flex items-center justify-between border-b border-[#eae6de] pb-3">
            <h2 className="flex items-center gap-2 text-sm font-extrabold text-[#2e3230]">
              <CheckCircle2 className="h-4 w-4 text-[#4a7c59]" />
              核心看点要点（带关键定量数据）
            </h2>
            <span className="text-xs font-medium text-[#705c30] bg-[#705c30]/10 px-2 py-0.5 rounded">
              核心要点提炼
            </span>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {payload.core_conclusions?.map((point, index) => (
              <div 
                key={index} 
                className="flex items-start gap-3 rounded-lg border border-[#c4c8bc]/30 bg-[#faf6f0] p-3.5 transition-all hover:bg-white hover:shadow-xs hover:border-[#4a7c59]/40"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#4a7c59] text-xs font-bold text-white shadow-2xs">
                  {index + 1}
                </span>
                <p className="text-sm font-semibold leading-relaxed text-[#2e3230]">
                  {point}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 1.5 深度驱动与因果归因剖析 (Deep Logical Attribution Section) */}
      {payload.deep_logic_analysis && payload.deep_logic_analysis.length > 0 && (
        <section className="rounded-xl border border-[#705c30]/30 bg-[#f7f3ea] p-6 shadow-xs space-y-4">
          <div className="flex items-center justify-between border-b border-[#e2d5bd] pb-3">
            <h2 className="flex items-center gap-2 text-sm font-extrabold text-[#2e3230]">
              <Layers className="h-4.5 w-4.5 text-[#705c30]" />
              深度驱动逻辑与因果剖析 (Deep Drivers)
            </h2>
            <span className="text-xs font-bold text-[#705c30] bg-[#705c30]/15 px-2.5 py-0.5 rounded-full">
              复盘深层因果
            </span>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {payload.deep_logic_analysis.map((item, idx) => (
              <div 
                key={idx} 
                className="rounded-lg border border-[#e2d5bd] bg-white p-5 shadow-xs space-y-2 hover:border-[#705c30]/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-[#705c30]" />
                  <h3 className="text-xs sm:text-sm font-extrabold text-[#705c30]">
                    {item.topic}
                  </h3>
                </div>
                <p className="text-xs sm:text-sm font-normal leading-relaxed text-[#2e3230] bg-[#faf8f3] p-3 rounded-md border border-[#c4c8bc]/30">
                  {item.reasoning}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 2. Key Market Metrics Card */}
      {payload.market_metrics && payload.market_metrics.length > 0 && (
        <section className="rounded-xl border border-[#c4c8bc]/40 bg-white/60 p-6 shadow-xs">
          <h2 className="mb-4 flex items-center gap-2 text-sm font-bold text-[#2e3230]">
            <TrendingUp className="h-4 w-4 text-[#4a7c59]" />
            核心市场行情与指标
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {payload.market_metrics.map((metric, idx) => (
              <div key={idx} className="rounded-lg border border-[#c4c8bc]/40 bg-[#faf6f0] p-4 flex flex-col justify-between">
                <span className="text-xs font-bold text-[#686d68]">{metric.name}</span>
                <div className="mt-2 flex items-baseline justify-between">
                  <span className="text-lg font-extrabold text-[#2e3230]">{metric.value}</span>
                  {metric.change && (
                    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-bold ${getChangeTone(metric.change)}`}>
                      {metric.change}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 3. Intraday Trend & Multi-Day Evolution */}
      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-[#c4c8bc]/40 bg-white/60 p-6 shadow-xs">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-[#2e3230]">
            <Clock className="h-4 w-4 text-[#4a7c59]" />
            盘中走势及阶段表现
          </h2>
          <p className="text-xs font-normal leading-relaxed text-[#4a4e4a] whitespace-pre-line bg-[#faf6f0] p-4 rounded-lg border border-[#c4c8bc]/30">
            {payload.intraday_trend}
          </p>
        </div>

        <div className="rounded-xl border border-[#c4c8bc]/40 bg-white/60 p-6 shadow-xs">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-[#2e3230]">
            <Layers className="h-4 w-4 text-[#4a7c59]" />
            多日演化脉络与连贯结构
          </h2>
          <div className="space-y-3">
            {payload.multi_day_context?.map((stage, idx) => (
              <div key={idx} className="relative pl-5 border-l-2 border-[#4a7c59]/40 pb-1">
                <span className="absolute -left-[5px] top-1.5 h-2 w-2 rounded-full bg-[#4a7c59]" />
                <span className="text-xs font-bold text-[#2e3230] block">{stage.stage_name}</span>
                <p className="text-xs text-[#686d68] mt-0.5">{stage.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 4. Leading Sectors Section */}
      {payload.leading_sectors && payload.leading_sectors.length > 0 && (
        <section className="rounded-xl border border-[#c4c8bc]/40 bg-white/60 p-6 shadow-xs">
          <h2 className="mb-4 flex items-center gap-2 text-sm font-bold text-[#2e3230]">
            <Sparkles className="h-4 w-4 text-[#705c30]" />
            领涨主线与板块热点分析
          </h2>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {payload.leading_sectors.map((sec, idx) => (
              <div key={idx} className="rounded-lg border border-[#c4c8bc]/40 bg-[#faf6f0] p-4">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-bold text-[#2e3230]">{sec.sector_name}</h3>
                  <span className={`rounded-md border px-2 py-0.5 text-[11px] font-bold ${getTrendTagTone(sec.trend_type)}`}>
                    {sec.trend_type}
                  </span>
                </div>
                <p className="text-xs leading-relaxed text-[#4a4e4a]">{sec.detail}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 5. Key Takeaways Section */}
      {payload.key_takeaways && payload.key_takeaways.length > 0 && (
        <section className="rounded-xl border border-[#c4c8bc]/40 bg-[#f4f0e8] p-6">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-[#2e3230]">
            <AlertCircle className="h-4 w-4 text-[#705c30]" />
            核心策略启示与观察要点
          </h2>
          <ul className="grid gap-2.5 md:grid-cols-2 text-xs text-[#4a4e4a]">
            {payload.key_takeaways.map((item, idx) => (
              <li key={idx} className="flex gap-2 rounded-md bg-white/60 p-3 border border-[#c4c8bc]/30">
                <span className="font-bold text-[#4a7c59] shrink-0">#{idx + 1}</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 6. Raw Content View Toggle */}
      <section className="rounded-xl border border-[#c4c8bc]/40 bg-white/60 p-6 shadow-xs">
        <button
          onClick={() => setShowRaw(!showRaw)}
          className="flex w-full items-center justify-between rounded-lg bg-[#faf6f0] px-4 py-3 text-xs font-bold text-[#2e3230] hover:bg-[#f0ece4]"
        >
          <div className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-[#4a7c59]" />
            <span>{showRaw ? '隐藏导入文章 Markdown 原文' : '查看导入文章 Markdown 原文'}</span>
          </div>
          {showRaw ? <ChevronUp className="h-4 w-4 text-[#686d68]" /> : <ChevronDown className="h-4 w-4 text-[#686d68]" />}
        </button>

        {showRaw && (
          <div className="mt-4 rounded-lg bg-[#fcfbfa] p-5 border border-[#c4c8bc]/40">
            <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-[#2e3230]">
              {rawContent || payload.full_markdown}
            </pre>
          </div>
        )}
      </section>
    </div>
  );
}
