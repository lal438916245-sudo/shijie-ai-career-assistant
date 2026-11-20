import {useEffect,useState} from 'react'
import {Card} from './ui/card'
import {Button} from './ui/button'
import {workbenchRequest} from '@/lib/workbench-api.mjs'

type Report={can_publish:boolean;plan_digest:string;validation_digest:string;notice:string;checks:{code:string;label:string;passed:boolean;detail:any}[]}
export default function WorkbenchPlanConfirmation({token,version,planDigest,tasks,historical,published,disabled,onConfirm}:{token:string;version:number;planDigest:string;tasks:{task_id:string;day:number;title:string;preparation:string;expected_outcome:string}[];historical:boolean;published:boolean;disabled:boolean;onConfirm:(extra:Record<string,any>)=>Promise<any>}){
 const [report,setReport]=useState<Report|null>(null),[ack,setAck]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('')
 useEffect(()=>{setReport(null);setAck(false);setError('')},[token,version,planDigest])
 const check=async()=>{setBusy(true);setError('');setAck(false);try{const value=await workbenchRequest('plan_check',token,{plan_version:version});if(value.plan_digest!==planDigest)throw Error('计划版本已变化，请重新读取会话。');setReport(value)}catch(e){setReport(null);setError((e as Error).message)}finally{setBusy(false)}}
 const confirm=async()=>{if(!report?.can_publish||!ack)return;setBusy(true);setError('');try{const r=await onConfirm({plan_version:version,plan_digest:report.plan_digest,validation_digest:report.validation_digest,review_confirmed:true});if(!r)throw Error('发布结果尚未确认，请查询页面上方原操作回执，不要重复发布。')}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return <Card className="multi-card wb-plan-confirm" aria-label="程序校验与计划发布"><span className="micro-label">CHECK · CONFIRM · LEARN</span><h2>{published?'已确认发布 · 可以开始学习':historical?'历史版本 · 只读查看':'查看安排，再确认发布'}</h2>
 <p>比赛版由程序检查任务与诊断绑定、每天最多60分钟、资料和学习卡是否齐全，再由你确认。F 智能审查已移至赛后路线图。</p>
 {published?<p>发布来源与确认依据可在成长记录查看。完成学习只记录进度，能力变化仍需独立答卷支持。</p>:historical?<p>请切回当前版本完成校验与确认。</p>:<>
 <p>先展开下方两周任务查看安排。确认后可打开每日详情，保存学习中、已完成或暂缓状态，也可调整日期。</p>
 <details><summary>发布前查看各日目标与起步条件</summary>{tasks.map(t=><section key={t.task_id}><h3>第 {t.day} 天 · {t.title}</h3><p>准备：{t.preparation}</p><p>交付：{t.expected_outcome}</p></section>)}</details>
 <Button variant="outline" disabled={disabled||busy} onClick={check}>{busy?'正在核对…':report?'重新运行程序校验（不调用模型）':'运行程序校验（不调用模型）'}</Button>
 {report&&<div aria-live="polite"><h3>{report.can_publish?'程序校验通过 · 待你确认':'暂未通过 · 草案保留'}</h3><ul>{report.checks.map(c=><li key={c.code}><strong>{c.passed?'✓':'待处理'} · {c.label}</strong><p>{Array.isArray(c.detail)?`${c.detail.length} 项学习任务材料已核对。`:c.detail}</p></li>)}</ul><p className="wb-muted">{report.notice}</p>
 <label className="wb-call-confirm"><input type="checkbox" checked={ack} disabled={disabled||busy||!report.can_publish} onChange={e=>setAck(e.target.checked)}/>我已查看计划，确认任务和起步条件适合自己，同意发布此版本开始学习。</label>
 <Button disabled={disabled||busy||!report.can_publish||!ack} onClick={confirm}>确认发布计划（不调用模型）</Button></div>}
 </>}{error&&<p role="alert">{error}</p>}
 </Card>
}
