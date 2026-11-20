"""从现有数据库读取能力证据；只读，不迁移、不创建客户端。"""

import hashlib
import json
import unicodedata

from assessment_profile import load_plan_attempts
from assessment_rules import coerce_score
from mastery_policy import project
from competition_contracts import MasteryStateRecord


def fingerprint(text):
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    normalized = "".join(char for char in normalized if char.isalnum())
    if not normalized:
        raise ValueError("题面不能为空")
    return "question:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def json_list(value):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        raise ValueError("来源必须为明确记录的列表")
    return value


def rows(conn, sql, params=()):
    cursor = conn.execute(sql, params)
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


class EvidenceReader:
    """给复测预览使用的最小只读数据库接口。"""
    EXAM_TASK_TYPE = "考察"

    def __init__(self, conn):
        self.conn = conn

    def get_task_by_id(self, task_id):
        found = rows(self.conn, "SELECT * FROM study_tasks WHERE id=?", (task_id,))
        return found[0] if found else None

    def get_latest_assessment_attempt(self, task_id):
        found = rows(self.conn, "SELECT id FROM assessment_attempts WHERE task_id=? "
                     "ORDER BY attempt_no DESC,id DESC LIMIT 1", (task_id,))
        return found[0] if found else None


def trusted_rubric(attempt):
    """只有能由保存的历史 rubric 复算的分数才用于比赛能力判定。"""
    if attempt.get("score_source") != "rubric_weighted":
        return False
    if any((attempt.get("broken") or {}).values()):
        return False
    rubric = attempt.get("rubric")
    definition = attempt.get("rubric_definition")
    if not isinstance(rubric, list) or not isinstance(definition, list):
        return False
    weights = {}
    for item in definition:
        if not isinstance(item, dict):
            return False
        key, weight = item.get("key"), item.get("weight")
        if not isinstance(key, str) or key in weights:
            return False
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            return False
        if not 0 < weight <= 100:
            return False
        weights[key] = weight
    total = 0
    weight_sum = 0
    seen = set()
    for item in rubric:
        if not isinstance(item, dict):
            return False
        key = item.get("dimension")
        score = coerce_score(item.get("score"))
        if key not in weights or key in seen or score is None:
            return False
        seen.add(key)
        total += score * weights[key]
        weight_sum += weights[key]
    return bool(coerce_score(attempt.get("final_score")) is not None
                and weight_sum and weight_sum == attempt.get("rubric_weight")
                and round(total / weight_sum) == attempt.get("final_score"))


def load_evidence(conn, plan_id, trace_id):
    if not plan_id or not trace_id:
        raise ValueError("必须明确指定 plan_id 和 trace_id")
    tasks = rows(conn, "SELECT * FROM study_tasks WHERE plan_id=? ORDER BY id",
                 (plan_id,))
    loaded = load_plan_attempts(conn, plan_id)
    attempts = [a for a in loaded["attempts"] if a["trace_id"] == trace_id]
    feedbacks = {r["id"]: r["feedback"] for r in rows(
        conn, "SELECT a.id,a.feedback FROM assessment_attempts a "
        "JOIN study_tasks t ON t.id=a.task_id WHERE t.plan_id=? AND a.trace_id=?",
        (plan_id, trace_id))} if loaded["table_available"] else {}
    questions = []
    learning = []
    links = {}
    if table_exists(conn, "variant_retests"):
        links = {r["child_task_id"]: r for r in rows(
            conn, "SELECT * FROM variant_retests WHERE plan_id=? AND trace_id=? "
            "AND status='ready'", (plan_id, trace_id))}
    for task in tasks:
        try:
            gaps = json_list(task["gap_ids"])
        except (ValueError, TypeError):
            gaps = []
        if str(task["task_type"] or "").startswith("考察"):
            link = links.get(task["id"], {})
            questions.append({
                "task_id": task["id"], "question": task["content"],
                "question_fingerprint": fingerprint(task["content"]),
                "gap_ids": gaps, "parent_task_id": link.get("parent_task_id"),
                "retest_round": link.get("round", 0),
            })
        else:
            learning.append({"task_id": task["id"], "gap_ids": gaps})
    question_ids = {q["task_id"] for q in questions}
    for attempt in attempts:
        attempt["feedback"] = feedbacks.get(attempt["attempt_id"], "")
        if not trusted_rubric(attempt):
            attempt["score_source"] = "unverified_evidence"
        try:
            attempt["question_fingerprint"] = fingerprint(attempt["question_text"])
        except ValueError:
            attempt["score_source"] = "unverified_evidence"
        # 旧的逐日入口也能直接在学习任务上保存考核，保留其 attempt 来源快照。
        if attempt["task_id"] not in question_ids:
            questions.append({"task_id": attempt["task_id"],
                              "gap_ids": attempt["gap_ids"] or []})
            question_ids.add(attempt["task_id"])
    return {"tasks": tasks, "questions": questions, "attempts": attempts,
            "learning_tasks": learning, "table_available": loaded["table_available"]}


def project_plan(conn, plan_id, trace_id):
    """逐 gap 返回与页面合同兼容的当前状态，状态不写回数据库。"""
    evidence = load_evidence(conn, plan_id, trace_id)
    gap_ids = sorted({g for t in evidence["questions"] + evidence["learning_tasks"]
                      for g in t["gap_ids"] if isinstance(g, str)})
    states = []
    for gap_id in gap_ids:
        scoped = [a for a in evidence["attempts"]
                  if gap_id in (a.get("gap_ids") or [])]
        result = project(
            scoped, questions=evidence["questions"], gap_id=gap_id,
            learning_task_ids=[t["task_id"] for t in evidence["learning_tasks"]
                               if gap_id in t["gap_ids"]],
        )
        states.append(MasteryStateRecord(
            gap_id=gap_id, **result.to_dict()).model_dump())
    return states
