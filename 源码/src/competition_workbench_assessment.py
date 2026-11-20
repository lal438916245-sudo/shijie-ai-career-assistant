"""Transactional, session-local C/retest double. Never open legacy/real evidence DBs."""
from contextlib import closing
from copy import deepcopy
from datetime import date,timedelta
import hashlib,json,uuid
from competition_workbench_fixtures import bound_id
from competition_case import validate_source
from workbench_question_bank import assessment_questions,scoped_assessment_questions,retest_question,fixed_grade,fingerprint,PATHS,RULE_VERSION
from workbench_mastery import project_topic

OPERATIONS={
 'assessment_start':{'plan_version','kind','period_start','period_end','task_ids','fixture_path'},
 'retest_start':{'plan_version','topic_id','source_attempt_id','fixture_path'},
 'answer':{'run_id','question_id','answer'},
 'assessment_next':{'run_id','last_attempt_id'},
 'assessment_end':{'run_id'}}

def encode(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(v):return hashlib.sha256(encode(v).encode()).hexdigest()
def expect(v,message):
    from competition_workbench import expect as check
    check(v,message)
def invalid(message):
    from competition_workbench import WorkbenchError
    raise WorkbenchError(message)

class WorkbenchAssessment:
    def _assessment_schema(self,conn):
        # Only additive tables, only during an explicitly requested write.
        conn.execute('CREATE TABLE IF NOT EXISTS wba_runs(run_id TEXT PRIMARY KEY,payload_json TEXT NOT NULL,payload_digest TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS wba_answers(attempt_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,question_id TEXT NOT NULL UNIQUE,record_id TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL,payload_digest TEXT NOT NULL)')

    def _has_assessments(self,conn):
        return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wba_runs'").fetchone())

    def _saved_run(self,conn,meta,rid):
        expect(isinstance(rid,str) and self._has_assessments(conn),'本会话尚无这份考核，请重新读取。')
        row=conn.execute('SELECT * FROM wba_runs WHERE run_id=?',(rid,)).fetchone()
        expect(row is not None,'考核或复测不属于当前会话。')
        value=json.loads(row['payload_json'])
        expect(digest(value)==row['payload_digest'] and value['scope']==self._scope(meta),'考核快照来源或校验和不一致，停止使用。')
        expect(value['plan_digest']==self._plan(conn,value['plan_version'])['plan_digest'],'考核对应的计划快照不一致。')
        return value

    def _save_run(self,conn,run):
        conn.execute('INSERT INTO wba_runs VALUES (?,?,?) ON CONFLICT(run_id) DO UPDATE SET payload_json=excluded.payload_json,payload_digest=excluded.payload_digest',
            (run['run_id'],encode(run),digest(run)))

    def _answer_rows(self,conn,meta):
        if not self._has_assessments(conn):return []
        rows=[];runs={}
        for row in conn.execute('SELECT a.*,r.seq,r.envelope_json,r.payload_json AS recorded_payload FROM wba_answers a JOIN wb_records r ON r.record_id=a.record_id ORDER BY r.seq'):
            answer=json.loads(row['payload_json']);envelope=json.loads(row['envelope_json']);validate_source(envelope)
            expect(digest(answer)==row['payload_digest'] and answer['scope']==self._scope(meta),'答卷快照校验失败；不生成能力结论。')
            reference=json.loads(row['recorded_payload'])
            minimal={'event':'answer_submitted','attempt_id':answer['attempt_id'],'run_id':answer['run_id']}
            expect(reference==minimal or reference==answer,'答卷引用与原始快照不一致，停止展示。')
            expect(all(envelope[k]==meta[k] for k in ('case_id','session_id','plan_id','trace_id')) and envelope['source_kind']=='fixed_stub_output' and envelope['run_mode']=='demo','答卷来源不属于本演示会话。')
            run=runs.setdefault(row['run_id'],self._saved_run(conn,meta,row['run_id']))
            question=next((q for q in run['questions'] if q['question_id']==row['question_id']),None)
            expect(question is not None and answer['question']==question and answer['fingerprint']==fingerprint(question['prompt']),'答卷与原题指纹不一致。')
            expect(answer['topic_keys']==[p['topic_key'] for p in question['parts']],'专题分项引用不一致。')
            expect(answer['grade']==self._initial_grade(question,run['kind'],run['fixture_path'],question['ordinal']),'固定评分版本或分项不一致，需复核。')
            expect(answer['question_id']==row['question_id'] and answer['attempt_id']==row['attempt_id'] and answer['record_id']==row['record_id'],'答卷身份不一致。')
            rows.append({**answer,'commit_seq':row['seq']})
        expect(len(rows)==conn.execute('SELECT COUNT(*) FROM wba_answers').fetchone()[0],'答卷来源记录缺失，不能当作尚未考核。')
        return rows

    def _capabilities(self,conn,meta):
        rows=self._answer_rows(conn,meta)
        return [{**project_topic(t['topic_key'],rows,meta['active_version'] is not None),
            'topic_id':t['topic_id'],'title':t['title'],'source_gap_ids':t['source_gap_ids']}
            for t in (meta['bindings'] or {}).get('topics',[])]

    def _assessment_state(self,conn,meta):
        runs=[]
        if self._has_assessments(conn):
            for row in conn.execute('SELECT run_id FROM wba_runs ORDER BY rowid DESC'):
                r=self._saved_run(conn,meta,row[0])
                runs.append({k:r[k] for k in ('run_id','kind','title','status','fixture_path','stop_reason','source_attempt_id')} | {'topic_id':r.get('topic_id')})
        return {'assessment_runs':runs,'capabilities':self._capabilities(conn,meta),
            'mastery_rule_version':RULE_VERSION,'real_ability_notice':'尚无真实评分；以下能力状态仅演示规则，不代表你的真实能力。'}

    def _published(self,conn,meta):
        expect(meta['published_version'] is not None,'请先在学习计划完成程序校验与确认发布，再开始考核。')
        return self._plan(conn,meta['published_version'])

    def _scope_options(self,conn,meta,kind,start,end):
        plan=self._published(conn,meta)
        try:
            a=date.fromisoformat(start);b=date.fromisoformat(end)
            if kind not in ('day','week') or (b-a).days!=(0 if kind=='day' else 6):raise ValueError()
        except (ValueError,TypeError):invalid('请选择有效的日/周日期范围。')
        tasks=[]
        for task in plan['plan']['tasks']:
            p=dict(conn.execute('SELECT * FROM wb_progress WHERE task_id=?',(task['task_id'],)).fetchone())
            if p['start_date']<=end and p['end_date']>=start:
                tasks.append({'task_id':task['task_id'],'task_template_id':task['task_template_id'],'title':task['title'],
                    'topic_ids':task['topic_ids'],'topic_keys':task['topic_keys'],'source_gap_ids':task['source_gap_ids'],
                    'start_date':p['start_date'],'end_date':p['end_date'],'status':p['status'],'schedule_revision':p['revision']})
        return {'kind':kind,'period_start':start,'period_end':end,'timezone':'Asia/Shanghai',
            'plan_version':meta['published_version'],'plan_digest':plan['plan_digest'],'tasks':tasks,
            'question_count':2 if kind=='day' else 3,'min_questions':1 if kind=='day' else 5,
            'max_questions':min(5 if kind=='day' else 10, len(tasks)*5),'questions_per_task':5,'basis':'按本次确认的日期范围与任务出题；未开始/学习中/暂缓也可自愿选入，开始时冻结实际状态。'}

    def assessment_options(self,token,kind,start,end):
        with self.lock,closing(self._connect(token)) as conn:
            meta=self._meta(conn)
            return self._reply(scope=self._scope(meta),revision=meta['revision'],options=self._scope_options(conn,meta,kind,start,end))

    def _bind_question(self,meta,run,raw,index):
        q=deepcopy(raw);topics={t['topic_key']:t for t in meta['bindings']['topics']}
        q.update(question_id=bound_id(meta['session_id'],'question',run['run_id']+':'+str(index)),ordinal=index,
            fingerprint=fingerprint(q['prompt']),topic_ids=[topics[p['topic_key']]['topic_id'] for p in q['parts']],
            source_gap_ids=list(dict.fromkeys(g for p in q['parts'] for g in topics[p['topic_key']]['source_gap_ids'])))
        return q

    def _new_run(self,meta,body,kind,title):
        path=body['fixture_path']
        if path not in PATHS:invalid('请选择有效的固定演示路线。')
        return {'run_id':bound_id(meta['session_id'],'run',body['request_id']),'scope':self._scope(meta),
            'plan_version':meta['published_version'],'kind':kind,'title':title,'status':'active','cursor':0,
            'fixture_path':path,'source_attempt_id':None,'last_attempt_id':None,'questions':[],
            'question_records':{},'stop_reason':None,'contract_version':'competition-assessment-v1',
            'source_kind':'fixed_stub_output','run_mode':'demo','simulated':True}

    def _active_runs(self,conn,meta):
        return [r for row in conn.execute('SELECT run_id FROM wba_runs') if (r:=self._saved_run(conn,meta,row[0]))['status']=='active']

    def _question_event(self,conn,meta,run,parents):
        q=run['questions'][run['cursor']]
        rid=q['question_id']+':prepared'
        self._record(conn,meta,rid,'retest' if run['kind']=='retest' else 'assessment',
            ('专题复测' if run['kind']=='retest' else '日考核' if run['kind']=='day' else '周考核')+f" · 准备第{run['cursor']+1}题",
            {'event':'question_prepared','run_id':run['run_id'],'question_id':q['question_id'],
             'scope_snapshot':run['scope_snapshot'],'branch':q['branch'],'basis':q['basis'],'fixture_path':run['fixture_path']},parents)
        run['question_records'][q['question_id']]=rid

    def _do_assessment_start(self,conn,meta,body):
        self._active(meta,body);plan=self._published(conn,meta)
        expect(not any(r['kind'] in ('day','week') for r in self._active_runs(conn,meta)),'已有未结束的日/周考核，请继续或结束后再新建。')
        options=self._scope_options(conn,meta,body['kind'],body['period_start'],body['period_end'])
        ids=body['task_ids']
        if not isinstance(ids,list) or not ids or any(not isinstance(t,str) for t in ids) or len(set(ids))!=len(ids):invalid('请确认至少一项任务，不能重复选择。')
        by_id={t['task_id']:t for t in options['tasks']}
        expect(set(ids)<=set(by_id),'所选任务已改期或不在本次范围；请重新确认，旧考核不被改写。')
        run=self._new_run(meta,body,body['kind'],'日考核' if body['kind']=='day' else '周考核')
        if body['kind']=='day' and body.get('question_count')==1:run['experience_policy']='single-feedback-v1'
        run['plan_digest']=plan['plan_digest'];run['scope_snapshot']={**options,'tasks':[by_id[t] for t in ids],'session_revision':meta['revision']}
        tasks=[t for t in plan['plan']['tasks'] if t['task_id'] in ids]
        if 'question_count' in body:
            count = body['question_count']
            minimum = options['min_questions']
            maximum = min(options['max_questions'], len(tasks) * options['questions_per_task'])
            expect(type(count) is int and minimum <= count <= maximum,
                f'当前任务范围支持 {minimum}～{maximum} 题，请重新确认题量。')
            questions = scoped_assessment_questions(tasks, body['kind'], count)
        else:
            # Older clients and pending requests retain the original fixed 2/3 format.
            questions = assessment_questions(tasks, body['kind'])
        run['scope_snapshot']['question_count'] = len(questions)
        run['questions'] = [self._bind_question(meta, run, q, i) for i, q in enumerate(questions)]
        self._question_event(conn,meta,run,[plan['record_id']]);self._save_run(conn,run)
        return {'run_id':run['run_id']}

    def _topic_and_latest(self,conn,meta,topic_id):
        topic=next((t for t in (meta['bindings'] or {}).get('topics',[]) if t['topic_id']==topic_id),None)
        expect(topic is not None,'专题不属于本会话。')
        projection=next(t for t in self._capabilities(conn,meta) if t['topic_id']==topic_id)
        return topic,projection

    def _topic_progress(self,conn,plan,key):
        tasks=[t for t in plan['plan']['tasks'] if key in t['topic_keys']]
        progress=[]
        for t in tasks:
            p=dict(conn.execute('SELECT * FROM wb_progress WHERE task_id=?',(t['task_id'],)).fetchone())
            progress.append({k:p[k] for k in ('task_id','status','revision','start_date','end_date')})
        return tasks,progress

    def _do_retest_start(self,conn,meta,body):
        self._active(meta,body);plan=self._published(conn,meta)
        topic,p=self._topic_and_latest(conn,meta,body['topic_id'])
        expect(p['state'] in ('needs_retest','regressed','provisional_pass') and p['latest_attempt_id']==body['source_attempt_id'],
            '复测来源需为本专题最新有效答卷，且状态为待补强/回退/暂时通过。请刷新后确认。')
        expect(not any(r['kind']=='retest' and r['topic_id']==topic['topic_id'] for r in self._active_runs(conn,meta)), '本专题已有进行中的复测，请先继续或结束。')
        run=self._new_run(meta,body,'retest',topic['title']+' · 专题复测')
        run.update(topic_id=topic['topic_id'],topic_key=topic['topic_key'],source_attempt_id=body['source_attempt_id'],
            last_attempt_id=body['source_attempt_id'],plan_digest=plan['plan_digest'])
        tasks,progress=self._topic_progress(conn,plan,topic['topic_key'])
        run['scope_snapshot']={'timezone':'Asia/Shanghai','tasks':progress,'topic_id':topic['topic_id'],
            'source_attempt_id':body['source_attempt_id'],'session_revision':meta['revision'],'max_questions':3}
        raw=retest_question(topic['topic_key'],0,p['latest_score'],[t['task_id'] for t in tasks],progress)
        run['questions']=[self._bind_question(meta,run,raw,0)]
        root=next(a for a in self._answer_rows(conn,meta) if a['attempt_id']==p['latest_attempt_id'])
        self._question_event(conn,meta,run,[plan['record_id'],root['record_id']]);self._save_run(conn,run)
        return {'run_id':run['run_id']}

    def _retest_current(self,conn,meta,run):
        if run['kind']=='retest':
            _,p=self._topic_and_latest(conn,meta,run['topic_id'])
            expect(p['latest_attempt_id']==run['last_attempt_id'],'本专题已有更新的有效答卷；请结束旧复测并从最新证据重新开始，旧记录仍保留。')

    def _do_answer(self,conn,meta,body):
        run=self._saved_run(conn,meta,body['run_id']);expect(run['status']=='active','这份考核已经结束，请查看报告。')
        q=run['questions'][run['cursor']]
        expect(body['question_id']==q['question_id'],'请提交当前题目，不能跳题或借用其他会话。')
        expect(not conn.execute('SELECT 1 FROM wba_answers WHERE question_id=?',(q['question_id'],)).fetchone(),'本题已提交，不能覆盖；请查看答卷或继续下一题。')
        if not isinstance(body['answer'],str) or not body['answer'].strip() or len(body['answer'])>6000:invalid('请填写1～6000字作答后提交。')
        self._retest_current(conn,meta,run)
        before=self._capabilities(conn,meta)
        aid=bound_id(meta['session_id'],'attempt',q['question_id']);rid=aid+':saved'
        answer={'attempt_id':aid,'record_id':rid,'run_id':run['run_id'],'kind':run['kind'],
            'question_id':q['question_id'],'question':q,'answer':body['answer'],'fingerprint':q['fingerprint'],
            'topic_keys':[p['topic_key'] for p in q['parts']],'grade':self._initial_grade(q,run['kind'],run['fixture_path'],q['ordinal']),
            'scope':self._scope(meta),'source_kind':'fixed_stub_output','run_mode':'demo','simulated':True,
            'plan_version':run['plan_version'],'scope_snapshot':run['scope_snapshot'],'fixture_path':run['fixture_path'],
            'event':'answer_submitted','notice':('此题已采用候选题目，保存原始作答并等待核对评分，不沿用固定路线分数。' if q.get('model_application') else '答案原文由用户填写；反馈与分数为所选固定路线，未分析用户作答，不构成真实评分。')}
        self._record(conn,meta,rid,'retest' if run['kind']=='retest' else 'assessment',run['title']+f" · 第{q['ordinal']+1}题答卷",
            {'event':'answer_submitted','attempt_id':aid,'run_id':run['run_id']},[run['question_records'][q['question_id']]])
        conn.execute('INSERT INTO wba_answers VALUES (?,?,?,?,?,?)',(aid,run['run_id'],q['question_id'],rid,encode(answer),digest(answer)))
        after=self._capabilities(conn,meta)
        if run['kind']=='retest':
            if answer['grade']['status']=='scored':run['last_attempt_id']=aid
            p=next(p for p in after if p['topic_id']==run['topic_id'])
            stop='评分待复核，请核对本次答卷。' if answer['grade']['status']!='scored' else '已满足两道独立题面通过条件，提前结束。' if p['state']=='mastered' else '已达本次3题上限，先返回学习计划补强。' if q['ordinal']>=2 else None
            if stop and not q.get('model_application'):run.update(status='completed',stop_reason=stop)
        elif q['ordinal']==len(run['questions'])-1:run.update(status='completed',stop_reason='本次确认范围的题目已全部提交。')
        self._save_run(conn,run)
        parents=[a['record_id'] for a in self._answer_rows(conn,meta)]
        projection_id=aid+':projection'
        self._record(conn,meta,projection_id,'mastery','按已提交答卷更新演示能力状态',
            {'event':'demo_projection','rule_version':RULE_VERSION,'trigger_attempt_id':aid,'before':before,'after':after,
             'notice':'仅演示域；不更新真实掌握状态。'},parents,source='deterministic_projection',usage='derived_mastery')
        return {'run_id':run['run_id'],'attempt_id':aid,'record_id':rid}

    def _do_assessment_next(self,conn,meta,body):
        run=self._saved_run(conn,meta,body['run_id']);expect(run['status']=='active','本次已结束，请查看报告或重新确认范围。')
        current=run['questions'][run['cursor']]
        row=conn.execute('SELECT attempt_id,record_id FROM wba_answers WHERE question_id=?',(current['question_id'],)).fetchone()
        expect(row and row['attempt_id']==body['last_attempt_id'],'先提交当前题目，再按本题答卷继续。')
        effective=next(a for a in self._answer_rows(conn,meta) if a['attempt_id']==body['last_attempt_id'])
        expect(not current.get('model_application') or effective['grade']['status']=='scored','候选题答卷尚待核对评分，请先完成评分采用，或结束本次考核。')
        self._retest_current(conn,meta,run)
        run['cursor']+=1
        if run['kind']=='retest':
            expect(run['cursor']<3,'已到本次复测上限。')
            plan=self._published(conn,meta);tasks,progress=self._topic_progress(conn,plan,run['topic_key'])
            expect(not all(p['status']=='deferred' for p in progress),'本专题学习任务均已暂缓，请先调整学习安排，或结束本次复测。')
            _,p=self._topic_and_latest(conn,meta,run['topic_id'])
            raw=retest_question(run['topic_key'],run['cursor'],p['latest_score'],[t['task_id'] for t in tasks],progress)
            run['questions'].append(self._bind_question(meta,run,raw,run['cursor']))
        expect(run['cursor']<len(run['questions']),'本次题目已全部提交。')
        self._question_event(conn,meta,run,[row['record_id']]);self._save_run(conn,run)
        return {'run_id':run['run_id'],'question_id':run['questions'][run['cursor']]['question_id']}

    def _do_assessment_end(self,conn,meta,body):
        run=self._saved_run(conn,meta,body['run_id']);expect(run['status']=='active','本次已结束，不重复结束。')
        run.update(status='cancelled',stop_reason='用户结束本次练习；已提交答卷和证据保留，未答题不计0分。')
        self._save_run(conn,run);rid=run['run_id']+':ended'
        self._record(conn,meta,rid,'retest' if run['kind']=='retest' else 'assessment',run['title']+' · 提前结束',
            {'event':'ended','run_id':run['run_id'],'reason':run['stop_reason']},list(run['question_records'].values()))
        return {'run_id':run['run_id']}

    def assessment(self,token,run_id):
        with self.lock,closing(self._connect(token)) as conn:
            meta=self._meta(conn);run=self._saved_run(conn,meta,run_id)
            answers=[a for a in self._answer_rows(conn,meta) if a['run_id']==run_id]
            q=run['questions'][run['cursor']]
            answered=next((a for a in answers if a['question_id']==q['question_id']),None)
            public_question=None
            if run['status']=='active' and not answered:
                public_question={k:v for k,v in q.items() if k!='parts'}
                public_question['parts']=[{k:v for k,v in p.items() if k!='reference'} for p in q['parts']]
            return self._reply(scope=self._scope(meta),revision=meta['revision'],run={
                **{k:run[k] for k in ('run_id','kind','title','status','fixture_path','stop_reason','scope_snapshot','source_attempt_id','plan_version')},
                'question':public_question,'answers':answers,'answered_count':len(answers),
                'planned_count':3 if run['kind']=='retest' else len(run['questions']),
                'next_available':run['status']=='active' and answered is not None and (not q.get('model_application') or answered['grade']['status']=='scored'),
                'last_attempt_id':answered['attempt_id'] if answered else None,
                'capabilities':self._capabilities(conn,meta),
                'notice':'固定演示评分，与输入答案内容无关。提交后才显示本题参考与解析；下一题不会提前展示。'})
