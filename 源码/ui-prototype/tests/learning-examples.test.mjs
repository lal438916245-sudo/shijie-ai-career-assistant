import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {learningExamples} from '../src/lib/learning-examples.mjs'

test('每个固定学习任务都有对应岗位依据与练习提示、参考思路和自查要点',()=>{
 const data=JSON.parse(readFileSync(new URL('../../examples/learning_journey_demo/scenario_03/journey.json',import.meta.url),'utf8'))
 assert.deepEqual(Object.keys(learningExamples).sort(),data.tasks.map(task=>task.task_id).sort())
 for(const task of data.tasks){
  const example=learningExamples[task.task_id]
  assert.ok(data.guides.some(g=>g.task_id===task.task_id&&g.exercise),task.task_id)
  for(const part of example.requirement.split('；'))assert.ok(data.session.job_description.includes(part),`${task.task_id}: ${part}`)
  assert.ok(example.reason&&example.hint&&example.answer,task.task_id)
  assert.ok(example.checks.length>=3&&example.checks.every(Boolean),task.task_id)
 }
})
