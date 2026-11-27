"""Business tools use the real SDK/receipt path with intercepted HTTP only."""
from contextlib import closing
from copy import deepcopy
import json
import http.client
from pathlib import Path
import sys
import time
import threading
import uuid

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from career_agent import CareerAgent, encode
from career_agent_business import CareerBusiness
from career_agent_model import AgentModel
from career_agent_tools import CareerTools, definitions
from competition_workbench import CompetitionWorkbench, WorkbenchConflict
from unified_model import UnifiedModelPreparation
from model_preparation import DEFAULT, PreparationError
from workbench_abf import FixedABFTransport
from ced_contracts import fixed_output
from test_career_agent import TestVault, tool, reply, request, plan_from_context


def wait(agent, token, run_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with agent.guard:
            worker = agent.running.get(run_id)
        if worker is None:
            return agent.snapshot(token)
        worker.join(.1)
    raise AssertionError('Business workflow did not finish')


@pytest.fixture
def business(tmp_path):
    prep = UnifiedModelPreparation(tmp_path, TestVault())
    prep.save({'config': {**DEFAULT, 'provider': 'business-test', 'base_url': 'https://provider.invalid/v1',
                         'model': 'shared-business-model', 'max_input_chars': 100000,
                         'input_price_per_million': 2, 'output_price_per_million': 8},
               'api_key': 'synthetic-business-key', 'key_action': 'replace', 'expected_revision': prep._read()['revision']})
    token = '8' * 64
    sdk_calls, agent_calls, decisions = [], [], []
    failure = []

    def sdk_provider(http_request):
        assert http_request.headers['authorization'] == 'Bearer synthetic-business-key'
        body = json.loads(http_request.content)
        stage = json.loads(body['messages'][1]['content']).get('stage', 'a_diagnosis')
        sdk_calls.append(stage)
        if failure:
            raise httpx.ReadTimeout(failure.pop())
        with closing(workbench._connect(token)) as conn:
            prefix = 'wbf' if stage == 'a_diagnosis' else 'wbc'
            row = conn.execute(f"SELECT p.request_json FROM {prefix}_grants g JOIN {prefix}_previews p USING(preview_id) WHERE g.status='dispatching' ORDER BY g.rowid DESC LIMIT 1").fetchone()
            frozen = json.loads(row[0])
        content = FixedABFTransport().send(frozen)['content'] if stage == 'a_diagnosis' else encode(fixed_output(frozen))
        return httpx.Response(200, json={'choices': [{'index': 0, 'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': content}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}})

    workbench = CompetitionWorkbench(tmp_path, case_profile='final-20261107', session_preparation=prep,
        session_outbound_enabled=True,
        session_http_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(sdk_provider)))
    workbench.create_personal(token, {'request_id': str(uuid.uuid4()), 'start_date': '2026-11-27',
        'target_role': '测试开发实习生',
        'resume_text': '我用Python编写过接口测试，了解SQL基础查询，尚未完成LEFT JOIN结果验证和聚合练习。',
        'jd_text': '岗位要求Python接口自动化测试、SQL多表连接与日志排查，能说明项目个人贡献和验证方法。'})

    def agent_provider(http_request):
        assert http_request.headers['authorization'] == 'Bearer synthetic-business-key'
        body = json.loads(http_request.content)
        agent_calls.append(deepcopy(body))
        assert len(body['tools']) == 9
        decision = decisions.pop(0)
        return httpx.Response(200, json=reply(decision(body) if callable(decision) else decision))

    model = AgentModel(tmp_path, preparation=prep,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(agent_provider)))
    agent = CareerAgent(workbench, model=model, enabled=True)
    return agent, token, sdk_calls, agent_calls, decisions, failure


def workflow(agent, token, decisions):
    def business_tools(_body):
        calls = [tool(name, {})['tool_calls'][0] for name in
                 ('diagnose_job', 'optimize_resume', 'start_mock_interview')]
        return {'role': 'assistant', 'content': None, 'tool_calls': calls}
    decisions.extend([tool('read_context', {}), business_tools,
                      plan_from_context, {'role': 'assistant', 'content': '诊断和简历草稿已生成，请回答面试问题。'}])
    body = request()
    agent.start(token, body)
    state = wait(agent, token, body['request_id'])
    assert state['runs'][0]['status'] == 'waiting_user', state['runs'][0]
    return state, body


