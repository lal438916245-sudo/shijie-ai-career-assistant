import test from 'node:test'
import assert from 'node:assert/strict'
import {preparationRequest,workflowRequest} from '../src/lib/workflow-api.mjs'
const token='b'.repeat(64)
const reply=(data,status=200)=>({ok:status===200,status,json:async()=>({data})})
const preparation={source_kind:'model_preparation_only',dispatch_enabled:false,authorized:false,key_state:'saved'}

test('配置只发本机准备接口，不碰浏览器存储或携带代理服务密钥',async()=>{
 const old=globalThis.localStorage;globalThis.localStorage=new Proxy({},{get(){throw Error('不得存储配置和密钥')}})
 try{
  let captured,calls=0
  const body={api_key:'synthetic-not-real',key_action:'replace'}
  const result=await preparationRequest('model-config',null,body,async(url,options)=>{captured={url,options};calls++;return reply(preparation)})
  assert.equal(calls,1);assert.equal(captured.url,'/api/live/model-config');assert.deepEqual(JSON.parse(captured.options.body),body)
  assert.equal(captured.options.headers['X-CP-Local-Key'],undefined);assert.equal(captured.options.headers['X-CP-Session'],undefined)
  assert.equal(result.authorized,false);assert.equal(result.dispatch_enabled,false)
 }finally{globalThis.localStorage=old}
})
test('预览使用独立会话凭据；拒绝启用调用或授予权限的响应',async()=>{
 let captured
 await preparationRequest('call-preview',token,{stage:'diagnosis'},async(url,options)=>{captured=options;return reply(preparation)})
 assert.equal(captured.headers['X-CP-Session'],token)
 for(const invalid of [{...preparation,authorized:true},{...preparation,dispatch_enabled:true},{...preparation,source_kind:'real_model'}]){
  await assert.rejects(preparationRequest('model-config',null,undefined,async()=>reply(invalid)),e=>e.code==='source')
 }
})
test('配置保存超时或断连只报告未确认，不自动重发',async()=>{
 for(const fail of [()=>{throw Object.assign(new Error(),{name:'AbortError'})},()=>{throw Error('offline') }]){
  let calls=0
  await assert.rejects(preparationRequest('model-config',null,{api_key:'synthetic'},async()=>{calls++;return fail()}),e=>e.code==='unavailable')
  assert.equal(calls,1)
 }
})
test('中断恢复是独立写操作，不能自动变成重新诊断',async()=>{
 let captured,calls=0
 await workflowRequest('recover',token,{stage:'diagnosis',recovery_id:'attempt'},async(url,options)=>{captured={url,options};calls++;return reply({source_kind:'local_workflow_double',status:'failed'})})
 assert.equal(calls,1);assert.equal(captured.url,'/api/live/recover');assert.equal(JSON.parse(captured.options.body).recovery_id,'attempt')
})
