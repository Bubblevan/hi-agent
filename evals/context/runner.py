"""Run the Context pipeline against a real OpenAI-compatible LLM."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from context.compiler import compile_context
from context.formatter import format_openai_messages
from context.payload import build_openai_payload
from context.structure import structure_messages
from context.trace import build_context_trace
from core.llm_client import MyLLMClient
from core.llm_result import LLMResult
from evals.context.scorer import score_case
from evals.data_generation.context_validator import load_cases


class MetadataProvider(Protocol):
    model: str

    def invoke_with_metadata(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> LLMResult: ...


METRIC_NAMES = (
    "exact_match",
    "must_select_recall",
    "distractor_exclusion",
    "required_coverage",
    "forbidden_leakage",
    "truncation",
)


def _invoke_provider(
    provider: Any,
    payload: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
) -> LLMResult:
    """Call a metadata-aware provider, with a compatibility fallback."""

    try:
        method = getattr(provider, "invoke_with_metadata", None)
        if method is not None:
            return method(
                payload,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        # This keeps the runner easy to exercise with a tiny fake provider.
        answer = provider.invoke(
            payload,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return LLMResult(
            content=answer,
            model=getattr(provider, "model", "fake-provider"),
            finish_reason="stop",
        )
    except Exception as error:  # noqa: BLE001 - report provider failures
        return LLMResult(
            content=f"provider error: {error}",
            model=getattr(provider, "model", "unknown"),
            error=str(error),
        )


def evaluate_case(
    case: Any,
    provider: Any,
    *,
    repeat: int,
    temperature: float = 0.0,
    max_tokens: int = 256,
) -> dict[str, Any]:
    """Run one case through compile, format, provider, and scorer."""

    started = time.perf_counter()
    try:
        compiled = compile_context(
            [item.to_domain() for item in case.items],
            case.budget.to_domain(),
        )
        trace = build_context_trace(compiled)
        structured = structure_messages(compiled)
        formatted = format_openai_messages(structured)
        payload = build_openai_payload(formatted)
        result = _invoke_provider(
            provider,
            payload,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        scores = score_case(
            case=case.model_dump(),
            actual_selected=trace.selected_item_ids,
            actual_dropped=trace.dropped_item_ids,
            answer=result.content,
            finish_reason=result.finish_reason,
        )
        record: dict[str, Any] = {
            "case_id": case.case_id,
            "repeat": repeat,
            "selected_item_ids": trace.selected_item_ids,
            "dropped_item_ids": trace.dropped_item_ids,
            "answer": result.content,
            "scores": scores,
            "provider_error": result.provider_error,
            "error": result.error,
            "model": result.model,
            "finish_reason": result.finish_reason,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "reasoning_tokens": result.reasoning_tokens,
            "cached_tokens": result.cached_tokens,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        return record
    except Exception as error:  # noqa: BLE001 - keep a failed row in the report
        return {
            "case_id": case.case_id,
            "repeat": repeat,
            "selected_item_ids": [],
            "dropped_item_ids": [],
            "answer": "",
            "scores": None,
            "provider_error": True,
            "error": f"{type(error).__name__}: {error}",
            "model": getattr(provider, "model", "unknown"),
            "finish_reason": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "reasoning_tokens": None,
            "cached_tokens": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }


def _mean(records: list[dict[str, Any]], key: str) -> float | None:
    values = [
        record[key]
        for record in records
        if record.get(key) is not None
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _metric_mean(records: list[dict[str, Any]], metric: str) -> float | None:
    values = [
        record["scores"][metric]
        for record in records
        if record.get("scores") is not None
    ]
    if not values:
        return None
    return round(sum(float(value) for value in values) / len(values), 6)


def build_report(
    fixture: str | Path,
    cases: list[Any],
    attempts: list[dict[str, Any]],
    *,
    repeats: int,
) -> dict[str, Any]:
    """Build a JSON-serializable report with aggregate and raw results."""

    total_attempts = len(attempts)
    provider_errors = sum(
        bool(record.get("provider_error")) for record in attempts
    )
    metrics: dict[str, float | None] = {
        metric: _metric_mean(attempts, metric)
        for metric in METRIC_NAMES
    }
    metrics["provider_error"] = round(
        provider_errors / total_attempts,
        6,
    ) if total_attempts else None

    models = sorted(
        {
            record["model"]
            for record in attempts
            if record.get("model")
        }
    )

    return {
        "schema_version": "context-eval-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixture": str(fixture),
        "case_count": len(cases),
        "repeats": repeats,
        "total_attempts": total_attempts,
        "successful_attempts": total_attempts - provider_errors,
        "models": models,
        "metrics": metrics,
        "operational": {
            "average_latency_ms": _mean(attempts, "latency_ms"),
            "average_prompt_tokens": _mean(attempts, "prompt_tokens"),
            "average_completion_tokens": _mean(attempts, "completion_tokens"),
            "average_reasoning_tokens": _mean(attempts, "reasoning_tokens"),
            "average_cached_tokens": _mean(attempts, "cached_tokens"),
        },
        "results": attempts,
    }


def run_evaluation(
    fixture: str | Path,
    provider: Any,
    *,
    repeats: int = 3,
    temperature: float = 0.0,
    max_tokens: int = 256,
) -> dict[str, Any]:
    """Run every fixture case repeatedly and return the report."""

    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")

    cases = load_cases(fixture)
    attempts = [
        evaluate_case(
            case,
            provider,
            repeat=repeat,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        for repeat in range(1, repeats + 1)
        for case in cases
    ]
    return build_report(fixture, cases, attempts, repeats=repeats)


def write_report(report: dict[str, Any], output: str | Path) -> Path:
    """Persist a report as UTF-8 JSON and return its path."""

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def run_live_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    """Create the configured client and run the live evaluation."""

    api_key = (
        args.api_key
        or os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    base_url = args.base_url or os.getenv("LLM_BASE_URL")
    provider = MyLLMClient(
        model=args.model,
        api_key=api_key,
        base_url=base_url,
        provider="auto",
    )
    report = run_evaluation(
        args.fixture,
        provider,
        repeats=args.repeats,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    output = write_report(report, args.output)
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"report written to {output}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--api-key")
    parser.add_argument("--base-url")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=256)
    args = parser.parse_args()

    try:
        run_live_evaluation(args)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Context Eval failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
