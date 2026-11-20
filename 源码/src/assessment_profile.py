"""
考核证据画像：把 `assessment_attempts` 投影成**当前能力**与**进步趋势**。

定位
----
这是**只读投影**，不写库、不调用模型、不依赖任何 Agent 实例。
输入是 T03-B 已经沉淀好的评测证据，输出是确定性、可复算的 dict。

与 `ability_profile.py` 的区别（两者不能混成一种分数）
----------------------------------------------------
| | `ability_profile` | 本模块 |
|---|---|---|
| 数据来源 | Agent A 的 `score_breakdown` / gap 表 / 综合匹配分 | 真实作答与阅卷记录 |
| 回答的问题 | "我和这个岗位有多匹配" | "我这几道题考得怎么样" |
| 时间性 | 某个时间点的求职基线 | 随每次作答演进的过程证据 |
| 用途 | 岗位匹配雷达图 | 学习效果与进步趋势 |

因此导出里分成两节，标题与口径都不同 —— 把求职匹配分和学习考核分混在一起，
会让"匹配度 52"看起来像"考试 52 分"，这是两种完全不同的东西。

核心口径
--------
**每道题只取最近一次有效作答**（`latest-per-task`），然后**按题等权**。

为什么不能把全部 attempts 平均：一道题做十次，就会有十个样本，
用户只要反复刷同一道简单的题，就能把整体画像拉高 ——
那是把"练得次数多"当成了"能力强"。一个人再怎么重考同一张卷子，
也只说明这一张卷子的水平。所以当前画像里，一道题永远只占一个样本。

三态来源（`gap_ids`）
--------------------
`NULL` = 未记录；`[]` = 明确无 gap 来源；非空 = 可归属到具体 gap。
前两者都不能伪造归属，分别记进 diagnostics。
"""

import json

# 分数合法性与混合类型排序键都只有一份定义（见 assessment_rules）。
# 注意：排序键只决定**顺序**，不能拿它判断"是不是同一个 id"。
from assessment_rules import coerce_score
from assessment_rules import id_sort_key as _id_sort_key

# 维度数据来源文案：必须诚实说明"这是模型打分 + 代码聚合"，
# 不能写成"客观真值"或"系统实测"。
DIM_SOURCE = "模型逐维评分，代码按题等权聚合"

CURRENT_SOURCE = "assessment_attempts.latest_per_task"
TREND_SOURCE = "assessment_attempts.first_vs_latest_per_task"

TABLE = "assessment_attempts"

# 参与聚合的列（顺序即契约，读取端按名字取值，不靠位置猜）
_ATTEMPT_SQL_COLUMNS = (
    "a.id", "a.task_id", "a.attempt_no", "a.trace_id",
    "a.final_score", "a.model_score", "a.score_source", "a.status",
    "a.rubric_json", "a.rubric_definition_json", "a.rubric_weight",
    "a.gap_ids", "a.source_task_ids",
    # 只读题干：复测建议要能让人知道"复测哪道题"。
    # 刻意**不读** answer_text / feedback / 原始模型响应 —— 画像只需要证据，
    # 不需要把用户作答正文搬进导出与诊断。
    "a.question_text",
    "t.content", "t.task_type",
)


# ---------------------------------------------------------------- 基础工具

def _table_exists(conn, name=TABLE):
    """
    表是否存在。**不捕获数据库异常**。

    曾经这里写的是 `except Exception: return False` —— 那会把
    "连接已关闭 / 数据库被锁 / SQL 执行失败" 全部伪装成
    "旧库没有 assessment_attempts 表"，用户看到的是"暂无证据"，
    真实故障被吞掉，排查时完全找不到方向。

    缺表的正常表现是：查询成功、但没有匹配行 → False。
    查询本身出错 → 异常原样往上抛。
    """
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone() is not None


def _load_json(value, default):
    """
    解析 JSON 列。返回 (值, 是否损坏)。

    `None` 是**有效值**（= 未记录），不是损坏 —— 调用方靠它保留三态语义。
    非字符串/已解析对象也视为有效（便于纯函数单测直接传 Python 对象）。
    """
    if value is None:
        return default, False
    if isinstance(value, (list, dict)):
        return value, False
    try:
        return json.loads(value), False
    except Exception:
        return default, True


