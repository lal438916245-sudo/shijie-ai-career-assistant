import test from 'node:test'
import assert from 'node:assert/strict'
import {isSessionRuntimeValue,isSessionCall} from '../src/lib/session-runtime-api.mjs'
import {workbenchRequest} from '../src/lib/workbench-api.mjs'
import {abfCall} from '../src/lib/abf-call-api.mjs'
import {cedCall} from '../src/lib/ced-call-api.mjs'
import {createAbfJournal,readAbfEntry} from '../src/lib/abf-call-journal.mjs'
import {createCedJournal,readCedEntry} from '../src/lib/ced-call-journal.mjs'
const token='a'.repeat(64),id='12345678-1234-4234-8234-123456789012',digest='b'.repeat(64)
const scope={case_id:'test',session_id:'session',trace_id:'trace',plan_id:'plan'}
function value(stage='a_diagnosis',real=false){return {source_kind:'competition_workbench_session',scope,run_mode:real?'real':'demo',mode:real?'session_real_model':'session_sdk_rehearsal',simulated:!real,real_dispatch_enabled:false,model_requests:real?null:0,execution_mode:real?'real_model':'local_sdk_rehearsal',authorization_field:'accept_session_once',session_runtime:{scope,version:'session-runtime-v1',execution_mode:real?'real_model':'local_sdk_rehearsal',simulated:!real,policy_digest:digest},stage,preview_id:id,authorization_id:id,request_digest:digest,target_version:0,target_id:'RUN_'+('a'.repeat(24)),status:'authorized',consumed:false}}
const ok=data=>({ok:true,json:async()=>({data})})
test('session source guard accepts explicit modes and rejects forged/missing scope or mixed markers',async()=>{
 for(const real of [false,true])assert.ok(isSessionCall(value('a_diagnosis',real)))
 for(const patch of [{session_runtime:null},{run_mode:'real'},{simulated:false},{scope:{...scope,session_id:'wrong'}},{model_requests:7}]){
  const v={...value(),...patch};assert.equal(isSessionRuntimeValue(v),false)
  await assert.rejects(workbenchRequest('state',token,undefined,async()=>ok(v)),e=>e.code==='source')
 }
})
test('new ABF/CED single confirmation is exact and legacy dual acknowledgement cannot silently pass',async()=>{
 const body={preview_id:id,request_digest:digest,accept_session_once:true}
 assert.equal((await abfCall('abf_authorize',token,body,async()=>ok(value()))).mode,'session_sdk_rehearsal')
 assert.equal((await cedCall('call_authorize',token,body,async()=>ok(value('c_question',true)))).mode,'session_real_model')
 for(const fn of [abfCall,cedCall])await assert.rejects(fn(fn===abfCall?'abf_authorize':'call_authorize',token,{...body,accept_fixed_only:true},async()=>assert.fail('must not send')),e=>e.code==='invalid')
})
test('both journals retain execution mode and recover the same authorization without legacy consent',async()=>{
 for(const [factory,read,stage] of [[createAbfJournal,readAbfEntry,'a_diagnosis'],[createCedJournal,readCedEntry,'c_question']]){
  const map=new Map(),storage={getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)}
  const calls=[];const p=value(stage,true)
  if(stage==='a_diagnosis')p.target_id='0'
  const journal=factory(storage,token,async(action,t,body)=>{calls.push({action,body});return p},async fn=>fn())
  await journal.authorize(p)
  assert.deepEqual(calls[0].body,{preview_id:id,request_digest:digest,accept_session_once:true})
  assert.equal(read(storage,token).executionMode,'real_model')
  await journal.step(stage==='a_diagnosis'?'abf_status':'call_status',read(storage,token))
  assert.equal(calls.length,2)
 }
})
