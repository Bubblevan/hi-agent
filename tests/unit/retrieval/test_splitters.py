from __future__ import annotations

import pytest

from retrieval.models import Document
from retrieval.splitters import get_splitter
from retrieval.splitters.base import (
    ApproxTokenCounter,
    SplitterParams,
    TokenizerTokenCounter,
)
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


class FakeTokenizer:
    def encode(self, text: str, *, add_special_tokens: bool = False) -> list[int]:
        tokens = [index for index, _ in enumerate(text.split(), start=1)]
        if add_special_tokens:
            return [101, *tokens, 102]
        return tokens


def test_tokenizer_counter_uses_target_tokenizer() -> None:
    counter = TokenizerTokenCounter(FakeTokenizer())

    assert counter.count("hello world") == 2
    assert counter.count("hello_world_without_spaces") == 1


def test_tokenizer_counter_can_include_special_tokens() -> None:
    counter = TokenizerTokenCounter(FakeTokenizer(), add_special_tokens=True)

    assert counter.count("hello world") == 4


def test_splitter_params_rejects_object_without_count_method() -> None:
    with pytest.raises(TypeError, match="token_counter"):
        SplitterParams(token_counter=object())


def test_splitter_factory_accepts_target_token_counter() -> None:
    text = "one two three four"
    counter = TokenizerTokenCounter(FakeTokenizer())
    document = make_document(text)

    splitter = get_splitter(
        document,
        params=SplitterParams(chunk_size=2, chunk_overlap=0, token_counter=counter),
    )
    chunks = splitter.split(document)

    assert len(chunks) == 2
    assert all(counter.count(chunk.content) <= 2 for chunk in chunks)


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
