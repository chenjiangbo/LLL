'use client';

import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import {
  PlayCircle,
  Search,
  Calendar,
  Sparkles,
  Target,
  Activity,
  AlertTriangle,
  Loader2,
  TrendingUp,
  BarChart2,
  Layers,
  ChevronRight,
  Filter,
  Info,
  ChevronDown,
  ChevronUp,
  Download,
} from 'lucide-react';
import { init, dispose, Chart } from 'klinecharts';
import { downloadSingleStockMarkdown } from './singleStockMarkdown';
import { preQualificationText, type PreQualification, type RoundedRepair } from './preQualification';
import { doubleBottomLabel } from './doubleBottomLabel';

interface SingleStockHistoryItem {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number;
  amount: number;
  total_score: number;
  score_type?: 'PREP_SCORE' | 'TURN_SCORE' | 'NONE';
  prep_score?: number;
  turn_score?: number;
  state: string;
  selected?: boolean;
  is_overextended?: boolean;
  turn_episode_state?: string;
  pre_qualification?: PreQualification | null;
  rounded_repair?: RoundedRepair | null;
  pre_entry_reason?: string | null;
  pre_confirm_date?: string | null;
  early_observation?: { active: boolean; first_date?: string; ma5?: number; ma10?: number; ma5_slope_3d?: number; ma10_slope_5d?: number; retake_count?: number } | null;
  second_opportunity?: { active: boolean; types: string[] } | null;
  signal_status?: string;
  entry_extension_state?: string;
  first_trigger_date?: string;
  first_trigger_close?: number;
  return_since_first_trigger?: number;
  structural_damage_flag?: boolean;
  retake_count?: number | null;
  episode_base_low?: number | null;
  episode_base_low_date?: string | null;
  first_wave_high_close?: number | null;
  first_wave_high_date?: string | null;
  first_wave_gain?: number | null;
  first_wave_gain_atr?: number | null;
  first_wave_formed?: boolean;
  first_wave_formation_bars?: number | null;
  first_wave_speed?: 'FAST' | 'NORMAL' | null;
  drawdown_from_first_wave_high?: number | null;
  bottom_structure_type?: string;
  bottom_structure_quality?: 'NONE' | 'POSSIBLE' | 'CLEAR';
  bottom_structure_strength?: number;
  bottom_first_low_date?: string | null;
  bottom_second_low_date?: string | null;
  bottom_structure_confirmed_date?: string | null;
  bottom_first_low?: number | null;
  bottom_middle_high?: number | null;
  bottom_second_low?: number | null;
  bottom_low_gap_bars?: number | null;
  background_type: string;
  score_detail_json: Record<string, any>;
  reasons_json: Array<{ type: string; msg: string }>;
}

interface SingleStockKLineCandle {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number;
  amount: number;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma30: number | null;
  ma60: number | null;
}

interface SingleStockEvalResult {
  ts_code: string;
  name: string;
  industry: string;
  strategy_id: string;
  start_date: string;
  end_date: string;
  history: SingleStockHistoryItem[];
  klines: SingleStockKLineCandle[];
}

/**
 * 单股测试接口返回的是日线（评分与导出也必须继续使用日线）。
 * K 线图切换到周线时，不能只修改 klinecharts 的 period：setPeriod
 * 不会替我们把通过 dataLoader 注入的日线数组重新聚合。因此在展示层
 * 明确按交易周聚合，避免周线按钮看起来与日线完全相同。
 */
const aggregateWeeklyKlines = (daily: SingleStockKLineCandle[]): SingleStockKLineCandle[] => {
  const groups = new Map<string, SingleStockKLineCandle[]>();
  daily.forEach((item) => {
    const date = String(item.trade_date || '');
    if (date.length !== 8) return;
    const d = new Date(Date.UTC(Number(date.slice(0, 4)), Number(date.slice(4, 6)) - 1, Number(date.slice(6, 8))));
    if (Number.isNaN(d.getTime())) return;
    // ISO 周一作为分组键；接口数据按交易日升序，组内顺序因此稳定。
    const day = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() - day + 1);
    const key = d.toISOString().slice(0, 10);
    const bucket = groups.get(key);
    if (bucket) bucket.push(item);
    else groups.set(key, [item]);
  });

  return Array.from(groups.values()).map((items) => {
    const first = items[0];
    const last = items[items.length - 1];
    return {
      trade_date: last.trade_date,
      open: first.open,
      high: Math.max(...items.map((item) => item.high)),
      low: Math.min(...items.map((item) => item.low)),
      close: last.close,
      vol: items.reduce((sum, item) => sum + item.vol, 0),
      amount: items.reduce((sum, item) => sum + item.amount, 0),
      // 图表会根据周线收盘价重新计算 MA；这里不沿用日线 MA，避免语义混淆。
      ma5: null,
      ma10: null,
      ma20: null,
      ma30: null,
      ma60: null,
    };
  });
};

const getApiBase = (): string => {
  if (process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL) {
    return process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;
  }
  if (typeof window !== 'undefined' && window.location?.hostname) {
    return `${window.location.protocol}//${window.location.hostname}:18080`;
  }
  return 'http://127.0.0.1:18080';
};

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

