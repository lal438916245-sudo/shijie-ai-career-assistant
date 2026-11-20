"""
证据契约层（Evidence Contract）

为什么需要它
------------
"证据驱动"是本项目的核心主张，但在引入本模块之前，它只兑现了一处：

    Agent A  invisible_gaps[].gap_reason     <- 无强度、无来源类型
    Agent B  study_tasks                     <- 没有证据概念
    Agent C  verdict + feedback（纯文本）     <- 无强度、无来源类型
    Agent D  evidence + evidence_strength    <- 唯一有校验的
    Agent E  vulnerability（自由文本）        <- 无强度、无来源类型

五个 Agent 用五种方式表达"证据"，于是"证据驱动"是**局部特性**而非**系统属性**。

**当前覆盖（本轮补齐后）**：A / B / C / D / E 六个出口全部接入归一化 ——
`claims_from_agent_a/b/c/d/e`，其中 B 与 C 是本轮新增。
B/C 用的是 `EVIDENCE_PROMPT_RULES_GROUNDING`（不改其结构化输出的 schema，
只约束内容接地），因此它们的 kind 仍靠推断而非声明，这与 D/E 的处理方式一致。

而且它已经反噬过一次：Agent D 曾建议把「1,095 行自检脚本」
改写成「1,100 行自动化测试代码」——把"数量"重新定性为"性质"，
当时没有任何一条规则能拦住它。

本模块提供三样东西
------------------
1. 统一的证据数据结构（Evidence / Claim）
2. 通用校验器 —— 含新规则「**证据等级不得抬高**」（STRENGTH_CEILING）
3. **出口归一化适配器** —— 不动任何 Agent 的 prompt，在结果出口处把
   各 Agent 的输出翻译成统一 Claim。于是立刻能量化出"谁的证据纪律最差"。

设计取舍：为什么走"出口归一化"
------------------------------
改 prompt 要动 4 个 Agent、重跑验证输出质量，风险高、周期长。
出口归一化是**加一层**，零破坏、当天可用，且立刻产出诊断结论。

代价是：kind（来源类型）目前靠关键词**推断**而不是 Agent 声明。
将来把 EVIDENCE_PROMPT_RULES 加进各 Agent 的 system prompt 后，
kind/strength 就从"推断"升级为"声明"，归一化层自动变精确 —— 无需重写。

自检
----
    python src/contracts.py
"""

import re
from dataclasses import dataclass, field


# ============================================================
# 常量定义
# ============================================================

# 证据强度：由弱到强
STRENGTH_ORDER = ("none", "weak", "medium", "strong")

# 证据来源类型
EVIDENCE_KINDS = (
    "resume",       # 简历原句
    "jd",           # JD 条目
    "gap",          # Agent A 的 gap 报告
    "interview",    # Agent E 的对练记录
    "submission",   # 用户提交的作答
    "plan",         # 计划内部一致性
    "inference",    # 模型自推 —— 无外部依据
    "none",         # 无
)

# 每种来源允许的最高强度。
# 这是「证据等级不得抬高」这条规则的代码化：
# 模型自推（inference）最高只能到 weak —— 它不能伪装成有事实依据的结论。
STRENGTH_CEILING = {
    "resume": "strong",
    "jd": "strong",
    "gap": "strong",
    "interview": "strong",
    "submission": "strong",
    "plan": "medium",
    "inference": "weak",
    "none": "none",
}

# 未声明强度时的默认值。
# 一律给 medium 而不是 strong —— 没声明就不给最高等级，这是"证据驱动"的保守立场。
DEFAULT_STRENGTH = {
    "resume": "medium",
    "jd": "medium",
    "gap": "medium",
    "interview": "medium",
    "submission": "medium",
    "plan": "medium",
    "inference": "weak",
    "none": "none",
}

