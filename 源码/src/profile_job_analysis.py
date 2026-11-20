"""
真实岗位分析业务服务（Real-profile job analysis）

解决什么问题
------------
`run_hunter.py`（手贴真实 JD → Agent A 打分 → 落库）与 `pipeline_full.py`
（全流程）本应有**同一套**真实岗位分析实现。在抽取之前它是脚本内的私有函数，
于是 pipeline_full 只能退回到 `job_matching.run_job_matching()` 那条读
`data/jobs_mock.xlsx` 的模拟路径 —— 用户明明传了真实简历和真实 JD，
首次岗位分析却可能基于模拟岗位和 `DEFAULT_MUST` 默认技能。

这个模块就是那条"被复制了第二份"之前被抽出来的**唯一实现**：
不含 argparse、不在 import 时执行任何任务、不写文件、不建连接。

职责边界
--------
· 输入：简历原文 + JD 原文（都已由调用方从 profile 读好）
· 处理：调用 Agent A 深度剖析 → 构造 gap 表 → 落库 → 落盘 → 写交接记录
· 输出：job / score / trace_id / report_id / audit

**不负责**读 profile、不负责选岗位、不负责决定交接给谁 ——
这些属于调用方的策略，用参数传进来（`handoff_to` 就是为此而生）。

交接目标（handoff_to）
----------------------
同一次分析在不同入口下要接给不同下游：
  · `run_hunter.py`     → `Agent_E`（猎头分析后接面试题库，保持原行为）
  · `pipeline_full.py`  → `Agent_B`（全流程里岗位分析后接学习计划）

把它做成显式参数，而不是让两个调用方各写一遍 append_message，
是为了保证"**同一次调用只产生一条交接记录**"这条不变量。

零依赖
------
本模块只依赖 pandas / profile_loader / json_utils / 调用方传入的 hunter。
不导入 openai、chromadb、python-docx，因此可在离线下被完整单测。
"""

import os
import uuid

import pandas as pd

import paths
import profile_loader as pl

# 直接使用公共 JSON 解析函数 —— 不通过 Agent 模块间接导入。
# （`agent_a_hunter` 里那个同名符号只是为老代码保留的向后兼容别名。）
from json_utils import extract_json_from_text

# 输入指纹：给"实际传给 Agent 的文本"算内容指纹，
# 让 audit_json / agent_messages 能回答"当时用的是哪一版简历"。
import input_provenance


DEFAULT_RESUME = "resume.md"
REPORT_DIR = "reports"          # 相对 profile 目录


# ============================================================
# 小工具
# ============================================================

def guess_company(job_name):
    """从岗位文件名里猜公司名，文件名约定为「公司-岗位」。"""
    for sep in ("-", "－", "—", "_"):
        if sep in job_name:
            return job_name.split(sep, 1)[0].strip()
    return ""


def build_gap_df(audit):
    """
    从 Agent A 的输出构造 gap DataFrame。

    优先用模型直接给的 gap_table；没有就从 invisible_gaps 兜底翻译。
    `save_gap_report` 要求这里必须是 DataFrame。
    """
    rows = audit.get("gap_table") or []
    if not rows:
        rows = [
            {
                "技能": g.get("skill", ""),
                "状态": "未掌握 (Gap)",
                "优先级": "P1 - 高优补充",
            }
            for g in (audit.get("invisible_gaps") or [])
        ]
    if not rows:
        rows = [{"技能": "（模型未给出结构化 gap）", "状态": "-", "优先级": "-"}]

    df = pd.DataFrame(rows)
    for col in ("技能", "状态", "优先级"):
        if col not in df.columns:
            df[col] = ""
    return df


def render_report(job_name, company, trace_id, report_id, audit):
    """把一次分析渲染成可读的 Markdown。"""
    score = audit.get("match_score")
    lines = [
        f"# {job_name}",
        "",
        f"- 公司：{company or '（未识别）'}",
        f"- trace_id：`{trace_id}`",
        f"- report_id：`{report_id}`",
        f"- **综合匹配度：{score} / 100**",
        "",
        f"> {audit.get('score_reason', '')}",
        "",
        "## 分维度打分",
        "",
        "| 维度 | 分数 | 依据 |",
        "|---|---|---|",
    ]
    labels = {"hard_skills": "技术栈吻合", "project_depth": "项目深度", "domain_fit": "场景匹配"}
    for key, label in labels.items():
        item = (audit.get("score_breakdown") or {}).get(key) or {}
        lines.append(f"| {label} | {item.get('score', '-')} | {item.get('reason', '-')} |")

    lines += [
        "",
        "## 致命弱点",
        "",
        f"{audit.get('fatal_weakness', '（无）')}",
        "",
        "## 隐形 Gap",
        "",
    ]
    for i, g in enumerate(audit.get("invisible_gaps") or [], 1):
        lines += [
            f"### {i}. {g.get('skill', '')}",
            "",
            f"- **岗位真实要求**：{g.get('industry_requirement', '')}",
            f"- **我的现状**：{g.get('candidate_current', '')}",
            f"- **差在哪里**：{g.get('gap_reason', '')}",
            "",
        ]

    advice = audit.get("actionable_advice") or []
    if advice:
        lines += ["## 行动建议", ""]
        lines += [f"{i}. {a}" for i, a in enumerate(advice, 1)]
        lines.append("")

    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================

