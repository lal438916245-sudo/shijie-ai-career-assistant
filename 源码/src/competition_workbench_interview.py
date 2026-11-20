"""Bounded job-wide dialogue adapter, local doubles only; no SDK or Key access."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timezone
import json
from competition_case import validate_source
from competition_workbench_fixtures import bound_id
from diagnosis_evidence import build_jd_outline
from competition_workbench_assessment import encode,digest,expect,invalid
from workbench_interview_bank import bank,classify,build_report

INTERVIEW_OPERATIONS={
    'interview_start':{'mode','include_learning_evidence'},
    'interview_answer':{'interview_id','question_turn_id','answer'},
    'interview_end':{'interview_id'}}

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')

class WorkbenchInterview:
    def _interview_schema(self,conn):
        conn.execute('CREATE TABLE IF NOT EXISTS wbi_runs(interview_id TEXT PRIMARY KEY,payload_json TEXT NOT NULL,payload_digest TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS wbi_turns(turn_id TEXT PRIMARY KEY,interview_id TEXT NOT NULL,seq INTEGER NOT NULL,record_id TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL,payload_digest TEXT NOT NULL,UNIQUE(interview_id,seq))')
        conn.execute('CREATE TABLE IF NOT EXISTS wbi_reports(interview_id TEXT PRIMARY KEY,record_id TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL,payload_digest TEXT NOT NULL)')

    def _has_interviews(self,conn):return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='wbi_runs'").fetchone())

    def _interview_run(self,conn,meta,iid):
        expect(isinstance(iid,str) and self._has_interviews(conn),'本会话没有这份面试，请重新读取。')
        row=conn.execute('SELECT * FROM wbi_runs WHERE interview_id=?',(iid,)).fetchone()
        expect(row is not None,'面试不属于当前会话。')
        r=json.loads(row['payload_json'])
        expect(digest(r)==row['payload_digest'] and r['scope']==self._scope(meta) and r['interview_id']==iid,'面试快照来源校验失败。')
        expect(r['context']['input_digest']==meta['input_digest'] and r['context']['position']==meta['package']['case']['position'], '面试岗位来源不一致。')
        start=conn.execute('SELECT payload_json,envelope_json FROM wb_records WHERE record_id=?',(r['start_record_id'],)).fetchone()
        expect(start is not None,'面试开始记录缺失，停止使用。')
        reference=json.loads(start[0]);env=validate_source(json.loads(start[1]))
        expect(reference.get('event')=='interview_started' and reference.get('interview_id')==iid and
            env['record_kind']=='interview' and env['source_kind']=='fixed_stub_output' and
            all(env[k]==meta[k] for k in r['scope']),'面试开始记录来源错配。')
        return r

    def _save_interview(self,conn,r):
        conn.execute('INSERT INTO wbi_runs VALUES (?,?,?) ON CONFLICT(interview_id) DO UPDATE SET payload_json=excluded.payload_json,payload_digest=excluded.payload_digest',
            (r['interview_id'],encode(r),digest(r)))

    def _interview_turns(self,conn,meta,r):
        rows=[]
        sql='SELECT t.*,e.payload_json AS reference_json,e.envelope_json,e.seq AS commit_seq FROM wbi_turns t JOIN wb_records e ON e.record_id=t.record_id WHERE t.interview_id=? ORDER BY t.seq'
        for row in conn.execute(sql,(r['interview_id'],)):
            t=json.loads(row['payload_json']);reference=json.loads(row['reference_json']);env=json.loads(row['envelope_json']);validate_source(env)
            expect(digest(t)==row['payload_digest'] and t['interview_id']==r['interview_id'] and t['scope']==r['scope'] and t['turn_id']==row['turn_id'], '对话快照校验失败。')
            expect(env['record_kind']=='interview' and env['source_kind']=='fixed_stub_output' and all(env[k]==meta[k] for k in r['scope']), '对话记录不属于本演示会话。')
            expect(reference=={'event':'interview_turn','interview_id':r['interview_id'],'turn_id':t['turn_id']},'对话引用不一致，停止展示。')
            expect(t['seq']==len(rows)+1 and t['role']==('assistant' if len(rows)%2==0 else 'user'),'对话顺序不完整，不能跳轮。')
            if t['role']=='user':expect(rows and t['question_turn_id']==rows[-1]['turn_id'],'回答没有引用上一条问题。')
            rows.append(t)
        count=conn.execute('SELECT COUNT(*) FROM wbi_turns WHERE interview_id=?',(r['interview_id'],)).fetchone()[0]
        expect(len(rows)==count and rows,'对话来源记录缺失，不能当作空面试。')
        return rows

    def _add_interview_turn(self,conn,meta,r,role,text,**extra):
        seq=conn.execute('SELECT COUNT(*) FROM wbi_turns WHERE interview_id=?',(r['interview_id'],)).fetchone()[0]+1
        tid=bound_id(meta['session_id'],'iturn',r['interview_id']+':'+str(seq));record_id=tid+':saved'
        t={'turn_id':tid,'interview_id':r['interview_id'],'seq':seq,'role':role,'text':text,'scope':r['scope'],
            'created_at':now(),**extra}
        parents=[r['start_record_id']] if seq==1 else [conn.execute('SELECT record_id FROM wbi_turns WHERE interview_id=? AND seq=?',(r['interview_id'],seq-1)).fetchone()[0]]
        self._record(conn,meta,record_id,'interview',('面试官提问' if role=='assistant' else '面试回答')+f' · 对话第{seq}条',
            {'event':'interview_turn','interview_id':r['interview_id'],'turn_id':tid},parents)
        conn.execute('INSERT INTO wbi_turns VALUES (?,?,?,?,?,?)',(tid,r['interview_id'],seq,record_id,encode(t),digest(t)))
        return t

    def _ask_interview(self,conn,meta,r,template,main_index,is_followup,parent_answer=None):
        topics={t['topic_key']:t for t in (meta['bindings'] or {}).get('topics',[])}
        t=self._add_interview_turn(conn,meta,r,'assistant',template['prompt'],question_key=template['key'],title=template['title'],
            main_index=main_index,is_followup=is_followup,parent_answer_id=parent_answer,
            topic_ids=[topics[k]['topic_id'] for k in template['topic_keys'] if k in topics],requirement_ids=template['requirement_ids'],
            routing_notice='预设位置的澄清追问，不判断回答对错。' if is_followup else '按岗位覆盖计划进入下一个方向。')
        r['current_question_id']=t['turn_id']

    def _interview_context(self,conn,meta,include):
        context={'candidate':deepcopy(meta['package']['case']['candidate']),'position':deepcopy(meta['package']['case']['position']),
            'input_digest':meta['input_digest'],'diagnosis_record_id':meta['session_id']+':diagnosis',
            'jd_requirements':build_jd_outline(meta['inputs']['jd_text'])}
        parents=[meta['session_id']+':input',meta['session_id']+':diagnosis']
        if include:
            context['learning_summary']={'plan_version':meta['published_version'],
                'progress':[dict(row) for row in conn.execute('SELECT task_id,status,revision,start_date,end_date FROM wb_progress ORDER BY task_id')],
                'capabilities':[{'topic_id':p['topic_id'],'title':p['title'],'state':p['state'],'latest_score':p['latest_score'],
                    'evidence_ids':p['evidence_ids'],'simulated':True} for p in self._capabilities(conn,meta)],
                'notice':'只加入进度/演示能力摘要，不包含学习笔记或答卷正文；不据此缩减整个岗位范围。'}
            if meta['published_version']:parents.append(self._plan(conn,meta['published_version'])['record_id'])
        return context,parents

    def _do_interview_start(self,conn,meta,body):
        expect(meta['diagnosis'] is not None and meta['bindings'],'请先完成本会话岗位诊断，再开始岗位面试；无需先通过所有学习考核。')
        if body['mode'] not in ('full','quick','short') or type(body['include_learning_evidence']) is not bool:invalid('请检查面试模式与资料选择。')
        for row in conn.execute('SELECT interview_id FROM wbi_runs'):
            expect(self._interview_run(conn,meta,row[0])['status']!='active','已有进行中的面试，请继续或结束后再新建。')
        context,parents=self._interview_context(conn,meta,body['include_learning_evidence']);b=bank()
        if meta['package']['case']['version']==2:
            mapping={'project':['JD-07','JD-09'],'data':['JD-02','JD-03'],'stream':['JD-04'],
                     'engineering':['JD-05','JD-12'],'communication':['JD-09','JD-10'],
                     'project_followup':['JD-07','JD-09'],'data_followup':['JD-02','JD-03']}
            for question in b['questions']+list(b['followups'].values()):
                question['requirement_ids']=mapping[question['key']]
        if meta['package'].get('personal_input'):
            from personal_workbench_input import personal_interview_bank
            b=personal_interview_bank(b,meta['package'])
        iid=bound_id(meta['session_id'],'interview',body['request_id']);start_id=iid+':started'
        r={'interview_id':iid,'scope':self._scope(meta),'status':'active','mode':body['mode'],'bank':b,
            'main_keys':[q['key'] for q in b['questions'][:5 if body['mode']=='full' else 1 if body['mode']=='short' else 3]],
            'max_followups':2 if body['mode']=='full' else 0 if body['mode']=='short' else 1,'followups_used':0,'current_question_id':None,
            'context':context,'context_selection':{'include_learning_evidence':body['include_learning_evidence'],'notes_included':False,'answer_text_included':False},
            'created_at':now(),'ended_at':None,'start_record_id':start_id}
        self._record(conn,meta,start_id,'interview','开始岗位级模拟面试',{'event':'interview_started','interview_id':iid,
            'mode':r['mode'],'position_title':context['position']['title'],'context_selection':r['context_selection'],
            'planned_main':len(r['main_keys']),'max_followups':r['max_followups']},parents)
        self._ask_interview(conn,meta,r,b['questions'][0],0,False);self._save_interview(conn,r)
        return {'interview_id':iid}

    def _finish_interview(self,conn,meta,r,status):
        r.update(status=status,current_question_id=None,ended_at=now());self._save_interview(conn,r)
        turns=self._interview_turns(conn,meta,r);report=build_report(r,turns);rid=r['interview_id']+':report'
        parents=[row[0] for row in conn.execute('SELECT record_id FROM wbi_turns WHERE interview_id=? ORDER BY seq',(r['interview_id'],))]
        self._record(conn,meta,rid,'interview','岗位面试复盘 · '+('已完成' if status=='completed' else '提前结束'),
            {'event':'interview_report','interview_id':r['interview_id']},parents)
        conn.execute('INSERT INTO wbi_reports VALUES (?,?,?,?)',(r['interview_id'],rid,encode(report),digest(report)))
        return rid

    def _do_interview_answer(self,conn,meta,body):
        r=self._interview_run(conn,meta,body['interview_id']);expect(r['status']=='active','面试已结束，请查看已保存报告。')
        turns=self._interview_turns(conn,meta,r);q=turns[-1]
        expect(q['role']=='assistant' and q['turn_id']==body['question_turn_id']==r['current_question_id'],'请回答当前这一轮问题，不能跳轮或覆盖旧回答。')
        if not isinstance(body['answer'],str) or not body['answer'].strip() or len(body['answer'])>6000:invalid('请填写1～6000字回答后发送。')
        a=self._add_interview_turn(conn,meta,r,'user',body['answer'],question_turn_id=q['turn_id'],answer_origin='user_entered_text')
        main=r['bank']['questions'][q['main_index']]
        template=r['bank']['followups'].get(main['key'])
        if not q['is_followup'] and template and r['followups_used']<r['max_followups'] and classify(main,body['answer'])!='clear':
            r['followups_used']+=1;self._ask_interview(conn,meta,r,template,q['main_index'],True,a['turn_id'])
        elif q['main_index']+1<len(r['main_keys']):
            self._ask_interview(conn,meta,r,r['bank']['questions'][q['main_index']+1],q['main_index']+1,False,a['turn_id'])
        else:
            rid=self._finish_interview(conn,meta,r,'completed')
            return {'interview_id':r['interview_id'],'answer_turn_id':a['turn_id'],'report_record_id':rid}
        self._save_interview(conn,r)
        return {'interview_id':r['interview_id'],'answer_turn_id':a['turn_id']}

    def _do_interview_end(self,conn,meta,body):
        r=self._interview_run(conn,meta,body['interview_id']);expect(r['status']=='active','这份面试已经结束。')
        self._interview_turns(conn,meta,r)
        rid=self._finish_interview(conn,meta,r,'ended_early')
        return {'interview_id':r['interview_id'],'report_record_id':rid}

    def _interview_report(self,conn,meta,r,turns):
        row=conn.execute('SELECT * FROM wbi_reports WHERE interview_id=?',(r['interview_id'],)).fetchone()
        if r['status']=='active':
            expect(row is None,'面试状态与复盘不一致。');return None
        expect(row is not None,'复盘尚不可用；不能把已结束状态当作报告已保存。')
        value=json.loads(row['payload_json'])
        expect(digest(value)==row['payload_digest'] and value==build_report(r,turns),'复盘与原始对话不一致，停止展示。')
        rec=conn.execute('SELECT payload_json,envelope_json FROM wb_records WHERE record_id=?',(row['record_id'],)).fetchone()
        expect(rec is not None and json.loads(rec[0])=={'event':'interview_report','interview_id':r['interview_id']},'复盘来源记录缺失或错配。')
        env=validate_source(json.loads(rec[1]));expect(env['record_kind']=='interview' and env['source_kind']=='fixed_stub_output' and all(env[k]==meta[k] for k in r['scope']),'复盘来源不属于本会话。')
        return value

    def _interview_state(self,conn,meta):
        runs=[]
        if self._has_interviews(conn):
            for row in conn.execute('SELECT interview_id FROM wbi_runs ORDER BY rowid DESC'):
                r=self._interview_run(conn,meta,row[0]);turns=self._interview_turns(conn,meta,r)
                self._interview_report(conn,meta,r,turns)
                runs.append({'interview_id':r['interview_id'],'status':r['status'],'mode':r['mode'],
                    'position_title':r['context']['position']['title'],'created_at':r['created_at'],
                    'answered_count':sum(t['role']=='user' for t in turns)})
        return {'interviews':runs}

    def interview(self,token,iid):
        with self.lock,closing(self._connect(token)) as conn:
            meta=self._meta(conn);r=self._interview_run(conn,meta,iid);turns=self._interview_turns(conn,meta,r)
            current=next((t for t in turns if t['turn_id']==r['current_question_id']),None)
            examples=None
            if current and not current.get('model_application'):
                templates=r['bank']['questions']+list(r['bank']['followups'].values())
                examples=next(q['examples'] for q in templates if q['key']==current['question_key'])
            return self._reply(scope=self._scope(meta),revision=meta['revision'],interview={
                **{k:r[k] for k in ('interview_id','status','mode','context_selection','created_at','ended_at','followups_used','max_followups')},
                'position':r['context']['position'],'candidate_name':r['context']['candidate']['display_name'],
                'persona':r['bank']['persona'],'planned_main':len(r['main_keys']),
                'context_summary':r['context'].get('learning_summary'),
                'coverage_plan':[{'title':q['title'],'planned':q['key'] in r['main_keys']} for q in r['bank']['questions']],
                'turns':turns,'current_question':current,'examples':examples,
                'report':self._interview_report(conn,meta,r,turns),
                'notice':'岗位级固定对话；追问按预设分支，示例分析只匹配内置示例，自定义回答不做语义评价。不评分、不更新能力、不自动改学习计划。'})

    def _interview_record_payloads(self,conn,meta,only_interview_ids=None):
        output={}
        if not self._has_interviews(conn):return output
        for row in conn.execute('SELECT interview_id FROM wbi_runs'):
            if only_interview_ids is not None and row[0] not in only_interview_ids:continue
            r=self._interview_run(conn,meta,row[0]);turns=self._interview_turns(conn,meta,r)
            for t in turns:
                record=conn.execute('SELECT record_id FROM wbi_turns WHERE turn_id=?',(t['turn_id'],)).fetchone()[0]
                output[record]={'event':'interview_turn','interview_id':r['interview_id'],'turn':t}
            report=self._interview_report(conn,meta,r,turns)
            if report:output[r['interview_id']+':report']={'event':'interview_report','interview_id':r['interview_id'],'report':report}
        return output
