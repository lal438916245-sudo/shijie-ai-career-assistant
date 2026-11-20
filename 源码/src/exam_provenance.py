"""
学习任务 → 考题 的来源链（Exam Provenance）

解决什么问题
------------
改造前，一道考题知道自己"落在第几天"，却不知道自己"考的是哪条学习任务"：

    exam_scope.build_material()   → 只有 `[Day N] 内容`，**没有任务 ID**
    Agent C 输出合同               → 只有 target_day，同一天两条任务无法区分
    insert_exam_task()            → 不写来源，gap_ids 也是 NULL

于是"这道题对应哪个差距"在考题这一层彻底断掉。而 `target_day` 只是排期信息：
同一天可以有多条任务（v3 迁移就允许了），用 day 反推来源等于**猜**。

本模块负责三件事
----------------
1. 校验模型声明的 `source_task_ids` 是否真的在本次范围内；
2. 从**有效来源任务**派生考题的 `gap_ids`（模型不能自己决定）；
3. 给出明确的来源状态，供落库与诊断。

责任边界
--------
模型只能**声明**来源（source_task_ids）；
代码负责**验证**与**派生**（有效集合、gap 继承）。
模型不参与 gap 的合并，也不允许重写它 —— 否则"可追溯"就退化成"模型说了算"。

三态语义（与 T02-A 一致）
-------------------------
    None  —— 未记录（旧数据 / 上游未提供）
    []    —— 记录为"没有"
    非空  —— 有明确列表
派生 gap_ids 时严格遵守：
    · 任一有效来源任务的 gap_ids 为 None → 考题 gap_ids 也是 None（不伪装完整）
    · 全部有效来源都明确为空列表 → []
    · 否则确定性去重合并
"""

import json


# ------------------------------------------------------------
# 来源状态（写进 study_tasks.provenance_status）
# ------------------------------------------------------------
# 用 `exam_` 前缀与普通学习任务的 linked/unlinked/... 区分开：
# 同一个列里同时承载两类实体，前缀让"这行是考题"一眼可辨，
# 也避免查询普通任务时把考题状态混进来。

EXAM_LINKED = "exam_linked"
EXAM_PARTIALLY_LINKED = "exam_partially_linked"
EXAM_UNKNOWN_SOURCE = "exam_unknown_source"
EXAM_UNLINKED = "exam_unlinked"

EXAM_PROVENANCE_VALUES = (
    EXAM_LINKED,
    EXAM_PARTIALLY_LINKED,
    EXAM_UNKNOWN_SOURCE,
    EXAM_UNLINKED,
)


def normalize_ids(raw):
    """
    把模型给的 source_task_ids 归一化成 list[int]。

    · 接受 int 与纯数字字符串（模型经常把 ID 写成 "1"）；
    · 布尔值要排除 —— Python 里 `True` 是 int 的子类，会被当成 1；
    · 去重且保持首次出现顺序（确定性）；
    · 其它噪音（None / 浮点 / 非数字 / dict / list）一律丢弃。
    """
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raw = [raw]

    out = []
    for x in raw:
        if isinstance(x, bool):
            continue
        if isinstance(x, int):
            val = x
        elif isinstance(x, str) and x.strip().isdigit():
            val = int(x.strip())
        else:
            continue
        if val not in out:
            out.append(val)
    return out


def validate(declared_ids, tasks):
    """
    用**本次实际选中的任务集合**校验声明。

    返回 (valid_ids, unknown_ids)，两者都保持声明顺序、已去重。

    不存在的 ID 绝不会进入 valid —— 它是"模型编造的来源"，
    只能作为诊断信息保留，不能落库成有效来源。
    """
    known = {int(t["id"]) for t in tasks if t.get("id") is not None}
    valid, unknown = [], []
    for tid in normalize_ids(declared_ids):
        if tid in known:
            if tid not in valid:
                valid.append(tid)
        else:
            if tid not in unknown:
                unknown.append(tid)
    return valid, unknown


