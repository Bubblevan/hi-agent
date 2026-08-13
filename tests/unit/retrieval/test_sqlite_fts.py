from __future__ import annotations

import pytest

from retrieval.indexes.sqlite_fts import SQLiteFTSIndex
from retrieval.models import Chunk, Document


def make_document(
    text: str,
    *,
    user_id: str = "alice",
    namespace: str = "notes",
    source: str = "notes.md",
) -> Document:
    return Document.build(
        user_id=user_id,
        namespace=namespace,
        source=source,
        text=text,
    )


def make_chunks(document: Document) -> list[Chunk]:
    pieces = document.text.split("\n\n")
    chunks = []
    cursor = 0
    for position, piece in enumerate(pieces):
        start = document.text.index(piece, cursor)
        end = start + len(piece)
        chunks.append(
            Chunk.build(
                document=document,
                content=piece,
                position=position,
                start_char=start,
                end_char=end,
                heading_path=f"# section {position}",
                metadata={"topic": "rag" if position == 0 else "memory"},
            )
        )
        cursor = end
    return chunks


def test_fts5_search_returns_bm25_results_in_relevance_order(tmp_path) -> None:
    index = SQLiteFTSIndex(tmp_path / "fts.sqlite3")
    document = make_document(
        "Qdrant stores dense vectors for semantic retrieval.\n\n"
        "SQLite stores source metadata and provenance."
    )
    chunks = make_chunks(document)
    index.replace_document(document, chunks)

    results = index.search("dense vectors", user_id="alice", namespace="notes")

    assert results
    assert results[0].chunk.chunk_id == chunks[0].chunk_id
    assert results[0].retriever == "bm25"
    assert results[0].score > 0
    assert results[0].score_components["bm25"] == pytest.approx(results[0].score)


def test_fts_search_isolated_by_tenant_and_source(tmp_path) -> None:
    index = SQLiteFTSIndex(tmp_path / "fts.sqlite3")
    alice = make_document("private alpha retrieval", source="alice.md")
    bob = make_document("private alpha retrieval", user_id="bob", source="bob.md")
    other = make_document("private alpha retrieval", source="other.md")
    index.replace_document(alice, make_chunks(alice))
    index.replace_document(bob, make_chunks(bob))
    index.replace_document(other, make_chunks(other))

    results = index.search(
        "private alpha",
        user_id="alice",
        namespace="notes",
        source="alice.md",
    )

    assert len(results) == 1
    assert results[0].chunk.user_id == "alice"


def test_replacing_document_removes_stale_chunks(tmp_path) -> None:
    index = SQLiteFTSIndex(tmp_path / "fts.sqlite3")
    old = make_document("old qdrant content\n\nold sqlite content")
    new = make_document("new qdrant content")
    index.replace_document(old, make_chunks(old))

    index.replace_document(new, make_chunks(new))

    assert index.search("old", user_id="alice", namespace="notes") == []
    assert index.search("new", user_id="alice", namespace="notes")[0].chunk.content == "new qdrant content"


def test_search_supports_metadata_filter(tmp_path) -> None:
    index = SQLiteFTSIndex(tmp_path / "fts.sqlite3")
    document = make_document("retrieval notes\n\nretrieval memory")
    chunks = make_chunks(document)
    index.replace_document(document, chunks)

    results = index.search(
        "retrieval",
        user_id="alice",
        namespace="notes",
        metadata_filters={"topic": "memory"},
    )

    assert [result.chunk.chunk_id for result in results] == [chunks[1].chunk_id]


def test_query_is_escaped_and_invalid_arguments_are_rejected(tmp_path) -> None:
    index = SQLiteFTSIndex(tmp_path / "fts.sqlite3")
    document = make_document("BM25 retrieval supports safe query parsing")
    index.replace_document(document, make_chunks(document))

    assert index.search('BM25 OR "broken', user_id="alice", namespace="notes")
    with pytest.raises(ValueError, match="query"):
        index.search(" ", user_id="alice", namespace="notes")
    with pytest.raises(ValueError, match="limit"):
        index.search("BM25", user_id="alice", namespace="notes", limit=0)
