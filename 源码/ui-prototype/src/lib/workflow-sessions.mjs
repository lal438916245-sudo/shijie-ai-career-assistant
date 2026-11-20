import {readSavedLearningPreferences as normalizeLearningPreferences} from './learning-preferences.mjs'
import {validateDraft} from './draft.mjs'
export const REGISTRY_KEY='career-pilot:workflow-double:registry:v1'
const validToken=t=>typeof t==='string'&&/^[0-9a-f]{64}$/.test(t)
const fail=()=>{throw Error('无法读取本地会话列表；原记录未被覆盖，请保留浏览器数据。')}
function validPending(value){try{if(!value||Object.keys(validateDraft(value)).length)return false;normalizeLearningPreferences(value.learning_preferences);return true}catch{return false}}
function copyPending(value){const result={role:value.role,resume:value.resume,jd:value.jd,days:value.days};const preferences=normalizeLearningPreferences(value.learning_preferences);if(preferences!==undefined)result.learning_preferences=preferences;return result}

export async function withRegistryLock(action,locks=globalThis.navigator?.locks){if(!locks?.request)throw Error('当前浏览器不能安全保存会话，请使用支持本机会话管理的桌面浏览器。');return locks.request('career-pilot-workflow-registry-v1',action)}
export function readRegistry(storage){
 try{const raw=storage.getItem(REGISTRY_KEY);if(raw===null)return {version:1,active:null,entries:[]};const value=JSON.parse(raw)
 if(value?.version!==1||!Array.isArray(value.entries)||value.entries.length>100)fail()
 const seen=new Set();for(const e of value.entries){if(!validToken(e.token)||seen.has(e.token)||typeof e.label!=='string'||e.label.length>160||typeof e.saved!=='boolean'||!Number.isFinite(Date.parse(e.createdAt))||(e.pending!==null&&!validPending(e.pending)))fail();seen.add(e.token)}
 if(value.active!==null&&!seen.has(value.active))fail()
 return {version:1,active:value.active,entries:value.entries.map(e=>({token:e.token,label:e.label,saved:e.saved,createdAt:e.createdAt,pending:e.pending===null?null:copyPending(e.pending)}))}
 }catch{fail()}
}
function persist(storage,value){try{storage.setItem(REGISTRY_KEY,JSON.stringify(value));return value}catch{throw Error('浏览器未能保存会话列表，尚未发送新请求；请检查存储权限。')}}
/** @param {any} storage @param {any} random @param {string|null} [legacyToken] @param {any} [pending] */
export function addSession(storage,random,legacyToken=null,pending=null){const value=readRegistry(storage)
 const token=legacyToken??Array.from(random.getRandomValues(new Uint8Array(32)),n=>n.toString(16).padStart(2,'0')).join('')
 if(!validToken(token)||(pending!==null&&!validPending(pending)))fail()
 const existing=value.entries.find(e=>e.token===token)
 if(!existing){if(value.entries.length>=100)throw Error('本地会话列表已达上限，请先保留当前记录。');value.entries.push({token,label:`会话 ${value.entries.length+1}`,saved:false,createdAt:new Date().toISOString(),pending})}
 value.active=token;return persist(storage,value)
}
export function selectSession(storage,token){const value=readRegistry(storage);if(!value.entries.some(e=>e.token===token))fail();value.active=token;return persist(storage,value)}
export function updateSession(storage,token,patch){const value=readRegistry(storage),entry=value.entries.find(e=>e.token===token);if(!entry)fail()
 if(Object.keys(patch).some(k=>!['label','saved','pending'].includes(k)))fail()
 if(patch.pending!==undefined&&patch.pending!==null&&!validPending(patch.pending))fail()
 if(patch.label!==undefined&&(typeof patch.label!=='string'||patch.label.length>160))fail()
 if(patch.saved!==undefined&&typeof patch.saved!=='boolean')fail()
 Object.assign(entry,patch);return persist(storage,value)
}
