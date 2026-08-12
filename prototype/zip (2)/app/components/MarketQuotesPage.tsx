'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import dynamic from 'next/dynamic';
import {
  Search,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  ArrowUp,
  ArrowDown,
  X,
  Calendar,
  Zap,
  CheckCircle2,
  ChevronRight
} from 'lucide-react';

const KLineModal = dynamic(() => import('./KLineModal'), { ssr: false });

export interface StockQuote {
  code: string;
  name: string;
  industry?: string;
  price: number;
  pct_chg: number;
  change: number;
  volume: number;
  amount: number;
  amplitude: number;
  turnover: number;
  speed: number;
  net_quantity: number;
  net_inflow: number;
  open: number;
  high: number;
  low: number;
  pre_close: number;
}

export interface BoardQuote {
  name: string;
  stock_count: number;
  pct_chg: number;
  amount: number;
  top_stock_code: string;
  top_stock_name: string;
  top_stock_pct: number;
}

export interface FreshnessInfo {
  daily_market_date?: string;
  latest_open_trade_date?: string;
  is_up_to_date?: boolean;
}

export interface TaskStatus {
  status?: 'idle' | 'running' | 'RUNNING' | 'success' | 'failed' | 'cancelled';
  progress?: number;
  step_message?: string;
  error?: string;
}

interface MarketQuotesPageProps {
  apiHost?: string;
}