def _score(value):
    """
    把分数规范成 float；**不合法就返回 None，绝不返回 0**。

    只保留这个兼容入口，判定**全部委托** `assessment_rules.coerce_score`：
    分数合法性（bool / 非数值 / 越界 / NaN / ±inf）只允许有一份定义。
    曾经这里自己写了一遍 `v < 0 or v > 100`，NaN 与任何数比较都是 False，
    于是 NaN 被当成合法分数，一路流进画像和复测候选。
    """
    return coerce_score(value)


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _dedupe_keep_order(items):
    out = []
    seen = set()
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _unique_ids(values):
    """
    按「类型 + 值」去重，保留首次出现。

    为什么不用 `set(values)` 直接去重：`0 == False` 且哈希相同，会把两者合并；
    `None` 与 `0` 则是不同值，必须都留下。这里用 `(类型名, 值)` 作为键，
    既保住身份，也不会把 `None` 挤成 `0`。
    """
    out, seen = [], set()
    for v in values or []:
        key = (type(v).__name__, v)
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def _finalize_diagnostics(diagnostics):
    """
    把 diagnostics 收敛成**确定性**结构，所有返回路径都必须经过这里。

    为什么需要它：`invalid_score_attempt_ids` / `broken_json_attempt_ids`
    是边遍历边 append 的，顺序跟着输入走 —— 同一批记录换一个读取顺序，
    JSON 就不一样了。这对"结果可复算"是硬伤，也会让快照对比出现假差异。

    排序规则：
      · 三个 attempt_id 列表：按 `_id_sort_key`（int < str < None）；
      · `dimension_anomalies`：按 (attempt_id, dimension, reason) 复合键。
    """
    for key in ("ignored_attempt_ids", "invalid_score_attempt_ids",
                "broken_json_attempt_ids"):
        # 先去重（同一 id 在一个列表里最多一条），再按稳定键排序
        diagnostics[key] = sorted(_unique_ids(diagnostics.get(key)),
                                  key=_id_sort_key)

    anomalies = diagnostics.get("dimension_anomalies") or []
    diagnostics["dimension_anomalies"] = sorted(
        anomalies,
        key=lambda a: (_id_sort_key(a.get("attempt_id")),
                       str(a.get("dimension") or ""),
                       str(a.get("reason") or "")))
    return diagnostics


# ---------------------------------------------------------------- 读库

def load_plan_attempts(conn, plan_id):
    """
    读取某个计划的全部评测证据（**只读**，不触发迁移）。

    返回 {"table_available": bool, "reason": str|None, "attempts": [...]}。

    两个字段各说一件事，**不要合并**：
      · `table_available` —— 数据库里**真实存在** `assessment_attempts` 表吗？
        只回答"这类证据读不读得到"，与有没有给 plan_id 无关。
      · `reason` —— 这次读取为什么没拿到证据：
          `missing_plan_id`     调用方没给计划（优先级最高，先于表检查的结果）；
          `no_assessment_table` 表不存在（v8 之前的旧库，**不回退**到
                                agent_evaluations 正文猜测）；
          `None`                读到了（可能是空列表，那是"没作答"，不是读失败）。

    组合关系（写进合同，测试逐格钉住）：
        表在   + 缺 plan_id → table_available=True,  reason=missing_plan_id
        表不在 + 缺 plan_id → table_available=False, reason=missing_plan_id
        表不在 + 有 plan_id → table_available=False, reason=no_assessment_table
        表在   + 有 plan_id → table_available=True,  reason=None

    · 顺序固定为 `task_id, attempt_no, id` —— 聚合结果不依赖行的物理顺序；
    · 按 `study_tasks.plan_id` 隔离，不会混入其他计划的作答；
    · 表状态查询**不吞异常**：库被锁 / 连接坏会原样抛出，不会被说成"没有表"。
    """
    table_available = _table_exists(conn)      # 异常照抛，不翻译成 False

    if not plan_id:
        # 参数问题优先于表状态：没给计划，本来也无从查起
        return {"table_available": table_available,
                "reason": "missing_plan_id", "attempts": []}
    if not table_available:
        return {"table_available": False,
                "reason": "no_assessment_table", "attempts": []}

    sql = (
        "SELECT " + ", ".join(_ATTEMPT_SQL_COLUMNS) + " "
        "FROM assessment_attempts a "
        "JOIN study_tasks t ON a.task_id = t.id "
        "WHERE t.plan_id = ? "
        "ORDER BY a.task_id, a.attempt_no, a.id"
    )
    rows = conn.execute(sql, (plan_id,)).fetchall()

    attempts = []
    for row in rows:
        (aid, task_id, attempt_no, trace_id, final_score, model_score,
         score_source, status, rubric_json, rubric_def_json, rubric_weight,
         gap_ids_raw, src_ids_raw, question_text, task_content, task_type) = row

        rubric, bad_rubric = _load_json(rubric_json, [])
        definition, bad_def = _load_json(rubric_def_json, [])
        # gap_ids / source_task_ids 保留三态：None != []
        gaps, bad_gaps = _load_json(gap_ids_raw, None)
        src_ids, bad_src = _load_json(src_ids_raw, None)

        attempts.append({
            "attempt_id": aid,
            "task_id": task_id,
            "attempt_no": attempt_no,
            "trace_id": trace_id,
            "final_score": final_score,
            "model_score": model_score,
            "score_source": score_source,
            "status": status,
            "rubric": rubric,
            "rubric_definition": definition,
            "rubric_weight": rubric_weight,
            "gap_ids": gaps,
            "source_task_ids": src_ids,
            "question_text": question_text,
            "task_content": task_content,
            "task_type": task_type,
            "broken": {
                "rubric": bad_rubric,
                "rubric_definition": bad_def,
                "gap_ids": bad_gaps,
                "source_task_ids": bad_src,
            },
        })

    return {"table_available": True, "reason": None, "attempts": attempts}


