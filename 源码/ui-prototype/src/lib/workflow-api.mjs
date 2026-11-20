// The service capability stays in the local Vite proxy. This token is a separate
// session credential and is never placed in the URL or logs. Legacy tab tokens
// can be imported explicitly into the persistent, browser-local session list.
export const WORKFLOW_TOKEN_KEY='career-pilot:workflow-double:token:v1'
export const WORKFLOW_DRAFT_KEY='career-pilot:workflow-double:draft:v1'
const tokenPattern=/^[0-9a-f]{64}$/
export class WorkflowError extends Error{constructor(message,code){super(message);this.code=code}}
export function readWorkflowToken(storage=sessionStorage){try{const value=storage.getItem(WORKFLOW_TOKEN_KEY);if(value===null)return null;if(!tokenPattern.test(value))throw Error('invalid');return value}catch{throw new WorkflowError('无法读取本标签页的会话身份，请检查浏览器存储；原有数据未被覆盖。','storage')}}
export function prepareWorkflowToken(storage=sessionStorage,random=crypto){const old=readWorkflowToken(storage);if(old)return old;const bytes=new Uint8Array(32);random.getRandomValues(bytes);const value=Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('');try{storage.setItem(WORKFLOW_TOKEN_KEY,value)}catch{throw new WorkflowError('无法保存会话身份，请检查浏览器存储。','storage')}return value}
export async function workflowRequest(path,token,body,transport=fetch){
 if(!['session','diagnosis','plan','recover','plan-progress'].includes(path)||!tokenPattern.test(token))throw new WorkflowError('会话请求无效。','invalid')
 const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),15000)
 try{const options={cache:'no-store',signal:controller.signal,headers:{'X-CP-Session':token}};if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(body)}
  const response=await transport('/api/live/'+path,options);let payload;try{payload=await response.json()}catch{throw new WorkflowError('工作流预览服务暂不可用，请确认服务已启动。','unavailable')}
  if(!response.ok)throw new WorkflowError(response.status===403?'本机服务访问状态失效，请确认工作流预览已启动，再重新读取。':payload.error||'请求未完成，请稍后重试。',response.status===403?'access':payload.code||'unavailable')
  if(payload.data?.source_kind!=='local_workflow_double')throw new WorkflowError('结果来源无法确认，已停止展示。','source')
  return payload.data
 }catch(error){if(error instanceof WorkflowError)throw error;if(error?.name==='AbortError')throw new WorkflowError('请求等待超时，结果尚未确认；请先重新读取已保存状态，再决定是否重试。','uncertain');throw new WorkflowError('无法连接本机工作流预览服务，请确认服务已启动，再重新读取。','unavailable')}finally{clearTimeout(timer)}
}

// Separate preparation responses never count as model output or call consent.
/** @param {string} path @param {string|null} [token] @param {any} [body] @param {typeof fetch} [transport] */
export async function preparationRequest(path,token=null,body=undefined,transport=fetch){
 if(!['model-config','call-preview'].includes(path)||(token!==null&&!tokenPattern.test(token)))throw new WorkflowError('准备请求无效。','invalid')
 const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),15000)
 try{
  const options={cache:'no-store',signal:controller.signal,headers:{}}
  if(token)options.headers['X-CP-Session']=token
  if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(body)}
  const response=await transport('/api/live/'+path,options);let payload
  try{payload=await response.json()}catch{throw new WorkflowError('本机配置服务暂不可用。','unavailable')}
  if(!response.ok)throw new WorkflowError(response.status===403?'本机服务访问失效，请检查预览服务。':payload.error||'准备未完成。',payload.code||'unavailable')
  if(payload.data?.source_kind!=='model_preparation_only'||payload.data.dispatch_enabled!==false||payload.data.authorized!==false)throw new WorkflowError('准备服务边界无法确认，已停止展示。','source')
  return payload.data
 }catch(error){if(error instanceof WorkflowError)throw error;throw new WorkflowError(error?.name==='AbortError'?'保存或预览结果未确认，请重新读取本机配置，不会自动重发。':'无法连接本机配置服务，请确认预览已启动。','unavailable')}finally{clearTimeout(timer)}
}

// Local-only one-use grants have a separate response domain from preparation.
/** @param {string} action @param {string} token @param {any} [body] @param {typeof fetch} [transport] */
export async function authorizedABRequest(action,token,body=undefined,transport=fetch){
 if(!['preview','authorize','execute','status','latest'].includes(action)||!tokenPattern.test(token))throw new WorkflowError('单次授权请求无效。','invalid')
 const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),15000)
 try{
  const options={cache:'no-store',signal:controller.signal,headers:{'X-CP-Session':token}}
  if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(body)}
  const response=await transport('/api/live/ab/'+action,options);let payload
  try{payload=await response.json()}catch{throw new WorkflowError('本机请求服务不可用，请先查询会话或授权状态。','unavailable')}
  if(!response.ok)throw new WorkflowError(response.status===403?'本机预览访问失效，请确认服务已启动。':payload.error||'单次请求未完成，请查询状态。',payload.code||'unavailable')
  if(payload.data?.source_kind!=='authorized_ab_double'||payload.data.mode!=='local_request_double'||payload.data.real_dispatch_enabled!==false)throw new WorkflowError('单次授权来源或执行边界不符，已停止展示。','source')
  return payload.data
 }catch(error){if(error instanceof WorkflowError)throw error;throw new WorkflowError('请求结果尚未确认，请先查询授权或会话状态；不会自动重发。','uncertain')}finally{clearTimeout(timer)}
}

/** @param {string} path @param {string|null} [token] @param {any} [body] @param {string|null} [mode] @param {typeof fetch} [transport] */
export async function sdkRequest(path,token=null,body=undefined,mode=null,transport=fetch){
 if(!['capabilities','session','diagnosis','plan','recover','plan-progress','ab/preview','ab/authorize','ab/execute','ab/status','ab/latest'].includes(path)||(token!==null&&!tokenPattern.test(token))||(mode!==null&&!['sdk_rehearsal','real_model'].includes(mode)))throw new WorkflowError('SDK 请求无效。','invalid')
 const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),15000)
 try{
  const options={cache:'no-store',signal:controller.signal,headers:{}}
  if(token)options.headers['X-CP-Session']=token
  if(mode)options.headers['X-CP-SDK-Mode']=mode
  if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(body)}
  const response=await transport('/api/sdk/'+path,options);let payload
  try{payload=await response.json()}catch{throw new WorkflowError('SDK 本机服务不可用，请确认已用 SDK 环境启动预览。','unavailable')}
  if(!response.ok)throw new WorkflowError(payload.error||'SDK 操作未完成，请先读取状态。',payload.code||'unavailable')
  const d=payload.data
  if(!d||!['sdk_rehearsal','real_model'].includes(d.mode)||(mode&&d.mode!==mode)||typeof d.real_dispatch_enabled!=='boolean'||typeof d.simulated!=='boolean'||!(d.mode==='sdk_rehearsal'?['sdk_ab_authorization','sdk_rehearsal_session']:['sdk_ab_authorization','real_model_session','real_mode_http_test_session']).includes(d.source_kind)||(d.mode==='sdk_rehearsal'&&(d.real_dispatch_enabled!==false||d.simulated!==true)))throw new WorkflowError('SDK 模式或数据来源不符，已停止展示。','source')
  return d
 }catch(error){if(error instanceof WorkflowError)throw error;throw new WorkflowError('SDK 操作结果未确认；请查询本栏会话或最近回执，不会自动重发。','uncertain')}finally{clearTimeout(timer)}
}