# 「定性升级」检测表。
# 结论里出现左侧的定性词，但证据描述里连一个右侧支撑词都没有 -> 告警。
#
# 为什么单列这条规则：STRENGTH_CEILING 只能拦住"强度标注被抬高"，
# 拦不住"语义定性被抬高"。而这个漏洞真实发生过 —— Agent D 曾建议把
# 「1,095 行自检脚本」改写成「1,100 行自动化测试代码」：强度标的是 medium
# （并没有标错），错在把"脚本"说成了"自动化测试"。
#
# 只告警、不拦截 —— 启发式规则必然有误报，最终判断交给用户。
QUALIFICATION_UPGRADE = {
    "自动化测试": ("自动化", "pytest", "unittest", "测试框架", "用例", "断言", "CI"),
    "单元测试": ("单元测试", "pytest", "unittest", "断言", "覆盖率"),
    "主导": ("主导", "负责人", "owner", "leader", "牵头"),
    "精通": ("精通", "源码", "深入原理"),
    "架构": ("架构", "设计并落地", "技术选型"),
}

KIND_LABEL = {
    "resume": "简历原句",
    "jd": "JD 条目",
    "gap": "Agent A gap 报告",
    "interview": "Agent E 对练记录",
    "submission": "用户作答",
    "plan": "计划内部一致性",
    "inference": "模型推理（无外部依据）",
    "none": "无",
}

# 可复用的 prompt 片段。
# 加进各 Agent 的 system prompt 后，kind / strength 从"推断"变"声明"。
EVIDENCE_PROMPT_RULES = """
【证据契约（本系统所有 Agent 共同遵守）】
1. 每一条结论都必须标注 `evidence_kind`（来源类型）、`evidence_ref`（具体引用）与
   `evidence_strength`（强度）。
2. 强度定义：
   strong —— 能逐字引用到简历原句 / JD 条目 / 已落库的报告字段
   medium —— 有依据但需一步推理（如由多条简历内容归纳得出）
   weak   —— 仅凭行业通识或常识判断，没有候选人本人材料支撑
   none   —— 完全没有依据
3. **不得抬高证据等级**：禁止把"数量"重新定性为"性质"。
   例：1,095 行自检脚本 ≠ 1,100 行自动化测试代码；"参与" ≠ "主导"。
   只能如实描述，或建议用户去补。
4. `evidence_strength` 为 none 的条目，不得给出任何具体表述（改写 / 建议 / 结论），
   只能建议去补。
5. 没有外部依据、仅由你自己推理得出的结论，必须标注为 weak —— 不允许伪装成强证据。
"""

# 给"结构化输出"类 Agent（B / C）用的接地规则。
#
# 为什么不直接把 EVIDENCE_PROMPT_RULES 塞给它们
# ------------------------------------------------
# B 的输出是严格 Pydantic Schema（LearningPlan），C 的输出是固定 JSON。
# 让它们"每条结论额外输出 evidence_kind / evidence_strength 字段"，
# 会直接污染 schema：模型多吐字段 -> 校验失败 -> 重试 -> 白烧 token。
#
# 所以对这两个 Agent，规则要落在**内容接地**上而不是**新增字段**上：
# 不改输出结构，只约束"写出来的东西必须有出处"。
# 来源标注由契约层的出口归一化（claims_from_agent_b/c）负责，不需要模型声明。
EVIDENCE_PROMPT_RULES_GROUNDING = """
【接地要求（不改输出结构，只约束内容）】
1. 你写出的每一条内容，都必须能对应到给定材料里的具体条目
   （差距报告的技能项 / JD 的硬性要求）。
2. **不允许引入材料中没有的技能、技术或要求** —— 那属于凭空发挥。
3. 材料里没提到的东西，如果你认为重要，只能在说明里提示"材料未覆盖，建议补充"，
   不能当作既定事实写进主体内容。
4. 不要为了凑数量而编造条目；材料支撑多少就写多少。
"""


# ============================================================
# 数据结构
# ============================================================

def _rank(strength):
    """强度的数值序位，未知值按最弱处理。"""
    try:
        return STRENGTH_ORDER.index(strength)
    except ValueError:
        return 0


@dataclass
class Evidence:
    """一条证据。"""
    kind: str = "none"
    ref: str = ""
    strength: str = "none"
    # kind 是推断出来的（True）还是 Agent 显式声明的（False）
    inferred_kind: bool = False

    @property
    def label(self):
        return KIND_LABEL.get(self.kind, self.kind)

    def to_dict(self):
        d = {"kind": self.kind, "ref": self.ref, "strength": self.strength}
        if self.inferred_kind:
            d["kind_inferred"] = True
        return d


