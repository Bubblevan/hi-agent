from __future__ import annotations

from types import SimpleNamespace

import pytest

from retrieval.context_builder import ContextBuilder
from retrieval.generator import DeepSeekGenerator, NO_CONTEXT_ANSWER
from retrieval.models import Chunk, Document, RetrievalResult
from retrieval.pipeline import validate_answer_citations
from retrieval.pipeline import RAGPipeline
from retrieval.indexes.qdrant import QdrantVectorStore
from retrieval.indexes.sqlite_fts import SQLiteFTSIndex


def make_results(*contents: str) -> list[RetrievalResult]:
    text = "\n".join(contents)
    document = Document.build(
        user_id="alice",
        namespace="notes",
        source="notes.md",
        text=text,
    )
    results = []
    cursor = 0
    for position, content in enumerate(contents):
        chunk = Chunk.build(
            document=document,
            content=content,
            position=position,
            start_char=cursor,
            end_char=cursor + len(content),
            heading_path=f"# Section {position + 1}",
        )
        results.append(
            RetrievalResult.from_chunk(
                chunk=chunk,
                score=1.0 / (position + 1),
                retriever="hybrid",
                score_components={"rrf": 1.0 / (position + 1)},
            )
        )
        cursor += len(content) + 1
    return results


def test_context_builder_numbers_sources_and_returns_citations() -> None:
    results = make_results("first fact", "second fact")
    context = ContextBuilder(max_chars=1000).build("what facts?", results)

    assert context.question == "what facts?"
    assert context.citations == [results[0].chunk.chunk_id, results[1].chunk.chunk_id]
    assert "[1] notes.md" in context.text
    assert "[2] notes.md" in context.text
    assert "first fact" in context.text
    assert context.messages[1]["role"] == "user"
    assert "[1]" in context.messages[1]["content"]


def test_context_builder_deduplicates_chunks_and_respects_whole_chunk_budget() -> None:
    results = make_results("first", "second", "third")
    duplicate = RetrievalResult.from_chunk(
        chunk=results[0].chunk,
        score=999,
        retriever="dense",
        score_components={"dense": 999},
    )

    context = ContextBuilder(max_chars=80).build(
        "question",
        [results[0], duplicate, results[1], results[2]],
    )

    assert context.citations == [results[0].chunk.chunk_id, results[1].chunk.chunk_id]
    assert "third" not in context.text
    assert context.selected_results == [results[0], results[1]]


def test_context_builder_rejects_empty_question_and_budget() -> None:
    result = make_results("fact")
    with pytest.raises(ValueError, match="question"):
        ContextBuilder(max_chars=100).build(" ", result)
    with pytest.raises(ValueError, match="max_chars"):
        ContextBuilder(max_chars=0)


def test_generator_abstains_without_context_without_calling_llm() -> None:
    fake = FakeClient("should not be used")
    generator = DeepSeekGenerator(client=fake)

    answer = generator.answer("unknown", ContextBuilder(max_chars=100).build("unknown", []))

    assert answer.answer == NO_CONTEXT_ANSWER
    assert answer.contexts == []
    assert answer.citations == []
    assert fake.calls == []


def test_generator_calls_deepseek_compatible_client_and_preserves_citations() -> None:
    fake = FakeClient("依据资料回答 [1]。")
    generator = DeepSeekGenerator(client=fake, model="deepseek-test")
    results = make_results("the answer")
    context = ContextBuilder(max_chars=1000).build("what?", results)

    answer = generator.answer("what?", context)

    assert answer.answer == "依据资料回答 [1]。"
    assert answer.citations == [results[0].chunk.chunk_id]
    assert answer.metadata["model"] == "deepseek-test"
    assert fake.calls[0]["model"] == "deepseek-test"
    assert fake.calls[0]["messages"][0]["role"] == "system"
    assert "只使用给定资料" in fake.calls[0]["messages"][0]["content"]


def test_generator_rejects_blank_model_output() -> None:
    generator = DeepSeekGenerator(client=FakeClient("   "))
    context = ContextBuilder(max_chars=100).build("what?", make_results("fact"))

    with pytest.raises(RuntimeError, match="empty"):
        generator.answer("what?", context)


def test_citation_validator_rejects_unknown_source_numbers() -> None:
    context = ContextBuilder(max_chars=100).build("what?", make_results("fact"))

    assert validate_answer_citations("答案见 [1]。", context) == [1]
    with pytest.raises(ValueError, match="outside"):
        validate_answer_citations("答案见 [2]。", context)
    with pytest.raises(ValueError, match="at least one"):
        validate_answer_citations("没有编号。", context)


def test_local_pipeline_runs_ingest_retrieve_context_and_generation(tmp_path) -> None:
    class FakeEmbedder:
        dimension = 3

        def embed_documents(self, texts):
            return [[1.0, 0.0, 0.0] for _ in texts]

        def embed_queries(self, texts):
            return [[1.0, 0.0, 0.0] for _ in texts]

    class FakeGenerator:
        def answer(self, question, context):
            return __import__("retrieval.models", fromlist=["RAGAnswer"]).RAGAnswer(
                answer="资料见 [1]。",
                contexts=context.selected_results,
                citations=context.citations,
            )

    from qdrant_client import QdrantClient
    from retrieval.loaders.markdown import MarkdownLoader

    source = tmp_path / "note.md"
    source.write_text("---\ntitle: Test\n---\n\n# Retrieval\n\nRAG uses evidence.", encoding="utf-8")
    document = MarkdownLoader().load(source, user_id="alice", namespace="notes")
    pipeline = RAGPipeline(
        embedder=FakeEmbedder(),
        dense_store=QdrantVectorStore(
            client=QdrantClient(":memory:"),
            collection_name="pipeline-test",
            dimension=3,
        ),
        lexical_index=SQLiteFTSIndex(tmp_path / "fts.sqlite3"),
        generator=FakeGenerator(),
        context_builder=ContextBuilder(max_chars=1000),
    )

    chunks = pipeline.ingest(document)
    answer = pipeline.answer("What does RAG use?", user_id="alice", namespace="notes")

    assert chunks
    assert answer.answer == "资料见 [1]。"
    assert answer.citations


class FakeClient:
    def __init__(self, content: str):
        self.content = content
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )
