"""Career agent endpoints using existing loopback and session authorization."""
from career_agent import CareerAgent
from career_agent_model import AgentModel
from model_preparation import PreparationError
from competition_workbench import WorkbenchError


def handle_agent(handler, workbench, kind, parsed, write):
    if kind not in {'agent-state', 'agent-run', 'agent-cancel', 'agent-configure', 'model-platform'}:
        return False
    if parsed.query or (write == (kind == 'agent-state')):
        raise WorkbenchError('智能体请求方法无效。')
    with handler.server.guard:
        agent = getattr(workbench, 'career_agent', None)
        if agent is None:
            agent = CareerAgent(workbench, model=AgentModel(workbench.directory.parent,preparation=handler.server.preparation),
                                enabled=getattr(handler.server, 'session_outbound_enabled', False))
            workbench.career_agent = agent

    def active(started, run_id):
        with handler.server.guard:
            marker = ('career-agent', run_id)
            if started:
                handler.server.active.add(marker)
            else:
                handler.server.active.discard(marker)

    token = handler.token()
    try:
        if kind == 'agent-state':
            value = agent.snapshot(token)
        elif kind == 'agent-run':
            value = agent.start(token, handler.body(), active)
        elif kind == 'agent-configure':
            with handler.server.guard:
                if sum(marker[0]=='competition-workbench' for marker in handler.server.active)>1:
                    raise WorkbenchError('当前模型请求尚未结束，请完成后再切换连接。')
            value = agent.configure(token, handler.body())
        elif kind == 'model-platform':
            body=handler.body()
            if not isinstance(body,dict) or set(body)!={'revision'}:raise WorkbenchError('模型切换字段无效。')
            with handler.server.guard,agent.guard:
                if agent.running or sum(marker[0]=='competition-workbench' for marker in handler.server.active)>1:
                    raise WorkbenchError('当前模型请求尚未结束，请完成后再切换连接。')
                agent.model.preparation.select_platform(body['revision'])
            value=agent.snapshot(token)
        else:
            value = agent.cancel(token, handler.body())
    except PreparationError as exc:
        raise WorkbenchError(str(exc)) from None
    handler.reply(200, {'data': value})
    return True
