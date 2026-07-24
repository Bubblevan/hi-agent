from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class VectorHit:
    id: str
    score: float
    metadata: dict[str, Any]


class VectorStore(Protocol):
    def upsert(
        self,
        ids: list[str],
        vectors: list[list[float]],
        metadata: list[dict[str, Any]],
    ) -> None:
        ...

    def search(
        self,
        query_vector: list[float],
        limit: int,
        filters: dict[str, Any] | None = None,
        score_threshold: float | None = None,
    ) -> list[VectorHit]:
        ...

    def delete(self, ids: list[str]) -> int:
        ...
