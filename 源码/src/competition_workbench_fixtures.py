"""Fixed A/B/F boundaries for the one frozen competition case. No SDK/Key."""
from copy import deepcopy
import json
import uuid

from competition_case import CaseContractError
from diagnosis_evidence import build_jd_outline, validate_evidence_audit

TOPIC_JD = {'sql':['JD-02'], 'model':['JD-03'], 'stream':['JD-04'], 'engineering':['JD-05','JD-07']}


def fixed_hunter(inputs):
    from agent_a_hunter import HunterAgent, HUNTER_SYSTEM_PROMPT
    outline = build_jd_outline(inputs['jd_text'])
    rows = []
    labels = {'JD-01':'岗位背景','JD-02':'连接与金额口径验证','JD-03':'事实粒度与数据质量',
              'JD-04':'事件时间与恢复边界','JD-05':'工程测试与日志','JD-06':'Python与基础SQL',
              'JD-07':'说明验证依据与边界','JD-08':'可复现流处理或自动测试','JD-09':'面试安排'}
    for item in outline:
        rid = item['requirement_id']
        if rid not in labels:
            raise CaseContractError('unexpected_case_jd_outline')
        context = item['category'] == 'context'
        row = {'requirement_id':rid,'label':labels[rid],
            'evidence_status':'not_applicable' if context else 'not_provided','resume_quotes':[],
            'rationale':'岗位背景或面试安排，不作为学习差距。' if context else '未提供足够验证材料，先核对，不断言不会。',
            'follow_up':'' if context else '用订单小样本补充可核对的结果和说明。',
            'priority':'none' if context else 'P2' if item['category']=='bonus' else 'P1',
            'action':'none' if context else 'verify'}
        if rid == 'JD-02':
            row.update(evidence_status='partial',resume_quotes=['做过基础SQL聚合和离线订单报表课程练习'],
                rationale='基础SQL有自述，连接后的金额口径尚需小样本验证；不是确认不会。')
        if rid == 'JD-06':
            row.update(evidence_status='supported',resume_quotes=['用Python读取CSV、清理空值并按订单ID去重，做过基础SQL聚合和离线订单报表课程练习'],
                rationale='有有限课程实践自述；未经独立考核，不等于精通。',follow_up='',priority='P3',action='maintain')
        if rid == 'JD-07':
            row.update(evidence_status='partial',resume_quotes=['能说明样本输入和汇总结果'],
                rationale='能说明已有样本；完整假设、核对与未验证边界仍应通过交付说明核对。')
        rows.append(row)
    response = {'diagnosis_version':'evidence-a-v1','analysis_mode':'targeted','match_score':55,
        'score_reason':'固定案例的证据匹配参考55分，不评价本次用户输入，不是实测能力或成长分。',
        'evidence_assessment':{'job_level':'junior','job_level_quote':'初级','confidence':'medium','requirements':rows}}
    validate_evidence_audit(response,inputs)
    agent = HunterAgent.__new__(HunterAgent)
    agent.evidence_contract_required = True
    agent.system_prompt = HUNTER_SYSTEM_PROMPT
    agent.model_name = 'competition-fixed-A'
    agent.think = lambda *_a,**_kw: json.dumps(response,ensure_ascii=False)
    return agent


def bound_id(session_id, kind, template_id):
    return kind.upper()+'_'+uuid.uuid5(uuid.NAMESPACE_URL,session_id+':'+kind+':'+template_id).hex[:24]


def make_bindings(meta, package, diagnosis):
    by_requirement = {g['requirement_id']:g for g in diagnosis['gaps'] if g.get('source')=='evidence_assessment'}
    topics = []
    for topic in package['case']['topics']:
        refs = topic.get('requirement_ids',TOPIC_JD[topic['topic_id']])
        if package.get('personal_input'):
            refs=[r for r in refs if r in by_requirement]
            if not refs:continue
        if any(r not in by_requirement for r in refs):
            raise CaseContractError('case_diagnosis_binding_missing')
        topics.append({'topic_id':bound_id(meta['session_id'],'topic',topic['topic_id']),
            'topic_key':topic['topic_id'],'title':topic['title'],
            'primary_gap_id':by_requirement[refs[0]]['gap_id'],
            'source_gap_ids':[by_requirement[r]['gap_id'] for r in refs],
            'requirement_ids':refs})
    used = {g for t in topics for g in t['source_gap_ids']}
    disposition = [{'gap_id':g['gap_id'],'skill':g['skill'],'reason':('当前没有覆盖这项要求的已核对课程；不影响岗位诊断和简历优化，不代表已掌握。' if package.get('personal_input') else '加分项不作为本轮硬门槛；本轮先验证基础，再按成果补充可复现材料。'),
        'revisit_when':'完成入门任务且能提供独立复现记录后再核对。'} for g in diagnosis['gaps'] if g['gap_id'] not in used]
    return {'topics':topics,'deferred_gaps':disposition}