# ---------------------------------------------------------------- 纯聚合

def _pick_latest_and_first(attempts):
    """
    按 task_id 分组，取 (first, latest)。

    排序键用 **(attempt_no, attempt_id 的稳定键)**，不用 created_at ——
    同一秒写入的两条记录时间戳可能相同，序号才是业务上的"第几次"。

    ⚠ `attempt_no` 才做 `_int()` 归一化；`attempt_id` 走 `_id_sort_key()`，
    因为它是**证据身份**，可以不是整数（纯函数合同允许 Python 对象）。
    曾经这里写成 `(_int(attempt_no), _int(attempt_id))`，字符串 id 全变成 0，
    于是"最新一次"恒等于第一条、ignored 恒为空、趋势整条消失 —— 身份被改写，
    引用就错了。

    用 max/min 而不是"按输入顺序取最后一条"，保证输入乱序也不影响结果。
    """
    by_task = {}
    for a in attempts:
        key = (_int(a.get("attempt_no")), _id_sort_key(a.get("attempt_id")))
        slot = by_task.setdefault(a.get("task_id"), {"first": None, "latest": None})
        if slot["first"] is None or key < slot["first"][0]:
            slot["first"] = (key, a)
        if slot["latest"] is None or key > slot["latest"][0]:
            slot["latest"] = (key, a)
    return by_task


def _latest_items(latest, task_ids):
    """
    把"每题最近一次"摊平成**稳定顺序**的逐题证据清单。

    这份清单是 `retest_policy` 的唯一输入：它必须与当前分、维度、gap 证据
    使用**同一批** latest-per-task 记录，否则"总分 53、建议复测 5 道题"
    会对不上账。

    只放"判断需要什么"：题干、任务正文、分数、来源、gap。
    **不放答案正文、feedback、原始模型响应** —— 复测建议不需要这些。
    `gap_ids` 做浅拷贝：列表复制一份，`None` 原样保留（三态语义）。
    """
    items = []
    for task_id in task_ids:
        a = latest[task_id]
        gaps = a.get("gap_ids")
        gaps_out = list(gaps) if isinstance(gaps, list) else gaps
        items.append({
            "task_id": task_id,
            "attempt_id": a.get("attempt_id"),
            "attempt_no": a.get("attempt_no"),
            "score": round(a["_score"], 1),
            "score_source": a.get("score_source"),
            "status": a.get("status"),
            "question_text": a.get("question_text"),
            "task_content": a.get("task_content"),
            "gap_ids": gaps_out,
        })
    return items


