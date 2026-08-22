from memory.base import MemoryConfig
from memory.manager import MemoryManager


def test_sqlite_episodic_memory_is_filtered_by_user_id(tmp_path, patch_fake_embedder):
    config = MemoryConfig(database_path=str(tmp_path / "memory.db"))
    manager_a = MemoryManager(
        config=config,
        user_id="user_a",
        enable_working=False,
        enable_episodic=True,
    )
    manager_b = MemoryManager(
        config=config,
        user_id="user_b",
        enable_working=False,
        enable_episodic=True,
    )

    manager_a.add_memory("Alice likes Python", memory_type="episodic")
    manager_b.add_memory("Bob likes coffee", memory_type="episodic")

    assert "Bob likes coffee" not in [
        item.content for item in manager_a.retrieve_memories("coffee")
    ]
    assert [item.content for item in manager_b.retrieve_memories("coffee")] == [
        "Bob likes coffee"
    ]


def test_sqlite_delete_requires_matching_user_id(tmp_path, patch_fake_embedder):
    config = MemoryConfig(database_path=str(tmp_path / "memory.db"))
    manager_a = MemoryManager(
        config=config,
        user_id="user_a",
        enable_working=False,
        enable_episodic=True,
    )
    manager_b = MemoryManager(
        config=config,
        user_id="user_b",
        enable_working=False,
        enable_episodic=True,
    )

    memory_id = manager_a.add_memory("Alice private note", memory_type="episodic")

    assert manager_b.memory_types["episodic"].delete(memory_id, user_id="user_b") is False
    assert manager_a.retrieve_memories("Alice", memory_types=["episodic"])[0].id == memory_id


def test_clear_all_only_clears_current_user(tmp_path, patch_fake_embedder):
    config = MemoryConfig(database_path=str(tmp_path / "memory.db"))
    manager_a = MemoryManager(
        config=config,
        user_id="user_a",
        enable_working=False,
        enable_episodic=True,
    )
    manager_b = MemoryManager(
        config=config,
        user_id="user_b",
        enable_working=False,
        enable_episodic=True,
    )

    manager_a.add_memory("Alice private note", memory_type="episodic")
    manager_b.add_memory("Bob private note", memory_type="episodic")

    assert manager_a.clear_all() == 1
    assert manager_b.retrieve_memories("Bob", memory_types=["episodic"])[0].content == (
        "Bob private note"
    )
