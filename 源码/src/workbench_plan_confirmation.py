"""Competition publication: inspectable program checks, then explicit consent.

Historical F reviews and publication receipts remain immutable. This does not
replace semantic review or certify that the user has learned a skill.
"""
from contextlib import closing
from copy import deepcopy
import json

VERSION = 'program-confirm-v1'
OPERATIONS = {'plan_prepare': set(), 'plan_confirm_publish': {'plan_version', 'plan_digest', 'validation_digest', 'review_confirmed'}}


class WorkbenchPlanConfirmation:
    def _do_plan_prepare(self, c, meta, body):
        return self._do_plan(c, meta, body, competition_policy=True)

    def _program_plan_check(self, c, meta, version):
        from competition_workbench import expect, digest, WorkbenchError
        from competition_case import CaseContractError, resolve_selection
        from abf_contracts import mandatory_findings
        from workbench_learning_cards import follow_along_card
        expect(type(version) is int and version == meta['active_version'], '请核对当前计划版本，历史版本不能重新发布。')
        saved = self._plan(c, version)
        plan = saved['plan']
        checks = []

        def check(code, label, action):
            try:
                result = action()
                checks.append({'code': code, 'label': label, 'passed': True, 'detail': result})
            except (WorkbenchError, CaseContractError, ValueError, KeyError, TypeError, OSError) as exc:
                # Public diagnostics only; never include raw model/provider errors.
                detail = str(exc) if isinstance(exc, WorkbenchError) else '所需学习卡、资料或字段未通过完整性检查，请保留草案并核对。'
                checks.append({'code': code, 'label': label, 'passed': False, 'detail': detail})

        def bindings():
            self._validate_plan(plan, meta)
            expect(digest(plan) == saved['plan_digest'], '计划内容与保存摘要不一致。')
            return '当前简历/JD、诊断差距、任务与资料绑定一致。'

        def time_and_boundary():
            from competition_workbench_fixtures import budget_total
            expect(all(budget_total(t['budget']) <= 60 for t in plan['tasks']), '有任务超过每天60分钟，请先调整草案。')
            findings = mandatory_findings(plan, meta['diagnosis'])
            expect(not findings, '；'.join(f'{tid}：{message}' for tid, _, message in findings))
            return '每天最多60分钟；收尾不叠加，未提供证据不写成确认不会。'

        def materials():
            cards = []
            for task in plan['tasks']:
                card = deepcopy(meta['package']['card']) if task['task_template_id'] == 'CP-T01' else follow_along_card(meta['package'], task)
                exercise = card['exercise']
                expect(bool(card['concepts']) and bool(card['worked_example']) and
                       all(bool(exercise.get(k)) for k in ('prompt', 'reference_answer', 'hints', 'checkpoints')) and
                       bool(card.get('prerequisites')) and bool(card.get('fallback')), f"{task['task_template_id']} 缺少完整的零基础引导、示例或自查。")
                resolved = resolve_selection(meta['package']['catalog'], task['resource_selection'], task['topic_keys'])
                expect(resolved['state'] == 'verified_primary', f"{task['task_template_id']} 的主资料需要核对。")
                cards.append({'task_id': task['task_id'], 'card_digest': digest(card), 'resource_digest': digest(resolved)})
            return cards

        check('bindings', '任务、诊断与资料来源', bindings)
        check('time_boundary', '60分钟安排与证据边界', time_and_boundary)
        check('starter_materials', '概念、示例、练习、答案和自查齐全', materials)
        report = {'policy': VERSION, 'scope': self._scope(meta), 'input_digest': meta['input_digest'],
                  'plan_version': version, 'plan_digest': saved['plan_digest'], 'checks': checks,
                  'can_publish': all(x['passed'] for x in checks),
                  'notice': '程序只检查结构、来源和已知规则，不证明教学效果或能力提升。请查看每日任务，确认难度与起步条件适合自己。F实验审查不再是发布前置条件。'}
        return {**report, 'validation_digest': digest(report)}

    def plan_check(self, token, body):
        from competition_workbench import require_fields
        require_fields(body, {'plan_version'})
        with self.lock, closing(self._connect(token)) as c:
            meta = self._context(c, self._meta(c))
            return self._session_container(c, meta, self._reply(**self._program_plan_check(c, meta, body['plan_version']), new_model_requests=0))

    def _do_plan_confirm_publish(self, c, meta, body):
        from competition_workbench import expect
        self._active(meta, body)
        expect(meta['published_version'] is None, '这份计划已发布，请读取原确认记录。')
        expect(body['review_confirmed'] is True, '请先查看计划并明确确认学习安排。')
        check = self._program_plan_check(c, meta, body['plan_version'])
        expect(check['can_publish'], '程序校验尚未全部通过，草案保留，暂未发布。')
        expect(body['plan_digest'] == check['plan_digest'] and body['validation_digest'] == check['validation_digest'], '计划或学习材料已变化，请重新校验并确认。')
        plan = self._plan(c, body['plan_version'])
        rid = meta['session_id'] + ':published:' + str(body['plan_version'])
        payload = {'event': 'published', 'version': body['plan_version'], 'plan_digest': plan['plan_digest'],
                   'publication_policy': VERSION, 'user_confirmed': True, 'program_check': check}
        self._record(c, meta, rid, 'plan', '程序校验通过 · 用户确认发布学习计划', payload, [plan['record_id']])
        c.execute('UPDATE wb_meta SET published_version=? WHERE singleton=1', (body['plan_version'],))
        return {'record_id': rid, 'plan_version': body['plan_version'], 'publication_policy': VERSION, 'new_model_requests': 0}

    def _program_publication_validate(self, c, meta):
        from competition_workbench import expect, digest
        published = meta['published_version']
        for row in c.execute("SELECT record_id,payload_json,parent_ids_json FROM wb_records WHERE kind='plan'"):
            value = json.loads(row['payload_json'])
            parents = json.loads(row['parent_ids_json'])
            if row['record_id'].startswith(meta['session_id'] + ':published:'):
                expect(value.get('event') == 'published', '计划发布事件标识缺失，请保留会话并核对备份。')
            if row['record_id'].startswith(meta['session_id'] + ':published:') and len(parents) == 1:
                expect(value.get('publication_policy') == VERSION, '程序发布记录的策略标识缺失，请保留会话并核对备份。')
            if value.get('publication_policy') != VERSION:
                continue  # Immutable historical F-based receipts retain their own provenance.
            plan = self._plan(c, value.get('version'))
            check = value.get('program_check', {})
            frozen = {k: v for k, v in check.items() if k != 'validation_digest'}
            expect(value.get('event') == 'published' and value.get('user_confirmed') is True and
                   value.get('version') == published and row['record_id'] == meta['session_id'] + ':published:' + str(published) and
                   json.loads(row['parent_ids_json']) == [plan['record_id']] and
                   value.get('plan_digest') == plan['plan_digest'] == digest(plan['plan']) and
                   check.get('policy') == VERSION and check.get('plan_version') == published and
                   check.get('scope') == self._scope(meta) and check.get('input_digest') == meta['input_digest'] and
                   check.get('plan_digest') == plan['plan_digest'] and check.get('can_publish') is True and
                   len(check.get('checks', [])) == 3 and all(x.get('passed') is True for x in check['checks']) and
                   check.get('validation_digest') == digest(frozen), '计划发布的程序校验或用户确认记录不完整，请保留会话并核对备份。')
        if published is not None:
            expect(c.execute('SELECT 1 FROM wb_records WHERE record_id=?', (meta['session_id'] + ':published:' + str(published),)).fetchone(), '已发布计划的确认记录缺失，请保留会话并核对备份。')
