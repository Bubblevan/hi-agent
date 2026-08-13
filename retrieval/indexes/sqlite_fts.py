from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from types import MappingProxyType

from retrieval.models import Chunk, Document, RetrievalResult


_QUERY_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
_METADATA_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_scope(user_id: str, namespace: str) -> None:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id must be a non-blank string")
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError("namespace must be a non-blank string")


class SQLiteFTSIndex:
    """SQLite FTS5 index using its built-in BM25 ranking function."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._create_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_schema(self) -> None:
        with self._connect() as connection:
            try:
                connection.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                        chunk_id UNINDEXED,
                        document_id UNINDEXED,
                        user_id UNINDEXED,
                        namespace UNINDEXED,
                        source UNINDEXED,
                        content,
                        heading_path,
                        position UNINDEXED,
                        start_char UNINDEXED,
                        end_char UNINDEXED,
                        metadata_json UNINDEXED,
                        tokenize = 'unicode61'
                    );
                    """
                )
            except sqlite3.OperationalError as exc:
                raise RuntimeError("SQLite FTS5 is not available in this Python build") from exc

    def replace_document(self, document: Document, chunks: list[Chunk]) -> int:
        self._validate_document_and_chunks(document, chunks)
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM chunks_fts
                WHERE user_id = ? AND namespace = ? AND source = ?
                """,
                (document.user_id, document.namespace, document.source),
            )
            connection.executemany(
                """
                INSERT INTO chunks_fts (
                    chunk_id, document_id, user_id, namespace, source, content,
                    heading_path, position, start_char, end_char, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        document.document_id,
                        document.user_id,
                        document.namespace,
                        document.source,
                        chunk.content,
                        chunk.heading_path or "",
                        chunk.position,
                        chunk.start_char,
                        chunk.end_char,
                        json.dumps(
                            dict(chunk.metadata),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    )
                    for chunk in chunks
                ],
            )
        return len(chunks)

    def search(
        self,
        query: str,
        *,
        user_id: str,
        namespace: str,
        limit: int = 5,
        source: str | None = None,
        metadata_filters: dict[str, object] | None = None,
    ) -> list[RetrievalResult]:
        _validate_scope(user_id, namespace)
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-blank string")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if source is not None and (not isinstance(source, str) or not source.strip()):
            raise ValueError("source must be a non-blank string")

        match_query = self._build_match_query(query)
        if not match_query:
            return []

        conditions = ["chunks_fts MATCH ?", "user_id = ?", "namespace = ?"]
        parameters: list[object] = [match_query, user_id, namespace]
        if source is not None:
            conditions.append("source = ?")
            parameters.append(source)
        for key, value in (metadata_filters or {}).items():
            if not isinstance(key, str) or not _METADATA_KEY_RE.fullmatch(key):
                raise ValueError("metadata filter keys must be simple field names")
            conditions.append("json_extract(metadata_json, ?) = ?")
            parameters.extend([f"$.{key}", value])
        parameters.append(limit)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT chunk_id, document_id, user_id, namespace, content,
                       source, position, start_char, end_char, heading_path,
                       metadata_json, -bm25(chunks_fts) AS relevance
                FROM chunks_fts
                WHERE {' AND '.join(conditions)}
                ORDER BY bm25(chunks_fts) ASC, position ASC
                LIMIT ?
                """,
                parameters,
            ).fetchall()

        results: list[RetrievalResult] = []
        for row in rows:
            score = float(row["relevance"])
            chunk = Chunk(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                user_id=row["user_id"],
                namespace=row["namespace"],
                source=row["source"],
                content=row["content"],
                position=row["position"],
                start_char=row["start_char"],
                end_char=row["end_char"],
                heading_path=row["heading_path"] or None,
                metadata=MappingProxyType(json.loads(row["metadata_json"])),
            )
            results.append(
                RetrievalResult.from_chunk(
                    chunk=chunk,
                    score=score,
                    retriever="bm25",
                    score_components={"bm25": score},
                )
            )
        return results

    @staticmethod
    def _build_match_query(query: str) -> str:
        tokens = _QUERY_TOKEN_RE.findall(query)
        return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)

    @staticmethod
    def _validate_document_and_chunks(
        document: Document, chunks: list[Chunk]
    ) -> None:
        _validate_scope(document.user_id, document.namespace)
        if not isinstance(document.source, str) or not document.source.strip():
            raise ValueError("source must be a non-blank string")
        if not isinstance(chunks, list):
            raise TypeError("chunks must be a list")
        if [chunk.position for chunk in chunks] != list(range(len(chunks))):
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
            json.dumps(dict(chunk.metadata), ensure_ascii=False, sort_keys=True)
