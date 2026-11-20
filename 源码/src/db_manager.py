import sqlite3
import pandas as pd
import json

from paths import DB_PATH as _DEFAULT_DB_PATH

# 差距登记册：纯标准库模块，只用来给"任务声明了哪些来源"分类。
# 放在这里是为了让 DB 层成为 provenance 的**唯一落库权威** ——
# 调用方只需给出合法 gap_id 集合，分类规则不会在两处各写一份。
import gap_registry


# 公司名里常见的后缀 / 修饰，做去重时应先剥掉。
# 例：「腾讯」与「腾讯科技（深圳）有限公司」指的是同一家公司，
# 直接字符串比较会漏判成两个。
_COMPANY_NOISE = [
    "有限公司", "股份有限公司", "有限责任公司", "集团", "科技", "网络",
    "（", "）", "(", ")", " ", "　", "·",
]


def normalize_company(name):
    """
    归一化公司名，用于岗位去重。

    只做**保守**的清洗：剥掉法律后缀与括号，去掉空白。
    不做模糊匹配 —— 那属于匹配逻辑，不该藏在"归一化"里。
    空值返回空串，调用方自行决定是否视为"未识别"。
    """
    s = (name or "").strip()
    for noise in _COMPANY_NOISE:
        s = s.replace(noise, "")
    return s


