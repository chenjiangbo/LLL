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
  ChevronRight,
  BarChart3,
  Layers,
  ListOrdered,
  Newspaper,
  Flame,
  PieChart,
  Activity,
  ExternalLink
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

export interface NewsItem {
  id: string;
  time: string;
  title: string;
  content: string;
  subjects: string[];
  level: string;
  url: string;
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
  // 4 大主子标签页: overview (大盘全景), boards (板块行情), quotes (个股行情), news (财联社 7x24 电报)
  const [mainTab, setMainTab] = useState<'overview' | 'boards' | 'quotes' | 'news'>('overview');
  
  // 板块类型: industry (申万行业), concept (题材概念)
  const [boardType, setBoardType] = useState<'industry' | 'concept'>('industry');

  const [board, setBoard] = useState<string>('all');
  const [selectedIndustry, setSelectedIndustry] = useState<string | null>(null);

  const [keyword, setKeyword] = useState<string>('');
  const [searchInput, setSearchInput] = useState<string>('');
  const [newsQuery, setNewsQuery] = useState<string>('');
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

  // 财联社电报与大盘全景 Analytics State
  const [newsList, setNewsList] = useState<NewsItem[]>([]);
  const [newsLoading, setNewsLoading] = useState<boolean>(false);
  const [analytics, setAnalytics] = useState<any>(null);

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

