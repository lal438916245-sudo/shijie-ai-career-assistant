import {abfCall} from './abf-call-api.mjs'
import {withWorkbenchLock} from './workbench-sessions.mjs'

export const abfStageNames={a_diagnosis:'A · 岗位诊断',b_plan:'B · 学习计划',f_review:'F · 计划审查'}
const terminal = new Set(['completed','failed_transport','failed_validation','unknown_outcome','expired','invalidated'])
const uuid = value => typeof value==='string' && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value)
const key = token => 'career-pilot:abf-journal:v1:'+token
const storageError = () => Error('本机授权记录暂不可用，请检查浏览器存储后再操作。')
const same = (a,b) => a?.previewId===b?.previewId && a?.authorizationId===b?.authorizationId &&
  a?.stage===b?.stage && a?.targetId===b?.targetId && a?.digest===b?.digest

export function readAbfEntry(storage,token) {
  try {
    const raw=storage.getItem(key(token))
    if(raw===null)return null
    const item=JSON.parse(raw)
    if(!item || !Object.hasOwn(abfStageNames,item.stage) || typeof item.targetId!=='string' ||
       !uuid(item.previewId) || !/^[0-9a-f]{64}$/.test(item.digest) ||
       (item.authorizationId!==null&&!uuid(item.authorizationId)) ||
       typeof item.executeRequested!=='boolean' || (item.executeRequested&&!item.authorizationId))throw storageError()
    if(item.authorizationField!==undefined&&(item.authorizationField!=='accept_session_once'||!['real_model','local_sdk_rehearsal'].includes(item.executionMode)))throw storageError()
    return item
  } catch { throw storageError() }
}

function write(storage,token,item) {
  try { storage.setItem(key(token),JSON.stringify(item)) }
  catch { throw storageError() }
}

function checked(entry,value) {
  if(value.stage!==entry.stage || value.target_version!==Number(entry.targetId) || value.preview_id!==entry.previewId || value.request_digest!==entry.digest ||
     !uuid(value.authorization_id) || (entry.authorizationId&&entry.authorizationId!==value.authorization_id)) {
    throw Error('回执与本地预览或授权不一致，请保留编号后查询。')
  }
  if(entry.authorizationField==='accept_session_once'&&(value.authorization_field!==entry.authorizationField||value.execution_mode!==entry.executionMode))throw Error('运行模式与原单次授权不一致。')
  return value
}

function current(storage,token,expected) {
  const entry=readAbfEntry(storage,token)
  if(!entry||!same(entry,expected))throw Error('另一页面已更新本机会话的授权记录，请重新打开准备区。')
  return entry
}

async function authorize(storage,token,entry,request) {
  const result=checked(entry,await request('abf_authorize',token,{
    preview_id:entry.previewId,request_digest:entry.digest,...(entry.authorizationField==='accept_session_once'?{accept_session_once:true}:{accept_fixed_only:true}),
  }))
  write(storage,token,{...entry,authorizationId:result.authorization_id,executeRequested:result.consumed===true})
  return result
}

export function createAbfJournal(storage,token,request=abfCall,lock=withWorkbenchLock) {
  return {
    read:()=>readAbfEntry(storage,token),
    authorize:preview=>lock(async()=>{
      if(readAbfEntry(storage,token))throw Error('请先核对本会话已有的授权。')
      const entry={stage:preview.stage,targetId:preview.target_id,previewId:preview.preview_id,
        digest:preview.request_digest,authorizationId:null,executeRequested:false,...(preview.authorization_field==='accept_session_once'?{authorizationField:'accept_session_once',executionMode:preview.execution_mode}:{})}
      write(storage,token,entry)
      return authorize(storage,token,entry,request)
    }),
    recoverAuthorization:expected=>lock(async()=>{
      const entry=current(storage,token,expected)
      if(entry.authorizationId)throw Error('授权编号已保存，请查询这次调用。')
      return authorize(storage,token,entry,request)
    }),
    restoreStoredReceipt:(target,authorizationId)=>lock(async()=>{
      const before=readAbfEntry(storage,token)
      if(before?.authorizationId&&before.authorizationId!==authorizationId)throw Error('请先查询并结束当前授权，原回执不会丢失。')
      if(!uuid(authorizationId)||!Object.hasOwn(abfStageNames,target.stage)||!Number.isInteger(target.version))throw Error('请选择同一会话已保存的回执。')
      const value=await request('abf_status',token,{authorization_id:authorizationId})
      if(value.stage!==target.stage||value.target_version!==target.version||value.authorization_id!==authorizationId||!uuid(value.preview_id)||!/^[0-9a-f]{64}$/.test(value.request_digest))throw Error('原回执与当前目标不一致。')
      if(before){current(storage,token,before)}else if(readAbfEntry(storage,token)){throw Error('另一页面已更新授权记录，请重新打开。')}
      const entry={stage:value.stage,targetId:String(value.target_version),previewId:value.preview_id,digest:value.request_digest,authorizationId:value.authorization_id,executeRequested:value.consumed===true,
        ...(value.authorization_field==='accept_session_once'?{authorizationField:'accept_session_once',executionMode:value.execution_mode}:{})}
      checked(entry,value);write(storage,token,entry);return value
    }),
    step:(action,expected)=>lock(async()=>{
      if(!['abf_execute','abf_status','abf_recover'].includes(action))throw Error('调用操作无效。')
      const entry=current(storage,token,expected)
      if(!entry.authorizationId)throw Error('请先找回授权编号。')
      if(action==='abf_execute'){
        if(entry.executeRequested)throw Error('已请求过执行，请查询或恢复原回执。')
        write(storage,token,{...entry,executeRequested:true})
      }
      return checked(entry,await request(action,token,{authorization_id:entry.authorizationId}))
    }),
    clear:(expected,receipt)=>lock(()=>{
      const entry=current(storage,token,expected)
      if(entry.executeRequested&&(!receipt||!terminal.has(checked(entry,receipt).status))) {
        throw Error('已请求执行的授权须先核对为结束状态。')
      }
      try { storage.removeItem(key(token)) }
      catch { throw storageError() }
    }),
  }
}

export const isAbfTerminal = status => terminal.has(status)
