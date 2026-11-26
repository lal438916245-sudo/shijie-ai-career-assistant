"""Same local proxy authorization as legacy; never available via SDK profiles."""
import sqlite3
import uuid
from urllib.parse import parse_qs
from competition_workbench import CompetitionWorkbench,WorkbenchError
from competition_case import CaseContractError
from workbench_published_resume import published_read,published_resume
from competition_workbench_calls import CALL_ACTIONS,CEDSDKTransport
from competition_sessions import SessionError,SessionBusy
from workbench_abf import ABF_ACTIONS

PREFIX='/api/live/workbench/'


def handle(handler,parsed,*,write=False):
    if not parsed.path.startswith(PREFIX):return False
    if handler.server.source_kind!='local_workflow_double':
        handler.reject_request(404,{'error':'该入口仅支持隔离的比赛固定会话。','code':'unsupported_mode'})
        return True
    active_mark=None
    try:
        with handler.server.guard:
            service=getattr(handler.server,'competition_workbench',None)
            if service is None:
                preparation=handler.server.preparation
                def configuration():
                    with preparation.lock:return preparation._read()
                transport=CEDSDKTransport(preparation) if handler.server.ced_sdk_rehearsal else None
                from workbench_contract_sdk import ABFSDKRehearsal,CESDKRehearsal
                contract_sdk=getattr(handler.server,'contract_sdk_rehearsal',False)
                service=CompetitionWorkbench(handler.server.directory.parent,abf_transport=ABFSDKRehearsal(preparation) if contract_sdk else None,
                                             ce_transport=CESDKRehearsal(preparation) if contract_sdk else None,call_configuration=configuration,
                                             call_transport=transport,call_boot_id=handler.server.boot_id,case_profile=handler.server.workbench_case_profile,session_preparation=preparation,session_outbound_enabled=getattr(handler.server,'session_outbound_enabled',False))
                handler.server.competition_workbench=service
            if write:
                active_mark=('competition-workbench',str(uuid.uuid4()))
                handler.server.active.add(active_mark)
        kind=parsed.path[len(PREFIX):]
        from career_agent_http import handle_agent
        if handle_agent(handler,service,kind,parsed,write):return True
        if write:
            if parsed.query or (kind not in CALL_ACTIONS|ABF_ACTIONS and kind not in ('create','create_personal','diagnosis','plan','review','adopt','publish','progress','learning_artifact','recover','assessment_start','retest_start','answer','assessment_next','assessment_end','interview_start','interview_answer','interview_end','resume_generate','resume_check','candidate_apply','abf_apply','ce_budget_open','session_runtime_open','saved_b_preview','saved_b_apply','plan_check','plan_confirm_publish','plan_prepare')):
                handler.reject_request(404,{'error':'工作台接口不存在。','code':'not_found'});return True
            body=handler.body();token=handler.token()
            value=getattr(service,kind)(token,body) if kind in CALL_ACTIONS|ABF_ACTIONS or kind in ('saved_b_preview','plan_check') else service.create(token,body) if kind=='create' else service.create_personal(token,body) if kind=='create_personal' else service.mutate(token,kind,body)
        else:
            query=parse_qs(parsed.query,strict_parsing=True)
            if any(len(v)!=1 for v in query.values()):raise WorkbenchError('读取参数重复。')
            if kind=='template' and not query:value=service.template()
            else:
                token=handler.token()
                from replay_read_cache import ReplayReadCache
                with handler.server.guard:
                    cache=getattr(service,'replay_read_cache',None)
                    if cache is None:cache=service.replay_read_cache=ReplayReadCache()
                value=cache.read(service,token,kind,query,lambda:read_workbench(service,token,kind,query))
        handler.reply(200,{'data':value})
    except WorkbenchError as exc:
        handler.reply(exc.status,{'error':str(exc),'code':exc.code})
    except SessionBusy:
        handler.reply(409,{'error':'示例步骤正在执行或曾中断，请先重新读取状态。','code':'busy'})
    except (SessionError,CaseContractError):
        handler.reply(409,{'error':'结果或来源未通过校验，当前计划未改写；请重新读取会话状态。','code':'validation'})
    except (OSError,sqlite3.Error):
        handler.reply(503,{'error':'本机工作台暂不可用，请保留会话列表并重新读取。','code':'unavailable'})
    except (ValueError,TypeError,KeyError):
        handler.reply(400,{'error':'请求内容或固定结果未通过校验。','code':'invalid'})
    finally:
        if active_mark is not None:
            with handler.server.guard:handler.server.active.discard(active_mark)
    return True


def read_workbench(service,token,kind,query):
    def publication(s,t):
        from workbench_published_resume import load_publication
        cache=getattr(s,'replay_read_cache',None)
        return cache.read(s,t,'publication',{},lambda:load_publication(s,t)) if cache else load_publication(s,t)
    if kind=='state' and not query:value=service.state(token)
    elif kind=='session-budget' and not query:value=service.session_budget(token)
    elif kind=='ce-budget' and not query:value=service.ce_budget(token)
    elif kind=='records' and not query:value=service.records(token)
    elif kind=='plan' and set(query)=={'version'}:
        raw=query['version'][0]
        if not raw.isdigit() or len(raw)>4:raise WorkbenchError('计划版本无效。')
        value=service.plan(token,int(raw))
    elif kind=='learning' and set(query)=={'task_id'}:value=service.learning(token,query['task_id'][0])
    elif kind=='assessment-options' and set(query)=={'kind','period_start','period_end'}:value=service.assessment_options(token,query['kind'][0],query['period_start'][0],query['period_end'][0])
    elif kind=='assessment' and set(query)=={'run_id'}:value=service.assessment(token,query['run_id'][0])
    elif kind=='interview' and set(query)=={'interview_id'}:value=service.interview(token,query['interview_id'][0])
    elif kind=='resume' and set(query)=={'resume_id'}:value=published_resume(service,token,query['resume_id'][0],loader=publication) or service.resume(token,query['resume_id'][0])
    elif kind=='request' and set(query)=={'request_id'}:value=service.request_status(token,query['request_id'][0])
    else:
        from competition_workbench import WorkbenchMissing
        raise WorkbenchMissing('工作台接口不存在。')
    return published_read(service,token,kind,value,loader=publication) if kind in ('state','records') else value