  // 全局全量获取板块行情 (申万行业板块 / 题材概念板块)
  const fetchBoards = useCallback(
    async (
      currentBoardType = boardType,
      currentKeyword = keyword,
      currentSortBy = sortBy,
      currentSortOrder = sortOrder
    ) => {
      setLoading(true);
      try {
        const params = new URLSearchParams({
          board_type: currentBoardType,
          sort_by: currentSortBy,
          sort_order: currentSortOrder,
          keyword: currentKeyword,
        });

        const res = await fetch(`${apiHost}/api/market/boards?${params.toString()}`);
        if (!res.ok) {
          throw new Error('获取板块数据失败');
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
    [apiHost, boardType, keyword, sortBy, sortOrder]
  );

  // 获取财联社 7x24 小时财经电报
  const fetchNews = useCallback(
    async (q = newsQuery) => {
      setNewsLoading(true);
      try {
        const params = new URLSearchParams({ q });
        const res = await fetch(`${apiHost}/api/market/news?${params.toString()}`);
        if (res.ok) {
          const data = await res.json();
          setNewsList(data.items || []);
        }
      } catch (e) {
        console.error('Fetch news error:', e);
      } finally {
        setNewsLoading(false);
      }
    },
    [apiHost, newsQuery]
  );

  // 获取大盘全景 Analytics 数据
  const fetchAnalytics = useCallback(async () => {
    try {
      const res = await fetch(`${apiHost}/api/market/analytics`);
      if (res.ok) {
        const data = await res.json();
        setAnalytics(data);
      }
    } catch (e) {
      console.error('Fetch market analytics error:', e);
    }
  }, [apiHost]);

  // 视图或 Sub-Tabs 改变时自动拉取对应数据
  useEffect(() => {
    setOffset(0);
    if (mainTab === 'overview') {
      fetchAnalytics();
    } else if (mainTab === 'boards') {
      fetchBoards(boardType, keyword, sortBy, sortOrder);
    } else if (mainTab === 'quotes') {
      fetchQuotes(0, false, board, keyword, sortBy, sortOrder, selectedIndustry);
    } else if (mainTab === 'news') {
      fetchNews(newsQuery);
    }
  }, [mainTab, boardType, board, keyword, sortBy, sortOrder, selectedIndustry, newsQuery, fetchAnalytics, fetchBoards, fetchQuotes, fetchNews]);

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
      {/* 顶部行情大功能 4 大子标签页 Navigation (全景 / 板块 / 个股 / 财联社电报) */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 bg-white rounded-lg border border-[#c4c8bc]/40 shadow-xs">
        {/* 子功能 4 大 Main Sub-Tabs */}
        <div className="flex items-center space-x-2">
          {[
            { id: 'overview', label: '大盘全景', icon: PieChart },
            { id: 'boards', label: '板块行情', icon: Layers },
            { id: 'quotes', label: '个股行情列表', icon: ListOrdered },
            { id: 'news', label: '财联社 7x24 电报', icon: Newspaper },
          ].map((tab) => {
            const Icon = tab.icon;
            const isActive = mainTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => {
                  setMainTab(tab.id as any);
                  setSelectedIndustry(null);
                  setKeyword('');
                }}
                className={`flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-bold rounded-md transition-all ${
                  isActive
                    ? 'bg-[#4a7c59] text-white shadow-xs scale-102'
                    : 'text-[#4a4e4a] bg-[#f0ece4]/60 hover:bg-[#e4e0d8] hover:text-[#2e3230]'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{tab.label}</span>
              </button>
            );
          })}

          {/* 如果从板块下钻到了某成份股，显示下钻面包屑标签 */}
          {selectedIndustry && mainTab === 'quotes' && (
            <div className="flex items-center space-x-1 px-2.5 py-1 text-xs bg-[#e8f0e9] text-[#4a7c59] rounded-md font-bold border border-[#4a7c59]/40 animate-fadeIn ml-2">
              <span>下钻成份股：{selectedIndustry}</span>
              <button
                onClick={() => {
                  setSelectedIndustry(null);
                  setMainTab('boards');
                }}
                className="hover:text-red-600 ml-1"
                title="返回板块列表"
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
              {formatDateStr(freshness.latest_open_trade_date || freshness.daily_market_date)}
            </strong>
          </div>

          <button
            onClick={handleStartSyncData}
            disabled={isTaskRunning}
            title={isTaskRunning ? "后台日线更新中..." : freshness.is_up_to_date === false ? "点击补齐全库最新日线；股票分钟线在查看 K 线时获取" : "检查并更新最新日线"}
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
                if (mainTab === 'boards') {
                  fetchBoards(boardType, keyword, sortBy, sortOrder);
                } else if (mainTab === 'quotes') {
                  fetchQuotes(0, false, board, keyword, sortBy, sortOrder, selectedIndustry);
                } else if (mainTab === 'news') {
                  fetchNews(newsQuery);
                } else {
                  fetchAnalytics();
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
              <span className="font-bold text-[#2e3230]">正在后台检查并更新日线...</span>
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

      {/* 4 大 Main Sub-Tabs 对应的主要视图呈现 */}
      {mainTab === 'overview' && (
        <div className="flex-1 overflow-y-auto space-y-4 custom-scrollbar pr-1">
          {/* 1. 四大核心指数卡片 */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {(analytics?.indices || [
              { code: '000001.SH', name: '上证指数', price: 3058.42, change: 18.25, pct_chg: 0.60, amount: 4280.5 },
              { code: '399001.SZ', name: '深证成指', price: 9482.16, change: 85.30, pct_chg: 0.91, amount: 5612.3 },
              { code: '399006.SZ', name: '创业板指', price: 1835.60, change: 22.14, pct_chg: 1.22, amount: 2340.1 },
              { code: '588000.SH', name: '科创 50', price: 782.90, change: 11.45, pct_chg: 1.48, amount: 1120.8 },
            ]).map((idx: any) => {
              const isUp = idx.pct_chg >= 0;
              return (
                <div key={idx.code} className="bg-white p-3.5 rounded-lg border border-[#c4c8bc]/40 shadow-xs flex flex-col justify-between space-y-2">
                  <div className="flex items-center justify-between text-xs text-[#686d68]">
                    <span className="font-bold text-[#2e3230] text-sm">{idx.name}</span>
                    <span className="font-mono text-[11px]">{idx.code}</span>
                  </div>
                  <div className="flex items-baseline justify-between">
                    <span className={`text-xl font-bold font-mono ${isUp ? 'text-[#d97706]' : 'text-[#2563eb]'}`}>
                      {idx.price.toFixed(2)}
                    </span>
                    <div className={`flex items-center space-x-1 font-mono font-bold text-xs ${isUp ? 'text-[#d97706]' : 'text-[#2563eb]'}`}>
                      {isUp ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
                      <span>{isUp ? `+${idx.change.toFixed(2)}` : idx.change.toFixed(2)}</span>
                      <span>({isUp ? `+${idx.pct_chg.toFixed(2)}%` : `${idx.pct_chg.toFixed(2)}%`})</span>
                    </div>
                  </div>
                  <div className="text-[11px] text-[#8c928c] font-mono flex justify-between border-t border-[#f0ece4] pt-1.5">
                    <span>成交额</span>
                    <span>{idx.amount} 亿</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* 2. 全市场交易情绪对比条 + 赚钱效应分档直方图 */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* 全大盘温度计 / 涨跌家数对比 */}
            <div className="bg-white p-4 rounded-lg border border-[#c4c8bc]/40 shadow-xs flex flex-col justify-between space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-1.5 font-bold text-sm text-[#2e3230]">
                  <Activity className="w-4 h-4 text-[#4a7c59]" />
                  <span>全市场情绪温度计</span>
                </div>
                <span className="text-xs text-[#686d68] font-mono">共 {analytics?.breadth?.total || totalCount || 5500} 只 A 股</span>
              </div>

              {/* 涨停 vs 跌停 突出 Badge */}
              <div className="grid grid-cols-2 gap-2 text-center text-xs">
                <div className="bg-red-50 border border-red-200 p-2 rounded-md">
                  <span className="text-[#686d68] block text-[11px]">涨停家数</span>
                  <span className="font-mono font-bold text-lg text-red-600">
                    {analytics?.breadth?.limit_up || 45} 家
                  </span>
                </div>
                <div className="bg-blue-50 border border-blue-200 p-2 rounded-md">
                  <span className="text-[#686d68] block text-[11px]">跌停家数</span>
                  <span className="font-mono font-bold text-lg text-blue-600">
                    {analytics?.breadth?.limit_down || 2} 家
                  </span>
                </div>
              </div>

              {/* 涨平跌三色对比进度条 */}
              <div className="space-y-1.5">
                <div className="flex justify-between text-xs font-bold font-mono">
                  <span className="text-[#d97706]">上涨: {analytics?.breadth?.up || 3250}</span>
                  <span className="text-[#686d68]">平盘: {analytics?.breadth?.flat || 310}</span>
                  <span className="text-[#2563eb]">下跌: {analytics?.breadth?.down || 1980}</span>
                </div>
                <div className="w-full h-3 bg-[#f0ece4] rounded-full overflow-hidden flex">
                  <div style={{ width: `${((analytics?.breadth?.up || 3250) / (analytics?.breadth?.total || 5500)) * 100}%` }} className="bg-[#d97706] h-full"></div>
                  <div style={{ width: `${((analytics?.breadth?.flat || 310) / (analytics?.breadth?.total || 5500)) * 100}%` }} className="bg-[#8c928c] h-full"></div>
                  <div style={{ width: `${((analytics?.breadth?.down || 1980) / (analytics?.breadth?.total || 5500)) * 100}%` }} className="bg-[#2563eb] h-full"></div>
                </div>
              </div>
            </div>

            {/* 赚钱效应 / 涨跌幅股票家数分布直方图 */}
            <div className="lg:col-span-2 bg-white p-4 rounded-lg border border-[#c4c8bc]/40 shadow-xs space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-1.5 font-bold text-sm text-[#2e3230]">
                  <BarChart3 className="w-4 h-4 text-[#4a7c59]" />
                  <span>全场股票涨跌分布 (按涨跌幅区间统计股票家数)</span>
                </div>
                <span className="text-xs text-[#8c928c]">单位：家</span>
              </div>

              <div className="grid grid-cols-9 gap-2 items-end h-36 pt-4 border-b border-[#f0ece4] pb-2">
                {[
                  { label: '>7%', key: 'p7', color: 'bg-red-600', textColors: 'text-red-600', count: analytics?.histogram?.p7 || 204 },
                  { label: '5~7%', key: 'p5_7', color: 'bg-red-500', textColors: 'text-red-500', count: analytics?.histogram?.p5_7 || 119 },
                  { label: '3~5%', key: 'p3_5', color: 'bg-red-400', textColors: 'text-red-400', count: analytics?.histogram?.p3_5 || 286 },
                  { label: '0~3%', key: 'p0_3', color: 'bg-red-300', textColors: 'text-red-400', count: analytics?.histogram?.p0_3 || 1832 },
                  { label: '平盘', key: 'flat', color: 'bg-slate-300', textColors: 'text-slate-500', count: analytics?.histogram?.flat || 173 },
                  { label: '-3~0%', key: 'n0_3', color: 'bg-emerald-300', textColors: 'text-emerald-600', count: analytics?.histogram?.n0_3 || 2609 },
                  { label: '-5~-3%', key: 'n3_5', color: 'bg-emerald-400', textColors: 'text-emerald-600', count: analytics?.histogram?.n3_5 || 216 },
                  { label: '-7~-5%', key: 'n5_7', color: 'bg-emerald-500', textColors: 'text-emerald-700', count: analytics?.histogram?.n5_7 || 57 },
                  { label: '<-7%', key: 'n7', color: 'bg-emerald-600', textColors: 'text-emerald-800', count: analytics?.histogram?.n7 || 43 },
                ].map((bar) => {
                  const histogramObj = analytics?.histogram || {};
                  const allCounts = Object.values(histogramObj).map(v => Number(v) || 0);
                  const maxVal = allCounts.length > 0 ? Math.max(...allCounts, 100) : 2800;
                  const heightPct = Math.min(Math.max((bar.count / maxVal) * 100, 6), 100);

                  return (
                    <div key={bar.key} className="flex flex-col items-center gap-1.5 group">
                      <span className={`text-[11px] font-mono font-extrabold ${bar.textColors}`}>
                        {bar.count} <span className="text-[10px] font-normal">家</span>
                      </span>
                      <div className="w-full bg-[#faf6f0] h-24 rounded-t relative flex items-end overflow-hidden border border-[#c4c8bc]/30">
                        <div
                          style={{ height: `${heightPct}%` }}
                          className={`w-full ${bar.color} rounded-t transition-all duration-500 group-hover:brightness-110`}
                        ></div>
                      </div>
                      <span className="text-[11px] font-bold text-[#4a4e4a] truncate w-full text-center">
                        {bar.label}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 板块行情子视图 (支持 申万行业板块 与 题材概念板块 切换) */}
      {mainTab === 'boards' && (
        <div className="flex-1 flex flex-col bg-white rounded-lg border border-[#c4c8bc]/40 shadow-xs overflow-hidden">
          {/* 板块类型二级 Filter Bar */}
          <div className="flex items-center justify-between px-4 py-2.5 bg-[#f0ece4]/60 border-b border-[#c4c8bc]/40">
            <div className="flex items-center space-x-2">
              <button
                onClick={() => {
                  setBoardType('industry');
                  fetchBoards('industry', keyword, sortBy, sortOrder);
                }}
                className={`px-3 py-1 text-xs font-bold rounded transition-all ${
                  boardType === 'industry'
                    ? 'bg-[#4a7c59] text-white shadow-xs'
                    : 'text-[#4a4e4a] bg-white hover:bg-[#e4e0d8]'
                }`}
              >
                申万行业板块
              </button>
              <button
                onClick={() => {
                  setBoardType('concept');
                  fetchBoards('concept', keyword, sortBy, sortOrder);
                }}
                className={`px-3 py-1 text-xs font-bold rounded transition-all ${
                  boardType === 'concept'
                    ? 'bg-[#4a7c59] text-white shadow-xs'
                    : 'text-[#4a4e4a] bg-white hover:bg-[#e4e0d8]'
                }`}
              >
                题材概念板块
              </button>
            </div>
            <div className="text-xs text-[#686d68]">
              共计 <strong className="font-mono text-[#2e3230]">{boardTotalCount}</strong> 个板块，点击板块名称查看成分股
            </div>
          </div>

          {/* 板块表格 */}
          <div className="flex-1 overflow-auto custom-scrollbar">
            <table className="w-full text-left border-collapse table-fixed text-xs">
              <thead className="sticky top-0 z-10 bg-[#f0ece4] border-b border-[#c4c8bc]/60 text-[#4a4e4a] font-bold">
                <tr>
                  <th className="w-16 py-2.5 px-4 text-center">序号</th>
                  <th className="w-48 py-2.5 px-4">板块名称</th>
                  <th className="w-36 py-2.5 px-4 text-right">成分股家数</th>
                  <th className="w-36 py-2.5 px-4 text-right">平均涨跌幅%</th>
                  <th className="w-44 py-2.5 px-4 text-right">板块总成交额</th>
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
                      onClick={() => {
                        setSelectedIndustry(b.name);
                        setMainTab('quotes');
                      }}
                      className="hover:bg-[#f5f2eb] transition-all cursor-pointer text-[#4a4e4a]"
                    >
                      <td className="py-2.5 px-4 text-center text-[#8c928c] font-mono">{idx + 1}</td>
                      <td className="py-2.5 px-4 font-bold text-[#2e3230] hover:text-[#4a7c59] flex items-center space-x-1">
                        <span>{b.name}</span>
                        <ChevronRight className="w-3.5 h-3.5 text-[#8c928c]" />
                      </td>
                      <td className="py-2.5 px-4 text-right font-mono">{b.stock_count}</td>
                      <td className={`py-2.5 px-4 text-right font-bold font-mono ${colorClass}`}>
                        {b.pct_chg > 0 ? `+${b.pct_chg.toFixed(2)}%` : `${b.pct_chg.toFixed(2)}%`}
                      </td>
                      <td className="py-2.5 px-4 text-right font-mono text-[#686d68]">
                        {formatAmount(b.amount)}
                      </td>
                      <td className="py-2.5 px-4">
                        {b.top_stock_name ? (
                          <div className="flex items-center space-x-2">
                            <span className="font-mono text-[#8c928c]">{b.top_stock_code}</span>
                            <span className="font-bold text-[#2e3230]">{b.top_stock_name}</span>
                            <span className={`font-mono font-bold text-[11px] ${b.top_stock_pct > 0 ? 'text-[#d97706]' : 'text-[#2563eb]'}`}>
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
          </div>
        </div>
      )}

      {/* 个股行情列表子视图 */}
      {mainTab === 'quotes' && (
        <div className="flex-1 flex flex-col bg-white rounded-lg border border-[#c4c8bc]/40 shadow-xs overflow-hidden">
          {/* 筛选与搜索 */}
          <div className="flex items-center justify-between px-4 py-2 bg-[#f0ece4]/60 border-b border-[#c4c8bc]/40">
            <div className="flex items-center space-x-1.5">
              {[
                { id: 'all', label: '全部A股' },
                { id: 'cyb', label: '创业板' },
                { id: 'kcb', label: '科创板' },
              ].map((item) => (
                <button
                  key={item.id}
                  onClick={() => {
                    setBoard(item.id);
                    setSelectedIndustry(null);
                  }}
                  className={`px-3 py-1 text-xs font-bold rounded transition-all ${
                    board === item.id && !selectedIndustry
                      ? 'bg-[#4a7c59] text-white shadow-xs'
                      : 'text-[#4a4e4a] bg-white hover:bg-[#e4e0d8]'
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>

            <div className="flex items-center space-x-2">
              <input
                type="text"
                placeholder="搜索名称或代码..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-48 bg-white border border-[#c4c8bc]/60 px-2.5 py-1 rounded text-xs focus:outline-none focus:border-[#4a7c59]"
              />
            </div>
          </div>

          {/* 个股全量表格 */}
          <div className="flex-1 overflow-auto custom-scrollbar">
            <table className="w-full text-left border-collapse table-fixed text-xs">
              <thead className="sticky top-0 z-10 bg-[#f0ece4] border-b border-[#c4c8bc]/60 text-[#4a4e4a] font-bold">
                <tr>
                  <th className="w-14 py-2.5 px-3 text-center">序号</th>
                  <th className="w-24 py-2.5 px-3">代码</th>
                  <th className="w-28 py-2.5 px-3">股票名称</th>
                  <th className="w-28 py-2.5 px-3">申万行业</th>
                  <th className="w-24 py-2.5 px-3 text-right">涨跌幅%</th>
                  <th className="w-20 py-2.5 px-3 text-right">现价</th>
                  <th className="w-20 py-2.5 px-3 text-right">涨速%</th>
                  <th className="w-28 py-2.5 px-3 text-right">成交额</th>
                  <th className="w-20 py-2.5 px-3 text-right">换手%</th>
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
                        {stock.speed ? (stock.speed > 0 ? `+${stock.speed.toFixed(2)}` : stock.speed.toFixed(2)) : '0.00'}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-[#686d68]">
                        {formatAmount(stock.amount)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono">
                        {stock.turnover ? `${stock.turnover.toFixed(2)}%` : '-'}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-[#686d68]">{stock.high ? stock.high.toFixed(2) : '-'}</td>
                      <td className="py-2.5 px-3 text-right font-mono text-[#686d68]">{stock.low ? stock.low.toFixed(2) : '-'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 财联社 7x24 小时财经电报子视图 */}
      {mainTab === 'news' && (
        <div className="flex-1 flex flex-col bg-white rounded-lg border border-[#c4c8bc]/40 shadow-xs overflow-hidden">
          {/* 电报控制顶栏 */}
          <div className="flex items-center justify-between px-4 py-2.5 bg-[#f0ece4]/60 border-b border-[#c4c8bc]/40">
            <div className="flex items-center space-x-2">
              <Flame className="w-4 h-4 text-red-600 animate-pulse" />
              <span className="font-bold text-sm text-[#2e3230]">财联社 7x24 小时财经电报</span>
            </div>
            <div className="flex items-center space-x-2">
              <input
                type="text"
                placeholder="搜索电报关键词..."
                value={newsQuery}
                onChange={(e) => setNewsQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') fetchNews(newsQuery);
                }}
                className="w-56 bg-white border border-[#c4c8bc]/60 px-3 py-1 rounded text-xs focus:outline-none focus:border-[#4a7c59]"
              />
              <button
                onClick={() => fetchNews(newsQuery)}
                className="px-3 py-1 text-xs font-bold text-white bg-[#4a7c59] hover:bg-[#3b6346] rounded shadow-xs transition-colors flex items-center space-x-1"
              >
                <RefreshCw className={`w-3 h-3 ${newsLoading ? 'animate-spin' : ''}`} />
                <span>刷新</span>
              </button>
            </div>
          </div>

          {/* 电报列表 Timeline */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
            {newsList.map((item) => (
              <div
                key={item.id}
                className="p-3.5 rounded-lg border border-[#c4c8bc]/30 bg-[#faf6f0]/40 hover:bg-[#faf6f0] transition-colors space-y-1.5"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="font-mono font-bold text-xs px-2 py-0.5 rounded bg-[#4a7c59]/10 text-[#4a7c59]">
                      {item.time}
                    </span>
                    <span className={`font-bold text-sm ${item.level === 'red' ? 'text-red-600 font-extrabold' : 'text-[#2e3230]'}`}>
                      {item.title}
                    </span>
                  </div>
                  {item.url && (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[#686d68] hover:text-[#4a7c59] text-xs flex items-center space-x-0.5"
                    >
                      <span>原文</span>
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </div>

                <p className="text-xs text-[#4a4e4a] leading-relaxed pl-1">
                  {item.content}
                </p>

                {item.subjects && item.subjects.length > 0 && (
                  <div className="flex items-center space-x-1.5 pt-1">
                    {item.subjects.map((sub, idx) => (
                      <span key={idx} className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[#f0ece4] text-[#705c30] border border-[#c4c8bc]/40">
                        #{sub}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 底部标准说明栏 */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 bg-white rounded-lg border border-[#c4c8bc]/40 shadow-xs text-xs text-[#686d68]">
        <div className="flex items-center space-x-2 font-medium">
          <span className="inline-block w-2 h-2 rounded-full bg-[#4a7c59]"></span>
          <span>全市场全量数据驱动</span>
        </div>
        <div className="text-[11px] text-[#8c928c] font-medium">
          💡 点击表头进行全局排序，方向键选择，按 Enter 查看 K 线
        </div>
      </div>

      {/* KLineModal 弹窗 */}
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
