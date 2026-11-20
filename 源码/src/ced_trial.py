"""Isolated, five-slot DeepSeek C/E/D acceptance trial."""
from contextlib import closing
from decimal import Decimal, ROUND_CEILING
import json
from uuid import uuid4

from ced_contracts import STAGES
from competition_workbench import CompetitionWorkbench, WorkbenchMissing, digest, expect
from competition_workbench_assessment import encode
from competition_workbench_calls import FixedCEDTransport
from sdk_transport import SDKTransport

# Peak, uncached CNY per million tokens, verified against DeepSeek's CNY
# pricing. Never take a lower price from the saved settings.
INPUT_RATE = Decimal('2')
OUTPUT_RATE = Decimal('8')
MICRO = Decimal(1000000)
TRIAL_DATE = '2026-11-05'
STAGE_OUTPUT_LIMIT = 4096


def micro_cny(amount):
    return int((Decimal(amount) * MICRO).to_integral_value(rounding=ROUND_CEILING))


class TrialTransport(FixedCEDTransport):
    mode = 'ced_trial'
    kind = 'ced_trial_sdk'

    def __init__(self, preparation, *, enabled=False, http_client_factory=None):
        self.preparation = preparation
        self.enabled = enabled
        self.http_client_factory = http_client_factory

    def send(self, request):
        sdk = SDKTransport(self.preparation, rehearsal=False, outbound_enabled=self.enabled,
                           http_client_factory=self.http_client_factory)
        sdk_request = {**request, 'sdk_policy': {'rehearsal': False},
                       'timeout_seconds': request['config']['timeout_seconds']}
        return sdk.send(sdk_request, None, None)


class CEDTrial(CompetitionWorkbench):
    def __init__(self, directory, transport, budget_micro, *, d_thinking='disabled', d_output_limit=4096, case_profile='legacy'):
        from ced_output_control import MODES
        if d_thinking not in MODES or type(d_output_limit) is not int or not 256<=d_output_limit<=4096:
            raise ValueError('D思考模式或输出上限无效')
        self.d_thinking=d_thinking;self.d_output_limit=d_output_limit
        self.trial_budget = budget_micro
        self.preparation = transport.preparation
        super().__init__(directory, call_transport=transport, call_configuration=self.configuration, case_profile=case_profile)

    def configuration(self):
        with self.preparation.lock:
            return self.preparation._read()

    def _d_output_control(self, settings):
        from ced_output_control import d_controls
        return d_controls(settings,thinking_mode=self.d_thinking,output_limit=self.d_output_limit)

    def _call_request(self, c, meta, stage, target):
        request = super()._call_request(c, meta, stage, target)
        config = request['config']
        expect(config['provider'].casefold() == 'deepseek' and config['currency'] == 'CNY'
               and config['base_url'] in ('https://api.deepseek.com','https://api.deepseek.com/v1')
               and config['model'] == 'deepseek-flash' and config['output_token_parameter'] == 'max_tokens',
               '本轮验收只支持已核对的 DeepSeek Flash 人民币配置。')
        return request

    def _call_request_policy(self, request):
        config = request['config']
        output = min(config['max_output_tokens'], STAGE_OUTPUT_LIMIT, request.get('output_control',{}).get('max_output_tokens',STAGE_OUTPUT_LIMIT))
        request['payload']['max_tokens'] = output
        rates = (max(INPUT_RATE, Decimal(str(config['input_price_per_million'] or 0))),
                 max(OUTPUT_RATE, Decimal(str(config['output_price_per_million'] or 0))))
        # UTF-8 byte count plus framing allowance is deliberately much larger
        # than the rough display estimate, but is still a local estimate.
        prompt_bound = len(encode(request['payload']).encode('utf-8')) + 512
        reserve = int((prompt_bound*rates[0] + output*rates[1]).to_integral_value(rounding=ROUND_CEILING))
        return {'trial_budget_micro_cny': self.trial_budget, 'reserve_micro_cny': reserve,
                'input_token_allowance': prompt_bound, 'trial_rates': [str(rate) for rate in rates]}

    def _trial_consumed(self, c):
        rows = c.execute('SELECT p.request_json,p.request_digest,g.response_json,g.response_digest FROM wbc_grants g JOIN wbc_previews p USING(preview_id) WHERE g.dispatch_count>0')
        consumed = {}
        for row in rows:
            request = json.loads(row['request_json'])
            expect(digest(request)==row['request_digest'] and request['mode']=='ced_trial'
                   and request['stage'] not in consumed, '本轮费用账本校验失败。')
            response = json.loads(row['response_json']) if row['response_json'] else {}
            if row['response_json']:
                expect(digest(response)==row['response_digest'],'本轮用量回执校验失败。')
            usage = response.get('usage')
            charge = 0
            if usage:
                input_rate, output_rate = map(Decimal,request['trial_rates'])
                charge = int((usage['prompt_tokens']*input_rate + usage['completion_tokens']*output_rate).to_integral_value(rounding=ROUND_CEILING))
            consumed[request['stage']] = max(request['reserve_micro_cny'],charge)
        return consumed

    def _call_check_authorization(self, c, request):
        expect(self.call_transport.enabled, '真实外发尚未启用，当前只能预览。')
        expect(self.configuration()['encrypted_key'], '本机尚未保存 API Key。')
        consumed = self._trial_consumed(c)
        expect(request['stage'] not in consumed, '该操作已消费一次，请查原回执。')
        expect(sum(consumed.values())+request['reserve_micro_cny']<=self.trial_budget,
               '本轮剩余预算不足，未发送。')

    def call_preview(self, token, body):
        result = super().call_preview(token, body)
        with closing(self._connect(token)) as conn:
            row = conn.execute('SELECT request_json FROM wbc_previews WHERE preview_id=?',(result['preview_id'],)).fetchone()
            request = json.loads(row[0])
            consumed = self._trial_consumed(conn)
        input_rate, output_rate = map(Decimal, request['trial_rates'])
        output = request['payload']['max_tokens']
        result.update(run_mode='ced_trial', simulated=self.call_transport.http_client_factory is not None,
                      real_dispatch_enabled=self.call_transport.enabled and self.call_transport.http_client_factory is None,
                      external_network_allowed=self.call_transport.enabled and self.call_transport.http_client_factory is None,
                      max_output_tokens=output, estimated_cost=float((result['estimated_input_tokens']*input_rate+output*output_rate)/MICRO),
                      reserve_micro_cny=request['reserve_micro_cny'], trial_budget_micro_cny=self.trial_budget,
                      already_reserved_micro_cny=sum(consumed.values()), stage_consumed=body['stage'] in consumed,
                      input_token_allowance=request['input_token_allowance'],
                      notice='请核对下方将发送的虚构资料及单次预算。',
                      cost_notice='费用按配置与已核对高峰单价中的较高值计算，扣费以服务商账单为准。')
        return result

    def _call_view(self, row, request):
        value = super()._call_view(row, request)
        simulated = self.call_transport.http_client_factory is not None
        response = json.loads(row['response_json']) if row['response_json'] else {}
        usage = response.get('usage')
        rates = list(map(Decimal, request['trial_rates']))
        billed_estimate = float((usage['prompt_tokens']*rates[0]+usage['completion_tokens']*rates[1])/MICRO) if usage and not simulated else None
        value.pop('fixed_dispatch_attempts')
        value.update(run_mode='ced_trial', simulated=simulated, model_requests=0 if simulated else row['dispatch_count'],
                     real_dispatch_enabled=self.call_transport.enabled and not simulated,
                     external_network_allowed=self.call_transport.enabled and not simulated,
                     provider_request_attempted=None if not simulated and value['consumed'] and not response else bool(response) and not simulated,
                     dispatch_attempts=row['dispatch_count'], usage=usage,
                     reserve_micro_cny=request['reserve_micro_cny'], estimated_usage_cost=billed_estimate,
                     actual_model_cost=0 if simulated or not value['consumed'] else None,
                     notice='独立验收回执。通过合同的结果保留为待人工核对的候选。')
        if value['result'] and request['stage']=='c_grade':
            value['result']['notice']='验收候选评分，保留在独立回执中。'
        return value


