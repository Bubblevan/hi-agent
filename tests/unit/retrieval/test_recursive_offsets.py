from retrieval.models import Document
from retrieval.splitters.base import SplitterParams
from retrieval.splitters.recursive import RecursiveSplitter


class CharacterCounter:
    def count(self, text: str) -> int:
        return len(text)


def make_document(text: str) -> Document:
    return Document.build(
        user_id="alice",
        namespace="notes",
        source="fixture.txt",
        text=text,
    )


def test_recursive_splitter_offsets_cover_original_text_without_overlap() -> None:
    text = "第一段。\n\nemoji🙂 and 中文\n最后一段。"
    splitter = RecursiveSplitter(
        SplitterParams(
            chunk_size=5,
            chunk_overlap=0,
            token_counter=CharacterCounter(),
        )
    )

    chunks = splitter.split(make_document(text))

    assert chunks
    assert "".join(chunk.content for chunk in chunks) == text
    assert [chunk.position for chunk in chunks] == list(range(len(chunks)))
    assert all(
        text[chunk.start_char : chunk.end_char] == chunk.content
        for chunk in chunks
    )
    assert all(
        left.end_char == right.start_char
        for left, right in zip(chunks, chunks[1:])
    )


def test_recursive_splitter_offsets_remain_ordered_with_overlap() -> None:
    text = "a b c d e f g h"
    splitter = RecursiveSplitter(
        SplitterParams(
            chunk_size=4,
            chunk_overlap=2,
            token_counter=CharacterCounter(),
        )
    )

    chunks = splitter.split(make_document(text))

    assert [chunk.start_char for chunk in chunks] == [0, 2, 4, 6, 8, 10, 12]
    assert [chunk.end_char for chunk in chunks] == [4, 6, 8, 10, 12, 14, 15]
    assert all(
        text[chunk.start_char : chunk.end_char] == chunk.content
        for chunk in chunks
    )


def test_recursive_splitter_returns_no_chunks_for_empty_document() -> None:
    assert RecursiveSplitter().split(make_document("")) == []
