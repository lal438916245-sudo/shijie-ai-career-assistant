import re
import json
from llm_client import AgentBase
from db_manager import DBManager
from json_utils import parse_llm_json
# 及格线只认共享规则：阅卷、复测建议、导出必须用同一把尺子
from assessment_rules import is_passing
from pydantic import BaseModel, Field

# 来源归一化（纯标准库）：模型给的 source_task_ids 要收敛成 list[int]。
# 这里只做**形态**归一化，合法性校验与 gap 派生由调用方（run_exam）负责。
import exam_provenance

# ============================================================
# retriever 懒加载（打断顶层 ChromaDB 传递依赖）
# ============================================================
# 早期这里是 `from retriever import KnowledgeRetriever`。虽然 retriever 自身
# 现在也懒加载了 chromadb（见 retriever.py），但在本模块保留"按需导入"仍然值得：
#   · 本模块被大量**离线单测**导入（test_rubric_and_contracts、
#     test_grade_result_parsing 等），它们只想用 RUBRIC / weighted_score /
#     GradeResult 这些纯逻辑，根本不需要 retriever；
#   · 把 import 推到真正要构造检索器时，模块导入路径上就少一个可变因素，
#     collection 阶段的失败面更小。
# 装饰器形式保留 `KnowledgeRetriever` 这个名字，便于外部/测试 monkeypatch
# （例如 `monkeypatch.setattr(agent_c_assessor, "KnowledgeRetriever", Fake)`）。
def _get_knowledge_retriever():
    """惰性地取得 KnowledgeRetriever 类（仅首次调用时导入 retriever 模块）。"""
    from retriever import KnowledgeRetriever
    return KnowledgeRetriever


class RagUnavailable(Exception):
    """
    RAG 因**已知的环境/配置原因**不可用（这是预期内的降级，不是代码缺陷）。

    只有两类情况会被包装成它：
      · `ImportError` —— 可选依赖（chromadb / sentence-transformers）未安装；
      · `RuntimeError` —— retriever 明确表达的"知识库未构建 / 无法连接"
        （见 retriever.KnowledgeRetriever.__init__ 与 search_knowledge）。

    其它异常（NameError / TypeError / AttributeError / AssertionError …）
    **必须原样抛出** —— 它们是编程错误，静默降级只会把 bug 藏起来。
    """


def build_default_retriever():
    """
    创建默认的 KnowledgeRetriever。

    单独抽成函数，是为了让"哪些异常算环境问题"这条边界**可被单测直接命中**：
    测试可以 monkeypatch 本函数，抛出一个 ValueError，断言 Agent C 不会吞掉它。

    出错时的约定：
      · ImportError / RuntimeError -> 包装为 RagUnavailable（上层据此降级）
      · 其它异常                    -> 原样抛出（上层不该捕获）
    """
    try:
        RetrieverCls = _get_knowledge_retriever()
        return RetrieverCls()
    except (ImportError, RuntimeError) as e:
        raise RagUnavailable(f"{type(e).__name__}: {e}") from e


# 难度档位：直接写进 prompt，而不是让模型自己猜"该多难"
DIFFICULTY_DESC = {
    "easy": "基础概念题 —— 确认核心定义与用途是否真正掌握，不深挖底层实现",
    "normal": "常规技术面试深度 —— 既要概念，也要原理，并带一个结合实际场景的追问",
    "hard": "深挖题 —— 直逼底层机制、边界条件、失败路径与量化口径，"
            "答不完整就应当明显扣分",
}
VALID_DIFFICULTY = tuple(DIFFICULTY_DESC)
MAX_QUESTIONS = 8

