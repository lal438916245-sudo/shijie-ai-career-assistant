import { useEffect, useState, type CSSProperties } from "react"
import { ArrowRight, ArrowUpRight, Compass, FileCheck2, FileSearch, RotateCcw, ShieldCheck, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { demo } from "@/data/demo"
import "./welcome.css"

type Props = { onEnter: (view: "overview" | "new") => void; hasDraft: boolean }
const milestones = [
  { x: 930, y: 557, delay: 2.42, name: "首次考核", state: "待复测", detail: "识别薄弱环节，进入针对性复测。" },
  { x: 1158, y: 389, delay: 3.24, name: "变式复测 01", state: "暂时通过", detail: "获得一道不同题面的正式通过证据。" },
  { x: 1248, y: 242, delay: 3.76, name: "变式复测 02", state: "已掌握", detail: "两道不同题面通过，满足掌握规则。" },
]
const route = "M1040 960 C940 946 745 908 783 855 C815 815 924 813 902 765 C888 731 735 719 742 667 C749 622 980 603 930 557 C898 527 891 502 926 478 C970 448 1178 431 1158 389 C1142 363 1106 357 1146 330 C1182 303 1268 292 1248 242 C1232 218 1219 215 1240 193 L1254 174"

export function Welcome({ onEnter, hasDraft }: Props) {
  const [panel, setPanel] = useState<"path" | "about" | null>(null)
  const [run, setRun] = useState(0)
  const [imageReady, setImageReady] = useState(false)
  const [imageFailed, setImageFailed] = useState(false)
  const [active, setActive] = useState<number | null>(null)
  const [reduced, setReduced] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches)
  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)")
    const update = () => setReduced(preference.matches)
    preference.addEventListener("change", update)
    return () => preference.removeEventListener("change", update)
  }, [])
  const restart = () => { setActive(null); setRun(previous => previous + 1) }
  return <div className="welcome-page">
    <a className="welcome-skip" href="#welcome-main">跳到主要内容</a>
    <header className="welcome-header"><a href="#welcome" className="welcome-brand" aria-label="拾阶 欢迎页"><span className="welcome-brand-compass"><Compass size={37} strokeWidth={1.25} /></span><span>拾阶<small className="welcome-brand-subtitle">AI 求职准备助手</small></span></a><nav aria-label="欢迎页导航"><button className="welcome-nav-link" onClick={() => setPanel("path")}>成长路径</button><button className="welcome-nav-link" onClick={() => setPanel("about")}>关于项目</button><Button variant="outline" className="welcome-enter" onClick={() => onEnter("overview")}>进入工作台 <ArrowUpRight size={16} /></Button></nav></header>

    <main id="welcome-main" className="welcome-main" tabIndex={-1}>
      <section className="welcome-copy" aria-labelledby="welcome-title"><p className="welcome-kicker">你的职业成长领航员</p><h1 id="welcome-title">让每一步成长，<br />都有据可循。</h1><p className="welcome-description">从岗位差距到能力验证，<br />让学习连接下一次机会。</p><div className="welcome-actions"><Button className="welcome-primary" onClick={() => onEnter("overview")}>查看完整案例 <ArrowRight size={19} /></Button><Button variant="outline" className="welcome-secondary" onClick={() => onEnter("new")}>开始动手体验</Button></div><p className="welcome-reassurance">先看完整案例，再亲手操作。案例不调用模型，个人体验由AI辅助生成。</p></section>

      <section className="welcome-visual" aria-label="成长航线：固定演示样例">
        <div className="welcome-art-caption"><i /><span>成长路径演示 · 固定样例</span><i /></div>
        <div className={`welcome-art ${imageReady || imageFailed ? "is-ready" : ""} ${imageFailed ? "art-unavailable" : ""}`} data-motion={reduced ? "reduced" : "standard"}>
          <img src="/art/growth-landscape-v1.png" width="1536" height="1024" className="welcome-landscape" alt="手绘职业探索山景：指南针、学习手册、通向山顶的路径与成长证据。" fetchPriority="high" decoding="async" draggable={false} onLoad={() => setImageReady(true)} onError={() => setImageFailed(true)} />
          <svg key={run} className="welcome-animation" viewBox="0 0 1536 1024" aria-hidden="true" preserveAspectRatio="xMidYMid meet">
            <defs><filter id="route-soft-shadow"><feDropShadow dx="0" dy="2" stdDeviation="2" floodColor="#765727" floodOpacity=".12" /></filter></defs>
            <path className="welcome-route-underlay" d={route} pathLength="100" fill="none" />
            <path className="welcome-route" d={route} pathLength="100" fill="none" filter="url(#route-soft-shadow)" />
            {milestones.map((point, i) => <g key={i} className={`welcome-milestone milestone-${i}`} style={{ "--node-delay": `${point.delay}s` } as CSSProperties}>
              <circle className="welcome-node-halo" cx={point.x} cy={point.y} r="23" />
              <circle className="welcome-node" cx={point.x} cy={point.y} r="12" />
              <circle className="welcome-node-core" cx={point.x} cy={point.y} r="4" />
              <text className="welcome-node-score" x={point.x + (i === 2 ? 38 : 33)} y={point.y + 9}>{demo.attempts[i].score}</text>
            </g>)}
            <g transform="translate(318 724) scale(1 .9)"><g className="welcome-compass-needle">
              <path d="M0 -114 L12 -13 L76 0 L13 12 L0 114 L-12 13 L-76 0 L-13 -12 Z" fill="#e5d7b7" stroke="#294d3f" strokeWidth="2" />
              <path d="M0 -114 L12 -13 L0 0 Z M0 0 L13 12 L0 114 L-12 13 Z M0 0 L-13 -12 L-76 0 Z" fill="#245c48" />
              <path d="M0 0 L12 -13 L76 0 L13 12 Z" fill="#b58c49" />
              <path d="M0 -114 L0 114 M-76 0 L76 0" fill="none" stroke="#355246" strokeWidth="1.3" />
            </g><circle r="14" fill="#c7a363" stroke="#2e493b" strokeWidth="3" /><circle r="6" fill="#f4e6c7" stroke="#735d32" strokeWidth="2" /></g>
          </svg>
          <div className="welcome-hotspots">{milestones.map((point, i) => <button key={i} className={`welcome-hotspot ${active === i ? "selected" : ""}`} style={{ left: `${point.x / 15.36}%`, top: `${point.y / 10.24}%` }} aria-label={`${point.name} ${demo.attempts[i].score} 分，${point.state}，查看说明`} aria-expanded={active === i} aria-controls="welcome-evidence-note" onClick={() => setActive(active === i ? null : i)}><span className="sr-only">查看{point.name}</span></button>)}</div>
          {imageFailed && <p className="welcome-art-error" role="status">插画暂时无法加载，仍可直接进入工作台体验。</p>}
          {active !== null && <div className="welcome-evidence-note" id="welcome-evidence-note" role="status"><span><strong>{milestones[active].name} · {demo.attempts[active].score} 分</strong><small>{milestones[active].state} · {milestones[active].detail}</small></span><button aria-label="关闭节点说明" onClick={() => setActive(null)}><X size={15} /></button></div>}
        </div>
        <div className="welcome-art-controls"><span>{reduced ? "已按系统偏好减少动态效果" : "每一次验证，都让方向更清晰"}</span><button onClick={restart} disabled={reduced || (!imageReady && !imageFailed)} aria-label="重播成长航线动画"><RotateCcw size={13} /> 重播成长路径</button></div>
      </section>
    </main>

    <section className="welcome-promises" aria-label="产品承诺"><div><FileSearch size={26} strokeWidth={1.2} /><span>演示数据有标识</span></div><div><ShieldCheck size={26} strokeWidth={1.2} /><span>能力结论可追溯</span></div><div><FileCheck2 size={26} strokeWidth={1.2} /><span>简历表达有边界</span></div></section>
    <footer className="welcome-footer"><span>拾阶 <i /> 让努力留下证据</span><button onClick={() => setPanel("about")}>两种入口 · 来源分别标注 <ArrowUpRight size={12} /></button></footer>

    <Dialog open={panel !== null} onOpenChange={open => { if (!open) setPanel(null) }}><DialogContent className="welcome-info-dialog"><DialogHeader><span className="welcome-dialog-icon"><Compass size={28} strokeWidth={1.5} /></span><DialogTitle>{panel === "path" ? "每一步，都连接下一份证据。" : "关于拾阶——AI 求职准备助手"}</DialogTitle><DialogDescription>{panel === "path" ? "从职业目标出发，让学习、验证与表达形成一条有来源的路径。" : "一个围绕岗位差距、针对性学习和能力验证的职业成长项目。"}</DialogDescription></DialogHeader>{panel === "path" ? <ol className="welcome-path-list">{[{ title: "明确目标，找到差距", detail: "把已有经历与目标岗位要求放在一起。" }, { title: "针对性学习", detail: "让每条学习任务都回应一个具体能力差距。" }, { title: "考核、复测与验证", detail: "通过不同题面的证据，判断能力是否得到提升。" }, { title: "形成有据表达", detail: "让能力陈述有依据，让经历保持真实。" }].map((item, i) => <li key={item.title}><span>0{i + 1}</span><div><strong>{item.title}</strong><p>{item.detail}</p></div></li>)}</ol> : <div className="welcome-about-copy"><p>查看完整案例：只读回放诊断、学习、考核、面试和简历优化；历史真实模型结果单独标注，浏览不产生调用。</p><p>开始动手体验：填写自己的资料，建立独立会话。点击生成后使用AI分析，原文与结果独立保存。学习资料当前重点覆盖数据方向，不影响其他岗位先完成诊断和简历优化。</p></div>}<Button className="welcome-dialog-cta" onClick={() => { setPanel(null); onEnter("overview") }}>查看完整案例 <ArrowRight size={15} /></Button></DialogContent></Dialog>
  </div>
}
