"""Generate grounded RAG candidates from paged PDF text.

The generator is deliberately separate from validation.  An LLM may propose
questions and answers, but only the deterministic validator can promote them
to frozen benchmark data.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from evals.data_generation.rag_validator import (
    ReviewItem,
    ValidationReport,
    validate_candidates,
)
from evals.rag.runner import _extract_pages
from evals.rag.schema import RAGEvalCase


class CandidateClient(Protocol):
    """Minimal interface needed by the candidate generator."""

    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        ...


SYSTEM_PROMPT = """You generate grounded RAG benchmark candidates from a paged source.
Return JSONL only, one object per line, with these fields:
case_id, suite, source_id, question, answer_type, difficulty,
answerable_from, expected_terms, forbidden_terms, should_abstain, gold_evidence.
gold_evidence must be a list of {page: integer, quote: string} objects.
Every quote must be copied exactly from the supplied page after whitespace
normalization. Use abstention cases only for questions that appear answerable
from the topic but are not actually supported by the supplied source.
Do not invent facts, page numbers, or quotes.
"""


DEFAULT_CANDIDATES_PER_PAGE = (8, 8, 10, 12, 10)


class CandidateParseError(ValueError):
    """Raised when an LLM response is not JSONL candidate data."""


@dataclass(frozen=True)
class GenerationResult:
    """Result of candidate generation and deterministic promotion checks."""

    candidates: tuple[dict[str, Any], ...]
    accepted: tuple[RAGEvalCase, ...]
    review_queue: tuple[ReviewItem, ...]


def build_paged_document(
    pages: list[str],
    *,
    page_numbers: list[int] | None = None,
) -> str:
    """Format pages with explicit markers for use in a generation prompt."""

    if page_numbers is None:
        page_numbers = list(range(1, len(pages) + 1))
    if len(page_numbers) != len(pages):
        raise ValueError("page_numbers must have one number per page")
    if any(page_number < 1 for page_number in page_numbers):
        raise ValueError("page numbers must be positive")
    return "\n\n".join(
        f"=== PAGE {page_number} ===\n{text}"
        for page_number, text in zip(page_numbers, pages)
    )


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        for key in ("output_text", "text", "content"):
            if key in response:
                return _response_text(response[key])
    if isinstance(response, list):
        return "".join(_response_text(item) for item in response)
    for attribute in ("output_text", "text", "content"):
        value = getattr(response, attribute, None)
        if value is not None:
            return _response_text(value)
    raise CandidateParseError(
        f"unsupported LLM response type: {type(response).__name__}"
    )


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if "```" not in stripped:
        return stripped
    chunks = stripped.split("```")
    fenced = [chunk for chunk in chunks[1::2] if chunk.strip()]
    if not fenced:
        return stripped
    first = fenced[0].lstrip()
    if first.startswith("json"):
        first = first[4:].lstrip("\r\n ")
    return first


def parse_jsonl(response: Any) -> list[dict[str, Any]]:
    """Parse JSONL, a JSON array, or a fenced JSONL response."""

    text = _strip_code_fence(_response_text(response))
    if not text:
        raise CandidateParseError("LLM returned an empty candidate response")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None

    if parsed is not None:
        rows = parsed if isinstance(parsed, list) else [parsed]
        if not all(isinstance(row, dict) for row in rows):
            raise CandidateParseError("candidate JSON must contain objects")
        return rows

    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise CandidateParseError(
                f"invalid candidate JSON at response line {line_number}: {error}"
            ) from error
        if not isinstance(row, dict):
            raise CandidateParseError(
                f"response line {line_number} is not a JSON object"
            )
        rows.append(row)
    if not rows:
        raise CandidateParseError("LLM returned no candidate objects")
    return rows


def _prompt_for_page(
    page_number: int,
    page_text: str,
    *,
    source_id: str,
    candidate_count: int,
) -> list[dict[str, str]]:
    user_prompt = (
        f"Source ID: {source_id}\n"
        f"Generate up to {candidate_count} diverse candidates grounded in page "
        f"{page_number}. Include mechanism, fact, table, comparison, and hard "
        "negative cases when the page supports them.\n\n"
        + build_paged_document([page_text], page_numbers=[page_number])
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def generate_candidates(
    client: CandidateClient,
    pages: list[str],
    *,
    source_id: str,
    candidates_per_page: tuple[int, ...] = DEFAULT_CANDIDATES_PER_PAGE,
    temperature: float = 0.2,
    max_tokens: int = 5000,
    thinking_enabled: bool = False,
) -> list[dict[str, Any]]:
    """Generate candidates one page at a time to improve quote grounding."""

    if not source_id.strip():
        raise ValueError("source_id must not be blank")
    if len(candidates_per_page) < len(pages):
        raise ValueError("candidates_per_page must cover every source page")
    if temperature < 0:
        raise ValueError("temperature must be non-negative")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    candidates: list[dict[str, Any]] = []
    for page_number, page_text in enumerate(pages, start=1):
        response = client.invoke(
            _prompt_for_page(
                page_number,
                page_text,
                source_id=source_id,
                candidate_count=candidates_per_page[page_number - 1],
            ),
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={
                "thinking": {
                    "type": "enabled" if thinking_enabled else "disabled"
                }
            },
        )
        for candidate in parse_jsonl(response):
            candidate = dict(candidate)
            candidate.setdefault("source_id", source_id)
            candidates.append(candidate)
    return candidates


def serialize_cases(cases: tuple[RAGEvalCase, ...] | list[RAGEvalCase]) -> str:
    """Serialize accepted cases as compact UTF-8 JSONL."""

    return "".join(
        json.dumps(
            case.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
        for case in cases
    )


def write_cases(path: str | Path, cases: tuple[RAGEvalCase, ...] | list[RAGEvalCase]) -> None:
    """Freeze accepted candidates into a checked-in JSONL file."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_cases(cases), encoding="utf-8")


