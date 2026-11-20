"""比赛模型配置与单请求阅卷器；导入本模块不会创建模型客户端。"""

from functools import partial
from importlib.util import find_spec
import os
from pathlib import Path

from dotenv import dotenv_values

from paths import ROOT


def sdk_available():
    return find_spec("openai") is not None


def settings():
    values = {**dotenv_values(Path(ROOT) / ".env"), **os.environ}
    return values.get("AI_MODEL") or "deepseek-v4-flash", bool(values.get("AI_API_KEY"))


def assessor_for(db, context):
    from agent_c_assessor import AssessorAgent
    model_name, _ = settings()
    assessor = AssessorAgent(db, trace_id=context["trace_id"],
                             model_name=model_name, enable_rag=False)
    return single_request(assessor)


def single_request(agent):
    agent.client = agent.client.with_options(max_retries=0)
    agent.think = partial(agent.think, max_retries=1, max_truncations=0)
    return agent


def hunter_for(db, context):
    from agent_a_hunter import HunterAgent
    model_name, _ = settings()
    return single_request(HunterAgent(db, trace_id=context["trace_id"], model_name=model_name))


def planner_for(db, context):
    from agent_b_planner import PlannerAgent
    model_name, _ = settings()
    # 由会话服务统一保存计划与回执，避免旧入口内部的独立 commit。
    return single_request(PlannerAgent(None, trace_id=context["trace_id"], model_name=model_name))


def critic_for(db, context):
    from agent_f_critic import CriticAgent
    model_name, _ = settings()
    return single_request(CriticAgent(db, trace_id=context["trace_id"], model_name=model_name))
