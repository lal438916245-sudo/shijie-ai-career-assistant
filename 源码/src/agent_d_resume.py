"""
Agent D：智能简历改写助手

它和"AI 润色工具"的分界线
--------------------------
市面上大多数改简历工具只看简历文本本身，于是只能做两件事：
**润色措辞 + 堆砌关键词**。结果很典型：简历看起来漂亮，面试第一轮就被打穿。

Agent D 的工作法是「三差集」：

    JD 要求  ×  简历声称  ×  真实证据

    ① JD 要 + 有证据 + 简历没写   -> 【必须补】价值最高
    ② JD 要 + 无证据             -> 【不许写】-> 转成学习任务
    ③ 简历写了 + JD 不要          -> 【降权或删】
    ④ 简历写了 + 有证据 + JD 也要  -> 【保留】并改写成 JD 的语言

其中第 ② 条是整个设计的灵魂：**它把"简历缺陷"直接转成"学习任务"**，
让 C→B→学习→证据→D 形成闭环。

输出不是一份新简历，而是一张**可解释的建议表**
-----------------------------------------------
直接给全文是错误设计 —— 用户会盲目接受，然后在面试里被打脸。
必须让用户看到：改了哪里、为什么改、风险在哪。

因此本模块有两道防线：
  1. prompt 里要求每条建议标注证据来源与强度
  2. **代码级强制拦截**（enforce_evidence_rule）：无证据的条目一律清空改写内容。
     模型可以"想编"，但编出来的东西进不了最终结果。
"""

from llm_client import AgentBase
from json_utils import parse_llm_json


from llm_client import AgentBase
from json_utils import parse_llm_json
from contracts import (normalize_evidence, check_qualification_upgrade,
                       guess_kind)


def enforce_evidence_rule(report):
    """
    核心原则的代码级强制执行。

    规则：`evidence` 为空、或归一化后强度为 none 的条目，
    **不允许**给出 `rewritten` —— 只保留"建议去补"，并把该条转成待补事项。

    强度归一化不再由本模块自己维护，而是交给统一的**证据契约层**
    （`contracts.normalize_evidence`）。这样 Agent D 自动获得两条保护：
      · 证据等级不得抬高（模型自推最高只能到 weak）
      · 定性升级检测（把"数量"重新定性为"性质"会被记告警）

    这道防线存在的原因：prompt 只能"请求"模型守规矩，代码才能"保证"它守规矩。

    返回 (report, violations, downgrades)
      violations —— 模型试图在无证据情况下改写、被清空的条数
      downgrades —— 强度被契约层下调的条数（试图抬高证据等级）
    """
    violations = 0
    downgrades = 0
    missing = report.setdefault("missing_evidence", [])

    for item in report.get("items", []):
        ref = str(item.get("evidence") or "").strip()
        kind = guess_kind(ref)

        ev, warns = normalize_evidence(
            kind=kind, ref=ref, strength=item.get("evidence_strength"),
            inferred=True,
        )
        # 定性升级检测针对的是"改写后的措辞"，不是原文
        text_for_check = str(item.get("rewritten") or item.get("original") or "")
        warns.extend(check_qualification_upgrade(text_for_check, ref))

        if any(w.startswith("strength_capped") for w in warns):
            downgrades += 1

        # 把归一化结果写回，让下游（报告渲染 / 审计）能看到确定的来源与强度
        item["evidence_kind"] = ev.kind
        item["evidence_strength"] = ev.strength
        if warns:
            item["contract_warnings"] = warns

        # 无证据 / 强度为 none -> 拦截改写内容
        if ev.strength == "none":
            if item.get("rewritten"):
                violations += 1
            item["rewritten"] = ""
            item["blocked"] = True

            claim = (item.get("original") or "").strip()
            if claim and claim not in missing:
                missing.append(claim)
        else:
            item["blocked"] = False

    return report, violations, downgrades


# 漏洞 detail 的展示上限。
# Agent E 的 prompt 已要求 ≤120 字，但**历史数据可能更长**，而且这是一条
# 会影响 token 成本的关键路径：实测 2 条 200 字的洞就让 D 的推理量涨到 82%，
# 漏洞再多几条就可能撞 max_tokens 上限。所以在渲染端也兜一层。
VULN_DETAIL_LIMIT = 160

_SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


