from __future__ import annotations

import re
from collections.abc import Mapping

from retrieval.context_builder import ContextBuilder, ContextPrompt
from retrieval.generator import DeepSeekGenerator
from retrieval.hybrid import reciprocal_rank_fusion
from retrieval.indexes.qdrant import QdrantVectorStore
from retrieval.indexes.sqlite_fts import SQLiteFTSIndex
from retrieval.models import Document, RAGAnswer, RetrievalResult
from retrieval.splitters import get_splitter
from retrieval.splitters.base import SplitterParams


_CITATION_RE = re.compile(r"\[(\d+)\]")


def validate_answer_citations(
    answer: str,
    context: ContextPrompt,
    *,
    require_citation: bool = True,
) -> list[int]:
    """Validate that generated citation numbers refer to this prompt's sources."""
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("answer must be a non-blank string")
    cited_numbers = [int(value) for value in _CITATION_RE.findall(answer)]
    if any(number < 1 or number > len(context.selected_results) for number in cited_numbers):
        raise ValueError("answer contains a citation outside the context range")
    if require_citation and context.selected_results and not cited_numbers:
        raise ValueError("answer must cite at least one retrieved source")
    return cited_numbers


class RAGPipeline:
    """Index and answer flow shared by local tests and live evaluation."""

    def __init__(
        self,
        *,
        embedder,
        dense_store: QdrantVectorStore,
        lexical_index: SQLiteFTSIndex,
        generator: DeepSeekGenerator,
        context_builder: ContextBuilder | None = None,
        splitter_params: SplitterParams | None = None,
        rrf_k: int = 60,
        rrf_weights: Mapping[str, float] | None = None,
    ) -> None:
        self.embedder = embedder
        self.dense_store = dense_store
        self.lexical_index = lexical_index
        self.generator = generator
        self.context_builder = context_builder or ContextBuilder()
        self.splitter_params = splitter_params
        self.rrf_k = rrf_k
        self.rrf_weights = rrf_weights

    def ingest(self, document: Document) -> list:
        chunks = get_splitter(document, self.splitter_params).split(document)
        vectors = self.embedder.embed_documents([chunk.content for chunk in chunks])
        self.dense_store.upsert_chunks(document, chunks, vectors)
        self.lexical_index.replace_document(document, chunks)
        return chunks

    def retrieve(self, question: str, *, user_id: str, namespace: str, limit: int = 5) -> list[RetrievalResult]:
        query_vector = self.embedder.embed_queries([question])[0]
        dense = self.dense_store.search(
            query_vector,
            user_id=user_id,
            namespace=namespace,
            limit=limit,
        )
        bm25 = self.lexical_index.search(
            question,
            user_id=user_id,
            namespace=namespace,
            limit=limit,
        )
        return reciprocal_rank_fusion(
            {"dense": dense, "bm25": bm25},
            k=self.rrf_k,
            weights=self.rrf_weights,
            limit=limit,
        )

    def answer(
        self,
        question: str,
        *,
        user_id: str,
        namespace: str,
        limit: int = 5,
        require_citation: bool = True,
    ) -> RAGAnswer:
        results = self.retrieve(
            question,
            user_id=user_id,
            namespace=namespace,
            limit=limit,
        )
        context = self.context_builder.build(question, results)
        answer = self.generator.answer(question, context)
        validate_answer_citations(
            answer.answer,
            context,
            require_citation=require_citation,
        )
        return answer
