import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"

const local = readFileSync(new URL("../src/data/replay.json", import.meta.url), "utf8")
const source = readFileSync(new URL("../../examples/demo_replay/scenario_01/bundle.json", import.meta.url), "utf8")
const replay = JSON.parse(local)

test("前端固定快照与已验收的 Demo Replay 一致，保留人工整理来源声明", () => {
  assert.equal(local, source)
  assert.equal(replay.meta.disclosure.generator_type, "curated_demo")
  assert.equal(replay.meta.disclosure.model_name, null)
})

test("岗位差距、任务、题目、评分与状态具有完整关联，不出现悬空证据", () => {
  assert.ok(replay.gaps.length && replay.learning_tasks.length && replay.questions.length && replay.attempts.length)
  const gapIds = new Set(replay.gaps.map(gap => gap.gap_id))
  const taskIds = new Set(replay.learning_tasks.map(task => task.task_id))
  const questionIds = new Set(replay.questions.map(question => question.task_id))
  const attemptIds = new Set(replay.attempts.map(attempt => attempt.attempt_id))
  for (const task of replay.learning_tasks) { assert.ok(task.gap_ids.length); task.gap_ids.forEach(id => assert.ok(gapIds.has(id))) }
  for (const question of replay.questions) {
    assert.ok(question.source_task_ids.length)
    question.source_task_ids.forEach(id => assert.ok(taskIds.has(id)))
    question.gap_ids.forEach(id => assert.ok(gapIds.has(id)))
  }
  for (const attempt of replay.attempts) {
    assert.ok(questionIds.has(attempt.task_id))
    assert.equal(Math.round(attempt.rubric.reduce((sum, item) => sum + item.score * item.weight, 0)), attempt.score)
    assert.ok(replay.mastery_states.some(state => state.attempt_ids.at(-1) === attempt.attempt_id))
  }
  for (const state of replay.mastery_states) {
    assert.ok(gapIds.has(state.gap_id))
    state.attempt_ids.forEach(id => assert.ok(attemptIds.has(id)))
    state.task_ids.forEach(id => assert.ok(questionIds.has(id)))
  }
})
