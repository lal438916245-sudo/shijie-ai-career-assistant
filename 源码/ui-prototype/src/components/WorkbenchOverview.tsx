import {ArrowRight, BookOpen, Check, Compass, FileCheck2, MessageSquareText, Target} from 'lucide-react'
import {Button} from './ui/button'
import {Card} from './ui/card'
import type {View} from '@/lib/routes.mjs'
import './workbench-overview.css'

type Task = {task_id:string;title:string;day:number}
type Progress = {task_id:string;status:string;start_date:string;end_date:string}
type Capability = {topic_id:string;state:string;label:string;title:string;latest_score:number|null}
type OverviewState = {
 candidate:{display_name:string};position:{title:string};diagnosis:unknown;plan:{plan:{tasks:Task[]}}|null
 personal_input?:boolean;resume_reports?:unknown[];published_version:number|null;recovery_available:boolean;progress:Progress[];capabilities?:Capability[]
}
type OverviewRecord = {kind:string;payload:unknown}
type Destination = {view:View;params?:Record<string,string>}
type Next = Destination & {label:string;detail:string}
const needsRetest = new Set(['needs_retest','regressed','provisional_pass'])
const events = (records:OverviewRecord[],kind:string,event:string)=>records.filter(r=>r.kind===kind&&(r.payload as {event?:string})?.event===event)

export function overviewJourney(data:OverviewState|null,records:OverviewRecord[],date:string,recordsReady:boolean) {
 const tasks=data?.plan?.plan.tasks??[]
 const progress=new Map(data?.progress.map(p=>[p.task_id,p]))
 const completed=tasks.filter(t=>progress.get(t.task_id)?.status==='completed').length
 const inProgress=tasks.filter(t=>progress.get(t.task_id)?.status==='in_progress').length
 const deferred=tasks.filter(t=>progress.get(t.task_id)?.status==='deferred').length
 const available=tasks.filter(t=>['not_started','in_progress'].includes(progress.get(t.task_id)?.status??'not_started'))
 const task=available.find(t=>progress.get(t.task_id)?.status==='in_progress')
  ??available.find(t=>{const p=progress.get(t.task_id);return p&&p.end_date<date})
  ??available.find(t=>{const p=progress.get(t.task_id);return p&&p.start_date<=date&&p.end_date>=date})??available[0]
 const answers=records.filter(r=>['assessment','retest'].includes(r.kind)&&(r.payload as {event?:string})?.event==='answer_submitted')
 const interviews=events(records,'interview','interview_report')
 const resumes=events(records,'resume','resume_report')
 const supplement=data?.capabilities?.find(c=>needsRetest.has(c.state))
 let next:Next={view:'new',label:'开始新的求职计划',detail:'先保存自己的简历和JD，再确认运行模式与累计额度。'}
 if(data){
  if(data.recovery_available)next={view:'diagnosis',label:'恢复岗位诊断',detail:'诊断步骤曾中断，请先查看恢复提示，原资料与记录继续保留。'}
  else if(!data.diagnosis)next={view:'diagnosis',label:'开始岗位诊断',detail:'对照简历与岗位要求，先弄清已有证据和需要补足的方向。'}
  else if(data.personal_input&&!data.plan)next={view:'resume',label:data.resume_reports?.length?'查看已保存的完整简历':'优化我的简历',detail:'岗位诊断已保存，可直接核对并优化已有简历；学习计划、单题反馈和短面试可稍后按需使用。'}
  else if(!data.plan)next={view:'plan',label:'制定学习计划',detail:'岗位诊断已保存，接下来为差距安排可执行的学习任务。'}
  else if(!data.published_version)next={view:'plan',label:'查看并确认学习计划',detail:'先查看每日任务与程序校验结果，由你确认发布后开始学习。'}
  else if(task)next={view:'plan',params:{task:task.task_id},label:'继续学习：'+task.title,detail:`第 ${task.day} 天 · 从讲解和示例开始，再做练习并保存学习进度。`}
  else if(completed<tasks.length)next={view:'plan',label:'调整暂缓的学习安排',detail:'尚有任务暂缓，可以调整日期或恢复学习；暂缓不会计作已完成。'}
  else if(!recordsReady)next={view:'growth',label:'查看成长状态与待验证项',detail:'学习任务已完成，正在核对本会话的考核、面试与简历记录。'}
  else if(supplement)next={view:'retest',params:{focus:supplement.topic_id},label:'补强与复测：'+supplement.title,detail:'已有答卷提示仍需验证。可在专题复测页查看依据，并返回相关任务补学。'}
  else if(!data.capabilities?.length||data.capabilities.some(c=>c.latest_score==null||c.state==='review_required'||(c as Capability&{pending_ids?:string[]}).pending_ids?.length))next={view:'exam',label:'用日周考核验证学习',detail:'完成学习不等于已经掌握，提交独立答卷后才能积累能力证据；待核对的评分也可从考核页查看。'}
  else if(!interviews.length)next={view:'scenario',label:'开始岗位模拟面试',detail:'已有学习与考核证据，接下来围绕整个岗位练习表达与追问。'}
  else if(!resumes.length)next={view:'resume',label:'查看有证据的简历优化',detail:'岗位面试已有结束复盘，结合学习成果核对可以写进简历的内容。'}
  else next={view:'resume',label:'查看优化简历与修改依据',detail:'本会话已有学习、答卷、面试复盘与简历版本，可继续核对证据和完善表达。'}
 }
 const steps:[View,string,string,typeof Target][]=[
  ['diagnosis','了解岗位差距',data?.diagnosis?'已保存诊断':'从简历与 JD 开始',Target],
  ['plan','按计划学习',data?.published_version?`完成 ${completed}/${tasks.length} 项`:data?.plan?'计划待确认':'把差距拆成任务',BookOpen],
  ['exam','考核与补强',recordsReady?answers.length?`已有 ${answers.length} 份答卷`:'尚无作答记录':'日周考核 · 专题复测',FileCheck2],
  ['scenario','岗位模拟面试',recordsReady&&interviews.length?`已有 ${interviews.length} 场复盘`:'逐轮问答与复盘',MessageSquareText],
  ['resume','优化求职简历',recordsReady&&resumes.length?`已有 ${resumes.length} 份建议`:'让修改有证据',FileCheck2],
 ]
 return {next,steps,tasks,completed,inProgress,deferred,answers:answers.length,interviews:interviews.length,resumes:resumes.length}
}

