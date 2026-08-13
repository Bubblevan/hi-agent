from __future__ import annotations

from dataclasses import dataclass
from retrieval.models import RetrievalResult


@dataclass(frozen=True)
class ContextPrompt:
    question: str
    text: str
    selected_results: list[RetrievalResult]
    citations: list[str]
    messages: list[dict[str, str]]


class ContextBuilder:
    """Turn ranked chunks into bounded, numbered evidence for an LLM."""

    SYSTEM_PROMPT = (
        "你是一个严谨的检索增强问答助手。只使用给定资料回答问题；"
        "资料不足时明确说明，不要补造事实。引用资料时使用 [编号]。"
    )

    def __init__(self, *, max_chars: int = 12000, max_chunks: int | None = None):
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        if max_chunks is not None and max_chunks <= 0:
            raise ValueError("max_chunks must be positive")
        self.max_chars = max_chars
        self.max_chunks = max_chunks

    def build(
        self,
        question: str,
        results: list[RetrievalResult],
    ) -> ContextPrompt:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a non-blank string")
        if not isinstance(results, list):
            raise TypeError("results must be a list")

        selected: list[RetrievalResult] = []
        seen: set[str] = set()
        blocks: list[str] = []
        current_length = 0
        for result in results:
            if not isinstance(result, RetrievalResult):
                raise TypeError("results must contain RetrievalResult objects")
            chunk_id = result.chunk.chunk_id
            if chunk_id in seen:
                continue
            if self.max_chunks is not None and len(selected) >= self.max_chunks:
                break

            block = self._format_block(len(selected) + 1, result)
            separator_length = 2 if blocks else 0
            if current_length + separator_length + len(block) > self.max_chars:
                continue
            seen.add(chunk_id)
            selected.append(result)
            blocks.append(block)
            current_length += separator_length + len(block)

        text = "\n\n".join(blocks)
        citations = [result.chunk.chunk_id for result in selected]
        user_content = (
            f"问题：{question.strip()}\n\n"
            "以下是检索到的资料：\n"
            f"{text if text else '（没有检索到相关资料）'}\n\n"
            "请给出简洁回答，并在相关句子后标注 [编号]。"
        )
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        return ContextPrompt(
            question=question.strip(),
            text=text,
            selected_results=selected,
            citations=citations,
            messages=messages,
        )

    @staticmethod
    def _format_block(number: int, result: RetrievalResult) -> str:
        chunk = result.chunk
        heading = f" {chunk.heading_path}" if chunk.heading_path else ""
        return f"[{number}] {chunk.source}{heading}\n{chunk.content}"
