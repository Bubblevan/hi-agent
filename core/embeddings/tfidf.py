from __future__ import annotations

import hashlib

from .base import EmbedderBase, validate_embeddings

try:
    from sklearn.feature_extraction.text import TfidfVectorizer

    SKLEARN_AVAILABLE = True
except ImportError:
    TfidfVectorizer = None
    SKLEARN_AVAILABLE = False


class TFIDFEmbedder(EmbedderBase):
    """Lightweight fallback embedder used when real providers are unavailable."""

    def __init__(self, dimension: int = 384, max_features: int = 384) -> None:
        super().__init__(dimension=dimension)
        self.max_features = max_features
        self._is_fitted = False

        if not SKLEARN_AVAILABLE:
            raise ImportError("scikit-learn is not installed. Install it with: pip install scikit-learn")

        self.vectorizer = TfidfVectorizer(
            max_features=max_features,
            stop_words=None,
            analyzer="char",
            ngram_range=(1, 2),
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            if not self._is_fitted:
                self.vectorizer.fit(texts)
                self._is_fitted = True
            dense_vectors = self.vectorizer.transform(texts).toarray()
            vectors = [self._fit_dimension(list(vector)) for vector in dense_vectors]
        except Exception:
            vectors = [self._hash_vector(text) for text in texts]

        validate_embeddings(vectors, self.dimension)
        return vectors

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    def _fit_dimension(self, vector: list[float]) -> list[float]:
        if len(vector) < self.dimension:
            return vector + [0.0] * (self.dimension - len(vector))
        return vector[: self.dimension]

    def _hash_vector(self, text: str) -> list[float]:
        digest = hashlib.md5(text.encode("utf-8")).digest()
        return [(digest[index % len(digest)] / 255.0) * 2 - 1 for index in range(self.dimension)]
