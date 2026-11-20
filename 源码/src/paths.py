"""
项目路径集中管理。

所有路径都以**项目根**为基准，而不是当前工作目录（CWD）。
这样从任何目录运行都不会找错文件。

用法
----
    import paths
    db = DBManager(paths.DB_PATH)
    src = paths.data_file("jobs_mock.xlsx")
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- 数据库 ----
DB_PATH    = os.path.join(ROOT, "career_agent.db")
BACKUP_DIR = os.path.join(ROOT, "backups")

# ---- 数据与知识库 ----
DATA_DIR      = os.path.join(ROOT, "data")
KNOWLEDGE_DIR = os.path.join(ROOT, "knowledge_base")
CHROMA_DIR    = os.path.join(ROOT, "chroma_db_storage")

# ---- 个人资料 ----
PROFILE_DIR         = os.path.join(ROOT, "my_profile")
EXAMPLE_PROFILE_DIR = os.path.join(ROOT, "my_profile.example")

# ---- 演示资料（--demo 用） ----
# 内置的脱敏示例简历 + 示例 JD，让用户零配置先看到效果。
# 演示**产出**不写回这里（那是仓库里的只读样例），而是复制到
# `my_profile/_demo/`（已被 .gitignore 覆盖），避免弄脏仓库。
DEMO_PROFILE_DIR    = os.path.join(ROOT, "examples", "demo_profile")
DEMO_REPLAY_DIR     = os.path.join(ROOT, "examples", "demo_replay")

# ---- 比赛 UI 本地运行状态（不进入仓库） ----
RUNTIME_DIR         = os.path.join(ROOT, "runtime")

# ---- 文档与样例 ----
DOCS_DIR     = os.path.join(ROOT, "docs")
EXAMPLES_DIR = os.path.join(ROOT, "examples")


def data_file(name):
    """取 data/ 下的文件完整路径，例如 data_file("jobs_mock.xlsx")。"""
    return os.path.join(DATA_DIR, name)
