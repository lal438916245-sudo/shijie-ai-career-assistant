export const DRAFT_KEY = "career-pilot:ui-prototype:draft:v1"
export const SESSION_KEY = "career-pilot:ui-prototype:session:v1"

export function emptyDraft() { return { role: "", resume: "", jd: "", days: 14 } }

export const SAMPLE_INPUT = {
  role: "数据开发工程师",
  resume: "计算机相关专业，熟悉 Python、SQL 与离线数据仓库。完成过订单数据清洗、批处理与报表开发练习。希望补齐流式计算、状态管理和故障恢复能力。以上为脱敏演示资料。",
  jd: "负责实时数据链路开发与维护，掌握事件时间窗口、Watermark、状态管理与 Checkpoint。能够分析乱序数据、故障恢复和端到端一致性问题，具备清晰的工程取舍能力。以上为演示岗位要求。",
  days: 14,
}

/** @returns {Record<string, string>} */
export function validateDraft(draft) {
  const errors = {}
  if (!draft || typeof draft !== "object") return { role: "请填写目标岗位" }
  if (typeof draft.role !== "string" || !draft.role.trim()) errors.role = "给这段成长一个明确的岗位方向"
  else if (draft.role.length > 120) errors.role = "岗位名称请控制在 120 字以内"
  if (typeof draft.resume !== "string" || draft.resume.trim().length < 20) errors.resume = "请填写至少 20 字的经历或技能描述"
  else if (draft.resume.length > 60000) errors.resume = "简历文本请控制在 60,000 字以内"
  if (typeof draft.jd !== "string" || draft.jd.trim().length < 20) errors.jd = "请填写至少 20 字的岗位要求"
  else if (draft.jd.length > 30000) errors.jd = "岗位要求请控制在 30,000 字以内"
  if (!Number.isInteger(draft.days) || draft.days < 4 || draft.days > 30) errors.days = "请选择 4–30 天的学习时间"
  return errors
}

export function parseDraft(raw) {
  try {
    const value = JSON.parse(raw)
    if (!value || typeof value !== "object" || Array.isArray(value)) return null
    if (typeof value.role !== "string" || value.role.length > 120
      || typeof value.resume !== "string" || value.resume.length > 60000
      || typeof value.jd !== "string" || value.jd.length > 30000
      || !Number.isInteger(value.days) || value.days < 4 || value.days > 30) return null
    return { role: value.role, resume: value.resume, jd: value.jd, days: value.days }
  } catch { return null }
}

export function makePreviewSession(draft, id) {
  if (Object.keys(validateDraft(draft)).length) throw new Error("请先补齐必要资料")
  return {
    kind: "browser-prototype",
    id: `prototype:${id}`,
    role: draft.role.trim(), resume: draft.resume.trim(), jd: draft.jd.trim(), days: draft.days,
    status: "input_saved",
  }
}