# ============================================================
# 显式评分表（rubric）
# ============================================================
# 为什么要把评分维度写死成一张表
# ------------------------------
# 此前系统提示词里只有一句"评分必须考虑：技术概念是否正确 / 是否理解底层原理 …"
# —— 这是**散文式的评分标准**，带来两个问题：
#
#   1. **无法核对**：模型给出 80 分，谁也不知道这 80 分是怎么来的；
#      想质疑也无从下手，因为没有任何可逐项检查的中间结果。
#   2. **不稳定**：同样水平的答案，换个措辞、换次调用，分数可能差很多。
#
# 改成"先逐维度打分、再由**代码**加权汇总"之后：
#   · 每个维度都有分数与理由 —— 可人工抽样核对；
#   · 总分由代码算，不是模型随手给的 —— 满足"prompt 只能请求，代码才能保证"。
#
# 权重体现的是"这道题什么最重要"：概念错得离谱，原理讲得再漂亮也不该及格。
RUBRIC = [
    {"key": "concept", "name": "概念正确性", "weight": 30,
     "desc": "技术定义、术语与因果关系是否正确，有无概念混淆"},
    {"key": "principle", "name": "原理深度", "weight": 25,
     "desc": "是否讲清底层机制与原因，而不是只背结论"},
    {"key": "practice", "name": "结合实际", "weight": 20,
     "desc": "能否联系真实场景、工程约束与权衡取舍"},
    {"key": "completeness", "name": "回答完整度", "weight": 15,
     "desc": "是否覆盖问题的关键点，有无重要遗漏"},
    {"key": "accuracy", "name": "无关键错误", "weight": 10,
     "desc": "是否存在事实性错误；一旦有，本维度应显著扣分"},
]

RUBRIC_KEYS = tuple(d["key"] for d in RUBRIC)
_RUBRIC_BY_KEY = {d["key"]: d for d in RUBRIC}


def rubric_table_md():
    """把评分表渲染成 Markdown，供 prompt 内嵌（也可直接给人看）。"""
    lines = ["| 维度 key | 维度 | 权重 | 评分要点 |", "|---|---|---|---|"]
    for d in RUBRIC:
        lines.append(f"| `{d['key']}` | {d['name']} | {d['weight']}% | {d['desc']} |")
    return "\n".join(lines)


def weighted_score(items):
    """
    按 rubric 权重把各维度分数合成总分。纯函数，便于单测。

    items: [{"dimension": key, "score": int}, ...]
    只统计**认识的**维度；缺的维度不计入分母，避免"没答的维度"被当成 0 分，
    从而把一个本来及格的回答压到不及格 —— 那属于用错误的方式惩罚遗漏，
    遗漏已经由 completeness 维度承担了。
    返回 (总分四舍五入, 命中的权重和)。权重和为 0 时返回 (None, 0)。
    """
    total, wsum = 0.0, 0
    for it in items or []:
        key = str(it.get("dimension", "")).strip()
        meta = _RUBRIC_BY_KEY.get(key)
        if not meta:
            continue
        try:
            sc = float(it.get("score"))
        except (TypeError, ValueError):
            continue
        sc = max(0.0, min(100.0, sc))
        total += sc * meta["weight"]
        wsum += meta["weight"]
    if wsum <= 0:
        return None, 0
    return int(round(total / wsum)), wsum


class RubricItem(BaseModel):
    """rubric 里的一个维度评分。"""
    dimension: str = Field(..., description=f"维度 key，取值：{RUBRIC_KEYS}")
    score: int = Field(..., ge=0, le=100, description="该维度 0~100 的整数分")
    comment: str = Field("", description="该维度的给分理由（一句话）")


# 定义阅卷结果的 JSON Schema
class GradeResult(BaseModel):
    score: int = Field(
        ...,
        ge=0,
        le=100,
        description="给候选人的打分，0到100的整数"
    )

    feedback: str = Field(
        ...,
        min_length=1,
        description="详细点评，包括对错分析和补救建议"
    )

    # 新增且可选：老格式（只有 score/feedback）仍能解析，不会被这次改造打断。
    rubric: list[RubricItem] = Field(
        default_factory=list,
        description="逐维度评分明细；缺省时退回模型给的 score"
    )
