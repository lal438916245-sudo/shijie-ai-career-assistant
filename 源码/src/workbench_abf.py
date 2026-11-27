"""Durable A/B/F local rehearsal: preview -> grant -> candidate -> reviewed apply.

Own tables, same workbench session/plan/records. No real transport or Key access.
Existing C/E/D trial limits and the sealed public replay remain unchanged.
"""
from contextlib import closing
from copy import deepcopy
from datetime import date,timedelta
import json,time,uuid
from abf_contracts import VERSION,STAGES,ABFValidation,build_context,payload,normalize,fixed_output
from competition_workbench_assessment import encode,digest,expect,invalid
from competition_workbench_fixtures import fixed_plan,bound_id

ABF_ACTIONS={'abf_preview','abf_authorize','abf_execute','abf_status','abf_recover','abf_adoption_preview'}
ABF_OPERATIONS={'abf_apply':{'authorization_id','candidate_digest','review_confirmed'}}
class FixedABFTransport:
    mode='abf_fixed_rehearsal'
    def send(self,request):return {'content':encode(fixed_output(request)),'finish_reason':'stop','usage':None}

def fields(body,keys):
    if not isinstance(body,dict) or set(body)!=set(keys):invalid('A/B/F字段不完整或包含不支持的内容。')
def uid(value):
    try:
        if not isinstance(value,str):raise ValueError()
        result=str(uuid.UUID(value));expect(result==value,'请求身份须为规范UUID。');return result
    except (ValueError,TypeError,AttributeError):invalid('A/B/F请求身份无效。')

