# -*- coding: utf-8 -*-
"""上下文选择器模块。

负责在 token 预算内选择上下文中哪些项应该保留。
"""

from typing import List, Set

from context.models import ContextBudget, ContextItem
from context.budget import (
    calculate_available_input_tokens,
    calculate_required_tokens,
    assert_within_budget,
    BudgetExceededError,
)


def _check_duplicate_item_ids(items: List[ContextItem]) -> None:
    """检查 item_id 是否重复，重复则抛出 ValueError。

    Args:
        items: 上下文条目列表。

    Raises:
        ValueError: 当存在重复 item_id 时。
    """
    seen: Set[str] = set()
    duplicates: Set[str] = set()

    for item in items:
        if item.item_id in seen:
            duplicates.add(item.item_id)
        seen.add(item.item_id)

    if duplicates:
        raise ValueError(
            f"duplicate item_id(s) found: {', '.join(sorted(duplicates))}"
        )


def _calculate_optional_selection_target(
    required_tokens: int,
    soft_limit: int,
    available_input: int,
) -> int:
    """计算 optional 可用的最大 token 数。

    selection_target = min(soft_limit, available_input)
    optional_budget = max(0, selection_target - required_tokens)

    Args:
        required_tokens: required 项的总 token 数。
        soft_limit: 软上限。
        available_input: 输入硬上限。

    Returns:
        optional 可用的最大 token 数。
    """
    selection_target = min(soft_limit, available_input)
    return max(0, selection_target - required_tokens)


def _select_optional_items(
    optional_items: List[ContextItem],
    optional_budget: int,
) -> List[ContextItem]:
    """按 priority 从高到低选择 optional 项。

    算法：
    1. 按 priority 降序排序，priority 相同时保持输入顺序。
    2. 依次尝试加入每个 optional，放不下则跳过，继续尝试后续项目。

    Args:
        optional_items: optional 项列表。
        optional_budget: optional 可用的最大 token 数。

    Returns:
        选中的 optional 项列表（按输入顺序）。
    """
    if not optional_items or optional_budget <= 0:
        return []

    # 记录原始索引用于保持稳定排序
    indexed = [(idx, item) for idx, item in enumerate(optional_items)]

    # 按 priority 降序排序，priority 相同时按原始索引（输入顺序）
    indexed.sort(key=lambda x: (-x[1].priority, x[0]))

    selected: List[ContextItem] = []
    remaining_budget = optional_budget

    for idx, item in indexed:
        if item.token_count <= remaining_budget:
            selected.append(item)
            remaining_budget -= item.token_count
        # 否则跳过，继续尝试后面的项目

    # 按原始索引排序，恢复输入顺序
    selected.sort(key=lambda x: optional_items.index(x))

    return selected


def select_items(items: List[ContextItem], budget: ContextBudget) -> List[ContextItem]:
    """在预算内选择上下文项。

    算法（Selector V1）：
    1. 检查 item_id 是否重复，重复则显式失败。
    2. 调用 assert_within_budget()，确认 required 没突破硬预算。
    3. required 项全部保留，不受 priority 影响。
    4. optional 按 priority 从高到低尝试加入。
    5. priority 相同时保持原输入顺序。
    6. 某个 optional 放不下时跳过，继续尝试后面更小的项目。
    7. 最终返回结果仍保持原始输入顺序。

    Args:
        items: 上下文条目列表。
        budget: 上下文预算配置。

    Returns:
        选中的上下文条目列表，保持原始输入顺序。

    Raises:
        ValueError: 当 item_id 重复时。
        BudgetExceededError: 当 required 项超出硬预算时。
    """
    # 1. 检查重复 item_id
    _check_duplicate_item_ids(items)

    # 2. 确认 required 没突破硬预算
    assert_within_budget(items, budget)

    # 3. 分离 required 和 optional
    required_items: List[ContextItem] = []
    optional_items: List[ContextItem] = []

    for item in items:
        if item.required:
            required_items.append(item)
        else:
            optional_items.append(item)

    # 4. 计算预算
    available_input = calculate_available_input_tokens(budget)
    required_tokens = calculate_required_tokens(items)

    # 5. 计算 optional 可用预算
    optional_budget = _calculate_optional_selection_target(
        required_tokens,
        budget.soft_limit,
        available_input,
    )

    # 6. 如果 required 已经超过 soft_limit，丢弃所有 optional
    if optional_budget <= 0:
        return required_items

    # 7. 选择 optional
    selected_optional = _select_optional_items(optional_items, optional_budget)

    # 8. 合并结果，保持原始顺序
    selected_ids = {item.item_id for item in selected_optional}
    result: List[ContextItem] = []

    for item in items:
        if item.required or item.item_id in selected_ids:
            result.append(item)

    return result