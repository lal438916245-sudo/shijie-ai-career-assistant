import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile,writeFile,mkdtemp,mkdir,rm} from 'node:fs/promises'
import {resolve,join} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {build} from 'vite'
const root=fileURLToPath(new URL('..',import.meta.url))
test('published real D labels generation, simulated evidence, old usage and no new dispatch separately',async()=>{
 const cache=join(root,'node_modules/.cache');await mkdir(cache,{recursive:true});const dir=await mkdtemp(join(cache,'published-D-'))
 try{
  const built=await build({root,configFile:resolve(root,'vite.config.ts'),logLevel:'silent',build:{ssr:resolve(root,'src/components/WorkbenchResumeProvenance.tsx'),write:false,minify:false}})
  const output=Array.isArray(built)?built[0].output:built.output;const entry=join(dir,'view.mjs')
  await writeFile(entry,output.find(c=>c.type==='chunk'&&c.isEntry).code)
  const {default:View}=await import(pathToFileURL(entry))
  const asset=JSON.parse(await readFile(resolve(root,'../examples/competition_case/v2/results/d-20261110.json'),'utf8'))
  const real=renderToStaticMarkup(React.createElement(View,{report:{...asset.resume.report,result_provenance:asset.provenance}}))
  for(const s of ['真实模型结果','已核对采用','DeepSeek','deepseek-flash','4,903','固定虚构演示','不调用模型','小于 0.01 元','未提供精确值','不证明生产经验'])assert.ok(real.includes(s),s)
  assert.ok(!real.includes('API Key'));assert.ok(!real.includes('encrypted_key'))
  const fixed=renderToStaticMarkup(React.createElement(View,{report:{model_application:{simulated:true}}}))
  assert.ok(fixed.includes('固定演示建议'));assert.ok(!fixed.includes('真实模型结果'));assert.ok(!fixed.includes('4,903'))
  const unknown=renderToStaticMarkup(React.createElement(View,{report:{model_application:{simulated:false}}}))
  assert.ok(unknown.includes('真实模型结果'));assert.ok(!unknown.includes('4,903'));assert.ok(!unknown.includes('0.01'))
 }finally{assert.ok(dir.startsWith(cache));await rm(dir,{force:true,recursive:true})}
})
