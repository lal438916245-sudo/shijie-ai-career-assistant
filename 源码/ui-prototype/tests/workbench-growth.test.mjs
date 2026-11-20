import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath, pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

const root = fileURLToPath(new URL('..', import.meta.url))

test('growth trends select the exact answer and saved update, even with reviews and unrelated topics', async () => {
  const cache = join(root, 'node_modules', '.cache')
  await mkdir(cache, {recursive:true})
  const temp = await mkdtemp(join(cache, 'workbench-growth-'))
  try {
    const {output} = await build({root, logLevel:'silent', build:{
      ssr:join(root, 'src/components/WorkbenchGrowth.tsx'), write:false, minify:false,
    }})
    const entry = join(temp, 'view.mjs')
    await writeFile(entry, output.find(chunk => chunk.type==='chunk' && chunk.isEntry).code)
    const {buildGrowthHistory, GrowthTrend, GrowthUpdate} = await import(pathToFileURL(entry))
    const fixture = JSON.parse(await readFile(join(root, 'tests/fixtures/workbench-assessment.json'), 'utf8'))
    const {scope, attempt_id: firstId} = fixture.attempt
    const before = {...fixture.capabilities.find(cap => cap.topic_key==='sql'), label:'待首次验证',
      latest_attempt_id:null, latest_score:null, evidence_ids:[], pending_ids:[], distinct_passes:0}
    const reviewedId = 'ATTEMPT_'+'a'.repeat(24)
    const retestId = 'ATTEMPT_'+'b'.repeat(24)
    const failure = {...before, label:'待补强复测', latest_score:55, latest_attempt_id:firstId, evidence_ids:[firstId]}
    const reviewed = {...failure, pending_ids:[reviewedId]}
    const after = {...reviewed, label:'暂时通过', explanation:'目前仅一道独立题面通过，需再验证迁移能力。',
      evidence_ids:[firstId,retestId], latest_attempt_id:retestId, latest_score:72, distinct_passes:1}
    const records = []
    function append(id, kind, seq, prior, next, score) {
      const record_id = id+':saved'
      const projectionId = id+':projection'
      const envelope = {record_id,...scope,run_mode:'demo',simulated:true}
      const record = {record_id, seq, title:'题目与答卷', created_at:'2026-11-04T00:00:00Z',
        kind:kind==='retest'?'retest':'assessment', parent_ids:[],
        envelope:{...envelope,source_kind:'fixed_stub_output',evidence_use:'presentation_only'},
        payload:{...fixture.attempt,attempt_id:id,kind,record_id,commit_seq:seq,
          grade:{...fixture.attempt.grade,status:score===null?'review_required':'scored',scores:score===null?[]:[
            {topic_key:'model',score:99},{topic_key:'sql',score},
          ]}}}
      const projection = {record_id:projectionId,kind:'mastery',seq:seq+1,parent_ids:[record_id],
        envelope:{...envelope,record_id:projectionId,source_kind:'deterministic_projection',evidence_use:'derived_mastery'},
        payload:{event:'demo_projection',rule_version:'competition-demo-mastery-v1',trigger_attempt_id:id,before:[prior],after:[next]}}
      records.unshift(projection,record)
      return projection
    }
    append(firstId,'day',1,before,failure,55)
    append(reviewedId,'week',5,failure,reviewed,null)
    const update = append(retestId,'retest',10,reviewed,after,72)
    const {points,missing} = buildGrowthHistory(records,scope,after)
    assert.equal(missing,0)
    assert.deepEqual(points.map(p=>p.answer.attempt_id),[firstId,reviewedId,retestId])
    assert.deepEqual(points.map(p=>p.score),[55,null,72])
    assert.equal(points[1].update.after.latest_score,55)
    assert.equal(points[2].update.before.label,'待补强复测')
    assert.equal(points[2].update.after.label,'暂时通过')
    assert.match(points[2].answer.answer,/先核对粒度和金额/)
    const trend = renderToStaticMarkup(React.createElement(GrowthTrend,{points}))
    for(const text of ['第 1 次 · 日考核 · 55 分','第 2 次 · 周考核 · 待复核','第 3 次 · 专题复测 · 72 分','60 分通过线'])assert.ok(trend.includes(text),text)
    assert.doesNotMatch(trend,/<line /)
    const detail = renderToStaticMarkup(React.createElement(GrowthUpdate,{point:points[2]}))
    assert.match(detail,/待补强复测.*暂时通过.*0 → 1.*competition-demo-mastery-v1/)
    const answerRecord=records.find(r=>r.record_id===retestId+':saved')
    const appId='APPLICATION_example',appRecord='APPLICATION_example:adopted'
    answerRecord.payload.model_application={application_id:appId,record_id:appRecord}
    answerRecord.payload.grade.scores.find(v=>v.topic_key==='sql').score=70
    const adoption={record_id:appRecord,kind:'retest',seq:20,parent_ids:[answerRecord.record_id],
      envelope:{...answerRecord.envelope,record_id:appRecord,source_kind:'user_review'},
      payload:{event:'candidate_adopted',application_id:appId,target_key:retestId,stage:'c_grade'}}
    const adoptedProjection={...update,record_id:'adopted-projection',seq:21,parent_ids:[answerRecord.record_id,appRecord],
      envelope:{...update.envelope,record_id:'adopted-projection'},
      payload:{...update.payload,application_id:appId,before:[after],after:[{...after,latest_score:70}]}}
    records.push(adoption,adoptedProjection)
    const accepted=buildGrowthHistory(records,scope,{...after,latest_score:70})
    assert.equal(accepted.points[2].score,70)
    assert.equal(accepted.points[2].update.after.latest_score,70)
    records.splice(records.indexOf(adoption),1)
    assert.equal(buildGrowthHistory(records,scope,after).missing,1)
    records.splice(records.indexOf(adoptedProjection),1)
    delete answerRecord.payload.model_application
    answerRecord.payload.grade.scores.find(v=>v.topic_key==='sql').score=72
    update.parent_ids = [firstId+':saved']
    assert.equal(buildGrowthHistory(records,scope,after).points[2].update,null)
    const first = records.find(r=>r.record_id===firstId+':saved')
    first.envelope.session_id = 'different-session'
    assert.equal(buildGrowthHistory(records,scope,after).missing,1)
    assert.deepEqual(buildGrowthHistory(records,scope,{...after,evidence_ids:[],pending_ids:[]}).points,[])
  } finally {
    await rm(temp,{recursive:true,force:true})
  }
})
