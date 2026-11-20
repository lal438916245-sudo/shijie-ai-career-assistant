import {cedCall} from './ced-call-api.mjs'
import {withWorkbenchLock} from './workbench-sessions.mjs'

export const stageNames = {
  c_question:'C · 当前题出题',
  c_grade:'C · 已保存答卷评分',
  e_turn:'E · 当前轮提问',
  e_report:'E · 面试结束复盘',
  d_revision:'D · 简历建议',
}
const terminal = new Set(['completed','failed_transport','failed_validation','unknown_outcome','expired','invalidated'])
const uuid = value => typeof value==='string' && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value)
const key = token => 'career-pilot:ced-journal:v1:'+token
const storageError = () => Error('本机授权记录暂不可用，请检查浏览器存储后再操作。')
const same = (a,b) => a?.previewId===b?.previewId && a?.authorizationId===b?.authorizationId &&
  a?.stage===b?.stage && a?.targetId===b?.targetId && a?.digest===b?.digest

export function readCedEntry(storage,token) {
  try {
    const raw=storage.getItem(key(token))
    if(raw===null)return null
    const item=JSON.parse(raw)
    if(!item || !Object.hasOwn(stageNames,item.stage) || typeof item.targetId!=='string' ||
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
  if(value.stage!==entry.stage || value.preview_id!==entry.previewId || value.request_digest!==entry.digest ||
     !uuid(value.authorization_id) || (entry.authorizationId&&entry.authorizationId!==value.authorization_id)) {
    throw Error('回执与本地预览或授权不一致，请保留编号后查询。')
  }
  if(entry.authorizationField==='accept_session_once'&&(value.authorization_field!==entry.authorizationField||value.execution_mode!==entry.executionMode))throw Error('运行模式与原单次授权不一致。')
  return value
}

function current(storage,token,expected) {
  const entry=readCedEntry(storage,token)
  if(!entry||!same(entry,expected))throw Error('另一页面已更新本机会话的授权记录，请重新打开准备区。')
  return entry
}

async function authorize(storage,token,entry,request) {
  const result=checked(entry,await request('call_authorize',token,{
    preview_id:entry.previewId,request_digest:entry.digest,...(entry.authorizationField==='accept_session_once'?{accept_session_once:true}:{accept_fixed_only:true}),
  }))
  write(storage,token,{...entry,authorizationId:result.authorization_id,executeRequested:result.consumed===true})
  return result
}

export function createCedJournal(storage,token,request=cedCall,lock=withWorkbenchLock) {
  return {
    read:()=>readCedEntry(storage,token),
    authorize:preview=>lock(async()=>{
      if(readCedEntry(storage,token))throw Error('请先核对本会话已有的授权。')
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
    step:(action,expected)=>lock(async()=>{
      if(!['call_execute','call_status','call_recover'].includes(action))throw Error('调用操作无效。')
      const entry=current(storage,token,expected)
      if(!entry.authorizationId)throw Error('请先找回授权编号。')
      if(action==='call_execute'){
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

export const isCedTerminal = status => terminal.has(status)
