"use client";

import { useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  ChevronRight,
  CirclePause,
  Cable,
  ClipboardList,
  Database,
  Download,
  Ellipsis,
  Eye,
  FileText,
  Flag,
  Filter,
  History,
  Landmark,
  ListChecks,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Save,
  Settings,
  Shield,
  ShieldCheck,
  ShoppingCart,
  SlidersHorizontal,
  Trash2,
  UserRound,
  Wallet,
  X,
  Zap,
} from "lucide-react";
import TradePlansPage, { ActionPlanDialog, type TradePlanPrefill } from "./TradePlansPage";
import TradesPage, { ExitRuleDialog, RiskReferenceDialog } from "./TradesPage";
import PrototypeTradingPage, { type PrototypePageKey } from "./PrototypeTradingPage";

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;
type TradingView =
  | "overview" | "trades" | "plan" | "execution" | "orders" | "positions" | "settings"
  | "trade" | "risk" | "open" | "add" | "reduce" | "close" | "action";
type RootView =
  | "market"
  | "review"
  | "screening"
  | "watchlist"
  | "technical-classification"
  | "trading-system"
  | "trading-overview"
  | "trade-plans";
type ShellProps = {
  initialView: TradingView;
  onNavigate: (view: RootView) => void;
  accountId: number;
  embedded?: boolean;
  tradePlanPrefill?: TradePlanPrefill | null;
  onPlanPrefillConsumed?: () => void;
  settingsOpen?: boolean;
  onSettingsOpenChange?: (open: boolean) => void;
};
const secondaryNavigation: Array<[TradingView, string, typeof BarChart3]> = [
  ["overview", "交易总览", BarChart3],
  ["trades", "交易", ClipboardList],
  ["execution", "执行", Zap],
  ["orders", "订单", ShoppingCart],
  ["positions", "持仓", Wallet],
  ["settings", "配置", Settings],
];

const prototypePageForView: Partial<Record<TradingView, PrototypePageKey>> = {
  overview: "overview",
  trades: "trades",
  trade: "trade",
  risk: "risk",
  open: "open",
  add: "add",
  reduce: "reduce",
  close: "close",
  action: "action",
  execution: "execution",
  orders: "orders",
  positions: "positions",
};

