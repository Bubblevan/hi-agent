from evals.rag.scorer import (
    compute_answer_scores,
    score_case,
    validate_evidence_quotes,
)
from evals.rag.schema import RAGEvalCase


def make_case(**updates) -> RAGEvalCase:
    raw = {
        "case_id": "case",
        "suite": "test",
        "source_id": "source",
        "question": "What is the answer?",
        "answer_type": "fact",
        "difficulty": "easy",
        "answerable_from": "single_page",
        "expected_terms": ["term1", "term2"],
        "forbidden_terms": ["wrong"],
        "should_abstain": False,
        "gold_evidence": [{"page": 1, "quote": "term1 and term2"}],
    }
    raw.update(updates)
    return RAGEvalCase.model_validate(raw)


def test_evidence_quote_requires_exact_page_content() -> None:
    case = make_case()

    assert validate_evidence_quotes(case, ["term1 and term2 appear here"]) == []
    assert validate_evidence_quotes(case, ["term1 only"]) == [
        "case: evidence 1 quote is not present on page 1",
    ]


def test_evidence_page_must_exist() -> None:
    case = make_case(gold_evidence=[{"page": 2, "quote": "term1"}])

    assert validate_evidence_quotes(case, ["term1 and term2"]) == [
        "case: evidence 1 references page 2, but source has 1 pages",
        "case: evidence does not support expected terms: term1, term2",
    ]


def test_answer_scores_cover_terms_and_detect_leakage() -> None:
    scores = compute_answer_scores(
        "term1 is present but wrong is also present",
        ["term1", "term2"],
        ["wrong"],
    )

    assert scores["expected_term_coverage"] == 0.5
    assert scores["forbidden_term_leakage"] is True
    assert scores["answer_success"] is False


def test_abstention_is_scored_separately_from_positive_answer_coverage() -> None:
    raw = make_case(
        answer_type="abstention",
        answerable_from="not_answerable",
        expected_terms=[],
        forbidden_terms=[],
        should_abstain=True,
        gold_evidence=[],
    )

    scores = score_case(raw, "", answer_abstained=True)

    assert scores["abstention_correct"] is True
    assert scores["answer_success"] is True
    assert scores["grounded_answer_success"] is True
