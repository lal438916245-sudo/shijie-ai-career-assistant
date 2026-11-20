import {useEffect,useState} from 'react'
import {Card} from './ui/card'
import {Button} from './ui/button'
import {workbenchRequest} from '@/lib/workbench-api.mjs'
import {WorkbenchAttemptReport} from './WorkbenchAssessments'
import {WorkbenchInterviewReport,InterviewQuestionBasis} from './WorkbenchInterviewEvidence'
import {WorkbenchResumeDraft} from './WorkbenchResumeDraft'
import {WorkbenchResumeReport} from './WorkbenchResume'

export default function CompleteCaseReview({view,data,token,onNavigate,summary,initialRun='',initialResume='',initialInterview='',focusTopic=''}:any){
 const first=(data.assessment_runs??[]).find((r:any)=>r.run_id===initialRun)
 const [kind,setKind]=useState(first?.kind==='week'?'week':'day'),[id,setId]=useState(initialRun),[saved,setSaved]=useState<any>(null),[error,setError]=useState(''),[tab,setTab]=useState('dialogue')
 const runs=(data.assessment_runs??[]).filter((r:any)=>view==='retest'?r.kind==='retest':r.kind===kind)
 const chosen=id||(view==='scenario'?initialInterview||summary?.interview_id||data.interviews?.[0]?.interview_id:view==='resume'?initialResume||summary?.final_resume_id||data.resume_reports?.[0]?.resume_id:(view==='retest'&&focusTopic?runs.find((r:any)=>r.topic_id===focusTopic||r.topic_keys?.includes(focusTopic))?.run_id:null)||runs[0]?.run_id)
 useEffect(()=>{let active=true;setSaved(null);setError('');if(!chosen)return
  const path=view==='scenario'?'interview?interview_id=':view==='resume'?'resume?resume_id=':'assessment?run_id='
  workbenchRequest(path+chosen,token).then((v:any)=>{if(active)setSaved(v)}).catch((e:Error)=>{if(active)setError(e.message)})
  return()=>{active=false}
 },[chosen,token,view])
 const interview=saved?.interview,run=saved?.run
 return <div className="complete-case-review">
 {error&&<p role="alert" className="multi-error">{error}</p>}
 {(view==='exam'||view==='retest')&&<><Card className="multi-card"><h2>{view==='retest'?'按专题查看完整复测':'每日与每周的完整考核'}</h2>{view==='exam'&&<div className="multi-actions"><Button variant={kind==='day'?'default':'outline'} onClick={()=>{setKind('day');setId('')}}>日考核</Button><Button variant={kind==='week'?'default':'outline'} onClick={()=>{setKind('week');setId('')}}>周考核</Button></div>}<p>{runs.length}份已保存记录，可查看题目、示例作答、反馈与参考解析。</p><label>选择记录<select value={chosen??''} onChange={e=>setId(e.target.value)}>{runs.map((r:any,i:number)=><option key={r.run_id} value={r.run_id}>{r.title} · 第{runs.length-i}次</option>)}</select></label></Card>{run&&<Card className="multi-card"><h2>{run.title}</h2><p>{run.answered_count}道已答题目 · {run.status==='completed'?'本次已完成':'记录已保存'}</p>{run.answers.map((a:any,i:number)=><details key={a.attempt_id} open={i===0}><summary>第{i+1}题 · 查看作答与解析</summary><WorkbenchAttemptReport attempt={a}/></details>)}<Button variant="outline" onClick={()=>onNavigate('growth')}>查看对应成长变化</Button></Card>}</>}
 {view==='scenario'&&interview&&<><Card className="multi-card"><h2>{interview.position.title}</h2><p>{interview.planned_main}个主问题 · 已回答{interview.answered_count??interview.turns.filter((t:any)=>t.role==='user').length}轮</p><div className="multi-actions"><Button variant={tab==='dialogue'?'default':'outline'} onClick={()=>setTab('dialogue')}>完整对话</Button><Button variant={tab==='report'?'default':'outline'} onClick={()=>setTab('report')}>面试复盘与参考思路</Button></div></Card>{tab==='dialogue'?<Card className="multi-card">{interview.turns.map((t:any)=><article className={'wbi-bubble '+(t.role==='user'?'from-user':'from-interviewer')} key={t.turn_id}><strong>{t.role==='user'?'案例中的回答':'岗位面试官'}</strong><p className="wbi-preserve">{t.text}</p>{t.role==='assistant'&&<InterviewQuestionBasis question={t} jd={data.diagnosis.audit.jd_items??[]} turns={interview.turns}/>}</article>)}</Card>:<Card className="multi-card"><WorkbenchInterviewReport report={interview.report} jd={data.diagnosis.audit.jd_items??[]} turns={interview.turns} onPlan={()=>onNavigate('resume')}/></Card>}</>}
 {view==='resume'&&saved?.report&&<><Card className="multi-card"><h2>学习与验证之后，简历发生了什么变化？</h2><p>原文、课程练习、答卷和面试记录共同构成案例中的修改依据。</p><WorkbenchResumeDraft resumeId={saved.resume_id} report={saved.report} name={data.candidate.display_name} onSource={(record:string)=>onNavigate('records',{record})}/></Card><Card className="multi-card"><WorkbenchResumeReport report={saved.report} showSuggested={false} onSource={(record:string)=>onNavigate('records',{record})}/></Card></>}
 {!saved&&!error&&<p role="status">正在打开完整案例记录…</p>}
 </div>
}
