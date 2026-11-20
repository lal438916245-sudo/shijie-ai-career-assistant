import {Card} from './ui/card'
import {Textarea} from './ui/textarea'
import {Button} from './ui/button'
import './beginner-learning-card.css'

type Table={columns:string[];rows:(string|number)[][]}
type Resource={resource_id:string;title:string;publisher:string;url:string;section:string;read_scope:string;language:string;estimated_read_minutes:number;use_boundary:string;verification:{checked_on:string}}
type TitledTable=Table & {title:string}
type CardCommon={card_id:string;title:string;subtitle:string;prerequisites:string;objectives:string[];authorship:string;resource_slot_policy:string;budget:{total_minutes:number;learning_minutes:number;core_minutes:number;review_minutes:number;optional_minutes:number;notice:string};basis:{jd_quote:string;reason:string};steps:{title:string;minutes:number;instruction:string}[];concepts:{term:string;text:string}[];reading_questions:string[];offline_fallback:string;optional:{prompt:string;answer:string;deliverable:string};fallback:string;assessment_boundary:string;completion_check:string}
type Exercise={prompt:string;deliverable:string;hints:string[];reference_answer:string;checkpoints:string[]}
type SqlCard=CardCommon & {card_version:'beginner-card-v1';worked_example:{orders:Table;items:Table;joined:Table;explanation:string[]};exercise:Exercise & {orders:Table;items:Table;reference_sql:string;sql_notice:string}}
type FollowAlongCard=CardCommon & {card_version:'follow-along-card-v1';worked_example:{intro:string;tables:TitledTable[];explanation:string[]};exercise:Exercise & {tables:TitledTable[]}}
export type LearningCardPreview={source_kind:string;purpose:string;case_id:string;case_version:number;notice:string;resources:{state:string;fallback:string;primary:Resource|null;backup:Resource|null};card:SqlCard|FollowAlongCard}

function CardTables({tables}:{tables:TitledTable[]}){
 return <div className={tables.length>1?'beginner-resource-grid':undefined}>{tables.map(table=><DataTable key={table.title} title={table.title} data={table}/>)}</div>
}

