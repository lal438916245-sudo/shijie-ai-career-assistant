"""
共享的「及格」规则 —— 全项目只此一处定义阈值。

为什么需要它
------------
`60` 这个数字原本散落在三处：Agent C 判 completed/failed、脚本统计"未通过"、
报告着色。任何一处改动都会让"及格"在不同地方含义不同 —— 同一份数据，
阅卷记为 failed、复测建议却认为已经通过，用户看到的是自相矛盾的结论。

这里把阈值和判定收敛成一个纯函数，让**阅卷**、**复测建议**、**导出**都用同一把尺子。

边界
----
· `60` 恰好算及格（>=）；
· `bool` 不是分数（`True` 会被当成 1 分，必须排除）；
· 非数值、负数、超过 100 一律**不是有效分数**，`is_passing` 返回 False，
  但调用方应当先用 `coerce_score` 判断"有没有分"，不要把"没有分"当成"不及格"。
"""

import math

PASS_SCORE = 60

MIN_SCORE = 0
MAX_SCORE = 100


def coerce_score(value):
    """
    把分数规范成 float；不是合理分数就返回 None。

    注意：`None` 表示"没有可用分数"，与 0（考得极差）语义完全不同，
    调用方必须分开处理。
    """
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    v = float(value)
    # NaN / ±inf 必须显式拒绝：NaN 与任何数比较都是 False，
    # 所以 `v < 0 or v > 100` 对它**恒为假**，会一路被当成合法分数。
    if not math.isfinite(v):
        return None
    if v < MIN_SCORE or v > MAX_SCORE:
        return None
    return v


def is_valid_score(value):
    """是否存在一个可用于判定的分数。"""
    return coerce_score(value) is not None


def is_passing(score):
    """
    分数是否达到及格线。

    · 恰好 60 → True；
    · 无效分数（None / bool / 越界 / 非数值）→ False。
      它们不该被当成"不及格"，调用方应先 `is_valid_score()` 分流。
    """
    v = coerce_score(score)
    if v is None:
        return False
    return v >= PASS_SCORE


def describe_threshold():
    """给文案用的一句话（避免各处手写 '60 分及格'）。"""
    return f"{PASS_SCORE} 分及格"


def id_sort_key(value):
    """
    给可能混合类型的 id 排序（int / str / None）。

    排序**不等于**身份：这里只决定"谁排在前面"，绝不能拿它的返回值判断
    "是不是同一个 id"。身份判断要用原始值或完整选择键（见 assessment_profile）。

        int  → (0, 数值, "")
        str  → (1, 0, 字符串)
        None → (2, 0, "")

    为什么不直接 `sorted()`：`[1, "2", None]` 在 Python 3 会 `TypeError`。
    为什么不把 `None` 换成 0：那会把"未知 id"伪装成真实 id。
    """
    if isinstance(value, bool):
        return (1, 0, str(value))
    if isinstance(value, int):
        return (0, value, "")
    if value is None:
        return (2, 0, "")
    return (1, 0, str(value))
