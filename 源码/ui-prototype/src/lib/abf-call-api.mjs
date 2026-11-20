import {isSessionCall} from './session-runtime-api.mjs'
import {workbenchRequest,WorkbenchError} from './workbench-api.mjs'
const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v)
const stages=new Set(['a_diagnosis','b_plan','f_review'])
const keys={abf_preview:['request_id','expected_revision','stage','target_version'],abf_authorize:['preview_id','request_digest','accept_fixed_only'],
 abf_execute:['authorization_id'],abf_status:['authorization_id'],abf_recover:['authorization_id'],abf_adoption_preview:['authorization_id'],
 abf_apply:['request_id','expected_revision','authorization_id','candidate_digest','review_confirmed']}
const sha=v=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v)
export async function abfCall(action,token,body,transport=fetch){
 const fields=action==='abf_authorize'&&body?.accept_session_once===true?['preview_id','request_digest','accept_session_once']:Object.hasOwn(keys,action)?keys[action]:null
 if(!fields||!body||Object.keys(body).length!==fields.length||!fields.every(k=>Object.hasOwn(body,k)))throw new WorkbenchError('A/B/F调用字段无效。','invalid')
 if(action==='abf_preview'||action==='abf_apply'){
  if(!uuid(body.request_id)||!Number.isInteger(body.expected_revision)||body.expected_revision<0)throw new WorkbenchError('A/B/F请求或版本身份无效。','invalid')
 }
 if(action==='abf_preview'){
  if(!stages.has(body.stage)||!Number.isInteger(body.target_version)||body.target_version<0||body.target_version>1000||
   (body.stage==='a_diagnosis'&&body.target_version!==0)||(body.stage==='f_review'&&body.target_version===0))throw new WorkbenchError('请选择有效阶段和计划版本。','invalid')
 }else if(action==='abf_authorize'){
  if(!uuid(body.preview_id)||!sha(body.request_digest)||(body.accept_fixed_only!==true&&body.accept_session_once!==true))throw new WorkbenchError('本批仅允许确认本地替身。','invalid')
 }else{
  if(!uuid(body.authorization_id))throw new WorkbenchError('A/B/F授权身份无效。','invalid')
  if(action==='abf_apply'&&(!sha(body.candidate_digest)||body.review_confirmed!==true))throw new WorkbenchError('请先核对候选，再明确确认采用。','invalid')
 }
 const value=await workbenchRequest(action,token,body,transport)
 if(!isSessionCall(value)&&(value.mode!=='abf_fixed_rehearsal'||value.external_network_allowed!==false||value.actual_model_cost!==0))throw new WorkbenchError('A/B/F来源或费用边界不符。','source')
 if(action==='abf_preview'?(value.stage!==body.stage||value.target_version!==body.target_version):action==='abf_authorize'?value.preview_id!==body.preview_id:
  action==='abf_apply'?value.request_id!==body.request_id:value.authorization_id!==body.authorization_id)throw new WorkbenchError('A/B/F回执与请求身份不符。','source')
 return value
}
