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
} from 'lucide-react';
import { init, dispose, Chart } from 'klinecharts';

interface SingleStockHistoryItem {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number;
  amount: number;
  total_score: number;
  state: string;
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

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL || 'http://127.0.0.1:18080';

const STRATEGIES = [
  { id: 'A_PRE_V2', name: '🧪 A-Pre V2 早期转强实验 (均线状态迁移)', desc: '基于均线高度压缩、结扎交叉、次序重排与新鲜度的早期爆发转强模型' },
];

const PRESET_STOCKS = [
  { code: '688505.SH', name: '复旦张江' },
  { code: '600518.SH', name: '康美药业' },
  { code: '600683.SH', name: '京投发展' },
  { code: '600216.SH', name: '浙江医药' },
  { code: '300404.SZ', name: '博济医药' },
  { code: '002659.SZ', name: '凯文教育' },
];

const DEFAULT_MA_ITEMS = [
  { day: 5, color: '#ec4899' },
  { day: 10, color: '#f59e0b' },
  { day: 30, color: '#3b82f6' },
  { day: 60, color: '#8b5cf6' },
];

// 根据状态获取颜色
function getStateColor(state: string): { bg: string; text: string; label: string } {
  switch (state) {
    case 'EARLY_TURN_STRICT':
      return { bg: '#d97706', text: '#ffffff', label: '🔥 严格精选转强' };
    case 'EARLY_TURN':
      return { bg: '#16a34a', text: '#ffffff', label: '🔥 转强信号' };
    case 'PRE_READY_STRICT':
      return { bg: '#705c30', text: '#ffffff', label: '⭐ 严格重点观察' };
    case 'PRE_READY':
      return { bg: '#92400e', text: '#ffffff', label: '⭐ 重点观察' };
    case 'WATCH':
      return { bg: '#334155', text: '#ffffff', label: '👀 初步观察' };
    case 'TOO_LATE':
      return { bg: '#be123c', text: '#ffffff', label: '⚠️ 偏离过大' };
    default:
      return { bg: '#94a3b8', text: '#ffffff', label: '无信号' };
  }
}

export default function SingleStockTestView() {
  const [strategyId, setStrategyId] = useState<string>('A_PRE_V2');
  const [stockInput, setStockInput] = useState<string>('688505.SH');
  const [startDate, setStartDate] = useState<string>('2026-07-10');
  const [endDate, setEndDate] = useState<string>('2026-08-12');
  
  const [loading, setLoading] = useState<boolean>(false);
  const [result, setResult] = useState<SingleStockEvalResult | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [hoveredHistoryItem, setHoveredHistoryItem] = useState<SingleStockHistoryItem | null>(null);
  const [showBreakdownTable, setShowBreakdownTable] = useState<boolean>(false);

  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<Chart | null>(null);

  // 执行单股多日策略测试
  const handleRunEval = useCallback(async (codeOverride?: string) => {
    const targetCode = codeOverride || stockInput;
    if (!targetCode.trim()) return;

    setLoading(true);
    try {
      const sDate = startDate.replace(/-/g, '');
      const eDate = endDate.replace(/-/g, '');

      const params = new URLSearchParams({
        strategy_id: strategyId,
        ts_code: targetCode.trim(),
        start_date: sDate,
        end_date: eDate,
      });

      const res = await fetch(`${API_BASE}/api/strategy/single-stock/eval?${params.toString()}`);
      if (res.ok) {
        const json: SingleStockEvalResult = await res.json();
        setResult(json);
        if (json.history && json.history.length > 0) {
          setSelectedDate(json.history[json.history.length - 1].trade_date);
        }
      }
    } catch (e) {
      console.error('Failed to run single stock eval:', e);
    } finally {
      setLoading(false);
    }
  }, [stockInput, startDate, endDate, strategyId]);

  // 初始加载一次
  useEffect(() => {
    handleRunEval('688505.SH');
  }, []);

  // 渲染 K 线图
  useEffect(() => {
    if (!result || !result.klines || result.klines.length === 0 || !chartRef.current) return;

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

                const prev = neighborData.prev;
                const currentClose = typeof current.close === 'number' ? current.close : 0;
                const prevClose = prev && typeof prev.close === 'number' ? prev.close : (typeof current.open === 'number' ? current.open : currentClose);

                let changePct = 0;
                if (prevClose > 0) {
                  changePct = ((currentClose - prevClose) / prevClose) * 100;
                }

                const changePctStr = `${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%`;
                const changeColor = changePct > 0 ? '#ef4444' : changePct < 0 ? '#10b981' : '#6b7280';

                const rawDate = String(current.trade_date || '');
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

      // 3. 转换 K 线数据
      const dataList = result.klines.map((k) => {
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
        type: 'day',
      });

      // 增大单根 K 线宽度（默认放大，方便显示得分标记）
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

      // 4. 建立交易日历史得分索引 map
      const historyMap = new Map<string, SingleStockHistoryItem>();
      result.history.forEach((h) => historyMap.set(h.trade_date, h));

      // 5. 在 K 线上标注具体得分数值 (字体颜色/背景展示对应状态)
      dataList.forEach((d) => {
        const h = historyMap.get(d.trade_date);
        if (h && h.total_score > 0) {
          const scoreText = `${h.total_score.toFixed(1)}`;
          const colorInfo = getStateColor(h.state);

          chart.createOverlay({
            name: 'simpleAnnotation',
            extendData: scoreText,
            points: [{ timestamp: d.timestamp, value: d.high }],
            styles: {
              text: {
                color: colorInfo.text,
                backgroundColor: colorInfo.bg,
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

      // 6. 监听鼠标十字光标移动，划过某天 K 线时实时更新顶部的特征诊断 Banner
      chart.subscribeAction('onCrosshairChange', (param: any) => {
        if (param && param.kLineData && param.kLineData.trade_date) {
          const tDate = String(param.kLineData.trade_date);
          const item = historyMap.get(tDate);
          if (item) {
            setHoveredHistoryItem(item);
          } else {
            setHoveredHistoryItem(null);
          }
        } else {
          setHoveredHistoryItem(null);
        }
      });
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
  }, [result]);

  const maxScoreItem = useMemo(() => {
    if (!result || !result.history || result.history.length === 0) return null;
    return [...result.history].sort((a, b) => b.total_score - a.total_score)[0];
  }, [result]);

  const activeDisplayItem = useMemo(() => {
    if (hoveredHistoryItem) return hoveredHistoryItem;
    if (!result || !result.history || !selectedDate) return null;
    return result.history.find((h) => h.trade_date === selectedDate) || null;
  }, [hoveredHistoryItem, result, selectedDate]);

  return (
    <div className="space-y-4">
      {/* 控制栏: 策略选择 + 股票输入 + 区间选择 */}
      <div className="bg-white/90 p-4 rounded-xl border border-[#c4c8bc]/60 shadow-xs flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          {/* 策略选择 */}
          <div className="flex items-center gap-2 bg-[#faf6f0] px-3 py-1.5 rounded-lg border border-[#c4c8bc]/50 text-xs">
            <Layers className="h-4 w-4 text-[#4a7c59]" />
            <span className="font-bold text-[#2e3230]">评估策略:</span>
            <select
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value)}
              className="bg-white border border-[#c4c8bc]/60 px-2 py-1 rounded font-bold text-xs outline-none text-[#2e3230]"
            >
              {STRATEGIES.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>

          {/* 股票代码/名称 */}
          <div className="flex items-center gap-2 bg-[#faf6f0] px-3 py-1.5 rounded-lg border border-[#c4c8bc]/50 text-xs">
            <Search className="h-4 w-4 text-[#705c30]" />
            <span className="font-bold text-[#2e3230]">测试股票:</span>
            <input
              type="text"
              value={stockInput}
              onChange={(e) => setStockInput(e.target.value)}
              placeholder="如 688505 或 康美药业"
              className="w-28 bg-white border border-[#c4c8bc]/60 px-2 py-1 rounded font-mono font-bold outline-none text-[#2e3230]"
            />
          </div>

          {/* 预设热门测试标的 */}
          <div className="hidden lg:flex items-center gap-1">
            <span className="text-[11px] text-[#686d68] font-bold">预设:</span>
            {PRESET_STOCKS.map((st) => (
              <button
                key={st.code}
                onClick={() => {
                  setStockInput(st.code);
                  handleRunEval(st.code);
                }}
                className={`px-2 py-0.5 rounded text-[11px] font-bold transition border ${
                  stockInput === st.code
                    ? 'bg-[#4a7c59] text-white border-[#4a7c59]'
                    : 'bg-white text-[#4a4e4a] hover:bg-[#faf6f0] border-[#c4c8bc]/50'
                }`}
              >
                {st.name}
              </button>
            ))}
          </div>

          {/* 日期范围选择 */}
          <div className="flex items-center gap-2 bg-[#faf6f0] px-3 py-1.5 rounded-lg border border-[#c4c8bc]/50 text-xs">
            <Calendar className="h-4 w-4 text-[#4a7c59]" />
            <span className="font-bold text-[#2e3230]">测试日期区间:</span>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="bg-white border border-[#c4c8bc]/60 px-2 py-0.5 rounded font-mono font-bold outline-none text-[#2e3230]"
            />
            <span className="text-[#686d68] font-bold">至</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="bg-white border border-[#c4c8bc]/60 px-2 py-0.5 rounded font-mono font-bold outline-none text-[#2e3230]"
            />
          </div>

          <button
            onClick={() => handleRunEval()}
            disabled={loading || !stockInput.trim()}
            className="inline-flex items-center gap-1.5 bg-[#4a7c59] hover:bg-[#3b6447] text-white px-4 py-1.5 rounded-lg font-bold text-xs shadow-xs transition disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
            <span>{loading ? '策略计算中...' : '开始单股区间测试'}</span>
          </button>
        </div>
      </div>

      {/* 测试标的概览 Banner */}
      {result && (
        <div className="bg-[#faf6f0] border border-[#c4c8bc]/60 p-4 rounded-xl shadow-xs flex flex-wrap items-center justify-between gap-4 text-xs">
          <div className="flex items-center gap-3">
            <div className="bg-[#4a7c59] text-white p-2.5 rounded-lg font-mono font-bold text-base shadow-xs">
              {result.ts_code}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-lg text-[#2e3230]">{result.name}</span>
                <span className="px-2 py-0.5 bg-[#4a7c59]/10 text-[#4a7c59] rounded font-bold text-xs">
                  {result.industry}
                </span>
              </div>
              <p className="text-[11px] text-[#686d68]">
                策略: <span className="font-bold text-[#2e3230]">A-Pre V2 均线状态迁移模型</span> | 区间有效交易日: <span className="font-mono font-bold">{result.history.length}</span> 天
              </p>
            </div>
          </div>

          {maxScoreItem && (
            <div className="flex items-center gap-6">
              <div className="bg-white px-3.5 py-2 rounded-lg border border-[#c4c8bc]/50 text-right">
                <span className="text-[11px] text-[#686d68] font-bold block">区间最高分日</span>
                <span className="font-mono font-bold text-base text-[#d97706]">
                  {maxScoreItem.total_score.toFixed(1)}分 ({maxScoreItem.trade_date})
                </span>
              </div>
              <div className="bg-white px-3.5 py-2 rounded-lg border border-[#c4c8bc]/50 text-right">
                <span className="text-[11px] text-[#686d68] font-bold block">精选转强触发天数</span>
                <span className="font-mono font-bold text-base text-[#4a7c59]">
                  {result.history.filter((h) => h.state.includes('EARLY_TURN')).length} 天
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* K 线图区域 */}
      <div className="bg-white p-4 rounded-xl border border-[#c4c8bc]/60 shadow-xs space-y-3">
        {/* 顶部工具栏与图例 */}
        <div className="flex flex-wrap items-center justify-between border-b border-[#c4c8bc]/40 pb-2.5 text-xs gap-2">
          <div className="flex items-center gap-3">
            <span className="font-bold text-[#2e3230] flex items-center gap-1.5">
              <BarChart2 className="h-4 w-4 text-[#4a7c59]" />
              单股历史 K 线图 (放大切片，数据截止至: <span className="font-mono text-[#d97706]">{endDate}</span>)
            </span>
            <div className="flex items-center gap-1">
              <span className="text-[11px] text-[#686d68] font-bold">均线:</span>
              {DEFAULT_MA_ITEMS.map((ma) => (
                <span key={ma.day} className="px-1.5 py-0.2 rounded text-[10px] font-bold text-white" style={{ backgroundColor: ma.color }}>
                  MA{ma.day}
                </span>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2 text-[11px]">
            <span className="text-[#686d68] font-bold">得分色块图例:</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold text-white bg-[#d97706]">严格精选(75+)</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold text-white bg-[#16a34a]">普通转强</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold text-white bg-[#705c30]">重点观察</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold text-white bg-[#be123c]">偏离过大</span>
          </div>
        </div>

        {/* 位于图表顶部、固定独立的特征诊断 Banner（鼠标在 K 线上移动时自动联动刷新，100% 绝不遮挡 K 线） */}
        {activeDisplayItem && (
          <div className="bg-[#faf6f0] p-3 rounded-xl border border-[#c4c8bc]/60 text-xs space-y-1.5 shadow-2xs">
            <div className="flex flex-wrap items-center justify-between border-b border-[#c4c8bc]/40 pb-1.5 gap-2">
              <div className="flex items-center gap-2">
                <Info className="w-4 h-4 text-[#4a7c59]" />
                <span className="font-bold text-[#2e3230]">十字光标选中日期:</span>
                <span className="font-mono font-bold text-[#4a7c59]">
                  {activeDisplayItem.trade_date.slice(0, 4)}-{activeDisplayItem.trade_date.slice(4, 6)}-{activeDisplayItem.trade_date.slice(6, 8)}
                </span>
                {hoveredHistoryItem ? (
                  <span className="text-[10px] text-[#4a7c59] bg-[#4a7c59]/15 px-1.5 py-0.2 rounded font-bold">
                    鼠标划过即时联动中
                  </span>
                ) : (
                  <span className="text-[10px] text-[#686d68] bg-white px-1.5 py-0.2 rounded border border-[#c4c8bc]/40">
                    点击表格选中
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                <span className="text-[#686d68] font-bold">策略得分:</span>
                <span className="font-mono font-bold text-base text-[#2e3230]">
                  {activeDisplayItem.total_score.toFixed(1)}分
                </span>
                <span
                  className="px-2 py-0.5 rounded text-[10px] font-bold text-white"
                  style={{ backgroundColor: getStateColor(activeDisplayItem.state).bg }}
                >
                  {getStateColor(activeDisplayItem.state).label}
                </span>
              </div>
            </div>

            <div className="text-[11px] text-[#2e3230] space-y-1">
              <span className="font-bold text-[#686d68] mr-2">主要特征诊断与说明:</span>
              <div className="inline-flex flex-wrap items-center gap-x-4 gap-y-1">
                {activeDisplayItem.reasons_json && activeDisplayItem.reasons_json.length > 0 ? (
                  activeDisplayItem.reasons_json.map((r, idx) => (
                    <span key={idx} className="bg-white px-2 py-0.5 rounded border border-[#c4c8bc]/40 font-medium">
                      • {r.msg}
                    </span>
                  ))
                ) : (
                  <span className="text-gray-400">形态处于整理蓄势期</span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* 高度 520px 的 K 线图表容器（画布无遮挡） */}
        <div ref={chartRef} className="w-full h-[520px] bg-white" />
      </div>

      {/* 逐日得分与 7 大算子明细表格（默认隐藏，点击展开） */}
      {result && result.history && (
        <div className="bg-white rounded-xl border border-[#c4c8bc]/60 shadow-xs overflow-hidden">
          <div
            onClick={() => setShowBreakdownTable(!showBreakdownTable)}
            className="p-3.5 bg-[#f0ece4] hover:bg-[#e8e4dc] transition cursor-pointer flex items-center justify-between text-xs select-none"
          >
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-[#4a7c59]" />
              <span className="font-bold text-[#2e3230]">
                区间内交易日逐日得分与 7 大算子拆解表 ({result.history.length} 个交易日)
              </span>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-white text-[#4a7c59] border border-[#c4c8bc]/40">
                {showBreakdownTable ? '点击收起明细表' : '点击展开明细表'}
              </span>
            </div>

            <div className="flex items-center gap-3">
              {activeDisplayItem && (
                <span className="font-mono text-xs font-bold text-[#705c30]">
                  当前高亮日期: {activeDisplayItem.trade_date} ({activeDisplayItem.total_score.toFixed(1)}分)
                </span>
              )}
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
                    <th className="py-2.5 px-3 font-bold w-24">总得分</th>
                    <th className="py-2.5 px-3 font-bold w-36">评级状态</th>
                    <th className="py-2.5 px-3 font-bold w-28">背景类型</th>
                    <th className="py-2.5 px-3 font-bold">7 大算子得分明细 (Base/Trans/Retake/Dir/Fresh/Vol/Space)</th>
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
                        onClick={() => setSelectedDate(item.trade_date)}
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

                        {/* 总得分 */}
                        <td className="py-2.5 px-3 font-mono font-bold text-sm text-[#2e3230]">
                          {item.total_score.toFixed(1)}分
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

                        {/* 背景类型 */}
                        <td className="py-2.5 px-3 text-[#686d68] font-bold">
                          {item.background_type === 'FIRST_TURN'
                            ? '首次底部转向'
                            : item.background_type === 'SECONDARY_TURN'
                            ? '二次转强突破'
                            : item.background_type === 'CONSOLIDATION_RESTART'
                            ? '整理后再启动'
                            : item.background_type}
                        </td>

                        {/* 7 大算子得分明细 */}
                        <td className="py-2.5 px-3">
                          <div className="flex flex-wrap items-center gap-1 text-[11px] font-mono">
                            <span className="px-1.5 py-0.2 rounded bg-slate-100 text-slate-700">
                              Base: {item.score_detail_json?.background || 0}
                            </span>
                            <span className="px-1.5 py-0.2 rounded bg-blue-50 text-blue-700">
                              Trans: {s.transition || 0} (扣 penalty:-{s.chop_penalty || 0})
                            </span>
                            <span className="px-1.5 py-0.2 rounded bg-purple-50 text-purple-700">
                              Retake: {s.retake || 0}
                            </span>
                            <span className="px-1.5 py-0.2 rounded bg-emerald-50 text-emerald-700">
                              Dir: {s.direction || 0}
                            </span>
                            <span className="px-1.5 py-0.2 rounded bg-amber-50 text-amber-700">
                              Fresh: {s.freshness || 0}
                            </span>
                            <span className="px-1.5 py-0.2 rounded bg-indigo-50 text-indigo-700">
                              Vol: {s.vol || 0}
                            </span>
                            <span className="px-1.5 py-0.2 rounded bg-rose-50 text-rose-700">
                              Space: {s.space || 0}
                            </span>
                          </div>
                        </td>

                        {/* 核心诊断原因说明 */}
                        <td className="py-2.5 px-3 text-[#2e3230]">
                          <div className="space-y-0.5 max-w-xs">
                            {item.reasons_json && item.reasons_json.length > 0 ? (
                              item.reasons_json.map((r, idx) => (
                                <div key={idx} className="text-[11px] truncate" title={r.msg}>
                                  • {r.msg}
                                </div>
                              ))
                            ) : (
                              <span className="text-[#686d68] text-[11px]">形态平淡，处于整理蓄势期</span>
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
