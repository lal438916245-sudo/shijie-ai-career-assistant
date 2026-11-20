"""Evidence-bounded D double. Resume self-report is never upgraded by demo C/E."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timezone
import json
from competition_case import validate_source
from competition_workbench_fixtures import bound_id
from competition_workbench_assessment import encode,digest,expect,invalid
from workbench_learning_evidence import learning_handoff

RESUME_OPERATIONS={'resume_generate':set(),'resume_check':{'resume_id','text'}}
VERSION='competition-resume-fixed-v1'
NOTICE='固定替身建议，仅使用本会话冻结的资料；简历自述未经独立核验，学习完成、固定评分和面试表达均不能证明生产经历。不调用模型，不改写简历原文或能力状态。'

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')

def make_report(snapshot):
    if snapshot.get('optional_context_policy')=='confirmed-optional-evidence-v1':
        base=deepcopy(snapshot);base.pop('optional_context_policy')
        report=make_report(base)
        report['optional_context']={'policy':snapshot['optional_context_policy'],'omitted':deepcopy(snapshot['omitted_context_counts'])}
        report['notice']+=' 未采用的考核与面试反馈已排除；可先整理原文，后续另存新版本补充有效材料。'
        return report
    if snapshot.get('personal_input_profile'):
        from personal_resume_report import make_personal_report
        return make_personal_report(snapshot)
    original=snapshot['resume_text'];sources=snapshot['sources'];base=sources[0]['record_id'];diagnosis=next(s['record_id'] for s in sources if s['kind']=='diagnosis')
    contract=snapshot.get('resume_edit_contract',{})
    quote=contract.get('project_quote') or '用Python读取CSV、清理空值并按订单ID去重，做过基础SQL聚合和离线订单报表课程练习；能说明样本输入和汇总结果。'
    expect(quote in original,'固定改写模板与简历原文不匹配，已停止生成。')
    draft=contract.get('project_rewrite') or '在离线订单报表课程练习中，使用Python读取CSV、清理空值并按订单ID去重，完成基础SQL聚合；能够说明样本输入和汇总结果。'
    boundary=contract.get('boundary_quote') or '没有生产Flink链路、商业上线和真实性能提升经历。'
    expect(boundary in original,'固定边界与简历原文不匹配，已停止生成。')
    items=[{'item_id':'original-project','status':'suggested','title':'把已有课程练习写得具体','original_quote':quote,'suggested_text':draft,
        'reason':'调整语序，保留课程、小样本与自述边界；没有新增规模、指标、个人主导或生产经历。','source_ids':[base,diagnosis],
        'evidence_level':'简历原文自述，未经独立核验','next_action':'使用前自行确认每个动作确实由本人完成；如有材料，可另补脚本、输入及预期输出。'},
        {'item_id':'production-boundary','status':'withheld','title':'生产与性能成果保持留白','original_quote':boundary,'suggested_text':'',
         'reason':'原文明示没有相关经历；诊断待验证、演示高分及面试清晰表达都不能推翻这个边界。','source_ids':[base,diagnosis],
         'evidence_level':'原文明确边界','next_action':'保留事实，不添加生产Flink、商业上线或性能提升数字；未来有真实材料再核实。'}]
    handoff=learning_handoff(snapshot)
    ready=[task for task in (handoff or {}).get('tasks',[]) if task['ready']]
    if ready:
        draft+=('\n  学习计划补充（课程小样本）：\n  - '+'\n  - '.join(task['artifact_summary'] for task in ready)) if contract else ' 学习后补充的课程练习：'+' '.join(task['artifact_summary'] for task in ready)
        item=items[0]
        item.update(title='把学习后的课程练习融入项目经历',suggested_text=draft,
            change_kind='learning_outcome',reason='整合已保存的课程练习成果，关联完成记录和最近的考核复测分项；请本人核实可复现的练习过程。',
            evidence_level='固定课程成果 / 演示考核及复测，限于学习练习')
        item['source_ids']=list(dict.fromkeys(item['source_ids']+[sid for task in ready for sid in task['source_ids']+task['interview_ids']]))
        old_materials=contract.get('materials_quote') or '未提供复杂连接、执行计划、事实粒度、自动测试与监控的验证材料。'
        if old_materials in original:
            items.append({'item_id':'learning-materials-boundary','status':'suggested','change_kind':'learning_outcome',
                'title':'更新课程材料的完成范围','original_quote':old_materials,
                'suggested_text':contract.get('materials_rewrite') or '已整理对应课程小样本和核对记录，自动化执行、规模与线上监控仍待实际验证。',
                'reason':'按本份报告冻结的课程材料更新范围，保留自动化执行和线上验证的限制。',
                'source_ids':item['source_ids'],'evidence_level':'课程小样本 / 固定演示',
                'next_action':'采用前核对本人材料，并与上方课程练习表述一起查看。'})
    if contract and {'CP-T01','CP-T04','CP-T08'} <= {t['task_template_id'] for t in ready}:
        items.append({'item_id':'learning-sql-skills','status':'suggested','change_kind':'learning_outcome',
          'title':'同步更新SQL技能的课程验证范围','original_quote':contract['skills_quote'],
          'suggested_text':contract['skills_rewrite'],'reason':'依据连接、执行计划与窗口排序三个已核对课程任务，保留小样本边界。',
          'source_ids':list(dict.fromkeys(sid for task in ready if task['task_template_id'] in ('CP-T01','CP-T04','CP-T08') for sid in task['source_ids'])),
          'evidence_level':'固定课程成果 / 演示考核复测','next_action':'核实本人能复现这些练习，不能写成精通或生产优化收益。'})
    for source in sources:
        view=source['view'];kind=source['kind'];rid=source['record_id']
        if kind=='learning_progress':
            items.append({'item_id':rid,'status':'supplement','title':'学习进度只作为补证线索','original_quote':'','suggested_text':'',
                'reason':f"记录状态为{view['status']}，这是个人进度记录，不能替代作品或独立验证。",'source_ids':[rid],
                'evidence_level':'用户进度，不是能力证据','next_action':'补充真实练习文件、运行命令、小样本输入与预期/实际输出；不要把勾选已完成写成已掌握。'})
        elif kind in ('assessment','retest'):
            items.append({'item_id':rid,'status':'supplement','title':('专题复测' if kind=='retest' else '日周考核')+'只支持定位补证方向','original_quote':'','suggested_text':'',
                'reason':'题目与原始答卷有保存，但评分来自预设路线，不评价自由输入的真实能力；不据此新增简历能力。','source_ids':[rid],
                'evidence_level':'固定替身评分 / 仅演示','next_action':'围绕该题整理本人可复现的解法与反例，核实后再考虑补入练习经历；当前不生成成果表述。'})
        elif kind=='interview':
            findings=view['findings'];detail=next((f for f in findings if f['analysis_kind']=='needs_detail'),None)
            clear=next((f for f in findings if f['analysis_kind']=='clear'),None)
            chosen=detail or clear
            items.append({'item_id':rid,'status':'supplement','title':'把面试表达问题转成补证清单','original_quote':chosen['quote'] if chosen else '', 'suggested_text':'',
                'reason':('内置示例反馈：'+chosen['observation']) if chosen else '没有可归因的示例分析；自定义回答只保存，不推断短板。',
                'source_ids':[rid]+([chosen['answer_record_id']] if chosen else []),
                'evidence_level':'面试自述 / 示例反馈，不是已发生项目的证明',
                'next_action':(chosen['suggestion'] if chosen else '按已保存对话自查个人贡献、可核对材料与未验证边界；待真实分析接入后再评估。')+' 不自动把面试回答移入简历。'})
    report={'contract_version':VERSION,'scope':snapshot['scope'],'input_digest':snapshot['input_digest'],'resume_text':original,
        'position_title':snapshot['position_title'],'snapshot_revision':snapshot['revision'],'created_at':snapshot['created_at'],
        'notice':NOTICE,'items':items,'sources':sources,'source_counts':{k:sum(s['kind']==k for s in sources) for k in ('input','diagnosis','learning_progress','assessment','retest','interview')},
        'approved_texts':[item['suggested_text'] for item in items if item['status']=='suggested'], 'coverage_notice':'只使用开始生成前已保存的学习进度、答卷和已结束面试；进行中的面试不作反馈依据。没有记录的方向明确留空。'}
    if contract:
        report['resume_has_header']=True
        report['preview_default_item_ids']=[item['item_id'] for item in items if item['status']=='suggested']
    if handoff is not None:
        report['learning_handoff']=handoff
        if any(s['kind']=='learning_artifact' for s in sources):
            report['source_counts']['learning_artifact']=sum(s['kind']=='learning_artifact' for s in sources)
    return report

def check_text(report,text):
    # Closed-world acceptance: never pretend a fixed double understands arbitrary claims.
    matched=next((i for i in report['items'] if i['status']=='suggested' and text.strip()==i['suggested_text']),None)
    if matched:return {'status':'bounded_suggestion','reason':('与本报告课程练习建议逐字一致；请本人核实成果和验证过程，当前为固定演示。' if matched.get('change_kind')=='learning_outcome' else '与本报告有原文来源的建议逐字一致；仅作自述语序整理，仍需本人确认，未独立验证事实。'),'source_ids':matched['source_ids'],'accepted_text':matched['suggested_text']}
    inflated='主导生产Flink链路上线，处理千万级订单，性能提升80%。'
    if text.strip()==inflated:
        return {'status':'blocked','reason':'内置夸大示例：生产上线、千万级规模、主导职责及80%提升均无来源，且生产经历与简历原文明示边界冲突。','source_ids':[report['sources'][0]['record_id']],'accepted_text':''}
    return {'status':'needs_verification','reason':'固定替身无法对自定义表述作语义核验；未进入有来源建议白名单，已阻止作为可用改写。请提供可核对材料后人工核实，不能据此认定内容虚假。','source_ids':[],'accepted_text':''}

class WorkbenchResume:
    def _resume_schema(self,conn):
        conn.execute('CREATE TABLE IF NOT EXISTS wbd_reports(resume_id TEXT PRIMARY KEY,record_id TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL,payload_digest TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS wbd_checks(check_id TEXT PRIMARY KEY,resume_id TEXT NOT NULL,record_id TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL,payload_digest TEXT NOT NULL)')

    def _has_resumes(self,conn):return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='wbd_reports'").fetchone())

    def _source_row(self,conn,meta,rid):
        row=conn.execute('SELECT * FROM wb_records WHERE record_id=?',(rid,)).fetchone()
        expect(row is not None,'简历建议的来源记录缺失，停止使用。')
        r=dict(row);env=validate_source(json.loads(r['envelope_json']))
        expect(all(env[k]==meta[k] for k in self._scope(meta)) and env['record_kind']==r['kind'],'简历来源不属于本会话。')
        return r

    def _resume_snapshot(self,conn,meta):
        expect(meta['diagnosis'] is not None and meta['bindings'],'请先保存本会话岗位诊断，再准备简历建议。')
        answers={a['record_id']:a for a in self._answer_rows(conn,meta)}
        interviews=self._interview_record_payloads(conn,meta)
        sources=[];refs={}
        def add(row,view):
            refs[row['record_id']]=digest(row)
            sources.append({'record_id':row['record_id'],'kind':row['kind'],'title':row['title'],'seq':row['seq'],'view':view})
        input_id=meta['session_id']+':input';diag_id=meta['session_id']+':diagnosis'
        for rid,view in ((input_id,{'resume_text':meta['inputs']['resume_text'],'jd_text':meta['inputs']['jd_text'],'evidence':('用户提供的简历原文 / 自述，未经独立核验' if meta['package'].get('personal_input') else '虚构候选人原文 / 自述，不是核验事实')}),
                         (diag_id,{'requirements':deepcopy(meta['diagnosis']['audit']['evidence_assessment']['requirements']),'evidence':'A固定证据判断，不证明新增技能'})):
            add(self._source_row(conn,meta,rid),view)
        artifacts={r['record_id']:r for r in self._learning_artifact_rows(conn,meta)}
        for row in conn.execute("SELECT * FROM wb_records WHERE kind IN ('learning_progress','learning_artifact','assessment','retest','interview') ORDER BY seq"):
            row=self._source_row(conn,meta,row['record_id']);payload=json.loads(row['payload_json'])
            if row['kind']=='learning_artifact':
                add(row,{**deepcopy(artifacts[row['record_id']]['artifact']),'plan_version':artifacts[row['record_id']]['plan_version']})
            elif row['kind']=='learning_progress':
                p=payload['progress'];add(row,{'plan_version':payload['plan_version'],**{k:p[k] for k in ('task_id','status','start_date','end_date','revision')}})
            elif row['record_id'] in answers:
                a=answers[row['record_id']];add(row,{'attempt_id':a['attempt_id'],'question':a['question']['prompt'],'answer':a['answer'],'grade':a['grade'],'plan_version':a['plan_version'],'topic_keys':a['topic_keys'],'task_ids':([t['task_id'] for t in a['scope_snapshot']['tasks']] if a['kind']=='retest' else list(dict.fromkeys(p['task_id'] for p in a['question']['parts']))),'evidence':'固定评分不证明答题能力'})
            elif payload.get('event')=='interview_report':
                report=deepcopy(interviews[row['record_id']]['report'])
                for f in report['findings']:
                    turn=conn.execute('SELECT record_id FROM wbi_turns WHERE turn_id=?',(f['answer_turn_id'],)).fetchone()
                    expect(turn is not None,'面试回答引用缺失。');rid=turn[0]
                    source=self._source_row(conn,meta,rid);refs[rid]=digest(source)
                    f['answer_record_id']=rid;f['answer_text']=interviews[rid]['turn']['text']
                    expect(not f['quote'] or f['quote'] in f['answer_text'],'面试反馈引用不在原始回答中。')
                add(row,{'findings':report['findings'],'interview_id':report['interview_id'],'status':report['status'],'answered_count':report['answered_count']})
        for application in self._application_rows(conn,meta):
            if application['stage'] in ('c_grade','e_report'):
                refs[application['record_id']]=digest(self._source_row(conn,meta,application['record_id']))
        snapshot={'scope':self._scope(meta),'input_digest':meta['input_digest'],'resume_text':meta['inputs']['resume_text'],'position_title':meta['inputs']['target_role'],
            'revision':meta['revision'],'created_at':now(),'sources':sources,'source_digests':refs}
        if meta['package'].get('personal_input'):
            snapshot['personal_input_profile']=meta['package']['personal_input']['contract_version']
        contract=meta['package']['case'].get('resume_edit_contract')
        if contract:snapshot['resume_edit_contract']=deepcopy(contract)
        if meta['published_version']:
            plan=self._plan(conn,meta['published_version'])
            refs[plan['record_id']]=digest(self._source_row(conn,meta,plan['record_id']))
            snapshot['learning_plan']={'version':plan['version'],'record_id':plan['record_id'],'plan_digest':plan['plan_digest'],
                'tasks':[{k:t[k] for k in ('task_id','task_template_id','title','topic_keys')} for t in plan['plan']['tasks']]}
        return snapshot

    def _do_resume_generate(self,conn,meta,body):
        from competition_short_flow import confirmed_snapshot
        snapshot=confirmed_snapshot(self,conn,meta,self._resume_snapshot(conn,meta));report=make_report(snapshot)
        rid=bound_id(meta['session_id'],'resume',body['request_id']);record_id=rid+':report'
        saved={'resume_id':rid,'snapshot':snapshot,'report':report}
        self._record(conn,meta,record_id,'resume','D · 保存有来源的简历建议',{'event':'resume_report','resume_id':rid},sorted(snapshot['source_digests']))
        conn.execute('INSERT INTO wbd_reports VALUES (?,?,?,?)',(rid,record_id,encode(saved),digest(saved)))
        return {'resume_id':rid,'record_id':record_id}

    def _resume_saved(self,conn,meta,rid):
        expect(isinstance(rid,str) and self._has_resumes(conn),'当前会话没有这份简历建议。')
        row=conn.execute('SELECT * FROM wbd_reports WHERE resume_id=?',(rid,)).fetchone();expect(row is not None,'简历建议不属于本会话。')
        saved=json.loads(row['payload_json']);snap=saved['snapshot']
        expect(digest(saved)==row['payload_digest'] and saved['resume_id']==rid and snap['scope']==self._scope(meta) and snap['input_digest']==meta['input_digest'] and snap['resume_text']==meta['inputs']['resume_text'],'简历建议快照来源校验失败。')
        expect(snap.get('personal_input_profile')==meta['package'].get('personal_input',{}).get('contract_version'),'简历建议的个人资料模式不一致。')
        for source_id,expected in snap['source_digests'].items():expect(digest(self._source_row(conn,meta,source_id))==expected,'简历建议引用的来源已变化，停止展示。')
        if snap.get('learning_plan'):
            frozen=snap['learning_plan'];plan=self._plan(conn,frozen['version'])
            expect(frozen=={'version':plan['version'],'record_id':plan['record_id'],'plan_digest':plan['plan_digest'],
                'tasks':[{k:t[k] for k in ('task_id','task_template_id','title','topic_keys')} for t in plan['plan']['tasks']]},
                '简历引用的学习计划不一致。')
        # Validate only interview bodies referenced by this frozen report;
        # later interviews may have adopted turns beyond its application cutoff.
        answers={a['record_id']:a for a in self._answer_rows(conn,meta)}
        frozen_interviews={s['view']['interview_id'] for s in snap['sources'] if s['kind']=='interview'}
        interviews=self._interview_record_payloads(conn,meta,only_interview_ids=frozen_interviews)
        artifacts={row['record_id']:row for row in self._learning_artifact_rows(conn,meta)}
        source_ids=[source['record_id'] for source in snap['sources']]
        expect(len(source_ids)==len(set(source_ids)) and
            [source['seq'] for source in snap['sources']]==sorted(source['seq'] for source in snap['sources']),
            '简历的来源顺序或身份不一致。')
        for source in snap['sources']:
            raw=self._source_row(conn,meta,source['record_id'])
            expect(all(source[key]==raw[key] for key in ('kind','seq','title')),'冻结来源的标识不一致。')
            if source['kind']=='learning_progress':
                payload=json.loads(raw['payload_json'])
                expected={k:payload['progress'][k] for k in ('task_id','status','start_date','end_date','revision')}
                if snap.get('learning_plan'):
                    expected['plan_version']=payload['plan_version']
                expect(source['view']==expected,'冻结学习进度与原始记录不一致。')
            elif source['kind']=='learning_artifact':
                original=artifacts.get(source['record_id'])
                expect(original is not None and source['view']=={**original['artifact'],'plan_version':original['plan_version']},'冻结练习成果与原始记录不一致。')
            elif source['kind'] in ('assessment','retest'):
                a=answers.get(source['record_id']);v=source['view']
                expect(a is not None and v['attempt_id']==a['attempt_id'] and v['question']==a['question']['prompt'] and v['answer']==a['answer'] and v['grade']==a['grade'] and v.get('topic_keys',a['topic_keys'])==a['topic_keys'],'冻结答卷与原始记录不一致。')
            elif source['kind']=='interview':
                report=interviews.get(source['record_id'],{}).get('report');v=source['view']
                expect(report is not None and v['interview_id']==report['interview_id'] and v['status']==report['status'] and v['answered_count']==report['answered_count'],'冻结面试与原始记录不一致。')
                for f in v['findings']:
                    original=next((x for x in report['findings'] if x['answer_turn_id']==f['answer_turn_id']),None)
                    expect(original is not None and all(f[k]==value for k,value in original.items()),'冻结面试反馈与来源不一致。')
                    expect(interviews.get(f['answer_record_id'],{}).get('turn',{}).get('text')==f['answer_text'],'冻结回答与原文不一致。')
        expect(saved['report']==make_report(snap),'简历建议与冻结来源不一致。')
        reference=self._source_row(conn,meta,row['record_id'])
        expect(reference['kind']=='resume' and json.loads(reference['payload_json'])=={'event':'resume_report','resume_id':rid} and json.loads(reference['parent_ids_json'])==sorted(snap['source_digests']),'简历建议引用不完整。')
        return saved

    def _do_resume_check(self,conn,meta,body):
        saved=self._resume_saved(conn,meta,body['resume_id']);text=body['text']
        if not isinstance(text,str) or not text.strip() or len(text)>6000:invalid('请填写1～6000字拟用表述。')
        result=check_text(saved['report'],text);cid=bound_id(meta['session_id'],'rcheck',body['request_id']);record_id=cid+':saved'
        value={'check_id':cid,'resume_id':body['resume_id'],'text':text,'result':result,'scope':self._scope(meta),'created_at':now()}
        self._record(conn,meta,record_id,'resume','D · 核对拟用表述：'+{'bounded_suggestion':'保留原文边界','blocked':'拦截夸大示例','needs_verification':'待核实，未放行'}[result['status']],
            {'event':'resume_check','check_id':cid,'resume_id':body['resume_id']},[body['resume_id']+':report'])
        conn.execute('INSERT INTO wbd_checks VALUES (?,?,?,?,?)',(cid,body['resume_id'],record_id,encode(value),digest(value)))
        return {'resume_id':body['resume_id'],'check_id':cid,'check':value}

    def _resume_checks(self,conn,meta,rid):
        saved=self._resume_saved(conn,meta,rid);output=[]
        for row in conn.execute('SELECT * FROM wbd_checks WHERE resume_id=? ORDER BY rowid DESC',(rid,)):
            v=json.loads(row['payload_json']);ref=self._source_row(conn,meta,row['record_id'])
            expect(digest(v)==row['payload_digest'] and v['scope']==self._scope(meta) and v['resume_id']==rid and v['check_id']==row['check_id'] and v['result']==check_text(saved['report'],v['text']),'简历表述核对记录不一致。')
            expect(json.loads(ref['payload_json'])=={'event':'resume_check','check_id':v['check_id'],'resume_id':rid} and json.loads(ref['parent_ids_json'])==[rid+':report'],'简历核对来源引用缺失。')
            output.append(v)
        return output

    def resume(self,token,rid):
        with self.lock,closing(self._connect(token)) as conn:
            meta=self._meta(conn);saved=self._resume_saved(conn,meta,rid)
            return self._reply(scope=self._scope(meta),resume_id=rid,report=saved['report'],checks=self._resume_checks(conn,meta,rid))

    def _resume_state(self,conn,meta):
        rows=[]
        if self._has_resumes(conn):
            for row in conn.execute('SELECT resume_id FROM wbd_reports ORDER BY rowid DESC'):
                s=self._resume_saved(conn,meta,row[0]);self._resume_checks(conn,meta,row[0])
                rows.append({'resume_id':row[0],'created_at':s['report']['created_at'],'snapshot_revision':s['report']['snapshot_revision'],'source_counts':s['report']['source_counts'],**({'result_origin':'personal_local'} if s['report'].get('result_origin')=='personal_local' else {})})
        return {'resume_reports':rows}

    def _resume_record_payloads(self,conn,meta):
        output={}
        if self._has_resumes(conn):
            for row in conn.execute('SELECT resume_id FROM wbd_reports'):
                rid=row[0];saved=self._resume_saved(conn,meta,rid)
                output[rid+':report']={'event':'resume_report','resume_id':rid,'report':saved['report']}
                for c in self._resume_checks(conn,meta,rid):output[c['check_id']+':saved']={'event':'resume_check',**c}
        return output
