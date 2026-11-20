import test from 'node:test'
import assert from 'node:assert/strict'
import {sdkRequest} from '../src/lib/workflow-api.mjs'
const token='b'.repeat(64)
const data={source_kind:'sdk_ab_authorization',mode:'sdk_rehearsal',real_dispatch_enabled:false,simulated:true}
const reply=value=>({ok:true,status:200,json:async()=>({data:value})})
test('SDK 请求使用独立路径与显式模式，不泄露代理凭据',async()=>{
 let request
 await sdkRequest('ab/execute',token,{authorization_id:'sdk-only'},'sdk_rehearsal',async(url,options)=>{request={url,options};return reply(data)})
 assert.equal(request.url,'/api/sdk/ab/execute');assert.equal(request.options.headers['X-CP-SDK-Mode'],'sdk_rehearsal')
 assert.equal(request.options.headers['X-CP-Session'],token);assert.equal(request.options.headers['X-CP-Local-Key'],undefined)
})
test('SDK 预演拒绝真实模式、外发开启或来源混用响应',async()=>{
 for(const invalid of [{...data,mode:'real_model'},{...data,real_dispatch_enabled:true},{...data,simulated:false},{...data,source_kind:'real_model_session'}]){
  await assert.rejects(sdkRequest('ab/execute',token,{},'sdk_rehearsal',async()=>reply(invalid)),e=>e.code==='source')
 }
 const real={source_kind:'real_model_session',mode:'real_model',real_dispatch_enabled:false,simulated:false}
 assert.equal((await sdkRequest('session',token,undefined,'real_model',async()=>reply(real))).mode,'real_model')
 await assert.rejects(sdkRequest('session',token,undefined,'real_model',async()=>reply({...real,source_kind:'sdk_rehearsal_session'})),e=>e.code==='source')
})
test('SDK 断连不自动重发，查询不会隐式授权或执行',async()=>{
 let calls=0
 await assert.rejects(sdkRequest('ab/execute',token,{},'sdk_rehearsal',async()=>{calls++;throw Error('offline')}),e=>e.code==='uncertain')
 assert.equal(calls,1)
 let captured
 await sdkRequest('ab/latest',token,undefined,'sdk_rehearsal',async(url,options)=>{captured={url,options};return reply(data)})
 assert.equal(captured.url,'/api/sdk/ab/latest');assert.equal(captured.options.method,undefined)
})
