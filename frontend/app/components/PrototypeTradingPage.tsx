"use client";

import { memo, type RefObject, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import KLineModal from "./KLineModal";

export type PrototypePageKey =
  | "overview"
  | "trades"
  | "trade"
  | "risk"
  | "open"
  | "add"
  | "reduce"
  | "close"
  | "action"
  | "execution"
  | "orders"
  | "positions";

const files: Record<PrototypePageKey, string> = {
  overview: "_1",
  trades: "_2",
  risk: "_3",
  trade: "trade",
  open: "open",
  add: "trade_add_1",
  reduce: "trade_reduce_1",
  close: "trade_close",
  action: "action_add_1",
  execution: "executionplan",
  orders: "orders",
  positions: "positions",
};

type Props = {
  page: PrototypePageKey;
  onNavigate: (page: PrototypePageKey, tradeId?: number, planId?: number) => void;
  accountId: number;
  refreshToken?: number;
  marketRealtimeEnabled?: boolean;
  tradeId?: number | null;
  actionPlanId?: number | null;
  onExecutionStatusChange?: (executionPlanId: number, status: string) => void;
  onOrderCancel?: (orderId: number) => void;
  onExitRuleCreate?: (tradeId: number) => void;
  onExitRuleChange?: (tradeId: number, ruleId: number, operation: "edit" | "delete") => void;
  onPauseAll?: () => void;
  onCancelOpenOrders?: () => void;
  onCreateExecutionPlan?: () => void;
  onOrderInspect?: (orderId: number) => void;
  onExecutionOrderInspect?: (executionPlanId: number) => void;
  onCreateTradePlan?: (values: Record<string, string>) => void;
  onActionSubmit?: (page: Extract<PrototypePageKey, "add" | "reduce" | "close">, values: Record<string, string>) => void;
  onRiskReferenceSubmit?: (values: Record<string, string>) => void;
  onOpenSettings?: () => void;
  onRefresh?: () => void;
};
type PrototypeFilter = { status?: string | string[]; side?: string; type?: string; query?: string; tradeId?: number; dateDays?: number; page?: number; pageSize?: number; positionMode?: string };

type InteractiveControlSnapshot = {
  index: number;
  tagName: string;
  type?: string;
  value: string;
  checked?: boolean;
  selectionStart?: number | null;
  selectionEnd?: number | null;
};

type InteractiveStateSnapshot = {
  controls: InteractiveControlSnapshot[];
  focusedIndex: number | null;
};

// 原型页的主体是由后端数据水合后的静态 HTML。筛选、轮询和弹窗状态改变时，
// 绝不能让 React 再把旧 markup 写回这棵 DOM 树，否则浏览器正在编辑的输入值和
// 焦点都会被覆盖。只有 markup 本身或账号切换时才允许此节点重新渲染。
const PrototypeMarkup = memo(function PrototypeMarkup({
  markup,
  accountId,
  contentRef,
}: {
  markup: string;
  accountId: number;
  contentRef: RefObject<HTMLDivElement | null>;
}) {
  return <div ref={contentRef} data-account-id={accountId} dangerouslySetInnerHTML={{ __html: markup }} />;
});

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;

function captureInteractiveState(root: Element): InteractiveStateSnapshot {
  const controls = Array.from(root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>("input, textarea, select"));
  const activeElement = root.ownerDocument.activeElement;
  return {
    focusedIndex: controls.findIndex((control) => control === activeElement),
    controls: controls.map((control, index) => ({
      index,
      tagName: control.tagName,
      type: control instanceof HTMLInputElement ? control.type : undefined,
      value: control.value,
      checked: control instanceof HTMLInputElement ? control.checked : undefined,
      selectionStart: control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement ? control.selectionStart : null,
      selectionEnd: control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement ? control.selectionEnd : null,
    })),
  };
}

function restoreInteractiveState(root: Element, snapshot: InteractiveStateSnapshot) {
  const controls = Array.from(root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>("input, textarea, select"));
  snapshot.controls.forEach((saved) => {
    const control = controls[saved.index];
    if (!control || control.tagName !== saved.tagName) return;
    if (control instanceof HTMLInputElement && saved.type && control.type !== saved.type) return;
    control.value = saved.value;
    if (control instanceof HTMLInputElement && saved.checked !== undefined) control.checked = saved.checked;
  });
  if (snapshot.focusedIndex === null || snapshot.focusedIndex < 0) return;
  const focusedControl = controls[snapshot.focusedIndex];
  if (!focusedControl) return;
  focusedControl.focus({ preventScroll: true });
  const saved = snapshot.controls.find((item) => item.index === snapshot.focusedIndex);
  if (
    saved
    && (focusedControl instanceof HTMLInputElement || focusedControl instanceof HTMLTextAreaElement)
    && saved.selectionStart !== undefined
    && saved.selectionEnd !== undefined
    && saved.selectionStart !== null
    && saved.selectionEnd !== null
  ) {
    focusedControl.setSelectionRange(saved.selectionStart, saved.selectionEnd);
  }
}

async function readApiResponse(response: Response, fallback: string) {
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
    throw new Error(typeof detail === "string"
      ? detail
      : typeof detail?.message === "string"
        ? detail.message
        : `${fallback}（HTTP ${response.status}）`);
  }
  return response.json();
}

function assertAccountScope(payload: any, accountId: number, label: string) {
  const accountValue = payload?.account?.id ?? payload?.account?.account_id ?? payload?.account_id ?? payload?.item?.account_id;
  if (accountValue !== undefined && accountValue !== null && Number(accountValue) !== accountId) {
    throw new Error(`${label}账号数据校验失败，请刷新后重试`);
  }
  return payload;
}

function assertTradingOverview(payload: any, accountId: number) {
  const scoped = assertAccountScope(payload, accountId, "交易总览");
  const requiredCollections = ["positions", "trades", "execution_plans", "orders", "fills", "reconciliation_issues"];
  const requiredAccountFields = ["id", "name", "account_type", "status", "equity", "available_cash"];
  if (!scoped.account || requiredAccountFields.some((key) => !Object.prototype.hasOwnProperty.call(scoped.account, key)) || requiredCollections.some((key) => !Array.isArray(scoped[key]))) {
    throw new Error("交易总览数据不完整，请刷新后重试");
  }
  return scoped;
}

function requireDetailItem(payload: any, label: string, requiredFields: string[] = []) {
  if (!payload || !payload.item || typeof payload.item !== "object" || requiredFields.some((key) => !Object.prototype.hasOwnProperty.call(payload.item, key))) {
    throw new Error(`${label}数据不完整，请刷新后重试`);
  }
  return payload;
}

function requireDetailItems(payload: any, label: string) {
  if (!Array.isArray(payload?.items)) {
    throw new Error(`${label}数据不完整，请刷新后重试`);
  }
  return payload;
}

function textOf(button: Element) {
  return (button.textContent || "").replace(/\s+/g, " ").trim();
}

function prototypeFormValues(root: Element) {
  const values: Record<string, string> = {};
  root.querySelectorAll("input, select, textarea").forEach((element, index) => {
    const input = element as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
    const key = input.getAttribute("data-prototype-field") || input.name || input.id || `${input.tagName.toLowerCase()}_${index}`;
    if ((input as HTMLInputElement).type === "radio" && !(input as HTMLInputElement).checked) return;
    values[key] = input.value || input.getAttribute("data-prototype-value") || "";
  });
  root.querySelectorAll("[data-prototype-field][data-prototype-selected='true']").forEach((element) => {
    const field = element.getAttribute("data-prototype-field");
    const value = element.getAttribute("data-prototype-value");
    if (field && value) values[field] = value;
  });
  return values;
}

