"""
能力画像：为雷达图构造**真实**的维度与分数（纯逻辑，不调用大模型）。

为什么需要它
------------
`core_pipeline.py` 里的雷达图曾经是写死的：

    cats   = ['代码力', '产品力', '业务感', 'AI工具应用', '文档力']
    scores = [85, 70, 60, 95, 75]

这两行是项目里最容易被面试官问住的地方之一 —— 一个"能力画像"图表，
分数却是编的。更糟的是它**看起来**很专业，没人会怀疑。

现在改成从真实数据算：
  · Agent A 的 `score_breakdown`（大模型给的三维度打分，带依据）
  · gap 表的「已掌握 / 未掌握」统计（确定性的、可复算）
  · 综合匹配分

维度不足 3 个时抛错，而不是画一个退化的图形 ——
**宁可不出图，也不要出一张靠编的图。**

维度来源会在报告的"数据来源"一列里如实标注，让读者知道
哪些是模型打分、哪些是规则统计。
"""

# Agent A 的三维度键名 → 展示用标签
BREAKDOWN_LABELS = {
    "hard_skills": "技术栈吻合",
    "project_depth": "项目深度",
    "domain_fit": "场景匹配",
}

MIN_DIMS = 3

# 维度来源（写进报告，避免读者混淆"模型打分"与"规则统计"）
SRC_LLM = "AI 猎头打分"
SRC_GAP = "Gap 表统计"
SRC_OVERALL = "综合分"


def breakdown_dimensions(audit):
    """取 Agent A 的三维度打分（有依据，属于模型判断）。"""
    bd = (audit or {}).get("score_breakdown") or {}
    out = []
    for key, label in BREAKDOWN_LABELS.items():
        item = bd.get(key) or {}
        score = item.get("score")
        if isinstance(score, (int, float)):
            out.append({
                "label": label,
                "score": round(float(score), 1),
                "source": SRC_LLM,
                "reason": str(item.get("reason") or "").strip(),
            })
    return out


def _is_mastered(status):
    # gap 表里"已掌握"是唯一表示掌握的取值（实测形如 "已掌握" / " 未掌握 (Gap)"）
    return "已掌握" in (status or "")


def _is_urgent(priority):
    p = (priority or "").strip()
    return p.startswith("P0") or p.startswith("P1")


def coverage_dimensions(gap_records):
    """
    从 gap 表算两项覆盖率（确定性统计，可复算）。

      · 硬技能覆盖面 = 已掌握 / 全部技能
      · 紧急缺口完成度 = P0/P1 中已掌握 / P0/P1 总数
    """
    records = [r for r in (gap_records or []) if (r.get("技能") or "").strip()]
    if not records:
        return []

    total = len(records)
    mastered = sum(1 for r in records if _is_mastered(r.get("状态")))
    urgent = [r for r in records if _is_urgent(r.get("优先级"))]

    out = [{
        "label": "硬技能覆盖面",
        "score": round(mastered * 100.0 / total, 1),
        "source": SRC_GAP,
        "reason": f"岗位要求 {total} 项技能，已掌握 {mastered} 项",
    }]

    if urgent:
        done = sum(1 for r in urgent if _is_mastered(r.get("状态")))
        out.append({
            "label": "紧急缺口完成度",
            "score": round(done * 100.0 / len(urgent), 1),
            "source": SRC_GAP,
            "reason": f"P0/P1 共 {len(urgent)} 项，已掌握 {done} 项",
        })
    return out


def build(audit=None, gap_records=None, overall=None, min_dims=MIN_DIMS):
    """
    组装雷达图数据。

    优先级：模型三维度 > gap 统计维度 > 综合分。
    同名的维度只保留第一个（模型的"技术栈吻合"与统计的"硬技能覆盖面"语义不同，
    所以它们会同时存在，而不是互相覆盖 —— 两者不一致本身就是有价值的信息）。

    返回 dict(labels=[...], scores=[...], details=[...])
    维度不足时报 ValueError。
    """
    details = []
    seen = set()

    def add(items):
        for d in items:
            if d["label"] in seen:
                continue
            seen.add(d["label"])
            details.append(d)

    add(breakdown_dimensions(audit))
    add(coverage_dimensions(gap_records))

    if isinstance(overall, (int, float)):
        add([{
            "label": "综合匹配度",
            "score": round(float(overall), 1),
            "source": SRC_OVERALL,
            "reason": "该岗位的综合评分",
        }])

    if len(details) < min_dims:
        raise ValueError(
            f"可用维度只有 {len(details)} 个（需要 >= {min_dims}）——"
            f"不足以画雷达图。缺数据时宁可不出图，也不要填假数字。")

    return {
        "labels": [d["label"] for d in details],
        "scores": [d["score"] for d in details],
        "details": details,
    }


if __name__ == "__main__":
    # 自检：三种数据组合下的表现
    print("=" * 60)
    print("A. 模型三维度 + gap 统计 + 综合分（最完整）")
    print("=" * 60)
    p = build(
        audit={"score_breakdown": {
            "hard_skills": {"score": 58, "reason": "TS 缺失"},
            "project_depth": {"score": 52, "reason": "个人项目为主"},
            "domain_fit": {"score": 40, "reason": "无 PM 经验"}}},
        gap_records=[
            {"技能": "SQL", "状态": "已掌握", "优先级": "P3 - 巩固即可"},
            {"技能": "Python", "状态": "已掌握", "优先级": "P3 - 巩固即可"},
            {"技能": "AB实验", "状态": " 未掌握 (Gap)", "优先级": "P0 - 极其紧急"},
            {"技能": "用户调研", "状态": " 未掌握 (Gap)", "优先级": "P1 - 高优补充"},
        ],
        overall=52.0)
    for d in p["details"]:
        print("  %-14s %5.1f  [%s] %s" % (d["label"], d["score"],
                                          d["source"], d["reason"]))
    assert len(p["labels"]) == 6

    print()
    print("=" * 60)
    print("B. 只有 gap + 综合分（模型没给 breakdown）")
    print("=" * 60)
    p2 = build(gap_records=[
        {"技能": "A", "状态": "已掌握", "优先级": "P3"},
        {"技能": "B", "状态": "未掌握 (Gap)", "优先级": "P0"},
    ], overall=70)
    for d in p2["details"]:
        print("  %-14s %5.1f  [%s]" % (d["label"], d["score"], d["source"]))
    assert len(p2["labels"]) == 3

    print()
    print("=" * 60)
    print("C. 数据不足 -> 应当报错而不是画假图")
    print("=" * 60)
    try:
        build(overall=60)
        print("  FAIL：本应报错")
    except ValueError as e:
        print("  OK ->", e)

    print("\n能力画像自检通过 ✅")
