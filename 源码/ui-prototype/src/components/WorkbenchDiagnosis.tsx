import {ArrowRight, BriefcaseBusiness, FileText} from 'lucide-react'
import {Button} from './ui/button'
import {Card} from './ui/card'
import './workbench-diagnosis.css'

const statusLabels = {
  supported: '有证据支持',
  partial: '部分支持',
  not_provided: '待补充证据',
  explicit_absence: '明确尚无经验',
} as const

const categoryLabels = {
  responsibility: '岗位职责',
  requirement: '任职要求',
  bonus: '加分项',
  unclassified: '待分类要求',
} as const

type EvidenceStatus = keyof typeof statusLabels
type Category = keyof typeof categoryLabels
type JDItem = {requirement_id: string; category: Category | 'context'; jd_quote: string}
type AuditRow = {
  requirement_id: string
  label: string
  evidence_status: EvidenceStatus | 'not_applicable'
  resume_quotes: string[]
  rationale: string
  follow_up: string
  priority?: 'P0' | 'P1' | 'P2' | 'P3' | 'none'
}
export type DiagnosisAudit = {
  match_score: number
  score_reason: string
  score_label: string
  jd_items?: JDItem[]
  evidence_assessment: {requirements: AuditRow[]}
}

type Candidate = {display_name: string; resume_text: string}
type Position = {title: string; jd_text: string}
type Evidence = {row: AuditRow & {evidence_status: EvidenceStatus}; category: Category; jdQuote?: string}

const statusOrder = Object.keys(statusLabels) as EvidenceStatus[]
const categoryOrder = Object.keys(categoryLabels) as Category[]

function SourceComparison({candidate, position, jdItems}: {candidate: Candidate; position: Position; jdItems: JDItem[]}) {
  const resumeOverview = candidate.resume_text.match(/[^。！？\n]+[。！？]?/g)?.slice(0, 2).join('').trim()
  const jdSections = [
    {label: '主要职责', items: jdItems.filter(item => item.category === 'responsibility').slice(0, 2)},
    {label: '任职要求', items: jdItems.filter(item => item.category === 'requirement').slice(0, 2)},
  ].filter(section => section.items.length)
  const jdExcerpt = position.jd_text.split('\n').map(line => line.trim())
    .filter(line => line && line !== position.title).slice(0, 3).join('\n')
  return <section className="wbd-section" aria-labelledby="wbd-inputs">
    <h2 id="wbd-inputs">简历与岗位对照</h2>
    <div className="wb-evidence-grid wbd-sources">
      <Card className="multi-card wbd-source">
        <span className="wbd-source-label"><FileText size={17} aria-hidden="true"/> 简历概况</span>
        <h3>{candidate.display_name}</h3>
        <p>{resumeOverview || '暂无简历概况。'}</p>
        <details><summary>查看简历原文</summary><p className="wbd-quote">{candidate.resume_text || '暂无简历原文。'}</p></details>
      </Card>
      <Card className="multi-card wbd-source">
        <span className="wbd-source-label"><BriefcaseBusiness size={17} aria-hidden="true"/> 岗位描述（JD）</span>
        <h3>{position.title}</h3>
        {jdSections.length ? <div className="wbd-jd-preview">
          {jdSections.map(({label, items}) => <div key={label}>
            <strong>{label}</strong>
            <ul>{items.map(item => <li key={item.requirement_id}>{item.jd_quote.replace(/^\d+\s*[、.．)）]\s*/, '')}</li>)}</ul>
          </div>)}
        </div> : <p className="wbd-quote">{jdExcerpt || '暂无岗位描述摘录。'}</p>}
        <details><summary>查看完整 JD</summary><p className="wbd-quote">{position.jd_text || '暂无岗位描述原文。'}</p></details>
      </Card>
    </div>
  </section>
}

function EvidenceChart({evidence}: {evidence: Evidence[]}) {
  return <Card className="multi-card wbd-chart">
    <span className="micro-label">EVIDENCE COVERAGE</span>
    <h2>能力图 · 岗位证据覆盖</h2>
    <p className="wb-muted">按 JD 类别统计证据状态，每段表示本组条目占比。加分项单列，岗位背景和面试安排不计入。</p>
    {evidence.length ? <figure aria-label="岗位证据覆盖图">
      <ul className="wbd-legend" aria-label="图例">
        {statusOrder.map(status => <li key={status}><i className={status} aria-hidden="true"/>{statusLabels[status]}</li>)}
      </ul>
      {categoryOrder.map(category => {
        const entries = evidence.filter(item => item.category === category)
        if (!entries.length) return null
        const segments = statusOrder.map(status => ({
          status, count: entries.filter(item => item.row.evidence_status === status).length,
        })).filter(segment => segment.count > 0)
        const label = segments.map(({status, count}) => statusLabels[status]+' '+count+' 项').join('，')
        return <div className="wbd-chart-group" key={category}>
          <div><strong>{categoryLabels[category]}</strong><span>{entries.length} 项</span></div>
          <div className="wbd-bar" aria-hidden="true">
            {segments.map(({status, count}) => <span className={status} key={status} style={{flexGrow: count}}/>)}
          </div>
          <small>{label}</small>
        </div>
      })}
    </figure> : <p>当前没有可统计的岗位证据条目。</p>}
  </Card>
}

