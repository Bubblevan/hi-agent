# -*- coding: utf-8 -*-
"""单元测试 - 上下文 Eval 评分器（Red 阶段）。"""

import pytest

# 注意：此时 evals.context.scorer 尚未实现，导入会失败。
# 先写测试，运行会提示 ImportError，这是预期的 Red。
from eval.context.scorer import compute_selection_scores, compute_answer_scores, score_case


class TestSelectionScores:
    def test_exact_match(self):
        expected = ["a", "b", "c"]
        actual_selected = ["a", "b", "c"]
        actual_dropped = []
        scores = compute_selection_scores(expected, actual_selected, actual_dropped)
        assert scores["exact_match"] is True
        assert scores["must_select_recall"] == 1.0
        assert scores["distractor_exclusion"] == 1.0

    def test_missing_required(self):
        expected = ["a", "b", "c"]
        actual_selected = ["a", "c"]
        actual_dropped = ["b"]
        scores = compute_selection_scores(expected, actual_selected, actual_dropped)
        assert scores["exact_match"] is False
        assert scores["must_select_recall"] == 2/3
        assert scores["distractor_exclusion"] == 1.0

    def test_extra_distractor(self):
        expected = ["a", "b"]
        actual_selected = ["a", "b", "c"]
        actual_dropped = ["c"]
        scores = compute_selection_scores(expected, actual_selected, actual_dropped)
        assert scores["exact_match"] is False
        assert scores["must_select_recall"] == 1.0
        assert scores["distractor_exclusion"] == 0.0


class TestAnswerScores:
    def test_required_terms_coverage(self):
        required = ["term1", "term2"]
        answer = "This contains term1 only."
        scores = compute_answer_scores(answer, required, [])
        assert scores["required_coverage"] == 0.5
        assert scores["forbidden_leakage"] is False

    def test_forbidden_leakage(self):
        forbidden = ["badword"]
        answer = "This has badword."
        scores = compute_answer_scores(answer, [], forbidden)
        assert scores["forbidden_leakage"] is True

    def test_full_coverage_no_forbidden(self):
        required = ["term1", "term2"]
        forbidden = ["bad"]
        answer = "term1 and term2 are present."
        scores = compute_answer_scores(answer, required, forbidden)
        assert scores["required_coverage"] == 1.0
        assert scores["forbidden_leakage"] is False


class TestScoreCase:
    def test_perfect_case(self):
        case = {
            "expected": {
                "selected_item_ids": ["a", "b"],
                "required_answer_terms": ["term"],
                "forbidden_answer_terms": ["bad"]
            }
        }
        actual_selected = ["a", "b"]
        actual_dropped = []
        answer = "This has term."
        finish_reason = None
        scores = score_case(case, actual_selected, actual_dropped, answer, finish_reason)
        assert scores["exact_match"] is True
        assert scores["must_select_recall"] == 1.0
        assert scores["distractor_exclusion"] == 1.0
        assert scores["required_coverage"] == 1.0
        assert scores["forbidden_leakage"] is False
        assert scores["truncation"] is False

    def test_truncation(self):
        case = {"expected": {"selected_item_ids": []}}
        scores = score_case(case, [], [], "answer", "length")
        assert scores["truncation"] is True