@dataclass
class Claim:
    """一条带证据的结论 —— 本系统里"结论"的最小单位。"""
    origin: str = ""            # 由哪个 Agent 产出
    text: str = ""              # 结论正文
    evidence: Evidence = field(default_factory=Evidence)
    blocked: bool = False       # 是否因无证据被拦截
    violations: list = field(default_factory=list)   # 违反的契约规则

    def to_dict(self):
        return {
            "origin": self.origin,
            "text": self.text,
            "evidence": self.evidence.to_dict(),
            "blocked": self.blocked,
            "violations": list(self.violations),
        }


# ============================================================
# 核心校验器
# ============================================================

def normalize_evidence(kind=None, ref="", strength=None, inferred=False,
                       available_sources=None):
    """
    归一化一条证据，返回 (Evidence, violations)。

    violations 是规则名列表，用于审计：
      unknown_kind:xxx            未识别的来源类型
      unknown_strength:xxx        未识别的强度
      strength_without_ref        声明了强度却给不出引用
      strength_capped:A->B        强度被下调（试图抬高证据等级）
      claimed_source_unavailable:x  声称的来源本次并不可用
    """
    violations = []
    ref = (ref or "").strip()

    # ---- 1. 归一化 kind ----
    k = (kind or "").strip().lower()
    if k not in EVIDENCE_KINDS:
        if k:
            violations.append("unknown_kind:" + k)
        k = "none"

    # ---- 2. 归一化 strength ----
    s = (strength or "").strip().lower()
    if s not in STRENGTH_ORDER:
        if s:
            violations.append("unknown_strength:" + s)
        # 没声明强度 -> 按来源类型取默认（保守值）
        s = DEFAULT_STRENGTH.get(k, "none")

    # ---- 3. 声明了强度，就必须给得出引用 ----
    if s != "none" and not ref:
        violations.append("strength_without_ref")
        s = "none"

    # ---- 4. 核心新规则：证据等级不得抬高 ----
    ceiling = STRENGTH_CEILING.get(k, "none")
    if _rank(s) > _rank(ceiling):
        violations.append("strength_capped:%s->%s" % (s, ceiling))
        s = ceiling

    # ---- 5. 声称的来源本次是否真的可用 ----
    if available_sources is not None and k not in ("none", "inference"):
        if k not in available_sources:
            violations.append("claimed_source_unavailable:" + k)

    return Evidence(kind=k, ref=ref, strength=s, inferred_kind=inferred), violations


def check_qualification_upgrade(text, ref):
    """
    检查结论是否把证据"定性升级"了 —— 把"数量"重新定性为"性质"。

    返回 violations 列表（形如 qualification_upgrade:自动化测试）。
    只告警不拦截：启发式必然有误报，是否采纳由用户判断。
    """
    violations = []
    text = text or ""
    ref = ref or ""
    for word, supports in QUALIFICATION_UPGRADE.items():
        if word in text and not any(s in ref for s in supports):
            violations.append("qualification_upgrade:" + word)
    return violations


def make_claim(origin, text, kind=None, ref="", strength=None,
               inferred=False, available_sources=None):
    """构造一条 Claim，自动完成证据归一化与校验。"""
    ev, violations = normalize_evidence(
        kind=kind, ref=ref, strength=strength,
        inferred=inferred, available_sources=available_sources,
    )
    violations.extend(check_qualification_upgrade(text, ref))
    return Claim(origin=origin, text=(text or "").strip(),
                 evidence=ev, violations=violations)


# ============================================================
# 漏洞归一化
# ============================================================
# Agent E 的 vulnerability 此前是自由文本，Agent D 拿到后只能原样贴进 prompt，
# 无法知道它攻击的是简历里哪一句、有多严重 —— 于是"挖洞 → 改写 → 复测"
# 这条闭环只能靠模型自己猜关联。
#
# 放在契约层而不是 Agent E 内部，是因为 evidence.py 和 Agent D 都要用它，
# 而 contracts 是本项目唯一一个零依赖的模块（纯标准库），谁都能安全引用 ——
# 不会因为 import 它而连带拉起 openai / chromadb。

VALID_SEVERITY = ("high", "medium", "low")


