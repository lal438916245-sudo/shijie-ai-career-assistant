import test from "node:test"
import assert from "node:assert/strict"
import {readStored,parsePreviewSession,persistPreview} from "../src/lib/storage.mjs"
import {DRAFT_KEY,SESSION_KEY,SAMPLE_INPUT,makePreviewSession} from "../src/lib/draft.mjs"
import {FLOW_STEPS,VIEW_TITLES,hashForView,viewFromHash,retestRoundFromHash,unknownHash} from "../src/lib/routes.mjs"
const session=makePreviewSession(SAMPLE_INPUT,"test");const {kind,id,role,days,status}=session;const minimal={kind,id,role,days,status}
test("第二轮链接刷新与返回仍明确指向第二轮，非法轮次回退第一轮",()=>{
 assert.equal(hashForView("retest",2),"#retest?round=2")
 assert.equal(viewFromHash(hashForView("retest",2)),"retest")
 assert.equal(retestRoundFromHash(hashForView("retest",2)),2)
 for(const hash of ["#retest","#retest?round=0","#retest?round=99","#retest?round=bad"])assert.equal(retestRoundFromHash(hash),1)
 assert.equal(unknownHash("#no-such-page"),true);assert.equal(unknownHash("#retest?round=2"),false);assert.equal(unknownHash(""),false)
 assert.equal(new Set(FLOW_STEPS.map(step=>step.view)).size,7)
 for(const step of FLOW_STEPS)assert.ok(VIEW_TITLES[step.view])
})
test("损坏与不可读记录只报告恢复失败，不在读取时覆写原数据",()=>{
 const storage={getItem:()=>"{broken",setItem:()=>assert.fail("must not write")}
 const result=readStored(storage,"key",parsePreviewSession,null,"体验会话")
 assert.equal(result.value,null);assert.match(result.notice,/没有被自动覆盖/)
 const inaccessible=readStored({getItem:()=>{throw Error("private details")}},"key",parsePreviewSession,null,"体验会话")
 assert.match(inaccessible.notice,/无法读取/);assert.doesNotMatch(inaccessible.notice,/private details/)
 assert.equal(readStored({getItem:()=>null},"key",parsePreviewSession,null,"体验会话").notice,"")
})
test("恢复体验会话严格检查身份、周期与状态，并去掉未知字段",()=>{
 assert.deepEqual(parsePreviewSession(JSON.stringify({...session,secret:"discard"})),minimal)
 for(const invalid of [{...session,id:"real:1"},{...session,days:0},{...session,days:14.5},{...session,status:"mastered"},{...session,role:""}])assert.equal(parsePreviewSession(JSON.stringify(invalid)),null)
})
test("创建体验会话成功后同时保存草稿与最小身份，不保存附加字段",()=>{
 const map=new Map();persistPreview({getItem:key=>map.get(key)??null,setItem:(key,value)=>map.set(key,value),removeItem:key=>map.delete(key)},SAMPLE_INPUT,{...session,extra:"discard"})
 assert.deepEqual(JSON.parse(map.get(DRAFT_KEY)),SAMPLE_INPUT);assert.deepEqual(JSON.parse(map.get(SESSION_KEY)),minimal)
})
test("第二次写入失败恢复旧草稿和旧会话，不能报告创建成功",()=>{
 for(const previous of [null,"old draft"]){
  const map=new Map([[SESSION_KEY,"old session"]]);if(previous!==null)map.set(DRAFT_KEY,previous)
  const storage={getItem:key=>map.get(key)??null,setItem:(key,value)=>{if(key===SESSION_KEY)throw Error("quota");map.set(key,value)},removeItem:key=>map.delete(key)}
  assert.throws(()=>persistPreview(storage,SAMPLE_INPUT,session),/尚未创建/)
  assert.equal(map.get(DRAFT_KEY)??null,previous);assert.equal(map.get(SESSION_KEY),"old session")
 }
})
test("回滚也失败时明确提示部分保存，不冒充已恢复",()=>{
 let writes=0;const storage={getItem:()=>"old",setItem:()=>{writes++;if(writes>1)throw Error("private quota")},removeItem:()=>{throw Error("fail")}}
 assert.throws(()=>persistPreview(storage,SAMPLE_INPUT,session),error=>/部分输入可能已保留/.test(error.message)&&!error.message.includes("private quota"))
})
