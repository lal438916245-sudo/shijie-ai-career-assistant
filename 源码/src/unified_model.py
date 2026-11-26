"""One effective model configuration, with a platform default and user override."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

from model_preparation import ModelPreparation, PreparationError, PreparationConflict, DEFAULT, validate_config

_locks = {}
_locks_guard = threading.Lock()


class UnifiedModelPreparation(ModelPreparation):
    unified = True

    def __init__(self, directory, vault=None):
        super().__init__(directory, vault)
        self.directory = Path(directory)
        self.path = self.path.with_name('profiles.json')
        with _locks_guard:
            self.lock = _locks.setdefault(str(self.path.resolve()), threading.RLock())

    def _write_profiles(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.profiles-', dir=self.path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _profiles(self):
        if not self.path.exists():
            legacy = ModelPreparation(self.directory, self.vault)._read()
            old_agent = ModelPreparation(self.directory / 'agent-model', self.vault)._read()
            policy_path = self.path.with_name('judge-policy.json')
            policy = json.loads(policy_path.read_text(encoding='utf-8')) if policy_path.exists() else None
            fingerprint = hashlib.sha256(json.dumps(legacy['config'], ensure_ascii=False,
                sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            sponsored = bool(policy and policy.get('config_digest') == fingerprint)
            profile = {'config': legacy['config'], 'encrypted_key': legacy['encrypted_key'], 'policy': policy if sponsored else None}
            platform = profile if sponsored and legacy['encrypted_key'] else None
            user = profile if legacy['encrypted_key'] and not sponsored else None
            if user is None and old_agent['encrypted_key']:
                user = {'config': old_agent['config'], 'encrypted_key': old_agent['encrypted_key'], 'policy': None}
            value = {'version': 1, 'revision': max(legacy['revision'], old_agent['revision']) + 1,
                     'selected': 'user' if user else 'platform', 'platform': platform, 'user': user}
            self._write_profiles(value)
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if value['version'] != 1 or type(value['revision']) is not int or value['revision'] < 0 or value['selected'] not in ('platform', 'user'):
                raise ValueError()
            for source in ('platform', 'user'):
                profile = value[source]
                if profile is not None:
                    profile['config'] = validate_config(profile['config'])
                    if not isinstance(profile['encrypted_key'], str) or not profile['encrypted_key']:
                        raise ValueError()
            return value
        except (ValueError, TypeError, KeyError):
            raise PreparationError('统一模型配置无法读取，原文件已保留。') from None

    def _read(self):
        with self.lock:
            value = self._profiles()
            profile = value[value['selected']]
            return {'version': 1, 'revision': value['revision'],
                    'config': deepcopy(profile['config']) if profile else dict(DEFAULT),
                    'encrypted_key': profile['encrypted_key'] if profile else None}

    def status(self):
        with self.lock:
            result = super().status()
            value = self._profiles()
            profile = value[value['selected']]
            result.update(model_source=value['selected'],
                          platform_available=value['platform'] is not None,
                          user_key_saved=value['user'] is not None,
                          tools_supported=value['selected'] == 'user' or bool(profile and (profile['policy'] or {}).get('tool_calls_supported')))
            return result

    def platform_policy(self):
        with self.lock:
            value = self._profiles()
            return deepcopy(value['platform']['policy']) if value['selected'] == 'platform' and value['platform'] else None

    def install_platform(self, config, key, policy):
        config = validate_config(config)
        with self.lock:
            value = self._profiles()
            old = value['platform']
            encrypted = old['encrypted_key'] if old and self.vault.open(old['encrypted_key']) == key else self.vault.seal(key)
            profile = {'config': config, 'encrypted_key': encrypted, 'policy': deepcopy(policy)}
            if old != profile:
                value['platform'] = profile
                if value['selected'] == 'platform':
                    value['revision'] += 1
                self._write_profiles(value)
            return self.status()

    def save(self, body):
        if not isinstance(body, dict) or set(body) != {'config', 'api_key', 'key_action', 'expected_revision'}:
            raise PreparationError('模型配置字段无效。')
        config = validate_config(body['config'])
        key, action = body['api_key'], body['key_action']
        if action not in ('keep', 'replace', 'delete') or not isinstance(key, str):
            raise PreparationError('密钥操作无效。')
        if action == 'replace' and (not 8 <= len(key) <= 4096 or any(ch.isspace() for ch in key)):
            raise PreparationError('请填写有效API Key。')
        if action != 'replace' and key:
            raise PreparationError('密钥操作与内容不一致。')
        with self.lock:
            value = self._profiles()
            if type(body['expected_revision']) is not int or value['revision'] != body['expected_revision']:
                raise PreparationConflict('模型配置已变化，请重新读取后再保存。')
            if action == 'delete':
                value['selected'] = 'platform'
                value['user'] = None
            else:
                old = value['user']
                encrypted = old['encrypted_key'] if old and old['config']['base_url'] == config['base_url'] else None
                if action == 'replace':
                    encrypted = self.vault.seal(key)
                if not encrypted:
                    raise PreparationError('首次使用自己的模型时请填写API Key。')
                value['user'] = {'config': config, 'encrypted_key': encrypted, 'policy': None}
                value['selected'] = 'user'
            value['revision'] += 1
            self._write_profiles(value)
            return self.status()

    def select_platform(self, revision):
        with self.lock:
            value = self._profiles()
            if type(revision) is not int or value['revision'] != revision:
                raise PreparationConflict('模型配置已变化，请重新读取。')
            if value['platform'] is None:
                raise PreparationError('平台连接尚未就绪，请联网启动后重试。')
            if value['selected'] != 'platform':
                value['selected'] = 'platform'
                value['revision'] += 1
                self._write_profiles(value)
            return self.status()