function decoratePrototypeFormControls(root: Element, page: PrototypePageKey) {
  const markButtons = (field: string, mapping: Record<string, string>) => {
    root.querySelectorAll("button").forEach((button) => {
      const label = textOf(button);
      const match = Object.keys(mapping).find((text) => label.includes(text));
      if (!match) return;
      button.setAttribute("data-prototype-field", field);
      button.setAttribute("data-prototype-value", mapping[match]);
      if (button.classList.contains("active") || button.classList.contains("bg-primary")) {
        button.setAttribute("data-prototype-selected", "true");
        button.setAttribute("aria-pressed", "true");
      }
    });
  };
  if (page === "open") {
    markButtons("trade_type", { "趋势交易": "TREND", "反弹波段": "REBOUND", "固定目标": "FIXED_TARGET", "自定义": "CUSTOM" });
    root.querySelector("select")?.setAttribute("data-prototype-field", "playbook_id");
    const fields = ["reference_entry_price", "risk_reference_price", "plan_risk_pct", "target_price"];
    root.querySelector("textarea")?.setAttribute("data-prototype-field", "thesis");
    root.querySelectorAll("input").forEach((input, index) => fields[index] && input.setAttribute("data-prototype-field", fields[index]));
  }
  if (page === "risk") {
    root.querySelector("#newRiskPriceInput")?.setAttribute("data-prototype-field", "risk_reference_price");
    root.querySelector("textarea")?.setAttribute("data-prototype-field", "reason_text");
  }
  if (page === "add") {
    const reason = root.querySelector("select");
    reason?.setAttribute("name", "reason_code");
    // The prototype's fifth numeric control is the ADD action-risk budget;
    // it does not expose a manual share quantity control.
    const fields = ["reason_text", "reference_price", "risk_reference_price", "action_risk_budget_amount", "unified_risk_reference_price"];
    root.querySelectorAll("input:not([type='radio'])").forEach((input, index) => fields[index] && input.setAttribute("data-prototype-field", fields[index]));
    root.querySelector("input[name='fail_action']")?.closest("div")?.setAttribute("data-prototype-group", "failure_handling");
    root.querySelector("[onclick*='worst-case-panel']")?.setAttribute("data-prototype-toggle", "worst-case");
  }
  if (page === "reduce") {
    markButtons("reason_code", {
      "主动兑现利润": "PROFIT_TAKING", "达到预设目标": "TARGET_REACHED", "短期趋势转弱": "TREND_WEAKENING",
      "加仓确认失败": "FAILED_ADD", "时间窗口退出": "TIME_EXIT", "总体敞口降险": "RISK_REDUCTION",
    });
    markButtons("reduce_method", { "固定数量": "FIXED_QTY", "持仓比例": "POSITION_PCT", "目标数量": "TARGET_REMAINING_QTY", "目标仓位": "TARGET_REMAINING_PCT" });
    markButtons("quantity", { "25% (75股)": "75", "33% (100股)": "100", "50% (150股)": "150", "最大 (300股)": "300" });
    ["quantity", "reference_price", "minimum_acceptable_price"].forEach((field, index) => {
      const input = Array.from(root.querySelectorAll("input:not([type='radio'])"))[index];
      input?.setAttribute("data-prototype-field", field);
    });
    root.querySelector("textarea")?.setAttribute("data-prototype-field", "reason_text");
    root.querySelectorAll("input[name='residual_mode']").forEach((input, index) => {
      const value = ["KEEP", "NEW_REFERENCE", "MANUAL"][index] || "KEEP";
      input.setAttribute("data-prototype-value", value);
      input.setAttribute("value", value);
    });
  }
  if (page === "close") {
    markButtons("reason_code", {
      "趋势彻底终结": "TREND_WEAKENING", "达终极目标位": "TARGET_REACHED", "触及风控止损": "RISK_REDUCTION",
      "调仓换股分配": "POSITION_CONCENTRATION", "策略逻辑失效": "CUSTOM", "持仓时间耗尽": "TIME_EXIT",
    });
    root.querySelectorAll("input[name='trigger_cond']").forEach((input, index) => {
      const value = index === 0 ? "IMMEDIATE_MARKET_EXIT" : "RISK_LINE_EXIT";
      input.setAttribute("data-prototype-field", "trigger_condition");
      input.setAttribute("data-prototype-value", value);
      input.setAttribute("value", value);
    });
    root.querySelector("textarea")?.setAttribute("data-prototype-field", "reason_text");
  }
  if (["orders", "trades", "positions"].includes(page)) {
    root.querySelectorAll<HTMLElement>("button[onclick*='toggleRow']").forEach((button) => {
      const match = button.getAttribute("onclick")?.match(/toggleRow\(['\"]([^'\"]+)['\"]/);
      if (match?.[1]) button.setAttribute("data-prototype-row-toggle", match[1]);
    });
    root.querySelectorAll<HTMLElement>("button[onclick*='toggleTradeLeg']").forEach((button) => {
      const match = button.getAttribute("onclick")?.match(/toggleTradeLeg\(['\"]([^'\"]+)['\"]/);
      if (match?.[1]) button.setAttribute("data-prototype-row-toggle", match[1]);
    });
  }
}

function replaceStaticKline(root: Element, page: PrototypePageKey) {
  if (!(["open", "trade", "risk"] as PrototypePageKey[]).includes(page)) return;
  root.querySelectorAll("svg").forEach((svg) => {
    const slot = root.ownerDocument.createElement("div");
    slot.className = svg.getAttribute("class") || "h-full w-full";
    slot.setAttribute("data-prototype-kline-slot", "true");
    const message = root.ownerDocument.createElement("div");
    message.className = "flex h-full min-h-[220px] items-center justify-center text-sm text-on-surface-variant";
    message.textContent = "正在加载项目真实 K 线…";
    slot.appendChild(message);
    svg.replaceWith(slot);
  });
}

function formatMoney(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : "—";
}
function sumNumericOrNull(values: unknown[]) {
  if (!values.length) return null;
  if (values.some((value) => typeof value !== "number" || !Number.isFinite(value))) return null;
  return values.reduce<number>((total, value) => total + Number(value), 0);
}
/** TradePlan V2.0 §29-30: calculate current risk from remaining TradeLegs. */
function calculateCurrentTradeRisk(trade: any, position: any) {
  const legs = Array.isArray(trade?.legs) ? trade.legs : [];
  let capitalRisk = 0;
  let givebackRisk = 0;
  let validLegs = 0;
  let incomplete = legs.length === 0;
  for (const leg of legs) {
    const remainingQty = Number(leg.remaining_qty);
    if (!Number.isFinite(remainingQty) || remainingQty < 0) {
      incomplete = true;
      continue;
    }
    if (remainingQty === 0) continue;
    const entryPrice = Number(leg.actual_avg_entry_price ?? leg.planned_entry_price);
    const riskReference = Number(leg.current_risk_reference_price ?? leg.initial_risk_reference_price);
    const marketPrice = Number(position?.market_price);
    if (!Number.isFinite(entryPrice) || !Number.isFinite(riskReference) || riskReference <= 0) {
      incomplete = true;
      continue;
    }
    validLegs += 1;
    capitalRisk += Math.max(0, entryPrice - riskReference) * remainingQty;
    if (!Number.isFinite(marketPrice)) incomplete = true;
    else givebackRisk += Math.max(0, marketPrice - riskReference) * remainingQty;
  }
  if (validLegs === 0) incomplete = true;
  return { capital: incomplete ? null : capitalRisk, giveback: incomplete ? null : givebackRisk, incomplete };
}
function formatDateTime(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}
function businessLabel(value: unknown) {
  return ({
    PLANNED: "计划中", ACTIVE: "进行中", CLOSING: "清仓中", CLOSED: "已结束", CANCELLED: "已取消", CANCELLED_ORDER: "已撤单", CANCELED: "已撤单",
    DRAFT: "草稿", READY: "已确认", ARMED: "已就绪", MONITORING: "监控中", PARTIALLY_EXECUTED: "部分成交", EXECUTED: "已成交", COMPLETED: "已完成", INVALIDATED: "已失效", PAUSED: "已暂停",
    PENDING_SUBMIT: "等待发送", QUEUED: "排队中", CLAIMED: "已接收", DISPATCHING: "发送中", NEW: "已报", PENDING_NEW: "等待报单", SUBMITTED: "已发送", ACCEPTED: "已接受", PARTIALLY_FILLED: "部分成交", FILLED: "已成交", REJECTED: "已拒单", EXPIRED: "已过期", CANCEL_REQUESTED: "撤单中", PENDING_CANCEL: "撤单中", UNKNOWN: "状态未知", FAILED: "失败",
    TREND: "趋势交易", REBOUND: "反弹 / 波段", FIXED_TARGET: "固定目标", CUSTOM: "自定义", BUY: "买入", SELL: "卖出",
    OPEN: "建仓", ADD: "加仓", REDUCE: "减仓", CLOSE: "清仓", OPEN_LONG: "建仓", LIMIT: "限价委托", PERSISTENT_LIMIT: "持续限价", PRICE_TRIGGER: "到价触发", PRICE_RANGE: "价格区间触发",
  } as Record<string, string>)[String(value)] || (value ? "未记录" : "—");
}
function sourceLabel(value: unknown) {
  return ({ MANUAL: "人工创建", STRATEGY: "策略生成", BROKER: "券商回报", IMPORTED: "导入记录", UNKNOWN: "来源未知" } as Record<string, string>)[String(value)] || "来源未知";
}

function replaceExactText(root: Element, from: string, to: string) {
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let current: Node | null = walker.nextNode();
  while (current) {
    if ((current.nodeValue || "").trim() === from) nodes.push(current as Text);
    current = walker.nextNode();
  }
  nodes.forEach((node) => { node.nodeValue = (node.nodeValue || "").replace(from, to); });
}

function replaceTextEverywhere(root: Element, from: string, to: string) {
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let current: Node | null = walker.nextNode();
  while (current) {
    if ((current.nodeValue || "").includes(from)) nodes.push(current as Text);
    current = walker.nextNode();
  }
  nodes.forEach((node) => { node.nodeValue = (node.nodeValue || "").split(from).join(to); });
}

function replaceLeafText(root: Element, pattern: RegExp, replacement: string) {
  root.querySelectorAll("span, p, div").forEach((element) => {
    if (element.children.length > 0) return;
    const value = (element.textContent || "").trim();
    if (!pattern.test(value)) return;
    pattern.lastIndex = 0;
    element.textContent = value.replace(pattern, replacement);
  });
}

function replacePatternEverywhere(root: Element, pattern: RegExp, replacement: string) {
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let current: Node | null = walker.nextNode();
  while (current) {
    if (pattern.test(current.nodeValue || "")) nodes.push(current as Text);
    pattern.lastIndex = 0;
    current = walker.nextNode();
  }
  nodes.forEach((node) => { node.nodeValue = (node.nodeValue || "").replace(pattern, replacement); });
}

function removePrototypeEntities(root: Element, protectedValues: string[] = []) {
  ["安硕信息", "中航电测", "浪潮信息", "北方华创", "赛力斯", "中际旭创", "300380", "300114", "000977", "002371", "601127", "300308"].filter((value) => !protectedValues.includes(value)).forEach((value) => replaceTextEverywhere(root, value, "—"));
}

function relatedTradeExecutionData(detail: { trade: any }, data: any, actionPlanId?: number | null) {
  const allPlans = Array.isArray(detail.trade?.plans) ? detail.trade.plans : [];
  const plans = actionPlanId
    ? allPlans.filter((plan: any) => Number(plan.id) === Number(actionPlanId))
    : allPlans;
  const planIds = new Set(plans.map((plan: any) => Number(plan.id)));
  const executions = Array.from(new Map([
    ...plans.flatMap((plan: any) => Array.isArray(plan.execution_plans) ? plan.execution_plans : []),
    ...(Array.isArray(data.execution_plans) ? data.execution_plans.filter((plan: any) => planIds.has(Number(plan.trade_plan_id))) : []),
  ].map((item: any, index: number) => [Number(item.id) || `execution-${index}`, item])).values());
  const executionIds = new Set(executions.map((execution: any) => Number(execution.id)));
  const orders = Array.from(new Map([
    ...executions.flatMap((execution: any) => Array.isArray(execution.orders) ? execution.orders : []),
    ...(Array.isArray(data.orders) ? data.orders.filter((order: any) => executionIds.has(Number(order.execution_plan_id))) : []),
  ].map((item: any, index: number) => [Number(item.id) || `order-${index}`, item])).values());
  const orderIds = new Set(orders.map((order: any) => Number(order.id)));
  const fills = Array.from(new Map([
    ...orders.flatMap((order: any) => Array.isArray(order.fills) ? order.fills : []),
    ...(Array.isArray(data.fills) ? data.fills.filter((fill: any) => orderIds.has(Number(fill.order_id))) : []),
  ].map((item: any, index: number) => [Number(item.id) || `fill-${index}`, item])).values());
  return { executions, orders, fills };
}

function tradeKlineMarkers(detail: { trade: any }, data: any) {
  const plans = Array.isArray(detail.trade?.plans) ? detail.trade.plans : [];
  return plans.flatMap((plan: any) => {
    const executionData = relatedTradeExecutionData({ trade: { ...detail.trade, plans: [plan] } }, data);
    const fills = executionData.fills;
    return fills.map((fill: any) => ({
      date: String(fill.filled_at || fill.created_at || "").slice(0, 10),
      price: Number.isFinite(Number(fill.price ?? fill.average_fill_price)) ? Number(fill.price ?? fill.average_fill_price) : undefined,
      label: `${businessLabel(plan.action_type || plan.action)} #${plan.sequence_no ?? "—"}`,
      color: plan.action_type === "CLOSE" || plan.action_type === "REDUCE" ? "#b42318" : "#0f766e",
    })).filter((marker: { date: string }) => marker.date);
  });
}

function writeDetailRows(root: Element, page: PrototypePageKey, data: any, detail?: { trade: any; position: any; rules: any[]; history: any[] }, actionPlanId?: number | null) {
  if (!detail?.trade) return;
  const tables = Array.from(root.querySelectorAll("table"));
  const empty = (tbody: Element) => {
    tbody.replaceChildren();
    const row = tbody.ownerDocument.createElement("tr");
    const cell = tbody.ownerDocument.createElement("td");
    cell.colSpan = 12;
    cell.className = "px-4 py-8 text-center text-xs text-on-surface-variant";
    cell.textContent = "当前 Trade 暂无可展示记录";
    row.appendChild(cell);
    tbody.appendChild(row);
  };
  const write = (table: Element, rows: any[], values: (item: any, index: number) => string[]) => {
    const tbody = table.querySelector("tbody");
    const template = tbody?.querySelector(":scope > tr");
    if (!tbody || !template) return;
    if (!rows.length) { empty(tbody); return; }
    tbody.replaceChildren(...rows.map((item, index) => {
      const row = template.cloneNode(true) as HTMLTableRowElement;
      values(item, index).forEach((value, cellIndex) => {
        const cell = row.querySelectorAll("td")[cellIndex];
        if (cell) cell.textContent = value;
      });
      return row;
    }));
  };
  const legs = Array.isArray(detail.trade.legs) ? detail.trade.legs : [];
  if (page === "trade") {
    const finiteNumber = (...values: unknown[]) => {
      for (const value of values) {
        if (value === null || value === undefined || value === "") continue;
        const parsed = Number(value);
        if (Number.isFinite(parsed)) return parsed;
      }
      return null;
    };
    const legValues = (leg: any) => {
      const quantity = finiteNumber(leg.remaining_qty, leg.quantity, leg.entry_qty);
      const averageEntry = finiteNumber(leg.actual_avg_entry_price, leg.average_entry_price, leg.avg_price, leg.planned_entry_price);
      const riskReference = finiteNumber(leg.current_risk_reference_price, leg.initial_risk_reference_price);
      const capitalRisk = finiteNumber(leg.current_capital_risk)
        ?? (quantity !== null && averageEntry !== null && riskReference !== null ? quantity * Math.max(0, averageEntry - riskReference) : null);
      const status = leg.status ? businessLabel(leg.status) : quantity !== null && quantity > 0 ? "持有" : quantity === 0 ? "已结束" : "未记录";
      return { quantity, averageEntry, riskReference, capitalRisk, status };
    };
    write(tables[0], legs, (leg) => {
      const values = legValues(leg);
      return [businessLabel(leg.leg_type || `Leg #${leg.sequence_no || "—"}`), values.quantity === null ? "—" : String(values.quantity), formatMoney(values.averageEntry), formatMoney(values.riskReference), formatMoney(values.capitalRisk), values.status];
    });
    write(tables[1], legs, (leg) => {
      const values = legValues(leg);
      return [businessLabel(leg.leg_type || `Leg #${leg.sequence_no || "—"}`), sourceLabel(leg.source || leg.source_type), values.quantity === null ? "—" : String(values.quantity), formatMoney(values.averageEntry), formatMoney(values.riskReference), values.status, "—"];
    });
  }
  if (page === "action") {
    const { orders, fills } = relatedTradeExecutionData(detail, data, actionPlanId);
    const orderById = new Map<number, any>(orders.map((order: any) => [Number(order.id), order]));
    write(tables[0], fills, (fill) => {
      const order = orderById.get(Number(fill.order_id));
      const feeValues = [fill.commission, fill.tax, fill.other_fee]
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value));
      const totalFee = feeValues.length ? feeValues.reduce((sum, value) => sum + value, 0) : null;
      return [String(fill.id ?? "—"), formatDateTime(fill.filled_at || fill.created_at), order?.broker_order_id || order?.client_order_id || "—", formatMoney(fill.price), String(fill.quantity ?? "—"), formatMoney(totalFee)];
    });
  }
}

function prototypeSectionForHeading(root: Element, heading: string) {
  const headingElement = Array.from(root.querySelectorAll("h1, h2, h3, h4")).find((element) => (element.textContent || "").trim() === heading);
  if (!headingElement) return null;
  let section: Element | null = headingElement.closest("div.bg-surface-container-lowest");
  if (!section) section = headingElement.parentElement;
  while (section && !(section.classList.contains("bg-surface-container-lowest") && (section.classList.contains("rounded-xl") || section.classList.contains("rounded-lg")))) section = section.parentElement;
  return section;
}

function replacePrototypeSection(root: Element, heading: string, message: string) {
  const section = prototypeSectionForHeading(root, heading);
  if (!section) return;
  const headingElement = Array.from(section.querySelectorAll("h1, h2, h3, h4")).find((element) => (element.textContent || "").trim() === heading);
  if (!headingElement) return;
  const headingRow = headingElement.parentElement;
  const empty = root.ownerDocument.createElement("div");
  empty.className = "rounded-lg bg-surface-container-low p-4 text-xs text-on-surface-variant";
  empty.textContent = message;
  section.replaceChildren(headingRow || headingElement, empty);
}

function movePrototypeSection(root: Element, heading: string, destinationHeading: string) {
  const source = prototypeSectionForHeading(root, heading);
  const destination = prototypeSectionForHeading(root, destinationHeading);
  if (!source || !destination || source === destination || !source.parentElement) return;
  source.parentElement.insertBefore(destination, source);
  source.remove();
}

function reconciliationSummary(issues: any[]) {
  if (!issues.length) return "当前账号暂无待处理对账事项。";
  const counts = issues.reduce((result: Record<string, number>, issue: any) => {
    const key = String(issue.issue_type || "OTHER");
    result[key] = (result[key] || 0) + 1;
    return result;
  }, {});
  const parts = [
    ["LOCAL_ORDER_UNCONFIRMED", "本地待确认委托"],
    ["UNMATCHED_BROKER_ORDER_EVENT", "未关联券商委托"],
    ["UNMATCHED_BROKER_FILL", "未关联成交回报"],
  ].filter(([key]) => counts[key]).map(([key, label]) => `${label} ${counts[key as string]} 项`);
  const availableMismatches = issues
    .filter((issue: any) => issue.issue_type === "POSITION_AVAILABLE_QUANTITY_MISMATCH")
    .map((issue: any) => `${issue.symbol || "—"} 可卖数量不一致（系统 ${issue.local_value?.available_quantity ?? "—"} 股，券商 ${issue.broker_value?.available_quantity ?? "—"} 股）`);
  parts.push(...availableMismatches);
  const positionMismatches = issues
    .filter((issue: any) => issue.issue_type === "POSITION_QUANTITY_MISMATCH")
    .map((issue: any) => `${issue.symbol || "—"} 持仓数量不一致（系统 ${issue.local_value?.quantity ?? "—"} 股，券商 ${issue.broker_value?.quantity ?? "—"} 股）`);
  parts.push(...positionMismatches);
  if (counts.OTHER) parts.push(`其他待核对记录 ${counts.OTHER} 项`);
  return `当前账号有 ${issues.length} 项待处理对账事项（${parts.join("、")}）。完成核对前不会发送新的委托。`;
}

function replaceRecentActions(root: Element, orders: any[], fills: any[]) {
  const headingElement = Array.from(root.querySelectorAll("h1, h2, h3, h4")).find((element) => (element.textContent || "").trim() === "最近系统动作");
  if (!headingElement) return;
  let section: Element | null = headingElement.closest("div.bg-surface-container-lowest");
  if (!section) section = headingElement.parentElement;
  while (section && !(section.classList.contains("bg-surface-container-lowest") && (section.classList.contains("rounded-xl") || section.classList.contains("rounded-lg")))) section = section.parentElement;
  if (!section) return;
  const body = root.ownerDocument.createElement("div");
  body.className = "relative space-y-3 pl-3 before:absolute before:bottom-1.5 before:left-1 before:top-1.5 before:w-0.5 before:bg-surface-variant/50";
  const orderKind = (order: any) => {
    const status = String(order.status || "");
    if (["FILLED", "PARTIALLY_FILLED"].includes(status)) return "成交委托";
    if (["CANCELLED", "CANCELED", "CANCELLED_ORDER", "REJECTED", "FAILED", "EXPIRED"].includes(status)) return "撤单 / 拒单";
    return "委托";
  };
  const entries = [
    ...(Array.isArray(orders) ? orders.map((order: any) => ({ kind: orderKind(order), symbol: order.symbol || "—", time: order.updated_at || order.created_at, text: `${businessLabel(order.side)} ${order.quantity ?? "—"} 股 · ${formatMoney(order.price ?? order.limit_price)} · ${businessLabel(order.status)} · ${order.broker_order_id || order.client_order_id || "—"}` })) : []),
    ...(Array.isArray(fills) ? fills.map((fill: any) => ({ kind: "成交回报", symbol: fill.symbol || "—", time: fill.filled_at || fill.created_at, text: `${fill.quantity ?? fill.filled_quantity ?? "—"} 股 @ ${formatMoney(fill.price ?? fill.average_fill_price)} · ${fill.broker_fill_id || "—"}` })) : []),
  ];
  if (!entries.length) {
    body.className = "rounded-lg bg-surface-container-low p-4 text-xs text-on-surface-variant";
    body.textContent = "当前账号暂无订单或成交流水。";
  } else {
    entries.sort((a, b) => String(b.time || "").localeCompare(String(a.time || "")));
    const tagStyles: Record<string, { tag: string; dot: string }> = {
      "委托": { tag: "bg-sky-50 text-sky-800 border border-sky-200", dot: "bg-sky-600" },
      "成交委托": { tag: "bg-emerald-50 text-emerald-800 border border-emerald-200", dot: "bg-emerald-600" },
      "成交回报": { tag: "bg-violet-50 text-violet-800 border border-violet-200", dot: "bg-violet-600" },
      "撤单 / 拒单": { tag: "bg-rose-50 text-rose-800 border border-rose-200", dot: "bg-rose-600" },
    };
    entries.forEach((entry) => {
      const row = root.ownerDocument.createElement("div");
      row.className = "relative flex items-start justify-between gap-2 text-xs";
      const dot = root.ownerDocument.createElement("div");
      dot.className = `absolute -left-[13px] top-1 h-2 w-2 rounded-full ring-2 ring-surface-container-lowest ${tagStyles[entry.kind]?.dot || "bg-slate-500"}`;
      const content = root.ownerDocument.createElement("div");
      content.className = "min-w-0";
      const kind = root.ownerDocument.createElement("div");
      kind.className = "flex items-center gap-1.5";
      const tag = root.ownerDocument.createElement("span");
      tag.className = `rounded px-1.5 py-0.5 text-[10px] font-bold ${tagStyles[entry.kind]?.tag || "bg-slate-100 text-slate-700 border border-slate-200"}`;
      tag.textContent = entry.kind;
      const symbol = root.ownerDocument.createElement("span");
      symbol.className = "font-headline font-medium text-on-surface";
      symbol.textContent = entry.symbol;
      kind.append(tag, symbol);
      const detail = root.ownerDocument.createElement("div");
      detail.className = "mt-1 text-[10px] leading-tight text-on-surface-variant";
      detail.textContent = entry.text;
      content.append(kind, detail);
      const time = root.ownerDocument.createElement("time");
      time.className = "shrink-0 font-mono text-[10px] text-on-surface-variant";
      time.dateTime = String(entry.time || "");
      time.textContent = entry.time ? new Date(entry.time).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).replace(/\//g, "-") : "—";
      row.append(dot, content, time);
      body.appendChild(row);
    });
  }
  section.replaceChildren(headingElement.parentElement || headingElement, body);
}

function replaceOverviewMetrics(root: Element, data: any) {
  const account = data.account || {};
  const riskProfile = data.risk_profile || {};
  const positions = Array.isArray(data.positions) ? data.positions : [];
  const trades = Array.isArray(data.trades) ? data.trades : [];
  const activeTrades = trades.filter((trade: any) => ["ACTIVE", "CLOSING"].includes(String(trade.status)));
  const hasIncompleteRiskReference = activeTrades.some((trade: any) => {
    const legs = Array.isArray(trade.legs) ? trade.legs.filter((leg: any) => Number(leg.remaining_qty ?? leg.quantity ?? 0) > 0) : [];
    return legs.length === 0 || legs.some((leg: any) => {
      const reference = Number(leg.current_risk_reference_price ?? leg.initial_risk_reference_price);
      return !Number.isFinite(reference) || reference <= 0;
    });
  });
  const cards = Array.from(root.querySelectorAll("div.bg-surface-container-lowest.rounded-xl")).filter((card) => Array.from(card.querySelectorAll("span")).some((span) => ["账户净资产", "可用现金", "当前总仓位", "账户当前总风险"].includes((span.textContent || "").trim())));
  const cardFor = (label: string) => cards.find((card) => Array.from(card.querySelectorAll("span")).some((span) => (span.textContent || "").trim() === label));
  const setValue = (card: Element | undefined, value: string) => {
    const target = card?.querySelector(".text-xl") || card?.querySelector(".text-2xl");
    if (target) target.textContent = value;
  };
  const equity = typeof account.equity === "number" ? account.equity : null;
  const availableCash = typeof account.available_cash === "number" ? account.available_cash : null;
  const exposure = typeof account.total_exposure_pct === "number" ? account.total_exposure_pct : null;
  const activeTradeRisks = activeTrades.map((trade: any) => calculateCurrentTradeRisk(trade, positions.find((position: any) => String(position.symbol) === String(trade.symbol))));
  const riskValues: Array<number | null> = activeTradeRisks.map((risk: { capital: number | null }) => risk.capital);
  const plannedRisk = riskValues.length === 0
    ? 0
    : riskValues.every((value) => typeof value === "number" && Number.isFinite(value))
      ? riskValues.reduce((total: number, value: number | null) => total + Number(value), 0)
      : null;
  setValue(cardFor("账户净资产"), formatMoney(equity));
  setValue(cardFor("可用现金"), formatMoney(availableCash));
  setValue(cardFor("当前总仓位"), exposure === null ? "—" : `${(exposure * 100).toFixed(2)}%`);
  setValue(cardFor("账户当前总风险"), formatMoney(plannedRisk));
  const netAssetCard = cardFor("账户净资产");
  const netAssetChange = netAssetCard ? Array.from(netAssetCard.querySelectorAll<HTMLElement>("*")).find((element) => element.classList.contains("gap-1.5")) || null : null;
  if (netAssetChange) netAssetChange.textContent = "当前账号暂无当日资产变动数据";
  const cashCard = cardFor("可用现金");
  if (cashCard) replaceMetricAfterLabel(cashCard, "现金储备比例", equity && availableCash !== null ? `${((availableCash / equity) * 100).toFixed(2)}%` : "—");
  const exposureCard = cardFor("当前总仓位");
  const holdingCount = exposureCard ? Array.from(exposureCard.querySelectorAll<HTMLElement>("*")).find((element) => element.classList.contains("text-[11px]")) || null : null;
  if (holdingCount) holdingCount.textContent = equity === null || exposure === null ? `${positions.length} 只持仓标的` : `持仓市值 ${formatMoney(account.market_value)} · ${positions.length} 只持仓标的`;
  const progress = exposureCard?.querySelector(".bg-tertiary.h-full") as HTMLElement | null;
  if (progress) {
    progress.style.backgroundColor = "#ffffff";
    if (progress.parentElement) progress.parentElement.style.backgroundColor = "rgba(255,255,255,0.34)";
    if (exposure !== null) progress.style.width = `${Math.max(0, Math.min(100, exposure * 100))}%`;
  }
  const riskCard = cardFor("账户当前总风险");
  const riskPct = riskCard?.querySelector(".text-xs.font-semibold");
  if (riskPct) riskPct.textContent = plannedRisk !== null && equity ? `${((plannedRisk / equity) * 100).toFixed(2)}%` : "—";
  // max_trade_risk_pct is a per-Trade limit. The account-wide risk budget is
  // a separate future RiskProfile field and must not be substituted here.
  const accountRiskBudget = typeof riskProfile.max_account_risk_pct === "number" ? riskProfile.max_account_risk_pct : null;
  const budgetLine = riskCard?.querySelector(".flex.items-center.justify-between.mt-1");
  if (budgetLine) budgetLine.textContent = accountRiskBudget === null ? "账户最大风险预算尚未配置" : `预算基准: ${(accountRiskBudget * 100).toFixed(2)}%`;
  const riskProgress = Array.from(root.querySelectorAll("span")).find((span) => (span.textContent || "").trim() === "计划风险进度")?.parentElement;
  if (riskProgress) {
    const riskBlock = riskProgress.parentElement;
    if (riskBlock) {
      (riskBlock as HTMLElement).style.flex = "1 1 100%";
      (riskBlock as HTMLElement).style.width = "100%";
    }
    const line = riskProgress.querySelector(".font-mono");
    if (line) {
      const budgetAmount = accountRiskBudget !== null && equity !== null && equity > 0 ? equity * accountRiskBudget : null;
      line.textContent = plannedRisk === null || budgetAmount === null ? "—" : `${formatMoney(plannedRisk)} / ${formatMoney(budgetAmount)}`;
    }
    const bar = riskProgress.parentElement?.querySelector(".bg-primary.h-full") as HTMLElement | null;
    if (bar) bar.style.width = accountRiskBudget === null || plannedRisk === null || equity === null || equity <= 0 || accountRiskBudget <= 0 ? "0%" : `${Math.max(0, Math.min(100, (plannedRisk / equity) / accountRiskBudget * 100))}%`;

    // The prototype has four metric cards in the first row and places risk
    // progress in a separate panel. It is the fifth metric card and belongs
    // in that same row; move the existing prototype panel instead of
    // recreating its markup.
    const topGrid = cardFor("账户净资产")?.parentElement;
    const riskPanel = riskBlock?.parentElement;
    if (topGrid && riskPanel && !topGrid.contains(riskPanel)) {
      topGrid.classList.remove("lg:grid-cols-4");
      topGrid.classList.add("lg:grid-cols-5");
      riskPanel.classList.remove("lg:col-span-4");
      topGrid.appendChild(riskPanel);
      const warningText = Array.from(root.querySelectorAll("p")).find((element) => (element.textContent || "").includes("部分 Trade 尚未设置有效风险参考"));
      let warningPanel = warningText?.parentElement || null;
      while (warningPanel && !warningPanel.classList.contains("lg:col-span-8")) warningPanel = warningPanel.parentElement;
      if (warningPanel) {
        warningPanel.classList.remove("lg:col-span-8");
        warningPanel.classList.add("lg:col-span-12");
      }
    }
    // Make the fifth card use the exact same DOM hierarchy as the account
    // risk card: title/icon row, amount/percentage row, and supporting line.
    if (riskPanel) {
      const currentRiskPct = plannedRisk !== null && equity !== null && equity > 0 ? `${((plannedRisk / equity) * 100).toFixed(2)}%` : "—";
      const budgetAmount = accountRiskBudget !== null && equity !== null && equity > 0 ? equity * accountRiskBudget : null;
      const budgetText = budgetAmount === null ? "尚未配置账户风险预算" : `预算金额: ${formatMoney(budgetAmount)}`;
      const budgetPctText = accountRiskBudget === null ? "" : `预算比例: ${(accountRiskBudget * 100).toFixed(2)}%`;
      const progressWidth = accountRiskBudget === null || plannedRisk === null || equity === null || equity <= 0 || accountRiskBudget <= 0
        ? 0
        : Math.max(0, Math.min(100, (plannedRisk / equity) / accountRiskBudget * 100));
      riskPanel.className = "rounded-xl border-2 border-[#45677a] bg-[#567a8f] p-3 text-white shadow-sm transition-shadow hover:shadow-md relative overflow-hidden";
      riskPanel.innerHTML = `<div class="mb-1 flex items-center justify-between"><span class="text-xs font-medium text-white">计划风险进度</span><span class="material-symbols-outlined text-white text-[18px]">speed</span></div><div class="text-xl font-bold font-headline text-white tracking-tight">${currentRiskPct}</div><div class="mt-1 flex items-center justify-between text-[11px] text-white/85"><span>${budgetText}</span><span>${budgetPctText}</span></div><div class="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/30"><div class="h-full rounded-full bg-white" style="width: ${progressWidth}%"></div></div>`;
    }
  }
  const exposureProgress = Array.from(root.querySelectorAll("span")).find((span) => (span.textContent || "").trim() === "仓位占用")?.parentElement;
  if (exposureProgress) {
    // “当前总仓位” already displays the current value and its configured
    // limit. Remove the obsolete occupancy block, including its wrapper.
    const exposureBlock = exposureProgress.parentElement;
    if (exposureBlock) exposureBlock.style.display = "none";
    const divider = exposureBlock?.parentElement?.querySelector(".h-6.w-px") as HTMLElement | null;
    if (divider) divider.style.display = "none";
  }
  const warningText = Array.from(root.querySelectorAll("p")).find((element) => (element.textContent || "").includes("部分 Trade 尚未设置有效风险参考"));
  let warning: Element | null = warningText || null;
  while (warning && !(warning.classList.contains("rounded-xl") && warning.classList.contains("bg-surface-container-low"))) warning = warning.parentElement;
  if (warning) (warning as HTMLElement).style.display = hasIncompleteRiskReference ? "" : "none";
}

function replaceDetailList(root: Element, headingPart: string, items: any[], render: (item: any) => string, emptyMessage: string, onRuleActions = false, onPlanActions = false) {
  const headingElement = Array.from(root.querySelectorAll("h1, h2, h3, h4")).find((element) => (element.textContent || "").includes(headingPart));
  if (!headingElement) return;
  let section: Element | null = headingElement.closest("div.bg-surface-container-lowest");
  if (!section) section = headingElement.parentElement;
  while (section && !(section.classList.contains("rounded-xl") || section.classList.contains("rounded-lg"))) section = section.parentElement;
  if (!section) return;
  const body = root.ownerDocument.createElement("div");
  body.className = "space-y-2 text-xs";
  if (items.length) items.forEach((item) => {
    const row = root.ownerDocument.createElement("div");
    row.className = "flex items-center justify-between gap-2 rounded-lg bg-surface-container-low p-3";
    const summary = root.ownerDocument.createElement("span");
    summary.textContent = render(item);
    row.appendChild(summary);
    if (onPlanActions) {
      if (item.id !== undefined) row.setAttribute("data-trade-plan-id", String(item.id));
      const action = root.ownerDocument.createElement("button");
      action.type = "button";
      action.className = "shrink-0 font-semibold text-primary";
      action.textContent = "查看动作详情";
      row.appendChild(action);
    }
    if (onRuleActions && item.id !== undefined) {
      row.setAttribute("data-exit-rule-id", String(item.id));
      const actions = root.ownerDocument.createElement("span");
      actions.className = "flex shrink-0 gap-2";
      const edit = root.ownerDocument.createElement("button");
      edit.type = "button";
      edit.textContent = "编辑";
      const remove = root.ownerDocument.createElement("button");
      remove.type = "button";
      remove.textContent = "删除";
      actions.append(edit, remove);
      row.appendChild(actions);
    }
    body.appendChild(row);
  });
  else {
    body.className = "rounded-lg bg-surface-container-low p-3 text-xs text-on-surface-variant";
    body.textContent = emptyMessage;
  }
  section.replaceChildren(headingElement.parentElement || headingElement, body);
}

function replaceActionTrace(root: Element, detail: { trade: any }, data: any, actionPlanId?: number | null) {
  const heading = Array.from(root.querySelectorAll("h1, h2, h3, h4")).find((element) => (element.textContent || "").includes("全流程 4 级下钻链路 (Action Trace Pipeline)"));
  if (!heading) return;
  let section: Element | null = heading.parentElement?.parentElement?.parentElement || null;
  if (!section) section = heading.parentElement;
  if (!section) return;
  const plans = detail.trade.plans || [];
  const plan = actionPlanId ? plans.find((item: any) => Number(item.id) === Number(actionPlanId)) : plans[plans.length - 1];
  const plansForTrace = plan ? [plan] : plans;
  const planIds = new Set(plansForTrace.map((item: any) => item.id));
  const executions = Array.from(new Map([
    ...plansForTrace.flatMap((item: any) => item.execution_plans || []),
    ...(data.execution_plans || []).filter((item: any) => planIds.has(item.trade_plan_id)),
  ].map((item: any, index: number) => [item.id ?? `${item.trade_plan_id}:${index}`, item])).values());
  const executionIds = new Set(executions.map((item: any) => item.id));
  const orders = Array.from(new Map([
    ...executions.flatMap((item: any) => item.orders || []),
    ...(data.orders || []).filter((item: any) => executionIds.has(item.execution_plan_id)),
  ].map((item: any, index: number) => [item.id ?? `${item.execution_plan_id}:${index}`, item])).values());
  const orderIds = new Set(orders.map((item: any) => item.id));
  const nestedFills = orders.flatMap((item: any) => item.fills || []);
  const accountFills = (data.fills || []).filter((item: any) => actionPlanId
    ? orderIds.has(item.order_id)
    : item.trade_id === detail.trade.id || orderIds.has(item.order_id));
  const fills = Array.from(new Map([...nestedFills, ...accountFills].map((item: any, index: number) => [item.id ?? `${item.order_id}:${item.filled_at}:${index}`, item])).values());
  const body = root.ownerDocument.createElement("div");
  body.className = "mt-3 space-y-2 text-xs";
  const planInput = plan?.input_json || {};
  const planSnapshot = plan?.calculation_snapshot_json || {};
  const planReason = plan?.reason_text || plan?.reason_code || planInput.reason_text || planInput.reason_code || "未填写依据";
  const planRisk = plan?.action_risk_budget_amount ?? planSnapshot.action_risk_budget_amount ?? planInput.action_risk_budget_amount;
  const planExpiry = plan?.expires_at || planInput.expires_at;
  const fillAmount = (item: any) => {
    const directValue = item.amount ?? item.filled_amount;
    const direct = Number(directValue);
    if (directValue !== null && directValue !== undefined && directValue !== "" && Number.isFinite(direct)) return direct;
    const quantity = Number(item.filled_quantity ?? item.quantity);
    const price = Number(item.price ?? item.average_fill_price);
    return Number.isFinite(quantity) && Number.isFinite(price) ? quantity * price : null;
  };
  const cards: Array<[string, string, string]> = [
    ["第 1 层：TradePlan", plan ? `#${plan.id} · 第 ${plan.sequence_no ?? "—"} 个动作 · ${businessLabel(plan.action_type)} · ${businessLabel(plan.status)}` : "当前 Trade 暂无交易计划", plan ? `目标 ${planSnapshot.planned_qty ?? planSnapshot.target_qty ?? planInput.target_qty ?? "—"} 股 · 参考价 ${formatMoney(planInput.reference_entry_price ?? planInput.reference_price)} · 风险预算 ${formatMoney(planRisk)} · 有效期至 ${formatDateTime(planExpiry)} · 创建于 ${formatDateTime(plan.created_at)} · ${planReason}` : "—"],
    ["第 2 层：ExecutionPlan", executions.length ? executions.map((item: any) => `#${item.id} · ${businessLabel(item.status)}`).join("；") : "当前计划暂无执行方案", executions.length ? executions.map((item: any) => `${businessLabel(item.execution_type)} · ${businessLabel(item.side)} · 目标 ${item.target_qty ?? "—"} 股 · ${executionRuleSummary(item.execution_type, item.execution_params_json || item.execution_params || {})} · 有效期至 ${formatDateTime(item.valid_until || item.expires_at)}`).join("；") : "—"],
    ["第 3 层：Order", orders.length ? orders.map((item: any) => `#${item.id} · ${businessLabel(item.status)}`).join("；") : "当前执行方案暂无订单", orders.length ? orders.map((item: any) => `${businessLabel(item.side)} · ${item.quantity ?? "—"} 股 · 委托价 ${formatMoney(item.price ?? item.limit_price)} · ${item.broker_order_id || item.client_order_id || "—"}`).join("；") : "—"],
    ["第 4 层：Fill", fills.length ? `${fills.length} 笔成交回报` : "当前订单暂无成交回报", fills.length ? fills.map((item: any) => `${item.filled_quantity ?? item.quantity ?? "—"} 股 @ ${formatMoney(item.price ?? item.average_fill_price)} · 成交金额 ${formatMoney(fillAmount(item))} · ${formatDateTime(item.filled_at || item.created_at)}`).join("；") : "—"],
  ];
  cards.forEach(([title, state, detailText]) => {
    const card = root.ownerDocument.createElement("div");
    card.className = "rounded-lg bg-surface-container-low p-3";
    const strong = root.ownerDocument.createElement("strong");
    strong.textContent = title;
    const status = root.ownerDocument.createElement("div");
    status.className = "mt-1 font-semibold";
    status.textContent = state;
    const description = root.ownerDocument.createElement("div");
    description.className = "mt-1 text-on-surface-variant";
    description.textContent = detailText;
    card.append(strong, status, description);
    body.appendChild(card);
  });
  section.replaceChildren(heading.parentElement || heading, body);
}

function replaceExecutionMonitor(root: Element, plans: any[], trades: any[] = []) {
  const heading = Array.from(root.querySelectorAll("span, div")).find((element) => (element.textContent || "").trim() === "执行方案监控 (Execution Engine Monitor)");
  if (!heading) return;
  let section: Element | null = heading.parentElement;
  while (section && !(section.classList.contains("bg-surface-container-lowest") && (section.classList.contains("rounded-xl") || section.classList.contains("rounded-lg")))) section = section.parentElement;
  if (!section) return;
  const body = root.ownerDocument.createElement("div");
  body.className = "relative mt-3 ml-2 space-y-4 border-l-2 border-[#c8d8ff] pl-5 text-xs";
  if (!plans.length) {
    body.className = "mt-3 rounded-lg bg-surface-container-low p-4 text-xs text-on-surface-variant";
    body.textContent = "当前账号暂无执行方案。";
  }
  const orderedPlans = [...plans].sort((a, b) => {
    const aTime = new Date(a.created_at || a.updated_at || a.valid_until || 0).getTime();
    const bTime = new Date(b.created_at || b.updated_at || b.valid_until || 0).getTime();
    return aTime - bTime;
  });
  orderedPlans.forEach((plan: any) => {
    const owner = trades.find((trade: any) => (trade.plans || []).some((candidate: any) => candidate.id === plan.trade_plan_id));
    const item = root.ownerDocument.createElement("div");
    item.className = "relative";
    const dot = root.ownerDocument.createElement("span");
    const terminal = ["COMPLETED", "CANCELLED", "CANCELED", "EXPIRED", "FAILED", "REJECTED"].includes(String(plan.status));
    dot.className = `absolute -left-[1.65rem] top-3 h-3 w-3 rounded-full border-2 border-white ${terminal ? "bg-[#7b8794]" : plan.status === "PAUSED" ? "bg-[#d28b25]" : "bg-[#4f82d8]"}`;
    const card = root.ownerDocument.createElement("div");
    card.className = "rounded-xl border border-[#dfe6f0] bg-white p-3 shadow-sm";
    card.setAttribute("data-execution-plan-id", String(plan.id));
    const params = plan.execution_params_json || plan.execution_params || {};
    const price = executionRuleSummary(plan.execution_type, params);
    const title = root.ownerDocument.createElement("div");
    title.className = "flex flex-wrap items-center justify-between gap-2 font-semibold";
    const titleText = root.ownerDocument.createElement("span");
    titleText.textContent = `${plan.symbol || "—"} · Trade #${owner?.id ?? "—"} · ${businessLabel(plan.side)}`;
    const status = root.ownerDocument.createElement("span");
    status.className = "rounded-full border border-[#c8d8ff] bg-[#e8efff] px-2 py-1 text-[10px] font-semibold text-[#315ca8]";
    status.textContent = businessLabel(plan.status);
    title.append(titleText, status);
    const detail = root.ownerDocument.createElement("div");
    detail.className = "mt-1 text-on-surface-variant";
    detail.textContent = `${businessLabel(plan.execution_type)} · 目标 ${plan.target_qty ?? "—"} 股 · ${price} · ExecutionPlan #${plan.id}`;
    const time = root.ownerDocument.createElement("div");
    time.className = "mt-2 text-[10px] text-on-surface-variant";
    time.textContent = formatDateTime(plan.created_at || plan.updated_at || plan.valid_until);
    const actions = root.ownerDocument.createElement("div");
    actions.className = "mt-2 flex flex-wrap gap-2";
    const action = (label: string) => { const button = root.ownerDocument.createElement("button"); button.type = "button"; button.className = "rounded-md bg-surface-container-highest px-2 py-1 font-semibold"; button.textContent = label; return button; };
    if (["ACTIVE", "MONITORING", "ARMED"].includes(plan.status)) actions.appendChild(action("暂停"));
    if (plan.status === "PAUSED") actions.appendChild(action("继续"));
    if (!["COMPLETED", "CANCELLED", "CANCELED", "CANCELLED_ORDER", "EXPIRED", "FAILED", "REJECTED"].includes(plan.status)) actions.appendChild(action("撤销"));
    actions.appendChild(action("查看订单"));
    card.append(title, detail, time, actions);
    item.append(dot, card);
    body.appendChild(item);
  });
  section.replaceChildren(heading.parentElement || heading, body);
}

function executionRuleSummary(executionType: unknown, params: any) {
  if (executionType === "PRICE_RANGE") return `${formatMoney(params.low_price)} - ${formatMoney(params.high_price)} · 触发后限价 ${formatMoney(params.limit_price)}`;
  if (executionType === "PRICE_TRIGGER") return `触发 ${formatMoney(params.trigger_price)} · 触发后限价 ${formatMoney(params.limit_price)}`;
  return formatMoney(params.limit_price);
}

function replaceExecutionChannelStatus(root: Element, data: any) {
  const account = data.account || {};
  const connection = data.broker_status || {};
  const node = connection.node_status || {};
  const connected = connection.status === "CONNECTED" || connection.ok === true;
  const reconciliationIssues = Array.isArray(data.reconciliation_issues) ? data.reconciliation_issues : [];
  const accountExecutionPaused = data.control?.execution_paused === true || Number(data.control?.execution_paused) === 1;
  const status = ["UNAVAILABLE", "DISCONNECTED"].includes(connection.status)
    ? "券商状态暂时无法读取"
    : !connected
    ? "券商通道未连接"
    : node.agent_online === false
      ? "执行器离线"
      : accountExecutionPaused
        ? "当前账号已暂停执行"
      : reconciliationIssues.length > 0
        ? "待处理对账"
        : node.reconciliation_required
          ? "券商通道保护中"
        : node.execution_enabled === false || node.paused
          ? "暂不可执行"
          : "正常在线";
  replaceTextEverywhere(root, "国投仿真", String(account.name || "当前券商账号"));
  replaceTextEverywhere(root, "12ms", "—");
  replaceTextEverywhere(root, "正常在线", status);
}

function decorateExecutionMetricCards(root: Element, data: any) {
  const connection = data.broker_status || {};
  const node = connection.node_status || {};
  const ready = connection.status === "CONNECTED" && node.agent_online !== false && node.execution_enabled !== false && !node.paused;
  const styles: Record<string, [string, string]> = {
    "待执行计划": ["#fff4dc", "#d6a84f"],
    "活跃监控中": ["#eaf0ff", "#9bb7ef"],
    "今日已执行": ["#e7f5eb", "#9dccaa"],
    "执行通道状态": [ready ? "#e7f5eb" : "#fff0ef", ready ? "#9dccaa" : "#e2aaa5"],
  };
  Object.entries(styles).forEach(([label, [background, border]]) => {
    const card = findMetricCard(root, label) as HTMLElement | null;
    if (!card) return;
    card.style.backgroundColor = background;
    card.style.borderLeft = `4px solid ${border}`;
    card.style.boxShadow = "0 2px 8px rgba(43, 55, 72, 0.06)";
  });
}

function replacePositionSummary(root: Element, data: any) {
  const account = data.account || {};
  const positions = Array.isArray(data.positions) ? data.positions : [];
  const trades = Array.isArray(data.trades) ? data.trades : [];
  const exposure = typeof account.total_exposure_pct === "number" ? `${(account.total_exposure_pct * 100).toFixed(2)}%` : "—";
  const maxExposure = typeof data.risk_profile?.max_total_exposure_pct === "number" ? `${(data.risk_profile.max_total_exposure_pct * 100).toFixed(2)}%` : "—";
  const symbols = new Set(positions.map((item: any) => String(item.symbol || "")).filter(Boolean));
  const tradeSymbols = new Set(trades.map((item: any) => String(item.symbol || "")).filter(Boolean));
  const hasCompleteLockData = positions.length > 0 && positions.every((item: any) => [item.quantity, item.available_quantity, item.market_price].every((value) => typeof value === "number" && Number.isFinite(value)));
  const lockedValue = hasCompleteLockData
    ? positions.reduce((total: number, item: any) => total + Math.max(0, item.quantity - item.available_quantity) * item.market_price, 0)
    : null;
  const activeTrades = trades.filter((item: any) => item.status === "ACTIVE").length;
  const asOf = account.updated_at ? new Date(account.updated_at).toLocaleString("zh-CN") : "—";
  const realized = typeof account.realized_pnl === "number" ? formatMoney(account.realized_pnl) : "—";
  const marketValue = typeof account.market_value === "number" ? formatMoney(account.market_value) : "—";
  const riskBudget = typeof data.risk_profile?.max_trade_risk_pct === "number" && typeof account.equity === "number"
    ? formatMoney(account.equity * data.risk_profile.max_trade_risk_pct)
    : "—";
  const marketConnected = data.broker_status?.node_status?.market_connected;
  const marketSessionOpen = data.market_session?.open;
  const marketStatus = ["UNAVAILABLE", "DISCONNECTED"].includes(data.broker_status?.status) || typeof marketConnected !== "boolean"
    ? "行情状态暂时无法读取"
    : marketSessionOpen === false
      ? "当前非交易时段，显示最近一次有效价格"
    : marketConnected
      ? "行情通道已连接，显示最近一次有效价格"
      : "行情通道未连接，显示最近一次有效价格";
  const unrealized = typeof account.unrealized_pnl === "number"
    ? account.unrealized_pnl
    : sumNumericOrNull(positions.map((item: any) => item.unrealized_pnl));
  const costBasis = sumNumericOrNull(positions.map((item: any) => {
    const quantity = Number(item.quantity);
    const cost = Number(item.average_cost ?? item.cost_price);
    return Number.isFinite(quantity) && Number.isFinite(cost) ? quantity * cost : null;
  }));
  const planRisk = sumNumericOrNull(trades.flatMap((trade: any) => (trade.plans || []).map((plan: any) => {
    const value = plan.calculation_snapshot_json?.planned_risk_amount ?? plan.action_risk_budget_amount;
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  })));
  const riskPct = planRisk !== null && typeof account.equity === "number" && account.equity > 0
    ? `${((planRisk / account.equity) * 100).toFixed(2)}% NAV`
    : "暂无数据";
  const availableCash = typeof account.available_cash === "number" ? formatMoney(account.available_cash) : "暂无数据";
  replaceTextEverywhere(root, "T+0实时", "最新有效价格");
  replaceCardMetric(root, "证券总资产 (NAV)", formatMoney(account.equity));
  replaceCardMetric(root, "持仓总市值", marketValue);
  replaceCardMetric(root, "可用现金额度", typeof account.available_cash === "number" ? formatMoney(account.available_cash) : "—");
  setMetricCardValue(root, "证券总资产 (NAV)", formatMoney(account.equity));
  setMetricCardValue(root, "持仓总市值", marketValue);
  setMetricCardValue(root, "可用现金额度", availableCash);
  setMetricCardValue(root, "当前资金总仓位", exposure);
  setMetricCardValue(root, "总计划风险 (Heat)", planRisk === null ? "暂无数据" : formatMoney(planRisk));
  setCardText(root, "证券总资产 (NAV)", "日内", "日内变化：暂无数据");
  setCardText(root, "持仓总市值", "累计浮盈", `累计浮盈 ${unrealized === null ? "暂无数据" : formatMoney(unrealized)}`);
  setCardText(root, "持仓总市值", "成本", `成本 ${costBasis === null ? "暂无数据" : formatMoney(costBasis)}`);
  setCardText(root, "可用现金额度", "可取现", `可取现: ${availableCash}`);
  setCardText(root, "可用现金额度", "备用", typeof account.available_cash === "number" ? "现金数据已加载" : "暂无数据");
  setCardText(root, "总计划风险 (Heat)", "NAV", `${riskPct}`);
  setCardText(root, "总计划风险 (Heat)", "硬止损额度上限", `硬止损额度上限: ${typeof data.risk_profile?.max_account_risk_pct === "number" ? `${(data.risk_profile.max_account_risk_pct * 100).toFixed(2)}%` : "暂无数据"}`);
  setCardText(root, "总计划风险 (Heat)", "利润垫", `利润垫 ${unrealized === null ? "暂无数据" : formatMoney(Math.max(0, unrealized))}`);
  const allocationCard = findMetricCard(root, "当前资金总仓位");
  if (allocationCard) {
    setCardText(root, "当前资金总仓位", "上限", `上限 ${maxExposure}`);
    setCardText(root, "当前资金总仓位", "已占用", `已占用 ${exposure}`);
    setCardText(root, "当前资金总仓位", "剩余可开", `剩余可开 ${maxExposure === "—" || exposure === "—" ? "暂无数据" : `${Math.max(0, Number(maxExposure.replace("%", "")) - Number(exposure.replace("%", ""))).toFixed(2)}%`}`);
    const progress = allocationCard.querySelector(".bg-primary.h-full") as HTMLElement | null;
    if (progress && exposure !== "—") progress.style.width = exposure;
  }
  replaceLabeledStrong(root, "持仓证券合计:", String(symbols.size));
  replaceLabeledStrong(root, "今日已实现收益:", realized);
  replacePatternEverywhere(root, /\d+个标的\s*\/\s*\d+个Trade/g, `${symbols.size}个标的 / ${tradeSymbols.size}个Trade`);
  replacePatternEverywhere(root, /持仓证券合计:\s*—/g, `持仓证券合计: ${symbols.size}`);
  replacePatternEverywhere(root, /标的\s*今日已实现收益:\s*——\.00/g, `标的 今日已实现收益: ${realized}`);
  replacePatternEverywhere(root, /最后同步:\s*[\d:]+/g, `最后同步: ${asOf}`);
  replaceTextEverywhere(root, "A股集中竞价中 (实时双向直连中金/华泰证券)", marketStatus);
  replacePatternEverywhere(root, /可取现:\s*¥—/g, `可取现: ${typeof account.available_cash === "number" ? formatMoney(account.available_cash) : "—"}`);
  replacePatternEverywhere(root, /当前资金总仓位\s+上限\s+—\s+—\s+\/\s+—\s+已占用\s+—\s+剩余可开/g, `当前资金总仓位 上限 ${maxExposure} 已占用 ${exposure} 剩余可开 ${maxExposure === "—" || exposure === "—" ? "—" : `${Math.max(0, Number(maxExposure.replace("%", "")) - Number(exposure.replace("%", ""))).toFixed(2)}%`}`);
  replacePatternEverywhere(root, /NAV 硬止损额度上限:\s*—/g, `NAV 硬止损额度上限: ${riskBudget}`);
  replacePatternEverywhere(root, /已锁定垫\s+—k\s+\/\s+敞口\s+—\s+\(7\.98倍保护\)/g, `已锁定垫 ${lockedValue !== null ? formatMoney(lockedValue) : "—"} / 敞口 ${exposure}（保护倍数暂无）`);
  replacePatternEverywhere(root, /在途锁定市值\s+—\s+\(占比总仓位\s+—\)/g, `在途锁定市值 ${lockedValue !== null ? formatMoney(lockedValue) : "—"}（占比总仓位 ${lockedValue !== null && typeof account.market_value === "number" && account.market_value !== 0 ? `${((lockedValue / account.market_value) * 100).toFixed(2)}%` : "—"}）`);
  replacePatternEverywhere(root, /\d+个 ACTIVE Trade 均已挂接云端保本追踪单/g, activeTrades ? `当前账号有 ${activeTrades} 笔进行中的 Trade` : "当前账号暂无进行中的 Trade");
  replaceTextEverywhere(root, "极度健康", "风险数据已加载");
  const tabCounts: Record<string, number> = {
    "全部持仓": positions.length,
    "多Trade标的": positions.filter((item: any) => trades.filter((trade: any) => trade.symbol === item.symbol).length > 1).length,
    "有在途T+1": positions.filter((item: any) => typeof item.quantity === "number" && typeof item.available_quantity === "number" && item.available_quantity < item.quantity).length,
    "清仓中": trades.filter((trade: any) => trade.status === "CLOSING").length,
  };
  Object.entries(tabCounts).forEach(([label, count]) => {
    replaceButtonCount(root, label, count);
    replacePatternEverywhere(root, new RegExp(`${label}\\s*\\(\\d+\\)`, "g"), `${label} (${count})`);
  });
}

function writeTableRows(root: Element, page: PrototypePageKey, data: any, filter: PrototypeFilter) {
  const table = root.querySelector("table");
  const tbody = table?.querySelector("tbody");
  const template = tbody?.querySelector(":scope > tr");
  if (!table || !tbody || !template) return;
  const positions = Array.isArray(data.positions) ? data.positions : [];
  const source = Array.isArray(page === "orders" ? data.orders : page === "positions" ? positions : data.trades)
    ? (page === "orders" ? data.orders : page === "positions" ? positions : data.trades)
    : [];
  const filteredSource = source.filter((item: any) => {
    const statusValues = Array.isArray(filter.status) ? filter.status : filter.status ? [filter.status] : [];
    const statusMatches = statusValues.length === 0 || statusValues.includes("ALL") || statusValues.includes(item.status);
    const sideMatches = !filter.side || filter.side === "ALL" || item.side === filter.side;
    const relatedExecution = page === "orders"
      ? data.execution_plans?.find((plan: any) => plan.id === item.execution_plan_id)
      : undefined;
    const relatedTrades = (data.trades || []).filter((trade: any) =>
      (page === "trades" && trade.id === item.id)
      || (page === "overview" && trade.id === item.id)
      ||
      trade.id === item.trade_id
      || trade.id === item.trade?.id
      || (relatedExecution?.trade_plan_id !== undefined && (trade.plans || []).some((plan: any) => plan.id === relatedExecution.trade_plan_id))
      || (page === "positions" && trade.symbol === item.symbol),
    );
    const tradeContextMatches = filter.tradeId === undefined || relatedTrades.some((trade: any) => Number(trade.id) === Number(filter.tradeId));
    const typeValue = ({ "全部类型": "ALL", "趋势交易": "TREND", "反弹波段": "REBOUND", "反弹 / 波段": "REBOUND", "固定目标": "FIXED_TARGET", "自定义": "CUSTOM" } as Record<string, string>)[String(filter.type || "")] || filter.type;
    const typeMatches = !typeValue || typeValue === "ALL" || relatedTrades.some((trade: any) =>
      (item.trade_type || trade.trade_type) === typeValue,
    );
    const dateMatches = !filter.dateDays || (() => {
      const createdAt = new Date(item.created_at || item.updated_at || 0).getTime();
      return Number.isFinite(createdAt) && createdAt >= Date.now() - filter.dateDays * 24 * 60 * 60 * 1000;
    })();
    const query = (filter.query || "").trim().toLowerCase();
    const queryMatches = !query || [
      item.symbol,
      item.security_name,
      item.broker_order_id,
      item.client_order_id,
      item.trade_id,
      item.trade?.id,
      item.trade?.symbol,
      item.trade?.symbol_name,
      ...relatedTrades.flatMap((trade: any) => [trade.id, trade.symbol, trade.symbol_name]),
    ].some((value) => String(value ?? "").toLowerCase().includes(query));
    const positionModeMatches = page !== "positions" || !filter.positionMode || filter.positionMode === "ALL"
      || (filter.positionMode === "MULTI" && relatedTrades.length > 1)
      || (filter.positionMode === "T1" && Number(item.available_quantity) < Number(item.quantity))
      || (filter.positionMode === "CLOSING" && relatedTrades.some((trade: any) => trade.status === "CLOSING"));
    return tradeContextMatches && statusMatches && sideMatches && typeMatches && dateMatches && positionModeMatches && queryMatches;
  });
  if (!Array.isArray(filteredSource) || filteredSource.length === 0) {
    tbody.replaceChildren();
    const emptyRow = tbody.ownerDocument.createElement("tr");
    const emptyCell = tbody.ownerDocument.createElement("td");
    emptyCell.colSpan = 12;
    emptyCell.className = "px-4 py-8 text-center text-xs text-on-surface-variant";
    emptyCell.textContent = "当前筛选条件下暂无数据";
    emptyRow.appendChild(emptyCell);
    tbody.appendChild(emptyRow);
    return;
  }
  const pageSize = Math.max(1, Number(filter.pageSize) || 10);
  const pageCount = Math.max(1, Math.ceil(filteredSource.length / pageSize));
  const currentPage = Math.min(Math.max(1, Number(filter.page) || 1), pageCount);
  const pageItems = filteredSource.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const rows = pageItems.map((item: any, index: number) => {
    const row = template.cloneNode(true) as HTMLTableRowElement;
    const execution = page === "orders"
      ? data.execution_plans?.find((candidate: any) => candidate.id === item.execution_plan_id)
      : item;
    const relatedTrades = (data.trades || []).filter((trade: any) =>
      (page === "trades" && trade.id === item.id)
      || (page === "overview" && trade.id === item.id)
      ||
      trade.id === item.trade_id
      || trade.id === item.trade?.id
      || (execution?.trade_plan_id !== undefined && (trade.plans || []).some((plan: any) => plan.id === execution.trade_plan_id))
      || (page === "positions" && trade.symbol === item.symbol),
    );
    const relatedTrade = relatedTrades.length === 1 ? relatedTrades[0] : data.trades?.find((trade: any) =>
      trade.id === item.trade_id || trade.id === item.trade?.id || (execution?.trade_plan_id !== undefined && (trade.plans || []).some((plan: any) => plan.id === execution.trade_plan_id))
    );
    const relatedTradeId = page === "trades" || page === "overview" ? item.id : item.trade_id ?? item.trade?.id ?? relatedTrade?.id;
    if (relatedTradeId !== undefined) row.setAttribute("data-trade-id", String(relatedTradeId));
    if (page === "positions") row.setAttribute("data-trade-count", String(relatedTrades.length));
    if (item.id !== undefined) {
      if (page === "execution") row.setAttribute("data-execution-plan-id", String(item.id));
      if (page === "orders") row.setAttribute("data-order-id", String(item.id));
      if (item.action_type) row.setAttribute("data-action-type", String(item.action_type));
    }
    const position = positions.find((candidate: any) => candidate.symbol === item.symbol);
    const plan = relatedTrade?.plans?.[relatedTrade.plans.length - 1];
    const relatedPlan = data.trades?.flatMap((trade: any) => trade.plans || []).find((candidate: any) => candidate.id === (item.trade_plan_id ?? execution?.trade_plan_id));
    const snapshot = plan?.calculation_snapshot_json || {};
    const marketValue = Number(item.market_value ?? position?.market_value);
    const equity = Number(data.account?.equity);
    const exposureValue = item.position_pct ?? item.exposure_pct;
    const exposure = Number.isFinite(Number(exposureValue))
      ? Number(exposureValue)
      : Number.isFinite(marketValue) && Number.isFinite(equity) && equity !== 0
        ? marketValue / equity
        : null;
    const filledQuantity = item.filled_quantity ?? item.filled_qty;
    const executionParams = item.execution_params_json || item.execution_params || {};
    const executionRule = executionRuleSummary(item.execution_type, executionParams);
    const cells = Array.from(row.querySelectorAll("td"));
    if (page === "overview") {
      const priceCell = row.ownerDocument.createElement("td");
      priceCell.className = "py-2.5 px-3 text-right font-mono";
      cells[4]?.after(priceCell);
      const header = table.querySelector("thead tr");
      if (header && !table.hasAttribute("data-price-column-added")) {
        const exposureHeader = Array.from(header.querySelectorAll("th")).find((cell) => (cell.textContent || "").trim() === "资金仓位");
        if (exposureHeader) {
          const priceHeader = table.ownerDocument.createElement("th");
          priceHeader.className = "py-2.5 px-3 text-right";
          priceHeader.textContent = "当前价 / 买入价";
          exposureHeader.after(priceHeader);
          table.setAttribute("data-price-column-added", "true");
        }
      }
      const recentActionHeader = Array.from(table.querySelectorAll("thead th")).find((cell) => (cell.textContent || "").trim() === "最近动作");
      if (recentActionHeader) recentActionHeader.remove();
      const recentActionCell = cells[8];
      if (recentActionCell) recentActionCell.remove();
    }
    const rowCells = Array.from(row.querySelectorAll("td"));
    const overviewRisk = page === "overview" && relatedTrade ? calculateCurrentTradeRisk(relatedTrade, position) : null;
    const positionTradeType = relatedTrades.length > 1
      ? "多个 Trade"
      : relatedTrades.length === 1
        ? businessLabel(relatedTrade?.trade_type)
        : "未关联 Trade";
    const positionTradeStatus = relatedTrades.length > 1
      ? "多个 Trade"
      : relatedTrades.length === 1
        ? businessLabel(relatedTrade?.status)
        : "未关联 Trade";
    const tradeRisk = page === "trades" && relatedTrade ? calculateCurrentTradeRisk(relatedTrade, position) : null;
    const positionRisk = page === "positions" && relatedTrades.length === 1 && relatedTrade ? calculateCurrentTradeRisk(relatedTrade, item) : null;
    const values = page === "positions"
      ? [String(index + 1), `${item.security_name || item.symbol || "—"} / ${item.symbol || "—"}`, positionTradeType, positionTradeStatus, `持仓 ${item.quantity ?? "—"} 股 / 可卖 ${item.available_quantity ?? "—"} 股`, `${formatMoney(item.average_cost)} / ${formatMoney(item.market_price)}`, formatMoney(item.unrealized_pnl), exposure === null ? "—" : `${(exposure * 100).toFixed(2)}%`, formatMoney(positionRisk?.capital ?? item.current_capital_risk ?? (relatedTrades.length === 1 ? relatedTrade?.trade_risk_budget_amount ?? snapshot.planned_risk_amount : null)), formatMoney(positionRisk?.giveback ?? item.current_giveback_risk ?? (item.quantity === 0 ? 0 : null)), formatMoney(item.current_risk_reference_price ?? item.position_risk_reference_price ?? position?.current_risk_reference_price ?? position?.position_risk_reference_price)]
      : page === "orders"
        ? [formatDateTime(item.created_at || item.updated_at), item.symbol || "—", relatedTrade?.id ? `Trade #${relatedTrade.id}` : "—", businessLabel(item.action_type || relatedPlan?.action_type), businessLabel(item.side), businessLabel(item.order_type || item.execution_type), formatMoney(item.average_fill_price ?? item.limit_price ?? item.price), `${item.quantity ?? item.target_qty ?? "—"} / ${filledQuantity == null ? "—" : Number(filledQuantity).toLocaleString()}`, businessLabel(item.status), item.broker_order_id || item.client_order_id || "—"]
        : page === "execution"
          ? [`${item.symbol || "—"}`, businessLabel(item.action_type || relatedPlan?.action_type), `${businessLabel(item.side)} ${item.target_qty ?? item.quantity ?? "—"}`, executionRule, businessLabel(item.status)]
          : page === "overview"
            ? [`${item.symbol || "—"} ${item.symbol_name || item.security_name || ""}`.trim(), businessLabel(item.trade_type), businessLabel(item.status), `持仓 ${position?.quantity ?? "—"} 股 / 可卖 ${position?.available_quantity ?? "—"} 股`, Number.isFinite(marketValue) && Number.isFinite(equity) && equity !== 0 ? `${((marketValue / equity) * 100).toFixed(2)}%` : "—", `${formatMoney(position?.market_price)} / ${formatMoney(position?.average_cost)}`, formatMoney(position?.unrealized_pnl), formatMoney(overviewRisk?.capital), formatMoney(overviewRisk?.giveback)]
            : [`${item.symbol || "—"} ${item.symbol_name || item.security_name || ""}`.trim(), businessLabel(item.trade_type), businessLabel(item.status), `持仓 ${position?.quantity ?? "—"} 股 / 可卖 ${position?.available_quantity ?? "—"} 股`, `${formatMoney(position?.market_price)} / ${formatMoney(position?.average_cost)}`, formatMoney(position?.unrealized_pnl), formatMoney(tradeRisk?.capital ?? item.current_capital_risk ?? snapshot.planned_risk_amount ?? item.capital_risk), formatMoney(tradeRisk?.giveback ?? item.current_giveback_risk ?? position?.current_giveback_risk ?? item.profit_retrace_risk ?? (position?.quantity === 0 ? 0 : null)), formatDateTime(item.created_at)];
    if (page === "trades") {
      // Do not clone the prototype row structure here. It contains a fixture-only
      // “最近动作” column that does not exist in the header; cloning it again on
      // every filter update shifts 创建时间 / 操作 and eventually deletes 详情.
      // Build the ten actual columns directly so filtering remains idempotent.
      row.replaceChildren();
      const cellClasses = [
        "py-3 pl-4 pr-2",
        "py-3 px-2",
        "py-3 px-2",
        "py-3 px-2 text-right font-mono",
        "py-3 px-2 text-right font-mono",
        "py-3 px-2 text-right font-mono",
        "py-3 px-2 text-right font-mono",
        "py-3 px-2 text-right font-mono",
        "py-3 px-2 font-mono text-[11px] text-on-surface-variant",
      ];
      values.forEach((value, cellIndex) => {
        const cell = row.ownerDocument.createElement("td");
        cell.className = cellClasses[cellIndex] || "py-3 px-2";
        cell.textContent = String(value ?? "—");
        row.appendChild(cell);
      });
      const operationCell = row.ownerDocument.createElement("td");
      operationCell.className = "py-3 pr-4 pl-2 text-right";
      const detailButton = row.ownerDocument.createElement("button");
      detailButton.type = "button";
      detailButton.className = "rounded px-1.5 py-0.5 text-xs font-semibold text-primary transition-colors hover:bg-primary-fixed/40 hover:underline";
      detailButton.textContent = "详情";
      operationCell.appendChild(detailButton);
      row.appendChild(operationCell);
      return row;
    }
    if (page === "positions") {
      const positionValues = [String(index + 1), `${item.security_name || item.symbol || "—"} / ${item.symbol || "—"}`, positionTradeType, positionTradeStatus, `${item.quantity ?? "—"} / ${item.available_quantity ?? "—"}`, `${formatMoney(item.average_cost)} / ${formatMoney(item.market_price)}`, formatMoney(item.unrealized_pnl), exposure === null ? "—" : `${(exposure * 100).toFixed(2)}%`, formatMoney(positionRisk?.capital ?? item.current_capital_risk ?? (relatedTrades.length === 1 ? relatedTrade?.trade_risk_budget_amount ?? snapshot.planned_risk_amount : null)), formatMoney(positionRisk?.giveback ?? item.current_giveback_risk ?? (item.quantity === 0 ? 0 : null)), formatMoney(item.current_risk_reference_price ?? item.position_risk_reference_price ?? position?.current_risk_reference_price ?? position?.position_risk_reference_price)];
      positionValues.forEach((value, cellIndex) => { if (cells[cellIndex]) cells[cellIndex].textContent = value; });
    }
    if (page !== "positions") rowCells.slice(0, values.length).forEach((cell, cellIndex) => {
      cell.textContent = String(values[cellIndex] ?? "—");
    });
    if (page === "overview" && cells[0]) {
      const code = String(item.symbol || "—");
      const name = String(item.symbol_name || item.security_name || "");
      cells[0].replaceChildren();
      const codeElement = cells[0].ownerDocument.createElement("span");
      codeElement.textContent = code;
      codeElement.setAttribute("data-copy-stock-code", code);
      codeElement.setAttribute("title", `点击复制股票代码 ${code}`);
      codeElement.className = "mr-2 cursor-copy font-bold underline decoration-dotted underline-offset-2";
      const nameElement = cells[0].ownerDocument.createElement("span");
      nameElement.textContent = name;
      nameElement.setAttribute("data-copy-stock-code", code);
      nameElement.setAttribute("title", `点击复制股票代码 ${code}`);
      nameElement.className = "cursor-pointer";
      cells[0].append(codeElement, nameElement);
    }
    return row;
  });
  tbody.replaceChildren(...rows);
  const totalValue = Array.from(root.querySelectorAll("strong")).find((element) => (element.parentElement?.textContent || "").includes("笔交易"));
  if (totalValue) totalValue.textContent = String(filteredSource.length);
  const pageText = Array.from(root.querySelectorAll("span")).find((element) => /第\s*\d+\s*\/\s*\d+\s*页/.test(element.textContent || ""));
  if (pageText) pageText.textContent = `第 ${Math.min(currentPage, pageCount)} / ${pageCount} 页`;
  if (page === "trades") table.setAttribute("data-page-count", String(pageCount));
  root.querySelectorAll("[data-trades-pagination]").forEach((element) => {
    element.setAttribute("data-total", String(filteredSource.length));
    element.setAttribute("data-page-count", String(pageCount));
  });
}

function syncTradeListControlState(root: Element, data: any, filter: PrototypeFilter) {
  const trades = Array.isArray(data.trades) ? data.trades : [];
  const count = (status: string) => trades.filter((item: any) => item.status === status).length;
  const selectedStatus = filter.status;
  root.querySelectorAll("#status-filter-group button").forEach((button) => {
    const label = (button.textContent || "").replace(/\s*\(\d+\)/, "").trim();
    const counts: Record<string, number> = {
      "全部": trades.length,
      "计划中": count("PLANNED"),
      "进行中": count("ACTIVE"),
      "清仓中": count("CLOSING"),
      "已结束": trades.filter((item: any) => ["CLOSED", "COMPLETED"].includes(item.status)).length,
      "已取消": count("CANCELLED"),
    };
    if (label in counts) button.textContent = `${label} (${counts[label]})`;
    const selected = (!selectedStatus || selectedStatus === "ALL")
      ? label === "全部"
      : label === "计划中" && selectedStatus === "PLANNED"
        || label === "进行中" && selectedStatus === "ACTIVE"
        || label === "清仓中" && selectedStatus === "CLOSING"
        || label === "已取消" && selectedStatus === "CANCELLED"
        || label === "已结束" && Array.isArray(selectedStatus) && selectedStatus.includes("CLOSED");
    button.classList.toggle("bg-primary", selected);
    button.classList.toggle("text-on-primary", selected);
    button.classList.toggle("active-tab", selected);
    button.classList.toggle("text-on-surface-variant", !selected);
  });

  const selects = root.querySelectorAll("select");
  const typeSelect = selects[0] as HTMLSelectElement | undefined;
  const pageSizeSelect = selects[1] as HTMLSelectElement | undefined;
  if (typeSelect) typeSelect.value = String(filter.type || "全部类型");
  const pageSize = Math.max(1, Number(filter.pageSize) || 10);
  if (pageSizeSelect) pageSizeSelect.value = `${pageSize} 条`;

  const selectedDays = Number(filter.dateDays ?? 30);
  root.querySelectorAll<HTMLElement>("[data-trade-date-filter]").forEach((button) => {
    const selected = Number(button.dataset.tradeDateFilter) === selectedDays;
    button.classList.toggle("bg-primary", selected);
    button.classList.toggle("text-on-primary", selected);
    button.classList.toggle("text-on-surface-variant", !selected);
  });

  const table = root.querySelector("table");
  const pageCount = Math.max(1, Number(table?.getAttribute("data-page-count")) || 1);
  const currentPage = Math.min(Math.max(1, Number(filter.page) || 1), pageCount);
  const pagination = Array.from(root.querySelectorAll("div")).find((element) => textOf(element).includes("每页行数:") && /第\s*\d+\s*\/\s*\d+\s*页/.test(textOf(element)));
  if (!pagination) return;
  pagination.setAttribute("data-trades-pagination", "true");
  const pageText = Array.from(pagination.querySelectorAll("span, div")).find((element) => element.children.length === 0 && /第\s*\d+\s*\/\s*\d+\s*页/.test(element.textContent || ""));
  if (pageText) pageText.textContent = `第 ${currentPage} / ${pageCount} 页`;
  const buttons = Array.from(pagination.querySelectorAll("button"));
  const previous = buttons.find((button) => button.querySelector(".material-symbols-outlined")?.textContent?.trim() === "chevron_left");
  const next = buttons.find((button) => button.querySelector(".material-symbols-outlined")?.textContent?.trim() === "chevron_right");
  const pageButtonContainer = next?.parentElement || previous?.parentElement || pagination;
  Array.from(pageButtonContainer.querySelectorAll("button")).filter((button) => /^\d+$/.test(textOf(button))).forEach((button) => button.remove());
  previous?.setAttribute("data-trade-page", String(Math.max(1, currentPage - 1)));
  next?.setAttribute("data-trade-page", String(Math.min(pageCount, currentPage + 1)));
  if (previous) (previous as HTMLButtonElement).disabled = currentPage === 1;
  if (next) (next as HTMLButtonElement).disabled = currentPage === pageCount;
  const anchor = next?.parentElement === pageButtonContainer ? next : null;
  for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
    const button = root.ownerDocument.createElement("button");
    button.type = "button";
    button.textContent = String(pageNumber);
    button.setAttribute("data-trade-page", String(pageNumber));
    const selected = pageNumber === currentPage;
    button.className = selected
      ? "flex h-8 min-w-8 items-center justify-center rounded-md bg-primary px-2 text-xs font-semibold text-on-primary"
      : "flex h-8 min-w-8 items-center justify-center rounded-md px-2 text-xs font-semibold text-on-surface-variant hover:bg-surface-container";
    if (anchor) pageButtonContainer.insertBefore(button, anchor);
    else pageButtonContainer.appendChild(button);
  }
}

function decorateTradeListVisuals(root: Element, data: any) {
  const trades = Array.isArray(data.trades) ? data.trades : [];
  const typeColors: Record<string, string> = {
    趋势交易: "bg-[#e8efff] text-[#315ca8] border border-[#c8d8ff]",
    "反弹 / 波段": "bg-[#f4eaff] text-[#7441a8] border border-[#ddc8f6]",
    固定目标: "bg-[#fff3d6] text-[#8b5e14] border border-[#f0d69b]",
    自定义: "bg-[#edf0f2] text-[#52616b] border border-[#d6dde1]",
  };
  const statusColors: Record<string, string> = {
    进行中: "bg-[#e4f4e9] text-[#276749] border border-[#bfe3ca]",
    计划中: "bg-[#e8efff] text-[#315ca8] border border-[#c8d8ff]",
    清仓中: "bg-[#fff0dc] text-[#9a5b00] border border-[#f0d39d]",
    已结束: "bg-[#eef0f2] text-[#68736b] border border-[#d8dde0]",
    已取消: "bg-[#eef0f2] text-[#68736b] border border-[#d8dde0]",
    已暂停: "bg-[#fff0dc] text-[#9a5b00] border border-[#f0d39d]",
  };
  root.querySelectorAll("table tbody tr[data-trade-id]").forEach((row) => {
    const trade = trades.find((item: any) => Number(item.id) === Number(row.getAttribute("data-trade-id")));
    if (!trade) return;
    const cells = row.querySelectorAll("td");
    const tag = (cell: Element | undefined, text: string, classes: string, rounded = "rounded-md") => {
      if (!cell) return;
      cell.replaceChildren();
      const badge = document.createElement("span");
      badge.className = `inline-flex ${rounded} px-2 py-1 text-[10px] font-semibold ${classes}`;
      badge.textContent = text || "未记录";
      cell.appendChild(badge);
    };
    tag(cells[1], businessLabel(trade.trade_type), typeColors[businessLabel(trade.trade_type)] || typeColors["自定义"]);
    tag(cells[2], businessLabel(trade.status), statusColors[businessLabel(trade.status)] || "bg-[#f1f3f4] text-[#52616b] border border-[#d8dde0]", "rounded-full");
    const position = (Array.isArray(data.positions) ? data.positions : []).find((item: any) => String(item.symbol) === String(trade.symbol));
    const market = Number(position?.market_price);
    const cost = Number(position?.average_cost);
    if (Number.isFinite(market) && Number.isFinite(cost) && cells[5]) {
      const tone = market > cost ? "#b83230" : market < cost ? "#237a4b" : "#52616b";
      cells[5].style.color = tone;
    }
  });
}

function decorateExecutionAndOrderTags(root: Element, page: PrototypePageKey) {
  const tag = (cell: Element | undefined, text: string, classes: string) => {
    if (!cell) return;
    cell.replaceChildren();
    const badge = document.createElement("span");
    badge.className = `inline-flex rounded-md border px-2 py-1 text-[10px] font-semibold ${classes}`;
    badge.textContent = text || "未记录";
    cell.appendChild(badge);
  };
  const statusClass = (value: string) => ["已成交", "已完成", "正常在线", "监控中"].includes(value)
    ? "border-[#bfe3ca] bg-[#e4f4e9] text-[#276749]"
    : ["部分成交", "挂单中", "已暂停", "撤单中", "待处理"].includes(value)
      ? "border-[#f0d39d] bg-[#fff0dc] text-[#9a5b00]"
      : ["已拒单", "失败", "已过期", "不可执行"].includes(value)
        ? "border-[#f1b9b5] bg-[#fff1f0] text-[#a23b3b]"
        : "border-[#d8dde0] bg-[#eef0f2] text-[#68736b]";
  root.querySelectorAll("table tbody tr").forEach((row) => {
    const cells = row.querySelectorAll("td");
    if (page === "orders") {
      tag(cells[3], cells[3]?.textContent?.trim() || "—", "border-[#ddc8f6] bg-[#f4eaff] text-[#7441a8]");
      tag(cells[4], cells[4]?.textContent?.trim() || "—", cells[4]?.textContent?.trim() === "卖出" ? "border-[#bfe3ca] bg-[#eef9f0] text-[#237a4b]" : "border-[#f1b9b5] bg-[#fff1f3] text-[#b83230]");
      tag(cells[8], cells[8]?.textContent?.trim() || "—", statusClass(cells[8]?.textContent?.trim() || ""));
    } else if (page === "positions") {
      tag(cells[2], cells[2]?.textContent?.trim() || "—", "border-[#c8d8ff] bg-[#e8efff] text-[#315ca8]");
      tag(cells[3], cells[3]?.textContent?.trim() || "—", statusClass(cells[3]?.textContent?.trim() || ""));
      if (cells[6]) cells[6].style.color = cells[6].textContent?.trim().startsWith("-") ? "#237a4b" : "#b83230";
    } else if (page === "execution") {
      tag(cells[4], cells[4]?.textContent?.trim() || "—", statusClass(cells[4]?.textContent?.trim() || ""));
    }
  });
}

function decorateOverviewVisuals(root: Element, data: any) {
  const cardColors: Record<string, { background: string; border: string }> = {
    "账户净资产": { background: "#4b5b73", border: "#3e4c63" },
    "可用现金": { background: "#5f8f6e", border: "#4d795b" },
    "当前总仓位": { background: "#8a6a35", border: "#705326" },
    "账户当前总风险": { background: "#b0003a", border: "#8f0030" },
  };
  Object.entries(cardColors).forEach(([label, color]) => {
    const labelElement = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim() === label);
    const card = labelElement?.parentElement?.parentElement;
    if (!card) return;
    card.classList.remove("bg-surface-container-lowest");
    card.classList.add("border-2", "shadow-md");
    (card as HTMLElement).style.backgroundColor = color.background;
    (card as HTMLElement).style.borderColor = color.border;
    (card as HTMLElement).style.color = "#ffffff";
    card.querySelectorAll("*").forEach((element) => {
      const child = element as HTMLElement;
      child.style.color = "#ffffff";
      child.style.borderColor = "rgba(255,255,255,0.24)";
    });
  });

  // Keep the prototype's legend and make it explicit that the whole row is
  // colored by the current account's profit/loss state.
  const modeLabel = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim() === "红涨绿跌模式");
  if (modeLabel) {
    modeLabel.className = "rounded-full bg-[#fff1f3] px-2 py-1 text-[10px] font-semibold text-[#a73354]";
    modeLabel.textContent = "红涨绿跌模式";
    modeLabel.title = "盈利行显示浅红色，亏损行显示浅绿色";
  }

  const positions = Array.isArray(data.positions) ? data.positions : [];
  const trades = Array.isArray(data.trades) ? data.trades : [];
  const positionBySymbol = new Map<string, any>(positions.map((position: any) => [String(position.symbol), position]));
  const typeColors: Record<string, string> = {
    趋势交易: "bg-[#e8efff] text-[#315ca8] border border-[#c8d8ff]",
    "反弹 / 波段": "bg-[#f4eaff] text-[#7441a8] border border-[#ddc8f6]",
    固定目标: "bg-[#fff3d6] text-[#8b5e14] border border-[#f0d69b]",
    自定义: "bg-[#edf0f2] text-[#52616b] border border-[#d6dde1]",
  };
  const statusColors: Record<string, string> = {
    进行中: "bg-[#e4f4e9] text-[#276749] border border-[#bfe3ca]",
    计划中: "bg-[#e8efff] text-[#315ca8] border border-[#c8d8ff]",
    清仓中: "bg-[#fff0dc] text-[#9a5b00] border border-[#f0d39d]",
    已结束: "bg-[#eef0f2] text-[#68736b] border border-[#d8dde0]",
    已暂停: "bg-[#fff0dc] text-[#9a5b00] border border-[#f0d39d]",
  };
  root.querySelectorAll("table tbody tr").forEach((row) => {
    const tradeId = Number(row.getAttribute("data-trade-id"));
    const trade = trades.find((item: any) => Number(item.id) === tradeId);
    const cells = row.querySelectorAll("td");
    const position = positionBySymbol.get(String(trade?.symbol || ""));
    const typeCell = cells[1];
    const statusCell = cells[2];
      const typeText = typeCell?.textContent?.trim() || "";
    const statusText = statusCell?.textContent?.trim() || "";
    if (typeCell) {
      typeCell.replaceChildren();
      const badge = document.createElement("span");
      badge.className = `inline-flex rounded-md px-2 py-1 text-[10px] font-semibold ${typeColors[typeText] || typeColors["自定义"]}`;
      badge.textContent = typeText || "类型未记录";
      typeCell.appendChild(badge);
    }
    if (statusCell) {
      statusCell.replaceChildren();
      const badge = document.createElement("span");
      badge.className = `inline-flex rounded-full px-2 py-1 text-[10px] font-semibold ${statusColors[statusText] || "bg-[#f1f3f4] text-[#52616b] border border-[#d8dde0]"}`;
      badge.textContent = statusText || "状态未记录";
      statusCell.appendChild(badge);
    }
    const marketPrice = Number(position?.market_price);
    const averageCost = Number(position?.average_cost);
    if (Number.isFinite(marketPrice) && Number.isFinite(averageCost)) {
      const comparison = marketPrice === averageCost ? 0 : marketPrice > averageCost ? 1 : -1;
      (row as HTMLElement).style.backgroundColor = comparison > 0 ? "#fff1f3" : comparison < 0 ? "#eef9f0" : "";
      const priceCell = cells[5];
      if (priceCell) {
        const tone = comparison > 0 ? "#b83230" : comparison < 0 ? "#237a4b" : "#52616b";
        priceCell.innerHTML = `<span class="text-[11px] font-semibold" style="color:${tone}">当前价 ${formatMoney(marketPrice)}</span><span class="mt-0.5 block text-[10px] text-on-surface-variant">买入价：${formatMoney(averageCost)}</span>`;
      }
    }
    const holdingCell = cells[3];
    const quantity = position?.quantity;
    const availableQuantity = position?.available_quantity;
    if (holdingCell && (quantity !== undefined || availableQuantity !== undefined)) {
      holdingCell.innerHTML = `<span class="text-[11px] font-semibold">持仓 ${quantity ?? "—"} 股</span><span class="mt-0.5 block text-[10px] text-on-surface-variant">可卖 ${availableQuantity ?? "—"} 股</span>`;
    }
  });
}

function writePendingExecutionRows(root: Element, data: any) {
  const table = root.querySelector("table");
  const tbody = table?.querySelector("tbody");
  const template = tbody?.querySelector(":scope > tr");
  if (!table || !tbody || !template) return;
  const executionTradePlanIds = new Set((Array.isArray(data.execution_plans) ? data.execution_plans : []).map((plan: any) => Number(plan.trade_plan_id)));
  const plans = (Array.isArray(data.trades) ? data.trades : []).flatMap((trade: any) =>
    (Array.isArray(trade.plans) ? trade.plans : [])
      .filter((plan: any) => ["READY", "ARMED"].includes(plan.status) && !executionTradePlanIds.has(Number(plan.id)))
      .map((plan: any) => ({ trade, plan }))
  );
  if (!plans.length) {
    tbody.replaceChildren();
    const row = tbody.ownerDocument.createElement("tr");
    const cell = tbody.ownerDocument.createElement("td");
    cell.colSpan = 6;
    cell.className = "px-4 py-8 text-center text-xs text-on-surface-variant";
    cell.textContent = "当前账号暂无待创建执行方案的已确认交易计划。";
    row.appendChild(cell);
    tbody.appendChild(row);
    return;
  }
  tbody.replaceChildren(...plans.map(({ trade, plan }: any) => {
    const row = template.cloneNode(true) as HTMLTableRowElement;
    row.setAttribute("data-trade-id", String(trade.id));
    row.setAttribute("data-trade-plan-id", String(plan.id));
    const values = [
      String(plan.symbol || trade.symbol || "—"),
      businessLabel(plan.action_type || plan.action),
      `${businessLabel(["ADD", "OPEN"].includes(plan.action_type) ? "BUY" : "SELL")} ${plan.calculation_snapshot_json?.planned_qty ?? "—"}`,
      formatMoney(plan.input_json?.reference_entry_price ?? plan.calculation_snapshot_json?.entry_price),
      businessLabel(plan.status),
    ];
    Array.from(row.querySelectorAll("td")).slice(0, values.length).forEach((cell, index) => { cell.textContent = values[index]; });
    return row;
  }));
}

function clearPrototypeInputValues(root: Element) {
  root.querySelectorAll("input").forEach((input) => {
    if (input.type === "radio" || input.type === "checkbox") return;
    input.removeAttribute("value");
    input.value = "";
  });
  root.querySelectorAll("textarea").forEach((textarea) => { textarea.textContent = ""; });
}

const stockCodePattern = /^(?:(?:SH|SZ|BJ|XSHG|XSHE)[:.]?)?\d{6}(?:\.(?:SH|SZ|BJ))?$/i;

async function copyTextToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(text); return true; } catch { /* try the browser-compatible path below */ }
  }
  const input = document.createElement("textarea");
  input.value = text;
  input.setAttribute("readonly", "");
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.appendChild(input);
  input.select();
  const copied = document.execCommand("copy");
  input.remove();
  return copied;
}

