import { useState, type FormEvent } from "react"
import { ArrowLeft, ArrowRight, BookOpen, Check, CheckCheck, Clock3, FileText, Save, ShieldCheck, Sparkles, Target } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Progress } from "@/components/ui/progress"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { toast } from "sonner"
import { usePendingEdits } from "@/components/WorkspaceQuality"
import { emptyDraft, SAMPLE_INPUT, validateDraft } from "@/lib/draft.mjs"

export type Draft = ReturnType<typeof emptyDraft>
type Props = { draft: Draft; onChange: (value: Draft) => void; onSave: () => boolean; onCreate: () => boolean; dirty:boolean; notice:string; saveError:string; onBack: () => void }

export function NewSession({ draft, onChange, onSave, onCreate, onBack, dirty, notice, saveError }: Props) {
  usePendingEdits("new-input",dirty)
  const [sampleOpen,setSampleOpen]=useState(false)
  const fillSample=()=>{onChange({...SAMPLE_INPUT});setErrors({});setSampleOpen(false);toast.success("已填入脱敏示例，尚未保存",{id:"sample-input"})}
  const requestSample=()=>{if(JSON.stringify(draft)===JSON.stringify(SAMPLE_INPUT)){toast.info("当前已经是脱敏示例",{id:"sample-input"});return}if(draft.role.trim()||draft.resume.trim()||draft.jd.trim())setSampleOpen(true);else fillSample()}
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [reviewOpen, setReviewOpen] = useState(false)
  const currentErrors = validateDraft(draft)
  const readiness = ["role", "resume", "jd", "days"].map(field => !currentErrors[field])
  const readyCount = readiness.filter(Boolean).length
  const update = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    onChange({ ...draft, [key]: value })
    if (errors[key]) setErrors(previous => ({ ...previous, [key]: "" }))
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const nextErrors = validateDraft(draft)
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length) {
      const first = Object.keys(nextErrors)[0]
      document.getElementById(first)?.focus()
      return
    }
    setReviewOpen(true)
  }
  return <div className="page-enter input-page">
    <button className="back-link" onClick={onBack}><ArrowLeft size={14} /> 返回成长概览</button>
    <section className="input-intro"><div><div className="eyebrow"><span /> YOUR NEXT CHAPTER</div><h1>新的方向，<span>从认识自己开始。</span></h1><p>告诉我们你走过的路，以及接下来想去的地方。</p></div><Badge variant="outline" className="local-only"><ShieldCheck size={13} /> 仅浏览器保存</Badge></section>
    <div className="form-stepper" aria-label="创建体验会话的流程"><div className="active"><b>01</b><span>准备成长资料</span></div><i /><div><b>02</b><span>预览目标与输入</span></div><i /><div><b>03</b><span>创建体验会话</span></div></div>

    <div className="input-layout"><Card className="form-card"><form onSubmit={submit} noValidate>
      <div className="form-card-heading"><div><h2>建立你的成长起点</h2><p>约 2 分钟，整理你的经历与目标。</p></div><Button type="button" variant="outline" size="sm" className="sample-button" onClick={requestSample}><Sparkles size={14} /> 使用脱敏示例</Button></div>
      <div className="target-fields"><div><Label htmlFor="role">目标岗位 <span className="required">*</span></Label><Input id="role" placeholder="例如：数据开发工程师" maxLength={120} value={draft.role} onChange={e => update("role", e.target.value)} aria-invalid={!!errors.role} aria-describedby={errors.role ? "role-error" : undefined} />{errors.role && <p className="field-error" id="role-error">{errors.role}</p>}</div><div className="duration-field"><Label htmlFor="days">学习时间 <span className="required">*</span></Label><div className="days-control"><Clock3 size={15} /><Input id="days" type="number" min={4} max={30} value={draft.days || ""} onChange={e => update("days", e.target.valueAsNumber || 0)} aria-invalid={!!errors.days} aria-describedby="days-hint" /><span>天</span></div><p id="days-hint" className={errors.days ? "field-error" : "field-hint"}>{errors.days || "4–30 天，按你的节奏来"}</p></div></div>

      <div className="document-fields"><section className="document-field"><div className="document-heading"><span className="document-number">01</span><div><Label htmlFor="resume">你的经历 <span className="required">*</span></Label><p>简历、项目经历或已有技能</p></div><FileText size={17} /></div><Textarea id="resume" placeholder="粘贴你的简历，或描述已有的技能、项目和实践经历……" value={draft.resume} onChange={e => update("resume", e.target.value)} maxLength={60000} aria-invalid={!!errors.resume} aria-describedby="resume-hint" /><div className="document-meta"><span id="resume-hint" className={errors.resume ? "field-error" : ""}>{errors.resume || "建议先移除姓名、电话等个人信息"}</span><span>{draft.resume.length} 字</span></div></section>
        <section className="document-field"><div className="document-heading"><span className="document-number jd">02</span><div><Label htmlFor="jd">目标岗位要求 <span className="required">*</span></Label><p>一份具体的 JD，让方向更清晰</p></div><Target size={17} /></div><Textarea id="jd" placeholder="粘贴目标岗位的职责、技能要求和任职条件……" value={draft.jd} onChange={e => update("jd", e.target.value)} maxLength={30000} aria-invalid={!!errors.jd} aria-describedby="jd-hint" /><div className="document-meta"><span id="jd-hint" className={errors.jd ? "field-error" : ""}>{errors.jd || "填写至少 20 字的岗位要求"}</span><span>{draft.jd.length} 字</span></div></section></div>
      <div className={`draft-save-state ${dirty?"dirty":""}`} role="status"><Save size={13}/>{dirty?"有未保存的修改":"暂无待保存的修改"}</div>{notice&&<div className="input-storage-feedback" role="status">{notice}</div>}{saveError&&<div className="input-storage-feedback error" role="alert">{saveError}</div>}
      <div className="form-actions"><p><ShieldCheck size={14} /> 本次只体验界面，不会发送资料或调用模型。</p><div><Button type="button" variant="outline" onClick={onSave}><Save size={15} /> 保存草稿</Button><Button type="submit" className="primary-cta">预览并创建 <ArrowRight size={15} /></Button></div></div>
    </form></Card>

      <aside className="input-aside"><Card className="readiness-card"><span className="aside-icon"><CheckCheck size={21} /></span><h3>好的成长，始于清晰的起点。</h3><p>把经历和目标放在一起，让接下来的每一步都有方向。</p><div className="readiness-heading"><span>输入准备度</span><strong>{readyCount} / 4</strong></div><Progress value={readyCount * 25} aria-label={`输入准备度：已完成 ${readyCount} 项，共 4 项`} /><div className="readiness-list">{["明确的目标岗位", "已有经历与技能", "具体的岗位要求", "适合自己的学习时间"].map((label, i) => <div key={label} className={readiness[i] ? "ready" : ""}><span>{readiness[i] ? <Check size={12} /> : <i />}</span>{label}</div>)}</div></Card>
        <div className="next-steps-card"><span className="eyebrow small">WHAT COMES NEXT</span><h3>你的资料，将连接到</h3><div><span><Target size={17} /></span><p><strong>岗位差距诊断</strong>找到最值得补齐的能力</p></div><div><span><BookOpen size={17} /></span><p><strong>针对性学习计划</strong>每条任务，都回应一个差距</p></div><div><span><ShieldCheck size={17} /></span><p><strong>可验证的成长证据</strong>从“学过”到“能够证明”</p></div><p className="prototype-note">这些步骤将在后续连接现有后端。本原型仅体验输入与页面交互。</p></div>
      </aside></div>
    <footer className="page-footer"><span>CAREER-PILOT <i /> 每一次出发，都值得认真</span><span>独立 UI 原型 · 不连接 Python 或数据库</span></footer>

    <Dialog open={sampleOpen} onOpenChange={setSampleOpen}><DialogContent className="sample-confirm-dialog"><DialogHeader><DialogTitle>改用脱敏示例？</DialogTitle><DialogDescription>示例会替换当前表单中的岗位、经历和岗位要求。已保存的草稿不会自动覆盖。</DialogDescription></DialogHeader><div className="guard-dialog-actions"><Button variant="outline" onClick={()=>setSampleOpen(false)}>保留当前输入</Button><Button onClick={fillSample}>使用示例</Button></div></DialogContent></Dialog>
    <Dialog open={reviewOpen} onOpenChange={setReviewOpen}><DialogContent className="review-dialog"><DialogHeader><span className="dialog-hero-icon"><BriefcaseIcon /></span><DialogTitle>准备好，开始新的成长旅程。</DialogTitle><DialogDescription>核对你的目标。确认后，仅在当前浏览器保存一份体验会话。</DialogDescription></DialogHeader><div className="preview-summary"><span>目标岗位</span><strong>{draft.role}</strong><div><span>学习周期</span><b>{draft.days} 天</b></div><div><span>经历文本</span><b>{draft.resume.length} 字</b></div><div><span>岗位要求</span><b>{draft.jd.length} 字</b></div></div><div className="prototype-confirmation"><ShieldCheck size={17} /><p>交互原型，不会创建真实数据库、执行岗位诊断或产生模型费用。</p></div>{saveError&&<p className="input-storage-feedback error" role="alert">{saveError}</p>}<DialogFooter><Button variant="outline" onClick={() => setReviewOpen(false)}>返回修改</Button><Button onClick={() => { if(onCreate())setReviewOpen(false) }}>确认创建体验会话 <ArrowRight size={14} /></Button></DialogFooter></DialogContent></Dialog>
  </div>
}

function BriefcaseIcon() { return <Target size={25} /> }
