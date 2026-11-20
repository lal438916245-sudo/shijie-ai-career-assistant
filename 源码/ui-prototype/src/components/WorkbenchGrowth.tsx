import {useEffect, useRef, useState} from 'react'
import {ArrowRight, History, RefreshCw} from 'lucide-react'
import {workbenchRequest} from '@/lib/workbench-api.mjs'
import {WorkbenchAttemptReport} from './WorkbenchAssessments'
import {Button} from './ui/button'
import {Card} from './ui/card'
import {Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle} from './ui/dialog'
import './workbench-growth.css'

type Scope = {session_id: string; case_id: string; trace_id: string; plan_id: string}
type Snapshot = {
  topic_id: string; topic_key: string; state: string; label: string; explanation: string
  distinct_passes: number; latest_attempt_id: string | null; latest_score: number | null
  evidence_ids: string[]; pending_ids: string[]
}
export type GrowthTopic = Snapshot & {title: string}
type AnswerKind = 'day' | 'week' | 'retest'
type Answer = {
  attempt_id: string; record_id: string; commit_seq: number; kind: AnswerKind
  scope: Scope; topic_keys: string[]; source_kind: string; run_mode: string; simulated: boolean
  model_application?: {application_id:string;record_id:string}
  grade: {status: 'scored' | 'review_required'; scores: {topic_key: string; score: number}[]}
}
type Projection = {application_id?:string;target_key?:string;stage?:string;trigger_attempt_id: string; before: Snapshot[]; after: Snapshot[]; rule_version: string}
type SavedRecord = {
  record_id: string; seq: number; created_at: string; kind: string; title: string; parent_ids: string[]
  envelope: Scope & {record_id: string; source_kind: string; evidence_use: string; run_mode: string; simulated: boolean}
  payload: {event?: string} & Partial<Answer & Projection>
}
type Point = {
  answer: Answer; title: string; savedAt: string; score: number | null
  update: {before: Snapshot; after: Snapshot; version: string} | null
}

const kindNames: Record<AnswerKind, string> = {day: '日考核', week: '周考核', retest: '专题复测'}
const stateTone: Record<string, string> = {
  mastered: 'green', provisional_pass: 'green', needs_retest: 'amber', regressed: 'amber', review_required: 'violet',
}
const scopeKeys = ['session_id', 'case_id', 'trace_id', 'plan_id'] as const
const sameScope = (scope: Scope, other?: Scope) => scopeKeys.every(key => scope[key] === other?.[key])
const savedTime = new Intl.DateTimeFormat('zh-CN', {timeZone: 'Asia/Shanghai', dateStyle: 'medium', timeStyle: 'short'})

