# -*- coding: utf-8 -*-
"""消息结构模块单元测试。

测试 Message Structure V1 的核心行为：
- 将 CompiledContext 转换为 ContextMessage 列表
- 每个 selected item 对应一条消息
- 保留 item_id、kind、source、content
- 保持 selected_items 顺序
- dropped_items 不出现
- 空列表返回空
- content 不被修改
"""

import pytest

from context.models import (
    ContextBudget,
    ContextItem,
    CompiledContext,
    ContextMessage,
)
from context.structure import structure_messages
from context.budget import calculate_available_input_tokens


class TestStructureBasic:
    """基本转换测试"""

    def test_compiled_context_converts_to_context_messages(self):
        """CompiledContext 能被转换为 ContextMessage 列表"""
        items = [
            ContextItem(
                item_id="task",
                kind="system",
                content="Task: write a function",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=20,
            ),
        ]
        budget = ContextBudget(soft_limit=100, hard_limit=100, output_reserve=20)

        # 先编译，再结构化为消息
        compiled = CompiledContext(
            selected_items=items,
            dropped_items=[],
            total_input_tokens=20,
            available_input_tokens=80,
        )

        messages = structure_messages(compiled)

        # 返回的是列表，且元素是 ContextMessage
        assert isinstance(messages, list)
        if messages:
            assert isinstance(messages[0], ContextMessage)

    def test_each_selected_item_produces_exactly_one_message(self):
        """每个 selected ContextItem 对应一条 ContextMessage"""
        items = [
            ContextItem(
                item_id="item_1",
                kind="system",
                content="Content 1",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=10,
            ),
            ContextItem(
                item_id="item_2",
                kind="user",
                content="Content 2",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=20,
            ),
            ContextItem(
                item_id="item_3",
                kind="retrieved",
                content="Content 3",
                source="rag",
                priority=50,
                required=False,
                token_count=30,
            ),
        ]
        budget = ContextBudget(soft_limit=100, hard_limit=100, output_reserve=20)

        compiled = CompiledContext(
            selected_items=items,
            dropped_items=[],
            total_input_tokens=60,
            available_input_tokens=80,
        )

        messages = structure_messages(compiled)

        assert len(messages) == 3

    def test_message_preserves_trace_fields_and_content(self):
        """ContextMessage 保留 item_id、kind、source、content"""
        item = ContextItem(
            item_id="test_id",
            kind="test_kind",
            content="This is test content",
            source="test_source",
            priority=100,
            required=True,
            token_count=10,
        )
        compiled = CompiledContext(
            selected_items=[item],
            dropped_items=[],
            total_input_tokens=10,
            available_input_tokens=80,
        )

        messages = structure_messages(compiled)
        assert len(messages) == 1

        msg = messages[0]
        assert msg.item_id == "test_id"
        assert msg.kind == "test_kind"
        assert msg.source == "test_source"
        assert msg.content == "This is test content"


class TestStructureOrder:
    """顺序保持测试"""

    def test_messages_keep_selected_items_order(self):
        """消息顺序保持 selected_items 顺序"""
        items = [
            ContextItem(
                item_id="first",
                kind="retrieval",
                content="First content",
                source="rag",
                priority=50,
                required=False,
                token_count=10,
            ),
            ContextItem(
                item_id="second",
                kind="system",
                content="Second content",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=10,
            ),
            ContextItem(
                item_id="third",
                kind="task",
                content="Third content",
                source="user",
                priority=100,
                required=True,
                token_count=10,
            ),
        ]
        compiled = CompiledContext(
            selected_items=items,
            dropped_items=[],
            total_input_tokens=30,
            available_input_tokens=80,
        )

        messages = structure_messages(compiled)
        message_ids = [msg.item_id for msg in messages]

        # 必须保持 retrieval → system → task 的顺序，不按 kind 重排
        assert message_ids == ["first", "second", "third"]


class TestStructureFiltering:
    """丢弃项过滤测试"""

    def test_dropped_items_do_not_appear_in_messages(self):
        """dropped_items 不出现在消息列表中"""
        selected = [
            ContextItem(
                item_id="selected",
                kind="system",
                content="Selected content",
                source="hardcoded",
                priority=100,
                required=True,
                token_count=20,
            ),
        ]
        dropped = [
            ContextItem(
                item_id="dropped",
                kind="retrieved",
                content="Dropped content",
                source="rag",
                priority=1,
                required=False,
                token_count=30,
            ),
        ]
        compiled = CompiledContext(
            selected_items=selected,
            dropped_items=dropped,
            total_input_tokens=20,
            available_input_tokens=80,
        )

        messages = structure_messages(compiled)
        message_ids = {msg.item_id for msg in messages}

        assert "selected" in message_ids
        assert "dropped" not in message_ids


class TestStructureEdgeCases:
    """边界情况测试"""

    def test_empty_selected_items_returns_empty_list(self):
        """selected_items 为空时返回空列表"""
        compiled = CompiledContext(
            selected_items=[],
            dropped_items=[],
            total_input_tokens=0,
            available_input_tokens=80,
        )

        messages = structure_messages(compiled)
        assert messages == []

    def test_content_is_not_modified_with_trace_prefixes(self):
        """content 必须保持原样，不能加入追踪前缀"""
        original_content = "This is the original content"
        item = ContextItem(
            item_id="test",
            kind="test_kind",
            content=original_content,
            source="test_source",
            priority=100,
            required=True,
            token_count=10,
        )
        compiled = CompiledContext(
            selected_items=[item],
            dropped_items=[],
            total_input_tokens=10,
            available_input_tokens=80,
        )

        messages = structure_messages(compiled)
        assert messages[0].content == original_content
        # 确保没有添加类似 "[test_kind][test_source]\n" 这样的前缀
        assert messages[0].content.startswith("This is the original content")
        assert messages[0].content == "This is the original content"

    def test_same_input_produces_same_output(self):
        """相同输入产生相同输出（确定性）"""
        item = ContextItem(
            item_id="test",
            kind="system",
            content="Content",
            source="hardcoded",
            priority=100,
            required=True,
            token_count=10,
        )
        compiled = CompiledContext(
            selected_items=[item],
            dropped_items=[],
            total_input_tokens=10,
            available_input_tokens=80,
        )

        result1 = structure_messages(compiled)
        result2 = structure_messages(compiled)

        assert len(result1) == len(result2)
        for m1, m2 in zip(result1, result2):
            assert m1.item_id == m2.item_id
            assert m1.kind == m2.kind
            assert m1.source == m2.source
            assert m1.content == m2.content