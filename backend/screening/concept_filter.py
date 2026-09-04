from __future__ import annotations

import re


LOW_SIGNAL_CONCEPT_NAMES = {
    "融资融券",
    "沪股通",
    "深股通",
    "陆股通",
    "富时罗素",
    "标普道琼斯A股",
    "MSCI概念",
    "转融券标的",
    "证金持股",
}

LOW_SIGNAL_CONCEPT_PATTERN = re.compile(
    r"同花顺|昨日|融资融券|沪股通|深股通|陆股通|MSCI|富时罗素|标普|"
    r"样本股|成份股|成分股|全A|沪深|A股|指数|大盘|中盘|小盘|"
    r"高估值|低估值|高动量|低动量|高盈利|低盈利|均衡|保守投资|激进投资|"
    r"百日新高|高贝塔|股性|减持|增发|可转债|基金重仓|保险重仓|社保重仓|"
    r"城市群|都市圈|华东|华南|华北|华中|西南|西北|东北|广东|江苏|浙江|上海|深圳|北京|河北|湖北"
)


def is_low_signal_ths_concept(name: str | None) -> bool:
    clean = (name or "").strip()
    if not clean:
        return True
    return clean in LOW_SIGNAL_CONCEPT_NAMES or bool(LOW_SIGNAL_CONCEPT_PATTERN.search(clean))


def filter_ths_concept_names(names: list[str]) -> list[str]:
    result: list[str] = []
    for name in names:
        clean = (name or "").strip()
        if clean and clean not in result and not is_low_signal_ths_concept(clean):
            result.append(clean)
    return result
