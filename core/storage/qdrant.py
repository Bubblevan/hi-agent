from __future__ import annotations

import os
import uuid
from typing import Any, Optional

from .vector_store import VectorHit

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointIdsList,
        PointStruct,
        VectorParams,
    )

    QDRANT_AVAILABLE = True
except ImportError:
    QdrantClient = None
    Distance = FieldCondition = Filter = MatchValue = PointIdsList = PointStruct = VectorParams = None
    QDRANT_AVAILABLE = False


class QdrantVectorStore:
    """Generic Qdrant-backed vector store for memory, RAG, and other retrieval."""

    def __init__(
        self,
        collection_name: str,
        vector_size: int,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        host: str = "localhost",
        port: int = 6333,
        distance: Any = None,
        create_if_missing: bool = True,
        fail_fast: bool = False,
    ) -> None:
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.client = None
        self._initialized = False
        self.fail_fast = fail_fast
        self.distance = distance or (Distance.COSINE if QDRANT_AVAILABLE else None)

        if not QDRANT_AVAILABLE:
            if fail_fast:
                raise ImportError("qdrant-client is not installed. Install it with: pip install qdrant-client")
            return

        try:
            url = url or os.getenv("QDRANT_URL")
            api_key = api_key or os.getenv("QDRANT_API_KEY")
            self.client = QdrantClient(url=url, api_key=api_key) if url else QdrantClient(host=host, port=port)
            if create_if_missing:
                self._ensure_collection()
            self._initialized = True
        except Exception:
            self.client = None
            self._initialized = False
            if fail_fast:
                raise

    def is_available(self) -> bool:
        return self._initialized and self.client is not None

    def upsert(
        self,
        ids: list[str],
        vectors: list[list[float]],
        metadata: list[dict[str, Any]],
    ) -> None:
        if len(ids) != len(vectors) or len(ids) != len(metadata):
            raise ValueError("ids, vectors, and metadata must have the same length")
        self._require_available()
        for index, vector in enumerate(vectors):
            self._validate_vector(vector, index)

        points = [
            PointStruct(
                id=self._point_id(item_id),
                vector=vector,
                payload={"id": item_id, **payload},
            )
            for item_id, vector, payload in zip(ids, vectors, metadata)
        ]
        self.client.upsert(collection_name=self.collection_name, points=points)

    def search(
        self,
        query_vector: list[float],
        limit: int,
        filters: dict[str, Any] | None = None,
        score_threshold: float | None = None,
    ) -> list[VectorHit]:
        self._require_available()
        self._validate_vector(query_vector, 0)
        query_filter = self._build_filter(filters)

        try:
            hits = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=query_filter,
                score_threshold=score_threshold,
            )
        except AttributeError:
            result = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=limit,
                query_filter=query_filter,
                score_threshold=score_threshold,
            )
            hits = getattr(result, "points", result)

        return [
            VectorHit(
                id=str((hit.payload or {}).get("id", hit.id)),
                score=float(hit.score),
                metadata=dict(hit.payload or {}),
            )
            for hit in hits
        ]

    def delete(self, ids: list[str]) -> int:
        self._require_available()
        deleted = 0
        for item_id in ids:
            points, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=self._build_filter({"id": item_id}),
                limit=100,
            )
            point_ids = [point.id for point in points]
            if point_ids:
                self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=PointIdsList(points=point_ids),
                )
                deleted += len(point_ids)
        return deleted

    def clear(self, filters: dict[str, Any] | None = None) -> int:
        self._require_available()
        if filters:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=self._build_filter(filters),
            )
            return 1
        self.client.delete_collection(self.collection_name)
        self._ensure_collection()
        return 1

    def _ensure_collection(self) -> None:
        collections = self.client.get_collections().collections
        if any(collection.name == self.collection_name for collection in collections):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=self.vector_size, distance=self.distance),
        )

    def _build_filter(self, filters: dict[str, Any] | None) -> Any:
        if not filters:
            return None
        return Filter(
            must=[
                FieldCondition(key=key, match=MatchValue(value=value))
                for key, value in filters.items()
            ]
        )

    def _require_available(self) -> None:
        if not self.is_available():
            raise RuntimeError("Qdrant vector store is not available")

    def _validate_vector(self, vector: list[float], index: int) -> None:
        if len(vector) != self.vector_size:
            raise ValueError(
                f"Vector dimension mismatch at index {index}: expected {self.vector_size}, got {len(vector)}"
            )

    @staticmethod
    def _point_id(item_id: str) -> str:
        try:
            return str(uuid.UUID(str(item_id)))
        except ValueError:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, str(item_id)))
