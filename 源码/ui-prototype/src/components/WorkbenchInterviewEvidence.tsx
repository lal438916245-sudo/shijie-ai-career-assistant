import {ArrowRight, BookOpen, FileText, MessageCircle} from 'lucide-react'
import type {DiagnosisAudit} from './WorkbenchDiagnosis'
import {Button} from './ui/button'

export type InterviewJD = NonNullable<DiagnosisAudit['jd_items']>

type TurnBase = {turn_id: string; interview_id: string; text: string}
export type QuestionTurn = TurnBase & {
  role: 'assistant'
  title: string
  main_index: number
  is_followup: boolean
  parent_answer_id: string | null
  requirement_ids: string[]
  routing_notice: string
}
export type InterviewTurn = QuestionTurn | (TurnBase & {role: 'user'; question_turn_id: string})
type Finding = {
  finding_id: string; question_turn_id: string; answer_turn_id: string; title: string
  analysis_kind: 'needs_detail' | 'clear' | 'custom_unreviewed' | 'candidate_reviewed'
  quote: string; observation: string; issue: string | null; suggestion: string; reference_outline: string
  requirement_ids: string[]
}
type Report = {
  interview_id: string; position_title: string; status: 'completed' | 'ended_early'
  planned_main: number; answered_main: number; answered_count: number
  issue_count: number; clear_sample_count: number; unreviewed_count: number
  model_application?:{simulated:boolean};notice?:string;review_status?:string
  findings: Finding[]
  coverage: {key: string; title: string; planned: boolean; asked: boolean; answered: boolean}[]
}

const categories: Record<InterviewJD[number]['category'], string> = {
  responsibility: '岗位职责', requirement: '任职要求', bonus: '加分项', context: '岗位背景', unclassified: '岗位条目',
}
const analysisNames = {needs_detail: '待补充示例', clear: '清晰示例', custom_unreviewed: '自定义回答 · 已保存',candidate_reviewed:'候选分析 · 已核对采用'}
export const interviewQuestionLabel = (question: QuestionTurn) =>
  `主问题 ${question.main_index + 1}${question.is_followup ? ' · 追问' : ''}`

function JobRequirements({ids, jd}: {ids: string[]; jd: InterviewJD}) {
  return ids.length ? <ul className="wbi-job-sources">{ids.map(id => {
    const item = jd.find(row => row.requirement_id === id)
    return <li key={id}><strong>{item ? categories[item.category]+' · ' : ''}{id}</strong>
      <p className="wbi-preserve">{item?.jd_quote ?? '这条岗位原句暂不可用。'}</p></li>
  })}</ul> : <p>这轮暂无可核对的岗位条目引用。</p>
}

export function InterviewQuestionBasis({question, jd, turns}: {
  question: QuestionTurn; jd: InterviewJD; turns: InterviewTurn[]
}) {
  const previous = question.is_followup ? turns.find(turn => turn.role === 'user' &&
    turn.interview_id === question.interview_id && turn.turn_id === question.parent_answer_id) : undefined
  const parent = previous?.role === 'user' ? turns.find((turn): turn is QuestionTurn => turn.role === 'assistant' &&
    turn.interview_id === question.interview_id && turn.turn_id === previous.question_turn_id &&
    turn.main_index === question.main_index && !turn.is_followup) : undefined
  return <details className="wbi-basis">
    <summary>查看出题依据 <small>{question.requirement_ids.length} 条岗位引用{question.is_followup ? ' · 上一轮回答' : ''}</small></summary>
    <JobRequirements ids={question.requirement_ids} jd={jd}/>
    {question.is_followup && <div className="wbi-parent">
      <strong>接续的回答 · {parent?.title ?? '本轮对话记录'}</strong>
      {previous && parent ? <blockquote>{previous.text}</blockquote> : <p>关联的原回答暂不可用。</p>}
      <p className="wb-muted">{question.routing_notice}</p>
    </div>}
  </details>
}

