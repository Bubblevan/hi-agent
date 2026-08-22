# -*- coding: utf-8 -*-
"""OpenAI-Compatible Message Payload 单元测试。

测试 Payload V1 的核心行为：
- FormattedMessage → dict 转换
- 只包含 role 和 content
- item_id 和 source 不进入 payload
- 顺序保持
- content 原样保留
- 空输入返回空列表
- 确定性输出
"""

from context.models import FormattedMessage
from context.payload import build_openai_payload


def make_formatted_message(
    *,
    role: str = "user",
    content: str = "Complete the task.",
    item_id: str = "task-1",
    source: str = "user",
) -> FormattedMessage:
    """创建测试用的 FormattedMessage"""
    return FormattedMessage(
        role=role,
        content=content,
        item_id=item_id,
        source=source,
    )


class TestPayloadBasic:
    """基本转换测试"""

    def test_formatted_message_converts_to_provider_payload(self):
        """FormattedMessage 正确转换为 Provider payload 字典"""
        message = make_formatted_message(
            role="system",
            content="Follow the rules.",
        )

        payload = build_openai_payload([message])

        assert payload == [
            {
                "role": "system",
                "content": "Follow the rules.",
            }
        ]

    def test_payload_contains_only_role_and_content(self):
        """payload 字典只包含 role 和 content"""
        message = make_formatted_message(
            item_id="retrieval-1",
            source="rag",
        )

        payload = build_openai_payload([message])

        # 只包含 role 和 content，没有多余字段
        assert set(payload[0]) == {"role", "content"}


class TestPayloadPrivacy:
    """隐私边界测试（item_id/source 不进入 payload）"""

    def test_trace_fields_do_not_enter_payload(self):
        """item_id 和 source 不得进入 payload"""
        message = make_formatted_message(
            item_id="private-item-id",
            source="private-source",
            content="Some content",
        )

        payload = build_openai_payload([message])

        # 直接检查字段不存在
        assert "item_id" not in payload[0]
        assert "source" not in payload[0]

        # 确保追踪信息没有被拼接进 content
        assert "private-item-id" not in payload[0]["content"]
        assert "private-source" not in payload[0]["content"]

    def test_content_preserves_original_format(self):
        """content 保持原样，不做任何修改"""
        original_content = "Evidence:\n  keep whitespace exactly.\n"
        message = make_formatted_message(content=original_content)

        payload = build_openai_payload([message])

        assert payload[0]["content"] == original_content
        assert payload[0]["content"] == "Evidence:\n  keep whitespace exactly.\n"


class TestPayloadOrder:
    """顺序保持测试"""

    def test_payload_preserves_message_order(self):
        """payload 顺序与输入顺序一致"""
        messages = [
            make_formatted_message(
                role="system",
                content="system content",
                item_id="first",
            ),
            make_formatted_message(
                role="user",
                content="user content",
                item_id="second",
            ),
            make_formatted_message(
                role="assistant",
                content="assistant content",
                item_id="third",
            ),
        ]

        payload = build_openai_payload(messages)

        assert [item["content"] for item in payload] == [
            "system content",
            "user content",
            "assistant content",
        ]


class TestPayloadEdgeCases:
    """边界情况测试"""

    def test_empty_input_returns_empty_payload(self):
        """空输入返回空列表"""
        assert build_openai_payload([]) == []

    def test_same_input_produces_same_payload(self):
        """相同输入产生相同 payload（确定性）"""
        messages = [
            make_formatted_message(
                role="system",
                content="rules",
                item_id="system",
            ),
            make_formatted_message(
                role="user",
                content="task",
                item_id="task",
            ),
        ]

        first = build_openai_payload(messages)
        second = build_openai_payload(messages)

        assert first == second

    def test_multiple_messages_produce_multiple_payloads(self):
        """多个消息产生多个 payload 字典"""
        messages = [
            make_formatted_message(role="system", content="Rule 1"),
            make_formatted_message(role="system", content="Rule 2"),
            make_formatted_message(role="user", content="Task"),
        ]

        payload = build_openai_payload(messages)

        assert len(payload) == 3
        assert payload[0]["role"] == "system"
        assert payload[1]["role"] == "system"
        assert payload[2]["role"] == "user"