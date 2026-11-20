import {useRef,useState} from 'react'
import {workbenchRequest} from '@/lib/workbench-api.mjs'
import {Card} from './ui/card'
import {Button} from './ui/button'

export default function WorkbenchSavedBRecovery({token,authorizationId,onApply}:{token:string;authorizationId:string;onApply:(body:Record<string,unknown>)=>Promise<any>}){
 const [preview,setPreview]=useState<any>(null),[checked,setChecked]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const flight=useRef(false)
 const perform=async(fn:()=>Promise<any>)=>{if(flight.current)return;flight.current=true;setBusy(true);setError('');try{await fn()}catch(e){setError((e as Error).message)}finally{flight.current=false;setBusy(false)}}
 return <Card className="multi-card"><h3>继续使用已保存的学习内容</h3><p>原 B 调用因时间安排超限未采用。可保留原学习内容，改用程序固定的每日60分钟；不重新调用模型，原失败记录和费用保留。</p>
 {error&&<p role="alert">{error}</p>}
 {!preview?<Button disabled={busy} onClick={()=>perform(async()=>{setPreview(await workbenchRequest('saved_b_preview',token,{authorization_id:authorizationId}));setChecked(false)})}>核对保存内容与时间调整</Button>:<>
 <p>{preview.notice}</p><p>{preview.source.simulated?'本地替身保存内容':'已保存的真实模型内容'} · {preview.source.provider} / {preview.source.model} · 原调用状态：校验未通过。</p>
 <p>每天固定：阅读20、必做25、复盘5、收尾10（选做或日考核择一）。学习内容经程序校验、用户确认后发布。</p>
 <details open><summary>查看各项时间调整</summary><ul>{preview.source.changes.map((t:any)=><li key={t.task_template_id}>{preview.candidate.plan.tasks.find((v:any)=>v.task_template_id===t.task_template_id)?.title}：{t.old_minutes} → {t.new_minutes} 分钟</li>)}</ul></details>
 <details><summary>核对全部学习内容</summary>{preview.candidate.plan.tasks.map((t:any)=><section key={t.task_id}><h4>第{t.day}天 · {t.title}</h4><p>从这里开始：{t.preparation}</p><p>交付：{t.expected_outcome}</p><p>依据：{t.gap_interpretation}</p></section>)}</details>
 {preview.already_applied?<p role="status">已正式保存，请重新读取学习计划。</p>:<><label className="ab-consent"><input type="checkbox" checked={checked} disabled={busy||!preview.can_apply} onChange={e=>setChecked(e.target.checked)}/>我已核对学习内容、原调用来源和程序时间，确认保存为待确认草案。</label><Button disabled={busy||!checked||!preview.can_apply} onClick={()=>perform(async()=>{const result=await onApply({authorization_id:authorizationId,derivation_digest:preview.derivation_digest,review_confirmed:true});if(!result)throw Error('保存结果未确认，请查询工作台原操作回执，不要重复提交。');setChecked(false)})}>确认采用保存内容（不调用模型）</Button></>}
 </>}
 </Card>
}
