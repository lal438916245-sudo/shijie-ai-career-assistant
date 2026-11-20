import test from 'node:test'
import assert from 'node:assert/strict'
import {createCedJournal} from '../src/lib/ced-call-journal.mjs'

const token='a'.repeat(64)
const preview={stage:'c_grade',target_id:'ATTEMPT_'+'b'.repeat(24),
  preview_id:'d8488011-ade9-4425-8564-ec29fc8df6fa',request_digest:'e'.repeat(64),
  request:{messages:['PRIVATE-PREVIEW-BODY']}}
const authorization_id='ec8eb72e-67ed-4a4d-a0e6-6ac02234a3a1'
const receipt={stage:preview.stage,preview_id:preview.preview_id,authorization_id,request_digest:preview.request_digest}
const storage=()=>{
  const values=new Map()
  return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),
    removeItem:key=>values.delete(key),dump:()=>[...values.values()].join('')}
}
function serialized(){
  let tail=Promise.resolve()
  return callback=>{
    const pending=tail.then(callback)
    tail=pending.catch(()=>{})
    return pending
  }
}

test('lost execute retains identity across remount, recovers saved response without resending',async()=>{
  const store=storage(),calls=[]
  const request=async(action,session,body)=>{
    assert.equal(session,token)
    calls.push(action)
    if(action==='call_authorize')return {...receipt,status:'authorized',consumed:false}
    assert.deepEqual(body,{authorization_id})
    if(action==='call_execute'){
      assert.match(store.dump(),/"executeRequested":true/)
      throw Error('response lost')
    }
    if(action==='call_status')return {...receipt,status:'response_saved',consumed:true}
    return {...receipt,status:'completed',consumed:true,result:{marker:'recovered'}}
  }
  const lock=serialized(),journal=createCedJournal(store,token,request,lock)
  await journal.authorize(preview)
  assert.deepEqual(calls,['call_authorize'])
  assert.doesNotMatch(store.dump(),/PRIVATE-PREVIEW-BODY/)
  const before=journal.read()
  await assert.rejects(journal.step('call_execute',before),/response lost/)
  const remounted=createCedJournal(store,token,request,lock)
  const pending=remounted.read()
  assert.equal(pending.authorizationId,authorization_id)
  assert.equal(pending.executeRequested,true)
  await assert.rejects(remounted.step('call_execute',pending),/已请求过执行/)
  const status=await remounted.step('call_status',pending)
  await assert.rejects(remounted.clear(pending,status),/须先核对/)
  const recovered=await remounted.step('call_recover',pending)
  assert.equal(recovered.result.marker,'recovered')
  await remounted.clear(pending,recovered)
  assert.equal(remounted.read(),null)
  assert.deepEqual(calls,['call_authorize','call_execute','call_status','call_recover'])
})

test('lost authorization only recovers the same grant; concurrent execution dispatches once',async()=>{
  const store=storage(),lock=serialized(),calls=[]
  let lost=true
  const request=async(action,session,body)=>{
    calls.push({action,body})
    if(action==='call_authorize'&&lost){lost=false;throw Error('lost authorization')}
    return {...receipt,status:action==='call_authorize'?'authorized':'completed',consumed:action!=='call_authorize'}
  }
  const journal=createCedJournal(store,token,request,lock)
  await assert.rejects(journal.authorize(preview),/lost authorization/)
  const pending=journal.read()
  assert.equal(pending.authorizationId,null)
  await journal.recoverAuthorization(pending)
  assert.deepEqual(calls[0],calls[1])
  const entry=journal.read()
  const otherTab=createCedJournal(store,token,request,lock)
  const results=await Promise.allSettled([journal.step('call_execute',entry),otherTab.step('call_execute',entry)])
  assert.deepEqual(results.map(x=>x.status),['fulfilled','rejected'])
  assert.equal(calls.filter(call=>call.action==='call_execute').length,1)
  assert.equal(createCedJournal(store,'c'.repeat(64),request,lock).read(),null)
})

test('saving execution identity is mandatory and swapped receipts cannot replace it',async()=>{
  const store=storage()
  let sent=0
  const journal=createCedJournal(store,token,async action=>{
    if(action==='call_authorize')return {...receipt,status:'authorized',consumed:false}
    sent++
    return {...receipt,request_digest:'0'.repeat(64),status:'completed'}
  },serialized())
  await journal.authorize(preview)
  const entry=journal.read()
  const set=store.setItem
  store.setItem=()=>{throw Error('quota')}
  await assert.rejects(journal.step('call_execute',entry),/授权记录暂不可用/)
  assert.equal(sent,0)
  store.setItem=set
  await assert.rejects(journal.step('call_status',entry),/回执与本地预览或授权不一致/)
  assert.equal(journal.read().authorizationId,authorization_id)
})