function markStockCodeElements(root: Element) {
  root.querySelectorAll("span, b, td, div").forEach((element) => {
    const code = (element.textContent || "").trim();
    if (!stockCodePattern.test(code)) return;
    element.setAttribute("data-copy-stock-code", code);
    element.setAttribute("title", `点击复制股票代码 ${code}`);
    element.classList.add("cursor-pointer", "underline", "decoration-dotted", "underline-offset-2", "after:ml-1", "after:text-[10px]", "after:opacity-60", "after:content-['⧉']");
  });
}

function clearOpenPrototypeFixtureCopy(root: Element) {
  // The OPEN page is a blank creation form. Its HTML fixture contains a
  // complete example analysis, which must never be presented as account data.
  [
    "结构评分：强势形态（二买右侧确立）",
    "日线站稳20日线，成交量倍增突破左侧震荡平台颈线",
    "距离入场：1.19R 结构位",
    "盈亏空间比 1 : 3.07",
  ].forEach((value) => replaceTextEverywhere(root, value, "暂无数据"));
  [
    "现价 ¥32.10", "¥32.14", "¥30.10", "¥29.47", "¥28.60",
    "MA5: 29.80", "MA10: 28.94", "MA20: 27.65", "MA60: 25.10",
    "+3.48%", "+1.19R", "-1.0R", "800元",
    "单股风险 ¥0.87", "¥0.87 / 股", "¥800.00 (0.80%)",
    "¥261.00 (0.26% NAV)", "¥800 / ¥0.87 = 357.14 股",
    "向下取整 300 股", "充足 (可用: ¥91,159)",
    "不利买入情景：若涨至上限 ¥30.10 进场", "¥450.00 (↑72.4%)",
    "¥9,030.00 (9.03%)", "8.84%", "¥672.00 / 0.67% NAV",
    "¥8,841.00", "基准价: ¥29.47", "整手数: 3 手",
  ].forEach((value) => replaceTextEverywhere(root, value, "—"));
  root.querySelectorAll("select").forEach((select) => {
    select.querySelectorAll("option").forEach((option) => {
      option.removeAttribute("selected");
      (option as HTMLOptionElement).selected = false;
    });
    select.selectedIndex = -1;
    select.value = "";
    select.removeAttribute("value");
    const placeholder = select.ownerDocument.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "请选择 Playbook";
    placeholder.disabled = true;
    placeholder.selected = true;
    placeholder.setAttribute("selected", "");
    select.insertBefore(placeholder, select.firstChild);
  });
}

