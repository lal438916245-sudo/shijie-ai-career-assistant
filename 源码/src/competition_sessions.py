"""首次输入与 A→B→首次 C 考核的独立会话服务。页面读取无需模型或迁移。"""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError

import gap_registry
from diagnosis_evidence import (EvidenceAssessment, JDItem, EvidenceValidationError, validate_evidence_audit)
import input_provenance
from plan_contract import PlanValidationError, validate_plan, validation_error
from daily_learning import LearningPreferences, plan_model
from mastery_service import fingerprint, json_list, rows, table_exists


class SessionError(ValueError):
    pass


class SessionPlanError(SessionError):
    def __init__(self, diagnostics):
        self.validation_error = diagnostics
        super().__init__(diagnostics['summary'])


class SessionDiagnosisError(SessionError):
    def __init__(self, diagnostics):
        self.validation_error = diagnostics
        super().__init__(diagnostics['summary'])


class SessionBusy(SessionError):
    pass


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    target_role: str = Field(min_length=1, max_length=120)
    resume_text: str = Field(min_length=20, max_length=60000)
    jd_text: str = Field(min_length=20, max_length=30000)
    available_days: int = Field(default=7, ge=4, le=30)
    learning_preferences: LearningPreferences | None = None


class DiagnosticGap(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, str_strip_whitespace=True)
    skill: str = Field(min_length=1, max_length=300)
    industry_requirement: str = Field(min_length=1, max_length=2000)
    candidate_current: str = Field(min_length=1, max_length=2000)
    gap_reason: str = Field(min_length=1, max_length=2000)


