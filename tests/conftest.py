import json
import math
from pathlib import Path

import pytest


class FakeEmbedder:
    """Small deterministic embedder for memory tests."""

    dimension = 16

    def encode(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return [self._vector_for(text) for text in texts]

    def _vector_for(self, text):
        buckets = [0.0] * self.dimension
        for index, ch in enumerate((text or "").lower()):
            bucket = (ord(ch) + index) % self.dimension
            buckets[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in buckets)) or 1.0
        return [value / norm for value in buckets]


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture(autouse=True)
def patch_fake_embedder(monkeypatch, fake_embedder):
    monkeypatch.setattr("memory.manager.get_text_embedder", lambda: fake_embedder)
    return fake_embedder


@pytest.fixture
def memory_config(tmp_path):
    from memory.base import MemoryConfig

    return MemoryConfig(
        database_path=str(tmp_path / "memory_test.db"),
        working_memory_capacity=5,
        working_memory_ttl=60,
        qdrant_url=None,
        qdrant_api_key=None,
    )


@pytest.fixture
def memory_cases():
    path = Path(__file__).parent / "fixtures" / "memory_cases.jsonl"
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]