async function request(path: string, options?: RequestInit) {
  if (!API_BASE) throw new Error("NEXT_PUBLIC_MARKET_REVIEW_API_URL 未配置");
  let lastError: unknown;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        cache: "no-store",
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...(options?.headers || {}),
        },
      });
      if (!response.ok) {
        if (response.status === 401 || response.status === 403) {
          throw new Error("当前账号没有访问该交易数据的权限");
        }
        if (response.status === 503) {
          throw new Error("交易服务暂时不可用，请稍后重试");
        }
        if (response.status >= 500) {
          throw new Error("交易服务处理失败，请稍后重试");
        }
        throw new Error(await response.text());
      }
      return response.json();
    } catch (error) {
      lastError = error;
      if (attempt < 2 && error instanceof TypeError) await new Promise((resolve) => setTimeout(resolve, 400 * (attempt + 1)));
      else throw error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("交易数据接口暂时无法连接");
}
function accountPath(path: string, accountId: number) {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}account_id=${encodeURIComponent(String(accountId))}`;
}
function money(value: any) {
  return typeof value === "number"
    ? `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`
    : "—";
}
function pct(value: any) {
  return typeof value === "number" ? `${(value * 100).toFixed(2)}%` : "—";
}
function statusLabel(status: string) {
  return (
    (
      {
        ACTIVE: "运行中",
        PAUSED: "已暂停",
        DRAFT: "草稿",
        COMPLETED: "已完成",
        CANCELLED: "已取消",
        EXPIRED: "已过期",
        PENDING_SUBMIT: "等待发送",
        SUBMITTED: "已发送",
        ACCEPTED: "已接受",
        PARTIALLY_FILLED: "部分成交",
        FILLED: "全部成交",
        CANCELLED_ORDER: "已撤单",
        REJECTED: "已拒绝",
        UNKNOWN: "状态未知",
      } as Record<string, string>
    )[status] || status
  );
}
function brokerConnectionHealthy(connection: any) {
  return connection?.status === "CONNECTED" || connection?.ok === true;
}

function maskAccountIdentifier(value: unknown) {
  const text = String(value ?? "");
  if (!text) return "—";
  return `${text.slice(0, Math.min(4, text.length))}${"*".repeat(8)}`;
}

function maskToken(value: unknown) {
  const text = String(value ?? "");
  return text ? `${text.slice(0, 6)}${"*".repeat(8)}` : "—";
}
function actionLabel(action: string | undefined) {
  return ({ OPEN: "建仓", ADD: "加仓", REDUCE: "减仓", CLOSE: "清仓" } as Record<string, string>)[action || ""] || "动作";
}
function executionTypeLabel(type: string) {
  return ({
    LIMIT: "限价委托",
    PERSISTENT_LIMIT: "持续限价",
    PRICE_TRIGGER: "价格触发",
    PRICE_RANGE: "价格区间触发",
  } as Record<string, string>)[type] || type;
}
function executionRuleLabel(item: any) {
  const params = item.execution_params_json || {};
  if (item.execution_type === "LIMIT" || item.execution_type === "PERSISTENT_LIMIT")
    return `不高于 ${money(Number(params.limit_price))}`;
  if (item.execution_type === "PRICE_TRIGGER")
    return `价格达到 ${money(Number(params.trigger_price))} 后启动`;
  if (item.execution_type === "PRICE_RANGE")
    return `${money(Number(params.low_price))} 至 ${money(Number(params.high_price))} 内启动`;
  return "—";
}
function minuteSyncStatusLabel(status: string) {
  return ({ COMPLETE: "已完成", PARTIAL: "部分完成", FAILED: "更新失败", PENDING: "待处理", INACTIVE: "当天无有效行情", EMPTY: "当天无有效行情" } as Record<string, string>)[status] || "状态未知";
}

export default function TradingSystemShell({
  initialView,
  onNavigate,
  accountId,
  embedded = false,
  tradePlanPrefill,
  onPlanPrefillConsumed,
  settingsOpen: controlledSettingsOpen,
  onSettingsOpenChange,
}: ShellProps) {
  const [view, setView] = useState<TradingView>(initialView);
  const [tradeToOpen, setTradeToOpen] = useState<number | null>(null);
  const [selectedTradeId, setSelectedTradeId] = useState<number | null>(null);
  const [actionDialog, setActionDialog] = useState<"ADD" | "REDUCE" | "CLOSE" | null>(null);
  const [actionInitialValues, setActionInitialValues] = useState<Record<string, string> | undefined>(undefined);
  const [prototypePlanForm, setPrototypePlanForm] = useState<any>(undefined);
  const [prototypePlanDialogOpen, setPrototypePlanDialogOpen] = useState(false);
  const [riskDialog, setRiskDialog] = useState<{ tradeId: number; legs: any[]; current?: number; reason?: string } | null>(null);
  const [exitRuleDialog, setExitRuleDialog] = useState<{ tradeId: number; rule?: any } | null>(null);
  const [executionComposerOpen, setExecutionComposerOpen] = useState(false);
  const [orderDetail, setOrderDetail] = useState<any>(null);
  const [control, setControl] = useState<any>({ execution_paused: false });
  const [account, setAccount] = useState<any>(null);
  const [broker, setBroker] = useState<any>(null);
  const [reconciliationIssueCount, setReconciliationIssueCount] = useState(0);
  const [dataRevision, setDataRevision] = useState(0);
  const [shellError, setShellError] = useState<string | null>(null);
  const [internalSettingsOpen, setInternalSettingsOpen] = useState(false);
  const settingsOpen = controlledSettingsOpen ?? internalSettingsOpen;
  const setSettingsOpen = (open: boolean) => {
    onSettingsOpenChange?.(open);
    if (controlledSettingsOpen === undefined) setInternalSettingsOpen(open);
  };
  const openTrade = (tradeId: number) => {
    setTradeToOpen(tradeId);
    setSelectedTradeId(tradeId);
    setView("trades");
  };
  const navigatePrototype = (nextView: PrototypePageKey, tradeId?: number) => {
    if (tradeId !== undefined) setSelectedTradeId(tradeId);
    if (nextView === "risk" && tradeId !== undefined) {
      setRiskDialog(null);
    }
    setView(nextView as TradingView);
  };
  const submitPrototypePlan = (values: Record<string, string>) => {
    const tradeType = values.trade_type || "TREND";
    const fixedTarget = tradeType === "FIXED_TARGET";
    setPrototypePlanForm({
      trade_type: tradeType,
      thesis: values.thesis || values.textarea_0 || "",
      reference_entry_price: values.reference_entry_price || values.input_2 || "",
      max_acceptable_entry_price: values.max_acceptable_entry_price || values.input_3 || "",
      risk_reference_price: values.risk_reference_price || values.input_4 || "",
      plan_risk_pct: (values.plan_risk_pct || values.input_5 || "").replace("%", ""),
      target_type: fixedTarget ? "FIXED_TARGET" : "TREND_FOLLOWING",
      target_price: fixedTarget ? values.target_price || values.input_6 || "" : "",
      expected_price: fixedTarget ? "" : values.target_price || values.input_6 || "",
    });
    setPrototypePlanDialogOpen(true);
  };
  const submitPrototypeAction = (page: "add" | "reduce" | "close", values: Record<string, string>) => {
    if (selectedTradeId === null) {
      setShellError("当前页面缺少 Trade 上下文，无法提交交易动作");
      return;
    }
    if (page === "add") {
      setActionInitialValues({
        reasonCode: values.reason_code || "CUSTOM",
        referencePrice: values.reference_price || values.input_2 || "",
        maxPrice: values.max_acceptable_price || values.input_3 || "",
        riskPrice: values.risk_reference_price || values.input_4 || "",
        quantity: values.quantity || values.input_5 || "",
        reasonText: values.reason_text || values.input_1 || "",
        failureHandling: ({ exit_add: "EXIT_ADDED_QTY_ONLY", reduce_to: "REDUCE_TO_TARGET_QTY", exit_all: "CLOSE_ALL", manual: "MANUAL_REVIEW" } as Record<string, string>)[values.fail_action] || "EXIT_ADDED_QTY_ONLY",
        riskMode: values.risk_mode === "unified" ? "UNIFIED" : "INDEPENDENT",
        unifiedRiskReference: values.unified_risk_reference_price || values.input_11 || "",
      });
    } else if (page === "reduce") {
      setActionInitialValues({
        reasonCode: values.reason_code || "CUSTOM",
        reduceMethod: values.reduce_method || "FIXED_QTY",
        quantity: values.quantity || values.input_0 || "",
        referencePrice: values.reference_price || values.input_1 || "",
        minimumPrice: values.minimum_acceptable_price || values.input_2 || "",
        reasonText: values.reason_text || values.textarea_0 || "",
        residualMode: values.residual_mode || "KEEP",
      });
    } else {
      setActionInitialValues({
        reasonCode: values.reason_code || "CUSTOM",
        triggerCondition: values.trigger_condition || "",
        reasonText: values.reason_text || values.textarea_0 || "",
      });
    }
    setActionDialog(page.toUpperCase() as "ADD" | "REDUCE" | "CLOSE");
  };
  const submitPrototypeRisk = (values: Record<string, string>) => {
    if (selectedTradeId === null) {
      setShellError("当前页面缺少 Trade 上下文，无法调整风险参考");
      return;
    }
    const price = values.risk_reference_price || values.newRiskPriceInput || "";
    request(accountPath(`/api/trades/${selectedTradeId}`, accountId))
      .then((result) => setRiskDialog({ tradeId: selectedTradeId, legs: result.item?.legs || [], current: Number(price) || result.item?.position_risk_reference_price, reason: values.reason_text || values.textarea_0 || "" }))
      .catch((error) => setShellError(error instanceof Error ? error.message : "交易风险信息读取失败"));
  };

  async function loadShell() {
    setShellError(null);
    setAccount(null);
    setBroker(null);
    setReconciliationIssueCount(0);
    setControl({ execution_paused: false });
    try {
      const [overview, controlResult, brokerResult] = await Promise.all([
        request(accountPath("/api/trading/overview", accountId)),
        request(accountPath("/api/trading/control", accountId)),
        request(accountPath("/api/trading/broker", accountId)),
      ]);
      setAccount(overview.account);
      setReconciliationIssueCount(Array.isArray(overview.reconciliation_issues) ? overview.reconciliation_issues.length : 0);
      setControl(controlResult.control);
      setBroker(brokerResult);
      setDataRevision((current) => current + 1);
    } catch (error) {
      setShellError(
        error instanceof Error ? error.message : "交易系统状态读取失败",
      );
    }
  }
  useEffect(() => {
    setSelectedTradeId(null);
    setTradeToOpen(null);
    setActionDialog(null);
    setActionInitialValues(undefined);
    setRiskDialog(null);
    setExitRuleDialog(null);
    setOrderDetail(null);
    setPrototypePlanDialogOpen(false);
    setPrototypePlanForm(undefined);
    setView("overview");
    loadShell();
  }, [accountId]);
  async function togglePause() {
    const paused = !control.execution_paused;
    try {
      const result = await request(accountPath("/api/trading/control", accountId), {
        method: "PATCH",
        body: JSON.stringify({
          execution_paused: paused,
          reason: paused ? "用户暂停全部执行" : null,
        }),
      });
      setControl(result.control);
    } catch (error) {
      setShellError(
        error instanceof Error ? error.message : "执行状态更新失败",
      );
    }
  }
  async function updateExecutionStatus(executionPlanId: number, status: string) {
    try {
      await request(accountPath(`/api/trading/execution-plans/${executionPlanId}/status`, accountId), {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      await loadShell();
    } catch (error) {
      setShellError(error instanceof Error ? error.message : "执行计划状态更新失败");
    }
  }
  async function cancelOrder(orderId: number) {
    try {
      await request(accountPath(`/api/trading/orders/${orderId}/cancel`, accountId), { method: "POST" });
      await loadShell();
    } catch (error) {
      setShellError(error instanceof Error ? error.message : "订单撤销失败");
    }
  }
  async function cancelOpenOrders() {
    if (!window.confirm("确认暂停当前账号执行，并撤销全部未成交委托？")) return;
    try {
      await request(accountPath("/api/trading/control/cancel-open-orders", accountId), {
        method: "POST",
        body: JSON.stringify({ confirmed: true, reason: "用户暂停并撤销未成交委托" }),
      });
      await loadShell();
    } catch (error) {
      setShellError(error instanceof Error ? error.message : "暂停并撤单失败");
    }
  }
  async function openExitRuleDialog(tradeId: number) {
    setSelectedTradeId(tradeId);
    setExitRuleDialog({ tradeId });
  }
  async function changeExitRule(tradeId: number, ruleId: number, operation: "edit" | "delete") {
    try {
      const result = await request(accountPath(`/api/trades/${tradeId}/exit-rules`, accountId));
      const rule = (result.items || []).find((item: any) => item.id === ruleId);
      if (!rule) throw new Error("当前账号中未找到该退出规则");
      if (operation === "edit") {
        setExitRuleDialog({ tradeId, rule });
        return;
      }
      if (!window.confirm("确认删除这条退出规则？")) return;
      await request(accountPath(`/api/trades/${tradeId}/exit-rules/${ruleId}`, accountId), { method: "DELETE" });
      await loadShell();
      setView("trade");
    } catch (error) {
      setShellError(error instanceof Error ? error.message : "退出规则操作失败");
    }
  }
  async function inspectOrder(orderId: number) {
    try {
      const result = await request(accountPath("/api/trading/overview", accountId));
      const order = (result.orders || []).find((item: any) => item.id === orderId);
      if (!order) throw new Error("当前账号中未找到该订单");
      const fills = (result.fills || []).filter((item: any) => item.order_id === orderId);
      setOrderDetail({ order, fills });
    } catch (error) {
      setShellError(error instanceof Error ? error.message : "订单详情读取失败");
    }
  }
  async function inspectExecutionOrders(executionPlanId: number) {
    try {
      const result = await request(accountPath("/api/trading/overview", accountId));
      const orders = (result.orders || []).filter((item: any) => item.execution_plan_id === executionPlanId);
      if (orders.length === 0) throw new Error("当前账号中该执行计划暂无关联订单");
      if (orders.length > 1) throw new Error("该执行计划关联多个订单，请在订单页面按执行计划逐笔查看");
      const order = orders[0];
      const fills = (result.fills || []).filter((item: any) => item.order_id === order.id);
      setOrderDetail({ order, fills });
    } catch (error) {
      setShellError(error instanceof Error ? error.message : "执行计划订单读取失败");
    }
  }
  // The API exposes either normalized CONNECTED or Broker Node health ({ ok: true }).
  const connected = brokerConnectionHealthy(broker?.connection);
  const accountType =
    account?.account_type === "LIVE"
      ? "实盘账户"
      : account?.account_type === "SIMULATION"
        ? "模拟账户"
        : "规划账户";
  const brokerStatusText = !connected
    ? "未连接"
    : broker?.connection?.node_status?.agent_online === false
      ? "已连接·执行器离线"
      : broker?.connection?.node_status?.reconciliation_required
      ? "已连接·待对账"
      : broker?.connection?.node_status?.paused
        ? "已连接·已暂停"
      : broker?.connection?.node_status?.execution_enabled === false
        ? "已连接·暂不可执行"
        : "连接正常";
  return (
    <div className="trading-system-shell min-h-screen bg-[#f8f9fa] text-[#191c1d]">
      {!embedded && (
      <header className="fixed top-0 z-50 w-full border-b border-[#dee2e6] bg-white/95 shadow-[0_1px_8px_rgba(0,0,0,0.04)] backdrop-blur-md">
        <div className="flex h-16 items-center justify-between gap-4 px-6 xl:px-8">
          <div className="flex min-w-0 items-center gap-5">
            <button
              onClick={() => onNavigate("market")}
              className="flex shrink-0 items-center gap-2 text-left"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#0f5238] text-white">
                <BarChart3 className="h-5 w-5" />
              </span>
              <span className="text-xl font-bold tracking-tight text-[#0f5238]">
                LLL 交易研究
              </span>
            </button>
            <nav
              aria-label="一级功能"
              className="hidden items-center gap-1 md:flex"
            >
              {(
                [
                  ["market", "A股行情"],
                  ["review", "复盘"],
                  ["screening", "自动选股"],
                  ["technical-classification", "全市场技术分类"],
                  ["watchlist", "⭐ 自选股"],
                ] as [RootView, string][]
              ).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => onNavigate(key)}
                  className="rounded-md px-3 py-1.5 text-sm font-bold text-[#4a4e4a] hover:bg-[#edeeef]"
                >
                  {label}
                </button>
              ))}
              <span className="rounded-md bg-[#0f5238] px-3 py-1.5 text-sm font-bold text-white">
                交易系统
              </span>
            </nav>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <div className="hidden items-center gap-2 rounded-full border border-[#bfc9c1] bg-[#edeeef] px-3 py-1.5 text-xs font-bold text-[#404943] lg:flex">
              <span
                className={`h-2 w-2 rounded-full ${connected ? "bg-[#2d6a4f]" : "bg-[#e67e22]"}`}
              />
              {accountType} · {connected
                ? (broker?.connection?.node_status?.agent_online === false ? "已连接·执行器离线" : broker?.connection?.node_status?.reconciliation_required ? "已连接·待对账" : broker?.connection?.node_status?.paused ? "已连接·已暂停" : broker?.connection?.node_status?.execution_enabled === false ? "已连接·暂不可执行" : "连接正常")
                : "券商未连接"}
              {account?.account_type === "LIVE" && (
                <span className="rounded bg-[#9b2226] px-2 py-0.5 text-[10px] text-white">
                  LIVE
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={() => setSettingsOpen(true)}
              title="交易设置"
              aria-label="交易设置"
              className={`inline-flex h-8 w-8 items-center justify-center rounded-lg border transition-colors ${settingsOpen ? "border-[#0f5238] bg-[#0f5238] text-white" : "border-[#d2d9d5] bg-white text-[#354860] hover:border-[#0f5238] hover:text-[#0f5238]"}`}
            >
              <Settings className="h-4 w-4" />
            </button>
            <div className="hidden items-center gap-2 sm:flex">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#0f5238] text-white">
                <UserRound className="h-4 w-4" />
              </span>
      </div>
    </div>
    </div>
      </header>
      )}
      <main className={`min-h-screen bg-[#f8f7f2] ${embedded ? "pt-0" : "pt-16"}`}>
        {embedded && (
          <div className="flex min-h-12 items-center justify-between gap-3 border-b border-[#d9ddd7] bg-white px-4 py-2 text-xs shadow-[0_1px_5px_rgba(25,28,29,0.04)] sm:px-6">
            <div className="flex min-w-0 items-center gap-2">
              <span className={`h-2 w-2 shrink-0 rounded-full ${account?.status === "ACTIVE" ? "bg-[#2d6a4f]" : "bg-[#ae2012]"}`} />
              <span className="truncate font-bold text-[#27332c]">{account?.name || "正在读取账号…"}</span>
              <span className="hidden text-[#68736b] sm:inline">{accountType}</span>
              <span className="hidden text-[#68736b] md:inline">· 券商{brokerStatusText}</span>
              {reconciliationIssueCount > 0 && <span className="hidden rounded bg-[#fff0dc] px-2 py-1 font-bold text-[#8a4b08] sm:inline">· 待处理对账 {reconciliationIssueCount} 项</span>}
            </div>
            <button
              onClick={togglePause}
              title={control.execution_paused ? "解除暂停：允许当前账号执行计划继续运行" : "暂停当前账号：不发送新的委托"}
              aria-label={control.execution_paused ? "解除当前账号暂停" : "暂停当前账号执行"}
              className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs font-bold text-white transition-colors ${control.execution_paused ? "bg-[#e67e22] hover:bg-[#c66a12]" : "bg-[#ae2012] hover:bg-[#92190f]"}`}
            >
              {control.execution_paused ? <Play className="h-4 w-4" /> : <CirclePause className="h-4 w-4" />}
              <span className="hidden sm:inline">{control.execution_paused ? "已暂停 · 恢复执行" : "暂停执行"}</span>
            </button>
          </div>
        )}
        <div className="flex min-h-[calc(100vh-3rem)]">
        <aside className="sticky top-16 flex h-[calc(100vh-4rem)] w-[60px] shrink-0 flex-col border-r border-stone-200/80 bg-[#f6f4ee] px-0 py-4">
          <nav aria-label="交易系统功能" className="flex flex-1 flex-col items-center gap-3">
            {secondaryNavigation.map(([key, label, Icon]) => (
              <button
                key={key}
                onClick={() => setView(key)}
                title={label}
                aria-label={label}
                className={`group relative flex h-[48px] w-[48px] flex-col items-center justify-center rounded-lg text-[10px] transition-colors ${key === "settings" ? "mt-auto" : ""} ${view === key ? "bg-[#2d5a43] font-bold text-white shadow-[0_2px_6px_rgba(45,90,67,0.28)]" : "text-stone-500 hover:bg-stone-200/60 hover:text-stone-800"}`}
              >
                <Icon className="h-5 w-5" strokeWidth={1.8} />
                <span className="mt-1">{label === "交易总览" ? "总览" : label}</span>
              </button>
            ))}
          </nav>
        </aside>
        <div className="min-w-0 flex-1">
          {shellError && (
            <div className="mx-6 mt-4 rounded-lg border border-[#ffdad6] bg-[#ffdad6] px-4 py-3 text-sm text-[#93000a]">
              {shellError}
            </div>
          )}
          {prototypePageForView[view] && (
            <PrototypeTradingPage
              page={prototypePageForView[view] as PrototypePageKey}
              onNavigate={navigatePrototype}
              accountId={accountId}
              refreshToken={dataRevision}
              tradeId={selectedTradeId}
              onExecutionStatusChange={updateExecutionStatus}
              onOrderCancel={cancelOrder}
              onExitRuleCreate={openExitRuleDialog}
              onExitRuleChange={changeExitRule}
              onPauseAll={togglePause}
              onCancelOpenOrders={cancelOpenOrders}
              onCreateExecutionPlan={() => setExecutionComposerOpen(true)}
              onOrderInspect={inspectOrder}
              onExecutionOrderInspect={inspectExecutionOrders}
              onCreateTradePlan={submitPrototypePlan}
              onActionSubmit={submitPrototypeAction}
              onRiskReferenceSubmit={submitPrototypeRisk}
            />
          )}
          {view === "plan" && <TradePlansPage accountId={accountId} onOpenSettings={() => setView("settings")} prefill={tradePlanPrefill} onPrefillConsumed={onPlanPrefillConsumed} />}
          {view === "open" && prototypePlanDialogOpen && (
            <div className="fixed inset-0 z-[60] overflow-y-auto bg-[#f8f9fa]">
            <TradePlansPage accountId={accountId} initialMode="new" initialForm={prototypePlanForm} onOpenSettings={() => setView("settings")} onPrefillConsumed={() => { setPrototypePlanDialogOpen(false); setPrototypePlanForm(undefined); setView("overview"); }} />
            </div>
          )}
          {view === "settings" && <SettingsPage accountId={accountId} onRefresh={loadShell} onClose={() => setView("overview")} />}
          {actionDialog && selectedTradeId !== null && (
            <ActionPlanDialog
              accountId={accountId}
              fullPage
              action={{ tradeId: selectedTradeId, symbol: "", securityName: "", type: actionDialog }}
              initialValues={actionInitialValues}
              onClose={() => setActionDialog(null)}
              onSaved={async () => { setActionDialog(null); await loadShell(); setView("trade"); }}
              onError={setShellError}
            />
          )}
          {riskDialog && (
            <RiskReferenceDialog
              accountId={accountId}
              tradeId={riskDialog.tradeId}
              legs={riskDialog.legs}
              current={riskDialog.current}
              initialReason={riskDialog.reason}
              onClose={() => setRiskDialog(null)}
              onSaved={async () => { setRiskDialog(null); await loadShell(); }}
              onError={setShellError}
            />
          )}
          {exitRuleDialog !== null && (
            <ExitRuleDialog
              accountId={accountId}
              tradeId={exitRuleDialog.tradeId}
              rule={exitRuleDialog.rule}
              onClose={() => setExitRuleDialog(null)}
              onSaved={async () => { setExitRuleDialog(null); await loadShell(); }}
              onError={setShellError}
            />
          )}
          {executionComposerOpen && (
            <ExecutionComposerDialog
              accountId={accountId}
              onClose={() => setExecutionComposerOpen(false)}
              onSaved={async () => { setExecutionComposerOpen(false); await loadShell(); }}
              onError={setShellError}
            />
          )}
          {orderDetail && <PrototypeOrderDetailDialog data={orderDetail} onClose={() => setOrderDetail(null)} />}
        </div>
        </div>
      </main>
      {!embedded && <footer className="flex flex-col justify-between gap-3 border-t border-[#dee2e6] bg-[#f3f4f5] px-6 py-6 text-xs text-[#52616b] md:flex-row md:items-center">
        <span>© 2024 LLL 交易研究 · 交易系统</span>
        <span className="flex items-center gap-5">
          <span className="flex items-center gap-1">
            <Shield className="h-4 w-4 text-[#2d6a4f]" />
            数据安全
          </span>
          <span className="flex items-center gap-1">
            <Zap className="h-4 w-4" />
            行情状态以数据源为准
          </span>
        </span>
      </footer>}
    </div>
  );
}

function PageFrame({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`w-full px-5 py-5 xl:px-6 ${className}`}>
      <div className="mx-auto max-w-[1600px]">{children}</div>
    </div>
  );
}

function ExecutionComposerDialog({ accountId, onClose, onSaved, onError }: { accountId: number; onClose: () => void; onSaved: () => Promise<void>; onError: (message: string) => void }) {
  const [plans, setPlans] = useState<any[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [executionType, setExecutionType] = useState("LIMIT");
  const [price, setPrice] = useState("");
  const [limitPrice, setLimitPrice] = useState("");
  const [rangeHigh, setRangeHigh] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    request(accountPath("/api/trades", accountId)).then((result) => {
      const ready = (result.items || []).flatMap((trade: any) => (trade.plans || [])
        .filter((plan: any) => ["READY", "ARMED"].includes(plan.status))
        .map((plan: any) => ({ ...plan, symbol: trade.symbol, security_name: trade.symbol_name, trade_status: trade.status })));
      setPlans(ready);
      if (ready.length) {
        setSelectedId(String(ready[0].id));
        setPrice(String(ready[0].input_json?.reference_entry_price || ""));
        setLimitPrice(String(ready[0].input_json?.max_acceptable_entry_price || ready[0].input_json?.reference_entry_price || ""));
        setRangeHigh(String(ready[0].input_json?.max_acceptable_entry_price || ready[0].input_json?.reference_entry_price || ""));
      }
    }).catch((error) => onError(error instanceof Error ? error.message : "待执行交易计划读取失败"));
  }, [accountId, onError]);
  const selected = plans.find((plan) => String(plan.id) === selectedId);
  async function save() {
    if (!selected) { onError("请选择一个已确认的交易计划"); return; }
    if (!price || Number(price) <= 0) { onError("请输入有效执行价格"); return; }
    if (["PRICE_TRIGGER", "PRICE_RANGE"].includes(executionType) && (!limitPrice || Number(limitPrice) <= 0)) { onError("条件触发计划必须填写触发后的限价保护"); return; }
    if (executionType === "PRICE_RANGE" && (!rangeHigh || Number(rangeHigh) <= Number(price))) { onError("价格区间的上限必须大于下限"); return; }
    setBusy(true);
    try {
      const created = await request(accountPath("/api/trading/execution-plans", accountId), { method: "POST", body: JSON.stringify({
        trade_plan_id: selected.id,
        symbol: selected.symbol,
        side: ["REDUCE", "CLOSE"].includes(selected.input_json?.action_type) ? "SELL" : "BUY",
        target_qty: Number(selected.calculation_snapshot_json?.planned_qty),
        execution_type: executionType,
        valid_until: validUntil ? `${validUntil}T23:59:59+08:00` : null,
        execution_params: executionType === "PRICE_TRIGGER"
          ? { trigger_price: Number(price), limit_price: Number(limitPrice) }
          : executionType === "PRICE_RANGE"
            ? { low_price: Number(price), high_price: Number(rangeHigh), limit_price: Number(limitPrice) }
            : { limit_price: Number(price) },
      })});
      await request(accountPath(`/api/trading/execution-plans/${created.item.id}/status`, accountId), { method: "PATCH", body: JSON.stringify({ status: "ACTIVE" }) });
      await onSaved();
    } catch (error) { onError(error instanceof Error ? error.message : "执行计划创建失败"); }
    finally { setBusy(false); }
  }
  return <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/30 p-4"><div className="w-full max-w-lg rounded-xl bg-white p-5 shadow-xl"><div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-bold">创建执行计划</h2><button onClick={onClose} className="text-xl text-[#52616b]">×</button></div>{plans.length === 0 ? <p className="rounded-lg bg-[#fff8ed] p-3 text-sm text-[#8a4b08]">当前账号没有可创建执行计划的已确认交易计划。</p> : <div className="grid gap-3"><label className="text-sm font-bold">交易计划<select value={selectedId} onChange={(event) => { const next = plans.find((plan) => String(plan.id) === event.target.value); setSelectedId(event.target.value); setPrice(String(next?.input_json?.reference_entry_price || "")); setLimitPrice(String(next?.input_json?.max_acceptable_entry_price || next?.input_json?.reference_entry_price || "")); setRangeHigh(String(next?.input_json?.max_acceptable_entry_price || next?.input_json?.reference_entry_price || "")); }} className="input mt-1">{plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.symbol} · {plan.security_name || "—"} · {plan.calculation_snapshot_json?.planned_qty || 0} 股</option>)}</select></label><label className="text-sm font-bold">执行方式<select value={executionType} onChange={(event) => setExecutionType(event.target.value)} className="input mt-1"><option value="LIMIT">限价委托</option><option value="PRICE_TRIGGER">价格触发</option><option value="PRICE_RANGE">价格区间触发</option></select></label><label className="text-sm font-bold">{executionType === "PRICE_TRIGGER" ? "触发价格" : executionType === "PRICE_RANGE" ? "区间下限" : "限价"}<input value={price} onChange={(event) => setPrice(event.target.value)} type="number" min="0.01" step="0.01" className="input mt-1" /></label>{executionType === "PRICE_RANGE" && <label className="text-sm font-bold">区间上限<input value={rangeHigh} onChange={(event) => setRangeHigh(event.target.value)} type="number" min="0.01" step="0.01" className="input mt-1" /></label>}{["PRICE_TRIGGER", "PRICE_RANGE"].includes(executionType) && <label className="text-sm font-bold">触发后限价保护<input value={limitPrice} onChange={(event) => setLimitPrice(event.target.value)} type="number" min="0.01" step="0.01" className="input mt-1" /></label>}<label className="text-sm font-bold">有效期<input value={validUntil} onChange={(event) => setValidUntil(event.target.value)} type="date" className="input mt-1" /></label></div>}<div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-md border border-[#bfc9c1] px-3 py-2 text-sm font-bold">取消</button><button onClick={() => void save()} disabled={busy || plans.length === 0} className="rounded-md bg-[#0f5238] px-3 py-2 text-sm font-bold text-white disabled:opacity-50">保存并启用</button></div></div></div>;
}

function PrototypeOrderDetailDialog({ data, onClose }: { data: { order: any; fills: any[] }; onClose: () => void }) {
  const { order, fills } = data;
  return <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/30 p-4"><div className="w-full max-w-2xl rounded-xl bg-white p-5 shadow-xl"><div className="mb-4 flex items-start justify-between"><div><h2 className="text-lg font-bold">订单详情</h2><p className="mt-1 text-xs text-[#52616b]">{order.symbol || "—"} · 订单 #{order.id}</p></div><button onClick={onClose} className="text-xl text-[#52616b]">×</button></div><div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4"><div className="rounded-lg bg-[#f5f3ed] p-3"><span className="block text-xs text-[#52616b]">方向</span><b>{order.side === "BUY" ? "买入" : order.side === "SELL" ? "卖出" : "—"}</b></div><div className="rounded-lg bg-[#f5f3ed] p-3"><span className="block text-xs text-[#52616b]">状态</span><b>{statusLabel(order.status)}</b></div><div className="rounded-lg bg-[#f5f3ed] p-3"><span className="block text-xs text-[#52616b]">委托数量</span><b>{order.quantity ?? "—"}</b></div><div className="rounded-lg bg-[#f5f3ed] p-3"><span className="block text-xs text-[#52616b]">成交数量</span><b>{order.filled_quantity ?? order.filled_qty ?? 0}</b></div></div><div className="mt-4 grid grid-cols-2 gap-3 rounded-lg border border-[#edf0f2] p-3 text-xs sm:grid-cols-3"><div><span className="block text-[#52616b]">Broker Order ID</span><b className="break-all">{order.broker_order_id || "—"}</b></div><div><span className="block text-[#52616b]">Client Order ID</span><b className="break-all">{order.client_order_id || "—"}</b></div><div><span className="block text-[#52616b]">所属 ExecutionPlan</span><b>{order.execution_plan_id ?? "—"}</b></div><div><span className="block text-[#52616b]">所属 TradePlan</span><b>{order.trade_plan_id ?? "—"}</b></div><div><span className="block text-[#52616b]">所属 Trade</span><b>{order.trade_id ? `Trade #${order.trade_id}` : "—"}</b></div><div><span className="block text-[#52616b]">订单时间</span><b>{order.created_at || "—"}</b></div></div><h3 className="mt-5 mb-2 text-sm font-bold">成交回报</h3>{fills.length ? <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead className="bg-[#f5f3ed]"><tr><th className="px-3 py-2">时间</th><th className="px-3 py-2">成交价</th><th className="px-3 py-2">成交数量</th><th className="px-3 py-2">券商成交号</th></tr></thead><tbody>{fills.map((fill: any) => <tr key={fill.id} className="border-t border-[#edf0f2]"><td className="px-3 py-2">{fill.filled_at || fill.created_at || "—"}</td><td className="px-3 py-2">{money(fill.price)}</td><td className="px-3 py-2">{fill.quantity ?? fill.filled_quantity ?? "—"}</td><td className="px-3 py-2">{fill.broker_fill_id || "—"}</td></tr>)}</tbody></table></div> : <p className="rounded-lg bg-[#f5f3ed] p-3 text-sm text-[#52616b]">当前订单暂无成交回报。</p>}<div className="mt-5 flex justify-end"><button onClick={onClose} className="rounded-lg bg-[#0f5238] px-3 py-2 text-sm font-bold text-white">关闭</button></div></div></div>;
}
function Card({
  children,
  className = "",
  id,
}: {
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section
      id={id}
      className={`rounded-xl bg-white shadow-[0_2px_7px_rgba(25,28,29,0.06)] ${className}`}
    >
      {children}
    </section>
  );
}
function MetricCard({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div
      className={`rounded-xl border border-[#dee2e6] p-3 ${accent ? "bg-[#effaf4]" : "bg-white"}`}
    >
      <div className="text-xs tracking-wide text-[#52616b]">{label}</div>
      <div
        className={`mt-1 text-xl font-bold ${accent ? "text-[#0f5238]" : ""}`}
      >
        {value}
      </div>
    </div>
  );
}

function OverviewPage({
  onNavigate,
  onOpenTrade,
  accountId,
}: {
  onNavigate: (view: TradingView) => void;
  onOpenTrade: (tradeId: number) => void;
  accountId: number;
}) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  async function load() {
    try {
      const [overview, trades, executions, orders] = await Promise.all([
        request(accountPath("/api/trading/overview", accountId)),
        request(accountPath("/api/trades", accountId)),
        request(accountPath("/api/trading/execution-plans", accountId)),
        request(accountPath("/api/trading/orders", accountId)),
      ]);
      const groupedPlans = (trades.items || []).flatMap((trade: any) =>
        (trade.plans || []).map((plan: any) => ({ ...plan, trade_id: trade.id, trade_status: trade.status })),
      );
      setData({
        ...overview,
        trades: trades.items || [],
        plans: groupedPlans,
        executions: executions.items || [],
        orders: orders.items || [],
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "交易总览读取失败");
    }
  }
  useEffect(() => {
    setData(null);
    setError(null);
    load();
  }, [accountId]);
  if (error)
    return (
      <PageFrame>
        <ErrorBox message={error} onRetry={load} />
      </PageFrame>
    );
  if (!data)
    return (
      <PageFrame>
        <Loading />
      </PageFrame>
    );
  const account = data.account;
  // The overview exposure panel represents actual open exposure.  Planned
  // Trades remain visible in the Trade list, but they have no position or
  // exposure yet and must not be counted as active.
  const activeTrades = data.trades.filter((item: any) => ["ACTIVE", "CLOSING"].includes(item.status));
  const readyPlans = data.plans.filter((item: any) => item.status === "READY");
  const unfinishedOrders = data.orders.filter((item: any) => !["FILLED", "CANCELLED", "REJECTED", "EXPIRED"].includes(item.status));
  const exposure = typeof account.total_exposure_pct === "number" ? account.total_exposure_pct * 100 : null;
  const risk = typeof account.equity === "number" && typeof data.risk_profile?.default_trade_risk_pct === "number"
    ? account.equity * data.risk_profile.default_trade_risk_pct
    : null;
  const typeText = (type: string) => type === "TREND" ? "趋势交易" : type === "REBOUND" ? "反弹/波段" : type === "FIXED_TARGET" ? "固定目标" : "自定义";
  const statusText = (status: string) => status === "ACTIVE" ? "ACTIVE" : status === "CLOSING" ? "CLOSING" : "PLANNED";
  const latestPlan = (trade: any) => trade.plans?.length ? trade.plans[trade.plans.length - 1] : null;
  const pnlTone = (item: any) => Number(item.unrealized_pnl || 0) >= 0 ? "text-[#a73354]" : "text-[#2b543c]";
  const environmentText = account.account_type === "SIMULATION" ? "仿真" : account.account_type === "LIVE" ? "实盘" : "规划";
  const brokerNodeStatus = data.broker_status?.node_status || {};
  const engineText = !data.broker_status?.ok && data.broker_status?.status !== "CONNECTED"
    ? "未连接"
    : brokerNodeStatus.reconciliation_required
      ? "待对账"
      : data.control?.execution_paused || brokerNodeStatus.paused
        ? "已暂停"
        : brokerNodeStatus.execution_enabled === false
          ? "暂不可执行"
          : "已连接";
  const card = (tone: string, icon: ReactNode, title: string, badge: string, value: ReactNode, footer: ReactNode, extra?: ReactNode) => (
    <div className={`flex min-h-[140px] flex-col justify-between overflow-hidden rounded-xl p-5 shadow-sm ${tone}`}>
      <div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2">{icon}<span className="text-sm font-medium">{title}</span></div><span className="rounded-full bg-white/15 px-2 py-0.5 text-[11px]">{badge}</span></div>
      <div className="my-2 flex items-baseline gap-2 text-[28px] font-bold tracking-tight">{value}{extra}</div>
      <div className="flex items-center justify-between gap-3 text-xs opacity-85">{footer}</div>
    </div>
  );
  return <PageFrame className="pb-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3"><span className="h-2.5 w-2.5 animate-pulse rounded-full bg-[#2b543c]" /><span className="text-base font-semibold">账户资产与活动 Trade 全景监控</span><span className="hidden h-4 w-px bg-[#c1c8c1] sm:block" /><span className="text-xs text-[#414943]">价格口径：最近一次有效行情</span></div>
      <div className="flex items-center gap-2"><div className="flex items-center gap-1.5 rounded-lg bg-white px-3 py-2 text-xs shadow-sm"><Activity className="h-4 w-4 text-[#2b543c]" />交易环境：<b className="text-[#2b543c]">{environmentText}</b></div><div className="flex items-center gap-1.5 rounded-lg bg-white px-3 py-2 text-xs shadow-sm"><span className={`h-2 w-2 rounded-full ${engineText === "已连接" ? "bg-[#2b543c]" : "bg-[#a64b00]"}`} />执行引擎：<b>{engineText}</b></div><button onClick={() => onNavigate("plan")} className="inline-flex items-center gap-1 rounded-lg bg-[#2b543c] px-3 py-2 text-sm font-medium text-white"><Plus className="h-4 w-4" />新建交易</button></div>
    </div>
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {card("bg-[#434c54] text-white", <Landmark className="h-5 w-5 text-[#d8e1eb]" />, "账户净资产", account.account_type === "LIVE" ? "实盘主账户" : "规划账户", money(account.equity), <span>可用现金 {money(account.available_cash)}</span>, <span className="text-xs">占比 {typeof account.available_cash === "number" && typeof account.equity === "number" && account.equity ? `${((account.available_cash / account.equity) * 100).toFixed(1)}%` : "—"}</span>)}
      {card("bg-[#436c53] text-white", <Activity className="h-5 w-5 text-[#beebcc]" />, "当前总仓位", "持仓市值 " + money(account.market_value), exposure === null ? "—" : `${exposure.toFixed(1)}%`, <span>当前总头寸 {data.positions.length} 只</span>, <span className="text-xs">/ 上限 {pct(data.risk_profile?.max_total_exposure_pct)}</span>)}
      {card("bg-[#a73354] text-white", <Shield className="h-5 w-5 text-[#ffd9de]" />, "账户总计划风险", "风控状态：正常", risk === null ? "—" : money(risk), <span>单笔硬上限 {pct(data.risk_profile?.max_trade_risk_pct)}</span>, <span className="text-xs">已设止损敞口</span>)}
      {card("bg-white text-[#1b1c18]", <Activity className="h-5 w-5 text-[#a73354]" />, "今日浮动盈亏", "日内表现", money(account.unrealized_pnl), <span>累计实现盈亏</span>, <span className="text-xs text-[#a73354]">{money(account.realized_pnl)}</span>)}
    </div>
    <Card className="flex flex-col gap-4 bg-white p-5">
      <div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2"><div className="grid h-6 w-6 place-items-center rounded-lg bg-[#eae8e2]"><AlertTriangle className="h-4 w-4" /></div><h2 className="text-base font-semibold">待处理事项</h2><span className="rounded-full bg-[#ffd9de] px-2 py-0.5 text-[11px] font-medium text-[#88193d]">{readyPlans.length} 项需要关注</span></div><span className="text-xs text-[#414943]">自动化风控队列实时轮询中</span></div>
      <div className="grid gap-3 md:grid-cols-3">
        {[...readyPlans.slice(0, 1).map((plan: any) => ({ kind: "warning", title: plan.symbol, text: `${actionLabel(plan.input_json?.action_type)} 计划已就绪，等待创建执行计划。`, meta: "待部署", action: "立即部署执行" })), ...data.positions.filter((p: any) => Number(p.available_quantity) < Number(p.quantity)).slice(0, 1).map((p: any) => ({ kind: "clock", title: p.symbol, text: `当前剩余持仓受 T+1 或可卖数量限制，需等待可卖。`, meta: "流通受限", action: "查看详情" })), ...activeTrades.slice(0, 1).map((t: any) => ({ kind: "review", title: t.symbol, text: "整体风险参考需要复核，建议查看 Trade 详情。", meta: "风险复核", action: "复核调整" }))].map((item: any, index: number) => <div key={`${item.kind}-${item.title}-${index}`} className="flex min-h-[112px] flex-col justify-between gap-2 rounded-lg bg-[#f5f3ed] p-3"><div className="flex items-start gap-2"><AlertTriangle className={`mt-0.5 h-5 w-5 shrink-0 ${item.kind === "warning" ? "text-[#a73354]" : "text-[#434c54]"}`} /><div><b className="block text-sm">{item.title}</b><p className="mt-1 text-xs text-[#414943]">{item.text}</p></div></div><div className="flex items-center justify-between"><span className="text-[10px] text-[#717972]">{item.meta}</span><button onClick={() => onNavigate(item.kind === "warning" ? "execution" : "trades")} className="rounded-lg bg-[#2b543c] px-2.5 py-1 text-[11px] font-semibold text-white">{item.action}</button></div></div>)}
        {!readyPlans.length && !data.positions.some((p: any) => Number(p.available_quantity) < Number(p.quantity)) && !activeTrades.length && <div className="md:col-span-3 rounded-lg bg-[#f5f3ed] p-4 text-sm text-[#414943]">当前没有需要立即处理的事项。</div>}
      </div>
    </Card>
    <Card className="overflow-hidden bg-white p-0">
      <div className="flex flex-wrap items-center justify-between gap-3 p-5"><div className="flex flex-wrap items-center gap-3"><div className="flex items-center gap-2"><Activity className="h-5 w-5 text-[#2b543c]" /><h2 className="text-base font-semibold">活动 Trade 实时监控</h2></div><div className="flex items-center gap-1 rounded-lg bg-[#f5f3ed] p-0.5 text-xs"><button className="rounded-md bg-white px-3 py-1.5 font-semibold shadow-sm">全部活动 ({activeTrades.length})</button><button className="px-3 py-1.5 text-[#414943]">趋势突破</button><button className="px-3 py-1.5 text-[#414943]">波段/回踩</button><button className="px-3 py-1.5 text-[#414943]">退出管理</button></div></div><div className="flex items-center gap-2 text-xs text-[#414943]"><span className="flex items-center gap-1 rounded-lg bg-[#f5f3ed] px-2 py-1.5"><Filter className="h-4 w-4" />按风险敞口降序</span><button title="导出" className="rounded-lg p-1.5 hover:bg-[#f0eee8]"><Download className="h-5 w-5" /></button></div></div>
      <div className="overflow-x-auto"><table className="w-full min-w-[1260px] border-collapse text-left text-xs"><thead className="bg-[#f5f3ed] text-[#414943]"><tr>{["股票代码 / 名称","交易类型","生命周期","当前持仓","仓位占比","现价 / 成本","浮动盈亏","本金计划风险","利润回吐风险","最近动作","操作"].map((label) => <th key={label} className="px-4 py-3 font-medium">{label}</th>)}</tr></thead><tbody>{activeTrades.map((item: any) => { const position = data.positions.find((p: any) => p.symbol === item.symbol); const plan = latestPlan(item); const quantity = position?.quantity ?? "—"; const available = position?.available_quantity ?? "—"; const exposurePct = typeof position?.market_value === "number" && typeof account.equity === "number" && account.equity ? (position.market_value / account.equity) * 100 : null; const pnl = position?.unrealized_pnl; return <tr key={item.id} className="border-t border-[#eae8e2] hover:bg-[#fbf9f3]"><td className="px-4 py-4"><button onClick={() => onOpenTrade(item.id)} className="text-left"><b className="mr-2 text-sm text-[#a73354]">{item.symbol}</b><b className="text-sm">{item.symbol_name}</b><span className="mt-1 block text-[10px] text-[#717972]">{item.sector || "—"}</span></button></td><td className="px-4 py-4"><span className="rounded bg-[#f0eee8] px-2 py-1">{typeText(item.trade_type)}</span></td><td className="px-4 py-4"><span className={`rounded-full px-2 py-1 text-[10px] font-medium ${item.status === "CLOSING" ? "bg-[#a73354] text-white" : "bg-[#2b543c] text-white"}`}>{statusText(item.status)}</span></td><td className="px-4 py-4"><b className="block text-sm">{quantity} 股</b><span className="text-[10px] text-[#717972]">可卖 {available} 股</span></td><td className="px-4 py-4"><div className="flex items-center gap-2"><span>{exposurePct === null ? "—" : `${exposurePct.toFixed(1)}%`}</span><span className="h-1.5 w-12 overflow-hidden rounded-full bg-[#e4e2dd]"><span className="block h-full rounded-full bg-[#2b543c]" style={{ width: `${Math.min(100, exposurePct || 0)}%` }} /></span></div></td><td className="px-4 py-4"><b className="block">{money(position?.market_price)}</b><span className="text-[#717972]">成本：{money(position?.average_cost)}</span></td><td className={`px-4 py-4 ${pnlTone(position || {})}`}><b className="block text-sm">{money(pnl)}</b><span>{typeof pnl === "number" && typeof position?.market_value === "number" && position.market_value ? `${((pnl / position.market_value) * 100).toFixed(2)}%` : "—"}</span></td><td className="px-4 py-4 text-[#2b543c]">{risk === null ? "—" : money(risk)}<span className="block text-[10px]">{risk === null ? "" : "已设止损敞口"}</span></td><td className="px-4 py-4">{money(item.profit_retrace_risk)}</td><td className="px-4 py-4"><span className={`rounded px-2 py-1 ${item.status === "CLOSING" ? "bg-[#ffd9de] text-[#88193d]" : "bg-[#f0eee8]"}`}>{plan ? `${actionLabel(plan.action_type)} #${plan.sequence_no}` : "—"}</span></td><td className="px-4 py-4 text-right"><button onClick={() => onOpenTrade(item.id)} className="inline-flex items-center gap-1 rounded-lg bg-[#f5f3ed] px-3 py-1.5 font-semibold text-[#2b543c]">查看详情<ChevronRight className="h-4 w-4" /></button></td></tr>; })}</tbody></table></div>
      <div className="flex flex-wrap items-center justify-between gap-3 bg-[#f5f3ed] px-5 py-3 text-xs text-[#414943]"><div className="flex flex-wrap items-center gap-3"><span>统计：活动头寸 {activeTrades.length} 笔</span><span>•</span><span>持仓均赢率 {data.positions.length ? `${((data.positions.filter((p: any) => Number(p.unrealized_pnl || 0) >= 0).length / data.positions.length) * 100).toFixed(1)}%` : "—"}</span><span>•</span><span>未实现净收益：<b className="text-[#a73354]">{money(account.unrealized_pnl)}</b></span></div><span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[#2b543c]" />数据流已绑定券商行情分发引擎</span></div>
    </Card>
    <div className="grid gap-4 lg:grid-cols-12"><Card className="flex flex-col justify-between gap-4 bg-white p-5 lg:col-span-7"><div><div className="mb-4 flex items-center justify-between"><div className="flex items-center gap-2"><History className="h-5 w-5 text-[#2b543c]" /><h2 className="text-base font-semibold">最近操作与执行流水</h2></div><span className="rounded bg-[#f0eee8] px-2 py-1 text-[11px]">今日流水：{data.orders.length} 笔</span></div><div className="relative flex flex-col gap-4 border-l-2 border-[#eae8e2] pl-5">{[...data.orders.slice(0, 3).map((order: any) => ({ title: order.symbol || "—", tag: statusLabel(order.status), text: `${statusLabel(order.status)}，订单状态已同步至交易系统`, time: order.updated_at || order.created_at || "—" })), ...data.executions.slice(0, 3).map((execution: any) => ({ title: execution.symbol || "—", tag: statusLabel(execution.status), text: `执行计划${statusLabel(execution.status)}`, time: execution.updated_at || execution.created_at || "—" }))].slice(0, 3).map((event: any, index: number) => <div key={`${event.title}-${event.time}-${index}`} className="relative flex items-start justify-between gap-3"><span className="absolute -left-[1.62rem] top-1 h-2.5 w-2.5 rounded-full bg-[#2b543c] ring-4 ring-white" /><div><div className="flex flex-wrap items-center gap-2"><b className="text-sm">{event.title}</b><span className="rounded bg-[#c0edce] px-2 py-0.5 text-[10px]">{event.tag}</span></div><p className="mt-1 text-xs text-[#414943]">{event.text}</p></div><span className="whitespace-nowrap text-[10px] text-[#717972]">{event.time}</span></div>)}{!data.orders.length && !data.executions.length && <p className="text-sm text-[#717972]">暂无执行流水。</p>}</div></div><div className="flex items-center justify-between rounded-lg bg-[#f5f3ed] p-3 text-xs text-[#414943]"><span>已记录交易信号、委托确认与挂单回报</span><button onClick={() => onNavigate("orders")} className="flex items-center gap-1 font-semibold text-[#2b543c]">查看完整订单日志<ChevronRight className="h-4 w-4" /></button></div></Card>
      <Card className="flex flex-col justify-between gap-4 bg-white p-5 lg:col-span-5"><div><div className="mb-4 flex items-center justify-between"><div className="flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-[#2b543c]" /><h2 className="text-base font-semibold">风控与执行合规看板</h2></div><span className="rounded-full bg-[#c0edce] px-2 py-1 text-[11px] text-[#264f38]">合规等级 A+</span></div><div className="flex flex-col gap-4"><div className="rounded-lg bg-[#f5f3ed] p-3"><div className="flex items-center justify-between text-xs"><span>总风险暴露度（Total Plan Risk）</span><b>{risk === null ? "—" : `${(data.risk_profile?.default_trade_risk_pct * 100).toFixed(2)}% / ${(data.risk_profile?.max_trade_risk_pct * 100).toFixed(2)}%`}</b></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-[#e4e2dd]"><div className="h-full rounded-full bg-[#2b543c]" style={{ width: `${Math.min(100, (data.risk_profile?.default_trade_risk_pct || 0) / (data.risk_profile?.max_trade_risk_pct || 1) * 100)}%` }} /></div><span className="mt-1 block text-[10px] text-[#717972]">基于当前账户风险规则计算</span></div><div className="rounded-lg bg-[#f5f3ed] p-3"><div className="flex items-center justify-between text-xs"><span>头寸集中度（Max Single Position）</span><b>{data.positions.length ? `${Math.max(...data.positions.map((p: any) => Number(p.market_value || 0))) && account.equity ? `${(Math.max(...data.positions.map((p: any) => Number(p.market_value || 0))) / account.equity * 100).toFixed(1)}%` : "—"}` : "—"}</b></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-[#e4e2dd]"><div className="h-full rounded-full bg-[#434c54]" style={{ width: `${Math.min(100, exposure || 0)}%` }} /></div><span className="mt-1 block text-[10px] text-[#717972]">单票上限规则为 {pct(data.risk_profile?.max_single_position_pct)}</span></div><div className="flex items-start gap-2 rounded-lg bg-[#f0eee8] p-3"><CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-[#2b543c]" /><div><b className="block text-xs">风控策略状态通报</b><p className="mt-1 text-xs text-[#414943]">{activeTrades.length ? `当前 ${activeTrades.length} 笔活动 Trade 已接入风险计算，实际风险以账户与持仓接口返回为准。` : "当前没有活动 Trade，等待交易数据接入。"}</p></div></div></div></div><div className="flex items-center justify-between text-[10px] text-[#717972]"><span>自动风控巡检：每秒 1 次</span><button onClick={() => onNavigate("settings")} className="flex items-center gap-1 hover:text-[#2b543c]"><Settings className="h-3.5 w-3.5" />风控参数设置</button></div></Card></div>
  </PageFrame>;
}

function ExecutionPage({ accountId, onRefresh }: { accountId: number; onRefresh: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [readyPlans, setReadyPlans] = useState<any[]>([]);
  const [broker, setBroker] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [composer, setComposer] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  async function load() {
    try {
      const [plans, brokerResult, trades] = await Promise.all([
        request(accountPath("/api/trading/execution-plans", accountId)),
        request(accountPath("/api/trading/broker", accountId)),
        request(accountPath("/api/trades", accountId)),
      ]);
      setItems(plans.items || []);
      setBroker(brokerResult);
      setReadyPlans((trades.items || []).flatMap((trade: any) => (trade.plans || [])
        .filter((plan: any) => ["READY", "ARMED"].includes(plan.status))
        .map((plan: any) => ({ ...plan, trade_status: trade.status, trade_type: trade.trade_type }))));
    } catch (e) {
      setError(e instanceof Error ? e.message : "交易执行读取失败");
    }
  }
  useEffect(() => {
    setItems([]);
    setBroker(null);
    setReadyPlans([]);
    setError(null);
    load();
  }, [accountId]);
  async function setStatus(id: number, status: string) {
    try {
      await request(accountPath(`/api/trading/execution-plans/${id}/status`, accountId), {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      await load();
      onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "执行计划状态更新失败");
    }
  }
  async function createExecutionPlan() {
    if (!composer) return;
    setBusy(true);
    setError(null);
    try {
      const created = await request(accountPath("/api/trading/execution-plans", accountId), {
        method: "POST",
        body: JSON.stringify({
          trade_plan_id: composer.tradePlan.id,
          symbol: composer.tradePlan.symbol,
          side: ["REDUCE", "CLOSE"].includes(composer.tradePlan.input_json?.action_type) ? "SELL" : "BUY",
          target_qty: Number(composer.tradePlan.calculation_snapshot_json?.planned_qty),
          execution_type: composer.execution_type,
          valid_until: composer.valid_until || null,
          execution_params: composer.execution_params,
        }),
      });
      await request(accountPath(`/api/trading/execution-plans/${created.item.id}/status`, accountId), {
        method: "PATCH",
        body: JSON.stringify({ status: "ACTIVE" }),
      });
      setComposer(null);
      await load();
      onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "执行计划创建失败");
    } finally {
      setBusy(false);
    }
  }
  const executionPlanIds = new Set(items.map((item) => item.trade_plan_id));
  const brokerConnected = brokerConnectionHealthy(broker?.connection);
  const brokerNodeStatus = broker?.connection?.node_status || {};
  const executionReady = brokerConnected && brokerNodeStatus.execution_enabled === true && !brokerNodeStatus.reconciliation_required && brokerNodeStatus.paused !== true;
  return (
    <PageFrame>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-[#0f5238]">EXECUTION DESK</p><h1 className="mt-1 text-3xl font-bold">交易执行 <span className="text-xl font-normal text-[#52616b]">/ Orders & Routing</span></h1><p className="mt-1 text-sm text-[#52616b]">将已确认的 TradePlan 转换为可管理的执行计划。</p></div><div className="grid grid-cols-3 gap-2 text-center"><div className="rounded-xl border border-[#e2ded4] bg-white px-5 py-3"><p className="text-xs text-[#52616b]">活跃执行</p><b className="text-xl text-[#0f5238]">{items.filter((item) => item.status === "ACTIVE").length}</b></div><div className="rounded-xl border border-[#e2ded4] bg-white px-5 py-3"><p className="text-xs text-[#52616b]">已暂停</p><b className="text-xl">{items.filter((item) => item.status === "PAUSED").length}</b></div><div className="rounded-xl border border-[#e2ded4] bg-white px-5 py-3"><p className="text-xs text-[#52616b]">待创建</p><b className="text-xl">{readyPlans.filter((plan) => !executionPlanIds.has(plan.id)).length}</b></div></div></div>
      {!executionReady && (
        <div className="mb-4 flex items-center justify-between gap-4 rounded-xl border border-[#ffb3b3] bg-[#ffdad6] px-5 py-4 text-[#93000a]">
          <div className="flex items-center gap-3"><Cable className="h-7 w-7 shrink-0" /><div><b className="block text-base">{!brokerConnected ? "券商未连接" : brokerNodeStatus.reconciliation_required ? "券商已连接，待完成对账" : brokerNodeStatus.paused ? "当前账号已暂停执行" : "当前暂不可执行"}</b><span className="text-sm">暂不可发送委托；可以保存执行意图、查看记录和完成风险复核。</span></div></div>
          <span className="rounded-lg bg-white px-3 py-2 text-xs font-bold">{!brokerConnected ? "请前往交易设置连接券商" : brokerNodeStatus.reconciliation_required ? "完成对账后可执行" : brokerNodeStatus.paused ? "恢复账号执行后可发送委托" : "检查执行权限后重试"}</span>
        </div>
      )}
      {error && <ErrorBox message={error} onRetry={load} />}
      {composer && (
        <Card className="mb-3 border border-[#bdc9d8] bg-[#f4f7fb] p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-bold text-[#354860]">创建执行计划</h2>
              <p className="mt-0.5 text-xs text-[#52616b]">
                {composer.tradePlan.symbol} {composer.tradePlan.security_name} · 目标 {Number(composer.tradePlan.calculation_snapshot_json?.planned_qty || 0).toLocaleString()} 股
              </p>
            </div>
            <button type="button" title="关闭" onClick={() => setComposer(null)} className="rounded-md p-1.5 hover:bg-white">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="grid gap-2 sm:grid-cols-4">
            <label className="text-xs font-bold text-[#52616b] sm:col-span-1">
              执行方式
              <select
                value={composer.execution_type}
                onChange={(e) => setComposer((current: any) => ({ ...current, execution_type: e.target.value }))}
                className="input mt-1"
              >
                <option value="LIMIT">限价委托</option>
                <option value="PERSISTENT_LIMIT">持续限价</option>
                <option value="PRICE_TRIGGER">价格触发</option>
                <option value="PRICE_RANGE">价格区间触发</option>
              </select>
            </label>
            {composer.execution_type === "PRICE_RANGE" ? (
              <>
                <label className="text-xs font-bold text-[#52616b]">最低触发价<input type="number" step="0.01" value={composer.execution_params.low_price} onChange={(e) => setComposer((current: any) => ({ ...current, execution_params: { ...current.execution_params, low_price: Number(e.target.value) } }))} className="input mt-1" /></label>
                <label className="text-xs font-bold text-[#52616b]">最高触发价<input type="number" step="0.01" value={composer.execution_params.high_price} onChange={(e) => setComposer((current: any) => ({ ...current, execution_params: { ...current.execution_params, high_price: Number(e.target.value) } }))} className="input mt-1" /></label>
              </>
            ) : (
              <label className="text-xs font-bold text-[#52616b] sm:col-span-1">
                {composer.execution_type === "PRICE_TRIGGER" ? "触发价格" : "限价"}
                <input type="number" step="0.01" value={composer.execution_params[composer.execution_type === "PRICE_TRIGGER" ? "trigger_price" : "limit_price"]} onChange={(e) => setComposer((current: any) => ({ ...current, execution_params: { ...current.execution_params, [current.execution_type === "PRICE_TRIGGER" ? "trigger_price" : "limit_price"]: Number(e.target.value) } }))} className="input mt-1" />
              </label>
            )}
            <label className="text-xs font-bold text-[#52616b]">有效期<input type="date" value={composer.valid_until} onChange={(e) => setComposer((current: any) => ({ ...current, valid_until: e.target.value ? `${e.target.value}T23:59:59+08:00` : "" }))} className="input mt-1" /></label>
          </div>
          <div className="mt-3 flex items-center justify-between gap-3">
            <span className="text-xs text-[#52616b]">最高可接受价：{money(Number(composer.tradePlan.input_json?.max_acceptable_entry_price))}。启用后仍需通过下单前风控。</span>
            <button type="button" disabled={busy} onClick={createExecutionPlan} className="inline-flex items-center gap-1.5 rounded-md bg-[#354860] px-3 py-2 text-xs font-bold text-white disabled:opacity-50"><Zap className="h-3.5 w-3.5" />保存并启用</button>
          </div>
        </Card>
      )}
      {readyPlans.filter((plan) => !executionPlanIds.has(plan.id)).length > 0 && (
        <Card className="mb-3 p-4">
          <div className="mb-2 flex items-center justify-between"><h2 className="text-base font-bold">待执行交易计划</h2><span className="text-xs text-[#52616b]">已确认的 TradePlan</span></div>
          <div className="divide-y divide-[#edf0f2]">
            {readyPlans.filter((plan) => !executionPlanIds.has(plan.id)).map((plan) => (
              <div key={plan.id} className="flex items-center justify-between gap-3 py-2.5">
                <div className="min-w-0 text-sm"><b>{plan.symbol} {plan.security_name}</b><span className="ml-2 text-xs text-[#52616b]">计划 {Number(plan.calculation_snapshot_json?.planned_qty || 0).toLocaleString()} 股 · 参考 {money(Number(plan.input_json?.reference_entry_price))} · 上限 {money(Number(plan.input_json?.max_acceptable_entry_price))}</span></div>
                <button type="button" title="创建执行计划" onClick={() => setComposer({ tradePlan: plan, execution_type: "LIMIT", execution_params: { limit_price: Number(plan.input_json?.reference_entry_price) }, valid_until: "" })} className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-[#354860] px-2.5 py-1.5 text-xs font-bold text-white"><Plus className="h-3.5 w-3.5" />创建执行</button>
              </div>
            ))}
          </div>
        </Card>
      )}
      {items.length ? (
        <div className="space-y-3">
          {items.map((item) => (
            <Card key={item.id} className="border-l-4 border-[#0f5238] p-4">
              <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)_180px]">
                <div>
                  <div className="flex items-center gap-3">
                    <h3 className="text-lg font-bold">{item.symbol}</h3>
                    <span className="rounded bg-[#d9f4e6] px-2 py-1 text-xs font-bold text-[#0e5138]">
                      {item.side === "BUY" ? "买入" : "卖出"}
                    </span>
                  </div>
                  <div className="mt-2 text-sm text-[#52616b]">
                    {executionTypeLabel(item.execution_type)} · 目标{" "}
                    {item.target_qty.toLocaleString()} 股
                  </div>
                  <div className="mt-1 text-xs text-[#354860]">规则：{executionRuleLabel(item)}</div>
                </div>
                <div>
                  <div className="mb-2 flex justify-between text-sm">
                    <span>执行进度</span>
                    <span>
                      {item.filled_qty.toLocaleString()} /{" "}
                      {item.target_qty.toLocaleString()}
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-[#e1e3e4]">
                    <div
                      className="h-full rounded-full bg-[#2d6a4f]"
                      style={{
                        width: `${Math.min(100, item.target_qty ? (item.filled_qty / item.target_qty) * 100 : 0)}%`,
                      }}
                    />
                  </div>
                  <div className="mt-2 text-sm text-[#52616b]">
                    剩余：{item.remaining_qty.toLocaleString()} 股
                  </div>
                </div>
                <div className="flex items-center justify-end gap-2">
                  <span
                    className={`rounded-full px-3 py-1 text-xs font-bold ${item.status === "PAUSED" ? "bg-[#fff0dc] text-[#a64b00]" : "bg-[#d9f4e6] text-[#0e5138]"}`}
                  >
                    {statusLabel(item.status)}
                  </span>
                  {item.status === "ACTIVE" && (
                    <button
                      onClick={() => setStatus(item.id, "PAUSED")}
                      title="暂停"
                      className="rounded-full bg-[#f3f4f5] p-3"
                    >
                      <Pause className="h-4 w-4" />
                    </button>
                  )}
                  {item.status === "PAUSED" && (
                    <button
                      onClick={() => setStatus(item.id, "ACTIVE")}
                      title="继续"
                      className="rounded-full bg-[#f3f4f5] p-3"
                    >
                      <Play className="h-4 w-4" />
                    </button>
                  )}
                  <button
                    onClick={() => setStatus(item.id, "CANCELLED")}
                    title="取消"
                    className="rounded-full bg-[#f3f4f5] p-3"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <EmptyState icon={<ListChecks />} text="还没有执行计划" />{" "}
        </Card>
      )}
    </PageFrame>
  );
}

function OrdersPage({ accountId }: { accountId: number }) {
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<any>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  async function load() {
    try {
      const [result, executions, trades, fills] = await Promise.all([request(accountPath("/api/trading/orders", accountId)), request(accountPath("/api/trading/execution-plans", accountId)), request(accountPath("/api/trades", accountId)), request(accountPath("/api/trading/fills", accountId))]);
      const plans = new Map<number, any>();
      (trades.items || []).forEach((trade: any) => (trade.plans || []).forEach((plan: any) => plans.set(plan.id, trade)));
      const executionMap = new Map<number, any>((executions.items || []).map((item: any) => [item.id, item]));
      const fillsByOrder = new Map<number, any[]>();
      (fills.items || []).forEach((fill: any) => fillsByOrder.set(fill.order_id, [...(fillsByOrder.get(fill.order_id) || []), fill]));
      setItems((result.items || []).map((order: any) => ({ ...order, fills: fillsByOrder.get(order.id) || [], execution: executionMap.get(order.execution_plan_id), trade: plans.get(executionMap.get(order.execution_plan_id)?.trade_plan_id) })));
    } catch (e) {
      setError(e instanceof Error ? e.message : "订单读取失败");
    }
  }
  useEffect(() => {
    setItems([]);
    setSelected(null);
    setError(null);
    load();
  }, [accountId]);
  async function cancel(id: number) {
    try {
      await request(accountPath(`/api/trading/orders/${id}/cancel`, accountId), { method: "POST" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "撤单失败");
    }
  }
  const visibleItems = items.filter((item) => {
    const needle = query.trim().toLowerCase();
    const matchesQuery = !needle || [item.symbol, item.trade?.symbol, item.client_order_id, item.broker_order_id].some((value) => String(value || "").toLowerCase().includes(needle));
    return matchesQuery && (statusFilter === "ALL" || item.status === statusFilter);
  });
  return (
    <PageFrame>
      <div className="mb-5 flex items-end justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-[#0f5238]">ORDER LEDGER</p><h1 className="mt-1 text-3xl font-bold">订单</h1><p className="mt-1 text-sm text-[#52616b]">以真实委托和成交记录为准，点击详情查看所属 Trade 与执行计划。</p></div><div className="rounded-xl border border-[#e2ded4] bg-white px-4 py-3 text-sm"><span className="text-[#52616b]">订单总数</span><b className="ml-3 text-xl">{items.length}</b></div></div>
      {error && <ErrorBox message={error} onRetry={load} />}
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-[#dee2e6] bg-[#f8f7f2] px-4 py-3">
          <label className="relative min-w-[220px] flex-1"><span className="sr-only">搜索订单</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索证券、Trade 或订单号" className="w-full rounded-lg bg-white px-3 py-2 text-sm outline-none ring-1 ring-[#dee2e6] focus:ring-[#0f5238]" /></label>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="rounded-lg bg-white px-3 py-2 text-sm ring-1 ring-[#dee2e6] outline-none"><option value="ALL">全部状态</option>{["PENDING_SUBMIT", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"].map((value) => <option key={value} value={value}>{statusLabel(value)}</option>)}</select>
          <span className="text-xs text-[#52616b]">显示 {visibleItems.length} / {items.length}</span>
          <button onClick={load} title="刷新订单" aria-label="刷新订单" className="rounded-md p-1.5 text-[#52616b] hover:bg-[#f3f4f5]">
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
        {visibleItems.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#f3f4f5] text-xs uppercase tracking-wide text-[#404943]">
                <tr>
                  {[
                    "时间",
                    "证券",
                    "所属 Trade / 动作",
                    "类型",
                    "价格",
                    "数量",
                    "成交",
                    "状态",
                    "订单编号",
                    "操作",
                  ].map((label) => (
                    <th key={label} className="px-4 py-2.5">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleItems.map((item) => (
                  <tr key={item.id} className="border-t border-[#dee2e6]">
                    <td className="px-4 py-3 text-[#52616b]">
                      {item.created_at?.slice(11, 19) || "—"}
                    </td>
                    <td className="px-4 py-3">
                      <b>{item.symbol}</b>
                      <div className="text-xs text-[#52616b]">
                        {item.side === "BUY" ? "买入" : "卖出"}
                      </div>
                    </td>
                    <td className="px-4 py-3"><b>{item.trade?.symbol || "—"}</b><div className="text-xs text-[#52616b]">{item.trade ? `${actionLabel(item.trade.input_json?.action_type)} #${item.trade.sequence_no}` : "未关联 Trade"}</div></td>
                    <td className="px-4 py-3">{item.order_type}</td>
                    <td className="px-4 py-3 font-mono">
                      {item.price == null ? "市价" : item.price}
                    </td>
                    <td className="px-4 py-3">
                      {item.quantity.toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      {item.filled_quantity.toLocaleString()} (
                      {item.quantity
                        ? Math.round(
                            (item.filled_quantity / item.quantity) * 100,
                          )
                        : 0}
                      %)
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded-full bg-[#e7e8e9] px-3 py-1 text-xs font-bold">
                        {statusLabel(item.status)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[#52616b]">
                      {item.broker_order_id || item.client_order_id}
                    </td>
                    <td className="px-4 py-3">
                      <button type="button" onClick={() => setSelected(item)} className="mr-3 text-xs font-bold text-[#0f5238]">详情</button>
                      {!["FILLED", "CANCELLED", "REJECTED", "EXPIRED"].includes(
                        item.status,
                      ) && (
                        <button
                          onClick={() => cancel(item.id)}
                          title="撤单"
                          className="text-[#ae2012]"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
        <EmptyState icon={<ClipboardList />} text="当前没有订单记录" />
        )}
      </Card>
      {selected && <OrderDetailDialog item={selected} onClose={() => setSelected(null)} />}
    </PageFrame>
  );
}

function OrderDetailDialog({ item, onClose }: { item: any; onClose: () => void }) {
  const execution = item.execution;
  const trade = item.trade;
  return <div className="fixed inset-0 z-[80] flex justify-end bg-black/30" role="dialog" aria-modal="true" aria-label="订单详情"><aside className="h-full w-full max-w-xl overflow-y-auto bg-white p-6 shadow-2xl"><div className="mb-6 flex items-start justify-between"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-[#0f5238]">ORDER DETAIL</p><h2 className="mt-1 text-xl font-bold">{item.symbol} 订单详情</h2><p className="mt-1 text-sm text-[#52616b]">{item.side === "BUY" ? "买入" : "卖出"} · {statusLabel(item.status)}</p></div><button type="button" onClick={onClose} className="rounded-md px-3 py-1 text-xl hover:bg-[#f3f1eb]" aria-label="关闭">×</button></div><div className="space-y-5"><section><h3 className="mb-2 text-sm font-bold">订单标识</h3><dl className="grid grid-cols-2 gap-3 rounded-lg bg-[#f8f7f2] p-4 text-sm"><div><dt className="text-xs text-[#52616b]">券商订单号</dt><dd className="mt-1 font-mono">{item.broker_order_id || "暂未分配"}</dd></div><div><dt className="text-xs text-[#52616b]">客户端订单号</dt><dd className="mt-1 font-mono">{item.client_order_id || "—"}</dd></div><div><dt className="text-xs text-[#52616b]">委托价格</dt><dd className="mt-1 font-mono">{item.price == null ? "市价" : money(item.price)}</dd></div><div><dt className="text-xs text-[#52616b]">委托数量 / 已成交</dt><dd className="mt-1 font-mono">{item.quantity} / {item.filled_quantity} 股</dd></div></dl></section><section><h3 className="mb-2 text-sm font-bold">成交明细</h3>{item.fills?.length ? <div className="space-y-2 rounded-lg border border-[#e2ded4] p-4 text-sm">{item.fills.map((fill: any) => <div key={fill.id} className="flex justify-between"><span>{fill.created_at || fill.filled_at || "—"}</span><b>{money(fill.price)} · {fill.quantity} 股</b></div>)}</div> : <p className="rounded-lg bg-[#f8f7f2] p-4 text-sm text-[#52616b]">该订单暂无成交记录。</p>}</section><section><h3 className="mb-2 text-sm font-bold">交易归属</h3><div className="space-y-2 rounded-lg border border-[#e2ded4] p-4 text-sm"><p><span className="text-[#52616b]">ExecutionPlan：</span>{execution ? `#${execution.id} · ${executionTypeLabel(execution.execution_type)} · ${statusLabel(execution.status)}` : "未关联"}</p><p><span className="text-[#52616b]">TradePlan：</span>{execution?.trade_plan_id ? `#${execution.trade_plan_id}` : "未关联"}</p><p><span className="text-[#52616b]">Trade：</span>{trade ? `#${trade.id} · ${trade.symbol} ${trade.symbol_name || ""}` : "未关联"}</p></div></section></div></aside></div>;
}

function PositionsPage({
  onNavigate,
  onOpenTrade,
  accountId,
}: {
  onNavigate: (view: TradingView) => void;
  onOpenTrade: (tradeId: number) => void;
  accountId: number;
}) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<any>(null);
  const [riskAction, setRiskAction] = useState<any>(null);
  async function load() {
    try {
      const [overview, trades] = await Promise.all([request(accountPath("/api/trading/overview", accountId)), request(accountPath("/api/trades", accountId))]);
      setData({ ...overview, trades: trades.items || [] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "持仓读取失败");
    }
  }
  useEffect(() => {
    setData(null);
    setAction(null);
    setRiskAction(null);
    setError(null);
    load();
  }, [accountId]);
  return (
    <PageFrame>
      {error ? (
        <ErrorBox message={error} onRetry={load} />
      ) : !data ? (
        <Loading />
      ) : (
        <>
          <div className="mb-5 flex items-end justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-[#0f5238]">POSITION MONITOR</p><h1 className="mt-1 text-3xl font-bold">持仓</h1><p className="mt-1 text-sm text-[#52616b]">在 Trade 上下文中查看持仓、可卖数量与风险参考。</p></div>
            <button
              onClick={() => onNavigate("plan")}
              title="创建新交易"
              aria-label="创建新交易"
              className="inline-flex items-center gap-2 rounded-lg bg-[#0f5238] px-4 py-2.5 text-sm font-bold text-white"
            >
              <Plus className="h-4 w-4" />创建新交易
            </button>
          </div>
          <Card className="mb-4 grid grid-cols-2 gap-x-5 gap-y-2 bg-[#e7e8e9] px-4 py-3 text-sm sm:grid-cols-4">
            <CompactAccountMetric label="总资产" value={money(data.account.equity)} accent />
            <CompactAccountMetric label="持仓市值" value={money(data.account.market_value)} />
            <CompactAccountMetric label="可用现金" value={money(data.account.available_cash)} />
            <CompactAccountMetric label="总仓位" value={pct(data.account.total_exposure_pct)} />
          </Card>
          <Card className="overflow-hidden">
            <PositionTable positions={data.positions} trades={data.trades} onOpenTrade={onOpenTrade} onAction={setAction} onRisk={async (trade: any, position: any) => {
              try {
                const detail = await request(accountPath(`/api/trades/${trade.id}`, accountId));
                setRiskAction({ trade, position, legs: detail.item?.legs || [] });
              } catch (e) {
                setError(e instanceof Error ? e.message : "交易风险信息读取失败");
              }
            }} />
          </Card>
          {action && <ActionPlanDialog accountId={accountId} fullPage action={action} onClose={() => setAction(null)} onSaved={async () => { setAction(null); await load(); }} onError={setError} />}
          {riskAction && <RiskReferenceDialog accountId={accountId} tradeId={riskAction.trade.id} legs={riskAction.legs} current={riskAction.position.current_risk_reference_price} onClose={() => setRiskAction(null)} onSaved={async () => { setRiskAction(null); await load(); }} onError={setError} />}
        </>
      )}
    </PageFrame>
  );
}

function PositionTable({ positions, trades = [], onOpenTrade, onAction, onRisk }: { positions: any[]; trades?: any[]; onOpenTrade?: (tradeId: number) => void; onAction?: (action: any) => void; onRisk?: (trade: any, position: any) => void }) {
  const tradeBySymbol = new Map<string, any>(trades.map((trade: any) => [trade.symbol, trade]));
  return positions.length ? (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="bg-[#f3f4f5] text-xs uppercase tracking-wide text-[#404943]">
          <tr>
            {[
              "证券",
              "所属 Trade",
              "数量 / 可卖",
              "成本 / 现价",
              "市值",
              "盈亏",
              "风险参考",
              "操作",
            ].map((label) => (
              <th key={label} className="px-4 py-2.5">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {positions.map((item) => {
            const trade = tradeBySymbol.get(item.symbol);
            const canReduceOrClose = trade && ["ACTIVE", "CLOSING"].includes(trade.status);
            const canAdd = trade?.status === "ACTIVE";
            return <tr key={item.symbol} className="border-t border-[#dee2e6]">
              <td className="px-4 py-3">
                <b>{item.security_name}</b>
                <div className="text-xs text-[#52616b]">{item.symbol}</div>
              </td>
              <td className="px-4 py-3">{trade ? <><b>{trade.trade_type === "TREND" ? "趋势交易" : trade.trade_type === "REBOUND" ? "反弹 / 波段" : trade.trade_type === "FIXED_TARGET" ? "固定目标" : "自定义"}</b><div className="text-xs text-[#52616b]">{trade.status === "ACTIVE" ? "进行中" : trade.status}</div></> : <span className="text-[#52616b]">未关联 Trade</span>}</td>
              <td className="px-4 py-3">
                {item.quantity.toLocaleString()}
                <div className="text-xs text-[#52616b]">
                  {item.available_quantity.toLocaleString()}
                </div>
              </td>
              <td className="px-4 py-3">
                {item.average_cost.toFixed(2)}
                <div className="font-bold text-[#2d6a4f]">
                  {item.market_price.toFixed(2)}
                </div>
              </td>
              <td className="px-4 py-3">{money(item.market_value)}</td>
              <td
                className={`px-4 py-3 font-bold ${item.unrealized_pnl >= 0 ? "text-[#2d6a4f]" : "text-[#ae2012]"}`}
              >
                {money(item.unrealized_pnl)}
              </td>
              <td className="px-4 py-3 text-[#0f5238]">
                {item.current_risk_reference_price?.toFixed(2) || "未设置"}
              </td>
              <td className="px-4 py-3">
                {trade ? <div className="flex flex-wrap gap-2">{onOpenTrade && <button type="button" onClick={() => onOpenTrade(trade.id)} className="text-xs font-bold text-[#0f5238]">查看交易</button>}{canAdd && onAction && <button type="button" onClick={() => onAction({ tradeId: trade.id, symbol: trade.symbol, securityName: trade.symbol_name, type: "ADD" })} className="text-xs font-bold text-[#0f5238]">加仓</button>}{canReduceOrClose && onAction && <><button type="button" onClick={() => onAction({ tradeId: trade.id, symbol: trade.symbol, securityName: trade.symbol_name, type: "REDUCE" })} className="text-xs font-bold text-[#0f5238]">减仓</button><button type="button" onClick={() => onAction({ tradeId: trade.id, symbol: trade.symbol, securityName: trade.symbol_name, type: "CLOSE" })} className="text-xs font-bold text-[#ae2012]">清仓</button></>}{canReduceOrClose && onRisk && <button type="button" onClick={() => onRisk(trade, item)} className="text-xs font-bold text-[#0f5238]">调整风险</button>}</div> : <span className="text-xs text-[#52616b]">请先关联 Trade</span>}
              </td>
            </tr>
          })}
        </tbody>
      </table>
    </div>
  ) : (
    <EmptyState icon={<Wallet />} text="当前没有持仓记录" />
  );
}

function CompactAccountMetric({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2 sm:block">
      <span className="text-xs text-[#52616b]">{label}</span>
      <b className={`sm:mt-0.5 sm:block ${accent ? "text-[#0f5238]" : ""}`}>{value}</b>
    </div>
  );
}

export function SettingsPage({ accountId, onRefresh, onClose, mode = "trade" }: { accountId?: number; onRefresh: () => void; onClose: () => void; mode?: "trade" | "global" }) {
  const isGlobal = mode === "global";
  const [data, setData] = useState<any>(null);
  const [dataManagement, setDataManagement] = useState<any>(null);
  const [dataConfig, setDataConfig] = useState<any>(null);
  const [dataSources, setDataSources] = useState<any>(null);
  const [failedItems, setFailedItems] = useState<any[]>([]);
  const [failedTotal, setFailedTotal] = useState(0);
  const [failedPage, setFailedPage] = useState(1);
  const [failedQuery, setFailedQuery] = useState("");
  const [failedFilter, setFailedFilter] = useState("");
  const failedPageSize = 15;
  const [account, setAccount] = useState<any>({});
  const [risk, setRisk] = useState<any>({});
  const [brokerAccounts, setBrokerAccounts] = useState<any[]>([]);
  const [brokerForm, setBrokerForm] = useState<any>({ name: "", account_type: "SIMULATION", broker: "国投证券掘金", broker_account_id: "", broker_strategy_id: "", broker_node_url: "http://192.168.20.109:18731", broker_gm_token: "" });
  const [brokerDialogOpen, setBrokerDialogOpen] = useState(false);
  const [editingBrokerId, setEditingBrokerId] = useState<number | null>(null);
  const [testingBrokerId, setTestingBrokerId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [settingsSection, setSettingsSection] = useState<"account" | "risk" | "data-management">("account");
  const [dataSection, setDataSection] = useState<"overview" | "schedule" | "repair" | "tasks">("overview");
  async function load() {
    try {
      const [result, broker, management, sources, brokerAccountResult, riskResult] = await Promise.all([
        isGlobal ? Promise.resolve({}) : request(accountPath("/api/trading/account", accountId as number)),
        !isGlobal ? request(accountPath("/api/trading/broker", accountId as number)) : Promise.resolve(null),
        isGlobal ? request("/api/screening/data-management") : Promise.resolve(null),
        isGlobal ? request("/api/screening/data-management/sources") : Promise.resolve(null),
        request("/api/trading/broker-accounts"),
        !isGlobal ? request(accountPath("/api/trading/risk-profile", accountId as number)) : Promise.resolve(null),
      ]);
      setData({ ...result, broker });
      setAccount(result.account || result);
      setRisk(riskResult?.risk_profile || result.risk_profile || {});
      if (brokerAccountResult) setBrokerAccounts(brokerAccountResult.items || []);
      if (management) { setDataManagement(management); setDataConfig(management.config.config); setDataSources(sources); }
    } catch (e) {
      setError(e instanceof Error ? e.message : "交易设置读取失败");
    }
  }
  async function refreshDataManagement() {
    const management = await request("/api/screening/data-management");
    setDataManagement(management);
    setDataConfig(management.config.config);
  }
  async function saveDataConfig() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await request("/api/screening/data-management/config", {
        method: "PATCH",
        body: JSON.stringify({ config: dataConfig }),
      });
      await refreshDataManagement();
      setNotice("数据管理配置已保存");
    } catch (e) {
      setError(e instanceof Error ? e.message : "数据管理配置保存失败");
    } finally {
      setBusy(false);
    }
  }
  async function triggerDataSync() {
    setBusy(true);
    setError(null);
    try {
      await request("/api/screening/data-sync/async", { method: "POST" });
      await refreshDataManagement();
      setNotice("行情更新任务已启动");
    } catch (e) {
      setError(e instanceof Error ? e.message : "行情更新任务启动失败");
    } finally {
      setBusy(false);
    }
  }
  async function loadFailedItems(page = failedPage, search = failedFilter) {
    const query = search ? `&search=${encodeURIComponent(search)}` : "";
    const result = await request(`/api/screening/data-management/failed?page=${page}&page_size=${failedPageSize}${query}`);
    setFailedItems(result.items || []);
    setFailedTotal(result.total || 0);
  }
  async function retryFailedItems() {
    const latestDate = failedItems[0]?.trade_date;
    if (!latestDate) return;
    setBusy(true);
    try {
      await request("/api/screening/data-management/retry-failed", { method: "POST", body: JSON.stringify({ trade_date: latestDate, asset_type: "all" }) });
      await refreshDataManagement();
      await loadFailedItems(1);
      setFailedPage(1);
      setNotice(`${latestDate} 的未完成分钟线重试任务已启动`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "失败项重试启动失败");
    } finally {
      setBusy(false);
    }
  }
  function searchFailedItems(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFailedFilter(failedQuery.trim());
    setFailedPage(1);
  }
  async function cancelCurrentTask() {
    const taskId = dataManagement?.live_task?.task_id;
    if (!taskId) return;
    try {
      await request(`/api/screening/data-management/tasks/${taskId}/cancel`, { method: "POST" });
      await refreshDataManagement();
      setNotice("已请求停止当前更新任务");
    } catch (e) {
      setError(e instanceof Error ? e.message : "停止任务失败");
    }
  }
  useEffect(() => {
    load();
  }, [accountId, isGlobal]);
  async function save() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await request(accountPath("/api/trading/account", accountId as number), {
        method: "PATCH",
        body: JSON.stringify(account),
      });
      await request(accountPath("/api/trading/risk-profile", accountId as number), {
        method: "PATCH",
        body: JSON.stringify(risk),
      });
      await load();
      onRefresh();
      setNotice("交易设置已保存");
    } catch (e) {
      setError(e instanceof Error ? e.message : "交易设置保存失败");
    } finally {
      setBusy(false);
    }
  }
  async function testBrokerConnection() {
    setBusy(true);
    setError(null);
    try {
      const broker = await request(accountPath("/api/trading/broker", accountId as number));
      setData((current: any) => ({ ...current, broker }));
      setNotice(brokerConnectionHealthy(broker?.connection) ? "券商连接成功" : (broker?.connection?.message || "券商尚未连接"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "券商连接测试失败");
    } finally {
      setBusy(false);
    }
  }
  async function createBrokerAccount() {
    setBusy(true); setError(null);
    try {
      await request("/api/trading/broker-accounts", { method: "POST", body: JSON.stringify(brokerForm) });
      const result = await request("/api/trading/broker-accounts");
      setBrokerAccounts(result.items || []);
      setBrokerDialogOpen(false);
      setNotice("账户已添加");
    } catch (e) {
      setError(e instanceof Error ? e.message : "账户添加失败");
    } finally { setBusy(false); }
  }
  async function saveBrokerAccount() {
    setBusy(true); setError(null);
    try {
      const url = editingBrokerId ? `/api/trading/broker-accounts/${editingBrokerId}` : "/api/trading/broker-accounts";
      await request(url, { method: editingBrokerId ? "PUT" : "POST", body: JSON.stringify(brokerForm) });
      const result = await request("/api/trading/broker-accounts");
      setBrokerAccounts(result.items || []);
      setBrokerDialogOpen(false); setEditingBrokerId(null);
      setNotice(editingBrokerId ? "账户已更新" : "账户已添加");
    } catch (e) { setError(e instanceof Error ? e.message : "账户保存失败"); }
    finally { setBusy(false); }
  }
  function editBrokerProfile(item: any) {
    setBrokerForm({ name: item.name, account_type: item.account_type, broker: item.broker, broker_account_id: item.broker_account_id, broker_strategy_id: item.broker_strategy_id, broker_node_url: item.broker_node_url, broker_gm_token: item.broker_gm_token });
    setEditingBrokerId(item.id); setBrokerDialogOpen(true);
  }
  async function testBrokerProfile(id: number) {
    setBusy(true); setTestingBrokerId(id); setError(null);
    try {
      const result = await request(`/api/trading/broker-accounts/${id}/test`, { method: "POST" });
      setNotice(brokerConnectionHealthy(result.connection) ? "券商连接成功" : (result.connection?.message || "券商尚未连接"));
    } catch (e) { setError(e instanceof Error ? e.message : "连接测试失败"); }
    finally { setBusy(false); setTestingBrokerId(null); }
  }
  async function deleteBrokerProfile(id: number) {
    if (!window.confirm("确定删除这个券商账户吗？")) return;
    setBusy(true); setError(null);
    try {
      await request(`/api/trading/broker-accounts/${id}`, { method: "DELETE" });
      const result = await request("/api/trading/broker-accounts");
      setBrokerAccounts(result.items || []);
      setNotice("账户已删除");
    } catch (e) { setError(e instanceof Error ? e.message : "账户删除失败"); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (!isGlobal || !dataManagement?.live_task || !["running", "RUNNING"].includes(dataManagement.live_task.status)) return;
    const timer = window.setInterval(() => { void refreshDataManagement(); }, 2000);
    return () => window.clearInterval(timer);
  }, [isGlobal, dataManagement?.live_task?.status]);
  useEffect(() => {
    if (isGlobal && settingsSection === "data-management" && dataSection === "repair") void loadFailedItems(failedPage, failedFilter);
  }, [isGlobal, settingsSection, dataSection, failedPage, failedFilter]);
  if (error)
    return (
      <SettingsDialog onClose={onClose} modal={isGlobal}>
        <ErrorBox message={error} onRetry={load} />
      </SettingsDialog>
    );
  if (!data)
    return (
      <SettingsDialog onClose={onClose} modal={isGlobal}>
        <Loading />
      </SettingsDialog>
    );
  if (!isGlobal)
    return (
      <SettingsDialog onClose={onClose}>
        <CurrentAccountSettings risk={risk} setRisk={setRisk} save={save} accountId={accountId} brokerAccounts={brokerAccounts} />
        {notice && <div className="fixed bottom-5 right-5 z-[80] inline-flex items-center gap-2 rounded-lg bg-[#0f5238] px-4 py-3 text-sm font-bold text-white shadow-lg" role="status"><CheckCircle2 className="h-4 w-4" />{notice}</div>}
      </SettingsDialog>
    );
  return (
    <SettingsDialog onClose={onClose} modal={isGlobal}>
      <div className={isGlobal ? "grid items-start gap-5 lg:grid-cols-[210px_minmax(0,1fr)]" : "space-y-6"}>
        {isGlobal && <nav className="sticky top-0 h-fit self-start space-y-2" aria-label="系统配置分类">
          <button type="button" onClick={() => setSettingsSection("account")} className={`flex w-full items-center gap-3 rounded-lg px-4 py-3 text-left font-bold ${settingsSection === "account" ? "bg-[#b1f0ce] text-[#0e5138]" : "text-[#404943] hover:bg-[#edeeef]"}`}>
            <Wallet className="h-5 w-5" />
            账号设置
          </button>
          <button type="button" onClick={() => { setSettingsSection("data-management"); setDataSection("overview"); }} className={`flex w-full items-center gap-3 rounded-lg px-4 py-3 text-left font-bold ${settingsSection === "data-management" ? "bg-[#b1f0ce] text-[#0e5138]" : "text-[#404943] hover:bg-[#edeeef]"}`}>
            <Database className="h-5 w-5" />
            数据管理
          </button>
          {isGlobal && settingsSection === "data-management" && (
            <div className="ml-4 space-y-1 border-l border-[#c8d8ce] pl-3" aria-label="数据管理分类">
              {([
                ["overview", "数据概览"],
                ["schedule", "更新计划"],
                ["repair", "失败修复"],
                ["tasks", "任务与日志"],
              ] as Array<[typeof dataSection, string]>).map(([key, label]) => (
                <button key={key} type="button" onClick={() => setDataSection(key)} className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm ${dataSection === key ? "bg-[#e4f7eb] font-bold text-[#0e5138]" : "text-[#52616b] hover:bg-[#edeeef]"}`}>
                  <ChevronRight className={`h-3.5 w-3.5 ${dataSection === key ? "text-[#0f5238]" : "text-[#9aa59d]"}`} />
                  {label}
                </button>
              ))}
            </div>
          )}
        </nav>}
        <div className="space-y-6">
          {isGlobal && settingsSection === "account" && <BrokerAccountsPanel brokerAccounts={brokerAccounts} brokerForm={brokerForm} setBrokerForm={setBrokerForm} setBrokerDialogOpen={setBrokerDialogOpen} busy={busy} testingBrokerId={testingBrokerId} testBrokerProfile={testBrokerProfile} deleteBrokerProfile={deleteBrokerProfile} editBrokerProfile={editBrokerProfile} />}
          {!isGlobal && <Card id="account" className="rounded-xl border border-stone-200/70 bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center justify-between border-b border-stone-100 pb-4">
              <div className="flex items-center gap-3">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#a1f4c8] text-[#005236]">
                  <UserRound className="h-4 w-4" />
                </span>
                <div>
                  <div className="flex items-center gap-2"><h2 className="text-base font-bold text-stone-900">交易账户设置</h2><span className="inline-flex items-center gap-1 rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-[#2d5a43]"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />{account.status === "ACTIVE" ? "正常可用" : statusLabel(account.status)}</span></div>
                  <p className="mt-0.5 text-xs text-[#52616b]">主规划账户与资产配置</p>
                </div>
              </div>
              <button
                onClick={save}
                disabled={busy}
                title={busy ? "正在保存交易设置" : "保存交易设置"}
                aria-label={busy ? "正在保存交易设置" : "保存交易设置"}
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-[#354860] text-white transition-colors hover:bg-[#506988] disabled:opacity-50"
              >
                {busy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              </button>
            </div>
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
              <div className="grid grid-cols-2 gap-3.5 rounded-lg border border-stone-200/60 bg-stone-50/80 p-3.5 lg:col-span-5">
              {editField("账户名称", "name", account, setAccount, "text")}
              {selectField("账户类型", "account_type", account, setAccount, [["PLANNING", "规划账户"], ["SIMULATION", "模拟账户"], ["LIVE", "实盘账户"]])}
              {selectField("账户状态", "status", account, setAccount, [["ACTIVE", "可用"], ["DISCONNECTED", "已断开"], ["LOCKED", "已锁定"]])}
              {editField("币种", "currency", account, setAccount, "text")}
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 lg:col-span-7">
                {[['账户净资产 (NAV)', 'equity'], ['总现金储备', 'cash'], ['可用资金 (可开仓)', 'available_cash']].map(([label, key], index) => <div key={key} className="flex flex-col justify-between rounded-lg border border-stone-200/70 bg-stone-50/70 p-3.5"><div className="flex items-center justify-between"><span className="text-[11px] font-medium text-stone-500">{label}</span><span className={`rounded px-1 text-[10px] font-mono ${index === 1 ? "bg-blue-100 text-blue-700" : "bg-emerald-100 text-emerald-700"}`}>{index === 1 ? "充裕" : "100%"}</span></div><div className="my-2"><div className={`text-xl font-bold tracking-tight ${index === 2 ? "text-[#2d5a43]" : "text-stone-900"}`}>{money(account[key])}</div><div className="mt-0.5 text-[11px] text-stone-500">折合：<span className="font-medium text-stone-700">{typeof account[key] === "number" ? `${(account[key] / 10000).toFixed(2)} 万元` : "—"}</span></div></div><div className="h-1 w-full overflow-hidden rounded-full bg-stone-200"><div className={`h-full w-full rounded-full ${index === 1 ? "bg-blue-600" : "bg-emerald-500"}`} /></div></div>)}
              </div>
            </div>
          </Card>}
          {!isGlobal && <Card id="broker-accounts" className="rounded-xl border border-stone-200/70 bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <div><div className="flex items-center gap-2"><h2 className="text-base font-bold text-stone-900">券商网关与交易通道</h2><span className="rounded-full bg-stone-100 px-2 py-0.5 text-xs font-mono text-stone-600">已挂载 {brokerAccounts.length} 个实例</span></div><p className="mt-1 text-xs text-[#52616b]">管理仿真策略通道与券商交易连接。</p></div>
              <button type="button" onClick={() => { setBrokerForm({ name: "", account_type: "SIMULATION", broker: "国投证券掘金", broker_account_id: "", broker_strategy_id: "", broker_node_url: "http://192.168.20.109:18731", broker_gm_token: "" }); setBrokerDialogOpen(true); }} className="inline-flex items-center gap-1 rounded-lg bg-[#2d5a43] px-3.5 py-1.5 text-xs font-medium text-white shadow-sm"><Plus className="h-4 w-4" />添加券商通道</button>
            </div>
            {brokerAccounts.length === 0 ? <div className="rounded-lg bg-[#f3f4f5] px-4 py-6 text-center text-sm text-[#52616b]">暂未添加券商账户</div> : <div className="mt-4 space-y-3">{brokerAccounts.map((item) => <div key={item.id} className="rounded-lg border border-stone-200 bg-white p-4 transition-all hover:border-[#3a6d50]/40 hover:shadow-sm"><div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center"><div className="flex-1 space-y-2"><div className="flex flex-wrap items-center gap-2.5"><span className="text-sm font-bold text-stone-900">{item.name}（{item.broker}）</span><span className="inline-flex items-center rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">{item.account_type === "SIMULATION" ? "仿真环境" : "实盘环境"}</span><span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-mono ${item.status === "ACTIVE" ? "bg-emerald-50/60 text-emerald-600" : "bg-stone-100 text-stone-500"}`}><span className={`h-1.5 w-1.5 rounded-full ${item.status === "ACTIVE" ? "bg-emerald-500" : "bg-stone-400"}`} />{item.status === "ACTIVE" ? "已配置" : item.status}</span></div><div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs md:grid-cols-6"><div><span className="block text-[11px] text-stone-400">账户 ID</span><span className="block max-w-[120px] truncate font-mono font-medium text-stone-800" title="账户 ID 已隐藏">{maskAccountIdentifier(item.broker_account_id)}</span></div><div><span className="block text-[11px] text-stone-400">策略 ID</span><span className="block max-w-[120px] truncate font-mono font-medium text-stone-800" title="策略 ID 已隐藏">{maskAccountIdentifier(item.broker_strategy_id)}</span></div><div><span className="block text-[11px] text-stone-400">Token</span><span className="block max-w-[130px] truncate font-mono font-medium text-stone-800" title="Token 已隐藏">{maskToken(item.broker_gm_token)}</span></div><div><span className="block text-[11px] text-stone-400">内部实例别名</span><span className="rounded bg-stone-100 px-1.5 py-0.5 font-mono text-[11px] text-stone-700">{item.broker_account_key}</span></div><div className="col-span-2"><span className="block text-[11px] text-stone-400">网关 RPC 地址</span><span className="block max-w-[220px] truncate font-mono text-stone-700" title={item.broker_node_url}>{item.broker_node_url}</span></div></div></div><div className="flex shrink-0 items-center gap-2 border-t border-stone-100 pt-2 lg:border-t-0 lg:pt-0"><button type="button" onClick={() => void testBrokerProfile(item.id)} disabled={busy} className="inline-flex items-center gap-1.5 rounded border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs font-medium text-stone-700 hover:bg-stone-100 disabled:opacity-50"><Zap className={`h-3.5 w-3.5 text-emerald-600 ${testingBrokerId === item.id ? "animate-spin" : ""}`} />{testingBrokerId === item.id ? "测试中" : "测试"}</button><button type="button" onClick={() => void deleteBrokerProfile(item.id)} disabled={busy} className="rounded border border-red-200/80 px-2.5 py-1.5 text-xs text-red-600 hover:bg-red-50 disabled:opacity-50">删除</button></div></div></div>)}</div>}
          </Card>}
          {!isGlobal && <Card id="risk" className="rounded-xl border border-stone-200/70 bg-white p-5 shadow-sm">
            <div className="mb-1 flex items-center gap-2">
              <Shield className="h-5 w-5 text-[#8d4d4e]" />
              <h2 className="text-base font-bold text-stone-900">量化风控规则与前置拦截</h2>
            </div>
            <p className="mb-3 text-xs text-[#52616b]">
              所有报单将在本地与网关双重校验，超出阈值的委托将被拦截。
            </p>
            <div className="grid grid-cols-1 gap-3.5 md:grid-cols-3 xl:grid-cols-5">
              <PercentageField label="默认单笔风险比例" fieldKey="default_trade_risk_pct" state={risk} setState={setRisk} />
              <PercentageField label="最大单笔允许风险" fieldKey="max_trade_risk_pct" state={risk} setState={setRisk} />
              <PercentageField label="单一个股最大仓位比例" fieldKey="max_single_position_pct" state={risk} setState={setRisk} />
              <PercentageField label="最大总仓位比例" fieldKey="max_total_exposure_pct" state={risk} setState={setRisk} />
              <div className="flex flex-col justify-between rounded-lg border border-stone-200/80 bg-stone-50/80 p-3"><div><div className="flex items-center justify-between"><span className="text-xs font-semibold text-[#2d5a43]">最低现金留存</span><span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-mono text-[#2d5a43]">流动性</span></div><p className="mt-1 text-[11px] text-stone-400">根据账户最大总仓位自动计算的现金安全垫</p></div><div className="mt-3"><div className="w-full rounded border border-stone-200 bg-white px-2.5 py-1 font-mono text-sm font-bold text-[#2d5a43]">{typeof risk.max_total_exposure_pct === "number" ? `${((1 - risk.max_total_exposure_pct) * 100).toFixed(1)}%` : "—"}</div><div className="mt-1 text-[10px] font-mono text-stone-400">可用现金安全垫</div></div></div>
            </div>
          </Card>}
          {isGlobal && settingsSection === "data-management" && <Card id="data-management" className={dataSection === "overview" ? "p-5" : "bg-transparent p-0 shadow-none"}>
            {dataSection === "overview" && <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <Database className="h-5 w-5 text-[#0f5238]" />
                <div>
                  <h2 className="text-lg font-bold">数据管理</h2>
                  <p className="text-xs text-[#52616b]">管理行情更新计划、查看数据状态并手动启动更新。</p>
                </div>
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={() => void refreshDataManagement()} className="inline-flex items-center gap-1 rounded-lg border border-[#c4c8bc] bg-white px-3 py-2 text-xs font-bold text-[#354860]">
                  <RefreshCw className="h-3.5 w-3.5" />刷新状态
                </button>
                <button type="button" onClick={() => void triggerDataSync()} disabled={busy || ["running", "RUNNING"].includes(dataManagement?.live_task?.status)} className="inline-flex items-center gap-1 rounded-lg bg-[#0f5238] px-3 py-2 text-xs font-bold text-white disabled:opacity-50">
                  <Play className="h-3.5 w-3.5" />立即更新
                </button>
                {["running", "RUNNING"].includes(dataManagement?.live_task?.status) && <button type="button" onClick={() => void cancelCurrentTask()} className="inline-flex items-center gap-1 rounded-lg border border-[#a23b3b] bg-white px-3 py-2 text-xs font-bold text-[#a23b3b]"><CirclePause className="h-3.5 w-3.5" />停止任务</button>}
              </div>
            </div>}
            {dataSection === "overview" && <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <DataStatus label="正式日线至" value={dataManagement?.freshness?.official_daily_date || "未知"} />
              <DataStatus label="分钟线至" value={dataManagement?.freshness?.min_bar_time || "未知"} />
              <DataStatus label="最近任务" value={dataManagement?.live_task?.status === "running" ? `${dataManagement.live_task.progress || 0}% 更新中` : "当前无运行任务"} />
              <DataStatus label="配置版本" value={`v${dataManagement?.config?.version ?? 0}`} />
            </div>}
            {dataSection === "overview" && <div className="mt-4 rounded-lg border border-[#dee2e6] bg-white p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div><h3 className="font-bold">数据质量</h3><p className="text-xs text-[#52616b]">基于当前数据库全量记录检查覆盖情况。</p></div>
                <span className={`rounded-full px-3 py-1 text-xs font-bold ${dataManagement?.quality?.status === "READY" ? "bg-[#d9f4e6] text-[#0e5138]" : dataManagement?.quality?.status === "BLOCKING" ? "bg-[#ffdad6] text-[#93000a]" : "bg-[#fff1df] text-[#9a4d00]"}`}>{dataManagement?.quality?.status === "READY" ? "可用" : dataManagement?.quality?.status === "BLOCKING" ? "存在阻断问题" : "需要关注"}</span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <DataStatus label="证券主数据" value={`股票 ${dataManagement?.quality?.assets?.stock ?? 0} · ETF ${dataManagement?.quality?.assets?.etf ?? 0}`} />
                <DataStatus label="最新日线记录" value={`${dataManagement?.quality?.daily?.trade_date || "未知"} · ${dataManagement?.quality?.daily?.stock_rows ?? 0} 条股票`} />
                <DataStatus label="最新分钟线" value={`${dataManagement?.quality?.minute?.trade_date || "未知"} · ${dataManagement?.quality?.minute?.assets ?? 0} 个资产`} />
                <DataStatus label="同步失败记录" value={String(dataManagement?.quality?.sync_logs?.failed ?? 0)} />
              </div>
              {(dataManagement?.quality?.issues || []).length > 0 && <div className="mt-3 space-y-1.5">{dataManagement.quality.issues.map((issue: any) => <div key={issue.code} className="rounded-md bg-[#fff8ed] px-3 py-2 text-xs text-[#8a4b08]"><span className="font-bold">{issue.severity === "BLOCKING" ? "阻断" : "关注"}</span> · {issue.message}</div>)}</div>}
            </div>}
            {dataSection === "overview" && <div className="mt-4 rounded-lg border border-[#dee2e2] bg-white p-4">
              <div className="mb-3 flex items-center justify-between"><div><h3 className="font-bold">数据源状态</h3><p className="text-xs text-[#52616b]">健康检查使用真实接口，不采用缓存结果。</p></div><button type="button" onClick={() => void load()} className="rounded-lg border border-[#c4c8bc] px-3 py-2 text-xs font-bold">重新检查</button></div>
              <div className="grid gap-3 sm:grid-cols-2">{["tushare", "akshare"].map((name) => <div key={name} className="flex items-center justify-between rounded-lg bg-[#f3f4f5] px-3 py-3"><div><div className="font-bold">{name === "tushare" ? "TuShare" : "AkShare"}</div><div className="mt-1 text-xs text-[#52616b]">{dataSources?.[name]?.message || "未检查"}</div></div><span className={`rounded-full px-2.5 py-1 text-xs font-bold ${dataSources?.[name]?.status === "PASS" ? "bg-[#d9f4e6] text-[#0e5138]" : dataSources?.[name]?.status === "FAIL" ? "bg-[#ffdad6] text-[#93000a]" : "bg-[#fff1df] text-[#9a4d00]"}`}>{dataSources?.[name]?.status || "UNKNOWN"}</span></div>)}</div>
            </div>}
            {dataSection === "repair" && <div className="mt-4 rounded-lg border border-[#dee2e2] bg-white p-4">
              <div className="mb-3 flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-bold">未完成分钟线</h3><p className="text-xs text-[#52616b]">每页显示 15 条。可按证券代码或名称搜索；重试会跳过已完整数据。</p></div><button type="button" onClick={() => void retryFailedItems()} disabled={busy || !failedItems.length} className="rounded-lg bg-[#354860] px-3 py-2 text-xs font-bold text-white disabled:opacity-50">重试最新交易日未完成项</button></div>
              <form onSubmit={searchFailedItems} className="mb-3 flex max-w-md gap-2"><input value={failedQuery} onChange={(event) => setFailedQuery(event.target.value)} placeholder="搜索证券代码或名称" className="min-w-0 flex-1 rounded-lg border border-[#c4c8bc] bg-white px-3 py-2 text-sm outline-none focus:border-[#0f5238]" /><button type="submit" className="rounded-lg border border-[#c4c8bc] bg-white px-3 py-2 text-xs font-bold text-[#354860]">搜索</button>{failedFilter && <button type="button" onClick={() => { setFailedQuery(""); setFailedFilter(""); setFailedPage(1); }} className="rounded-lg px-2 py-2 text-xs text-[#52616b]">清除</button>}</form>
              <div className="overflow-x-auto rounded-lg border border-[#edf0ef]"><table className="w-full min-w-[680px] table-fixed text-left text-xs"><thead className="bg-[#f3f4f5] text-[#52616b]"><tr><th className="w-[100px] px-3 py-2">交易日</th><th className="w-[145px] px-3 py-2">证券</th><th className="w-[65px] px-3 py-2">类型</th><th className="w-[190px] px-3 py-2">完成进度</th><th className="w-[95px] px-3 py-2">处理状态</th><th className="w-[185px] px-3 py-2">说明</th></tr></thead><tbody>{failedItems.map((item) => <tr key={`${item.trade_date}-${item.asset_code}`} className="border-t border-[#edf0ef]"><td className="truncate px-3 py-2">{item.trade_date}</td><td className="truncate px-3 py-2 font-bold" title={`${item.asset_code} ${item.name || ""}`}>{item.asset_code} {item.name || ""}</td><td className="truncate px-3 py-2">{item.asset_type === "stock" ? "股票" : "ETF"}</td><td className="truncate px-3 py-2">已完成 {item.actual_slots} 个 30 分钟时段，共 {item.expected_slots} 个</td><td className="truncate px-3 py-2 font-bold">{minuteSyncStatusLabel(item.status)}</td><td className="truncate px-3 py-2 text-[#a23b3b]" title={item.last_error || ""}>{item.last_error || "需要补齐缺失时段"}</td></tr>)}</tbody></table>{!failedItems.length && <div className="px-4 py-6 text-center text-xs text-[#7a827c]">当前没有需要修复的数据</div>}</div>
              {failedTotal > 0 && <div className="mt-3 flex items-center justify-between text-xs text-[#52616b]"><span>共 {failedTotal} 条记录，第 {failedPage} / {Math.ceil(failedTotal / failedPageSize)} 页</span><div className="flex gap-2"><button type="button" disabled={failedPage <= 1} onClick={() => setFailedPage((page) => page - 1)} className="rounded-md border border-[#c4c8bc] px-3 py-1.5 disabled:opacity-40">上一页</button><button type="button" disabled={failedPage >= Math.ceil(failedTotal / failedPageSize)} onClick={() => setFailedPage((page) => page + 1)} className="rounded-md border border-[#c4c8bc] px-3 py-1.5 disabled:opacity-40">下一页</button></div></div>}
            </div>}
            {dataSection === "schedule" && dataConfig && <>
              <div className="mt-5 border-t border-[#dee2e6] pt-4">
                <div className="mb-3 flex items-center justify-between">
                  <div><h3 className="font-bold">更新计划</h3><p className="text-xs text-[#52616b]">设置系统什么时候自动获取行情数据。修改后点击“保存计划”才会生效。</p></div>
                  <button type="button" onClick={() => void saveDataConfig()} disabled={busy} className="inline-flex items-center gap-1 rounded-lg bg-[#354860] px-3 py-2 text-xs font-bold text-white disabled:opacity-50"><Save className="h-3.5 w-3.5" />保存计划</button>
                </div>
                <div className="space-y-4">
                  <SettingsGroup title="自动更新总开关" description="关闭后，系统不会按下面的计划自动更新；手动点击“立即更新”仍可执行。">
                    <ToggleField label="按计划自动更新行情数据" fieldKey="enabled" state={dataConfig} setState={setDataConfig} />
                  </SettingsGroup>
                  <SettingsGroup title="盘中行情更新" description="交易时间内获取 30 分钟行情。你可以分别选择股票和 ETF，并设置获取频率。">
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      <ToggleField label="启用盘中 30 分钟行情更新" fieldKey="intraday_enabled" state={dataConfig} setState={setDataConfig} />
                      <ToggleField label="更新股票 30 分钟数据" fieldKey="stock_30m_enabled" state={dataConfig} setState={setDataConfig} />
                      <ToggleField label="更新 ETF 30 分钟数据" fieldKey="etf_30m_enabled" state={dataConfig} setState={setDataConfig} />
                      {editField("每隔多少分钟更新", "intraday_interval_minutes", dataConfig, setDataConfig)}
                      {editField("开始获取时间", "intraday_start_time", dataConfig, setDataConfig, "time")}
                      {editField("停止获取时间", "intraday_end_time", dataConfig, setDataConfig, "time")}
                    </div>
                  </SettingsGroup>
                  <SettingsGroup title="盘后日线更新" description="收盘后获取当天的日线和相关指标，作为第二天分析使用。">
                    <ToggleField label="每天收盘后自动更新日线" fieldKey="daily_enabled" state={dataConfig} setState={setDataConfig} />
                    <p className="mt-2 text-xs text-[#7a827c]">计划执行时间：{(dataConfig.daily_run_times || []).join("、")}</p>
                  </SettingsGroup>
                  <SettingsGroup title="日志保留" description="控制更新过程中的记录保留多久，避免失败日志无限占用空间。">
                    <div className="grid gap-3 sm:grid-cols-2">
                      {editField("最多保留多少天", "sync_log_retention_days", dataConfig, setDataConfig)}
                      {editField("最多保留多少条", "sync_log_max_rows", dataConfig, setDataConfig)}
                    </div>
                  </SettingsGroup>
                </div>
                <p className="mt-4 text-xs text-[#7a827c]">当前配置版本 v{dataManagement?.config?.version ?? 0}。</p>
              </div>
            </>}
            {dataSection === "tasks" && <div className="mt-5 border-t border-[#dee2e6] pt-4">
              <div className="mb-2 flex items-center justify-between"><h3 className="font-bold">最近更新记录</h3><span className="text-xs text-[#52616b]">保留最近 30 条</span></div>
              <div className="overflow-x-auto rounded-lg border border-[#dee2e6]">
                <table className="w-full min-w-[620px] text-left text-xs"><thead className="bg-[#f3f4f5] text-[#52616b]"><tr><th className="px-3 py-2">时间</th><th className="px-3 py-2">类型</th><th className="px-3 py-2">日期</th><th className="px-3 py-2">状态</th><th className="px-3 py-2">说明</th></tr></thead><tbody>{(dataManagement?.sync_logs || []).slice(0, 8).map((item: any) => <tr key={item.id} className="border-t border-[#edf0ef]"><td className="px-3 py-2">{String(item.created_at || "").replace("T", " ").slice(0, 19)}</td><td className="px-3 py-2 font-bold">{item.sync_type}</td><td className="px-3 py-2">{item.trade_date}</td><td className={`px-3 py-2 font-bold ${item.status === "PASS" ? "text-[#0f7a4f]" : "text-[#a23b3b]"}`}>{item.status}</td><td className="max-w-[360px] truncate px-3 py-2 text-[#52616b]" title={item.message || ""}>{item.message || "—"}</td></tr>)}</tbody></table>
                {(dataManagement?.sync_logs || []).length === 0 && <div className="px-4 py-6 text-center text-xs text-[#7a827c]">暂无更新记录</div>}
              </div>
            </div>}
            {dataSection === "tasks" && <div className="mt-5 border-t border-[#dee2e6] pt-4">
              <div className="mb-2 flex items-center justify-between"><h3 className="font-bold">任务历史</h3><span className="text-xs text-[#52616b]">已持久化记录</span></div>
              <div className="overflow-x-auto rounded-lg border border-[#dee2e6]">
                <table className="w-full min-w-[620px] text-left text-xs"><thead className="bg-[#f3f4f5] text-[#52616b]"><tr><th className="px-3 py-2">创建时间</th><th className="px-3 py-2">任务</th><th className="px-3 py-2">状态</th><th className="px-3 py-2">进度</th><th className="px-3 py-2">结果</th></tr></thead><tbody>{(dataManagement?.tasks || []).slice(0, 8).map((item: any) => <tr key={item.task_id} className="border-t border-[#edf0ef]"><td className="px-3 py-2">{String(item.created_at || "").replace("T", " ").slice(0, 19)}</td><td className="px-3 py-2 font-bold">{item.task_type === "market_data" ? "行情数据更新" : item.task_type}</td><td className={`px-3 py-2 font-bold ${item.status === "SUCCESS" ? "text-[#0f7a4f]" : item.status === "FAILED" ? "text-[#a23b3b]" : "text-[#9a6500]"}`}>{item.status}</td><td className="px-3 py-2">{item.progress}%</td><td className="max-w-[300px] truncate px-3 py-2 text-[#52616b]" title={item.error_message || item.stage_message}>{item.error_message || item.stage_message || "—"}</td></tr>)}</tbody></table>
                {(dataManagement?.tasks || []).length === 0 && <div className="px-4 py-6 text-center text-xs text-[#7a827c]">暂无任务记录</div>}
              </div>
            </div>}
          </Card>}
      </div>
      </div>
      {brokerDialogOpen && <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/35 p-4" role="dialog" aria-modal="true" aria-label="添加券商账户"><div className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-2xl"><div className="mb-5 flex items-center justify-between"><div><h2 className="text-xl font-bold">添加券商账户</h2><p className="mt-1 text-xs text-[#52616b]">填写账户连接信息后保存。</p></div><button type="button" onClick={() => setBrokerDialogOpen(false)} className="rounded-lg p-2 text-xl text-[#52616b] hover:bg-[#edf0f3]">×</button></div><div className="grid gap-3 sm:grid-cols-2">{editField("账户名称", "name", brokerForm, setBrokerForm, "text")}{selectField("账户类型", "account_type", brokerForm, setBrokerForm, [["SIMULATION", "仿真账户"], ["LIVE", "实盘账户"]])}{editField("券商", "broker", brokerForm, setBrokerForm, "text")}{editField("账户 ID", "broker_account_id", brokerForm, setBrokerForm, "text")}{editField("策略 ID", "broker_strategy_id", brokerForm, setBrokerForm, "text")}{editField("Broker Node 地址", "broker_node_url", brokerForm, setBrokerForm, "url")}{editField("Token", "broker_gm_token", brokerForm, setBrokerForm, "text")}</div><div className="mt-6 flex justify-end gap-2"><button type="button" onClick={() => setBrokerDialogOpen(false)} className="rounded-lg border border-[#c4c8bc] px-4 py-2 text-sm font-bold text-[#52616b]">取消</button><button type="button" onClick={() => void createBrokerAccount()} disabled={busy} className="rounded-lg bg-[#354860] px-4 py-2 text-sm font-bold text-white disabled:opacity-50">保存账户</button></div></div></div>}
      {notice && (
        <div className="fixed bottom-5 right-5 z-[80] inline-flex items-center gap-2 rounded-lg bg-[#0f5238] px-4 py-3 text-sm font-bold text-white shadow-[0_8px_24px_rgba(25,28,29,0.18)]" role="status">
          <CheckCircle2 className="h-4 w-4" />
          {notice}
        </div>
      )}
    </SettingsDialog>
  );
}

function CurrentAccountSettings({ risk, setRisk, save, accountId, brokerAccounts }: any) {
  const riskField = (label: string, key: string, description: string) => <label className="block rounded-lg border border-stone-200/80 bg-stone-50/80 p-3"><span className="block text-xs font-semibold text-stone-800">{label}</span><span className="mt-1 block text-[11px] text-stone-400">{description}</span><div className="mt-3 flex items-center gap-2"><input type="number" min="0" max="100" step="0.1" value={risk[key] == null ? "" : Number(risk[key]) * 100} onChange={(event) => setRisk({ ...risk, [key]: Number(event.target.value) / 100 })} className="w-full rounded border border-stone-200 bg-white px-2.5 py-1.5 text-sm font-bold outline-none focus:border-[#3a6d50]" /><span className="text-xs text-stone-500">%</span></div></label>;
  const currentBroker = brokerAccounts.find((item: any) => item.account_id === accountId);
  return <main className="mx-auto w-full max-w-7xl space-y-5 px-6 py-5" aria-label="当前账号设置">
    <section className="rounded-xl border border-stone-200/70 bg-white p-5 shadow-sm"><div className="flex items-center justify-between border-b border-stone-100 pb-4"><div><h2 className="text-base font-bold text-stone-900">当前账号设置</h2><p className="mt-1 text-xs text-[#52616b]">配置当前选中账号的交易风控和执行规则。</p></div><button type="button" onClick={() => void save()} className="rounded-lg bg-[#2d5a43] px-4 py-2 text-sm font-bold text-white">保存设置</button></div><div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">{riskField("默认单笔风险比例", "default_trade_risk_pct", "用于计算单笔交易的风险预算")}{riskField("最大单笔风险比例", "max_trade_risk_pct", "超过后禁止提交交易")}{riskField("单票最大仓位比例", "max_single_position_pct", "限制单个标的占用的账户资产")}{riskField("最大总仓位比例", "max_total_exposure_pct", "限制全部持仓占用的账户资产")}</div><div className="mt-4 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-500">最低现金留存：{typeof risk.max_total_exposure_pct === "number" ? `${((1 - risk.max_total_exposure_pct) * 100).toFixed(1)}%` : "—"}（根据最大总仓位自动计算）</div></section>
    <NodeSettingsPanel currentBroker={currentBroker} />
  </main>;
}

function BrokerAccountsPanel({ brokerAccounts, brokerForm, setBrokerForm, setBrokerDialogOpen, busy, testingBrokerId, testBrokerProfile, deleteBrokerProfile, editBrokerProfile }: any) {
  function openAdd() {
    setBrokerForm({ name: "", account_type: "SIMULATION", broker: "", broker_account_id: "", broker_strategy_id: "", broker_node_url: "", broker_gm_token: "" });
    setBrokerDialogOpen(true);
  }
  return <Card id="broker-accounts" className="rounded-xl border border-stone-200/70 bg-white p-5 shadow-sm">
    <div className="mb-4 flex items-center justify-between gap-3 border-b border-stone-100 pb-4">
      <div><h2 className="text-base font-bold text-stone-900">券商账号</h2><p className="mt-1 text-xs text-[#52616b]">管理仿真和实盘账号，并测试账号连接状态。</p></div>
      <button type="button" onClick={openAdd} className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-[#2d5a43] px-3.5 py-1.5 text-xs font-medium text-white"><Plus className="h-4 w-4" />添加账号</button>
    </div>
    {brokerAccounts.length === 0 ? <div className="rounded-lg bg-[#f3f4f5] px-4 py-8 text-center text-sm text-[#52616b]">暂未添加券商账号</div> : <div className="space-y-3">{brokerAccounts.map((item: any) => <div key={item.id} className="rounded-lg border border-stone-200 bg-white p-4"><div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center"><div className="min-w-0 flex-1 space-y-2"><div className="flex flex-wrap items-center gap-2.5"><span className="text-sm font-bold text-stone-900">{item.name}</span><span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">{item.account_type === "SIMULATION" ? "仿真环境" : "实盘环境"}</span><span className="inline-flex items-center gap-1 rounded bg-emerald-50/60 px-2 py-0.5 text-[11px] font-medium text-emerald-600"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />{item.status === "ACTIVE" ? "已配置" : item.status}</span></div><div className="grid grid-cols-2 gap-x-5 gap-y-2 text-xs md:grid-cols-5"><div><span className="block text-[11px] text-stone-400">券商</span><span className="block truncate font-medium text-stone-700">{item.broker || "—"}</span></div><div><span className="block text-[11px] text-stone-400">账户 ID</span><span className="block truncate font-mono font-medium text-stone-800">{maskAccountIdentifier(item.broker_account_id)}</span></div><div><span className="block text-[11px] text-stone-400">策略 ID</span><span className="block truncate font-mono font-medium text-stone-800">{maskAccountIdentifier(item.broker_strategy_id)}</span></div><div><span className="block text-[11px] text-stone-400">Token</span><span className="block truncate font-mono font-medium text-stone-800">{maskToken(item.broker_gm_token)}</span></div><div><span className="block text-[11px] text-stone-400">Broker Node</span><span className="block truncate font-mono text-stone-700" title={item.broker_node_url}>{item.broker_node_url || "—"}</span></div></div></div><div className="flex shrink-0 items-center gap-2 border-t border-stone-100 pt-2 lg:border-t-0 lg:pt-0"><button type="button" onClick={() => editBrokerProfile(item)} disabled={busy} className="rounded border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs font-medium text-stone-700 disabled:opacity-50">编辑</button><button type="button" onClick={() => void testBrokerProfile(item.id)} disabled={busy} className="inline-flex items-center gap-1.5 rounded border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs font-medium text-stone-700 disabled:opacity-50"><Zap className={`h-3.5 w-3.5 text-emerald-600 ${testingBrokerId === item.id ? "animate-spin" : ""}`} />{testingBrokerId === item.id ? "测试中" : "测试"}</button><button type="button" onClick={() => void deleteBrokerProfile(item.id)} disabled={busy} className="rounded border border-red-200/80 px-2.5 py-1.5 text-xs text-red-600 disabled:opacity-50">删除</button></div></div></div>)}</div>}
  </Card>;
}

function NodeSettingsPanel({ currentBroker }: { currentBroker?: any }) {
  const selected = currentBroker;
  const [settings, setSettings] = useState({ allow_live_orders: false, start_paused: true });
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!selected || selected.account_type !== "LIVE") return;
    setLoading(true); setMessage(null);
    void request(`/api/trading/broker-accounts/${selected.id}/node-settings`)
      .then((result) => setSettings({ allow_live_orders: Boolean(result.settings?.settings?.allow_live_orders), start_paused: Boolean(result.settings?.settings?.start_paused) }))
      .catch((error) => setMessage(error instanceof Error ? error.message : "读取 Node 设置失败"))
      .finally(() => setLoading(false));
  }, [selected?.id]);

  async function save() {
    if (!selected || !password) { setMessage("请输入管理员密码"); return; }
    setLoading(true); setMessage(null);
    try {
      await request(`/api/trading/broker-accounts/${selected.id}/node-settings`, { method: "PATCH", body: JSON.stringify({ ...settings, password }) });
      setPassword(""); setMessage("Node 设置已保存并生效");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Node 设置保存失败"); }
    finally { setLoading(false); }
  }

  return <section className="rounded-xl border border-stone-200/70 bg-white p-5 shadow-sm">
    <div className="mb-4 flex items-center gap-2 border-b border-stone-100 pb-4"><div className="rounded border border-rose-100 bg-rose-50 p-1.5 text-rose-600"><Shield className="h-4 w-4" /></div><div><h2 className="text-base font-bold text-stone-900">实盘交易授权</h2><p className="mt-1 text-xs text-stone-500">修改后同步到对应 Broker Node。变更授权需要管理员密码。</p></div></div>
    {!selected ? <p className="text-sm text-stone-500">当前账号未绑定券商账号。</p> : selected.account_type !== "LIVE" ? <p className="text-sm text-stone-500">当前为仿真账号，无需配置实盘交易授权。</p> : <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="rounded-lg bg-stone-50 px-3 py-2 text-sm font-medium text-stone-700">当前账号：{selected.name}</div>
      <label className="flex items-center justify-between rounded-lg bg-stone-50 px-3 py-2"><span className="text-sm font-medium text-stone-700">允许实盘下单</span><input type="checkbox" checked={settings.allow_live_orders} onChange={(event) => setSettings({ ...settings, allow_live_orders: event.target.checked })} disabled={loading} className="h-4 w-4 accent-[#0f5238]" /></label>
      <label className="block"><span className="mb-1 block text-xs font-medium text-stone-600">管理员密码</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" placeholder="请输入密码确认" className="w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-[#3a6d50]" /></label>
      <div className="flex items-end justify-between gap-3"><p className="text-xs text-stone-500">当前 Node：{selected?.broker_node_url || "—"}</p><button type="button" onClick={() => void save()} disabled={loading} className="rounded-lg bg-[#2d5a43] px-4 py-2 text-sm font-bold text-white disabled:opacity-50">{loading ? "保存中…" : "保存授权"}</button></div>
    </div>}
    {message && <p className="mt-3 text-xs text-stone-600" role="status">{message}</p>}
  </section>;
}

function ExactTradeSettings({ account, setAccount, risk, setRisk, brokerAccounts, brokerForm, setBrokerForm, setBrokerDialogOpen, busy, testingBrokerId, save, testBrokerProfile, deleteBrokerProfile, editBrokerProfile }: any) {
  const riskMetric = (label: string, key: string, badge: string, description: string, tone = "normal") => <div className="flex flex-col justify-between rounded-lg border border-stone-200/80 bg-stone-50/80 p-3"><div><div className="flex items-center justify-between"><span className={`text-xs font-semibold ${tone === "danger" ? "text-rose-700" : "text-stone-800"}`}>{label}</span><span className={`rounded px-1.5 py-0.5 text-[10px] font-num ${tone === "danger" ? "bg-rose-100 font-semibold text-rose-700" : tone === "liquidity" ? "bg-emerald-100 text-[#2d5a43]" : "bg-stone-200 text-stone-600"}`}>{badge}</span></div><p className="mt-1 text-[11px] text-stone-400">{description}</p></div><div className="mt-3 flex items-center gap-2"><input type="number" step="0.1" value={risk[key] == null ? "" : Number(risk[key]) * 100} onChange={(e) => setRisk({ ...risk, [key]: Number(e.target.value) / 100 })} className={`w-full rounded border bg-white px-2.5 py-1 font-mono text-sm font-bold outline-none ${tone === "danger" ? "border-rose-200 text-rose-600 focus:ring-1 focus:ring-rose-500" : "border-stone-200 text-stone-900 focus:ring-1 focus:ring-[#3a6d50]"}`} /><span className="text-xs font-medium text-stone-500 font-num">%</span></div></div>;
  function resetRisk() {
    setRisk({ ...risk, default_trade_risk_pct: 0.008, max_trade_risk_pct: 0.012, max_single_position_pct: 0.2, max_total_exposure_pct: 0.8 });
  }
  return <main className="trade-settings-reference mx-auto w-full max-w-7xl px-6 py-5" aria-label="交易账户与券商连接设置">
    <section className="rounded-xl border border-stone-200/70 bg-white p-5 shadow-sm"><div className="flex items-center justify-between border-b border-stone-100 pb-4"><div><div className="flex items-center gap-2"><h2 className="text-base font-bold text-stone-900">券商网关与交易通道</h2><span className="rounded-full bg-stone-100 px-2 py-0.5 text-xs font-mono text-stone-600">已挂载 {brokerAccounts.length} 个实例</span></div><p className="mt-0.5 text-xs text-stone-500">管理仿真策略通道与券商实盘交易柜台直连链路，支持单笔心跳检测与报单重连</p></div><button type="button" onClick={() => { setBrokerForm({ name: "", account_type: "SIMULATION", broker: "国投证券掘金", broker_account_id: "", broker_strategy_id: "", broker_node_url: "http://192.168.20.109:18731", broker_gm_token: "" }); setBrokerDialogOpen(true); }} className="inline-flex items-center gap-1 rounded-lg bg-[#2d5a43] px-3.5 py-1.5 text-xs font-medium text-white shadow-sm"><Plus className="h-4 w-4" />添加券商通道</button></div><div className="mt-4 space-y-3">{brokerAccounts.map((item: any) => <div key={item.id} className="rounded-lg border border-stone-200 bg-white p-4 transition-all hover:border-[#3a6d50]/40 hover:shadow-sm"><div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center"><div className="flex-1 space-y-2"><div className="flex flex-wrap items-center gap-2.5"><span className="text-sm font-bold text-stone-900">{item.name}</span><span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">{item.account_type === "SIMULATION" ? "仿真环境" : "实盘环境"}</span><span className="inline-flex items-center gap-1 rounded bg-emerald-50/60 px-2 py-0.5 text-[11px] font-mono text-emerald-600"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />{item.status === "ACTIVE" ? "已配置" : item.status}</span></div><div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs md:grid-cols-6"><div><span className="block text-[11px] text-stone-400">券商渠道</span><span className="font-medium text-stone-700">{item.broker}</span></div><div><span className="block text-[11px] text-stone-400">账户 ID</span><span className="block max-w-[120px] truncate font-mono font-medium text-stone-800" title="账户 ID 已隐藏">{maskAccountIdentifier(item.broker_account_id)}</span></div><div><span className="block text-[11px] text-stone-400">策略 ID</span><span className="block max-w-[120px] truncate font-mono font-medium text-stone-800" title="策略 ID 已隐藏">{maskAccountIdentifier(item.broker_strategy_id)}</span></div><div><span className="block text-[11px] text-stone-400">Token</span><span className="block max-w-[130px] truncate font-mono font-medium text-stone-800" title="Token 已隐藏">{maskToken(item.broker_gm_token)}</span></div><div><span className="block text-[11px] text-stone-400">内部实例别名</span><span className="rounded bg-stone-100 px-1.5 py-0.5 font-mono text-[11px] text-stone-700">{item.broker_account_key}</span></div><div><span className="block text-[11px] text-stone-400">网关 RPC 地址</span><span className="block max-w-[180px] truncate font-mono text-stone-700" title={item.broker_node_url}>{item.broker_node_url}</span></div></div></div><div className="flex shrink-0 items-center gap-2 border-t border-stone-100 pt-2 lg:border-t-0 lg:pt-0"><button type="button" onClick={() => editBrokerProfile(item)} disabled={busy} className="inline-flex items-center gap-1.5 rounded border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs font-medium text-stone-700"><Pencil className="h-3.5 w-3.5 text-stone-500" />编辑</button><button type="button" onClick={() => void testBrokerProfile(item.id)} disabled={busy} className="inline-flex items-center gap-1.5 rounded border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs font-medium text-stone-700"><Zap className={`h-3.5 w-3.5 text-emerald-600 ${testingBrokerId === item.id ? "animate-spin" : ""}`} />{testingBrokerId === item.id ? "测试中" : "测试"}</button><button type="button" onClick={() => void deleteBrokerProfile(item.id)} disabled={busy} className="rounded border border-red-200/80 px-2.5 py-1.5 text-xs text-red-600">删除</button></div></div></div>)}{brokerAccounts.length === 0 && <div className="rounded-lg bg-stone-50 px-4 py-6 text-center text-sm text-stone-500">暂未添加券商账户</div>}</div></section>
    <section className="rounded-xl border border-stone-200/70 bg-white p-5 shadow-sm"><div className="flex items-center justify-between border-b border-stone-100 pb-4"><div className="flex items-center gap-2.5"><div className="rounded border border-rose-100 bg-rose-50 p-1.5 text-rose-600"><Shield className="h-4 w-4" /></div><div><h2 className="text-base font-bold text-stone-900">量化风控规则与前置拦截</h2><p className="text-xs text-stone-500">所有报单将在本地与网关双重校验，超出阈值的委托指令将被直接驳回拦截</p></div></div><span className="text-xs font-semibold text-stone-700">风控引擎已启用</span></div><div className="mt-4 grid grid-cols-1 gap-3.5 md:grid-cols-3 lg:grid-cols-5">{riskMetric("单笔风险预算 (R)", "default_trade_risk_pct", "基准", "触发单笔止损时允许损失的净资产上限比例")}{riskMetric("单笔风险硬上限", "max_trade_risk_pct", "硬拦截", "即使出现黑天鹅极端跳空，单笔最大容忍亏损极限", "danger")}{riskMetric("单票最大持仓", "max_single_position_pct", "防集中度", "单个股票标的占用总市值的最高比例限制")}{riskMetric("账户最大总仓位", "max_total_exposure_pct", "总敞口", "全市场股票多头持仓总市值占账户净资产最高限")}{<div className="flex flex-col justify-between rounded-lg border border-stone-200/80 bg-stone-50/80 p-3"><div><div className="flex items-center justify-between"><span className="text-xs font-semibold text-[#2d5a43]">最低现金留存</span><span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-mono text-[#2d5a43]">流动性</span></div><p className="mt-1 text-[11px] text-stone-400">必须保留的可用流动性安全垫，禁止开仓耗尽</p></div><div className="mt-3"><div className="rounded border border-stone-200 bg-white px-2.5 py-1 font-mono text-sm font-bold text-[#2d5a43]">{typeof risk.max_total_exposure_pct === "number" ? `${((1 - risk.max_total_exposure_pct) * 100).toFixed(1)}%` : "—"}</div><div className="mt-1 text-[10px] font-mono text-stone-400">保底安全金</div></div></div>}</div><div className="mt-4 flex flex-col items-center justify-between gap-2 border-t border-stone-100 pt-3 text-xs text-stone-500 sm:flex-row"><div className="flex items-center gap-2"><span className="text-stone-500">提示：风控参数修改后将立即下发至本地交易引擎并写入日志审计，无需重启网关。</span></div><div className="flex items-center gap-2"><button type="button" onClick={resetRisk} className="text-stone-500 underline hover:text-stone-800">重置为保守预设</button><span className="text-stone-300">|</span><button type="button" onClick={() => void save()} className="font-medium text-[#2d5a43]">应用并广播风控规则</button></div></div></section>
  </main>;
}

function BrokerAccountDialog({ brokerForm, setBrokerForm, setBrokerDialogOpen, createBrokerAccount, busy, editing = false }: any) {
  const field = (label: string, key: string, type = "text") => <label className="block"><span className="mb-1 block text-xs font-medium text-stone-600">{label}</span><input type={type} value={brokerForm[key] ?? ""} onChange={(e) => setBrokerForm({ ...brokerForm, [key]: e.target.value })} className="w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-[#3a6d50]" /></label>;
  return <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/35 p-4" role="dialog" aria-modal="true" aria-label="添加券商账户"><div className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-2xl"><div className="mb-5 flex items-center justify-between"><h2 className="text-xl font-bold">添加券商账户</h2><button type="button" onClick={() => setBrokerDialogOpen(false)} className="rounded-lg p-2 text-xl text-stone-500">×</button></div><div className="grid gap-3 sm:grid-cols-2">{field("账户名称", "name")}<label className="block"><span className="mb-1 block text-xs font-medium text-stone-600">账户类型</span><select value={brokerForm.account_type ?? ""} onChange={(e) => setBrokerForm({ ...brokerForm, account_type: e.target.value })} className="w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-[#3a6d50]"><option value="SIMULATION">仿真账户</option><option value="LIVE">实盘账户</option></select></label>{field("券商", "broker")}{field("账户 ID", "broker_account_id")}{field("策略 ID", "broker_strategy_id")}{field("Broker Node 地址", "broker_node_url", "url")}{field("Token", "broker_gm_token")}</div><div className="mt-6 flex justify-end gap-2"><button type="button" onClick={() => setBrokerDialogOpen(false)} className="rounded-lg border border-stone-200 px-4 py-2 text-sm font-bold text-stone-600">取消</button><button type="button" onClick={() => void createBrokerAccount()} disabled={busy} className="rounded-lg bg-[#2d5a43] px-4 py-2 text-sm font-bold text-white">保存账户</button></div></div></div>;
}

function SettingsDialog({ children, onClose, modal = false }: { children: ReactNode; onClose: () => void; modal?: boolean }) {
  if (modal) return <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/35 p-4 backdrop-blur-sm"><section className="flex h-[min(760px,calc(100vh-3rem))] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-[#d8dde4] bg-[#f8f9fa] shadow-2xl" role="dialog" aria-modal="true" aria-label="全局设置"><header className="flex shrink-0 items-center justify-between border-b border-[#dee2e6] bg-white px-6 py-4"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-[#0f5238]">GLOBAL SETTINGS</p><h2 className="mt-1 text-lg font-bold text-[#191c1d]">全局设置</h2><p className="mt-0.5 text-xs text-[#52616b]">数据管理、更新计划、数据质量与任务记录</p></div><button type="button" onClick={onClose} aria-label="关闭全局设置" className="rounded-lg p-2 text-[#52616b] hover:bg-[#edf0f3]"><X className="h-4 w-4" /></button></header><div className="min-h-0 flex-1 overflow-y-auto p-6">{children}</div></section></div>;
  return <div className="min-h-screen w-full bg-[#f6f4ee] px-6 py-5"><div className="mx-auto max-w-[1600px]">{children}</div></div>;
}

function DataStatus({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-[#f3f4f5] px-3 py-2"><div className="text-[11px] text-[#52616b]">{label}</div><div className="mt-1 truncate text-sm font-bold text-[#354860]" title={value}>{value}</div></div>;
}

function SettingsGroup({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return <section className="rounded-xl border border-[#dee2e6] bg-white p-4">
    <div className="mb-3">
      <h4 className="font-bold text-[#354860]">{title}</h4>
      <p className="mt-1 text-xs leading-5 text-[#68736d]">{description}</p>
    </div>
    {children}
  </section>;
}

function ToggleField({ label, fieldKey, state, setState }: { label: string; fieldKey: string; state: any; setState: (value: any) => void }) {
  return <label className="flex items-center justify-between gap-3 rounded-lg bg-[#f3f4f5] px-3 py-2"><span className="text-[11px] font-bold text-[#52616b]">{label}</span><input type="checkbox" checked={Boolean(state[fieldKey])} onChange={(event) => setState({ ...state, [fieldKey]: event.target.checked })} className="h-4 w-4 accent-[#0f5238]" /></label>;
}

function editField(
  label: string,
  key: string,
  state: any,
  setState: (value: any) => void,
  type = "number",
) {
  return (
    <label className="block rounded-lg bg-[#f3f4f5] px-2.5 py-2">
      <span className="mb-0.5 block text-[11px] text-[#52616b]">{label}</span>
      <input
        type={type}
        step={type === "number" ? "0.0001" : undefined}
        value={state[key] ?? ""}
        onChange={(event) =>
          setState({
            ...state,
            [key]:
              type === "number"
                ? Number(event.target.value)
                : event.target.value,
          })
        }
        className="h-5 w-full border-0 bg-transparent text-sm font-bold outline-none"
      />
    </label>
  );
}
function formatAmountInput(value: string) {
  if (!value) return "";
  const [integer, decimal] = value.split(".");
  const formattedInteger = Number(integer || "0").toLocaleString("zh-CN");
  return decimal === undefined ? formattedInteger : `${formattedInteger}.${decimal}`;
}
function chineseAmount(value: unknown) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "";
  const trim = (number: number) => Number(number.toFixed(2)).toLocaleString("zh-CN");
  const sign = amount < 0 ? "-" : "";
  const absolute = Math.abs(amount);
  if (absolute >= 100_000_000) return `${sign}${trim(absolute / 100_000_000)} 亿元`;
  if (absolute >= 10_000) return `${sign}${trim(absolute / 10_000)} 万元`;
  return `${sign}${trim(absolute)} 元`;
}
function AmountField({
  label,
  fieldKey,
  state,
  setState,
}: {
  label: string;
  fieldKey: string;
  state: any;
  setState: (value: any) => void;
}) {
  const externalValue = state[fieldKey];
  const [draft, setDraft] = useState(() => externalValue == null ? "" : formatAmountInput(String(externalValue)));
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!focused) setDraft(externalValue == null ? "" : formatAmountInput(String(externalValue)));
  }, [externalValue, focused]);
  const amount = Number(draft.replace(/,/g, ""));
  return (
    <label className="block rounded-lg bg-[#f3f4f5] px-2.5 py-2">
      <span className="mb-0.5 block text-[11px] text-[#52616b]">{label}</span>
      <input
        type="text"
        inputMode="decimal"
        value={draft}
        onFocus={() => setFocused(true)}
        onChange={(event) => {
          const raw = event.target.value.replace(/,/g, "");
          if (!/^\d*(?:\.\d{0,2})?$/.test(raw)) return;
          setDraft(formatAmountInput(raw));
          setState({ ...state, [fieldKey]: raw === "" || raw === "." ? null : Number(raw) });
        }}
        onBlur={() => setFocused(false)}
        className="h-5 w-full border-0 bg-transparent text-sm font-bold outline-none"
      />
      {draft && Number.isFinite(amount) && <span className="mt-0.5 block text-[10px] text-[#7a827c]">{chineseAmount(amount)}</span>}
    </label>
  );
}
function percentageText(value: unknown) {
  if (value === null || value === undefined || value === "") return "";
  const number = Number(value);
  return Number.isFinite(number) ? (number * 100).toFixed(2) : "";
}
function PercentageField({
  label,
  fieldKey,
  state,
  setState,
}: {
  label: string;
  fieldKey: string;
  state: any;
  setState: (value: any) => void;
}) {
  const externalValue = state[fieldKey];
  const [draft, setDraft] = useState(() => percentageText(externalValue));
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!focused) setDraft(percentageText(externalValue));
  }, [externalValue, focused]);

  return (
    <label className="block rounded-lg bg-[#f3f4f5] px-2.5 py-2">
      <span className="mb-0.5 block text-[11px] text-[#52616b]">{label}</span>
      <div className="relative">
        <input
          type="number"
          min="0.01"
          max="100"
          step="0.01"
          value={draft}
          onFocus={() => setFocused(true)}
          onChange={(event) => {
            const next = event.target.value;
            setDraft(next);
            const numeric = Number(next);
            setState({
              ...state,
              [fieldKey]: next.trim() && Number.isFinite(numeric) ? numeric / 100 : null,
            });
          }}
          onBlur={() => {
            setFocused(false);
            setDraft(percentageText(state[fieldKey]));
          }}
          className="h-5 w-full border-0 bg-transparent pr-5 text-sm font-bold outline-none"
        />
        <span className="pointer-events-none absolute right-0 top-0 text-xs text-[#52616b]">%</span>
      </div>
    </label>
  );
}
function selectField(
  label: string,
  key: string,
  state: any,
  setState: (value: any) => void,
  options: [string, string][],
) {
  return <label className="block rounded-lg bg-[#f3f4f5] px-2.5 py-2"><span className="mb-0.5 block text-[11px] text-[#52616b]">{label}</span><select value={state[key] ?? ""} onChange={(event) => setState({ ...state, [key]: event.target.value })} className="h-5 w-full border-0 bg-transparent text-sm font-bold outline-none">{options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>;
}
function BrokerCapabilities({ capabilities }: { capabilities: any }) {
  const groups: [string, string, string[]][] = [["支持的委托方式", "native_orders", capabilities?.native_orders || []], ["条件执行方式", "conditional_execution", capabilities?.conditional_execution || []], ["算法执行方式", "algorithms", capabilities?.algorithms || []]];
  return <div className="grid gap-4 sm:grid-cols-3">{groups.map(([label, key, items]) => <div key={key}><div className="mb-2 text-sm font-bold">{label}</div><div className="flex flex-wrap gap-2">{items.length ? items.map((item) => <span key={item} className="rounded bg-[#edeeef] px-3 py-1 text-xs">{item}</span>) : <span className="text-sm text-[#52616b]">连接券商后显示</span>}</div></div>)}</div>;
}
function EmptyState({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-20 text-center text-[#52616b]">
      <span className="text-[#bfc9c1]">{icon}</span>
      <span>{text}</span>
    </div>
  );
}
function Loading() {
  return (
    <div className="py-24 text-center text-sm text-[#52616b]">
      正在读取交易数据…
    </div>
  );
}
function ErrorBox({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="rounded-xl border border-[#ffdad6] bg-[#ffdad6] p-5 text-sm text-[#93000a]">
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-4 w-4" />
        {message}
      </div>
      <button
        onClick={onRetry}
        className="mt-3 rounded bg-white px-3 py-1.5 font-bold"
      >
        重新读取
      </button>
    </div>
  );
}
