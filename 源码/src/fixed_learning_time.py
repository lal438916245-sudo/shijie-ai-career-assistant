"""Program-owned 60-minute task budgets for newly frozen workbench requests."""
from copy import deepcopy
import json

VERSION='program-60-v1'
BUDGET={'learning_minutes':20,'core_minutes':25,'review_minutes':5,'optional_minutes':10,
        'assessment_minutes':10,'ending_policy':'choose_one'}
def fixed_budget():return deepcopy(BUDGET)
def policy():return {'version':VERSION,'source':'program','daily_minutes':60,'ending':'选做练习或日考核择一，不叠加'}
def apply_to_plan(plan):
    plan['time_policy']=policy();plan['daily_minutes']=60
    for t in plan['tasks']:t['budget']=fixed_budget()

def prepare_request(request):
    from abf_contracts import ContentPlan
    req=deepcopy(request);stage=req['stage'];ctx=req['context']
    if stage not in ('b_plan','f_review'):return req
    if stage=='f_review' and ctx['plan'].get('time_policy')!=policy():return req
    req['learning_time_policy']=VERSION
    data=json.loads(req['payload']['messages'][1]['content'])
    if stage=='b_plan':
        data['output_schema']=ContentPlan.model_json_schema()
        data['task']=f'只返回overall_goal和指定{len(ctx["task_catalog"])}个task_template_id的学习内容字段；不返回budget或学习用时、学习时间范围。示例中的事件时间与窗口时长可正常说明。14天、日期、专题、gap和任务身份由服务端绑定。程序固定每日60分钟：阅读20、必做25、复盘5、收尾10（选做与日考核择一）；请让学习目标、起步条件和交付物适合这个固定范围，过大的目标缩小为可核对的小样本。不虚构资源链接。修订依据previous_tasks和已保存review，保留正确内容。'
        for t in data['untrusted_context'].get('previous_tasks',[]):t.pop('budget',None)
        prefs=data['untrusted_context'].get('preferences')
        if prefs is not None:prefs['daily_minutes']=60
    else:
        schema=data['output_schema'];issue=schema['$defs']['Issue']['properties']
        issue['field']['enum']=[v for v in issue['field']['enum'] if v!='budget']
        issue['replacement']={'type':'string','minLength':1,'maxLength':500}
        schema['$defs'].pop('Budget',None)
        data['task']+=' 本计划时间由程序固定60分钟，不得建议修改budget或分钟数。审查任务内容是否过多、起步是否清楚、交付物是否可核对；过大时修改preparation或expected_outcome来缩小任务，不扩大时间。'
    data['untrusted_context']['program_time_policy']={**policy(),'budget':fixed_budget()}
    req['payload']['messages'][1]['content']=json.dumps(data,ensure_ascii=False,separators=(',',':'))
    return req
