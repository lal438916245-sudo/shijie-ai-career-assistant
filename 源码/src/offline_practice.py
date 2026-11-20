"""固定替身的独立练习会话；禁止连接模型或冒充真实评分。"""
import json
import sqlite3
import uuid
from datetime import date
from pathlib import Path
from competition_sessions import create_session, session_info
from db_manager import DBManager
from variant_retest import VariantRetestService, RetestError, ensure_schema
from topic_contract import load_demo_topic_catalog, get_demo_topic

INPUT={"target_role":"数据开发工程师（固定替身练习）","resume_text":"合成案例具备 Python、基础 SQL 与离线报表练习经验，用于本地固定替身测试。","jd_text":"合成岗位要求实时计算、复杂 SQL、数据建模和工程测试，用于验证学习与复测流程。","available_days":14}
TOPICS={
 "stream":("实时计算","学习窗口、水位线与故障恢复","订单流出现迟到数据和故障，如何设计窗口推进与恢复？",55),
 "sql":("复杂 SQL","学习执行计划、倾斜和结果验证","订单关联后查询变慢，怎样先验证结果再定位热点？",58),
 "model":("数仓建模","学习事实粒度、维度和数据质量","订单事实表如何选择粒度并核验数据质量？",73),
 "engineering":("工程测试","学习测试案例、指标和告警","如何为数据链路设计故障恢复测试和关键指标？",52),
}
NOTICE="固定替身会话：题目与成绩用于流程测试，不评价本次回答，不代表真实能力或模型结果。"

_UNSET=object()

class PracticeError(ValueError): pass
class PracticeConflict(PracticeError): pass

def _marker(conn):
    try:
        row=conn.execute("SELECT session_id,trace_id,plan_id,fixture_version FROM offline_practice_meta WHERE singleton=1").fetchone()
        meta=session_info(conn)
        if not row or not meta or row[3]!=1 or (row[0],row[1],row[2])!=(meta["session_id"],meta["trace_id"],meta["plan_id"]): raise PracticeError("不是有效的固定替身会话")
        return {"session_id":row[0],"trace_id":row[1],"plan_id":row[2]}
    except sqlite3.Error as exc: raise PracticeError("不是有效的固定替身会话") from exc

