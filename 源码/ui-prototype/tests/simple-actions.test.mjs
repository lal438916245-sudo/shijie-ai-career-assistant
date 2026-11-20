import test from 'node:test'
import assert from 'node:assert/strict'
import {createSimpleActions,resumePreview} from '../src/lib/simple-actions.mjs'
const aid='11111111-1111-4111-8111-111111111111',pid='22222222-2222-4222-8222-222222222222'
const storage=()=>{const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)}}
function setup({existing=false,failExecute=false}={}){
 let applied=false,executed=existing;const calls=[]
 const s={revision:0,diagnosis:null,runtime_capabilities:{outbound_enabled:true,model_configured:true,sponsored_gateway:{session_budget_micro_cny:1000000}},session_runtime:existing?{execution_mode:'real_model',entries:[{stage:'a_diagnosis',authorization_id:aid,status:'settled'}]}:null}
 const receipt=()=>({stage:'a_diagnosis',target_version:0,authorization_id:aid,preview_id:pid,request_digest:'a'.repeat(64),status:executed?'completed':'authorized',consumed:executed})
 const request=async(path,token,body)=>{calls.push(path);if(path==='state')return structuredClone(s)
  if(path==='session_runtime_open'){s.session_runtime={execution_mode:'real_model',entries:[]};s.revision++;return {saved:true}}
  if(path==='abf_apply'){s.diagnosis={audit:{}};s.revision++;applied=true;return {saved:true}}
  if(path.startsWith('request?'))return {found:false}
  throw Error('Unexpected mutation '+path)
 }
 const abf=async(path,token,body)=>{calls.push(path)
  if(path==='abf_preview')return {preview_id:pid,request_digest:'a'.repeat(64),input_limit_exceeded:false}
  if(path==='abf_authorize'){s.session_runtime.entries=[{stage:'a_diagnosis',authorization_id:aid,status:'held_unconsumed'}];return receipt()}
  if(path==='abf_execute'){if(failExecute)throw Error('uncertain');executed=true;return receipt()}
  if(path==='abf_status')return receipt()
  if(path==='abf_adoption_preview')return {already_applied:applied,application:applied?{}:null,can_apply:!applied,candidate_digest:'b'.repeat(64)}
  throw Error(path)
 }
 return {calls,s,actions:createSimpleActions({token:'c'.repeat(64),storage:storage(),request,abf,uuid:()=>pid,lock:async fn=>fn()})}
}
test('one explicit diagnosis action opens a hidden runtime, dispatches once and saves; reopening does not resend',async()=>{
 const f=setup();assert.equal(f.calls.length,0)
 await f.actions.diagnosis();await f.actions.diagnosis()
 assert.equal(f.calls.filter(x=>x==='abf_execute').length,1)
 assert.equal(f.calls.filter(x=>x==='abf_authorize').length,1)
 assert.equal(f.calls.filter(x=>x==='session_runtime_open').length,1)
 assert.ok(f.s.diagnosis)
})
test('a saved paid response is adopted without another preview, authorization or model dispatch',async()=>{
 const f=setup({existing:true});await f.actions.diagnosis()
 assert.equal(f.calls.filter(x=>['abf_execute','abf_authorize','abf_preview'].includes(x)).length,0)
 assert.ok(f.calls.includes('abf_status')&&f.calls.includes('abf_apply'))
})
test('uncertain execution is not retried when the user returns',async()=>{
 const f=setup({failExecute:true});await assert.rejects(()=>f.actions.diagnosis(),/uncertain/)
 await assert.rejects(()=>f.actions.diagnosis(),/尚未确认/)
 assert.equal(f.calls.filter(x=>x==='abf_execute').length,1)
})
test('resume preview follows Unicode offsets, preserves unselected originals and refuses overlaps',()=>{
 const original='🧭原始经历。课程练习。'
 const points=Array.from(original),a={item_id:'a',original_ref:{source_id:'resume_original',start:1,end:5,quote:points.slice(1,5).join('')},proposed_text:'已有经历'}
 assert.equal(resumePreview(original,[a],[]),original)
 assert.equal(resumePreview(original,[a],['a']),'🧭已有经历。课程练习。')
 assert.throws(()=>resumePreview(original,[a,{...a,item_id:'b'}],['a','b']),/位置需要/)
})
