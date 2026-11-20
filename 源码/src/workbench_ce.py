"""C/E per-slot local rehearsal with a durable session-wide simulation budget.

Only in-process synthetic responses; no SDK, saved provider settings or Key reads.
Reservations are immutable. Expired unused grants release holds, consumed grants never reset.
"""
from copy import deepcopy
from contextlib import closing
import json,math
from competition_workbench_assessment import encode,digest,expect,invalid
from competition_workbench_calls import FixedCEDTransport
from model_preparation import DEFAULT
from ced_contracts import VERSION as CED_VERSION,payload,validate_result,fixed_output,CEDValidation

VERSION='ce-session-budget-v1'
STAGES=('c_question','c_grade','e_turn','e_report')
CE_OPERATIONS={'ce_budget_open':{'simulation_limit_micro_cny'}}

QUESTIONS={
 'sql':[
  ('体检机构要保留全部预约，包括没有缴费的预约。缴费记录可能拆分和退款，怎样按预约编号核对每单实付并找出缺失与重复记录？','先按预约编号归并缴费和退款，再从预约主表保留全部预约，逐笔对照实付与缺失记录。'),
  ('某项目同时关联工时明细和验收记录，两边都可能多行。怎样统计每个项目的工时与验收次数，避免两组明细相互放大？','两组明细分别按项目编号汇总，再关联项目；对照单边汇总与最终指标，不直接连接两组明细后累加。'),
  ('应急车辆一天内可执行多次任务，每次任务又有多个GPS点。怎样统计各车任务数，并保留当天未执行任务的车辆？','以任务编号统计任务，先将GPS点归并到任务再关联车辆；保留车辆全集，核对空任务和重复任务。'),
  ('课程允许同一学生多次补考。怎样为每份选课记录选出最近一次考试结果，时间相同又如何保证唯一，并保留未考试的选课？','按选课编号分组，考试时间与考试编号共同排序取唯一最新记录，再关联全部选课；核对并列时间和未考试行。'),
  ('医院药品表记录品种，药房批次表记录库存。调入一批已售空药品后，哪些品种数和库存指标应改变，怎样用小样本验证查询？','先区分品种和批次粒度；按品种汇总批次库存，分别核对品种计数、零库存和缺批次情况。'),
  ('公交线路有上下行班次，每个班次可能多次刷卡。怎样比较线路实际发车数和乘车人次，并排查重复上报班次导致的统计异常？','班次按业务编号核对唯一性，刷卡按乘车事件统计；分别聚合并检查重复上报和无乘客班次。'),
  ('工单可能同时有评论和标签。怎样计算每个服务组的工单数及评论数，并证明增加一个标签不应改变评论指标？','评论先按工单编号汇总，标签用存在性判断或独立集合；加入重复标签反例，核对工单与评论指标保持不变。'),
  ('员工基础工资与报销明细放在两张表中。怎样汇总部门应付金额，保留没有报销的员工，并核对工资没有因多笔报销重复计入？','报销先按员工编号汇总，再关联员工及部门；基础工资每员工只计一次，核对无报销与多报销员工。'),
  ('食堂采购订单允许分批收货。若验收只通过一部分，怎样查询尚未收齐的订单，并检查空收货和重复收货记录？','先按采购订单汇总通过验收的收货数量，再保留全部采购订单比较应收与实收，核对空值和重复单据。'),
  ('档案目录存在分类与子分类，怎样查找没有有效归档文件的末级分类，并验证软删除文件不被算作有效文件？','明确末级分类集合，用不存在有效文件的条件筛选；对照软删除、空分类和多份文件边界。'),
  ('社区居民每月可有多次健康随访。怎样查询连续两月均无随访的居民，并避免把重复随访当成多个月份？','先把居民与月份归并，构造两月范围检查缺失；保留居民主表，核对月份边界和重复事件。'),
  ('设备运行时长按日保存，维修事件不定期发生。怎样计算每次维修前最近三天的运行时长，并核对缺一天数据的情况？','以设备和维修事件为目标粒度，按日期范围关联每日运行汇总，逐事件核对三天窗口与缺失日期。'),

 ],
 'stream':[
  ('工厂设备离线后补发故障读数，读数落在已经关闭的统计窗口。应记录哪些时间，如何决定丢弃、侧输出还是补算，并核对结果？','区分设备事件时间和收到时间，依据水位线及允许迟到规则处理，核对补算前后结果与重复读数。'),
  ('快递轨迹到达顺序颠倒，还会重复上报。按小时统计实际发生的揽收事件时，窗口、去重与重放验证应怎样安排？','按业务事件时间分窗，用事件编号去重，设置乱序与迟到边界，对照重放后的统计。'),
  ('任务恢复后从较早位置重放数据，下游文件却已写入一部分。怎样验证检查点和输出提交的边界，而不是只确认任务能重启？','构造恢复点前后数据，核对重放范围和输出幂等性，逐笔检查重复与遗漏，保留验证条件。'),
 ],
 'model':[
  ('退货申请可能拆为多次入库，一次入库也有多件商品。统计退货申请数和实际入库件数应如何定义事实粒度并验证？','分别以申请和入库明细定义粒度，按业务键关联并分别聚合，检查拆分、空明细与重复键。'),
  ('会员等级变更保留历史版本，消费事件引用当时等级。应如何定义有效期和唯一匹配，并用边界日期检查归属？','明确事件粒度和等级有效期，检查区间交界及重叠，每笔消费只匹配一个历史版本。'),
  ('课程报名表的唯一键从学生号改为学生号加课程号。怎样验证模型变化没有丢失同一学生的多门课程？','按报名事件定义复合键，检查唯一性和空值，对照变更前后课程与学生两个口径的数量。'),
 ],
 'engineering':[
  ('门禁事件提交超时后客户端重试。怎样构造最小复现、断言最终记录唯一，并用日志区分两次执行和同一业务事件？','固定业务事件编号，记录独立执行编号和阶段，模拟提交超时，对照落库状态与重复遗漏。'),
  ('批量导入部分成功后重跑，怎样组织正常、空输入和部分失败用例，并证明恢复不会覆盖已经确认的记录？','分别定义输入、预期输出和失败点，核对已提交与待处理记录，记录可重现步骤及版本。'),
  ('指标报警后总量正常但部分明细缺失，应先看哪些对照数据和日志，如何验证修复而不是仅关闭报警？','按业务键逐笔比对输入输出，沿关联编号定位阶段，构造最小缺失样本并重跑验证。'),
 ]}

