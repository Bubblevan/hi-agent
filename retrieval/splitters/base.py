"""Shared contracts and length accounting for retrieval text splitters."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from retrieval.models import Chunk, Document


@runtime_checkable
class TextSplitter(Protocol):
    def split(self, document: Document) -> list[Chunk]: ...


@runtime_checkable
class TokenCounter(Protocol):
    """Replaceable token-counting strategy used by every splitter."""

    def count(self, text: str) -> int: ...


@dataclass(frozen=True)
class TokenizerTokenCounter:
    """Adapter for a model tokenizer's ``encode`` method.

    The returned count is exact relative to the injected tokenizer. This class
    does not download a tokenizer or assume that a provider's model name maps
    to a locally available vocabulary.
    """

    tokenizer: object
    add_special_tokens: bool = False

    def __post_init__(self) -> None:
        if not callable(getattr(self.tokenizer, "encode", None)):
            raise TypeError("tokenizer must provide a callable encode method")

    def count(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        encode = self.tokenizer.encode
        try:
            tokens = encode(text, add_special_tokens=self.add_special_tokens)
        except TypeError:
            # Some lightweight tokenizer adapters only accept the text value.
            tokens = encode(text)

        try:
            count = len(tokens)
        except TypeError as exc:
            raise TypeError("tokenizer.encode must return a sized sequence") from exc
        if count < 0:
            raise ValueError("tokenizer returned a negative token count")
        return count


_NON_CJK_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\w\s]", re.UNICODE)


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2CEAF
        or 0x30000 <= code <= 0x3134F
    )


@dataclass(frozen=True)
class ApproxTokenCounter:
    """Dependency-free, conservative counter for mixed CJK and Latin text.

    CJK ideographs and punctuation count as one token. Latin/digit runs use a
    four-characters-per-token approximation, with at least one token per run.
    It is deliberately an estimate; callers can inject a model tokenizer via
    the :class:`TokenCounter` protocol without changing splitter logic.
    """

    latin_chars_per_token: int = 4

    def __post_init__(self) -> None:
        if self.latin_chars_per_token <= 0:
            raise ValueError("latin_chars_per_token must be greater than 0")

    def count(self, text: str) -> int:
        if not text:
            return 0

        cjk_count = sum(1 for ch in text if _is_cjk(ch))
        non_cjk = "".join(" " if _is_cjk(ch) else ch for ch in text)
        other_count = 0
        for token in _NON_CJK_TOKEN_RE.findall(non_cjk):
            if token.isalnum() or "_" in token:
                other_count += max(1, math.ceil(len(token) / self.latin_chars_per_token))
            else:
                other_count += 1
        return cjk_count + other_count


DEFAULT_TOKEN_COUNTER = ApproxTokenCounter()


def _approx_token_len(text: str) -> int:
    """Backward-compatible entry point for the default approximate counter."""

    return DEFAULT_TOKEN_COUNTER.count(text)


@dataclass(frozen=True)
class SplitterParams:
    chunk_size: int = 800
    chunk_overlap: int = 120
    token_counter: TokenCounter = field(default=DEFAULT_TOKEN_COUNTER)

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0")
        if self.chunk_overlap < 0:
            raise ValueError("chunk_overlap cannot be negative")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if not callable(getattr(self.token_counter, "count", None)):
            raise TypeError("token_counter must provide a callable count method")
