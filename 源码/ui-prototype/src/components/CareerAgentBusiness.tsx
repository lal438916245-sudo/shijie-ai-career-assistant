import {useEffect, useState} from 'react'
import {Button} from './ui/button'
import {Textarea} from './ui/textarea'
import {resumePreview} from '@/lib/simple-actions.mjs'

export default function CareerAgentBusiness({business, disabled, onAnswer, onSave}: {
  business: any; disabled: boolean
  onAnswer: (interview: any, answer: string) => Promise<boolean>
  onSave: (authorization: string, selected: string[]) => Promise<void>
}) {
  const [answer, setAnswer] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const interview = business?.interview
  const question = interview?.question
  const draft = business?.resume_draft
  useEffect(() => {setAnswer('')}, [question?.turn_id])
  useEffect(() => {
    const refs: any[] = [], ids: string[] = []
    for (const item of draft?.candidate.items ?? []) {
      if (!draft.selectable_item_ids.includes(item.item_id)) continue
      const ref = item.original_ref
      if (refs.some(other => ref.start < other.end && other.start < ref.end)) continue
      refs.push(ref); ids.push(item.item_id)
    }
    setSelected(ids)
  }, [draft?.authorization_id])
  let preview = draft?.saved_text ?? draft?.original_text ?? ''
  let previewError = ''
  try {if (draft && !draft.saved_resume_id) preview = resumePreview(draft.original_text, draft.candidate.items, selected)}
  catch {previewError = '修改位置需要重新核对，请保留原文。'}

  return <>
    {question && interview.waiting_for_user && <section className="agent-business">
      <h3>模拟面试 · 等待你的回答</h3>
      <p className="agent-preserve">{question.text}</p>
      <label>我的回答<Textarea value={answer} disabled={disabled} maxLength={6000} onChange={e => setAnswer(e.target.value)}/></label>
      <Button disabled={disabled || !answer.trim()} onClick={async () => {
        if (await onAnswer(interview, answer)) setAnswer('')
      }}>提交回答，复盘并继续</Button>
      <p className="wb-muted">提交后，智能体会读取真实作答、生成面试反馈，再调整后续任务。</p>
    </section>}
    {interview?.report?.model_application && <section className="agent-business">
      <h3>本轮面试复盘</h3>
      {interview.report.findings.map((finding: any, index: number) => <article key={index}>
        {finding.quote && <blockquote>{finding.quote}</blockquote>}
        <p className="agent-preserve">{finding.observation}</p>
        <p className="agent-preserve">{finding.suggestion}</p>
      </article>)}
    </section>}
    {draft && <section className="agent-business">
      <h3>{draft.saved_resume_id ? '已保存的优化简历' : '智能体生成的简历草稿'}</h3>
      <p>核对原文和修改依据，选择希望保存的条目。</p>
      <details><summary>查看原有简历</summary><p className="agent-preserve">{draft.original_text}</p></details>
      {draft.candidate.items.map((item: any) => <article className="agent-resume-item" key={item.item_id}>
        <label className="agent-choice"><input type="checkbox" checked={selected.includes(item.item_id)}
          disabled={disabled || Boolean(draft.saved_resume_id) || !draft.selectable_item_ids.includes(item.item_id)}
          onChange={e => setSelected(old => e.target.checked ? [...old, item.item_id] : old.filter(id => id !== item.item_id))}/>
          采用这条修改</label>
        <blockquote>{item.original_ref.quote}</blockquote>
        <p className="agent-preserve">{item.proposed_text}</p><p>{item.rationale}</p>
        {!draft.selectable_item_ids.includes(item.item_id) && <p>这条修改证据不足，保留原文。</p>}
      </article>)}
      {(draft.candidate.missing_evidence ?? []).map((item: string, index: number) => <p key={index}>待补材料　{item}</p>)}
      {previewError ? <p role="alert">{previewError}</p> : <details><summary>查看整份简历</summary><p className="agent-preserve">{preview}</p></details>}
      {!draft.saved_resume_id && <Button disabled={disabled || !draft.can_apply || !selected.length || Boolean(previewError)}
        onClick={() => onSave(draft.authorization_id, selected)}>已核对，保存此版简历</Button>}
      {!draft.saved_resume_id && !draft.can_apply && <p>资料已变化，这份草稿可查看，请让智能体根据最新材料重新生成。</p>}
    </section>}
  </>
}
