"""
证据聚合层（Evidence Layer）

为什么单独成一个模块
--------------------
"证据驱动"是这个项目的核心原则，但此前它只是一句设计口号 ——
证据散落在两个地方，而且没有任何一个模块把它们统一起来：

  1. Agent A 的 gap 报告   -> 数据库 `job_gap_reports.audit_json`
  2. Agent E 的对练漏洞     -> `my_profile/sessions/*.json` 的 `vulnerabilities`

Agent D（简历改写）必须同时吃到这两类证据，才能做到"无证据不给改写建议"。
Agent E（面试官）也需要第一类作为三来源题库之一。

把这段逻辑抽到这里，是让"证据驱动"从口号变成一个**可复用的架构组件**。
"""

import json
import os

from paths import PROFILE_DIR
from contracts import normalize_vulnerability


# ============================================================
# 证据来源 1：Agent A 的 gap 报告
# ============================================================

_GAP_COLS = ["report_id", "trace_id", "company", "title", "tis_score",
             "gap_table_json", "audit_json"]


def load_gap_audit(trace_id=None, job_name=None, profile_dir=None, quiet=False):
    """
    从数据库取 Agent A 产出的 gap 报告（含 invisible_gaps）。

    取值顺序
    --------
    1. trace_id 显式指定
    2. 用 job_name 与 job_gap_reports.title 互相包含做模糊匹配

    取不到返回 None。注意：手贴进 my_profile/jobs/ 的 JD 若没跑过
    `run_hunter.py`，这里是取不到报告的。
    """
    try:
        from db_manager import DBManager
    except Exception as e:
        if not quiet:
            print(f"[证据] 无法导入 DBManager：{e}")
        return None

    try:
        db = DBManager()
    except Exception as e:
        if not quiet:
            print(f"[证据] 无法连接数据库：{e}")
        return None

    try:
        row = None
        if trace_id:
            row = db.get_gap_report_by_trace(trace_id)
        elif job_name:
            db.cursor.execute(
                "SELECT report_id, trace_id, company, title, tis_score, "
                "gap_table_json, audit_json FROM job_gap_reports "
                "ORDER BY created_at DESC")
            for r in db.cursor.fetchall():
                title = r[3] or ""
                if title and (title in job_name or job_name in title):
                    row = dict(zip(_GAP_COLS, r))
                    break

        if not row:
            if not quiet:
                print("[证据] 未找到匹配的 gap 报告（该岗位还没跑过 run_hunter.py）")
            return None

        audit = json.loads(row.get("audit_json") or "{}")
        if not quiet:
            print(f"[证据] 已接入 Agent A 的 gap 报告：{row.get('title')}"
                  f"（{row.get('trace_id')}，匹配度 {row.get('tis_score')}）")
        return audit
    except Exception as e:
        if not quiet:
            print(f"[证据] 读取 gap 报告失败：{e}")
        return None
    finally:
        try:
            db.close()
        except Exception:
            pass


# ============================================================
# 证据来源 2：Agent E 的对练漏洞
# ============================================================

def list_sessions(profile_dir=None):
    """列出所有对练记录（按时间倒序），返回 [{"path","data"}, ...]。"""
    root = profile_dir or PROFILE_DIR
    sess_dir = os.path.join(root, "sessions")
    if not os.path.isdir(sess_dir):
        return []

    out = []
    for fn in sorted(os.listdir(sess_dir), reverse=True):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(sess_dir, fn)
        try:
            with open(path, "r", encoding="utf-8") as fp:
                out.append({"path": path, "data": json.load(fp)})
        except Exception:
            continue
    return out


def _normalize_vuln_list(raw_list):
    """
    统一漏洞形态。

    历史数据是自由文本、新数据是结构化对象，这里一律归一化 ——
    否则下游（Agent D / 复测）要为两种格式各写一份分支。
    """
    out = []
    for x in (raw_list or []):
        v = normalize_vulnerability(x)
        if v:
            out.append(v)
    return out


