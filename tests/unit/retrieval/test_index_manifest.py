from dataclasses import replace

import pytest

from retrieval.indexes.sqlite_manifest import SQLiteManifestIndex
from retrieval.models import Chunk, Document


def make_document(
    text: str,
    *,
    user_id: str = "alice",
    namespace: str = "notes",
    source: str = "notes.md",
    document_id: str | None = None,
) -> Document:
    return Document.build(
        user_id=user_id,
        namespace=namespace,
        source=source,
        text=text,
        document_id=document_id,
    )


def make_chunks(document: Document, boundaries: list[tuple[int, int]]) -> list[Chunk]:
    return [
        Chunk.build(
            document=document,
            content=document.text[start:end],
            position=position,
            start_char=start,
            end_char=end,
            metadata={"position_label": position},
        )
        for position, (start, end) in enumerate(boundaries)
    ]


def test_first_index_creates_manifest_and_chunks(tmp_path) -> None:
    document = make_document("alpha\nbeta")
    chunks = make_chunks(document, [(0, 5), (5, 10)])
    index = SQLiteManifestIndex(tmp_path / "manifest.sqlite3")

    result = index.index_document(document, chunks, embedding_model="qwen3.7-text-embedding")

    assert result.status == "inserted"
    assert result.deleted_chunk_count == 0
    assert result.inserted_chunk_count == 2
    manifest = index.get_manifest("alice", "notes", "notes.md")
    assert manifest is not None
    assert manifest.document_id == document.document_id
    assert manifest.checksum == document.checksum
    assert manifest.chunk_count == 2
    assert manifest.embedding_model == "qwen3.7-text-embedding"
    assert index.get_chunk_ids("alice", "notes", "notes.md") == [
        chunk.chunk_id for chunk in chunks
    ]


def test_same_snapshot_is_idempotent(tmp_path) -> None:
    document = make_document("alpha\nbeta")
    chunks = make_chunks(document, [(0, 5), (5, 10)])
    index = SQLiteManifestIndex(tmp_path / "manifest.sqlite3")
    index.index_document(document, chunks)
    first_manifest = index.get_manifest("alice", "notes", "notes.md")

    result = index.index_document(document, chunks)

    assert result.status == "unchanged"
    assert result.deleted_chunk_count == 0
    assert result.inserted_chunk_count == 0
    assert index.count_chunks("alice", "notes", "notes.md") == 2
    assert index.get_manifest("alice", "notes", "notes.md").indexed_at == first_manifest.indexed_at


def test_changed_source_replaces_old_chunks(tmp_path) -> None:
    old_document = make_document("alpha\nbeta")
    old_chunks = make_chunks(old_document, [(0, 5), (5, 10)])
    new_document = make_document("alpha\ngamma")
    new_chunks = make_chunks(new_document, [(0, 5), (5, 11)])
    index = SQLiteManifestIndex(tmp_path / "manifest.sqlite3")
    index.index_document(old_document, old_chunks)

    result = index.index_document(new_document, new_chunks)

    assert result.status == "updated"
    assert result.deleted_chunk_count == 2
    assert result.inserted_chunk_count == 2
    assert index.get_chunk_ids("alice", "notes", "notes.md") == [
        chunk.chunk_id for chunk in new_chunks
    ]
    assert not set(index.get_chunk_ids("alice", "notes", "notes.md")) & {
        chunk.chunk_id for chunk in old_chunks
    }
    assert index.get_manifest("alice", "notes", "notes.md").document_id == new_document.document_id


def test_same_source_and_checksum_but_new_chunking_reindexes(tmp_path) -> None:
    document = make_document("alpha\nbeta", document_id="stable-document")
    old_chunks = make_chunks(document, [(0, 5), (5, 10)])
    new_chunks = make_chunks(document, [(0, 10)])
    index = SQLiteManifestIndex(tmp_path / "manifest.sqlite3")
    index.index_document(document, old_chunks)

    result = index.index_document(document, new_chunks)

    assert result.status == "updated"
    assert result.deleted_chunk_count == 2
    assert result.inserted_chunk_count == 1
    assert index.count_chunks("alice", "notes", "notes.md") == 1


def test_source_is_isolated_by_user_and_namespace(tmp_path) -> None:
    alice_document = make_document("alice", user_id="alice")
    bob_document = make_document("bob", user_id="bob")
    alice_chunks = make_chunks(alice_document, [(0, 5)])
    bob_chunks = make_chunks(bob_document, [(0, 3)])
    index = SQLiteManifestIndex(tmp_path / "manifest.sqlite3")
    index.index_document(alice_document, alice_chunks)
    index.index_document(bob_document, bob_chunks)

    assert index.get_manifest("alice", "notes", "notes.md").document_id == alice_document.document_id
    assert index.get_manifest("bob", "notes", "notes.md").document_id == bob_document.document_id
    assert index.count_chunks("alice", "notes", "notes.md") == 1
    assert index.count_chunks("bob", "notes", "notes.md") == 1


def test_delete_document_removes_manifest_and_chunks(tmp_path) -> None:
    document = make_document("alpha\nbeta")
    index = SQLiteManifestIndex(tmp_path / "manifest.sqlite3")
    index.index_document(document, make_chunks(document, [(0, 5), (5, 10)]))

    deleted = index.delete_document("alice", "notes", "notes.md")

    assert deleted == 2
    assert index.get_manifest("alice", "notes", "notes.md") is None
    assert index.get_chunk_ids("alice", "notes", "notes.md") == []
    assert index.delete_document("alice", "notes", "notes.md") == 0


def test_invalid_chunk_is_rejected_before_existing_index_is_touched(tmp_path) -> None:
    document = make_document("alpha\nbeta")
    chunks = make_chunks(document, [(0, 5), (5, 10)])
    index = SQLiteManifestIndex(tmp_path / "manifest.sqlite3")
    index.index_document(document, chunks)
    invalid = replace(chunks[1], content="not beta")

    with pytest.raises(ValueError, match="source span"):
        index.index_document(document, [chunks[0], invalid])

    assert index.get_chunk_ids("alice", "notes", "notes.md") == [
        chunk.chunk_id for chunk in chunks
    ]


@pytest.mark.parametrize(
    ("user_id", "namespace"),
    [("", "notes"), ("alice", " "), (None, "notes")],
)
def test_scope_must_be_non_blank(user_id, namespace, tmp_path) -> None:
    document = make_document("text", user_id=user_id, namespace=namespace)
    index = SQLiteManifestIndex(tmp_path / "manifest.sqlite3")

    with pytest.raises(ValueError, match="user_id|namespace"):
        index.index_document(document, [])
