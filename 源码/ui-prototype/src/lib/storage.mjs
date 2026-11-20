import {DRAFT_KEY,SESSION_KEY} from "./draft.mjs"
/** Read-only recovery: never overwrite damaged data during page load.
 * @template T @param {{getItem:(key:string)=>string|null}} storage @param {string} key @param {(raw:string|null)=>T|null} parse @param {T} fallback @param {string} label */
export function readStored(storage,key,parse,fallback,label) {
  try {
    const raw=storage.getItem(key)
    if(raw===null)return {value:fallback,notice:""}
    const value=parse(raw)
    return value===null ? {value:fallback,notice:`${label}暂未恢复，现显示初始内容；原记录没有被自动覆盖。`} : {value,notice:""}
  }catch{return {value:fallback,notice:`暂时无法读取${label}；可以继续填写，保存时会再次尝试。`}}
}
export function parsePreviewSession(raw) {
  try {
    const value=JSON.parse(raw??"null")
    if(value?.kind!=="browser-prototype" || typeof value.id!=="string" || !value.id.startsWith("prototype:") || value.id.length>200 || typeof value.role!=="string" || !value.role.trim() || value.role.length>120 || !Number.isInteger(value.days) || value.days<4 || value.days>30 || value.status!=="input_saved")return null
    const {kind,id,role,days,status}=value;return {kind,id,role,days,status}
  }catch{return null}
}
/** Save both browser records, restoring previous values if the second write fails.
 * @param {{getItem:(key:string)=>string|null,setItem:(key:string,value:string)=>void,removeItem:(key:string)=>void}} storage @param {any} draft @param {any} session */
export function persistPreview(storage,draft,session) {
  const writes=[[DRAFT_KEY,JSON.stringify(draft)],[SESSION_KEY,JSON.stringify({kind:session.kind,id:session.id,role:session.role,days:session.days,status:session.status})]]
  const previous=new Map();const done=[]
  try{
    for(const [key] of writes)previous.set(key,storage.getItem(key))
    for(const [key,value] of writes){storage.setItem(key,value);done.push(key)}
  }catch{
    let restored=true
    for(const key of done.reverse())try{const old=previous.get(key);if(old===null)storage.removeItem(key);else storage.setItem(key,old)}catch{restored=false}
    throw new Error(restored ? "浏览器未能保存，体验会话尚未创建。请保留本页并重试。" : "会话未完成保存，部分输入可能已保留。请保留本页，检查后重试。")
  }
}