function hydrateReduceQuantityControls(root: Element, data: any, detail?: { trade: any; position: any; rules: any[]; history: any[] }) {
  const symbol = detail?.trade?.symbol;
  const position = (Array.isArray(data.positions) ? data.positions : []).find((item: any) => String(item.symbol || "") === String(symbol || ""));
  const quantity = Number(position?.quantity ?? detail?.position?.position_qty ?? detail?.position?.quantity);
  if (!Number.isFinite(quantity) || quantity < 0) return;
  const percentages = [0.25, 1 / 3, 0.5, 1];
  root.querySelectorAll("[data-prototype-field='quantity']").forEach((element, index) => {
    const button = element as HTMLButtonElement;
    const planned = Math.floor(quantity * (percentages[index] || 1));
    const label = index === 3 ? `最大 (${planned}股)` : `${Math.round((percentages[index] || 1) * 100)}% (${planned}股)`;
    button.textContent = label;
    button.setAttribute("data-prototype-value", String(planned));
  });
  const step = Number(detail?.trade?.plans?.[0]?.instrument_json?.quantity_step || 100);
  replaceTextEverywhere(root, "单批次最小单位 —", `单批次最小单位 ${Number.isFinite(step) ? step : "—"}`);
  replaceTextEverywhere(root, "合规校验：符合沪深 A 股 —整数卖出规范", `合规校验：符合沪深 A 股 ${Number.isFinite(step) ? step : "—"}整数卖出规范`);
  const available = position?.available_quantity;
  if (typeof available === "number" && Number.isFinite(available)) {
    replacePatternEverywhere(root, /占用可用额度\s+—/g, `占用可用额度 ${available} 股`);
    replaceTextEverywhere(root, "T+1锁定 —", `T+1锁定 ${Math.max(0, quantity - available)} 股`);
  }
}

