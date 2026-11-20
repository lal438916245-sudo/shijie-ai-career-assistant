"""比赛 UI 与 Demo Replay 共用的版本化数据合同。

这里保存的是**展示与证据合同**，不是第二套业务算法。Live 模式把数据库与
Agent 结果投影成此结构；Demo Replay 只读取已保存的同结构快照。页面层不得
重新计算分数、mastery 或来源关系。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelDisclosure(ContractModel):
    generator_type: Literal["model", "rule", "human", "curated_demo"]
    model_name: str | None = None
    note: str


class SnapshotMeta(ContractModel):
    schema_version: Literal[1]
    mode: Literal["live", "demo_replay"]
    scenario_id: str
    generated_at: str
    origin: str
    disclosure: ModelDisclosure


class InputSummary(ContractModel):
    target_role: str
    initial_match_score: float = Field(ge=0, le=100)
    resume_summary: str
    jd_summary: str
    source_id: str
    bundle_id: str


class TraceRefs(ContractModel):
    trace_id: str
    report_id: str
    plan_id: str


class GapRecord(ContractModel):
    gap_id: str
    title: str
    description: str
    priority: Literal["high", "medium", "low"]
    evidence: str


class LearningTaskRecord(ContractModel):
    task_id: int
    day: int
    title: str
    content: str
    gap_ids: list[str]
    provenance_status: str


class QuestionRecord(ContractModel):
    task_id: int
    question: str
    focus: str
    source_task_ids: list[int]
    gap_ids: list[str]
    provenance_status: str
    question_fingerprint: str
    parent_task_id: int | None = None
    retest_round: int = Field(default=0, ge=0, le=2)


class RubricScore(ContractModel):
    dimension: str
    score: float = Field(ge=0, le=100)
    weight: float = Field(gt=0, le=1)


class AttemptRecord(ContractModel):
    attempt_id: int
    task_id: int
    attempt_no: int = Field(ge=1)
    score: float = Field(ge=0, le=100)
    score_source: str
    status: Literal["completed", "failed"]
    feedback: str
    rubric: list[RubricScore]


class MasteryStateRecord(ContractModel):
    gap_id: str
    state: Literal[
        "unassessed",
        "learning",
        "needs_retest",
        "provisional_pass",
        "mastered",
        "review_required",
        "regressed",
    ]
    rule_code: str
    explanation: str
    task_ids: list[int]
    attempt_ids: list[int]


class InterviewEvidence(ContractModel):
    evidence_id: str
    gap_id: str
    mastery_state: Literal["provisional_pass", "mastered"]
    question: str
    result: str
    evidence_note: str


class EvidenceRef(ContractModel):
    kind: Literal["gap", "task", "attempt", "interview"]
    ref_id: str


class ResumeSuggestion(ContractModel):
    suggestion_id: str
    status: Literal["accepted", "blocked"]
    requested_claim: str
    suggestion: str | None = None
    reason: str
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class ToolEvent(ContractModel):
    event_id: str
    category: Literal[
        "input_diagnosis", "learning_support", "validation_action"
    ]
    tool_name: str
    status: Literal["completed", "blocked", "recorded"]
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    label: str


class CompetitionSnapshot(ContractModel):
    meta: SnapshotMeta
    inputs: InputSummary
    trace: TraceRefs
    gaps: list[GapRecord]
    learning_tasks: list[LearningTaskRecord]
    questions: list[QuestionRecord]
    attempts: list[AttemptRecord]
    mastery_states: list[MasteryStateRecord]
    interview_evidence: list[InterviewEvidence] = Field(default_factory=list)
    resume_suggestions: list[ResumeSuggestion] = Field(default_factory=list)
    tool_events: list[ToolEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self):
        gap_ids = {g.gap_id for g in self.gaps}
        learning_ids = {t.task_id for t in self.learning_tasks}
        question_ids = {q.task_id for q in self.questions}
        attempt_ids = {a.attempt_id for a in self.attempts}
        interview_ids = {e.evidence_id for e in self.interview_evidence}

        for task in self.learning_tasks:
            if not set(task.gap_ids) <= gap_ids:
                raise ValueError(f"学习任务 {task.task_id} 引用了未知 gap")
        for question in self.questions:
            if not set(question.gap_ids) <= gap_ids:
                raise ValueError(f"考题 {question.task_id} 引用了未知 gap")
            if not set(question.source_task_ids) <= learning_ids:
                raise ValueError(f"考题 {question.task_id} 引用了未知学习任务")
            if question.parent_task_id is not None:
                if question.parent_task_id not in question_ids:
                    raise ValueError(f"考题 {question.task_id} 的父题不存在")
                if question.parent_task_id == question.task_id:
                    raise ValueError("考题不能把自己设为父题")
        if not {a.task_id for a in self.attempts} <= question_ids:
            raise ValueError("作答记录引用了未知考题")
        for state in self.mastery_states:
            if state.gap_id not in gap_ids:
                raise ValueError("能力状态引用了未知 gap")
            if not set(state.attempt_ids) <= attempt_ids:
                raise ValueError("能力状态引用了未知 attempt")
        valid_refs = {
            "gap": gap_ids,
            "task": {str(i) for i in learning_ids | question_ids},
            "attempt": {str(i) for i in attempt_ids},
            "interview": interview_ids,
        }
        for suggestion in self.resume_suggestions:
            for ref in suggestion.evidence_refs:
                if ref.ref_id not in valid_refs[ref.kind]:
                    raise ValueError(
                        f"简历建议 {suggestion.suggestion_id} 引用了未知证据")
        return self