def fixed_plan(meta, package, diagnosis, bindings):
    case = package['case'];catalog = {r['resource_id']:r for r in package['catalog']['resources']}
    topic_by_key = {t['topic_key']:t for t in bindings['topics']}
    tasks = []
    from personal_workbench_input import active_templates
    templates=active_templates(package,bindings) if package.get('personal_input') else case['learning_tasks']
    for template in templates:
        keys = template['topic_ids']
        task = {'task_id':bound_id(meta['session_id'],'task',template['task_template_id']),
            'task_template_id':template['task_template_id'],'day':template['day'],
            'topic_keys':keys,'topic_ids':[topic_by_key[k]['topic_id'] for k in keys],
            'source_gap_ids':list(dict.fromkeys(g for k in keys for g in topic_by_key[k]['source_gap_ids'])),
            'title':template['title'],'expected_outcome':'写出小样本输入、预期结果、判断依据与仍未验证的边界。',
            'preparation':'先复述相关概念，再用纸面或已有环境做小验证；不要求部署生产系统。',
            'gap_interpretation':'先验证材料不足的地方，不把未提供证据当作不会。',
            'resource_selection':{'primary_id':template['resource_ids'][0],
                'backup_id':template['resource_ids'][1] if len(template['resource_ids'])>1 else None},
            'resource_goals':[catalog[r]['learning_goal'] for r in template['resource_ids']],
            'budget':{'learning_minutes':20,'core_minutes':20,'review_minutes':10,
                      'optional_minutes':10,'assessment_minutes':10,'ending_policy':'choose_one'},
            'guide_kind':'complete_card' if case['version']==2 or template['task_template_id']=='CP-T01' else 'basic_outline'}
        if template['task_template_id']=='CP-T01' and not package.get('personal_input'):
            task.update(expected_outcome=package['card']['exercise']['deliverable'],
                preparation='先安装PostgreSQL数据库和Flink集群，再开始订单连接纸面练习。',
                gap_interpretation='已确认不会多表连接，必须先补齐。',
                budget={'learning_minutes':35,'core_minutes':25,'review_minutes':5,
                        'optional_minutes':10,'assessment_minutes':10,'ending_policy':'stack'})
        tasks.append(task)
    return {'plan_contract':'competition-workbench-plan-v1','plan_id':meta['plan_id'],
        'report_id':meta['report_id'],'input_digest':meta['input_digest'],'overall_goal':('围绕本次JD的'+ '、'.join(t['title'] for t in case['topics'] if t['topic_id'] in topic_by_key)+'安排小样本任务；未覆盖要求暂缓。' if package.get('personal_input') else '先让订单数据结果可信，再逐步验证实时、建模与工程边界。'),
        'available_days':14,'daily_minutes':60,'tasks':tasks,'non_learning_days':deepcopy(case['non_learning_days']),
        'deferred_scope':deepcopy(case['deferred_scope']),'deferred_gaps':deepcopy(bindings['deferred_gaps']),
        'fixture_notice':'B初稿是人工设定的待审草案，刻意保留3个问题以演示F审查；不是实际模型生成质量。'}


def budget_total(budget):
    base=sum(budget[k] for k in ('learning_minutes','core_minutes','review_minutes'))
    ending=max(budget['optional_minutes'],budget['assessment_minutes']) if budget['ending_policy']=='choose_one' else budget['optional_minutes']+budget['assessment_minutes']
    return base+ending