def prepare_trial_fixture(service, token):
    """Seed the acceptance DB entirely from the bundled case and scripted answers."""
    try:
        service.state(token)
    except WorkbenchMissing:
        service.create(token, {'request_id':str(uuid4()), 'start_date':TRIAL_DATE})
    target_file = service.directory.parent / 'synthetic-targets.json'
    if target_file.exists():
        targets = json.loads(target_file.read_text(encoding='utf-8'))
        expect(set(targets)==set(STAGES), '虚构样例索引损坏。')
        return targets

    def act(operation, **fields):
        state = service.state(token)
        return service.mutate(token,operation,{'request_id':str(uuid4()),'expected_revision':state['revision'],**fields})

    expect(service.state(token)['revision']==0, '样例初始化曾中断，请核对本机验收目录。')
    act('diagnosis')
    act('plan')
    act('review',plan_version=1)
    act('adopt',plan_version=1,review_id=service.state(token)['review']['review_id'])
    act('review',plan_version=2)
    act('publish',plan_version=2)
    options = service.assessment_options(token,'day',TRIAL_DATE,TRIAL_DATE)['options']
    exam = dict(plan_version=2,kind='day',period_start=TRIAL_DATE,period_end=TRIAL_DATE,
                task_ids=[task['task_id'] for task in options['tasks']],fixture_path='repair')
    run_id = act('assessment_start',**exam)['run_id']
    question = service.assessment(token,run_id)['run']['question']
    attempt = act('answer',run_id=run_id,question_id=question['question_id'],
                  answer='我先确认订单和明细表的粒度，再用样本检查一对多是否放大金额。')['attempt_id']
    act('assessment_end',run_id=run_id)
    turn_id = act('interview_start',mode='quick',include_learning_evidence=True)['interview_id']
    # Capture one answered turn for review and use the other independent
    # interview's next slot as the source for question generation.
    interview = service.interview(token,turn_id)['interview']
    act('interview_answer',interview_id=turn_id,question_turn_id=interview['current_question']['turn_id'],
        answer='在课程练习里，我用三笔虚构订单对比输入和输出，并单独检查退款和重复行。')
    if service.interview(token,turn_id)['interview']['status']=='active':
        act('interview_end',interview_id=turn_id)
    next_turn = act('interview_start',mode='quick',include_learning_evidence=True)['interview_id']
    next_run = act('assessment_start',**exam)['run_id']
    resume = act('resume_generate')['resume_id']
    targets = dict(c_question=next_run,c_grade=attempt,e_turn=next_turn,e_report=turn_id,d_revision=resume)
    target_file.write_text(encode(targets),encoding='utf-8')
    return targets
