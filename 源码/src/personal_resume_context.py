"""Bounded, frozen personal evidence sent to D. References do not verify facts."""
from copy import deepcopy
import re

VERSION='personal-evidence-v4'

def options(sid,text):
    rows=[]
    for m in re.finditer(r'[^\r\n]+',text):
        q=m.group()
        if 12<=len(q)<=240 and text.count(q)==1:
            rows.append({'source_id':sid,'start':m.start(),'end':m.end(),'quote':q})
    return rows[:6]

def personal_evidence_context(context,snapshot):
    c=deepcopy(context);sources=c['sources'];original=snapshot['resume_text']
    sources['resume_original']['reference_options']=options('resume_original',original)
    def add(source,text,kind,usage='personal_learning_context_only',simulated=True):
        sources[source]={'text':text,'kind':kind,'usage':usage,'simulated':simulated,
            'reference_options':options(source,text)}
    selected=[]
    progress={}
    for s in snapshot['sources']:
        if s['kind']=='learning_progress':progress[s['view']['task_id']]=s
    for s in list(progress.values())[:3]:
        v=s['view'];add(s['record_id'],f"学习任务 {v['task_id']}：用户记录状态为{v['status']}，日期{v['start_date']}至{v['end_date']}。进度勾选不是能力验证。",'user_progress')
        selected.append(s['record_id'])
    for kind in ('assessment','retest'):
        for s in [s for s in snapshot['sources'] if s['kind']==kind][-2:]:
            v=s['view'];g=v['grade'];real=g.get('simulated') is False
            text='题目：'+v['question'][:650]+'\n原始作答：'+v['answer'][:1200]+'\n评分反馈：'+g.get('feedback','')[:450]+'\n边界：'+('真实模型评价本次作答，非独立能力证明。' if real else '本地替身评分，不证明实际能力。')
            add(s['record_id'],text,'user_answer_with_review',simulated=not real);selected.append(s['record_id'])
    for s in [s for s in snapshot['sources'] if s['kind']=='interview'][-1:]:
        lines=[]
        for f in s['view']['findings'][:4]:
            lines.append('面试原话：'+f['answer_text'][:450]+'\n表达观察：'+f['observation'][:180]+'\n建议：'+f['suggestion'][:180])
        add(s['record_id'],'\n'.join(lines)+'\n边界：面试自述与表达反馈不证明项目事实。','interview_expression_context')
        selected.append(s['record_id'])
    c.update(output_contract=VERSION,personal_evidence={'version':VERSION,'record_ids':selected,
        'snapshot_revision':snapshot['revision'],'missing_record_kinds':[k for k in ('learning_progress','assessment','retest','interview') if not any(s['kind']==k for s in snapshot['sources'])],
        'excluded_demo_artifacts':sum(s['kind']=='learning_artifact' for s in snapshot['sources']),
        'notice':'仅本会话冻结的进度、答卷和已结束面试；内置参考样例未作为个人成果发送。引用用于解释改写或补证，不证明新增技能或生产事实。'},
        revision_policy='原简历定位已有经历；supporting_refs可逐字引用本次personal_learning_context_only记录。仅改进已有事实的表达或提出待核对的课程练习表述；不可把分数、勾选、参考答案、面试自述升级为新技能、主导、生产上线或绩效。没有依据的学习成果只能列入missing_evidence。')
    return c
