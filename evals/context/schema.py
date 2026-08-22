"""Pydantic schema for executable Context evaluation cases.

The schema is the boundary for frozen JSONL data.  It validates shape and
cross-field invariants, while the Selector remains the deterministic oracle
for the expected selection result.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from context.models import ContextBudget, ContextItem


def _validate_unique_ids(value: list[str]) -> list[str]:
    if any(not item_id.strip() for item_id in value):
        raise ValueError("item IDs must not be blank")
    if len(value) != len(set(value)):
        raise ValueError("item IDs must be unique")
    return value


class ContextItemSpec(BaseModel):
    """Serializable ContextItem specification used by the dataset."""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source: str = Field(min_length=1)
    priority: int
    required: bool
    token_count: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("item_id", "kind", "content", "source")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text fields must not be blank")
        return value

    def to_domain(self) -> ContextItem:
        """Convert the serialized spec to the runtime ContextItem model."""

        return ContextItem(**self.model_dump())


class BudgetSpec(BaseModel):
    """Serializable ContextBudget specification."""

    model_config = ConfigDict(extra="forbid")

    soft_limit: int = Field(gt=0)
    hard_limit: int = Field(gt=0)
    output_reserve: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_limits(self) -> "BudgetSpec":
        if self.soft_limit > self.hard_limit:
            raise ValueError("soft_limit must not exceed hard_limit")
        if self.output_reserve >= self.hard_limit:
            raise ValueError("output_reserve must be less than hard_limit")
        return self

    def to_domain(self) -> ContextBudget:
        """Convert the serialized spec to the runtime ContextBudget model."""

        return ContextBudget(**self.model_dump())


class ExpectedSpec(BaseModel):
    """Expected deterministic outcome for one Context case."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["success", "error"] = "success"
    selected_item_ids: list[str] = Field(default_factory=list)
    dropped_item_ids: list[str] = Field(default_factory=list)
    required_answer_terms: list[str] = Field(default_factory=list)
    forbidden_answer_terms: list[str] = Field(default_factory=list)
    error_type: str | None = None

    _unique_selected_ids = field_validator(
        "selected_item_ids", "dropped_item_ids"
    )(_validate_unique_ids)

    @field_validator("required_answer_terms", "forbidden_answer_terms")
    @classmethod
    def validate_terms(cls, value: list[str]) -> list[str]:
        if any(not term.strip() for term in value):
            raise ValueError("answer terms must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("answer terms must be unique")
        return value

    @model_validator(mode="after")
    def validate_outcome_fields(self) -> "ExpectedSpec":
        selected = set(self.selected_item_ids)
        dropped = set(self.dropped_item_ids)
        if selected.intersection(dropped):
            raise ValueError("selected and dropped IDs must not overlap")

        if self.outcome == "success" and self.error_type is not None:
            raise ValueError("success outcome must not define error_type")

        if self.outcome == "error":
            if not self.error_type or not self.error_type.strip():
                raise ValueError("error outcome requires error_type")
            if self.selected_item_ids or self.dropped_item_ids:
                raise ValueError("error outcome must not define selected or dropped IDs")

        return self


class ContextEvalCase(BaseModel):
    """One executable Context dataset row."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    suite: str = Field(min_length=1)
    task: str = Field(min_length=1)
    token_mode: Literal["synthetic", "estimated"] = "synthetic"
    budget: BudgetSpec
    items: list[ContextItemSpec] = Field(min_length=1)
    expected: ExpectedSpec

    @field_validator("case_id", "suite", "task")
    @classmethod
    def reject_blank_case_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("case fields must not be blank")
        return value

    @model_validator(mode="after")
    def validate_expected_ids(self) -> "ContextEvalCase":
        item_ids = {item.item_id for item in self.items}
        if len(item_ids) != len(self.items):
            raise ValueError("items must have unique item_id values")

        expected_ids = set(self.expected.selected_item_ids) | set(
            self.expected.dropped_item_ids
        )
        unknown_ids = expected_ids - item_ids
        if unknown_ids:
            raise ValueError(
                "expected result references unknown item IDs: "
                + ", ".join(sorted(unknown_ids))
            )
        return self


__all__ = [
    "BudgetSpec",
    "ContextEvalCase",
    "ContextItemSpec",
    "ExpectedSpec",
]
