"""The sole current competition case. Fictional inputs and fixed outputs, no network."""
from copy import deepcopy
from pathlib import Path
import hashlib,json
from competition_case import ROOT,require,validate_package,CaseContractError
from diagnosis_evidence import build_jd_outline,validate_evidence_audit

CASE_ID='career-pilot-showcase-20261107'
PROFILE='final-20261107'
DIRECTORY='showcase_sessions_20261107'
REPLAY_TOKEN=hashlib.sha256(b'CareerPilot:public-fictional-showcase:20261107').hexdigest()
REPLAY_START='2026-10-20'

def load_showcase_package(root=ROOT):
    root=Path(root)
    names=('examples/competition_case/v2/case.json','examples/competition_case/v2/cards/sql-join-grain.json',
           'examples/competition_case/v2/cards/follow-along-v1.json','knowledge_base/curated_resources/v1/catalog.json')
    try:
        manifest=json.loads((root/'examples/competition_case/v2/manifest.json').read_text(encoding='utf-8'))
        require(manifest['case_id']==CASE_ID and manifest['version']==2 and set(manifest['files'])==set(names),'showcase_manifest')
        documents=[]
        for name in names:
            raw=(root/name).read_bytes();require(hashlib.sha256(raw).hexdigest()==manifest['files'][name],'showcase_digest')
            documents.append(json.loads(raw))
        package={'case':documents[0],'card':documents[1],'catalog':documents[3]}
        validate_package(package)
        from workbench_learning_cards import load_follow_along_cards
        load_follow_along_cards(package,root)
        contract=package['case']['resume_edit_contract'];original=package['case']['candidate']['resume_text']
        for key in ('project_quote','boundary_quote','materials_quote','skills_quote'):
            require(original.count(contract[key])==1,'showcase_resume_quote')
        return package
    except (KeyError,OSError,ValueError,TypeError) as exc:
        if isinstance(exc,CaseContractError):raise
        raise CaseContractError('showcase_package_unavailable') from None

def fixed_showcase_hunter(inputs):
    from agent_a_hunter import HunterAgent,HUNTER_SYSTEM_PROMPT
    case=load_showcase_package()['case']
    require(inputs['resume_text']==case['candidate']['resume_text'] and inputs['jd_text']==case['position']['jd_text'],'showcase_fixed_inputs')
    outline=build_jd_outline(inputs['jd_text']);require(len(outline)==13,'showcase_jd_outline')
    definitions={
      'JD-02':('连接与金额口径','partial',['做过基础SQL聚合和离线订单报表课程练习'],'基础聚合有课程自述，复杂连接的金额口径尚需样本验证。'),
      'JD-03':('事实粒度与数据质量','partial',['尚需补充订单与明细粒度、唯一键及空值检查材料'],'知道业务字段，仍需核对粒度与质量检查；材料不足不是确认不会。'),
      'JD-04':('事件时间与恢复边界','not_provided',[],'未提供流处理验证材料，先学习基本概念并做小样本，不要求生产集群。'),
      'JD-05':('工程测试与日志','partial',['尚未形成系统化的测试、日志与故障复现清单'],'已有基础排错，系统化验证与复现材料仍需补充。'),
      'JD-06':('教育与课程基础','supported',['某大学｜计算机科学与技术｜本科','相关课程：数据库原理、数据结构、操作系统、计算机网络、Python程序设计。'],'教育与课程是候选人自述，不代表已独立验证全部能力。'),
      'JD-07':('Python与基础SQL','supported',['用Python读取CSV、清理空值并按订单ID去重，做过基础SQL聚合和离线订单报表课程练习'],'有课程小样本经历，保留这一入门优势，未经独立实测。'),
      'JD-08':('查询方法与学习基础','supported',['愿意从可核对的小任务做起，能承认未知并补充验证。','相关课程：数据库原理、数据结构、操作系统、计算机网络、Python程序设计。'],'课程与学习方式有自述，保持并在任务中验证，不推断熟练程度。'),
      'JD-09':('沟通与方案边界','partial',['与同学核对字段含义，整理样例数据和课程说明'],'有协作自述，方案假设、核对记录和边界说明仍需具体交付支持。'),
      'JD-10':('AI辅助后的验证责任','partial',['会对照给定样例核对结果；尚未整理假设、反例与验证责任的完整记录'],'能核对样例，但需补充反例与验证责任，不将AI输出直接视为正确。'),
      'JD-11':('课程作品加分材料','supported',['离线订单报表课程练习｜个人课程项目'],'有课程项目自述；不把加分项当硬门槛，也不证明真实性能收益。'),
      'JD-12':('可复现流处理或自动测试','not_provided',[],'加分方向尚缺可复现材料，先完成基础任务，额外工程实践后再核对。'),
    }
    rows=[]
    for item in outline:
        rid=item['requirement_id'];context=item['category']=='context'
        if context:row={'requirement_id':rid,'label':'岗位与面试背景','evidence_status':'not_applicable','resume_quotes':[],
            'rationale':'岗位背景与面试安排，不产生技能差距。','follow_up':'','priority':'none','action':'none'}
        else:
            label,status,quotes,reason=definitions[rid];supported=status=='supported'
            row={'requirement_id':rid,'label':label,'evidence_status':status,'resume_quotes':quotes,'rationale':reason,
              'follow_up':'' if supported else '按对应学习任务整理小样本、预期结果、核对过程和未验证边界。',
              'priority':'P3' if supported else 'P2' if item['category']=='bonus' else 'P1','action':'maintain' if supported else 'verify'}
        rows.append(row)
    response={'diagnosis_version':'evidence-a-v1','analysis_mode':'targeted','match_score':55,
      'score_reason':'固定案例证据匹配参考55分；依据简历引用与JD分层，不按简历篇幅加分，不是个人能力或成长分。',
      'evidence_assessment':{'job_level':'internship','job_level_quote':'应届实习','confidence':'medium','requirements':rows}}
    validate_evidence_audit(response,inputs)
    agent=HunterAgent.__new__(HunterAgent);agent.evidence_contract_required=True;agent.system_prompt=HUNTER_SYSTEM_PROMPT
    agent.model_name='competition-fixed-A-final';agent.think=lambda *_a,**_kw:json.dumps(deepcopy(response),ensure_ascii=False)
    return agent

def replay_entry(service):
    # Public synthetic sample identity only; never user credentials or a private session token.
    if not service._identity(REPLAY_TOKEN)[2].is_file():return None
    marker=service._session_directory(REPLAY_TOKEN)/'replay-sealed.json'
    summary=json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {}
    return {'complete_summary':summary,'case_id':CASE_ID,'token':REPLAY_TOKEN,'label':'完整演示 · 林知远的14天成长','start_date':REPLAY_START,
      'saved':True,'pending':None,'createdAt':'2026-11-07T00:00:00Z'}
