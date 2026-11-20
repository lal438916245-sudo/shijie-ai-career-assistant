import test from 'node:test'
import assert from 'node:assert/strict'
import {WORKFLOW_TOKEN_KEY,readWorkflowToken,prepareWorkflowToken,workflowRequest} from '../src/lib/workflow-api.mjs'
import {multiRoute,multiHash} from '../src/lib/multi.mjs'

function storage(){const values=new Map();return {getItem:key=>values.get(key)??null,setItem:(key,val)=>values.set(key,val),dump:()=>values}}
test('工作流模式路由可刷新恢复，并保持演示案例身份',()=>{
 assert.equal(multiRoute('#new?case=workflow&topic=sql').caseId,'workflow')
 assert.equal(multiHash('plan','workflow','sql'),'#plan?case=workflow&topic=sql')
 assert.equal(multiRoute('#new?case=journey&topic=sql').caseId,'journey')
})
test('工作流会话身份由随机源产生并复用；损坏或不可写时不能覆盖',()=>{
 const s=storage(),rng={getRandomValues(bytes){bytes.fill(172);return bytes}}
 const id=prepareWorkflowToken(s,rng);assert.equal(id,'ac'.repeat(32));assert.equal(prepareWorkflowToken(s,rng),id);assert.equal(readWorkflowToken(s),id)
 s.setItem(WORKFLOW_TOKEN_KEY,'broken');assert.throws(()=>prepareWorkflowToken(s,rng),/无法读取/);assert.equal(s.getItem(WORKFLOW_TOKEN_KEY),'broken')
 assert.throws(()=>prepareWorkflowToken({getItem:()=>null,setItem:()=>{throw Error('blocked')}},rng),/无法保存/)
})
test('请求不传代理服务密钥、携带标签会话身份并拒绝不明来源',async()=>{
 const token='bc'.repeat(32);let captured
 const transport=async(url,options)=>{captured={url,options};return {ok:true,json:async()=>({data:{source_kind:'local_workflow_double',status:'completed'}})}}
 assert.equal((await workflowRequest('diagnosis',token,{},transport)).status,'completed')
 assert.equal(captured.url,'/api/live/diagnosis');assert.equal(captured.options.headers['X-CP-Session'],token)
 assert.equal(captured.options.headers['X-CP-Local-Key'],undefined)
 await assert.rejects(()=>workflowRequest('plan',token,undefined,async()=>({ok:true,json:async()=>({data:{source_kind:'fixed_stub'}})})),/来源无法确认/)
 await assert.rejects(()=>workflowRequest('../practice',token,undefined,transport),/请求无效/)
})
