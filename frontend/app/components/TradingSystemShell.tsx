"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { exchangeFromSymbol, orderTypesForExchange, orderTypeLabel, orderTypeDescription } from "./trading/orderTypes";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  BriefcaseBusiness,
  Building2,
  CandlestickChart,
  ChartNoAxesCombined,
  ChevronDown,
  CheckCircle2,
  ChevronRight,
  CirclePause,
  Cable,
  ClipboardList,
  Coins,
  CircleDollarSign,
  Database,
  Download,
  Ellipsis,
  Eye,
  FileText,
  Flag,
  Filter,
  FlaskConical,
  History,
  Landmark,
  ListChecks,
  Layers3,
  MonitorCog,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Rocket,
  Save,
  Settings,
  Shield,
  ShieldCheck,
  ShoppingCart,
  SlidersHorizontal,
  Trash2,
  UserRound,
  Wallet,
  WalletCards,
  Gem,
  X,
  Zap,
} from "lucide-react";
import TradePlansPage, { ActionPlanDialog, type TradePlanPrefill } from "./TradePlansPage";
import { ExitRuleDialog, RiskReferenceDialog } from "./TradeDialogs";
import type { TradingPageKey } from "./trading/types";
import TradingOverviewPage from "./trading/overview/TradingOverviewPage";
import TradingTradesPage from "./trading/trades/TradingTradesPage";
import { ActionDetailPage, ActionPage, RiskReferencePage, TradeDetailPage } from "./trading/TradingLifecyclePages";
import OrdersReactPage from "./trading/orders/OrdersPage";
import PositionsReactPage from "./trading/positions/PositionsPage";

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;
type TradingView =
  | "overview" | "trades" | "execution" | "orders" | "positions" | "settings"
  | "trade" | "risk" | "open" | "add" | "reduce" | "close" | "action";
type RootView =
  | "market"
  | "review"
  | "screening"
  | "watchlist"
  | "technical-classification"
  | "trading-system"
  | "trading-overview";
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
  ["orders", "订单", ShoppingCart],
  ["positions", "持仓", Wallet],
  ["settings", "配置", Settings],
];

function chinaMarketSession(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const weekday = parts.find((part) => part.type === "weekday")?.value;
  const hour = Number(parts.find((part) => part.type === "hour")?.value);
  const minute = Number(parts.find((part) => part.type === "minute")?.value);
  const minutes = hour * 60 + minute;
  const weekdayOpen = weekday !== "Sat" && weekday !== "Sun";
  return weekdayOpen && ((minutes >= 570 && minutes < 690) || (minutes >= 780 && minutes < 900));
}

function nextChinaMarketOpenMs(now = new Date()) {
  const candidate = new Date(now);
  for (let dayOffset = 0; dayOffset <= 7; dayOffset += 1) {
    candidate.setTime(now.getTime() + dayOffset * 24 * 60 * 60 * 1000);
    candidate.setHours(9, 30, 0, 0);
    if (candidate.getDay() !== 0 && candidate.getDay() !== 6 && candidate.getTime() > now.getTime()) {
      return Math.max(1000, candidate.getTime() - now.getTime());
    }
  }
  return 24 * 60 * 60 * 1000;
}

