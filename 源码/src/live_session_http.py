"""Local-only adapter for the real session workflow with injected test doubles.

This module deliberately does not wire a model client or expose a launcher. All
results and databases produced here are marked local_double and isolated in a
dedicated directory. A production model adapter needs its own provenance and
consent boundary before it can be enabled.
"""
from contextlib import closing
import hashlib
import hmac
import json
import re
import sqlite3
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from competition_sessions import (SessionBusy, SessionError, SessionPlanError, SessionDiagnosisError, SessionInput,
                                  SessionWorkflow, completed_result, create_session,
                                  session_info, stage_records)
from db_manager import DBManager
from mastery_service import json_list
from model_preparation import ModelPreparation, PreparationError, PreparationConflict
from workflow_lease import DirectoryLease
from authorized_ab import AuthorizedAB, FixedABTransport, ABConflict

_SECRET = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BODY = 400_000
_ORIGIN = "local_workflow_double"


class AdapterError(ValueError):
    pass


class AdapterMissing(AdapterError):
    pass


class LocalWorkflowServer(ThreadingHTTPServer):
    """Explicit dependency injection only; never constructs a real model client."""
    daemon_threads = True
    session_subdirectory='live_adapter_stub_sessions'
    session_namespace='CareerPilotLiveAdapterDouble:'
    source_kind=_ORIGIN
    source_notice='本地替身演示，不调用模型，不代表个人能力。'
    authorization_class=AuthorizedAB
    handler_class=None

    def __init__(self, address, directory, origins, access_key, *, hunter_factory, planner_factory, configuration_vault=None, ab_transport=None, ced_sdk_rehearsal=False, workbench_case_profile='legacy', contract_sdk_rehearsal=False,session_outbound_enabled=False):
        if address[0] != "127.0.0.1":
            raise ValueError("只能监听本机回环地址")
        if not isinstance(access_key, str) or not _SECRET.fullmatch(access_key):
            raise ValueError("服务访问密钥必须为 32 字节随机十六进制")
        if not callable(hunter_factory) or not callable(planner_factory):
            raise ValueError("必须显式注入本地替身")
        self.directory = (Path(directory).resolve() / self.session_subdirectory).resolve()
        self.origins = frozenset(origins)
        self.access_key = access_key
        self.hunter_factory = hunter_factory
        self.planner_factory = planner_factory
        self.creation_lock = threading.Lock()
        self.guard = threading.RLock()
        self.active = set()
        self.reservations = {}
        self.active_authorizations = set()
        self.ab_transport = ab_transport or FixedABTransport()
        if not isinstance(self.ab_transport,FixedABTransport):
            raise ValueError("本轮只允许固定本地请求替身")
        self.boot_id = str(uuid.uuid4())
        if type(ced_sdk_rehearsal) is not bool:
            raise ValueError("C/E/D SDK 预演开关必须为布尔值")
        if workbench_case_profile not in ('legacy','final-20261107'):raise ValueError('Unknown workbench case')
        self.workbench_case_profile=workbench_case_profile
        self.ced_sdk_rehearsal = ced_sdk_rehearsal
        if type(contract_sdk_rehearsal) is not bool:raise ValueError('Invalid contract SDK rehearsal flag')
        self.contract_sdk_rehearsal=contract_sdk_rehearsal
        if type(session_outbound_enabled) is not bool:raise ValueError("Invalid session outbound flag")
        self.session_outbound_enabled=session_outbound_enabled
        self.preparation = ModelPreparation(Path(directory).resolve(), configuration_vault)
        self.lease = DirectoryLease(directory)
        try:
            super().__init__(address, self.handler_class or LocalWorkflowHandler)
        except Exception:
            self.lease.close()
            raise

    def server_close(self):
        # Call after shutdown, and only release the lease when local workers stop.
        with self.guard:
            if self.active or self.reservations or self.active_authorizations:
                raise RuntimeError("工作流仍在执行，不能释放目录锁")
            super().server_close()
            self.lease.close()

    def recovery_info(self, path, stage, conn):
        key=(str(path),stage)
        with self.guard:
            if key in self.active or key in self.reservations:
                return {"recovery_available":False,"recovery_reason":"当前步骤仍在运行，请先重新读取状态"}
            try:
                row=conn.execute("SELECT attempt_id,protected FROM local_adapter_workers WHERE stage=?",(stage,)).fetchone()
            except sqlite3.Error:
                row=None
            if not row or row[1]!=1:
                return {"recovery_available":False,"recovery_reason":"旧执行者没有受目录锁保护的记录，无法安全自动恢复，需人工检查"}
            return {"recovery_available":True,"recovery_id":row[0],"recovery_reason":"目录锁已取得且当前无该步骤的执行者，可恢复为失败；不会自动重新执行"}


    def session_path(self, token):
        if not isinstance(token, str) or not _SECRET.fullmatch(token):
            raise AdapterError("会话身份无效")
        # Keep the browser's high-entropy token out of filenames and API responses.
        creation = uuid.uuid5(uuid.NAMESPACE_URL, self.session_namespace + token)
        sid = uuid.uuid5(uuid.NAMESPACE_URL, "CareerPilot:" + str(creation)).hex
        return self.directory / f"session_{sid}.db", creation


