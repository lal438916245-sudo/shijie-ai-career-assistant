"""Original fixed job-wide interview examples, never a provider or text classifier."""
from copy import deepcopy

BANK_VERSION='competition-job-interview-v1'
PERSONA={'name':'岗位面试官','style':'专业、平和；追问依据、个人贡献与未验证边界，不做人身评价。'}

def item(key,title,topics,requirements,prompt,weak,weak_quote,issue,suggestion,clear,clear_quote,outline):
    return {'key':key,'title':title,'topic_keys':topics,'requirement_ids':requirements,'prompt':prompt,
        'examples':{'needs_detail':weak,'clear':clear},'feedback':{
          'needs_detail':{'quote':weak_quote,'observation':'这段内置示例没有把可核对的材料说完整。',
             'issue':issue,'suggestion':suggestion},
          'clear':{'quote':clear_quote,'observation':'这段内置示例给出了具体依据，并说明实践边界。',
             'issue':None,'suggestion':'继续用真实小样本或可复现材料支持这段表述，不把课程练习改写成生产经历。'}},
        'reference_outline':outline}

def bank():
    questions=[
      item('project','项目经历与岗位理解',[],['JD-06','JD-07'],
        '我们面试的是初级数据开发岗位。请用一个你实际做过的订单报表或数据处理练习，说明目标、你个人做了什么、如何核对结果，以及哪些环节尚未验证。',
        '我做过一些订单报表，大概是清洗一下再汇总，效果还不错。','效果还不错',
        '项目结果缺少核对依据与个人贡献（示例）','按“输入—个人操作—输出—核对—边界”说明，至少给一组可以手算的样本。',
        '这是课程练习。我用Python读取CSV，清理空值并按订单ID去重，再用基础SQL汇总；用固定小样本核对订单数与金额。我个人完成清洗和核对，没有生产上线或真实性能提升的证据。','没有生产上线或真实性能提升的证据',
        '说明课程/练习背景与个人操作，给出输入和预期结果，区分已验证范围与尚无证据的生产经验。'),
      item('data','SQL、粒度与结果口径',['sql','model'],['JD-02','JD-03'],
        '订单表一行一订单，明细表一行一商品。关联后订单金额变大了，你会怎样确认目标统计口径、定位原因并验证修正？再说明一个数据质量检查。',
        '我会把重复的金额去掉，SUM(DISTINCT 金额)应该就可以了。','SUM(DISTINCT 金额)',
        '按金额去重可能合并不同订单（示例）','构造两笔金额相同、ID不同的订单；先确认一行代表什么，再按订单ID和目标粒度核对总额。',
        '先确认目标是订单总额还是商品指标。一对多关联会重复携带订单总额；若只要总额直接从订单表统计，需要商品指标时先聚合到订单粒度再关联。我会检查订单ID唯一性，并用金额相同的不同订单验证，不能按金额去重。','不能按金额去重',
        '目标口径→连接基数→订单ID/粒度→修正→小样本对照；数据质量至少核对唯一键、空值或金额守恒。'),
      item('stream','事件时间与故障恢复',['stream'],['JD-04'],
        '支付事件10:00发生、10:04被收到；处理链在检查点之后故障。请说明按事件时间统计时如何处理迟到，以及为什么恢复状态不等于所有外部下游永不重复。',
        '收到就处理，恢复检查点以后应该不会重复，也不用额外检查。','应该不会重复',
        '状态恢复与外部提交边界混在一起（示例）','分别说明事件时间/处理时间、迟到策略、源重放和下游事务或幂等；用故障前后小样本核对结果。',
        '事件时间是10:00，处理时间是10:04。迟到是否接受取决于水位线、窗口和允许迟到配置。检查点只恢复约定边界内的状态，源可能重放，下游还需事务或幂等提交；这些需要用故障注入验证，我尚无生产链路证明。','下游还需事务或幂等提交',
        '分别讨论时间语义、窗口/迟到配置、状态与源位置、外部提交边界；不凭检查点承诺完整生产SLA。'),
      item('engineering','测试、日志与工程验证',['engineering'],['JD-05','JD-08'],
        '你准备交付一份订单金额处理脚本。会选哪些正常/异常样本与断言？偶发失败时用什么日志定位？如果尚未做自动化测试，也请直接说明。可复现自动测试属于加分材料，不要求生产规模经历。',
        '脚本能跑通就差不多了，失败时再看看报错，暂时不用测试。','能跑通就差不多了',
        '跑通与验证可靠性没有区分（示例）','固定正常/重复键/空值等样本，写预期断言；日志记录关联ID、阶段和计数，不记录Key与完整个人资料。',
        '先固定正常样本及重复订单、空值反例，断言订单数和金额；自动测试是我接下来要补的材料。日志记录运行/关联ID、阶段、错误类别与必要计数，不写Key和完整个人信息。课程小样本跑通还不能证明生产可靠性。','不能证明生产可靠性',
        '可重复输入、明确断言、异常边界、关联日志与最小复现；没有自动化实践时承认未知，不夸大加分项。'),
      item('communication','需求对齐、协作与边界说明',['engineering'],['JD-07'],
        '业务同学说“报表数字对不上”，但没有说比较的是哪个口径。你会如何澄清、给出排查顺序并说明结论的边界？若使用AI辅助排查，你会怎样验证它的建议？AI辅助是可选讨论，不新增岗位硬门槛。',
        '我会先按自己的理解改SQL，AI说能用的方案就直接提交。','直接提交',
        '需求口径与验证责任没有对齐（示例）','先确认指标、时间范围、去重键和对照样本，再做最小复现；AI建议也要核对假设、运行结果与反例。',
        '先与业务确认指标定义、时间范围、订单状态和对照样本，再分层核对输入、关联、聚合与输出。说明当前已验证的数据范围及剩余风险。若用AI，只把它作为建议，仍由我验证假设、小样本和异常结果后再提交。','仍由我验证假设',
        '先澄清再排查，给出可共享的依据和边界；AI使用与否都不免除工程验证责任。')]
    followups={
      'project':item('project_followup','项目依据追问',[],['JD-06','JD-07'],
        '请补充一组你能手算的输入与预期结果，以及哪一步由你个人完成；如果还没有核对材料，也可以直接说明。',
        '样本我现在记不清，反正结果能出来。','样本我现在记不清',
        '补充说明仍没有可核对样本（示例）','可以从两笔订单开始，明确原始记录、去重前后行数及目标金额；不必编造项目规模。',
        '例如订单A=60、B=40，另有一条重复A；我个人按订单ID去重，预期两笔订单、总额100，再将脚本输出与手算对照。这里只验证这个课程样本。','预期两笔订单、总额100',
        '用两三条数据说明去重键、预期行数与总额，并点明个人操作和样本边界。'),
      'data':item('data_followup','相同金额反例追问',['sql','model'],['JD-02','JD-03'],
        '若两笔不同订单的金额恰好都是80，按不同金额只加一次会得到多少？正确总额应是多少？这对你的修正方案意味着什么？',
        '金额相同就算一笔，应该是80。','金额相同就算一笔',
        '把相同金额当作同一订单（示例）','按订单ID识别事实，正确总额为160；先消除关联造成的重复，不合并真实不同订单。',
        '按不同金额只加一次是80，但两笔不同订单的正确总额是160。金额不是订单身份，要按订单ID与目标粒度核对，不能用金额DISTINCT修复。','正确总额是160',
        '80与160形成反例，说明订单身份、事实粒度和关联基数，而非金额取值本身。')}
    return {'version':BANK_VERSION,'persona':deepcopy(PERSONA),'questions':questions,'followups':followups}

