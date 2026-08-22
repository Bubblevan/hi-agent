# -*- coding: utf-8 -*-
"""OpenAI-Compatible Message Payload 模块。

将内部 FormattedMessage 投影为 Provider 可接受的纯消息字典。
"""

from typing import List

from context.models import FormattedMessage


def build_openai_payload(
    messages: List[FormattedMessage],
) -> List[dict[str, str]]:
    """将 FormattedMessage 列表转换为 OpenAI-compatible 消息字典。

    Args:
        messages: FormattedMessage 列表（已通过 role 校验）。

    Returns:
        OpenAI-compatible 消息字典列表，每个字典包含 role 和 content。
        输出顺序与输入顺序一致。
        不包含 item_id、source 等追踪字段。

    Example:
        >>> messages = [FormattedMessage(role="user", content="Hello", item_id="1", source="user")]
        >>> build_openai_payload(messages)
        [{"role": "user", "content": "Hello"}]
    """
    return [
        {
            "role": message.role,
            "content": message.content,
        }
        for message in messages
    ]