const STRATEGIES = [
  { id: 'A_PRE_V2', name: '🧪 A-Pre V2 早期转强实验', desc: '基于均线高度压缩、结扎交叉、次序重排与新鲜度的早期爆发转强模型' },
];

const DEFAULT_MA_ITEMS = [
  { day: 5, color: '#ec4899' },
  { day: 10, color: '#f59e0b' },
  { day: 30, color: '#3b82f6' },
  { day: 60, color: '#8b5cf6' },
];

// 根据状态获取颜色与标签
function getStateColor(state: string): { bg: string; text: string; label: string } {
  switch (state) {
    case 'FIRST_TURN_WINDOW':
      return { bg: '#4a7c59', text: '#ffffff', label: '首次转强' };
    case 'POST_FIRST_WAVE':
      return { bg: '#aa1c4a', text: '#ffffff', label: '第一波已完成' };
    case 'PRE_FIRST_TURN':
      return { bg: '#334155', text: '#ffffff', label: '底部准备中' };
    case 'OUTSIDE_A_PRE':
      return { bg: '#94a3b8', text: '#ffffff', label: '未进入底部准备' };
    default:
      return { bg: '#94a3b8', text: '#ffffff', label: '无信号' };
  }
}

// 尚未进入生命周期时展示准备度诊断，但不把它当作正式选股得分。
function displayScore(item: SingleStockHistoryItem): number | null {
  const value = item.prep_score;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

const getTodayDateStr = (): string => {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
};

const getOneMonthAgoDateStr = (): string => {
  const d = new Date();
  d.setMonth(d.getMonth() - 1);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
};

export default function SingleStockTestView() {
  const [strategyId, setStrategyId] = useState<string>('A_PRE_V2');
  const [stockInput, setStockInput] = useState<string>('');
  const [startDate, setStartDate] = useState<string>(getOneMonthAgoDateStr());
  const [endDate, setEndDate] = useState<string>(getTodayDateStr());
  
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SingleStockEvalResult | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [hoveredDate, setHoveredDate] = useState<string | null>(null);
  const [extraHistoryItem, setExtraHistoryItem] = useState<SingleStockHistoryItem | null>(null);
  const [hoverError, setHoverError] = useState<string | null>(null);
  const extraHistoryCacheRef = useRef<Map<string, SingleStockHistoryItem>>(new Map());
  const [showBreakdownTable, setShowBreakdownTable] = useState<boolean>(true);
  const [period, setPeriod] = useState<'day' | 'week'>('day');

  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<Chart | null>(null);

  // 避免图表提示重复触发同一日期的状态更新。
  const lastHoverDateRef = useRef<string>('');

  const handleHoverDate = useCallback((tradeDate: string) => {
    if (lastHoverDateRef.current === tradeDate) return;
    lastHoverDateRef.current = tradeDate;
    setHoveredDate(tradeDate);
  }, []);

  const onHoverDateRef = useRef(handleHoverDate);
  useEffect(() => {
    onHoverDateRef.current = handleHoverDate;
  }, [handleHoverDate]);

  // 导出拆解表为 Markdown 文档（与选股列表“单股数据”共用同一实现）
  const handleExportMarkdown = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (!result || !result.history || result.history.length === 0) return;
    downloadSingleStockMarkdown(result);
  }, [result]);

  // 执行单股多日策略测试
  const handleRunEval = useCallback(async (codeOverride?: string) => {
    const targetCode = codeOverride || stockInput;
    if (!targetCode.trim()) return;

    setLoading(true);
    setError(null);
    try {
      const sDate = startDate.replace(/-/g, '');
      const eDate = endDate.replace(/-/g, '');

      const params = new URLSearchParams({
        strategy_id: strategyId,
        ts_code: targetCode.trim(),
        start_date: sDate,
        end_date: eDate,
      });

      const baseUrl = getApiBase();
      const res = await safeFetch(`${baseUrl}/api/strategy/single-stock/eval?${params.toString()}`);
      if (!res || !res.ok) {
        let detail = `单股测试接口异常（HTTP ${res?.status || 'Network Error'}）`;
        if (res) {
          try {
            const body = await res.json();
            if (typeof body?.detail === 'string') detail = body.detail;
          } catch (_) {
            // 保留上面的明确 HTTP 错误，不静默吞掉失败。
          }
        }
        throw new Error(detail);
      }

      const json: SingleStockEvalResult = await res.json();
      if (!json.history || json.history.length === 0) {
        throw new Error(`${targetCode.trim()} 在 ${startDate} 至 ${endDate} 没有可评估的日线数据`);
      }
      extraHistoryCacheRef.current.clear();
      lastHoverDateRef.current = '';
      setHoveredDate(null);
      setExtraHistoryItem(null);
      setHoverError(null);
      setResult(json);
      setSelectedDate(json.history[json.history.length - 1].trade_date);
    } catch (e) {
      console.warn('Failed to run single stock eval:', e);
      setError(e instanceof Error ? e.message : '单股测试失败');
    } finally {
      setLoading(false);
    }
  }, [stockInput, startDate, endDate, strategyId]);

  // 渲染 K 线图
  useEffect(() => {
    if (!result || !result.klines || result.klines.length === 0 || !chartRef.current) return;

    // 建立历史得分索引 Map
    const hMap = new Map<string, SingleStockHistoryItem>();
    result.history.forEach((h) => hMap.set(h.trade_date, h));

    if (chartInstanceRef.current) {
      dispose(chartRef.current);
      chartInstanceRef.current = null;
    }

    const chart = init(chartRef.current, {
      styles: {
        grid: {
          show: true,
          horizontal: { color: '#e2e8f0', style: 'dashed' },
          vertical: { color: '#e2e8f0', style: 'dashed' },
        },
        candle: {
          bar: {
            upColor: '#ef4444',
            downColor: '#10b981',
            noChangeColor: '#6b7280',
            upBorderColor: '#ef4444',
            downBorderColor: '#10b981',
            noChangeBorderColor: '#6b7280',
            upWickColor: '#ef4444',
            downWickColor: '#10b981',
            noChangeWickColor: '#6b7280',
          },
          tooltip: {
            showRule: 'always',
            showType: 'standard',
            title: {
              show: false,
            },
            legend: {
              template: (neighborData: any) => {
                const current = neighborData.current;
                if (!current) return [];

                // 官方触发机制: 当鼠标十字光标移动时，template 必定会被 klinecharts 实时调用
                const rawDate = String(current.trade_date || '');
                if (rawDate && onHoverDateRef.current) {
                  onHoverDateRef.current(rawDate);
                }

                const prev = neighborData.prev;
                const currentClose = typeof current.close === 'number' ? current.close : 0;
                const prevClose = prev && typeof prev.close === 'number' ? prev.close : (typeof current.open === 'number' ? current.open : currentClose);

                let changePct = 0;
                if (prevClose > 0) {
                  changePct = ((currentClose - prevClose) / prevClose) * 100;
                }

                const changePctStr = `${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%`;
                const changeColor = changePct > 0 ? '#ef4444' : changePct < 0 ? '#10b981' : '#6b7280';

                const dateStr = rawDate.length === 8 ? `${rawDate.slice(0, 4)}-${rawDate.slice(4, 6)}-${rawDate.slice(6)}` : rawDate;
                const volVal = typeof current.volume === 'number' ? current.volume : 0;
                const volStr = volVal >= 10000 ? `${(volVal / 10000).toFixed(1)}万` : `${(volVal / 1000).toFixed(1)}千`;

                return [
                  { title: '时间:', value: dateStr },
                  { title: ' 幅:', value: { text: changePctStr, color: changeColor } },
                  { title: ' O:', value: typeof current.open === 'number' ? current.open.toFixed(2) : '--' },
                  { title: ' H:', value: typeof current.high === 'number' ? current.high.toFixed(2) : '--' },
                  { title: ' L:', value: typeof current.low === 'number' ? current.low.toFixed(2) : '--' },
                  { title: ' C:', value: typeof current.close === 'number' ? current.close.toFixed(2) : '--' },
                  { title: ' V:', value: volStr },
                ];
              },
            },
          },
        },
        indicator: {
          tooltip: {
            showRule: 'always',
            showType: 'standard',
            title: {
              showName: true,
              showParams: false,
            },
          },
        },
      },
    });

    chartInstanceRef.current = chart;

    if (chart) {
      // 1. 主图 MA 均线
      chart.createIndicator(
        {
          name: 'MA',
          paneId: 'candle_pane',
          calcParams: DEFAULT_MA_ITEMS.map((item) => item.day),
          styles: {
            lines: DEFAULT_MA_ITEMS.map((item) => ({ color: item.color })),
          },
        },
        true,
      );

      // 2. 副图: VOL 成交量
      chart.createIndicator('VOL', false);

      // 3. 转换 K 线数据。接口始终返回日线：周线必须在这里显式聚合，
      // 否则仅调用 chart.setPeriod 不会改变 dataLoader 注入的蜡烛数量。
      const displayKlines = period === 'week' ? aggregateWeeklyKlines(result.klines) : result.klines;
      const dataList = displayKlines.map((k) => {
        const y = parseInt(k.trade_date.slice(0, 4));
        const m = parseInt(k.trade_date.slice(4, 6)) - 1;
        const d = parseInt(k.trade_date.slice(6, 8));
        const ts = Date.UTC(y, m, d);

        return {
          timestamp: ts,
          open: k.open,
          high: k.high,
          low: k.low,
          close: k.close,
          volume: k.vol,
          turnover: k.amount,
          trade_date: k.trade_date,
        };
      });

      chart.setSymbol({
        ticker: result.ts_code,
        pricePrecision: 2,
        volumePrecision: 2,
      });
      chart.setPeriod({
        span: 1,
        type: period === 'week' ? 'week' : 'day',
      });

      // 默认放大单根 K 线宽度 (设为 16px)
      chart.setBarSpace(16);

      chart.setDataLoader({
        getBars: ({ callback }) => {
          callback(dataList);
        },
      });

      requestAnimationFrame(() => {
        if (chartInstanceRef.current) {
          chartInstanceRef.current.resize();
        }
      });

      // 4. 在日线 K 线上标注具体得分数值（周线不标注）
      if (period === 'day') {
        dataList.forEach((d) => {
          const h = hMap.get(d.trade_date);
          const score = h ? displayScore(h) : null;
          if (h && score !== null) {
            const scoreText = `${score.toFixed(1)}${h.second_opportunity?.active ? ' ★' : ''}`;
            const scoreColor = getStateColor(h.turn_episode_state || h.state).bg;

            chart.createOverlay({
              name: 'simpleAnnotation',
              extendData: scoreText,
              points: [{ timestamp: d.timestamp, value: d.high }],
              styles: {
                text: {
                  color: '#ffffff',
                  backgroundColor: scoreColor,
                  borderRadius: 4,
                  paddingLeft: 5,
                  paddingRight: 5,
                  paddingTop: 2,
                  paddingBottom: 2,
                },
              },
            });
          }
        });
      }
    }

    const handleResize = () => {
      if (chartInstanceRef.current) {
        chartInstanceRef.current.resize();
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) {
        dispose(chartRef.current);
        chartInstanceRef.current = null;
      }
    };
  }, [result, period]);

  // K 线包含测试区间之外的历史；悬停时按实际日期读取，不沿用上一个日期。
  useEffect(() => {
    if (!result || !hoveredDate || result.history.some((item) => item.trade_date === hoveredDate)) {
      setHoverError(null);
      return;
    }
    const cached = extraHistoryCacheRef.current.get(hoveredDate);
    if (cached) {
      setExtraHistoryItem(cached);
      setHoverError(null);
      return;
    }
    const controller = new AbortController();
    setHoverError(null);
    const timer = window.setTimeout(async () => {
      try {
        const params = new URLSearchParams({
          strategy_id: result.strategy_id,
          ts_code: result.ts_code,
          start_date: hoveredDate,
          end_date: hoveredDate,
        });
        const response = await fetch(`${getApiBase()}/api/strategy/single-stock/eval?${params}`, { signal: controller.signal });
        if (!response.ok) throw new Error(`读取失败（HTTP ${response.status}）`);
        const data: SingleStockEvalResult = await response.json();
        const item = data.history.find((row) => row.trade_date === hoveredDate);
        if (!item) throw new Error('该日期暂无可评估数据');
        extraHistoryCacheRef.current.set(hoveredDate, item);
        setExtraHistoryItem(item);
      } catch (error) {
        if (!controller.signal.aborted) setHoverError(error instanceof Error ? error.message : '读取失败');
      }
    }, 350);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [hoveredDate, result]);

  const activeDisplayItem = useMemo(() => {
    if (!result) return null;
    const date = hoveredDate || selectedDate;
    if (!date) return null;
    return result.history.find((h) => h.trade_date === date)
      || (extraHistoryItem?.trade_date === date ? extraHistoryItem : null);
  }, [extraHistoryItem, hoveredDate, result, selectedDate]);

  return (
    <div className="space-y-3">
      {/* 单行紧凑型顶栏控制区: 策略选择 + 股票输入 + 区间选择 */}
      <div className="bg-white/90 px-3.5 py-2.5 rounded-xl border border-[#c4c8bc]/60 shadow-xs flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex flex-wrap items-center gap-3">
          {/* 策略选择 */}
          <div className="flex items-center gap-1.5 bg-[#faf6f0] px-2.5 py-1 rounded-lg border border-[#c4c8bc]/50">
            <Layers className="h-3.5 w-3.5 text-[#4a7c59]" />
            <span className="font-bold text-[#2e3230]">策略:</span>
            <select
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value)}
              className="bg-white border border-[#c4c8bc]/60 px-2 py-0.5 rounded font-bold outline-none text-[#2e3230]"
            >
              {STRATEGIES.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>

          {/* 股票代码/名称 */}
          <div className="flex items-center gap-1.5 bg-[#faf6f0] px-2.5 py-1 rounded-lg border border-[#c4c8bc]/50">
            <Search className="h-3.5 w-3.5 text-[#705c30]" />
            <span className="font-bold text-[#2e3230]">股票:</span>
            <input
              type="text"
              value={stockInput}
              onFocus={(e) => e.currentTarget.select()}
              onChange={(e) => setStockInput(e.target.value)}
              placeholder="688505 或 康美药业"
              className="w-32 bg-white border border-[#c4c8bc]/60 px-2 py-0.5 rounded font-mono font-bold outline-none text-[#2e3230]"
            />
          </div>

          {/* 日期范围选择 */}
          <div className="flex items-center gap-1.5 bg-[#faf6f0] px-2.5 py-1 rounded-lg border border-[#c4c8bc]/50">
            <Calendar className="h-3.5 w-3.5 text-[#4a7c59]" />
            <span className="font-bold text-[#2e3230]">日期区间:</span>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="bg-white border border-[#c4c8bc]/60 px-1.5 py-0.5 rounded font-mono font-bold outline-none text-[#2e3230]"
            />
            <span className="text-[#686d68] font-bold">至</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="bg-white border border-[#c4c8bc]/60 px-1.5 py-0.5 rounded font-mono font-bold outline-none text-[#2e3230]"
            />
          </div>
        </div>

        <button
          onClick={() => handleRunEval()}
          disabled={loading || !stockInput.trim()}
          className="inline-flex items-center gap-1.5 bg-[#4a7c59] hover:bg-[#3b6447] text-white px-3.5 py-1 rounded-lg font-bold text-xs shadow-xs transition disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlayCircle className="h-3.5 w-3.5" />}
          <span>{loading ? '计算中...' : '开始测试'}</span>
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-bold text-rose-800">
          {error}
        </div>
      )}

      {/* K 线图主卡片区域 */}
      <div className="bg-white p-4 rounded-xl border border-[#c4c8bc]/60 shadow-xs space-y-3">
        {/* K 线 Header: 股票代码名称 + 均线图例 + 4大状态图例 */}
        <div className="flex flex-wrap items-center justify-between border-b border-[#c4c8bc]/40 pb-2.5 text-xs gap-2">
          <div className="flex items-center gap-3">
            {result ? (
              <div className="flex items-center gap-2">
                <span className="bg-[#4a7c59] text-white px-2 py-0.5 rounded font-mono font-bold text-xs">
                  {result.ts_code}
                </span>
                <span className="font-bold text-base text-[#2e3230]">{result.name}</span>
                <span className="px-2 py-0.5 bg-[#4a7c59]/10 text-[#4a7c59] rounded font-bold text-xs">
                  {result.industry}
                </span>
                <span className="text-[11px] text-[#686d68] font-mono">
                  (截止: <span className="font-bold text-[#d97706]">{endDate}</span>)
                </span>

                {/* 时间框架/周期选择 (日线 / 周线) */}
                <div className="flex items-center gap-1 bg-[#faf6f0] p-0.5 rounded-lg border border-[#c4c8bc]/50 text-[11px] font-bold ml-1">
                  <button
                    onClick={() => setPeriod('day')}
                    className={`px-2 py-0.5 rounded transition ${
                      period === 'day' ? 'bg-[#4a7c59] text-white shadow-xs' : 'text-[#686d68] hover:text-[#2e3230]'
                    }`}
                  >
                    日线
                  </button>
                  <button
                    onClick={() => setPeriod('week')}
                    className={`px-2 py-0.5 rounded transition ${
                      period === 'week' ? 'bg-[#4a7c59] text-white shadow-xs' : 'text-[#686d68] hover:text-[#2e3230]'
                    }`}
                  >
                    周线
                  </button>
                </div>
              </div>
            ) : (
              <span className="font-bold text-[#2e3230] flex items-center gap-1.5">
                <BarChart2 className="h-4 w-4 text-[#4a7c59]" />
                单股历史 K 线图
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1">
              <span className="text-[11px] text-[#686d68] font-bold">均线:</span>
              {DEFAULT_MA_ITEMS.map((ma) => (
                <span key={ma.day} className="px-1.5 py-0.2 rounded text-[10px] font-bold text-white" style={{ backgroundColor: ma.color }}>
                  MA{ma.day}
                </span>
              ))}
            </div>

            <div className="flex items-center gap-1.5 text-[11px]">
              <span className="text-[#686d68] font-bold">图例:</span>
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold text-white bg-[#94a3b8]">未进入底部准备</span>
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold text-white bg-[#334155]">底部准备</span>
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold text-white bg-[#4a7c59]">首次转强</span>
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold text-white bg-[#aa1c4a]">第一波已完成</span>
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold text-indigo-700 bg-indigo-50">★ 二买机会</span>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[minmax(220px,20%)_minmax(0,1fr)] gap-3">
          <aside className="rounded-lg border border-[#c4c8bc]/60 bg-[#faf8f3] p-3 text-xs overflow-y-auto lg:h-[clamp(360px,calc(100vh-310px),680px)]">
            {activeDisplayItem ? (() => {
              const item = activeDisplayItem;
              const details = item.score_detail_json?.v2_details || {};
              const prep = details.prep || {};
              const statusLabels: Record<string, string> = {
                EARLY_TURN: '转强', PRE_READY: '重点', WATCH: '观察',
                NO_SIGNAL: '未入选', POST_FIRST_WAVE: '本轮退出',
              };
              const status = item.signal_status ? statusLabels[item.signal_status] || item.signal_status : '暂无';
              const quality = item.bottom_structure_quality;
              return (
                <div className="space-y-3 text-[#2e3230]">
                  <div className="border-b border-[#c4c8bc]/50 pb-2">
                    <div className="font-mono font-bold text-sm">{item.trade_date.slice(0, 4)}-{item.trade_date.slice(4, 6)}-{item.trade_date.slice(6, 8)}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <span className="font-bold text-base">{displayScore(item)?.toFixed(1) ?? '—'} 分</span>
                      <span className="text-[#686d68]">底部准备度</span>
                    </div>
                    {item.turn_episode_state === 'FIRST_TURN_WINDOW' && item.turn_score != null && (
                      <div className="mt-1 text-[#686d68]">转强确认 {item.turn_score.toFixed(1)} 分</div>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex justify-between gap-2"><span className="text-[#686d68]">生命周期</span><span className="font-bold">{getStateColor(item.turn_episode_state || item.state).label}</span></div>
                    {item.first_wave_speed === 'FAST' && <div className="flex justify-between gap-2"><span className="text-[#686d68]">第一波</span><span className="font-bold">快速上涨候选（{item.first_wave_formation_bars} 个交易日）</span></div>}
                    <div className="flex justify-between gap-2"><span className="text-[#686d68]">二买机会</span><span className="font-bold">{item.second_opportunity?.active ? item.second_opportunity.types.map(kind => kind === 'PULLBACK_RECOVERY' ? '回调企稳' : kind === 'CONSOLIDATION_BREAKOUT' ? '横盘突破' : kind).join(' · ') : '暂无'}</span></div>
                    <div className="flex justify-between gap-2"><span className="text-[#686d68]">评级状态</span><span className="font-bold">{status}</span></div>
                    <div className="flex justify-between gap-2"><span className="text-[#686d68]">双底结构</span><span className="font-bold">{doubleBottomLabel(item.bottom_structure_type, quality)}</span></div>
                    {quality && quality !== 'NONE' && (
                      <div className="text-[11px] leading-5 text-[#686d68]">第一底 {item.bottom_first_low_date || '—'}<br />第二底 {item.bottom_second_low_date || '—'}<br />确认 {item.bottom_structure_confirmed_date || '—'}</div>
                    )}
                  </div>
                  <div className="border-t border-[#c4c8bc]/50 pt-2 space-y-1.5">
                    <div className="font-bold">评分拆解</div>
                    {([
                      ['走平拐头', prep.slope_turn, 40], ['均线结构', prep.compression_cross, 25],
                      ['夺回均线', prep.retake, 20], ['背景位置', prep.background_position, 15],
                    ] as Array<[string, number | undefined, number]>).map(([label, score, max]) => (
                      <div key={label} className="flex justify-between gap-2"><span className="text-[#686d68]">{label}</span><span className="font-mono font-bold">{score ?? '—'} / {max}</span></div>
                    ))}
                    {prep.bottom_bonus != null && <div className="flex justify-between gap-2"><span className="text-[#686d68]">日线双底加分</span><span className="font-mono font-bold">+{prep.bottom_bonus}</span></div>}
                    {prep.bottom_bonus != null && <div className="text-[11px] text-[#686d68]">原准备度 {prep.base_score} + 双底 {prep.bottom_bonus} = {displayScore(item)?.toFixed(1) ?? '—'}</div>}
                    {prep.slope_breakdown && <div className="text-[11px] leading-5 text-[#686d68]">MA5 {prep.slope_breakdown.ma5}/15 · MA10 {prep.slope_breakdown.ma10}/15 · MA20 {prep.slope_breakdown.ma20}/10</div>}
                    <div className="text-[11px] text-[#686d68]">站回 {item.retake_count ?? item.score_detail_json?.retake_count ?? '—'} 根均线</div>
                  </div>
                  <div className="border-t border-[#c4c8bc]/50 pt-2 space-y-1">
                    <div className="font-bold">条件与说明</div>
                    <div className="text-[11px] leading-5 text-[#686d68]">{preQualificationText(item.pre_qualification, item.rounded_repair)}</div>
                    {item.turn_episode_state === 'PRE_FIRST_TURN' && typeof details.ma20_slope_5d === 'number' && (
                      <div className="text-[11px] leading-5 text-[#686d68]">首次转强：MA20 五日变化 {(details.ma20_slope_5d * 100).toFixed(2)}%，{details.ma20_slope_5d >= -0.02 ? '达到 -2% 要求' : '尚未达到 -2% 要求'}</div>
                    )}
                    {item.reasons_json?.filter((reason) => !reason.msg.startsWith('底部准备度 ')).map((reason, index) => <div key={index} className="text-[11px] leading-5 text-[#686d68]">• {reason.msg}</div>)}
                  </div>
                </div>
              );
            })() : (
              <div className="text-[#686d68] leading-5">
                {hoveredDate ? <><div className="font-mono font-bold">{hoveredDate.slice(0, 4)}-{hoveredDate.slice(4, 6)}-{hoveredDate.slice(6, 8)}</div><div>{hoverError || '正在读取该日期的数据…'}</div></> : '开始测试后，将鼠标移到 K 线上查看对应日期的状态和评分。'}
              </div>
            )}
          </aside>
          <div ref={chartRef} className="w-full min-w-0 h-[clamp(360px,calc(100vh-310px),680px)] bg-white" />
        </div>
      </div>

      {/* 逐日评分明细与 Markdown 导出 */}
      {result && result.history && (
        <div className="bg-white rounded-xl border border-[#c4c8bc]/60 shadow-xs overflow-hidden">
          <div
            onClick={() => setShowBreakdownTable(!showBreakdownTable)}
            className="p-3 bg-[#f0ece4] hover:bg-[#e8e4dc] transition cursor-pointer flex items-center justify-between text-xs select-none"
          >
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-[#4a7c59]" />
              <span className="font-bold text-[#2e3230]">
                区间内交易日逐日评分拆解表 ({result.history.length} 个交易日)
              </span>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-white text-[#4a7c59] border border-[#c4c8bc]/40">
                {showBreakdownTable ? '点击收起明细表' : '点击展开明细表'}
              </span>
            </div>

            <div className="flex items-center gap-3">
              {activeDisplayItem && (
                <span className="font-mono text-xs font-bold text-[#705c30]">
                  当前高亮: {activeDisplayItem.trade_date} (准备度 {displayScore(activeDisplayItem)?.toFixed(1) ?? '--'}分)
                </span>
              )}
              <button
                onClick={handleExportMarkdown}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-bold bg-[#4a7c59] hover:bg-[#3b6447] text-white transition shadow-xs"
                title="将表格数据导出为 Markdown (.md) 文件"
              >
                <Download className="h-3.5 w-3.5" />
                <span>导出 MD 文档</span>
              </button>
              {showBreakdownTable ? (
                <ChevronUp className="h-4 w-4 text-[#686d68]" />
              ) : (
                <ChevronDown className="h-4 w-4 text-[#686d68]" />
              )}
            </div>
          </div>

          {showBreakdownTable && (
            <div className="overflow-x-auto border-t border-[#c4c8bc]/40">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="bg-[#faf6f0] border-b border-[#c4c8bc]/40 text-[#686d68]">
                    <th className="py-2.5 px-3 font-bold w-24">交易日期</th>
                    <th className="py-2.5 px-3 font-bold w-20">收盘价</th>
                    <th className="py-2.5 px-3 font-bold w-28">评分</th>
                    <th className="py-2.5 px-3 font-bold w-36">评级状态</th>
                    <th className="py-2.5 px-3 font-bold w-28">背景类型</th>
                    <th className="py-2.5 px-3 font-bold">评分拆解</th>
                    <th className="py-2.5 px-3 font-bold w-64">主要特征诊断与说明</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#c4c8bc]/20">
                  {result.history.map((item) => {
                    const s = item.score_detail_json?.v2_details || {};
                    const isSelected = activeDisplayItem?.trade_date === item.trade_date;

                    return (
                      <tr
                        key={item.trade_date}
                        onClick={() => { lastHoverDateRef.current = ''; setHoveredDate(null); setSelectedDate(item.trade_date); }}
                        className={`hover:bg-[#f7f5f0]/80 transition cursor-pointer ${
                          isSelected ? 'bg-[#4a7c59]/10 font-bold' : ''
                        }`}
                      >
                        {/* 交易日期 */}
                        <td className="py-2.5 px-3 font-mono font-bold text-[#2e3230]">
                          {item.trade_date.slice(0, 4)}-{item.trade_date.slice(4, 6)}-{item.trade_date.slice(6, 8)}
                        </td>

                        {/* 收盘价 */}
                        <td className="py-2.5 px-3 font-mono font-bold text-[#2e3230]">
                          {item.close.toFixed(2)}
                        </td>

                        {/* 分数与所属评分体系 */}
                        <td className="py-2.5 px-3 font-mono font-bold text-sm text-[#2e3230]">
                          <div>{displayScore(item)?.toFixed(1) ?? '--'}分</div>
                          <div className="mt-0.5 text-[10px] font-sans text-[#686d68]">
                            底部准备度{item.turn_episode_state === 'OUTSIDE_A_PRE' ? '（尚未进入底部准备）' : ''}
                            {item.turn_episode_state === 'FIRST_TURN_WINDOW' && item.turn_score != null && <div>转强确认 {item.turn_score.toFixed(1)}分</div>}
                          </div>
                        </td>

                        {/* 评级状态 */}
                        <td className="py-2.5 px-3">
                          <span
                            className="px-2 py-0.5 rounded text-[10px] font-bold text-white"
                            style={{ backgroundColor: getStateColor(item.state).bg }}
                          >
                            {getStateColor(item.state).label}
                          </span>
                        </td>

                        {/* 3 层属性与生命周期 */}
                        <td className="py-2.5 px-3 space-y-1">
                          <div className="flex flex-col gap-1 items-start">
                            <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold border ${
                              (item.turn_episode_state || s.turn_episode_state) === 'FIRST_TURN_WINDOW'
                                ? 'bg-emerald-50 text-emerald-800 border-emerald-300'
                                : (item.turn_episode_state || s.turn_episode_state) === 'POST_FIRST_WAVE'
                                ? 'bg-slate-100 text-slate-700 border-slate-300'
                                : 'bg-zinc-100 text-zinc-600 border-zinc-300'
                            }`}>
                              {(item.turn_episode_state || s.turn_episode_state) === 'FIRST_TURN_WINDOW'
                                ? '首次转强'
                                : (item.turn_episode_state || s.turn_episode_state) === 'POST_FIRST_WAVE'
                                ? '第一波已完成 (退出A-Pre)'
                                : (item.turn_episode_state || s.turn_episode_state) === 'OUTSIDE_A_PRE'
                                ? '未进入 A-Pre'
                                : '底部准备中'}
                            </span>

                            {item.second_opportunity?.active && (
                              <span className="inline-block rounded px-1.5 py-0.5 text-[10px] font-bold border border-indigo-300 bg-indigo-50 text-indigo-800">
                                二买机会 · {item.second_opportunity.types.map(kind => kind === 'PULLBACK_RECOVERY' ? '回调企稳' : kind === 'CONSOLIDATION_BREAKOUT' ? '横盘突破' : kind).join(' · ')}
                              </span>
                            )}

                            {item.early_observation?.active && (
                              <span className="inline-block rounded px-1.5 py-0.5 text-[10px] font-bold border border-amber-300 bg-amber-50 text-amber-800">
                                提前修复观察 · 首次 {item.early_observation.first_date} · MA5 {item.early_observation.ma5?.toFixed(2)}（连续修复，3日{((item.early_observation.ma5_slope_3d ?? 0) * 100).toFixed(2)}%） · MA10 {item.early_observation.ma10?.toFixed(2)}（{((item.early_observation.ma10_slope_5d ?? 0) * 100).toFixed(2)}%） · 尚未确认 · 夺回{item.early_observation.retake_count}根均线
                              </span>
                            )}
                            {(item.is_overextended || s.is_overextended) && (
                              <span className="inline-block rounded px-1.5 py-0.5 text-[10px] font-black border bg-rose-50 text-rose-800 border-rose-300">
                                偏离过大
                              </span>
                            )}
                            {item.bottom_structure_quality && item.bottom_structure_quality !== 'NONE' && (
                              <span
                                className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold border ${
                                  item.bottom_structure_quality === 'CLEAR'
                                    ? 'bg-emerald-50 text-emerald-800 border-emerald-300'
                                    : 'bg-amber-50 text-amber-800 border-amber-300'
                                }`}
                                title={`第一底 ${item.bottom_first_low_date || '-'} · 第二底 ${item.bottom_second_low_date || '-'} · 确认 ${item.bottom_structure_confirmed_date || '-'}`}
                              >
                                {doubleBottomLabel(item.bottom_structure_type, item.bottom_structure_quality)}
                              </span>
                            )}
                          </div>
                        </td>

                        {/* 按生命周期显示对应评分拆解 */}
                        <td className="py-2.5 px-3">
                          {item.prep_score != null ? (
                            <div className="flex flex-wrap items-center gap-1 text-[11px] font-mono">
                              <span className="px-1.5 py-0.2 rounded bg-emerald-50 text-emerald-700">走平拐头: {s.prep?.slope_turn ?? 0}/40</span>
                              {s.prep?.slope_breakdown && <span className="px-1.5 py-0.2 rounded bg-emerald-50 text-emerald-700">MA5 {s.prep.slope_breakdown.ma5}/15 · MA10 {s.prep.slope_breakdown.ma10}/15 · MA20 {s.prep.slope_breakdown.ma20}/10</span>}
                              <span className="px-1.5 py-0.2 rounded bg-blue-50 text-blue-700">均线结构: {s.prep?.compression_cross ?? 0}/25</span>
                              <span className="px-1.5 py-0.2 rounded bg-purple-50 text-purple-700">夺回{s.retake_count ?? item.score_detail_json?.retake_count ?? '—'}根均线: {s.prep?.retake ?? '—'}/20</span>
                              <span className="px-1.5 py-0.2 rounded bg-amber-50 text-amber-700">背景位置: {s.prep?.background_position ?? 0}/15</span>
                              {s.prep?.bottom_bonus != null && <span className="px-1.5 py-0.2 rounded bg-emerald-50 text-emerald-700">日线双底: +{s.prep.bottom_bonus}（原分 {s.prep.base_score}）</span>}
                            </div>
                          ) : (
                            <div className="flex flex-wrap items-center gap-1 text-[11px] font-mono">
                              <span className="px-1.5 py-0.2 rounded bg-slate-100 text-slate-700">Base: {item.score_detail_json?.background || 0}</span>
                              <span className="px-1.5 py-0.2 rounded bg-blue-50 text-blue-700">Trans: {s.transition || 0} (扣 penalty:-{s.chop_penalty || 0})</span>
                              <span className="px-1.5 py-0.2 rounded bg-purple-50 text-purple-700">Retake: {s.retake || 0}</span>
                              <span className="px-1.5 py-0.2 rounded bg-emerald-50 text-emerald-700">Dir: {s.direction || 0}</span>
                              <span className="px-1.5 py-0.2 rounded bg-amber-50 text-amber-700">Fresh: {s.freshness || 0}</span>
                              <span className="px-1.5 py-0.2 rounded bg-indigo-50 text-indigo-700">Vol: {s.vol || 0}</span>
                              <span className="px-1.5 py-0.2 rounded bg-rose-50 text-rose-700">Space: {s.space || 0}</span>
                            </div>
                          )}
                        </td>

                        {/* 核心诊断原因说明 */}
                        <td className="py-2.5 px-3 text-[#2e3230]">
                          <div className="space-y-0.5 max-w-xs">
                            <div className="text-[11px] leading-relaxed">{preQualificationText(item.pre_qualification, item.rounded_repair)}</div>
                            {item.pre_entry_reason && <div className="text-[11px]">进入方式：{item.pre_entry_reason === 'EARLY_ROUNDED_REPAIR' ? '早期圆弧修复' : '持续修复确认'}{item.pre_confirm_date ? ` · 确认 ${item.pre_confirm_date}` : ''}</div>}
                            {item.reasons_json && item.reasons_json.length > 0 ? (
                              item.reasons_json.map((r, idx) => (
                                <div key={idx} className="text-[11px] truncate" title={r.msg}>
                                  • {r.msg}
                                </div>
                              ))
                            ) : (
                              <span className="text-[#686d68] text-[11px]">形态处于整理蓄势期</span>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