function hydrateRiskFields(root: Element, detail: { trade: any; position: any; rules: any[]; history: any[] }, data: any) {
  const trade = detail.trade || {};
  const snapshot = detail.position || {};
  const accountPosition = (Array.isArray(data.positions) ? data.positions : []).find((item: any) => String(item.symbol || "") === String(trade.symbol || "")) || {};
  const finiteNumber = (...values: unknown[]) => {
    for (const value of values) {
      if (value === null || value === undefined || value === "") continue;
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
    return null;
  };
  const legs = Array.isArray(trade.legs) ? trade.legs : [];
  const quantity = finiteNumber(accountPosition.quantity, snapshot.position_qty, snapshot.quantity);
  const averageCost = finiteNumber(accountPosition.average_cost, snapshot.avg_cost, snapshot.average_cost);
  const marketPrice = finiteNumber(accountPosition.market_price, snapshot.market_price);
  const pnl = finiteNumber(accountPosition.unrealized_pnl, snapshot.unrealized_pnl, trade.unrealized_pnl);
  const riskReference = finiteNumber(
    accountPosition.current_risk_reference_price,
    snapshot.position_risk_reference_price,
    ...legs.map((leg: any) => leg.current_risk_reference_price ?? leg.initial_risk_reference_price),
    ...legs.flatMap((leg: any) => Array.isArray(trade.plans) ? trade.plans.filter((plan: any) => Number(plan.sequence_no) === Number(leg.sequence_no)).map((plan: any) => plan.input_json?.risk_reference_price) : []),
  );
  const percentage = marketPrice !== null && averageCost !== null && averageCost !== 0
    ? `${((marketPrice / averageCost - 1) * 100).toFixed(2)}%`
    : "—";
  const quantityText = quantity === null ? "—" : `${quantity}`;
  const avgText = formatMoney(averageCost);
  const priceText = formatMoney(marketPrice);
  const pnlText = formatMoney(pnl);
  const riskText = formatMoney(riskReference);

  const headerName = root.querySelector("span.font-headline.font-bold.text-base") as HTMLElement | null;
  if (headerName) headerName.textContent = String(trade.symbol_name || trade.symbol || "—");
  const headerSymbol = root.querySelector("span.font-mono.text-xs") as HTMLElement | null;
  if (headerSymbol) headerSymbol.textContent = String(trade.symbol || "—");
  const headerType = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim().startsWith("趋势交易 #")) as HTMLElement | undefined;
  if (headerType) headerType.textContent = `${businessLabel(trade.trade_type)} · ${trade.id ? `Trade #${trade.id}` : "—"}`;
  const headerSummary = Array.from(root.querySelectorAll("p")).find((element) => (element.textContent || "").includes("持仓量:"));
  if (headerSummary) headerSummary.textContent = `持仓量: ${quantityText}股 · 综合成本: ${avgText} · 现价: ${priceText} (${percentage})`;
  const headerPnlLabel = Array.from(root.querySelectorAll("div")).find((element) => (element.textContent || "").trim() === "浮动盈亏");
  const headerPnl = headerPnlLabel?.parentElement?.querySelector(".font-headline") as HTMLElement | null;
  if (headerPnl) headerPnl.textContent = `${pnlText} (${percentage})`;
  const headerRiskLabel = Array.from(root.querySelectorAll("div")).find((element) => (element.textContent || "").trim() === "原风险参考价");
  const headerRisk = headerRiskLabel?.parentElement?.querySelector(".font-mono") as HTMLElement | null;
  if (headerRisk) headerRisk.textContent = riskText;
  const riskStatus = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim() === "低风险运行") as HTMLElement | undefined;
  if (riskStatus) riskStatus.textContent = riskReference === null ? "风险参考未设置" : "风险参考已设置";
  const chartOverlay = root.querySelector("div.absolute.right-4") as HTMLElement | null;
  if (chartOverlay) {
    const chartLines = Array.from(chartOverlay.querySelectorAll(":scope > div")) as HTMLElement[];
    if (chartLines[0]) chartLines[0].textContent = `现价: ${priceText}`;
    if (chartLines[1]) chartLines[1].textContent = "新防守建议线: —";
    if (chartLines[2]) chartLines[2].textContent = `原止损底线: ${riskText}`;
  }

  const legCards = Array.from(root.querySelectorAll("div.bg-surface-container-lowest.rounded-lg"))
    .filter((element) => Array.from(element.querySelectorAll("div.font-medium")).some((item) => (item.textContent || "").includes("Leg")));
  legCards.forEach((card, index) => {
    const leg = legs[index];
    const label = card.querySelector("div.font-medium") as HTMLElement | null;
    const detailLine = card.querySelector("div.text-\\[11px\\]") as HTMLElement | null;
    const result = card.querySelector("div.text-primary.font-medium") as HTMLElement | null;
    const referenceLine = Array.from(card.querySelectorAll("div.text-\\[11px\\]")).find((element) => (element.textContent || "").includes("风险")) as HTMLElement | undefined;
    const legQty = finiteNumber(leg?.remaining_qty, leg?.quantity, leg?.entry_qty);
    const legAvg = finiteNumber(leg?.actual_avg_entry_price, leg?.average_entry_price, leg?.avg_price, leg?.planned_entry_price);
    const legRef = finiteNumber(leg?.current_risk_reference_price, leg?.initial_risk_reference_price, riskReference);
    const legPnl = legQty !== null && legAvg !== null && marketPrice !== null ? legQty * (marketPrice - legAvg) : null;
    if (label) label.textContent = `${businessLabel(leg?.leg_type || "LEG")} #${leg?.sequence_no ?? index + 1}`;
    if (detailLine) detailLine.textContent = `成交 ${legQty === null ? "—" : legQty}股 @ ${formatMoney(legAvg)} · ${formatDateTime(leg?.created_at || leg?.opened_at)}`;
    if (result) result.textContent = formatMoney(legPnl);
    if (referenceLine) referenceLine.textContent = `风险参考: ${formatMoney(legRef)}`;
  });

  const totalPosition = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim().startsWith("当前总持仓:")) as HTMLElement | undefined;
  if (totalPosition) totalPosition.textContent = `当前总持仓: ${quantityText}股`;
  const scopeLabels = Array.from(root.querySelectorAll("label")).filter((element) => element.querySelector("input[name='scopeTarget']"));
  scopeLabels.forEach((label, index) => {
    const value = index === 0 ? `整个 Trade (${quantityText}股)` : `${businessLabel(legs[index - 1]?.leg_type || `Leg #${index}`)} (${finiteNumber(legs[index - 1]?.remaining_qty, legs[index - 1]?.quantity, legs[index - 1]?.entry_qty) ?? "—"}股)`;
    const textSpan = Array.from(label.querySelectorAll("span")).find((element) => !(element.className || "").toString().includes("rounded-full") && (element.textContent || "").trim().length > 0) as HTMLElement | undefined;
    if (textSpan) textSpan.textContent = value;
  });
  const oldRiskLabel = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim() === "原风险参考价");
  const oldRiskValue = oldRiskLabel?.parentElement?.parentElement?.querySelector(".font-mono") as HTMLElement | null;
  if (oldRiskValue) oldRiskValue.textContent = riskText;
  const oldRiskDistance = oldRiskLabel?.parentElement?.parentElement?.querySelector(".text-error.font-mono") as HTMLElement | null;
  if (oldRiskDistance) oldRiskDistance.textContent = "未计算";
  replacePatternEverywhere(root, /[-—\d.%]+\s*止损距/g, "未计算");
  const drawerSubtitle = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").includes("调整防守基准")) as HTMLElement | undefined;
  if (drawerSubtitle) drawerSubtitle.textContent = `${String(trade.symbol_name || trade.symbol || "—")} · 调整防守基准，即时重算交易敞口`;
  const riskInput = root.querySelector("#newRiskPriceInput") as HTMLInputElement | null;
  if (riskInput) {
    riskInput.value = "";
    riskInput.removeAttribute("value");
    riskInput.placeholder = "请输入新的风险参考价";
  }
  const riskNote = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim().startsWith("防守抬升"));
  if (riskNote) riskNote.textContent = "填写后计算";
  const textarea = root.querySelector("textarea") as HTMLTextAreaElement | null;
  if (textarea) textarea.value = "";
  const quickPills = Array.from(root.querySelectorAll("button.quick-pill"));
  quickPills.forEach((pill, index) => {
    const value = index === 0 ? priceText : index === 1 ? avgText : "—";
    const numericValue = index === 0 ? marketPrice : index === 1 ? averageCost : null;
    if (numericValue === null) {
      pill.removeAttribute("data-val");
      (pill as HTMLButtonElement).disabled = true;
    } else {
      pill.setAttribute("data-val", String(numericValue));
      (pill as HTMLButtonElement).disabled = false;
    }
    const number = Array.from(pill.querySelectorAll("span")).pop() as HTMLElement | undefined;
    if (number) number.textContent = value;
    if (index === 2) pill.textContent = "暂无技术基准";
  });

  const comparisonHeading = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").includes("核心风控指标前后对比看板"));
  const comparison = comparisonHeading?.closest("section");
  comparison?.querySelectorAll(".grid.grid-cols-2 > div").forEach((card) => {
    card.querySelectorAll(".font-mono").forEach((element) => { (element as HTMLElement).textContent = "—"; });
    const note = Array.from(card.querySelectorAll("div, span")).filter((element) => (element.className || "").toString().includes("text-[10px]")).pop();
    if (note) note.textContent = "填写新风险参考价后计算";
  });
  const projectionHeading = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").includes("到新基准"));
  if (projectionHeading) projectionHeading.textContent = "到新基准 — 的分腿盈亏拆解";
  const projection = projectionHeading?.closest("section");
  const projectionCards = projection ? Array.from(projection.querySelectorAll("div.p-2\\.5.rounded-xl.bg-surface-container")) : [];
  projectionCards.forEach((card, index) => {
    const leg = legs[index];
    const legQty = finiteNumber(leg?.remaining_qty, leg?.quantity, leg?.entry_qty);
    const legAvg = finiteNumber(leg?.actual_avg_entry_price, leg?.average_entry_price, leg?.avg_price, leg?.planned_entry_price);
    const legLabel = card.querySelector("span.font-semibold") as HTMLElement | null;
    const entryLabel = card.querySelector("span.font-mono") as HTMLElement | null;
    if (legLabel) legLabel.textContent = `${businessLabel(leg?.leg_type || "LEG")} (${legQty === null ? "—" : legQty}股)`;
    if (entryLabel) entryLabel.textContent = `@${formatMoney(legAvg)}`;
    const values = card.querySelectorAll(".font-mono.font-bold");
    values.forEach((element) => { (element as HTMLElement).textContent = "—"; });
    const note = card.querySelector("p") as HTMLElement | null;
    if (note) note.textContent = "填写新风险参考价后计算";
    const badge = Array.from(card.querySelectorAll("span")).filter((element) => (element.className || "").toString().includes("text-[10px]")).pop() as HTMLElement | undefined;
    if (badge) badge.textContent = "待计算";
  });
  replaceTextEverywhere(root, "PositionRiskHistory", "风险历史记录");
  replaceTextEverywhere(root, "ExitRules", "退出规则");
}

function clearUnhydratedNumbers(root: Element) {
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let current: Node | null = walker.nextNode();
  while (current) {
    const value = (current.nodeValue || "").trim();
    const parent = (current as Text).parentElement;
    const interactive = parent?.closest("button, a, input, select, option, [role='button']");
    if (!interactive && /^(?:[+-]?¥[\d,.]+|[+-]?\d[\d,.]*%|\d[\d,.]* 股|\d[\d,.]* 只|\d[\d,.]* 笔)$/.test(value)) nodes.push(current as Text);
    current = walker.nextNode();
  }
  nodes.forEach((node) => { node.nodeValue = "—"; });
}

function clearPrototypeMetricFragments(root: Element) {
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let current: Node | null = walker.nextNode();
  while (current) {
    const parent = (current as Text).parentElement;
    const interactive = parent?.closest("button, a, input, select, option, [role='button']");
    if (!interactive && /([+-]?¥[\d,.]+|[+-]?\d[\d,.]*%|\d[\d,.]* 股|\d[\d,.]* 只|\d[\d,.]* 笔)/.test(current.nodeValue || "")) nodes.push(current as Text);
    current = walker.nextNode();
  }
  nodes.forEach((node) => {
    node.nodeValue = (node.nodeValue || "").replace(/[+-]?¥[\d,.]+|[+-]?\d[\d,.]*%|\d[\d,.]* 股|\d[\d,.]* 只|\d[\d,.]* 笔/g, "—");
  });
}

function clearPrototypeFixtureValues(root: Element, protectedValues: string[] = []) {
  // The HTML files are visual fixtures. Remove their known sample values before
  // binding account data so a real account can never inherit demo values.
  [
    "安硕信息", "300380.SZ", "300380", "Trade #T-20241018-02", "Trade #TRD-20250115-001",
    "¥32.10", "¥31.85", "¥31.40", "¥31.20", "¥31.12", "¥31.10", "¥30.54", "¥30.33", "¥30.13", "¥29.85", "¥29.47", "¥29.21", "¥28.60",
    "1,248,500.00", "426,800.00", "8,640.00", "780.00", "480.00", "375.00", "345.00", "320.00", "300.00", "200.00", "100.00", "66.7%", "65.82%", "16.05%", "6.54%", "5.08%", "0.80%", "0.32%",
    "2023-09-08 10:14:58", "09-08 09:30:15", "09-08 10:14:58", "09-08 10:15:01", "09-08 10:15:02", "09-03 09:35", "09-12 14:00", "09-20 待处理",
    "500 股", "300 股", "200 股", "100 股", "500", "300", "200", "100", "2 笔", "4 个关键节点",
  ].filter((value) => !protectedValues.some((protectedValue) => protectedValue && (value === protectedValue || value.startsWith(protectedValue)))).forEach((value) => replaceTextEverywhere(root, value, "—"));
}

function clearPrototypeFixtureFragments(root: Element) {
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let current: Node | null = walker.nextNode();
  while (current) {
    const text = current.nodeValue || "";
    if (/\b(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{2}:\d{2})?|\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)\b/.test(text) || /\b\d[\d,]*(?:\.\d+)?\s*股\b/.test(text) || /\b(?:TRD|PLAN|EXEC|ORD)-[A-Za-z0-9-]+\b|\bcli_ord_[A-Za-z0-9_]+\b/.test(text)) nodes.push(current as Text);
    current = walker.nextNode();
  }
  nodes.forEach((node) => {
    node.nodeValue = (node.nodeValue || "")
      .replace(/\b(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{2}:\d{2})?|\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)\b/g, "—")
      .replace(/\b\d[\d,]*(?:\.\d+)?\s*股\b/g, "—")
      .replace(/\b(?:TRD|PLAN|EXEC|ORD)-[A-Za-z0-9-]+\b|\bcli_ord_[A-Za-z0-9_]+\b/g, "—");
  });
  const numericOnly: Text[] = [];
  const secondWalker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  current = secondWalker.nextNode();
  while (current) {
    const parent = (current as Text).parentElement;
    const interactive = parent?.closest("button, a, input, select, option, [role='button']");
    if (!interactive && /^\s*\d+(?:\.\d+)?\s*$/.test(current.nodeValue || "")) numericOnly.push(current as Text);
    current = secondWalker.nextNode();
  }
  numericOnly.forEach((node) => { node.nodeValue = "—"; });
}

