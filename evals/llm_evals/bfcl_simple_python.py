"""Run a BFCL v4 single-turn evaluation against an OpenAI-compatible model.

The benchmark functions are supplied by BFCL for every case. We intentionally
call the provider directly instead of using ``MyFunctionCallAgent.run``:
``run`` executes tools and returns only the final text, while BFCL evaluates the
raw tool calls emitted by the model.

This script does three things:

1. Loads BFCL prompts and possible answers when the category has ground truth.
2. Records raw function calls in BFCL JSONL result format.
3. Scores each prediction with BFCL's official AST checker.

It does not execute any benchmark function.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_CATEGORIES = ("simple_python", "multiple", "parallel", "irrelevance")
PROVIDER_TYPE_MAP = {
    "dict": "object",
    "float": "number",
    "tuple": "array",
}
DEFAULT_BFCL_ROOT = (
    PROJECT_ROOT
    / "evals"
    / "llm_evals"
    / "temp_gorilla"
    / "berkeley-function-call-leaderboard"
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _get_field(value: Any, name: str, default: Any = None) -> Any:
    """Read a field from either an SDK object or a plain dictionary."""

    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON on {path}:{line_number}") from error
            if not isinstance(row, dict):
                raise ValueError(f"Expected an object on {path}:{line_number}")
            rows.append(row)
    return rows


def _normalize_schema_types(value: Any) -> Any:
    """Convert BFCL's ``dict`` schema type to JSON Schema's ``object`` type."""

    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            # A BFCL function can itself have a parameter literally named
            # ``type``. In that case the value is a nested schema object, not
            # the schema's type string.
            if key == "type" and isinstance(item, str):
                if item == "any":
                    continue
                normalized[key] = PROVIDER_TYPE_MAP.get(item, item)
            else:
                normalized[key] = _normalize_schema_types(item)
        return normalized
    if isinstance(value, list):
        return [_normalize_schema_types(item) for item in value]
    return value


def build_provider_tools(
    functions: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Build provider tools and map BFCL names to wire-safe function names.

    OpenAI-compatible APIs generally reject dots in function names. BFCL uses
    names such as ``math.factorial``, so the provider receives
    ``math_factorial``. The official checker knows about this convention when
    the scoring profile is an FC model.
    """

    tools: list[dict[str, Any]] = []
    wire_name_by_input: dict[str, str] = {}
    original_by_wire_name: dict[str, str] = {}

    for function in functions:
        original_name = function["name"]
        wire_name = original_name.replace(".", "_")
        previous_original = original_by_wire_name.get(wire_name)
        if previous_original is not None and previous_original != original_name:
            raise ValueError(
                "Function name collision after provider normalization: "
                f"{previous_original!r} and {original_name!r}"
            )

        original_by_wire_name[wire_name] = original_name
        wire_name_by_input[original_name] = wire_name
        wire_name_by_input[wire_name] = wire_name
        parameters = _normalize_schema_types(function.get("parameters", {}))
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": wire_name,
                    "description": function.get("description", ""),
                    "parameters": parameters,
                },
            }
        )

    return tools, wire_name_by_input


def extract_tool_result(
    message: Any,
    wire_name_by_input: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Convert an SDK assistant message into BFCL's ``result`` value."""

    predictions: list[dict[str, Any]] = []
    errors: list[str] = []
    tool_calls = _get_field(message, "tool_calls", []) or []

    for index, tool_call in enumerate(tool_calls):
        function = _get_field(tool_call, "function", {}) or {}
        name = _get_field(function, "name")
        raw_arguments = _get_field(function, "arguments", "{}")

        if not name:
            errors.append(f"tool_call[{index}] has no function name")
            continue

        try:
            arguments = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str)
                else raw_arguments
            )
        except json.JSONDecodeError as error:
            errors.append(f"tool_call[{index}] arguments are not valid JSON: {error}")
            arguments = {}

        if not isinstance(arguments, dict):
            errors.append(f"tool_call[{index}] arguments are not an object")
            arguments = {}

        wire_name = wire_name_by_input.get(name, name)
        predictions.append({wire_name: arguments})

    return predictions, errors


def first_turn_messages(question: Any) -> list[dict[str, Any]]:
    """Extract the first provider message list from BFCL's turn structure."""

    if not isinstance(question, list) or not question:
        raise ValueError("BFCL question must contain at least one turn")
    first_turn = question[0]
    if not isinstance(first_turn, list) or not all(
        isinstance(message, dict) for message in first_turn
    ):
        raise ValueError("BFCL simple_python first turn must be a list of messages")
    return first_turn


def score_prediction(
    prompt: dict[str, Any],
    prediction: list[dict[str, Any]],
    possible_answer: list[dict[str, Any]] | None,
    category: str,
    scoring_profile: str,
) -> dict[str, Any]:
    """Use BFCL's official checker for one supported single-turn case."""

    if category == "irrelevance":
        if prediction:
            return {
                "valid": False,
                "error": ["The model emitted a tool call for an irrelevant request."],
                "error_type": "irrelevance_error:tool_call_emitted",
            }
        return {"valid": True, "error": []}

    if possible_answer is None:
        raise ValueError(f"Ground truth is required for category {category!r}")

    from bfcl_eval.constants.enums import Language
    from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING
    from bfcl_eval.eval_checker.ast_eval.ast_checker import ast_checker

    if scoring_profile not in MODEL_CONFIG_MAPPING:
        available = ", ".join(sorted(MODEL_CONFIG_MAPPING)[:8])
        raise ValueError(
            f"Unknown BFCL scoring profile {scoring_profile!r}. "
            f"Use a registered FC profile, for example: {available}"
        )

    return ast_checker(
        prompt["function"],
        prediction,
        possible_answer,
        Language.PYTHON,
        category,
        scoring_profile,
    )


