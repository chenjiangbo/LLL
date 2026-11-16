export type AShareExchange = "SH" | "SZ";

export const ORDER_TYPE_LABELS: Record<string, string> = {
  LIMIT: "限价",
  MARKET: "市价（交易所默认方式）",
  MARKET_BOC: "对手方最优价",
  MARKET_BOP: "本方最优价",
  MARKET_FAK: "即时成交，余量撤销",
  MARKET_FOK: "全额成交或撤销",
  MARKET_B5TC: "最优五档成交，余量撤销",
  MARKET_B5TL: "最优五档成交，余量转限价",
};

const ORDER_TYPES_BY_EXCHANGE: Record<AShareExchange, string[]> = {
  SH: ["LIMIT", "MARKET", "MARKET_BOC", "MARKET_BOP", "MARKET_B5TC", "MARKET_B5TL"],
  SZ: ["LIMIT", "MARKET", "MARKET_BOC", "MARKET_BOP", "MARKET_FAK", "MARKET_FOK", "MARKET_B5TC"],
};

export function exchangeFromSymbol(symbol: unknown): AShareExchange {
  const value = String(symbol || "").trim().toUpperCase();
  if (/^(SH|SSE|SHSE)[:.]/.test(value) || value.endsWith(".SH")) return "SH";
  if (/^(SZ|SZSE)[:.]/.test(value) || value.endsWith(".SZ")) return "SZ";
  if (/^6/.test(value)) return "SH";
  if (/^[03]/.test(value)) return "SZ";
  throw new Error(`无法从证券代码识别交易所：${value}`);
}

export function orderTypesForExchange(exchange: AShareExchange) {
  return ORDER_TYPES_BY_EXCHANGE[exchange].map((value) => [value, ORDER_TYPE_LABELS[value]] as const);
}

export function orderTypeLabel(value: unknown) {
  return ORDER_TYPE_LABELS[String(value || "").toUpperCase()] || "委托类型未记录";
}

export function orderTypeDescription(value: unknown, exchange: AShareExchange) {
  const descriptions: Record<string, string> = {
    LIMIT: "只按你填写的价格或更优价格成交；暂时不合适就按该价排队，不会追价。",
    MARKET: exchange === "SH"
      ? "买入按卖方、卖出按买方实时报价逐档撮合，最多五档；余量转限价，受保护限价约束。"
      : "深交所默认按对手方最优价：买入看卖一（例：1.55），卖出看买一（1.45）。",
    MARKET_BOC: "按提交时对手方最优价申报：买入取卖一、卖出取买一；未成交余量按该价挂单。",
    MARKET_BOP: "按提交时本方最优价申报：买入取买一、卖出取卖一；通常不会立即与对手盘成交。",
    MARKET_FAK: "按对手方所有档位依次成交；能成交多少就成交多少，剩余数量立即撤销。",
    MARKET_FOK: "对手方所有档位合计足够时才全部成交；数量不足则整笔立即撤销。",
    MARKET_B5TC: "按对手方最优五档逐档撮合；五档内仍未成交的数量自动撤销。",
    MARKET_B5TL: "按对手方最优五档逐档撮合；未成交余量转限价挂单，无成交时按本方最优价挂单。",
  };
  return descriptions[String(value || "").toUpperCase()] || "";
}

export function isMarketOrder(value: unknown) {
  return String(value || "").toUpperCase() !== "LIMIT";
}
