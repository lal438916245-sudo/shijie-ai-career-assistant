import { useState } from "react"
import { ArrowDown, ArrowRight, ArrowUpRight, BookOpen, BriefcaseBusiness, Check, ChevronDown, FileText, Link2, ShieldCheck, Target } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ReplayBanner, ReplayFooter } from "@/components/ReplayContext"
import { demo, replay } from "@/data/demo"
import type { EvidenceTarget } from "@/components/Overview"

type Props = { onPlan: () => void; onEvidence: (target: EvidenceTarget) => void }

export function Diagnosis({ onPlan, onEvidence }: Props) {
  const [expanded, setExpanded] = useState<string | null>(replay.gaps[0].gap_id)
  const highPriority = replay.gaps.filter(gap => gap.priority === "high").length
  return <div className="page-enter career-page diagnosis-page">
    <section className="page-intro"><div><div className="eyebrow"><span /> UNDERSTAND YOUR NEXT STEP</div><h1>先看清差距，<span>再找到成长的方向。</span></h1><p>把已有经历与岗位期待放在一起，让下一步学习有的放矢。</p></div><Button className="primary-cta" onClick={onPlan}>查看对应学习计划 <ArrowRight size={15} /></Button></section>
    <ReplayBanner />

    <div className="diagnosis-summary-grid"><Card className="match-card"><div className="career-card-label"><Target size={15} /> 初始岗位匹配</div><div className="match-ring" role="img" aria-label={`固定样例的初始岗位匹配度为 ${demo.initialMatch} 分，满分 100`}><svg viewBox="0 0 180 180" aria-hidden="true"><circle cx="90" cy="90" r="73" className="match-ring-track" /><circle cx="90" cy="90" r="73" className="match-ring-value" pathLength="100" strokeDasharray="100" strokeDashoffset={100 - demo.initialMatch} transform="rotate(-90 90 90)" /></svg><div><strong>{demo.initialMatch}<span>/ 100</span></strong><small>演示案例 · 初始诊断</small></div></div><p>匹配度是一份起点，<br />还需要具体证据理解能力差距。</p></Card>
      <Card className="diagnosis-insight"><div className="career-card-label"><BriefcaseBusiness size={16} /> 目标岗位画像</div><h2>{demo.role}<span>{demo.direction}</span></h2><p className="diagnosis-role-copy">{replay.inputs.jd_summary}</p><div className="comparison-summary"><div><span className="comparison-icon"><Check size={15} /></span><div><strong>已有的起点</strong><p>{replay.inputs.resume_summary}</p></div></div><div><span className="comparison-icon gold"><Target size={15} /></span><div><strong>这次优先补齐</strong><p>{replay.gaps[0].title}</p><small>从窗口、状态与容错的可核验证据开始。</small></div></div></div><div className="diagnosis-facts"><div><strong>{String(replay.gaps.length).padStart(2, "0")}</strong><span>项识别差距</span></div><div><strong>{String(highPriority).padStart(2, "0")}</strong><span>项高优先级</span></div><div><strong>{String(replay.learning_tasks.length).padStart(2, "0")}</strong><span>项关联任务</span></div></div></Card></div>

    <Tabs defaultValue="gaps" className="career-tabs"><div className="career-section-bar"><TabsList><TabsTrigger value="gaps">岗位差距 <span>{replay.gaps.length}</span></TabsTrigger><TabsTrigger value="inputs">输入对照</TabsTrigger></TabsList><span><ShieldCheck size={13} /> 结论与来源一起查看</span></div>
      <TabsContent value="gaps"><div className="diagnosis-detail-grid"><div>{replay.gaps.map((gap, index) => { const open = expanded === gap.gap_id; const tasks = replay.learning_tasks.filter(task => task.gap_ids.includes(gap.gap_id)); return <Card className="gap-card" key={gap.gap_id}><button className="gap-card-toggle" aria-expanded={open} aria-controls={`gap-detail-${index}`} onClick={() => setExpanded(open ? null : gap.gap_id)}><span className="career-order">0{index + 1}</span><span><strong>{gap.title}</strong><small>{tasks.length} 项学习任务已关联此差距</small></span><Badge variant="secondary" className="priority-badge">{gap.priority === "high" ? "优先补齐" : "待补齐"}</Badge><ChevronDown size={17} className={open ? "is-expanded" : ""} /></button>{open && <div className="gap-card-body" id={`gap-detail-${index}`}><p className="gap-description">{gap.description}</p><div className="gap-evidence"><span><FileText size={14} /> 判断依据</span><p>{gap.evidence}</p></div><div className="gap-learning-link"><span className="learning-icon"><BookOpen size={19} /></span><div><span className="micro-label">回应这个差距的学习任务</span><strong>{tasks[0]?.title ?? "该快照未提供对应任务"}</strong></div><Button variant="ghost" size="icon" onClick={onPlan} aria-label="查看对应学习任务"><ArrowUpRight size={19} /></Button></div><div className="gap-card-footer"><span><Link2 size={12} /> 来源已关联</span><button onClick={() => onEvidence("all")}>查看证据关联 <ArrowUpRight size={13} /></button></div></div>}</Card>})}</div>
        <aside className="diagnosis-next"><span className="eyebrow small">FROM INSIGHT TO ACTION</span><h3>把差距，变成可以走的路。</h3><ol><li><span>01</span><div><strong>明确缺少的证据</strong><p>从初始诊断中定位值得补齐的能力。</p></div></li><li><span>02</span><div><strong>选择对应学习任务</strong><p>让学习内容直接回应岗位差距。</p></div></li><li><span>03</span><div><strong>通过考核验证成长</strong><p>在不同题面中积累正式证据。</p></div></li></ol><Button variant="outline" onClick={onPlan}>去看演示学习计划 <ArrowRight size={14} /></Button></aside></div></TabsContent>
      <TabsContent value="inputs"><div className="input-comparison-grid"><Card className="input-summary-card"><div className="career-card-label"><FileText size={16} /> 经历摘要</div><h3>已经走过的路</h3><p>{replay.inputs.resume_summary}</p><div className="topic-chips"><span>批处理</span><span>SQL</span><span>数据仓库</span></div><small>来自固定演示资料的摘要，不是你的浏览器草稿。</small></Card><div className="comparison-connector"><ArrowRight size={21} /></div><Card className="input-summary-card"><div className="career-card-label"><Target size={16} /> 岗位要求摘要</div><h3>接下来想去的地方</h3><p>{replay.inputs.jd_summary}</p><div className="topic-chips"><span>流式计算</span><span>状态管理</span><span>窗口与容错</span></div><small>对照这份要求，查看已识别的实时链路差距。</small></Card></div></TabsContent>
    </Tabs>
    <div className="career-bottom-note"><ArrowDown size={16} /><span>诊断的下一步，是一项有来源的学习任务。</span><button onClick={onPlan}>查看学习计划 <ArrowRight size={14} /></button></div>
    <ReplayFooter />
  </div>
}
