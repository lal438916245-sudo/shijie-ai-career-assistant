import json
import re
from pydantic import BaseModel, Field, ValidationError,field_validator
from typing import List,Literal
from llm_client import AgentBase
from json_utils import parse_llm_json
from contracts import EVIDENCE_PROMPT_RULES_GROUNDING
import gap_registry
from plan_contract import PlanValidationError, validate_plan, validation_error, session_plan_rules
import uuid

# ==========================================
#  第一步：制定铁律 (Schema 定义)
# ==========================================
# 使用 Pydantic 定义 JSON 的结构。大模型如果敢偏离这个结构哪怕一点点，都会触发报警！

class DailyTask(BaseModel):
    day: int = Field(..., description="全局第几天，必须是整数")
    task_type: Literal["理论学习", "实战编码", "复习"] 

    content: str = Field(..., description="具体的学习内容或要刷的题")
    expected_outcome: str = Field(..., description="当天的考核交付标准")

    # v6：这条任务针对哪些 Agent A 差距。由模型从 prompt 给出的清单里挑选。
    #
    # 为什么是**可选且默认空**：
    #   · 旧版模型输出 / 旧测试 / 旧调用方根本不带这个字段 —— 默认空数组让它们
    #     继续可用，不会因为 schema 变严而全部校验失败；
    #   · 空数组的语义是"模型没有声明来源"，落库时会被标成 unlinked，
    #     而不是被当成"和任何 gap 无关"或被自动补一个来源。
    source_gap_ids: List[str] = Field(
        default_factory=list,
        description="该任务针对的 gap_id 列表，只能取自给定的差距清单；无对应则留空")


class StudyPhase(BaseModel):
    phase_name: str = Field(..., description="阶段名称，如'第一阶段：底层原理扫盲'")
    phase_goal: str = Field(..., description="本阶段要达成的核心目标")
    tasks: List[DailyTask] = Field(..., description="该阶段包含的每日任务列表")

class LearningPlan(BaseModel):
    overall_goal: str = Field(..., description="这份计划的总体目标总结")
    phases: List[StudyPhase] = Field(...,min_length=4,max_length=6, description="学习阶段列表,必须为4到6个阶段")

# ==========================================
#  第二步：Agent B 规划师
# ==========================================
# 三种产生计划的方式：
#   1. generate_plan()            —— 直接生成并落库（原有行为，保持不变）
#   2. plan_with_reflection()     —— 生成 -> Agent F 审计 -> 修正 -> 落库（新增）
#   3. plan_from_trace()          —— 从库读 gap 后再走上面任一条
#
# 为什么要拆出 _generate_validated()：
#   反思循环里的"修正"也必须走同一套结构校验与业务校验 ——
#   不能因为"这是修正版"就跳过验证。

