from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Protocol


class BaseEmbedder(Protocol):
    """Common embedding interface shared by memory, RAG, and evals."""

    dimension: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        ...


class EmbedderBase(ABC):
    """Optional base class with caching and legacy encode() compatibility."""

    dimension: int

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension
        self._document_cache: dict[str, list[float]] = {}
        self._query_cache: dict[str, list[float]] = {}

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    def encode(self, texts: str | list[str]) -> list[list[float]]:
        """Legacy memory API: treat encode() as document embedding."""

        return self.embed_documents(_normalize_texts(texts))

    def encode_with_cache(self, texts: str | list[str]) -> list[list[float]]:
        return self.embed_documents_with_cache(_normalize_texts(texts))

    def embed_documents_with_cache(self, texts: list[str]) -> list[list[float]]:
        return self._embed_with_cache(texts, self._document_cache, self.embed_documents)

    def embed_queries_with_cache(self, texts: list[str]) -> list[list[float]]:
        return self._embed_with_cache(texts, self._query_cache, self.embed_queries)

    def _embed_with_cache(
        self,
        texts: list[str],
        cache: dict[str, list[float]],
        embed_fn,
    ) -> list[list[float]]:
        results: list[tuple[int, list[float]]] = []
        misses: list[str] = []
        miss_indices: list[int] = []

        for index, text in enumerate(texts):
            key = self._cache_key(text)
            if key in cache:
                results.append((index, cache[key]))
            else:
                misses.append(text)
                miss_indices.append(index)

        if misses:
            vectors = embed_fn(misses)
            validate_embeddings(vectors, self.dimension)
            for index, vector in zip(miss_indices, vectors):
                cache[self._cache_key(texts[index])] = vector
                results.append((index, vector))

        results.sort(key=lambda item: item[0])
        return [vector for _, vector in results]

    @staticmethod
    def _cache_key(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()


def _normalize_texts(texts: str | list[str]) -> list[str]:
    return [texts] if isinstance(texts, str) else texts


def validate_embeddings(vectors: list[list[float]], dimension: int) -> None:
    for index, vector in enumerate(vectors):
        if len(vector) != dimension:
            raise ValueError(
                f"Embedding dimension mismatch at index {index}: "
                f"expected {dimension}, got {len(vector)}"
            )
