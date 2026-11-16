'use client';

import { useEffect, useState } from 'react';
import { History, X, Clock, Database, CheckCircle2, ChevronRight, Loader2, FileText, Filter } from 'lucide-react';

type ScreeningRunItem = {
  run_id: string;
  trade_date: string;
  run_name?: string;
  notes?: string;
  universe_type?: string;
  universe_params_json?: Record<string, any>;
  data_freshness_json?: Record<string, any>;
  started_at: string;
  finished_at?: string;
  status: string;
  summary_json?: Record<string, any>;
};

const API = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL ?? '';

export default function RunHistoryModal({
  isOpen,
  onClose,
  onSelectRun,
}: {
  isOpen: boolean;
  onClose: () => void;
  onSelectRun: (runId: string) => void;
}) {
  const [runs, setRuns] = useState<ScreeningRunItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      fetch(`${API}/api/screening/runs/history?limit=30`)
        .then((res) => res.json())
        .then((data) => {
          setRuns(data.items || []);
        })
        .catch((err) => console.error('Failed to fetch runs history:', err))
        .finally(() => setLoading(false));
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-end bg-black/40 backdrop-blur-xs">
      <div className="h-full w-full max-w-2xl bg-white p-6 shadow-2xl space-y-4 overflow-y-auto border-l border-[#c4c8bc]/60">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#c4c8bc]/30 pb-3">
          <div className="flex items-center gap-2 text-sm font-bold text-[#2e3230]">
            <History className="h-5 w-5 text-[#4a7c59]" />
            <span>选股任务历史归档看板</span>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-[#686d68] hover:bg-[#e4e0d8] hover:text-[#2e3230]">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Loading */}
        {loading ? (
          <div className="py-12 flex justify-center items-center gap-2 text-xs text-[#686d68]">
            <Loader2 className="h-4 w-4 animate-spin text-[#4a7c59]" />
            读取历史选股任务记录...
          </div>
        ) : runs.length === 0 ? (
          <div className="py-12 text-center text-xs text-[#686d68]">
            暂无历史选股任务归档。
          </div>
        ) : (
          <div className="space-y-3">
            {runs.map((run) => {
              const summary = run.summary_json || {};
              const freshness = run.data_freshness_json || {};
              const isDone = run.status === 'DONE';

              return (
                <div
                  key={run.run_id}
                  onClick={() => {
                    if (isDone) {
                      onSelectRun(run.run_id);
                      onClose();
                    }
                  }}
                  className={`group rounded-xl border p-4 transition text-xs space-y-2.5 ${
                    isDone
                      ? 'border-[#c4c8bc]/50 bg-[#faf6f0]/70 hover:border-[#4a7c59] hover:bg-white hover:shadow-md cursor-pointer'
                      : 'border-red-200 bg-red-50/30'
                  }`}
                >
                  {/* Title & Status */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-sm text-[#2e3230] group-hover:text-[#4a7c59]">
                        {run.run_name || `${run.trade_date} 选股任务`}
                      </span>
                      <span className="font-mono text-[11px] text-[#686d68] bg-[#e4e0d8] px-1.5 py-0.5 rounded">
                        {run.run_id}
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded-md px-2 py-0.5 text-[10px] font-bold ${
                          isDone ? 'bg-[#4a7c59]/15 text-[#4a7c59]' : 'bg-red-100 text-red-700'
                        }`}
                      >
                        {run.status}
                      </span>
                      <ChevronRight className="h-4 w-4 text-[#686d68] group-hover:text-[#4a7c59] transition-transform group-hover:translate-x-0.5" />
                    </div>
                  </div>

                  {/* Notes & Scope */}
                  <div className="flex flex-wrap items-center gap-3 text-[#686d68]">
                    <span>交易日: <strong className="text-[#2e3230]">{run.trade_date}</strong></span>
                    <span>运行时间: {run.started_at ? run.started_at.substring(0, 19).replace('T', ' ') : '未知'}</span>
                    <span>
                      范围: <span className="font-bold text-[#705c30]">
                        {run.universe_type === 'INDUSTRIES' ? '🏢 限定行业' : run.universe_type === 'CUSTOM_CODES' ? '🔍 单股/多股诊断' : '🌐 全市场'}
                      </span>
                    </span>
                  </div>

                  {run.notes && (
                    <p className="text-[11px] text-[#4a4e4a] bg-white/60 p-1.5 rounded border border-[#c4c8bc]/30">
                      <span className="font-bold text-[#686d68] mr-1">备注:</span>
                      {run.notes}
                    </p>
                  )}

                  {/* Data Freshness Indicator */}
                  <div className="flex items-center gap-4 text-[10px] text-[#686d68] bg-[#e4e0d8]/40 px-2.5 py-1 rounded">
                    <span>行情数据至: <strong className="text-[#2e3230]">{freshness.daily_market_date || run.trade_date}</strong></span>
                    <span>财报数据至: <strong className="text-[#2e3230]">{freshness.financial_data_quarter || '2026Q2'}</strong></span>
                  </div>

                  {/* Stage Funnel Summary Breakdown Badges */}
                  {isDone && summary.l0_count != null && (
                    <div className="flex flex-wrap items-center gap-1.5 pt-1 text-[11px] border-t border-[#c4c8bc]/20">
                      <span className="rounded bg-[#2e3230] text-white px-2 py-0.5 font-bold">L0: {summary.l0_count}</span>
                      <span className="text-[#c4c8bc]">➔</span>
                      <span className="rounded bg-[#4a7c59]/10 text-[#4a7c59] px-2 py-0.5 font-bold">L1: {summary.l1_pass}</span>
                      <span className="text-[#c4c8bc]">➔</span>
                      <span className="rounded bg-[#4a7c59]/10 text-[#4a7c59] px-2 py-0.5 font-bold">L2: {summary.l2_pass}</span>
                      <span className="text-[#c4c8bc]">➔</span>
                      <span className="rounded bg-[#4a7c59]/10 text-[#4a7c59] px-2 py-0.5 font-bold">L3: {summary.l3_pass}</span>
                      <span className="text-[#c4c8bc]">➔</span>
                      <span className="rounded bg-[#4a7c59]/10 text-[#4a7c59] px-2 py-0.5 font-bold">L4: {summary.l4_pass}</span>
                      <span className="text-[#c4c8bc]">➔</span>
                      <span className="rounded bg-[#705c30] text-white px-2 py-0.5 font-bold">L5: {summary.l5_pass}</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