def _vulns_from_messages(job_name=None, quiet=False):
    """
    从数据库交接表读 Agent E → Agent D 的记录。

    这条渠道比读 JSON 文件更符合架构：A→B、B→C 都走 agent_messages，
    E→D 也走同一张表，"对抗闭环"才在数据层真实存在。
    """
    try:
        from db_manager import DBManager
    except Exception:
        return [], None

    try:
        db = DBManager()
    except Exception:
        return [], None

    try:
        cur = db.cursor
        cur.execute(
            "SELECT trace_id, payload_json, created_at FROM agent_messages "
            "WHERE from_agent = 'Agent_E' AND to_agent = 'Agent_D' "
            "ORDER BY id DESC LIMIT 20")
        for trace_id, payload_json, created_at in cur.fetchall():
            try:
                payload = json.loads(payload_json or "{}")
            except Exception:
                continue
            # 复测记录（type=retest）没有漏洞清单，跳过
            if payload.get("type") == "retest":
                continue
            job = payload.get("job") or ""
            if job_name and job and not (job_name in job or job in job_name):
                continue
            vulns = _normalize_vuln_list(payload.get("vulnerabilities"))
            if not vulns:
                continue
            meta = {
                "job": job,
                "persona": payload.get("persona"),
                "overall_verdict": payload.get("overall_verdict"),
                "created_at": created_at,
                "trace_id": trace_id,
                "session": payload.get("session"),
                "source": "agent_messages",
            }
            if not quiet:
                print(f"[证据] 已接入 Agent E 的对练记录（数据库交接）：{job}"
                      f"（漏洞 {len(vulns)} 条，trace={trace_id}）")
            return vulns, meta
    except Exception as e:
        if not quiet:
            print(f"[证据] 读取交接记录失败：{e}")
    finally:
        try:
            db.close()
        except Exception:
            pass
    return [], None


def _vulns_from_sessions(job_name=None, profile_dir=None, quiet=False):
    """从 my_profile/sessions/*.json 读（历史数据 / 数据库不可用时的兜底）。"""
    sessions = list_sessions(profile_dir)
    for item in sessions:
        data = item["data"]
        job = data.get("job") or ""
        if job_name and job and not (job_name in job or job in job_name):
            continue
        vulns = _normalize_vuln_list(data.get("vulnerabilities"))
        if not vulns:
            continue
        meta = {
            "job": job,
            "persona": data.get("persona"),
            "overall_verdict": data.get("overall_verdict"),
            "created_at": data.get("created_at"),
            "trace_id": data.get("trace_id"),
            "path": item["path"],
            "source": "sessions_json",
        }
        if not quiet:
            print(f"[证据] 已接入 Agent E 的对练记录（本地文件）：{job}"
                  f"（{meta['created_at']}，漏洞 {len(vulns)} 条）")
        return vulns, meta

    # 「没有记录」和「有记录但没挖出漏洞」是两件事，提示必须分开 ——
    # 否则用户会以为简历很干净，而真相可能是对练时题目被跳过了。
    if not quiet:
        if sessions:
            print(f"[证据] 有 {len(sessions)} 次对练记录，但都没有挖出漏洞"
                  f"（多半是作答被跳过了）")
        else:
            print("[证据] 未找到对练记录（先跑 run_interview.py）")
    return [], None


def load_interview_vulnerabilities(job_name=None, profile_dir=None, quiet=False):
    """
    取 Agent E 挖出的漏洞。

    取值顺序（新渠道优先）：
      1. `agent_messages` 里 Agent_E → Agent_D 的交接记录
      2. `my_profile/sessions/*.json` 文件

    返回 (vulnerabilities, session_meta)。漏洞统一为结构化 dict：
      {"detail", "claim_ref", "severity", "evidence_kind", "structured"}
    """
    vulns, meta = _vulns_from_messages(job_name=job_name, quiet=quiet)
    if vulns:
        return vulns, meta
    return _vulns_from_sessions(job_name=job_name, profile_dir=profile_dir,
                                quiet=quiet)


# ============================================================
# 聚合入口
# ============================================================

def collect(job_name=None, trace_id=None, profile_dir=None, quiet=False):
    """
    一次性收齐某个岗位的全部证据。

    返回 dict：
        {"job": 岗位名, "gap_audit": dict|None, "vulnerabilities": [...],
         "session": dict|None, "sources": ["gap", "interview"]}
    """
    if not quiet:
        print(f"\n[证据] 正在聚合岗位「{job_name}」的证据...")

    gap_audit = load_gap_audit(trace_id=trace_id, job_name=job_name,
                               profile_dir=profile_dir, quiet=quiet)
    vulns, meta = load_interview_vulnerabilities(job_name=job_name,
                                                 profile_dir=profile_dir, quiet=quiet)

    sources = []
    if gap_audit:
        sources.append("gap")
    if vulns:
        sources.append("interview")

    if not quiet:
        print(f"[证据] 聚合完成，可用来源：{'、'.join(sources) if sources else '无（将只用简历+JD）'}\n")

    return {
        "job": job_name,
        "gap_audit": gap_audit,
        "vulnerabilities": vulns,
        "session": meta,
        "sources": sources,
    }
