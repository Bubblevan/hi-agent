"""Pairwise LLM evaluation and win-rate reporting.

This module compares two candidates for the same item.  The candidates may be
answers, tool traces, generated benchmark cases, or any other JSON values.
The judge randomizes the displayed order deterministically and maps the result
back to the original ``candidate_a``/``candidate_b`` labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from evals.data_generation.llm_judge import parse_judge_json


Winner = Literal["a", "b", "tie"]


class PairwiseClient(Protocol):
    model: str

    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        ...


class PairwiseRubric(BaseModel):
    """Criteria used to compare two candidates."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    criteria: list[str] = Field(min_length=1)
    instructions: str = "Prefer correctness and task fulfillment over style."

    @field_validator("name", "version", "instructions")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rubric text must not be blank")
        return value


DEFAULT_PAIRWISE_RUBRIC = PairwiseRubric(
    name="generic-pairwise-quality-v1",
    version="1",
    criteria=[
        "correctness",
        "relevance to the task",
        "completeness",
        "clarity",
    ],
)


class PairwiseItem(BaseModel):
    """One comparison row with optional reference/context JSON."""

    model_config = ConfigDict(extra="forbid")

    pair_id: str = Field(min_length=1)
    prompt: Any
    candidate_a: Any
    candidate_b: Any
    reference: Any | None = None
    context: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PairwiseResult(BaseModel):
    """One blind comparison result mapped back to original labels."""

    pair_id: str
    rubric: str
    rubric_version: str
    judge_model: str
    winner: Winner
    rationale: str
    display_a_was_original: bool
    raw_response: dict[str, Any]


class PairwiseReport(BaseModel):
    """Aggregate pairwise results.

    ``a_win_rate`` is tie-adjusted: a tie contributes half a win to each
    candidate.  ``decisive_a_win_rate`` excludes ties and is accompanied by a
    Wilson 95% interval.
    """

    rubric: str
    rubric_version: str
    judge_model: str
    created_at: str
    total_pairs: int
    a_wins: int
    b_wins: int
    ties: int
    a_win_rate: float
    b_win_rate: float
    decisive_a_win_rate: float | None
    decisive_a_win_rate_ci95: tuple[float, float] | None
    results: list[PairwiseResult]


class PairwiseResponseError(ValueError):
    """Raised when the judge response cannot be normalized."""


SYSTEM_PROMPT = """You are a blind pairwise evaluator for generated data.
Compare candidate A and candidate B against the supplied task, reference, and
context. Use the rubric criteria. Do not reward verbosity, formatting, or
position alone. Return exactly one JSON object:
{"winner":"A"|"B"|"tie","rationale":"short explanation"}
"""


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _display_order(pair_id: str, seed: int) -> bool:
    """Return True when original A is shown as display A."""

    digest = hashlib.sha256(f"{seed}:{pair_id}".encode("utf-8")).digest()
    return digest[0] % 2 == 0


def _normalize_winner(value: Any) -> Literal["A", "B", "tie"]:
    normalized = str(value).strip().lower()
    if normalized in {"a", "candidate_a", "candidate a"}:
        return "A"
    if normalized in {"b", "candidate_b", "candidate b"}:
        return "B"
    if normalized in {"tie", "draw", "equal"}:
        return "tie"
    raise PairwiseResponseError(f"invalid winner: {value!r}")


