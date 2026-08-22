from core.embeddings.dashscope import DashScopeEmbedder


def test_dashscope_embedder_uses_official_default_model_name(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DASHSCOPE_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBED_MODEL_NAME", raising=False)

    embedder = DashScopeEmbedder(
        api_key="test-key",
        base_url="https://example.invalid/v1",
    )

    assert embedder.model == "qwen3.7-text-embedding"


def test_dashscope_embedder_allows_explicit_model_override(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_EMBEDDING_MODEL", "custom-embedding-model")

    embedder = DashScopeEmbedder(
        api_key="test-key",
        base_url="https://example.invalid/v1",
    )

    assert embedder.model == "custom-embedding-model"
