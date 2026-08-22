"""Validate executable Context JSONL against the Selector contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from context.budget import BudgetExceededError
from context.selector import select_items
from evals.context.schema import ContextEvalCase


class ContextDatasetError(ValueError):
    """Raised when a Context dataset cannot be parsed or executed."""


def load_cases(path: str | Path) -> list[ContextEvalCase]:
    """Load and schema-validate every non-empty JSONL row."""

    dataset_path = Path(path)
    cases = []
    seen_case_ids: set[str] = set()
    with dataset_path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                case = ContextEvalCase.model_validate(raw)
            except (json.JSONDecodeError, ValidationError) as error:
                raise ContextDatasetError(
                    f"{dataset_path}:{line_number}: invalid case: {error}"
                ) from error

            if case.case_id in seen_case_ids:
                raise ContextDatasetError(
                    f"{dataset_path}:{line_number}: duplicate case_id {case.case_id}"
                )
            seen_case_ids.add(case.case_id)
            cases.append(case)
    return cases


def validate_case(case: ContextEvalCase) -> list[str]:
    """Return contract violations for one already parsed case."""

    items = [item.to_domain() for item in case.items]
    budget = case.budget.to_domain()
    expected = case.expected

    try:
        selected = select_items(items, budget)
    except Exception as error:  # noqa: BLE001 - validator reports exact type
        if expected.outcome != "error":
            return [
                f"{case.case_id}: selector raised {type(error).__name__}"
            ]
        if type(error).__name__ != expected.error_type:
            return [
                f"{case.case_id}: expected {expected.error_type}, "
                f"got {type(error).__name__}"
            ]
        return []

    if expected.outcome == "error":
        return [f"{case.case_id}: expected {expected.error_type}, selector succeeded"]

    selected_ids = [item.item_id for item in selected]
    selected_set = set(selected_ids)
    dropped_ids = [
        item.item_id
        for item in items
        if not item.required and item.item_id not in selected_set
    ]
    errors = []
    if selected_ids != expected.selected_item_ids:
        errors.append(
            f"{case.case_id}: selected IDs differ; "
            f"expected {expected.selected_item_ids}, got {selected_ids}"
        )
    if dropped_ids != expected.dropped_item_ids:
        errors.append(
            f"{case.case_id}: dropped IDs differ; "
            f"expected {expected.dropped_item_ids}, got {dropped_ids}"
        )
    required_ids = {item.item_id for item in items if item.required}
    if not required_ids <= selected_set:
        errors.append(f"{case.case_id}: required item was not selected")
    if selected_set.intersection(dropped_ids):
        errors.append(f"{case.case_id}: selected and dropped IDs overlap")
    return errors


def validate_cases(cases: list[ContextEvalCase]) -> list[str]:
    """Return all Selector contract violations in a dataset."""

    errors = []
    for case in cases:
        errors.extend(validate_case(case))
    return errors


def validate_file(path: str | Path) -> list[str]:
    """Load and validate a JSONL dataset, returning human-readable errors."""

    return validate_cases(load_cases(path))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    try:
        cases = load_cases(args.path)
        errors = validate_cases(cases)
    except ContextDatasetError as error:
        print(f"INVALID: {error}")
        return 1

    if errors:
        print("INVALID")
        print("\n".join(f"- {error}" for error in errors))
        return 1

    print(f"VALID: {len(cases)} Context cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