def create_practice(directory,creation_token):
    """只创建新的固定输入会话；同 token 重开已标记会话，不接管其他数据库。"""
    catalog=load_demo_topic_catalog(Path(__file__).resolve().parents[1]/"examples/demo_replay/scenario_02")
    token=str(uuid.UUID(str(creation_token)));sid=uuid.uuid5(uuid.NAMESPACE_URL,"CareerPilot:"+token).hex
    directory=Path(directory).resolve()/"offline_fixture_sessions"
    expected=directory/f"session_{sid}.db";existed=expected.exists()
    if existed:
        c=sqlite3.connect(expected.as_uri()+"?mode=ro",uri=True)
        try:_marker(c)
        finally:c.close()
    info=create_session(directory,INPUT,token)
    db=DBManager(info["path"])
    try:
        ensure_schema(db.conn)
        db.conn.execute("BEGIN IMMEDIATE")
        if db.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='offline_practice_meta'").fetchone():
            marker=_marker(db.conn);db.conn.rollback();return {"path":info["path"],**marker,"notice":NOTICE}
        if existed:raise PracticeError("已有会话不是固定替身，拒绝修改")
        sid=info["session_id"];trace=info["trace_id"];plan="OFFLINE_PLAN_"+sid[:16];phase="OFFLINE_PHASE_"+sid[:16]
        db.conn.execute("CREATE TABLE offline_practice_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1), session_id TEXT NOT NULL, trace_id TEXT NOT NULL, plan_id TEXT NOT NULL, fixture_version INTEGER NOT NULL CHECK(fixture_version=1))")
        db.conn.execute("CREATE TABLE offline_practice_topics(topic_key TEXT PRIMARY KEY, gap_id TEXT NOT NULL UNIQUE, source_task_id INTEGER NOT NULL UNIQUE, root_question_id INTEGER NOT NULL UNIQUE)")
        db.conn.execute("CREATE TABLE offline_topic_tasks(topic_key TEXT NOT NULL REFERENCES offline_practice_topics(topic_key), source_task_id INTEGER NOT NULL UNIQUE REFERENCES study_tasks(id), PRIMARY KEY(topic_key,source_task_id))")
        db.conn.execute("CREATE TABLE offline_learning_records(source_task_id INTEGER PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('not_started','in_progress','completed')), note TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>=0), start_date TEXT, end_date TEXT, FOREIGN KEY(source_task_id) REFERENCES study_tasks(id))")
        db.insert_study_plan(plan_id=plan,overall_goal="固定替身多专题练习",total_days=14)
        db.insert_study_phase(phase_id=phase,plan_id=plan,phase_name="固定练习",phase_goal="验证记录与复测链",phase_order=1)
        for key,(title,content,question,_) in TOPICS.items():
            gap="OFFLINE_GAP_"+sid[:12]+"_"+key.upper()
            template=get_demo_topic(catalog,key);sources=[]
            for task in template.learning_tasks:
                db.insert_daily_task(plan,phase,"固定练习",{"day":task.day,"task_type":"理论学习","content":task.content,"expected_outcome":task.title,"gap_ids":[gap],"provenance_status":"linked"})
                sources.append(db.cursor.lastrowid)
            root=db.insert_exam_task(plan,phase,"固定练习",template.learning_tasks[0].day,question,focus=title,source_task_ids=sources,gap_ids=[gap],provenance_status="exam_linked",commit=False)
            db.conn.execute("INSERT INTO offline_practice_topics VALUES (?,?,?,?)",(key,gap,sources[0],root))
            for source in sources:
                db.conn.execute("INSERT INTO offline_topic_tasks VALUES (?,?)",(key,source))
                db.conn.execute("INSERT INTO offline_learning_records VALUES (?,'not_started','',0,NULL,NULL)",(source,))
        db.conn.execute("UPDATE competition_session SET plan_id=? WHERE singleton=1 AND plan_id IS NULL",(plan,))
        db.conn.execute("INSERT INTO offline_practice_meta VALUES (1,?,?,?,1)",(sid,trace,plan))
        db.conn.commit()
        return {"path":info["path"],"session_id":sid,"trace_id":trace,"plan_id":plan,"notice":NOTICE}
    except Exception:
        db.conn.rollback();raise
    finally:db.close()

def open_practice(path):
    """先以只读方式识别标记，避免 DBManager 迁移非演示数据库。"""
    path=Path(path).resolve()
    if not path.is_file():raise PracticeError("固定替身会话不存在")
    conn=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True)
    try:_marker(conn)
    finally:conn.close()
    db=DBManager(str(path))
    try:return OfflinePractice(db)
    except Exception:db.close();raise

class PracticeRetest(VariantRetestService):
    def prepare(self,parent_attempt_id):
        context=super().prepare(parent_attempt_id)
        if "existing_task_id" not in context:
            records=[]
            for task_id in context["source_task_ids"]:
                row=self.conn.execute("SELECT status,note,version FROM offline_learning_records WHERE source_task_id=?",(task_id,)).fetchone()
                if not row:raise PracticeError("来源学习记录不存在")
                records.append({"task_id":task_id,"status":row[0],"note_present":bool(row[1].strip()),"version":row[2]})
            parent=self.db.get_latest_assessment_attempt(context["parent_task_id"])
            if not parent or parent["id"]!=parent_attempt_id:raise PracticeError("请使用最新作答")
            context["fixture_learning"]=records
            context["fixture_parent_score"]=parent["final_score"]
        return context

def fixed_question(context):
    """依据最新固定评分及学习状态选预设题；不分析答案和笔记正文。"""
    first=context["round"]==1
    studied=any(r["status"]=="completed" for r in context["fixture_learning"])
    parent_passed=context["fixture_parent_score"]>=60
    if first and studied:text="已记录学习后请用一个新的业务情境，解释关键边界、验证步骤与故障处理依据。"
    elif first:text="尚未完成补学时，请先用一个新的业务情境说明关键概念，并指出仍需核实的边界。"
    elif parent_passed:text="上一次固定记录已通过；若输入条件变化，请说明验证顺序、取舍与失败后的处理。"
    else:text="上一次固定记录仍需补强；换一种场景解释薄弱概念与可以检查的证据。"
    return {"question":text,"focus":"固定替身："+("补学后变式" if studied else "当前学习状态变式"),"source_task_ids":context["source_task_ids"],"gap_ids":context["gap_ids"]}

