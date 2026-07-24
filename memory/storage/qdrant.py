"""Memory-compatible wrapper over the shared Qdrant vector store."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.storage.qdrant import QDRANT_AVAILABLE
from core.storage.qdrant import QdrantVectorStore as CoreQdrantVectorStore


class QdrantVectorStore(CoreQdrantVectorStore):
    def __init__(
        self,
        collection_name: str = "hello_agents_vectors",
        vector_size: int = 384,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        host: str = "localhost",
        port: int = 6333,
    ) -> None:
        super().__init__(
            collection_name=collection_name,
            vector_size=vector_size,
            url=url,
            api_key=api_key,
            host=host,
            port=port,
            fail_fast=False,
        )

    def add_vector(
        self,
        vector: List[float],
        memory_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.is_available():
            return False
        try:
            self.upsert(
                ids=[memory_id],
                vectors=[vector],
                metadata=[{"memory_id": memory_id, **(metadata or {})}],
            )
            return True
        except Exception as exc:
            print(f"Qdrant add vector failed: {exc}")
            return False

    def search_vectors(
        self,
        query_vector: List[float],
        limit: int = 10,
        score_threshold: Optional[float] = None,
        filter_payload: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []
        try:
            hits = self.search(
                query_vector=query_vector,
                limit=limit,
                filters=filter_payload,
                score_threshold=score_threshold,
            )
            return [
                {
                    "memory_id": hit.metadata.get("memory_id", hit.id),
                    "score": hit.score,
                    "payload": hit.metadata,
                }
                for hit in hits
            ]
        except Exception as exc:
            print(f"Qdrant search failed: {exc}")
            return []

    def delete_by_memory_id(self, memory_id: str, user_id: Optional[str] = None) -> bool:
        if not self.is_available():
            return False
        try:
            filters: Dict[str, Any] = {"memory_id": memory_id}
            if user_id:
                filters["user_id"] = user_id
            points, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=self._build_filter(filters),
                limit=100,
            )
            point_ids = [point.id for point in points]
            if point_ids:
                from qdrant_client.models import PointIdsList

                self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=PointIdsList(points=point_ids),
                )
            return True
        except Exception as exc:
            print(f"Qdrant delete failed: {exc}")
            return False

    def clear(self, filter_payload: Optional[Dict[str, Any]] = None) -> int:
        if not self.is_available():
            return 0
        try:
            return super().clear(filters=filter_payload)
        except Exception as exc:
            print(f"Qdrant clear failed: {exc}")
            return 0
