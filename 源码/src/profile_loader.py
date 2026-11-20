"""
个人资料输入接口（Profile Loader）

职责
----
把「我的简历 / 我的理想岗位 / 我的偏好条件」读成结构化对象，供各 Agent 消费。

设计原则
--------
1. 真实数据放 `my_profile/`（已在 .gitignore 中），**不会进仓库**
2. 仓库里只保留 `my_profile.example/` 模板
3. 全程只读，不修改用户的任何文件

目录约定
--------
my_profile/
├── resume.md          # 简历原文（Markdown / 纯文本均可）
├── preferences.md     # 城市 / 薪资 / 学历 / 期望方向（可选）
└── jobs/
    ├── 腾讯-数据挖掘专家.md
    └── 字节-推荐算法工程师.md

文件名即岗位名，一个岗位一个文件。
"""

import os
import shutil

import paths

PROFILE_DIR = paths.PROFILE_DIR
EXAMPLE_DIR = paths.EXAMPLE_PROFILE_DIR
DEMO_SRC_DIR = paths.DEMO_PROFILE_DIR

# 演示模式的**工作目录**：demo 产出（报告 / 对练记录）写在这里，
# 而不是写回仓库里的 examples/demo_profile/。
# 放在 my_profile/ 之下，天然被 .gitignore 覆盖，不会弄脏仓库。
DEMO_WORK_DIR = os.path.join(PROFILE_DIR, "_demo")


# ============================================================
# 基础工具
# ============================================================

def _read(path):
    """读文本文件，统一 UTF-8。文件不存在返回 None。"""
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _jobs_dir(root=PROFILE_DIR):
    return os.path.join(root, "jobs")


def ensure_profile(root=PROFILE_DIR):
    """
    确保 profile 目录存在。不存在则从 example 复制一份并提示用户去填。
    返回 True 表示是本次新建的（调用方可以据此中断主流程）。
    """
    if os.path.isdir(root):
        return False

    if not os.path.isdir(EXAMPLE_DIR):
        raise FileNotFoundError(
            f"既没有 {root}/ 也没有模板目录 {EXAMPLE_DIR}/，无法初始化个人资料。"
        )

    shutil.copytree(EXAMPLE_DIR, root)
    print(f"[Profile] 已从模板创建 {root}/，请先填入你的真实资料后再运行。")
    return True


# ============================================================
# 演示模式（--demo）
# ============================================================

def prepare_demo(root=None, src=None):
    """
    把内置的脱敏演示资料复制到一个**可写**的工作目录，返回该目录路径。

    为什么要复制而不是直接读 `examples/demo_profile/`
    --------------------------------------------------
    跑 demo 时各脚本会把报告 / 对练记录写进 profile 目录。如果直接对着
    仓库里的样例目录写，一次 demo 就会弄脏 git 工作区 —— 这对"发布"是灾难。

    所以：**只读的样例放仓库（examples/demo_profile/），
    可写的产出放 my_profile/_demo/（已被 .gitignore 覆盖）**。

    幂等：已存在就直接复用，不覆盖用户上次的 demo 产出。

    注意：root / src 用 None 而不是把模块常量写成默认参数 ——
    默认参数在**定义时**求值，写成 `root=DEMO_WORK_DIR` 会让这个常量
    无法被测试替换（monkeypatch 改不动已经绑定的默认值）。
    """
    root = root or DEMO_WORK_DIR
    src = src or DEMO_SRC_DIR

    if not os.path.isdir(src):
        raise FileNotFoundError(f"演示资料目录不存在：{src}")

    if not os.path.isdir(root):
        shutil.copytree(src, root)
        print(f"[Demo] 已准备演示资料 → {root}/（内置脱敏示例，无需你自己填）")
    else:
        print(f"[Demo] 复用已有演示目录 → {root}/")
    return root


def resolve_profile_dir(profile=None, demo=False):
    """
    统一的 profile 目录解析：`--demo` 优先于 `--profile`。

    各入口脚本解析完参数后调一次即可，避免每个脚本各写一遍演示逻辑：
        args.profile = pl.resolve_profile_dir(args.profile, args.demo)
    """
    if demo:
        return prepare_demo()
    return profile or PROFILE_DIR


# ============================================================
# 简历
# ============================================================

