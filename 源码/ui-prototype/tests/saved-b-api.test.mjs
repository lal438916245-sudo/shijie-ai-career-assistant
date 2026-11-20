import test from 'node:test'
import assert from 'node:assert/strict'
import {workbenchRequest} from '../src/lib/workbench-api.mjs'

test('保存B内容的预览和采用走本机接口，不发执行或授权请求',async()=>{
 const calls=[],token='b'.repeat(64),value={source_kind:'competition_workbench_double',run_mode:'demo',simulated:true,real_dispatch_enabled:false,model_requests:0,new_model_requests:0}
 const transport=async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>({data:value})}}
 await workbenchRequest('saved_b_preview',token,{authorization_id:'original-failed'},transport)
 const body={request_id:'kept-id',expected_revision:2,authorization_id:'original-failed',derivation_digest:'digest',review_confirmed:true}
 await workbenchRequest('saved_b_apply',token,body,transport)
 assert.deepEqual(calls,[{url:'/api/live/workbench/saved_b_preview',body:{authorization_id:'original-failed'}},{url:'/api/live/workbench/saved_b_apply',body}])
 let count=0
 await assert.rejects(workbenchRequest('saved_b_apply',token,body,async()=>{count++;throw Error('lost response')}),/先查询/)
 assert.equal(count,1)
})
