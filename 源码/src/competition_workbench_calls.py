"""One-use C/E/D calls. Candidate outputs stay isolated."""
from contextlib import closing
from copy import deepcopy
import hashlib,json,math,sqlite3,time,uuid
from competition_workbench_assessment import encode,digest,expect,invalid
from model_preparation import DEFAULT
from sdk_transport import SDKFailure, SDKTransport
from ced_contracts import VERSION,STAGES,payload,validate_result,fixed_output,CEDValidation

CALL_ACTIONS={'call_preview','call_authorize','call_execute','call_status','call_recover','call_adoption_preview'}
TRANSPORT_LABELS={
    'session_sdk':'当前会话的真实SDK传输，受单次授权和累计额度约束',
    'ced_trial_sdk':'独立 C/E/D 验收 SDK，目标为预览中列出的服务商',
    'in_process_fixed':'进程内固定响应，无 SDK、外网或 Key 读取',
    'sdk_http_rehearsal':'正式 SDK 构造 HTTP 请求，由本地替身拦截；真实外发关闭',
}
SDK_RESPONSE_ERRORS={'truncated','incomplete','invalid_response','empty_response','unsupported_tools','output_limit'}

class FixedCEDTransport:
    mode='ced_fixed_rehearsal'
    kind='in_process_fixed'
    def send(self,request):
        expect(request['mode']==self.mode,'本轮只允许固定传输预演。')
        return {'content':encode(fixed_output(request)),'finish_reason':'stop','usage':None}

class _CEDRehearsalWire(SDKTransport):
    def _mock_response(self,request,_meta,_diagnosis):
        content=encode(fixed_output(request))
        return {'content':content,'finish_reason':'stop','synthetic_output_tokens':math.ceil(len(content)/2)}


class CEDSDKTransport(FixedCEDTransport):
    """Use the installed SDK with an intercepted wire and synthetic Key."""
    kind='sdk_http_rehearsal'

    def __init__(self,preparation):
        self.preparation=preparation

    def send(self,request):
        expect(request['mode']==self.mode and request.get('transport_kind')==self.kind,
               '授权的传输类型与本地 SDK 预演不一致。')
        sdk_request={**request,'sdk_policy':{'rehearsal':True},'timeout_seconds':request['config']['timeout_seconds']}
        return _CEDRehearsalWire(self.preparation,rehearsal=True,outbound_enabled=False).send(sdk_request,None,None)


def uid(value):
    try:return str(uuid.UUID(value))
    except (ValueError,TypeError,AttributeError):invalid('调用身份格式无效。')
def fields(body,keys):
    if not isinstance(body,dict) or set(body)!=set(keys):invalid('调用请求字段不完整或包含额外内容。')
def default_config():return {'revision':0,'config':deepcopy(DEFAULT),'encrypted_key':None}