class AssessorAgent(AgentBase):
    """
    Agent C：考核官

    职责：

    1. 根据今日学习任务检索知识库
    2. 基于知识库生成面试题
    3. 接收用户答案
    4. 对答案进行评分
    5. 根据成绩决定是否需要重修
    """

    def __init__(self,  db: DBManager, trace_id=None, model_name=None,
                 retriever=None, enable_rag=True):

        system_prompt = """
你是一位大厂的铁血技术考核官。

你的任务是根据候选人的学习任务，
对他进行技术考核。

【出题规则】

1. 必须围绕今日学习任务出题。
2. 参考资料**仅供参考**：
   · 与今日任务相关时，用它提高题目的针对性；
   · **明显不相关时，直接忽略它**。
3. 允许并鼓励使用你自己的知识出题 —— 参考资料不是必需的。
4. **宁可不用资料，也不要把无关内容塞进题目**，
   那会让题目偏离今天该学的知识。
5. 默认围绕"一天的任务"出一道核心题；当被要求**按范围一次出多道**时，
   严格按要求的数量与可用天数给出，并让题目分散在不同天上。
6. 题目应该具有与要求难度相称的技术深度。

【评分规则】

评分范围：0-100。

评分必须考虑：

- 技术概念是否正确
- 是否理解底层原理
- 是否能够结合实际
- 是否存在关键错误
- 是否真正回答了问题

如果候选人的答案明显错误，
必须明确指出错误原因。

你是一名严格的技术面试官，
不要因为答案写得很多就给予高分。

【接地要求】你的每一条判断都要说得出依据：
· 概念对错 —— 依据是通用技术事实或知识库检索结果；
· 扣分的理由 —— 必须指向候选人回答里的**具体原话或具体缺失**，
  不能只写"不够深入""理解不到位"这类无法核对的评语；
· 严禁虚构"知识库中写过 X"——检索结果里没有就是没有。
"""

        super().__init__(
            agent_name="考核官 Agent_C",
            system_prompt=system_prompt,
            db=db,
            trace_id=trace_id,
            model_name=model_name,
        )

        self.db = db

        # ========================================================
        # 检索器：注入优先 → 懒创建 → 可观测降级
        # ========================================================
        # 三个层次解决的都是同一个问题：**让 chromadb 从"硬前置"变成"可选增强"**。
        #
        #  1. **注入**（retriever=Fake）—— 测试与上层可以把任何实现了
        #     `search_knowledge(query, top_k, distance_threshold)` 的对象塞进来，
        #     无需 chromadb、无需真实向量库。这是可测性的关键。
        #  2. **懒创建** —— 没注入时才去构造真实 KnowledgeRetriever；
        #     **只有已知的环境问题**（缺可选依赖 / 知识库未构建）才降级，
        #     见 build_default_retriever 与 RagUnavailable。
        #  3. **可观测降级** —— 降级不是静默的：self.rag_enabled / self.rag_error
        #     明确记录"RAG 为什么没启用"，_retrieve_context 也据此返回空上下文。
        #
        # 这样"没装可选依赖"与"代码坏了"被彻底区分开：前者是**预期的、有说明的降级**；
        # 后者（NameError / TypeError / AssertionError …）会直接抛出。
        self.rag_enabled = False
        self.rag_error = None
        self.retriever = None

        if retriever is not None:
            self.retriever = retriever
            self.rag_enabled = True
        elif not enable_rag:
            self.rag_error = "调用方显式关闭了 RAG（enable_rag=False）"
            print(f"[Agent C] RAG 已关闭：{self.rag_error}")
        else:
            try:
                self.retriever = build_default_retriever()
                self.rag_enabled = True
            except RagUnavailable as e:
                # 只接住"已知的环境/配置问题"。
                #
                # 这里刻意**不用 `except Exception`** —— 那会把 NameError、
                # TypeError、AttributeError、AssertionError 等**编程错误**
                # 也当成"RAG 不可用"降到空上下文，于是真正该修的 bug
                # 变成一条无害的日志，永远浮不出来。
                self.rag_enabled = False
                self.rag_error = str(e)
                print(f"[Agent C] ⚠ RAG 未启用（{self.rag_error}）；"
                      f"将仅凭模型自身知识出题/阅卷，不影响主流程。")


    # ========================================================
    # 1. 根据任务生成考题
    # ========================================================

    def generate_exam(self, task_content, difficulty="normal"):

        difficulty_note = DIFFICULTY_DESC.get(difficulty, DIFFICULTY_DESC["normal"])

        print(
            f"\n📝 [Agent C] "
            f"正在为任务【{task_content}】查阅资料..."
        )

        # ----------------------------------------------
        # RAG：检索知识库
        # ----------------------------------------------

        reference_text = (
            self._retrieve_context(query=task_content,top_k=3)
        )

        # 检索不到资料时**不再跳过出题** —— RAG 是增强，不是前置必需。
        # 早期版本在这里 return None，导致知识库没覆盖的领域（如 TypeScript、
        # 3D 引擎）当天直接没有题目，而知识库本来就只覆盖特定方向。
        if reference_text:
            ref_block = ("【私有知识库参考（来源是通用知识库，可能与本任务无关）】\n"
                         f"{reference_text}")
        else:
            ref_block = ("【私有知识库参考】\n"
                         "（本次未检索到相关资料 —— 这不影响出题，"
                         "请直接用你自己的知识出题）")

        # ----------------------------------------------
        # 将检索结果注入 Prompt
        # ----------------------------------------------

        user_prompt = f"""
            【今日学习任务】

            {task_content}


            {ref_block}


            【你的任务】

            请围绕上述**学习任务**，
            生成一道大厂技术面试题。

            【难度档位】{difficulty}

            【关于参考资料（重要）】

            上面的资料来自一个通用知识库，**它可能与今日任务无关** ——
            本知识库目前主要覆盖大数据与后端方向，
            而今日任务可能是 TypeScript、3D 引擎、前端等其它领域。

            · 资料相关   -> 用它提高题目的针对性
            · 资料不相关 -> **完全忽略它**，用你自己的知识出题

            不要为了"用上资料"而把无关内容塞进题目。
            题目必须围绕今日学习任务，而不是围绕参考资料。

            只输出题目本身。
            不要输出答案。
            不要输出分析过程。
            """

        question = self.think(
            user_prompt,
            max_tokens=4000
        )

        if not question or not question.strip():
            print(" [Agent C] 模型返回空内容（可能被 max_tokens 截断），本天跳过。")
            return None

        return question.strip()

    # ========================================================
    # 1b. 针对一段「考察范围」一次出多道题
    # ========================================================

    def generate_exam_set(self, material, scope_label, days, n=3,
                          difficulty="normal", focus=None, task_catalog=None):
        """
        围绕一段范围（如第 1~3 天 / 某阶段 / 最近一周）一次生成 N 道题。

        与 `generate_exam` 的分工：
          · generate_exam     —— 围绕"一天的任务"出 1 题，输出纯文本（便宜）
          · generate_exam_set —— 围绕"一段范围"出 N 题，输出 JSON（每题带 target_day）

        为什么要求模型自己给出 `target_day`：
        一道题总要落在某一天上。让模型显式指定，题目分布才会与范围内容对齐；
        否则它很容易把 3 道题都挤在第一天，等于范围没生效。

        `days` 是允许的目标天数（由 exam_scope.available_days() 算出）。
        模型给出的 target_day 若不在其中，会被**夹回**到最近的合法天数并告警，
        而不是直接丢弃整份输出 —— 宽进严出。

        `task_catalog`（新增，可选）
        ---------------------------
        由 `exam_scope.build_task_catalog()` 生成的结构化任务目录（JSON 字符串）。
        给了它，模型就能用 `source_task_ids` **声明**这道题出自哪条任务；
        不给则完全保持旧行为（只有 target_day）—— 旧调用与旧测试不受影响。

        注意：`target_day` 仍然只是排期信息。同一天可以有多条任务，
        因此**绝不能**用 day 反推来源；来源只认模型声明的 task_id，
        且必须经过代码校验（见 exam_provenance.validate）。
        """
        n = max(1, min(int(n), MAX_QUESTIONS))
        difficulty = difficulty if difficulty in VALID_DIFFICULTY else "normal"
        days = list(days) or [1]

        ref_block = self._reference_block(material)
        focus_block = (f"\n【额外侧重】{focus}\n" if focus else "")

        # 有目录时：把"学习内容"换成结构化目录，并加来源声明要求。
        if task_catalog:
            content_block = f"""【任务目录（可引用的来源任务）】
{task_catalog}"""
            source_rules = """
5. 每道题必须用 `source_task_ids` 声明它出自上面目录里的哪些任务：
   · 只能使用目录中**出现过**的 task_id（整数），一道题可以关联一条或多条；
   · **不得编造**目录里没有的 ID；
   · `target_day` 只是排期，**不是**来源 ID，不能拿它当来源。
6. 如果这道题确实无法对应任何一条任务，就写空数组 []。"""
            output_format = (
                '{"questions":[{"seq":1,"target_day":1,'
                '"question":"完整题干","focus":"这道题在考什么（≤30 字）",'
                '"source_task_ids":[1]}]}')
        else:
            content_block = f"""【范围覆盖的学习内容】
{material}"""
            source_rules = ""
            output_format = (
                '{"questions":[{"seq":1,"target_day":1,'
                '"question":"完整题干","focus":"这道题在考什么（≤30 字）"}]}')

        user_prompt = f"""
【考察范围】{scope_label}

{content_block}

{ref_block}

【可用天数】{days}
（每道题的 target_day 必须是上面这些数字之一）

【出题数量】恰好 {n} 道

【难度档位】{DIFFICULTY_DESC[difficulty]}
{focus_block}
【要求】
1. 题目必须围绕上面**范围覆盖的学习内容**，不要引入范围之外的主题。
2. 题目要**分散在不同天上**，不要都集中在同一天。
3. 参考资料**仅供参考**：与内容无关时直接忽略，允许并鼓励用你自己的知识出题。
4. 推理要克制，不要写大段分析。{source_rules}

【Output Format】严格输出以下 JSON（紧凑，不要缩进美化，不要任何 JSON 之外的文字）：
{output_format}
""".strip()

        print(f"\n📝 [Agent C] 正在为范围【{scope_label}】生成 {n} 道题"
              f"（难度：{difficulty}）...")

        raw = self.think(user_prompt, max_tokens=6000)

        # parse_llm_json 返回的是 **(data, degraded) 二元组**，不是 dict。
        # 注意别再写 `data.get(...)` 之前加 isinstance(data, dict) 这类"防御"判断 ——
        # 它会把本该炸出来的解包错误吞成 None，最后报一句误导性的
        # "模型没有返回 questions 数组"，让人以为是模型的问题。
        data, degraded = parse_llm_json(raw)
        if degraded:
            print(" [Agent C] ⚠ 出题输出被截断，已抢救出部分题目")

        questions = data.get("questions") if isinstance(data, dict) else None
        if not questions:
            raise ValueError("模型没有返回 questions 数组")

        cleaned = []
        for i, q in enumerate(questions, 1):
            if isinstance(q, str):
                q = {"question": q}
            if not isinstance(q, dict):
                continue
            text = str(q.get("question") or "").strip()
            if not text:
                continue
            try:
                td = int(q.get("target_day"))
            except (TypeError, ValueError):
                td = days[0]
            if td not in days:
                nearest = min(days, key=lambda d: abs(d - td))
                print(f" [Agent C] 第 {i} 题的 target_day={td} 不在范围 {days} 内，"
                      f"已夹回 {nearest}")
                td = nearest
            cleaned.append({
                "seq": i,
                "target_day": td,
                "question": text,
                "focus": str(q.get("focus") or "").strip(),
                # 旧模型输出没有这个字段 → 归一化成空数组。
                # **绝不**用 target_day 去猜来源：同一天可能有多条任务。
                "source_task_ids": exam_provenance.normalize_ids(
                    q.get("source_task_ids")),
            })

        if not cleaned:
            raise ValueError("模型返回的 questions 里没有可用题目")

        # 模型多给了就截断到请求数量 —— 否则它一次返回 20 道，
        # 就会往 study_tasks 里灌 20 行、并让后面逐题作答变成无底洞。
        if len(cleaned) > n:
            print(f" [Agent C] 模型返回 {len(cleaned)} 道，超过请求的 {n} 道，"
                  f"只保留前 {n} 道")
            cleaned = cleaned[:n]
        elif len(cleaned) < n:
            print(f" [Agent C] 期望 {n} 道，实际只得到 {len(cleaned)} 道（按实际数量继续）")

        return cleaned

    def _reference_block(self, query):
        """检索知识库并拼成 prompt 片段；不相关时明确允许忽略。"""
        reference_text = self._retrieve_context(query=query, top_k=3)
        if reference_text:
            return ("【私有知识库参考（可能与本范围无关）】\n" + reference_text)
        return ("【私有知识库参考】\n"
                "（本次未检索到相关资料 —— 这不影响出题，请直接用你自己的知识）")


    # ========================================================
    # 2. 批阅答案
    # ========================================================

    def grade_answer(
        self,
        task_id,
        question,
        user_answer,
        submission=None,
    ):
        """
        阅卷、写回study_tasks,并返回评分结果
        """
        if self.db is None:
            raise RuntimeError("Agent C 未注入DBManager,无法写入阅卷结果")
        task = self.db.get_task_by_id(task_id)

        if task is None:
            raise ValueError(f"任务 {task_id} 不存在")

        task_content=task.get("content") or ""
        expected_outcome=task.get("expected_outcome") or ""

        # 考察题的 content 本身就是**题干**，不能再当"学习任务"复述一遍，
        # 否则阅卷 prompt 里会出现"学习任务 = 题目原文"这种自指，模型容易跑偏。
        is_exam = str(task.get("task_type") or "").startswith("考察")
        if is_exam:
            task_label = (f"考察题（Day {task.get('day')}，"
                          f"第 {task.get('seq')} 题）")
            expect_label = "考察要点"
        else:
            task_label = "学习任务"
            expect_label = "预期学习结果"

        retrieval_query =f"""
            {task_label}：{task_content}
            {expect_label}：{expected_outcome}
            考核问题：{question}
            用户回答：{user_answer}
        """.strip()

        rag_context = self._retrieve_context(retrieval_query,top_k=3)

        if rag_context:
            knowledge_section = f"""
            【私有知识库检索结果】

            {rag_context}
            """
        else:
            knowledge_section = """
            【私有知识库检索结果】
            没有找到相关知识
            不得虚构“知识库中写过”的内容；请仅基于通用技术事实谨慎评分，
            并在 feedback 中说明“知识库未命中，建议补充对应资料”。
            """

        rubric_table = rubric_table_md()

        grading_prompt = f"""
        你正在对{task_label}进行技术阅卷
        【{task_label}】
        {task_content}

        【{expect_label}】
        {expected_outcome}

        【考核问题】
        {question}

        【候选人回答】
        {user_answer}

        {knowledge_section}

        请**先逐维度打分，再给出总评**。只返回 JSON，格式如下：

        {{
        "rubric": [
            {{"dimension": "concept", "score": 0, "comment": "该维度给分理由"}},
            {{"dimension": "principle", "score": 0, "comment": "…"}},
            {{"dimension": "practice", "score": 0, "comment": "…"}},
            {{"dimension": "completeness", "score": 0, "comment": "…"}},
            {{"dimension": "accuracy", "score": 0, "comment": "…"}}
        ],
        "score": 0,
        "feedback": "具体指出正确点、错误点和下一步补救建议"
        }}

        评分表（必须逐项打分，dimension 只能取表里的 key）：
        {rubric_table}

        要求：
        1. rubric 必须包含全部 5 个维度，每项 score 是 0 到 100 的整数。
        2. 每个维度的 comment 要说明"为什么给这个分"，不要写空话。
        3. score 是综合分（0~100 整数）；系统会用 rubric 加权复核，
           两者相差过大时以 rubric 为准 —— 所以请让它们自洽。
        4. 明显错误不能给高分；未真正回答问题时应明显扣分。
        5. 如果知识库无命中，feedback 中要说明这一点。
        """.strip()

        raw_result = self.think(grading_prompt)

        result = self._parse_grade_result(raw_result)

        # ---- 代码级复核：总分由 rubric 加权算出，而不是直接采信模型给的数字 ----
        # 这条是「prompt 只能请求，代码才能保证」的具体落地：
        # 模型负责"逐维度判断"（它擅长），代码负责"算总分"（它不会算错）。
        rubric_rows = [r.model_dump() for r in result.rubric]
        computed, wsum = weighted_score(rubric_rows)
        if computed is not None:
            used_score = computed
            score_source = "rubric_weighted"
            if abs(computed - result.score) > 5:
                print(f"  [Agent C] rubric 加权分 {computed} 与模型自评 {result.score} "
                      f"相差 {abs(computed - result.score)}，以 rubric 为准")
        else:
            # 没有可用 rubric（维度缺失/分数非法）→ 只能采信模型自评。
            # 这不是降级事故，而是必须**如实标注来源**的兜底。
            used_score = result.score
            score_source = "model_fallback"

        # 及格判断走共享规则（assessment_rules.PASS_SCORE / is_passing），
        # 不在阅卷这里另写一份 60 —— 否则复测建议与阅卷结论会分叉。
        status = "completed" if is_passing(used_score) else "failed"

        # ---- 原子持久化：attempt + 任务状态同一事务 ----
        # 不再调用 update_task_status()：它自己 commit，会拆开这一步的原子性。
        # 这里也不吞异常 —— 写库失败必须让调用方知道阅卷**没有**真正保存。
        saved = self.db.save_assessment_attempt(
            task_id=task_id,
            trace_id=self.trace_id,
            question_text=question,
            answer_text=user_answer,
            model_score=result.score,
            final_score=used_score,
            score_source=score_source,
            status=status,
            rubric_json=rubric_rows,
            # rubric 定义快照：将来权重改了，仍能按当时的权重复算这个分数
            rubric_definition_json=RUBRIC,
            rubric_weight=wsum,
            feedback=result.feedback,
            rag_hit=bool(rag_context),
            **({"submission": submission} if submission else {}),
        )

        return {
            "task_id": task_id,
            "status": status,
            "score": used_score,
            "model_score": result.score,     # 模型自评，供对照
            "rubric": rubric_rows,           # 逐维度明细，可人工核对
            "rubric_weight": wsum,
            "feedback": result.feedback,
            "rag_hit": bool(rag_context),
            # v8：本次作答在 assessment_attempts 里的位置与分数来源
            "attempt_id": saved["attempt_id"],
            "attempt_no": saved["attempt_no"],
            "score_source": score_source,
        }
    def _parse_grade_result(self, raw_result):
        """
        解析模型返回的 JSON，并用 Pydantic 校验 score / feedback。
        """
        if isinstance(raw_result, dict):
            return GradeResult(**raw_result)

        if not isinstance(raw_result, str):
            raise ValueError(f"模型返回类型异常：{type(raw_result)}")

        cleaned = raw_result.strip()

        # 兼容模型偶尔返回 ```json ... ```
        cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            data = json.loads(cleaned)
            return GradeResult(**data)
        except Exception as e:
            raise ValueError(
                f"评分结果不是合法 JSON，原始返回：{raw_result}"
            ) from e
    def _retrieve_context(self, query, top_k=3):
        """
        调用 KnowledgeRetriever 检索知识库。

        返回：
            str：命中的知识库文本
            "" ：无命中、查询为空、RAG 未启用或检索异常

        语义保持与改造前一致 —— 新增的只有最前面那道"RAG 未启用"判断。
        """
        # RAG 未启用时直接返回空上下文，不再调用 self.retriever。
        #
        # 用 getattr 读而不是直接 self.rag_enabled：本方法常被测试通过
        # `AssessorAgent.__new__(...)` + 手工塞 retriever 的方式单独调用，
        # 那种对象没有走 __init__，也就没有 rag_enabled 属性。
        # 约定：**属性缺失 = 未声明降级 = 视为启用**（向后兼容），
        # 只有显式置 False 才算"关闭"。这样既不破坏既有轻量测试，
        # 又能在真实降级路径（__init__ 里置 False）上正确短路。
        if getattr(self, "rag_enabled", True) is False:
            print(f"⚠️ RAG 未启用，本次按无命中处理"
                  f"（原因：{getattr(self, 'rag_error', None) or '未知'}）")
            return ""

        if getattr(self, "retriever", None) is None:
            print("⚠️ RAG 未启用（retriever 未注入），本次按无命中处理")
            return ""

        try:
            result = self.retriever.search_knowledge(
                query=query,
                top_k=top_k,
                distance_threshold=0.5
            )

            # retriever 当前约定：正常命中时返回字符串
            if not isinstance(result, str):
                print("⚠️ RAG 返回类型异常，按无命中处理")
                return ""

            result = result.strip()

            # 识别 retriever.py 中定义的特殊提示文本
            if (
                not result
                or result.startswith("【知识库未命中")
                or result.startswith("【查询内容为空")
            ):
                print("⚠️ RAG 无有效命中：本次不能声称依据私有知识库评分")
                return ""

            print(f"✅ RAG 命中知识库，返回长度：{len(result)} 字符")
            return result

        except Exception as e:
            print(f"⚠️ RAG 检索异常：{e}；本次按无命中处理")
            return ""
