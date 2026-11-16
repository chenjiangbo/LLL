export type TradingRecord = Record<string, any>;

const LOCAL_OVERVIEW_CACHE_VERSION = 1;

export function readLocalOverviewCache(accountId: number): { data: TradingRecord; cachedAt: string } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(`lll:trading-local-overview:${LOCAL_OVERVIEW_CACHE_VERSION}:${accountId}`);
    if (!raw) return null;
    const cached = JSON.parse(raw);
    const data = cached?.data;
    const collections = ["positions", "trades", "execution_plans", "orders", "fills", "reconciliation_issues"];
    if (cached?.accountId !== accountId || typeof cached.cachedAt !== "string" || Number(data?.account?.id) !== accountId || collections.some((key) => !Array.isArray(data?.[key]))) return null;
    return { data, cachedAt: cached.cachedAt };
  } catch {
    return null;
  }
}

export function writeLocalOverviewCache(accountId: number, data: TradingRecord) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(`lll:trading-local-overview:${LOCAL_OVERVIEW_CACHE_VERSION}:${accountId}`, JSON.stringify({ accountId, cachedAt: new Date().toISOString(), data }));
  } catch {
    // The fresh API response remains authoritative if the browser cannot store a presentation cache.
  }
}

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;

export async function readTradingJson(path: string, accountId: number, init?: RequestInit) {
  if (!API_BASE) throw new Error("交易服务配置不可用，请联系管理员");
  const separator = path.includes("?") ? "&" : "?";
  const response = await fetch(`${API_BASE}${path}${separator}account_id=${encodeURIComponent(String(accountId))}`, {
    ...init,
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`交易数据读取失败（HTTP ${response.status}）`);
  return response.json() as Promise<TradingRecord>;
}

export function money(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : "—";
}

export function numberLabel(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN") : "—";
}

export function dateLabel(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN");
}

export function statusLabel(value: unknown) {
  return ({
    DRAFT: "草稿", READY: "已确认，待安排执行", ARMED: "执行中", PARTIALLY_EXECUTED: "部分成交", EXECUTED: "已成交", INVALIDATED: "已失效",
    ACTIVE: "持仓中", PLANNED: "计划中", CLOSING: "清仓中", CLOSED: "已结束", COMPLETED: "已完成",
    FAILED: "失败", PENDING_SUBMIT: "等待发送", QUEUED: "排队中", SUBMITTED: "已发送", ACCEPTED: "已接受",
    PARTIALLY_FILLED: "部分成交", FILLED: "已成交", CANCEL_PENDING: "撤单中", PENDING_CANCEL: "撤单中",
    CANCEL_REQUESTED: "撤单中", CANCELLED: "已撤单", CANCELED: "已撤单", CANCELLED_ORDER: "已撤单",
    REJECTED: "委托被拒绝", EXPIRED: "已过期", PAUSED: "已暂停，待检查", SUSPENDED: "已暂停，待检查",
  } as Record<string, string>)[String(value)] || String(value || "状态未记录");
}

export function actionLabel(value: unknown) {
  return ({ OPEN: "建仓", ADD: "加仓", REDUCE: "减仓", CLOSE: "清仓" } as Record<string, string>)[String(value)] || "动作";
}

export function sideLabel(value: unknown) {
  return ({ BUY: "买入", SELL: "卖出" } as Record<string, string>)[String(value)] || String(value || "—");
}

export function executionTypeLabel(value: unknown) {
  return ({ LIMIT: "立即提交限价单", PERSISTENT_LIMIT: "持续限价（旧方案）", PRICE_TRIGGER: "达到价格后提交限价单", PRICE_RANGE: "进入价格区间后提交限价单" } as Record<string, string>)[String(value)] || String(value || "执行方式未记录");
}

export function statusTone(value: unknown) {
  const status = String(value || "");
  if (["FAILED", "REJECTED", "CANCELLED", "CANCELED", "CANCELLED_ORDER"].includes(status)) return "danger";
  if (["PAUSED", "SUSPENDED", "PLANNED", "READY", "ARMED"].includes(status)) return "warning";
  if (["FILLED", "COMPLETED", "ACTIVE", "SUBMITTED", "ACCEPTED"].includes(status)) return "success";
  return "neutral";
}

export function canEditTradePlan(item: TradingRecord) {
  const status = String(item.status || "").toUpperCase();
  const executions = Array.isArray(item.execution_plans) ? item.execution_plans : [];
  if (!["DRAFT", "READY"].includes(status)) return false;
  return executions.every((execution: TradingRecord) => {
    if (!["CANCELLED", "EXPIRED"].includes(String(execution.status || "").toUpperCase())) return false;
    const orders = Array.isArray(execution.orders) ? execution.orders : [];
    return orders.every((order: TradingRecord) => {
      const orderStatus = String(order.status || "").toUpperCase();
      const terminal = ["CANCELLED", "CANCELED", "CANCELLED_ORDER", "REJECTED", "FAILED", "EXPIRED"].includes(orderStatus);
      return terminal && Number(order.filled_quantity || 0) === 0 && !(Array.isArray(order.fills) && order.fills.length);
    });
  });
}
