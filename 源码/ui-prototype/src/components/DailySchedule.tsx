import { useRef, useState } from "react"
import { ArrowRight, BookOpen, CalendarDays, Check, ChevronRight, Clock3, Flag, History, MoveRight, PencilLine, ShieldCheck } from "lucide-react"
import { usePendingEdits } from "@/components/WorkspaceQuality"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Textarea } from "@/components/ui/textarea"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { SCHEDULE_KEY, SCHEDULE_ITEMS, STATUS_LABELS, createSchedule, parseSchedule, setStudyStatus, saveStudyNote, adjustSchedule, moveScheduleStart, studyProgress, addDays, daysBetween, localToday } from "@/lib/schedule.mjs"
import "./daily-schedule.css"

type Schedule = ReturnType<typeof createSchedule>
type StudyStatus = "not_started" | "in_progress" | "completed"
type Props = { onExam: () => void; onRetest: () => void; onSource: () => void }
function loadSchedule() {
  try { const raw = localStorage.getItem(SCHEDULE_KEY); const restored = parseSchedule(raw); return { value:restored ?? createSchedule(),warning:raw !== null && !restored ? "本地安排未能读取，现显示初始示例；保存后将使用新安排。" : "" } }
  catch { return {value:createSchedule(),warning:"暂时无法读取浏览器记录，仍可在当前页面调整。"} }
}
function shortDate(date: string) { const [,month,day] = date.split("-"); return `${Number(month)}/${Number(day)}` }
function dateLabel(date: string) { const [,month,day] = date.split("-"); return `${Number(month)}月${Number(day)}日` }