def _collect_dimensions(latest_by_task, task_ids, diagnostics):
    """
    聚合 rubric 维度：**每道题、每个维度最多一个样本**，按题等权平均。

    维度名称与顺序**优先取该次作答保存的 `rubric_definition_json`**，
    不回读当前 `agent_c_assessor.RUBRIC` —— 权重和维度会演进，
    用今天的定义去解释旧记录，等于篡改历史。
    """
    order = []          # 维度出现顺序（按 task_id 升序 × 每次作答内的顺序）
    labels = {}
    samples = {}        # key -> [(task_id, attempt_id, score)]

    for task_id in task_ids:
        attempt = latest_by_task[task_id]
        aid = attempt.get("attempt_id")

        definition = attempt.get("rubric_definition")
        if isinstance(definition, list):
            for d in definition:
                if not isinstance(d, dict):
                    continue
                key = str(d.get("key") or "").strip()
                if not key:
                    continue
                if key not in order:
                    order.append(key)
                labels.setdefault(key, str(d.get("name") or key))

        rubric = attempt.get("rubric")
        if not isinstance(rubric, list):
            if rubric not in (None, []):
                diagnostics["dimension_anomalies"].append(
                    {"attempt_id": aid, "dimension": None,
                     "reason": "rubric 不是数组"})
            continue

        seen = set()
        for item in rubric:
            if not isinstance(item, dict):
                diagnostics["dimension_anomalies"].append(
                    {"attempt_id": aid, "dimension": None,
                     "reason": "维度项不是对象"})
                continue
            key = str(item.get("dimension") or "").strip()
            if not key:
                diagnostics["dimension_anomalies"].append(
                    {"attempt_id": aid, "dimension": None,
                     "reason": "缺少 dimension 字段"})
                continue
            if key in seen:
                # 同一题同一维度出现两次：只认第一次，不进平均
                diagnostics["dimension_anomalies"].append(
                    {"attempt_id": aid, "dimension": key,
                     "reason": "重复维度，已忽略后出现的项"})
                continue
            seen.add(key)

            score = _score(item.get("score"))
            if score is None:
                diagnostics["dimension_anomalies"].append(
                    {"attempt_id": aid, "dimension": key,
                     "reason": f"分数不合法：{item.get('score')!r}"})
                continue

            if key not in order:
                order.append(key)      # 定义里没有的维度也保留，key 原样使用
            labels.setdefault(key, key)
            samples.setdefault(key, []).append((task_id, aid, score))

    dimensions = []
    for key in order:
        group = samples.get(key) or []
        if not group:
            continue
        # 同上：混合类型必须走 id_sort_key，直接 sorted() 会 TypeError
        task_ids_in = sorted({t for t, _, _ in group}, key=_id_sort_key)
        dimensions.append({
            "key": key,
            "label": labels.get(key, key),
            "score": round(sum(s for _, _, s in group) / len(group), 1),
            "task_count": len(task_ids_in),
            "task_ids": task_ids_in,
            "attempt_ids": [aid for _, aid, _ in group],
            "source": DIM_SOURCE,
        })
    return dimensions


