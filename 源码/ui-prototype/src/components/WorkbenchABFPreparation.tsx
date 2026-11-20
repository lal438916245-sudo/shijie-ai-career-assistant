import ModelResultSource from './ModelResultSource'
import {useEffect,useRef,useState} from 'react'
import {abfCall} from '@/lib/abf-call-api.mjs'
import {createAbfJournal,readAbfEntry,isAbfTerminal,abfStageNames} from '@/lib/abf-call-journal.mjs'
import {usePendingEdits} from './WorkspaceQuality'
import {Button} from './ui/button'
import {Dialog,DialogContent,DialogDescription,DialogHeader,DialogTitle} from './ui/dialog'
import './workbench-call-preparation.css'

const labels:Record<string,string>=abfStageNames
export type ABFTarget={stage:'a_diagnosis'|'b_plan'|'f_review';version:number}
export default function WorkbenchABFPreparation({token,revision,target,onClose,onApply,onUpdated,budget}:{budget?:any;token:string;revision:number;target:ABFTarget|null;onClose:()=>void;onApply:(body:Record<string,unknown>)=>Promise<any>;onUpdated:()=>Promise<any>}){
 const [entry,setEntry]=useState<any>(null),[preview,setPreview]=useState<any>(null),[receipt,setReceipt]=useState<any>(null)
 const [adoption,setAdoption]=useState<any>(null),[ack,setAck]=useState(false),[reviewed,setReviewed]=useState(false)
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[storageError,setStorageError]=useState(''),[savedOpen,setSavedOpen]=useState(false)
 const flight=useRef(false);usePendingEdits('abf-call-preparation',busy)
 const refresh=()=>{try{setEntry(readAbfEntry(localStorage,token));setStorageError('')}catch(e){setStorageError((e as Error).message)}}
 useEffect(()=>{refresh();window.addEventListener('storage',refresh);return()=>window.removeEventListener('storage',refresh)},[token])
 const perform=async(fn:()=>Promise<any>)=>{if(flight.current||storageError)return;flight.current=true;setBusy(true);setError('');try{await fn()}catch(e){setError((e as Error).message)}finally{try{await onUpdated()}catch{}refresh();flight.current=false;setBusy(false)}}
 const journal=()=>createAbfJournal(localStorage,token)
 const session=preview?.session_runtime??receipt?.session_runtime
 const real=(session?.execution_mode??entry?.executionMode??budget?.execution_mode)==='real_model'
 const active=entry&&receipt?.authorization_id===entry.authorizationId&&receipt?.preview_id===entry.previewId?receipt:null
 const previousCalls=(budget?.entries??[]).filter((r:any)=>r.family==='abf'&&r.stage!=='f_review'&&/^\d+$/.test(r.slot_key)&&r.authorization_id!==entry?.authorizationId).slice(-3)
 const restoreSaved=(r:any)=>perform(async()=>{const value=await journal().restoreStoredReceipt({stage:r.stage,version:Number(r.slot_key)},r.authorization_id);setReceipt(value);setPreview(null);setAdoption(null);setSavedOpen(true)})
 const close=()=>{if(flight.current)return;setPreview(null);setReceipt(null);setAdoption(null);setAck(false);setReviewed(false);setSavedOpen(false);onClose()}
 const previewRequest=()=>perform(async()=>{if(!target||entry)return;const p=await abfCall('abf_preview',token,{request_id:crypto.randomUUID(),expected_revision:revision,stage:target.stage,target_version:target.version});setPreview(p);setAck(false);await onUpdated()})
 const step=(op:string)=>perform(async()=>{if(entry)setReceipt(await journal().step(op,entry))})
 return <>
 {entry&&<div className="wb-call-recovery"><span>本会话模型调用回执（含历史） · {labels[entry.stage]}</span><Button variant="outline" onClick={()=>setSavedOpen(true)}>查询或恢复原调用</Button></div>}
 {previousCalls.map((r:any)=><div className="wb-call-recovery" key={r.authorization_id}><span>{labels[r.stage]} · 已保存的原调用</span><Button variant="outline" disabled={busy||Boolean(storageError)} onClick={()=>restoreSaved(r)}>找回原回执（不调用模型）</Button></div>)}
 {storageError&&<p role="alert">{storageError}</p>}
 <Dialog open={Boolean(target)||savedOpen} onOpenChange={v=>{if(!v)close()}}><DialogContent className="wb-call-dialog" showCloseButton={!busy}>
 <DialogHeader><DialogTitle>{labels[entry?.stage??target?.stage]??'A/B'} · 调用准备</DialogTitle><DialogDescription>{real?'真实模型模式：将按本次预览发送资料，单次授权后才可执行；受会话累计额度控制。':'本地模拟 · 费用0元，结果用于体验流程。'}</DialogDescription></DialogHeader>
 <p>预览、单次授权、执行、核对采用分别确认。首次预览后本会话进入候选流程，原固定生产按钮不再混用；结果来源以每次回执为准；输入来源以当前会话标注为准。</p>
 {(error||storageError)&&<p role="alert" className="multi-error">{error||storageError}</p>}{busy&&<p role="status">正在处理，请稍候…</p>}
 {entry&&target&&(entry.stage!==target.stage||entry.targetId!==String(target.version))&&<p>本机会话仍有上一次授权入口，请先查询并结束处理；正式回执和采用结果会保留，再预览当前目标。</p>}
 {!entry&&target&&!preview&&<Button disabled={busy||Boolean(storageError)} onClick={previewRequest}>生成发送内容与费用预览</Button>}
 {preview&&!entry&&<>
 <div className="wb-call-metrics"><div><small>本次实际模型费用</small><strong>{real?'用量结算后核对':'¥0'}</strong></div><div><small>按配置单价的参考估算</small><strong>{preview.estimated_cost==null?'暂无单价':`¥${preview.estimated_cost.toFixed(6)}`}</strong></div><div><small>保守输入预留＋输出上限</small><strong>{preview.configured_cost_ceiling==null?'暂无单价':`¥${preview.configured_cost_ceiling.toFixed(6)}`}</strong></div></div>
 <p>{preview.request_characters} 字符 · 输出上限 {preview.max_output_tokens??'按本地合同'} tokens。参考估算和预留不是账单；{real?'失败可能计费，实际账单待平台核对。':'本轮不产生真实费用。'}{session?'本次已计入会话共同额度（含历史费用）；授权时预留，失败或用量未知不清零。':'累计模拟预算仅覆盖后续 C/E。'}</p>
 <p>{preview.transport_destination??'进程内固定替身，无外网'}。{preview.configured_destination&&`已配置服务商地址（本轮不访问）：${preview.configured_destination}`}</p>
 {preview.input_limit_exceeded&&<p role="alert">完整内容超过配置输入上限，不能授权。请精简内容或在本机设置中明确调整，之后重新预览。</p>}
 <details className="wb-call-disclosure" open><summary>核对实际发送的完整内容</summary><pre>{JSON.stringify(preview.request,null,2)}</pre></details>
 <label className="wb-call-confirm"><input type="checkbox" checked={ack} disabled={busy||preview.input_limit_exceeded} onChange={e=>setAck(e.target.checked)}/>{real?'我已核对发送资料与本次费用预留，同意向该服务商单次调用。':'我已核对本次发送内容，同意仅对本地 HTTP 替身授权一次。'}</label>
 <Button disabled={busy||!ack||preview.input_limit_exceeded} onClick={()=>perform(async()=>{setReceipt(await journal().authorize({...preview,target_id:String(preview.target_version)}));setAck(false)})}>确认单次授权</Button>
 </>}
 {entry&&<section className="wb-call-status">{entry.stage==='f_review'&&<p>历史 F 实验回执：已移出比赛主流程，不作为计划发布前置条件。保留查询与原响应恢复，不新增执行或采用。</p>}<h3>{active?({authorized:'已授权，待单次执行',completed:'候选已保存，待核对采用',response_saved:'响应已保存，可本地恢复',failed_transport:'请求失败，原授权不重发',failed_validation:'候选校验未通过',dispatching:'结果待确认，不重发',unknown_outcome:'结果未知，本次授权已消费，禁止重发',invalidated:'授权已失效',expired:'授权已过期'} as Record<string,string>)[active.status]??active.status:'请查询原调用回执'}</h3>
 {active&&<p>{real?'SDK派发':'SDK本地派发'} {active.dispatch_attempts} 次 · {real?'按用量与冻结单价计入累计额度，账单待核对':'实际费用 ¥0'}</p>}
 <ModelResultSource provenance={active?.status==='completed'?active.model_provenance:undefined}/>
 {!!active?.errors?.length&&<ul>{active.errors.map((e:any,i:number)=><li key={i}>{e.requirement_number?`第${e.requirement_number}项：`:''}{e.message??e.code}</li>)}</ul>}
 <div className="multi-actions">{!entry.authorizationId?<Button disabled={busy} onClick={()=>perform(async()=>setReceipt(await journal().recoverAuthorization(entry)))}>找回同一授权</Button>:<Button variant="outline" disabled={busy} onClick={()=>step('abf_status')}>查询原回执</Button>}
 {entry.stage!=='f_review'&&active?.status==='authorized'&&!entry.executeRequested&&<Button disabled={busy} onClick={()=>step('abf_execute')}>{real?'按本次真实授权执行一次':'单次执行 SDK 本地替身'}</Button>}
 {active?.status==='response_saved'&&<Button disabled={busy} onClick={()=>step('abf_recover')}>从原响应恢复（不重发）</Button>}
 {entry.stage!=='f_review'&&active?.status==='completed'&&<Button disabled={busy} onClick={()=>perform(async()=>{setAdoption(await abfCall('abf_adoption_preview',token,{authorization_id:entry.authorizationId}));setReviewed(false)})}>核对候选与来源</Button>}
 {(!entry.executeRequested||active&&isAbfTerminal(active.status))&&<Button variant="ghost" disabled={busy} onClick={()=>perform(async()=>{await journal().clear(entry,active);setReceipt(null);setPreview(null);setAdoption(null);setSavedOpen(false);onClose()})}>{adoption?.already_applied?'完成本步，保留结果':'结束处理，保留服务端回执'}</Button>}</div>
 {adoption&&entry?.stage!=='f_review'&&<section className="wb-call-disclosure"><h3>正式采用前核对</h3><p>{adoption.notice}</p><pre>{JSON.stringify(adoption.candidate,null,2)}</pre>
 {!adoption.can_apply&&!adoption.already_applied&&<p role="alert">候选待复核、来源已变化或该目标已有正式结果，不能覆盖。</p>}
 {adoption.already_applied?<p role="status">已正式保存到同一会话，无需再次采用。</p>:<><label className="wb-call-confirm"><input type="checkbox" checked={reviewed} disabled={busy||!adoption.can_apply} onChange={e=>setReviewed(e.target.checked)}/>我已核对输入、结论和引用，确认采用{real?'本次模型':'本地演练'}结果。</label><Button disabled={busy||!reviewed||!adoption.can_apply} onClick={()=>perform(async()=>{const r=await onApply({authorization_id:entry.authorizationId,candidate_digest:adoption.candidate_digest,review_confirmed:true});if(!r)throw Error('采用结果未确认，请查询工作台原操作回执，不要重复提交。');setAdoption(await abfCall('abf_adoption_preview',token,{authorization_id:entry.authorizationId}));setReviewed(false)})}>确认采用并正式保存（不调用模型）</Button></>}
 </section>}
 </section>}
 </DialogContent></Dialog>
 </>
}
