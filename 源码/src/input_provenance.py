"""
输入来源指纹（Input Provenance）

解决什么问题
------------
数据库原本只能说明"某个 trace 用了某个岗位名、产生了某个 gap report"，
但它回答不了这些真正影响可信度的问题：

  · 当时分析的是 `resume.md` 还是 `resume_v2.md`？
  · 文件后来被改过，旧报告对应哪个版本？
  · Agent A 和后续 Agent 用的是不是同一份内容？
  · 两次运行的输入是否完全一致？

本模块给"实际传给 Agent 的文本"算一个内容指纹，落进 `audit_json` 与
`agent_messages.payload_json` 的**保留字段**里 —— 不扩 schema、不存原文。

设计约束
--------
1. 指纹只用于识别**内容版本**，不代表内容真实可信；
2. 用 SHA-256（不用 Python 的 `hash()` —— 它跨进程不稳定，加盐后每次运行都不同）；
3. 哈希对象必须是**实际传给 Agent 的文本**（不是在磁盘上另读一遍）；
4. 不把绝对路径写进指纹（`logical_name` 一律取 basename）；
5. 不保存原始文本，日志与交接 payload 里也不重复放原文；
6. 相同内容 → 相同指纹；内容任一字符变化 → 指纹必然变化。

═══════════════════════════════════════════════════════════════════
 IMPORTANT —— 这个指纹**不能**证明什么
═══════════════════════════════════════════════════════════════════
哈希只证明"**这次**分析用的内容与**某次**记录的内容**逐字节相同**"。
它**不证明**：

  · 内容来源的权威性（谁写的、是不是本人真实简历）；
  · 内容真实性（有没有夸大、伪造）；
  · 文件在哈希之后没被改过（本模块不做签名、不做时间戳锚定）；
  · 分析与结论的正确性（同样的输入也可能得到不同结论）。

换句话说：**哈希是"同一性"证据，不是"真实性"证据**。
任何把它当成"简历已认证"的解读都是过度使用。
═══════════════════════════════════════════════════════════════════

零依赖、离线、确定性：只用 `hashlib` / `json` / `os`，不联网不调模型。
"""

import hashlib
import json
import os

# 允许的输入种类。新增种类时要同步考虑：bundle_id 的规范化格式是否需要调整。
VALID_KINDS = ("resume", "jd")

# bundle 结构的版本号。字段含义变化时才 +1，便于旧数据识别。
BUNDLE_SCHEMA_VERSION = 1

# audit_json 里的保留字段名。模型输出若同名会被本模块覆盖 ——
# 这是**有意的**：保留字段的语义由代码保证，不能交给模型自由发挥。
AUDIT_BUNDLE_KEY = "_input_bundle"


