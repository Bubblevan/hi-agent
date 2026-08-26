"""Generate and validate original AIME-style mathematical problems.

The LLM proposes problems and worked solutions.  This module only promotes
structurally valid candidates: the answer must be an integer in ``0..999``,
the problem and solution must be non-empty, and duplicate problems are sent to
the generic human-review queue.  Mathematical correctness remains a review
responsibility unless a separate trusted solver is supplied.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class AIMEClient(Protocol):
    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        ...


class AIMECandidate(BaseModel):
    """Schema for one generated AIME-style candidate."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    suite: str = "aime-generated-v1"
    problem: str = Field(min_length=1)
    solution: str = Field(min_length=1)
    answer: int
    topic: str = Field(min_length=1)
    difficulty: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("case_id", "suite", "problem", "solution", "topic", "difficulty")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("AIME text fields must not be blank")
        return value

    @field_validator("answer", mode="before")
    @classmethod
    def reject_boolean_answer(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("AIME answer must be an integer in 0..999")
        return value

    @field_validator("answer")
    @classmethod
    def validate_answer(cls, value: int) -> int:
        if not 0 <= value <= 999:
            raise ValueError("AIME answer must be an integer in 0..999")
        return value

    @property
    def answer_code(self) -> str:
        """Return the canonical three-digit answer used in audit output."""

        return f"{self.answer:03d}"


@dataclass(frozen=True)
class AIMEReviewItem:
    candidate_index: int
    candidate: Any
    errors: tuple[str, ...]


@dataclass(frozen=True)
class AIMEValidationReport:
    accepted: tuple[AIMECandidate, ...]
    review_queue: tuple[AIMEReviewItem, ...]


@dataclass(frozen=True)
class AIMEGenerationResult:
    candidates: tuple[dict[str, Any], ...]
    accepted: tuple[AIMECandidate, ...]
    review_queue: tuple[AIMEReviewItem, ...]


class AIMEParseError(ValueError):
    """Raised when an LLM response is not candidate JSON."""


SYSTEM_PROMPT = """You generate original AIME-style mathematics problems.
Return only a JSON array. Each object must contain:
case_id, problem, solution, answer, topic, difficulty.
The answer must be an integer from 0 through 999, inclusive. Provide a
complete, checkable solution and make the final answer agree with the solution.
Do not copy a known contest problem or mention external sources. Avoid relying
on diagrams or unstated conventions. Generate diverse but self-contained
problems at the requested difficulty.
"""


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
    raise AIMEParseError(f"unsupported response type: {type(response).__name__}")


def parse_candidates(response: Any) -> list[dict[str, Any]]:
    """Parse a JSON array, object, JSONL, or fenced JSON response."""

    text = _response_text(response).strip()
    if not text:
        raise AIMEParseError("LLM returned an empty response")
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        rows = parsed if isinstance(parsed, list) else [parsed]
        if not all(isinstance(row, dict) for row in rows):
            raise AIMEParseError("AIME response must contain JSON objects")
        return rows

    rows = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise AIMEParseError(f"invalid JSON at response line {line_number}: {error}") from error
        if not isinstance(row, dict):
            raise AIMEParseError(f"response line {line_number} is not an object")
        rows.append(row)
    if not rows:
        raise AIMEParseError("LLM returned no AIME candidates")
    return rows


def _prompt(topic: str, count: int, difficulty: str) -> list[dict[str, str]]:
    user = (
        f"Topic: {topic}\nDifficulty: {difficulty}\n"
        f"Generate exactly {count} original problems. Return JSON only."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def generate_candidates(
    client: AIMEClient,
    topics: list[str],
    *,
    count_per_topic: int = 1,
    difficulty: str = "medium",
    temperature: float = 0.4,
    max_tokens: int = 5000,
) -> list[dict[str, Any]]:
    """Ask once per topic so failures and quality can be audited per topic."""

    if not topics or any(not topic.strip() for topic in topics):
        raise ValueError("topics must contain non-blank values")
    if count_per_topic <= 0 or max_tokens <= 0 or temperature < 0:
        raise ValueError("count, max_tokens and temperature have invalid values")
    candidates: list[dict[str, Any]] = []
    for topic in topics:
        response = client.invoke(
            _prompt(topic.strip(), count_per_topic, difficulty),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        candidates.extend(parse_candidates(response))
    return candidates


def validate_candidates(candidates: list[Any]) -> AIMEValidationReport:
    """Schema-validate and deduplicate candidates without claiming math proof."""

    accepted: list[AIMECandidate] = []
    review: list[AIMEReviewItem] = []
    seen_problems: set[str] = set()
    seen_ids: set[str] = set()
    for index, raw in enumerate(candidates, start=1):
        try:
            candidate = (
                raw if isinstance(raw, AIMECandidate) else AIMECandidate.model_validate(raw)
            )
        except (ValidationError, TypeError, ValueError) as error:
            review.append(AIMEReviewItem(index, raw, (f"schema validation failed: {error}",)))
            continue
        problem_key = " ".join(candidate.problem.split()).casefold()
        errors: list[str] = []
        if candidate.case_id in seen_ids:
            errors.append("duplicate case_id")
        if problem_key in seen_problems:
            errors.append("duplicate problem text")
        if errors:
            review.append(AIMEReviewItem(index, candidate.model_dump(mode="json"), tuple(errors)))
            continue
        seen_ids.add(candidate.case_id)
        seen_problems.add(problem_key)
        accepted.append(candidate)
    return AIMEValidationReport(tuple(accepted), tuple(review))


def generate_and_validate(
    client: AIMEClient,
    topics: list[str],
    *,
    count_per_topic: int = 1,
    difficulty: str = "medium",
    temperature: float = 0.4,
    max_tokens: int = 5000,
) -> AIMEGenerationResult:
    candidates = generate_candidates(
        client,
        topics,
        count_per_topic=count_per_topic,
        difficulty=difficulty,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    report = validate_candidates(candidates)
    return AIMEGenerationResult(tuple(candidates), report.accepted, report.review_queue)


def write_cases(path: str | Path, cases: tuple[AIMECandidate, ...] | list[AIMECandidate]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(case.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")) + "\n" for case in cases),
        encoding="utf-8",
    )


def write_review_queue(path: str | Path, queue: tuple[AIMEReviewItem, ...]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(
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
            for item in queue
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", action="append", required=True)
    parser.add_argument("--count-per-topic", type=int, default=1)
    parser.add_argument("--difficulty", default="medium")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--response", type=Path, help="validate a saved response without an LLM call")
    parser.add_argument("--model")
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--max-tokens", type=int, default=5000)
    args = parser.parse_args()

    if args.response:
        candidates = parse_candidates(args.response.read_text(encoding="utf-8"))
    else:
        from core.llm_client import MyLLMClient

        candidates = generate_candidates(
            MyLLMClient(model=args.model),
            args.topic,
            count_per_topic=args.count_per_topic,
            difficulty=args.difficulty,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
    report = validate_candidates(candidates)
    write_cases(args.output, report.accepted)
    write_review_queue(args.review_output, report.review_queue)
    print(f"accepted={len(report.accepted)} review={len(report.review_queue)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