def build(attempts):
    """
    把证据聚合成画像。纯函数：同一份输入永远得到同一份输出。

    返回：
        {
          "available": bool,
          "current": {score, task_count, attempt_ids, task_ids, source, note},
          "dimensions": [...],
          "trend": {task_count, avg_delta, improved, unchanged, declined, items, source},
          "gap_evidence": [...],
          "diagnostics": {...},
        }

    没有有效作答时 `current["score"] is None`、`available=False`
    —— 不生成默认分，也不画零分雷达图。
    """
    diagnostics = {
        "total_attempts": 0,
        "latest_task_samples": 0,
        "ignored_attempt_ids": [],
        "invalid_score_attempt_ids": [],
        "broken_json_attempt_ids": [],
        "unknown_gap_source_count": 0,
        "explicit_no_gap_count": 0,
        "rubric_weighted_count": 0,
        "model_fallback_count": 0,
        "dimension_anomalies": [],
    }

    items = list(attempts or [])
    diagnostics["total_attempts"] = len(items)

    # ---- 1) 过滤不可用记录（不把坏数据当成 0 分） ----
    # 顺序很重要：**先记 broken，再校验分数**。
    # 反过来写（先 `if score is None: continue`）时，"分数坏 + JSON 也坏"的记录
    # 只会被记成前者，JSON 损坏信息被 `continue` 吞掉 —— 一条记录可以同时属于
    # 多种异常，诊断要如实全部记录，不能只报第一个发现的问题。
    valid = []
    for a in items:
        broken = a.get("broken") or {}
        if any(bool(v) for v in broken.values()):
            diagnostics["broken_json_attempt_ids"].append(a.get("attempt_id"))

        score = _score(a.get("final_score"))
        if score is None:
            diagnostics["invalid_score_attempt_ids"].append(a.get("attempt_id"))
            continue

        valid.append(dict(a, _score=score))

    if not valid:
        # 两种"没有画像"必须分开：一条记录都没有 vs 有记录但全不可用。
        # 混成一种，用户会以为"我没考过"，实际上考了、只是分数坏了。
        reason = "no_attempts" if not items else "no_valid_attempts"
        return {
            "available": False,
            "unavailable_reason": reason,
            "current": {
                "score": None, "task_count": 0, "attempt_ids": [],
                "task_ids": [], "items": [], "source": CURRENT_SOURCE,
                "note": ("暂无可用评测证据" if reason == "no_attempts"
                         else "存在作答记录，但没有可用评分证据"),
            },
            "dimensions": [],
            "trend": {"task_count": 0, "avg_delta": None, "improved": 0,
                      "unchanged": 0, "declined": 0, "items": [],
                      "source": TREND_SOURCE},
            "gap_evidence": [],
            "diagnostics": _finalize_diagnostics(diagnostics),
        }

    # ---- 2) 每题只保留最近一次 ----
    slots = _pick_latest_and_first(valid)
    # 用共享的 id_sort_key，而不是 `(_int(t), str(t))`：
    # 后者会给整数 2 和字符串 "2" **完全相同**的键 (2, "2")，
    # sorted() 的稳定性再把顺序交还给输入顺序 —— 正序/反序结果不同。
    task_ids = sorted(slots, key=_id_sort_key)
    latest = {t: slots[t]["latest"][1] for t in task_ids}
    diagnostics["latest_task_samples"] = len(task_ids)

    # "被忽略"按**记录身份**判定，不看 id 的数值形态。
    # 曾经写成 `{_int(a["attempt_id"]) for ...}`：字符串 id 全归约成 0，
    # 于是新旧两条都被认成同一个 id，ignored 恒为空 —— 引用关系被抹掉了。
    selected = {id(rec) for rec in latest.values()}
    diagnostics["ignored_attempt_ids"] = [
        a.get("attempt_id") for a in valid if id(a) not in selected
    ]

    for t in task_ids:
        src = latest[t].get("score_source")
        if src == "rubric_weighted":
            diagnostics["rubric_weighted_count"] += 1
        elif src == "model_fallback":
            diagnostics["model_fallback_count"] += 1

    # ---- 3) 当前总分：按题等权 ----
    scores = [latest[t]["_score"] for t in task_ids]
    current = {
        "score": round(sum(scores) / len(scores), 1),
        "task_count": len(task_ids),
        "attempt_ids": [latest[t].get("attempt_id") for t in task_ids],
        "task_ids": list(task_ids),
        # 逐题最新证据：复测策略只吃这一份，不再回看历史 attempts
        "items": _latest_items(latest, task_ids),
        "source": CURRENT_SOURCE,
        "note": "每道题只取最近一次有效作答，按题等权平均（同题多次作答不增加权重）",
    }

    # ---- 4) rubric 维度 ----
    dimensions = _collect_dimensions(latest, task_ids, diagnostics)

    # ---- 5) 趋势：同题"第一次 → 最近一次" ----
    trend_items = []
    for t in task_ids:
        first = slots[t]["first"][1]
        last = latest[t]
        # 用**完整选择键**判断是不是同一条记录，而不是整数化后的 id。
        # 字符串 id 下 `_int("old") == _int("new") == 0`，会把两次作答当成一次，
        # 趋势凭空消失（这正是上一轮的真实缺陷）。
        if slots[t]["first"][0] == slots[t]["latest"][0]:
            continue          # 只有一次作答，不参与趋势
        delta = round(last["_score"] - first["_score"], 1)
        trend_items.append({
            "task_id": t,
            "task_content": last.get("task_content"),
            "first_attempt_id": first.get("attempt_id"),
            "first_attempt_no": first.get("attempt_no"),
            "first_score": round(first["_score"], 1),
            "latest_attempt_id": last.get("attempt_id"),
            "latest_attempt_no": last.get("attempt_no"),
            "latest_score": round(last["_score"], 1),
            "delta": delta,
        })

    deltas = [i["delta"] for i in trend_items]
    trend = {
        "task_count": len(trend_items),
        "avg_delta": round(sum(deltas) / len(deltas), 1) if deltas else None,
        "improved": sum(1 for d in deltas if d > 0),
        "unchanged": sum(1 for d in deltas if d == 0),
        "declined": sum(1 for d in deltas if d < 0),
        "items": trend_items,
        "source": TREND_SOURCE,
        "note": "只比较同一任务的第一次与最近一次；单次作答不构成趋势",
    }

    # ---- 6) 按 gap_id 归集（三态：NULL / [] / 非空） ----
    gap_samples = {}
    for t in task_ids:
        attempt = latest[t]
        gaps = attempt.get("gap_ids")
        aid = attempt.get("attempt_id")

        if gaps is None:
            diagnostics["unknown_gap_source_count"] += 1
            continue
        if not isinstance(gaps, list):
            diagnostics["unknown_gap_source_count"] += 1
            continue
        if len(gaps) == 0:
            diagnostics["explicit_no_gap_count"] += 1
            continue

        seen = set()
        for raw in gaps:
            if raw is None:
                continue
            gid = str(raw).strip()
            if not gid or gid in seen:
                continue
            seen.add(gid)
            gap_samples.setdefault(gid, []).append((t, aid, attempt["_score"]))

    gap_evidence = []
    for gid in sorted(gap_samples):
        group = gap_samples[gid]
        gap_evidence.append({
            "gap_id": gid,
            "current_score": round(sum(s for _, _, s in group) / len(group), 1),
            "task_count": len({t for t, _, _ in group}),
            "task_ids": sorted({t for t, _, _ in group}, key=_id_sort_key),
            "attempt_ids": [aid for _, aid, _ in group],
            "source": "assessment_attempts.latest_per_task.gap_ids",
        })

    return {
        "available": True,
        "unavailable_reason": None,
        "current": current,
        "dimensions": dimensions,
        "trend": trend,
        "gap_evidence": gap_evidence,
        "diagnostics": _finalize_diagnostics(diagnostics),
    }


