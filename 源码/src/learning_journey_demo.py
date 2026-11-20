"""Read-only integrity checks for the isolated curated journey demo; no model or database."""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from mastery_service import fingerprint

class JourneyError(ValueError):
    pass

def require(condition,message):
    if not condition: raise JourneyError(message)

def unique(items,key):
    require(isinstance(items,list),f"{key}: 必须是列表")
    result={}
    for item in items:
        require(isinstance(item,dict) and isinstance(item.get(key),str) and item[key] and item[key] not in result,f"{key}: 身份缺失或重复")
        result[item[key]]=item
    return result

def day(value):
    try: return date.fromisoformat(value)
    except (ValueError,TypeError): raise JourneyError("日期无效") from None

def stamp(value):
    try:
        t=datetime.fromisoformat(value.replace("Z","+00:00"))
        require(t.utcoffset() is not None,"时间须含时区")
        return t
    except (ValueError,TypeError,AttributeError): raise JourneyError("时间无效") from None

def validate(d):
    try: return _validate(d)
    except (KeyError,TypeError,IndexError,AttributeError,ArithmeticError) as exc: raise JourneyError("演示结构或引用无效") from exc

def _validate(d):
    require(d["contract_version"]=="learning-evidence-v2-draft1" and d["source_kind"]=="curated_demo","来源或合同版本无效")
    sess=d["session"];require(all(sess[k] for k in ("session_id","plan_id","trace_id","position_id")) and sess["timezone"]=="Asia/Shanghai","会话域无效")
    stamp(sess["snapshot_at"])
    topics=unique(d["topics"],"topic_id"); tasks=unique(d["tasks"],"task_id"); schedules=unique(d["schedule"],"schedule_id")
    guides=unique(d["guides"],"guide_id"); resources=unique(d["resources"],"resource_id")
    require(len(topics)==4 and len(tasks)==10 and len({x["gap_id"] for x in topics.values()})==len(topics),"专题或任务不完整")
    require(all(t["plan_id"]==sess["plan_id"] and t["gap_id"] for t in topics.values()),"专题域无效")
    for t in tasks.values():
        require(t["plan_id"]==sess["plan_id"] and t["title"] and t["goal"] and t["topic_ids"] and set(t["topic_ids"])<=topics.keys(),"任务专题无效")
    require({s["task_id"] for s in schedules.values()}==set(tasks),"安排缺少任务")
    for s in schedules.values():
        require(s["task_id"] in tasks and day(s["start_date"])<=day(s["end_date"]) and s["status"] in {"not_started","in_progress","completed"} and type(s["version"]) is int and s["version"]>0,"安排无效")
    require({g["task_id"] for g in guides.values()}==set(tasks) and len(guides)==len(tasks),"学习引导不完整")
    for g in guides.values():
        require(g["task_id"] in tasks and g["objectives"] and g["steps"] and g["exercise"] and g["self_check"] and g["resource_ids"] and set(g["resource_ids"])<=resources.keys(),"学习引导无效")
    for r in resources.values():require(r["type"]=="offline_text" and r["title"] and r["body"] and r["verification"],"材料无效")
    assessments=unique(d["assessments"],"assessment_id");questions=unique(d["questions"],"question_id");attempts=unique(d["attempts"],"attempt_id");evidence=unique(d["topic_evidence"],"evidence_id");retests=unique(d["retests"],"retest_session_id");interviews=unique(d["interviews"],"interview_id")
    for a in assessments.values():
        require(a["kind"] in ("day","week") and a["status"]=="completed","考核状态无效");stamp(a["created_at"])
        scope=a["scope_snapshot"];require(scope["timezone"]==sess["timezone"] and day(scope["period_start"])<=day(scope["period_end"]) and scope["items"],"考核范围无效")
        seen=set()
        for item in scope["items"]:
            sid=item["schedule_id"];require(sid in schedules and sid not in seen,"范围身份重复或不存在");seen.add(sid)
            s=schedules[sid];t=tasks[s["task_id"]];require(item["task_id"]==s["task_id"] and item["topic_ids"]==t["topic_ids"] and day(item["start_date"])<=day(item["end_date"]) and type(item["version"]) is int and 0<item["version"]<=s["version"] and item["status"] in {"not_started","in_progress","completed"},"范围快照无效")
    for q in questions.values():
        require(q["text"] and q["fingerprint"]==fingerprint(q["text"]) and q["task_ids"] and q["topic_ids"] and len(set(q["task_ids"]))==len(q["task_ids"]) and len(set(q["topic_ids"]))==len(q["topic_ids"]),"题目无效")
        require(set(q["task_ids"])<=tasks.keys() and set(q["topic_ids"])=={topic for tid in q["task_ids"] for topic in tasks[tid]["topic_ids"]},"题目任务与专题不符")
        if q["owner_type"]=="assessment":
            require(q["owner_id"] in assessments,"考核不存在");scope=assessments[q["owner_id"]]["scope_snapshot"]
            require(set(q["task_ids"])<={item["task_id"] for item in scope["items"]},"考题超出冻结范围")
        else:require(q["owner_type"]=="retest" and q["owner_id"] in retests and q["topic_ids"]==[retests[q["owner_id"]]["topic_id"]],"复测题归属无效")
    seqs=set();attempt_by_q={}
    for a in attempts.values():
        qid=a["question_id"];require(qid in questions and qid not in attempt_by_q,"题目作答缺失或重复");attempt_by_q[qid]=a
        require(type(a["commit_seq"]) is int and a["commit_seq"]>0 and a["commit_seq"] not in seqs and a["status"]=="graded" and a["score_source"]=="curated_demo" and a["answer"] and a["scoring_version"]==questions[qid]["rubric_definition_version"],"作答无效")
        seqs.add(a["commit_seq"]);stamp(a["submitted_at"])
    require(set(attempt_by_q)==set(questions) and seqs==set(range(1,len(attempts)+1)),"作答序列不完整")
    ordered=sorted(attempts.values(),key=lambda a:a["commit_seq"]);require(all(stamp(a["submitted_at"])<=stamp(b["submitted_at"]) for a,b in zip(ordered,ordered[1:])),"样例时间与提交顺序不一致")
    pairs=set()
    for e in evidence.values():
        aid=e["attempt_id"];topic=e["topic_id"];require(aid in attempts and topic in questions[attempts[aid]["question_id"]]["topic_ids"] and (aid,topic) not in pairs,"分项身份不匹配");pairs.add((aid,topic))
        require(e["provenance"]=="curated_demo" and e["status"]=="active" and e["feedback"],"分项来源无效")
        dims=e["rubric_dimensions"];require(isinstance(dims,list) and dims and len({x["key"] for x in dims})==len(dims),"评分维度无效")
        require(all(x["key"] and type(x["weight_bps"]) is int and x["weight_bps"]>0 and type(x["score"]) is int and 0<=x["score"]<=100 for x in dims) and sum(x["weight_bps"] for x in dims)==10000,"评分权重或分数无效")
        score=(sum(Decimal(x["score"])*x["weight_bps"] for x in dims)/Decimal(10000)).quantize(Decimal("1"),rounding=ROUND_HALF_EVEN)
        require(type(e["topic_score"]) is int and score==e["topic_score"],"专题成绩不能复算")
    require(pairs=={(a["attempt_id"],t) for a in attempts.values() for t in questions[a["question_id"]]["topic_ids"]},"专题分项缺失")
    for r in retests.values():
        require(r["topic_id"] in topics and r["source_evidence_id"] in evidence and evidence[r["source_evidence_id"]]["topic_id"]==r["topic_id"] and r["steps"] and r["status"]=="completed","复测来源无效");stamp(r["created_at"])
        parent=evidence[r["source_evidence_id"]]["attempt_id"]
        for step in r["steps"]:
            qid=step["question_id"];require(qid in questions and questions[qid]["owner_id"]==r["retest_session_id"] and parent==step["parent_attempt_id"] and step["parent_question_id"]==attempts[parent]["question_id"],"复测父子关系无效")
            child=attempt_by_q[qid];require(attempts[parent]["commit_seq"]<child["commit_seq"],"复测顺序无效")
            older=[e for e in evidence.values() if e["topic_id"]==r["topic_id"] and attempts[e["attempt_id"]]["commit_seq"]<child["commit_seq"]]
            require(max(attempts[e["attempt_id"]]["commit_seq"] for e in older)==attempts[parent]["commit_seq"],"复测未承接最新专题作答")
            parent=child["attempt_id"]
        require({x["question_id"] for x in r["steps"]}=={q["question_id"] for q in questions.values() if q["owner_type"]=="retest" and q["owner_id"]==r["retest_session_id"]},"复测题链不完整")
    for i in interviews.values():
        require(i["position_id"]==sess["position_id"] and i["status"]=="completed" and i["notice"] and stamp(i["created_at"])<=stamp(i["completed_at"]),"面试无效")
        turns=unique(i["turns"],"turn_id");require([x["seq"] for x in i["turns"]]==list(range(1,len(turns)+1)),"面试轮次无效")
        require(all(x["role"]==( "interviewer" if n%2==0 else "candidate_example") and x["text"] and set(x["topic_ids"])<=topics.keys() for n,x in enumerate(i["turns"])),"面试对话无效")
        for f in i["feedback"]:
            require(f["text"] and f["turn_refs"] and set(f["turn_refs"])<=turns.keys() and set(f.get("suggested_topic_ids",[]))<=topics.keys() and set(f.get("suggested_task_ids",[]))<=tasks.keys(),"面试反馈引用无效")
    records=unique(d["record_views"],"record_id");expected={("day_assessment" if a["kind"]=="day" else "week_assessment",a["assessment_id"]) for a in assessments.values()}|{("retest",r) for r in retests}|{("interview",i) for i in interviews}|{("learning",sid) for sid in schedules}
    pairs2={(r["type"],r["ref_id"]) for r in records.values()};require(len(records)==len(expected) and pairs2==expected,"记录索引缺失或重复")
    for r in records.values():stamp(r["occurred_at"])
    return True

