import { ArrowRight, ArrowUpRight, BookOpen, BriefcaseBusiness, Check, FileCheck2, GitBranch, Link2, Plus, ShieldCheck, Target, TrendingUp } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { demo } from "@/data/demo"

export type EvidenceTarget = number | "all" | "resume"
export type PreviewSession = { kind: string; id: string; role: string; days: number; status: string }

type Props = { onNew: () => void; onDiagnosis: () => void; onPlan: () => void; onExam: () => void; onGrowth: () => void; onScenario: () => void; onResume: () => void; onEvidence: (target: EvidenceTarget) => void; onAbout: () => void; session: PreviewSession | null }

function GrowthChart({ onSelect }: { onSelect: (index: number) => void }) {
  // Same linear scale as the labelled ticks: 45 at y=180, 90 at y=60.
  const positions = demo.attempts.map((attempt, i) => ({ x: [68, 304, 540][i], y: 180 - (attempt.score - 45) * 120 / 45 }))
  return <svg className="growth-chart" viewBox="0 0 608 232" role="group" aria-label="固定演示成长曲线：首次 55 分、复测 72 分、再次复测 82 分">
    <defs><linearGradient id="growthFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#879564" stopOpacity=".19" /><stop offset="100%" stopColor="#879564" stopOpacity=".01" /></linearGradient></defs>
    {[60, 100, 140, 180].map((y, i) => <g key={y}><line x1="34" x2="580" y1={y} y2={y} stroke="#e4e1cf" strokeDasharray="3 5" /><text x="8" y={y + 4} className="chart-axis">{90 - i * 15}</text></g>)}
    <path d="M68 153.333 L304 108 L540 81.333 L540 187 L68 187 Z" fill="url(#growthFill)" />
    <path d="M68 153.333 L304 108 L540 81.333" fill="none" stroke="#4d7651" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    {positions.map((p, i) => <g key={p.x} role="button" tabIndex={0} className="chart-point" aria-label={`查看${demo.attempts[i].label} ${demo.attempts[i].score} 分的证据`} onClick={() => onSelect(i)} onKeyDown={event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); onSelect(i) } }}>
      <rect x={p.x - 38} y="14" width="76" height="210" fill="transparent" />
      <circle cx={p.x} cy={p.y} r="18" fill="transparent" /><circle cx={p.x} cy={p.y} r="8" fill="#fffdf8" stroke="#4d7651" strokeWidth="2.5" />
      <circle cx={p.x} cy={p.y} r="3" fill="#a99052" />
      <text x={p.x} y={p.y - 23} textAnchor="middle" className="chart-score">{demo.attempts[i].score}<tspan className="chart-score-unit"> 分</tspan></text>
      <text x={p.x} y="216" textAnchor="middle" className="chart-label">{demo.attempts[i].label}</text>
    </g>)}
  </svg>
}

