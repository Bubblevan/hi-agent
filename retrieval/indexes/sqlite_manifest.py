from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retrieval.indexes.base import IndexResult, ManifestRecord
from retrieval.models import Chunk, Document


def _validate_scope(user_id: str, namespace: str) -> None:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id must be a non-blank string")
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError("namespace must be a non-blank string")


class SQLiteManifestIndex:
    """持久化文档索引清单，并以事务方式替换一份文档的所有 chunks。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._create_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _create_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS index_manifest (
                    document_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    source TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL,
                    embedding_model TEXT,
                    PRIMARY KEY (user_id, namespace, source)
                );

                CREATE TABLE IF NOT EXISTS indexed_chunks (
                    chunk_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    start_char INTEGER NOT NULL,
                    end_char INTEGER NOT NULL,
                    heading_path TEXT,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (user_id, namespace, chunk_id)
                );

                CREATE INDEX IF NOT EXISTS idx_indexed_chunks_document
                    ON indexed_chunks (user_id, namespace, document_id, position);
                """
            )

    def get_manifest(
        self, user_id: str, namespace: str, source: str
    ) -> ManifestRecord | None:
        _validate_scope(user_id, namespace)
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a non-blank string")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT document_id, user_id, namespace, source, checksum,
                       chunk_count, indexed_at, embedding_model
                FROM index_manifest
                WHERE user_id = ? AND namespace = ? AND source = ?
                """,
                (user_id, namespace, source),
            ).fetchone()
        return self._manifest_from_row(row) if row else None

    def get_chunk_ids(self, user_id: str, namespace: str, source: str) -> list[str]:
        """返回一份 source 当前保存的 chunk 顺序，便于测试和调试。"""
        _validate_scope(user_id, namespace)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT chunk_id
                FROM indexed_chunks
                WHERE user_id = ? AND namespace = ? AND source = ?
                ORDER BY position
                """,
                (user_id, namespace, source),
            ).fetchall()
        return [row["chunk_id"] for row in rows]

    def count_chunks(self, user_id: str, namespace: str, source: str) -> int:
        return len(self.get_chunk_ids(user_id, namespace, source))

    def index_document(
        self,
        document: Document,
        chunks: list[Chunk],
        *,
        embedding_model: str | None = None,
    ) -> IndexResult:
        self._validate_document_and_chunks(document, chunks)
        old = self.get_manifest(document.user_id, document.namespace, document.source)

        with self._connect() as connection:
            old_rows = connection.execute(
                """
                SELECT chunk_id, content, position, start_char, end_char,
                       heading_path, metadata_json
                FROM indexed_chunks
                WHERE user_id = ? AND namespace = ? AND source = ?
                ORDER BY position
                """,
                (document.user_id, document.namespace, document.source),
            ).fetchall()

            if old and self._same_snapshot(old, old_rows, document, chunks, embedding_model):
                return IndexResult(
                    status="unchanged",
                    document_id=document.document_id,
                    inserted_chunk_count=0,
                )

            deleted_count = len(old_rows)
            connection.execute(
                """
                DELETE FROM indexed_chunks
                WHERE user_id = ? AND namespace = ? AND source = ?
                """,
                (document.user_id, document.namespace, document.source),
            )
            connection.execute(
                """
                DELETE FROM index_manifest
                WHERE user_id = ? AND namespace = ? AND source = ?
                """,
                (document.user_id, document.namespace, document.source),
            )

            indexed_at = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                INSERT INTO index_manifest (
                    document_id, user_id, namespace, source, checksum,
                    chunk_count, indexed_at, embedding_model
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.document_id,
                    document.user_id,
                    document.namespace,
                    document.source,
                    document.checksum,
                    len(chunks),
                    indexed_at,
                    embedding_model,
                ),
            )
            connection.executemany(
                """
                INSERT INTO indexed_chunks (
                    chunk_id, document_id, user_id, namespace, source, content,
                    position, start_char, end_char, heading_path, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.user_id,
                        chunk.namespace,
                        document.source,
                        chunk.content,
                        chunk.position,
                        chunk.start_char,
                        chunk.end_char,
                        chunk.heading_path,
                        json.dumps(dict(chunk.metadata), ensure_ascii=False, sort_keys=True),
                    )
                    for chunk in chunks
                ],
            )

        return IndexResult(
            status="inserted" if old is None else "updated",
            document_id=document.document_id,
            deleted_chunk_count=deleted_count,
            inserted_chunk_count=len(chunks),
        )

    def delete_document(self, user_id: str, namespace: str, source: str) -> int:
        _validate_scope(user_id, namespace)
        with self._connect() as connection:
            count = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM indexed_chunks
                WHERE user_id = ? AND namespace = ? AND source = ?
                """,
                (user_id, namespace, source),
            ).fetchone()["count"]
            connection.execute(
                """
                DELETE FROM indexed_chunks
                WHERE user_id = ? AND namespace = ? AND source = ?
                """,
                (user_id, namespace, source),
            )
            connection.execute(
                """
                DELETE FROM index_manifest
                WHERE user_id = ? AND namespace = ? AND source = ?
                """,
                (user_id, namespace, source),
            )
        return int(count)

    @staticmethod
    def _manifest_from_row(row: sqlite3.Row) -> ManifestRecord:
        return ManifestRecord(
            document_id=row["document_id"],
            user_id=row["user_id"],
            namespace=row["namespace"],
            source=row["source"],
            checksum=row["checksum"],
            chunk_count=row["chunk_count"],
            indexed_at=row["indexed_at"],
            embedding_model=row["embedding_model"],
        )

    @staticmethod
    def _validate_document_and_chunks(
        document: Document, chunks: list[Chunk]
    ) -> None:
        _validate_scope(document.user_id, document.namespace)
        if not isinstance(document.source, str) or not document.source.strip():
            raise ValueError("source must be a non-blank string")
        if not isinstance(chunks, list):
            raise TypeError("chunks must be a list")

        expected_positions = list(range(len(chunks)))
        actual_positions = [chunk.position for chunk in chunks]
        if actual_positions != expected_positions:
            raise ValueError("chunk positions must be contiguous and start at zero")

        for chunk in chunks:
            if (
                chunk.document_id != document.document_id
                or chunk.user_id != document.user_id
                or chunk.namespace != document.namespace
            ):
                raise ValueError("chunk does not belong to the indexed document")
            if document.text[chunk.start_char : chunk.end_char] != chunk.content:
                raise ValueError("chunk source span does not match document")
            if Chunk.rebuild_id(document, chunk.content, chunk.position) != chunk.chunk_id:
                raise ValueError("chunk_id does not match document content and position")

    @classmethod
    def _same_snapshot(
        cls,
        old: ManifestRecord,
        old_rows: list[sqlite3.Row],
        document: Document,
        chunks: list[Chunk],
        embedding_model: str | None,
    ) -> bool:
        if (
            old.document_id != document.document_id
            or old.checksum != document.checksum
            or old.embedding_model != embedding_model
            or len(old_rows) != len(chunks)
        ):
            return False
        for row, chunk in zip(old_rows, chunks):
            if (
                row["chunk_id"] != chunk.chunk_id
                or row["content"] != chunk.content
                or row["position"] != chunk.position
                or row["start_char"] != chunk.start_char
                or row["end_char"] != chunk.end_char
                or row["heading_path"] != chunk.heading_path
                or json.loads(row["metadata_json"]) != dict(chunk.metadata)
            ):
                return False
        return True
