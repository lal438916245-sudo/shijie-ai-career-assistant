"""Loopback-only production asset server. No Vite, Node or owner paths required."""
from contextlib import ExitStack
from functools import partial
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,unquote
import argparse,hashlib,http.client,json,mimetypes,os,secrets,shutil,subprocess,sys,threading,time,uuid,webbrowser

BUILD='career-pilot-business-agent-20261127-v3'
APPROOT=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
BODY_LIMIT=400000
SAFE_CONFIG={'provider':'本地体验（模拟计价，非服务商验证）','base_url':'https://api.deepseek.com','model':'deepseek-flash','max_input_chars':16000,'max_output_tokens':16000,'timeout_seconds':60,'currency':'CNY','input_price_per_million':2,'output_price_per_million':8,'output_token_parameter':'max_tokens','temperature':0.7}

def default_data():
    base=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))
    return base/'CareerPilotCompetition'/'20261113'

def read_json(path):return json.loads(path.read_text(encoding='utf-8'))
def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,path)

def seed_data(data,root=APPROOT):
    """Copy only allowlisted fictional replay; never settings, personal DBs or keys."""
    manifest=read_json(root/'seed'/'manifest.json')
    assert manifest['build'] in (BUILD,'career-pilot-windows-20261113-v1','career-pilot-agent-20261126-v1','career-pilot-unified-model-20261126-v2') and len(manifest['files'])==2
    for name,expected in manifest['files'].items():
        rel=Path(name)
        if rel.is_absolute() or '..' in rel.parts or rel.parts[0]!='showcase_sessions_20261107':raise ValueError('Invalid seed manifest')
        source=root/'seed'/rel;destination=data/rel
        if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:raise ValueError('演示资料校验失败，请重新解压完整提交包。')
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest()!=expected:raise ValueError('演示快照变化，原数据保留，请联系维护者。')
        else:
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
    from unified_model import UnifiedModelPreparation
    preparation=UnifiedModelPreparation(data)
    preparation._read()
    from showcase_replay import prepare_replay
    return prepare_replay(data)

class PublicServer(ThreadingHTTPServer):
    # Shutdown waits for proxy requests, while internal services are still alive.
    daemon_threads=False
    def __init__(self,address,root,instance):
        super().__init__(address,PublicHandler)
        self.root=root;self.instance=instance;self.backends={};self.origin=f'http://127.0.0.1:{self.server_port}'

