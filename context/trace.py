# -*- coding: utf-8 -*-
"""上下文追踪模块。

记录 Compiler 的确定性决策结果。
"""

from context.models import CompiledContext, ContextTrace


def build_context_trace(compiled: CompiledContext) -> ContextTrace:
    """从 CompiledContext 构建追踪记录。

    Args:
        compiled: 编译后的上下文。

    Returns:
        ContextTrace 对象，包含编译决策的快照。
    """
    return ContextTrace(
        stage="compiler",
        selected_item_ids=[item.item_id for item in compiled.selected_items],
        dropped_item_ids=[item.item_id for item in compiled.dropped_items],
        total_input_tokens=compiled.total_input_tokens,
        available_input_tokens=compiled.available_input_tokens,
    )