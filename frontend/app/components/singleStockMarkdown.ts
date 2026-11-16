import { preQualificationText, type PreQualification, type RoundedRepair } from './preQualification';
import { doubleBottomLabel } from './doubleBottomLabel';

export interface SingleStockMarkdownResult {
  ts_code: string;
  name: string;
  industry: string;
  strategy_id: string;
  start_date: string;
  end_date: string;
  history: Array<{
    trade_date: string;
    close: number;
    total_score: number;
    prep_score?: number | null;
    turn_score?: number | null;
    pre_qualification?: PreQualification | null;
    rounded_repair?: RoundedRepair | null;
    pre_entry_reason?: string | null;
    pre_confirm_date?: string | null;
    turn_episode_state?: string | null;
    score_type?: 'PREP_SCORE' | 'TURN_SCORE' | 'NONE';
    state: string;
    episode_replay_version?: string | null;
    episode_replay_start_date?: string | null;
    episode_replay_first_evaluation_date?: string | null;
    background_type: string;
    score_detail_json?: Record<string, any>;
    reasons_json?: Array<{ msg: string }>;
    episode_base_low?: number | null;
    episode_base_low_date?: string | null;
    first_wave_high_close?: number | null;
    first_wave_high_date?: string | null;
    first_wave_gain?: number | null;
    first_wave_gain_atr?: number | null;
    first_wave_formed?: boolean;
    first_wave_formation_bars?: number | null;
    first_wave_speed?: 'FAST' | 'NORMAL' | null;
    bottom_structure_type?: string | null;
    bottom_structure_quality?: string | null;
    bottom_first_low_date?: string | null;
    bottom_second_low_date?: string | null;
    bottom_structure_confirmed_date?: string | null;
    early_observation?: { active: boolean; first_date?: string; ma5?: number; ma10?: number; ma5_slope_3d?: number; ma10_slope_5d?: number; retake_count?: number } | null;
    second_opportunity?: { active: boolean; types: string[] } | null;
    drawdown_from_first_wave_high?: number | null;
    last_closed_episode?: {
      pre_enter_date: string | null;
      first_trigger_date: string | null;
      post_enter_date: string | null;
      end_date: string;
      end_reason: string;
      end_signals: string[];
    } | null;
  }>;
  klines?: Array<{
    trade_date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    vol: number;
    amount: number;
    ma5: number | null;
    ma10: number | null;
    ma20: number | null;
    ma30: number | null;
    ma60: number | null;
  }>;
}

function stateLabel(state: string): string {
  if (state === 'FIRST_TURN_WINDOW') return '首次转强';
  if (state === 'POST_FIRST_WAVE') return '第一波已完成';
  if (state === 'PRE_FIRST_TURN') return '底部准备中';
  if (state === 'OUTSIDE_A_PRE') return '未进入 A-Pre';
  return state || '无信号';
}

function backgroundLabel(value: string): string {
  if (value === 'FIRST_TURN') return '首次底部转向';
  if (value === 'SECONDARY_TURN') return '二次转强突破';
  if (value === 'CONSOLIDATION_RESTART') return '整理后再启动';
  return value || '未标注';
}

function formatKlineNumber(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined || Number.isNaN(value) ? '-' : value.toFixed(digits);
}