class PublicHandler(BaseHTTPRequestHandler):
    server_version='CareerPilotDelivery/1'
    def log_message(self,*_):pass
    def setup(self):super().setup();self.connection.settimeout(240)
    def send_bytes(self,status,raw,kind='application/json; charset=utf-8',cache='no-store',head=False):
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control',cache);self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY');self.end_headers()
        if not head:self.wfile.write(raw)
    def error(self,status,message):
        self.close_connection=True
        self.send_bytes(status,json.dumps({'error':message},ensure_ascii=False).encode('utf-8'))
    def allowed(self,write=False):
        # Reject DNS rebinding, foreign origins, cross-site reads and capability injection.
        if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}':return False
        origin=self.headers.get('Origin')
        return (origin==self.server.origin if write else origin in (None,self.server.origin)) and self.headers.get('Sec-Fetch-Site')!='cross-site'
    def do_GET(self):self.route()
    def do_HEAD(self):self.route(head=True)
    def do_POST(self):self.route(write=True)
    def do_OPTIONS(self):self.error(403,'不开放跨域接口。')
    def route(self,write=False,head=False):
        if not self.allowed(write):return self.error(403,'仅允许本机页面访问。')
        path=urlsplit(self.path)
        if path.path=='/__release/health' and not write and not path.query:
            return self.send_bytes(200,json.dumps({'build':BUILD,'instance':self.server.instance,'ready':bool(self.server.backends),'outbound_enabled':self.server.outbound},ensure_ascii=False).encode(),head=head)
        if path.path.startswith('/api/'):
            if head:return self.error(405,'不支持此方法。')
            key=next((k for k in ('/api/live/','/api/sdk/') if path.path.startswith(k)),None)
            if not key:return self.error(404,'接口不存在。')
            raw=None
            if write:
                if self.headers.get('Transfer-Encoding'):return self.error(400,'不支持分块请求。')
                try:length=int(self.headers.get('Content-Length','-1'))
                except ValueError:return self.error(400,'请求长度无效。')
                if not 0<=length<=BODY_LIMIT:return self.error(413,'请求资料过长。')
                if self.headers.get_content_type()!='application/json':return self.error(400,'需要JSON请求。')
                raw=self.rfile.read(length)
                if len(raw)!=length:return self.error(400,'请求尚未完整收到。')
            backend=self.server.backends[key]
            headers={'X-CP-Local-Key':self.server.access,'Content-Type':'application/json','Origin':self.server.origin}
            for name in ('X-CP-Session','X-CP-SDK-Mode'):
                if self.headers.get(name):headers[name]=self.headers[name]
            connection=http.client.HTTPConnection('127.0.0.1',backend.server_port,timeout=230)
            try:
                connection.request('POST' if write else 'GET',self.path,body=raw,headers=headers)
                response=connection.getresponse();body=response.read(4000000)
                return self.send_bytes(response.status,body,response.getheader('Content-Type','application/json; charset=utf-8'))
            except (OSError,http.client.HTTPException):return self.error(503,'接口暂不可用，请保留原操作并查询回执，不要重复执行。')
            finally:connection.close()
        if write:return self.error(404,'接口不存在。')
        relative=unquote(path.path).lstrip('/') or 'index.html'
        target=(self.server.root/'web'/relative).resolve();web=(self.server.root/'web').resolve()
        if not target.is_relative_to(web) or not target.is_file():return self.error(404,'文件不存在。')
        kind=mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
        # Windows registry mime mappings can give .js text/plain; use web types explicitly.
        kind={'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.html':'text/html'}.get(target.suffix,kind)
        self.send_bytes(200,target.read_bytes(),kind,head=head)

def deny_external_network():
    """Verification-only guard: even an accidental SDK path cannot leave loopback."""
    import socket
    connect=socket.socket.connect;lookup=socket.getaddrinfo
    def local(address):
        if isinstance(address,tuple) and address[0] not in ('127.0.0.1','localhost','::1'):raise OSError('Verification blocks external network')
    def guarded(self,address):local(address);return connect(self,address)
    def dns(host,*args,**kwargs):
        if host not in ('127.0.0.1','localhost','::1',None):raise OSError('Verification blocks external DNS')
        return lookup(host,*args,**kwargs)
    socket.socket.connect=guarded;socket.getaddrinfo=dns

def serve(data,port=0,allow_real_calls=False,offline=False,root=APPROOT):
    if offline:
        if allow_real_calls:raise ValueError('离线验证不能开放真实模型。')
        deny_external_network()
    from workflow_lease import DirectoryLease
    from live_session_http import LocalWorkflowServer
    from sdk_workflow import SDKWorkflowServer
    data.mkdir(parents=True,exist_ok=True)
    lease=DirectoryLease(data/'service');servers=[];workers=[]
    instance=uuid.uuid4().hex;public=None
    try:
        if port:public=PublicServer(('127.0.0.1',port),root,instance)
        else:
            # Stable first choice keeps browser-local personal session identities after restart.
            for candidate in range(5180,5201):
                try:public=PublicServer(('127.0.0.1',candidate),root,instance);break
                except OSError:continue
            if public is None:raise RuntimeError('5180～5200端口均被占用，请关闭旧实例或联系维护者。')
        public.outbound=allow_real_calls;access=secrets.token_hex(32);public.access=access
        live=LocalWorkflowServer(('127.0.0.1',0),data,{public.origin},access,
          hunter_factory=lambda *_:(_ for _ in ()).throw(RuntimeError('Use per-call authorization')),
          planner_factory=lambda *_:(_ for _ in ()).throw(RuntimeError('Use per-call authorization')),
          ced_sdk_rehearsal=True,workbench_case_profile='final-20261107',contract_sdk_rehearsal=True,session_outbound_enabled=allow_real_calls)
        servers.append(live)
        seed_data(data,root)
        sdk=SDKWorkflowServer(('127.0.0.1',0),data,{public.origin},access,rehearsal=False,outbound_enabled=allow_real_calls)
        sdk.preparation=live.preparation;servers.append(sdk)
        public.backends={'/api/live/':live,'/api/sdk/':sdk};servers.append(public)
        for server in servers:
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();workers.append(worker)
        state={'build':BUILD,'instance':instance,'pid':os.getpid(),'origin':public.origin,'root':str(root),'outbound_enabled':allow_real_calls}
        write_json(data/'service'/'instance.json',state)
        stop=data/'service'/('stop-'+instance+'.flag')
        while not stop.exists():time.sleep(.2)
        # Allow active writes/calls to finish before releasing service leases.
        while True:
            active=False
            for server in (live,sdk):
                with server.guard:active=active or bool(server.active or server.reservations or server.active_authorizations)
            if not active:break
            time.sleep(.2)
    finally:
        for server in reversed(servers):
            if servers.index(server)<len(workers):server.shutdown()
            server.server_close()
        for worker in workers:worker.join(timeout=10)
        if public and public not in servers:public.server_close()
        lease.close()
        (data/'service'/('stopped-'+instance+'.flag')).touch()

