# -*- coding: utf-8 -*-
"""OpenAI-Compatible Formatter 模块。

将 provider-neutral 的 ContextMessage 转换为 OpenAI-compatible 格式。
"""

from typing import List

from context.models import ContextMessage, FormattedMessage

# 支持的 kind → OpenAI role 映射
KIND_TO_ROLE = {
    "system": "system",
    "task": "user",
    "user": "user",
    "assistant": "assistant",
    "retrieval": "user",
}


def format_openai_messages(
    messages: List[ContextMessage],
) -> List[FormattedMessage]:
    """将 ContextMessage 列表转换为 OpenAI-compatible 格式。

    Args:
        messages: provider-neutral 的 ContextMessage 列表。

    Returns:
        FormattedMessage 列表，包含 role、content 和追踪字段。

    Raises:
        ValueError: 当遇到不支持的 kind 时。
    """
    result: List[FormattedMessage] = []

    for msg in messages:
        # 1. 检查是否支持该 kind
        if msg.kind not in KIND_TO_ROLE:
            raise ValueError(
                f"unsupported kind: {msg.kind}. "
                f"Supported kinds: {', '.join(KIND_TO_ROLE.keys())}"
            )

        # 2. 映射 role
        role = KIND_TO_ROLE[msg.kind]

        # 3. 构建 FormattedMessage
        result.append(
            FormattedMessage(
                role=role,
                content=msg.content,
                item_id=msg.item_id,
                source=msg.source,
            )
        )

    return result