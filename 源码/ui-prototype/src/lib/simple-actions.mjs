import {workbenchRequest} from './workbench-api.mjs'
import {abfCall} from './abf-call-api.mjs'
import {cedCall} from './ced-call-api.mjs'
import {withWorkbenchLock} from './workbench-sessions.mjs'

const finalStates=new Set(['completed','failed_validation','failed_transport','unknown_outcome','invalidated','expired'])
const sameTarget=(r,stage,target)=>r.stage===stage&&(stage==='a_diagnosis'?r.target_version===Number(target):r.target_id===target)
export function createSimpleActions({token,storage,request=workbenchRequest,abf=abfCall,ced=cedCall,uuid=()=>crypto.randomUUID(),lock=withWorkbenchLock}){
 const base='shijie:normal-flow:v1:'+token
 const read=k=>{try{return JSON.parse(storage.getItem(k)??'null')}catch{throw Error('本机操作记录不可读，请保留资料后联系维护者。')}}
 const write=(k,v)=>{try{storage.setItem(k,JSON.stringify(v))}catch{throw Error('无法保存操作进度，已停止发送。')}}
 const state=()=>request('state',token)
 async function mutate(op,extra={}){
  const key=base+':save',old=read(key)
  if(old){
   if(old.op===op&&old.extra!==JSON.stringify(extra))throw Error('上次保存尚未确认，当前草稿已保留。请先恢复原结果。')
   const recovered=await request('request?request_id='+old.body.request_id,token)
   if(recovered.found){storage.removeItem(key);if(old.op===op)return recovered.receipt}
   else if(old.op!==op)throw Error('上次保存结果尚未确认，请先继续原操作。')
  }
  const current=await state()
  const body=old?.op===op?old.body:{request_id:uuid(),expected_revision:current.revision,...extra}
  write(key,{op,body,extra:JSON.stringify(extra)})
  try{const result=await request(op,token,body);storage.removeItem(key);return result}
  catch(e){if(['invalid','conflict','validation','not_found'].includes(e.code))storage.removeItem(key);throw e}
 }
 async function ready(){
  let s=await state()
  if(s.session_runtime){if(s.session_runtime.execution_mode!=='real_model')throw Error('这是历史本地演练。原记录可继续查看，请新建求职准备使用AI服务。');return s}
  const cap=s.runtime_capabilities
  if(!cap?.outbound_enabled||!cap.model_configured)throw Error('AI服务暂不可用，你的资料已保留。可以稍后继续，或先查看完整案例。')
  await mutate('session_runtime_open',{execution_mode:'real_model',budget_micro_cny:cap.sponsored_gateway?.session_budget_micro_cny??1000000})
  return state()
 }
 async function invoke(stage,target){
  let s=await ready()
  const isA=stage==='a_diagnosis',call=isA?abf:ced,prefix=isA?'abf':'call'
  const key=base+':model:'+stage+':'+target
  let memo=read(key),receipt=null
  const configRevision=s.runtime_capabilities?.config_revision
  if(memo&&!memo.executeRequested&&typeof configRevision==='number'&&memo.configRevision!==configRevision){storage.removeItem(key);memo=null}
  // Recover from durable server records even if the old browser preparation UI was cleared.
  for(const entry of [...(s.session_runtime?.entries??[])].reverse()){
   if(entry.stage!==stage||entry.status==='released_unconsumed')continue
   const existing=await call(prefix+'_status',token,{authorization_id:entry.authorization_id})
   if(sameTarget(existing,stage,target)){receipt=existing;break}
  }
  if(!receipt&&memo?.authorizationId)receipt=await call(prefix+'_status',token,{authorization_id:memo.authorizationId})
  if(receipt?.status==='authorized'&&typeof configRevision==='number'&&receipt.config_revision!==configRevision){storage.removeItem(key);memo=null;receipt=null}
  if(!receipt){
   if(!memo){
    const preview=await call(prefix+'_preview',token,{request_id:uuid(),expected_revision:s.revision,stage,...(isA?{target_version:Number(target)}:{target_id:target})})
    if(preview.input_limit_exceeded)throw Error('资料超过本次处理上限，请适当精简后再生成。')
    memo={stage,target,configRevision,previewId:preview.preview_id,digest:preview.request_digest,authorizationId:null,executeRequested:false}
    write(key,memo)
   }
   receipt=await call(prefix+'_authorize',token,{preview_id:memo.previewId,request_digest:memo.digest,accept_session_once:true})
   memo={...memo,authorizationId:receipt.authorization_id};write(key,memo)
  }
  if(!sameTarget(receipt,stage,target))throw Error('保存结果与当前资料不一致，已停止操作。')
  if(receipt.status==='authorized'){
   if(memo?.executeRequested)throw Error('上次生成结果尚未确认。已保留原请求，请稍后继续查看，不会重复发送。')
   memo={...memo,stage,target,authorizationId:receipt.authorization_id,executeRequested:true};write(key,memo)
   receipt=await call(prefix+'_execute',token,{authorization_id:receipt.authorization_id})
  }
  if(receipt.status==='response_saved')receipt=await call(prefix+'_recover',token,{authorization_id:receipt.authorization_id})
  if(receipt.status!=='completed'){
   const detail=receipt.errors?.map(e=>e.message??({'positive_evidence_required':'部分引用与结论不一致，结果已保留待复核。','sponsor_budget_exhausted':'体验服务额度已用完。'}[e.code]??'返回结果需要复核。')).join('；')
   throw Error(detail||'本次结果仍待确认，原请求与资料已保留，不会自动重复调用。')
  }
  const adoption=await call(prefix+'_adoption_preview',token,{authorization_id:receipt.authorization_id})
  return {receipt,adoption}
 }
 async function apply(result,selected=[]){
  const {receipt,adoption}=result
  if(adoption.already_applied||adoption.application_id)return adoption.application??adoption
  if(!adoption.can_apply)throw Error('这份结果需要补充核对，已保留原文，不覆盖已有结果。')
  return mutate(receipt.stage==='a_diagnosis'?'abf_apply':'candidate_apply',{
   authorization_id:receipt.authorization_id,candidate_digest:adoption.candidate_digest,review_confirmed:true,
   ...(receipt.stage==='a_diagnosis'?{}:{selected_item_ids:selected})
  })
 }
 return {
  state,mutate,
  diagnosis:()=>lock(async()=>{const result=await invoke('a_diagnosis',0);await apply(result);return state()}),
  resume:()=>lock(async()=>{
   const s=await ready();if(!s.diagnosis)throw Error('请先完成岗位诊断。')
   // Reopen the same pending base instead of charging again after a refresh.
   const key=base+':resume-base';let saved=read(key)
   const evidence=JSON.stringify({interviews:(s.interviews??[]).map(i=>[i.interview_id,i.status,i.answered_count]),assessments:(s.assessment_runs??[]).map(i=>[i.run_id,i.status,i.answered_count]),progress:s.progress??[]})
   if(!saved||saved.evidence!==evidence){saved={...await mutate('resume_generate'),evidence};write(key,saved)}
   return {...await invoke('d_revision',saved.resume_id),baseId:saved.resume_id}
  }),
  saveResume:(result,selected)=>lock(()=>apply(result,selected)),
  startInterview:()=>lock(async()=>{
   const s=await ready();if(!s.diagnosis)throw Error('请先完成岗位诊断。')
   let interview=s.interviews?.find(i=>i.status==='active')
   if(!interview)interview=await mutate('interview_start',{mode:'short',include_learning_evidence:false})
   const iid=interview.interview_id
   const result=await invoke('e_turn',iid);await apply(result)
   return request('interview?interview_id='+iid,token)
  }),
  answerInterview:(iid,questionId,answer)=>lock(async()=>{
   const current=await request('interview?interview_id='+iid,token)
   if(current.interview.status==='active')await mutate('interview_answer',{interview_id:iid,question_turn_id:questionId,answer})
   const result=await invoke('e_report',iid);await apply(result)
   return request('interview?interview_id='+iid,token)
  })
 }
}

export function resumePreview(original,items,chosen){
 const points=Array.from(original),edits=items.filter(i=>chosen.includes(i.item_id)).sort((a,b)=>a.original_ref.start-b.original_ref.start)
 let cursor=0,text=''
 for(const item of edits){const ref=item.original_ref
  if(ref.source_id!=='resume_original'||ref.start<cursor||points.slice(ref.start,ref.end).join('')!==ref.quote)throw Error('修改位置需要重新核对，未覆盖原文。')
  text+=points.slice(cursor,ref.start).join('')+item.proposed_text;cursor=ref.end
 }
 return text+points.slice(cursor).join('')
}
