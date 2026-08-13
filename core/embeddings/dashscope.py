from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any, Optional

from .base import EmbedderBase, validate_embeddings

try:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())
except ImportError:
    pass

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OpenAI = None
    OPENAI_AVAILABLE = False


class DashScopeEmbedder(EmbedderBase):
    """DashScope MaaS embedding client using the OpenAI-compatible API."""

    DEFAULT_MODEL = "qwen3.7-text-embedding"
    DEFAULT_DIMENSION = 1024
    DEFAULT_BATCH_SIZE = 64
    MAX_PROVIDER_BATCH_SIZE = 20
    DEFAULT_MAX_RETRIES = 2
    DEFAULT_RETRY_BACKOFF_SECONDS = 0.5

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        dimension: int = DEFAULT_DIMENSION,
        base_url: Optional[str] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(dimension=dimension)
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")

        self.batch_size = batch_size
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.sleep_fn = sleep_fn
        self.model = (
            model
            or os.getenv("DASHSCOPE_EMBEDDING_MODEL")
            or os.getenv("EMBED_MODEL_NAME")
            or self.DEFAULT_MODEL
        )
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY") or os.getenv("EMBED_API_KEY")
        self.base_url = base_url or os.getenv("DASHSCOPE_BASE_URL")

        if not self.api_key:
            raise ValueError("DashScope API key is missing. Set DASHSCOPE_API_KEY or EMBED_API_KEY.")
        if not self.base_url:
            raise ValueError(
                "DashScope base URL is missing. Set DASHSCOPE_BASE_URL, for example "
                "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
            )
        if not OPENAI_AVAILABLE:
            raise ImportError("openai is not installed. Install it with: pip install openai")

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._validate_texts(texts)

        vectors: list[list[float]] = []
        effective_batch_size = min(self.batch_size, self.MAX_PROVIDER_BATCH_SIZE)
        for start in range(0, len(texts), effective_batch_size):
            batch = texts[start : start + effective_batch_size]
            vectors.extend(self._embed_batch(batch, batch_start=start))

        validate_embeddings(vectors, self.dimension)
        return vectors

    def _embed_batch(self, texts: list[str], *, batch_start: int) -> list[list[float]]:
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=texts,
                )
                vectors = self._extract_vectors(response, expected_count=len(texts))
                try:
                    validate_embeddings(vectors, self.dimension)
                except ValueError as exc:
                    raise EmbeddingResponseError(str(exc)) from exc
                return vectors
            except EmbeddingResponseError:
                raise
            except Exception as exc:
                if not self._is_retryable(exc) or attempt >= self.max_retries:
                    raise EmbeddingRequestError(
                        batch_start=batch_start,
                        batch_size=len(texts),
                        attempts=attempt + 1,
                        cause=exc,
                    ) from exc
                self.sleep_fn(self.retry_backoff_seconds * (2**attempt))

        raise AssertionError("embedding retry loop did not return or raise")

    @staticmethod
    def _validate_texts(texts: list[str]) -> None:
        if not isinstance(texts, list):
            raise TypeError("texts must be a list of strings")
        for index, text in enumerate(texts):
            if not isinstance(text, str):
                raise TypeError(f"embedding input at index {index} must be a string")
            if not text.strip():
                raise ValueError(f"embedding input at index {index} must not be blank")

    @staticmethod
    def _extract_vectors(response: Any, *, expected_count: int) -> list[list[float]]:
        data = getattr(response, "data", None)
        if not isinstance(data, list) or len(data) != expected_count:
            raise EmbeddingResponseError(
                f"DashScope returned {len(data) if isinstance(data, list) else 'no'} "
                f"vectors for {expected_count} inputs"
            )

        indexed_items = [getattr(item, "index", None) for item in data]
        if any(index is not None for index in indexed_items):
            if not all(index is not None for index in indexed_items):
                raise EmbeddingResponseError(
                    "DashScope returned only some embedding indexes"
                )
            try:
                indexes = [int(index) for index in indexed_items]
            except (TypeError, ValueError) as exc:
                raise EmbeddingResponseError(
                    "DashScope returned invalid embedding indexes"
                ) from exc
            if sorted(indexes) != list(range(expected_count)):
                raise EmbeddingResponseError(
                    "DashScope returned invalid or duplicate embedding indexes"
                )
            data = [item for _, item in sorted(zip(indexes, data), key=lambda pair: pair[0])]

        vectors: list[list[float]] = []
        try:
            for item in data:
                embedding = getattr(item, "embedding")
                vectors.append([float(value) for value in embedding])
        except (AttributeError, TypeError, ValueError) as exc:
            raise EmbeddingResponseError(
                "DashScope returned a malformed embedding vector"
            ) from exc
        return vectors

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return True

        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and status_code in {408, 409, 429}:
            return True
        if isinstance(status_code, int) and 500 <= status_code <= 599:
            return True

        name = type(exc).__name__.lower()
        return any(
            marker in name
            for marker in (
                "ratelimit",
                "apiconnection",
                "apitimeout",
                "serviceunavailable",
                "internalserver",
            )
        )


class EmbeddingResponseError(ValueError):
    """The provider returned a response that violates the embedding contract."""


class EmbeddingRequestError(RuntimeError):
    """A provider request failed after its retry policy was exhausted."""

    def __init__(
        self,
        *,
        batch_start: int,
        batch_size: int,
        attempts: int,
        cause: Exception,
    ) -> None:
        self.batch_start = batch_start
        self.batch_size = batch_size
        self.attempts = attempts
        self.cause = cause
        super().__init__(
            "DashScope embedding request failed for "
            f"batch starting at {batch_start} (size={batch_size}) "
            f"after {attempts} attempt(s): {cause}"
        )
