export type PreQualification = {
  decline_context?: boolean | null;
  ma5_confirmed?: boolean | null;
  ma5_rounded?: boolean | null;
  ma10_confirmed?: boolean | null;
  ma10_recent_repair?: boolean | null;
  ma10_deceleration?: boolean | null;
  ma10_slope_5d?: number | null;
  price_retake?: boolean | null;
  retake_count?: number | null;
  repair_context?: boolean | null;
  eligible?: boolean;
};
export type RoundedRepair = {
  indicators_available?: boolean;
  decline_context?: boolean;
  ma5_rounded?: boolean;
  ma5_decelerating?: boolean;
  ma5_flattened?: boolean;
  ma5_turning_up?: boolean;
  ma10_repair?: boolean;
  above_ma5_ma10?: boolean;
  eligible?: boolean;
};
const verdict = (value?: boolean | null) => value == null ? '数据不足' : value ? '通过' : '未通过';
export function preQualificationText(q?: PreQualification | null, rounded?: RoundedRepair | null): string {
  if (!q) return '暂无底部准备条件数据';
  const slope = typeof q.ma10_slope_5d === 'number' ? `（五日 ${(q.ma10_slope_5d * 100).toFixed(2)}%${q.ma10_recent_repair ? '，近期企稳' : q.ma10_deceleration ? '，近期下跌减速' : ''}）` : '';
  const confirmed = `底部准备：下跌背景${verdict(q.decline_context)}，MA5圆弧修复${verdict(q.ma5_rounded)}，MA10走平${verdict(q.ma10_confirmed)}${slope}，站上MA5和MA10${verdict(q.price_retake)}，压缩或交叉${verdict(q.repair_context)}`;
  if (!rounded?.indicators_available) return confirmed;
  const missing = [
    rounded.ma5_decelerating === false ? '尚未形成下跌减速过程' : '',
    rounded.ma5_flattened === false ? '平缓过渡不足' : '',
    rounded.ma5_turning_up === false && !rounded.ma5_rounded ? '尚未走平或抬头' : '',
  ].filter(Boolean).join('、');
  const detail = missing || (rounded.ma5_rounded === false ? '尚未形成连续的减速、平缓和回升过程' : '');
  return `${confirmed}${detail ? `；MA5：${detail}` : ''}`;
}