def _sha256_text(text):
    """对文本算 SHA-256（UTF-8 编码，十六进制小写）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_logical_name(logical_name, kind):
    """
    把逻辑名收敛成**不含目录**的文件名。

    要求"不把绝对路径写入数据库"，所以这里取 basename：
      `C:/Users/x/my_profile/resume.md` → `resume.md`
      `my_profile\\resume.md`            → `resume.md`

    Windows 上 `os.path.basename` 只认 `\\`，而 Git Bash / 配置里也可能出现 `/`，
    所以先统一分隔符再切，避免 `a/b\\c.md` 这类混合路径漏网。
    """
    if logical_name is None:
        raise ValueError(f"{kind}: logical_name 不能为空")

    normalized = str(logical_name).replace("\\", "/").strip()
    name = os.path.basename(normalized)
    if not name:
        raise ValueError(f"{kind}: logical_name 不能为空（原始值：{logical_name!r}）")
    return name


def build_source(kind, logical_name, text):
    """
    构造单个输入来源的指纹。

    参数
    ----
    kind         : "resume" 或 "jd"
    logical_name : 逻辑名（简历文件名 / 岗位名）。绝对路径会被收敛成 basename。
    text         : **实际传给 Agent 的文本**。空文本直接报错。

    返回
    ----
    {
        "source_id": "resume:<sha256>",   # kind 前缀让不同 kind 天然区分
        "kind": "resume",
        "logical_name": "resume_v2.md",
        "sha256": "<64 位十六进制>",
        "char_count": 1234,
    }

    注意 `source_id` 带 kind 前缀：即使简历与 JD 内容完全相同，
    两者的 source_id 也不会相同 —— 它们语义上是不同的输入。
    """
    if kind not in VALID_KINDS:
        raise ValueError(
            f"未知的来源类型 kind={kind!r}；只支持 {VALID_KINDS}")

    if text is None:
        raise ValueError(f"{kind}: text 不能为空（None）")
    if not isinstance(text, str):
        raise TypeError(f"{kind}: text 必须是 str，实际是 {type(text).__name__}")
    if not text.strip():
        raise ValueError(f"{kind}: text 不能是空文本（空白字符也不接受）")

    digest = _sha256_text(text)
    return {
        "source_id": f"{kind}:{digest}",
        "kind": kind,
        "logical_name": _safe_logical_name(logical_name, kind),
        "sha256": digest,
        "char_count": len(text),
    }


def _canonical_payload(sources):
    """
    bundle_id 的规范化输入：**只取内容指纹**，按固定顺序、紧凑 JSON。

    · `sort_keys=True`      —— 键序固定，不受 dict 插入顺序影响
    · `separators=(",", ":")` —— 去掉空格，消除格式化差异
    · `ensure_ascii=False`  —— 中文不会被转义成 \\uXXXX（此处只有 hex，无影响，但保持一致）
    · 只放 sha256       —— 逻辑名/路径不参与，所以"同内容不同文件名"仍是同一版本，
                              而"内容变了"必然改变 bundle_id
    """
    return json.dumps(
        {
            "resume": sources["resume"]["sha256"],
            "jd": sources["jd"]["sha256"],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def build_input_bundle(resume_text, jd_text, resume_name, job_name):
    """
    构造一次分析的输入组合指纹。

    参数
    ----
    resume_text : 实际传给 Agent A 的简历原文
    jd_text     : 实际传给 Agent A 的 JD 原文
    resume_name : 简历逻辑名（如 resume_v2.md）
    job_name    : 岗位逻辑名（JD 文件去扩展名，如 示例科技-数据开发工程师）

    返回
    ----
    {
        "schema_version": 1,
        "bundle_id": "bundle:<sha256>",
        "sources": {"resume": {...}, "jd": {...}},
    }

    **不包含**任何原文，也**不包含**绝对路径 —— 只有逻辑名、长度和哈希。
    """
    sources = {
        "resume": build_source("resume", resume_name, resume_text),
        "jd": build_source("jd", job_name, jd_text),
    }
    bundle_digest = _sha256_text(_canonical_payload(sources))
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "bundle_id": f"bundle:{bundle_digest}",
        "sources": sources,
    }


def attach_to_audit(audit, bundle):
    """
    把 bundle 挂进 audit 的**保留字段**，不改模型原始字段。

    返回一个新 dict（浅拷贝），避免就地修改调用方持有的对象。
    模型若自己输出了同名键 `_input_bundle`，会被这里覆盖 ——
    保留字段的语义必须由代码保证。
    """
    merged = dict(audit)
    merged[AUDIT_BUNDLE_KEY] = bundle
    return merged


def summarize(bundle):
    """
    一行摘要，供日志/CLI 打印。**只含哈希与逻辑名，不含原文。**

    例：`resume_v2.md(39cef1…) + 示例科技-数据开发工程师(7a02bd…) → bundle:1f3c9d…`
    """
    if not bundle:
        return "(无输入指纹)"

    def _short(source):
        return f"{source['logical_name']}({source['sha256'][:6]}…)"

    sources = bundle.get("sources") or {}
    return (f"{_short(sources['resume'])} + {_short(sources['jd'])} "
            f"→ {bundle['bundle_id'][:15]}…")
