'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { Target, CheckCircle2, AlertCircle, RefreshCw, Plus, ArrowRight, Loader2, Sparkles, HelpCircle } from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL || 'http://127.0.0.1:18080';

interface PositiveSampleItem {
  sample_id?: number;
  ts_code: string;
  target_date: string;
  sample_name: string;
  note?: string;
  total_score?: number;
  state?: string;
  hit?: boolean;
  score_detail_json?: Record<string, any>;
  reasons_json?: Array<{ type: string; msg: string }>;
}

export default function SampleValidationView({
  onClose,
}: {
  onClose?: () => void;
}) {
  const [samples, setSamples] = useState<PositiveSampleItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [validating, setValidating] = useState(false);

  // New Sample Form
  const [newTsCode, setNewTsCode] = useState('');
  const [newTargetDate, setNewTargetDate] = useState('20260807');
  const [newSampleName, setNewSampleName] = useState('');
  const [newNote, setNewNote] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);

  // Fetch positive samples & validation
  const runValidation = useCallback(async () => {
    setValidating(true);
    try {
      const res = await fetch(`${API_BASE}/api/early-turn/samples/validate`);
      if (res.ok) {
        const json = await res.json();
        setSamples(json.items || []);
      }
    } catch (e) {
      console.error('Failed to validate positive samples:', e);
    } finally {
      setValidating(false);
    }
  }, []);

  useEffect(() => {
    runValidation();
  }, [runValidation]);

  const handleAddSample = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTsCode.trim() || !newSampleName.trim()) return;

    try {
      const res = await fetch(`${API_BASE}/api/early-turn/samples`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ts_code: newTsCode.trim().toUpperCase(),
          target_date: newTargetDate.trim(),
          sample_name: newSampleName.trim(),
          note: newNote.trim(),
        }),
      });
      if (res.ok) {
        setShowAddForm(false);
        setNewTsCode('');
        setNewSampleName('');
        setNewNote('');
        runValidation();
      }
    } catch (e) {
      console.error('Failed to add positive sample:', e);
    }
  };

  const hitCount = samples.filter((s) => s.hit).length;

  return (
    <div className="space-y-4">
      {/* 顶栏控制 */}
      <div className="bg-white p-4 rounded-xl border border-[#c4c8bc]/60 shadow-xs flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Target className="h-5 w-5 text-[#705c30]" />
          <div>
            <h3 className="font-bold text-sm text-[#2e3230]">A-Pre V2 正负样本回归校验看板</h3>
            <p className="text-[11px] text-[#686d68]">
              验证策略改动对京投发展等 6 大标志性正样本的红箭头命中率与首次入选时间
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAddForm(!showAddForm)}
            className="inline-flex items-center gap-1.5 bg-[#faf6f0] hover:bg-[#e4e0d8] text-[#2e3230] border border-[#c4c8bc]/60 px-3 py-1.5 rounded-lg font-bold text-xs transition"
          >
            <Plus className="h-4 w-4" />
            <span>添加测试正样本</span>
          </button>

          <button
            onClick={runValidation}
            disabled={validating}
            className="inline-flex items-center gap-1.5 bg-[#4a7c59] hover:bg-[#3b6447] text-white px-4 py-1.5 rounded-lg font-bold text-xs shadow-xs transition disabled:opacity-50"
          >
            {validating ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            <span>{validating ? '重新校验中...' : '运行样本回归测试'}</span>
          </button>

          {onClose && (
            <button
              onClick={onClose}
              className="px-3 py-1.5 bg-white border border-[#c4c8bc]/60 text-[#4a4e4a] rounded-lg font-bold text-xs hover:bg-[#e4e0d8]"
            >
              返回选股列表
            </button>
          )}
        </div>
      </div>

      {/* 新增样本表单 */}
      {showAddForm && (
        <form onSubmit={handleAddSample} className="bg-[#faf6f0] p-4 rounded-xl border border-[#c4c8bc]/60 space-y-3 text-xs">
          <div className="font-bold text-[#2e3230] border-b border-[#c4c8bc]/30 pb-2">录入新的正样本进行回归跟踪</div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div>
              <label className="block font-bold text-[#686d68] mb-1">股票代码</label>
              <input
                type="text"
                value={newTsCode}
                onChange={(e) => setNewTsCode(e.target.value)}
                placeholder="600683.SH"
                className="w-full bg-white border border-[#c4c8bc]/60 px-2.5 py-1.5 rounded outline-none"
              />
            </div>
            <div>
              <label className="block font-bold text-[#686d68] mb-1">目标日期 (红箭头日)</label>
              <input
                type="text"
                value={newTargetDate}
                onChange={(e) => setNewTargetDate(e.target.value)}
                placeholder="20260807"
                className="w-full bg-white border border-[#c4c8bc]/60 px-2.5 py-1.5 rounded outline-none"
              />
            </div>
            <div>
              <label className="block font-bold text-[#686d68] mb-1">样本名称</label>
              <input
                type="text"
                value={newSampleName}
                onChange={(e) => setNewSampleName(e.target.value)}
                placeholder="京投发展"
                className="w-full bg-white border border-[#c4c8bc]/60 px-2.5 py-1.5 rounded outline-none"
              />
            </div>
            <div>
              <label className="block font-bold text-[#686d68] mb-1">备注/形态特征</label>
              <input
                type="text"
                value={newNote}
                onChange={(e) => setNewNote(e.target.value)}
                placeholder="均线重组突破"
                className="w-full bg-white border border-[#c4c8bc]/60 px-2.5 py-1.5 rounded outline-none"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => setShowAddForm(false)}
              className="px-3 py-1 bg-white border border-[#c4c8bc]/60 rounded text-[#4a4e4a]"
            >
              取消
            </button>
            <button type="submit" className="px-4 py-1 bg-[#4a7c59] text-white font-bold rounded shadow-xs">
              保存样本
            </button>
          </div>
        </form>
      )}

      {/* 验证结果看板 */}
      <div className="bg-white rounded-xl border border-[#c4c8bc]/60 p-4 shadow-xs space-y-4">
        <div className="flex items-center justify-between border-b border-[#c4c8bc]/30 pb-3">
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm text-[#2e3230]">回归测试结果汇总:</span>
            <span className="bg-[#4a7c59]/15 text-[#4a7c59] px-2 py-0.5 rounded font-bold text-xs">
              命中率: {samples.length > 0 ? Math.round((hitCount / samples.length) * 100) : 0}% ({hitCount}/{samples.length})
            </span>
          </div>
          <span className="text-xs text-[#686d68]">命中标准: 目标日期评级达到 WATCH / PRE_READY / EARLY_TURN</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {samples.map((s) => {
            const isHit = s.hit;
            const detail = s.score_detail_json || {};

            return (
              <div
                key={`${s.ts_code}-${s.target_date}`}
                className={`rounded-xl border p-4 space-y-3 transition ${
                  isHit
                    ? 'border-[#4a7c59]/60 bg-[#4a7c59]/5 shadow-xs'
                    : 'border-[#c4c8bc]/60 bg-[#faf6f0]/60'
                }`}
              >
                {/* Header */}
                <div className="flex items-center justify-between border-b border-[#c4c8bc]/30 pb-2">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-sm text-[#2e3230]">
                      {s.sample_name} ({s.ts_code})
                    </span>
                    <span className="font-mono text-xs text-[#686d68] bg-white px-1.5 py-0.5 rounded border border-[#c4c8bc]/40">
                      目标: {s.target_date}
                    </span>
                  </div>

                  <span
                    className={`px-2 py-0.5 rounded font-bold text-xs ${
                      isHit ? 'bg-[#4a7c59] text-white' : 'bg-gray-200 text-gray-700'
                    }`}
                  >
                    {isHit ? `✅ 命中 (${s.state})` : `未命中 (${s.state || 'NO_SIGNAL'})`}
                  </span>
                </div>

                {s.note && <p className="text-xs text-[#686d68] italic bg-white/60 p-1.5 rounded">{s.note}</p>}

                {/* Score breakdown */}
                <div className="space-y-1.5 text-xs">
                  <div className="flex items-center justify-between font-bold">
                    <span>评级得分:</span>
                    <span className="font-mono text-sm text-[#2e3230]">{(s.total_score || 0).toFixed(1)}分</span>
                  </div>

                  <div className="grid grid-cols-3 gap-1.5 text-[11px] text-[#4a4e4a]">
                    <div className="bg-white p-1.5 rounded border border-[#c4c8bc]/30">
                      <span>均线压缩: </span>
                      <strong className="text-[#2e3230]">{detail.compression || 0}分</strong>
                    </div>
                    <div className="bg-white p-1.5 rounded border border-[#c4c8bc]/30">
                      <span>均线结扎: </span>
                      <strong className="text-[#2e3230]">{detail.knot || 0}分</strong>
                    </div>
                    <div className="bg-white p-1.5 rounded border border-[#c4c8bc]/30">
                      <span>方向重排: </span>
                      <strong className="text-[#2e3230]">{detail.direction || 0}分</strong>
                    </div>
                    <div className="bg-white p-1.5 rounded border border-[#c4c8bc]/30">
                      <span>斜率转向: </span>
                      <strong className="text-[#2e3230]">{detail.slope || 0}分</strong>
                    </div>
                    <div className="bg-white p-1.5 rounded border border-[#c4c8bc]/30">
                      <span>夺回成本区: </span>
                      <strong className="text-[#2e3230]">{detail.retake || 0}分</strong>
                    </div>
                    <div className="bg-white p-1.5 rounded border border-[#c4c8bc]/30">
                      <span>偏离扩展: </span>
                      <strong className="text-[#2e3230]">{detail.extension || 0}分</strong>
                    </div>
                  </div>
                </div>

                {/* Reasons / Diagnostic */}
                {s.reasons_json && s.reasons_json.length > 0 && (
                  <div className="space-y-1 text-[11px] pt-1">
                    {s.reasons_json.map((r, idx) => (
                      <div key={idx} className="flex items-center gap-1.5">
                        <span className="rounded bg-[#4a7c59]/10 text-[#4a7c59] px-1 py-0.2 font-bold text-[10px]">
                          {r.type}
                        </span>
                        <span className="text-[#2e3230]">{r.msg}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
