import test from 'node:test'
import assert from 'node:assert/strict'
import {webcrypto} from 'node:crypto'
import {mkdir,mkdtemp,writeFile,rm,readFile} from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {workbenchRequest} from '../src/lib/workbench-api.mjs'
import {addWorkbenchSession,patchWorkbenchSession,readWorkbenchRegistry} from '../src/lib/workbench-sessions.mjs'
const source={source_kind:'competition_workbench_double',run_mode:'demo',simulated:true,real_dispatch_enabled:false,model_requests:0}
const request_id='12345678-1234-1234-1234-123456789abc'
const storage=()=>{const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)}}

test('program check and user confirmation dispatch separately once; uncertain publication does not retry',async()=>{
 const token='a'.repeat(64),calls=[]
 for(const [path,body] of [['plan_check',{plan_version:1}],['plan_confirm_publish',{request_id,expected_revision:3,plan_version:1,plan_digest:'b'.repeat(64),validation_digest:'c'.repeat(64),review_confirmed:true}]]){
  await workbenchRequest(path,token,body,async(url,options)=>{calls.push(url);assert.deepEqual(JSON.parse(options.body),body);return {ok:true,json:async()=>({data:source})}})
 }
 assert.deepEqual(calls,['/api/live/workbench/plan_check','/api/live/workbench/plan_confirm_publish'])
 let sent=0;await assert.rejects(workbenchRequest('plan_confirm_publish',token,{},async()=>{sent++;throw Error('lost')}),e=>e.code==='uncertain');assert.equal(sent,1)
})

test('publication and saved-B pending bodies survive reload while rejecting injected data',()=>{
 const s=storage(),v=addWorkbenchSession(s,webcrypto,'2026-11-12'),token=v.active
 for(const [operation,extra] of [['plan_prepare',{}],['plan_confirm_publish',{plan_version:1,plan_digest:'b'.repeat(64),validation_digest:'c'.repeat(64),review_confirmed:true}],['saved_b_apply',{authorization_id:request_id,derivation_digest:'e'.repeat(64),review_confirmed:true}]]){
  const pending={operation,body:{request_id,expected_revision:3,...extra},startedAt:new Date().toISOString()}
  patchWorkbenchSession(s,token,{pending});assert.deepEqual(readWorkbenchRegistry(s).entries[0].pending,pending)
  assert.throws(()=>patchWorkbenchSession(s,token,{pending:{...pending,body:{...pending.body,api_key:'forbidden'}}}))
  if(operation==='plan_confirm_publish')assert.throws(()=>patchWorkbenchSession(s,token,{pending:{...pending,body:{...pending.body,review_confirmed:false}}}))
 }
})

test('competition plan UI exposes program check and consent, no active F action, and labels archived F',async()=>{
 const root=resolve('.'),cache=join(root,'node_modules/.cache/plan-confirm-tests');await mkdir(cache,{recursive:true});const dir=await mkdtemp(join(cache,'view-'))
 try{
  const result=await build({root,configFile:join(root,'vite.config.ts'),logLevel:'silent',build:{ssr:join(root,'src/components/WorkbenchPlanConfirmation.tsx'),write:false,minify:false}})
  const output=Array.isArray(result)?result[0].output:result.output,module=join(dir,'view.mjs');await writeFile(module,output.find(c=>c.type==='chunk'&&c.isEntry).code)
  const {default:View}=await import(pathToFileURL(module));const props={token:'a'.repeat(64),version:1,planDigest:'b'.repeat(64),tasks:[{task_id:'t',day:1,title:'连接练习',preparation:'纸笔即可',expected_outcome:'核对行数'}],historical:false,published:false,disabled:false,onConfirm:async()=>{}}
  const html=renderToStaticMarkup(React.createElement(View,props));assert.match(html,/运行程序校验/);assert.match(html,/纸笔即可/);assert.match(html,/核对行数/);assert.doesNotMatch(html,/确认发布计划（不调用模型）/)
  const published=renderToStaticMarkup(React.createElement(View,{...props,published:true}));assert.match(published,/已确认发布/);assert.doesNotMatch(published,/运行程序校验/)
  const workspace=await readFile(join(root,'src/components/CompetitionWorkspace.tsx'),'utf8'),operations=await readFile(join(root,'src/components/WorkbenchSessionOperations.tsx'),'utf8')
  assert.doesNotMatch(workspace,/setAbfTarget\(\{stage:'f_review'/);assert.doesNotMatch(operations,/准备 F|根据 F 准备/)
  assert.match(workspace,/publication_policy==='program-confirm-v1'/)
 }finally{assert.ok(dir.startsWith(cache));await rm(dir,{recursive:true,force:true})}
})