def _default_output_path(bfcl_root: Path, model_label: str, category: str) -> Path:
    return (
        bfcl_root
        / "result"
        / model_label
        / "non_live"
        / f"BFCL_v4_{category}_result.json"
    )


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bfcl-root", type=Path, default=DEFAULT_BFCL_ROOT)
    parser.add_argument(
        "--category",
        choices=SUPPORTED_CATEGORIES,
        default="simple_python",
        help="BFCL single-turn category to evaluate",
    )
    parser.add_argument("--samples", type=int, default=5, help="0 means all samples")
    parser.add_argument("--model", default=None, help="Provider model; defaults to LLM_MODEL_ID")
    parser.add_argument("--model-label", default="hi-agent-baseline")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument(
        "--scoring-profile",
        default="gpt-4o-2024-11-20-FC",
        help="Registered BFCL FC profile used only for AST name normalization",
    )
    parser.add_argument("--data", type=Path, default=None)
    parser.add_argument("--ground-truth", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    bfcl_root = args.bfcl_root.resolve()
    category = args.category
    data_path = args.data or (
        bfcl_root / "bfcl_eval" / "data" / f"BFCL_v4_{category}.json"
    )
    ground_truth_path = args.ground_truth or (
        bfcl_root
        / "bfcl_eval"
        / "data"
        / "possible_answer"
        / f"BFCL_v4_{category}.json"
    )
    output_path = args.output or _default_output_path(
        bfcl_root, args.model_label, category
    )
    report_path = args.report or PROJECT_ROOT / "artifacts" / f"bfcl-{category}.json"

    prompts = _load_jsonl(data_path)
    if category == "irrelevance":
        ground_truth_by_id: dict[str, list[dict[str, Any]]] = {}
    else:
        ground_truth_rows = _load_jsonl(ground_truth_path)
        ground_truth_by_id = {
            row["id"]: row["ground_truth"] for row in ground_truth_rows
        }

        if len(prompts) != len(ground_truth_rows):
            raise ValueError(
                "Prompt/ground-truth count mismatch: "
                f"{len(prompts)} != {len(ground_truth_rows)}"
            )

    selected = prompts if args.samples == 0 else prompts[: args.samples]

    from core.llm_client import MyLLMClient

    llm = MyLLMClient(model=args.model)
    result_rows: list[dict[str, Any]] = []
    report_rows: list[dict[str, Any]] = []

    for index, prompt in enumerate(selected, start=1):
        case_id = prompt["id"]
        tools, wire_name_by_input = build_provider_tools(prompt["function"])
        started = time.perf_counter()
        prediction: list[dict[str, Any]] = []
        parse_errors: list[str] = []
        provider_error: str | None = None
        content = ""
        finish_reason = None
        usage: dict[str, Any] = {}
        parallel_tool_calls = category == "parallel"

        try:
            request_kwargs: dict[str, Any] = {
                "model": llm.model,
                "messages": first_turn_messages(prompt["question"]),
                "tools": tools,
                "tool_choice": "auto",
                "temperature": args.temperature,
                "max_tokens": args.max_tokens,
            }
            if parallel_tool_calls:
                request_kwargs["parallel_tool_calls"] = True

            response = llm._client.chat.completions.create(**request_kwargs)
            choice = response.choices[0]
            message = choice.message
            prediction, parse_errors = extract_tool_result(message, wire_name_by_input)
            content = _get_field(message, "content", "") or ""
            finish_reason = _get_field(choice, "finish_reason")
            raw_usage = _get_field(response, "usage")
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = _get_field(raw_usage, key)
                if value is not None:
                    usage[key] = value
        except Exception as error:  # Keep one provider failure from hiding other cases.
            provider_error = f"{type(error).__name__}: {error}"

        if provider_error is not None:
            score = {
                "valid": False,
                "error": [provider_error],
                "error_type": "provider_error",
            }
        else:
            try:
                score = score_prediction(
                    prompt,
                    prediction,
                    ground_truth_by_id.get(case_id),
                    category,
                    args.scoring_profile,
                )
            except Exception as error:
                score = {
                    "valid": False,
                    "error": [f"{type(error).__name__}: {error}"],
                    "error_type": "scoring_error",
                }

        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        result_row: dict[str, Any] = {"id": case_id, "result": prediction}
        if parse_errors:
            result_row["inference_log"] = " | ".join(parse_errors)
        if provider_error:
            result_row["inference_log"] = provider_error
        result_rows.append(result_row)

        report_rows.append(
            {
                "id": case_id,
                "index": index,
                "valid": bool(score.get("valid")),
                "prediction": prediction,
                "score": score,
                "content": content,
                "finish_reason": finish_reason,
                "usage": usage,
                "latency_ms": elapsed_ms,
            }
        )
        print(f"[{index}/{len(selected)}] {case_id}: {'PASS' if score.get('valid') else 'FAIL'}")

    _write_jsonl(output_path, result_rows)
    correct = sum(1 for row in report_rows if row["valid"])
    report = {
        "benchmark": f"BFCL v4 {category}",
        "category": category,
        "model": llm.model,
        "model_label": args.model_label,
        "scoring_profile": args.scoring_profile,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "total_samples": len(report_rows),
        "correct_samples": correct,
        "accuracy": correct / len(report_rows) if report_rows else 0.0,
        "result_path": str(output_path),
        "parallel_tool_calls": category == "parallel",
        "cases": report_rows,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Accuracy: {correct}/{len(report_rows)} = {report['accuracy']:.2%}")
    print(f"BFCL result: {output_path}")
    print(f"Eval report: {report_path}")
    return 0 if correct == len(report_rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
