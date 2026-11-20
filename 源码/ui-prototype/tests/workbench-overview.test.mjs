import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdir,mkdtemp,writeFile,rm} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

test('overview recommendations follow saved learning and evidence, without declaring learning completion as mastery',async()=>{
 const root=fileURLToPath(new URL('..',import.meta.url)),cache=join(root,'node_modules/.cache')
 await mkdir(cache,{recursive:true});const temp=await mkdtemp(join(cache,'overview-'))
 try {
  const {output}=await build({root,logLevel:'silent',build:{ssr:join(root,'src/components/WorkbenchOverview.tsx'),write:false,minify:false}})
  const entry=join(temp,'view.mjs');await writeFile(entry,output.find(c=>c.type==='chunk'&&c.isEntry).code)
  const {overviewJourney,default:Overview}=await import(pathToFileURL(entry))
  const day='2026-11-07',task={task_id:'task-1',title:'认识连接粒度',day:1}
  const state={candidate:{display_name:'虚构候选人'},position:{title:'初级数据开发'},diagnosis:null,plan:null,published_version:null,recovery_available:false,progress:[],capabilities:[]}
  const next=(s,records=[],ready=true)=>overviewJourney(s,records,day,ready).next
  assert.equal(next(null).view,'new')
  assert.equal(next(state).view,'diagnosis')
  assert.match(next({...state,recovery_available:true}).label,/恢复/)
  const diagnosed={...state,diagnosis:{}}
  assert.match(next(diagnosed).label,/制定/)
  assert.equal(next({...diagnosed,personal_input:true}).view,'resume')
  assert.match(next({...diagnosed,personal_input:true,resume_reports:[{}]}).label,/已保存/)
  const draft={...diagnosed,plan:{plan:{tasks:[task]}}}
  assert.match(next(draft).label,/确认/)
  const published={...draft,published_version:2,progress:[{task_id:task.task_id,status:'in_progress',start_date:day,end_date:day}]}
  assert.deepEqual(next(published).params,{task:task.task_id})
  const futureTask={task_id:'task-2',title:'后续任务',day:2}
  const overdue={...published,plan:{plan:{tasks:[task,futureTask]}},progress:[
   {...published.progress[0],status:'not_started',start_date:'2026-11-05',end_date:'2026-11-05'},
   {task_id:futureTask.task_id,status:'not_started',start_date:day,end_date:day},
  ]}
  assert.deepEqual(next(overdue).params,{task:task.task_id})
  assert.deepEqual(next({...overdue,progress:[overdue.progress[0],{...overdue.progress[1],status:'in_progress'}]}).params,{task:futureTask.task_id})
  const paused={...published,progress:[{...published.progress[0],status:'deferred'}]}
  assert.match(next(paused).label,/暂缓/)
  const completed={...published,progress:[{...published.progress[0],status:'completed'}]}
  assert.equal(next(completed).view,'exam')
  assert.equal(next(completed,[],false).view,'growth')
  const weak={topic_id:'topic-sql',title:'SQL',state:'needs_retest',latest_score:55,label:'待补强'}
  assert.deepEqual(next({...completed,capabilities:[weak]}).params,{focus:weak.topic_id})
  const mastered={...completed,capabilities:[{...weak,state:'mastered',latest_score:85}]}
  assert.equal(next(mastered).view,'scenario')
  const interview={kind:'interview',payload:{event:'interview_report'}}
  assert.equal(next(mastered,[interview]).view,'resume')
  const unscored={...mastered,capabilities:[{...weak,state:'review_required',latest_score:85,pending_ids:['pending']}]}
  assert.equal(next(unscored,[interview]).view,'exam')
  const markup=renderToStaticMarkup(React.createElement(Overview,{data:completed,label:'比赛会话 1',records:[],recordsReady:true,date:day,onNavigate:()=>{}}))
  assert.equal((markup.match(/<li>/g)??[]).length,5)
  assert.match(markup,/C\/E未完成不阻塞D/)
  assert.match(markup,/0 项/)
  assert.match(markup,/aria-current="step"/)
  assert.match(markup,/不代表真实学习成效/)
  const blocked=renderToStaticMarkup(React.createElement(Overview,{data:state,records:[],recordsReady:true,date:day,blocked:true,onNavigate:()=>{}}))
  assert.equal((blocked.match(/disabled=""/g)??[]).length,8)
 }finally{await rm(temp,{recursive:true,force:true})}
})

