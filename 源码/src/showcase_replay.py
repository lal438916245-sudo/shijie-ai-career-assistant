"""Build the public fictional replay exclusively through real local service operations.

No SDK, credentials, provider, network or copied historical grades are involved.
"""
from contextlib import closing
from datetime import date,timedelta
from pathlib import Path
import hashlib,json,uuid
from competition_workbench import CompetitionWorkbench
from competition_showcase import PROFILE,CASE_ID,REPLAY_TOKEN,REPLAY_START

def prepare_replay(directory):
    service=CompetitionWorkbench(directory,case_profile=PROFILE)
    marker=service._session_directory(REPLAY_TOKEN)/'replay-sealed.json'
    if marker.is_file():
        result=json.loads(marker.read_text(encoding='utf-8'))
        if hashlib.sha256(service._identity(REPLAY_TOKEN)[2].read_bytes()).hexdigest()!=result['database_sha256']:
            raise ValueError('完整演示快照发生变化，请保留现状并检查，不能静默重建。')
        service.state(REPLAY_TOKEN);service.resume(REPLAY_TOKEN,result['final_resume_id'])
        return result
    if service._identity(REPLAY_TOKEN)[2].exists():raise ValueError('发现未封存的演示，请核对中断状态，不覆盖已有记录。')
    counter=0
    def identity(label):
        nonlocal counter
        counter+=1;return str(uuid.uuid5(uuid.NAMESPACE_URL,CASE_ID+':'+str(counter)+':'+label))
    def state():return service.state(REPLAY_TOKEN)
    def act(operation,**fields):
        return service.mutate(REPLAY_TOKEN,operation,{'request_id':identity(operation),'expected_revision':state()['revision'],**fields})
    service.create(REPLAY_TOKEN,{'request_id':identity('create'),'start_date':REPLAY_START})
    act('diagnosis');act('plan')
    act('review',plan_version=1);act('adopt',plan_version=1,review_id=state()['review']['review_id'])
    act('review',plan_version=2);act('publish',plan_version=2)
    initial=act('resume_generate')['resume_id']
    tasks=state()['plan']['plan']['tasks']
    def complete_run(rid,weak=False):
        rounds=0
        while True:
            run=service.assessment(REPLAY_TOKEN,rid)['run']
            if run['status']!='active':return run
            rounds+=1
            if rounds>30:raise AssertionError('Fixed replay must terminate')
            if run['question']:
                with closing(service._connect(REPLAY_TOKEN)) as conn:
                    meta=service._meta(conn);saved=service._saved_run(conn,meta,rid)
                    q=next(q for q in saved['questions'] if q['question_id']==run['question']['question_id'])
                answer=('模拟首次作答：我会使用SUM(DISTINCT 金额)去掉重复金额，没有先确认订单与明细的粒度。' if weak else
                        '模拟学习后作答（固定演示）：'+'\n'.join(str(p['reference']) for p in q['parts']))
                act('answer',run_id=rid,question_id=q['question_id'],answer=answer)
            elif run['next_available']:act('assessment_next',run_id=rid,last_attempt_id=run['last_attempt_id'])
            else:raise AssertionError('Replay stopped without a saved result')
    def retest(key):
        cap=next(c for c in state()['capabilities'] if c['topic_key']==key)
        if cap['state'] not in ('needs_retest','regressed','provisional_pass'):return
        rid=act('retest_start',plan_version=2,topic_id=cap['topic_id'],source_attempt_id=cap['latest_attempt_id'],fixture_path='repair')['run_id']
        complete_run(rid)
    for i,task in enumerate(tasks):
        day=(date.fromisoformat(REPLAY_START)+timedelta(days=task['day']-1)).isoformat()
        act('progress',plan_version=2,task_id=task['task_id'],status='completed',note='模拟学习记录：按学习卡跟做，核对参考和自查要点；不代表真实用户学习。',reason='',start_date=day,end_date=day)
        lesson=service.learning(REPLAY_TOKEN,task['task_id'])
        assert lesson['learning_card'] and lesson['learning_card']['card']['exercise']['reference_answer']
        act('learning_artifact',plan_version=2,task_id=task['task_id'])
        options=service.assessment_options(REPLAY_TOKEN,'day',day,day)['options']
        assert any(t['task_id']==task['task_id'] for t in options['tasks'])
        rid=act('assessment_start',plan_version=2,kind='day',period_start=day,period_end=day,task_ids=[task['task_id']],question_count=2,fixture_path='repair' if i==0 else 'pass')['run_id']
        complete_run(rid,weak=i==0)
        for key in task['topic_keys']:retest(key)
    for offset in (0,7):
        first=(date.fromisoformat(REPLAY_START)+timedelta(days=offset)).isoformat()
        last=(date.fromisoformat(first)+timedelta(days=6)).isoformat()
        options=service.assessment_options(REPLAY_TOKEN,'week',first,last)['options']
        rid=act('assessment_start',plan_version=2,kind='week',period_start=first,period_end=last,
          task_ids=[t['task_id'] for t in options['tasks']],question_count=5,fixture_path='pass')['run_id']
        complete_run(rid)
    iid=act('interview_start',mode='full',include_learning_evidence=True)['interview_id']
    rounds=0
    while True:
        run=service.interview(REPLAY_TOKEN,iid)['interview']
        if run['status']!='active':break
        rounds+=1;assert rounds<=7
        with closing(service._connect(REPLAY_TOKEN)) as conn:
            meta=service._meta(conn);saved=service._interview_run(conn,meta,iid);turns=service._interview_turns(conn,meta,saved)
            q=turns[-1];templates=saved['bank']['questions']+list(saved['bank']['followups'].values())
            template=next(t for t in templates if t['key']==q['question_key'])
        answer=template['examples']['needs_detail' if q['question_key'] in ('project','data') else 'clear']
        act('interview_answer',interview_id=iid,question_turn_id=q['turn_id'],answer=answer)
    final=act('resume_generate')['resume_id'];saved=service.resume(REPLAY_TOKEN,final)
    assert saved['report']['learning_handoff']['ready_tasks']==10
    assert len(saved['report']['approved_texts'])==3
    for text in (saved['report']['approved_texts'][0],'主导生产Flink链路上线，处理千万级订单，性能提升80%。'):
        act('resume_check',resume_id=final,text=text)
    state_data=state();records=service.records(REPLAY_TOKEN)['records']
    assert all(r['envelope']['case_id']==CASE_ID for r in records)
    index={r['record_id']:r for r in records}
    for r in records:assert all(p in index and index[p]['seq']<r['seq'] for p in r['parent_ids'])
    assert all(set(item['source_ids'])<=index.keys() for item in saved['report']['items'])
    assert all(c['real_state']=='unassessed' and c['state']=='mastered' for c in state_data['capabilities'])
    result={'case_id':CASE_ID,'initial_resume_id':initial,'final_resume_id':final,'interview_id':iid,'learning_tasks':10,
      'day_runs':10,'week_runs':2,'answer_count':sum(r['kind'] in ('assessment','retest') and r['payload'].get('event')=='answer_submitted' for r in records),
      'retest_runs':sum(r['kind']=='retest' for r in state_data['assessment_runs']),
      'record_count':len(records),'ready_learning_tasks':10,'revision':state_data['revision'],
      'capabilities':[{k:c[k] for k in ('topic_key','state','latest_score','real_state')} for c in state_data['capabilities']],
      'real_model_requests':0,'simulated':True,'all_references_same_session':True,
      'database_sha256':hashlib.sha256(service._identity(REPLAY_TOKEN)[2].read_bytes()).hexdigest()}
    marker.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