def write_review_queue(path: str | Path, review_queue: tuple[ReviewItem, ...]) -> None:
    """Write rejected and duplicate candidates for human review."""

    rows = (
        json.dumps(
            {
                "candidate_index": item.candidate_index,
                "candidate": item.candidate,
                "errors": list(item.errors),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
        for item in review_queue
    )
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(rows), encoding="utf-8")


def generate_and_validate(
    client: CandidateClient,
    pages: list[str],
    *,
    source_id: str,
    candidates_per_page: tuple[int, ...] = DEFAULT_CANDIDATES_PER_PAGE,
    thinking_enabled: bool = False,
) -> GenerationResult:
    """Generate, validate, deduplicate, and triage one source."""

    candidates = generate_candidates(
        client,
        pages,
        source_id=source_id,
        candidates_per_page=candidates_per_page,
        thinking_enabled=thinking_enabled,
    )
    report: ValidationReport = validate_candidates(
        candidates,
        pages,
        source_id=source_id,
    )
    return GenerationResult(
        candidates=tuple(candidates),
        accepted=report.accepted,
        review_queue=report.review_queue,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--response",
        type=Path,
        help="parse a saved LLM response instead of making live calls",
    )
    parser.add_argument("--model")
    parser.add_argument(
        "--enable-thinking",
        action="store_true",
        help="enable provider thinking mode; disabled by default for JSON extraction",
    )
    parser.add_argument("--review-output", type=Path)
    args = parser.parse_args()

    pages = _extract_pages(args.source, "pdf")
    if args.response:
        candidates = parse_jsonl(args.response.read_text(encoding="utf-8"))
        report = validate_candidates(candidates, pages, source_id=args.source_id)
        review_queue = report.review_queue
    else:
        from core.llm_client import MyLLMClient

        client = MyLLMClient(model=args.model)
        result = generate_and_validate(
            client,
            pages,
            source_id=args.source_id,
            thinking_enabled=args.enable_thinking,
        )
        report = ValidationReport(result.accepted, result.review_queue)
        review_queue = result.review_queue

    write_cases(args.output, report.accepted)
    if args.review_output:
        write_review_queue(args.review_output, review_queue)
    print(
        f"accepted={len(report.accepted)} review={len(review_queue)} "
        f"output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
