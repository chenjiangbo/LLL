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

export default function SingleStockTestView() {
  const [strategyId, setStrategyId] = useState<string>('A_PRE_V2');
  const [stockInput, setStockInput] = useState<string>('688505.SH');
  const [startDate, setStartDate] = useState<string>('2026-07-10');
  const [endDate, setEndDate] = useState<string>('2026-08-12');
  
  const [loading, setLoading] = useState<boolean>(false);
  const [result, setResult] = useState<SingleStockEvalResult | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

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

    const chart = init(chartRef.current);
    chartInstanceRef.current = chart;

    if (chart) {
      // 各种 MA 指标设置
      chart.createIndicator('MA', false);
      chart.createIndicator('VOL', false);

      // 转换为 Klinecharts 格式的数据
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

      // 标注测试区间内的转强信号点 (EARLY_TURN_STRICT / EARLY_TURN)
      const historyMap = new Map<string, SingleStockHistoryItem>();
      result.history.forEach((h) => historyMap.set(h.trade_date, h));

      // 给有强信号的日期增加 Tag
      dataList.forEach((d) => {
        const h = historyMap.get(d.trade_date);
        if (h && (h.state === 'EARLY_TURN_STRICT' || h.state === 'EARLY_TURN' || h.state === 'PRE_READY_STRICT')) {
          const text = h.state === 'EARLY_TURN_STRICT' ? '🔥精选' : h.state === 'EARLY_TURN' ? '🔥转强' : '⭐重点';
          const color = h.state.includes('EARLY_TURN') ? '#d97706' : '#705c30';
          
          chart.createOverlay({
            name: 'simpleAnnotation',
            extendData: text,
            points: [{ timestamp: d.timestamp, value: d.high }],
            styles: {
              text: {
                color: '#ffffff',
                backgroundColor: color,
                borderRadius: 4,
                paddingLeft: 4,
                paddingRight: 4,
                paddingTop: 2,
                paddingBottom: 2,
              },
            },
          });
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

  const selectedItem = useMemo(() => {
    if (!result || !result.history || !selectedDate) return null;
    return result.history.find((h) => h.trade_date === selectedDate) || null;
  }, [result, selectedDate]);

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

      {/* K 线图区域 (K线历史严格截止至 end_date) */}
      <div className="bg-white p-4 rounded-xl border border-[#c4c8bc]/60 shadow-xs space-y-2">
        <div className="flex items-center justify-between border-b border-[#c4c8bc]/40 pb-2 text-xs">
          <span className="font-bold text-[#2e3230] flex items-center gap-1.5">
            <BarChart2 className="h-4 w-4 text-[#4a7c59]" />
            单股历史 K 线图 (图表数据截止至: <span className="font-mono text-[#d97706]">{endDate}</span>，无未来数据)
          </span>
          <span className="text-[11px] text-[#686d68]">
            图标说明: <span className="px-1.5 py-0.5 bg-amber-600 text-white rounded text-[10px] font-bold mr-1">🔥精选</span>
            <span className="px-1.5 py-0.5 bg-[#705c30] text-white rounded text-[10px] font-bold">⭐重点</span>
          </span>
        </div>
        <div ref={chartRef} className="w-full h-80 bg-white" />
      </div>

      {/* 逐日得分与 7 大算子明细表格 */}
      {result && result.history && (
        <div className="bg-white rounded-xl border border-[#c4c8bc]/60 shadow-xs overflow-hidden">
          <div className="p-3 bg-[#f0ece4] border-b border-[#c4c8bc]/40 flex items-center justify-between text-xs">
            <span className="font-bold text-[#2e3230] flex items-center gap-1.5">
              <TrendingUp className="h-4 w-4 text-[#4a7c59]" />
              区间内交易日逐日得分与 7 大算子拆解表 ({result.history.length} 个交易日)
            </span>
            {selectedItem && (
              <span className="font-mono text-xs font-bold text-[#705c30]">
                当前高亮日期: {selectedItem.trade_date} ({selectedItem.total_score.toFixed(1)}分)
              </span>
            )}
          </div>

          <div className="overflow-x-auto">
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
                  const isSelected = selectedDate === item.trade_date;

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
                          className={`px-2 py-0.5 rounded text-[10px] font-bold text-white ${
                            item.state === 'EARLY_TURN_STRICT'
                              ? 'bg-amber-600'
                              : item.state === 'EARLY_TURN'
                              ? 'bg-[#4a7c59]'
                              : item.state === 'PRE_READY_STRICT'
                              ? 'bg-[#705c30]'
                              : item.state === 'PRE_READY'
                              ? 'bg-amber-800'
                              : item.state === 'WATCH'
                              ? 'bg-[#2e3230]'
                              : item.state === 'TOO_LATE'
                              ? 'bg-rose-700'
                              : 'bg-gray-400'
                          }`}
                        >
                          {item.state === 'EARLY_TURN_STRICT'
                            ? '🔥 严格精选转强'
                            : item.state === 'EARLY_TURN'
                            ? '🔥 转强信号'
                            : item.state === 'PRE_READY_STRICT'
                            ? '⭐ 严格重点观察'
                            : item.state === 'PRE_READY'
                            ? '⭐ 重点观察'
                            : item.state === 'WATCH'
                            ? '👀 初步观察'
                            : item.state === 'TOO_LATE'
                            ? '⚠️ 偏离过大'
                            : '无信号'}
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
        </div>
      )}
    </div>
  );
}