def status_for(valid_ids, unknown_ids):
    """按"有没有有效来源 / 有没有编造"判定状态。"""
    if unknown_ids and valid_ids:
        return EXAM_PARTIALLY_LINKED
    if unknown_ids:
        return EXAM_UNKNOWN_SOURCE
    if valid_ids:
        return EXAM_LINKED
    return EXAM_UNLINKED


def _parse_gap_cell(value):
    """
    把 study_tasks.gap_ids 的存储形态解析成 list 或 None。

    存储约定：JSON 数组字符串；NULL 表示"未记录"。
    解析失败时抛错而不是吞掉 —— 静默当成 [] 会把"未记录"伪装成"记录为无"。
    """
    if value is None:
        return None
    if isinstance(value, list):
        return list(value)
    text = str(value).strip()
    if not text:
        return None
    data = json.loads(text)
    if data is None:
        return None
    if not isinstance(data, list):
        raise ValueError(f"gap_ids 字段不是数组：{value!r}")
    return data


def derive_gap_ids(valid_ids, tasks):
    """
    从**有效来源任务**派生考题的 gap_ids。

    规则（缺一不可）：
      1. 只读有效来源任务，模型不能提供或覆盖；
      2. 任一来源 gap_ids 为 None → 返回 None（不伪装成完整继承）；
      3. 全部来源都明确为空 → 返回 []；
      4. 否则按"来源声明顺序 → 任务内顺序"合并，去重。

    返回 (gap_ids, unknown_meta)。unknown_meta 仅用于诊断。
    """
    by_id = {int(t["id"]): t for t in tasks if t.get("id") is not None}

    if not valid_ids:
        # 没有任何有效来源：明确记录为"空"，而不是 None（None 是未记录）
        return [], {"sources_with_null_gap": []}

    cells = []
    null_sources = []
    for tid in valid_ids:
        task = by_id.get(int(tid))
        if task is None:            # 理论上不会发生（validate 已过滤）
            continue
        parsed = _parse_gap_cell(task.get("gap_ids"))
        if parsed is None:
            null_sources.append(int(tid))
        cells.append(parsed)

    if null_sources:
        # 有一个来源的 gap 未记录，就不能声称"已完整继承"
        return None, {"sources_with_null_gap": null_sources}

    merged = []
    for cell in cells:
        for gid in (cell or []):
            gid = str(gid).strip()
            if gid and gid not in merged:
                merged.append(gid)
    return merged, {"sources_with_null_gap": []}


def attach_provenance(questions, tasks):
    """
    给 Agent C 的每道题补齐来源字段：有效 source_task_ids / gap_ids / 状态。

    输入 questions 只要求有 "question" 等字段；返回新的 list[dict]，
    额外带：
        source_task_ids   仅有效 ID
        gap_ids           由来源任务派生（可能 None / [] / 非空）
        provenance_status  exam_* 之一
        unknown_task_ids  本次诊断用（不落库）
    """
    out = []
    for q in (questions or []):
        item = dict(q)
        declared = item.get("source_task_ids")
        valid, unknown = validate(declared, tasks)
        gap_ids, meta = derive_gap_ids(valid, tasks)

        item["source_task_ids"] = valid
        item["gap_ids"] = gap_ids
        item["provenance_status"] = status_for(valid, unknown)
        item["unknown_task_ids"] = unknown
        item["sources_with_null_gap"] = meta["sources_with_null_gap"]
        out.append(item)
    return out


def summarize(questions):
    """统计一批题目的来源覆盖情况，供日志/交接 payload 使用。"""
    counts = {v: 0 for v in EXAM_PROVENANCE_VALUES}
    unknown_all = []
    for q in (questions or []):
        st = q.get("provenance_status")
        if st in counts:
            counts[st] += 1
        for tid in (q.get("unknown_task_ids") or []):
            if tid not in unknown_all:
                unknown_all.append(tid)
    result = {"total": len(questions or []), "unknown_task_ids": unknown_all}
    result.update(counts)
    return result
