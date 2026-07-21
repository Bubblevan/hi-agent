from datetime import datetime, timedelta

from memory.base import MemoryConfig, MemoryItem
from memory.manager import MemoryManager


def test_working_memory_add_search_stats_and_ttl(patch_fake_embedder):
    manager = MemoryManager(
        config=MemoryConfig(working_memory_ttl=1),
        user_id="user_a",
        enable_working=True,
    )
    memory_id = manager.add_memory("Python is my main language", importance=0.7)

    results = manager.retrieve_memories("Python", limit=3)
    stats = manager.get_stats()

    assert [item.id for item in results] == [memory_id]
    assert stats["working"]["count"] == 1

    manager.memory_types["working"]._items[0].timestamp = (
        datetime.now() - timedelta(minutes=2)
    )
    assert manager.retrieve_memories("Python", limit=3) == []
    assert manager.get_stats()["working"]["count"] == 0


def test_working_memory_capacity_evicts_lowest_importance(patch_fake_embedder):
    manager = MemoryManager(
        config=MemoryConfig(working_memory_capacity=2),
        user_id="user_a",
        enable_working=True,
    )

    low_id = manager.add_memory("low value note", importance=0.1)
    kept_id = manager.add_memory("Python project note", importance=0.8)
    new_id = manager.add_memory("coffee preference note", importance=0.5)

    remaining_ids = {item.id for item in manager.memory_types["working"]._items}
    assert low_id not in remaining_ids
    assert remaining_ids == {kept_id, new_id}


def test_manager_global_sort_currently_uses_importance_after_module_retrieval(
    patch_fake_embedder,
):
    manager = MemoryManager(user_id="user_a", enable_working=False)
    relevant = MemoryItem(
        id="relevant",
        user_id="user_a",
        content="Python related",
        memory_type="fake",
        importance=0.2,
    )
    important = MemoryItem(
        id="important",
        user_id="user_a",
        content="Unrelated but important",
        memory_type="fake",
        importance=0.9,
    )

    class StubMemory:
        def retrieve(self, **kwargs):
            return [relevant, important]

    manager.memory_types["fake"] = StubMemory()

    assert [item.id for item in manager.retrieve_memories("Python", limit=2)] == [
        "important",
        "relevant",
    ]
