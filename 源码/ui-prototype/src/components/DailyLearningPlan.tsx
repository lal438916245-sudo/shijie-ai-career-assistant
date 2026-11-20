import {usePendingEdits} from './WorkspaceQuality'
import {useEffect,useRef,useState} from 'react'
import {Button} from './ui/button'
import {Input} from './ui/input'
import {workflowRequest,sdkRequest} from '@/lib/workflow-api.mjs'

type Status='not_started'|'in_progress'|'completed'|'deferred'
type Progress={status:Status;reason:string;revision:number}
export type GuidedTask={id:number;day:number;content:string;expected_outcome:string;gap_ids:string[];progress:Progress;time_budget:{learning_minutes:number;core_minutes:number;review_minutes:number;optional_minutes:number};guide:{starting_point:string;concepts:{term:string;explanation:string;example:string}[];steps:string[];worked_example:string;exercise:{prompt:string;hints:string[];reference_answer:string;checkpoints:string[]};fallback:string};tiers:{tier:'core'|'optional';content:string;expected_outcome:string}[]}
export type DailyPlanData={deferred_gap_display?:{gap_id:string;skill:string;reason:string;revisit_when:string}[];notice:string;source_kind:string;result?:{plan:{plan_version?:string;learning_preferences?:{daily_minutes:number;starting_level:string};deferred_gaps?:{gap_id:string;reason:string;revisit_when:string}[]}};tasks?:GuidedTask[]}
const labels:Record<Status,string>={not_started:'未开始',in_progress:'学习中',completed:'已完成',deferred:'暂缓学习'}

function TaskCard({task,busy,onSave,scope}:{task:GuidedTask;busy:boolean;scope:string;onSave:(task:GuidedTask,status:Status,reason:string)=>void}){
 const [status,setStatus]=useState(task.progress.status),[reason,setReason]=useState(task.progress.reason)
 useEffect(()=>{setStatus(task.progress.status);setReason(task.progress.reason)},[task.id,task.progress.revision])
 const b=task.time_budget,exercise=task.guide.exercise
 const required=b.learning_minutes+b.core_minutes+b.review_minutes
 const dirty=status!==task.progress.status||reason!==task.progress.reason
 usePendingEdits(scope+':'+task.id,dirty)
 return <section className="daily-learning-card"><header><span className="micro-label">DAY {String(task.day).padStart(2,'0')}</span><span>{labels[task.progress.status]}</span></header><h3>{task.content}</h3><p>基础安排 {required} 分钟；选做另 {b.optional_minutes} 分钟，总计 {required+b.optional_minutes} 分钟。</p><p className="multi-muted">讲解 {b.learning_minutes} · 必做 {b.core_minutes} · 复盘 {b.review_minutes} · 选做 {b.optional_minutes} 分钟</p><p>交付：{task.expected_outcome}</p>
 <details open={task.day===1}><summary>从这里开始学习</summary><p>{task.guide.starting_point}</p>{task.guide.concepts.map((c,i)=><div key={i}><h4>{c.term}</h4><p>{c.explanation}</p><p>例如：{c.example}</p></div>)}<ol>{task.guide.steps.map((s,i)=><li key={i}>{s}</li>)}</ol><h4>跟着做一个例子</h4><p>{task.guide.worked_example}</p></details>
 <div className="daily-task-tiers">{task.tiers.map(t=><section key={t.tier}><h4>{t.tier==='core'?'必做 · 先达到最低目标':'选做 · 有余力再挑战'}</h4><p>{t.content}</p><p>交付：{t.expected_outcome}</p></section>)}</div>
 <details><summary>动手练习 · 提示、参考答案与自查</summary><p>这是学习练习，不评分、不更新能力状态。</p><p>{exercise.prompt}</p><details><summary>需要一点提示</summary><ul>{exercise.hints.map((s,i)=><li key={i}>{s}</li>)}</ul></details><details><summary>查看参考答案与自查点</summary><pre className="daily-reference">{exercise.reference_answer}</pre><ul>{exercise.checkpoints.map((s,i)=><li key={i}>{s}</li>)}</ul></details></details>
 <p>觉得困难时：{task.guide.fallback}</p><div className="model-config-grid"><label>学习进度<select value={status} disabled={busy} onChange={e=>{const next=e.target.value as Status;setStatus(next);if(next!=='deferred')setReason('')}}>{Object.entries(labels).map(([s,label])=><option key={s} value={s}>{label}</option>)}</select></label>{status==='deferred'&&<label>暂缓原因<Input value={reason} maxLength={1000} disabled={busy} onChange={e=>setReason(e.target.value)} placeholder="例如本周时间冲突，之后再继续"/></label>}</div><Button disabled={busy||!dirty||(status==='deferred'&&!reason.trim())} onClick={()=>onSave(task,status,reason)}>保存学习进度</Button>{task.progress.status==='deferred'&&<p>暂缓原因：{task.progress.reason}。之后选择“未开始”或“学习中”并保存即可恢复。</p>}
 </section>
}