function hydrateDetailFields(root: Element, detail: { trade: any; position: any; rules: any[]; history: any[] }, data: any, page?: PrototypePageKey, actionPlanId?: number | null) {
  const trade = detail.trade;
  const positionSnapshot = detail.position || {};
  const accountPosition = (Array.isArray(data.positions) ? data.positions : []).find((item: any) => String(item.symbol || "") === String(trade.symbol || "")) || {};
  const position = {
    ...positionSnapshot,
    position_qty: accountPosition.quantity ?? positionSnapshot.position_qty ?? positionSnapshot.quantity,
    available_qty: accountPosition.available_quantity ?? positionSnapshot.available_qty ?? positionSnapshot.available_quantity,
    avg_cost: accountPosition.average_cost ?? positionSnapshot.avg_cost ?? positionSnapshot.average_cost,
    market_price: accountPosition.market_price ?? positionSnapshot.market_price,
    unrealized_pnl: accountPosition.unrealized_pnl ?? positionSnapshot.unrealized_pnl,
    position_risk_reference_price: accountPosition.current_risk_reference_price ?? positionSnapshot.position_risk_reference_price,
  };
  const plans = Array.isArray(trade.plans) ? trade.plans : [];
  const legs = Array.isArray(trade.legs) ? trade.legs : [];
  const plan = actionPlanId
    ? plans.find((item: any) => Number(item.id) === Number(actionPlanId)) || null
    : plans.length ? plans[plans.length - 1] : null;
  const input = plan?.input_json || {};
  const calc = plan?.calculation_snapshot_json || {};
  const related = relatedTradeExecutionData(detail, data, actionPlanId);
  const orders = related.orders;
  const fills = related.fills;
  const finiteNumber = (...values: unknown[]) => {
    for (const value of values) {
      if (value === null || value === undefined || value === "") continue;
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
    return null;
  };
  const filledTotal = orders.length ? sumNumericOrNull(orders.map((item: any) => item.filled_quantity ?? item.filled_qty)) : null;
  const fillQuantities = fills.map((item: any) => finiteNumber(item.quantity, item.filled_quantity));
  const fillPrices = fills.map((item: any) => finiteNumber(item.price, item.average_fill_price));
  const fillQuantityTotal = fills.length && fillQuantities.every((item) => item !== null)
    ? fillQuantities.reduce((sum, item) => sum + (item as number), 0)
    : null;
  const fillNotionalTotal = fills.length && fillQuantities.every((item) => item !== null) && fillPrices.every((item) => item !== null)
    ? fills.reduce((sum, item, index) => sum + (fillQuantities[index] as number) * (fillPrices[index] as number), 0)
    : null;
  const values: Record<string, string> = {
    symbol: String(trade.symbol || input.symbol || "—"),
    name: String(trade.symbol_name || input.security_name || trade.symbol || "—"),
    trade: `Trade #${trade.id}`,
    quantity: `${finiteNumber(position.position_qty, position.quantity, calc.planned_qty) ?? "—"} 股`,
    available: `可卖: ${finiteNumber(position.available_qty, position.available_quantity) ?? "—"}`,
    avg: formatMoney(finiteNumber(position.average_cost, position.avg_cost, position.avg_price, input.reference_entry_price)),
    price: formatMoney(finiteNumber(position.market_price, input.current_price)),
    pnl: formatMoney(finiteNumber(position.unrealized_pnl, trade.unrealized_pnl)),
    ref: formatMoney(finiteNumber(position.position_risk_reference_price, input.risk_reference_price)),
    planQty: `${finiteNumber(input.manual_planned_qty, calc.planned_qty) ?? "—"}`,
    entry: formatMoney(finiteNumber(input.reference_entry_price, calc.entry_price)),
    orderAvg: formatMoney(fillQuantityTotal && fillNotionalTotal !== null ? fillNotionalTotal / fillQuantityTotal : null),
    filled: `${filledTotal === null ? "—" : filledTotal} 股`,
  };
  if (page === "trade") {
    const header = root.querySelector(".sticky.top-12");
    const headerTitle = header?.querySelector(".font-headline") as HTMLElement | null;
    const headerSymbol = header?.querySelector(".font-mono") as HTMLElement | null;
    if (headerTitle) headerTitle.textContent = values.name;
    if (headerSymbol) headerSymbol.textContent = values.symbol;
    if (header) replaceTextEverywhere(header, "二买放量突破", trade.playbook_id ? String(trade.playbook_id) : "—");
    const summaryTitle = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim() === "均价 / 现价");
    const summaryCard = summaryTitle?.parentElement?.parentElement;
    const currentPrice = summaryCard?.querySelector(".text-xl") as HTMLElement | null;
    if (currentPrice) currentPrice.textContent = values.price;
    const averageCost = Array.from(root.querySelectorAll("div")).find((element) => (element.textContent || "").trim().startsWith("平均成本:"))?.querySelector("span") as HTMLElement | null;
    if (averageCost) averageCost.textContent = values.avg;
    const summary = root.querySelector("section.grid.grid-cols-2") || root.querySelector("section");
    const cards = summary ? Array.from(summary.children) as HTMLElement[] : [];
    const totalQty = finiteNumber(position.position_qty, position.quantity);
    const availableQty = finiteNumber(position.available_qty, position.available_quantity);
    const totalValue = totalQty !== null && finiteNumber(position.market_price) !== null ? totalQty * (finiteNumber(position.market_price) as number) : null;
    const exposure = totalValue !== null && finiteNumber(data.account?.equity) ? totalValue / (finiteNumber(data.account?.equity) as number) : null;
    const tradePercentage = finiteNumber(position.market_price) !== null && finiteNumber(position.average_cost, position.avg_cost) !== null && finiteNumber(position.average_cost, position.avg_cost) !== 0
      ? `${(((finiteNumber(position.market_price) as number) / (finiteNumber(position.average_cost, position.avg_cost) as number) - 1) * 100).toFixed(2)}%`
      : "—";
    const tradeRiskReference = finiteNumber(
      position.position_risk_reference_price,
      input.risk_reference_price,
      ...plans.flatMap((candidate: any) => [candidate.input_json?.risk_reference_price, candidate.calculation_snapshot_json?.risk_reference_price]),
      ...legs.flatMap((leg: any) => [leg.current_risk_reference_price, leg.initial_risk_reference_price]),
    );
    const tradeRiskBudget = finiteNumber(trade.trade_risk_budget_amount);
    const principalRisk = sumNumericOrNull(legs.map((leg: any) => {
      const legQty = finiteNumber(leg.remaining_qty, leg.quantity, leg.entry_qty);
      const legAvg = finiteNumber(leg.actual_avg_entry_price, leg.average_entry_price, leg.avg_price, leg.planned_entry_price);
      const legRef = finiteNumber(leg.current_risk_reference_price, leg.initial_risk_reference_price, tradeRiskReference);
      return finiteNumber(leg.current_capital_risk) ?? (legQty !== null && legAvg !== null && legRef !== null ? legQty * Math.max(0, legAvg - legRef) : null);
    }));
    const remainingRisk = tradeRiskBudget !== null && principalRisk !== null ? Math.max(0, tradeRiskBudget - principalRisk) : null;
    const riskMetric = (labelText: string, value: string) => {
      const label = Array.from(root.querySelectorAll("div")).find((element) => (element.textContent || "").trim() === labelText);
      const valueElement = label?.parentElement?.querySelector(".font-mono") as HTMLElement | null;
      if (valueElement) valueElement.textContent = value;
    };
    riskMetric("Trade风险预算", `${formatMoney(tradeRiskBudget)} (${trade.trade_risk_budget_pct == null ? "—" : `${(Number(trade.trade_risk_budget_pct) * 100).toFixed(2)}%`})`);
    riskMetric("本金计划风险", formatMoney(principalRisk));
    riskMetric("利润回吐风险", formatMoney(finiteNumber(position.current_giveback_risk, position.giveback_risk)));
    riskMetric("剩余风险容量", formatMoney(remainingRisk));
    riskMetric("当前整体风险参考", formatMoney(tradeRiskReference));
    replacePatternEverywhere(root, /单腿风险盈亏测算分解 \(到参考价 —\)/g, `单腿风险盈亏测算分解 (到参考价 ${formatMoney(tradeRiskReference)})`);
    replacePatternEverywhere(root, /支撑位: — \(参考线\)/g, `支撑位: ${formatMoney(tradeRiskReference)} (参考线)`);
    const lockQty = totalQty !== null && availableQty !== null ? Math.max(0, totalQty - availableQty) : null;
    if (cards[0]) {
      const metric = cards[0].querySelector(".font-headline.font-bold") as HTMLElement | null;
      const available = cards[0].querySelector("strong") as HTMLElement | null;
      const lock = Array.from(cards[0].querySelectorAll("span")).find((element) => (element.textContent || "").includes("T+1冻结")) as HTMLElement | undefined;
      if (metric) metric.textContent = totalQty === null ? "—" : String(totalQty);
      if (available) available.textContent = availableQty === null ? "—" : String(availableQty);
      if (lock) lock.textContent = `T+1冻结: ${lockQty === null ? "—" : lockQty}`;
    }
    if (cards[2]) {
      const metric = cards[2].querySelector(".font-headline.font-bold") as HTMLElement | null;
      const bar = cards[2].querySelector(".bg-primary.h-1\\.5") as HTMLElement | null;
      if (metric) metric.textContent = exposure === null ? "—" : `${(exposure * 100).toFixed(2)}%`;
      if (bar) bar.style.width = exposure === null ? "0%" : `${Math.max(0, Math.min(100, exposure * 100))}%`;
    }
    if (cards[3]) {
      const metric = cards[3].querySelector(".font-mono.font-bold.text-2xl") as HTMLElement | null;
      const marketValue = Array.from(cards[3].querySelectorAll("div")).find((element) => (element.textContent || "").trim().startsWith("总持仓市值:")) as HTMLElement | undefined;
      const pct = cards[3].querySelector(".font-mono.font-bold.text-lg") as HTMLElement | null;
      if (metric) metric.textContent = values.pnl;
      if (marketValue) marketValue.textContent = `总持仓市值: ${formatMoney(totalValue)}`;
      if (pct) pct.textContent = tradePercentage;
    }
    const tradeRiskStatus = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim() === "低风险运行") as HTMLElement | undefined;
    if (tradeRiskStatus) tradeRiskStatus.textContent = finiteNumber(position.position_risk_reference_price, input.risk_reference_price) === null ? "风险参考未设置" : "风险参考已设置";
  }
  if (page === "action" && plan) {
    const actionTitle = `${businessLabel(plan.action_type || plan.action)} #${plan.sequence_no ?? "—"}`;
    replacePatternEverywhere(root, /(?:OPEN|ADD|REDUCE|CLOSE) #\d+ 动作详情/g, `${actionTitle} 动作详情`);
    replacePatternEverywhere(root, /(?:OPEN|ADD|REDUCE|CLOSE) #\d+ \([^)]*\)/g, actionTitle);
    const breadcrumb = root.querySelector("a") as HTMLElement | null;
    if (breadcrumb) breadcrumb.textContent = `${values.name} ${values.symbol}`;
    const setMetric = (label: string, value: string) => {
      const labelElement = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim() === label);
      const container = labelElement?.parentElement;
      if (!container || !labelElement) return;
      const valueElement = Array.from(container.children).filter((element) => element !== labelElement).pop() as HTMLElement | undefined;
      if (valueElement) valueElement.textContent = value;
    };
    const plannedQty = finiteNumber(input.manual_quantity, calc.planned_qty);
    const referencePrice = finiteNumber(input.reference_price, calc.entry_price);
    const riskReference = finiteNumber(input.risk_reference_price, calc.risk_reference_price);
    const actionRisk = finiteNumber(
      calc.incremental_risk_amount,
      calc.current_capital_risk,
      calc.action_risk_budget_amount,
      plan.action_risk_budget_amount,
      plannedQty !== null && referencePrice !== null && riskReference !== null ? plannedQty * Math.max(0, referencePrice - riskReference) : null,
    );
    const actionType = String(plan.action_type || plan.action || "").toUpperCase();
    const quantityLabel = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim() === "计划加仓量") as HTMLElement | undefined;
    if (quantityLabel && actionType !== "ADD") quantityLabel.textContent = "计划数量";
    setMetric(actionType === "ADD" ? "计划加仓量" : "计划数量", plannedQty === null ? "—" : `${plannedQty} 股`);
    setMetric("计划参考价格", formatMoney(referencePrice));
    setMetric("实际成交均价", values.orderAvg);
    setMetric("成交总金额", formatMoney(fillNotionalTotal));
    setMetric("消耗风险预算", formatMoney(actionRisk));
    const riskLabel = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim() === "消耗风险预算");
    const riskValue = riskLabel?.parentElement?.querySelector("span.text-sm") as HTMLElement | null;
    if (riskValue) riskValue.textContent = formatMoney(actionRisk);
    setMetric("触发逻辑", String(plan.reason_text || plan.reason_code || input.reason_text || input.reason_code || "未填写依据"));
    const protection = Array.from(root.querySelectorAll("div"))
      .filter((element) => (element.textContent || "").includes("跌破") && (element.textContent || "").includes("仅平掉加仓"))
      .sort((left, right) => (left.textContent || "").length - (right.textContent || "").length)[0];
    if (protection) {
      protection.textContent = actionType === "ADD"
        ? `跌破 ${formatMoney(finiteNumber(input.risk_reference_price))} 仅平掉加仓的 ${plannedQty === null ? "—" : plannedQty} 股`
        : String(plan.failure_handling || input.failure_handling || "当前动作未配置额外失败处理");
    }
    const reason = String(plan.reason_text || plan.reason_code || input.reason_text || input.reason_code || "未填写依据");
    const triggerLine = Array.from(root.querySelectorAll("p")).find((element) => (element.textContent || "").includes("触发来源："));
    if (triggerLine) {
      const spans = Array.from(triggerLine.querySelectorAll("span"));
      if (spans[0]) spans[0].textContent = `触发来源：${reason}`;
      if (spans[2]) spans[2].textContent = `指令触发时刻：${formatDateTime(orders[0]?.created_at || fills[0]?.filled_at)}`;
    }
    // The prototype's impact-analysis cards are part of the Action Detail
    // contract. Derive them from the selected plan's real fills and the
    // account's current position instead of leaving fixture placeholders.
    const planFilledQuantity = (candidate: any) => {
      const candidateOrders = (candidate?.execution_plans || []).flatMap((execution: any) => execution.orders || []);
      const quantities: number[] = candidateOrders.map((order: any) => finiteNumber(order.filled_quantity, order.filled_qty)).filter((value: number | null): value is number => value !== null);
      return quantities.length ? quantities.reduce((sum: number, value: number) => sum + value, 0) : 0;
    };
    const planSide = (candidate: any) => {
      const execution = candidate?.execution_plans?.[0];
      return String(execution?.side || candidate?.action_type || candidate?.action || "").toUpperCase().includes("SELL") || String(candidate?.action_type || candidate?.action || "").toUpperCase() === "REDUCE" || String(candidate?.action_type || candidate?.action || "").toUpperCase() === "CLOSE" ? -1 : 1;
    };
    const selectedSequence = finiteNumber(plan.sequence_no);
    const currentQuantity = finiteNumber(position.position_qty, position.quantity);
    const selectedDelta = (fillQuantityTotal ?? 0) * planSide(plan);
    const laterDelta = plans
      .filter((candidate: any) => selectedSequence !== null && finiteNumber(candidate.sequence_no) !== null && Number(candidate.sequence_no) > selectedSequence)
      .reduce((sum: number, candidate: any) => sum + planFilledQuantity(candidate) * planSide(candidate), 0);
    const actionAfterQuantity = currentQuantity === null ? null : currentQuantity - laterDelta;
    const actionBeforeQuantity = actionAfterQuantity === null ? null : actionAfterQuantity - selectedDelta;
    const actionFillAverage = fillQuantityTotal && fillNotionalTotal !== null ? fillNotionalTotal / fillQuantityTotal : null;
    const currentAverage = finiteNumber(position.average_cost, position.avg_cost, position.avg_price);
    const actionAfterAverage = actionType === "OPEN" && actionFillAverage !== null ? actionFillAverage : currentAverage;
    const actionBeforeAverage = actionBeforeQuantity === null || actionBeforeQuantity <= 0
      ? null
      : actionAfterAverage !== null && actionFillAverage !== null && selectedDelta > 0
        ? ((actionAfterQuantity || 0) * actionAfterAverage - (fillQuantityTotal || 0) * actionFillAverage) / actionBeforeQuantity
        : actionAfterAverage;
    const accountEquity = finiteNumber(data.account?.equity);
    const marketPrice = finiteNumber(position.market_price, input.current_price);
    const maxPositionPctRaw = finiteNumber(data.risk_profile?.max_single_position_pct);
    const maxPositionPct = maxPositionPctRaw === null ? null : maxPositionPctRaw * 100;
    const afterExposure = accountEquity !== null && marketPrice !== null && actionAfterQuantity !== null && accountEquity > 0
      ? (actionAfterQuantity * marketPrice / accountEquity) * 100
      : null;
    const beforeExposure = accountEquity !== null && marketPrice !== null && actionBeforeQuantity !== null && accountEquity > 0
      ? (actionBeforeQuantity * marketPrice / accountEquity) * 100
      : null;
    const qtyText = (value: number | null) => value === null ? "—" : `${value.toLocaleString("zh-CN")} 股`;
    const evolutionLabel = Array.from(root.querySelectorAll("span")).find((candidate) => (candidate.textContent || "").trim() === "持仓股数演变");
    const evolutionSection = evolutionLabel?.parentElement?.parentElement;
    if (evolutionSection) {
      const deltaLabel = evolutionSection.querySelector(".text-primary.font-bold") as HTMLElement | null;
      if (deltaLabel) deltaLabel.textContent = `${selectedDelta >= 0 ? "+" : ""}${selectedDelta === 0 ? "—" : selectedDelta} ${selectedDelta === 0 ? "仓位变化未发生" : "仓位变化"}`;
      const quantities = Array.from(evolutionSection.querySelectorAll(".font-headline")) as HTMLElement[];
      const setQuantity = (element: HTMLElement | undefined, value: number | null) => {
        if (!element) return;
        const unit = element.querySelector("span");
        element.firstChild?.replaceWith(element.ownerDocument.createTextNode(value === null ? "—" : String(value)));
        if (!unit && value !== null) element.appendChild(element.ownerDocument.createTextNode(" 股"));
      };
      setQuantity(quantities[0], actionBeforeQuantity);
      setQuantity(quantities[1], actionAfterQuantity);
    }
    const costLabel = Array.from(root.querySelectorAll("span")).find((candidate) => (candidate.textContent || "").trim() === "成本线推移");
    const costSection = costLabel?.parentElement?.parentElement;
    if (costSection) {
      const deltaLabel = costSection.querySelector(".text-tertiary.font-bold") as HTMLElement | null;
      if (deltaLabel) deltaLabel.textContent = actionBeforeAverage === null || actionAfterAverage === null
        ? "— / 股 未计算"
        : `${formatMoney(actionAfterAverage - actionBeforeAverage)} / 股 ${actionAfterAverage >= actionBeforeAverage ? "抬升" : "下降"}`;
      const costs = Array.from(costSection.querySelectorAll(".font-headline")) as HTMLElement[];
      if (costs[0]) costs[0].textContent = formatMoney(actionBeforeAverage);
      if (costs[1]) costs[1].textContent = formatMoney(actionAfterAverage);
    }
    const ratioLabel = Array.from(root.querySelectorAll("span")).find((candidate) => (candidate.textContent || "").trim() === "当前仓位配置占比");
    const ratioValue = ratioLabel?.parentElement?.querySelector("span.font-bold") as HTMLElement | null;
    if (ratioValue) ratioValue.textContent = `${beforeExposure === null ? "—" : `${beforeExposure.toFixed(2)}%`} / ${afterExposure === null ? "—" : `${afterExposure.toFixed(2)}%`} (${maxPositionPct === null ? "—" : `${maxPositionPct.toFixed(2)}%`})`;
    const ratioBox = ratioLabel?.closest("div.bg-surface-container-low");
    if (ratioBox) {
      const labels = Array.from(ratioBox.querySelectorAll("span.text-secondary"));
      if (labels[1]) labels[1].textContent = `底仓 ${qtyText(actionBeforeQuantity)}`;
      if (labels[2]) labels[2].textContent = `${selectedDelta >= 0 ? "本次顺势" : "本次兑现"} ${qtyText(Math.abs(selectedDelta))}`;
      if (labels[3]) labels[3].textContent = `剩余可用空间 ${maxPositionPct === null || afterExposure === null ? "—" : `${Math.max(0, maxPositionPct - afterExposure).toFixed(2)}%`}`;
      const bars = Array.from(ratioBox.querySelectorAll("div.h-full")) as HTMLElement[];
      if (bars[0] && maxPositionPct !== null && beforeExposure !== null) bars[0].style.width = `${Math.max(0, Math.min(100, beforeExposure / maxPositionPct * 100))}%`;
      if (bars[1] && maxPositionPct !== null && selectedDelta !== 0 && accountEquity !== null && marketPrice !== null) bars[1].style.width = `${Math.max(0, Math.min(100, Math.abs(selectedDelta) * marketPrice / accountEquity / (maxPositionPct / 100) * 100))}%`;
    }
    replaceExactText(root, "底仓 —", `底仓 ${qtyText(actionBeforeQuantity)}`);
    replaceExactText(root, "本次顺势 —", `本次顺势 ${qtyText(Math.abs(selectedDelta))}`);
    replaceExactText(root, "剩余可用空间 —", `剩余可用空间 ${maxPositionPct === null || afterExposure === null ? "—" : `${Math.max(0, maxPositionPct - afterExposure).toFixed(2)}%`}`);
    replacePatternEverywhere(root, /加仓动作完全确认。底仓浮盈已充分覆盖加仓防护带，系统已正式切换至「无本金风险保护模式」\。?/g, "当前暂无可用的策略状态计算结果");
    replacePatternEverywhere(root, /加仓动作完全确认。?/g, "");
    replacePatternEverywhere(root, /底仓浮盈已充分覆盖加仓防护带，系统已正式切换至「无本金风险保护模式」\s*。?/g, "当前暂无可用的策略状态计算结果");
    replaceTextEverywhere(root, "失败保护方案 (已生效)", plan.failure_handling || input.failure_handling ? "失败处理" : "失败处理");
    const strategyStatus = Array.from(root.querySelectorAll("p")).find((element) => (element.textContent || "").includes("底仓浮盈已充分覆盖"));
    if (strategyStatus) strategyStatus.textContent = "当前暂无可用的策略状态计算结果";
    replaceTextEverywhere(root, "仓位扩张", "仓位变化待计算");
    replaceTextEverywhere(root, "安全", "未计算");
    replaceTextEverywhere(root, "极低滑点", "—");
    replaceTextEverywhere(root, "18 ms", "—");
    replaceTextEverywhere(root, "1,024 ms (分批全成)", "—");
  }
  if (page === "close") {
    const quantity = finiteNumber(position.position_qty, position.quantity);
    const available = finiteNumber(position.available_qty, position.available_quantity);
    const locked = quantity !== null && available !== null ? Math.max(0, quantity - available) : null;
    const targetText = quantity === null ? "—" : `${quantity} 股`;
    const availableText = available === null ? "—" : `${available} 股`;
    const lockedText = locked === null ? "—" : `${locked} 股`;
    replacePatternEverywhere(root, /目标清仓\s+—/g, `目标清仓 ${targetText}`);
    replacePatternEverywhere(root, /当前可执行：—/g, `当前可执行：${availableText}`);
    replacePatternEverywhere(root, /T\+1 待处理：—/g, `T+1 待处理：${lockedText}`);
    const settlementLine = Array.from(root.querySelectorAll("p")).find((element) => (element.textContent || "").includes("目标清仓"));
    const settlementValues = settlementLine ? Array.from(settlementLine.querySelectorAll("strong, span")) as HTMLElement[] : [];
    if (settlementValues[0]) settlementValues[0].textContent = targetText;
    if (settlementValues[1]) settlementValues[1].textContent = availableText;
    if (settlementValues[2]) settlementValues[2].textContent = lockedText;
    const statusBadge = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim().startsWith("趋势交易 #"));
    if (statusBadge) statusBadge.textContent = `${businessLabel(trade.trade_type)} · ${values.symbol}`;
    const executionLabel = Array.from(root.querySelectorAll("div")).find((element) => (element.textContent || "").trim() === "即时执行");
    const deferredLabel = Array.from(root.querySelectorAll("div")).find((element) => (element.textContent || "").trim() === "T+1 递延");
    const setProgress = (label: Element | undefined, percent: number | null, qty: number | null) => {
      const box = label?.parentElement;
      const metric = box?.querySelector(".text-sm.font-bold") as HTMLElement | null;
      const amount = box
        ? Array.from(box.querySelectorAll("div"))
          .filter((element) => element !== label && !element.classList.contains("text-sm"))
          .pop() as HTMLElement | undefined
        : undefined;
      if (metric) metric.textContent = percent === null ? "—" : `${percent.toFixed(1)}%`;
      if (amount) amount.textContent = qty === null ? "—" : `${qty} 股`;
    };
    const total = quantity && quantity > 0 ? quantity : null;
    setProgress(executionLabel, total === null || available === null ? null : (available / total) * 100, available);
    setProgress(deferredLabel, total === null || locked === null ? null : (locked / total) * 100, locked);
  }
  if (page && ["add", "reduce", "close"].includes(page)) {
    const association = Array.from(root.querySelectorAll("span")).find((element) =>
      (element.textContent || "").trim() === "母仓关联：",
    );
    const associationValue = association?.parentElement?.querySelector("span.font-medium") as HTMLElement | null;
    if (associationValue) associationValue.textContent = `${values.name} ${values.symbol}`;
  }
  ["安硕信息", "300380.SZ", "300380"].forEach((fixture) => replaceTextEverywhere(root, fixture, values.name === "—" ? values.symbol : values.name));
  replaceTextEverywhere(root, "Trade #—", values.trade);
  replaceTextEverywhere(root, "Trade #T-20241018-02", values.trade);
  replaceTextEverywhere(root, "Trade #TRD-20250115-001", values.trade);
  bindLabelValue(root, ["当前持仓", "总持仓"], values.quantity.replace(/ 股$/, ""));
  bindLabelValue(root, ["可卖", "当前可卖"], values.available.replace("可卖: ", ""));
  bindLabelValue(root, ["当前总持仓"], values.quantity.replace(/ 股$/, ""));
  bindLabelValue(root, ["可用可卖数量"], values.available.replace("可卖: ", ""));
  bindLabelValue(root, ["均价", "综合成本"], values.avg);
  bindLabelValue(root, ["持仓均价", "平均成本"], values.avg);
  bindLabelValue(root, ["现价", "当前价"], values.price);
  bindLabelValue(root, ["当前市价"], values.price);
  bindLabelValue(root, ["浮动盈亏", "今日浮动盈亏"], values.pnl);
  bindLabelValue(root, ["当前浮动盈亏"], values.pnl);
  bindLabelValue(root, ["风险参考", "原风险参考价", "当前风险参考"], values.ref);
  bindLabelValue(root, ["防守锁利线"], values.ref);
  bindLabelValue(root, ["利润回吐敞口风险"], formatMoney(finiteNumber(position.current_giveback_risk, position.giveback_risk)));
  if (["add", "reduce", "close"].includes(page || "")) {
    const setCardMetric = (prefix: string, value: string) => {
      const label = Array.from(root.querySelectorAll("span.font-label")).find((element) => (element.textContent || "").trim().startsWith(prefix));
      const card = label?.parentElement;
      const valueElement = card?.querySelector("div.mt-1 span.font-headline") as HTMLElement | null;
      if (valueElement) valueElement.textContent = value;
    };
    setCardMetric("当前总持仓", values.quantity.replace(/ 股$/, ""));
    setCardMetric("可用可卖数量", values.available.replace("可卖: ", ""));
    const priceLabel = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim() === "持仓均价 / 当前市价");
    const priceValues = priceLabel?.parentElement?.querySelectorAll(".text-sm, .text-lg");
    if (priceValues?.[0]) (priceValues[0] as HTMLElement).textContent = values.avg;
    if (priceValues?.[1]) (priceValues[1] as HTMLElement).textContent = values.price;
    const pnlLabel = Array.from(root.querySelectorAll("span.font-label")).find((element) => (element.textContent || "").trim().startsWith("当前浮动盈亏"));
    const pnlValue = pnlLabel?.parentElement?.querySelector("div.mt-1 span.text-lg") as HTMLElement | null;
    if (pnlValue) pnlValue.textContent = values.pnl;

    // The ADD/CLOSE prototypes use compact metric cards rather than the
    // REDUCE dashboard labels. Bind those cards structurally so a fixture
    // currency value can never receive the quantity field.
    const metricCard = (labelText: string) => {
      const label = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim() === labelText);
      return label?.closest(".bg-surface-container-lowest") || label?.parentElement?.parentElement || null;
    };
    const holdingCard = metricCard("当前持仓");
    const holdingValue = holdingCard?.querySelector(".font-headline") as HTMLElement | null;
    if (holdingValue) holdingValue.textContent = values.quantity.replace(/ 股$/, "");
    const sellHint = holdingCard ? Array.from(holdingCard.querySelectorAll("div")).find((element) => (element.textContent || "").includes("可卖")) as HTMLElement | undefined : undefined;
    if (sellHint) {
      const available = values.available.replace("可卖: ", "");
      const quantity = finiteNumber(position.position_qty, position.quantity);
      const availableNumber = finiteNumber(position.available_qty, position.available_quantity);
      sellHint.textContent = `可卖 ${available} 股 (T+1锁${quantity !== null && availableNumber !== null ? Math.max(0, quantity - availableNumber) : "—"})`;
    }
    const priceCard = metricCard("均价 / 现价");
    const compactPriceValues = priceCard ? Array.from(priceCard.querySelectorAll(".font-headline")) as HTMLElement[] : [];
    if (compactPriceValues[0]) compactPriceValues[0].textContent = values.avg;
    if (compactPriceValues[1]) compactPriceValues[1].textContent = values.price;
    const pnlCard = metricCard("浮动盈亏");
    const pnlCardValue = pnlCard?.querySelector(".font-headline") as HTMLElement | null;
    if (pnlCardValue) pnlCardValue.textContent = values.pnl;
  }
  if (plan) {
    bindLabelValue(root, ["计划加仓量", "计划数量"], values.planQty);
    bindLabelValue(root, ["参考基准价", "参考加仓价", "参考卖出价"], values.entry);
    bindLabelValue(root, ["最低可接受卖出价"], formatMoney(finiteNumber(input.minimum_acceptable_price)));
    bindLabelValue(root, ["实际成交均价", "加仓后平均成本"], values.orderAvg);
    bindLabelValue(root, ["成交总金额"], formatMoney(fillNotionalTotal));
    bindLabelValue(root, ["消耗风险预算", "本次新增风险"], formatMoney(finiteNumber(
      calc.planned_risk_amount,
      calc.incremental_risk_amount,
      calc.current_capital_risk,
      plan.action_risk_budget_amount,
      input.manual_quantity !== undefined && input.reference_price !== undefined && input.risk_reference_price !== undefined
        ? Number(input.manual_quantity) * Math.max(0, Number(input.reference_price) - Number(input.risk_reference_price))
        : null,
    )));
  }
}

function bindLabelValue(root: Element, labels: string[], value: string) {
  if (!value) return;
  for (const label of labels) {
    const elements = Array.from(root.querySelectorAll("span, p, h1, h2, h3, div"))
      .filter((element) => (element.textContent || "").trim() === label);
    for (const element of elements) {
      let container: Element | null = element.parentElement;
      for (let level = 0; level < 4 && container; level += 1, container = container.parentElement) {
        const walker = root.ownerDocument.createTreeWalker(container, NodeFilter.SHOW_TEXT);
        let node: Node | null = walker.nextNode();
        while (node) {
          const text = (node.nodeValue || "").trim();
          if (node !== element.firstChild && /^(?:—|¥[\d,.]+|[\d,.]+|[\d,.]+%|[\d,.]+ 股|[\d,.]+ 只|[\d,.]+ 笔)$/.test(text)) {
            node.nodeValue = (node.nodeValue || "").replace(text, value);
            return;
          }
          node = walker.nextNode();
        }
      }
    }
  }
}

function replaceMetricAfterLabel(root: Element, label: string, value: string) {
  const labelElement = Array.from(root.querySelectorAll("span, p, div")).find((element) => (element.textContent || "").trim() === label);
  const container = labelElement?.parentElement;
  if (!container) return;
  const walker = root.ownerDocument.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let node: Node | null = walker.nextNode();
  while (node) {
    if (node !== labelElement.firstChild && /^(?:—|¥[\d,.]+|[\d,.]+|[\d,.]+%|[\d,.]+ 只)$/.test((node.nodeValue || "").trim())) {
      node.nodeValue = value;
      return;
    }
    node = walker.nextNode();
  }
}

function replaceCardMetric(root: Element, label: string, value: string) {
  const labelElement = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim() === label);
  const card = labelElement?.parentElement?.parentElement;
  const metric = card?.querySelector(".my-1 span.text-xl");
  if (metric) metric.textContent = value;
}

function findMetricCard(root: Element, label: string): Element | null {
  const labelElement = Array.from(root.querySelectorAll("span, div")).find((element) => (element.textContent || "").trim() === label);
  let card = labelElement?.parentElement || null;
  while (card && card !== root) {
    if (card.classList.contains("bg-surface-container-lowest")) return card;
    card = card.parentElement;
  }
  return labelElement?.parentElement?.parentElement || null;
}

function setMetricCardValue(root: Element, label: string, value: string) {
  const card = findMetricCard(root, label);
  const metric = card?.querySelector(".text-xl, .font-headline.font-bold") as HTMLElement | null;
  if (metric) metric.textContent = value;
  return card;
}

function setCardText(root: Element, label: string, matcher: string | RegExp, value: string) {
  const card = findMetricCard(root, label);
  if (!card) return;
  const element = Array.from(card.querySelectorAll("span, div, p")).find((candidate) => {
    const text = (candidate.textContent || "").trim();
    return typeof matcher === "string" ? text.includes(matcher) : matcher.test(text);
  }) as HTMLElement | undefined;
  if (element) element.textContent = value;
}

function replaceLabeledStrong(root: Element, label: string, value: string) {
  const strong = Array.from(root.querySelectorAll("strong")).find((candidate) => {
    const parent = candidate.parentElement;
    return Boolean(parent && (parent.textContent || "").includes(label));
  });
  if (strong) strong.textContent = value;
}

function replaceButtonCount(root: Element, label: string, count: number) {
  const button = Array.from(root.querySelectorAll("button")).find((candidate) => (candidate.textContent || "").includes(label));
  if (!button) return;
  const walker = root.ownerDocument.createTreeWalker(button, NodeFilter.SHOW_TEXT);
  let node: Node | null = walker.nextNode();
  while (node) {
    if (/\(\d+\)/.test(node.nodeValue || "")) {
      node.nodeValue = (node.nodeValue || "").replace(/\(\d+\)/, `(${count})`);
      return;
    }
    node = walker.nextNode();
  }
}

