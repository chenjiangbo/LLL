'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  FileText,
  Film,
  Image as ImageIcon,
  Info,
  Layers3,
  Menu,
  MousePointer2,
  Play,
  Sparkles,
  X,
} from 'lucide-react';
import styles from './training.module.css';

type AssetKind = 'image' | 'video' | 'before-after' | 'process';

type TrainingPage = {
  number: string;
  eyebrow: string;
  title: string;
  subtitle?: string;
  kind: AssetKind;
  bullets?: string[];
  leftLabel?: string;
  rightLabel?: string;
  note?: string;
  prompt?: string;
  tags?: string[];
  speakerNotes: string;
  materialNotes: string;
};

const pages: TrainingPage[] = [
  {
    number: '01', eyebrow: 'AI 视觉内容生成与应用', title: '图片、视频与智能影像技术发展及应用实践', kind: 'image',
    subtitle: '陕西省再担保有限责任公司 · AI 应用专题交流', tags: ['TRAINING / 03', 'VISUAL AI'],
    speakerNotes: '前两次交流主要围绕大模型在文字处理、材料分析、数据处理和办公场景中的应用。这一次结合大家关注的方向，交流 AI 在图片、视频和智能影像方面的发展和应用。', materialNotes: '背景建议使用 8–12 秒高质量 AI 视频循环播放，静音；深色、克制、科技感。点击任意位置进入下一页。',
  },
  {
    number: '02', eyebrow: '能力地图', title: 'AI 视觉内容的主要生成方式', kind: 'process',
    leftLabel: '图片生成与处理', rightLabel: '视频生成与处理',
    bullets: ['文生图：文字 → 图片', '图生图 / 参考生图', '图片编辑与多图融合', '风格转换：写实、动漫、3D'],
    tags: ['TEXT → IMAGE', 'IMAGE → VIDEO'], speakerNotes: '这一页先把分类讲清楚。图片部分不只是文生图，还包括图生图、图片编辑、多图融合和风格转换；视频部分也已经从文字生成扩展到首尾帧、参考素材和视频编辑。', materialNotes: '两列能力地图；每个条目可带一句话定义，默认不展开。',
  },
  {
    number: '03', eyebrow: '发展现状', title: 'AI 视觉内容的发展现状', kind: 'process',
    bullets: ['生成质量持续提高', '从生成走向编辑', '从提示词走向参考素材', '视频时长与叙事能力提升', '从单一画面走向音画一体'],
    tags: ['QUALITY', 'CONTROL', 'AUDIO-VISUAL'], speakerNotes: '这一页讲的是能力发展阶段：生成质量提高、从生成走向编辑、从提示词走向参考素材、视频时长和连续叙事能力增强，以及音画一体化。', materialNotes: '五个卡片；数据和例子放到悬浮说明中。',
  },
  {
    number: '04', eyebrow: '场景 1 / 文生图', title: '用文字描述画面，由 AI 直接生成图片。', kind: 'image',
    leftLabel: '家庭装修构想', rightLabel: '旅行画面',
    note: '页面正式素材：豆包生成结果 / 即梦生成结果',
    prompt: '生成一张真实摄影风格的家庭客厅装修效果图。客厅约20平方米，适合一家四口、两个孩子日常使用。整体采用原木色和浅灰色，采光明亮，有充足收纳空间，温暖、整洁、实用。16:9，广角视角，完整展示客厅空间。',
    tags: ['豆包', '即梦'], speakerNotes: '建议以家庭装修构想为主，因为题材生活化，后续还可以继续用于迭代优化和首尾帧。旅行画面作为补充，展示氛围感。', materialNotes: '默认展示两张最终结果；Prompt 用按钮弹出；图片支持放大。',
  },
  {
    number: '05', eyebrow: '场景 2 / 迭代优化', title: '同一张图片，可以在原结果基础上继续优化。', kind: 'before-after',
    bullets: ['V1｜初始生成', 'V2｜调整家具与色调', 'V3｜增加儿童收纳', 'V4｜保持布局不变，改为夜景'],
    note: '页面正式素材：同一客厅的四轮连续编辑结果',
    tags: ['V1', 'V2', 'V3', 'V4'], speakerNotes: '重点不是重新生成四张不同图片，而是让大家看到 AI 可以基于当前结果继续修改，同时保持布局和主体关系。', materialNotes: '横向时间轴；点击某一版放大，悬停显示该轮修改说明。',
  },
  {
    number: '06', eyebrow: '场景 3 / 图片编辑', title: '更换背景、修复老照片、合成指定场景。', kind: 'before-after',
    bullets: ['更换背景：保留人物，修改环境', '老照片修复：修复、清晰化、自然上色', '合成场景：保留本人形象，生成合影效果'],
    note: '合影案例为 AI 合成效果，不代表真实场景。',
    tags: ['BEFORE', 'AFTER'], speakerNotes: '建议做三个小案例：孩子照片更换海边背景、老照片修复、与指定人物合影。合影必须明确说明是 AI 合成效果。', materialNotes: '每组案例使用原图 / 结果图对照；支持拖动分割；Prompt 用折叠按钮显示。',
  },
  {
    number: '07', eyebrow: '场景 4 / 风格转换', title: '同一人物 / 同一主体，生成不同视觉形式。', kind: 'image',
    bullets: ['二维动画风格', '3D 动画电影风格', '儿童绘本风格'],
    note: '页面正式素材：同一人物的三种风格转换结果',
    tags: ['2D', '3D', 'PICTURE BOOK'], speakerNotes: '建议使用孩子照片做风格转换，因为人物最容易看出主体是否保持。三种风格分别突出二维动画、3D 动画电影和儿童绘本质感。', materialNotes: '三联图；图片下方只显示风格名称；点击放大。',
  },
  {
    number: '08', eyebrow: '场景 5 / 文生视频', title: '一段完整的视频描述，可以直接生成高质量动态画面。', kind: 'video',
    leftLabel: '提示词摘要', rightLabel: '15 秒 AI 动漫视频',
    bullets: ['机甲战士', '能量启动', '多段镜头运动', '爆发式动作', '商业动漫感'],
    prompt: '在未来都市废墟的夜晚，一名银白与深蓝配色的机甲战士启动胸口核心能源，镜头从低机位快速推近，沿人物半圈环绕，最后释放大范围能量冲击。商业动漫预告片质感，动作流畅，15秒。',
    tags: ['即梦', '15 SEC', 'MUTED'], speakerNotes: '建议用机甲战士释放能量冲击作为示例，视觉冲击强、镜头变化丰富，且非真人题材对人物一致性要求相对低。', materialNotes: '视频必须提前准备，不现场等待生成；默认展示 Prompt 摘要，完整 Prompt 弹窗查看。',
  },
  {
    number: '09', eyebrow: '控制方式', title: '从“描述想要什么”逐步发展到“明确控制怎么生成”。', kind: 'process',
    bullets: ['仅靠文字：描述人物、场景、动作、镜头和声音', '加入参考素材：图片、角色、场景、视频、音频', '指定关键过程：首帧、尾帧、镜头运动、局部编辑'],
    tags: ['自由度', '可控度'], speakerNotes: '单纯依赖文字，自由度高但模型需要做更多判断。加入图片、视频、首尾帧后，生成过程更受控，更适合正式内容。', materialNotes: '三层递进结构，用箭头表达控制程度增强。',
  },
  {
    number: '10', eyebrow: '场景 6 / 图生视频', title: '图片确定画面，文字确定动作与镜头。', kind: 'video',
    leftLabel: '静态图片', rightLabel: '生成视频',
    note: '秋天的京都小巷，一家四口从石板路走过；人物行走、镜头跟拍、枫叶轻微摆动。',
    prompt: '镜头从一家四口身后缓慢跟拍，人物自然向前行走，孩子轻微摆动手臂，道路两侧的枫叶随微风轻轻晃动，少量落叶飘落。保持人物外貌、服装和环境不变，真实旅行纪录片风格。',
    tags: ['即梦', 'IMAGE → VIDEO'], speakerNotes: '直接复用场景 1 的京都旅行画面。图片确定画面，文字补充动作和镜头，重点观察人物、服装和环境是否保持。', materialNotes: '左右分栏；左图可放大，右侧视频静音循环 6–8 秒。',
  },
  {
    number: '11', eyebrow: '场景 7 / 首尾帧', title: '让 AI 生成从首帧到尾帧之间的自然变化。', kind: 'video',
    leftLabel: '首帧 · 白天客厅', rightLabel: '尾帧 · 夜晚客厅',
    note: '房间结构、家具位置和镜头机位保持稳定，时间从下午逐渐过渡到夜晚。',
    tags: ['START FRAME', 'END FRAME', '6–8 SEC'], speakerNotes: '首帧使用白天客厅，尾帧使用夜景客厅。展示时间变化、窗外变暗、城市灯光亮起和室内暖光开启的连续过程。', materialNotes: '首帧、过程、尾帧三段式；两张关键帧可放大，中间视频静音循环。',
  },
  {
    number: '12', eyebrow: '场景 8 / 多素材参考', title: '多个素材共同参与，生成统一的视频结果。', kind: 'video',
    bullets: ['产品图：一只保温杯', '环境图：湖边露营场景', '参考视频：围绕产品缓慢环绕的镜头运动'],
    note: '以产品图为主体，参考环境图与运镜视频，生成 8–10 秒商业产品广告。',
    tags: ['产品', '环境', '运镜', '即梦'], speakerNotes: '用保温杯广告讲清素材驱动：产品图锁定主体，环境图确定场景，参考视频提供镜头运动。', materialNotes: '左侧展示三个输入素材缩略图，右侧播放最终视频，中间用流程线连接。',
  },
  {
    number: '13', eyebrow: '技术趋势', title: 'AI 视频技术的发展方向', kind: 'process',
    bullets: ['更长：更长时长与连续叙事', '更稳：人物、场景和动作一致性', '更可控：图片、视频、音频、首尾帧', '音画一体：对白、音效与画面整合'],
    tags: ['LONGER', 'STABLE', 'CONTROLLED', 'AUDIO-VISUAL'], speakerNotes: '结合具体例子讲更长、更稳、更可控和音画一体。不要只讲抽象趋势，重点说明视频时长、主体一致性、多种参考方式和声音整合。', materialNotes: '四张卡片，每张卡片提供一个简短例子按钮。',
  },
  {
    number: '14', eyebrow: '产业化与商业化', title: 'AI 视觉内容正在进入真实生产链条。', kind: 'image',
    leftLabel: '专业影像', rightLabel: 'AI 动漫与短内容',
    bullets: ['广告与品牌视频', 'MV、宣传片、影视前后期', '个人及小团队即可生产', '平台分发、付费、广告与流量分成'],
    tags: ['PRODUCTION', 'DISTRIBUTION'], speakerNotes: '商业化大致有两条路径：专业影像，以及 AI 动漫和短内容。前者通常是传统拍摄与 AI 生成结合，后者团队更轻、试错成本更低。', materialNotes: '左右两栏，每栏一张代表性图片，不堆叠案例。',
  },
  {
    number: '15', eyebrow: 'AI 漫剧', title: '生产方式的变化', kind: 'process',
    bullets: ['故事 / 剧本', '角色设定', '分镜与关键画面', '视频生成', '声音与成片'],
    note: '一个小团队能够覆盖过去需要多个专业岗位完成的环节。',
    tags: ['STORY', 'CHARACTER', 'STORYBOARD', 'VIDEO', 'SOUND'], speakerNotes: 'AI 漫剧仍然需要故事、人物、分镜、画面、声音和成片。真正的变化是大量原来依赖人工绘制、动画制作或实拍的环节现在可以由 AI 完成。', materialNotes: '纵向流程图；每个节点配简洁图标，右侧放结论。',
  },
];

