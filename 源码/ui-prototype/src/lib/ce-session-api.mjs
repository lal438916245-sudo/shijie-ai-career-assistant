import {workbenchRequest,WorkbenchError} from './workbench-api.mjs'
const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v)
export async function openCEBudget(token,body,transport=fetch){
 const keys=['request_id','expected_revision','simulation_limit_micro_cny']
 if(!body||Object.keys(body).length!==3||!keys.every(k=>Object.hasOwn(body,k))||!uuid(body.request_id)||
   !Number.isInteger(body.expected_revision)||body.expected_revision<0||!Number.isInteger(body.simulation_limit_micro_cny)||body.simulation_limit_micro_cny<1||body.simulation_limit_micro_cny>100000000)
  throw new WorkbenchError('请确认有效的会话身份和本地模拟预算。','invalid')
 const value=await workbenchRequest('ce_budget_open',token,body,transport)
 if(value.mode!=='ce_local_rehearsal'||value.actual_model_cost!==0||value.external_network_allowed!==false||value.request_id!==body.request_id)
  throw new WorkbenchError('模拟预算来源或请求身份不符。','source')
 return value
}
export async function readCEBudget(token,transport=fetch){
 const value=await workbenchRequest('ce-budget',token,undefined,transport),budget=value.ce_budget
 if(budget!==null&&(!budget||budget.mode!=='ce_local_rehearsal'||budget.simulated!==true||budget.actual_model_cost!==0||!value.scope||!budget.scope||!['case_id','session_id','trace_id','plan_id'].every(k=>budget.scope[k]===value.scope[k])||
  !['limit_micro_cny','spent_simulated_micro_cny','held_unconsumed_micro_cny','consumed_unconfirmed_micro_cny','available_micro_cny','overrun_micro_cny','overspent_micro_cny'].every(k=>Number.isInteger(budget[k])&&budget[k]>=0)))
   throw new WorkbenchError('累计模拟预算内容不完整，不展示未核对金额。','source')
 return value
}
