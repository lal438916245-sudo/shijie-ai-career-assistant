import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp,writeFile,rm,mkdir} from 'node:fs/promises'
import {resolve,join} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

const root=fileURLToPath(new URL('..',import.meta.url))
test('准备、作答和报告互斥；当前题唯一，历史及解析按场景展示',async()=>{
 const cache=join(root,'node_modules','.cache');await mkdir(cache,{recursive:true})
 const directory=await mkdtemp(join(cache,'practice-render-'))
 try{
  const result=await build({root,configFile:resolve(root,'vite.config.ts'),logLevel:'silent',build:{ssr:resolve(root,'src/components/JourneyPracticeFlow.tsx'),write:false,minify:false}})
  const output=Array.isArray(result)?result[0].output:result.output
  const code=output.find(x=>x.type==='chunk'&&x.isEntry).code
  const entry=join(directory,'flow.mjs');await writeFile(entry,code)
  const {default:Flow}=await import(pathToFileURL(entry))
  const noop=()=>{}
  const base={preparing:false,preparation:React.createElement('div',null,'准备范围选择'),busy:false,answer:'',history:[],onAnswer:noop,onSubmit:noop,onNext:noop,onFinish:noop,onPrepare:noop,onResume:noop,onRecords:noop,onLearning:noop,topics:{sql:'SQL'}}
  const run={run_id:'r',kind:'day',status:'active',scope:{},current_question:{id:'q',text:'当前唯一问题',topic_ids:['sql']},submitted_count:0,question_count:2,result:null,report:null,reviews:[]}
  const render=props=>renderToStaticMarkup(React.createElement(Flow,{...base,...props}))
  const prepared=render({run,preparing:true});assert.match(prepared,/准备范围选择/);assert.doesNotMatch(prepared,/当前唯一问题/);assert.match(prepared,/继续本次练习/)
  const active=render({run});assert.match(active,/当前唯一问题/);assert.doesNotMatch(active,/准备范围选择/);assert.equal((active.match(/id="journey-answer"/g)||[]).length,1)
  const pending=render({run:{...run,status:'awaiting_next',submitted_count:1,current_question:null}});assert.match(pending,/进入下一题/);assert.doesNotMatch(pending,/id="journey-answer"/)
  const review={item_id:'q',question_text:'已提交题目',answer:'我的输入',topic_ids:['sql'],reference_answer:'人工参考答案',explanation:'解题原因',checkpoints:['核对'],common_mistakes:['常见误区'],notice:'不评价回答'}
  const report=render({run:{...run,status:'completed',submitted_count:2,current_question:null,reviews:[review]}});assert.match(report,/本次报告/);assert.match(report,/人工参考答案/);assert.doesNotMatch(report,/准备范围选择|id="journey-answer"/);assert.match(report,/<details class="practice-review">/)
  const interview=render({run:{...run,kind:'interview'},history:[{item_id:'old',question_text:'上一轮问题',answer:'上一轮回答'}]});assert.match(interview,/已提交面试对话/);assert.match(interview,/上一轮回答/)
 }finally{await rm(directory,{recursive:true,force:true})}
})
