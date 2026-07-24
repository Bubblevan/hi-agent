import hashlib
from dataclasses import dataclass, field
from typing import Any

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())

# 当前每个环节的产出都是"调用方负责填字段"。loader 产出 `Document`，
# 但 `checksum` 是 loader 自己算还是调用方传？
# splitter 产出 `Chunk`，但 `chunk_id` 谁生成？
# 如果每个环节的输入/输出类型不强制，很快就会出现 `dict` 透传——
# 某个环节往 `metadata` 里塞了一个字段，下游依赖它，但没有任何地方声明这个契约。


## 解法：每个类型自带工厂 + 唯一入口
# 四个对象各自只有**一个合法构造路径**。外部不能直接 `Document(...)` 或 `Chunk(...)`
# 必须通过工厂方法。这样每个字段的来源和约束被锁死在类型内部。

@dataclass(frozen=True)  # 不可变——防止下游偷偷改
class Document:
    document_id: str
    user_id: str
    namespace: str
    source: str          # 原始路径或 URL
    text: str            # 全文
    checksum: str        # sha256(text)，构造时自动算
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def build(
        *,
        user_id: str,
        namespace: str,
        source: str,
        text: str,
        document_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Document":
        """
        loader 的唯一入口。
        document_id 不传则用 source + checksum 确定性生成。
        checksum 自动计算，调用方不用管。
        """
        checksum = _sha256(text)
        doc_id = document_id or _sha256(f"{source}:{checksum}")
        return Document(
            document_id=doc_id,
            user_id=user_id,
            namespace=namespace,
            source=source,
            text=text,
            checksum=checksum,
            metadata=metadata or {},
        )

# 边界：loader 的返回值类型声明为 `Document`。
# 调用方不需要知道 `checksum` 怎么算的、`document_id` 怎么生成的。
# loader 内部拿到原始文本后，调 `Document.build()`完事

@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    user_id: str
    namespace: str
    content: str
    position: int        # 在文档中的序号，0-based，单调递增
    start_char: int
    end_char: int
    heading_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def build(
        *,
        document: Document,
        content: str,
        position: int,
        start_char: int,
        end_char: int,
        heading_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Chunk":
        """
        splitter 的唯一入口。
        传入完整 Document（不是 document_id 字符串），
        因为 chunk_id 依赖 document.checksum。
        """
        normalized = _normalize_whitespace(content)
        chunk_id = _sha256(
            f"{document.document_id}:{document.checksum}:{position}:{normalized}"
        )
        return Chunk(
            chunk_id=chunk_id,
            document_id=document.document_id,
            user_id=document.user_id,
            namespace=document.namespace,
            content=content,
            position=position,
            start_char=start_char,
            end_char=end_char,
            heading_path=heading_path,
            metadata=metadata or {},
        )

    @staticmethod
    def rebuild_id(document: Document, content: str, position: int) -> str:
        """外部验证用：给定参数，算出 chunk_id 应该是多少。"""
        return _sha256(
            f"{document.document_id}:{document.checksum}:{position}:{_normalize_whitespace(content)}"
        )
# **边界**：splitter 的输入是 `Document` 对象（不是 dict），输出是 `list[Chunk]`。
# splitter 内部不需要知道 `chunk_id` 的 hash 逻辑——调 `Chunk.build()` 即可
# 但最关键的是：**splitter 不能只传 `document_id` 字符串**——必须传完整的 `Document`，
# 因为 `chunk_id` 依赖 `document.checksum`。如果只传 `document_id`，splitter 就不知道文档内容变了没有

@dataclass(frozen=True)
class RetrievalResult:
    chunk: Chunk
    score: float
    retriever: str                    # "bm25" / "dense" / "hybrid"
    score_components: dict[str, float] = field(default_factory=dict)
    # 例: {"bm25": 0.72, "dense": 0.65, "rrf": 0.018}
    
    @staticmethod
    def from_chunk(
        chunk: Chunk,
        score: float,
        retriever: str,
        score_components: dict[str, float] | None = None,
    ) -> "RetrievalResult":
        return RetrievalResult(
            chunk=chunk,
            score=score,
            retriever=retriever,
            score_components=score_components or {},
        )
# **边界**：retriever 的输入是 `str`（查询文本），输出是 `list[RetrievalResult]`
# `score_components` 在 hybrid 模式下把 BM25 和 dense 各自的分数都保留——将来调参时能看到是哪一路贡献的

@dataclass(frozen=True)
class RAGAnswer:
    answer: str
    contexts: list[RetrievalResult]
    citations: list[str]              # 引用的 chunk_id 列表
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def build(
        *,
        answer: str,
        contexts: list[RetrievalResult],
    ) -> "RAGAnswer":
        citations = [r.chunk.chunk_id for r in contexts]
        return RAGAnswer(
            answer=answer,
            contexts=contexts,
            citations=citations,
        )
# **边界**：pipeline 的输入是 `str`（用户问题），
# 输出是 `RAGAnswer`。`citations` 自动从 `contexts` 里提取，调用方不需要手动维护。