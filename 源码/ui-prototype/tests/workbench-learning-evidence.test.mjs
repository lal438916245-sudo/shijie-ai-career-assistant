import test from 'node:test'
import assert from 'node:assert/strict'
import {webcrypto} from 'node:crypto'
import {workbenchRequest} from '../src/lib/workbench-api.mjs'
import {addWorkbenchSession,patchWorkbenchSession,readWorkbenchRegistry} from '../src/lib/workbench-sessions.mjs'
import {matchesRecord} from '../src/lib/workbench-history.mjs'

test('coursework artifact save uses the fixed session boundary and preserves uncertain request identity',async()=>{
  const values=new Map()
  const storage={getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)}
  const session=addWorkbenchSession(storage,webcrypto,'2026-11-05').active
  const body={request_id:'12345678-1234-1234-1234-123456789abc',expected_revision:3,plan_version:2,task_id:'TASK_'+'a'.repeat(24)}
  const pending={operation:'learning_artifact',body,startedAt:'2026-11-05T04:00:00Z'}
  patchWorkbenchSession(storage,session,{pending})
  let count=0
  await assert.rejects(workbenchRequest('learning_artifact',session,body,async(path,options)=>{
    count++
    assert.equal(path,'/api/live/workbench/learning_artifact')
    assert.equal(options.headers['X-CP-Session'],session)
    assert.deepEqual(JSON.parse(options.body),body)
    throw Error('response lost')
  }),error=>error.code==='uncertain')
  assert.equal(count,1)
  assert.deepEqual(readWorkbenchRegistry(storage).entries[0].pending,pending)
  const before=JSON.stringify([...values])
  assert.throws(()=>patchWorkbenchSession(storage,session,{pending:{...pending,body:{...body,artifact_text:'untrusted upgrade'}}}))
  assert.equal(JSON.stringify([...values]),before)
})

test('artifact history can be located by task, topic and Beijing date',()=>{
  const row={kind:'learning_artifact',created_at:'2026-11-04T16:01:00Z',
    payload:{event:'learning_artifact',artifact:{task_id:'task',topic_keys:['sql','model']}}}
  const filters={kind:'learning_artifact',task:'task',subject:'sql',date:'2026-11-05'}
  assert.equal(matchesRecord(row,filters,[],[]),true)
  assert.equal(matchesRecord(row,{...filters,subject:'engineering'},[],[]),false)
  assert.equal(matchesRecord(row,{...filters,task:'another'},[],[]),false)
})


test('artifact preview supports the original SQL card and later follow-along cards',async()=>{
  const {build}=await import('vite')
  const {fileURLToPath,pathToFileURL}=await import('node:url')
  const {join,resolve}=await import('node:path')
  const {mkdir,mkdtemp,readFile,writeFile,rm}=await import('node:fs/promises')
  const React=await import('react')
  const {renderToStaticMarkup}=await import('react-dom/server')
  const root=fileURLToPath(new URL('..',import.meta.url))
  const cache=join(root,'node_modules','.cache')
  await mkdir(cache,{recursive:true})
  const dir=await mkdtemp(join(cache,'learning-artifact-'))
  try{
    const bundle=await build({root,configFile:resolve(root,'vite.config.ts'),logLevel:'silent',
      build:{ssr:resolve(root,'src/components/WorkbenchLearningEvidence.tsx'),write:false,minify:false}})
    const output=Array.isArray(bundle)?bundle[0].output:bundle.output
    const entry=join(dir,'view.mjs')
    await writeFile(entry,output.find(item=>item.type==='chunk'&&item.isEntry).code)
    const {LearningArtifactView,ResumeLearningHandoff}=await import(pathToFileURL(entry))
    const first=JSON.parse(await readFile(resolve(root,'../examples/competition_case/v1/cards/sql-join-grain.json'),'utf8'))
    const later=JSON.parse(await readFile(resolve(root,'../examples/competition_case/v1/cards/follow-along-v1.json'),'utf8')).cards[0]
    for(const card of [first,later]){
      const view=renderToStaticMarkup(React.createElement(LearningArtifactView,{artifact:{
        title:card.title,summary:'课程练习成果',exercise:card.exercise,notice:'固定课程小样本',
      }}))
      assert.ok(view.includes('<table>')&&view.includes('核对练习输入与参考结果'))
      assert.ok(view.includes(card.exercise.reference_answer.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')))
    }
    const handoff={completed_tasks:1,artifact_tasks:1,ready_tasks:1,total_tasks:1,notice:'固定演示',
      tasks:[{task_id:'task',title:'练习',ready:true,artifact_summary:'核对小样本',
        artifact_record_id:'artifact',source_ids:['artifact'],interview_ids:[]}]}
    const html=renderToStaticMarkup(React.createElement(ResumeLearningHandoff,{
      handoff,onSource:()=>{},sources:[{record_id:'artifact',kind:'learning_artifact'}],
    }))
    assert.ok(html.includes('查看练习成果')&&html.includes('核对小样本'))
  }finally{
    assert.ok(dir.startsWith(cache))
    await rm(dir,{recursive:true,force:true})
  }
})
