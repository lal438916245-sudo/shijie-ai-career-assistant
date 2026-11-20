"""固定案例的只读专题合同；不访问数据库、不调用模型、不生成题目。"""
import hashlib
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict
from competition_contracts import CompetitionSnapshot, GapRecord, LearningTaskRecord, QuestionRecord, AttemptRecord, MasteryStateRecord
from demo_replay import load_demo_replay
from mastery_policy import project

class TopicContractError(ValueError):
    pass

class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class ScheduleReference(Record):
    schedule_id: str
    task_id: int
    sample_day: int
    sample_progress: str

class TopicView(Record):
    topic_key: str
    gap: GapRecord
    learning_tasks: tuple[LearningTaskRecord, ...]
    sample_schedule: tuple[ScheduleReference, ...]
    questions: tuple[QuestionRecord, ...]
    attempts: tuple[AttemptRecord, ...]
    latest_attempt_id: int | None
    mastery: MasteryStateRecord

class TopicCatalog(Record):
    contract_version: int = 1
    source_kind: str = "curated_demo"
    scenario_id: str
    trace_id: str
    plan_id: str
    topics: tuple[TopicView, ...]

def unique(items, key, label):
    values = [item[key] if isinstance(item,dict) else getattr(item,key) for item in items]
    if len(values) != len(set(values)):
        raise TopicContractError(label + "身份重复")
    return dict(zip(values,items))

def build_topic_catalog(snapshot: CompetitionSnapshot, presentation: dict) -> TopicCatalog:
    """按 gap 隔离记录，使用已有纯规则核对历史和最新能力状态。"""
    if snapshot.meta.mode != "demo_replay" or snapshot.meta.disclosure.generator_type != "curated_demo" or snapshot.meta.disclosure.model_name is not None:
        raise TopicContractError("仅支持固定演示数据")
    if presentation.get("schema_version") != 2 or presentation.get("scenario_id") != snapshot.meta.scenario_id:
        raise TopicContractError("展示数据案例或版本不匹配")
    disclosure=presentation.get("disclosure") or {}
    if disclosure.get("generator_type") != "curated_demo" or disclosure.get("model_name") is not None:
        raise TopicContractError("缺少演示来源声明")
    try:
        topics=unique(presentation["topics"],"key","专题")
        gaps=unique(snapshot.gaps,"gap_id","差距")
        tasks=unique(snapshot.learning_tasks,"task_id","学习任务")
        questions=unique(snapshot.questions,"task_id","考题")
        attempts=unique(snapshot.attempts,"attempt_id","作答")
        order=presentation["topic_order"]
        if not topics or len(order)!=len(topics) or set(order)!=set(topics) or {t["gap_id"] for t in topics.values()}!=set(gaps) or len(gaps)!=len(topics) or set(tasks)&set(questions):
            raise TopicContractError("专题、差距或任务身份不一致")
        for task in tasks.values():
            if not task.gap_ids or not set(task.gap_ids)<=set(gaps): raise TopicContractError("学习任务来源无效")
        for q in questions.values():
            if not q.gap_ids or not q.source_task_ids or not q.question_fingerprint: raise TopicContractError("考题缺少来源")
            source_gaps={gid for tid in q.source_task_ids for gid in tasks[tid].gap_ids}
            if not set(q.gap_ids)<=source_gaps: raise TopicContractError("考题与学习任务跨专题")
            if q.retest_round==0 and q.parent_task_id is not None: raise TopicContractError("首次考核父题无效")
            if q.retest_round>0:
                parent=questions.get(q.parent_task_id)
                if parent is None or parent.retest_round!=0 or not set(q.gap_ids)<=set(parent.gap_ids): raise TopicContractError("复测父题无效")
        for a in attempts.values():
            if a.task_id not in questions: raise TopicContractError("作答缺少考题")
            if a.score_source=="rubric_weighted":
                dims=[x.dimension for x in a.rubric]
                if len(dims)!=len(set(dims)) or abs(sum(x.weight for x in a.rubric)-1)>1e-9 or round(sum(x.weight*x.score for x in a.rubric))!=a.score:
                    raise TopicContractError("正式评分明细不可复算")
                if a.status != ("completed" if a.score>=60 else "failed"): raise TopicContractError("评分状态不一致")
        schedule=presentation["schedule"]
        if schedule["version"]!=2 or schedule["caseId"]!=snapshot.meta.scenario_id: raise TopicContractError("学习安排案例不匹配")
        rows=schedule["items"];unique(rows,"id","安排");assigned=[]
        for row in rows:
            if row["kind"] not in ("study","weekly","buffer"): raise TopicContractError("安排类型无效")
            if row["kind"]!="study":
                if row["task_id"] is not None or row["topic"] is not None: raise TopicContractError("非学习安排关联了专题任务")
                continue
            topic=topics.get(row["topic"]);task=tasks.get(row["task_id"])
            if not topic or not task or topic["gap_id"] not in task.gap_ids or not isinstance(row["day"],int) or isinstance(row["day"],bool) or not 1<=row["day"]<=30 or row["status"] not in ("not_started","in_progress","completed"):
                raise TopicContractError("学习安排来源或进度无效")
            assigned.append(row["task_id"])
        if len(assigned)!=len(set(assigned)) or set(assigned)!=set(tasks): raise TopicContractError("学习安排任务缺失或重复")
        views=[]
        for key in order:
            gid=topics[key]["gap_id"]
            tt=tuple(sorted((x for x in tasks.values() if gid in x.gap_ids),key=lambda x:x.task_id))
            qq=tuple(sorted((x for x in questions.values() if gid in x.gap_ids),key=lambda x:(x.retest_round,x.task_id)))
            ids={x.task_id for x in qq}
            aa=tuple(sorted((x for x in attempts.values() if x.task_id in ids),key=lambda x:x.attempt_id))
            qd=[x.model_dump() for x in qq]; td=[x.task_id for x in tt]
            calculated=project([x.model_dump() for x in aa],questions=qd,gap_id=gid,learning_task_ids=td)
            history=[x for x in snapshot.mastery_states if x.gap_id==gid]
            if not history: raise TopicContractError("专题缺少能力状态")
            endpoints=set()
            for state in history:
                end=max(state.attempt_ids,default=-1)
                if end in endpoints: raise TopicContractError("能力状态有歧义")
                endpoints.add(end)
                referenced=[attempts[x].model_dump() for x in state.attempt_ids]
                if any(x["task_id"] not in ids for x in referenced): raise TopicContractError("状态引用其他专题作答")
                if state.model_dump(exclude={"gap_id"})!=project(referenced,questions=qd,gap_id=gid,learning_task_ids=td).to_dict(): raise TopicContractError("历史状态与规则不一致")
            latest=max(history,key=lambda x:max(x.attempt_ids,default=-1))
            if latest.model_dump(exclude={"gap_id"})!=calculated.to_dict(): raise TopicContractError("最新状态未覆盖当前证据")
            refs=tuple(ScheduleReference(schedule_id=x["id"],task_id=x["task_id"],sample_day=x["day"],sample_progress=x["status"]) for x in rows if x["kind"]=="study" and x["topic"]==key)
            views.append(TopicView(topic_key=key,gap=gaps[gid],learning_tasks=tt,sample_schedule=refs,questions=qq,attempts=aa,latest_attempt_id=aa[-1].attempt_id if aa else None,mastery=latest))
        return TopicCatalog(scenario_id=snapshot.meta.scenario_id,trace_id=snapshot.trace.trace_id,plan_id=snapshot.trace.plan_id,topics=tuple(views))
    except TopicContractError: raise
    except (KeyError,TypeError,ValueError) as exc: raise TopicContractError("专题数据缺失或结构无效") from exc