function hydrateMarkup(root: Element, data: any, page: PrototypePageKey, detail?: { trade: any; position: any; rules: any[]; history: any[] }, filter: PrototypeFilter = {}, actionPlanId?: number | null) {
  const account = data.account || {};
  const positions = Array.isArray(data.positions) ? data.positions : [];
  const trades = Array.isArray(data.trades) ? data.trades : [];
  const totalUnrealizedPnl = typeof account.unrealized_pnl === "number"
    ? account.unrealized_pnl
    : sumNumericOrNull(positions.map((item: any) => item.unrealized_pnl));
  const totalRealizedPnl = typeof account.realized_pnl === "number" ? account.realized_pnl : null;
  const plannedRiskValues = trades.flatMap((trade: any) => Array.isArray(trade.plans)
    ? trade.plans.map((plan: any) => plan.calculation_snapshot_json?.planned_risk_amount ?? plan.action_risk_budget_amount)
    : []);
  const plannedRiskAmount = sumNumericOrNull(plannedRiskValues);
  const brokerConnected = data.broker_status?.status === "CONNECTED" || data.broker_status?.ok === true;
  const brokerUnavailable = data.broker_status?.status === "UNAVAILABLE";
  const reconciliationIssues = Array.isArray(data.reconciliation_issues) ? data.reconciliation_issues : [];
  const accountExecutionPaused = data.control?.execution_paused === true || Number(data.control?.execution_paused) === 1;
  const brokerReady = brokerConnected && !accountExecutionPaused && data.broker_status?.node_status?.agent_online !== false && data.broker_status?.node_status?.execution_enabled !== false && !data.broker_status?.node_status?.paused && !data.broker_status?.node_status?.reconciliation_required && reconciliationIssues.length === 0;
  const risk = typeof account.equity === "number" && typeof data.risk_profile?.default_trade_risk_pct === "number"
    ? account.equity * data.risk_profile.default_trade_risk_pct
    : null;
  // Clear literal prototype metrics before applying the account response.
  // This prevents values from the design fixture leaking into an empty or
  // differently populated account.
  clearPrototypeFixtureValues(root, detail?.trade
    ? [String(detail.trade.symbol || ""), String(detail.trade.symbol || "").slice(0, 3), String(detail.trade.symbol_name || ""), "安硕信息", "300", "300380", "300380.SZ"]
    : []);
  clearPrototypeFixtureFragments(root);
  clearUnhydratedNumbers(root);
  clearPrototypeMetricFragments(root);
  if (page === "overview") replaceOverviewMetrics(root, data);
  replaceExactText(root, "¥1,248,500.00", formatMoney(account.equity));
  replaceExactText(root, "¥426,800.00", formatMoney(account.available_cash));
  replaceExactText(root, "¥8,640.00", formatMoney(risk));
  replaceExactText(root, "8 只持仓标的", `${positions.length} 只持仓标的`);
  replaceExactText(root, "65.82%", typeof account.total_exposure_pct === "number" ? `${(account.total_exposure_pct * 100).toFixed(2)}%` : "—");
  bindLabelValue(root, ["账户净资产", "总资产"], formatMoney(account.equity));
  bindLabelValue(root, ["可用现金"], formatMoney(account.available_cash));
  bindLabelValue(root, ["持仓市值"], formatMoney(account.market_value));
  bindLabelValue(root, ["当前总仓位", "总仓位", "仓位占用"], typeof account.total_exposure_pct === "number" ? `${(account.total_exposure_pct * 100).toFixed(2)}%` : "—");
  bindLabelValue(root, ["今日浮动盈亏", "浮动盈亏"], formatMoney(totalUnrealizedPnl));
  bindLabelValue(root, ["累计实现盈亏", "已实现盈亏"], formatMoney(totalRealizedPnl));
  bindLabelValue(root, ["持仓标的", "只持仓标的"], `${positions.length} 只`);
  bindLabelValue(root, ["订单总数", "今日订单", "今日流水"], `${Array.isArray(data.orders) ? data.orders.length : 0} 笔`);
  bindLabelValue(root, ["执行计划总数", "活跃执行"], `${Array.isArray(data.execution_plans) ? data.execution_plans.length : 0}`);
  bindLabelValue(root, ["计划风险", "账户总风险", "本金计划风险"], formatMoney(plannedRiskAmount));
  bindLabelValue(root, ["持仓浮盈:", "持仓浮盈", "浮动盈亏:"], formatMoney(totalUnrealizedPnl));
  bindLabelValue(root, ["持仓标的:", "持仓标的"], `${positions.length} 只`);
  replacePatternEverywhere(root, /账户净资产\s+[^\n]*?今日/g, `账户净资产 ${formatMoney(account.equity)} 今日`);
  if (page === "overview") {
    const activeTradeCount = trades.filter((item: any) => ["ACTIVE", "CLOSING"].includes(item.status)).length;
    replacePatternEverywhere(root, /\d+\s+活跃/g, `${activeTradeCount} 活跃`);
    replaceTextEverywhere(root, "3 活跃", `${activeTradeCount} 活跃`);
    replaceTextEverywhere(root, "—持仓标的", `${positions.length} 只持仓标的`);
    replaceMetricAfterLabel(root, "持仓浮盈:", formatMoney(totalUnrealizedPnl));
    replaceMetricAfterLabel(root, "持仓标的:", `${positions.length} 只`);
  }
  if (page === "trades") {
    replacePatternEverywhere(root, /综合在途风险敞口:\s*¥[\d,.]+\s*\([\d.]+% NAV\)/g,
      `综合在途风险敞口: ${plannedRiskAmount !== null && plannedRiskAmount > 0 ? formatMoney(plannedRiskAmount) : "—"} (${account.equity && plannedRiskAmount !== null ? `${((plannedRiskAmount / account.equity) * 100).toFixed(2)}% NAV` : "—"})`);
    replaceLabeledStrong(root, "持仓浮盈:", formatMoney(totalUnrealizedPnl));
    replaceLabeledStrong(root, "持仓标的:", `${positions.length} 只`);
  }
  const tableRows = page === "orders" ? data.orders : page === "positions" ? positions : page === "execution" ? data.execution_plans : trades;
  if (Array.isArray(tableRows)) {
    replacePatternEverywhere(root, /共\s*\d+/g, `共 ${tableRows.length}`);
    if (page === "trades") {
      const count = (status: string) => trades.filter((item: any) => item.status === status).length;
      const statusCounts: Record<string, number> = { "全部": trades.length, "计划中": count("PLANNED"), "进行中": count("ACTIVE"), "清仓中": count("CLOSING"), "已结束": trades.filter((item: any) => ["CLOSED", "COMPLETED"].includes(item.status)).length, "已取消": count("CANCELLED") };
      root.querySelectorAll("#status-filter-group button").forEach((button) => {
        const label = (button.textContent || "").replace(/\s*\(\d+\)/, "").trim();
        if (label in statusCounts) button.textContent = `${label} (${statusCounts[label]})`;
        const selected = filter.status === "ALL" || !filter.status
          ? label === "全部"
          : label === "计划中" && filter.status === "PLANNED"
            || label === "进行中" && filter.status === "ACTIVE"
            || label === "清仓中" && filter.status === "CLOSING"
            || label === "已取消" && filter.status === "CANCELLED"
            || label === "已结束" && Array.isArray(filter.status) && filter.status.includes("CLOSED");
        button.classList.toggle("bg-primary", selected);
        button.classList.toggle("text-on-primary", selected);
        button.classList.toggle("active-tab", selected);
        button.classList.toggle("text-on-surface-variant", !selected);
      });
      replacePatternEverywhere(root, /全部\s*\(\d+\)/g, `全部 (${trades.length})`);
      replacePatternEverywhere(root, /计划中\s*\(\d+\)/g, `计划中 (${count("PLANNED")})`);
      replacePatternEverywhere(root, /进行中\s*\(\d+\)/g, `进行中 (${count("ACTIVE")})`);
      replacePatternEverywhere(root, /清仓中\s*\(\d+\)/g, `清仓中 (${count("CLOSING")})`);
      replacePatternEverywhere(root, /已结束\s*\(\d+\)/g, `已结束 (${trades.filter((item: any) => ["CLOSED", "COMPLETED"].includes(item.status)).length})`);
      replacePatternEverywhere(root, /已取消\s*\(\d+\)/g, `已取消 (${count("CANCELLED")})`);
      replacePatternEverywhere(root, /共\s*—\s*笔交易/g, `共 ${trades.length} 笔交易`);
      replaceTextEverywhere(root, "共 — 笔交易", `共 ${trades.length} 笔交易`);
      replaceLeafText(root, /^共\s*—\s*笔交易$/, `共 ${trades.length} 笔交易`);
      const totalLabel = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").includes("笔交易") && element.querySelector("strong"));
      const totalValue = totalLabel?.querySelector("strong");
      if (totalValue) totalValue.textContent = String(trades.length);
      const pageSize = Math.max(1, Number(filter.pageSize) || 10);
      const currentPage = Math.max(1, Number(filter.page) || 1);
      const pages = Math.max(1, Math.ceil(trades.length / pageSize));
      replaceExactText(root, "第 1 / 2 页", `第 ${Math.min(currentPage, pages)} / ${pages} 页`);
      const typeSelect = root.querySelector("select") as HTMLSelectElement | null;
      if (typeSelect && filter.type) typeSelect.value = String(filter.type);
      const days = Number(filter.dateDays ?? 30);
      root.querySelectorAll("[data-trade-date-filter]").forEach((button) => {
        const selected = Number((button as HTMLElement).getAttribute("data-trade-date-filter")) === days;
        button.classList.toggle("bg-primary", selected);
        button.classList.toggle("text-on-primary", selected);
        button.classList.toggle("text-on-surface-variant", !selected);
      });
      root.querySelectorAll("button[title]").forEach((button) => {
        if (button.getAttribute("title") === "列设置") button.setAttribute("data-trade-column-toggle", "true");
        if (button.getAttribute("title") === "导出CSV") button.setAttribute("data-trade-export", "true");
      });
      const pagination = Array.from(root.querySelectorAll("div")).find((element) => textOf(element).includes("每页行数:") && textOf(element).includes("第 1 /"));
      if (pagination) {
        pagination.setAttribute("data-trades-pagination", "true");
        pagination.querySelectorAll("button").forEach((button) => {
          const icon = button.querySelector(".material-symbols-outlined")?.textContent?.trim();
          const number = Number(textOf(button));
          if (icon === "chevron_left") button.setAttribute("data-trade-page", String(Math.max(1, currentPage - 1)));
          else if (icon === "chevron_right") button.setAttribute("data-trade-page", String(Math.min(pages, currentPage + 1)));
          else if (Number.isFinite(number) && number > 0) button.setAttribute("data-trade-page", String(number));
        });
      }
    }
  }
  // Keep every real account symbol/name that was just written into the DOM.
  // This matters when a real account legitimately contains one of the symbols
  // used by the visual prototype; fixture cleanup must never erase API data.
  const protectedEntities = [
    ...positions.flatMap((item: any) => [item.symbol, item.security_name]),
    ...trades.flatMap((item: any) => [item.symbol, item.symbol_name]),
    ...((Array.isArray(data.orders) ? data.orders : []).map((item: any) => item.symbol)),
    ...(detail?.trade ? [detail.trade.symbol, detail.trade.symbol_name] : []),
  ].filter((value): value is string => typeof value === "string" && value.length > 0);
  removePrototypeEntities(root, protectedEntities);
  if (page === "overview") {
    replaceRecentActions(root, Array.isArray(data.orders) ? data.orders : [], Array.isArray(data.fills) ? data.fills : []);
    // A Trade record is not itself a pending task. Only show this section when
    // the account has an actionable exception, such as reconciliation issues.
    replacePrototypeSection(root, "待处理事项", reconciliationIssues.length
      ? reconciliationSummary(reconciliationIssues)
      : "当前账号暂无待处理事项。");
  }
  if (page === "orders") {
    const orders = Array.isArray(data.orders) ? data.orders : [];
    const count = (statuses: string[]) => orders.filter((item: any) => statuses.includes(item.status)).length;
    bindLabelValue(root, ["今日委托笔数"], String(orders.length));
    bindLabelValue(root, ["已完全成交"], String(count(["FILLED"])));
    bindLabelValue(root, ["部成 / 挂单中"], String(count(["PARTIALLY_FILLED", "PENDING_SUBMIT", "SUBMITTED", "ACCEPTED"])));
    setMetricCardValue(root, "今日委托笔数", String(orders.length));
    setMetricCardValue(root, "已完全成交", String(count(["FILLED"])));
    setMetricCardValue(root, "部成 / 挂单中", String(count(["PARTIALLY_FILLED", "PENDING_SUBMIT", "SUBMITTED", "ACCEPTED"])));
    setMetricCardValue(root, "已撤单 / 废单", String(count(["CANCELLED", "CANCELED", "CANCELLED_ORDER", "REJECTED", "FAILED", "EXPIRED"])));
    replaceTextEverywhere(root, "73.8%", orders.length ? `${((count(["FILLED"]) / orders.length) * 100).toFixed(1)}%` : "—");
    replaceTextEverywhere(root, "42 条流水", `${orders.length} 条流水`);
    replacePatternEverywhere(root, /主动撤单\s+\d+/g, `主动撤单 ${count(["CANCELLED", "CANCELED", "CANCELLED_ORDER"])}`);
    replacePatternEverywhere(root, /拒单\s+\d+/g, `拒单 ${count(["REJECTED", "FAILED"])}`);
    const filledNotional = (side: string): number | null => {
      const relevant = orders.filter((item: any) => item.side === side && Number(item.filled_quantity) > 0);
      if (!relevant.length) return null;
      if (relevant.some((item: any) => !Number.isFinite(Number(item.filled_quantity)) || !Number.isFinite(Number(item.average_fill_price ?? item.price)))) return null;
      return relevant.reduce((total: number, item: any) => total + Number(item.filled_quantity) * Number(item.average_fill_price ?? item.price), 0);
    };
    const buyNotional = filledNotional("BUY");
    const sellNotional = filledNotional("SELL");
    const totalNotional = sumNumericOrNull(orders.map((item: any) => {
      const quantity = Number(item.filled_quantity ?? item.filled_qty);
      const price = Number(item.average_fill_price ?? item.price ?? item.limit_price);
      return Number.isFinite(quantity) && Number.isFinite(price) && quantity > 0 ? quantity * price : null;
    }));
    setMetricCardValue(root, "今日实际成交总额", formatMoney(totalNotional));
    setCardText(root, "已完全成交", "成交率", `成交率 ${orders.length ? ((count(["FILLED"]) / orders.length) * 100).toFixed(1) : "—"}%`);
    setCardText(root, "已撤单 / 废单", "主动撤单", `主动撤单 ${count(["CANCELLED", "CANCELED", "CANCELLED_ORDER"])} · 拒单 / 过期 ${count(["REJECTED", "FAILED", "EXPIRED"])}`);
    setCardText(root, "今日实际成交总额", "买入", `买入 ${buyNotional == null ? "—" : formatMoney(buyNotional)} / 卖出 ${sellNotional == null ? "—" : formatMoney(sellNotional)}`);
    replacePatternEverywhere(root, /买入\s+—M\s+\/\s+卖出\s+—K/g, `买入 ${buyNotional == null ? "—" : formatMoney(buyNotional)} / 卖出 ${sellNotional == null ? "—" : formatMoney(sellNotional)}`);
    replacePatternEverywhere(root, /RTT:\s*\d+ms/g, "RTT: —");
    root.querySelectorAll("#statusFilterTabs button").forEach((button) => {
      const label = (button.textContent || "").replace(/\s*\(\d+\)/, "").trim();
      const counts: Record<string, number> = { "全部": orders.length, "已成交": count(["FILLED"]), "部成": count(["PARTIALLY_FILLED"]), "已撤销": count(["CANCELLED", "CANCELED", "CANCELLED_ORDER"]), "废单/拒单": count(["REJECTED", "FAILED", "EXPIRED"]) };
      if (label in counts) button.textContent = `${label} (${counts[label]})`;
    });
    replaceTextEverywhere(root, "2023-09-08", "当前交易日");
    replaceTextEverywhere(root, "华泰证券 CTP-01 (柜台已就绪)", brokerReady ? "当前券商通道已就绪" : brokerUnavailable ? "当前券商状态暂时无法读取" : !brokerConnected ? "当前券商通道未连接" : accountExecutionPaused ? "当前账号已暂停执行" : data.broker_status?.node_status?.agent_online === false ? "券商已连接，执行器离线" : data.broker_status?.node_status?.reconciliation_required ? "券商已连接，通道保护中" : "券商已连接，暂不可执行");
    if (orders.length === 0) Array.from(root.querySelectorAll("button")).filter((button) => ["1", "2", "3"].includes((button.textContent || "").trim())).forEach((button) => button.remove());
    replaceTextEverywhere(root, "CTP/L2 专线平稳", brokerReady ? "券商连接正常" : brokerUnavailable ? "券商状态暂时无法读取" : !brokerConnected ? "券商未连接" : accountExecutionPaused ? "当前账号已暂停执行" : data.broker_status?.node_status?.agent_online === false ? "券商已连接，执行器离线" : data.broker_status?.node_status?.reconciliation_required ? "券商已连接，通道保护中" : "券商已连接，暂不可执行");
    replacePatternEverywhere(root, /今日委托笔数\s+receipt_long\s+\d+/g, `今日委托笔数 receipt_long ${orders.length}`);
    replacePatternEverywhere(root, /已完全成交\s+check_circle\s+\d+/g, `已完全成交 check_circle ${count(["FILLED"])}`);
    replacePatternEverywhere(root, /部成 \/ 挂单中\s+hourglass_bottom\s+\d+/g, `部成 / 挂单中 hourglass_bottom ${count(["NEW", "PENDING_NEW", "PARTIALLY_FILLED", "PENDING_SUBMIT", "QUEUED", "CLAIMED", "DISPATCHING", "SUBMITTED", "ACCEPTED", "CANCEL_PENDING", "CANCEL_REQUESTED"])}`);
    replacePatternEverywhere(root, /已撤单 \/ 废单\s+cancel\s+(?:\d+|—)\s+主动撤单\s+(?:\d+|—)\s+·\s+拒单\s+(?:\d+|—)/g, `已撤单 / 废单 cancel ${count(["CANCELLED", "CANCELED", "CANCELLED_ORDER", "REJECTED", "FAILED", "EXPIRED"])} 主动撤单 ${count(["CANCELLED", "CANCELED", "CANCELLED_ORDER"])} · 拒单 / 过期 ${count(["REJECTED", "FAILED", "EXPIRED"])}`);
    replacePatternEverywhere(root, /实时订单明细 \(Order Book Log\) 共 \d+ 条记录/g, `实时订单明细 (Order Book Log) 共 ${orders.length} 条记录`);
    replacePatternEverywhere(root, /显示第 \d+ 到 \d+ 项，共 \d+ 条流水/g, `显示第 ${orders.length ? 1 : 0} 到 ${orders.length} 项，共 ${orders.length} 条流水`);
    replaceLeafText(root, /^已撤单 \/ 废单\s+cancel\s+(?:\d+|—)\s+主动撤单\s+(?:\d+|—)\s+·\s+拒单\s+(?:\d+|—)$/, `已撤单 / 废单 cancel ${count(["CANCELLED", "CANCELED", "CANCELLED_ORDER", "REJECTED", "FAILED", "EXPIRED"])} 主动撤单 ${count(["CANCELLED", "CANCELED", "CANCELLED_ORDER"])} · 拒单 / 过期 ${count(["REJECTED", "FAILED", "EXPIRED"])}`);
    const cancelledCardLabel = Array.from(root.querySelectorAll("span")).find((element) => (element.textContent || "").trim() === "已撤单 / 废单");
    const cancelledCard = cancelledCardLabel?.parentElement?.parentElement;
    const cancelledMetric = cancelledCard?.querySelector(".text-xl");
    const cancelledDetail = cancelledCard?.querySelector(".text-\\[11px\\]");
    if (cancelledMetric) cancelledMetric.textContent = String(count(["CANCELLED", "CANCELED", "CANCELLED_ORDER", "REJECTED", "FAILED", "EXPIRED"]));
    if (cancelledDetail) cancelledDetail.textContent = `主动撤单 ${count(["CANCELLED", "CANCELED", "CANCELLED_ORDER"])} · 拒单 / 过期 ${count(["REJECTED", "FAILED", "EXPIRED"])}`;
    const pageCount = Math.max(1, Math.ceil(orders.length / 20));
    const pageButtons = Array.from(root.querySelectorAll("button")).filter((button) => /^\d+$/.test((button.textContent || "").trim()));
    pageButtons.forEach((button, index) => {
      if (index >= pageCount) button.remove();
      else button.textContent = String(index + 1);
    });
    const pageLabel = Array.from(root.querySelectorAll("span, div")).find((element) => /^第\s*\d+\s*\/\s*\d+\s*页$/.test((element.textContent || "").trim()));
    if (pageLabel) pageLabel.textContent = `第 1 / ${pageCount} 页`;
    const drawer = root.querySelector("#orderDetailDrawer");
    drawer?.remove();
  }
  if (page === "execution") {
    const plans = Array.isArray(data.execution_plans) ? data.execution_plans : [];
    const accountExecutionPaused = data.control?.execution_paused === true || Number(data.control?.execution_paused) === 1;
    const executionTradePlanIds = new Set(plans.map((plan: any) => Number(plan.trade_plan_id)));
    const tradePlans = trades.flatMap((trade: any) => trade.plans || []).filter((plan: any) => ["READY", "ARMED"].includes(plan.status) && !executionTradePlanIds.has(Number(plan.id)));
    const executionReadiness = brokerUnavailable
      ? "券商状态暂时无法读取"
      : accountExecutionPaused
      ? "当前账号已暂停执行"
      : brokerReady
      ? "引擎就绪"
      : reconciliationIssues.length > 0
        ? "待处理对账"
        : data.broker_status?.node_status?.reconciliation_required
        ? "券商通道保护中"
        : data.broker_status?.node_status?.agent_online === false
          ? "执行器离线"
          : "当前不可执行";
    replaceTextEverywhere(root, "引擎就绪", executionReadiness);
    bindLabelValue(root, ["待执行计划"], `${tradePlans.length} 笔待路由`);
    bindLabelValue(root, ["活跃监控中"], `${plans.filter((plan: any) => ["ARMED", "MONITORING"].includes(plan.status)).length} 笔挂机盯盘`);
    bindLabelValue(root, ["今日已执行"], `${plans.filter((plan: any) => plan.status === "COMPLETED").length} 笔`);
    replacePatternEverywhere(root, /\d+\s+笔待路由/g, `${tradePlans.length} 笔待路由`);
    replacePatternEverywhere(root, /\d+\s+笔挂机盯盘/g, `${plans.filter((plan: any) => ["ARMED", "MONITORING"].includes(plan.status)).length} 笔挂机盯盘`);
    replacePatternEverywhere(root, /\d+\s+笔\s+\([^)]*\)/g, `${plans.filter((plan: any) => plan.status === "COMPLETED").length} 笔`);
    const completedPlans = plans.filter((plan: any) => plan.status === "COMPLETED").length;
    const terminalPlans = plans.filter((plan: any) => ["COMPLETED", "CANCELLED", "CANCELED", "REJECTED", "EXPIRED"].includes(String(plan.status))).length;
    const executionOrders = Array.isArray(data.orders) ? data.orders : [];
    const executedNotional = sumNumericOrNull(executionOrders.map((order: any) => {
      const quantity = Number(order.filled_quantity ?? order.filled_qty);
      const price = Number(order.average_fill_price ?? order.price ?? order.limit_price);
      return Number.isFinite(quantity) && Number.isFinite(price) && quantity > 0 ? quantity * price : null;
    }));
    const executedLabel = Array.from(root.querySelectorAll("div")).find((element) => (element.textContent || "").trim() === "今日已执行");
    const executedCard = executedLabel?.parentElement?.parentElement?.parentElement;
    const executedCount = executedCard?.querySelector(".font-headline.font-bold") as HTMLElement | null;
    const executedDetail = executedCard?.querySelector(".text-\\[10px\\].text-on-surface-variant") as HTMLElement | null;
    const executedRate = executedCard ? Array.from(executedCard.querySelectorAll("span")).find((element) => (element.textContent || "").includes("成功")) as HTMLElement | undefined : undefined;
    if (executedCount) executedCount.textContent = String(completedPlans);
    if (executedDetail) executedDetail.textContent = `笔 (${formatMoney(executedNotional)})`;
    if (executedRate) executedRate.textContent = terminalPlans > 0 ? `${((completedPlans / terminalPlans) * 100).toFixed(1)}% 成功` : "未计算";
    replaceExecutionChannelStatus(root, data);
    decorateExecutionMetricCards(root, data);
    replaceExecutionMonitor(root, plans, trades);
    root.querySelectorAll("button").forEach((button) => {
      const text = textOf(button);
      if (["全部", "监控中", "执行中", "已完成", "已暂停"].some((label) => text.startsWith(label))) {
        const status = text.startsWith("监控中") ? "监控中" : text.startsWith("执行中") ? "执行中" : text.startsWith("已完成") ? "已完成" : text.startsWith("已暂停") ? "已暂停" : "全部";
        const classes = status === "已完成" || status === "监控中" ? "border-[#bfe3ca] bg-[#e4f4e9] text-[#276749]" : status === "已暂停" ? "border-[#f0d39d] bg-[#fff0dc] text-[#9a5b00]" : status === "执行中" ? "border-[#c8d8ff] bg-[#e8efff] text-[#315ca8]" : "border-[#d8dde0] bg-[#eef0f2] text-[#68736b]";
        button.className = `rounded-md border px-2.5 py-1 text-xs font-semibold ${classes}`;
      }
    });
  }
  if (page === "positions") replacePositionSummary(root, data);
  if (detail?.trade) {
    const trade = detail.trade;
    replaceExactText(root, "安硕信息", String(trade.symbol_name || trade.symbol || "—"));
    replaceExactText(root, "300 股", `${detail.position?.position_qty ?? detail.position?.quantity ?? "—"} 股`);
    replaceExactText(root, "Trade #TRD-20250115-001", `Trade #${trade.id}`);
    replaceExactText(root, "进行中", businessLabel(trade.status));
    replaceExactText(root, "交易类型：趋势交易", `交易类型：${businessLabel(trade.trade_type)}`);
    replaceExactText(root, "风险参考：¥29.47", `风险参考：${formatMoney(detail.position?.position_risk_reference_price)}`);
    hydrateDetailFields(root, detail, data, page, actionPlanId);
    if (page === "risk") hydrateRiskFields(root, detail, data);
    if (page === "action") replaceActionTrace(root, detail, data, actionPlanId);
    if (page === "reduce") hydrateReduceQuantityControls(root, data, detail);
  }
  if (["overview", "trades", "orders", "positions"].includes(page)) writeTableRows(root, page, data, filter);
  if (page === "trades") {
    decorateTradeListVisuals(root, data);
    syncTradeListControlState(root, data, filter);
  }
  if (page === "orders" || page === "positions") decorateExecutionAndOrderTags(root, page);
  if (page === "overview") decorateOverviewVisuals(root, data);
  if (page === "execution") {
    writePendingExecutionRows(root, data);
    decorateExecutionAndOrderTags(root, "execution");
    const executionSummary = (labelText: string, countText: string, detailText: string) => {
      const label = Array.from(root.querySelectorAll("div")).find((element) => (element.textContent || "").trim() === labelText);
      const card = label?.parentElement?.parentElement?.parentElement;
      const countElement = card?.querySelector(".font-headline.font-bold") as HTMLElement | null;
      const detailElement = card ? Array.from(card.querySelectorAll("span")).find((element) => element !== countElement && (element.textContent || "").includes("笔")) as HTMLElement | undefined : undefined;
      if (countElement) countElement.textContent = countText;
      if (detailElement) detailElement.textContent = detailText;
    };
    const executionPlans = Array.isArray(data.execution_plans) ? data.execution_plans : [];
    const executionTradePlanIds = new Set(executionPlans.map((plan: any) => Number(plan.trade_plan_id)));
    const readyCount = trades.flatMap((trade: any) => trade.plans || []).filter((plan: any) => ["READY", "ARMED"].includes(plan.status) && !executionTradePlanIds.has(Number(plan.id))).length;
    const activeCount = executionPlans.filter((plan: any) => ["ARMED", "MONITORING"].includes(plan.status)).length;
    const completedCount = executionPlans.filter((plan: any) => plan.status === "COMPLETED").length;
    const terminalCount = executionPlans.filter((plan: any) => ["COMPLETED", "CANCELLED", "CANCELED", "REJECTED", "EXPIRED"].includes(String(plan.status))).length;
    const executionFills = Array.isArray(data.fills) ? data.fills : [];
    const notional = sumNumericOrNull(executionFills.map((fill: any) => {
      const quantity = Number(fill.quantity ?? fill.filled_quantity);
      const price = Number(fill.price ?? fill.average_fill_price);
      return Number.isFinite(quantity) && Number.isFinite(price) && quantity > 0 ? quantity * price : null;
    }));
    executionSummary("待执行计划", String(readyCount), "笔待路由");
    executionSummary("活跃监控中", String(activeCount), "笔挂机盯盘");
    executionSummary("今日已执行", String(completedCount), `笔 (${formatMoney(notional)})`);
    const executedLabel = Array.from(root.querySelectorAll("div")).find((element) => (element.textContent || "").trim() === "今日已执行");
    const executedCard = executedLabel?.parentElement?.parentElement?.parentElement;
    const success = executedCard ? Array.from(executedCard.querySelectorAll("span")).find((element) => (element.textContent || "").includes("成功")) as HTMLElement | undefined : undefined;
    if (success) success.textContent = terminalCount > 0 ? `${((completedCount / terminalCount) * 100).toFixed(1)}% 成功` : "未计算";
    replaceTextEverywhere(root, "笔 (—)", `笔 (${formatMoney(notional)})`);
    replaceTextEverywhere(root, "—% 成功", terminalCount > 0 ? `${((completedCount / terminalCount) * 100).toFixed(1)}% 成功` : "未计算");
  }
  if (page !== "action") writeDetailRows(root, page, data, detail, actionPlanId);
  if (detail?.trade && page === "trade") {
    replaceDetailList(root, "生命周期时间线", detail.trade.plans || [], (plan) => `${businessLabel(plan.action_type || plan.action)} #${plan.sequence_no || "—"} · ${businessLabel(plan.status)} · ${plan.calculation_snapshot_json?.planned_qty ?? "—"} 股 · ${formatDateTime(plan.created_at)}`, "当前 Trade 暂无交易计划流水。", false, true);
    replaceDetailList(root, "退出规则", detail.rules || [], (rule) => `${businessLabel(rule.trigger_type)} → ${businessLabel(rule.action_type)} · ${rule.enabled ? "启用" : "停用"}`, "当前 Trade 暂无退出规则。", true);
  }
  if (detail?.trade && page === "risk") {
    replaceDetailList(root, "查看历史", detail.history || [], (item) => `${formatDateTime(item.created_at)} · ${formatMoney(item.old_price ?? item.previous_price)} → ${formatMoney(item.new_price)} · ${item.reason || "未填写依据"}`, "当前 Trade 暂无风险参考调整记录。");
  }
  if (["open", "add", "reduce", "close", "action"].includes(page)) clearPrototypeInputValues(root);
  if (page === "open") clearOpenPrototypeFixtureCopy(root);
  const rows = page === "orders" ? data.orders : page === "positions" ? positions : page === "execution" ? [...(data.execution_plans || []), ...trades.flatMap((trade: any) => trade.plans || []).filter((plan: any) => ["READY", "ARMED"].includes(plan.status))] : trades;
  if (!Array.isArray(rows) || rows.length === 0) {
    root.querySelectorAll("table tbody").forEach((tbody) => {
      tbody.innerHTML = `<tr><td colspan="12" class="px-4 py-8 text-center text-xs text-on-surface-variant">当前账号暂无交易数据</td></tr>`;
    });
  }
}

