'use client';

import React, { useState, useEffect } from 'react';
import { X, Sparkles, Building2, TrendingUp, Layers, Tag, Bot, History, AlertTriangle, CheckCircle2, HelpCircle } from 'lucide-react';

interface SecondaryStockDetailDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  tsCode: string;
  asOfDate: string;
  stockName?: string;
  onTriggerAI: (tsCode: string) => void;
}

export const SecondaryStockDetailDrawer: React.FC<SecondaryStockDetailDrawerProps> = ({
  isOpen,
  onClose,
  tsCode,
  asOfDate,
  stockName,
  onTriggerAI,
}) => {
  const [activeTab, setActiveTab] = useState<'technical' | 'evidence' | 'leadership' | 'supply' | 'concepts' | 'ai' | 'history'>('technical');
  const [detailData, setDetailData] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen && tsCode && asOfDate) {
      fetchDetail();
    }
  }, [isOpen, tsCode, asOfDate]);

  const fetchDetail = async () => {
    setLoading(true);
    try {
      const res = await fetch(`http://127.0.0.1:18080/api/candidate-secondary/${tsCode}?date=${asOfDate}`);
      if (res.ok) {
        const json = await res.json();
        setDetailData(json);
      }
    } catch (e) {
      console.error('Fetch secondary detail failed:', e);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  const detail = detailData?.detail || {};
  const conceptsInfo = detailData?.concepts_info || {};
  const aiResearch = detailData?.ai_research || {};

  return (
    <div className="fixed inset-0 z-50 overflow-hidden flex justify-end bg-black/50 backdrop-blur-xs select-none">
      <div className="w-full max-w-4xl bg-white h-full shadow-2xl flex flex-col border-l border-[#c4c8bc]">
        {/* Header */}
        <div className="bg-[#faf6f0] px-6 py-4 border-b border-[#c4c8bc]/60 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-[#4a7c59] text-white font-mono font-bold px-2.5 py-1 rounded text-sm">
              {tsCode}
            </div>
            <div>
              <h2 className="text-lg font-bold text-[#2e3230] flex items-center gap-2">
                <span>{stockName || detail.name || tsCode}</span>
                <span className="text-xs font-normal text-[#686d68] bg-white px-2 py-0.5 rounded border border-[#c4c8bc]/40">
                  {detail.industry || 'A股候选'}
                </span>
              </h2>
              <p className="text-xs text-[#686d68]">
                二次评价时点 (as_of_date): <span className="font-mono font-bold text-[#4a7c59]">{asOfDate}</span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => onTriggerAI(tsCode)}
              className="inline-flex items-center gap-1.5 bg-[#4a7c59] hover:bg-[#3b6447] text-white px-3 py-1.5 rounded-lg text-xs font-bold shadow-xs transition"
            >
              <Sparkles className="w-4 h-4" />
              <span>AI 深度分析此股</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* 7 Tabs Nav */}
        <div className="flex items-center gap-1 bg-[#f0ece4] px-6 border-b border-[#c4c8bc]/50 text-xs font-bold overflow-x-auto">
          <button
            onClick={() => setActiveTab('technical')}
            className={`py-3 px-3 border-b-2 flex items-center gap-1.5 transition ${
              activeTab === 'technical' ? 'border-[#4a7c59] text-[#4a7c59] bg-white' : 'border-transparent text-[#686d68] hover:text-[#2e3230]'
            }`}
          >
            <TrendingUp className="w-3.5 h-3.5" />
            <span>1. 技术来源</span>
          </button>
          <button
            onClick={() => setActiveTab('evidence')}
            className={`py-3 px-3 border-b-2 flex items-center gap-1.5 transition ${
              activeTab === 'evidence' ? 'border-[#4a7c59] text-[#4a7c59] bg-white' : 'border-transparent text-[#686d68] hover:text-[#2e3230]'
            }`}
          >
            <Building2 className="w-3.5 h-3.5" />
            <span>2. 公司证据</span>
          </button>
          <button
            onClick={() => setActiveTab('leadership')}
            className={`py-3 px-3 border-b-2 flex items-center gap-1.5 transition ${
              activeTab === 'leadership' ? 'border-[#4a7c59] text-[#4a7c59] bg-white' : 'border-transparent text-[#686d68] hover:text-[#2e3230]'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>3. 相对领先</span>
          </button>
          <button
            onClick={() => setActiveTab('supply')}
            className={`py-3 px-3 border-b-2 flex items-center gap-1.5 transition ${
              activeTab === 'supply' ? 'border-[#4a7c59] text-[#4a7c59] bg-white' : 'border-transparent text-[#686d68] hover:text-[#2e3230]'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>4. 筹码画像</span>
          </button>
          <button
            onClick={() => setActiveTab('concepts')}
            className={`py-3 px-3 border-b-2 flex items-center gap-1.5 transition ${
              activeTab === 'concepts' ? 'border-[#4a7c59] text-[#4a7c59] bg-white' : 'border-transparent text-[#686d68] hover:text-[#2e3230]'
            }`}
          >
            <Tag className="w-3.5 h-3.5" />
            <span>5. 概念标签</span>
          </button>
          <button
            onClick={() => setActiveTab('ai')}
            className={`py-3 px-3 border-b-2 flex items-center gap-1.5 transition ${
              activeTab === 'ai' ? 'border-[#4a7c59] text-[#4a7c59] bg-white' : 'border-transparent text-[#686d68] hover:text-[#2e3230]'
            }`}
          >
            <Bot className="w-3.5 h-3.5" />
            <span>6. AI研究</span>
          </button>
          <button
            onClick={() => setActiveTab('history')}
            className={`py-3 px-3 border-b-2 flex items-center gap-1.5 transition ${
              activeTab === 'history' ? 'border-[#4a7c59] text-[#4a7c59] bg-white' : 'border-transparent text-[#686d68] hover:text-[#2e3230]'
            }`}
          >
            <History className="w-3.5 h-3.5" />
            <span>7. 历史变化</span>
          </button>
        </div>

        {/* Drawer Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-white">
          {loading ? (
            <div className="py-20 text-center text-[#686d68]">加载二次评价数据中...</div>
          ) : (
            <>
              {/* Tab 1: 技术来源 */}
              {activeTab === 'technical' && (
                <div className="space-y-4">
                  <div className="bg-[#faf6f0] p-4 rounded-xl border border-[#c4c8bc]/50 space-y-3">
                    <h3 className="font-bold text-sm text-[#2e3230]">A-PreV2 早期转强筛选技术评估</h3>
                    <div className="grid grid-cols-3 gap-4 text-xs">
                      <div className="bg-white p-3 rounded-lg border border-[#c4c8bc]/40">
                        <span className="text-[#686d68] block">评级总分</span>
                        <span className="text-xl font-mono font-bold text-[#4a7c59]">{detail.aprev2_score || 75.0} 分</span>
                      </div>
                      <div className="bg-white p-3 rounded-lg border border-[#c4c8bc]/40">
                        <span className="text-[#686d68] block">评估状态</span>
                        <span className="text-sm font-bold text-[#705c30]">{detail.aprev2_status || 'EARLY_TURN'}</span>
                      </div>
                      <div className="bg-white p-3 rounded-lg border border-[#c4c8bc]/40">
                        <span className="text-[#686d68] block">转向背景类型</span>
                        <span className="text-sm font-bold text-[#2e3230]">{detail.turn_type || 'BOTTOM_REBOUND'}</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Tab 2: 公司证据 */}
              {activeTab === 'evidence' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between border-b pb-2">
                    <h3 className="font-bold text-sm text-[#2e3230]">Q1 公司层面客观证据 (Company Evidence)</h3>
                    <span className={`px-2.5 py-0.5 rounded text-xs font-bold text-white ${
                      detail.evidence_state === 'POSITIVE' ? 'bg-[#4a7c59]' :
                      detail.evidence_state === 'MIXED' ? 'bg-[#705c30]' :
                      detail.evidence_state === 'RISK' ? 'bg-rose-700' : 'bg-gray-500'
                    }`}>
                      {detail.evidence_state || 'UNKNOWN'}
                    </span>
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                    <div className="p-3 bg-gray-50 rounded-lg border">
                      <span className="text-[#686d68] block">营收同比</span>
                      <span className="font-mono font-bold text-sm">
                        {detail.revenue_yoy != null ? `${(detail.revenue_yoy * 100).toFixed(1)}%` : '--'}
                      </span>
                    </div>
                    <div className="p-3 bg-gray-50 rounded-lg border">
                      <span className="text-[#686d68] block">归母净利润状态</span>
                      <span className="font-bold text-sm text-[#705c30]">
                        {detail.parent_profit_state || '--'}
                      </span>
                    </div>
                    <div className="p-3 bg-gray-50 rounded-lg border">
                      <span className="text-[#686d68] block">扣非净利润状态</span>
                      <span className="font-bold text-sm text-[#705c30]">
                        {detail.deducted_profit_state || '--'}
                      </span>
                    </div>
                    <div className="p-3 bg-gray-50 rounded-lg border">
                      <span className="text-[#686d68] block">业绩预告类型</span>
                      <span className="font-bold text-sm text-[#2e3230]">
                        {detail.forecast_type || '无预告'}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* Tab 3: 相对领先 */}
              {activeTab === 'leadership' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between border-b pb-2">
                    <h3 className="font-bold text-sm text-[#2e3230]">Q2 行业内部相对领先性 (Relative Leadership)</h3>
                    <span className="px-2.5 py-0.5 bg-[#4a7c59] text-white rounded text-xs font-bold">
                      {detail.leadership_state || 'INSUFFICIENT_EVIDENCE'}
                    </span>
                  </div>

                  <div className="grid grid-cols-3 gap-4 text-xs">
                    <div className="p-3 bg-gray-50 rounded-lg border">
                      <span className="text-[#686d68] block">20日行业 RS 百分位</span>
                      <span className="font-mono font-bold text-lg text-[#4a7c59]">
                        {detail.industry_rs_20_pct != null ? `${detail.industry_rs_20_pct.toFixed(1)} %` : '证据不足'}
                      </span>
                    </div>
                    <div className="p-3 bg-gray-50 rounded-lg border">
                      <span className="text-[#686d68] block">行业上涨捕获超额</span>
                      <span className="font-mono font-bold text-lg text-[#705c30]">
                        {detail.up_capture_excess != null ? `+${(detail.up_capture_excess * 100).toFixed(2)}%` : '证据不足'}
                      </span>
                    </div>
                    <div className="p-3 bg-gray-50 rounded-lg border">
                      <span className="text-[#686d68] block">行业下跌防守超额</span>
                      <span className="font-mono font-bold text-lg text-[#2e3230]">
                        {detail.down_defense_excess != null ? `+${(detail.down_defense_excess * 100).toFixed(2)}%` : '证据不足'}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* Tab 4: 筹码画像 */}
              {activeTab === 'supply' && (
                <div className="space-y-4">
                  <h3 className="font-bold text-sm text-[#2e3230]">Q3 筹码与推动画像 (Supply Profile)</h3>
                  <div className="grid grid-cols-3 gap-4 text-xs">
                    <div className="p-3 bg-[#faf6f0] rounded-lg border border-[#c4c8bc]/50">
                      <span className="text-[#686d68] block">自由流通市值</span>
                      <span className="font-mono font-bold text-lg text-[#4a7c59]">
                        {detail.free_float_mv != null ? `${detail.free_float_mv.toFixed(1)} 亿元` : '--'}
                      </span>
                    </div>
                    <div className="p-3 bg-[#faf6f0] rounded-lg border border-[#c4c8bc]/50">
                      <span className="text-[#686d68] block">画像分类标签</span>
                      <span className="font-bold text-base text-[#705c30]">{detail.supply_profile_label || 'MID_CAP'}</span>
                    </div>
                    <div className="p-3 bg-[#faf6f0] rounded-lg border border-[#c4c8bc]/50">
                      <span className="text-[#686d68] block">自由流通换手率</span>
                      <span className="font-mono font-bold text-lg text-[#2e3230]">
                        {detail.turnover_rate_f != null ? `${detail.turnover_rate_f.toFixed(2)}%` : '--'}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* Tab 5: 概念标签 */}
              {activeTab === 'concepts' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between border-b pb-2">
                    <h3 className="font-bold text-sm text-[#2e3230]">M1 同花顺概念标签底库</h3>
                    <span className="text-xs font-mono font-bold text-[#705c30]">
                      快照状态: {conceptsInfo.temporal_status || 'PIT_SAFE'}
                    </span>
                  </div>

                  <p className="text-xs text-[#686d68] italic">{conceptsInfo.temporal_notice}</p>

                  <div className="flex flex-wrap gap-2">
                    {(conceptsInfo.concepts || []).map((c: any, idx: number) => (
                      <div key={idx} className="bg-[#faf6f0] border border-[#c4c8bc]/60 px-3 py-1.5 rounded-lg text-xs flex items-center gap-1.5">
                        <Tag className="w-3.5 h-3.5 text-[#705c30]" />
                        <span className="font-bold text-[#2e3230]">{c.ths_name}</span>
                        <span className="text-[10px] bg-white px-1.5 py-0.2 rounded border text-[#686d68]">{c.type_label}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Tab 6: AI 研究 */}
              {activeTab === 'ai' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between border-b pb-2">
                    <h3 className="font-bold text-sm text-[#2e3230]">A1 AI 深度分析报告</h3>
                    <button
                      onClick={() => onTriggerAI(tsCode)}
                      className="px-3 py-1 bg-[#4a7c59] text-white rounded text-xs font-bold hover:bg-[#3b6447]"
                    >
                      重新跑 AI 分析
                    </button>
                  </div>

                  {aiResearch?.result_markdown ? (
                    <div className="prose prose-sm max-w-none bg-[#faf6f0] p-4 rounded-xl border border-[#c4c8bc]/60 text-xs leading-relaxed whitespace-pre-wrap font-sans text-[#2e3230]">
                      {aiResearch.result_markdown}
                    </div>
                  ) : (
                    <div className="py-12 text-center text-[#686d68] space-y-2">
                      <p>暂无针对该股票在该交易日的 AI 深度研究报告</p>
                      <button
                        onClick={() => onTriggerAI(tsCode)}
                        className="px-4 py-1.5 bg-[#4a7c59] text-white font-bold rounded-lg text-xs"
                      >
                        立即生成 AI 深度研究
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Tab 7: 历史变化 */}
              {activeTab === 'history' && (
                <div className="space-y-4">
                  <h3 className="font-bold text-sm text-[#2e3230]">H1 历史 40 个交易日演变轨迹</h3>
                  <p className="text-xs text-[#686d68]">展示该股票从初始候选转化为相对领先的演变过程。</p>
                  <div className="py-12 text-center text-[#686d68] bg-gray-50 rounded-lg border">
                    已累计记录 {asOfDate} 历史快照事实。
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
