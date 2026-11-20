/** @typedef {"not_started" | "in_progress" | "completed"} StudyStatus */
/** @typedef {{id:string,start:string,end:string,minutes:number,status:StudyStatus,note:string}} ScheduleEntry */
/** @typedef {{at:string,entryId:string,label:string,reason:string}} ScheduleEvent */
/** @typedef {{version:1,caseId:string,anchor:string,entries:ScheduleEntry[],history:ScheduleEvent[]}} Schedule */
export const SCHEDULE_KEY = "career-pilot:ui-prototype:study-schedule:v1:data-engineer-growth-v1"
export const CASE_ID = "PLAN_DEMO_STREAM_01"
export const STATUS_LABELS = { not_started: "未开始", in_progress: "学习中", completed: "已完成" }
// Authored scheduling examples, separate from the immutable canonical replay evidence.
export const SCHEDULE_ITEMS = [
  { id:"study-window",day:1,kind:"study",title:"理解事件时间与窗口",minutes:30,sourceTaskId:1001,topics:["事件时间","窗口"],goal:"画出事件时间与处理时间的区别，说明 5 分钟窗口如何归组。",check:"一条订单晚到了两分钟，它一定属于当前窗口吗？试着解释依据。",output:"一张时间线草图与一段说明" },
  { id:"study-watermark",day:2,kind:"study",title:"处理乱序与迟到数据",minutes:40,sourceTaskId:1001,topics:["Watermark","迟到数据"],goal:"梳理 Watermark、乱序边界与迟到数据处理之间的关系。",check:"窗口已经关闭时又收到旧订单，你会保留、补偿还是丢弃？为什么？",output:"一份迟到数据处理思路" },
  { id:"study-state",day:3,kind:"study",title:"连接状态与故障恢复",minutes:45,sourceTaskId:1001,topics:["状态后端","Checkpoint"],goal:"解释 Checkpoint 保存了什么，以及失败后如何从恢复点继续。",check:"状态恢复成功，就一定能保证下游不重复吗？说明还需要检查什么。",output:"一张状态恢复步骤清单" },
  { id:"study-practice",day:4,kind:"study",title:"串起订单流处理方案",minutes:60,sourceTaskId:1001,topics:["窗口","Watermark","容错"],goal:"将窗口、迟到数据和状态恢复连成一个订单聚合方案，可配合自己的小实验。",check:"尝试模拟一次节点失败，并记录你的预期现象与观察结果。",output:"一份方案或实验记录；此页不运行代码" },
  { id:"study-recall",day:5,kind:"study",title:"不看笔记，再解释一次",minutes:20,sourceTaskId:1001,topics:["主动回忆","综合解释"],goal:"用自己的话解释四个核心概念，标记仍需要查资料的部分。",check:"能否向一位同伴解释：Watermark 和 Checkpoint 分别解决什么问题？",output:"一段自己的解释与疑问列表" },
  { id:"study-repair",day:6,kind:"study",title:"给薄弱处留出补学时间",minutes:30,sourceTaskId:1001,topics:["薄弱点补学","灵活调整"],goal:"回看本周记录，挑一个最不确定的环节补学；内容较难时可延长此任务。",check:"哪一处目前只能说出术语，还不能解释场景与边界？",output:"一份补学记录与下一步问题" },
  { id:"weekly-check",day:7,kind:"weekly",title:"每周检查与复测安排",minutes:45,sourceTaskId:1001,topics:["综合检查","变式复测"],goal:"检查本周主题的关联理解，从考核反馈中选择需要补学和变式复测的部分。",check:"区分：已经完成哪些学习任务，哪些能力仍缺少验证证据？",output:"一份周复盘；现有考核入口只回放原专题样例" },
]

