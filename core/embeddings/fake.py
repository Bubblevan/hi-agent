from __future__ import annotations

import math

from .base import EmbedderBase


class FakeEmbedder(EmbedderBase):
    """Deterministic fake embedder for pytest and eval harnesses."""

    def __init__(self, dimension: int = 16) -> None:
        super().__init__(dimension=dimension)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_vector(text) for text in texts]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_vector(text) for text in texts]

    def _hash_vector(self, text: str) -> list[float]:
        buckets = [0.0] * self.dimension
        for index, char in enumerate((text or "").lower()):
            buckets[(ord(char) + index) % self.dimension] += 1.0
        norm = math.sqrt(sum(value * value for value in buckets)) or 1.0
        return [value / norm for value in buckets]
