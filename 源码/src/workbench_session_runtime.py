"""Opt-in immutable A/B/C/D/E/F session runtime and common reservation ledger.

Legacy protocol modes stay backward compatible. execution_mode and the receipt's
provenance, not those protocol names, identify the actual transport. Local course
and mastery projections remain demonstrations, even after genuine model calls.
"""
from contextlib import closing
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING
import json
from competition_workbench_assessment import encode,digest,expect
from workbench_contract_sdk import ContractSDKBridge
from abf_contracts import ABFValidation
from ced_contracts import CEDValidation,payload
from sdk_transport import SDKFailure

VERSION='session-runtime-v1'
STAGES=('a_diagnosis','b_plan','f_review','c_question','c_grade','d_revision','e_turn','e_report')
RUNTIME_OPERATIONS={'session_runtime_open':{'execution_mode','budget_micro_cny'}}

def charge(tokens,rate):return int((Decimal(tokens)*Decimal(str(rate))).to_integral_value(rounding=ROUND_CEILING))

class SessionABFRouter:
    """Installed as a FixedABFTransport subtype by init_runtime, no global switching."""
    pass

class WorkbenchSessionRuntime:
    def _init_runtime(self,preparation=None,*,outbound_enabled=False,http_client_factory=None):
        expect(type(outbound_enabled) is bool,'真实外发开关无效。')
        self.session_preparation=preparation;self.session_outbound_enabled=outbound_enabled
        self.session_http_client_factory=http_client_factory
        if preparation:
            from workbench_abf import FixedABFTransport
            fallback=self.abf_transport;owner=self
            class Router(FixedABFTransport):
                def freeze(self,req):return fallback.freeze(req) if hasattr(fallback,'freeze') else req
                def send(self,req):return owner._session_send(req) if req.get('session_runtime') else fallback.send(req)
            self.abf_transport=Router()

    @staticmethod
    def _has_runtime(c):return bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='wsr_policy'").fetchone())

    def _session_policy(self,c,meta):
        if not self._has_runtime(c):return None
        row=c.execute('SELECT * FROM wsr_policy WHERE singleton=1').fetchone()
        expect(row is not None,'会话运行策略缺失。');p=json.loads(row['policy_json'])
        expect(digest(p)==row['policy_digest'] and p['version']==VERSION and p['scope']==self._scope(meta)
            and p['input_digest']==meta['input_digest'] and p['execution_mode'] in ('local_sdk_rehearsal','real_model')
            and type(p['budget_micro_cny']) is int and 0<p['budget_micro_cny']<=100000000,'运行策略来源不一致。')
        record=c.execute('SELECT payload_json FROM wb_records WHERE record_id=?',(row['record_id'],)).fetchone()
        expect(record and json.loads(record[0])=={'event':'session_runtime_open','policy':p},'运行策略记录缺失或变化。')
        return p

    def _do_session_runtime_open(self,c,meta,body):
        mode=body['execution_mode'];limit=body['budget_micro_cny']
        expect(self.case_profile=='final-20261107' and meta['package'].get('personal_input') and self.session_preparation is not None,
            '请在当前版新建个人资料会话后设置运行模式。')
        expect(mode in ('local_sdk_rehearsal','real_model') and type(limit) is int and 0<limit<=100000000,'请选择有效模式及大于0、不超过100元的会话额度。')
        from judge_client import sponsored_policy
        sponsor=sponsored_policy(self.session_preparation)
        if mode=='real_model' and sponsor and 'session_budget_micro_cny' in sponsor:
            expect(limit<=sponsor['session_budget_micro_cny'],'本会话额度超过作者预置上限。')
        expect(not self._has_runtime(c) and not self._has_ce(c),'模式和预算一经确认不能切换、重置或扩额；请另建会话。')
        for table in ('wbf_previews','wbc_previews','wba_runs','wbi_runs','wbd_reports'):
            expect(not c.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone() or c.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,
                '请在首次模型预览前设置；已有旧调用或练习的会话不能混入新账本。')
        expect(meta['diagnosis'] is None,'已有诊断的会话不能追认费用；请新建个人资料会话。')
        with self.session_preparation.lock:current=self.session_preparation._read()
        conf=current['config']
        expect(conf['currency']=='CNY' and conf['model'] and conf['base_url'],'请先在本机保存模型、服务商地址与人民币单价。')
        for name in ('input_price_per_million','output_price_per_million'):
            v=conf[name]
            expect(type(v) in (int,float) and Decimal(str(v)).is_finite() and 0<Decimal(str(v))<=1000000,'请先填写有效的输入/输出单价；不会用零价格放行。')
        p={'version':VERSION,'scope':self._scope(meta),'input_digest':meta['input_digest'],'execution_mode':mode,
            'budget_micro_cny':limit,'config_revision':current['revision'],'config_digest':digest(conf),
            'input_rate':conf['input_price_per_million'],'output_rate':conf['output_price_per_million'],
            'currency':'CNY','notice':'额度按冻结配置单价与保守token预留控制，平台实际账单需另核对；未知用量不清零。'}
        c.execute('CREATE TABLE wsr_policy(singleton INTEGER PRIMARY KEY CHECK(singleton=1),policy_json TEXT NOT NULL,policy_digest TEXT NOT NULL,record_id TEXT NOT NULL)')
        c.execute('CREATE TABLE wsr_reservations(authorization_id TEXT PRIMARY KEY,family TEXT NOT NULL,stage TEXT NOT NULL,slot_key TEXT NOT NULL,request_digest TEXT NOT NULL,reserve_micro_cny INTEGER NOT NULL)')
        rid=meta['session_id']+':session-runtime';c.execute('INSERT INTO wsr_policy VALUES(1,?,?,?)',(encode(p),digest(p),rid))
        self._record(c,meta,rid,'plan_review','A/B/C/D/E/F · 会话模式与累计额度',{'event':'session_runtime_open','policy':p},[meta['session_id']+':input'])
        return {'execution_mode':mode,'budget_policy_digest':digest(p),'notice':'仅保存模式与累计额度，未授权任何模型请求。'}

    def _session_bridge(self,mode):
        expect(self.session_preparation is not None,'当前服务尚未配置同会话SDK。')
        return ContractSDKBridge(self.session_preparation,rehearsal=mode=='local_sdk_rehearsal',
            outbound_enabled=self.session_outbound_enabled if mode=='real_model' else False,
            http_client_factory=self.session_http_client_factory)

    def _session_freeze(self,c,meta,request,p):
        from judge_client import sponsored_policy
        sponsored=sponsored_policy(self.session_preparation) if self.session_preparation else None
        if sponsored and p['execution_mode']=='real_model':
            expect(request['stage'] in sponsored['supported_stages'],'评委赞助额度仅开放A/D及服务端已启用的E短面试；其他工具可查看完整案例或本地模拟。')
        if request['stage']=='a_diagnosis':
            from a_source_selection import prepare_request
            request=prepare_request(request)
        elif request['stage']=='b_plan':
            request=deepcopy(request)
            request['b_source_policy']='mixed-plan-sources-v1'
        if request['stage'] in ('b_plan','f_review'):
            from fixed_learning_time import prepare_request as prepare_fixed_time
            request=prepare_fixed_time(request)
        req=self._session_bridge(p['execution_mode']).freeze(request)
        unified=getattr(self.session_preparation,'unified',False)
        expect(unified or req['config_revision']==p['config_revision'] and digest(req['config'])==p['config_digest'],
            '模型配置或单价已变化，旧会话额度不可换价使用；请保留记录并新建会话。')
        input_rate=req['config']['input_price_per_million'] if unified else p['input_rate']
        output_rate=req['config']['output_price_per_million'] if unified else p['output_rate']
        allowance=len(encode(req['payload']).encode('utf-8'))+2048
        cap=req['contract_sdk']['output_limit']
        slot=(str(req['target_version']) if req['stage'] in ('a_diagnosis','b_plan','f_review') else self._adoption_key(req))
        simulated=p['execution_mode']=='local_sdk_rehearsal' or self.session_http_client_factory is not None
        req['contract_sdk']['http_intercepted']=self.session_http_client_factory is not None
        req['session_runtime']={'version':VERSION,'scope':req['scope'],'policy_digest':digest(p),'execution_mode':p['execution_mode'],
            'simulated':simulated,'input_token_allowance':allowance,'output_limit':cap,'slot_key':slot,
            'reserve_micro_cny':charge(allowance,input_rate)+charge(cap,output_rate)}
        if unified:req['session_runtime'].update(pricing_version='per-request-v1',input_rate=input_rate,output_rate=output_rate)
        return req

    def _abf_request(self,c,meta,stage,version):
        req=super()._abf_request(c,meta,stage,version);p=self._session_policy(c,meta)
        return self._session_freeze(c,meta,req,p) if p else req

    def _ce_request(self,c,meta,stage,target):
        p=self._session_policy(c,meta)
        if not p:return super()._ce_request(c,meta,stage,target)
        expect(stage in STAGES[3:],'请选择当前题目、答卷、面试或简历建议。')
        ctx=self._call_context(c,meta,stage,target)
        with self.session_preparation.lock:config=self.session_preparation._read()
        req={'contract_version':'ced-contract-v1','mode':'ced_fixed_rehearsal','stage':stage,'target_id':target,
            'scope':self._scope(meta),'revision':meta['revision'],'context':ctx,'boot_id':self.call_boot_id,
            'automatic_retries':0,'payload':payload(stage,ctx,config['config'])}
        from ced_contracts import VERSION as CED_VERSION
        req['contract_version']=CED_VERSION
        if stage=='d_revision':req['output_control']=self._d_output_control(config['config'])
        return self._session_freeze(c,meta,req,p)

    def _ce_context(self,c,meta,stage,ctx):
        ctx=super()._ce_context(c,meta,stage,ctx)
        if self._has_runtime(c) and stage=='c_question' and ctx['question_rules'].get('experience_policy')!='single-feedback-v1':
            old=[a['question']['prompt'] for a in self._answer_rows(c,meta) if set(ctx['topic_keys']).intersection(a['topic_keys'])]
            ctx['question_rules']['avoid_prompts']=list(dict.fromkeys(ctx['question_rules']['avoid_prompts']+old))
            expect(len(ctx['question_rules']['avoid_prompts'])<=64,'题目历史超出范围，停止生成而不丢弃禁用题面。')
        return ctx

    def _session_send(self,req):
        runtime=req['session_runtime']
        bridge=self._session_bridge(runtime['execution_mode'])
        expect(runtime['simulated']==(bridge.rehearsal or bridge.http_client_factory is not None),'执行器与冻结来源不一致。')
        if not bridge.rehearsal and not bridge.outbound_enabled:raise SDKFailure('outbound_disabled')
        response=bridge.send(deepcopy(req))
        # ABF's existing transport envelope is deliberately only three fields.
        return {k:response[k] for k in ('content','finish_reason','usage')}

    def _ce_dispatch(self,req):return self._session_send(req) if req.get('session_runtime') else super()._ce_dispatch(req)

    @staticmethod
    def _session_is_simulated(req):return req.get('session_runtime',{}).get('simulated',True)

    def _session_provenance(self,req,aid):
        r=req.get('session_runtime')
        if not r:return {}
        return {'model_provenance':{'version':VERSION,'execution_mode':r['execution_mode'],'simulated':r['simulated'],
            'source_kind':'sdk_http_rehearsal' if r['simulated'] else 'real_model_output',
            'execution_receipt_id':aid,'request_digest':digest(req),'scope':req['scope'],
            'provider':req['config']['provider'],'model':req['config']['model']}}

    def _session_public(self,req):
        r=req.get('session_runtime')
        if not r:return {}
        simulated=r['simulated'];real=r['execution_mode']=='real_model'
        return {'source_kind':'competition_workbench_session','scope':req['scope'],'run_mode':'real' if real else 'demo',
            'mode':'session_real_model' if real else 'session_sdk_rehearsal','simulated':simulated,
            'execution_mode':r['execution_mode'],'session_runtime':deepcopy(r),'authorization_field':'accept_session_once',
            'config_revision':req['config_revision'],
            'real_dispatch_enabled':real and self.session_outbound_enabled,'external_network_allowed':real and self.session_outbound_enabled and not simulated,
            'actual_model_cost':0 if simulated else None,'model_requests':0 if simulated else None,
            'sdk_rehearsal':simulated,'transport_destination':'本地HTTP替身，不读取用户Key' if simulated else req['config']['base_url'],
            'transport_kind':req['transport_kind'],'notice':'候选来源按本次回执标注；预览/授权不执行，采用不再次调用。实际账单待平台核对。'}

    def _abf_view(self,row,req):
        v=super()._abf_view(row,req);v.update(self._session_public(req));v.update(self._session_provenance(req,row['authorization_id']))
        return v

    def _call_view(self,row,req):
        v=super()._call_view(row,req);v.update(self._session_public(req));v.update(self._session_provenance(req,row['authorization_id']))
        if req.get('session_runtime'):
            v['provider_request_attempted']=bool(row['dispatch_count']) and not self._session_is_simulated(req)
        return v

    def _session_check_saved(self,c,row,req,family):
        r=req.get('session_runtime')
        if not r:
            expect(not self._has_runtime(c),'新模式会话不允许未计入账本的旧授权。');return
        meta=self._meta_base_for_runtime(c);p=self._session_policy(c,meta)
        per_request=r.get('pricing_version')=='per-request-v1'
        expect(p and r['version']==VERSION and r['policy_digest']==digest(p) and r['execution_mode']==p['execution_mode']
            and req['scope']==p['scope'] and (per_request or req['config_revision']==p['config_revision'] and digest(req['config'])==p['config_digest']),
            '调用与会话模式/单价不一致。')
        input_rate=r['input_rate'] if per_request else p['input_rate']
        output_rate=r['output_rate'] if per_request else p['output_rate']
        if per_request:
            expect(input_rate==req['config']['input_price_per_million'] and output_rate==req['config']['output_price_per_million'],
                   '调用冻结单价与本次模型配置不一致。')
        expect(req['sdk_policy']=={'rehearsal':p['execution_mode']=='local_sdk_rehearsal'}
            and r['simulated']==(req['sdk_policy']['rehearsal'] or req['contract_sdk'].get('http_intercepted',False))
            and req['transport_kind']==('sdk_http_rehearsal' if req['sdk_policy']['rehearsal'] else 'session_sdk'),
            '传输来源与冻结的真实/替身标记不一致。')
        reserve=c.execute('SELECT * FROM wsr_reservations WHERE authorization_id=?',(row['authorization_id'],)).fetchone()
        allowance=len(encode(req['payload']).encode('utf-8'))+2048;cap=req['contract_sdk']['output_limit']
        expect(reserve and reserve['family']==family and reserve['stage']==req['stage'] and reserve['request_digest']==digest(req)==row['request_digest']
            and reserve['slot_key']==r['slot_key'] and allowance==r['input_token_allowance'] and cap==r['output_limit']
            and reserve['reserve_micro_cny']==r['reserve_micro_cny']==charge(allowance,input_rate)+charge(cap,output_rate),
            '授权预留缺失、来源变化或费用未完整计入。')

    def _meta_base_for_runtime(self,c):
        return self._meta(c)

    def _session_ledger(self,c,meta):
        p=self._session_policy(c,meta)
        if not p:return None
        entries=[];spent=held=unknown=overrun=0
        for family,table in (('abf','wbf'),('ced','wbc')):
            has=c.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table+'_grants',)).fetchone()
            rows=c.execute(f'SELECT g.*,p.request_json,p.request_digest,p.expires_at FROM {table}_grants g JOIN {table}_previews p USING(preview_id) ORDER BY g.rowid').fetchall() if has else []
            for raw in rows:
                row=dict(raw);req=json.loads(row['request_json']);self._session_check_saved(c,row,req,family)
                r=req['session_runtime'];usage=None;cost=None
                if not row['dispatch_count']:
                    configuration_current=not getattr(self.session_preparation,'unified',False) or req['config_revision']==self.session_preparation._read()['revision']
                    state='held_unconsumed' if configuration_current and row['status']=='authorized' and row['expires_at']>self.call_clock() else 'released_unconsumed'
                    exposure=r['reserve_micro_cny'] if state=='held_unconsumed' else 0;held+=exposure
                else:
                    expect(row['dispatch_count']==1,'单次授权派发次数异常。')
                    response=json.loads(row['response_json']) if row['response_json'] else None
                    if response is not None:expect(digest(response)==row['response_digest'],'用量响应摘要不一致。')
                    usage=self._ce_usage(req,response)
                    if usage is None:state='consumed_usage_unconfirmed';exposure=r['reserve_micro_cny'];unknown+=exposure
                    else:
                        cost=charge(usage['prompt_tokens'],r.get('input_rate',p['input_rate']))+charge(usage['completion_tokens'],r.get('output_rate',p['output_rate']))
                        exposure=cost;spent+=cost;state='settled_simulated_usage' if r['simulated'] else 'settled_provider_usage'
                        if usage['prompt_tokens']>r['input_token_allowance'] or usage['completion_tokens']>r['output_limit'] or cost>r['reserve_micro_cny']:
                            overrun+=max(1,cost-r['reserve_micro_cny']);state='usage_exceeds_reservation'
                entries.append({'authorization_id':row['authorization_id'],'stage':req['stage'],'family':family,'slot_key':r['slot_key'],
                    'status':state,'dispatch_attempts':row['dispatch_count'],'simulated':r['simulated'],
                    'reserve_micro_cny':r['reserve_micro_cny'],'charge_micro_cny':cost,'budget_exposure_micro_cny':exposure,'usage':usage})
        expect(len(entries)==c.execute('SELECT count(*) FROM wsr_reservations').fetchone()[0],'累计账本有缺失或多余的授权预留。')
        return {'version':VERSION,'scope':p['scope'],'execution_mode':p['execution_mode'],'limit_micro_cny':p['budget_micro_cny'],
            'spent_micro_cny':spent,'held_unconsumed_micro_cny':held,'consumed_unconfirmed_micro_cny':unknown,'overrun_micro_cny':overrun,
            'overspent_micro_cny':max(0,spent+held+unknown-p['budget_micro_cny']),
            'available_micro_cny':max(0,p['budget_micro_cny']-spent-held-unknown),'entries':entries,
            'actual_model_cost':0 if all(e['simulated'] for e in entries) else None,'notice':p['notice']}

    def _session_before_authorize(self,c,req):
        if not req.get('session_runtime'):return
        if req['session_runtime']['execution_mode']=='real_model':
            expect(self.session_outbound_enabled,'当前服务真实外发关闭，不能授权真实请求；本轮请用本地SDK替身。')
        for prefix in ('wbf','wbc'):
            if c.execute('SELECT 1 FROM sqlite_master WHERE name=?',(prefix+'_grants',)).fetchone():
                c.execute(f"UPDATE {prefix}_grants SET status='invalidated' WHERE dispatch_count=0 AND status='authorized' AND (boot_id<>? OR preview_id IN (SELECT preview_id FROM {prefix}_previews WHERE expires_at<=?))",(self.call_boot_id,self.call_clock()))
                if getattr(self.session_preparation,'unified',False):
                    revision=self.session_preparation._read()['revision']
                    c.execute(f"UPDATE {prefix}_grants SET status='invalidated' WHERE dispatch_count=0 AND status='authorized' AND preview_id IN (SELECT preview_id FROM {prefix}_previews WHERE json_extract(request_json,'$.config_revision')<>?)",(revision,))
        b=self._session_ledger(c,self._meta_base_for_runtime(c));r=req['session_runtime']
        expect(not b['overrun_micro_cny'] and not b['overspent_micro_cny'],'用量或预算异常，停止新增授权。')
        expect(not any(e['stage']==req['stage'] and e['slot_key']==r['slot_key'] and e['status']!='released_unconsumed' for e in b['entries']),
            '当前目标已预留或消费一次，请查询原回执；不能通过换预览重复调用。')
        expect(r['reserve_micro_cny']<=b['available_micro_cny'],'A/B/C/D/E/F同会话累计额度不足，未授权、未派发。')

    def _session_on_authorized(self,c,req,aid,family):
        if req.get('session_runtime'):
            r=req['session_runtime'];c.execute('INSERT INTO wsr_reservations VALUES(?,?,?,?,?,?)',(aid,family,req['stage'],r['slot_key'],digest(req),r['reserve_micro_cny']))

    def _session_before_dispatch(self,c,req,aid):
        if not req.get('session_runtime'):return
        if req['session_runtime']['execution_mode']=='real_model':expect(self.session_outbound_enabled,'当前服务已关闭真实外发，未派发。')
        b=self._session_ledger(c,self._meta_base_for_runtime(c));e=next((e for e in b['entries'] if e['authorization_id']==aid),None)
        expect(e and e['status']=='held_unconsumed' and not b['overrun_micro_cny'] and not b['overspent_micro_cny'],'原费用预留失效或累计用量异常，未派发。')

    def _session_validate_usage(self,req,response,error):
        r=req.get('session_runtime')
        if r:
            u=self._ce_usage(req,response)
            if u is None:raise error('session_usage_missing_or_invalid')
            if u['prompt_tokens']>r['input_token_allowance'] or u['completion_tokens']>r['output_limit']:raise error('session_usage_exceeds_reservation')

    def _abf_sdk_usage(self,req,response):
        self._session_validate_usage(req,response,ABFValidation);return super()._abf_sdk_usage(req,response)

    def _ce_validate_response(self,req,response):
        self._session_validate_usage(req,response,CEDValidation);return super()._ce_validate_response(req,response)

    def _ce_check_saved_call(self,c,row,req):
        if req.get('session_runtime'):self._session_check_saved(c,row,req,'ced')
        else:super()._ce_check_saved_call(c,row,req)

    def _ce_guard(self,c,meta,operation,body):
        if not self._has_runtime(c):return super()._ce_guard(c,meta,operation,body)
        expect(operation!='ce_budget_open','本会话已使用共同累计额度，不能再开C/E独立账本。')
        if operation in ('assessment_start','retest_start'):expect(meta['published_version'],'请先采用A/B结果，并在学习计划完成程序校验与确认发布。')
        if operation=='answer':
            run=self._saved_run(c,meta,body['run_id']);expect(self._application_for(c,meta,'c_question',run['questions'][run['cursor']]['question_id']),'请先核对采用当前题目。')
        elif operation=='interview_answer':
            run=self._interview_run(c,meta,body['interview_id']);expect(self._application_for(c,meta,'e_turn',run['current_question_id']),'请先核对采用当前面试问题。')


    def _ce_report_pending(self,c,report):
        if not self._has_runtime(c):return super()._ce_report_pending(c,report)
        report=deepcopy(report);report.update(review_status='pending_candidate_review',issue_count=0,clear_sample_count=0,notice='本场复盘待单次生成和核对；不使用内置反馈代替模型分析。')
        for f in report['findings']:f.update(analysis_kind='review_required',observation='待复盘核对',suggestion='',quote='',evidence=[],issue=None)
        return report

    def _session_validate_records(self,c,meta):
        if self._has_runtime(c):self._session_ledger(c,meta)

    def _session_container(self,c,meta,v):
        if meta['package'].get('personal_input'):
            current=self.session_preparation._read() if self.session_preparation else {'config':{},'encrypted_key':''}
            config=current['config']
            v['runtime_capabilities']={'version':VERSION,'outbound_enabled':self.session_outbound_enabled,
                'sdk_available':self.session_preparation is not None,
                'model_configured':bool(current['encrypted_key'] and config.get('model') and config.get('base_url')
                    and config.get('currency')=='CNY' and all(type(config.get(name)) in (int,float) and config[name]>0 for name in ('input_price_per_million','output_price_per_million'))),
                'provider':config.get('provider',''),'model':config.get('model',''),'config_revision':current['revision'] if self.session_preparation else None}
            from judge_client import sponsored_policy
            v['runtime_capabilities']['sponsored_gateway']=sponsored_policy(self.session_preparation) if self.session_preparation else None
        b=self._session_ledger(c,meta)
        if b:
            p=self._session_policy(c,meta);real=p['execution_mode']=='real_model';simulated=not real or self.session_http_client_factory is not None
            v.update(source_kind='competition_workbench_session',run_mode='real' if real else 'demo',simulated=simulated,
                real_dispatch_enabled=real and self.session_outbound_enabled,model_requests=0 if simulated else None,
                session_runtime={**b,'simulated':simulated,'outbound_enabled':self.session_outbound_enabled,'all_agents':['A','B','C','D','E','F'],'active_agents':['A','B','C','D','E'],'deferred_agents':['F']},
                notice='个人会话；模型结果来源按各调用回执标注。课程参考与本地能力投影仍非真实掌握证明。')
            if v.get('diagnosis') and self._has_abf(c):
                row=c.execute("SELECT payload_json FROM wbf_applications WHERE stage='a_diagnosis'").fetchone()
                if row:
                    app=json.loads(row[0]);v['diagnosis'].update(candidate_simulated=app['candidate_simulated'],model_provenance=app['model_provenance'])
        return v

    def _abf_state(self,c):
        v=super()._abf_state(c)
        if v and self._has_runtime(c):
            p=self._session_policy(c,self._meta(c));simulated=p['execution_mode']!='real_model' or self.session_http_client_factory is not None
            v['abf'].update(mode='session_real_model' if p['execution_mode']=='real_model' else 'session_sdk_rehearsal',
                simulated=simulated,notice='本会话候选流程；各次模型来源及费用以单次回执和共同账本为准。')
        return v

    def state(self,token):
        v=self._fixed_state(token)
        v['competition_flow']={'plan_release':'program-confirm-v1','active_agents':['A','B','C','D','E'],'deferred_agents':['F'],'daily_minutes':60}
        with self.lock,closing(self._connect(token)) as c:
            meta=self._meta(c)
            if meta['package'].get('personal_input'):v['saved_b_recovery']=self._saved_b_available(c,meta)
            return self._session_container(c,meta,v)

    def records(self,token):
        v=self._fixed_records(token)
        with self.lock,closing(self._connect(token)) as c:return self._session_container(c,self._meta(c),v)

    def session_budget(self,token):
        with self.lock,closing(self._connect(token)) as c:
            meta=self._meta(c);return self._session_container(c,meta,self._reply(scope=self._scope(meta),session_runtime=None))

    def _session_attach(self,token,value,family):
        prefix='wbf' if family=='abf' else 'wbc'
        with self.lock,closing(self._connect(token)) as c:
            if value.get('authorization_id'):
                row,req=(self._abf_row if family=='abf' else self._call_row)(c,value['authorization_id'])
                value.update(self._session_public(req));value.update(self._session_provenance(req,value['authorization_id']))
            elif value.get('preview_id'):
                row=c.execute(f'SELECT request_json FROM {prefix}_previews WHERE preview_id=?',(value['preview_id'],)).fetchone()
                if row:value.update(self._session_public(json.loads(row[0])))
        return value

    def abf_preview(self,token,body):return self._session_attach(token,super().abf_preview(token,body),'abf')
    def call_preview(self,token,body):return self._session_attach(token,super().call_preview(token,body),'ced')
    def abf_adoption_preview(self,token,body):return self._session_attach(token,super().abf_adoption_preview(token,body),'abf')
    def call_adoption_preview(self,token,body):return self._session_attach(token,super().call_adoption_preview(token,body),'ced')

    def _do_abf_apply(self,c,meta,body):
        result=super()._do_abf_apply(c,meta,body);_,req=self._abf_row(c,body['authorization_id'])
        result.update(self._session_public(req));return result

    def _do_candidate_apply(self,c,meta,body):
        result=super()._do_candidate_apply(c,meta,body);_,req=self._call_row(c,body['authorization_id'])
        result.update(self._session_public(req));return result
