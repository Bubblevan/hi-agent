from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

from memory.base import MemoryConfig, MemoryItem
from memory.manager import MemoryManager
from memory.storage.neo4j import Neo4jMemoryStore


class FakeResult:
    def __init__(self, records=None, single_value=None):
        self.records = list(records or [])
        self.single_value = single_value

    def single(self):
        return self.single_value

    def __iter__(self):
        return iter(self.records)


class FakeSession:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def run(self, query, **params):
        self.driver.calls.append((query, params))
        normalized = " ".join(query.split())

        if normalized.startswith("CREATE CONSTRAINT") or normalized.startswith("CREATE INDEX"):
            return FakeResult()

        if normalized.startswith("MERGE (m:Memory"):
            existing = self.driver.nodes.get(params["id"])
            if existing is None:
                existing = {"id": params["id"], "user_id": params["user_id"]}
                self.driver.nodes[params["id"]] = existing
            if existing["user_id"] != params["user_id"]:
                return FakeResult()
            existing.update({
                key: params[key]
                for key in (
                    "content", "memory_type", "timestamp", "importance",
                    "metadata_json", "session_id",
                )
            })
            return FakeResult(single_value={"m": existing})

        if normalized.startswith("MATCH (m:Memory {id: $memory_id") and "DETACH DELETE" not in normalized:
            node = self.driver.nodes.get(params["memory_id"])
            if node and node["user_id"] == params["user_id"]:
                return FakeResult(single_value={"m": node})
            return FakeResult()

        if normalized.startswith("MATCH (m:Memory)") and "DETACH DELETE" in normalized:
            to_delete = [
                node_id
                for node_id, node in self.driver.nodes.items()
                if node["user_id"] == params["user_id"]
                and (
                    params.get("memory_type") is None
                    or node["memory_type"] == params["memory_type"]
                )
            ]
            for node_id in to_delete:
                self.driver.nodes.pop(node_id)
            return FakeResult(single_value={"deleted": len(to_delete)})

        if normalized.startswith("MATCH (m:Memory {id: $memory_id") and "DETACH DELETE" in normalized:
            node = self.driver.nodes.get(params["memory_id"])
            if node and node["user_id"] == params["user_id"]:
                self.driver.nodes.pop(params["memory_id"])
                return FakeResult(single_value={"deleted": 1})
            return FakeResult(single_value={"deleted": 0})

        if normalized.startswith("MATCH (m:Memory) WHERE m.user_id"):
            query_text = params["query_text"].lower()
            records = []
            for node in self.driver.nodes.values():
                if node["user_id"] != params["user_id"]:
                    continue
                if params.get("memory_type") and node["memory_type"] != params["memory_type"]:
                    continue
                if params.get("session_id") and node.get("session_id") != params["session_id"]:
                    continue
                if node["importance"] < params["min_importance"]:
                    continue
                if query_text and query_text not in node["content"].lower():
                    continue
                score = 1.0 if query_text else 0.0
                records.append((score, node["importance"], node["timestamp"], node))
            records.sort(key=lambda value: value[:3], reverse=True)
            return FakeResult(
                records=[{"m": node, "score": score} for score, _, _, node in records[: params["limit"]]]
            )

        if normalized.startswith("MATCH (source:Memory") and "MERGE (source)-[r:RELATED]" in normalized:
            source = self.driver.nodes.get(params["source_id"])
            target = self.driver.nodes.get(params["target_id"])
            if not source or not target or source["user_id"] != params["user_id"] or target["user_id"] != params["user_id"]:
                return FakeResult(single_value={"linked": 0})
            self.driver.relations[(params["source_id"], params["target_id"])] = {
                "relation": params["relation"],
                "weight": params["weight"],
            }
            return FakeResult(single_value={"linked": 1})

        if normalized.startswith("MATCH (source:Memory") and "RETURN target" in normalized:
            records = []
            for (source_id, target_id), relation in self.driver.relations.items():
                if source_id != params["memory_id"]:
                    continue
                source = self.driver.nodes.get(source_id)
                target = self.driver.nodes.get(target_id)
                if not source or not target or source["user_id"] != params["user_id"] or target["user_id"] != params["user_id"]:
                    continue
                if params.get("relation") and relation["relation"] != params["relation"]:
                    continue
                records.append({"target": target, "relation": relation["relation"]})
            return FakeResult(records=records[: params["limit"]])

        raise AssertionError(f"Unhandled Cypher in fake: {normalized}")


class FakeDriver:
    def __init__(self):
        self.nodes = {}
        self.relations = {}
        self.calls = []
        self.closed = False

    def session(self, database=None):
        return FakeSession(self)

    def close(self):
        self.closed = True


