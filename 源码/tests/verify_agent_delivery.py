"""Run the packaged application against a loopback-only tool-calling provider."""
import argparse
from tempfile import TemporaryDirectory
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import uuid


class Provider(BaseHTTPRequestHandler):
    requests = 0

    def log_message(self, *_args):
        pass

    def do_POST(self):
        Provider.requests += 1
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert self.path == '/v1/chat/completions'
        assert len(body['tools']) == 5
        user = json.loads(body['messages'][1]['content'])
        observations = [json.loads(m['content']) for m in body['messages'] if m['role'] == 'tool']
        names = [m['tool_calls'][0]['function']['name'] for m in body['messages']
                 if m['role'] == 'assistant' and m.get('tool_calls')]
        if not observations:
            name, arguments = 'read_context', {}
        elif names[-1] == 'read_context':
            name, arguments = 'search_history', {'query': 'JOIN'}
        elif names[-1] == 'search_history':
            name, arguments = 'search_resources', {'query': 'JOIN'}
        elif names[-1] == 'search_resources':
            context = observations[0]
            name, arguments = 'save_plan', {'expected_version': context['agent']['plan_version'],
                'rationale': '依据用户受阻反馈拆分前置任务。' if user['latest_user_feedback'] else '依据岗位要求先验证JOIN基础。',
                'tasks': [{'title': '先练习手工逐行配对' if user['latest_user_feedback'] else '核对JOIN结果',
                           'action': '画出三行测试数据的配对结果，再核对LEFT JOIN输出。',
                           'success_criteria': '能解释重复键和未匹配行的处理。'}]}
        else:
            name, arguments = None, None
        if name:
            message = {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'call_' + uuid.uuid4().hex, 'type': 'function',
                 'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}]}
        else:
            message = {'role': 'assistant', 'content': '已保存计划，请执行并反馈。'}
        result = {'choices': [{'message': message, 'finish_reason': 'tool_calls' if name else 'stop'}],
                  'usage': {'prompt_tokens': 600, 'completion_tokens': 100, 'total_tokens': 700}}
        raw = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main(executable):
    provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    token = 'd' * 64
    with TemporaryDirectory(prefix='shijie-agent-exe-') as folder:
        data = Path(folder) / 'data'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        environment = {**os.environ, 'PATH': str(Path(os.environ['SystemRoot']) / 'System32')}
        for key in ('PYTHONPATH', 'PYTHONHOME', 'AI_API_KEY', 'OPENAI_API_KEY', 'DEEPSEEK_API_KEY'):
            environment.pop(key, None)

        def api(path, body=None):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            try:
                conn.request('POST' if body is not None else 'GET', '/api/live/workbench/' + path,
                             body=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
                             headers={'Origin': f'http://127.0.0.1:{port}', 'X-CP-Session': token,
                                      'Content-Type': 'application/json'})
                response = conn.getresponse()
                result = json.loads(response.read())
                assert response.status == 200, (path, response.status, result)
                return result['data']
            finally:
                conn.close()

        def launch():
            log = Path(folder) / 'startup.log'
            with log.open('wb') as output:
                process = subprocess.Popen([str(executable), 'serve', '--allow-real-calls',
                    '--data-dir', str(data), '--port', str(port)], env=environment,
                    stdout=output, stderr=output)
            try:
                for _ in range(160):
                    if process.poll() is not None:
                        raise RuntimeError(log.read_text(encoding='utf-8', errors='replace'))
                    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=0.5)
                    try:
                        conn.request('GET', '/__release/health')
                        response = conn.getresponse()
                        if response.status == 200 and json.loads(response.read())['ready']:
                            return process
                    except OSError:
                        time.sleep(0.2)
                    finally:
                        conn.close()
                raise RuntimeError('Executable startup timed out')
            except Exception:
                process.terminate()
                process.wait(5)
                raise

        def wait_for_run():
            for _ in range(60):
                state = api('agent-state')
                if state['runs'][0]['status'] != 'running':
                    assert state['runs'][0]['status'] == 'waiting_user', state['runs'][0]
                    return state
                time.sleep(0.1)
            raise RuntimeError('Agent loop timed out')

        process = None
        try:
            process = launch()
            api('create_personal', {'request_id': str(uuid.uuid4()), 'start_date': '2026-11-26',
                'target_role': '测试开发实习生', 'resume_text': '我使用Python编写过接口测试，了解基础SQL，尚未完成JOIN结果验证。',
                'jd_text': '岗位要求使用Python编写测试，掌握SQL多表连接并能够核对查询输出与业务预期。'})
            state = api('agent-state')
            api('agent-configure', {'base_url': f'http://127.0.0.1:{provider.server_port}/v1',
                'model': 'local-test-tool-model', 'api_key': 'local-double-key-only',
                'input_price': 2, 'output_price': 8, 'revision': state['model']['revision']})
            first = {'request_id': str(uuid.uuid4()), 'goal': '根据资料和执行结果准备SQL面试',
                     'budget_micro_cny': 500000, 'feedback': None}
            api('agent-run', first)
            state = wait_for_run()
            assert state['tasks'][0]['title'] == '核对JOIN结果'
            calls = Provider.requests
            api('agent-run', first)
            assert Provider.requests == calls
            api('agent-run', {**first, 'request_id': str(uuid.uuid4()),
                'feedback': {'task_id': state['tasks'][0]['task_id'], 'status': 'blocked',
                             'content': '不会JOIN的配对规则，需要拆分前置步骤。'}})
            state = wait_for_run()
            assert state['tasks'][0]['title'] == '先练习手工逐行配对'
            assert len(state['feedback']) == 1 and state['plan_version'] == 3
            stopped = subprocess.run([str(executable), 'stop', '--data-dir', str(data)],
                                     env=environment, capture_output=True, timeout=20)
            assert stopped.returncode == 0, stopped.stderr.decode(errors='replace')
            process.wait(10)
            process = launch()
            restored = api('agent-state')
            assert restored['tasks'] == state['tasks'] and restored['model']['configured']
            assert Provider.requests == 10
            print('Packaged EXE verified: personal HTTP entry, DPAPI configuration, 10 native tool-call requests, feedback replanning, duplicate protection and restart recovery. Provider was loopback-only.')
        finally:
            if process and process.poll() is None:
                process.terminate()
                process.wait(8)
            provider.shutdown()
            provider.server_close()
            thread.join(3)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', type=Path, required=True)
    args = parser.parse_args()
    main(args.executable.resolve())
