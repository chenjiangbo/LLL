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
  ChevronDown,
  TestTube2,
  Loader2,
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
  last_30m_slot?: string;
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

interface StrategyScoreItem {
  trade_date: string;
  high?: number;
  total_score: number;
  prep_score?: number | null;
  turn_score?: number | null;
  score_type?: 'PREP_SCORE' | 'TURN_SCORE' | 'NONE';
  state: string;
  turn_episode_state?: string;
  second_opportunity?: { active: boolean; types?: string[] } | null;
  reasons_json?: Array<{ type?: string; msg?: string }>;
}

interface KLineModalProps {
  assetCode: string;
  assetName: string;
  industry?: string;
  scoreStartDate?: string;
  scoreTradeDate?: string;
  isOpen: boolean;
  onClose: () => void;
  onNavigatePrev?: () => void;
  onNavigateNext?: () => void;
  hasPrev?: boolean;
  hasNext?: boolean;
  apiHost?: string;
  isSelected?: boolean;
  onToggleSelect?: () => void;
  onSpaceToggleWatchlist?: () => void;
  watchlistSource?: { type: 'MANUAL' | 'STRATEGY'; strategy?: string; stage?: string; snapshot_date?: string };
  showSubIndicators?: boolean;
  showAiPoolButton?: boolean;
  showWatchlistButton?: boolean;
  embedded?: boolean;
  showNavigation?: boolean;
  showAssetInfo?: boolean;
  onPickPrice?: (price: number) => void;
  planPriceLines?: Array<{ key: string; label: string; title: string; value: number; color: string }>;
  tradeMarkers?: Array<{ date: string; price?: number; label: string; color?: string }>;
  strategyTestRequest?: number;
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

function toMarketDataAssetCode(assetCode: string): string {
  const match = assetCode.trim().toUpperCase().match(/^(SH|SSE|SHSE|SZ|SZSE|BJ|BSE):([0-9]{6})$/);
  if (!match) return assetCode;
  const exchange = ({ SH: 'SH', SSE: 'SH', SHSE: 'SH', SZ: 'SZ', SZSE: 'SZ', BJ: 'BJ', BSE: 'BJ' } as const)[match[1] as 'SH' | 'SSE' | 'SHSE' | 'SZ' | 'SZSE' | 'BJ' | 'BSE'];
  return `${match[2]}.${exchange}`;
}

const DEFAULT_MA_ITEMS: MaConfigItem[] = [
  { id: '1', day: 5, color: '#ec4899' },
  { id: '2', day: 10, color: '#f59e0b' },
  { id: '3', day: 30, color: '#3b82f6' },
  { id: '4', day: 60, color: '#8b5cf6' },
];

const SCORE_OVERLAY_ID_PREFIX = 'early-turn-score-overlay-';
// 固定副图 pane，避免 KLineModal 重建/切换周期时由 klinecharts 自动分配出重复副图。
const VOLUME_PANE_ID = 'watchlist-volume-pane';
const SUB_INDICATOR_PANE_ID = 'watchlist-sub-indicator-pane';
// 不能在组件参数中直接使用 `=[]`：每次渲染都会创建新数组，进而触发图表
// 初始化 effect 反复销毁、重建和重新请求数据。
const EMPTY_TRADE_MARKERS: Array<{ date: string; price?: number; label: string; color?: string }> = [];

function getLifecycleColor(state: string): { bg: string; text: string } {
  switch (state) {
    case 'FIRST_TURN_WINDOW':
      return { bg: '#4a7c59', text: '#ffffff' };
    case 'POST_FIRST_WAVE':
      return { bg: '#aa1c4a', text: '#ffffff' };
    case 'PRE_FIRST_TURN':
      return { bg: '#334155', text: '#ffffff' };
    default:
      return { bg: '#94a3b8', text: '#ffffff' };
  }
}

function getDisplayedPreparationScore(item: StrategyScoreItem): number | null {
  return typeof item.prep_score === 'number' && Number.isFinite(item.prep_score)
    ? item.prep_score
    : null;
}

function normalizeTradeDate(value: string): string {
  return String(value).replace(/-/g, '').slice(0, 8);
}

export default function KLineModal({
  assetCode,
  assetName,
  industry,
  scoreStartDate,
  scoreTradeDate,
  isOpen,
  onClose,
  onNavigatePrev,
  onNavigateNext,
  hasPrev = false,
  hasNext = false,
  apiHost = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL,
  isSelected = false,
  onToggleSelect,
  onSpaceToggleWatchlist,
  watchlistSource,
  showSubIndicators = true,
  showAiPoolButton = true,
  showWatchlistButton = true,
  embedded = false,
  showNavigation = true,
  showAssetInfo = !embedded,
  onPickPrice,
  planPriceLines,
  tradeMarkers = EMPTY_TRADE_MARKERS,
  strategyTestRequest = 0,
}: KLineModalProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Nullable<Chart>>(null);
  const [planLineLayout, setPlanLineLayout] = useState<Array<{ key: string; label: string; title: string; value: number; color: string; y: number; labelY: number; direction: number }>>([]);
  const planPriceLinesRef = useRef(planPriceLines);
  planPriceLinesRef.current = planPriceLines;

  useEffect(() => {
    if (!isOpen || !planPriceLines) return;
    const updateLayout = () => {
      const chart = chartRef.current;
      const pane = chart?.getSize('candle_pane');
      if (!chart || !pane || pane.height <= 0) return;
      const entries = (planPriceLinesRef.current || []).flatMap((line) => {
        if (!Number.isFinite(line.value) || line.value <= 0) return [];
        const point = chart.convertToPixel({ value: line.value }, { paneId: 'candle_pane' });
        const y = !Array.isArray(point) ? point.y : undefined;
        if (typeof y !== 'number' || !Number.isFinite(y)) return [];
        return [{ ...line, y, labelY: Math.max(10, Math.min(pane.height - 10, y)), direction: y < 0 ? -1 : y > pane.height ? 1 : 0 }];
      }).sort((a, b) => a.labelY - b.labelY);
      for (let i = 1; i < entries.length; i++) entries[i].labelY = Math.max(entries[i].labelY, entries[i - 1].labelY + 22);
      for (let i = entries.length - 1; i >= 0; i--) entries[i].labelY = Math.min(entries[i].labelY, pane.height - 10 - (entries.length - 1 - i) * 22);
      setPlanLineLayout((previous) => JSON.stringify(previous) === JSON.stringify(entries) ? previous : entries);
    };
    updateLayout();
    const timer = window.setInterval(updateLayout, 200);
    return () => window.clearInterval(timer);
  }, [isOpen, Boolean(planPriceLines)]);

  const [inWatchlist, setInWatchlist] = useState(false);

  // Check & Toggle Watchlist in PostgreSQL
  useEffect(() => {
    if (!isOpen || !assetCode) return;
    fetch(`${apiHost}/api/watchlist/stocks`)
      .then((res) => res.json())
      .then((data) => {
        const codes = Array.isArray(data.watchlist_codes) ? data.watchlist_codes : [];
        setInWatchlist(codes.includes(assetCode));
      })
      .catch(() => {});
  }, [isOpen, assetCode, apiHost]);

  const handleToggleWatchlist = async () => {
    try {
      const res = await fetch(`${apiHost}/api/watchlist/stocks/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asset_code: assetCode, source: watchlistSource }),
      });
      if (res.ok) {
        const data = await res.json();
        setInWatchlist(data.in_watchlist);
      }
    } catch (e) {
      console.error('Toggle watchlist error:', e);
    }
  };

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

  // 划线工具下拉状态
  const [showDrawingDropdown, setShowDrawingDropdown] = useState<boolean>(false);
  const drawingDropdownRef = useRef<HTMLDivElement>(null);

  // AI 分析池快捷操作
  const [inAiPool, setInAiPool] = useState<boolean>(false);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [showStrategyTestDialog, setShowStrategyTestDialog] = useState(false);
  const [strategyTestRange, setStrategyTestRange] = useState<{
    strategyId: string;
    startDate: string;
    endDate: string;
  } | null>(null);
  const [strategyTestLoading, setStrategyTestLoading] = useState(false);
  const [strategyTestError, setStrategyTestError] = useState<string | null>(null);
  const [strategyTestStrategyId, setStrategyTestStrategyId] = useState('A_PRE_V2');
  const [strategyScores, setStrategyScores] = useState<StrategyScoreItem[]>([]);
  const [activeStrategyScore, setActiveStrategyScore] = useState<StrategyScoreItem | null>(null);
  const strategyScoreMapRef = useRef<Map<string, StrategyScoreItem>>(new Map());
  const lastStrategyScoreDateRef = useRef('');

  const formatDateInput = (date: Date): string => {
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  };

  const getDefaultStrategyTestRange = () => {
    const end = scoreTradeDate ? scoreTradeDate.slice(0, 10) : formatDateInput(new Date());
    const endDate = new Date(`${end}T00:00:00`);
    endDate.setMonth(endDate.getMonth() - 1);
    return { startDate: formatDateInput(endDate), endDate: end };
  };

  const [strategyTestForm, setStrategyTestForm] = useState(() => getDefaultStrategyTestRange());

  const openStrategyTestDialog = () => {
    setStrategyTestError(null);
    setStrategyTestStrategyId('A_PRE_V2');
    setStrategyTestForm(getDefaultStrategyTestRange());
    setShowStrategyTestDialog(true);
  };

  useEffect(() => {
    if (strategyTestRequest > 0) openStrategyTestDialog();
    // The request counter is intentionally used as a one-way trigger from the drawer header.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategyTestRequest]);

  const closeStrategyTest = () => {
    setShowStrategyTestDialog(false);
    setStrategyTestRange(null);
    setStrategyScores([]);
    setActiveStrategyScore(null);
    strategyScoreMapRef.current = new Map();
    lastStrategyScoreDateRef.current = '';
  };

  const confirmStrategyTest = () => {
    if (!strategyTestForm.startDate || !strategyTestForm.endDate) {
      setStrategyTestError('请选择完整的测试时间范围');
      return;
    }
    if (strategyTestForm.startDate > strategyTestForm.endDate) {
      setStrategyTestError('开始日期不能晚于结束日期');
      return;
    }
    setStrategyTestError(null);
    setStrategyTestLoading(true);
    setStrategyScores([]);
    setActiveStrategyScore(null);
    setStrategyTestRange({ strategyId: strategyTestStrategyId, ...strategyTestForm });
    setShowStrategyTestDialog(false);
  };

  const copyStockText = async (value: string, label: string) => {
    await navigator.clipboard.writeText(value);
    setToastMsg(`已复制${label}：${value}`);
    window.setTimeout(() => setToastMsg(null), 1800);
  };

  useEffect(() => {
    if (!isOpen || !assetCode || !showAiPoolButton) {
      setInAiPool(false);
      return;
    }

    const controller = new AbortController();
    const checkInAiPool = async () => {
      try {
        const res = await fetch(`${apiHost}/api/watchlist/ai-pool`, { signal: controller.signal });
        if (!res.ok) throw new Error(`AI 分析池接口返回 HTTP ${res.status}`);
        const data = await res.json();
        if (!controller.signal.aborted) {
          setInAiPool(Array.isArray(data.codes) && data.codes.includes(assetCode));
        }
      } catch (e) {
        // 这是弹窗按钮的辅助状态。关闭或切换股票导致的取消不应成为控制台错误。
        if (controller.signal.aborted || (e instanceof DOMException && e.name === 'AbortError')) return;
        setInAiPool(false);
      }
    };
    void checkInAiPool();
    return () => controller.abort();
  }, [isOpen, assetCode, apiHost, showAiPoolButton]);

  const toggleAiPool = async () => {
    try {
      const res = await fetch(`${apiHost}/api/watchlist/ai-pool/toggle`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ asset_code: assetCode }) });
      if (!res.ok) throw new Error(`AI 分析池接口返回 HTTP ${res.status}`);
      const data = await res.json();
      setInAiPool(Boolean(data.in_pool));
      setToastMsg(data.in_pool ? '已加入 AI 分析池' : '已移出 AI 分析池');
      setTimeout(() => setToastMsg(null), 2000);
    } catch (e) {
      console.error('AI 分析池操作失败:', e);
      setToastMsg('AI 分析池操作失败，请重试');
    }
  };

  // Click Outside 闭合均线、划线工具及划线样式面板
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (maConfigRef.current && !maConfigRef.current.contains(event.target as Node)) {
        setShowMaConfig(false);
      }
      if (stylePanelRef.current && !stylePanelRef.current.contains(event.target as Node)) {
        setShowStylePanel(false);
      }
      if (drawingDropdownRef.current && !drawingDropdownRef.current.contains(event.target as Node)) {
        setShowDrawingDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // 副图指标状态 (MACD / KDJ / RSI)
  const [subIndicator, setSubIndicator] = useState<'MACD' | 'KDJ' | 'RSI' | null>(null);
  const currentSubIndicatorRef = useRef<'MACD' | 'KDJ' | 'RSI' | null>(null);

  const stateRef = useRef({ period, adjust, assetCode, apiHost });
  useEffect(() => {
    stateRef.current = { period, adjust, assetCode, apiHost };
  }, [period, adjust, assetCode, apiHost]);

  // 抽屉里的单股测试是一次性的；其他页面仍可通过 scoreStartDate/scoreTradeDate
  // 继续使用原有的自动评分标注。
  const effectiveScoreStartDate = strategyTestRange?.startDate || scoreStartDate;
  const effectiveScoreTradeDate = strategyTestRange?.endDate || scoreTradeDate;
  const effectiveScoreStrategyId = strategyTestRange?.strategyId || 'A_PRE_V2';

  // 静默自动保存划线函数
  const autoSaveDrawings = async () => {
    if (!chartRef.current) return;
    const overlays = chartRef.current.getOverlays();
    const drawingsData = overlays.filter((o) => !String(o.id || '').startsWith(SCORE_OVERLAY_ID_PREFIX)).map((o) => ({
      id: o.id,
      name: o.name,
      points: o.points,
      styles: o.styles,
    }));

    try {
      await fetch(`${stateRef.current.apiHost}/api/screening/drawings/${encodeURIComponent(toMarketDataAssetCode(stateRef.current.assetCode))}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ drawings: drawingsData }),
      });
    } catch (e) {
      console.error('自动保存划线失败', e);
    }
  };

  // 全局键盘监听：Esc 关闭弹窗，Space 加入/移出自选股，← / → 按列表顺序导航
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
        if (onSpaceToggleWatchlist) onSpaceToggleWatchlist();
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
                const scoreItem = strategyScoreMapRef.current.get(rawDate.replace(/-/g, ''));
                if (scoreItem && lastStrategyScoreDateRef.current !== rawDate) {
                  lastStrategyScoreDateRef.current = rawDate;
                  setActiveStrategyScore(scoreItem);
                }
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

    // 仅在 showSubIndicators 为 true 时创建副图指标
    if (showSubIndicators) {
      // 防止开发环境 StrictMode 或外部重挂载在同一 chart 实例上遗留副图。
      chart.getIndicators().filter((item) =>
        item.name === 'VOL' || item.name === 'MACD' || item.name === 'KDJ' || item.name === 'RSI'
      ).forEach((item) => chart.removeIndicator({ id: item.id }));
      chart.createIndicator({ name: 'VOL', paneId: VOLUME_PANE_ID }, false);
      if (subIndicator) {
        chart.createIndicator({ name: subIndicator, paneId: SUB_INDICATOR_PANE_ID }, false);
        currentSubIndicatorRef.current = subIndicator;
      }
    }

    // 3. 注册 DataLoader 异步载入数据
    chart.setDataLoader({
      getBars: async ({ callback }) => {
        const { period: currentPeriod, adjust: currentAdjust, assetCode: currentAsset, apiHost: currentApiHost } = stateRef.current;
        const marketDataAssetCode = toMarketDataAssetCode(currentAsset);
        setLoading(true);
        setError(null);
        try {
          const klineRes = await fetch(`${currentApiHost}/api/screening/kline/${encodeURIComponent(marketDataAssetCode)}?period=${currentPeriod}&adjust=${currentAdjust}`);
          if (!klineRes.ok) throw new Error('加载K线数据失败');
          const klineJson = await klineRes.json();
          const bars: KLineBar[] = klineJson.bars || [];

          if (bars.length === 0) {
            if (currentPeriod === '30min') {
              setError('该标的暂无可用的 30 分钟行情');
            } else {
              setError('暂无当前周期的 K线数据');
            }
          }

          if (bars.length > 0) {
            const historyRaw = window.localStorage.getItem('trade-plan:kline-view-history');
            let history: Record<string, number> = {};
            if (historyRaw) {
              try {
                const parsed = JSON.parse(historyRaw);
                if (parsed && typeof parsed === 'object') history = parsed;
              } catch {
                history = {};
              }
            }
            history[currentAsset.split('.')[0]] = Date.now();
            window.localStorage.setItem('trade-plan:kline-view-history', JSON.stringify(history));
          }

	          callback(bars);
	          // 复盘文章中的股票也必须默认定位到当前最新交易日，不能停留在
	          // 图表组件的历史默认视口（例如 7 月）。用户仍可手动向左回看。
	          requestAnimationFrame(() => {
	            if (chartRef.current === chart) {
	              chart.scrollToRealTime();
	            }
	          });

          // 还原划线
          const drawingsRes = await fetch(`${currentApiHost}/api/screening/drawings/${encodeURIComponent(marketDataAssetCode)}`);
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
	          if (tradeMarkers.length > 0) {
            const barsByDate = new Map(bars.map((bar) => [String(bar.trade_date).replace(/-/g, ''), bar]));
            tradeMarkers.forEach((marker, index) => {
              const bar = barsByDate.get(String(marker.date).slice(0, 10).replace(/-/g, ''));
              if (!bar) return;
              chart.createOverlay({
                id: `trade-marker-${index}-${String(marker.date).replace(/[^0-9]/g, '')}`,
                name: 'simpleAnnotation',
                extendData: marker.label,
                points: [{ timestamp: bar.timestamp, value: marker.price || bar.close }],
                styles: { text: { color: '#ffffff', backgroundColor: marker.color || '#0f5238', borderRadius: 4, paddingLeft: 5, paddingRight: 5, paddingTop: 2, paddingBottom: 2 } },
              });
            });
          }
	          if (currentPeriod === 'daily' && effectiveScoreTradeDate) {
	            const cleanEndDate = effectiveScoreTradeDate.replace(/-/g, '');
	            const cleanStartDate = (effectiveScoreStartDate || effectiveScoreTradeDate).replace(/-/g, '');
	            const scoreParams = new URLSearchParams({
	              ts_code: currentAsset,
	              start_date: cleanStartDate,
	              end_date: cleanEndDate,
	              strategy_id: effectiveScoreStrategyId,
	            });
	            const scoreRes = await fetch(`${currentApiHost}/api/strategy/single-stock/eval?${scoreParams.toString()}`);
	            if (scoreRes.ok) {
	              const scoreJson = await scoreRes.json();
	              const scores: StrategyScoreItem[] = Array.isArray(scoreJson.history) ? scoreJson.history : [];
	              strategyScoreMapRef.current = new Map(scores.map((score) => [String(score.trade_date).replace(/-/g, ''), score]));
	              lastStrategyScoreDateRef.current = '';
	              setStrategyScores(scores);
	              setActiveStrategyScore(scores.length > 0 ? scores[scores.length - 1] : null);
	              const barsByDate = new Map(bars.map((bar) => [normalizeTradeDate(bar.trade_date), bar]));
	              scores.forEach((score) => {
	                const preparationScore = score ? getDisplayedPreparationScore(score) : null;
	                if (!score || preparationScore === null) return;
	                const scoreBar = barsByDate.get(normalizeTradeDate(score.trade_date));
	                if (!scoreBar) return;
	                const lifecycle = score.turn_episode_state || score.state;
	                const colorInfo = getLifecycleColor(lifecycle);
	                chart.createOverlay({
	                  id: `${SCORE_OVERLAY_ID_PREFIX}${score.trade_date}`,
	                  name: 'simpleAnnotation',
	                  extendData: `${preparationScore.toFixed(1)}${score.second_opportunity?.active ? ' ★' : ''}`,
	                  points: [{ timestamp: scoreBar.timestamp, value: scoreBar.high }],
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
	              });
	              setStrategyTestLoading(false);
	            } else if (strategyTestRange) {
	              setStrategyTestLoading(false);
	              throw new Error(`单股测试接口返回 HTTP ${scoreRes.status}`);
	            }
	          } else if (strategyTestRange) {
	            setStrategyTestLoading(false);
	          }
	        } catch (err: any) {
          setError(err.message || '加载图表失败');
        } finally {
          setLoading(false);
          if (strategyTestRange) setStrategyTestLoading(false);
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
  }, [isOpen, assetCode, period, adjust, effectiveScoreStartDate, effectiveScoreTradeDate, effectiveScoreStrategyId, tradeMarkers, strategyTestRange]);

  // 切换副图指标 (MACD / KDJ / RSI)
  const handleChangeSubIndicator = (newIndicator: 'MACD' | 'KDJ' | 'RSI') => {
    if (!chartRef.current) return;
    // 只操作固定的副图 pane，避免按名称删除/创建时留下重复指标实例。
    chartRef.current.removeIndicator({ paneId: SUB_INDICATOR_PANE_ID });
    if (newIndicator === subIndicator) {
      currentSubIndicatorRef.current = null;
      setSubIndicator(null);
      return;
    }
    chartRef.current.createIndicator({ name: newIndicator, paneId: SUB_INDICATOR_PANE_ID }, false);
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

  const handleChartClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!onPickPrice || activeTool || !chartRef.current || !chartContainerRef.current) return;
    const rect = chartContainerRef.current.getBoundingClientRect();
    const point = chartRef.current.convertFromPixel(
      [{ x: event.clientX - rect.left, y: event.clientY - rect.top }],
      { paneId: 'candle_pane' },
    );
    const value = Array.isArray(point) ? point[0]?.value : point.value;
    if (typeof value === 'number' && Number.isFinite(value)) onPickPrice(Number(value.toFixed(2)));
  };

  if (!isOpen) return null;

  const chartPanel = (
    <>
      {/* Toast 提示 */}
      {toastMsg && (
        <div className="absolute top-6 left-1/2 -translate-x-1/2 z-50 bg-[#2e3230] text-white px-4 py-2 rounded-xl text-xs font-bold shadow-2xl flex items-center gap-2 border border-purple-400/40 animate-bounce">
          <Star className="w-4 h-4 text-purple-400 fill-purple-400" />
          <span>{toastMsg}</span>
        </div>
      )}
      <div className={`relative flex min-h-0 flex-col overflow-hidden bg-white ${embedded ? 'h-full w-full' : 'h-[94vh] w-[96vw] max-w-[1500px] rounded-xl border border-slate-200 shadow-2xl'}`}>
        {/* 全局单行工具栏 (Single Header Bar, 严格单行不换行 flex-nowrap) */}
        <div className="relative z-20 flex flex-nowrap items-center justify-between px-3 py-1.5 border-b border-slate-200 bg-slate-50 shrink-0 gap-1.5 h-12 text-xs overflow-visible">
          {/* 左区：标的信息、上一只/下一只、周期/复权控制 */}
          <div className="flex items-center gap-1 shrink-0">
            {!embedded && <LineChart className="w-4 h-4 text-emerald-600 mr-0.5" />}

            {/* 上一只/下一只导航按钮 */}
            {showNavigation && (
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
            )}

            {(showAssetInfo || embedded) && (
              <h3 className="mr-1 flex items-center gap-1.5 whitespace-nowrap font-bold text-slate-800 text-sm">
                <button type="button" onClick={() => void copyStockText(assetName, '股票名称')} title="点击复制股票名称" className="hover:underline">{assetName}</button>
                <button type="button" onClick={() => void copyStockText(assetCode, '股票代码')} title="点击复制股票代码" className="text-xs font-normal text-slate-500 hover:underline">({assetCode})</button>
                {displayIndustry && (
                  <span className="ml-1 px-2 py-0.5 rounded bg-emerald-50 text-[#4a7c59] text-xs font-bold border border-[#4a7c59]/30">
                    {displayIndustry}
                  </span>
                )}
              </h3>
            )}

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

            {/* AI 分析池按钮 */}
            {showAiPoolButton && (
              <button
                onClick={toggleAiPool}
                className={`px-2.5 py-1 text-xs font-bold rounded-md transition flex items-center gap-1 shadow-xs ${
                  inAiPool
                    ? 'bg-purple-600 text-white hover:bg-purple-700'
                    : 'bg-white text-purple-700 hover:bg-purple-50 border border-purple-300'
                }`}
              title="加入/移出 AI 分析池"
              >
                <Star className={`w-3.5 h-3.5 ${inAiPool ? 'fill-white text-white' : 'text-purple-600'}`} />
                <span>{inAiPool ? '✓ AI' : '+ AI'}</span>
              </button>
            )}

            {/* 自选股按钮 */}
            {showWatchlistButton && (
              <button
                onClick={handleToggleWatchlist}
                className={`px-2.5 py-1 text-xs font-bold rounded-md transition flex items-center gap-1 shadow-xs ${
                  inWatchlist
                    ? 'bg-amber-500 text-white hover:bg-amber-600'
                    : 'bg-white text-amber-700 hover:bg-amber-50 border border-amber-300'
                }`}
                title="加入/移出自选股 (PostgreSQL 存储)"
              >
                <Star className={`w-3.5 h-3.5 ${inWatchlist ? 'fill-white text-white' : 'text-amber-500'}`} />
                <span>{inWatchlist ? '✓ 自选' : '+ 自选'}</span>
              </button>
            )}

            {/* 入候选池按钮 */}
            {onToggleSelect && (
              <button
                onClick={onToggleSelect}
                className={`px-2.5 py-1 text-xs font-bold rounded-md transition flex items-center gap-1 shadow-xs ${
                  isSelected
                    ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                    : 'bg-white text-slate-700 hover:bg-emerald-50 hover:text-emerald-700 border border-slate-300'
                }`}
                title="入候选池 / 取消入池"
              >
                <Star className={`w-3.5 h-3.5 ${isSelected ? 'fill-white text-white' : 'text-emerald-500'}`} />
                <span>{isSelected ? '✓ 候选' : '+ 候选'}</span>
              </button>
            )}

            {/* 快捷缩放控制按钮组 */}
            <div className="flex bg-slate-200/80 p-0.5 rounded items-center gap-0.5">
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
            <div ref={maConfigRef} className="relative">
              <button
                onClick={() => setShowMaConfig(!showMaConfig)}
                className="inline-flex items-center gap-1 bg-white hover:bg-slate-100 border border-slate-200 text-slate-700 font-bold px-2.5 py-0.5 rounded text-xs transition"
                title="自定义 MA 均线天数与颜色"
              >
                <span>均线</span>
                <Settings className="w-3.5 h-3.5 text-slate-500 hover:text-emerald-600" />
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

          {/* 右区：划线多样式控制 + 下拉图标工具 + 单线/全清删除 + 关闭 */}
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

            {/* 划线工具下拉选择 + 删除操作 */}
            <div className="flex items-center gap-1">
              <div ref={drawingDropdownRef} className="relative">
                <button
                  onClick={() => setShowDrawingDropdown(!showDrawingDropdown)}
                  className={`px-2.5 py-1 text-xs font-bold rounded-md transition flex items-center gap-1 border shadow-xs ${
                    activeTool
                      ? 'bg-emerald-600 text-white border-emerald-600'
                      : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-100 hover:text-emerald-700'
                  }`}
                  title="选择划线工具"
                  aria-label="选择划线工具"
                >
                  {(() => {
                    const activeObj = DRAWING_TOOLS.find((t) => t.key === activeTool);
                    const ToolIcon = activeObj ? activeObj.icon : Slash;
                    return (
                      <>
                        <ToolIcon className="w-3.5 h-3.5" />
                        <ChevronDown className="w-3 h-3 opacity-70" />
                      </>
                    );
                  })()}
                </button>

                {showDrawingDropdown && (
                  <div className="absolute top-8 right-0 z-30 w-36 p-1 bg-white rounded-lg shadow-xl border border-slate-200 space-y-0.5 text-xs select-none">
                    <div className="px-2 py-1 text-[10px] font-bold text-slate-400 border-b border-slate-100 mb-0.5">
                      画线工具菜单
                    </div>
                    {DRAWING_TOOLS.map((tool) => {
                      const IconComponent = tool.icon;
                      const isActive = activeTool === tool.key;
                      return (
                        <button
                          key={tool.key}
                          onClick={() => {
                            handleSelectTool(tool.key);
                            setShowDrawingDropdown(false);
                          }}
                          className={`w-full px-2 py-1.5 flex items-center gap-2 text-left rounded transition font-bold ${
                            isActive
                              ? 'bg-emerald-50 text-emerald-700'
                              : 'text-slate-700 hover:bg-slate-100'
                          }`}
                        >
                          <IconComponent className={`w-3.5 h-3.5 ${isActive ? 'text-emerald-600' : 'text-slate-500'}`} />
                          <span>{tool.label}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* 删除选中线段 */}
              <button
                onClick={handleRemoveSingleDrawing}
                title="删除当前选中的线 (也可按 Delete/Backspace 键)"
                className="p-1 text-amber-700 bg-amber-50 hover:bg-amber-100 border border-amber-200 rounded transition"
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

            {/* 纯图标右上角关闭按钮 (支持点击或 Esc 键) */}
            {!embedded && (
              <button
                onClick={onClose}
                title="关闭窗口 (快捷键: Esc)"
                className="p-1.5 bg-slate-100 hover:bg-rose-600 hover:text-white border border-slate-200 text-slate-600 rounded-lg transition shadow-xs flex items-center justify-center ml-2"
              >
                <X className="w-4 h-4 stroke-[2.5]" />
              </button>
            )}
          </div>
        </div>

        {/* 主图表容器 */}
          <div className="relative min-h-0 flex-1 bg-white w-full h-full overflow-hidden">
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
          {strategyTestRange && activeStrategyScore && period === 'daily' && (
            <div className="pointer-events-auto absolute left-3 top-3 z-20 w-72 rounded-xl border border-[#c4c8bc]/80 bg-white/95 p-3 text-xs shadow-lg backdrop-blur-xs">
              <div className="mb-2 flex items-center justify-between border-b border-[#c4c8bc]/40 pb-1.5">
                <div className="flex items-center gap-1.5 font-bold text-[#2e3230]">
                  <TestTube2 className="h-3.5 w-3.5 text-[#4a7c59]" />
                  <span>单股测试</span>
                </div>
                <button
                  type="button"
                  onClick={closeStrategyTest}
                  className="rounded p-0.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
                  title="关闭单股测试标注"
                  aria-label="关闭单股测试标注"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono font-bold text-slate-600">
                  {String(activeStrategyScore.trade_date).replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3')}
                </span>
                <span className="rounded bg-[#4a7c59] px-1.5 py-0.5 font-mono text-sm font-black text-white">
                  {getDisplayedPreparationScore(activeStrategyScore)?.toFixed(1) ?? '—'}分
                </span>
              </div>
              <div className="mt-1 text-[10px] font-bold text-slate-500">
                {activeStrategyScore.turn_episode_state || activeStrategyScore.state || '未分类'} · 底部准备度 · 移动十字光标查看其他交易日
              </div>
              {activeStrategyScore.turn_episode_state === 'FIRST_TURN_WINDOW' && typeof activeStrategyScore.turn_score === 'number' && (
                <div className="mt-1 text-[10px] font-bold text-slate-500">转强评分 {activeStrategyScore.turn_score.toFixed(1)}分</div>
              )}
              <div className="mt-2 max-h-20 space-y-1 overflow-y-auto text-[11px] leading-snug text-[#4a4e4a]">
                {activeStrategyScore.reasons_json && activeStrategyScore.reasons_json.length > 0 ? (
                  activeStrategyScore.reasons_json.slice(0, 3).map((reason, index) => (
                    <div key={`${reason.type || 'reason'}-${index}`} className="rounded border border-[#c4c8bc]/30 bg-[#faf6f0] px-2 py-1">
                      • {reason.msg || '暂无说明'}
                    </div>
                  ))
                ) : (
                  <div className="text-slate-400">暂无详细诊断说明</div>
                )}
              </div>
            </div>
          )}
          <div
            ref={chartContainerRef}
            style={{ width: '100%', height: '100%' }}
            className={`h-full min-h-0 ${onPickPrice ? 'cursor-crosshair' : ''}`}
            onClick={handleChartClick}
          />
          {planPriceLines && <div className="plan-chart-price-layer" aria-label="交易计划价格标记">{planLineLayout.map((line) => <React.Fragment key={line.key}>{line.direction === 0 && <div className="plan-chart-price-line" style={{ top: line.y, borderColor: line.color }} />}<span className="plan-chart-price-label" title={`${line.title} ¥${line.value.toFixed(2)}${line.direction < 0 ? '（高于当前可见范围）' : line.direction > 0 ? '（低于当前可见范围）' : ''}`} style={{ top: line.labelY, backgroundColor: line.color }}>{line.direction < 0 ? '↑ ' : line.direction > 0 ? '↓ ' : ''}{line.label} {line.value.toFixed(2)}</span></React.Fragment>)}</div>}
        </div>
      </div>
      {showStrategyTestDialog && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/25 px-4" onMouseDown={(event) => event.stopPropagation()}>
          <div className="w-full max-w-md rounded-xl border border-[#c4c8bc] bg-white p-4 shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h3 className="flex items-center gap-2 text-base font-black text-[#2e3230]">
                  <TestTube2 className="h-4 w-4 text-[#4a7c59]" />
                  单股测试
                </h3>
                <p className="mt-1 text-xs font-bold text-slate-500">临时计算 {assetName} 的历史策略得分，不会保存测试结果。</p>
              </div>
              <button type="button" onClick={() => setShowStrategyTestDialog(false)} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="关闭单股测试设置">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-3 text-xs">
              <label className="block">
                <span className="mb-1 block font-bold text-[#2e3230]">选股策略</span>
                <select value={strategyTestStrategyId} onChange={(event) => setStrategyTestStrategyId(event.target.value)} className="w-full rounded-md border border-[#c4c8bc] bg-[#faf6f0] px-3 py-2 font-bold text-[#2e3230] outline-none">
                  <option value="A_PRE_V2">A-Pre V2 早期转强</option>
                </select>
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="mb-1 block font-bold text-[#2e3230]">开始日期</span>
                  <input type="date" value={strategyTestForm.startDate} onChange={(event) => setStrategyTestForm((form) => ({ ...form, startDate: event.target.value }))} className="w-full rounded-md border border-[#c4c8bc] bg-[#faf6f0] px-3 py-2 font-mono font-bold text-[#2e3230] outline-none" />
                </label>
                <label className="block">
                  <span className="mb-1 block font-bold text-[#2e3230]">结束日期</span>
                  <input type="date" value={strategyTestForm.endDate} onChange={(event) => setStrategyTestForm((form) => ({ ...form, endDate: event.target.value }))} className="w-full rounded-md border border-[#c4c8bc] bg-[#faf6f0] px-3 py-2 font-mono font-bold text-[#2e3230] outline-none" />
                </label>
              </div>
              {strategyTestError && <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 font-bold text-rose-800">{strategyTestError}</div>}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={() => setShowStrategyTestDialog(false)} className="rounded-md border border-slate-300 px-3 py-2 font-bold text-slate-600 hover:bg-slate-50">取消</button>
                <button type="button" onClick={confirmStrategyTest} disabled={strategyTestLoading} className="inline-flex items-center gap-1.5 rounded-md bg-[#4a7c59] px-3 py-2 font-bold text-white hover:bg-[#3b6447] disabled:opacity-60">
                  {strategyTestLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  开始计算
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );

  if (embedded) {
    return <div className="relative flex h-full min-h-0 w-full">{chartPanel}</div>;
  }

  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-3 backdrop-blur-xs">{chartPanel}</div>;
}
