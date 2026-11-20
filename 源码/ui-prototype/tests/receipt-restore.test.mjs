import test from 'node:test'
import assert from 'node:assert/strict'
import {createAbfJournal} from '../src/lib/abf-call-journal.mjs'
const aid='11111111-1111-4111-8111-111111111111',pid='22222222-2222-4222-8222-222222222222',digest='a'.repeat(64)
const receipt={stage:'a_diagnosis',target_version:0,authorization_id:aid,preview_id:pid,request_digest:digest,consumed:true,status:'completed',authorization_field:'accept_session_once',execution_mode:'real_model'}
function storage(){const map=new Map();return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)}}
test('restore uses the original status endpoint only and never reauthorizes or executes',async()=>{
 const saved=storage(),calls=[]
 const request=async(action,token,body)=>{calls.push({action,body});return receipt}
 const journal=createAbfJournal(saved,'test',request,async fn=>fn())
 assert.equal((await journal.restoreStoredReceipt({stage:'a_diagnosis',version:0},aid)).authorization_id,aid)
 assert.deepEqual(calls,[{action:'abf_status',body:{authorization_id:aid}}])
 assert.equal(journal.read().executeRequested,true)
 await assert.rejects(()=>journal.step('abf_execute',journal.read()),/已请求过执行/)
 assert.equal(calls.length,1)
})
test('restore rejects a foreign target without writing browser history',async()=>{
 const saved=storage(),journal=createAbfJournal(saved,'test',async()=>({...receipt,target_version:1}),async fn=>fn())
 await assert.rejects(()=>journal.restoreStoredReceipt({stage:'a_diagnosis',version:0},aid),/目标不一致/)
 assert.equal(journal.read(),null)
})
