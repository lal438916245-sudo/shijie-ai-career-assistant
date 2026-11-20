"""
简历空泛声明扫描器（纯规则，零依赖，零 token 成本）

为什么单独成一个模块
--------------------
「简历里出现熟悉 / 了解 / 掌握 / 精通，却没给量化或机制说明」这件事，
**判定标准是确定的，不该交给大模型**。

把它做成纯规则有三个好处：
  1. 零依赖、零成本 —— 不需要 API Key 就能跑
  2. 结果可复现 —— 同一份简历永远扫出同样的结果
  3. 大模型只负责"怎么问"，不负责"该不该问"

90% 的简历被打穿，都发生在这几个词后面。

单独运行
--------
python resume_scan.py my_profile/resume.md
"""

import re
import sys

# 触发词：简历里最容易被追问到底的几个词
TRIGGER_WORDS = ["熟悉", "了解", "掌握", "精通", "熟练", "有经验", "参与过"]

# 命中这些模式 -> 说明给了量化结果，可以不深挖
#
# 注意：这里刻意**不**使用裸的 `\d{3,}`。
# 因为「2024 年实习」里的年份会被误判成量化证据，导致真正空泛的声明被漏掉。
# 只认带单位/语义的数字。
QUANTIFY_MARKERS = [
    r"\d+\s*%",                              # 30%
    r"\d+\s*倍",                             # 3 倍
    r"\d+\s*[wW万]",                         # 10万
    r"\d+\s*[qQ][pP][sS]",                   # 5000QPS
    r"\d+\s*ms",                             # 50ms
    r"\d+\s*[kK](?![a-zA-Z])",               # 100K
    r"\d+\s*(?:次|条|个|台|人|篇|项|行|张|款|名)",  # 10万次 / 3个项目
    r"从\s*\d+\s*[到至]\s*\d+",               # 从 100 到 1000
]

# 命中这些词 -> 说明解释了实现机制，可以不深挖
MECHANISM_MARKERS = [
    "因为", "原因是", "原理", "通过", "基于", "采用", "实现方式", "底层",
    "源码", "机制", "架构", "方案", "对比", "而非", "而不是", "权衡",
]


def scan_vague_claims(resume_text):
    """
    找出"声称会、但没给证据"的条目。

    判定：句子命中触发词，且既没有量化、也没有机制说明。

    三条预处理规则（都源于实战踩坑）：
      · 跳过引用块（`>` 开头）—— 那是模板里的说明文字，不是简历声明。
        不跳过的话，模板自己的提示语会被误判成可疑条目。
      · 去掉项目符号和编号，让输出的 claim 干净可读。
      · **判定时忽略引号内的内容** —— 引号里通常是"被引述的词"而不是自我声称。
        真实误报案例：简历里描述本模块的那句
        「区分『有量化证据的声明』与『空泛声明』（如"熟悉/掌握"但无数据支撑）」
        因为出现了"熟悉/掌握"被判为空泛声明 —— 可它恰恰是在**说明怎么抓空泛声明**。

    长度门槛设为 4（触发词本身 2 字 + 至少 1 字技能名）。
    早期设为 6，导致「熟悉 Go」这类短但有效的声明被误杀 —— 实测漏报过。

    返回 [{"claim": 原句, "trigger": 命中的触发词, "reason": 为什么可疑}, ...]
    """
    findings = []

    # 成对的引号：命中判定在这段被剔除后的文本上做，输出仍用原句
    QUOTED = re.compile(r"(?:「[^」]*」|『[^』]*』|“[^”]*”|\"[^\"]*\")")

    for raw_line in resume_text.splitlines():
        line = raw_line.strip()

        # 跳过空行与引用块（模板说明文字）
        if not line or line.startswith(">"):
            continue

        # 再按句末标点切句
        for raw in re.split(r"[。；;]+", line):
            s = raw.strip()
            s = re.sub(r"^[-*\u2022]+\s*", "", s)      # 去掉项目符号
            s = re.sub(r"^\d+[.、)]\s*", "", s)         # 去掉编号
            s = s.strip()

            if not s or len(s) < 4:
                continue

            probe = QUOTED.sub("", s).strip()
            if not probe:
                continue

            # 一句话里可能有多个触发词，全部记下来（早期只取第一个，信息有损）
            hits = [w for w in TRIGGER_WORDS if w in probe]
            if not hits:
                continue

            has_quant = any(re.search(p, probe) for p in QUANTIFY_MARKERS)
            has_mech = any(m in probe for m in MECHANISM_MARKERS)

            if not has_quant and not has_mech:
                joined = "、".join(hits)
                findings.append({
                    "claim": s,
                    "trigger": joined,
                    "reason": f"用了「{joined}」但没有量化结果，也没有解释实现机制",
                })

    return findings


def format_findings(findings):
    """把扫描结果格式化成可打印的字符串。"""
    if not findings:
        return "未发现明显空泛的声明。"

    lines = []
    for i, f in enumerate(findings, 1):
        lines.append(f"[{i}] 命中「{f['trigger']}」")
        lines.append(f"    {f['claim']}")
        lines.append(f"    -> {f['reason']}")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python resume_scan.py <简历文件路径>")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as fp:
        content = fp.read()

    results = scan_vague_claims(content)
    print(f"\n扫描完成，命中 {len(results)} 条可疑声明：\n")
    print(format_findings(results))
    print()