export default function PrototypeTradingPage({ page, onNavigate, accountId, refreshToken = 0, marketRealtimeEnabled = false, tradeId, actionPlanId, onExecutionStatusChange, onOrderCancel, onExitRuleCreate, onExitRuleChange, onPauseAll, onCancelOpenOrders, onCreateExecutionPlan, onOrderInspect, onExecutionOrderInspect, onCreateTradePlan, onActionSubmit, onRiskReferenceSubmit, onOpenSettings, onRefresh }: Props) {
  const [markup, setMarkup] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);
  const [filter, setFilter] = useState<PrototypeFilter>({});
  const [klineContext, setKlineContext] = useState<{ code: string; name: string; markers: Array<{ date: string; price?: number; label: string; color?: string }> } | null>(null);
  const [klineOpen, setKlineOpen] = useState(false);
  const [klineMount, setKlineMount] = useState<HTMLElement | null>(null);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const dataRef = useRef<any>(null);
  const filterRef = useRef<PrototypeFilter>(filter);
  const renderedPageRef = useRef<PrototypePageKey | null>(null);

  useEffect(() => {
    filterRef.current = filter;
  }, [filter]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const requestInit: RequestInit = { cache: "no-store", signal: controller.signal };
    setError(null);
    setKlineContext(null);
    setKlineOpen(false);
    if (!API_BASE) {
      Promise.resolve().then(() => {
        if (!cancelled) setError("交易服务配置不可用，请联系管理员");
      });
      return () => { cancelled = true; controller.abort(); };
    }
    if (accountId === undefined || accountId === null) {
      Promise.resolve().then(() => {
        if (!cancelled) setError("请先选择交易账号后再查看交易页面");
      });
      return () => { cancelled = true; controller.abort(); };
    }
    const detailPage = ["trade", "risk", "add", "reduce", "close", "action"].includes(page);
    if (detailPage && (tradeId === null || tradeId === undefined)) {
      Promise.resolve().then(() => {
        if (!cancelled) setError("当前页面缺少交易上下文，请从交易列表选择具体 Trade 后进入。");
      });
      return () => { cancelled = true; };
    }
    const detailPromise = detailPage
      ? Promise.all([
          fetch(`${API_BASE}/api/trades/${encodeURIComponent(String(tradeId))}?account_id=${encodeURIComponent(String(accountId))}`, requestInit),
          fetch(`${API_BASE}/api/trades/${encodeURIComponent(String(tradeId))}/position-state?account_id=${encodeURIComponent(String(accountId))}`, requestInit),
          fetch(`${API_BASE}/api/trades/${encodeURIComponent(String(tradeId))}/exit-rules?account_id=${encodeURIComponent(String(accountId))}`, requestInit),
          fetch(`${API_BASE}/api/trades/${encodeURIComponent(String(tradeId))}/risk-reference-history?account_id=${encodeURIComponent(String(accountId))}`, requestInit),
        ]).then(async ([tradeResponse, positionResponse, rulesResponse, historyResponse]) => {
          const [tradeResult, positionResult, rulesResult, historyResult] = await Promise.all([
            readApiResponse(tradeResponse, "交易详情读取失败"),
            readApiResponse(positionResponse, "持仓状态读取失败"),
            readApiResponse(rulesResponse, "退出规则读取失败"),
            readApiResponse(historyResponse, "风险历史读取失败"),
          ]);
          const scopedTrade = requireDetailItem(assertAccountScope(tradeResult, accountId, "交易详情"), "交易详情", ["id", "account_id", "symbol", "symbol_name", "trade_type", "status", "plans", "legs"]);
          const scopedPosition = requireDetailItem(assertAccountScope(positionResult, accountId, "持仓状态"), "持仓状态", ["trade_id", "position_qty", "available_qty", "avg_cost", "market_price", "market_value", "position_risk_reference_price"]);
          const scopedRules = requireDetailItems(assertAccountScope(rulesResult, accountId, "退出规则"), "退出规则");
          const scopedHistory = requireDetailItems(assertAccountScope(historyResult, accountId, "风险历史"), "风险历史");
          return { trade: scopedTrade.item, position: scopedPosition.item, rules: scopedRules.items, history: scopedHistory.items };
        })
      : Promise.resolve(null);
    const brokerPromise = fetch(`${API_BASE}/api/trading/broker?account_id=${encodeURIComponent(String(accountId))}`, requestInit)
      .then((response) => readApiResponse(response, "券商状态读取失败"))
      .then((payload) => ({ connection: payload.connection || payload }))
      .catch((reason) => ({
        connection: {
          status: "UNAVAILABLE",
          error: reason instanceof Error ? reason.message : "券商状态读取失败",
        },
      }));
    const liveSnapshotPromise = marketRealtimeEnabled
      ? fetch(`${API_BASE}/api/trading/live-snapshot?account_id=${encodeURIComponent(String(accountId))}`, requestInit)
        .then((response) => readApiResponse(response, "实时账户快照读取失败"))
      : Promise.resolve(null);
    Promise.all([
      fetch(`/prototype-pages/${files[page]}/code.html`, requestInit).then((response) => {
        if (!response.ok) throw new Error(`原型页面读取失败（HTTP ${response.status}）`);
        return response.text();
      }),
      fetch(`${API_BASE}/api/trading/overview?account_id=${encodeURIComponent(String(accountId))}`, requestInit)
        .then((response) => readApiResponse(response, "交易数据读取失败"))
        .then((payload) => assertTradingOverview(payload, accountId)),
      detailPromise,
      brokerPromise,
      liveSnapshotPromise,
    ])
      .then(([html, overview, detail, broker, liveSnapshot]) => {
        if (cancelled) return;
        const hydratedOverview = liveSnapshot
          ? {
              ...overview,
              account: { ...overview.account, ...(liveSnapshot as any).account },
              positions: (liveSnapshot as any).positions,
              broker_status: (liveSnapshot as any).broker_status,
              market_session: { open: marketRealtimeEnabled },
            }
          : { ...overview, market_session: { open: marketRealtimeEnabled } };
        dataRef.current = hydratedOverview;
        const currentRoot = contentRef.current;
        const canHydrateInPlace = renderedPageRef.current === page
          && currentRoot !== null;
        if (canHydrateInPlace) {
          const interactiveState = captureInteractiveState(currentRoot);
          hydrateMarkup(currentRoot, { ...hydratedOverview, broker_status: liveSnapshot ? (liveSnapshot as any).broker_status : broker.connection }, page, detail || undefined, filterRef.current, actionPlanId);
          markStockCodeElements(currentRoot);
          restoreInteractiveState(currentRoot, interactiveState);
          setError(null);
          return;
        }
        const document = new DOMParser().parseFromString(html, "text/html");
        const main = document.querySelector("main");
        if (!main) throw new Error("原型页面缺少 main 内容区域");
        main.querySelectorAll("script").forEach((script) => script.remove());
        main.querySelectorAll("img").forEach((image) => {
          const source = image.getAttribute("src") || "";
          if (source.includes("lh3.googleusercontent.com")) {
            image.setAttribute("src", "/prototype-assets/prototype-remote-1.png");
          }
        });
        replaceStaticKline(main, page);
        decoratePrototypeFormControls(main, page);
        hydrateMarkup(main, { ...hydratedOverview, broker_status: liveSnapshot ? (liveSnapshot as any).broker_status : broker.connection }, page, detail || undefined, filterRef.current, actionPlanId);
        markStockCodeElements(main);
        if ((page === "trade" || page === "risk") && detail?.trade?.symbol) {
          setKlineContext({
            code: String(detail.trade.symbol),
            name: String(detail.trade.symbol_name || detail.trade.symbol),
            markers: tradeKlineMarkers(detail, hydratedOverview),
          });
        } else if (page === "open") {
          const codeElement = Array.from(main.querySelectorAll("span")).find((element) => /^\d{6}$/.test((element.textContent || "").trim()));
          const code = codeElement?.textContent?.trim() || "";
          const name = codeElement?.previousElementSibling?.textContent?.trim() || code;
          setKlineContext(code ? { code, name, markers: [] } : null);
        }
        setError(null);
        renderedPageRef.current = page;
        setMarkup(main.innerHTML);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "原型页面读取失败");
      });
    return () => { cancelled = true; controller.abort(); };
  }, [page, accountId, refreshToken, marketRealtimeEnabled, retryToken, tradeId, actionPlanId]);
  useEffect(() => {
    if (!markup || !["open", "trade", "risk"].includes(page)) {
      setKlineMount(null);
      return;
    }
    const mount = contentRef.current?.querySelector("[data-prototype-kline-slot]") as HTMLElement | null;
    mount?.replaceChildren();
    setKlineMount(mount);
  }, [markup, page, klineContext]);
  useEffect(() => {
    const root = contentRef.current;
    if (!root || !markup || !["orders", "trades"].includes(page) || !dataRef.current) return;
    hydrateMarkup(root, dataRef.current, page, undefined, filter, actionPlanId);
    markStockCodeElements(root);
  }, [filter, markup, page, actionPlanId]);
  useEffect(() => {
    setFilter(page === "orders" && tradeId !== null && tradeId !== undefined ? { tradeId } : {});
  }, [page, accountId, tradeId]);

  useEffect(() => {
    const root = contentRef.current;
    if (!root) return;
    const click = (event: MouseEvent) => {
      const sourceTarget = event.target as HTMLElement;
      const copyTarget = sourceTarget.closest("[data-copy-stock-code]") as HTMLElement | null;
      if (copyTarget) {
        const code = copyTarget.getAttribute("data-copy-stock-code") || copyTarget.textContent?.trim() || "";
        if (!code) return;
        copyTextToClipboard(code).then((copied) => {
          if (!copied) { setError("股票代码复制失败，请检查浏览器剪贴板权限"); return; }
          const previousTitle = copyTarget.title;
          copyTarget.title = `已复制 ${code}`;
          setCopiedCode(code);
          window.setTimeout(() => { copyTarget.title = previousTitle; }, 1200);
          window.setTimeout(() => setCopiedCode((current) => current === code ? null : current), 1600);
        });
        return;
      }
      const stockCell = sourceTarget.closest("td");
      const cellCode = stockCell?.textContent?.match(/\b\d{6}(?:\.(?:SH|SZ|BJ))?\b/i)?.[0];
      if (stockCell && cellCode) {
        copyTextToClipboard(cellCode).then((copied) => {
          if (!copied) { setError("股票代码复制失败，请检查浏览器剪贴板权限"); return; }
          setCopiedCode(cellCode);
          window.setTimeout(() => setCopiedCode((current) => current === cellCode ? null : current), 1600);
        });
        return;
      }
      const target = sourceTarget.closest("button, a");
      if (!target) return;
      if (page === "risk" && target.classList.contains("quick-pill")) {
        const value = target.getAttribute("data-val") || "";
        const input = root.querySelector("#newRiskPriceInput") as HTMLInputElement | null;
        if (input) input.value = value;
        root.querySelectorAll("button.quick-pill").forEach((button) => {
          button.classList.toggle("active", button === target);
          button.setAttribute("aria-pressed", button === target ? "true" : "false");
        });
        return;
      }
      if (page === "risk" && target.classList.contains("reason-tag")) {
        const reason = textOf(target).replace(/^●\s*/, "").trim();
        const textarea = root.querySelector("textarea") as HTMLTextAreaElement | null;
        if (textarea) textarea.value = reason;
        root.querySelectorAll("button.reason-tag").forEach((button) => {
          const selected = button === target;
          button.classList.toggle("active", selected);
          button.setAttribute("data-prototype-selected", selected ? "true" : "false");
          button.setAttribute("aria-pressed", selected ? "true" : "false");
        });
        return;
      }
      if (page === "reduce" && target.closest("#reduce-reasons button")) {
        const reason = target.closest("#reduce-reasons button") as HTMLButtonElement;
        root.querySelectorAll("#reduce-reasons button").forEach((button) => {
          const selected = button === reason;
          button.className = selected
            ? "px-3 py-2 text-xs rounded-lg text-left font-medium bg-primary text-on-primary shadow-sm flex items-center justify-between transition-all"
            : "px-3 py-2 text-xs rounded-lg text-left font-medium bg-surface-container text-on-surface hover:bg-surface-container-high transition-all";
          button.setAttribute("data-prototype-selected", selected ? "true" : "false");
          button.setAttribute("aria-pressed", selected ? "true" : "false");
          const icon = button.querySelector(".material-symbols-outlined");
          if (selected && !icon) {
            const check = document.createElement("span");
            check.className = "material-symbols-outlined text-sm";
            check.textContent = "check";
            button.appendChild(check);
          } else if (!selected && icon) {
            icon.remove();
          }
        });
        return;
      }
      if (page === "close" && target.closest("#reason-container .reason-pill")) {
        const reason = target.closest("#reason-container .reason-pill");
        root.querySelectorAll("#reason-container .reason-pill").forEach((button) => {
          const selected = button === reason;
          button.classList.toggle("bg-primary", selected);
          button.classList.toggle("text-on-primary", selected);
          button.classList.toggle("shadow-sm", selected);
          button.classList.toggle("bg-surface-container-low", !selected);
          button.classList.toggle("text-on-surface", !selected);
          button.setAttribute("data-prototype-selected", selected ? "true" : "false");
          button.setAttribute("aria-pressed", selected ? "true" : "false");
          const icon = button.querySelector(".material-symbols-outlined");
          icon?.classList.toggle("opacity-0", !selected);
        });
        return;
      }
      if (page === "add" && target.closest("[data-prototype-toggle='worst-case']")) {
        const panel = root.querySelector("#worst-case-panel");
        const icon = root.querySelector("#panel-chevron");
        if (panel) {
          const hidden = panel.classList.toggle("hidden");
          if (icon) icon.textContent = hidden ? "expand_more" : "expand_less";
        }
        return;
      }
      if (["orders", "trades", "positions"].includes(page) && target.getAttribute("data-prototype-row-toggle")) {
        const rowId = target.getAttribute("data-prototype-row-toggle");
        const row = rowId ? root.querySelector(`#${CSS.escape(rowId)}`) : null;
        const icon = target.querySelector(".material-symbols-outlined");
        if (row) {
          const hidden = row.classList.toggle("hidden");
          icon?.classList.toggle("rotate-90", !hidden);
        }
        return;
      }
      const prototypeField = target.getAttribute("data-prototype-field");
      if (prototypeField) {
        root.querySelectorAll(`[data-prototype-field="${prototypeField}"]`).forEach((element) => {
          element.setAttribute("data-prototype-selected", element === target ? "true" : "false");
          if (element instanceof HTMLElement) element.setAttribute("aria-pressed", element === target ? "true" : "false");
        });
        if (prototypeField === "quantity") {
          const quantityInput = root.querySelector("input[type='number']") as HTMLInputElement | null;
          const value = target.getAttribute("data-prototype-value");
          if (quantityInput && value) quantityInput.value = value;
        }
        return;
      }
      const rowTradeId = Number(target.closest("tr")?.getAttribute("data-trade-id"));
      const selectedTradeId = Number.isFinite(rowTradeId) && rowTradeId > 0 ? rowTradeId : tradeId || undefined;
      const rowPlanId = Number(target.closest("[data-trade-plan-id]")?.getAttribute("data-trade-plan-id"));
      const selectedPlanId = Number.isFinite(rowPlanId) && rowPlanId > 0 ? rowPlanId : undefined;
      const positionTradeCount = Number(target.closest("tr")?.getAttribute("data-trade-count") || 0);
      const label = textOf(target);
      if (page === "orders" && label.includes("刷新流水") && onRefresh) {
        onRefresh();
        return;
      }
      if (page === "orders" && label.includes("导出流水")) {
        const csvRows = Array.from(root.querySelectorAll("table tr")).map((row) => Array.from(row.querySelectorAll("th,td")).map((cell) => `"${(cell.textContent || "").replace(/"/g, '""').replace(/\s+/g, " ").trim()}"`).join(","));
        const blob = new Blob(["\ufeff" + csvRows.join("\n")], { type: "text/csv;charset=utf-8" });
        const anchor = document.createElement("a");
        anchor.href = URL.createObjectURL(blob);
        anchor.download = `订单流水_${new Date().toISOString().slice(0, 10)}.csv`;
        anchor.click();
        URL.revokeObjectURL(anchor.href);
        return;
      }
      if (page === "positions" && ["全部持仓", "多Trade标的", "有在途T+1", "清仓中"].some((item) => label.startsWith(item))) {
        const positionMode = label.startsWith("多Trade标的") ? "MULTI" : label.startsWith("有在途T+1") ? "T1" : label.startsWith("清仓中") ? "CLOSING" : "ALL";
        setFilter((current) => ({ ...current, positionMode }));
        return;
      }
      if (page === "trades" && label.includes("刷新报价") && onRefresh) {
        onRefresh();
        return;
      }
      if (page === "trades" && target.closest("[data-trade-date-filter]")) {
        const selectedDays = Number((target.closest("[data-trade-date-filter]") as HTMLElement).getAttribute("data-trade-date-filter"));
        setFilter((value) => ({ ...value, dateDays: Number.isFinite(selectedDays) ? selectedDays : 30, page: 1 }));
        return;
      }
      if (page === "trades" && target.closest("[data-trade-export]")) {
        const csvRows = Array.from(root.querySelectorAll("table tr")).map((row) => Array.from(row.querySelectorAll("th,td")).map((cell) => `"${(cell.textContent || "").replace(/"/g, '""').replace(/\s+/g, " ").trim()}"`).join(","));
        const blob = new Blob(["\ufeff" + csvRows.join("\n")], { type: "text/csv;charset=utf-8" });
        const anchor = document.createElement("a");
        anchor.href = URL.createObjectURL(blob);
        anchor.download = `交易列表_${new Date().toISOString().slice(0, 10)}.csv`;
        anchor.click();
        URL.revokeObjectURL(anchor.href);
        return;
      }
      if (page === "trades" && target.closest("[data-trade-column-toggle]")) {
        const table = root.querySelector("table");
        const hidden = table?.getAttribute("data-risk-columns-hidden") === "true";
        table?.setAttribute("data-risk-columns-hidden", hidden ? "false" : "true");
        table?.querySelectorAll("tr").forEach((row) => [7, 8].forEach((index) => {
          const cell = row.children[index] as HTMLElement | undefined;
          if (cell) cell.style.display = hidden ? "" : "none";
        }));
        return;
      }
      if (page === "trades" && target.closest("[data-trade-page]")) {
        const requested = Number((target.closest("[data-trade-page]") as HTMLElement).getAttribute("data-trade-page"));
        if (Number.isFinite(requested) && requested > 0) setFilter((value) => ({ ...value, page: requested }));
        return;
      }
      if (target.getAttribute("data-prototype-open-kline") === "true" || (page === "trade" && label.includes("查看K线"))) {
        if (klineContext) {
          setKlineOpen(true);
        } else {
          setError("当前交易尚未关联证券，暂时无法加载 K 线。");
        }
        return;
      }
      const ruleId = Number(target.closest("[data-exit-rule-id]")?.getAttribute("data-exit-rule-id"));
      if (page === "trade" && label.includes("查看动作详情") && selectedTradeId !== undefined) {
        onNavigate("action", selectedTradeId, selectedPlanId);
        return;
      }
      if (page === "trade" && label.includes("成交日志") && selectedTradeId !== undefined) {
        onNavigate("orders", selectedTradeId);
        return;
      }
      if (page === "trade" && label.includes("查看计算") && selectedTradeId !== undefined) {
        onNavigate("action", selectedTradeId);
        return;
      }
      if (page === "trade" && Number.isFinite(ruleId) && ruleId > 0 && onExitRuleChange && (label === "编辑" || label === "删除")) {
        onExitRuleChange(tradeId || 0, ruleId, label === "编辑" ? "edit" : "delete");
        return;
      }
      if (page === "orders" && ["全部", "已成交", "部成", "已撤销", "废单/拒单", "买入", "卖出"].some((item) => label === item || label.startsWith(`${item} `))) {
        const filterLabel = ["全部", "已成交", "部成", "已撤销", "废单/拒单"].find((item) => label === item || label.startsWith(`${item} `)) || label;
        const status = ({ "已成交": "FILLED", "部成": "PARTIALLY_FILLED", "已撤销": ["CANCELLED", "CANCELED", "CANCELLED_ORDER"], "废单/拒单": ["REJECTED", "FAILED", "EXPIRED"] } as Record<string, string | string[]>)[filterLabel];
        setFilter((current) => ({ ...current, status: status || (filterLabel === "全部" ? "ALL" : current.status), side: filterLabel === "买入" || filterLabel === "卖出" ? (filterLabel === "买入" ? "BUY" : "SELL") : current.side }));
        return;
      }
      if (page === "trades" && ["全部", "计划中", "进行中", "清仓中", "已结束", "已取消"].some((item) => label.startsWith(item))) {
        const status: string | string[] = label.startsWith("计划中") ? "PLANNED" : label.startsWith("进行中") ? "ACTIVE" : label.startsWith("清仓中") ? "CLOSING" : label.startsWith("已结束") ? ["CLOSED", "COMPLETED"] : label.startsWith("已取消") ? "CANCELLED" : "ALL";
        setFilter((current) => ({ ...current, status }));
        return;
      }
      if (page === "execution" && ["全部", "监控中", "执行中", "已完成", "已暂停"].some((item) => label.startsWith(item))) {
        const status: string | string[] = label.startsWith("监控中") ? ["MONITORING", "ARMED"] : label.startsWith("执行中") ? ["ACTIVE", "DISPATCHING", "SUBMITTED"] : label.startsWith("已完成") ? ["COMPLETED", "FILLED"] : label.startsWith("已暂停") ? "PAUSED" : "ALL";
        setFilter((current) => ({ ...current, status }));
        return;
      }
      if (page === "open" && label.includes("确认计划") && onCreateTradePlan) {
        onCreateTradePlan(prototypeFormValues(root));
        return;
      }
      if (["add", "reduce", "close"].includes(page) && label.includes("确认") && onActionSubmit) {
        onActionSubmit(page as "add" | "reduce" | "close", prototypeFormValues(root));
        return;
      }
      if (page === "risk" && label.includes("确认调整") && onRiskReferenceSubmit) {
        onRiskReferenceSubmit(prototypeFormValues(root));
        return;
      }
      if (page === "execution" && label.includes("一键暂停") && onPauseAll) {
        onPauseAll();
        return;
      }
      if (page === "execution" && label.includes("批量取消") && onCancelOpenOrders) {
        onCancelOpenOrders();
        return;
      }
      if (page === "execution" && (label.includes("创建执行") || label.includes("创建执行计划")) && onCreateExecutionPlan) {
        onCreateExecutionPlan();
        return;
      }
      const executionPlanId = Number(target.closest("tr,[data-execution-plan-id]")?.getAttribute("data-execution-plan-id"));
      if (page === "execution" && Number.isFinite(executionPlanId) && executionPlanId > 0 && label.includes("查看订单") && onExecutionOrderInspect) {
        onExecutionOrderInspect(executionPlanId);
        return;
      }
      if (page === "execution" && Number.isFinite(executionPlanId) && executionPlanId > 0 && onExecutionStatusChange) {
        if (label.includes("暂停")) { onExecutionStatusChange(executionPlanId, "PAUSED"); return; }
        if (label.includes("启动") || label.includes("恢复") || label.includes("启用")) { onExecutionStatusChange(executionPlanId, "ACTIVE"); return; }
        if (label.includes("取消")) { onExecutionStatusChange(executionPlanId, "CANCELLED"); return; }
      }
      if (page === "execution" && (label.includes("所属Trade") || label.includes("查看明细")) && selectedTradeId !== undefined) {
        onNavigate("trade", selectedTradeId);
        return;
      }
      if (page === "action" && label.includes("重新执行")) {
        onNavigate("execution", selectedTradeId);
        return;
      }
      if (page === "risk" && label.includes("查看历史")) {
        onNavigate("trade", selectedTradeId);
        return;
      }
      if (page === "overview" && label.includes("去设置") && onOpenSettings) {
        onOpenSettings();
        return;
      }
      if (page === "overview" && label.includes("刷新数据") && onRefresh) {
        onRefresh();
        return;
      }
      const orderId = Number(target.closest("tr")?.getAttribute("data-order-id"));
      if (page === "orders" && Number.isFinite(orderId) && orderId > 0 && onOrderCancel && label.includes("撤")) {
        onOrderCancel(orderId);
        return;
      }
      if (page === "orders" && Number.isFinite(orderId) && orderId > 0 && onOrderInspect && (label.includes("详情") || label.includes("诊断") || label.includes("查看"))) {
        onOrderInspect(orderId);
        return;
      }
      if (page === "orders" && label.includes("Trade") && selectedTradeId !== undefined) {
        onNavigate("trade", selectedTradeId);
        return;
      }
      if (page === "positions" && positionTradeCount !== 1 && (label.includes("查看") || label.includes("详情") || label.includes("加仓") || label.includes("减仓") || label.includes("清仓") || label.includes("调风控"))) {
        onNavigate("trades");
        return;
      }
      if ((label.includes("新增规则") || label.includes("添加规则")) && selectedTradeId !== undefined && onExitRuleCreate) {
        onExitRuleCreate(selectedTradeId);
        return;
      }
      if (label.includes("创建交易") || label.includes("新建交易") || label.includes("新建交易计划")) onNavigate("open", selectedTradeId);
      else if (label.includes("加仓")) onNavigate("add", selectedTradeId);
      else if (label.includes("减仓")) onNavigate("reduce", selectedTradeId);
      else if (label.includes("清仓")) onNavigate("close", selectedTradeId);
      else if (label.includes("调风控") || label.includes("调整参考")) onNavigate("risk", selectedTradeId);
      else if (label.includes("查看Trade") || label.includes("查看") || label.includes("详情") || label.includes("下钻详情") || label.includes("返回Trade") || label.includes("返回 Trade") || label.includes("返回母仓") || label.includes("交易 /")) onNavigate("trade", selectedTradeId);
      else if (label.includes("执行计划") || label.includes("去执行")) onNavigate("execution", selectedTradeId);
      else if (label.includes("返回")) onNavigate("trades", selectedTradeId);
    };
    root.addEventListener("click", click);
    return () => root.removeEventListener("click", click);
  }, [onNavigate, markup, tradeId, page, klineContext, onExecutionStatusChange, onOrderCancel, onExitRuleCreate, onExitRuleChange, onPauseAll, onCancelOpenOrders, onCreateExecutionPlan, onOrderInspect, onExecutionOrderInspect, onCreateTradePlan, onActionSubmit, onRiskReferenceSubmit, onOpenSettings, onRefresh]);
  useEffect(() => {
    const root = contentRef.current;
    if (!root || !["orders", "trades", "positions"].includes(page)) return;
    const input = root.querySelector("input[placeholder*='搜索']") as HTMLInputElement | null;
    if (!input) return;
    const onInput = () => setFilter((current) => ({ ...current, query: input.value }));
    input.addEventListener("input", onInput);
    const select = page === "trades" ? root.querySelector("select") as HTMLSelectElement | null : null;
    const onTypeChange = () => select && setFilter((current) => ({ ...current, type: select.value }));
    select?.addEventListener("change", onTypeChange);
    const pageSizeSelect = page === "trades" ? root.querySelectorAll("select")[1] as HTMLSelectElement | undefined : undefined;
    const onPageSizeChange = () => pageSizeSelect && setFilter((current) => ({ ...current, pageSize: Number(pageSizeSelect.value.match(/\d+/)?.[0] || 10), page: 1 }));
    pageSizeSelect?.addEventListener("change", onPageSizeChange);
    return () => {
      input.removeEventListener("input", onInput);
      select?.removeEventListener("change", onTypeChange);
      pageSizeSelect?.removeEventListener("change", onPageSizeChange);
    };
  }, [markup, page]);

  if (error) return <div className="flex flex-col items-start gap-3 p-6 text-sm text-error"><p>{error}</p><button type="button" onClick={() => { setError(null); setMarkup(null); setRetryToken((value) => value + 1); }} className="rounded-lg border border-error px-3 py-1.5 font-semibold text-error hover:bg-error-container">重试</button></div>;
  if (!markup) return <div className="p-6 text-sm text-on-surface-variant">正在载入页面…</div>;
  return <>
    <PrototypeMarkup markup={markup} accountId={accountId} contentRef={contentRef} />
    {copiedCode && <div role="status" className="fixed bottom-6 right-6 z-[120] rounded-lg bg-[#2d5a43] px-4 py-2.5 text-sm font-bold text-white shadow-lg">已复制股票代码：{copiedCode}</div>}
    {klineContext && <KLineModal
      isOpen={klineOpen}
      assetCode={klineContext.code}
      assetName={klineContext.name}
      onClose={() => setKlineOpen(false)}
      showAiPoolButton={false}
      showWatchlistButton={false}
      showNavigation={false}
      showAssetInfo
      tradeMarkers={klineContext.markers}
    />}
    {klineMount && klineContext && createPortal(
      <KLineModal
        embedded
        isOpen
        assetCode={klineContext.code}
        assetName={klineContext.name}
        onClose={() => undefined}
        showAiPoolButton={false}
        showWatchlistButton={false}
        showNavigation={false}
        showAssetInfo={false}
        tradeMarkers={klineContext.markers}
      />,
      klineMount,
    )}
  </>;
}
