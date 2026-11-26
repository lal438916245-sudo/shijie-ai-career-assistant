import {useEffect, useRef, useState} from 'react'
import {Card} from './ui/card'
import {Button} from './ui/button'
import {Input} from './ui/input'
import {Textarea} from './ui/textarea'
import {agentRequest} from '@/lib/career-agent-api.mjs'
import './career-agent.css'

type Task = {task_id: string; title: string; action: string; success_criteria: string; status: string; result: string}
type Run = {run_id: string; status: string; summary: string; error: string; held_micro_cny: number}
type State = {
  enabled: boolean; plan_version: number; rationale: string; tasks: Task[]; runs: Run[]
  events: {seq: number; kind: string; content: any}[]
  model: {configured: boolean; revision: number; base_url: string; model: string; input_price: number | null; output_price: number | null; source: string; platform_available: boolean; user_key_saved: boolean; tools_supported: boolean}
}
const statuses: Record<string, string> = {
  running: '正在执行', cancel_requested: '正在停止', waiting_user: '等待你执行任务',
  completed: '已完成', pending: '待执行', blocked: '遇到阻碍', failed: '执行中断',
  limit_reached: '达到本轮上限', cancelled: '已停止', interrupted: '服务曾中断',
}
const tools: Record<string, string> = {
  read_context: '读取求职资料与任务', search_history: '检索历史记录',
  search_resources: '检索学习资源目录', check_resume_quotes: '核对简历原文', save_plan: '保存任务计划',
}

