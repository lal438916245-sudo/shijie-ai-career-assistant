import ModelResultSource from './ModelResultSource'
import {useEffect,useRef,useState} from 'react'
import {ShieldCheck} from 'lucide-react'
import {WorkbenchCandidateReview} from './WorkbenchCandidateReview'
import {cedCall} from '@/lib/ced-call-api.mjs'
import {createCedJournal,isCedTerminal,readCedEntry,stageNames} from '@/lib/ced-call-journal.mjs'
import {Button} from './ui/button'
import {usePendingEdits} from './WorkspaceQuality'
import {Dialog,DialogContent,DialogDescription,DialogHeader,DialogTitle} from './ui/dialog'
import './workbench-call-preparation.css'

export type CedTarget={stage:keyof typeof stageNames;targetId:string}
type Entry=CedTarget & {executionMode?:string;previewId:string;digest:string;authorizationId:string|null;executeRequested:boolean}
type Preview={session_runtime?:any;authorization_field?:string;execution_mode?:string;
  stage:CedTarget['stage'];target_id:string;preview_id:string;request_digest:string
  output_control?:{thinking_mode:string;max_output_tokens:number};request:Record<string,unknown>;expires_at:number;request_characters:number
  transport_kind?:string;max_output_tokens:number;estimated_input_tokens:number;estimated_cost:number|null;currency:string
  input_limit_exceeded:boolean;provider:string;configured_destination:string|null;transport_destination:string
  field_summary:{source_id:string;kind:string;usage:string;characters:number}[]
  context_fields:{name:string;characters:number}[];cost_notice:string
}
type Receipt={model_provenance?:any;session_runtime?:any;execution_mode?:string;
  authorization_id:string;preview_id:string;status:string;fixed_dispatch_attempts:number
  failure_guidance?:string;result:Record<string,unknown>|null;errors:{code:string;path:string}[];recoverable:boolean
}
const states:Record<string,string>={
  authorized:'已授权 · 待执行',dispatching:'执行结果待核对',response_saved:'原响应已保存 · 可本地恢复',
  completed:'候选结果已保存',failed_transport:'传输失败，原授权不重发',failed_validation:'候选响应未通过校验',
  unknown_outcome:'结果未知 · 本次授权已消费',expired:'授权已过期',invalidated:'授权已失效',
}

