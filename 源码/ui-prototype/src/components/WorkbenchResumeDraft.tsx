import {useEffect,useRef,useState} from 'react'
import {Copy} from 'lucide-react'
import {Button} from './ui/button'
import {Textarea} from './ui/textarea'
import {resumeDraft,resumeDraftParts,resumeEdits} from '@/lib/workbench-history.mjs'

export function WorkbenchResumeDraft({report,resumeId,name,onSource}:{
  report:any;resumeId:string;name:string;onSource:(id:string)=>void
}){
  const [chosen,setChosen]=useState<string[]>([])
  const [notice,setNotice]=useState('')
  const draftArea=useRef<HTMLTextAreaElement>(null)
  const key='career-pilot:resume-draft:v1:'+resumeId
  const edits=resumeEdits(report)
  const accepted=edits.filter((item:any)=>chosen.includes(item.item_id)).length
  const draft=resumeDraft(report,chosen,name)
  const parts=resumeDraftParts(report,chosen,name)
  useEffect(()=>{
    setChosen([])
    setNotice('')
    try{
      const ids=JSON.parse(localStorage.getItem(key)??JSON.stringify(report.server_accepted_item_ids??report.preview_default_item_ids??[]))
      if(Array.isArray(ids))setChosen(ids.filter(id=>typeof id==='string'))
    }catch{setNotice('本机采用选择暂不可读，可重新选择。')}
  },[key])
  const adopt=(id:string,include:boolean)=>{
    const next=include?[...new Set([...chosen,id])]:chosen.filter(value=>value!==id)
    setChosen(next)
    try{localStorage.setItem(key,JSON.stringify(next));setNotice('')}
    catch{setNotice('采用选择仅保留在本页。')}
  }
  const selectDraft=()=>{
    draftArea.current?.focus()
    draftArea.current?.select()
    setNotice('已选中整稿，请按 Ctrl+C 或长按复制。')
  }
  const copy=async()=>{
    try{await navigator.clipboard.writeText(draft);setNotice('已复制整份简历草稿。')}
    catch{selectDraft()}
  }
  const locate=(id:string)=>{
    document.getElementById('resume-change-'+id)?.focus()
    document.getElementById('resume-change-'+id)?.scrollIntoView({behavior:'smooth',block:'center'})
  }
  return <section className="wbd-draft-editor" aria-label="简历草稿">
    <div className="wb-section-heading">
      <div><h2>让每一处修改，都有依据。</h2><p>对照原文查看整稿，勾选确认后合入修改。点击高亮可查看下方依据。</p></div>
      <span className="wb-chip">{report.resume_has_header&&!report.model_application?'预览采用':'已采用'} {accepted} 条</span>
    </div>
    {report.model_application&&<p role="status">本份修改已核对并另存为会话简历版本。下方采用选择可用于预览，已保存版本继续保留。</p>}
    <div className="wbd-resume-pair">
      <section aria-labelledby="wbd-original-title">
        <h3 id="wbd-original-title">原有简历</h3>
        <pre className="wbd-resume-paper">{report.resume_text}</pre>
      </section>
      <section aria-labelledby="wbd-optimized-title">
        <div className="wb-section-heading"><h3 id="wbd-optimized-title">优化后的简历</h3><Button size="sm" onClick={copy}><Copy size={16}/>复制整稿</Button></div>
        {accepted===0&&<p className="wb-muted">在下方采用修改，查看整稿变化。</p>}
        <pre className="wbd-resume-paper">{parts.map((part:any,index:number)=>part.itemId?
          <button key={index} className="wbd-change-highlight" aria-label="查看这处修改的依据" onClick={()=>locate(part.itemId)}>{part.text}</button>:
          <span key={index}>{part.text}</span>)}</pre>
        <details className="wbd-copy-area"><summary>选择整稿文本</summary>
          <label htmlFor="wbd-draft-text">整份简历草稿</label>
          <Textarea id="wbd-draft-text" className="wbd-full-draft" ref={draftArea} readOnly value={draft}/>
          <Button variant="outline" onClick={selectDraft}>选择整稿</Button>
        </details>
      </section>
    </div>
    {notice&&<p role="status">{notice}</p>}
    <h3>修改位置与对应证据</h3>
    {report.learning_handoff&&<p className="wb-muted">{report.result_origin==='personal_local'?`本会话关联 ${report.learning_handoff.total_tasks} 项任务，${report.learning_handoff.ready_tasks} 项本地流程记录齐备；尚不能据此写成真实学习成果。`:`本份建议已核对 ${report.learning_handoff.total_tasks} 项学习任务，${report.learning_handoff.ready_tasks} 项具备课程练习表述的演示依据。`}</p>}
    {edits.length===0&&<p>目前没有能定位到原文的可采用修改，整稿保留现有内容。</p>}
    {edits.map((item:any,index:number)=><section className="wbd-draft-change" id={'resume-change-'+item.item_id} tabIndex={-1} key={item.item_id}>
      <div className="wb-section-heading"><h4>修改 {index+1} · {item.title}</h4>
        <label className="wbd-adopt"><input type="checkbox" checked={chosen.includes(item.item_id)} onChange={event=>adopt(item.item_id,event.target.checked)}/>{report.model_application?'预览包含此修改':'采用这条修改'}</label></div>
      <div className="wbd-draft-compare">
        <section><h5>原文</h5><p className="wbd-text">{item.original_quote}</p></section>
        <section><h5>修改后</h5><p className="wbd-text">{item.suggested_text}</p></section>
      </div>
      {item.change_kind==='learning_outcome'&&<span className="wb-chip">学习后课程成果 · 固定演示</span>}
      <p>{item.reason}</p>
      <div className="multi-actions">{item.source_ids.slice(0,3).map((id:string)=><Button key={id} size="sm" variant="outline" onClick={()=>onSource(id)}>
        查看{({input:'简历',diagnosis:'诊断',assessment:'考核',retest:'复测',interview:'面试',learning_progress:'学习',learning_artifact:'练习成果'} as Record<string,string>)[report.sources?.find((source:any)=>source.record_id===id)?.kind]??'相关'}原记录
      </Button>)}</div>
      {item.source_ids.length>3&&<details><summary>查看其余 {item.source_ids.length-3} 项依据</summary><div className="multi-actions">{item.source_ids.slice(3).map((id:string)=><Button key={id} size="sm" variant="outline" onClick={()=>onSource(id)}>定位依据 {item.source_ids.indexOf(id)+1}</Button>)}</div></details>}
    </section>)}
  </section>
}