def classify(example,text):
    for key,value in example['examples'].items():
        if text.strip()==value:return key
    return 'custom_unreviewed'

def build_report(run,turns):
    by_id={t['turn_id']:t for t in turns};questions={t['question_key']:t for t in turns if t['role']=='assistant'}
    templates={q['key']:q for q in run['bank']['questions']}
    templates.update({q['key']:q for q in run['bank']['followups'].values()})
    findings=[]
    for a in (t for t in turns if t['role']=='user'):
        q=by_id[a['question_turn_id']];template=templates[q['question_key']];kind='custom_unreviewed' if q.get('model_application') else classify(template,a['text'])
        if kind=='custom_unreviewed':
            result={'quote':'','observation':'自定义回答已保存；固定替身未进行语义分析。','issue':None,
                'suggestion':'请按参考结构自查结论、依据、个人贡献及未验证边界；待真实面试分析接入后再评价这段回答。'}
        else:result=deepcopy(template['feedback'][kind])
        if result['quote'] and result['quote'] not in a['text']:raise ValueError('interview quote not grounded')
        findings.append({'finding_id':a['turn_id']+':feedback','question_turn_id':q['turn_id'],
            'answer_turn_id':a['turn_id'],'title':template['title'],'analysis_kind':kind,**result,
            'reference_outline':('此轮已采用候选问题，原题参考不适用；可在结束后核对候选复盘与原话。' if q.get('model_application') else template['reference_outline']),'topic_ids':q['topic_ids'],
            'requirement_ids':q['requirement_ids']})
    coverage=[]
    for q in run['bank']['questions']:
        asked=questions.get(q['key']);answered=bool(asked and any(t['role']=='user' and t['question_turn_id']==asked['turn_id'] for t in turns))
        coverage.append({'key':q['key'],'title':q['title'],'planned':q['key'] in run['main_keys'],
            'asked':bool(asked),'answered':answered,'requirement_ids':q['requirement_ids']})
    requirement_coverage={}
    if run['bank'].get('requirement_contract')=='focused-jd-v1':
        all_ids=run['bank']['all_requirement_ids']
        addressed=list(dict.fromkeys(rid for q in turns if q['role']=='assistant' and any(a['role']=='user' and a['question_turn_id']==q['turn_id'] for a in turns) for rid in q['requirement_ids']))
        requirement_coverage={'requirement_coverage':{'all_requirement_ids':all_ids,'addressed_ids':addressed,'uncovered_ids':[rid for rid in all_ids if rid not in addressed],'notice':'每轮聚焦至多6项相关要求；未覆盖不等于不会，不据此给出整岗认证。'}}
    return {**requirement_coverage,'contract_version':BANK_VERSION,'interview_id':run['interview_id'],'scope':run['scope'],
        'position_title':run['context']['position']['title'],'status':run['status'],'ended_at':run['ended_at'],
        'mode':run['mode'],'answered_count':len(findings),'answered_main':sum(c['answered'] for c in coverage),
        'planned_main':len(run['main_keys']),'followup_count':sum(t['role']=='assistant' and t['is_followup'] for t in turns),
        'findings':findings,'coverage':coverage,
        'issue_count':sum(f['analysis_kind']=='needs_detail' for f in findings),
        'clear_sample_count':sum(f['analysis_kind']=='clear' for f in findings),
        'unreviewed_count':sum(f['analysis_kind']=='custom_unreviewed' for f in findings),
        'context_selection':run['context_selection'],
        'notice':'本报告只对完全匹配内置示例的回答展示预设分析；自定义回答不被判对错。不是模型评价、面试成绩或岗位胜任证明，不更新能力状态。'}
