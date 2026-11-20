"""Local configuration and disclosure only. No SDK clients or network calls."""
import base64
import ctypes
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import urlsplit

class PreparationError(ValueError):pass
class PreparationConflict(PreparationError):pass

class WindowsVault:
    """DPAPI current-user scope; never falls back to plaintext."""
    def _convert(self,data,protect):
        if os.name!='nt':raise PreparationError('当前系统不支持本机加密存储，未保存密钥')
        from ctypes import wintypes
        class Blob(ctypes.Structure):
            _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_ubyte))]
        buffer=ctypes.create_string_buffer(data)
        incoming=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));out=Blob()
        crypto=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        function=crypto.CryptProtectData if protect else crypto.CryptUnprotectData
        function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        function.restype=wintypes.BOOL
        kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
        if not function(ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(out)):
            raise PreparationError('本机密钥加密或读取失败，请重新配置')
        try:return ctypes.string_at(out.pbData,out.cbData)
        finally:kernel.LocalFree(out.pbData)
    def seal(self,value):return base64.b64encode(self._convert(value.encode('utf-8'),True)).decode('ascii')
    def open(self,value):return self._convert(base64.b64decode(value,validate=True),False).decode('utf-8')

DEFAULT={'provider':'','base_url':'','model':'','max_input_chars':120000,'max_output_tokens':2048,'timeout_seconds':60,'currency':'CNY','input_price_per_million':None,'output_price_per_million':None,'output_token_parameter':'max_tokens','temperature':0.7}

def validate_config(value):
    if not isinstance(value,dict) or not set(DEFAULT)-{'output_token_parameter','temperature'}<=set(value)<=set(DEFAULT):raise PreparationError('配置字段不完整')
    c={**DEFAULT,**value}
    if c['output_token_parameter'] not in ('max_tokens','max_completion_tokens'):raise PreparationError('SDK 输出参数无效')
    if c['temperature'] is not None and (type(c['temperature']) not in (int,float) or not math.isfinite(c['temperature']) or not 0<=c['temperature']<=2):raise PreparationError('temperature 须为空或 0 到 2 之间')
    if not isinstance(c['provider'],str) or not 1<=len(c['provider'].strip())<=80:raise PreparationError('请填写服务商名称')
    c['provider']=c['provider'].strip()
    if not isinstance(c['model'],str) or not re.fullmatch(r'[A-Za-z0-9_./:\-]{1,160}',c['model']):raise PreparationError('请填写有效模型标识')
    try:
        u=urlsplit(c['base_url'])
        if not u.hostname or u.username or u.password or u.query or u.fragment or u.port==0:raise ValueError()
        if u.scheme!='https' and not (u.scheme=='http' and u.hostname in ('127.0.0.1','localhost','::1')):raise ValueError()
        if any(ch.isspace() for ch in c['base_url']) or len(c['base_url'])>400:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise PreparationError('服务地址须为 HTTPS；本机地址可用 HTTP，不含凭据、查询参数或片段') from None
    c['base_url']=c['base_url'].rstrip('/')
    for k,low,high in [('max_input_chars',1000,200000),('max_output_tokens',256,16000),('timeout_seconds',5,180)]:
        if type(c[k]) is not int or not low<=c[k]<=high:raise PreparationError('请求长度、输出量或超时设置超出范围')
    if c['currency'] not in ('CNY','USD'):raise PreparationError('请选择费用币种')
    for k in ('input_price_per_million','output_price_per_million'):
        x=c[k]
        if x is not None and (type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=100000):raise PreparationError('单价须为空或有限的非负数')
    return c

