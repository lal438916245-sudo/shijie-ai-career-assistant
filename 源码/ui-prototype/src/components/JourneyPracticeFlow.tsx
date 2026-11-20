import { useEffect, useRef, type ReactNode } from "react"
import { ArrowRight, Check, ClipboardList } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"

export type PracticeReview={item_id:string;question_text:string;answer:string;topic_ids:string[];reference_answer:string;explanation:string;checkpoints:string[];common_mistakes:string[];notice:string}
type Evidence={evidence_id:string;topic_id:string;topic_score:number;feedback:string;question_id?:string;rubric_dimensions:{key:string;label:string;score:number;weight_bps:number}[]}
export type PracticeRun={run_id:string;kind:string;template_id:string;status:string;scope:{items?:{task_id:string;start_date:string;status:string}[];notice?:string;topic_id?:string;source_evidence_id?:string};current_question:{id:string;text:string;topic_ids:string[]}|null;result:{topic_evidence:Evidence[];notice:string}|null;report:{feedback:{id:string;kind:string;text:string;suggested_topic_ids?:string[]}[];notice:string}|null;reviews?:PracticeReview[];submitted_count:number;question_count:number;notice:string}
type Answer={item_id:string;answer:string;question_text:string}
const names:Record<string,string>={day:"每日考核",week:"每周考核",retest:"专题复测",interview:"岗位模拟面试"}

export function ReferenceReviews({reviews}:{reviews:PracticeReview[]}){
 return <div className="practice-reviews">{reviews.map((r,i)=><details key={r.item_id} className="practice-review"><summary><span>{String(i+1).padStart(2,"0")}</span><strong>{r.question_text}</strong><span>展开复盘</span></summary><div className="practice-review-body"><h4>我的回答</h4><p className="practice-own-answer">{r.answer}</p><h4>人工参考思路</h4><p>{r.reference_answer}</p><h4>为什么这样解答</h4><p>{r.explanation}</p><h4>核对要点</h4><ul>{r.checkpoints.map(x=><li key={x}>{x}</li>)}</ul><h4>常见误区 · 不代表你犯了这些错误</h4><ul>{r.common_mistakes.map(x=><li key={x}>{x}</li>)}</ul><small>{r.notice}</small></div></details>)}</div>
}

