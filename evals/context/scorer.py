"""Deterministic scorers for Context Eval V1."""

from typing import Any


ScoreDict = dict[str, bool | float]


def _coverage(
    expected_ids: list[str],
    actual_ids: list[str],
) -> float:
    """Return the fraction of expected IDs found in actual IDs."""
    expected = set(expected_ids)

    if not expected:
        return 1.0

    actual = set(actual_ids)
    return len(expected & actual) / len(expected)


def compute_selection_scores(
    expected_selected_ids: list[str],
    expected_dropped_ids: list[str],
    actual_selected_ids: list[str],
    actual_dropped_ids: list[str],
) -> ScoreDict:
    """Score Context selection and exclusion behavior."""

    exact_match = (
        actual_selected_ids == expected_selected_ids
        and actual_dropped_ids == expected_dropped_ids
    )

    must_select_recall = _coverage(
        expected_selected_ids,
        actual_selected_ids,
    )

    distractor_exclusion = _coverage(
        expected_dropped_ids,
        actual_dropped_ids,
    )

    return {
        "exact_match": exact_match,
        "must_select_recall": must_select_recall,
        "distractor_exclusion": distractor_exclusion,
    }


def compute_answer_scores(
    answer: str,
    required_terms: list[str],
    forbidden_terms: list[str],
) -> ScoreDict:
    """Score required fact coverage and forbidden fact leakage."""

    normalized_answer = answer.casefold()

    if required_terms:
        required_hits = sum(
            term.casefold() in normalized_answer
            for term in required_terms
        )
        required_coverage = (
            required_hits / len(required_terms)
        )
    else:
        required_coverage = 1.0

    forbidden_leakage = any(
        term.casefold() in normalized_answer
        for term in forbidden_terms
    )

    return {
        "required_coverage": required_coverage,
        "forbidden_leakage": forbidden_leakage,
    }


def score_case(
    case: dict[str, Any],
    actual_selected: list[str],
    actual_dropped: list[str],
    answer: str,
    finish_reason: str | None,
) -> ScoreDict:
    """Score one complete Context Eval case."""

    expected = case["expected"]

    selection_scores = compute_selection_scores(
        expected_selected_ids=expected.get(
            "selected_item_ids",
            [],
        ),
        expected_dropped_ids=expected.get(
            "dropped_item_ids",
            [],
        ),
        actual_selected_ids=actual_selected,
        actual_dropped_ids=actual_dropped,
    )

    answer_scores = compute_answer_scores(
        answer=answer,
        required_terms=expected.get(
            "required_answer_terms",
            [],
        ),
        forbidden_terms=expected.get(
            "forbidden_answer_terms",
            [],
        ),
    )

    return {
        **selection_scores,
        **answer_scores,
        "truncation": finish_reason == "length",
    }