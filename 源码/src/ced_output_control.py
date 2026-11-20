"""Frozen D-only generation controls; no SDK, credentials or network."""
from copy import deepcopy

VERSION='d-generation-controls-v1'
OUTPUT_CAP=4096
MODES=('disabled','low')

def deepseek_flash(config):
    from urllib.parse import urlsplit
    url=urlsplit(config.get('base_url',''))
    gateway=(config.get('provider')=='评委网关v2 · DeepSeek' and url.scheme=='https' and bool(url.hostname) and url.path=='/v1' and not(url.username or url.password or url.query or url.fragment))
    return ((gateway or (config.get('provider','').casefold()=='deepseek'
        and config.get('base_url') in ('https://api.deepseek.com','https://api.deepseek.com/v1')
        )) and config.get('model')=='deepseek-flash')

def d_controls(config,*,thinking_mode='disabled',output_limit=OUTPUT_CAP):
    if thinking_mode not in MODES:raise ValueError('D思考模式只支持关闭或低强度')
    if type(output_limit) is not int or not 256<=output_limit<=OUTPUT_CAP:raise ValueError('D输出上限须为256～4096')
    supported=deepseek_flash(config)
    if thinking_mode=='low' and not supported:raise ValueError('低强度思考仅支持已核对的DeepSeek Flash官方接口')
    return {'policy_version':VERSION,'thinking_mode':thinking_mode if supported else 'provider_default',
      'reasoning_effort':'low' if supported and thinking_mode=='low' else None,
      'max_output_tokens':min(config['max_output_tokens'],output_limit),
      'json_output':supported,'max_items':2,'max_missing_evidence':3,
      'max_reference_characters':240,'max_proposed_characters':300,'max_rationale_characters':100,'max_missing_characters':80,
      'automatic_retries':0,'on_truncation':'stop_without_retry',
      'notice':'思考模式与输出共用服务商输出预算；上限不是预分配或费用承诺。只输出局部修改，整稿由本地原文与已核对修改合成。'}

def apply_controls(body,config,controls):
    body=deepcopy(body)
    body[config.get('output_token_parameter','max_tokens')]=controls['max_output_tokens']
    if controls['thinking_mode']!='provider_default':
        body['thinking']={'type':'disabled' if controls['thinking_mode']=='disabled' else 'enabled'}
        if controls['reasoning_effort']:
            body['reasoning_effort']=controls['reasoning_effort']
            body.pop('temperature',None)
        if controls['json_output']:body['response_format']={'type':'json_object'}
    return body

def sdk_kwargs(payload,config):
    """Keep previews as the actual wire JSON. SDK-only extra_body is not a payload field."""
    if 'extra_body' in payload:raise ValueError('SDK extra_body不能作为已预览请求正文')
    result=deepcopy(payload)
    if 'thinking' in result:
        if not deepseek_flash(config):raise ValueError('未核对的服务商不能接收DeepSeek思考参数')
        thinking=result.pop('thinking')
        if thinking not in ({'type':'enabled'},{'type':'disabled'}):raise ValueError('思考参数无效')
        effort=result.get('reasoning_effort')
        if thinking['type']=='disabled' and effort is not None:raise ValueError('关闭思考时不能同时设置思考强度')
        if thinking['type']=='enabled' and effort!='low':raise ValueError('本轮仅允许低强度思考')
        result['extra_body']={'thinking':thinking}
    return result
