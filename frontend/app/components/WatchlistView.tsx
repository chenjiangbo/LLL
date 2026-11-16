'use client';

import React, { useEffect, useState, useCallback } from 'react';
import {
  Star,
  Folder,
  FolderPlus,
  FolderTree,
  Trash2,
  Edit2,
  Sparkles,
  ChevronRight,
  Layers,
  Search,
  Loader2,
  ClipboardList,
  Check,
  X,
} from 'lucide-react';
import SecondaryStockDetailDrawer from './SecondaryStockDetailDrawer';

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL || 'http://127.0.0.1:18080';

interface WatchlistGroup {
  group_id: number | null;
  group_key: string;
  group_name: string;
  group_icon?: string;
  group_type: 'manual' | 'industry';
  parent_id?: number | null;
  sort_order: number;
  stock_count?: number;
  created_at?: string;
}

interface WatchlistStock {
  asset_code: string;
  name: string;
  industry: string;
  group_id?: number | null;
  created_at?: string;
  research_as_of_date?: string | null;
  aprev2_score?: number | string | null;
  aprev2_status?: string | null;
  turn_type?: string | null;
  evidence_state?: string | null;
  fundamental_filter_state?: string | null;
  latest_report_period?: string | null;
  revenue_yoy?: number | string | null;
  parent_net_profit_yoy?: number | string | null;
  operating_cashflow_yoy?: number | string | null;
  forecast_type?: string | null;
  fact_tags_json?: Array<{ label?: string; tone?: string }> | null;
  risk_flags_json?: string[] | null;
  ai_as_of_date?: string | null;
  ai_status?: string | null;
  ai_priority?: string | null;
  ai_created_at?: string | null;
  ai_total_tokens?: number | null;
  ai_elapsed_ms?: number | null;
  web_search_used?: boolean | null;
  source_type?: 'MANUAL' | 'STRATEGY' | 'UNKNOWN' | null;
  source_strategy?: string | null;
  source_stage?: string | null;
  source_snapshot_date?: string | null;
}

const technicalStatusText: Record<string, string> = {
  PRE_READY: '底部准备',
  PRE_READY_STRICT: '底部准备',
  EARLY_TURN: '早期转强',
  EARLY_TURN_STRICT: '早期转强',
  PRE_FIRST_TURN: '底部准备',
  FIRST_TURN_WINDOW: '首次转强',
  POST_FIRST_WAVE: '第一波已完成',
  OUTSIDE_A_PRE: '未进入 A-Pre',
};

const fundamentalStatusText: Record<string, string> = {
  FUNDAMENTAL_ACCEPTABLE: '基本面可接受',
  FUNDAMENTAL_POSITIVE: '经营向好',
  FUNDAMENTAL_RISK: '存在风险',
  FUNDAMENTAL_DATA_INSUFFICIENT: '数据不足',
};

const aiStatusText: Record<string, string> = {
  READY: 'AI 研究已完成',
  STALE: '需重新分析',
  FAILED: 'AI 分析失败',
};

const formatResearchDate = (value?: string | null): string => {
  const date = String(value || '').trim();
  if (/^\d{8}$/.test(date)) return `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6)}`;
  return date || '暂无';
};

const GROUP_ICONS: Record<string, string> = { folder: '📁', star: '⭐', chart: '📈', chip: '🔧', fire: '🔥', leaf: '🌱', gem: '💎', globe: '🌐' };

// 页面切换、React 开发模式的 effect 重连都会终止已经失去归属的请求。
// 此时浏览器不保证抛出 AbortError，也可能只报 TypeError: Failed to fetch，
// 因此必须优先以 signal.aborted 判断，避免旧请求污染当前页面状态。
const requestWasCancelled = (signal?: AbortSignal, error?: unknown): boolean => (
  Boolean(signal?.aborted) || (error instanceof DOMException && error.name === 'AbortError')
);

