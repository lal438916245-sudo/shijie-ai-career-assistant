import {isSessionCall} from './session-runtime-api.mjs'
import {workbenchRequest,WorkbenchError} from './workbench-api.mjs'
const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v)
const stages={c_question:/^RUN_[0-9a-f]{24}$/,c_grade:/^ATTEMPT_[0-9a-f]{24}$/,e_turn:/^INTERVIEW_[0-9a-f]{24}$/,e_report:/^INTERVIEW_[0-9a-f]{24}$/,d_revision:/^RESUME_[0-9a-f]{24}$/}
const keys={call_preview:['request_id','expected_revision','stage','target_id'],call_authorize:['preview_id','request_digest','accept_fixed_only'],call_execute:['authorization_id'],call_status:['authorization_id'],call_recover:['authorization_id'],call_adoption_preview:['authorization_id']}
/** Each invocation dispatches one endpoint only. Caller retains identities after uncertain outcomes. */
export async function cedCall(action,token,body,transport=fetch){
 const valid=action==='call_authorize'&&body?.accept_session_once===true?['preview_id','request_digest','accept_session_once']:Object.hasOwn(keys,action)?keys[action]:null
 if(!valid||!body||Object.keys(body).length!==valid.length||!valid.every(k=>k in body))throw new WorkbenchError('C/E/D调用准备字段无效。','invalid')
 if(action==='call_preview'){
  if(!uuid(body.request_id)||!Number.isInteger(body.expected_revision)||body.expected_revision<0||!Object.hasOwn(stages,body.stage)||!stages[body.stage].test(body.target_id))throw new WorkbenchError('请选择有效操作和本会话记录。','invalid')
 }else if(action==='call_authorize'){
  if(!uuid(body.preview_id)||!/^[0-9a-f]{64}$/.test(body.request_digest)||(body.accept_fixed_only!==true&&body.accept_session_once!==true))throw new WorkbenchError('本轮仅允许明确确认固定替身的一次请求。','invalid')
 }else if(!uuid(body.authorization_id))throw new WorkbenchError('单次授权身份无效。','invalid')
 const value=await workbenchRequest(action,token,body,transport)
 if(!isSessionCall(value)&&(value.mode!=='ced_fixed_rehearsal'||value.external_network_allowed!==false||value.actual_model_cost!==0))throw new WorkbenchError('C/E/D预演模式或费用边界不符。','source')
 if(action==='call_preview'?(value.stage!==body.stage||value.target_id!==body.target_id):action==='call_authorize'?value.preview_id!==body.preview_id:value.authorization_id!==body.authorization_id)throw new WorkbenchError('C/E/D回执与当前请求身份不一致。','source')
 return value
}
