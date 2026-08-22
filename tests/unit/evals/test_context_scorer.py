"""Unit tests for deterministic Context Eval scoring."""

from evals.context.scorer import (
    compute_answer_scores,
    compute_selection_scores,
    score_case,
)


class TestSelectionScores:
    def test_exact_selection_and_exclusion(self):
        scores = compute_selection_scores(
            expected_selected_ids=["a", "b"],
            expected_dropped_ids=["c"],
            actual_selected_ids=["a", "b"],
            actual_dropped_ids=["c"],
        )

        assert scores["exact_match"] is True
        assert scores["must_select_recall"] == 1.0
        assert scores["distractor_exclusion"] == 1.0

    def test_missing_required_item_lowers_recall(self):
        scores = compute_selection_scores(
            expected_selected_ids=["a", "b", "c"],
            expected_dropped_ids=["d"],
            actual_selected_ids=["a", "c"],
            actual_dropped_ids=["b", "d"],
        )

        assert scores["exact_match"] is False
        assert scores["must_select_recall"] == 2 / 3
        assert scores["distractor_exclusion"] == 1.0

    def test_selected_distractor_lowers_exclusion(self):
        scores = compute_selection_scores(
            expected_selected_ids=["a", "b"],
            expected_dropped_ids=["c"],
            actual_selected_ids=["a", "b", "c"],
            actual_dropped_ids=[],
        )

        assert scores["exact_match"] is False
        assert scores["must_select_recall"] == 1.0
        assert scores["distractor_exclusion"] == 0.0

    def test_different_order_is_not_exact_match(self):
        scores = compute_selection_scores(
            expected_selected_ids=["a", "b"],
            expected_dropped_ids=["c"],
            actual_selected_ids=["b", "a"],
            actual_dropped_ids=["c"],
        )

        assert scores["exact_match"] is False
        assert scores["must_select_recall"] == 1.0


class TestAnswerScores:
    def test_required_terms_coverage(self):
        scores = compute_answer_scores(
            answer="This contains TERM1 only.",
            required_terms=["term1", "term2"],
            forbidden_terms=[],
        )

        assert scores["required_coverage"] == 0.5
        assert scores["forbidden_leakage"] is False

    def test_forbidden_term_is_detected(self):
        scores = compute_answer_scores(
            answer="This has BADWORD.",
            required_terms=[],
            forbidden_terms=["badword"],
        )

        assert scores["required_coverage"] == 1.0
        assert scores["forbidden_leakage"] is True

    def test_full_coverage_without_leakage(self):
        scores = compute_answer_scores(
            answer="TERM1 and term2 are present.",
            required_terms=["term1", "term2"],
            forbidden_terms=["bad"],
        )

        assert scores["required_coverage"] == 1.0
        assert scores["forbidden_leakage"] is False


class TestScoreCase:
    def test_perfect_case(self):
        case = {
            "expected": {
                "selected_item_ids": ["a", "b"],
                "dropped_item_ids": ["c"],
                "required_answer_terms": ["term"],
                "forbidden_answer_terms": ["bad"],
            }
        }

        scores = score_case(
            case=case,
            actual_selected=["a", "b"],
            actual_dropped=["c"],
            answer="This has term.",
            finish_reason="stop",
        )

        assert scores == {
            "exact_match": True,
            "must_select_recall": 1.0,
            "distractor_exclusion": 1.0,
            "required_coverage": 1.0,
            "forbidden_leakage": False,
            "truncation": False,
        }

    def test_length_finish_reason_marks_truncation(self):
        case = {
            "expected": {
                "selected_item_ids": [],
                "dropped_item_ids": [],
            }
        }

        scores = score_case(
            case=case,
            actual_selected=[],
            actual_dropped=[],
            answer="partial answer",
            finish_reason="length",
        )

        assert scores["truncation"] is True

    def test_same_input_produces_same_scores(self):
        case = {
            "expected": {
                "selected_item_ids": ["a"],
                "dropped_item_ids": ["b"],
                "required_answer_terms": ["answer"],
                "forbidden_answer_terms": ["wrong"],
            }
        }

        first = score_case(
            case,
            ["a"],
            ["b"],
            "answer",
            "stop",
        )
        second = score_case(
            case,
            ["a"],
            ["b"],
            "answer",
            "stop",
        )

        assert first == second