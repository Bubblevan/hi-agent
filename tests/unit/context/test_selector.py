# -*- coding: utf-8 -*-
"""上下文选择器模块单元测试。

测试 Selector V1 的核心行为：
- required 项全部保留
- optional 按 priority 从高到低选择
- priority 相同时保持输入顺序
- 重复 item_id 被拒绝
- 超大的高优先级项目不阻塞后续小项目
"""

import pytest

from context.models import ContextBudget, ContextItem
from context.selector import select_items


class TestSelectorRequired:
    """required 项行为测试"""

    def test_required_items_are_always_retained(self):
        """required 项无论 priority 高低，全部保留"""
        budget = ContextBudget(soft_limit=50, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required_low",
                kind="system",
                content="Low priority required",
                source="hardcoded",
                priority=1,
                required=True,
                token_count=10,
            ),
            ContextItem(
                item_id="required_high",
                kind="system",
                content="High priority required",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=10,
            ),
            ContextItem(
                item_id="optional_high",
                kind="retrieved",
                content="High priority optional",
                source="rag",
                priority=100,
                required=False,
                token_count=10,
            ),
        ]

        result = select_items(items, budget)
        result_ids = {item.item_id for item in result}

        # required 项必须全部存在
        assert "required_low" in result_ids
        assert "required_high" in result_ids
        # optional 不一定存在，但 required 必须都在

    def test_required_items_within_soft_limit_no_optional_filtering(self):
        """required 总量在 soft_limit 内时，optional 正常按 priority 选择"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required_1",
                kind="system",
                content="Required 1",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=30,
            ),
            ContextItem(
                item_id="required_2",
                kind="user",
                content="Required 2",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=30,
            ),
            ContextItem(
                item_id="optional_high",
                kind="retrieved",
                content="High priority optional",
                source="rag",
                priority=100,
                required=False,
                token_count=10,
            ),
            ContextItem(
                item_id="optional_low",
                kind="retrieved",
                content="Low priority optional",
                source="rag",
                priority=1,
                required=False,
                token_count=10,
            ),
        ]

        result = select_items(items, budget)
        result_ids = {item.item_id for item in result}

        # required 必须都在
        assert "required_1" in result_ids
        assert "required_2" in result_ids

        # optional_high 应该被选中（priority 高）
        assert "optional_high" in result_ids

        # optional_low 也应该被选中（因为总 token = 80，正好等于 soft_limit）
        assert "optional_low" in result_ids

    def test_required_items_exceed_soft_limit_but_within_hard_limit(self):
        """required 超过 soft_limit 但未超 hard_limit 时，optional 全部丢弃"""
        budget = ContextBudget(soft_limit=50, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="required_big",
                kind="system",
                content="Big required",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=60,
            ),
            ContextItem(
                item_id="optional_high",
                kind="retrieved",
                content="High priority optional",
                source="rag",
                priority=100,
                required=False,
                token_count=10,
            ),
        ]

        result = select_items(items, budget)
        result_ids = {item.item_id for item in result}

        # required 必须保留
        assert "required_big" in result_ids
        # optional 应该被丢弃（因为 required=60 > soft_limit=50）
        assert "optional_high" not in result_ids


class TestSelectorPriority:
    """priority 选择行为测试"""

    def test_higher_priority_optional_item_is_selected_first(self):
        """高 priority 的 optional 优先于低 priority 被选择"""
        budget = ContextBudget(soft_limit=50, hard_limit=100, output_reserve=20)

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
                item_id="optional_high",
                kind="retrieved",
                content="High priority",
                source="rag",
                priority=100,
                required=False,
                token_count=30,
            ),
            ContextItem(
                item_id="optional_low",
                kind="retrieved",
                content="Low priority",
                source="rag",
                priority=1,
                required=False,
                token_count=30,
            ),
        ]

        result = select_items(items, budget)
        result_ids = {item.item_id for item in result}

        # required 20 + optional_high 30 = 50 <= soft_limit
        assert "required" in result_ids
        assert "optional_high" in result_ids
        # optional_low 放不下
        assert "optional_low" not in result_ids

    def test_lower_priority_optional_item_is_dropped_when_budget_insufficient(self):
        """预算不足时低 priority 被丢弃"""
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

        result = select_items(items, budget)
        result_ids = {item.item_id for item in result}

        # required 30 + optional_high 20 = 50 <= soft_limit
        assert "required" in result_ids
        assert "optional_high" in result_ids
        assert "optional_low" not in result_ids

    def test_equal_priority_items_keep_input_order(self):
        """priority 相同时保持输入顺序（预算足够时全部入选）"""
        budget = ContextBudget(soft_limit=100, hard_limit=150, output_reserve=20)

        items = [
            ContextItem(
                item_id="required",
                kind="system",
                content="Required",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=10,
            ),
            ContextItem(
                item_id="optional_first",
                kind="retrieved",
                content="First optional",
                source="rag",
                priority=50,
                required=False,
                token_count=20,
            ),
            ContextItem(
                item_id="optional_second",
                kind="retrieved",
                content="Second optional",
                source="rag",
                priority=50,
                required=False,
                token_count=20,
            ),
            ContextItem(
                item_id="optional_third",
                kind="retrieved",
                content="Third optional",
                source="rag",
                priority=50,
                required=False,
                token_count=20,
            ),
        ]

        result = select_items(items, budget)
        result_ids = [item.item_id for item in result]

        # 所有项都应该入选（budget 足够）
        assert len(result_ids) == 4
        # 顺序必须保持原样
        assert result_ids == ["required", "optional_first", "optional_second", "optional_third"]

    def test_equal_priority_budget_competition_picks_earlier_item(self):
        """【新增】相同 priority 时，预算只够一个，选择输入顺序靠前的那个"""
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
                item_id="optional_first",
                kind="retrieved",
                content="First optional (same priority)",
                source="rag",
                priority=50,
                required=False,
                token_count=20,
            ),
            ContextItem(
                item_id="optional_second",
                kind="retrieved",
                content="Second optional (same priority)",
                source="rag",
                priority=50,
                required=False,
                token_count=20,
            ),
        ]

        result = select_items(items, budget)
        result_ids = {item.item_id for item in result}

        # required 30 + optional_first 20 = 50 <= soft_limit
        # 预算只够放一个 optional，应该选择输入顺序靠前的 optional_first
        assert "required" in result_ids
        assert "optional_first" in result_ids
        assert "optional_second" not in result_ids

    def test_oversized_high_priority_item_does_not_block_smaller_item(self):
        """超大的高 priority optional 不应阻塞后续较小的项目"""
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
                item_id="optional_big",
                kind="retrieved",
                content="Big optional",
                source="rag",
                priority=100,
                required=False,
                token_count=30,  # 30 + 30 = 60 > 50，放不下
            ),
            ContextItem(
                item_id="optional_small",
                kind="retrieved",
                content="Small optional",
                source="rag",
                priority=50,
                required=False,
                token_count=20,  # 30 + 20 = 50 <= 50，能放下
            ),
        ]

        result = select_items(items, budget)
        result_ids = {item.item_id for item in result}

        assert "required" in result_ids
        # big 放不下被跳过
        assert "optional_big" not in result_ids
        # small 虽然 priority 低，但因为 big 放不下，small 被选中
        assert "optional_small" in result_ids


class TestSelectorValidation:
    """输入验证测试"""

    def test_duplicate_item_ids_are_rejected(self):
        """重复 item_id 必须显式报错"""
        budget = ContextBudget(soft_limit=50, hard_limit=100, output_reserve=20)

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
                required=True,
                token_count=10,
            ),
        ]

        with pytest.raises(ValueError, match="duplicate.*item_id"):
            select_items(items, budget)

    def test_output_reserve_is_not_used_by_optional_items(self):
        """output_reserve 不供 optional 使用，只影响硬边界"""
        budget = ContextBudget(soft_limit=80, hard_limit=100, output_reserve=50)

        items = [
            ContextItem(
                item_id="required",
                kind="system",
                content="Required",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=40,
            ),
            ContextItem(
                item_id="optional",
                kind="retrieved",
                content="Optional",
                source="rag",
                priority=100,
                required=False,
                token_count=50,
            ),
        ]

        # available_input = 100 - 50 = 50
        # selection_target = min(80, 50) = 50
        # required=40 <= 50，不报错
        # 但 optional 50 放不下（40+50=90 > 50）
        result = select_items(items, budget)
        result_ids = {item.item_id for item in result}

        assert "required" in result_ids
        assert "optional" not in result_ids


class TestSelectorOrderPreservation:
    """最终顺序保持测试"""

    def test_final_result_keeps_original_input_order(self):
        """【加固】最终返回结果保持原始输入顺序，不按 priority 重排"""
        budget = ContextBudget(soft_limit=100, hard_limit=150, output_reserve=20)

        items = [
            ContextItem(
                item_id="first",
                kind="system",
                content="First",
                source="hardcoded",
                priority=1,
                required=True,
                token_count=10,
            ),
            ContextItem(
                item_id="second",
                kind="user",
                content="Second",
                source="hardcoded",
                priority=100,
                required=False,
                token_count=10,
            ),
            ContextItem(
                item_id="third",
                kind="retrieved",
                content="Third",
                source="rag",
                priority=50,
                required=False,
                token_count=10,
            ),
        ]

        result = select_items(items, budget)
        result_ids = [item.item_id for item in result]

        # 所有项都应该入选（budget 足够）
        # 顺序必须保持原样
        assert result_ids == ["first", "second", "third"]

    def test_selection_order_separate_from_output_order(self):
        """【新增】验证选择顺序（按 priority）与输出顺序（按输入）被正确分离"""
        budget = ContextBudget(soft_limit=50, hard_limit=100, output_reserve=20)

        items = [
            ContextItem(
                item_id="first_in_input",
                kind="system",
                content="First in input, low priority",
                source="hardcoded",
                priority=1,
                required=True,
                token_count=10,
            ),
            ContextItem(
                item_id="second_in_input",
                kind="retrieved",
                content="Second in input, high priority",
                source="rag",
                priority=100,
                required=False,
                token_count=30,
            ),
            ContextItem(
                item_id="third_in_input",
                kind="retrieved",
                content="Third in input, medium priority",
                source="rag",
                priority=50,
                required=False,
                token_count=20,
            ),
        ]

        result = select_items(items, budget)
        result_ids = [item.item_id for item in result]

        # required=10，可选预算 = 50 - 10 = 40
        # 高 priority 的 second (30) 被选中，medium 的 third (20) 放不下
        # 但输出顺序必须保持输入顺序
        assert result_ids == ["first_in_input", "second_in_input"]
        # third_in_input 未被选中
        assert "third_in_input" not in [item.item_id for item in result]