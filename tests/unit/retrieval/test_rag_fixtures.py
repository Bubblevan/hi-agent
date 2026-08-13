from pathlib import Path

import pytest
from dotenv import dotenv_values

from retrieval.datasets import load_rag_manifest, resolve_source_path, sha256_file
from retrieval.loaders.markitdown import MarkitdownLoader


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = PROJECT_ROOT / "tests" / "fixtures" / "rag_sources.json"


def test_rag_manifest_has_one_pdf_and_blog_sources() -> None:
    manifest = load_rag_manifest(MANIFEST_PATH)

    assert manifest["version"] == 1
    assert manifest["dataset_id"] == "hi-agent-rag-task-1"
    assert len(manifest["sources"]) == 6
    assert sum(source["kind"] == "pdf" for source in manifest["sources"]) == 1
    assert sum(source["kind"] == "markdown" for source in manifest["sources"]) == 5


def test_rag_fixture_paths_exist_and_match_manifest() -> None:
    manifest = load_rag_manifest(MANIFEST_PATH)

    for source in manifest["sources"]:
        path = resolve_source_path(source, project_root=PROJECT_ROOT)
        assert path.is_file(), f"fixture does not exist: {path}"
        assert path.stat().st_size == source["bytes"], source["id"]
        assert sha256_file(path) == source["sha256"]


def test_rag_manifest_has_stable_source_ids_and_namespaces() -> None:
    manifest = load_rag_manifest(MANIFEST_PATH)
    sources = manifest["sources"]

    ids = [source["id"] for source in sources]
    assert len(ids) == len(set(ids))
    assert all(source["user_id"] == "bubblevan" for source in sources)
    assert {source["namespace"] for source in sources} == {
        "hello-agents",
        "bubblevan-blog",
    }


def test_pdf_fixture_is_readable_by_markitdown_loader() -> None:
    manifest = load_rag_manifest(MANIFEST_PATH)
    source = next(item for item in manifest["sources"] if item["kind"] == "pdf")
    path = resolve_source_path(source, project_root=PROJECT_ROOT)

    document = MarkitdownLoader().load(
        path,
        user_id=source["user_id"],
        namespace=source["namespace"],
    )

    assert document.text.strip()
    assert len(document.text) > 1000
    assert document.metadata["source_format"] == ".pdf"
    assert document.metadata["converter"] == "markitdown"


def test_blog_fixtures_are_nonempty_utf8_markdown() -> None:
    manifest = load_rag_manifest(MANIFEST_PATH)
    blog_sources = [
        source for source in manifest["sources"] if source["kind"] == "markdown"
    ]

    for source in blog_sources:
        path = resolve_source_path(source, project_root=PROJECT_ROOT)
        text = path.read_text(encoding="utf-8")
        assert text.strip(), source["id"]
        assert path.suffix == ".md"


def test_local_env_declares_required_rag_settings_without_printing_values() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        pytest.skip("local .env is not part of the repository")

    values = dotenv_values(env_path)
    required = {
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_BASE_URL",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL_ID",
        "QDRANT_URL",
        "QDRANT_API_KEY",
    }

    assert required <= values.keys()
    assert all(values[name] for name in required)