class LocalWorkflowHandler(BaseHTTPRequestHandler):
    server_version = "CareerPilotLocalWorkflow/1"

    def log_message(self, *args):
        pass  # no input text, paths, token, headers or response bodies in access logs

    def reply(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def reject_request(self,status,payload):
        # Windows can reset a socket closed with an unread request body before
        # the caller receives its 403/404/409. Drain only a bounded declared body.
        if getattr(self,"command",None)=="POST":
            try:
                length=int(self.headers.get("Content-Length","0"))
                if 0<length<=_MAX_BODY:
                    self.connection.settimeout(2)
                    self.rfile.read(length)
            except (ValueError,OSError):pass
            self.close_connection=True
        return self.reply(status,payload)

    def authorized(self, write=False):
        origin = self.headers.get("Origin")
        supplied = self.headers.get("X-CP-Local-Key", "")
        return (self.headers.get("Host", "") == f"127.0.0.1:{self.server.server_port}"
                and hmac.compare_digest(supplied, self.server.access_key)
                and (origin in self.server.origins if write else origin is None or origin in self.server.origins))

    def token(self):
        value = self.headers.get("X-CP-Session", "")
        if not _SECRET.fullmatch(value):
            raise AdapterError("会话身份无效")
        return value

    def body(self):
        if self.headers.get_content_type() != "application/json":
            raise AdapterError("需要 JSON 请求")
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if length < 0 or length > _MAX_BODY:
                raise ValueError()
        except ValueError:
            raise AdapterError("请求长度无效") from None

        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate")
                value[key] = item
            return value

        try:
            result = json.loads(self.rfile.read(length).decode("utf-8"), object_pairs_hook=unique)
        except (ValueError, UnicodeError):
            raise AdapterError("请求内容无效") from None
        if not isinstance(result, dict):
            raise AdapterError("请求内容无效")
        return result

    def checked_path(self, token):
        path, _ = self.server.session_path(token)
        if path.is_symlink() or not path.is_file() or path.resolve().parent != self.server.directory:
            raise AdapterMissing("会话不存在或不可用")
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
                meta = session_info(conn)
                mark = conn.execute("SELECT source_kind,token_digest FROM local_adapter_identity WHERE singleton=1").fetchone()
                digest = hashlib.sha256(token.encode("ascii")).hexdigest()
                if not meta or not mark or mark[0] != self.server.source_kind or not hmac.compare_digest(mark[1], digest):
                    raise AdapterMissing("会话不存在或不可用")
        except sqlite3.Error:
            raise AdapterMissing("会话不存在或不可用") from None
        return path

    def create(self, token, body):
        # Validate before creating directories or touching a database.
        inputs = SessionInput.model_validate(body).model_dump(exclude_none=True)
        path, creation = self.server.session_path(token)
        with self.server.creation_lock:
            if path.exists() or path.is_symlink():
                self.checked_path(token)  # never take over an unmarked or foreign DB
            result = create_session(self.server.directory, inputs, creation)
            if Path(result["path"]).resolve() != path:
                raise AdapterError("会话路径无效")
            # create_session has already committed. A crash before this marker is
            # deliberately not auto-recovered: an unmarked file is never adopted.
            with closing(sqlite3.connect(path)) as conn:
                with conn:
                    conn.execute("CREATE TABLE IF NOT EXISTS local_adapter_identity "
                                 "(singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                                 "source_kind TEXT NOT NULL, token_digest TEXT NOT NULL)")
                    conn.execute("INSERT OR IGNORE INTO local_adapter_identity VALUES (1,?,?)",
                                 (self.server.source_kind, hashlib.sha256(token.encode("ascii")).hexdigest()))
            self.checked_path(token)
        return self.read(token, "session")

    def read(self, token, kind):
        path = self.checked_path(token)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
            meta = session_info(conn)
            stages = [{"stage": x["stage"], "status": x["status"],
                       "error_type": x["error_type"], "model_name": x["model_name"],
                       **({"validation_error":json.loads(x["validation_json"])} if x.get("validation_json") else {})}
                      for x in stage_records(conn)]
            for item in stages:
                if item["status"]=="generating":item.update(self.server.recovery_info(path,item["stage"],conn))
            common = {"source_kind": self.server.source_kind, "notice": self.server.source_notice}
            if kind == "session":
                return {**common, "session_id": meta["session_id"], "trace_id": meta["trace_id"],
                        "report_id": meta["report_id"], "plan_id": meta["plan_id"],
                        "target_role": meta["inputs"]["target_role"],
                        "available_days": meta["inputs"]["available_days"], "stages": stages,
                        **({"learning_preferences":meta["inputs"]["learning_preferences"]} if meta["inputs"].get("learning_preferences") is not None else {})}
            result = completed_result(conn, kind)
            stage = next((s for s in stages if s["stage"] == kind), None)
            data = {**common, "status": stage["status"] if stage else "not_started", "result": result}
            if stage and stage.get("validation_error"):
                data["validation_error"] = stage["validation_error"]
            if stage:data.update({k:v for k,v in stage.items() if k.startswith("recovery_")})
            if kind == "plan" and result:
                conn.row_factory = sqlite3.Row
                tasks = conn.execute("SELECT id,day,seq,content,expected_outcome,gap_ids,provenance_status "
                                     "FROM study_tasks WHERE plan_id=? AND task_type NOT LIKE '考察%' "
                                     "ORDER BY day,seq", (meta["plan_id"],)).fetchall()
                data["tasks"] = [{**dict(t), "gap_ids": json_list(t["gap_ids"])} for t in tasks]
                if result['plan'].get('plan_version')=='daily-learning-v1':
                    from learning_progress import read_progress
                    generated={t['day']:t for p in result['plan']['phases'] for t in p['tasks']}
                    progress=read_progress(conn,[t['id'] for t in data['tasks']])
                    skills={g['gap_id']:g['skill'] for g in completed_result(conn,'diagnosis')['gaps']}
                    data['deferred_gap_display']=[{**g,'skill':skills[g['gap_id']]} for g in result['plan']['deferred_gaps']]
                    for task in data['tasks']:
                        source=generated[task['day']]
                        task.update({k:source[k] for k in ('time_budget','guide','tiers')})
                        task['progress']=progress[task['id']]

            return data

    def update_plan_progress(self, token, body):
        from learning_progress import update_progress,ProgressConflict
        if set(body)!={'task_id','status','reason','expected_revision'}:raise AdapterError('学习状态字段无效')
        path=self.checked_path(token)
        with self.server.guard,closing(sqlite3.connect(path)) as conn:
            result=completed_result(conn,'plan')
            if not result or result['plan'].get('plan_version')!='daily-learning-v1':raise AdapterError('当前计划没有每日学习合同；不会自动改写旧计划')
            try:update_progress(conn,result['plan_id'],body['task_id'],body['status'],body['reason'],body['expected_revision'])
            except ProgressConflict as exc:raise ABConflict(str(exc)) from None
        return self.read(token,'plan')

    def execute(self, token, stage, *, authorized_factory=None, authorization_id=None):
        path = self.checked_path(token)
        key=(str(path),stage)
        with self.server.guard:
            reserved=self.server.reservations.get(key)
            if key in self.server.active or (reserved and reserved!=authorization_id):raise SessionBusy("步骤仍在运行")
            if authorized_factory is not None and (reserved!=authorization_id or authorization_id not in self.server.active_authorizations):raise ABConflict("缺少已消费的单次授权")
            with closing(sqlite3.connect(path)) as conn:
                current=next((x for x in stage_records(conn) if x["stage"]==stage),None)
                if current and current["status"]=="generating":raise SessionBusy("请先查询或安全恢复")
                if current and current["status"]=="completed":return self.read(token,stage)
                with conn:
                    conn.execute("CREATE TABLE IF NOT EXISTS local_adapter_workers(stage TEXT PRIMARY KEY,attempt_id TEXT NOT NULL,boot_id TEXT NOT NULL,protected INTEGER NOT NULL)")
                    if "authorization_id" not in {r[1] for r in conn.execute("PRAGMA table_info(local_adapter_workers)")}:
                        conn.execute("ALTER TABLE local_adapter_workers ADD COLUMN authorization_id TEXT")
                    conn.execute("INSERT INTO local_adapter_workers(stage,attempt_id,boot_id,protected,authorization_id) VALUES (?,?,?,1,?) ON CONFLICT(stage) DO UPDATE SET attempt_id=excluded.attempt_id,boot_id=excluded.boot_id,protected=1,authorization_id=excluded.authorization_id",(stage,str(uuid.uuid4()),self.server.boot_id,authorization_id))
            self.server.reservations.pop(key,None)
            self.server.active.add(key)
        db=None
        try:
            db = DBManager(str(path));workflow = SessionWorkflow(db)
            if stage == "diagnosis":workflow.diagnose(lambda: (authorized_factory or self.server.hunter_factory)(db))
            else:workflow.generate_plan(lambda: (authorized_factory or self.server.planner_factory)(db))
        finally:
            try:
                if db is not None:db.close()
            finally:
                with self.server.guard:self.server.active.discard(key)
        return self.read(token, stage)

    def recover(self,token,body):
        if set(body)!={"stage","recovery_id"} or body["stage"] not in ("diagnosis","plan") or not isinstance(body["recovery_id"],str):raise AdapterError("恢复请求无效")
        stage=body["stage"];path=self.checked_path(token)
        with self.server.guard:
            with closing(sqlite3.connect(path.as_uri()+"?mode=ro",uri=True)) as conn:
                current=next((x for x in stage_records(conn) if x["stage"]==stage),None)
                if not current or current["status"]!="generating":raise SessionError("步骤状态已变化，请重新读取")
                info=self.server.recovery_info(path,stage,conn)
                if not info["recovery_available"] or info["recovery_id"]!=body["recovery_id"]:raise SessionBusy("无法确认旧执行者已停止，请重新读取")
            db=DBManager(str(path))
            try:SessionWorkflow(db).recover_interrupted(stage,worker_stopped=True)
            finally:db.close()
        return self.read(token,stage)

    def call_preview(self,token,body):
        if set(body)!={"stage"}:raise AdapterError("预览请求无效")
        path=self.checked_path(token)
        with closing(sqlite3.connect(path.as_uri()+"?mode=ro",uri=True)) as conn:
            return self.server.preparation.preview(body["stage"],session_info(conn),completed_result(conn,"diagnosis"))

    def do_OPTIONS(self):
        self.reply(403, {"error": "请求来源不可用"})

    def do_GET(self):
        if not self.authorized():
            return self.reply(403, {"error": "请求来源不可用"})
        try:
            parsed = urlsplit(self.path)
            from competition_workbench_http import handle as handle_workbench
            if handle_workbench(self,parsed):return
            if not parsed.query and parsed.path=="/api/live/ab/latest":
                return self.reply(200,{"data":self.server.authorization_class(self).latest(self.token())})
            if not parsed.query and parsed.path=="/api/live/model-config":
                return self.reply(200,{"data":self.server.preparation.status()})
            if parsed.query or parsed.path not in {"/api/live/session", "/api/live/diagnosis", "/api/live/plan"}:
                return self.reply(404, {"error": "接口不存在"})
            self.reply(200, {"data": self.read(self.token(), parsed.path.rsplit("/", 1)[-1])})
        except PreparationError as exc:
            self.reply(400,{"error":str(exc),"code":"configuration"})
        except AdapterMissing:
            self.reply(404, {"error": "会话不存在或不可用", "code": "not_found"})
        except (AdapterError, ValueError, TypeError):
            self.reply(400, {"error": "请求内容无效", "code": "invalid"})
        except (OSError, sqlite3.Error):
            self.reply(503, {"error": "本地会话暂不可用", "code": "unavailable"})

    def do_POST(self):
        if not self.authorized(write=True):
            # Close rather than leave unread user-supplied bytes on a keep-alive connection.
            self.close_connection = True
            return self.reject_request(403, {"error": "请求来源不可用"})
        try:
            parsed = urlsplit(self.path)
            from competition_workbench_http import handle as handle_workbench
            if handle_workbench(self,parsed,write=True):return
            if parsed.query or parsed.path not in {"/api/live/plan-progress", "/api/live/session", "/api/live/diagnosis", "/api/live/plan", "/api/live/model-config", "/api/live/call-preview", "/api/live/recover", "/api/live/ab/preview", "/api/live/ab/authorize", "/api/live/ab/execute", "/api/live/ab/status"}:
                return self.reject_request(404, {"error": "接口不存在"})
            body = self.body()
            if parsed.path=="/api/live/model-config":return self.reply(200,{"data":self.server.preparation.save(body)})
            token = self.token()
            if parsed.path.startswith("/api/live/ab/"):
                action=parsed.path.rsplit("/",1)[-1]
                return self.reply(200,{"data":getattr(self.server.authorization_class(self),action)(token,body)})
            if parsed.path=="/api/live/call-preview":return self.reply(200,{"data":self.call_preview(token,body)})
            if parsed.path=="/api/live/recover":return self.reply(200,{"data":self.recover(token,body)})
            if parsed.path=="/api/live/plan-progress":return self.reply(200,{"data":self.update_plan_progress(token,body)})
            kind = parsed.path.rsplit("/", 1)[-1]
            if kind != "session" and body:
                raise AdapterError("请求字段无效")
            result = self.create(token, body) if kind == "session" else self.execute(token, kind)
            self.reply(200, {"data": result})
        except ABConflict as exc:
            self.reply(409,{"error":str(exc),"code":"request_conflict"})
        except PreparationConflict as exc:
            self.reply(409,{"error":str(exc),"code":"configuration_conflict"})
        except PreparationError as exc:
            self.reply(400,{"error":str(exc),"code":"configuration"})
        except AdapterMissing:
            self.reply(404, {"error": "会话不存在或不可用", "code": "not_found"})
        except SessionBusy:
            self.reply(409, {"error": "步骤正在执行或会话初始化中，请稍后读取状态", "code": "busy"})
        except (SessionPlanError, SessionDiagnosisError) as exc:
            self.reply(409, {'error':str(exc),'code':'validation','validation_error':exc.validation_error})
        except SessionError:
            self.reply(409, {"error": "步骤前置条件未满足、输入冲突或结果不完整", "code": "conflict"})
        except (AdapterError, ValueError, TypeError, KeyError):
            self.reply(400, {"error": "请求内容无效或结果未通过校验", "code": "invalid"})
        except TimeoutError:
            self.reply(503, {"error":"响应超时，结果未确认；请先重新读取状态，核对后再手动重试。真实调用失败也可能计费。","code":"unavailable","failure_kind":"timeout","automatic_retry":False})
        except (OSError, sqlite3.Error):
            self.reply(503, {"error": "本地会话暂不可用，请先重新读取确认保存状态", "code": "unavailable"})
        except Exception as exc:
            # Do not leak upstream exception messages, input text or credentials.
            kind={"TimeoutError":"timeout","APITimeoutError":"timeout","AuthenticationError":"authentication","RateLimitError":"rate_limit","APIConnectionError":"connection"}.get(type(exc).__name__,"unknown")
            message={"authentication":"密钥或服务商授权未通过，请检查配置；已有结果保留。","rate_limit":"服务商可能限流或额度不足，请核对后再手动重试；已有结果保留。","connection":"服务连接失败，请先核对状态与服务地址；已有结果保留。"}.get(kind,"步骤未完成，已有结果已保留；请先重新读取，核对后再手动重试。真实调用失败也可能计费。")
            self.reply(503, {"error": message, "code": "unavailable", "failure_kind":kind,"automatic_retry":False})
