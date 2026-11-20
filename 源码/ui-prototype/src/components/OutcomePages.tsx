import { usePendingEdits } from "@/components/WorkspaceQuality"
import { useRef, useState } from "react"
import { ArrowLeft, ArrowRight, ArrowUpRight, BookOpen, Check, ChevronDown, Copy, FileCheck2, Fingerprint, GitBranch, Layers3, Link2, MessageSquareText, PenLine, Play, ShieldCheck, ShieldX, Target, TrendingUp } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ReplayBanner, ReplayFooter } from "@/components/ReplayContext"
import { demo, replay } from "@/data/demo"
import { assessmentForRound } from "@/lib/assessment.mjs"
import { canCopyDemoSuggestion, resolveEvidenceRefs, scenarioRecord } from "@/lib/outcomes.mjs"
import type { EvidenceTarget } from "@/components/Overview"
import "./outcomes.css"

type OutcomeView="growth"|"scenario"|"resume"
type Destination=OutcomeView|"overview"|"diagnosis"|"plan"|"exam"|"retest"
type Props={onNavigate:(view:Destination)=>void;onEvidence:(target:EvidenceTarget)=>void}
type SnapshotRound={question:(typeof replay.questions)[number];attempt:(typeof replay.attempts)[number];state:(typeof replay.mastery_states)[number];task:(typeof replay.learning_tasks)[number]}
const kindLabels:Record<string,string>={gap:"岗位差距",task:"学习任务",attempt:"评分记录",interview:"场景验证"}

function EvidenceReferences({refs,onNavigate,onEvidence}:{refs:{kind:string;ref_id:string}[]}&Props) {
  const resolved=resolveEvidenceRefs(replay,refs)
  const open=(ref:(typeof resolved)[number])=>{
    if(ref.kind === "attempt"){const index=demo.attempts.findIndex(item=>String(item.id)===ref.ref_id);if(index>=0)onEvidence(index)}
    else onNavigate(ref.kind === "gap" ? "diagnosis" : ref.kind === "task" ? "plan" : "scenario")
  }
  return <div className="outcome-ref-list">{resolved.map(ref=><button key={`${ref.kind}:${ref.ref_id}`} disabled={!ref.found} onClick={()=>open(ref)}><span><Link2 size={14}/></span><div><small>{kindLabels[ref.kind]??"未知来源"}</small><strong>{ref.label}</strong><code>{ref.ref_id}</code></div><ArrowUpRight size={14}/></button>)}</div>
}
function OutcomeIntro({eyebrow,title,description,back,onBack}:{eyebrow:string;title:React.ReactNode;description:string;back:string;onBack:()=>void}) {
  return <section className="page-intro"><div><div className="eyebrow"><span/>{eyebrow}</div><h1>{title}</h1><p>{description}</p></div><Button variant="outline" className="career-back-button" onClick={onBack}><ArrowLeft size={14}/>{back}</Button></section>
}
function RecordedEvent({name}:{name:string}) {
  const event=replay.tool_events.find(item=>item.tool_name===name)
  if(!event)return null
  return <details className="outcome-record"><summary><Fingerprint size={15}/><span>查看快照中的关联记录</span><ChevronDown size={13}/></summary><div><strong>{event.label}</strong><code>{event.event_id} · {event.tool_name}</code><p>仅展示已收录记录，本轮没有执行该操作。</p></div></details>
}