def analyze_one(db, hunter, job_name, jd_text, resume_text, dry_run=False,
                trace_id=None, profile=None, handoff_to="Agent_E",
                resume_name="resume.md"):
    """
    分析单个岗位，落库并落盘。返回结果 dict（dry_run 时返回 None）。

    参数
    ----
    db          : DBManager
    hunter      : 任何有 `deep_audit(target_job_title, resume_text, jd_text)` 的对象
    job_name    : 岗位名（同时作为 report 文件名、target_job_title 与 JD 的逻辑名）
    jd_text     : JD 原文（原样传给 Agent A）
    resume_text : 简历原文（原样传给 Agent A）
    trace_id    : 复用已有 trace；为空则新建
    profile     : **报告落盘根目录**。必须由调用方传入，不能用模块级
                  `pl.PROFILE_DIR` —— 否则 --demo / 自定义 profile 会把报告
                  写进用户的真实 my_profile/。
    handoff_to  : 交接目标 Agent 名，默认 "Agent_E"（run_hunter 的老行为）；
                  pipeline_full 传 "Agent_B"。
    resume_name : 简历**逻辑名**（如 resume_v2.md），只用于输入指纹。
                  默认 "resume.md" 以保持老调用方式兼容。
                  ⚠ 调用方务必传**真实**用到的文件名 —— 否则指纹会把
                  resume_v2.md 的内容记成 resume.md（版本对不上）。

    关于输入指纹
    ------------
    本函数为每次分析建立**一个** input bundle，并把它写进三处：
      · 返回值 `result["input_bundle"]`
      · `job_gap_reports.audit_json` 的保留字段 `_input_bundle`
      · `agent_messages.payload_json` 的 `input_bundle_id` / `input_sources`
    三处共用同一个对象，**不存在重新计算**，所以结构不可能不一致。
    """
    company = guess_company(job_name)

    # 输入指纹必须在**真正调用 Agent 之前**算好，
    # 且哈希对象就是下面要传下去的这两份文本本身 ——
    # 不是"再去磁盘读一遍"，避免"读到的"和"送进去的"不是同一份。
    bundle = input_provenance.build_input_bundle(
        resume_text=resume_text, jd_text=jd_text,
        resume_name=resume_name, job_name=job_name)

    if dry_run:
        print(f"  [dry-run] {job_name}")
        print(f"            简历 {len(resume_text)} 字 / JD {len(jd_text)} 字 / 公司推断={company or '未识别'}")
        print(f"            输入指纹 {input_provenance.summarize(bundle)}")
        return None

    # 复用外部传入的 trace（让链路串成同一条），否则新建
    trace_id = trace_id or f"TRACE_{uuid.uuid4().hex[:12]}"
    print(f"  [分析中] {job_name}  (trace={trace_id})")
    print(f"            输入指纹 {input_provenance.summarize(bundle)}")

    # 关键：把 trace 传给 Agent，否则它的审计记录会挂在随机 UUID 下、追溯不到本次分析
    hunter.trace_id = trace_id

    raw = hunter.deep_audit(
        target_job_title=job_name,
        resume_text=resume_text,
        jd_text=jd_text,
    )
    audit = extract_json_from_text(raw)

    # 模型原始字段一律保留，只多挂一个保留字段 _input_bundle。
    # 注意：这里**不写**简历/JD 原文 —— audit_json 只该有模型的判断和这份指纹。
    audit = input_provenance.attach_to_audit(audit, bundle)

    gap_df = build_gap_df(audit)
    report_id = f"GAP_{uuid.uuid4().hex[:12]}"
    score = float(audit.get("match_score") or 0.0)

    db.save_gap_report(
        report_id=report_id, trace_id=trace_id,
        company=company, title=job_name,
        tis_score=score, gap_df=gap_df, audit=audit,
        # 这条线的分数是**大模型综合判断**，与 core_pipeline 的
        # 关键词命中比例不同尺度 —— 必须标明，否则读的人会误读。
        scorer="model_match",
    )

    # 只写**一条**交接记录：目标由 handoff_to 决定。
    # 这样"同一次调用产生重复交接"在结构上就不可能发生。
    # payload 只带 bundle 的 id 与 sources（哈希 + 逻辑名），不带原文。
    db.append_message(trace_id, "Agent_A", handoff_to, "handoff",
                      {"report_id": report_id, "job": job_name,
                       "match_score": score,
                       "input_bundle_id": bundle["bundle_id"],
                       "input_sources": bundle["sources"]})

    # 落盘一份人可读的报告。
    out_dir = os.path.join(profile or pl.PROFILE_DIR, REPORT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{job_name}.md")
    with open(out_path, "w", encoding="utf-8") as fp:
        fp.write(render_report(job_name, company, trace_id, report_id, audit))

    print(f"            综合匹配度 {score} / 100   gap 项 {len(gap_df)} 个")
    print(f"            已落库 {report_id} ｜ 报告 {out_path}")
    return {"job": job_name, "score": score, "trace_id": trace_id,
            "report_id": report_id, "audit": audit,
            "input_bundle": bundle}
