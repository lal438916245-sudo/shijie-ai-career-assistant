"""基于正式作答证据投影能力状态的纯规则模块。

本模块不访问数据库、不调用模型，也不持久化状态。相同输入始终得到相同输出，
因此 Live 与 Demo Replay 可以共用同一套规则并保留完整的依据 ID。
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass

from assessment_rules import coerce_score, id_sort_key, is_passing


TRUSTED_SOURCES = frozenset({"rubric_weighted"})


@dataclass(frozen=True)
class MasteryProjection:
    """一次只读投影；tuple 防止调用方无意修改证据集合。"""

    state: str
    rule_code: str
    explanation: str
    task_ids: tuple
    attempt_ids: tuple

    def to_dict(self):
        result = asdict(self)
        result["task_ids"] = list(self.task_ids)
        result["attempt_ids"] = list(self.attempt_ids)
        return result


def _value(record, name, default=None):
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def _unique(values):
    result = []
    for value in values:
        if value is not None and value not in result:
            result.append(value)
    return result


def _question_metadata(questions, gap_id):
    metadata = {}
    for question in questions or []:
        task_id = _value(question, "task_id")
        if task_id is None:
            continue
        gap_ids = _as_list(_value(question, "gap_ids"))
        if gap_id is not None and gap_id not in gap_ids:
            continue
        fingerprint = _value(question, "question_fingerprint")
        metadata[task_id] = {
            "fingerprint": str(fingerprint) if fingerprint else None,
            "round": _value(question, "retest_round", 0),
        }
    return metadata


def _in_scope(attempt, question_meta, gap_id, questions_supplied):
    task_id = _value(attempt, "task_id")
    if gap_id is None:
        return True
    if task_id in question_meta:
        return True
    if questions_supplied:
        return False
    return gap_id in _as_list(_value(attempt, "gap_ids"))


def _number(value, default=0):
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return value
    return default


def _chronology_key(attempt, question_meta):
    task_id = _value(attempt, "task_id")
    return (
        id_sort_key(_value(attempt, "attempt_id")),
        _number(_value(attempt, "attempt_no"), 0),
        id_sort_key(task_id),
    )


def _question_identity(attempt, question_meta):
    task_id = _value(attempt, "task_id")
    fingerprint = (_value(attempt, "question_fingerprint")
                   or question_meta.get(task_id, {}).get("fingerprint"))
    if fingerprint:
        return ("fingerprint", fingerprint)
    return ("task", type(task_id).__name__, str(task_id))


def _score(attempt):
    value = _value(attempt, "score")
    if value is None:
        value = _value(attempt, "final_score")
    return coerce_score(value)


def _projection(state, rule_code, explanation, attempts=(), task_ids=()):
    evidence_tasks = _unique(
        list(task_ids) + [_value(item, "task_id") for item in attempts]
    )
    evidence_attempts = _unique(
        [_value(item, "attempt_id") for item in attempts]
    )
    return MasteryProjection(
        state=state,
        rule_code=rule_code,
        explanation=explanation,
        task_ids=tuple(evidence_tasks),
        attempt_ids=tuple(evidence_attempts),
    )


def project(attempts=(), *, questions=(), gap_id=None, learning_task_ids=()):
    """把一个能力 gap 的证据投影成当前状态。

    ``questions`` 提供题面指纹与复测轮次；相同指纹即使使用不同 task_id，
    也只算一道独立题面。传入 ``gap_id`` 时，只消费明确引用该 gap 的题目。
    ``model_fallback`` 和未知来源永远不能推动或降低正式状态。
    """
    attempts = list(attempts or [])
    questions = list(questions or [])
    learning_task_ids = list(learning_task_ids or [])
    question_meta = _question_metadata(questions, gap_id)
    scoped = [
        item for item in attempts
        if _in_scope(item, question_meta, gap_id, bool(questions))
    ]
    scoped.sort(key=lambda item: _chronology_key(item, question_meta))

    trusted = []
    review_evidence = []
    for item in scoped:
        score = _score(item)
        source = _value(item, "score_source")
        has_identity = (
            _value(item, "task_id") is not None
            and _value(item, "attempt_id") is not None
        )
        if source in TRUSTED_SOURCES and score is not None and has_identity:
            trusted.append(item)
        elif source not in TRUSTED_SOURCES or score is None or not has_identity:
            review_evidence.append(item)

    question_task_ids = sorted(
        question_meta,
        key=lambda task_id: (
            _number(question_meta[task_id].get("round"), 0),
            id_sort_key(task_id),
        ),
    )
    known_task_ids = _unique(
        sorted(learning_task_ids, key=id_sort_key) + question_task_ids
    )

    if not trusted:
        if review_evidence:
            return _projection(
                "review_required",
                "NO_USABLE_TRUSTED_EVIDENCE",
                "已有评测记录，但缺少可定位的正式 rubric 证据，需要人工复核。",
                review_evidence,
                known_task_ids,
            )
        if known_task_ids:
            return _projection(
                "learning",
                "LEARNING_WITHOUT_TRUSTED_ATTEMPT",
                "已有学习或考题记录，但尚无可用于判定的正式 rubric 作答。",
                task_ids=known_task_ids,
            )
        return _projection(
            "unassessed",
            "NO_LEARNING_OR_ASSESSMENT_EVIDENCE",
            "尚无学习任务或正式评测证据。",
        )

    distinct_passes_since_failure = set()
    passed_task_ids = set()
    mastered_before_latest = False
    latest = trusted[-1]

    for item in trusted:
        if is_passing(_score(item)):
            task_id = _value(item, "task_id")
            if task_id not in passed_task_ids:
                distinct_passes_since_failure.add(
                    _question_identity(item, question_meta)
                )
            passed_task_ids.add(task_id)
            if len(distinct_passes_since_failure) >= 2:
                mastered_before_latest = True
        else:
            distinct_passes_since_failure.clear()
            passed_task_ids.clear()

    latest_score = _score(latest)
    if not is_passing(latest_score):
        if mastered_before_latest:
            return _projection(
                "regressed",
                "TRUSTED_FAILURE_AFTER_MASTERY",
                f"已掌握后出现新的正式 rubric 失败（{latest_score:g} 分），能力状态回退。",
                trusted,
                known_task_ids,
            )
        return _projection(
            "needs_retest",
            "LATEST_TRUSTED_BELOW_PASS",
            f"最新正式 rubric 得分 {latest_score:g}，低于统一及格线。",
            trusted,
            known_task_ids,
        )

    if len(distinct_passes_since_failure) >= 2:
        return _projection(
            "mastered",
            "TWO_DISTINCT_TRUSTED_PASSES",
            "最近一次正式失败后，已通过两道不同题面的正式 rubric 评测。",
            trusted,
            known_task_ids,
        )

    return _projection(
        "provisional_pass",
        "ONE_DISTINCT_TRUSTED_PASS",
        "当前只有一道独立题面的正式 rubric 通过证据，暂时通过并等待变式复测。",
        trusted,
        known_task_ids,
    )

