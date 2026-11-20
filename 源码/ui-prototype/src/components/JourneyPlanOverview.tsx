import { useMemo, useState } from "react"
import { ArrowRight, CalendarDays } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"

type Task={task_id:string;title:string;goal:string;topic_ids:string[]}
type Schedule={task_id:string;start_date:string;end_date:string;status:string}
type Topic={topic_id:string;title:string}
type Assessment={assessment_id:string;kind:string;scope_snapshot:{period_start:string;period_end:string}}
type Catalog={tasks:Task[];schedule:Schedule[];topics:Topic[];assessments:Assessment[]}
type Props={catalog:Catalog;onOpenTask:(task:Task)=>void;onExam:(kind:"day"|"week",value:string)=>void;onTopics:()=>void}
const statuses:Record<string,string>={not_started:"未开始",in_progress:"学习中",completed:"已完成"}
function today(){const p=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date());return ["year","month","day"].map(x=>p.find(y=>y.type===x)?.value).join("-")}
function week(date:string){const d=new Date(date+"T00:00:00Z");if(Number.isNaN(d.getTime()))return null;d.setUTCDate(d.getUTCDate()-((d.getUTCDay()+6)%7));const start=d.toISOString().slice(0,10);d.setUTCDate(d.getUTCDate()+6);return {start,end:d.toISOString().slice(0,10)}}
export default function JourneyPlanOverview({catalog,onOpenTask,onExam,onTopics}:Props){
 const [mode,setMode]=useState<"today"|"day"|"week"|"all">("today"),[date,setDate]=useState(today)
 const current=today(),selected=mode==="today"?current:date,period=mode==="week"?week(selected):null
 const start=period?.start??selected,end=period?.end??selected
 const tasks=useMemo(()=>catalog.schedule.filter(s=>mode==="all"||(start&&s.start_date<=end&&s.end_date>=start)).map(s=>({schedule:s,task:catalog.tasks.find(t=>t.task_id===s.task_id)})).filter((x):x is {schedule:Schedule;task:Task}=>Boolean(x.task)).sort((a,b)=>a.schedule.start_date.localeCompare(b.schedule.start_date)||a.task.title.localeCompare(b.task.title)),[catalog,start,end,mode])
 const topicName=(task:Task)=>task.topic_ids.map(id=>catalog.topics.find(t=>t.topic_id===id)?.title??id).join(" / ")
 const weekTemplate=period&&catalog.assessments.find(a=>a.kind==="week"&&a.scope_snapshot.period_start===period.start&&a.scope_snapshot.period_end===period.end)
 return <section className="journey-overview" aria-label="学习计划总览">
  <Card className="multi-card journey-overview-head"><div><span className="micro-label">YOUR LEARNING SCHEDULE</span><h2>把每一天的安排，放在一起看。</h2><p>从全部专题查看当前已保存的任务；点击任务进入学习、调整日期或更新状态。</p></div><Button variant="outline" onClick={onTopics}>按专题查看<ArrowRight size={14}/></Button></Card>
  <div className="journey-overview-tabs" role="group" aria-label="总览方式"><button aria-pressed={mode==="today"} onClick={()=>setMode("today")}>今日任务</button><button aria-pressed={mode==="day"} onClick={()=>setMode("day")}>按天查看</button><button aria-pressed={mode==="week"} onClick={()=>setMode("week")}>按周查看</button><button aria-pressed={mode==="all"} onClick={()=>setMode("all")}>全部安排</button></div>
  <Card className="multi-card journey-overview-content"><div className="journey-overview-range"><div><span className="micro-label">{mode==="week"?"WEEKLY VIEW":mode==="all"?"FULL PLAN":"DAILY VIEW"}</span><h2>{mode==="today"?"今天的学习":mode==="day"?"这一天的学习":mode==="week"?"这一周的学习":"全部学习安排"}</h2><p>{mode==="all"?"按开始日期排列":mode==="week"?`${start} 至 ${end} · 周一至周日`:selected||"请选择日期"} · {tasks.length} 项任务</p></div>{(mode==="day"||mode==="week")&&<label>选择日期<input aria-label="总览日期" type="date" value={date} onChange={e=>setDate(e.target.value)}/></label>}</div>
  {tasks.length?<div className="journey-overview-list">{tasks.map(({task,schedule})=><button key={task.task_id} className="journey-overview-task" onClick={()=>onOpenTask(task)}><span className="journey-overview-date"><CalendarDays size={15}/>{schedule.start_date===schedule.end_date?schedule.start_date:`${schedule.start_date} 至 ${schedule.end_date}`}</span><span className="journey-overview-task-main"><strong>{task.title}</strong><small>{topicName(task)}</small></span><span className="journey-overview-status">{statuses[schedule.status]??schedule.status}</span><ArrowRight size={16}/></button>)}</div>:<div className="journey-overview-empty"><strong>这段时间没有已安排的学习任务。</strong><p>可以切换日期查看其他安排，或进入专题调整任务日期。</p><Button variant="outline" onClick={onTopics}>查看全部专题</Button></div>}
  <p className="multi-muted">当前固定演示数据没有预计学习时长，暂不显示或计算总时长。多日任务在覆盖的日期和周内均可看到。</p>
  {mode!=="all"&&<div className="journey-overview-assessment"><div><strong>{mode==="week"?"准备好检查这一周？":"完成学习后，检查这一天。"}</strong><p>{mode==="week"?(weekTemplate?"进入对应日期的预设周考核；题目覆盖范围固定，可能与调整后的安排不同。":"所选周暂无对应的固定周考核样例；可到考核页查看现有预设周期。"):"按所选日期查看已有的固定每日考核样例。"}</p></div>{mode==="week"?<Button variant="outline" onClick={()=>onExam("week",weekTemplate?.assessment_id??"")}>{weekTemplate?"进入本周考核":"查看预设周考核"}<ArrowRight size={14}/></Button>:<Button variant="outline" disabled={!selected} onClick={()=>onExam("day",selected)}>进入这一天的考核<ArrowRight size={14}/></Button>}</div>}
  </Card>
 </section>
}
