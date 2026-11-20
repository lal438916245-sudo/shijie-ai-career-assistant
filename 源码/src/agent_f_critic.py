"""
Agent F：审计员（Critic）—— 对学习计划挑刺

为什么需要它
------------
Agent B 生成计划后直接落库、直接输出。没有任何环节检查
"这份计划是否真的针对这个人"。

结果很典型：计划看起来无懈可击 —— 4~6 个阶段、day 完整覆盖、
结构校验全过 —— 但**可能是一份通用模板**：换成任何人的 gap 报告
都能生成几乎一样的东西。

用户举的那个例子正是靶心："你给出的 C++ 学习路径太泛了，
没有结合他 VTG 项目里的指针错误。"

这是 Agent 能力分层里的第 3 层：**能从结果中修正自己**（Reflection）。
但天真的实现有三个已知失败模式，本模块用三个硬约束逐一解决：

  ┌ 失败模式 ────────────┬ 对策 ──────────────────────────────────┐
  │ 1. 自我肯定           │ 不合并到 B：F 是独立 Agent，独立 system   │
  │    （同模型自评说好话）│ prompt，且要求它"只找问题，不说优点"       │
  │ 2. 批评无法验证       │ **grounding**：每条批评必须有 evidence_ref │
  │    （"感觉不够深入"）  │                                        │
  │ 3. 无限循环烧 token   │ ① 最多 2 轮 ② 无新的有效批评即收敛        │
  │                       │ ③ 上一轮提过的明确禁止重复                 │
  └───────────────────────┴────────────────────────────────────────┘

最关键的是**代码级过滤** `validate_critiques()`
------------------------------------------------
prompt 只能"请求"模型提有据批评，代码才能"保证"它提不出来。
两条硬规则：

  1. `evidence_ref` 为空        -> 丢弃（无据批评，不可证伪）
  2. `target` 在计划里找不到    -> 丢弃（鬼影批评，批评了不存在的东西）

第 2 条尤其重要：它让"批评"必须落在计划的实际文字上，
而不是模型凭想象编一条计划里根本没有的条文来批。

复用契约层，不发明第六套字段
----------------------------
`evidence_kind` 沿用 `contracts` 的来源词表（resume / jd / gap），
只额外新增一个 `plan_internal`（批评的依据是计划自身的自相矛盾）。

自检
----
    python src/agent_f_critic.py
"""

from dataclasses import dataclass

from llm_client import AgentBase
from json_utils import parse_llm_json


# 批评依据的来源类型。
# 前三个直接复用契约层的词表；plan_internal 是 F 特有的
# —— 它的依据是"计划自己前后矛盾"，不指向任何外部证据。
CRITIQUE_KINDS = ("resume", "jd", "gap", "plan_internal")

KIND_LABEL = {
    "resume": "简历原句",
    "jd": "JD 条目",
    "gap": "gap 报告项",
    "plan_internal": "计划内部矛盾",
}

# 每轮最多接受几条批评。
# 从 4 降到 3 是实测调优的结果：模型被要求"挑刺"时总能找出问题，
# 提得越多、修正就越发散，而边际收益递减 —— 实测单轮 4 条让成本涨到单跑 B 的 9 倍。
MAX_CRITIQUES_PER_ROUND = 3


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Critique:
    """一条批评。target 必须指向计划里真实存在的文字。"""
    target: str = ""
    problem: str = ""
    evidence_kind: str = "plan_internal"
    evidence_ref: str = ""
    suggestion: str = ""

    def to_dict(self):
        return {
            "target": self.target,
            "problem": self.problem,
            "evidence_kind": self.evidence_kind,
            "evidence": self.evidence_ref,
            "suggestion": self.suggestion,
        }

    def brief(self):
        return f"[{self.evidence_kind}] {self.problem}"


# ============================================================
# 计划展平与定位
# ============================================================

