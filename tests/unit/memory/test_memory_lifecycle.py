from __future__ import annotations

from datetime import datetime, timedelta


def _build_manager(config, user_id="u_alice", *, working=True, episodic=True, semantic=False):
    from memory.manager import MemoryManager

    return MemoryManager(
        config=config,
        user_id=user_id,
        enable_working=working,
        enable_episodic=episodic,
        enable_semantic=semantic,
        enable_perceptual=False,
    )


def test_working_capacity_evicts_lowest_importance(memory_config):
    from memory.base import MemoryConfig
    from memory.manager import MemoryManager

    config = MemoryConfig(
        database_path=memory_config.database_path,
        working_memory_capacity=3,
        working_memory_ttl=60,
        qdrant_url=None,
        qdrant_api_key=None,
    )
    manager = MemoryManager(config=config, user_id="u_capacity", enable_working=True)

    manager.add_memory("capacity alpha low", "working", importance=0.05)
    manager.add_memory("capacity beta middle", "working", importance=0.45)
    manager.add_memory("capacity gamma high", "working", importance=0.85)
    manager.add_memory("capacity delta highest", "working", importance=0.95)

    results = manager.retrieve_memories("capacity", limit=10, memory_types=["working"])
    contents = [item.content for item in results]

    assert "capacity alpha low" not in contents
    assert "capacity delta highest" in contents


def test_importance_based_forget_returns_report(memory_config):
    manager = _build_manager(memory_config, user_id="u_forget", episodic=False)

    manager.add_memory("forget trash item", "working", importance=0.08)
    manager.add_memory("forget keeper item", "working", importance=0.88)

    report = manager.forget_memories(
        strategy="importance_based",
        threshold=0.2,
        memory_type="working",
    )

    assert report.deleted_count == 1
    assert report.errors == []

    results = manager.retrieve_memories("forget", limit=10, memory_types=["working"])
    contents = [item.content for item in results]

    assert "forget trash item" not in contents
    assert "forget keeper item" in contents


def test_working_ttl_expires_old_memories(memory_config):
    from memory.base import MemoryConfig, MemoryItem
    from memory.types.working import WorkingMemory
    from tests.conftest import FakeEmbedder

    config = MemoryConfig(
        database_path=memory_config.database_path,
        working_memory_capacity=5,
        working_memory_ttl=1,
    )
    memory = WorkingMemory(config=config, embedder=FakeEmbedder())

    old = MemoryItem(
        user_id="u_ttl",
        content="ttl expired item",
        memory_type="working",
        importance=0.9,
        timestamp=datetime.now() - timedelta(minutes=5),
    )
    fresh = MemoryItem(
        user_id="u_ttl",
        content="ttl fresh item",
        memory_type="working",
        importance=0.9,
    )

    memory.add(old)
    memory.add(fresh)

    results = memory.retrieve("ttl", limit=10, user_id="u_ttl")
    contents = [item.content for item in results]

    assert "ttl expired item" not in contents
    assert "ttl fresh item" in contents


def test_consolidation_is_idempotent_and_preserves_provenance(memory_config):
    manager = _build_manager(memory_config, user_id="u_alice", working=True, episodic=True)

    source_id = manager.add_memory(
        content="consolidate important working memory about pytest fixtures",
        memory_type="working",
        importance=0.91,
        metadata={"session_id": "s_consolidate"},
    )

    first_count = manager.consolidate_memories(
        from_type="working",
        to_type="episodic",
        importance_threshold=0.7,
    )
    second_count = manager.consolidate_memories(
        from_type="working",
        to_type="episodic",
        importance_threshold=0.7,
    )

    assert first_count == 1
    assert second_count == 0

    episodic = manager.retrieve_memories(
        query="pytest fixtures",
        limit=5,
        memory_types=["episodic"],
    )
    assert len([item for item in episodic if "pytest fixtures" in item.content]) == 1

    target = next(item for item in episodic if "pytest fixtures" in item.content)
    assert target.memory_type == "episodic"
    assert target.metadata["provenance"]["source_id"] == source_id
    assert target.metadata["provenance"]["source_type"] == "working"