export function buildGrowthHistory(records: SavedRecord[], scope: Scope, topic: GrowthTopic) {
  const answers = new Map<string, SavedRecord[]>()
  const projections = new Map<string, SavedRecord[]>()
  for (const record of records) {
    const {envelope, payload} = record
    if (!sameScope(scope, envelope) || envelope.record_id !== record.record_id ||
        envelope.run_mode !== 'demo' || envelope.simulated !== true) continue
    if (payload.event === 'answer_submitted' && payload.attempt_id &&
        envelope.source_kind === 'fixed_stub_output' && envelope.evidence_use === 'presentation_only') {
      answers.set(payload.attempt_id, [...(answers.get(payload.attempt_id) ?? []), record])
    }
    if (payload.event === 'demo_projection' && payload.trigger_attempt_id && record.kind === 'mastery' &&
        envelope.source_kind === 'deterministic_projection' && envelope.evidence_use === 'derived_mastery') {
      projections.set(payload.trigger_attempt_id, [...(projections.get(payload.trigger_attempt_id) ?? []), record])
    }
  }

  const pending = new Set(topic.pending_ids)
  const ids = new Set([...topic.evidence_ids, ...pending])
  const points: Point[] = []
  for (const id of ids) {
    const matches = answers.get(id)
    if (matches?.length !== 1) continue
    const record = matches[0]
    const answer = record.payload as Answer
    const needsReview = pending.has(id)
    if (!sameScope(scope, answer.scope) || answer.record_id !== record.record_id || answer.commit_seq !== record.seq ||
        answer.source_kind !== 'fixed_stub_output' || answer.run_mode !== 'demo' || answer.simulated !== true ||
        !answer.topic_keys?.includes(topic.topic_key) || !Object.hasOwn(kindNames, answer.kind) ||
        record.kind !== (answer.kind === 'retest' ? 'retest' : 'assessment') ||
        answer.grade?.status !== (needsReview ? 'review_required' : 'scored')) continue
    const application=answer.model_application
    if(application){
      const adopted=records.filter(row=>row.record_id===application.record_id&&sameScope(scope,row.envelope)&&row.envelope.source_kind==='user_review'&&row.envelope.evidence_use==='presentation_only'&&row.payload.event==='candidate_adopted'&&row.payload.application_id===application.application_id&&row.payload.target_key===id&&row.payload.stage==='c_grade')
      if(adopted.length!==1)continue
    }
    const score = needsReview ? null : answer.grade.scores.find(part => part.topic_key === topic.topic_key)?.score
    if (score !== null && (typeof score !== 'number' || !Number.isFinite(score) || score < 0 || score > 100)) continue

    const candidates = (projections.get(id)??[]).filter(row=>application?row.payload.application_id===application.application_id:!row.payload.application_id)
    const projection = candidates.length === 1 ? candidates[0] : undefined
    const isTopic = (snapshot: Snapshot) => snapshot.topic_id === topic.topic_id && snapshot.topic_key === topic.topic_key
    const before = projection?.payload.before?.find(isTopic)
    const after = projection?.payload.after?.find(isTopic)
    const version = projection?.payload.rule_version
    const membership = needsReview ? 'pending_ids' : 'evidence_ids'
    const update = projection && projection.seq > record.seq && projection.parent_ids.includes(record.record_id) && (!answer.model_application||projection.parent_ids.includes(answer.model_application.record_id)) &&
      before && after && version && (answer.model_application||!before[membership]?.includes(id)) && after[membership]?.includes(id) &&
      (answer.model_application||needsReview || (after.latest_attempt_id === id && after.latest_score === score))
      ? {before, after, version} : null
    points.push({answer, title: record.title, savedAt: record.created_at, score, update})
  }
  points.sort((a, b) => a.answer.commit_seq - b.answer.commit_seq)
  return {points, missing: ids.size - points.length}
}

function labelFor(point: Point, index: number) {
  return `第 ${index + 1} 次 · ${kindNames[point.answer.kind]} · ${point.score === null ? '待复核' : point.score+' 分'}`
}

