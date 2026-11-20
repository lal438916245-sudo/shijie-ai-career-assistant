"""Isolated, local fixed-stub practice over the scenario_03 curated demo.

No models, remote requests, production evidence, or modifications of legacy sessions.
"""
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import date
from pathlib import Path
from learning_journey_demo import load, records
from journey_practice_bank import load_bank, legacy_items

DEMO_DIR=Path(__file__).resolve().parents[1]/"examples/learning_journey_demo/scenario_03"
NOTICE="固定替身练习：题目、分数、追问和反馈来自预设案例，不分析本次输入，不代表真实能力。"
class JourneyPracticeError(ValueError): pass
class JourneyPracticeConflict(JourneyPracticeError): pass
class JourneyPracticeMissing(JourneyPracticeError): pass

_CREATE_LOCK=threading.Lock()

def _uuid(value):
    try:return str(uuid.UUID(str(value)))
    except (ValueError,TypeError,AttributeError):raise JourneyPracticeError("请求身份无效") from None

def _path(directory,token):
    token=_uuid(token);sid=uuid.uuid5(uuid.NAMESPACE_URL,"CareerPilotJourneyV2:"+token).hex
    return Path(directory).resolve()/"journey_fixture_sessions"/("journey_"+sid+".db"),sid

def _check(conn,sid):
    try:
        row=conn.execute("SELECT session_id,format_version,data_json FROM journey_meta WHERE singleton=1").fetchone()
        if not row or row[0]!=sid or row[1]!=1:raise JourneyPracticeError("不是有效的学习闭环演示会话")
        return json.loads(row[2])
    except (sqlite3.Error,ValueError,TypeError) as exc:raise JourneyPracticeError("不是有效的学习闭环演示会话") from exc

def create(directory,token):
    with _CREATE_LOCK:
        return _create(directory,token)

def _create(directory,token):
    path,sid=_path(directory,token);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_file():
        session=open_session(directory,token);session.close()
        return {"session_id":sid,"source_kind":"fixed_stub","notice":NOTICE}
    data=load(DEMO_DIR)
    try:
        fd=os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd);created=True
    except FileExistsError:created=False
    if not created:
        session=open_session(directory,token);session.close();return {"session_id":sid,"source_kind":"fixed_stub","notice":NOTICE}
    conn=sqlite3.connect(path,timeout=10)
    try:
        conn.executescript("""
        BEGIN IMMEDIATE;
        CREATE TABLE journey_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),session_id TEXT NOT NULL,format_version INTEGER NOT NULL,data_json TEXT NOT NULL);
        CREATE TABLE learning(schedule_id TEXT PRIMARY KEY,task_id TEXT NOT NULL UNIQUE,status TEXT NOT NULL,note TEXT NOT NULL,start_date TEXT NOT NULL,end_date TEXT NOT NULL,version INTEGER NOT NULL);
        CREATE TABLE learning_events(event_id TEXT PRIMARY KEY,task_id TEXT NOT NULL,snapshot_json TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE runs(run_id TEXT PRIMARY KEY,kind TEXT NOT NULL,template_id TEXT NOT NULL,status TEXT NOT NULL,position INTEGER NOT NULL,items_json TEXT NOT NULL,scope_json TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE submissions(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,item_id TEXT NOT NULL,answer TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(run_id,item_id));
        CREATE TABLE receipts(request_id TEXT PRIMARY KEY,operation TEXT NOT NULL,body_hash TEXT NOT NULL,response_json TEXT NOT NULL);
        """)
        conn.execute("INSERT INTO journey_meta VALUES (1,?,1,?)",(sid,json.dumps(data,ensure_ascii=False)))
        for s in data["schedule"]:conn.execute("INSERT INTO learning VALUES (?,?,?,?,?,?,?)",(s["schedule_id"],s["task_id"],s["status"],s["note"],s["start_date"],s["end_date"],s["version"]))
        conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()
    return {"session_id":sid,"source_kind":"fixed_stub","notice":NOTICE}

