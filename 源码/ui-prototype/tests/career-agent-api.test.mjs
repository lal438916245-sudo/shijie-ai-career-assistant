import test from 'node:test'
import assert from 'node:assert/strict'
import {agentRequest} from '../src/lib/career-agent-api.mjs'

test('agent requests keep personal session authorization and native agent provenance', async () => {
  const token = 'a'.repeat(64)
  const state = {source_kind: 'career_agent', tasks: [], runs: []}
  const requests = []
  const transport = async (url, options) => {
    requests.push({url, options})
    return {ok: true, json: async () => ({data: state})}
  }
  assert.deepEqual(await agentRequest('agent-state', token, undefined, transport), state)
  assert.equal(requests[0].url, '/api/live/workbench/agent-state')
  assert.equal(requests[0].options.headers['X-CP-Session'], token)
  const body = {request_id: 'original-request', goal: '准备面试'}
  await agentRequest('agent-run', token, body, transport)
  assert.deepEqual(JSON.parse(requests[1].options.body), body)
  await agentRequest('agent-answer-interview', token, {...body, answer: '用户真实回答'}, transport)
  assert.equal(requests[2].url, '/api/live/workbench/agent-answer-interview')
  assert.equal(JSON.parse(requests[2].options.body).answer, '用户真实回答')
  await agentRequest('agent-resume-apply', token, {authorization_id: 'saved-candidate', selected_item_ids: ['one']}, transport)
  assert.equal(requests[3].options.headers['X-CP-Session'], token)
  await assert.rejects(agentRequest('agent-state', 'invalid', undefined, transport))
  await assert.rejects(agentRequest('agent-unknown', token, {}, transport))
  await assert.rejects(agentRequest('agent-state', token, undefined, async () => ({ok: true,
    json: async () => ({data: {source_kind: 'competition_workbench_double'}})})), /来源无效/)
})

test('agent API surfaces model and session failures without resending', async () => {
  let requests = 0
  await assert.rejects(agentRequest('agent-run', 'b'.repeat(64), {}, async () => {
    requests++
    return {ok: false, json: async () => ({error: '本轮已在执行'})}
  }), /本轮已在执行/)
  assert.equal(requests, 1)
})
