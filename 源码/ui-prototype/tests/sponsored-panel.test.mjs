import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdir,mkdtemp,writeFile,rm} from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

test('sponsored v2 preconfig selects real mode without dispatch and preserves local choice',async()=>{
 const root=resolve('.'),cache=join(root,'node_modules/.cache/sponsored-panel');await mkdir(cache,{recursive:true});const dir=await mkdtemp(join(cache,'view-'))
 try{
  const bundle=await build({root,configFile:join(root,'vite.config.ts'),logLevel:'silent',build:{ssr:join(root,'src/components/SessionRuntimePanel.tsx'),write:false,minify:false}})
  const file=join(dir,'panel.mjs');await writeFile(file,bundle.output.find(c=>c.type==='chunk'&&c.isEntry).code)
  const {default:Panel}=await import(pathToFileURL(file))
  let calls=0
  const props={disabled:false,onOpen:async()=>{calls++},onPrepare:()=>{calls++}}
  const data={runtime_capabilities:{outbound_enabled:true,model_configured:true,provider:'评委网关v2 · DeepSeek',model:'deepseek-flash',sponsored_gateway:{version:'judge-gateway-v2',supported_stages:['a_diagnosis','d_revision','e_turn','e_report'],session_budget_micro_cny:1000000,expires_at:'2026-11-20T23:59:00+08:00'}}}
  const html=renderToStaticMarkup(React.createElement(Panel,{...props,data}))
  assert.match(html,/作者额度已就绪/);assert.match(html,/A\/D及一轮短面试/)
  assert.match(html,/<option value="real_model" selected=""/)
  assert.match(html,/本会话预置上限 ¥1\.00/);assert.doesNotMatch(html,/aria-label="会话累计额度"/)
  assert.match(html,/确认模式与额度（不调用模型）/);assert.match(html,/<button[^>]*disabled=""/)
  const local=renderToStaticMarkup(React.createElement(Panel,{...props,data:{runtime_capabilities:{outbound_enabled:false}}}))
  assert.match(local,/<option value="local_sdk_rehearsal" selected=""/)
  assert.match(local,/aria-label="会话累计额度"/);assert.equal(calls,0)
 }finally{assert.ok(dir.startsWith(cache));await rm(dir,{recursive:true,force:true})}
})