class ScoreDimension(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    score: int = Field(ge=0, le=100)
    reason: str = Field(min_length=1, max_length=2000)


class Diagnosis(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, str_strip_whitespace=True)
    analysis_mode: Literal["targeted"] = "targeted"
    match_score: int = Field(ge=0, le=100)
    score_reason: str = Field(min_length=1, max_length=2000)
    fatal_weakness: str = Field(min_length=1, max_length=3000)
    score_breakdown: dict[str, ScoreDimension] = Field(default_factory=dict)
    invisible_gaps: list[DiagnosticGap] = Field(default_factory=list, max_length=40)
    gap_table: list[dict[str, str]] = Field(default_factory=list, max_length=40)
    actionable_advice: list[str] = Field(default_factory=list, max_length=20)
    diagnosis_version: Literal['evidence-a-v1'] | None = None
    evidence_assessment: EvidenceAssessment | None = None
    jd_items: list[JDItem] | None = None
    clarification_questions: list[str] | None = None
    score_label: str | None = None


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def session_info(conn):
    if not table_exists(conn, "competition_session"):
        return None
    found = rows(conn, "SELECT * FROM competition_session WHERE singleton=1")
    if not found:
        raise SessionError("会话初始化尚未完成")
    result = found[0]
    result["inputs"] = json.loads(result.pop("input_json"))
    result["input_bundle"] = json.loads(result.pop("bundle_json"))
    return result


def stage_records(conn):
    if not table_exists(conn, "competition_stages"):
        return []
    columns = {r[1] for r in conn.execute("PRAGMA table_info(competition_stages)")}
    detail = "validation_json" if "validation_json" in columns else "NULL AS validation_json"
    return rows(conn, "SELECT stage,status,error_type,model_name,result_json," + detail +
                " FROM competition_stages ORDER BY rowid")


def completed_result(conn, stage):
    record = next((r for r in stage_records(conn)
                   if r["stage"] == stage and r["status"] == "completed"), None)
    return json.loads(record["result_json"]) if record else None


def create_session(directory, inputs, creation_token):
    """用户显式保存时创建一个本地库；同一创建 token 不能覆盖另一份输入。"""
    from db_manager import DBManager
    inputs = SessionInput.model_validate(inputs)
    token = str(uuid.UUID(str(creation_token)))
    session_id = uuid.uuid5(uuid.NAMESPACE_URL, "CareerPilot:" + token).hex
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"session_{session_id}.db"
    payload = inputs.model_dump(exclude_none=True)
    digest = hashlib.sha256(encode(payload).encode("utf-8")).hexdigest()
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            try:
                existing = session_info(conn)
            except sqlite3.Error as exc:
                raise SessionBusy("会话正在初始化，请稍后重试") from exc
            if existing is None:
                raise SessionBusy("会话初始化未完成，请创建新的会话")
            if existing["input_digest"] != digest and SessionInput.model_validate(existing["inputs"]).model_dump(exclude_none=True) != payload:
                raise SessionError("已保存输入不能被覆盖，请新建会话保存修改")
            return {"path": str(path), **existing}
        finally:
            conn.close()
    db = DBManager(str(path))
    try:
        db.conn.execute("BEGIN IMMEDIATE")
        db.conn.execute("""
            CREATE TABLE competition_session (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                session_id TEXT NOT NULL UNIQUE, trace_id TEXT NOT NULL UNIQUE,
                report_id TEXT NOT NULL, plan_id TEXT,
                input_digest TEXT NOT NULL, input_json TEXT NOT NULL,
                bundle_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.conn.execute("""
            CREATE TABLE competition_stages (
                stage TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN ('generating','completed','failed')),
                owner_token TEXT, result_json TEXT, model_name TEXT, error_type TEXT, validation_json TEXT
            )
        """)
        bundle = input_provenance.build_input_bundle(
            inputs.resume_text, inputs.jd_text, "resume.txt", "target-jd.txt")
        db.conn.execute(
            "INSERT INTO competition_session(singleton,session_id,trace_id,report_id,"
            "input_digest,input_json,bundle_json) VALUES (1,?,?,?,?,?,?)",
            (session_id, "TRACE_" + session_id[:16], "GAP_" + session_id[:16],
             digest, encode(payload), encode(bundle)))
        db.conn.commit()
        return {"path": str(path), **session_info(db.conn)}
    finally:
        db.close()


class SessionWorkflow:
    def __init__(self, db):
        self.db, self.conn = db, db.conn
        if session_info(self.conn) is None:
            raise SessionError("该库没有首次输入会话，请从概览创建会话")

    def _message(self, from_agent, to_agent, stage, refs):
        meta = session_info(self.conn)
        seq = self.conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM agent_messages "
                                "WHERE trace_id=?", (meta["trace_id"],)).fetchone()[0]
        self.conn.execute("INSERT INTO agent_messages"
                          "(trace_id,seq,from_agent,to_agent,msg_type,payload_json) "
                          "VALUES (?,?,?,?,?,?)",
                          (meta["trace_id"], seq, from_agent, to_agent, "result",
                           encode({"type": stage, "input_bundle_id":
                                   meta["input_bundle"]["bundle_id"], **refs})))

    def _run(self, stage, producer, saver):
        token = uuid.uuid4().hex
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            if 'validation_json' not in {r[1] for r in self.conn.execute('PRAGMA table_info(competition_stages)')}:
                self.conn.execute('ALTER TABLE competition_stages ADD COLUMN validation_json TEXT')
            current = next((r for r in stage_records(self.conn) if r["stage"] == stage), None)
            if current and current["status"] == "completed":
                self.conn.rollback()
                return json.loads(current["result_json"])
            if current and current["status"] == "generating":
                raise SessionBusy("该步骤正在执行，请勿重复提交")
            self.conn.execute(
                "INSERT INTO competition_stages(stage,status,owner_token) VALUES (?,'generating',?) "
                "ON CONFLICT(stage) DO UPDATE SET status='generating',owner_token=excluded.owner_token,"
                "error_type=NULL,validation_json=NULL WHERE competition_stages.status='failed'", (stage, token))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        try:
            payload = producer(session_info(self.conn))
            self.conn.execute("BEGIN IMMEDIATE")
            owner = self.conn.execute(
                "SELECT 1 FROM competition_stages WHERE stage=? AND owner_token=? "
                "AND status='generating'", (stage, token)).fetchone()
            if not owner:
                raise SessionError("该步骤已恢复或失效，旧结果不能保存")
            saver(payload, session_info(self.conn))
            self.conn.execute(
                "UPDATE competition_stages SET status='completed',owner_token=NULL,"
                "result_json=?,model_name=? WHERE stage=?",
                (encode(payload), payload.get("model_name"), stage))
            self.conn.commit()
            return payload
        except Exception as exc:
            self.conn.rollback()
            self.conn.execute("UPDATE competition_stages SET status='failed',owner_token=NULL,"
                              "error_type=?,validation_json=? WHERE stage=? AND owner_token=? AND status='generating'",
                              (type(exc).__name__, encode(exc.validation_error) if isinstance(exc, (SessionPlanError, SessionDiagnosisError)) else None, stage, token))
            self.conn.commit()
            raise

    def diagnose(self, hunter_factory):
        def produce(meta):
            from json_utils import parse_llm_json
            hunter = hunter_factory()
            hunter.learning_preferences = meta["inputs"].get("learning_preferences")
            hunter.trace_id = meta["trace_id"]
            try:
                raw = hunter.deep_audit(target_job_title=meta["inputs"]["target_role"],
                                        resume_text=meta["inputs"]["resume_text"],
                                        jd_text=meta["inputs"]["jd_text"])
                if isinstance(raw, str):
                    raw, degraded = parse_llm_json(raw)
                    if degraded:
                        raise EvidenceValidationError([{'code': 'diagnosis_json', 'path': 'diagnosis'}])
                if (getattr(hunter, 'evidence_contract_required', False)
                        or (isinstance(raw, dict) and 'diagnosis_version' in raw)):
                    raw = validate_evidence_audit(raw, meta['inputs'])
                audit = Diagnosis.model_validate(raw).model_dump(exclude_none=True)
            except EvidenceValidationError as exc:
                raise SessionDiagnosisError(exc.validation_error) from None
            audit = input_provenance.attach_to_audit(audit, meta["input_bundle"])
            gaps = gap_registry.extract_gaps(audit, meta["report_id"])
            if any(not gap["skill"] for gap in gaps):
                raise SessionError("诊断差距缺少技能名称")
            return {"audit": audit, "gaps": gaps, "report_id": meta["report_id"],
                    "model_name": getattr(hunter, "model_name", "unspecified")}
        def save(payload, meta):
            import pandas as pd
            audit = payload["audit"]
            self.db.save_gap_report(
                meta["report_id"], meta["trace_id"], "用户目标岗位",
                meta["inputs"]["target_role"], audit["match_score"],
                pd.DataFrame(audit["gap_table"]), audit,
                scorer=self.db.SCORER_MODEL_MATCH, commit=False)
            self._message("Agent_A", "Agent_B", "competition_diagnosis",
                          {"report_id": meta["report_id"]})
        return self._run("diagnosis", produce, save)

    def generate_plan(self, planner_factory):
        diagnosis = completed_result(self.conn, "diagnosis")
        if not diagnosis:
            raise SessionError("请先完成岗位诊断")
        if not diagnosis["gaps"]:
            raise SessionError("诊断没有结构化差距，当前无需生成差距学习计划")
        def produce(meta):
            from agent_b_planner import LearningPlan, PlannerAgent
            planner = planner_factory()
            planner.trace_id = meta["trace_id"]
            if getattr(planner, "db", None) is not None:
                raise SessionError("计划生成器必须由会话服务统一保存结果")
            planner.require_session_plan = True
            planner.session_plan_gaps = diagnosis['gaps']
            preferences=meta['inputs'].get('learning_preferences')
            planner.learning_preferences=preferences
            planner.schema_json=json.dumps(plan_model(preferences).model_json_schema(),ensure_ascii=False)
            try:
                plan = planner.generate_plan(
                    encode(diagnosis["audit"]), meta["inputs"]["available_days"], max_retries=1,
                    gaps=diagnosis["gaps"], report_id=meta["report_id"])
                if plan is None:
                    detail = getattr(planner, 'last_plan_validation', None)
                    raise SessionPlanError(detail or validation_error(None).diagnostics)
                plan = plan_model(preferences).model_validate(plan)
                validate_plan(plan, meta['inputs']['available_days'], gaps=diagnosis['gaps'], require_sources=True, learning_preferences=preferences)
            except PlanValidationError as exc:
                raise SessionPlanError(exc.diagnostics) from None
            except ValidationError as exc:
                raise SessionPlanError(validation_error(exc).diagnostics) from None
            return {"plan": plan.model_dump(), "plan_id": "PLAN_" + meta["session_id"][:16],
                    "model_name": getattr(planner, "model_name", "unspecified")}
        def save(payload, meta):
            from agent_b_planner import LearningPlan
            self.db.save_complete_plan(plan_model(meta["inputs"].get("learning_preferences")).model_validate(payload["plan"]),
                payload["plan_id"], source_report_id=meta["report_id"],
                known_gap_ids=gap_registry.known_gap_ids(diagnosis["gaps"]), commit=False)
            self.conn.execute("UPDATE competition_session SET plan_id=? WHERE singleton=1",
                              (payload["plan_id"],))
            self._message("Agent_B", "Agent_C", "competition_plan",
                          {"plan_id": payload["plan_id"], "report_id": meta["report_id"]})
        return self._run("plan", produce, save)

    def review_plan(self, critic_factory):
        plan_result = completed_result(self.conn, "plan")
        diagnosis = completed_result(self.conn, "diagnosis")
        if not plan_result or not diagnosis:
            raise SessionError("请先生成学习计划")
        def produce(meta):
            from agent_b_planner import LearningPlan
            critic = critic_factory()
            critic.trace_id = meta["trace_id"]
            result = critic.critique(LearningPlan.model_validate(plan_result["plan"]),
                resume_text=meta["inputs"]["resume_text"], jd_text=meta["inputs"]["jd_text"],
                gap_report=encode(diagnosis["audit"]))
            if (not isinstance(result, dict) or result.get("_degraded")
                    or not isinstance(result.get("critiques"), list)
                    or not isinstance(result.get("summary"), str) or not result["summary"].strip()
                    or not isinstance(result.get("_valid"), list)):
                raise SessionError("计划审查结果不完整")
            valid = [c.to_dict() if hasattr(c, "to_dict") else c for c in result["_valid"]]
            verdict = "needs_revision" if valid else (
                "review_required" if result.get("_rejected") else "pass")
            return {"verdict": verdict, "summary": result["summary"], "critiques": valid,
                    "rejected_count": len(result.get("_rejected") or []),
                    "model_name": getattr(critic, "model_name", "unspecified")}
        return self._run("review", produce, lambda payload, meta: self._message(
            "Agent_F", "Agent_B", "competition_review",
            {"plan_id": meta["plan_id"], "verdict": payload["verdict"]}))

    def create_initial_exam(self, task_id, assessor_factory):
        meta = session_info(self.conn)
        task = self.db.get_task_by_id(task_id)
        if (not meta["plan_id"] or not task or task["plan_id"] != meta["plan_id"]
                or str(task["task_type"] or "").startswith(self.db.EXAM_TASK_TYPE)):
            raise SessionError("请选择当前会话学习计划中的学习任务")
        if not json_list(task["gap_ids"]):
            raise SessionError("学习任务缺少 gap 来源")
        def produce(meta):
            import exam_scope
            import exam_provenance
            assessor = assessor_factory()
            assessor.trace_id = meta["trace_id"]
            catalog = exam_scope.build_task_catalog([task])
            questions = assessor.generate_exam_set(
                material=catalog, scope_label="首次单任务考核", days=[task["day"]],
                n=1, difficulty="normal", focus=task["expected_outcome"], task_catalog=catalog)
            questions = exam_provenance.attach_provenance(questions, [task])
            if (len(questions) != 1 or questions[0]["source_task_ids"] != [task_id]
                    or questions[0]["unknown_task_ids"]
                    or questions[0]["provenance_status"] != "exam_linked"):
                raise SessionError("首次考题来源不完整")
            question = questions[0]
            fingerprint(question.get("question"))
            return {"question": question, "model_name": getattr(assessor, "model_name", "unspecified")}
        def save(payload, meta):
            q = payload["question"]
            current = self.db.get_task_by_id(task_id)
            if current != task:
                raise SessionError("生成期间学习任务已变化")
            payload["task_id"] = self.db.insert_exam_task(
                meta["plan_id"], task["phase_id"], task["phase_name"], task["day"],
                q["question"], focus=q.get("focus"), difficulty="normal",
                source_task_ids=q["source_task_ids"], gap_ids=q["gap_ids"],
                provenance_status=q["provenance_status"], commit=False)
            self._message("Agent_C", "Learner", "competition_initial_exam",
                          {"task_id": payload["task_id"], "source_task_ids": [task_id]})
        return self._run(f"exam:{task_id}", produce, save)

    def recover_interrupted(self, stage, *, worker_stopped=False):
        if not worker_stopped:
            raise SessionError("请先确认旧工作进程已经停止")
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE competition_stages SET status='failed',owner_token=NULL,"
                "error_type='WorkerInterrupted' WHERE stage=? AND status='generating'", (stage,))
        return cursor.rowcount == 1
