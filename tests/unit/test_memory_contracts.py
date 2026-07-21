import pytest

from memory.base import BaseMemory, MemoryConfig, MemoryItem
from memory.manager import MemoryManager


@pytest.mark.xfail(reason="Tenant isolation is only metadata today; CRUD is not enforced.")
def test_user_a_cannot_retrieve_user_b_working_memory(patch_fake_embedder):
    manager_a = MemoryManager(user_id="user_a", enable_working=True)
    manager_b = MemoryManager(user_id="user_b", enable_working=True)

    manager_b.memory_types["working"] = manager_a.memory_types["working"]
    manager_a.add_memory(
        "Alice likes Python",
        metadata={"user_id": "user_a"},
    )
    manager_b.add_memory(
        "Bob likes coffee",
        metadata={"user_id": "user_b"},
    )

    results = manager_a.retrieve_memories("coffee", limit=5)
    assert all(item.metadata["user_id"] == "user_a" for item in results)


@pytest.mark.xfail(reason="Manager currently re-sorts merged results by importance only.")
def test_cross_memory_retrieval_prefers_relevance_over_importance(patch_fake_embedder):
    manager = MemoryManager(user_id="user_a", enable_working=False)
    relevant = MemoryItem(
        id="relevant",
        content="Python related",
        memory_type="fake",
        importance=0.2,
    )
    important = MemoryItem(
        id="important",
        content="Unrelated but important",
        memory_type="fake",
        importance=0.9,
    )

    class StubMemory:
        def retrieve(self, **kwargs):
            return [relevant, important]

    manager.memory_types["fake"] = StubMemory()

    assert manager.retrieve_memories("Python", limit=2)[0].id == "relevant"


@pytest.mark.xfail(reason="BaseMemory does not define a structured forget contract yet.")
def test_base_memory_requires_forget_contract():
    assert "forget" in BaseMemory.__abstractmethods__


@pytest.mark.xfail(reason="Consolidation currently copies source IDs and is not idempotent.")
def test_repeated_consolidation_is_idempotent(patch_fake_embedder):
    manager = MemoryManager(
        user_id="user_a",
        enable_working=True,
        enable_episodic=True,
    )
    manager.add_memory("Important Python memory", importance=0.9)

    first = manager.consolidate_memories()
    second = manager.consolidate_memories()

    assert first == 1
    assert second == 0


@pytest.mark.xfail(reason="Embedding providers can still return zero vectors on failure.")
def test_embedding_failure_does_not_store_zero_vector(fake_embedder):
    class ZeroEmbedder:
        dimension = 3

        def encode(self, texts):
            return [[0.0, 0.0, 0.0]]

    from memory.types.working import WorkingMemory

    memory = WorkingMemory(MemoryConfig(), ZeroEmbedder())
    memory.add(MemoryItem(content="Python memory", memory_type="working"))

    assert memory._items[0].embedding is None
