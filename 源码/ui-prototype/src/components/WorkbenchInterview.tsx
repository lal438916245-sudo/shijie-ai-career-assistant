import {useEffect,useRef,useState} from 'react'
import {ArrowRight,History,MessageCircle,Send,RefreshCw} from 'lucide-react'
import {recentRuns} from '@/lib/workbench-history.mjs'
import type {CedTarget} from './WorkbenchCallPreparation'
import {Card} from './ui/card'
import {Button} from './ui/button'
import {Textarea} from './ui/textarea'
import {workbenchRequest} from '@/lib/workbench-api.mjs'
import {InterviewQuestionBasis, WorkbenchInterviewReport, interviewQuestionLabel} from './WorkbenchInterviewEvidence'
import './workbench-interview.css'

type Props={initialInterview:string;onPrepareCall:(target:CedTarget)=>void;token:string;data:any;busy:boolean;pending:boolean;onAction:(op:string,extra:any)=>Promise<any>;onDirty:(v:boolean)=>void;onRecords:()=>void;onPlan:()=>void;onDiagnose:()=>void}
const dateLabel=(s:string)=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short'}).format(new Date(s))

export default function WorkbenchInterview({initialInterview,token,data,busy,pending,onPrepareCall,onAction,onDirty,onRecords,onPlan,onDiagnose}:Props){
 const sessions=data.interviews??[]
 const [iid,setIid]=useState<string>(sessions.some((r:any)=>r.interview_id===initialInterview)?initialInterview:sessions.find((r:any)=>r.status==='active')?.interview_id??'')
 const [interview,setInterview]=useState<any>(null),[loading,setLoading]=useState(false),[error,setError]=useState('')
 const [mode,setMode]=useState('short'),[include,setInclude]=useState(false),[answer,setAnswer]=useState(''),[draftFor,setDraftFor]=useState(''),[transcript,setTranscript]=useState(false)
 const generation=useRef(0),chat=useRef<HTMLDivElement>(null)
 const dirty=Boolean(answer.trim()),disabled=busy||pending||loading
 const jd=data.diagnosis?.audit.jd_items??[]
 const current=interview?.current_question,questionIdentity=current?current.turn_id+':'+current.text:'',staleDraft=dirty&&draftFor!==questionIdentity
 useEffect(()=>{onDirty(dirty)},[dirty,onDirty])
 useEffect(()=>()=>{generation.current++;onDirty(false)},[onDirty])
 const fetchInterview=async(id:string)=>{const g=++generation.current;setLoading(true);setError('');try{const v=await workbenchRequest('interview?interview_id='+id,token);if(g!==generation.current)return;if(v.scope.session_id!==data.scope.session_id||v.interview.interview_id!==id)throw Error('面试来源不属于当前会话。');setInterview(v.interview)}catch(e){if(g===generation.current)setError((e as Error).message)}finally{if(g===generation.current)setLoading(false)}}
 useEffect(()=>{if(iid)fetchInterview(iid)},[iid,data.revision])
 useEffect(()=>{if(chat.current)chat.current.scrollTop=chat.current.scrollHeight},[interview?.turns.length,transcript])
 useEffect(()=>{if(interview)requestAnimationFrame(()=>document.getElementById(interview.status==='active'?'wbi-dialogue':'wbi-report')?.scrollIntoView({behavior:'smooth',block:'start'}))},[interview?.current_question?.turn_id,interview?.status])
 const open=(id:string)=>{if(dirty||disabled)return;setInterview(null);setTranscript(false);if(id===iid){fetchInterview(id);return}setIid(id)}
 const modelFlow=Boolean(data.session_runtime||data.ce_budget),real=data.session_runtime?.execution_mode==='real_model'
 const writeDisabled=disabled||Boolean(data.read_only_demo)||Boolean(data.abf&&!data.ce_budget&&!data.session_runtime)
 const start=async()=>{const r=await onAction('interview_start',{mode,include_learning_evidence:include});if(r?.interview_id)open(r.interview_id)}
 const send=async()=>{if(!current||!dirty||disabled||staleDraft)return;const r=await onAction('interview_answer',{interview_id:iid,question_turn_id:current.turn_id,answer});if(r){setAnswer('');setDraftFor('');await fetchInterview(iid)}}
 const end=async()=>{if(dirty||disabled)return;const r=await onAction('interview_end',{interview_id:iid});if(r){setTranscript(false);await fetchInterview(iid)}}
 const prepare=()=>{if(dirty||disabled)return;generation.current++;setIid('');setInterview(null);setTranscript(false)}
 const fill=(kind:string)=>{if(!current||disabled||staleDraft)return;setDraftFor(questionIdentity);setAnswer(interview.examples[kind])}
 const change=(value:string)=>{if(!answer.trim()||!value.trim())setDraftFor(value.trim()?questionIdentity:'');setAnswer(value)}
 if(!data.diagnosis)return <Card className="multi-card"><h2>先明确目标岗位与候选人资料。</h2><p>完成本会话A诊断即可开始岗位面试，无需先通过所有学习考核。</p><Button onClick={onDiagnose}>前往岗位诊断<ArrowRight size={16}/></Button></Card>
 return <div className="wbi-workspace">
 <p className="wbi-notice"><strong>{real?'真实模型短面试 · 提问与复盘逐次授权。':modelFlow?'本地体验 · SDK替身，不调用模型。':'岗位固定回放 · 不调用模型。'}</strong>{modelFlow?'先核对采用问题，再保存自己的回答；一问一答后，预览并授权复盘，核对原话与建议后正式保存。':'预设回答与分析仅供演示，不评价本次输入。'}</p>
 {error&&<p className="multi-error" role="alert">{error}</p>}
 {!iid?<Card className="multi-card"><span className="micro-label">ONE ROLE · A SHARED CONTEXT</span><h2>把整个岗位，放进一段对话。</h2><p>{data.position.title} · {data.candidate.display_name}</p><p>从项目经历谈到技术取舍、验证与协作。默认聚焦一个关键岗位要求；扩展模式覆盖更多方向，不因学习完成而跳过未知项。</p><div className="wbi-scope-chips">{['岗位要求','个人经历','依据与边界'].map(s=><span className="wb-chip" key={s}>{s}</span>)}</div><div className="wbi-setup"><label>面试范围<select value={mode} disabled={disabled} onChange={e=>setMode(e.target.value)}><option value="short">短面试 · 1问1答后复盘</option><option value="full">扩展 · 完整岗位面试 · 5个主问题 / 最多2次追问</option><option value="quick">扩展 · 快速体验 · 前3个方向 / 最多1次追问</option></select></label><p>预计{mode==='full'?'12～18':mode==='short'?'2～3':'5～8'}分钟，可随时提前结束。短面试默认围绕一个关键岗位要求，一问一答后复盘；不覆盖全部方向，未涉及部分会明确列出。</p><label className="wbi-context-choice"><input type="checkbox" checked={include} disabled={disabled} onChange={e=>setInclude(e.target.checked)}/><span>加入学习进度与演示能力摘要<small>不包含学习笔记或答卷正文；开始时冻结。未勾选时只使用当前简历、JD与A的岗位关联。</small></span></label></div><details><summary>查看岗位与资料使用范围</summary><p className="wbi-preserve">{data.position.jd_text}</p><p>对话在本机会话保存；进入调用预览时会说明实际发送范围，确认后才执行；已有考核分数不作为真实岗位胜任证明。面试官风格：专业、平和，追问依据和边界。</p></details><Button disabled={writeDisabled} onClick={start}>确认范围，开始岗位面试<MessageCircle size={16}/></Button></Card>:<>
 <Card className="multi-card wbi-session-head"><div><span className="micro-label">JOB INTERVIEW · SAME SESSION</span><h2>{interview?.position.title??'正在恢复面试…'}</h2><p>{!interview?'读取中':interview.status==='active'?'对话进行中':interview.status==='completed'?'本轮问答已结束':'已提前结束'}{interview&&` · ${interview.planned_main}个主问题 / 最多${interview.max_followups}次追问`}</p></div>{interview&&<><p>已保存{interview.turns.filter((t:any)=>t.role==='user').length}轮回答 · 已使用{interview.followups_used}次追问。{interview.persona.style}</p><details><summary>本轮岗位范围与上下文</summary><ul>{interview.coverage_plan.map((c:any)=><li key={c.title}>{c.title} · {c.planned?'已安排':'快速模式未安排'}</li>)}</ul><p>学习摘要：{interview.context_selection.include_learning_evidence?'已加入开始时摘要，不含笔记/答卷正文':'未加入，只使用岗位与候选人资料'}。</p>{interview.context_summary&&<p>冻结时计划版本{interview.context_summary.plan_version??'尚未发布'}，包含{interview.context_summary.progress.length}项任务进度和{interview.context_summary.capabilities.length}个演示能力摘要。后续学习变化不改写旧面试上下文。</p>}</details></>}<div className="multi-actions"><Button variant="outline" disabled={disabled||dirty} onClick={()=>fetchInterview(iid)}><RefreshCw size={15}/>读取已保存对话</Button>{interview?.status==='active'?<Button variant="outline" disabled={writeDisabled||dirty} onClick={end}>结束面试并生成复盘</Button>:interview&&<Button variant="outline" disabled={disabled||dirty} onClick={prepare}>准备新一轮岗位面试</Button>}<Button variant="outline" disabled={disabled||dirty} onClick={onRecords}>查看全部面试记录<History size={15}/></Button></div></Card>
 {loading&&!interview&&<p role="status">正在读取已保存的对话与复盘…</p>}
 {interview&&<>
 {interview.status!=='active'&&<div className="wbi-view-tabs" role="group" aria-label="面试结果查看方式"><Button variant={transcript?'outline':'default'} onClick={()=>setTranscript(false)}>复盘报告</Button><Button variant={transcript?'default':'outline'} onClick={()=>setTranscript(true)}>完整对话</Button></div>}
 {(interview.status==='active'||transcript)&&<Card className="multi-card wbi-chat-card" id="wbi-dialogue"><div className="wbi-chat" ref={chat} role="log" aria-label="面试对话" aria-live="polite">{interview.turns.map((t:any)=><article className={'wbi-bubble '+(t.role==='user'?'from-user':'from-interviewer')} key={t.turn_id}><header><strong>{t.role==='user'?'我的回答':`岗位面试官 · ${interviewQuestionLabel(t)}`}</strong><small>{dateLabel(t.created_at)}</small></header><p className="wbi-preserve">{t.text}</p>{t.role==='assistant'&&<InterviewQuestionBasis question={t} jd={jd} turns={interview.turns}/>}</article>)}</div><p className="wb-muted">每道题都可展开出题依据。参考回答思路将在面试结束后的复盘中开放。</p></Card>}
 {current&&<Card className="multi-card wbi-composer"><h3>{current.is_followup?'回应这次追问':'回应当前主问题'} · {current.title}</h3>
 <Button variant="outline" disabled={writeDisabled||dirty} onClick={()=>onPrepareCall({stage:'e_turn',targetId:iid})}>准备 E 提问调用</Button>{staleDraft&&<p role="alert">当前问题已经变化，旧草稿仍保留。请先核对/复制，再清空；不会把旧草稿发送给新的问题。</p>}<label>我的面试回答<Textarea value={answer} maxLength={6000} disabled={writeDisabled} onChange={e=>change(e.target.value)} placeholder="可以坦诚说明不知道或尚未实践；无需编造生产经历。" onKeyDown={e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();send()}}}/></label><div className="multi-actions"><Button disabled={writeDisabled||!dirty||staleDraft||Boolean(modelFlow&&!current?.model_application)} onClick={send}>发送回答<Send size={15}/></Button>{dirty&&<Button variant="ghost" disabled={disabled} onClick={()=>{setAnswer('');setDraftFor('')}}>清空本轮草稿</Button>}</div>{!modelFlow&&interview.examples&&<details><summary>体验预设分析：填入内置示例</summary><p>只对完全匹配内置示例的回答展示对应预设分析。改写成其他文字会作为自定义回答保存，不判对错；这不是关键词评分。</p><div className="multi-actions"><Button variant="outline" disabled={disabled||staleDraft} onClick={()=>fill('needs_detail')}>填入待补充示例</Button><Button variant="outline" disabled={disabled||staleDraft} onClick={()=>fill('clear')}>填入清晰示例</Button></div></details>}<p className="wb-muted">未发送草稿仅当前页面；已发送回答不可覆盖，可刷新恢复。请先发送或清空草稿，再结束或切换会话。</p></Card>}
 {interview.status!=='active'&&dirty&&<Card className="multi-card"><h3>旧草稿仍保留，请核对后清空。</h3><Textarea value={answer} readOnly/><Button onClick={()=>{setAnswer('');setDraftFor('')}}>清空已核对草稿</Button></Card>}
 {interview.report&&!transcript&&<Card className="multi-card" id="wbi-report"><WorkbenchInterviewReport report={interview.report} jd={jd} turns={interview.turns} onPlan={onPlan}/><Button variant="outline" disabled={writeDisabled} onClick={()=>onPrepareCall({stage:'e_report',targetId:iid})}>准备 E 复盘调用</Button></Card>}
 </>}
 </>}
 {sessions.length>0&&<Card className="multi-card"><h3>岗位面试 · 进行中和最近记录</h3><div className="wbi-history">{recentRuns<any>(sessions).map((r:any)=><button disabled={disabled||dirty} key={r.interview_id} onClick={()=>open(r.interview_id)}><span><strong>第{sessions.length-sessions.indexOf(r)}次 · {r.position_title}</strong><small>{dateLabel(r.created_at)} · 已答{r.answered_count}轮</small></span><span>{r.status==='active'?'继续对话':r.status==='completed'?'查看复盘':'提前结束的复盘'}</span><ArrowRight size={15}/></button>)}</div><Button variant="outline" disabled={disabled} onClick={onRecords}>查看全部</Button></Card>}
 </div>
}
