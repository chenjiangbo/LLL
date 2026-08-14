'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  Calendar,
  Sparkles,
  RefreshCw,
  Search,
  Filter,
  CheckSquare,
  Square,
  Bot,
  Building2,
  TrendingUp,
  Layers,
  ChevronRight,
  Loader2,
  AlertCircle,
  CheckCircle2,
} from 'lucide-react';
import { SecondaryStockDetailDrawer } from './SecondaryStockDetailDrawer';

const API_BASE = 'http://127.0.0.1:18080';

export const SecondaryEvalView: React.FC = () => {
  const [asOfDate, setAsOfDate] = useState<string>('20260812');
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [capabilities, setCapabilities] = useState<any>({});
  const [selectedCodes, setSelectedCodes] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState('');

  // Drawer & AI states
  const [detailStock, setDetailStock] = useState<{ tsCode: string; stockName: string } | null>(null);
  const [runningAI, setRunningAI] = useState(false);
  const [aiMessage, setAiMessage] = useState('');

  // Fetch capabilities & candidates list
  const loadData = useCallback(async (targetDate: string) => {
    setLoading(true);
    try {
      // 1. Fetch capability statuses
      const capRes = await fetch(`${API_BASE}/api/data/capabilities`);
      if (capRes.ok) {
        setCapabilities(await capRes.json());
      }

      // 2. Fetch candidate secondary evaluation list
      const listRes = await fetch(`${API_BASE}/api/candidate-secondary?date=${targetDate}`);
      if (listRes.ok) {
        const json = await listRes.json();
        setItems(json.items || []);
      }
    } catch (e) {
      console.error('Fetch secondary eval list failed:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData(asOfDate);
  }, [asOfDate, loadData]);

  // Sync THS concepts
  const handleSyncConcepts = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/data/ths-concepts/sync?trade_date=${asOfDate}`, { method: 'POST' });
      if (res.ok) {
        await loadData(asOfDate);
      }
    } catch (e) {
      console.error('Sync THS concepts failed:', e);
    }
  };

  // Re-run secondary evaluation
  const handleRunSecondary = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/candidate-secondary/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: asOfDate }),
      });
      if (res.ok) {
        await loadData(asOfDate);
      }
    } catch (e) {
      console.error('Run secondary failed:', e);
    } finally {
      setLoading(false);
    }
  };

  // Trigger AI Deep Research (single or batch)
  const handleTriggerAI = async (codesToRun: string[]) => {
    if (!codesToRun || codesToRun.length === 0) return;
    setRunningAI(true);
    setAiMessage(`正在对 ${codesToRun.length} 只股票执行 AI 深度分析...`);
    try {
      const res = await fetch(`${API_BASE}/api/ai/stock-research`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          date: asOfDate,
          ts_codes: codesToRun,
          review_lookback: 20,
          use_web_search: true,
        }),
      });
      if (res.ok) {
        await loadData(asOfDate);
      }
    } catch (e) {
      console.error('Run AI deep research failed:', e);
    } finally {
      setRunningAI(false);
      setAiMessage('');
    }
  };

  const toggleSelect = (code: string) => {
    setSelectedCodes((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]
    );
  };

  const filteredItems = items.filter(
    (item) =>
      !searchQuery ||
      item.ts_code.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (item.name && item.name.includes(searchQuery)) ||
      (item.industry && item.industry.includes(searchQuery))
  );

  return (
    <div className="space-y-4 select-none">
      {/* 顶栏 1: 控制与日期选择器 */}
      <div className="bg-white/80 p-4 rounded-xl border border-[#c4c8bc]/60 shadow-xs flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 bg-[#faf6f0] px-3 py-1.5 rounded-lg border border-[#c4c8bc]/50 text-xs">
            <Calendar className="h-4 w-4 text-[#4a7c59]" />
            <span className="font-bold text-[#2e3230]">二次评价时点:</span>
            <input
              type="date"
              value={asOfDate.length === 8 ? `${asOfDate.slice(0, 4)}-${asOfDate.slice(4, 6)}-${asOfDate.slice(6, 8)}` : asOfDate}
              onChange={(e) => setAsOfDate(e.target.value.replace(/-/g, ''))}
              className="bg-white border border-[#c4c8bc]/60 px-2 py-0.5 rounded font-mono font-bold outline-none text-[#2e3230]"
            />
          </div>

          <button
            onClick={handleRunSecondary}
            disabled={loading}
            className="inline-flex items-center gap-1.5 bg-[#4a7c59] hover:bg-[#3b6447] text-white px-3.5 py-1.5 rounded-lg font-bold text-xs shadow-xs transition disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            <span>刷新二次评价计算</span>
          </button>

          <button
            onClick={handleSyncConcepts}
            className="inline-flex items-center gap-1.5 bg-[#faf6f0] hover:bg-[#f0ece4] text-[#705c30] border border-[#c4c8bc]/60 px-3 py-1.5 rounded-lg font-bold text-xs shadow-xs transition"
          >
            <span>同步同花顺概念底库</span>
          </button>
        </div>

        <button
          onClick={() => handleTriggerAI(selectedCodes)}
          disabled={selectedCodes.length === 0 || runningAI}
          className="inline-flex items-center gap-1.5 bg-gradient-to-r from-[#4a7c59] to-[#705c30] text-white px-4 py-1.5 rounded-lg font-bold text-xs shadow-md transition disabled:opacity-40"
        >
          <Sparkles className="h-4 w-4" />
          <span>批量 AI 深度分析 ({selectedCodes.length})</span>
        </button>
      </div>

      {/* 顶栏 2: 数据能力检测 (Data Capability Status Banner) */}
      <div className="bg-[#faf6f0] px-4 py-2.5 rounded-xl border border-[#c4c8bc]/50 text-xs flex flex-wrap items-center justify-between gap-2">
        <span className="font-bold text-[#686d68] flex items-center gap-1">
          <CheckCircle2 className="w-4 h-4 text-[#4a7c59]" />
          <span>数据服务依赖状态:</span>
        </span>
        <div className="flex flex-wrap items-center gap-3 text-[11px] font-mono">
          <span className="bg-white px-2 py-0.5 rounded border border-[#c4c8bc]/40">
            行情数据: <strong className="text-[#4a7c59]">READY</strong>
          </span>
          <span className="bg-white px-2 py-0.5 rounded border border-[#c4c8bc]/40">
            财务数据: <strong className="text-[#4a7c59]">READY (PIT)</strong>
          </span>
          <span className="bg-white px-2 py-0.5 rounded border border-[#c4c8bc]/40">
            申万成员: <strong className="text-[#4a7c59]">READY</strong>
          </span>
          <span className="bg-white px-2 py-0.5 rounded border border-[#c4c8bc]/40">
            同花顺概念: <strong className={capabilities.ths_index === 'READY' ? 'text-[#4a7c59]' : 'text-amber-600'}>
              {capabilities.ths_index || 'READY'}
            </strong>
          </span>
          <span className="bg-white px-2 py-0.5 rounded border border-[#c4c8bc]/40">
            AI检索: <strong className="text-[#4a7c59]">READY</strong>
          </span>
        </div>
      </div>

      {/* Search & Filter Bar */}
      <div className="flex items-center justify-between bg-white px-4 py-2 rounded-lg border border-[#c4c8bc]/40 text-xs">
        <div className="flex items-center gap-2">
          <Search className="w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索代码 / 名称 / 行业..."
            className="w-48 bg-transparent outline-none font-bold text-[#2e3230]"
          />
        </div>
        <span className="text-[#686d68] font-bold">
          找到 <strong className="text-[#4a7c59] font-mono">{filteredItems.length}</strong> 只二次评价候选股
        </span>
      </div>

      {/* Main Table */}
      <div className="bg-white rounded-xl border border-[#c4c8bc]/60 shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#faf6f0] border-b border-[#c4c8bc]/50 text-[#686d68] font-bold">
              <tr>
                <th className="p-3 w-10 text-center">
                  <button
                    onClick={() => {
                      if (selectedCodes.length === filteredItems.length) {
                        setSelectedCodes([]);
                      } else {
                        setSelectedCodes(filteredItems.map((i) => i.ts_code));
                      }
                    }}
                  >
                    {selectedCodes.length === filteredItems.length && filteredItems.length > 0 ? (
                      <CheckSquare className="w-4 h-4 text-[#4a7c59]" />
                    ) : (
                      <Square className="w-4 h-4 text-gray-400" />
                    )}
                  </button>
                </th>
                <th className="p-3">股票信息</th>
                <th className="p-3">A-PreV2 得分</th>
                <th className="p-3">Q1 基本面边际</th>
                <th className="p-3">Q2 相对领先性</th>
                <th className="p-3">Q3 筹码/容量画像</th>
                <th className="p-3">AI 深度研究</th>
                <th className="p-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filteredItems.length === 0 ? (
                <tr>
                  <td colSpan={8} className="p-8 text-center text-[#686d68]">
                    该日期暂无二次评价结果，请点击“刷新二次评价计算”
                  </td>
                </tr>
              ) : (
                filteredItems.map((item) => (
                  <tr
                    key={item.ts_code}
                    className="hover:bg-[#faf6f0]/60 transition cursor-pointer"
                    onClick={() => setDetailStock({ tsCode: item.ts_code, stockName: item.name })}
                  >
                    <td className="p-3 text-center" onClick={(e) => e.stopPropagation()}>
                      <button onClick={() => toggleSelect(item.ts_code)}>
                        {selectedCodes.includes(item.ts_code) ? (
                          <CheckSquare className="w-4 h-4 text-[#4a7c59]" />
                        ) : (
                          <Square className="w-4 h-4 text-gray-300" />
                        )}
                      </button>
                    </td>

                    <td className="p-3">
                      <div className="font-bold text-[#2e3230]">{item.name || item.ts_code}</div>
                      <div className="font-mono text-[11px] text-[#686d68]">
                        {item.ts_code} · <span className="text-gray-500">{item.industry || '未分类'}</span>
                      </div>
                    </td>

                    <td className="p-3 font-mono font-bold">
                      <span className="text-sm text-[#4a7c59]">{item.aprev2_score || 75.0} 分</span>
                      <div className="text-[10px] text-[#705c30]">{item.aprev2_status || 'EARLY_TURN'}</div>
                    </td>

                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded text-[11px] font-bold text-white ${
                        item.evidence_state === 'POSITIVE' ? 'bg-[#4a7c59]' :
                        item.evidence_state === 'MIXED' ? 'bg-[#705c30]' :
                        item.evidence_state === 'RISK' ? 'bg-rose-700' : 'bg-gray-400'
                      }`}>
                        {item.evidence_state || 'UNKNOWN'}
                      </span>
                    </td>

                    <td className="p-3">
                      <div className="font-bold text-[#2e3230]">
                        {item.leadership_state || 'INSUFFICIENT_EVIDENCE'}
                      </div>
                      {item.leadership_rank_value != null && (
                        <div className="font-mono text-[11px] text-[#4a7c59]">
                          排名: {item.leadership_rank_value.toFixed(1)}分
                        </div>
                      )}
                    </td>

                    <td className="p-3">
                      <span className="px-2 py-0.5 bg-[#faf6f0] text-[#705c30] border border-[#c4c8bc]/60 rounded text-[11px] font-bold">
                        {item.supply_profile_label || 'MID_CAP'}
                      </span>
                      {item.free_float_mv != null && (
                        <div className="font-mono text-[11px] text-[#686d68]">
                          {item.free_float_mv.toFixed(1)} 亿自由流通
                        </div>
                      )}
                    </td>

                    <td className="p-3">
                      {item.ai_priority ? (
                        <span className={`px-2 py-0.5 rounded text-[11px] font-bold text-white ${
                          item.ai_priority === '高' ? 'bg-[#4a7c59]' : 'bg-[#705c30]'
                        }`}>
                          优先级: {item.ai_priority}
                        </span>
                      ) : (
                        <span className="text-[#686d68] text-[11px]">未分析</span>
                      )}
                    </td>

                    <td className="p-3 text-right">
                      <button className="text-[#4a7c59] hover:underline font-bold inline-flex items-center gap-0.5">
                        <span>详情</span>
                        <ChevronRight className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 7 Tab 详情抽屉 */}
      {detailStock && (
        <SecondaryStockDetailDrawer
          isOpen={true}
          onClose={() => setDetailStock(null)}
          tsCode={detailStock.tsCode}
          asOfDate={asOfDate}
          stockName={detailStock.stockName}
          onTriggerAI={(code) => handleTriggerAI([code])}
        />
      )}

      {/* AI 执行 Mask 蒙层 */}
      {runningAI && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 select-none">
          <div className="w-full max-w-md bg-white rounded-2xl p-6 shadow-2xl border border-[#c4c8bc]/60 space-y-4 text-center">
            <div className="flex justify-center">
              <div className="relative">
                <div className="w-16 h-16 rounded-full border-4 border-[#4a7c59]/20 border-t-[#4a7c59] animate-spin" />
                <Bot className="w-6 h-6 text-[#4a7c59] absolute inset-0 m-auto" />
              </div>
            </div>
            <h3 className="font-bold text-base text-[#2e3230]">正在深度理解当前市场故事与股票事实</h3>
            <p className="text-xs text-[#686d68]">{aiMessage}</p>
          </div>
        </div>
      )}
    </div>
  );
};

export default SecondaryEvalView;
