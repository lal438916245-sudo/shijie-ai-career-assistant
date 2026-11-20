"""
LLM 输出的 JSON 解析工具。

三层能力
--------
1. `extract_json_from_text`  —— 从夹带 markdown 废话的输出里抠出 JSON（原有能力，迁到此处）
2. `salvage_truncated_json`  —— 输出被 max_tokens 截断时，抢救出已完成的部分
3. `parse_llm_json`          —— 先正常解析，失败则抢救，并告诉调用方是否降级

为什么必须有"抢救"
------------------
推理模型的 `reasoning_tokens` 会吃掉 `max_tokens` 的绝大部分。实测某次
Agent D 调用：`completion_tokens=16001`，其中 `reasoning_tokens=12934` ——
只剩约 3,000 给正文，于是 JSON 在数组中间被硬截断。

**扩容能缓解但不能根治**：推理量会跟着预算一起涨（实测 8000 → 13000 → 16000
三次全部截断）。更糟的是，其中一次 `正文=0` —— 整个预算全被推理吃光。

所以需要一层兜底：截断时丢掉最后一个不完整的元素，把剩下的解析出来。
把「全丢」变成「丢一点」，45,000 token 的浪费就不会再发生。
"""

import json
import re


def extract_json_from_text(text: str) -> dict:
    """
    从大模型输出里抠出 JSON：用正则剥掉 markdown 符号与前后废话。

    要求 JSON 必须**完整**。若内容被截断，这里会抛错 ——
    此时应改用 `salvage_truncated_json()` 或 `parse_llm_json()`。
    """
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError("未能在大模型输出中找到 JSON 结构！")

    json_str = match.group(0)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 格式错误: {e}\n提取到的文本: {json_str}")


def salvage_truncated_json(text: str) -> dict:
    """
    从**被截断**的 JSON 里抢救出已完成的部分。

    策略：扫描文本，记录两个"安全截断点"，从优到次尝试：
      1. 最后一次有容器闭合的位置（`}` / `]` 之后）—— 最安全，丢掉的只是尾部
      2. 顶层的最后一个逗号 —— 丢掉的只是最后一个键值对

    在截断点切断，再把尚未闭合的容器补上，然后尝试解析。

    抛 ValueError 表示确实救不回来（截断位置太靠前）。
    """
    start = text.find("{")
    if start < 0:
        raise ValueError("找不到 JSON 起始的 '{'")
    s = text[start:]

    stack = []                      # 待闭合的符号，如 ["}", "]"]
    in_str = False
    esc = False

    close_pos, close_stack = None, None      # 安全点 1：容器刚闭合处
    comma_pos, comma_stack = None, None      # 安全点 2：顶层逗号处

    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if not stack:
                continue
            stack.pop()
            if not stack:
                # 顶层容器已经闭合 —— 其实内容是完整的
                return json.loads(s[:i + 1])
            close_pos, close_stack = i + 1, list(stack)
        elif ch == "," and len(stack) == 1:
            comma_pos, comma_stack = i, list(stack)

    for pos, st in ((close_pos, close_stack), (comma_pos, comma_stack)):
        if pos is None:
            continue
        try:
            return json.loads(s[:pos] + "".join(reversed(st)))
        except Exception:
            continue

    raise ValueError("截断位置太靠前，无法抢救")


def parse_llm_json(text: str):
    """
    解析大模型返回的 JSON，带截断兜底。

    返回 (data, degraded)
        degraded=False —— 完整解析成功
        degraded=True  —— 内容被截断，返回的是抢救出来的**部分结果**
                          （调用方应提示用户"本次结果可能不完整"）
    两条路都失败时抛 ValueError。

    ⚠ **必须解包**：`data, degraded = parse_llm_json(raw)`
    这个返回值是二元组，不是 dict。曾经有调用方写成
    `data = parse_llm_json(raw)` 再 `data.get("questions")`，
    又用 `isinstance(data, dict)` 兜了一下，结果把解包错误吞成了
    "模型没有返回 questions 数组" —— 白排查了半天，其实是自己的 bug。
    """
    try:
        return extract_json_from_text(text), False
    except ValueError:
        pass

    try:
        return salvage_truncated_json(text), True
    except Exception as e:
        raise ValueError(f"JSON 解析失败，且截断抢救也失败：{e}")
