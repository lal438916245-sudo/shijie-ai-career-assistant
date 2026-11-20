import test from 'node:test'
import assert from 'node:assert/strict'
import {showcaseRoute,showcaseHash} from '../src/lib/showcase-route.mjs'
import {WORKBENCH_KEY,ARCHIVED_WORKBENCH_KEY,importWorkbenchReplay,readWorkbenchRegistry,addWorkbenchSession} from '../src/lib/workbench-sessions.mjs'
import {webcrypto} from 'node:crypto'
test('historical cases exit through the current overview; old task identities never follow',()=>{
 for(const c of ['classic','multi','journey']){
  const route=showcaseRoute(`#plan?case=${c}&task=old&round=2`)
  assert.equal(route.view,'overview');assert.equal(route.archived,true)
  assert.equal(route.hash,'#overview?case=workflow&topic=sql')
 }
 assert.equal(showcaseRoute('#plan?case=workflow&task=TASK_123').hash,'#plan?case=workflow&topic=sql&task=TASK_123')
 assert.equal(showcaseHash('resume',{case:'multi',resume:'resume-1'}),'#resume?case=workflow&topic=sql&resume=resume-1')
})
test('new browser registry preserves archived bytes and explicit replay selection never borrows private sessions',()=>{
 const values=new Map([[ARCHIVED_WORKBENCH_KEY,'old-registry-bytes']]),storage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)}
 const sample={case_id:'career-pilot-showcase-20261107',token:'b'.repeat(64),label:'完整演示 · 林知远的14天成长',start_date:'2026-10-20',createdAt:'2026-11-07T00:00:00Z'}
 assert.notEqual(WORKBENCH_KEY,ARCHIVED_WORKBENCH_KEY)
 let value=importWorkbenchReplay(storage,sample);assert.equal(value.active,sample.token)
 const fresh=addWorkbenchSession(storage,webcrypto,'2026-11-07').active
 value=importWorkbenchReplay(storage,sample);assert.equal(value.active,fresh);assert.equal(value.entries.length,2)
 assert.equal(value.entries.find(e=>e.token===fresh).pending,null)
 value=importWorkbenchReplay(storage,sample,true);assert.equal(value.active,sample.token)
 assert.equal(values.get(ARCHIVED_WORKBENCH_KEY),'old-registry-bytes')
 const before=values.get(WORKBENCH_KEY)
 assert.throws(()=>importWorkbenchReplay(storage,{...sample,case_id:'old-case'}))
 assert.equal(values.get(WORKBENCH_KEY),before)
})
