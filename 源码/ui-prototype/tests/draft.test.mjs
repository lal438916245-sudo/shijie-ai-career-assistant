import test from "node:test"
import assert from "node:assert/strict"
import { emptyDraft, validateDraft, parseDraft, makePreviewSession, SAMPLE_INPUT, DRAFT_KEY } from "../src/lib/draft.mjs"

test("空输入逐字段提示，不创建体验会话", () => {
  assert.deepEqual(Object.keys(validateDraft(emptyDraft())).sort(), ["jd", "resume", "role"])
  assert.throws(() => makePreviewSession(emptyDraft(), "test"))
})

test("脱敏示例可创建浏览器原型会话，不包含后端身份或模型结果", () => {
  const session = makePreviewSession(SAMPLE_INPUT, "test")
  assert.equal(session.kind, "browser-prototype")
  assert.equal(session.status, "input_saved")
  assert.equal(session.id, "prototype:test")
  assert.equal("trace_id" in session, false)
  assert.equal("score" in session, false)
  assert.ok(DRAFT_KEY.includes("ui-prototype"))
})

test("天数、长度与最小输入量保持与现有业务边界一致", () => {
  for (const days of [0, 3, 31, 4.5, true, "14"]) assert.ok(validateDraft({ ...SAMPLE_INPUT, days }).days)
  for (const days of [4, 14, 30]) assert.equal(validateDraft({ ...SAMPLE_INPUT, days }).days, undefined)
  assert.ok(validateDraft({ ...SAMPLE_INPUT, role: "x".repeat(121) }).role)
  assert.ok(validateDraft({ ...SAMPLE_INPUT, resume: "short" }).resume)
})

test("损坏或异常本地草稿安全回退，额外字段不带入页面", () => {
  for (const value of ["{broken", "null", "[]", "{}", JSON.stringify({ ...SAMPLE_INPUT, days: 100 })]) assert.equal(parseDraft(value), null)
  const value = parseDraft(JSON.stringify({ ...SAMPLE_INPUT, apiKey: "never-store-this" }))
  assert.deepEqual(value, SAMPLE_INPUT)
})
