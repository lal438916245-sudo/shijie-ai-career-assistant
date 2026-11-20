from dotenv import load_dotenv
import time
import os
import uuid
from db_manager import DBManager 
from paths import ROOT as _PROJECT_ROOT

# 只读取**当前项目根目录**的 .env。
# 不使用裸 `load_dotenv()`：后者会隐式向上搜索，可能在换 cwd、测试插件或
# 宿主工具环境中读到不属于本项目的配置。显式路径让 Key 的来源可预测、可审计。
PROJECT_ENV_PATH = os.path.join(_PROJECT_ROOT, ".env")
load_dotenv(dotenv_path=PROJECT_ENV_PATH)

# ============================================================
#  openai 懒加载（lazy import）
# ============================================================
# 为什么不在文件顶层 `from openai import OpenAI`
# --------------------------------------------
# `openai` 虽然列在 requirements.txt 的"核心依赖"里，但它是**只有真正调用
# 大模型时才需要**的东西。把 import 放在模块顶层，会带来两个真实问题：
#
#   1. **纯离线场景被无谓地拖下水**：导入本模块的测试（如 test_rubric_and_
#      contracts.py 经由 agent_c_assessor 间接导入）只是想读常量、跑纯函数，
#      却因为 openai 没装而整个 collection 失败。
#   2. **报错位置具有误导性**：用户会看到 `ImportError: No module named
#      'openai'` 出现在"导入某个 Agent 模块"时，而不是出现在"真的要用模型"
#      时 —— 前者看起来像代码坏了，后者才是实话。
#
# 所以这里把 import 推迟到**创建客户端的那一刻**，并给出可操作的提示。
# 模块级 `OpenAI` 这个名字仍然保留（见下方 __getattr__），
# 这样 `from llm_client import OpenAI` 的老写法也不会被这次改造打断。
_OPENAI_IMPORT_ERROR = (
    "缺少依赖：openai。\n"
    "  它是调用大模型所必需的，但只有当**真正创建客户端**时才会用到。\n"
    "  修复：pip install -r requirements.txt\n"
    "  说明：纯离线功能（常量、纯函数、离线单测）无需 openai，可直接使用。"
)


def _import_openai():
    """
    惰性地导入 OpenAI 类。

    只在需要实例化客户端时调用。导入失败时抛出**带修复指引**的 ImportError，
    而不是把裸的 `No module named 'openai'` 抛给用户。
    """
    try:
        from openai import OpenAI as _OpenAI
    except ImportError as e:
        raise ImportError(_OPENAI_IMPORT_ERROR) from e
    return _OpenAI


def __getattr__(name):
    """
    模块级惰性属性：`llm_client.OpenAI` 首次访问时才真正导入 openai。

    PEP 562 模块 __getattr__。保留这条路径是为了兼容既有写法
    （例如 `from llm_client import OpenAI`），同时不把 openai 变成硬依赖。
    """
    if name == "OpenAI":
        value = _import_openai()
        globals()["OpenAI"] = value  # 缓存，后续访问不再走这里
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# ============================================================
#  模型名解析（AI_MODEL 参数化）
# ============================================================
# 早期实现把模型名 "deepseek-v4-flash" 硬编码在每个 Agent 的签名默认值里，
# 换模型要改 5 个文件 —— 而且很容易漏。这里收敛成**单点解析**：
#
#     显式传参  >  环境变量 AI_MODEL  >  内置默认
#
# 这样换模型只改 .env 一行；需要时也能在单个 Agent 上显式覆盖。
DEFAULT_MODEL = "deepseek-v4-flash"


def resolve_model_name(explicit=None):
    """
    解析最终使用的模型名。

    优先显式传参（便于单点覆盖 / 测试注入），其次读环境变量 `AI_MODEL`，
    最后回落到内置默认 —— 保证没配 .env 的旧用户行为完全不变。
    """
    return explicit or os.getenv("AI_MODEL") or DEFAULT_MODEL


