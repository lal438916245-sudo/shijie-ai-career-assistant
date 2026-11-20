import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdir,mkdtemp,writeFile,rm} from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

test('complete case preserves an explicit weekly answer link and a focused retest instead of selecting the latest',async()=>{
 const root=resolve('.'),cache=join(root,'node_modules/.cache/complete-navigation');await mkdir(cache,{recursive:true});const dir=await mkdtemp(join(cache,'view-'))
 try{
  const bundle=await build({root,configFile:join(root,'vite.config.ts'),logLevel:'silent',build:{ssr:join(root,'src/components/CompleteCaseReview.tsx'),write:false,minify:false}})
  const file=join(dir,'case.mjs');await writeFile(file,bundle.output.find(c=>c.type==='chunk'&&c.isEntry).code)
  const {default:View}=await import(pathToFileURL(file))
  const data={assessment_runs:[{run_id:'latest-day',kind:'day',title:'最近日考核'},{run_id:'selected-week',kind:'week',title:'指定周考核'},{run_id:'recent-retest',kind:'retest',topic_id:'sql',title:'SQL复测'},{run_id:'selected-retest',kind:'retest',topic_id:'stream',title:'流处理复测'}]}
  const render=props=>renderToStaticMarkup(React.createElement(View,{data,token:'a'.repeat(64),onNavigate:()=>{},summary:{},...props}))
  const week=render({view:'exam',initialRun:'selected-week'})
  assert.match(week,/<option value="selected-week" selected=""/)
  assert.doesNotMatch(week,/演示设置|准备 C|开始.*考核/)
  const topic=render({view:'retest',focusTopic:'stream'})
  assert.match(topic,/<option value="selected-retest" selected=""/)
  const explicit=render({view:'retest',initialRun:'recent-retest',focusTopic:'stream'})
  assert.match(explicit,/<option value="recent-retest" selected=""/)
 }finally{assert.ok(dir.startsWith(cache));await rm(dir,{recursive:true,force:true})}
})
