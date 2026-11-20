import test from 'node:test'
import assert from 'node:assert/strict'
import {abfCall} from '../src/lib/abf-call-api.mjs'
import {addWorkbenchSession,patchWorkbenchSession,readWorkbenchRegistry} from '../src/lib/workbench-sessions.mjs'
import {webcrypto} from 'node:crypto'
const id='12345678-1234-1234-1234-123456789abc',token='b'.repeat(64),sha='c'.repeat(64)
const source={source_kind:'competition_workbench_double',run_mode:'demo',simulated:true,real_dispatch_enabled:false,model_requests:0,
 mode:'abf_fixed_rehearsal',external_network_allowed:false,actual_model_cost:0}
test('ABF endpoints dispatch separately once and retain preview/grant/apply identity',async()=>{
 let count=0
 const bodies={abf_preview:{request_id:id,expected_revision:0,stage:'a_diagnosis',target_version:0},abf_authorize:{preview_id:id,request_digest:sha,accept_fixed_only:true},
 abf_execute:{authorization_id:id},abf_status:{authorization_id:id},abf_recover:{authorization_id:id},abf_adoption_preview:{authorization_id:id},
 abf_apply:{request_id:id,expected_revision:0,authorization_id:id,candidate_digest:sha,review_confirmed:true}}
 for(const [action,body] of Object.entries(bodies))await abfCall(action,token,body,async(path,options)=>{
  count++;assert.equal(path,'/api/live/workbench/'+action);assert.deepEqual(JSON.parse(options.body),body)
  return {ok:true,json:async()=>({data:{...source,...body}})}
 })
 assert.equal(count,7)
 await assert.rejects(abfCall('abf_execute',token,{authorization_id:id},async()=>{count++;throw Error('lost')}),e=>e.code==='uncertain')
 assert.equal(count,8)
})
test('ABF refuses real mode, foreign identities, unknown fields and invalid stages before dispatch',async()=>{
 let calls=0;const wire=async()=>{calls++;return {ok:true,json:async()=>({data:{...source,authorization_id:id,mode:'real_model'}})}}
 await assert.rejects(abfCall('abf_execute',token,{authorization_id:id},wire),/来源/)
 for(const body of [{request_id:id,expected_revision:0,stage:'f_review',target_version:0},
  {request_id:id,expected_revision:0,stage:'b_plan',target_version:true},{request_id:id,expected_revision:0,stage:'a_diagnosis',target_version:0,api_key:'extra'}])
  await assert.rejects(abfCall('abf_preview',token,body,wire))
 await assert.rejects(abfCall('abf_authorize',token,{preview_id:id,request_digest:sha,accept_real_model:true},wire))
 assert.equal(calls,1)
 await assert.rejects(abfCall('abf_status',token,{authorization_id:id},async()=>({ok:true,json:async()=>({data:{...source,authorization_id:'22345678-1234-1234-1234-123456789abc'}})})),/身份/)
})
test('ABF apply pending receipt restores exact identity and rejects candidate text injection',()=>{
 const values=new Map(),storage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)},t=addWorkbenchSession(storage,webcrypto,'2026-11-10').active
 const pending={operation:'abf_apply',body:{request_id:id,expected_revision:1,authorization_id:id,candidate_digest:sha,review_confirmed:true},startedAt:new Date().toISOString()}
 patchWorkbenchSession(storage,t,{pending});assert.deepEqual(readWorkbenchRegistry(storage).entries[0].pending,pending)
 const before=JSON.stringify([...values]);assert.throws(()=>patchWorkbenchSession(storage,t,{pending:{...pending,body:{...pending.body,candidate:{invented:true}}}}))
 assert.equal(JSON.stringify([...values]),before)
})
