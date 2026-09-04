"use client";

import { useEffect, useRef, useState } from "react";

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
  onNavigate: (page: PrototypePageKey, tradeId?: number) => void;
  accountId: number;
  refreshToken?: number;
  tradeId?: number | null;
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
};
type PrototypeFilter = { status?: string; side?: string; type?: string; query?: string };

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;

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
    throw new Error(`${fallback}（HTTP ${response.status}）`);
  }
  return response.json();
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
  }
  if (page === "risk") {
    root.querySelector("#newRiskPriceInput")?.setAttribute("data-prototype-field", "risk_reference_price");
    root.querySelector("textarea")?.setAttribute("data-prototype-field", "reason_text");
  }
  if (page === "add") {
    const reason = root.querySelector("select");
    reason?.setAttribute("name", "reason_code");
  }
  if (page === "reduce") {
    markButtons("reason_code", {
      "主动兑现利润": "PROFIT_TAKING", "达到预设目标": "TARGET_REACHED", "短期趋势转弱": "TREND_WEAKENING",
      "加仓确认失败": "FAILED_ADD", "时间窗口退出": "TIME_EXIT", "总体敞口降险": "RISK_REDUCTION",
    });
    markButtons("reduce_method", { "固定数量": "FIXED_QTY", "持仓比例": "POSITION_PCT", "目标数量": "TARGET_REMAINING_QTY", "目标仓位": "TARGET_REMAINING_PCT" });
    markButtons("quantity", { "25% (75股)": "75", "33% (100股)": "100", "50% (150股)": "150", "最大 (300股)": "300" });
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
  }
}

function formatMoney(value: unknown) {
  return typeof value === "number"
    ? `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : "—";
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
    PLANNED: "计划中", ACTIVE: "进行中", CLOSING: "清仓中", CLOSED: "已结束", CANCELLED: "已取消",
    DRAFT: "草稿", READY: "已确认", ARMED: "已就绪", MONITORING: "监控中", COMPLETED: "已完成", PAUSED: "已暂停",
    PENDING_SUBMIT: "等待发送", SUBMITTED: "已发送", ACCEPTED: "已接受", PARTIALLY_FILLED: "部分成交", FILLED: "已成交", REJECTED: "已拒单", EXPIRED: "已过期",
    TREND: "趋势交易", REBOUND: "反弹 / 波段", FIXED_TARGET: "固定目标", CUSTOM: "自定义", BUY: "买入", SELL: "卖出",
    OPEN: "建仓", ADD: "加仓", REDUCE: "减仓", CLOSE: "清仓", OPEN_LONG: "建仓", LIMIT: "限价委托", PERSISTENT_LIMIT: "持续限价", PRICE_TRIGGER: "到价触发", PRICE_RANGE: "价格区间触发",
  } as Record<string, string>)[String(value)] || String(value || "—");
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

function relatedTradeExecutionData(detail: { trade: any }, data: any) {
  const plans = Array.isArray(detail.trade?.plans) ? detail.trade.plans : [];
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

function writeDetailRows(root: Element, page: PrototypePageKey, data: any, detail?: { trade: any; position: any; rules: any[]; history: any[] }) {
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
    write(tables[0], legs, (leg) => [businessLabel(leg.leg_type || `Leg #${leg.sequence_no || "—"}`), String(leg.remaining_qty ?? leg.quantity ?? "—"), formatMoney(leg.average_entry_price ?? leg.avg_price), formatMoney(leg.current_risk_reference_price), formatMoney(leg.current_capital_risk), businessLabel(leg.status || "持有")]);
    write(tables[1], legs, (leg) => [businessLabel(leg.leg_type || `Leg #${leg.sequence_no || "—"}`), leg.source || leg.source_type || "—", String(leg.remaining_qty ?? leg.quantity ?? "—"), formatMoney(leg.average_entry_price ?? leg.avg_price), formatMoney(leg.current_risk_reference_price), businessLabel(leg.status || "持有"), "—"]);
  }
  if (page === "action") {
    const { orders, fills } = relatedTradeExecutionData(detail, data);
    const orderById = new Map<number, any>(orders.map((order: any) => [Number(order.id), order]));
    write(tables[0], fills, (fill) => {
      const order = orderById.get(Number(fill.order_id));
      return [String(fill.id ?? "—"), formatDateTime(fill.filled_at || fill.created_at), order?.broker_order_id || order?.client_order_id || "—", formatMoney(fill.price), String(fill.quantity ?? "—"), formatMoney(Number(fill.commission || 0) + Number(fill.tax || 0) + Number(fill.other_fee || 0))];
    });
  }
}

function replacePrototypeSection(root: Element, heading: string, message: string) {
  const headingElement = Array.from(root.querySelectorAll("h1, h2, h3, h4")).find((element) => (element.textContent || "").trim() === heading);
  if (!headingElement) return;
  let section: Element | null = headingElement.closest("div.bg-surface-container-lowest");
  if (!section) section = headingElement.parentElement;
  while (section && !(section.classList.contains("bg-surface-container-lowest") && (section.classList.contains("rounded-xl") || section.classList.contains("rounded-lg")))) section = section.parentElement;
  if (!section) return;
  const headingRow = headingElement.parentElement;
  const empty = root.ownerDocument.createElement("div");
  empty.className = "rounded-lg bg-surface-container-low p-4 text-xs text-on-surface-variant";
  empty.textContent = message;
  section.replaceChildren(headingRow || headingElement, empty);
}

