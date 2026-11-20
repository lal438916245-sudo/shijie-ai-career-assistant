import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {matchesRecord,recentRuns,resumeDraft,resumeDraftParts,resumeEdits} from '../src/lib/workbench-history.mjs'

const {report}=JSON.parse(await readFile(new URL('./fixtures/workbench-resume.json',import.meta.url),'utf8'))
test('draft only applies selected, approved and uniquely located original excerpts',()=>{
  const [item]=resumeEdits(report)
  assert.ok(item&&item.original_quote!==item.suggested_text)
  const base=resumeDraft(report,[],'小林（虚构）')
  const draft=resumeDraft(report,[item.item_id],'小林（虚构）')
  assert.ok(base.includes(item.original_quote)&&!base.includes(item.suggested_text))
  assert.ok(draft.includes(item.suggested_text)&&!draft.includes(item.original_quote))
  assert.ok(draft.includes('教育背景')&&draft.includes('课程实践'))
  assert.ok(draft.includes('没有生产Flink链路、商业上线和真实性能提升经历。'))
  const unsafe={...report,items:[...report.items,{...item,item_id:'overlap'}]}
  assert.equal(resumeEdits(unsafe).length,0)
  assert.equal(resumeEdits({...report,approved_texts:[]}).length,0)
  assert.equal(resumeEdits({...report,resume_text:report.resume_text+item.original_quote}).length,0)
  assert.equal(resumeDraft(report,report.items.filter(i=>i.status!=='suggested').map(i=>i.item_id),'小林（虚构）'),base)
})

test('history filters compose in Beijing time and an answer belongs to its assessed topics',()=>{
  const rows=[
    {kind:'assessment',created_at:'2026-11-03T16:05:00Z',payload:{event:'answer_submitted',kind:'week',
      topic_keys:['sql'],scope_snapshot:{kind:'week',tasks:[{topic_keys:['stream']}]}}},
    {kind:'learning_progress',created_at:'2026-11-03T15:59:59Z',payload:{progress:{task_id:'task-1'}}},
    {kind:'interview',created_at:'2026-11-04T08:00:00Z',payload:{event:'interview_report'}},
    {kind:'interview',created_at:'2026-11-04T08:00:00Z',payload:{event:'interview_turn'}},
  ]
  const tasks=[{task_id:'task-1',topic_keys:['sql']}]
  const select=patch=>rows.filter(row=>matchesRecord(row,{kind:'all',subject:'',date:'',task:'',...patch},tasks,[]))
  assert.deepEqual(select({kind:'week',subject:'sql',date:'2026-11-04'}),[rows[0]])
  assert.deepEqual(select({kind:'week',subject:'stream'}),[])
  assert.deepEqual(select({kind:'learning_progress',task:'task-1',date:'2026-11-03'}),[rows[1]])
  assert.deepEqual(select({kind:'interview_reports'}),[rows[2]])
})

test('compact history keeps every active run and the three newest finished runs',()=>{
  const rows=['completed','active','cancelled','completed','active','completed'].map((status,id)=>({status,id}))
  assert.deepEqual(recentRuns(rows).map(r=>r.id),[1,4,0,2,3])
})


test('draft highlights map to the same adopted text as the copied full draft',()=>{
  const [item]=resumeEdits(report)
  const chosen=[item.item_id]
  const parts=resumeDraftParts(report,chosen,'小林（虚构）')
  assert.equal(parts.map(part=>part.text).join(''),resumeDraft(report,chosen,'小林（虚构）'))
  assert.deepEqual(parts.filter(part=>part.itemId).map(part=>[part.itemId,part.text]),[[item.item_id,item.suggested_text]])
  assert.equal(resumeDraftParts(report,[],'小林（虚构）').filter(part=>part.itemId).length,0)
})
