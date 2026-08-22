"""Deterministic scorers and evidence checks for grounded RAG evals."""

from __future__ import annotations

from collections.abc import Sequence

from evals.rag.schema import RAGEvalCase


ScoreValue = bool | float
ScoreDict = dict[str, ScoreValue]


def normalize_text(text: str) -> str:
    """Normalize line wrapping from PDF extraction without changing words."""

    return " ".join(text.split())


def _coverage(expected_terms: Sequence[str], text: str) -> float:
    if not expected_terms:
        return 1.0
    normalized = text.casefold()
    hits = sum(term.casefold() in normalized for term in expected_terms)
    return hits / len(expected_terms)


def validate_evidence_quotes(
    case: RAGEvalCase,
    pages: Sequence[str],
) -> list[str]:
    """Return provenance errors for a case against extracted source pages."""

    if case.should_abstain:
        return []

    errors: list[str] = []
    evidence_text: list[str] = []
    for index, evidence in enumerate(case.gold_evidence, start=1):
        if evidence.page > len(pages):
            errors.append(
                f"{case.case_id}: evidence {index} references page "
                f"{evidence.page}, but source has {len(pages)} pages"
            )
            continue

        page_text = normalize_text(pages[evidence.page - 1])
        quote = normalize_text(evidence.quote)
        if quote not in page_text:
            errors.append(
                f"{case.case_id}: evidence {index} quote is not present on "
                f"page {evidence.page}"
            )
        evidence_text.append(quote)

    evidence_text_joined = " ".join(evidence_text)
    missing_terms = [
        term
        for term in case.expected_terms
        if term.casefold() not in evidence_text_joined.casefold()
    ]
    if missing_terms:
        errors.append(
            f"{case.case_id}: evidence does not support expected terms: "
            + ", ".join(missing_terms)
        )
    return errors


def compute_answer_scores(
    answer: str,
    expected_terms: Sequence[str],
    forbidden_terms: Sequence[str] = (),
    *,
    should_abstain: bool = False,
    answer_abstained: bool | None = None,
) -> ScoreDict:
    """Score answer-term coverage, leakage, and abstention behavior."""

    abstained = not answer.strip() if answer_abstained is None else answer_abstained
    expected_term_coverage = _coverage(expected_terms, answer)
    forbidden_term_leakage = any(
        term.casefold() in answer.casefold() for term in forbidden_terms
    )
    abstention_correct = abstained == should_abstain
    answer_success = (
        abstention_correct
        and not forbidden_term_leakage
        and (should_abstain or expected_term_coverage == 1.0)
    )
    return {
        "expected_term_coverage": expected_term_coverage,
        "forbidden_term_leakage": forbidden_term_leakage,
        "abstention_correct": abstention_correct,
        "answer_success": answer_success,
    }


def score_case(
    case: RAGEvalCase,
    answer: str,
    *,
    evidence_errors: Sequence[str] = (),
    citation_valid: bool = True,
    answer_abstained: bool | None = None,
) -> ScoreDict:
    """Score one answer and attach deterministic grounding metadata."""

    answer_scores = compute_answer_scores(
        answer,
        case.expected_terms,
        case.forbidden_terms,
        should_abstain=case.should_abstain,
        answer_abstained=answer_abstained,
    )
    return {
        **answer_scores,
        "evidence_valid": not evidence_errors,
        "citation_valid": citation_valid,
        "grounded_answer_success": bool(
            answer_scores["answer_success"]
            and not evidence_errors
            and citation_valid
        ),
    }


__all__ = [
    "ScoreDict",
    "compute_answer_scores",
    "normalize_text",
    "score_case",
    "validate_evidence_quotes",
]