class WorkbenchCalls:
    def _init_calls(self,configuration=None,transport=None,boot_id=None,clock=None):
        self.call_configuration=configuration or default_config
        self.call_transport=transport or FixedCEDTransport()
        if (not isinstance(self.call_transport,FixedCEDTransport)
                or self.call_transport.kind not in TRANSPORT_LABELS
                or self.call_transport.mode != self._call_mode(self.call_transport.kind)):
            invalid('C/E/D 传输模式无效。')
        self.call_boot_id=boot_id or str(uuid.uuid4());self.call_clock=clock or time.time;self.call_active=set()

    @staticmethod
    def _call_mode(kind):
        return 'ced_trial' if kind=='ced_trial_sdk' else 'ced_fixed_rehearsal'

    def _d_output_control(self,settings):
        from ced_output_control import d_controls
        return d_controls(settings)

    def _call_request_policy(self,request):
        return {}

    def _call_check_authorization(self,c,request):
        pass

    def _call_schema(self,c):
        c.execute('CREATE TABLE IF NOT EXISTS wbc_previews(preview_id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,body_digest TEXT NOT NULL,request_json TEXT NOT NULL,request_digest TEXT NOT NULL,expires_at REAL NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS wbc_grants(authorization_id TEXT PRIMARY KEY,preview_id TEXT NOT NULL UNIQUE,boot_id TEXT NOT NULL,status TEXT NOT NULL,dispatch_count INTEGER NOT NULL DEFAULT 0,response_json TEXT,response_digest TEXT,result_json TEXT,error_json TEXT,FOREIGN KEY(preview_id) REFERENCES wbc_previews(preview_id))')

    def _call_context(self,c,meta,stage,target):
        sources={}
        def source(sid,text,kind='self_report',usage='context_only'):
            sources[sid]={'text':text,'kind':kind,'usage':usage,'simulated':True};return sid
        context={'scope':self._scope(meta),'input_digest':meta['input_digest'],'session_revision':meta['revision'],'sources':sources}
        if stage in ('c_question','c_grade'):
            if stage=='c_question':
                run=self._saved_run(c,meta,target);need_active=run['status']=='active'
                expect(need_active,'只为进行中考核当前一个待答槽位预演出题。')
                q=run['questions'][run['cursor']]
                answers=self._answer_rows(c,meta)
                expect(not any(a['question_id']==q['question_id'] for a in answers),'当前题已答；下一题需显式准备后再预演。')
                topics=list(dict.fromkeys(p['topic_key'] for p in q['parts']))
                avoided=[q['prompt']]
                parent=next((a for a in answers if a['attempt_id']==run['source_attempt_id']),None)
                if parent:
                    avoided.append(parent['question']['prompt'])
                avoided.extend(a['question']['prompt'] for a in reversed(answers) if set(topics).intersection(a['topic_keys']))
                context.update(run_id=run['run_id'],target_question_id=q['question_id'],topic_keys=topics,
                    question_rules={'output_contract':'server-owned-fields-v2','difficulty':'beginner','allowed_topic_keys':topics,'avoid_prompts':list(dict.fromkeys(avoided))[:4]})
                plan=self._plan(c,run['plan_version'])['plan'];ids={p['task_id'] for p in q['parts']}
                context['learning_tasks']=[{'task_id':t['task_id'],'title':t['title'],'expected_outcome':t['expected_outcome'],
                    'topic_keys':[key for key in t['topic_keys'] if key in topics]} for t in plan['tasks'] if t['task_id'] in ids]
                from competition_short_flow import daily_rules
                daily_rules(context,run,answers)
            else:
                answer=next((a for a in self._answer_rows(c,meta) if a['attempt_id']==target),None)
                expect(answer is not None,'请先保存本会话答卷，评分授权只对应这一份答卷。')
                q=answer['question'];sid=source(answer['attempt_id'],answer['answer'],'user_answer','grade_this_answer_only')
                context.update(attempt_id=target,question_id=q['question_id'],question=q['prompt'],answer_source_id=sid,
                    topic_keys=answer['topic_keys'],rubrics=[deepcopy(p['rubric']) for p in q['parts']],
                    reference_outlines=[{'topic_key':p['topic_key'],'text':p['reference'],'kind':'curated_demo_reference'} for p in q['parts']])
                # Fixed route, existing score/mastery and fixture_path are deliberately excluded.
        elif stage in ('e_turn','e_report'):
            r=self._interview_run(c,meta,target);turns=self._interview_turns(c,meta,r)
            context.update(interview_id=target,position=deepcopy(r['context']['position']),candidate=deepcopy(r['context']['candidate']),
                jd_requirements=deepcopy(r['context']['jd_requirements']),max_followups=r['max_followups'],planned_main=len(r['main_keys']))
            if 'learning_summary' in r['context']:
                summary=r['context']['learning_summary']
                context['learning_summary']={'plan_version':summary['plan_version'],'progress':deepcopy(summary['progress']),
                    'notice':'只提供进度，不提供固定分数、演示掌握状态、笔记或答卷正文，不能当作已验证能力。'}
            if r['bank'].get('requirement_contract'):
                context['personal_interview_contract']=r['bank']['requirement_contract']
            if stage=='e_turn':
                expect(r['status']=='active','面试已结束，只能预演结束复盘。')
                q=turns[-1];expect(q['role']=='assistant' and q['turn_id']==r['current_question_id'],'面试当前待答槽位不一致。')
                history=turns[:-1];parent=next((t['turn_id'] for t in reversed(history) if t['role']=='user'),None)
                # Slot identity is server planned. A provider cannot silently extend scope/budget.
                context.update(pending_question_id=q['turn_id'],seed_prompt=q['text'],
                    pending_slot={'question_kind':'followup' if q['is_followup'] else 'main','main_index':q['main_index'],
                        'parent_answer_id':parent,'requirement_ids':q['requirement_ids']},
                    followups_before_slot=sum(t['role']=='assistant' and t['is_followup'] for t in history))
            else:
                expect(r['status']!='active','先显式结束面试，再预演问题分析与建议。')
                report=self._interview_report(c,meta,r,turns);history=turns;context['coverage']=deepcopy(report['coverage'])
                context['answer_turn_ids']=[t['turn_id'] for t in turns if t['role']=='user']
            context['history']=[{k:t[k] for k in ('turn_id','role','text')} for t in history]
            for t in history:
                if t['role']=='user':source(t['turn_id'],t['text'],'interview_self_report','expression_analysis_only')
            # No preset E feedback, sample classifier or reference answers sent to provider.
        else:
            saved=self._resume_saved(c,meta,target);snap=saved['snapshot']
            context.update(resume_id=target,position_title=snap['position_title'],snapshot_revision=snap['revision'])
            source('resume_original',snap['resume_text'],'resume_self_report','existing_claims_only')
            context['supporting_record_kinds']=sorted({entry['kind'] for entry in snap['sources']
                if entry['kind'] in ('learning_progress','assessment','retest','interview')})
            context['revision_policy']='仅简历原文可引用。记录类别用于提示待补材料。'
            context['output_contract']='server-owned-fields-v2'
            handoff=saved['report'].get('learning_handoff')
            if snap.get('personal_input_profile'):
                context['personal_input_profile']=snap['personal_input_profile']
                context['revision_policy']='仅整理用户简历原文；记录类别只提示待补材料。固定课程样本、替身评分和面试自述不可写成用户新增成果。'
            if handoff and not snap.get('personal_input_profile'):
                context['learning_handoff']={k:deepcopy(handoff[k]) for k in
                    ('plan_version','completed_tasks','artifact_tasks','ready_tasks','total_tasks','notice')}
                context['learning_handoff']['tasks']=[{k:deepcopy(task[k]) for k in
                    ('task_id','title','ready','artifact_record_id','source_ids','blockers')} for task in handoff['tasks']]
                ready_ids={t['artifact_record_id'] for t in handoff['tasks'] if t['ready']}
                for entry in snap['sources']:
                    if entry['record_id'] in ready_ids:
                        source(entry['record_id'],entry['view']['summary'],'coursework_demo','coursework_demo_only')
                context['learning_handoff']['interview_guidance']=[
                    {'source_id':entry['record_id'],'findings':[{'observation':f['observation'][:240],'suggestion':f['suggestion'][:240]}
                        for f in entry['view']['findings']]}
                    for entry in snap['sources'] if entry['kind']=='interview'][-1:]
                if ready_ids:
                    context['revision_policy']='原文引用定位已有经历，supporting_refs仅可引用提供的课程成果摘要。新增课程练习表述待本人核实，演示分数和面试自述不得升级为生产事实。'
                    context['output_contract']='learning-evidence-v3'
        if stage=='d_revision' and saved['snapshot'].get('personal_input_profile') and self._has_runtime(c):
            from personal_resume_context import personal_evidence_context
            context=personal_evidence_context(context,saved['snapshot'])
        if stage=='d_revision' and meta['package']['case'].get('resume_edit_contract'):
            contract=meta['package']['case']['resume_edit_contract']
            original=context['sources']['resume_original']['text']
            quotes=[contract[k] for k in ('project_quote','materials_quote','skills_quote')]
            context['sources']['resume_original']['reference_options']=[
                {'source_id':'resume_original','start':original.index(q),'end':original.index(q)+len(q),'quote':q}
                for q in quotes if original.count(q)==1 and len(q)<=240]
            for sid,entry in context['sources'].items():
                if entry['usage']=='coursework_demo_only' and len(entry['text'])<=240:
                    entry['reference_options']=[{'source_id':sid,'start':0,'end':len(entry['text']),'quote':entry['text']}]
        return self._ce_context(c,meta,stage,context)

    def _call_request(self,c,meta,stage,target):
        ce=self._ce_request(c,meta,stage,target)
        if ce is not None:return ce
        if stage not in STAGES or not isinstance(target,str) or not 1<=len(target)<=160:invalid('请选择有效的C/E/D操作及本会话目标。')
        context=self._call_context(c,meta,stage,target);config=self.call_configuration();settings=deepcopy(config['config'])
        control=self._d_output_control(settings) if stage=='d_revision' else None
        request={'contract_version':VERSION,'mode':self.call_transport.mode,'stage':stage,'target_id':target,
            'scope':self._scope(meta),'revision':meta['revision'],'context':context,'config_revision':config['revision'],
            'config':settings,'key_slot_digest':hashlib.sha256((config.get('encrypted_key') or '').encode()).hexdigest(),
            'boot_id':self.call_boot_id,'transport_kind':self.call_transport.kind,'automatic_retries':0,'payload':payload(stage,context,settings,output_control=control)}
        if control:request['output_control']=control
        request.update(self._call_request_policy(request))
        return request

    def _call_row(self,c,identity):
        exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='wbc_grants'").fetchone()
        expect(exists is not None,'本会话没有这份单次授权。')
        row=c.execute('SELECT g.*,p.request_json,p.request_digest,p.expires_at FROM wbc_grants g JOIN wbc_previews p USING(preview_id) WHERE authorization_id=?',(identity,)).fetchone()
        expect(row is not None,'单次授权不属于本会话。');row=dict(row);req=json.loads(row['request_json'])
        expect(digest(req)==row['request_digest'],'调用快照校验失败。')
        expect(req['scope']==self._scope(self._meta(c)) and req['contract_version']==VERSION
               and req.get('transport_kind','in_process_fixed') in TRANSPORT_LABELS
               and req['mode']==self._call_mode(req.get('transport_kind','in_process_fixed'))
               and req['mode']==self.call_transport.mode,'调用快照不属于本会话或模式。')
        self._ce_check_saved_call(c,row,req)
        if row['response_json']:expect(digest(json.loads(row['response_json']))==row['response_digest'],'保存响应的校验和不一致。')
        if row['result_json']:
            expect(row['status']=='completed' and row['response_json'] is not None,'候选结果没有对应成功响应。')
            try:reconstructed=validate_result(req,json.loads(row['response_json'])['content'])
            except CEDValidation:expect(False,'候选结果的原始响应不再满足合同。')
            expect(json.loads(row['result_json'])==reconstructed,'候选结果与已保存响应不一致。')
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='wbc_rechecks'").fetchone():
            audit=c.execute('SELECT payload_json,payload_digest FROM wbc_rechecks WHERE authorization_id=?',(identity,)).fetchone()
            if audit:
                check=json.loads(audit[0])
                expect(digest(check)==audit[1] and check['authorization_id']==identity
                    and check['request_digest']==row['request_digest'] and check['response_digest']==row['response_digest']
                    and row['status']=='completed' and check['result_digest']==digest(json.loads(row['result_json']))
                    and check['previous_status']=='failed_validation'
                    and (check['previous_errors']==[{'code':'unsafe_value_deduplication','path':'$.reference_outline'}]
                        or (check['previous_errors']==[{'code':'fields','path':'$'}] and check.get('policy')=='single-question-format-marker-v1'
                            and req['stage']=='c_question' and req['context'].get('question_rules',{}).get('experience_policy')=='single-feedback-v1')),
                    '本地复核记录与原响应不一致。')
                row['validation_recheck']=check
        return row,req

    def _call_view(self,row,req):
        state=row['status']
        if state=='authorized':
            if row['boot_id']!=self.call_boot_id:state='invalidated'
            elif row['expires_at']<=self.call_clock():state='expired'
        result=json.loads(row['result_json']) if row['result_json'] else None
        response=json.loads(row['response_json']) if row['response_json'] else {}
        if result and req['stage']=='c_question':result={k:v for k,v in result.items() if k!='reference_outline'}
        output_details={}
        if req.get('output_control'):
            output_details={'output_control':req['output_control'],'response_diagnostics':response.get('diagnostics')}
            if any(e['code']=='truncated' for e in json.loads(row['error_json'] or '[]')):
                output_details['failure_guidance']='D响应因长度限制结束，无法确认输出完整性；本次不生成候选、不续写、不扩容或自动重试。已保存的用量可核对；参数调整后须新预览和新授权。'
        return self._reply(**self._ce_public(req),**output_details,**({'validation_recheck':row['validation_recheck']} if 'validation_recheck' in row else {}),mode=req['mode'],authorization_id=row['authorization_id'],preview_id=row['preview_id'],
            stage=req['stage'],target_id=req['target_id'],transport_kind=req.get('transport_kind','in_process_fixed'),status=state,consumed=row['dispatch_count']>0,fixed_dispatch_attempts=row['dispatch_count'],
            automatic_retry=False,provider_request_attempted=False,actual_model_cost=0,external_network_allowed=False,
            request_digest=row['request_digest'],result=result,usage=response.get('usage'),errors=json.loads(row['error_json']) if row['error_json'] else [],
            recoverable=state in ('response_saved','dispatching'),source_revision=req['revision'],application_policy='candidate_only_never_auto_apply',
            notice='C/E/D合同与一次授权的固定预演；候选结果单独保存，不改变演示题目、分数、能力、面试或简历。已消费授权不会补发。')

    def call_preview(self,token,body):
        fields(body,('request_id','expected_revision','stage','target_id'));identity=uid(body['request_id'])
        if type(body['expected_revision']) is not int or body['expected_revision']<0:invalid('会话修订号无效。')
        with self.lock,closing(self._connect(token,write=True)) as c:
            meta=self._meta(c);expect(meta['revision']==body['expected_revision'],'会话已更新，请重新读取后预览。')
            with c:
                self._call_schema(c)
                old=c.execute('SELECT * FROM wbc_previews WHERE request_id=?',(identity,)).fetchone()
                if old:
                    expect(old['body_digest']==digest(body),'预览请求身份已用于其他内容。');req=json.loads(old['request_json']);pid=old['preview_id'];expires=old['expires_at']
                    expect(req==self._call_request(c,meta,body['stage'],body['target_id']),'配置、提示或来源已变化，需新建预览。')
                else:
                    req=self._call_request(c,meta,body['stage'],body['target_id']);pid=str(uuid.uuid4());expires=self.call_clock()+300
                    c.execute('INSERT INTO wbc_previews VALUES (?,?,?,?,?,?)',(pid,identity,digest(body),encode(req),digest(req),expires))
            chars=len(encode(req['payload']));conf=req['config'];tokens=math.ceil(chars/2)
            output_limit=req['payload'][conf.get('output_token_parameter','max_tokens')]
            priced=all(conf[k] is not None for k in ('input_price_per_million','output_price_per_million'))
            estimate=(tokens*conf['input_price_per_million']+output_limit*conf['output_price_per_million'])/1000000 if priced else None
            return self._reply(**self._ce_public(req),**({'output_control':req['output_control']} if req.get('output_control') else {}),mode=req['mode'],preview_id=pid,request_digest=digest(req),expires_at=expires,
                stage=req['stage'],target_id=req['target_id'],request=req['payload'],field_summary=[{'source_id':k,'characters':len(v['text']),'kind':v['kind'],'usage':v['usage']} for k,v in req['context']['sources'].items()],
                context_fields=[{'name':k,'characters':len(encode(v))} for k,v in req['context'].items()],
                config_revision=req['config_revision'],provider=conf['provider'] or '本地固定替身',configured_destination=conf['base_url'] or None,
                transport_kind=req['transport_kind'],transport_destination=TRANSPORT_LABELS[req['transport_kind']],request_characters=chars,input_limit_exceeded=chars>conf['max_input_chars'],
                max_output_tokens=output_limit,timeout_seconds=conf['timeout_seconds'],automatic_retries=0,
                estimated_input_tokens=tokens,estimated_cost=estimate,currency=conf['currency'],actual_model_cost=0,external_network_allowed=False,
                notice='这是一份完整请求预览，预览/授权都不执行；每个出题、评分、面试轮次、复盘或D建议各需独立授权。',
                cost_notice='按字符粗估及配置单价，不是账单或硬费用上限；本轮真实调用关闭、费用0，未来真实失败也可能计费。')

    def call_authorize(self,token,body):
        confirmation='accept_session_once' if isinstance(body,dict) and 'accept_session_once' in body else 'accept_trial_once' if self.call_transport.mode=='ced_trial' else 'accept_fixed_only'
        fields(body,('preview_id','request_digest',confirmation));pid=uid(body['preview_id'])
        if body[confirmation] is not True:invalid('请明确确认本次单次授权。')
        with self.lock,closing(self._connect(token,write=True)) as c:
            self._call_schema(c);p=c.execute('SELECT * FROM wbc_previews WHERE preview_id=?',(pid,)).fetchone()
            expect(p is not None and p['expires_at']>self.call_clock() and p['request_digest']==body['request_digest'],'预览已过期或不属于本会话。')
            req=json.loads(p['request_json']);meta=self._meta(c)
            expect((confirmation=='accept_session_once')==bool(req.get('session_runtime')),'授权确认与当前请求模式不一致。')
            expect(digest(req)==p['request_digest'] and req==self._call_request(c,meta,req['stage'],req['target_id']),'会话、配置、提示或进程已变化，请新建预览。')
            expect(len(encode(req['payload']))<=req['config']['max_input_chars'],'完整请求超过输入预检上限，未授权。')
            with c:
                c.execute('BEGIN IMMEDIATE')
                old=c.execute('SELECT authorization_id FROM wbc_grants WHERE preview_id=?',(pid,)).fetchone()
                aid=old[0] if old else str(uuid.uuid4())
                if not old:
                    self._session_before_authorize(c,req)
                    self._call_check_authorization(c,req)
                    self._ce_check_authorization(c,req)
                    c.execute('INSERT INTO wbc_grants(authorization_id,preview_id,boot_id,status) VALUES (?,?,?,?)',(aid,pid,self.call_boot_id,'authorized'))
                    self._ce_on_authorized(c,req,aid)
                    self._session_on_authorized(c,req,aid,'ced')
            row,req=self._call_row(c,aid);return self._call_view(row,req)

    def call_status(self,token,body):
        fields(body,('authorization_id',));aid=uid(body['authorization_id'])
        with self.lock,closing(self._connect(token)) as c:
            row,req=self._call_row(c,aid);return self._call_view(row,req)

    def _call_finish(self,c,aid,req):
        row,stored=self._call_row(c,aid);expect(stored==req and row['status']=='response_saved','没有可本地恢复的已保存响应。')
        response=json.loads(row['response_json']);expect(digest(response)==row['response_digest'],'保存的响应校验失败，不重新发送。')
        try:
            self._ce_validate_response(req,response)
            if response.get('finish_reason')!='stop':raise CEDValidation('truncated_or_incomplete_response')
            if response.get('usage') and response['usage']['completion_tokens']>req['payload'][req['config'].get('output_token_parameter','max_tokens')]:
                raise CEDValidation('output_limit')
            if len(response.get('content',''))>req['payload'][req['config'].get('output_token_parameter','max_tokens')]*8:raise CEDValidation('response_exceeds_local_size_guard')
            result=validate_result(req,response.get('content'));status='completed';errors=[]
        except CEDValidation as exc:result=None;status='failed_validation';errors=exc.errors
        c.execute('UPDATE wbc_grants SET status=?,result_json=?,error_json=? WHERE authorization_id=?',(status,encode(result) if result is not None else None,encode(errors),aid))

    def call_execute(self,token,body):
        fields(body,('authorization_id',));aid=uid(body['authorization_id'])
        with self.lock,closing(self._connect(token,write=True)) as c:
            row,req=self._call_row(c,aid)
            if row['status']!='authorized':return self._call_view(row,req)
            expect(row['boot_id']==self.call_boot_id and row['expires_at']>self.call_clock(),'授权过期或进程已变化，请重新预览授权。')
            meta=self._meta(c);expect(req==self._call_request(c,meta,req['stage'],req['target_id']),'请求来源、配置或提示已变化，旧授权不能执行。')
            with c:
                c.execute('BEGIN IMMEDIATE')
                self._call_check_authorization(c,req)
                self._ce_check_dispatch(c,req,aid)
                self._session_before_dispatch(c,req,aid)
                consumed=c.execute("UPDATE wbc_grants SET status='dispatching',dispatch_count=1 WHERE authorization_id=? AND status='authorized'",(aid,))
                expect(consumed.rowcount==1,'授权已被消费，请查看原回执。')
            self.call_active.add(aid)
        try:
            started=time.monotonic()
            try:
                response=self._ce_dispatch(req)
                if time.monotonic()-started>req['config']['timeout_seconds']:raise TimeoutError()
                if not isinstance(response,dict) or set(response) not in ({'content','finish_reason','usage'},{'content','finish_reason','usage','diagnostics'}) or not isinstance(response['content'],str):raise CEDValidation('invalid_transport_response')
                if len(response['content'])>400000:raise CEDValidation('response_length')
            except Exception as exc:
                code=exc.code if isinstance(exc,SDKFailure) else 'timeout' if isinstance(exc,TimeoutError) else 'transport_failure'
                errors=exc.errors if isinstance(exc,CEDValidation) else [{'code':code,'path':'$'}]
                status='failed_validation' if code in SDK_RESPONSE_ERRORS else 'failed_transport'
                with self.lock,closing(self._connect(token,write=True)) as c:
                    usage=exc.usage if isinstance(exc,SDKFailure) else None
                    diagnostics=exc.diagnostics if isinstance(exc,SDKFailure) else None
                    failed_response={'content':'','finish_reason':'length' if code=='truncated' else 'error','usage':usage} if usage is not None or diagnostics and diagnostics.get('finish_reason') else None
                    if failed_response is not None and diagnostics is not None:failed_response['diagnostics']=diagnostics
                    with c:c.execute("UPDATE wbc_grants SET status=?,error_json=?,response_json=?,response_digest=? WHERE authorization_id=?",
                        (status,encode(errors),encode(failed_response) if failed_response is not None else None,
                         digest(failed_response) if failed_response is not None else None,aid))
                    row,req=self._call_row(c,aid);return self._call_view(row,req)
            with self.lock,closing(self._connect(token,write=True)) as c:
                # Commit raw response first, so a later validation/save failure can recover without another call.
                with c:c.execute("UPDATE wbc_grants SET status='response_saved',response_json=?,response_digest=? WHERE authorization_id=?",(encode(response),digest(response),aid))
                with c:self._call_finish(c,aid,req)
                row,req=self._call_row(c,aid);return self._call_view(row,req)
        finally:
            with self.lock:self.call_active.discard(aid)

    def _recheck_saved_c_counterexample(self,c,row,req):
        # A narrowly scoped local recovery for the negated-counterexample guard.
        # It never changes the request/response, opens a Key or calls a transport.
        expected=[{'code':'unsafe_value_deduplication','path':'$.reference_outline'}]
        if req['stage']!='c_question' or row['dispatch_count']!=1 or not row['response_json'] or json.loads(row['error_json'] or '[]')!=expected:
            return
        response=json.loads(row['response_json'])
        if response.get('finish_reason')!='stop' or not response.get('content'):
            return
        try:validate_result(req,response['content'])
        except CEDValidation:return
        c.execute("UPDATE wbc_grants SET status='response_saved' WHERE authorization_id=?",(row['authorization_id'],))
        self._call_finish(c,row['authorization_id'],req)
        updated=c.execute('SELECT status,result_json FROM wbc_grants WHERE authorization_id=?',(row['authorization_id'],)).fetchone()
        expect(updated['status']=='completed','原响应仍未通过本地复核，没有新增请求。')
        check={'authorization_id':row['authorization_id'],'previous_status':row['status'],'previous_errors':expected,
            'request_digest':row['request_digest'],'response_digest':row['response_digest'],
            'result_digest':digest(json.loads(updated['result_json'])),'policy':'negated-numeric-counterexample-v4',
            'rechecked_at':self.call_clock(),'new_provider_requests':0}
        c.execute('CREATE TABLE IF NOT EXISTS wbc_rechecks(authorization_id TEXT PRIMARY KEY,payload_json TEXT NOT NULL,payload_digest TEXT NOT NULL)')
        c.execute('INSERT INTO wbc_rechecks VALUES (?,?,?)',(row['authorization_id'],encode(check),digest(check)))

    def _recheck_saved_question_format(self,c,row,req):
        # One allowlisted non-business format marker only. No transport or edits.
        expected=[{'code':'fields','path':'$'}]
        if (req['stage']!='c_question' or req['context'].get('question_rules',{}).get('experience_policy')!='single-feedback-v1'
            or row['dispatch_count']!=1 or not row['response_json'] or json.loads(row['error_json'] or '[]')!=expected):return
        response=json.loads(row['response_json'])
        if response.get('finish_reason')!='stop':return
        try:candidate=validate_result(req,response.get('content'))
        except CEDValidation:return
        if candidate.get('format_marker_ignored')!='json_object':return
        c.execute("UPDATE wbc_grants SET status='response_saved' WHERE authorization_id=?",(row['authorization_id'],))
        self._call_finish(c,row['authorization_id'],req)
        check={'authorization_id':row['authorization_id'],'previous_status':row['status'],'previous_errors':expected,
            'request_digest':row['request_digest'],'response_digest':row['response_digest'],'result_digest':digest(candidate),
            'policy':'single-question-format-marker-v1','rechecked_at':self.call_clock(),'new_provider_requests':0}
        c.execute('CREATE TABLE IF NOT EXISTS wbc_rechecks(authorization_id TEXT PRIMARY KEY,payload_json TEXT NOT NULL,payload_digest TEXT NOT NULL)')
        c.execute('INSERT INTO wbc_rechecks VALUES (?,?,?)',(row['authorization_id'],encode(check),digest(check)))

    def call_recover(self,token,body):
        fields(body,('authorization_id',));aid=uid(body['authorization_id'])
        with self.lock,closing(self._connect(token,write=True)) as c:
            row,req=self._call_row(c,aid);expect(aid not in self.call_active,'本次调用仍在执行，不能恢复或重发。')
            with c:
                if row['status']=='response_saved':self._call_finish(c,aid,req)
                elif row['status']=='failed_validation':
                    self._recheck_saved_c_counterexample(c,row,req)
                    latest,stored=self._call_row(c,aid)
                    if latest['status']=='failed_validation':self._recheck_saved_question_format(c,latest,stored)
                elif row['status']=='dispatching':c.execute("UPDATE wbc_grants SET status='unknown_outcome',error_json=? WHERE authorization_id=?",(encode([{'code':'outcome_unknown_do_not_resend','path':'$'}]),aid))
                elif row['status']=='authorized':
                    expect(row['boot_id']!=self.call_boot_id or row['expires_at']<=self.call_clock(),'尚未消费的有效授权无需恢复。')
                    c.execute("UPDATE wbc_grants SET status='invalidated' WHERE authorization_id=?",(aid,))
            row,req=self._call_row(c,aid);return self._call_view(row,req)
