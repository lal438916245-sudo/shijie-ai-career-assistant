// Byte-identical local copy of examples/demo_replay/scenario_01/bundle.json.
// Display labels are UI metadata; all scores, IDs, statements and states come from the snapshot.
import replay from "./replay.json"
export { replay }

const stateLabels: Record<string, string> = { needs_retest: "待复测", provisional_pass: "暂时通过", mastered: "已掌握" }
const gap = replay.gaps[0]
const task = replay.learning_tasks[0]
export const demo = {
  role: replay.inputs.target_role.split("（")[0],
  direction: replay.inputs.target_role.match(/（(.+)）/)?.[1] ?? "",
  initialMatch: replay.inputs.initial_match_score,
  passedFaces: new Set(replay.attempts.filter(attempt => attempt.status === "completed")
    .map(attempt => replay.questions.find(question => question.task_id === attempt.task_id)!.question_fingerprint)).size,
  gap: { id: gap.gap_id, title: gap.title, detail: gap.description },
  task: { id: task.task_id, day: task.day, title: task.title, detail: task.content },
  attempts: replay.attempts.map(attempt => {
    const question = replay.questions.find(item => item.task_id === attempt.task_id)!
    const state = replay.mastery_states.find(item => item.attempt_ids.at(-1) === attempt.attempt_id)!
    return { id: attempt.attempt_id, questionId: question.task_id,
      label: question.retest_round === 0 ? "首次考核" : `变式复测 ${String(question.retest_round).padStart(2, "0")}`,
      score: attempt.score, state: stateLabels[state.state] ?? state.state,
      rule: state.rule_code, focus: question.focus, feedback: attempt.feedback }
  }),
  accepted: replay.resume_suggestions.find(item => item.status === "accepted")!.suggestion ?? "",
  blocked: replay.resume_suggestions.find(item => item.status === "blocked")!.requested_claim,
}