class DBManager:
    # ------------------------------------------------------------
    # assessment_attempts（v8）：一次作答 = 一行评测证据
    # ------------------------------------------------------------
    # 为什么不塞进 study_tasks：一个任务可以多次作答，是一对多关系。
    # 横向加列只能保留"最后一次"，历史会被覆盖。
    ATTEMPT_TABLE = "assessment_attempts"
    ATTEMPT_INDEX = "uq_assessment_attempt"

    # 列序即契约（建表、补列、INSERT 都从这里取）
    ATTEMPT_COLUMNS = (
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("task_id", "INTEGER NOT NULL"),
        ("attempt_no", "INTEGER NOT NULL"),
        ("trace_id", "TEXT"),
        ("question_text", "TEXT"),
        ("answer_text", "TEXT"),
        ("model_score", "INTEGER"),
        ("final_score", "INTEGER"),
        ("score_source", "TEXT"),
        ("status", "TEXT"),
        ("rubric_json", "TEXT"),
        ("rubric_definition_json", "TEXT"),
        ("rubric_weight", "INTEGER"),
        ("feedback", "TEXT"),
        ("rag_hit", "INTEGER"),
        ("source_task_ids", "TEXT"),
        ("gap_ids", "TEXT"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    )

    # 少掉这些列就不是一张可用的评测表 —— 表为空时可以重建，有数据时报错
    ATTEMPT_CORE_COLUMNS = ("id", "task_id", "attempt_no")

    # 唯一索引的**定义契约**：列集合 + 列顺序。
    # 顺序也算契约 —— 反过来写虽然同样唯一，但查询计划与既有索引不一致，
    # 而且"定义对不上就重建"这条规则若给顺序开例外，就没有稳定判据了。
    ATTEMPT_INDEX_COLUMNS = ("task_id", "attempt_no")

    @classmethod
    def _attempt_create_sql(cls):
        body = ",\n                ".join(f"{n} {d}" for n, d in cls.ATTEMPT_COLUMNS)
        return f"""
            CREATE TABLE IF NOT EXISTS {cls.ATTEMPT_TABLE} (
                {body},
                FOREIGN KEY (task_id) REFERENCES study_tasks(id)
            )
            """

    @classmethod
    def _attempt_index_sql(cls):
        """
        **不带** `IF NOT EXISTS`。

        首次验收的真实缺陷：`IF NOT EXISTS` 遇到同名但定义错误的索引时
        直接无操作返回，错误因此被静默保留（`UNIQUE(task_id)` 一直存在，
        第二次作答才炸）。现在先由 `_ensure_attempt_index()` 用 PRAGMA 验证定义，
        确认可安全重建后才显式 `DROP INDEX`，再执行本语句。
        """
        cols = ", ".join(cls.ATTEMPT_INDEX_COLUMNS)
        return (f"CREATE UNIQUE INDEX {cls.ATTEMPT_INDEX} "
                f"ON {cls.ATTEMPT_TABLE}({cols})")

    # ------------------------------------------------------------
    # v8 索引：定义验证（PRAGMA）与安全重建
    # ------------------------------------------------------------
    def _assessment_index_state(self):
        """
        读取 `uq_assessment_attempt` 的**真实定义**，而不是"名字在不在"。

        判据（全部成立才算完整）：
          1. 名字 == ATTEMPT_INDEX；
          2. `PRAGMA index_list` 的 unique 标志为真；
          3. 不是 partial index；
          4. `PRAGMA index_info` 的列**严格等于** ATTEMPT_INDEX_COLUMNS（含顺序）。

        返回 dict：exists / unique / partial / columns / problems / ok。
        表不存在时 PRAGMA 返回空列表，这里如实报 "索引不存在"。
        """
        table = self.ATTEMPT_TABLE
        try:
            rows = self.cursor.execute(f"PRAGMA index_list({table})").fetchall()
        except sqlite3.Error:
            rows = []

        for row in rows:
            # PRAGMA index_list: (seq, name, unique, origin, partial)
            name = row[1]
            if name != self.ATTEMPT_INDEX:
                continue
            unique = bool(row[2])
            partial = bool(row[4]) if len(row) > 4 else False
            columns = [r[2] for r in self.cursor.execute(
                f"PRAGMA index_info({name})").fetchall()]
            expected = list(self.ATTEMPT_INDEX_COLUMNS)

            problems = []
            if not unique:
                problems.append("不是 UNIQUE")
            if partial:
                problems.append("是 partial index")
            if columns != expected:
                problems.append(f"列为 {columns}，应为 {expected}")
            return {"exists": True, "unique": unique, "partial": partial,
                    "columns": columns, "problems": problems, "ok": not problems}

        return {"exists": False, "unique": False, "partial": False,
                "columns": [], "problems": ["索引不存在"], "ok": False}

    def _attempt_duplicate_keys(self):
        """列出重复的 (task_id, attempt_no)。建立唯一索引前必须先看它。"""
        try:
            return self.cursor.execute(
                f"SELECT task_id, attempt_no, COUNT(*) FROM {self.ATTEMPT_TABLE} "
                "GROUP BY task_id, attempt_no HAVING COUNT(*) > 1 "
                "ORDER BY task_id, attempt_no").fetchall()
        except sqlite3.Error:
            # 表还不存在 → 没有重复键可言
            return []

    def _ensure_attempt_index(self):
        """
        校验并（必要时）重建唯一索引。返回 (rebuilt, state)。

        安全重建规则
        ------------
        · 定义已正确 → 什么都不做（不重建、不扫数据、rootpage 不变）；
        · 索引状态不正确（**无论是"缺失"还是"定义错误"**）+ 有重复键
            → 抛 RuntimeError，**不动数据、不创建/删除索引、不写版本号**；
        · 索引状态不正确 + 无重复键
            → 缺失则直接创建；定义错误则先精确 DROP 再创建；
        · 创建后**再用 PRAGMA 复核**，复核不过照样抛错。

        为什么重复键检查不能只在"索引已存在"分支里
        ------------------------------------------
        那是首次收尾时的缺陷：索引被彻底删掉、表里又有重复
        `(task_id, attempt_no)` 时，代码会直接 `CREATE UNIQUE INDEX`，
        撞出裸的 `sqlite3.IntegrityError: UNIQUE constraint failed: ...`。
        数据和版本确实没坏，但**异常类型与诊断**不符合本函数的承诺 ——
        调用方拿到的是一个没有"哪几组重复、该怎么办"的底层报错。
        所以只要准备建立/重建唯一索引，就必须先问一次"数据能不能满足它"。
        """
        state = self._assessment_index_state()
        if state["ok"]:
            return False, state

        dups = self._attempt_duplicate_keys()
        if dups:
            detail = "、".join(
                f"(task_id={t}, attempt_no={n})×{c}" for t, n, c in dups[:10])
            more = "" if len(dups) <= 10 else f" 等共 {len(dups)} 组"
            raise RuntimeError(
                f"{self.ATTEMPT_TABLE} 的 (task_id, attempt_no) 唯一索引不可用"
                f"（{'；'.join(state['problems'])}），"
                f"表内已存在重复的 (task_id, attempt_no)：{detail}{more}。\n"
                "拒绝自动修复：建立唯一索引必须先删除重复行，"
                "那会丢失历史作答记录。\n"
                "请人工确认并处理重复数据后重试"
                "（历史数据与 schema_version 均未被改动，索引也未创建）。")

        if state["exists"]:
            # DROP INDEX 用的是**精确索引名**，不会误删别的索引
            self.cursor.execute(f"DROP INDEX {self.ATTEMPT_INDEX}")
            print(f"[DB] 索引 {self.ATTEMPT_INDEX} 定义错误"
                  f"（{'；'.join(state['problems'])}），已删除准备重建")

        self.cursor.execute(self._attempt_index_sql())

        state = self._assessment_index_state()
        if not state["ok"]:
            raise RuntimeError(
                f"重建后 {self.ATTEMPT_INDEX} 定义仍不正确：{state['problems']}")
        return True, state

    def __init__(self, db_name=_DEFAULT_DB_PATH):
        print(f" 正在连接本地数据库: {db_name}")
        # 建立连接。如果这个 db 文件不存在，Python 会自动帮你创建一个
        self.conn = sqlite3.connect(db_name)
        self.conn.execute("PRAGMA foreign_keys = ON") 
        self.cursor = self.conn.cursor()
        try:
            self._create_table()
            self.ensure_score_column()

            # 版本门禁：逐级升到最新。
            #
            # ⚠ 每一级迁移之后都必须**重新读取**真实版本号，不能沿用
            # 初始化时的那份快照。这是 T03-A 首次验收发现的缺陷：
            #
            #   库：schema_version=7、source_task_ids 已存在、缺 v6 的某列
            #   → 初始化读到 version=7（快照）
            #   → v6 门禁发现缺列 → migrate_to_v6() 把版本写成 6
            #   → v7 门禁仍用快照 7 → 判定"已是最新" → 跳过
            #   → 结构已是 v7，但版本号永久停在 6（**倒退**）
            #
            # 版本号是"当前状态"，不是"本次运行的起点"。低级修复把状态写低之后，
            # 后续门禁必须基于**新状态**重新判断，否则修复越彻底、版本越落后。
            #
            # 注意：这里也不能"在最后无条件写 7" —— 那会把前级迁移的失败
            # 掩盖成"看起来已经最新"。只认每次迁移自己写入的版本。
            version = self._current_schema_version()

            # 门禁必须看**真实建表语句**，而不是「有没有 seq 列」——
            # ALTER TABLE 能加列，却改不掉 UNIQUE 约束，只看列会误判成已迁移。
            row = self.cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='study_tasks'"
            ).fetchone()
            ddl = (row[0] if row else "") or ""

            if "seq" not in ddl:
                if version < 2:
                    self.migrate_to_v2()
                    version = self._current_schema_version()
                self.migrate_to_v3()
                version = self._current_schema_version()
            elif version < 3:
                # 已是 v3 结构（新库，或已迁移过的库）：只补版本号，不重建
                self._set_schema_version(3)
                version = self._current_schema_version()

            if version < 4:
                self.migrate_to_v4()
                version = self._current_schema_version()

            # v5：jobs / job_gap_reports 补列。
            # 这里同样**查真实 DDL**，而不是只看版本号 ——
            # 版本号只说"迁移跑到哪"，不等于"结构真的长这样"。
            # 曾经的真实故障就是：jobs 还是 v1 结构，schema_version 却已经是 4，
            # 两者脱节且没人发现。所以判据以"列在不在"为准，版本号只作参考。
            jobs_row = self.cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'"
            ).fetchone()
            jobs_ddl = (jobs_row[0] if jobs_row else "") or ""

            if version < 5 or "job_jd_full" not in jobs_ddl:
                self.migrate_to_v5()
                version = self._current_schema_version()

            # v6：gap → task 可追溯列。**共三列，跨两张表**。
            #
            # 门禁必须逐列查真实结构，不能"看到 gap_ids 就认为 v6 齐了" ——
            # 这是首次验收真实漏掉的缺陷：版本号谎报为 6、study_tasks.gap_ids
            # 存在，但 study_tasks.provenance_status 或
            # study_plans.source_report_id 缺失时，迁移被跳过，随后
            # `insert_study_plan(source_report_id=...)` 直接抛
            #   sqlite3.OperationalError: table study_plans has no column
            #   named source_report_id
            #
            # 用 PRAGMA table_info 读列集合（而不是判断建表 SQL 的字符串）：
            # 字符串包含判断既会被注释/同名列干扰，也只能覆盖被查询的那张表。
            def _table_cols(table):
                return {r[1] for r in self.cursor.execute(
                    f"PRAGMA table_info({table})").fetchall()}

            task_cols = _table_cols("study_tasks")
            plan_cols = _table_cols("study_plans")
            v6_columns = (
                ("study_tasks", "gap_ids", task_cols),
                ("study_tasks", "provenance_status", task_cols),
                ("study_plans", "source_report_id", plan_cols),
            )
            missing = [f"{tbl}.{col}" for tbl, col, cols in v6_columns
                       if col not in cols]

            if version < 6 or missing:
                if missing:
                    print(f"[DB] v6 结构不完整，缺少：{'、'.join(missing)}")
                self.migrate_to_v6()
                # 关键：v6 可能把版本写低（从 7 → 6），必须刷新后再判 v7
                version = self._current_schema_version()

            # v7：考题的来源学习任务列。
            # 与 v6 同样的原则：逐列查真实结构，版本号只作参考。
            # 这里虽然只有一列，也照样用 PRAGMA 判断 —— 不能因为"只有一列"
            # 就退回"看建表 SQL 字符串"，那正是 v6 首次验收踩过的坑。
            # 注意 task_cols 要**重新读**：v6 刚可能加过列。
            task_cols = _table_cols("study_tasks")
            if version < 7 or "source_task_ids" not in task_cols:
                if "source_task_ids" not in task_cols:
                    print("[DB] v7 结构不完整，缺少：study_tasks.source_task_ids")
                self.migrate_to_v7()
                version = self._current_schema_version()

            # v8：评测尝试表。
            #
            # 门禁看三件事：表在、列齐、**唯一索引的定义正确**。
            # 前两件用 PRAGMA table_info；第三件必须用
            # `PRAGMA index_list` + `PRAGMA index_info` 核对
            # unique / partial / 列集合 / 列顺序 ——
            # **"sqlite_master 里有同名对象" ≠ "索引定义正确"**。
            # 首次验收就漏在这里：同名 `UNIQUE(task_id)` 被当成完整，
            # 第一次作答成功、第二次撞 UNIQUE constraint。
            attempt_cols = _table_cols(self.ATTEMPT_TABLE)
            need_attempt_cols = {n for n, _ in self.ATTEMPT_COLUMNS}
            index_state = self._assessment_index_state()
            cols_ok = need_attempt_cols <= attempt_cols

            if version < 8 or not cols_ok or not index_state["ok"]:
                lacking = sorted(need_attempt_cols - attempt_cols)
                if lacking or not index_state["ok"]:
                    print(f"[DB] v8 结构不完整：缺列={lacking or '无'}，"
                          f"唯一索引={index_state['problems']}")
                self.migrate_to_v8()
                version = self._current_schema_version()
        except Exception:
            self.conn.close()
            raise
    def ensure_score_column(self):
        """
        确保 study_tasks 表有 score 字段。
        老数据库第一次运行时会自动迁移；
        后续重复运行不会报重复字段错误。
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(study_tasks)")
            columns = [row[1] for row in cursor.fetchall()]

            if "score" not in columns:
                cursor.execute("""
                    ALTER TABLE study_tasks
                    ADD COLUMN score INTEGER
                """)
                self.conn.commit()
                print("✅ 已为 study_tasks 添加 score 字段")
            else:
                print("ℹ️ study_tasks.score 字段已存在，无需迁移")

        except Exception as e:
            self.conn.rollback()
            print(f"❌ score 字段迁移失败：{e}")
            raise

    def print_study_tasks_schema(self):
        """打印 study_tasks 表字段，供测试和排错使用。"""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(study_tasks)")

        print("\n=== study_tasks 表结构 ===")
        for row in cursor.fetchall():
            print(f"字段名: {row[1]}, 类型: {row[2]}, 默认值: {row[4]}")
            
    def _create_table(self):
        """ 初始化建表操作 """
        try:
            # ============================================================
            # 1. jobs：岗位信息表
            # ============================================================
            # 写一段 SQL 语句。定义表名 jobs，以及各个字段的类型
            # PRIMARY KEY 保证了 JD链接 是全宇宙唯一的！
            sql = '''
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,    -- 终极杀招：合成的主键 ID
                company TEXT,               -- 公司名
                title TEXT,                 -- 岗位名称
                jd_must TEXT,               -- JD核心技能
                jd_nice TEXT,               -- JD加分技能
                salary TEXT,                -- 薪资区间
                crawl_date TEXT,            -- 采集日期
                tis_score REAL,             -- TIS关键词匹配分（0~100，见下）
                status TEXT DEFAULT '未生成报告',
                company_norm TEXT,          -- v5：归一化公司名（去后缀/空格，用于去重）
                source TEXT,                -- v5：来源 mock / pasted / crawl
                job_jd_full TEXT            -- v5：JD 原文（不再是几个技能词）
            )
            '''
            self.cursor.execute(sql)
            self.conn.commit()#提交
            print(" 数据库表结构校验完毕！")

            # ============================================================
            # 2. agent_evaluations：Agent 调用审计表
            # ============================================================
            # 说明：早期的 memory_stream（Agent 记忆流表）已在 v4 迁移中移除 ——
            # 它从建立起就没人写过。Agent 之间的"记忆"实际由
            # agent_messages（显式交接）+ trace_id（调用审计）承担。

            sql_evaluation = '''
            CREATE TABLE IF NOT EXISTS agent_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                session_id TEXT,
                agent_name TEXT,

                model_name TEXT,
                system_prompt TEXT,
                user_prompt TEXT,       

                input_data TEXT,
                output_text TEXT,

                total_tokens INTEGER,
                latency_ms REAL,

                status TEXT,
                error_message TEXT,

                human_score INTEGER,
                human_feedback TEXT,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''

            self.cursor.execute(sql_evaluation)
            self.conn.commit()

            print(" Agent评测表(agent_evaluations)校验完毕！")
            #删除旧study_tasks
            # self.cursor.execute(
            #     "DROP TABLE IF EXISTS study_tasks"
            # )

            # print("旧 study_tasks 已删除！")

            # ============================================================
            # 学习计划表
            # ============================================================

            sql_plan = '''
            CREATE TABLE IF NOT EXISTS study_plans (
                plan_id TEXT PRIMARY KEY,

                overall_goal TEXT,

                total_days INTEGER,

                status TEXT DEFAULT '未开始',

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                -- v6：这份计划由哪份 Agent A 报告生成（NULL = 未记录）
                source_report_id TEXT
            )
            '''

            self.cursor.execute(sql_plan)

            print(" 学习计划表 study_plans 校验完毕！")

            # ============================================================
            # 学习阶段表
            # ============================================================

            sql_phase = '''
            CREATE TABLE IF NOT EXISTS study_phases (
                phase_id TEXT PRIMARY KEY,

                plan_id TEXT NOT NULL,

                phase_name TEXT,

                phase_goal TEXT,

                phase_order INTEGER,

                FOREIGN KEY (plan_id)
                    REFERENCES study_plans(plan_id)
            )
            '''

            self.cursor.execute(sql_phase)

            print(" 学习阶段表 study_phases 校验完毕！")

            # ============================================================
            # 4. study_tasks：Agent B 每日学习任务表
            # ============================================================

            sql_tasks = '''
            CREATE TABLE IF NOT EXISTS study_tasks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id          TEXT NOT NULL,
                phase_id         TEXT NOT NULL,
                phase_name       TEXT,
                day              INTEGER NOT NULL,
                seq              INTEGER NOT NULL DEFAULT 1,   -- 同一天的第几条（原计划任务记 1）
                task_type        TEXT,
                content          TEXT,
                expected_outcome TEXT,
                status           TEXT NOT NULL DEFAULT 'pending'
                                CHECK(status IN ('pending','doing','completed','failed')),
                score            INTEGER,
                -- v6：来源可追溯。NULL = 未记录来源（旧数据 / 无报告上下文）；
                -- '[]' + provenance_status='unlinked' = 明确记录为"无来源"。
                gap_ids            TEXT,
                provenance_status  TEXT,
                -- v7：考题的来源学习任务（JSON 数组，元素是 study_tasks.id）。
                -- NULL = 未记录（旧考题 / 旧调用）；'[]' = 记录为无来源。
                source_task_ids    TEXT,
                UNIQUE(plan_id, day, seq),                      -- 允许一天多行
                FOREIGN KEY (plan_id)  REFERENCES study_plans(plan_id),
                FOREIGN KEY (phase_id) REFERENCES study_phases(phase_id)
            )
            '''
            self.cursor.execute(sql_tasks)

            print("学习任务表 study_tasks 校验完毕！")

            # ============================================================
            # 4.5 assessment_attempts（v8）：作答 / rubric / 最终分 / 反馈
            # ============================================================
            # 一个任务可以多次作答 → 一对多。横向往 study_tasks 加列只能留最后一次。
            self.cursor.execute(self._attempt_create_sql())
            # 唯一索引**不在这里建**：索引的完整性判据只有一份，
            # 由 v8 门禁 → migrate_to_v8 → _ensure_attempt_index() 统一负责
            # （PRAGMA 验证 unique/partial/列集合/列顺序 + 安全重建）。
            # 若这里也建一次，就会出现"初始化用 IF NOT EXISTS、迁移用另一套判据"
            # 的双轨，错误定义又会被静默跳过。

            print("评测尝试表 assessment_attempts 校验完毕！")

            sql_idx = '''
            CREATE TABLE IF NOT EXISTS job_gap_reports (
                report_id      TEXT PRIMARY KEY,     -- GAP_<uuid12>
                trace_id       TEXT NOT NULL,
                company        TEXT,
                title          TEXT,
                tis_score      REAL,                 -- 分数值（尺度由 scorer 决定）
                scorer         TEXT,                 -- v5：tis_keyword / model_match
                gap_table_json TEXT,                 -- selected_gap_df 的 JSON
                audit_json     TEXT,                 -- Agent A 返回的完整 JSON
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
            self.cursor.execute(sql_idx)

            print("岗位Gap报告表 job_gap_reports 校验完毕！")

            sql_agent_messages = '''
            CREATE TABLE IF NOT EXISTS agent_messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id     TEXT NOT NULL,
            seq          INTEGER NOT NULL,
            from_agent   TEXT NOT NULL,
            to_agent     TEXT,
            msg_type     TEXT NOT NULL,   -- handoff / result / error
            payload_json TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(trace_id, seq)
            )
            '''
            
            self.cursor.execute(sql_agent_messages)
            print("多智能体交接表 agent_messages 校验完毕！")

            # ============================================================
            # 所有建表操作统一提交
            # ============================================================

            self.conn.commit()

            print("所有数据库表结构校验完毕！")


        except sqlite3.Error as e:

            # 如果建表过程中出现 SQLite 错误
            self.conn.rollback()

            print(f"[数据库初始化失败] {e}")

            # 不要吞掉异常
            raise
    def migrate_to_v2(self):
        """重建 study_tasks：统一 status 枚举 / 加唯一约束 / 字段名统一小写"""
        print("[DB] 开始迁移 study_tasks → v2 ...")
        # 迁移期间必须关外键，否则改名旧表时会连带触发约束检查
        self.conn.execute("PRAGMA foreign_keys = OFF")
        try:
            self.cursor.execute("ALTER TABLE study_tasks RENAME TO study_tasks_old")

            self.cursor.execute("""
            CREATE TABLE study_tasks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id          TEXT NOT NULL,
                phase_id         TEXT NOT NULL,
                phase_name       TEXT,
                day              INTEGER NOT NULL,
                task_type        TEXT,
                content          TEXT,
                expected_outcome TEXT,
                status           TEXT NOT NULL DEFAULT 'pending'
                                CHECK(status IN ('pending','doing','completed','failed')),
                score            INTEGER,
                UNIQUE(plan_id, day),
                FOREIGN KEY (plan_id)  REFERENCES study_plans(plan_id),
                FOREIGN KEY (phase_id) REFERENCES study_phases(phase_id)
            )
            """)

            self.cursor.execute("""
            INSERT INTO study_tasks
                (plan_id, phase_id, phase_name, day, task_type,
                content, expected_outcome, status, score)
            SELECT
                plan_id, phase_id, phase_name, day, task_type,
                content, expected_outcome,
                CASE status
                    WHEN '未开始'    THEN 'pending'
                    WHEN '进行中'    THEN 'doing'
                    WHEN 'completed' THEN 'completed'
                    WHEN 'failed'    THEN 'failed'
                    ELSE 'pending'
                END,
                score
            FROM study_tasks_old
            """)

            self.cursor.execute("DROP TABLE study_tasks_old")
            self.cursor.execute("CREATE INDEX idx_tasks_plan ON study_tasks(plan_id)")
            self.conn.commit()
            self._set_schema_version(2)
            print("[DB] study_tasks 迁移完成 ✅")

        except Exception as e:
            self.conn.rollback()
            print(f"[DB] 迁移失败：{e}")
            raise
        finally:
            self.conn.commit()                                # 先结束事务
            self.conn.execute("PRAGMA foreign_keys = ON")     # 事务内设 PRAGMA 无效

    def migrate_to_v3(self):
        """
        重建 study_tasks：把 UNIQUE(plan_id, day) 放宽为 UNIQUE(plan_id, day, seq)。

        为什么要放宽
        ------------
        `UNIQUE(plan_id, day)` 的副作用是「每个计划的每一天只能有一条记录」，
        由此带来两个真实限制：
          1. **一天只能出一道题** —— 7 天计划最多 7 道题，评估样本太薄；
          2. **范围考察无处安放** —— "把第 1~3 天一起考一遍"产生的多道题
             没有地方落库。

        `seq` 语义：同一天内的第几条。原计划的每日学习任务统一记为 `seq=1`
        （所以旧数据迁移后行为完全不变），考察题从 `seq=2` 开始追加。

        迁移期间必须关外键：改名旧表会连带触发约束检查。
        DDL 顺序保持「改名 → 建新表 → 搬数据 → 删旧表 → 建索引」，
        这样索引名不会与旧表冲突（旧索引随旧表一起被 DROP）。
        """
        print("[DB] 开始迁移 study_tasks → v3（一天可多行）...")
        self.conn.execute("PRAGMA foreign_keys = OFF")
        try:
            self.cursor.execute("ALTER TABLE study_tasks RENAME TO study_tasks_old")

            self.cursor.execute("""
            CREATE TABLE study_tasks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id          TEXT NOT NULL,
                phase_id         TEXT NOT NULL,
                phase_name       TEXT,
                day              INTEGER NOT NULL,
                seq              INTEGER NOT NULL DEFAULT 1,
                task_type        TEXT,
                content          TEXT,
                expected_outcome TEXT,
                status           TEXT NOT NULL DEFAULT 'pending'
                                CHECK(status IN ('pending','doing','completed','failed')),
                score            INTEGER,
                UNIQUE(plan_id, day, seq),
                FOREIGN KEY (plan_id)  REFERENCES study_plans(plan_id),
                FOREIGN KEY (phase_id) REFERENCES study_phases(phase_id)
            )
            """)

            # 旧记录全部记为 seq=1，语义与迁移前完全一致
            self.cursor.execute("""
            INSERT INTO study_tasks
                (plan_id, phase_id, phase_name, day, seq, task_type,
                 content, expected_outcome, status, score)
            SELECT
                plan_id, phase_id, phase_name, day, 1, task_type,
                content, expected_outcome,
                CASE status
                    WHEN '未开始'    THEN 'pending'
                    WHEN '进行中'    THEN 'doing'
                    WHEN 'completed' THEN 'completed'
                    WHEN 'failed'    THEN 'failed'
                    ELSE 'pending'
                END,
                score
            FROM study_tasks_old
            """)

            self.cursor.execute("DROP TABLE study_tasks_old")
            self.cursor.execute("CREATE INDEX idx_tasks_plan ON study_tasks(plan_id)")
            self.conn.commit()
            self._set_schema_version(3)
            print("[DB] study_tasks 迁移完成 ✅（现在同一天可以有多条记录）")

        except Exception as e:
            self.conn.rollback()
            print(f"[DB] v3 迁移失败：{e}")
            # 必须抛出去：迁移失败意味着约束没放宽，
            # 若静默继续，「一天多题」会在插入时才炸，且很难定位。
            raise
        finally:
            self.conn.commit()
            self.conn.execute("PRAGMA foreign_keys = ON")

    def migrate_to_v4(self):
        """
        删除 `memory_stream` 表（从未被使用的死表）。

        为什么删而不是留
        --------------
        它从建立起就**没有任何代码写过**：唯一的相关方法 `insert_memory()` 从未被调用，
        表里只有 2 行手工测试数据（`test_001`，2026-08-07）。

        它原本的设想是"跨步骤的会话记忆"，但这个需求实际由另外两个机制承担了：
          · `agent_messages` —— Agent 之间的**显式交接**（可审计、有序）
          · `trace_id` —— 把同一轮分析的所有调用串成一条链

        而且这恰好是本项目的核心主张：**Agent 之间不共享隐式记忆，
        而是通过显式消息传递**。所以留着一张名字像"记忆系统"的空表，
        比删掉它更有害 —— 读代码的人会以为这里有记忆机制。

        保留选择：如果将来要做"跨会话的用户画像累积"（那是另一件事，
        与 trace 无关），应新建一张语义明确的表，而不是复用这个名字。
        """
        print("[DB] 开始迁移 → v4（移除未使用的 memory_stream）...")
        try:
            exists = self.cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_stream'"
            ).fetchone()
            if exists:
                n = self.cursor.execute(
                    "SELECT COUNT(*) FROM memory_stream").fetchone()[0]
                self.cursor.execute("DROP TABLE memory_stream")
                self.conn.commit()
                print(f"[DB] 已删除 memory_stream（丢弃 {n} 行历史测试数据）")
            else:
                print("[DB] memory_stream 不存在，跳过删除")

            self._set_schema_version(4)
            print("[DB] 迁移完成 ✅（当前 schema v4）")

        except Exception as e:
            self.conn.rollback()
            print(f"[DB] v4 迁移失败：{e}")
            raise

    def migrate_to_v5(self):
        """
        v5：补齐 `jobs` 与 `job_gap_reports` 的结构缺口。

        修的是什么
        ----------
        真实库当时的状态是：**`schema_version` 已经是 4，但 `jobs` 仍是 v1 结构**
        —— 版本号与真实表结构脱节。原因是门禁只检查了 `study_tasks`，
        `jobs` 从没进过迁移链，于是它停在最初那版，而版本号却一路涨到了 4。

        这次补三件东西：

        1. `jobs.job_jd_full` —— JD **原文**。
           产品承诺是"输入你的理想岗位建立岗位库"，但表里只存了几个技能词，
           真实 JD 进来无处安放。原文是 Agent A/E/D 的共同燃料。

        2. `jobs.source` —— 数据来源（mock / pasted / crawl）。
           现有 99 行全是 `random.choice` 生成的 mock，与真实 JD 混在一起无法区分。
           标明来源后，"这行数据能不能信"才有答案。

        3. `jobs.company_norm` —— 归一化公司名，用于去重。
           原名形如「腾讯」/「腾讯科技（深圳）有限公司」，直接比较会漏判重复。

        另补 `job_gap_reports.scorer` —— 分清分数尺度。
        `tis_score` 这一列被两条线共用，尺度却完全不同：
          · core_pipeline 写的是**关键词命中比例**（如 88.5）
          · run_hunter 写的是**模型综合判断**（如 52.0）
        同列不同尺度，读的人无法解释。加一列 `scorer` 标明来源即可。

        用 ADD COLUMN 而不是重建表
        ------------------------
        这里只**加列**，不涉及 UNIQUE / 约束变更，所以 ALTER 足够，
        也不会像 study_tasks 那样需要关外键重建。仍然是让脚本幂等：
        加之前先查列是否存在。
        """
        print("[DB] 开始迁移 → v5（补齐 jobs / job_gap_reports 结构）...")
        try:
            added = []

            def _cols(table):
                return {r[1] for r in self.cursor.execute(
                    f"PRAGMA table_info({table})").fetchall()}

            jobs_cols = _cols("jobs")
            for col, decl in (
                ("job_jd_full", "TEXT"),      # JD 原文
                ("source", "TEXT"),           # mock / pasted / crawl
                ("company_norm", "TEXT"),     # 归一化公司名
            ):
                if col not in jobs_cols:
                    self.cursor.execute(f"ALTER TABLE jobs ADD COLUMN {col} {decl}")
                    added.append(f"jobs.{col}")

            gap_cols = _cols("job_gap_reports")
            if "scorer" not in gap_cols:
                self.cursor.execute(
                    "ALTER TABLE job_gap_reports ADD COLUMN scorer TEXT")
                added.append("job_gap_reports.scorer")

            self.conn.commit()

            # 回填：已有 jobs 全部是 mock 数据，标清楚来源；
            # 已有 gap 报告来自 core_pipeline（关键词线），按其语义回填。
            self.cursor.execute(
                "UPDATE jobs SET source='mock' WHERE source IS NULL")
            self.cursor.execute(
                "UPDATE job_gap_reports SET scorer='tis_keyword' WHERE scorer IS NULL")
            self.conn.commit()

            if added:
                print(f"[DB] 已新增列：{'、'.join(added)}")
            else:
                print("[DB] 所需列均已存在，跳过 ALTER")

            self._set_schema_version(5)
            print("[DB] 迁移完成 ✅（当前 schema v5）")

        except Exception as e:
            self.conn.rollback()
            print(f"[DB] v5 迁移失败：{e}")
            raise

    def migrate_to_v6(self):
        """
        v6：建立「岗位差距 → 学习任务」的可追溯列。

        加三列，全部可空，全部用 ADD COLUMN（不重建表、不动任何约束）：

          study_tasks.gap_ids            TEXT —— 来源 gap_id 的 JSON 数组
          study_tasks.provenance_status  TEXT —— linked / unlinked /
                                                 unknown_gap_id / no_gaps_in_report
          study_plans.source_report_id   TEXT —— 这份计划由哪份 A 报告生成

        为什么不是重建表
        ----------------
        这里只**加列**，不涉及 UNIQUE / 外键变更。study_tasks 在 v3 那次因为
        要改 UNIQUE(plan_id, day) 才不得不关外键重建；本次完全没有那个必要。
        ALTER TABLE ADD COLUMN 在 SQLite 上是原地操作，旧行自动为 NULL。

        旧数据的语义（重要）
        -------------------
        NULL 表示 **"未记录来源"**，不是"没有差距"，也不表示"和任何 gap 无关"。
        绝不在迁移里给旧行回填一个猜出来的 gap_id —— 那才是真正的伪造来源。
        """
        print("[DB] 开始迁移 → v6（gap → task 可追溯列）...")
        try:
            added = []

            def _cols(table):
                return {r[1] for r in self.cursor.execute(
                    f"PRAGMA table_info({table})").fetchall()}

            task_cols = _cols("study_tasks")
            for col, decl in (
                ("gap_ids", "TEXT"),
                ("provenance_status", "TEXT"),
            ):
                if col not in task_cols:
                    self.cursor.execute(
                        f"ALTER TABLE study_tasks ADD COLUMN {col} {decl}")
                    added.append(f"study_tasks.{col}")

            plan_cols = _cols("study_plans")
            if "source_report_id" not in plan_cols:
                self.cursor.execute(
                    "ALTER TABLE study_plans ADD COLUMN source_report_id TEXT")
                added.append("study_plans.source_report_id")

            self.conn.commit()

            if added:
                print(f"[DB] 已新增列：{'、'.join(added)}")
            else:
                print("[DB] 所需列均已存在，跳过 ALTER")

            self._set_schema_version(6)
            print("[DB] 迁移完成 ✅（当前 schema v6）")

        except Exception as e:
            self.conn.rollback()
            print(f"[DB] v6 迁移失败：{e}")
            raise

    def migrate_to_v7(self):
        """
        v7：给考题加"来源学习任务"列。

            study_tasks.source_task_ids TEXT
                JSON 数组，元素是 study_tasks.id（真实主键，不另造 ID）。
                NULL = 未记录（旧考题 / 旧调用）；
                '[]' = 明确记录为"没有来源"。

        只加一列，ADD COLUMN，不动任何约束。
        旧行一律保持 NULL —— **绝不按 day 回填**：同一天可能有多条任务，
        按日期猜来源就是伪造。
        """
        print("[DB] 开始迁移 → v7（考题来源列）...")
        try:
            added = []
            cols = {r[1] for r in self.cursor.execute(
                "PRAGMA table_info(study_tasks)").fetchall()}
            if "source_task_ids" not in cols:
                self.cursor.execute(
                    "ALTER TABLE study_tasks ADD COLUMN source_task_ids TEXT")
                added.append("study_tasks.source_task_ids")

            self.conn.commit()

            if added:
                print(f"[DB] 已新增列：{'、'.join(added)}")
            else:
                print("[DB] 所需列均已存在，跳过 ALTER")

            self._set_schema_version(7)
            print("[DB] 迁移完成 ✅（当前 schema v7）")

        except Exception as e:
            self.conn.rollback()
            print(f"[DB] v7 迁移失败：{e}")
            raise

    def migrate_to_v8(self):
        """
        v8：新建 `assessment_attempts`（一次作答一行评测证据）。

        幂等性
        ------
        · 表不存在 → `CREATE TABLE IF NOT EXISTS`；
        · 表存在但缺**非核心列** → `ALTER TABLE ADD COLUMN` 逐个补；
        · 缺**核心列**（id/task_id/attempt_no）：
            空表 → 直接重建（没有数据可丢）；
            非空表 → 明确报错，不静默删数据；
        · 唯一索引 `(task_id, attempt_no)`：**按 PRAGMA 验证定义**，
          定义错误时先查重复键 —— 无重复才删旧建新，有重复则拒绝并报出重复键。

        旧数据
        ------
        不迁移、不回填：`study_tasks` 里的历史 status/score 不会变成伪造的 attempt。
        旧任务在查询时返回空列表，导出走 legacy fallback。
        """
        print("[DB] 开始迁移 → v8（评测尝试表）...")
        table = self.ATTEMPT_TABLE
        try:
            self.cursor.execute(self._attempt_create_sql())

            def _cols():
                return {r[1] for r in self.cursor.execute(
                    f"PRAGMA table_info({table})").fetchall()}

            cols = _cols()
            core_missing = [c for c in self.ATTEMPT_CORE_COLUMNS if c not in cols]

            if core_missing:
                rows = self.cursor.execute(
                    f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if rows:
                    raise RuntimeError(
                        f"{table} 结构异常（缺核心列 {core_missing}）且有 {rows} 行数据，"
                        "拒绝自动重建。请先备份并人工确认。")
                print(f"[DB] {table} 缺核心列 {core_missing} 且为空，重建")
                self.cursor.execute(f"DROP TABLE {table}")
                self.cursor.execute(self._attempt_create_sql())
                cols = _cols()

            added = []
            for name, decl in self.ATTEMPT_COLUMNS:
                if name in cols:
                    continue
                # 只剩可空列会走到这里；ADD COLUMN 不允许无默认值的 NOT NULL
                self.cursor.execute(
                    f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                added.append(name)

            # 唯一索引：先验证定义，再决定是否安全重建。
            # 不用 `CREATE ... IF NOT EXISTS` —— 同名错定义会被它静默放过。
            self._ensure_attempt_index()
            self.conn.commit()

            if added:
                print(f"[DB] 已新增列：{'、'.join(added)}")
            else:
                print(f"[DB] {table} 列已齐，跳过 ALTER")

            self._set_schema_version(8)
            print("[DB] 迁移完成 ✅（当前 schema v8）")

        except Exception as e:
            self.conn.rollback()
            print(f"[DB] v8 迁移失败：{e}")
            raise

    def _current_schema_version(self):
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = self.cursor.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] or 0

    def _set_schema_version(self, v):
        """
        写入当前 schema 版本 —— 幂等。

        schema_version 是「当前状态」而不是「迁移日志」：它只该有一行。
        早期实现只 INSERT 不清理，把每级迁移的版本号都堆在表里
        （现库里就同时躺着 2、3、4 三行），读取端靠 MAX() 才侥幸没出错。
        一旦将来有人回滚，MAX() 会指向已经作废的高版本，门禁即刻失效。

        所以这里先清空再写：无论调用多少次，表里恒为单行。
        """
        self.cursor.execute("DELETE FROM schema_version")
        self.cursor.execute("INSERT INTO schema_version (version) VALUES (?)", (v,))
        self.conn.commit()

    def append_message(self, trace_id, from_agent, to_agent, msg_type, payload: dict):
        """多智能体交接记录：谁把什么交给了谁"""
        seq = self.cursor.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_messages WHERE trace_id = ?",
            (trace_id,)
        ).fetchone()[0]

        self.cursor.execute("""
            INSERT INTO agent_messages
                (trace_id, seq, from_agent, to_agent, msg_type, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (trace_id, seq, from_agent, to_agent, msg_type,
            json.dumps(payload, ensure_ascii=False)))

        self.conn.commit()
        return seq

    def get_trace_messages(self, trace_id):
        self.cursor.execute("""
            SELECT seq, from_agent, to_agent, msg_type, payload_json
            FROM agent_messages WHERE trace_id = ? ORDER BY seq
        """, (trace_id,))
        return self.cursor.fetchall()

    # 注：原 insert_memory() 随 memory_stream 表一起在 v4 迁移中移除。
    # 它从建立起从未被任何代码调用过。

    def insert_new_job(self, job_dict):
        """ 尝试插入一个新岗位 (增量更新的核心) """

         #  数据工程师的魔法：造一个全宇宙唯一的 ID
        # 只要公司、岗位和日期一样，我们就认为是同一个招聘需求
        unique_job_id = f"{job_dict.get('公司名', '未知')}_{job_dict.get('岗位名称', '未知')}_{job_dict.get('采集日期', '未知')}"
        # 使用 INSERT OR IGNORE。意思是：如果 URL 已经存在，就不报错，直接跳过！
        sql = '''
        INSERT OR IGNORE INTO jobs
            (job_id, company, title, jd_must, jd_nice, salary, crawl_date,
             tis_score, source, job_jd_full, company_norm)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        company = job_dict.get("公司名", "")
        # 执行插入
        self.cursor.execute(sql, (
             unique_job_id,                      # 1. job_id
            company,                             # 2. company
            job_dict.get("岗位名称", ""),       # 3. title
            str(job_dict.get("JD核心技能", "")),# 4. jd_must (强制转字符串防止列表报错)
            str(job_dict.get("JD加分技能", "")),# 5. jd_nice
            job_dict.get("薪资区间", ""),       # 6. salary
            job_dict.get("采集日期", ""),       # 7. crawl_date
            job_dict.get("TIS综合评分", 0.0),   # 8. tis_score
            job_dict.get("来源", "mock"),       # 9. source（默认 mock：历史数据都是随机生成的）
            job_dict.get("职位描述", ""),       # 10. job_jd_full（JD 原文）
            normalize_company(company),         # 11. company_norm（去重用的归一化名）
        ))
        
        self.conn.commit()
        # rowcount 表示这次操作影响了几行。如果是 0，说明被 IGNORE（忽略）了，是重复数据！
        if self.cursor.rowcount > 0:
            print(f" 新增岗位成功:{unique_job_id}")
            return True
        else:
           # print(f" 岗位已存在，跳过增量: {unique_job_id}")
            return False

    def insert_evaluation(
        self,
        session_id,
        agent_name,
        model_name,
        system_prompt,
        user_prompt,
        input_data,
        output_text,
        total_tokens,
        latency_ms,
        status="success",
        error_message=None
    ):
        """保存一次 Agent 调用的完整评测记录"""

        sql = '''
        INSERT INTO agent_evaluations (
            session_id,
            agent_name,
            model_name,
            system_prompt,
            user_prompt,
            input_data,
            output_text,
            total_tokens,
            latency_ms,
            status,
            error_message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''

        self.cursor.execute(sql, (
            session_id,
            agent_name,
            model_name,
            system_prompt,
            user_prompt,
            input_data,
            output_text,
            total_tokens,
            latency_ms,
            status,
            error_message
        ))

        self.conn.commit()

        return self.cursor.lastrowid#告知我这次测试倍数据库记录成了第几条

    def get_all_jobs(self):
        """从 SQLite 岗位库读取所有岗位，返回 DataFrame"""

        sql = """
        SELECT
            company AS 公司名,
            title AS 岗位名称,
            jd_must AS JD核心技能,
            jd_nice AS JD加分技能,
            salary AS 薪资区间,
            crawl_date AS 采集日期,
            tis_score AS TIS综合评分,
            source AS 来源,
            job_jd_full AS 职位描述,
            company_norm AS 公司名归一,
            status AS 状态
        FROM jobs
        """

        return pd.read_sql(sql, self.conn)

    def _validate_task_dict(self, task_dict: dict):
        """检查 Agent B 返回的任务字典是否符合要求"""

        required_fields = [
            "day",
            "task_type",
            "content",
            "expected_outcome"
        ]

        for field in required_fields:

            if field not in task_dict:
                raise ValueError(
                    f"Agent B 返回的任务缺少字段: {field}"
                )

        if not isinstance(task_dict["day"], int):
            raise TypeError(
                f"day 必须是整数，实际类型为："
                f"{type(task_dict['day']).__name__}"
            )

    def insert_study_plan(
        self,
        plan_id: str,
        overall_goal: str,
        total_days: int,
        source_report_id: str = None
    ):
        """
        source_report_id：这份计划是从哪份 Agent A 报告生成的（v6 新增）。
        不传时写 NULL —— 表示"调用方没有提供报告上下文"，
        与"报告是某一版"明确区分，不伪造来源。
        """

        cursor = self.conn.cursor()

        cursor.execute('''
            INSERT INTO study_plans
            (
                plan_id,
                overall_goal,
                total_days,
                source_report_id
            )
            VALUES (?, ?, ?, ?)
        ''', (
            plan_id,
            overall_goal,
            total_days,
            source_report_id
        ))

            


    def insert_study_phase(
        self,
        phase_id: str,
        plan_id: str,
        phase_name: str,
        phase_goal: str,
        phase_order: int
    ):

    

        cursor = self.conn.cursor()

        cursor.execute('''
            INSERT INTO study_phases
            (
                phase_id,
                plan_id,
                phase_name,
                phase_goal,
                phase_order
            )
            VALUES (?, ?, ?, ?, ?)
        ''', (
            phase_id,
            plan_id,
            phase_name,
            phase_goal,
            phase_order
        ))

    def insert_daily_task(self,plan_id:str, phase_id: str,phase_name:str, task_dict: dict):
        """
        接收 Agent B 传来的单日任务字典，并写入数据库

        task_dict 可选带 `seq`（同一天的第几条，默认 1）。
        默认 1 意味着：Agent B 保持"一天一个任务"的行为完全不变；
        只有当它显式给出 seq 时，才会在一天内写入多条。

        v6 起还可选带：
        · `gap_ids`            —— 该任务来源的 gap_id 列表（写 JSON 数组字符串）
        · `provenance_status`  —— 来源状态（linked / unlinked / unknown_gap_id /
                                  no_gaps_in_report）

        两者都不传时写 NULL —— 语义是**"未记录来源"**（旧调用 / 旧数据），
        与"记录为无来源"（空数组 + unlinked）明确区分，绝不互相冒充。
        """
        # 第一步：先验证 Agent B 的数据
        self._validate_task_dict(task_dict)

        seq = task_dict.get("seq", 1)
        if not isinstance(seq, int) or seq < 1:
            raise ValueError(f"seq 必须是 >=1 的整数，实际为：{seq!r}")

        gap_ids = task_dict.get("gap_ids")
        if gap_ids is not None and not isinstance(gap_ids, str):
            # list/tuple -> 规范化 JSON 数组；保证落库形态唯一，便于查询
            gap_ids = json.dumps(list(gap_ids), ensure_ascii=False)

        provenance = task_dict.get("provenance_status")
        source_ids = task_dict.get("source_task_ids")
        if source_ids is not None and not isinstance(source_ids, str):
            source_ids = json.dumps(list(source_ids), ensure_ascii=False)

        self.cursor.execute('''
            INSERT INTO study_tasks 
            (plan_id,phase_id,phase_name, day, seq, task_type, content,
             expected_outcome, gap_ids, provenance_status, source_task_ids)
            VALUES (?, ?,?,?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            plan_id,
            phase_id,
            phase_name,
            task_dict["day"],
            seq,
            task_dict["task_type"],
            task_dict["content"],
            task_dict["expected_outcome"],
            gap_ids,
            provenance,
            source_ids
            ))

    def save_complete_plan(
        self,
        plan,
        plan_id: str,
        source_report_id: str = None,
        known_gap_ids=None,
        commit=True,
    ):
        """
        保存完整学习计划。
        一个计划包含：
        1. study_plans
        2. study_phases
        3. study_tasks
        事务规则：
        - 全部成功 -> COMMIT
        - 任意失败 -> ROLLBACK
        - commit=False 时必须已有外层事务，由调用方统一提交或回滚。

        来源可追溯（v6）
        -----------------
        · `source_report_id`：这份计划由哪份 Agent A 报告生成，写进 study_plans。
        · `known_gap_ids`   ：该报告里合法的 gap_id 集合。给了它，DB 层就会把
          每个 task 的 `source_gap_ids` 分成"有效 / 编造"两类，并落成
          `gap_ids` + `provenance_status` 两列。

        关键区分（**不能混为一谈**）：
        · `known_gap_ids is None` —— 调用方没有报告上下文（旧调用 / 手工建计划）。
          两列写 NULL，含义是**"未记录来源"**，不去猜。
        · `known_gap_ids == set()` —— 有报告，但报告里没有结构化 gap。
          任务标 `no_gaps_in_report`，`gap_ids` 为空数组。
        空集合和 None 在 Python 里布尔值不同，这里刻意用 `is None` 判断。
        """
        try:

            print(
                f"[DB] 开始保存完整学习计划：{plan_id}"
            )
            # ==========================================
            # 1. 开始事务
            # ==========================================

            if commit:
                self.conn.execute("BEGIN")
            elif not self.conn.in_transaction:
                raise ValueError("保存计划需要外层事务")

            # ==========================================
            # 2. 计算总天数
            # ==========================================

            total_days = max(
                task.day
                for phase in plan.phases
                for task in phase.tasks
            )

            # ==========================================
            # 3. 保存 Plan
            # ==========================================

            self.insert_study_plan(
                plan_id=plan_id,
                overall_goal=plan.overall_goal,
                total_days=total_days,
                source_report_id=source_report_id
            )

            # ==========================================
            # 4. 保存 Phase
            # ==========================================

            for phase_index, phase in enumerate(
                plan.phases,
                start=1
            ):

                phase_id = (
                    f"{plan_id}_PHASE_{phase_index:02d}"
                )

                self.insert_study_phase(
                    phase_id=phase_id,
                    plan_id=plan_id,
                    phase_name=phase.phase_name,
                    phase_goal=phase.phase_goal,
                    phase_order=phase_index
                )

                # ======================================
                # 5. 保存 Task
                # ======================================

                for task in phase.tasks:

                    task_dict = task.model_dump()
                    raw_ids = task_dict.pop("source_gap_ids", None)

                    if known_gap_ids is None:
                        # 没有报告上下文：明确写 NULL（未记录），不猜、不伪造
                        task_dict["gap_ids"] = None
                        task_dict["provenance_status"] = None
                    else:
                        valid, _unknown, status = gap_registry.classify(
                            raw_ids, known_gap_ids, bool(known_gap_ids))
                        task_dict["gap_ids"] = valid
                        task_dict["provenance_status"] = status

                    self.insert_daily_task(
                        plan_id=plan_id,
                        phase_id=phase_id,
                        phase_name=phase.phase_name,
                        task_dict=task_dict
                    )

                
            # ==========================================
            # 6. 全部成功 → 提交
            # ==========================================

            if commit:
                self.conn.commit()

            print(
                f"[DB] 学习计划 {plan_id} "
                + ("保存成功！" if commit else "已写入外层事务，等待统一提交")
            )

            return True

        except Exception as e:

            # ==========================================
            # 7. 任意失败 → 回滚
            # ==========================================

            print(f"[DB] 保存学习计划失败：{e}")
            if commit:
                self.conn.rollback()
                print("[DB] Transaction Rollback 完成！")
            raise
                    
    def update_task_status(self, task_id, status, score):
        """
        更新任务状态和阅卷分数
        status:
            completed - 通过
            failed    - 未通过，需要复习
        """          
        allowed_status = ["completed", "failed"]

        if status not in allowed_status:
            raise ValueError(f"不支持的任务状态：{status},只允许：{allowed_status}")
        if not isinstance(score, int) or not 0 <= score <= 100:
            raise ValueError("阅卷分数必须是整数，且在 0-100 之间")

        cursor = self.conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE study_tasks
                SET 
                    status = ?,
                    score = ?
                WHERE id = ?
                """,
                (status, score, task_id)
            )

            if cursor.rowcount != 1 :
                self.conn.rollback()
                print(f"更新失败：未找到 task_id={task_id} 的任务")
                return False

            self.conn.commit()
            print(f"更新成功：task_id={task_id}, status={status}, score={score}")
            return True

        except Exception as e:
            self.conn.rollback()
            print(f"更新失败：{e}")
            return False

    # ============================================================
    # 评测尝试（v8）
    # ============================================================

    SCORE_SOURCE_RUBRIC = "rubric_weighted"
    SCORE_SOURCE_MODEL = "model_fallback"
    SCORE_SOURCES = (SCORE_SOURCE_RUBRIC, SCORE_SOURCE_MODEL)
    ATTEMPT_STATUSES = ("completed", "failed")

    @staticmethod
    def _json_cell(value):
        """list/dict → JSON 字符串；字符串与 None 原样保留。"""
        if value is None or isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def save_assessment_attempt(self, task_id, trace_id, question_text,
                                answer_text, model_score, final_score,
                                score_source, status, rubric_json,
                                rubric_definition_json, rubric_weight,
                                feedback, rag_hit, submission=None):
        """
        在**一个事务**里写入一次作答，并同步更新任务的最新状态。

        为什么不能用 `update_task_status()`
        ----------------------------------
        它内部自己 commit。如果在插 attempt 之后调它，一旦它失败（或进程中断），
        attempt 已经落库、task 却没更新，出现"有评测记录但任务状态没变"的裂缝。
        所以这里自己开事务：校验 → 算 attempt_no → 插入 → 更新 → 统一 commit。
        任一步失败整体 rollback，不留下孤儿记录。

        来源快照
        --------
        `source_task_ids` / `gap_ids` **直接从被评分的 study_tasks 行读取**，
        不接受调用方传入，也不按 day 猜。三态（NULL / [] / 非空）原样复制。

        返回 {"attempt_id", "attempt_no", "score_source", "final_score"}。
        """
        if status not in self.ATTEMPT_STATUSES:
            raise ValueError(f"不支持的评测状态：{status},只允许：{self.ATTEMPT_STATUSES}")
        if score_source not in self.SCORE_SOURCES:
            raise ValueError(f"未知的 score_source：{score_source}")
        if not isinstance(final_score, int) or not 0 <= final_score <= 100:
            raise ValueError("final_score 必须是 0-100 的整数")

        table = self.ATTEMPT_TABLE
        try:
            self.conn.execute("BEGIN")

            if submission:
                request_id, owner_token = submission
                receipt = self.conn.execute(
                    "SELECT task_id,trace_id FROM competition_grading WHERE request_id=? "
                    "AND owner_token=? AND status='generating'",
                    (request_id, owner_token)).fetchone()
                if receipt != (task_id, trace_id):
                    raise ValueError("阅卷请求已失效，拒绝保存重复作答")

            # 1) 校验任务存在，并取来源快照（只读，不采信模型）
            row = self.cursor.execute(
                "SELECT source_task_ids, gap_ids FROM study_tasks WHERE id=?",
                (task_id,)).fetchone()
            if row is None:
                raise ValueError(f"任务 {task_id} 不存在，拒绝写入评测记录")
            source_ids, gap_ids = row[0], row[1]

            # 2) 下一次作答序号
            attempt_no = self.cursor.execute(
                f"SELECT COALESCE(MAX(attempt_no), 0) + 1 "
                f"FROM {table} WHERE task_id=?", (task_id,)).fetchone()[0]

            # 3) 插入评测记录
            self.cursor.execute(f"""
                INSERT INTO {table}
                    (task_id, attempt_no, trace_id, question_text, answer_text,
                     model_score, final_score, score_source, status,
                     rubric_json, rubric_definition_json, rubric_weight,
                     feedback, rag_hit, source_task_ids, gap_ids)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                task_id, attempt_no, trace_id, question_text, answer_text,
                model_score, final_score, score_source, status,
                self._json_cell(rubric_json),
                self._json_cell(rubric_definition_json),
                rubric_weight, feedback, 1 if rag_hit else 0,
                source_ids, gap_ids,
            ))
            attempt_id = self.cursor.lastrowid

            # 4) 更新任务为**最新一次**结果
            cur = self.cursor.execute(
                "UPDATE study_tasks SET status=?, score=? WHERE id=?",
                (status, final_score, task_id))
            if cur.rowcount != 1:
                raise RuntimeError(f"更新任务 {task_id} 失败（rowcount={cur.rowcount}）")

            if submission:
                self.conn.execute(
                    "UPDATE competition_grading SET status='completed',attempt_id=?,"
                    "owner_token=NULL WHERE request_id=? AND owner_token=?",
                    (attempt_id, request_id, owner_token))

            self.conn.commit()
            return {"attempt_id": attempt_id, "attempt_no": attempt_no,
                    "score_source": score_source, "final_score": final_score}

        except Exception:
            # 任何一步失败：attempt 与 task 更新一起回滚
            self.conn.rollback()
            raise

    @staticmethod
    def _parse_attempt_row(row, cols):
        """把一行 attempt 解析成结构化 dict（JSON 字段还原成对象）。"""
        d = dict(zip(cols, row))

        def _load(key):
            raw = d.get(key)
            if raw is None:
                return None
            if isinstance(raw, (list, dict)):
                return raw
            try:
                return json.loads(raw)
            except Exception:
                return raw

        d["rubric"] = _load("rubric_json")
        d["rubric_definition"] = _load("rubric_definition_json")
        d["source_task_ids"] = _load("source_task_ids")
        d["gap_ids"] = _load("gap_ids")
        d["rag_hit"] = bool(d.get("rag_hit"))
        return d

    def get_assessment_attempts(self, task_id):
        """
        取某个任务的全部作答记录，按 attempt_no 升序。

        没有记录返回 []（旧任务 / 从未阅卷过）。
        """
        cols = [n for n, _ in self.ATTEMPT_COLUMNS]
        rows = self.cursor.execute(
            f"SELECT {', '.join(cols)} FROM {self.ATTEMPT_TABLE} "
            f"WHERE task_id=? ORDER BY attempt_no, id", (task_id,)).fetchall()
        return [self._parse_attempt_row(r, cols) for r in rows]

    def get_latest_assessment_attempt(self, task_id):
        """取最近一次作答；没有记录返回 None。"""
        cols = [n for n, _ in self.ATTEMPT_COLUMNS]
        row = self.cursor.execute(
            f"SELECT {', '.join(cols)} FROM {self.ATTEMPT_TABLE} "
            f"WHERE task_id=? ORDER BY attempt_no DESC, id DESC LIMIT 1",
            (task_id,)).fetchone()
        return self._parse_attempt_row(row, cols) if row else None

    def get_task_by_id(self, task_id):
        """
        按任务 ID 查询一条学习任务。

        返回的 dict 与 `get_tasks_by_plan()` **同一套列**（`_TASK_COLS`），
        因此也带 v6/v7 的 `gap_ids` / `provenance_status` / `source_task_ids`。
        评测落库要直接读这三列做快照，不能另写一套位置不一致的查询。
        """
        sql = ("SELECT " + ", ".join(self._TASK_COLS) +
               " FROM study_tasks WHERE id = ?")
        row = self.conn.execute(sql, (task_id,)).fetchone()
        if row is None:
            return None
        return dict(zip(self._TASK_COLS, row))

    # job_gap_reports.scorer 的取值。
    # 同一个 tis_score 列被两条线共用，尺度完全不同，必须标明来源，
    # 否则读的人无法解释 88.5 和 52.0 为什么差这么多。
    SCORER_TIS_KEYWORD = "tis_keyword"    # 关键词命中比例（core_pipeline，确定性、零 token）
    SCORER_MODEL_MATCH = "model_match"    # 大模型综合判断（run_hunter）

    def save_gap_report(self, report_id, trace_id, company, title,
                    tis_score, gap_df, audit: dict,
                    scorer=SCORER_TIS_KEYWORD, commit=True):
        """
        保存 gap 报告。

        scorer 标明 tis_score 的**尺度来源**，默认 tis_keyword 仅为兼容旧调用；
        新代码应显式传入（core_pipeline → tis_keyword，run_hunter → model_match）。
        """
        if not commit and not self.conn.in_transaction:
            raise ValueError("保存诊断需要外层事务")
        self.cursor.execute("""
            INSERT INTO job_gap_reports
                (report_id, trace_id, company, title, tis_score, scorer,
                gap_table_json, audit_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report_id, trace_id, company, title, float(tis_score), scorer,
            gap_df.to_json(orient="records", force_ascii=False),
            json.dumps(audit, ensure_ascii=False),
        ))
        if commit:
            self.conn.commit()
        return report_id

    def get_gap_report_by_trace(self, trace_id):
        self.cursor.execute("""
            SELECT report_id, trace_id, company, title, tis_score, scorer,
                gap_table_json, audit_json
            FROM job_gap_reports
            WHERE trace_id = ? ORDER BY created_at DESC LIMIT 1
        """, (trace_id,))
        row = self.cursor.fetchone()
        if row is None:
            return None
        cols = ["report_id", "trace_id", "company", "title", "tis_score", "scorer",
                "gap_table_json", "audit_json"]
        return dict(zip(cols, row))
    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            print("数据库连接已关闭！")

    # 考察题在 study_tasks 里的 task_type 标记。
    # 用常量而不是散落的字面量，避免查询条件写法不一致。
    EXAM_TASK_TYPE = "考察"

    # 注意：新增列只能**追加在末尾** —— 这里靠 zip 把查询结果映射成 dict，
    # 顺序即契约。插在中间会让所有老调用悄悄拿到错位的字段。
    _TASK_COLS = ["id", "plan_id", "phase_id", "phase_name", "day", "seq",
                  "task_type", "content", "expected_outcome", "status", "score",
                  "gap_ids", "provenance_status", "source_task_ids"]

    def _query_tasks(self, where_sql, params, include_exam=False):
        """按条件取任务行，统一列序与排序（day, seq）。"""
        sql = ("SELECT id, plan_id, phase_id, phase_name, day, seq, task_type, "
               "content, expected_outcome, status, score, "
               "gap_ids, provenance_status, source_task_ids FROM study_tasks "
               "WHERE " + where_sql)
        if not include_exam:
            # 默认排除考察题：否则"再考一遍"会把考察题本身当成学习内容。
            # 用前缀匹配而不是等值 —— task_type 可能带难度后缀（如「考察·hard」）。
            sql += " AND (task_type IS NULL OR task_type NOT LIKE ?)"
            params = tuple(params) + (self.EXAM_TASK_TYPE + "%",)
        sql += " ORDER BY day, seq"
        self.cursor.execute(sql, tuple(params))
        return [dict(zip(self._TASK_COLS, r)) for r in self.cursor.fetchall()]

    def get_tasks_by_plan(self, plan_id, include_exam=False):
        """取一个计划的全部学习任务（默认不含考察题）。"""
        return self._query_tasks("plan_id = ?", (plan_id,), include_exam)

    def get_tasks_by_day_range(self, plan_id, day_from, day_to, include_exam=False):
        """取某一天或某一段天的任务 —— 范围考察用（如 'day:1-3'）。"""
        return self._query_tasks(
            "plan_id = ? AND day >= ? AND day <= ?",
            (plan_id, int(day_from), int(day_to)), include_exam)

    def get_tasks_by_phase(self, plan_id, phase_order, include_exam=False):
        """取某个学习阶段（按 phase_order）的全部任务 —— 阶段考察用。"""
        sql = ("SELECT t.id, t.plan_id, t.phase_id, t.phase_name, t.day, t.seq, "
               "t.task_type, t.content, t.expected_outcome, t.status, t.score, "
               "t.gap_ids, t.provenance_status, t.source_task_ids "
               "FROM study_tasks t JOIN study_phases p ON t.phase_id = p.phase_id "
               "WHERE t.plan_id = ? AND p.phase_order = ?")
        params = [plan_id, int(phase_order)]
        if not include_exam:
            sql += " AND (t.task_type IS NULL OR t.task_type NOT LIKE ?)"
            params.append(self.EXAM_TASK_TYPE + "%")
        sql += " ORDER BY t.day, t.seq"
        self.cursor.execute(sql, tuple(params))
        return [dict(zip(self._TASK_COLS, r)) for r in self.cursor.fetchall()]

    def get_tasks_by_keyword(self, plan_id, keyword, include_exam=False):
        """按关键词匹配任务内容 —— 知识点考察用（如 'keyword:epoll'）。"""
        return self._query_tasks(
            "plan_id = ? AND (content LIKE ? OR expected_outcome LIKE ?)",
            (plan_id, "%" + keyword + "%", "%" + keyword + "%"), include_exam)

    def get_distinct_days(self, plan_id, include_exam=True):
        """取计划里出现过的所有 day（升序）。用于"最近 N 天"这类范围。"""
        sql = "SELECT DISTINCT day FROM study_tasks WHERE plan_id = ?"
        params = [plan_id]
        if not include_exam:
            sql += " AND (task_type IS NULL OR task_type NOT LIKE ?)"
            params.append(self.EXAM_TASK_TYPE + "%")
        sql += " ORDER BY day"
        self.cursor.execute(sql, tuple(params))
        return [r[0] for r in self.cursor.fetchall()]

    def next_seq(self, plan_id, day):
        """同一天里下一个可用的 seq（原计划任务占 1，考察题从 2 起）。"""
        row = self.cursor.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM study_tasks "
            "WHERE plan_id = ? AND day = ?", (plan_id, day)).fetchone()
        return row[0]

    def insert_exam_task(self, plan_id, phase_id, phase_name, day,
                         question, focus=None, difficulty=None,
                         source_task_ids=None, gap_ids=None,
                         provenance_status=None, commit=True):
        """
        把一道考察题写成 study_tasks 的一行（同一天追加，seq 自增）。

        为什么复用 study_tasks 而不是另建表：
          · 成绩只有一个载体，`export_plan` / 复测 / 统计都不用改口径；
          · 拆掉 UNIQUE(plan_id, day) 之后，"一天多题"天然被支持。
        `content` 存题目本身，`expected_outcome` 存考察要点，
        题目元信息（难度/来源范围）写进 task_type 的后缀，便于回看。

        v7 来源参数（全部可选，旧调用保持可用）
        -------------------------------------
        source_task_ids : 有效来源任务的 id 列表；落库为 JSON 数组。
                          传 None 表示"未记录"（旧行为），传 [] 表示"记录为无来源"。
        gap_ids         : 由来源任务**派生**的差距列表（调用方算好，本函数不推导）。
                          同样区分 None（不完整/未记录）与 []（明确为空）。
        provenance_status : exam_linked / exam_partially_linked /
                            exam_unknown_source / exam_unlinked

        为什么不在 DB 层推导 gap_ids：派生规则属于业务判断，放在 DB 层会让
        "落库"和"校验"两件事纠缠；这里只负责**如实保存**调用方给的结论。
        """
        if not commit and not self.conn.in_transaction:
            raise ValueError("保存考题需要外层事务")
        seq = self.next_seq(plan_id, day)
        ttype = self.EXAM_TASK_TYPE
        if difficulty:
            ttype = f"{self.EXAM_TASK_TYPE}·{difficulty}"

        def _dump(value):
            """None 原样保留（未记录）；列表序列化成 JSON。"""
            if value is None:
                return None
            if isinstance(value, str):
                return value
            return json.dumps(list(value), ensure_ascii=False)

        self.cursor.execute("""
            INSERT INTO study_tasks
                (plan_id, phase_id, phase_name, day, seq, task_type,
                 content, expected_outcome, source_task_ids,
                 gap_ids, provenance_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (plan_id, phase_id, phase_name, day, seq, ttype,
              question, focus or "",
              _dump(source_task_ids), _dump(gap_ids), provenance_status))
        if commit:
            self.conn.commit()
        return self.cursor.lastrowid
