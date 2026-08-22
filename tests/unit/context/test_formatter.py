# -*- coding: utf-8 -*-
"""OpenAI-Compatible Formatter 单元测试。

测试 Formatter V1 的核心行为：
- kind → role 映射正确
- 顺序保持
- 追踪字段保留
- content 原样保留
- 不支持的 kind 拒绝
- 空输入返回空列表
- 确定性输出
"""

import pytest

from context.models import ContextMessage, FormattedMessage
from context.formatter import format_openai_messages


def make_message(
    *,
    item_id: str = "item-1",
    kind: str = "task",
    source: str = "user",
    content: str = "Complete the task.",
) -> ContextMessage:
    """创建测试用的 ContextMessage"""
    return ContextMessage(
        item_id=item_id,
        kind=kind,
        source=source,
        content=content,
    )


class TestFormatterKindMapping:
    """kind → role 映射测试"""

    @pytest.mark.parametrize(
        ("kind", "expected_role"),
        [
            ("system", "system"),
            ("task", "user"),
            ("user", "user"),
            ("assistant", "assistant"),
            ("retrieval", "user"),
        ],
    )
    def test_supported_kinds_map_to_openai_roles(self, kind, expected_role):
        """支持的 kind 正确映射到 OpenAI role"""
        formatted = format_openai_messages([make_message(kind=kind)])

        assert len(formatted) == 1
        assert formatted[0].role == expected_role

    def test_formatter_preserves_message_order(self):
        """消息顺序保持"""
        messages = [
            make_message(item_id="first", kind="system"),
            make_message(item_id="second", kind="task"),
            make_message(item_id="third", kind="retrieval"),
        ]

        formatted = format_openai_messages(messages)

        assert [msg.item_id for msg in formatted] == [
            "first",
            "second",
            "third",
        ]

    def test_formatter_preserves_trace_fields(self):
        """item_id 和 source 保持原样"""
        message = make_message(
            item_id="retrieval-1",
            kind="retrieval",
            source="rag",
            content="Evidence content",
        )

        formatted = format_openai_messages([message])

        assert formatted[0].item_id == "retrieval-1"
        assert formatted[0].source == "rag"

    def test_formatter_preserves_content_exactly(self):
        """content 必须保持原样，不能修改"""
        content = "Evidence:\n  keep whitespace exactly.\n"
        message = make_message(content=content)

        formatted = format_openai_messages([message])

        assert formatted[0].content == content
        # 确保没有添加前缀
        assert formatted[0].content.startswith("Evidence:")

    @pytest.mark.parametrize(
        "unsupported_kind",
        [
            "conversation",
            "tool_result",
            "retrieved",  # 注意：测试中用 'retrieval'，这里测试拼写错误
            "unknown",
            "invalid",
        ],
    )
    def test_unsupported_kinds_are_rejected(self, unsupported_kind):
        """不支持的 kind 必须抛出 ValueError"""
        message = make_message(kind=unsupported_kind)

        with pytest.raises(ValueError, match="unsupported"):
            format_openai_messages([message])

    def test_empty_messages_return_empty_list(self):
        """空输入返回空列表"""
        assert format_openai_messages([]) == []

    def test_same_input_produces_same_output(self):
        """相同输入产生相同输出（确定性）"""
        messages = [
            make_message(item_id="system", kind="system"),
            make_message(item_id="task", kind="task"),
        ]

        first = format_openai_messages(messages)
        second = format_openai_messages(messages)

        assert first == second

    def test_formatted_message_is_not_just_dict(self):
        """FormattedMessage 是结构化对象，不是裸 dict"""
        message = make_message(kind="system")
        formatted = format_openai_messages([message])

        assert isinstance(formatted[0], FormattedMessage)
        assert hasattr(formatted[0], "role")
        assert hasattr(formatted[0], "content")
        assert hasattr(formatted[0], "item_id")
        assert hasattr(formatted[0], "source")