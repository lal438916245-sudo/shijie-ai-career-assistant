/** Fixed templates grouped by the current saved schedule, without creating questions. */
export function dailyTemplates(catalog,date){
 if(!catalog||!date)return []
 const matching=new Set(catalog.schedule.filter(s=>s.start_date<=date&&date<=s.end_date).map(s=>s.task_id))
 return catalog.assessments.filter(a=>a.kind==="day"&&a.scope_snapshot.items.some(item=>matching.has(item.task_id)))
}
export function preferredDay(catalog,taskId){return catalog?.schedule.find(s=>s.task_id===taskId)?.start_date??null}
export function recordType(type){if(type==="learning"||type==="learning_update")return "learning";if(type==="day"||type==="day_assessment")return "day";if(type==="week"||type==="week_assessment")return "week";return type}
export function recordDate(row){
 try{const parts=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date(row.created_at??row.occurred_at));const get=key=>parts.find(p=>p.type===key)?.value;return `${get("year")}-${get("month")}-${get("day")}`}catch{return ""}
}
export function filterRecords(rows,type,start,end){return rows.filter(r=>{const date=recordDate(r);return (type==="all"||recordType(r.type)===type)&&(!start||date>=start)&&(!end||date<=end)})}