def healthy(data):
    try:
        state=read_json(data/'service'/'instance.json')
        if state['build']!=BUILD or state['root']!=str(APPROOT):return None
        url=urlsplit(state['origin'])
        if url.hostname!='127.0.0.1' or url.scheme!='http' or not 1<=url.port<=65535:return None
        conn=http.client.HTTPConnection('127.0.0.1',url.port,timeout=2)
        try:
            conn.request('GET','/__release/health');r=conn.getresponse();value=json.loads(r.read(10000))
            return state if r.status==200 and value=={'build':BUILD,'instance':state['instance'],'ready':True,'outbound_enabled':state['outbound_enabled']} else None
        finally:conn.close()
    except (OSError,ValueError,KeyError,TypeError,http.client.HTTPException):return None

def command(action,data,port=0,allow_real_calls=False,offline=False,browser=True):
    state=healthy(data)
    if action=='status':
        if not state:raise RuntimeError('服务未运行，请双击“一键启动”。')
        print('两个入口已就绪：'+state['origin']+'/#welcome');return state
    if action=='stop':
        if not state:print('没有本包正在运行的服务；未关闭其他程序。');return
        (data/'service'/('stop-'+state['instance']+'.flag')).touch()
        for _ in range(150):
            if (data/'service'/('stopped-'+state['instance']+'.flag')).exists():print('已正常停止，个人资料和记录保留。');return
            time.sleep(.2)
        raise RuntimeError('仍有操作进行中，已请求正常停止；请稍候，未强制结束。')
    if not state:
        data.mkdir(parents=True,exist_ok=True);(data/'service').mkdir(exist_ok=True)
        cmd=([sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(APPROOT/'scripts'/'delivery_launcher.py')])+['serve','--data-dir',str(data)]
        if port:cmd+=['--port',str(port)]
        if allow_real_calls:cmd+=['--allow-real-calls']
        if offline:cmd+=['--offline-verification']
        options={}
        if os.name=='nt':
            si=subprocess.STARTUPINFO();si.dwFlags|=subprocess.STARTF_USESHOWWINDOW;si.wShowWindow=subprocess.SW_HIDE
            options={'startupinfo':si,'creationflags':subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP}
        # No inherited provider keys; settings are managed only by backend DPAPI.
        env=os.environ.copy()
        for name in ('AI_API_KEY','OPENAI_API_KEY','DEEPSEEK_API_KEY','SHIJIE_PROVIDER_KEY','SHIJIE_JUDGE_PASS','CP_WORKFLOW_PREVIEW_KEY','PYTHONPATH','PYTHONHOME'):env.pop(name,None)
        with (data/'service'/'startup.log').open('ab') as log:
            child=subprocess.Popen(cmd,cwd=APPROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,close_fds=True,**options)
        for _ in range(180):
            state=healthy(data)
            if state:break
            if child.poll() is not None:raise RuntimeError('服务启动失败；请查看数据目录service/startup.log。')
            time.sleep(.25)
        if not state:raise RuntimeError('服务尚未就绪，请稍候检查状态，不要重复执行模型请求。')
    elif allow_real_calls!=state['outbound_enabled']:
        raise RuntimeError('服务已在另一外发模式运行，请先正常停止；不会静默切换模式。')
    url=state['origin']+'/#welcome'
    print('两个入口已就绪：'+url)
    print('启动不调用模型。'+('真实模式须由主机配置Key并逐次授权。' if state['outbound_enabled'] else '默认关闭真实外发，本地体验模型费用0元。'))
    print('数据目录：'+str(data))
    if browser:webbrowser.open(url,new=2)
    return state