class PlannerAgent(AgentBase):
    def __init__(self,db=None,trace_id=None,model_name=None):
        # 强制把 Pydantic 定义的 JSON 格式说明，塞进系统提示词里！
        schema_dict = LearningPlan.model_json_schema()
        self.schema_json = json.dumps(schema_dict, ensure_ascii=False)
        
        # 初始 Prompt 留空，我们在不同的方法里动态生成
        super().__init__(agent_name="规划师 Agent_B", system_prompt="你是一位顶级的大厂技术培训官。", trace_id=trace_id, db=db, model_name=model_name)
        self.db = db
        self.current_plan_id = None 
        # 反思循环的历史（供导出/审计用）
        self.reflection_history = []
        
    def extract_json_from_text(self, text):
        """ 暴力抠出大模型回复中的 JSON 块 """
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            return text[start_idx:end_idx+1]
        raise ValueError("未找到 JSON 结构")


     # [新增功能 1]: 智能估算学习时长
    def recommend_duration(self, gap_report):
        print("\n [Agent B] 正在评估您的 Gap 严重程度，为您测算合理的突击时长...")
        prompt = f"""
        请阅读以下猎头出具的【差距报告】：
        {gap_report}
        
        作为培训官，请评估要弥补这些 Gap，对于一个普通程序员需要多少天（全职脱产学习状态）。
        请直接输出一个整数（天数），不要输出任何其他废话。例如：14
        """
        response = self.think(prompt,max_tokens=2000).strip()
        try:
            # 尝试提取数字
            days = int(''.join(filter(str.isdigit, response)))
            return days if days > 0 else 7
        except:
            return 7 # 兜底 7 天

    def validate_plan_days(self, plan, final_days):
        """验证学习计划业务规则（共享规则，兼容旧独立调用）。"""
        return validate_plan(plan, final_days)

    def _plan_prompt(self, gap_report, final_days, gaps=None):
        return build_plan_prompt(gap_report, final_days, gaps, require_sources=getattr(self, 'require_session_plan', False), learning_preferences=getattr(self,'learning_preferences',None))

    def _explain_error(self, e):
        """
        把技术化报错翻译成模型能直接照做的指令。

        为什么要翻译：Pydantic 的原始报错长这样 ——
            "2 validation errors for LearningPlan / overall_goal Field required
             [type=missing, input_value={'计划名称': '腾讯A...'}] /
             For further information visit https://errors.pydantic.dev/2.13/v/missing"
        模型看了抓不住重点（实测连续两轮都没改对"中文键名"这个问题）。
        翻译后它才知道该改什么。
        """
        if isinstance(e, ValidationError):
            # 错误类型映射：让模型知道到底是「缺字段」还是「值不合法」。
            # 早期版本只说"缺失或键名错误"，遇到 task_type 枚举越界时
            # 模型会误以为是键名问题，白改一轮。
            TYPE_HINT = {
                "missing": "缺少该字段",
                "literal_error": "值不在允许范围内",
                "int_parsing": "不是合法整数",
                "int_type": "应为整数",
                "string_type": "应为字符串",
                "list_type": "应为数组",
                "too_short": "内容过短",
            }
            paths = []
            for err in e.errors():
                loc = err.get("loc") or ("?",)
                etype = err.get("type") or ""
                ctx = err.get("ctx") or {}

                # 拼出完整路径（如 phases[0].tasks[0]）并去重。
                # 早期版本只取 loc[0]，导致多个子项错误被压成
                # "phases、phases、phases"，模型看不出该改哪里。
                parts = []
                for x in loc[:4]:
                    if isinstance(x, int):
                        if parts:
                            parts[-1] = "%s[%d]" % (parts[-1], x)
                    else:
                        parts.append(str(x))
                path = ".".join(parts)

                hint = TYPE_HINT.get(etype)
                if etype == "literal_error" and ctx.get("expected"):
                    hint = "值不在允许范围内，允许：%s" % ctx["expected"]
                item = "%s（%s）" % (path, hint) if hint else path
                if item not in paths:
                    paths.append(item)

            return ("JSON 结构不符合要求 —— 有问题的字段路径：%s。"
                    "请检查键名是否写成了中文（必须用英文原件："
                    "overall_goal / phases / phase_name / phase_goal / tasks / "
                    "day / task_type / content / expected_outcome），"
                    "以及字段是否缺失、值是否在允许范围内。"
                    % "、".join(paths[:6]))
        return str(e)

    # =========================================================
    # 生成核心：调模型 -> 抠 JSON -> Pydantic 校验 -> 业务校验
    # =========================================================
    def _set_system_prompt(self, final_days):
        self.system_prompt = build_plan_system_prompt(final_days, self.schema_json, require_sources=getattr(self, 'require_session_plan', False))

    def _generate_validated(self, user_prompt, source_material, final_days,
                            max_retries=3, task_label="生成的学习计划"):
        """
        调模型 -> 抠 JSON -> Pydantic 校验 -> 业务规则校验，失败则带错误重试。

        参数
        ----
        user_prompt     : 首次请求内容
        source_material : 原始素材（gap 报告 / 旧计划+审计意见），重试时随错误一并回传
        task_label      : 用于错误提示（"生成"或"修正"）

        返回 LearningPlan，或 None（重试用尽）。

        抽成独立方法的原因：反思循环里的"修正"也必须走同一套校验。
        """
        retries = 0
        self.last_plan_validation = None
        while retries < max_retries:
            # ======================================================
            # 第一阶段：调用 LLM
            # ======================================================
            raw_response = self.think(user_prompt, max_tokens=6000)
            
            try:
                # ==================================================
                # 第二阶段：解析模型输出
                # ==================================================
                # 用带抢救能力的解析器（json_utils），而不是裸 json.loads：
                # 学习计划 JSON 很长、又容易撞截断，裸解析一失败就丢弃整次输出。
                # 实测：首轮生成 3 次里有 2 次因 JSON 问题作废，白烧约 9,000 token。
                json_data, degraded = parse_llm_json(raw_response)
                if degraded:
                    # 抢救出的内容是不完整的（尾部任务缺失），业务校验必然失败。
                    # 直接抛错比让它失败在 day 覆盖检查上更能提示模型问题所在。
                    raise ValueError(
                        "输出被截断，JSON 不完整（已抢救出部分内容，但不足以构成完整计划）")
                # ==================================================
                # 第三阶段：Pydantic 结构校验
                # ==================================================
                from daily_learning import plan_model
                validated_plan = plan_model(getattr(self,'learning_preferences',None)).model_validate(json_data)

                # ==================================================
                # 第四阶段：业务规则校验
                # ==================================================
                self.validate_plan_days(validated_plan, final_days)
                if getattr(self, 'require_session_plan', False):
                    validate_plan(validated_plan, final_days, gaps=self.session_plan_gaps, require_sources=True, learning_preferences=getattr(self,'learning_preferences',None))

                # ==================================================
                # 第五阶段：校验成功
                # ==================================================
                print(
                    f"[Agent B] {task_label}成功，"
                    "所有结构与业务规则校验通过！"
                )
                return validated_plan

            except(json.JSONDecodeError,ValidationError,ValueError,TypeError)  as e:
                retries += 1
                self.last_plan_validation = validation_error(e).diagnostics
                err_text = self.last_plan_validation['summary'] if getattr(self, 'require_session_plan', False) else self._explain_error(e)
                print(f"\n [Agent B] 模型输出没有通过校验"
                      f"\n 错误:{err_text}"
                )

                if retries >= max_retries:
                    if getattr(self, 'require_session_plan', False):
                        raise validation_error(e) from None
                    print(f"\n [Agent B] 重试次数已用完，{task_label}彻底失败。")
                    return None

                print(f"\n 正在触发【自我反思重试机制】"
                      f"\n({retries}/{max_retries})..."
                )

                user_prompt = f"""
                    你上一次{task_label}没有通过程序校验。

                    【原始素材】
                    {source_material}

                    【本次错误】
                    {err_text}

                    【重新生成要求】
                    1. 必须重新生成完整 JSON
                    2. 不允许只修复错误部分
                    3. 必须包含 overall_goal
                    4. phases 必须存在
                    5. phases 必须包含 4~6 个阶段
                    6. 每个 phase 必须包含：
                        phase_name
                        phase_goal
                        tasks
                    7. 每个 task 必须包含：
                        day
                        task_type
                        content
                        expected_outcome
                        source_gap_ids（数组，元素只能取自差距清单里的 gap_id；
                                        无对应就写 []，不要编造）
                    8. day 必须完整覆盖 1~{final_days}
                    9. 不允许重复 day
                    10. 不允许 Markdown
                    11. 不允许 ```json
                    12. 不允许任何解释文字
                    13. 必须输出完整 JSON
                    14. JSON 必须能够被 Python json.loads() 直接解析
                    15. 不允许省略字段
                    16. 不允许使用 ...
                    17. 【重点排查】上一次失败通常源于：JSON 外有多余文字、
                        对象/数组之间漏了逗号、用了单引号而非双引号、
                        结尾没有闭合、**键名被翻译成了中文**、
                        **day 重复或跳号**。请逐项检查后再输出
                    18. 【键名必须是英文原件，一字不改】顶层用 overall_goal 与
                        phases；phase 用 phase_name / phase_goal / tasks；
                        task 用 day / task_type / content / expected_outcome。
                        禁止写成"计划名称""学习阶段""具体内容"这类中文键名
                    19. 【控制长度】content 与 expected_outcome 各写一句即可，
                        phases 4~6 个 —— JSON 过长会被截断，导致整次输出作废
                    【JSON Schema】
                    {self.schema_json}
                    """
                continue

            except Exception as e:
                # ==================================================
                # 非 LLM 校验错误：不重试，直接抛出
                # ==================================================
                print("\n[Agent B] 发生非预期程序异常：")
                print(f"错误类型：{type(e).__name__}")
                print(f"错误信息：{e}")
                raise

        return None

    # =========================================================
    # 路径一：直接生成（原有行为）
    # =========================================================
    def generate_plan(self, gap_report, final_days,max_retries=3,
                      gaps=None, report_id=None):
        """
        `gaps` / `report_id` 是 v6 新增的**可选**上下文：
        给了就把来源关系落成可追溯数据，不给则维持旧行为（两列 NULL）。
        老调用 `generate_plan(gap_report, final_days)` 完全不受影响。
        """
        print(f"\n [Agent B] 开始为您深度定制为期 {final_days} 天的【多阶段突击计划】...")

        self._set_system_prompt(final_days)

        prompt = self._plan_prompt(gap_report, final_days, gaps)
        validated_plan = self._generate_validated(
            user_prompt=prompt,
            source_material=prompt,
            final_days=final_days,
            max_retries=max_retries,
            task_label="生成的学习计划",
        )
        if validated_plan is None:
            return None

        plan_id = f"PLAN_{uuid.uuid4().hex[:12]}"
        self.current_plan_id=plan_id

        if self.db:
            # 注意：
            # 如果数据库失败，让异常直接暴露
            self.db.save_complete_plan(
                plan=validated_plan,
                plan_id=plan_id,
                source_report_id=report_id,
                # 关键区分：gaps=None 表示"没有报告上下文"（写 NULL）；
                # gaps=[] 表示"有报告但报告里没有 gap"（写 no_gaps_in_report）。
                known_gap_ids=(None if gaps is None
                               else gap_registry.known_gap_ids(gaps)),
            )
            self._log_plan_provenance(validated_plan, gaps, plan_id, report_id)

        return validated_plan

    def _log_plan_provenance(self, plan, gaps, plan_id, report_id):
        """
        把"这份计划的来源覆盖情况"写进交接记录，便于审计。

        与落库用的是同一个 `gap_registry.classify()`，所以 payload 的统计
        和 study_tasks.provenance_status 不会各说各话。
        只记 id 与计数，不记任务正文。
        """
        if gaps is None:
            return

        stats = gap_registry.summarize_plan_provenance(plan, gaps)
        stats["plan_id"] = plan_id
        stats["report_id"] = report_id
        self._log_handoff("Agent_B", "Agent_C", "plan_task_map", stats)

        if stats.get("unknown_ids"):
            # 明确打出来：模型编了不存在的 gap_id。不是静默忽略。
            print(f"[Agent B] ⚠ 模型声明了 {len(stats['unknown_ids'])} 个"
                  f"不存在的 gap_id：{'、'.join(stats['unknown_ids'][:5])}"
                  f"（已记录，未写入任务来源）")

    # =========================================================
    # 反思循环：修正
    # =========================================================
    def revise_plan(self, plan, critiques, final_days, max_retries=3,
                    gaps=None):
        """
        按 Agent F 的审计意见修正计划。

        参数
        ----
        plan      : 待修正的 LearningPlan
        critiques : Critique 列表（**必须已经过 validate_critiques 过滤**）
        gaps      : 本次分析的合法 gap 清单（可选）。

        为什么修订也要 gaps
        ------------------
        首次生成时 prompt 里带了 gap 目录，模型据此填 `source_gap_ids`；
        但修订路径此前只拿到"上一版计划 JSON + 审计意见"，**没有目录** ——
        旧 JSON 里碰巧保留的 id 成了唯一线索。一旦审计要求"补一个新的来源"，
        模型要么照抄旧 id，要么凭空编一个。

        传入 gaps 后，修订与首次生成使用**同一份**合法目录：
        · 仍然有效的 id 必须保留；
        · 需要新增/修改时只能从目录里选，不得编造。
        `gaps=None` 时维持旧行为（不出现目录，也不出现"只能从目录选"的要求），
        不伪造一个空目录。
        """
        if not critiques:
            return plan

        crit_lines = []
        for i, c in enumerate(critiques, 1):
            crit_lines.append(
                f"  {i}. 问题：{c.problem}\n"
                f"     针对计划中的：{c.target}\n"
                f"     依据（{c.evidence_kind}）：{c.evidence_ref}\n"
                f"     修改建议：{c.suggestion}"
            )
        crit_block = "\n".join(crit_lines)

        # 目录进入 source_material —— 它同时被嵌进 user_prompt，
        # 所以修订模型在"当前请求"和"出错重试"两条路上看到的是同一份目录。
        catalog = gap_registry.format_gap_catalog(gaps or [])

        source = (f"【你上一版的学习计划】\n{plan.model_dump_json()}\n\n"
                  f"【审计员提出的问题】\n{crit_block}")
        if catalog:
            source = f"{source}\n\n{catalog}"

        # 只有在真的给了目录时，才加"只能从目录选"这条约束
        gap_rule = ""
        if catalog:
            gap_rule = (
                "\n        6. 【来源字段 source_gap_ids】每个 task 里**仍然有效**的"
                "引用必须保留，不要因为改写措辞就丢掉；\n"
                "           需要新增或修改引用时，只能从上面的差距清单里挑选完整的 "
                "gap_id，**不得编造**；\n"
                "           确实不对应任何差距时留空数组 []。"
            )

        print(f"\n [Agent B] 正在根据 {len(critiques)} 条审计意见修正计划...")
        if catalog:
            print(f"           已附上 {len(gaps)} 条合法差距目录（与首次生成同一份）")

        self._set_system_prompt(final_days)

        user_prompt = f"""
        你是培训官。你上一版学习计划被审计员挑出了问题，现在请**修正**它。

        {source}

        【修正要求】
        1. **只针对上面列出的问题修改，不要推翻重来** —— 没被批评的部分保持原样
        2. 修正后仍必须满足：完整覆盖 1~{final_days} 天、4~6 个阶段、
           每天一个 task、所有字段齐全
        3. 输出**完整 JSON**（不是差异补丁）
        4. 修正要落在具体内容上，不要只改措辞
        5. 只输出 JSON，不要任何解释文字或分析{gap_rule}
        """
        return self._generate_validated(
            user_prompt=user_prompt,
            source_material=source,
            final_days=final_days,
            max_retries=max_retries,
            task_label="修正的学习计划",
        )

    # =========================================================
    # 反思循环：编排
    # =========================================================
    def _log_handoff(self, from_agent, to_agent, msg_type, payload):
        """写多智能体交接记录（best-effort：失败不影响业务）。"""
        if not self.db:
            return
        try:
            self.db.append_message(self.trace_id, from_agent, to_agent,
                                   msg_type, payload)
        except Exception as e:
            print(f"  [交接失败] {e}")

    def plan_with_reflection(self, gap_report, final_days, resume_text=None,
                             jd_text=None, critic=None, max_rounds=1,
                             gaps=None, report_id=None):
        """
        生成 -> Agent F 审计 -> 修正 -> （最多 max_rounds 轮）-> 落库

        收敛由三条一起保证：
          1. 最多 max_rounds 轮（硬上限）
          2. 某一轮**没有新的有效批评**，立即停止
          3. 上一轮的批评会明确告知 F 不要重复

        **为什么默认只跑 1 轮（实测调优结果）**
        跑满 2 轮做过真实对比：第 1 轮和第 2 轮提的问题**落在同一批缺口区域**，
        第 2 轮只是更细 —— 但它多花 19,845 token，还把计划从 978 字撑到 1,736 字。
        边际收益明显低于成本。需要更彻底打磨时用 `--rounds 2` 显式开启。

        （第 2 条判据在实践中很少触发：模型被要求挑刺时总能找出问题，
          真正兜底的是轮次上限。）

        计划**只在最后落库一次** —— 中间版本不写进数据库，
        避免留下"改到一半"的残骸（这是这个项目踩过的坑）。

        三条上下文流（别把它们混成一条）
        --------------------------------
        1. **B 首次生成**：`_plan_prompt(gap_report, days, gaps)`
           = 精简人话报告 + 结构化目录。目录在这里出现**一次**。
        2. **B 反思修订**：`revise_plan(..., gaps=gaps)`
           = 上一版计划 JSON + 审计意见 + 同一份目录。
        3. **F 审计**：`critic.critique(..., gap_report=critic_gap_context)`
           = 精简人话报告 + 同一份目录。

        为什么 F 需要单独组合（真实缺陷）
        --------------------------------
        T02-B 为了让 B 的 prompt 不重复，把 `gap_report` 在 gaps 非空时改成了
        精简版（不含 gap 明细）。但这段字符串同时也是 F 的输入 —— 于是 F 只看到
        "目标岗位 / 致命弱点 / 见下方清单 / 突击建议"，而"下方"什么都没有。
        F 要在**没有差距证据**的情况下判断"计划是否对准了真实差距"，
        只能凭计划内部一致性，正好丢掉它最该抓的那类问题。

        所以这里只为 F 组合一次：精简报告 + 目录。简历/JD 已经有独立参数
        （`resume_text` / `jd_text`），不再复制进 gap context。
        `gaps` 为空或 None 时原样使用 `gap_report`（旧行为，不伪造目录）。
        """
        # 让 F 与 B 共用同一条 trace，交接记录才能串起来
        if not self.trace_id:
            self.trace_id = f"TRACE_{uuid.uuid4().hex[:12]}"

        # F 的差距上下文：精简报告 + 同一份结构化目录（与 B 两侧逐字一致，
        # 都来自同一次 extract_gaps 的 format_gap_catalog 结果）。
        # 注意：**不要**把这个组合塞回 _plan_prompt —— B 的 prompt 已有目录，
        # 再塞一次就是同一提示词里两份差距明细。
        critic_gap_context = gap_report
        if gaps:
            critic_gap_context = (
                f"{gap_report}\n\n{gap_registry.format_gap_catalog(gaps)}")

        print(f"\n[Agent B] 开启反思循环（最多 {max_rounds} 轮，trace={self.trace_id}）")

        plan = self._generate_validated(
            user_prompt=self._plan_prompt(gap_report, final_days, gaps),
            source_material=self._plan_prompt(gap_report, final_days, gaps),
            final_days=final_days,
            task_label="生成的学习计划",
        )
        if plan is None:
            return None

        if critic is None:
            from agent_f_critic import CriticAgent
            critic = CriticAgent(db=self.db, trace_id=self.trace_id)

        prior = []
        self.reflection_history = []

        for r in range(1, max_rounds + 1):
            result = critic.critique(
                plan, resume_text=resume_text, jd_text=jd_text,
                # 传组合后的上下文（含结构化目录），而不是被去重后的精简报告 ——
                # 否则 F 看不到任何 gap 证据，只能凭计划内部一致性挑刺。
                gap_report=critic_gap_context,
                round_no=r, prior_critiques=prior)

            valid = result.get("_valid") or []
            rejected = result.get("_rejected") or []

            # 交接：F -> B（审计意见，含被丢弃的，便于审计"模型想提但提不出证据"）
            self._log_handoff("Agent_F", "Agent_B", "critique", {
                "round": r,
                "verdict": result.get("verdict"),
                "summary": result.get("summary"),
                "valid": [c.to_dict() for c in valid],
                "rejected": [{"problem": c.problem, "reason": why}
                             for c, why in rejected],
            })

            self.reflection_history.append({
                "round": r,
                "summary": result.get("summary"),
                "critiques": [c.to_dict() for c in valid],
                "rejected_count": len(rejected),
            })

            # 收敛判据：没有有效批评就停
            if not valid:
                print(f"[Agent B] 第 {r} 轮无有效批评 —— 已收敛，停止迭代")
                break

            new_plan = self.revise_plan(plan, valid, final_days, gaps=gaps)
            if new_plan is None:
                print("[Agent B] 修正失败，保留上一版计划（不丢已生成的内容）")
                break

            self._log_handoff("Agent_B", "Agent_F", "revision", {
                "round": r,
                "addressed": len(valid),
            })

            plan = new_plan
            prior = prior + valid
        else:
            print(f"[Agent B] 已达最大轮次 {max_rounds}，停止迭代")

        plan_id = f"PLAN_{uuid.uuid4().hex[:12]}"
        self.current_plan_id = plan_id
        if self.db:
            self.db.save_complete_plan(
                plan=plan, plan_id=plan_id,
                source_report_id=report_id,
                known_gap_ids=(None if gaps is None
                               else gap_registry.known_gap_ids(gaps)),
            )
            self._log_plan_provenance(plan, gaps, plan_id, report_id)

        print(f"[Agent B] 反思循环结束，最终计划 {plan_id} 已落库"
              f"（共 {len(self.reflection_history)} 轮审计）")
        return plan

    # =========================================================
    # gap 报告渲染 & 从 trace 取数
    # =========================================================
    def _render_gap_report(self, record, include_gaps=True) -> str:
        """
        把库里的 JSON 还原成'人话版'差距报告。

        `include_gaps=False` 时**不渲染两个 gap 明细段**（隐形 Gap / 硬技能表）——
        因为同一份 prompt 里还会附结构化 gap 目录，两段都放等于把同一批内容
        粘贴两遍，纯属白烧 token。致命弱点与突击建议仍然保留（目录里没有）。

        默认 True，保持老调用与"没有人传结构化目录"的场景行为不变。
        """
        audit = json.loads(record["audit_json"] or "{}")
        gaps  = json.loads(record["gap_table_json"] or "[]")

        lines = [f"目标岗位：{record['company']} {record['title']}"
                f"（TIS {record['tis_score']}）", ""]

        lines += ["【致命弱点】", audit.get("fatal_weakness", "无"), ""]

        if include_gaps:
            lines.append("【隐形 Gap】")
            for g in audit.get("invisible_gaps", []):
                lines.append(
                    f"- {g.get('skill')}：JD要求 {g.get('industry_requirement')}；"
                    f"现状 {g.get('candidate_current')}；差距 {g.get('gap_reason')}")
            lines.append("")

            lines.append("【硬技能 Gap 表】")
            for r in gaps:
                lines.append(f"- {r['技能']} | {r['状态']} | {r['优先级']}")
            lines.append("")
        else:
            # 明细已在结构化目录里，这里只留一句指路，避免读者以为漏了内容
            lines += ["【差距明细】见下方结构化差距清单"
                      "（gap_id 与判别字段在同一对象内）。", ""]

        lines.append("【突击建议】")
        for a in audit.get("actionable_advice", []):
            lines.append(f"- {a}")

        return "\n".join(lines)

    def plan_from_trace(self, trace_id, final_days, resume_text=None,
                        jd_text=None, with_reflection=False, critic=None,
                        max_rounds=1):
        """
        从库里读 gap -> 生成计划。

        with_reflection=True 时走「生成 → Agent F 审计 → 修正」的反思循环。
        简历/JD 是给 Agent F 判断"计划是否针对这个人"用的 —— 不传的话
        F 只能用计划内部一致性作为依据，抓不到"通用模板"这类最严重的问题。
        """
        record = self.db.get_gap_report_by_trace(trace_id)
        if record is None:
            raise ValueError(f"trace={trace_id} 没有 gap 报告，请先跑 Agent A")

        # 计划必须归属到**这条** trace：否则交接记录会挂在 Agent 初始化时的
        # 旧 trace 上（与 Agent A 曾经把审计挂到随机 UUID 下是同一类缺陷）。
        if trace_id:
            self.trace_id = trace_id

        # v6：把报告里的结构化 gap 提成带稳定 ID 的清单，交给模型回填
        # `source_gap_ids`。这是"任务 → 来源差距"的唯一合规建立方式 ——
        # 不再靠任务正文与技能名的子串匹配去猜。
        audit = json.loads(record["audit_json"] or "{}")
        gaps = gap_registry.extract_gaps(audit, record["report_id"])
        report_id = record["report_id"]

        # 有结构化目录时，人话版报告不再重复渲染 gap 明细（避免同一 prompt
        # 里出现两份相同的差距内容）—— 明细由目录承载，且与 gap_id 绑在一起。
        gap_report = self._render_gap_report(record, include_gaps=not gaps)
        print(f"\n[Agent B] 已从库读取 gap：{record['company']} {record['title']}")

        if gaps:
            print(f"[Agent B] 已登记 {len(gaps)} 条可追溯差距"
                  f"（{report_id}）")
        else:
            # 旧版报告 / 模型没给结构化 gap：不编造来源，只明确记录"无从关联"
            print("[Agent B] ⚠ 该报告没有结构化 gap —— "
                  "任务将被标记为 no_gaps_in_report")

        if with_reflection:
            return self.plan_with_reflection(
                gap_report, final_days, resume_text=resume_text,
                jd_text=jd_text, critic=critic, max_rounds=max_rounds,
                gaps=gaps, report_id=report_id)

        return self.generate_plan(gap_report, final_days=final_days,
                                  gaps=gaps, report_id=report_id)


