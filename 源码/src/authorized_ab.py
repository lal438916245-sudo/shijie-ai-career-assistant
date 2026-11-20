"""Full A/B requests and durable one-use grants, exclusively for local doubles.

No SDK import, API key access, HTTP client or real transport is available here.
"""
from contextlib import closing
import hashlib
import json
import math
import sqlite3
import time
import uuid

from competition_sessions import SessionError, SessionBusy, session_info, completed_result, stage_records, encode
from model_preparation import DEFAULT

MODE='local_request_double'
SOURCE='authorized_ab_double'
PROMPT_VERSION='ab-shared-prompts-v4-a-evidence'

class ABConflict(SessionError):pass

def digest(value):return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()

def build_request(meta,diagnosis,configuration,stage,stage_state):
    """The same builders invoked by the actual HunterAgent/PlannerAgent methods."""
    from agent_a_hunter import HUNTER_SYSTEM_PROMPT, build_audit_prompt
    from agent_b_planner import LearningPlan, build_plan_system_prompt, build_plan_prompt
    if stage=='diagnosis':
        system=HUNTER_SYSTEM_PROMPT
        user=build_audit_prompt(meta['inputs']['target_role'],meta['inputs']['resume_text'],meta['inputs']['jd_text'])
        fields={k:meta['inputs'][k] for k in ('target_role','resume_text','jd_text')}
    elif stage=='plan':
        if not diagnosis or not diagnosis['gaps']:raise ABConflict('请先完成并保存包含差距来源的诊断')
        from daily_learning import plan_model
        preferences=meta['inputs'].get('learning_preferences')
        system=build_plan_system_prompt(meta['inputs']['available_days'],json.dumps(plan_model(preferences).model_json_schema(),ensure_ascii=False),require_sources=True)
        user=build_plan_prompt(encode(diagnosis['audit']),meta['inputs']['available_days'],diagnosis['gaps'],require_sources=True,learning_preferences=preferences)
        fields={'diagnosis_audit':diagnosis['audit'],'gap_catalog':diagnosis['gaps'],'available_days':meta['inputs']['available_days']}
        if preferences is not None:fields['learning_preferences']=preferences
    else:raise ABConflict('仅支持 A 诊断和 B 学习计划')
    if stage_state and stage_state['status'] in ('completed','generating'):raise ABConflict('此步骤已完成或正在执行，请读取已有状态，或新建独立会话验证')
    configured=configuration['revision']>0
    c=configuration['config'] if configured else {**DEFAULT,'provider':'本地替身验证','base_url':'local://request-double','model':'local-request-double'}
    payload={'model':c['model'],'messages':[{'role':'system','content':system},{'role':'user','content':user}],'temperature':0.7,'max_tokens':c['max_output_tokens']}
    return {'version':1,'mode':MODE,'prompt_version':PROMPT_VERSION,'stage':stage,'session_id':meta['session_id'],'trace_id':meta['trace_id'],'input_digest':digest(meta['inputs']),'diagnosis_digest':digest(diagnosis) if stage=='plan' else None,'stage_digest':digest(stage_state),'config_revision':configuration['revision'],'config':c,'configured':configured,'timeout_seconds':c['timeout_seconds'],'automatic_retries':0,'payload':payload,'fields':[{'name':k,'characters':len(v if isinstance(v,str) else encode(v)),'sha256':digest(v)} for k,v in fields.items()]}