def normalize_vulnerability(raw):
    """
    把模型 / 历史数据给出的 vulnerability 归一化成结构化对象。

    必须兼容字符串形态 —— 旧数据是自由文本，模型也有小概率偷懒或格式漂移，
    而一处格式不符就会让整条证据链断掉。所以这里"宽进严出"：
    什么都收，但输出规范。

    返回 dict 或 None（表示无漏洞）：
        {"detail", "claim_ref", "severity", "evidence_kind", "structured"}
    """
    if raw is None:
        return None

    # 形态一：自由文本（旧格式 / 模型偷懒）
    if isinstance(raw, str):
        s = raw.strip()
        if not s or s.lower() in ("无", "none", "null"):
            return None
        return {
            "detail": s,
            "claim_ref": "",
            "severity": "medium",
            "evidence_kind": "interview",
            "structured": False,
        }

    # 形态二：结构化对象（期望格式）
    if isinstance(raw, dict):
        detail = str(raw.get("detail") or raw.get("vulnerability") or "").strip()
        if not detail or detail.lower() in ("无", "none", "null"):
            return None
        sev = str(raw.get("severity") or "medium").strip().lower()
        if sev not in VALID_SEVERITY:
            sev = "medium"
        return {
            "detail": detail,
            "claim_ref": str(raw.get("claim_ref") or "").strip(),
            "severity": sev,
            "evidence_kind": str(raw.get("evidence_kind") or "interview").strip(),
            "structured": True,
        }

    return None


# ============================================================
# 出口归一化适配器
# 把各 Agent 已有的输出结构翻译成统一 Claim —— 不改各 Agent 的代码。
# ============================================================

# 显式自推的信号词 —— 命中即判为「模型推理」，这是唯一会被压到 weak 的来源。
#
# 注意"行业标准"也在此列：模型凭内置知识脑补出来的行业标准 JD，确实是推理产物，
# 不是外部证据，所以它不该被当成强证据。
_INFERENCE_HINT = re.compile(
    r"我觉得|我认为|行业通识|行业标准|一般来说|通常|据我所知|推测|估计|常识|经验判断")
_JD_HINT = re.compile(r"JD|岗位要求|职位描述|招聘", re.I)
_GAP_HINT = re.compile(r"gap|隐形|猎头|Agent\s*A", re.I)
_INTERVIEW_HINT = re.compile(r"对练|面试|漏洞|压测|追问")


def guess_kind(ref):
    """
    从证据描述里推断来源类型。

    Agent D 目前不显式声明 kind，所以只能靠关键词推断 —— 这是"出口归一化"
    方案的已知代价。把它公开导出，是为了让 Agent D 自己也能复用同一套推断，
    避免两处各写一份、日后发散。

    判断顺序按"特异性从高到低"：
      1. 先识别可追溯的外部来源（gap / 对练记录）
      2. 再识别**显式自推**的信号词 -> inference
      3. 再识别 JD
      4. 其余**默认判为 resume**

    为什么默认是 resume 而不是 inference：Agent D 的证据描述绝大多数指向
    候选人自己的材料（"Career-Pilot 规则+模型混合校验模块"这种没有任何
    "简历/项目"字样的描述也会出现）。默认 inference 会把大量合法证据
    误压到 weak —— 这是用真实运行数据（trace TRACE_c731da423a07）发现的。

    安全性由另一条规则兜底：真正自推的内容会被信号词抓住，而"标了强度
    却给不出引用"由 strength_without_ref 拦截。
    """
    if not ref:
        return "none"
    if _GAP_HINT.search(ref):
        return "gap"
    if _INTERVIEW_HINT.search(ref):
        return "interview"
    if _INFERENCE_HINT.search(ref):
        return "inference"
    if _JD_HINT.search(ref):
        return "jd"
    return "resume"


def _kind_from_source_label(src):
    """Agent E 的 source 标签（"简历 | 隐形Gap | JD要求"）-> kind。"""
    s = (src or "").strip()
    if "隐性" in s or "隐形" in s or s.lower().startswith("gap"):
        return "gap"
    if s.startswith("JD") or "JD" in s:
        return "jd"
    if "简历" in s:
        return "resume"
    return "inference"