def item(memory_id, user_id="alice", memory_type="semantic", content="Neo4j graph"):
    return MemoryItem(
        id=memory_id,
        user_id=user_id,
        content=content,
        memory_type=memory_type,
        timestamp=datetime(2026, 8, 13, 10, 0, 0),
        importance=0.8,
        metadata={"session_id": "s1", "source": "unit-test"},
    )


@pytest.fixture
def store():
    return Neo4jMemoryStore(driver=FakeDriver(), ensure_schema=False)


def test_upsert_get_and_tenant_isolation(store):
    saved = item("m-1")
    assert store.upsert(saved) is True

    loaded = store.get("m-1", "alice")
    assert loaded is not None
    assert loaded.content == saved.content
    assert loaded.metadata["source"] == "unit-test"
    assert store.get("m-1", "bob") is None

    query, params = store.driver.calls[-1]
    assert "$user_id" in query
    assert params["user_id"] == "bob"


def test_search_filters_tenant_type_session_and_importance(store):
    assert store.upsert(item("m-1", content="Neo4j relationships"))
    assert store.upsert(item("m-2", memory_type="episodic", content="Neo4j session"))
    assert store.upsert(item("m-3", user_id="bob", content="Neo4j relationships"))

    results = store.search(
        "relationships", "alice", memory_type="semantic", session_id="s1", min_importance=0.7
    )
    assert [result.id for result in results] == ["m-1"]
    assert results[0].metadata["graph_score"] == 1.0


def test_delete_and_clear_are_user_scoped(store):
    assert store.upsert(item("a-1"))
    assert store.upsert(item("a-2", memory_type="episodic"))
    assert store.upsert(item("b-1", user_id="bob"))

    assert store.delete("a-1", "alice") is True
    assert store.get("a-1", "alice") is None
    assert store.clear("alice", memory_type="episodic") == 1
    assert store.get("b-1", "bob") is not None


def test_relationships_are_tenant_scoped_and_relation_is_data(store):
    assert store.upsert(item("a-1"))
    assert store.upsert(item("a-2", content="related target"))
    assert store.upsert(item("b-1", user_id="bob"))

    assert store.relate("a-1", "a-2", "alice", relation="SUPPORTS", weight=0.9)
    related = store.related("a-1", "alice", relation="SUPPORTS")
    assert [result.id for result in related] == ["a-2"]
    assert related[0].metadata["graph_relation"] == "SUPPORTS"
    assert store.relate("a-1", "b-1", "alice") is False
    assert store.related("a-1", "bob") == []


def test_schema_setup_and_close():
    driver = FakeDriver()
    adapter = Neo4jMemoryStore(driver=driver, ensure_schema=True)
    schema_calls = [query for query, _ in driver.calls if query.strip().startswith(("CREATE CONSTRAINT", "CREATE INDEX"))]
    assert len(schema_calls) == 4
    adapter.close()
    assert driver.closed is False  # injected drivers belong to the caller


def test_missing_credentials_without_driver():
    with pytest.raises(ValueError, match="uri, user, and password"):
        Neo4jMemoryStore(ensure_schema=False)


def test_config_reads_neo4j_database_and_enabled(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://example")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    monkeypatch.setenv("NEO4J_DATABASE", "memory")
    monkeypatch.setenv("NEO4J_ENABLED", "true")

    config = MemoryConfig.from_env()
    assert config.neo4j_database == "memory"
    assert config.neo4j_enabled is True


def test_manager_projects_added_memories_and_exposes_graph_traversal():
    graph = Neo4jMemoryStore(driver=FakeDriver(), ensure_schema=False)
    database_path = Path.cwd() / f".neo4j-manager-{uuid4().hex}.db"
    try:
        config = MemoryConfig(database_path=str(database_path))
        manager = MemoryManager(
            config=config,
            user_id="alice",
            enable_working=True,
            neo4j_store=graph,
        )

        first_id = manager.add_memory("first graph memory")
        second_id = manager.add_memory("second graph memory")
        assert graph.get(first_id, "alice") is not None
        assert graph.get(second_id, "alice") is not None
        assert manager.link_memories(first_id, second_id, relation="FOLLOWS") is True
        assert [item.id for item in manager.retrieve_related_memories(first_id)] == [second_id]
        assert manager.update_memory(first_id, content="updated graph memory", importance=0.9)
        assert graph.get(first_id, "alice").content == "updated graph memory"
        assert manager.delete_memory(second_id) is True
        assert graph.get(second_id, "alice") is None
        assert manager.graph_sync_errors == []
        manager.close()
    finally:
        for path in database_path.parent.glob(f"{database_path.stem}*"):
            path.unlink(missing_ok=True)
