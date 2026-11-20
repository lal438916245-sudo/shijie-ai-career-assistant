import test from 'node:test'
import assert from 'node:assert/strict'
import {authorizedABRequest} from '../src/lib/workflow-api.mjs'
const token='b'.repeat(64)
const envelope={source_kind:'authorized_ab_double',mode:'local_request_double',real_dispatch_enabled:false,status:'authorized'}
const response=(data,status=200)=>({ok:status===200,status,json:async()=>({data})})

test('预览、授权、执行和查询分别发送一次，不隐式串联操作或存储授权',async()=>{
 const old=globalThis.localStorage;globalThis.localStorage=new Proxy({},{get(){throw Error('不得使用浏览器持久存储')}})
 try{
  for(const action of ['preview','authorize','execute','status','latest']){
   const calls=[];const body=action==='latest'?undefined:{authorization_id:'local-only'}
   const data=await authorizedABRequest(action,token,body,async(url,options)=>{calls.push({url,options});return response(envelope)})
   assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/live/ab/'+action)
   assert.equal(calls[0].options.headers['X-CP-Session'],token)
   assert.equal(calls[0].options.headers['X-CP-Local-Key'],undefined)
   assert.equal(calls[0].options.method,action==='latest'?undefined:'POST')
   assert.equal(data.real_dispatch_enabled,false)
  }
 }finally{globalThis.localStorage=old}
})
test('拒绝真实传输、未知来源以及不匹配的授权模式',async()=>{
 for(const data of [{...envelope,real_dispatch_enabled:true},{...envelope,mode:'real_model'},{...envelope,source_kind:'model_preparation_only'}]){
  await assert.rejects(authorizedABRequest('execute',token,{},async()=>response(data)),e=>e.code==='source')
 }
})
test('执行响应丢失只返回未确认，禁止自动重新执行或重新授权',async()=>{
 let count=0
 await assert.rejects(authorizedABRequest('execute',token,{authorization_id:'id'},async()=>{count++;throw Object.assign(Error(),{name:'AbortError'})}),e=>e.code==='uncertain')
 assert.equal(count,1)
 await assert.rejects(authorizedABRequest('execute-real',token,{},async()=>{throw Error('must not run')}),e=>e.code==='invalid')
})