class RealLLMCallBlocked(RuntimeError):
    """
    在**测试进程内**、未获显式授权时试图发起真实模型调用。

    为什么需要这个异常类型
    ----------------------
    光靠 pytest 的 skip 标记不够：清空 `addopts`、直接指定测试文件、
    或用 `-m integration` 都能绕过收集阶段的过滤。只要本机配了 `AI_API_KEY`，
    一条"忘了打标记"的用例就会真的发网络请求、烧 token。
    所以这里再加一道**运行时**保险：调用发生的那一刻再拦一次。
    """


# 显式授权开关。只有严格等于 "1" 才算打开 ——
# 0 / true / yes / TRUE 一律视为未授权（避免"看着像开"的模糊判断）。
REAL_LLM_ENV = "RUN_REAL_LLM_TESTS"

# **仅供 pytest 内部使用**的第三把钥匙：当前测试项是否带了 `needs_llm`。
#
# 这不是用户接口：不要写进 .env、不要让用户手工设置。
# 它由 tests/conftest.py 的 autouse 夹具在每个用例开始时按 marker 发放、
# 用例结束自动清除。存在的意义：
#   RUN_REAL_LLM_TESTS=1 是"我允许这次会话花钱"，不是"每一个测试都可以花钱"。
#   一条没打 needs_llm 的用例（例如忘了标、或临时写的探针）不该因为会话级
#   开关而获得真实调用能力。
ITEM_AUTH_ENV = "PYTEST_REAL_LLM_ITEM_AUTHORIZED"


def llm_key_present():
    """只表示 Key 是否存在，**不代表授权**。"""
    return bool(os.getenv("AI_API_KEY"))


def real_llm_opted_in():
    """用户级许可：仅当 RUN_REAL_LLM_TESTS 严格等于 "1"。"""
    return os.getenv(REAL_LLM_ENV) == "1"


def real_llm_item_authorized():
    """
    测试项级许可：仅当 conftest 为**当前这个用例**发放了内部授权。

    非 pytest 进程不会设置它（也不需要）。
    """
    return os.getenv(ITEM_AUTH_ENV) == "1"


def real_llm_calls_authorized():
    """
    用户级授权 = 有 Key **且** 显式 opt-in。

    注意：pytest 内还**额外**需要 `real_llm_item_authorized()`（见下）。
    单看这个函数会漏掉"这条测试有没有标 marker"这一层。
    """
    return llm_key_present() and real_llm_opted_in()


def _running_under_pytest():
    """
    是否处于某个测试用例的执行期间。

    pytest 会为每个用例设置 `PYTEST_CURRENT_TEST`（形如
    "tests/test_x.py::test_y (call)"），用例结束后清除。

    为什么用它当开关，而不是无条件拦截
    ----------------------------------
    这是**测试安全门**，不是产品功能开关。脚本（run_hunter / pipeline_full）
    正常运行时不该被要求设置 `RUN_REAL_LLM_TESTS`；只有"在 pytest 里"才需要。
    """
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


def assert_real_llm_allowed(agent_name="?"):
    """
    真实调用的最后一道闸。必须在**碰任何 client 之前**调用。

    非 pytest 进程直接放行（生产脚本行为不变）。

    pytest 进程内需要**三件同时成立**：
      1. AI_API_KEY                     —— 有能力调用
      2. RUN_REAL_LLM_TESTS=1           —— 用户允许这次会话花钱
      3. 当前测试项带 needs_llm marker  —— 这条测试被显式标记为"要真跑模型"
         （由 conftest 的 autouse 夹具转成进程内授权）

    第 3 条是后补的：只有前两条时，任何一条**没打 marker** 的用例
    （临时探针、忘了标的测试）只要会话开了 opt-in 就能真实调用 ——
    那是"全局许可"被当成了"逐条许可"。
    """
    if not _running_under_pytest():
        return
    if (llm_key_present() and real_llm_opted_in()
            and real_llm_item_authorized()):
        return

    missing = []
    if not llm_key_present():
        missing.append("AI_API_KEY")
    if not real_llm_opted_in():
        missing.append(f"{REAL_LLM_ENV}=1")
    if not real_llm_item_authorized():
        missing.append("当前测试项没有 needs_llm marker"
                       "（请给测试加 @pytest.mark.needs_llm）")

    raise RealLLMCallBlocked(
        f"[LLM 安全门] 测试进程内拒绝发起真实模型调用（Agent={agent_name}）。\n"
        f"  缺少授权条件：\n    · " + "\n    · ".join(missing) + "\n"
        f"  真实调用会产生网络请求并消耗 token。\n"
        f"  如确实要跑真实模型用例，需要**三件事同时成立**：\n"
        f"    1) 给测试加 @pytest.mark.needs_llm\n"
        f"    2) 设置 {REAL_LLM_ENV}=1（严格等于 1）\n"
        f"    3) 配置 AI_API_KEY\n"
        f"  注意：仅有 AI_API_KEY，或全局开启 {REAL_LLM_ENV}，"
        f"都不会自动给某条测试授权。"
    )


