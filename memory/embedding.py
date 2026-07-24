"""Compatibility exports for the shared embedding layer.

New code should import from core.embeddings. Memory still imports this module in
several places, so keep these names stable during the migration.
"""

from core.embeddings import (
    BaseEmbedder,
    DashScopeEmbedder,
    FakeEmbedder,
    LocalTransformerEmbedder,
    TFIDFEmbedder,
    get_global_embedder,
    get_text_embedder,
)

__all__ = [
    "BaseEmbedder",
    "DashScopeEmbedder",
    "FakeEmbedder",
    "LocalTransformerEmbedder",
    "TFIDFEmbedder",
    "get_global_embedder",
    "get_text_embedder",
]
