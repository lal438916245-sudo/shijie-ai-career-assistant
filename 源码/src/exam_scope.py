"""
考察范围解析（纯逻辑：不调用大模型、不访问网络、不读知识库）。

为什么要单独成模块
----------------
"考哪几天的内容"是一个**判定问题**，不是生成问题：

    · 判定标准是确定的（day 1-3 / 第 2 阶段 / 最近 7 天 / 含某关键词）
    · 结果必须可复现、可单独测试
    · 不该为了"决定考哪几天"而多花一次大模型调用

所以这里只做解析与取数，把"出什么题"留给 Agent C。

支持的写法
---------
    day:3            只考第 3 天
    day:1-3          考第 1~3 天
    phase:2          考第 2 个学习阶段（按 study_phases.phase_order）
    last:3           最近 3 天（按计划里实际存在的 day 取最后 N 个）
    keyword:epoll    考内容里含该关键词的任务
    all              全部（默认不含已生成的考察题）

用法
----
    scope = parse_scope("day:1-3")            # -> dict
    tasks = select_tasks(db, plan_id, scope)  # -> list[dict]
    label = describe(scope, tasks)            # -> "第 1~3 天（3 天 / 5 个任务）"
"""

VALID_KINDS = ("day", "day_range", "phase", "last", "keyword", "all")


def parse_scope(spec):
    """
    把字符串范围说明解析成结构化 dict。

    解析失败时**抛出 ValueError 并给出可用写法** —— 静默退化成 "all"
    会让用户以为考的是"最近一周"，实际考了全部，属于危险的不一致。
    """
    s = (spec or "").strip()
    if not s:
        raise ValueError("范围不能为空")

    low = s.lower()

    if low == "all":
        return {"raw": s, "kind": "all"}

    if ":" not in s:
        raise ValueError(
            f"无法识别的范围写法：{spec!r}\n"
            "可用：day:3 ｜ day:1-3 ｜ phase:2 ｜ last:3 ｜ keyword:xxx ｜ all")

    head, _, tail = s.partition(":")
    head = head.strip().lower()
    tail = tail.strip()
    if not tail:
        raise ValueError(f"范围 {spec!r} 缺少参数，例如 day:1-3")

    if head == "day":
        if "-" in tail:
            a, _, b = tail.partition("-")
            try:
                d_from, d_to = int(a), int(b)
            except ValueError:
                raise ValueError(f"day 范围必须是整数，收到：{tail!r}")
            if d_from > d_to:
                d_from, d_to = d_to, d_from      # 容忍写反
            return {"raw": s, "kind": "day_range",
                    "day_from": d_from, "day_to": d_to}
        try:
            d = int(tail)
        except ValueError:
            raise ValueError(f"day 必须是整数，收到：{tail!r}")
        return {"raw": s, "kind": "day", "day_from": d, "day_to": d}

    if head == "phase":
        try:
            order = int(tail)
        except ValueError:
            raise ValueError(f"phase 必须是阶段序号（整数），收到：{tail!r}")
        if order < 1:
            raise ValueError("phase 序号从 1 开始")
        return {"raw": s, "kind": "phase", "phase_order": order}

    if head in ("last", "recent"):
        try:
            n = int(tail)
        except ValueError:
            raise ValueError(f"last 必须是天数（整数），收到：{tail!r}")
        if n < 1:
            raise ValueError("last 的天数必须 >= 1")
        return {"raw": s, "kind": "last", "n": n}

    if head in ("keyword", "kw", "kw"):
        return {"raw": s, "kind": "keyword", "keyword": tail}

    raise ValueError(
        f"无法识别的范围类型 {head!r}。可用：day / phase / last / keyword / all")


def select_tasks(db, plan_id, scope):
    """
    按范围取任务（默认排除已有考察题，避免"再考一遍"考到之前的题）。

    返回 list[dict]；空列表表示这个范围没命中任何任务 ——
    调用方应据此提示用户，而不是继续出题。
    """
    kind = scope["kind"]

    if kind in ("day", "day_range"):
        return db.get_tasks_by_day_range(
            plan_id, scope["day_from"], scope["day_to"])
    if kind == "phase":
        return db.get_tasks_by_phase(plan_id, scope["phase_order"])
    if kind == "last":
        days = db.get_distinct_days(plan_id, include_exam=False)
        if not days:
            return []
        tail = days[-scope["n"]:]
        return db.get_tasks_by_day_range(plan_id, min(tail), max(tail))
    if kind == "keyword":
        return db.get_tasks_by_keyword(plan_id, scope["keyword"])
    if kind == "all":
        return db.get_tasks_by_plan(plan_id)

    raise ValueError(f"未知范围类型：{kind!r}")


def available_days(tasks):
    """范围内可被出题针对的 day 列表（升序、去重）。"""
    return sorted({t["day"] for t in tasks})