def profile_for_plan(conn, plan_id):
    """
    便捷入口：读库 + 聚合（导出层只需调这一个）。

    三个返回字段的语义（务必分清，"表可读"不等于"画像有证据"）：

    · `table_available`
        bool —— 数据库里**有没有** `assessment_attempts` 表。
        False 只表示"库里读不到这类证据"，不代表计划没作答。
    · `available`
        bool —— 是否真的产出了可用画像（至少一条有效作答）。
        它可能为 False 而 `table_available` 为 True（有行但分数全坏了）。
    · `unavailable_reason` —— 四选一 + None：
        `missing_plan_id`    调用方没给计划，无从查起；
        `no_assessment_table` 旧库没有评测表（v8 之前），不做正文猜测；
        `no_attempts`         表在、计划在，但一条作答都没有；
        `no_valid_attempts`   有作答记录，但没有一条能算出分；
        `None`                有可用画像。
    """
    loaded = load_plan_attempts(conn, plan_id)
    result = build(loaded["attempts"])

    # 两个布尔值各说一件事，不能互相顶替：
    #   table_available —— 库里有没有这张表（读取层面）
    #   available       —— 有没有产出可用画像（业务层面）
    result["table_available"] = loaded["table_available"]

    if loaded["reason"]:
        # 读取就没成功（缺 plan_id / 缺表）：原因以读取端为准
        result["unavailable_reason"] = loaded["reason"]
    elif result["available"]:
        result["unavailable_reason"] = None
    else:
        # 表能读，但画像不可用 —— 用 build() 区分 no_attempts / no_valid_attempts
        result["unavailable_reason"] = (result.get("unavailable_reason")
                                        or "no_valid_attempts")
    return result