export default function WorkbenchOverview({data,label,records,recordsReady,date,blocked=false,onNavigate}:{
 data:OverviewState|null;label?:string;records:OverviewRecord[];recordsReady:boolean;date:string;blocked?:boolean
 onNavigate:(view:View,params?:Record<string,string>)=>void
}) {
 const model=overviewJourney(data,records,date,recordsReady)
 const active=model.next.view==='retest'?'exam':model.next.view
 const verified=data?.capabilities?.filter(c=>c.latest_score!==null).length??0
 const mastered=data?.capabilities?.filter(c=>c.state==='mastered').length??0
 return <div className="wb-home">
  <Card className="wb-home-focus">
   <div className="wb-home-copy"><span className="micro-label"><Compass size={14}/> {data?'CURRENT JOURNEY':'YOUR NEXT OPPORTUNITY'}</span>
    <h2>{data?data.position.title:'开启你的求职成长之旅'}</h2>
    <p className="wb-home-context">{data?`${label??'当前会话'} · ${data.candidate.display_name}`:'从岗位差距出发，把学习成果变成有证据的简历提升。'}</p>
    <div className="wb-home-next"><span>建议下一步</span><p>{model.next.detail}</p>
     <Button disabled={blocked} onClick={()=>onNavigate(model.next.view,model.next.params)}>{model.next.label}<ArrowRight size={17}/></Button>
     {blocked&&<small>请先处理上方待确认操作，或等待会话读取完成。</small>}
    </div>
   </div>
   <aside className="wb-home-compass" aria-label="本会话学习进度">
    <span className="wb-home-orbit"><Compass size={42} strokeWidth={1.2}/></span>
    <strong>{data?.published_version?`${model.completed} / ${model.tasks.length}`:'从这里出发'}</strong>
    <span>{data?.published_version?'项学习任务已完成':data?.diagnosis?'岗位诊断已保存':'先了解自己与目标岗位'}</span>
    {data?.published_version&&<progress aria-label="本会话学习完成度" value={model.completed} max={model.tasks.length||1}/>}
    <small>{data?.published_version?`学习中 ${model.inProgress} · 暂缓 ${model.deferred}`:'每一步的结果会保存在同一会话'}</small>
   </aside>
  </Card>
  <section className="wb-home-path" aria-labelledby="wb-home-path-title"><div className="wb-home-heading"><h2 id="wb-home-path-title">接下来，沿着这条路走</h2><span>随时可回看，按需补强</span></div>
   <ol aria-label="求职成长五步流程">{model.steps.map(([view,title,detail,Icon],index)=><li key={view}>
    <button disabled={blocked} type="button" aria-current={active===view?'step':undefined} onClick={()=>onNavigate(view)}>
     <span className="wb-home-step-mark"><Icon size={19}/><small>{String(index+1).padStart(2,'0')}</small></span>
     <strong>{title}</strong><span>{detail}</span>{active===view&&<em>建议下一步</em>}
    </button>{index<4&&<ArrowRight className="wb-home-connector" size={16} aria-hidden="true"/>}
   </li>)}</ol>
   <p className="wb-home-footnote">{data?.personal_input?'最短流程：A 岗位诊断 → D 简历优化。学习计划、单题反馈和短面试按需使用，不影响先整理已有经历。':'先完成一项学习与单题反馈，短面试可按需体验；也可先进入简历优化，C/E未完成不阻塞D。学习进度与能力状态分别记录。'}</p>
  </section>
  {data&&<Card className="multi-card wb-home-growth"><div className="wb-home-heading"><h2>我的成长，一眼看清</h2><Button variant="ghost" disabled={blocked} onClick={()=>onNavigate('growth')}>查看状态与依据<ArrowRight size={15}/></Button></div>
   <div className="wb-home-metrics"><div><span>已提交答卷</span><strong>{recordsReady?`${model.answers} 份`:'读取中'}</strong><small>日周考核与专题复测合并统计</small></div>
    <div><span>已有有效分项的专题</span><strong>{verified} / {data.capabilities?.length??0}</strong><small>依据本会话保存的考核与复测</small></div>
    <div><span>{data.personal_input?'达到当前掌握规则':'达到演示掌握规则'}</span><strong>{mastered} 项</strong><small>需要独立题面的通过证据</small></div></div>
   <div className="wb-home-growth-footer"><span><Check size={14}/> {data.personal_input?'本会话验证状态；模型反馈不等于独立验证的学习成效':'固定演示状态，不代表真实学习成效'}</span><Button variant="ghost" disabled={blocked} onClick={()=>onNavigate('records')}>查看全部成长记录<ArrowRight size={14}/></Button></div>
  </Card>}
  <details className="wb-binding-details"><summary>赛后路线图 · 不属于当前交付功能</summary><p>F 智能审查：保留实验实现和历史回执，引用与审查质量仍待完善。自定义每日学习时间：保留早期实现，待完善时间重排与质量验证。比赛版固定每天60分钟，支持进度、日期和暂缓调整。</p></details>
 </div>
}
