"""
复测建议：基于「每题最近一次证据」的**纯规则**判断。

边界（写死在这里，不要越界）
--------------------------
· 不查数据库：输入只有 `profile["current"]["items"]`，不碰历史 attempts；
· 不调用模型：没有"让 AI 判断该不该复测"这回事；
· 不生成新题、不安排时间、不执行复测、不改 gap 状态；
· 只回答一个问题：**按当前证据，哪些题建议重做、哪些需要人工看一眼**。

为什么只吃 latest items
-----------------------
`assessment_profile` 已经按题取了最近一次。策略若自己再扫历史，就会出现
"这道题上次 40、这次 85，仍然被建议复测" —— 也就是把**已经解决**的问题
重新排进待办。历史只用于展示趋势，不参与决策。

candidates 与 review_required
-----------------------------
| 情况 | 归属 |
|---|---|
| 分数 < 及格线，且来源是正式 rubric 加权 | `candidates`（可自动排复测） |
| 分数 < 及格线，但来源是 `model_fallback` | `review_required`（人工看一眼） |
| 分数 < 及格线，来源未知 / 不认识 | `review_required` |
| 分数 < 及格线，但缺 task_id / attempt_id 等定位字段 | `review_required` |
| 分数 >= 及格线 | 不推荐 |
| 没有有效分数 | 不推荐（记 diagnostics，不当成"不及格"） |

`model_fallback` 为什么不能直接驱动自动复测：它是在**没有 rubric 明细**时
退回模型自报的总分。模型给个 55 分不代表这题真的没掌握，可能只是它没有
打分依据；拿它去排复测，等于用一个不可核对的数字驱动学习计划。
"""

from assessment_rules import (PASS_SCORE, coerce_score, id_sort_key,
                              is_passing)

# 只有这些来源被视为"可自动采信的正式阅卷"
TRUSTED_SOURCES = ("rubric_weighted",)

# 形成正式候选所需的最小定位字段
REQUIRED_FIELDS = ("task_id", "attempt_id")


def _copy_item(item, reason, kind):
    """从输入 item 复制出建议条目（不修改原对象）。"""
    gaps = item.get("gap_ids")
    gaps_out = list(gaps) if isinstance(gaps, list) else gaps
    return {
        "task_id": item.get("task_id"),
        "attempt_id": item.get("attempt_id"),
        "attempt_no": item.get("attempt_no"),
        "score": coerce_score(item.get("score")),
        "score_source": item.get("score_source"),
        "question_text": item.get("question_text"),
        "task_content": item.get("task_content"),
        "gap_ids": gaps_out,
        "reason": reason,
        "kind": kind,
    }


def _sort_key(entry):
    """
    稳定排序：分数升序 → task_id → attempt_id。

    混合类型（int / str / None）由 `id_sort_key` 统一处理，不会 TypeError，
    也不会把 `None` 改写成 0。
    """
    score = entry.get("score")
    return (score if score is not None else 0.0,
            id_sort_key(entry.get("task_id")),
            id_sort_key(entry.get("attempt_id")))


def recommend(profile):
    """
    根据当前画像给出复测建议。纯函数：同一输入必得同一输出。

    参数
    ----
    profile : assessment_profile.profile_for_plan() 的返回值（或其等价 dict）

    返回
    ----
    {
      "pass_score": 60,
      "candidates": [...],       # 正式复测候选（可自动排）
      "review_required": [...],  # 需人工复核（不自动执行）
      "diagnostics": {...},
    }

    `current.items` 缺失或为空时安全返回空结果 —— 不猜、不造。
    """
    current = (profile or {}).get("current") or {}
    items = current.get("items") or []

    candidates = []
    review = []
    diagnostics = {
        "total_items": len(items),
        "pass_score": PASS_SCORE,
        "passing": 0,
        "below_pass": 0,
        "candidates": 0,
        "review_required": 0,
        "skipped_invalid_score_ids": [],
        "unknown_source_ids": [],
        "unusable_item_ids": [],
    }

    for item in items:
        if not isinstance(item, dict):
            diagnostics["unusable_item_ids"].append(None)
            continue

        score = coerce_score(item.get("score"))
        if score is None:
            # 没有可用分数 ≠ 不及格。记诊断，不推荐。
            diagnostics["skipped_invalid_score_ids"].append(item.get("attempt_id"))
            continue

        if is_passing(score):
            diagnostics["passing"] += 1
            continue

        diagnostics["below_pass"] += 1
        source = item.get("score_source")

        # 缺少定位字段 → 无法安全形成正式候选
        missing = [f for f in REQUIRED_FIELDS if item.get(f) is None]
        if missing:
            diagnostics["unusable_item_ids"].append(item.get("attempt_id"))
            review.append(_copy_item(
                item,
                f"证据缺少定位字段（{'、'.join(missing)}），无法安全排入自动复测",
                "unusable_evidence"))
            continue

        if source in TRUSTED_SOURCES:
            candidates.append(_copy_item(
                item,
                f"最近一次 {score:g} 分，低于及格线 {PASS_SCORE} 分"
                f"（来源：正式 rubric 加权阅卷）",
                "rubric_below_pass"))
        elif source == "model_fallback":
            review.append(_copy_item(
                item,
                f"最近一次 {score:g} 分，但来自模型自报兜底（无 rubric 明细），"
                "不足以作为自动复测依据",
                "model_fallback"))
        else:
            diagnostics["unknown_source_ids"].append(item.get("attempt_id"))
            review.append(_copy_item(
                item,
                f"最近一次 {score:g} 分，但评分来源未知（{source!r}），需人工确认",
                "unknown_source"))

    candidates.sort(key=_sort_key)
    review.sort(key=_sort_key)
    diagnostics["candidates"] = len(candidates)
    diagnostics["review_required"] = len(review)
    diagnostics["skipped_invalid_score_ids"].sort(key=id_sort_key)
    diagnostics["unknown_source_ids"].sort(key=id_sort_key)
    diagnostics["unusable_item_ids"].sort(key=id_sort_key)

    return {
        "pass_score": PASS_SCORE,
        "candidates": candidates,
        "review_required": review,
        "diagnostics": diagnostics,
    }
