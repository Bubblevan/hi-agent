from pathlib import Path

import pytest

from retrieval.loaders.markdown import MarkdownLoader
from retrieval.loaders.markitdown import MarkitdownLoader
from retrieval.loaders.text import TextLoader


@pytest.mark.parametrize("loader", [TextLoader(), MarkdownLoader(), MarkitdownLoader()])
@pytest.mark.parametrize("field", ["user_id", "namespace"])
def test_loader_rejects_blank_tenant_context(
    loader, field: str, tmp_path: Path
) -> None:
    path = tmp_path / "note.md"
    path.write_text("# Note\n\nbody\n", encoding="utf-8")
    context = {"user_id": "alice", "namespace": "notes"}
    context[field] = "   "

    with pytest.raises(ValueError, match=field):
        loader.load(path, **context)


def test_text_loader_rejects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.touch()

    with pytest.raises(ValueError, match="文件为空"):
        TextLoader().load(path, user_id="alice", namespace="notes")


def test_text_loader_reports_decode_failure(tmp_path: Path) -> None:
    path = tmp_path / "invalid.txt"
    path.write_bytes(b"\xff\xfe\xfa\xfb")

    with pytest.raises(UnicodeDecodeError):
        TextLoader().load(path, user_id="alice", namespace="notes")


def test_markdown_loader_extracts_frontmatter_and_keeps_body(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text(
        "---\n"
        "title: Loader notes\n"
        "tags: [rag, loader]\n"
        "custom: value\n"
        "---\n"
        "# Body\n\ncontent\n",
        encoding="utf-8",
    )

    document = MarkdownLoader().load(path, user_id="alice", namespace="notes")

    assert document.text == "# Body\n\ncontent\n"
    assert document.metadata["title"] == "Loader notes"
    assert document.metadata["tags"] == ["rag", "loader"]
    assert document.metadata["raw_frontmatter"]["custom"] == "value"
    assert document.metadata["encoding"] == "utf-8"


def test_markitdown_loader_delegates_markdown_metadata(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("---\ntitle: Delegated\n---\n# Body\n", encoding="utf-8")

    document = MarkitdownLoader().load(path, user_id="alice", namespace="notes")

    assert document.metadata["loader"] == "markdown"
    assert document.metadata["title"] == "Delegated"
    assert document.text == "# Body\n"


def test_markitdown_loader_wraps_code_with_language_fence(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    document = MarkitdownLoader().load(path, user_id="alice", namespace="code")

    assert document.text.startswith("```py\n")
    assert document.text.endswith("\n```")
    assert "return a + b" in document.text
    assert document.metadata["source_format"] == ".py"
    assert document.metadata["converter"] == "code-block"


def test_markitdown_loader_rejects_audio_with_explicit_boundary(tmp_path: Path) -> None:
    path = tmp_path / "voice.mp3"
    path.write_bytes(b"not-a-real-audio-file")

    with pytest.raises(ValueError, match="音频文件暂不支持"):
        MarkitdownLoader().load(path, user_id="alice", namespace="audio")
