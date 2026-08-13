from __future__ import annotations

import json
import math
from pathlib import Path
from types import MappingProxyType
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from qdrant_client.http import models

from retrieval.models import Chunk, Document, RetrievalResult


def _validate_scope(user_id: str, namespace: str) -> None:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id must be a non-blank string")
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError("namespace must be a non-blank string")


class QdrantVectorStore:
    """Qdrant point storage for chunks; retrieval is implemented in task 10."""

    def __init__(
        self,
        *,
        client: QdrantClient | None = None,
        collection_name: str = "hi_agent_rag",
        dimension: int,
        url: str | None = None,
        api_key: str | None = None,
        path: str | Path | None = None,
    ) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        if not isinstance(collection_name, str) or not collection_name.strip():
            raise ValueError("collection_name must be a non-blank string")
        if client is not None and any(value is not None for value in (url, path)):
            raise ValueError("pass either client or url/path, not both")
        if url is not None and path is not None:
            raise ValueError("pass either url or path, not both")

        if client is None:
            if path is not None:
                client = QdrantClient(path=str(path))
            else:
                client = QdrantClient(url=url, api_key=api_key)

        self.client = client
        self.collection_name = collection_name
        self.dimension = dimension
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.dimension,
                    distance=models.Distance.COSINE,
                ),
            )
            self._ensure_payload_indexes()
            return

        collection = self.client.get_collection(self.collection_name)
        vectors = collection.config.params.vectors
        existing_dimension = getattr(vectors, "size", None)
        if existing_dimension != self.dimension:
            raise ValueError(
                f"Qdrant collection dimension mismatch: expected {self.dimension}, "
                f"got {existing_dimension}"
            )
        existing_distance = getattr(vectors, "distance", None)
        if existing_distance != models.Distance.COSINE:
            raise ValueError(
                "Qdrant collection distance mismatch: expected cosine, "
                f"got {existing_distance}"
            )
        self._ensure_payload_indexes()

    def _ensure_payload_indexes(self) -> None:
        """Create keyword indexes required by tenant/source filters."""
        for field_name in ("user_id", "namespace", "source", "document_id", "chunk_id"):
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.KEYWORD,
                wait=True,
            )

    def upsert_chunks(
        self,
        document: Document,
        chunks: list[Chunk],
        vectors: list[list[float]],
    ) -> int:
        self._validate_chunks(document, chunks)
        self._validate_vectors(vectors, expected_count=len(chunks))
        if not chunks:
            return 0

        points = [
            models.PointStruct(
                id=self._point_id(document, chunk),
                vector=vector,
                payload=self._payload(document, chunk),
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
            wait=True,
        )
        return len(points)

    def count_chunks(self, user_id: str, namespace: str, source: str) -> int:
        self._validate_source_scope(user_id, namespace, source)
        result = self.client.count(
            collection_name=self.collection_name,
            count_filter=self._scope_filter(user_id, namespace, source),
            exact=True,
        )
        return int(result.count)

    def delete_document(self, user_id: str, namespace: str, source: str) -> int:
        self._validate_source_scope(user_id, namespace, source)
        count = self.count_chunks(user_id, namespace, source)
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=self._scope_filter(user_id, namespace, source)
            ),
            wait=True,
        )
        return count

    def get_chunk_payload(
        self,
        user_id: str,
        namespace: str,
        source: str,
        chunk_id: str,
    ) -> dict | None:
        self._validate_source_scope(user_id, namespace, source)
        points, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(
                must=[
                    *self._scope_conditions(user_id, namespace, source),
                    models.FieldCondition(
                        key="chunk_id",
                        match=models.MatchValue(value=chunk_id),
                    ),
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        return dict(points[0].payload or {}) if points else None

    def search(
        self,
        query_vector: list[float],
        *,
        user_id: str,
        namespace: str,
        limit: int = 5,
        source: str | None = None,
        score_threshold: float | None = None,
        metadata_filters: dict[str, object] | None = None,
    ) -> list[RetrievalResult]:
        """Search only within a tenant and reconstruct RAG retrieval results."""
        _validate_scope(user_id, namespace)
        if limit <= 0:
            raise ValueError("limit must be positive")
        if source is not None and (not isinstance(source, str) or not source.strip()):
            raise ValueError("source must be a non-blank string")
        self._validate_vectors([query_vector], expected_count=1)

        conditions = self._scope_conditions(user_id, namespace, source)
        for key, value in (metadata_filters or {}).items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("metadata filter keys must be non-blank strings")
            conditions.append(
                models.FieldCondition(
                    key=f"metadata.{key}",
                    match=models.MatchValue(value=value),
                )
            )

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=models.Filter(must=conditions),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
            with_vectors=False,
        )
        points = getattr(response, "points", response)
        return [
            RetrievalResult.from_chunk(
                chunk=self._chunk_from_payload(point.payload or {}),
                score=float(point.score),
                retriever="dense",
                score_components={"dense": float(point.score)},
            )
            for point in points
        ]

    @staticmethod
    def _point_id(document: Document, chunk: Chunk) -> str:
        return str(
            uuid5(
                NAMESPACE_URL,
                f"hi-agent:{document.user_id}:{document.namespace}:{chunk.chunk_id}",
            )
        )

    @staticmethod
    def _payload(document: Document, chunk: Chunk) -> dict:
        metadata = dict(chunk.metadata)
        # Fail before the Qdrant call rather than discovering non-serializable
        # metadata halfway through a batch.
        json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        return {
            "chunk_id": chunk.chunk_id,
            "document_id": document.document_id,
            "user_id": document.user_id,
            "namespace": document.namespace,
            "source": document.source,
            "content": chunk.content,
            "position": chunk.position,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "heading_path": chunk.heading_path,
            "metadata": metadata,
        }

    @staticmethod
    def _chunk_from_payload(payload: dict) -> Chunk:
        required = (
            "chunk_id",
            "document_id",
            "user_id",
            "namespace",
            "content",
            "position",
            "start_char",
            "end_char",
        )
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError(f"Qdrant payload is missing chunk fields: {missing}")
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("Qdrant chunk metadata must be an object")
        return Chunk(
            chunk_id=str(payload["chunk_id"]),
            document_id=str(payload["document_id"]),
            user_id=str(payload["user_id"]),
            namespace=str(payload["namespace"]),
            source=str(payload.get("source", "")),
            content=str(payload["content"]),
            position=int(payload["position"]),
            start_char=int(payload["start_char"]),
            end_char=int(payload["end_char"]),
            heading_path=payload.get("heading_path"),
            metadata=MappingProxyType(dict(metadata)),
        )

    @staticmethod
    def _validate_chunks(document: Document, chunks: list[Chunk]) -> None:
        if not isinstance(chunks, list):
            raise TypeError("chunks must be a list")
        expected_positions = list(range(len(chunks)))
        if [chunk.position for chunk in chunks] != expected_positions:
            raise ValueError("chunk positions must be contiguous and start at zero")
        for chunk in chunks:
            if (
                chunk.document_id != document.document_id
                or chunk.user_id != document.user_id
                or chunk.namespace != document.namespace
            ):
                raise ValueError("chunk does not belong to the indexed document")
            if document.text[chunk.start_char : chunk.end_char] != chunk.content:
                raise ValueError("chunk source span does not match document")

    def _validate_vectors(self, vectors: list[list[float]], *, expected_count: int) -> None:
        if not isinstance(vectors, list):
            raise TypeError("vectors must be a list")
        if len(vectors) != expected_count:
            raise ValueError("chunks and vectors must have the same number of items")
        for index, vector in enumerate(vectors):
            if len(vector) != self.dimension:
                raise ValueError(
                    f"vector dimension mismatch at index {index}: "
                    f"expected {self.dimension}, got {len(vector)}"
                )
            if not all(math.isfinite(float(value)) for value in vector):
                raise ValueError(f"vector at index {index} contains a non-finite value")

    @staticmethod
    def _validate_source_scope(user_id: str, namespace: str, source: str) -> None:
        _validate_scope(user_id, namespace)
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a non-blank string")

    @staticmethod
    def _scope_conditions(
        user_id: str, namespace: str, source: str | None = None
    ) -> list[models.FieldCondition]:
        conditions = [
            models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
            models.FieldCondition(
                key="namespace", match=models.MatchValue(value=namespace)
            ),
        ]
        if source is not None:
            conditions.append(
                models.FieldCondition(key="source", match=models.MatchValue(value=source))
            )
        return conditions

    @classmethod
    def _scope_filter(cls, user_id: str, namespace: str, source: str) -> models.Filter:
        return models.Filter(must=cls._scope_conditions(user_id, namespace, source))