export function localToday() { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")}` }
/** @param {unknown} value */
export function validDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year,month,day] = value.split("-").map(Number)
  const date = new Date(Date.UTC(year,month-1,day))
  return year >= 2000 && year <= 2100 && date.getUTCFullYear() === year && date.getUTCMonth() === month-1 && date.getUTCDate() === day
}
/** @param {string} date @param {number} days */
export function addDays(date, days) {
  if (!validDate(date) || !Number.isInteger(days)) throw new Error("日期无效")
  const value = new Date(`${date}T00:00:00Z`); value.setUTCDate(value.getUTCDate()+days)
  const result = value.toISOString().slice(0,10)
  if (!validDate(result)) throw new Error("日期需在 2000–2100 年之间")
  return result
}
/** @param {string} from @param {string} to */
export function daysBetween(from,to) {
  if (!validDate(from) || !validDate(to)) throw new Error("日期无效")
  return Math.round((Date.parse(`${to}T00:00:00Z`)-Date.parse(`${from}T00:00:00Z`))/86400000)
}
/** @param {string} [anchor] @returns {Schedule} */
export function createSchedule(anchor=localToday()) {
  if (!validDate(anchor)) throw new Error("请选择有效的开始日期")
  return { version:1,caseId:CASE_ID,anchor,entries:SCHEDULE_ITEMS.map(item=>({id:item.id,start:addDays(anchor,item.day-1),end:addDays(anchor,item.day-1),minutes:item.minutes,status:"not_started",note:""})),history:[] }
}
/** @param {unknown} value @returns {value is StudyStatus} */
function isStatus(value) { return value === "not_started" || value === "in_progress" || value === "completed" }
/** @param {unknown} value */
function validEntry(value) {
  if (!value || typeof value !== "object") return false
  const item = /** @type {ScheduleEntry} */ (value)
  return validDate(item.start) && validDate(item.end) && item.end >= item.start && daysBetween(item.start,item.end) <= 60 && Number.isInteger(item.minutes) && item.minutes >= 5 && item.minutes <= 480 && isStatus(item.status) && typeof item.note === "string" && item.note.length <= 1000
}
/** @param {string|null} raw @returns {Schedule|null} */
export function parseSchedule(raw) {
  try {
    const value = JSON.parse(raw ?? "null")
    if (value?.version !== 1 || value.caseId !== CASE_ID || !validDate(value.anchor) || !Array.isArray(value.entries) || value.entries.length !== SCHEDULE_ITEMS.length || !Array.isArray(value.history) || value.history.length > 40) return null
    const entries = SCHEDULE_ITEMS.map(item => {
      const matches = value.entries.filter(candidate=>candidate?.id === item.id)
      if (matches.length !== 1 || !validEntry(matches[0])) throw new Error("Invalid entry")
      const {id,start,end,minutes,status,note} = matches[0]; return {id,start,end,minutes,status,note}
    })
    const history = value.history.map(event => {
      if (!event || !SCHEDULE_ITEMS.some(item=>item.id === event.entryId) || typeof event.at !== "string" || !Number.isFinite(Date.parse(event.at)) || typeof event.label !== "string" || event.label.length > 200 || typeof event.reason !== "string" || event.reason.length > 600) throw new Error("Invalid history")
      const {at,entryId,label,reason} = event; return {at,entryId,label,reason}
    })
    return {version:1,caseId:CASE_ID,anchor:value.anchor,entries,history}
  } catch { return null }
}
/** @param {Schedule} value @param {string} entryId @param {string} label @param {string} reason */
function log(value,entryId,label,reason) { return [...value.history,{at:new Date().toISOString(),entryId,label,reason}].slice(-40) }
/** @param {Schedule} value @param {string} id @param {StudyStatus} status @returns {Schedule} */
export function setStudyStatus(value,id,status) {
  if (!isStatus(status) || !value.entries.some(item=>item.id === id)) throw new Error("无效任务或状态")
  if (value.entries.find(item=>item.id === id)?.status === status) return value
  return {...value,entries:value.entries.map(item=>item.id === id ? {...item,status} : item),history:log(value,id,`状态改为${STATUS_LABELS[status]}`,"手动更新学习进度；不改变能力验证状态")}
}
/** @param {Schedule} value @param {string} id @param {string} note @returns {Schedule} */
export function saveStudyNote(value,id,note) {
  if (typeof note !== "string" || note.length > 1000 || !value.entries.some(item=>item.id === id)) throw new Error("学习记录最多 1000 字")
  return {...value,entries:value.entries.map(item=>item.id === id ? {...item,note} : item)}
}
/** @param {Schedule} value @param {string} id @param {{start:string,end:string,minutes:number,reason:string,shiftFollowing:boolean}} patch @returns {Schedule} */
export function adjustSchedule(value,id,patch) {
  const index = value.entries.findIndex(item=>item.id === id)
  if (index < 0 || typeof patch.reason !== "string" || !patch.reason.trim() || patch.reason.length > 600 || typeof patch.shiftFollowing !== "boolean") throw new Error("请填写有效的调整原因")
  const old = value.entries[index]; const next = {...old,start:patch.start,end:patch.end,minutes:patch.minutes}
  if (!validEntry(next)) throw new Error("请检查日期、起止顺序及预计投入（5–480 分钟）；单项最多安排 61 个自然日")
  const delta = daysBetween(old.end,next.end)
  const entries = value.entries.map((item,i) => i === index ? next : patch.shiftFollowing && delta !== 0 && i > index && item.status !== "completed" ? {...item,start:addDays(item.start,delta),end:addDays(item.end,delta)} : item)
  return {...value,entries,history:log(value,id,`${old.start}～${old.end} → ${next.start}～${next.end} · ${next.minutes} 分钟${patch.shiftFollowing && delta !== 0 ? "；后续未完成任务同步移动" : ""}`,patch.reason.trim())}
}
/** @param {Schedule} value @param {string} anchor @returns {Schedule} */
export function moveScheduleStart(value,anchor) {
  if (!validDate(anchor)) throw new Error("请选择有效的计划起点")
  const delta = daysBetween(value.anchor,anchor)
  return {...value,anchor,entries:value.entries.map(item=>item.status === "completed" ? item : {...item,start:addDays(item.start,delta),end:addDays(item.end,delta)}),history:log(value,SCHEDULE_ITEMS[0].id,`计划起点 ${value.anchor} → ${anchor}`,"只移动尚未完成的安排，保留已完成任务日期")}
}
/** @param {Schedule} value */
export function studyProgress(value) {
  const ids = SCHEDULE_ITEMS.filter(item=>item.kind === "study").map(item=>item.id)
  const entries = value.entries.filter(item=>ids.includes(item.id))
  const completed = entries.filter(item=>item.status === "completed").length
  return {total:entries.length,completed,active:entries.filter(item=>item.status === "in_progress").length,percent:Math.round(completed/entries.length*100)}
}
