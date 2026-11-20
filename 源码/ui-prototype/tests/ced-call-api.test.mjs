import test from 'node:test'
import assert from 'node:assert/strict'
import {cedCall} from '../src/lib/ced-call-api.mjs'
const token='a'.repeat(64),id='12345678-1234-1234-1234-123456789abc'
const fixed={source_kind:'competition_workbench_double',run_mode:'demo',simulated:true,real_dispatch_enabled:false,model_requests:0,mode:'ced_fixed_rehearsal',external_network_allowed:false,actual_model_cost:0,preview_id:id,authorization_id:id,stage:'c_grade',target_id:'ATTEMPT_'+'b'.repeat(24)}
const request={request_id:id,expected_revision:1,stage:'c_grade',target_id:'ATTEMPT_'+'b'.repeat(24)}
test('CED preview, grant, execute, query and recovery are independent single requests',async()=>{
 const seen=[]
 for(const [action,body] of [['call_preview',request],['call_authorize',{preview_id:id,request_digest:'a'.repeat(64),accept_fixed_only:true}],['call_execute',{authorization_id:id}],['call_status',{authorization_id:id}],['call_recover',{authorization_id:id}]]){
  await cedCall(action,token,body,async(path,options)=>{seen.push(path);assert.equal(path,'/api/live/workbench/'+action);assert.deepEqual(JSON.parse(options.body),body);return {ok:true,json:async()=>({data:fixed})}})
 }
 assert.equal(seen.length,5)
})
test('CED uncertain call preserves caller identity and never retries or recovers automatically',async()=>{
 let count=0;const body={authorization_id:id}
 await assert.rejects(cedCall('call_execute',token,body,async()=>{count++;throw Error('lost')}),e=>e.code==='uncertain')
 assert.equal(count,1);assert.deepEqual(body,{authorization_id:id})
})
test('CED rejects broadened fields, real confirmations, wrong target types and paid/mode changes',async()=>{
 for(const [a,b] of [['call_preview',{...request,api_key:'forbidden'}],['call_preview',{...request,stage:'e_report'}],['call_authorize',{preview_id:id,request_digest:'a'.repeat(64),accept_real_model:true}],['real_execute',{authorization_id:id}]])await assert.rejects(cedCall(a,token,b,()=>{throw Error('must not dispatch')}),e=>e.code==='invalid')
 for(const change of [{mode:'real_model'},{actual_model_cost:1},{external_network_allowed:true}])await assert.rejects(cedCall('call_status',token,{authorization_id:id},async()=>({ok:true,json:async()=>({data:{...fixed,...change}})})),e=>e.code==='source')
})
test('CED refuses swapped valid-mode receipt identities and inherited object keys',async()=>{
 await assert.rejects(cedCall('call_status',token,{authorization_id:id},async()=>({ok:true,json:async()=>({data:{...fixed,authorization_id:'different'}})})),e=>e.code==='source')
 await assert.rejects(cedCall('toString',token,{},()=>{throw Error('must not dispatch')}),e=>e.code==='invalid')
 await assert.rejects(cedCall('call_preview',token,{...request,stage:'toString'},()=>{throw Error('must not dispatch')}),e=>e.code==='invalid')
})