export default function MarketQuotesPage({
  apiHost = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL || 'http://127.0.0.1:18080',
}: MarketQuotesPageProps) {
  const [board, setBoard] = useState<string>('all');
  const [selectedIndustry, setSelectedIndustry] = useState<string | null>(null);

  const [keyword, setKeyword] = useState<string>('');
  const [searchInput, setSearchInput] = useState<string>('');
  const [sortBy, setSortBy] = useState<string>('pct_chg');
  const [sortOrder, setSortOrder] = useState<'desc' | 'asc'>('desc');

  // 数据更新新鲜度与后台任务 Status
  const [freshness, setFreshness] = useState<FreshnessInfo>({});
  const [taskStatus, setTaskStatus] = useState<TaskStatus>({ status: 'idle', progress: 0 });

  // 股票列表 State
  const [stocks, setStocks] = useState<StockQuote[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(false);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [hasMore, setHasMore] = useState<boolean>(true);
  const [offset, setOffset] = useState<number>(0);

  // 板块列表 State
  const [boards, setBoards] = useState<BoardQuote[]>([]);
  const [boardTotalCount, setBoardTotalCount] = useState<number>(0);

  // 智能下拉推荐 State
  const [suggestions, setSuggestions] = useState<StockQuote[]>([]);
  const [showSuggestions, setShowSuggestions] = useState<boolean>(false);
  const [suggestHighlightedIndex, setSuggestHighlightedIndex] = useState<number>(-1);

  const [selectedIndex, setSelectedIndex] = useState<number>(0);
  const [activeStock, setActiveStock] = useState<StockQuote | null>(null);
  const [isKLineOpen, setIsKLineOpen] = useState<boolean>(false);

  const tableContainerRef = useRef<HTMLDivElement>(null);
  const tableBodyRef = useRef<HTMLTableSectionElement>(null);
  const searchContainerRef = useRef<HTMLDivElement>(null);

  // 判断当前是展现申万板块大盘表格，还是股票行情表格
  const isBoardView = board === 'sw_industry' && !selectedIndustry;

  const formatDateStr = (dateStr?: string) => {
    if (!dateStr || dateStr.length !== 8) return dateStr || '未同步';
    return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`;
  };

  const formatAmount = (val: number) => {
    if (!val) return '0.00';
    const absVal = Math.abs(val);
    if (absVal >= 100000000) {
      return (val / 100000000).toFixed(2) + '亿';
    }
    if (absVal >= 10000) {
      return (val / 10000).toFixed(2) + '万';
    }
    return val.toFixed(2);
  };

  // 获取新鲜度
  const fetchFreshness = useCallback(async () => {
    try {
      const res = await fetch(`${apiHost}/api/screening/freshness`);
      if (res.ok) {
        const data = await res.json();
        setFreshness(data);
      }
    } catch (e) {
      console.error('Failed to fetch freshness:', e);
    }
  }, [apiHost]);

  // 检查任务状态
  const checkTaskStatus = useCallback(async () => {
    try {
      const res = await fetch(`${apiHost}/api/screening/status`);
      if (res.ok) {
        const data = await res.json();
        setTaskStatus(data);
        return data;
      }
    } catch (e) {
      console.error('Failed to check task status:', e);
    }
    return null;
  }, [apiHost]);

  // 挂载与轮询
  useEffect(() => {
    fetchFreshness();
    checkTaskStatus();

    const interval = setInterval(async () => {
      const status = await checkTaskStatus();
      if (status?.status === 'success' || status?.status === 'failed' || status?.status === 'cancelled') {
        fetchFreshness();
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [fetchFreshness, checkTaskStatus]);

  // 启动后台异步数据补全
  const handleStartSyncData = async () => {
    try {
      setTaskStatus({ status: 'running', progress: 10, step_message: '正在启动后台补全...' });
      const res = await fetch(`${apiHost}/api/screening/data-sync/async`, { method: 'POST' });
      if (!res.ok) {
        throw new Error('启动后台补全失败');
      }
      checkTaskStatus();
    } catch (e) {
      console.error('Start sync failed:', e);
      alert('启动数据补全任务失败，请稍后重试');
    }
  };

  // 取消后台异步数据补全
  const handleCancelSyncData = async () => {
    try {
      await fetch(`${apiHost}/api/screening/data-sync/cancel`, { method: 'POST' });
      checkTaskStatus();
    } catch (e) {
      console.error('Cancel sync failed:', e);
    }
  };

  // 全局全量获取股票行情 (支持申万行业精准下钻)
  const fetchQuotes = useCallback(
    async (
      currentOffset: number,
      isAppend: boolean = false,
      currentBoard = board,
      currentKeyword = keyword,
      currentSortBy = sortBy,
      currentSortOrder = sortOrder,
      industryFilter = selectedIndustry
    ) => {
      if (isAppend) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }

      try {
        const limit = currentOffset === 0 ? 100 : 50;
        const params = new URLSearchParams({
          offset: currentOffset.toString(),
          limit: limit.toString(),
          sort_by: currentSortBy,
          sort_order: currentSortOrder,
          board: currentBoard.startsWith('sw_') ? 'all' : currentBoard,
          keyword: currentKeyword,
        });

        if (industryFilter) {
          params.append('industry', industryFilter);
        }

        const res = await fetch(`${apiHost}/api/market/quotes?${params.toString()}`);
        if (!res.ok) {
          throw new Error('获取行情数据失败');
        }
        const data = await res.json();

        if (isAppend) {
          setStocks((prev) => [...prev, ...(data.items || [])]);
        } else {
          setStocks(data.items || []);
          setSelectedIndex(0);
        }
        setTotalCount(data.total || 0);
        setHasMore(data.has_more || false);
        setOffset(currentOffset);
      } catch (err) {
        console.error('Fetch market quotes error:', err);
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [apiHost, board, keyword, sortBy, sortOrder, selectedIndustry]
  );

  // 全局全量获取申万板块行情
  const fetchBoards = useCallback(
    async (
      currentKeyword = keyword,
      currentSortBy = sortBy,
      currentSortOrder = sortOrder
    ) => {
      setLoading(true);
      try {
        const params = new URLSearchParams({
          sort_by: currentSortBy,
          sort_order: currentSortOrder,
          keyword: currentKeyword,
        });

        const res = await fetch(`${apiHost}/api/market/boards?${params.toString()}`);
        if (!res.ok) {
          throw new Error('获取申万板块数据失败');
        }
        const data = await res.json();
        setBoards(data.items || []);
        setBoardTotalCount(data.total || 0);
        setSelectedIndex(0);
      } catch (err) {
        console.error('Fetch market boards error:', err);
      } finally {
        setLoading(false);
      }
    },
    [apiHost, keyword, sortBy, sortOrder]
  );

  // 视图或筛选改变时加载
  useEffect(() => {
    setOffset(0);
    if (isBoardView) {
      fetchBoards(keyword, sortBy, sortOrder);
    } else {
      fetchQuotes(0, false, board, keyword, sortBy, sortOrder, selectedIndustry);
    }
  }, [board, keyword, sortBy, sortOrder, selectedIndustry, isBoardView, fetchQuotes, fetchBoards]);

  // 防抖联想搜股票
  useEffect(() => {
    const term = searchInput.trim();
    if (!term) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`${apiHost}/api/market/suggest?query=${encodeURIComponent(term)}`);
        if (res.ok) {
          const data = await res.json();
          setSuggestions(data.items || []);
          setShowSuggestions(true);
          setSuggestHighlightedIndex(-1);
        }
      } catch (e) {
        console.error('Failed to fetch suggestions:', e);
      }
    }, 150);

    return () => clearTimeout(timer);
  }, [searchInput, apiHost]);

  // 点击外部关闭下拉菜单
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchContainerRef.current && !searchContainerRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    if (isBoardView) return;
    const target = e.currentTarget;
    if (loading || loadingMore || !hasMore) return;
    if (target.scrollHeight - target.scrollTop - target.clientHeight < 120) {
      const nextOffset = stocks.length;
      fetchQuotes(nextOffset, true);
    }
  };

  const handleSort = (field: string) => {
    if (sortBy === field) {
      setSortOrder((prev) => (prev === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortBy(field);
      setSortOrder('desc');
    }
  };

  const openKLine = (stock: StockQuote) => {
    setActiveStock(stock);
    setIsKLineOpen(true);
    setShowSuggestions(false);
  };

  // 点击申万行业名称直接触发钻取成分股
  const drilldownBoard = (boardName: string) => {
    setSelectedIndustry(boardName);
    setBoard('sw_industry'); // 保持选中申万板块
  };

  const handleSearchSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const query = searchInput.trim();

    if (showSuggestions && suggestHighlightedIndex >= 0 && suggestions[suggestHighlightedIndex]) {
      openKLine(suggestions[suggestHighlightedIndex]);
      return;
    }

    setKeyword(query);
    setShowSuggestions(false);

    if (query) {
      const match = suggestions.find(
        (s) => s.code.toLowerCase() === query.toLowerCase() || s.name === query
      ) || stocks.find(
        (s) => s.code.toLowerCase() === query.toLowerCase() || s.name === query
      );
      if (match) {
        openKLine(match);
      }
    }
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement)?.tagName)) {
        if (showSuggestions && suggestions.length > 0) {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setSuggestHighlightedIndex((prev) => Math.min(prev + 1, suggestions.length - 1));
            return;
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setSuggestHighlightedIndex((prev) => Math.max(prev - 1, 0));
            return;
          }
        }
        if (e.key === 'Enter') {
          handleSearchSubmit();
        }
        return;
      }

      if (isKLineOpen) return;

      if (!isBoardView) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          setSelectedIndex((prev) => {
            const next = Math.min(prev + 1, stocks.length - 1);
            scrollToRow(next);
            return next;
          });
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          setSelectedIndex((prev) => {
            const next = Math.max(prev - 1, 0);
            scrollToRow(next);
            return next;
          });
        } else if (e.key === 'Enter') {
          e.preventDefault();
          if (stocks[selectedIndex]) {
            openKLine(stocks[selectedIndex]);
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isKLineOpen, stocks, selectedIndex, showSuggestions, suggestions, suggestHighlightedIndex, isBoardView]);

  const scrollToRow = (index: number) => {
    if (!tableBodyRef.current) return;
    const row = tableBodyRef.current.children[index] as HTMLElement;
    if (row) {
      row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  };

  const handleNavigatePrev = () => {
    if (selectedIndex > 0) {
      const newIdx = selectedIndex - 1;
      setSelectedIndex(newIdx);
      setActiveStock(stocks[newIdx]);
    }
  };

  const handleNavigateNext = () => {
    if (selectedIndex < stocks.length - 1) {
      const newIdx = selectedIndex + 1;
      setSelectedIndex(newIdx);
      setActiveStock(stocks[newIdx]);
    }
  };

  const isTaskRunning = taskStatus.status === 'running' || taskStatus.status === 'RUNNING';

  return (
    <div className="flex flex-col h-[calc(100vh-64px)] bg-[#faf6f0] text-[#2e3230] font-sans overflow-hidden select-none p-4 lg:p-6 gap-3">
      {/* 顶部控制栏：分类 Tag + 日期 Label + 补齐图标按钮 */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 bg-white rounded-lg border border-[#c4c8bc]/40 shadow-xs">
        {/* 板块 Tag */}
        <div className="flex items-center space-x-1.5 overflow-x-auto">
          {[
            { id: 'all', label: '全部A股' },
            { id: 'sw_industry', label: '申万板块' },
            { id: 'cyb', label: '创业板' },
            { id: 'kcb', label: '科创板' },
            { id: 'sh', label: '沪A' },
            { id: 'sz', label: '深A' },
            { id: 'new', label: '次新股' },
          ].map((item) => (
            <button
              key={item.id}
              onClick={() => {
                setBoard(item.id);
                setSelectedIndustry(null);
                setKeyword('');
              }}
              className={`px-3 py-1.5 text-xs font-bold rounded-md transition-all ${
                board === item.id
                  ? 'bg-[#4a7c59] text-white shadow-xs'
                  : 'text-[#4a4e4a] bg-[#f0ece4]/60 hover:bg-[#e4e0d8] hover:text-[#2e3230]'
              }`}
            >
              {item.label}
            </button>
          ))}

          {/* 如果从申万板块下钻到了某板块成分股，显示明确下钻面包屑标签 */}
          {selectedIndustry && (
            <div className="flex items-center space-x-1 px-2.5 py-1 text-xs bg-[#e8f0e9] text-[#4a7c59] rounded-md font-bold border border-[#4a7c59]/40 animate-fadeIn">
              <span>成分股：{selectedIndustry}</span>
              <button
                onClick={() => {
                  setSelectedIndustry(null);
                  setKeyword('');
                }}
                className="hover:text-red-600 ml-1"
                title="返回申万板块列表"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>

        {/* 顶部右侧：纯文本日期 Label + 精简图标补齐按钮 */}
        <div className="flex items-center space-x-3">
          <div className="flex items-center space-x-1.5 text-xs text-[#686d68] font-medium">
            <Calendar className="w-3.5 h-3.5 text-[#4a7c59]" />
            <span>行情日期:</span>
            <strong className="text-[#2e3230] font-mono font-bold">
              {formatDateStr(freshness.daily_market_date)}
            </strong>
          </div>

          <button
            onClick={handleStartSyncData}
            disabled={isTaskRunning}
            title={isTaskRunning ? "后台数据补全中..." : freshness.is_up_to_date === false ? "点击补齐全库最新行情与30分钟K线" : "补齐/刷新最新数据"}
            className={`p-1.5 rounded-md transition-all shadow-xs flex items-center justify-center ${
              isTaskRunning
                ? 'bg-gray-100 text-gray-400 cursor-not-allowed border border-gray-200'
                : freshness.is_up_to_date === false
                ? 'bg-[#d97706] text-white hover:bg-[#b45309] animate-pulse'
                : 'bg-[#f0ece4] text-[#4a7c59] hover:bg-[#e4e0d8] border border-[#c4c8bc]/40'
            }`}
          >
            <Zap className={`w-4 h-4 ${isTaskRunning ? 'animate-spin text-gray-400' : ''}`} />
          </button>

          {/* 全库实时联想搜索框 */}
          <div ref={searchContainerRef} className="relative flex items-center space-x-2">
            <form onSubmit={handleSearchSubmit} className="relative">
              <input
                type="text"
                placeholder={isBoardView ? "搜索申万板块..." : "搜索代码/名称 (如 30027)"}
                value={searchInput}
                onFocus={() => {
                  if (!isBoardView && suggestions.length > 0) setShowSuggestions(true);
                }}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-60 bg-[#f0ece4]/50 border border-[#c4c8bc]/60 rounded-md px-3 py-1.5 pl-8 text-xs text-[#2e3230] placeholder-[#8c928c] focus:outline-none focus:border-[#4a7c59] focus:bg-white transition-all shadow-xs"
              />
              <Search className="w-3.5 h-3.5 text-[#8c928c] absolute left-2.5 top-2.5" />
              {searchInput && (
                <button
                  type="button"
                  onClick={() => {
                    setSearchInput('');
                    setKeyword('');
                    setSuggestions([]);
                    setShowSuggestions(false);
                  }}
                  className="absolute right-2.5 top-2.5 text-[#8c928c] hover:text-[#2e3230]"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </form>

            {/* 智能联想下拉菜单 */}
            {!isBoardView && showSuggestions && suggestions.length > 0 && (
              <div className="absolute top-full left-0 mt-1.5 w-80 bg-white rounded-lg shadow-xl border border-[#c4c8bc]/60 overflow-hidden z-50 max-h-80 overflow-y-auto divide-y divide-[#f0ece4]">
                <div className="px-3 py-1.5 bg-[#f0ece4]/60 text-[11px] font-bold text-[#686d68] flex justify-between">
                  <span>匹配股票 (全库 5539 只)</span>
                  <span>回车全局搜索</span>
                </div>
                {suggestions.map((item, i) => {
                  const isHighlight = i === suggestHighlightedIndex;
                  const isUp = item.pct_chg > 0;
                  const isDown = item.pct_chg < 0;
                  const colorClass = isUp ? 'text-[#d97706]' : isDown ? 'text-[#2563eb]' : 'text-[#686d68]';

                  return (
                    <div
                      key={`${item.code}-${i}`}
                      onClick={() => openKLine(item)}
                      onMouseEnter={() => setSuggestHighlightedIndex(i)}
                      className={`flex items-center justify-between px-3 py-2 text-xs cursor-pointer transition-colors ${
                        isHighlight ? 'bg-[#e8f0e9] font-semibold text-[#2e3230]' : 'hover:bg-[#f5f2eb]'
                      }`}
                    >
                      <div className="flex items-center space-x-2">
                        <span className="font-mono font-bold text-[#4a7c59]">{item.code}</span>
                        <span className="font-bold text-[#2e3230]">{item.name}</span>
                      </div>
                      <div className="flex items-center space-x-3 font-mono">
                        <span className="text-[#4a4e4a]">{item.price.toFixed(2)}</span>
                        <span className={`font-bold ${colorClass}`}>
                          {item.pct_chg > 0 ? `+${item.pct_chg.toFixed(2)}%` : `${item.pct_chg.toFixed(2)}%`}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            <button
              onClick={() => {
                if (isBoardView) {
                  fetchBoards(keyword, sortBy, sortOrder);
                } else {
                  fetchQuotes(0, false, board, keyword, sortBy, sortOrder, selectedIndustry);
                }
              }}
              className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-bold text-[#4a4e4a] bg-[#f0ece4] hover:bg-[#e4e0d8] rounded-md transition-colors border border-[#c4c8bc]/40"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-[#4a7c59]' : ''}`} />
              <span>刷新</span>
            </button>
          </div>
        </div>
      </div>

      {/* 后台数据补全进度条卡片 */}
      {isTaskRunning && (
        <div className="px-4 py-3 bg-white rounded-lg border border-[#4a7c59]/40 shadow-sm flex flex-col gap-2 transition-all animate-fadeIn">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center space-x-2">
              <Zap className="w-4 h-4 text-[#4a7c59] animate-bounce" />
              <span className="font-bold text-[#2e3230]">正在后台更新日线与 30 分钟 K 线...</span>
              <span className="text-[#686d68] text-[11px] font-mono">({taskStatus.step_message})</span>
            </div>
            <div className="flex items-center space-x-3">
              <span className="font-mono font-bold text-[#4a7c59] text-sm">{taskStatus.progress || 10}%</span>
              <button
                onClick={handleCancelSyncData}
                className="px-2 py-0.5 text-[11px] font-bold text-red-600 bg-red-50 hover:bg-red-100 rounded border border-red-200 transition-colors"
              >
                取消补齐
              </button>
            </div>
          </div>
          <div className="w-full bg-[#f0ece4] h-2 rounded-full overflow-hidden">
            <div
              className="bg-[#4a7c59] h-full rounded-full transition-all duration-500 ease-out relative"
              style={{ width: `${taskStatus.progress || 10}%` }}
            >
              <div className="absolute inset-0 bg-white/20 animate-pulse"></div>
            </div>
          </div>
        </div>
      )}

      {/* 补齐成功提示条 */}
      {taskStatus.status === 'success' && (
        <div className="px-4 py-2 bg-[#e8f0e9] rounded-lg border border-[#4a7c59]/30 text-xs text-[#4a7c59] font-bold flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <CheckCircle2 className="w-4 h-4 text-[#4a7c59]" />
            <span>{taskStatus.step_message || '后台日线与 30 分钟 K 线数据已全部成功补齐！'}</span>
          </div>
          <button
            onClick={() => setTaskStatus({ status: 'idle' })}
            className="text-[#686d68] hover:text-[#2e3230]"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* 主表格卡片 */}
      <div
        ref={tableContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-auto rounded-lg border border-[#c4c8bc]/40 bg-white shadow-xs custom-scrollbar"
      >
        {isBoardView ? (
          /* 申万板块大盘表格 (无右侧操作列，行业名称无前置图标，直接点击钻取) */
          <table className="w-full text-left border-collapse table-fixed text-xs">
            <thead className="sticky top-0 z-10 bg-[#f0ece4] border-b border-[#c4c8bc]/60 text-[#4a4e4a] font-bold">
              <tr>
                <th className="w-16 py-2.5 px-4 text-center">序号</th>
                <th className="w-48 py-2.5 px-4">申万板块名称</th>
                <th
                  onClick={() => handleSort('stock_count')}
                  className="w-36 py-2.5 px-4 text-right cursor-pointer hover:text-[#4a7c59]"
                >
                  <div className="flex items-center justify-end space-x-1">
                    <span>成分股家数</span>
                    {sortBy === 'stock_count' && (
                      sortOrder === 'desc' ? <ArrowDown className="w-3 h-3 text-[#d97706]" /> : <ArrowUp className="w-3 h-3 text-[#2563eb]" />
                    )}
                  </div>
                </th>
                <th
                  onClick={() => handleSort('pct_chg')}
                  className="w-36 py-2.5 px-4 text-right cursor-pointer hover:text-[#4a7c59]"
                >
                  <div className="flex items-center justify-end space-x-1">
                    <span>平均涨跌幅%</span>
                    {sortBy === 'pct_chg' && (
                      sortOrder === 'desc' ? <ArrowDown className="w-3 h-3 text-[#d97706]" /> : <ArrowUp className="w-3 h-3 text-[#2563eb]" />
                    )}
                  </div>
                </th>
                <th
                  onClick={() => handleSort('amount')}
                  className="w-44 py-2.5 px-4 text-right cursor-pointer hover:text-[#4a7c59]"
                >
                  <div className="flex items-center justify-end space-x-1">
                    <span>板块总成交额</span>
                    {sortBy === 'amount' && (
                      sortOrder === 'desc' ? <ArrowDown className="w-3 h-3 text-[#d97706]" /> : <ArrowUp className="w-3 h-3 text-[#2563eb]" />
                    )}
                  </div>
                </th>
                <th className="w-64 py-2.5 px-4">领涨股票</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e4e0d8]">
              {boards.map((b, idx) => {
                const isUp = b.pct_chg > 0;
                const isDown = b.pct_chg < 0;
                const colorClass = isUp ? 'text-[#d97706]' : isDown ? 'text-[#2563eb]' : 'text-[#686d68]';

                return (
                  <tr
                    key={`${b.name}-${idx}`}
                    onClick={() => drilldownBoard(b.name)}
                    className="hover:bg-[#f5f2eb] transition-all cursor-pointer text-[#4a4e4a]"
                    title="点击查看该行业成分股列表"
                  >
                    <td className="py-3 px-4 text-center text-[#8c928c] font-mono">{idx + 1}</td>
                    <td className="py-3 px-4 font-bold text-[#2e3230] text-sm hover:text-[#4a7c59]">
                      <span>{b.name}</span>
                    </td>
                    <td className="py-3 px-4 text-right font-mono font-semibold text-[#2e3230]">
                      {b.stock_count} 只
                    </td>
                    <td className={`py-3 px-4 text-right font-mono font-bold text-sm ${colorClass}`}>
                      {b.pct_chg > 0 ? `+${b.pct_chg.toFixed(2)}%` : `${b.pct_chg.toFixed(2)}%`}
                    </td>
                    <td className="py-3 px-4 text-right font-mono text-[#686d68] font-semibold">
                      {formatAmount(b.amount)}
                    </td>
                    <td className="py-3 px-4 font-medium">
                      {b.top_stock_name ? (
                        <div className="flex items-center space-x-2">
                          <span className="font-mono text-[#4a7c59] font-bold">{b.top_stock_code}</span>
                          <span className="text-[#2e3230]">{b.top_stock_name}</span>
                          <span className={`font-mono text-xs font-bold ${b.top_stock_pct > 0 ? 'text-[#d97706]' : 'text-[#2563eb]'}`}>
                            {b.top_stock_pct > 0 ? `+${b.top_stock_pct.toFixed(2)}%` : `${b.top_stock_pct.toFixed(2)}%`}
                          </span>
                        </div>
                      ) : (
                        <span className="text-[#8c928c]">-</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          /* 股票行情列表 (包含全量股票或下钻的申万成分股) */
          <table className="w-full text-left border-collapse table-fixed text-xs">
            <thead className="sticky top-0 z-10 bg-[#f0ece4] border-b border-[#c4c8bc]/60 text-[#4a4e4a] font-bold">
              <tr>
                <th className="w-12 py-2.5 px-3 text-center">序号</th>
                <th className="w-20 py-2.5 px-3">代码</th>
                <th className="w-28 py-2.5 px-3">名称</th>
                <th className="w-28 py-2.5 px-3">申万行业</th>
                <th
                  onClick={() => handleSort('pct_chg')}
                  className="w-24 py-2.5 px-3 text-right cursor-pointer hover:text-[#4a7c59]"
                >
                  <div className="flex items-center justify-end space-x-1">
                    <span>涨跌幅%</span>
                    {sortBy === 'pct_chg' && (
                      sortOrder === 'desc' ? <ArrowDown className="w-3 h-3 text-[#d97706]" /> : <ArrowUp className="w-3 h-3 text-[#2563eb]" />
                    )}
                  </div>
                </th>
                <th
                  onClick={() => handleSort('price')}
                  className="w-20 py-2.5 px-3 text-right cursor-pointer hover:text-[#4a7c59]"
                >
                  <div className="flex items-center justify-end space-x-1">
                    <span>现价</span>
                    {sortBy === 'price' && (
                      sortOrder === 'desc' ? <ArrowDown className="w-3 h-3 text-[#d97706]" /> : <ArrowUp className="w-3 h-3 text-[#2563eb]" />
                    )}
                  </div>
                </th>
                <th
                  onClick={() => handleSort('speed')}
                  className="w-20 py-2.5 px-3 text-right cursor-pointer hover:text-[#4a7c59]"
                >
                  <div className="flex items-center justify-end space-x-1">
                    <span>涨速%</span>
                    {sortBy === 'speed' && (
                      sortOrder === 'desc' ? <ArrowDown className="w-3 h-3 text-[#d97706]" /> : <ArrowUp className="w-3 h-3 text-[#2563eb]" />
                    )}
                  </div>
                </th>
                <th
                  onClick={() => handleSort('change')}
                  className="w-20 py-2.5 px-3 text-right cursor-pointer hover:text-[#4a7c59]"
                >
                  <span>涨跌</span>
                </th>
                <th
                  onClick={() => handleSort('net_quantity')}
                  className="w-24 py-2.5 px-3 text-right cursor-pointer hover:text-[#4a7c59]"
                >
                  <span>主力净量</span>
                </th>
                <th
                  onClick={() => handleSort('net_inflow')}
                  className="w-28 py-2.5 px-3 text-right cursor-pointer hover:text-[#4a7c59]"
                >
                  <div className="flex items-center justify-end space-x-1">
                    <span>主力净流入</span>
                    {sortBy === 'net_inflow' && (
                      sortOrder === 'desc' ? <ArrowDown className="w-3 h-3 text-[#d97706]" /> : <ArrowUp className="w-3 h-3 text-[#2563eb]" />
                    )}
                  </div>
                </th>
                <th
                  onClick={() => handleSort('amount')}
                  className="w-28 py-2.5 px-3 text-right cursor-pointer hover:text-[#4a7c59]"
                >
                  <span>成交额</span>
                </th>
                <th
                  onClick={() => handleSort('turnover')}
                  className="w-20 py-2.5 px-3 text-right cursor-pointer hover:text-[#4a7c59]"
                >
                  <span>换手%</span>
                </th>
                <th className="w-20 py-2.5 px-3 text-right">最高</th>
                <th className="w-20 py-2.5 px-3 text-right">最低</th>
              </tr>
            </thead>
            <tbody ref={tableBodyRef} className="divide-y divide-[#e4e0d8]">
              {stocks.map((stock, idx) => {
                const isSelected = selectedIndex === idx;
                const isUp = stock.pct_chg > 0;
                const isDown = stock.pct_chg < 0;
                const colorClass = isUp ? 'text-[#d97706]' : isDown ? 'text-[#2563eb]' : 'text-[#686d68]';

                return (
                  <tr
                    key={`${stock.code}-${idx}`}
                    onClick={() => setSelectedIndex(idx)}
                    onDoubleClick={() => openKLine(stock)}
                    className={`transition-all cursor-pointer ${
                      isSelected
                        ? 'bg-[#e8f0e9] text-[#2e3230] border-l-4 border-l-[#4a7c59] font-medium'
                        : 'hover:bg-[#f5f2eb] text-[#4a4e4a]'
                    }`}
                  >
                    <td className="py-2.5 px-3 text-center text-[#8c928c] font-mono">{idx + 1}</td>
                    <td
                      onClick={(e) => {
                        e.stopPropagation();
                        openKLine(stock);
                      }}
                      className="py-2.5 px-3 font-mono font-bold text-[#4a7c59] hover:underline"
                    >
                      {stock.code}
                    </td>
                    <td
                      onClick={(e) => {
                        e.stopPropagation();
                        openKLine(stock);
                      }}
                      className="py-2.5 px-3 font-bold text-[#2e3230] hover:text-[#4a7c59]"
                    >
                      {stock.name}
                    </td>
                    <td className="py-2.5 px-3 font-medium text-[#4a7c59]">
                      {stock.industry || '-'}
                    </td>
                    <td className={`py-2.5 px-3 text-right font-bold font-mono ${colorClass}`}>
                      {stock.pct_chg > 0 ? `+${stock.pct_chg.toFixed(2)}%` : `${stock.pct_chg.toFixed(2)}%`}
                    </td>
                    <td className={`py-2.5 px-3 text-right font-mono font-bold ${colorClass}`}>
                      {stock.price.toFixed(2)}
                    </td>
                    <td className={`py-2.5 px-3 text-right font-mono ${stock.speed > 0 ? 'text-[#d97706]' : stock.speed < 0 ? 'text-[#2563eb]' : 'text-[#8c928c]'}`}>
                      {stock.speed > 0 ? `+${stock.speed.toFixed(2)}` : stock.speed.toFixed(2)}
                    </td>
                    <td className={`py-2.5 px-3 text-right font-mono ${colorClass}`}>
                      {stock.change > 0 ? `+${stock.change.toFixed(2)}` : stock.change.toFixed(2)}
                    </td>
                    <td className="py-2.5 px-3 text-right font-mono text-[#4a4e4a]">
                      {stock.net_quantity ? stock.net_quantity.toFixed(2) : '-'}
                    </td>
                    <td className={`py-2.5 px-3 text-right font-mono font-semibold ${stock.net_inflow > 0 ? 'text-[#d97706]' : stock.net_inflow < 0 ? 'text-[#2563eb]' : 'text-[#686d68]'}`}>
                      {formatAmount(stock.net_inflow)}
                    </td>
                    <td className="py-2.5 px-3 text-right font-mono text-[#686d68]">
                      {formatAmount(stock.amount)}
                    </td>
                    <td className="py-2.5 px-3 text-right font-mono text-[#686d68]">
                      {stock.turnover ? `${stock.turnover.toFixed(2)}%` : '-'}
                    </td>
                    <td className="py-2.5 px-3 text-right font-mono text-[#686d68]">{stock.high.toFixed(2)}</td>
                    <td className="py-2.5 px-3 text-right font-mono text-[#686d68]">{stock.low.toFixed(2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {loading && (
          <div className="py-12 text-center text-[#686d68] text-xs flex items-center justify-center space-x-2">
            <RefreshCw className="w-4 h-4 animate-spin text-[#4a7c59]" />
            <span>加载数据中...</span>
          </div>
        )}

        {!isBoardView && loadingMore && (
          <div className="py-3 text-center text-[#686d68] text-xs flex items-center justify-center space-x-2 bg-[#f0ece4]/50 border-t border-[#c4c8bc]/40">
            <RefreshCw className="w-3.5 h-3.5 animate-spin text-[#4a7c59]" />
            <span>自动加载下 50 条股票...</span>
          </div>
        )}
      </div>

      {/* 底部提示 */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 bg-white rounded-lg border border-[#c4c8bc]/40 shadow-xs text-xs text-[#686d68]">
        <div className="flex items-center space-x-2 font-medium">
          <span className="inline-block w-2 h-2 rounded-full bg-[#4a7c59]"></span>
          <span>全库全量数据实时驱动</span>
          {isBoardView && <span className="text-[#4a7c59] font-bold">| 点击申万板块名称可直接下钻成分股</span>}
        </div>
        <div className="text-[11px] text-[#8c928c] font-medium">
          💡 提示：所有表头点击均为全库全局全量排序；按 <kbd className="px-1.5 py-0.5 bg-[#f0ece4] text-[#2e3230] rounded border border-[#c4c8bc]/60 font-mono text-[10px]">↑</kbd> <kbd className="px-1.5 py-0.5 bg-[#f0ece4] text-[#2e3230] rounded border border-[#c4c8bc]/60 font-mono text-[10px]">↓</kbd> 挑选，按 <kbd className="px-1.5 py-0.5 bg-[#f0ece4] text-[#2e3230] rounded border border-[#c4c8bc]/60 font-mono text-[10px]">Enter</kbd> 唤起 K 线
        </div>
      </div>

      {/* KLineModal 弹窗整合 */}
      {isKLineOpen && activeStock && (
        <KLineModal
          assetCode={activeStock.code}
          assetName={activeStock.name}
          industry={activeStock.industry}
          isOpen={isKLineOpen}
          onClose={() => setIsKLineOpen(false)}
          onNavigatePrev={handleNavigatePrev}
          onNavigateNext={handleNavigateNext}
          hasPrev={selectedIndex > 0}
          hasNext={selectedIndex < stocks.length - 1}
          apiHost={apiHost}
        />
      )}
    </div>
  );
}