class ModelPreparation:
    def __init__(self,directory,vault=None):
        self.path=Path(directory)/'model-preparation'/'settings.json';self.vault=vault or WindowsVault();self.lock=threading.RLock()
    def _read(self):
        if not self.path.exists():return {'version':1,'revision':0,'config':dict(DEFAULT),'encrypted_key':None}
        try:
            d=json.loads(self.path.read_text(encoding='utf-8'))
            if d['version']!=1 or type(d['revision']) is not int or d['revision']<1:raise ValueError()
            d['config']=validate_config(d['config'])
            if d['encrypted_key'] is not None and not isinstance(d['encrypted_key'],str):raise ValueError()
            return d
        except (ValueError,TypeError,KeyError):raise PreparationError('本机模型配置损坏，原文件已保留，未自动重置') from None
    def status(self):
        with self.lock:
            d=self._read();state='missing'
            if d['encrypted_key']:
                try:state='saved' if self.vault.open(d['encrypted_key']) else 'unreadable'
                except Exception:state='unreadable'
            return {'source_kind':'model_preparation_only','revision':d['revision'],'config':d['config'],'key_state':state,'configured':d['revision']>0,'sdk_installed':importlib.util.find_spec('openai') is not None,'dispatch_enabled':False,'authorized':False,'automatic_retries':0,'notice':'只检查本机配置，未验证 Key、额度、模型存在性或服务连通性；当前没有真实模型调用入口。'}
    def save(self,body):
        if not isinstance(body,dict) or set(body)!={'config','api_key','key_action','expected_revision'}:raise PreparationError('配置请求字段无效')
        config=validate_config(body['config']);key=body['api_key'];action=body['key_action']
        if action not in ('keep','replace','delete') or not isinstance(key,str):raise PreparationError('密钥操作无效')
        if (action=='replace' and (not 8<=len(key)<=4096 or any(x.isspace() for x in key))) or (action!='replace' and key):raise PreparationError('请输入有效密钥，或选择保留／删除')
        with self.lock:
            old=self._read()
            if type(body['expected_revision']) is not int or old['revision']!=body['expected_revision']:raise PreparationConflict('配置已变化，请重新读取后再保存')
            encrypted=old['encrypted_key']
            if action=='delete' or config['base_url']!=old['config']['base_url'] or config['provider']!=old['config']['provider']:encrypted=None
            if action=='replace':encrypted=self.vault.seal(key)
            new={'version':1,'revision':old['revision']+1,'config':config,'encrypted_key':encrypted}
            self.path.parent.mkdir(parents=True,exist_ok=True)
            fd,temp=tempfile.mkstemp(prefix='.settings-',dir=self.path.parent)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(new,f,ensure_ascii=False,allow_nan=False);f.flush();os.fsync(f.fileno())
                os.replace(temp,self.path)
            finally:
                if os.path.exists(temp):os.unlink(temp)
            return self.status()
    def preview(self,stage,meta,diagnosis):
        status=self.status();c=status['config']
        if stage=='diagnosis':parts={k:meta['inputs'][k] for k in ('target_role','resume_text','jd_text')}
        elif stage=='plan':
            if not diagnosis:raise PreparationError('请先保存诊断，才能预览计划生成的资料范围')
            parts={'diagnosis_audit':diagnosis['audit'],'gap_catalog':diagnosis['gaps'],'available_days':meta['inputs']['available_days']}
            if meta['inputs'].get('learning_preferences') is not None:parts['learning_preferences']=meta['inputs']['learning_preferences']
        else:raise PreparationError('仅支持诊断和学习计划的准备预览')
        fields=[];characters=0
        for name,value in parts.items():
            text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,sort_keys=True)
            characters+=len(text);fields.append({'name':name,'characters':len(text),'sha256':hashlib.sha256(text.encode('utf-8')).hexdigest()})
        estimate=math.ceil(characters/2);prices_known=c['input_price_per_million'] is not None and c['output_price_per_million'] is not None
        cost=(estimate*c['input_price_per_million']+c['max_output_tokens']*c['output_price_per_million'])/1000000 if prices_known else None
        return {'source_kind':'model_preparation_only','stage':stage,'revision':status['revision'],'provider':c['provider'],'destination':c['base_url'],'model':c['model'],'fields':fields,'input_characters':characters,'input_limit_exceeded':characters>c['max_input_chars'],'estimated_input_tokens':estimate,'max_output_tokens':c['max_output_tokens'],'timeout_seconds':c['timeout_seconds'],'estimated_cost':cost,'currency':c['currency'],'automatic_retries':0,'authorized':False,'dispatch_enabled':False,'key_state':status['key_state'],'session_source_kind':'local_workflow_double','notice':'拟发送范围草案，仅本机计算；未发送、未授权。最终提示词和请求组装尚未接入，须在真实调用前再次核对。','cost_notice':'按每 2 字符约 1 token 粗估及手填单价计算，未含系统提示、协议和其他调用开销；不是账单或费用上限。未填写单价时费用未知，真实失败也可能产生费用。'}