def open_session(directory,token):
    path,sid=_path(directory,token)
    if not path.is_file():raise JourneyPracticeMissing("学习闭环演示会话不存在")
    conn=sqlite3.connect(path.as_uri()+"?mode=rw",uri=True,timeout=10);conn.row_factory=sqlite3.Row
    try:data=_check(conn,sid);return JourneySession(conn,data)
    except Exception:conn.close();raise

class JourneySession:
    def __init__(self,conn,data):self.conn=conn;self.data=data
    def close(self):self.conn.close()
    def _find(self,key,idkey,value):
        found=[x for x in self.data[key] if x[idkey]==value]
        if len(found)!=1:raise JourneyPracticeMissing("演示对象不存在")
        return found[0]
    def _run(self,run_id):
        _uuid(run_id);r=self.conn.execute("SELECT * FROM runs WHERE run_id=?",(run_id,)).fetchone()
        if not r:raise JourneyPracticeMissing("练习记录不存在")
        return r
    def _learning(self,task_id):
        if not isinstance(task_id,str):raise JourneyPracticeError("学习任务无效")
        row=self.conn.execute("SELECT * FROM learning WHERE task_id=?",(task_id,)).fetchone()
        if not row:raise JourneyPracticeMissing("学习任务不存在")
        return dict(row)
    def catalog(self):
        schedule=[{k:v for k,v in dict(row).items() if k!="note"} for row in self.conn.execute("SELECT schedule_id,task_id,status,start_date,end_date,version FROM learning ORDER BY start_date,task_id")]
        retests=[]
        bank=load_bank(self.data)["templates"]
        for r in self.data["retests"]:
            e=self._find("topic_evidence","evidence_id",r["source_evidence_id"])
            a=self._find("attempts","attempt_id",e["attempt_id"]);q=self._find("questions","question_id",a["question_id"])
            matching=[x for x in self.data["record_views"] if x["ref_id"]==q["owner_id"] and x["type"] in ("day_assessment","week_assessment")]
            retests.append({"retest_session_id":r["retest_session_id"],"topic_id":r["topic_id"],"source_evidence_id":r["source_evidence_id"],"source_score":e["topic_score"],"source_feedback":e["feedback"],"source_question":q["text"],"source_record_id":matching[0]["record_id"] if len(matching)==1 else None,"question_count":len(bank[r["retest_session_id"]])})
        return {"source_kind":"fixed_stub","notice":NOTICE,"topics":self.data["topics"],"tasks":self.data["tasks"],"schedule":schedule,"assessments":[{"assessment_id":a["assessment_id"],"kind":a["kind"],"scope_snapshot":a["scope_snapshot"],"historical_example":True,"question_count":len(bank[a["assessment_id"]])} for a in self.data["assessments"]],"retests":retests,"interviews":[{"interview_id":i["interview_id"],"position_id":i["position_id"],"question_count":len(bank[i["interview_id"]])} for i in self.data["interviews"]]}
    def learning(self,task_id):
        task=self._find("tasks","task_id",task_id);guide=self._find("guides","task_id",task_id)
        resources=[self._find("resources","resource_id",rid) for rid in guide["resource_ids"]]
        result = {"task":task,"guide":guide,"resources":resources,"progress":self._learning(task_id),"source_kind":"fixed_stub","notice":NOTICE}
        # A separately labeled, read-only content preview. It does not replace
        # stored guides, scope, progress, questions, attempts or historical scores.
        from competition_case import preview_for_legacy, CaseContractError
        try:
            preview = preview_for_legacy(self.data['scenario_id'], task_id)
            if preview is not None:
                result['learning_card_preview'] = preview
        except CaseContractError:
            result['learning_card_preview_error'] = '增强学习卡暂不可用，原有固定引导和学习记录保持可用。'
        return result
    def _once(self,operation,body,fn):
        rid=_uuid(body.get("request_id"));payload=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":"));digest=hashlib.sha256(payload.encode()).hexdigest()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            old=self.conn.execute("SELECT operation,body_hash,response_json FROM receipts WHERE request_id=?",(rid,)).fetchone()
            if old:
                if old[0]!=operation or old[1]!=digest:raise JourneyPracticeConflict("请求身份已用于其他内容")
                self.conn.rollback();return json.loads(old[2])
            result=fn();self.conn.execute("INSERT INTO receipts VALUES (?,?,?,?)",(rid,operation,digest,json.dumps(result,ensure_ascii=False)))
            self.conn.commit();return result
        except Exception:self.conn.rollback();raise
    def update_learning(self,body):
        task_id=body["task_id"];status=body["status"];note=body["note"];version=body["expected_version"];start=body["start_date"];end=body["end_date"]
        if status not in ("not_started","in_progress","completed") or not isinstance(note,str) or len(note)>1000 or type(version) is not int or version<0:raise JourneyPracticeError("学习记录无效")
        try:
            first=date.fromisoformat(start);last=date.fromisoformat(end)
            if first.isoformat()!=start or last.isoformat()!=end or not 2000<=first.year<=2100 or not 0<=(last-first).days<=60:raise ValueError()
        except (ValueError,TypeError):raise JourneyPracticeError("学习日期无效") from None
        def change():
            current=self._learning(task_id)
            if current["version"]!=version:raise JourneyPracticeConflict("学习记录已变化，请重新读取")
            self.conn.execute("UPDATE learning SET status=?,note=?,start_date=?,end_date=?,version=version+1 WHERE task_id=?",(status,note,start,end,task_id))
            progress=self._learning(task_id);event_id="LE-"+str(uuid.uuid4())
            self.conn.execute("INSERT INTO learning_events(event_id,task_id,snapshot_json) VALUES (?,?,?)",(event_id,task_id,json.dumps(progress,ensure_ascii=False)))
            return {"progress":progress,"record_id":event_id,"source_kind":"fixed_stub","notice":NOTICE}
        return self._once("learning",body,change)
    def start(self,body):
        kind=body["kind"];template=body["template_id"]
        if kind not in ("day","week","retest","interview") or not isinstance(template,str):raise JourneyPracticeError("练习类型无效")
        def make():
            if kind in ("day","week"):
                a=self._find("assessments","assessment_id",template)
                if a["kind"]!=kind:raise JourneyPracticeError("考核类型与样例不符")
                items=[q["question_id"] for q in self.data["questions"] if q["owner_type"]=="assessment" and q["owner_id"]==template]
                # Freeze the selected template's task IDs with current practice progress, not the history's prior dates.
                scope={"template_period":a["scope_snapshot"],"items":[{k:v for k,v in self._learning(x["task_id"]).items() if k!="note"} for x in a["scope_snapshot"]["items"]],"notice":"所选任务和开始时进度快照；后续修改不会改变本次范围。"}
            elif kind=="retest":
                r=self._find("retests","retest_session_id",template);items=[x["question_id"] for x in r["steps"]]
                scope={"topic_id":r["topic_id"],"source_evidence_id":r["source_evidence_id"],"learning":{k:v for k,v in self._learning(r["learning_context"]["task_id"]).items() if k!="note"},"notice":"固定历史样例来源；不是根据本次回答生成的新题。"}
            else:
                i=self._find("interviews","interview_id",template);items=[x["turn_id"] for x in i["turns"] if x["role"]=="interviewer"]
                scope={"position_id":i["position_id"],"context_selection":i["context_selection"],"notice":"固定岗位问题与追问，不分析用户回答。"}
            practice=load_bank(self.data)
            frozen_items=practice["templates"][template]
            items=[x["id"] for x in frozen_items]
            scope["_practice_items"]=frozen_items
            scope["_practice_version"]=practice["version"]
            if not items:raise JourneyPracticeError("该样例没有题目")
            run_id=str(uuid.uuid4());self.conn.execute("INSERT INTO runs(run_id,kind,template_id,status,position,items_json,scope_json) VALUES (?,?,?,'active',0,?,?)",(run_id,kind,template,json.dumps(items),json.dumps(scope,ensure_ascii=False)))
            return self.state(run_id)
        return self._once("start",body,make)
    def _practice_items(self,r):
        scope=json.loads(r["scope_json"])
        items=scope.get("_practice_items")
        if items is None:return legacy_items(self.data,r)
        if [x["id"] for x in items]!=json.loads(r["items_json"]):raise JourneyPracticeError("已保存题目身份不一致")
        return items
    def state(self,run_id):
        r=self._run(run_id);items=self._practice_items(r);scope=json.loads(r["scope_json"])
        # Private frozen references must never leak in preparation/current question.
        scope={k:v for k,v in scope.items() if not k.startswith("_practice_")}
        terminal=r["status"] in ("completed","ended_early")
        question=None
        if r["status"]=="active":
            item=items[r["position"]];question={k:item[k] for k in ("id","text","topic_ids")}
        submissions=self.conn.execute("SELECT item_id,answer FROM submissions WHERE run_id=? ORDER BY id",(run_id,)).fetchall()
        by_id={x["id"]:x for x in items};reviews=[];evidence=[]
        reveal=terminal or r["kind"]=="retest"
        if reveal:
            for row in submissions:
                item=by_id[row["item_id"]]
                reviews.append({"item_id":item["id"],"question_text":item["text"],"answer":row["answer"],"topic_ids":item["topic_ids"],**item["review"]})
                evidence.extend({**e,"question_id":item["id"]} for e in item["sample_evidence"])
        result={"topic_evidence":evidence,"source_kind":"fixed_stub","notice":"仅展示已有合成案例题的分项分数；不代表整份试卷得分或本次作答评价。"} if evidence else None
        report=None
        if r["kind"]=="interview" and r["status"]=="completed":
            i=self._find("interviews","interview_id",r["template_id"]);report={"feedback":i["feedback"],"notice":"预先编写的合成案例反馈，不评价本次回答。"}
        return {"run_id":run_id,"kind":r["kind"],"template_id":r["template_id"],"status":r["status"],"scope":scope,"current_question":question,"result":result,"report":report,"reviews":reviews,"submitted_count":len(submissions),"question_count":len(items),"source_kind":"fixed_stub","notice":NOTICE}
    def answer(self,body):
        run_id=body["run_id"];item=body["item_id"];answer=body["answer"]
        if not isinstance(item,str) or not isinstance(answer,str) or not answer.strip() or len(answer)>6000:raise JourneyPracticeError("请填写有效回答")
        def submit():
            r=self._run(run_id);items=json.loads(r["items_json"])
            if r["status"]!="active" or items[r["position"]]!=item:raise JourneyPracticeConflict("当前题目已变化，请重新读取")
            self.conn.execute("INSERT INTO submissions(run_id,item_id,answer) VALUES (?,?,?)",(run_id,item,answer))
            status="completed" if r["position"]==len(items)-1 else "awaiting_next"
            self.conn.execute("UPDATE runs SET status=? WHERE run_id=?",(status,run_id))
            return self.state(run_id)
        return self._once("answer",body,submit)
    def next(self,body):
        run_id=body["run_id"]
        def advance():
            r=self._run(run_id)
            if r["status"]!="awaiting_next":raise JourneyPracticeConflict("请先完成当前题，或该练习已结束")
            self.conn.execute("UPDATE runs SET position=position+1,status='active' WHERE run_id=?",(run_id,))
            return self.state(run_id)
        return self._once("next",body,advance)
    def finish(self,body):
        run_id=body["run_id"]
        def finish_run():
            r=self._run(run_id)
            if r["status"] not in ("active","awaiting_next"):raise JourneyPracticeConflict("该练习已结束")
            self.conn.execute("UPDATE runs SET status='ended_early' WHERE run_id=?",(run_id,));return self.state(run_id)
        return self._once("finish",body,finish_run)
    def record_list(self,topic=None):
        history=records(self.data,topic)
        result=[]
        for r in history:
            if r["type"]=="learning":
                item=self._find("schedule","schedule_id",r["ref_id"]);title=self._find("tasks","task_id",item["task_id"])["title"]
            elif r["type"] in ("day_assessment","week_assessment"):
                item=self._find("assessments","assessment_id",r["ref_id"])
                title=" / ".join(self._find("tasks","task_id",x["task_id"])["title"] for x in item["scope_snapshot"]["items"])
            elif r["type"]=="retest":title=self._find("topics","topic_id",r["topic_ids"][0])["title"]+" · 固定复测"
            else:title="数据开发岗位 · 固定面试"
            result.append({**r,"origin":"curated_history","title":title})
        for event in self.conn.execute("SELECT event_id,task_id,created_at FROM learning_events ORDER BY created_at,event_id"):
            related=self._find("tasks","task_id",event["task_id"])["topic_ids"]
            if topic is None or topic in related:result.append({"record_id":event["event_id"],"type":"learning_update","title":self._find("tasks","task_id",event["task_id"])["title"],"created_at":event["created_at"].replace(" ","T")+"Z","topic_ids":related,"origin":"fixed_stub_practice"})
        for r in self.conn.execute("SELECT run_id,kind,template_id,status,created_at FROM runs ORDER BY created_at,run_id"):
            full=self._run(r["run_id"]);scope=json.loads(full["scope_json"])
            if r["kind"] in ("day","week"):
                tids=[x["task_id"] for x in scope["items"]];related=sorted({t for task in self.data["tasks"] if task["task_id"] in tids for t in task["topic_ids"]})
            elif r["kind"]=="retest":related=[scope["topic_id"]]
            else:related=scope["context_selection"]["learning_summary_topic_ids"]
            if r["kind"] in ("day","week"):title=" / ".join(self._find("tasks","task_id",tid)["title"] for tid in tids)
            elif r["kind"]=="retest":title=self._find("topics","topic_id",scope["topic_id"])["title"]+" · 专题练习"
            else:title="数据开发岗位 · 面试练习"
            if topic is None or topic in related:result.append({"record_id":r["run_id"],"type":r["kind"],"title":title,"status":r["status"],"created_at":r["created_at"].replace(" ","T")+"Z","topic_ids":related,"origin":"fixed_stub_practice"})
        result.sort(key=lambda item:(item.get("created_at",item.get("occurred_at","")),item["record_id"]))
        return {"records":result,"notice":"历史样例与本机固定替身练习分开标注；学习状态记录是历史案例截面。","source_kind":"fixed_stub"}
    def record_detail(self,record_id):
        for x in self.data["record_views"]:
            if x["record_id"]==record_id:
                kind=x["type"];ref=x["ref_id"]
                if kind=="learning":obj=self._find("schedule","schedule_id",ref)
                elif kind in ("day_assessment","week_assessment"):obj=self._find("assessments","assessment_id",ref)
                elif kind=="retest":obj=self._find("retests","retest_session_id",ref)
                else:obj=self._find("interviews","interview_id",ref)
                details={"origin":"curated_history","record":x,"detail":obj,"notice":"预存合成历史案例，不是本机练习结果。"}
                if kind in ("day_assessment","week_assessment","retest"):
                    qs=[q for q in self.data["questions"] if q["owner_id"]==ref and q["owner_type"]==("retest" if kind=="retest" else "assessment")]
                    details["questions"]=qs;details["attempts"]=[a for a in self.data["attempts"] if a["question_id"] in {q["question_id"] for q in qs}]
                    details["topic_evidence"]=[e for e in self.data["topic_evidence"] if e["attempt_id"] in {a["attempt_id"] for a in details["attempts"]}]
                return details
        event=self.conn.execute("SELECT task_id,snapshot_json,created_at FROM learning_events WHERE event_id=?",(record_id,)).fetchone()
        if event:return {"origin":"fixed_stub_practice","type":"learning_update","record_id":record_id,"progress":json.loads(event["snapshot_json"]),"created_at":event["created_at"].replace(" ","T")+"Z","notice":NOTICE}
        if isinstance(record_id,str) and record_id.startswith("LE-"):raise JourneyPracticeMissing("学习记录不存在")
        state=self.state(record_id);rows=self.conn.execute("SELECT item_id,answer FROM submissions WHERE run_id=? ORDER BY id",(record_id,)).fetchall()
        history=[]
        by_id={x["id"]:x for x in self._practice_items(self._run(record_id))}
        for row in rows:
            item=by_id[row["item_id"]]
            history.append({"item_id":row["item_id"],"answer":row["answer"],"question_text":item["text"],"topic_ids":item["topic_ids"]})
        return {"origin":"fixed_stub_practice","state":state,"answers":history,"notice":NOTICE}