class AgentBase:
    """
    大模型调用中枢（The LLM Client）
    负责：
    1.调用大模型
    2.API异常重试
    3.Token统计
    4.调用耗时统计
    5.自动记录Agent测试结果
    """

    def __init__(self, agent_name,system_prompt, model_name=None,db=None,trace_id=None):
        print(f"[Agent:{agent_name}] 正在初始化大脑中枢...")
        self.agent_name = agent_name
        # model_name 默认 None → 交给 resolve_model_name 走 "env > 内置默认"
        self.model_name = resolve_model_name(model_name)
        self.system_prompt = system_prompt
        self.db = db
        self.trace_id = trace_id 

        

        # 从环境变量中安全读取 API Key 和 URL
        # 如果读取不到，程序会报错，防止你带着空的 Key 裸奔
        api_key = os.getenv("AI_API_KEY")
        base_url = os.getenv("AI_BASE_URL")

        if not api_key:
                raise ValueError(" 致命错误：找不到 API Key！请检查 .env 文件是否配置正确。")

        # =========================
        # 创建 OpenAI 客户端
        # =========================
        # 注意顺序：**先校验 API Key，再导入 openai**。
        # 这样"没配 Key"和"没装 openai"是两个互不掩盖的、各自明确的错误，
        # 而不是在所有情况下都先报 import 失败。
        OpenAI = _import_openai()
        self.client = OpenAI(api_key=api_key, base_url=base_url)


    def think(self, user_prompt, max_retries=3, max_tokens=8000, max_truncations=2):
            """
            调用大模型，并自动记录本次 Agent Evaluation

            第一行是**安全门**：在 pytest 进程内，必须同时具备
            `AI_API_KEY`、`RUN_REAL_LLM_TESTS=1` 与**当前测试项的 needs_llm 授权**
            才放行；否则直接抛 `RealLLMCallBlocked` ——
            在组装 messages、碰 client 之前就停，因此不会产生任何网络请求。
            """
            assert_real_llm_allowed(self.agent_name)

            session_id = self.trace_id or str(uuid.uuid4())

            # =========================
            # 1. 组装 Prompt
            # =========================
            messages = [
                {"role": "system", "content": self.system_prompt},#告诉 AI：你是谁，你应该怎么做
                {"role": "user", "content": user_prompt}#告诉 AI：我现在问你什么
            ]

            retries = 0

            # 截断自动扩容。
            # 关键认知：max_tokens 是**上限不是预分配** —— 调大它在正常情况下不花额外钱，
            # 只在真的输出更长时才会用到。所以默认值宁可给足，撞到截断时再自动扩容。
            truncations = 0
            budget = max_tokens
            TRUNCATION_LIMIT = max_truncations
            BUDGET_CAP = 16000          # 扩容上限

            # 用于记录整个请求开始时间
            start_time = time.perf_counter()

            while retries < max_retries:
                try:
                    print(f" [{self.agent_name}] 正在思考中... (尝试 {retries + 1}/{max_retries})")

                

                    # =========================
                    # 2. 调用大模型
                    # =========================
                    response = self.client.chat.completions.create(
                        model=self.model_name,
                        messages=messages,
                        temperature=0.7, # 创造力指数，0.7 适合写计划
                        max_tokens=budget  # 上限而非预分配，见下方截断扩容逻辑
                    )

                    latency_ms = int(
                                            (time.perf_counter() - start_time) * 1000
                                        )
                    
                    # 提取 AI 的回答
                    ai_reply = response.choices[0].message.content
                    finish_reason = response.choices[0].finish_reason

                    # 提取 Token 消耗（用于对账，大厂必备视角）
                    # 注意：必须在截断判断之前算出来，否则截断分支记审计时会用到未定义变量
                    tokens_used = 0
                    if response.usage:
                        tokens_used = response.usage.total_tokens

                    if finish_reason == "length":
                        # 截断 = 这次的内容不可用（JSON 必然残缺）。
                        # 先记一笔审计，再扩容重试 —— 否则这次调用白烧的 token 无人对账。
                        self._safe_log(session_id, user_prompt, ai_reply or "",
                                       tokens_used, latency_ms,
                                       status="truncated",
                                       error_message=f"finish_reason=length, budget={budget}")

                        if truncations < TRUNCATION_LIMIT and budget < BUDGET_CAP:
                            truncations += 1
                            new_budget = min(int(budget * 1.5) + 1000, BUDGET_CAP)
                            print(f"  [{self.agent_name}] 输出被 max_tokens({budget}) 截断，"
                                  f"自动扩容到 {new_budget} 重试（第 {truncations}/{TRUNCATION_LIMIT} 次）")
                            budget = new_budget
                            continue

                        print(f"  [{self.agent_name}] 已扩容 {truncations} 次仍被截断"
                              f"（budget={budget}），返回截断内容 —— 调用方需要处理解析失败。")

                    print(f" [{self.agent_name}] 思考完毕！(消耗 Token: {tokens_used},请求耗时：{latency_ms}ms)")
                    print(f"Token详细信息:{response.usage }")

                    # =========================
                    # 6. 自动写入数据库（best-effort：失败不影响结果）
                    # =========================
                    self._safe_log(session_id, user_prompt, ai_reply,
                                   tokens_used, latency_ms)

                    #返回AI回答
                    return ai_reply
 
                except Exception as e:

                    latency_ms=int(
                    (time.perf_counter()-start_time)
                    *1000
                )
                    
                    print(f" [{self.agent_name}] 大脑短路 (API 报错): {e}")
                    retries += 1
                    
                    # =========================
                    # 最后一次失败
                    # =========================

                    if retries >= max_retries:

                        # 记录失败测试（同样是 best-effort）
                        self._safe_log(session_id, user_prompt, "", 0,
                                       latency_ms, status="failed",
                                       error_message=str(e))
                        return "ERROR: Agent 思考失败，请检查网络或 API Key。"

                    time.sleep(2)

    def _safe_log(self, session_id, user_prompt, output_text, total_tokens,
                  latency_ms, status="success", error_message=None):
        """
        写 Agent 评测记录（审计日志）。
        这是外部副作用，失败只警告 —— 绝不影响 think() 的返回值，也绝不触发重试。
        """
        if not self.db:
            return
        try:
            self.db.insert_evaluation(
                session_id=session_id,
                agent_name=self.agent_name,
                model_name=self.model_name,
                system_prompt=self.system_prompt,
                user_prompt=user_prompt,
                input_data=user_prompt,
                output_text=output_text,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                status=status,
                error_message=error_message,
            )
        except Exception as e:
            print(f" ⚠️ 写评测记录失败（不影响本次结果）: {e}")
            try:
                self.db.conn.rollback()
            except Exception:
                pass

# ==========================================
#  测试区：唤醒你的第一个 Agent！
# ==========================================
if __name__ == "__main__":
    
    # 1. 给它设定人设 (System Prompt)
    sys_prompt = "你是一个极其严厉、毒舌的腾讯技术总监。候选人向你提问时，你总是先挑刺，再给出专业的建议。"
    
    # 2. 实例化 Agent
    interviewer_agent = AgentBase(agent_name="毒舌总监", system_prompt=sys_prompt)
    
    # 3. 你对它说的话
    my_question = "总监好，我目前只会写基础的 Python 循环，我想一个月后面试腾讯后端，我该怎么办？"
    
    # 4. 调用 think 方法，等待奇迹发生！
    print(f"\n 我：{my_question}")
    reply = interviewer_agent.think(my_question)
    print(f"\n {reply}")
