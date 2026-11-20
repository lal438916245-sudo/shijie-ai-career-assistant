import test from 'node:test'
import assert from 'node:assert/strict'
import {openCEBudget,readCEBudget} from '../src/lib/ce-session-api.mjs'
import {cedCall} from '../src/lib/ced-call-api.mjs'
import {addWorkbenchSession,patchWorkbenchSession,readWorkbenchRegistry} from '../src/lib/workbench-sessions.mjs'
import {webcrypto} from 'node:crypto'
const id='12345678-1234-1234-1234-123456789abc',token='b'.repeat(64)
const scope={case_id:'case',session_id:'same',trace_id:'trace',plan_id:'plan'}
const source={scope,source_kind:'competition_workbench_double',run_mode:'demo',simulated:true,real_dispatch_enabled:false,model_requests:0}
const body={request_id:id,expected_revision:6,simulation_limit_micro_cny:3000000}
const ledger={scope,mode:'ce_local_rehearsal',simulated:true,actual_model_cost:0,limit_micro_cny:3000000,spent_simulated_micro_cny:10000,
 held_unconsumed_micro_cny:40000,consumed_unconfirmed_micro_cny:50000,available_micro_cny:2900000,overrun_micro_cny:0,overspent_micro_cny:0}
test('CE budget create and read are separate local requests, never real authorization or a retry',async()=>{
 let calls=0
 await openCEBudget(token,body,async(path,options)=>{calls++;assert.equal(path,'/api/live/workbench/ce_budget_open');assert.deepEqual(JSON.parse(options.body),body)
  return {ok:true,json:async()=>({data:{...source,mode:'ce_local_rehearsal',external_network_allowed:false,actual_model_cost:0,request_id:id}})}})
 await readCEBudget(token,async(path,options)=>{calls++;assert.equal(path,'/api/live/workbench/ce-budget');assert.equal(options.method,undefined);return {ok:true,json:async()=>({data:{...source,ce_budget:ledger}})}})
 await assert.rejects(openCEBudget(token,body,async()=>{calls++;throw Error('lost')}),e=>e.code==='uncertain');assert.equal(calls,3)
 for(const b of [{...body,simulation_limit_micro_cny:0},{...body,simulation_limit_micro_cny:true},{...body,accept_real_model:true}])await assert.rejects(openCEBudget(token,b,()=>{throw Error('must not send')}))
 await assert.rejects(readCEBudget(token,async()=>({ok:true,json:async()=>({data:{...source,ce_budget:{...ledger,simulated:false}}})})),/预算/)
 await assert.rejects(readCEBudget(token,async()=>({ok:true,json:async()=>({data:{...source,ce_budget:{...ledger,scope:{...scope,session_id:'other'}}}})})),/预算/)
})
test('CE budget opening pending identity survives reload and extra fields cannot enter the request',()=>{
 const values=new Map(),storage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)},t=addWorkbenchSession(storage,webcrypto,'2026-11-10').active
 const pending={operation:'ce_budget_open',body,startedAt:new Date().toISOString()};patchWorkbenchSession(storage,t,{pending})
 assert.deepEqual(readWorkbenchRegistry(storage).entries[0].pending,pending)
 const before=JSON.stringify([...values]);assert.throws(()=>patchWorkbenchSession(storage,t,{pending:{...pending,body:{...body,clear_history:true}}}));assert.equal(JSON.stringify([...values]),before)
})
test('C/E session receipts remain isolated fixed candidates with explicit simulated budget labels',async()=>{
 const value={...source,mode:'ced_fixed_rehearsal',external_network_allowed:false,actual_model_cost:0,authorization_id:id,
  ce_budget_rehearsal:{usage_source:'local_simulated',reserve_micro_cny:40000,actual_model_cost:0}}
 assert.deepEqual(await cedCall('call_status',token,{authorization_id:id},async()=>({ok:true,json:async()=>({data:value})})),value)
 await assert.rejects(cedCall('call_execute',token,{authorization_id:id},async()=>({ok:true,json:async()=>({data:{...value,mode:'ced_trial',actual_model_cost:null}})})),/边界|来源/)
})


test('unadopted interview report displays pending state without leaking fixed analysis',async()=>{
 const {mkdtemp,mkdir,writeFile,rm}=await import('node:fs/promises')
 const {resolve,join}=await import('node:path'),{fileURLToPath,pathToFileURL}=await import('node:url')
 const {build}=await import('vite'),React=(await import('react')).default,{renderToStaticMarkup}=await import('react-dom/server')
 const root=fileURLToPath(new URL('..',import.meta.url)),cache=join(root,'node_modules/.cache');await mkdir(cache,{recursive:true})
 const dir=await mkdtemp(join(cache,'ce-pending-'))
 try{
  const built=await build({root,configFile:resolve(root,'vite.config.ts'),logLevel:'silent',build:{ssr:resolve(root,'src/components/WorkbenchInterviewEvidence.tsx'),write:false,minify:false}})
  const output=Array.isArray(built)?built[0].output:built.output,entry=join(dir,'view.mjs');await writeFile(entry,output.find(c=>c.type==='chunk'&&c.isEntry).code)
  const {WorkbenchInterviewReport}=await import(pathToFileURL(entry))
  const html=renderToStaticMarkup(React.createElement(WorkbenchInterviewReport,{report:{review_status:'pending_candidate_review',answered_count:1,
    notice:'回答已保存，等待候选复盘。',findings:[{observation:'FIXED_ANALYSIS_MUST_NOT_LEAK',reference_outline:'HIDDEN_REFERENCE'}]}}))
  assert.ok(html.includes('复盘待核对采用'));assert.ok(!html.includes('FIXED_ANALYSIS_MUST_NOT_LEAK'));assert.ok(!html.includes('HIDDEN_REFERENCE'))
 }finally{assert.ok(dir.startsWith(cache));await rm(dir,{recursive:true,force:true})}
})