def describe(scope, tasks):
    """生成人可读的范围说明，用于提示与落库标签。"""
    kind = scope["kind"]
    if kind == "day":
        base = f"第 {scope['day_from']} 天"
    elif kind == "day_range":
        base = f"第 {scope['day_from']}~{scope['day_to']} 天"
    elif kind == "phase":
        base = f"第 {scope['phase_order']} 个学习阶段"
    elif kind == "last":
        base = f"最近 {scope['n']} 天"
    elif kind == "keyword":
        base = f"含关键词「{scope['keyword']}」"
    else:
        base = "全部计划"

    days = available_days(tasks)
    if not days:
        return f"{base}（未命中任务）"
    return f"{base}（覆盖 Day {days[0]}~{days[-1]}，共 {len(tasks)} 个任务）"


def build_material(tasks, max_chars_per_task=400):
    """
    把范围内的任务拼成**人可读**的材料（dry-run 预览、日志用）。

    ⚠ 这个格式**没有任务 ID**，不能作为 Agent C 的来源依据 ——
    同一天两条任务在它眼里长得一样（只有 Day 和正文）。
    模型输入请用 `build_task_catalog()`。
    """
    lines = []
    for t in tasks:
        content = (t.get("content") or "").strip()
        expect = (t.get("expected_outcome") or "").strip()
        if len(content) > max_chars_per_task:
            content = content[:max_chars_per_task] + "…"
        if len(expect) > max_chars_per_task:
            expect = expect[:max_chars_per_task] + "…"
        lines.append(f"[Day {t['day']}] {content}")
        if expect:
            lines.append(f"    预期学习结果：{expect}")
    return "\n".join(lines)


def _parse_gap_cell(value):
    """study_tasks.gap_ids 的存储形态 → list 或 None（含义见 exam_provenance）。"""
    import json

    if value is None:
        return None
    if isinstance(value, list):
        return list(value)
    text = str(value).strip()
    if not text:
        return None
    data = json.loads(text)
    return data if isinstance(data, list) else None


def build_task_catalog(tasks, max_chars_per_task=400):
    """
    构造给 Agent C 的**结构化任务目录**（确定性 JSON 数组）。

    每条记录包含（且只包含）：
        task_id          数据库真实主键 —— 不另造 ID
        day              排期信息（**不是**来源标识）
        content          学习内容（截断）
        expected_outcome 交付标准（截断）
        gap_ids          该任务已记录的来源差距（None / [] / 非空）

    为什么不放别的：简历/JD 原文、绝对路径、status/score/phase_id 之类
    与"这道题考哪条任务"无关，放进去只会白烧 token 并污染引用边界。

    为什么用 JSON 而不是 `[Day N] 内容`：
      · 同一天可以有多条任务（v3 迁移允许一天多行），只有 Day 根本无法区分；
      · JSON 里 ID 与判别字段绑在同一个对象上，模型选完可以直接回填；
      · 正文里的换行 / 引号不会破坏结构。
    """
    import json

    records = []
    for t in tasks:
        content = (t.get("content") or "").strip()
        expect = (t.get("expected_outcome") or "").strip()
        if len(content) > max_chars_per_task:
            content = content[:max_chars_per_task] + "…"
        if len(expect) > max_chars_per_task:
            expect = expect[:max_chars_per_task] + "…"
        records.append({
            "task_id": int(t["id"]),
            "day": int(t["day"]),
            "content": content,
            "expected_outcome": expect,
            "gap_ids": _parse_gap_cell(t.get("gap_ids")),
        })
    return json.dumps(records, ensure_ascii=False, sort_keys=True, indent=2)


if __name__ == "__main__":
    # 自检：解析规则是纯函数，可直接断言
    cases = [
        ("day:3", {"kind": "day", "day_from": 3, "day_to": 3}),
        ("day:1-3", {"kind": "day_range", "day_from": 1, "day_to": 3}),
        ("day:3-1", {"kind": "day_range", "day_from": 1, "day_to": 3}),
        ("phase:2", {"kind": "phase", "phase_order": 2}),
        ("last:7", {"kind": "last", "n": 7}),
        ("keyword:epoll", {"kind": "keyword", "keyword": "epoll"}),
        ("all", {"kind": "all"}),
        ("ALL", {"kind": "all"}),
    ]
    ok = True
    for spec, expect in cases:
        got = parse_scope(spec)
        hit = all(got.get(k) == v for k, v in expect.items())
        ok = ok and hit
        print(f"  [{'OK' if hit else 'FAIL'}] {spec:16s} -> {got}")

    bad = ["", "day", "day:x", "phase:0", "last:0", "week:3", "xxx:1"]
    print()
    for spec in bad:
        try:
            parse_scope(spec)
            print(f"  [FAIL] {spec!r} 本应报错却通过了")
            ok = False
        except ValueError:
            print(f"  [OK] {spec!r} 正确报错")

    print("\n范围解析自检：" + ("全部通过 ✅" if ok else "存在失败 ❌"))