export function DailyLearningPlanContent({data,busy=false,onSave=()=>{},scope='daily-plan'}:{data:DailyPlanData;scope?:string;busy?:boolean;onSave?:(task:GuidedTask,status:Status,reason:string)=>void}){
 const plan=data.result?.plan
 if(plan?.plan_version!=='daily-learning-v1')return null
 const deferredGaps=data.deferred_gap_display??plan.deferred_gaps
 const tasks=data.tasks??[],done=tasks.filter(t=>t.progress.status==='completed').length,deferred=tasks.filter(t=>t.progress.status==='deferred').length
 return <div className="daily-learning-plan"><h3>每日学习 · 从概念到小练习</h3><p>每天最多 {plan.learning_preferences?.daily_minutes} 分钟 · {plan.learning_preferences?.starting_level==='beginner'?'零基础引导':'已有基础'}。完成 {done}/{tasks.length} 项，暂缓 {deferred} 项；暂缓不算完成。</p><p className="workflow-note">{data.notice} 学习进度与答卷、评分和能力状态分开，不因勾选完成或查看答案而提升能力。</p>{tasks.map(t=><TaskCard key={t.id} task={t} busy={busy} onSave={onSave} scope={scope}/>)}<section className="daily-deferred"><h4>本轮暂缓的差距</h4>{deferredGaps?.length?deferredGaps.map(g=><div key={g.gap_id}><strong>{'skill' in g?String(g.skill):'暂缓差距'}</strong><p>{g.reason}</p><p>恢复条件：{g.revisit_when}</p><details><summary>查看差距来源</summary><code>{g.gap_id}</code></details></div>):<p>本轮没有单独暂缓的差距。</p>}<p>这些差距没有计入本轮任务训练，也不代表已掌握。</p></section></div>
}

export default function DailyLearningPlan({token,api='workflow',mode='real_model'}:{token:string;api?:'workflow'|'sdk';mode?:'sdk_rehearsal'|'real_model'}){
 const [data,setData]=useState<DailyPlanData|null>(null),[error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false)
 const epoch=useRef(0),flight=useRef(false)
 const request=(path:string,body?:Record<string,unknown>)=>api==='sdk'?sdkRequest(path,token,body,mode):workflowRequest(path,token,body)
 useEffect(()=>{const id=++epoch.current;setData(null);setError('');setMessage('');setBusy(false);flight.current=false;request('plan').then((value:DailyPlanData)=>{if(id===epoch.current)setData(value)}).catch((e:Error)=>{if(id===epoch.current)setError(e.message)});return()=>{epoch.current++}},[token,api,mode])
 const reload=async()=>{if(flight.current)return;flight.current=true;const id=++epoch.current;setError('');setBusy(true);try{const value=await request('plan');if(id===epoch.current)setData(value)}catch(e){if(id===epoch.current)setError(e instanceof Error?e.message:'读取失败')}finally{if(id===epoch.current){flight.current=false;setBusy(false)}}}
 const save=async(task:GuidedTask,status:Status,reason:string)=>{if(flight.current)return;const id=++epoch.current;flight.current=true;setBusy(true);setError('');setMessage('');try{const value=await request('plan-progress',{task_id:task.id,status,reason,expected_revision:task.progress.revision});if(id===epoch.current){setData(value);setMessage('学习进度已保存；没有评分、模型调用或能力状态变化。')}}catch(e){if(id===epoch.current)setError(e instanceof Error?e.message:'保存结果未确认，请重新读取')}finally{if(id===epoch.current){flight.current=false;setBusy(false)}}}
 return <>{error&&<p role="alert" className="multi-error">{error} 保存结果不确定时请重新读取，不会自动重发。</p>}{message&&<p role="status">{message}</p>}<Button variant="outline" disabled={busy} onClick={reload}>重新读取学习进度</Button>{data?<DailyLearningPlanContent data={data} busy={busy} onSave={save} scope={api+token}/>:<p>正在读取每日学习安排…</p>}</>
}
