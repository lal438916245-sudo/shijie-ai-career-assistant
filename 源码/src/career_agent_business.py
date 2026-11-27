"""Career tools backed by the existing validated, one-dispatch business runtime."""
from contextlib import closing
import hashlib
import json
import uuid

from competition_workbench import WorkbenchError, WorkbenchConflict
from model_preparation import PreparationError


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class CareerBusiness:
    def __init__(self, agent, token, run_id=None):
        self.agent, self.token, self.run_id = agent, token, run_id
        self.workbench = agent.workbench

    def get(self, key):
        with self.agent.guard, closing(self.agent._open(self.token)) as conn:
            row = conn.execute('SELECT payload FROM business_operations WHERE operation_key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def put(self, key, value, kind='internal'):
        with self.agent.guard, closing(self.agent._open(self.token)) as conn, conn:
            conn.execute('INSERT INTO business_operations VALUES(?,?,?) ON CONFLICT(operation_key) DO UPDATE SET payload=excluded.payload',
                         (key, kind, json.dumps(value, ensure_ascii=False)))

    def mutate(self, operation, extra=None, *, key):
        identity = 'mutation:' + operation + ':' + key
        saved = self.get(identity)
        if saved is None:
            saved = {'request_id': str(uuid.uuid4()), 'expected_revision': self.workbench.state(self.token)['revision'], **(extra or {})}
            self.put(identity, saved)
        found = self.workbench.request_status(self.token, saved['request_id'])
        if found['found']:
            return found['receipt']
        return self.workbench.mutate(self.token, operation, saved)

    def ready(self):
        if not self.agent.enabled or not self.agent.model.status().get('business_tools_supported', True):
            raise WorkbenchConflict('当前连接尚未开放业务工具，请升级平台连接或使用自己的工具调用模型。')
        state = self.workbench.state(self.token)
        runtime = state.get('session_runtime')
        if runtime:
            if runtime['execution_mode'] != 'real_model':
                raise WorkbenchConflict('当前会话是历史本地演练，请新建个人求职准备后使用业务智能体。')
            return state
        capabilities = state.get('runtime_capabilities') or {}
        if not capabilities.get('outbound_enabled') or not capabilities.get('model_configured'):
            raise WorkbenchConflict('当前业务模型连接未就绪，未派发请求。')
        limit = (capabilities.get('sponsored_gateway') or {}).get('session_budget_micro_cny', 1000000)
        self.mutate('session_runtime_open', {'execution_mode': 'real_model', 'budget_micro_cny': limit}, key='session-runtime')
        return self.workbench.state(self.token)

    def _receipt(self, stage, target):
        state = self.workbench.state(self.token)
        family = 'abf' if stage == 'a_diagnosis' else 'call'
        for entry in reversed((state.get('session_runtime') or {}).get('entries', [])):
            if entry['stage'] != stage or entry['status'] == 'released_unconsumed':
                continue
            receipt = getattr(self.workbench, family + '_status')(self.token, {'authorization_id': entry['authorization_id']})
            if (receipt.get('target_version') if family == 'abf' else receipt.get('target_id')) == target:
                return receipt
        return None

    def invoke(self, stage, target):
        state = self.ready()
        family = 'abf' if stage == 'a_diagnosis' else 'call'
        receipt = self._receipt(stage, target)
        if receipt is None:
            preview = getattr(self.workbench, family + '_preview')(self.token, {
                'request_id': str(uuid.uuid4()), 'expected_revision': state['revision'], 'stage': stage,
                **({'target_version': target} if family == 'abf' else {'target_id': target})})
            if preview.get('input_limit_exceeded'):
                raise WorkbenchConflict('业务资料超过输入上限，请精简后重试。')
            reserve = preview['session_runtime']['reserve_micro_cny']
            self.agent.check_budget(self.token, self.run_id, reserve)
            receipt = getattr(self.workbench, family + '_authorize')(self.token, {
                'preview_id': preview['preview_id'], 'request_digest': preview['request_digest'], 'accept_session_once': True})
        aid = receipt['authorization_id']
        if receipt['status'] == 'authorized':
            with self.workbench.lock, closing(self.workbench._connect(self.token)) as conn:
                _, request = (self.workbench._abf_row if family == 'abf' else self.workbench._call_row)(conn, aid)
            self.agent.reserve_business(self.token, self.run_id, aid, request['session_runtime']['reserve_micro_cny'])
            if self.agent._is_cancelled(self.token, self.run_id):
                raise PreparationError('本轮已停止，业务请求未派发。')
            try:
                receipt = getattr(self.workbench, family + '_execute')(self.token, {'authorization_id': aid})
            finally:
                self.agent.settle_business(self.token, aid)
        if receipt['status'] == 'response_saved':
            receipt = getattr(self.workbench, family + '_recover')(self.token, {'authorization_id': aid})
        if receipt['status'] != 'completed':
            return {'error': 'business_result_unavailable', 'stage': stage, 'authorization_id': aid,
                    'status': receipt['status'], 'errors': receipt.get('errors', []),
                    'message': '原调用及费用记录已保留，不自动重发；请调整后续任务或请用户核对。'}
        adoption = getattr(self.workbench, family + '_adoption_preview')(self.token, {'authorization_id': aid})
        return {'receipt': receipt, 'adoption': adoption}

    def apply(self, result):
        adoption, receipt = result['adoption'], result['receipt']
        if adoption.get('already_applied') or adoption.get('application_id'):
            return adoption.get('application') or adoption
        if not adoption['can_apply']:
            raise WorkbenchConflict('业务结果已过时或未通过采用条件，已保留原结果。')
        operation = 'abf_apply' if receipt['stage'] == 'a_diagnosis' else 'candidate_apply'
        # The user delegated A/E execution. D edits still require the user's explicit selection.
        local = self.workbench.agent_review
        local.actor = 'career_agent'
        try:
            return self.mutate(operation, {'authorization_id': receipt['authorization_id'],
                'candidate_digest': adoption['candidate_digest'], 'review_confirmed': True,
                **({} if operation == 'abf_apply' else {'selected_item_ids': []})}, key=receipt['authorization_id'])
        finally:
            local.actor = None

    def diagnose_job(self):
        state = self.ready()
        if state.get('diagnosis'):
            return {'reused': True, 'diagnosis': self.diagnosis_view(state['diagnosis']), 'next': '可生成简历草稿或开始模拟面试。'}
        result = self.invoke('a_diagnosis', 0)
        if result.get('error'):
            return result
        self.apply(result)
        self.put('diagnosis', {'authorization_id': result['receipt']['authorization_id']}, 'diagnosis')
        return {'saved': True, 'diagnosis': self.diagnosis_view(self.workbench.state(self.token)['diagnosis'])}

    @staticmethod
    def diagnosis_view(diagnosis):
        audit = diagnosis['audit']
        return {key: audit.get(key) for key in ('match_score', 'score_reason', 'gap_table', 'resume_evidence_summary')}

    def optimize_resume(self):
        state = self.ready()
        if not state.get('diagnosis'):
            return {'error': 'diagnosis_required', 'message': '请先调用diagnose_job完成岗位诊断。'}
        evidence = {'interviews': [{k: i[k] for k in ('interview_id', 'status', 'answered_count')}
                                  for i in state.get('interviews', []) if i['answered_count']],
                    'assessments': state.get('assessment_runs', []),
                    'progress': state.get('progress', [])}
        # Adopted interview feedback changes the available evidence even when answered_count stays fixed.
        records = self.workbench.records(self.token)['records']
        evidence['feedback_records'] = [r['record_id'] for r in records
                                        if r['kind'] == 'interview' and r['payload'].get('stage') == 'e_report']
        key = 'resume:' + digest(evidence)
        saved = self.get(key)
        if saved is None:
            base = self.mutate('resume_generate', key=key)
            saved = {'base_resume_id': base['resume_id']}
            self.put(key, saved, 'resume')
        result = self.invoke('d_revision', saved['base_resume_id'])
        if result.get('error'):
            return result
        saved.update(authorization_id=result['receipt']['authorization_id'])
        self.put(key, saved, 'resume')
        draft = self.resume_draft(saved)
        return {'generated': True, 'authorization_id': saved['authorization_id'],
                'items': draft['candidate']['items'], 'saved_resume_id': draft.get('saved_resume_id'),
                'requires_user_review': not bool(draft.get('saved_resume_id')),
                'notice': '草稿已生成并保留；用户可在智能体面板核对并保存，不能把建议认作新增经历。'}

    def start_mock_interview(self):
        state = self.ready()
        if not state.get('diagnosis'):
            return {'error': 'diagnosis_required', 'message': '请先调用diagnose_job完成岗位诊断。'}
        saved = self.get('interview-start:' + self.run_id)
        active = next((i for i in state.get('interviews', []) if i['status'] == 'active'), None)
        if not active:
            for previous in state.get('interviews', []):
                if previous['status'] != 'active' and previous['answered_count']:
                    view = self.interview_view(previous['interview_id'])
                    if (view.get('report') or {}).get('review_status') == 'pending_candidate_review':
                        return {'error': 'interview_review_required', 'interview_id': previous['interview_id'],
                                'message': '先调用review_mock_interview处理已提交回答的面试，再开始新面试。'}
        iid = active['interview_id'] if active else saved.get('interview_id') if saved else None
        if iid is None:
            created = self.mutate('interview_start', {'mode': 'short', 'include_learning_evidence': False}, key=self.run_id)
            iid = created['interview_id']
        self.put('interview-start:' + self.run_id, {'interview_id': iid})
        interview = self.workbench.interview(self.token, iid)['interview']
        if interview['status'] != 'active':
            return {'interview_id': iid, 'status': interview['status'], 'message': '本轮面试已结束，请调用review_mock_interview读取复盘。'}
        if not (interview.get('current_question') or {}).get('model_application'):
            result = self.invoke('e_turn', iid)
            if result.get('error'):
                return result
            self.apply(result)
        self.put('interview:' + iid, {'interview_id': iid}, 'interview')
        return self.interview_view(iid)

    def review_mock_interview(self, interview_id):
        self.ready()
        interview = self.workbench.interview(self.token, interview_id)['interview']
        if interview['status'] == 'active':
            return {**self.interview_view(interview_id), 'error': 'user_answer_required',
                    'message': '必须等待用户在界面提交真实回答，不能代答或虚构作答。'}
        if not any(turn['role'] == 'user' for turn in interview['turns']):
            return {'error': 'user_answer_required', 'message': '本场面试没有用户回答，不能生成作答评价。'}
        if (interview.get('report') or {}).get('review_status') == 'pending_candidate_review':
            result = self.invoke('e_report', interview_id)
            if result.get('error'):
                return result
            self.apply(result)
        self.put('interview:' + interview_id, {'interview_id': interview_id}, 'interview')
        return self.interview_view(interview_id)

    def record_answer(self, answer):
        # This method is called only with a persisted HTTP user input, never from the model's tool arguments.
        result = self.mutate('interview_answer', answer, key='user-answer:' + self.run_id)
        return {'recorded': True, 'interview_id': answer['interview_id'], 'answer_turn_id': result['answer_turn_id'],
                'next': '请调用review_mock_interview评价本次真实回答，再据结果调整并保存任务。'}

    def interview_view(self, iid):
        interview = self.workbench.interview(self.token, iid)['interview']
        question = interview.get('current_question')
        return {'interview_id': iid, 'status': interview['status'],
                'waiting_for_user': bool(question and question.get('model_application')),
                'question': {'turn_id': question['turn_id'], 'text': question['text']} if question and question.get('model_application') else None,
                'report': interview.get('report'),
                'answered_count': sum(t['role'] == 'user' for t in interview['turns'])}

    def resume_draft(self, saved):
        preview = self.workbench.call_adoption_preview(self.token, {'authorization_id': saved['authorization_id']})
        formal_id = preview.get('formal_resume_id')
        return {'authorization_id': saved['authorization_id'], 'base_resume_id': saved['base_resume_id'],
                'original_text': self.workbench.state(self.token)['candidate']['resume_text'],
                'candidate': preview['candidate'], 'selectable_item_ids': preview['selectable_item_ids'],
                'can_apply': preview['can_apply'], 'saved_resume_id': formal_id,
                'saved_text': self.workbench.resume(self.token, formal_id)['report']['final_draft'] if formal_id else None}

    def accept_resume(self, body):
        if not isinstance(body, dict) or set(body) != {'request_id', 'authorization_id', 'selected_item_ids'}:
            raise WorkbenchError('请核对并选择简历修改。')
        with self.agent.guard:
            if self.agent.running:
                raise WorkbenchConflict('请在智能体结束本轮后保存简历。')
        with closing(self.agent._open(self.token)) as conn:
            saved = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM business_operations WHERE kind='resume'")]
        if not any(r.get('authorization_id') == body['authorization_id'] for r in saved):
            raise WorkbenchConflict('这份草稿不属于当前智能体会话。')
        preview = self.workbench.call_adoption_preview(self.token, {'authorization_id': body['authorization_id']})
        if preview.get('application_id'):
            return
        if not preview['can_apply']:
            raise WorkbenchConflict('草稿来源已变化，请保留原文并重新生成。')
        self.workbench.mutate(self.token, 'candidate_apply', {
            'request_id': body['request_id'], 'expected_revision': self.workbench.state(self.token)['revision'],
            'authorization_id': body['authorization_id'], 'candidate_digest': preview['candidate_digest'],
            'review_confirmed': True, 'selected_item_ids': body['selected_item_ids']})

    def snapshot(self, state=None):
        with closing(self.agent._open(self.token)) as conn:
            rows = [(r[0], json.loads(r[1])) for r in conn.execute(
                "SELECT kind,payload FROM business_operations WHERE kind IN ('resume','interview') ORDER BY rowid DESC")]
        draft = next((value for kind, value in rows if kind == 'resume' and value.get('authorization_id')), None)
        iid = next((value['interview_id'] for kind, value in rows if kind == 'interview'), None)
        interviews = (state if state is not None else self.workbench.state(self.token)).get('interviews', [])
        current = next((i for i in interviews if i['status'] == 'active'), None)
        if current:
            iid = current['interview_id']
        elif iid is None and interviews:
            iid = interviews[0]['interview_id']
        return {'resume_draft': self.resume_draft(draft) if draft else None,
                'interview': self.interview_view(iid) if iid else None}