def load(directory):
    directory=Path(directory);m=json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
    require(m.get("schema_version")==1 and m.get("data_file")=="journey.json" and m.get("source_kind")=="curated_demo","manifest 无效")
    raw=(directory/"journey.json").read_bytes();require(hashlib.sha256(raw).hexdigest()==m.get("sha256"),"演示数据摘要不一致")
    try:d=json.loads(raw.decode("utf-8"))
    except (ValueError,UnicodeError) as exc:raise JourneyError("演示数据无法读取") from exc
    require(d.get("scenario_id")==m.get("scenario_id") and d.get("contract_version")==m.get("contract_version"),"演示身份不一致")
    validate(d);return d

def summary(d):
    return {"scenario_id":d["scenario_id"],"source_kind":d["source_kind"],"topics":len(d["topics"]),"learning_tasks":len(d["tasks"]),"guides":len(d["guides"]),"day_assessments":sum(a["kind"]=="day" for a in d["assessments"]),"week_assessments":sum(a["kind"]=="week" for a in d["assessments"]),"questions":len(d["questions"]),"topic_evidence":len(d["topic_evidence"]),"retest_sessions":len(d["retests"]),"interview_turns":sum(len(i["turns"]) for i in d["interviews"]),"records":len(d["record_views"]),"notice":d["disclosure"]}


def records(d,topic_id=None):
    """Read references only; learning times are snapshot dates, not inferred completion times."""
    validate(d)
    topics={t["topic_id"] for t in d["topics"]}
    if topic_id is not None: require(topic_id in topics,"专题不存在")
    tasks={t["task_id"]:t for t in d["tasks"]};schedules={s["schedule_id"]:s for s in d["schedule"]}
    assessments={a["assessment_id"]:a for a in d["assessments"]};retests={r["retest_session_id"]:r for r in d["retests"]};interviews={i["interview_id"]:i for i in d["interviews"]}
    result=[]
    for record in d["record_views"]:
        kind=record["type"];ref=record["ref_id"]
        if kind=="learning": related=tasks[schedules[ref]["task_id"]]["topic_ids"]
        elif kind in ("day_assessment","week_assessment"): related=sorted({t for x in assessments[ref]["scope_snapshot"]["items"] for t in x["topic_ids"]})
        elif kind=="retest":related=[retests[ref]["topic_id"]]
        else:related=sorted({t for turn in interviews[ref]["turns"] for t in turn["topic_ids"]})
        if topic_id is None or topic_id in related:result.append({**record,"topic_ids":related})
    return result
