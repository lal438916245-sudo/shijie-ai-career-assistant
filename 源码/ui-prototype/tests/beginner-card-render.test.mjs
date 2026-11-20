import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp,writeFile,readFile,rm,mkdir} from 'node:fs/promises'
import {resolve,join} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

const root=fileURLToPath(new URL('..',import.meta.url))
test('完整学习卡显示同一阅读预算、核对资料、纸面跟做、参考与边界；拒绝伪装真实来源',async()=>{
 const cache=join(root,'node_modules','.cache');await mkdir(cache,{recursive:true})
 const directory=await mkdtemp(join(cache,'beginner-card-'))
 try{
  const result=await build({root,configFile:resolve(root,'vite.config.ts'),logLevel:'silent',build:{ssr:resolve(root,'src/components/BeginnerLearningCard.tsx'),write:false,minify:false}})
  const output=Array.isArray(result)?result[0].output:result.output
  const entry=join(directory,'card.mjs');await writeFile(entry,output.find(x=>x.type==='chunk'&&x.isEntry).code)
  const {default:View}=await import(pathToFileURL(entry))
  const preview=JSON.parse(await readFile(join(root,'tests/fixtures/beginner-card-preview.json'),'utf8'))
  const html=renderToStaticMarkup(React.createElement(View,{preview}))
  for(const s of ['零基础完整学习卡','连接后金额为什么变大了','必做路线 50 分钟','不需要数据库','主、备选二选一','7分钟阅读时段','原订单表','配对后的结果','280','200','120','参考答案与自查','不评分、不生成答卷、不更新能力状态','2026-11-03'])assert.ok(html.includes(s),s)
  assert.match(html,/https:\/\/www\.postgresql\.org\/docs\/18\/tutorial-join\.html/)
  assert.match(html,/noopener noreferrer/)
  assert.match(html,/id="beginner-practice-draft"/)
  assert.match(html,/只复用学习模板，不导入历史成绩/)
  const invalid=renderToStaticMarkup(React.createElement(View,{preview:{...preview,source_kind:'real_model_output'}}))
  assert.match(invalid,/学习卡来源暂无法确认/)
  assert.doesNotMatch(invalid,/postgresql\.org|已掌握/)
 }finally{await rm(directory,{recursive:true,force:true})}
})