export function DailySchedule({ onExam, onRetest, onSource }: Props) {
  const [initial] = useState(loadSchedule)
  const [schedule,setSchedule] = useState<Schedule>(initial.value)
  const [unsavedStorage,setUnsavedStorage]=useState(false)
  const [warning,setWarning] = useState(initial.warning)
  const focusRef=useRef<HTMLDivElement>(null)
  const [selected,setSelected] = useState(SCHEDULE_ITEMS[0].id)
  const [filter,setFilter] = useState("all")
  const [draftNotes,setDraftNotes] = useState<Record<string,string>>({})
  const [adjusting,setAdjusting] = useState(false)
  const [startDialog,setStartDialog] = useState(false)
  const [newAnchor,setNewAnchor] = useState(schedule.anchor)
  const [edit,setEdit] = useState({start:"",end:"",minutes:30,reason:"时间冲突",extra:"",shiftFollowing:false})
  const [editError,setEditError] = useState("")
  const item = SCHEDULE_ITEMS.find(candidate=>candidate.id === selected)!
  const entry = schedule.entries.find(candidate=>candidate.id === selected)!
  const note = draftNotes[selected] ?? entry.note
  const dirty = note !== entry.note
  usePendingEdits("study-notes",unsavedStorage||Object.entries(draftNotes).some(([id,value])=>value!==schedule.entries.find(record=>record.id===id)?.note))
  const progress = studyProgress(schedule)
  const unfinished = progress.total-progress.completed
  const visibleItems = SCHEDULE_ITEMS.filter(candidate=>filter !== "unfinished" || schedule.entries.find(record=>record.id === candidate.id)?.status !== "completed")
  const overlap = schedule.entries.filter(candidate=>candidate.id !== entry.id && candidate.start <= entry.end && candidate.end >= entry.start).length
  const update = (next:Schedule,message:string) => {
    setSchedule(next)
    try { localStorage.setItem(SCHEDULE_KEY,JSON.stringify(next)); setWarning(""); setUnsavedStorage(false); toast.success(message,{id:"schedule-save",description:"已保存在此浏览器；不改变演示评分和能力状态。"}) }
    catch { setUnsavedStorage(true); setWarning("当前改动尚未保存到浏览器，刷新可能丢失；可点击重试保存。"); toast.error("浏览器未能保存，改动暂留在当前页面。") }
  }
  const openAdjustment = () => { setEdit({start:entry.start,end:entry.end,minutes:entry.minutes,reason:"时间冲突",extra:"",shiftFollowing:false}); setEditError(""); setAdjusting(true) }
  const applyAdjustment = () => {
    try { const next = adjustSchedule(schedule,selected,{...edit,reason:`${edit.reason}${edit.extra.trim() ? `：${edit.extra.trim()}` : ""}`}); update(next,"学习安排已调整"); setAdjusting(false) }
    catch(error) { setEditError(error instanceof Error ? error.message : "请检查安排") }
  }
  const setStatus = (status:StudyStatus) => {
    const next=setStudyStatus(schedule,selected,status); update(next,`已标记为${STATUS_LABELS[status]}`)
    if (filter === "unfinished" && status === "completed") { const following=next.entries.find(record=>record.status !== "completed"); if (following) setSelected(following.id) }
  }
  const chooseFilter = (next:string) => { setFilter(next); if (next === "unfinished" && entry.status === "completed") { const following=schedule.entries.find(record=>record.status !== "completed"); if (following) setSelected(following.id) } }
  return <div className="daily-schedule">
    <div className="schedule-disclosure"><CalendarDays size={16} /><p><strong>可调整的一周示例</strong> · 围绕现有专题人工编排，尚非模型生成的完整计划。日期、进度与笔记只保存在此浏览器。</p></div>
    {warning && <div className="schedule-warning" role="status"><span>{warning}</span><Button variant="outline" size="sm" onClick={()=>update(schedule,"安排已重新保存")}>重试保存</Button></div>}
    <Card className="schedule-progress"><div><span className="micro-label">第 1 周 · 实时数据链路</span><h3>按自己的节奏，把学习落实到每天。</h3><p>时间有冲突就改期，内容较难就多留一天。</p></div><div className="schedule-progress-metric"><strong>{progress.completed}<small> / {progress.total}</small></strong><span>学习任务已完成</span></div><Progress value={progress.percent} aria-label={`学习任务完成 ${progress.completed} 项，共 ${progress.total} 项`} /><div className="schedule-progress-meta"><span>{progress.active} 项学习中 · {unfinished} 项未完成</span><span>周检查单独记录 · 完成任务 ≠ 已掌握</span></div></Card>
    <div className="schedule-toolbar"><div><Button variant={filter === "all" ? "secondary" : "ghost"} size="sm" onClick={()=>chooseFilter("all")}>全部安排</Button><Button variant={filter === "unfinished" ? "secondary" : "ghost"} size="sm" onClick={()=>chooseFilter("unfinished")}>仅看未完成</Button></div><button onClick={()=>{setNewAnchor(schedule.anchor);setEditError("");setStartDialog(true)}}><CalendarDays size={13} /> 调整计划起点</button></div>
    <div className={`schedule-board ${visibleItems.length===0?"empty":""}`}><nav className="schedule-days" aria-label="每日学习安排">{visibleItems.map(candidate=>{const record=schedule.entries.find(value=>value.id === candidate.id)!; return <button key={candidate.id} className={selected === candidate.id ? "selected" : ""} aria-pressed={selected === candidate.id} onClick={()=>setSelected(candidate.id)}><span className={`schedule-day-icon ${record.status}`}>{candidate.kind === "weekly" ? <Flag size={16} /> : record.status === "completed" ? <Check size={16} /> : <b>{String(candidate.day).padStart(2,"0")}</b>}</span><span><strong>{candidate.kind === "weekly" ? "本周检查" : `学习日 ${candidate.day}`}</strong><small>{shortDate(record.start)}{record.end !== record.start ? `—${shortDate(record.end)}` : ""}</small><i className={`schedule-status-text ${record.status}`}>{STATUS_LABELS[record.status]}</i></span><ChevronRight size={13} /></button>})}{visibleItems.length === 0 && <p className="schedule-empty">所有安排都已完成，可切回全部安排查看。</p>}</nav>
      {visibleItems.length===0?<div className="schedule-empty-panel" role="status"><h3>当前没有未完成安排。</h3><p>可以回看学习记录，或前往本周检查。任务完成情况与能力验证仍分别记录。</p><Button variant="outline" onClick={()=>chooseFilter("all")}>查看全部安排 <ArrowRight size={13}/></Button></div>:<Card ref={focusRef} className={`schedule-focus ${item.kind === "weekly" ? "weekly" : ""}`}><div className="schedule-focus-top"><span className="micro-label">{item.kind === "weekly" ? "WEEKLY CHECKPOINT · 每周检查" : `DAILY LEARNING · 学习日 ${item.day}`}</span><button aria-label="调整当前任务安排" onClick={openAdjustment}><PencilLine size={14} /> 调整安排</button></div><h2>{item.title}</h2><div className="schedule-timing"><span><CalendarDays size={13} />{dateLabel(entry.start)}{entry.end !== entry.start ? ` 至 ${dateLabel(entry.end)}` : ""}</span><span><Clock3 size={13} />预计投入 {entry.minutes} 分钟{entry.end !== entry.start ? ` · 分 ${daysBetween(entry.start,entry.end)+1} 天学习` : ""}</span></div>{entry.end < localToday() && entry.status !== "completed" && <p className="schedule-overdue">这项安排尚未完成，可以继续学习或调整日期。</p>}{overlap > 0 && <p className="schedule-overlap">这段时间还有 {overlap} 项安排；可按精力调整，系统不会自动覆盖。</p>}
      <div className="schedule-status-control" role="group" aria-label="当前任务进度">{(Object.keys(STATUS_LABELS) as StudyStatus[]).map(status=><button key={status} aria-pressed={entry.status === status} className={entry.status === status ? `active ${status}` : ""} disabled={entry.status===status} onClick={()=>setStatus(status)}>{status === "completed" && <Check size={12} />}{STATUS_LABELS[status]}</button>)}</div>
      <div className="schedule-goal"><span className="micro-label">{item.kind === "weekly" ? "本周检查目标" : "本次学习目标"}</span><p>{item.goal}</p><div className="topic-chips">{item.topics.map(topic=><span key={topic}>{topic}</span>)}</div></div><div className="schedule-selfcheck"><BookOpen size={17} /><div><strong>{item.kind === "weekly" ? "先复盘，再决定如何验证" : "每日轻量自查"}</strong><p>{item.check}</p><small>手动自查，不自动阅卷或更新能力状态。</small></div></div><div className="schedule-output"><span className="micro-label">建议留下的学习成果</span><p>{item.output}</p></div>
      {item.kind === "weekly" && <div className="schedule-weekly-actions"><p>{unfinished > 0 ? `还有 ${unfinished} 项学习任务未完成，可先补学或改期；仍可打开现有考核体验。` : "学习任务已标记完成，可以通过考核检查理解，再针对薄弱点复测。"}</p><div><Button size="sm" onClick={onExam}>打开考核演示 <ArrowRight size={13} /></Button><Button size="sm" variant="outline" onClick={onRetest}>查看变式复测 <MoveRight size={13} /></Button></div><small>目前回放原专题的三道题；尚无独立生成的周综合试卷。</small></div>}
      <div className="schedule-note"><label htmlFor={`study-note-${selected}`}>学习笔记与自查记录 <span>{unsavedStorage?"尚未保存到浏览器":dirty?"有未保存内容":entry.note?"已保存在此浏览器":"尚无学习记录"}</span></label><Textarea id={`study-note-${selected}`} maxLength={1000} value={note} onChange={event=>setDraftNotes(previous=>({...previous,[selected]:event.target.value}))} placeholder="记下自己的解释、遇到的困难，或下次要补学的内容……" /><div><span>{note.length} / 1000</span><Button variant="outline" size="sm" disabled={!dirty&&!unsavedStorage} onClick={()=>{update(saveStudyNote(schedule,selected,note),"学习记录已保存");setDraftNotes(previous=>({...previous,[selected]:note}))}}>{unsavedStorage?"重试保存记录":!dirty&&entry.note?"已保存":"保存学习记录"}</Button></div></div><div className="schedule-source"><ShieldCheck size={13} /><span>所有安排关联原专题任务 #{item.sourceTaskId}</span><button onClick={onSource}>查看专题与来源 <ArrowRight size={12} /></button></div></Card>}
    </div>
    <Card className="schedule-week-summary"><Flag size={19} /><div><strong>每天检查理解，每周检查关联，薄弱点再复测。</strong><p>学习进度由你手动管理；考核证据保持独立。周末遇到时间冲突，也可以把检查日改期。</p></div><Button variant="outline" size="sm" onClick={()=>{setFilter("all");setSelected("weekly-check");focusRef.current?.scrollIntoView({behavior:"instant",block:"start"})}}>查看本周检查 <ArrowRight size={13} /></Button></Card>
    <details className="schedule-history"><summary><History size={15} /> 最近的进度与改期记录 <span>{schedule.history.length} 条</span></summary>{schedule.history.length ? <ol>{schedule.history.slice(-6).reverse().map((event,index)=><li key={`${event.at}-${index}`}><strong>{SCHEDULE_ITEMS.find(record=>record.id === event.entryId)?.title}</strong><p>{event.label}</p><small>{event.reason} · {new Date(event.at).toLocaleString("zh-CN",{hour12:false})}</small></li>)}</ol> : <p>尚未调整。你的状态更新与改期原因会记录在这里。</p>}</details>
    <Dialog open={adjusting} onOpenChange={setAdjusting}><DialogContent className="schedule-dialog"><DialogHeader><DialogTitle>让安排，适应你的节奏。</DialogTitle><DialogDescription>调整“{item.title}”的日期和预计投入。保留原学习目标与证据关联。</DialogDescription></DialogHeader><div className="schedule-edit-dates"><label>开始日期<input type="date" min="2000-01-01" max="2100-12-31" value={edit.start} onInput={event=>{const value=event.currentTarget.value;setEdit(previous=>({...previous,start:value}))}} onChange={event=>setEdit(previous=>({...previous,start:event.target.value}))} /></label><label>结束日期<input type="date" min="2000-01-01" max="2100-12-31" value={edit.end} onInput={event=>{const value=event.currentTarget.value;setEdit(previous=>({...previous,end:value}))}} onChange={event=>setEdit(previous=>({...previous,end:event.target.value}))} /></label></div><div className="schedule-extend"><span>内容较难？多留一点时间。</span><Button variant="outline" size="sm" onClick={()=>{try{setEdit(previous=>({...previous,end:addDays(previous.end,1),reason:"内容较难"}));setEditError("")}catch{setEditError("请先选择有效日期")}}}>延长一天</Button></div><label>预计总投入（分钟）<input type="number" min={5} max={480} step={5} value={Number.isFinite(edit.minutes) ? edit.minutes : ""} onChange={event=>setEdit(previous=>({...previous,minutes:event.target.valueAsNumber}))} /></label><label>调整原因<select value={edit.reason} onChange={event=>setEdit(previous=>({...previous,reason:event.target.value}))}><option>时间冲突</option><option>内容较难</option><option>其他安排</option></select></label><label>补充说明（选填）<Textarea maxLength={500} value={edit.extra} onChange={event=>setEdit(previous=>({...previous,extra:event.target.value}))} placeholder="例如：本周有考试，或还需要多做一次实验。" /></label><label className="schedule-shift-option"><input type="checkbox" checked={edit.shiftFollowing} onChange={event=>setEdit(previous=>({...previous,shiftFollowing:event.target.checked}))} /><span>将后续未完成安排一起移动<small>按本任务结束日的变化天数移动，含本周检查；已完成任务保持原日期。取消勾选则仅调整当前任务。</small></span></label>{editError && <p className="schedule-edit-error" role="alert">{editError}</p>}<div className="schedule-dialog-actions"><Button variant="ghost" onClick={()=>setAdjusting(false)}>取消</Button><Button onClick={applyAdjustment}>保存安排 <Check size={14} /></Button></div></DialogContent></Dialog>
    <Dialog open={startDialog} onOpenChange={setStartDialog}><DialogContent className="schedule-dialog"><DialogHeader><DialogTitle>从合适的一天开始。</DialogTitle><DialogDescription>按照新起点平移尚未完成的安排，已完成任务的日期和记录保留。改期后可以跨自然周。</DialogDescription></DialogHeader><label>计划开始日期<input type="date" min="2000-01-01" max="2100-12-31" value={newAnchor} onInput={event=>setNewAnchor(event.currentTarget.value)} onChange={event=>setNewAnchor(event.target.value)} /></label>{editError && <p role="alert" className="schedule-edit-error">{editError}</p>}<div className="schedule-dialog-actions"><Button variant="ghost" onClick={()=>setStartDialog(false)}>取消</Button><Button onClick={()=>{try{update(moveScheduleStart(schedule,newAnchor),"计划起点已调整");setStartDialog(false)}catch(error){setEditError(error instanceof Error ? error.message : "请检查日期")}}}>保存新起点 <Check size={14} /></Button></div></DialogContent></Dialog>
  </div>
}