function AssetCanvas({ page, onOpen, comparePosition, onCompareChange }: { page: TrainingPage; onOpen: () => void; comparePosition: number; onCompareChange: (value: number) => void }) {
  if (page.kind === 'process') {
    return (
      <div className={styles.processCanvas}>
        {(page.bullets ?? []).map((item, index) => (
          <div className={styles.processStep} key={item}>
            <span>{String(index + 1).padStart(2, '0')}</span><strong>{item}</strong>
            {index < (page.bullets?.length ?? 0) - 1 && <ArrowRight size={16} />}
          </div>
        ))}
      </div>
    );
  }

  if (page.kind === 'before-after') {
    return (
      <div className={styles.comparisonGrid}>
        {(page.bullets ?? ['Before', 'After']).map((label, index) => (
          <div className={`${styles.assetCard} ${styles.comparisonCard}`} key={label}>
            <button onClick={onOpen} type="button">
              <div className={styles.compareVisual}>
                <div className={styles.assetVisual} style={{ ['--tone' as string]: `${index * 17 + 18}%` }}><Layers3 size={24} /></div>
                <div className={styles.compareAfter} style={{ width: `${comparePosition}%` }}><div className={styles.assetVisual} style={{ ['--tone' as string]: `${index * 17 + 45}%` }}><Sparkles size={24} /></div></div>
                <div className={styles.compareLine} style={{ left: `${comparePosition}%` }} />
              </div>
            </button>
            <span>{label}</span>
          </div>
        ))}
        <label className={styles.compareControl}>拖动分割查看 <input aria-label="调整 Before After 分割位置" type="range" min="8" max="92" value={comparePosition} onChange={(event) => onCompareChange(Number(event.target.value))} /></label>
      </div>
    );
  }

  const labels = [page.leftLabel ?? '输入素材', page.rightLabel ?? (page.kind === 'video' ? '视频结果' : '视觉结果')];
  return (
    <div className={`${styles.mediaCanvas} ${page.kind === 'video' ? styles.videoCanvas : ''}`}>
      {labels.map((label, index) => (
        <button className={styles.assetCard} onClick={onOpen} key={label} type="button">
          <div className={styles.assetVisual} style={{ ['--tone' as string]: `${index * 28 + 16}%` }}>
            {page.kind === 'video' ? (index === 1 ? <Play size={30} fill="currentColor" /> : <ImageIcon size={28} />) : <Sparkles size={28} />}
            <small>待置入正式素材</small>
          </div>
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
}

export default function TrainingPageView() {
  const [current, setCurrent] = useState(0);
  const [showNotes, setShowNotes] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [comparePosition, setComparePosition] = useState(50);
  const page = pages[current];

  const go = (next: number) => setCurrent(Math.max(0, Math.min(pages.length - 1, next)));
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'ArrowRight' || event.key === ' ') { event.preventDefault(); go(current + 1); }
      if (event.key === 'ArrowLeft') { event.preventDefault(); go(current - 1); }
      if (event.key === 'Escape') { setExpanded(false); setShowPrompt(false); setShowNotes(false); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [current]);

  const progress = useMemo(() => `${((current + 1) / pages.length) * 100}%`, [current]);

  return (
    <main className={styles.shell}>
      <div className={styles.ambient} />
      <header className={styles.topbar}>
        <div className={styles.brand}><span className={styles.brandMark}>✦</span><span>陕再担保 · AI 视觉专题交流</span></div>
        <div className={styles.topActions}>
          <span className={styles.counter}>{page.number} / 15</span>
          <button className={styles.iconButton} onClick={() => setShowNotes(true)} type="button" title="打开讲解备注"><FileText size={17} /></button>
          <button className={styles.iconButton} onClick={() => setShowMenu((value) => !value)} type="button" title="打开页面目录"><Menu size={17} /></button>
        </div>
      </header>

      <div className={styles.progress}><span style={{ width: progress }} /></div>

      <section className={styles.stage} onClick={() => { if (current === 0) go(1); }}>
        <div className={styles.pageIntro}>
          <div className={styles.pageNo}>{page.number}</div>
          <div>
            <p className={styles.eyebrow}>{page.eyebrow}</p>
            <h1>{page.title}</h1>
            {page.subtitle && <p className={styles.subtitle}>{page.subtitle}</p>}
          </div>
        </div>

        <div className={styles.contentGrid}>
          <div className={styles.textPanel}>
            {page.bullets && page.kind !== 'process' && (
              <div className={styles.bulletList}>{page.bullets.map((item) => <div key={item}><span />{item}</div>)}</div>
            )}
            {page.kind === 'process' && <p className={styles.lead}>视觉内容生成正在从单一生成，走向更高质量、更强控制、更完整的内容生产流程。</p>}
            {page.note && <div className={styles.note}><Info size={16} /><span>{page.note}</span></div>}
            <div className={styles.metaRow}>{page.tags?.map((tag) => <span key={tag}>{tag}</span>)}</div>
            <div className={styles.actionRow}>
              {page.prompt && <button className={styles.secondaryButton} onClick={() => setShowPrompt(true)} type="button"><FileText size={15} /> 查看完整提示词</button>}
              <span className={styles.hint}><MousePointer2 size={14} /> 点击素材可放大</span>
            </div>
          </div>
          <div className={styles.visualPanel}>
            <AssetCanvas page={page} onOpen={() => setExpanded(true)} comparePosition={comparePosition} onCompareChange={setComparePosition} />
            <div className={styles.visualFooter}><span><CircleHelp size={14} /> 正式素材待置入</span><span>{page.kind === 'video' ? <Film size={14} /> : <ImageIcon size={14} />} {page.kind === 'video' ? '视频演示位' : '图片演示位'}</span></div>
          </div>
        </div>

        <div className={styles.navigation}>
          <button className={styles.navButton} disabled={current === 0} onClick={() => go(current - 1)} type="button"><ChevronLeft size={18} /> 上一页</button>
          <div className={styles.dots}>{pages.map((item, index) => <button aria-label={`第 ${index + 1} 页`} className={index === current ? styles.activeDot : ''} key={item.number} onClick={() => go(index)} type="button" />)}</div>
          <button className={styles.navButton} disabled={current === pages.length - 1} onClick={() => go(current + 1)} type="button">下一页 <ChevronRight size={18} /></button>
        </div>
      </section>

      {showMenu && <aside className={styles.menu}><div className={styles.menuHeader}><strong>页面目录</strong><button onClick={() => setShowMenu(false)} type="button"><X size={16} /></button></div>{pages.map((item, index) => <button className={index === current ? styles.menuActive : ''} key={item.number} onClick={() => { go(index); setShowMenu(false); }} type="button"><span>{item.number}</span>{item.eyebrow}</button>)}</aside>}

      {(expanded || showPrompt || showNotes) && <div className={styles.overlay} onClick={() => { setExpanded(false); setShowPrompt(false); setShowNotes(false); }}>
        <div className={styles.modal} onClick={(event) => event.stopPropagation()}>
          <button className={styles.modalClose} onClick={() => { setExpanded(false); setShowPrompt(false); setShowNotes(false); }} type="button"><X size={18} /></button>
          {expanded && <><p className={styles.eyebrow}>素材预览</p><h2>{page.title}</h2><div className={`${styles.assetVisual} ${styles.largeVisual}`}><Sparkles size={42} /><span>正式图片 / 视频素材待置入</span></div><p className={styles.modalCopy}>当前页面的交互和版式已就绪，替换正式素材后即可用于培训演示。</p></>}
          {showPrompt && <><p className={styles.eyebrow}>生成说明</p><h2>完整提示词</h2><p className={styles.prompt}>{page.prompt}</p></>}
          {showNotes && <><p className={styles.eyebrow}>Presenter Mode · {page.number}</p><h2>讲解与演示提示</h2><p className={styles.modalCopy}>{page.speakerNotes}</p><div className={styles.presenterBlock}><strong>素材与交互</strong><p>{page.materialNotes}</p></div><div className={styles.note}><Info size={16} /><span>按 ← / → 翻页，按 Esc 关闭当前面板。</span></div></>}
        </div>
      </div>}
    </main>
  );
}