function GrowthPage({onNavigate,onEvidence}:Props) {
  const [round,setRound]=useState(2)
  const {question,attempt,state}=assessmentForRound(replay,round) as SnapshotRound
  const index=demo.attempts.findIndex(item=>item.id===attempt.attempt_id)
  const passed=replay.attempts.filter(item=>state.attempt_ids.includes(item.attempt_id)&&item.status==="completed")
  const distinct=new Set(passed.map(item=>replay.questions.find(q=>q.task_id===item.task_id)?.question_fingerprint)).size
  const eligible=["provisional_pass","mastered"].includes(state.state)
  return <div className="page-enter career-page outcome-page growth-state-page"><OutcomeIntro eyebrow="PROGRESS WITH A TRACE" title={<>让进步，<span>留下可以追溯的轨迹。</span></>} description="沿着三次不同题面的考核，查看样例的能力状态如何变化。" back="返回成长概览" onBack={()=>onNavigate("overview")}/><ReplayBanner/>
    <div className="outcome-metrics"><Card><span><TrendingUp size={15}/>当前查看节点的成绩</span><strong>{attempt.score}<small>/ 100</small></strong><p>{demo.attempts[index].label} · 固定样例</p></Card><Card><span><Layers3 size={15}/>此节点的不同题面通过</span><strong>{String(distinct).padStart(2,"0")}<small>道</small></strong><p>读取已有通过记录，按题面区分</p></Card><Card><span><GitBranch size={15}/>关联考核记录</span><strong>{String(state.attempt_ids.length).padStart(2,"0")}<small>次</small></strong><p>每一次均能追到题目与评分</p></Card></div>
    <div className="outcome-grid"><section><Card className="outcome-card state-card"><div className="outcome-card-heading"><div><span className="micro-label">同一岗位差距 · 历史状态回放</span><h2>{demo.gap.title}</h2></div><Badge variant="secondary">{demo.attempts[index].state}</Badge></div><div className="state-steps" aria-label="历史能力状态">{demo.attempts.map((item,i)=><button key={item.id} aria-pressed={round===i} className={round===i?"selected":""} onClick={()=>setRound(i)}><span>0{i+1}</span><strong>{item.state}</strong><small>{item.label}</small><b>{item.score}<i>分</i></b></button>)}</div><p className="outcome-history-note">切换历史节点只改变当前展示，不修改案例最新状态，也不受每日任务打卡影响。</p><div className={`state-explanation ${round===0?"needs-retest":""}`}><ShieldCheck size={21}/><div><strong>{state.explanation}</strong><p>{attempt.feedback}</p></div></div><dl className="outcome-identity"><div><dt>当前考核侧重</dt><dd>{question.focus}</dd></div><div><dt>状态规则</dt><dd><code>{state.rule_code}</code></dd></div><div><dt>评分与题目</dt><dd>attempt #{attempt.attempt_id} · question #{question.task_id}</dd></div></dl><div className="outcome-actions"><Button variant="outline" onClick={()=>onEvidence(index)}>查看本次评分证据 <ArrowUpRight size={13}/></Button><Button onClick={()=>onNavigate(eligible?"scenario":"retest")}>{eligible?"进入岗位场景验证":"继续变式复测"}<ArrowRight size={14}/></Button></div></Card><RecordedEvent name="mastery_policy.project"/>
      <Card className="outcome-card outcome-next-card"><span className="aside-icon"><BookOpen size={20}/></span><div><h3>完成学习，与验证能力，各有记录。</h3><p>每日安排中的“已完成”表示你执行了任务；这里的状态来自固定考核证据，两类记录独立。</p></div><button onClick={()=>onNavigate("plan")}>管理学习安排 <ArrowUpRight size={14}/></button></Card></section>
      <aside className="outcome-sidebar"><Card className="outcome-guide"><span className="aside-icon"><Target size={22}/></span><h3>从会回答，<br/>到会解决问题。</h3><p>该样例最新状态为“{demo.attempts.at(-1)?.state}”。下一步通过岗位场景，观察知识之间的联系与迁移。</p><ol><li><Check size={13}/>首次考核暴露薄弱点</li><li><Check size={13}/>两道不同题面的通过记录</li><li><MessageSquareText size={13}/>岗位场景验证</li><li><FileCheck2 size={13}/>形成有证据的表达</li></ol><Button onClick={()=>onNavigate("scenario")}>查看场景样例 <ArrowRight size={13}/></Button></Card><div className="outcome-scope"><span className="eyebrow small">EVIDENCE, NOT A LABEL</span><h3>状态有依据，也有边界。</h3><p>“已掌握”是当前规则对样例证据的投影，不代表具备真实生产项目经历。场景验证也不会直接改写掌握状态。</p><button onClick={()=>onEvidence("all")}>查看关联证据 <ArrowUpRight size={13}/></button></div></aside></div><ReplayFooter/>
  </div>
}

