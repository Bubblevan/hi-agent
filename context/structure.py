# -*- coding: utf-8 -*-
"""消息结构模块。

将 CompiledContext 转换为内部消息序列。
"""

from typing import List

from context.models import CompiledContext, ContextMessage


def structure_messages(compiled: CompiledContext) -> List[ContextMessage]:
    """将 CompiledContext 转换为 ContextMessage 列表。

    Args:
        compiled: 编译后的上下文。

    Returns:
        ContextMessage 列表，保持 selected_items 的顺序。
    """
    return [
        ContextMessage(
            item_id=item.item_id,
            kind=item.kind,
            source=item.source,
            content=item.content,
        )
        for item in compiled.selected_items
    ]