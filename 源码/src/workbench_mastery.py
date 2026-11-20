"""Isolated demo projection, ordered by server commit sequence. No fake real admission."""
from decimal import Decimal,ROUND_HALF_EVEN
from assessment_rules import coerce_score,is_passing
from workbench_question_bank import RULE_VERSION,GRADING_VERSION,fingerprint

LABELS={'unassessed':'尚未考核','learning':'待首次验证','review_required':'需复核','needs_retest':'待补强复测',
 'regressed':'出现回退','provisional_pass':'暂时通过','mastered':'满足演示掌握条件'}

def topic_score(definition,values):
    dims=definition['dimensions'];keys=[d['key'] for d in dims]
    if definition['version']!=GRADING_VERSION or not keys or len(set(keys))!=len(keys) or set(values)!=set(keys):raise ValueError('rubric keys')
    if any(type(d['weight']) is not int or d['weight']<=0 for d in dims) or sum(d['weight'] for d in dims)!=10000:raise ValueError('rubric weights')
    if any(coerce_score(values[k]) is None for k in keys):raise ValueError('rubric values')
    return int((sum(Decimal(str(values[d['key']]))*d['weight'] for d in dims)/10000).quantize(Decimal('1'),rounding=ROUND_HALF_EVEN))

def project_topic(topic,answers,has_tasks=True):
    """Caller validates scope/snapshot; fixed evidence stays demo, never rubric_weighted."""
    passed=set();question_ids=set();ever_mastered=False;valid=[];pending=[]
    for answer in sorted(answers,key=lambda a:a['commit_seq']):
        if topic not in answer['topic_keys']:continue
        if answer.get('source_kind')!='fixed_stub_output' or answer.get('run_mode')!='demo' or not answer.get('simulated'):
            raise ValueError('non-demo answer rejected')
        if answer['grade']['status']!='scored':pending.append(answer['attempt_id']);continue
        component=next((s for s in answer['grade']['scores'] if s['topic_key']==topic),None)
        part=next((p for p in answer['question']['parts'] if p['topic_key']==topic),None)
        if component is None or part is None or topic_score(part['rubric'],component['dimensions'])!=component['score']:raise ValueError('invalid topic component')
        valid.append((answer,component['score']))
        if is_passing(component['score']):
            # A multi-topic question with another section changed is not a new
            # independent check of this unchanged topic section.
            if answer['question_id'] not in question_ids and not answer['question'].get('practice_repeat'):passed.add(fingerprint(part['prompt']))
            question_ids.add(answer['question_id'])
            if len(passed)>=2:ever_mastered=True
        else:passed.clear();question_ids.clear()
    if not valid:
        state='review_required' if pending else 'learning' if has_tasks else 'unassessed'
        why='评分信息不足，不等于不及格。' if pending else '暂无已提交、分项完整的演示答卷；学习完成不自动通过。'
    elif not is_passing(valid[-1][1]):
        state='regressed' if ever_mastered else 'needs_retest';why='最近一次有效专题分项低于60；旧通过不能抵消新失败。'
    elif len(passed)>=2:state='mastered';why='最近失败后已通过两道不同题面（且不同题目）的演示检查。'
    else:state='provisional_pass';why='目前仅一道独立题面通过，需再验证迁移能力。'
    return {'topic_key':topic,'state':state,'label':LABELS[state],'explanation':why,'rule_version':RULE_VERSION,
        'pass_score':60,'distinct_passes':len(passed),'latest_score':valid[-1][1] if valid else None,
        'latest_attempt_id':valid[-1][0]['attempt_id'] if valid else None,
        'evidence_ids':[a['attempt_id'] for a,s in valid],'pending_ids':pending,
        'real_state':'unassessed','simulated':True,'run_mode':'demo',
        'notice':'这是隔离的演示状态，不代表你的真实能力；未写入真实掌握状态。'}