class LocalCETransport:
    mode='ce_local_rehearsal'
    def send(self,request):
        if request['stage']=='c_question':
            topics=request['context']['topic_keys'];result=None
            for index in range(max(len(QUESTIONS[t]) for t in topics)):
                parts=[QUESTIONS[t][index%len(QUESTIONS[t])] for t in topics]
                candidate={'contract_version':CED_VERSION,'prompt':' '.join(v[0] for v in parts),'reference_outline':' '.join(v[1] for v in parts)}
                try:validate_result(request,encode(candidate));result=candidate;break
                except CEDValidation:continue
            if result is None:raise CEDValidation('local_question_pool_exhausted')
        else:result=fixed_output(request)
        content=encode(result)
        usage={'prompt_tokens':math.ceil(len(encode(request['payload']))/2),'completion_tokens':math.ceil(len(content)/2)}
        usage['total_tokens']=sum(usage.values())
        return {'content':content,'finish_reason':'stop','usage':usage}

class WorkbenchCE:
    def _init_ce(self,transport=None):
        self.ce_transport=transport or LocalCETransport()
        if not isinstance(self.ce_transport,LocalCETransport) or self.ce_transport.mode!='ce_local_rehearsal':
            raise ValueError('C/E会话预算只支持本地替身。')

    @staticmethod
    def _has_ce(c):return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wce_policy'").fetchone())

    def _ce_policy(self,c,meta):
        if not self._has_ce(c):return None
        row=c.execute('SELECT policy_json,policy_digest FROM wce_policy WHERE singleton=1').fetchone()
        expect(row is not None,'C/E预算策略缺失。');p=json.loads(row[0])
        expect(digest(p)==row[1] and p['version']==VERSION and p['scope']==self._scope(meta)
            and p['input_digest']==meta['input_digest'] and p['mode']=='ce_local_rehearsal'
            and type(p['simulation_limit_micro_cny']) is int and p['simulation_limit_micro_cny']>0
            and p['input_rate']==2 and p['output_rate']==8,'C/E累计预算来源不符。')
        return p

    def _do_ce_budget_open(self,c,meta,body):
        limit=body['simulation_limit_micro_cny']
        expect(type(limit) is int and 0<limit<=100000000,'请填写有效的本地演练预算，单位为微元。')
        expect(self.case_profile=='final-20261107' and self.call_transport.mode=='ced_fixed_rehearsal'
               and self._has_abf(c) and meta['published_version'] is not None,'请先采用A/B结果，并在当前会话确认发布学习计划；旧真实验收器不接入本预算。')
        expect(not self._has_ce(c),'本会话已有累计预算，不能通过重开清零或扩额。')
        for table in ('wba_runs','wbi_runs'):
            expect(not c.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone() or c.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,
                   '请在第一场考核/面试之前开启累计预算；本批不把旧固定练习改成新的候选流程。')
        expect(not c.execute("SELECT 1 FROM sqlite_master WHERE name='wbc_grants'").fetchone()
               or c.execute('SELECT count(*) FROM wbc_grants').fetchone()[0]==0,'已有旧C/E/D授权，请保留原账本；本批不混入未计预算的历史调用。')
        p={'version':VERSION,'mode':'ce_local_rehearsal','scope':self._scope(meta),'input_digest':meta['input_digest'],
           'simulation_limit_micro_cny':limit,'input_rate':2,'output_rate':8,
           'pricing_notice':'固定模拟单价与用量，仅验证预算控制；不代表账单或真实调用授权。'}
        c.execute('CREATE TABLE wce_policy(singleton INTEGER PRIMARY KEY CHECK(singleton=1),policy_json TEXT NOT NULL,policy_digest TEXT NOT NULL,record_id TEXT NOT NULL)')
        c.execute('CREATE TABLE wce_reservations(authorization_id TEXT PRIMARY KEY,stage TEXT NOT NULL,slot_key TEXT NOT NULL,request_digest TEXT NOT NULL,reserve_micro_cny INTEGER NOT NULL)')
        rid=meta['session_id']+':ce-budget'
        c.execute('INSERT INTO wce_policy VALUES (1,?,?,?)',(encode(p),digest(p),rid))
        self._record(c,meta,rid,'plan_review','C/E · 开启同会话模拟预算',{'event':'ce_budget_open','policy':p},[self._plan(c,meta['published_version'])['record_id']])
        return {'budget_policy_digest':digest(p),'mode':'ce_local_rehearsal','actual_model_cost':0,'external_network_allowed':False}

    def _ce_context(self,c,meta,stage,ctx):
        if not self._has_ce(c):return ctx
        if stage=='c_question' and ctx['question_rules'].get('experience_policy')!='single-feedback-v1':
            avoided=ctx['question_rules']['avoid_prompts']
            avoided+= [a['question']['prompt'] for a in self._answer_rows(c,meta) if set(ctx['topic_keys']).intersection(a['topic_keys'])]
            ctx['question_rules']['avoid_prompts']=list(dict.fromkeys(avoided))
            expect(len(ctx['question_rules']['avoid_prompts'])<=64,'相关题目历史过长，请先核对出题范围；不会静默丢弃禁用题面。')
        return ctx

    def _ce_request(self,c,meta,stage,target):
        p=self._ce_policy(c,meta)
        if p is None:return None
        expect(stage in STAGES,'本轮累计预算仅支持C/E；D调用和其他模型步骤须另行准备，不能生成未计预算的授权。')
        ctx=self._call_context(c,meta,stage,target)
        settings={**deepcopy(DEFAULT),'provider':'本地C/E预算替身','model':'local-ce-double','base_url':'local://ce-budget',
                  'max_output_tokens':4096,'max_input_chars':40000,'input_price_per_million':2,'output_price_per_million':8,'currency':'CNY'}
        req={'contract_version':CED_VERSION,'mode':'ced_fixed_rehearsal','stage':stage,'target_id':target,
             'scope':self._scope(meta),'revision':meta['revision'],'context':ctx,'config_revision':0,
             'config':settings,'key_slot_digest':None,'boot_id':self.call_boot_id,'transport_kind':'in_process_fixed',
             'automatic_retries':0,'payload':payload(stage,ctx,settings)}
        if hasattr(self.ce_transport,'freeze'):req=self.ce_transport.freeze(req)
        allowance=len(encode(req['payload']).encode('utf-8'))+512
        req['ce_policy']={'version':VERSION,'policy_digest':digest(p),'slot_key':self._adoption_key(req),
                         'input_token_allowance':allowance,'reserve_micro_cny':allowance*2+4096*8}
        return req

    def _ce_validate_entry(self,c,meta,reservation,grant,request):
        p=self._ce_policy(c,meta);frozen=request.get('ce_policy',{})
        allowance=len(encode(request['payload']).encode('utf-8'))+512
        expect(request['stage'] in STAGES and request['mode']=='ced_fixed_rehearsal' and request['transport_kind'] in ('in_process_fixed','sdk_http_rehearsal')
           and request['scope']==p['scope'] and request['context']['input_digest']==p['input_digest']
           and frozen=={'version':VERSION,'policy_digest':digest(p),'slot_key':self._adoption_key(request),
                       'input_token_allowance':allowance,'reserve_micro_cny':allowance*2+4096*8}
           and 1<=request['payload'][request['config'].get('output_token_parameter','max_tokens')]<=4096
           and (request['payload']['model']=='local-ce-double' if not request.get('contract_sdk') else request['contract_sdk']['rehearsal'] is True and request['sdk_policy']=={'rehearsal':True})
           and digest(request)==grant['request_digest'] and reservation['request_digest']==grant['request_digest']
           and reservation['stage']==request['stage'] and reservation['slot_key']==frozen['slot_key']
           and reservation['reserve_micro_cny']==frozen['reserve_micro_cny'],'C/E预留与冻结请求不一致。')

    def _ce_check_saved_call(self,c,row,req):
        if not req.get('ce_policy'):return
        expect(self._has_ce(c),'C/E调用缺少原累计预算。')
        r=c.execute('SELECT * FROM wce_reservations WHERE authorization_id=?',(row['authorization_id'],)).fetchone()
        expect(r is not None,'C/E调用缺少原预算预留。')
        self._ce_validate_entry(c,self._meta(c),r,row,req)

    @staticmethod
    def _ce_usage(req,response):
        usage=response.get('usage') if response else None
        if not isinstance(usage,dict) or set(usage)!={'prompt_tokens','completion_tokens','total_tokens'}:return None
        if not all(type(v) is int and v>=0 for v in usage.values()) or usage['prompt_tokens']+usage['completion_tokens']!=usage['total_tokens']:return None
        return usage

    def _ce_ledger(self,c,meta):
        p=self._ce_policy(c,meta)
        if p is None:return None
        held=spent=pending=overrun=0;entries=[]
        rows=c.execute('SELECT r.*,g.status,g.dispatch_count,g.boot_id,g.response_json,g.response_digest,p.request_json,p.request_digest AS frozen_digest,p.expires_at FROM wce_reservations r JOIN wbc_grants g USING(authorization_id) JOIN wbc_previews p USING(preview_id) ORDER BY r.rowid').fetchall() if c.execute("SELECT 1 FROM sqlite_master WHERE name='wbc_grants'").fetchone() else []
        for row in rows:
            row=dict(row);req=json.loads(row['request_json']);grant={**row,'request_digest':row['frozen_digest']}
            self._ce_validate_entry(c,meta,row,grant,req)
            exposure=0;usage=None;charge=None
            if row['dispatch_count']==0:
                active=row['status']=='authorized' and row['expires_at']>self.call_clock()
                state='held_unconsumed' if active else 'released_unconsumed'
                if active:held+=row['reserve_micro_cny'];exposure=row['reserve_micro_cny']
            else:
                expect(row['dispatch_count']==1,'C/E派发次数异常。')
                response=json.loads(row['response_json']) if row['response_json'] else None
                if response is not None:expect(digest(response)==row['response_digest'],'C/E用量回执校验失败。')
                usage=self._ce_usage(req,response)
                if usage is None:
                    state='consumed_usage_unconfirmed';pending+=row['reserve_micro_cny'];exposure=row['reserve_micro_cny']
                else:
                    charge=usage['prompt_tokens']*p['input_rate']+usage['completion_tokens']*p['output_rate']
                    spent+=charge;exposure=charge;state='settled_simulated_usage'
                    excess=max(0,charge-row['reserve_micro_cny'])
                    if excess or usage['prompt_tokens']>req['ce_policy']['input_token_allowance'] or usage['completion_tokens']>4096:
                        overrun+=max(1,excess);state='usage_exceeds_reservation'
            entries.append({'authorization_id':row['authorization_id'],'stage':row['stage'],'slot_key':row['slot_key'],
                 'status':state,'dispatch_attempts':row['dispatch_count'],'reserve_micro_cny':row['reserve_micro_cny'],
                 'simulation_charge_micro_cny':charge,'budget_exposure_micro_cny':exposure,'usage':usage})
        all_grants=c.execute("SELECT count(*) FROM wbc_grants g JOIN wbc_previews p USING(preview_id)").fetchone()[0] if c.execute("SELECT 1 FROM sqlite_master WHERE name='wbc_grants'").fetchone() else 0
        expect(all_grants==len(entries)==c.execute('SELECT count(*) FROM wce_reservations').fetchone()[0],'同会话存在未计入预算的授权或缺失回执。')
        return {'version':VERSION,'mode':'ce_local_rehearsal','scope':p['scope'],'simulated':True,'actual_model_cost':0,
                'limit_micro_cny':p['simulation_limit_micro_cny'],'spent_simulated_micro_cny':spent,
                'held_unconsumed_micro_cny':held,'consumed_unconfirmed_micro_cny':pending,'overrun_micro_cny':overrun,
                'available_micro_cny':max(0,p['simulation_limit_micro_cny']-spent-held-pending),
                'overspent_micro_cny':max(0,spent+held+pending-p['simulation_limit_micro_cny']),
                'entries':entries,'notice':'这是同一虚构会话的模拟预算与用量，实际模型费用为0。消费失败/未知不清零；旧未消费授权过期或重启可释放预留。'}

    def _ce_check_authorization(self,c,req):
        if not req.get('ce_policy'):return
        # Persist invalidation under the authorization transaction before releasing a previous boot's unused hold.
        # An older worker then cannot dispatch the same grant after a new reservation takes its place.
        c.execute("UPDATE wbc_grants SET status='invalidated' WHERE dispatch_count=0 AND status='authorized' AND (boot_id<>? OR preview_id IN (SELECT preview_id FROM wbc_previews WHERE expires_at<=?))",(self.call_boot_id,self.call_clock()))
        ledger=self._ce_ledger(c,self._meta(c));slot=req['ce_policy']['slot_key']
        expect(not ledger['overrun_micro_cny'] and not ledger['overspent_micro_cny'],'预算/用量异常，停止新增授权。')
        expect(not any(e['stage']==req['stage'] and e['slot_key']==slot and e['status']!='released_unconsumed' for e in ledger['entries']),
               '当前题目/答卷/面试轮次已预留或消费一次，请查原回执；不能换预览重复调用。')
        expect(req['ce_policy']['reserve_micro_cny']<=ledger['available_micro_cny'],'同会话累计模拟预算不足，未授权、未派发。')

    def _ce_on_authorized(self,c,req,aid):
        if not req.get('ce_policy'):return
        c.execute('INSERT INTO wce_reservations VALUES (?,?,?,?,?)',(aid,req['stage'],req['ce_policy']['slot_key'],digest(req),req['ce_policy']['reserve_micro_cny']))

    def _ce_check_dispatch(self,c,req,aid):
        if not req.get('ce_policy'):return
        ledger=self._ce_ledger(c,self._meta(c));entry=next((e for e in ledger['entries'] if e['authorization_id']==aid),None)
        expect(entry and entry['status']=='held_unconsumed' and not ledger['overrun_micro_cny'] and not ledger['overspent_micro_cny'],
               '原预算预留失效或用量异常，未派发。')

    def _ce_validate_response(self,req,response):
        if not req.get('ce_policy'):return
        usage=self._ce_usage(req,response)
        if usage is None:raise CEDValidation('local_usage_missing_or_invalid')
        if usage['prompt_tokens']>req['ce_policy']['input_token_allowance'] or usage['completion_tokens']>4096:
            raise CEDValidation('local_usage_exceeds_reservation')

    def _ce_dispatch(self,req):
        return self.ce_transport.send(deepcopy(req)) if req.get('ce_policy') else self.call_transport.send(deepcopy(req))

    def _ce_public(self,req):
        return {'ce_budget_rehearsal':{**req['ce_policy'],'usage_source':'local_simulated','actual_model_cost':0,'notice':'模拟单价与用量，仅本地预算演练，不是当前服务商报价或真实费用。'}} if req.get('ce_policy') else {}

    def ce_budget(self,token):
        with self.lock,closing(self._connect(token)) as c:
            meta=self._meta(c);return self._reply(scope=self._scope(meta),ce_budget=self._ce_ledger(c,meta))

    def _ce_validate_records(self,c,meta):
        if not self._has_ce(c):return
        p=self._ce_policy(c,meta);record=c.execute('SELECT payload_json,parent_ids_json FROM wb_records WHERE record_id=?',(meta['session_id']+':ce-budget',)).fetchone()
        expect(record and json.loads(record[0])=={'event':'ce_budget_open','policy':p},'原累计预算来源记录缺失或变化。')
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='wbc_grants'").fetchone():self._ce_ledger(c,meta)

    def _ce_guard(self,c,meta,operation,body):
        if meta['package'].get('personal_input') and operation in ('assessment_start','retest_start','interview_start'):
            expect(self._has_ce(c),'个人会话请先完成计划发布并确认C/E累计模拟预算；不会混入固定评分步骤。')
        if not self._has_ce(c):return
        if operation=='answer':
            run=self._saved_run(c,meta,body['run_id']);q=run['questions'][run['cursor']]
            expect(self._application_for(c,meta,'c_question',q['question_id']),'先核对采用本次当前题目，再提交作答。')
        elif operation=='interview_answer':
            run=self._interview_run(c,meta,body['interview_id'])
            expect(self._application_for(c,meta,'e_turn',run['current_question_id']),'先核对采用当前面试轮次，再提交回答。')


    def _ce_report_pending(self,c,report):
        if not self._has_ce(c):return report
        report=deepcopy(report)
        report.update(review_status='pending_candidate_review',source='ce_pending_review',issue_count=0,clear_sample_count=0,
                      notice='面试原始回答已保存，复盘尚待单次生成及核对采用；不使用固定反馈冒充模型结论。')
        for finding in report['findings']:
            finding.update(analysis_kind='review_required',observation='本轮回答待复盘核对。',suggestion='',quote='',evidence=[],issue=None)
        return report
