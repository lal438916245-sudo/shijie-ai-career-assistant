import {readFileSync} from "node:fs"
import test from "node:test"
import assert from "node:assert/strict"
import {SCHEDULE_ITEMS,createSchedule,parseSchedule,setStudyStatus,saveStudyNote,adjustSchedule,moveScheduleStart,studyProgress,addDays,validDate} from "../src/lib/schedule.mjs"

test("学习状态可往返调整，周检查不计入六项学习进度，也不产生能力成绩",()=>{
  const original=createSchedule("2026-10-27")
  let next=setStudyStatus(original,"study-window","in_progress")
  assert.equal(studyProgress(next).active,1)
  next=setStudyStatus(next,"study-window","completed")
  next=setStudyStatus(next,"weekly-check","completed")
  assert.deepEqual(studyProgress(next),{total:6,completed:1,active:0,percent:17})
  next=setStudyStatus(next,"study-window","not_started")
  assert.equal(studyProgress(next).completed,0)
  assert.equal(original.entries[0].status,"not_started")
  for(const key of ["score","mastery_state","attempt_id"]) assert.equal(key in next,false)
})
test("改期默认只动当前任务，顺延时跳过已完成安排并保留稳定身份",()=>{
  let original=setStudyStatus(createSchedule("2026-10-27"),"study-state","completed")
  const patch={start:"2026-10-28",end:"2026-10-30",minutes:90,reason:"内容较难",shiftFollowing:false}
  const single=adjustSchedule(original,"study-watermark",patch)
  assert.equal(single.entries[1].end,"2026-10-30")
  assert.equal(single.entries[3].start,original.entries[3].start)
  const shifted=adjustSchedule(original,"study-watermark",{...patch,shiftFollowing:true})
  assert.deepEqual(shifted.entries[2],original.entries[2])
  assert.equal(shifted.entries[3].start,addDays(original.entries[3].start,2))
  assert.equal(shifted.entries[6].start,addDays(original.entries[6].start,2))
  assert.deepEqual(shifted.entries.map(item=>item.id),SCHEDULE_ITEMS.map(item=>item.id))
  assert.equal(shifted.history.at(-1).reason,"内容较难")
  assert.equal(original.entries[1].end,"2026-10-28")
})
test("计划起点变化保留已完成日期；跨月、闰年与非法日期受校验",()=>{
  const original=setStudyStatus(createSchedule("2026-10-27"),"study-window","completed")
  const next=moveScheduleStart(original,"2026-11-01")
  assert.equal(next.entries[0].start,"2026-10-27")
  assert.equal(next.entries[1].start,"2026-11-02")
  assert.equal(addDays("2028-02-28",1),"2028-02-29")
  assert.equal(addDays("2026-10-31",1),"2026-11-01")
  for(const value of ["2026-02-29","2026-02-31","2026-13-01","not-date"]) assert.equal(validDate(value),false)
})
test("损坏、本案例以外或重复身份的本地记录被拒绝，额外字段不进入恢复结果",()=>{
  const original=saveStudyNote(createSchedule("2026-10-27"),"study-window","我的自查记录")
  const raw=JSON.parse(JSON.stringify(original));raw.secret="ignore";raw.entries[0].score=100
  assert.deepEqual(parseSchedule(JSON.stringify(raw)),original)
  for(const mutate of [value=>value.caseId="other",value=>value.entries[1].id=value.entries[0].id,value=>value.entries[0].status="mastered",value=>value.entries[0].start="2026-02-31",value=>value.history=[{at:"bad"}]]){
    const broken=structuredClone(original);mutate(broken);assert.equal(parseSchedule(JSON.stringify(broken)),null)
  }
  assert.equal(parseSchedule("{broken"),null)
})
test("无效调整不修改旧安排，笔记和历史长度有界",()=>{
  const original=createSchedule("2026-10-27")
  const base={start:"2026-10-28",end:"2026-10-28",minutes:40,reason:"时间冲突",shiftFollowing:false}
  for(const patch of [{minutes:NaN},{minutes:0},{minutes:481},{end:"2026-10-26"},{start:"2026-02-31"},{reason:""},{end:"2027-10-28"}]) assert.throws(()=>adjustSchedule(original,"study-window",{...base,...patch}))
  assert.throws(()=>saveStudyNote(original,"study-window","x".repeat(1001)))
  let next=original
  for(let i=0;i<45;i++)next=setStudyStatus(next,"study-window",i%2?"completed":"in_progress")
  assert.equal(next.history.length,40)
  assert.deepEqual(parseSchedule(JSON.stringify(next)),next)
  assert.equal(original.history.length,0)
})

test("手工日程只引用真实专题，六个学习日与一个周检查不扩写规范证据",()=>{
  const replay=JSON.parse(readFileSync(new URL("../src/data/replay.json",import.meta.url),"utf8"))
  assert.equal(SCHEDULE_ITEMS.filter(item=>item.kind === "study").length,6)
  assert.equal(SCHEDULE_ITEMS.filter(item=>item.kind === "weekly").length,1)
  assert.equal(new Set(SCHEDULE_ITEMS.map(item=>item.id)).size,7)
  for(const item of SCHEDULE_ITEMS)assert.ok(replay.learning_tasks.some(task=>task.task_id === item.sourceTaskId))
  assert.equal(replay.learning_tasks.length,1)
  assert.equal(replay.questions.length,3)
})
