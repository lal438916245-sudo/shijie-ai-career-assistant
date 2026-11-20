"""Current A/B/F/C/E contracts on the existing one-request SDK boundary.

HTTP entry points install rehearsal adapters only. The generic wire also supports
the explicit outbound guard; neither a browser field nor a saved Key enables it.
"""
from copy import deepcopy
import hashlib, math, json
from sdk_transport import SDKTransport,SDKFailure
from workbench_abf import FixedABFTransport
from workbench_ce import LocalCETransport
from competition_workbench_assessment import encode
from ced_output_control import d_controls,apply_controls

def compact_abf_payload(body,stage):
    body=deepcopy(body)
    if stage not in ('a_diagnosis','b_plan','f_review'):return body
    data=json.loads(body['messages'][1]['content']);ctx=data['untrusted_context']
    def schema(value):
        if isinstance(value,list):return [schema(v) for v in value]
        if isinstance(value,dict):return {k:schema(v) for k,v in value.items() if not (k=='title' and isinstance(v,str))}
        return value
    data['output_schema']=schema(data['output_schema'])
    # Model outputs never own these identities; retain them only in server snapshots.
    ctx.pop('scope',None);ctx.pop('input_digest',None)
    if stage=='b_plan' and 'previous_tasks' in ctx:
        # Revision copies the adopted plan and follows F; no new resource selection.
        ctx.pop('sources',None);ctx.pop('resources',None)
        ctx['task_catalog']=[{'task_template_id':t['task_template_id']} for t in ctx['task_catalog']]
        data['task']+=' 修订仅依据已采用的previous_tasks、岗位差距和本版F意见；沿用原资源ID，未受影响字段保持原值。'
    if stage=='f_review':
        # A's evidence assessment is present; raw resume/JD are duplicate sources.
        # Keep full diagnostic/plan text and original Unicode quote offsets intact.
        ctx['sources']={k:{'text':v['text']} for k,v in ctx['sources'].items() if k not in ('resume','jd')}
        ctx['task_catalog']=[{k:v for k,v in t.items() if k!='budget'} for t in ctx['task_catalog']]
        data['task']+=' 引用只可来自本次sources，预算原文在各任务budget来源中，不得引用未发送的原简历/JD。'
    body['messages'][1]['content']=json.dumps(data,ensure_ascii=False,separators=(',',':'))
    return body

class ContractSDKWire(SDKTransport):
    def _mock_response(self,request,_meta,_diagnosis):
        value=(FixedABFTransport() if request['stage'] in ('a_diagnosis','b_plan','f_review') else LocalCETransport()).send(request)
        return {**value,'synthetic_output_tokens':math.ceil(len(value['content'])/2)}

class ContractSDKBridge:
    def __init__(self,preparation,*,rehearsal=True,outbound_enabled=False,http_client_factory=None):
        if type(rehearsal) is not bool or type(outbound_enabled) is not bool or rehearsal and outbound_enabled:
            raise ValueError('SDK rehearsal cannot enable outbound')
        self.preparation=preparation;self.rehearsal=rehearsal;self.outbound_enabled=outbound_enabled
        self.http_client_factory=http_client_factory;self.last_metadata=None

    def freeze(self,request):
        req=deepcopy(request)
        if req['stage']=='d_revision' and req['context'].get('output_contract')=='personal-evidence-v4':
            # Stored requests use canonical JSON key order. Allocate auxiliary
            # IDs in that same order BEFORE freezing the menu, so a reload or
            # another process cannot change a valid source's assigned ID.
            req['context']['sources']=dict(sorted(req['context']['sources'].items()))
        with self.preparation.lock:current=self.preparation._read()
        settings=deepcopy(current['config'])
        from c_grading_contract import prepare_request as prepare_grading
        req=prepare_grading(req,settings)
        from e_report_contract import prepare_request as prepare_interview
        from d_resume_contract import prepare_request as prepare_resume
        req=prepare_interview(req,settings)
        req=prepare_resume(req,settings)
        body=compact_abf_payload(req['payload'],req['stage'])
        cap=12000 if req['stage']=='b_plan' else 4096
        limit=min(settings['max_output_tokens'],cap)
        body.pop('max_tokens',None);body.pop('max_completion_tokens',None)
        body.pop('thinking',None);body.pop('reasoning_effort',None)
        body.update(model=settings['model'] or 'local-sdk-contract-rehearsal')
        # Same frozen vendor output controls as D: known DeepSeek JSON mode and
        # disabled thinking; other providers retain their default behavior.
        control=d_controls(settings,output_limit=min(limit,4096))
        control['max_output_tokens']=limit
        body=apply_controls(body,settings,control)
        req.update(config=settings,config_revision=current['revision'],
            key_slot_digest=hashlib.sha256(current['encrypted_key'].encode()).hexdigest() if not self.rehearsal and current['encrypted_key'] else None,
            payload=body,sdk_policy={'rehearsal':self.rehearsal},timeout_seconds=settings['timeout_seconds'],
            transport_kind='sdk_http_rehearsal' if self.rehearsal else 'session_sdk',
            contract_sdk={'version':'workbench-contract-sdk-v1','rehearsal':self.rehearsal,'output_limit':limit})
        return req

    def send(self,request):
        if request.get('sdk_policy')!={'rehearsal':self.rehearsal}:raise SDKFailure('mode_mismatch')
        # SDKTransport checks config/Key version after durable consumption,
        # disables retries, redirects, environment proxies and inherited headers.
        wire=ContractSDKWire(self.preparation,rehearsal=self.rehearsal,
            outbound_enabled=self.outbound_enabled,http_client_factory=self.http_client_factory)
        try:return wire.send(request,None,None)
        finally:self.last_metadata=deepcopy(wire.metadata)

class ABFSDKRehearsal(FixedABFTransport):
    kind='sdk_http_rehearsal'
    def __init__(self,preparation):self.bridge=ContractSDKBridge(preparation)
    def freeze(self,request):return self.bridge.freeze(request)
    def send(self,request):return self.bridge.send(request)

class CESDKRehearsal(LocalCETransport):
    kind='sdk_http_rehearsal'
    def __init__(self,preparation):self.bridge=ContractSDKBridge(preparation)
    def freeze(self,request):return self.bridge.freeze(request)
    def send(self,request):return self.bridge.send(request)
