"""Regression coverage for native tool calls, replanning and durable execution."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import json
import http.client
import sys
import threading
import time
import uuid

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from career_agent import CareerAgent
from career_agent_model import AgentModel
from career_agent_tools import CareerTools
from competition_workbench import CompetitionWorkbench, WorkbenchConflict
from model_preparation import DEFAULT, ModelPreparation


class TestVault:
    __test__ = False

    def seal(self, value):
        return 'test-encrypted:' + value

    def open(self, value):
        return value.removeprefix('test-encrypted:')


def tool(name, arguments):
    return {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'call_' + uuid.uuid4().hex, 'type': 'function',
         'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}]}


def reply(message):
    return {'choices': [{'message': message, 'finish_reason': 'tool_calls' if message.get('tool_calls') else 'stop'}],
            'usage': {'prompt_tokens': 400, 'completion_tokens': 60, 'total_tokens': 460}}


def request(feedback=None, budget=500000):
    return {'request_id': str(uuid.uuid4()), 'goal': '准备SQL测试开发面试，依据反馈调整任务',
            'feedback': feedback, 'budget_micro_cny': budget}


def wait(agent, token, run_id):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        with agent.guard:
            worker = agent.running.get(run_id)
        if worker is None:
            return agent.snapshot(token)
        worker.join(timeout=0.1)
    raise AssertionError('Agent did not finish')


@pytest.fixture
def setup(tmp_path):
    workbench = CompetitionWorkbench(tmp_path, case_profile='final-20261107')
    token = 'a' * 64
    workbench.create_personal(token, {'request_id': str(uuid.uuid4()), 'start_date': '2026-11-26',
        'target_role': '测试开发实习生', 'resume_text': '我使用Python编写过接口测试，了解基础SQL查询，尚未验证多表连接与聚合。',
        'jd_text': '岗位要求使用Python开发自动化测试，熟悉SQL多表连接、数据质量核对和缺陷排查。'})
    prep = ModelPreparation(tmp_path / 'private-test-model', vault=TestVault())
    prep.save({'config': {**DEFAULT, 'provider': 'test', 'base_url': 'https://model.example.invalid/v1',
                         'model': 'test-tools', 'max_input_chars': 60000,
                         'input_price_per_million': 2, 'output_price_per_million': 8},
               'api_key': 'test-secret-model-key', 'key_action': 'replace', 'expected_revision': 0})
    calls = []
    decisions = []

    def provider(req):
        body = json.loads(req.content)
        calls.append(deepcopy(body))
        assert req.headers['authorization'] == 'Bearer test-secret-model-key'
        assert body['tool_choice'] == 'auto' and len(body['tools']) == 5
        decision = decisions.pop(0)
        return httpx.Response(200, json=reply(decision(body) if callable(decision) else decision))

    model = AgentModel(tmp_path, preparation=prep,
                       client_factory=lambda: httpx.Client(transport=httpx.MockTransport(provider)))
    agent = CareerAgent(workbench, model=model, enabled=True)
    return agent, token, calls, decisions


def plan_from_context(body, title='完成一组JOIN结果核对'):
    context = json.loads(next(m['content'] for m in reversed(body['messages'])
                              if m['role'] == 'tool' and 'plan_version' in m['content']))
    return tool('save_plan', {'expected_version': context['agent']['plan_version'],
        'rationale': '根据岗位要求和本次执行证据调整准备顺序。',
        'tasks': [{'title': title, 'action': '用三行样例手算LEFT JOIN，再写查询并核对实际结果。',
                   'success_criteria': '解释未匹配行和重复键为何影响结果行数。'}]})


def test_native_tool_observations_drive_next_decision_and_persist(setup):
    agent, token, calls, decisions = setup

    def after_quote(body):
        observation = json.loads(body['messages'][-1]['content'])
        assert observation['checks'][0]['found'] is False
        return tool('search_resources', {'query': 'JOIN'})

    decisions.extend([tool('read_context', {}),
                      tool('check_resume_quotes', {'claims': [{'claim': '有生产优化经验', 'quote': '我优化过千万级查询'}]}),
                      after_quote, plan_from_context,
                      {'role': 'assistant', 'content': '已有资料缺少生产优化证据，先完成JOIN结果核对。'}])
    body = request()
    agent.start(token, body)
    state = wait(agent, token, body['request_id'])
    assert state['runs'][0]['status'] == 'waiting_user'
    assert state['tasks'][0]['title'] == '完成一组JOIN结果核对'
    assert len(calls) == 5
    assert any(e['content'].get('name') == 'search_resources' for e in state['events'])
    restored = CareerAgent(agent.workbench, model=agent.model, enabled=True).snapshot(token)
    assert restored['tasks'] == state['tasks']
    assert restored['runs'][0]['held_micro_cny'] > 0
    assert 'test-secret-model-key' not in json.dumps(restored)


def test_blocked_feedback_is_retrieved_and_plan_changes_without_duplicate_dispatch(setup):
    agent, token, calls, decisions = setup
    decisions.extend([tool('read_context', {}), plan_from_context, {'role': 'assistant', 'content': '请先执行任务。'}])
    first = request()
    agent.start(token, first)
    state = wait(agent, token, first['request_id'])
    task_id = state['tasks'][0]['task_id']

    def after_history(body):
        observation = json.loads(body['messages'][-1]['content'])
        assert any('不会LEFT JOIN' in r['content'] for r in observation['results'])
        return plan_from_context(body, '先画出两张表的逐行配对')

    decisions.extend([tool('read_context', {}), tool('search_history', {'query': '不会LEFT JOIN'}),
                      after_history, {'role': 'assistant', 'content': '已根据受阻原因降低任务难度。'}])
    second = request({'task_id': task_id, 'status': 'blocked', 'content': '不会LEFT JOIN，无法判断未匹配行。'})
    agent.start(token, second)
    state = wait(agent, token, second['request_id'])
    assert state['tasks'][0]['title'] == '先画出两张表的逐行配对'
    before = len(calls)
    agent.start(token, second)
    assert len(calls) == before
    assert len(state['feedback']) == 1
    assert state['plan_version'] == 3


def test_completed_task_survives_replanning_and_invalid_calls_are_observations(setup):
    agent, token, calls, decisions = setup
    decisions.extend([tool('read_context', {}), plan_from_context, {'role': 'assistant', 'content': '任务已安排。'}])
    first = request()
    agent.start(token, first)
    state = wait(agent, token, first['request_id'])
    task_id = state['tasks'][0]['task_id']

    def reject_invalid_then_replan(body):
        assert json.loads(body['messages'][-1]['content'])['error'] == 'unknown_tool'
        return plan_from_context(body, '继续核对GROUP BY口径')

    decisions.extend([tool('read_context', {}), tool('execute_arbitrary_code', {}),
                      reject_invalid_then_replan, {'role': 'assistant', 'content': '保留已完成任务，安排聚合练习。'}])
    second = request({'task_id': task_id, 'status': 'completed', 'content': '已完成手算与查询，核对结果一致。'})
    agent.start(token, second)
    state = wait(agent, token, second['request_id'])
    assert state['runs'][0]['status'] == 'waiting_user'
    assert any(t['task_id'] == task_id and t['status'] == 'completed' for t in state['tasks'])
    assert CareerTools(agent, token, second['request_id']).execute('search_history', {'query': ''})['error'] == 'invalid_arguments'


def test_concurrent_start_cancel_and_configure(setup):
    agent, token, calls, decisions = setup
    entered, release = threading.Event(), threading.Event()

    def slow(_body):
        entered.set()
        assert release.wait(5)
        return tool('read_context', {})

    decisions.append(slow)
    body = request()
    agent.start(token, body)
    assert entered.wait(3)
    with ThreadPoolExecutor(max_workers=2) as pool:
        duplicates = list(pool.map(lambda _: agent.start(token, body), range(2)))
    assert all(v['runs'][0]['run_id'] == body['request_id'] for v in duplicates)
    with pytest.raises(WorkbenchConflict):
        agent.start(token, request())
    with pytest.raises(WorkbenchConflict):
        agent.configure(token, {})
    agent.cancel(token, {'run_id': body['request_id']})
    release.set()
    state = wait(agent, token, body['request_id'])
    assert state['runs'][0]['status'] == 'cancelled' and len(calls) == 1
    assert not any(e['kind'] == 'tool_result' for e in state['events'])


def test_budget_gate_and_unknown_usage_are_durable(setup):
    agent, token, calls, decisions = setup
    settings = agent.model.preparation._read()
    expensive = {**settings['config'], 'input_price_per_million': 100000, 'output_price_per_million': 100000}
    agent.model.preparation.save({'config': expensive, 'api_key': '', 'key_action': 'keep', 'expected_revision': settings['revision']})
    body = request(budget=10000)
    agent.start(token, body)
    state = wait(agent, token, body['request_id'])
    assert state['runs'][0]['status'] == 'limit_reached' and not calls

    settings = agent.model.preparation._read()
    agent.model.preparation.save({'config': {**settings['config'], 'input_price_per_million': 2, 'output_price_per_million': 8},
                                  'api_key': '', 'key_action': 'keep', 'expected_revision': settings['revision']})

    def timeout(_body):
        raise httpx.ReadTimeout('simulated transport timeout')

    decisions.append(timeout)
    body = request()
    agent.start(token, body)
    state = wait(agent, token, body['request_id'])
    assert state['runs'][0]['status'] == 'failed'
    assert state['runs'][0]['held_micro_cny'] > 0
    agent.start(token, body)
    assert len(calls) == 1


def test_replay_is_read_only_and_personal_sessions_are_isolated(setup):
    agent, token, calls, decisions = setup
    another = 'b' * 64
    agent.workbench.create_personal(another, {'request_id': str(uuid.uuid4()), 'start_date': '2026-11-26',
        'target_role': '数据开发实习生', 'resume_text': '我学习过Python和数据库基础，目前正在准备数据开发实习岗位，希望补充实践。',
        'jd_text': '要求熟悉SQL查询、基本数据建模与数据质量核对，能够用Python完成数据处理。'})
    decisions.extend([tool('read_context', {}), plan_from_context, {'role': 'assistant', 'content': '请执行。'}])
    body = request()
    agent.start(token, body)
    wait(agent, token, body['request_id'])
    assert agent.snapshot(another)['tasks'] == []
    with pytest.raises(Exception):
        agent.snapshot('c' * 64)


def test_round_limit_and_restart_preserve_unknown_reservations(setup):
    agent, token, calls, decisions = setup
    decisions.extend([tool('search_resources', {'query': 'no-such-topic'}) for _ in range(8)])
    body = request()
    agent.start(token, body)
    state = wait(agent, token, body['request_id'])
    assert state['runs'][0]['status'] == 'limit_reached' and len(calls) == 8
    with agent._open(token) as conn:
        conn.execute("UPDATE runs SET status='running' WHERE run_id=?", (body['request_id'],))
        conn.execute('INSERT INTO calls VALUES(?,?,?,?,NULL,NULL)', ('crashed-call', body['request_id'], 'dispatching', 1000))
    restored = CareerAgent(agent.workbench, model=agent.model, enabled=True).snapshot(token)
    assert restored['runs'][0]['status'] == 'interrupted'
    assert restored['runs'][0]['held_micro_cny'] >= 1000


def test_http_entrypoint_enforces_session_and_returns_background_run(setup, tmp_path):
    from live_session_http import LocalWorkflowServer
    agent, token, calls, decisions = setup
    agent.workbench.career_agent = agent
    origin = 'http://127.0.0.1:5173'
    key = 'f' * 64
    server = LocalWorkflowServer(('127.0.0.1', 0), tmp_path / 'http-server', {origin}, key,
                                hunter_factory=lambda *_: None, planner_factory=lambda *_: None,
                                workbench_case_profile='final-20261107', session_outbound_enabled=True)
    server.competition_workbench = agent.workbench
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(path, body=None, session=token):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        try:
            conn.request('POST' if body is not None else 'GET', '/api/live/workbench/' + path,
                         body=json.dumps(body) if body is not None else None,
                         headers={'Origin': origin, 'X-CP-Local-Key': key, 'X-CP-Session': session,
                                  'Content-Type': 'application/json'})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    try:
        status, response = call('agent-state')
        assert status == 200 and response['data']['source_kind'] == 'career_agent'
        assert call('agent-state', session='invalid')[0] == 400
        decisions.extend([tool('read_context', {}), plan_from_context, {'role': 'assistant', 'content': '请按当前计划执行。'}])
        body = request()
        status, response = call('agent-run', body)
        assert status == 200 and response['data']['runs'][0]['run_id'] == body['request_id']
        wait(agent, token, body['request_id'])
        status, response = call('agent-state')
        assert response['data']['runs'][0]['status'] == 'waiting_user'
        assert not server.active
        assert call('agent-state', {})[0] == 400
    finally:
        server.shutdown()
        server.server_close()
        server.lease.close()
        thread.join(timeout=3)
