"""Owner-hosted A/D sponsorship gateway. Provider Key never reaches judge clients.

Only an authenticated, fixed-model endpoint is exposed. A persistent global
reservation precedes dispatch; timeout/unknown usage remains held. No retries.
Serve behind a TLS reverse proxy; the CLI binds loopback by default.
"""
from contextlib import closing
from datetime import datetime,timezone
from decimal import Decimal,ROUND_CEILING
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import argparse,hashlib,hmac,json,os,re,sqlite3,time,uuid
from judge_ledger import JudgeLedger,GatewayError

LIMIT=200000
LEGACY_STAGES=('a_diagnosis','d_revision')
STAGES=(*LEGACY_STAGES,'e_turn','e_report')

def encode(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(v):return hashlib.sha256(encode(v).encode()).hexdigest()
def charge(n,price):return int((Decimal(n)*Decimal(str(price))).to_integral_value(rounding=ROUND_CEILING))


def validate_agent_messages(body):
    tools=body.get('tools')
    names={'read_context','search_history','search_resources','check_resume_quotes','save_plan',
           'diagnose_job','optimize_resume','start_mock_interview','review_mock_interview'}
    if body.get('tool_choice')!='auto' or not isinstance(tools,list) or not 1<=len(tools)<=9:raise ValueError()
    declared=set()
    for tool in tools:
        if not isinstance(tool,dict) or tool.get('type')!='function' or set(tool)!={'type','function'}:raise ValueError()
        function=tool['function']
        if not isinstance(function,dict) or function.get('name') not in names or not isinstance(function.get('parameters'),dict):raise ValueError()
        if function['name'] in declared:raise ValueError()
        declared.add(function['name'])
    pending=set();used=set()
    for message in body['messages']:
        if not isinstance(message,dict) or set(message)-{'role','content','tool_calls','tool_call_id'}:raise ValueError()
        role=message.get('role')
        content=message.get('content')
        if role=='tool':
            identity=message.get('tool_call_id')
            if identity not in pending or not isinstance(content,str) or 'tool_calls' in message:raise ValueError()
            pending.remove(identity)
            continue
        if pending or role not in ('system','user','assistant') or 'tool_call_id' in message:raise ValueError()
        calls=message.get('tool_calls',[])
        if content is not None and not isinstance(content,str):raise ValueError()
        if not calls and not isinstance(content,str):raise ValueError()
        if calls:
            if role!='assistant' or not isinstance(calls,list) or not 1<=len(calls)<=4:raise ValueError()
            for call in calls:
                if not isinstance(call,dict) or call.get('type')!='function':raise ValueError()
                identity=call.get('id');function=call.get('function')
                if not isinstance(identity,str) or not 1<=len(identity)<=200 or identity in used:raise ValueError()
                if not isinstance(function,dict) or function.get('name') not in declared or not isinstance(function.get('arguments'),str):raise ValueError()
                used.add(identity);pending.add(identity)
    if pending:raise ValueError()

def policy(value):
    fields={'provider','base_url','model','input_price_per_million','output_price_per_million','budget_micro_cny','max_calls','expires_at','max_input_chars','max_output_tokens'}
    optional={'supported_stages','session_budget_micro_cny','tool_calls_supported'}
    if not isinstance(value,dict) or not fields<=set(value)<=fields|optional:raise ValueError('Gateway policy fields invalid')
    p=dict(value);u=urlsplit(p['base_url'])
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:raise ValueError('HTTPS upstream required')
    if not re.fullmatch(r'[A-Za-z0-9_./:\-]{1,160}',p['model']):raise ValueError('Invalid fixed model')
    if not isinstance(p['provider'],str) or not 1<=len(p['provider'])<=80:raise ValueError('Invalid provider')
    for name,low,high in [('budget_micro_cny',1,100000000),('max_calls',1,10000),('max_input_chars',1000,100000),('max_output_tokens',256,4096)]:
        if type(p[name]) is not int or not low<=p[name]<=high:raise ValueError('Invalid gateway limit')
    for name in ('input_price_per_million','output_price_per_million'):
        if type(p[name]) not in (int,float) or not Decimal(str(p[name])).is_finite() or not 0<p[name]<=100000:raise ValueError('Positive configured prices required')
    expiry=datetime.fromisoformat(p['expires_at'].replace('Z','+00:00'))
    if expiry.tzinfo is None:raise ValueError('Expiry timezone required')
    if set(p)&{'supported_stages','session_budget_micro_cny'}:
        stages=p.get('supported_stages');limit=p.get('session_budget_micro_cny')
        if not isinstance(stages,list) or len(stages)!=len(set(stages)) or not set(LEGACY_STAGES)<=set(stages)<=set(STAGES):raise ValueError('Invalid sponsored stages')
        if ('e_turn' in stages)!=('e_report' in stages):raise ValueError('Both interview stages must be enabled together')
        if type(limit) is not int or not 0<limit<=p['budget_micro_cny']:raise ValueError('Invalid session allowance')
    if 'tool_calls_supported' in p and type(p['tool_calls_supported']) is not bool:raise ValueError('Invalid tool calling capability')
    return p

class JudgeGateway:
    def __init__(self,path,settings,access_token,provider_key,*,client_factory=None,clock=time.time,probe_only=False,database_url=None,previous_settings=None):
        if type(probe_only) is not bool:raise ValueError('Invalid probe mode')
        self.probe_only=probe_only
        self.policy=policy(settings);self.path=Path(path) if path is not None else None;self.clock=clock
        if not 24<=len(access_token)<=1024 or any(c.isspace() for c in access_token):raise ValueError('A separate strong judge pass is required')
        if len(provider_key)<8 or any(c.isspace() for c in provider_key) or provider_key==access_token:raise ValueError('Separate provider Key required')
        self.token_hash=hashlib.sha256(access_token.encode()).hexdigest();self.provider_key=provider_key;self.client_factory=client_factory
        self.ledger=JudgeLedger(path,database_url=database_url)
        previous_fingerprint=None;migration=None
        if previous_settings is not None:
            old_policy=policy(previous_settings)
            changed={k for k in set(old_policy)|set(self.policy) if old_policy.get(k)!=self.policy.get(k)}
            allowed={'budget_micro_cny','max_calls','expires_at','max_input_chars','tool_calls_supported'}
            if not changed<=allowed or self.policy['budget_micro_cny']<old_policy['budget_micro_cny'] or self.policy['max_calls']<old_policy['max_calls'] or datetime.fromisoformat(self.policy['expires_at'])<datetime.fromisoformat(old_policy['expires_at']):
                raise ValueError('Only explicitly approved limit increases may migrate the original ledger')
            if self.policy['max_input_chars']<old_policy['max_input_chars'] or old_policy.get('tool_calls_supported',False) and not self.policy.get('tool_calls_supported',False):raise ValueError('Capability migrations must preserve existing limits')
            previous_fingerprint=digest({'settings':old_policy,'token_hash':self.token_hash})
            migration=encode({'version':'limit-increase-v1','previous_policy':old_policy,'new_policy':self.policy,'notice':'All calls, responses, settled charges and unknown holds are retained.'})
        self.ledger.initialize(digest({'settings':self.policy,'token_hash':self.token_hash}),probe_only=probe_only,previous_fingerprint=previous_fingerprint,migration=migration)

    def connect(self):return self.ledger.connect()
    def authenticate(self,authorization):
        given=authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else ''
        if not hmac.compare_digest(hashlib.sha256(given.encode()).hexdigest(),self.token_hash):raise GatewayError(401,'judge_access_denied')
        if self.clock()>=datetime.fromisoformat(self.policy['expires_at'].replace('Z','+00:00')).timestamp():raise GatewayError(410,'judge_access_expired')

    def configuration(self,authorization):
        self.authenticate(authorization);p=self.policy
        stages=p.get('supported_stages',list(LEGACY_STAGES))
        return {'version':'judge-gateway-v2' if 'supported_stages' in p else 'judge-gateway-v1','provider':p['provider'],'model':p['model'],'currency':'CNY','input_price_per_million':p['input_price_per_million'],'output_price_per_million':p['output_price_per_million'],'max_input_chars':p['max_input_chars'],'max_output_tokens':p['max_output_tokens'],'expires_at':p['expires_at'],'supported_stages':stages,'sponsored':True,'budget_micro_cny':p['budget_micro_cny'],**({'tool_calls_supported':True,'agent_business_tools_supported':True} if p.get('tool_calls_supported') else {}),**({'probe_only':True} if self.probe_only else {}),**({'session_budget_micro_cny':p['session_budget_micro_cny']} if 'session_budget_micro_cny' in p else {}),'notice':'作者承担模型费用；每次仍须预览与授权。资料经作者托管网关转发至模型服务商。全体评委共享服务端总额度，失败与未知用量保留占额。'}

    def status(self,authorization):
        self.authenticate(authorization)
        n,total,unknown=self.ledger.status()
        return {'budget_micro_cny':self.policy['budget_micro_cny'],'calls':n,'max_calls':self.policy['max_calls'],'committed_micro_cny':total,'unknown_held_micro_cny':unknown,'available_micro_cny':max(0,self.policy['budget_micro_cny']-total),'expires_at':self.policy['expires_at']}

    def validate(self,raw,stage,rid):
        agent=stage=='career_agent' and self.policy.get('tool_calls_supported') is True
        if not (agent or stage in self.policy.get('supported_stages',LEGACY_STAGES)) or not re.fullmatch(r'[0-9a-f]{64}',rid):raise GatewayError(400,'invalid_stage_or_request')
        try:
            def pairs(rows):
                result={}
                for k,v in rows:
                    if k in result:raise ValueError()
                    result[k]=v
                return result
            body=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            allowed={'model','messages','max_tokens','max_completion_tokens','temperature','response_format','thinking','reasoning_effort'}
            if agent:allowed|={'tools','tool_choice'}
            if not isinstance(body,dict) or not {'model','messages'}<=set(body)<=allowed:raise ValueError()
            p=self.policy
            if body['model']!=p['model'] or len(raw.decode('utf-8'))>p['max_input_chars']:raise ValueError()
            caps=[body[k] for k in ('max_tokens','max_completion_tokens') if k in body]
            if len(caps)!=1 or type(caps[0]) is not int or not 1<=caps[0]<=p['max_output_tokens']:raise ValueError()
            messages=body['messages']
            if not isinstance(messages,list) or not 1<=len(messages)<=(64 if agent else 4):raise ValueError()
            if agent:validate_agent_messages(body)
            elif any(not isinstance(m,dict) or set(m)!={'role','content'} or m['role'] not in ('system','user','assistant') or not isinstance(m['content'],str) for m in messages):raise ValueError()
            if 'thinking' in body and body['thinking']!={'type':'disabled'}:raise ValueError()
            if 'response_format' in body and body['response_format']!={'type':'json_object'}:raise ValueError()
            if 'temperature' in body and (type(body['temperature']) not in (int,float) or not 0<=body['temperature']<=2):raise ValueError()
            if 'reasoning_effort' in body and body['reasoning_effort']!='none':raise ValueError()
            reserve=charge(len(raw)+2048,p['input_price_per_million'])+charge(caps[0],p['output_price_per_million'])
            return body,reserve
        except (ValueError,TypeError,KeyError,UnicodeError):raise GatewayError(400,'invalid_model_request') from None

    def complete(self,authorization,raw,stage,rid):
        if self.probe_only:raise GatewayError(503,'probe_only_no_model_dispatch')
        self.authenticate(authorization);body,reserve=self.validate(raw,stage,rid);body_hash=digest({'body':body,'stage':stage})
        cached=self.ledger.reserve(rid,body_hash,stage,reserve,self.clock(),self.policy)
        if cached is not None:
            try:return json.loads(cached)
            except (ValueError,TypeError):raise GatewayError(503,'ledger_receipt_invalid_no_dispatch') from None
        # Reserve is committed before any external client exists. No logs contain inputs/Keys.
        result=None;cost=None
        try:
            import httpx
            client=self.client_factory() if self.client_factory else httpx.Client(transport=httpx.HTTPTransport(retries=0),follow_redirects=False,trust_env=False,timeout=90)
            with client:
                with client.stream('POST',self.policy['base_url'].rstrip('/')+'/chat/completions',content=raw,headers={'Authorization':'Bearer '+self.provider_key,'Content-Type':'application/json','Accept':'application/json'}) as response:
                    received=bytearray()
                    for part in response.iter_bytes():
                        received.extend(part)
                        if len(received)>1000000:raise GatewayError(502,'upstream_response_too_large')
                    if response.status_code!=200:raise GatewayError(502,'upstream_failed_usage_unknown')
                    result=json.loads(received)
            u=result.get('usage',{});a=u.get('prompt_tokens');b=u.get('completion_tokens')
            if type(a) is not int or type(b) is not int or min(a,b)<0 or u.get('total_tokens')!=a+b:raise GatewayError(502,'upstream_usage_unknown')
            cost=charge(a,self.policy['input_price_per_million'])+charge(b,self.policy['output_price_per_million'])
            # Never return headers or raw provider errors; redact accidental Key echo.
            if self.provider_key in encode(result):raise GatewayError(502,'upstream_secret_echo_blocked')
            if not isinstance(result.get('choices'),list) or len(result['choices'])!=1:raise GatewayError(502,'upstream_invalid_response')
        except Exception as exc:
            self.ledger.finish(rid,status='unknown',cost=cost)
            if isinstance(exc,GatewayError):raise
            raise GatewayError(502,'upstream_unavailable_usage_held') from None
        self.ledger.finish(rid,status='completed',cost=cost,response=encode(result))
        return result

class GatewayServer(ThreadingHTTPServer):
    daemon_threads=False
    def __init__(self,address,gateway):self.gateway=gateway;super().__init__(address,GatewayHandler)

class GatewayHandler(BaseHTTPRequestHandler):
    server_version='ShijieJudgeGateway/1'
    def log_message(self,*_):pass
    def setup(self):super().setup();self.connection.settimeout(100)
    def reply(self,status,value):
        raw=encode(value).encode();self.send_response(status)
        for k,v in {'Content-Type':'application/json; charset=utf-8','Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}.items():self.send_header(k,v)
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        try:
            if self.path=='/health':
                self.server.gateway.ledger.check()
                return self.reply(200,{'service':'shijie-judge-gateway','version':2,'ledger_backend':self.server.gateway.ledger.backend,'ledger_ready':True,'model_dispatch_enabled':not self.server.gateway.probe_only})
            if self.path=='/judge/status':return self.reply(200,self.server.gateway.status(self.headers.get('Authorization','')))
            if self.path!='/judge/config':raise GatewayError(404,'not_found')
            self.reply(200,self.server.gateway.configuration(self.headers.get('Authorization','')))
        except GatewayError as e:self.reply(e.status,{'error':{'code':e.code,'message':e.code}})
    def do_POST(self):
        try:
            if self.path!='/v1/chat/completions':raise GatewayError(404,'not_found')
            if self.headers.get('Transfer-Encoding') or self.headers.get_content_type()!='application/json':raise GatewayError(400,'invalid_content')
            try:n=int(self.headers.get('Content-Length','-1'))
            except ValueError:raise GatewayError(400,'invalid_length')
            if not 0<n<=LIMIT:raise GatewayError(413,'request_too_large')
            raw=self.rfile.read(n)
            if len(raw)!=n:raise GatewayError(400,'incomplete_body')
            # Consume the bounded body before replying: unread POST bytes can
            # reset a Windows TCP connection and hide the 401 from the client.
            self.server.gateway.authenticate(self.headers.get('Authorization',''))
            self.reply(200,self.server.gateway.complete(self.headers.get('Authorization',''),raw,self.headers.get('X-Shijie-Stage',''),self.headers.get('X-Shijie-Request-ID','')))
        except GatewayError as e:self.close_connection=True;self.reply(e.status,{'error':{'code':e.code,'message':e.code}})

def main():
    p=argparse.ArgumentParser(description='拾阶评委额度网关；密钥仅留在维护者服务端')
    p.add_argument('--policy',type=Path,required=True);p.add_argument('--ledger',type=Path)
    p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8080)
    p.add_argument('--owner-preparation',type=Path,help='Windows维护者已有加密模型配置目录')
    p.add_argument('--judge-pass-file',type=Path,help='仅维护者当前Windows用户可解密的评委通行证')
    p.add_argument('--stop-file',type=Path,help='维护者本机正常停止信号，不开放公网停止接口')
    p.add_argument('--probe-only',action='store_true',help='仅连接测试；拒绝所有模型派发')
    p.add_argument('--previous-policy',type=Path,help='显式授权的原策略，仅保留账本增加额度/次数/期限')
    a=p.parse_args()
    try:
        settings=json.loads(a.policy.read_text(encoding='utf-8'))
        if a.owner_preparation or a.judge_pass_file:
            if not(a.owner_preparation and a.judge_pass_file):raise ValueError('Both private owner options required')
            from judge_operator_secrets import owner_secrets
            access,key=owner_secrets(a.owner_preparation,a.judge_pass_file,settings)
        else:access,key=os.environ.get('SHIJIE_JUDGE_PASS',''),os.environ.get('SHIJIE_PROVIDER_KEY','')
        database_url=os.environ.get('SHIJIE_DATABASE_URL')
        if database_url and a.ledger:raise ValueError('Choose Postgres or explicit local ledger, not both')
        g=JudgeGateway(a.ledger,settings,access,key,probe_only=a.probe_only,database_url=database_url,previous_settings=json.loads(a.previous_policy.read_text(encoding='utf-8')) if a.previous_policy else None)
        server=GatewayServer((a.host,a.port),g);print('Judge gateway ready. No model request until authenticated execution.',flush=True)
        if a.stop_file:
            import threading
            def watch():
                while not a.stop_file.exists():time.sleep(.5)
                server.shutdown()
            threading.Thread(target=watch,daemon=True).start()
        server.serve_forever()
        server.server_close()
    except (ValueError,OSError):raise SystemExit('Gateway startup failed; verify database connection, policy, secrets and retained ledger. No secrets printed.')

if __name__=='__main__':main()
