import {useEffect,useState} from 'react'
import {Card} from './ui/card'
import {Button} from './ui/button'
const money=(v:number)=>(v/1000000).toFixed(6)
export default function SessionRuntimePanel({data,disabled,onOpen,onPrepare}:{data:any;disabled:boolean;onOpen:(mode:string,limit:number)=>Promise<any>;onPrepare:()=>void}){
 const [mode,setMode]=useState(data.runtime_capabilities?.sponsored_gateway?.version==='judge-gateway-v2'?'real_model':'local_sdk_rehearsal'),[amount,setAmount]=useState(String((data.runtime_capabilities?.sponsored_gateway?.session_budget_micro_cny??1000000)/1000000)),[ack,setAck]=useState(false),[error,setError]=useState('')
 const b=data.session_runtime,cap=data.runtime_capabilities,sponsor=cap?.sponsored_gateway
 const [touched,setTouched]=useState(false)
 const interviewEnabled=Boolean(sponsor?.supported_stages?.includes('e_report'))
 const sponsorScope=interviewEnabled?'A/D及一轮短面试':'A/D'
 useEffect(()=>{if(sponsor?.version==='judge-gateway-v2'&&!touched&&!b){setMode('real_model');setAmount(String(sponsor.session_budget_micro_cny/1000000))}},[sponsor?.version,sponsor?.session_budget_micro_cny,touched,Boolean(b)])
 if(!b&&(data.abf||data.diagnosis))return null
 const open=async()=>{
  if(!/^\d{1,3}(\.\d{1,6})?$/.test(amount)||Number(amount)<=0||Number(amount)>100){setError('请输入大于0、不超过100元的额度，最多6位小数。');return}
  if(!ack)return
  setError('');try{await onOpen(mode,Math.round(Number(amount)*1000000))}catch(e){setError((e as Error).message)}
 }
 return <Card className="multi-card" id="session-runtime-panel" aria-label="会话模式与费用"><span className="micro-label">YOUR EXPERIENCE</span><h2>{b?'本会话额度':sponsor?'作者额度已就绪':'选择体验模式'}</h2>
 {!b?<>
 <p>{sponsor?`无需填写模型或API Key。作者承担${sponsorScope}费用，每次发送资料前仍需确认。`:'默认本地模拟，费用0元。真实模型需配置就绪，并在每次执行前授权。'}</p>
 <label>运行模式<select aria-label="会话运行模式" value={mode} disabled={disabled} onChange={e=>{setTouched(true);setMode(e.target.value);setAck(false)}}><option value="local_sdk_rehearsal">本地模拟 · 不调用模型 · 费用0元</option><option value="real_model" disabled={!cap?.outbound_enabled||cap?.model_configured===false}>{sponsor?'真实模型 · 作者额度（'+sponsorScope+'）':'真实模型 · 每次确认后单次调用'}{!cap?.outbound_enabled?'（未开放）':cap?.model_configured===false?'（配置未就绪）':''}</option></select></label>
 {sponsor?<p className="wb-muted">本会话预置上限 ¥{Number(amount).toFixed(2)}，所有评委共享服务端总额度。</p>:<label>{mode==='real_model'?'本会话累计额度（元）':'模拟累计额度（元）'}<input aria-label="会话累计额度" type="text" inputMode="decimal" value={amount} disabled={disabled} onChange={e=>setAmount(e.target.value)}/></label>}
 <p className="wb-muted">{mode==='real_model'?(sponsor?'资料将经作者网关发送至模型服务商。':'资料将按每次预览发送至配置的模型服务商，失败也可能计费。'):'模拟结果用于体验操作，不评价你的实际能力。'}</p>
 <details className="wb-binding-details"><summary>模型配置与额度规则</summary><p>{cap?.model_configured?`${cap.provider} / ${cap.model}`:'真实模型尚未就绪，可先本地模拟。'}</p><p>保存模式和额度不发请求；确认后本会话不能切换、清零或扩额。按冻结单价预留，用量未知保留占额，平台实付另核对，不自动重试。</p>{sponsor&&<p>赞助有效期：{sponsor.expires_at}。评委无需填写服务商Key，其他工具可查看案例或本地模拟。</p>}</details>
 <label><input type="checkbox" checked={ack} disabled={disabled} onChange={e=>setAck(e.target.checked)}/>我已核对模式与额度，确认后本会话不再切换或重置。</label><Button disabled={disabled||!ack} onClick={open}>确认模式与额度（不调用模型）</Button>
 </>:<>
 <p>{b.simulated?'本地模拟 · 实际模型费用0元':'真实模型 · 每次授权后调用'}</p>
 <div className="wb-call-metrics"><div><small>{b.simulated?'模拟上限':'累计上限'}</small><strong>¥{money(b.limit_micro_cny)}</strong></div><div><small>{b.simulated?'已结算模拟值':'按用量计价'}</small><strong>¥{money(b.spent_micro_cny)}</strong></div><div><small>可再授权额度</small><strong>¥{money(b.available_micro_cny)}</strong></div></div>
 <progress max={b.limit_micro_cny} value={b.spent_micro_cny+b.held_unconsumed_micro_cny+b.consumed_unconfirmed_micro_cny}/>
 {(b.overrun_micro_cny>0||b.overspent_micro_cny>0)&&<p role="alert">用量或额度异常，已停止新增授权。请保留原回执核对账单。</p>}
 <details className="wb-binding-details"><summary>费用与调用记录 · {b.entries.length} 条</summary><p>未执行预留 ¥{money(b.held_unconsumed_micro_cny)} · 用量未知 ¥{money(b.consumed_unconfirmed_micro_cny)}。失败、换页和重启不清零，不自动重试。</p><p>{b.notice}</p><ul>{b.entries.map((e:any)=><li key={e.authorization_id}>{e.stage} · {e.simulated?'本地模拟':'真实模型'} · {e.status} · 派发{e.dispatch_attempts}次 · {e.charge_micro_cny==null?'用量待确认':`¥${money(e.charge_micro_cny)}`}</li>)}</ul></details>
 {!data.diagnosis&&<Button disabled={disabled} onClick={onPrepare}>准备 A 岗位诊断（先预览）</Button>}
 </>}{error&&<p role="alert">{error}</p>}
 </Card>
}
