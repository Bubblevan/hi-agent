from __future__ import annotations

import os
from typing import Optional

from .base import BaseEmbedder
from .dashscope import DashScopeEmbedder
from .local import LocalTransformerEmbedder
from .tfidf import TFIDFEmbedder


def get_text_embedder(
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    dimension: Optional[int] = None,
) -> BaseEmbedder:
    """Create a configured embedder.

    Explicit providers fail loudly. The default auto mode tries cloud, local, then
    TF-IDF so existing memory flows still have a fallback.
    """

    provider = provider or os.getenv("EMBED_PROVIDER") or os.getenv("EMBED_MODEL_TYPE") or "auto"
    env_model = os.getenv("EMBED_MODEL_NAME")
    env_api_key = os.getenv("EMBED_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    env_base_url = os.getenv("DASHSCOPE_BASE_URL")

    if provider in {"dashscope", "auto"}:
        try:
            return DashScopeEmbedder(
                api_key=api_key or env_api_key,
                model=model_name or env_model or "qwen3.7-text-embedding",
                dimension=dimension or DashScopeEmbedder.DEFAULT_DIMENSION,
                base_url=env_base_url,
            )
        except Exception:
            if provider == "dashscope":
                raise

    if provider in {"local", "auto"}:
        try:
            return LocalTransformerEmbedder(
                model_name=model_name or env_model or "sentence-transformers/all-MiniLM-L6-v2",
                dimension=dimension or 384,
            )
        except Exception:
            if provider == "local":
                raise

    return TFIDFEmbedder(dimension=dimension or 384)


_global_embedder: BaseEmbedder | None = None


def get_global_embedder() -> BaseEmbedder:
    global _global_embedder
    if _global_embedder is None:
        _global_embedder = get_text_embedder()
    return _global_embedder