class PairwiseJudge:
    """Run blind pairwise comparisons and derive aggregate win rates."""

    def __init__(
        self,
        client: PairwiseClient,
        rubric: PairwiseRubric = DEFAULT_PAIRWISE_RUBRIC,
        *,
        seed: int = 0,
        temperature: float = 0.0,
        max_tokens: int = 800,
        retries: int = 1,
    ):
        if temperature < 0:
            raise ValueError("temperature must be non-negative")
        if max_tokens <= 0 or retries < 0:
            raise ValueError("max_tokens must be positive and retries non-negative")
        self.client = client
        self.rubric = rubric
        self.seed = seed
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retries = retries

    def build_messages(self, item: PairwiseItem) -> list[dict[str, str]]:
        original_a_first = _display_order(item.pair_id, self.seed)
        display_a = item.candidate_a if original_a_first else item.candidate_b
        display_b = item.candidate_b if original_a_first else item.candidate_a
        user = {
            "pair_id": item.pair_id,
            "task": item.prompt,
            "reference": item.reference,
            "context": item.context,
            "rubric": {
                "criteria": self.rubric.criteria,
                "instructions": self.rubric.instructions,
            },
            "candidate_A": display_a,
            "candidate_B": display_b,
        }
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _json_text(user)},
        ]

    def _evaluate_once(self, item: PairwiseItem) -> PairwiseResult:
        original_a_first = _display_order(item.pair_id, self.seed)
        response = self.client.invoke(
            self.build_messages(item),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        try:
            payload = response if isinstance(response, dict) else parse_judge_json(response)
            if not isinstance(payload, dict):
                raise PairwiseResponseError("pairwise response must be a JSON object")
            display_winner = _normalize_winner(payload.get("winner"))
            rationale = str(payload.get("rationale", "")).strip()
            if not rationale:
                raise PairwiseResponseError("rationale must not be blank")
        except (TypeError, KeyError, ValueError) as error:
            raise PairwiseResponseError(str(error)) from error

        if display_winner == "tie":
            winner: Winner = "tie"
        elif display_winner == "A":
            winner = "a" if original_a_first else "b"
        else:
            winner = "b" if original_a_first else "a"
        return PairwiseResult(
            pair_id=item.pair_id,
            rubric=self.rubric.name,
            rubric_version=self.rubric.version,
            judge_model=getattr(self.client, "model", "unknown"),
            winner=winner,
            rationale=rationale,
            display_a_was_original=original_a_first,
            raw_response=payload,
        )

    def evaluate(self, item: PairwiseItem) -> PairwiseResult:
        last_error: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                return self._evaluate_once(item)
            except PairwiseResponseError as error:
                last_error = error
        raise PairwiseResponseError(f"failed after retries: {last_error}") from last_error

    def evaluate_batch(self, items: list[PairwiseItem]) -> PairwiseReport:
        results = [self.evaluate(item) for item in items]
        a_wins = sum(result.winner == "a" for result in results)
        b_wins = sum(result.winner == "b" for result in results)
        ties = sum(result.winner == "tie" for result in results)
        total = len(results)
        decisive = a_wins + b_wins
        a_rate = (a_wins + ties / 2) / total if total else 0.0
        b_rate = (b_wins + ties / 2) / total if total else 0.0
        decisive_rate = a_wins / decisive if decisive else None
        ci = _wilson_interval(a_wins, decisive) if decisive else None
        return PairwiseReport(
            rubric=self.rubric.name,
            rubric_version=self.rubric.version,
            judge_model=getattr(self.client, "model", "unknown"),
            created_at=_timestamp(),
            total_pairs=total,
            a_wins=a_wins,
            b_wins=b_wins,
            ties=ties,
            a_win_rate=a_rate,
            b_win_rate=b_rate,
            decisive_a_win_rate=decisive_rate,
            decisive_a_win_rate_ci95=ci,
            results=results,
        )


def _wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    if trials <= 0:
        raise ValueError("trials must be positive")
    z = 1.96
    p = successes / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * trials)) / trials) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def load_items(path: str | Path) -> list[PairwiseItem]:
    items: list[PairwiseItem] = []
    for line_number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            items.append(PairwiseItem.model_validate(json.loads(raw)))
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"{path}:{line_number}: invalid pairwise item: {error}") from error
    return items


def write_jsonl(path: str | Path, rows: list[Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=800)
    args = parser.parse_args()

    from core.llm_client import MyLLMClient

    judge = PairwiseJudge(
        MyLLMClient(model=args.model),
        seed=args.seed,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    report = judge.evaluate_batch(load_items(args.input))
    write_jsonl(args.output, [result.model_dump(mode="json") for result in report.results])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(
        f"pairs={report.total_pairs} a_wins={report.a_wins} "
        f"b_wins={report.b_wins} ties={report.ties} "
        f"a_win_rate={report.a_win_rate:.2%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