class WorkbenchABF:
    def _init_abf(self,transport=None):
        transport=transport or FixedABFTransport()
        if not isinstance(transport,FixedABFTransport) or transport.mode!='abf_fixed_rehearsal':
            raise ValueError('本批A/B/F只允许本地替身。')
        self.abf_transport=transport;self.abf_active=set()

    def _abf_schema(self,c):
        c.execute('CREATE TABLE IF NOT EXISTS wbf_policy(singleton INTEGER PRIMARY KEY CHECK(singleton=1),contract_version TEXT NOT NULL)')
        c.execute('INSERT OR IGNORE INTO wbf_policy VALUES (1,?)',(VERSION,))
        c.execute('CREATE TABLE IF NOT EXISTS wbf_previews(preview_id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,body_digest TEXT NOT NULL,request_json TEXT NOT NULL,request_digest TEXT NOT NULL,expires_at REAL NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS wbf_grants(authorization_id TEXT PRIMARY KEY,preview_id TEXT NOT NULL UNIQUE,boot_id TEXT NOT NULL,status TEXT NOT NULL,dispatch_count INTEGER NOT NULL DEFAULT 0,response_json TEXT,response_digest TEXT,result_json TEXT,result_digest TEXT,error_json TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS wbf_applications(application_id TEXT PRIMARY KEY,authorization_id TEXT NOT NULL UNIQUE,stage TEXT NOT NULL,target_version INTEGER NOT NULL,revision INTEGER NOT NULL UNIQUE,payload_json TEXT NOT NULL,payload_digest TEXT NOT NULL,UNIQUE(stage,target_version))')

    @staticmethod
    def _has_abf(c):return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wbf_policy'").fetchone())

    def _abf_guard(self,c,operation):
        if self._has_abf(c) or self._meta(c)['package'].get('personal_input'):
            expect(operation not in ('diagnosis','plan','plan_prepare','review','adopt','recover'),
                   '本会话使用模型候选核对流程，请通过相应候选生成和采用；不能混入固定演示生产步骤。')

    def _abf_request(self,c,meta,stage,version):
        if stage!='a_diagnosis':
            expect(self._has_abf(c) and c.execute("SELECT 1 FROM wbf_applications WHERE stage='a_diagnosis'").fetchone(),
                   'B/F必须使用本会话已核对采用的A结果，不能混入固定步骤或其他会话诊断。')
        ctx=build_context(self,c,meta,stage,version)
        req={'contract_version':VERSION,'mode':'abf_fixed_rehearsal','stage':stage,'target_version':version,
             'scope':self._scope(meta),'input_digest':meta['input_digest'],'revision':meta['revision'],
             'boot_id':self.call_boot_id,'context':ctx,'payload':payload(stage,ctx),'automatic_retries':0}
        if stage=='b_plan':req['fixture_plan']=fixed_plan(meta,meta['package'],ctx['diagnosis'],ctx['bindings'])
        return self.abf_transport.freeze(req) if hasattr(self.abf_transport,"freeze") else req

    def _abf_row(self,c,aid):
        expect(self._has_abf(c),'本会话没有A/B/F授权。')
        row=c.execute('SELECT g.*,p.request_json,p.request_digest,p.expires_at FROM wbf_grants g JOIN wbf_previews p USING(preview_id) WHERE authorization_id=?',(uid(aid),)).fetchone()
        expect(row is not None,'A/B/F授权不属于本会话。');row=dict(row);req=json.loads(row['request_json']);meta=self._meta(c)
        expect(req['contract_version']==VERSION and req['mode']=='abf_fixed_rehearsal' and req['scope']==self._scope(meta)
               and req['input_digest']==meta['input_digest'] and req['context']['inputs']==meta['inputs']
               and req['context']['scope']==req['scope'] and req['context']['snapshot_digest']==meta['snapshot_digest']
               and row['boot_id']==req['boot_id'] and digest(req)==row['request_digest'],'A/B/F请求来源校验失败。')
        self._session_check_saved(c,row,req,'abf')
        if row['response_json']:expect(digest(json.loads(row['response_json']))==row['response_digest'],'A/B/F响应摘要校验失败。')
        if row['result_json']:
            expect(row['response_json'] and json.loads(row['response_json'])['finish_reason']=='stop','完整候选缺少正常结束的响应。')
            result=json.loads(row['result_json']);expect(digest(result)==row['result_digest'] and row['status']=='completed','候选摘要校验失败。')
            self._abf_sdk_usage(req,json.loads(row['response_json']))
            reconstructed=normalize(self,meta,req,json.loads(row['response_json'])['content'])
            expect(reconstructed==result,'A/B/F候选与原响应不一致。')
        return row,req

    def _abf_view(self,row,req):
        status=row['status']
        if status=='authorized':
            if req['boot_id']!=self.call_boot_id:status='invalidated'
            elif row['expires_at']<=self.call_clock():status='expired'
        if req.get('contract_sdk') and status=='dispatching' and row['authorization_id'] not in self.abf_active:status='unknown_outcome'
        response=json.loads(row['response_json']) if row['response_json'] else None
        return self._reply(**self._abf_sdk_public(req),contract_version=VERSION,mode='abf_fixed_rehearsal',authorization_id=row['authorization_id'],
           preview_id=row['preview_id'],stage=req['stage'],target_version=req['target_version'],status=status,
           request_digest=row['request_digest'],consumed=bool(row['dispatch_count']),dispatch_attempts=row['dispatch_count'],
           simulated=True,external_network_allowed=False,actual_model_cost=0,automatic_retry=False,
           result=json.loads(row['result_json']) if row['result_json'] else None,
           candidate_digest=row['result_digest'],errors=json.loads(row['error_json']) if row['error_json'] else [],
           source_revision=req['revision'],usage=response.get('usage') if response else None,
           recoverable=status=='response_saved',notice='A/B/F本地替身候选；尚未采用不会写入正式诊断、计划或审查。失败与查询均不自动重发。')

    def abf_preview(self,token,body):
        fields(body,('request_id','expected_revision','stage','target_version'));rid=uid(body['request_id'])
        expect(type(body['expected_revision']) is int and body['expected_revision']>=0,'会话修订号无效。')
        with self.lock,closing(self._connect(token,write=True)) as c:
            meta=self._context(c,self._meta(c));expect(meta['revision']==body['expected_revision'],'会话已更新，请重新读取后预览。')
            req=self._abf_request(c,meta,body['stage'],body['target_version'])
            with c:
                self._abf_schema(c)
                old=c.execute('SELECT * FROM wbf_previews WHERE request_id=?',(rid,)).fetchone()
                if old:
                    expect(old['body_digest']==digest(body) and old['request_json']==encode(req),'请求身份已用于其他内容或来源已改变。')
                    pid=old['preview_id'];expires=old['expires_at']
                else:
                    pid=str(uuid.uuid4());expires=self.call_clock()+300
                    c.execute('INSERT INTO wbf_previews VALUES (?,?,?,?,?,?)',(pid,rid,digest(body),encode(req),digest(req),expires))
            return self._reply(**self._abf_sdk_public(req),contract_version=VERSION,mode='abf_fixed_rehearsal',preview_id=pid,request_digest=digest(req),
                stage=req['stage'],target_version=req['target_version'],revision=req['revision'],scope=req['scope'],
                input_digest=req['input_digest'],request=req['payload'],request_characters=len(encode(req['payload'])),
                expires_at=expires,external_network_allowed=False,actual_model_cost=0,automatic_retries=0,
                notice='完整A/B/F请求预览，仅本地替身；未授权、未执行、不读取Key，不调用真实模型。')

    def abf_authorize(self,token,body):
        confirmation='accept_session_once' if isinstance(body,dict) and 'accept_session_once' in body else 'accept_fixed_only'
        fields(body,('preview_id','request_digest',confirmation));expect(body[confirmation] is True,'请明确核对本次单次授权。')
        with self.lock,closing(self._connect(token,write=True)) as c:
            expect(self._has_abf(c),'没有可授权的预览。')
            p=c.execute('SELECT * FROM wbf_previews WHERE preview_id=?',(uid(body['preview_id']),)).fetchone()
            expect(p and p['request_digest']==body['request_digest'] and p['expires_at']>self.call_clock(),'预览不匹配或已过期。')
            req=json.loads(p['request_json']);meta=self._context(c,self._meta(c))
            expect(confirmation==('accept_session_once' if req.get('session_runtime') else 'accept_fixed_only'),'授权确认与预览模式不一致。')
            expect(not self._abf_sdk_public(req).get('input_limit_exceeded',False),'完整请求超过输入上限，未授权；请先调整请求或本机配置。')
            expect(req==self._abf_request(c,meta,req['stage'],req['target_version']),'来源/提示/进程已变化，旧预览不能授权。')
            with c:
                c.execute('BEGIN IMMEDIATE')
                old=c.execute('SELECT authorization_id FROM wbf_grants WHERE preview_id=?',(p['preview_id'],)).fetchone()
                aid=old[0] if old else str(uuid.uuid4())
                if not old:
                    self._session_before_authorize(c,req)
                    c.execute("INSERT INTO wbf_grants(authorization_id,preview_id,boot_id,status) VALUES (?,?,?,'authorized')",(aid,p['preview_id'],self.call_boot_id))
                    self._session_on_authorized(c,req,aid,'abf')
            row,req=self._abf_row(c,aid);return self._abf_view(row,req)

    def _abf_validate_saved(self,c,aid):
        row,req=self._abf_row(c,aid);expect(row['status']=='response_saved','没有可恢复的已保存响应。')
        response=json.loads(row['response_json'])
        try:
            self._abf_sdk_usage(req,response)
            if response['finish_reason']!='stop':raise ABFValidation('truncated_or_incomplete')
            result=normalize(self,self._meta(c),req,response['content']);status='completed';errors=[]
        except ABFValidation as exc:result=None;status='failed_validation';errors=exc.errors
        c.execute('UPDATE wbf_grants SET status=?,result_json=?,result_digest=?,error_json=? WHERE authorization_id=?',
            (status,encode(result) if result is not None else None,digest(result) if result is not None else None,encode(errors),aid))

    def abf_execute(self,token,body):
        fields(body,('authorization_id',));aid=uid(body['authorization_id'])
        with self.lock,closing(self._connect(token,write=True)) as c:
            row,req=self._abf_row(c,aid)
            if row['status']!='authorized':return self._abf_view(row,req)
            expect(req['boot_id']==self.call_boot_id and row['expires_at']>self.call_clock(),'授权已过期或服务已重启，未发出请求。')
            meta=self._context(c,self._meta(c));expect(req==self._abf_request(c,meta,req['stage'],req['target_version']),'来源已变化，未派发旧授权。')
            with c:
                c.execute('BEGIN IMMEDIATE')
                self._session_before_dispatch(c,req,aid)
                changed=c.execute("UPDATE wbf_grants SET status='dispatching',dispatch_count=1 WHERE authorization_id=? AND status='authorized'",(aid,))
                expect(changed.rowcount==1,'本授权已消费，请查询回执。')
            self.abf_active.add(aid)
        try:
            try:
                response=self.abf_transport.send(deepcopy(req))
                if not isinstance(response,dict) or set(response)!={'content','finish_reason','usage'} or not isinstance(response['content'],str) or len(response['content'])>200000:
                    raise ABFValidation('transport_response')
                if response['usage'] is not None and not req.get('contract_sdk'):raise ABFValidation('fixed_transport_usage')
            except Exception as exc:
                from sdk_transport import SDKFailure
                errors=exc.errors if isinstance(exc,ABFValidation) else [{'code':exc.code if isinstance(exc,SDKFailure) else 'timeout' if isinstance(exc,TimeoutError) else 'transport_failed','path':'$'}]
                with self.lock,closing(self._connect(token,write=True)) as c:
                    usage=getattr(exc,'usage',None)
                    failed={'content':'','finish_reason':'length' if getattr(exc,'code',None)=='truncated' else 'error','usage':usage} if usage is not None else None
                    with c:c.execute("UPDATE wbf_grants SET status='failed_transport',error_json=?,response_json=?,response_digest=? WHERE authorization_id=?",(encode(errors),encode(failed) if failed else None,digest(failed) if failed else None,aid))
                    row,req=self._abf_row(c,aid);return self._abf_view(row,req)
            with self.lock,closing(self._connect(token,write=True)) as c:
                with c:c.execute("UPDATE wbf_grants SET status='response_saved',response_json=?,response_digest=? WHERE authorization_id=?",(encode(response),digest(response),aid))
                with c:self._abf_validate_saved(c,aid)
                row,req=self._abf_row(c,aid);return self._abf_view(row,req)
        finally:
            with self.lock:self.abf_active.discard(aid)

    def abf_status(self,token,body):
        fields(body,('authorization_id',))
        with self.lock,closing(self._connect(token)) as c:
            row,req=self._abf_row(c,body['authorization_id']);return self._abf_view(row,req)

    def abf_recover(self,token,body):
        fields(body,('authorization_id',));aid=uid(body['authorization_id'])
        with self.lock,closing(self._connect(token,write=True)) as c:
            row,req=self._abf_row(c,aid)
            expect(aid not in self.abf_active,'本请求仍在处理，请先读取回执。')
            # A dispatch with no durable response is unknown, never a reason to resend.
            if row['status']=='response_saved':
                with c:self._abf_validate_saved(c,aid)
                row,req=self._abf_row(c,aid)
            return self._abf_view(row,req)

    def abf_adoption_preview(self,token,body):
        fields(body,('authorization_id',))
        with self.lock,closing(self._connect(token)) as c:
            row,req=self._abf_row(c,body['authorization_id']);expect(row['status']=='completed','只有完整且通过校验的候选可核对采用。')
            meta=self._context(c,self._meta(c));candidate=json.loads(row['result_json'])
            app=c.execute('SELECT payload_json FROM wbf_applications WHERE authorization_id=?',(row['authorization_id'],)).fetchone()
            occupied=c.execute('SELECT 1 FROM wbf_applications WHERE stage=? AND target_version=?',(req['stage'],req['target_version'])).fetchone()
            try:current=build_context(self,c,meta,req['stage'],req['target_version'])==req['context']
            except ValueError:current=False
            acceptable=not (req['stage']=='f_review' and candidate['review']['verdict']=='needs_review')
            return self._reply(mode='abf_fixed_rehearsal',authorization_id=row['authorization_id'],stage=req['stage'],
                target_version=req['target_version'],revision=meta['revision'],candidate=candidate,candidate_digest=row['result_digest'],
                can_apply=current and not occupied and acceptable,stale=not current,already_applied=bool(app),
                application=json.loads(app[0]) if app else None,external_network_allowed=False,actual_model_cost=0,
                notice='核对采用只写入同一会话；待复核/已过时/已采用候选不会覆盖正式结果。')

    def _do_abf_apply(self,c,meta,body):
        expect(body['review_confirmed'] is True,'请先明确核对候选及来源。')
        row,req=self._abf_row(c,body['authorization_id'])
        expect(row['status']=='completed' and body['candidate_digest']==row['result_digest'],'候选未完成或摘要不一致。')
        expect(c.execute('SELECT 1 FROM wbf_applications WHERE stage=? AND target_version=?',(req['stage'],req['target_version'])).fetchone() is None,'此目标已有采用结果，不能覆盖。')
        expect(build_context(self,c,meta,req['stage'],req['target_version'])==req['context'],'会话来源或计划已变化，请保留旧候选。')
        candidate=json.loads(row['result_json']);stage=req['stage'];version=req['target_version'];next_version=version+1
        expect(stage!='f_review' or candidate['review']['verdict']!='needs_review','本份审查仍待复核，不能保存为通过。')
        app_id=bound_id(meta['session_id'],'abf_application',body['request_id']);record_id=app_id+':adopted'
        parents=[meta['session_id']+':input'] if stage=='a_diagnosis' else [meta['session_id']+':diagnosis'] if stage=='b_plan' and version==0 else [self._plan(c,version)['record_id']]
        if stage=='b_plan' and version:parents.append(self._review(c,version)['record_id'])
        app={'application_id':app_id,'authorization_id':row['authorization_id'],'scope':self._scope(meta),'input_digest':meta['input_digest'],
             'stage':stage,'target_version':version,'revision':meta['revision']+1,'record_id':record_id,
             'candidate_digest':row['result_digest'],'request_digest':row['request_digest'],'candidate_simulated':self._session_is_simulated(req),**self._session_provenance(req,row['authorization_id']),
             'review_confirmed':True,'parent_ids':parents,'notice':'已核对采用本地替身结果；不代表真实模型评价或真实学习效果。'}
        producer={'producer_contract':VERSION,'producer_application_id':app_id,'candidate_simulated':self._session_is_simulated(req),**self._session_provenance(req,row['authorization_id'])}
        if stage=='a_diagnosis':
            result=candidate['diagnosis'];bindings=candidate['bindings']
            c.execute("INSERT INTO competition_stages(stage,status,result_json,model_name) VALUES ('diagnosis','completed',?,?)",(encode(result),result['model_name']))
            from db_manager import DBManager
            import pandas as pd
            db=DBManager.__new__(DBManager);db.conn=c;db.cursor=c.cursor()
            db.save_gap_report(meta['report_id'],meta['trace_id'],'用户目标岗位',meta['inputs']['target_role'],result['audit']['match_score'],
                pd.DataFrame(result['audit']['gap_table']),result['audit'],scorer=DBManager.SCORER_MODEL_MATCH,commit=False)
            c.execute('UPDATE wb_meta SET bindings_json=? WHERE singleton=1',(encode(bindings),))
            formal_id=meta['session_id']+':diagnosis';formal={'report_id':meta['report_id'],'diagnosis':result,'bindings':bindings,**producer}
            kind='diagnosis'
        elif stage=='b_plan':
            formal=deepcopy(candidate['plan']);formal.update(producer);formal_id=meta['session_id']+':plan:'+str(next_version);kind='plan'
            c.execute('INSERT INTO wb_plans VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)',(next_version,formal_id,encode(formal),digest(formal),version or None))
            c.execute('UPDATE wb_meta SET active_version=? WHERE singleton=1',(next_version,))
            if version==0:
                for task in formal['tasks']:
                    day=(date.fromisoformat(meta['start_date'])+timedelta(days=task['day']-1)).isoformat()
                    c.execute('INSERT INTO wb_progress(task_id,status,start_date,end_date) VALUES (?,?,?,?)',(task['task_id'],'not_started',day,day))
        else:
            review_id=bound_id(meta['session_id'],'review',str(version));formal_id=meta['session_id']+':review:'+str(version);kind='plan_review'
            formal={**candidate['review'],**producer,'scope':self._scope(meta)}
            c.execute('INSERT INTO wb_reviews VALUES (?,?,?,?,?)',(review_id,version,req['context']['plan_digest'],encode(formal),formal_id))
        app.update(formal_record_id=formal_id,formal_result=deepcopy(formal))
        if getattr(self.agent_review,'actor',None)=='career_agent':
            app.update(review_actor='career_agent',notice='用户委托智能体调用，程序校验后自动保存；非本人逐条事实核实。')
        if stage=='b_plan':app['formal_plan_version']=next_version
        if stage=='f_review':app['formal_review_id']=review_id
        self._record(c,meta,record_id,kind,'核对采用 · '+stage,{'event':'abf_candidate_adopted',**app},parents,source='user_review')
        if stage=='b_plan':
            event={'version':next_version,'plan_digest':digest(formal),'task_count':len(formal['tasks']),**producer}
            if version:event.update(source_version=version,review_id=req['context']['review']['review_id'])
        elif stage=='f_review':event={'review_id':review_id,'plan_version':version,'plan_digest':req['context']['plan_digest'],**formal}
        else:event=formal
        self._record(c,meta,formal_id,kind,{'a_diagnosis':'A · 候选核对后的岗位诊断','b_plan':'B · 候选核对后的计划','f_review':'F · 候选核对后的审查'}[stage],event,[record_id])
        c.execute('INSERT INTO wbf_applications VALUES (?,?,?,?,?,?,?)',(app_id,row['authorization_id'],stage,version,app['revision'],encode(app),digest(app)))
        return {'application_id':app_id,'record_id':record_id,'formal_record_id':formal_id,'stage':stage,
                'formal_plan_version':app.get('formal_plan_version'),'formal_review_id':app.get('formal_review_id'),
                'mode':'abf_fixed_rehearsal','external_network_allowed':False,'actual_model_cost':0}

    def _abf_validate_records(self,c,meta):
        if not self._has_abf(c):return
        expect(c.execute('SELECT contract_version FROM wbf_policy').fetchone()[0]==VERSION,'A/B/F会话策略无效。')
        from competition_sessions import completed_result
        for row in c.execute('SELECT * FROM wbf_applications ORDER BY revision'):
            app=json.loads(row['payload_json']);expect(digest(app)==row['payload_digest'] and app['scope']==self._scope(meta)
                 and app['input_digest']==meta['input_digest'] and type(app['candidate_simulated']) is bool and app['review_confirmed'] is True,'A/B/F采用来源被改写。')
            expect(all(app[k]==row[k] for k in ('application_id','authorization_id','stage','target_version','revision')),'A/B/F采用索引被改写。')
            grant,req=self._abf_row(c,app['authorization_id']);candidate=json.loads(grant['result_json']) if grant['result_json'] else None
            expect(grant['status']=='completed' and grant['dispatch_count']==1 and req['stage']==app['stage'] and req['target_version']==app['target_version']
                and req['revision']<app['revision']<=meta['revision']
                and grant['result_digest']==app['candidate_digest'] and grant['request_digest']==app['request_digest'],'A/B/F采用不匹配原始回执。')
            event=c.execute('SELECT payload_json,parent_ids_json FROM wb_records WHERE record_id=?',(app['record_id'],)).fetchone()
            expect(event is not None and json.loads(event[0])=={'event':'abf_candidate_adopted',**app} and json.loads(event[1])==app['parent_ids'],'A/B/F采用记录缺失或变化。')
            expect(app['candidate_simulated']==self._session_is_simulated(req),'采用结果的真实/替身来源不一致。')
            expect(app.get('model_provenance')==self._session_provenance(req,app['authorization_id']).get('model_provenance'),'采用结果的模型来源回执不一致。')
            producer={'producer_contract':VERSION,'producer_application_id':app['application_id'],'candidate_simulated':self._session_is_simulated(req),**self._session_provenance(req,app['authorization_id'])}
            if app['stage']=='a_diagnosis':
                expected={'report_id':meta['report_id'],'diagnosis':candidate['diagnosis'],'bindings':candidate['bindings'],**producer}
                expect(completed_result(c,'diagnosis')==candidate['diagnosis'] and meta['bindings']==candidate['bindings'],'A正式结果与采用候选不同。')
                saved=c.execute('SELECT audit_json,trace_id,tis_score,scorer FROM job_gap_reports WHERE report_id=?',(meta['report_id'],)).fetchone()
                expect(saved is not None and json.loads(saved[0])==candidate['diagnosis']['audit'] and saved[1]==meta['trace_id']
                       and saved[2]==candidate['diagnosis']['audit']['match_score'] and saved[3]=='model_match','A诊断报告缺失或不同。')
            elif app['stage']=='b_plan':
                expected={**candidate['plan'],**producer}
                saved=c.execute('SELECT plan_json,plan_digest,parent_version,record_id FROM wb_plans WHERE version=?',(app['formal_plan_version'],)).fetchone()
                expect(saved and json.loads(saved[0])==expected and saved[1]==digest(expected) and saved[2]==(req['target_version'] or None)
                       and saved[3]==app['formal_record_id'] and app['formal_plan_version']==req['target_version']+1,'B正式计划与采用候选不同。')
            else:
                expected={**candidate['review'],**producer,'scope':self._scope(meta)}
                saved=c.execute('SELECT result_json,plan_digest,plan_version,record_id FROM wb_reviews WHERE review_id=?',(app['formal_review_id'],)).fetchone()
                expect(saved and json.loads(saved[0])==expected and saved[1]==req['context']['plan_digest'] and saved[2]==req['target_version']
                       and saved[3]==app['formal_record_id'],'F正式审查与采用候选不同。')
            expect(app['formal_result']==expected,'A/B/F正式快照与候选合成不同。')
            formal=c.execute('SELECT payload_json,parent_ids_json FROM wb_records WHERE record_id=?',(app['formal_record_id'],)).fetchone()
            expect(formal is not None and json.loads(formal[1])==[app['record_id']],'A/B/F正式来源记录缺失。')
            if app['stage']=='a_diagnosis':expected_event=expected
            elif app['stage']=='b_plan':
                expected_event={'version':app['formal_plan_version'],'plan_digest':digest(expected),'task_count':len(expected['tasks']),**producer}
                if req['target_version']:expected_event.update(source_version=req['target_version'],review_id=req['context']['review']['review_id'])
            else:expected_event={'review_id':app['formal_review_id'],'plan_version':req['target_version'],'plan_digest':req['context']['plan_digest'],**expected}
            expect(json.loads(formal[0])==expected_event,'A/B/F正式记录与采用快照不同。')

    def _abf_sdk_public(self,req):
        if not req.get('contract_sdk'):return {}
        import math
        conf=req['config'];chars=len(encode(req['payload']));allowance=len(encode(req['payload']).encode('utf-8'))+512
        rates=[conf['input_price_per_million'],conf['output_price_per_million']]
        return {'transport_kind':req['transport_kind'],'sdk_rehearsal':True,
            'input_limit_exceeded':chars>conf['max_input_chars'],
            'max_output_tokens':req['contract_sdk']['output_limit'],'estimated_input_tokens':math.ceil(chars/2),
            'input_token_allowance':allowance,'currency':conf['currency'],
            'estimated_cost':(math.ceil(chars/2)*rates[0]+req['contract_sdk']['output_limit']*rates[1])/1000000 if all(x is not None for x in rates) else None,
            'configured_cost_ceiling':(allowance*rates[0]+req['contract_sdk']['output_limit']*rates[1])/1000000 if all(x is not None for x in rates) else None,
            'transport_destination':'正式SDK → 本地HTTP替身，无外网/用户Key；真实外发关闭',
            'configured_destination':conf['base_url'],'provider':conf['provider'],'output_limit':req['contract_sdk']['output_limit']}

    def _abf_sdk_usage(self,req,response):
        if not req.get('contract_sdk'):return
        u=response.get('usage');cap=req['contract_sdk']['output_limit']
        if not isinstance(u,dict) or set(u)!={'prompt_tokens','completion_tokens','total_tokens'} or not all(type(x) is int and x>=0 for x in u.values()) or u['prompt_tokens']+u['completion_tokens']!=u['total_tokens']:
            raise ABFValidation('sdk_usage_invalid')
        if u['completion_tokens']>cap:raise ABFValidation('sdk_output_limit')
        if req['stage']=='f_review' and response.get('finish_reason')=='stop':
            try:raw=json.loads(response['content'])
            except (ValueError,TypeError):return
            sent=json.loads(req['payload']['messages'][1]['content'])['untrusted_context']['sources']
            if isinstance(raw,dict) and isinstance(raw.get('issues'),list):
                for item in raw['issues']:
                    if isinstance(item,dict):
                        for key in ('target_ref','evidence_ref'):
                            if isinstance(item.get(key),dict) and item[key].get('source_id') not in sent:raise ABFValidation('sdk_reference_not_sent')


    def _abf_state(self,c):
        if not self._has_abf(c):return {}
        return {'abf':{'mode':'abf_fixed_rehearsal','contract_version':VERSION,'simulated':True,'model_requests':0,
           'applications':[{k:r[k] for k in ('application_id','authorization_id','stage','target_version','revision')}
                           for r in c.execute('SELECT * FROM wbf_applications ORDER BY revision')],
           'notice':'A/B/F候选已按同一会话采用；本批仅本地替身，真实SDK与页面调用操作另行接入。'}}
