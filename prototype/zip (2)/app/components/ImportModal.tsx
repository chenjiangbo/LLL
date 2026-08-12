'use client';

import React, { useState } from 'react';
import { X, Upload, Sparkles, FileText, Loader2, Calendar } from 'lucide-react';

const SAMPLE_AUG_04 = `# 2026年8月4日A股市场复盘
## 一、先说结论
8月4日是一次力度很强的**科技成长股修复行情**：

**成交额重新放大，创业板、CPO、PCB、半导体和CRO集中反攻，市场情绪明显回暖；但这还不能证明7月份形成的周线调整已经结束。**

当天的行情不是8月3日“小盘股普涨”的简单延续，而是发生了明显的风格切换：

+ 8月3日：科技权重下跌，微盘股和低位题材上涨；
+ 8月4日：资金大举回流科技权重，银行、保险等传统权重回落；
+ 创业板大涨5.64%，但沪指只上涨0.33%，说明资金主要集中在成长赛道，而不是全面推升所有权重板块。

---

## 二、主要市场数据
| 指标 | 8月4日收盘 | 涨跌幅 |
| --- | --- | --- |
| 上证指数 | 3822.28点 | +0.33% |
| 深证成指 | 13885.71点 | +3.25% |
| 创业板指 | 3488.97点 | +5.64% |
| 科创50 | — | +4.09% |
| 沪深京成交额 | 22287亿元 | 增加2174亿元 |
| 上涨股票 | 约3642只 | 占约67.6% |
| 下跌股票 | 1747只 | — |
| 涨停股票 | 140只 | — |
| 跌停股票 | 1只 | — |

---

## 三、与8月3日相比，市场发生了什么变化
| 指标 | 8月3日 | 8月4日 |
| --- | --- | --- |
| 上证指数 | -0.59% | +0.33% |
| 深证成指 | -0.96% | +3.25% |
| 创业板指 | -1.24% | +5.64% |
| 科创50 | -5.08% | +4.09% |
| 成交额 | 20113亿元 | 22287亿元 |
| 市场主导方向 | 微盘、核电、电网 | CPO、PCB、半导体、CRO |

---

## 四、盘中走势
三大指数集体高开，开盘后CPO、PCB、半导体、创新药迅速走强，银行、保险相对弱势。午后科技股继续扩大战果，创业板收盘大涨5.64%。

# 五、领涨主线分析
## （一）CPO和光通信：当天最核心的主线
CPO、光模块和光通信对指数贡献最大。天孚通信、新易盛、中际旭创均上涨超过11%。东方财富主力资金显示通信设备获得222亿元净流入。

## （二）PCB与半导体
东山精密、沪电股份等多股涨停；半导体设备与材料同步走强。

## （三）CRO与医药
药明康德半年报业绩超预期涨停，带动医药板块全线上涨。`;

const SAMPLE_AUG_05 = `# 2026年8月5日中国A股市场复盘报告

**复盘日期：2026年8月5日**

## 一、核心结论
8月5日A股三大指数低开高走，成交额显著放大，市场延续了8月4日的科技修复行情。
与8月4日不同，8月5日出现了明显的内部切换：
> **CPO核心股经历天量分歧，资金转向半导体设备、材料、存储芯片、电子化学品、智能驾驶和贵金属。**

1. **指数低开高走**：创业板早盘一度低开3.35%，收盘上涨1.32%；科创50大涨4.78%。
2. **成交额大幅增加**：沪深两市成交约2.66万亿元，较8月4日增加约4460亿元（增幅约20%）。
3. **板块转向结构筛选**：半导体设备与材料领涨，CPO天量巨震。

---

## 二、主要指数和市场数据
| 指标 | 8月5日收盘 | 涨跌幅 |
| --- | ---: | ---: |
| 上证指数 | 3878.43点 | +1.47% |
| 深证成指 | 14144.20点 | +1.86% |
| 创业板指 | 3535.14点 | +1.32% |
| 科创50 | 1693.67点 | +4.78% |
| 沪深两市成交额 | 约2.66万亿元 | 增加约4460亿元 |
| 上涨股票 | 超过3700只 | — |
| 涨停股票 | 超过100只 | — |

---

## 三、8月3日至5日的三日结构
- **8月3日**：半导体集中抛售，微盘与低位题材上涨。
- **8月4日**：CPO、PCB与算力带动全面强反弹。
- **8月5日**：CPO天量分歧，半导体设备、材料与智能驾驶接力。

---

## 四、主要板块表现
1. **半导体设备与材料**：正帆科技20%涨停，有研新材、中巨芯等涨停，中微公司、拓荆科技大涨超10%。
2. **CPO分歧**：中际旭创成交额达到创纪录的675亿元，天量剧烈换手。
3. **智能驾驶与贵金属**：索菱股份等涨停；四川黄金涨停带动有色板块走强。`;

