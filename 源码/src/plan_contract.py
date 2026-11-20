"""Shared session-plan rules and bounded diagnostics; never includes model text."""
import json
from collections import Counter

VERSION = 'session-plan-v2'
MAX_ISSUES = 20


class PlanValidationError(ValueError):
    def __init__(self, issues):
        self.diagnostics = {
            'contract_version': VERSION,
            'summary': '学习计划未通过校验：' + issues[0]['message'],
            'issue_count': len(issues),
            'issues': issues[:MAX_ISSUES],
        }
        super().__init__(self.diagnostics['summary'])


def issue(code, path, message, **numbers):
    return {'code': code, 'path': path, 'message': message, **numbers}


def validation_error(exc):
    if isinstance(exc, PlanValidationError):
        return exc
    from pydantic import ValidationError
    if isinstance(exc, ValidationError):
        allowed = {'overall_goal', 'phases', 'phase_name', 'phase_goal', 'tasks',
                   'day', 'task_type', 'content', 'expected_outcome', 'source_gap_ids',
                   'plan_version','learning_preferences','daily_minutes','starting_level','time_budget',
                   'learning_minutes','core_minutes','review_minutes','optional_minutes','guide',
                   'starting_point','concepts','term','explanation','example','steps','worked_example',
                   'exercise','prompt','hints','reference_answer','checkpoints','fallback','tiers','tier',
                   'deferred_gaps','gap_id','reason','revisit_when'}
        issues = []
        for error in exc.errors(include_input=False, include_context=False, include_url=False):
            path = ''
            for part in error['loc'][:8]:
                if type(part) is int:
                    path += f'[{part}]' if 0 <= part <= 100000 else '[?]'
                else:
                    name = part if part in allowed else 'field'
                    path += ('.' if path else '') + name
            messages = {'missing': '缺少必填字段', 'literal_error': '任务类型只允许理论学习、实战编码或复习',
                        'int_parsing': '必须填写整数天数', 'int_type': '必须填写整数天数',
                        'int_from_float': '天数不能是小数', 'string_type': '必须填写文本',
                        'list_type': '必须填写数组', 'too_short': '条目数量不足',
                        'too_long': '条目数量超出范围', 'model_type': '必须是计划对象'}
            message = messages.get(error['type'], '字段结构或类型不符合计划要求')
            if error['type']=='literal_error' and error['loc'][-1:]!=('task_type',):
                message='字段取值不符合每日学习要求'
            if error['type'] in ('greater_than_equal','less_than_equal'):
                message='数值超出每日学习允许范围'

            code = 'plan_schema'
            if error['loc'] == ('phases',) and error['type'] in ('too_short', 'too_long'):
                code, message = 'phase_count', '阶段数量必须为4到6个，且不能超过学习天数'
            issues.append(issue(code, path or '$', message))
        return PlanValidationError(issues or [issue('plan_schema', '$', '计划结构不完整')])
    if isinstance(exc, (json.JSONDecodeError, ValueError, TypeError)):
        return PlanValidationError([issue('plan_json', '$', '返回内容不是可解析的完整计划JSON')])
    return PlanValidationError([issue('plan_unknown', '$', '未取得可校验的计划，具体原因未记录')])


def validate_plan(plan, days, *, gaps=None, require_sources=False, learning_preferences=None):
    """Same validation for actual PlannerAgent output and session persistence."""
    problems = []
    phases = plan.phases
    maximum = min(6, days) if require_sources else 6
    if not 4 <= len(phases) <= maximum:
        problems.append(issue('phase_count', 'phases', f'阶段数量须为4到{maximum}个'))
    all_days = [task.day for phase in phases for task in phase.tasks]
    duplicates = sorted(day for day,count in Counter(all_days).items() if count > 1)
    if duplicates:
        problems.append(issue('duplicate_day', 'phases[].tasks[].day',
                              '存在重复的 day，每天只能有一项任务', days=[day for day in duplicates if 1 <= day <= days]))
    missing = sorted(set(range(1, days + 1)) - set(all_days))
    extra = sorted(set(all_days) - set(range(1, days + 1)))
    if missing or extra:
        problems.append(issue('day_coverage', 'phases[].tasks[].day',
                              f'Day覆盖错误，须连续覆盖第1到第{days}天',
                              missing_days=missing, extra_count=len(extra)))
    if require_sources:
        known = {gap['gap_id'] for gap in gaps or []}
        covered = set()
        for pi, phase in enumerate(phases):
            path = f'phases[{pi}]'
            if not phase.tasks:
                problems.append(issue('empty_phase', path + '.tasks', '学习阶段不能为空'))
            for ti, task in enumerate(phase.tasks):
                field = path + f'.tasks[{ti}]'
                for name in ('content', 'expected_outcome'):
                    if not getattr(task, name).strip():
                        problems.append(issue('empty_task_text', field + '.' + name,
                                              '学习任务的内容和交付标准不能为空白'))
                sources = set(task.source_gap_ids)
                if not sources:
                    problems.append(issue('missing_gap_sources', field + '.source_gap_ids',
                                          '每项学习任务含复习均须关联至少一条已登记差距来源'))
                unknown = sources - known
                if unknown:
                    problems.append(issue('unknown_gap_sources', field + '.source_gap_ids',
                                          '学习任务引用了未登记的差距来源', unknown_count=len(unknown)))
                covered.update(sources & known)
        if known - covered and learning_preferences is None:
            problems.append(issue('gap_coverage', 'phases[].tasks[].source_gap_ids',
                                  '学习计划没有覆盖全部已登记差距', missing_count=len(known - covered)))
    if learning_preferences is not None:
        from daily_learning import validate_daily_plan
        try:validate_daily_plan(plan,learning_preferences,gaps)
        except PlanValidationError as exc:problems.extend(exc.diagnostics['issues'])
    if problems:
        raise PlanValidationError(problems)
    return True


def session_plan_rules(days, *, learning_preferences=None):
    maximum = min(6, days)
    coverage = '所有任务的来源并集必须覆盖全部已登记gap_id' if learning_preferences is None else '任务实际训练来源与明确暂缓列表的并集须覆盖全部登记gap_id，暂缓项不得计入训练覆盖'
    return f'''【会话计划合同 {VERSION}：提示、校验、保存共用】
1. 阶段4到{maximum}个，每个阶段tasks非空；{days}天计划每天恰好一项任务。
2. day为整数，完整覆盖1到{days}，不重复、不跳号、不超出范围。
3. content与expected_outcome必须是非空白文本，写明学习内容和可检查的交付。
4. 每项任务包括复习都必须有非空source_gap_ids，只选目录中的完整合法ID；禁止未知ID。
5. {coverage}；同一天可真实关联多条差距，不能编造来源或事后补齐。
6. 覆盖表示计划安排涉及，不表示已掌握；短期总体目标写清入门范围，不能承诺在{days}天内完全补齐或获得录用。'''
