"""Explicit, transactional adoption of validated C/E/D receipts.

Candidates, original answers and reports remain immutable. Adopted views are
reconstructed from the frozen receipt; synthetic sessions stay synthetic.
"""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json

from competition_workbench_assessment import digest, encode, expect, invalid
from competition_workbench_calls import fields, uid
from competition_workbench_fixtures import bound_id
from workbench_question_bank import fixed_grade, fingerprint, GRADING_VERSION, RULE_VERSION

ADOPTION_OPERATIONS = {'candidate_apply': {'authorization_id', 'candidate_digest', 'review_confirmed', 'selected_item_ids'}}


def candidate_grade(result, application):
    return {'status': 'scored', 'version': GRADING_VERSION,
        'scores': [{'topic_key': topic['topic_key'], 'score': score['score'],
                    'dimensions': {d['key']: d['score'] for d in topic['dimensions']}}
                   for topic, score in zip(result['topics'], result['server_scores'])],
        'feedback': result['feedback'], 'evidence_topics':deepcopy(result['topics']), 'source': 'reviewed_candidate',
        'application_id': application['application_id'], 'simulated': application['candidate_simulated'],
        'notice': '已核对采用的候选评分。当前是虚构案例会话，能力变化仍为演示，不证明用户真实掌握。'}