const SAMPLE_AUG_06 = `# 2026年8月6日中国A股市场复盘报告

**复盘日期：2026年8月6日**

## 一、核心结论
8月6日A股三大指数涨跌不一，市场发生明显的**指数分化与风格切换**：
> **煤炭、贵金属等资源方向推动沪指上涨；电子化学品、半导体材料、先进封装和通信设备维持科技局部热度；前两日大涨的高弹性成长股进入获利消化。**

沪深京成交额约2.55万亿元，较8月5日减少1324亿元（缩量4.9%）。

---

## 二、主要市场数据
| 指标 | 8月6日收盘 | 当日变化 |
| --- | ---: | ---: |
| 上证指数 | 3900.35点 | +0.57% |
| 深证成指 | 14110.12点 | -0.24% |
| 创业板指 | 3515.56点 | -0.55% |
| 科创综指 | — | +1.25% |
| 沪深京成交额 | 约2.55万亿元 | 减少1324亿元 |
| 上涨股票 | 接近2800只 | — |
| 涨停股票 | 83只 | — |

---

## 三、8月3日至6日市场演变链条
恐慌释放（8/3） → 全面修复（8/4） → 板块扩散（8/5） → 内部筛选分歧（8/6）。

---

## 四、核心主线
1. **煤炭资源**：昊华能源、潞安环能等多股涨停，受电力负荷创历史新高与低估值高股息驱动。
2. **电子化学品与半导体材料**：中巨芯、江化微等涨停，资金由高位硬件流向低位材料。
3. **6G与通信设备**：广哈通信、沃格光电等大涨，受AI基站与6G产业预期催化。`;

interface ImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (tradeDate: string) => void;
  apiBase?: string;
}

