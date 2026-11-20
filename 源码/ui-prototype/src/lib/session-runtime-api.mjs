export function isSessionRuntimeValue(v){
 const r=v?.session_runtime
 return v?.source_kind==='competition_workbench_session'&&r?.version==='session-runtime-v1'&&
 ['real_model','local_sdk_rehearsal'].includes(r.execution_mode)&&
 typeof v.simulated==='boolean'&&typeof v.real_dispatch_enabled==='boolean'&&
 (r.execution_mode==='real_model'?v.run_mode==='real':v.run_mode==='demo'&&v.simulated===true&&v.real_dispatch_enabled===false)&&
 ['case_id','session_id','trace_id','plan_id'].every(k=>typeof v.scope?.[k]==='string'&&v.scope[k]===r.scope?.[k])&&
 (v.simulated?v.model_requests===0:v.model_requests===null)
}
export function isSessionCall(v){return isSessionRuntimeValue(v)&&v.authorization_field==='accept_session_once'&&
 /^[0-9a-f]{64}$/.test(v.session_runtime.policy_digest)&&
 typeof v.session_runtime.simulated==='boolean'&&v.session_runtime.simulated===v.simulated&&
 (v.execution_mode==='real_model'?v.mode==='session_real_model':v.mode==='session_sdk_rehearsal')}
