"""Pydantic schema for grounded RAG evaluation cases.

The schema keeps answer expectations separate from provenance.  A case can
therefore say both *what* an answer must contain and *where* that answer must
be grounded.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GoldEvidence(BaseModel):
    """One human-verifiable evidence quote from a source page."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    quote: str = Field(min_length=1)

    @field_validator("quote")
    @classmethod
    def reject_blank_quote(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence quote must not be blank")
        return value


class RAGEvalCase(BaseModel):
    """One executable grounded-RAG benchmark row."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    suite: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answer_type: Literal["fact", "mechanism", "comparison", "table", "abstention"]
    difficulty: Literal["easy", "medium", "hard"]
    answerable_from: str = Field(min_length=1)
    expected_terms: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    should_abstain: bool = False
    gold_evidence: list[GoldEvidence] = Field(default_factory=list)

    @field_validator("case_id", "suite", "source_id", "question", "answerable_from")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("case text fields must not be blank")
        return value

    @field_validator("expected_terms", "forbidden_terms")
    @classmethod
    def validate_terms(cls, value: list[str]) -> list[str]:
        if any(not term.strip() for term in value):
            raise ValueError("answer terms must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("answer terms must be unique")
        return value

    @model_validator(mode="after")
    def validate_grounding_contract(self) -> "RAGEvalCase":
        if self.should_abstain:
            if self.answer_type != "abstention":
                raise ValueError("abstention cases must use answer_type=abstention")
            if self.expected_terms:
                raise ValueError("abstention cases must not require answer terms")
            if self.gold_evidence:
                raise ValueError("abstention cases must not define positive evidence")
            if self.answerable_from != "not_answerable":
                raise ValueError(
                    "abstention cases must use answerable_from=not_answerable"
                )
            return self

        if self.answer_type == "abstention":
            raise ValueError("only abstention cases may use answer_type=abstention")
        if not self.gold_evidence:
            raise ValueError("answerable cases require at least one gold_evidence quote")
        if self.answerable_from == "not_answerable":
            raise ValueError("answerable cases cannot use answerable_from=not_answerable")
        return self


__all__ = ["GoldEvidence", "RAGEvalCase"]
