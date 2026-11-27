"""Validated tools exposed to the career agent, scoped to one personal session."""
from pathlib import Path
import json
import re

from pydantic import BaseModel, ConfigDict, Field


class Arguments(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Empty(Arguments):
    pass


class Search(Arguments):
    query: str = Field(min_length=1, max_length=180)


class Claim(Arguments):
    claim: str = Field(min_length=1, max_length=300)
    quote: str = Field(min_length=1, max_length=500)


class Claims(Arguments):
    claims: list[Claim] = Field(min_length=1, max_length=8)


class Task(Arguments):
    task_id: str | None = None
    title: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=1800)
    success_criteria: str = Field(min_length=1, max_length=600)


class Plan(Arguments):
    expected_version: int = Field(ge=0)
    rationale: str = Field(min_length=1, max_length=1200)
    tasks: list[Task] = Field(min_length=1, max_length=8)


class Interview(Arguments):
    interview_id: str = Field(min_length=1, max_length=240)


TOOL_MODELS = {
    'read_context': Empty,
    'search_history': Search,
    'search_resources': Search,
    'check_resume_quotes': Claims,
    'save_plan': Plan,
}
BUSINESS_MODELS = {'diagnose_job': Empty, 'optimize_resume': Empty,
                   'start_mock_interview': Empty, 'review_mock_interview': Interview}
DESCRIPTIONS = {
    'read_context': '读取当前用户简历、JD、诊断、最新任务、计划版本和执行反馈。先读取再规划。',
    'search_history': '按关键词检索当前会话的历史记录、用户执行反馈和以前的智能体结果。返回来源编号。',
    'search_resources': '检索项目已有的本地学习资源目录。返回参考链接及阅读目标，未实时访问外部网页。',
    'check_resume_quotes': '逐字核对引用能否在当前简历找到。命中只表示原文有此自述，不能证明能力或业绩。',
    'save_plan': '按当前计划版本保存或调整可执行任务。保留已完成任务。工具返回新的任务编号和版本。',
    'diagnose_job': '调用当前配置的真实业务模型生成并保存岗位匹配诊断，复用已有成功诊断。先read_context。费用计入本轮上限。',
    'optimize_resume': '依据已保存诊断和真实会话材料生成简历优化草稿。复用相同证据的草稿，用户核对条目后保存。不得声称事实已核实。',
    'start_mock_interview': '调用业务模型生成一轮短面试问题。返回用户待答问题后等待界面真实作答，不允许代答。每轮至多创建一场。',
    'review_mock_interview': '依据用户已提交的真实回答调用业务模型生成复盘，返回问题分析和改进建议。然后据结果调整计划；未作答会返回等待状态。',
}


def definitions(include_business=False):
    return [
        {'type': 'function', 'function': {'name': name, 'description': DESCRIPTIONS[name],
                                        'parameters': model.model_json_schema()}}
        for name, model in (TOOL_MODELS | (BUSINESS_MODELS if include_business else {})).items()
    ]


def search_rows(rows, query, limit=6):
    terms = re.findall(r'[\w]+', query.lower())
    ranked = []
    for row in rows:
        text = json.dumps(row, ensure_ascii=False).lower()
        score = sum(term in text for term in terms)
        if score:
            ranked.append((score, row))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [row for _, row in ranked[:limit]]


class CareerTools:
    def __init__(self, owner, token, run_id):
        self.owner = owner
        self.token = token
        self.run_id = run_id

    def execute(self, name, arguments):
        models = TOOL_MODELS | BUSINESS_MODELS
        if name not in models:
            return {'error': 'unknown_tool', 'message': '请选择已提供的工具。'}
        try:
            args = models[name].model_validate(arguments)
        except ValueError:
            return {'error': 'invalid_arguments', 'message': '工具参数未通过校验，请按工具定义修正。'}
        if name in BUSINESS_MODELS:
            from contextlib import closing
            from career_agent_business import CareerBusiness
            from competition_workbench import WorkbenchError
            with closing(self.owner._open(self.token)) as conn:
                read = conn.execute("SELECT 1 FROM events WHERE run_id=? AND kind='tool_result' AND json_extract(content,'$.name')='read_context'", (self.run_id,)).fetchone()
            if not read:
                return {'error': 'context_required', 'message': '请先调用read_context读取当前资料和版本。'}
            business = CareerBusiness(self.owner, self.token, self.run_id)
            try:
                return business.review_mock_interview(args.interview_id) if name == 'review_mock_interview' else getattr(business, name)()
            except WorkbenchError as exc:
                return {'error': 'business_conflict', 'message': str(exc), 'retry_automatically': False}
        return getattr(self, name)(args)

    def read_context(self, _args):
        context = self.owner.context(self.token)
        state = self.owner.snapshot(self.token)
        pending = [task for task in state['tasks'] if task['status'] != 'completed']
        completed = [task for task in state['tasks'] if task['status'] == 'completed'][-6:]
        tasks = [{**task, 'action': task['action'][:450], 'success_criteria': task['success_criteria'][:220],
                  'result': task['result'][:500]} for task in pending + completed]
        feedback = [{**row, 'content': row['content'][:1000]} for row in state['feedback'][:4]]
        return {**context, 'agent': {'plan_version': state['plan_version'],
                                    'rationale': state['rationale'], 'tasks': tasks,
                                    'feedback': feedback}}

    def search_history(self, args):
        records = self.owner.workbench.records(self.token)['records']
        rows = [{'source_id': r['record_id'], 'kind': r['kind'], 'title': r['title'],
                 'content': json.dumps(r['payload'], ensure_ascii=False)[:1600]}
                for r in records[:40]]
        agent = self.owner.snapshot(self.token)
        rows.extend({'source_id': r['source_id'], 'kind': 'user_feedback', 'content': r['content']}
                    for r in agent['feedback'])
        rows.extend({'source_id': r['run_id'], 'kind': 'agent_summary', 'content': r['summary'][:1800]}
                    for r in agent['runs'] if r['summary'])
        return {'results': search_rows(rows, args.query),
                'scope': 'current_session', 'notice': '用户自述和模型意见须结合原始材料核实。'}

    def search_resources(self, args):
        path = Path(__file__).resolve().parents[1] / 'knowledge_base/curated_resources/v1/catalog.json'
        rows = json.loads(path.read_text(encoding='utf-8'))['resources']
        selected = search_rows(rows, args.query)
        return {'results': [{key: row.get(key) for key in
                             ('resource_id', 'title', 'url', 'topic_ids', 'read_scope', 'learning_goal')}
                            for row in selected], 'live_web_fetch': False,
                'notice': '目录匹配可能为空，请据实调整任务或请用户补充资源。'}

    def check_resume_quotes(self, args):
        resume = self.owner.workbench.state(self.token)['candidate']['resume_text']
        return {'checks': [{'claim': item.claim, 'quote': item.quote,
                            'found': item.quote in resume,
                            'start': resume.find(item.quote)} for item in args.claims],
                'notice': '匹配只验证原文位置，不能独立证明事实真实性或结论。'}

    def save_plan(self, args):
        return self.owner.save_plan(self.token, self.run_id, args)
