import test from 'node:test'
import assert from 'node:assert/strict'
import {webcrypto} from 'node:crypto'
import {addPersonalWorkbenchSession,addWorkbenchSession,readWorkbenchRegistry,patchWorkbenchSession,selectWorkbenchSession} from '../src/lib/workbench-sessions.mjs'
import {workbenchRequest} from '../src/lib/workbench-api.mjs'
const storage=()=>{const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)}}
const request_id='12345678-1234-4234-8234-123456789abc'
const body={request_id,start_date:'2026-11-11',target_role:'初级数据开发工程师',resume_text:'课程项目中使用Python读取CSV并进行基础清洗，复杂SQL仍需核对。',jd_text:'岗位职责\n1、编写SQL关联查询并核对金额口径，保留可复核的结果。'}
const source={source_kind:'competition_workbench_double',run_mode:'demo',simulated:true,real_dispatch_enabled:false,model_requests:0}
test('personal input saves a separate identity and exact pending body without borrowing demo progress',()=>{
 const s=storage(),demo=addWorkbenchSession(s,webcrypto,'2026-11-11'),old=demo.active
 const personal=addPersonalWorkbenchSession(s,webcrypto,'2026-11-11'),token=personal.active
 assert.notEqual(token,old);assert.match(personal.entries.at(-1).label,/个人资料/)
 const pending={operation:'create_personal',body,startedAt:new Date().toISOString()}
 patchWorkbenchSession(s,token,{pending});selectWorkbenchSession(s,old);selectWorkbenchSession(s,token)
 const restored=readWorkbenchRegistry(s);assert.deepEqual(restored.entries.find(e=>e.token===token).pending,pending)
 assert.equal(restored.entries.find(e=>e.token===old).pending,null)
 assert.throws(()=>patchWorkbenchSession(s,token,{pending:{...pending,body:{...body,api_key:'NOT-ALLOWED'}}}))
 assert.deepEqual(readWorkbenchRegistry(s).entries.find(e=>e.token===token).pending,pending)
})
test('personal create posts user text once, with no inherited revision, authorization or automatic retry',async()=>{
 const calls=[],token='a'.repeat(64)
 const transport=async(path,options)=>{calls.push({path,options});throw Error('lost response')}
 await assert.rejects(workbenchRequest('create_personal',token,body,transport),/尚未确认/)
 assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/live/workbench/create_personal')
 assert.deepEqual(JSON.parse(calls[0].options.body),body);assert.equal(calls[0].options.headers['X-CP-Session'],token)
})
test('personal create response must retain the local boundary and is never an implicit real model request',async()=>{
 const token='a'.repeat(64),response=data=>async()=>({ok:true,json:async()=>({data})})
 const value=await workbenchRequest('create_personal',token,body,response({...source,operation:'create_personal',request_id}))
 assert.equal(value.request_id,request_id)
 await assert.rejects(workbenchRequest('create_personal',token,body,response({...source,real_dispatch_enabled:true})),/来源/)
})
