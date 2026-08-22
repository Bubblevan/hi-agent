"""Validate, deduplicate, and triage generated grounded-RAG candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from evals.rag.scorer import normalize_text, validate_evidence_quotes
from evals.rag.schema import RAGEvalCase


@dataclass(frozen=True)
class ReviewItem:
    """One candidate that needs human review before freezing."""

    candidate_index: int
    candidate: Any
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ValidationReport:
    """Accepted cases and rejected/duplicate candidates."""

    accepted: tuple[RAGEvalCase, ...]
    review_queue: tuple[ReviewItem, ...]

    @property
    def duplicate_count(self) -> int:
        return sum(
            any(error.startswith("duplicate candidate") for error in item.errors)
            for item in self.review_queue
        )


def validate_case(
    case: RAGEvalCase,
    source_pages: list[str],
    *,
    source_id: str | None = None,
) -> list[str]:
    """Validate one schema-parsed case against the source pages."""

    errors: list[str] = []
    if source_id is not None and case.source_id != source_id:
        errors.append(
            f"{case.case_id}: source_id {case.source_id!r} does not match "
            f"expected {source_id!r}"
        )
    errors.extend(validate_evidence_quotes(case, source_pages))
    return errors


def _dedup_key(case: RAGEvalCase) -> tuple[Any, ...]:
    evidence = tuple(
        (item.page, normalize_text(item.quote).casefold())
        for item in case.gold_evidence
    )
    return (
        case.source_id,
        normalize_text(case.question).casefold(),
        evidence,
    )


def validate_candidates(
    candidates: list[Any],
    source_pages: list[str],
    *,
    source_id: str | None = None,
) -> ValidationReport:
    """Schema-validate candidates, check grounding, and deduplicate them.

    Invalid and duplicate candidates are retained in ``review_queue`` rather
    than silently discarded.  Only ``accepted`` is suitable for frozen JSONL.
    """

    accepted: list[RAGEvalCase] = []
    review_queue: list[ReviewItem] = []
    seen_keys: set[tuple[Any, ...]] = set()

    for candidate_index, raw in enumerate(candidates, start=1):
        try:
            case = (
                raw
                if isinstance(raw, RAGEvalCase)
                else RAGEvalCase.model_validate(raw)
            )
        except (ValidationError, TypeError, ValueError) as error:
            review_queue.append(
                ReviewItem(
                    candidate_index=candidate_index,
                    candidate=raw,
                    errors=(f"schema validation failed: {error}",),
                )
            )
            continue

        errors = validate_case(case, source_pages, source_id=source_id)
        if errors:
            review_queue.append(
                ReviewItem(
                    candidate_index=candidate_index,
                    candidate=case.model_dump(mode="json"),
                    errors=tuple(errors),
                )
            )
            continue

        key = _dedup_key(case)
        if key in seen_keys:
            review_queue.append(
                ReviewItem(
                    candidate_index=candidate_index,
                    candidate=case.model_dump(mode="json"),
                    errors=("duplicate candidate: same source, question, and evidence",),
                )
            )
            continue

        seen_keys.add(key)
        accepted.append(case)

    return ValidationReport(tuple(accepted), tuple(review_queue))


__all__ = [
    "ReviewItem",
    "ValidationReport",
    "validate_case",
    "validate_candidates",
]
