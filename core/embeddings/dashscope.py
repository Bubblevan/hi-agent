from __future__ import annotations

import os
from typing import Optional

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

    DEFAULT_DIMENSION = 1024

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "qwen3.7-text-embedding",
        dimension: int = DEFAULT_DIMENSION,
        base_url: Optional[str] = None,
    ) -> None:
        super().__init__(dimension=dimension)
        self.model = model
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

        try:
            response = self.client.embeddings.create(model=self.model, input=texts)
            vectors = [item.embedding for item in response.data]
        except Exception as exc:
            raise RuntimeError(f"DashScope embedding request failed: {exc}") from exc

        validate_embeddings(vectors, self.dimension)
        return vectors
