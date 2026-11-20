import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { assessmentForRound } from "../src/lib/assessment.mjs"
import { viewFromHash, VIEW_TITLES } from "../src/lib/routes.mjs"
const snapshot = JSON.parse(readFileSync(new URL("../src/data/replay.json", import.meta.url), "utf8"))

test("三轮考核通过身份关联到原题、记录和状态，不依赖数组排序", () => {
  const shuffled = structuredClone(snapshot)
  for (const field of ["questions", "attempts", "mastery_states"]) shuffled[field].reverse()
  for (const [round, questionId, attemptId, score, state] of [[0,2001,3001,55,"needs_retest"],[1,2002,3002,72,"provisional_pass"],[2,2003,3003,82,"mastered"]]) {
    const result = assessmentForRound(shuffled, round)
    assert.equal(result.question.task_id, questionId)
    assert.equal(result.attempt.attempt_id, attemptId)
    assert.equal(result.attempt.score, score)
    assert.equal(result.state.state, state)
    assert.equal(result.task.task_id, 1001)
  }
})

test("缺失或歧义证据拒绝展示，不能用其他题成绩兜底", () => {
  for (const mutate of [value => value.attempts.shift(), value => value.questions.push({...value.questions[0]}), value => value.mastery_states.shift(), value => value.learning_tasks.splice(0)]) {
    const broken = structuredClone(snapshot); mutate(broken)
    assert.throws(() => assessmentForRound(broken, 0))
  }
  assert.throws(() => assessmentForRound(snapshot, 3))
})

test("考核和复测直达路由保持页面身份，无效地址回到欢迎页", () => {
  for (const route of ["exam", "retest"]) {
    assert.equal(viewFromHash(`#${route}`), route)
    assert.equal(viewFromHash(`#/${route}`), route)
    assert.ok(VIEW_TITLES[route])
  }
  assert.equal(viewFromHash("#not-a-page"), "welcome")
})