async function request(path: string, options?: RequestInit) {
  if (!API_BASE) throw new Error("交易服务配置不可用，请联系管理员");
  const method = String(options?.method || "GET").toUpperCase();
  // A write may already have reached the server when the browser loses the
  // response. Retrying it here could create a second plan or order. Only
  // idempotent reads may use the transient-network retry budget.
  const retryable = method === "GET" || method === "HEAD" || method === "OPTIONS";
  const maxAttempts = retryable ? 3 : 1;
  let lastError: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        cache: "no-store",
        ...options,
        headers: {
          ...(options?.body ? { "Content-Type": "application/json" } : {}),
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
        const payload = await response.json().catch(() => null);
        const detail = payload?.detail;
        throw new Error(typeof detail === "string" ? detail : typeof detail?.message === "string" ? detail.message : `交易请求未完成（HTTP ${response.status}）`);
      }
      return response.json();
    } catch (error) {
      lastError = error;
      if (attempt + 1 < maxAttempts && error instanceof TypeError) await new Promise((resolve) => setTimeout(resolve, 400 * (attempt + 1)));
      else throw error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("交易数据接口暂时无法连接");
}
function accountPath(path: string, accountId: number) {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}account_id=${encodeURIComponent(String(accountId))}`;
}
function assertTradingOverview(payload: any, accountId: number) {
  const actualAccountId = payload?.account?.id ?? payload?.account?.account_id;
  const requiredCollections = ["positions", "trades", "execution_plans", "orders", "fills", "reconciliation_issues"];
  if (actualAccountId !== undefined && Number(actualAccountId) !== accountId) {
    throw new Error("交易总览账号数据校验失败，请刷新后重试");
  }
  if (!payload?.account || requiredCollections.some((key) => !Array.isArray(payload[key]))) {
    throw new Error("交易总览数据不完整，请刷新后重试");
  }
  return payload;
}
function money(value: any) {
  return typeof value === "number" && Number.isFinite(value)
    ? `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : "—";
}
function moneyInput(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return money(Number.isFinite(parsed) ? parsed : null);
}
function dateTime(value: unknown) {
  if (!value) return "—";
  const parsed = new Date(String(value));
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
function pct(value: any) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "—";
}
function statusLabel(status: string) {
  return (
    (
      {
        ACTIVE: "运行中",
        PLANNED: "计划中",
        CLOSING: "清仓中",
        CLOSED: "已结束",
        PAUSED: "已暂停",
        DRAFT: "草稿",
        COMPLETED: "已完成",
        CANCELLED: "已取消",
        EXPIRED: "已过期",
        PENDING_SUBMIT: "等待发送",
        QUEUED: "排队中",
        CLAIMED: "已接收",
        DISPATCHING: "发送中",
        NEW: "已报",
        PENDING_NEW: "等待报单",
        SUBMITTED: "已发送",
        ACCEPTED: "已接受",
        PARTIALLY_FILLED: "部分成交",
        FILLED: "已成交",
        CANCEL_PENDING: "撤单中",
        PENDING_CANCEL: "撤单中",
        CANCEL_REQUESTED: "撤单中",
        CANCELLED_ORDER: "已撤单",
        CANCELED: "已撤单",
        REJECTED: "已拒绝",
        FAILED: "失败",
        UNKNOWN: "状态未知",
      } as Record<string, string>
    )[status] || (status ? "状态未知" : "—")
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
function sideLabel(side: unknown) {
  return side === "BUY" ? "买入" : side === "SELL" ? "卖出" : "方向未记录";
}
function executionTypeLabel(type: string) {
  return ({
    LIMIT: "限价委托",
    PERSISTENT_LIMIT: "持续限价",
    PRICE_TRIGGER: "价格触发",
    PRICE_RANGE: "价格区间触发",
  } as Record<string, string>)[type] || "执行方式未记录";
}
function executionRuleLabel(item: any) {
  const params = item.execution_params_json || {};
  if (item.execution_type === "LIMIT" || item.execution_type === "PERSISTENT_LIMIT")
    return `不高于 ${moneyInput(params.limit_price)}`;
  if (item.execution_type === "PRICE_TRIGGER")
    return `价格达到 ${moneyInput(params.trigger_price)} 后启动，限价保护 ${moneyInput(params.limit_price)}`;
  if (item.execution_type === "PRICE_RANGE")
    return `${moneyInput(params.low_price)} 至 ${moneyInput(params.high_price)} 内启动，限价保护 ${moneyInput(params.limit_price)}`;
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
  const [view, setView] = useState<TradingView>(initialView === "execution" ? "trades" : initialView);
  const [viewRestored, setViewRestored] = useState(false);
  useEffect(() => {
    const saved = window.sessionStorage.getItem(`lll-trading-view-${accountId}`);
    const restorable: TradingView[] = ["overview", "trades", "orders", "positions", "settings"];
    if (initialView === "overview" && saved && restorable.includes(saved as TradingView)) setView(saved as TradingView);
    setViewRestored(true);
  }, [accountId]);
  useEffect(() => {
    if (viewRestored && ["overview", "trades", "orders", "positions", "settings"].includes(view)) {
      window.sessionStorage.setItem(`lll-trading-view-${accountId}`, view);
    }
  }, [accountId, view, viewRestored]);
  const [tradeToOpen, setTradeToOpen] = useState<number | null>(null);
  const [selectedTradeId, setSelectedTradeId] = useState<number | null>(null);
  const [selectedActionPlanId, setSelectedActionPlanId] = useState<number | null>(null);
  const [actionDialog, setActionDialog] = useState<"ADD" | "REDUCE" | "CLOSE" | null>(null);
  const [actionInitialValues, setActionInitialValues] = useState<Record<string, string> | undefined>(undefined);
  const [prototypePlanForm, setPrototypePlanForm] = useState<any>(undefined);
  const [prototypePlanDialogOpen, setPrototypePlanDialogOpen] = useState(false);
  const [riskDialog, setRiskDialog] = useState<{ tradeId: number; legs: any[]; current?: number; reason?: string; target?: string } | null>(null);
  const [exitRuleDialog, setExitRuleDialog] = useState<{ tradeId: number; rule?: any } | null>(null);
  const [executionComposerOpen, setExecutionComposerOpen] = useState(false);
  const [orderDetail, setOrderDetail] = useState<any>(null);
  const [control, setControl] = useState<any>({ execution_paused: false });
  const [account, setAccount] = useState<any>(null);
  const [broker, setBroker] = useState<any>(null);
  const [reconciliationIssueCount, setReconciliationIssueCount] = useState(0);
  const [dataRevision, setDataRevision] = useState(0);
  const [marketRealtimeEnabled, setMarketRealtimeEnabled] = useState(false);
  const [shellError, setShellError] = useState<string | null>(null);
  const shellLoadVersion = useRef(0);
  const riskRequestVersion = useRef(0);
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
  const navigatePrototype = (nextView: TradingPageKey, tradeId?: number, planId?: number) => {
    if (tradeId !== undefined) setSelectedTradeId(tradeId);
    setSelectedActionPlanId((nextView === "action" || nextView === "open" || nextView === "add" || nextView === "reduce" || nextView === "close") && planId !== undefined ? planId : null);
    if (nextView === "risk" && tradeId !== undefined) {
      setRiskDialog(null);
    }
    setView((nextView === "execution" ? "trades" : nextView) as TradingView);
  };
  const requirePrototypeFields = (values: Record<string, string>, fields: string[], label: string) => {
    const missing = fields.filter((field) => !String(values[field] ?? "").trim());
    if (missing.length) {
      setShellError(`${label}缺少必填信息，请先完成表单后再继续`);
      return false;
    }
    setShellError(null);
    return true;
  };
  const submitPrototypePlan = (values: Record<string, string>) => {
    if (!requirePrototypeFields(values, ["trade_type", "reference_entry_price", "risk_reference_price", "plan_risk_pct"], "建仓计划")) return;
    const tradeType = values.trade_type;
    const fixedTarget = tradeType === "FIXED_TARGET";
    if (fixedTarget && !requirePrototypeFields(values, ["target_price"], "建仓计划")) return;
    setPrototypePlanForm({
      trade_type: tradeType,
      playbook_id: values.playbook_id || "",
      thesis: values.thesis || values.textarea_0 || "",
      reference_entry_price: values.reference_entry_price || values.input_2 || "",
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
      setShellError("当前页面缺少单股信息，无法提交交易动作");
      return;
    }
    if (page === "add") {
      if (!requirePrototypeFields(values, ["reason_code", "reason_text", "reference_price", "risk_reference_price", "action_risk_budget_amount"], "加仓计划")) return;
      setActionInitialValues({
        reasonCode: values.reason_code,
        referencePrice: values.reference_price || values.input_2 || "",
        riskPrice: values.risk_reference_price || values.input_4 || "",
        quantity: values.quantity || "",
        actionRiskBudget: values.action_risk_budget_amount || values.input_5 || "",
        reasonText: values.reason_text || values.input_1 || "",
        failureHandling: ({ exit_add: "EXIT_ADDED_QTY_ONLY", reduce_to: "REDUCE_TO_TARGET_QTY", exit_all: "CLOSE_ALL", manual: "MANUAL_REVIEW" } as Record<string, string>)[values.fail_action] || "EXIT_ADDED_QTY_ONLY",
        riskMode: values.risk_mode === "unified" ? "UNIFIED" : values.risk_mode === "mixed" ? "MIXED" : "INDEPENDENT",
        unifiedRiskReference: values.unified_risk_reference_price || values.input_11 || "",
      });
    } else if (page === "reduce") {
      if (!requirePrototypeFields(values, ["reason_code", "reduce_method", "quantity", "reference_price", "minimum_acceptable_price"], "减仓计划")) return;
      setActionInitialValues({
        reasonCode: values.reason_code,
        reduceMethod: values.reduce_method,
        quantity: values.quantity || values.input_0 || "",
        referencePrice: values.reference_price || values.input_1 || "",
        minimumPrice: values.minimum_acceptable_price || values.input_2 || "",
        reasonText: values.reason_text || values.textarea_0 || "",
        residualMode: values.residual_mode || "KEEP",
      });
    } else {
      if (!requirePrototypeFields(values, ["reason_code", "trigger_condition"], "清仓计划")) return;
      setActionInitialValues({
        reasonCode: values.reason_code,
        triggerCondition: values.trigger_condition,
        reasonText: values.reason_text || values.textarea_0 || "",
      });
    }
    setActionDialog(page.toUpperCase() as "ADD" | "REDUCE" | "CLOSE");
  };
  const submitPrototypeRisk = (values: Record<string, string>) => {
    if (selectedTradeId === null) {
      setShellError("当前页面缺少单股信息，无法调整风险参考");
      return;
    }
    const price = values.risk_reference_price || values.newRiskPriceInput || "";
    const requestedTarget = values.scopeTarget || "all";
    const version = ++riskRequestVersion.current;
    request(accountPath(`/api/trades/${selectedTradeId}`, accountId))
      .then((result) => {
        if (version !== riskRequestVersion.current) return;
        const legs = result.item?.legs || [];
        const selectedLeg = requestedTarget === "all" ? null : legs[Number(requestedTarget.replace("leg", "")) - 1];
        if (requestedTarget !== "all" && !selectedLeg) {
          setShellError("当前单股中未找到所选交易腿，请刷新后重试");
          return;
        }
        const current = price.trim() ? Number(price) : result.item?.position_risk_reference_price;
        if (price.trim() && (!Number.isFinite(current) || current <= 0)) {
          setShellError("请输入有效的风险参考价");
          return;
        }
        setRiskDialog({ tradeId: selectedTradeId, legs, current, reason: values.reason_text || values.textarea_0 || "", target: selectedLeg ? String(selectedLeg.id) : "TRADE" });
      })
      .catch((error) => { if (version === riskRequestVersion.current) setShellError(error instanceof Error ? error.message : "交易风险信息读取失败"); });
  };

  async function loadShell(resetCurrentAccount = false) {
    const version = ++shellLoadVersion.current;
    setShellError(null);
    // 后台轮询只更新已加载的数据，不能先清空 account。否则左侧账号入口
    // 会在“LLL 仿真”和“账号”之间短暂切换，造成页面闪烁。
    // 只有真正切换 accountId 时才清空旧账号，避免短暂展示上一个账号。
    if (resetCurrentAccount) {
      setAccount(null);
      setBroker(null);
      setReconciliationIssueCount(0);
      setControl({ execution_paused: false });
    }
    try {
      const [overviewResult, controlResult, brokerResult] = await Promise.allSettled([
        request(accountPath("/api/trading/overview", accountId)),
        request(accountPath("/api/trading/control", accountId)),
        request(accountPath("/api/trading/broker", accountId)),
      ]);
      if (overviewResult.status === "rejected") throw overviewResult.reason;
      if (controlResult.status === "rejected") throw controlResult.reason;
      if (version !== shellLoadVersion.current) return;
      const overview = assertTradingOverview(overviewResult.value, accountId);
      const control = controlResult.value;
      setAccount(overview.account);
      setReconciliationIssueCount(Array.isArray(overview.reconciliation_issues) ? overview.reconciliation_issues.length : 0);
      setControl(control.control);
      // The overview response already contains the account-scoped broker
      // status. Reuse it when the separate broker-status request is slow or
      // unavailable, so the Shell and prototype page cannot contradict one
      // another. This is the same server response, never fabricated state.
      if (brokerResult.status === "fulfilled") {
        setBroker(brokerResult.value);
      } else if (overview.broker_status && typeof overview.broker_status === "object") {
        setBroker({ connection: overview.broker_status });
      } else {
        setBroker({ connection: { status: "UNAVAILABLE", message: "券商状态暂时无法读取" } });
      }
      setDataRevision((current) => current + 1);
    } catch (error) {
      if (version !== shellLoadVersion.current) return;
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
    loadShell(true);
  }, [accountId]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let running = false;
    const poll = async () => {
      if (cancelled || running) return;
      const connected = broker?.connection?.status === "CONNECTED" || broker?.connection?.ok === true;
      const marketOpen = chinaMarketSession();
      const marketConnected = broker?.connection?.node_status?.market_connected === true;
      if (!connected) {
        setMarketRealtimeEnabled(false);
        running = true;
        try { await loadShell(); } finally { running = false; }
        if (!cancelled) timer = window.setTimeout(() => { void poll(); }, 15000);
        return;
      }
      if (!marketOpen) {
        setMarketRealtimeEnabled(false);
        timer = window.setTimeout(() => { void poll(); }, nextChinaMarketOpenMs());
        return;
      }
      if (!marketConnected) {
        setMarketRealtimeEnabled(false);
        running = true;
        try { await loadShell(); } finally { running = false; }
        if (!cancelled) timer = window.setTimeout(() => { void poll(); }, 15000);
        return;
      }
      setMarketRealtimeEnabled(true);
      running = true;
      try { await loadShell(); } finally { running = false; }
      if (!cancelled) timer = window.setTimeout(() => { void poll(); }, 2000);
    };
    timer = window.setTimeout(() => { void poll(); }, 1000);
    return () => { cancelled = true; if (timer !== undefined) window.clearTimeout(timer); };
  }, [accountId, broker?.connection?.status, broker?.connection?.ok, broker?.connection?.node_status?.market_connected]);
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
      // Re-read the selected account after a successful control write so the
      // embedded prototype page cannot keep stale execution/status data.
      if (!result.control) throw new Error("交易控制接口未返回当前账号状态");
      await loadShell();
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
  const hasBrokerStatus = Boolean(broker?.connection);
  const accountType =
    account?.account_type === "LIVE"
      ? "实盘账户"
      : account?.account_type === "SIMULATION"
        ? "模拟账户"
        : "规划账户";
  const brokerStatusText = !connected
    ? !hasBrokerStatus
      ? "状态读取中"
      : broker?.connection?.status === "UNAVAILABLE"
        ? "状态暂不可用"
        : "未连接"
    : broker?.connection?.node_status?.agent_online === false
      ? "已连接·执行器离线"
      : reconciliationIssueCount > 0
      ? "已连接·待处理对账"
      : broker?.connection?.node_status?.reconciliation_required
      ? "已连接·保护中"
      : broker?.connection?.node_status?.paused
        ? "已连接·已暂停"
      : broker?.connection?.node_status?.execution_enabled === false
        ? "已连接·暂不可执行"
        : "连接正常";
  const overviewReact = view === "overview";
  return (
    <div className={`trading-system-shell min-h-screen bg-[#f8f9fa] text-[#191c1d] ${embedded ? "trading-system-shell-embedded" : ""} ${overviewReact ? "trading-overview-shell" : ""}`}>
      {!embedded && (
      <header className={`fixed top-0 z-50 w-full border-b border-[#dee2e6] bg-white/95 shadow-[0_1px_8px_rgba(0,0,0,0.04)] backdrop-blur-md ${overviewReact ? "trading-overview-header" : ""}`}>
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
                ? (broker?.connection?.node_status?.agent_online === false ? "已连接·执行器离线" : reconciliationIssueCount > 0 ? "已连接·待对账" : broker?.connection?.node_status?.reconciliation_required ? "已连接·待对账" : broker?.connection?.node_status?.paused ? "已连接·已暂停" : broker?.connection?.node_status?.execution_enabled === false ? "已连接·暂不可执行" : "连接正常")
                : brokerStatusText === "未连接" ? "券商未连接" : brokerStatusText}
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
      <main className={`min-h-screen bg-[#f8f7f2] ${embedded ? "pt-0" : "pt-16"} ${overviewReact ? "trading-overview-main" : ""}`}>
        <div className="flex min-h-[calc(100vh-3rem)]">
        <aside className={`sticky top-16 flex h-[calc(100vh-4rem)] w-[60px] shrink-0 flex-col border-r border-stone-200/80 bg-[#f6f4ee] px-0 py-3 ${overviewReact ? "trading-overview-sidebar" : ""}`}>
          <nav aria-label="交易系统功能" className="flex flex-1 flex-col items-center gap-3">
            {secondaryNavigation.filter(([key]) => key !== "settings").map(([key, label, Icon]) => (
              <button
                key={key}
                onClick={() => setView(key)}
                title={label}
                aria-label={label}
                className={`group relative flex h-[48px] w-[48px] flex-col items-center justify-center rounded-lg text-[10px] transition-colors ${view === key ? "bg-[#2d5a43] font-bold text-white shadow-[0_2px_6px_rgba(45,90,67,0.28)]" : "text-stone-500 hover:bg-stone-200/60 hover:text-stone-800"}`}
              >
                <Icon className="h-5 w-5" strokeWidth={1.8} />
                <span className="mt-1">{label === "交易总览" ? "总览" : label}</span>
              </button>
            ))}
          </nav>
          <div className="mb-2 flex w-full flex-col items-center gap-2 border-t border-stone-200/80 pt-3">
            <button type="button" title={`${account?.name || "账号读取中"} · 券商${brokerStatusText}`} aria-label={`当前账号：${account?.name || "账号读取中"}，券商${brokerStatusText}`} className={`relative flex h-[42px] w-[48px] flex-col items-center justify-center rounded-lg shadow-sm ${connected ? "bg-[#b8dec0] text-[#1f2937]" : "bg-[#ae2012] text-white"}`}>
              <UserRound className="h-4 w-4" />
              <span className="mt-0.5 max-w-[44px] truncate text-[9px]">{account?.name || "账号"}</span>
              <span className={`absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full ring-2 ring-white/70 ${connected ? "bg-[#2d6a4f]" : "bg-[#ffd0cc]"}`} />
            </button>
            <button type="button" onClick={togglePause} title={control.execution_paused ? "当前账号已暂停，点击恢复执行" : "暂停当前账号执行"} aria-label={control.execution_paused ? "恢复当前账号执行" : "暂停当前账号执行"} className={`flex h-[36px] w-[48px] items-center justify-center rounded-lg transition-colors ${control.execution_paused ? "bg-[#fff0dc] text-[#c66a12] hover:bg-[#ffe2bd]" : "bg-[#fde7e5] text-[#ae2012] hover:bg-[#f8d5d1]"}`}>
              {control.execution_paused ? <Play className="h-4 w-4" /> : <CirclePause className="h-4 w-4" />}
            </button>
            {reconciliationIssueCount > 0 && <span title={`待处理对账 ${reconciliationIssueCount} 项`} className="flex h-6 min-w-6 items-center justify-center rounded-full bg-[#fff0dc] px-1 text-[10px] font-bold text-[#8a4b08]">{reconciliationIssueCount}</span>}
            <button key="settings" onClick={() => setView("settings")} title="配置" aria-label="配置" className={`flex h-[48px] w-[48px] flex-col items-center justify-center rounded-lg text-[10px] transition-colors ${view === "settings" ? "bg-[#2d5a43] font-bold text-white shadow-[0_2px_6px_rgba(45,90,67,0.28)]" : "text-stone-500 hover:bg-stone-200/60 hover:text-stone-800"}`}>
              <Settings className="h-5 w-5" strokeWidth={1.8} />
              <span className="mt-1">配置</span>
            </button>
          </div>
        </aside>
        <div className="min-w-0 flex-1">
          {shellError && (
            <div className="mx-6 mt-4 rounded-lg border border-[#ffdad6] bg-[#ffdad6] px-4 py-3 text-sm text-[#93000a]">
              {shellError}
            </div>
          )}
          {actionDialog && selectedTradeId !== null ? (
            <ActionPlanDialog
              accountId={accountId}
              fullPage
              action={{ tradeId: selectedTradeId, symbol: "", securityName: "", type: actionDialog }}
              initialValues={actionInitialValues}
              onClose={() => setActionDialog(null)}
              onSaved={async () => { setActionDialog(null); await loadShell(); setView("trade"); }}
              onError={setShellError}
            />
          ) : view === "overview" ? (
            <TradingOverviewPage
              accountId={accountId}
              onNavigate={navigatePrototype}
              onCreateTrade={() => setView("open")}
              onOpenSettings={() => setView("settings")}
              onRefresh={() => void loadShell()}
            />
          ) : view === "trades" ? (
            <TradingTradesPage
              accountId={accountId}
              onNavigate={navigatePrototype}
              onRefresh={() => void loadShell()}
            />
          ) : view === "trade" ? (
            <TradeDetailPage accountId={accountId} tradeId={selectedTradeId} onNavigate={navigatePrototype} onRefresh={() => void loadShell()} />
          ) : view === "risk" ? (
            <RiskReferencePage accountId={accountId} tradeId={selectedTradeId} onNavigate={navigatePrototype} onRefresh={() => void loadShell()} />
          ) : view === "open" ? (
            <TradePlansPage accountId={accountId} initialMode="new" initialPlanId={selectedActionPlanId} prefill={tradePlanPrefill} onPrefillConsumed={onPlanPrefillConsumed} onOpenSettings={() => setView("settings")} onExecuted={() => setView("trades")} />
          ) : ["add", "reduce", "close"].includes(view) ? (
            <ActionPage accountId={accountId} tradeId={selectedTradeId} planId={selectedActionPlanId} mode={view.toUpperCase() as "ADD" | "REDUCE" | "CLOSE"} onNavigate={navigatePrototype} onRefresh={() => void loadShell()} />
          ) : view === "action" ? (
            <ActionDetailPage accountId={accountId} tradeId={selectedTradeId} planId={selectedActionPlanId} onNavigate={navigatePrototype} />
          ) : view === "execution" ? (
            <TradingTradesPage accountId={accountId} onNavigate={navigatePrototype} onRefresh={() => void loadShell()} />
          ) : view === "orders" ? (
            <OrdersReactPage accountId={accountId} onNavigate={navigatePrototype} onRefresh={() => void loadShell()} />
          ) : view === "positions" ? (
            <PositionsReactPage accountId={accountId} onNavigate={navigatePrototype} onRefresh={() => void loadShell()} />
          ) : null}
          {view === "settings" && <SettingsPage accountId={accountId} onRefresh={loadShell} onClose={() => setView("overview")} />}
          {riskDialog && (
            <RiskReferenceDialog
              accountId={accountId}
              tradeId={riskDialog.tradeId}
              legs={riskDialog.legs}
              current={riskDialog.current}
              initialReason={riskDialog.reason}
              initialTarget={riskDialog.target}
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
  const [orderType, setOrderType] = useState("LIMIT");
  const [price, setPrice] = useState("");
  const [limitPrice, setLimitPrice] = useState("");
  const [rangeHigh, setRangeHigh] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [clientRequestId] = useState(() => crypto.randomUUID());
  useEffect(() => {
    request(accountPath("/api/trades", accountId)).then((result) => {
      const ready = (result.items || []).flatMap((trade: any) => (trade.plans || [])
        .filter((plan: any) => ["READY", "ARMED"].includes(plan.status))
        .map((plan: any) => ({ ...plan, symbol: trade.symbol, security_name: trade.symbol_name, trade_status: trade.status })));
      setPlans(ready);
      if (ready.length) {
        setSelectedId(String(ready[0].id));
        setPrice(String(ready[0].input_json?.reference_entry_price || ""));
        setLimitPrice(String(ready[0].input_json?.reference_entry_price || ""));
        setRangeHigh(String(ready[0].input_json?.reference_entry_price || ""));
      }
    }).catch((error) => onError(error instanceof Error ? error.message : "待执行交易计划读取失败"));
  }, [accountId, onError]);
  const selected = plans.find((plan) => String(plan.id) === selectedId);
  const exchange = selected ? exchangeFromSymbol(selected.symbol) : null;
  const orderPriceRequired = orderType === "LIMIT" || exchange === "SH";
  const orderPriceLabel = orderType === "LIMIT" ? "委托限价" : "保护限价";
  const executionTypes = exchange ? orderTypesForExchange(exchange) : [];
  function changeOrderType(nextType: string) {
    setOrderType(nextType);
    if (nextType === "LIMIT" || exchange === "SH") {
      const value = selected?.input_json?.reference_entry_price;
      if (value) setPrice(String(value));
    } else {
      setPrice("");
    }
  }
  function switchExecutionType(nextType: string) {
    setExecutionType(nextType);
    const rawReference = selected?.input_json?.reference_entry_price;
    const reference = typeof rawReference === "number" && Number.isFinite(rawReference) && rawReference > 0 ? rawReference : null;
    setPrice((current) => current || (reference === null ? "" : String(reference)));
    setLimitPrice((current) => current || (reference === null ? "" : String(reference)));
    setRangeHigh((current) => current || (reference === null ? "" : String(reference)));
  }
  async function save() {
    if (!selected) { onError("请选择一个已确认的交易计划"); return; }
    const priceValue = Number(price);
    const limitValue = Number(limitPrice);
    const rangeHighValue = Number(rangeHigh);
    const targetQty = selected.calculation_snapshot_json?.planned_qty;
    const needsOrderPrice = orderType === "LIMIT" || exchange === "SH";
    if (executionType === "LIMIT" && needsOrderPrice && (!Number.isFinite(priceValue) || priceValue <= 0)) { onError(`请输入有效${orderType === "LIMIT" ? "委托限价" : "保护限价"}`); return; }
    if (executionType === "PRICE_TRIGGER" && (!Number.isFinite(priceValue) || priceValue <= 0)) { onError("请输入有效触发价格"); return; }
    if (executionType === "PRICE_RANGE" && (!Number.isFinite(priceValue) || priceValue <= 0 || !Number.isFinite(rangeHighValue) || rangeHighValue <= priceValue)) { onError("价格区间必须填写有效的下限和上限，且上限大于下限"); return; }
    if (["PRICE_TRIGGER", "PRICE_RANGE"].includes(executionType) && needsOrderPrice && (!Number.isFinite(limitValue) || limitValue <= 0)) { onError(`请输入有效的触发后${orderType === "LIMIT" ? "委托限价" : "保护限价"}`); return; }
    if (typeof targetQty !== "number" || !Number.isFinite(targetQty) || targetQty <= 0) { onError("执行计划缺少有效的目标数量，请先完成交易计划计算"); return; }
    setBusy(true);
    try {
      const created = await request(accountPath("/api/trading/execution-plans", accountId), { method: "POST", body: JSON.stringify({
        trade_plan_id: selected.id,
        symbol: selected.symbol,
        side: ["REDUCE", "CLOSE"].includes(selected.action_type) ? "SELL" : "BUY",
        target_qty: targetQty,
        execution_type: executionType,
        client_request_id: clientRequestId,
        valid_until: validUntil ? `${validUntil}T23:59:59+08:00` : null,
        execution_params: {
          order_type: orderType,
          ...(orderType === "LIMIT" ? { limit_price: ["PRICE_TRIGGER", "PRICE_RANGE"].includes(executionType) ? limitValue : priceValue } : exchange === "SH" ? { protection_price: ["PRICE_TRIGGER", "PRICE_RANGE"].includes(executionType) ? limitValue : priceValue } : {}),
          ...(executionType === "PRICE_TRIGGER" ? { trigger_price: priceValue } : {}),
          ...(executionType === "PRICE_RANGE" ? { low_price: priceValue, high_price: rangeHighValue } : {}),
        },
      })});
      await request(accountPath(`/api/trading/execution-plans/${created.item.id}/status`, accountId), { method: "PATCH", body: JSON.stringify({ status: "ACTIVE" }) });
      await onSaved();
    } catch (error) { onError(error instanceof Error ? error.message : "执行计划创建失败"); }
    finally { setBusy(false); }
  }
  return <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/30 p-4"><div className="w-full max-w-lg rounded-xl bg-white p-5 shadow-xl"><div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-bold">创建执行计划</h2><button onClick={onClose} className="text-xl text-[#52616b]">×</button></div>{plans.length === 0 ? <p className="rounded-lg bg-[#fff8ed] p-3 text-sm text-[#8a4b08]">当前账号没有可创建执行计划的已确认交易计划。</p> : <div className="grid gap-3"><label className="text-sm font-bold">交易计划<select value={selectedId} onChange={(event) => { const next = plans.find((plan) => String(plan.id) === event.target.value); setSelectedId(event.target.value); setPrice(String(next?.input_json?.reference_entry_price || "")); setLimitPrice(String(next?.input_json?.reference_entry_price || "")); setRangeHigh(String(next?.input_json?.reference_entry_price || "")); setOrderType("LIMIT"); }} className="input mt-1">{plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.symbol} · {plan.security_name || "—"} · {typeof plan.calculation_snapshot_json?.planned_qty === "number" ? plan.calculation_snapshot_json.planned_qty.toLocaleString() : "—"} 股</option>)}</select></label><label className="text-sm font-bold">执行方式<select value={executionType} onChange={(event) => switchExecutionType(event.target.value)} className="input mt-1"><option value="LIMIT">立即提交</option><option value="PRICE_TRIGGER">价格触发</option><option value="PRICE_RANGE">价格区间触发</option></select></label><label className="text-sm font-bold">委托类型<select value={orderType} onChange={(event) => changeOrderType(event.target.value)} className="input mt-1">{executionTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><p className="-mt-2 text-xs font-normal text-[#52616b]">{exchange ? orderTypeDescription(orderType, exchange) : ""}</p>{(executionType === "LIMIT" ? orderPriceRequired : true) && <label className="text-sm font-bold">{executionType === "LIMIT" ? orderPriceLabel : executionType === "PRICE_TRIGGER" ? "触发价格" : "区间下限"}<input value={price} onChange={(event) => setPrice(event.target.value)} type="number" min="0.01" step="0.01" className="input mt-1" /></label>}{executionType === "PRICE_RANGE" && <label className="text-sm font-bold">区间上限<input value={rangeHigh} onChange={(event) => setRangeHigh(event.target.value)} type="number" min="0.01" step="0.01" className="input mt-1" /></label>}{["PRICE_TRIGGER", "PRICE_RANGE"].includes(executionType) && (orderType === "LIMIT" || exchange === "SH") && <label className="text-sm font-bold">{orderType === "LIMIT" ? "触发后委托限价" : "触发后保护限价"}<input value={limitPrice} onChange={(event) => setLimitPrice(event.target.value)} type="number" min="0.01" step="0.01" className="input mt-1" /></label>}<p className="text-xs text-[#52616b]">{exchange === "SH" && orderType !== "LIMIT" ? "上交所市价类型需要填写保护限价。" : exchange === "SZ" && orderType !== "LIMIT" ? "深交所市价类型不填写保护限价。" : "限价委托按填写的价格申报。"}</p><label className="text-sm font-bold">有效期<input value={validUntil} onChange={(event) => setValidUntil(event.target.value)} type="date" className="input mt-1" /></label></div>}<div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-md border border-[#bfc9c1] px-3 py-2 text-sm font-bold">取消</button><button onClick={() => void save()} disabled={busy || plans.length === 0} className="rounded-md bg-[#0f5238] px-3 py-2 text-sm font-bold text-white disabled:opacity-50">保存并启用</button></div></div></div>;
}

function PrototypeOrderDetailDialog({ data, onClose }: { data: { order: any; fills: any[] }; onClose: () => void }) {
  const { order, fills } = data;
  return <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/30 p-4"><div className="w-full max-w-2xl rounded-xl bg-white p-5 shadow-xl"><div className="mb-4 flex items-start justify-between"><div><h2 className="text-lg font-bold">订单详情</h2><p className="mt-1 text-xs text-[#52616b]">{order.symbol || "—"} · 订单 #{order.id}</p></div><button onClick={onClose} className="text-xl text-[#52616b]">×</button></div><div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4"><div className="rounded-lg bg-[#f5f3ed] p-3"><span className="block text-xs text-[#52616b]">方向</span><b>{order.side === "BUY" ? "买入" : order.side === "SELL" ? "卖出" : "—"}</b></div><div className="rounded-lg bg-[#f5f3ed] p-3"><span className="block text-xs text-[#52616b]">状态</span><b>{statusLabel(order.status)}</b></div><div className="rounded-lg bg-[#f5f3ed] p-3"><span className="block text-xs text-[#52616b]">委托数量</span><b>{order.quantity ?? "—"}</b></div><div className="rounded-lg bg-[#f5f3ed] p-3"><span className="block text-xs text-[#52616b]">成交数量</span><b>{order.filled_quantity ?? order.filled_qty ?? "—"}</b></div></div><div className="mt-4 grid grid-cols-2 gap-3 rounded-lg border border-[#edf0f2] p-3 text-xs sm:grid-cols-3"><div><span className="block text-[#52616b]">Broker Order ID</span><b className="break-all">{order.broker_order_id || "—"}</b></div><div><span className="block text-[#52616b]">Client Order ID</span><b className="break-all">{order.client_order_id || "—"}</b></div><div><span className="block text-[#52616b]">所属 ExecutionPlan</span><b>{order.execution_plan_id ?? "—"}</b></div><div><span className="block text-[#52616b]">所属单股Plan</span><b>{order.trade_plan_id ?? "—"}</b></div><div><span className="block text-[#52616b]">所属单股</span><b>{order.trade_id ? `Trade #${order.trade_id}` : "—"}</b></div><div><span className="block text-[#52616b]">订单时间</span><b>{dateTime(order.created_at)}</b></div></div><h3 className="mt-5 mb-2 text-sm font-bold">成交回报</h3>{fills.length ? <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead className="bg-[#f5f3ed]"><tr><th className="px-3 py-2">时间</th><th className="px-3 py-2">成交价</th><th className="px-3 py-2">成交数量</th><th className="px-3 py-2">券商成交号</th></tr></thead><tbody>{fills.map((fill: any) => <tr key={fill.id} className="border-t border-[#edf0f2]"><td className="px-3 py-2">{dateTime(fill.filled_at || fill.created_at)}</td><td className="px-3 py-2">{money(fill.price)}</td><td className="px-3 py-2">{fill.quantity ?? fill.filled_quantity ?? "—"}</td><td className="px-3 py-2">{fill.broker_fill_id || "—"}</td></tr>)}</tbody></table></div> : <p className="rounded-lg bg-[#f5f3ed] p-3 text-sm text-[#52616b]">当前订单暂无成交回报。</p>}<div className="mt-5 flex justify-end"><button onClick={onClose} className="rounded-lg bg-[#0f5238] px-3 py-2 text-sm font-bold text-white">关闭</button></div></div></div>;
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

/**
 * @deprecated This legacy React overview is intentionally not rendered.
 * The active trading-system overview is the component in
 * trading/overview/TradingOverviewPage.tsx. Keep this marker until the
 * remaining legacy block is extracted from this settings/dialog module
 * without changing the active route.
 */
function LegacyOverviewPage({
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
  const [tradeFilter, setTradeFilter] = useState<"ALL" | "TREND" | "REBOUND" | "EXIT">("ALL");
  const [riskSortDescending, setRiskSortDescending] = useState(true);
  const loadVersion = useRef(0);
  async function load() {
    const version = ++loadVersion.current;
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
      if (version !== loadVersion.current) return;
      setData({
        ...overview,
        trades: trades.items || [],
        plans: groupedPlans,
        executions: executions.items || [],
        orders: orders.items || [],
      });
    } catch (e) {
      if (version === loadVersion.current) setError(e instanceof Error ? e.message : "交易总览读取失败");
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
  const allActiveTrades = data.trades.filter((item: any) => ["ACTIVE", "CLOSING"].includes(item.status));
  const readyPlans = data.plans.filter((item: any) => item.status === "READY");
  const unfinishedOrders = data.orders.filter((item: any) => !["FILLED", "CANCELLED", "CANCELED", "CANCELLED_ORDER", "REJECTED", "EXPIRED", "FAILED"].includes(item.status));
  const exposure = typeof account.total_exposure_pct === "number" && Number.isFinite(account.total_exposure_pct)
    ? account.total_exposure_pct * 100
    : null;
  const positionBySymbol = new Map<string, any>((data.positions || []).map((position: any) => [String(position.symbol), position] as [string, any]));
  const tradeRiskById = new Map<number, { capital: number | null; giveback: number | null }>();
  allActiveTrades.forEach((trade: any) => {
    const position = positionBySymbol.get(String(trade.symbol));
    let capital = 0;
    let giveback = 0;
    const legs = Array.isArray(trade.legs) ? trade.legs : [];
    let incomplete = legs.length === 0;
    let validLegs = 0;
    legs.forEach((leg: any) => {
      const remainingQty = Number(leg.remaining_qty);
      if (!Number.isFinite(remainingQty) || remainingQty < 0) {
        incomplete = true;
        return;
      }
      if (remainingQty === 0) return;
      const entryPrice = Number(leg.actual_avg_entry_price ?? leg.planned_entry_price);
      const riskReference = Number(leg.current_risk_reference_price ?? leg.initial_risk_reference_price);
      const marketPrice = Number(position?.market_price);
      if (!Number.isFinite(entryPrice) || !Number.isFinite(riskReference) || riskReference <= 0) {
        incomplete = true;
        return;
      }
      validLegs += 1;
      capital += Math.max(0, entryPrice - riskReference) * remainingQty;
      if (!Number.isFinite(marketPrice)) incomplete = true;
      else giveback += Math.max(0, marketPrice - riskReference) * remainingQty;
    });
    if (validLegs === 0) incomplete = true;
    tradeRiskById.set(Number(trade.id), { capital: incomplete ? null : capital, giveback: incomplete ? null : giveback });
  });
  const riskValues = allActiveTrades.map((trade: any) => tradeRiskById.get(Number(trade.id))?.capital);
  const risk = riskValues.length === 0 ? 0 : riskValues.every((value: number | null) => typeof value === "number")
    ? riskValues.reduce((sum: number, value: number | null) => sum + (value || 0), 0)
    : null;
  const riskLimit = typeof account.equity === "number" && typeof data.risk_profile?.max_trade_risk_pct === "number"
    ? account.equity * data.risk_profile.max_trade_risk_pct
    : null;
  const riskRatio = typeof risk === "number" && typeof riskLimit === "number" && riskLimit > 0
    ? (risk / riskLimit) * 100
    : null;
  const riskConfigured = data.risk_profile?.configuration_confirmed === true;
  const typeText = (type: string) => type === "TREND" ? "趋势交易" : type === "REBOUND" ? "反弹/波段" : type === "FIXED_TARGET" ? "固定目标" : type === "CUSTOM" ? "自定义" : "类型未记录";
  const statusText = (status: string) => status === "ACTIVE" ? "进行中" : status === "CLOSING" ? "清仓中" : status === "CLOSED" || status === "COMPLETED" ? "已结束" : ["CANCELLED", "CANCELED"].includes(status) ? "已取消" : status === "PLANNED" ? "计划中" : "状态未知";
  const latestPlan = (trade: any) => trade.plans?.length ? trade.plans[trade.plans.length - 1] : null;
  const activeTrades = allActiveTrades
    .filter((trade: any) => tradeFilter === "ALL" || (tradeFilter === "EXIT" ? trade.status === "CLOSING" : trade.trade_type === tradeFilter))
    .sort((left: any, right: any) => {
      const leftPosition = positionBySymbol.get(String(left.symbol));
      const rightPosition = positionBySymbol.get(String(right.symbol));
      const leftExposure = Number(leftPosition?.market_value);
      const rightExposure = Number(rightPosition?.market_value);
      const leftValue = Number.isFinite(leftExposure) ? leftExposure : -Infinity;
      const rightValue = Number.isFinite(rightExposure) ? rightExposure : -Infinity;
      return riskSortDescending ? rightValue - leftValue : leftValue - rightValue;
    });
  function exportTrades() {
    const rows: Array<Array<unknown>> = activeTrades.map((trade: any) => {
      const position = positionBySymbol.get(String(trade.symbol));
      const riskValues = tradeRiskById.get(Number(trade.id));
      return [trade.symbol, trade.symbol_name, trade.trade_type, trade.status, position?.quantity ?? "", position?.market_value ?? "", riskValues?.capital ?? "", riskValues?.giveback ?? ""];
    });
    const csv = [["证券代码", "证券名称", "交易类型", "状态", "持仓数量", "持仓市值", "本金计划风险", "利润回吐风险"], ...rows]
      .map((row: unknown[]) => row.map((value: unknown) => `"${String(value).replaceAll('"', '""')}"`).join(","))
      .join("\n");
    const url = URL.createObjectURL(new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `交易总览-${account.id}-${new Date().toISOString().slice(0, 10)}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  const pnlTone = (item: any) => typeof item.unrealized_pnl === "number" && Number.isFinite(item.unrealized_pnl)
    ? item.unrealized_pnl >= 0 ? "text-[#a73354]" : "text-[#2b543c]"
    : "text-[#717972]";
  const positionWinRate = data.positions.length > 0 && data.positions.every((item: any) => typeof item.unrealized_pnl === "number" && Number.isFinite(item.unrealized_pnl))
    ? `${((data.positions.filter((item: any) => item.unrealized_pnl >= 0).length / data.positions.length) * 100).toFixed(1)}%`
    : "—";
  const environmentText = account.account_type === "SIMULATION" ? "仿真" : account.account_type === "LIVE" ? "实盘" : "规划";
  const brokerNodeStatus = data.broker_status?.node_status || {};
  const marketConnected = brokerNodeStatus.market_connected;
  const marketStatusUnavailable = ["UNAVAILABLE", "DISCONNECTED"].includes(data.broker_status?.status) || typeof marketConnected !== "boolean";
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
      <div className="flex items-center gap-3"><span className="h-2.5 w-2.5 animate-pulse rounded-full bg-[#2b543c]" /><span className="text-base font-semibold">账户资产与活动 Trade 全景监控</span><span className="hidden h-4 w-px bg-[#c1c8c1] sm:block" /><span className="text-xs text-[#414943]">价格口径：最近一次有效行情 · 数据更新：{dateTime(account.updated_at)}</span>{risk === null && <span className="rounded bg-[#fff8ed] px-2 py-1 text-xs text-[#8a4b08]">部分 Trade 风险数据不完整</span>}</div>
      <div className="flex items-center gap-2"><div className="flex items-center gap-1.5 rounded-lg bg-white px-3 py-2 text-xs shadow-sm"><Activity className="h-4 w-4 text-[#2b543c]" />交易环境：<b className="text-[#2b543c]">{environmentText}</b></div><div className="flex items-center gap-1.5 rounded-lg bg-white px-3 py-2 text-xs shadow-sm"><span className={`h-2 w-2 rounded-full ${engineText === "已连接" ? "bg-[#2b543c]" : "bg-[#a64b00]"}`} />执行引擎：<b>{engineText}</b></div><button onClick={() => onNavigate("open")} className="inline-flex items-center gap-1 rounded-lg bg-[#2b543c] px-3 py-2 text-sm font-medium text-white"><Plus className="h-4 w-4" />新建交易</button></div>
    </div>
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {card("bg-[#434c54] text-white", <Landmark className="h-5 w-5 text-[#d8e1eb]" />, "账户净资产", account.account_type === "LIVE" ? "实盘主账户" : "规划账户", money(account.equity), <span>可用现金 {money(account.available_cash)}</span>, <span className="text-xs">占比 {typeof account.available_cash === "number" && typeof account.equity === "number" && account.equity ? `${((account.available_cash / account.equity) * 100).toFixed(1)}%` : "—"}</span>)}
      {card("bg-[#436c53] text-white", <Activity className="h-5 w-5 text-[#beebcc]" />, "当前总仓位", "持仓市值 " + money(account.market_value), exposure === null ? "—" : `${exposure.toFixed(1)}%`, <span>当前总头寸 {data.positions.length} 只</span>, <span className="text-xs">/ 上限 {pct(data.risk_profile?.max_total_exposure_pct)}</span>)}
      {card("bg-[#a73354] text-white", <Shield className="h-5 w-5 text-[#ffd9de]" />, "账户当前总风险", riskConfigured ? "风控已配置" : "风控待配置", risk === null ? "—" : money(risk), <span>单笔硬上限 {pct(data.risk_profile?.max_trade_risk_pct)}</span>, <span className="text-xs">{risk === null ? "风险数据不完整" : "按 TradeLeg 汇总"}</span>)}
      {card("bg-white text-[#1b1c18]", <Activity className="h-5 w-5 text-[#a73354]" />, "今日浮动盈亏", "日内表现", money(account.unrealized_pnl), <span>累计实现盈亏</span>, <span className="text-xs text-[#a73354]">{money(account.realized_pnl)}</span>)}
    </div>
    <Card className="flex flex-col gap-4 bg-white p-5">
      <div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2"><div className="grid h-6 w-6 place-items-center rounded-lg bg-[#eae8e2]"><AlertTriangle className="h-4 w-4" /></div><h2 className="text-base font-semibold">待处理事项</h2><span className="rounded-full bg-[#ffd9de] px-2 py-0.5 text-[11px] font-medium text-[#88193d]">{readyPlans.length} 项需要关注</span></div><span className="text-xs text-[#414943]">基于当前账号最近一次同步结果</span></div>
      <div className="grid gap-3 md:grid-cols-3">
        {[...readyPlans.map((plan: any) => ({ kind: "warning", title: plan.symbol, text: `${actionLabel(plan.action_type)} 计划已就绪，等待创建执行计划。`, meta: "待部署", action: "立即部署执行" })), ...data.positions.filter((p: any) => Number(p.available_quantity) < Number(p.quantity)).map((p: any) => ({ kind: "clock", title: p.symbol, text: `当前剩余持仓受 T+1 或可卖数量限制，需等待可卖。`, meta: "流通受限", action: "查看详情" })), ...activeTrades.map((t: any) => ({ kind: "review", title: t.symbol, text: "整体风险参考需要复核，建议查看 Trade 详情。", meta: "风险复核", action: "复核调整" }))].map((item: any, index: number) => <div key={`${item.kind}-${item.title}-${index}`} className="flex min-h-[112px] flex-col justify-between gap-2 rounded-lg bg-[#f5f3ed] p-3"><div className="flex items-start gap-2"><AlertTriangle className={`mt-0.5 h-5 w-5 shrink-0 ${item.kind === "warning" ? "text-[#a73354]" : "text-[#434c54]"}`} /><div><b className="block text-sm">{item.title}</b><p className="mt-1 text-xs text-[#414943]">{item.text}</p></div></div><div className="flex items-center justify-between"><span className="text-[10px] text-[#717972]">{item.meta}</span><button onClick={() => onNavigate(item.kind === "warning" ? "execution" : "trades")} className="rounded-lg bg-[#2b543c] px-2.5 py-1 text-[11px] font-semibold text-white">{item.action}</button></div></div>)}
        {!readyPlans.length && !data.positions.some((p: any) => Number(p.available_quantity) < Number(p.quantity)) && !activeTrades.length && <div className="md:col-span-3 rounded-lg bg-[#f5f3ed] p-4 text-sm text-[#414943]">当前没有需要立即处理的事项。</div>}
      </div>
    </Card>
    <Card className="overflow-hidden bg-white p-0">
      <div className="flex flex-wrap items-center justify-between gap-3 p-5"><div className="flex flex-wrap items-center gap-3"><div className="flex items-center gap-2"><Activity className="h-5 w-5 text-[#2b543c]" /><h2 className="text-base font-semibold">活动 Trade 实时监控</h2></div><div className="flex items-center gap-1 rounded-lg bg-[#f5f3ed] p-0.5 text-xs"><button onClick={() => setTradeFilter("ALL")} className={`rounded-md px-3 py-1.5 font-semibold ${tradeFilter === "ALL" ? "bg-white shadow-sm" : "text-[#414943]"}`}>全部活动 ({allActiveTrades.length})</button><button onClick={() => setTradeFilter("TREND")} className={`rounded-md px-3 py-1.5 font-semibold ${tradeFilter === "TREND" ? "bg-white shadow-sm" : "text-[#414943]"}`}>趋势突破</button><button onClick={() => setTradeFilter("REBOUND")} className={`rounded-md px-3 py-1.5 font-semibold ${tradeFilter === "REBOUND" ? "bg-white shadow-sm" : "text-[#414943]"}`}>波段/回踩</button><button onClick={() => setTradeFilter("EXIT")} className={`rounded-md px-3 py-1.5 font-semibold ${tradeFilter === "EXIT" ? "bg-white shadow-sm" : "text-[#414943]"}`}>退出管理</button></div></div><div className="flex items-center gap-2 text-xs text-[#414943]"><button onClick={() => setRiskSortDescending((value) => !value)} className="flex items-center gap-1 rounded-lg bg-[#f5f3ed] px-2 py-1.5" title="切换风险敞口排序"><Filter className="h-4 w-4" />按持仓市值{riskSortDescending ? "降序" : "升序"}</button><button onClick={exportTrades} title="导出当前筛选结果" aria-label="导出当前筛选结果" className="rounded-lg p-1.5 hover:bg-[#f0eee8]"><Download className="h-5 w-5" /></button></div></div>
      <div className="overflow-x-auto"><table className="w-full min-w-[1260px] border-collapse text-left text-xs"><thead className="bg-[#f5f3ed] text-[#414943]"><tr>{["股票代码 / 名称","交易类型","生命周期","当前持仓","仓位占比","现价 / 成本","浮动盈亏","本金计划风险","利润回吐风险","最近动作","操作"].map((label) => <th key={label} className="px-4 py-3 font-medium">{label}</th>)}</tr></thead><tbody>{activeTrades.map((item: any) => { const position = positionBySymbol.get(String(item.symbol)); const plan = latestPlan(item); const tradeRisk = tradeRiskById.get(Number(item.id)); const quantity = position?.quantity ?? "—"; const available = position?.available_quantity ?? "—"; const exposurePct = typeof position?.market_value === "number" && typeof account.equity === "number" && account.equity ? (position.market_value / account.equity) * 100 : null; const pnl = position?.unrealized_pnl; return <tr key={item.id} className="border-t border-[#eae8e2] hover:bg-[#fbf9f3]"><td className="px-4 py-4"><button onClick={() => onOpenTrade(item.id)} className="text-left"><b className="mr-2 text-sm text-[#a73354]">{item.symbol}</b><b className="text-sm">{item.symbol_name}</b><span className="mt-1 block text-[10px] text-[#717972]">{item.sector || "—"}</span></button></td><td className="px-4 py-4"><span className="rounded bg-[#f0eee8] px-2 py-1">{typeText(item.trade_type)}</span></td><td className="px-4 py-4"><span className={`rounded-full px-2 py-1 text-[10px] font-medium ${item.status === "CLOSING" ? "bg-[#a73354] text-white" : "bg-[#2b543c] text-white"}`}>{statusText(item.status)}</span></td><td className="px-4 py-4"><b className="block text-sm">{quantity} 股</b><span className="text-[10px] text-[#717972]">可卖 {available} 股</span></td><td className="px-4 py-4"><div className="flex items-center gap-2"><span>{exposurePct === null ? "—" : `${exposurePct.toFixed(1)}%`}</span><span className="h-1.5 w-12 overflow-hidden rounded-full bg-[#e4e2dd]"><span className="block h-full rounded-full bg-[#2b543c]" style={{ width: `${Math.min(100, exposurePct || 0)}%` }} /></span></div></td><td className="px-4 py-4"><b className="block">{money(position?.market_price)}</b><span className="text-[#717972]">成本：{money(position?.average_cost)}</span></td><td className={`px-4 py-4 ${pnlTone(position || {})}`}><b className="block text-sm">{money(pnl)}</b><span>{typeof pnl === "number" && typeof position?.market_value === "number" && position.market_value ? `${((pnl / position.market_value) * 100).toFixed(2)}%` : "—"}</span></td><td className="px-4 py-4 text-[#2b543c]">{money(tradeRisk?.capital)}<span className="block text-[10px]">{tradeRisk?.capital == null ? "风险数据不完整" : "按 TradeLeg 计算"}</span></td><td className="px-4 py-4">{money(tradeRisk?.giveback)}</td><td className="px-4 py-4"><span className={`rounded px-2 py-1 ${item.status === "CLOSING" ? "bg-[#ffd9de] text-[#88193d]" : "bg-[#f0eee8]"}`}>{plan ? `${actionLabel(plan.action_type)} #${plan.sequence_no}` : "—"}</span></td><td className="px-4 py-4 text-right"><button onClick={() => onOpenTrade(item.id)} className="inline-flex items-center gap-1 rounded-lg bg-[#f5f3ed] px-3 py-1.5 font-semibold text-[#2b543c]">查看详情<ChevronRight className="h-4 w-4" /></button></td></tr>; })}</tbody></table></div>
      <div className="flex flex-wrap items-center justify-between gap-3 bg-[#f5f3ed] px-5 py-3 text-xs text-[#414943]"><div className="flex flex-wrap items-center gap-3"><span>统计：活动头寸 {activeTrades.length} 笔</span><span>•</span><span>持仓均赢率 {positionWinRate}</span><span>•</span><span>未实现净收益：<b className="text-[#a73354]">{money(account.unrealized_pnl)}</b></span></div><span className="flex items-center gap-1"><span className={`h-2 w-2 rounded-full ${marketStatusUnavailable ? "bg-[#a64b00]" : "bg-[#2b543c]"}`} />{marketStatusUnavailable ? "行情状态暂时无法读取" : marketConnected === true ? "行情通道已连接" : "已收盘，显示最近一次有效价格"}</span></div>
    </Card>
    <div className="grid gap-4 lg:grid-cols-12"><Card className="flex flex-col justify-between gap-4 bg-white p-5 lg:col-span-7"><div><div className="mb-4 flex items-center justify-between"><div className="flex items-center gap-2"><History className="h-5 w-5 text-[#2b543c]" /><h2 className="text-base font-semibold">最近操作与执行流水</h2></div><span className="rounded bg-[#f0eee8] px-2 py-1 text-[11px]">今日流水：{data.orders.length} 笔</span></div><div className="relative flex flex-col gap-4 border-l-2 border-[#eae8e2] pl-5">{[...data.orders.map((order: any) => ({ title: order.symbol || "—", tag: statusLabel(order.status), text: `${statusLabel(order.status)}，订单状态已同步至交易系统`, time: order.updated_at || order.created_at || "—" })), ...data.executions.map((execution: any) => ({ title: execution.symbol || "—", tag: statusLabel(execution.status), text: `执行计划${statusLabel(execution.status)}`, time: execution.updated_at || execution.created_at || "—" }))].map((event: any, index: number) => <div key={`${event.title}-${event.time}-${index}`} className="relative flex items-start justify-between gap-3"><span className="absolute -left-[1.62rem] top-1 h-2.5 w-2.5 rounded-full bg-[#2b543c] ring-4 ring-white" /><div><div className="flex flex-wrap items-center gap-2"><b className="text-sm">{event.title}</b><span className="rounded bg-[#c0edce] px-2 py-0.5 text-[10px]">{event.tag}</span></div><p className="mt-1 text-xs text-[#414943]">{event.text}</p></div><span className="whitespace-nowrap text-[10px] text-[#717972]">{event.time}</span></div>)}{!data.orders.length && !data.executions.length && <p className="text-sm text-[#717972]">暂无执行流水。</p>}</div></div><div className="flex items-center justify-between rounded-lg bg-[#f5f3ed] p-3 text-xs text-[#414943]"><span>已记录交易信号、委托确认与挂单回报</span><button onClick={() => onNavigate("orders")} className="flex items-center gap-1 font-semibold text-[#2b543c]">查看完整订单日志<ChevronRight className="h-4 w-4" /></button></div></Card>
      <Card className="flex flex-col justify-between gap-4 bg-white p-5 lg:col-span-5"><div><div className="mb-4 flex items-center justify-between"><div className="flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-[#2b543c]" /><h2 className="text-base font-semibold">风控与执行合规看板</h2></div><span className="rounded-full bg-[#c0edce] px-2 py-1 text-[11px] text-[#264f38]">{riskConfigured ? "已配置" : "待配置"}</span></div><div className="flex flex-col gap-4"><div className="rounded-lg bg-[#f5f3ed] p-3"><div className="flex items-center justify-between text-xs"><span>当前计划风险 / 风险上限</span><b>{risk === null || riskLimit === null ? "—" : `${money(risk)} / ${money(riskLimit)}`}</b></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-[#e4e2dd]"><div className="h-full rounded-full bg-[#2b543c]" style={{ width: `${Math.min(100, riskRatio || 0)}%` }} /></div><span className="mt-1 block text-[10px] text-[#717972]">基于当前 TradeLeg 和账号风控规则计算</span></div><div className="rounded-lg bg-[#f5f3ed] p-3"><div className="flex items-center justify-between text-xs"><span>头寸集中度（Max Single Position）</span><b>{data.positions.length ? `${Math.max(...data.positions.map((p: any) => Number(p.market_value || 0))) && account.equity ? `${(Math.max(...data.positions.map((p: any) => Number(p.market_value || 0))) / account.equity * 100).toFixed(1)}%` : "—"}` : "—"}</b></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-[#e4e2dd]"><div className="h-full rounded-full bg-[#434c54]" style={{ width: `${Math.min(100, exposure || 0)}%` }} /></div><span className="mt-1 block text-[10px] text-[#717972]">单票上限规则为 {pct(data.risk_profile?.max_single_position_pct)}</span></div><div className="flex items-start gap-2 rounded-lg bg-[#f0eee8] p-3"><CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-[#2b543c]" /><div><b className="block text-xs">风控策略状态通报</b><p className="mt-1 text-xs text-[#414943]">{activeTrades.length ? `当前 ${activeTrades.length} 笔活动 Trade 已接入风险计算，实际风险以账户与持仓接口返回为准。` : "当前没有活动 Trade，等待交易数据接入。"}</p></div></div></div></div><div className="flex items-center justify-between text-[10px] text-[#717972]"><span>风控状态依据当前账号规则更新</span><button onClick={() => onNavigate("settings")} className="flex items-center gap-1 hover:text-[#2b543c]"><Settings className="h-3.5 w-3.5" />风控参数设置</button></div></Card></div>
  </PageFrame>;
}

function ExecutionPage({ accountId, onRefresh }: { accountId: number; onRefresh: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [readyPlans, setReadyPlans] = useState<any[]>([]);
  const [broker, setBroker] = useState<any>(null);
  const [reconciliationIssueCount, setReconciliationIssueCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [composer, setComposer] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const loadVersion = useRef(0);
  const currentAccountId = useRef(accountId);
  async function load() {
    const version = ++loadVersion.current;
    setLoading(true);
    try {
      const [plans, brokerResult, trades, overview] = await Promise.all([
        request(accountPath("/api/trading/execution-plans", accountId)),
        request(accountPath("/api/trading/broker", accountId)),
        request(accountPath("/api/trades", accountId)),
        request(accountPath("/api/trading/overview", accountId)),
      ]);
      if (version !== loadVersion.current) return;
      setItems(plans.items || []);
      setBroker(brokerResult);
      setReconciliationIssueCount(Array.isArray(overview.reconciliation_issues) ? overview.reconciliation_issues.length : 0);
      setReadyPlans((trades.items || []).flatMap((trade: any) => (trade.plans || [])
        .filter((plan: any) => ["READY", "ARMED"].includes(plan.status))
        .map((plan: any) => ({ ...plan, trade_status: trade.status, trade_type: trade.trade_type }))));
      setLoading(false);
    } catch (e) {
      if (version === loadVersion.current) { setError(e instanceof Error ? e.message : "交易执行读取失败"); setLoading(false); }
    }
  }
  useEffect(() => {
    currentAccountId.current = accountId;
    setItems([]);
    setBroker(null);
    setReadyPlans([]);
    setReconciliationIssueCount(0);
    setError(null);
    load();
  }, [accountId]);
  async function setStatus(id: number, status: string) {
    try {
      await request(accountPath(`/api/trading/execution-plans/${id}/status`, accountId), {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      if (currentAccountId.current !== accountId) return;
      await load();
      onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "执行计划状态更新失败");
    }
  }
  function switchComposerType(nextType: string) {
    setComposer((current: any) => {
      if (!current) return current;
      const rawReference = current.tradePlan.input_json?.reference_entry_price;
      const reference = typeof rawReference === "number" && Number.isFinite(rawReference) && rawReference > 0 ? rawReference : null;
        const currentParams = current.execution_params || {};
      const orderType = currentParams.order_type || "LIMIT";
      const priceKey = orderType === "LIMIT" ? "limit_price" : "protection_price";
      const currentLimit = typeof currentParams[priceKey] === "number" && Number.isFinite(currentParams[priceKey]) && currentParams[priceKey] > 0 ? currentParams[priceKey] : null;
      const base = currentLimit ?? reference;
      const currentTrigger = typeof currentParams.trigger_price === "number" && Number.isFinite(currentParams.trigger_price) && currentParams.trigger_price > 0 ? currentParams.trigger_price : null;
      const currentLow = typeof currentParams.low_price === "number" && Number.isFinite(currentParams.low_price) && currentParams.low_price > 0 ? currentParams.low_price : null;
      const currentHigh = typeof currentParams.high_price === "number" && Number.isFinite(currentParams.high_price) && currentParams.high_price > 0 ? currentParams.high_price : null;
      if (nextType === "PRICE_TRIGGER") return { ...current, execution_type: nextType, execution_params: { order_type: orderType, trigger_price: currentTrigger ?? reference ?? undefined, [priceKey]: base ?? undefined } };
      if (nextType === "PRICE_RANGE") return { ...current, execution_type: nextType, execution_params: { order_type: orderType, low_price: currentLow ?? reference ?? undefined, high_price: currentHigh ?? reference ?? undefined, [priceKey]: base ?? undefined } };
      return { ...current, execution_type: nextType, execution_params: { order_type: orderType, [priceKey]: base ?? undefined } };
    });
  }
  function changeComposerOrderType(nextOrderType: string) {
    if (!composer) return;
    const exchange = exchangeFromSymbol(composer.tradePlan.symbol);
    const oldParams = composer.execution_params || {};
    const reference = composer.tradePlan.input_json?.reference_entry_price;
    const priceKey = nextOrderType === "LIMIT" ? "limit_price" : "protection_price";
    setComposer({ ...composer, execution_type: nextOrderType !== "LIMIT" && composer.execution_type === "PERSISTENT_LIMIT" ? "LIMIT" : composer.execution_type, execution_params: { ...oldParams, order_type: nextOrderType, limit_price: undefined, protection_price: undefined, ...(nextOrderType === "LIMIT" || exchange === "SH" ? { [priceKey]: reference } : {}) } });
  }
  async function createExecutionPlan() {
    if (!composer) return;
    const params = composer.execution_params || {};
    const exchange = exchangeFromSymbol(composer.tradePlan.symbol);
    const orderType = params.order_type || "LIMIT";
    const priceKey = orderType === "LIMIT" ? "limit_price" : "protection_price";
    const needsPrice = orderType === "LIMIT" || exchange === "SH";
    if (composer.execution_type === "PRICE_RANGE" && (!(params.low_price > 0) || !(params.high_price > params.low_price))) {
      setError("价格区间必须填写有效的下限和上限，且上限大于下限");
      return;
    }
    if ((needsPrice && !(params[priceKey] > 0)) || (composer.execution_type === "PRICE_TRIGGER" && !(params.trigger_price > 0))) {
      setError("请填写有效的委托限价或上交所市价保护限价，以及必要的触发价格");
      return;
    }
    const targetQty = composer.tradePlan.calculation_snapshot_json?.planned_qty;
    if (typeof targetQty !== "number" || !Number.isFinite(targetQty) || targetQty <= 0) {
      setError("执行计划缺少有效的目标数量，请先完成交易计划计算");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await request(accountPath("/api/trading/execution-plans", accountId), {
        method: "POST",
        body: JSON.stringify({
          trade_plan_id: composer.tradePlan.id,
          symbol: composer.tradePlan.symbol,
          side: ["REDUCE", "CLOSE"].includes(composer.tradePlan.action_type) ? "SELL" : "BUY",
          target_qty: targetQty,
          execution_type: composer.execution_type,
          client_request_id: composer.client_request_id,
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
  const executionReady = brokerConnected && brokerNodeStatus.execution_enabled === true && !brokerNodeStatus.reconciliation_required && brokerNodeStatus.paused !== true && reconciliationIssueCount === 0;
  const composerExchange = composer ? exchangeFromSymbol(composer.tradePlan.symbol) : null;
  const composerOrderType = composer?.execution_params?.order_type || "LIMIT";
  const composerPriceKey = composerOrderType === "LIMIT" ? "limit_price" : "protection_price";
  const composerNeedsPrice = composerOrderType === "LIMIT" || composerExchange === "SH";
  const composerPriceLabel = composerOrderType === "LIMIT" ? "委托限价" : "保护限价";
  return (
    <PageFrame>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-[#0f5238]">EXECUTION DESK</p><h1 className="mt-1 text-3xl font-bold">交易执行 <span className="text-xl font-normal text-[#52616b]">/ Orders & Routing</span></h1><p className="mt-1 text-sm text-[#52616b]">将已确认的 TradePlan 转换为可管理的执行计划。</p></div><div className="grid grid-cols-3 gap-2 text-center"><div className="rounded-xl border border-[#e2ded4] bg-white px-5 py-3"><p className="text-xs text-[#52616b]">活跃执行</p><b className="text-xl text-[#0f5238]">{items.filter((item) => item.status === "ACTIVE").length}</b></div><div className="rounded-xl border border-[#e2ded4] bg-white px-5 py-3"><p className="text-xs text-[#52616b]">已暂停</p><b className="text-xl">{items.filter((item) => item.status === "PAUSED").length}</b></div><div className="rounded-xl border border-[#e2ded4] bg-white px-5 py-3"><p className="text-xs text-[#52616b]">待创建</p><b className="text-xl">{readyPlans.filter((plan) => !executionPlanIds.has(plan.id)).length}</b></div></div></div>
      {!executionReady && (
        <div className="mb-4 flex items-center justify-between gap-4 rounded-xl border border-[#ffb3b3] bg-[#ffdad6] px-5 py-4 text-[#93000a]">
          <div className="flex items-center gap-3"><Cable className="h-7 w-7 shrink-0" /><div><b className="block text-base">{!brokerConnected ? "券商未连接" : reconciliationIssueCount > 0 ? "券商已连接，待处理对账" : brokerNodeStatus.reconciliation_required ? "券商已连接，通道保护中" : brokerNodeStatus.paused ? "当前账号已暂停执行" : "当前暂不可执行"}</b><span className="text-sm">暂不可发送委托；可以保存执行意图、查看记录和完成风险复核。</span></div></div>
          <span className="rounded-lg bg-white px-3 py-2 text-xs font-bold">{!brokerConnected ? "请前往交易设置连接券商" : reconciliationIssueCount > 0 ? `完成 ${reconciliationIssueCount} 项对账后可执行` : brokerNodeStatus.reconciliation_required ? "等待券商通道完成重连校验" : brokerNodeStatus.paused ? "恢复账号执行后可发送委托" : "检查执行权限后重试"}</span>
        </div>
      )}
      {error && <ErrorBox message={error} onRetry={load} />}
      {composer && (
        <Card className="mb-3 border border-[#bdc9d8] bg-[#f4f7fb] p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-bold text-[#354860]">创建执行计划</h2>
              <p className="mt-0.5 text-xs text-[#52616b]">
                {composer.tradePlan.symbol} {composer.tradePlan.security_name} · 目标 {typeof composer.tradePlan.calculation_snapshot_json?.planned_qty === "number" ? composer.tradePlan.calculation_snapshot_json.planned_qty.toLocaleString() : "—"} 股
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
                onChange={(e) => switchComposerType(e.target.value)}
                className="input mt-1"
              >
                <option value="LIMIT">限价委托</option>
                <option value="PERSISTENT_LIMIT">持续限价</option>
                <option value="PRICE_TRIGGER">价格触发</option>
                <option value="PRICE_RANGE">价格区间触发</option>
              </select>
            </label>
            <label className="text-xs font-bold text-[#52616b] sm:col-span-1">
              委托类型
              <select value={composerOrderType} onChange={(e) => changeComposerOrderType(e.target.value)} className="input mt-1">
                {composerExchange && orderTypesForExchange(composerExchange).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            {composerExchange && <p className="text-xs text-[#52616b] sm:col-span-4">{orderTypeDescription(composerOrderType, composerExchange)}</p>}
            {composer.execution_type === "PRICE_RANGE" ? (
              <>
                <label className="text-xs font-bold text-[#52616b]">最低触发价<input type="number" step="0.01" value={composer.execution_params.low_price} onChange={(e) => setComposer((current: any) => ({ ...current, execution_params: { ...current.execution_params, low_price: Number(e.target.value) } }))} className="input mt-1" /></label>
                <label className="text-xs font-bold text-[#52616b]">最高触发价<input type="number" step="0.01" value={composer.execution_params.high_price} onChange={(e) => setComposer((current: any) => ({ ...current, execution_params: { ...current.execution_params, high_price: Number(e.target.value) } }))} className="input mt-1" /></label>
                {composerNeedsPrice && <label className="text-xs font-bold text-[#52616b]">触发后{composerPriceLabel}<input type="number" step="0.01" value={composer.execution_params[composerPriceKey]} onChange={(e) => setComposer((current: any) => ({ ...current, execution_params: { ...current.execution_params, [composerPriceKey]: Number(e.target.value) } }))} className="input mt-1" /></label>}
              </>
            ) : (
              composer.execution_type === "PRICE_TRIGGER" ? (
                <label className="text-xs font-bold text-[#52616b] sm:col-span-1">触发价格<input type="number" step="0.01" value={composer.execution_params.trigger_price} onChange={(e) => setComposer((current: any) => ({ ...current, execution_params: { ...current.execution_params, trigger_price: Number(e.target.value) } }))} className="input mt-1" /></label>
              ) : composerNeedsPrice ? (
                <label className="text-xs font-bold text-[#52616b] sm:col-span-1">{composerPriceLabel}<input type="number" step="0.01" value={composer.execution_params[composerPriceKey]} onChange={(e) => setComposer((current: any) => ({ ...current, execution_params: { ...current.execution_params, [composerPriceKey]: Number(e.target.value) } }))} className="input mt-1" /></label>
              ) : null
            )}
            {composer.execution_type === "PRICE_TRIGGER" && composerNeedsPrice && <label className="text-xs font-bold text-[#52616b]">触发后{composerPriceLabel}<input type="number" step="0.01" value={composer.execution_params[composerPriceKey]} onChange={(e) => setComposer((current: any) => ({ ...current, execution_params: { ...current.execution_params, [composerPriceKey]: Number(e.target.value) } }))} className="input mt-1" /></label>}
            <label className="text-xs font-bold text-[#52616b]">有效期<input type="date" value={composer.valid_until} onChange={(e) => setComposer((current: any) => ({ ...current, valid_until: e.target.value ? `${e.target.value}T23:59:59+08:00` : "" }))} className="input mt-1" /></label>
          </div>
      <div className="mt-3 flex items-center justify-between gap-3">
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
                <div className="min-w-0 text-sm"><b>{plan.symbol} {plan.security_name}</b><span className="ml-2 text-xs text-[#52616b]">计划 {typeof plan.calculation_snapshot_json?.planned_qty === "number" ? plan.calculation_snapshot_json.planned_qty.toLocaleString() : "—"} 股 · 参考 {moneyInput(plan.input_json?.reference_entry_price)}</span></div>
                <button type="button" title="创建执行计划" onClick={() => { const reference = plan.input_json?.reference_entry_price; const limitPrice = typeof reference === "number" && Number.isFinite(reference) && reference > 0 ? reference : undefined; setComposer({ tradePlan: plan, execution_type: "LIMIT", execution_params: { limit_price: limitPrice }, valid_until: "", client_request_id: crypto.randomUUID() }); }} className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-[#354860] px-2.5 py-1.5 text-xs font-bold text-white"><Plus className="h-3.5 w-3.5" />创建执行</button>
              </div>
            ))}
          </div>
        </Card>
      )}
      {loading ? (
        <Card><Loading /></Card>
      ) : items.length ? (
        <div className="space-y-3">
          {items.map((item) => (
            <Card key={item.id} className="border-l-4 border-[#0f5238] p-4">
              <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)_180px]">
                <div>
                  <div className="flex items-center gap-3">
                    <h3 className="text-lg font-bold">{item.symbol}</h3>
                    <span className="rounded bg-[#d9f4e6] px-2 py-1 text-xs font-bold text-[#0e5138]">
                      {sideLabel(item.side)}
                    </span>
                  </div>
                  <div className="mt-2 text-sm text-[#52616b]">
                    {executionTypeLabel(item.execution_type)} · 目标{" "}
                    {item.target_qty == null ? "—" : Number(item.target_qty).toLocaleString()} 股
                  </div>
                  <div className="mt-1 text-xs text-[#354860]">规则：{executionRuleLabel(item)}</div>
                </div>
                <div>
                  <div className="mb-2 flex justify-between text-sm">
                    <span>执行进度</span>
                    <span>
                      {item.filled_qty == null ? "—" : Number(item.filled_qty).toLocaleString()} /{" "}
                      {item.target_qty == null ? "—" : Number(item.target_qty).toLocaleString()}
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-[#e1e3e4]">
                    <div
                      className="h-full rounded-full bg-[#2d6a4f]"
                      style={{
                        width: `${Math.min(100, item.target_qty && item.filled_qty != null ? (Number(item.filled_qty) / Number(item.target_qty)) * 100 : 0)}%`,
                      }}
                    />
                  </div>
                  <div className="mt-2 text-sm text-[#52616b]">
                    剩余：{item.remaining_qty == null ? "—" : Number(item.remaining_qty).toLocaleString()} 股
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
                  {["COMPLETED", "CANCELLED", "CANCELED", "CANCELLED_ORDER", "EXPIRED", "FAILED", "REJECTED"].includes(item.status) ? null : (
                    <button
                      onClick={() => setStatus(item.id, "CANCELLED")}
                      title="取消"
                      className="rounded-full bg-[#f3f4f5] p-3"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
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
  const loadVersion = useRef(0);
  const currentAccountId = useRef(accountId);
  const [loading, setLoading] = useState(true);
  async function load() {
    const version = ++loadVersion.current;
    setLoading(true);
    try {
      const [result, executions, trades, fills] = await Promise.all([request(accountPath("/api/trading/orders", accountId)), request(accountPath("/api/trading/execution-plans", accountId)), request(accountPath("/api/trades", accountId)), request(accountPath("/api/trading/fills", accountId))]);
      const plans = new Map<number, any>();
      (trades.items || []).forEach((trade: any) => (trade.plans || []).forEach((plan: any) => plans.set(plan.id, trade)));
      const executionMap = new Map<number, any>((executions.items || []).map((item: any) => [item.id, item]));
      const fillsByOrder = new Map<number, any[]>();
      (fills.items || []).forEach((fill: any) => fillsByOrder.set(fill.order_id, [...(fillsByOrder.get(fill.order_id) || []), fill]));
      if (version !== loadVersion.current) return;
      setItems((result.items || []).map((order: any) => ({ ...order, fills: fillsByOrder.get(order.id) || [], execution: executionMap.get(order.execution_plan_id), trade: plans.get(executionMap.get(order.execution_plan_id)?.trade_plan_id) })));
      setLoading(false);
    } catch (e) {
      if (version === loadVersion.current) { setError(e instanceof Error ? e.message : "订单读取失败"); setLoading(false); }
    }
  }
  useEffect(() => {
    currentAccountId.current = accountId;
    setItems([]);
    setSelected(null);
    setError(null);
    load();
  }, [accountId]);
  async function cancel(id: number) {
    try {
      await request(accountPath(`/api/trading/orders/${id}/cancel`, accountId), { method: "POST" });
      if (currentAccountId.current !== accountId) return;
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
  const quantityText = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString() : "—";
  const fillPercentText = (item: any) => {
    const quantity = item.quantity;
    const filled = item.filled_quantity;
    if (typeof quantity !== "number" || !Number.isFinite(quantity) || quantity <= 0 || typeof filled !== "number" || !Number.isFinite(filled)) return "—";
    return `${Math.round((filled / quantity) * 100)}%`;
  };
  return (
    <PageFrame>
      <div className="mb-5 flex items-end justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-[#0f5238]">ORDER LEDGER</p><h1 className="mt-1 text-3xl font-bold">订单</h1><p className="mt-1 text-sm text-[#52616b]">以真实委托和成交记录为准，点击详情查看所属单股 与执行计划。</p></div><div className="rounded-xl border border-[#e2ded4] bg-white px-4 py-3 text-sm"><span className="text-[#52616b]">订单总数</span><b className="ml-3 text-xl">{items.length}</b></div></div>
      {error && <ErrorBox message={error} onRetry={load} />}
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-[#dee2e6] bg-[#f8f7f2] px-4 py-3">
          <label className="relative min-w-[220px] flex-1"><span className="sr-only">搜索订单</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索证券、Trade 或订单号" className="w-full rounded-lg bg-white px-3 py-2 text-sm outline-none ring-1 ring-[#dee2e6] focus:ring-[#0f5238]" /></label>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="rounded-lg bg-white px-3 py-2 text-sm ring-1 ring-[#dee2e6] outline-none"><option value="ALL">全部状态</option>{["NEW", "PENDING_NEW", "PENDING_SUBMIT", "QUEUED", "CLAIMED", "DISPATCHING", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "PENDING_CANCEL", "CANCEL_REQUESTED", "CANCELLED", "CANCELLED_ORDER", "CANCELED", "REJECTED", "EXPIRED", "FAILED", "UNKNOWN"].map((value) => <option key={value} value={value}>{statusLabel(value)}</option>)}</select>
          <span className="text-xs text-[#52616b]">显示 {visibleItems.length} / {items.length}</span>
          <button onClick={load} title="刷新订单" aria-label="刷新订单" className="rounded-md p-1.5 text-[#52616b] hover:bg-[#f3f4f5]">
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
        {loading ? (
          <div className="p-6"><Loading /></div>
        ) : visibleItems.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#f3f4f5] text-xs uppercase tracking-wide text-[#404943]">
                <tr>
                  {[
                    "时间",
                    "证券",
                    "所属单股 / 动作",
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
                      {dateTime(item.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <b>{item.symbol}</b>
                      <div className="text-xs text-[#52616b]">
                        {sideLabel(item.side)}
                      </div>
                    </td>
                    <td className="px-4 py-3"><b>{item.trade?.symbol || "—"}</b><div className="text-xs text-[#52616b]">{item.trade ? `${actionLabel(item.trade.action_type)} #${item.trade.sequence_no}` : "未关联单股"}</div></td>
                    <td className="px-4 py-3">{executionTypeLabel(item.order_type || item.execution_type || "")}</td>
                    <td className="px-4 py-3 font-mono">
                      {item.price == null ? "市价" : money(item.price)}
                    </td>
                    <td className="px-4 py-3">
                      {quantityText(item.quantity)}
                    </td>
                    <td className="px-4 py-3">
                      {quantityText(item.filled_quantity)} ({fillPercentText(item)})
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
                      {!["FILLED", "CANCELLED", "CANCELLED_ORDER", "CANCELED", "REJECTED", "EXPIRED", "FAILED"].includes(
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
  return <div className="fixed inset-0 z-[80] flex justify-end bg-black/30" role="dialog" aria-modal="true" aria-label="订单详情"><aside className="h-full w-full max-w-xl overflow-y-auto bg-white p-6 shadow-2xl"><div className="mb-6 flex items-start justify-between"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-[#0f5238]">ORDER DETAIL</p><h2 className="mt-1 text-xl font-bold">{item.symbol} 订单详情</h2><p className="mt-1 text-sm text-[#52616b]">{sideLabel(item.side)} · {statusLabel(item.status)}</p></div><button type="button" onClick={onClose} className="rounded-md px-3 py-1 text-xl hover:bg-[#f3f1eb]" aria-label="关闭">×</button></div><div className="space-y-5"><section><h3 className="mb-2 text-sm font-bold">订单标识</h3><dl className="grid grid-cols-2 gap-3 rounded-lg bg-[#f8f7f2] p-4 text-sm"><div><dt className="text-xs text-[#52616b]">券商订单号</dt><dd className="mt-1 font-mono">{item.broker_order_id || "暂未分配"}</dd></div><div><dt className="text-xs text-[#52616b]">客户端订单号</dt><dd className="mt-1 font-mono">{item.client_order_id || "—"}</dd></div><div><dt className="text-xs text-[#52616b]">委托价格</dt><dd className="mt-1 font-mono">{item.price == null ? "市价" : money(item.price)}</dd></div><div><dt className="text-xs text-[#52616b]">委托数量 / 已成交</dt><dd className="mt-1 font-mono">{item.quantity ?? "—"} / {item.filled_quantity ?? "—"} 股</dd></div></dl></section><section><h3 className="mb-2 text-sm font-bold">成交明细</h3>{item.fills?.length ? <div className="space-y-2 rounded-lg border border-[#e2ded4] p-4 text-sm">{item.fills.map((fill: any) => <div key={fill.id} className="flex justify-between"><span>{dateTime(fill.filled_at || fill.created_at)}</span><b>{money(fill.price)} · {fill.quantity} 股</b></div>)}</div> : <p className="rounded-lg bg-[#f8f7f2] p-4 text-sm text-[#52616b]">该订单暂无成交记录。</p>}</section><section><h3 className="mb-2 text-sm font-bold">交易归属</h3><div className="space-y-2 rounded-lg border border-[#e2ded4] p-4 text-sm"><p><span className="text-[#52616b]">ExecutionPlan：</span>{execution ? `#${execution.id} · ${executionTypeLabel(execution.execution_type)} · ${statusLabel(execution.status)}` : "未关联"}</p><p><span className="text-[#52616b]">TradePlan：</span>{execution?.trade_plan_id ? `#${execution.trade_plan_id}` : "未关联"}</p><p><span className="text-[#52616b]">Trade：</span>{trade ? `#${trade.id} · ${trade.symbol} ${trade.symbol_name || ""}` : "未关联"}</p></div></section></div></aside></div>;
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
  const loadVersion = useRef(0);
  async function load() {
    const version = ++loadVersion.current;
    try {
      const [overview, trades] = await Promise.all([request(accountPath("/api/trading/overview", accountId)), request(accountPath("/api/trades", accountId))]);
      if (version !== loadVersion.current) return;
      setData({ ...overview, trades: trades.items || [] });
    } catch (e) {
      if (version === loadVersion.current) setError(e instanceof Error ? e.message : "持仓读取失败");
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
          <div className="mb-5 flex items-end justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-[#0f5238]">POSITION MONITOR</p><h1 className="mt-1 text-3xl font-bold">持仓</h1><p className="mt-1 text-sm text-[#52616b]">在单股交易中查看持仓、可卖数量与风险参考。</p></div>
            <button
              onClick={() => onNavigate("open")}
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
              const requestVersion = loadVersion.current;
              try {
                const detail = await request(accountPath(`/api/trades/${trade.id}`, accountId));
                if (requestVersion !== loadVersion.current) return;
                const legs = Array.isArray(detail.item?.legs) ? detail.item.legs : [];
                const activeLeg = legs.find((leg: any) => Number(leg.remaining_qty) > 0);
                setRiskAction({ trade, position, legs, current: position.current_risk_reference_price ?? activeLeg?.current_risk_reference_price ?? activeLeg?.initial_risk_reference_price });
              } catch (e) {
                if (requestVersion === loadVersion.current) setError(e instanceof Error ? e.message : "交易风险信息读取失败");
              }
            }} />
          </Card>
          {action && <ActionPlanDialog accountId={accountId} fullPage action={action} onClose={() => setAction(null)} onSaved={async () => { setAction(null); await load(); }} onError={setError} />}
          {riskAction && <RiskReferenceDialog accountId={accountId} tradeId={riskAction.trade.id} legs={riskAction.legs} current={riskAction.current} onClose={() => setRiskAction(null)} onSaved={async () => { setRiskAction(null); await load(); }} onError={setError} />}
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
              "所属单股",
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
              <td className="px-4 py-3">{trade ? <><b>{trade.trade_type === "TREND" ? "趋势交易" : trade.trade_type === "REBOUND" ? "反弹 / 波段" : trade.trade_type === "FIXED_TARGET" ? "固定目标" : "自定义"}</b><div className="text-xs text-[#52616b]">{statusLabel(trade.status)}</div></> : <span className="text-[#52616b]">未关联单股</span>}</td>
              <td className="px-4 py-3">
                {item.quantity == null ? "—" : Number(item.quantity).toLocaleString()}
                <div className="text-xs text-[#52616b]">
                  {item.available_quantity == null ? "—" : Number(item.available_quantity).toLocaleString()}
                </div>
              </td>
              <td className="px-4 py-3">
                {item.average_cost == null ? "—" : Number(item.average_cost).toFixed(2)}
                <div className="font-bold text-[#2d6a4f]">
                  {item.market_price == null ? "—" : Number(item.market_price).toFixed(2)}
                </div>
              </td>
              <td className="px-4 py-3">{money(item.market_value)}</td>
              <td
                className={`px-4 py-3 font-bold ${item.unrealized_pnl >= 0 ? "text-[#2d6a4f]" : "text-[#ae2012]"}`}
              >
                {money(item.unrealized_pnl)}
              </td>
              <td className="px-4 py-3 text-[#0f5238]">
                {Number.isFinite(Number(item.current_risk_reference_price)) ? Number(item.current_risk_reference_price).toFixed(2) : "未设置"}
              </td>
              <td className="px-4 py-3">
                {trade ? <div className="flex flex-wrap gap-2">{onOpenTrade && <button type="button" onClick={() => onOpenTrade(trade.id)} className="text-xs font-bold text-[#0f5238]">查看交易</button>}{canAdd && onAction && <button type="button" onClick={() => onAction({ tradeId: trade.id, symbol: trade.symbol, securityName: trade.symbol_name, type: "ADD" })} className="text-xs font-bold text-[#0f5238]">加仓</button>}{canReduceOrClose && onAction && <><button type="button" onClick={() => onAction({ tradeId: trade.id, symbol: trade.symbol, securityName: trade.symbol_name, type: "REDUCE" })} className="text-xs font-bold text-[#0f5238]">减仓</button><button type="button" onClick={() => onAction({ tradeId: trade.id, symbol: trade.symbol, securityName: trade.symbol_name, type: "CLOSE" })} className="text-xs font-bold text-[#ae2012]">清仓</button></>}{canReduceOrClose && onRisk && <button type="button" onClick={() => onRisk(trade, item)} className="text-xs font-bold text-[#0f5238]">调整风险</button>}</div> : <span className="text-xs text-[#52616b]">请先关联单股</span>}
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

/** Existing settings UI intentionally preserved; it is not part of the visual refactor. */
export function SettingsPage({ accountId, onRefresh, onClose, mode = "trade", openCreateAccount = false, onCreateAccountOpened }: { accountId?: number; onRefresh: () => void; onClose: () => void; mode?: "trade" | "global"; openCreateAccount?: boolean; onCreateAccountOpened?: () => void }) {
  const isGlobal = mode === "global";
  const [data, setData] = useState<any>(null);
  const [dataManagement, setDataManagement] = useState<any>(null);
  const [dataConfig, setDataConfig] = useState<any>(null);
  const [dataSources, setDataSources] = useState<any>(null);
  const [account, setAccount] = useState<any>({});
  const [risk, setRisk] = useState<any>({});
  const [brokerAccounts, setBrokerAccounts] = useState<any[]>([]);
  const [brokerForm, setBrokerForm] = useState<any>({ name: "", icon_key: "landmark", account_type: "SIMULATION", broker: "国投证券掘金", broker_account_id: "", broker_strategy_id: "", broker_gm_token: "" });
  const [brokerDialogOpen, setBrokerDialogOpen] = useState(false);
  const [editingBrokerId, setEditingBrokerId] = useState<number | null>(null);
  const [testingBrokerId, setTestingBrokerId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [settingsSection, setSettingsSection] = useState<"account" | "risk" | "data-management">("account");
  const [dataSection, setDataSection] = useState<"overview" | "schedule" | "tasks">("overview");
  async function load() {
    try {
      if (isGlobal) {
        // The global account editor is backed by the local trading database.
        // Render it as soon as its own request completes instead of making it
        // wait for the unrelated, heavier data-management overview request.
        setError(null);
        setData({});
        const brokerAccountResult = await request("/api/trading/broker-accounts");
        setBrokerAccounts(brokerAccountResult.items || []);
        const [management, sources] = await Promise.all([
          request("/api/screening/data-management"),
          request("/api/screening/data-management/sources"),
        ]);
        setDataManagement(management);
        setDataConfig(management.config.config);
        setDataSources(sources);
        return;
      }
      const [result, brokerAccountResult, riskResult] = await Promise.all([
        request(accountPath("/api/trading/account", accountId as number)),
        request("/api/trading/broker-accounts"),
        request(accountPath("/api/trading/risk-profile", accountId as number)),
      ]);
      setData(result);
      setAccount(result.account || result);
      setRisk(riskResult?.risk_profile || result.risk_profile || {});
      if (brokerAccountResult) setBrokerAccounts(brokerAccountResult.items || []);
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
  useEffect(() => {
    if (!isGlobal || !openCreateAccount || !data) return;
    setSettingsSection("account");
    setBrokerForm({ name: "", icon_key: "landmark", account_type: "SIMULATION", broker: "国投证券掘金", broker_account_id: "", broker_strategy_id: "", broker_gm_token: "" });
    setBrokerDialogOpen(true);
    onCreateAccountOpened?.();
  }, [isGlobal, openCreateAccount, data, onCreateAccountOpened]);
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
      const created = await request("/api/trading/broker-accounts", { method: "POST", body: JSON.stringify(brokerForm) });
      const result = await request("/api/trading/broker-accounts");
      setBrokerAccounts(result.items || []);
      setBrokerDialogOpen(false);
      onRefresh();
      setNotice(`账户已添加，Node 端口 ${created.item?.broker_node_url ? new URL(created.item.broker_node_url).port : "已分配"}`);
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
      onRefresh();
      setNotice(editingBrokerId ? "账户已更新" : "账户已添加");
    } catch (e) { setError(e instanceof Error ? e.message : "账户保存失败"); }
    finally { setBusy(false); }
  }
  function editBrokerProfile(item: any) {
    setBrokerForm({ name: item.name, icon_key: item.icon_key || "landmark", account_type: item.account_type, broker: item.broker, broker_account_id: item.broker_account_id, broker_strategy_id: item.broker_strategy_id, broker_gm_token: item.broker_gm_token });
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
  if (error)
    return (
      <SettingsDialog onClose={onClose} modal={isGlobal}>
        <ErrorBox message={error} onRetry={load} />
      </SettingsDialog>
    );
  if (!data)
    return (
      <SettingsDialog onClose={onClose} modal={isGlobal}>
        <Loading label="正在读取账号设置…" />
      </SettingsDialog>
    );
  if (!isGlobal)
    return (
      <SettingsDialog onClose={onClose}>
        <CurrentAccountSettings account={account} risk={risk} setRisk={setRisk} save={save} accountId={accountId} brokerAccounts={brokerAccounts} />
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
          {!isGlobal && account.account_type !== "PLANNING" && <Card id="execution-hours" className="rounded-xl border border-stone-200/70 bg-white p-5 shadow-sm">
            <div className="mb-4 border-b border-stone-100 pb-3">
              <h2 className="text-base font-bold text-stone-900">交易时段</h2>
              <p className="mt-1 text-xs text-[#52616b]">执行计划会在交易时段内尝试报单；其他时间等到次日委托开始时间。券商回报决定委托是否被接受。</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              {editField("上午开始", "morning_session_start", account, setAccount, "time")}
              {editField("上午结束", "morning_session_end", account, setAccount, "time")}
              {editField("下午开始", "afternoon_session_start", account, setAccount, "time")}
              {editField("下午结束", "afternoon_session_end", account, setAccount, "time")}
              {editField("次日委托开始", "next_day_submission_start", account, setAccount, "time")}
            </div>
          </Card>}
          {!isGlobal && <Card id="broker-accounts" className="rounded-xl border border-stone-200/70 bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <div><div className="flex items-center gap-2"><h2 className="text-base font-bold text-stone-900">券商网关与交易通道</h2><span className="rounded-full bg-stone-100 px-2 py-0.5 text-xs font-mono text-stone-600">已挂载 {brokerAccounts.length} 个实例</span></div><p className="mt-1 text-xs text-[#52616b]">管理仿真策略通道与券商交易连接。</p></div>
              <button type="button" onClick={() => { setBrokerForm({ name: "", icon_key: "landmark", account_type: "SIMULATION", broker: "国投证券掘金", broker_account_id: "", broker_strategy_id: "", broker_gm_token: "" }); setBrokerDialogOpen(true); }} className="inline-flex items-center gap-1 rounded-lg bg-[#2d5a43] px-3.5 py-1.5 text-xs font-medium text-white shadow-sm"><Plus className="h-4 w-4" />添加券商通道</button>
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
              <PercentageField label="单股最大风险预算" fieldKey="max_trade_risk_pct" state={risk} setState={setRisk} />
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
                <button type="button" onClick={() => void refreshDataManagement()} aria-label="刷新数据" title="刷新数据" className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[#c4c8bc] bg-white text-[#354860] shadow-sm hover:bg-stone-50">
                  <RefreshCw className="h-4 w-4" />
                </button>
                <button type="button" onClick={() => void triggerDataSync()} disabled={busy || ["running", "RUNNING"].includes(dataManagement?.live_task?.status)} className="inline-flex items-center gap-1 rounded-lg bg-[#0f5238] px-3 py-2 text-xs font-bold text-white disabled:opacity-50">
                  <Play className="h-3.5 w-3.5" />立即更新
                </button>
                {["running", "RUNNING"].includes(dataManagement?.live_task?.status) && <button type="button" onClick={() => void cancelCurrentTask()} className="inline-flex items-center gap-1 rounded-lg border border-[#a23b3b] bg-white px-3 py-2 text-xs font-bold text-[#a23b3b]"><CirclePause className="h-3.5 w-3.5" />停止任务</button>}
              </div>
            </div>}
            {dataSection === "overview" && <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <DataStatus label="正式日线至" value={dataManagement?.freshness?.official_daily_date || "未知"} />
              <DataStatus label="周线至" value={dataManagement?.freshness?.weekly_market_date || "未知"} />
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
                  <SettingsGroup title="股票分钟行情" description="打开股票 K 线时按需获取当日 30 分钟数据，用于合成当日走势；ETF 仅更新日线。">
                    <ToggleField label="查看股票 K 线时获取当日 30 分钟数据" fieldKey="stock_30m_enabled" state={dataConfig} setState={setDataConfig} />
                  </SettingsGroup>
                  <SettingsGroup title="盘后日线更新" description="收盘后获取当天的日线和相关指标，作为第二天分析使用。">
                    <ToggleField label="每天收盘后自动更新日线" fieldKey="daily_enabled" state={dataConfig} setState={setDataConfig} />
                    <p className="mt-2 text-xs text-[#7a827c]">计划执行时间：{(dataConfig.daily_run_times || []).join("、")}</p>
                  </SettingsGroup>
                  <SettingsGroup title="周线行情更新" description="盘后更新最近一个完整交易周的周线数据，供周线图和技术分类使用。">
                    <ToggleField label="自动更新周线行情" fieldKey="weekly_enabled" state={dataConfig} setState={setDataConfig} />
                    <p className="mt-2 text-xs text-[#7a827c]">使用上方盘后计划执行时间。</p>
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
                <table className="w-full min-w-[620px] text-left text-xs"><thead className="bg-[#f3f4f5] text-[#52616b]"><tr><th className="px-3 py-2">时间</th><th className="px-3 py-2">类型</th><th className="px-3 py-2">日期</th><th className="px-3 py-2">状态</th><th className="px-3 py-2">说明</th></tr></thead><tbody>{(dataManagement?.sync_logs || []).map((item: any) => <tr key={item.id} className="border-t border-[#edf0ef]"><td className="px-3 py-2">{String(item.created_at || "").replace("T", " ").slice(0, 19)}</td><td className="px-3 py-2 font-bold">{item.sync_type}</td><td className="px-3 py-2">{item.trade_date}</td><td className={`px-3 py-2 font-bold ${item.status === "PASS" ? "text-[#0f7a4f]" : "text-[#a23b3b]"}`}>{item.status}</td><td className="max-w-[360px] truncate px-3 py-2 text-[#52616b]" title={item.message || ""}>{item.message || "—"}</td></tr>)}</tbody></table>
                {(dataManagement?.sync_logs || []).length === 0 && <div className="px-4 py-6 text-center text-xs text-[#7a827c]">暂无更新记录</div>}
              </div>
            </div>}
            {dataSection === "tasks" && <div className="mt-5 border-t border-[#dee2e6] pt-4">
              <div className="mb-2 flex items-center justify-between"><h3 className="font-bold">任务历史</h3><span className="text-xs text-[#52616b]">已持久化记录</span></div>
              <div className="overflow-x-auto rounded-lg border border-[#dee2e6]">
                <table className="w-full min-w-[620px] text-left text-xs"><thead className="bg-[#f3f4f5] text-[#52616b]"><tr><th className="px-3 py-2">创建时间</th><th className="px-3 py-2">任务</th><th className="px-3 py-2">状态</th><th className="px-3 py-2">进度</th><th className="px-3 py-2">结果</th></tr></thead><tbody>{(dataManagement?.tasks || []).map((item: any) => <tr key={item.task_id} className="border-t border-[#edf0ef]"><td className="px-3 py-2">{String(item.created_at || "").replace("T", " ").slice(0, 19)}</td><td className="px-3 py-2 font-bold">{item.task_type === "market_data" ? "行情数据更新" : item.task_type}</td><td className={`px-3 py-2 font-bold ${item.status === "SUCCESS" ? "text-[#0f7a4f]" : item.status === "FAILED" ? "text-[#a23b3b]" : "text-[#9a6500]"}`}>{item.status}</td><td className="px-3 py-2">{item.progress}%</td><td className="max-w-[300px] truncate px-3 py-2 text-[#52616b]" title={item.error_message || item.stage_message}>{item.error_message || item.stage_message || "—"}</td></tr>)}</tbody></table>
                {(dataManagement?.tasks || []).length === 0 && <div className="px-4 py-6 text-center text-xs text-[#7a827c]">暂无任务记录</div>}
              </div>
            </div>}
          </Card>}
      </div>
      </div>
      {brokerDialogOpen && <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/35 p-4" role="dialog" aria-modal="true" aria-label={editingBrokerId ? "编辑交易账号" : "创建交易账号"}><div className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-2xl"><div className="mb-5 flex items-center justify-between"><div><h2 className="text-xl font-bold">{editingBrokerId ? "编辑交易账号" : "创建交易账号"}</h2><p className="mt-1 text-xs text-[#52616b]">账号图标只用于识别，不会触发券商连接。</p></div><button type="button" onClick={() => { setBrokerDialogOpen(false); setEditingBrokerId(null); }} className="rounded-lg p-2 text-xl text-[#52616b] hover:bg-[#edf0f3]">×</button></div><div className="grid gap-3 sm:grid-cols-2">{editField("账户名称", "name", brokerForm, setBrokerForm, "text")}{selectField("账户类型", "account_type", brokerForm, setBrokerForm, [["SIMULATION", "仿真账户"], ["LIVE", "实盘账户"]])}<div className="sm:col-span-2"><span className="mb-1 block text-xs font-medium text-[#52616b]">账号图标</span><AccountIconPicker value={brokerForm.icon_key} onChange={(iconKey) => setBrokerForm({ ...brokerForm, icon_key: iconKey })} /></div>{editField("券商", "broker", brokerForm, setBrokerForm, "text")}{editField("账户 ID", "broker_account_id", brokerForm, setBrokerForm, "text")}{editField("策略 ID", "broker_strategy_id", brokerForm, setBrokerForm, "text")}{editField("Node 端口", "broker_node_port", brokerForm, setBrokerForm, "number")}{editField("Token", "broker_gm_token", brokerForm, setBrokerForm, "text")}</div><div className="mt-6 flex justify-end gap-2"><button type="button" onClick={() => { setBrokerDialogOpen(false); setEditingBrokerId(null); }} className="rounded-lg border border-[#c4c8bc] px-4 py-2 text-sm font-bold text-[#52616b]">取消</button><button type="button" onClick={() => void (editingBrokerId ? saveBrokerAccount() : createBrokerAccount())} disabled={busy} className="rounded-lg bg-[#354860] px-4 py-2 text-sm font-bold text-white disabled:opacity-50">{editingBrokerId ? "保存修改" : "保存账号"}</button></div></div></div>}
      {notice && (
        <div className="fixed bottom-5 right-5 z-[80] inline-flex items-center gap-2 rounded-lg bg-[#0f5238] px-4 py-3 text-sm font-bold text-white shadow-[0_8px_24px_rgba(25,28,29,0.18)]" role="status">
          <CheckCircle2 className="h-4 w-4" />
          {notice}
        </div>
      )}
    </SettingsDialog>
  );
}

function CurrentAccountSettings({ account, risk, setRisk, save, accountId, brokerAccounts }: any) {
  const riskField = (label: string, key: string, description: string) => <label className="block rounded-lg border border-stone-200/80 bg-stone-50/80 p-3"><span className="block text-xs font-semibold text-stone-800">{label}</span><span className="mt-1 block text-[11px] text-stone-400">{description}</span><div className="mt-3 flex items-center gap-2"><input type="number" min="0" max="100" step="0.1" value={risk[key] == null ? "" : Number(risk[key]) * 100} onChange={(event) => setRisk({ ...risk, [key]: event.target.value === "" ? null : Number(event.target.value) / 100 })} className="w-full rounded border border-stone-200 bg-white px-2.5 py-1.5 text-sm font-bold outline-none focus:border-[#3a6d50]" /><span className="text-xs text-stone-500">%</span></div></label>;
  const limitField = (label: string, key: string, unit: string, description: string) => <label className="block rounded-lg border border-stone-200/80 bg-stone-50/80 p-3"><span className="block text-xs font-semibold text-stone-800">{label}</span><span className="mt-1 block text-[11px] text-stone-400">{description}</span><div className="mt-3 flex items-center gap-2"><input type="number" min="0" step="1" value={risk[key] ?? ""} onChange={(event) => setRisk({ ...risk, [key]: event.target.value === "" ? null : Number(event.target.value) })} placeholder="不限制" className="w-full rounded border border-stone-200 bg-white px-2.5 py-1.5 text-sm font-bold outline-none focus:border-[#3a6d50]" /><span className="text-xs text-stone-500">{unit}</span></div></label>;
  const currentBroker = brokerAccounts.find((item: any) => item.account_id === accountId);
  const isLiveAccount = account?.account_type === "LIVE";
  return <main className="mx-auto w-full max-w-7xl space-y-5 px-6 py-5" aria-label="当前账号设置">
    <section className="rounded-xl border border-stone-200/70 bg-white p-5 shadow-sm"><div className="flex items-center justify-between border-b border-stone-100 pb-4"><div><h2 className="text-base font-bold text-stone-900">当前账号设置</h2><p className="mt-1 text-xs text-[#52616b]">配置当前选中账号的交易风控和执行规则。</p></div><button type="button" onClick={() => void save()} className="rounded-lg bg-[#2d5a43] px-4 py-2 text-sm font-bold text-white">保存设置</button></div><div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">{riskField("单股最大风险预算", "max_trade_risk_pct", "按账户净资产设定建仓及加仓的计划止损风险额度；跳空和滑点可能导致实际损失更高。")}{riskField("账户总风险预算", "max_account_risk_pct", "限制所有活动单股合计承担的风险")}{riskField("单票最大仓位比例", "max_single_position_pct", "限制单个标的占用的账户资产")}{riskField("最大总仓位比例", "max_total_exposure_pct", "限制全部持仓占用的账户资产")}{limitField("单笔最大数量", "max_single_order_quantity", "股", "超过此数量的委托会被拦截")}{limitField("单笔最大金额", "max_single_order_notional", "元", "超过此金额的委托会被拦截")}{limitField("证券最小申报数量", "min_order_quantity", "股", "OPEN 数量不得低于此数量")}{limitField("证券数量步长 / 交易单位", "quantity_step", "股", "OPEN 数量按此单位向下取整")}</div><div className="mt-4 rounded-lg border border-stone-200/80 bg-stone-50/80 p-3"><div className="flex items-start justify-between gap-4"><div><span className="block text-xs font-semibold text-stone-800">最低现金比例</span><span className="mt-1 block text-[11px] text-stone-400">启用后，交易后账户必须保留指定现金比例，并参与 OPEN 仓位计算。</span></div><label className="inline-flex shrink-0 items-center gap-2 text-xs font-semibold text-stone-700"><input type="checkbox" checked={Boolean(risk.min_cash_ratio_enabled)} onChange={(event) => setRisk({ ...risk, min_cash_ratio_enabled: event.target.checked })} className="h-4 w-4 accent-[#2d5a43]" />启用</label></div><div className="mt-3 flex items-center gap-2"><input type="number" min="0" max="100" step="0.1" value={risk.min_cash_ratio_pct == null ? "" : Number(risk.min_cash_ratio_pct) * 100} onChange={(event) => setRisk({ ...risk, min_cash_ratio_pct: event.target.value === "" ? null : Number(event.target.value) / 100 })} className="w-full rounded border border-stone-200 bg-white px-2.5 py-2 text-sm font-bold outline-none focus:border-[#3a6d50]" placeholder="例如 20" /><span className="text-xs text-stone-500">%</span></div></div><div className="mt-4 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-500">当前总仓位来自账户持仓快照；最低现金比例未启用时不会参与 OPEN 计算。</div></section>
    {isLiveAccount && <NodeSettingsPanel currentBroker={currentBroker} />}
  </main>;
}

function BrokerAccountsPanel({ brokerAccounts, brokerForm, setBrokerForm, setBrokerDialogOpen, busy, testingBrokerId, testBrokerProfile, deleteBrokerProfile, editBrokerProfile }: any) {
  function openAdd() {
    setBrokerForm({ name: "", icon_key: "landmark", account_type: "SIMULATION", broker: "", broker_account_id: "", broker_strategy_id: "", broker_gm_token: "" });
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

const accountIconOptions = [
  ["landmark", Landmark, "规划", "text-emerald-700 bg-emerald-100"],
  ["briefcase", BriefcaseBusiness, "业务", "text-blue-700 bg-blue-100"],
  ["flask", FlaskConical, "仿真", "text-violet-700 bg-violet-100"],
  ["wallet", WalletCards, "资金", "text-amber-700 bg-amber-100"],
  ["chart", ChartNoAxesCombined, "策略", "text-sky-700 bg-sky-100"],
  ["shield", Shield, "风控", "text-rose-700 bg-rose-100"],
  ["building", Building2, "机构", "text-indigo-700 bg-indigo-100"],
  ["coins", Coins, "资产", "text-yellow-700 bg-yellow-100"],
  ["cash", CircleDollarSign, "现金", "text-green-700 bg-green-100"],
  ["monitor", MonitorCog, "终端", "text-cyan-700 bg-cyan-100"],
  ["layers", Layers3, "组合", "text-orange-700 bg-orange-100"],
  ["rocket", Rocket, "增长", "text-fuchsia-700 bg-fuchsia-100"],
  ["gem", Gem, "精选", "text-pink-700 bg-pink-100"],
  ["candlestick", CandlestickChart, "行情", "text-teal-700 bg-teal-100"],
] as const;

function AccountIconPicker({ value, onChange }: { value?: string; onChange: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  const selected = accountIconOptions.find(([key]) => key === value) || accountIconOptions[0];
  const SelectedIcon = selected[1];
  return <div className="relative">
    <button type="button" onClick={() => setOpen((current) => !current)} aria-haspopup="listbox" aria-expanded={open} className="flex h-10 w-full items-center justify-between rounded-lg border border-stone-200 bg-white px-3 text-sm font-medium text-stone-700 hover:border-[#9fc8ae]">
      <span className="flex items-center gap-2"><span className={`flex h-7 w-7 items-center justify-center rounded-md ${selected[3]}`}><SelectedIcon className="h-4 w-4" strokeWidth={1.8} /></span>{selected[2]}</span>
      <ChevronDown className={`h-4 w-4 text-stone-500 transition-transform ${open ? "rotate-180" : ""}`} />
    </button>
    {open && <div role="listbox" aria-label="选择账号图标" className="absolute left-0 top-full z-[100] mt-2 w-full min-w-[260px] rounded-xl border border-stone-200 bg-white p-2 shadow-[0_12px_28px_rgba(46,50,48,0.18)]">
      <div className="grid grid-cols-7 gap-1.5">{accountIconOptions.map(([key, Icon, label, color]) => <button key={key} type="button" role="option" aria-selected={value === key} onClick={() => { onChange(key); setOpen(false); }} title={label} aria-label={label} className={`flex h-10 items-center justify-center rounded-lg ${value === key ? `${color} ring-2 ring-[#2d5a43]` : `${color} opacity-75 hover:opacity-100`}`}><Icon className="h-5 w-5" strokeWidth={1.8} /></button>)}</div>
    </div>}
  </div>;
}

function AccountIconDisplay({ iconKey }: { iconKey?: string | null }) {
  const option = accountIconOptions.find(([key]) => key === iconKey) || accountIconOptions[0];
  const Icon = option[1];
  return <span className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${option[3]}`} aria-hidden="true"><Icon className="h-4 w-4" strokeWidth={1.8} /></span>;
}

function NodeSettingsPanel({ currentBroker }: { currentBroker?: any }) {
  const selected = currentBroker;
  const liveSelected = selected?.account_type === "LIVE";
  const [settings, setSettings] = useState({ allow_live_orders: false });
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!selected || selected.account_type !== "LIVE") return;
    setLoading(true); setMessage(null);
    void request(`/api/trading/broker-accounts/${selected.id}/node-settings`)
      .then((result) => setSettings({ allow_live_orders: Boolean(result.settings?.settings?.allow_live_orders) }))
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
    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="rounded-lg bg-stone-50 px-3 py-2 text-sm font-medium text-stone-700">{liveSelected ? `当前账号：${selected.name}` : "当前实盘账号尚未关联券商配置"}</div>
      <label className="flex items-center justify-between rounded-lg bg-stone-50 px-3 py-2"><span className="text-sm font-medium text-stone-700">允许实盘下单</span><input type="checkbox" checked={liveSelected && settings.allow_live_orders} onChange={(event) => setSettings({ ...settings, allow_live_orders: event.target.checked })} disabled={loading || !liveSelected} className="h-4 w-4 accent-[#0f5238]" /></label>
      <label className="block"><span className="mb-1 block text-xs font-medium text-stone-600">管理员密码</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" placeholder={liveSelected ? "请输入密码确认" : "配置实盘账号后可用"} disabled={!liveSelected} className="w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-[#3a6d50] disabled:bg-stone-100" /></label>
      <div className="flex items-end justify-between gap-3"><p className="text-xs text-stone-500">{liveSelected ? `当前 Node：${selected.broker_node_url || "—"}` : "配置实盘账号后可进行授权设置"}</p><button type="button" onClick={() => void save()} disabled={loading || !liveSelected} className="rounded-lg bg-[#2d5a43] px-4 py-2 text-sm font-bold text-white disabled:opacity-50">{loading ? "保存中…" : "保存授权"}</button></div>
    </div>
    {message && <p className="mt-3 text-xs text-stone-600" role="status">{message}</p>}
  </section>;
}

function ExactTradeSettings({ account, setAccount, risk, setRisk, brokerAccounts, brokerForm, setBrokerForm, setBrokerDialogOpen, busy, testingBrokerId, save, testBrokerProfile, deleteBrokerProfile, editBrokerProfile }: any) {
  const riskMetric = (label: string, key: string, badge: string, description: string, tone = "normal") => { const display = label; const hint = description; return <div className="flex flex-col justify-between rounded-lg border border-stone-200/80 bg-stone-50/80 p-3"><div><div className="flex items-center justify-between"><span className={`text-xs font-semibold ${tone === "danger" ? "text-rose-700" : "text-stone-800"}`}>{display}</span><span className={`rounded px-1.5 py-0.5 text-[10px] font-num ${tone === "danger" ? "bg-rose-100 font-semibold text-rose-700" : tone === "liquidity" ? "bg-emerald-100 text-[#2d5a43]" : "bg-stone-200 text-stone-600"}`}>{badge}</span></div><p className="mt-1 text-[11px] text-stone-400">{hint}</p></div><div className="mt-3 flex items-center gap-2"><input type="number" step="0.1" value={risk[key] == null ? "" : Number(risk[key]) * 100} onChange={(e) => setRisk({ ...risk, [key]: Number(e.target.value) / 100 })} className={`w-full rounded border bg-white px-2.5 py-1 font-mono text-sm font-bold outline-none ${tone === "danger" ? "border-rose-200 text-rose-600 focus:ring-1 focus:ring-rose-500" : "border-stone-200 text-stone-900 focus:ring-1 focus:ring-[#3a6d50]"}`} /><span className="text-xs font-medium text-stone-500 font-num">%</span></div></div>; };
  function resetRisk() {
    setRisk({ ...risk, default_trade_risk_pct: 0.02, max_trade_risk_pct: 0.02, max_single_position_pct: 0.2, max_total_exposure_pct: 0.8 });
  }
  return <main className="trade-settings-reference mx-auto w-full max-w-7xl px-6 py-5" aria-label="交易账户与券商连接设置">
    <section className="rounded-xl border border-stone-200/70 bg-white p-5 shadow-sm"><div className="flex items-center justify-between border-b border-stone-100 pb-4"><div><div className="flex items-center gap-2"><h2 className="text-base font-bold text-stone-900">券商网关与交易通道</h2><span className="rounded-full bg-stone-100 px-2 py-0.5 text-xs font-mono text-stone-600">已挂载 {brokerAccounts.length} 个实例</span></div><p className="mt-0.5 text-xs text-stone-500">管理仿真策略通道与券商实盘交易柜台直连链路，支持单笔心跳检测与报单重连</p></div><button type="button" onClick={() => { setBrokerForm({ name: "", account_type: "SIMULATION", broker: "国投证券掘金", broker_account_id: "", broker_strategy_id: "", broker_node_url: "http://192.168.20.109:18731", broker_gm_token: "" }); setBrokerDialogOpen(true); }} className="inline-flex items-center gap-1 rounded-lg bg-[#2d5a43] px-3.5 py-1.5 text-xs font-medium text-white shadow-sm"><Plus className="h-4 w-4" />添加券商通道</button></div><div className="mt-4 space-y-3">{brokerAccounts.map((item: any) => <div key={item.id} className="rounded-lg border border-stone-200 bg-white p-4 transition-all hover:border-[#3a6d50]/40 hover:shadow-sm"><div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center"><div className="flex-1 space-y-2"><div className="flex flex-wrap items-center gap-2.5"><span className="text-sm font-bold text-stone-900">{item.name}</span><span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">{item.account_type === "SIMULATION" ? "仿真环境" : "实盘环境"}</span><span className="inline-flex items-center gap-1 rounded bg-emerald-50/60 px-2 py-0.5 text-[11px] font-mono text-emerald-600"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />{item.status === "ACTIVE" ? "已配置" : item.status}</span></div><div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs md:grid-cols-6"><div><span className="block text-[11px] text-stone-400">券商渠道</span><span className="font-medium text-stone-700">{item.broker}</span></div><div><span className="block text-[11px] text-stone-400">账户 ID</span><span className="block max-w-[120px] truncate font-mono font-medium text-stone-800" title="账户 ID 已隐藏">{maskAccountIdentifier(item.broker_account_id)}</span></div><div><span className="block text-[11px] text-stone-400">策略 ID</span><span className="block max-w-[120px] truncate font-mono font-medium text-stone-800" title="策略 ID 已隐藏">{maskAccountIdentifier(item.broker_strategy_id)}</span></div><div><span className="block text-[11px] text-stone-400">Token</span><span className="block max-w-[130px] truncate font-mono font-medium text-stone-800" title="Token 已隐藏">{maskToken(item.broker_gm_token)}</span></div><div><span className="block text-[11px] text-stone-400">内部实例别名</span><span className="rounded bg-stone-100 px-1.5 py-0.5 font-mono text-[11px] text-stone-700">{item.broker_account_key}</span></div><div><span className="block text-[11px] text-stone-400">网关 RPC 地址</span><span className="block max-w-[180px] truncate font-mono text-stone-700" title={item.broker_node_url}>{item.broker_node_url}</span></div></div></div><div className="flex shrink-0 items-center gap-2 border-t border-stone-100 pt-2 lg:border-t-0 lg:pt-0"><button type="button" onClick={() => editBrokerProfile(item)} disabled={busy} className="inline-flex items-center gap-1.5 rounded border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs font-medium text-stone-700"><Pencil className="h-3.5 w-3.5 text-stone-500" />编辑</button><button type="button" onClick={() => void testBrokerProfile(item.id)} disabled={busy} className="inline-flex items-center gap-1.5 rounded border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs font-medium text-stone-700"><Zap className={`h-3.5 w-3.5 text-emerald-600 ${testingBrokerId === item.id ? "animate-spin" : ""}`} />{testingBrokerId === item.id ? "测试中" : "测试"}</button><button type="button" onClick={() => void deleteBrokerProfile(item.id)} disabled={busy} className="rounded border border-red-200/80 px-2.5 py-1.5 text-xs text-red-600">删除</button></div></div></div>)}{brokerAccounts.length === 0 && <div className="rounded-lg bg-stone-50 px-4 py-6 text-center text-sm text-stone-500">暂未添加券商账户</div>}</div></section>
    <section className="rounded-xl border border-stone-200/70 bg-white p-5 shadow-sm"><div className="flex items-center justify-between border-b border-stone-100 pb-4"><div className="flex items-center gap-2.5"><div className="rounded border border-rose-100 bg-rose-50 p-1.5 text-rose-600"><Shield className="h-4 w-4" /></div><div><h2 className="text-base font-bold text-stone-900">量化风控规则与前置拦截</h2><p className="text-xs text-stone-500">所有报单将在本地与网关双重校验，超出阈值的委托指令将被直接驳回拦截</p></div></div><span className="text-xs font-semibold text-stone-700">风控引擎已启用</span></div><div className="mt-4 grid grid-cols-1 gap-3.5 md:grid-cols-3 lg:grid-cols-5">{riskMetric("单股最大风险预算", "max_trade_risk_pct", "风险上限", "按账户净资产计算建仓及加仓的计划止损风险额度；跳空和滑点可能导致实际损失更高。", "danger")}{riskMetric("单票最大持仓", "max_single_position_pct", "防集中度", "单个股票标的占用总市值的最高比例限制")}{riskMetric("账户最大总仓位", "max_total_exposure_pct", "总敞口", "全市场股票多头持仓总市值占账户净资产最高限")}{<div className="flex flex-col justify-between rounded-lg border border-stone-200/80 bg-stone-50/80 p-3"><div><div className="flex items-center justify-between"><span className="text-xs font-semibold text-[#2d5a43]">最低现金留存</span><span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-mono text-[#2d5a43]">流动性</span></div><p className="mt-1 text-[11px] text-stone-400">必须保留的可用流动性安全垫，禁止开仓耗尽</p></div><div className="mt-3"><div className="rounded border border-stone-200 bg-white px-2.5 py-1 font-mono text-sm font-bold text-[#2d5a43]">{typeof risk.max_total_exposure_pct === "number" ? `${((1 - risk.max_total_exposure_pct) * 100).toFixed(1)}%` : "—"}</div><div className="mt-1 text-[10px] font-mono text-stone-400">保底安全金</div></div></div>}</div><div className="mt-4 flex flex-col items-center justify-between gap-2 border-t border-stone-100 pt-3 text-xs text-stone-500 sm:flex-row"><div className="flex items-center gap-2"><span className="text-stone-500">提示：风控参数修改后将立即下发至本地交易引擎并写入日志审计，无需重启网关。</span></div><div className="flex items-center gap-2"><button type="button" onClick={resetRisk} className="text-stone-500 underline hover:text-stone-800">重置为保守预设</button><span className="text-stone-300">|</span><button type="button" onClick={() => void save()} className="font-medium text-[#2d5a43]">应用并广播风控规则</button></div></div></section>
  </main>;
}

function BrokerAccountDialog({ brokerForm, setBrokerForm, setBrokerDialogOpen, createBrokerAccount, busy, editing = false }: any) {
  const field = (label: string, key: string, type = "text") => key === "broker_node_port" ? null : <label className="block"><span className="mb-1 block text-xs font-medium text-stone-600">{label}</span><input type={type} value={brokerForm[key] ?? ""} onChange={(e) => setBrokerForm({ ...brokerForm, [key]: e.target.value })} className="w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-[#3a6d50]" /></label>;
  const iconOptions = [["landmark", Landmark, "规划"], ["briefcase", BriefcaseBusiness, "业务"], ["flask", FlaskConical, "仿真"], ["wallet", WalletCards, "资金"], ["chart", ChartNoAxesCombined, "策略"], ["shield", Shield, "风控"]] as const;
  return <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/35 p-4" role="dialog" aria-modal="true" aria-label={editing ? "编辑交易账号" : "创建交易账号"}><div className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-2xl"><div className="mb-5 flex items-center justify-between"><div><h2 className="text-xl font-bold">{editing ? "编辑交易账号" : "创建交易账号"}</h2><p className="mt-1 text-xs text-stone-500">账号图标只用于识别，不会触发券商连接。</p></div><button type="button" onClick={() => setBrokerDialogOpen(false)} className="rounded-lg p-2 text-xl text-stone-500">×</button></div><div className="grid gap-3 sm:grid-cols-2">{field("账户名称", "name")}<label className="block"><span className="mb-1 block text-xs font-medium text-stone-600">账户类型</span><select value={brokerForm.account_type ?? ""} onChange={(e) => setBrokerForm({ ...brokerForm, account_type: e.target.value })} className="w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-[#3a6d50]"><option value="SIMULATION">仿真账户</option><option value="LIVE">实盘账户</option></select></label><div className="sm:col-span-2"><span className="mb-1 block text-xs font-medium text-stone-600">账号图标</span><div className="flex flex-wrap gap-2">{iconOptions.map(([key, Icon, label]) => <button key={key} type="button" onClick={() => setBrokerForm({ ...brokerForm, icon_key: key })} title={label} aria-label={label} className={`flex h-10 w-10 items-center justify-center rounded-lg border ${brokerForm.icon_key === key ? "border-[#2d5a43] bg-[#dcefe3] text-[#2d5a43]" : "border-stone-200 bg-stone-50 text-stone-500 hover:border-[#9fc8ae]"}`}><Icon className="h-5 w-5" strokeWidth={1.8} /></button>)}</div></div>{field("券商", "broker")}{field("账户 ID", "broker_account_id")}{field("策略 ID", "broker_strategy_id")}{field("Node 端口", "broker_node_port", "number")}{field("Token", "broker_gm_token")}</div><div className="mt-6 flex justify-end gap-2"><button type="button" onClick={() => setBrokerDialogOpen(false)} className="rounded-lg border border-stone-200 px-4 py-2 text-sm font-bold text-stone-600">取消</button><button type="button" onClick={() => void createBrokerAccount()} disabled={busy} className="rounded-lg bg-[#2d5a43] px-4 py-2 text-sm font-bold text-white">保存账号</button></div></div></div>;
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
  if (key === "broker_node_port") return null;
  return (
    <label className="block rounded-lg bg-[#f3f4f5] px-2.5 py-2">
      <span className="mb-0.5 block text-[11px] text-[#52616b]">{label}</span>
      <input
        type={type}
        step={type === "number" ? "0.0001" : undefined}
        value={type === "time" && typeof state[key] === "string" ? state[key].slice(0, 5) : state[key] ?? ""}
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
  const groups: [string, string, string[]][] = [["已接入委托类型", "native_orders", capabilities?.native_orders || []], ["条件执行方式", "conditional_execution", capabilities?.conditional_execution || []], ["算法执行方式", "algorithms", capabilities?.algorithms || []]];
  const verified = new Set<string>(capabilities?.verified_order_types || []);
  return <div><div className="grid gap-4 sm:grid-cols-3">{groups.map(([label, key, items]) => <div key={key}><div className="mb-2 text-sm font-bold">{label}</div><div className="flex flex-wrap gap-2">{items.length ? items.map((item) => <span key={item} className={`rounded px-3 py-1 text-xs ${key === "native_orders" && verified.has(item) ? "bg-[#d8f5e5] text-[#12633f]" : "bg-[#edeeef]"}`}>{key === "native_orders" ? orderTypeLabel(item) : item}</span>) : <span className="text-sm text-[#52616b]">连接券商后显示</span>}</div></div>)}</div>{capabilities?.status === "CONNECTED" && <><div className="mt-3 text-xs text-[#52616b]">上交所：{(capabilities.order_types_by_exchange?.SH || []).map(orderTypeLabel).join("、")}<br />深交所：{(capabilities.order_types_by_exchange?.SZ || []).map(orderTypeLabel).join("、")}</div><div className="mt-2 text-xs text-[#52616b]">国投实机已验证：{verified.size ? [...verified].map(orderTypeLabel).join("、") : "暂无"}。其他委托类型已接入 SDK 调用链，需用交易时段仿真账号实测。</div></>}</div>;
}
function EmptyState({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-20 text-center text-[#52616b]">
      <span className="text-[#bfc9c1]">{icon}</span>
      <span>{text}</span>
    </div>
  );
}
function Loading({ label = "正在读取交易数据…" }: { label?: string }) {
  return (
    <div className="py-24 text-center text-sm text-[#52616b]">
      {label}
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
