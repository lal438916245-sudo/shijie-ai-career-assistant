"""Job-neutral personal A/D inputs; optional curated data curriculum is separate.

This module performs no network calls, SDK construction or Key access. A
personal input is a user self-report, never a verified skill or a demo identity.
"""
from copy import deepcopy
import hashlib,json,re
from competition_sessions import SessionInput
from diagnosis_evidence import build_jd_outline,validate_evidence_audit
from competition_workbench_assessment import expect,invalid

VERSION='personal-data-input-v1'
PATTERNS={
 'sql':r'\bSQL\b|数据库查询|多表|查询|连接|关联',
 'model':r'数仓|建模|事实粒度|数据模型|维度|数据质量|唯一键',
 'stream':r'实时|\bFlink\b|\bKafka\b|事件时间|水位线|检查点|checkpoint',
 'engineering':r'测试|日志|监控|复现|验证|排查|\bGit\b',
}
def canonical_inputs(body):
    keys={'request_id','start_date','target_role','resume_text','jd_text'}
    if not isinstance(body,dict) or set(body)!=keys:invalid('个人会话字段不完整或包含额外设置。')
    try:
        value=SessionInput.model_validate({k:body[k] for k in ('target_role','resume_text','jd_text')}|{
            'available_days':14,'learning_preferences':{'daily_minutes':60,'starting_level':'beginner'}}).model_dump(exclude_none=True)
    except ValueError:invalid('请填写岗位名称、至少20字的简历/概况及至少20字的JD；简历最多60000字、JD最多30000字。')
    return value

def curriculum_requirements(inputs):
    """Do not attach SQL/testing cards to unrelated careers just by keyword overlap."""
    eligible=bool(re.search(r'数据开发|数据工程|数仓|大数据|\bETL\b|data engineer',inputs['target_role'],re.I))
    eligible=eligible and not re.search(r'高级|资深|架构师|总监|负责人|\bsenior\b|\blead\b',inputs['target_role'],re.I)
    return {k:v for k,v in topic_requirements(inputs['jd_text']).items() if v} if eligible else {}

def topic_requirements(jd):
    outline=build_jd_outline(jd)
    return {key:[r['requirement_id'] for r in outline if r['category'] not in ('context','bonus')
                 and re.search(pattern,r['jd_quote'],re.I)] for key,pattern in PATTERNS.items()}

def package_for_personal(base,inputs):
    p=deepcopy(base);case=p['case'];mapping=curriculum_requirements(inputs)
    case['candidate']={'candidate_id':'PERSON_'+hashlib.sha256(inputs['resume_text'].encode()).hexdigest()[:16],
        'display_name':'我的资料（用户自述）','resume_text':inputs['resume_text'],
        'notice':'用户主动提供的原始资料；尚未独立核实，不能当作能力证明。'}
    case['position']={'position_id':'POSITION_'+hashlib.sha256(inputs['jd_text'].encode()).hexdigest()[:16],
        'title':inputs['target_role'],'source_kind':'user_input','jd_text':inputs['jd_text']}
    case['title']='个人求职准备会话';case.pop('resume_edit_contract',None)
    case['topics']=[{**t,'requirement_ids':mapping[t['topic_id']],
        'notice':'课程范围绑定本次JD原文；是否学习须依据本会话A的实际证据结果。'} for t in case['topics'] if t['topic_id'] in mapping]
    case['learning_tasks']=[t for t in case['learning_tasks'] if set(t['topic_ids'])<=mapping.keys()]
    if len(case['learning_tasks'])<len(base['case']['learning_tasks']):
        days=[1,2,3,4,5,6,8,9,10,11]
        for index,task in enumerate(case['learning_tasks']):task['day']=days[index]
    used={t['day'] for t in case['learning_tasks']};old={t['day']:t for t in case['non_learning_days']}
    case['non_learning_days']=[deepcopy(old.get(day,{'day':day,'kind':'flex_or_review','task_count':0})) for day in range(1,15) if day not in used]
    case['deferred_scope']={'title':'尚未覆盖或暂缓的要求','reason':'课程仅覆盖本次JD明确出现且已有学习卡的部分；其他要求不计为掌握。',
        'revisit_when':'补充相关材料或扩展已核对课程后再规划。','counts_as_mastered':False}
    sql=next((r for r in build_jd_outline(inputs['jd_text']) if r['requirement_id'] in mapping.get('sql',[])),None)
    if sql:p['card']['basis']['jd_quote']=sql['jd_quote']
    p['personal_input']={'contract_version':VERSION,'topic_requirements':mapping,'curriculum_case_id':base['case']['case_id'],
        'core_scope':'job-neutral-a-d-v1','curriculum_available':bool(case['learning_tasks']),
        'notice':'A岗位诊断与D简历优化使用本次原文，不以岗位名称或课程覆盖为前提；学习卡仅在已有资料范围内提供，未覆盖不影响A→D。'}
    return p