export function GrowthTrend({points, onSelect}: {
  points: Point[]; onSelect: (point: Point, trigger: HTMLButtonElement) => void
}) {
  const lines = points.flatMap((point, index) => {
    const previous = points[index - 1]
    if (!previous || previous.score === null || point.score === null) return []
    return [{from: previous.score, to: point.score, index}]
  })
  return <figure className="wbg-trend" aria-label="专题答卷分项趋势">
    <div className="wbg-legend"><span><i className="day"/>日考核</span><span><i className="week"/>周考核</span><span><i className="retest"/>专题复测</span></div>
    <div className="wbg-graph">
      <div className="wbg-axis" aria-hidden="true">
        <span style={{top:'0%'}}>100</span><span style={{top:'40%'}}>60</span><span style={{top:'100%'}}>0</span>
      </div>
      <div className="wbg-scroll" tabIndex={0} role="region" aria-label="历史趋势图，可横向滚动">
        <div className="wbg-plot" style={{minWidth:points.length*64}}>
          <div className="wbg-score-space">
            {[0, 40, 100].map(top => <div className={'wbg-gridline '+(top===40?'is-pass':'')} style={{top:top+'%'}} key={top}/>)}
            <svg className="wbg-line" aria-hidden="true" viewBox={`0 0 ${points.length*100} 100`} preserveAspectRatio="none">
              {lines.map(({from,to,index}) => <line key={index} x1={100*index-50} y1={100-from} x2={100*index+50} y2={100-to}/>)}
            </svg>
            {points.map((point,index) => point.score !== null && <button
              key={point.answer.attempt_id} type="button" className="wbg-point" data-kind={point.answer.kind}
              style={{left:(index+.5)*100/points.length+'%',top:100-point.score+'%'}}
              aria-label={labelFor(point,index)} onClick={e=>onSelect(point,e.currentTarget)}>
              <span>{point.score}</span><i aria-hidden="true"/>
            </button>)}
          </div>
          <div className="wbg-ticks" style={{gridTemplateColumns:`repeat(${points.length}, minmax(0, 1fr))`}}>
            {points.map((point,index) => <div key={point.answer.attempt_id}>
              <span aria-hidden="true">{index+1}</span>
              {point.score === null && <button type="button" className="wbg-pending"
                aria-label={labelFor(point,index)} onClick={e=>onSelect(point,e.currentTarget)}>待复核</button>}
            </div>)}
          </div>
        </div>
      </div>
    </div>
    <figcaption>横轴为本专题的答卷提交顺序，虚线为 60 分通过线。待复核答卷单独列在轴下。</figcaption>
  </figure>
}

export function GrowthUpdate({point}: {point: Point}) {
  const update = point.update
  if (!update) return <section className="wbg-update"><h3>更新依据暂不可用</h3><p>可核对这份原始答卷。该次状态更新记录缺失或引用无法核对。</p></section>
  const {before, after} = update
  return <section className="wbg-update">
    <h3>本次状态更新依据</h3>
    <p><strong>{before.label}</strong> <span aria-label="变为">→</span> <strong>{after.label}</strong></p>
    <p>独立通过题面 {before.distinct_passes} → {after.distinct_passes} 道</p>
    {point.score === null && <p>本次分项待复核，待确认后才可计入有效成绩。</p>}
    <p>{after.explanation}</p>
    <small>规则 {update.version}</small>
  </section>
}

