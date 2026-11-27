"""The platform/user selection is shared by all model consumers and old receipts."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sys
import uuid

import httpx
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from test_career_agent import TestVault
from unified_model import UnifiedModelPreparation
from model_preparation import DEFAULT, ModelPreparation, PreparationError
from career_agent_model import AgentModel
from career_agent_tools import definitions
from competition_workbench import CompetitionWorkbench
from sdk_transport import SDKTransport
from workbench_abf import FixedABFTransport
from judge_client import sponsored_policy
from judge_gateway import JudgeGateway, GatewayError, encode


def config(url='https://platform.invalid/v1', model='platform-model', input_rate=2, output_rate=8):
    return {**DEFAULT,'provider':'Test provider','base_url':url,'model':model,
            'input_price_per_million':input_rate,'output_price_per_million':output_rate,
            'max_input_chars':60000,'max_output_tokens':4096}


def sponsor():
    return {'version':'judge-gateway-v2','sponsored':True,'supported_stages':['a_diagnosis','d_revision','e_turn','e_report'],
            'expires_at':'2026-12-10T23:59:00+08:00','budget_micro_cny':7000000,
            'session_budget_micro_cny':1000000,'tool_calls_supported':True,'notice':'test'}


def user_body(prep, **extra):
    return {'base_url':'https://user.invalid/v1','model':'user-model','api_key':'own-user-api-key',
            'input_price':4,'output_price':12,'revision':prep._read()['revision'],**extra}


def test_platform_is_default_and_override_is_shared_by_sdk_and_agent(tmp_path):
    prep=UnifiedModelPreparation(tmp_path,TestVault())
    prep.install_platform(config(),'platform-access-pass',sponsor())
    assert prep.status()['model_source']=='platform'
    observed=[]

    def provider(request):
        observed.append((str(request.url),request.headers.get('authorization'),request.headers.get('x-shijie-stage')))
        return httpx.Response(200,json={'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'{"ok":true}'}}],
                                      'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}})

    factory=lambda:httpx.Client(transport=httpx.MockTransport(provider))
    model=AgentModel(tmp_path,preparation=prep,client_factory=factory)

    def call_all():
        settings=prep._read()
        for stage in ('a_diagnosis','d_revision','e_turn','e_report'):
            request={'stage':stage,'payload':{'model':settings['config']['model'],
                'messages':[{'role':'user','content':'synthetic test input'}],'max_tokens':256},
                'config':settings['config'],'config_revision':settings['revision'],
                'key_slot_digest':hashlib.sha256(settings['encrypted_key'].encode()).hexdigest(),
                'sdk_policy':{'rehearsal':False},'timeout_seconds':5}
            SDKTransport(prep,rehearsal=False,outbound_enabled=True,http_client_factory=factory).send(request,None,None)
        model.complete(model.payload([{'role':'user','content':'test'}],definitions(),settings),settings,request_id='a'*64)

    call_all()
    assert all(url.startswith('https://platform.invalid/') and key=='Bearer platform-access-pass' for url,key,_ in observed)
    assert observed[-1][2]=='career_agent'
    assert [row[2] for row in observed[:4]]==['a_diagnosis','d_revision','e_turn','e_report']
    model.configure(user_body(prep))
    assert prep.status()['model_source']=='user' and sponsored_policy(prep) is None
    observed.clear()
    call_all()
    assert all(url.startswith('https://user.invalid/') and key=='Bearer own-user-api-key' for url,key,_ in observed)
    assert all(stage is None for _,_,stage in observed)
    reloaded=UnifiedModelPreparation(tmp_path,TestVault())
    assert reloaded._read()==prep._read()
    reloaded.select_platform(reloaded._read()['revision'])
    assert reloaded.status()['model_source']=='platform'
    assert reloaded.vault.open(reloaded._read()['encrypted_key'])=='platform-access-pass'


def test_migration_keeps_old_platform_and_existing_agent_override(tmp_path):
    base=ModelPreparation(tmp_path,TestVault())
    base.save({'config':config(),'api_key':'old-platform-access','key_action':'replace','expected_revision':0})
    policy=sponsor()
    policy['config_digest']=hashlib.sha256(encode(config()).encode()).hexdigest()
    base.path.with_name('judge-policy.json').write_text(json.dumps(policy),encoding='utf-8')
    old_agent=ModelPreparation(tmp_path/'agent-model',TestVault())
    old_agent.save({'config':config('https://old-user.invalid/v1','old-user-model'),'api_key':'old-agent-user-key',
                    'key_action':'replace','expected_revision':0})
    prep=UnifiedModelPreparation(tmp_path,TestVault())
    assert prep.status()['model_source']=='user'
    assert prep._read()['config']['model']=='old-user-model'
    prep.select_platform(prep._read()['revision'])
    assert prep.vault.open(prep._read()['encrypted_key'])=='old-platform-access'
    assert base.path.exists() and old_agent.path.exists()
    with pytest.raises(PreparationError):
        AgentModel(tmp_path,preparation=prep).configure(user_body(prep,api_key='',base_url='https://new.invalid/v1'))


def test_reimporting_platform_preserves_selected_user_model(tmp_path):
    prep=UnifiedModelPreparation(tmp_path,TestVault())
    prep.install_platform(config(),'platform-access-pass',sponsor())
    AgentModel(tmp_path,preparation=prep).configure(user_body(prep))
    before=prep._read()
    prep.install_platform(config(model='new-platform-model'),'new-platform-access-pass',sponsor())
    assert prep._read()==before
    prep.select_platform(before['revision'])
    assert prep._read()['config']['model']=='new-platform-model'


def test_old_paid_receipts_and_new_price_requests_survive_model_switch(tmp_path):
    prep=UnifiedModelPreparation(tmp_path,TestVault())
    prep.install_platform(config(),'platform-access-pass',sponsor())
    replies=[]
    def provider(request):
        return httpx.Response(200,json=replies.pop(0))
    workbench=CompetitionWorkbench(tmp_path,case_profile='final-20261107',session_preparation=prep,
        session_outbound_enabled=True,session_http_client_factory=lambda:httpx.Client(transport=httpx.MockTransport(provider)))
    token='e'*64
    workbench.create_personal(token,{'request_id':str(uuid.uuid4()),'start_date':'2026-11-26',
        'target_role':'测试开发实习生','resume_text':'我用Python开发过接口自动化测试，了解SQL基础查询，尚未完成多表连接练习。',
        'jd_text':'要求Python接口自动化测试、SQL查询和日志排查，能够说明个人项目贡献及验证方法。'})
    workbench.mutate(token,'session_runtime_open',{'request_id':str(uuid.uuid4()),'expected_revision':workbench.state(token)['revision'],
        'execution_mode':'real_model','budget_micro_cny':1000000})
    preview=workbench.abf_preview(token,{'request_id':str(uuid.uuid4()),'expected_revision':workbench.state(token)['revision'],
                                      'stage':'a_diagnosis','target_version':0})
    grant=workbench.abf_authorize(token,{'preview_id':preview['preview_id'],'request_digest':preview['request_digest'],'accept_session_once':True})
    with closing(workbench._connect(token)) as conn:
        _,request=workbench._abf_row(conn,grant['authorization_id'])
    content=FixedABFTransport().send(request)['content']
    replies.append({'choices':[{'index':0,'message':{'role':'assistant','content':content},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':100,'completion_tokens':100,'total_tokens':200}})
    completed=workbench.abf_execute(token,{'authorization_id':grant['authorization_id']})
    assert completed['status']=='completed',completed.get('errors')
    before=workbench.state(token)['session_runtime']['spent_micro_cny']
    AgentModel(tmp_path,preparation=prep).configure(user_body(prep))
    restored=workbench.abf_status(token,{'authorization_id':grant['authorization_id']})
    assert restored['status']=='completed'
    assert workbench.state(token)['session_runtime']['spent_micro_cny']==before
    preview=workbench.abf_preview(token,{'request_id':str(uuid.uuid4()),'expected_revision':workbench.state(token)['revision'],
                                      'stage':'a_diagnosis','target_version':0})
    with closing(workbench._connect(token)) as conn:
        fresh=json.loads(conn.execute('SELECT request_json FROM wbf_previews WHERE preview_id=?',(preview['preview_id'],)).fetchone()[0])
    assert fresh['config']['model']=='user-model'
    assert fresh['session_runtime']['input_rate']==4 and fresh['session_runtime']['output_rate']==12


def test_gateway_tool_upgrade_preserves_existing_global_ledger(tmp_path):
    old=json.loads((Path(__file__).resolve().parents[1]/'deploy/judge-gateway/render/previous-policy.json').read_text(encoding='utf-8'))
    upgraded={**old,'max_input_chars':60000,'tool_calls_supported':True}
    sent=[]
    def provider(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':'ok'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5}})
    factory=lambda:httpx.Client(transport=httpx.MockTransport(provider))
    path=tmp_path/'ledger.db'
    gateway=JudgeGateway(path,old,'limited-platform-access-pass','owner-provider-key',client_factory=factory,clock=lambda:0)
    original={'model':old['model'],'messages':[{'role':'user','content':'test'}],'max_tokens':256}
    gateway.complete('Bearer limited-platform-access-pass',encode(original).encode(),'a_diagnosis','1'*64)
    before=gateway.status('Bearer limited-platform-access-pass')
    gateway=JudgeGateway(path,upgraded,'limited-platform-access-pass','owner-provider-key',client_factory=factory,clock=lambda:0,previous_settings=old)
    assert gateway.status('Bearer limited-platform-access-pass')==before
    body={**original,'tools':definitions(include_business=True),'tool_choice':'auto'}
    gateway.complete('Bearer limited-platform-access-pass',encode(body).encode(),'career_agent','2'*64)
    assert gateway.configuration('Bearer limited-platform-access-pass')['tool_calls_supported']
    assert gateway.configuration('Bearer limited-platform-access-pass')['agent_business_tools_supported']
    assert gateway.status('Bearer limited-platform-access-pass')['calls']==2
    gateway.complete('Bearer limited-platform-access-pass',encode(body).encode(),'career_agent','2'*64)
    assert len(sent)==2
    broken={**body,'messages':[{'role':'tool','content':'orphan','tool_call_id':'missing'}]}
    with pytest.raises(GatewayError):
        gateway.validate(encode(broken).encode(),'career_agent','3'*64)


def test_unsent_old_configuration_is_released_and_cannot_dispatch(tmp_path):
    prep=UnifiedModelPreparation(tmp_path,TestVault())
    prep.install_platform(config(),'platform-access-pass',sponsor())
    workbench=CompetitionWorkbench(tmp_path,case_profile='final-20261107',session_preparation=prep,session_outbound_enabled=True)
    token='f'*64
    workbench.create_personal(token,{'request_id':str(uuid.uuid4()),'start_date':'2026-11-26',
        'target_role':'测试开发实习生','resume_text':'我用Python编写过接口自动化测试，了解SQL基础查询，正在补充多表连接实践。',
        'jd_text':'要求Python接口测试、SQL基础查询与日志排查，能够描述个人贡献和问题定位方法。'})
    workbench.mutate(token,'session_runtime_open',{'request_id':str(uuid.uuid4()),'expected_revision':workbench.state(token)['revision'],
        'execution_mode':'real_model','budget_micro_cny':1000000})
    def authorize():
        preview=workbench.abf_preview(token,{'request_id':str(uuid.uuid4()),'expected_revision':workbench.state(token)['revision'],
            'stage':'a_diagnosis','target_version':0})
        return workbench.abf_authorize(token,{'preview_id':preview['preview_id'],'request_digest':preview['request_digest'],'accept_session_once':True})
    old=authorize()
    AgentModel(tmp_path,preparation=prep).configure(user_body(prep))
    entries=workbench.state(token)['session_runtime']['entries']
    assert entries[0]['status']=='released_unconsumed'
    new=authorize()
    assert new['config_revision']==prep._read()['revision']
    assert workbench.abf_status(token,{'authorization_id':old['authorization_id']})['status']=='invalidated'
    refused=workbench.abf_execute(token,{'authorization_id':old['authorization_id']})
    assert refused['status']=='invalidated' and refused['consumed'] is False