function ScenarioPage({onNavigate,onEvidence}:Props) {
  const [answer,setAnswer]=useState("")
  const [revealed,setRevealed]=useState(false)
  const [error,setError]=useState(false)
  usePendingEdits("scenario-answer",Boolean(answer.trim())&&!revealed)
  const {evidence,state,attempts,eligible}=scenarioRecord(replay,replay.interview_evidence[0].evidence_id) as {evidence:(typeof replay.interview_evidence)[number];state:(typeof replay.mastery_states)[number];attempts:typeof replay.attempts;eligible:boolean}
  const supporting=attempts.filter(item=>item.status==="completed")
  const reveal=(requireAnswer:boolean)=>{if(requireAnswer&&!answer.trim()){setError(true);document.getElementById("scenario-answer")?.focus();return}setError(false);setRevealed(true)}
  return <div className="page-enter career-page outcome-page scenario-page"><OutcomeIntro eyebrow="BRING KNOWLEDGE INTO CONTEXT" title={<>换到岗位场景，<span>看看知识能否连起来。</span></>} description="从现有能力证据出发，观察真实工作情境中的分析思路。" back="返回成长状态" onBack={()=>onNavigate("growth")}/><ReplayBanner/>
    <div className="scenario-entry"><ShieldCheck size={17}/><div><strong>样例进入依据：{demo.attempts.at(-1)?.state}</strong><p>{state.explanation} 这属于固定案例，不读取你的学习打卡。</p></div><button onClick={()=>onNavigate("growth")}>查看状态依据 <ArrowUpRight size={13}/></button></div>
    <div className="outcome-grid"><section><Card className="outcome-card scenario-question"><div className="outcome-card-heading"><div><span className="micro-label">岗位场景 · 数据开发工程师</span><h2>实时链路延迟升高，如何分层排查？</h2></div><span className="aside-icon"><MessageSquareText size={23}/></span></div><p className="scenario-prompt">{evidence.question}</p><div className="scenario-question-footer"><span><Target size={13}/>{demo.gap.title}</span><code>{evidence.evidence_id}</code></div></Card>
      {!revealed?<Card className="outcome-card scenario-practice"><div className="outcome-card-heading"><h2>试着说出你的排查思路</h2><PenLine size={17}/></div><label className="sr-only" htmlFor="scenario-answer">岗位场景练习回答</label><Textarea id="scenario-answer" maxLength={3000} value={answer} aria-invalid={error} aria-describedby={error?"scenario-practice-note scenario-error":"scenario-practice-note"} onChange={event=>{setAnswer(event.target.value);setError(false)}} placeholder="可以从观察哪些指标、怎样验证假设，以及何时采取回滚措施说起……"/><div className="outcome-answer-meta"><span>仅当前页面保留，离页或刷新清空。</span><span>{answer.length} / 3000</span></div><p id="scenario-practice-note" className="outcome-disclosure">提交后只回放预存验证记录，不评价本次回答，不产生面试成绩。</p>{error&&<p id="scenario-error" className="outcome-error" role="alert">请先写下你的思路，或直接回放样例。</p>}<div className="outcome-actions"><Button variant="ghost" onClick={()=>reveal(false)}><Play size={13}/>直接回放验证记录</Button><Button disabled={!eligible} onClick={()=>reveal(true)}>提交体验并回放 <ArrowRight size={14}/></Button></div></Card>:<Card className="outcome-card scenario-result" aria-live="polite"><div className="outcome-card-heading"><h2>岗位场景验证记录</h2><Badge variant="secondary">固定回放</Badge></div><div className="scenario-record-result"><MessageSquareText size={22}/><p>{evidence.result}</p></div><p className="outcome-disclosure">以上为人工整理快照中的验证描述，与本次练习输入无关；不是标准化面试成绩，不会直接改变能力状态。</p><details className="scenario-record-boundary"><summary>快照包含哪些内容？<ChevronDown size={13}/></summary><p>包含场景题、验证结果和来源标识。记录提到回答过一次追问，但未附追问题面、历史答卷或评分细节，本页不补写这些内容。</p></details>{answer.trim()&&<details className="scenario-record-boundary"><summary>查看我的练习回答<ChevronDown size={13}/></summary><p className="practice-answer">{answer}</p></details>}<div className="outcome-actions"><Button variant="outline" onClick={()=>setRevealed(false)}>返回练习</Button><Button onClick={()=>onNavigate("resume")}>查看证据化简历建议 <ArrowRight size={14}/></Button></div></Card>}
      <RecordedEvent name="Agent_E.transfer_interview"/></section><aside className="outcome-sidebar"><Card className="outcome-guide"><span className="aside-icon"><Link2 size={22}/></span><h3>先有证据，<br/>再谈迁移。</h3><p>以下是该样例掌握状态所关联的通过记录，可回看评分依据。</p><EvidenceReferences refs={supporting.map(item=>({kind:"attempt",ref_id:String(item.attempt_id)}))} onNavigate={onNavigate} onEvidence={onEvidence}/><code className="outcome-state-code">{state.rule_code}</code></Card><div className="outcome-scope"><span className="eyebrow small">A FOCUSED SCENARIO</span><h3>一次场景验证，一份明确记录。</h3><p>当前只展示快照中的一道场景题。没有实时面试、语音评估或新增追问；你的练习回答不上传。</p><button onClick={()=>onNavigate("resume")}>浏览已有简历建议 <ArrowUpRight size={13}/></button></div></aside></div><ReplayFooter/>
  </div>
}