def load_resume(root=PROFILE_DIR, filename="resume.md"):
    """
    读简历原文。返回 str；缺失则抛错（简历是必需的）。

    filename: 简历文件名，默认 resume.md。
              保留历史版本时（如 resume_v2.md）可显式指定。
    """
    text = _read(os.path.join(root, filename))
    if not text:
        raise FileNotFoundError(
            f"找不到简历：{root}/{filename}\n"
            f"请把你的简历内容填进去（Markdown 或纯文本都可以）。"
        )
    return text


# ============================================================
# 理想岗位
# ============================================================

def list_jobs(root=PROFILE_DIR):
    """
    列出所有理想岗位。
    返回 [{"name": 文件名去扩展, "path": 完整路径, "text": JD 原文}, ...]
    """
    d = _jobs_dir(root)
    if not os.path.isdir(d):
        return []

    jobs = []
    for fn in sorted(os.listdir(d)):
        if not fn.lower().endswith((".md", ".txt")):
            continue
        path = os.path.join(d, fn)
        text = _read(path)
        if not text:
            continue
        jobs.append({
            "name": os.path.splitext(fn)[0],
            "path": path,
            "text": text,
        })
    return jobs


def load_job(key=None, root=PROFILE_DIR):
    """
    按岗位名（或序号）取一个岗位。
    返回 (name, jd_text)。key 为 None 时取第一个。
    """
    jobs = list_jobs(root)
    if not jobs:
        raise FileNotFoundError(
            f"{_jobs_dir(root)}/ 下没有任何岗位文件。\n"
            f"每个理想岗位建一个 .md 文件，把你的 JD 原文粘进去即可。"
        )

    if key is None:
        return jobs[0]["name"], jobs[0]["text"]

    # 支持传序号
    key = str(key).strip()
    if key.isdigit():
        idx = int(key) - 1
        if 0 <= idx < len(jobs):
            return jobs[idx]["name"], jobs[idx]["text"]
        raise IndexError(f"岗位序号 {key} 超出范围（共 {len(jobs)} 个）")

    # 支持按名称模糊匹配
    for j in jobs:
        if j["name"] == key:
            return j["name"], j["text"]
    for j in jobs:
        if key in j["name"]:
            return j["name"], j["text"]

    names = "、".join(j["name"] for j in jobs)
    raise KeyError(f"找不到岗位「{key}」。可选：{names}")


# ============================================================
# 偏好条件（城市 / 薪资 / 学历 / 期望方向）
# ============================================================

def load_preferences(root=PROFILE_DIR):
    """
    读偏好条件。格式为简单的 `key: value` 每行一条，返回 dict。
    文件不存在、或全部未填写时返回空 dict（偏好是可选的）。

    与 resume_scan 同一条原则：跳过 `#` 注释与 `>` 引用块
    —— 那是模板里的说明文字，不是用户的配置。
    值为空的项也一并丢弃，避免"填了字段但内容为空"被当成已配置。
    """
    text = _read(os.path.join(root, "preferences.md"))
    if not text:
        return {}

    prefs = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(">"):
            continue

        line = line.lstrip("-").strip()
        if ":" not in line and "：" not in line:
            continue

        for sep in (":", "："):
            if sep in line:
                k, v = line.split(sep, 1)
                k, v = k.strip(), v.strip()
                if k and v:
                    prefs[k] = v
                break
    return prefs


# ============================================================
# 状态自检
# ============================================================

def profile_status(root=PROFILE_DIR):
    """打印个人资料准备情况，供排错和首次运行时自检。"""
    print(f"\n{'=' * 56}")
    print(f"  个人资料状态：{root}/")
    print(f"{'=' * 56}")

    if not os.path.isdir(root):
        print("  [X] 目录不存在。运行 ensure_profile() 可从模板创建。")
        return

    resume = _read(os.path.join(root, "resume.md"))
    if resume:
        print(f"  [OK] 简历          {len(resume)} 字")
    else:
        print("  [X ] 简历          缺失（必需）")

    jobs = list_jobs(root)
    if jobs:
        print(f"  [OK] 理想岗位      {len(jobs)} 个")
        for j in jobs:
            print(f"         - {j['name']}  ({len(j['text'])} 字)")
    else:
        print("  [X ] 理想岗位      缺失（跑匹配类流程时必需）")

    prefs = load_preferences(root)
    if prefs:
        print(f"  [OK] 偏好条件      {len(prefs)} 项")
        for k, v in prefs.items():
            print(f"         - {k}: {v}")
    else:
        print("  [--] 偏好条件      未填写（可选）")

    print()


# ============================================================
# 自测
# ============================================================

if __name__ == "__main__":
    if ensure_profile():
        print("已创建模板，请填入资料后重新运行。")
    else:
        profile_status()
