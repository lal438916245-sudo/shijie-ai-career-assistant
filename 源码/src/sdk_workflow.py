"""Isolated SDK rehearsal and real-mode authorization; external calls default OFF."""
from contextlib import closing
from pathlib import Path
import hashlib
import sqlite3
from urllib.parse import urlsplit

from authorized_ab import AuthorizedAB,ABConflict
from live_session_http import LocalWorkflowServer,LocalWorkflowHandler
from sdk_transport import SDKTransport,sdk_agents,SDKFailure

SDK_INPUT={'target_role':'合成 SDK 预演岗位','resume_text':'合成经历：熟悉 SQL 和离线处理，尚未实践实时故障恢复。'*3,'jd_text':'合成要求：理解事件时间、窗口和检查点，提供可核对的恢复验证步骤。'*3,'available_days':4}

def blocked_factory(_db):raise ABConflict('SDK 模式必须通过单次授权，不允许直接执行旧示例入口')

class SDKAuthorizedAB(AuthorizedAB):
    source='sdk_ab_authorization'
    def __init__(self,handler):super().__init__(handler);self.transport=None
    @property
    def mode(self):return 'sdk_rehearsal' if self.server.rehearsal else 'real_model'
    @property
    def confirmation_field(self):return 'accept_sdk_rehearsal' if self.server.rehearsal else 'accept_real_model'
    @property
    def real_dispatch_enabled(self):return self.server.outbound_enabled and not self.server.rehearsal
    def _reply(self,**kw):
        return super()._reply(simulated=self.server.rehearsal or self.server.http_client_factory is not None,external_network_allowed=self.real_dispatch_enabled and self.server.http_client_factory is None,**kw)
    def prepare_request(self,request,configuration):
        if not self.server.rehearsal:
            if not configuration['revision'] or not configuration['encrypted_key']:raise ABConflict('真实模式需要已保存的服务商配置与本机加密 Key')
        request['mode']=self.mode
        request['key_slot_digest']=hashlib.sha256(configuration['encrypted_key'].encode()).hexdigest() if not self.server.rehearsal else None
        request['sdk_policy']={'rehearsal':self.server.rehearsal,'outbound_enabled':self.server.outbound_enabled,'http_test_double':self.server.http_client_factory is not None,'instance':self.server.boot_id,'adapter_version':'openai-chat-sdk-v1'}
        c=request['config'];limit=request['payload'].pop('max_tokens')
        request['payload'][c.get('output_token_parameter','max_tokens')]=limit
        temperature=c.get('temperature',0.7)
        if temperature is None:request['payload'].pop('temperature',None)
        else:request['payload']['temperature']=temperature
        return request
    def check_dispatch(self,request):
        if not self.server.rehearsal and not self.server.outbound_enabled:raise ABConflict('真实外发开关关闭，不读取 Key、不构造 SDK 客户端；当前授权不能执行')
    def preview(self,token,body):
        data=super().preview(token,body)
        data['cost_notice']='按完整请求及手填单价粗估，实际 usage 和账单可能不同，不是硬费用上限；失败也可能计费。SDK预演的模型费用为0。'
        data.update({'transport_destination':'真实 SDK + 本地 HTTP 替身（无外网）' if self.server.rehearsal else ('受控 HTTP 测试替身' if self.server.http_client_factory else '配置的真实服务商；外发开启' if self.server.outbound_enabled else '真实外发关闭'),
            'notice':'这是 SDK 预演：SDK 生成 HTTP 请求，由本地响应器拦截；结果为合成内容，不代表真实模型效果。' if self.server.rehearsal else '真实模式授权：资料会发送给配置服务商，可能产生费用。预览不执行，授权只对应这一份请求。当前外发开关状态须同时允许。',
            'actual_cost':0 if self.server.rehearsal or self.server.http_client_factory else None,'external_network_allowed':self.real_dispatch_enabled and self.server.http_client_factory is None,'simulated':self.server.rehearsal or self.server.http_client_factory is not None})
        return data
    def agent_factory(self,request,meta,diagnosis):
        self.transport=SDKTransport(self.server.preparation,rehearsal=self.server.rehearsal,outbound_enabled=self.server.outbound_enabled,http_client_factory=self.server.http_client_factory)
        return sdk_agents(request,self.transport,meta,diagnosis)
    def failure_code(self,exc):return exc.code if isinstance(exc,SDKFailure) else super().failure_code(exc)
    def _receipt(self,row,status,result=None,error=None):
        value=super()._receipt(row,status,result,error)
        simulated=self.server.rehearsal or self.server.http_client_factory is not None
        value.update({'actual_model_cost':0 if simulated else None,'simulated':simulated,'external_network_allowed':self.real_dispatch_enabled and not simulated,'sdk_metadata':self.transport.metadata if self.transport else None,
          'notice':'SDK 预演完成只证明请求链路通过；响应为本地合成内容，不是真实诊断或计划。已消费授权不补发。' if self.server.rehearsal else '真实模式单次授权；失败或断连也可能计费，已消费授权不会自动补发。'})
        return value

