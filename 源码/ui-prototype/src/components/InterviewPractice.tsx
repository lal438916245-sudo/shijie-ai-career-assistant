import { useState } from "react"
import { ArrowRight, MessageSquareText } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { usePendingEdits } from "./WorkspaceQuality"

type Interview={persona:string;context:string;turns:{role:string;text:string}[];feedback:{title:string;text:string}[]}
type Props={interview:Interview;onNavigate:(view:"plan"|"resume",round?:number,topic?:string)=>void}
export default function InterviewPractice({interview,onNavigate}:Props){
 const [step,setStep]=useState<0|1|2>(0),[answers,setAnswers]=useState(["",""]),[error,setError]=useState("")
 usePendingEdits("interview-conversation",step<2&&answers.some(a=>a.trim().length>0))
 const submit=()=>{if(!answers[step]?.trim()){setError("请先填写本轮回答。");document.getElementById("interview-answer")?.focus();return}setError("");setStep(step===0?1:2)}
 const restart=()=>{setAnswers(["",""]);setError("");setStep(0)}
 return <section aria-label="对话式模拟面试">
  <Card className="multi-interview-context"><MessageSquareText size={26}/><div><span className="micro-label">{interview.persona}</span><h2>一次贴近岗位的对话。</h2><p>{interview.context} 这次对话以固定情境演示面试过程，不改变学习进度或能力状态。</p></div></Card>
  <div className="interview-progress" aria-label="面试进度"><span className={step===0?"active":""}>01 主问</span><span className={step===1?"active":""}>02 追问</span><span className={step===2?"active":""}>03 复盘</span></div>
  <div className="multi-conversation" aria-live="polite">
   <Card className="multi-bubble interviewer"><span>E · 面试官 / 主问</span><p>{interview.turns[0].text}</p></Card>
   {step>=1&&<Card className="multi-bubble candidate"><span>我的回答 / 主问</span><p>{answers[0]}</p></Card>}
   {step>=1&&<Card className="multi-bubble interviewer"><span>E · 面试官 / 固定追问</span><p>{interview.turns[2].text}</p></Card>}
   {step===2&&<Card className="multi-bubble candidate"><span>我的回答 / 追问</span><p>{answers[1]}</p></Card>}
  </div>
  {step<2?<Card className="multi-card interview-compose"><span className="micro-label">{step===0?"YOUR ANSWER":"FOLLOW-UP"} · {step===0?"回答主问":"回答追问"}</span><h2>{step===0?"先说说你的排查思路。":"面对新约束，你会怎么调整？"}</h2><label htmlFor="interview-answer">我的演示回答</label><Textarea id="interview-answer" maxLength={3000} value={answers[step]} onChange={e=>{const next=[...answers];next[step]=e.target.value;setAnswers(next);setError("")}} placeholder="写下你的思路……"/><p className="multi-muted">回答仅保留在当前页面，刷新或离开后清空；请使用演示内容。追问是预设内容，不根据回答生成。</p>{error&&<p className="multi-error" role="alert">{error}</p>}<div className="multi-actions"><Button onClick={submit}>{step===0?"发送回答，继续追问":"结束面试，查看复盘"}<ArrowRight size={14}/></Button></div></Card>:<>
   <Card className="multi-card interview-report"><span className="micro-label">INTERVIEW REFLECTION · 固定案例复盘</span><h2>把一次回答，变成下一步的线索。</h2><p className="interview-disclaimer">以下是预先编写的合成案例反馈，不分析或评价你的回答，也不是你的面试成绩。</p><div className="multi-two-col"><section><span className="interview-report-number">01</span><h3>案例中的亮点</h3><p>{interview.feedback[0].text}</p></section><section><span className="interview-report-number">02</span><h3>案例中待改进的问题</h3><p>{interview.feedback[1].text}</p></section></div><div className="interview-advice"><strong>练习建议 · 可以如何继续</strong><p>回到 SQL 学习安排，练习先验证查询语义，再对照执行计划定位性能瓶颈；也可重新组织自己的面试回答。</p><Button variant="outline" onClick={()=>onNavigate("plan",1,"sql")}>查看 SQL 学习计划<ArrowRight size={14}/></Button><p className="multi-muted">这是固定建议，点击只打开计划，不自动修改任务或能力状态。</p></div></Card>
   <details className="sequential-history"><summary>查看固定案例的参考回答</summary><p>主问：{interview.turns[1].text}</p><p>追问：{interview.turns[3].text}</p><p>人工编写的合成样例，不是你的回答。</p></details>
   <div className="multi-actions"><Button variant="outline" onClick={restart}>重新开始面试</Button><Button variant="outline" onClick={()=>onNavigate("resume")}>查看简历修改<ArrowRight size={14}/></Button></div>
  </>}
 </section>
}
