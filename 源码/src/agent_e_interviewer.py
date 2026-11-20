"""
Agent E：毒舌面试官（Persona 压力测试器）

与前面几个 Agent 的区别
------------------------
A / B / C 都是"帮助你"的，E 是"打击你"的。
但它的价值**不在于说话难听，而在于攻击面选得准**。

题库三个来源（缺一不可，否则就只是个随机刁难的玩具）
--------------------------------------------------
  1. 简历每条 claim            -> 追问细节
  2. gap 报告的 invisible_gaps -> 直接问你知道他不会的（最狠）
  3. JD 每条硬要求             -> 逐条压测

另外两个关键机制
----------------
  · 人格卡：不是决定"语气凶不凶"，而是决定"攻击哪一面"。
    同一份简历在不同人格下会暴露不同的洞。

  · 触发词黑名单：简历里出现「熟悉 / 了解 / 掌握 / 精通」却没有量化或
    机制说明 -> 自动深挖。
    90% 的简历被打穿，都发生在这几个词后面。

输出里有一个关键字段 `vulnerability`（挖出的漏洞），它是回传给 Agent D
（简历改写）的燃料 —— D↔E 对抗闭环就靠它。

它现在是**结构化对象**（detail / claim_ref / severity / evidence_kind），
而不是一句自由文本。原因：自由文本无法让 D 知道这个洞攻击的是简历里哪一句、
有多严重，于是闭环只能靠模型自己猜关联。结构化之后：
    E 挖洞（带 claim_ref） → D 精确对齐改写 → E 复测逐条比对是否堵上
"""

from llm_client import AgentBase
from json_utils import extract_json_from_text
from resume_scan import scan_vague_claims
from contracts import normalize_vulnerability, VALID_SEVERITY   # noqa: F401


# ============================================================
# 人格卡：决定攻击面，而不是决定语气
# ============================================================

PERSONAS = {
    "tencent_backend": {
        "name": "腾讯 T3.2 后端老兵",
        "attack_surface": "实现细节、底层机制、性能瓶颈在哪一层",
        "style": "最烦'熟悉'两个字，逐条追问实现细节，不接受名词堆砌",
    },
    "byte_director": {
        "name": "字节三面 技术总监",
        "attack_surface": "数据规模、指标口径、'这个提升是怎么测出来的'",
        "style": "冷静、只认数据。任何没有口径和量级的结论都会被质疑",
    },
    "hrbp": {
        "name": "HRBP / HR 面",
        "attack_surface": "稳定性、离职原因、薪资预期、职业规划的合理性",
        "style": "客气但每一步都在试探你的动机是否自洽",
    },
    "cross_team": {
        "name": "交叉面 团队负责人",
        "attack_surface": "协作、推动力、有没有带过人、跨团队拿结果的证据",
        "style": "关注'你个人做了什么'，会拆穿所有用'我们'掩盖的表述",
    },
}

DEFAULT_PERSONA = "tencent_backend"


# ============================================================
# 漏洞结构化
# ============================================================
# 为什么必须结构化：此前 vulnerability 是一句自由文本，D 拿到后只能
# 原样贴进 prompt。它无法知道这个洞攻击的是简历里哪一句、有多严重，
# 于是"E 挖洞 → D 改简历"这条对抗闭环只能靠模型自己猜关联。
#
# 结构化之后，每条漏洞都带 claim_ref（攻击的简历原句）和 severity，
# D 就能做精确对齐，复测也能逐条比对。
#
# 归一化实现已下沉到契约层（contracts.normalize_vulnerability）——
# evidence.py 与 Agent D 都要用它，而 contracts 是唯一零依赖的模块。
# 本模块只保留 Agent E 特有的"打包成交接 payload"这一步。


def vulnerability_to_dict(vulns, job=None, persona=None, **extra):
    """把漏洞列表打包成可落库 / 可交接的 payload。"""
    items = [v for v in (vulns or []) if v]
    payload = {
        "job": job,
        "persona": persona,
        "count": len(items),
        "by_severity": {
            s: sum(1 for v in items if v.get("severity") == s)
            for s in VALID_SEVERITY
        },
        "vulnerabilities": items,
    }
    payload.update(extra)
    return payload


