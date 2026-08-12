from __future__ import annotations

import pytest

from retrieval.models import Document
from retrieval.splitters.base import ApproxTokenCounter, SplitterParams
from retrieval.splitters.markdown import MarkdownSplitter
from retrieval.splitters.recursive import RecursiveSplitter


def make_document(text: str, *, loader: str = "text") -> Document:
    return Document.build(
        user_id="alice",
        namespace="notes",
        source="fixture.txt",
        text=text,
        metadata={"loader": loader},
    )


def test_approx_counter_does_not_double_count_pure_cjk() -> None:
    counter = ApproxTokenCounter()

    assert counter.count("你好世界") == 4
    assert counter.count("你好 world!") == 5
    assert counter.count("") == 0


def test_splitter_params_reject_invalid_budgets() -> None:
    with pytest.raises(ValueError):
        SplitterParams(chunk_size=0)
    with pytest.raises(ValueError):
        SplitterParams(chunk_size=10, chunk_overlap=10)


def test_recursive_splitter_preserves_text_offsets_and_budget() -> None:
    text = "第一段。第二段！\n\nhello_world_without_spaces and tail."
    counter = ApproxTokenCounter()
    splitter = RecursiveSplitter(
        SplitterParams(chunk_size=6, chunk_overlap=2, token_counter=counter)
    )

    chunks = splitter.split(make_document(text))

    assert len(chunks) > 1
    assert all(counter.count(chunk.content) <= 6 for chunk in chunks)
    assert all(text[chunk.start_char : chunk.end_char] == chunk.content for chunk in chunks)
    assert [chunk.position for chunk in chunks] == list(range(len(chunks)))


def test_markdown_heading_parser_ignores_hashes_inside_fences() -> None:
    text = """# Top

intro

```python
# not a heading
print('ok')
```

## Child

details
"""
    splitter = MarkdownSplitter(SplitterParams(chunk_size=100, chunk_overlap=0))

    paragraphs = splitter._split_paragraphs_with_headings(text)

    code = next(p for p in paragraphs if "not a heading" in p["content"])
    details = next(p for p in paragraphs if p["content"] == "details")
    assert code["heading_path"] == "Top"
    assert details["heading_path"] == "Top > Child"


def test_markdown_oversized_paragraph_respects_budget() -> None:
    counter = ApproxTokenCounter()
    text = "# Long\n\n" + "这是很长的一段中文" * 8
    splitter = MarkdownSplitter(
        SplitterParams(chunk_size=10, chunk_overlap=2, token_counter=counter)
    )

    chunks = splitter.split(make_document(text, loader="markdown"))

    assert len(chunks) > 1
    assert all(counter.count(chunk.content) <= 10 for chunk in chunks)
    assert all(chunk.heading_path == "Long" for chunk in chunks)
