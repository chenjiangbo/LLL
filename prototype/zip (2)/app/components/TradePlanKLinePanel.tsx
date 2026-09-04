'use client';

import { useEffect, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import { init, dispose, Chart, Nullable } from 'klinecharts';

type PickField = 'reference_entry_price' | 'max_acceptable_entry_price' | 'risk_reference_price' | 'target_price';
type Bar = { timestamp: number; open: number; high: number; low: number; close: number; volume: number; turnover: number };

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;
export default function TradePlanKLinePanel({
  assetCode,
  activeField,
  onPickPrice,
}: {
  assetCode: string;
  activeField: PickField;
  onPickPrice: (field: PickField, price: number) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Nullable<Chart>>(null);
  const [hoverPrice, setHoverPrice] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current || !assetCode) return;
    if (!API_BASE) {
      setError('NEXT_PUBLIC_MARKET_REVIEW_API_URL 未配置');
      return;
    }
    const chart = init(containerRef.current, {
      styles: {
        grid: { show: true, horizontal: { color: '#eee8dc' }, vertical: { color: '#f3eee5' } },
        crosshair: { show: true, horizontal: { show: true }, vertical: { show: true } },
      },
    });
    if (!chart) {
      setError('K 线组件初始化失败');
      return;
    }
    chartRef.current = chart;
    chart.setDataLoader({
      getBars: async ({ callback }) => {
        try {
          setError(null);
          const response = await fetch(`${API_BASE}/api/screening/kline/${encodeURIComponent(assetCode)}?period=daily&adjust=qfq`);
          if (!response.ok) throw new Error('K 线数据加载失败');
          const data = await response.json();
          const bars: Bar[] = data.bars || [];
          if (!bars.length) throw new Error('暂无该股票的日线数据');
          const historyKey = assetCode.split('.')[0];
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
          history[historyKey] = Date.now();
          window.localStorage.setItem('trade-plan:kline-view-history', JSON.stringify(history));
          callback(bars);
          requestAnimationFrame(() => chart.scrollToRealTime());
        } catch (cause) {
          setError(cause instanceof Error ? cause.message : 'K 线数据加载失败');
        }
      },
    });
    chart.setSymbol({ ticker: assetCode, pricePrecision: 2, volumePrecision: 0 });
    chart.setPeriod({ type: 'day', span: 1 });
    chart.createIndicator({ name: 'MA', paneId: 'candle_pane', calcParams: [5, 10, 20, 60] }, true);
    chart.createIndicator({ name: 'VOL', paneId: 'trade-plan-volume' }, false);
    const onResize = () => chart.resize();
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      if (containerRef.current) dispose(containerRef.current);
      chartRef.current = null;
    };
  }, [assetCode]);

  const priceAtEvent = (event: MouseEvent<HTMLDivElement>) => {
    if (!chartRef.current || !containerRef.current) return null;
    const rect = containerRef.current.getBoundingClientRect();
    const point = chartRef.current.convertFromPixel([{ x: event.clientX - rect.left, y: event.clientY - rect.top }], { paneId: 'candle_pane' });
    const value = Array.isArray(point) ? point[0]?.value : point.value;
    return typeof value === 'number' && Number.isFinite(value) ? Number(value.toFixed(2)) : null;
  };

  return <div className="relative h-[680px] overflow-hidden">
    {hoverPrice !== null && <span className="pointer-events-none absolute right-3 top-3 z-10 rounded bg-white/90 px-2 py-1 font-mono text-sm font-bold text-[#2e3230] shadow-sm">¥{hoverPrice.toFixed(2)}</span>}
    <div ref={containerRef} className="h-full w-full cursor-crosshair" onMouseMove={(event) => setHoverPrice(priceAtEvent(event))} onMouseLeave={() => setHoverPrice(null)} onClick={(event) => { const price = priceAtEvent(event); if (price !== null) onPickPrice(activeField, price); }} />
    {error && <div className="absolute inset-0 flex items-center justify-center bg-white/90 text-sm font-bold text-rose-700">{error}</div>}
  </div>;
}
