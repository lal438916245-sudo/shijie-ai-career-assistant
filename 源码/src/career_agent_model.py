"""Native OpenAI-compatible function calling with local encrypted configuration."""
from copy import deepcopy
import json
from urllib.parse import urlsplit

import httpx

from model_preparation import DEFAULT, ModelPreparation, PreparationError


class AgentModel:
    def __init__(self, directory, *, preparation=None, client_factory=None):
        self.preparation = preparation or ModelPreparation(directory / 'agent-model')
        self.client_factory = client_factory

    def status(self):
        status = self.preparation.status()
        config = status['config']
        return {'configured': status['key_state'] == 'saved', 'revision': status['revision'],
                'base_url': config['base_url'], 'model': config['model'],
                'input_price': config['input_price_per_million'],
                'output_price': config['output_price_per_million']}

    def configure(self, body):
        if not isinstance(body, dict) or set(body) != {
                'base_url', 'model', 'api_key', 'input_price', 'output_price', 'revision'}:
            raise PreparationError('请填写模型地址、名称、密钥和单价。')
        config = {**DEFAULT, 'provider': 'Career Agent', 'base_url': body['base_url'],
                  'model': body['model'], 'max_input_chars': 60000, 'max_output_tokens': 3000,
                  'timeout_seconds': 45, 'input_price_per_million': body['input_price'],
                  'output_price_per_million': body['output_price'], 'currency': 'CNY'}
        for name in ('input_price', 'output_price'):
            value = body[name]
            if type(value) not in (int, float) or not 0 < value <= 100000:
                raise PreparationError('请按服务商账单填写大于0的人民币单价。')
        self.preparation.save({'config': config, 'api_key': body['api_key'],
                               'key_action': 'replace' if body['api_key'] else 'keep',
                               'expected_revision': body['revision']})
        return self.status()

    def settings(self):
        with self.preparation.lock:
            value = self.preparation._read()
            if not value['encrypted_key']:
                raise PreparationError('请先配置支持工具调用的模型。')
            return deepcopy(value)

    def payload(self, messages, tools, settings):
        config = settings['config']
        body = {'model': config['model'], 'messages': messages, 'tools': tools,
                'tool_choice': 'auto', 'max_tokens': config['max_output_tokens']}
        host = urlsplit(config['base_url']).hostname
        if host == 'api.deepseek.com':
            body['thinking'] = {'type': 'disabled'}
        if len(json.dumps(body, ensure_ascii=False)) > config['max_input_chars']:
            raise PreparationError('本次上下文超过上限，请缩短目标或反馈内容后新建一轮。')
        return body

    def complete(self, payload, settings):
        with self.preparation.lock:
            current = self.preparation._read()
            if current != settings:
                raise PreparationError('模型配置已变化，请保留当前记录后重新开始一轮。')
            key = self.preparation.vault.open(current['encrypted_key'])
        config = settings['config']
        factory = self.client_factory or (lambda: httpx.Client(
            transport=httpx.HTTPTransport(retries=0), follow_redirects=False, trust_env=False,
            timeout=config['timeout_seconds']))
        with factory() as client:
            with client.stream('POST', config['base_url'] + '/chat/completions', json=payload,
                               headers={'Authorization': 'Bearer ' + key}) as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 1000000:
                        raise ValueError('模型返回内容过长。')
        result = json.loads(raw)
        if key in json.dumps(result, ensure_ascii=False):
            raise ValueError('模型响应包含凭据信息，已停止采用。')
        return result