class FixedABTransport:
    mode=MODE
    def send(self,request,meta,diagnosis):
        # Only a deterministic, in-process response. Destination and API Key are
        # never read, and no real model client exists in this transport.
        if request['mode']!=MODE:raise ABConflict('禁止切换为真实调用')
        if request['stage']=='diagnosis':
            value={'analysis_mode':'targeted','match_score':55,'score_reason':'完整请求链路的固定合成响应，不评价本次输入。','fatal_weakness':'合成示例：实时验证经验待补充。','invisible_gaps':[{'skill':'实时数据处理','industry_requirement':'理解事件时间与故障恢复','candidate_current':'合成示例：具备离线数据处理基础','gap_reason':'合成示例：缺少窗口及恢复验证'}],'gap_table':[],'actionable_advice':['学习窗口与恢复的验证方法。']}
        else:
            days=meta['inputs']['available_days'];phases=[{'phase_name':f'合成阶段 {n+1}','phase_goal':'验证计划和来源','tasks':[]} for n in range(4)]
            for day in range(1,days+1):phases[min((day-1)*4//days,3)]['tasks'].append({'day':day,'task_type':'理论学习','content':f'合成第 {day} 天：窗口与恢复验证','expected_outcome':'解释概念并列出验证步骤','source_gap_ids':[g['gap_id'] for g in diagnosis['gaps']]})
            value={'overall_goal':'本地完整请求替身计划，不是个性化评价','phases':phases}
        if meta['inputs'].get('learning_preferences') is not None:
            if request['stage']=='diagnosis':
                value['gap_table']=[{'技能':'Python工程化','状态':'部分掌握','优先级':'P2 - 战略放弃'}]
            else:
                from daily_learning import fixed_daily_plan
                value=fixed_daily_plan(meta['inputs']['available_days'],diagnosis['gaps'],meta['inputs']['learning_preferences'])
        content=json.dumps(value,ensure_ascii=False)
        output=math.ceil(len(content)/2)
        return {'content':content,'finish_reason':'stop' if output<=request['payload']['max_tokens'] else 'length','synthetic_output_tokens':output}

def request_agents(request,transport,meta,diagnosis):
    """Use real Agent methods with a one-shot think boundary, never __init__."""
    from agent_a_hunter import HunterAgent
    from agent_b_planner import PlannerAgent, LearningPlan
    sent=False
    def create(db):
        nonlocal sent
        cls=HunterAgent if request['stage']=='diagnosis' else PlannerAgent
        agent=cls.__new__(cls)
        agent.db=None;agent.model_name='local-request-double';agent.trace_id=meta['trace_id']
        agent.evidence_contract_required = bool(getattr(transport, 'evidence_contract_required', False))
        agent.system_prompt=request['payload']['messages'][0]['content']
        if request['stage']=='plan':
            agent.schema_json=json.dumps(LearningPlan.model_json_schema(),ensure_ascii=False);agent.current_plan_id=None;agent.reflection_history=[]
        def think(prompt,**_kwargs):
            nonlocal sent
            if sent:raise ABConflict('本次授权已经发出一次请求，不允许自动重试或修正')
            actual=[{'role':'system','content':agent.system_prompt},{'role':'user','content':prompt}]
            if actual!=request['payload']['messages']:raise ABConflict('实际提示与已确认请求不一致，拒绝执行')
            sent=True;start=time.monotonic()
            response=transport.send(json.loads(encode(request)),meta,diagnosis)
            if time.monotonic()-start>request['timeout_seconds']:raise TimeoutError('local substitute timeout')
            if not isinstance(response,dict) or response.get('finish_reason')!='stop':raise ABConflict('替身响应截断或未正常完成，不自动扩容或重试')
            if type(response.get('synthetic_output_tokens')) is not int or not 0<=response['synthetic_output_tokens']<=request['payload']['max_tokens']:raise ABConflict('替身输出超出已授权上限')
            if not isinstance(response.get('content'),str) or not response['content'].strip():raise ABConflict('替身响应为空')
            return response['content']
        agent.think=think
        return agent
    return create

class AuthorizedAB:
    mode=MODE
    source=SOURCE
    confirmation_field='accept_local_only'
    @property
    def real_dispatch_enabled(self):return False
    def prepare_request(self,request,configuration):return request
    def check_dispatch(self,request):pass
    def agent_factory(self,request,meta,diagnosis):return request_agents(request,self.server.ab_transport,meta,diagnosis)
    def failure_code(self,exc):return 'timeout' if isinstance(exc,TimeoutError) else 'validation' if isinstance(exc,(SessionError,ValueError)) else 'execution'
    def __init__(self,handler):self.h=handler;self.server=handler.server
    def _connect(self,path):
        c=sqlite3.connect(path,timeout=10);c.row_factory=sqlite3.Row
        c.executescript('''CREATE TABLE IF NOT EXISTS ab_previews(preview_id TEXT PRIMARY KEY,stage TEXT NOT NULL,digest TEXT NOT NULL,request_json TEXT NOT NULL,created_at REAL NOT NULL,expires_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS ab_authorizations(authorization_id TEXT PRIMARY KEY,preview_id TEXT NOT NULL UNIQUE,status TEXT NOT NULL,boot_id TEXT NOT NULL,created_at REAL NOT NULL,expires_at REAL NOT NULL,receipt_json TEXT);''')
        return c
    def _fresh(self,c,stage):
        configuration=self.server.preparation._read()  # caller holds preparation.lock; never decrypt a Key
        state=next((x for x in stage_records(c) if x['stage']==stage),None)
        if state is not None:
            try:
                marker=c.execute('SELECT attempt_id FROM local_adapter_workers WHERE stage=?',(stage,)).fetchone()
                state={**state,'execution_marker':marker[0] if marker else None}
            except sqlite3.Error:state={**state,'execution_marker':None}
        return self.prepare_request(build_request(session_info(c),completed_result(c,'diagnosis'),configuration,stage,state),configuration)
    def _reply(self,**kw):return {'source_kind':self.source,'mode':self.mode,'real_dispatch_enabled':self.real_dispatch_enabled,**kw}
    def preview(self,token,body):
        if set(body)!={'stage'}:raise ABConflict('请求预览字段无效')
        path=self.h.checked_path(token)
        with self.server.preparation.lock,self.server.guard,closing(self._connect(path)) as c:
            request=self._fresh(c,body['stage']);identity=str(uuid.uuid4());now=time.time()
            with c:c.execute('INSERT INTO ab_previews VALUES (?,?,?,?,?,?)',(identity,request['stage'],digest(request),encode(request),now,now+300))
        count=len(encode(request['payload']));config=request['config'];estimated=math.ceil(count/2)
        priced=config['input_price_per_million'] is not None and config['output_price_per_million'] is not None
        cost=(estimated*config['input_price_per_million']+request['config']['max_output_tokens']*config['output_price_per_million'])/1000000 if priced else None
        return self._reply(preview_id=identity,request_digest=digest(request),expires_at=now+300,stage=request['stage'],request=request['payload'],fields=request['fields'],config_revision=request['config_revision'],configured_provider=config['provider'],configured_destination=config['base_url'],transport_destination='本进程固定替身，无外部请求',timeout_seconds=request['timeout_seconds'],automatic_retries=0,request_characters=count,input_limit_exceeded=count>config['max_input_chars'],estimated_input_tokens=estimated,estimated_cost=cost,currency=config['currency'],actual_cost=0,notice='完整 A/B 请求已组装；本次只允许本地替身验证，无需真实 Key。确认后仍需单独点击执行，真实调用保持关闭。',cost_notice='费用按完整请求字符数及每 2 字符约 1 token 粗估，使用手填单价；不是账单或硬上限。本轮替身不产生模型费用。')
    def authorize(self,token,body):
        if set(body)!={'preview_id','request_digest',self.confirmation_field} or body[self.confirmation_field] is not True:raise ABConflict('请明确确认本次模式的一次请求')
        path=self.h.checked_path(token)
        with self.server.preparation.lock,self.server.guard,closing(self._connect(path)) as c:
            c.execute('BEGIN IMMEDIATE')
            p=c.execute('SELECT * FROM ab_previews WHERE preview_id=?',(body['preview_id'],)).fetchone()
            if not p or p['expires_at']<=time.time() or p['digest']!=body['request_digest']:raise ABConflict('预览已过期或不匹配，请重新预览')
            request=self._fresh(c,p['stage'])
            if digest(request)!=p['digest']:raise ABConflict('配置、资料、阶段或提示已变化，请重新预览')
            if len(encode(request['payload']))>request['config']['max_input_chars']:raise ABConflict('完整请求超过输入预检阈值，不能授权')
            old=c.execute('SELECT * FROM ab_authorizations WHERE preview_id=?',(p['preview_id'],)).fetchone()
            if old:identity=old['authorization_id']
            else:
                identity=str(uuid.uuid4());now=time.time()
                c.execute('INSERT INTO ab_authorizations VALUES (?,?,?,?,?,?,NULL)',(identity,p['preview_id'],'authorized',self.server.boot_id,now,p['expires_at']))
            c.commit()
        return self.status(token,{'authorization_id':identity})
    def _row(self,c,identity):
        if not isinstance(identity,str) or len(identity)>80:raise ABConflict('授权身份无效')
        row=c.execute('SELECT a.*,p.stage,p.digest,p.request_json FROM ab_authorizations a JOIN ab_previews p USING(preview_id) WHERE authorization_id=?',(identity,)).fetchone()
        if not row:raise ABConflict('此会话不存在对应授权')
        return row
    def _receipt(self,row,status,result=None,error=None):
        return self._reply(authorization_id=row['authorization_id'],preview_id=row['preview_id'],stage=row['stage'],status=status,expires_at=row['expires_at'],consumed=status not in ('authorized','expired','invalidated'),request_digest=row['digest'],result=result,error_code=error,automatic_retry=False,actual_model_cost=0,notice='本地替身单次授权，不可用于真实模型；已消费授权不会重新发送。')
    def status(self,token,body):
        if set(body)!={'authorization_id'}:raise ABConflict('状态请求字段无效')
        path=self.h.checked_path(token)
        with self.server.preparation.lock,self.server.guard,closing(self._connect(path)) as c:
            row=self._row(c,body['authorization_id'])
            if row['receipt_json']:return json.loads(row['receipt_json'])
            if row['status']=='authorized':
                state='expired' if row['expires_at']<=time.time() else 'authorized'
                if state=='authorized':
                    try:
                        if digest(self._fresh(c,row['stage']))!=row['digest']:state='invalidated'
                    except SessionError:state='invalidated'
                return self._receipt(row,state)
            if row['authorization_id'] in self.server.active_authorizations:return self._receipt(row,'running')
            # A crash after the stage commit can be recovered without dispatch,
            # but only if that exact authorization owned the persisted step.
            try:worker=c.execute('SELECT authorization_id FROM local_adapter_workers WHERE stage=?',(row['stage'],)).fetchone()
            except sqlite3.Error:worker=None
            result=completed_result(c,row['stage'])
            receipt=self._receipt(row,'completed' if worker and worker[0]==row['authorization_id'] and result else 'interrupted',result=self.h.read(token,row['stage']) if worker and worker[0]==row['authorization_id'] and result else None)
            with c:c.execute('UPDATE ab_authorizations SET status=?,receipt_json=? WHERE authorization_id=?',(receipt['status'],encode(receipt),row['authorization_id']))
            return receipt
    def latest(self,token):
        path=self.h.checked_path(token)
        with self.server.guard,closing(self._connect(path)) as c:
            row=c.execute('SELECT authorization_id FROM ab_authorizations ORDER BY rowid DESC LIMIT 1').fetchone()
        return self._reply(authorization=self.status(token,{'authorization_id':row[0]}) if row else None)
    def execute(self,token,body):
        if set(body)!={'authorization_id'}:raise ABConflict('执行请求字段无效')
        path=self.h.checked_path(token);identity=body['authorization_id'];request=None
        with self.server.preparation.lock,self.server.guard,closing(self._connect(path)) as c:
            c.execute('BEGIN IMMEDIATE');row=self._row(c,identity)
            if row['status']!='authorized':
                c.rollback();return self.status(token,body)
            if row['expires_at']<=time.time():raise ABConflict('授权已过期，请重新预览并确认')
            request=self._fresh(c,row['stage'])
            if digest(request)!=row['digest']:raise ABConflict('请求已变化，授权失效，请重新预览')
            self.check_dispatch(request)
            key=(str(path),row['stage'])
            if key in self.server.active or key in self.server.reservations:raise SessionBusy('步骤仍在执行')
            meta=session_info(c);diagnosis=completed_result(c,'diagnosis')
            self.server.reservations[key]=identity;self.server.active_authorizations.add(identity)
            try:
                c.execute("UPDATE ab_authorizations SET status='running',boot_id=? WHERE authorization_id=? AND status='authorized'",(self.server.boot_id,identity));c.commit()
            except BaseException:
                self.server.reservations.pop(key,None);self.server.active_authorizations.discard(identity);raise
        receipt=None
        try:
            factory=self.agent_factory(request,meta,diagnosis)
            result=self.h.execute(token,request['stage'],authorized_factory=factory,authorization_id=identity)
            receipt=self._receipt(row,'completed',result=result)
        except Exception as exc:
            error=self.failure_code(exc)
            receipt=self._receipt(row,'failed',error=error)
            from competition_sessions import SessionPlanError, SessionDiagnosisError
            if isinstance(exc,(SessionPlanError, SessionDiagnosisError)):receipt['validation_error']=exc.validation_error
        finally:
            with self.server.guard:
                self.server.reservations.pop((str(path),request['stage']),None)
                if receipt is None:self.server.active_authorizations.discard(identity)
                # Keep active authorization until the receipt commit below. A
                # process death here is reconciled from stage ownership on read.
        try:
            with self.server.guard,closing(self._connect(path)) as c:
                with c:c.execute('UPDATE ab_authorizations SET status=?,receipt_json=? WHERE authorization_id=?',(receipt['status'],encode(receipt),identity))
        finally:
            with self.server.guard:self.server.active_authorizations.discard(identity)
        return receipt
