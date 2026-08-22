"""Generate executable Context contract cases deterministically.

The generator creates structural cases and applies semantic skins.  It never
asks an LLM to decide the expected selection: ``select_items`` is the oracle.
Use ``python -m evals.data_generation.context_generator`` to print JSONL or
pass ``--output`` to freeze it into a fixture.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from context.budget import BudgetExceededError
from context.selector import select_items
from evals.context.schema import ContextEvalCase


SKINS = (
    {
        "name": "database-migration",
        "task": "Continue the database migration without changing the agreed strategy.",
        "goal": "Continue the database migration.",
        "state": "Dual writes are enabled; historical rows still need backfill.",
        "next": "Backfill historical rows next.",
    },
    {
        "name": "pytest-debugging",
        "task": "Resume the failed pytest debugging task without repeating completed work.",
        "goal": "Resume the pytest debugging task.",
        "state": "The failure is isolated to one assertion; the remaining problem is still open.",
        "next": "Inspect the failing assertion next.",
    },
    {
        "name": "checkpoint-recovery",
        "task": "Recover the interrupted checkpoint while preserving the completed refactor.",
        "goal": "Recover the interrupted checkpoint.",
        "state": "The core refactor is complete; the integration boundary still needs verification.",
        "next": "Verify the integration boundary next.",
    },
    {
        "name": "rag-compaction",
        "task": "Continue the RAG task while preserving the selected evidence and provenance.",
        "goal": "Continue the RAG task.",
        "state": "The selected evidence is available and its source provenance is recorded.",
        "next": "Use the selected evidence with its provenance.",
    },
)

FAMILIES = (
    "required-only",
    "soft-limit",
    "required-over-soft",
    "oversized-optional",
    "priority-order",
    "stable-tie",
    "required-over-hard",
    "no-optional",
)


def _item(
    item_id: str,
    *,
    kind: str,
    content: str,
    source: str,
    priority: int,
    required: bool,
    token_count: int,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "kind": kind,
        "content": content,
        "source": source,
        "priority": priority,
        "required": required,
        "token_count": token_count,
    }


def _scenario(family: str, skin: dict[str, str], variant: int) -> dict[str, Any]:
    """Build one structural scenario before computing its expected result."""

    suffix = f" Variant {variant + 1}."
    goal = skin["goal"] + suffix
    state = skin["state"] + suffix
    next_action = skin["next"] + suffix

    if family == "required-only":
        budget = {"soft_limit": 60, "hard_limit": 100, "output_reserve": 20}
        items = [
            _item("goal", kind="task", content=goal, source="user", priority=100, required=True, token_count=20),
            _item("state", kind="checkpoint", content=state, source="checkpoint", priority=90, required=True, token_count=15),
        ]
    elif family == "soft-limit":
        budget = {"soft_limit": 50, "hard_limit": 100, "output_reserve": 20}
        items = [
            _item("goal", kind="task", content=goal, source="user", priority=100, required=True, token_count=20),
            _item("high_optional", kind="note", content=next_action, source="agent", priority=90, required=False, token_count=20),
            _item("low_optional", kind="tool_result", content="A lower-priority detail that should not consume the soft budget.", source="tool", priority=80, required=False, token_count=15),
        ]
    elif family == "required-over-soft":
        budget = {"soft_limit": 40, "hard_limit": 100, "output_reserve": 20}
        items = [
            _item("goal", kind="task", content=goal, source="user", priority=100, required=True, token_count=35),
            _item("state", kind="checkpoint", content=state, source="checkpoint", priority=90, required=True, token_count=10),
            _item("optional", kind="note", content=next_action, source="agent", priority=80, required=False, token_count=10),
        ]
    elif family == "oversized-optional":
        budget = {"soft_limit": 60, "hard_limit": 100, "output_reserve": 20}
        items = [
            _item("goal", kind="task", content=goal, source="user", priority=100, required=True, token_count=20),
            _item("huge_optional", kind="tool_result", content="A large replayable output that does not fit the remaining optional budget.", source="tool", priority=90, required=False, token_count=50),
            _item("small_optional", kind="note", content=next_action, source="checkpoint", priority=80, required=False, token_count=20),
        ]
    elif family == "priority-order":
        budget = {"soft_limit": 45, "hard_limit": 100, "output_reserve": 20}
        items = [
            _item("goal", kind="task", content=goal, source="user", priority=100, required=True, token_count=15),
            _item("low_priority", kind="note", content="A low-priority background detail.", source="memory", priority=70, required=False, token_count=15),
            _item("high_priority", kind="checkpoint", content=state, source="checkpoint", priority=90, required=False, token_count=15),
            _item("medium_priority", kind="note", content=next_action, source="agent", priority=80, required=False, token_count=15),
        ]
    elif family == "stable-tie":
        budget = {"soft_limit": 50, "hard_limit": 100, "output_reserve": 20}
        items = [
            _item("goal", kind="task", content=goal, source="user", priority=100, required=True, token_count=20),
            _item("first_tie", kind="checkpoint", content="The first equally prioritized checkpoint should win the tie.", source="checkpoint", priority=80, required=False, token_count=20),
            _item("second_tie", kind="checkpoint", content="The second equally prioritized checkpoint should be dropped.", source="checkpoint", priority=80, required=False, token_count=20),
            _item("small_followup", kind="note", content=next_action, source="agent", priority=70, required=False, token_count=10),
        ]
    elif family == "required-over-hard":
        budget = {"soft_limit": 30, "hard_limit": 40, "output_reserve": 10}
        items = [
            _item("goal", kind="task", content=goal, source="user", priority=100, required=True, token_count=20),
            _item("state", kind="checkpoint", content=state, source="checkpoint", priority=100, required=True, token_count=15),
        ]
    elif family == "no-optional":
        budget = {"soft_limit": 40, "hard_limit": 80, "output_reserve": 10}
        items = [
            _item("goal", kind="task", content=goal, source="user", priority=100, required=True, token_count=20),
        ]
    else:
        raise ValueError(f"unknown Context family: {family}")

    return {
        "case_id": f"ctx-generated-{family}-{variant + 1:02d}-{skin['name']}",
        "suite": "context-contract-v2-generated",
        "task": skin["task"] + suffix,
        "token_mode": "synthetic",
        "budget": budget,
        "items": items,
    }


def compute_gold(case: dict[str, Any]) -> dict[str, Any]:
    """Compute expected results from the runtime Selector contract."""

    parsed = ContextEvalCase.model_validate(
        {**case, "expected": {"outcome": "success"}}
    )
    items = [item.to_domain() for item in parsed.items]
    budget = parsed.budget.to_domain()

    try:
        selected = select_items(items, budget)
    except BudgetExceededError as error:
        return {
            "outcome": "error",
            "error_type": type(error).__name__,
        }

    selected_ids = [item.item_id for item in selected]
    selected_set = set(selected_ids)
    dropped_ids = [
        item.item_id
        for item in items
        if not item.required and item.item_id not in selected_set
    ]
    return {
        "outcome": "success",
        "selected_item_ids": selected_ids,
        "dropped_item_ids": dropped_ids,
        "required_answer_terms": [],
        "forbidden_answer_terms": [],
    }


def generate_cases(variants: int = 4) -> list[ContextEvalCase]:
    """Generate ``len(FAMILIES) * variants`` validated executable cases."""

    if variants <= 0:
        raise ValueError("variants must be positive")

    cases = []
    for variant in range(variants):
        skin = SKINS[variant % len(SKINS)]
        for family in FAMILIES:
            scenario = _scenario(family, skin, variant)
            scenario["expected"] = compute_gold(scenario)
            cases.append(ContextEvalCase.model_validate(scenario))
    return cases


def serialize_cases(cases: list[ContextEvalCase]) -> str:
    """Serialize validated cases as compact UTF-8 JSONL."""

    return "".join(
        json.dumps(case.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        + "\n"
        for case in cases
    )


def write_cases(path: str | Path, cases: list[ContextEvalCase]) -> None:
    """Write generated cases to a JSONL file."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_cases(cases), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", type=int, default=4)
    parser.add_argument(
        "--output",
        type=Path,
        help="write JSONL to this path; otherwise print JSONL to stdout",
    )
    args = parser.parse_args()

    cases = generate_cases(args.variants)
    if args.output:
        write_cases(args.output, cases)
        print(f"generated {len(cases)} cases at {args.output}")
    else:
        print(serialize_cases(cases), end="")


if __name__ == "__main__":
    main()
