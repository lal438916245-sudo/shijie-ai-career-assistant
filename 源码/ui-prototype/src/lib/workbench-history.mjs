/** @type {Record<string,string>} */
export const recordKinds={
  all:'全部类型', learning_progress:'学习进度', learning_artifact:'练习成果', assessment:'日周考核', day:'日考核', week:'周考核',
  retest:'专题复测', answers:'考核与复测答卷', interview:'岗位面试', interview_reports:'面试复盘',
  resume:'简历记录', resume_reports:'简历建议版本', input:'首次输入', diagnosis:'岗位诊断',
  plan:'计划版本', plan_review:'历史 F 实验审查', mastery:'能力状态依据',
}

const calendar=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'})
export function recordDay(stamp) {
  const instant=new Date(stamp)
  return Number.isFinite(instant.getTime())?calendar.format(instant):''
}

/** @template {{status:string}} T @param {T[]} items */
export function recentRuns(items) {
  return [...items.filter(row=>row.status==='active'),...items.filter(row=>row.status!=='active').slice(0,3)]
}

export function matchesRecord(record,{kind,subject,date,task},tasks,topics) {
  const p=record.payload??{}
  const event=p.event
  const typeMatches=kind==='all' || (kind==='day'||kind==='week'
    ?record.kind==='assessment'&&(p.kind??p.scope_snapshot?.kind)===kind
    :kind==='answers'?event==='answer_submitted'
    :kind==='interview_reports'?event==='interview_report'
    :kind==='resume_reports'?event==='resume_report'
    :record.kind===kind)
  if(!typeMatches||(date&&recordDay(record.created_at)!==date))return false
  if(task&&(p.progress?.task_id??p.artifact?.task_id)!==task)return false
  if(!subject)return true
  if(Array.isArray(p.topic_keys))return p.topic_keys.includes(subject)
  if(Array.isArray(p.artifact?.topic_keys))return p.artifact.topic_keys.includes(subject)
  const topicId=topics.find(t=>t.topic_key===subject)?.topic_id
  const hasTopicIds=ids=>Boolean(topicId&&Array.isArray(ids)&&ids.includes(topicId))
  return Boolean(tasks.find(t=>t.task_id===p.progress?.task_id)?.topic_keys.includes(subject) ||
    p.scope_snapshot?.tasks?.some(t=>t.topic_keys?.includes(subject)||hasTopicIds(t.topic_ids)) ||
    (topicId&&p.scope_snapshot?.topic_id===topicId) ||
    hasTopicIds(p.turn?.topic_ids) ||
    p.report?.findings?.some(f=>hasTopicIds(f.topic_ids)) ||
    p.after?.some(row=>row.topic_key===subject&&
      (row.evidence_ids?.includes(p.trigger_attempt_id)||row.pending_ids?.includes(p.trigger_attempt_id))))
}

export function resumeEdits(report) {
  const original=report.resume_text
  const candidates=report.items.flatMap(item=>{
    if(item.status!=='suggested'||!item.original_quote||!item.suggested_text||!report.approved_texts.includes(item.suggested_text))return []
    const ref=item.original_ref
    if(ref){
      const points=Array.from(original)
      if(!Number.isInteger(ref.start)||!Number.isInteger(ref.end)||ref.start<0||ref.end<=ref.start||ref.end>points.length||points.slice(ref.start,ref.end).join('')!==item.original_quote)return []
      const start=points.slice(0,ref.start).join('').length
      return [{...item,start,end:start+item.original_quote.length}]
    }
    const start=original.indexOf(item.original_quote)
    if(start<0||original.indexOf(item.original_quote,start+1)>=0)return []
    return [{...item,start,end:start+item.original_quote.length}]
  })
  return candidates.filter((item,index)=>!candidates.some((other,i)=>i!==index&&
    (item.item_id===other.item_id||(item.start<other.end&&other.start<item.end))))
}

export function resumeDraftParts(report,chosen,name) {
  const edits=resumeEdits(report).filter(item=>chosen.includes(item.item_id)).sort((a,b)=>a.start-b.start)
  const original=report.resume_text
  const range=(start,end)=>{
    const parts=[]
    let cursor=start
    for(const edit of edits.filter(item=>item.start>=start&&item.end<=end)){
      parts.push({text:original.slice(cursor,edit.start)},{text:edit.suggested_text,itemId:edit.item_id})
      cursor=edit.end
    }
    parts.push({text:original.slice(cursor,end)})
    return parts
  }
  const intro='计算机相关专业应届生。'
  const sample=resumeEdits(report).find(item=>item.item_id==='original-project'&&item.start===intro.length)
  const namePart=name&&!report.resume_has_header?[{text:name+'\n\n'}]:[]
  if(sample&&original.startsWith(intro)){
    return [...namePart,{text:'教育背景\n'},...range(0,intro.length),
      {text:'\n\n课程实践\n'},...range(sample.start,sample.end),
      ...(sample.end<original.length?[{text:'\n\n其他说明\n'},...range(sample.end,original.length)]:[])]
  }
  return [...namePart,...range(0,original.length)]
}

export function resumeDraft(report,chosen,name) {
  return resumeDraftParts(report,chosen,name).map(part=>part.text).join('')
}
