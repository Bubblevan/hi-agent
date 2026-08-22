# -*- coding: utf-8 -*-
"""上下文组装预算计算模块。

本模块提供上下文组装流水线所需的核心预算计算逻辑。
它将"预算是什么"（models.py 中定义的数据结构）与
"如何计算和执行预算约束"（本模块）这两个关注点分离开。
"""

from typing import List

from context.models import ContextBudget, ContextItem


class BudgetExceededError(Exception):
    """当必需上下文条目超出可用 token 预算时抛出的异常。

    这是一个硬错误，而非警告。必需条目必须能放入预算内；
    如果放不下，调用方必须精简条目或提高预算上限。
    """

    def __init__(self, required_tokens: int, available: int, items: List[ContextItem]):
        self.required_tokens = required_tokens
        self.available = available
        self.items = items
        super().__init__(
            f"必需上下文条目超出可用预算："
            f"需要 {required_tokens} 个 token，可用 {available} 个"
        )


def calculate_available_input_tokens(budget: ContextBudget) -> int:
    """计算可用于输入上下文的 token 数量。

    公式：硬上限 - 输出预留，结果最小为 0。

    Args:
        budget: 上下文预算配置。

    Returns:
        可用于输入上下文的最大 token 数。
    """
    return max(0, budget.hard_limit - budget.output_reserve)


def calculate_required_tokens(items: List[ContextItem]) -> int:
    """计算所有必需条目的 token 总数。

    Args:
        items: 上下文条目列表。

    Returns:
        required=True 的条目的 token 总和。
    """
    # 修正：使用 token_count 而不是 tokens
    return sum(item.token_count for item in items if item.required)


def is_within_budget(items: List[ContextItem], budget: ContextBudget) -> bool:
    """检查必需条目是否在可用预算范围内。

    Args:
        items: 上下文条目列表。
        budget: 上下文预算配置。

    Returns:
        若必需 token 数 <= 可用输入 token 数则返回 True，否则返回 False。
    """
    available = calculate_available_input_tokens(budget)
    required = calculate_required_tokens(items)
    return required <= available


def assert_within_budget(items: List[ContextItem], budget: ContextBudget) -> None:
    """断言必需条目在可用预算范围内。

    若必需 token 数超出可用预算，则抛出 BudgetExceededError。

    Args:
        items: 上下文条目列表。
        budget: 上下文预算配置。

    Raises:
        BudgetExceededError: 当必需 token 数超出可用预算时。
    """
    available = calculate_available_input_tokens(budget)
    required = calculate_required_tokens(items)

    if required > available:
        raise BudgetExceededError(required, available, items)