function DataTable({data,title}:{data:Table;title:string}){
 return <div className="beginner-data"><h4>{title}</h4><div className="beginner-table-scroll"><table><thead><tr>{data.columns.map(c=><th scope="col" key={c}>{c}</th>)}</tr></thead><tbody>{data.rows.map((row,i)=><tr key={i}>{row.map((value,j)=><td key={j}>{value}</td>)}</tr>)}</tbody></table></div></div>
}
function Reading({resource,label}:{resource:Resource;label:string}){
 return <section className="beginner-reading"><span className="micro-label">{label} · {resource.language==='zh-CN'?'中文':'英文'} · 指定片段约{resource.estimated_read_minutes}分钟</span><h4><a href={resource.url} target="_blank" rel="noopener noreferrer">{resource.title} ↗</a></h4><p>{resource.publisher} · 核对日期 {resource.verification.checked_on}</p><p><strong>只读这里：</strong>{resource.section}</p><p>{resource.read_scope}</p><small>{resource.use_boundary}</small></section>
}
export default function BeginnerLearningCard({preview,draft='',onDraft=()=>{}}:{preview:LearningCardPreview;draft?:string;onDraft?:(value:string)=>void}){
 if(preview.source_kind!=='curated_demo'||!['learning_content_preview_only','session_bound_learning_card'].includes(preview.purpose)||!['beginner-card-v1','follow-along-card-v1'].includes(preview.card.card_version))return <Card className="multi-card"><p>学习卡来源暂无法确认，请使用原有学习引导。</p></Card>
 const c=preview.card,b=c.budget
 const followAlong=c.card_version==='follow-along-card-v1'
 return <Card className="multi-card beginner-card" aria-label="零基础完整学习卡"><header><span className="micro-label">FOLLOW ALONG · 零基础完整学习卡</span><h2>{c.title}</h2><p>{c.subtitle}</p><p className="beginner-source">{preview.notice}</p></header>
 <div className="beginner-budget"><strong>必做路线 {b.total_minutes-b.optional_minutes} 分钟</strong><span>选做 {b.optional_minutes} 分钟 · 合计最多 {b.total_minutes} 分钟</span><small>{b.notice}</small></div>
 <p><strong>开始前：</strong>{c.prerequisites}</p><h3>今天完成什么</h3><ul>{c.objectives.map(s=><li key={s}>{s}</li>)}</ul><p><strong>对应岗位：</strong>“{c.basis.jd_quote}”</p><p>{c.basis.reason}</p>
 <details open><summary>按顺序跟学 · 时间与步骤</summary><ol className="beginner-route">{c.steps.map(s=><li key={s.title}><h4>{s.title}<span>{s.minutes} 分钟</span></h4><p>{s.instruction}</p></li>)}</ol></details>
 <details open><summary>1 · 先看中文概念，再选一份资料</summary><div className="beginner-concepts">{c.concepts.map(s=><section key={s.term}><h4>{s.term}</h4><p>{s.text}</p></section>)}</div><p>{c.resource_slot_policy}</p><div className="beginner-resource-grid">{preview.resources.primary&&<Reading resource={preview.resources.primary} label="主资料"/>}{preview.resources.backup&&<Reading resource={preview.resources.backup} label="备选补充"/>}</div>{preview.resources.state!=='verified_primary'&&<p role="status">{preview.resources.fallback}</p>}<h4>带着这两个问题读</h4><ul>{c.reading_questions.map(s=><li key={s}>{s}</li>)}</ul><p className="beginner-fallback"><strong>链接打不开或读不懂：</strong>{c.offline_fallback}</p></details>
 <details open><summary>2 · 跟做一个完整例子</summary>{followAlong?<><p>{c.worked_example.intro}</p><CardTables tables={c.worked_example.tables}/></>:<><div className="beginner-resource-grid"><DataTable title="原订单表 · 一行一订单" data={c.worked_example.orders}/><DataTable title="原明细表 · 一行一明细" data={c.worked_example.items}/></div><DataTable title="按订单ID配对后的结果" data={c.worked_example.joined}/></>}<ol>{c.worked_example.explanation.map(s=><li key={s}>{s}</li>)}</ol></details>
 <details open><summary>3 · 换一组数据，动手练一练</summary><p>{c.assessment_boundary}</p><p>{c.exercise.prompt}</p>{followAlong?<CardTables tables={c.exercise.tables}/>:<div className="beginner-resource-grid"><DataTable title="练习订单表" data={c.exercise.orders}/><DataTable title="练习明细表" data={c.exercise.items}/></div>}<p><strong>交付：</strong>{c.exercise.deliverable}</p><label htmlFor="beginner-practice-draft">我的练习草稿（仅当前页面）</label><Textarea id="beginner-practice-draft" maxLength={2000} value={draft} onChange={e=>onDraft(e.target.value)} placeholder={followAlong?'先写结果，再用一句话写出依据……':'先列出配对行和总额，写下判断依据……'}/><p className="multi-muted">草稿不会自动保存，切换任务前请保存到自己的笔记或清空；学习笔记仍由下方原入口保存。</p>{draft&&<Button variant="outline" onClick={()=>onDraft('')}>清空练习草稿</Button>}<details><summary>卡住时看提示</summary><ol>{c.exercise.hints.map(s=><li key={s}>{s}</li>)}</ol></details><details><summary>完成后查看参考答案与自查</summary><p>{c.exercise.reference_answer}</p><ul>{c.exercise.checkpoints.map(s=><li key={s}>{s}</li>)}</ul>{!followAlong&&<details><summary>已有SQL基础？看可复现的只读示例</summary><p>{c.exercise.sql_notice}</p><pre>{c.exercise.reference_sql}</pre></details>}</details></details>
 <details><summary>{followAlong?'选做 · 再看一个边界':'选做 · 没有明细的订单怎么办？'}</summary><p>{c.optional.prompt}</p><p>{c.optional.deliverable}</p><details><summary>查看选做参考</summary><p>{c.optional.answer}</p></details></details>
 <p className="beginner-fallback"><strong>觉得太难：</strong>{c.fallback}</p><p>{c.completion_check}</p><small>{c.authorship}</small>
 </Card>
}
