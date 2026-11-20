import SimplePersonalWorkspace from './SimplePersonalWorkspace'
import CompleteCaseReview from './CompleteCaseReview'
import {useEffect,useRef,useState} from 'react'
import {ArrowRight,Check,History,RefreshCw,ShieldCheck,Sparkles} from 'lucide-react'
import {Card} from './ui/card'
import {Button} from './ui/button'
import {Textarea} from './ui/textarea'
import WorkbenchCallPreparation,{type CedTarget} from './WorkbenchCallPreparation'
import WorkbenchABFPreparation,{type ABFTarget} from './WorkbenchABFPreparation'
import WorkbenchSavedBRecovery from './WorkbenchSavedBRecovery'
import WorkbenchPlanConfirmation from './WorkbenchPlanConfirmation'
import WorkbenchSessionOperations from './WorkbenchSessionOperations'
import ModelResultSource from './ModelResultSource'
import SessionRuntimePanel from './SessionRuntimePanel'
import {modeForSession,type ExperienceMode} from './ExperienceMode'
import PersonalInputCard,{type PersonalDraft} from './PersonalInputCard'
import WorkbenchOverview from './WorkbenchOverview'
import WorkbenchGrowth,{type GrowthTopic} from './WorkbenchGrowth'
import WorkbenchDiagnosis,{type DiagnosisAudit} from './WorkbenchDiagnosis'
import WorkbenchResume,{WorkbenchResumeReport,WorkbenchResumeCheck} from './WorkbenchResume'
import WorkbenchInterview from './WorkbenchInterview'
import {InterviewQuestionBasis, WorkbenchInterviewReport, type InterviewJD, type InterviewTurn} from './WorkbenchInterviewEvidence'
import WorkbenchAssessments,{WorkbenchAttemptReport} from './WorkbenchAssessments'
import {LearningArtifactView} from './WorkbenchLearningEvidence'
import BeginnerLearningCard,{type LearningCardPreview} from './BeginnerLearningCard'
import {usePendingEdits} from './WorkspaceQuality'
import {workbenchRequest} from '@/lib/workbench-api.mjs'
import {readWorkbenchRegistry,importWorkbenchReplay,addWorkbenchSession,addPersonalWorkbenchSession,selectWorkbenchSession,patchWorkbenchSession,withWorkbenchLock,readEntryRegistry,entryRegistry,rememberPersonalSelection} from '@/lib/workbench-sessions.mjs'
import {matchesRecord,recordKinds} from '@/lib/workbench-history.mjs'
import type {View} from '@/lib/routes.mjs'
import './competition-workbench.css'

