import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdir,mkdtemp,writeFile,rm} from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

test('mode follows the current session, never configuration readiness or a previous route',async()=>{
 const root=resolve('.'),cache=join(root,'node_modules/.cache/experience-mode');await mkdir(cache,{recursive:true});const dir=await mkdtemp(join(cache,'view-'))
 try{
  const bundle=await build({root,configFile:join(root,'vite.config.ts'),logLevel:'silent',build:{ssr:join(root,'src/components/ExperienceMode.tsx'),write:false,minify:false}})
  const file=join(dir,'mode.mjs');await writeFile(file,bundle.output.find(c=>c.type==='chunk'&&c.isEntry).code)
  const {modeForSession,ExperienceModeBadge}=await import(pathToFileURL(file))
  const local={personal_input:{},session_runtime:{execution_mode:'local_sdk_rehearsal',simulated:true}}
  const real={personal_input:{},session_runtime:{execution_mode:'real_model',simulated:false}}
  for(const [input,expected] of [
   [{entryMode:'demo',data:real},'case'],
   [{entryMode:'personal',data:{runtime_capabilities:{outbound_enabled:true,model_configured:true}}},'pending'],
   [{entryMode:'personal',data:local},'local'],
   [{entryMode:'personal',data:real},'real'],
   [{entryMode:'personal',data:{...real,session_runtime:{execution_mode:'real_model',simulated:true}}},'local'],
   [{entryMode:'personal',data:{session_runtime:{execution_mode:'real_model'}}},'unavailable'],
   [{entryMode:'personal',data:real,loading:true},'loading'],
   [{entryMode:'personal',failed:true},'unavailable'],
   [{entryMode:'personal',data:{personal_input:{},abf:{}}},'local'],
  ])assert.equal(modeForSession(input),expected)
  for(const [mode,text,detail] of [['case','案例回放','不调用模型'],['local','本地模拟','费用0元'],['real','真实模型','']]){
   const html=renderToStaticMarkup(React.createElement(ExperienceModeBadge,{mode}))
   assert.match(html,/role="status"/);assert.ok(html.includes(text)&&html.includes(detail))
   assert.doesNotMatch(html,/<p[ >]|<details[ >]|按次授权|预览、授权/)
  }
 }finally{assert.ok(dir.startsWith(cache));await rm(dir,{recursive:true,force:true})}
})