def plan_for_critic(plan):
    tasks=[]
    for t in plan['tasks']:
        tasks.append({'content':t['title']+'\n'+t['preparation']+'\n'+t['gap_interpretation']+
            f"\n任务预算合计{budget_total(t['budget'])}分钟；收尾策略{t['budget']['ending_policy']}。",
            'expected_outcome':t['expected_outcome']})
    return {'overall_goal':plan['overall_goal'],'phases':[{'phase_name':'同一会话的14天安排',
        'phase_goal':'先验证再学习，不承诺生产胜任','tasks':tasks}]}


def review_findings(plan, package, bindings):
    """Necessary, inspectable local checks. No claim of semantic model review."""
    first=next(t for t in plan['tasks'] if t['task_template_id']=='CP-T01')
    issues=[]
    def add(code, title, target, evidence, suggestion, patch):
        issues.append({'issue_id':code,'task_id':first['task_id'],'task_template_id':'CP-T01','title':title,
            'target':target,'evidence_kind':'plan_internal','evidence_ref':evidence,'suggestion':suggestion,
            'patch':patch,'adoptable':True})
    if budget_total(first['budget'])>plan['daily_minutes'] or first['budget']['ending_policy']!='choose_one':
        add('F-TIME','阅读与考核叠加后超过每日预算',f"任务预算合计{budget_total(first['budget'])}分钟",
            f"本日合计{budget_total(first['budget'])}分钟，每日上限{plan['daily_minutes']}分钟。",
            '学习30、必做15、复盘5；最后10分钟选做或考核择一。',
            {'budget':{'learning_minutes':30,'core_minutes':15,'review_minutes':5,'optional_minutes':10,'assessment_minutes':10,'ending_policy':'choose_one'}})
    if first['preparation']!=package['card']['prerequisites']:
        add('F-ENTRY','零基础纸面练习不应先部署生产环境',first['preparation'],
            '首卡准备条件：会整数加法，不需要数据库或编程环境。',
            '先纸笔配对，安装数据库与Flink不作为当天前置。',{'preparation':package['card']['prerequisites']})
    if first['gap_interpretation']!='先用小样本验证连接与口径，不把未提供证据或部分支持认定为不会。':
        add('F-EVIDENCE','计划把待验证项写成已确认不会',first['gap_interpretation'],
            '本会话A对连接能力仅有部分支持，后续动作是先验证。',
            '先用小样本验证，保留已有基础与未知边界。',
            {'gap_interpretation':'先用小样本验证连接与口径，不把未提供证据或部分支持认定为不会。'})
    return issues


def fixed_review(plan, package, bindings, meta):
    from agent_f_critic import CriticAgent
    findings=review_findings(plan,package,bindings)
    raw={'summary':'发现3项必须修订的问题；不采纳不会改变原计划。' if findings else '当前版本通过本地固定规则复核；可以确认后开始学习。',
        'critiques':[{'target':i['target'],'problem':i['title'],'evidence_kind':i['evidence_kind'],
            'evidence_ref':i['evidence_ref'],'suggestion':i['suggestion']} for i in findings]}
    critic=CriticAgent.__new__(CriticAgent)
    critic.model_name='competition-fixed-F';critic.trace_id=meta['trace_id'];critic.db=None
    critic.think=lambda *_a,**_kw:json.dumps(raw,ensure_ascii=False)
    result=critic.critique(plan_for_critic(plan),resume_text=meta['inputs']['resume_text'],
        jd_text=meta['inputs']['jd_text'],gap_report=json.dumps(bindings,ensure_ascii=False))
    if result.get('_degraded') or result.get('_rejected') or len(result.get('_valid',[]))!=len(findings):
        raise CaseContractError('fixed_F_grounding_failed')
    actual=[c.to_dict() for c in result['_valid']]
    expected=[{'target':i['target'],'problem':i['title'],'evidence_kind':i['evidence_kind'],
               'evidence':i['evidence_ref'],'suggestion':i['suggestion']} for i in findings]
    if actual!=expected:
        raise CaseContractError('fixed_F_response_mismatch')
    return {'review_contract':'competition-F-review-v1','verdict':'needs_revision' if findings else 'pass',
        'summary':result['summary'],'issues':findings,'checks':[
            '每日预算含阅读，选做与日考核互斥','先修与零基础起步','任务与本会话A差距来源一致',
            '资料ID有效且对应任务','必做交付可检查','暂缓项不计已掌握'],
        'model_name':'competition-fixed-F','notice':'实际F方法使用本地固定响应并做规则与引用检查；不是实时模型理解或全方位教学质量认证。'}
