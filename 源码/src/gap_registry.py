"""
差距登记册（Gap Registry）

解决什么问题
------------
Agent A 的 `invisible_gaps` 只是 JSON 数组里的匿名对象，`gap_table` 的行也只有
「技能 / 状态 / 优先级」。于是：

  · 同一份报告里两条同名技能的 gap 无法区分；
  · 报告重算后无法判断"还是不是同一条"；
  · Agent B 生成的学习任务**没有任何字段**能指回它的来源差距。

`_render_gap_report()` 更把结构压成了"人话版"字符串，下游只能靠
**文本子串匹配**（`contracts.claims_from_agent_b` 里的 `s in low`）去猜关联 ——
这不是关系，只是事后猜测，也无法落库查询。

本模块给每条 gap 一个**内容派生**的稳定 ID，并提供"任务声明的 id 是否合法"的
分类器。它是纯标准库、零依赖、离线、确定性的。

gap_id 的计算
-------------
    gap_id = f"{report_id}#{sha256(canonical_gap)[:12]}"

其中 `canonical_gap` 是把 gap 的语义字段按固定顺序序列化：

    json.dumps({"skill", "industry_requirement", "candidate_current",
                "gap_reason", "status", "priority"},
               sort_keys=True, separators=(",", ":"), ensure_ascii=False)

三条性质（都有对应测试）：
  1. **稳定** —— 同一报告 + 同一内容，跨进程、跨次运行结果相同（不用 `hash()`）；
  2. **顺序无关** —— 按内容算而不按数组下标，所以 `invisible_gaps` 调换顺序不改变 id；
  3. **内容敏感** —— 任一字段改一个字符，id 必然变化，即"这是另一版 gap"。

为什么前缀是 `report_id`
------------------------
不同报告里完全相同的技能（比如「特征工程」）语义上是**不同的 gap 实例**。
带上 report_id 就天然不串线，不需要额外的命名空间管理。

⚠ 这个 ID 只证明"两次读到的是同一段内容"，不证明差距判断本身正确、
也不证明内容真实。它是**同一性**标识，不是真实性认证。
"""

import hashlib
import json

# gap_id 的分隔符。用 `#` 而不是 `:`，方便一眼分辨
# `GAP_xxx#a1b2c3` 是「某报告下的某条 gap」。
SEPARATOR = "#"


# ------------------------------------------------------------
# provenance_status 取值（写进 study_tasks.provenance_status）
# ------------------------------------------------------------

# 模型的 source_gap_ids 全部有效
PROVENANCE_LINKED = "linked"
# 报告里有 gap，但模型没声明来源（给的是空数组）
PROVENANCE_UNLINKED = "unlinked"
# 模型声明了至少一个不存在的 id（可能同时含有有效 id）
PROVENANCE_UNKNOWN_GAP_ID = "unknown_gap_id"
# 报告本身没有结构化 gap，无从关联
PROVENANCE_NO_GAPS = "no_gaps_in_report"

PROVENANCE_VALUES = (
    PROVENANCE_LINKED,
    PROVENANCE_UNLINKED,
    PROVENANCE_UNKNOWN_GAP_ID,
    PROVENANCE_NO_GAPS,
)


# ============================================================
# gap_id
# ============================================================

