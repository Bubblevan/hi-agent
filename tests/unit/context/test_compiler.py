# -*- coding: utf-8 -*-
"""上下文编译器模块单元测试。

测试 Compiler V1 的核心行为：
- 返回 CompiledContext 结构
- required 项保留在 selected_items 中
- 被丢弃的 optional 项记录在 dropped_items 中
- 正确计算 token 统计
- 传递 Selector 的异常
- 输出确定性
"""

import pytest

from context.models import ContextBudget, ContextItem, CompiledContext
from context.compiler import compile_context
from context.budget import BudgetExceededError


class TestCompilerStructure:
    """Compiler 输出结构测试"""

    def test_compiler_returns_compiled_context(self):
        """Compiler 返回 CompiledContext 结构，而非普通 list"""
        budget = ContextBudget(soft_limit=100, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="task",
                kind="system",
                content="Task description",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=20,
            ),
        ]

        result = compile_context(items, budget)

        # 返回的是 CompiledContext，不是 list
        assert hasattr(result, "selected_items")
        assert hasattr(result, "dropped_items")
        assert hasattr(result, "total_input_tokens")
        assert hasattr(result, "available_input_tokens")

        # 类型检查（如果 CompiledContext 是 dataclass）
        assert isinstance(result, CompiledContext)


class TestCompilerRequired:
    """required 项保留测试"""

    def test_required_item_retained_in_selected_items(self):
        """Compiler 将 required 项保留在 selected_items 中"""
        budget = ContextBudget(soft_limit=100, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required",
                kind="system",
                content="Required content",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=20,
            ),
            ContextItem(
                item_id="optional",
                kind="retrieved",
                content="Optional content",
                source="rag",
                priority=50,
                required=False,
                token_count=10,
            ),
        ]

        result = compile_context(items, budget)
        selected_ids = {item.item_id for item in result.selected_items}

        assert "required" in selected_ids

    def test_multiple_required_items_all_retained(self):
        """多个 required 项全部保留"""
        budget = ContextBudget(soft_limit=100, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required_1",
                kind="system",
                content="Required 1",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=10,
            ),
            ContextItem(
                item_id="required_2",
                kind="user",
                content="Required 2",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=20,
            ),
            ContextItem(
                item_id="optional",
                kind="retrieved",
                content="Optional",
                source="rag",
                priority=50,
                required=False,
                token_count=10,
            ),
        ]

        result = compile_context(items, budget)
        selected_ids = {item.item_id for item in result.selected_items}

        assert "required_1" in selected_ids
        assert "required_2" in selected_ids


class TestCompilerDropped:
    """被丢弃项记录测试"""

    def test_dropped_optional_item_is_recorded(self):
        """被丢弃的 optional 项记录在 dropped_items 中"""
        budget = ContextBudget(soft_limit=50, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required",
                kind="system",
                content="Required",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=30,
            ),
            ContextItem(
                item_id="optional_selected",
                kind="retrieved",
                content="Selected optional",
                source="rag",
                priority=100,
                required=False,
                token_count=20,
            ),
            ContextItem(
                item_id="optional_dropped",
                kind="retrieved",
                content="Dropped optional",
                source="rag",
                priority=1,
                required=False,
                token_count=20,
            ),
        ]

        result = compile_context(items, budget)
        selected_ids = {item.item_id for item in result.selected_items}
        dropped_ids = {item.item_id for item in result.dropped_items}

        # required + optional_selected = 50 <= soft_limit
        assert "required" in selected_ids
        assert "optional_selected" in selected_ids
        # optional_dropped 被丢弃
        assert "optional_dropped" in dropped_ids

    def test_selected_and_dropped_have_no_overlap(self):
        """selected_items 和 dropped_items 没有交集"""
        budget = ContextBudget(soft_limit=50, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required",
                kind="system",
                content="Required",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=30,
            ),
            ContextItem(
                item_id="optional_selected",
                kind="retrieved",
                content="Selected",
                source="rag",
                priority=100,
                required=False,
                token_count=20,
            ),
            ContextItem(
                item_id="optional_dropped",
                kind="retrieved",
                content="Dropped",
                source="rag",
                priority=1,
                required=False,
                token_count=20,
            ),
        ]

        result = compile_context(items, budget)
        selected_ids = {item.item_id for item in result.selected_items}
        dropped_ids = {item.item_id for item in result.dropped_items}

        assert selected_ids.isdisjoint(dropped_ids)

    def test_all_items_either_selected_or_dropped(self):
        """所有输入项要么在 selected_items，要么在 dropped_items"""
        budget = ContextBudget(soft_limit=50, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required",
                kind="system",
                content="Required",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=30,
            ),
            ContextItem(
                item_id="optional_selected",
                kind="retrieved",
                content="Selected",
                source="rag",
                priority=100,
                required=False,
                token_count=20,
            ),
            ContextItem(
                item_id="optional_dropped",
                kind="retrieved",
                content="Dropped",
                source="rag",
                priority=1,
                required=False,
                token_count=20,
            ),
        ]

        result = compile_context(items, budget)

        all_input_ids = {item.item_id for item in items}
        all_output_ids = (
            {item.item_id for item in result.selected_items}
            | {item.item_id for item in result.dropped_items}
        )

        assert all_input_ids == all_output_ids


