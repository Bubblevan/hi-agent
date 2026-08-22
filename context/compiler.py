# -*- coding: utf-8 -*-
"""上下文编译器模块。

负责调用 Selector 并组织编译结果。
"""

from typing import List

from context.models import ContextBudget, ContextItem, CompiledContext
from context.selector import select_items
from context.budget import calculate_available_input_tokens


def compile_context(
    items: List[ContextItem],
    budget: ContextBudget,
) -> CompiledContext:
    """编译上下文：选择项并报告结果。

    Args:
        items: 候选上下文项列表。
        budget: 上下文预算配置。

    Returns:
        编译结果（CompiledContext）。

    Raises:
        ValueError: 当 item_id 重复时。
        BudgetExceededError: 当 required 项超出硬预算时。
    """
    # 1. 调用 Selector 获得选中的项（保持输入顺序）
    selected = select_items(items, budget)

    # 2. 计算 dropped items：所有不在 selected 中的输入项
    selected_ids = {item.item_id for item in selected}
    dropped = [item for item in items if item.item_id not in selected_ids]

    # 3. 计算 token 统计
    total_tokens = sum(item.token_count for item in selected)
    available = calculate_available_input_tokens(budget)

    # 4. 返回编译结果
    return CompiledContext(
        selected_items=selected,
        dropped_items=dropped,
        total_input_tokens=total_tokens,
        available_input_tokens=available,
    )