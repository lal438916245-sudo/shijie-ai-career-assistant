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
const root=fileURLToPath(new URL('..',import.meta.url)),iid='INTERVIEW_'+'a'.repeat(24),qid='ITURN_'+'b'.repeat(24)
const request_id='12345678-1234-1234-1234-123456789abc'
const source={source_kind:'competition_workbench_double',run_mode:'demo',simulated:true,real_dispatch_enabled:false,model_requests:0}
test('interview uses isolated fixed paths, sends once and never requests future turns or real transport',async()=>{
 let calls=0
 for(const op of ['interview_start','interview_answer','interview_end'])await workbenchRequest(op,'a'.repeat(64),{},async(path,o)=>{calls++;assert.equal(path,'/api/live/workbench/'+op);assert.equal(o.method,'POST');return {ok:true,json:async()=>({data:source})}})
 await assert.rejects(workbenchRequest('interview_answer','a'.repeat(64),{},async()=>{calls++;throw Error('lost')}),e=>e.code==='uncertain');assert.equal(calls,4)
 for(const path of ['interview?interview_id='+iid+'&turn=5','interview?interview_id=../other','/api/sdk/interview'])await assert.rejects(workbenchRequest(path,'a'.repeat(64),undefined,()=>{throw Error('must not dispatch')}))
 await assert.rejects(workbenchRequest('interview?interview_id='+iid,'a'.repeat(64),undefined,async()=>({ok:true,json:async()=>({data:{...source,source_kind:'real_model_output'}})})),/来源或调用边界/)
})
test('pending interview answer and context choice survive reload exactly, without broader fields',()=>{
 const values=new Map(),s={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)},token=addWorkbenchSession(s,webcrypto,'2026-11-03').active
 for(const [operation,extra] of [['interview_start',{mode:'full',include_learning_evidence:false}],['interview_answer',{interview_id:iid,question_turn_id:qid,answer:'保留的草稿'}],['interview_end',{interview_id:iid}]]){
  const pending={operation,body:{request_id,expected_revision:2,...extra},startedAt:new Date().toISOString()};patchWorkbenchSession(s,token,{pending});assert.deepEqual(readWorkbenchRegistry(s).entries[0].pending,pending)
 }
 const before=JSON.stringify([...values]);for(const extra of [{mode:'full',include_learning_evidence:'yes'},{mode:'other',include_learning_evidence:false},{mode:'full',include_learning_evidence:false,api_key:'extra'}])assert.throws(()=>patchWorkbenchSession(s,token,{pending:{operation:'interview_start',body:{request_id,expected_revision:2,...extra},startedAt:new Date().toISOString()}}))
 assert.equal(JSON.stringify([...values]),before)
})
test('interview sources cite the correct JD and preceding answer, with reference guidance only in the review',async()=>{
 const cache=join(root,'node_modules','.cache');await mkdir(cache,{recursive:true});const dir=await mkdtemp(join(cache,'workbench-interview-'))
 try{
  const result=await build({root,configFile:resolve(root,'vite.config.ts'),logLevel:'silent',build:{ssr:resolve(root,'src/components/WorkbenchInterviewEvidence.tsx'),write:false,minify:false}})
  const output=Array.isArray(result)?result[0].output:result.output,entry=join(dir,'view.mjs');await writeFile(entry,output.find(x=>x.type==='chunk'&&x.isEntry).code)
  const {WorkbenchInterviewReport,InterviewQuestionBasis}=await import(pathToFileURL(entry))
  const fixture=JSON.parse(await readFile(join(root,'tests/fixtures/workbench-interview.json'),'utf8'))
  assert.equal(fixture.before.report,null);assert.equal(fixture.before.turns.length,1);assert.ok(!JSON.stringify(fixture.before).includes('reference_outline'))
  const jd=[
    {requirement_id:'JD-07',category:'requirement',jd_quote:'2、能说明方案假设、核对依据和未验证边界，愿意学习工程方法。'},
    {requirement_id:'JD-06',category:'requirement',jd_quote:'1、具备Python和基础SQL能力，能用小样本说明结果。'},
    {requirement_id:'JD-09',category:'context',jd_quote:'无关的面试城市'},
  ]
  const turns=fixture.transcript
  const follow=turns.find(turn=>turn.role==='assistant'&&turn.is_followup)
  const previous=turns.find(turn=>turn.turn_id===follow.parent_answer_id)
  const basis=(question, source=turns)=>renderToStaticMarkup(React.createElement(InterviewQuestionBasis,{question,jd,turns:source}))
  const current=basis(fixture.before.current_question)
  assert.match(current,/查看出题依据/);assert.match(current,/具备Python和基础SQL能力/)
  assert.doesNotMatch(current,/无关的面试城市|改进建议|参考回答思路|接续的回答/)
  const followHtml=basis(follow)
  assert.ok(followHtml.includes(previous.text))
  assert.match(followHtml,/接续的回答.*预设位置的澄清追问/)
  const crossed=turns.map(turn=>turn===previous?{...turn,interview_id:'different'}:turn)
  const unavailable=basis(follow,crossed)
  assert.match(unavailable,/关联的原回答暂不可用/)
  assert.ok(!unavailable.includes(previous.text))
  const mainWithPredecessor=turns.find(turn=>turn.role==='assistant'&&!turn.is_followup&&turn.parent_answer_id)
  assert.doesNotMatch(basis(mainWithPredecessor),/接续的回答/)
  const html=renderToStaticMarkup(React.createElement(WorkbenchInterviewReport,{report:fixture.report,jd,turns}))
  for(const s of ['岗位面试复盘','主问题作答进度','已答主问题','自定义回答 · 仅保存','内置待补充示例','SUM(DISTINCT 金额)','原回答片段','问题分析','改进建议','参考回答思路','未进行语义分析','查看原题、原回答与岗位依据','查看岗位方向覆盖'])assert.ok(html.includes(s),s)
  assert.doesNotMatch(html,/面试得分|能力上涨|100分/)
  const empty={...fixture.report,answered_count:0,answered_main:0,findings:[],issue_count:0,clear_sample_count:0,unreviewed_count:0,status:'ended_early',coverage:fixture.report.coverage.map(c=>({...c,asked:false,answered:false}))}
  const blank=renderToStaticMarkup(React.createElement(WorkbenchInterviewReport,{report:empty}))
  assert.match(blank,/尚未提交回答/);assert.doesNotMatch(blank,/原回答片段|参考回答思路/)
 }finally{await rm(dir,{recursive:true,force:true})}
})
