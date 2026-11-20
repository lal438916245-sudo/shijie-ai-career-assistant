"""Single-request OpenAI-compatible SDK adapter, with an explicit local HTTP rehearsal."""
import importlib.metadata
import hashlib
import json
import math
import time

class SDKFailure(ValueError):
    def __init__(self,code):
        self.code=code
        self.usage=None
        self.diagnostics=None
        super().__init__('SDK 请求未完成，请读取回执后再决定是否重新授权')

class SDKTransport:
    def __init__(self,preparation,*,rehearsal=True,outbound_enabled=False,http_client_factory=None):
        self.preparation=preparation;self.rehearsal=rehearsal;self.outbound_enabled=outbound_enabled
        self.http_client_factory=http_client_factory;self.sent=False
        self.metadata={'sdk_http_requests':0,'usage':None,'provider_request_id':None,'simulated':rehearsal or http_client_factory is not None,'sdk_version':None}
    def _mock_response(self,request,meta,diagnosis):
        from authorized_ab import FixedABTransport
        adapted={**request,'mode':'local_request_double','payload':{**request['payload'],'max_tokens':request['config']['max_output_tokens']}}
        return FixedABTransport().send(adapted,meta,diagnosis)

    def _mock_client(self,request,meta,diagnosis):
        import httpx
        def handle(http_request):
            self.metadata['sdk_http_requests']+=1
            actual=json.loads(http_request.content)
            if http_request.method!='POST' or str(http_request.url)!='https://sdk-rehearsal.invalid/v1/chat/completions' or actual!=request['payload']:raise SDKFailure('request_mismatch')
            if http_request.headers.get('authorization')!='Bearer sdk-rehearsal-not-a-real-key':raise SDKFailure('key_boundary')
            result=self._mock_response(request,meta,diagnosis)
            prompt=math.ceil(len(http_request.content.decode('utf-8'))/2);output=result['synthetic_output_tokens']
            return httpx.Response(200,headers={'x-request-id':'sdk-http-rehearsal'},json={'id':'chatcmpl-local-sdk','object':'chat.completion','created':int(time.time()),'model':request['payload']['model'],'choices':[{'index':0,'message':{'role':'assistant','content':result['content']},'finish_reason':result['finish_reason']}],'usage':{'prompt_tokens':prompt,'completion_tokens':output,'total_tokens':prompt+output}})
        return httpx.Client(transport=httpx.MockTransport(handle),follow_redirects=False,trust_env=False)
    def send(self,request,meta,diagnosis):
        if self.sent:raise SDKFailure('already_sent')
        if not self.rehearsal and not self.outbound_enabled:raise SDKFailure('outbound_disabled')
        if request.get('sdk_policy',{}).get('rehearsal')!=self.rehearsal:raise SDKFailure('mode_mismatch')
        from ced_output_control import sdk_kwargs
        try:call_kwargs=sdk_kwargs(request['payload'],request['config'])
        except ValueError:raise SDKFailure('request_mismatch') from None
        diagnostics={'finish_reason':None,'usage_details':{}} if request.get('output_control') else None
        # Check the version and take the Key under the same server-side lock.
        # No SDK client exists before authorization is consumed by its caller.
        with self.preparation.lock:
            current=self.preparation._read()
            if current['revision']!=request['config_revision'] or (current['revision'] and current['config']!=request['config']):raise SDKFailure('config_changed')
            if self.rehearsal:key='sdk-rehearsal-not-a-real-key';base_url='https://sdk-rehearsal.invalid/v1'
            else:
                if not current['encrypted_key']:raise SDKFailure('key_missing')
                if hashlib.sha256(current['encrypted_key'].encode()).hexdigest()!=request.get('key_slot_digest'):raise SDKFailure('config_changed')
                try:key=self.preparation.vault.open(current['encrypted_key'])
                except Exception:raise SDKFailure('key_unreadable') from None
                if not isinstance(key,str) or len(key)<8 or any(ch.isspace() for ch in key):raise SDKFailure('key_unreadable')
                base_url=request['config']['base_url']
        try:
            from openai import OpenAI
            import httpx
            import logging
            for name in {'openai','httpx','httpcore',*[n for n in logging.Logger.manager.loggerDict if n.startswith(('openai.','httpx.','httpcore.'))]}:
                logging.getLogger(name).setLevel(logging.CRITICAL+1)
        except ImportError:raise SDKFailure('sdk_missing') from None
        self.metadata['sdk_version']=importlib.metadata.version('openai')
        wire=None;client=None;self.sent=True
        try:
            if self.rehearsal:wire=self._mock_client(request,meta,diagnosis)
            elif self.http_client_factory:wire=self.http_client_factory()
            else:wire=httpx.Client(transport=httpx.HTTPTransport(retries=0),follow_redirects=False,trust_env=False)
            # Disable both SDK retries and HTTP redirects; destination, Key and
            # timeout never come from environment variables or browser overrides.
            expected_url=httpx.URL(base_url.rstrip('/')+'/chat/completions')
            def enforce_wire(http_request):
                if http_request.url!=expected_url:raise SDKFailure('destination_changed')
                try:matches=json.loads(http_request.content)==request['payload']
                except (ValueError,UnicodeError):matches=False
                if not matches:raise SDKFailure('request_mismatch')
                # The installed SDK can inherit organization/project and custom
                # headers from its environment. Only the confirmed Bearer and
                # minimal protocol headers are allowed onto this request.
                body_size=len(http_request.content)
                http_request.headers.clear()
                http_request.headers.update({'Authorization':'Bearer '+key,'Content-Type':'application/json','Accept':'application/json','Host':http_request.url.netloc.decode('ascii'),'Content-Length':str(body_size),'User-Agent':'CareerPilotSDK/1'})
                if not self.rehearsal:
                    from judge_client import sponsored_policy
                    sponsored=sponsored_policy(self.preparation)
                    if sponsored:
                        http_request.headers['X-Shijie-Stage']=request['stage']
                        http_request.headers['X-Shijie-Request-ID']=hashlib.sha256(json.dumps(request,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                if not self.rehearsal:self.metadata['sdk_http_requests']+=1
            wire.event_hooks.setdefault('request',[]).append(enforce_wire)
            client=OpenAI(api_key=key,base_url=base_url,max_retries=0,timeout=float(request['timeout_seconds']),http_client=wire)
            response=client.chat.completions.create(**call_kwargs)
            identity=getattr(response,'_request_id',None)
            self.metadata['provider_request_id']=identity if isinstance(identity,str) and len(identity)<=200 and key not in identity else None
            usage=getattr(response,'usage',None)
            if usage:
                values={k:getattr(usage,k,None) for k in ('prompt_tokens','completion_tokens','total_tokens')}
                if all(type(v) is int and v>=0 for v in values.values()) and values['prompt_tokens']+values['completion_tokens']==values['total_tokens']:self.metadata['usage']=values
            if diagnostics is not None and self.metadata['usage']:
                for group,key,public,maximum in (
                    ('completion_tokens_details','reasoning_tokens','reasoning_tokens',self.metadata['usage']['completion_tokens']),
                    ('prompt_tokens_details','cached_tokens','cached_input_tokens',self.metadata['usage']['prompt_tokens'])):
                    details=getattr(usage,group,None)
                    value=details.get(key) if isinstance(details,dict) else getattr(details,key,None)
                    if type(value) is int and 0<=value<=maximum:diagnostics['usage_details'][public]=value
            choices=getattr(response,'choices',None)
            if not choices or len(choices)!=1:raise SDKFailure('invalid_response')
            choice=choices[0]
            if diagnostics is not None:diagnostics['finish_reason']=choice.finish_reason if choice.finish_reason in ('stop','length','content_filter','tool_calls','function_call') else 'other'
            if choice.finish_reason!='stop':raise SDKFailure('truncated' if choice.finish_reason=='length' else 'incomplete')
            if getattr(choice.message,'tool_calls',None):raise SDKFailure('unsupported_tools')
            content=choice.message.content
            if not isinstance(content,str) or not content.strip():raise SDKFailure('empty_response')
            if self.metadata['usage'] and self.metadata['usage']['completion_tokens']>request['payload'][request['config'].get('output_token_parameter','max_tokens')]:raise SDKFailure('output_limit')
            return {'content':content,'finish_reason':'stop','usage':self.metadata['usage'],**({'diagnostics':diagnostics} if diagnostics is not None else {})}
        except SDKFailure as exc:
            exc.usage=self.metadata['usage']
            exc.diagnostics=diagnostics
            raise
        except Exception as exc:
            code={'APITimeoutError':'timeout','AuthenticationError':'authentication','RateLimitError':'rate_limit','APIConnectionError':'connection','APIStatusError':'http_error','BadRequestError':'bad_request','PermissionDeniedError':'permission'}.get(type(exc).__name__,'sdk_error')
            raise SDKFailure(code) from None
        finally:
            key=None
            try:
                if client is not None:client.close()
                elif wire is not None:wire.close()
            except Exception:pass

def sdk_agents(request,transport,meta,diagnosis):
    from agent_a_hunter import HunterAgent
    from agent_b_planner import PlannerAgent,LearningPlan
    sent=False
    def create(_db):
        cls=HunterAgent if request['stage']=='diagnosis' else PlannerAgent
        agent=cls.__new__(cls);agent.db=None;agent.trace_id=meta['trace_id']
        agent.evidence_contract_required = not transport.rehearsal
        agent.model_name='sdk-http-rehearsal' if transport.metadata['simulated'] else request['payload']['model']
        agent.system_prompt=request['payload']['messages'][0]['content']
        if request['stage']=='plan':agent.schema_json=json.dumps(LearningPlan.model_json_schema(),ensure_ascii=False);agent.current_plan_id=None;agent.reflection_history=[]
        def think(prompt,**_kwargs):
            nonlocal sent
            if sent:raise SDKFailure('already_sent')
            if [{'role':'system','content':agent.system_prompt},{'role':'user','content':prompt}]!=request['payload']['messages']:raise SDKFailure('request_mismatch')
            sent=True
            return transport.send(request,meta,diagnosis)['content']
        agent.think=think
        return agent
    return create
