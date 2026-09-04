"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Download,
  Plus,
  RefreshCw,
  Save,
} from "lucide-react";
import KLineModal from "./KLineModal";

const API_BASE = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;
type PickField =
  | "reference_entry_price"
  | "max_acceptable_entry_price"
  | "risk_reference_price"
  | "target_price"
  | "expected_price";
type FormState = {
  symbol: string;
  security_name: string;
  current_price: string;
  reference_entry_price: string;
  max_acceptable_entry_price: string;
  risk_reference_price: string;
  plan_risk_pct: string;
  target_type: "FIXED_TARGET" | "TREND_FOLLOWING";
  trade_type: "TREND" | "REBOUND" | "FIXED_TARGET" | "CUSTOM";
  target_price: string;
  expected_price: string;
  target_zone_lower: string;
  target_zone_upper: string;
  holding_period_days: string;
  time_invalidation_condition: string;
  manual_planned_qty: string;
  risk_reference_note: string;
  thesis: string;
  selection_source_type: "MANUAL" | "STRATEGY" | "UNKNOWN";
  selection_strategy: string;
  selection_stage: string;
  selection_snapshot_date: string;
};
type Account = {
  account_equity: number;
  available_cash: number;
  current_invested_amount: number;
  default_risk_pct: number;
  max_single_position_pct: number;
  max_total_position_pct: number;
};
const initial: FormState = {
  symbol: "",
  security_name: "",
  current_price: "",
  reference_entry_price: "",
  max_acceptable_entry_price: "",
  risk_reference_price: "",
  plan_risk_pct: "0.80",
  target_type: "TREND_FOLLOWING",
  trade_type: "TREND",
  target_price: "",
  expected_price: "",
  target_zone_lower: "",
  target_zone_upper: "",
  holding_period_days: "",
  time_invalidation_condition: "",
  manual_planned_qty: "",
  risk_reference_note: "",
  thesis: "",
  selection_source_type: "MANUAL",
  selection_strategy: "",
  selection_stage: "",
  selection_snapshot_date: "",
};
export type TradePlanPrefill = {
  symbol: string;
  securityName: string;
  sourceType: "MANUAL" | "STRATEGY" | "UNKNOWN";
  strategy?: string | null;
  stage?: string | null;
  snapshotDate?: string | null;
};
const emptyAccount: Account = {
  account_equity: 0,
  available_cash: 0,
  current_invested_amount: 0,
  default_risk_pct: 0,
  max_single_position_pct: 0,
  max_total_position_pct: 0,
};

