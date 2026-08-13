from __future__ import annotations

import os
from types import MappingProxyType
from typing import Any

from openai import OpenAI

from retrieval.context_builder import ContextPrompt
from retrieval.models import RAGAnswer


NO_CONTEXT_ANSWER = "根据现有资料，无法确定答案。"


class DeepSeekGenerator:
    """Generate a cited RAG answer through a DeepSeek-compatible API."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> None:
        if temperature < 0:
            raise ValueError("temperature must be non-negative")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.model = model or os.getenv("LLM_MODEL_ID") or "deepseek-v4-flash"
        self.temperature = temperature
        self.max_tokens = max_tokens
        if client is not None:
            self.client = client
            return

        resolved_api_key = api_key or os.getenv("LLM_API_KEY")
        if not resolved_api_key:
            raise ValueError("LLM_API_KEY is required for DeepSeek generation")
        self.client = OpenAI(
            api_key=resolved_api_key,
            base_url=base_url or os.getenv("LLM_BASE_URL") or "https://api.deepseek.com",
        )

    def answer(self, question: str, context: ContextPrompt) -> RAGAnswer:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a non-blank string")
        if question.strip() != context.question:
            raise ValueError("question does not match the context prompt")
        if not context.selected_results:
            return RAGAnswer(
                answer=NO_CONTEXT_ANSWER,
                contexts=[],
                citations=[],
                metadata=MappingProxyType({"abstained": True, "model": self.model}),
            )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=context.messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=False,
            )
            answer = response.choices[0].message.content
        except Exception as exc:
            raise RuntimeError(f"DeepSeek generation request failed: {exc}") from exc

        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("DeepSeek returned empty answer")
        return RAGAnswer(
            answer=answer.strip(),
            contexts=context.selected_results,
            citations=context.citations,
            metadata=MappingProxyType(
                {"abstained": False, "model": self.model}
            ),
        )
