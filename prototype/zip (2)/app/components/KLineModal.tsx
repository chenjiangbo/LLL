'use client';

import React, { useEffect, useRef, useState } from 'react';
import { init, dispose, Chart, Nullable } from 'klinecharts';
import {
  X,
  Trash2,
  LineChart,
  RefreshCw,
  Settings,
  Slash,
  MoveHorizontal,
  MoveVertical,
  ArrowUpRight,
  Tag,
  Square,
  Layers,
  Minus,
  Palette,
  Eraser,
  Plus,
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Star,
} from 'lucide-react';

interface KLineBar {
  timestamp: number;
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  turnover: number;
  [key: string]: unknown;
}

interface DrawingItem {
  id?: string;
  name: string;
  points?: Array<{ timestamp?: number; value?: number }>;
  styles?: Record<string, any>;
}

interface MaConfigItem {
  id: string;
  day: number;
  color: string;
}

interface KLineModalProps {
  assetCode: string;
  assetName: string;
  industry?: string;
  isOpen: boolean;
  onClose: () => void;
  onNavigatePrev?: () => void;
  onNavigateNext?: () => void;
  hasPrev?: boolean;
  hasNext?: boolean;
  apiHost?: string;
  isSelected?: boolean;
  onToggleSelect?: () => void;
}

const DRAWING_TOOLS = [
  { key: 'segment', label: '趋势线', icon: Slash },
  { key: 'straightLine', label: '直线', icon: MoveHorizontal },
  { key: 'ray', label: '射线', icon: ArrowUpRight },
  { key: 'horizontalStraightLine', label: '水平线', icon: Minus },
  { key: 'verticalStraightLine', label: '垂直线', icon: MoveVertical },
  { key: 'priceLine', label: '价格线', icon: Tag },
  { key: 'rectangle', label: '矩形', icon: Square },
  { key: 'parallelStraightLine', label: '平行通道', icon: Layers },
];

const PALETTE_COLORS = [
  { color: '#ef4444', label: '红' },
  { color: '#3b82f6', label: '蓝' },
  { color: '#10b981', label: '绿' },
  { color: '#f59e0b', label: '黄' },
  { color: '#8b5cf6', label: '紫' },
  { color: '#000000', label: '黑' },
];

const DEFAULT_MA_ITEMS: MaConfigItem[] = [
  { id: '1', day: 5, color: '#ec4899' },
  { id: '2', day: 10, color: '#f59e0b' },
  { id: '3', day: 30, color: '#3b82f6' },
  { id: '4', day: 60, color: '#8b5cf6' },
];