def claims_from_agent_a(audit):
    """Agent A 的结论：致命弱点 + 隐形 Gap。"""
    claims = []
    if not isinstance(audit, dict):
        return claims

    fatal = (audit.get("fatal_weakness") or "").strip()
    if fatal:
        # 致命弱点是 A 的综合判断，没有可逐字引用的出处
        claims.append(make_claim("Agent_A", fatal, kind="inference"))

    for g in (audit.get("invisible_gaps") or []):
        if not isinstance(g, dict):
            continue
        skill = (g.get("skill") or "").strip()
        reason = (g.get("gap_reason") or "").strip()
        # candidate_current 是 A 对简历现状的引用，有则算 resume 来源
        ref = (g.get("candidate_current") or "").strip()
        kind = "resume" if ref else "inference"
        claims.append(make_claim(
            "Agent_A", "%s：%s" % (skill, reason),
            kind=kind, ref=ref, inferred=not ref,
        ))
    return claims


def claims_from_agent_c(result):
    """
    Agent C 的阅卷结论：总评 + **逐维度 rubric**。

    本轮扩展：C 现在会逐维度打分（见 agent_c_assessor.RUBRIC）。
    每个维度分数都是一条可核对的结论 —— 把它也纳入契约层，
    意味着"这道题为什么给 80 分"在证据链里是可审计的，
    而不是只有一个孤零零的总分。
    """
    claims = []
    if not isinstance(result, dict):
        return claims

    fb = (result.get("feedback") or "").strip()
    if fb:
        ref = "task_id=%s" % result.get("task_id") if result.get("task_id") else ""
        claims.append(make_claim("Agent_C", fb, kind="submission", ref=ref,
                                 strength="medium"))

    for item in (result.get("rubric") or []):
        if not isinstance(item, dict):
            continue
        dim = str(item.get("dimension") or "").strip()
        comment = str(item.get("comment") or "").strip()
        if not dim and not comment:
            continue
        text = "rubric[%s]=%s：%s" % (dim, item.get("score"), comment or "（无理由）")
        # 维度分数是对"用户作答"这一外部证据的判断，来源归为 submission
        ref = "task_id=%s" % result.get("task_id") if result.get("task_id") else ""
        claims.append(make_claim("Agent_C", text, kind="submission", ref=ref,
                                 strength="medium"))
    return claims