def render_vulnerability_block(vulnerabilities):
    """
    把 Agent E 的漏洞列表渲染成 prompt 片段（证据 B）。

    抽成模块级函数有两个原因：
      1. 可单独测试 —— 不必真的调用模型就能验证渲染对不对
      2. `run_resume.py --dry-run` 能预览它，零成本确认漏洞是否真的接进来了

    结构化漏洞会带上 [严重度] 与"攻击的简历原句"，让模型能把
    "这条改写建议"和"那个具体的洞"精确对应，而不是笼统地"参考一下"。

    展示顺序按严重度降序 —— 万一数量多到需要取舍，先看到的必须是 high。
    """
    if not vulnerabilities:
        return "  （未接入面试压测结果：没有可用的漏洞记录）"

    def _sev(v):
        return _SEV_ORDER.get((v or {}).get("severity") if isinstance(v, dict)
                              else "medium", 1)

    lines = []
    for v in sorted(vulnerabilities, key=_sev):
        if isinstance(v, dict):
            sev = v.get("severity", "medium")
            ref = v.get("claim_ref") or ""
            detail = v.get("detail", "") or ""
            if len(detail) > VULN_DETAIL_LIMIT:
                detail = detail[:VULN_DETAIL_LIMIT] + "…"
            line = f"  - [{sev}] {detail}"
            if ref:
                line += f"\n      攻击的简历原句：{ref}"
        else:
            line = f"  - {v}"
        lines.append(line)
    return "\n".join(lines)


