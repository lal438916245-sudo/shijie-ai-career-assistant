import test from "node:test"
import assert from "node:assert/strict"
import { webcrypto } from "node:crypto"
import { readJourneyToken,prepareJourneyToken,prepareNewJourneyToken,readLastRun,saveLastRun,requestForRetry,journeyRequest } from "../src/lib/journey-api.mjs"
import { multiHash,multiRoute } from "../src/lib/multi.mjs"
import { viewFromHash,unknownHash } from "../src/lib/routes.mjs"
const memory=()=>{const data=new Map();return {getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,String(v)),removeItem:k=>data.delete(k)}}
if (!globalThis.crypto) Object.defineProperty(globalThis,"crypto",{value:webcrypto,configurable:true})

test("新案例与记录路由可刷新恢复，旧案例仍保持原身份",()=>{
 const hash=multiHash("records","journey","sql");assert.equal(viewFromHash(hash),"records");assert.equal(unknownHash(hash),false);assert.equal(multiRoute(hash).caseId,"journey");assert.equal(multiRoute(hash).topic,"sql");assert.equal(multiRoute(multiHash("plan","classic","sql")).caseId,"classic");assert.equal(multiRoute(multiHash("plan","multi","sql")).caseId,"multi")
})
test("闭环身份独立、保存恢复并拒绝覆盖损坏身份",()=>{
 globalThis.localStorage=memory();assert.equal(readJourneyToken(),null);const token=prepareJourneyToken();assert.equal(readJourneyToken(),token);assert.equal(prepareJourneyToken(),token);assert.equal(saveLastRun(token,"exam","run-1"),true);assert.equal(readLastRun(token,"exam"),"run-1");assert.equal(readLastRun(token,"scenario"),null);const next=prepareNewJourneyToken();assert.notEqual(next,token);assert.deepEqual(JSON.parse(localStorage.getItem("career-pilot:journey:session-token:v1:previous")),[token])
 localStorage.setItem("career-pilot:journey:session-token:v1","broken");assert.throws(()=>prepareJourneyToken(),/原数据未被覆盖/);assert.equal(localStorage.getItem("career-pilot:journey:session-token:v1"),"broken")
})
test("请求不确定时保留同一身份，修改输入后使用新身份",()=>{
 const first=requestForRetry(null,"answer",{run_id:"a",answer:"甲"});assert.deepEqual(requestForRetry(first,"answer",{run_id:"a",answer:"甲"}),first);assert.notEqual(requestForRetry(first,"answer",{run_id:"a",answer:"乙"}).requestId,first.requestId)
})
test("新服务使用本机同源路径且解析接口结果",async()=>{
 let captured;globalThis.fetch=async (url,options)=>{captured={url,options};return {ok:true,json:async()=>({data:{notice:"固定演示"}})}}
 const result=await journeyRequest("start","token",{kind:"day",request_id:"r"});assert.equal(result.notice,"固定演示");assert.equal(captured.url,"/api/practice/journey/start");assert.equal(captured.options.method,"POST");assert.equal(captured.options.headers["X-Practice-Token"],"token")
})
