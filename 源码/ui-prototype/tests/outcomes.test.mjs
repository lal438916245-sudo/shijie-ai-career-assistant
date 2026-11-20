import test from "node:test"
import assert from "node:assert/strict"
import {readFileSync} from "node:fs"
import {resolveEvidenceRefs,canCopyDemoSuggestion,scenarioRecord} from "../src/lib/outcomes.mjs"
import {viewFromHash,VIEW_TITLES} from "../src/lib/routes.mjs"
const replay=JSON.parse(readFileSync(new URL("../src/data/replay.json",import.meta.url),"utf8"))
test("简历建议的五条引用能追到原始证据；拦截项没有可复制声明",()=>{
 const accepted=replay.resume_suggestions.find(item=>item.status==="accepted")
 const blocked=replay.resume_suggestions.find(item=>item.status==="blocked")
 const refs=resolveEvidenceRefs(replay,accepted.evidence_refs)
 assert.equal(refs.length,5);assert.ok(refs.every(ref=>ref.found));assert.equal(canCopyDemoSuggestion(replay,accepted),true)
 assert.equal(canCopyDemoSuggestion(replay,blocked),false);assert.equal(blocked.suggestion,null)
})
test("缺失与未知引用禁止复制演示建议，不能凭标题猜配证据",()=>{
 const accepted=replay.resume_suggestions.find(item=>item.status==="accepted")
 const missing=structuredClone(replay);missing.attempts=missing.attempts.filter(item=>item.attempt_id!==3002)
 assert.equal(canCopyDemoSuggestion(missing,accepted),false)
 assert.equal(canCopyDemoSuggestion(replay,{...accepted,evidence_refs:[]}),false)
 assert.equal(canCopyDemoSuggestion(replay,{...accepted,evidence_refs:[{kind:"unknown",ref_id:"1001"}]}),false)
 assert.equal(canCopyDemoSuggestion(replay,{...accepted,suggestion:""}),false)
})
test("场景记录关联原差距与掌握状态，拒绝缺失或歧义记录",()=>{
 const data=scenarioRecord(replay,"INTERVIEW_DEMO_01")
 assert.equal(data.eligible,true);assert.equal(data.state.state,"mastered");assert.deepEqual(data.attempts.map(item=>item.attempt_id),[3001,3002,3003])
 assert.equal("score" in data.evidence,false)
 for(const mutate of [value=>value.interview_evidence=[],value=>value.interview_evidence.push({...value.interview_evidence[0]}),value=>value.gaps=[],value=>value.mastery_states=value.mastery_states.filter(item=>item.state!=="mastered"),value=>value.attempts.pop()]){
  const broken=structuredClone(replay);mutate(broken);assert.throws(()=>scenarioRecord(broken,"INTERVIEW_DEMO_01"))
 }
})
test("三页直达路由与标题可用，不影响旧入口",()=>{
 for(const view of ["growth","scenario","resume","plan","retest"]){assert.equal(viewFromHash(`#${view}`),view);assert.equal(viewFromHash(`#/${view}`),view);assert.ok(VIEW_TITLES[view])}
 assert.equal(viewFromHash("#unknown"),"welcome")
})
