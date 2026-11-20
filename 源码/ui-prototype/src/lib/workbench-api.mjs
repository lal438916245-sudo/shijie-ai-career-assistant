import {isSessionRuntimeValue} from './session-runtime-api.mjs'
export class WorkbenchError extends Error{constructor(message,code='unavailable'){super(message);this.code=code}}
const tokenPattern=/^[0-9a-f]{64}$/
const writePaths=new Set(['create','create_personal','diagnosis','plan','review','adopt','publish','progress','learning_artifact','recover','assessment_start','retest_start','answer','assessment_next','assessment_end','interview_start','interview_answer','interview_end','resume_generate','resume_check','call_preview','call_authorize','call_execute','call_status','call_recover','call_adoption_preview','candidate_apply','abf_preview','abf_authorize','abf_execute','abf_status','abf_recover','abf_adoption_preview','abf_apply','ce_budget_open','session_runtime_open','saved_b_preview','saved_b_apply','plan_check','plan_confirm_publish','plan_prepare'])
const assessmentRead=path=>/^assessment\?run_id=RUN_[0-9a-f]{24}$/.test(path)||/^assessment-options\?kind=(day|week)&period_start=\d{4}-\d{2}-\d{2}&period_end=\d{4}-\d{2}-\d{2}$/.test(path)
const readPath=path=>/^resume\?resume_id=RESUME_[0-9a-f]{24}$/.test(path)||/^interview\?interview_id=INTERVIEW_[0-9a-f]{24}$/.test(path)||assessmentRead(path)||['template','state','records','ce-budget','session-budget'].includes(path)||/^plan\?version=[1-9][0-9]{0,3}$/.test(path)||/^learning\?task_id=TASK_[0-9a-f]{24}$/.test(path)||/^request\?request_id=[0-9a-f-]{36}$/.test(path)
/** @param {string} path @param {string|null} [token] @param {any} [body] @param {typeof fetch} [transport] */
export async function workbenchRequest(path,token=null,body=undefined,transport=fetch){
 if((body===undefined?!readPath(path):!writePaths.has(path))||(token!==null&&!tokenPattern.test(token))||(path!=='template'&&token===null))throw new WorkbenchError('工作台请求无效。','invalid')
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),['call_execute','abf_execute'].includes(path)?200000:15000)
 try{
  const options={cache:'no-store',signal:controller.signal,headers:{}}
  if(token)options.headers['X-CP-Session']=token
  if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(body)}
  const response=await transport('/api/live/workbench/'+path,options)
  let payload;try{payload=await response.json()}catch{throw new WorkbenchError('本机工作台未返回可用结果；请确认已启动工作流预览。',body===undefined?'unavailable':'uncertain')}
  if(!response.ok)throw new WorkbenchError(payload.error||'操作未完成，请重新读取会话。',response.status===403?'access':payload.code||'unavailable')
  const value=payload.data
  if(!isSessionRuntimeValue(value)&&(value?.source_kind!=='competition_workbench_double'||value.run_mode!=='demo'||value.simulated!==true||value.real_dispatch_enabled!==false||value.model_requests!==0))throw new WorkbenchError('结果来源或调用边界不符，已停止展示。','source')
  return value
 }catch(error){if(error instanceof WorkbenchError)throw error;throw new WorkbenchError(body===undefined?'无法连接工作台，请确认本机预览已启动，再重新读取。':'操作结果尚未确认，请先查询本次回执，不会自动重发。',body===undefined?'unavailable':'uncertain')}
 finally{clearTimeout(timer)}
}
