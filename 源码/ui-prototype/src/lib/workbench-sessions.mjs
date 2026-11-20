export const ARCHIVED_WORKBENCH_KEY='career-pilot:competition-workbench:sessions:v1'
export const WORKBENCH_KEY='career-pilot:competition-showcase:20261107:sessions:v1'
const validToken=t=>typeof t==='string'&&/^[0-9a-f]{64}$/.test(t)
const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v)
const date=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v)&&Number.isFinite(Date.parse(v))&&new Date(v+'T00:00:00Z').toISOString().slice(0,10)===v
const fail=()=>{throw Error('无法读取比赛会话列表；原记录未覆盖，请保留浏览器数据。')}
const keys={plan_prepare:['request_id','expected_revision'],plan_confirm_publish:['request_id','expected_revision','plan_version','plan_digest','validation_digest','review_confirmed'],saved_b_apply:['request_id','expected_revision','authorization_id','derivation_digest','review_confirmed'],session_runtime_open:['request_id','expected_revision','execution_mode','budget_micro_cny'],create_personal:['request_id','start_date','target_role','resume_text','jd_text'],ce_budget_open:['request_id','expected_revision','simulation_limit_micro_cny'],abf_apply:['request_id','expected_revision','authorization_id','candidate_digest','review_confirmed'],candidate_apply:['request_id','expected_revision','authorization_id','candidate_digest','review_confirmed','selected_item_ids'],learning_artifact:['request_id','expected_revision','plan_version','task_id'],resume_generate:['request_id','expected_revision'],resume_check:['request_id','expected_revision','resume_id','text'],interview_start:['request_id','expected_revision','mode','include_learning_evidence'],interview_answer:['request_id','expected_revision','interview_id','question_turn_id','answer'],interview_end:['request_id','expected_revision','interview_id'],assessment_start:['request_id','expected_revision','plan_version','kind','period_start','period_end','task_ids','fixture_path'],retest_start:['request_id','expected_revision','plan_version','topic_id','source_attempt_id','fixture_path'],answer:['request_id','expected_revision','run_id','question_id','answer'],assessment_next:['request_id','expected_revision','run_id','last_attempt_id'],assessment_end:['request_id','expected_revision','run_id'],create:['request_id','start_date'],diagnosis:['request_id','expected_revision'],plan:['request_id','expected_revision'],review:['request_id','expected_revision','plan_version'],adopt:['request_id','expected_revision','plan_version','review_id'],publish:['request_id','expected_revision','plan_version'],recover:['request_id','expected_revision'],progress:['request_id','expected_revision','plan_version','task_id','status','note','reason','start_date','end_date']}
function pendingValid(p){
 if(p===null)return true
 if(!p||!keys[p.operation]||!p.body||!Number.isFinite(Date.parse(p.startedAt)))return false
 const b=p.body
 const sized=p.operation==='assessment_start'&&Object.hasOwn(b,'question_count')
 const k=sized?[...keys[p.operation],'question_count']:keys[p.operation]
 if(sized&&(!Number.isInteger(b.question_count)||b.question_count<(b.kind==='day'?1:5)||b.question_count>(b.kind==='day'?5:10)))return false
 if(Object.keys(b).length!==k.length||!k.every(key=>key in b)||!uuid(b.request_id))return false
 if(p.operation==='create_personal')return date(b.start_date)&&typeof b.target_role==='string'&&b.target_role.trim().length>0&&b.target_role.length<=120&&typeof b.resume_text==='string'&&b.resume_text.trim().length>=20&&b.resume_text.length<=60000&&typeof b.jd_text==='string'&&b.jd_text.trim().length>=20&&b.jd_text.length<=30000
 if(p.operation==='create')return date(b.start_date)
 if(!Number.isInteger(b.expected_revision)||b.expected_revision<0)return false
 if(p.operation==='session_runtime_open')return ['real_model','local_sdk_rehearsal'].includes(b.execution_mode)&&Number.isInteger(b.budget_micro_cny)&&b.budget_micro_cny>0&&b.budget_micro_cny<=100000000
 if(p.operation==='ce_budget_open')return Number.isInteger(b.simulation_limit_micro_cny)&&b.simulation_limit_micro_cny>0&&b.simulation_limit_micro_cny<=100000000
 if(p.operation==='plan_confirm_publish')return Number.isInteger(b.plan_version)&&b.plan_version>=1&&/^[0-9a-f]{64}$/.test(b.plan_digest)&&/^[0-9a-f]{64}$/.test(b.validation_digest)&&b.review_confirmed===true
 if(p.operation==='saved_b_apply')return uuid(b.authorization_id)&&/^[0-9a-f]{64}$/.test(b.derivation_digest)&&b.review_confirmed===true
 if(p.operation==='abf_apply')return uuid(b.authorization_id)&&/^[0-9a-f]{64}$/.test(b.candidate_digest)&&b.review_confirmed===true
 if(p.operation==='candidate_apply')return uuid(b.authorization_id)&&/^[0-9a-f]{64}$/.test(b.candidate_digest)&&b.review_confirmed===true&&Array.isArray(b.selected_item_ids)&&b.selected_item_ids.length<=6&&b.selected_item_ids.every(v=>typeof v==='string'&&v.length<=100)&&new Set(b.selected_item_ids).size===b.selected_item_ids.length
 if('plan_version'in b&&(!Number.isInteger(b.plan_version)||b.plan_version<1))return false
 if(p.operation==='learning_artifact')return /^TASK_[0-9a-f]{24}$/.test(b.task_id)
 if(p.operation==='resume_check')return /^RESUME_[0-9a-f]{24}$/.test(b.resume_id)&&typeof b.text==='string'&&Boolean(b.text.trim())&&b.text.length<=6000
 if(p.operation==='interview_start')return ['full','quick','short'].includes(b.mode)&&typeof b.include_learning_evidence==='boolean'
 if(p.operation.startsWith('interview_')&&!/^INTERVIEW_[0-9a-f]{24}$/.test(b.interview_id))return false
 if(p.operation==='interview_answer')return /^ITURN_[0-9a-f]{24}$/.test(b.question_turn_id)&&typeof b.answer==='string'&&Boolean(b.answer.trim())&&b.answer.length<=6000
 if('run_id'in b&&!/^RUN_[0-9a-f]{24}$/.test(b.run_id))return false
 if('fixture_path'in b&&!['repair','pass','weak','review'].includes(b.fixture_path))return false
 if(p.operation==='assessment_start')return ['day','week'].includes(b.kind)&&date(b.period_start)&&date(b.period_end)&&Array.isArray(b.task_ids)&&b.task_ids.length>0&&b.task_ids.length<=10&&b.task_ids.every(id=>/^TASK_[0-9a-f]{24}$/.test(id))&&new Set(b.task_ids).size===b.task_ids.length
 if(p.operation==='retest_start')return /^TOPIC_[0-9a-f]{24}$/.test(b.topic_id)&&/^ATTEMPT_[0-9a-f]{24}$/.test(b.source_attempt_id)
 if(p.operation==='answer')return /^QUESTION_[0-9a-f]{24}$/.test(b.question_id)&&typeof b.answer==='string'&&b.answer.trim().length>0&&b.answer.length<=6000
 if(p.operation==='assessment_next')return /^ATTEMPT_[0-9a-f]{24}$/.test(b.last_attempt_id)
 if('review_id'in b&&(typeof b.review_id!=='string'||!/^REVIEW_[0-9a-f]{24}$/.test(b.review_id)))return false
 if(p.operation==='progress')return /^TASK_[0-9a-f]{24}$/.test(b.task_id)&&['not_started','in_progress','completed','deferred'].includes(b.status)&&typeof b.note==='string'&&b.note.length<=1000&&typeof b.reason==='string'&&b.reason.length<=500&&date(b.start_date)&&date(b.end_date)
 return true
}
export function readWorkbenchRegistry(storage){
 try{const raw=storage.getItem(WORKBENCH_KEY);if(raw===null)return {version:1,active:null,entries:[]};const v=JSON.parse(raw)
 if(v?.version!==1||!Array.isArray(v.entries)||v.entries.length>100)fail()
 const seen=new Set();for(const e of v.entries){if(!validToken(e.token)||seen.has(e.token)||typeof e.label!=='string'||e.label.length>100||!date(e.start_date)||typeof e.saved!=='boolean'||!Number.isFinite(Date.parse(e.createdAt))||!pendingValid(e.pending))fail();seen.add(e.token)}
 if(v.active!==null&&!seen.has(v.active))fail()
 return {version:1,active:v.active,entries:v.entries.map(e=>({token:e.token,label:e.label,start_date:e.start_date,saved:e.saved,createdAt:e.createdAt,pending:e.pending===null?null:JSON.parse(JSON.stringify(e.pending))}))}
 }catch{fail()}
}
function persist(storage,value){try{storage.setItem(WORKBENCH_KEY,JSON.stringify(value));return value}catch{throw Error('浏览器未能保存比赛会话身份，尚未发送新请求。')}}
export async function withWorkbenchLock(action,locks=globalThis.navigator?.locks){if(!locks?.request)throw Error('当前浏览器不能安全保存比赛会话，请使用支持本机存储的桌面浏览器。');return locks.request('career-pilot-competition-workbench-v1',action)}
export function addWorkbenchSession(storage,random,startDate){
 const v=readWorkbenchRegistry(storage);if(!date(startDate))throw Error('请选择有效的计划开始日期。')
 if(v.entries.length>=100)throw Error('比赛会话列表已达上限，请保留当前数据。')
 const token=Array.from(random.getRandomValues(new Uint8Array(32)),n=>n.toString(16).padStart(2,'0')).join('')
 if(!validToken(token)||v.entries.some(e=>e.token===token))fail()
 v.entries.push({token,label:`从头体验 ${v.entries.filter(e=>!e.label.startsWith('完整演示')).length+1}`,start_date:startDate,saved:false,createdAt:new Date().toISOString(),pending:null});v.active=token
 return persist(storage,v)
}
export function addPersonalWorkbenchSession(storage,random,startDate){
 const value=addWorkbenchSession(storage,random,startDate),entry=value.entries.find(e=>e.token===value.active)
 entry.label=`个人资料 ${value.entries.filter(e=>e.label.startsWith('个人资料')).length+1} · 我的求职会话`
 return persist(storage,value)
}
export function selectWorkbenchSession(storage,token){const v=readWorkbenchRegistry(storage);if(!v.entries.some(e=>e.token===token))fail();v.active=token;return persist(storage,v)}
export function patchWorkbenchSession(storage,token,patch){
 const v=readWorkbenchRegistry(storage),e=v.entries.find(e=>e.token===token);if(!e||Object.keys(patch).some(k=>!['saved','pending'].includes(k)))fail()
 if(patch.saved!==undefined&&typeof patch.saved!=='boolean')fail()
 if(patch.pending!==undefined&&!pendingValid(patch.pending))fail()
 Object.assign(e,patch);return persist(storage,v)
}

