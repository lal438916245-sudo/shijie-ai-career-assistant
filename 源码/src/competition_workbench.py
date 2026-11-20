"""Session-bound competition workbench. All producers are in-process doubles.

Own session directory/tables; legacy and real-model DBs are never opened here.
"""
from contextlib import closing
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
import threading
import uuid

from competition_case import CaseContractError, load_package, validate_package, resolve_selection, validate_handoff, validate_source
from workbench_learning_cards import follow_along_card
from workbench_learning_evidence import WorkbenchLearningEvidence, ARTIFACT_OPERATIONS, artifact_definition
from competition_sessions import create_session, session_info, completed_result, stage_records, SessionWorkflow
from competition_workbench_fixtures import (fixed_hunter, make_bindings, fixed_plan, fixed_review,
    budget_total, bound_id)

from competition_workbench_assessment import WorkbenchAssessment,OPERATIONS
from competition_workbench_interview import WorkbenchInterview,INTERVIEW_OPERATIONS
from competition_workbench_resume import WorkbenchResume,RESUME_OPERATIONS
from competition_workbench_calls import WorkbenchCalls
from workbench_candidate_adoption import WorkbenchCandidateAdoption, ADOPTION_OPERATIONS
from workbench_abf import WorkbenchABF,ABF_OPERATIONS
from workbench_ce import WorkbenchCE,CE_OPERATIONS

from workbench_session_runtime import WorkbenchSessionRuntime,RUNTIME_OPERATIONS
from workbench_saved_b import WorkbenchSavedB,OPERATIONS as SAVED_B_OPERATIONS
from workbench_plan_confirmation import WorkbenchPlanConfirmation,OPERATIONS as CONFIRM_OPERATIONS

SOURCE='competition_workbench_double'
TOKEN=re.compile(r'[0-9a-f]{64}\Z')
SCOPE=('case_id','session_id','trace_id','plan_id')


class WorkbenchError(ValueError):
    status=400
    code='invalid'


class WorkbenchMissing(WorkbenchError):
    status=404
    code='not_found'


class WorkbenchConflict(WorkbenchError):
    status=409
    code='conflict'


def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def expect(value,message):
    if not value:
        raise WorkbenchConflict(message)


def integer(value):
    return type(value) is int and value>=0


def identifier(value):
    try:
        if not isinstance(value,str):raise ValueError()
        return str(uuid.UUID(value))
    except (ValueError,TypeError,AttributeError):
        raise WorkbenchError('请求身份无效。') from None


def require_fields(body, fields):
    if not isinstance(body,dict) or set(body)!=set(fields):
        raise WorkbenchError('请求字段不完整或包含不支持的内容。')


class WorkbenchConnection(sqlite3.Connection):
    """Request-local validated-view cache, discarded when this connection closes."""