function EvidenceDetails({evidence}: {evidence: Evidence[]}) {
  return <Card className="multi-card wbd-details">
    <span className="micro-label">TRACE EVERY CLAIM</span>
    <h2>逐项证据</h2>
    <p>展开一项，对照 JD 原句、简历引用、判断依据和下一步。</p>
    {evidence.map(({row, category, jdQuote}, index) => <details key={row.requirement_id} open={index === 0}>
      <summary>
        <span className="wbd-row-name"><strong>{row.label}</strong><small>{categoryLabels[category]}</small></span>
        <span className={'wb-chip wbd-status '+row.evidence_status}>{statusLabels[row.evidence_status]}</span>
      </summary>
      <div className="wbd-row-body">
        <div className="wb-evidence-grid">
          <div><h3>JD 原句</h3>{jdQuote ? <blockquote className="wbd-quote">{jdQuote}</blockquote> : <p>该条原句未随结果保存，可在上方核对完整 JD。</p>}</div>
          <div><h3>简历引用</h3>{row.resume_quotes.length ? row.resume_quotes.map((quote, i) => <blockquote key={i}>{quote}</blockquote>) : <p>本项暂无对应的简历引用。</p>}</div>
        </div>
        <p><strong>判断依据</strong>　{row.rationale}</p>
        {row.follow_up && <p><strong>下一步</strong>　{row.follow_up}</p>}
      </div>
    </details>)}
    {!evidence.length && <p>暂无可查看的技能证据。</p>}
  </Card>
}

export default function WorkbenchDiagnosis({candidate, position, audit, busy, recover, hasPlan, onRun, onRecover, onPlan, personal=false}: {
  candidate: Candidate; position: Position; audit?: DiagnosisAudit; busy: boolean; recover: boolean; hasPlan: boolean
  onRun: () => void; onRecover: () => void; onPlan: () => void; personal?:boolean
}) {
  const jdItems = audit?.jd_items ?? []
  const jdById = new Map(jdItems.map(item => [item.requirement_id, item]))
  const evidence: Evidence[] = []
  for (const row of audit?.evidence_assessment.requirements ?? []) {
    const jd = jdById.get(row.requirement_id)
    if (row.evidence_status === 'not_applicable' || jd?.category === 'context') continue
    evidence.push({
      row: {...row, evidence_status: row.evidence_status},
      category: jd?.category ?? 'unclassified',
      jdQuote: jd?.jd_quote,
    })
  }
  const strengths = evidence.filter(({row, category}) => row.evidence_status === 'supported' && category !== 'bonus')
  const priorities = evidence.filter(({row, category}) => category !== 'bonus' && (row.priority === 'P0' || row.priority === 'P1'))

  return <>
    <SourceComparison candidate={candidate} position={position} jdItems={jdItems}/>
    {audit ? <>
      <div className="wb-evidence-grid wbd-results">
        <Card className="multi-card wbd-conclusion">
          <span className="micro-label">A · DIAGNOSIS</span>
          <h2>诊断结论</h2>
          <div className="wbd-score"><strong>{audit.match_score}<small> / 100</small></strong><span>{personal?'岗位匹配参考':'固定匹配参考'}</span></div>
          <p className="wb-muted">范围：简历材料与岗位要求的匹配。考核与复测的结果见成长状态。</p>
          <dl>
            <div><dt>简历已提供的基础</dt><dd>{strengths.map(({row}) => row.label).join('、') || '暂无充分的简历证据。'}</dd></div>
            <div><dt>优先验证</dt><dd>{priorities.map(({row}) => row.label).join('、') || '暂无标为高优先级的条目。'}</dd></div>
          </dl>
          <Button disabled={busy} onClick={onPlan}>{personal?'优化我的简历':hasPlan ? '查看本会话学习计划' : '带着本次诊断制定计划'}<ArrowRight size={16}/></Button>
          <details><summary>查看分数说明</summary><p>{audit.score_label}。</p><p>{audit.score_reason}</p></details>
        </Card>
        <EvidenceChart evidence={evidence}/>
      </div>
      <EvidenceDetails evidence={evidence}/>
    </> : <Card className="multi-card">
      <span className="micro-label">A · FIXED EVIDENCE AUDIT</span>
      <h2>诊断待完成</h2>
      <p>{personal?'点击后使用AI对照本次简历与岗位要求，结果会自动保存。':'核对上方资料后，运行固定示例查看岗位匹配结论和逐项证据。'}</p>
      {recover ? <Button disabled={busy} onClick={onRecover}>恢复中断步骤（不重发）</Button> :
        <Button disabled={busy} onClick={onRun}>{personal?'开始岗位诊断':'完成示例岗位诊断'}<ArrowRight size={16}/></Button>}
    </Card>}
  </>
}