type Scope={case_id:string;session_id:string;trace_id:string;plan_id:string}
type Budget={learning_minutes:number;core_minutes:number;review_minutes:number;optional_minutes:number;assessment_minutes:number;ending_policy:string}
type Task={task_id:string;task_template_id:string;day:number;title:string;topic_keys:string[];topic_ids:string[];source_gap_ids:string[];expected_outcome:string;preparation:string;gap_interpretation:string;resource_goals:string[];budget:Budget;guide_kind:string}
type Plan={plan_id:string;report_id:string;input_digest:string;overall_goal:string;tasks:Task[];daily_minutes:number;available_days:number;fixture_notice:string;deferred_gaps:{gap_id:string;skill:string;reason:string;revisit_when:string}[]}
type SavedPlan={version:number;plan_digest:string;parent_version:number|null;record_id:string;plan:Plan}
type Issue={issue_id:string;task_id:string;title:string;target:string;evidence_ref:string;suggestion:string;patch:{budget?:Budget;preparation?:string;gap_interpretation?:string}}
type Review={review_id:string;plan_version:number;plan_digest:string;verdict:string;summary:string;notice:string;issues:Issue[];checks:string[]}
type Progress={task_id:string;status:string;note:string;reason:string;start_date:string;end_date:string;revision:number}
type ProgressForm=Omit<Progress,'task_id'|'revision'>
type State={saved_b_recovery?:{authorization_id:string}|null;session_runtime?:any;runtime_capabilities?:any;personal_input?:any;abf?:any;ce_budget?:any;publication_status?:{status:string;resume_id?:string;notice?:string};read_only_demo?:boolean;capabilities?:GrowthTopic[];scope:Scope;revision:number;start_date:string;case_title:string;candidate:{display_name:string;resume_text:string};position:{title:string;jd_text:string};input_digest:string;active_version:number|null;published_version:number|null;diagnosis_status:string;recovery_available:boolean;diagnosis:{audit:DiagnosisAudit}|null;bindings:{topics:{topic_id:string;topic_key:string;title:string;primary_gap_id:string;source_gap_ids:string[]}[]}|null;plan:SavedPlan|null;review:Review|null;plan_versions:{version:number;plan_digest:string;parent_version:number|null}[];progress:Progress[];record_count:number;deferred_scope:{title:string;reason:string;revisit_when:string}}
type Lesson={artifact_template?:any;artifacts?:{record_id:string;artifact:any}[];scope:Scope;revision:number;plan_version:number;task:Task;progress:Progress;resources:{state:string;fallback:string;primary:Resource|null;backup:Resource|null};learning_card:LearningCardPreview|null;guide_notice:string}
type Resource={title:string;url:string;section:string;read_scope:string;learning_goal:string;language:string;verification:{checked_on:string}}
type RecordRow={record_id:string;kind:string;title:string;seq:number;created_at:string;envelope:{source_kind:string;evidence_use:string};payload:unknown;parent_ids:string[]}
type Pending={operation:string;body:Record<string,any>;startedAt:string}
type Entry={token:string;label:string;saved:boolean;start_date:string;pending:Pending|null}
type Registry={version:number;active:string|null;entries:Entry[]}
type Template={replay_entry?:{case_id:string;token:string;label:string;start_date:string;createdAt:string}|null;title:string;candidate:{display_name:string;resume_text:string};position:{title:string;jd_text:string};resource_count:number;topic_titles:string[]}
const statusLabels:Record<string,string>={not_started:'未开始',in_progress:'学习中',completed:'已完成',deferred:'暂缓学习'}
const operationLabels:Record<string,string>={plan_prepare:'准备固定演示学习草案',plan_confirm_publish:'程序校验后确认发布计划',saved_b_apply:'审计采用保存的B内容与程序时间',session_runtime_open:'保存会话模式与累计额度',create_personal:'保存个人原始资料',abf_apply:'核对采用模型正式结果',ce_budget_open:'保存累计模拟预算',candidate_apply:'核对采用并保存正式结果',learning_artifact:'保存课程练习成果',resume_generate:'生成有来源简历建议',resume_check:'保存表述核对结果',create:'创建会话',diagnosis:'示例诊断',plan:'生成草案',review:'F审查',adopt:'采纳建议',publish:'确认学习计划',progress:'保存学习进度',recover:'恢复中断步骤',assessment_start:'开始日周考核',retest_start:'开始专题复测',answer:'提交本题答卷',assessment_next:'准备下一题',assessment_end:'结束本次练习',interview_start:'开始岗位面试',interview_answer:'发送面试回答',interview_end:'结束面试并生成复盘'}
const headings:Partial<Record<View,[string,string]>>={resume:['D · WORDS WITH SOURCES','让每一句经历，都有来处。'],scenario:['JOB INTERVIEW · ONE CONVERSATION','围绕整个岗位，展开一段对话。'],exam:['DAY / WEEK · FROZEN SCOPE','学过的任务，用独立作答核对。'],retest:['TOPIC · ONE QUESTION AT A TIME','换一个情境，再验证一次。'],overview:['YOUR CAREER JOURNEY','下一步，从这里出发。'],new:['BEGIN WITH A CLEAR CONTEXT','从同一份资料，开始这段旅程。'],diagnosis:['A · EVIDENCE BEFORE JUDGMENT','先看证据，再决定补什么。'],plan:['B · A PLAN YOU CAN FOLLOW','核对安排，确认后开始行动。'],records:['YOUR JOURNEY, IN ONE PLACE','每次判断与调整，都有来处。'],growth:['GROWTH NEEDS EVIDENCE','学习进度与能力证据，分开看。']}
const total=(b:Budget)=>b.learning_minutes+b.core_minutes+b.review_minutes+(b.ending_policy==='choose_one'?Math.max(b.optional_minutes,b.assessment_minutes):b.optional_minutes+b.assessment_minutes)
const taskWeek=(task:Task)=>task.day<=7?1:2
const formatDates=(p:Progress)=>p.start_date===p.end_date?p.start_date:p.start_date+' 至 '+p.end_date
const fromProgress=(p:Progress):ProgressForm=>({status:p.status,note:p.note,reason:p.reason,start_date:p.start_date,end_date:p.end_date})
const today=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())
function initial(mode:'demo'|'personal'){try{return {registry:readEntryRegistry(localStorage,mode) as Registry,error:''}}catch(e){return {registry:{version:1,active:null,entries:[]} as Registry,error:e instanceof Error?e.message:'无法读取会话列表。'}}}
function time(value:string){try{return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short'}).format(new Date(value))+' 北京时间'}catch{return value}}

export function WorkbenchSavedRecord({record,onPlan=()=>{},onRemediate,jd=[],interviewTurns=[],onSource}:{
 record:RecordRow;onPlan?:()=>void;onRemediate?:(taskId:string,topicKey:string)=>void
 jd?:InterviewJD;interviewTurns?:InterviewTurn[];onSource?:(id:string)=>void
}){
 const p=record.payload as Record<string,any>
 if(p.event==='abf_candidate_adopted')return <section><h3>核对采用 · {p.stage}</h3><p>{p.notice}</p><p>修订 {p.revision} · 本会话来源和原候选保留。</p></section>
 if(p.event==='candidate_adopted')return <section><h3>已核对采用 · {p.stage}</h3><p>{p.notice}</p><p>{p.candidate_simulated?'本地替身候选 · 不代表真实模型评价':'模型候选已人工核对 · 仍需核实事实'}</p><p>采用版本 {p.revision} · 原始调用回执与原记录继续保留。</p>{p.formal_resume_id&&<p>已另存为新的简历版本，可从简历修改页查看。</p>}<details><summary>查看采用内容</summary><pre>{JSON.stringify(p.candidate,null,2)}</pre></details></section>
 if(record.kind==='resume')return p.event==='resume_report'?<WorkbenchResumeReport report={p.report} onSource={onSource}/>:<WorkbenchResumeCheck check={p}/>
 if(record.kind==='interview')return p.event==='interview_report'?<WorkbenchInterviewReport report={p.report} jd={jd} turns={interviewTurns} onPlan={onPlan}/>:p.event==='interview_turn'?<section><h3>{p.turn.role==='assistant'?'面试官提问':'我的面试回答'}</h3><p className="wbi-preserve">{p.turn.text}</p><p className="wb-muted">原始对话，未作评分或能力更新。复盘保存在同一面试的结束记录中。</p>{p.turn.role==='assistant'&&<InterviewQuestionBasis question={p.turn} jd={jd} turns={interviewTurns}/>}<code className="wb-id-line">{p.turn.turn_id}</code></section>:<section><h3>岗位面试范围已确认</h3><p>{p.position_title} · {p.planned_main}个主问题，最多{p.max_followups}次追问。逐轮对话与结束复盘都属于本会话。</p><p>学习摘要：{p.context_selection?.include_learning_evidence?'已选择加入，不含笔记/答卷正文':'未加入'}。</p></section>

 if(['assessment','retest'].includes(record.kind))return p.event==='answer_submitted'?<WorkbenchAttemptReport attempt={{...p,commit_seq:record.seq}} onRemediate={onRemediate}/>:<section><h3>{p.event==='ended'?'本次练习提前结束':'确认范围并准备题目'}</h3><p>{p.reason??p.basis??'已按本会话保存范围准备题目，不提前展示参考答案。'}</p><p>已提交答卷保留，未答题不计0分。题目与报告可在对应日周考核/专题复测入口恢复。</p></section>
 if(record.kind==='mastery')return <section><h3>答卷驱动的演示状态变化</h3><p>{p.notice}</p><p>规则：{p.rule_version}；本次触发答卷：{p.trigger_attempt_id}</p>{p.after?.map((a:any)=><p key={a.topic_id}>{a.title}：{p.before?.find((b:any)=>b.topic_id===a.topic_id)?.label??'尚未考核'} → {a.label}。{a.explanation}</p>)}<p>具体依据答卷ID见下方同会话引用；真实掌握状态未更新。</p></section>

 if(record.kind==='learning_artifact')return <LearningArtifactView artifact={p.artifact}/>
 if(record.kind==='learning_progress')return <section><h3>学习记录</h3><p>状态：{statusLabels[p.progress?.status]??'暂无'} · {p.progress?.start_date} 至 {p.progress?.end_date}</p><p>笔记：{p.progress?.note||'暂无'}</p>{p.progress?.reason&&<p>暂缓原因：{p.progress.reason}</p>}<p className="wb-muted">计划v{p.plan_version}。本次只更新学习进度，没有答卷评分或能力变化。</p></section>
 if(p.event==='ce_budget_open')return <section><h3>C/E同会话模拟预算</h3><p>本地演练上限：{p.policy.simulation_limit_micro_cny/1000000} 元模拟额度。真实模型费用为0，原授权与用量不会因换题、重开面试或重启而清零。</p><p>{p.policy.pricing_notice}</p></section>
 if(record.kind==='plan_review')return <section><h3>历史 F 实验审查 · 计划v{p.plan_version}</h3><p>{p.summary}</p>{p.issues?.map((i:Issue)=><div className="wb-review-issue" key={i.issue_id}><h4>{i.title}</h4><p>依据：{i.evidence_ref}</p><p>建议：{i.suggestion}</p></div>)}<p className="wb-muted">审查对应保存时的计划版本；不是对你个人能力的评分。</p></section>
 if(record.kind==='plan'&&p.event==='published')return <section><h3>已确认采用计划v{p.version}</h3><p>{p.publication_policy==='program-confirm-v1'?'程序校验通过，并由用户确认发布；不是F审查，也不是能力认证。':'历史计划发布记录，原审查及来源保留；不代表当前比赛流程。'}</p></section>
 if(record.kind==='diagnosis'&&p.action==='mark_failed_only')return <section><h3>已恢复中断步骤的状态</h3><p>本次只将中断步骤标为可重新执行，没有重发诊断，也没有生成能力结论。</p></section>
 if(record.kind==='plan')return <section><h3>{p.source_version?`从v${p.source_version}修订到v${p.version}`:`计划v${p.version??'—'}`}</h3><p>{p.source_version?'采纳F建议后另存了新版本，原始草案仍然保留。':p.version?'保存了本版学习任务，待程序校验与用户确认发布。':'确认了通过复核的计划，开放学习入口。'}</p><Button variant="outline" onClick={onPlan}>前往计划页比较版本<ArrowRight size={15}/></Button></section>
 if(record.kind==='diagnosis')return <section><h3>岗位证据已保存</h3><p>{p.diagnosis?.audit?.score_reason??'后续任务指回本次诊断；材料不足保留待核对，不认定不会。'}</p><p className="wb-muted">固定替身结果，不是实测个人能力或成长成绩。</p></section>
 return <section><h3>首次输入已保存</h3><p>{record.envelope?.source_kind==='user_input'?'本会话使用用户提供的简历和JD原文，后续诊断、计划与建议沿用这份独立资料；自述未经独立核验。':'本会话使用新版完整结构化虚构简历和标准数据开发JD，后续诊断、计划和审查沿用同一份资料。'}</p></section>
}

export function WorkbenchReview({review,version,busy,onReview,onAdopt,onPublish,published=false,historical=false}:{review:Review|null;version:number;busy:boolean;onReview:()=>void;onAdopt:()=>void;onPublish:()=>void;published?:boolean;historical?:boolean}){
 return <Card className="multi-card wb-review" aria-label="F计划审查"><div className="wb-section-heading"><div><span className="micro-label">F · PLAN REVIEW</span><h2>{review?(review.verdict==='pass'?'固定复核通过。':'先修好这三个交付问题。'):'让F先看一遍这份草案。'}</h2></div><span className={'wb-chip '+(review?.verdict==='pass'?'is-good':'')}>v{version} · {historical?'历史只读':published?'已用于学习':review?.verdict==='pass'?'待确认学习':review?'需修订':'待审查'}</span></div>
 <p>检查时间负荷、起步门槛、资料与交付，也检查计划有没有把“证据不足”误写成“不会”。全部采用固定替身，无模型调用。</p>
 {review?<><p><strong>{review.summary}</strong></p>{review.issues.map(i=><section className="wb-review-issue" key={i.issue_id}><h3>{i.title}</h3><p><strong>当前计划：</strong>{i.target}</p><p><strong>核对依据：</strong>{i.evidence_ref}</p><p><strong>建议：</strong>{i.suggestion}</p>{i.patch.budget&&<div className="wb-budget-after"><span>建议调整后</span><strong>{total(i.patch.budget)} 分钟</strong><small>阅读与讲解30 · 必做15 · 复盘5 · 最后10分钟选做/日考核二选一</small></div>}</section>)}<details><summary>查看本次检查范围与边界</summary><ul>{review.checks.map(c=><li key={c}>{c}</li>)}</ul><p>{review.notice}</p></details></>:<p className="wb-muted">B的固定v1草案刻意保留3项问题，用来体验F审查和修订；这不是对真实模型计划质量的评价。</p>}
 {!historical&&!published&&<div className="multi-actions">{!review&&<Button disabled={busy} onClick={onReview}>审查当前 v{version}<ShieldCheck size={16}/></Button>}{review?.verdict==='needs_revision'&&<Button disabled={busy} onClick={onAdopt}>采纳{review.issues.length}项建议，另存 v{version+1}<ArrowRight size={16}/></Button>}{review?.verdict==='pass'&&<Button disabled={busy} onClick={onPublish}>确认采用 v{version}，开始学习<ArrowRight size={16}/></Button>}</div>}
 {historical?<p className="wb-muted">历史版本仅供核对，不覆盖当前计划，也不能采纳旧建议。</p>:published?<p className="wb-success"><Check size={16}/>此版本已确认学习；原草案、审查和采纳记录都已保留。</p>:<p className="wb-muted">审查不会自动改计划。采纳会另存新版本，复核通过后才可确认学习。</p>}
 </Card>
}

export default function CompetitionWorkspace({view,routeHash,onNavigate,entryMode='demo',onModeChange}:{onModeChange?:(mode:ExperienceMode)=>void;entryMode?:'demo'|'personal';view:View;routeHash:string;onNavigate:(view:View,params?:Record<string,string>)=>void}){
 const [first]=useState(()=>initial(entryMode)),[registry,setRegistry]=useState<Registry>(first.registry),[token,setToken]=useState<string|null>(first.registry.active)
 const [data,setData]=useState<State|null>(null),[template,setTemplate]=useState<Template|null>(null),[error,setError]=useState(first.error),[info,setInfo]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(Boolean(first.registry.active))
 const [startDate,setStartDate]=useState(today),[selectedVersion,setSelectedVersion]=useState<number|null>(null),[historical,setHistorical]=useState<(SavedPlan&{review:Review|null})|null>(null)
 const query=new URLSearchParams(routeHash.split('?')[1]??'')
 const routeTask=view==='plan'?query.get('task'):null,focus=query.get('focus')??''
 const activeTask=data?.plan?.plan.tasks.find(t=>t.task_id===routeTask)
 const taskId=activeTask?.task_id??''
 const [lesson,setLesson]=useState<Lesson|null>(null),[form,setForm]=useState<ProgressForm|null>(null),[draft,setDraft]=useState(''),[records,setRecords]=useState<RecordRow[]>([]),[recordsReady,setRecordsReady]=useState(false)
 const [selectedRecord,setSelectedRecord]=useState(query.get('record')??'')
 const [filters,setFilters]=useState({kind:Object.hasOwn(recordKinds,query.get('kind')??'')?query.get('kind')!:'all',
  subject:query.get('subject')??'',date:query.get('date')??'',task:view==='records'?query.get('task')??'':''})
 const changeFilters=(patch:Partial<typeof filters>)=>{setFilters(prev=>({...prev,...patch}));setSelectedRecord('')}
 const alive=useRef(true),epoch=useRef(0),lessonEpoch=useRef(0),flight=useRef(false),tokenRef=useRef(token)
 const entry=registry.entries.find(e=>e.token===token),pending=entry?.pending??null
 const formDirty=Boolean(lesson&&form&&JSON.stringify(form)!==JSON.stringify(fromProgress(lesson.progress)))
 const [assessmentDirty,setAssessmentDirty]=useState(false)
 const [cedTarget,setCedTarget]=useState<CedTarget|null>(null)
 const [abfTarget,setAbfTarget]=useState<ABFTarget|null>(null)
 const [personalDirty,setPersonalDirty]=useState(false)
 const dirty=formDirty||Boolean(draft.trim())||assessmentDirty||personalDirty
 useEffect(()=>{onModeChange?.(modeForSession({entryMode,loading,failed:Boolean(error)&&!data,data:personalDirty&&view==='new'?null:data}))},[entryMode,loading,error,data,personalDirty,view,onModeChange])
 usePendingEdits('competition-workbench',dirty||busy)
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;epoch.current++;lessonEpoch.current++}},[])
 useEffect(()=>{let current=true;workbenchRequest('template').then(async(v:{template:Template})=>{
  if(!current)return;setTemplate(v.template)
  if(entryMode==='demo'&&v.template.replay_entry&&!first.error){const latest=entryRegistry(await withWorkbenchLock(()=>importWorkbenchReplay(localStorage,v.template.replay_entry,true)),'demo');if(current){setRegistry(latest);if(tokenRef.current!==latest.active){tokenRef.current=latest.active;setToken(latest.active)}}}
 }).catch((e:Error)=>{if(current)setError(e.message)});return()=>{current=false}},[])
 const openReplay=()=>{if(!busy&&!dirty)onNavigate('overview',{entry:'demo'})}
 const updateRegistry=(value:Registry)=>{if(alive.current)setRegistry(entryRegistry(value,entryMode,entryMode==='personal'?localStorage.getItem('career-pilot:personal-workbench:last:v1'):null))}
 const savePending=async(t:string,p:Pending)=>withWorkbenchLock(()=>{const latest=readWorkbenchRegistry(localStorage) as Registry;const old=latest.entries.find((e:Entry)=>e.token===t)?.pending;if(old&&old.body.request_id!==p.body.request_id)throw Error('另一页面有待确认操作，请先读取本次回执。');const value=patchWorkbenchSession(localStorage,t,{pending:p});updateRegistry(value);return value})
 const clearPending=async(t:string,rid:string,saved=false)=>withWorkbenchLock(()=>{const latest=readWorkbenchRegistry(localStorage) as Registry;const old=latest.entries.find((e:Entry)=>e.token===t);if(!old)throw Error('会话身份已变化，请保留当前数据。');const patch:Record<string,unknown>=saved?{saved:true}:{};if(old.pending?.body.request_id===rid)patch.pending=null;const value=patchWorkbenchSession(localStorage,t,patch);updateRegistry(value);return value})
 const readState=async(t:string)=>{const id=++epoch.current;const value=await workbenchRequest('state',t) as State;if(entryMode==='demo'&&!value.read_only_demo)throw Error('演示入口仅显示公开只读案例；请使用动手体验入口恢复自己的会话。');if(entryMode==='personal'&&(!value.personal_input||value.read_only_demo))throw Error('个人入口不能载入演示成绩，请新建自己的会话。');if(alive.current&&tokenRef.current===t&&id===epoch.current){setData(value);setLoading(false);setSelectedVersion(value.active_version);setHistorical(null)}return value}
 const readRecords=async(t:string)=>{const value=await workbenchRequest('records',t);if(alive.current&&tokenRef.current===t){setRecords(value.records);setRecordsReady(true)}}
 const readLesson=async(t:string,id:string,keepDraft=false)=>{const generation=++lessonEpoch.current;const value=await workbenchRequest('learning?task_id='+encodeURIComponent(id),t) as Lesson;if(alive.current&&tokenRef.current===t&&generation===lessonEpoch.current){setLesson(value);if(!keepDraft)setForm(fromProgress(value.progress))}return value}
 useEffect(()=>{tokenRef.current=token;epoch.current++;lessonEpoch.current++;setData(null);setLesson(null);setForm(null);setRecords([]);setRecordsReady(false);setDraft('');setHistorical(null);setError(first.error);setInfo('');setLoading(Boolean(token));if(!token){setLoading(false);return}const selected=registry.entries.find(e=>e.token===token);if(selected&&!selected.saved){setLoading(false);return}readState(token).catch((e:Error)=>{if(alive.current&&tokenRef.current===token){setLoading(false);setError(e.message)}})},[token])
 useEffect(()=>{if((view==='overview'||view==='records'||(view==='plan'&&data?.published_version))&&token&&data)readRecords(token).catch((e:Error)=>{if(alive.current)setError(e.message)})},[view,token,data?.revision])
 useEffect(()=>{if(view!=='plan'||!token||!taskId||!data?.published_version)return;setLesson(null);setForm(null);setDraft('');readLesson(token,taskId).catch((e:Error)=>{if(alive.current)setError(e.message)})},[view,token,taskId,data?.published_version])
 const run=async(operation:string,extra:Record<string,unknown>={},existing?:Pending,t=token)=>{
  if(!['create','create_personal'].includes(operation)&&data?.read_only_demo&&t===token){setError('演示为只读。请通过动手体验入口填写自己的资料并创建独立会话。');return}
  if(!t||flight.current)return;if(!existing&&pending){setError('还有一项操作待确认，请先查询回执。');return}
  flight.current=true;setBusy(true);setError('');setInfo('')
  const p=existing??{operation,body:{request_id:crypto.randomUUID(),...(['create','create_personal'].includes(operation)?extra:{expected_revision:data?.revision,...extra})},startedAt:new Date().toISOString()}
  try{
   await savePending(t,p)
   const receipt=await workbenchRequest(p.operation,t,p.body)
   const current=await readState(t)
   await clearPending(t,p.body.request_id,['create','create_personal'].includes(operation))
   if(alive.current&&tokenRef.current===t){if(['progress','learning_artifact'].includes(operation)&&taskId)await readLesson(t,taskId);if(view==='records')await readRecords(t);setInfo(`${operationLabels[operation]??'操作'}已保存；当前为${current.active_version?`计划v${current.active_version}`:'首次输入'}，没有模型调用。`)}
   return receipt
  }catch(e){
   const err=e as Error&{code?:string}
   if(['invalid','conflict','validation','not_found','busy'].includes(err.code??'')){
    try{await clearPending(t,p.body.request_id);await readState(t);if(['progress','learning_artifact'].includes(operation)&&taskId)await readLesson(t,taskId,true)}catch{}
   }
   if(alive.current&&tokenRef.current===t)setError((err.message||'操作未完成。')+(operation==='progress'?'你的学习草稿仍保留，请核对最新状态再保存。':''))
  }finally{flight.current=false;if(alive.current)setBusy(false)}
 }
 const create=async(sdk=false)=>{
  if(flight.current||dirty)return;setError('');setInfo('');setBusy(true)
  try{const next=await withWorkbenchLock(()=>addWorkbenchSession(localStorage,crypto,startDate)) as Registry;updateRegistry(next);const t=next.active!;tokenRef.current=t;setToken(t);setData(null);setLesson(null);setForm(null);setRecords([]);setBusy(false);const created=await run('create',{start_date:startDate},undefined,t);if(created&&sdk)setAbfTarget({stage:'a_diagnosis',version:0})}catch(e){setBusy(false);setError(e instanceof Error?e.message:'会话身份未保存，没有发送创建请求。')}
 }
 const createPersonal=async(fields:PersonalDraft)=>{
  if(flight.current||formDirty||Boolean(draft.trim())||assessmentDirty)return
  setError('');setInfo('');setBusy(true)
  try{
   const next=await withWorkbenchLock(()=>addPersonalWorkbenchSession(localStorage,crypto,startDate)) as Registry
   updateRegistry(next);const t=next.active!;rememberPersonalSelection(localStorage,t);tokenRef.current=t;setToken(t);setData(null);setLesson(null);setForm(null);setRecords([]);setBusy(false)
   const result=await run('create_personal',{start_date:startDate,...fields},undefined,t)
   if(result){setPersonalDirty(false);setAbfTarget(null)}
   return result
  }catch(e){setBusy(false);setError(e instanceof Error?e.message:'个人会话尚未创建，请保留草稿。')}
 }
 const select=async(t:string)=>{if(busy||dirty){setError('请先保存学习记录并清空练习草稿，再切换会话。');return}try{const next=await withWorkbenchLock(()=>{const selected=selectWorkbenchSession(localStorage,t);if(entryMode==='personal')rememberPersonalSelection(localStorage,t);return selected});updateRegistry(next);tokenRef.current=t;setToken(t)}catch(e){setError(e instanceof Error?e.message:'无法切换会话。')}}
 const reload=async()=>{if(!token||busy)return;setBusy(true);setError('');try{await readState(token);if(view==='records'||view==='overview')await readRecords(token);if(view==='plan'&&taskId&&data?.published_version)await readLesson(token,taskId,dirty);setInfo(dirty?'已读取最新状态，你的未保存草稿保持原样。':'会话已恢复为本机保存的状态。')}catch(e){setError(e instanceof Error?e.message:'读取未完成。')}finally{setBusy(false)}}
 const confirmPending=async()=>{if(!token||!pending||busy)return;setBusy(true);setError('');try{const result=await workbenchRequest('request?request_id='+pending.body.request_id,token);if(result.found){await clearPending(token,pending.body.request_id,['create','create_personal'].includes(pending.operation));await readState(token);setInfo('已查到保存回执，未重新执行任何步骤。')}else setInfo('服务尚未记录本请求的成功回执。可以重新读取会话，或由你选择按原请求重试。')}catch(e){setError(e instanceof Error?e.message:'暂未确认回执。')}finally{setBusy(false)}}
 const clearInterrupted=async()=>{if(!token||!pending||busy)return;try{const result=await workbenchRequest('request?request_id='+pending.body.request_id,token);if(result.found){setError('服务已有回执，请先查询并恢复结果。');return}await clearPending(token,pending.body.request_id);setInfo('只清除了本机待确认标记，没有重发步骤。中断诊断可显式恢复后再执行。')}catch(e){setError(e instanceof Error?e.message:'无法核对请求状态。')}}
 const chooseVersion=async(version:number)=>{if(dirty||busy){setError('请先保存学习记录并清空练习草稿，再查看其他版本。');return}setSelectedVersion(version);if(version===data?.active_version){setHistorical(null);return}if(!token)return;setBusy(true);try{const saved=await workbenchRequest('plan?version='+version,token);if(alive.current)setHistorical(saved)}catch(e){setSelectedVersion(data?.active_version??null);setHistorical(null);setError(e instanceof Error?e.message:'历史版本暂不可用。')}finally{setBusy(false)}}
 const chooseTask=(id:string)=>onNavigate('plan',{task:id})
 const remediate=(taskId:string,topicKey:string)=>{
  const target=data?.plan?.plan.tasks.find(t=>t.task_id===taskId&&t.topic_keys.includes(topicKey))
  const cap=data?.capabilities?.find(c=>c.topic_key===topicKey)
  if(!data?.published_version||!target||!cap){setError('这道题的学习来源暂不可用，请从本会话计划查看。');return}
  onNavigate('plan',{task:target.task_id,focus:cap.topic_id})
 }
 const saveProgress=()=>{if(!data||!form||!lesson)return;run('progress',{plan_version:data.published_version,task_id:lesson.task.task_id,...form})}
 const prepareAbf=(target:ABFTarget)=>{if(data?.personal_input&&!data.session_runtime&&!data.abf){setError('请先确认本会话的运行模式和会话累计额度，再预览A请求。');document.getElementById('session-runtime-panel')?.scrollIntoView({behavior:'smooth'});return}setAbfTarget(target)}
 const currentPlan=historical??data?.plan??null,currentReview=historical?historical.review:data?.review??null
 const isHistorical=Boolean(currentPlan&&currentPlan.version!==data?.active_version)
 const heading=(routeTask?['DAILY LEARNING','每日学习详情']:headings[view])??['ONE SESSION · CLEAR SOURCES','让所有记录，都指回同一段旅程。']
 const tasks=data?.plan?.plan.tasks??[]
 const progressByTask=new Map(data?.progress.map(p=>[p.task_id,p]))
 const date=today()
 const scheduledToday=tasks.filter(t=>{const p=progressByTask.get(t.task_id);return p&&p.start_date<=date&&p.end_date>=date})
 const todayTask=scheduledToday.find(t=>['in_progress','not_started'].includes(progressByTask.get(t.task_id)?.status??''))
 const completed=data?.progress.filter(p=>p.status==='completed').length??0
 const openWeek=query.has('week')?(query.get('week')==='2'?2:1):scheduledToday[0]?taskWeek(scheduledToday[0]):1
 const remediation=data?.capabilities?.find(c=>c.topic_id===focus&&activeTask?.topic_keys.includes(c.topic_key))

 const visibleRecords=records.filter(r=>matchesRecord(r,filters,tasks,data?.capabilities??[]))
 const detail=visibleRecords.find(r=>r.record_id===selectedRecord)
 const openSource=(record:string)=>onNavigate('records',{record})
 const recordTitle=(r:RecordRow)=>{
  const p=r.payload as {progress?:{task_id:string};scope_snapshot?:{period_start?:string;period_end?:string}}
  const task=tasks.find(t=>t.task_id===p.progress?.task_id)
  const scope=p.scope_snapshot
  if(task)return task.title+' · 学习记录'
  if(scope?.period_start&&scope.period_end&&scope.period_start!==scope.period_end)return r.title+' · '+scope.period_start+' 至 '+scope.period_end
  return r.title
 }
 const recordPayload=detail?.payload as {run_id?:string;interview_id?:string;resume_id?:string;artifact?:{task_id:string};progress?:{task_id:string}}|undefined
 const recordDestination: {view:View;params:Record<string,string>;label:string}|null=
  detail?.kind==='assessment'&&recordPayload?.run_id?{view:'exam',params:{run:recordPayload.run_id},label:'打开完整考核'}:
  detail?.kind==='retest'&&recordPayload?.run_id?{view:'retest',params:{run:recordPayload.run_id},label:'打开完整专题复测'}:
  detail?.kind==='interview'&&recordPayload?.interview_id?{view:'scenario',params:{interview:recordPayload.interview_id},label:'打开原面试'}:
  detail?.kind==='resume'&&recordPayload?.resume_id?{view:'resume',params:{resume:recordPayload.resume_id},label:'打开原简历建议'}:
  detail?.kind==='learning_artifact'&&recordPayload?.artifact?.task_id?{view:'plan',params:{task:recordPayload.artifact.task_id},label:'打开成果对应学习任务'}:
  detail?.kind==='learning_progress'&&recordPayload?.progress?.task_id?{view:'plan',params:{task:recordPayload.progress.task_id},label:'打开对应学习任务'}:null
 const learningHistory=records.filter(r=>r.kind==='learning_progress'&&(!taskId||
  (r.payload as {progress?:{task_id:string}}).progress?.task_id===taskId)).slice(0,3)
 useEffect(()=>{
  if(view==='records'&&detail&&query.get('record')===detail.record_id){
   const element=document.getElementById('wb-selected-record')
   element?.focus({preventScroll:true})
   element?.scrollIntoView({block:'start'})
  }
 },[view,detail?.record_id])
 const interviewId=detail?.kind==='interview'?(detail.payload as {interview_id?:string})?.interview_id:undefined
 const interviewTurns=interviewId?records.flatMap(record=>{
  const payload=record.payload as {event?:string;turn?:InterviewTurn}
  return record.kind==='interview'&&payload?.event==='interview_turn'&&payload.turn?.interview_id===interviewId?[payload.turn]:[]
 }):[]
 if(entryMode==='personal')return <SimplePersonalWorkspace view={view} data={data} token={token} registry={registry} onCreate={createPersonal} onNavigate={onNavigate} onSelect={select} onReload={reload} startDate={startDate} onDate={setStartDate} onDirty={setPersonalDirty} error={error} pending={pending} onConfirmPending={confirmPending} initialResume={query.get('resume')??''} initialInterview={query.get('interview')??''} initialRecord={query.get('record')??''}/>
 if(data?.read_only_demo&&['exam','retest','scenario','resume'].includes(view))return <div className="page-enter career-page"><section className="page-intro"><div><div className="eyebrow">COMPLETE CASE</div><h1>{headings[view]?.[1]}</h1><p>固定案例 · 不调用模型</p></div></section><CompleteCaseReview view={view} data={data} token={token} onNavigate={onNavigate} summary={(template?.replay_entry as any)?.complete_summary} initialRun={query.get('run')??''} initialResume={query.get('resume')??''} initialInterview={query.get('interview')??''} focusTopic={focus}/></div>
 return <div className={"page-enter career-page wb-page"+(view==='overview'?' wb-home-page':'')}><section className="page-intro"><div><div className="eyebrow"><span/>{heading[0]}</div><h1>{heading[1]}</h1><p>{view==='overview'?'从岗位差距到简历提升，每一步都知道往哪里走。':data?.personal_input?`${data.position.title} · 当前个人会话`:false?'保存自己的资料，开启独立的求职会话。':'统一比赛案例 · 初级数据开发 · 同一候选人、同一会话'}</p></div></section>
 {view==='overview'&&template?.replay_entry&&token!==template.replay_entry.token&&<div className="wb-current-session"><span>想先了解完整效果？查看同一案例的只读回放。</span><Button variant="outline" disabled={busy||dirty} onClick={openReplay}>查看完整演示</Button></div>}
 {data?.read_only_demo&&view==='overview'&&<div className="wb-current-session wb-replay-notice"><span>完整案例只读回放；动手体验使用独立会话。</span><Button variant="outline" disabled={busy} onClick={()=>onNavigate('new',{entry:'personal'})}>开始动手体验<ArrowRight size={15}/></Button></div>}
 {data?.publication_status?.status==='unavailable'&&<p role="alert" className="multi-error wb-feedback">{data.publication_status.notice}</p>}
 {error&&<p role="alert" className="multi-error wb-feedback">{error}</p>}{info&&<p role="status" className="sequential-info wb-feedback">{info}</p>}
 {pending&&<Card className="multi-card wb-pending"><h3>{operationLabels[pending.operation]} · 待确认</h3><p>已保留同一请求身份，不会自动重发。先查保存回执；没有回执时，你可以选择按原请求重试。</p><div className="multi-actions"><Button disabled={busy} onClick={confirmPending}>查询本次回执</Button><Button variant="outline" disabled={busy} onClick={()=>run(pending.operation,{},pending)}>按原请求重试</Button><Button variant="ghost" disabled={busy} onClick={clearInterrupted}>核对后清除本机标记</Button></div></Card>}
 {busy&&<p className="quality-loading" role="status">正在保存本机会话结果，请稍候…</p>}
 {view==='new'&&<PersonalInputCard busy={busy||Boolean(pending)||Boolean(first.error)} startDate={startDate} onDate={setStartDate} onCreate={createPersonal} onDirty={setPersonalDirty}/>}
 {!token&&!loading&&view!=='new'&&view!=='overview'&&<Card className="multi-card"><h2>从一个成长会话开始</h2><p>创建后，诊断、学习、考核和答卷都保存在同一会话中。</p><Button disabled={busy} onClick={()=>onNavigate('new')}>填写我的简历和JD<ArrowRight size={16}/></Button></Card>}
 {view==='overview'&&!token&&!loading&&<WorkbenchOverview data={null} records={[]} recordsReady={false} date={date} blocked={busy||Boolean(pending)||Boolean(first.error)} onNavigate={onNavigate}/>}
 {loading&&<p role="status" className="quality-loading">正在恢复同一会话的数据…</p>}
 {token&&!data&&!loading&&view!=='new'&&<Card className="multi-card"><h2>先恢复或确认这份会话。</h2><p>原列表和本机记录没有清除。请重新读取；若创建请求待确认，可查询上方回执。</p><Button variant="outline" disabled={busy} onClick={reload}>重新读取会话</Button></Card>}
 {data&&<>
 {view==='overview'&&<WorkbenchOverview data={data} label={entry?.label} records={records} recordsReady={recordsReady} date={date} blocked={busy||loading||Boolean(pending)} onNavigate={onNavigate}/>}
 {data.personal_input&&!data.session_runtime&&data.abf&&<p className="wb-muted">这是历史本地会话。新模式请新建会话，原记录保留。</p>}
 {data.personal_input&&['new','overview','diagnosis'].includes(view)&&<SessionRuntimePanel data={data} disabled={busy||dirty||Boolean(pending)} onOpen={(mode,limit)=>run('session_runtime_open',{execution_mode:mode,budget_micro_cny:limit})} onPrepare={()=>prepareAbf({stage:'a_diagnosis',version:0})}/>}
 {view==='diagnosis'&&<ModelResultSource provenance={(data.diagnosis as any)?.model_provenance}/>}
 {view==='plan'&&<><ModelResultSource provenance={(data.plan?.plan as any)?.model_provenance}/></>}
 {data.abf&&['overview','diagnosis','plan','exam','retest','scenario'].includes(view)&&<WorkbenchSessionOperations data={data} disabled={busy||dirty||Boolean(pending)||Boolean(data.read_only_demo)} onPrepare={prepareAbf} onOpenBudget={limit=>run('ce_budget_open',{simulation_limit_micro_cny:limit})}/>}
 {token&&view==='plan'&&data.saved_b_recovery&&<WorkbenchSavedBRecovery token={token} authorizationId={data.saved_b_recovery.authorization_id} onApply={extra=>{if(dirty||pending)throw Error('请先处理当前草稿或待确认操作。');return run('saved_b_apply',extra)}}/>}
 {token&&<WorkbenchABFPreparation key={token+':abf'} token={token} revision={data.revision} target={abfTarget} budget={data.session_runtime} onUpdated={()=>readState(token)} onClose={()=>{setAbfTarget(null);void reload()}} onApply={extra=>{if(dirty||pending)throw Error('请先处理当前草稿或待确认操作。');return run('abf_apply',extra)}}/>}
 {view==='diagnosis'&&<WorkbenchDiagnosis
  candidate={data.candidate} position={data.position} audit={data.diagnosis?.audit}
  recover={data.recovery_available} busy={busy||Boolean(pending)} hasPlan={Boolean(data.plan)}
  onRun={()=>data.abf||data.personal_input?prepareAbf({stage:'a_diagnosis',version:0}):run('diagnosis')} onRecover={()=>run('recover')} onPlan={()=>onNavigate('plan')}/>}
 {view==='plan'&&<>{!data.diagnosis?<Card className="multi-card"><h2>计划要先有本会话的诊断来源。</h2><p>不会按相同的专题名称借用其他会话的差距。</p><Button onClick={()=>onNavigate('diagnosis')}>先完成岗位诊断<ArrowRight size={16}/></Button></Card>:(data.personal_input?.curriculum_available===false||(data.session_runtime?.execution_mode==='real_model'&&data.runtime_capabilities?.sponsored_gateway))?<Card className="multi-card"><h2>{data.personal_input?.curriculum_available===false?'该岗位暂无配套学习卡。':'评委赞助入口先体验诊断与简历优化。'}</h2><p>{data.personal_input?.curriculum_available===false?'当前已核对课程集中在数据开发方向，不会套入本岗位。':'作者赞助额度开放岗位诊断、简历优化和一轮短面试；学习工具可在完整案例或本地模拟中体验。'}A诊断和D简历优化可继续使用，不需要先完成学习计划。</p><Button onClick={()=>onNavigate('resume')}>继续优化简历<ArrowRight size={16}/></Button></Card>:!data.plan?<Card className="multi-card"><span className="micro-label">B · A DRAFT BEFORE REVIEW</span><h2>为同一候选人准备14天安排。</h2><p>按本次JD和A的证据选择已有课程，任务数随支持范围变化。先查看B草案，通过程序校验并由你确认发布；未覆盖的要求明确暂缓。</p><Button disabled={busy||Boolean(pending)} onClick={()=>data.abf?prepareAbf({stage:'b_plan',version:0}):run('plan_prepare')}>{data.abf?'准备 B 学习草案调用':'制定固定学习草案'}<ArrowRight size={16}/></Button></Card>:<>
 {!routeTask&&<>
  <Card className="multi-card wb-plan-head"><div><span className="micro-label">B · VERSIONED PLAN</span><h2>{currentPlan?.plan.overall_goal}</h2><p>{data.published_version?`已确认学习 v${data.published_version}`:'草案尚未用于学习'} · 14 天 / {currentPlan?.plan.tasks.length??0} 项任务 / 每日最多 60 分钟</p></div><label>查看计划版本<select value={selectedVersion??data.active_version??''} disabled={busy||dirty} onChange={e=>chooseVersion(Number(e.target.value))}>{data.plan_versions.map(v=><option value={v.version} key={v.version}>v{v.version}{v.version===data.active_version?' · 当前版本':' · 原始快照'}</option>)}</select></label></Card>
  {currentPlan&&<WorkbenchPlanConfirmation key={token+':confirm:'+currentPlan.plan_digest} token={token!} version={currentPlan.version} planDigest={currentPlan.plan_digest} tasks={currentPlan.plan.tasks} historical={isHistorical} published={data.published_version===currentPlan.version} disabled={busy||dirty||Boolean(pending)||Boolean(data.read_only_demo)} onConfirm={extra=>run('plan_confirm_publish',extra)}/>}
  {currentPlan&&<Card className="multi-card"><div className="wb-section-heading"><div><h2>学习计划总览</h2><p>{isHistorical?'当前为历史版本快照。':data.published_version?'按原计划周次展开；任务行显示保存后的实际日期和状态。':'程序校验通过并确认发布后，可打开每日详情。'}</p></div>{todayTask&&!isHistorical&&<Button disabled={busy} onClick={()=>chooseTask(todayTask.task_id)}>打开今日学习<ArrowRight size={16}/></Button>}</div>
   {[1,2].map(week=>{const weekTasks=currentPlan.plan.tasks.filter(t=>taskWeek(t)===week)
    return <details key={week} className="wb-plan-week" open={week===openWeek}>
     <summary>第 {week} 周 · {week===1?'基础与验证':'迁移与表达'} <span>{weekTasks.length} 项任务{data.published_version&&!isHistorical?` · 完成 ${weekTasks.filter(t=>progressByTask.get(t.task_id)?.status==='completed').length}` :''}</span></summary>
     <div className="wb-task-table">{weekTasks.map(t=>{const p=isHistorical?undefined:progressByTask.get(t.task_id)
      return <button key={t.task_id} disabled={!data.published_version||isHistorical||busy} onClick={()=>chooseTask(t.task_id)}><span className="wb-task-day">第 {t.day} 天</span><strong>{t.title}</strong><span>{p?formatDates(p):'原计划第 '+t.day+' 天'} · {total(t.budget)} 分钟</span><span className="wb-task-status">{p?statusLabels[p.status]:'待确认'}</span><ArrowRight size={15}/></button>
     })}</div>
    </details>
   })}
   <details className="wb-plan-week"><summary>复盘、弹性日和暂缓范围</summary><p>第 7、12 天复盘，第 13 天弹性或复测，第 14 天岗位表达。完成进度只统计本次计划的学习任务。</p><p>{data.deferred_scope.title}：{data.deferred_scope.reason} 恢复条件：{data.deferred_scope.revisit_when}</p></details>
  </Card>}
 </>}
 {routeTask&&<div className="wb-lesson-nav"><Button variant="outline" disabled={busy} onClick={()=>onNavigate('plan',{week:String(activeTask?taskWeek(activeTask):1)})}>返回学习计划总览</Button>{activeTask&&<span>每日详情 · 第 {activeTask.day} 天</span>}</div>}
 {routeTask&&(!activeTask||!data.published_version)&&<Card className="multi-card"><h2>每日详情暂不可用</h2><p>请从当前会话已确认的计划重新选择任务。</p></Card>}
 {activeTask&&remediation&&<Card className="multi-card wb-remediation"><span className="micro-label">REVIEW A MISSED QUESTION</span><h2>补学 · {remediation.title}</h2><p>先复习下方任务，重做示例，并用参考要点核对自己的判断。可以在学习笔记写下错因；保存进度会保留这次学习记录。</p><p className="wb-muted">专题复测会重新核对本会话最新有效答卷。学习进度单独记录。</p></Card>}
 {data.published_version&&activeTask&&<div id="wb-learning" className="wb-lesson">{lesson&&form?<><Card className="multi-card"><span className="micro-label">LEARN · SAME SESSION</span><h2>{lesson.task.title}</h2><p>{lesson.task.preparation}</p><p>交付：{lesson.task.expected_outcome}</p><p className="wb-muted">{lesson.guide_notice}</p><details><summary>核对此任务的来源绑定</summary><p>计划v{lesson.plan_version} · 任务 {lesson.task.task_template_id}</p><p>{lesson.task.gap_interpretation}</p>{lesson.task.source_gap_ids.map(id=><code className="wb-id-line" key={id}>{id}</code>)}</details></Card>{lesson.learning_card?<BeginnerLearningCard preview={lesson.learning_card} draft={draft} onDraft={setDraft}/>:<Card className="multi-card"><h2>先按这份基础提纲开始。</h2><p>完整学习卡暂不可用，可先查看核对目标和已绑定资料。</p><ol>{lesson.task.resource_goals.map(g=><li key={g}>{g}</li>)}</ol>{[lesson.resources.primary,lesson.resources.backup].filter(Boolean).map((r,i)=><section className="wb-resource" key={r!.url}><h3><a href={r!.url} target="_blank" rel="noopener noreferrer">{i===0?'主资料':'备选补充'} · {r!.title} ↗</a></h3><p>只读：{r!.section}</p><p>{r!.read_scope}</p><small>核对：{r!.verification.checked_on} · 主备在同一阅读时段二选一</small></section>)}{lesson.resources.state!=='verified_primary'&&<p>{lesson.resources.fallback}</p>}</Card>}<Card className="multi-card"><h2>把练习过程保存为一份成果</h2>
 {lesson.artifact_template&&<><LearningArtifactView artifact={lesson.artifact_template}/>
 {dirty&&<p className="wb-muted">先保存学习进度并清空临时练习草稿，再保存演示成果。</p>}<div className="multi-actions"><Button disabled={busy||Boolean(pending)||dirty||data.read_only_demo} onClick={()=>run('learning_artifact',{plan_version:data.published_version,task_id:lesson.task.task_id})}>保存当前演示练习成果</Button>
 <Button variant="outline" disabled={busy||dirty} onClick={()=>onNavigate('resume')}>查看学习后的简历建议</Button></div></>}
 {(lesson.artifacts?.length??0)>0&&<div className="wb-artifact-list"><h3>本任务已保存的成果</h3>{lesson.artifacts!.map(item=><Button key={item.record_id} variant="outline" onClick={()=>openSource(item.record_id)}>查看已保存成果原记录</Button>)}</div>}
 </Card><Card className="multi-card wb-progress"><div className="wb-section-heading"><h2>记录自己的学习节奏。</h2><span className="wb-chip">本机已保存：{statusLabels[lesson.progress.status]}</span></div><p>日期和进度可以调整。这里不评分，也不会把“已完成”改写成“已掌握”。</p><div className="wb-form-grid"><label>学习状态<select value={form.status} disabled={busy||data.read_only_demo} onChange={e=>setForm({...form,status:e.target.value,reason:e.target.value==='deferred'?form.reason:''})}>{Object.entries(statusLabels).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select></label><label>开始日期<input type="date" value={form.start_date} disabled={busy||data.read_only_demo} onChange={e=>setForm({...form,start_date:e.target.value})}/></label><label>结束日期<input type="date" value={form.end_date} disabled={busy||data.read_only_demo} onChange={e=>setForm({...form,end_date:e.target.value})}/></label></div>{form.status==='deferred'&&<label>暂缓原因<Textarea value={form.reason} maxLength={500} disabled={busy||data.read_only_demo} onChange={e=>setForm({...form,reason:e.target.value})}/></label>}<label>学习笔记<Textarea value={form.note} maxLength={1000} disabled={busy||data.read_only_demo} onChange={e=>setForm({...form,note:e.target.value})} placeholder="记录你对例子的理解或卡点；请勿填写真实个人资料。"/></label><div className="multi-actions"><Button disabled={busy||Boolean(pending)||data.read_only_demo||!formDirty||(form.status==='deferred'&&!form.reason.trim())} onClick={saveProgress}>保存本会话学习记录<Check size={16}/></Button>{remediation&&<Button variant="outline" disabled={busy||dirty||Boolean(pending)} onClick={()=>onNavigate('retest',{focus:remediation.topic_id})}>前往该专题复测<ArrowRight size={16}/></Button>}</div></Card></>:<p className="quality-loading">正在读取本会话学习卡…</p>}</div>}

 </>}</>}
 {view==='plan'&&data.published_version&&(!routeTask||activeTask)&&<Card className="multi-card wb-learning-recent">
  <div className="wb-section-heading"><h3>{activeTask?'此任务最近的学习记录':'学习 · 进行中和最近记录'}</h3><Button variant="outline" disabled={busy||dirty} onClick={()=>onNavigate('records',taskId?{kind:'learning_progress',task:taskId}:{kind:'learning_progress'})}>查看全部学习记录</Button></div>
  {!activeTask&&tasks.filter(t=>progressByTask.get(t.task_id)?.status==='in_progress').map(t=><Button key={t.task_id} variant="outline" onClick={()=>chooseTask(t.task_id)}>继续学习 · {t.title}</Button>)}
  {learningHistory.length>0?<ul>{learningHistory.map(r=><li key={r.record_id}><Button variant="ghost" onClick={()=>openSource(r.record_id)}>{recordTitle(r)} · {time(r.created_at)}</Button></li>)}</ul>:
    <p>{recordsReady?'暂无学习记录。':'正在读取学习记录…'}</p>}
  
 </Card>}
 {view==='records'&&<>
  <Card className="multi-card wb-record-head"><div><span className="micro-label">A SINGLE RECORD TRAIL</span><h2>同一会话的成长记录</h2><p>按类型、专题或北京时间筛选，打开原答卷、面试或学习记录。</p></div>
   <div className="wb-record-filters">
    <label>记录类型<select value={filters.kind} onChange={e=>changeFilters({kind:e.target.value})}>{Object.entries(recordKinds).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label>
    <label>专题<select value={filters.subject} onChange={e=>changeFilters({subject:e.target.value})}><option value="">全部专题</option>{data.capabilities?.map(t=><option value={t.topic_key} key={t.topic_id}>{t.title}</option>)}</select></label>
    <label>记录日期<input type="date" value={filters.date} onChange={e=>changeFilters({date:e.target.value})}/></label>
    {filters.task&&<span className="wb-chip">{tasks.find(t=>t.task_id===filters.task)?.title??'指定学习任务'}</span>}
    <Button variant="outline" onClick={()=>changeFilters({kind:'all',subject:'',date:'',task:''})}>清除筛选</Button>
   </div>
  </Card>
  {!recordsReady?<p role="status">{error?'成长记录暂不可用。':'正在读取本会话记录…'}</p>:<div className="wb-record-layout">
   <div className="wb-record-list" aria-label="成长记录列表">
    {visibleRecords.length===0&&<p>这个筛选范围暂无记录。</p>}
    {visibleRecords.map(r=><button type="button" key={r.record_id} aria-pressed={selectedRecord===r.record_id} className={selectedRecord===r.record_id?'selected':''} onClick={()=>setSelectedRecord(r.record_id)}>
     <span className="micro-label">{recordKinds[r.kind]??r.kind} · #{r.seq}</span><strong>{recordTitle(r)}</strong><small>{time(r.created_at)}</small>
    </button>)}
   </div>
   <Card className="multi-card wb-record-detail" id="wb-selected-record" tabIndex={-1}>{detail?<><span className="micro-label">{recordKinds[detail.kind]??detail.kind} · #{detail.seq}</span><h2>{recordTitle(detail)}</h2><p>{time(detail.created_at)}</p>
    <WorkbenchSavedRecord record={detail} onPlan={()=>onNavigate('plan')} onRemediate={remediate} jd={data.diagnosis?.audit.jd_items} interviewTurns={interviewTurns} onSource={openSource}/>
    {detail.kind==='input'&&<details open><summary>简历与 JD 原文</summary><h3>简历原文</h3><p className="wbd-text">{data.candidate.resume_text}</p><h3>JD 原文</h3><p className="wbd-text">{data.position.jd_text}</p></details>}
    {detail.kind==='diagnosis'&&data.diagnosis&&<Button variant="outline" onClick={()=>onNavigate('diagnosis')}>查看岗位诊断与原句</Button>}
    {recordDestination&&<Button variant="outline" onClick={()=>onNavigate(recordDestination.view,recordDestination.params)}>{recordDestination.label}<ArrowRight size={15}/></Button>}
    <ModelResultSource provenance={(detail.payload as any).model_provenance??(detail.payload as any).report?.model_provenance??(detail.payload as any).model_application?.provenance}/><details><summary>核对完整保存内容（含来源字段）</summary><p>来源：{detail.envelope.source_kind} · 用途：{detail.envelope.evidence_use}</p><pre>{JSON.stringify(detail.payload,null,2)}</pre></details>
    <details><summary>查看同会话引用</summary><code className="wb-id-line">{detail.record_id}</code>{detail.parent_ids.map(id=><code key={id} className="wb-id-line">{id}</code>)}</details>
   </>:<><History size={24}/><h2>{selectedRecord?'这条原记录暂不可用':'选择一条记录'}</h2><p>{selectedRecord?'可核对当前会话，或清除筛选后重新查看。':'选择左侧的学习、答卷、面试或简历记录。'}</p></>}</Card>
  </div>}
 </>}
 {view==='growth'&&<WorkbenchGrowth key={token} token={token!} scope={data.scope} revision={data.revision}
  topics={data.capabilities??[]} completed={completed} total={tasks.length} onRecords={subject=>onNavigate('records',{kind:'answers',subject})}
  onExam={()=>onNavigate('exam')} onRetest={id=>onNavigate('retest',{focus:id})}/>}
 {!data.read_only_demo&&['exam','retest','scenario','resume'].includes(view)&&
  <WorkbenchCallPreparation key={token} token={token!} revision={data.revision} budget={data.session_runtime??data.ce_budget} onUpdated={()=>readState(token!)} target={cedTarget} onClose={()=>setCedTarget(null)} onApply={extra=>{if(dirty||pending)throw Error('请先保存或清空草稿，并确认原操作回执，再采用候选。');return run('candidate_apply',extra)}} onOpenSaved={result=>{setCedTarget(null);if(result.formal_resume_id)onNavigate('resume',{resume:result.formal_resume_id});else onNavigate('records',{record:result.record_id})}}/>}
 {['exam','retest'].includes(view)&&<WorkbenchAssessments initialRun={query.get('run')??''} key={token+':'+view} token={token!} data={data} view={view as 'exam'|'retest'} focusTopic={focus} onRemediate={remediate} onExam={()=>onNavigate('exam')} busy={busy} pending={Boolean(pending)} onPrepareCall={setCedTarget} onAction={run} onDirty={setAssessmentDirty} onRecords={()=>onNavigate('records',{kind:view==='retest'?'retest':'assessment'})} onPlan={()=>onNavigate('plan')} onGrowth={()=>onNavigate('growth')}/>}
 {view==='scenario'&&<WorkbenchInterview initialInterview={query.get('interview')??''} key={token+':interview'} token={token!} data={data} busy={busy} pending={Boolean(pending)} onPrepareCall={setCedTarget} onAction={run} onDirty={setAssessmentDirty} onRecords={()=>onNavigate('records',{kind:'interview'})} onPlan={()=>onNavigate('plan')} onDiagnose={()=>onNavigate('diagnosis')}/>}
 {view==='resume'&&<WorkbenchResume initialResume={query.get('resume')??''} onLearnTask={chooseTask} onSource={openSource} key={token+':resume'} token={token!} data={data} busy={busy} pending={Boolean(pending)} onPrepareCall={setCedTarget} onAction={run} onDirty={setAssessmentDirty} onRecords={()=>onNavigate('records',{kind:'resume'})} onDiagnose={()=>onNavigate('diagnosis')}/>}
 </>}
 <footer className="multi-footer"><span>拾阶 · 同一会话，每一步都有来处</span><span>本次查看不调用模型 · 历史结果按来源标注</span></footer></div>
}

