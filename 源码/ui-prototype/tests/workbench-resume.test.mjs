import test from 'node:test'
import assert from 'node:assert/strict'
import {webcrypto} from 'node:crypto'
import {mkdtemp,writeFile,readFile,rm,mkdir} from 'node:fs/promises'
import {resolve,join} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {workbenchRequest} from '../src/lib/workbench-api.mjs'
import {addWorkbenchSession,patchWorkbenchSession,readWorkbenchRegistry} from '../src/lib/workbench-sessions.mjs'
const root=fileURLToPath(new URL('..',import.meta.url)),rid='RESUME_'+'a'.repeat(24),token='b'.repeat(64)
const request_id='12345678-1234-1234-1234-123456789abc'
const source={source_kind:'competition_workbench_double',run_mode:'demo',simulated:true,real_dispatch_enabled:false,model_requests:0}

test('resume dispatches only isolated fixed endpoints once, refuses SDK or broader read parameters',async()=>{
 let calls=0
 for(const op of ['resume_generate','resume_check'])await workbenchRequest(op,token,{},async(path,options)=>{calls++;assert.equal(path,'/api/live/workbench/'+op);assert.equal(options.method,'POST');return {ok:true,json:async()=>({data:source})}})
 await workbenchRequest('resume?resume_id='+rid,token,undefined,async()=>{calls++;return {ok:true,json:async()=>({data:source})}})
 await assert.rejects(workbenchRequest('resume_check',token,{},async()=>{calls++;throw Error('lost')}),e=>e.code==='uncertain');assert.equal(calls,4)
 for(const path of ['resume?resume_id='+rid+'&session_id=other','resume?resume_id=../other','/api/sdk/resume'])await assert.rejects(workbenchRequest(path,token,undefined,()=>{throw Error('must not dispatch')}))
 await assert.rejects(workbenchRequest('resume?resume_id='+rid,token,undefined,async()=>({ok:true,json:async()=>({data:{...source,model_requests:1}})})),/来源或调用边界/)
})

test('pending D report and exact custom text restore without losing draft or adding privileged fields',()=>{
 const values=new Map(),s={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)},own=addWorkbenchSession(s,webcrypto,'2026-11-03').active
 for(const [operation,extra] of [['resume_generate',{}],['resume_check',{resume_id:rid,text:'  自定义换行\n请保留  '}]]){
  const pending={operation,body:{request_id,expected_revision:2,...extra},startedAt:new Date().toISOString()};patchWorkbenchSession(s,own,{pending});assert.deepEqual(readWorkbenchRegistry(s).entries[0].pending,pending)
 }
 const before=JSON.stringify([...values]);for(const extra of [{resume_id:rid,text:''},{resume_id:rid,text:'x'.repeat(6001)},{resume_id:'RESUME_other',text:'x'},{resume_id:rid,text:'x',api_key:'extra'}])assert.throws(()=>patchWorkbenchSession(s,own,{pending:{operation:'resume_check',body:{request_id,expected_revision:2,...extra},startedAt:new Date().toISOString()}}))
 assert.equal(JSON.stringify([...values]),before)
})

test('D report shows original quotations, concrete sources and boundaries; empty evidence stays empty',async()=>{
 const cache=join(root,'node_modules','.cache');await mkdir(cache,{recursive:true});const dir=await mkdtemp(join(cache,'workbench-resume-'))
 try{
  const result=await build({root,configFile:resolve(root,'vite.config.ts'),logLevel:'silent',build:{ssr:resolve(root,'src/components/WorkbenchResume.tsx'),write:false,minify:false}})
  const output=Array.isArray(result)?result[0].output:result.output,entry=join(dir,'view.mjs');await writeFile(entry,output.find(x=>x.type==='chunk'&&x.isEntry).code)
  const {WorkbenchResumeReport,WorkbenchResumeCheck}=await import(pathToFileURL(entry))
  const fixture=JSON.parse(await readFile(join(root,'tests/fixtures/workbench-resume.json'),'utf8'))
  const html=renderToStaticMarkup(React.createElement(WorkbenchResumeReport,{report:fixture.report}))
  for(const text of ['课程练习','证据边界','原始作答','面试原回答','不能转换成项目或真实技能证明','来源：'])assert.ok(html.includes(text),text)
  assert.ok(html.includes('未经独立核验'));assert.ok(html.includes('保留的简历原文'));assert.ok(html.includes('没有替换原文'))
  const formal=JSON.parse(await readFile(join(root,'tests/fixtures/candidate-adopted-resume.json'),'utf8'))
  const saved=renderToStaticMarkup(React.createElement(WorkbenchResumeReport,{report:formal}))
  for(const text of ['已保存的采用依据','课程练习补充','候选复盘已核对采用','评分已核对采用'])assert.ok(saved.includes(text),text)
  const empty=renderToStaticMarkup(React.createElement(WorkbenchResumeReport,{report:fixture.empty}))
  for(const text of ['尚无学习进度记录','尚无考核/复测答卷','尚无已结束面试'])assert.ok(empty.includes(text),text)
  for(const check of fixture.checks){const view=renderToStaticMarkup(React.createElement(WorkbenchResumeCheck,{check}));assert.ok(view.includes(check.result.reason));assert.ok(view.includes(check.text));assert.ok(view.includes('不修改简历'))}
  assert.deepEqual(new Set(fixture.checks.map(c=>c.result.status)),new Set(['bounded_suggestion','blocked','needs_verification']))
  const approved=fixture.report.items.filter(i=>i.suggested_text).map(i=>i.suggested_text).join('');assert.doesNotMatch(approved,/生产|千万|80%|精通|主导/)
 }finally{assert.ok(dir.startsWith(cache));await rm(dir,{recursive:true,force:true})}
})
