"""Structured metadata returned by an LLM provider call."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LLMResult:
    """Provider response content plus the metadata needed by evals."""

    content: str
    model: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None
    error: str | None = None

    @property
    def provider_error(self) -> bool:
        """Whether the provider call failed before producing a normal answer."""

        return self.error is not None


__all__ = ["LLMResult"]