export default function WorkbenchGrowth({token, scope, revision, topics, completed, total, onRecords, onExam, onRetest}: {
  token: string; scope: Scope; revision: number; topics: GrowthTopic[]; completed: number; total: number
  onRecords: (subject: string) => void; onExam: () => void; onRetest: (topicId: string) => void
}) {
  const [activeId,setActiveId] = useState('')
  const [selected,setSelected] = useState<Point | null>(null)
  const [history,setHistory] = useState<SavedRecord[] | null>(null)
  const [error,setError] = useState('')
  const [retry,setRetry] = useState(0)
  const trigger = useRef<HTMLButtonElement | null>(null)
  const topic = topics.find(p => p.topic_id === activeId) ?? topics.find(p => p.evidence_ids.length || p.pending_ids.length) ?? topics[0]
  const hasHistory = topics.some(p => p.evidence_ids.length || p.pending_ids.length)

  useEffect(() => {
    if (!hasHistory) return
    let current = true
    setHistory(null)
    setError('')
    workbenchRequest('records',token).then(value => {
      if (!sameScope(scope,value.scope) || !Array.isArray(value.records)) throw Error('记录与当前会话不符，请重新读取。')
      if (current) setHistory(value.records)
    }).catch((e: Error) => { if (current) setError(e.message) })
    return () => {current = false}
  },[token,scope,revision,retry,hasHistory])

  const {points, missing} = topic && history ? buildGrowthHistory(history,scope,topic) : {points:[], missing:0}
  const selectPoint = (point: Point, button: HTMLButtonElement) => {
    trigger.current = button
    setSelected(point)
  }
  const topicHasHistory = Boolean(topic?.evidence_ids.length || topic?.pending_ids.length)

  return <>
    <Card className="multi-card wbg-summary">
      <div className="wb-section-heading"><div><span className="micro-label">TOPIC STATUS</span><h2>专题当前状态</h2></div><span className="wb-chip">学习进度 {completed}/{total} 项</span></div>
      <p>这里展示固定演示答卷的验证状态。学习完成度和岗位匹配参考单独记录。</p>
      <div className="wbg-matrix">
        {topics.map(p => <button key={p.topic_id} type="button" aria-pressed={p.topic_id === topic?.topic_id} onClick={()=>setActiveId(p.topic_id)}>
          <strong>{p.title}</strong>
          <span className="wbg-state" data-tone={stateTone[p.state] ?? 'neutral'}><i aria-hidden="true"/>{p.label}</span>
          <small>{p.latest_score === null ? '暂无有效分项' : '最近有效分项 '+p.latest_score+' 分'}</small>
        </button>)}
      </div>
      {!topic && <p>完成本会话的岗位诊断和学习计划后，即可查看专题。</p>}
    </Card>
    {topic && <Card className="multi-card wbg-history">
      <div className="wb-section-heading"><div><span className="micro-label">ASSESSMENT TIMELINE</span><h2>{topic.title} · 考核与复测变化</h2></div></div>
      <p>{topic.explanation}</p>
      {topic.pending_ids.length > 0 && <p className="wb-muted">另有 {topic.pending_ids.length} 份待复核分项。</p>}
      {topicHasHistory && (error ? <div role="alert"><p>{error}</p><Button variant="outline" onClick={()=>setRetry(value=>value+1)}><RefreshCw size={15}/>重新读取答卷</Button></div> :
        history === null ? <p role="status">正在读取本会话答卷…</p> : <>
          {points.length > 0 && <><p className="wb-muted">点选图上的分数或「待复核」，查看对应答卷和状态更新依据。</p><GrowthTrend points={points} onSelect={selectPoint}/></>}
          {missing > 0 && <p role="status">有 {missing} 份已引用答卷暂无法核对，图表仅显示已核对记录。</p>}
        </>)}
      {!topicHasHistory && <p className="wbg-empty">这个专题还没有已提交答卷。</p>}
      <div className="multi-actions">
        {['needs_retest','regressed','provisional_pass'].includes(topic.state) && <Button onClick={()=>onRetest(topic.topic_id)}>进入该专题复测<ArrowRight size={15}/></Button>}
        {!topicHasHistory && <Button onClick={onExam}>进入日周考核<ArrowRight size={15}/></Button>}
        <Button variant="outline" onClick={()=>onRecords(topic.topic_key)}><History size={15}/>查看统一答卷记录</Button>
      </div>
      <details className="wbg-rules"><summary>查看演示状态规则</summary>
        <ul>
          <li>每个专题按服务端提交顺序独立判断，分项 60 分及以上通过。</li>
          <li>最近失败后，一道独立题面通过为「暂时通过」，两道不同题面通过才满足演示掌握条件。</li>
          <li>有效失败清空通过积累；曾满足掌握条件后失败显示「出现回退」。</li>
          <li>待复核分项保留原有效证据。学习完成、阅读答案和面试反馈单独记录。</li>
        </ul>
        <p className="wb-muted">题面指纹可排除完全相同或仅空白不同的题面。规则 competition-demo-mastery-v1。</p>
      </details>
    </Card>}
    <Dialog open={selected!==null} onOpenChange={open=>{if(!open)setSelected(null)}}>
      {selected && <DialogContent className="wbg-dialog" onCloseAutoFocus={event=>{event.preventDefault();trigger.current?.focus()}}>
        <DialogHeader>
          <DialogTitle>{selected.title}</DialogTitle>
          <DialogDescription>{savedTime.format(new Date(selected.savedAt))} 北京时间 · 固定演示答卷</DialogDescription>
        </DialogHeader>
        <GrowthUpdate point={selected}/>
        <WorkbenchAttemptReport attempt={selected.answer}/>
      </DialogContent>}
    </Dialog>
  </>
}