function ResumePage({onNavigate,onEvidence}:Props) {
  const [tab,setTab]=useState("accepted")
  const [copyOpen,setCopyOpen]=useState(false)
  const copyRef=useRef<HTMLTextAreaElement>(null)
  const accepted=replay.resume_suggestions.find(item=>item.status==="accepted")!
  const blocked=replay.resume_suggestions.find(item=>item.status==="blocked")!
  const refs=resolveEvidenceRefs(replay,accepted.evidence_refs)
  const canCopy=canCopyDemoSuggestion(replay,accepted)
  const selectStatement=()=>{copyRef.current?.focus();copyRef.current?.select()}
  return <div className="page-enter career-page outcome-page resume-page"><OutcomeIntro eyebrow="LET EVIDENCE SHAPE YOUR STORY" title={<>把验证过的成长，<span>写成有依据的表达。</span></>} description="沿着差距、任务与验证记录，分清可以表达的成果和暂不成立的声明。" back="返回岗位场景验证" onBack={()=>onNavigate("scenario")}/><ReplayBanner/>
    <div className="resume-summary"><div><span className="aside-icon"><FileCheck2 size={24}/></span><div><span className="micro-label">固定案例 · 学习成果表达</span><h2>让每一句表述，都能找到来处。</h2><p>只读取既有建议，不改写或覆盖你的简历文件。</p></div></div><div><span><b>01</b>可采用样例</span><span><b>01</b>被拦截声明</span></div></div>
    <div className="outcome-grid"><section><Tabs value={tab} onValueChange={setTab} className="career-tabs resume-tabs"><TabsList><TabsTrigger value="accepted">可采用建议 · 01</TabsTrigger><TabsTrigger value="blocked">被拦截表达 · 01</TabsTrigger></TabsList><TabsContent value="accepted"><Card className="outcome-card resume-accepted"><div className="outcome-card-heading"><div><span className="micro-label">学习成果 · 演示建议</span><h2>{accepted.requested_claim}</h2></div><Badge variant="secondary"><ShieldCheck size={12}/>样例已收录</Badge></div><blockquote className="resume-statement">{accepted.suggestion}</blockquote><div className="resume-reason"><Check size={15}/><div><strong>这条表达为什么有依据？</strong><p>{accepted.reason}</p></div></div><div className="resume-copy-row"><span>复制的是演示案例，不代表你的个人经历。</span><Button disabled={!canCopy} onClick={()=>setCopyOpen(true)}><Copy size={13}/>查看与复制表述</Button></div>{!canCopy&&<p className="outcome-error">建议缺少完整来源，暂不可复制。</p>}<div className="resume-evidence-heading"><span><Link2 size={15}/>这句话的证据来源</span><b>{refs.filter(ref=>ref.found).length} / {refs.length} 已关联</b></div><EvidenceReferences refs={accepted.evidence_refs} onNavigate={onNavigate} onEvidence={onEvidence}/><details className="scenario-record-boundary"><summary>查看建议标识<ChevronDown size={13}/></summary><code>{accepted.suggestion_id}</code><p>这是固定样例已有的 accepted 记录；页面不执行新的建议生成或真实简历审核。</p></details></Card><RecordedEvent name="Agent_D.evidence_resume"/></TabsContent><TabsContent value="blocked"><Card className="outcome-card resume-blocked"><div className="outcome-card-heading"><div><span className="micro-label">证据边界 · 被拦截的请求</span><h2>这条声明，现有证据还不支持。</h2></div><ShieldX size={24}/></div><blockquote className="resume-statement">{blocked.requested_claim}</blockquote><div className="resume-reason"><ShieldX size={17}/><div><strong>拦截原因</strong><p>{blocked.reason}</p></div></div><div className="resume-blocked-note"><strong>样例中没有可采用的替代表述</strong><p>这条请求没有可采用建议，关联证据 {blocked.evidence_refs.length} 条。本页保留拦截结果，不提供复制此声明的按钮。</p></div><div className="outcome-actions"><Button variant="outline" onClick={()=>setTab("accepted")}>回看已有学习成果</Button><Button onClick={()=>onNavigate("plan")}>返回学习与实践 <ArrowRight size={14}/></Button></div><details className="scenario-record-boundary"><summary>查看拦截记录标识<ChevronDown size={13}/></summary><code>{blocked.suggestion_id}</code><p>仅回放固定案例的 blocked 记录，本轮没有执行新的模型审核。</p></details></Card><RecordedEvent name="Agent_D.evidence_guard"/></TabsContent></Tabs></section>
    <aside className="outcome-sidebar"><Card className="outcome-guide"><span className="aside-icon"><ShieldCheck size={22}/></span><h3>有证据的表达，<br/>才更有底气。</h3><p>专题学习与考核可以支持学习成果描述。项目职责、业务规模和真实产出，需要相应的真实项目证据。</p><ol><li><Target size={13}/>岗位差距明确</li><li><BookOpen size={13}/>学习任务可追溯</li><li><Check size={13}/>两次不同题面通过</li><li><MessageSquareText size={13}/>岗位场景验证记录</li></ol><Button variant="outline" onClick={()=>onNavigate("growth")}>回看成长状态 <ArrowRight size={13}/></Button></Card><div className="outcome-scope"><span className="eyebrow small">A CLEAR BOUNDARY</span><h3>保留成长，也保留事实。</h3><p>这份演示没有真实项目规模、职责或业务结果。可切换到拦截记录，查看系统为何没有强化项目经历。</p><button onClick={()=>setTab("blocked")}>查看拦截原因 <ArrowUpRight size={13}/></button></div></aside></div><Dialog open={copyOpen} onOpenChange={setCopyOpen}><DialogContent className="outcome-copy-dialog"><DialogHeader><DialogTitle>保留这份有依据的表达。</DialogTitle><DialogDescription>这是固定案例的学习成果样例，不代表你的个人经历，也不会写入或覆盖简历文件。</DialogDescription></DialogHeader><label htmlFor="demo-resume-statement">演示表述文本</label><Textarea id="demo-resume-statement" ref={copyRef} readOnly value={accepted.suggestion??""} onFocus={event=>event.currentTarget.select()}/><p>选中文本后，电脑按 Ctrl+C；手机可长按复制。</p><div><Button variant="outline" onClick={selectStatement}><Copy size={13}/>选中文本</Button><Button onClick={()=>setCopyOpen(false)}>完成</Button></div></DialogContent></Dialog><ReplayFooter/>
  </div>
}

export default function OutcomePages({view,...props}:Props&{view:OutcomeView}) { return view==="growth"?<GrowthPage {...props}/>:view==="scenario"?<ScenarioPage {...props}/>:<ResumePage {...props}/> }
