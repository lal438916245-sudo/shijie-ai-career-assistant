"""Career agent endpoints using existing loopback and session authorization."""
from career_agent import CareerAgent
from model_preparation import PreparationError
from competition_workbench import WorkbenchError


def handle_agent(handler, workbench, kind, parsed, write):
    if kind not in {'agent-state', 'agent-run', 'agent-cancel', 'agent-configure'}:
        return False
    if parsed.query or (write == (kind == 'agent-state')):
        raise WorkbenchError('智能体请求方法无效。')
    with handler.server.guard:
        agent = getattr(workbench, 'career_agent', None)
        if agent is None:
            agent = CareerAgent(workbench, enabled=getattr(handler.server, 'session_outbound_enabled', False))
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
            value = agent.configure(token, handler.body())
        else:
            value = agent.cancel(token, handler.body())
    except PreparationError as exc:
        raise WorkbenchError(str(exc)) from None
    handler.reply(200, {'data': value})
    return True
