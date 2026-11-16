"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { TradingPageKey } from "../types";
import {
  actionLabel,
  dateLabel,
  executionTypeLabel,
  money,
  numberLabel,
  readTradingJson,
  sideLabel,
  statusLabel,
  statusTone,
  type TradingRecord,
} from "../common/tradingData";

type Props = { accountId: number; onNavigate: (page: TradingPageKey, tradeId?: number, planId?: number) => void; onOpenSettings?: () => void; onRefresh?: () => void };

function PageState({ loading, error, retry }: { loading: boolean; error: string | null; retry: () => void }) {
  if (loading) return <div className="trading-page-state">正在读取执行计划…</div>;
  if (error) return <div className="trading-page-state trading-page-state-error"><strong>{error}</strong><button type="button" onClick={retry}>重新读取</button></div>;
  return null;
}

function MetricCard({ label, value, detail, tone = "neutral" }: { label: string; value: React.ReactNode; detail: React.ReactNode; tone?: string }) {
  return <div className={`execution-metric execution-metric-${tone}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function executionRule(plan: TradingRecord) {
  const params = plan.execution_params || plan.execution_params_json || {};
  if (plan.execution_type === "PRICE_RANGE") return `${money(params.low_price)} – ${money(params.high_price)} 触发`;
  if (plan.execution_type === "PRICE_TRIGGER") return `触发 ${money(params.trigger_price)} · 保护 ${money(params.limit_price)}`;
  return params.limit_price == null ? "等待执行参数" : `限价 ${money(params.limit_price)}`;
}

export default function ExecutionPlansPage({ accountId, onNavigate, onOpenSettings, onRefresh }: Props) {
  const [plans, setPlans] = useState<TradingRecord[]>([]);
  const [readyPlans, setReadyPlans] = useState<TradingRecord[]>([]);
  const [broker, setBroker] = useState<TradingRecord | null>(null);
  const [brokerLoading, setBrokerLoading] = useState(true);
  const [reconciliationCount, setReconciliationCount] = useState(0);
  const [composer, setComposer] = useState<TradingRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadBroker = useCallback(async () => {
    setBrokerLoading(true);
    try { setBroker(await readTradingJson("/api/trading/broker", accountId)); }
    catch { setBroker(null); }
    finally { setBrokerLoading(false); }
  }, [accountId]);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const localResult = await readTradingJson("/api/trading/overview/local", accountId);
      if (!Array.isArray(localResult.execution_plans) || !Array.isArray(localResult.trades) || !Array.isArray(localResult.reconciliation_issues)) {
        throw new Error("执行计划数据不完整，请刷新后重试");
      }
      setPlans(localResult.execution_plans);
      setReconciliationCount(localResult.reconciliation_issues.length);
      const nextReadyPlans = localResult.trades.flatMap((trade: TradingRecord) => {
        const tradePlans = Array.isArray(trade.plans) ? trade.plans : [];
        return tradePlans
          .filter((plan: TradingRecord) => ["READY", "ARMED"].includes(String(plan.status)))
          .map((plan: TradingRecord) => ({ ...plan, symbol: plan.symbol || trade.symbol, security_name: plan.security_name || trade.symbol_name, trade_id: trade.id }));
      });
      setReadyPlans(nextReadyPlans);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "执行计划读取失败");
    } finally { setLoading(false); }
    void loadBroker();
  }, [accountId, loadBroker]);

  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);

  const connected = broker?.connection?.status === "CONNECTED" || broker?.connection?.ok === true || broker?.status === "CONNECTED" || broker?.ok === true;
  const executionPlanIds = useMemo(() => new Set(plans.map((item) => Number(item.trade_plan_id))), [plans]);
  const pendingPlans = readyPlans.filter((plan) => !executionPlanIds.has(Number(plan.id)));
  const counts = useMemo(() => ({
    pending: plans.filter((item) => ["PENDING_SUBMIT", "QUEUED", "READY", "ARMED"].includes(String(item.status))).length,
    active: plans.filter((item) => ["ACTIVE", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"].includes(String(item.status))).length,
    completed: plans.filter((item) => ["COMPLETED", "FILLED"].includes(String(item.status))).length,
    paused: plans.filter((item) => ["PAUSED", "SUSPENDED"].includes(String(item.status))).length,
  }), [plans]);

  async function updateStatus(item: TradingRecord, status: string) {
    setError(null);
    try {
      await readTradingJson(`/api/trading/execution-plans/${item.id}/status`, accountId, { method: "PATCH", body: JSON.stringify({ status }) });
      await load(); onRefresh?.();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "执行计划状态更新失败"); }
  }

  async function createPlan() {
    if (!composer) return;
    const params = composer.execution_params || {};
    const quantity = Number(composer.calculation_snapshot_json?.planned_qty ?? composer.target_qty);
    if (!Number.isFinite(quantity) || quantity <= 0) { setError("执行计划缺少有效目标数量，请先完成交易计划计算"); return; }
    if (!(Number(params.limit_price) > 0)) { setError("请填写有效的执行限价"); return; }
    setBusy(true); setError(null);
    try {
      const result = await readTradingJson("/api/trading/execution-plans", accountId, {
        method: "POST",
        body: JSON.stringify({
          trade_plan_id: composer.id,
          symbol: composer.symbol,
          side: ["REDUCE", "CLOSE"].includes(String(composer.action_type)) ? "SELL" : "BUY",
          target_qty: quantity,
          execution_type: composer.execution_type || "LIMIT",
          client_request_id: composer.client_request_id || crypto.randomUUID(),
          valid_until: composer.valid_until || null,
          execution_params: params,
        }),
      });
      if (!result.item?.id) throw new Error("执行计划创建接口未返回计划编号");
      await readTradingJson(`/api/trading/execution-plans/${result.item.id}/status`, accountId, { method: "PATCH", body: JSON.stringify({ status: "ACTIVE" }) });
      setComposer(null); await load(); onRefresh?.();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "执行计划创建失败"); }
    finally { setBusy(false); }
  }

  return <div className="trading-react-page execution-plans-page">
    <header className="trading-react-page-header execution-page-header"><div><small>交易执行 / EXECUTION PLANS</small><h1>交易执行</h1><p>管理已确认交易计划的执行方案与券商算法路由。</p></div><div className="trading-react-page-actions"><button type="button" onClick={() => onNavigate("overview")}>返回总览</button><button type="button" onClick={() => { void load(); onRefresh?.(); }}>刷新计划</button></div></header>
    <PageState loading={loading} error={error} retry={() => void load()} />
    {!loading && !error && <>
      <section className="execution-metric-grid"><MetricCard label="待路由" value={`${counts.pending} 笔`} detail="等待发送或待触发" tone="warning" /><MetricCard label="监控中" value={`${counts.active} 笔`} detail="已进入执行通道" tone="success" /><MetricCard label="已完成" value={`${counts.completed} 笔`} detail="执行结果" tone="neutral" /><MetricCard label="已暂停" value={`${counts.paused} 笔`} detail="需要人工恢复" tone="danger" /></section>
      {brokerLoading || !connected || reconciliationCount > 0 ? <section className="execution-guard"><strong>{brokerLoading ? "正在检查交易通道" : !connected ? "券商交易通道未连接" : "当前账号有待处理对账事项"}</strong><span>{brokerLoading ? "执行计划已加载，交易通道状态正在后台更新。" : !connected ? "暂不可发送委托，可以查看和保存执行意图。" : reconciliationCount > 0 ? `完成 ${reconciliationCount} 项对账后才可继续执行。` : ""}</span>{!brokerLoading && !connected && <button type="button" onClick={() => onOpenSettings?.()}>去配置</button>}</section> : null}
      {pendingPlans.length ? <section className="trading-panel execution-pending-panel"><div className="trading-panel-title"><h2>待执行交易计划</h2><span>{pendingPlans.length} 项已确认</span></div>{pendingPlans.map((plan) => <div className="execution-pending-row" key={String(plan.id)}><div><strong>{plan.symbol_name || plan.security_name || plan.symbol || "—"}</strong><small>{plan.symbol || "—"} · {actionLabel(plan.action_type || plan.action)} · 目标 {numberLabel(plan.calculation_snapshot_json?.planned_qty ?? plan.target_qty)} 股</small></div><div><span>参考价 {money(plan.input_json?.reference_entry_price)}</span><button type="button" onClick={() => setComposer({ ...plan, execution_type: "LIMIT", execution_params: { limit_price: plan.input_json?.reference_entry_price } })}>创建执行</button></div></div>)}</section> : null}
      <section className="execution-monitor-grid"><div className="trading-panel"><div className="trading-panel-title"><h2>执行方案监控</h2><span>{plans.length} 笔</span></div>{plans.length ? <div className="execution-plan-list">{plans.map((item) => { const target = Number(item.target_qty); const filled = Number(item.filled_qty ?? item.filled_quantity); const progress = Number.isFinite(target) && target > 0 && Number.isFinite(filled) ? Math.min(100, Math.max(0, filled / target * 100)) : 0; const terminal = ["COMPLETED", "FILLED", "CANCELLED", "FAILED", "EXPIRED", "REJECTED"].includes(String(item.status)); const paused = ["PAUSED", "SUSPENDED"].includes(String(item.status)); return <article className="execution-plan-card" key={String(item.id)}><div className="execution-plan-card-main"><div className="execution-plan-symbol"><strong>{item.symbol_name || item.symbol || "—"}</strong><small>{item.symbol || "—"} · {sideLabel(item.side)} · {actionLabel(item.action_type || item.action)}</small></div><div className="execution-plan-rule"><span>{executionTypeLabel(item.execution_type)}</span><small>{executionRule(item)}</small></div><div className="execution-plan-progress"><div><span>执行进度</span><strong>{numberLabel(item.filled_qty ?? item.filled_quantity)} / {numberLabel(item.target_qty)} 股</strong></div><div className="overview-progress-track"><div className="overview-progress-risk" style={{ width: `${progress}%` }} /></div><small>剩余 {numberLabel(item.remaining_qty)} 股 · 更新于 {dateLabel(item.updated_at || item.created_at)}</small></div></div><div className="execution-plan-card-actions"><span className={`execution-status execution-status-${statusTone(item.status)}`}>{statusLabel(item.status)}</span>{!terminal && <button type="button" onClick={() => void updateStatus(item, paused ? "ACTIVE" : "PAUSED")}>{paused ? "恢复" : "暂停"}</button>}{!terminal && <button type="button" className="danger" onClick={() => void updateStatus(item, "CANCELLED")}>取消</button>}</div></article>; })}</div> : <div className="trading-empty">当前账号暂无执行方案。</div>}</div></section>
    </>}
    {composer && <div className="execution-composer-backdrop"><section className="execution-composer" role="dialog" aria-modal="true"><div className="trading-panel-title"><div><h2>创建执行计划</h2><span>{composer.symbol_name || composer.security_name || composer.symbol} · 目标 {numberLabel(composer.calculation_snapshot_json?.planned_qty ?? composer.target_qty)} 股</span></div><button type="button" onClick={() => setComposer(null)}>关闭</button></div><div className="trading-form-grid"><label>执行方式<select value={composer.execution_type || "LIMIT"} onChange={(event) => setComposer((current) => current ? { ...current, execution_type: event.target.value } : current)}><option value="LIMIT">限价委托</option><option value="PERSISTENT_LIMIT">持续限价</option><option value="PRICE_TRIGGER">价格触发</option><option value="PRICE_RANGE">价格区间触发</option></select></label><label>限价<input type="number" step="0.01" value={composer.execution_params?.limit_price ?? ""} onChange={(event) => setComposer((current) => current ? { ...current, execution_params: { ...(current.execution_params || {}), limit_price: Number(event.target.value) } } : current)} /></label><label>有效期<input type="date" value={composer.valid_until ? String(composer.valid_until).slice(0, 10) : ""} onChange={(event) => setComposer((current) => current ? { ...current, valid_until: event.target.value ? `${event.target.value}T23:59:59+08:00` : "" } : current)} /></label></div><div className="trading-form-actions"><button type="button" onClick={() => setComposer(null)}>取消</button><button type="button" disabled={busy} onClick={() => void createPlan()}>{busy ? "保存中…" : "保存并启用"}</button></div></section></div>}
  </div>;
}