# ============================================================
# 触发词黑名单：纯规则扫描
# ============================================================
# 实现已抽到独立模块 resume_scan.py（零依赖、零 token 成本、结果可复现）。
# 本模块只负责"怎么问"，不负责"该不该问"。
# 单独测试：python resume_scan.py my_profile/resume.md


# ============================================================
# Agent E 本体
# ============================================================

class InterviewerAgent(AgentBase):

    def __init__(self, db=None, model_name=None,
                 trace_id=None, persona=DEFAULT_PERSONA):

        if persona not in PERSONAS:
            raise KeyError(
                f"未知人格卡「{persona}」。可选：{'、'.join(PERSONAS)}"
            )
        self.persona_key = persona
        self.persona = PERSONAS[persona]

        sys_prompt = f"""
        【Role】你是面试官，人格设定如下：
          身份：{self.persona['name']}
          攻击面：{self.persona['attack_surface']}
          风格：{self.persona['style']}

        【Tone】犀利、专业、不留情面。但不使用人身攻击，只针对技术与事实。
        【Constraint】必须严格遵循预设的 JSON 格式输出，禁止在 JSON 外附带任何解释性文字！
        """
        super().__init__(
            agent_name=f"面试官 Agent_E ({self.persona['name']})",
            system_prompt=sys_prompt,
            db=db,
            model_name=model_name,
            trace_id=trace_id,
        )

    # ---------------------------------------------------------
    # 出题：三来源题库
    # ---------------------------------------------------------
    def generate_questions(self, resume_text, jd_text=None,
                           gap_audit=None, n=6):
        """
        生成面试问题清单。

        参数
        ----
        resume_text : 简历原文
        jd_text     : 目标岗位 JD 原文（可选，没有则用行业标准要求）
        gap_audit   : Agent A 的 deep_audit 结果 dict（可选，含 invisible_gaps）
        n           : 生成几个问题
        """
        print(f"\n[Agent E] 面试官【{self.persona['name']}】已就位，准备压测...")

        # 来源一：触发词黑名单（规则扫描）
        vague = scan_vague_claims(resume_text)
        if vague:
            vague_block = "\n".join(
                f"  - {v['claim']}   （问题：{v['reason']}）" for v in vague
            )
            print(f"[Agent E] 规则扫描命中 {len(vague)} 条可疑声明，将自动深挖")
        else:
            vague_block = "  （未扫描到明显空泛的声明）"

        # 来源二：Agent A 的隐形 Gap
        if gap_audit:
            gaps = gap_audit.get("invisible_gaps") or []
            fatal = gap_audit.get("fatal_weakness") or ""
            gap_block = f"  致命弱点：{fatal}\n" + "\n".join(
                f"  - {g.get('skill','')}：{g.get('gap_reason','')}" for g in gaps
            )
        else:
            gap_block = "  （无 gap 报告，请完全依赖简历与 JD 语义推理）"

        # 来源三：JD
        jd_block = (
            f"【目标岗位 JD 原文】\n{jd_text}"
            if jd_text else
            "【目标岗位 JD】未提供。请调用你大脑中一线大厂该岗位的行业标准要求。"
        )

        user_prompt = f"""
        【Context】你正在面试一位候选人。目标岗位与候选人材料如下。

        {jd_block}

        【候选人简历原文】
        {resume_text}

        【规则扫描出的可疑声明（必须至少覆盖其中 2 条）】
        {vague_block}

        【猎头 Agent A 推理出的隐形 Gap（可以直接问，这是你的优势）】
        {gap_block}

        【Objective】生成 {n} 个面试问题。要求：
          1. **必须覆盖三个来源**：简历细节 / 隐形 Gap / JD 硬要求
          2. 每个问题都要能落到具体细节上，禁止"请介绍下你自己"这类废话
          3. 优先攻击"简历上写了但说不清"的地方
          4. 符合你的人格攻击面：{self.persona['attack_surface']}

        【Output Format】严格输出以下 JSON：
        {{
            "persona": "{self.persona['name']}",
            "overall_verdict": "一句话点评这份简历在这个岗位上最致命的短板",
            "questions": [
                {{
                    "seq": 1,
                    "source": "简历 | 隐形Gap | JD要求",
                    "attack_target": "具体攻击的那一条（引用原文或其要点）",
                    "question": "面试问题原文",
                    "expected_points": "期望听到的答案要点（用于后续评分）",
                    "why_ask": "作为面试官，问这个是为了验证什么"
                }}
            ]
        }}
        """
        raw = self.think(user_prompt, max_tokens=6000)
        return extract_json_from_text(raw)

    # ---------------------------------------------------------
    # 对单个回答评分 + 挖漏洞
    # ---------------------------------------------------------
    def evaluate_answer(self, question, expected_points, answer):
        """
        评估候选人的回答。返回 dict，其中 `vulnerability` 是回传给 Agent D 的燃料。
        """
        user_prompt = f"""
        【Context】你是面试官。候选人刚刚回答了你的问题。

        【你的问题】
        {question}

        【你期望听到的要点】
        {expected_points}

        【候选人的回答】
        {answer}

        【Objective】严格评估这个回答。宁严勿宽 —— 候选人需要的是真实的反馈，
        不是安慰。特别留意：有没有用名词堆砌掩盖理解不足、有没有答非所问、
        有没有把"团队的成果"说成"我做的"。

        【Output Format】严格输出以下 JSON：
        {{
            "verdict": "pass 或 vague 或 fail",
            "score": 0到100的整数,
            "what_worked": "答对了什么（没有则填'无'）",
            "vulnerability": {{
                "detail": "这个回答暴露出的具体漏洞（**≤120 字**，只写最关键的 1~3 个缺口，不要罗列所有细节）",
                "claim_ref": "被攻击的简历原文原句；若问的不是简历上写的内容，填 '（简历未提及）'",
                "severity": "high 或 medium 或 low —— 这个洞有多致命",
                "evidence_kind": "resume 或 jd 或 gap 或 interview 或 inference"
            }},
            "follow_up": "如果继续追问，你下一秒会问什么"
        }}

        没有挖出漏洞时，vulnerability 直接填 null。

        【关于 detail 的纪律（很重要）】
          · 只写「缺什么」，**不要写「应该怎么改」** —— 怎么改是 Agent D 的职责
          · 精炼 > 完整。你写得越长，下游 Agent D 的推理负担越重（实测每条 200 字
            会把它的推理量推高 3 倍）。把细节留在你的 what_worked / follow_up 里。
        """
        raw = self.think(user_prompt, max_tokens=4000)
        result = extract_json_from_text(raw)

        # 宽进严出：模型偶尔退回字符串格式，统一归一化后再交给调用方，
        # 否则下游（Agent D / 复测 / 落库）一处格式不符就整条链断掉。
        result["vulnerability"] = normalize_vulnerability(result.get("vulnerability"))
        return result

    # ---------------------------------------------------------
    # 复测：验证漏洞是否真的被修复
    # ---------------------------------------------------------
    def retest(self, vulnerabilities, revised_resume, baseline_resume=None,
               jd_text=None, job_title=""):
        """
        对修改后的简历复测，逐个判断原有漏洞是否已被修复。

        参数
        ----
        vulnerabilities : 历史漏洞列表（结构化）
        revised_resume  : 当前（改后）的简历
        baseline_resume : **对练时的简历快照 —— 这是正确性的前提**

        为什么 baseline 不是可选项
        --------------------------
        没有它，模型只能看到"当前简历里有没有能回应漏洞的内容"，
        于是会把**原本就存在的内容当成新增**，误判成"已修复"。

        这个问题在实测中真实发生过：简历一个字都没改，却被判「部分修复」，
        理由是"新增了 trace_id 全链路审计" —— 而那句话两版简历里都有。

        所以基线不是锦上添花，它是让复测结果可信的前提。

        判定标准从严：**只换了措辞而没有新增事实的，一律判 unresolved。**
        """
        vulns = [v for v in (vulnerabilities or []) if v]
        if not vulns:
            raise ValueError("没有可复测的漏洞，请先跑一次有作答的对练")

        print(f"\n[Agent E] 开始复测 {len(vulns)} 条历史漏洞...")

        vuln_lines = []
        for i, v in enumerate(vulns, 1):
            ref = v.get("claim_ref") or "（未标注）"
            vuln_lines.append(
                f"  {i}. [{v.get('severity', 'medium')}] {v.get('detail', '')}\n"
                f"     攻击的简历原句：{ref}"
            )
        vuln_block = "\n".join(vuln_lines)

        if baseline_resume:
            baseline_block = (
                "【修改前的简历（对练时的版本 —— 这是对比基线）】\n"
                f"{baseline_resume}")
        else:
            baseline_block = (
                "【修改前的简历】未提供。\n"
                "  这种情况下请格外从严：凡是无法确认是新增的内容，"
                "一律按「原本就有」处理。")

        jd_block = (f"【目标岗位 JD 原文】\n{jd_text}" if jd_text
                    else "【目标岗位 JD】未提供。")

        user_prompt = f"""
        【Context】你之前面试过这位候选人，并在他简历里挖出了若干漏洞。
        他据此修改了简历。现在你要复测：这些洞补上了没有。

        【目标岗位】{job_title}

        {jd_block}

        【你之前挖出的漏洞】
        {vuln_block}

        {baseline_block}

        【修改后的简历（现在）】
        {revised_resume}

        【Objective】逐个判断每个漏洞是否已被修复，标准从严：
          · resolved   —— 修改后的简历中出现了直接回应这个问题的新内容（具体证据 / 数字 / 机制）
          · partial    —— 有改善但仍不完整（只补了一部分，或补了但没说清）
          · unresolved —— 没有变化，**或只是换了措辞而没有新增任何事实**

        【最重要的判定纪律】
        只对比「修改前」与「修改后」两份简历的差异。
        **修改前就已经存在的内容，一律不算新增** ——
        不得把原本就有的表述当作"已补充"或"已修复的迹象"。
        拿不准某句话是不是新增时，按"原本就有"处理（从严）。
        另注意：把「参与」改成「主导」、把「熟悉 X」改成「精通 X」这类
        纯措辞调整，一律判 unresolved —— 那是粉饰，不是修复。

        【Output Format】严格输出以下 JSON（紧凑、不要缩进美化）：
        {{
            "summary": "整体判断（一句话，直接说结论）",
            "results": [
                {{"index": 1,
                  "status": "resolved 或 partial 或 unresolved",
                  "evidence": "两份简历之间的**实际差异**，引用原句；没有差异则填 '（未见变化）'",
                  "reason": "判定理由（≤40 字）"}}
            ],
            "fixed_count": 已修复的条数,
            "remaining": ["仍未解决的漏洞，用于下一轮迭代"]
        }}
        """
        raw = self.think(user_prompt, max_tokens=6000)
        result = extract_json_from_text(raw)

        # 把原漏洞的 claim_ref / severity 合并回去，形成"修复前后对照"
        results = result.get("results") or []
        for r in results:
            try:
                idx = int(r.get("index", 0)) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(vulns):
                r["claim_ref"] = vulns[idx].get("claim_ref", "")
                r["severity"] = vulns[idx].get("severity", "medium")
                r["detail"] = vulns[idx].get("detail", "")
        result["results"] = results

        # 用实际判定结果校正 fixed_count（不信任模型自己数数）
        result["fixed_count"] = sum(
            1 for r in results if r.get("status") == "resolved")
        result["total"] = len(vulns)
        return result
