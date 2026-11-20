"""Opt-in daily learning contract. Legacy plans are never enriched implicitly."""
from functools import lru_cache
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from plan_contract import PlanValidationError, issue

VERSION='daily-learning-v1'


class LearningPreferences(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    daily_minutes:int=Field(default=60,ge=15,le=240)
    starting_level:Literal['beginner','foundation']='beginner'


class TimeBudget(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    learning_minutes:int=Field(ge=1,le=240)
    core_minutes:int=Field(ge=1,le=240)
    review_minutes:int=Field(ge=1,le=240)
    optional_minutes:int=Field(ge=1,le=240)


class Concept(BaseModel):
    term:str=Field(min_length=1,max_length=100)
    explanation:str=Field(min_length=1,max_length=1000)
    example:str=Field(min_length=1,max_length=1000)


class Exercise(BaseModel):
    prompt:str=Field(min_length=1,max_length=1500)
    hints:list[str]=Field(min_length=1,max_length=5)
    reference_answer:str=Field(min_length=1,max_length=2000)
    checkpoints:list[str]=Field(min_length=1,max_length=6)


class BeginnerGuide(BaseModel):
    starting_point:str=Field(min_length=1,max_length=1000)
    concepts:list[Concept]=Field(min_length=1,max_length=3)
    steps:list[str]=Field(min_length=2,max_length=6)
    worked_example:str=Field(min_length=1,max_length=1500)
    exercise:Exercise
    fallback:str=Field(min_length=1,max_length=1000)


class TaskTier(BaseModel):
    tier:Literal['core','optional']
    content:str=Field(min_length=1,max_length=1500)
    expected_outcome:str=Field(min_length=1,max_length=1500)


class DeferredGap(BaseModel):
    gap_id:str=Field(min_length=1,max_length=200)
    reason:str=Field(min_length=1,max_length=1000)
    revisit_when:str=Field(min_length=1,max_length=1000)


@lru_cache(maxsize=1)
def daily_plan_model():
    # Import only at runtime, after Agent B's legacy models are defined.
    from agent_b_planner import DailyTask,StudyPhase,LearningPlan
    class GuidedTask(DailyTask):
        model_config=ConfigDict(extra="forbid",strict=True)
        time_budget:TimeBudget
        guide:BeginnerGuide
        tiers:list[TaskTier]=Field(min_length=2,max_length=2)
    class GuidedPhase(StudyPhase):
        model_config=ConfigDict(extra="forbid",strict=True)
        tasks:list[GuidedTask]
    class GuidedPlan(LearningPlan):
        model_config=ConfigDict(extra="forbid",strict=True)
        plan_version:Literal['daily-learning-v1']
        learning_preferences:LearningPreferences
        phases:list[GuidedPhase]=Field(min_length=4,max_length=6)
        deferred_gaps:list[DeferredGap]=Field(default_factory=list,max_length=80)
    return GuidedPlan


def plan_model(preferences=None):
    if preferences is not None:return daily_plan_model()
    from agent_b_planner import LearningPlan
    return LearningPlan


def validate_daily_plan(plan,preferences,gaps):
    expected=LearningPreferences.model_validate(preferences)
    problems=[]
    if plan.learning_preferences!=expected:
        problems.append(issue('learning_preferences','learning_preferences','计划每日时间或学习起点与保存的选择不一致'))
    known={g['gap_id'] for g in gaps or []}
    deferred=[g.gap_id for g in plan.deferred_gaps]
    if len(deferred)!=len(set(deferred)):
        problems.append(issue('deferred_duplicate','deferred_gaps','暂缓差距不能重复登记'))
    if set(deferred)-known:
        problems.append(issue('deferred_unknown','deferred_gaps','暂缓列表引用了未登记差距',unknown_count=len(set(deferred)-known)))
    covered=set()
    for pi,phase in enumerate(plan.phases):
        for ti,task in enumerate(phase.tasks):
            path=f'phases[{pi}].tasks[{ti}]'
            budget=task.time_budget
            total=sum(budget.model_dump().values())
            if total>expected.daily_minutes:
                problems.append(issue('daily_time_budget',path+'.time_budget','学习、必做、复盘及选做合计不能超过每日可用时间',extra_count=total-expected.daily_minutes))
            kinds=[t.tier for t in task.tiers]
            if sorted(kinds)!=['core','optional']:
                problems.append(issue('task_tiers',path+'.tiers','每天必须各有一项必做和选做任务'))
            # Schema length limits do not reject whitespace-only strings.
            def nonblank(value):
                if isinstance(value,str):return bool(value.strip())
                if isinstance(value,dict):return all(nonblank(v) for v in value.values())
                if isinstance(value,list):return all(nonblank(v) for v in value)
                return True
            if not nonblank(task.guide.model_dump()) or not nonblank([t.model_dump() for t in task.tiers]):
                problems.append(issue('learning_guide',path+'.guide','概念、示例、步骤、参考答案、自查及分层任务不能只有空白'))
            covered.update(task.source_gap_ids)
    overlap=covered&set(deferred)
    if overlap:
        problems.append(issue('deferred_overlap','deferred_gaps','已暂缓差距不能同时计入本轮任务训练来源',extra_count=len(overlap)))
    missing=known-covered-set(deferred)
    if missing:
        problems.append(issue('gap_disposition','deferred_gaps','每条差距须明确安排学习或说明暂缓原因',missing_count=len(missing)))
    if any(not g.reason.strip() or not g.revisit_when.strip() for g in plan.deferred_gaps):
        problems.append(issue('deferred_reason','deferred_gaps','暂缓差距须有原因和恢复学习条件'))
    if problems:raise PlanValidationError(problems)
    return True


def daily_plan_rules(preferences):
    p=LearningPreferences.model_validate(preferences)
    return f'''【每日学习合同 {VERSION}】
每日可用{p.daily_minutes}分钟，学习起点为{'零基础' if p.starting_level=='beginner' else '已有基础'}。输出plan_version=daily-learning-v1并原样声明learning_preferences。
每天给出time_budget的learning_minutes/core_minutes/review_minutes/optional_minutes，四项均为正整数且总和不超过{p.daily_minutes}分钟，选做不挤占必做。
guide包含起点/无需安装即可开始的准备、1到3个概念的解释和例子、至少2步学习顺序、完整worked_example，以及exercise的题面、提示、参考答案、自查点和困难时fallback。
tiers恰好core必做与optional选做各一项，有独立目标和交付。零基础先概念与纸面/小脚本验证，不能首日强制搭建整套生产环境。
不能在本轮合理安排的差距写入deferred_gaps，给gap_id、reason、revisit_when；它不等于完成或掌握，且不得与任一任务source_gap_ids重叠。学习来源与暂缓列表合起来覆盖全部登记差距，严禁假关联凑覆盖。
不输出内部字段名式任务指令，不编造资料链接；本轮用内置讲解和例子保证无需自行搜索也能开始。'''


def fixed_daily_plan(days,gaps,preferences):
    p=LearningPreferences.model_validate(preferences)
    # Explicit deterministic fixture, never a personalized assessment.
    deferred=[g for g in gaps if str(g.get('priority','')).startswith('P2')]
    active=[g for g in gaps if g not in deferred]
    if not active:raise ValueError('固定样例需要至少一条实际学习来源')
    lessons=[
        ('先理解事件时间','事件时间','事情实际发生的时刻，不是程序收到它的时刻。','订单10:00发生、10:02送达：事件时间10:00，处理时间10:02。','订单A在10:00发生、10:02收到，B在10:01发生、10:03收到；分别写出两种时间。','不要把收到时间当发生时间。','A事件时间10:00、处理时间10:02；B事件时间10:01、处理时间10:03。'),
        ('用小样本理解窗口','时间窗口','把指定时间范围内的数据分为一组计算。','[10:00,10:05)含10:04订单，不含10:05订单。','把10:01、10:04、10:05三个订单分到五分钟窗口。','留意窗口右边界不包含。','前两条归[10:00,10:05)，最后一条归[10:05,10:10)。'),
        ('理解重复与恢复','事件唯一标识与状态','记录见过的事件ID和累计结果，恢复时从保存点接续。','A金额5、重复A金额5、B金额3：按ID去重总额8。','纸面模拟A后保存状态，再收到重复A和B。','恢复后仍应记得已处理过A。','保存seen={A}及total=5，恢复后跳过A并加入B，得到8；这只是概念模拟。'),
        ('完成入门小验证','可重复验证','固定输入、预期输出和运行步骤，让别人能核对你的结果。','输入A:5,A:5,B:3；预期去重总额8。','用已有Python基础写去重求和，写明输入和预期输出。','先用集合记ID，再决定是否累加。','# Python 示例\nevents=[("A",5),("A",5),("B",3)]\nseen=set()\ntotal=0\nfor event_id, amount in events:\n    if event_id not in seen:\n        seen.add(event_id)\n        total += amount\nprint(total)  # 8'),
    ]
    phases=[{'phase_name':f'入门阶段{i+1}','phase_goal':'先理解再验证，不承诺生产胜任','tasks':[]} for i in range(4)]
    for day in range(1,days+1):
        title,term,explanation,example,question,hint,answer=lessons[(day-1)%4]
        budget=p.daily_minutes
        learn=max(3,budget//3);core=max(5,budget//3);review=max(2,budget//6);optional=budget-learn-core-review
        task={'day':day,'task_type':'理论学习' if day<4 else '实战编码','content':title,'expected_outcome':'交付一份能自查的概念解释或小样本结果','source_gap_ids':[g['gap_id'] for g in active],
              'time_budget':{'learning_minutes':learn,'core_minutes':core,'review_minutes':review,'optional_minutes':optional},
              'guide':{'starting_point':('准备纸笔；前3次学习无需安装Kafka或Flink，最后可使用已有Python环境。' if p.starting_level=='beginner' else '先尝试必做题，若概念有疑问再返回讲解；这些小样本不要求部署流处理环境。'),
                       'concepts':[{'term':term,'explanation':explanation,'example':example}],
                       'steps':[('先读概念，用自己的话解释。' if p.starting_level=='beginner' else '先写出预测结果，再对照概念检查理由。'),'跟着例子手算，再完成必做题。','对照参考与自查点，记录仍不理解的地方。'],
                       'worked_example':example+' 逐项核对时间或事件ID，再计算预期结果。',
                       'exercise':{'prompt':question,'hints':[hint],'reference_answer':answer,'checkpoints':['能说明判断依据','结果与参考一致，或能解释差异']},
                       'fallback':'若困难，只复现给定例子并写出卡点；可将任务暂缓，不标记为已掌握。'},
              'tiers':[{'tier':'core','content':question,'expected_outcome':'写出结果与一句判断依据'},
                       {'tier':'optional','content':'自行添加一个边界或重复事件，预测结果再核对。','expected_outcome':'额外一个反例与解释；未做不影响必做完成'}]}
        phases[min((day-1)*4//days,3)]['tasks'].append(task)
    return {'plan_version':VERSION,'learning_preferences':p.model_dump(),'overall_goal':'固定入门样例：在每日时间内理解事件、窗口和恢复概念，不代表真实学习成绩','phases':phases,
            'deferred_gaps':[{'gap_id':g['gap_id'],'reason':'当前时间优先用于入门验证，本轮不开展工程化训练。','revisit_when':'完成入门例子并有额外学习时间后，再单独安排。'} for g in deferred]}
