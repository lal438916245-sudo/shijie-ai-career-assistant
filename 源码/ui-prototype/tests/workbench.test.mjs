import test from 'node:test'
import assert from 'node:assert/strict'
import {webcrypto} from 'node:crypto'
import {workbenchRequest} from '../src/lib/workbench-api.mjs'
import {WORKBENCH_KEY,readWorkbenchRegistry,addWorkbenchSession,patchWorkbenchSession,selectWorkbenchSession,withWorkbenchLock} from '../src/lib/workbench-sessions.mjs'
const token='a'.repeat(64),request_id='12345678-1234-1234-1234-123456789abc'
const source={source_kind:'competition_workbench_double',run_mode:'demo',simulated:true,real_dispatch_enabled:false,model_requests:0}
const response=(data=source)=>({ok:true,json:async()=>({data})})
const storage=()=>{const values=new Map();return {getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)}}
test('only the fixed workbench namespace is admitted; identity travels in a header',async()=>{
 let calls=0
 const value=await workbenchRequest('review',token,{request_id},async(path,options)=>{calls++;assert.equal(path,'/api/live/workbench/review');assert.equal(options.headers['X-CP-Session'],token);assert.equal(options.cache,'no-store');assert.equal(options.method,'POST');return response()})
 assert.equal(value.model_requests,0);assert.equal(calls,1)
 for(const path of ['https://example.com','../sdk/execute','state?token='+token,'review?mode=real'])await assert.rejects(workbenchRequest(path,token,{},()=>{throw Error('must not dispatch')}),/请求无效/)
})
test('paid, unlabelled or altered source results fail closed',async()=>{
 for(const change of [{source_kind:'real_model_output'},{run_mode:'real_model'},{simulated:false},{real_dispatch_enabled:true},{model_requests:1}])await assert.rejects(workbenchRequest('state',token,undefined,async()=>response({...source,...change})),/来源或调用边界/)
})
test('uncertain POST is never retried; explicit receipt query stays read only',async()=>{
 let calls=0;await assert.rejects(workbenchRequest('review',token,{request_id},async()=>{calls++;throw Error('connection lost')}),e=>e.code==='uncertain');assert.equal(calls,1)
 await workbenchRequest('request?request_id='+request_id,token,undefined,async(path,o)=>{assert.equal(o.method,undefined);assert.equal(o.body,undefined);return response({...source,found:true})})
})
test('pending identity survives reload and session selection without crossing sessions',()=>{
 const s=storage();const one=addWorkbenchSession(s,webcrypto,'2026-11-03').active
 const pending={operation:'review',body:{request_id,expected_revision:2,plan_version:1},startedAt:new Date().toISOString()}
 patchWorkbenchSession(s,one,{saved:true,pending});const two=addWorkbenchSession(s,webcrypto,'2026-11-04').active
 assert.notEqual(one,two);assert.equal(readWorkbenchRegistry(s).entries[1].pending,null)
 selectWorkbenchSession(s,one);assert.deepEqual(readWorkbenchRegistry(s).entries[0].pending,pending)
 assert.equal(readWorkbenchRegistry(s).active,one)
})
test('malformed registry and invalid pending fields never overwrite original storage',()=>{
 const s=storage();s.setItem(WORKBENCH_KEY,'broken');assert.throws(()=>addWorkbenchSession(s,webcrypto,'2026-11-03'));assert.equal(s.getItem(WORKBENCH_KEY),'broken')
 const clean=storage(),v=addWorkbenchSession(clean,webcrypto,'2026-11-03'),before=clean.getItem(WORKBENCH_KEY)
 assert.throws(()=>patchWorkbenchSession(clean,v.active,{pending:{operation:'review',body:{request_id,api_key:'forbidden'},startedAt:new Date().toISOString()}}));assert.equal(clean.getItem(WORKBENCH_KEY),before)
})
test('browser locking failure prevents a write instead of silently falling back',async()=>{
 let called=false;await assert.rejects(withWorkbenchLock(()=>{called=true},{}));assert.equal(called,false)
 let lock='';await withWorkbenchLock(()=>{called=true},{request:async(name,fn)=>{lock=name;return fn()}});assert.equal(called,true);assert.equal(lock,'career-pilot-competition-workbench-v1')
})
