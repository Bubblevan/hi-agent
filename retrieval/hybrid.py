from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from retrieval.models import RetrievalResult


@dataclass
class _FusedCandidate:
    result: RetrievalResult
    score: float = 0.0
    first_seen: int = 0
    components: dict[str, float] = field(default_factory=dict)


def reciprocal_rank_fusion(
    result_sets: Mapping[str, Sequence[RetrievalResult]],
    *,
    k: int = 60,
    weights: Mapping[str, float] | None = None,
    limit: int | None = None,
) -> list[RetrievalResult]:
    """Fuse ranked retriever outputs without comparing their raw score scales.

    Each unique chunk contributes ``weight / (k + rank)`` once per retriever.
    Ranks are one-based; duplicate occurrences inside one retriever are ignored.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    if not isinstance(result_sets, Mapping):
        raise TypeError("result_sets must be a mapping of retriever names to results")

    configured_weights = dict(weights or {})
    for name, weight in configured_weights.items():
        if not isinstance(weight, (int, float)) or weight < 0:
            raise ValueError(f"weight for {name!r} must be non-negative")
    effective_weights = {
        name: float(configured_weights.get(name, 1.0))
        for name in result_sets
    }
    if not any(weight > 0 for weight in effective_weights.values()):
        raise ValueError("at least one retriever weight must be positive")

    candidates: dict[str, _FusedCandidate] = {}
    seen_order = 0
    for retriever_name, results in result_sets.items():
        if not isinstance(retriever_name, str) or not retriever_name.strip():
            raise ValueError("retriever names must be non-blank strings")
        if not isinstance(results, Sequence):
            raise TypeError(f"results for {retriever_name!r} must be a sequence")

        weight = effective_weights[retriever_name]
        seen_in_retriever: set[str] = set()
        for rank_index, result in enumerate(results, start=1):
            if not isinstance(result, RetrievalResult):
                raise TypeError("result sets must contain RetrievalResult objects")
            chunk_id = result.chunk.chunk_id
            if not isinstance(chunk_id, str) or not chunk_id:
                raise ValueError("every retrieval result must have a chunk_id")
            if chunk_id in seen_in_retriever:
                continue
            seen_in_retriever.add(chunk_id)
            if weight == 0:
                continue

            candidate = candidates.get(chunk_id)
            if candidate is None:
                candidate = _FusedCandidate(result=result, first_seen=seen_order)
                candidates[chunk_id] = candidate
                seen_order += 1

            contribution = weight / (k + rank_index)
            candidate.score += contribution
            candidate.components[f"{retriever_name}_rank"] = float(rank_index)
            candidate.components[f"{retriever_name}_score"] = float(result.score)

    ordered = sorted(
        candidates.values(),
        key=lambda candidate: (-candidate.score, candidate.first_seen),
    )
    if limit is not None:
        ordered = ordered[:limit]

    return [
        RetrievalResult.from_chunk(
            chunk=candidate.result.chunk,
            score=candidate.score,
            retriever="hybrid",
            score_components={**candidate.components, "rrf": candidate.score},
        )
        for candidate in ordered
    ]
