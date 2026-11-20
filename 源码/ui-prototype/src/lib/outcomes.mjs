/** @typedef {{kind:string,ref_id:string,found:boolean,label:string}} ResolvedRef */
/** Resolve existing references only; this does not generate or approve resume claims.
 * @param {any} snapshot @param {{kind:string,ref_id:string}[]} refs @returns {ResolvedRef[]} */
export function resolveEvidenceRefs(snapshot,refs) {
  return refs.map(ref=>{
    let label="无法找到关联记录",found=false
    if(ref.kind === "gap") {const item=snapshot.gaps.find(value=>value.gap_id === ref.ref_id);found=Boolean(item);if(item)label=item.title}
    if(ref.kind === "task") {const item=snapshot.learning_tasks.find(value=>String(value.task_id) === ref.ref_id);found=Boolean(item);if(item)label=item.title}
    if(ref.kind === "attempt") {const item=snapshot.attempts.find(value=>String(value.attempt_id) === ref.ref_id);found=Boolean(item);if(item)label=`评分记录 #${item.attempt_id} · ${item.score} 分`}
    if(ref.kind === "interview") {const item=snapshot.interview_evidence.find(value=>value.evidence_id === ref.ref_id);found=Boolean(item);if(item)label="岗位场景验证记录"}
    return {kind:ref.kind,ref_id:ref.ref_id,found,label}
  })
}
/** @param {any} snapshot @param {any} suggestion */
export function canCopyDemoSuggestion(snapshot,suggestion) {
  return suggestion?.status === "accepted" && typeof suggestion.suggestion === "string" && suggestion.suggestion.trim().length > 0 && Array.isArray(suggestion.evidence_refs) && suggestion.evidence_refs.length > 0 && resolveEvidenceRefs(snapshot,suggestion.evidence_refs).every(ref=>ref.found)
}
/** @param {any} snapshot @param {string} id */
export function scenarioRecord(snapshot,id) {
  const matches=snapshot.interview_evidence.filter(value=>value.evidence_id === id)
  if(matches.length !== 1)throw new Error("场景记录不存在或有歧义")
  const evidence=matches[0]
  if(!snapshot.gaps.some(value=>value.gap_id === evidence.gap_id))throw new Error("场景来源差距缺失")
  const states=snapshot.mastery_states.filter(value=>value.gap_id === evidence.gap_id && value.state === evidence.mastery_state)
  if(states.length !== 1)throw new Error("场景关联状态缺失或有歧义")
  const state=states[0]
  const attempts=state.attempt_ids.map(id=>{const matches=snapshot.attempts.filter(item=>item.attempt_id === id);if(matches.length !== 1)throw new Error("关联评分缺失或有歧义");return matches[0]})
  return {evidence,state,attempts,eligible:["provisional_pass","mastered"].includes(state.state)}
}