export function WorkbenchInterviewReport({report, jd = [], turns = [], onPlan}: {
  report: Report; jd?: InterviewJD; turns?: InterviewTurn[]; onPlan?: () => void
}) {
  if(report.review_status==='pending_candidate_review')return <section className="wbi-report"><h2>回答已保存，复盘待核对采用。</h2><p role="status">{report.notice}</p><p>本次已保存 {report.answered_count} 轮回答。核对采用前不展示固定示例分析充当本次复盘。</p></section>
  const firstIssue = report.findings.findIndex(finding => finding.analysis_kind === 'needs_detail')
  const byId = new Map(turns.filter(turn => turn.interview_id === report.interview_id).map(turn => [turn.turn_id, turn]))
  return <section className="wbi-report">
    <span className="micro-label">JOB INTERVIEW · REFLECTION</span>
    <h2>岗位面试复盘</h2>
    <p>{report.position_title} · {report.status === 'completed' ? '按所选范围完成' : '主动提前结束'}</p>
    <div className="wbi-coverage-meter">
      <span>已答主问题 {report.answered_main}/{report.planned_main} · 共 {report.answered_count} 轮回答</span>
      <progress aria-label="主问题作答进度" value={report.answered_main} max={report.planned_main}/>
    </div>
    {!report.model_application&&<div className="wbi-report-stats">
      <div><strong>{report.issue_count}</strong><span>内置待补充示例</span></div>
      <div><strong>{report.clear_sample_count}</strong><span>内置清晰示例</span></div>
      <div><strong>{report.unreviewed_count}</strong><span>自定义回答 · 仅保存</span></div>
    </div>}
    <p className="wbi-notice">{report.model_application?report.notice:"复盘分析来自内置示例。自定义回答可对照参考思路自查，能力状态继续以考核与复测记录为准。"}</p>
    <h3>逐轮复盘</h3>
    {report.findings.length === 0 && <p>尚未提交回答。下方保留本轮岗位方向的覆盖情况。</p>}
    {report.findings.map((finding, index) => {
      const q = byId.get(finding.question_turn_id)
      const a = byId.get(finding.answer_turn_id)
      const question = q?.role === 'assistant' ? q : undefined
      const answer = a?.role === 'user' && a.question_turn_id === question?.turn_id ? a : undefined
      return <details className="wbi-finding" key={finding.finding_id} open={index === Math.max(0, firstIssue)}>
        <summary><span><small>{question ? interviewQuestionLabel(question) : `第 ${index+1} 轮回答`}</small> {finding.title}</span>
          <span className="wb-chip" data-kind={finding.analysis_kind}>{analysisNames[finding.analysis_kind]}</span></summary>
        <div className="wbi-review-grid">
          <section><h4><MessageCircle size={16} aria-hidden="true"/>问题分析</h4>
            {finding.issue && <strong>{finding.issue}</strong>}
            <p>{finding.observation}</p>
            {finding.quote && <blockquote><small>原回答片段</small>{finding.quote}</blockquote>}
          </section>
          <section><h4><FileText size={16} aria-hidden="true"/>改进建议</h4><p>{finding.suggestion}</p></section>
          <section><h4><BookOpen size={16} aria-hidden="true"/>参考回答思路</h4><p>{finding.reference_outline}</p>
            <small>按个人实际经历调整示例。</small></section>
        </div>
        <details className="wbi-original">
          <summary>查看原题、原回答与岗位依据</summary>
          {question && <><strong>原题</strong><p className="wbi-preserve">{question.text}</p></>}
          {answer && <><strong>原回答</strong><p className="wbi-preserve">{answer.text}</p></>}
          {(!question || !answer) && <p className="wb-muted">部分原对话暂不可用，可在统一面试记录核对。</p>}
          {question ? <InterviewQuestionBasis question={question} jd={jd} turns={turns}/> :
            <JobRequirements ids={finding.requirement_ids} jd={jd}/>}
        </details>
      </details>
    })}
    <details className="wbi-coverage-details">
      <summary>查看岗位方向覆盖</summary>
      <div className="wbi-coverage">{report.coverage.map(item => <div key={item.key}>
        <strong>{item.title}</strong><span>{item.answered ? '已回答' : item.asked ? '已提问 · 未回答' : item.planned ? '本轮尚未涉及' : '快速模式未安排'}</span>
      </div>)}</div>
    </details>
    {onPlan && <Button variant="outline" onClick={onPlan}>返回学习计划<ArrowRight size={15}/></Button>}
  </section>
}
