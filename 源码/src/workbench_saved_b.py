"""Audited reuse of a complete legacy B response; no transport or grant mutation."""
from contextlib import closing
from copy import deepcopy
from datetime import date,timedelta
import json
from abf_contracts import Plan,normalize
from competition_workbench_assessment import encode,digest,expect
from competition_workbench_fixtures import bound_id,budget_total
from fixed_learning_time import VERSION as TIME_VERSION,policy

VERSION='saved-b-content-v1'
OPERATIONS={'saved_b_apply':{'authorization_id','derivation_digest','review_confirmed'}}

class WorkbenchSavedB:
    def _saved_b_has(self,c):
        return c.execute("SELECT 1 FROM sqlite_master WHERE name='wb_saved_b'").fetchone() is not None

    def _saved_b_candidate(self,c,meta,aid):
        expect(self._has_runtime(c) and meta['package'].get('personal_input'),'仅支持个人会话的已保存B内容。')
        row,req=self._abf_row(c,aid)
        expect(req['stage']=='b_plan' and req['target_version']==0 and row['status']=='failed_validation'
               and row['dispatch_count']==1 and row['response_json'] and not req.get('learning_time_policy'),
               '仅可复用完整旧B时间校验失败响应；不能复用超时、未知结果或其他阶段。')
        expect(json.loads(row['error_json'] or '[]')==[{'code':'contract','path':'$'}],
               '原失败原因不属于可审计的旧时间合同，未生成采用候选。')
        response=json.loads(row['response_json']);expect(response['finish_reason']=='stop','原响应不完整，不可复用。')
        self._abf_sdk_usage(req,response)
        meta=self._context(c,meta)
        expect(req['context']['diagnosis']==meta['diagnosis'],'原B引用的A诊断与当前正式诊断不同。')
        def pairs(values):
            result={}
            for k,v in values:expect(k not in result,'原响应包含重复字段，不可复用。');result[k]=v
            return result
        raw=json.loads(response['content'],object_pairs_hook=pairs);value=Plan.model_validate(raw).model_dump()
        expect(any(budget_total(t['budget'])>60 for t in value['tasks']),'原响应没有可核对的旧时间超限，不能借此另建计划。')
        content=deepcopy(value)
        changes=[]
        for t in content['tasks']:
            changes.append({'task_template_id':t['task_template_id'],'old_budget':t.pop('budget'),'old_minutes':budget_total(next(x['budget'] for x in value['tasks'] if x['task_template_id']==t['task_template_id'])),'new_minutes':60})
        # This is a local projection, not a replacement for the original request.
        projected=deepcopy(req);projected['learning_time_policy']=TIME_VERSION
        candidate=normalize(self,meta,projected,encode(content))
        simulated=self._session_is_simulated(req)
        candidate['plan']['fixture_notice']=('复用已保存的本地替身学习内容' if simulated else '复用已保存的真实模型学习内容')+'；原调用时间校验失败并保留。时间由程序固定每天60分钟，经核对采用，无新增模型请求；学习卡与资料为内置内容，仍需F审查后发布。'
        self._validate_plan(candidate['plan'],meta)
        source={'version':VERSION,'scope':self._scope(meta),'authorization_id':aid,
                'A_report_id':meta['report_id'],'A_diagnosis_digest':digest(meta['diagnosis']),
                'provider':req['config']['provider'],'model':req['config']['model'],'simulated':self._session_is_simulated(req),
                'original_request_digest':row['request_digest'],'original_response_digest':row['response_digest'],
                'original_status':'failed_validation','original_errors':json.loads(row['error_json']),
                'content_digest':digest(content),'time_policy':policy(),'changes':changes,
                'original_usage':response['usage'],'new_model_requests':0}
        return {'source':source,'candidate':candidate},req

    def saved_b_preview(self,token,body):
        from workbench_abf import fields
        fields(body,('authorization_id',))
        with self.lock,closing(self._connect(token)) as c:
            meta=self._context(c,self._meta(c));d,req=self._saved_b_candidate(c,meta,body['authorization_id'])
            existing=c.execute('SELECT payload_json FROM wb_saved_b WHERE authorization_id=?',(body['authorization_id'],)).fetchone() if self._saved_b_has(c) else None
            app=json.loads(existing[0]) if existing else None
            v=self._reply(scope=self._scope(meta),authorization_id=body['authorization_id'],revision=meta['revision'],
                derivation_digest=digest(d),candidate=d['candidate'],source=d['source'],
                already_applied=bool(app),application=app,
                can_apply=not app and meta['active_version'] is None and meta['published_version'] is None,
                new_model_requests=0,actual_model_cost=0,external_network_allowed=False,
                notice='仅复用保存的学习内容，时间由程序固定；原失败与费用保留，不重发模型。核对采用后须经程序校验与用户确认发布。')
            return self._session_container(c,meta,v)

    def _do_saved_b_apply(self,c,meta,body):
        expect(body['review_confirmed'] is True,'请先核对保存内容、程序时间与原调用来源。')
        expect(meta['active_version'] is None and meta['published_version'] is None,'本会话已有正式计划，不能覆盖或重复采用。')
        d,req=self._saved_b_candidate(c,meta,body['authorization_id'])
        expect(body['derivation_digest']==digest(d),'核对内容摘要已变化，未保存。')
        c.execute('CREATE TABLE IF NOT EXISTS wb_saved_b(application_id TEXT PRIMARY KEY,authorization_id TEXT NOT NULL UNIQUE,version INTEGER NOT NULL UNIQUE,revision INTEGER NOT NULL UNIQUE,payload_json TEXT NOT NULL,payload_digest TEXT NOT NULL)')
        expect(c.execute('SELECT count(*) FROM wb_saved_b').fetchone()[0]==0,'此会话已有保存内容采用记录，不能重复。')
        aid=bound_id(meta['session_id'],'saved_b',body['request_id']);source_id=aid+':source';record_id=aid+':adopted';formal_id=meta['session_id']+':plan:1'
        provenance=deepcopy(self._session_provenance(req,body['authorization_id']))
        provenance['model_provenance'].update(content_reuse=VERSION,original_call_status='failed_validation',schedule_source='program',new_model_requests=0)
        producer={'producer_contract':VERSION,'producer_application_id':aid,'candidate_simulated':self._session_is_simulated(req),**provenance}
        formal={**deepcopy(d['candidate']['plan']),**producer}
        app={'application_id':aid,'authorization_id':body['authorization_id'],'scope':self._scope(meta),'revision':meta['revision']+1,
             'derivation_digest':digest(d),'source_record_id':source_id,'record_id':record_id,'formal_record_id':formal_id,
             'version':1,'review_confirmed':True,'source':d['source'],'formal_result':formal}
        self._record(c,meta,source_id,'plan','B · 原失败调用与保存内容来源',d['source'],[meta['session_id']+':diagnosis'],source='user_review')
        self._record(c,meta,record_id,'plan','B · 审计采用保存内容与程序时间',{'event':'saved_b_adopted',**app},[source_id],source='user_review')
        c.execute('INSERT INTO wb_plans VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)',(1,formal_id,encode(formal),digest(formal),None))
        c.execute('UPDATE wb_meta SET active_version=1 WHERE singleton=1')
        for t in formal['tasks']:
            day=(date.fromisoformat(meta['start_date'])+timedelta(days=t['day']-1)).isoformat()
            c.execute('INSERT INTO wb_progress(task_id,status,start_date,end_date) VALUES (?,?,?,?)',(t['task_id'],'not_started',day,day))
        self._record(c,meta,formal_id,'plan','B · 已保存内容的正式计划草案',{'version':1,'plan_digest':digest(formal),'task_count':len(formal['tasks']),**producer},[record_id],source='user_review')
        c.execute('INSERT INTO wb_saved_b VALUES (?,?,?,?,?,?)',(aid,body['authorization_id'],1,app['revision'],encode(app),digest(app)))
        return self._session_container(c,meta,self._reply(scope=self._scope(meta),application_id=aid,record_id=record_id,
            formal_record_id=formal_id,formal_plan_version=1,new_model_requests=0,actual_model_cost=0,
            notice='正式草案已保存；复用原内容、程序固定60分钟，原失败与费用不变，等待程序校验与用户确认发布。'))

    def _saved_b_available(self,c,meta):
        if meta['active_version'] is not None or not self._has_runtime(c) or not self._has_abf(c):return None
        for r in c.execute("SELECT g.authorization_id,p.request_json FROM wbf_grants g JOIN wbf_previews p USING(preview_id) WHERE g.status='failed_validation' AND g.dispatch_count=1 ORDER BY p.rowid DESC"):
            q=json.loads(r['request_json'])
            if q['stage']=='b_plan' and q['target_version']==0 and not q.get('learning_time_policy'):
                return {'authorization_id':r['authorization_id'],'new_model_requests':0,'notice':'有已保存B响应可进行本地核对，不重发模型。'}
        return None

    def _saved_b_validate_records(self,c,meta):
        records=list(c.execute('SELECT * FROM wb_saved_b')) if self._saved_b_has(c) else []
        expected_ids=set()
        for row in records:
            app=json.loads(row['payload_json']);expect(digest(app)==row['payload_digest'],'保存内容采用摘要不一致。')
            expect(app['application_id']==row['application_id'] and app['authorization_id']==row['authorization_id'] and app['version']==row['version']==1
                   and app['revision']==row['revision']<=meta['revision'] and app['scope']==self._scope(meta) and app['review_confirmed'] is True,'保存内容采用索引或来源不一致。')
            d,req=self._saved_b_candidate(c,self._context(c,meta),app['authorization_id'])
            expect(app['derivation_digest']==digest(d) and app['source']==d['source'],'原保存内容与审计采用不一致。')
            prov=deepcopy(self._session_provenance(req,app['authorization_id']))
            prov['model_provenance'].update(content_reuse=VERSION,original_call_status='failed_validation',schedule_source='program',new_model_requests=0)
            producer={'producer_contract':VERSION,'producer_application_id':app['application_id'],'candidate_simulated':self._session_is_simulated(req),**prov}
            expected={**d['candidate']['plan'],**producer};expect(app['formal_result']==expected,'正式计划与保存内容及程序时间不一致。')
            p=c.execute('SELECT * FROM wb_plans WHERE version=1').fetchone()
            expect(p and p['record_id']==app['formal_record_id'] and json.loads(p['plan_json'])==expected and p['plan_digest']==digest(expected) and p['parent_version'] is None,'审计采用的正式计划缺失或被修改。')
            for rid,payload,parents in [
                (app['source_record_id'],d['source'],[meta['session_id']+':diagnosis']),
                (app['record_id'],{'event':'saved_b_adopted',**app},[app['source_record_id']]),
                (app['formal_record_id'],{'version':1,'plan_digest':digest(expected),'task_count':len(expected['tasks']),**producer},[app['record_id']])]:
                r=c.execute('SELECT payload_json,parent_ids_json FROM wb_records WHERE record_id=?',(rid,)).fetchone()
                expect(r and json.loads(r[0])==payload and json.loads(r[1])==parents,'保存内容采用的来源记录缺失或不一致。')
            expected_ids.add(app['application_id'])
        for r in c.execute('SELECT plan_json FROM wb_plans'):
            p=json.loads(r[0])
            if p.get('producer_contract')==VERSION:expect(p['producer_application_id'] in expected_ids,'正式计划的保存内容采用记录缺失。')