class CompetitionWorkbench(WorkbenchPlanConfirmation,WorkbenchSavedB,WorkbenchSessionRuntime,WorkbenchCE,WorkbenchABF,WorkbenchCandidateAdoption,WorkbenchLearningEvidence,WorkbenchAssessment,WorkbenchInterview,WorkbenchResume,WorkbenchCalls):
    def __init__(self,directory,*,hunter=fixed_hunter,reviewer=fixed_review,call_configuration=None,call_transport=None,call_boot_id=None,case_profile='legacy',abf_transport=None,ce_transport=None,session_preparation=None,session_outbound_enabled=False,session_http_client_factory=None):
        self.directory=Path(directory).resolve()/'unified_case_sessions'
        self.lock=threading.RLock()
        if case_profile not in ('legacy','final-20261107'):raise ValueError('Unknown case profile')
        self.case_profile=case_profile
        self.package_loader=load_package
        if case_profile=='final-20261107':
            from competition_showcase import load_showcase_package,fixed_showcase_hunter,DIRECTORY
            self.directory=Path(directory).resolve()/DIRECTORY
            self.package_loader=load_showcase_package
            if hunter is fixed_hunter:hunter=fixed_showcase_hunter
        self.hunter=hunter
        self.reviewer=reviewer
        self._init_calls(configuration=call_configuration,transport=call_transport,boot_id=call_boot_id)
        self._init_abf(abf_transport)
        self._init_ce(ce_transport)
        self._init_runtime(session_preparation,outbound_enabled=session_outbound_enabled,http_client_factory=session_http_client_factory)

    def _session_directory(self,token):
        if self.case_profile=='final-20261107':
            from competition_showcase import REPLAY_TOKEN
            complete=self.directory/'complete-v2'
            if token==REPLAY_TOKEN and complete.is_dir():return complete
        return self.directory

    def _identity(self,token):
        if not isinstance(token,str) or not TOKEN.fullmatch(token):
            raise WorkbenchError('会话身份无效。')
        creation=str(uuid.uuid5(uuid.NAMESPACE_URL,('CareerPilotFinalShowcase20261107:' if self.case_profile=='final-20261107' else 'CareerPilotUnifiedCaseDouble:')+token))
        sid=uuid.uuid5(uuid.NAMESPACE_URL,'CareerPilot:'+creation).hex
        return creation,sid,self._session_directory(token)/('session_'+sid+'.db')

    def _connect(self,token,*,write=False):
        _,sid,path=self._identity(token)
        if write and self.case_profile=='final-20261107':
            from competition_showcase import REPLAY_TOKEN
            if token==REPLAY_TOKEN and (self._session_directory(token)/'replay-sealed.json').is_file():
                raise WorkbenchConflict('完整演示为只读。请新建从头体验会话，原演示记录保持完整。')
        if path.is_symlink() or not path.is_file() or path.resolve().parent!=self._session_directory(token).resolve():
            raise WorkbenchMissing('这份比赛会话暂不可用；请保留列表并重新读取，或新建独立会话。')
        conn=sqlite3.connect(path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=10,factory=WorkbenchConnection)
        conn.row_factory=sqlite3.Row
        try:
            row=conn.execute('SELECT session_id,token_hash FROM wb_meta WHERE singleton=1').fetchone()
            if not row or row['session_id']!=sid or not hmac.compare_digest(row['token_hash'],hashlib.sha256(token.encode()).hexdigest()):
                raise WorkbenchMissing('会话来源无法确认，已停止读取。')
            self._validate_record_links(conn,self._meta(conn))
        except Exception:
            conn.close()
            raise
        return conn

    def _validate_record_links(self,conn,meta):
        """Validate persisted provenance before any read/write, without repairing it.

        Legitimate absence of optional C/E/D is valid. Missing committed parents
        or base A/B/F/progress references is corruption, never an empty history.
        """
        rows={row['record_id']:dict(row) for row in conn.execute('SELECT * FROM wb_records ORDER BY seq')}
        envelopes={}
        for rid,row in rows.items():
            env=validate_source(json.loads(row['envelope_json']))
            expect(env['record_id']==rid and env['record_kind']==row['kind'] and
                all(env[k]==meta[k] for k in SCOPE) and env['run_mode']=='demo' and env['simulated'] is True,
                '保存记录的来源标识不一致，已停止使用。')
            envelopes[rid]=env
        for rid,row in rows.items():
            parents=json.loads(row['parent_ids_json'])
            expect(isinstance(parents,list) and all(isinstance(x,str) for x in parents) and len(set(parents))==len(parents),
                '保存记录的来源引用格式不完整。')
            expect(all(x in rows and rows[x]['seq']<row['seq'] for x in parents),
                '已保存结果的来源记录缺失或顺序异常；不能当作暂无记录，请保留会话并核对备份。')
            expect(bool(parents) or row['kind']=='input','结果缺少输入来源，已停止使用。')
            validate_handoff(envelopes[rid],[envelopes[x] for x in parents])
        def referenced(rid,kind):
            expect(rid in rows and rows[rid]['kind']==kind,'已保存的诊断、计划、审查或学习来源记录缺失，请保留会话并核对备份。')
            return json.loads(rows[rid]['payload_json'])
        original=referenced(meta['session_id']+':input','input')
        expect(original.get('input_digest')==meta['input_digest'] and original.get('snapshot_digest')==meta['snapshot_digest'],
            '原始输入的来源摘要不一致，已停止使用。')
        if meta['bindings'] is not None:
            diagnosis=referenced(meta['session_id']+':diagnosis','diagnosis')
            expect(diagnosis.get('bindings')==meta['bindings'] and diagnosis.get('diagnosis')==completed_result(conn,'diagnosis'),
                '诊断来源与专题绑定不一致，已停止使用。')
        for plan in conn.execute('SELECT version,record_id FROM wb_plans'):
            payload=referenced(plan['record_id'],'plan')
            expect(payload.get('version')==plan['version'],'计划版本的来源引用不一致。')
        for review in conn.execute('SELECT * FROM wb_reviews'):
            payload=referenced(review['record_id'],'plan_review')
            expect(all(payload.get(k)==review[k] for k in ('review_id','plan_version','plan_digest')),'计划审查的来源引用不一致。')
        progress=[json.loads(row['payload_json']).get('progress') for row in rows.values() if row['kind']=='learning_progress']
        for row in conn.execute('SELECT * FROM wb_progress WHERE revision>0'):
            expect(dict(row) in progress,'当前学习进度的保存记录缺失；不能据此新增能力或经历。')
        self._learning_artifact_rows(conn,meta)
        self._application_rows(conn,meta)
        self._abf_validate_records(conn,meta)
        self._ce_validate_records(conn,meta)
        self._session_validate_records(conn,meta)
        self._saved_b_validate_records(conn,meta)
        self._program_publication_validate(conn,meta)

    def _meta(self,conn):
        row=dict(conn.execute('SELECT * FROM wb_meta WHERE singleton=1').fetchone())
        package=json.loads(row['snapshot_json'])
        expect(digest(package)==row['snapshot_digest'],'会话内容快照校验失败，已有记录未被改写。')
        row['package']=package
        row['bindings']=json.loads(row['bindings_json']) if row['bindings_json'] else None
        base=session_info(conn)
        row.update(trace_id=base['trace_id'],plan_id=base['plan_id'],report_id=base['report_id'],inputs=base['inputs'],input_digest=base['input_digest'])
        from personal_workbench_input import validate_snapshot
        validate_snapshot(package,row['inputs'])
        return row

    def _scope(self,meta):
        return {k:meta[k] for k in SCOPE}

    def _envelope(self,meta,record_id,kind,source='fixed_stub_output',usage='presentation_only'):
        return validate_source({'record_id':record_id,'record_kind':kind,'source_kind':source,
            'run_mode':'demo','simulated':True,'evidence_use':usage,**self._scope(meta)})

    def _record(self,conn,meta,record_id,kind,title,payload,parents=(),source='fixed_stub_output',usage='presentation_only'):
        envelope=self._envelope(meta,record_id,kind,source,usage)
        parent_envelopes=[]
        for parent in parents:
            found=conn.execute('SELECT envelope_json FROM wb_records WHERE record_id=?',(parent,)).fetchone()
            expect(found is not None,'来源记录缺失，不能借用其他会话结果。')
            parent_envelopes.append(json.loads(found[0]))
        validate_handoff(envelope,parent_envelopes)
        conn.execute('INSERT INTO wb_records(record_id,kind,title,envelope_json,payload_json,parent_ids_json) VALUES (?,?,?,?,?,?)',
            (record_id,kind,title,encode(envelope),encode(payload),encode(list(parents))))

    def _plan(self,conn,version):
        if not integer(version) or version<1:raise WorkbenchError('计划版本无效。')
        row=conn.execute('SELECT * FROM wb_plans WHERE version=?',(version,)).fetchone()
        expect(row is not None,'计划版本不属于当前会话。')
        row=dict(row);row['plan']=json.loads(row.pop('plan_json'))
        expect(digest(row['plan'])==row['plan_digest'],'计划快照校验失败，不能继续使用。')
        return row

    def _review(self,conn,version):
        row=conn.execute('SELECT * FROM wb_reviews WHERE plan_version=?',(version,)).fetchone()
        if not row:return None
        result=json.loads(row['result_json'])
        return {**result,'review_id':row['review_id'],'plan_version':row['plan_version'],
            'plan_digest':row['plan_digest'],'record_id':row['record_id']}

    def _validate_plan(self,plan,meta):
        if plan.get('time_policy',{}).get('version')=='program-60-v1':
            from fixed_learning_time import policy,fixed_budget
            expect(plan['time_policy']==policy() and all(t['budget']==fixed_budget() for t in plan['tasks']),
                   '每日60分钟及各时间分项由程序固定，不能修改；可调整学习进度或日期。')
        package=meta['package']
        from personal_workbench_input import active_templates
        selected=active_templates(package,meta['bindings']) if package.get('personal_input') else package['case']['learning_tasks']
        templates={t['task_template_id']:t for t in selected}
        binding={t['topic_key']:t for t in meta['bindings']['topics']}
        expect(plan['plan_id']==meta['plan_id'] and plan['report_id']==meta['report_id'] and plan['input_digest']==meta['input_digest'],'计划来源不属于本会话。')
        expect(plan['plan_contract']=='competition-workbench-plan-v1' and plan['available_days']==14 and plan['daily_minutes']==60,
            '计划时长与本会话保存的14天/60分钟约束不一致。')
        expect(len(plan['tasks'])==len(templates) and {t['task_template_id'] for t in plan['tasks']}==set(templates),'学习任务绑定不完整。')
        expect(len({t['task_id'] for t in plan['tasks']})==len(templates),'学习任务身份重复。')
        for task in plan['tasks']:
            original=templates[task['task_template_id']]
            expect(task['task_id']==bound_id(meta['session_id'],'task',task['task_template_id']) and
                task['day']==original['day'] and task['topic_keys']==original['topic_ids'],'任务与会话模板不一致。')
            topic_ids=[binding[k]['topic_id'] for k in task['topic_keys']]
            gap_ids=list(dict.fromkeys(g for k in task['topic_keys'] for g in binding[k]['source_gap_ids']))
            expect(task['topic_ids']==topic_ids and task['source_gap_ids']==gap_ids,'任务差距来源不属于当前诊断。')
            expect(task['expected_outcome'].strip() and task['preparation'].strip(),'任务缺少交付或起步条件。')
            selection=task['resource_selection']
            expect(set(v for v in selection.values() if v is not None)<=set(original['resource_ids']),'任务推荐了未绑定的资料。')
            resolved=resolve_selection(package['catalog'],selection,task['topic_keys'])
            expect(resolved['state']=='verified_primary','资料已需复核或不可用；保留内置引导，本批不发布未经复核的计划。')
            budget=task['budget']
            expect(set(budget)=={'learning_minutes','core_minutes','review_minutes','optional_minutes','assessment_minutes','ending_policy'} and
                all(type(budget[k]) is int and 0<=budget[k]<=240 for k in budget if k!='ending_policy') and
                budget['ending_policy'] in ('stack','choose_one'),'任务时间配置无效。')
            expect(task['task_template_id']=='CP-T01' or budget_total(budget)<=60,'其他任务时间超过固定预算。')
        covered={gid for t in plan['tasks'] for gid in t['source_gap_ids']}
        deferred={g['gap_id'] for g in plan['deferred_gaps']}
        diagnosis=completed_result_for_meta(meta)
        expect(not covered&deferred and covered|deferred=={g['gap_id'] for g in diagnosis['gaps']},'差距必须有真实任务来源或明确暂缓，不能假计覆盖。')

    def template(self):
        package=self.package_loader();case=package['case']
        sample=None
        if self.case_profile=='final-20261107':
            from competition_showcase import replay_entry
            sample=replay_entry(self)
        return self._reply(template={'replay_entry':sample,'case_id':case['case_id'],'version':case['version'],'title':case['title'],
            'candidate':case['candidate'],'position':case['position'],'learning_preferences':case['learning_preferences'],
            'topic_titles':[t['title'] for t in case['topics']],'resource_count':len(package['catalog']['resources'])})

    def _reply(self,**fields):
        return {'source_kind':SOURCE,'run_mode':'demo','simulated':True,'real_dispatch_enabled':False,
            'model_requests':0,'notice':'本会话沿用虚构案例；本操作不调用模型，候选来源以单次调用及采用回执为准。诊断/计划不是个人能力测评。',**fields}

    def create_personal(self,token,body):
        from personal_workbench_input import canonical_inputs,package_for_personal
        expect(self.case_profile=='final-20261107','个人输入仅在当前比赛工作台开放本地接入核验。')
        inputs=canonical_inputs(body);identifier(body['request_id'])
        package=package_for_personal(self.package_loader(),inputs)
        return self.create(token,{'request_id':body['request_id'],'start_date':body['start_date']},
            _personal={'inputs':inputs,'package':package,'body':body})

    def create(self,token,body,*,_personal=None):
        require_fields(body,('request_id','start_date'))
        rid=identifier(body['request_id'])
        try:
            start=date.fromisoformat(body['start_date'])
        except (ValueError,TypeError):raise WorkbenchError('请选择有效的计划开始日期。') from None
        creation,sid,path=self._identity(token)
        operation='create_personal' if _personal else 'create'
        receipt_body=_personal['body'] if _personal else body
        with self.lock:
            if path.exists():
                with closing(self._connect(token,write=True)) as conn:
                    meta=self._meta(conn)
                    expect(meta['start_date']==start.isoformat(),'这份会话已保存其他开始日期，请新建会话。')
                    existing=self._meta(conn)
                    expect(bool(existing['package'].get('personal_input'))==bool(_personal) and (not _personal or existing['inputs']==_personal['inputs']),'这份会话已保存其他输入，不能覆盖；请创建独立会话。')
                    old=self._receipt(conn,rid,operation,receipt_body)
                    if old:return old
                    with conn:return self._save_receipt(conn,rid,operation,receipt_body,meta['revision'])
            package=self.package_loader();case=package['case']
            inputs={'target_role':case['position']['title'],'resume_text':case['candidate']['resume_text'],
                'jd_text':case['position']['jd_text'],'available_days':14,
                'learning_preferences':{'daily_minutes':60,'starting_level':'beginner'}}
            if _personal:package=_personal['package'];case=package['case'];inputs=_personal['inputs']
            meta=create_session(self.directory,inputs,creation)
            with closing(sqlite3.connect(path)) as conn:
                conn.row_factory=sqlite3.Row
                conn.executescript('''
                CREATE TABLE wb_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),session_id TEXT NOT NULL,
                  token_hash TEXT NOT NULL,case_id TEXT NOT NULL,start_date TEXT NOT NULL,snapshot_json TEXT NOT NULL,
                  snapshot_digest TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0,active_version INTEGER,
                  published_version INTEGER,bindings_json TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE wb_plans(version INTEGER PRIMARY KEY,record_id TEXT NOT NULL UNIQUE,plan_json TEXT NOT NULL,
                  plan_digest TEXT NOT NULL,parent_version INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE wb_reviews(review_id TEXT PRIMARY KEY,plan_version INTEGER NOT NULL UNIQUE,
                  plan_digest TEXT NOT NULL,result_json TEXT NOT NULL,record_id TEXT NOT NULL UNIQUE,
                  FOREIGN KEY(plan_version) REFERENCES wb_plans(version));
                CREATE TABLE wb_adoptions(review_id TEXT PRIMARY KEY,source_version INTEGER NOT NULL,target_version INTEGER NOT NULL UNIQUE);
                CREATE TABLE wb_progress(task_id TEXT PRIMARY KEY,status TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',reason TEXT NOT NULL DEFAULT '',
                  start_date TEXT NOT NULL,end_date TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE wb_records(seq INTEGER PRIMARY KEY AUTOINCREMENT,record_id TEXT NOT NULL UNIQUE,kind TEXT NOT NULL,title TEXT NOT NULL,
                  envelope_json TEXT NOT NULL,payload_json TEXT NOT NULL,parent_ids_json TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE wb_requests(request_id TEXT PRIMARY KEY,operation TEXT NOT NULL,body_digest TEXT NOT NULL,response_json TEXT NOT NULL);
                ''')
                with conn:
                    conn.execute('INSERT INTO wb_meta(singleton,session_id,token_hash,case_id,start_date,snapshot_json,snapshot_digest) VALUES (1,?,?,?,?,?,?)',
                        (sid,hashlib.sha256(token.encode()).hexdigest(),case['case_id'],start.isoformat(),encode(package),digest(package)))
                    conn.execute('UPDATE competition_session SET plan_id=? WHERE singleton=1',('PLAN_'+sid[:16],))
                    own=self._meta(conn)
                    self._record(conn,own,sid+':input','input','保存个人求职资料' if _personal else '创建统一比赛会话',
                        {'candidate_id':case['candidate']['candidate_id'],'position_id':case['position']['position_id'],
                         'input_digest':meta['input_digest'],'snapshot_digest':own['snapshot_digest']},source='user_input' if _personal else 'synthetic_input')
                    return self._save_receipt(conn,rid,operation,receipt_body,0)

    def _receipt(self,conn,rid,operation,body):
        old=conn.execute('SELECT * FROM wb_requests WHERE request_id=?',(rid,)).fetchone()
        if not old:return None
        expect(old['operation']==operation and old['body_digest']==digest(body),'请求身份已用于其他操作，不能覆盖原回执。')
        return json.loads(old['response_json'])

    def _save_receipt(self,conn,rid,operation,body,revision,**details):
        result=self._reply(operation=operation,request_id=rid,revision=revision,committed=True,**details)
        conn.execute('INSERT INTO wb_requests VALUES (?,?,?,?)',(rid,operation,digest(body),encode(result)))
        return result

    def request_status(self,token,rid):
        rid=identifier(rid)
        with self.lock,closing(self._connect(token)) as conn:
            row=conn.execute('SELECT response_json FROM wb_requests WHERE request_id=?',(rid,)).fetchone()
            return self._reply(found=row is not None,receipt=json.loads(row[0]) if row else None)

    def _context(self,conn,meta):
        diagnosis=completed_result(conn,'diagnosis')
        meta['diagnosis']=diagnosis
        return meta

    def mutate(self,token,operation,body):
        extras={'diagnosis':set(),'plan':set(),'review':{'plan_version'},'adopt':{'review_id','plan_version'},
            'publish':{'plan_version'},'progress':{'plan_version','task_id','status','note','reason','start_date','end_date'},
            'recover':set(),**ARTIFACT_OPERATIONS,**OPERATIONS,**INTERVIEW_OPERATIONS,**RESUME_OPERATIONS,**ADOPTION_OPERATIONS,**ABF_OPERATIONS,**CE_OPERATIONS,**RUNTIME_OPERATIONS,**SAVED_B_OPERATIONS,**CONFIRM_OPERATIONS}
        if operation not in extras:raise WorkbenchError('不支持这个工作台操作。')
        optional = {'question_count'} if operation == 'assessment_start' and isinstance(body, dict) and 'question_count' in body else set()
        require_fields(body, {'request_id', 'expected_revision'} | extras[operation] | optional)
        rid=identifier(body['request_id'])
        if not integer(body['expected_revision']):raise WorkbenchError('会话修订号无效。')
        with self.lock,closing(self._connect(token,write=True)) as conn:
            old=self._receipt(conn,rid,operation,body)
            if old:return old
            meta=self._context(conn,self._meta(conn))
            expect(meta['revision']==body['expected_revision'],'会话已被其他页面更新；请重新读取后再操作，原输入仍保留。')
            self._abf_guard(conn,operation)
            self._ce_guard(conn,meta,operation,body)
            if operation=='diagnosis' and meta['diagnosis'] is None:
                # The actual A method/session validator writes its own stage.
                # It is idempotent if interrupted after the stage commit.
                from db_manager import DBManager
                db=DBManager(str(self._identity(token)[2]))
                try:SessionWorkflow(db).diagnose(lambda:self.hunter(meta['inputs']))
                finally:db.close()
                meta=self._context(conn,self._meta(conn))
            if operation=='recover':
                stage=next((r for r in stage_records(conn) if r['stage']=='diagnosis'),None)
                expect(stage and stage['status']=='generating','没有可恢复的中断诊断，请重新读取状态。')
                # This synchronous service holds its lock. The process owns the
                # launcher's exclusive directory lease; no old worker can run.
                from db_manager import DBManager
                db=DBManager(str(self._identity(token)[2]))
                try:SessionWorkflow(db).recover_interrupted('diagnosis',worker_stopped=True)
                finally:db.close()
            try:
                conn.execute('BEGIN IMMEDIATE')
                if operation in ADOPTION_OPERATIONS:self._adoption_schema(conn)
                if operation in OPERATIONS:self._assessment_schema(conn)
                if operation in INTERVIEW_OPERATIONS:self._interview_schema(conn)
                if operation in RESUME_OPERATIONS:self._resume_schema(conn)
                current=self._meta(conn)
                expect(current['revision']==meta['revision'],'会话版本已变化，请重新读取。')
                details=getattr(self,'_do_'+operation)(conn,meta,body)
                revision=meta['revision']+1
                conn.execute('UPDATE wb_meta SET revision=? WHERE singleton=1',(revision,))
                result=self._save_receipt(conn,rid,operation,body,revision,**details)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def _do_diagnosis(self,conn,meta,body):
        expect(meta['diagnosis'] is not None,'示例诊断尚未保存。')
        record_id=meta['session_id']+':diagnosis'
        exists=conn.execute('SELECT 1 FROM wb_records WHERE record_id=?',(record_id,)).fetchone()
        if not exists:
            binding=make_bindings(meta,meta['package'],meta['diagnosis'])
            conn.execute('UPDATE wb_meta SET bindings_json=? WHERE singleton=1',(encode(binding),))
            self._record(conn,meta,record_id,'diagnosis','A · 保存岗位证据与专题绑定',
                {'report_id':meta['report_id'],'diagnosis':meta['diagnosis'],'bindings':binding},[meta['session_id']+':input'])
        return {'record_id':record_id}

    def _do_plan(self,conn,meta,body,*,competition_policy=False):
        expect(meta['diagnosis'] and meta['bindings'],'请先完成本会话A诊断和专题绑定。')
        expect(meta['active_version'] is None,'已有计划版本，请读取现有草案或新建会话。')
        plan=fixed_plan(meta,meta['package'],meta['diagnosis'],meta['bindings'])
        if competition_policy:
            from fixed_learning_time import fixed_budget,policy
            plan['time_policy']=policy()
            plan['fixture_notice']='固定演示内容与程序60分钟安排，非模型生成；待程序校验与用户确认发布。'
            for task in plan['tasks']:
                task['budget']=fixed_budget()
                if task['task_template_id']=='CP-T01':
                    task['preparation']=meta['package']['card']['prerequisites']
                    task['gap_interpretation']='先用小样本验证连接与口径，不把未提供证据或部分支持认定为不会。'
        self._validate_plan(plan,meta)
        rid=meta['session_id']+':plan:1'
        conn.execute('INSERT INTO wb_plans VALUES (1,?,?,?,NULL,CURRENT_TIMESTAMP)',(rid,encode(plan),digest(plan)))
        conn.execute('UPDATE wb_meta SET active_version=1 WHERE singleton=1')
        self._record(conn,meta,rid,'plan','B · 保存计划草案 v1',{'version':1,'plan_digest':digest(plan),'task_count':len(plan['tasks'])},[meta['session_id']+':diagnosis'])
        for task in plan['tasks']:
            start=(date.fromisoformat(meta['start_date'])+timedelta(days=task['day']-1)).isoformat()
            conn.execute('INSERT INTO wb_progress(task_id,status,start_date,end_date) VALUES (?,?,?,?)',(task['task_id'],'not_started',start,start))
        return {'record_id':rid,'plan_version':1}

    def _active(self,meta,body):
        expect(integer(body.get('plan_version')) and body['plan_version']==meta['active_version'],'计划版本已变化，请重新读取当前版本。')

    def _do_review(self,conn,meta,body):
        self._active(meta,body)
        version=meta['active_version'];saved=self._plan(conn,version)
        self._validate_plan(saved['plan'],meta)
        existing=self._review(conn,version)
        if existing:return {'review_id':existing['review_id'],'plan_version':version}
        result=self.reviewer(deepcopy(saved['plan']),deepcopy(meta['package']),deepcopy(meta['bindings']),deepcopy(meta))
        from competition_workbench_fixtures import review_findings
        expected=review_findings(saved['plan'],meta['package'],meta['bindings'])
        expect(isinstance(result,dict) and result.get('issues')==expected and result.get('verdict')==('needs_revision' if expected else 'pass'),
            'F审查结果与本版本的可核对依据不一致，未保存。')
        review_id=bound_id(meta['session_id'],'review',str(version));record_id=meta['session_id']+':review:'+str(version)
        result={**result,'scope':self._scope(meta)}
        conn.execute('INSERT INTO wb_reviews VALUES (?,?,?,?,?)',(review_id,version,saved['plan_digest'],encode(result),record_id))
        self._record(conn,meta,record_id,'plan_review',f'F · 审查 v{version}：'+('需修订' if expected else '通过固定复核'),
            {'review_id':review_id,'plan_version':version,'plan_digest':saved['plan_digest'],**result},[saved['record_id'],meta['session_id']+':diagnosis'])
        return {'review_id':review_id,'plan_version':version}

    def _do_adopt(self,conn,meta,body):
        self._active(meta,body)
        expect(meta['published_version'] is None,'计划已开始学习，本批不覆盖已发布版本。')
        review=self._review(conn,body['plan_version'])
        expect(review and review['review_id']==body['review_id'],'审查建议不属于当前会话和版本。')
        saved=self._plan(conn,body['plan_version'])
        expect(review['plan_digest']==saved['plan_digest'] and review['verdict']=='needs_revision' and review['issues'], '这份审查没有可采纳的修订建议。')
        from competition_workbench_fixtures import review_findings
        expect(review['issues']==review_findings(saved['plan'],meta['package'],meta['bindings']),'审查快照与计划不一致，不能采纳。')
        revised=deepcopy(saved['plan'])
        tasks={t['task_id']:t for t in revised['tasks']}
        for issue in review['issues']:
            expect(issue['adoptable'] and issue['task_id'] in tasks and set(issue['patch'])<={'budget','preparation','gap_interpretation'},'建议包含不支持的修改。')
            tasks[issue['task_id']].update(deepcopy(issue['patch']))
        self._validate_plan(revised,meta)
        expect(not review_findings(revised,meta['package'],meta['bindings']),'采纳后的计划仍有未解决的问题。')
        version=body['plan_version']+1
        record_id=meta['session_id']+':plan:'+str(version)
        conn.execute('INSERT INTO wb_plans VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)',(version,record_id,encode(revised),digest(revised),body['plan_version']))
        conn.execute('INSERT INTO wb_adoptions VALUES (?,?,?)',(review['review_id'],body['plan_version'],version))
        conn.execute('UPDATE wb_meta SET active_version=? WHERE singleton=1',(version,))
        self._record(conn,meta,record_id,'plan',f'采纳F建议 · 新建修订版 v{version}',
            {'source_version':body['plan_version'],'version':version,'review_id':review['review_id'],
             'plan_digest':digest(revised),'issue_ids':[i['issue_id'] for i in review['issues']]},[saved['record_id'],review['record_id']])
        return {'record_id':record_id,'plan_version':version}

    def _do_publish(self,conn,meta,body):
        self._active(meta,body)
        expect(meta['published_version'] is None,'这份计划已经确认开始学习，无需重复发布。')
        plan=self._plan(conn,body['plan_version']);review=self._review(conn,body['plan_version'])
        self._validate_plan(plan['plan'],meta)
        expect(review and review['verdict']=='pass' and review['plan_digest']==plan['plan_digest'],'请先完成当前版本的F复核，通过后才能开始学习。')
        conn.execute('UPDATE wb_meta SET published_version=? WHERE singleton=1',(body['plan_version'],))
        record_id=meta['session_id']+':published:'+str(body['plan_version'])
        self._record(conn,meta,record_id,'plan','确认采用计划 · 开始学习',{'event':'published','version':body['plan_version'],'plan_digest':plan['plan_digest']},[plan['record_id'],review['record_id']])
        return {'record_id':record_id,'plan_version':body['plan_version']}

    def _do_progress(self,conn,meta,body):
        self._active(meta,body)
        expect(meta['published_version']==body['plan_version'],'请先在学习计划完成程序校验，并确认发布后开始学习。')
        plan=self._plan(conn,body['plan_version'])
        expect(body['task_id'] in {t['task_id'] for t in plan['plan']['tasks']},'任务不属于本会话计划。')
        if body['status'] not in ('not_started','in_progress','completed','deferred') or not all(isinstance(body[k],str) for k in ('note','reason')) or len(body['note'])>1000 or len(body['reason'])>500:
            raise WorkbenchError('请检查学习状态、笔记和暂缓原因。')
        if body['status']=='deferred' and not body['reason'].strip():raise WorkbenchError('暂缓学习需要说明原因。')
        try:
            start=date.fromisoformat(body['start_date']);end=date.fromisoformat(body['end_date'])
            if not 0<=(end-start).days<=60:raise ValueError()
        except (TypeError,ValueError):raise WorkbenchError('开始与结束日期无效，单项跨度最多60天。') from None
        reason=body['reason'].strip() if body['status']=='deferred' else ''
        conn.execute('UPDATE wb_progress SET status=?,note=?,reason=?,start_date=?,end_date=?,revision=revision+1 WHERE task_id=?',
            (body['status'],body['note'],reason,start.isoformat(),end.isoformat(),body['task_id']))
        progress=dict(conn.execute('SELECT * FROM wb_progress WHERE task_id=?',(body['task_id'],)).fetchone())
        rid=bound_id(meta['session_id'],'progress',body['request_id'])
        self._record(conn,meta,rid,'learning_progress','保存学习进度（不产生评分）',
            {'plan_version':body['plan_version'],'progress':progress},[plan['record_id']],source='user_progress',usage='learning_progress_only')
        return {'record_id':rid,'plan_version':body['plan_version']}

    def _do_recover(self,conn,meta,body):
        rid=bound_id(meta['session_id'],'recovery',body['request_id'])
        self._record(conn,meta,rid,'diagnosis','恢复中断的示例步骤（未重发）',{'stage':'diagnosis','action':'mark_failed_only'},[meta['session_id']+':input'])
        return {'record_id':rid}

    def _fixed_state(self,token):
        with self.lock,closing(self._connect(token)) as conn:
            meta=self._meta(conn);diagnosis=completed_result(conn,'diagnosis')
            versions=[dict(r) for r in conn.execute('SELECT version,record_id,plan_digest,parent_version,created_at FROM wb_plans ORDER BY version')]
            progress=[dict(r) for r in conn.execute('SELECT * FROM wb_progress ORDER BY task_id')]
            active=self._plan(conn,meta['active_version']) if meta['active_version'] else None
            review=self._review(conn,meta['active_version']) if active else None
            stage=next((r for r in stage_records(conn) if r['stage']=='diagnosis'),None)
            return self._reply(scope=self._scope(meta),revision=meta['revision'],start_date=meta['start_date'],
                read_only_demo=(self.case_profile=='final-20261107' and (self._session_directory(token)/'replay-sealed.json').is_file() and token==__import__('competition_showcase').REPLAY_TOKEN),
                personal_input=meta['package'].get('personal_input'),ce_budget=self._ce_ledger(conn,meta),**self._abf_state(conn),case_title=meta['package']['case']['title'],candidate=meta['package']['case']['candidate'],
                position=meta['package']['case']['position'],input_digest=meta['input_digest'],
                active_version=meta['active_version'],published_version=meta['published_version'],
                diagnosis_status=stage['status'] if stage else 'not_started',recovery_available=bool(stage and stage['status']=='generating'),
                diagnosis=diagnosis,bindings=meta['bindings'],plan=active,review=review,plan_versions=versions,progress=progress,
                candidate_adoptions=[{k:a[k] for k in ('application_id','record_id','stage','target_id','revision','candidate_simulated')} | {'formal_resume_id':a.get('formal_resume_id')} for a in self._application_rows(conn,meta)],
                record_count=conn.execute('SELECT COUNT(*) FROM wb_records').fetchone()[0],
                deferred_scope=meta['package']['case']['deferred_scope'],**self._assessment_state(conn,meta),**self._interview_state(conn,meta),**self._resume_state(conn,meta))

    def plan(self,token,version):
        with self.lock,closing(self._connect(token)) as conn:
            meta=self._meta(conn);saved=self._plan(conn,version)
            return self._reply(scope=self._scope(meta),**saved,review=self._review(conn,version),historical=version!=meta['active_version'])

    def learning(self,token,task_id):
        with self.lock,closing(self._connect(token)) as conn:
            meta=self._meta(conn)
            expect(meta['published_version'] is not None,'请先在学习计划中完成程序校验，并确认发布后开始学习。')
            saved=self._plan(conn,meta['published_version'])
            matches=[t for t in saved['plan']['tasks'] if t['task_id']==task_id]
            expect(len(matches)==1,'任务不属于本会话的已发布计划。')
            task=matches[0];progress=dict(conn.execute('SELECT * FROM wb_progress WHERE task_id=?',(task_id,)).fetchone())
            resources=resolve_selection(meta['package']['catalog'],task['resource_selection'],task['topic_keys'])
            package=meta['package']
            content=None
            if task['task_template_id']=='CP-T01':
                content=deepcopy(package['card'])
            else:
                try:
                    content=follow_along_card(package,task)
                except CaseContractError:
                    # Supplement failure must not erase the saved plan or block progress.
                    pass
            card=None
            if content is not None:
                card={'source_kind':'curated_demo','purpose':'session_bound_learning_card','case_id':meta['case_id'],
                    'case_version':package['case']['version'],'card':content,'resources':resources,
                    'notice':'本会话的人工学习内容，绑定当前计划与岗位诊断；固定练习与学习进度独立记录。',
                    'binding':{'task_id':task_id,'plan_id':meta['plan_id'],'plan_version':meta['published_version'],
                        'source_gap_ids':task['source_gap_ids'],'topic_ids':task['topic_ids']}}
            envelope=self._envelope(meta,meta['session_id']+':card:'+task_id,'learning_card','curated_demo','learning_content_only')
            return self._reply(scope=self._scope(meta),revision=meta['revision'],plan_version=meta['published_version'],
                task=task,progress=progress,resources=resources,learning_card=card,envelope=envelope,
                artifact_template=artifact_definition(package,task) if card else None,
                artifacts=[{'record_id':a['record_id'],'artifact':a['artifact']} for a in self._learning_artifact_rows(conn,meta) if a['artifact']['task_id']==task_id][-3:],
                guide_notice=('完整学习卡已关联本任务，可按概念、跟做、必做练习和自查顺序学习。' if card else
                              '完整学习卡暂不可用，可先按本任务的资料和目标学习。'))

    def _fixed_records(self,token):
        with self.lock,closing(self._connect(token)) as conn:
            meta=self._meta(conn)
            records=[]
            answers={a['attempt_id']:a for a in self._answer_rows(conn,meta)}
            interviews={**self._interview_record_payloads(conn,meta),**self._resume_record_payloads(conn,meta)}
            for row in conn.execute('SELECT * FROM wb_records ORDER BY seq DESC'):
                envelope=json.loads(row['envelope_json']);validate_source(envelope)
                expect(all(envelope[k]==meta[k] for k in SCOPE),'记录来源校验失败。')
                raw_payload=json.loads(row['payload_json'])
                public_payload=({'event':'candidate_adopted',**self._public_application(conn,raw_payload)} if raw_payload.get('event')=='candidate_adopted' else interviews.get(row['record_id'],answers.get(raw_payload.get('attempt_id'),raw_payload)))
                records.append({'record_id':row['record_id'],'kind':row['kind'],'title':row['title'],
                    'seq':row['seq'],'created_at':row['created_at'].replace(' ','T')+'Z','envelope':envelope,
                    'payload':public_payload,'parent_ids':json.loads(row['parent_ids_json'])})
            return self._reply(scope=self._scope(meta),records=records)


def completed_result_for_meta(meta):
    result=meta.get('diagnosis')
    expect(result is not None,'本会话诊断尚未保存。')
    return result
