"""Generic LLM Judge for generated-data quality evaluation.

The judge is intentionally suite-agnostic.  It does not know about RAG,
AIME, Context, ``gold_evidence`` or any other benchmark-specific field.
Suites provide ordinary JSON values and a :class:`JudgeRubric`; adapters can
perform deterministic validation before or after this subjective layer.

Input JSONL rows have this shape::

    {"item_id": "case-1", "candidate": {...},
     "reference": {...}, "context": {...}, "metadata": {...}}

The reference, context and metadata fields are optional.  The LLM is asked to
score only the configured dimensions.  The final decision is derived locally
from the dimension scores, so the judge cannot bypass the configured gates by
returning ``"accept"`` in its response.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Decision = Literal["accept", "needs_review", "reject"]


class JudgeClient(Protocol):
    """Minimal client contract; real and fake LLM clients can both implement it."""

    model: str

    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        ...


class DimensionSpec(BaseModel):
    """One rubric dimension and its numeric range."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    min_score: float = 1.0
    max_score: float = 5.0

    @field_validator("name", "description")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("dimension text must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def validate_range(self) -> "DimensionSpec":
        if self.min_score >= self.max_score:
            raise ValueError("min_score must be smaller than max_score")
        return self


class JudgeRubric(BaseModel):
    """Configurable scoring contract shared by all generated-data suites."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    dimensions: list[DimensionSpec] = Field(min_length=1)
    accept_threshold: float = 4.0
    review_threshold: float = 3.0
    instructions: str = "Score the candidate against the rubric without inventing facts."

    @model_validator(mode="after")
    def validate_rubric(self) -> "JudgeRubric":
        names = [dimension.name for dimension in self.dimensions]
        if len(names) != len(set(names)):
            raise ValueError("rubric dimension names must be unique")
        minimum = max(dimension.min_score for dimension in self.dimensions)
        maximum = min(dimension.max_score for dimension in self.dimensions)
        if not minimum <= self.review_threshold <= self.accept_threshold <= maximum:
            raise ValueError(
                "review_threshold and accept_threshold must fit every dimension range"
            )
        return self


class JudgeItem(BaseModel):
    """One suite-neutral candidate sent to the judge."""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1)
    candidate: Any
    reference: Any | None = None
    context: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("item_id")
    @classmethod
    def reject_blank_item_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("item_id must not be blank")
        return value.strip()


class JudgeScore(BaseModel):
    """Auditable score for one candidate."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    rubric: str
    rubric_version: str
    judge_model: str
    dimension_scores: dict[str, float]
    overall_score: float
    decision: Decision
    reasons: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    raw_response: str


class JudgeBatchReport(BaseModel):
    """Batch artifact with aggregate metrics and per-item evidence."""

    model_config = ConfigDict(extra="forbid")

    rubric: str
    rubric_version: str
    judge_model: str
    created_at: str
    total: int
    decision_counts: dict[str, int]
    dimension_averages: dict[str, float]
    scores: list[JudgeScore]


class JudgeResponseError(ValueError):
    """Raised when a provider response cannot satisfy the rubric contract."""


DEFAULT_RUBRIC = JudgeRubric(
    name="generic-generated-data-quality",
    version="v1",
    dimensions=[
        DimensionSpec(
            name="correctness",
            description="The candidate is factually or logically correct for its task.",
        ),
        DimensionSpec(
            name="relevance",
            description="The candidate directly serves the requested task and scope.",
        ),
        DimensionSpec(
            name="clarity",
            description="The candidate is understandable, unambiguous and well formed.",
        ),
        DimensionSpec(
            name="completeness",
            description="The candidate contains the information needed for its intended use.",
        ),
    ],
    instructions=(
        "Do not reward length by itself. Use the reference and context only as "
        "provided; do not fill missing evidence from memory."
    ),
)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


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
    raise JudgeResponseError(
        f"unsupported judge response type: {type(response).__name__}"
    )


def parse_judge_json(response: Any) -> dict[str, Any]:
    """Parse a JSON object from plain, fenced or wrapped model output."""

    text = _response_text(response).strip()
    if not text:
        raise JudgeResponseError("judge returned an empty response")

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S | re.I)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)

    object_match = re.search(r"\{.*\}", text, re.S)
    if object_match:
        candidates.append(object_match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise JudgeResponseError("judge response does not contain a valid JSON object")


class LLMJudge:
    """Suite-agnostic LLM Judge with locally derived decisions."""

    def __init__(
        self,
        client: JudgeClient,
        rubric: JudgeRubric = DEFAULT_RUBRIC,
        *,
        temperature: float = 0.0,
        max_tokens: int = 1200,
        retries: int = 1,
    ) -> None:
        if retries < 0:
            raise ValueError("retries must be non-negative")
        self.client = client
        self.rubric = rubric
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retries = retries

    def build_messages(self, item: JudgeItem) -> list[dict[str, str]]:
        rubric = [dimension.model_dump() for dimension in self.rubric.dimensions]
        system = (
            "You are an evaluator of generated data, not a generator. "
            "Score only the configured rubric and return one JSON object. "
            "Every dimension score must be numeric and within its declared range. "
            "Do not add markdown or extra top-level fields."
        )
        user = """Evaluate this candidate.

RUBRIC:
{rubric}

INSTRUCTIONS:
{instructions}

ITEM ID:
{item_id}

CANDIDATE:
{candidate}

REFERENCE (optional):
{reference}

CONTEXT (optional):
{context}

METADATA (optional):
{metadata}

Return exactly this JSON shape:
{{
  "dimension_scores": {{"dimension_name": 1}},
  "reasons": ["short evidence-based reason"],
  "strengths": ["..."],
  "weaknesses": ["..."]
}}
""".format(
            rubric=_json_text(rubric),
            instructions=self.rubric.instructions,
            item_id=item.item_id,
            candidate=_json_text(item.candidate),
            reference=_json_text(item.reference),
            context=_json_text(item.context),
            metadata=_json_text(item.metadata),
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def evaluate(self, item: JudgeItem) -> JudgeScore:
        last_error: Exception | None = None
        for _attempt in range(self.retries + 1):
            try:
                response = self.client.invoke(
                    self.build_messages(item),
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                raw_response = _response_text(response)
                payload = parse_judge_json(raw_response)
                return self._score_payload(item, payload, raw_response)
            except (JudgeResponseError, TypeError, ValueError) as error:
                last_error = error
        raise JudgeResponseError(
            f"failed to evaluate {item.item_id}: {last_error}"
        ) from last_error

    def _score_payload(
        self,
        item: JudgeItem,
        payload: dict[str, Any],
        raw_response: str,
    ) -> JudgeScore:
        raw_scores = payload.get("dimension_scores", payload.get("scores"))
        if not isinstance(raw_scores, dict):
            raise JudgeResponseError("judge JSON must contain dimension_scores")

        dimensions = {dimension.name: dimension for dimension in self.rubric.dimensions}
        missing = set(dimensions) - set(raw_scores)
        extra = set(raw_scores) - set(dimensions)
        if missing or extra:
            raise JudgeResponseError(
                f"dimension mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
            )

        scores: dict[str, float] = {}
        for name, dimension in dimensions.items():
            value = raw_scores[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise JudgeResponseError(f"score for {name} must be numeric")
            score = float(value)
            if not dimension.min_score <= score <= dimension.max_score:
                raise JudgeResponseError(
                    f"score for {name} must be between {dimension.min_score} and "
                    f"{dimension.max_score}"
                )
            scores[name] = score

        overall = fmean(scores.values())
        if overall >= self.rubric.accept_threshold:
            decision: Decision = "accept"
        elif overall >= self.rubric.review_threshold:
            decision = "needs_review"
        else:
            decision = "reject"

        def text_list(key: str) -> list[str]:
            value = payload.get(key, [])
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise JudgeResponseError(f"{key} must be a list of strings")
            return value

        return JudgeScore(
            item_id=item.item_id,
            rubric=self.rubric.name,
            rubric_version=self.rubric.version,
            judge_model=getattr(self.client, "model", "unknown"),
            dimension_scores=scores,
            overall_score=overall,
            decision=decision,
            reasons=text_list("reasons"),
            strengths=text_list("strengths"),
            weaknesses=text_list("weaknesses"),
            raw_response=raw_response,
        )

    def evaluate_batch(self, items: Iterable[JudgeItem]) -> JudgeBatchReport:
        scores = [self.evaluate(item) for item in items]
        dimensions = [dimension.name for dimension in self.rubric.dimensions]
        averages = {
            name: fmean(score.dimension_scores[name] for score in scores)
            for name in dimensions
        } if scores else {}
        return JudgeBatchReport(
            rubric=self.rubric.name,
            rubric_version=self.rubric.version,
            judge_model=getattr(self.client, "model", "unknown"),
            created_at=datetime.now(timezone.utc).isoformat(),
            total=len(scores),
            decision_counts=dict(Counter(score.decision for score in scores)),
            dimension_averages=averages,
            scores=scores,
        )


def load_items(path: str | Path) -> list[JudgeItem]:
    """Load suite-neutral candidate rows from JSONL."""

    items: list[JudgeItem] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                items.append(JudgeItem.model_validate(json.loads(line)))
            except Exception as error:  # noqa: BLE001 - add file context
                raise ValueError(f"{path}:{line_number}: invalid judge item: {error}") from error
    return items


def write_jsonl(report: JudgeBatchReport, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(
            json.dumps(score.model_dump(mode="json"), ensure_ascii=False) + "\n"
            for score in report.scores
        ),
        encoding="utf-8",
    )


def _load_rubric(path: Path | None) -> JudgeRubric:
    if path is None:
        return DEFAULT_RUBRIC
    return JudgeRubric.model_validate(json.loads(path.read_text(encoding="utf-8")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rubric", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--retries", type=int, default=1)
    args = parser.parse_args()

    from core.llm_client import MyLLMClient

    rubric = _load_rubric(args.rubric)
    client = MyLLMClient(model=args.model)
    report = LLMJudge(
        client,
        rubric,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        retries=args.retries,
    ).evaluate_batch(load_items(args.input))
    write_jsonl(report, args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(f"judged={report.total} decisions={report.decision_counts}")
    print(f"scores={args.output}")
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