export default function CareerAgentPanel({token, onModelChange}: {token: string; onModelChange: () => Promise<void>}) {
  const [data, setData] = useState<State | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [goal, setGoal] = useState('结合我的简历、岗位要求和历史记录，安排下一步求职准备任务。')
  const [budget, setBudget] = useState('0.50')
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [config, setConfig] = useState({base_url: 'https://api.deepseek.com', model: 'deepseek-flash', api_key: '', input_price: '', output_price: ''})
  const flight = useRef(false)
  const latest = data?.runs[0]
  const running = Boolean(latest && ['running', 'cancel_requested'].includes(latest.status))
  const journal = 'shijie:career-agent:v1:' + token

  useEffect(() => {
    let disposed = false
    async function refresh() {
      try {
        const next = await agentRequest('agent-state', token)
        if (!disposed) setData(next)
      } catch (e) { if (!disposed) setError((e as Error).message) }
    }
    void refresh()
    const timer = setInterval(() => { void refresh() }, running ? 1500 : 10000)
    return () => { disposed = true; clearInterval(timer) }
  }, [token, running])

  useEffect(() => {
    if (!data) return
    setConfig(old => ({...old, base_url: data.model.source==='user' ? data.model.base_url : 'https://api.deepseek.com',
      model: data.model.source==='user' ? data.model.model : 'deepseek-flash',
      input_price: data.model.input_price === null ? '' : String(data.model.input_price),
      output_price: data.model.output_price === null ? '' : String(data.model.output_price)}))
  }, [data?.model.revision])

  async function send(path: string, body: any) {
    if (flight.current) return
    flight.current = true
    setBusy(true)
    setError('')
    try {
      const result = await agentRequest(path, token, body)
      setData(result)
      return result
    } catch (e) {
      const failure = e as Error & {status?: number}
      if (path === 'agent-run' && [400, 403, 404, 409].includes(failure.status ?? 0)) {
        localStorage.removeItem(journal)
      }
      setError(failure.message || '连接中断，请重新读取本轮结果。')
    }
    finally { flight.current = false; setBusy(false) }
  }

  async function run(feedback: {task_id: string; status: string; content: string} | null = null) {
    const amount = Math.round(Number(budget) * 1000000)
    if (!Number.isFinite(amount) || amount < 10000 || amount > 2000000) {
      setError('请填写0.01至2元之间的本轮费用上限。'); return
    }
    try {
      const pending = localStorage.getItem(journal)
      let body = pending ? JSON.parse(pending) : null
      if (body && data?.runs.some(r => r.run_id === body.request_id)) {
        localStorage.removeItem(journal)
        body = null
      }
      if (!body) body = {request_id: crypto.randomUUID(), goal, feedback, budget_micro_cny: amount}
      localStorage.setItem(journal, JSON.stringify(body))
      const result = await send('agent-run', body)
      if (result) {
        localStorage.removeItem(journal)
        if (feedback) setAnswers(old => ({...old, [feedback.task_id]: ''}))
      }
    } catch { setError('无法保存本次请求编号，请检查浏览器存储后再开始。') }
  }

  async function configure() {
    const result = await send('agent-configure', {...config,
      input_price: Number(config.input_price), output_price: Number(config.output_price),
      revision: data?.model.revision ?? 0})
    if (result) {setConfig(old => ({...old, api_key: ''})); await onModelChange()}
  }

  async function usePlatform() {
    const result=await send('model-platform',{revision:data?.model.revision})
    if(result){setConfig(old=>({...old,api_key:''}));await onModelChange()}
  }

  return <Card className="multi-card career-agent">
    <h2>求职准备智能体</h2>
    <p>根据你的资料和执行反馈规划任务，调用工具核对证据，并调整后续安排。</p>
    {error && <p role="alert" className="multi-error">{error}</p>}
    {!data ? <p role="status">正在读取智能体状态…</p> : <>
      <h3>全平台模型连接</h3>
      <p>当前使用{data.model.source==='user'?'自己的API':'平台内置API'}{data.model.configured?' · '+data.model.model:' · 连接尚未就绪'}。此配置用于岗位诊断、简历优化、模拟面试和智能体。</p>
      <details open={!data.model.configured}>
        <summary>{data.model.source==='user'?'修改自己的API连接':'使用自己的API'}</summary>
        <div className="agent-config-grid">
          <label>服务地址<Input value={config.base_url} disabled={running} onChange={e => setConfig({...config, base_url: e.target.value})}/></label>
          <label>模型名称<Input value={config.model} disabled={running} onChange={e => setConfig({...config, model: e.target.value})}/></label>
          <label>API Key<Input type="password" autoComplete="off" value={config.api_key} disabled={running} onChange={e => setConfig({...config, api_key: e.target.value})} placeholder={data.model.user_key_saved ? '留空保留自己的密钥' : '输入你的API Key'}/></label>
          <label>每百万输入 token 单价（元）<Input type="number" min="0.001" step="any" value={config.input_price} onChange={e => setConfig({...config, input_price: e.target.value})}/></label>
          <label>每百万输出 token 单价（元）<Input type="number" min="0.001" step="any" value={config.output_price} onChange={e => setConfig({...config, output_price: e.target.value})}/></label>
        </div>
        <p className="wb-muted">密钥由当前 Windows 用户加密保存在本机。运行时发送本次资料及所选历史记录，费用按填写的单价预占。</p>
        <Button variant="outline" disabled={busy || running} onClick={configure}>保存并用于所有功能</Button>
      </details>
      {data.model.source==='user'&&<Button variant="outline" disabled={busy||running||!data.model.platform_available} onClick={usePlatform}>恢复平台内置API</Button>}
      {!data.enabled && <p role="status">当前处于离线模式，请通过“智能体启动.cmd”进入联网智能体。</p>}
      {data.model.configured&&!data.model.tools_supported&&<p role="status">平台网关的智能体连接待升级。可先使用诊断、简历和面试，或填写自己的API用于全部功能。</p>}
      <label>本轮目标<Textarea value={goal} maxLength={1800} disabled={running} onChange={e => setGoal(e.target.value)}/></label>
      <div className="agent-run-controls">
        <label>本轮费用上限（元）<Input type="number" min="0.01" max="2" step="0.01" value={budget} disabled={running} onChange={e => setBudget(e.target.value)}/></label>
        <Button disabled={busy || running || !data.enabled || !data.model.configured || !data.model.tools_supported || goal.trim().length < 2} onClick={() => run()}>开始自主规划</Button>
        {running && latest && <Button variant="outline" disabled={busy || latest.status === 'cancel_requested'} onClick={() => send('agent-cancel', {run_id: latest.run_id})}>停止本轮</Button>}
      </div>
      {latest && <section aria-live="polite">
        <p><strong>{statuses[latest.status] ?? latest.status}</strong> · 已记账及预占 {(latest.held_micro_cny / 1000000).toFixed(4)} 元</p>
        {latest.error && <p role="alert">{latest.error}</p>}
        {latest.summary && <p className="agent-preserve">{latest.summary}</p>}
      </section>}
      {data.tasks.length > 0 && <section>
        <h3>当前任务 · 第 {data.plan_version} 版</h3><p>{data.rationale}</p>
        {data.tasks.map(task => <article className="agent-task" key={task.task_id}>
          <h4>{task.title} <span>{statuses[task.status] ?? task.status}</span></h4>
          <p className="agent-preserve">{task.action}</p><p><strong>完成标准</strong>　{task.success_criteria}</p>
          {task.result && <p>你的反馈　{task.result}</p>}
          {task.status !== 'completed' && <>
            <label>执行结果或受阻原因<Textarea disabled={running} value={answers[task.task_id] ?? ''} maxLength={4000} onChange={e => setAnswers({...answers, [task.task_id]: e.target.value})}/></label>
            <div className="multi-actions">
              <Button disabled={busy || running || (answers[task.task_id]?.trim().length ?? 0) < 2} onClick={() => run({task_id: task.task_id, status: 'completed', content: answers[task.task_id]})}>记录完成并安排下一步</Button>
              <Button variant="outline" disabled={busy || running || (answers[task.task_id]?.trim().length ?? 0) < 2} onClick={() => run({task_id: task.task_id, status: 'blocked', content: answers[task.task_id]})}>遇到阻碍，调整任务</Button>
            </div>
          </>}
        </article>)}
      </section>}
      <details><summary>工具调用与执行记录</summary>
        {[...data.events].reverse().filter(event => ['tool_call', 'tool_result', 'started'].includes(event.kind)).map(event => <article className="agent-event" key={event.seq}>
          <strong>{event.kind === 'started' ? '开始本轮任务' : (tools[event.content.name] ?? event.content.name) + (event.kind === 'tool_call' ? ' · 调用' : ' · 返回')}</strong>
          <pre>{JSON.stringify(event.content.arguments ?? event.content.result ?? event.content, null, 2)}</pre>
        </article>)}
        {!data.events.length && <p>开始一轮任务后，工具调用结果会显示在这里。</p>}
      </details>
    </>}
  </Card>
}
