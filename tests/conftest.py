import pytest


class FakeEmbedder:
    """Small deterministic embedder for memory tests."""

    dimension = 3

    def encode(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return [self._vector_for(text) for text in texts]

    def _vector_for(self, text):
        text = text.lower()
        if "python" in text:
            return [1.0, 0.0, 0.0]
        if "coffee" in text or "tea" in text:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture
def patch_fake_embedder(monkeypatch, fake_embedder):
    monkeypatch.setattr("memory.manager.get_text_embedder", lambda: fake_embedder)
    return fake_embedder