export function Overview({ onNew, onDiagnosis, onPlan, onExam, onGrowth, onScenario, onResume, onEvidence, onAbout, session }: Props) {
  const metrics = [
    { label: "初始岗位匹配", value: String(demo.initialMatch), unit: "%", note: "来自岗位诊断", icon: Target, color: "sand" },
    { label: "最新正式考核", value: String(demo.attempts.at(-1)?.score), unit: "/ 100", note: `+${demo.attempts.at(-1)!.score - demo.attempts[0].score} 分 · 相比首次`, icon: TrendingUp, color: "green" },
    { label: "不同题面通过", value: String(demo.passedFaces).padStart(2, "0"), unit: "道", note: "满足本次掌握规则", icon: FileCheck2, color: "olive" },
    { label: "可追溯评测", value: String(demo.attempts.length).padStart(2, "0"), unit: "次", note: "每次都有评分依据", icon: GitBranch, color: "sage" },
  ]
  const journey = [
    { label: "识别岗位差距", detail: "实时数据链路经验不足", agent: "A" },
    { label: "针对性学习", detail: "构建可恢复的实时聚合链路", agent: "B" },
    { label: "考核与变式复测", detail: "55 → 72 → 82，两道变式题通过", agent: "C" },
    { label: "验证场景迁移", detail: "岗位场景追问 · 模型评估证据", agent: "E" },
    { label: "形成简历建议", detail: "一条有据表达，一条夸大声明被拦截", agent: "D" },
  ]
  return <div className="page-enter overview-page">
    <section className="page-intro">
      <div><div className="eyebrow"><span /> CAREER GROWTH WORKSPACE</div><h1>让每一步成长，<span>都有据可循。</span></h1><p>从岗位差距到能力验证，把进步积累成下一份机会的底气。</p></div>
      <Button onClick={onNew} className="primary-cta"><Plus size={17} /> 新建成长计划 <ArrowUpRight size={17} /></Button>
    </section>

    {session && <div className="local-session-notice"><span className="notice-icon"><Check size={17} /></span><div><strong>{session.role} · 体验会话已创建</strong><p>{session.days} 天成长方向已保存到此浏览器，尚未进行岗位诊断。下方仍是固定演示故事。</p></div><Button variant="ghost" size="sm" onClick={onNew}>继续查看 <ArrowRight size={14} /></Button></div>}

    <div className="scenario-strip"><div className="scenario-main"><span className="role-icon"><BriefcaseBusiness size={19} /></span><div><span className="micro-label">正在查看的演示目标</span><strong>{demo.role}<span className="role-direction">{demo.direction}</span></strong></div></div><div className="scenario-aside"><Badge variant="secondary" className="demo-badge">固定演示样例</Badge><button className="text-link" onClick={onAbout}>数据说明 <ArrowUpRight size={13} /></button></div></div>

    <div className="metric-grid">{metrics.map(metric => <Card className="metric-card" key={metric.label}><div className="metric-top"><span>{metric.label}</span><span className={`metric-icon ${metric.color}`}><metric.icon size={17} /></span></div><div className="metric-number">{metric.value}<span>{metric.unit}</span></div><div className={metric.color === "green" ? "metric-note positive" : "metric-note"}>{metric.color === "green" && <TrendingUp size={12} />}{metric.note}</div></Card>)}</div>

    <div className="bento-grid">
      <Card className="growth-card">
        <div className="section-heading"><div><div className="eyebrow small">GROWTH EVIDENCE</div><h2>进步，看得见也查得到</h2></div><Badge className="mastery-badge"><span className="status-dot" /> 已掌握</Badge></div>
        <Tabs defaultValue="scores" className="chart-tabs"><TabsList><TabsTrigger value="scores">得分变化</TabsTrigger><TabsTrigger value="rules">判定依据</TabsTrigger></TabsList>
          <TabsContent value="scores"><GrowthChart onSelect={onEvidence} /><div className="chart-hint"><span className="tiny-chart-line" /> 同知识点 · 不同题面<span className="chart-interaction">点击节点查看证据 <ArrowUpRight size={12} /></span></div></TabsContent>
          <TabsContent value="rules"><div className="rule-states">{demo.attempts.map((attempt, i) => <button onClick={() => onEvidence(i)} key={attempt.id}><span className="rule-order">0{i + 1}</span><div><strong>{attempt.state}</strong><p>{i === 0 ? "正式考核低于及格线，进入复测。" : i === 1 ? "一道不同题面的正式通过证据。" : "两道不同题面通过，满足掌握规则。"}</p></div><ArrowUpRight size={16} /></button>)}</div></TabsContent>
        </Tabs>
        <div className="chart-footer"><ShieldCheck size={15} /><span>两道不同题面的正式通过，才让“已掌握”成立。</span><button className="growth-status-link" onClick={onGrowth}>查看成长状态 <ArrowUpRight size={12}/></button></div>
      </Card>

      <Card className="journey-card"><div className="section-heading"><div><div className="eyebrow small">CONNECTED, NOT ISOLATED</div><h2>一条完整的成长证据链</h2></div><Link2 size={19} className="muted-icon" /></div><div className="journey-list">{journey.map((step, index) => <button className="journey-step" key={step.agent} onClick={() => index === 0 ? onDiagnosis() : index === 1 ? onPlan() : index === 2 ? onExam() : index === 3 ? onScenario() : onResume()}><span className="journey-check"><Check size={12} /></span><div><strong>{step.label}</strong><p>{step.detail}</p></div><span className="agent-letter">{step.agent}</span></button>)}</div><Button variant="ghost" className="full-evidence" onClick={() => onEvidence("all")}>查看完整证据链 <ArrowRight size={14} /></Button></Card>
    </div>

    <div className="bottom-grid"><Card className="learning-card"><div className="learning-icon"><BookOpen size={21} /></div><div className="learning-copy"><div className="micro-label">这条证据链中的学习任务 <span>DAY 02</span></div><h3>{demo.task.title}</h3><p>{demo.task.detail}</p></div><Button variant="ghost" size="icon" aria-label="查看对应学习计划" onClick={onPlan}><ArrowUpRight size={20} /></Button></Card><div className="resume-callout"><span className="callout-circle"><FileCheck2 size={24} /></span><div><span className="eyebrow small">EVIDENCE TO OPPORTUNITY</span><h3>把验证过的能力，写进下一次机会。</h3><p>表达更有底气，经历始终真实。</p><button onClick={onResume}>查看演示简历建议 <ArrowRight size={14} /></button></div></div></div>
    <footer className="page-footer"><span>CAREER-PILOT <i /> 让努力留下证据</span><span>以上为预存演示数据，并非本轮实时模型结果</span></footer>
  </div>
}
