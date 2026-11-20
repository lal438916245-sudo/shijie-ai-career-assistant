"""Fixed coursework artifacts and a task-by-task handoff to resume drafting."""
from copy import deepcopy
import json

from competition_workbench_assessment import digest, expect
from competition_workbench_fixtures import bound_id
from workbench_learning_cards import follow_along_card

ARTIFACT_OPERATIONS = {'learning_artifact': {'plan_version', 'task_id'}}
ARTIFACT_VERSION = 'coursework-artifact-demo-v1'
CLAIMS = {
    'CP-T01': '按订单ID核对连接行数和金额，使用等额订单反例检查错误的金额去重。',
    'CP-T02': '用延迟到达的消息样本区分事件时间与处理时间，说明迟到处理的边界。',
    'CP-T03': '分别定义订单与明细的事实粒度，按业务键核对关联前后的指标。',
    'CP-T04': '先核对查询结果，再对照执行计划；记录测试条件和性能结论的限制。',
    'CP-T05': '用检查点恢复样例追踪状态、输入位置与输出，说明重复处理风险。',
    'CP-T06': '构造正常、重复和缺失数据样本，为金额口径写出预期结果与核对项。',
    'CP-T07': '用窗口和水位线样例核对延迟消息的归属，记录接纳与补算条件。',
    'CP-T08': '为窗口排序加入确定的并列处理规则，并核对小样本的排名结果。',
    'CP-T09': '检查业务键唯一性和空值，逐笔对照模型变更前后的数量与金额。',
    'CP-T10': '按关联ID串联任务阶段和异常日志，整理小样本复现步骤与日志边界。',
}


def artifact_definition(package, task):
    card = package['card'] if task['task_template_id']=='CP-T01' else follow_along_card(package, task)
    exercise=deepcopy(card['exercise'])
    if 'tables' not in exercise:
        exercise['tables']=[{'title':'练习订单表',**exercise['orders']},
                            {'title':'练习明细表',**exercise['items']}]
    return {
        'version': ARTIFACT_VERSION,
        'task_id': task['task_id'],
        'task_template_id': task['task_template_id'],
        'title': task['title']+' · 课程练习成果',
        'topic_keys': task['topic_keys'],
        'summary': CLAIMS[task['task_template_id']],
        'exercise': exercise,
        'source_kind': 'curated_demo',
        'verification': 'fixed_sample',
        'notice': '内置课程小样本及参考结果，用于演示成果如何进入简历证据链。',
    }


class WorkbenchLearningEvidence:
    def _learning_artifact_rows(self, conn, meta):
        rows=[]
        for record in conn.execute("SELECT * FROM wb_records WHERE kind='learning_artifact' ORDER BY seq"):
            payload=json.loads(record['payload_json'])
            artifact=payload['artifact']
            expect(payload['event']=='learning_artifact' and digest(artifact)==payload['artifact_digest'],
                   '练习成果内容校验失败。')
            plan=self._plan(conn,payload['plan_version'])
            task=next((t for t in plan['plan']['tasks'] if t['task_id']==artifact['task_id']),None)
            expect(task is not None and artifact['task_template_id']==task['task_template_id']
                   and artifact['topic_keys']==task['topic_keys']
                   and artifact['version']==ARTIFACT_VERSION
                   and artifact['summary']==CLAIMS[task['task_template_id']]
                   and artifact['source_kind']=='curated_demo' and artifact['verification']=='fixed_sample',
                   '练习成果与当前会话任务不一致。')
            expect(json.loads(record['parent_ids_json'])==[plan['record_id']], '练习成果的计划来源不完整。')
            rows.append({**dict(record),'artifact':artifact,'plan_version':payload['plan_version']})
        return rows

    def _do_learning_artifact(self, conn, meta, body):
        self._active(meta,body)
        expect(meta['published_version']==body['plan_version'],'请先确认采用学习计划。')
        plan=self._plan(conn,body['plan_version'])
        task=next((t for t in plan['plan']['tasks'] if t['task_id']==body['task_id']),None)
        expect(task is not None,'练习任务不属于本会话计划。')
        artifact=artifact_definition(meta['package'],task)
        rid=bound_id(meta['session_id'],'artifact',body['request_id'])
        self._record(conn,meta,rid,'learning_artifact',artifact['title'],
            {'event':'learning_artifact','plan_version':body['plan_version'],
             'artifact':artifact,'artifact_digest':digest(artifact)},
            [plan['record_id']],source='curated_demo',usage='learning_content_only')
        return {'record_id':rid,'task_id':task['task_id']}


def learning_handoff(snapshot):
    """Derive only from the frozen plan and sources, never from current progress."""
    plan=snapshot.get('learning_plan')
    if not plan:
        return None
    sources=snapshot['sources']
    tasks=[]
    for task in plan['tasks']:
        progress=next((s for s in reversed(sources) if s['kind']=='learning_progress' and s['view'].get('plan_version')==plan['version']
                       and s['view']['task_id']==task['task_id']),None)
        artifact=next((s for s in reversed(sources) if s['kind']=='learning_artifact' and s['view'].get('plan_version')==plan['version']
                       and s['view']['task_id']==task['task_id']),None)
        checks=[s for s in sources if s['kind'] in ('assessment','retest') and s['view'].get('plan_version')==plan['version']
                and task['task_id'] in s['view'].get('task_ids',[])
                and set(task['topic_keys']).intersection(s['view'].get('topic_keys',[]))]
        latest={}
        for source in checks:
            for topic in set(task['topic_keys']).intersection(source['view']['topic_keys']):
                latest[topic]=source
        blockers=[]
        if not progress or progress['view']['status']!='completed':
            blockers.append('学习任务尚未标记完成')
        if not artifact:
            blockers.append('尚无已保存的课程练习成果')
        if len(latest)<len(task['topic_keys']):
            blockers.append('关联专题尚缺考核或复测记录')
        for topic,source in latest.items():
            grade=source['view']['grade']
            component=next((row for row in grade.get('scores',[]) if row['topic_key']==topic),None)
            if grade['status']!='scored' or component is None or component['score']<60:
                blockers.append('最近的关联专题分项尚待补强或复核')
        evidence_ids=list(dict.fromkeys([s['record_id'] for s in [progress,artifact,*latest.values()] if s]))
        interviews=[s for s in sources if s['kind']=='interview']
        interview_ids=[s['record_id'] for s in interviews[-1:]]
        tasks.append({
            **task,'status':progress['view']['status'] if progress else 'not_started',
            'artifact_record_id':artifact['record_id'] if artifact else None,
            'artifact_summary':artifact['view']['summary'] if artifact else '',
            'ready':not blockers,'blockers':list(dict.fromkeys(blockers)),
            'source_ids':evidence_ids,'interview_ids':interview_ids,
        })
    return {
        'contract_version':'learning-resume-handoff-v1','plan_version':plan['version'],
        'plan_record_id':plan['record_id'],'tasks':tasks,
        'completed_tasks':sum(t['status']=='completed' for t in tasks),
        'artifact_tasks':sum(bool(t['artifact_record_id']) for t in tasks),
        'ready_tasks':sum(t['ready'] for t in tasks),'total_tasks':len(tasks),
        'notice':'课程练习成果、进度和考核分项为固定演示。面试用于表达复盘；本摘要不证明生产经历。',
    }
