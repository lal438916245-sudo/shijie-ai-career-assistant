import os

# 必须在 import chromadb / sentence-transformers 之前设置
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")   # 万一要下载就走国内镜像
os.environ.setdefault("HF_HUB_OFFLINE", "1")                    # 模型已在本地缓存，跳过联网校验

from paths import CHROMA_DIR

# ============================================================
# chromadb 懒加载 + 优雅降级
# ============================================================
# RAG 是**可选增强**，不是核心链路的前置条件：
# requirements.txt 里 chromadb / sentence-transformers 是注释掉的可选项，
# 不装也能跑通 A→B→C 全流程（只是 Agent C 出题时没有知识库增强）。
#
# 但早期实现把 `import chromadb` 放在模块顶层，导致：
#   · 任何 `from retriever import KnowledgeRetriever` 都会连带要求 chromadb；
#   · Agent C 经由它被间接拖下水 —— 连"只想 import 一下常量"都会失败；
#   · 报错时机误导：看起来像"代码坏了"，实际只是"没装可选依赖"。
#
# 所以这里把 import 推迟并按需触发，同时把失败**真实记录下来**
# （见 CHROMA_IMPORT_ERROR），让上层能区分"缺依赖"和"真的检索不到"。
_CHROMA_IMPORT_ERROR = None


def _require_chromadb():
    """
    惰性导入 chromadb 与 embedding_functions。

    成功返回 (chromadb, embedding_functions)；失败抛出带修复指引的 ImportError。
    """
    global _CHROMA_IMPORT_ERROR
    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError as e:
        _CHROMA_IMPORT_ERROR = str(e)
        raise ImportError(
            "缺少可选依赖 chromadb / sentence-transformers —— 它们只用于 RAG 知识库增强。\n"
            "  核心流程（A→B→C）不依赖它们，可以照常运行。\n"
            "  若要启用知识库增强：\n"
            "    1) 在 requirements.txt 中取消 chromadb / sentence-transformers 两行注释\n"
            "    2) pip install -r requirements.txt\n"
            "    3) python scripts/build_vector_db.py\n"
            f"  原始错误：{e}"
        ) from e
    return chromadb, embedding_functions


def chroma_available():
    """探测 chromadb 是否可用（供上层决定是否启用 RAG，而不必捕获异常）。"""
    try:
        _require_chromadb()
        return True
    except ImportError:
        return False


class KnowledgeRetriever:
    """
    RAG 检索中台

    职责：
    1. 连接 ChromaDB
    2. 把用户查询转换成向量
    3. 搜索最相关的知识块
    4. 根据距离进行过滤
    5. 返回给 Agent C
    """

    def __init__(
        self,
        db_path=CHROMA_DIR,
        collection_name="career_knowledge"
    ):

        print("🔍 [Retriever] 正在连接私有知识库...")

        # 只有**真的要连知识库**时才需要 chromadb。
        # 注意：这里让缺依赖的 ImportError **原样抛出**（带修复指引），
        # 而不是降级成 RuntimeError —— 上层 `_retrieve_context` 会把异常
        # 记成"检索异常并按无命中处理"，那是"运行时检索失败"的语义；
        # 而"根本没装可选依赖"属于**配置问题**，两者不该混为一谈。
        chromadb, embedding_functions = _require_chromadb()

        self.client = chromadb.PersistentClient(
            path=db_path
        )

        self.ef = (
            embedding_functions
            .SentenceTransformerEmbeddingFunction(
                model_name="shibing624/text2vec-base-chinese"
            )
        )

        try:

            self.collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.ef
            )

        except Exception as e:

            raise RuntimeError(
                f"知识库连接失败，请先运行 build_vector_db.py\n"
                f"具体错误：{e}"
            )

        print(
            f"✅ [Retriever] 已连接知识库："
            f"{collection_name}"
        )


    def search_knowledge(
        self,
        query,
        top_k=2,
        distance_threshold=0.5
    ):
        """
        根据用户查询检索知识库。

        参数：
            query:
                当前学习任务/问题

            top_k:
                最多返回多少个知识块

            distance_threshold:
                距离阈值。
                距离越小通常代表越相似。
        """

        if not query or not query.strip():
            return "【查询内容为空，无法检索知识库】"

        print(
            f"\n🧠 [Retriever] 正在检索：{query}"
        )

        results = self.collection.query(
            query_texts=[query],
            n_results=top_k
        )

        docs = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]

        valid_docs = []

        for doc, dist in zip(docs, distances):

            print(
                f"   📏 距离：{round(dist, 4)}"
            )

            if dist <= distance_threshold:

                valid_docs.append(doc)

                print(
                    f"   ✅ [命中] {doc[:50]}..."
                )

            else:

                print(
                    f"   🚫 [舍弃] 距离过大"
                )

        if not valid_docs:

            return (
                "【知识库未命中相关内容】"
                "请不要编造知识库中不存在的内容。"
            )

        return "\n\n".join(valid_docs)
    

# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":

    retriever = KnowledgeRetriever()

    test_queries = [
        "C++虚函数和多态的底层原理",
        "C++运行时多态是如何实现的？",
        "什么是虚函数表 vtable？",
        "AARRR漏斗模型是什么？",
        "怎么炒股赚钱？"
    ]

    print("\n")
    print("=" * 70)
    print("🧪 Retriever RAG 检索测试")
    print("=" * 70)

    for query in test_queries:

        print("\n")
        print("=" * 70)

        context = retriever.search_knowledge(
            query=query,
            top_k=2
        )

        print("\n📦 返回给 Agent C 的 Context：")
        print("-" * 70)
        print(context)