def load_demo_topic_catalog(scenario_dir: str | Path) -> TopicCatalog:
    """校验核心及展示补充文件摘要后只读加载。"""
    root=Path(scenario_dir).resolve()
    snapshot=load_demo_replay(root)
    try:
        m=json.loads((root/"presentation.manifest.json").read_text(encoding="utf-8"))
        if set(m)!={"schema_version","scenario_id","presentation_file","presentation_sha256","core_sha256"} or m["schema_version"]!=2 or m["scenario_id"]!=snapshot.meta.scenario_id or m["presentation_file"]!="presentation.json": raise TopicContractError("补充 manifest 无效")
        manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
        if manifest.get("bundle_file")!="bundle.json": raise TopicContractError("核心文件身份不一致")
        raw=(root/"presentation.json").read_bytes()
        if hashlib.sha256((root/"bundle.json").read_bytes()).hexdigest()!=m["core_sha256"] or hashlib.sha256(raw).hexdigest()!=m["presentation_sha256"]: raise TopicContractError("演示数据校验和不匹配")
        return build_topic_catalog(snapshot,json.loads(raw))
    except TopicContractError: raise
    except (OSError,ValueError,TypeError,KeyError) as exc: raise TopicContractError("无法加载专题演示数据") from exc

def get_demo_topic(catalog: TopicCatalog, topic_key: str) -> TopicView:
    found=[x for x in catalog.topics if x.topic_key==topic_key]
    if len(found)!=1: raise TopicContractError("专题不存在或有歧义")
    return found[0]