type Props={run:PracticeRun|null;preparing:boolean;preparation:ReactNode;busy:boolean;answer:string;history:Answer[];onAnswer:(value:string)=>void;onSubmit:()=>void;onNext:()=>void;onFinish:()=>void;onPrepare:()=>void;onResume:()=>void;onRecords:()=>void;onLearning:(topic:string)=>void;topics:Record<string,string>}
export default function JourneyPracticeFlow(p:Props){
 const {run}=p
 const terminal=Boolean(run&&["completed","ended_early"].includes(run.status))
 const phase=p.preparing||!run?"prepare":terminal?"report":"answer"
 const focusTarget=useRef<HTMLElement>(null),conversation=useRef<HTMLDivElement>(null)
 useEffect(()=>{if(phase==="prepare")return;const frame=requestAnimationFrame(()=>{focusTarget.current?.focus({preventScroll:true});focusTarget.current?.scrollIntoView({block:"start",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"})});return()=>cancelAnimationFrame(frame)},[phase,run?.run_id,run?.current_question?.id,run?.status])
 useEffect(()=>{if(conversation.current)conversation.current.scrollTop=conversation.current.scrollHeight},[p.history.length])
 const blocked=p.busy||Boolean(p.answer.trim())
 return <section className="practice-flow" aria-label="准备、作答与报告"><ol className="practice-steps" aria-label="测试流程">{[["prepare","准备"],["answer","作答"],["report","报告"],["records","记录"]].map(([key,label],i)=><li key={key} aria-current={phase===key?"step":undefined}><span>{i+1}</span>{label}</li>)}</ol>
 {phase==="prepare"?<>{run&&<Card className="multi-card practice-resume"><div><h3>{terminal?"已有一份保存的报告":"有一份练习可以继续"}</h3><p>{names[run.kind]} · 已提交 {run.submitted_count} / {run.question_count} 题。新开测试会保留这份记录。</p></div><Button disabled={p.busy} onClick={p.onResume}>{terminal?"查看上次报告":"继续本次练习"}<ArrowRight size={14}/></Button></Card>}<div className="practice-preparation">{p.preparation}</div></>:run&&<section ref={focusTarget} tabIndex={-1} className="practice-focus" aria-label={phase==="report"?"测试报告":"当前作答"}>
 <div className="practice-session-head"><div><span className="micro-label">{phase==="report"?"YOUR REFLECTION":"ONE STEP AT A TIME"}</span><h2>{names[run.kind]} · {phase==="report"?"本次报告":"正在进行"}</h2><p>已提交 {run.submitted_count} / {run.question_count} 题{run.status==="ended_early"?" · 已提前结束":""}</p></div><Button variant="outline" disabled={blocked} onClick={p.onPrepare}>{phase==="report"?"返回准备，另开一次":"返回准备"}</Button></div>
 <div className="practice-progress" role="progressbar" aria-label="作答进度" aria-valuemin={0} aria-valuemax={run.question_count} aria-valuenow={run.submitted_count}><span style={{width:`${run.submitted_count/run.question_count*100}%`}}/></div>
 {phase==="answer"?<>
 {run.kind==="interview"&&p.history.length>0?<div className="practice-chat" ref={conversation} aria-label="已提交面试对话">{p.history.map((x,i)=><div key={x.item_id}><div className="practice-chat-interviewer"><small>面试官 · {i+1}</small><p>{x.question_text}</p></div><div className="practice-chat-candidate"><small>我的回答</small><p>{x.answer}</p></div></div>)}</div>:p.history.length>0&&<details className="practice-history"><summary>回看已提交回答（{p.history.length}）</summary>{p.history.map((x,i)=><div key={x.item_id}><strong>{i+1}. {x.question_text}</strong><p>{x.answer}</p></div>)}</details>}
 {run.current_question?<Card className="multi-card practice-question"><span className="micro-label">{run.kind==="interview"?"面试官":"当前题目"} · 第 {run.submitted_count+1} / {run.question_count} 题</span><h3>{run.current_question.text}</h3><label htmlFor="journey-answer">我的回答</label><Textarea id="journey-answer" value={p.answer} maxLength={6000} onChange={e=>p.onAnswer(e.target.value)} placeholder="写下你的思路……"/><p className="multi-muted">提交后保存到本机；当前为固定演示，不评价你的回答。{run.kind==="retest"?"提交本题后可查看参考解析。":"整份结束后可查看参考解析。"}</p><Button disabled={p.busy} onClick={p.onSubmit}>{p.busy?"正在保存…":"提交本题"}<ArrowRight size={14}/></Button></Card>:<Card className="multi-card practice-next"><Check size={24}/><h3>本题已保存。</h3><p>{run.kind==="retest"?"可先核对下方参考解析，再继续。看过解析后的表现不等于独立掌握。":"参考解析将在本次结束后统一开放。"}</p><Button disabled={p.busy} onClick={p.onNext}>{run.kind==="interview"?"继续面试":"进入下一题"}<ArrowRight size={14}/></Button></Card>}
 {run.kind==="retest"&&Boolean(run.reviews?.length)&&<Card className="multi-card"><h3>已提交题目的参考解析</h3><ReferenceReviews reviews={run.reviews??[]}/></Card>}
 <div className="multi-actions"><Button variant="ghost" disabled={blocked} onClick={p.onFinish}>提前结束并保留记录</Button><Button variant="outline" disabled={blocked} onClick={p.onRecords}>去成长记录</Button></div>{p.answer.trim()&&<p className="multi-muted">当前回答尚未提交；请先提交，或清空后离开。</p>}
 </>:<>
 <Card className="multi-card practice-report-summary"><span className="micro-label">{run.status==="completed"?"本次固定演示已完成":"本次已提前结束"}</span><h3>{run.status==="completed"?"把答题过程，变成下一步的方向。":"已保存的回答仍可回看。"}</h3><p>已提交 {run.submitted_count} 题 · 共 {run.question_count} 题 · 覆盖 {Array.from(new Set((run.reviews??[]).flatMap(r=>r.topic_ids))).map(t=>p.topics[t]??t).join("、")||"暂无已提交内容"}</p><p className="journey-warning">没有对本次回答进行真实评分。以下参考答案、核对要点及案例反馈均为人工预设；未提交题目不开放解析，也不会据此更新能力状态。</p></Card>
 {run.report&&<Card className="multi-card"><h3>面试案例复盘</h3><p>{run.report.notice}</p>{run.report.feedback.map(f=><section key={f.id} className="practice-feedback"><h4>{f.kind==="strength"?"合成案例亮点":f.kind==="improvement"?"合成案例待改进":"后续练习建议"}</h4><p>{f.text}</p>{f.suggested_topic_ids?.[0]&&<Button variant="outline" onClick={()=>p.onLearning(f.suggested_topic_ids![0])}>查看相关学习专题</Button>}</section>)}</Card>}
 {Boolean(run.reviews?.length)&&<Card className="multi-card"><h3>逐题复盘 · 回答与参考解析</h3><p>展开单题查看；开放题允许其他合理解法。面试示例提供表达思路，请结合实际经历回答。</p><ReferenceReviews reviews={run.reviews??[]}/></Card>}
 {run.result&&<details className="practice-history"><summary>查看历史案例分项 · 非本次评分</summary><p>{run.result.notice}</p>{run.result.topic_evidence.map(e=><p key={e.evidence_id}>{p.topics[e.topic_id]??e.topic_id} · 案例 {e.topic_score} 分：{e.feedback}</p>)}</details>}
 {run.kind==="interview"&&p.history.length>0&&<details className="practice-history"><summary>查看完整面试对话</summary>{p.history.map((x,i)=><div key={x.item_id}><strong>面试官 {i+1}：{x.question_text}</strong><p>我的回答：{x.answer}</p></div>)}</details>}
 <div className="multi-actions"><Button onClick={p.onRecords}>去成长记录回看<ClipboardList size={14}/></Button><Button variant="outline" onClick={()=>p.onLearning(run.scope.topic_id??run.reviews?.[0]?.topic_ids[0]??"sql")}>返回学习计划</Button></div>
 </>}
 </section>}
 </section>
}
