from __future__ import annotations

from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models

from retrieval.indexes.qdrant import QdrantVectorStore
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
    midpoint = len(document.text) // 2
    return [
        Chunk.build(
            document=document,
            content=document.text[:midpoint],
            position=0,
            start_char=0,
            end_char=midpoint,
            heading_path="# first",
            metadata={"kind": "note", "position_label": 0},
        ),
        Chunk.build(
            document=document,
            content=document.text[midpoint:],
            position=1,
            start_char=midpoint,
            end_char=len(document.text),
            metadata={"kind": "note", "position_label": 1},
        ),
    ]


def make_store(*, dimension: int = 3, collection_name: str = "rag-test"):
    client = QdrantClient(":memory:")
    store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        dimension=dimension,
    )
    return store, client


def test_store_creates_collection_and_upserts_chunk_payloads() -> None:
    store, client = make_store()
    document = make_document("abcdef")
    chunks = make_chunks(document)

    inserted = store.upsert_chunks(document, chunks, [[1, 0, 0], [0, 1, 0]])

    assert inserted == 2
    collection = client.get_collection("rag-test")
    assert collection.config.params.vectors.size == 3
    assert collection.config.params.vectors.distance == models.Distance.COSINE
    assert store.count_chunks("alice", "notes", "notes.md") == 2
    points, _ = client.scroll(collection_name="rag-test", limit=10, with_payload=True)
    payloads = {point.payload["chunk_id"]: point.payload for point in points}
    assert payloads[chunks[0].chunk_id]["source"] == "notes.md"
    assert payloads[chunks[0].chunk_id]["user_id"] == "alice"
    assert payloads[chunks[0].chunk_id]["heading_path"] == "# first"
    assert payloads[chunks[0].chunk_id]["metadata"] == {
        "kind": "note",
        "position_label": 0,
    }


def test_upsert_is_idempotent_for_same_chunk_ids() -> None:
    store, _ = make_store()
    document = make_document("abcdef")
    chunks = make_chunks(document)
    vectors = [[1, 0, 0], [0, 1, 0]]

    assert store.upsert_chunks(document, chunks, vectors) == 2
    assert store.upsert_chunks(document, chunks, vectors) == 2
    assert store.count_chunks("alice", "notes", "notes.md") == 2


def test_tenant_filter_prevents_cross_user_counts_and_deletes() -> None:
    store, _ = make_store()
    alice = make_document("abcdef", user_id="alice")
    bob = make_document("uvwxyz", user_id="bob")
    store.upsert_chunks(alice, make_chunks(alice), [[1, 0, 0], [0, 1, 0]])
    store.upsert_chunks(bob, make_chunks(bob), [[1, 0, 0], [0, 0, 1]])

    assert store.count_chunks("alice", "notes", "notes.md") == 2
    assert store.count_chunks("bob", "notes", "notes.md") == 2
    assert store.delete_document("alice", "notes", "notes.md") == 2
    assert store.count_chunks("alice", "notes", "notes.md") == 0
    assert store.count_chunks("bob", "notes", "notes.md") == 2


def test_delete_isolated_by_source_and_namespace() -> None:
    store, _ = make_store()
    first = make_document("abcdef", source="first.md", namespace="notes")
    second = make_document("uvwxyz", source="second.md", namespace="notes")
    other_namespace = make_document("123456", source="first.md", namespace="archive")
    store.upsert_chunks(first, make_chunks(first), [[1, 0, 0], [0, 1, 0]])
    store.upsert_chunks(second, make_chunks(second), [[1, 0, 0], [0, 0, 1]])
    store.upsert_chunks(other_namespace, make_chunks(other_namespace), [[1, 0, 0], [0, 0, 1]])

    assert store.delete_document("alice", "notes", "first.md") == 2
    assert store.count_chunks("alice", "notes", "second.md") == 2
    assert store.count_chunks("alice", "archive", "first.md") == 2


def test_upsert_rejects_invalid_chunk_or_vector_before_write() -> None:
    store, _ = make_store()
    document = make_document("abcdef")
    chunks = make_chunks(document)
    foreign = make_chunks(make_document("uvwxyz", user_id="bob"))

    with pytest.raises(ValueError, match="does not belong"):
        store.upsert_chunks(document, [chunks[0], foreign[1]], [[1, 0, 0], [0, 1, 0]])
    with pytest.raises(ValueError, match="same number"):
        store.upsert_chunks(document, chunks, [[1, 0, 0]])
    with pytest.raises(ValueError, match="dimension"):
        store.upsert_chunks(document, chunks, [[1, 0], [0, 1]])
    assert store.count_chunks("alice", "notes", "notes.md") == 0


def test_existing_collection_dimension_must_match() -> None:
    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name="rag-test",
        vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE),
    )

    with pytest.raises(ValueError, match="dimension"):
        QdrantVectorStore(client=client, collection_name="rag-test", dimension=3)


def test_search_returns_dense_results_in_similarity_order() -> None:
    store, _ = make_store()
    document = make_document("abcdef")
    chunks = make_chunks(document)
    store.upsert_chunks(document, chunks, [[1, 0, 0], [0, 1, 0]])

    results = store.search(
        [0, 1, 0],
        user_id="alice",
        namespace="notes",
        limit=2,
    )

    assert [result.chunk.chunk_id for result in results] == [chunks[1].chunk_id, chunks[0].chunk_id]
    assert results[0].retriever == "dense"
    assert results[0].score == pytest.approx(1.0)
    assert results[0].score_components["dense"] == pytest.approx(1.0)
    assert results[0].chunk.content == chunks[1].content


def test_search_always_applies_tenant_and_optional_source_filters() -> None:
    store, _ = make_store()
    alice = make_document("abcdef", user_id="alice", source="alice.md")
    bob = make_document("uvwxyz", user_id="bob", source="bob.md")
    store.upsert_chunks(alice, make_chunks(alice), [[1, 0, 0], [0, 1, 0]])
    store.upsert_chunks(bob, make_chunks(bob), [[1, 0, 0], [0, 1, 0]])

    results = store.search(
        [1, 0, 0],
        user_id="alice",
        namespace="notes",
        source="alice.md",
        limit=10,
    )

    assert len(results) == 2
    assert {result.chunk.user_id for result in results} == {"alice"}


def test_search_supports_nested_chunk_metadata_filters() -> None:
    store, _ = make_store()
    document = make_document("abcdef")
    chunks = make_chunks(document)
    store.upsert_chunks(document, chunks, [[1, 0, 0], [0, 1, 0]])

    results = store.search(
        [1, 0, 0],
        user_id="alice",
        namespace="notes",
        limit=10,
        metadata_filters={"position_label": 1},
    )

    assert [result.chunk.chunk_id for result in results] == [chunks[1].chunk_id]


def test_search_rejects_invalid_query_parameters() -> None:
    store, _ = make_store()

    with pytest.raises(ValueError, match="limit"):
        store.search([1, 0, 0], user_id="alice", namespace="notes", limit=0)
    with pytest.raises(ValueError, match="dimension"):
        store.search([1, 0], user_id="alice", namespace="notes")
    with pytest.raises(ValueError, match="user_id"):
        store.search([1, 0, 0], user_id="", namespace="notes")
