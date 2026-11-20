import {useState} from 'react'
import {Card} from './ui/card'
import {Button} from './ui/button'
import type {ABFTarget} from './WorkbenchABFPreparation'
const amount=(n:number)=>(n/1000000).toFixed(6)
export default function WorkbenchSessionOperations({data,disabled,onPrepare,onOpenBudget}:{data:any;disabled:boolean;onPrepare:(target:ABFTarget)=>void;onOpenBudget:(limit:number)=>Promise<any>}){
 const [limit,setLimit]=useState('1'),[error,setError]=useState('')
 const b=data.session_runtime?null:data.ce_budget
 if(data.session_runtime&&(!data.diagnosis||data.published_version||data.personal_input?.curriculum_available===false||data.runtime_capabilities?.sponsored_gateway))return null
 return <Card className="multi-card" aria-label="SDK同会话操作区"><h2>下一步准备</h2><p>{data.session_runtime?'预览后确认执行，核对结果后保存。':'本地模拟，费用0元；核对结果后保存。'}</p>
 {!data.published_version&&<div className="multi-actions">
 {!data.diagnosis&&<Button disabled={disabled} onClick={()=>onPrepare({stage:'a_diagnosis',version:0})}>准备 A 岗位诊断</Button>}
 {data.diagnosis&&!data.plan&&data.personal_input?.curriculum_available!==false&&!data.runtime_capabilities?.sponsored_gateway&&<Button disabled={disabled} onClick={()=>onPrepare({stage:'b_plan',version:0})}>准备 B 学习草案</Button>}
 {data.plan&&<p>请到学习计划总览运行程序校验，查看每日安排后确认发布，无需 F 审查。</p>}
 </div>}
 {data.published_version&&!b&&!data.session_runtime&&<><h3>开始 C/E 前，冻结本会话模拟预算</h3><p>仅覆盖 C 出题/阅卷与 E 提问/复盘，不含 A/B/D。新建考核、换题与重启不清零。应在第一场考核或面试之前开启；不会追认已有固定练习。</p><label>模拟额度（元，不是真实调用授权）<input type="text" inputMode="decimal" value={limit} disabled={disabled} onChange={e=>setLimit(e.target.value)}/></label><Button disabled={disabled} onClick={async()=>{if(!/^\d{1,3}(\.\d{1,6})?$/.test(limit)||Number(limit)<=0||Number(limit)>100){setError('请输入大于0、不超过100元的模拟额度，最多6位小数。');return}setError('');try{await onOpenBudget(Math.round(Number(limit)*1000000))}catch(e){setError((e as Error).message)}}}>确认本地模拟预算（不调用模型）</Button>{error&&<p role="alert">{error}</p>}</>}
 {b&&<><h3>C/E 累计模拟预算</h3><div className="wb-call-metrics"><div><small>模拟上限</small><strong>¥{amount(b.limit_micro_cny)}</strong></div><div><small>已结算模拟消费</small><strong>¥{amount(b.spent_simulated_micro_cny)}</strong></div><div><small>剩余可用</small><strong>¥{amount(b.available_micro_cny)}</strong></div></div><progress max={b.limit_micro_cny} value={b.spent_simulated_micro_cny+b.held_unconsumed_micro_cny+b.consumed_unconfirmed_micro_cny}/><p>未消费预留 ¥{amount(b.held_unconsumed_micro_cny)} · 已消费但用量未知 ¥{amount(b.consumed_unconfirmed_micro_cny)}。以上均为模拟值，实际模型费用 ¥0。失败/未知不清零，不自动重试。</p><details><summary>查看 {b.entries.length} 条授权预算明细</summary><ul>{b.entries.map((e:any)=><li key={e.authorization_id}>{e.stage} · {e.status} · 派发{e.dispatch_attempts}次 · {e.simulation_charge_micro_cny==null?'用量待确认':`模拟¥${amount(e.simulation_charge_micro_cny)}`}</li>)}</ul></details></>}
 </Card>
}