export default function KLineModal({
  assetCode,
  assetName,
  industry,
  isOpen,
  onClose,
  onNavigatePrev,
  onNavigateNext,
  hasPrev = false,
  hasNext = false,
  apiHost = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL || 'http://127.0.0.1:18080',
  isSelected = false,
  onToggleSelect,
}: KLineModalProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Nullable<Chart>>(null);

  const [fetchedIndustry, setFetchedIndustry] = useState<string>('');
  const [period, setPeriod] = useState<'daily' | 'weekly' | 'monthly' | '30min'>('daily');
  const [adjust, setAdjust] = useState<'qfq' | 'none'>('qfq');
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [drawingCount, setDrawingCount] = useState<number>(0);

  // 补全获取行业
  useEffect(() => {
    if (isOpen && !industry && assetCode) {
      const codeOnly = assetCode.split('.')[0];
      fetch(`${apiHost}/api/market/suggest?query=${encodeURIComponent(codeOnly)}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (data && data.items && data.items.length > 0) {
            setFetchedIndustry(data.items[0].industry || '');
          }
        })
        .catch(() => {});
    }
  }, [isOpen, industry, assetCode, apiHost]);

  const displayIndustry = industry || fetchedIndustry;

  // 均线配置状态
  const [maItems, setMaItems] = useState<MaConfigItem[]>(DEFAULT_MA_ITEMS);
  const [showMaConfig, setShowMaConfig] = useState<boolean>(false);
  const maConfigRef = useRef<HTMLDivElement>(null);

  // 划线样式自定义状态
  const [lineColor, setLineColor] = useState<string>('#ef4444');
  const [lineSize, setLineSize] = useState<number>(2);
  const [lineStyle, setLineStyle] = useState<'solid' | 'dashed'>('solid');
  const [showStylePanel, setShowStylePanel] = useState<boolean>(false);
  const stylePanelRef = useRef<HTMLDivElement>(null);

  // Click Outside 闭合均线及划线样式面板
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (maConfigRef.current && !maConfigRef.current.contains(event.target as Node)) {
        setShowMaConfig(false);
      }
      if (stylePanelRef.current && !stylePanelRef.current.contains(event.target as Node)) {
        setShowStylePanel(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // 副图指标状态 (MACD / KDJ / RSI)
  const [subIndicator, setSubIndicator] = useState<'MACD' | 'KDJ' | 'RSI'>('MACD');
  const currentSubIndicatorRef = useRef<'MACD' | 'KDJ' | 'RSI'>('MACD');

  const stateRef = useRef({ period, adjust, assetCode, apiHost });
  useEffect(() => {
    stateRef.current = { period, adjust, assetCode, apiHost };
  }, [period, adjust, assetCode, apiHost]);

  // 静默自动保存划线函数
  const autoSaveDrawings = async () => {
    if (!chartRef.current) return;
    const overlays = chartRef.current.getOverlays();
    const drawingsData = overlays.map((o) => ({
      id: o.id,
      name: o.name,
      points: o.points,
      styles: o.styles,
    }));

    try {
      await fetch(`${stateRef.current.apiHost}/api/screening/drawings/${stateRef.current.assetCode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ drawings: drawingsData }),
      });
    } catch (e) {
      console.error('自动保存划线失败', e);
    }
  };

  // 全局键盘监听：Esc 关闭弹窗，Space 入候选池，← / → 导航左右股票，Delete / Backspace 删划线
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;
      const target = e.target as HTMLElement;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) {
        return;
      }

      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }

      if (e.key === ' ' || e.code === 'Space') {
        e.preventDefault();
        if (onToggleSelect) onToggleSelect();
        return;
      }

      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        if (hasPrev && onNavigatePrev) onNavigatePrev();
        return;
      }

      if (e.key === 'ArrowRight') {
        e.preventDefault();
        if (hasNext && onNavigateNext) onNavigateNext();
        return;
      }

      if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (chartRef.current) {
          chartRef.current.zoomAtCoordinate(1.15);
        }
        return;
      }

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (chartRef.current) {
          chartRef.current.zoomAtCoordinate(0.85);
        }
        return;
      }

      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (chartRef.current) {
          const overlays = chartRef.current.getOverlays();
          const selected = overlays.find((o: any) => o.selected || o.isFocused);
          if (selected && selected.id) {
            chartRef.current.removeOverlay({ id: selected.id });
            updateDrawingCount();
            autoSaveDrawings();
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, hasPrev, hasNext, onNavigatePrev, onNavigateNext, onClose]);

  useEffect(() => {
    if (!isOpen || !assetCode || !chartContainerRef.current) return;

    // 1. 初始化 KLineChart
    const chart = init(chartContainerRef.current, {
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
                const rawDate = String(current.trade_date || '');
                const dateStr = rawDate.length === 8 ? `${rawDate.slice(0, 4)}-${rawDate.slice(4, 6)}-${rawDate.slice(6)}` : rawDate;
                const volVal = typeof current.volume === 'number' ? current.volume : 0;
                const volStr = volVal >= 10000 ? `${(volVal / 10000).toFixed(1)}万` : `${(volVal / 1000).toFixed(1)}千`;
                return [
                  { title: '时间:', value: dateStr },
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
    chartRef.current = chart;

    if (!chart) return;

    // 2. 将 MA 均线通过 paneId: 'candle_pane' 融合覆盖在 K 线主图上
    chart.createIndicator(
      {
        name: 'MA',
        paneId: 'candle_pane',
        calcParams: maItems.map((item) => item.day),
        styles: {
          lines: maItems.map((item) => ({
            color: item.color,
          })),
        },
      },
      true,
    );

    // 副图 1: 固定 VOL 成交量
    chart.createIndicator('VOL', false);

    // 副图 2: 切换的 MACD / KDJ / RSI
    chart.createIndicator(subIndicator, false);
    currentSubIndicatorRef.current = subIndicator;

    // 3. 注册 DataLoader 异步载入数据
    chart.setDataLoader({
      getBars: async ({ callback }) => {
        const { period: currentPeriod, adjust: currentAdjust, assetCode: currentAsset, apiHost: currentApiHost } = stateRef.current;
        setLoading(true);
        setError(null);
        try {
          const klineRes = await fetch(`${currentApiHost}/api/screening/kline/${currentAsset}?period=${currentPeriod}&adjust=${currentAdjust}`);
          if (!klineRes.ok) throw new Error('加载K线数据失败');
          const klineJson = await klineRes.json();
          const bars: KLineBar[] = klineJson.bars || [];

          if (bars.length === 0) {
            if (currentPeriod === '30min') {
              setError('暂未获取到该标的的 30分钟 K线数据（数据正在后台同步获取中）');
            } else {
              setError('暂无当前周期的 K线数据');
            }
          }

          callback(bars);

          // 还原划线
          const drawingsRes = await fetch(`${currentApiHost}/api/screening/drawings/${currentAsset}`);
          if (drawingsRes.ok) {
            const drawingsJson = await drawingsRes.json();
            const drawings: DrawingItem[] = drawingsJson.drawings || [];
            chart.removeOverlay();
            if (drawings.length > 0) {
              drawings.forEach((item) => {
                try {
                  chart.createOverlay({
                    id: item.id,
                    name: item.name,
                    points: item.points,
                    styles: item.styles,
                  });
                } catch (e) {
                  console.error('还原划线失败', e);
                }
              });
              setDrawingCount(drawings.length);
            } else {
              setDrawingCount(0);
            }
          }
        } catch (err: any) {
          setError(err.message || '加载图表失败');
        } finally {
          setLoading(false);
          requestAnimationFrame(() => {
            if (chartRef.current) chartRef.current.resize();
          });
        }
      },
    });

    // 4. 激活 Symbol 与 Period
    chart.setSymbol({
      ticker: assetCode,
      pricePrecision: 2,
      volumePrecision: 2,
    });
    chart.setPeriod({
      span: period === '30min' ? 30 : 1,
      type: period === 'daily' ? 'day' : period === 'weekly' ? 'week' : period === 'monthly' ? 'month' : 'minute',
    });

    const handleResize = () => {
      if (chartRef.current) {
        chartRef.current.resize();
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartContainerRef.current) {
        dispose(chartContainerRef.current);
        chartRef.current = null;
      }
    };
  }, [isOpen, assetCode, period, adjust]);

  // 切换副图指标 (MACD / KDJ / RSI)
  const handleChangeSubIndicator = (newIndicator: 'MACD' | 'KDJ' | 'RSI') => {
    if (!chartRef.current || newIndicator === subIndicator) return;
    const oldIndicator = currentSubIndicatorRef.current;
    chartRef.current.removeIndicator({ name: oldIndicator });
    chartRef.current.createIndicator(newIndicator, false);
    currentSubIndicatorRef.current = newIndicator;
    setSubIndicator(newIndicator);
  };

  // 均线设置：修改某条 MA 天数
  const handleUpdateMaDay = (id: string, newDay: number) => {
    setMaItems((prev) => prev.map((item) => (item.id === id ? { ...item, day: newDay } : item)));
  };

  // 均线设置：修改某条 MA 颜色
  const handleUpdateMaColor = (id: string, newColor: string) => {
    setMaItems((prev) => prev.map((item) => (item.id === id ? { ...item, color: newColor } : item)));
  };

  // 均线设置：添加一条新均线
  const handleAddMaItem = () => {
    if (maItems.length >= 8) return;
    const newId = String(Date.now());
    const nextDays = [5, 10, 20, 60, 120, 250, 30, 90];
    const existingDays = maItems.map((i) => i.day);
    const day = nextDays.find((d) => !existingDays.includes(d)) || (existingDays.length + 1) * 10;
    const colors = ['#ef4444', '#f59e0b', '#3b82f6', '#8b5cf6', '#10b981', '#334155'];
    const color = colors[maItems.length % colors.length];

    setMaItems((prev) => [...prev, { id: newId, day, color }]);
  };

  // 均线设置：删除一条均线
  const handleRemoveMaItem = (id: string) => {
    if (maItems.length <= 1) return;
    setMaItems((prev) => prev.filter((item) => item.id !== id));
  };

  // 保存均线配置并更新图表重绘
  const handleApplyMaConfig = () => {
    setShowMaConfig(false);

    if (chartRef.current && maItems.length > 0) {
      chartRef.current.overrideIndicator({
        name: 'MA',
        paneId: 'candle_pane',
        calcParams: maItems.map((item) => item.day),
        styles: {
          lines: maItems.map((item) => ({
            color: item.color,
          })),
        },
      });
    }
  };

  // 划线选择并注入自定义样式，并在划线完成时自动无感保存
  const handleSelectTool = (toolKey: string) => {
    if (!chartRef.current) return;
    setActiveTool(toolKey);

    chartRef.current.createOverlay({
      name: toolKey,
      styles: {
        line: {
          color: lineColor,
          size: lineSize,
          style: lineStyle,
          dashedValue: lineStyle === 'dashed' ? [6, 6] : undefined,
        },
        polygon: {
          color: lineColor + '22',
          borderColor: lineColor,
          borderSize: lineSize,
          borderStyle: lineStyle,
          borderDashedValue: lineStyle === 'dashed' ? [6, 6] : undefined,
        },
      },
      onDrawEnd: () => {
        setActiveTool(null);
        updateDrawingCount();
        autoSaveDrawings();
      },
    });
  };

  const updateDrawingCount = () => {
    if (!chartRef.current) return;
    const overlays = chartRef.current.getOverlays();
    setDrawingCount(overlays.length);
  };

  // 删除单根划线并自动保存
  const handleRemoveSingleDrawing = () => {
    if (!chartRef.current) return;
    const overlays = chartRef.current.getOverlays();
    if (overlays.length === 0) return;

    const selected = overlays.find((o: any) => o.selected || o.isFocused);
    if (selected && selected.id) {
      chartRef.current.removeOverlay({ id: selected.id });
    } else {
      const last = overlays[overlays.length - 1];
      if (last && last.id) {
        chartRef.current.removeOverlay({ id: last.id });
      }
    }
    updateDrawingCount();
    autoSaveDrawings();
  };

  // 清空所有划线并自动保存
  const handleClearDrawings = () => {
    if (!chartRef.current) return;
    chartRef.current.removeOverlay();
    setDrawingCount(0);
    setActiveTool(null);
    autoSaveDrawings();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 backdrop-blur-xs p-3">
      <div className="flex flex-col w-[96vw] max-w-[1500px] h-[94vh] bg-white rounded-xl shadow-2xl overflow-hidden border border-slate-200">
        {/* 全局单行工具栏 (Single Header Bar, 高度 46px) */}
        <div className="flex flex-wrap items-center justify-between px-4 py-2 border-b border-slate-200 bg-slate-50 shrink-0 gap-2 h-12 text-xs">
          {/* 左区：标的信息、上一只/下一只、周期/复权控制 */}
          <div className="flex items-center gap-1.5">
            <LineChart className="w-4 h-4 text-emerald-600 mr-0.5" />

            {/* 上一只/下一只导航按钮 */}
            <div className="flex items-center gap-0.5 mr-1">
              <button
                onClick={onNavigatePrev}
                disabled={!hasPrev}
                className="p-1 text-slate-600 hover:text-slate-900 hover:bg-slate-200 rounded transition disabled:opacity-25"
                title="上一只股票 (←)"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                onClick={onNavigateNext}
                disabled={!hasNext}
                className="p-1 text-slate-600 hover:text-slate-900 hover:bg-slate-200 rounded transition disabled:opacity-25"
                title="下一只股票 (→)"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>

            <h3 className="font-bold text-slate-800 text-sm flex items-center gap-1.5">
              <span>{assetName}</span>
              <span className="text-xs font-normal text-slate-500">({assetCode})</span>
              {displayIndustry && (
                <span className="ml-1 px-2 py-0.5 rounded bg-emerald-50 text-[#4a7c59] text-xs font-bold border border-[#4a7c59]/30">
                  行业: {displayIndustry}
                </span>
              )}
            </h3>

            {/* 周期 */}
            <div className="flex bg-slate-200/80 p-0.5 rounded ml-2">
              {(['daily', 'weekly', 'monthly', '30min'] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  className={`px-2 py-0.5 text-xs font-bold rounded transition ${
                    period === p ? 'bg-white text-slate-800 shadow-xs' : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  {p === 'daily' ? '日K' : p === 'weekly' ? '周K' : p === 'monthly' ? '月K' : '30分'}
                </button>
              ))}
            </div>

            {/* 复权 */}
            <div className="flex bg-slate-200/80 p-0.5 rounded ml-1">
              <button
                onClick={() => setAdjust('qfq')}
                className={`px-2 py-0.5 text-xs font-bold rounded transition ${
                  adjust === 'qfq' ? 'bg-white text-slate-800 shadow-xs' : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                前复权
              </button>
              <button
                onClick={() => setAdjust('none')}
                className={`px-2 py-0.5 text-xs font-bold rounded transition ${
                  adjust === 'none' ? 'bg-white text-slate-800 shadow-xs' : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                不复权
              </button>
            </div>

            {/* 入候选池按钮 */}
            {onToggleSelect && (
              <button
                onClick={onToggleSelect}
                className={`ml-2 px-2.5 py-1 text-xs font-bold rounded-md transition flex items-center gap-1.5 shadow-xs ${
                  isSelected
                    ? 'bg-amber-500 text-white hover:bg-amber-600'
                    : 'bg-white text-slate-700 hover:bg-emerald-50 hover:text-emerald-700 border border-slate-300'
                }`}
                title="入候选池 / 取消入池 (快捷键: 空格 Space)"
              >
                <Star className={`w-3.5 h-3.5 ${isSelected ? 'fill-white text-white' : 'text-amber-500'}`} />
                <span>{isSelected ? '已入池' : '入候选池'}</span>
              </button>
            )}

            {/* 快捷缩放控制按钮组 (仅图标) */}
            <div className="flex bg-slate-200/80 p-0.5 rounded ml-1 items-center gap-0.5">
              <button
                onClick={() => chartRef.current?.zoomAtCoordinate(1.15)}
                className="p-1 rounded hover:bg-white text-slate-700 hover:text-slate-900 transition"
                title="放大 K线 (键盘 ↑ 键)"
              >
                <ZoomIn className="w-3.5 h-3.5 text-emerald-600" />
              </button>
              <button
                onClick={() => chartRef.current?.zoomAtCoordinate(0.85)}
                className="p-1 rounded hover:bg-white text-slate-700 hover:text-slate-900 transition"
                title="缩小 K线 (键盘 ↓ 键)"
              >
                <ZoomOut className="w-3.5 h-3.5 text-amber-600" />
              </button>
            </div>
          </div>

          {/* 中区：主图均线设置与副图指标切换 */}
          <div className="flex items-center gap-3">
            {/* 主图均线设置 */}
            <div ref={maConfigRef} className="relative flex items-center gap-1 bg-white border border-slate-200 px-2 py-0.5 rounded">
              <span className="font-bold text-slate-700 text-[11px]">主图MA:</span>
              <div className="flex items-center gap-1">
                {maItems.map((item) => (
                  <span key={item.id} className="font-bold text-[11px]" style={{ color: item.color }}>
                    {item.day}
                  </span>
                ))}
              </div>
              <button
                onClick={() => setShowMaConfig(!showMaConfig)}
                className="p-0.5 text-slate-400 hover:text-emerald-600 transition ml-0.5"
                title="自定义 MA 均线天数与颜色"
              >
                <Settings className="w-3.5 h-3.5" />
              </button>

              {/* 均线设置 Popover */}
              {showMaConfig && (
                <div className="absolute top-7 left-0 z-30 w-72 p-3 bg-white rounded-lg shadow-xl border border-slate-200 space-y-2.5">
                  <div className="flex items-center justify-between border-b pb-1.5 border-slate-100">
                    <p className="text-xs font-bold text-slate-800">均线天数与颜色配置</p>
                    <button
                      onClick={handleAddMaItem}
                      disabled={maItems.length >= 8}
                      className="inline-flex items-center gap-0.5 px-2 py-0.5 text-[11px] font-bold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 rounded transition disabled:opacity-50"
                    >
                      <Plus className="w-3 h-3" /> 添加均线
                    </button>
                  </div>

                  {/* 均线列表 */}
                  <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
                    {maItems.map((item) => (
                      <div key={item.id} className="flex items-center justify-between gap-2 bg-slate-50 p-1.5 rounded border border-slate-200/60">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-bold text-slate-600">MA</span>
                          <input
                            type="number"
                            min={1}
                            max={500}
                            value={item.day}
                            onChange={(e) => handleUpdateMaDay(item.id, parseInt(e.target.value, 10) || 1)}
                            className="w-14 px-1.5 py-0.5 text-xs font-bold border border-slate-300 rounded outline-none focus:border-emerald-500 text-slate-800"
                          />
                          <span className="text-xs text-slate-500">日</span>
                        </div>

                        {/* 颜色挑选区 */}
                        <div className="flex items-center gap-1">
                          {PALETTE_COLORS.map((p) => (
                            <button
                              key={p.color}
                              onClick={() => handleUpdateMaColor(item.id, p.color)}
                              className={`w-4 h-4 rounded-full transition border ${
                                item.color === p.color ? 'border-slate-800 scale-125 shadow-xs' : 'border-transparent'
                              }`}
                              style={{ backgroundColor: p.color }}
                              title={p.label}
                            />
                          ))}
                          <button
                            onClick={() => handleRemoveMaItem(item.id)}
                            disabled={maItems.length <= 1}
                            className="p-1 text-rose-500 hover:bg-rose-100 rounded transition ml-1 disabled:opacity-30"
                            title="删除此均线"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="flex justify-end gap-2 pt-1 border-t border-slate-100">
                    <button
                      onClick={handleApplyMaConfig}
                      className="w-full py-1 bg-emerald-600 text-white rounded text-xs font-bold hover:bg-emerald-700 transition"
                    >
                      应用设置
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* 副图切换 */}
            <div className="flex items-center gap-0.5 bg-slate-200/80 p-0.5 rounded">
              <span className="text-[11px] font-bold text-slate-500 px-1.5">副图:</span>
              {(['MACD', 'KDJ', 'RSI'] as const).map((indicatorName) => (
                <button
                  key={indicatorName}
                  onClick={() => handleChangeSubIndicator(indicatorName)}
                  className={`px-2 py-0.5 text-xs font-bold rounded transition ${
                    subIndicator === indicatorName
                      ? 'bg-emerald-600 text-white shadow-xs'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  {indicatorName}
                </button>
              ))}
            </div>
          </div>

          {/* 右区：划线多样式控制 + 图标工具 + 单线/全清删除 + 关闭 */}
          <div className="flex items-center gap-2">
            {/* 划线样式调色板与粗细Popover */}
            <div ref={stylePanelRef} className="relative flex items-center gap-1 bg-white border border-slate-200 px-1.5 py-0.5 rounded">
              <button
                onClick={() => setShowStylePanel(!showStylePanel)}
                className="flex items-center gap-1 text-[11px] font-bold text-slate-700 hover:text-emerald-600 transition"
                title="设置划线颜色与粗细线型"
              >
                <Palette className="w-3.5 h-3.5" style={{ color: lineColor }} />
                <span className="w-2.5 h-2.5 rounded-full border border-slate-300 inline-block" style={{ backgroundColor: lineColor }} />
              </button>

              {/* 划线样式自定义 Popover */}
              {showStylePanel && (
                <div className="absolute top-7 right-0 z-30 w-56 p-2.5 bg-white rounded-lg shadow-xl border border-slate-200 space-y-2 text-xs">
                  <div>
                    <p className="font-bold text-slate-700 mb-1">线条颜色:</p>
                    <div className="flex gap-1.5">
                      {PALETTE_COLORS.map((item) => (
                        <button
                          key={item.color}
                          onClick={() => {
                            setLineColor(item.color);
                          }}
                          className={`w-6 h-6 rounded-full border transition flex items-center justify-center ${
                            lineColor === item.color ? 'border-slate-800 scale-110 shadow-xs' : 'border-transparent'
                          }`}
                          style={{ backgroundColor: item.color }}
                          title={item.label}
                        />
                      ))}
                    </div>
                  </div>

                  <div>
                    <p className="font-bold text-slate-700 mb-1">线条粗细:</p>
                    <div className="flex gap-1 bg-slate-100 p-0.5 rounded">
                      {[1, 2, 3].map((size) => (
                        <button
                          key={size}
                          onClick={() => setLineSize(size)}
                          className={`flex-1 py-0.5 text-xs font-bold rounded transition ${
                            lineSize === size ? 'bg-white text-slate-800 shadow-xs' : 'text-slate-600'
                          }`}
                        >
                          {size}px
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <p className="font-bold text-slate-700 mb-1">线条线型:</p>
                    <div className="flex gap-1 bg-slate-100 p-0.5 rounded">
                      <button
                        onClick={() => setLineStyle('solid')}
                        className={`flex-1 py-0.5 text-xs font-bold rounded transition ${
                          lineStyle === 'solid' ? 'bg-white text-slate-800 shadow-xs' : 'text-slate-600'
                        }`}
                      >
                        实线 ─
                      </button>
                      <button
                        onClick={() => setLineStyle('dashed')}
                        className={`flex-1 py-0.5 text-xs font-bold rounded transition ${
                          lineStyle === 'dashed' ? 'bg-white text-slate-800 shadow-xs' : 'text-slate-600'
                        }`}
                      >
                        虚线 ---
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* 划线图标工具 */}
            <div className="flex items-center gap-0.5">
              {DRAWING_TOOLS.map((tool) => {
                const IconComponent = tool.icon;
                const isActive = activeTool === tool.key;
                return (
                  <button
                    key={tool.key}
                    onClick={() => handleSelectTool(tool.key)}
                    title={tool.label}
                    className={`p-1 rounded border transition flex items-center justify-center ${
                      isActive
                        ? 'bg-emerald-600 text-white border-emerald-600 shadow-xs'
                        : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-100 hover:text-emerald-700'
                    }`}
                  >
                    <IconComponent className="w-3.5 h-3.5" />
                  </button>
                );
              })}
              {/* 删除选中线段 */}
              <button
                onClick={handleRemoveSingleDrawing}
                title="删除当前选中的线 (也可按 Delete/Backspace 键)"
                className="p-1 text-amber-700 bg-amber-50 hover:bg-amber-100 border border-amber-200 rounded transition ml-1"
              >
                <Eraser className="w-3.5 h-3.5" />
              </button>
              {/* 全部清空 */}
              <button
                onClick={handleClearDrawings}
                title="清空所有划线"
                className="p-1 text-rose-600 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded transition"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="h-4 w-[1px] bg-slate-300 mx-1" />

            <span className="text-[11px] font-bold text-slate-500">已划线: {drawingCount}</span>

            {/* 显眼高亮右上角关闭按钮 (支持点击或 Esc 键) */}
            <button
              onClick={onClose}
              title="关闭窗口 (快捷键: Esc)"
              className="px-2.5 py-1 bg-rose-50 hover:bg-rose-600 hover:text-white border border-rose-200 text-rose-700 rounded-lg transition shadow-xs flex items-center gap-1 ml-2 font-bold text-xs"
            >
              <X className="w-4 h-4 stroke-[2.5]" />
              <span>关闭 (Esc)</span>
            </button>
          </div>
        </div>

        {/* 主图表容器 */}
        <div className="relative flex-1 bg-white w-full h-full min-h-[620px]">
          {loading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/70 backdrop-blur-xs">
              <div className="flex items-center gap-2 text-slate-600 font-medium text-sm">
                <RefreshCw className="w-5 h-5 animate-spin text-emerald-600" />
                正在载入 K 线数据...
              </div>
            </div>
          )}
          {error && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-white">
              <div className="text-rose-600 font-medium text-sm bg-rose-50 px-4 py-2 rounded-lg border border-rose-200">
                {error}
              </div>
            </div>
          )}
          <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} className="min-h-[620px]" />
        </div>
      </div>
    </div>
  );
}
