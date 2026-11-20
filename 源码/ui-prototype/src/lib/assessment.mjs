// Resolve recorded evidence by identity, never by array position or a new pass threshold.
export function assessmentForRound(snapshot, round) {
  if (![0, 1, 2].includes(round)) throw new Error("Unknown demo round")
  const questions = snapshot.questions.filter(item => item.retest_round === round)
  if (questions.length !== 1) throw new Error("Ambiguous or missing demo question")
  const question = questions[0]
  const attempts = snapshot.attempts.filter(item => item.task_id === question.task_id)
  if (attempts.length !== 1) throw new Error("Ambiguous or missing recorded attempt")
  const attempt = attempts[0]
  const states = snapshot.mastery_states.filter(item => item.attempt_ids.at(-1) === attempt.attempt_id && question.gap_ids.includes(item.gap_id))
  if (states.length !== 1) throw new Error("Ambiguous or missing mastery evidence")
  const task = snapshot.learning_tasks.find(item => question.source_task_ids.includes(item.task_id))
  if (!task) throw new Error("Missing source learning task")
  return { question, attempt, state: states[0], task }
}
