'use client';

import { useState } from 'react';
import { PlayCircle, X, Layers, Filter, FileText, CheckCircle, Database } from 'lucide-react';

type UniverseType = 'ALL' | 'INDUSTRIES' | 'CUSTOM_CODES';

export default function RunScreeningModal({
  isOpen,
  onClose,
  onStartRun,
  tradeDate,
  freshnessInfo,
}: {
  isOpen: boolean;
  onClose: () => void;
  onStartRun: (params: {
    run_name: string;
    notes: string;
    universe_type: UniverseType;
    universe_params: Record<string, any>;
  }) => void;
  tradeDate?: string;
  freshnessInfo?: {
    daily_market_date?: string;
    financial_data_quarter?: string;
  };
}) {
  const [runName, setRunName] = useState(`${tradeDate || ''} 二次筛选任务`);
  const [notes, setNotes] = useState('');
  const [universeType, setUniverseType] = useState<UniverseType>('ALL');
  const [selectedIndustries, setSelectedIndustries] = useState<string>('');
  const [customCodes, setCustomCodes] = useState<string>('');

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const universe_params: Record<string, any> = {};
    if (universeType === 'INDUSTRIES') {
      universe_params.industries = selectedIndustries
        .split(/[,，\s]+/)
        .map((s) => s.trim())
        .filter(Boolean);
    } else if (universeType === 'CUSTOM_CODES') {
      universe_params.codes = customCodes
        .split(/[,，\s]+/)
        .map((s) => s.trim())
        .filter(Boolean);
    }

    onStartRun({
      run_name: runName.trim() || `${tradeDate || ''} 二次筛选任务`,
      notes: notes.trim(),
      universe_type: universeType,
      universe_params,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs">
      <div className="w-full max-w-lg rounded-2xl border border-[#c4c8bc]/60 bg-white p-6 shadow-2xl space-y-5">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-[#c4c8bc]/30 pb-3">
          <div className="flex items-center gap-2 text-sm font-bold text-[#2e3230]">
            <PlayCircle className="h-5 w-5 text-[#4a7c59]" />
            <span>配置并启动二次筛选任务</span>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-[#686d68] hover:bg-[#e4e0d8] hover:text-[#2e3230]">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Freshness Status Banner */}
        <div className="flex items-center justify-between rounded-xl bg-[#faf6f0] px-3.5 py-2.5 text-xs border border-[#c4c8bc]/40">
          <div className="flex items-center gap-1.5 font-bold text-[#705c30]">
            <Database className="h-4 w-4 text-[#705c30]" />
            <span>数据更新状态:</span>
          </div>
          <div className="flex items-center gap-3 text-[11px] text-[#4a4e4a]">
            <span>行情至: <strong className="text-[#2e3230]">{freshnessInfo?.daily_market_date || tradeDate || '最新'}</strong></span>
            <span>财报至: <strong className="text-[#2e3230]">{freshnessInfo?.financial_data_quarter || '2026Q2'}</strong></span>
          </div>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="space-y-4 text-xs">
          {/* Task Name */}
          <div>
            <label className="block font-bold text-[#2e3230] mb-1">选股任务名称</label>
            <input
              type="text"
              value={runName}
              onChange={(e) => setRunName(e.target.value)}
              placeholder="例如: 20260810-第1周精选"
              className="w-full rounded-lg border border-[#c4c8bc]/60 bg-[#faf6f0] px-3 py-2 outline-none text-[#2e3230] focus:border-[#4a7c59]"
            />
          </div>

          {/* Universe Target Scope */}
          <div>
            <label className="block font-bold text-[#2e3230] mb-1.5">评估目标范围 (Universe)</label>
            <div className="grid grid-cols-3 gap-2">
              <button
                type="button"
                onClick={() => setUniverseType('ALL')}
                className={`rounded-lg border px-3 py-2 font-bold text-center transition ${
                  universeType === 'ALL'
                    ? 'border-[#4a7c59] bg-[#4a7c59] text-white shadow-xs'
                    : 'border-[#c4c8bc]/50 bg-[#faf6f0] text-[#4a4e4a] hover:bg-[#e4e0d8]'
                }`}
              >
                🌐 全市场范围
              </button>

              <button
                type="button"
                onClick={() => setUniverseType('INDUSTRIES')}
                className={`rounded-lg border px-3 py-2 font-bold text-center transition ${
                  universeType === 'INDUSTRIES'
                    ? 'border-[#4a7c59] bg-[#4a7c59] text-white shadow-xs'
                    : 'border-[#c4c8bc]/50 bg-[#faf6f0] text-[#4a4e4a] hover:bg-[#e4e0d8]'
                }`}
              >
                🏢 限定行业
              </button>

              <button
                type="button"
                onClick={() => setUniverseType('CUSTOM_CODES')}
                className={`rounded-lg border px-3 py-2 font-bold text-center transition ${
                  universeType === 'CUSTOM_CODES'
                    ? 'border-[#4a7c59] bg-[#4a7c59] text-white shadow-xs'
                    : 'border-[#c4c8bc]/50 bg-[#faf6f0] text-[#4a4e4a] hover:bg-[#e4e0d8]'
                }`}
              >
                🔍 单股/多股诊断
              </button>
            </div>

            {/* Scope Inputs */}
            {universeType === 'INDUSTRIES' && (
              <div className="mt-2.5 space-y-1">
                <input
                  type="text"
                  value={selectedIndustries}
                  onChange={(e) => setSelectedIndustries(e.target.value)}
                  placeholder="输入申万行业名称，多个用逗号隔开 (如: 医药生物, 半导体)"
                  className="w-full rounded-lg border border-[#c4c8bc]/60 bg-white px-3 py-2 outline-none text-[#2e3230]"
                />
                <p className="text-[10px] text-[#686d68]">仅对这些行业内的股票执行 L0~L5 六层评级</p>
              </div>
            )}

            {universeType === 'CUSTOM_CODES' && (
              <div className="mt-2.5 space-y-1">
                <textarea
                  value={customCodes}
                  onChange={(e) => setCustomCodes(e.target.value)}
                  rows={2}
                  placeholder="粘贴股票代码，用逗号或换行隔开 (如: 600519.SH, 000001.SZ)"
                  className="w-full rounded-lg border border-[#c4c8bc]/60 bg-white px-3 py-2 outline-none text-[#2e3230]"
                />
                <p className="text-[10px] text-[#686d68]">专门针对这几只股票排查各层淘汰原因与算子得分</p>
              </div>
            )}
          </div>

          {/* Notes */}
          <div>
            <label className="block font-bold text-[#2e3230] mb-1">任务备注说明 (选填)</label>
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="例如: 重点排查动能突破股票"
              className="w-full rounded-lg border border-[#c4c8bc]/60 bg-[#faf6f0] px-3 py-2 outline-none text-[#2e3230]"
            />
          </div>

          {/* Modal Actions */}
          <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#c4c8bc]/30">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[#c4c8bc]/60 bg-white px-4 py-2 font-bold text-[#4a4e4a] hover:bg-[#e4e0d8]"
            >
              取消
            </button>
            <button
              type="submit"
              className="inline-flex items-center gap-1.5 rounded-lg bg-[#4a7c59] px-5 py-2 font-bold text-white shadow-xs hover:bg-[#3b6447]"
            >
              <CheckCircle className="h-4 w-4" />
              启动选股计算
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
