from dataclasses import dataclass, field
from typing import Any, List


@dataclass(frozen=True, slots=True)
class ContextItem:
    item_id: str
    kind: str
    content: str
    source: str
    priority: int
    required: bool
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self) -> None:
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content must not be blank")

        if type(self.required) is not bool:
            raise TypeError("required must be a boolean")

        if type(self.token_count) is not int:
            raise TypeError("token_count must be an integer")

        if self.token_count < 0:
            raise ValueError("token_count must be non-negative")


@dataclass(frozen=True, slots=True)
class ContextBudget:
    soft_limit: int
    hard_limit: int
    output_reserve: int
    def __post_init__(self) -> None:
        if type(self.soft_limit) is not int:
            raise TypeError("soft_limit must be an integer")
        if type(self.hard_limit) is not int:
            raise TypeError("hard_limit must be an integer")
        if type(self.output_reserve) is not int:
            raise TypeError("output_reserve must be an integer")

        if self.hard_limit <= 0:
            raise ValueError("hard_limit must be positive")
        if self.soft_limit <= 0:
            raise ValueError("soft_limit must be positive")
        if self.soft_limit > self.hard_limit:
            raise ValueError("soft_limit must not exceed hard_limit")
        if self.output_reserve < 0:
            raise ValueError("output_reserve must be non-negative")
        if self.output_reserve >= self.hard_limit:
            raise ValueError("output_reserve must be less than hard_limit")

@dataclass(frozen=True, slots=True)
class CompiledContext:
    """Compiler 编译结果。

    Attributes:
        selected_items: 最终被选中的上下文项，保持输入顺序。
        dropped_items: 未被选中的 optional 项，保持输入顺序。
        total_input_tokens: selected_items 的 token_count 总和。
        available_input_tokens: 扣除 output_reserve 后的输入预算（hard_limit - output_reserve）。
    """
    selected_items: List[ContextItem]
    dropped_items: List[ContextItem]
    total_input_tokens: int
    available_input_tokens: int

    def __post_init__(self) -> None:
        # 类型检查
        if not isinstance(self.selected_items, list):
            raise TypeError("selected_items must be a list")
        if not isinstance(self.dropped_items, list):
            raise TypeError("dropped_items must be a list")
        if not all(isinstance(item, ContextItem) for item in self.selected_items):
            raise TypeError("selected_items must contain only ContextItem")
        if not all(isinstance(item, ContextItem) for item in self.dropped_items):
            raise TypeError("dropped_items must contain only ContextItem")

        # 不允许有交集
        selected_ids = {item.item_id for item in self.selected_items}
        dropped_ids = {item.item_id for item in self.dropped_items}
        if selected_ids.intersection(dropped_ids):
            raise ValueError(
                "selected_items and dropped_items must not overlap. "
                f"Overlapping IDs: {selected_ids.intersection(dropped_ids)}"
            )

        # 计算值必须匹配
        if self.total_input_tokens != sum(item.token_count for item in self.selected_items):
            raise ValueError(
                f"total_input_tokens ({self.total_input_tokens}) does not match "
                f"sum of selected_items token_count ({sum(item.token_count for item in self.selected_items)})"
            )

        if self.available_input_tokens < 0:
            raise ValueError("available_input_tokens must be non-negative")

        if self.total_input_tokens < 0:
            raise ValueError("total_input_tokens must be non-negative")

        # total_input_tokens 不能超过 available_input_tokens
        if self.total_input_tokens > self.available_input_tokens:
            raise ValueError(
                f"total_input_tokens ({self.total_input_tokens}) exceeds "
                f"available_input_tokens ({self.available_input_tokens})"
            )

@dataclass(frozen=True, slots=True)
class ContextMessage:
    """内部消息信封，provider-neutral。

    这是 Context 层与 Provider 层之间的内部消息表示，
    不是可直接发送给 OpenAI/Anthropic/DashScope 的 API 消息。

    Attributes:
        item_id: 对应的 ContextItem ID，用于追踪。
        kind: 上下文内容类型（如 system、user、retrieval、tool_result），不等同于模型 role。
        source: 内容来源（如 hardcoded、rag、user）。
        content: 消息内容原文，不做任何修改。
    """
    item_id: str
    kind: str
    source: str
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.item_id, str) or not self.item_id.strip():
            raise ValueError("item_id must not be blank")
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("kind must not be blank")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must not be blank")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")

@dataclass(frozen=True, slots=True)
class ContextTrace:
    """上下文编译追踪记录。

    记录 Compiler 的确定性决策结果，作为旁路观测。

    Attributes:
        stage: 产生该 Trace 的阶段，V1 固定为 "compiler"。
        selected_item_ids: 被选中项目的 ID 列表，保持 selected_items 顺序。
        dropped_item_ids: 被淘汰项目的 ID 列表，保持 dropped_items 顺序。
        total_input_tokens: 复制自 CompiledContext.total_input_tokens。
        available_input_tokens: 复制自 CompiledContext.available_input_tokens。
    """
    stage: str
    selected_item_ids: List[str]
    dropped_item_ids: List[str]
    total_input_tokens: int
    available_input_tokens: int

    def __post_init__(self) -> None:
        if self.stage != "compiler":
            raise ValueError(
                f"stage must be 'compiler' in V1, got {self.stage}"
            )
        if not isinstance(self.selected_item_ids, list):
            raise TypeError("selected_item_ids must be a list")
        if not isinstance(self.dropped_item_ids, list):
            raise TypeError("dropped_item_ids must be a list")
        if not all(isinstance(x, str) for x in self.selected_item_ids):
            raise TypeError("selected_item_ids must contain only strings")
        if not all(isinstance(x, str) for x in self.dropped_item_ids):
            raise TypeError("dropped_item_ids must contain only strings")
        if self.total_input_tokens < 0:
            raise ValueError("total_input_tokens must be non-negative")
        if self.available_input_tokens < 0:
            raise ValueError("available_input_tokens must be non-negative")
        if self.total_input_tokens > self.available_input_tokens:
            raise ValueError(
                f"total_input_tokens ({self.total_input_tokens}) exceeds "
                f"available_input_tokens ({self.available_input_tokens})"
            )

@dataclass(frozen=True, slots=True)
class FormattedMessage:
    """OpenAI-compatible 格式化消息。

    包含 Provider 消息数据（role、content）和旁路追踪数据（item_id、source）。

    Attributes:
        role: OpenAI-compatible 消息角色（system/user/assistant）。
        content: 原始消息正文，未经修改。
        item_id: 对应的 ContextItem ID，用于追踪。
        source: 内容来源（如 hardcoded、rag、user）。
    """
    role: str
    content: str
    item_id: str
    source: str

    def __post_init__(self) -> None:
        if self.role not in ("system", "user", "assistant"):
            raise ValueError(
                f"role must be 'system', 'user', or 'assistant', got {self.role}"
            )
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        if not isinstance(self.item_id, str) or not self.item_id.strip():
            raise ValueError("item_id must not be blank")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must not be blank")