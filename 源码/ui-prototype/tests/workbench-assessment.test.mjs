import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp,writeFile,readFile,rm,mkdir} from 'node:fs/promises'
import {resolve,join} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {workbenchRequest} from '../src/lib/workbench-api.mjs'
import {addWorkbenchSession,patchWorkbenchSession,readWorkbenchRegistry} from '../src/lib/workbench-sessions.mjs'
import {webcrypto} from 'node:crypto'
const root=fileURLToPath(new URL('..',import.meta.url))
const source={source_kind:'competition_workbench_double',run_mode:'demo',simulated:true,real_dispatch_enabled:false,model_requests:0}
const rid='RUN_'+'a'.repeat(24),qid='QUESTION_'+'b'.repeat(24),aid='ATTEMPT_'+'c'.repeat(24),task='TASK_'+'d'.repeat(24)
const request_id='12345678-1234-1234-1234-123456789abc'
test('answer and next POST each dispatch once; no future-question parameter or external namespace',async()=>{
 let calls=0
 for(const op of ['assessment_start','retest_start','answer','assessment_next','assessment_end'])await workbenchRequest(op,'a'.repeat(64),{},async(path,o)=>{calls++;assert.equal(path,'/api/live/workbench/'+op);assert.equal(o.method,'POST');return {ok:true,json:async()=>({data:source})}})
 assert.equal(calls,5)
 await assert.rejects(workbenchRequest('answer','a'.repeat(64),{},async()=>{calls++;throw Error('lost')}),e=>e.code==='uncertain');assert.equal(calls,6)
 for(const path of ['assessment?run_id='+rid+'&question=2','assessment?run_id=../other','assessment-options?kind=topic&period_start=2026-11-03&period_end=2026-11-03'])await assert.rejects(workbenchRequest(path,'a'.repeat(64),undefined,()=>{throw Error('must not dispatch')}))
})
test('pending answer/scope/next identity restores exactly, extra fields and oversized answers rejected',()=>{
 const values=new Map(),s={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)}
 const token=addWorkbenchSession(s,webcrypto,'2026-11-03').active
 const examples=[['answer',{run_id:rid,question_id:qid,answer:'待确认的作答'}],['assessment_next',{run_id:rid,last_attempt_id:aid}],['assessment_start',{plan_version:2,kind:'day',period_start:'2026-11-03',period_end:'2026-11-03',task_ids:[task],fixture_path:'repair'}]]
 for(const [operation,extra] of examples){const pending={operation,body:{request_id,expected_revision:2,...extra},startedAt:new Date().toISOString()};patchWorkbenchSession(s,token,{pending});assert.deepEqual(readWorkbenchRegistry(s).entries[0].pending,pending)}
 for(const answer of ['', 'a'.repeat(6001)])assert.throws(()=>patchWorkbenchSession(s,token,{pending:{operation:'answer',body:{request_id,expected_revision:2,run_id:rid,question_id:qid,answer},startedAt:new Date().toISOString()}}))
 const before=JSON.stringify([...values]);assert.throws(()=>patchWorkbenchSession(s,token,{pending:{operation:'answer',body:{request_id,expected_revision:2,run_id:rid,question_id:qid,answer:'abc',api_key:'extra'},startedAt:new Date().toISOString()}}));assert.equal(JSON.stringify([...values]),before)
})
test('answer report preserves submitted answer and topic rubric',async()=>{
 const cache=join(root,'node_modules','.cache');await mkdir(cache,{recursive:true});const dir=await mkdtemp(join(cache,'workbench-assessment-'))
 try{
  const result=await build({root,configFile:resolve(root,'vite.config.ts'),logLevel:'silent',build:{ssr:resolve(root,'src/components/WorkbenchAssessments.tsx'),write:false,minify:false}})
  const output=Array.isArray(result)?result[0].output:result.output,entry=join(dir,'view.mjs');await writeFile(entry,output.find(x=>x.type==='chunk'&&x.isEntry).code)
  const {WorkbenchAttemptReport}=await import(pathToFileURL(entry))
  const fixture=JSON.parse(await readFile(join(root,'tests/fixtures/workbench-assessment.json'),'utf8'))
  assert.ok(!JSON.stringify(fixture.unanswered_question).includes('reference'))
  const report=renderToStaticMarkup(React.createElement(WorkbenchAttemptReport,{attempt:fixture.attempt}))
  for(const s of ['固定验收作答','结论与结果','55','参考答案与解析','160','100','未分析用户作答','presentation_only'])assert.ok(report.includes(s),s)
  const pending=renderToStaticMarkup(React.createElement(WorkbenchAttemptReport,{attempt:{...fixture.attempt,grade:{...fixture.attempt.grade,status:'review_required',scores:[]}}}))
  assert.match(pending,/未计为0分、通过或失败/);assert.doesNotMatch(pending,/本题演示通过/)
 }finally{await rm(dir,{recursive:true,force:true})}
})
