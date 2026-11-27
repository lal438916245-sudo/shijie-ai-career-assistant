"""Import an owner-issued, limited judge pass. Never import the owner's API Key."""
from pathlib import Path
from urllib.parse import urlsplit
import hashlib,json,threading
from model_preparation import ModelPreparation,validate_config

def fingerprint(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def sponsored_policy(preparation):
    if hasattr(preparation,'platform_policy'):return preparation.platform_policy()
    # Existing in-memory preparation adapters have no on-disk sponsorship file.
    if getattr(preparation,'path',None) is None:return None
    path=preparation.path.parent/'judge-policy.json'
    if not path.exists():return None
    try:
        data=json.loads(path.read_text(encoding='utf-8'));current=preparation._read()
        if data['version'] not in ('judge-gateway-v1','judge-gateway-v2') or data['config_digest']!=fingerprint(current['config']):return None
        return {k:data[k] for k in ('version','sponsored','supported_stages','expires_at','budget_micro_cny','notice')} | ({'session_budget_micro_cny':data['session_budget_micro_cny']} if 'session_budget_micro_cny' in data else {})
    except (KeyError,ValueError,TypeError):raise ValueError('评委配置损坏，未自动重置或调用模型。') from None

def import_access(directory,path,*,client_factory=None,allow_local_test=False):
    import httpx
    body=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(body,dict) or set(body)!={'version','gateway_url','access_pass'} or body['version']!=1:raise ValueError('评委连接文件无效。')
    url=body['gateway_url'];token=body['access_pass'];u=urlsplit(url)
    if not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/') or (u.scheme!='https' and not(allow_local_test and u.scheme=='http' and u.hostname=='127.0.0.1')):raise ValueError('评委网关须为HTTPS源地址。')
    if not isinstance(token,str) or not 24<=len(token)<=1024 or any(c.isspace() for c in token):raise ValueError('评委访问凭证无效。')
    client=client_factory() if client_factory else httpx.Client(timeout=90,follow_redirects=False,trust_env=False)
    try:
        with client:
            r=client.get(url.rstrip('/')+'/judge/config',headers={'Authorization':'Bearer '+token})
            if r.status_code!=200 or len(r.content)>10000:raise ValueError('评委服务未就绪、凭证已过期或暂不可用；未调用模型。')
            try:meta=r.json()
            except ValueError:raise ValueError('评委服务仍在启动或响应异常；未保存配置、未调用模型，请稍后重新启动。') from None
    except httpx.HTTPError:raise ValueError('无法连接评委网关；未调用模型，可改用普通启动查看演示。') from None
    if meta.get('probe_only'):raise ValueError('网关正在连接测试模式，尚未开放真实模型；未保存为可用模型配置。')
    stages=meta.get('supported_stages');version=meta.get('version')
    valid=version=='judge-gateway-v1' and stages==['a_diagnosis','d_revision']
    if version=='judge-gateway-v2' and isinstance(stages,list):
        valid=len(stages)==len(set(stages)) and {'a_diagnosis','d_revision'}<=set(stages)<={'a_diagnosis','d_revision','e_turn','e_report'} and (('e_turn' in stages)==('e_report' in stages)) and type(meta.get('session_budget_micro_cny')) is int and 0<meta['session_budget_micro_cny']<=meta.get('budget_micro_cny',0)
    if not valid or meta.get('sponsored') is not True or meta.get('currency')!='CNY':raise ValueError('评委服务合同不兼容。')
    from model_preparation import DEFAULT
    conf=validate_config({**DEFAULT,'provider':('评委网关v2 · ' if version=='judge-gateway-v2' else '评委免配置 · ')+meta['provider'],'base_url':url.rstrip('/')+'/v1','model':meta['model'],'input_price_per_million':meta['input_price_per_million'],'output_price_per_million':meta['output_price_per_million'],'max_input_chars':meta['max_input_chars'],'max_output_tokens':meta['max_output_tokens'],'timeout_seconds':100,**({'temperature':None} if version=='judge-gateway-v2' else {})})
    from unified_model import UnifiedModelPreparation
    prep=UnifiedModelPreparation(directory)
    sponsor={k:meta[k] for k in ('version','sponsored','supported_stages','expires_at','budget_micro_cny','notice')}
    if 'session_budget_micro_cny' in meta:sponsor['session_budget_micro_cny']=meta['session_budget_micro_cny']
    sponsor['tool_calls_supported']=meta.get('tool_calls_supported',False)
    sponsor['agent_business_tools_supported']=meta.get('agent_business_tools_supported',False)
    prep.install_platform(conf,token,sponsor)
    return sponsor
