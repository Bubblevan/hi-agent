import json
from pathlib import Path

import pytest

from core.embeddings.fake import FakeEmbedder


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