export default function WatchlistView({ onCreateTradePlan }: { onCreateTradePlan?: (stock: WatchlistStock) => void }) {
  const [groups, setGroups] = useState<WatchlistGroup[]>([]);
  const [stocks, setStocks] = useState<WatchlistStock[]>([]);
  const [totalStockCount, setTotalStockCount] = useState<number | null>(null);
  const [defaultResearchDate, setDefaultResearchDate] = useState<string | null>(null);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [selectedGroupKey, setSelectedGroupKey] = useState<string | null>(null);
  const [aiPoolStocks, setAiPoolStocks] = useState<WatchlistStock[]>([]);
  const [loading, setLoading] = useState(false);
  const [stockListError, setStockListError] = useState<string | null>(null);
  const [aiPoolError, setAiPoolError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [groupingMode, setGroupingMode] = useState<'industry' | 'manual'>('industry');

  // Group creation & editing modal state
  const [showAddGroupModal, setShowAddGroupModal] = useState(false);
  const [newGroupName, setNewGroupName] = useState('');
  const [newGroupIcon, setNewGroupIcon] = useState('folder');
  const [parentGroupId, setParentGroupId] = useState<number | null>(null);
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);
  const [editingName, setEditingName] = useState('');

  // 股票抽屉
  const [detailStock, setDetailStock] = useState<{ tsCode: string; stockName: string; asOfDate: string } | null>(null);
  const [aiResearchRunningCodes, setAiResearchRunningCodes] = useState<string[]>([]);
  const [selectedTradePlanStock, setSelectedTradePlanStock] = useState<WatchlistStock | null>(null);

  // Fetch Watchlist Groups
  const fetchGroups = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await fetch(`${API_BASE}/api/watchlist/groups`, { signal });
      if (res.ok) {
        const data = await res.json();
        if (!signal?.aborted) setGroups(data.groups || []);
      }
    } catch (e) {
      if (requestWasCancelled(signal, e)) return;
      console.error('Fetch watchlist groups error:', e);
    }
  }, []);

  // Fetch Watchlist Stocks
  const fetchStocks = useCallback(async (groupKey: string | null = null, signal?: AbortSignal) => {
    setLoading(true);
    setStockListError(null);
    try {
      const url = groupKey !== null ? `${API_BASE}/api/watchlist/stocks?group_key=${encodeURIComponent(groupKey)}` : `${API_BASE}/api/watchlist/stocks`;
      const res = await fetch(url, { signal });
      if (!res.ok) throw new Error(`自选股接口返回 HTTP ${res.status}`);
      const data = await res.json();
      if (signal?.aborted) return;
      const nextStocks = data.stocks || [];
      setStocks(nextStocks);
      setSelectedTradePlanStock(null);
      if (typeof data.default_research_date === 'string' && /^\d{8}$/.test(data.default_research_date)) {
        setDefaultResearchDate(data.default_research_date);
      }
      if (groupKey === null) setTotalStockCount(nextStocks.length);
    } catch (e) {
      if (requestWasCancelled(signal, e)) return;
      console.error('Fetch watchlist stocks error:', e);
      setStockListError(e instanceof TypeError ? '无法连接自选股服务，请确认服务已启动。' : (e as Error).message);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  const fetchAiPool = useCallback(async (signal?: AbortSignal) => {
    setAiPoolError(null);
    try {
      const res = await fetch(`${API_BASE}/api/watchlist/ai-pool`, { signal });
      if (!res.ok) throw new Error(`AI 分析池接口返回 HTTP ${res.status}`);
      const data = await res.json();
      if (signal?.aborted) return;
      setAiPoolStocks(data.stocks || []);
    } catch (e) {
      if (requestWasCancelled(signal, e)) return;
      console.error('Fetch AI analysis pool error:', e);
      setAiPoolError(e instanceof TypeError ? 'AI 分析池暂时无法读取。' : (e as Error).message);
    }
  }, []);

  // 用户选择不保留旧版浏览器 AI 池数据：清理后不再迁移或写入它。
  useEffect(() => {
    localStorage.removeItem('ai_analysis_pool_codes');
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    void fetchGroups(signal);
    if (selectedGroupKey === '__ai_pool__') {
      setLoading(false);
      setStockListError(null);
      void fetchAiPool(signal);
    } else {
      void fetchStocks(selectedGroupKey, signal);
    }
    return () => controller.abort();
  }, [fetchGroups, fetchStocks, fetchAiPool, selectedGroupKey]);

  // Create Group
  const handleCreateGroup = async () => {
    if (!newGroupName.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/api/watchlist/groups`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newGroupName.trim(), parent_id: parentGroupId, icon: newGroupIcon }),
      });
      if (res.ok) {
        setNewGroupName('');
        setNewGroupIcon('folder');
        setShowAddGroupModal(false);
        await fetchGroups();
      }
    } catch (e) {
      console.error('Create group failed:', e);
    }
  };

  // Update Group
  const handleUpdateGroup = async (groupId: number) => {
    if (!editingName.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/api/watchlist/groups/${groupId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: editingName.trim() }),
      });
      if (res.ok) {
        setEditingGroupId(null);
        await fetchGroups();
      }
    } catch (e) {
      console.error('Update group failed:', e);
    }
  };

  // Delete Group
  const handleDeleteGroup = async (groupId: number) => {
    if (!window.confirm('确定要删除该自选分组及其子分组吗？')) return;
    try {
      const res = await fetch(`${API_BASE}/api/watchlist/groups/${groupId}`, { method: 'DELETE' });
      if (res.ok) {
        if (selectedGroupId === groupId) { setSelectedGroupId(null); setSelectedGroupKey(null); }
        fetchGroups();
        fetchStocks(null);
      }
    } catch (e) {
      console.error('Delete group failed:', e);
    }
  };

  // Toggle/Remove Stock from Watchlist
  const handleRemoveStock = async (code: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/watchlist/stocks/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asset_code: code, group_id: selectedGroupId }),
      });
      if (res.ok) {
        fetchStocks(selectedGroupKey);
        if (selectedGroupId === null) {
          setTotalStockCount((count) => count === null ? null : Math.max(0, count - 1));
        }
      }
    } catch (e) {
      console.error('Remove stock failed:', e);
    }
  };

  const openDetail = (stock: WatchlistStock) => {
    // 自选股并不要求先存在选股快照；抽屉会按该日期读取股票级基础资料。
    // 若没有任何研究日期，则使用本地当天作为读取日期，基本面分析仍需用户主动触发。
    const localToday = new Date();
    const today = `${localToday.getFullYear()}${String(localToday.getMonth() + 1).padStart(2, '0')}${String(localToday.getDate()).padStart(2, '0')}`;
    const asOfDate = stock.ai_as_of_date || stock.research_as_of_date || defaultResearchDate || today;
    setSelectedTradePlanStock(stock);
    setDetailStock({ tsCode: stock.asset_code, stockName: stock.name, asOfDate });
  };

  const triggerAiResearch = async (code: string) => {
    const asOfDate = detailStock?.tsCode === code ? detailStock.asOfDate : null;
    if (!asOfDate) throw new Error('未找到该股票对应的研究交易日，无法启动 AI 分析');
    if (aiResearchRunningCodes.includes(code)) return;
    setAiResearchRunningCodes((codes) => Array.from(new Set([...codes, code])));
    try {
      const res = await fetch(`${API_BASE}/api/ai/stock-research-async`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ts_codes: [code], date: asOfDate, use_web_search: true }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = typeof body?.detail === 'string' ? body.detail : body?.detail?.message;
        throw new Error(message || `AI 分析提交失败（HTTP ${res.status}）`);
      }
      const jobId = body?.job_id;
      if (!jobId) throw new Error('AI 分析任务未成功创建');
      for (;;) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        const statusRes = await fetch(`${API_BASE}/api/ai/stock-research-status/${encodeURIComponent(jobId)}`);
        const statusBody = await statusRes.json().catch(() => ({}));
        if (!statusRes.ok) throw new Error(statusBody?.detail || `AI 分析状态读取失败（HTTP ${statusRes.status}）`);
        if (statusBody.status === 'success') break;
        if (statusBody.status === 'failed') throw new Error(statusBody.error || statusBody.step_message || 'AI 分析失败');
      }
      await fetchStocks(selectedGroupKey);
    } finally {
      setAiResearchRunningCodes((codes) => codes.filter((item) => item !== code));
    }
  };

  const triggerThemeMatch = async (code: string) => {
    const asOfDate = detailStock?.tsCode === code ? detailStock.asOfDate : null;
    if (!asOfDate) throw new Error('未找到该股票对应的研究交易日，无法启动主题匹配');
    const res = await fetch(`${API_BASE}/api/ai/stock-theme-match`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ts_code: code, date: asOfDate }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const message = typeof body?.detail === 'string' ? body.detail : body?.detail?.message;
      throw new Error(message || `主题匹配失败（HTTP ${res.status}）`);
    }
    await fetchStocks(selectedGroupKey);
  };

  // Build Multi-level Group Tree
  const manualGroups = groups.filter((g) => g.group_type === 'manual');
  const industryGroups = groups.filter((g) => g.group_type === 'industry');
  const rootGroups = manualGroups.filter((g) => g.parent_id === null || g.parent_id === undefined);
  const getSubGroups = (parentId: number) => manualGroups.filter((g) => g.parent_id === parentId);
  const selectedManualGroup = selectedGroupId === null ? null : manualGroups.find((group) => group.group_id === selectedGroupId) || null;

  const selectGroupingMode = (mode: 'industry' | 'manual') => {
    setGroupingMode(mode);
    setSelectedGroupId(null);
    setSelectedGroupKey(null);
  };

  const visibleStocks = selectedGroupKey === '__ai_pool__' ? aiPoolStocks : stocks;
  const filteredStocks = visibleStocks.filter((s) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase().trim();
    return s.asset_code.toLowerCase().includes(q) || (s.name || '').toLowerCase().includes(q) || (s.industry || '').toLowerCase().includes(q);
  });

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <div className="bg-white/80 p-4 rounded-xl border border-[#c4c8bc]/60 shadow-xs space-y-3 lg:col-span-1">
          <div className="flex items-center justify-between border-b border-[#c4c8bc]/40 pb-2">
            <span className="font-bold text-xs text-[#2e3230] flex items-center gap-1.5">
              <FolderTree className="w-4 h-4 text-[#4a7c59]" />
              <span>自选股{totalStockCount === null ? '' : `（${totalStockCount}）`}</span>
            </span>
            <div className="flex items-center gap-1">
              <button type="button" onClick={() => selectGroupingMode('industry')} className={`rounded p-1.5 ${groupingMode === 'industry' ? 'bg-[#e7f0e9] text-[#3b6447]' : 'text-[#686d68] hover:bg-[#f0ece4]'}`} title="按行业分组" aria-label="按行业分组"><Layers className="h-3.5 w-3.5" /></button>
              <button type="button" onClick={() => selectGroupingMode('manual')} className={`rounded p-1.5 ${groupingMode === 'manual' ? 'bg-[#e7f0e9] text-[#3b6447]' : 'text-[#686d68] hover:bg-[#f0ece4]'}`} title="按自定义分组" aria-label="按自定义分组"><Folder className="h-3.5 w-3.5" /></button>
              <button type="button" onClick={() => { setGroupingMode('manual'); setParentGroupId(selectedManualGroup?.group_id ?? null); setShowAddGroupModal(true); }} className="rounded p-1.5 text-[#4a7c59] hover:bg-[#e7f0e9]" title={selectedManualGroup ? '在当前分组中新建分组' : '新建自定义分组'} aria-label={selectedManualGroup ? '在当前分组中新建分组' : '新建自定义分组'}><FolderPlus className="h-3.5 w-3.5" /></button>
              <button type="button" disabled={!selectedManualGroup} onClick={() => { if (selectedManualGroup) { setEditingGroupId(selectedManualGroup.group_id); setEditingName(selectedManualGroup.group_name); } }} className="rounded p-1.5 text-[#686d68] hover:bg-[#f0ece4] disabled:cursor-not-allowed disabled:opacity-30" title="重命名当前分组" aria-label="重命名当前分组"><Edit2 className="h-3.5 w-3.5" /></button>
              <button type="button" disabled={!selectedManualGroup} onClick={() => { if (selectedManualGroup) handleDeleteGroup(selectedManualGroup.group_id as number); }} className="rounded p-1.5 text-rose-600 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-30" title="删除当前分组" aria-label="删除当前分组"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          </div>

          <div className="space-y-1">
            <button
              onClick={() => { setSelectedGroupId(null); setSelectedGroupKey('__ai_pool__'); }}
              className={`w-full text-left px-3 py-2 rounded-lg text-xs font-bold transition flex items-center justify-between ${selectedGroupKey === '__ai_pool__' ? 'bg-violet-100 text-violet-800 border border-violet-300' : 'text-[#2e3230] hover:bg-[#faf6f0] border border-transparent'}`}
            >
              <div className="flex items-center gap-2"><Sparkles className="w-3.5 h-3.5 text-violet-600" /><span>AI 分析池</span></div>
              <span className="font-mono text-[11px]">({aiPoolStocks.length})</span>
            </button>
            {selectedGroupKey === '__ai_pool__' && aiPoolError && (
              <div className="flex items-center justify-between gap-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] font-bold text-amber-800">
                <span>AI 分析池暂时无法读取</span>
                <button type="button" onClick={() => void fetchAiPool()} className="shrink-0 underline underline-offset-2">重试</button>
              </div>
            )}

            {groupingMode === 'industry' && industryGroups.map((group) => (
              <button key={group.group_key} onClick={() => { setSelectedGroupId(null); setSelectedGroupKey(group.group_key); }} className={`w-full text-left px-3 py-1.5 rounded-lg text-xs font-bold flex items-center justify-between ${selectedGroupKey === group.group_key ? 'bg-[#4a7c59]/15 text-[#4a7c59] border border-[#4a7c59]/40' : 'text-[#2e3230] hover:bg-[#faf6f0]'}`}>
                <span className="flex items-center gap-2"><Layers className="w-3.5 h-3.5 text-[#4a7c59]" />{group.group_name}</span><span className="font-mono text-[11px]">({group.stock_count || 0})</span>
              </button>
            ))}

            {groupingMode === 'manual' && rootGroups.map((group) => {
              const subGroups = getSubGroups(group.group_id as number);
              const isSelected = selectedGroupKey === group.group_key;
              const isEditing = editingGroupId === group.group_id;

              return (
                <div key={group.group_id} className="space-y-1 pl-1">
                  <div
                    className={`group/item flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs font-bold transition cursor-pointer ${
                      isSelected
                        ? 'bg-[#4a7c59]/15 text-[#4a7c59] border border-[#4a7c59]/40'
                        : 'text-[#2e3230] hover:bg-[#faf6f0]'
                    }`}
                    onClick={() => { setSelectedGroupId(group.group_id); setSelectedGroupKey(group.group_key); }}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <Folder className="w-3.5 h-3.5 text-[#4a7c59] shrink-0" />
                      {isEditing ? (
                        <><input
                          type="text"
                          value={editingName}
                          onChange={(e) => setEditingName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') { e.preventDefault(); void handleUpdateGroup(group.group_id as number); }
                            if (e.key === 'Escape') setEditingGroupId(null);
                          }}
                          className="bg-white border border-[#c4c8bc] px-1 py-0.5 rounded text-xs outline-none w-24"
                          autoFocus
                          onClick={(e) => e.stopPropagation()}
                        /><button type="button" title="保存名称" onClick={(e) => { e.stopPropagation(); void handleUpdateGroup(group.group_id as number); }} className="text-emerald-700"><Check className="h-3.5 w-3.5" /></button><button type="button" title="取消编辑" onClick={(e) => { e.stopPropagation(); setEditingGroupId(null); }} className="text-slate-500"><X className="h-3.5 w-3.5" /></button></>
                      ) : (
                        <span className="truncate">{GROUP_ICONS[group.group_icon || 'folder'] || GROUP_ICONS.folder} {group.group_name}</span>
                      )}
                    </div>

                  </div>

                  {/* 子分组列表 (层级缩进) */}
                  {subGroups.length > 0 && (
                    <div className="pl-4 space-y-1 border-l-2 border-[#c4c8bc]/30 ml-2">
                      {subGroups.map((sub) => {
                        const isSubSelected = selectedGroupId === sub.group_id;
                        const isSubEditing = editingGroupId === sub.group_id;

                        return (
                          <div key={sub.group_id} className="space-y-1">
                          <div
                            className={`group/sub flex items-center justify-between px-2 py-1 rounded text-xs font-medium transition cursor-pointer ${isSubSelected ? 'bg-[#4a7c59]/20 text-[#4a7c59] font-bold' : 'text-[#4a4e4a] hover:bg-[#faf6f0]'}`}
                        onClick={() => { setSelectedGroupId(sub.group_id); setSelectedGroupKey(sub.group_key); }}
                          >
                            <div className="flex items-center gap-1.5 min-w-0">
                              <ChevronRight className="w-3 h-3 text-[#686d68] shrink-0" />
                              {isSubEditing ? (
                                <>
                                  <input
                                    type="text"
                                    value={editingName}
                                    onChange={(e) => setEditingName(e.target.value)}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter') { e.preventDefault(); void handleUpdateGroup(sub.group_id as number); }
                                      if (e.key === 'Escape') setEditingGroupId(null);
                                    }}
                                    className="bg-white border border-[#c4c8bc] px-1 py-0.5 rounded text-xs outline-none w-20"
                                    autoFocus
                                    onClick={(e) => e.stopPropagation()}
                                  />
                                  <button
                                    type="button"
                                    title="保存名称"
                                    onClick={(e) => { e.stopPropagation(); void handleUpdateGroup(sub.group_id as number); }}
                                    className="text-emerald-700"
                                  >
                                    <Check className="h-3.5 w-3.5" />
                                  </button>
                                  <button
                                    type="button"
                                    title="取消编辑"
                                    onClick={(e) => { e.stopPropagation(); setEditingGroupId(null); }}
                                    className="text-slate-500"
                                  >
                                    <X className="h-3.5 w-3.5" />
                                  </button>
                                </>
                              ) : (
                                <span className="truncate">{GROUP_ICONS[sub.group_icon || 'folder'] || GROUP_ICONS.folder} {sub.group_name}</span>
                              )}
                            </div>

                          </div>
                          {getSubGroups(sub.group_id as number).map((child) => (
                            <div key={child.group_id} onClick={() => { setSelectedGroupId(child.group_id); setSelectedGroupKey(child.group_key); }} className={`ml-4 flex items-center gap-1.5 rounded px-2 py-1 text-xs cursor-pointer ${selectedGroupId === child.group_id ? 'bg-[#4a7c59]/20 text-[#4a7c59] font-bold' : 'text-[#686d68] hover:bg-[#faf6f0]'}`}>
                              <ChevronRight className="h-3 w-3 shrink-0" /><span className="truncate">{GROUP_ICONS[child.group_icon || 'folder'] || GROUP_ICONS.folder} {child.group_name}</span>
                            </div>
                          ))}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* 右侧自选股票列表 */}
        <div className="bg-white/80 p-4 rounded-xl border border-[#c4c8bc]/60 shadow-xs space-y-3 lg:col-span-3">
          <div className="flex items-center justify-between border-b border-[#c4c8bc]/40 pb-2">
            <span className="font-bold text-xs text-[#2e3230]">
              {selectedGroupKey === '__ai_pool__'
                ? 'AI 分析池'
                : selectedGroupKey === null
                ? '全部自选股'
                : `分组: ${groups.find((g) => g.group_key === selectedGroupKey)?.group_name || '已选分组'}`}
            </span>
            <div className="flex items-center gap-3">
              <button
                type="button"
                disabled={!selectedTradePlanStock}
                onClick={() => selectedTradePlanStock && onCreateTradePlan?.(selectedTradePlanStock)}
                title={selectedTradePlanStock ? `为 ${selectedTradePlanStock.name} 创建交易计划` : '请先选择一只自选股'}
                className="inline-flex items-center gap-1 rounded-md bg-[#0f5238] px-2.5 py-1.5 text-[11px] font-black text-white transition hover:bg-[#0b422e] disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ClipboardList className="h-3.5 w-3.5" />
                创建交易计划
              </button>
              <div className="flex items-center gap-1 rounded-lg border border-[#c4c8bc]/50 bg-white px-2.5 py-1.5 text-xs">
                <Search className="h-3.5 w-3.5 text-[#686d68]" />
                <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="搜索代码、名称、行业" className="w-36 bg-transparent outline-none text-[#2e3230]" />
              </div>
              <span className="text-[11px] font-mono font-bold text-[#686d68]">匹配 {filteredStocks.length} 只股票</span>
            </div>
          </div>

          {stockListError && (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              <span>{stockListError}</span>
              <button
                type="button"
                onClick={() => {
                  if (selectedGroupKey === '__ai_pool__') {
                    setStockListError(null);
                    return;
                  }
                  fetchStocks(selectedGroupKey);
                }}
                className="shrink-0 rounded-md border border-rose-300 bg-white px-2 py-1 font-bold hover:bg-rose-100"
              >
                重试
              </button>
            </div>
          )}

          <div className="overflow-x-auto rounded-lg border border-[#c4c8bc]/50">
            <table className="w-full text-left border-collapse text-xs">
              <thead className="bg-[#f0ece4] text-[#4a4e4a] font-bold border-b border-[#c4c8bc]/60">
                <tr>
                  <th className="py-2.5 px-3">代码 & 名称</th>
                  <th className="py-2.5 px-3">技术快照</th>
                  <th className="py-2.5 px-3">基本面研究</th>
                  <th className="py-2.5 px-3">AI 研究</th>
                  <th className="py-2.5 px-3">所属行业</th>
                  <th className="py-2.5 px-3">加入时间</th>
                  <th className="py-2.5 px-3 text-center">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#c4c8bc]/30 bg-white/90">
                {loading ? (
                  <tr>
                    <td colSpan={7} className="py-8 text-center text-slate-400 font-bold">
                      正在读取自选股...
                    </td>
                  </tr>
                ) : filteredStocks.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-slate-400 font-bold space-y-2">
                      <Star className="w-8 h-8 mx-auto text-amber-300" />
                      <div>该分组下暂无自选股票</div>
                      <div className="text-[11px] font-normal text-slate-400">可在选股列表或 K 线弹窗中点击 +号 快速添加</div>
                    </td>
                  </tr>
                ) : (
                  filteredStocks.map((stock) => (
                    <tr
                      key={stock.asset_code}
                      onClick={() => openDetail(stock)}
                      className={`cursor-pointer transition ${selectedTradePlanStock?.asset_code === stock.asset_code ? 'bg-[#e7f0e9]' : 'hover:bg-[#f7f5f0]/80'}`}
                    >
                      <td className="py-3 px-3 space-y-0.5 select-text" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center gap-1.5">
                          <button
                            onClick={() => handleRemoveStock(stock.asset_code)}
                            className="w-4 h-4 rounded-full bg-rose-100 hover:bg-rose-200 text-rose-700 font-black text-xs flex items-center justify-center shrink-0"
                            title="从自选股中移除 (-)"
                          >
                            -
                          </button>
                          <span className="font-mono font-black text-xs text-slate-900 select-text cursor-text">
                            {stock.asset_code}
                          </span>
                        </div>
                        <div className="font-black text-xs text-slate-800 select-text cursor-text pl-5">
                          {stock.name}
                        </div>
                      </td>

                      <td className="py-3 px-3 min-w-30">
                        {stock.research_as_of_date ? (
                          <div className="space-y-1">
                            <div className="font-black text-slate-900">{Number(stock.aprev2_score ?? 0).toFixed(1)} 分</div>
                            <span className="inline-flex rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[11px] font-bold text-emerald-800">
                              {technicalStatusText[String(stock.aprev2_status || '')] || stock.aprev2_status || '已生成'}
                            </span>
                            <div className="font-mono text-[10px] text-slate-400">快照 {formatResearchDate(stock.research_as_of_date)}</div>
                          </div>
                        ) : <span className="text-[11px] font-bold text-slate-400">尚无技术快照</span>}
                      </td>

                      <td className="py-3 px-3 min-w-48">
                        {stock.fundamental_filter_state ? (
                          <div className="flex max-w-60 flex-wrap gap-1">
                            <span className={`rounded border px-1.5 py-0.5 text-[11px] font-bold ${stock.fundamental_filter_state === 'FUNDAMENTAL_POSITIVE' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : stock.fundamental_filter_state === 'FUNDAMENTAL_RISK' ? 'border-rose-200 bg-rose-50 text-rose-800' : 'border-sky-200 bg-sky-50 text-sky-800'}`}>
                              {fundamentalStatusText[String(stock.fundamental_filter_state)] || stock.fundamental_filter_state}
                            </span>
                            {(stock.fact_tags_json || []).slice(0, 3).map((tag, index) => (
                              <span key={`${tag.label || 'fact'}-${index}`} className={`rounded border px-1.5 py-0.5 text-[11px] font-bold ${tag.tone === 'RISK' ? 'border-rose-200 bg-rose-50 text-rose-800' : tag.tone === 'POSITIVE' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                                {tag.label || '财务事实'}
                              </span>
                            ))}
                          </div>
                        ) : <span className="text-[11px] font-bold text-slate-400">尚未进行基本面研究</span>}
                      </td>

                      <td className="py-3 px-3 min-w-30">
                        {aiResearchRunningCodes.includes(stock.asset_code) ? (
                          <span className="inline-flex items-center gap-1 rounded border border-violet-200 bg-violet-50 px-1.5 py-0.5 text-[11px] font-bold text-violet-800"><Loader2 className="h-3 w-3 animate-spin" />分析中</span>
                        ) : stock.ai_status ? (
                          <div className="space-y-1">
                            <span className={`inline-flex rounded border px-1.5 py-0.5 text-[11px] font-bold ${stock.ai_status === 'READY' ? 'border-violet-200 bg-violet-50 text-violet-800' : stock.ai_status === 'STALE' ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-rose-200 bg-rose-50 text-rose-800'}`}>
                              {aiStatusText[String(stock.ai_status)] || stock.ai_status}
                            </span>
                            <div className="font-mono text-[10px] text-slate-400">{formatResearchDate(stock.ai_as_of_date)}</div>
                          </div>
                        ) : <span className="text-[11px] font-bold text-slate-400">尚未进行 AI 研究</span>}
                      </td>

                      <td className="py-3 px-3">
                        <span className="rounded bg-slate-100 text-slate-700 px-2 py-0.5 text-[11px] font-bold">
                          {stock.industry}
                        </span>
                      </td>

                      <td className="py-3 px-3 font-mono text-[11px] text-slate-500">
                        {stock.created_at ? stock.created_at.slice(0, 10) : '近期'}
                      </td>

                      <td className="py-3 px-3 text-center">
                        <div className="flex items-center justify-center gap-1.5">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRemoveStock(stock.asset_code);
                            }}
                            className="inline-flex items-center gap-1 px-2 py-1 text-[11px] font-bold rounded-md bg-rose-50 text-rose-700 hover:bg-rose-100 border border-rose-200 transition"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                            移除
                          </button>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              onCreateTradePlan?.(stock);
                            }}
                            className="inline-flex items-center gap-1 rounded-md border border-[#2d6a4f]/25 bg-[#e7f0e9] px-2 py-1 text-[11px] font-bold text-[#2d6a4f] transition hover:bg-[#d5e8da]"
                            title={`为 ${stock.name} 创建 OPEN 建仓计划`}
                          >
                            <ClipboardList className="h-3.5 w-3.5" />
                            交易
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* 新建分组 Modal */}
      {showAddGroupModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4">
          <div className="bg-white rounded-xl p-5 w-full max-w-sm border border-[#c4c8bc]/60 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b pb-2">
              <h3 className="font-bold text-sm text-[#2e3230] flex items-center gap-1.5">
                <FolderPlus className="w-4 h-4 text-[#4a7c59]" />
                <span>{parentGroupId ? '新建子分组' : '新建自定义分组'}</span>
              </h3>
              <button onClick={() => setShowAddGroupModal(false)} className="text-slate-400 hover:text-slate-700 font-bold">
                ✕
              </button>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-bold text-[#686d68]">分组名称:</label>
              <input
                type="text"
                value={newGroupName}
                onChange={(e) => setNewGroupName(e.target.value)}
                placeholder="如: 半导体、AI主线、算力..."
                className="w-full bg-slate-50 border border-slate-300 rounded-lg px-3 py-1.5 text-xs font-bold outline-none focus:border-[#4a7c59]"
                autoFocus
              />
            </div>

            <div className="space-y-2">
              <label className="text-xs font-bold text-[#686d68]">选择图标:</label>
              <div className="flex flex-wrap gap-2">
                {Object.entries(GROUP_ICONS).map(([key, glyph]) => (
                  <button key={key} type="button" onClick={() => setNewGroupIcon(key)} aria-label={`选择${key}图标`} aria-pressed={newGroupIcon === key} className={`h-9 w-9 rounded-lg border text-lg ${newGroupIcon === key ? 'border-[#4a7c59] bg-[#e7f0e9]' : 'border-slate-200 hover:bg-slate-50'}`}>{glyph}</button>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={() => setShowAddGroupModal(false)}
                className="px-3 py-1.5 bg-slate-100 text-slate-600 text-xs font-bold rounded-lg hover:bg-slate-200"
              >
                取消
              </button>
              <button
                onClick={handleCreateGroup}
                className="px-4 py-1.5 bg-[#4a7c59] text-white text-xs font-bold rounded-lg hover:bg-[#3b6447]"
              >
                确认创建
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 股票详情抽屉 */}
      {detailStock && (
        <SecondaryStockDetailDrawer
          isOpen={true}
          onClose={() => setDetailStock(null)}
          tsCode={detailStock.tsCode}
          asOfDate={detailStock.asOfDate}
          stockName={detailStock.stockName}
          aiRunning={aiResearchRunningCodes.includes(detailStock.tsCode)}
          onTriggerThemeMatch={triggerThemeMatch}
          onTriggerAI={triggerAiResearch}
        />
      )}
    </div>
  );
}