export default function ImportModal({ isOpen, onClose, onSuccess, apiBase = 'http://127.0.0.1:18080' }: ImportModalProps) {
  const [tradeDate, setTradeDate] = useState('2026-08-04');
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      if (text) {
        setContent(text);
        const dateMatch = file.name.match(/\d{4}[-_年]?\d{1,2}[-_月]?\d{1,2}/) || text.match(/\d{4}年\d{1,2}月\d{1,2}日/);
        if (dateMatch) {
          const cleaned = dateMatch[0].replace(/[年月]/g, '-').replace(/日/, '');
          setTradeDate(cleaned);
        }
      }
    };
    reader.readAsText(file);
  };

  const loadSample = (sampleType: 'aug04' | 'aug05' | 'aug06') => {
    setError(null);
    if (sampleType === 'aug04') {
      setTradeDate('2026-08-04');
      setContent(SAMPLE_AUG_04);
    } else if (sampleType === 'aug05') {
      setTradeDate('2026-08-05');
      setContent(SAMPLE_AUG_05);
    } else if (sampleType === 'aug06') {
      setTradeDate('2026-08-06');
      setContent(SAMPLE_AUG_06);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!content.trim()) {
      setError('请输入或导入复盘文章内容');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${apiBase}/api/market-review/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trade_date: tradeDate.trim() || undefined,
          content: content.trim(),
        }),
      });

      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || `HTTP ${res.status}`);
      }

      const data = await res.json();
      const savedDate = data.trade_date || tradeDate;
      setLoading(false);
      onSuccess(savedDate);
      onClose();
    } catch (err) {
      setLoading(false);
      setError(err instanceof Error ? err.message : '复盘解析导入失败');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4">
      <div className="w-full max-w-3xl rounded-xl border border-[#c4c8bc]/40 bg-[#faf6f0] p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between border-b border-[#c4c8bc]/30 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="rounded-lg bg-[#4a7c59]/10 p-2 text-[#4a7c59]">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-[#2e3230]">手工导入复盘文章</h2>
              <p className="text-xs text-[#686d68]">调用 AI 自动梳理结构化核心数据、多日演变与热点主线</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-[#686d68] hover:bg-[#e4e0d8] hover:text-[#2e3230]"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-[200px_1fr]">
            <div>
              <label className="mb-1 flex items-center gap-1.5 text-xs font-bold text-[#4a4e4a]">
                <Calendar className="h-3.5 w-3.5" />
                复盘交易日期
              </label>
              <input
                type="text"
                value={tradeDate}
                onChange={(e) => setTradeDate(e.target.value)}
                placeholder="YYYY-MM-DD"
                className="w-full rounded-md border border-[#c4c8bc]/60 bg-white px-3 py-2 text-sm text-[#2e3230] outline-none focus:border-[#4a7c59]"
              />
            </div>
            <div>
              <label className="mb-1 flex items-center gap-1.5 text-xs font-bold text-[#4a4e4a]">
                <FileText className="h-3.5 w-3.5" />
                快捷载入测试样本
              </label>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => loadSample('aug04')}
                  className="rounded-md border border-[#4a7c59]/40 bg-[#4a7c59]/10 px-3 py-1.5 text-xs font-bold text-[#4a7c59] hover:bg-[#4a7c59] hover:text-white"
                >
                  8月4日复盘
                </button>
                <button
                  type="button"
                  onClick={() => loadSample('aug05')}
                  className="rounded-md border border-[#4a7c59]/40 bg-[#4a7c59]/10 px-3 py-1.5 text-xs font-bold text-[#4a7c59] hover:bg-[#4a7c59] hover:text-white"
                >
                  8月5日复盘
                </button>
                <button
                  type="button"
                  onClick={() => loadSample('aug06')}
                  className="rounded-md border border-[#4a7c59]/40 bg-[#4a7c59]/10 px-3 py-1.5 text-xs font-bold text-[#4a7c59] hover:bg-[#4a7c59] hover:text-white"
                >
                  8月6日复盘
                </button>
              </div>
            </div>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <label className="text-xs font-bold text-[#4a4e4a]">复盘文章内容 (Markdown 或 纯文本)</label>
              <label className="inline-flex cursor-pointer items-center gap-1 text-xs font-semibold text-[#4a7c59] hover:underline">
                <Upload className="h-3.5 w-3.5" />
                上传 .md/.txt 文件
                <input type="file" accept=".md,.txt" onChange={handleFileUpload} className="hidden" />
              </label>
            </div>
            <textarea
              rows={12}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="在此粘贴复盘文章内容，或选择右上方样本载入/上传文件..."
              className="w-full rounded-md border border-[#c4c8bc]/60 bg-white p-3 font-mono text-xs leading-relaxed text-[#2e3230] outline-none focus:border-[#4a7c59]"
            />
          </div>

          {error && (
            <div className="rounded-md border border-[#b83230]/30 bg-[#b83230]/5 p-3 text-xs text-[#8f2927]">
              {error}
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-[#c4c8bc]/60 bg-white px-4 py-2 text-xs font-bold text-[#4a4e4a] hover:bg-[#eae6de]"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-md bg-[#4a7c59] px-5 py-2 text-xs font-bold text-white shadow-xs hover:bg-[#3b6447] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {loading ? 'AI 智能梳理中...' : 'AI 智能梳理并渲染'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