class WorkbenchCandidateAdoption:
    def _adoption_schema(self, c):
        c.execute('CREATE TABLE IF NOT EXISTS wbc_applications(application_id TEXT PRIMARY KEY,authorization_id TEXT NOT NULL UNIQUE,stage TEXT NOT NULL,target_key TEXT NOT NULL,revision INTEGER NOT NULL,record_id TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL,payload_digest TEXT NOT NULL,UNIQUE(stage,target_key))')

    def _application_rows(self, c, meta):
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='wbc_applications'").fetchone():
            return []
        cache_key=(c.total_changes,c.execute('PRAGMA data_version').fetchone()[0],self.call_transport.mode)
        cached=getattr(c,'_validated_applications',None)
        cutoff=meta.get('_application_revision',meta['revision'])
        if cached and cached[0]==cache_key:
            return [dict(a) for a in cached[1] if a['revision']<=cutoff]
        output = []
        for row in c.execute('SELECT * FROM wbc_applications ORDER BY revision'):
            app = json.loads(row['payload_json'])
            expect(digest(app) == row['payload_digest'] and app['scope'] == self._scope(meta)
                and all(app[k] == row[k] for k in ('application_id','authorization_id','stage','target_key','revision','record_id')),
                '候选采用记录的身份或快照不一致，已停止使用。')
            receipt, request = self._call_row(c, app['authorization_id'])
            expect(receipt['status'] == 'completed' and receipt['dispatch_count'] == 1
                and app['candidate'] == json.loads(receipt['result_json'])
                and app['candidate_digest'] == digest(app['candidate'])
                and app['request_digest'] == receipt['request_digest']
                and app['context'] == request['context'] and app['stage'] == request['stage']
                and app['target_id'] == request['target_id'] and app['revision'] > request['revision']
                and app['review_confirmed'] is True,
                '采用内容与原调用回执不一致，不能当作正式结果。')
            if request.get('session_runtime'):
                expect(app['candidate_simulated']==self._session_is_simulated(request) and app.get('model_provenance')==self._session_provenance(request,app['authorization_id'])['model_provenance'],'候选采用的模型来源不一致。')
            record = c.execute('SELECT * FROM wb_records WHERE record_id=?', (app['record_id'],)).fetchone()
            expect(record is not None and json.loads(record['payload_json']) == {'event':'candidate_adopted', **app}
                and json.loads(record['parent_ids_json']) == app['parent_ids'], '候选采用的来源记录缺失或变化。')
            expect(app['target_key'] == self._adoption_key(request), '采用的目标槽位不一致。')
            self._validate_selection(app['stage'], app['candidate'], app['selected_item_ids'])
            output.append({**app, 'commit_seq': record['seq']})
        # No process/global cache: changes in this transaction or another SQLite
        # connection invalidate it. Views below treat cached nested values as read-only.
        if hasattr(c,'__dict__'):
            c._validated_applications=(cache_key,output)
        return [dict(a) for a in output if a['revision']<=cutoff]

    def _application_for(self, c, meta, stage, key):
        return next((a for a in self._application_rows(c, meta) if a['stage'] == stage and a['target_key'] == key), None)

    @staticmethod
    def _adoption_key(request):
        return request['context'].get('target_question_id') if request['stage'] == 'c_question' else (
            request['context']['pending_question_id'] if request['stage'] == 'e_turn' else request['target_id'])

    @staticmethod
    def _validate_selection(stage, candidate, selected):
        expect(isinstance(selected, list) and all(isinstance(v,str) for v in selected)
               and len(set(selected)) == len(selected), '请核对采用条目，不可重复或提交其他内容。')
        if stage == 'd_revision':
            allowed = {i['item_id'] for i in candidate['items'] if i['server_status'] in ('original_self_report_only','needs_human_verification')}
            expect(bool(selected) and set(selected) <= allowed, '请选择至少一条经本人核对的简历修改；被拦截条目不能采用。')
            refs = [i['original_ref'] for i in candidate['items'] if i['item_id'] in selected]
            expect(not any(a['start'] < b['end'] and b['start'] < a['end'] for n,a in enumerate(refs) for b in refs[n+1:]),
                   '所选简历修改区间重叠，请分开核对，不能静默覆盖。')
        else:
            expect(not selected, '本项按完整候选采用，不接受额外选择。')
        if stage == 'c_grade':
            expect(candidate['status'] == 'scored' and candidate['confidence'] != 'low'
                and all(type(t['score']) is int for t in candidate['server_scores']),
                '本份评分仍待复核，不能采用为正式分数，也不按 0 分处理。')

    def _adoption_candidate(self, c, meta, authorization_id):
        row, request = self._call_row(c, uid(authorization_id))
        expect(row['status'] == 'completed' and row['result_json'], '只有已完整返回并通过合同校验的候选可进入核对。')
        return row, request, json.loads(row['result_json'])

    def _adoption_current(self, c, meta, request):
        from competition_workbench import WorkbenchConflict
        try:
            current = self._call_context(c,meta,request['stage'],request['target_id'])
        except WorkbenchConflict:
            return False
        original = deepcopy(request['context'])
        current.pop('session_revision',None);original.pop('session_revision',None)
        return current == original

    def call_adoption_preview(self, token, body):
        fields(body, ('authorization_id',))
        with self.lock, closing(self._connect(token)) as c:
            meta = self._context(c, self._meta(c))
            row, request, candidate = self._adoption_candidate(c, meta, body['authorization_id'])
            existing = self._application_for(c, meta, request['stage'], self._adoption_key(request))
            occupied = bool(existing and existing['authorization_id'] != row['authorization_id'])
            own = existing if existing and not occupied else None
            stale = bool(not existing and not self._adoption_current(c,meta,request))
            public = deepcopy(candidate)
            if request['stage'] == 'c_question':
                public.pop('reference_outline', None)
            return self._reply(mode=request['mode'], external_network_allowed=False, actual_model_cost=0,
                authorization_id=row['authorization_id'], stage=request['stage'], target_id=request['target_id'],
                candidate_digest=digest(candidate), candidate=public, revision=meta['revision'],
                source_revision=request['revision'], stale=stale,
                application_id=own['application_id'] if own else None,
                record_id=own['record_id'] if own else None,
                formal_resume_id=own.get('formal_resume_id') if own else None,
                blocked_reason=('该目标已采用另一份候选，当前候选未被采用，不能覆盖。' if occupied else '评分仍待复核，暂不保存为正式分数。'),
                selectable_item_ids=[i['item_id'] for i in candidate.get('items',[]) if i['server_status'] != 'blocked_unsupported_upgrade'],
                can_apply=not stale and existing is None and (request['stage'] != 'c_grade' or candidate['status'] == 'scored'),
                notice='采用只保存本机会话结果，不调用模型。请核对题目范围、评分证据或改写事实；本地替身结果仍标记为演示。')

    def _do_candidate_apply(self, c, meta, body):
        expect(body['review_confirmed'] is True, '请先核对候选内容与来源，再明确确认采用。')
        row, request, candidate = self._adoption_candidate(c, meta, body['authorization_id'])
        expect(body['candidate_digest'] == digest(candidate), '候选内容摘要不一致，请重新读取核对内容。')
        self._validate_selection(request['stage'], candidate, body['selected_item_ids'])
        key = self._adoption_key(request)
        expect(self._application_for(c, meta, request['stage'], key) is None, '这个目标已有正式采用结果，请查看原采用记录。')
        expect(self._adoption_current(c,meta,request),
               '候选生成后会话或目标已变化，不能覆盖新结果；请保留原回执，重新准备候选。')
        stage = request['stage']; context = request['context']
        if stage == 'c_question':
            run = self._saved_run(c, meta, request['target_id'])
            parents = [run['question_records'][key]]
            kind = 'retest' if run['kind'] == 'retest' else 'assessment'
        elif stage == 'c_grade':
            answer = next(a for a in self._answer_rows(c, meta) if a['attempt_id'] == key)
            parents = [answer['record_id']]; kind = 'retest' if answer['kind'] == 'retest' else 'assessment'
        elif stage.startswith('e_'):
            r = self._interview_run(c, meta, request['target_id'])
            if stage == 'e_turn':
                parents = [c.execute('SELECT record_id FROM wbi_turns WHERE turn_id=?', (key,)).fetchone()[0]]
            else:
                parents = [r['interview_id'] + ':report']
            kind = 'interview'
        else:
            parents = [key + ':report']; kind = 'resume'
        app_id = bound_id(meta['session_id'], 'application', body['request_id'])
        app = {'application_id': app_id, 'authorization_id': row['authorization_id'], 'stage':stage,
            'target_id':request['target_id'], 'target_key':key, 'revision':meta['revision']+1,
            'scope':self._scope(meta), 'candidate_digest':digest(candidate), 'request_digest':row['request_digest'],
            'candidate':candidate, 'context':context, 'review_confirmed':True,
            'selected_item_ids':body['selected_item_ids'], 'record_id':app_id+':adopted', 'parent_ids':parents,
            'created_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'candidate_simulated':self._session_is_simulated(request) if request.get('session_runtime') else request['mode'] != 'ced_trial' or self.call_transport.http_client_factory is not None,
            **self._session_provenance(request,row['authorization_id']),
            'notice':'同一虚构会话内经核对采用；固定替身结果不证明真实能力或简历事实。'}
        if stage == 'd_revision':
            app['formal_resume_id'] = bound_id(meta['session_id'], 'resume', body['request_id'])
        self._record(c, meta, app['record_id'], kind, '核对采用 · '+stage,
                     {'event':'candidate_adopted', **app}, parents, source='user_review')
        c.execute('INSERT INTO wbc_applications VALUES (?,?,?,?,?,?,?,?)',
            (app_id,row['authorization_id'],stage,key,app['revision'],app['record_id'],encode(app),digest(app)))
        effective_meta = {**meta, 'revision':meta['revision']+1}
        if stage == 'd_revision':
            self._resume_schema(c)
            base = self._resume_saved(c, meta, key)
            report = self._adopted_resume_report(base['report'], app)
            saved = {'resume_id':app['formal_resume_id'], 'snapshot':base['snapshot'], 'report':report,
                     'model_application_id':app_id, 'base_resume_id':key}
            rid = app['formal_resume_id'] + ':report'
            self._record(c, meta, rid, 'resume', 'D · 已核对采用的简历版本',
                {'event':'resume_report','resume_id':app['formal_resume_id']}, [app['record_id']])
            c.execute('INSERT INTO wbd_reports VALUES (?,?,?,?)', (app['formal_resume_id'],rid,encode(saved),digest(saved)))
        if stage == 'c_grade':
            answer = next(a for a in self._answer_rows(c, effective_meta) if a['attempt_id'] == key)
            run = self._saved_run(c, effective_meta, answer['run_id'])
            if run['kind'] == 'retest' and run['status'] == 'active' and run['questions'][run['cursor']]['question_id'] == answer['question_id']:
                run['last_attempt_id'] = key
                p = next(p for p in self._capabilities(c, effective_meta) if p['topic_id'] == run['topic_id'])
                if p['state'] == 'mastered' or run['cursor'] >= 2:
                    run.update(status='completed',stop_reason='采用评分后满足停止条件；请查看答卷和能力依据。')
                self._save_run(c, run)
            self._record(c, meta, app_id+':projection', 'mastery', '采用评分后更新会话演示状态',
                {'event':'demo_projection','rule_version':RULE_VERSION,'trigger_attempt_id':key, 'application_id':app_id,
                 'before':self._capabilities(c, meta), 'after':self._capabilities(c, effective_meta),
                 'notice':'候选评分已采用；固定案例仍不写入真实能力状态。'},
                 list(dict.fromkeys([a['record_id'] for a in self._answer_rows(c, meta)] + [app['record_id']])),
                source='deterministic_projection', usage='derived_mastery')
        return {'application_id':app_id, 'record_id':app['record_id'], 'stage':stage,
                'formal_resume_id':app.get('formal_resume_id')}

    def _initial_grade(self, question, kind, path, ordinal):
        if question.get('model_application'):
            return {'status':'review_required','version':GRADING_VERSION,'scores':[],
                    'feedback':'本题已采用候选题目，等待独立评分与核对采用；不沿用固定路线分数。'}
        return fixed_grade(question, kind, path, ordinal)

    def _saved_run(self, c, meta, rid):
        run = super()._saved_run(c, meta, rid)
        for q in run['questions']:
            app = self._application_for(c, meta, 'c_question', q['question_id'])
            if app:
                result = app['candidate']
                q.update(prompt=result['prompt'],fingerprint=fingerprint(result['prompt']),
                    model_application={'application_id':app['application_id'],'record_id':app['record_id'],
                                       'simulated':app['candidate_simulated']},
                    basis='已核对采用的候选题，专题与量表仍绑定本会话任务。',branch='reviewed_candidate')
                if 'practice_repeat' in result:
                    q['practice_repeat']=result['practice_repeat'];q['practice_notice']=result['practice_notice']
                    q['basis']+=' '+result['practice_notice']
                for part in q['parts']:
                    part.update(prompt=result['prompt'],reference=result['reference_outline'])
        return run

    def _answer_rows(self, c, meta):
        answers = super()._answer_rows(c, meta)
        for a in answers:
            app = self._application_for(c, meta, 'c_grade', a['attempt_id'])
            if app:
                a['initial_grade'] = a['grade']
                a['grade'] = candidate_grade(app['candidate'], app)
                a['notice'] = a['grade']['notice']
                a['model_application'] = {'application_id':app['application_id'],'record_id':app['record_id'],
                                          'simulated':app['candidate_simulated']}
                a['grade_commit_seq'] = app['commit_seq']
            else:
                from competition_short_flow import pending_feedback
                feedback=pending_feedback(self,c,meta,a)
                if feedback:a['pending_feedback']=feedback
        return answers

    def _interview_turns(self, c, meta, r):
        turns = super()._interview_turns(c, meta, r)
        for turn in turns:
            app = self._application_for(c, meta, 'e_turn', turn['turn_id'])
            if app:
                turn.update(text=app['candidate']['text'], requirement_ids=app['candidate']['requirement_ids'],
                            model_application={'application_id':app['application_id'],'record_id':app['record_id'],
                                               'simulated':app['candidate_simulated']},
                            routing_notice='此问题为已核对采用的候选；后续轮数与岗位覆盖仍由会话控制。')
        return turns

    def _interview_report(self, c, meta, r, turns):
        report = super()._interview_report(c, meta, r, turns)
        if report:
            app = self._application_for(c, meta, 'e_report', r['interview_id'])
            if app:
                report = deepcopy(report)
                by_id = {f['answer_turn_id']:f for f in app['candidate']['findings']}
                for finding in report['findings']:
                    candidate = by_id[finding['answer_turn_id']]
                    finding.update(analysis_kind='candidate_reviewed',observation=candidate['observation'],
                        suggestion=candidate['suggestion'],quote=candidate['evidence'][0]['quote'] if candidate['evidence'] else '',
                        evidence=deepcopy(candidate['evidence']),confidence=candidate['confidence'],issue=None)
                report.update(model_application={'application_id':app['application_id'],'record_id':app['record_id'],
                              'simulated':app['candidate_simulated']}, issue_count=0,clear_sample_count=0,
                              unreviewed_count=0,notice='已核对采用的候选复盘；引用原话给出建议，不评分、不升级简历事实。')
            else:report=self._ce_report_pending(c,report)
        return report

    def _resume_saved(self, c, meta, rid):
        if not self._has_resumes(c):
            return super()._resume_saved(c, meta, rid)
        row = c.execute('SELECT * FROM wbd_reports WHERE resume_id=?', (rid,)).fetchone()
        if not row:
            return super()._resume_saved(c, meta, rid)
        saved = json.loads(row['payload_json'])
        if saved.get('model_application_id'):
            expect(digest(saved)==row['payload_digest'], '采用后的简历快照校验失败。')
            app = next((a for a in self._application_rows(c, meta) if a['application_id']==saved['model_application_id']),None)
            expect(app is not None and app.get('formal_resume_id')==rid, '简历采用来源缺失。')
            base = self._resume_saved(c, meta, saved['base_resume_id'])
            expect(saved['snapshot']==base['snapshot'] and saved['report']==self._adopted_resume_report(base['report'],app),
                   '正式简历与核对采用的结果不一致。')
            reference = self._source_row(c, meta, row['record_id'])
            expect(json.loads(reference['parent_ids_json'])==[app['record_id']]
                and json.loads(reference['payload_json'])=={'event':'resume_report','resume_id':rid}, '正式简历的引用不一致。')
            return saved
        frozen = {**meta, '_application_revision':saved['snapshot']['revision']}
        return super()._resume_saved(c, frozen, rid)

    @staticmethod
    def _adopted_resume_report(base, app):
        report = deepcopy(base)
        items = []
        for i in app['candidate']['items']:
            if i['item_id'] not in app['selected_item_ids']:
                continue
            refs = [i['original_ref'], *i.get('supporting_refs',[])]
            sources = [app['record_id']] + [ref['source_id'] if ref['source_id']!='resume_original' else base['sources'][0]['record_id'] for ref in refs]
            items.append({'item_id':i['item_id'],'status':'suggested','title':'核对采用的简历修改',
                'original_quote':i['original_ref']['quote'],'original_ref':i['original_ref'],
                'suggested_text':i['proposed_text'],'reason':i['rationale'],'source_ids':list(dict.fromkeys(sources)),
                'evidence_level':'本人核对 / 原文自述或课程成果，未独立核验', 'next_action':'使用前核实所有事实及课程练习边界。'})
        report['items'] = items
        report['approved_texts'] = [i['suggested_text'] for i in items]
        text = report['resume_text']
        for i in sorted(items, key=lambda v:v['original_ref']['start'],reverse=True):
            ref = i['original_ref']
            text = text[:ref['start']] + i['suggested_text'] + text[ref['end']:]
        report.update(final_draft=text, server_accepted_item_ids=[i['item_id'] for i in items],
            snapshot_revision=app['revision'], created_at=app['created_at'],
            model_application={'application_id':app['application_id'],'record_id':app['record_id'], 'simulated':app['candidate_simulated']},
            notice='已核对采用并在同一会话保存为新的简历版本；原文、原候选与旧版本保留。事实仍由本人核实。')
        if app.get('model_provenance'):
            report['model_provenance']=deepcopy(app['model_provenance'])
            report['result_origin']='sdk_rehearsal_reviewed' if app['candidate_simulated'] else 'real_model_reviewed'
        report['sources'].append({'record_id':app['record_id'],'kind':'resume','title':'简历候选核对采用记录',
            'seq':None,'view':{'application_id':app['application_id'],'notice':app['notice']}})
        return report

    def _public_application(self, c, app):
        value = {k:deepcopy(v) for k,v in app.items() if k!='context'}
        if app['stage']=='c_question' and not c.execute('SELECT 1 FROM wba_answers WHERE question_id=?',(app['target_key'],)).fetchone():
            value['candidate'].pop('reference_outline',None)
        return value
