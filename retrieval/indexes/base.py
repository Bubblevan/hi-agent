from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from retrieval.models import Chunk, Document


IndexStatus = Literal["inserted", "unchanged", "updated"]


@dataclass(frozen=True)
class IndexResult:
    """结果只描述本次索引动作，不暴露数据库实现细节。"""

    status: IndexStatus
    document_id: str
    deleted_chunk_count: int = 0
    inserted_chunk_count: int = 0


@dataclass(frozen=True)
class ManifestRecord:
    """一份文档在某个租户命名空间中的索引快照。"""

    document_id: str
    user_id: str
    namespace: str
    source: str
    checksum: str
    chunk_count: int
    indexed_at: str
    embedding_model: str | None = None


class ManifestIndex(Protocol):
    def index_document(
        self,
        document: Document,
        chunks: list[Chunk],
        *,
        embedding_model: str | None = None,
    ) -> IndexResult: ...

    def get_manifest(
        self, user_id: str, namespace: str, source: str
    ) -> ManifestRecord | None: ...
