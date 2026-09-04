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
    score_type?: 'PREP_SCORE' | 'TURN_SCORE' | 'NONE';
    state: string;
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
    drawdown_from_first_wave_high?: number | null;
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
  lines.push(`- **评估区间**: \`${result.start_date}\` 至 \`${result.end_date}\` (共 ${result.history.length} 个交易日)`);
  lines.push(`- **导出时间**: \`${new Date().toLocaleString('zh-CN')}\``);
  lines.push(`\n---`);
  lines.push(`\n## 📅 交易日逐日评分拆解明细\n`);
  lines.push(`| 交易日期 | 收盘价 | 评分 | 评级状态 | 背景类型 | 评分拆解 | 生命周期诊断 | 主要特征诊断与说明 |`);
  lines.push(`| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |`);
  result.history.forEach((item) => {
    const details = item.score_detail_json?.v2_details || {};
    const date = item.trade_date.length === 8 ? `${item.trade_date.slice(0, 4)}-${item.trade_date.slice(4, 6)}-${item.trade_date.slice(6, 8)}` : item.trade_date;
    const isPrep = item.score_type === 'PREP_SCORE' || details.score_type === 'PREP_SCORE';
    const scoreTypeLabel = isPrep ? 'PREP_SCORE（底部准备度）' : details.score_type === 'TURN_SCORE' ? 'TURN_SCORE（转强确认度）' : '诊断分';
    const ops = isPrep
      ? `走平拐头:${details.prep?.slope_turn ?? 0}/40 | 靠拢交叉:${details.prep?.compression_cross ?? 0}/25 | 夺回均线:${details.prep?.retake ?? 0}/20 | 背景位置:${details.prep?.background_position ?? 0}/15 | MA10斜率:${((details.ma10_slope_5d ?? 0) * 100).toFixed(2)}% | MA20斜率:${((details.ma20_slope_5d ?? 0) * 100).toFixed(2)}% | MA10改善:${((details.ma10_curve_improve ?? 0) * 100).toFixed(2)}% | MA20改善:${((details.ma20_curve_improve ?? 0) * 100).toFixed(2)}% | 均线离散/ATR:${(details.ma_spread_atr ?? 0).toFixed(2)}`
      : `Base:${item.score_detail_json?.background || 0} | Trans:${details.transition || 0}(penalty:-${details.chop_penalty || 0}) | Retake:${details.retake || 0} | Dir:${details.direction || 0} | Fresh:${details.freshness || 0} | Vol:${details.vol || 0} | Space:${details.space || 0}`;
    const reasons = item.reasons_json && item.reasons_json.length > 0 ? item.reasons_json.map((r) => r.msg).join('； ') : '形态处于整理蓄势期';
    const lifecycle = [
      item.episode_base_low != null ? `基准低:${item.episode_base_low.toFixed(2)}(${item.episode_base_low_date || '-'})` : null,
      item.first_wave_high_close != null ? `第一波峰:${item.first_wave_high_close.toFixed(2)}(${item.first_wave_high_date || '-'})` : null,
      item.first_wave_gain != null ? `底→峰:${(item.first_wave_gain * 100).toFixed(1)}%` : null,
      item.first_wave_gain_atr != null ? `底→高:${item.first_wave_gain_atr.toFixed(1)}ATR` : null,
      item.first_wave_formed != null ? `第一波:${item.first_wave_formed ? '已形成' : '未形成'}` : null,
      item.drawdown_from_first_wave_high != null ? `峰值回撤:${(item.drawdown_from_first_wave_high * 100).toFixed(1)}%` : null,
    ].filter(Boolean).join('； ') || '尚未建立 Episode';
    lines.push(`| \`${date}\` | \`${item.close.toFixed(2)}\` | **${item.total_score.toFixed(1)}分**<br>${scoreTypeLabel} | ${stateLabel(item.state)} | ${backgroundLabel(item.background_type)} | \`${ops}\` | ${lifecycle} | ${reasons} |`);
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
