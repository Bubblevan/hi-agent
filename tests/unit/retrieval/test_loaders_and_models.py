from __future__ import annotations

import pytest

from retrieval.loaders.markdown import MarkdownLoader
from retrieval.loaders.text import TextLoader
from retrieval.models import Document


def test_text_loader_keeps_tenant_context_and_actual_encoding(tmp_path) -> None:
    path = tmp_path / "gb18030.txt"
    path.write_bytes("中文内容".encode("gb18030"))

    document = TextLoader().load(path, user_id="alice", namespace="notes")

    assert document.user_id == "alice"
    assert document.namespace == "notes"
    assert document.metadata["encoding"] == "gb18030"


def test_markdown_loader_keeps_invalid_frontmatter_in_body(tmp_path) -> None:
    path = tmp_path / "broken.md"
    raw = "---\ntitle: [broken\n---\n# Body\n"
    path.write_text(raw, encoding="utf-8")

    document = MarkdownLoader().load(path, user_id="alice", namespace="notes")

    assert document.text == raw


def test_document_metadata_cannot_be_mutated() -> None:
    document = Document.build(
        user_id="alice", namespace="notes", source="x", text="body", metadata={"x": 1}
    )

    with pytest.raises(TypeError):
        document.metadata["x"] = 2