async function request(path: string, options?: RequestInit, accountId?: number) {
  const scopedPath = accountId === undefined ? path : `${path}${path.includes("?") ? "&" : "?"}account_id=${encodeURIComponent(String(accountId))}`;
  try {
    const response = await fetch(`${API_BASE}${scopedPath}`, {
      cache: "no-store",
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options?.headers || {}),
      },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      const detail = payload?.detail;
      const message = typeof detail === "string"
        ? detail
        : typeof detail?.message === "string"
          ? detail.message
          : "交易服务未能完成本次请求，请检查填写内容后重试。";
      throw new Error(message);
    }
    return response.json();
  } catch (error) {
    if (error instanceof TypeError && /fetch/i.test(error.message))
      throw new Error("无法连接交易服务，请确认服务正在运行后重试。");
    throw error;
  }
}
function label(text: string, required = false) {
  return (
    <span className="mb-1 block text-xs font-bold text-[#686d68]">
      {text}
      {required && <em className="ml-1 text-rose-600">*</em>}
    </span>
  );
}
function money(value: any) {
  return typeof value === "number"
    ? `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`
    : "—";
}
function pct(value: any) {
  return typeof value === "number" ? `${(value * 100).toFixed(2)}%` : "—";
}
function percentageInput(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? (number * 100).toFixed(2) : "";
}
function limitingFactorLabel(value: string | undefined) {
  return (
    (
      {
        RISK_BUDGET: "单笔风险额度",
        SINGLE_POSITION_LIMIT: "单只仓位上限",
        CASH_LIMIT: "可用资金",
        TOTAL_POSITION_LIMIT: "总仓位上限",
      } as Record<string, string>
    )[value || ""] || "—"
  );
}
function strategyStageLabel(value: string | null | undefined) {
  return ({
    PRE_FIRST_TURN: "早期准备",
    FIRST_TURN_WINDOW: "首次转强",
    POST_FIRST_WAVE: "第一波已完成",
    OUTSIDE_A_PRE: "未进入 A-Pre",
    PRE_READY: "底部准备",
    EARLY_TURN: "早期转强",
  } as Record<string, string>)[value || ""] || value || "策略阶段未记录";
}
function calculationMessage(item: string, calculation: any) {
  if (item === "recommended_qty must be greater than 0")
    return `按当前${limitingFactorLabel(calculation?.limiting_factor)}，可买数量不足 100 股，暂不能建立计划。请调整交易设置或降低参考入场价。`;
  if (item === "expected_price must be greater than reference_entry_price for TREND_FOLLOWING")
    return "趋势跟踪的预期价格应高于参考入场价。";
  return item;
}
function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}
function planStatusLabel(status: string | undefined) {
  return ({
    DRAFT: "草稿",
    READY: "已确认",
    ARMED: "已就绪",
    PARTIALLY_EXECUTED: "部分成交",
    EXECUTED: "已成交",
    CANCELLED: "已取消",
    EXPIRED: "已过期",
    INVALIDATED: "已失效",
    ACTIVE: "执行中",
    PAUSED: "已暂停",
    COMPLETED: "已完成",
    REJECTED: "已拒绝",
  } as Record<string, string>)[status || ""] || "状态未记录";
}
function actionLabel(action: string | undefined) {
  return ({ OPEN: "建仓", ADD: "加仓", REDUCE: "减仓", CLOSE: "清仓" } as Record<string, string>)[action || ""] || "计划动作";
}
function formatPlanMarkdown(item: any) {
  const input = item.input_json || {};
  const calc = item.calculation_snapshot_json || {};
  const account = item.account_settings_json || {};
  const line = (label: string, value: string) => `- ${label}：${value}`;
  const price = (value: unknown) => money(Number(value));
  const quantity = (value: unknown) => value == null ? "未计算" : `${value} 股`;
  const targetSection = input.target_type === "FIXED_TARGET"
    ? [line("目标方式", "固定目标"), line("目标价", price(input.target_price)), line("潜在盈利", money(calc.target_profit_amount)), line("计划收益率", pct(calc.target_return_pct)), line("收益风险比", calc.reward_risk_ratio == null ? "未计算" : `${Number(calc.reward_risk_ratio).toFixed(2)} : 1`)]
    : [line("退出方式", input.trade_type === "REBOUND" ? "反弹目标区" : "趋势跟踪"), line("第一空间参考", price(input.expected_price)), line("第一空间参考对应R", calc.expected_reward_r == null ? "未计算" : `${Number(calc.expected_reward_r).toFixed(2)}R`), ...(input.trade_type === "REBOUND" ? [line("目标区", `${price(input.target_zone_lower)} - ${price(input.target_zone_upper)}`), line("预期持有周期", `${input.holding_period_days || "未设置"} 个交易日`), line("时间失效条件", input.time_invalidation_condition || "未设置")] : []), line("1R", price(calc.r1_price)), line("2R", price(calc.r2_price)), line("3R", price(calc.r3_price))];
  return [
    `# 交易计划：${item.symbol} ${item.security_name}`,
    "",
    line("计划状态", planStatusLabel(item.status)),
    line("创建时间", item.created_at ? new Date(item.created_at).toLocaleString("zh-CN") : "未记录"),
    "",
    "## 价格与风险",
    line("参考入场价", price(input.reference_entry_price)),
    line("最高可接受价", price(input.max_acceptable_entry_price)),
    line("风险参考价", price(input.risk_reference_price)),
    line("价格风险", pct(calc.price_risk_pct)),
    line("风险预算", `${money(calc.risk_budget_amount)} / ${pct(input.plan_risk_pct)}`),
    line("若按风险参考价退出的预计亏损", `${money(calc.planned_risk_amount)} / 账户 ${pct(calc.planned_account_risk_pct)}`),
    "",
    "## 仓位计划",
    line("最终计划数量", quantity(calc.planned_qty)),
    line("预计投入", money(calc.planned_notional)),
    line("本次资金仓位", pct(calc.planned_position_pct)),
    line("交易后总仓位", pct(calc.post_trade_total_position_pct)),
    line("最终限制", limitingFactorLabel(calc.limiting_factor)),
    line("风险预算允许", quantity(calc.qty_by_risk)),
    line("单只股票最大仓位允许", quantity(calc.qty_by_single_position)),
    line("可用现金允许", quantity(calc.qty_by_cash)),
    line("账户总仓位允许", quantity(calc.qty_by_total_position)),
    "",
    "## 收益 / 空间",
    ...targetSection,
    "",
    "## 账户依据",
    line("账户净资产", money(account.account_equity)),
    line("可用现金", money(account.available_cash)),
    line("账户最大总仓位", pct(account.max_total_position_pct)),
    "",
    "## 交易逻辑",
    input.thesis?.trim() || "未填写",
    "",
    "## 风险参考说明",
    input.risk_reference_note?.trim() || "未填写",
    "",
    "> 提示：实际亏损可能因跳空、滑点等高于计划值。",
  ].join("\n");
}
function downloadPlanMarkdown(item: any) {
  const blob = new Blob(["\uFEFF", formatPlanMarkdown(item)], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `交易计划_${item.symbol}_${item.security_name}.md`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
function ErrorHint({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="fixed bottom-5 right-5 z-[80] flex max-w-md items-start gap-2 rounded-lg border border-[#f2b8b5] bg-[#fff8f7] px-4 py-3 text-sm font-medium text-[#93000a] shadow-[0_8px_24px_rgba(25,28,29,0.18)]" role="alert">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{message}</span>
    </div>
  );
}
function isTradePlanList(mode: "list" | "new") {
  return mode === "list";
}

export default function TradePlansPage({
  onOpenSettings,
  prefill,
  initialForm,
  onPrefillConsumed,
  accountId,
  initialMode = "list",
}: {
  onOpenSettings?: () => void;
  prefill?: TradePlanPrefill | null;
  initialForm?: Partial<FormState>;
  onPrefillConsumed?: () => void;
  accountId?: number;
  initialMode?: "list" | "new";
}) {
  const [modeState, setMode] = useState<"list" | "new">(initialMode);
  const mode: any = modeState;
  const [form, setForm] = useState<FormState>(initial);
  const [draftId, setDraftId] = useState<number | null>(null);
  const [account, setAccount] = useState<Account>(emptyAccount);
  const [accountContext, setAccountContext] = useState<any>(null);
  const [items, setItems] = useState<any[]>([]);
  const [query, setQuery] = useState("");
  const [pickField, setPickField] = useState<PickField>(
    "reference_entry_price",
  );
  const [calculation, setCalculation] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const body = useMemo(
    () => ({
      plan: {
        ...form,
        trade_type: form.trade_type,
        current_price: form.current_price ? Number(form.current_price) : null,
        reference_entry_price: Number(form.reference_entry_price),
        max_acceptable_entry_price: Number(form.max_acceptable_entry_price),
        risk_reference_price: Number(form.risk_reference_price),
        plan_risk_pct: Number(form.plan_risk_pct) / 100,
        target_price: form.target_price ? Number(form.target_price) : null,
        expected_price: form.target_type === "TREND_FOLLOWING" ? Number(form.expected_price) : null,
        target_zone_lower: form.trade_type === "REBOUND" && form.target_zone_lower ? Number(form.target_zone_lower) : null,
        target_zone_upper: form.trade_type === "REBOUND" && form.target_zone_upper ? Number(form.target_zone_upper) : null,
        holding_period_days: form.trade_type === "REBOUND" && form.holding_period_days ? Number(form.holding_period_days) : null,
        time_invalidation_condition: form.trade_type === "REBOUND" ? form.time_invalidation_condition : null,
        manual_planned_qty: form.manual_planned_qty
          ? Number(form.manual_planned_qty)
          : null,
      },
      instrument: { quantity_step: 100 },
    }),
    [form],
  );
  async function load() {
    setBusy(true);
    setError(null);
    try {
      const [trades, settings, overview] = await Promise.all([
        request("/api/trades", undefined, accountId),
        request("/api/trade-settings", undefined, accountId),
        request("/api/trading/overview", undefined, accountId),
      ]);
      const groupedPlans = (trades.items || []).flatMap((trade: any) =>
        (trade.plans || []).map((plan: any) => ({
          ...plan,
          trade_id: trade.id,
          trade_status: trade.status,
          trade_type: trade.trade_type,
          playbook_id: trade.playbook_id,
          thesis: trade.thesis,
          legs: trade.legs,
        })),
      );
      setItems(groupedPlans);
      setAccount(settings.settings);
      setAccountContext({
        account: overview.account,
        risk_profile: overview.risk_profile,
        current_invested_amount: overview.account.market_value,
        current_exposure_pct: overview.account.total_exposure_pct,
        is_ready: settings.settings.is_ready,
      });
      setForm((current) => ({
        ...current,
        plan_risk_pct:
          percentageInput(settings.settings.default_risk_pct) ||
          current.plan_risk_pct,
      }));
    } catch (e) {
      setError(errorMessage(e, "交易计划读取失败"));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    load();
  }, [accountId]);
  useEffect(() => {
    if (!prefill) return;
    const strategySource = prefill.sourceType === "STRATEGY";
    const strategyName = prefill.strategy || "策略筛选";
    const stage = strategyStageLabel(prefill.stage);
    const snapshotDate = prefill.snapshotDate || "";
    setForm({
      ...initial,
      symbol: prefill.symbol.split(".")[0],
      security_name: prefill.securityName,
      selection_source_type: prefill.sourceType,
      selection_strategy: strategySource ? strategyName : "",
      selection_stage: strategySource ? stage : "",
      selection_snapshot_date: strategySource ? snapshotDate : "",
      thesis: strategySource
        ? `${strategyName} · ${stage}${snapshotDate ? `（${snapshotDate}）` : ""}\n选股逻辑：由该策略筛选，当前处于上述阶段。结合 K 线确认入场、风险参考价和仓位后执行。`
        : "",
    });
    setQuery(`${prefill.symbol.split(".")[0]} ${prefill.securityName}`);
    setDraftId(null);
    setCalculation(null);
    setMode("new");
    onPrefillConsumed?.();
  }, [prefill, onPrefillConsumed]);
  useEffect(() => {
    if (mode !== "new" || !initialForm) return;
    setForm((current) => ({ ...current, ...initialForm }));
  }, [initialForm, mode]);
  useEffect(() => {
    if (!error) return;
    const timer = window.setTimeout(() => setError(null), 5000);
    return () => window.clearTimeout(timer);
  }, [error]);
  useEffect(() => {
    if (!query.trim()) return;
    const timer = setTimeout(async () => {
      try {
        const data = await request(
          `/api/market/suggest?query=${encodeURIComponent(query.trim())}`,
        );
        const exact = data.items?.find(
          (item: any) => {
            const code = String(item.code || "");
            return code === query.trim() || code.split(".")[0] === query.trim() || item.name === query.trim();
          },
        );
        if (exact)
          setForm((current) => ({
            ...current,
            symbol: String(exact.code).split(".")[0],
            security_name: exact.name || current.security_name,
            current_price:
              exact.price > 0 ? String(exact.price) : current.current_price,
            ...(String(exact.code).split(".")[0] !== current.symbol
              ? {
                  selection_source_type: "MANUAL" as const,
                  selection_strategy: "",
                  selection_stage: "",
                  selection_snapshot_date: "",
                  thesis: "",
                }
              : {}),
          }));
      } catch (e) {
        setError(errorMessage(e, "股票信息读取失败"));
      }
    }, 180);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    if (
      mode !== "new" ||
      !form.symbol ||
      !form.reference_entry_price ||
      !form.max_acceptable_entry_price ||
      !form.risk_reference_price
    )
      return;
    const timer = setTimeout(async () => {
      try {
        const data = await request("/api/trade-plans/calculate", {
          method: "POST",
          body: JSON.stringify(body),
        }, accountId);
        setCalculation(data.calculation);
        setAccountContext(data.account_context);
      } catch (e) {
        setCalculation(null);
        setError(errorMessage(e, "计算失败"));
      }
    }, 220);
    return () => clearTimeout(timer);
  }, [
    body,
    mode,
    accountId,
    form.symbol,
    form.reference_entry_price,
    form.max_acceptable_entry_price,
    form.risk_reference_price,
  ]);
  if (isTradePlanList(mode))
    return (
      <div className="trade-plans-page min-h-[calc(100vh-64px)] bg-[#f8f9fa] px-6 py-6 text-[#191c1d] xl:px-8">
        <div className="mx-auto max-w-[1600px]">
          <PlanListCompact
            items={items}
            onNew={() => {
              setForm(initial);
              setDraftId(null);
              setQuery("");
              setCalculation(null);
              setMode("new");
            }}
            onRefresh={load}
            busy={busy}
            onEdit={(item) => { const input = item.input_json || {}; setDraftId(item.id); setForm({ ...initial, ...Object.fromEntries(Object.entries(input).map(([key, value]) => [key, key === "plan_risk_pct" ? percentageInput(value) : value == null ? "" : String(value)])) } as FormState); setQuery(`${item.symbol} ${item.security_name}`); setCalculation(item.calculation_snapshot_json || null); setMode("new"); }}
          />
        </div>
        <ErrorHint message={error} />
      </div>
    );
  function update(key: keyof FormState, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }
  async function save(confirm: boolean) {
    setBusy(true);
    setError(null);
    try {
      const created = await request(draftId ? `/api/trade-plans/${draftId}` : "/api/trade-plans", {
        method: draftId ? "PUT" : "POST",
        body: JSON.stringify(body),
      }, accountId);
      if (confirm)
        await request(`/api/trade-plans/${created.item.id}/confirm`, {
          method: "POST",
          body: JSON.stringify(body),
        }, accountId);
      await load();
      setDraftId(null);
      setMode("list");
    } catch (e) {
      setError(errorMessage(e, "保存失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-[calc(100vh-64px)] bg-[#f8f9fa] px-6 py-6 text-[#191c1d] xl:px-8">
      <div className="mx-auto max-w-[1600px]">
        {mode === "list" ? (
          <PlanList items={items} onNew={() => setMode("new")} />
        ) : (
          <><div className="mb-5 flex items-end justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-[#0f5238]">OPEN TRADE WORKSPACE</p><h1 className="mt-1 text-3xl font-bold">创建新交易</h1><p className="mt-1 text-sm text-[#52616b]">先定义风险，再确定仓位；价格可直接从 K 线拾取。</p></div><button type="button" onClick={() => setMode("list")} className="rounded-lg border border-[#d9d3c8] bg-white px-4 py-2 text-sm font-bold">返回交易计划</button></div><div className="grid gap-5 xl:grid-cols-12">
            <section className="col-span-12 h-[680px] overflow-hidden rounded-xl bg-white shadow-[0_2px_7px_rgba(25,28,29,0.06)] lg:col-span-8">
              {form.symbol ? (
                <KLineModal
                  embedded
                  isOpen
                  assetCode={form.symbol}
                  assetName={form.security_name || form.symbol}
                  onClose={() => undefined}
                  showAiPoolButton={false}
                  showWatchlistButton={false}
                  showNavigation={false}
                  showAssetInfo
                  onPickPrice={(price) => update(pickField, String(price))}
                />
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-[#686d68]">
                  在右侧输入股票代码或名称后查看 K 线
                </div>
              )}
            </section>
            <div className="col-span-12 lg:col-span-4">
            <PlanForm
                form={form}
                update={update}
                calculation={calculation}
                accountContext={accountContext}
                busy={busy}
                onSave={save}
                onBack={() => setMode("list")}
                onReset={() => {
                  setForm(initial);
                  setDraftId(null);
                  setQuery("");
                  setCalculation(null);
                }}
                onPickField={setPickField}
                onOpenSettings={onOpenSettings}
                stockQuery={query}
                onStockQueryChange={setQuery}
                onExport={() => downloadPlanMarkdown({
                  id: draftId,
                  symbol: form.symbol,
                  security_name: form.security_name,
                  status: draftId ? "DRAFT" : "未保存",
                  created_at: new Date().toISOString(),
                  input_json: body.plan,
                  calculation_snapshot_json: calculation || {},
                  account_settings_json: {
                    account_equity: accountContext?.account?.equity,
                    available_cash: accountContext?.account?.available_cash,
                    max_total_position_pct: accountContext?.risk_profile?.max_total_exposure_pct,
                  },
                })}
              />
            </div>
          </div></>
        )}
      </div>
      <ErrorHint message={error} />
    </div>
  );
}

function PlanForm({
  form,
  update,
  calculation,
  accountContext,
  busy,
  onSave,
  onBack,
  onReset,
  onPickField,
  onOpenSettings,
  stockQuery,
  onStockQueryChange,
  onExport,
}: {
  form: FormState;
  update: (key: keyof FormState, value: string) => void;
  calculation: any;
  accountContext: any;
  busy: boolean;
  onSave: (confirm: boolean) => void;
  onBack: () => void;
  onReset: () => void;
  onPickField: (field: PickField) => void;
  onOpenSettings?: () => void;
  stockQuery: string;
  onStockQueryChange: (value: string) => void;
  onExport: () => void;
}) {
  return (
    <aside className="h-fit space-y-4 xl:sticky xl:top-20">
      <Panel
        title="Trade Plan"
        action={
          <div className="flex items-center gap-2">
            <button type="button" onClick={onReset} className="flex items-center gap-1 text-xs font-bold text-[#0f5238] hover:opacity-80" title="清空当前计划">
              <RefreshCw className="h-3.5 w-3.5" />重置
            </button>
            <button type="button" onClick={onBack} title="返回交易计划列表" aria-label="返回交易计划列表" className="rounded-lg p-1.5 text-[#52616b] hover:bg-[#f3f4f5] hover:text-[#0f5238]"><ArrowLeft className="h-4 w-4" /></button>
          </div>
        }
      >
        <label className="mb-3 block">
          {label("股票", true)}
          <input
            value={stockQuery}
            onChange={(e) => onStockQueryChange(e.target.value)}
            placeholder="输入股票代码或名称"
            className="input"
          />
        </label>
        {form.selection_source_type === "STRATEGY" && (
          <div className="mb-3 rounded-lg border border-[#cdd9e6] bg-[#f4f7fb] px-3 py-2 text-xs text-[#354860]">
            <b>选股来源：</b>{form.selection_strategy} · {form.selection_stage}
            {form.selection_snapshot_date ? `（${form.selection_snapshot_date}）` : ""}
          </div>
        )}
        {form.selection_source_type === "UNKNOWN" && (
          <div className="mb-3 rounded-lg border border-[#e4e0d8] bg-[#faf8f3] px-3 py-2 text-xs text-[#686d68]">
            <b>选股来源：</b>来源未记录
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <label>
            {label("参考入场价", true)}
            <input
              type="number"
              step="0.01"
              value={form.reference_entry_price}
              onFocus={() => onPickField("reference_entry_price")}
              onChange={(e) => update("reference_entry_price", e.target.value)}
              className="input"
            />
          </label>
          <label className="sm:col-span-2">
            {label("交易类型", true)}
            <select value={form.trade_type} onChange={(e) => { const value = e.target.value as FormState["trade_type"]; update("trade_type", value); update("target_type", value === "FIXED_TARGET" ? "FIXED_TARGET" : "TREND_FOLLOWING"); }} className="input">
              <option value="TREND">趋势交易</option>
              <option value="REBOUND">反弹 / 波段</option>
              <option value="FIXED_TARGET">固定目标</option>
              <option value="CUSTOM">自定义</option>
            </select>
          </label>
          <label>
            {label("最高可接受价", true)}
            <input
              type="number"
              step="0.01"
              value={form.max_acceptable_entry_price}
              onFocus={() => onPickField("max_acceptable_entry_price")}
              onChange={(e) =>
                update("max_acceptable_entry_price", e.target.value)
              }
              className="input"
            />
          </label>
          <label>
            {label("风险参考价", true)}
            <input
              type="number"
              step="0.01"
              value={form.risk_reference_price}
              onFocus={() => onPickField("risk_reference_price")}
              onChange={(e) => update("risk_reference_price", e.target.value)}
              className="input"
            />
          </label>
          <label>
            {label("本次风险比例", true)}
            <div className="relative">
              <input
                type="number"
                min="0.01"
                max="100"
                step="0.01"
                value={form.plan_risk_pct}
                onChange={(e) => update("plan_risk_pct", e.target.value)}
                className="input pr-8"
              />
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-[#686d68]">
                %
              </span>
            </div>
          </label>
          <label>
            {label("目标方式")}
            <div className="flex h-9 rounded-lg bg-[#edeeef] p-1">
              {([["FIXED_TARGET", "固定目标"], ["TREND_FOLLOWING", "趋势跟踪"]] as const).map(([value, text]) => <button key={value} type="button" onClick={() => update("target_type", value)} className={`flex-1 rounded-md text-xs font-bold ${form.target_type === value ? "bg-white text-[#191c1d] shadow-sm" : "text-[#52616b]"}`}>{text}</button>)}
            </div>
          </label>
          {form.target_type === "FIXED_TARGET" && (
            <label>
              {label("目标价", true)}
              <input
                type="number"
                step="0.01"
                value={form.target_price}
                onFocus={() => onPickField("target_price")}
                onChange={(e) => update("target_price", e.target.value)}
                className="input"
              />
            </label>
          )}
          {form.target_type === "TREND_FOLLOWING" && (
            <label>
              {label("第一空间参考价", true)}
              <div className="relative">
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={form.expected_price}
                  onFocus={() => onPickField("expected_price")}
                  onChange={(e) => update("expected_price", e.target.value)}
                  className="input"
                />
              </div>
            </label>
          )}
          {form.trade_type === "REBOUND" && (
            <>
              <label>
                {label("目标区下沿", true)}
                <input type="number" step="0.01" value={form.target_zone_lower} onChange={(e) => update("target_zone_lower", e.target.value)} className="input" />
              </label>
              <label>
                {label("目标区上沿", true)}
                <input type="number" step="0.01" value={form.target_zone_upper} onChange={(e) => update("target_zone_upper", e.target.value)} className="input" />
              </label>
              <label>
                {label("预期持有周期（交易日）", true)}
                <input type="number" min="1" step="1" value={form.holding_period_days} onChange={(e) => update("holding_period_days", e.target.value)} className="input" />
              </label>
              <label className="md:col-span-2">
                {label("时间失效条件", true)}
                <input value={form.time_invalidation_condition} onChange={(e) => update("time_invalidation_condition", e.target.value)} className="input" placeholder="例如：10 个交易日内未触及目标区" />
              </label>
            </>
          )}
          <label>
            {label("人工计划数量")}
            <input
              type="number"
              step="100"
              value={form.manual_planned_qty}
              onChange={(e) => update("manual_planned_qty", e.target.value)}
              className="input"
              placeholder="留空使用系统建议"
            />
          </label>
        </div>
        <div className="mt-3 grid gap-3">
          <label>
            {label("风险参考说明")}
            <textarea
              value={form.risk_reference_note}
              onChange={(e) => update("risk_reference_note", e.target.value)}
              placeholder="说明该风险参考位置的判断依据"
              className="input min-h-16 resize-y py-2"
            />
          </label>
          <label>
            {label("交易逻辑")}
            <textarea
              value={form.thesis}
              onChange={(e) => update("thesis", e.target.value)}
              placeholder="记录入场条件、预期与失效条件"
              className="input min-h-20 resize-y py-2"
            />
          </label>
        </div>
      </Panel>
      <Panel title="计算结果">
        {!accountContext?.is_ready ? (
          <p className="text-sm text-[#686d68]">
            账户配置完成后，将根据资金和风险规则实时计算建议仓位。
          </p>
        ) : calculation ? (
          <>
            <div className="rounded-lg border border-[#d9e1ea] bg-[#f4f7fb] p-3">
              <p className="text-xs font-bold tracking-wide text-[#354860]">交易计划摘要</p>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <Metric
                  label={form.manual_planned_qty ? "人工计划数量" : "最终计划数量"}
                  value={`${calculation.planned_qty ?? "—"} 股`}
                />
                <Metric label="预计投入" value={money(calculation.planned_notional)} />
                <Metric label="本次资金仓位" value={pct(calculation.planned_position_pct)} />
                <Metric label="交易后总仓位" value={pct(calculation.post_trade_total_position_pct)} />
              </div>
              {form.manual_planned_qty && Number(form.manual_planned_qty) !== calculation.recommended_qty && (
                <p className="mt-2 text-xs text-amber-800">
                  系统建议 {calculation.recommended_qty} 股；当前人工计划 {calculation.planned_qty} 股。
                </p>
              )}
            </div>

            <ResultSection title="风险">
              <ResultRow label="参考入场价" value={money(Number(form.reference_entry_price))} />
              <ResultRow label="风险参考价" value={money(Number(form.risk_reference_price))} />
              <ResultRow label="价格风险" value={pct(calculation.price_risk_pct)} />
              <ResultRow label="风险预算" value={`${money(calculation.risk_budget_amount)} / ${form.plan_risk_pct}%`} strong />
              <div className="mt-2 rounded-md bg-rose-50 px-2.5 py-2 text-xs text-rose-900">
                <b>若按风险参考价退出：</b>预计计划亏损 {money(calculation.planned_risk_amount)}（账户 {pct(calculation.planned_account_risk_pct)}）
                <p className="mt-1 text-[11px] text-rose-700">实际亏损可能因跳空、滑点等高于计划值。</p>
              </div>
            </ResultSection>

            <ResultSection title="仓位计算">
              <ResultRow label="风险预算允许" value={`${calculation.qty_by_risk} 股`} />
              <ResultRow label="单只股票最大仓位允许" value={`${calculation.qty_by_single_position} 股`} />
              <ResultRow label="可用现金允许" value={`${calculation.qty_by_cash} 股`} />
              <ResultRow label="账户总仓位允许" value={`${calculation.qty_by_total_position} 股`} />
              <ResultRow label="最终限制" value={limitingFactorLabel(calculation.limiting_factor)} strong />
              {calculation.unrounded_recommended_qty !== calculation.recommended_qty && (
                <p className="mt-2 text-xs text-[#52616b]">
                  {calculation.unrounded_recommended_qty} 股 → 按 A 股买入交易单位向下调整 → {calculation.recommended_qty} 股
                </p>
              )}
            </ResultSection>

            <ResultSection title="收益 / 空间">
              {form.target_type === "FIXED_TARGET" ? (
                <>
                  <ResultRow label="目标方式" value="固定目标" />
                  <ResultRow label="目标价" value={money(Number(form.target_price))} />
                  <ResultRow label="潜在盈利" value={money(calculation.target_profit_amount)} />
                  <ResultRow label="计划收益率" value={pct(calculation.target_return_pct)} />
                  <ResultRow label="收益风险比" value={calculation.reward_risk_ratio != null ? `${calculation.reward_risk_ratio.toFixed(2)} : 1` : "—"} strong />
                </>
              ) : (
                <>
                  <ResultRow label="退出方式" value={form.trade_type === "REBOUND" ? "反弹目标区" : "趋势跟踪"} />
                  <ResultRow label="固定目标" value="无" />
                  <ResultRow label="固定盈亏比" value="不适用" />
                  <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
                    <div className="rounded-md bg-[#fffdf8] px-1.5 py-2"><b>1R</b><br />{money(calculation.r1_price)}</div>
                    <div className="rounded-md bg-[#fffdf8] px-1.5 py-2"><b>2R</b><br />{money(calculation.r2_price)}</div>
                    <div className="rounded-md bg-[#fffdf8] px-1.5 py-2"><b>3R</b><br />{money(calculation.r3_price)}</div>
                  </div>
                  {calculation.expected_reward_r != null && (
                    <p className="mt-2 text-xs font-bold text-[#354860]">第一空间参考 {money(calculation.expected_price)}，距离计划入场 {calculation.expected_reward_r.toFixed(2)}R</p>
                  )}
                  {form.trade_type === "REBOUND" && (
                    <p className="mt-2 text-xs text-[#52616b]">目标区 {money(Number(form.target_zone_lower))} - {money(Number(form.target_zone_upper))} · 持有 {form.holding_period_days || "—"} 个交易日 · {form.time_invalidation_condition || "未设置失效条件"}</p>
                  )}
                </>
              )}
            </ResultSection>

            {Number(form.max_acceptable_entry_price) > Number(form.reference_entry_price) && calculation.max_price_scenario && (
              <ResultSection title="最高买入价情景">
                <p className="mb-2 text-xs text-[#52616b]">若涨至最高可接受价 {money(calculation.max_price_scenario.entry_price)}：</p>
                <ResultRow label="建议数量" value={`${calculation.max_price_scenario.recommended_qty} 股`} />
                <ResultRow label="预计计划亏损" value={`${money(calculation.max_price_scenario.planned_risk_amount)} / ${pct(calculation.max_price_scenario.planned_account_risk_pct)}`} />
                <ResultRow label="本次资金仓位" value={pct(calculation.max_price_scenario.planned_position_pct)} />
                <ResultRow label="交易后总仓位" value={pct(calculation.max_price_scenario.post_trade_total_position_pct)} />
              </ResultSection>
            )}
            {calculation.warnings?.map((item: string) => (
              <p
                key={item}
                className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800"
              >
                ⚠ {item}
              </p>
            ))}
            {calculation.blocking_errors?.map((item: string) => (
              <p
                key={item}
                className="mt-2 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-800"
              >
                ✕ {calculationMessage(item, calculation)}
              </p>
            ))}
          </>
        ) : (
          <p className="text-sm text-[#686d68]">
            左侧选择股票并在 K 线上拾取价格后，这里会实时计算。
          </p>
        )}
      </Panel>
      <Panel title="账户依据">
        {!accountContext?.is_ready ? (
          <div className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800">
            <b>无法计算建议仓位</b>
            <p className="mt-1 text-xs">请先完成交易账户和风险规则配置。</p>
            {onOpenSettings && (
              <button
                onClick={onOpenSettings}
                className="mt-3 rounded-md bg-[#354860] px-3 py-1.5 text-xs font-bold text-white"
              >
                前往交易设置
              </button>
            )}
          </div>
        ) : (
          <AccountContext context={accountContext} />
        )}
      </Panel>
      <div className="grid grid-cols-3 gap-2">
        <button
          disabled={
            busy ||
            !accountContext?.is_ready ||
            !calculation ||
            calculation.blocking_errors?.length > 0
          }
          onClick={() => onSave(true)}
          title="确认交易计划"
          className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-[#2e3230] px-2 py-2.5 text-xs font-bold text-white disabled:opacity-40"
        >
          <CheckCircle2 className="h-4 w-4" />
          确认计划
        </button>
        <button
          disabled={busy || !accountContext?.is_ready || !calculation}
          onClick={() => onSave(false)}
          title="保存为草稿"
          className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-[#cfc4b3] px-2 py-2.5 text-xs font-bold"
        >
          <Save className="h-4 w-4" />
          存草稿
        </button>
        <button
          type="button"
          disabled={!form.symbol || !calculation}
          onClick={onExport}
          title="导出当前交易计划为 Markdown"
          className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-[#cfc4b3] px-2 py-2.5 text-xs font-bold disabled:opacity-40"
        >
          <Download className="h-4 w-4" />
          导出
        </button>
      </div>
    </aside>
  );
}
function AccountContext({ context }: { context: any }) {
  const account = context.account || {};
  const risk = context.risk_profile || {};
  return (
    <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
      <AccountMetric
        label="当前账户净资产"
        value={money(Number(account.equity))}
      />
      <AccountMetric
        label="可用现金"
        value={money(Number(account.available_cash))}
      />
      <AccountMetric
        label="当前总仓位"
        value={pct(Number(context.current_exposure_pct))}
      />
      <AccountMetric
        label="默认单笔风险"
        value={pct(Number(risk.default_trade_risk_pct))}
      />
      <AccountMetric
        label="单只最大仓位"
        value={pct(Number(risk.max_single_position_pct))}
      />
      <AccountMetric
        label="账户最大总仓位"
        value={pct(Number(risk.max_total_exposure_pct))}
      />
    </div>
  );
}
function AccountMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg bg-[#f7f3ea] px-2.5 py-2">
      <span className="text-[#686d68]">{label}</span>
      <b className="shrink-0">{value}</b>
    </div>
  );
}

export function ActionPlanDialog({
  action,
  accountId,
  initialValues,
  onClose,
  onSaved,
  onError,
  fullPage = false,
}: {
  action: { tradeId: number; symbol: string; securityName: string; type: "ADD" | "REDUCE" | "CLOSE" };
  accountId?: number;
  onClose: () => void;
  onSaved: () => Promise<void>;
  onError: (message: string) => void;
  fullPage?: boolean;
  initialValues?: Partial<{ referencePrice: string; minimumPrice: string; triggerCondition: string; reasonText: string; maxPrice: string; riskPrice: string; quantity: string; reduceMethod: string; positionPct: string; targetRemainingQty: string; targetRemainingPct: string; reasonCode: string; failureHandling: string; actionRiskBudget: string; riskMode: string; unifiedRiskReference: string; residualMode: string }>;
}) {
  const [referencePrice, setReferencePrice] = useState(initialValues?.referencePrice || "");
  const [minimumPrice, setMinimumPrice] = useState(initialValues?.minimumPrice || "");
  const [triggerCondition, setTriggerCondition] = useState(initialValues?.triggerCondition || "");
  const [reasonText, setReasonText] = useState(initialValues?.reasonText || "");
  const [maxPrice, setMaxPrice] = useState(initialValues?.maxPrice || "");
  const [riskPrice, setRiskPrice] = useState(initialValues?.riskPrice || "");
  const [quantity, setQuantity] = useState(initialValues?.quantity || "");
  const [reduceMethod, setReduceMethod] = useState(initialValues?.reduceMethod || "FIXED_QTY");
  const [positionPct, setPositionPct] = useState(initialValues?.positionPct || "");
  const [targetRemainingQty, setTargetRemainingQty] = useState(initialValues?.targetRemainingQty || "");
  const [targetRemainingPct, setTargetRemainingPct] = useState(initialValues?.targetRemainingPct || "");
  const [reasonCode, setReasonCode] = useState(initialValues?.reasonCode || "CUSTOM");
  const [failureHandling, setFailureHandling] = useState(initialValues?.failureHandling || "EXIT_ADDED_QTY_ONLY");
  const [actionRiskBudget, setActionRiskBudget] = useState(initialValues?.actionRiskBudget || "");
  const [riskMode, setRiskMode] = useState(initialValues?.riskMode || "INDEPENDENT");
  const [unifiedRiskReference, setUnifiedRiskReference] = useState(initialValues?.unifiedRiskReference || "");
  const [residualMode, setResidualMode] = useState(initialValues?.residualMode || "KEEP");
  const [residualRiskReference, setResidualRiskReference] = useState("");
  const [tradeRiskBudgetAmount, setTradeRiskBudgetAmount] = useState<number | null>(null);
  const [tradeContext, setTradeContext] = useState<any>(null);
  const [tradeContextLoading, setTradeContextLoading] = useState(true);
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const title = action.type === "ADD" ? "创建加仓计划" : action.type === "REDUCE" ? "创建减仓计划" : "创建清仓计划";
  useEffect(() => {
    if (accountId === undefined) return;
    let active = true;
    setTradeContextLoading(true);
    Promise.all([
      request(`/api/trades/${action.tradeId}`, undefined, accountId),
      request(`/api/trades/${action.tradeId}/position-state`, undefined, accountId),
    ])
      .then(([tradeResponse, positionResponse]) => {
        if (!active) return;
        setTradeContext({ ...tradeResponse.item, position: positionResponse.item });
        setTradeRiskBudgetAmount(typeof tradeResponse.item?.trade_risk_budget_amount === "number" ? tradeResponse.item.trade_risk_budget_amount : null);
      })
      .catch((error) => { if (active) onError(errorMessage(error, "交易动作关联数据读取失败")); })
      .finally(() => { if (active) setTradeContextLoading(false); });
    return () => { active = false; };
  }, [action.tradeId, accountId, onError]);
  async function calculate() {
    if (accountId === undefined) {
      onError("未选择交易账号，无法计算动作计划");
      return;
    }
    if (action.type === "ADD" && !reasonText.trim()) {
      onError("请填写加仓理由后再计算");
      return;
    }
    if (action.type === "REDUCE" && residualMode === "NEW_REFERENCE" && (!residualRiskReference || Number(residualRiskReference) <= 0)) {
      onError("请选择有效的剩余仓位风险参考价");
      return;
    }
    setBusy(true);
    try {
      if (action.type === "ADD" && tradeRiskBudgetAmount === null) throw new Error("当前 Trade 未设置风险预算，无法进行加仓计算");
      const payload = action.type === "ADD"
        ? { reference_price: Number(referencePrice), max_acceptable_price: Number(maxPrice || referencePrice), risk_reference_price: Number(riskPrice), manual_quantity: quantity ? Number(quantity) : undefined, reason_code: reasonCode, reason_text: reasonText, failure_handling: failureHandling, action_risk_budget_amount: actionRiskBudget ? Number(actionRiskBudget) : undefined, risk_management_mode: riskMode, unified_risk_reference_price: unifiedRiskReference ? Number(unifiedRiskReference) : undefined, trade_risk_budget_amount: tradeRiskBudgetAmount }
        : { reduce_method: action.type === "CLOSE" ? "FIXED_QTY" : reduceMethod, quantity: action.type === "CLOSE" ? undefined : reduceMethod === "FIXED_QTY" ? Number(quantity) : undefined, position_pct: reduceMethod === "POSITION_PCT" ? Number(positionPct) / 100 : undefined, target_remaining_qty: reduceMethod === "TARGET_REMAINING_QTY" ? Number(targetRemainingQty) : undefined, target_remaining_pct: reduceMethod === "TARGET_REMAINING_PCT" ? Number(targetRemainingPct) / 100 : undefined, reference_price: referencePrice ? Number(referencePrice) : undefined, minimum_acceptable_price: minimumPrice ? Number(minimumPrice) : undefined, trigger_condition: triggerCondition || undefined, residual_mode: residualMode, residual_risk_reference_price: residualRiskReference ? Number(residualRiskReference) : undefined, reason_code: reasonCode, reason_text: reasonText };
      const data = await request(`/api/trades/${action.tradeId}/${action.type.toLowerCase()}/calculate`, { method: "POST", body: JSON.stringify(payload) }, accountId);
      setResult(data.calculation);
    } catch (e) {
      setResult(null);
      onError(errorMessage(e, "动作计划计算失败"));
    } finally { setBusy(false); }
  }
  async function save() {
    if (!result || result.blocking_errors?.length) return;
    if (accountId === undefined) {
      onError("未选择交易账号，无法保存动作计划");
      return;
    }
    if (action.type === "ADD" && !reasonText.trim()) {
      onError("请填写加仓理由后再保存");
      return;
    }
    if (action.type === "REDUCE" && residualMode === "NEW_REFERENCE" && (!residualRiskReference || Number(residualRiskReference) <= 0)) {
      onError("请选择有效的剩余仓位风险参考价");
      return;
    }
    setBusy(true);
    try {
      if (action.type === "ADD" && tradeRiskBudgetAmount === null) throw new Error("当前 Trade 未设置风险预算，无法保存加仓计划");
      const payload = action.type === "ADD"
        ? { reference_price: Number(referencePrice), max_acceptable_price: Number(maxPrice || referencePrice), risk_reference_price: Number(riskPrice), manual_quantity: quantity ? Number(quantity) : undefined, reason_code: reasonCode, reason_text: reasonText, failure_handling: failureHandling, action_risk_budget_amount: actionRiskBudget ? Number(actionRiskBudget) : undefined, risk_management_mode: riskMode, unified_risk_reference_price: unifiedRiskReference ? Number(unifiedRiskReference) : undefined, trade_risk_budget_amount: tradeRiskBudgetAmount }
        : { reduce_method: action.type === "CLOSE" ? "FIXED_QTY" : reduceMethod, quantity: action.type === "CLOSE" ? undefined : reduceMethod === "FIXED_QTY" ? Number(quantity) : undefined, position_pct: reduceMethod === "POSITION_PCT" ? Number(positionPct) / 100 : undefined, target_remaining_qty: reduceMethod === "TARGET_REMAINING_QTY" ? Number(targetRemainingQty) : undefined, target_remaining_pct: reduceMethod === "TARGET_REMAINING_PCT" ? Number(targetRemainingPct) / 100 : undefined, reference_price: referencePrice ? Number(referencePrice) : undefined, minimum_acceptable_price: minimumPrice ? Number(minimumPrice) : undefined, trigger_condition: triggerCondition || undefined, residual_mode: residualMode, residual_risk_reference_price: residualRiskReference ? Number(residualRiskReference) : undefined, reason_code: reasonCode, reason_text: reasonText };
      await request(`/api/trades/${action.tradeId}/${action.type.toLowerCase()}`, { method: "POST", body: JSON.stringify(payload) }, accountId);
      await onSaved();
    } catch (e) { onError(errorMessage(e, "动作计划保存失败")); } finally { setBusy(false); }
  }
  return (
    <div className={fullPage ? "fixed inset-0 z-[70] overflow-y-auto bg-[#f8f9fa] p-5" : "fixed inset-0 z-[70] flex items-center justify-center bg-black/30 p-4"} role="dialog" aria-modal="true" aria-label={title}>
      <div className={fullPage ? "mx-auto min-h-[calc(100vh-40px)] w-full max-w-5xl rounded-xl border border-[#e4e0d8] bg-white p-6 shadow-xl" : "w-full max-w-lg rounded-xl border border-[#e4e0d8] bg-white p-5 shadow-xl"}>
        <div className="mb-4 flex items-start justify-between">
          <div><h3 className="text-base font-bold">{title}</h3><p className="mt-1 text-xs text-[#686d68]">{tradeContext?.symbol || action.symbol} {tradeContext?.symbol_name || action.securityName} · 交易动作工作区</p></div>
          <button type="button" onClick={onClose} title="关闭" aria-label="关闭" className="rounded-md px-2 py-1 text-lg text-[#686d68] hover:bg-[#f3f4f5]">×</button>
        </div>
        {tradeContext?.position && <div className="mb-4 grid grid-cols-2 gap-2 rounded-lg bg-[#f7f3ea] p-3 text-xs sm:grid-cols-4"><div><span className="block text-[#686d68]">当前持仓</span><b>{tradeContext.position.position_qty ?? tradeContext.position.quantity ?? "—"} 股</b></div><div><span className="block text-[#686d68]">可卖数量</span><b>{tradeContext.position.available_qty ?? tradeContext.position.available_quantity ?? "—"} 股</b></div><div><span className="block text-[#686d68]">平均成本</span><b>{money(tradeContext.position.avg_cost ?? tradeContext.position.average_cost)}</b></div><div><span className="block text-[#686d68]">当前价</span><b>{money(tradeContext.position.market_price)}</b></div></div>}
        {action.type === "ADD" ? (
          <div className="grid grid-cols-2 gap-3">
            <label>{label("参考入场价", true)}<input className="input" type="number" step="0.01" value={referencePrice} onChange={e => setReferencePrice(e.target.value)} /></label>
            <label>{label("最高可接受价", true)}<input className="input" type="number" step="0.01" value={maxPrice} onChange={e => setMaxPrice(e.target.value)} /></label>
            <label>{label("风险参考价", true)}<input className="input" type="number" step="0.01" value={riskPrice} onChange={e => setRiskPrice(e.target.value)} /></label>
            <label>{label("人工计划数量")}<input className="input" type="number" step="100" value={quantity} onChange={e => setQuantity(e.target.value)} placeholder="留空使用系统建议" /></label>
            <label>{label("本次风险预算")}<input className="input" type="number" min="0" step="0.01" value={actionRiskBudget} onChange={e => setActionRiskBudget(e.target.value)} placeholder="留空使用 Trade 剩余额度" /></label>
            <label>{label("加仓后风险管理") }<select className="input" value={riskMode} onChange={e => setRiskMode(e.target.value)}><option value="INDEPENDENT">各分腿独立风险参考</option><option value="UNIFIED">统一新的风险参考</option></select></label>
            {riskMode === "UNIFIED" && <label>{label("新的整体风险参考价", true)}<input className="input" type="number" min="0.01" step="0.01" value={unifiedRiskReference} onChange={e => setUnifiedRiskReference(e.target.value)} /></label>}
            <label className="col-span-2">{label("加仓理由", true)}<textarea className="input min-h-16" value={reasonText} onChange={e => setReasonText(e.target.value)} placeholder="补充本次加仓的触发信号与技术依据" /></label>
          </div>
        ) : action.type === "REDUCE" ? (
          <div className="grid grid-cols-2 gap-3"><label>{label("减仓方式", true)}<select className="input" value={reduceMethod} onChange={e => setReduceMethod(e.target.value)}><option value="FIXED_QTY">固定数量</option><option value="POSITION_PCT">按当前仓位比例</option><option value="TARGET_REMAINING_QTY">保留目标数量</option><option value="TARGET_REMAINING_PCT">保留目标仓位比例</option></select></label>{reduceMethod === "FIXED_QTY" && <label>{label("减仓数量", true)}<input className="input" type="number" step="100" min="100" value={quantity} onChange={e => setQuantity(e.target.value)} /></label>}{reduceMethod === "POSITION_PCT" && <label>{label("减仓比例（%）", true)}<input className="input" type="number" step="1" min="1" max="100" value={positionPct} onChange={e => setPositionPct(e.target.value)} /></label>}{reduceMethod === "TARGET_REMAINING_QTY" && <label>{label("保留数量", true)}<input className="input" type="number" step="100" min="0" value={targetRemainingQty} onChange={e => setTargetRemainingQty(e.target.value)} /></label>}{reduceMethod === "TARGET_REMAINING_PCT" && <label>{label("保留仓位比例（%）", true)}<input className="input" type="number" step="1" min="0" max="100" value={targetRemainingPct} onChange={e => setTargetRemainingPct(e.target.value)} /></label>}<label>{label("参考成交价")}<input className="input" type="number" step="0.01" value={referencePrice} onChange={e => setReferencePrice(e.target.value)} /></label></div>
        ) : <div className="rounded-lg bg-[#f7f3ea] px-3 py-2 text-sm text-[#52616b]">将按当前可卖持仓创建清仓计划，实际成交仍受 T+1 限制。</div>}
        {action.type === "REDUCE" && <div className="mt-3 grid grid-cols-2 gap-3"><label>{label("剩余仓位管理", true)}<select className="input" value={residualMode} onChange={e => setResidualMode(e.target.value)}><option value="KEEP">保留原风险参考</option><option value="NEW_REFERENCE">设置新的风险参考</option><option value="MANUAL">减仓后人工复核</option></select></label>{residualMode === "NEW_REFERENCE" && <label>{label("剩余仓位风险参考价", true)}<input className="input" type="number" min="0.01" step="0.01" value={residualRiskReference} onChange={e => setResidualRiskReference(e.target.value)} /></label>}</div>}
        {action.type !== "ADD" && <div className="mt-3 grid grid-cols-2 gap-3"><label>{label("最低可接受卖出价")}<input className="input" type="number" step="0.01" value={minimumPrice} onChange={e => setMinimumPrice(e.target.value)} /></label><label>{label("触发条件")}<input className="input" value={triggerCondition} onChange={e => setTriggerCondition(e.target.value)} placeholder="例如：跌破风险位" /></label></div>}
        <div className="mt-3 grid grid-cols-2 gap-3"><label>{label("计划理由", true)}<select className="input" value={reasonCode} onChange={e => setReasonCode(e.target.value)}><option value="PROFIT_TAKING">主动兑现利润</option><option value="FAILED_ADD">加仓失败</option><option value="TREND_WEAKENING">趋势转弱</option><option value="TARGET_REACHED">达到目标</option><option value="TIME_EXIT">时间退出</option><option value="RISK_REDUCTION">主动降低风险</option><option value="POSITION_CONCENTRATION">仓位过度集中</option><option value="CUSTOM">其他</option></select></label>{action.type === "ADD" && <label>{label("加仓失败处理", true)}<select className="input" value={failureHandling} onChange={e => setFailureHandling(e.target.value)}><option value="EXIT_ADDED_QTY_ONLY">只退出新增仓</option><option value="REDUCE_TO_TARGET_QTY">减至目标数量</option><option value="REDUCE_TO_TARGET_PCT">减至目标仓位</option><option value="CLOSE_ALL">全部清仓</option><option value="MANUAL_REVIEW">人工重新判断</option></select></label>}</div>
        {action.type !== "ADD" && <label className="mt-3 block">{label("原因说明")}<textarea className="input min-h-16" value={reasonText} onChange={e => setReasonText(e.target.value)} placeholder="补充本次动作依据" /></label>}
        {result && <div className="mt-4 rounded-lg bg-[#f4f7fb] px-3 py-2 text-sm"><div className="grid grid-cols-2 gap-1"><div>预计卖出数量：<b>{result.planned_qty ?? "—"} 股</b></div><div>减仓后持仓：<b>{result.remaining_qty ?? "—"} 股</b></div><div>预计卖出金额：<b>{money(result.planned_notional)}</b></div><div>预计实现盈亏：<b>{money(result.realized_pnl)}</b></div><div>减仓前本金风险：<b>{money(result.capital_risk_before)}</b></div><div>减仓后本金风险：<b>{money(result.capital_risk_after)}</b></div><div>减仓前利润回吐：<b>{money(result.giveback_risk_before)}</b></div><div>减仓后利润回吐：<b>{money(result.giveback_risk_after)}</b></div>{result.t_plus_one_limited && <div>延期待卖数量：<b>{Math.max(0, Number(result.requested_qty || 0) - Number(result.planned_qty || 0))} 股</b></div>}</div>{result.t_plus_one_limited && <p className="mt-2 text-xs text-amber-800">受 T+1 限制，本次只能执行当前可卖数量。</p>}{result.blocking_errors?.map((item: string) => <p key={item} className="mt-2 text-xs text-rose-700">{item}</p>)}</div>}
        <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded-lg border border-[#cfc4b3] px-3 py-2 text-xs font-bold">取消</button><button type="button" onClick={calculate} disabled={busy || tradeContextLoading} className="rounded-lg border border-[#0f5238] px-3 py-2 text-xs font-bold text-[#0f5238]">{tradeContextLoading ? "读取交易上下文…" : "计算"}</button><button type="button" onClick={save} disabled={busy || !result || result.blocking_errors?.length > 0} className="rounded-lg bg-[#0f5238] px-3 py-2 text-xs font-bold text-white disabled:opacity-40">保存计划</button></div>
      </div>
    </div>
  );
}

export function TradeDetailDialog({ tradeId, accountId, onClose, onError }: { tradeId: number; accountId?: number; onClose: () => void; onError: (message: string) => void }) {
  const [data, setData] = useState<any>(null);
  const [rules, setRules] = useState<any[]>([]);
  const [riskHistory, setRiskHistory] = useState<any[]>([]);
  const [rule, setRule] = useState({ trigger_type: "R_MULTIPLE", action_type: "REDUCE_POSITION_PCT", execution_behavior: "REQUIRE_CONFIRMATION" });
  const [busy, setBusy] = useState(false);
  async function load() {
    try {
      const [trade, exitRules, history] = await Promise.all([
        request("/api/trades/" + tradeId, undefined, accountId),
        request("/api/trades/" + tradeId + "/exit-rules", undefined, accountId),
        request("/api/trades/" + tradeId + "/risk-reference-history", undefined, accountId),
      ]);
      setData(trade.item);
      setRules(exitRules.items || []);
      setRiskHistory(history.items || []);
    } catch (e) { onError(errorMessage(e, "交易详情读取失败")); }
  }
  useEffect(() => { load(); }, [tradeId]);
  async function createRule() {
    setBusy(true);
    try {
      await request("/api/trades/" + tradeId + "/exit-rules", { method: "POST", body: JSON.stringify({ rule_type: "EXIT", ...rule }) }, accountId);
      await load();
    } catch (e) { onError(errorMessage(e, "退出规则保存失败")); } finally { setBusy(false); }
  }
  async function removeRule(id: number) {
    setBusy(true);
    try { await request("/api/trades/" + tradeId + "/exit-rules/" + id, { method: "DELETE" }, accountId); await load(); }
    catch (e) { onError(errorMessage(e, "退出规则删除失败")); } finally { setBusy(false); }
  }
  const triggerLabels: Record<string, string> = { MANUAL_CONFIRMATION: "人工确认", PRICE_ABOVE: "价格高于", PRICE_BELOW: "价格低于", PRICE_RANGE: "价格区间", R_MULTIPLE: "达到 R 倍数", DATE_TIME: "指定时间", HOLDING_DAYS: "持仓天数", CUSTOM: "自定义条件" };
  const actionLabels: Record<string, string> = { REDUCE_FIXED_QTY: "减仓固定数量", REDUCE_POSITION_PCT: "按仓位比例减仓", REDUCE_TO_TARGET_PCT: "减至目标仓位", CLOSE_ALL: "全部清仓", UPDATE_RISK_REFERENCE: "更新风险参考价", ALERT_ONLY: "仅提醒" };
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/30 p-4" role="dialog" aria-modal="true" aria-label="交易详情">
      <div className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-xl border border-[#e4e0d8] bg-white p-5 shadow-xl">
        <div className="mb-4 flex items-start justify-between"><div><h3 className="text-lg font-bold">交易详情</h3><p className="mt-1 text-xs text-[#686d68]">{data ? data.symbol + " " + data.symbol_name : "读取中…"}</p></div><button type="button" onClick={onClose} title="关闭" aria-label="关闭" className="rounded-md px-2 py-1 text-lg text-[#686d68]">×</button></div>
        {!data ? <p className="text-sm text-[#686d68]">正在读取交易数据…</p> : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Metric label="交易状态" value={data.status === "ACTIVE" ? "持仓中" : data.status === "CLOSING" ? "退出中" : data.status === "CLOSED" ? "已结束" : data.status === "PLANNED" ? "计划中" : "已取消"} />
              <Metric label="交易类型" value={({ TREND: "趋势交易", REBOUND: "反弹交易", FIXED_TARGET: "固定目标", CUSTOM: "自定义" } as Record<string, string>)[data.trade_type] || "自定义"} />
              <Metric label="动作计划" value={(data.plans?.length || 0) + " 项"} />
              <Metric label="交易腿" value={(data.legs?.length || 0) + " 个"} />
            </div>
            <section><h4 className="mb-2 text-sm font-bold">动作时间线</h4><div className="space-y-2 border-l-2 border-[#d9e1ea] pl-3">{(data.plans || []).map((plan: any) => <div key={plan.id} className="rounded-lg bg-[#f4f7fb] p-3 text-xs"><div className="flex justify-between"><b>第 {plan.sequence_no} 项 · {actionLabel(plan.action_type)}</b><span>{planStatusLabel(plan.status)}</span></div><div className="mt-1 text-[#52616b]">计划数量：{plan.calculation_snapshot_json?.planned_qty ?? "—"} 股 · 创建于 {plan.created_at ? new Date(plan.created_at).toLocaleString("zh-CN") : "—"}</div></div>)}</div></section>
            <section><h4 className="mb-2 text-sm font-bold">执行链路</h4><div className="space-y-2">{(data.plans || []).flatMap((plan: any) => (plan.execution_plans || []).map((execution: any) => <div key={execution.id} className="rounded-lg border border-[#dee2e6] p-3 text-xs"><div className="font-bold">TradePlan #{plan.id} → ExecutionPlan #{execution.id}</div><div className="mt-1 text-[#52616b]">执行状态：{planStatusLabel(execution.status)} · 订单 {execution.orders?.length || 0} 笔</div>{(execution.orders || []).map((order: any) => <div key={order.id} className="mt-1 border-l-2 border-[#bfc9c1] pl-2">Order #{order.id} · {planStatusLabel(order.status)} · 成交 {order.filled_quantity ?? 0} 股{order.fills?.length ? ` · Fill ${order.fills.length} 条` : ""}</div>)}</div>))}{!(data.plans || []).some((plan: any) => (plan.execution_plans || []).length) && <p className="text-xs text-[#52616b]">尚未创建执行计划。</p>}</div></section>
            <section><h4 className="mb-2 text-sm font-bold">退出规则</h4><div className="space-y-2">{rules.map((item) => <div key={item.id} className="flex items-center justify-between rounded-lg border border-[#e4e0d8] px-3 py-2 text-xs"><span>{triggerLabels[item.trigger_type] || item.trigger_type} → {actionLabels[item.action_type] || item.action_type}</span><button type="button" onClick={() => removeRule(item.id)} disabled={busy} title="删除退出规则" className="text-[#93000a]">删除</button></div>)}</div><div className="mt-2 grid gap-2 sm:grid-cols-4"><select className="input" value={rule.trigger_type} onChange={e => setRule({ ...rule, trigger_type: e.target.value })}>{Object.entries(triggerLabels).map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select><select className="input" value={rule.action_type} onChange={e => setRule({ ...rule, action_type: e.target.value })}>{Object.entries(actionLabels).map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select><select className="input" value={rule.execution_behavior} onChange={e => setRule({ ...rule, execution_behavior: e.target.value })}><option value="REQUIRE_CONFIRMATION">需要确认</option><option value="ALERT_ONLY">仅提醒</option></select><button type="button" onClick={createRule} disabled={busy} className="rounded-lg bg-[#0f5238] px-3 py-2 text-xs font-bold text-white">添加规则</button></div></section>
            <section><h4 className="mb-2 text-sm font-bold">风险参考价变更记录</h4>{riskHistory.length ? <div className="space-y-1 text-xs text-[#52616b]">{riskHistory.map((item: any) => <div key={item.id} className="flex justify-between rounded bg-[#faf8f3] px-2 py-1"><span>{item.old_price ?? "—"} → {item.new_price}</span><span>{item.reason}</span></div>)}</div> : <p className="text-xs text-[#686d68]">暂无变更记录</p>}</section>
          </div>
        )}
      </div>
    </div>
  );
}

function PlanListCompact({
  items,
  onNew,
  onRefresh,
  busy,
  onEdit,
}: {
  items: any[];
  onNew: () => void;
  onRefresh: () => void;
  busy: boolean;
  onEdit: (item: any) => void;
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-[#e4e0d8] bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-[#e4e0d8] px-5 py-4">
        <h2 className="font-bold">我的交易计划</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={onRefresh}
            title="刷新交易计划"
            aria-label="刷新交易计划"
            className="rounded-lg border border-[#bfc9c1] bg-white p-2"
          >
            <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
          </button>
          <button
            onClick={onNew}
            title="新建交易计划"
            aria-label="新建交易计划"
            className="rounded-lg bg-[#0f5238] p-2 text-white"
          >
            <Plus className="h-5 w-5" />
          </button>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="px-5 py-16 text-center text-sm text-[#686d68]">
          还没有交易计划，先创建一份计划。
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#faf8f3] text-xs text-[#686d68]">
              <tr>
                <th className="px-5 py-3">股票</th>
                <th className="px-5 py-3">状态</th>
                <th className="px-5 py-3">入场 / 风险参考</th>
                <th className="px-5 py-3">计划数量</th>
                <th className="px-5 py-3">账户风险</th>
                <th className="px-5 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, index) => {
                const input = item.input_json || {};
                const calc = item.calculation_snapshot_json || {};
                return (
                  <Fragment key={item.id}>
                    {(index === 0 || items[index - 1].trade_id !== item.trade_id) && (
                      <tr className="bg-[#f4f7fb]">
                        <td colSpan={6} className="px-5 py-2 text-xs font-bold text-[#354860]">
                          交易 {item.symbol} {item.security_name}
                          <span className="ml-3 font-medium text-[#686d68]">
                            {item.trade_status === "ACTIVE" ? "持仓中" : item.trade_status === "PLANNED" ? "计划中" : item.trade_status === "CLOSING" ? "退出中" : item.trade_status === "CLOSED" ? "已结束" : "已取消"}
                          </span>
                        </td>
                      </tr>
                    )}
                    <tr className="border-t border-[#eeeae2]">
                      <td className="px-5 py-3 pl-8">
                        <span className="text-xs text-[#686d68]">第 {input.sequence_no || "—"} 项</span>
                        <span className="ml-2 font-bold">{actionLabel(input.action_type)}</span>
                      </td>
                      <td className="px-5 py-3">
                        <span className="font-medium">{planStatusLabel(item.status)}</span>
                      </td>
                      <td className="px-5 py-3">
                        {input.reference_entry_price || "—"} / {input.risk_reference_price || "—"}
                      </td>
                      <td className="px-5 py-3">{calc.planned_qty ?? "—"} 股</td>
                      <td className="px-5 py-3">{pct(calc.planned_account_risk_pct)}</td>
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-1">
                          {item.status === "DRAFT" && (
                            <button type="button" onClick={() => onEdit(item)} title="编辑草稿" aria-label="编辑草稿" className="rounded-md p-1.5 text-[#0f5238] hover:bg-[#e8f3ed]">
                              <Save className="h-4 w-4" />
                            </button>
                          )}
                          <button type="button" onClick={() => downloadPlanMarkdown(item)} title="导出 Markdown" aria-label="导出 Markdown" className="rounded-md p-1.5 text-[#354860] hover:bg-[#edf1f5]">
                            <Download className="h-4 w-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function PlanList({ items, onNew }: { items: any[]; onNew: () => void }) {
  return (
    <section className="overflow-hidden rounded-2xl border border-[#e4e0d8] bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-[#e4e0d8] px-5 py-4">
        <h2 className="font-bold">我的交易计划</h2>
        <button onClick={onNew} className="text-sm font-bold text-[#8a7252]">
          新建
        </button>
      </div>
      {items.length === 0 ? (
        <div className="px-5 py-16 text-center text-sm text-[#686d68]">
          还没有交易计划，先创建一份计划。
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#faf8f3] text-xs text-[#686d68]">
              <tr>
                <th className="px-5 py-3">股票</th>
                <th className="px-5 py-3">状态</th>
                <th className="px-5 py-3">入场 / 风险参考</th>
                <th className="px-5 py-3">计划数量</th>
                <th className="px-5 py-3">账户风险</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const input = item.input_json || {};
                const calc = item.calculation_snapshot_json || {};
                return (
                  <tr key={item.id} className="border-t border-[#eeeae2]">
                    <td className="px-5 py-4">
                      <b>{item.symbol}</b>
                      <span className="ml-2 text-[#686d68]">
                        {item.security_name}
                      </span>
                    </td>
                    <td className="px-5 py-4">{item.status}</td>
                    <td className="px-5 py-4">
                      {input.reference_entry_price} /{" "}
                      {input.risk_reference_price}
                    </td>
                    <td className="px-5 py-4">{calc.planned_qty ?? "—"} 股</td>
                    <td className="px-5 py-4">
                      {pct(calc.planned_account_risk_pct)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
function Panel({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-[#e4e0d8] bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-bold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-[#f7f3ea] p-3">
      <p className="text-xs text-[#686d68]">{label}</p>
      <p className="mt-1 font-mono text-sm font-bold">{value}</p>
    </div>
  );
}
function ResultSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-3 border-t border-[#e4e0d8] pt-3">
      <h3 className="mb-2 text-xs font-bold tracking-wide text-[#354860]">{title}</h3>
      <div className="space-y-1.5">{children}</div>
    </section>
  );
}
function ResultRow({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="text-[#686d68]">{label}</span>
      <b className={strong ? "text-[#24384d]" : "text-[#2e3230]"}>{value}</b>
    </div>
  );
}
