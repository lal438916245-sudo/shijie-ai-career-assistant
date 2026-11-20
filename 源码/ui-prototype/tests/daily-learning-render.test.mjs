import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp,writeFile,readFile,rm,mkdir} from 'node:fs/promises'
import {resolve,join} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
const root=fileURLToPath(new URL('..',import.meta.url))

test('每日学习显示时间、内置讲解、必做选做、参考自查与独立暂缓；旧计划不造新卡',async()=>{
 const cache=join(root,'node_modules','.cache');await mkdir(cache,{recursive:true})
 const dir=await mkdtemp(join(cache,'daily-learning-'))
 try{
  const result=await build({root,configFile:resolve(root,'vite.config.ts'),logLevel:'silent',build:{ssr:resolve(root,'src/components/DailyLearningPlan.tsx'),write:false,minify:false}})
  const output=Array.isArray(result)?result[0].output:result.output
  const entry=join(dir,'daily.mjs');await writeFile(entry,output.find(x=>x.type==='chunk'&&x.isEntry).code)
  const {DailyLearningPlanContent:View}=await import(pathToFileURL(entry))
  const data=JSON.parse(await readFile(join(root,'tests/fixtures/daily-learning.json'),'utf8'))
  const html=renderToStaticMarkup(React.createElement(View,{data}))
  for(const label of ['每天最多 60 分钟','零基础引导','必做 · 先达到最低目标','选做 · 有余力再挑战','从这里开始学习','查看参考答案与自查点','暂缓原因：','时间冲突','本轮暂缓的差距','不代表已掌握'])assert.ok(html.includes(label),label)
  assert.match(html,/完成 0\/4 项，暂缓 1 项/)
  assert.equal((html.match(/保存学习进度/g)||[]).length,4)
  assert.match(html,/事件时间/)
  assert.equal(renderToStaticMarkup(React.createElement(View,{data:{result:{plan:{overall_goal:'旧计划'}},tasks:[]}})),'')
 }finally{await rm(dir,{recursive:true,force:true})}
})