class ResumeAgent(AgentBase):

    def __init__(self, db=None, model_name=None, trace_id=None):
        sys_prompt = """
        【Role】你是顶级简历改写顾问（Agent D）。
        【核心原则】证据驱动 —— 简历上的每一条能力声明都必须能指向一个证据来源。
          没有证据的技能，**不允许写出来**。宁可少写，不可编造。
          你的价值不是让候选人显得更强，而是让他在面试里**站得住**。
        【Tone】直接、具体、不客套。发现问题就说，不要为了照顾情绪而软化。
        【Constraint】必须严格遵循预设的 JSON 格式输出，禁止在 JSON 外附带任何解释性文字！
        """
        super().__init__(
            agent_name="改简历 Agent_D",
            system_prompt=sys_prompt,
            db=db,
            model_name=model_name,
            trace_id=trace_id,
        )

    # ---------------------------------------------------------
    # 生成改写建议
    # ---------------------------------------------------------
    def rewrite(self, resume_text, jd_text=None, job_title="",
                gap_audit=None, vulnerabilities=None):
        """
        产出「三差集」改写建议表。

        参数
        ----
        resume_text     : 简历原文
        jd_text         : 目标岗位 JD 原文
        job_title       : 岗位名（用于定位）
        gap_audit       : Agent A 的 deep_audit 结果（含 invisible_gaps）
        vulnerabilities : Agent E 挖出的漏洞列表（对练产出）
        """
        print(f"\n[Agent D] 正在对「{job_title}」做三差集分析...")

        # ---- 组装证据块 ----
        jd_block = (f"【目标岗位 JD 原文】\n{jd_text}" if jd_text
                    else "【目标岗位 JD】未提供。请调用你大脑中该岗位的行业标准要求作为标尺。")

        if gap_audit:
            gaps = gap_audit.get("invisible_gaps") or []
            gap_block = (f"  致命弱点：{gap_audit.get('fatal_weakness', '')}\n"
                         + "\n".join(f"  - {g.get('skill','')}：{g.get('gap_reason','')}"
                                     for g in gaps))
        else:
            gap_block = "  （无 gap 报告，请完全依赖简历与 JD 语义推理）"

        vuln_block = render_vulnerability_block(vulnerabilities)

        user_prompt = f"""
        【Context】你要帮一位候选人把他现有的简历，改写成"针对这个岗位、且每句话都站得住"的版本。

        【目标岗位】{job_title}

        {jd_block}

        【候选人简历原文】
        {resume_text}

        【证据 A：Agent A 推理出的隐形 Gap（他表面具备但深度不够的地方）】
        {gap_block}

        【证据 B：Agent E 面试压测挖出的漏洞（他说不清楚的地方）】
        {vuln_block}

        【证据 B 的用法】每条漏洞带 [严重度] 和它"攻击的简历原句"。
        优先处理 high 级；当某条漏洞攻击的原句正是你要改写的那一条时，
        **必须正面回应这个洞** —— 这是"改了措辞"和"真的堵上了"的分界。

        【工作法：三差集】请先把 JD 要求、简历声称、真实证据做差集，再分类给出建议：
          ① JD 要 + 有证据 + 简历没写   -> action = "add"，价值最高
          ② JD 要 + 无证据             -> action = "keep"，evidence_strength = "none"，
                                         **rewritten 必须留空**，并在 missing_evidence 里列出
          ③ 简历写了 + JD 不要          -> action = "delete" 或 "deprioritize"
          ④ 简历写了 + 有证据 + JD 也要  -> action = "rewrite"，改写成 JD 听得懂的语言

        【强制要求】
          · 每一条 item 的 `evidence` 必须写清证据来源。**没有证据的条目，rewritten 一律留空**
          · 不允许编造任何经历、数据、项目。宁可建议"去补"，也不要写出漂亮但假的句子
          · `risk` 要写"面试官看到这句会追问什么" —— 这是它和普通润色工具的差别

        【输出纪律（很重要，违反会导致结果不可用）】
          · **items 最多 8 条**，按重要性排序。宁可少而准，不要穷举式罗列
          · **JSON 不要缩进、不要换行美化**，写成紧凑的一行结构以节省输出长度
          · 每个字符串字段控制在一句话以内：`aligned_requirement` ≤ 20 字，
            `risk` ≤ 30 字，`evidence` ≤ 40 字，`rewritten` ≤ 80 字
          · 推理要克制，直接把结论写出来，不要反复推演

        【Output Format】严格输出以下 JSON：
        {{
            "target_job": "{job_title}",
            "summary": "整体诊断：这份简历针对该岗位最核心的问题是什么（不超过 150 字，直接说）",
            "items": [
                {{
                    "section": "项目经历 / 技能清单 / 自我评价 / 教育背景",
                    "original": "简历原文（引用原句；若是建议新增则填 '（新增）'）",
                    "rewritten": "建议改法。若 evidence_strength 为 none，此字段必须为空字符串",
                    "aligned_requirement": "对齐 JD 的哪一条要求（≤20 字）",
                    "evidence": "证据来源的具体描述（≤40 字）；无证据则留空",
                    "evidence_strength": "strong / medium / weak / none",
                    "risk": "面试官可能追问什么（≤30 字）",
                    "action": "keep / rewrite / add / delete / deprioritize"
                }}
            ],
            "must_add": ["有证据但简历漏写的（对应差集①），最多 3 条"],
            "missing_evidence": ["简历写了或想写但没有证据的（对应差集②），最多 5 条"],
            "must_drop": ["与目标岗位无关、稀释简历的（对应差集③），最多 3 条"]
        }}
        """
        raw = self.think(user_prompt, max_tokens=8000)

        # 先尝试完整解析；若被截断则抢救已产出的部分（推理模型很容易吃光额度）
        report, degraded = parse_llm_json(raw)
        if degraded:
            print("[Agent D] ⚠ 输出被截断，已抢救出**部分结果** —— "
                  "条目可能不全，建议重跑或调小分析范围")

        # ---- 代码级防线：拦截无证据的改写 ----
        report, violations, downgrades = enforce_evidence_rule(report)

        # 几个数含义不同，别混为一谈：
        #   violations —— 模型"想改写"但拿不出证据，被代码清空（说明 prompt 没管住）
        #   blocked    —— 因无证据而不能改写的条目总数（模型守规矩时也会有）
        #   downgrades —— 证据强度被契约层下调（模型试图抬高证据等级）
        blocked = sum(1 for it in (report.get("items") or []) if it.get("blocked"))

        if violations:
            print(f"[Agent D] ⚠ 代码级拦截 {violations} 条：模型试图在无证据的情况下改写，"
                  f"已清空其改写内容")
        elif blocked:
            print(f"[Agent D] 证据校验通过：模型没有越界改写；"
                  f"另有 {blocked} 条因无证据，仅标注『建议去补』")
        else:
            print("[Agent D] 证据校验通过：所有条目都有证据支撑")

        if downgrades:
            print(f"[Agent D] ⚠ 证据契约下调了 {downgrades} 条建议的强度"
                  f"（模型标注的强度高于该证据来源允许的上限）")

        # 定性升级：结论里的定性词在证据里找不到支撑（把"数量"说成"性质"）
        upgraded = sorted({
            w.split(":", 1)[1]
            for it in (report.get("items") or [])
            for w in (it.get("contract_warnings") or [])
            if w.startswith("qualification_upgrade")
        })
        if upgraded:
            print(f"[Agent D] ⚠ 定性升级告警：{'、'.join(upgraded)} —— "
                  f"结论中出现该定性词，但证据描述里找不到支撑，请人工确认后再采用")

        report["_degraded"] = degraded
        report["_violations"] = violations
        report["_blocked"] = blocked
        report["_downgrades"] = downgrades
        return report
