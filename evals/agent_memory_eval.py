from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AgentTraceReport:
    name: str
    metrics: dict[str, float]
    traces_count: int
    failures: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metrics": self.metrics,
            "traces_count": self.traces_count,
            "failures": self.failures,
        }


def load_traces(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    with source.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def _count_tool(turns: list[dict[str, Any]], field: str, tool_name: str) -> int:
    return sum(1 for turn in turns if tool_name in turn.get(field, []))


def _safe_div(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_agent_memory_traces(traces: list[dict[str, Any]]) -> AgentTraceReport:
    expected_add = actual_add = correct_add = 0
    expected_search = actual_search = correct_search = 0
    exact_tool_matches = 0
    total_turns = 0
    stale_memory_uses = 0
    private_leaks = 0
    failures: list[dict[str, Any]] = []

    for trace in traces:
        for index, turn in enumerate(trace.get("turns", [])):
            total_turns += 1
            expected = set(turn.get("expected_tools", []))
            actual = set(turn.get("actual_tools", []))

            expected_add += int("memory.add" in expected)
            actual_add += int("memory.add" in actual)
            correct_add += int("memory.add" in expected and "memory.add" in actual)

            expected_search += int("memory.search" in expected)
            actual_search += int("memory.search" in actual)
            correct_search += int("memory.search" in expected and "memory.search" in actual)

            if expected == actual:
                exact_tool_matches += 1
            else:
                failures.append(
                    {
                        "case_id": trace.get("case_id"),
                        "turn_index": index,
                        "kind": "tool_mismatch",
                        "expected_tools": sorted(expected),
                        "actual_tools": sorted(actual),
                    }
                )

            stale_memory_uses += int(turn.get("used_stale_memory", False))
            private_leaks += int(turn.get("leaked_private_memory", False))

    metrics = {
        "turns": float(total_turns),
        "memory_write_precision": _safe_div(correct_add, actual_add),
        "memory_write_recall": _safe_div(correct_add, expected_add),
        "memory_search_precision": _safe_div(correct_search, actual_search),
        "memory_search_recall": _safe_div(correct_search, expected_search),
        "unnecessary_memory_write_rate": _safe_div(actual_add - correct_add, total_turns),
        "unnecessary_memory_search_rate": _safe_div(actual_search - correct_search, total_turns),
        "tool_call_correctness": _safe_div(exact_tool_matches, total_turns),
        "stale_memory_usage_rate": _safe_div(stale_memory_uses, total_turns),
        "private_memory_leakage_rate": _safe_div(private_leaks, total_turns),
    }
    return AgentTraceReport(
        name="agent_memory_trace",
        metrics=metrics,
        traces_count=len(traces),
        failures=failures,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run agent memory tool-call trace evals.")
    parser.add_argument("--fixture", required=True, help="Path to JSONL trace fixture.")
    args = parser.parse_args()

    report = evaluate_agent_memory_traces(load_traces(args.fixture))
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
