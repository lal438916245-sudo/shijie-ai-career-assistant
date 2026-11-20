import test from 'node:test'
import assert from 'node:assert/strict'
import {cedCall} from '../src/lib/ced-call-api.mjs'
import {WORKBENCH_KEY,readWorkbenchRegistry,patchWorkbenchSession} from '../src/lib/workbench-sessions.mjs'
import {resumeDraft,resumeEdits} from '../src/lib/workbench-history.mjs'
import {build} from 'vite'
import {fileURLToPath,pathToFileURL} from 'node:url'
import {join,resolve} from 'node:path'
import {mkdir,mkdtemp,writeFile,rm} from 'node:fs/promises'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

const token='a'.repeat(64),id='12345678-1234-1234-1234-123456789abc'
test('候选采用预览仅查询一次，拒收串会话的授权和执行响应',async()=>{
  const expected={source_kind:'competition_workbench_double',run_mode:'demo',simulated:true,real_dispatch_enabled:false,
    model_requests:0,mode:'ced_fixed_rehearsal',external_network_allowed:false,actual_model_cost:0,authorization_id:id}
  let calls=0
  const value=await cedCall('call_adoption_preview',token,{authorization_id:id},async(path,options)=>{
    calls++;assert.equal(path,'/api/live/workbench/call_adoption_preview');assert.deepEqual(JSON.parse(options.body),{authorization_id:id})
    return {ok:true,json:async()=>({data:expected})}
  })
  assert.equal(value.authorization_id,id);assert.equal(calls,1)
  await assert.rejects(cedCall('call_adoption_preview',token,{authorization_id:id},async()=>({ok:true,json:async()=>({data:{...expected,authorization_id:'another'}})})),e=>e.code==='source')
})

test('采用请求身份与确认可恢复，额外候选正文不能写入待确认记录',()=>{
  const memory=new Map(),storage={getItem:k=>memory.get(k)??null,setItem:(k,v)=>memory.set(k,v)}
  storage.setItem(WORKBENCH_KEY,JSON.stringify({version:1,active:token,entries:[{token,label:'体验',saved:true,start_date:'2026-11-06',createdAt:'2026-11-06T00:00:00Z',pending:null}]}))
  const pending={operation:'candidate_apply',startedAt:'2026-11-06T00:00:00Z',body:{request_id:id,expected_revision:10,
    authorization_id:id,candidate_digest:'b'.repeat(64),review_confirmed:true,selected_item_ids:['revision-1']}}
  patchWorkbenchSession(storage,token,{pending})
  assert.deepEqual(readWorkbenchRegistry(storage).entries[0].pending,pending)
  assert.throws(()=>patchWorkbenchSession(storage,token,{pending:{...pending,body:{...pending.body,candidate:{score:100}}}}))
  assert.throws(()=>patchWorkbenchSession(storage,token,{pending:{...pending,body:{...pending.body,review_confirmed:false}}}))
  assert.deepEqual(readWorkbenchRegistry(storage).entries[0].pending,pending)
})

test('正式简历按Unicode引用定位重复原句，前后文本与整稿一致',()=>{
  const original='😀练习。保留。练习。'
  const report={resume_text:original,items:[{item_id:'one',status:'suggested',original_quote:'练习。',
    original_ref:{start:7,end:10},suggested_text:'完成课程核对。'}],approved_texts:['完成课程核对。']}
  assert.equal(resumeEdits(report)[0].start,8)
  assert.equal(resumeDraft(report,['one'],''),'😀练习。保留。完成课程核对。')
  report.items[0].original_ref.start=6
  assert.equal(resumeEdits(report).length,0)
})

test('核对界面展示前后简历与引用，低置信评分不伪装通过，内容自动转义',async()=>{
  const root=fileURLToPath(new URL('..',import.meta.url)),cache=join(root,'node_modules','.cache')
  await mkdir(cache,{recursive:true});const dir=await mkdtemp(join(cache,'candidate-review-'))
  try{
    const {output}=await build({root,configFile:resolve(root,'vite.config.ts'),logLevel:'silent',build:{ssr:resolve(root,'src/components/WorkbenchCandidateReview.tsx'),write:false,minify:false}})
    const entry=join(dir,'view.mjs');await writeFile(entry,output.find(c=>c.type==='chunk'&&c.isEntry).code)
    const {WorkbenchCandidateReview}=await import(pathToFileURL(entry))
    const render=(stage,candidate)=>renderToStaticMarkup(React.createElement(WorkbenchCandidateReview,{stage,candidate}))
    const html=render('d_revision',{items:[{item_id:'one',server_status:'needs_human_verification',original_ref:{quote:'原文'},
      proposed_text:'课程练习<script>bad</script>',rationale:'依据材料',supporting_refs:[{quote:'课程小样本'}]}],missing_evidence:['尚无生产经历']})
    for(const text of ['原文','修改后','课程小样本','尚无生产经历','待本人确认事实'])assert.ok(html.includes(text))
    assert.ok(!html.includes('<script>')&&html.includes('&lt;script&gt;'))
    const full=render('d_revision',{revision_contract:'resume-self-report-first-v1',items:[],missing_evidence:[],full_draft_preview:'姓名\n教育背景\n<script>not executable</script>'})
    assert.ok(full.includes('完整简历候选预览（尚未保存）')&&full.includes('按下方勾选的修改生成'))
    assert.ok(full.includes('学习、考核和面试记录可选')&&full.includes('保留原稿'))
    assert.ok(!full.includes('<script>')&&full.includes('&lt;script&gt;'))
    const low=render('c_grade',{status:'needs_review',confidence:'low',topics:[],server_scores:[],feedback:'待核对'})
    assert.ok(low.includes('不能记作通过或失败'))
  }finally{assert.ok(dir.startsWith(cache));await rm(dir,{recursive:true,force:true})}
})