def validate_snapshot(package,inputs):
    marker=package.get('personal_input')
    if not marker:return
    expected=curriculum_requirements(inputs) if marker.get('core_scope')=='job-neutral-a-d-v1' else {k:v for k,v in topic_requirements(inputs['jd_text']).items() if v}
    expect(marker['contract_version']==VERSION and marker['topic_requirements']==expected
        and package['case']['candidate']['resume_text']==inputs['resume_text']
        and package['case']['position']['jd_text']==inputs['jd_text'] and package['case']['position']['title']==inputs['target_role'],
        '个人资料与原始输入快照不一致；已停止读取，不会回退到演示资料。')

def local_a_output(inputs,*,quote_policy=None):
    rows=[]
    for item in build_jd_outline(inputs['jd_text']):
        context=item['category']=='context'
        rows.append({'requirement_id':item['requirement_id'],'label':item['jd_quote'][:100],
            'evidence_status':'not_applicable' if context else 'not_provided','resume_quotes':[],
            'rationale':'岗位背景不作学习差距。' if context else '仅本地请求替身，未分析能力；保留待核对状态。',
            'follow_up':'' if context else '请补充本人做过的具体例子或验证材料；当前不判断是否掌握。',
            'priority':'none' if context else 'P2' if item['category']=='bonus' else 'P1','action':'none' if context else 'verify'})
    text=inputs['target_role']+'\n'+inputs['jd_text'];level,quote=('unknown','')
    for token,name in [('实习','internship'),('应届','junior'),('初级','junior')]:
        if token in text:level,quote=name,token;break
    if quote_policy=='a-evidence-scope-v3':
        from a_source_selection import job_level_policy
        policy=job_level_policy(inputs);level=policy['allowed_levels'][0]
        quote=next((r['quote'] for r in policy['options'] if r['level']==level),'')
    value={'diagnosis_version':'evidence-a-v1','analysis_mode':'targeted','match_score':0,
        'score_reason':'本地替身占位值0，不是匹配评分、能力结论或真实模型分析。',
        'evidence_assessment':{'job_level':level,'job_level_quote':quote,'confidence':'low','requirements':rows}}
    validate_evidence_audit(value,inputs,quote_policy=quote_policy);return value

def active_templates(package,bindings):
    active={t['topic_key'] for t in bindings['topics']}
    return [t for t in package['case']['learning_tasks'] if set(t['topic_ids'])<=active]

def personal_cards(package,root):
    from competition_showcase import load_showcase_package
    from workbench_learning_cards import load_follow_along_cards
    base=load_showcase_package(root);bank=load_follow_along_cards(base,root)
    wanted={t['task_template_id'] for t in package['case']['learning_tasks']};outline={r['requirement_id']:r for r in build_jd_outline(package['case']['position']['jd_text'])}
    result={}
    for key,card in bank.items():
        if key not in wanted:continue
        card=deepcopy(card);topic=card['topic_ids'][0];rid=package['personal_input']['topic_requirements'][topic][0]
        card['basis']['jd_quote']=outline[rid]['jd_quote'];card['basis']['reason']='本次JD包含该要求；以下是复用的通用课程示例，不是个人实践证明。'
        result[key]=card
    return result


def personal_interview_bank(bank,package):
    bank=deepcopy(bank);mapping=package['personal_input']['topic_requirements']
    requirements=[r for r in build_jd_outline(package['case']['position']['jd_text']) if r['category']!='context']
    all_ids=[r['requirement_id'] for r in requirements];questions=[]
    for q in bank['questions']:
        keys=[k for k in q['topic_keys'] if k in mapping]
        if q['key'] not in ('project','communication') and not keys:continue
        q['topic_keys']=keys;q['requirement_ids']=list(dict.fromkeys(r for k in keys for r in mapping[k])) or all_ids
        if q['key']=='project':q['prompt']='请围绕你本次提交的资料说明一项实际经历：目标、个人贡献、结果核对方法与尚未验证的边界。没有做过的内容可以直接说明。'
        questions.append(q)
    for q in bank['followups'].values():
        q['topic_keys']=[k for k in q['topic_keys'] if k in mapping]
        q['requirement_ids']=list(dict.fromkeys(r for k in q['topic_keys'] for r in mapping[k])) or all_ids
    covered={r for ids in mapping.values() for r in ids};other=[r for r in requirements if r['requirement_id'] not in covered]
    if other:
        q=deepcopy(bank['questions'][0]);q.update(key='other_requirements',title='岗位其他要求与边界',topic_keys=[],
            requirement_ids=[r['requirement_id'] for r in other],prompt='本次JD还有这些要求：'+ '；'.join(r['jd_quote'] for r in other)+'。请说明已有依据和仍待验证的部分；加分项不作为必须具备的门槛。')
        questions.append(q)
    for q in questions+list(bank['followups'].values()):
        q['requirement_ids']=q['requirement_ids'][:6]
    bank['requirement_contract']='focused-jd-v1'
    bank['all_requirement_ids']=all_ids
    bank['questions']=questions
    return bank