def build_plan_prompt(gap_report, final_days, gaps=None, *, require_sources=False, learning_preferences=None):
        """
        构造首次生成请求。

        下面三处都是**踩坑换来的**，不是客套话：
        1. 结尾必须显式说"要计划、不要分析" —— 否则"严厉培训官"的人设会让模型
           跑去批评 gap 报告，输出一篇《它是诊断书，不是作战地图》（白烧 4,363 token）
        2. 必须给出**字段名的英文原件** —— 实测模型会输出中文键名（如 "计划名称"），
           而 Pydantic 只报 "Field required: overall_goal"，模型看不出问题在哪
           （白烧 9,540 token，还连带触发一次截断扩容）
        3. 必须给排期与规模约束 —— "存在重复的 day" 和"JSON 过长被截断"
           是另外两个高频失败

        `gaps` 给定时，额外附一段**带 gap_id 的差距清单**，并要求每个 task 用
        `source_gap_ids` 回填。这是让"任务 → 来源差距"变成**显式声明**而不是
        事后文本相似度猜测的唯一办法。
        """
        from diagnosis_evidence import plan_audit_summary
        gap_report = plan_audit_summary(gap_report)
        catalog = gap_registry.format_gap_catalog(gaps or [], allow_unlinked=not require_sources)
        rules = session_plan_rules(final_days,learning_preferences=learning_preferences) if require_sources else ""
        if any(g.get('source') == 'evidence_assessment' for g in (gaps or [])):
            rules += ('\n【A证据交接】not_provided/待补充证据不是确认不会。recommended_action=verify的来源'
                      '先安排补充材料或小型验证；不得写成已经证实的能力缺陷。加分项可暂缓，'
                      '职责按实习层级安排，不要求短期掌握整套生产系统。诊断分不是成长成绩。')
        if learning_preferences is not None:
            from daily_learning import daily_plan_rules
            rules += '\n'+daily_plan_rules(learning_preferences)
        phase_range = f"4~{min(6, final_days)}" if require_sources else "4~6"

        return f"""差距报告如下：
{gap_report}

请直接输出这份为期 {final_days} 天的学习计划 JSON。
不要分析、不要建议、不要写任何 JSON 之外的内容。

【JSON 键名必须使用下面的英文原件，不要翻译成中文】
{{
  "overall_goal": "总体目标（一句话）",
  "phases": [
    {{"phase_name": "第一阶段：xxx",
      "phase_goal": "本阶段要达成的目标",
      "tasks": [
        {{"day": 1,
          "task_type": "理论学习",
          "content": "当天学什么（一句话）",
          "expected_outcome": "当天交付标准（一句话）",
          "source_gap_ids": ["该任务针对的 gap_id"]}}
      ]}}
  ]
}}

{catalog}

{rules}

【排期规则】day 从 1 到 {final_days} 连续、不重复、不跳号；每个 task 占一个 day。
【规模控制】phases {phase_range} 个；content 与 expected_outcome 各写一句话即可 ——
JSON 过长会被截断，导致整次输出作废。
"""


def build_plan_system_prompt(final_days, schema_json, *, require_sources=False):
        phase_range = f"4 到 {min(6, final_days)}" if require_sources else "4 到 6"
        return f"""
        你是一位极其严厉的大厂技术培训官。
        请根据候选人的【差距报告】，为他制定一份为期 {final_days} 天的补位计划。
        要求：必须分为 {phase_range}个阶段 (Phases)，每个阶段包含具体的每日任务 (Tasks)。
        
        【极度严苛的约束】：【输出规则】
                            1. 只允许输出 JSON
                            2. 不允许使用 Markdown
                            3. 不允许输出 ```json
                            4. 不允许输出任何解释文字
                            5. 所有字符串必须使用双引号
                            6. JSON 中所有对象和数组之间必须使用逗号分隔
                            7. 必须保证 JSON 可以被 Python json.loads() 直接解析
                            8. tasks 中 day 必须是整数。
                            9. day 必须覆盖 1 到 {final_days}。
                            10.必须确保 JSON 结构完整闭合，不允许输出被截断的 JSON
                            11.所有task必须完整输出
                            12.不允许省略任何字段
                            13.不允许使用...    
        【JSON Schema】
        {schema_json}

        {EVIDENCE_PROMPT_RULES_GROUNDING}
        """

