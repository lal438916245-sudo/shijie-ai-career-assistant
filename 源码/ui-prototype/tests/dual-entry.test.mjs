import test from 'node:test'
import assert from 'node:assert/strict'
import {webcrypto} from 'node:crypto'
import {showcaseRoute,showcaseHash} from '../src/lib/showcase-route.mjs'
import {WORKBENCH_KEY,ARCHIVED_WORKBENCH_KEY,entryRegistry,readEntryRegistry,readWorkbenchRegistry,addPersonalWorkbenchSession,importWorkbenchReplay,rememberPersonalSelection,patchWorkbenchSession} from '../src/lib/workbench-sessions.mjs'
import {mkdir,mkdtemp,writeFile,rm} from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
const sample={case_id:'career-pilot-showcase-20261107',token:'a'.repeat(64),label:'完整演示 · 林知远的14天成长',start_date:'2026-10-20',createdAt:'2026-11-07T00:00:00Z'}
const memory=()=>{const m=new Map([[ARCHIVED_WORKBENCH_KEY,'preserve old bytes']]);return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)}}
test('entry route survives page and record navigation; unknown entry never becomes a third mode',()=>{
 for(const entry of ['demo','personal'])for(const view of ['overview','diagnosis','plan','exam','scenario','resume','records']){
  const hash=showcaseHash(view,{entry,record:'record-1'}),r=showcaseRoute(hash)
  assert.equal(r.entry,entry);assert.equal(r.hash,hash);assert.equal(r.view,view)
 }
 assert.equal(showcaseRoute('#new').entry,'personal');assert.equal(showcaseRoute('#overview').entry,'demo')
 assert.equal(showcaseRoute('#overview?entry=unknown').entry,'demo')
 assert.equal(showcaseRoute('#resume?case=multi&entry=personal&resume=old').entry,'demo')
})
test('demo is public replay; personal selection restores independently without deleting old sessions',()=>{
 const storage=memory();importWorkbenchReplay(storage,sample,true)
 const one=addPersonalWorkbenchSession(storage,webcrypto,'2026-11-13').active;rememberPersonalSelection(storage,one)
 const two=addPersonalWorkbenchSession(storage,webcrypto,'2026-11-13').active;rememberPersonalSelection(storage,one)
 importWorkbenchReplay(storage,sample,true)
 assert.equal(readEntryRegistry(storage,'demo').active,sample.token)
 assert.deepEqual(readEntryRegistry(storage,'demo').entries.map(e=>e.token),[sample.token])
 assert.equal(readEntryRegistry(storage,'personal').active,one)
 assert.deepEqual(readEntryRegistry(storage,'personal').entries.map(e=>e.token),[one,two])
 const before=storage.getItem(WORKBENCH_KEY);readEntryRegistry(storage,'demo');readEntryRegistry(storage,'personal')
 assert.equal(storage.getItem(WORKBENCH_KEY),before);assert.equal(storage.getItem(ARCHIVED_WORKBENCH_KEY),'preserve old bytes')
 assert.equal(readWorkbenchRegistry(storage).entries.length,3)
 assert.throws(()=>rememberPersonalSelection(storage,sample.token))
})
test('six reviewed D edits survive pending save/reload, extra candidate fields and seventh edit still fail',()=>{
 const storage=memory(),token=addPersonalWorkbenchSession(storage,webcrypto,'2026-11-13').active
 const pending={operation:'candidate_apply',body:{request_id:'11111111-1111-4111-8111-111111111111',expected_revision:5,
  authorization_id:'22222222-2222-4222-8222-222222222222',candidate_digest:'a'.repeat(64),review_confirmed:true,selected_item_ids:Array.from({length:6},(_,i)=>'revision-'+(i+1))},startedAt:new Date().toISOString()}
 patchWorkbenchSession(storage,token,{pending});assert.deepEqual(readEntryRegistry(storage,'personal').entries[0].pending,pending)
 assert.throws(()=>patchWorkbenchSession(storage,token,{pending:{...pending,body:{...pending.body,selected_item_ids:[...pending.body.selected_item_ids,'seventh']}}}))
 assert.throws(()=>patchWorkbenchSession(storage,token,{pending:{...pending,body:{...pending.body,candidate:{draft:'unreviewed'}}}}))
 assert.deepEqual(readWorkbenchRegistry(storage).entries[0].pending,pending)
})
test('real runtime opens C/E controls without legacy CE budget and clearly marks current source',async()=>{
 const root=resolve('.'),cache=join(root,'node_modules/.cache/dual-entry');await mkdir(cache,{recursive:true});const dir=await mkdtemp(join(cache,'views-'))
 try{
  async function load(component,key){
   const result=await build({root,configFile:join(root,'vite.config.ts'),logLevel:'silent',build:{ssr:join(root,'src/components/'+component),write:false,minify:false}})
   const file=join(dir,key+'.mjs');await writeFile(file,result.output.find(c=>c.type==='chunk'&&c.isEntry).code);return import(pathToFileURL(file))
  }
  const {default:Interview}=await load('WorkbenchInterview.tsx','interview')
  const common={token:'f'.repeat(64),data:{diagnosis:{audit:{jd_items:[]}},abf:{},session_runtime:{execution_mode:'real_model'},position:{title:'数据开发实习',jd_text:'SQL查询'},candidate:{display_name:'个人自述'},scope:{session_id:'s'},interviews:[]},busy:false,pending:false,onPrepareCall:()=>{},onAction:async()=>{},onDirty:()=>{},onRecords:()=>{},onPlan:()=>{},onDiagnose:()=>{}}
  const html=renderToStaticMarkup(React.createElement(Interview,{...common,initialInterview:''}))
  assert.match(html,/真实模型短面试/)
  const startButton=html.match(/<button\b[^>]*>确认范围，开始岗位面试/)
  assert.ok(startButton);assert.doesNotMatch(startButton[0],/\sdisabled(?:\s|=|>)/)
  assert.doesNotMatch(html,/岗位级固定对话/)
  const {default:Runtime}=await load('SessionRuntimePanel.tsx','runtime')
  const panel=renderToStaticMarkup(React.createElement(Runtime,{data:{runtime_capabilities:{outbound_enabled:true,model_configured:true,provider:'本地配置',model:'model-id'}},disabled:false,onOpen:async()=>{},onPrepare:()=>{}}))
  assert.match(panel,/本地模拟 · 不调用模型/);assert.match(panel,/真实模型 · 每次确认后单次调用/)
  assert.doesNotMatch(panel,/<option value="real_model" disabled/)
 }finally{assert.ok(dir.startsWith(cache));await rm(dir,{recursive:true,force:true})}
})
