export async function agentRequest(path, token, body, transport = fetch) {
  const reads = path === 'agent-state' && body === undefined
  const writes = ['agent-run', 'agent-cancel', 'agent-configure'].includes(path) && body !== undefined
  if ((!reads && !writes) || !/^[0-9a-f]{64}$/.test(token)) throw Error('智能体请求无效。')
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15000)
  try {
    const response = await transport('/api/live/workbench/' + path, {
      method: reads ? 'GET' : 'POST', cache: 'no-store', signal: controller.signal,
      headers: { 'X-CP-Session': token, ...(writes ? { 'Content-Type': 'application/json' } : {}) },
      ...(writes ? { body: JSON.stringify(body) } : {}),
    })
    const result = await response.json()
    if (!response.ok) {
      const error = new Error(result.error || '智能体操作未完成。')
      error.status = response.status
      throw error
    }
    if (result.data?.source_kind !== 'career_agent') throw Error('智能体响应来源无效。')
    return result.data
  } finally {
    clearTimeout(timeout)
  }
}