class SDKWorkflowHandler(LocalWorkflowHandler):
    def _map(self):
        parsed=urlsplit(self.path)
        if not parsed.path.startswith('/api/sdk/'):
            self.reject_request(404,{'error':'接口不存在'});return False
        self.path='/api/live/'+self.path[len('/api/sdk/'):]
        return True
    def _mode_matches(self):
        expected='sdk_rehearsal' if self.server.rehearsal else 'real_model'
        supplied=self.headers.get('X-CP-SDK-Mode')
        if supplied is not None and supplied!=expected:
            self.reject_request(409,{'error':'SDK 模式已变化，请重新读取服务状态','code':'mode_changed'});return False
        return True
    def read(self,token,kind):
        data=super().read(token,kind)
        data.update({'mode':'sdk_rehearsal' if self.server.rehearsal else 'real_model','real_dispatch_enabled':self.server.outbound_enabled and not self.server.rehearsal,'simulated':self.server.rehearsal or self.server.http_client_factory is not None})
        return data
    def do_GET(self):
        if self.path=='/api/sdk/capabilities':
            if not self.authorized():return self.reply(403,{'error':'请求来源不可用'})
            return self.reply(200,{'data':{'source_kind':'sdk_ab_authorization','mode':'sdk_rehearsal' if self.server.rehearsal else 'real_model','real_dispatch_enabled':self.server.outbound_enabled and not self.server.rehearsal,'external_network_allowed':self.server.outbound_enabled and not self.server.rehearsal and self.server.http_client_factory is None,'simulated':self.server.rehearsal or self.server.http_client_factory is not None}})
        if self._mode_matches() and self._map():super().do_GET()
    def do_POST(self):
        if self._mode_matches() and self._map():super().do_POST()
    def create(self,token,body):
        if self.server.rehearsal:
            if set(body)-{'learning_preferences'}:raise ABConflict('SDK 预演只使用内置合成资料，可设置每日学习时间')
            body={**SDK_INPUT,**body}
        return super().create(token,body)
    def execute(self,token,stage,*,authorized_factory=None,authorization_id=None):
        if authorized_factory is None:raise ABConflict('此模式必须通过 SDK 单次授权执行')
        return super().execute(token,stage,authorized_factory=authorized_factory,authorization_id=authorization_id)

class SDKWorkflowServer(LocalWorkflowServer):
    handler_class=SDKWorkflowHandler
    authorization_class=SDKAuthorizedAB
    def __init__(self,address,directory,origins,access_key,*,rehearsal=True,outbound_enabled=False,http_client_factory=None,configuration_vault=None):
        if type(rehearsal) is not bool or type(outbound_enabled) is not bool:raise ValueError('SDK 模式参数无效')
        if rehearsal and outbound_enabled:raise ValueError('SDK 预演不能开启真实外发')
        self.rehearsal=rehearsal;self.outbound_enabled=outbound_enabled;self.http_client_factory=http_client_factory
        profile='sdk_rehearsal' if rehearsal else 'real_mode_http_test' if http_client_factory else 'real_model'
        self.session_subdirectory=profile+'_sessions';self.session_namespace='CareerPilotSDK:'+profile+':'
        self.source_kind=profile+'_session'
        self.source_notice='SDK HTTP 预演合成结果，不代表真实模型或个人能力。' if rehearsal or http_client_factory else '真实模型结果，需人工核对，不等于已证实的个人能力。'
        super().__init__(address,Path(directory)/profile,origins,access_key,hunter_factory=blocked_factory,planner_factory=blocked_factory,configuration_vault=configuration_vault)