/** Import only the advertised public fictional replay, preserving the selected user's session. */
export function importWorkbenchReplay(storage,sample,activate=false){
 if(sample?.case_id!=='career-pilot-showcase-20261107'||!validToken(sample.token)||sample.label!=='完整演示 · 林知远的14天成长'||!date(sample.start_date)||!Number.isFinite(Date.parse(sample.createdAt)))fail()
 const value=readWorkbenchRegistry(storage),old=value.entries.find(e=>e.token===sample.token)
 if(!old){if(value.entries.length>=100)fail();value.entries.push({token:sample.token,label:sample.label,start_date:sample.start_date,saved:true,pending:null,createdAt:sample.createdAt})}
 if(activate||value.active===null)value.active=sample.token
 return persist(storage,value)
}


export const PERSONAL_SELECTION_KEY='career-pilot:personal-workbench:last:v1'
/** Filter views only. All entries and archived bytes remain in the shared registry. */
/** @param {any} value @param {'demo'|'personal'} mode @param {string|null} [remembered] */
export function entryRegistry(value,mode,remembered=null){
 const entries=value.entries.filter(e=>mode==='personal'?e.label.startsWith('个人资料'):e.label.startsWith('完整演示'))
 const has=t=>entries.some(e=>e.token===t)
 const active=has(remembered)?remembered:has(value.active)?value.active:entries.at(-1)?.token??null
 return {...value,entries,active}
}
export function readEntryRegistry(storage,mode){
 try{return entryRegistry(readWorkbenchRegistry(storage),mode,mode==='personal'?storage.getItem(PERSONAL_SELECTION_KEY):null)}
 catch{fail()}
}
export function rememberPersonalSelection(storage,token){
 const value=readWorkbenchRegistry(storage)
 if(!value.entries.some(e=>e.token===token&&e.label.startsWith('个人资料')))fail()
 try{storage.setItem(PERSONAL_SELECTION_KEY,token)}catch{throw Error('无法保存当前个人会话的快捷入口，请保留原浏览器数据。')}
 return entryRegistry(value,'personal',token)
}
