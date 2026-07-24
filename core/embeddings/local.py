from __future__ import annotations

from .base import EmbedderBase, validate_embeddings

try:
    from sentence_transformers import SentenceTransformer

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SentenceTransformer = None
    SENTENCE_TRANSFORMERS_AVAILABLE = False


class LocalTransformerEmbedder(EmbedderBase):
    """Local sentence-transformers embedder for offline development and tests."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        dimension: int = 384,
    ) -> None:
        super().__init__(dimension=dimension)
        self.model_name = model_name

        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError(
                "sentence-transformers is not installed. Install it with: pip install sentence-transformers"
            )

        try:
            self.model = SentenceTransformer(model_name, local_files_only=True)
            test_vector = self.model.encode("test", normalize_embeddings=True, show_progress_bar=False)
            self.dimension = len(test_vector)
        except Exception as exc:
            raise RuntimeError(f"Failed to load local embedding model {model_name}: {exc}") from exc

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            embeddings = self.model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise RuntimeError(f"Local embedding failed: {exc}") from exc

        if hasattr(embeddings, "tolist"):
            vectors = embeddings.tolist()
        else:
            vectors = [list(vector) for vector in embeddings]
        if vectors and not isinstance(vectors[0], list):
            vectors = [vectors]

        validate_embeddings(vectors, self.dimension)
        return vectors

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)
