/** 日线计算得到的两底结构；短间隔不代表已识别分钟线形态。 */
export function doubleBottomLabel(type?: string | null, quality?: string | null): string {
  if (quality === 'NONE') return '未识别';
  if (!quality) return '暂无数据';
  if (type === 'MICRO_DOUBLE_BOTTOM') return '短间隔双底';
  if (type === 'STANDARD_DOUBLE_BOTTOM') return quality === 'CLEAR' ? '日线双底·明显' : '日线双底·可能';
  return quality === 'CLEAR' ? '双底·明显' : '双底·可能';
}
