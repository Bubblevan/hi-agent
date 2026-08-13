import pytest

from retrieval.models import Chunk, Document


def make_document(text: str = "prefix body suffix") -> Document:
    return Document.build(
        user_id="alice",
        namespace="notes",
        source="notes/example.md",
        text=text,
    )


def test_document_checksum_and_id_are_deterministic() -> None:
    first = make_document()
    second = make_document()

    assert first.checksum == second.checksum
    assert first.document_id == second.document_id


def test_document_id_changes_when_source_or_text_changes() -> None:
    original = make_document()
    changed_text = make_document("prefix changed suffix")
    changed_source = Document.build(
        user_id="alice",
        namespace="notes",
        source="notes/other.md",
        text=original.text,
    )

    assert original.document_id != changed_text.document_id
    assert original.document_id != changed_source.document_id
    assert original.checksum != changed_text.checksum


def test_chunk_id_is_deterministic_and_rebuildable() -> None:
    document = make_document()
    kwargs = {
        "document": document,
        "content": "body",
        "position": 0,
        "start_char": 7,
        "end_char": 11,
    }

    first = Chunk.build(**kwargs)
    second = Chunk.build(**kwargs)

    assert first.chunk_id == second.chunk_id
    assert first.chunk_id == Chunk.rebuild_id(document, "body", 0)


def test_chunk_keeps_document_tenant_context() -> None:
    document = make_document()
    chunk = Chunk.build(
        document=document,
        content="body",
        position=0,
        start_char=7,
        end_char=11,
    )

    assert chunk.document_id == document.document_id
    assert chunk.user_id == "alice"
    assert chunk.namespace == "notes"


def test_chunk_span_matches_document_text() -> None:
    document = make_document()
    chunk = Chunk.build(
        document=document,
        content=document.text[7:11],
        position=0,
        start_char=7,
        end_char=11,
    )

    assert document.text[chunk.start_char : chunk.end_char] == chunk.content


def test_chunk_rejects_invalid_source_span() -> None:
    document = make_document()

    with pytest.raises(ValueError, match="source span"):
        Chunk.build(
            document=document,
            content="wrong",
            position=0,
            start_char=7,
            end_char=11,
        )


def test_metadata_is_shallow_read_only() -> None:
    document = Document.build(
        user_id="alice",
        namespace="notes",
        source="notes/example.md",
        text="body",
        metadata={"labels": ["rag"]},
    )

    with pytest.raises(TypeError):
        document.metadata["new"] = "value"

    # MappingProxyType only freezes the outer mapping; nested values are not copied.
    document.metadata["labels"].append("memory")
    assert document.metadata["labels"] == ["rag", "memory"]
