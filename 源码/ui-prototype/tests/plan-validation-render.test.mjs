import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp,writeFile,rm,mkdir} from 'node:fs/promises'
import {resolve,join} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

const root=fileURLToPath(new URL('..',import.meta.url))
test('失败回执显示具体字段、缺失天数与来源数量；旧回执不虚构原因',async()=>{
 const cache=join(root,'node_modules','.cache');await mkdir(cache,{recursive:true})
 const directory=await mkdtemp(join(cache,'plan-errors-'))
 try{
  const result=await build({root,configFile:resolve(root,'vite.config.ts'),logLevel:'silent',build:{ssr:resolve(root,'src/components/PlanValidationDetails.tsx'),write:false,minify:false}})
  const output=Array.isArray(result)?result[0].output:result.output
  const entry=join(directory,'details.mjs');await writeFile(entry,output.find(x=>x.type==='chunk'&&x.isEntry).code)
  const {default:Details}=await import(pathToFileURL(entry))
  const details={contract_version:'session-plan-v2',summary:'学习计划未通过校验',issue_count:3,issues:[{code:'day_coverage',path:'phases[].tasks[].day',message:'缺少学习日',missing_days:[2,3]},{code:'gap_coverage',path:'phases[].tasks[].source_gap_ids',message:'差距未覆盖',missing_count:2}]}
  const html=renderToStaticMarkup(React.createElement(Details,{details}))
  assert.match(html,/phases\[\]\.tasks\[\]\.day/)
  assert.match(html,/缺少第 2、3 天/)
  assert.match(html,/缺少 2 条来源/)
  assert.match(html,/共3项问题/)
  assert.match(html,/当前计划未保存/)
  assert.match(html,/每日安排/)
  assert.match(html,/查看具体字段位置/)
  const diagnosis=renderToStaticMarkup(React.createElement(Details,{details:{contract_version:'evidence-a-v1',summary:'A诊断未通过校验',issue_count:1,issues:[{code:'unknown_requires_verification',path:'evidence_assessment',requirement_number:5,message:'未知项须先验证，不能直接诊断为不会。'}]}}))
  assert.match(diagnosis,/岗位诊断校验明细/)
  assert.match(diagnosis,/第5项JD判断/)
  assert.match(diagnosis,/未知项须先验证/)
  assert.match(diagnosis,/当前诊断未保存；简历和岗位输入保留/)
  assert.doesNotMatch(diagnosis,/学习计划校验明细|已完成诊断保留/)
  const old=renderToStaticMarkup(React.createElement(Details,{legacy:true}))
  assert.match(old,/旧回执未记录具体校验规则/)
  assert.doesNotMatch(old,/缺少学习日|差距未覆盖/)
 }finally{await rm(directory,{recursive:true,force:true})}
})