function replaceRecentActions(root: Element, orders: any[], fills: any[]) {
  const headingElement = Array.from(root.querySelectorAll("h1, h2, h3, h4")).find((element) => (element.textContent || "").trim() === "最近系统动作");
  if (!headingElement) return;
  let section: Element | null = headingElement.closest("div.bg-surface-container-lowest");
  if (!section) section = headingElement.parentElement;
  while (section && !(section.classList.contains("bg-surface-container-lowest") && (section.classList.contains("rounded-xl") || section.classList.contains("rounded-lg")))) section = section.parentElement;
  if (!section) return;
  const body = root.ownerDocument.createElement("div");
  body.className = "space-y-2 text-xs";
  const entries = [
    ...(Array.isArray(orders) ? orders.map((order: any) => ({ kind: "委托", time: order.updated_at || order.created_at, text: `${businessLabel(order.side)} ${order.symbol || "—"} · ${order.quantity ?? "—"} 股 · ${formatMoney(order.price)} · ${businessLabel(order.status)} · ${order.broker_order_id || order.client_order_id || "—"}` })) : []),
    ...(Array.isArray(fills) ? fills.map((fill: any) => ({ kind: "成交回报", time: fill.filled_at || fill.created_at, text: `${fill.symbol || "—"} · ${fill.quantity ?? fill.filled_quantity ?? "—"} 股 @ ${formatMoney(fill.price)} · ${fill.broker_fill_id || "—"}` })) : []),
  ];
  if (!entries.length) {
    body.className = "rounded-lg bg-surface-container-low p-4 text-xs text-on-surface-variant";
    body.textContent = "当前账号暂无订单或成交流水。";
  } else {
    entries.sort((a, b) => String(b.time || "").localeCompare(String(a.time || "")));
    entries.forEach((entry) => {
      const row = root.ownerDocument.createElement("div");
      row.className = "flex items-start justify-between gap-3 rounded-lg bg-surface-container-low p-3";
      const content = root.ownerDocument.createElement("div");
      const kind = root.ownerDocument.createElement("div");
      kind.className = "font-semibold";
      kind.textContent = entry.kind;
      const detail = root.ownerDocument.createElement("div");
      detail.className = "mt-1 text-on-surface-variant";
      detail.textContent = entry.text;
      content.append(kind, detail);
      const time = root.ownerDocument.createElement("time");
      time.className = "shrink-0 font-mono text-on-surface-variant";
      time.dateTime = String(entry.time || "");
      time.textContent = entry.time ? new Date(entry.time).toLocaleString("zh-CN", { hour: "2-digit", minute: "2-digit" }) : "—";
      row.append(content, time);
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
  const cards = Array.from(root.querySelectorAll("div.bg-surface-container-lowest.rounded-xl")).filter((card) => Array.from(card.querySelectorAll("span")).some((span) => ["账户净资产", "可用现金", "当前总仓位", "账户当前总计划风险"].includes((span.textContent || "").trim())));
  const cardFor = (label: string) => cards.find((card) => Array.from(card.querySelectorAll("span")).some((span) => (span.textContent || "").trim() === label));
  const setValue = (card: Element | undefined, value: string) => {
    const target = card?.querySelector(".text-xl") || card?.querySelector(".text-2xl");
    if (target) target.textContent = value;
  };
  const equity = typeof account.equity === "number" ? account.equity : null;
  const availableCash = typeof account.available_cash === "number" ? account.available_cash : null;
  const exposure = typeof account.total_exposure_pct === "number" ? account.total_exposure_pct : null;
  const plannedRisk = trades.reduce((total: number, trade: any) => total + (Array.isArray(trade.plans) ? trade.plans.reduce((sum: number, plan: any) => sum + Number(plan.calculation_snapshot_json?.planned_risk_amount || 0), 0) : 0), 0);
  setValue(cardFor("账户净资产"), formatMoney(equity));
  setValue(cardFor("可用现金"), formatMoney(availableCash));
  setValue(cardFor("当前总仓位"), exposure === null ? "—" : `${(exposure * 100).toFixed(2)}%`);
  setValue(cardFor("账户当前总计划风险"), formatMoney(plannedRisk));
  const netAssetCard = cardFor("账户净资产");
  const netAssetChange = netAssetCard ? Array.from(netAssetCard.querySelectorAll<HTMLElement>("*")).find((element) => element.classList.contains("gap-1.5")) || null : null;
  if (netAssetChange) netAssetChange.textContent = "当前账号暂无当日资产变动数据";
  const cashCard = cardFor("可用现金");
  if (cashCard) replaceMetricAfterLabel(cashCard, "现金储备比例", equity && availableCash !== null ? `${((availableCash / equity) * 100).toFixed(2)}%` : "—");
  const exposureCard = cardFor("当前总仓位");
  const holdingCount = exposureCard ? Array.from(exposureCard.querySelectorAll<HTMLElement>("*")).find((element) => element.classList.contains("text-[11px]")) || null : null;
  if (holdingCount) holdingCount.textContent = `${positions.length} 只持仓标的`;
  const progress = exposureCard?.querySelector(".bg-tertiary.h-full") as HTMLElement | null;
  if (progress && exposure !== null) progress.style.width = `${Math.max(0, Math.min(100, exposure * 100))}%`;
  const riskCard = cardFor("账户当前总计划风险");
  const riskPct = riskCard?.querySelector(".text-xs.font-semibold");
  if (riskPct) riskPct.textContent = equity ? `${((plannedRisk / equity) * 100).toFixed(2)}%` : "—";
  const budget = typeof riskProfile.max_trade_risk_pct === "number" ? riskProfile.max_trade_risk_pct : null;
  const budgetLine = riskCard?.querySelector(".flex.items-center.justify-between.mt-1");
  if (budgetLine) budgetLine.textContent = budget === null ? "当前账号暂无风险预算数据" : `预算基准: ${(budget * 100).toFixed(2)}%`;
  const riskProgress = Array.from(root.querySelectorAll("span")).find((span) => (span.textContent || "").trim() === "计划风险进度")?.parentElement;
  if (riskProgress) {
    const line = riskProgress.querySelector(".font-mono");
    if (line) line.textContent = budget === null || !equity ? "— / —" : `${((plannedRisk / equity) * 100).toFixed(2)}% / ${(budget * 100).toFixed(2)}%`;
    const bar = riskProgress.parentElement?.querySelector(".bg-primary.h-full") as HTMLElement | null;
    if (bar && budget) bar.style.width = `${Math.max(0, Math.min(100, (plannedRisk / equity) / budget * 100))}%`;
  }
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

function replaceActionTrace(root: Element, detail: { trade: any }, data: any) {
  const heading = Array.from(root.querySelectorAll("h1, h2, h3, h4, span, div")).find((element) => (element.textContent || "").trim() === "全流程 4 级下钻链路 (Action Trace Pipeline)");
  if (!heading) return;
  let section: Element | null = heading.closest("div.bg-surface-container-lowest");
  if (!section) section = heading.parentElement;
  while (section && !(section.classList.contains("rounded-xl") || section.classList.contains("rounded-lg"))) section = section.parentElement;
  if (!section) return;
  const plans = detail.trade.plans || [];
  const plan = plans[plans.length - 1];
  const planIds = new Set(plans.map((item: any) => item.id));
  const executions = Array.from(new Map([
    ...plans.flatMap((item: any) => item.execution_plans || []),
    ...(data.execution_plans || []).filter((item: any) => planIds.has(item.trade_plan_id)),
  ].map((item: any, index: number) => [item.id ?? `${item.trade_plan_id}:${index}`, item])).values());
  const executionIds = new Set(executions.map((item: any) => item.id));
  const orders = Array.from(new Map([
    ...executions.flatMap((item: any) => item.orders || []),
    ...(data.orders || []).filter((item: any) => executionIds.has(item.execution_plan_id)),
  ].map((item: any, index: number) => [item.id ?? `${item.execution_plan_id}:${index}`, item])).values());
  const orderIds = new Set(orders.map((item: any) => item.id));
  const nestedFills = orders.flatMap((item: any) => item.fills || []);
  const accountFills = (data.fills || []).filter((item: any) => item.trade_id === detail.trade.id || orderIds.has(item.order_id));
  const fills = Array.from(new Map([...nestedFills, ...accountFills].map((item: any, index: number) => [item.id ?? `${item.order_id}:${item.filled_at}:${index}`, item])).values());
  const body = root.ownerDocument.createElement("div");
  body.className = "mt-3 space-y-2 text-xs";
  const cards: Array<[string, string, string]> = [
    ["第 1 层：TradePlan", plan ? `#${plan.id} · ${businessLabel(plan.action_type)} · ${businessLabel(plan.status)}` : "当前 Trade 暂无交易计划", plan ? `计划数量 ${plan.calculation_snapshot_json?.planned_qty ?? "—"} 股 · 参考价 ${formatMoney(plan.input_json?.reference_entry_price)}` : "—"],
    ["第 2 层：ExecutionPlan", executions.length ? executions.map((item: any) => `#${item.id} · ${businessLabel(item.status)}`).join("；") : "当前计划暂无执行方案", executions.length ? executions.map((item: any) => `${businessLabel(item.execution_type)} · 目标 ${item.target_qty ?? "—"} 股`).join("；") : "—"],
    ["第 3 层：Order", orders.length ? orders.map((item: any) => `#${item.id} · ${businessLabel(item.status)}`).join("；") : "当前执行方案暂无订单", orders.length ? orders.map((item: any) => `${businessLabel(item.side)} · ${item.quantity ?? "—"} 股 · ${item.broker_order_id || item.client_order_id || "—"}`).join("；") : "—"],
    ["第 4 层：Fill", fills.length ? `${fills.length} 笔成交回报` : "当前订单暂无成交回报", fills.length ? fills.map((item: any) => `${item.filled_quantity ?? item.quantity ?? "—"} 股 @ ${formatMoney(item.price ?? item.average_fill_price)}`).join("；") : "—"],
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
  body.className = "mt-3 space-y-2 text-xs";
  if (!plans.length) {
    body.className = "mt-3 rounded-lg bg-surface-container-low p-4 text-xs text-on-surface-variant";
    body.textContent = "当前账号暂无执行方案。";
  }
  plans.forEach((plan: any) => {
    const owner = trades.find((trade: any) => (trade.plans || []).some((candidate: any) => candidate.id === plan.trade_plan_id));
    const card = root.ownerDocument.createElement("div");
    card.className = "rounded-lg bg-surface-container-low p-3";
    card.setAttribute("data-execution-plan-id", String(plan.id));
    const params = plan.execution_params_json || plan.execution_params || {};
    const price = plan.execution_type === "PRICE_RANGE" ? `${formatMoney(params.low_price)} - ${formatMoney(params.high_price)}` : plan.execution_type === "PRICE_TRIGGER" ? `触发 ${formatMoney(params.trigger_price)}` : formatMoney(params.limit_price);
    const title = root.ownerDocument.createElement("div");
    title.className = "flex flex-wrap items-center justify-between gap-2 font-semibold";
    title.textContent = `${plan.symbol || "—"} · Trade #${owner?.id ?? "—"} · ${businessLabel(plan.side)} · ${businessLabel(plan.status)}`;
    const detail = root.ownerDocument.createElement("div");
    detail.className = "mt-1 text-on-surface-variant";
    detail.textContent = `${businessLabel(plan.execution_type)} · 目标 ${plan.target_qty ?? "—"} 股 · ${price} · ExecutionPlan #${plan.id}`;
    const actions = root.ownerDocument.createElement("div");
    actions.className = "mt-2 flex flex-wrap gap-2";
    const action = (label: string) => { const button = root.ownerDocument.createElement("button"); button.type = "button"; button.className = "rounded-md bg-surface-container-highest px-2 py-1 font-semibold"; button.textContent = label; return button; };
    if (["ACTIVE", "MONITORING", "ARMED"].includes(plan.status)) actions.appendChild(action("暂停"));
    if (plan.status === "PAUSED") actions.appendChild(action("继续"));
    if (!["COMPLETED", "CANCELLED", "EXPIRED"].includes(plan.status)) actions.appendChild(action("撤销"));
    actions.appendChild(action("查看订单"));
    card.append(title, detail, actions);
    body.appendChild(card);
  });
  section.replaceChildren(heading.parentElement || heading, body);
}

function replaceExecutionChannelStatus(root: Element, data: any) {
  const account = data.account || {};
  const connection = data.broker_status || {};
  const node = connection.node_status || {};
  const connected = connection.status === "CONNECTED" || connection.ok === true;
  const status = !connected
    ? "券商通道未连接"
    : node.agent_online === false
      ? "执行器离线"
      : node.reconciliation_required
        ? "待完成对账"
        : node.execution_enabled === false || node.paused
          ? "暂不可执行"
          : "正常在线";
  replaceTextEverywhere(root, "国投仿真", String(account.name || "当前券商账号"));
  replaceTextEverywhere(root, "12ms", "—");
  replaceTextEverywhere(root, "正常在线", status);
}

function replacePositionSummary(root: Element, data: any) {
  const account = data.account || {};
  const positions = Array.isArray(data.positions) ? data.positions : [];
  const trades = Array.isArray(data.trades) ? data.trades : [];
  const exposure = typeof account.total_exposure_pct === "number" ? `${(account.total_exposure_pct * 100).toFixed(2)}%` : "—";
  const maxExposure = typeof data.risk_profile?.max_total_exposure_pct === "number" ? `${(data.risk_profile.max_total_exposure_pct * 100).toFixed(2)}%` : "—";
  const symbols = new Set(positions.map((item: any) => String(item.symbol || "")).filter(Boolean));
  const tradeSymbols = new Set(trades.map((item: any) => String(item.symbol || "")).filter(Boolean));
  const lockedValue = positions.reduce((total: number, item: any) => total + Math.max(0, Number(item.quantity || 0) - Number(item.available_quantity || 0)) * Number(item.market_price || 0), 0);
  const activeTrades = trades.filter((item: any) => item.status === "ACTIVE").length;
  const asOf = account.updated_at ? new Date(account.updated_at).toLocaleString("zh-CN") : "—";
  const realized = typeof account.realized_pnl === "number" ? formatMoney(account.realized_pnl) : "—";
  const marketValue = typeof account.market_value === "number" ? formatMoney(account.market_value) : "—";
  const riskBudget = typeof data.risk_profile?.max_trade_risk_pct === "number" && typeof account.equity === "number"
    ? formatMoney(account.equity * data.risk_profile.max_trade_risk_pct)
    : "—";
  replaceTextEverywhere(root, "T+0实时", "最新有效价格");
  replaceCardMetric(root, "证券总资产 (NAV)", formatMoney(account.equity));
  replaceCardMetric(root, "持仓总市值", marketValue);
  replaceCardMetric(root, "可用现金额度", typeof account.available_cash === "number" ? formatMoney(account.available_cash) : "—");
  replaceLabeledStrong(root, "持仓证券合计:", String(symbols.size));
  replaceLabeledStrong(root, "今日已实现收益:", realized);
  replacePatternEverywhere(root, /\d+个标的\s*\/\s*\d+个Trade/g, `${symbols.size}个标的 / ${tradeSymbols.size}个Trade`);
  replacePatternEverywhere(root, /持仓证券合计:\s*—/g, `持仓证券合计: ${marketValue}`);
  replacePatternEverywhere(root, /标的\s*今日已实现收益:\s*——\.00/g, `标的 今日已实现收益: ${realized}`);
  replacePatternEverywhere(root, /最后同步:\s*[\d:]+/g, `最后同步: ${asOf}`);
  replaceTextEverywhere(root, "A股集中竞价中 (实时双向直连中金/华泰证券)", "收盘后，展示最近一次有效价格");
  replacePatternEverywhere(root, /持仓证券合计:\s*[^\s]+/g, `持仓证券合计: ${marketValue}`);
  replacePatternEverywhere(root, /可取现:\s*¥—/g, `可取现: ${typeof account.available_cash === "number" ? formatMoney(account.available_cash) : "—"}`);
  replacePatternEverywhere(root, /当前资金总仓位\s+上限\s+—\s+—\s+\/\s+—\s+已占用\s+—\s+剩余可开/g, `当前资金总仓位 上限 ${maxExposure} 已占用 ${exposure} 剩余可开 ${maxExposure === "—" || exposure === "—" ? "—" : `${Math.max(0, Number(maxExposure.replace("%", "")) - Number(exposure.replace("%", ""))).toFixed(2)}%`}`);
  replacePatternEverywhere(root, /NAV 硬止损额度上限:\s*—/g, `NAV 硬止损额度上限: ${riskBudget}`);
  replacePatternEverywhere(root, /已锁定垫\s+—k\s+\/\s+敞口\s+—\s+\(7\.98倍保护\)/g, `已锁定垫 ${lockedValue ? formatMoney(lockedValue) : "—"} / 敞口 ${exposure}（保护倍数暂无）`);
  replacePatternEverywhere(root, /在途锁定市值\s+—\s+\(占比总仓位\s+—\)/g, `在途锁定市值 ${lockedValue ? formatMoney(lockedValue) : "—"}（占比总仓位 ${lockedValue && account.market_value ? `${((lockedValue / account.market_value) * 100).toFixed(2)}%` : "—"}）`);
  replacePatternEverywhere(root, /\d+个 ACTIVE Trade 均已挂接云端保本追踪单/g, activeTrades ? `当前账号有 ${activeTrades} 笔进行中的 Trade` : "当前账号暂无进行中的 Trade");
  replaceTextEverywhere(root, "极度健康", "风险数据已加载");
  const tabCounts: Record<string, number> = {
    "全部持仓": positions.length,
    "多Trade标的": positions.filter((item: any) => trades.filter((trade: any) => trade.symbol === item.symbol).length > 1).length,
    "有在途T+1": positions.filter((item: any) => Number(item.available_quantity || 0) < Number(item.quantity || 0)).length,
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
  const source = page === "orders" ? data.orders : page === "positions" ? positions : data.trades;
  const filteredSource = source.filter((item: any) => {
    const statusMatches = !filter.status || filter.status === "ALL" || item.status === filter.status;
    const sideMatches = !filter.side || filter.side === "ALL" || item.side === filter.side;
    const relatedTrade = data.trades?.find((trade: any) => trade.symbol === item.symbol);
    const typeMatches = !filter.type || filter.type === "ALL" || (item.trade_type || relatedTrade?.trade_type) === filter.type;
    const query = (filter.query || "").trim().toLowerCase();
    const queryMatches = !query || [item.symbol, item.security_name, item.broker_order_id, item.client_order_id].some((value) => String(value || "").toLowerCase().includes(query));
    return statusMatches && sideMatches && typeMatches && queryMatches;
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
  const rows = filteredSource.map((item: any, index: number) => {
    const row = template.cloneNode(true) as HTMLTableRowElement;
    const execution = page === "orders"
      ? data.execution_plans?.find((candidate: any) => candidate.id === item.execution_plan_id)
      : item;
    const relatedTrade = data.trades?.find((trade: any) =>
      trade.id === item.trade_id
      || trade.id === item.trade?.id
      || (execution?.trade_plan_id !== undefined && (trade.plans || []).some((plan: any) => plan.id === execution.trade_plan_id))
      || (page === "positions" && trade.symbol === item.symbol),
    );
    const relatedTradeId = item.trade_id ?? item.trade?.id ?? relatedTrade?.id;
    if (relatedTradeId !== undefined) row.setAttribute("data-trade-id", String(relatedTradeId));
    if (item.id !== undefined) {
      if (page === "execution") row.setAttribute("data-execution-plan-id", String(item.id));
      if (page === "orders") row.setAttribute("data-order-id", String(item.id));
      if (item.action_type) row.setAttribute("data-action-type", String(item.action_type));
    }
    const position = positions.find((candidate: any) => candidate.symbol === item.symbol);
    const plan = relatedTrade?.plans?.[relatedTrade.plans.length - 1];
    const relatedPlan = data.trades?.flatMap((trade: any) => trade.plans || []).find((candidate: any) => candidate.id === (item.trade_plan_id ?? execution?.trade_plan_id));
    const snapshot = plan?.calculation_snapshot_json || {};
    const marketValue = Number(item.market_value ?? position?.market_value ?? 0);
    const exposure = Number(item.position_pct ?? item.exposure_pct ?? (data.account?.equity ? marketValue / Number(data.account.equity) : 0));
    const filledQuantity = Number(item.filled_quantity ?? item.filled_qty ?? 0);
    const executionParams = item.execution_params_json || item.execution_params || {};
    const executionRule = item.execution_type === "PRICE_RANGE"
      ? `${formatMoney(executionParams.low_price)} - ${formatMoney(executionParams.high_price)}`
      : item.execution_type === "PRICE_TRIGGER"
        ? `触发 ${formatMoney(executionParams.trigger_price)}`
        : formatMoney(executionParams.limit_price);
    const cells = Array.from(row.querySelectorAll("td"));
    const values = page === "positions"
      ? [String(index + 1), `${item.security_name || item.symbol || "—"} / ${item.symbol || "—"}`, businessLabel(relatedTrade?.trade_type), businessLabel(relatedTrade?.status), `${item.quantity ?? 0} / ${item.available_quantity ?? 0}`, `${formatMoney(item.average_cost)} / ${formatMoney(item.market_price)}`, formatMoney(item.unrealized_pnl), "—", "—", formatMoney(item.current_risk_reference_price), "—"]
      : page === "orders"
        ? [formatDateTime(item.created_at || item.updated_at), item.symbol || "—", relatedTrade?.id ? `Trade #${relatedTrade.id}` : "—", businessLabel(item.action_type || relatedPlan?.action_type), businessLabel(item.side), businessLabel(item.order_type || item.execution_type), formatMoney(item.average_fill_price ?? item.limit_price ?? item.price), `${item.quantity ?? item.target_qty ?? "—"} / ${filledQuantity}`, businessLabel(item.status), item.broker_order_id || item.client_order_id || "—"]
        : page === "execution"
          ? [`${item.symbol || "—"}`, businessLabel(item.action_type || relatedPlan?.action_type), `${businessLabel(item.side)} ${item.target_qty ?? item.quantity ?? "—"}`, executionRule, businessLabel(item.status)]
          : page === "overview"
            ? [`${item.symbol || "—"} ${item.symbol_name || item.security_name || ""}`.trim(), businessLabel(item.trade_type), businessLabel(item.status), `${position?.quantity ?? 0} / ${position?.available_quantity ?? 0}`, `${formatMoney(position?.market_price)} / ${formatMoney(position?.average_cost)}`, formatMoney(position?.unrealized_pnl), formatMoney(snapshot.planned_risk_amount ?? item.capital_risk), formatMoney(item.profit_retrace_risk), businessLabel(item.latest_action)]
            : [`${item.symbol || "—"} ${item.symbol_name || item.security_name || ""}`.trim(), businessLabel(item.trade_type), businessLabel(item.status), `${position?.quantity ?? 0} / ${position?.available_quantity ?? 0}`, `${formatMoney(position?.market_price)} / ${formatMoney(position?.average_cost)}`, formatMoney(position?.unrealized_pnl), formatMoney(snapshot.planned_risk_amount ?? item.capital_risk), formatMoney(item.profit_retrace_risk), businessLabel(item.latest_action), formatDateTime(item.created_at)];
    if (page === "positions") {
      const positionValues = [String(index + 1), `${item.security_name || item.symbol || "—"} / ${item.symbol || "—"}`, businessLabel(relatedTrade?.trade_type), businessLabel(relatedTrade?.status), `${item.quantity ?? 0} / ${item.available_quantity ?? 0}`, `${formatMoney(item.average_cost)} / ${formatMoney(item.market_price)}`, formatMoney(item.unrealized_pnl), `${(exposure * 100).toFixed(2)}%`, formatMoney(relatedTrade?.trade_risk_budget_amount ?? snapshot.planned_risk_amount), formatMoney(relatedTrade?.profit_retrace_risk), formatMoney(item.current_risk_reference_price ?? position?.current_risk_reference_price)];
      positionValues.forEach((value, cellIndex) => { if (cells[cellIndex]) cells[cellIndex].textContent = value; });
    }
    cells.slice(0, values.length).forEach((cell, cellIndex) => {
      cell.textContent = String(values[cellIndex] ?? "—");
    });
    return row;
  });
  tbody.replaceChildren(...rows);
}

function writePendingExecutionRows(root: Element, data: any) {
  const table = root.querySelector("table");
  const tbody = table?.querySelector("tbody");
  const template = tbody?.querySelector(":scope > tr");
  if (!table || !tbody || !template) return;
  const plans = (Array.isArray(data.trades) ? data.trades : []).flatMap((trade: any) =>
    (Array.isArray(trade.plans) ? trade.plans : [])
      .filter((plan: any) => ["READY", "ARMED"].includes(plan.status))
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

function clearUnhydratedNumbers(root: Element) {
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let current: Node | null = walker.nextNode();
  while (current) {
    const value = (current.nodeValue || "").trim();
    if (/^(?:[+-]?¥[\d,.]+|[+-]?\d[\d,.]*%|\d[\d,.]* 股|\d[\d,.]* 只|\d[\d,.]* 笔)$/.test(value)) nodes.push(current as Text);
    current = walker.nextNode();
  }
  nodes.forEach((node) => { node.nodeValue = "—"; });
}

function clearPrototypeMetricFragments(root: Element) {
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let current: Node | null = walker.nextNode();
  while (current) {
    if (/([+-]?¥[\d,.]+|[+-]?\d[\d,.]*%|\d[\d,.]* 股|\d[\d,.]* 只|\d[\d,.]* 笔)/.test(current.nodeValue || "")) nodes.push(current as Text);
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
    if (/^\s*\d+(?:\.\d+)?\s*$/.test(current.nodeValue || "")) numericOnly.push(current as Text);
    current = secondWalker.nextNode();
  }
  numericOnly.forEach((node) => { node.nodeValue = "—"; });
}

function hydrateDetailFields(root: Element, detail: { trade: any; position: any; rules: any[]; history: any[] }, data: any) {
  const trade = detail.trade;
  const position = detail.position || {};
  const plan = Array.isArray(trade.plans) && trade.plans.length ? trade.plans[trade.plans.length - 1] : null;
  const input = plan?.input_json || {};
  const calc = plan?.calculation_snapshot_json || {};
  const related = relatedTradeExecutionData(detail, data);
  const orders = related.orders;
  const fills = related.fills;
  const firstNumber = (...values: unknown[]) => values.find((value) => value !== null && value !== undefined && value !== "");
  const values: Record<string, string> = {
    symbol: String(trade.symbol || input.symbol || "—"),
    name: String(trade.symbol_name || input.security_name || trade.symbol || "—"),
    trade: `Trade #${trade.id}`,
    quantity: `${firstNumber(position.position_qty, position.quantity, calc.planned_qty, "—")} 股`,
    available: `可卖: ${firstNumber(position.available_quantity, "—")}`,
    avg: formatMoney(firstNumber(position.average_cost, position.avg_price, input.reference_entry_price)),
    price: formatMoney(firstNumber(position.market_price, input.current_price)),
    pnl: formatMoney(firstNumber(position.unrealized_pnl, trade.unrealized_pnl)),
    ref: formatMoney(firstNumber(position.position_risk_reference_price, input.risk_reference_price)),
    planQty: `${firstNumber(input.manual_planned_qty, calc.planned_qty, "—")}`,
    entry: formatMoney(firstNumber(input.reference_entry_price, calc.entry_price)),
    maxEntry: formatMoney(firstNumber(input.max_acceptable_entry_price, calc.max_entry_price)),
    orderAvg: formatMoney(firstNumber(orders[0]?.average_fill_price, orders[0]?.price, fills[0]?.price)),
    filled: `${orders.reduce((total: number, item: any) => total + Number(item.filled_quantity || 0), 0)} 股`,
  };
  ["安硕信息", "300380.SZ", "300380"].forEach((fixture) => replaceTextEverywhere(root, fixture, values.name === "—" ? values.symbol : values.name));
  replaceTextEverywhere(root, "Trade #—", values.trade);
  replaceTextEverywhere(root, "Trade #T-20241018-02", values.trade);
  replaceTextEverywhere(root, "Trade #TRD-20250115-001", values.trade);
  bindLabelValue(root, ["当前持仓", "总持仓"], values.quantity);
  bindLabelValue(root, ["可卖", "当前可卖"], values.available.replace("可卖: ", ""));
  bindLabelValue(root, ["均价", "综合成本"], values.avg);
  bindLabelValue(root, ["现价", "当前价"], values.price);
  bindLabelValue(root, ["浮动盈亏", "今日浮动盈亏"], values.pnl);
  bindLabelValue(root, ["风险参考", "原风险参考价", "当前风险参考"], values.ref);
  if (plan) {
    bindLabelValue(root, ["计划加仓量", "计划数量"], values.planQty);
    bindLabelValue(root, ["参考基准价", "参考加仓价", "参考卖出价"], values.entry);
    bindLabelValue(root, ["最高限价", "最高可接受加仓价", "最低可接受卖出价"], values.maxEntry);
    bindLabelValue(root, ["实际成交均价", "加仓后平均成本"], values.orderAvg);
    bindLabelValue(root, ["成交总金额"], formatMoney(firstNumber(orders[0]?.filled_notional, orders[0]?.notional, calc.planned_notional)));
    bindLabelValue(root, ["消耗风险预算", "本次新增风险"], formatMoney(firstNumber(calc.planned_risk_amount, plan.action_risk_budget_amount)));
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

function hydrateMarkup(root: Element, data: any, page: PrototypePageKey, detail?: { trade: any; position: any; rules: any[]; history: any[] }, filter: PrototypeFilter = {}) {
  const account = data.account || {};
  const positions = Array.isArray(data.positions) ? data.positions : [];
  const trades = Array.isArray(data.trades) ? data.trades : [];
  const totalUnrealizedPnl = typeof account.unrealized_pnl === "number"
    ? account.unrealized_pnl
    : positions.reduce((total: number, item: any) => total + Number(item.unrealized_pnl || 0), 0);
  const plannedRiskAmount = trades.reduce((total: number, trade: any) => total + (Array.isArray(trade.plans)
    ? trade.plans.reduce((sum: number, plan: any) => sum + Number(plan.calculation_snapshot_json?.planned_risk_amount || plan.action_risk_budget_amount || 0), 0)
    : 0), 0);
  const brokerConnected = data.broker_status?.status === "CONNECTED" || data.broker_status?.ok === true;
  const brokerReady = brokerConnected && data.broker_status?.node_status?.agent_online !== false && data.broker_status?.node_status?.execution_enabled !== false && !data.broker_status?.node_status?.paused && !data.broker_status?.node_status?.reconciliation_required;
  const risk = typeof account.equity === "number" && typeof data.risk_profile?.default_trade_risk_pct === "number"
    ? account.equity * data.risk_profile.default_trade_risk_pct
    : null;
  // Clear literal prototype metrics before applying the account response.
  // This prevents values from the design fixture leaking into an empty or
  // differently populated account.
  clearPrototypeFixtureValues(root, detail?.trade ? [String(detail.trade.symbol || ""), String(detail.trade.symbol_name || "")] : []);
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
  bindLabelValue(root, ["今日浮动盈亏", "浮动盈亏", "累计实现盈亏", "已实现盈亏"], formatMoney(totalUnrealizedPnl));
  bindLabelValue(root, ["持仓标的", "只持仓标的"], `${positions.length} 只`);
  bindLabelValue(root, ["订单总数", "今日订单", "今日流水"], `${Array.isArray(data.orders) ? data.orders.length : 0} 笔`);
  bindLabelValue(root, ["执行计划总数", "活跃执行"], `${Array.isArray(data.execution_plans) ? data.execution_plans.length : 0}`);
  bindLabelValue(root, ["计划风险", "账户总计划风险", "本金计划风险"], formatMoney(plannedRiskAmount || risk));
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
      `综合在途风险敞口: ${plannedRiskAmount ? formatMoney(plannedRiskAmount) : "—"} (${account.equity && plannedRiskAmount ? `${((plannedRiskAmount / account.equity) * 100).toFixed(2)}% NAV` : "—"})`);
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
      });
      replacePatternEverywhere(root, /全部\s*\(\d+\)/g, `全部 (${trades.length})`);
      replacePatternEverywhere(root, /计划中\s*\(\d+\)/g, `计划中 (${count("PLANNED")})`);
      replacePatternEverywhere(root, /进行中\s*\(\d+\)/g, `进行中 (${count("ACTIVE")})`);
      replacePatternEverywhere(root, /清仓中\s*\(\d+\)/g, `清仓中 (${count("CLOSING")})`);
      replacePatternEverywhere(root, /已结束\s*\(\d+\)/g, `已结束 (${trades.filter((item: any) => ["CLOSED", "COMPLETED"].includes(item.status)).length})`);
      replacePatternEverywhere(root, /已取消\s*\(\d+\)/g, `已取消 (${count("CANCELLED")})`);
      replacePatternEverywhere(root, /共\s*—\s*笔交易/g, `共 ${trades.length} 笔交易`);
      replaceExactText(root, "12", String(trades.length));
      const pages = Math.max(1, Math.ceil(trades.length / 10));
      replaceExactText(root, "第 1 / 2 页", `第 1 / ${pages} 页`);
      if (pages === 1) {
        Array.from(root.querySelectorAll("button")).filter((button) => (button.textContent || "").trim() === "2").forEach((button) => button.remove());
      }
    }
  }
  removePrototypeEntities(root, detail?.trade ? [String(detail.trade.symbol_name || ""), String(detail.trade.symbol || "")] : []);
  if (page === "overview") {
    replaceRecentActions(root, Array.isArray(data.orders) ? data.orders : [], Array.isArray(data.fills) ? data.fills : []);
    replacePrototypeSection(root, "账户敞口与技术分级监控快照", "当前账号暂无可展示的风险与技术快照。");
    replacePrototypeSection(root, "待处理事项", trades.length ? `当前账号有 ${trades.length} 笔 Trade，请进入交易列表查看当前动作。` : "当前账号暂无待处理事项。");
  }
  if (page === "orders") {
    const orders = Array.isArray(data.orders) ? data.orders : [];
    const count = (statuses: string[]) => orders.filter((item: any) => statuses.includes(item.status)).length;
    bindLabelValue(root, ["今日委托笔数"], String(orders.length));
    bindLabelValue(root, ["已完全成交"], String(count(["FILLED"])));
    bindLabelValue(root, ["部成 / 挂单中"], String(count(["PARTIALLY_FILLED", "PENDING_SUBMIT", "SUBMITTED", "ACCEPTED"])));
    replaceTextEverywhere(root, "73.8%", orders.length ? `${((count(["FILLED"]) / orders.length) * 100).toFixed(1)}%` : "—");
    replaceTextEverywhere(root, "42 条流水", `${orders.length} 条流水`);
    replaceExactText(root, "7", String(count(["CANCELLED", "REJECTED", "EXPIRED"])));
    replaceExactText(root, "6", String(count(["CANCELLED"])));
    replaceExactText(root, "1", String(count(["REJECTED"])));
    replacePatternEverywhere(root, /主动撤单\s+\d+/g, `主动撤单 ${count(["CANCELLED"])}`);
    replacePatternEverywhere(root, /拒单\s+\d+/g, `拒单 ${count(["REJECTED"])}`);
    const filledNotional = (side: string) => orders
      .filter((item: any) => item.side === side)
      .reduce((total: number, item: any) => total + Number(item.filled_quantity || 0) * Number(item.average_fill_price ?? item.price ?? 0), 0);
    replacePatternEverywhere(root, /买入\s+—M\s+\/\s+卖出\s+—K/g, `买入 ${filledNotional("BUY") ? formatMoney(filledNotional("BUY")) : "—"} / 卖出 ${filledNotional("SELL") ? formatMoney(filledNotional("SELL")) : "—"}`);
    replacePatternEverywhere(root, /RTT:\s*\d+ms/g, "RTT: —");
    root.querySelectorAll("#statusFilterTabs button").forEach((button) => {
      const label = (button.textContent || "").replace(/\s*\(\d+\)/, "").trim();
      const counts: Record<string, number> = { "全部": orders.length, "已成交": count(["FILLED"]), "部成": count(["PARTIALLY_FILLED"]), "已撤销": count(["CANCELLED"]), "废单/拒单": count(["REJECTED", "EXPIRED"]) };
      if (label in counts) button.textContent = `${label} (${counts[label]})`;
    });
    replaceTextEverywhere(root, "2023-09-08", "当前交易日");
    replaceTextEverywhere(root, "华泰证券 CTP-01 (柜台已就绪)", brokerReady ? "当前券商通道已就绪" : !brokerConnected ? "当前券商通道未连接" : data.broker_status?.node_status?.agent_online === false ? "券商已连接，执行器离线" : data.broker_status?.node_status?.reconciliation_required ? "券商已连接，待完成对账" : "券商已连接，暂不可执行");
    if (orders.length === 0) Array.from(root.querySelectorAll("button")).filter((button) => ["1", "2", "3"].includes((button.textContent || "").trim())).forEach((button) => button.remove());
    replaceTextEverywhere(root, "CTP/L2 专线平稳", brokerReady ? "券商连接正常" : !brokerConnected ? "券商未连接" : data.broker_status?.node_status?.agent_online === false ? "券商已连接，执行器离线" : data.broker_status?.node_status?.reconciliation_required ? "券商已连接，待完成对账" : "券商已连接，暂不可执行");
    replacePatternEverywhere(root, /今日委托笔数\s+receipt_long\s+\d+/g, `今日委托笔数 receipt_long ${orders.length}`);
    replacePatternEverywhere(root, /已完全成交\s+check_circle\s+\d+/g, `已完全成交 check_circle ${count(["FILLED"])}`);
    replacePatternEverywhere(root, /部成 \/ 挂单中\s+hourglass_bottom\s+\d+/g, `部成 / 挂单中 hourglass_bottom ${count(["PARTIALLY_FILLED", "PENDING_SUBMIT", "SUBMITTED", "ACCEPTED"])}`);
    replacePatternEverywhere(root, /已撤单 \/ 废单\s+cancel\s+\d+\s+主动撤单\s+\d+\s+·\s+拒单\s+\d+/g, `已撤单 / 废单 cancel ${count(["CANCELLED", "REJECTED", "EXPIRED"])} 主动撤单 ${count(["CANCELLED"])} · 拒单 ${count(["REJECTED"])}`);
    replacePatternEverywhere(root, /实时订单明细 \(Order Book Log\) 共 \d+ 条记录/g, `实时订单明细 (Order Book Log) 共 ${orders.length} 条记录`);
    replacePatternEverywhere(root, /显示第 \d+ 到 \d+ 项，共 \d+ 条流水/g, `显示第 ${orders.length ? 1 : 0} 到 ${orders.length} 项，共 ${orders.length} 条流水`);
    const drawer = root.querySelector("#orderDetailDrawer");
    drawer?.remove();
  }
  if (page === "execution") {
    const plans = Array.isArray(data.execution_plans) ? data.execution_plans : [];
    const tradePlans = trades.flatMap((trade: any) => trade.plans || []).filter((plan: any) => ["READY", "ARMED"].includes(plan.status));
    const executionReadiness = brokerReady ? "引擎就绪" : data.broker_status?.node_status?.agent_online === false ? "执行器离线" : "当前不可执行";
    replaceTextEverywhere(root, "引擎就绪", executionReadiness);
    bindLabelValue(root, ["待执行计划"], `${tradePlans.length} 笔待路由`);
    bindLabelValue(root, ["活跃监控中"], `${plans.filter((plan: any) => ["ARMED", "MONITORING"].includes(plan.status)).length} 笔挂机盯盘`);
    bindLabelValue(root, ["今日已执行"], `${plans.filter((plan: any) => plan.status === "COMPLETED").length} 笔`);
    replacePatternEverywhere(root, /\d+\s+笔待路由/g, `${tradePlans.length} 笔待路由`);
    replacePatternEverywhere(root, /\d+\s+笔挂机盯盘/g, `${plans.filter((plan: any) => ["ARMED", "MONITORING"].includes(plan.status)).length} 笔挂机盯盘`);
    replacePatternEverywhere(root, /\d+\s+笔\s+\([^)]*\)/g, `${plans.filter((plan: any) => plan.status === "COMPLETED").length} 笔`);
    replaceExecutionChannelStatus(root, data);
    replaceExecutionMonitor(root, plans, trades);
  }
  if (page === "positions") replacePositionSummary(root, data);
  if (detail?.trade) {
    const trade = detail.trade;
    replaceExactText(root, "安硕信息", String(trade.symbol_name || trade.symbol || "—"));
    replaceExactText(root, "300 股", `${detail.position?.position_qty ?? detail.position?.quantity ?? "—"} 股`);
    replaceExactText(root, "Trade #TRD-20250115-001", `Trade #${trade.id}`);
    replaceExactText(root, "进行中", trade.status === "ACTIVE" ? "进行中" : String(trade.status || "—"));
    replaceExactText(root, "交易类型：趋势交易", `交易类型：${trade.trade_type || "—"}`);
    replaceExactText(root, "风险参考：¥29.47", `风险参考：${formatMoney(detail.position?.position_risk_reference_price)}`);
    hydrateDetailFields(root, detail, data);
    if (page === "action") replaceActionTrace(root, detail, data);
  }
  if (["overview", "trades", "orders", "positions"].includes(page)) writeTableRows(root, page, data, filter);
  if (page === "execution") writePendingExecutionRows(root, data);
  writeDetailRows(root, page, data, detail);
  if (detail?.trade && page === "trade") {
    replaceDetailList(root, "生命周期时间线", detail.trade.plans || [], (plan) => `${plan.action_type || plan.action || "—"} #${plan.sequence_no || "—"} · ${businessLabel(plan.status)} · ${plan.calculation_snapshot_json?.planned_qty ?? "—"} 股 · ${formatDateTime(plan.created_at)}`, "当前 Trade 暂无交易计划流水。", false, true);
    replaceDetailList(root, "退出规则", detail.rules || [], (rule) => `${rule.trigger_type || "—"} → ${rule.action_type || "—"} · ${rule.enabled ? "启用" : "停用"}`, "当前 Trade 暂无退出规则。", true);
  }
  if (detail?.trade && page === "risk") {
    replaceDetailList(root, "查看历史", detail.history || [], (item) => `${formatDateTime(item.created_at)} · ${formatMoney(item.old_price ?? item.previous_price)} → ${formatMoney(item.new_price)} · ${item.reason || "未填写依据"}`, "当前 Trade 暂无风险参考调整记录。");
  }
  if (["open", "add", "reduce", "close", "action"].includes(page)) clearPrototypeInputValues(root);
  const rows = page === "orders" ? data.orders : page === "positions" ? positions : page === "execution" ? [...(data.execution_plans || []), ...trades.flatMap((trade: any) => trade.plans || []).filter((plan: any) => ["READY", "ARMED"].includes(plan.status))] : trades;
  if (!Array.isArray(rows) || rows.length === 0) {
    root.querySelectorAll("table tbody").forEach((tbody) => {
      tbody.innerHTML = `<tr><td colspan="12" class="px-4 py-8 text-center text-xs text-on-surface-variant">当前账号暂无交易数据</td></tr>`;
    });
  }
}

export default function PrototypeTradingPage({ page, onNavigate, accountId, refreshToken = 0, tradeId, onExecutionStatusChange, onOrderCancel, onExitRuleCreate, onExitRuleChange, onPauseAll, onCancelOpenOrders, onCreateExecutionPlan, onOrderInspect, onExecutionOrderInspect, onCreateTradePlan, onActionSubmit, onRiskReferenceSubmit }: Props) {
  const [markup, setMarkup] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<PrototypeFilter>({});
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setMarkup(null);
    setError(null);
    if (!API_BASE) {
      Promise.resolve().then(() => {
        if (!cancelled) setError("NEXT_PUBLIC_MARKET_REVIEW_API_URL 未配置");
      });
      return () => { cancelled = true; };
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
          fetch(`${API_BASE}/api/trades/${encodeURIComponent(String(tradeId))}?account_id=${encodeURIComponent(String(accountId))}`, { cache: "no-store" }),
          fetch(`${API_BASE}/api/trades/${encodeURIComponent(String(tradeId))}/position-state?account_id=${encodeURIComponent(String(accountId))}`, { cache: "no-store" }),
          fetch(`${API_BASE}/api/trades/${encodeURIComponent(String(tradeId))}/exit-rules?account_id=${encodeURIComponent(String(accountId))}`, { cache: "no-store" }),
          fetch(`${API_BASE}/api/trades/${encodeURIComponent(String(tradeId))}/risk-reference-history?account_id=${encodeURIComponent(String(accountId))}`, { cache: "no-store" }),
        ]).then(async ([tradeResponse, positionResponse, rulesResponse, historyResponse]) => {
          const [tradeResult, positionResult, rulesResult, historyResult] = await Promise.all([
            readApiResponse(tradeResponse, "交易详情读取失败"),
            readApiResponse(positionResponse, "持仓状态读取失败"),
            readApiResponse(rulesResponse, "退出规则读取失败"),
            readApiResponse(historyResponse, "风险历史读取失败"),
          ]);
          return { trade: tradeResult.item, position: positionResult.item, rules: rulesResult.items || [], history: historyResult.items || [] };
        })
      : Promise.resolve(null);
    Promise.all([
      fetch(`/prototype-pages/${files[page]}/code.html`, { cache: "no-store" }).then((response) => {
        if (!response.ok) throw new Error(`原型页面读取失败（HTTP ${response.status}）`);
        return response.text();
      }),
      fetch(`${API_BASE}/api/trading/overview?account_id=${encodeURIComponent(String(accountId))}`, { cache: "no-store" })
        .then((response) => readApiResponse(response, "交易数据读取失败")),
      detailPromise,
    ])
      .then(([html, overview, detail]) => {
        if (cancelled) return;
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
        decoratePrototypeFormControls(main, page);
        hydrateMarkup(main, overview, page, detail || undefined, filter);
        setError(null);
        setMarkup(main.innerHTML);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "原型页面读取失败");
      });
    return () => { cancelled = true; };
  }, [page, accountId, refreshToken, tradeId, filter]);
  useEffect(() => {
    setFilter({});
  }, [page, accountId, tradeId]);

  useEffect(() => {
    const root = contentRef.current;
    if (!root) return;
    const click = (event: MouseEvent) => {
      const target = (event.target as HTMLElement).closest("button, a");
      if (!target) return;
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
      const label = textOf(target);
      const ruleId = Number(target.closest("[data-exit-rule-id]")?.getAttribute("data-exit-rule-id"));
      if (page === "trade" && label.includes("查看动作详情") && selectedTradeId !== undefined) {
        onNavigate("action", selectedTradeId);
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
      if (page === "orders" && ["全部", "已成交", "部成", "已撤销", "废单/拒单", "买入", "卖出"].some((item) => label === item)) {
        const status = ({ "已成交": "FILLED", "部成": "PARTIALLY_FILLED", "已撤销": "CANCELLED", "废单/拒单": "REJECTED" } as Record<string, string>)[label];
        setFilter((current) => ({ ...current, status: status || (label === "全部" ? "ALL" : current.status), side: label === "买入" || label === "卖出" ? (label === "买入" ? "BUY" : "SELL") : current.side }));
        return;
      }
      if (page === "trades" && ["全部", "计划中", "进行中", "清仓中", "已结束", "已取消"].some((item) => label.startsWith(item))) {
        const status = label.startsWith("计划中") ? "PLANNED" : label.startsWith("进行中") ? "ACTIVE" : label.startsWith("清仓中") ? "CLOSING" : label.startsWith("已结束") ? "CLOSED" : label.startsWith("已取消") ? "CANCELLED" : "ALL";
        setFilter((current) => ({ ...current, status }));
        return;
      }
      if (page === "execution" && ["全部", "监控中", "执行中", "已完成", "已暂停"].some((item) => label.startsWith(item))) {
        const status = label.startsWith("监控中") ? "MONITORING" : label.startsWith("执行中") ? "ACTIVE" : label.startsWith("已完成") ? "COMPLETED" : label.startsWith("已暂停") ? "PAUSED" : "ALL";
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
  }, [onNavigate, markup, tradeId, page, onExecutionStatusChange, onOrderCancel, onExitRuleCreate, onExitRuleChange, onPauseAll, onCancelOpenOrders, onCreateExecutionPlan, onOrderInspect, onExecutionOrderInspect, onCreateTradePlan, onActionSubmit, onRiskReferenceSubmit]);
  useEffect(() => {
    const root = contentRef.current;
    if (!root || !["orders", "trades"].includes(page)) return;
    const input = root.querySelector("input[placeholder*='搜索']") as HTMLInputElement | null;
    if (!input) return;
    const onInput = () => setFilter((current) => ({ ...current, query: input.value }));
    input.addEventListener("input", onInput);
    const select = page === "trades" ? root.querySelector("select") as HTMLSelectElement | null : null;
    const onTypeChange = () => select && setFilter((current) => ({ ...current, type: select.value }));
    select?.addEventListener("change", onTypeChange);
    return () => { input.removeEventListener("input", onInput); select?.removeEventListener("change", onTypeChange); };
  }, [markup, page]);

  if (error) return <div className="p-6 text-sm text-error">{error}</div>;
  if (!markup) return <div className="p-6 text-sm text-on-surface-variant">正在载入页面…</div>;
  return <div ref={contentRef} data-account-id={accountId} dangerouslySetInnerHTML={{ __html: markup }} />;
}
