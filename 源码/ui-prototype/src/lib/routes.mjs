/** @typedef {"welcome" | "overview" | "new" | "diagnosis" | "plan" | "exam" | "retest" | "growth" | "scenario" | "resume" | "records"} View */

export const VIEW_TITLES = { welcome: "让每一步成长，都有据可循", overview: "成长概览", new: "新建成长计划", diagnosis: "岗位诊断", plan: "学习计划", exam: "学习考核", retest: "变式复测", growth: "成长状态", scenario: "模拟面试", resume: "简历修改", records: "成长记录" }

/** @returns {View} */
export function viewFromHash(hash) {
  const value = typeof hash === "string" ? hash.replace(/^#\/?/, "").split("?")[0] : ""
  return value === "overview" || value === "new" || value === "diagnosis" || value === "plan" || value === "exam" || value === "retest" || value === "growth" || value === "scenario" || value === "resume" || value === "records" ? value : "welcome"
}

/** @param {string} hash */
export function retestRoundFromHash(hash) { return new URLSearchParams((hash.split("?")[1]??"")).get("round")==="2"?2:1 }
/** @param {View} view @param {number} [round] */
export function hashForView(view,round=1) { return view==="retest"&&round===2?"#retest?round=2":`#${view}` }
/** @param {string} hash */
export function unknownHash(hash) { const path=hash.replace(/^#\/?/,"").split("?")[0];return Boolean(path)&&!Object.hasOwn(VIEW_TITLES,path) }
/** @type {{view:View,label:string}[]} */
export const FLOW_STEPS=[{view:"diagnosis",label:"岗位诊断"},{view:"plan",label:"学习计划"},{view:"exam",label:"学习考核"},{view:"retest",label:"变式复测"},{view:"growth",label:"成长状态"},{view:"scenario",label:"模拟面试"},{view:"resume",label:"简历修改"}]
