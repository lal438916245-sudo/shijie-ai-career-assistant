import {addDays,validDate,daysBetween} from './schedule.mjs'
export const MULTI_CASE='data-engineer-multi-v2'
export const MULTI_KEY='career-pilot:ui-prototype:study-schedule:v2:'+MULTI_CASE
export const TOPIC_KEYS=['stream','sql','model','engineering']
export const STATE_LABELS={mastered:'已掌握',provisional_pass:'暂时通过',needs_retest:'待复测',learning:'学习中 · 尚未验证',unassessed:'尚未验证',regressed:'需重新验证',review_required:'需要人工复核'}
const fail=(message)=>{throw Error(message)}
function unique(items,key){const ids=items.map(item=>item[key]);if(ids.some(id=>id===null||id===undefined)||new Set(ids).size!==ids.length)fail('身份缺失或重复：'+key);return new Map(items.map(item=>[String(item[key]),item]))}
function required(value,keys){if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(key=>!keys.includes(key))||keys.some(key=>!(key in value)))fail('展示合同字段不完整或包含未知字段')}
/** Resolve exactly one owned record. @param {any} core @param {any} extra @param {any[]} refs */
export function multiRefs(core,extra,refs){return refs.map(ref=>{
 const fields={gap:['gaps','gap_id','title'],task:['learning_tasks','task_id','title'],attempt:['attempts','attempt_id','feedback'],interview:['interview_evidence','evidence_id','result'],input:['input_snippets','id','text']}
 const field=fields[ref.kind];if(!field)fail('未知证据类型')
 const source=ref.kind==='input'?extra:core;const matches=source[field[0]].filter(item=>String(item[field[1]])===String(ref.ref_id));if(matches.length!==1)fail('证据缺失或有歧义')
 const item=matches[0];return {...ref,label:ref.kind==='attempt'?`评分 #${item.attempt_id} · ${item.score} 分`:ref.kind==='input'?`${item.kind==='resume'?'简历':'JD'}片段`:item.title??'面试验证',detail:item[field[2]],record:item}
})}
/** Choose by topic and round, never by array position. @param {any} core @param {string} gapId @param {number} round */
export function multiAssessment(core,gapId,round){
 if(![0,1,2].includes(round)||!core.gaps.some(gap=>gap.gap_id===gapId))fail('无效专题或轮次')
 const qs=core.questions.filter(q=>q.gap_ids.includes(gapId)&&q.retest_round===round);if(!qs.length)return null;if(qs.length!==1)fail('专题题目有歧义')
 const q=qs[0],aa=core.attempts.filter(a=>a.task_id===q.task_id);if(aa.length!==1)fail('作答缺失或有歧义')
 const states=core.mastery_states.filter(state=>state.gap_id===gapId&&state.attempt_ids.at(-1)===aa[0].attempt_id);if(states.length!==1)fail('能力状态缺失或有歧义')
 return {question:q,attempt:aa[0],state:states[0]}
}
/** @param {any} core @param {string} gapId */
export function latestMultiState(core,gapId){
 const states=core.mastery_states.filter(state=>state.gap_id===gapId);if(!states.length)fail('专题状态缺失')
 const rank=state=>Math.max(-1,...state.attempt_ids);const max=Math.max(...states.map(rank));const found=states.filter(state=>rank(state)===max);if(found.length!==1)fail('最新状态有歧义');return found[0]
}
/** Read-only validation. This checks recorded scores and identities, not a new mastery algorithm. @param {any} core @param {any} extra */
export function validateMulti(core,extra){
 required(extra,['schema_version','scenario_id','disclosure','topic_order','topics','input_snippets','strengths','schedule','answer_examples','plan_review','interview_dialogue','resume_edits'])
 if(extra.schema_version!==2||core.meta.schema_version!==1||extra.scenario_id!==MULTI_CASE||core.meta.scenario_id!==extra.scenario_id||core.meta.disclosure.generator_type!=='curated_demo'||extra.disclosure.generator_type!=='curated_demo'||core.meta.disclosure.model_name!==null||extra.disclosure.model_name!==null)fail('案例/来源版本不匹配')
 const gaps=unique(core.gaps,'gap_id'),tasks=unique(core.learning_tasks,'task_id'),qs=unique(core.questions,'task_id'),aa=unique(core.attempts,'attempt_id');unique(core.interview_evidence,'evidence_id');unique(core.resume_suggestions,'suggestion_id');unique(extra.input_snippets,'id');unique(extra.topics,'key');unique(extra.answer_examples,'question_id');unique(extra.resume_edits,'suggestion_id')
 if(extra.topics.length!==4||extra.topic_order.join()!==TOPIC_KEYS.join()||extra.topics.some(t=>!TOPIC_KEYS.includes(t.key)||!gaps.has(t.gap_id))||new Set(extra.topics.map(t=>t.gap_id)).size!==4)fail('专题身份不完整')
 for(const topic of extra.topics){multiRefs(core,extra,topic.input_refs.map(ref_id=>({kind:'input',ref_id})));latestMultiState(core,topic.gap_id)}
 for(const task of core.learning_tasks)if(task.gap_ids.length!==1||!gaps.has(task.gap_ids[0]))fail('任务来源无效')
 for(const q of core.questions){
  if(q.gap_ids.length!==1||!gaps.has(q.gap_ids[0])||!q.source_task_ids.length||!q.question_fingerprint||!q.source_task_ids.every(id=>tasks.get(String(id))?.gap_ids.includes(q.gap_ids[0])))fail('考题跨专题或来源无效')
  if(q.retest_round>0){const parent=qs.get(String(q.parent_task_id));if(!parent||parent.retest_round!==0||parent.gap_ids[0]!==q.gap_ids[0])fail('复测父题无效')}else if(q.parent_task_id!==null)fail('首次考核父题错误')
  multiAssessment(core,q.gap_ids[0],q.retest_round)
 }
 if(new Set(core.questions.map(q=>q.question_fingerprint)).size!==core.questions.length)fail('重复题面指纹')
 for(const a of core.attempts){
  if(!qs.has(String(a.task_id))||a.score_source!=='rubric_weighted'||!a.rubric.length||a.rubric.some(r=>!Number.isFinite(r.score)||r.score<0||r.score>100||!Number.isFinite(r.weight)||r.weight<=0)||Math.abs(a.rubric.reduce((n,r)=>n+r.weight,0)-1)>1e-9||Math.round(a.rubric.reduce((n,r)=>n+r.score*r.weight,0))!==a.score||(a.score>=60?'completed':'failed')!==a.status)fail('评分与明细不一致')
 }
 for(const state of core.mastery_states){if(!gaps.has(state.gap_id)||!STATE_LABELS[state.state]||state.attempt_ids.some(id=>!qs.get(String(aa.get(String(id))?.task_id))?.gap_ids.includes(state.gap_id))||state.task_ids.some(id=>!(tasks.get(String(id))??qs.get(String(id)))?.gap_ids.includes(state.gap_id)))fail('状态引用跨专题或缺失')}
 for(const answer of extra.answer_examples)if(aa.get(String(answer.attempt_id))?.task_id!==answer.question_id||answer.origin!=='synthetic_example'||!answer.text)fail('样例答卷身份错误')
 if(extra.answer_examples.length!==core.attempts.length)fail('样例答卷不完整')
 for(const suggestion of core.resume_suggestions){multiRefs(core,extra,suggestion.evidence_refs);if(suggestion.status==='accepted'&&(!suggestion.suggestion||!suggestion.evidence_refs.length))fail('建议缺少依据');if(suggestion.status==='blocked'&&suggestion.suggestion!==null)fail('拦截项不能提供强化文本')}
 for(const edit of extra.resume_edits){if(!core.resume_suggestions.some(s=>s.suggestion_id===edit.suggestion_id))fail('修改记录来源无效');multiRefs(core,extra,edit.input_refs.map(ref_id=>({kind:'input',ref_id})))}
 const interview=extra.interview_dialogue;const evidence=core.interview_evidence.filter(e=>e.evidence_id===interview.evidence_id);if(evidence.length!==1||latestMultiState(core,evidence[0].gap_id).state!==evidence[0].mastery_state||interview.turns.map(t=>t.role).join()!=='interviewer,candidate,interviewer,candidate')fail('面试来源或对话结构错误')
 for(const f of interview.feedback)multiRefs(core,extra,f.refs)
 for(const strength of extra.strengths)multiRefs(core,extra,strength.input_refs.map(ref_id=>({kind:'input',ref_id})))
 const review=extra.plan_review;if(review.plan_id!==core.trace.plan_id||review.initial_version===review.revised_version)fail('计划审查版本无效')
 for(const version of [review.initial,review.revised]){unique(version,'task_id');if(version.length!==tasks.size||version.some(v=>!tasks.has(String(v.task_id))||!Number.isInteger(v.day)||v.day<1||v.day>30))fail('计划版本任务无效')}
 for(const issue of review.issues)if(issue.task_ids.some(id=>!tasks.has(String(id))))fail('审查引用未知任务')
 const schedule=extra.schedule;if(schedule.caseId!==MULTI_CASE||schedule.version!==2||!validDate(schedule.anchor))fail('排程案例不匹配');unique(schedule.items,'id')
 const study=schedule.items.filter(i=>i.kind==='study');if(study.length!==tasks.size||new Set(study.map(i=>i.task_id)).size!==tasks.size)fail('学习安排缺失或重复')
 for(const i of schedule.items)if(!['study','weekly','buffer'].includes(i.kind)||!Number.isInteger(i.day)||i.day<1||i.day>30||!['not_started','in_progress','completed'].includes(i.status)||(i.kind==='study'&&(!tasks.has(String(i.task_id))||!extra.topics.some(t=>t.key===i.topic&&tasks.get(String(i.task_id)).gap_ids.includes(t.gap_id))))||(i.kind!=='study'&&(i.task_id!==null||i.topic!==null)))fail('每日安排身份错误')
 return true
}
/** @param {string} hash */
export function multiRoute(hash){const q=new URLSearchParams(hash.split('?')[1]??'');return {caseId:q.get('case')==='classic'?'classic':q.get('case')==='journey'?'journey':q.get('case')==='workflow'?'workflow':'multi',topic:TOPIC_KEYS.includes(q.get('topic')??'')?(q.get('topic')??'stream'):'stream',round:q.get('round')==='2'?2:1,invalidTopic:q.has('topic')&&!TOPIC_KEYS.includes(q.get('topic'))}}
/** @param {string} view @param {string} caseId @param {string} topic @param {number} [round] */
export function multiHash(view,caseId,topic,round=1){const p=new URLSearchParams({case:caseId==='classic'?'classic':caseId==='journey'?'journey':caseId==='workflow'?'workflow':'multi'});if(caseId!=='classic')p.set('topic',TOPIC_KEYS.includes(topic)?topic:'stream');if(view==='retest'&&round===2)p.set('round','2');return `#${view}?${p}`}
/** @param {any} extra */
export function initialMultiSchedule(extra){return {version:2,caseId:MULTI_CASE,anchor:extra.schedule.anchor,entries:extra.schedule.items.map(i=>({id:i.id,start:addDays(extra.schedule.anchor,i.day-1),end:addDays(extra.schedule.anchor,i.day-1),minutes:i.minutes,status:i.status,note:''})),history:[]}}
function validEntry(i){return validDate(i.start)&&validDate(i.end)&&i.end>=i.start&&daysBetween(i.start,i.end)<=60&&Number.isInteger(i.minutes)&&i.minutes>=5&&i.minutes<=480&&['not_started','in_progress','completed'].includes(i.status)&&typeof i.note==='string'&&i.note.length<=1000}
/** @param {string|null} raw @param {any} extra */
export function parseMultiSchedule(raw,extra){try{const value=JSON.parse(raw??'null');if(value?.version!==2||value.caseId!==MULTI_CASE||!validDate(value.anchor)||!Array.isArray(value.entries)||value.entries.length!==extra.schedule.items.length||!Array.isArray(value.history)||value.history.length>40)return null;const map=unique(value.entries,'id');const entries=extra.schedule.items.map(i=>{const found=map.get(i.id);if(!found||!validEntry(found))fail('无效安排');const {id,start,end,minutes,status,note}=found;return {id,start,end,minutes,status,note}});const history=value.history.map(i=>{if(typeof i.label!=='string'||i.label.length>800||typeof i.at!=='string'||!Number.isFinite(Date.parse(i.at)))fail('无效记录');return {label:i.label,at:i.at}});return {version:2,caseId:MULTI_CASE,anchor:value.anchor,entries,history}}catch{return null}}
/** Explicit user edits only. @param {any} value @param {string} id @param {any} patch */
export function editMultiSchedule(value,id,patch){const old=value.entries.find(i=>i.id===id);if(!old||!patch||Object.keys(patch).some(key=>!['start','end','minutes','status','note','shiftFollowing','reason'].includes(key)))fail('无效任务或修改');const {shiftFollowing=false,reason='',...fields}=patch;const next={...old,...fields};if(!validEntry(next)||typeof shiftFollowing!=='boolean'||typeof reason!=='string'||reason.length>500)fail('请检查日期、预计投入（5–480 分钟）、笔记或调整原因');const delta=daysBetween(old.end,next.end);const index=value.entries.findIndex(i=>i.id===id);return {...value,entries:value.entries.map((i,n)=>n===index?next:shiftFollowing&&delta!==0&&n>index&&i.status!=='completed'?{...i,start:addDays(i.start,delta),end:addDays(i.end,delta)}:i),history:[...value.history,{at:new Date().toISOString(),label:`${id}：${fields.status?'进度调整':fields.note!==undefined?'保存学习记录':'日期/时长调整'}${reason?' · '+reason:''}`}].slice(-40)}}
/** @param {any} value @param {string} anchor */
export function moveMultiStart(value,anchor){if(!validDate(anchor))fail('请选择有效日期');const delta=daysBetween(value.anchor,anchor);return {...value,anchor,entries:value.entries.map(i=>i.status==='completed'?i:{...i,start:addDays(i.start,delta),end:addDays(i.end,delta)}),history:[...value.history,{at:new Date().toISOString(),label:'调整起点，仅移动未完成安排至 '+anchor}].slice(-40)}}
/** @param {any} value @param {any} extra */
export function multiProgress(value,extra){const ids=new Set(extra.schedule.items.filter(i=>i.kind==='study').map(i=>i.id));const items=value.entries.filter(i=>ids.has(i.id));return {total:items.length,completed:items.filter(i=>i.status==='completed').length,active:items.filter(i=>i.status==='in_progress').length,pending:items.filter(i=>i.status==='not_started').length}}
