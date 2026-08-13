from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv

from retrieval.context_builder import ContextBuilder
from retrieval.datasets import load_rag_manifest, resolve_source_path
from retrieval.generator import DeepSeekGenerator
from retrieval.indexes.qdrant import QdrantVectorStore
from retrieval.indexes.sqlite_fts import SQLiteFTSIndex
from retrieval.loaders.markdown import MarkdownLoader
from retrieval.loaders.markitdown import MarkitdownLoader
from retrieval.pipeline import RAGPipeline, validate_answer_citations
from retrieval.splitters.base import SplitterParams


PROJECT_ROOT = Path(__file__).parents[2]
MANIFEST_PATH = PROJECT_ROOT / "tests" / "fixtures" / "rag_sources.json"


def _live_enabled() -> bool:
    return os.getenv("RUN_RAG_INTEGRATION") == "1"


def test_live_rag_pdf_and_blog_end_to_end(tmp_path, capsys) -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    if not _live_enabled():
        pytest.skip("set RUN_RAG_INTEGRATION=1 to call DashScope, Qdrant and DeepSeek")

    required = [
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_BASE_URL",
        "QDRANT_URL",
        "QDRANT_API_KEY",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL_ID",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.fail(f"live RAG test is missing environment keys: {', '.join(missing)}")

    from core.embeddings.dashscope import DashScopeEmbedder

    manifest = load_rag_manifest(MANIFEST_PATH)
    pdf_source = next(item for item in manifest["sources"] if item["kind"] == "pdf")
    blog_source = next(item for item in manifest["sources"] if item["id"] == "blog-vibe-coding")
    collection_name = f"hi_agent_rag_live_{uuid.uuid4().hex[:12]}"
    store = None
    report: list[dict[str, object]] = []

    try:
        embedder = DashScopeEmbedder(batch_size=32, max_retries=2)
        store = QdrantVectorStore(
            url=os.environ["QDRANT_URL"],
            api_key=os.environ["QDRANT_API_KEY"],
            collection_name=collection_name,
            dimension=embedder.dimension,
        )
        lexical = SQLiteFTSIndex(tmp_path / "live.sqlite3")
        generator = DeepSeekGenerator(max_tokens=3000, temperature=0.1)
        pipeline = RAGPipeline(
            embedder=embedder,
            dense_store=store,
            lexical_index=lexical,
            generator=generator,
            context_builder=ContextBuilder(max_chars=6000, max_chunks=6),
            splitter_params=SplitterParams(chunk_size=500, chunk_overlap=80),
            rrf_weights={"dense": 1.0, "bm25": 1.0},
        )

        documents = []
        for source in (pdf_source, blog_source):
            path = resolve_source_path(source, project_root=PROJECT_ROOT)
            loader = MarkitdownLoader() if source["kind"] == "pdf" else MarkdownLoader()
            document = loader.load(
                path,
                user_id=source["user_id"],
                namespace=source["namespace"],
            )
            chunks = pipeline.ingest(document)
            documents.append((source, document, chunks))

        cases = [
            {
                "case_id": "pdf-yolov8-bfds",
                "source_id": pdf_source["id"],
                "question": "What three optimizations does YOLOv8-BFDS integrate?",
                "expected_terms": ["DCNv2", "E-SEModule", "Concat_BiFPN"],
            },
            {
                "case_id": "blog-vibe-coding-layers",
                "source_id": blog_source["id"],
                "question": "Vibe Coding 的方法论先行部分列出了哪五个层？",
                "expected_terms": [
                    "规范前置层",
                    "需求设计层",
                    "任务拆解层",
                    "编码迭代层",
                    "质量校验层",
                ],
            },
        ]

        for case in cases:
            source = next(item for item in (pdf_source, blog_source) if item["id"] == case["source_id"])
            answer = pipeline.answer(
                case["question"],
                user_id=source["user_id"],
                namespace=source["namespace"],
                limit=10 if case["source_id"] == blog_source["id"] else 6,
            )
            context_results = answer.contexts
            cited_numbers = validate_answer_citations(
                answer.answer,
                pipeline.context_builder.build(case["question"], context_results),
            )
            retrieved_text = "\n".join(result.chunk.content for result in context_results)
            report.append(
                {
                    "case_id": case["case_id"],
                    "retrieved_chunks": len(context_results),
                    "retrieval_hit": all(term in retrieved_text for term in case["expected_terms"]),
                    "answer_covers_expected_terms": all(
                        term in answer.answer for term in case["expected_terms"]
                    ),
                    "citation_valid": bool(cited_numbers),
                    "citation_count": len(cited_numbers),
                    "answer": answer.answer,
                }
            )

        print(json.dumps(report, ensure_ascii=False))
        assert all(item["retrieval_hit"] for item in report), report
        assert all(item["citation_valid"] for item in report), report
        assert all(item["answer_covers_expected_terms"] for item in report), report
    finally:
        if store is not None:
            try:
                store.client.delete_collection(collection_name)
            except Exception:
                # Cleanup must not hide the actual integration failure.
                pass