def test_diagnosis_resume_interview_then_real_answer_review_and_replanning(business):
    agent, token, sdk, native, decisions, _ = business
    state, first = workflow(agent, token, decisions)
    assert sdk == ['a_diagnosis', 'd_revision', 'e_turn']
    assert agent.workbench.state(token)['diagnosis']
    draft = state['business']['resume_draft']
    assert draft['candidate']['items'] and not draft['saved_resume_id']
    interview = state['business']['interview']
    assert interview['waiting_for_user'] and interview['question']['text']
    before = len(native), len(sdk)
    agent.start(token, first)
    assert (len(native), len(sdk)) == before

    iid = interview['interview_id']
    def check_report(body):
        result = next(json.loads(m['content']) for m in reversed(body['messages'])
                      if m['role'] == 'tool' and json.loads(m['content']).get('report'))
        assert result['report']['model_application']
        assert result['report']['findings']
        return plan_from_context(body, '补充SQL连接验证与个人贡献证据')
    decisions.extend([tool('read_context', {}), plan_from_context,
                      tool('review_mock_interview', {'interview_id': iid}),
                      {'role': 'assistant', 'content': '提前结束，尚未按复盘更新任务。'},
                      tool('read_context', {}), check_report,
                      {'role': 'assistant', 'content': '已根据真实面试回答调整任务。'}])
    answer = {'request_id': str(uuid.uuid4()), 'goal': first['goal'], 'budget_micro_cny': 500000,
              'interview_id': iid, 'question_turn_id': interview['question']['turn_id'],
              'answer': '我写过Python接口测试，用固定请求编号核对重复提交；LEFT JOIN未匹配行目前还不会解释。'}
    agent.answer_interview(token, answer)
    state = wait(agent, token, answer['request_id'])
    assert state['runs'][0]['status'] == 'waiting_user', state['runs'][0]
    assert sdk == ['a_diagnosis', 'd_revision', 'e_turn', 'e_report']
    assert state['tasks'][0]['title'] == '补充SQL连接验证与个人贡献证据'
    turns = agent.workbench.interview(token, iid)['interview']['turns']
    assert [t['text'] for t in turns if t['role'] == 'user'] == [answer['answer']]
    agent.answer_interview(token, answer)
    assert len(sdk) == 4 and len(native) == 11
    restored = CareerAgent(agent.workbench, model=agent.model, enabled=True).snapshot(token)
    assert restored['business']['interview']['report']['model_application']
    assert restored['tasks'] == state['tasks']
    with closing(agent._open(token)) as conn:
        business_charges = conn.execute("SELECT count(*),sum(cost) FROM calls WHERE call_id LIKE 'business:%'").fetchone()
    assert tuple(business_charges) == (4, 4000)


def test_reuse_outputs_cannot_fabricate_answer_and_resume_needs_explicit_selection(business):
    agent, token, sdk, _, decisions, _ = business
    state, body = workflow(agent, token, decisions)
    tools = CareerTools(agent, token, body['request_id'])
    assert tools.execute('diagnose_job', {})['reused']
    assert tools.execute('optimize_resume', {})['generated']
    assert tools.execute('start_mock_interview', {})['waiting_for_user']
    assert tools.execute('start_mock_interview', {'answer': '伪造的模型回答'})['error'] == 'invalid_arguments'
    iid = state['business']['interview']['interview_id']
    assert tools.execute('review_mock_interview', {'interview_id': iid})['error'] == 'user_answer_required'
    assert sdk == ['a_diagnosis', 'd_revision', 'e_turn']
    assert not any(t['role'] == 'user' for t in agent.workbench.interview(token, iid)['interview']['turns'])
    draft = state['business']['resume_draft']
    selected = draft['selectable_item_ids'][:1]
    CareerBusiness(agent, token).accept_resume({'request_id': str(uuid.uuid4()),
        'authorization_id': draft['authorization_id'], 'selected_item_ids': selected})
    restored = agent.snapshot(token)['business']['resume_draft']
    assert restored['saved_resume_id'] and restored['saved_text']
    assert len(sdk) == 3


def test_unknown_business_response_is_not_dispatched_again(business):
    agent, token, sdk, _, decisions, failures = business
    failures.append('synthetic uncertain outcome')
    decisions.extend([tool('read_context', {}), tool('diagnose_job', {}),
                      tool('diagnose_job', {}), plan_from_context,
                      {'role': 'assistant', 'content': '诊断连接结果未知，先保留资料并安排原文核对。'}])
    body = request()
    agent.start(token, body)
    state = wait(agent, token, body['request_id'])
    assert state['runs'][0]['status'] == 'waiting_user', state['runs'][0]
    assert sdk == ['a_diagnosis']
    assert not agent.workbench.state(token)['diagnosis']
    with closing(agent._open(token)) as conn:
        row = conn.execute("SELECT status,cost,reserve FROM calls WHERE call_id LIKE 'business:%'").fetchone()
    assert row['status'] == 'unknown' and row['cost'] is None and row['reserve'] > 0


def test_business_request_obeys_same_run_budget_before_sdk_dispatch(business):
    agent, token, sdk, _, _, _ = business
    run = str(uuid.uuid4())
    with agent._open(token) as conn:
        conn.execute('INSERT INTO runs(run_id,body_digest,goal,status,budget,created) VALUES(?,?,?,?,?,?)',
                     (run, 'test-digest', '预算检查', 'running', 10000, '2026-11-27'))
        agent._event(conn, run, 'tool_result', {'name': 'read_context', 'result': {}})
    with pytest.raises(PreparationError, match='费用预占'):
        CareerTools(agent, token, run).execute('diagnose_job', {})
    assert not sdk
    assert not (agent.workbench.state(token)['session_runtime']['entries'])


def test_business_tools_require_context_and_foreign_interview_is_rejected(business):
    agent, token, sdk, _, decisions, _ = business
    definitions_with_business = definitions(include_business=True)
    assert len(definitions_with_business) == 9
    assert not any('answer' in t['function']['parameters'].get('properties', {}) for t in definitions_with_business)
    decisions.extend([tool('diagnose_job', {}), tool('read_context', {}), plan_from_context,
                      {'role': 'assistant', 'content': '先完成资料核对。'}])
    body = request()
    agent.start(token, body)
    state = wait(agent, token, body['request_id'])
    assert any(e['kind'] == 'tool_result' and e['content']['result'].get('error') == 'context_required' for e in state['events'])
    assert not sdk
    with pytest.raises(WorkbenchConflict):
        agent.answer_interview(token, {'request_id': str(uuid.uuid4()), 'goal': body['goal'], 'budget_micro_cny': 500000,
            'interview_id': 'foreign', 'question_turn_id': 'foreign', 'answer': '这份回答不得写入其他会话。'})


def test_http_answer_and_resume_entrypoints_continue_the_business_loop(business, tmp_path):
    from live_session_http import LocalWorkflowServer
    agent, token, sdk, _, decisions, _ = business
    state, first = workflow(agent, token, decisions)
    server = LocalWorkflowServer(('127.0.0.1', 0), tmp_path / 'http', {'http://127.0.0.1:5173'}, 'f' * 64,
        hunter_factory=lambda *_: None, planner_factory=lambda *_: None,
        workbench_case_profile='final-20261107', session_outbound_enabled=True)
    agent.workbench.career_agent = agent
    server.competition_workbench = agent.workbench
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    entered, release = threading.Event(), threading.Event()

    def post(path, body):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=15)
        try:
            conn.request('POST', '/api/live/workbench/' + path, body=json.dumps(body),
                headers={'Origin': 'http://127.0.0.1:5173', 'X-CP-Local-Key': 'f' * 64,
                         'X-CP-Session': token, 'Content-Type': 'application/json'})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()
    try:
        draft = state['business']['resume_draft']
        status, saved = post('agent-resume-apply', {'request_id': str(uuid.uuid4()),
            'authorization_id': draft['authorization_id'], 'selected_item_ids': draft['selectable_item_ids'][:1]})
        assert status == 200, saved
        assert saved['data']['business']['resume_draft']['saved_resume_id']
        question = state['business']['interview']
        decisions.extend([tool('read_context', {}), tool('review_mock_interview', {'interview_id': question['interview_id']}),
                          plan_from_context, {'role': 'assistant', 'content': '已复盘并保存后续任务。'}])
        body = {'request_id': str(uuid.uuid4()), 'goal': first['goal'], 'budget_micro_cny': 500000,
                'interview_id': question['interview_id'], 'question_turn_id': question['question']['turn_id'],
                'answer': '我能写接口断言，尚未核对SQL未匹配行，需要先练习样例结果。'}
        status, accepted = post('agent-answer-interview', body)
        assert status == 200, accepted
        state = wait(agent, token, body['request_id'])
        assert state['business']['interview']['report']['model_application']
        assert sdk == ['a_diagnosis', 'd_revision', 'e_turn', 'e_report']
        assert post('agent-answer-interview', body)[0] == 200
        assert len(sdk) == 4
        def delayed(_body):
            entered.set()
            assert release.wait(15)
            return tool('read_context', {})
        decisions.append(delayed)
        running = request()
        assert post('agent-run', running)[0] == 200
        assert entered.wait(5)
        assert post('resume_generate', {'request_id': str(uuid.uuid4()),
            'expected_revision': agent.workbench.state(token)['revision']})[0] == 409
        assert post('agent-cancel', {'run_id': running['request_id']})[0] == 200
        release.set()
        assert wait(agent, token, running['request_id'])['runs'][0]['status'] == 'cancelled'
    finally:
        release.set()
        server.shutdown(); thread.join(5); server.server_close()
