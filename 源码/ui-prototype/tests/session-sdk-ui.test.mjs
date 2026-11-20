import test from 'node:test'
import assert from 'node:assert/strict'
import {createAbfJournal,readAbfEntry} from '../src/lib/abf-call-journal.mjs'
import {readFile,mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {resolve,join} from 'node:path'
import {pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
const token='f'.repeat(64),pid='11111111-1111-4111-8111-111111111111',aid='22222222-2222-4222-8222-222222222222'
const preview={stage:'b_plan',target_id:'1',preview_id:pid,request_digest:'e'.repeat(64),request:{messages:['PRIVATE PREVIEW']}}
const receipt={stage:'b_plan',target_version:1,preview_id:pid,authorization_id:aid,request_digest:preview.request_digest}
const storage=()=>{const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k),dump:()=>[...m.values()].join('')}}
const serial=()=>{let tail=Promise.resolve();return fn=>{const p=tail.then(fn);tail=p.catch(()=>{});return p}}
test('ABF uncertain authorization and execution retain identity; remount queries original without redispatch',async()=>{
 const s=storage(),calls=[],lock=serial();let lostGrant=true,lostExecute=true
 const request=async(op,t,body)=>{calls.push(op);assert.equal(t,token)
  if(op==='abf_authorize'&&lostGrant){lostGrant=false;throw Error('lost authorization response')}
  if(op==='abf_execute'&&lostExecute){lostExecute=false;throw Error('lost execution response')}
  return {...receipt,status:op==='abf_authorize'?'authorized':'completed',consumed:op!=='abf_authorize'}
 }
 let j=createAbfJournal(s,token,request,lock)
 await assert.rejects(j.authorize(preview));assert.equal(readAbfEntry(s,token).authorizationId,null)
 assert(!s.dump().includes('PRIVATE PREVIEW'))
 await j.recoverAuthorization(j.read());await assert.rejects(j.step('abf_execute',j.read()))
 j=createAbfJournal(s,token,request,lock);await assert.rejects(j.step('abf_execute',j.read()))
 const r=await j.step('abf_status',j.read());await j.clear(j.read(),r)
 assert.equal(j.read(),null);assert.equal(calls.filter(x=>x==='abf_execute').length,1)
 assert.equal(calls.filter(x=>x==='abf_authorize').length,2)
})
test('ABF refuses swapped version and requires durable storage before authorization or execution',async()=>{
 const s=storage();let sent=0;const lock=serial()
 const j=createAbfJournal(s,token,async()=>{sent++;return {...receipt,target_version:2,status:'authorized'}},lock)
 await assert.rejects(j.authorize(preview),/不一致/);assert.equal(j.read().authorizationId,null)
 const broken={getItem:()=>null,setItem:()=>{throw Error('blocked storage')},removeItem:()=>{}}
 await assert.rejects(createAbfJournal(broken,token,async()=>{sent++},lock).authorize(preview))
 assert.equal(sent,1)
})
test('session operation UI identifies SDK rehearsal, C/E-only budget, held and unknown costs and leaves real execution closed',async()=>{
 const root=resolve('.'),cache=join(root,'node_modules/.cache/session-sdk-tests');await mkdir(cache,{recursive:true})
 const dir=await mkdtemp(join(cache,'view-')),module=join(dir,'operations.mjs')
 try{
  const built=await build({root,configFile:join(root,'vite.config.ts'),logLevel:'silent',build:{ssr:join(root,'src/components/WorkbenchSessionOperations.tsx'),write:false,minify:false}})
  const output=Array.isArray(built)?built[0].output:built.output;await writeFile(module,output.find(c=>c.type==='chunk'&&c.isEntry).code)
  const {default:View}=await import(pathToFileURL(module).href)
  const render=data=>renderToStaticMarkup(React.createElement(View,{data,disabled:false,onPrepare:()=>{},onOpenBudget:async()=>{}}))
  let html=render({published_version:2});assert.match(html,/不是真实调用授权/);assert.match(html,/不含 A\/B\/D/)
  html=render({published_version:2,ce_budget:{limit_micro_cny:1000000,spent_simulated_micro_cny:100000,held_unconsumed_micro_cny:200000,consumed_unconfirmed_micro_cny:300000,available_micro_cny:400000,entries:[]}})
  assert.match(html,/0\.400000/);assert.match(html,/0\.200000/);assert.match(html,/0\.300000/);assert.match(html,/本地模拟，费用0元/)
 }finally{assert.ok(dir.startsWith(cache));await rm(dir,{recursive:true,force:true})}
})
