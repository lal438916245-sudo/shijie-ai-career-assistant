import test from 'node:test'
import assert from 'node:assert/strict'
import {normalizeLearningPreferences} from '../src/lib/learning-preferences.mjs'
import {addSession,updateSession,readRegistry} from '../src/lib/workflow-sessions.mjs'
import {workflowRequest,sdkRequest} from '../src/lib/workflow-api.mjs'
import {SAMPLE_INPUT} from '../src/lib/draft.mjs'

function storage(){const values=new Map();return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)}}
test('新草稿每天固定60分钟，保留学习起点；不接受自定义分钟数',()=>{
 assert.deepEqual(normalizeLearningPreferences({daily_minutes:'',starting_level:'beginner'}),{daily_minutes:60,starting_level:'beginner'})
 assert.deepEqual(normalizeLearningPreferences({daily_minutes:'1',starting_level:'beginner'}),{daily_minutes:60,starting_level:'beginner'})
 assert.deepEqual(normalizeLearningPreferences({daily_minutes:'60',starting_level:'beginner'}),{daily_minutes:60,starting_level:'beginner'})
 for(const value of [true,14,241,30.5])assert.deepEqual(normalizeLearningPreferences({daily_minutes:value,starting_level:'foundation'}),{daily_minutes:60,starting_level:'foundation'})
 assert.throws(()=>normalizeLearningPreferences({daily_minutes:60,starting_level:'unknown'}),/学习起点/)
 assert.equal(normalizeLearningPreferences(undefined),undefined)
})

test('创建待确认会话保留每日时间，旧会话不被自动补配置',()=>{
 const s=storage(),rng={getRandomValues(bytes){bytes.fill(37);return bytes}}
 const r=addSession(s,rng),token=r.active
 updateSession(s,token,{pending:{...SAMPLE_INPUT,learning_preferences:{daily_minutes:45,starting_level:'beginner'}}})
 assert.equal(readRegistry(s).entries[0].pending.learning_preferences.daily_minutes,45)
 updateSession(s,token,{pending:{...SAMPLE_INPUT}})
 assert.equal(readRegistry(s).entries[0].pending.learning_preferences,undefined)
})

test('学习状态仅发本机专用接口；断连不重发也不变成模型调用',async()=>{
 let captured,calls=0;const token='b'.repeat(64),body={task_id:1,status:'deferred',reason:'时间冲突',expected_revision:0}
 const response=data=>({ok:true,status:200,json:async()=>({data})})
 await workflowRequest('plan-progress',token,body,async(url,options)=>{captured={url,options};return response({source_kind:'local_workflow_double'})})
 assert.equal(captured.url,'/api/live/plan-progress');assert.deepEqual(JSON.parse(captured.options.body),body)
 await sdkRequest('plan-progress',token,body,'sdk_rehearsal',async(url,options)=>{captured={url,options};return response({source_kind:'sdk_rehearsal_session',mode:'sdk_rehearsal',real_dispatch_enabled:false,simulated:true})})
 assert.equal(captured.url,'/api/sdk/plan-progress')
 await assert.rejects(workflowRequest('plan-progress',token,body,async()=>{calls++;throw Error('offline')}))
 assert.equal(calls,1)
})