def claims_from_agent_b(plan, gap_skills=None):
    """
    Agent B 的学习计划 -> Claim。

    为什么 B 也需要接入契约层
    ------------------------
    此前 B 的输出是纯结构化的计划（哪天学什么），没有任何"依据"概念 ——
    于是"这份计划是不是针对这个人的"只能靠 Agent F 事后去猜。
    接入之后，每条计划结论都带来源标注，可量化核对。

    来源推断规则（B 不显式声明，故用推断）：
      · 内容命中 gap 报告里的技能 -> kind=gap（有外部依据）
      · 只是计划内部的结构安排     -> kind=plan（STRENGTH_CEILING 限死 medium）

    计划类证据天然到不了 strong：它说明的是"我打算怎么学"，
    不是"我会什么"。把上限压在 medium 是刻意的。

    粒度：overall_goal + 每个 phase 一条（而不是每个 task 一条）——
    26 个任务全展开会让审计摘要淹没在噪音里，而阶段目标已经足够定位问题。
    """
    claims = []
    if not isinstance(plan, dict):
        return claims

    gap_skills = {str(s).strip().lower() for s in (gap_skills or []) if str(s).strip()}

    def _kind_of(text):
        if not gap_skills:
            return "plan"
        low = (text or "").lower()
        return "gap" if any(s in low for s in gap_skills) else "plan"

    goal = (plan.get("overall_goal") or "").strip()
    if goal:
        claims.append(make_claim("Agent_B", goal, kind="plan",
                                 ref="计划总体目标", inferred=True))

    for ph in (plan.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        name = (ph.get("phase_name") or "").strip()
        pgoal = (ph.get("phase_goal") or "").strip()
        tasks = ph.get("tasks") or []
        text = "%s：%s（%d 个任务）" % (name, pgoal, len(tasks))
        kind = _kind_of(name + pgoal)
        ref = "计划阶段" if kind == "plan" else "命中 gap 技能"
        claims.append(make_claim("Agent_B", text, kind=kind, ref=ref, inferred=True))

    return claims


def claims_from_agent_d(report):
    """Agent D 的改写建议（每条 item 是一条结论）。"""
    claims = []
    if not isinstance(report, dict):
        return claims

    for it in (report.get("items") or []):
        if not isinstance(it, dict):
            continue
        text = (it.get("rewritten") or it.get("original") or "").strip()
        ref = (it.get("evidence") or "").strip()
        kind = guess_kind(ref)
        c = make_claim(
            "Agent_D", text, kind=kind, ref=ref,
            strength=it.get("evidence_strength"), inferred=True,
        )
        c.blocked = bool(it.get("blocked"))
        claims.append(c)
    return claims


def claims_from_agent_e(result, available_sources=None):
    """
    Agent E 的结论：面试题（每条 attack_target 是一次判断）
    + 评分时挖出的漏洞。

    available_sources 传入本次实际可用的证据来源（如 ["gap"]）。
    若 E 把某题标成"隐形Gap"却没跑过 Agent A，会被记为
    claimed_source_unavailable:gap —— 这正是"来源标注名不副实"的自动检查。
    """
    claims = []
    if not isinstance(result, dict):
        return claims

    for q in (result.get("questions") or []):
        if not isinstance(q, dict):
            continue
        kind = _kind_from_source_label(q.get("source"))
        claims.append(make_claim(
            "Agent_E", (q.get("question") or "").strip(),
            kind=kind, ref=(q.get("attack_target") or "").strip(),
            inferred=True, available_sources=available_sources,
        ))

    vul = (result.get("vulnerability") or "").strip()
    if vul and vul != "无":
        ref = (result.get("question") or "").strip()
        claims.append(make_claim("Agent_E", vul, kind="submission", ref=ref,
                                 strength="medium"))
    return claims


# ============================================================
# 汇总 / 审计
# ============================================================

def summarize(claims):
    """
    统计证据强度分布，返回 dict：
        {"total": n, "by_strength": {...}, "by_kind": {...},
         "blocked": n, "violations": {规则: 次数}}
    这是"证据链可审计"的量化入口。
    """
    by_strength = {s: 0 for s in STRENGTH_ORDER}
    by_kind = {}
    violations = {}
    blocked = 0

    for c in claims:
        by_strength[c.evidence.strength] = by_strength.get(c.evidence.strength, 0) + 1
        by_kind[c.evidence.kind] = by_kind.get(c.evidence.kind, 0) + 1
        if c.blocked:
            blocked += 1
        for v in c.violations:
            rule = v.split(":", 1)[0]
            violations[rule] = violations.get(rule, 0) + 1

    return {
        "total": len(claims),
        "by_strength": by_strength,
        "by_kind": by_kind,
        "blocked": blocked,
        "violations": violations,
    }


def format_summary(claims, title="证据链"):
    """把 summarize() 的结果渲染成可打印文本。"""
    if not claims:
        return "[%s] 无结论" % title

    s = summarize(claims)
    lines = ["[%s] 本次共 %d 条结论" % (title, s["total"])]

    parts = []
    for st in ("strong", "medium", "weak", "none"):
        n = s["by_strength"].get(st, 0)
        if n:
            parts.append("%s %d" % (st, n))
    if parts:
        lines.append("  强度分布：" + " / ".join(parts))

    kinds = " / ".join("%s %d" % (KIND_LABEL.get(k, k), v)
                       for k, v in sorted(s["by_kind"].items(), key=lambda x: -x[1])
                       if k != "none")
    if kinds:
        lines.append("  来源分布：" + kinds)

    if s["blocked"]:
        lines.append("  已拦截：%d 条（无证据，仅建议去补）" % s["blocked"])

    if s["violations"]:
        v = " / ".join("%s %d" % (k, n) for k, n in s["violations"].items())
        lines.append("  契约告警：" + v)
    else:
        lines.append("  契约告警：无")

    return "\n".join(lines)


# ============================================================
# 自检
# ============================================================

def _self_test():
    print("=" * 62)
    print("  contracts 自检")
    print("=" * 62)

    cases = [
        # (说明, kind, ref, strength, 期望强度, 是否期望有告警)
        ("模型自推却宣称 strong（应被压到 weak）", "inference", "我觉得这个岗位很重要", "strong", "weak", True),
        ("简历原句 + strong（合法）", "resume", "累计 5,700+ 行代码", "strong", "strong", False),
        ("声明 strong 但给不出引用", "resume", "", "strong", "none", True),
        ("未声明强度（默认 medium）", "jd", "JD 第 2 条：判断什么该用 AI", None, "medium", False),
        # 未知来源类型 -> kind 退化为 none，强度也只能是 none
        ("未知来源类型", "telepathy", "读心术", "strong", "none", True),
    ]

    ok = True
    for desc, kind, ref, strength, want_s, want_warn in cases:
        ev, viol = normalize_evidence(kind=kind, ref=ref, strength=strength)
        passed = (ev.strength == want_s) and (bool(viol) == want_warn)
        ok = ok and passed
        print("\n  [%s] %s" % ("OK" if passed else "FAIL", desc))
        print("        kind=%s  strength=%s -> %s" % (ev.kind, strength, ev.strength))
        if viol:
            print("        告警：%s" % "、".join(viol))

    # 来源类型推断准确性
    print("\n" + "-" * 62)
    kind_cases = [
        ("Career-Pilot 项目源码", "resume"),
        ("简历原文求职方向", "resume"),
        # 下面这条来自真实运行数据（trace TRACE_c731da423a07）：
        # 它没有任何"简历/项目"字样，早期规则会误判成 inference 并把合法证据压到 weak
        ("Career-Pilot 规则+模型混合校验模块", "resume"),
        ("JD 第 2 条：判断什么该用 AI", "jd"),
        ("Agent A 的隐形 Gap 推理", "gap"),
        ("对练记录中暴露的漏洞", "interview"),
        ("我觉得这个能力很重要", "inference"),
        ("模型内置的行业标准 JD 要求", "inference"),
    ]
    for ref, want in kind_cases:
        got = guess_kind(ref)
        p = (got == want)
        ok = ok and p
        print("  [%s] %-28s -> %s" % ("OK" if p else "FAIL", ref[:26], got))

    # 名不副实的来源标注
    print("\n" + "-" * 62)
    ev, viol = normalize_evidence(kind="gap", ref="异步失败路径",
                                  available_sources=["resume", "jd"])
    passed = any(v.startswith("claimed_source_unavailable") for v in viol)
    ok = ok and passed
    print("  [%s] 标注『隐形Gap』但本次没有 gap 报告 -> 应告警" % ("OK" if passed else "FAIL"))
    print("        告警：%s" % "、".join(viol))

    # 定性升级检测（用上轮真实报告里的两条建议做对照）
    print("\n" + "-" * 62)
    upgrade_cases = [
        ("5,700+ 行代码中含 1,100 行自动化测试代码",
         "简历自述代码构成：测试 1,100 行", True),
        ("基于 pytest 的自动化测试，覆盖 12 个用例",
         "tests/ 目录，pytest 断言 14 条", False),
    ]
    for text, ref, want_warn in upgrade_cases:
        viol = check_qualification_upgrade(text, ref)
        p = (bool(viol) == want_warn)
        ok = ok and p
        print("  [%s] %s" % ("OK" if p else "FAIL", text[:24]))
        print("        证据：%s" % ref)
        print("        告警：%s" % ("、".join(viol) if viol else "无"))

    # 端到端：归一化一份 Agent D 报告
    print("\n" + "-" * 62)
    report = {
        "items": [
            {"original": "累计 5,700+ 行代码", "rewritten": "独立完成多 Agent 系统的设计与取舍",
             "evidence": "Career-Pilot 项目源码", "evidence_strength": "strong", "blocked": False},
            {"original": "定位硬核玩家开黑同步困难痛点", "rewritten": "",
             "evidence": "", "evidence_strength": "none", "blocked": True},
        ]
    }
    claims = claims_from_agent_d(report)
    print("  Agent D 报告归一化：")
    for c in claims:
        print("    - [%s] %s | %s" % (c.evidence.strength, c.evidence.label, c.text[:28]))
    print()
    print(format_summary(claims, "Agent D"))

    print("\n" + "=" * 62)
    print("  自检结果：%s" % ("全部通过" if ok else "存在失败项"))
    print("=" * 62)
    return ok


if __name__ == "__main__":
    _self_test()
