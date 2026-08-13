from retrieval.models import Document
from retrieval.splitters.base import SplitterParams
from retrieval.splitters.markdown import MarkdownSplitter


def make_document(text: str) -> Document:
    return Document.build(
        user_id="alice",
        namespace="notes",
        source="fixture.md",
        text=text,
        metadata={"loader": "markdown"},
    )


def test_markdown_chunks_keep_exact_source_span_when_merging_sections() -> None:
    text = "# Top\n\nintro paragraph\n\n## Child\n\ndetails\n"
    splitter = MarkdownSplitter(SplitterParams(chunk_size=100, chunk_overlap=0))

    chunks = splitter.split(make_document(text))

    assert len(chunks) == 1
    assert chunks[0].content == text[chunks[0].start_char : chunks[0].end_char]
    assert "## Child" in chunks[0].content
    assert "details" in chunks[0].content
    assert chunks[0].heading_path == "Top > Child"


def test_markdown_heading_allows_commonmark_indentation() -> None:
    text = "   ## Indented\n\nbody\n"
    splitter = MarkdownSplitter(SplitterParams(chunk_size=100, chunk_overlap=0))

    paragraphs = splitter._split_paragraphs_with_headings(text)

    assert paragraphs[0]["heading_path"] == "Indented"
    assert paragraphs[0]["content"] == "body"


def test_markdown_tilde_fence_protects_hash_lines() -> None:
    text = "# Top\n\n~~~python\n## not a heading\n~~~\n\nbody\n"
    splitter = MarkdownSplitter(SplitterParams(chunk_size=100, chunk_overlap=0))

    paragraphs = splitter._split_paragraphs_with_headings(text)

    code = next(p for p in paragraphs if "not a heading" in p["content"])
    body = next(p for p in paragraphs if p["content"] == "body")
    assert code["heading_path"] == "Top"
    assert body["heading_path"] == "Top"


def test_markdown_table_content_is_not_dropped() -> None:
    text = (
        "# Table\n\n"
        "| Name | Value |\n"
        "| --- | --- |\n"
        "| chunk_size | 800 |\n"
    )
    splitter = MarkdownSplitter(SplitterParams(chunk_size=100, chunk_overlap=0))

    chunks = splitter.split(make_document(text))

    assert len(chunks) == 1
    assert "| chunk_size | 800 |" in chunks[0].content
    assert chunks[0].content == text[chunks[0].start_char : chunks[0].end_char]
