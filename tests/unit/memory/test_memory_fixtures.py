from __future__ import annotations

from collections import Counter


def _enabled_types(cases):
    return sorted({case["memory_type"] for case in cases if case["user_id"] == "u_alice"})


def _build_manager(config, user_id="u_alice", *, working=True, episodic=True, semantic=True):
    from memory.manager import MemoryManager

    return MemoryManager(
        config=config,
        user_id=user_id,
        enable_working=working,
        enable_episodic=episodic,
        enable_semantic=semantic,
        enable_perceptual=False,
    )


def seed_cases(manager, cases, user_id="u_alice"):
    inserted = []
    for case in cases:
        if case["user_id"] != user_id:
            continue
        memory_type = case["memory_type"]
        if memory_type not in manager.memory_types:
            continue
        memory_id = manager.add_memory(
            content=case["content"],
            memory_type=memory_type,
            importance=case["importance"],
            metadata={**case.get("metadata", {}), "case_id": case["case_id"]},
        )
        inserted.append((case, memory_id))
    return inserted


def test_fixture_has_enough_coverage(memory_cases):
    counts = Counter(case["memory_type"] for case in memory_cases)

    assert len(memory_cases) >= 24
    assert counts["working"] >= 8
    assert counts["episodic"] >= 5
    assert counts["semantic"] >= 8
    assert any(case["user_id"] == "u_bob" for case in memory_cases)


def test_seeded_positive_queries_retrieve_expected_content(memory_config, memory_cases):
    manager = _build_manager(memory_config)
    seed_cases(manager, memory_cases, user_id="u_alice")

    for case in memory_cases:
        if case["user_id"] != "u_alice":
            continue
        if case["memory_type"] not in manager.memory_types:
            continue
        for query in case.get("positive_queries", [])[:1]:
            results = manager.retrieve_memories(
                query=query,
                limit=5,
                memory_types=[case["memory_type"]],
                min_importance=0.0,
            )
            assert any(case["content"] == item.content for item in results), (
                f"case_id={case['case_id']} query={query!r} was not retrieved; "
                f"got={[item.content for item in results]}"
            )


def test_min_importance_filters_low_value_working_memory(memory_config, memory_cases):
    manager = _build_manager(memory_config, episodic=False, semantic=False)
    seed_cases(manager, memory_cases, user_id="u_alice")

    results = manager.retrieve_memories(
        query="okay",
        limit=10,
        memory_types=["working"],
        min_importance=0.5,
    )

    assert all("用户刚才回复 okay" not in item.content for item in results)


def test_cross_type_retrieval_uses_relevance_not_only_importance(memory_config):
    manager = _build_manager(memory_config, episodic=False, semantic=False)

    manager.add_memory(
        content="unrelated but very important 北京酒店 机票 行程",
        memory_type="working",
        importance=0.99,
        metadata={"case_id": "unrelated_high_importance"},
    )
    manager.add_memory(
        content="target memory about RRF fusion relevance_score and MemorySearchResult",
        memory_type="working",
        importance=0.45,
        metadata={"case_id": "relevant_lower_importance"},
    )

    results = manager.retrieve_memories(
        query="RRF fusion relevance_score MemorySearchResult",
        limit=2,
        memory_types=["working"],
    )

    assert results
    assert results[0].metadata.get("case_id") == "relevant_lower_importance"
