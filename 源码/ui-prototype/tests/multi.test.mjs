import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createHash} from 'node:crypto'
import {validateMulti,multiAssessment,latestMultiState,multiRefs,initialMultiSchedule,parseMultiSchedule,editMultiSchedule,moveMultiStart,multiProgress,multiRoute,multiHash,MULTI_KEY} from '../src/lib/multi.mjs'
import {SCHEDULE_KEY} from '../src/lib/schedule.mjs'
const read=path=>readFileSync(new URL(path,import.meta.url),'utf8')
const core=JSON.parse(read('../src/data/multi-replay.json')),extra=JSON.parse(read('../src/data/multi-presentation.json'))
test('两套规范来源与校验和分别保留；新包及补充展示副本字节相同',()=>{
 for(const [scenario,local] of [['scenario_01','replay.json'],['scenario_02','multi-replay.json']]){const raw=read(`../../examples/demo_replay/${scenario}/bundle.json`),m=JSON.parse(read(`../../examples/demo_replay/${scenario}/manifest.json`));assert.equal(createHash('sha256').update(raw).digest('hex'),m.bundle_sha256);assert.equal(raw,read('../src/data/'+local))}
 const raw=read('../../examples/demo_replay/scenario_02/presentation.json'),m=JSON.parse(read('../../examples/demo_replay/scenario_02/presentation.manifest.json'));assert.equal(raw,read('../src/data/multi-presentation.json'));assert.equal(createHash('sha256').update(raw).digest('hex'),m.presentation_sha256);assert.equal(createHash('sha256').update(read('../src/data/multi-replay.json')).digest('hex'),m.core_sha256)
})
test('四专题、十任务、七份答卷以及四种状态与进度分母一致',()=>{
 assert.equal(validateMulti(core,extra),true);assert.equal(core.gaps.length,4);assert.equal(core.learning_tasks.length,10);assert.equal(core.questions.length,7);assert.equal(extra.answer_examples.length,7)
 assert.deepEqual(extra.topics.map(t=>latestMultiState(core,t.gap_id).state),['mastered','needs_retest','provisional_pass','learning']);assert.deepEqual(multiProgress(initialMultiSchedule(extra),extra),{total:10,completed:7,active:2,pending:1});assert.equal(core.tool_events.length,0)
})
test('同轮次按专题身份找题，乱序也不串成绩；无记录返回暂无',()=>{
 const shuffled=structuredClone(core);for(const key of ['questions','attempts','mastery_states'])shuffled[key].reverse()
 assert.equal(multiAssessment(shuffled,'GAP_MULTI_STREAM',2).attempt.score,82);assert.equal(multiAssessment(shuffled,'GAP_MULTI_SQL',2).attempt.score,54);assert.equal(multiAssessment(shuffled,'GAP_MULTI_MODEL',0).attempt.score,73);assert.equal(multiAssessment(shuffled,'GAP_MULTI_MODEL',1),null);assert.equal(multiAssessment(shuffled,'GAP_MULTI_ENGINEERING',0),null)
 assert.equal(latestMultiState(shuffled,'GAP_MULTI_SQL').state,'needs_retest')
})
test('考题跨专题、父题错误、重复轮次与作答歧义均拒绝',()=>{
 for(const mutate of [c=>c.questions[0].source_task_ids=[5101],c=>c.questions[1].parent_task_id=5211,c=>c.questions.push({...c.questions[0],task_id:5999}),c=>c.attempts.push({...c.attempts[0],attempt_id:5999}),c=>c.questions[1].question_fingerprint=c.questions[0].question_fingerprint]){const c=structuredClone(core);mutate(c);assert.throws(()=>validateMulti(c,extra))}
})
test('评分明细、权重、可信来源或状态引用被篡改即拒绝',()=>{
 for(const mutate of [c=>c.attempts[0].score=99,c=>c.attempts[0].rubric[0].weight=.9,c=>c.attempts[0].score_source='model_fallback',c=>c.mastery_states[0].attempt_ids=[5311],c=>c.mastery_states[0].task_ids=[5101]]){const c=structuredClone(core);mutate(c);assert.throws(()=>validateMulti(c,extra))}
})
test('补充合同拒绝未知根字段、错误案例和悬空简历输入引用',()=>{
 for(const mutate of [p=>p.secret=true,p=>p.scenario_id='other-case',p=>p.resume_edits[1].input_refs=['missing'],p=>p.answer_examples[0].attempt_id=5311,p=>p.topics[1].gap_id=p.topics[0].gap_id]){const p=structuredClone(extra);mutate(p);assert.throws(()=>validateMulti(core,p))}
})
test('E 只有一问一追问；F 的版本、任务与 D 的拦截来源可核查',()=>{
 for(const mutate of [p=>p.interview_dialogue.turns.pop(),p=>p.interview_dialogue.evidence_id='other',p=>p.interview_dialogue.feedback[0].refs=[{kind:'attempt',ref_id:'999'}],p=>p.plan_review.initial_version=p.plan_review.revised_version,p=>p.plan_review.issues[0].task_ids=[999]]){const p=structuredClone(extra);mutate(p);assert.throws(()=>validateMulti(core,p))}
 const blocked=structuredClone(core);blocked.resume_suggestions[2].suggestion='伪造项目';assert.throws(()=>validateMulti(blocked,extra));assert.equal(core.resume_suggestions[2].suggestion,null)
 assert.equal(multiRefs(core,extra,[{kind:'input',ref_id:'input:resume-sql'}])[0].record.kind,'resume');assert.throws(()=>multiRefs(core,extra,[{kind:'unknown',ref_id:'1'}]))
})
test('新案例按独立键恢复，旧案例、损坏或重复安排不被接受',()=>{
 assert.notEqual(MULTI_KEY,SCHEDULE_KEY);const schedule=initialMultiSchedule(extra);assert.deepEqual(parseMultiSchedule(JSON.stringify(schedule),extra),schedule)
 for(const mutate of [v=>v.caseId='PLAN_DEMO_STREAM_01',v=>v.entries[1].id=v.entries[0].id,v=>v.entries[0].end='invalid',v=>v.entries[0].minutes=0,v=>v.history=[{label:'x',at:'bad'}]]){const v=structuredClone(schedule);mutate(v);assert.equal(parseMultiSchedule(JSON.stringify(v),extra),null)}assert.equal(parseMultiSchedule('{broken',extra),null)
 const noisy={...schedule,secret:'discard',entries:schedule.entries.map(i=>({...i,extra:'discard'}))};assert.deepEqual(parseMultiSchedule(JSON.stringify(noisy),extra),schedule)
})
test('改期可顺延后续未完成安排，已完成日期及核心证据保持不变',()=>{
 const initial=initialMultiSchedule(extra),before=JSON.stringify(core);const edited=editMultiSchedule(initial,'multi-task-5108',{end:'2026-10-28',reason:'内容较难',shiftFollowing:true});assert.equal(edited.entries.find(i=>i.id==='multi-task-5109').start,'2026-10-29');assert.equal(edited.entries.find(i=>i.id==='multi-task-5107').start,initial.entries.find(i=>i.id==='multi-task-5107').start);assert.equal(JSON.stringify(core),before)
 const moved=moveMultiStart(initial,'2026-10-20');assert.equal(moved.entries.find(i=>i.id==='multi-task-5102').start,initial.entries.find(i=>i.id==='multi-task-5102').start);assert.equal(moved.entries.find(i=>i.id==='multi-task-5108').start,'2026-10-28')
})
test('任务进度可回退，笔记和日期校验有界，周复盘与弹性不计入学习分母',()=>{
 const schedule=initialMultiSchedule(extra);assert.equal(multiProgress(editMultiSchedule(schedule,'multi-weekly-14',{status:'completed'}),extra).completed,7);assert.equal(multiProgress(editMultiSchedule(schedule,'multi-task-5102',{status:'not_started'}),extra).completed,6)
 for(const patch of [{end:'2026-01-01'},{minutes:2},{note:'x'.repeat(1001)},{status:'mastered'},{task_id:1001},{start:'2101-01-01'}])assert.throws(()=>editMultiSchedule(schedule,'multi-task-5108',patch))
})
test('路由同时保存案例、专题和第二轮；旧案例直达保持隔离',()=>{
 assert.deepEqual(multiRoute(multiHash('retest','multi','sql',2)),{caseId:'multi',topic:'sql',round:2,invalidTopic:false});assert.equal(multiRoute(multiHash('plan','classic','sql')).caseId,'classic');assert.equal(multiRoute('#retest?topic=missing&round=9').topic,'stream');assert.equal(multiRoute('#retest?topic=missing').invalidTopic,true)
})
