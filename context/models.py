from dataclasses import dataclass, field
from typing import Any


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