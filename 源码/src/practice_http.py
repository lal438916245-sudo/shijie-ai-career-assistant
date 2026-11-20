"""Local-only HTTP bridge for isolated fixed-stub practice sessions."""
import json
import sqlite3
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from offline_practice import create_practice, open_practice, PracticeError, PracticeConflict, TOPICS
from variant_retest import RetestError, RetestBusy
from journey_practice import create as create_journey, open_session as open_journey, JourneyPracticeError, JourneyPracticeConflict, JourneyPracticeMissing
from learning_journey_demo import JourneyError

class PracticeServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,directory,origins):
        if address[0]!="127.0.0.1": raise ValueError("只能监听本机回环地址")
        self.directory=Path(directory).resolve();self.origins=frozenset(origins)
        super().__init__(address,Handler)

class Handler(BaseHTTPRequestHandler):
    server_version="CareerPilotFixture/1"
    def log_message(self,*args): pass  # Never log tokens, answers, notes or URLs.
    def reply(self,status,data):
        raw=json.dumps(data,ensure_ascii=False).encode("utf-8")
        self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
    def authorized(self,write=False):
        host=self.headers.get("Host","");expected=f"127.0.0.1:{self.server.server_port}"
        origin=self.headers.get("Origin")
        return host==expected and self.headers.get("X-CP-Local")=="fixed-stub-v1" and (origin in self.server.origins if write else origin is None or origin in self.server.origins)
    def token(self):
        try:return str(uuid.UUID(self.headers.get("X-Practice-Token","")))
        except ValueError:raise PracticeError("练习会话身份无效")
    def session_path(self,token):
        sid=uuid.uuid5(uuid.NAMESPACE_URL,"CareerPilot:"+token).hex
        return self.server.directory/"offline_fixture_sessions"/f"session_{sid}.db"
    def body(self):
        if self.headers.get_content_type()!="application/json":raise PracticeError("需要 JSON 请求")
        try:length=int(self.headers.get("Content-Length","-1"))
        except ValueError:raise PracticeError("请求长度无效")
        if length<0 or length>32768:raise PracticeError("请求内容过长")
        def pairs(items):
            result={}
            for key,item in items:
                if key in result:raise ValueError("duplicate")
                result[key]=item
            return result
        try:value=json.loads(self.rfile.read(length).decode("utf-8"),object_pairs_hook=pairs)
        except (ValueError,UnicodeError):raise PracticeError("请求内容无效")
        if not isinstance(value,dict):raise PracticeError("请求内容无效")
        return value
    @staticmethod
    def fields(value,required,optional=()):
        if not set(required)<=set(value) or not set(value)<=set(required)|set(optional):raise PracticeError("请求字段无效")
    def do_OPTIONS(self):self.reply(403,{"error":"请求来源不可用"})
    def do_GET(self):
        if not self.authorized():return self.reply(403,{"error":"请求来源不可用"})
        parsed=urlsplit(self.path)
        if parsed.path=="/api/practice/health":return self.reply(200,{"status":"ready","mode":"fixed_stub"})
        if parsed.path.startswith("/api/practice/journey/"):return self.journey_get(parsed)
        if parsed.path!="/api/practice/state":return self.reply(404,{"error":"接口不存在"})
        try:
            query=parse_qs(parsed.query,strict_parsing=True)
            if set(query)!={"topic"} or len(query["topic"])!=1:raise PracticeError("请选择有效专题")
            if query["topic"][0] not in TOPICS:raise PracticeError("请选择有效专题")
            practice=open_practice(self.session_path(self.token()))
            try:result=practice.state(query["topic"][0])
            finally:practice.close()
            self.reply(200,{"state":result})
        except PracticeError as exc:self.reply(404,{"error":str(exc),"code":"not_found"})
        except (ValueError,KeyError):self.reply(400,{"error":"请求内容无效"})
        except (OSError,sqlite3.Error):self.reply(503,{"error":"本地练习服务暂不可用，请重试"})
    def do_POST(self):
        if not self.authorized(write=True):
            # Drain a small declared body before responding; Windows may reset a
            # connection with unread request bytes before the client sees 403.
            try:
                length=int(self.headers.get("Content-Length","0"))
                if 0<length<=32768:
                    self.connection.settimeout(2)
                    self.rfile.read(length)
            except (ValueError,OSError):pass
            return self.reply(403,{"error":"请求来源不可用"})
        try:
            parsed=urlsplit(self.path)
            if parsed.query:raise PracticeError("请求地址无效")
            if parsed.path.startswith("/api/practice/journey/"):return self.journey_post(parsed)
            body=self.body();token=self.token()
            if parsed.path=="/api/practice/session":
                self.fields(body,())
                created=create_practice(self.server.directory,token)
                return self.reply(200,{"session_id":created["session_id"],"source_kind":"fixed_stub","notice":created["notice"]})
            if parsed.path not in ("/api/practice/learning","/api/practice/submit","/api/practice/next"):return self.reply(404,{"error":"接口不存在"})
            fields={"/api/practice/learning":(("topic","task_id","status","note","expected_version"),("start_date","end_date")),"/api/practice/submit":(("topic","question_id","answer"),()),"/api/practice/next":(("topic","parent_attempt_id"),())}
            required,optional=fields[parsed.path];self.fields(body,required,optional)
            topic=body["topic"]
            if not isinstance(topic,str) or topic not in TOPICS:raise PracticeError("请选择有效专题")
            practice=open_practice(self.session_path(token))
            try:
                if parsed.path.endswith("/learning"):
                    kwargs={key:body[key] for key in optional if key in body};result=practice.update_learning(topic,body["status"],body["note"],body["expected_version"],task_id=body["task_id"],**kwargs)
                elif parsed.path.endswith("/submit"):result=practice.submit(topic,body["question_id"],body["answer"])
                else:result=practice.create_next(topic,body["parent_attempt_id"])
                state=practice.state(topic)
            finally:practice.close()
            self.reply(200,{"result":result,"state":state})
        except (PracticeConflict,RetestBusy):self.reply(409,{"error":"记录已变化或请求正在执行，请重新读取后重试","code":"conflict"})
        except (PracticeError,RetestError) as exc:self.reply(400,{"error":str(exc),"code":"invalid"})
        except (ValueError,KeyError,TypeError):self.reply(400,{"error":"请求内容无效"})
        except (OSError,sqlite3.Error):self.reply(503,{"error":"本地练习服务暂不可用，请重试"})

    def journey_get(self,parsed):
        try:
            query=parse_qs(parsed.query,strict_parsing=True);path=parsed.path.rsplit("/",1)[-1]
            allowed={"catalog":(),"learning":("task_id",),"run":("run_id",),"records":(),"record":("record_id",)}
            if path not in allowed:return self.reply(404,{"error":"接口不存在"})
            required=allowed[path];optional=("topic",) if path=="records" else ()
            self.fields(query,required,optional)
            if any(len(v)!=1 for v in query.values()):raise JourneyPracticeError("请求参数无效")
            session=open_journey(self.server.directory,self.token())
            try:
                if path=="catalog":value=session.catalog()
                elif path=="learning":value=session.learning(query["task_id"][0])
                elif path=="run":value=session.state(query["run_id"][0])
                elif path=="records":value=session.record_list(query.get("topic",[None])[0])
                else:value=session.record_detail(query["record_id"][0])
            finally:session.close()
            return self.reply(200,{"data":value})
        except JourneyPracticeMissing as exc:return self.reply(404,{"error":str(exc),"code":"not_found"})
        except (JourneyPracticeError,PracticeError,JourneyError,ValueError,KeyError,TypeError) as exc:return self.reply(400,{"error":str(exc),"code":"invalid"})
        except (OSError,sqlite3.Error):return self.reply(503,{"error":"本地练习服务暂不可用，请重试"})

    def journey_post(self,parsed):
        try:
            path=parsed.path.rsplit("/",1)[-1];body=self.body();token=self.token()
            required={"session":(),"learning":("task_id","status","note","expected_version","start_date","end_date","request_id"),"start":("kind","template_id","request_id"),"answer":("run_id","item_id","answer","request_id"),"next":("run_id","request_id"),"finish":("run_id","request_id")}
            if path not in required:return self.reply(404,{"error":"接口不存在"})
            self.fields(body,required[path])
            if path=="session":return self.reply(200,{"data":create_journey(self.server.directory,token)})
            session=open_journey(self.server.directory,token)
            try:
                method={"learning":session.update_learning,"start":session.start,"answer":session.answer,"next":session.next,"finish":session.finish}[path]
                value=method(body)
            finally:session.close()
            return self.reply(200,{"data":value})
        except JourneyPracticeMissing as exc:return self.reply(404,{"error":str(exc),"code":"not_found"})
        except JourneyPracticeConflict as exc:return self.reply(409,{"error":str(exc),"code":"conflict"})
        except (JourneyPracticeError,PracticeError,JourneyError,ValueError,KeyError,TypeError) as exc:return self.reply(400,{"error":str(exc),"code":"invalid"})
        except (OSError,sqlite3.Error):return self.reply(503,{"error":"本地练习服务暂不可用，请重试"})