def _fixture_receipt(result):
    """不要把演示成绩或原始答卷伪装为真实阅卷返回。"""
    return {"id":result["id"],"task_id":result["task_id"],"final_score":result["final_score"],"status":result["status"],"feedback":result["feedback"],"score_source":"fixed_stub","notice":NOTICE}

class FixedAssessor:
    def __init__(self,db,trace_id,score):self.db=db;self.trace_id=trace_id;self.score=score
    def grade_answer(self,task_id,question,answer,submission):
        score=self.score
        return self.db.save_assessment_attempt(task_id=task_id,trace_id=self.trace_id,question_text=question,answer_text=answer,model_score=score,final_score=score,score_source="rubric_weighted",status="completed" if score>=60 else "failed",rubric_json=[{"dimension":"fixture","score":score,"comment":"固定替身，不评价答案"}],rubric_definition_json=[{"key":"fixture","weight":100}],rubric_weight=100,feedback="固定替身回执：此分数与本次回答内容无关。",rag_hit=False,submission=submission)

class OfflinePractice:
    def __init__(self,db):
        self.db=db;self.conn=db.conn;self.meta=_marker(self.conn)
        self.service=PracticeRetest(db,self.meta["plan_id"],self.meta["trace_id"])
    def close(self):self.db.close()
    def _topic(self,key):
        row=self.conn.execute("SELECT topic_key,gap_id,source_task_id,root_question_id FROM offline_practice_topics WHERE topic_key=?",(key,)).fetchone()
        if not row:raise PracticeError("专题不存在")
        return dict(zip(("topic_key","gap_id","source_task_id","root_question_id"),row))
    def learning_items(self,key):
        self._topic(key)
        rows=self.conn.execute("SELECT t.source_task_id,r.status,r.note,r.version,r.start_date,r.end_date,s.day,s.content,s.expected_outcome FROM offline_topic_tasks t JOIN offline_learning_records r ON r.source_task_id=t.source_task_id JOIN study_tasks s ON s.id=t.source_task_id WHERE t.topic_key=? ORDER BY s.day,t.source_task_id",(key,)).fetchall()
        return [{"source_task_id":row[0],"status":row[1],"note":row[2],"version":row[3],"start_date":row[4],"end_date":row[5],"day":row[6],"content":row[7],"title":row[8]} for row in rows]
    def learning(self,key,task_id=None):
        topic=self._topic(key);target=topic["source_task_id"] if task_id is None else task_id
        matches=[row for row in self.learning_items(key) if row["source_task_id"]==target]
        if type(target) is not int or len(matches)!=1:raise PracticeError("学习记录不属于当前专题")
        return matches[0]
    def update_learning(self,key,status,note,expected_version,*,task_id=None,start_date=_UNSET,end_date=_UNSET):
        if status not in ("not_started","in_progress","completed") or not isinstance(note,str) or len(note)>1000 or type(expected_version) is not int or expected_version<0:raise PracticeError("学习状态、笔记或版本无效")
        t=self._topic(key);target=t["source_task_id"] if task_id is None else task_id
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            current=self.learning(key,target)
            start=current["start_date"] if start_date is _UNSET else start_date
            end=current["end_date"] if end_date is _UNSET else end_date
            if start is not None or end is not None:
                try:
                    if not isinstance(start,str) or not isinstance(end,str) or len(start)!=10 or len(end)!=10:raise ValueError()
                    first=date.fromisoformat(start);last=date.fromisoformat(end)
                    if first.isoformat()!=start or last.isoformat()!=end or not 2000<=first.year<=2100 or not 2000<=last.year<=2100 or not 0<=(last-first).days<=60:raise ValueError()
                except ValueError as exc:raise PracticeError("日期无效，需为有效起止日期且跨度不超过 61 天") from exc
            result=self.conn.execute("UPDATE offline_learning_records SET status=?,note=?,version=version+1,start_date=?,end_date=? WHERE source_task_id=? AND version=?",(status,note,start,end,target,expected_version))
            if result.rowcount!=1:raise PracticeConflict("学习记录已变化，请重新读取")
            self.conn.commit();return self.learning(key,target)
        except Exception:self.conn.rollback();raise
    def state(self,key):
        t=self._topic(key);links=[x for x in self.service._requests() if x["root_task_id"]==t["root_question_id"] and x["status"]=="ready"]
        ids=[t["root_question_id"]]+[x["child_task_id"] for x in links]
        all_attempts=[a for tid in ids for a in self.db.get_assessment_attempts(tid) if a["trace_id"]==self.meta["trace_id"]]
        all_attempts.sort(key=lambda x:x["id"])
        pending=next((self.db.get_task_by_id(tid) for tid in ids if not self.db.get_latest_assessment_attempt(tid)),None)
        latest=all_attempts[-1] if all_attempts else None
        mastery=next(x for x in self.service.mastery() if x["gap_id"]==t["gap_id"])
        if pending:actions=["submit"]
        elif mastery["state"]=="mastered":actions=["finish"]
        elif len(links)>=2:actions=["review_learning","finish"]
        elif latest and (latest["final_score"]<60 or links):actions=["review_learning","create_next","finish"]
        else:actions=["review_learning","finish"]
        def public_attempt(a):
            return {"id":a["id"],"score":a["final_score"],"feedback":a["feedback"]} if a else None
        return {"first_attempt":public_attempt(all_attempts[0] if all_attempts else None),"previous_attempt":public_attempt(all_attempts[-2] if len(all_attempts)>1 else None),"retest_round":len(links),"session_id":self.meta["session_id"],"topic_key":key,"learning":self.learning(key),"learning_items":self.learning_items(key),"current_question":{"id":pending["id"],"text":pending["content"],"source_kind":"fixed_stub","notice":NOTICE} if pending else None,"latest_attempt":{"id":latest["id"],"score":latest["final_score"],"feedback":latest["feedback"]} if latest else None,"mastery":mastery,"actions":actions,"source_kind":"fixed_stub","notice":NOTICE}
    def submit(self,key,question_id,answer):
        if type(question_id) is not int or question_id<1 or not isinstance(answer,str) or not answer.strip() or len(answer)>6000:raise PracticeError("请填写有效题目和不超过 6000 字的回答")
        t=self._topic(key);state=self.state(key);current=state["current_question"]
        if not current or current["id"]!=question_id:
            known=[t["root_question_id"]]+[x["child_task_id"] for x in self.service._requests() if x["root_task_id"]==t["root_question_id"] and x["status"]=="ready"]
            previous=self.db.get_latest_assessment_attempt(question_id) if question_id in known else None
            if not previous or previous["answer_text"]!=answer.strip():raise PracticeError("该题不是当前待作答题目")
            return _fixture_receipt(self.service.grade_pending(question_id,answer,lambda:(_ for _ in ()).throw(PracticeError("不应重复阅卷"))))
        relation=next((x for x in self.service._requests() if x["child_task_id"]==question_id),None)
        score=(({1:72,2:82} if key=="stream" else {1:66,2:54})[relation["round"]]) if relation else TOPICS[key][3]
        return _fixture_receipt(self.service.grade_pending(question_id,answer,lambda:FixedAssessor(self.db,self.meta["trace_id"],score)))
    def create_next(self,key,parent_attempt_id):
        if type(parent_attempt_id) is not int or parent_attempt_id<1:raise PracticeError("请使用有效的父作答身份")
        t=self._topic(key);state=self.state(key)
        if state["current_question"]:
            match=next((x for x in self.service._requests() if x["root_task_id"]==t["root_question_id"] and x["parent_attempt_id"]==parent_attempt_id and x["child_task_id"]==state["current_question"]["id"] and x["status"]=="ready"),None)
            if match:return state["current_question"]
            raise PracticeError("先完成当前题目，不能提前创建下一题")
        if "create_next" not in state["actions"] or not state["latest_attempt"] or state["latest_attempt"]["id"]!=parent_attempt_id:raise PracticeError("当前不能创建下一题，请查看最新状态")
        child=self.service.generate(parent_attempt_id,fixed_question)
        return {"id":child["id"],"text":child["content"],"source_kind":"fixed_stub","notice":NOTICE}
