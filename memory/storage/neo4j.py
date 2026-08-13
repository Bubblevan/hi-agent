"""Neo4j graph projection for Memory.

SQLite remains the source of truth for memory records and Qdrant remains the
semantic index.  This adapter stores a tenant-scoped graph projection: memory
nodes plus explicit ``RELATED`` edges.  Keeping the graph as a projection
makes Neo4j optional and avoids making graph availability a prerequisite for
basic Memory CRUD.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, List, Optional

from ..base import MemoryItem


class Neo4jMemoryStore:
    """Store and traverse Memory records in Neo4j.

    The driver is injectable so all behavior can be tested without a live
    Aura instance.  ``user_id`` is required on every data operation; it is
    part of every node and relationship query and therefore acts as the
    application-level tenant boundary.
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
        *,
        driver: Any = None,
        ensure_schema: bool = True,
    ) -> None:
        self.database = database
        self._owns_driver = driver is None
        if driver is None:
            if not uri or not user or not password:
                raise ValueError(
                    "Neo4j requires uri, user, and password when no driver is injected"
                )
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(uri, auth=(user, password))
        self.driver = driver
        if ensure_schema:
            self.ensure_schema()

    def _session(self):
        if self.database:
            return self.driver.session(database=self.database)
        return self.driver.session()

    def ensure_schema(self) -> None:
        """Create the constraints and indexes needed by the adapter."""
        statements = (
            "CREATE CONSTRAINT memory_id_unique IF NOT EXISTS "
            "FOR (m:Memory) REQUIRE m.id IS UNIQUE",
            "CREATE INDEX memory_user_id IF NOT EXISTS "
            "FOR (m:Memory) ON (m.user_id)",
            "CREATE INDEX memory_type IF NOT EXISTS "
            "FOR (m:Memory) ON (m.memory_type)",
            "CREATE INDEX memory_session_id IF NOT EXISTS "
            "FOR (m:Memory) ON (m.session_id)",
        )
        with self._session() as session:
            for statement in statements:
                session.run(statement)

    @staticmethod
    def _properties(item: MemoryItem) -> dict[str, Any]:
        return {
            "id": item.id,
            "user_id": item.user_id,
            "content": item.content,
            "memory_type": item.memory_type,
            "timestamp": item.timestamp.isoformat(),
            "importance": float(item.importance),
            "metadata_json": json.dumps(item.metadata, ensure_ascii=False),
            "session_id": item.metadata.get("session_id"),
        }

    @staticmethod
    def _node_to_item(node: Any, extra_metadata: Optional[dict[str, Any]] = None) -> MemoryItem:
        properties = dict(node)
        metadata = json.loads(properties.get("metadata_json") or "{}")
        if extra_metadata:
            metadata.update(extra_metadata)
        return MemoryItem(
            id=str(properties["id"]),
            user_id=str(properties.get("user_id", "default_user")),
            content=str(properties.get("content", "")),
            memory_type=str(properties.get("memory_type", "semantic")),
            timestamp=datetime.fromisoformat(str(properties["timestamp"])),
            importance=float(properties.get("importance", 0.5)),
            metadata=metadata,
        )

    def upsert(self, item: MemoryItem) -> bool:
        """Insert or update one node, without allowing cross-tenant overwrite."""
        query = """
        MERGE (m:Memory {id: $id})
        ON CREATE SET m.user_id = $user_id
        WITH m
        WHERE m.user_id = $user_id
        SET m.content = $content,
            m.memory_type = $memory_type,
            m.timestamp = $timestamp,
            m.importance = $importance,
            m.metadata_json = $metadata_json,
            m.session_id = $session_id
        RETURN m
        """
        with self._session() as session:
            return session.run(query, **self._properties(item)).single() is not None

    def get(self, memory_id: str, user_id: str) -> Optional[MemoryItem]:
        query = """
        MATCH (m:Memory {id: $memory_id, user_id: $user_id})
        RETURN m
        """
        with self._session() as session:
            record = session.run(query, memory_id=memory_id, user_id=user_id).single()
        if record is None:
            return None
        return self._node_to_item(record["m"])

    def search(
        self,
        query_text: str,
        user_id: str,
        *,
        limit: int = 10,
        memory_type: Optional[str] = None,
        session_id: Optional[str] = None,
        min_importance: float = 0.0,
    ) -> List[MemoryItem]:
        """Search the graph projection with tenant and metadata filters.

        This is deliberately a graph-side lexical filter, not a replacement
        for Qdrant semantic search.  Use Memory's existing Qdrant path for
        meaning-based retrieval and this method for graph-aware filtering.
        """
        query = """
        MATCH (m:Memory)
        WHERE m.user_id = $user_id
          AND ($memory_type IS NULL OR m.memory_type = $memory_type)
          AND ($session_id IS NULL OR m.session_id = $session_id)
          AND m.importance >= $min_importance
          AND ($query_text = '' OR toLower(m.content) CONTAINS toLower($query_text))
        RETURN m,
               CASE WHEN $query_text = '' THEN 0.0
                    WHEN toLower(m.content) CONTAINS toLower($query_text) THEN 1.0
                    ELSE 0.0 END AS score
        ORDER BY score DESC, m.importance DESC, m.timestamp DESC
        LIMIT $limit
        """
        with self._session() as session:
            records = session.run(
                query,
                query_text=query_text,
                user_id=user_id,
                memory_type=memory_type,
                session_id=session_id,
                min_importance=float(min_importance),
                limit=int(limit),
            )
            return [
                self._node_to_item(
                    record["m"],
                    {"graph_score": float(record.get("score", 0.0))},
                )
                for record in records
            ]

    def delete(self, memory_id: str, user_id: str) -> bool:
        query = """
        MATCH (m:Memory {id: $memory_id, user_id: $user_id})
        DETACH DELETE m
        RETURN count(m) AS deleted
        """
        with self._session() as session:
            record = session.run(query, memory_id=memory_id, user_id=user_id).single()
        return bool(record and record.get("deleted", 0))

    def clear(self, user_id: str, memory_type: Optional[str] = None) -> int:
        query = """
        MATCH (m:Memory)
        WHERE m.user_id = $user_id
          AND ($memory_type IS NULL OR m.memory_type = $memory_type)
        DETACH DELETE m
        RETURN count(m) AS deleted
        """
        with self._session() as session:
            record = session.run(
                query, user_id=user_id, memory_type=memory_type
            ).single()
        return int(record.get("deleted", 0)) if record else 0

    def relate(
        self,
        source_id: str,
        target_id: str,
        user_id: str,
        *,
        relation: str = "RELATED_TO",
        weight: float = 1.0,
    ) -> bool:
        """Create a typed edge while keeping the Cypher relationship static."""
        query = """
        MATCH (source:Memory {id: $source_id, user_id: $user_id})
        MATCH (target:Memory {id: $target_id, user_id: $user_id})
        MERGE (source)-[r:RELATED]->(target)
        SET r.relation = $relation, r.weight = $weight
        RETURN count(r) AS linked
        """
        with self._session() as session:
            record = session.run(
                query,
                source_id=source_id,
                target_id=target_id,
                user_id=user_id,
                relation=relation,
                weight=float(weight),
            ).single()
        return bool(record and record.get("linked", 0))

    def related(
        self,
        memory_id: str,
        user_id: str,
        *,
        relation: Optional[str] = None,
        limit: int = 10,
    ) -> List[MemoryItem]:
        query = """
        MATCH (source:Memory {id: $memory_id, user_id: $user_id})
              -[r:RELATED]->(target:Memory {user_id: $user_id})
        WHERE $relation IS NULL OR r.relation = $relation
        RETURN target, r.relation AS relation
        ORDER BY target.importance DESC, target.timestamp DESC
        LIMIT $limit
        """
        with self._session() as session:
            records = session.run(
                query,
                memory_id=memory_id,
                user_id=user_id,
                relation=relation,
                limit=int(limit),
            )
            return [
                self._node_to_item(
                    record["target"],
                    {"graph_relation": record.get("relation")},
                )
                for record in records
            ]

    def close(self) -> None:
        if self._owns_driver:
            self.driver.close()

    def __enter__(self) -> "Neo4jMemoryStore":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
