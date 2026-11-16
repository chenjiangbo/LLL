'use client';
import { useEffect, useState, useCallback } from 'react';
import {
  Activity, AlertTriangle, CheckCircle2, ChevronDown, ChevronRight,
  Loader2, RefreshCw, XCircle, MinusCircle, PlayCircle,
} from 'lucide-react';

// ── Types ──────────────────────────────────────────────────────────────────
type RunInfo = {
  run_id: string;
  trade_date: string;
  status: string;
  config_version: string;
  data_version: string;
  started_at: string;
  finished_at?: string;
  summary_json?: Record<string, unknown>;
};

type FunnelRow = { pool_code: string; stage: string; status: string; cnt: number };

type StageRow = {
  ts_code: string;
  pool_code: string;
  stage: string;
  status: string;
  score?: number;
  score_detail?: Record<string, unknown>;
};

type ReasonRow = {
  ts_code: string;
  pool_code: string;
  stage: string;
  reason_code: string;
  severity: string;
  actual_value?: number;
  threshold_value?: number;
  message?: string;
};

type StockAudit = { stages: StageRow[]; reasons: ReasonRow[] };

// ── Constants ──────────────────────────────────────────────────────────────
const API = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL ?? '';
const STAGES = ['L0', 'L1', 'L2', 'L3'];
const STAGE_LABEL: Record<string, string> = {
  L0: 'L0 候选池',
  L1: 'L1 硬过滤',
  L2: 'L2 质量分',
  L3: 'L3 相对强度',
};
const STATUS_COLOR: Record<string, string> = {
  PASS:          'text-emerald-400',
  FAIL:          'text-rose-400',
  DEFER:         'text-amber-400',
  DATA_MISSING:  'text-orange-400',
  NOT_EVALUATED: 'text-zinc-500',
};
const STATUS_BG: Record<string, string> = {
  PASS:          'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30',
  FAIL:          'bg-rose-500/15 text-rose-300 border border-rose-500/30',
  DEFER:         'bg-amber-500/15 text-amber-300 border border-amber-500/30',
  DATA_MISSING:  'bg-orange-500/15 text-orange-300 border border-orange-500/30',
  NOT_EVALUATED: 'bg-zinc-800 text-zinc-500 border border-zinc-700',
};
const POOL_COLORS: Record<string, string> = {
  A: 'bg-violet-600/20 text-violet-300 border border-violet-500/40',
  B: 'bg-sky-600/20 text-sky-300 border border-sky-500/40',
  C: 'bg-teal-600/20 text-teal-300 border border-teal-500/40',
};

// ── Helpers ────────────────────────────────────────────────────────────────
async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${STATUS_BG[status] ?? STATUS_BG['NOT_EVALUATED']}`}>
      {status}
    </span>
  );
}

function PoolBadge({ pool }: { pool: string }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-bold ${POOL_COLORS[pool] ?? 'bg-zinc-700 text-zinc-300'}`}>
      {pool}池
    </span>
  );
}

// ── Funnel bar ─────────────────────────────────────────────────────────────
function FunnelBar({ label, passCount, failCount, total, onClick, active }: {
  label: string; passCount: number; failCount: number; total: number;
  onClick?: () => void; active?: boolean;
}) {
  const pct = total > 0 ? Math.round((passCount / total) * 100) : 0;
  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded-xl p-4 border transition-all duration-200 ${
        active
          ? 'border-violet-500/60 bg-violet-900/20 shadow-lg shadow-violet-900/20'
          : 'border-zinc-700/60 bg-zinc-800/40 hover:border-zinc-600 hover:bg-zinc-800/70'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-semibold text-zinc-200">{label}</span>
        <span className="text-xs text-zinc-400">{passCount.toLocaleString()} / {total.toLocaleString()}</span>
      </div>
      <div className="relative h-2 rounded-full bg-zinc-700/60 overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-emerald-500 to-emerald-400 transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between mt-1.5">
        <span className="text-xs text-emerald-400">通过 {passCount.toLocaleString()}</span>
        {failCount > 0 && <span className="text-xs text-rose-400">淘汰 {failCount.toLocaleString()}</span>}
        <span className="text-xs text-zinc-500">{pct}%</span>
      </div>
    </button>
  );
}

