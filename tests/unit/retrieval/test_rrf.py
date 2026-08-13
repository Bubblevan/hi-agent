from __future__ import annotations

import pytest

from retrieval.hybrid import reciprocal_rank_fusion
from retrieval.models import Chunk, Document, RetrievalResult


def make_results(names: list[str], *, retriever: str) -> list[RetrievalResult]:
    document = Document.build(
        user_id="alice",
        namespace="notes",
        source="notes.md",
        text="\n".join(names),
    )
    results = []
    cursor = 0
    for position, name in enumerate(names):
        chunk = Chunk.build(
            document=document,
            content=name,
            position=position,
            start_char=cursor,
            end_char=cursor + len(name),
        )
        results.append(
            RetrievalResult.from_chunk(
                chunk=chunk,
                score=float(position + 1) / 10,
                retriever=retriever,
                score_components={retriever: float(position + 1) / 10},
            )
        )
        cursor += len(name) + 1
    return results


def test_rrf_combines_ranks_and_deduplicates_by_chunk_id() -> None:
    dense = make_results(["alpha", "beta"], retriever="dense")
    bm25 = make_results(["beta", "gamma"], retriever="bm25")

    # The test fixtures use different document IDs, so make beta share the
    # dense chunk identity before fusing the two independent result lists.
    bm25[0] = RetrievalResult.from_chunk(
        chunk=dense[1].chunk,
        score=bm25[0].score,
        retriever="bm25",
        score_components={"bm25": bm25[0].score},
    )

    fused = reciprocal_rank_fusion({"dense": dense, "bm25": bm25}, k=1)

    assert [result.chunk.content for result in fused] == ["beta", "alpha", "gamma"]
    assert fused[0].retriever == "hybrid"
    assert fused[0].score == pytest.approx(5 / 6)
    assert fused[0].score_components["dense_rank"] == 2
    assert fused[0].score_components["bm25_rank"] == 1
    assert fused[0].score_components["rrf"] == pytest.approx(5 / 6)


def test_duplicate_inside_one_retriever_does_not_inflate_rrf() -> None:
    dense = make_results(["alpha", "beta"], retriever="dense")
    duplicate = RetrievalResult.from_chunk(
        chunk=dense[0].chunk,
        score=999.0,
        retriever="dense",
        score_components={"dense": 999.0},
    )

    fused = reciprocal_rank_fusion({"dense": [dense[0], duplicate, dense[1]]}, k=1)

    assert [result.chunk.content for result in fused] == ["alpha", "beta"]
    assert fused[0].score == pytest.approx(0.5)


def test_weights_can_prefer_one_retriever_and_limit_results() -> None:
    dense = make_results(["alpha", "beta"], retriever="dense")
    bm25 = make_results(["beta", "alpha"], retriever="bm25")
    bm25[1] = RetrievalResult.from_chunk(
        chunk=dense[0].chunk,
        score=bm25[1].score,
        retriever="bm25",
        score_components={"bm25": bm25[1].score},
    )
    bm25[0] = RetrievalResult.from_chunk(
        chunk=dense[1].chunk,
        score=bm25[0].score,
        retriever="bm25",
        score_components={"bm25": bm25[0].score},
    )

    fused = reciprocal_rank_fusion(
        {"dense": dense, "bm25": bm25},
        k=60,
        weights={"dense": 3.0, "bm25": 0.5},
        limit=1,
    )

    assert len(fused) == 1
    assert fused[0].chunk.content == "alpha"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"k": 0}, "k"),
        ({"weights": {"dense": -1}}, "weight"),
        ({"limit": 0}, "limit"),
    ],
)
def test_rrf_rejects_invalid_configuration(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        reciprocal_rank_fusion({"dense": []}, **kwargs)
