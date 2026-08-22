# -*- coding: utf-8 -*-
"""上下文预算模块单元测试。

测试预算计算的核心行为：
- 可用输入 token 数 = 硬上限 - 输出预留
- required 项总量在预算内时通过
- required 项超预算时抛出 BudgetExceededError
"""

import pytest

from context.models import ContextBudget, ContextItem
from context.budget import (
    calculate_available_input_tokens,
    is_within_budget,
    assert_within_budget,
    BudgetExceededError,
)


class TestBudgetCalculation:
    """预算计算核心行为测试"""

    def test_available_input_tokens_excludes_output_reserve(self):
        """输出预留确实从硬上限扣除"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=20)
        available = calculate_available_input_tokens(budget)
        assert available == 80

    def test_available_input_tokens_with_zero_output_reserve(self):
        """output_reserve 为 0 时可用的输入 token 等于硬上限"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=0)
        available = calculate_available_input_tokens(budget)
        assert available == 100

    # 注意：output_reserve 必须小于 hard_limit 是 models.py 层面的约束，
    # 非法组合不会进入计算逻辑，因此无需测试负数情形。


class TestBudgetAcceptance:
    """required 项预算检查测试"""

    def test_required_items_within_available_budget_are_accepted(self):
        """required 项总量未超预算时正常通过"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="system_prompt",
                kind="system",
                content="System prompt here",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=30,
            ),
            ContextItem(
                item_id="user_query",
                kind="user",
                content="User question",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=40,
            ),
        ]

        assert_within_budget(items, budget)
        assert is_within_budget(items, budget) is True

    def test_required_items_exactly_at_budget_limit(self):
        """required 项总量恰好等于可用预算时正常通过"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="system_prompt",
                kind="system",
                content="System prompt here",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=80,
            ),
        ]

        assert_within_budget(items, budget)
        assert is_within_budget(items, budget) is True

    def test_required_items_exceeding_available_budget_raise_error(self):
        """required 项超预算时必须显式报错，不能静默删除"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="system_prompt",
                kind="system",
                content="System prompt here",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=50,
            ),
            ContextItem(
                item_id="user_query",
                kind="user",
                content="User question",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=40,
            ),
        ]

        with pytest.raises(BudgetExceededError) as exc_info:
            assert_within_budget(items, budget)

        assert "90" in str(exc_info.value)
        assert is_within_budget(items, budget) is False

    def test_optional_items_are_not_counted_in_required_budget_check(self):
        """预算检查只统计 required=True 的项，optional 项不触发超预算错误"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="system_prompt",
                kind="system",
                content="System prompt",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=80,
            ),
            ContextItem(
                item_id="extra_context",
                kind="retrieved",
                content="Extra content",
                source="rag",
                priority=50,
                required=False,
                token_count=100,
            ),
        ]

        # 即使 total tokens (180) 超了，required tokens (80) 没超，不应报错
        assert_within_budget(items, budget)
        assert is_within_budget(items, budget) is True


class TestBudgetEdgeCases:
    """边界情况测试"""

    def test_empty_items_list(self):
        """空列表应始终通过预算检查"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=20)
        assert_within_budget([], budget)
        assert is_within_budget([], budget) is True

    def test_items_with_zero_tokens(self):
        """token_count=0 的项不应影响预算计算"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="empty",
                kind="empty",
                content="[empty content]",   # 修正：不能为空字符串
                source="hardcoded",
                priority=0,
                required=True,
                token_count=0,
            ),
        ]

        assert_within_budget(items, budget)
        assert is_within_budget(items, budget) is True

    def test_mixed_required_and_optional_exceeding_budget(self):
        """混合 required 和 optional 时，只有 required 超预算才报错"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="system",
                kind="system",
                content="System",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=60,
            ),
            ContextItem(
                item_id="query",
                kind="user",
                content="Query",
                source="hardcoded",
                priority=100,
                required=False,
                token_count=30,
            ),
            ContextItem(
                item_id="history",
                kind="history",
                content="History",
                source="store",
                priority=50,
                required=False,
                token_count=30,
            ),
        ]

        # required=60 <= 80，通过
        assert_within_budget(items, budget)
        assert is_within_budget(items, budget) is True

    def test_required_items_exceeding_budget_raises_with_correct_context(self):
        """超预算异常应携带足够的上下文信息"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="a",
                kind="system",
                content="A",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=60,
            ),
            ContextItem(
                item_id="b",
                kind="user",
                content="B",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=30,
            ),
        ]

        with pytest.raises(BudgetExceededError) as exc_info:
            assert_within_budget(items, budget)

        error = exc_info.value
        assert error.required_tokens == 90
        assert error.available == 80
        assert len(error.items) == 2
        assert error.items[0].item_id == "a"
        assert error.items[1].item_id == "b"