def configure(data):
    """Local operator setup, no credential in argv, logs, frontend or distribution."""
    import getpass
    from unified_model import UnifiedModelPreparation as ModelPreparation
    if healthy(data):raise RuntimeError('请先正常停止本提交版，再修改模型配置，旧会话与费用保留。')
    print('仅在本机保存配置，不测试服务商，不调用模型。Key经当前Windows用户DPAPI加密。')
    print('已有会话绑定原配置，配置变化后请新建会话。请按服务商控制台填写模型和单价。')
    prep=ModelPreparation(data);old=prep._read();conf=dict(SAFE_CONFIG)
    def ask(label,default):return input(label+' ['+str(default)+']：').strip() or default
    conf['provider']=ask('服务商名称','DeepSeek')
    conf['base_url']=ask('API地址','https://api.deepseek.com')
    conf['model']=ask('模型标识（以服务商为准）','deepseek-flash')
    conf['input_price_per_million']=float(input('每百万输入tokens价格（人民币，须大于0）：').strip())
    conf['output_price_per_million']=float(input('每百万输出tokens价格（人民币，须大于0）：').strip())
    if min(conf['input_price_per_million'],conf['output_price_per_million'])<=0:raise ValueError('预算单价必须大于0。')
    key=getpass.getpass('API Key（隐藏输入，不要发送到聊天）：').strip()
    if not key:raise ValueError('没有输入Key，未保存。')
    prep.save({'config':conf,'api_key':key,'key_action':'replace','expected_revision':old['revision']})
    print('已在本机加密保存，未发送模型请求。使用“真实模型启动”后仍须网页逐次授权。')

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    p=argparse.ArgumentParser(description='拾阶——AI 求职准备助手 Windows本地交付版')
    p.add_argument('action',nargs='?',default='start',choices=('start','serve','stop','status','configure'))
    p.add_argument('--data-dir',type=Path,default=default_data());p.add_argument('--port',type=int,default=0)
    p.add_argument('--allow-real-calls',action='store_true');p.add_argument('--offline-verification',action='store_true');p.add_argument('--no-browser',action='store_true')
    p.add_argument('--judge-access',type=Path,help='维护者预置的限额评委连接文件；不含服务商Key')
    a=p.parse_args();data=a.data_dir.resolve()
    if not 0<=a.port<=65535:p.error('端口无效')
    if a.offline_verification and a.allow_real_calls:p.error('离线验证不允许真实外发')
    try:
        if not a.judge_access and a.action in ('start','serve') and a.allow_real_calls and not a.offline_verification:
            from unified_model import UnifiedModelPreparation
            preparation=UnifiedModelPreparation(data)
            if preparation.status()['model_source']=='platform' and (APPROOT/'judge-access.json').is_file():
                from judge_client import import_access
                try:import_access(data,APPROOT/'judge-access.json')
                except (ValueError,OSError):print('平台连接暂不可用，可在成长概览填写自己的模型连接。',flush=True)
        if a.judge_access:
            if a.offline_verification or a.action not in ('start','serve'):raise ValueError('评委连接仅用于联网启动；不调用模型的离线模式不可启用。')
            from judge_client import import_access
            print('正在连接评委服务，不调用模型；免费服务唤醒可能需要约一分钟。',flush=True)
            import_access(data,a.judge_access.resolve())
            a.allow_real_calls=True
            print('评委连接已就绪，未调用模型。作者承担已开放步骤的费用，每次仍须预览与授权。')
        if a.action=='configure':configure(data)
        elif a.action=='serve':serve(data,a.port,a.allow_real_calls,a.offline_verification)
        else:command(a.action,data,a.port,a.allow_real_calls,a.offline_verification,not a.no_browser)
    except Exception as exc:print('操作未完成：'+str(exc),file=sys.stderr);return 1
    return 0