type Adoption={authorization_id:string;stage:string;candidate_digest:string;candidate:Record<string,any>;revision:number;stale:boolean;can_apply:boolean;blocked_reason?:string;application_id:string|null;record_id:string|null;formal_resume_id:string|null;selectable_item_ids:string[];notice:string}
export default function WorkbenchCallPreparation({token,revision,target,onClose,onApply,onOpenSaved,budget,onUpdated}:{
  token:string;revision:number;target:CedTarget|null;onClose:()=>void;budget?:any;onUpdated?:()=>Promise<any>
  onApply?:(extra:Record<string,unknown>)=>Promise<any>;onOpenSaved?:(result:any)=>void
}){
  const [openSaved,setOpenSaved]=useState(false)
  const [entry,setEntry]=useState<Entry|null>(null)
  const [preview,setPreview]=useState<Preview|null>(null)
  const [receipt,setReceipt]=useState<Receipt|null>(null)
  const [error,setError]=useState('')
  const [storageError,setStorageError]=useState('')
  const [busy,setBusy]=useState(false)
  const [ack,setAck]=useState(false)
  const [adoption,setAdoption]=useState<Adoption|null>(null)
  const [reviewed,setReviewed]=useState(false)
  const [selected,setSelected]=useState<string[]>([])
  const [applied,setApplied]=useState<any>(null)
  const flight=useRef(false)
  usePendingEdits('ced-call-preparation',busy)
  const session=preview?.session_runtime??receipt?.session_runtime
  const real=(session?.execution_mode??entry?.executionMode??budget?.execution_mode)==='real_model'
  const open=Boolean(target)||openSaved
  const operation=entry?.stage??target?.stage
  const activeReceipt=entry && receipt?.preview_id===entry.previewId && receipt.authorization_id===entry.authorizationId ? receipt : null

  const refreshEntry=()=>{
    try{
      const value=readCedEntry(localStorage,token) as Entry|null
      setEntry(value)
      setStorageError('')
    }catch(e){setStorageError((e as Error).message)}
  }
  useEffect(()=>{
    refreshEntry()
    window.addEventListener('storage',refreshEntry)
    return ()=>window.removeEventListener('storage',refreshEntry)
  },[token])

  const perform=async(action:()=>Promise<void>)=>{
    if(flight.current||storageError)return
    flight.current=true
    setBusy(true)
    setError('')
    try{await action()}catch(e){setError((e as Error).message)}
    finally{try{await onUpdated?.()}catch{}refreshEntry();flight.current=false;setBusy(false)}
  }
  const journal=()=>createCedJournal(localStorage,token)
  const close=()=>{
    if(flight.current)return
    setOpenSaved(false)
    setAdoption(null)
    setApplied(null)
    setReviewed(false)
    setPreview(null)
    setAck(false)
    setError('')
    onClose()
  }
  const readPreview=()=>perform(async()=>{
    if(!target||journal().read())return
    setAck(false)
    setPreview(null)
    const value=await cedCall('call_preview',token,{
      request_id:crypto.randomUUID(),expected_revision:revision,stage:target.stage,target_id:target.targetId,
    }) as Preview
    setPreview(value)
  })
  const authorize=()=>perform(async()=>{
    if(!preview||!ack||preview.input_limit_exceeded)return
    setReceipt(await journal().authorize(preview))
    setAck(false)
  })
  const recoverAuthorization=()=>perform(async()=>{
    if(entry&&!entry.authorizationId)setReceipt(await journal().recoverAuthorization(entry))
  })
  const step=(action:'call_execute'|'call_status'|'call_recover')=>perform(async()=>{
    if(!entry)return
    if(action==='call_execute'&&activeReceipt?.status!=='authorized')return
    setReceipt(await journal().step(action,entry))
  })
  const clear=()=>perform(async()=>{
    if(!entry)return
    await journal().clear(entry,activeReceipt)
    setReceipt(null)
    setPreview(null)
    setAck(false)
    setOpenSaved(false)
    setAdoption(null)
    setApplied(null)
    onClose()
  })

  const reviewCandidate=()=>perform(async()=>{
    if(!entry?.authorizationId)return
    const value=await cedCall('call_adoption_preview',token,{authorization_id:entry.authorizationId}) as Adoption
    setAdoption(value);setReviewed(false);setSelected([]);setApplied(null)
  })
  const applyCandidate=()=>perform(async()=>{
    if(!adoption||!reviewed||!onApply||!adoption.can_apply)return
    const value=await onApply({authorization_id:adoption.authorization_id,candidate_digest:adoption.candidate_digest,review_confirmed:true,selected_item_ids:selected})
    if(value){setApplied(value);setReviewed(false)}else setError('采用结果尚未确认，请在工作台查询原操作回执；不要重新提交。')
  })

  return <>
    {entry&&<div className="wb-call-recovery"><span>本会话最近一次调用准备 · {stageNames[entry.stage]}</span>
      <Button variant="outline" size="sm" onClick={()=>{refreshEntry();setOpenSaved(true)}}>查看或恢复调用回执</Button></div>}
    {storageError&&<p role="alert" className="multi-error">{storageError}</p>}
    <Dialog open={open} onOpenChange={next=>{if(!next)close()}}>
      <DialogContent className="wb-call-dialog" showCloseButton={!busy}>
        <DialogHeader>
          <DialogTitle>模型调用准备 · {operation?stageNames[operation]:'本会话授权'}</DialogTitle>
          <DialogDescription>{real?'真实模型模式：发送资料和费用预留按本次预览确认，失败也可能计费；不会自动重试。':'本地模拟 · 费用0元，结果用于体验流程。'}</DialogDescription>
        </DialogHeader>
        {budget&&<p className="wb-call-note">本会话{budget.version==='session-runtime-v1'?'会话累计':'C/E模拟'}上限 ¥{(budget.limit_micro_cny/1000000).toFixed(6)} · 已结算 ¥{((budget.spent_micro_cny??budget.spent_simulated_micro_cny)/1000000).toFixed(6)} · 可用 ¥{(budget.available_micro_cny/1000000).toFixed(6)}。消费失败/未知仍占额，不随换题清零，{real?'实付待平台核对。':'实际费用为0。'}</p>}
        <p className="wb-call-note">预览、确认授权和单次执行是三个独立操作。候选通过合同后仍需单独核对采用，才会保存到同一会话。原始回执、原答卷与旧报告保留。</p>
        {(storageError||error)&&<p role="alert" className="multi-error">{storageError||error}</p>}
        {busy&&<p role="status">正在处理这一步，请稍候…</p>}
        {entry&&target&&(entry.stage!==target.stage||entry.targetId!==target.targetId)&&<p className="wb-call-note">本会话还有一份调用记录。请先核对并结束处理，再为当前目标预览。</p>}
        {!entry&&target&&!preview&&<Button disabled={busy||Boolean(storageError)} onClick={readPreview}>生成发送内容与费用预览<ShieldCheck size={16}/></Button>}
        {preview&&(!entry||entry.previewId===preview.preview_id)&&<>
          <div className="wb-call-metrics">
            <div><small>本次费用</small><strong>{real?'用量结算后核对':'¥0'}</strong></div>
            <div><small>按已配置模型单价参考估算</small><strong>{preview.estimated_cost===null?'暂无单价':preview.estimated_cost.toFixed(6)+' '+preview.currency}</strong></div>
            <div><small>请求大小</small><strong>{preview.request_characters.toLocaleString()} 字符</strong></div>
          </div>
          {preview.output_control&&<p>D输出控制：{preview.output_control.thinking_mode==='disabled'?'关闭思考':preview.output_control.thinking_mode==='low'?'低强度思考':'服务商默认（未核对专用参数）'} · 只返回局部修改JSON · 截断后停止，需重新预览授权。</p>}
          <p>输入约 {preview.estimated_input_tokens.toLocaleString()} tokens，输出上限 {preview.max_output_tokens.toLocaleString()} tokens。{preview.cost_notice}</p>
          <p>实际目标：{preview.transport_destination}。{preview.configured_destination&&`已配置地址（用于预览）：${preview.configured_destination}。`}</p>
          <p className="wb-muted">预览有效至 {new Date(preview.expires_at*1000).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai'})}（北京时间）。</p>
          {preview.input_limit_exceeded&&<p role="alert">完整内容超过已配置的输入上限，此预览无法授权。</p>}
          <details className="wb-call-disclosure"><summary>查看本次来源与用途</summary>
            <ul>{preview.field_summary.map(field=><li key={field.source_id}><code>{field.source_id}</code> · {field.kind} · {field.characters} 字符 · {field.usage}</li>)}</ul>
            <p className="wb-muted">上下文字段：{preview.context_fields.map(field=>field.name).join('、')}</p>
          </details>
          <details className="wb-call-disclosure" open={!entry}><summary>查看完整请求内容</summary>
            <pre>{JSON.stringify(preview.request,null,2)}</pre>
          </details>
          {!entry&&<><label className="wb-call-confirm"><input type="checkbox" checked={ack} disabled={busy||preview.input_limit_exceeded} onChange={e=>setAck(e.target.checked)}/>
            {real?'我已核对发送资料与本次费用预留，同意向该服务商单次调用。':'我已核对内容和费用，同意仅授权本地替身执行这一次操作。'}</label>
            <div className="multi-actions"><Button disabled={busy||!ack||preview.input_limit_exceeded} onClick={authorize}>确认单次授权</Button>
            <Button variant="outline" disabled={busy} onClick={readPreview}>重新预览</Button></div></>}
        </>}
        {entry&&<section className="wb-call-status">
          <h3>{activeReceipt?states[activeReceipt.status]??activeReceipt.status:entry.authorizationId?'已有授权 · 请查询回执':'授权回执待确认'}</h3>
          <ModelResultSource provenance={activeReceipt?.status==='completed'?activeReceipt.model_provenance:undefined}/>
          {activeReceipt&&<p>{real?'SDK派发':'本地替身执行'} {activeReceipt.fixed_dispatch_attempts} 次 · {real?'费用按冻结单价计入会话账本，实付待核对':'实际模型费用 ¥0'}</p>}
          {!entry.authorizationId&&<p>可用原预览找回同一授权。找回授权只读取或创建该授权，执行需另外确认。</p>}
          {entry.executeRequested&&!activeReceipt&&<p>已提交过执行请求。请先查询回执；本页面保留原授权编号。</p>}
          {entry.executeRequested&&activeReceipt?.status==='authorized'&&<p>服务暂未确认消费。请继续查询，或在授权过期后重新预览。</p>}
          {activeReceipt?.recoverable&&<p>恢复只处理原授权。如果原响应已保存，将从该响应完成校验；没有可确认响应时记录为结果未知。</p>}
          {activeReceipt?.failure_guidance&&<p role="status">{activeReceipt.failure_guidance}</p>}
          {!!activeReceipt?.errors?.length&&<ul>{activeReceipt.errors.map((item,index)=><li key={index}><code>{item.code}</code> · {item.path}</li>)}</ul>}
          {activeReceipt?.result&&<details className="wb-call-disclosure"><summary>查看已保存候选结果</summary><pre>{JSON.stringify(activeReceipt.result,null,2)}</pre></details>}
          {activeReceipt?.status==='completed'&&<Button variant="outline" disabled={busy} onClick={reviewCandidate}>核对候选并保存正式结果</Button>}
          {adoption&&<section className="wb-call-disclosure" aria-label="候选采用核对">
            <h3>核对后，保存到本会话</h3><p>{adoption.notice}</p>
            <WorkbenchCandidateReview stage={adoption.stage} candidate={adoption.candidate}/>
            <details><summary>核对完整候选字段</summary><pre>{JSON.stringify(adoption.candidate,null,2)}</pre></details>
            {adoption.stale&&!adoption.application_id&&<p role="alert">会话或目标已更新，这份候选不能覆盖当前结果。请保留回执，重新准备。</p>}
            {!adoption.can_apply&&!adoption.stale&&!adoption.application_id&&<p role="alert">{adoption.blocked_reason??'评分仍待复核，暂不保存为正式分数。'}</p>}
            {adoption.stage==='d_revision'&&!adoption.application_id&&adoption.candidate.items?.map((item:any)=><label className="wb-call-confirm" key={item.item_id}>
              <input type="checkbox" disabled={busy||!adoption.can_apply||!adoption.selectable_item_ids.includes(item.item_id)} checked={selected.includes(item.item_id)} onChange={event=>setSelected(event.target.checked?[...selected,item.item_id]:selected.filter(id=>id!==item.item_id))}/>
              采用这条修改 · {adoption.selectable_item_ids.includes(item.item_id)?'请本人核对原文、改写和支持材料':'无证据升级已拦截'}
            </label>)}
            {!adoption.application_id&&!applied&&<><label className="wb-call-confirm"><input type="checkbox" checked={reviewed} disabled={busy||!adoption.can_apply} onChange={event=>setReviewed(event.target.checked)}/>我已核对范围、原文与引用；确认将这份结果保存到当前会话。</label>
              <Button disabled={busy||!onApply||!reviewed||!adoption.can_apply||(adoption.stage==='d_revision'&&!selected.length)} onClick={applyCandidate}>确认采用并保存（不调用模型）</Button></>}
            {(applied||adoption.application_id)&&<><p role="status">正式结果已保存，原候选与旧记录保留。</p><Button variant="outline" onClick={()=>{setOpenSaved(false);onOpenSaved?.(applied??adoption)}}>查看已保存结果</Button></>}
          </section>}
          <div className="multi-actions">
            {!entry.authorizationId&&<Button disabled={busy} onClick={recoverAuthorization}>找回同一授权</Button>}
            {entry.authorizationId&&<Button variant="outline" disabled={busy} onClick={()=>step('call_status')}>查询原调用回执</Button>}
            {activeReceipt?.status==='authorized'&&!entry.executeRequested&&<Button disabled={busy} onClick={()=>step('call_execute')}>{real?'按本次真实授权执行一次':'单次执行本地替身（SDK）'}</Button>}
            {activeReceipt?.recoverable&&<Button disabled={busy} onClick={()=>step('call_recover')}>恢复原调用（不重发）</Button>}
            {(!entry.executeRequested||(activeReceipt&&isCedTerminal(activeReceipt.status)))&&
              <Button variant="ghost" disabled={busy} onClick={clear}>{applied||adoption?.application_id?'完成本步，保留结果':'结束处理，保留服务端回执'}</Button>}
          </div>
        </section>}
      </DialogContent>
    </Dialog>
  </>
}