// ── Stock inspector ────────────────────────────────────────────────────────
function StockInspector({ runId }: { runId: string }) {
  const [code, setCode] = useState('');
  const [query, setQuery] = useState('');
  const [audit, setAudit] = useState<StockAudit | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lookup = useCallback(async (tsCode: string) => {
    if (!tsCode.trim()) return;
    setLoading(true);
    setError(null);
    setAudit(null);
    try {
      const data = await apiFetch<StockAudit & { ts_code: string }>(
        `/api/screening/runs/${runId}/stocks/${tsCode.trim()}`
      );
      setAudit(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [runId]);

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { setCode(query); lookup(query); } }}
          placeholder="输入股票代码（如 600519.SH）"
          className="flex-1 bg-zinc-800 border border-zinc-600 text-zinc-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-violet-500 placeholder:text-zinc-500"
        />
        <button
          onClick={() => { setCode(query); lookup(query); }}
          className="bg-violet-600 hover:bg-violet-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
        >
          查询
        </button>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-zinc-400 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" />查询中…
        </div>
      )}
      {error && <div className="text-rose-400 text-sm">{error}</div>}

      {audit && !loading && (
        <div className="space-y-3">
          {/* Timeline */}
          <div className="flex items-start gap-0">
            {STAGES.map((stage, i) => {
              const snap = audit.stages.find(s => s.stage === stage);
              const status = snap?.status ?? 'NOT_EVALUATED';
              const score = snap?.score;
              const isLast = i === STAGES.length - 1;
              return (
                <div key={stage} className="flex items-center flex-1">
                  <div className="flex flex-col items-center">
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 ${
                      status === 'PASS' ? 'border-emerald-500 bg-emerald-900/40 text-emerald-300' :
                      status === 'FAIL' ? 'border-rose-500 bg-rose-900/40 text-rose-300' :
                      status === 'DEFER' ? 'border-amber-500 bg-amber-900/40 text-amber-300' :
                      'border-zinc-600 bg-zinc-800 text-zinc-500'
                    }`}>
                      {stage}
                    </div>
                    <div className="text-xs text-zinc-400 mt-1 whitespace-nowrap">{STAGE_LABEL[stage]}</div>
                    {score != null && <div className="text-xs text-zinc-300 font-mono">{score.toFixed(1)}</div>}
                    <StatusBadge status={status} />
                  </div>
                  {!isLast && (
                    <div className={`h-0.5 flex-1 mx-1 ${
                      status === 'PASS' ? 'bg-emerald-500/50' : 'bg-zinc-700'
                    }`} />
                  )}
                </div>
              );
            })}
          </div>

          {/* Reasons */}
          {audit.reasons.length > 0 && (
            <div className="rounded-xl border border-rose-500/20 bg-rose-900/10 p-4 space-y-2">
              <div className="text-xs font-semibold text-rose-300 uppercase tracking-wider mb-2">淘汰原因</div>
              {audit.reasons.map((r, i) => (
                <div key={i} className="flex items-start gap-3 text-sm">
                  <span className="mt-0.5 text-xs px-1.5 py-0.5 rounded bg-rose-900/40 text-rose-300 font-mono whitespace-nowrap">
                    {r.reason_code}
                  </span>
                  <span className="text-zinc-300">{r.message}</span>
                  {r.actual_value != null && (
                    <span className="text-zinc-500 text-xs ml-auto whitespace-nowrap">
                      实际: {r.actual_value.toFixed(2)} / 阈值: {r.threshold_value?.toFixed(2)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Score detail for L2 */}
          {audit.stages.filter(s => s.stage === 'L2' && s.score_detail && s.status === 'PASS').map(s => (
            <div key={s.stage} className="rounded-xl border border-zinc-700 bg-zinc-800/40 p-4">
              <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">L2 质量分明细</div>
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(s.score_detail ?? {}).filter(([k]) => k !== 'note').map(([k, v]) => (
                  <div key={k} className="flex justify-between text-xs">
                    <span className="text-zinc-400">{k}</span>
                    <span className="text-zinc-200 font-mono">{String(v)}</span>
                  </div>
                ))}
              </div>
              {s.score_detail?.note != null && (
                <div className="mt-2 text-xs text-amber-400/80">{String(s.score_detail['note'])}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main AuditView ────────────────────────────────────────────────────────
export default function AuditView() {
  const [run, setRun] = useState<RunInfo | null>(null);
  const [funnel, setFunnel] = useState<FunnelRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const loadLatest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await apiFetch<RunInfo>('/api/screening/runs/latest');
      setRun(r);
      const f = await apiFetch<{ funnel: FunnelRow[] }>(`/api/screening/runs/${r.run_id}/funnel`);
      setFunnel(f.funnel);
    } catch (e: unknown) {
      if (e instanceof Error && e.message.startsWith('404')) {
        setError('暂无二次筛选记录，请先触发运行');
      } else {
        setError(String(e));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadLatest(); }, [loadLatest]);

  const triggerRun = async () => {
    if (!run?.trade_date) return;
    setRunning(true);
    setRunError(null);
    try {
      await apiFetch<unknown>(`/api/screening/secondary/run`);
      // POST requires body
      const res = await fetch(`${API}/api/screening/secondary/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trade_date: run.trade_date }),
      });
      if (!res.ok) throw new Error(await res.text());
      await loadLatest();
    } catch (e) {
      setRunError(String(e));
    } finally {
      setRunning(false);
    }
  };

  // Aggregate funnel counts per stage (across all pools)
  const stageSummary = STAGES.map(stage => {
    const rows = funnel.filter(r => r.stage === stage);
    const pass = rows.filter(r => r.status === 'PASS').reduce((s, r) => s + r.cnt, 0);
    const fail = rows.filter(r => r.status !== 'PASS' && r.status !== 'NOT_EVALUATED').reduce((s, r) => s + r.cnt, 0);
    const total = pass + fail;
    return { stage, pass, fail, total };
  });

  const l0Total = stageSummary.find(s => s.stage === 'L0')?.pass ?? 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-zinc-100">二次筛选审计</h2>
          {run && (
            <p className="text-xs text-zinc-500 mt-0.5">
              {run.trade_date} · {run.run_id} · <span className={run.status === 'DONE' ? 'text-emerald-400' : 'text-amber-400'}>{run.status}</span>
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadLatest}
            className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-200 border border-zinc-700 hover:border-zinc-500 px-3 py-1.5 rounded-lg transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" /> 刷新
          </button>
          <button
            onClick={triggerRun}
            disabled={running}
            className="flex items-center gap-1.5 text-xs bg-violet-600 hover:bg-violet-500 disabled:bg-zinc-700 text-white px-3 py-1.5 rounded-lg transition-colors font-semibold"
          >
            {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PlayCircle className="w-3.5 h-3.5" />}
            重新运行
          </button>
        </div>
      </div>
      {runError && <div className="text-rose-400 text-xs">{runError}</div>}

      {loading && (
        <div className="flex items-center gap-2 text-zinc-400 text-sm py-12 justify-center">
          <Loader2 className="w-5 h-5 animate-spin" /> 加载中…
        </div>
      )}
      {error && !loading && (
        <div className="flex items-center gap-2 text-amber-400 text-sm">{error}</div>
      )}

      {!loading && !error && run && (
        <>
          {/* Funnel cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {stageSummary.map(({ stage, pass, fail }) => (
              <FunnelBar
                key={stage}
                label={STAGE_LABEL[stage]}
                passCount={pass}
                failCount={fail}
                total={l0Total || pass + fail}
                active={selectedStage === stage}
                onClick={() => setSelectedStage(selectedStage === stage ? null : stage)}
              />
            ))}
          </div>

          {/* Elimination waterfall */}
          <div className="rounded-xl border border-zinc-700/60 bg-zinc-800/30 p-4">
            <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">淘汰瀑布</div>
            <div className="flex items-center gap-2 flex-wrap">
              {stageSummary.map(({ stage, pass, fail }, i) => (
                <div key={stage} className="flex items-center gap-2">
                  <div className="text-center">
                    <div className="text-xl font-bold text-zinc-100">{pass.toLocaleString()}</div>
                    <div className="text-xs text-zinc-400">{STAGE_LABEL[stage]}</div>
                    {fail > 0 && (
                      <div className="text-xs text-rose-400 mt-0.5">−{fail.toLocaleString()}</div>
                    )}
                  </div>
                  {i < stageSummary.length - 1 && (
                    <ChevronRight className="w-5 h-5 text-zinc-600 flex-shrink-0" />
                  )}
                </div>
              ))}
              <div className="ml-auto text-right">
                <div className="text-xs text-zinc-500">最终通过率</div>
                <div className="text-2xl font-bold text-emerald-400">
                  {l0Total > 0 ? Math.round((stageSummary[stageSummary.length - 1].pass / l0Total) * 100) : 0}%
                </div>
              </div>
            </div>
          </div>

          {/* Per-pool breakdown table */}
          {funnel.length > 0 && (
            <div className="rounded-xl border border-zinc-700/60 bg-zinc-800/30 overflow-hidden">
              <div className="px-4 py-3 border-b border-zinc-700/60 text-xs font-semibold text-zinc-400 uppercase tracking-wider">
                分池 × 分层明细
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-700/40">
                      <th className="text-left px-4 py-2 text-xs text-zinc-500">池</th>
                      {STAGES.map(s => (
                        <th key={s} className="text-center px-2 py-2 text-xs text-zinc-500">{s}</th>
                      ))}
                    </tr>
                    <tr className="border-b border-zinc-700/30">
                      <th className="px-4 py-1" />
                      {STAGES.map(s => (
                        <th key={s} className="text-center px-2 py-1 text-xs text-zinc-500">通过/淘汰</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {['A-Pre', 'A', 'B', 'C'].map(pool => (
                      <tr key={pool} className="border-b border-zinc-800 hover:bg-zinc-800/40">
                        <td className="px-4 py-2"><PoolBadge pool={pool} /></td>
                        {STAGES.map(stage => {
                          const rows = funnel.filter(r => r.stage === stage && r.pool_code === pool);
                          const pass = rows.filter(r => r.status === 'PASS').reduce((s, r) => s + r.cnt, 0);
                          const fail = rows.filter(r => r.status !== 'PASS' && r.status !== 'NOT_EVALUATED').reduce((s, r) => s + r.cnt, 0);
                          return (
                            <td key={stage} className="text-center px-1 py-2 font-mono text-xs">
                              <span className="text-emerald-400">{pass || '—'}</span>
                              {' / '}
                              <span className="text-rose-400">{fail || '—'}</span>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Stock inspector */}
          <div className="rounded-xl border border-zinc-700/60 bg-zinc-800/30 p-4 space-y-3">
            <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">个股审计轨迹</div>
            <StockInspector runId={run.run_id} />
          </div>
        </>
      )}
    </div>
  );
}
