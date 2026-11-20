import test from 'node:test'
import assert from 'node:assert/strict'
import {webcrypto} from 'node:crypto'
import {mkdir,mkdtemp,writeFile,rm} from 'node:fs/promises'
import {resolve,join} from 'node:path'
import {pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {addWorkbenchSession,patchWorkbenchSession,readWorkbenchRegistry} from '../src/lib/workbench-sessions.mjs'

test('short interview pending operation survives reload with exact consent body',()=>{
 const map=new Map(),storage={getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v)}
 const v=addWorkbenchSession(storage,webcrypto,'2026-11-13'),pending={operation:'interview_start',body:{request_id:'11111111-1111-4111-8111-111111111111',expected_revision:4,mode:'short',include_learning_evidence:false},startedAt:new Date().toISOString()}
 patchWorkbenchSession(storage,v.active,{pending});assert.deepEqual(readWorkbenchRegistry(storage).entries[0].pending,pending)
 assert.throws(()=>patchWorkbenchSession(storage,v.active,{pending:{...pending,body:{...pending.body,mode:'unlimited'}}}))
})

test('saved review feedback shows original evidence without a score, and interview defaults to one question',async()=>{
 const root=resolve('.'),cache=join(root,'node_modules/.cache/short-flow-tests');await mkdir(cache,{recursive:true});const temp=await mkdtemp(join(cache,'view-'))
 try{
  async function load(component,name){
   const r=await build({root,configFile:join(root,'vite.config.ts'),logLevel:'silent',build:{ssr:join(root,'src/components/'+component),write:false,minify:false}})
   const output=Array.isArray(r)?r[0].output:r.output,file=join(temp,name+'.mjs');await writeFile(file,output.find(c=>c.type==='chunk'&&c.isEntry).code);return import(pathToFileURL(file))
  }
  const {WorkbenchAttemptReport}=await load('WorkbenchAssessments.tsx','exam')
  const attempt={question:{prompt:'核对查询结果',parts:[{topic_key:'sql',reference:'核对唯一键'}]},answer:'我会核对结果',grade:{status:'needs_review',feedback:'评分待复核',version:'test'},attempt_id:'a',question_id:'q',plan_version:1,pending_feedback:{status:'needs_review',feedback:'请补充完整SQL和预期结果',notice:'未采用为分数',topics:[{topic_key:'sql',dimensions:[{key:'result',rationale:'还缺实现',evidence:[{quote:'我会核对结果'}]}]}]}}
  const html=renderToStaticMarkup(React.createElement(WorkbenchAttemptReport,{attempt}));assert.match(html,/已保存 · 待复核反馈/);assert.match(html,/请补充完整SQL和预期结果/);assert.match(html,/我会核对结果/);assert.doesNotMatch(html,/70 \/ 100/)
  const {default:Interview}=await load('WorkbenchInterview.tsx','interview')
  const data={diagnosis:{audit:{jd_items:[]}},candidate:{display_name:'虚构用户'},position:{title:'数据开发实习',jd_text:'SQL查询'},scope:{session_id:'s'},interviews:[]}
  const text=renderToStaticMarkup(React.createElement(Interview,{initialInterview:'',token:'b'.repeat(64),data,busy:false,pending:false,onPrepareCall:()=>{},onAction:async()=>{},onDirty:()=>{},onRecords:()=>{},onPlan:()=>{},onDiagnose:()=>{}}))
  assert.match(text,/<option value="short" selected="">/);assert.match(text,/1问1答后复盘/);assert.match(text,/2～3/)
 }finally{assert.ok(temp.startsWith(cache));await rm(temp,{recursive:true,force:true})}
})
