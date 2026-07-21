from __future__ import annotations


def _build_manager(config, user_id):
    from memory.manager import MemoryManager

    return MemoryManager(
        config=config,
        user_id=user_id,
        enable_working=True,
        enable_episodic=True,
        enable_semantic=True,
        enable_perceptual=False,
    )


def test_working_memory_isolated_between_users(memory_config):
    alice = _build_manager(memory_config, "u_alice")
    bob = _build_manager(memory_config, "u_bob")

    bob.add_memory(
        content="Bob secret_token_BOB_ONLY working memory",
        memory_type="working",
        importance=0.99,
    )

    results = alice.retrieve_memories(
        query="secret_token_BOB_ONLY",
        limit=10,
        memory_types=["working"],
    )

    assert all("secret_token_BOB_ONLY" not in item.content for item in results)


def test_sqlite_backed_episodic_memory_isolated_between_users(memory_config):
    alice = _build_manager(memory_config, "u_alice")
    bob = _build_manager(memory_config, "u_bob")

    bob.add_memory(
        content="Bob secret_token_BOB_ONLY episodic memory",
        memory_type="episodic",
        importance=0.99,
        metadata={"session_id": "s_bob"},
    )
    alice.add_memory(
        content="Alice public memory about Hi-Agent",
        memory_type="episodic",
        importance=0.8,
        metadata={"session_id": "s_alice"},
    )

    alice_results = alice.retrieve_memories(
        query="secret_token_BOB_ONLY",
        limit=10,
        memory_types=["episodic"],
    )
    bob_results = bob.retrieve_memories(
        query="secret_token_BOB_ONLY",
        limit=10,
        memory_types=["episodic"],
    )

    assert all("secret_token_BOB_ONLY" not in item.content for item in alice_results)
    assert any("secret_token_BOB_ONLY" in item.content for item in bob_results)


def test_semantic_memory_isolation_probe(memory_config):
    """This test may expose missing user_id propagation in SemanticMemory.

    If it fails, check SemanticMemory.add(): store.insert(...) and Qdrant payload
    should both include user_id.
    """
    alice = _build_manager(memory_config, "u_alice")
    bob = _build_manager(memory_config, "u_bob")

    bob.add_memory(
        content="Bob Rust async runtime preference semantic memory",
        memory_type="semantic",
        importance=0.93,
        metadata={"session_id": "s_bob"},
    )

    alice_results = alice.retrieve_memories(
        query="Rust async runtime",
        limit=10,
        memory_types=["semantic"],
    )

    assert all("Rust async runtime" not in item.content for item in alice_results)