export function buildSingleStockMarkdown(result: SingleStockMarkdownResult): string {
  const lines: string[] = [];
  lines.push(`# 📊 ${result.ts_code} ${result.name} 区间逐日评分拆解报告`);
  lines.push(`\n- **股票代码**: \`${result.ts_code}\``);
  lines.push(`- **股票名称**: **${result.name}**`);
  lines.push(`- **所属行业**: \`${result.industry}\``);
  lines.push(`- **策略模型**: \`${result.strategy_id}\``);
  const replay = result.history[result.history.length - 1];
  if (replay?.episode_replay_version) lines.push(`- **回放版本**: \`${replay.episode_replay_version}\``);
  if (replay?.episode_replay_start_date) lines.push(`- **行情回放起点**: \`${replay.episode_replay_start_date}\`（首次具备评估数据：\`${replay.episode_replay_first_evaluation_date || '-'}\`）`);
  lines.push(`- **评估区间**: \`${result.start_date}\` 至 \`${result.end_date}\` (共 ${result.history.length} 个交易日)`);
  lines.push(`- **导出时间**: \`${new Date().toLocaleString('zh-CN')}\``);
  lines.push(`\n---`);
  lines.push(`\n## 📅 交易日逐日评分拆解明细\n`);
  lines.push(`| 交易日期 | 收盘价 | 评分 | 评级状态 | 背景类型 | 评分拆解 | 生命周期诊断 | 主要特征诊断与说明 |`);
  lines.push(`| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |`);
  result.history.forEach((item) => {
    const details = item.score_detail_json?.v2_details || {};
    const date = item.trade_date.length === 8 ? `${item.trade_date.slice(0, 4)}-${item.trade_date.slice(4, 6)}-${item.trade_date.slice(6, 8)}` : item.trade_date;
    const outside = (item.turn_episode_state || item.state) === 'OUTSIDE_A_PRE';
    const isPrep = item.prep_score != null;
    const score = item.prep_score;
    const scoreTypeLabel = `底部准备度${outside ? '（尚未进入底部准备）' : ''}${item.turn_episode_state === 'FIRST_TURN_WINDOW' && item.turn_score != null ? `<br>转强确认 ${item.turn_score.toFixed(1)}分` : ''}`;
    const ops = isPrep
      ? `走平拐头:${details.prep?.slope_turn ?? 0}/40${details.prep?.slope_breakdown ? `（MA5:${details.prep.slope_breakdown.ma5}/15，MA10:${details.prep.slope_breakdown.ma10}/15，MA20:${details.prep.slope_breakdown.ma20}/10）` : ''} | 均线结构:${details.prep?.compression_cross ?? 0}/25 | 夺回${item.score_detail_json?.retake_count ?? "—"}根均线:${details.prep?.retake ?? "—"}/20 | 背景位置:${details.prep?.background_position ?? 0}/15${details.prep?.bottom_bonus != null ? ` | 原准备度:${details.prep.base_score} | 日线双底加分:+${details.prep.bottom_bonus}` : ''} | MA10斜率:${((details.ma10_slope_5d ?? 0) * 100).toFixed(2)}% | MA20斜率:${((details.ma20_slope_5d ?? 0) * 100).toFixed(2)}% | MA10改善:${((details.ma10_curve_improve ?? 0) * 100).toFixed(2)}% | MA20改善:${((details.ma20_curve_improve ?? 0) * 100).toFixed(2)}% | 均线离散/ATR:${(details.ma_spread_atr ?? 0).toFixed(2)}`
      : `Base:${item.score_detail_json?.background || 0} | Trans:${details.transition || 0}(penalty:-${details.chop_penalty || 0}) | Retake:${details.retake || 0} | Dir:${details.direction || 0} | Fresh:${details.freshness || 0} | Vol:${details.vol || 0} | Space:${details.space || 0}`;
    const reasons = item.reasons_json && item.reasons_json.length > 0 ? item.reasons_json.map((r) => r.msg).join('； ') : '形态处于整理蓄势期';
    const closed = item.last_closed_episode;
    const signalLabels: Record<string, string> = { NEW_60D_LOW: '创60日新低', NEAR_EPISODE_BASE: '接近旧周期底部', EFFECTIVE_BASE_BREAK: '收盘有效跌破旧底', EXTREME_PROTRACTED_BREAK: '深度回撤且持续破位' };
    const closedReason = closed?.end_reason === 'STRUCTURAL_FAILURE'
      ? `跌破旧触发区，${closed.end_signals.map((signal) => signalLabels[signal] || signal).join('、')}`
      : closed?.end_reason === 'EARLY_REPAIR_FAILURE' ? '早期修复失败，收盘跌回短均线下方' : '冷却期结束';
    const lifecycle = [
      item.second_opportunity?.active ? `二买机会：${item.second_opportunity.types.map(kind => kind === 'PULLBACK_RECOVERY' ? '回调企稳' : kind === 'CONSOLIDATION_BREAKOUT' ? '横盘突破' : kind).join('、')}` : '二买机会：暂无',
      item.bottom_structure_quality && item.bottom_structure_quality !== 'NONE' ? `${doubleBottomLabel(item.bottom_structure_type, item.bottom_structure_quality)}：第一底 ${item.bottom_first_low_date || '-'}，第二底 ${item.bottom_second_low_date || '-'}，确认 ${item.bottom_structure_confirmed_date || '-'}` : null,
      preQualificationText(item.pre_qualification, item.rounded_repair),
      item.pre_entry_reason ? `进入方式：${item.pre_entry_reason === 'EARLY_ROUNDED_REPAIR' ? '早期圆弧修复' : '持续修复确认'}${item.pre_confirm_date ? `，确认 ${item.pre_confirm_date}` : ''}` : null,
      item.early_observation?.active ? `提前修复观察：首次 ${item.early_observation.first_date}；MA5 ${item.early_observation.ma5?.toFixed(2)}（连续修复）；MA10 ${item.early_observation.ma10?.toFixed(2)}，斜率 ${((item.early_observation.ma10_slope_5d ?? 0) * 100).toFixed(2)}%；夺回${item.early_observation.retake_count}根均线` : null,
      item.episode_base_low != null ? `基准低:${item.episode_base_low.toFixed(2)}(${item.episode_base_low_date || '-'})` : null,
      item.first_wave_high_close != null ? `第一波峰:${item.first_wave_high_close.toFixed(2)}(${item.first_wave_high_date || '-'})` : null,
      item.first_wave_gain != null ? `底→峰:${(item.first_wave_gain * 100).toFixed(1)}%` : null,
      item.first_wave_gain_atr != null ? `底→高:${item.first_wave_gain_atr.toFixed(1)}ATR` : null,
      item.first_wave_formed != null ? `第一波:${item.first_wave_formed ? '已形成' : '未形成'}` : null,
      item.first_wave_speed === 'FAST' ? `快速第一波候选（${item.first_wave_formation_bars}个交易日）` : null,
      item.drawdown_from_first_wave_high != null ? `峰值回撤:${(item.drawdown_from_first_wave_high * 100).toFixed(1)}%` : null,
      closed ? `上一周期：底部准备 ${closed.pre_enter_date || '-'}、首次转强 ${closed.first_trigger_date || '-'}、第一波完成 ${closed.post_enter_date || '-'}；${closed.end_date} 结束（${closedReason}）` : null,
    ].filter(Boolean).join('； ') || '尚未建立 Episode';
    lines.push(`| \`${date}\` | \`${item.close.toFixed(2)}\` | **${score != null ? score.toFixed(1) : '--'}分**<br>${scoreTypeLabel} | ${stateLabel(item.state)} | ${backgroundLabel(item.background_type)} | \`${ops}\` | ${lifecycle} | ${reasons} |`);
  });
  lines.push(`\n---`);
  lines.push(`\n## 📈 每日 K 线数据（最近 ${result.klines?.length || 0} 个交易日）\n`);
  lines.push(`| 交易日期 | 开盘 | 最高 | 最低 | 收盘 | 成交量 | 成交额 | MA5 | MA10 | MA20 | MA30 | MA60 |`);
  lines.push(`| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |`);
  if (result.klines && result.klines.length > 0) {
    result.klines.forEach((kline) => {
      const date = kline.trade_date.length === 8 ? `${kline.trade_date.slice(0, 4)}-${kline.trade_date.slice(4, 6)}-${kline.trade_date.slice(6, 8)}` : kline.trade_date;
      lines.push(`| \`${date}\` | ${formatKlineNumber(kline.open)} | ${formatKlineNumber(kline.high)} | ${formatKlineNumber(kline.low)} | ${formatKlineNumber(kline.close)} | ${formatKlineNumber(kline.vol, 0)} | ${formatKlineNumber(kline.amount, 0)} | ${formatKlineNumber(kline.ma5)} | ${formatKlineNumber(kline.ma10)} | ${formatKlineNumber(kline.ma20)} | ${formatKlineNumber(kline.ma30)} | ${formatKlineNumber(kline.ma60)} |`);
    });
  } else {
    lines.push(`| - | - | - | - | - | - | - | - | - | - | - | - |`);
    lines.push(`\n> 当前接口未返回可导出的日 K 线数据。`);
  }
  return lines.join('\n');
}

export function downloadSingleStockMarkdown(result: SingleStockMarkdownResult): void {
  const blob = new Blob([buildSingleStockMarkdown(result)], { type: 'text/markdown;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${result.ts_code}_${result.name}_逐日打分拆解报告_${result.start_date}_${result.end_date}.md`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
