import test from 'node:test'
import assert from 'node:assert/strict'
import {REGISTRY_KEY,readRegistry,addSession,selectSession,updateSession,withRegistryLock} from '../src/lib/workflow-sessions.mjs'
import {SAMPLE_INPUT} from '../src/lib/draft.mjs'
import {workflowRequest} from '../src/lib/workflow-api.mjs'
function store(){const values=new Map();return {getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),values}}
const rng=n=>({getRandomValues:b=>{b.fill(n);return b}})
test('新建与选择保留其他会话，重新打开存储仍能恢复身份',()=>{
 const s=store();const a=addSession(s,rng(1)).active;updateSession(s,a,{saved:true,label:'A',pending:null})
 const b=addSession(s,rng(2)).active;assert.notEqual(a,b)
 const restored=readRegistry({getItem:k=>s.getItem(k)});assert.equal(restored.active,b);assert.equal(restored.entries.length,2)
 assert.equal(selectSession(s,a).active,a);assert.equal(readRegistry(s).entries.find(e=>e.token===b).saved,false)
})
test('创建待确认输入随会话保存，确认后清除而不影响其他会话',()=>{
 const s=store(),a=addSession(s,rng(1)).active;updateSession(s,a,{pending:SAMPLE_INPUT})
 const b=addSession(s,rng(2)).active;updateSession(s,b,{pending:{...SAMPLE_INPUT,days:4}})
 assert.deepEqual(selectSession(s,a).entries.find(e=>e.token===a).pending,SAMPLE_INPUT)
 updateSession(s,a,{saved:true,pending:null});assert.equal(readRegistry(s).entries.find(e=>e.token===a).pending,null)
 assert.equal(readRegistry(s).entries.find(e=>e.token===b).pending.days,4)
})
test('损坏列表和写入失败不会覆盖或返回虚假保存成功',()=>{
 const s=store();s.setItem(REGISTRY_KEY,'broken');assert.throws(()=>addSession(s,rng(1)),/原记录未被覆盖/);assert.equal(s.getItem(REGISTRY_KEY),'broken')
 const valid=store();const token=addSession(valid,rng(1)).active;const old=valid.getItem(REGISTRY_KEY)
 assert.throws(()=>selectSession(valid,'f'.repeat(64)),/原记录未被覆盖/);assert.equal(valid.getItem(REGISTRY_KEY),old)
 assert.throws(()=>updateSession({getItem:k=>valid.getItem(k),setItem:()=>{throw Error('blocked')}},token,{saved:true}),/未能保存/)
 assert.equal(valid.getItem(REGISTRY_KEY),old)
})
test('旧标签身份导入幂等，不删除旧列表或待确认输入',()=>{
 const s=store(),legacy='d'.repeat(64);addSession(s,rng(1),legacy,SAMPLE_INPUT);addSession(s,rng(2),legacy)
 const value=readRegistry(s);assert.equal(value.entries.length,1);assert.equal(value.active,legacy);assert.deepEqual(value.entries[0].pending,SAMPLE_INPUT)
})
test('浏览器锁串行保存多个会话；缺少锁时不发起写入',async()=>{
 const s=store();let queue=Promise.resolve();const locks={request(_name,fn){const result=queue.then(fn);queue=result.catch(()=>{});return result}}
 await Promise.all([1,2,3].map(n=>withRegistryLock(()=>addSession(s,rng(n)),locks)))
 assert.equal(readRegistry(s).entries.length,3)
 let wrote=false;await assert.rejects(()=>withRegistryLock(()=>{wrote=true},null),/不能安全保存/);assert.equal(wrote,false)
})
test('连接异常、超时与访问失效分别提示，不自动重复写请求',async()=>{
 const token='a'.repeat(64);let calls=0
 await assert.rejects(()=>workflowRequest('session',token,{},async()=>{calls++;throw Object.assign(Error('aborted'),{name:'AbortError'})}),e=>e.code==='uncertain'&&e.message.includes('先重新读取'))
 assert.equal(calls,1)
 await assert.rejects(()=>workflowRequest('session',token,undefined,async()=>{throw Error('network')}),e=>e.code==='unavailable')
 await assert.rejects(()=>workflowRequest('session',token,undefined,async()=>({ok:false,status:403,json:async()=>({})})),e=>e.code==='access')
})