def _sha12(text):
    """SHA-256 前 12 位十六进制 —— 足够避免碰撞，又不至于太长塞不进日志。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _canonical_gap(gap):
    """
    把一条 gap 收敛成规范字符串。

    两种来源的键名不同（invisible_gaps 用英文键，gap_table 用中文键），
    这里统一成一组的语义字段 —— 否则同一内容在两种来源下会算出不同 id。
    """
    payload = {
        "skill": str(gap.get("skill") or gap.get("技能") or "").strip(),
        "industry_requirement": str(gap.get("industry_requirement") or "").strip(),
        "candidate_current": str(gap.get("candidate_current") or "").strip(),
        "gap_reason": str(gap.get("gap_reason") or "").strip(),
        "status": str(gap.get("状态") or gap.get("status") or "").strip(),
        "priority": str(gap.get("优先级") or gap.get("priority") or "").strip(),
    }
    if gap.get('requirement_id'):
        payload['requirement_id'] = gap['requirement_id']
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def gap_id_for(report_id, gap):
    """
    计算一条 gap 的稳定 ID。

    report_id 必填 —— 没有报告上下文就无法保证不与其他报告串线。
    """
    if not report_id or not str(report_id).strip():
        raise ValueError("gap_id 需要 report_id（否则不同报告的同名 gap 无法区分）")
    if not isinstance(gap, dict):
        raise TypeError(f"gap 必须是 dict，实际是 {type(gap).__name__}")
    return f"{str(report_id).strip()}{SEPARATOR}{_sha12(_canonical_gap(gap))}"


# ============================================================
# 从 audit 提取 gap 清单
# ============================================================

def extract_gaps(audit, report_id):
    """
    从 Agent A 的 audit 里提取带稳定 ID 的 gap 清单。

    取值策略
    --------
    1. 先取 `invisible_gaps`（信息最全：JD 要求 / 现状 / 差距原因）；
    2. 再取 `gap_table`（硬技能表）。两边都取 —— 因为 Agent B 的
       `_render_gap_report` 同时展示了它们，只在表里出现的 gap 若不给 ID，
       对应任务就只能标 `unlinked`，白白丢一条可追溯关系。
    3. 内容完全相同的条目折叠成一条（它们的 canonical 一致 → 同一个 ID），
       避免 prompt 里出现重复行。

    返回 [{"gap_id","skill","priority","status","source",
            "industry_requirement","candidate_current","gap_reason"}, ...]

    顺序与原始数组一致；但 **ID 与顺序无关**（见模块注释）。
    """
    if not isinstance(audit, dict):
        return []

    if audit.get('diagnosis_version') == 'evidence-a-v1':
        from diagnosis_evidence import evidence_gaps
        return [{**gap, 'gap_id': gap_id_for(report_id, gap), 'source': 'evidence_assessment'}
                for gap in evidence_gaps(audit)]

    out = []
    seen = set()

    def _add(gap, source):
        if not isinstance(gap, dict):
            return
        gid = gap_id_for(report_id, gap)
        if gid in seen:
            return
        seen.add(gid)
        out.append({
            "gap_id": gid,
            "skill": str(gap.get("skill") or gap.get("技能") or "").strip(),
            "priority": str(gap.get("优先级") or gap.get("priority") or "").strip(),
            "status": str(gap.get("状态") or gap.get("status") or "").strip(),
            "source": source,
            "industry_requirement": str(gap.get("industry_requirement") or "").strip(),
            "candidate_current": str(gap.get("candidate_current") or "").strip(),
            "gap_reason": str(gap.get("gap_reason") or "").strip(),
        })

    for gap in (audit.get("invisible_gaps") or []):
        _add(gap, "invisible_gaps")
    for row in (audit.get("gap_table") or []):
        _add(row, "gap_table")
    return out


def known_gap_ids(gaps):
    """从 extract_gaps 的结果取出 id 集合（供分类器使用）。"""
    return {g["gap_id"] for g in (gaps or [])}


# ============================================================
# 任务来源分类
# ============================================================

def classify(raw_ids, known, has_gaps):
    """
    判断一条任务声明的来源是否合法。

    参数
    ----
    raw_ids  : 模型给出的 source_gap_ids（可能含空串、重复、不存在的 id）
    known    : 合法 gap_id 集合
    has_gaps : 报告里到底有没有 gap（区分"模型没选"和"没得选"）

    返回 (valid_ids, unknown_ids, status)
        status ∈ PROVENANCE_VALUES

    设计立场：**记录，不阻断**
    --------------------------
    模型给了不存在的 id 时，不把它当成"校验失败"去重试 ——
    重试有 token 成本，还可能反复失败。但也绝不静默忽略：
    `unknown_ids` 要原样返回，由调用方写进交接 payload，
    任务行的 `provenance_status` 标成 `unknown_gap_id`。
    这样"这条任务的来源是编的"在数据里是**可查的**，而不是悄悄消失。
    """
    known = set(known or ())

    # 去重但保留首次出现顺序，同时清掉空值与非字符串噪音。
    # 注意 `None` 不能被 str() 成 "None" 当成一个 id —— 那会被误判成编造来源。
    cleaned = []
    for x in (raw_ids or []):
        if x is None:
            continue
        s = str(x).strip()
        if s and s not in cleaned:
            cleaned.append(s)

    valid = [x for x in cleaned if x in known]
    unknown = [x for x in cleaned if x not in known]

    if unknown:
        # 含"部分有效"的情况也归到这里：只要有编造的 id 就必须被看见
        status = PROVENANCE_UNKNOWN_GAP_ID
    elif valid:
        status = PROVENANCE_LINKED
    elif not has_gaps:
        status = PROVENANCE_NO_GAPS
    else:
        status = PROVENANCE_UNLINKED

    return valid, unknown, status


def summarize_plan_provenance(plan, gaps):
    """
    统计一份计划的来源覆盖情况，供交接 payload / 日志使用。

    返回：
        {"total": n, "linked": n, "unlinked": n,
         "unknown_gap_id": n, "no_gaps_in_report": n,
         "unknown_ids": [...], "gap_count": 报告里的 gap 数}

    与 DB 落库时调用的是**同一个** `classify()`，
    所以 payload 的统计和 `provenance_status` 列不会各说各话。
    """
    known = known_gap_ids(gaps)
    has_gaps = bool(known)
    counts = {v: 0 for v in PROVENANCE_VALUES}
    unknown_all = []
    total = 0

    for phase in getattr(plan, "phases", []) or []:
        for task in getattr(phase, "tasks", []) or []:
            total += 1
            raw = getattr(task, "source_gap_ids", []) or []
            _valid, unknown, status = classify(raw, known, has_gaps)
            counts[status] = counts.get(status, 0) + 1
            for u in unknown:
                if u not in unknown_all:
                    unknown_all.append(u)

    result = {"total": total, "gap_count": len(known),
              "unknown_ids": unknown_all}
    result.update(counts)
    return result


# ============================================================
# Prompt 片段
# ============================================================

# 目录里每条记录必须带的字段 —— 也是"可判别"的最小充分集。
#
# 为什么必须带 industry_requirement / candidate_current / gap_reason：
# 旧版目录只输出 `gap_id | 技能 | 优先级`。当两条 gap 技能相同、优先级相同、
# 只有"JD 要求 / 我的现状 / 差在哪"不同时，模型看到的**除 ID 外完全相同**，
# 而 ID 是内容哈希、对人类和模型都是随机串 —— 它没有任何依据选对。
# 把判别字段与 ID 放进同一个对象，选择才有依据。
CATALOG_FIELDS = (
    "gap_id",
    "source",
    "skill",
    "priority",
    "status",
    "industry_requirement",
    "candidate_current",
    "gap_reason",
)


def build_gap_catalog(gaps):
    """
    把 `extract_gaps()` 的结果收敛成**可判别的结构化目录**。

    只保留 CATALOG_FIELDS 里的 8 个字段：
      · 不含简历/JD 原文，不含绝对路径，不含 audit 里与 gap 无关的字段；
      · `gap_id` **原样使用**，绝不重新计算 —— 重算会让目录与落库时的
        `source_gap_ids` 校验不是同一套 ID，等于制造两套主键。
    """
    records = []
    for g in (gaps or []):
        record = {k: g.get(k, "") for k in CATALOG_FIELDS}
        if g.get('source') == 'evidence_assessment':
            for key in ('requirement_id', 'jd_category', 'evidence_status', 'recommended_action', 'follow_up'):
                record[key] = g.get(key, '')
        records.append(record)
    return records


def format_gap_catalog(gaps, *, allow_unlinked=True):
    """
    把 gap 清单渲染成给 Agent B 的 prompt 片段（确定性 JSON 数组）。

    为什么从 Markdown 表格改成 JSON
    -------------------------------
    1. **可判别**：表格只放得下短字段，判别信息被压掉；JSON 能把
       industry_requirement / candidate_current / gap_reason 与 gap_id 绑在
       同一个对象里。
    2. **边界可靠**：字段里出现 `|`、换行、双引号时，Markdown 表格会被撑破
       （`|` 直接变成列分隔符），JSON 由 `json.dumps` 转义，边界不会被内容破坏。
    3. **确定性**：`ensure_ascii=False` + `sort_keys=True` + 固定缩进，
       同一份 gaps 多次渲染逐字一致，便于回归测试与 diff。

    顺序沿用 `extract_gaps()` 的输出顺序（与报告里的 gap 顺序一致），
    不再排序 —— 输入相同则输出相同；不引入额外的顺序假设。
    """
    if not gaps:
        return ""

    records = build_gap_catalog(gaps)
    if any(g.get('source') == 'evidence_assessment' for g in gaps):
        # No data is removed; only transport whitespace is compacted.
        payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    else:
        payload = json.dumps(records, ensure_ascii=False, sort_keys=True, indent=2)

    return "\n".join([
        "【可追溯的差距清单（唯一合法的 gap_id 来源）】",
        "下面是一个 JSON 数组，每个对象是一条差距：gap_id 与它的判别依据"
        "（JD 要求 / 我的现状 / 差在哪里）绑在同一个对象里。",
        "填写 `source_gap_ids` 时**只能**使用这里出现的完整 gap_id 字符串；"
        "请根据判别字段选择真正对应的那一条 —— 技能名相同并不代表是同一条差距。",
        ("如果某天的任务确实不对应任何一条差距（例如纯复习），留空数组 []，"
         "**不要编造 gap_id**。" if allow_unlinked else
         "本会话每项任务含复习都须关联至少一条真实差距；不得留空、编造或用无关来源凑数。"),
        "",
        "```json",
        payload,
        "```",
    ])
