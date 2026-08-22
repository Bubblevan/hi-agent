# -*- coding: utf-8 -*-
"""上下文 Eval 评分器。"""

from typing import List, Optional, Set


def compute_selection_scores(
    expected_ids: List[str],
    actual_selected: List[str],
    actual_dropped: List[str],
) -> dict:
    """计算选择相关的评分指标。"""
    expected_set = set(expected_ids)
    actual_selected_set = set(actual_selected)

    exact_match = (actual_selected == expected_ids)

    if expected_set:
        must_select_recall = len(expected_set & actual_selected_set) / len(expected_set)
    else:
        must_select_recall = 1.0

    # Distractor exclusion: 是否有不该选的被选入？
    extra_ids = actual_selected_set - expected_set
    if actual_selected:
        distractor_exclusion = 1.0 if len(extra_ids) == 0 else 0.0
    else:
        distractor_exclusion = 1.0

    return {
        "exact_match": exact_match,
        "must_select_recall": must_select_recall,
        "distractor_exclusion": distractor_exclusion,
    }


def compute_answer_scores(
    answer: str,
    required_terms: List[str],
    forbidden_terms: List[str],
) -> dict:
    """计算答案质量相关评分（关键词匹配）。"""
    answer_lower = answer.lower()

    if required_terms:
        required_hit = sum(1 for term in required_terms if term.lower() in answer_lower)
        required_coverage = required_hit / len(required_terms)
    else:
        required_coverage = 1.0

    forbidden_leakage = any(term.lower() in answer_lower for term in forbidden_terms)

    return {
        "required_coverage": required_coverage,
        "forbidden_leakage": forbidden_leakage,
    }


def score_case(
    case: dict,
    actual_selected: List[str],
    actual_dropped: List[str],
    answer: str,
    finish_reason: Optional[str],
) -> dict:
    """对单个 case 进行全面评分，返回所有指标。"""
    expected = case["expected"]
    expected_ids = expected["selected_item_ids"]
    required_terms = expected.get("required_answer_terms", [])
    forbidden_terms = expected.get("forbidden_answer_terms", [])

    selection_scores = compute_selection_scores(expected_ids, actual_selected, actual_dropped)
    answer_scores = compute_answer_scores(answer, required_terms, forbidden_terms)

    truncation = (finish_reason == "length")

    return {
        **selection_scores,
        **answer_scores,
        "truncation": truncation,
    }