def plan_to_text(plan):
    """
    把学习计划展平成可搜索文本。

    接受 Pydantic 对象或普通 dict —— F 不应该依赖 Agent B 的类型，
    否则两个模块会绑死（B 改结构就得改 F）。
    """
    if hasattr(plan, "model_dump"):
        plan = plan.model_dump()
    if not isinstance(plan, dict):
        return str(plan)

    parts = [str(plan.get("overall_goal") or "")]
    for ph in (plan.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        parts.append(str(ph.get("phase_name") or ""))
        parts.append(str(ph.get("phase_goal") or ""))
        for t in (ph.get("tasks") or []):
            if not isinstance(t, dict):
                continue
            parts.append(str(t.get("content") or ""))
            parts.append(str(t.get("expected_outcome") or ""))
    return "\n".join(parts)


def _locatable(target, plan_text):
    """
    target 能否在计划里定位到。

    先去掉全部空白再比 —— 模型抄片段时常会改动空格与换行。
    找不到时退一步：如果前 15 个字能在计划里找到，也算命中
    （模型可能只截了片段的前半句，或改动了后半句的标点）。
    """
    t = "".join((target or "").split())
    p = "".join((plan_text or "").split())
    if not t:
        return False
    if t in p:
        return True
    if len(t) >= 15 and t[:15] in p:
        return True
    return False


# ============================================================
# 代码级过滤 —— 本模块的核心
# ============================================================

def validate_critiques(raw_items, plan_text):
    """
    过滤无效批评。

    返回 (valid, rejected)：
        valid    —— Critique 列表，最多 MAX_CRITIQUES_PER_ROUND 条
        rejected —— [(Critique, 丢弃原因), ...]，用于审计与调 prompt

    这一步是"Reflection 从表演变成机制"的关键：模型可以随便说，
    但说不到点上的批评进不了下一轮修正。
    """
    valid, rejected = [], []

    for it in (raw_items or []):
        if not isinstance(it, dict):
            continue

        c = Critique(
            target=str(it.get("target") or "").strip(),
            problem=str(it.get("problem") or "").strip(),
            evidence_kind=str(it.get("evidence_kind") or "").strip().lower(),
            evidence_ref=str(it.get("evidence_ref")
                             or it.get("evidence") or "").strip(),
            suggestion=str(it.get("suggestion") or "").strip(),
        )

        if not c.problem:
            rejected.append((c, "问题描述为空"))
            continue

        if c.evidence_kind not in CRITIQUE_KINDS:
            c.evidence_kind = "plan_internal"

        # 规则 1：无据批评 —— 不可证伪的"感觉"一律不算
        if not c.evidence_ref:
            rejected.append((c, "无证据（evidence_ref 为空，不可证伪）"))
            continue

        # 规则 2：鬼影批评 —— 批评的对象必须真实存在于计划里
        if not _locatable(c.target, plan_text):
            rejected.append((c, "target 无法在计划中定位（批评了不存在的内容）"))
            continue

        valid.append(c)

    return valid[:MAX_CRITIQUES_PER_ROUND], rejected


# ============================================================
# Agent F 本体
# ============================================================

CRITIC_SYSTEM_PROMPT = """
        【Role】你是培训计划的**审计员**。你的唯一职责是挑刺。
        【核心原则】只提**可验证**的问题。
          每条批评都必须挂一个具体依据：简历原句 / JD 条目 / gap 项 /
          或计划自身的自相矛盾。提不出依据的"感觉不够深入""建议多实践"
          一律不要提 —— 那是不合格的批评。
        【分寸】只挑「不改就无法交付」的问题，不挑「可以更好」的建议 ——
          后者会让修订陷入无限打磨，每一轮都要烧掉一次完整的推理成本。
        【Tone】直接、具体、对事不对人。不要先说优点再转折，直接说问题。
        【Constraint】必须严格遵循预设的 JSON 格式输出，禁止在 JSON 外附带任何解释性文字！
"""

class CriticAgent(AgentBase):

    def __init__(self, db=None, trace_id=None, model_name=None):
        sys_prompt = CRITIC_SYSTEM_PROMPT
        super().__init__(
            agent_name="审计员 Agent_F",
            system_prompt=sys_prompt,
            db=db,
            model_name=model_name,
            trace_id=trace_id,
        )

    def critique(self, plan, resume_text=None, jd_text=None, gap_report=None,
                 round_no=1, prior_critiques=None):
        """
        审计一份学习计划。

        参数
        ----
        plan            : LearningPlan 对象或 dict
        resume_text     : 简历原文（F 判断"是否针对这个人"的关键）
        jd_text         : 目标岗位 JD
        gap_report      : 计划所依据的 gap 报告（人话版文本）
        round_no        : 第几轮（用于提示语）
        prior_critiques : 上一轮已提过的批评，要求不重复

        返回 dict，含：
            verdict / summary / critiques（原始）
            _valid    : 通过代码校验的 Critique 列表
            _rejected : [(Critique, 原因), ...]
        """
        plan_text = plan_to_text(plan)

        print(f"\n[Agent F] 第 {round_no} 轮审计开始"
              f"（计划文本 {len(plan_text)} 字）...")

        jd_block = (f"【目标岗位 JD】\n{jd_text}" if jd_text
                    else "【目标岗位 JD】未提供。")
        resume_block = (f"【候选人简历原文】\n{resume_text}" if resume_text
                        else "【候选人简历】未提供 —— 此时无法判断计划是否"
                             "针对这个人，请只用 plan_internal 依据。")
        gap_block = (f"【猎头的 gap 报告（计划的制定依据）】\n{gap_report}"
                     if gap_report else "【gap 报告】未提供。")

        if prior_critiques:
            lines = []
            for c in prior_critiques:
                p = c.problem if isinstance(c, Critique) else (c or {}).get("problem", "")
                if p:
                    lines.append(f"  - {p}")
            prior_block = ("【上一轮已经提过的批评 —— **不要再重复**，只提新的问题】\n"
                           + "\n".join(lines))
        else:
            prior_block = ""

        user_prompt = f"""
        【Context】你是培训计划的审计员。下面是一份为这位候选人生成的学习计划。
        请挑刺 —— 重点是找出它**没有针对这个人**的地方。

        {jd_block}

        {resume_block}

        {gap_block}

        【待审计的学习计划】
        {plan_text}

        【Objective】先做一次**交付判断**，再决定要不要提问题。

        判断标准是：**这一条不改，这份计划还能不能交付给学员？**
          · 会误导他、让他白花时间、或计划本身自相矛盾  -> 必须提
          · 只是"可以更好""能再深入点""还可以补充"       -> **不要提**

        后一类建议并不错误，但会把反思循环变成无限打磨 ——
        计划永远可以更好，而每一轮都要烧掉一次完整的推理成本。
        如果你判断这版已达到可交付标准，`critiques` 就留空。

        确实需要提的问题，按严重程度排序：
          ① 通用模板 —— 内容与这个人的具体项目/短板无关
          ② 与 gap 不符 —— 花时间补的不是 gap 里的项，或漏了 gap 的关键项
          ③ 与简历脱节 —— 没用上候选人已经踩过的坑、做过的项目
          ④ 不可考核 —— expected_outcome 无法判断是否达成
          ⑤ 内部矛盾 —— 阶段目标与任务内容不一致、day 编排错位

        【硬性要求（违反会被程序直接丢弃，白写）】
          1. 每条批评必须给出 `evidence_ref` —— 具体引用简历原句 / JD 条目 /
             gap 项 / 计划内部条文
          2. `target` 必须是**计划里原样存在的文字片段**，程序会逐个校验，
             找不到就作废
          3. **最多 3 条**，宁少勿滥

        【输出纪律（很重要）】
          · JSON 不要缩进美化，紧凑输出
          · 字段限长：problem ≤60 字、evidence_ref ≤60 字、suggestion ≤60 字
          · **推理要克制**，直接给结论，不要反复推演
          · summary 一句话即可

        {prior_block}

        【Output Format】严格输出以下 JSON（紧凑，不要缩进美化）：
        {{
            "verdict": "pass 或 needs_revision",
            "summary": "整体判断（一句话，直接说最致命的问题）",
            "critiques": [
                {{"target": "计划里原样存在的文字片段",
                  "problem": "问题是什么（≤60 字）",
                  "evidence_kind": "resume 或 jd 或 gap 或 plan_internal",
                  "evidence_ref": "具体依据（≤60 字）",
                  "suggestion": "怎么改（≤60 字）"}}
            ]
        }}
        """
        # 8000 而非 5000：实测审计输出会撞 5000 上限并触发一次扩容重试
        # （计划文本越长，F 要引用的原文片段越多，输出越长）
        raw = self.think(user_prompt, max_tokens=8000)
        data, degraded = parse_llm_json(raw)
        if degraded:
            print("[Agent F] ⚠ 审计输出被截断，已抢救出部分结果")

        valid, rejected = validate_critiques(data.get("critiques"), plan_text)

        data["_valid"] = valid
        data["_rejected"] = rejected
        data["_degraded"] = degraded
        # 以代码校验结果为准，不信任模型自己给的 verdict
        data["verdict"] = "needs_revision" if valid else "pass"

        print(f"[Agent F] 第 {round_no} 轮审计完成："
              f"有效批评 {len(valid)} 条，丢弃 {len(rejected)} 条")
        for c, why in rejected:
            print(f"          丢弃：{why} —— {c.problem[:30]}")

        return data


# ============================================================
# 自检
# ============================================================

def _self_test():
    print("=" * 62)
    print("  agent_f_critic 自检（不调用模型，只测代码级逻辑）")
    print("=" * 62)

    plan = {
        "overall_goal": "补齐大数据与分布式基础，达到腾讯数据挖掘岗要求",
        "phases": [
            {"phase_name": "第一阶段：C++ 底层",
             "phase_goal": "掌握指针与内存管理",
             "tasks": [
                 {"day": 1, "task_type": "理论学习",
                  "content": "复习 C++ 指针与内存管理基础",
                  "expected_outcome": "能写出指针运算示例"},
                 {"day": 2, "task_type": "实战编码",
                  "content": "实现一个动态数组",
                  "expected_outcome": "通过自测用例"},
             ]},
            {"phase_name": "第二阶段：Spark",
             "phase_goal": "掌握 Spark 核心",
             "tasks": [
                 {"day": 3, "task_type": "理论学习",
                  "content": "学习 RDD 与宽窄依赖",
                  "expected_outcome": "能解释 shuffle"},
             ]},
        ],
    }
    plan_text = plan_to_text(plan)

    cases = [
        ("合法批评（target 存在 + 有证据）",
         {"target": "复习 C++ 指针与内存管理基础",
          "problem": "与候选人项目脱节", "evidence_kind": "resume",
          "evidence_ref": "VTG 项目里出现过指针错误", "suggestion": "结合 VTG 讲"},
         True),

        ("无据批评（evidence_ref 为空）应被丢弃",
         {"target": "复习 C++ 指针与内存管理基础",
          "problem": "不够深入", "evidence_kind": "resume",
          "evidence_ref": "", "suggestion": "再深入点"},
         False),

        ("鬼影批评（target 不在计划里）应被丢弃",
         {"target": "第三阶段：Kafka 源码精读",
          "problem": "顺序不合理", "evidence_kind": "plan_internal",
          "evidence_ref": "与第一阶段目标冲突", "suggestion": "调整顺序"},
         False),

        ("problem 为空应被丢弃",
         {"target": "学习 RDD 与宽窄依赖", "problem": "",
          "evidence_kind": "gap", "evidence_ref": "gap 里有 Spark 项",
          "suggestion": "无"},
         False),

        ("plan_internal 依据（计划自相矛盾）应通过",
         {"target": "掌握 Spark 核心",
          "problem": "阶段目标与任务不匹配", "evidence_kind": "plan_internal",
          "evidence_ref": "目标写『掌握核心』但只排了 1 天 RDD",
          "suggestion": "补 shuffle 与调优"},
         True),
    ]

    ok = True
    valid_count = 0
    for desc, item, should_pass in cases:
        valid, rejected = validate_critiques([item], plan_text)
        passed = bool(valid) == should_pass
        ok = ok and passed
        if valid:
            valid_count += 1
        print("\n  [%s] %s" % ("OK" if passed else "FAIL", desc))
        if valid:
            print("        -> 通过：%s" % valid[0].brief())
        else:
            print("        -> 丢弃：%s" % rejected[0][1])

    # 数量上限
    many = [{"target": "学习 RDD 与宽窄依赖", "problem": "问题%d" % i,
             "evidence_kind": "jd", "evidence_ref": "依据%d" % i,
             "suggestion": "改%d" % i} for i in range(9)]
    valid, rejected = validate_critiques(many, plan_text)
    capped = len(valid) <= MAX_CRITIQUES_PER_ROUND
    ok = ok and capped
    print("\n  [%s] 数量上限：提交 9 条 -> 接受 %d 条（上限 %d）"
          % ("OK" if capped else "FAIL", len(valid), MAX_CRITIQUES_PER_ROUND))

    print("\n" + "=" * 62)
    print("  自检结果：%s" % ("全部通过" if ok else "存在失败项"))
    print("=" * 62)
    return ok


if __name__ == "__main__":
    _self_test()