class TestCompilerTokenCalculation:
    """token 统计计算测试"""

    def test_total_input_tokens_equals_selected_items_tokens(self):
        """total_input_tokens 等于 selected_items 的 token_count 总和"""
        budget = ContextBudget(soft_limit=100, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required",
                kind="system",
                content="Required",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=20,
            ),
            ContextItem(
                item_id="optional",
                kind="retrieved",
                content="Optional",
                source="rag",
                priority=50,
                required=False,
                token_count=30,
            ),
        ]

        result = compile_context(items, budget)
        expected_total = sum(item.token_count for item in result.selected_items)

        assert result.total_input_tokens == expected_total
        assert result.total_input_tokens == 50

    def test_total_input_tokens_with_only_required(self):
        """只有 required 项时的 token 计算"""
        budget = ContextBudget(soft_limit=100, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required",
                kind="system",
                content="Required",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=50,
            ),
        ]

        result = compile_context(items, budget)
        assert result.total_input_tokens == 50

    def test_available_input_tokens_is_correct(self):
        """available_input_tokens 等于 hard_limit - output_reserve"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required",
                kind="system",
                content="Required",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=20,
            ),
        ]

        result = compile_context(items, budget)
        assert result.available_input_tokens == 80


class TestCompilerExceptionPropagation:
    """异常传递测试"""

    def test_compiler_propagates_budget_exceeded_error(self):
        """required 项超预算时，Compiler 抛出 BudgetExceededError"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required_1",
                kind="system",
                content="Required 1",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=50,
            ),
            ContextItem(
                item_id="required_2",
                kind="user",
                content="Required 2",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=40,
            ),
        ]

        # required_tokens = 90 > available_input = 80
        with pytest.raises(BudgetExceededError) as exc_info:
            compile_context(items, budget)

        assert "90" in str(exc_info.value)
        assert "80" in str(exc_info.value)

    def test_compiler_propagates_duplicate_item_id_error(self):
        """重复 item_id 时，Compiler 抛出 ValueError"""
        budget = ContextBudget(soft_limit=100, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="duplicate",
                kind="system",
                content="First",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=10,
            ),
            ContextItem(
                item_id="duplicate",
                kind="user",
                content="Second",
                source="hardcoded",
                priority=100,
                required=False,
                token_count=10,
            ),
        ]

        with pytest.raises(ValueError, match="duplicate.*item_id"):
            compile_context(items, budget)


class TestCompilerDeterminism:
    """确定性测试"""

    def test_same_input_produces_same_output(self):
        """相同输入两次编译得到相同结果"""
        budget = ContextBudget(soft_limit=50, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required",
                kind="system",
                content="Required",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=30,
            ),
            ContextItem(
                item_id="optional_high",
                kind="retrieved",
                content="High priority",
                source="rag",
                priority=100,
                required=False,
                token_count=20,
            ),
            ContextItem(
                item_id="optional_low",
                kind="retrieved",
                content="Low priority",
                source="rag",
                priority=1,
                required=False,
                token_count=20,
            ),
        ]

        result1 = compile_context(items, budget)
        result2 = compile_context(items, budget)

        # selected_items 顺序相同
        assert [item.item_id for item in result1.selected_items] == \
               [item.item_id for item in result2.selected_items]

        # dropped_items 顺序相同
        assert [item.item_id for item in result1.dropped_items] == \
               [item.item_id for item in result2.dropped_items]

        # token 统计相同
        assert result1.total_input_tokens == result2.total_input_tokens
        assert result1.available_input_tokens == result2.available_input_tokens

    def test_dropped_items_keep_input_order(self):
        """dropped_items 保持输入顺序"""
        # 降低 soft_limit，让两个 optional 都放不下
        budget = ContextBudget(soft_limit=40, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required",
                kind="system",
                content="Required",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=30,
            ),
            ContextItem(
                item_id="optional_first",
                kind="retrieved",
                content="First optional",
                source="rag",
                priority=1,
                required=False,
                token_count=20,
            ),
            ContextItem(
                item_id="optional_second",
                kind="retrieved",
                content="Second optional",
                source="rag",
                priority=1,
                required=False,
                token_count=20,
            ),
        ]

        result = compile_context(items, budget)
        dropped_ids = [item.item_id for item in result.dropped_items]

        # 两个 optional 都放不下（30+20=50 > 40），应在 dropped_items 中按输入顺序排列
        assert dropped_ids == ["optional_first", "optional_second"]